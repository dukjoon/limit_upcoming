from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from limit_upcoming.models import (
    BundleManifest,
    ExcludedFile,
    IncludedFile,
    UsageSnapshot,
    VerificationRecord,
)

# Sensitive or dangerous file patterns to exclude by default
DEFAULT_SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "*credential*",
    "*secret*",
    "*token*",
    ".git/*",
    ".handoff/*",
]


def is_pattern_match(rel_path: str, patterns: List[str]) -> bool:
    name = Path(rel_path).name.lower()
    norm = rel_path.replace("\\", "/").lower()
    for pat in patterns:
        pat_lower = pat.lower()
        if fnmatch.fnmatch(norm, pat_lower) or fnmatch.fnmatch(name, pat_lower):
            return True
    return False


def is_binary_file(file_path: Path) -> bool:
    """Check if file is binary by looking for null bytes in the first 8KB."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return True
            # Attempt utf-8 decoding
            chunk.decode("utf-8")
            return False
    except UnicodeDecodeError:
        return True
    except Exception:
        return True


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class LocalBundleGenerator:
    """Deterministic local evidence bundle generator (0-token offline collection)."""

    def __init__(
        self,
        repo_dir: Optional[Path] = None,
        max_file_bytes: int = 102400,  # 100 KB
        secret_patterns: Optional[List[str]] = None,
    ):
        self.repo_dir = (repo_dir or Path.cwd()).resolve()
        self.max_file_bytes = max_file_bytes
        self.secret_patterns = secret_patterns or DEFAULT_SECRET_PATTERNS

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)

    def is_git_repo(self) -> bool:
        code, out, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return code == 0 and out.strip() == "true"

    def get_repo_info(self) -> Dict[str, Any]:
        if not self.is_git_repo():
            return {
                "is_git_repo": False,
                "commit": None,
                "branch": None,
                "status_short": None,
            }

        _, commit, _ = self._run_git(["rev-parse", "HEAD"])
        _, branch, _ = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        _, status_short, _ = self._run_git(["status", "--short"])

        return {
            "is_git_repo": True,
            "commit": commit.strip() if commit else "initial",
            "branch": branch.strip() if branch else "unknown",
            "status_short": status_short.strip(),
        }

    def collect_diffs(self) -> Tuple[str, str]:
        """Returns (unstaged_diff, staged_diff)."""
        _, unstaged, _ = self._run_git(["diff"])
        _, staged, _ = self._run_git(["diff", "--cached"])
        return unstaged, staged

    def collect_untracked_files(self) -> List[str]:
        """Collect list of untracked files respecting .gitignore."""
        code, out, _ = self._run_git(["ls-files", "--others", "--exclude-standard", "-z"])
        if code != 0 or not out:
            return []
        items = [p for p in out.split("\0") if p]
        return items

    def run_verification_command(
        self, command: str, timeout_sec: int = 30
    ) -> VerificationRecord:
        start_t = time.perf_counter()
        env_meta = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cwd": str(self.repo_dir),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            res = subprocess.run(
                command,
                cwd=str(self.repo_dir),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            dur = (time.perf_counter() - start_t) * 1000.0
            return VerificationRecord(
                command=command,
                exit_code=res.returncode,
                timed_out=False,
                duration_ms=round(dur, 2),
                stdout=res.stdout,
                stderr=res.stderr,
                environment=env_meta,
            )
        except subprocess.TimeoutExpired as e:
            dur = (time.perf_counter() - start_t) * 1000.0
            stdout_txt = e.stdout.decode("utf-8", errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr_txt = e.stderr.decode("utf-8", errors="ignore") if isinstance(e.stderr, bytes) else (e.stderr or "")
            return VerificationRecord(
                command=command,
                exit_code=-1,
                timed_out=True,
                duration_ms=round(dur, 2),
                stdout=stdout_txt,
                stderr=stderr_txt + f"\n[TIMED OUT after {timeout_sec}s]",
                environment=env_meta,
            )
        except Exception as e:
            dur = (time.perf_counter() - start_t) * 1000.0
            return VerificationRecord(
                command=command,
                exit_code=-1,
                timed_out=False,
                duration_ms=round(dur, 2),
                stdout="",
                stderr=str(e),
                environment=env_meta,
            )

    def generate_bundle(
        self,
        goal: str,
        notes: Optional[str] = None,
        verify_commands: Optional[List[str]] = None,
        verify_timeout: int = 30,
        usage_snapshot: Optional[UsageSnapshot] = None,
        output_dir: Optional[Path] = None,
    ) -> Tuple[Path, BundleManifest]:
        start_time = time.perf_counter()
        created_iso = datetime.now(timezone.utc).isoformat()

        # Output bundle path
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if output_dir is None:
            out_path = self.repo_dir / ".handoff" / f"bundle-{ts}"
        else:
            out_path = output_dir.resolve()

        patches_dir = out_path / "patches"
        untracked_dir = out_path / "untracked_files"
        patches_dir.mkdir(parents=True, exist_ok=True)
        untracked_dir.mkdir(parents=True, exist_ok=True)

        repo_info = self.get_repo_info()
        unstaged_diff, staged_diff = self.collect_diffs()

        included_files: List[IncludedFile] = []
        excluded_files: List[ExcludedFile] = []
        untracked_contents: Dict[str, str] = {}

        # Save diffs
        if unstaged_diff:
            p_unstaged = patches_dir / "unstaged.diff"
            p_unstaged.write_text(unstaged_diff, encoding="utf-8")
            included_files.append(
                IncludedFile(
                    path="patches/unstaged.diff",
                    size_bytes=len(unstaged_diff.encode("utf-8")),
                    sha256=hashlib.sha256(unstaged_diff.encode("utf-8")).hexdigest(),
                    category="unstaged_diff",
                )
            )

        if staged_diff:
            p_staged = patches_dir / "staged.diff"
            p_staged.write_text(staged_diff, encoding="utf-8")
            included_files.append(
                IncludedFile(
                    path="patches/staged.diff",
                    size_bytes=len(staged_diff.encode("utf-8")),
                    sha256=hashlib.sha256(staged_diff.encode("utf-8")).hexdigest(),
                    category="staged_diff",
                )
            )

        # Inspect untracked files
        raw_untracked = self.collect_untracked_files()
        for rel_str in raw_untracked:
            # Don't capture .handoff output directory itself
            if rel_str.startswith(".handoff/") or rel_str == ".handoff":
                continue

            full_p = self.repo_dir / rel_str
            if not full_p.exists() or not full_p.is_file():
                continue

            size = full_p.stat().st_size

            # Check 1: Secret pattern
            if is_pattern_match(rel_str, self.secret_patterns):
                excluded_files.append(
                    ExcludedFile(
                        path=rel_str,
                        size_bytes=size,
                        reason="secret_pattern",
                    )
                )
                continue

            # Check 2: Size limit
            if size > self.max_file_bytes:
                excluded_files.append(
                    ExcludedFile(
                        path=rel_str,
                        size_bytes=size,
                        reason="size_limit_exceeded",
                    )
                )
                continue

            # Check 3: Binary
            if is_binary_file(full_p):
                excluded_files.append(
                    ExcludedFile(
                        path=rel_str,
                        size_bytes=size,
                        reason="binary_or_non_utf8",
                    )
                )
                continue

            # Valid untracked text file -> include
            sha = compute_sha256(full_p)
            dest_copy = untracked_dir / rel_str
            dest_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full_p, dest_copy)

            included_files.append(
                IncludedFile(
                    path=rel_str,
                    size_bytes=size,
                    sha256=sha,
                    category="untracked",
                )
            )

            try:
                untracked_contents[rel_str] = full_p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                untracked_contents[rel_str] = f"[Error reading file: {e}]"

        # Run verification commands if any
        verif_records: List[VerificationRecord] = []
        if verify_commands:
            for cmd in verify_commands:
                cmd_clean = cmd.strip()
                if cmd_clean:
                    v_res = self.run_verification_command(cmd_clean, timeout_sec=verify_timeout)
                    verif_records.append(v_res)

        # Build Markdown Handoff Document
        md_content = self._build_handoff_markdown(
            goal=goal,
            notes=notes,
            repo_info=repo_info,
            usage_snapshot=usage_snapshot,
            unstaged_diff=unstaged_diff,
            staged_diff=staged_diff,
            untracked_contents=untracked_contents,
            excluded_files=excluded_files,
            verification_records=verif_records,
            created_at=created_iso,
        )

        bundle_md_path = out_path / "HANDOFF_BUNDLE.md"
        bundle_md_path.write_text(md_content, encoding="utf-8")

        # Measure duration and total bytes
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        total_bytes = sum(f.stat().st_size for f in out_path.glob("**/*") if f.is_file())

        manifest = BundleManifest(
            version="0.1.0",
            created_at=created_iso,
            repository=repo_info,
            goal=goal,
            notes=notes,
            generation_duration_ms=round(duration_ms, 2),
            total_bundle_bytes=total_bytes,
            usage_snapshot=usage_snapshot.to_dict() if usage_snapshot else None,
            included_files=[f.to_dict() for f in included_files],
            excluded_files=[f.to_dict() for f in excluded_files],
            verification_records=[v.to_dict() for v in verif_records],
        )

        manifest_path = out_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

        return out_path, manifest

    def _build_handoff_markdown(
        self,
        goal: str,
        notes: Optional[str],
        repo_info: Dict[str, Any],
        usage_snapshot: Optional[UsageSnapshot],
        unstaged_diff: str,
        staged_diff: str,
        untracked_contents: Dict[str, str],
        excluded_files: List[ExcludedFile],
        verification_records: List[VerificationRecord],
        created_at: str,
    ) -> str:
        lines: List[str] = []
        lines.append("# Handoff Evidence Bundle")
        lines.append(f"- **Created At**: `{created_at}`")
        lines.append(f"- **Git Branch**: `{repo_info.get('branch')}` | **Commit**: `{repo_info.get('commit')}`")
        if usage_snapshot:
            lines.append(
                f"- **Usage State**: `{usage_snapshot.provider}` | Effective Used: `{usage_snapshot.effective_used_percent}%` | Tier: `{usage_snapshot.tier.value}`"
            )
        lines.append("")

        lines.append("## 1. Goal & Context")
        lines.append(f"**Target Goal**:\n{goal}\n")
        if notes:
            lines.append(f"**Additional Notes / In-flight Tasks**:\n{notes}\n")

        lines.append("## 2. Working Tree Changes")
        if unstaged_diff:
            lines.append("### Unstaged Modifications (`git diff`)\n```diff")
            lines.append(unstaged_diff.rstrip())
            lines.append("```\n")
        else:
            lines.append("*No unstaged modifications on tracked files.*\n")

        if staged_diff:
            lines.append("### Staged Modifications (`git diff --cached`)\n```diff")
            lines.append(staged_diff.rstrip())
            lines.append("```\n")

        if untracked_contents:
            lines.append("### Untracked New Files (Complete Contents)")
            for path, content in untracked_contents.items():
                ext = Path(path).suffix.lstrip(".") or "text"
                lines.append(f"#### File: `{path}`\n```{ext}")
                lines.append(content.rstrip())
                lines.append("```\n")
        else:
            lines.append("*No untracked text files captured.*\n")

        if excluded_files:
            lines.append("### Excluded Files (Not captured in bundle)")
            lines.append("| Path | Size (bytes) | Reason |")
            lines.append("| :--- | :--- | :--- |")
            for ef in excluded_files:
                lines.append(f"| `{ef.path}` | {ef.size_bytes} | `{ef.reason}` |")
            lines.append("")

        lines.append("## 3. Verification Command Outputs")
        if verification_records:
            for vr in verification_records:
                status_str = "PASS (exit 0)" if vr.exit_code == 0 else f"FAIL (exit {vr.exit_code})"
                if vr.timed_out:
                    status_str += " [TIMED OUT]"
                lines.append(f"### Command: `{vr.command}`")
                lines.append(f"- **Result**: `{status_str}` | **Duration**: `{vr.duration_ms} ms`")
                if vr.stdout.strip():
                    lines.append("#### stdout\n```text")
                    lines.append(vr.stdout.rstrip())
                    lines.append("```")
                if vr.stderr.strip():
                    lines.append("#### stderr\n```text")
                    lines.append(vr.stderr.rstrip())
                    lines.append("```")
                lines.append("")
        else:
            lines.append("*No verification commands executed.*\n")

        lines.append("## 4. Resumption Instructions for Next Agent")
        lines.append("1. Review the **Target Goal** and in-flight notes above.")
        lines.append("2. Examine all working tree changes (unstaged, staged, untracked).")
        lines.append("3. Review any failing verification commands to continue fixing the code.")
        lines.append("4. Resume implementation without starting from scratch.")

        return "\n".join(lines)
