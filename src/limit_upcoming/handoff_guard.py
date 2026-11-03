from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from limit_upcoming.bundle_generator import LocalBundleGenerator
from limit_upcoming.models import BundleManifest, UsageSnapshot, UsageTier
from limit_upcoming.usage_probe import probe_usage


class HandoffGuard:
    """Monitors usage thresholds and orchestrates pre-limit draft and critical handoff bundles."""

    def __init__(
        self,
        repo_dir: Optional[Path] = None,
        warning_threshold: float = 88.0,
        critical_threshold: float = 93.0,
        provider: str = "auto",
        codex_file: Optional[Path] = None,
        claude_cache: Optional[Path] = None,
    ):
        self.repo_dir = (repo_dir or Path.cwd()).resolve()
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.provider = provider
        self.codex_file = codex_file
        self.claude_cache = claude_cache
        self.generator = LocalBundleGenerator(repo_dir=self.repo_dir)

    def check_and_act(
        self,
        goal: str = "Work in progress checkpoint",
        notes: Optional[str] = None,
        verify_commands: Optional[List[str]] = None,
        verify_timeout: int = 30,
        exec_adapter: Optional[str] = None,
        force_bundle: bool = False,
    ) -> Tuple[int, Optional[Path], Optional[BundleManifest], UsageSnapshot]:
        """Returns (exit_code, bundle_path, manifest, usage_snapshot).

        exit_code semantics:
          0 = SAFE or WATCH (no bundle generated unless force_bundle=True)
          1 = WARNING_PRE_LIMIT (draft bundle generated at .handoff/latest-draft)
          2 = CRITICAL_HANDOFF (final bundle generated at .handoff/bundle-<ts>)
        """
        snapshot = probe_usage(
            provider=self.provider,
            codex_file=self.codex_file,
            claude_cache=self.claude_cache,
        )

        eff = snapshot.effective_used_percent

        if force_bundle:
            out_p, manifest = self.generator.generate_bundle(
                goal=goal,
                notes=notes,
                verify_commands=verify_commands,
                verify_timeout=verify_timeout,
                usage_snapshot=snapshot,
            )
            self._maybe_exec_adapter(exec_adapter, out_p)
            return 2, out_p, manifest, snapshot

        # Tier 0 / Tier 1 check
        if eff is None or snapshot.stale or eff < self.warning_threshold:
            return 0, None, None, snapshot

        elif self.warning_threshold <= eff < self.critical_threshold:
            # Stage draft bundle into .handoff/latest-draft
            draft_dir = self.repo_dir / ".handoff" / "latest-draft"
            if draft_dir.exists():
                import shutil
                shutil.rmtree(draft_dir, ignore_errors=True)
            draft_dir.mkdir(parents=True, exist_ok=True)

            out_p, manifest = self.generator.generate_bundle(
                goal=goal,
                notes=f"[PRE-LIMIT DRAFT at {eff}%] {notes or ''}".strip(),
                verify_commands=verify_commands,
                verify_timeout=verify_timeout,
                usage_snapshot=snapshot,
                output_dir=draft_dir,
            )
            return 1, out_p, manifest, snapshot

        else:
            # eff >= critical_threshold
            out_p, manifest = self.generator.generate_bundle(
                goal=goal,
                notes=f"[CRITICAL HANDOFF at {eff}%] {notes or ''}".strip(),
                verify_commands=verify_commands,
                verify_timeout=verify_timeout,
                usage_snapshot=snapshot,
            )
            self._maybe_exec_adapter(exec_adapter, out_p)
            return 2, out_p, manifest, snapshot

    def _maybe_exec_adapter(self, exec_adapter: Optional[str], bundle_path: Path) -> None:
        if not exec_adapter:
            return
        bundle_md = bundle_path / "HANDOFF_BUNDLE.md"
        cmd = exec_adapter.format(
            bundle_dir=str(bundle_path),
            bundle_md=str(bundle_md),
        )
        try:
            print(f"[limit-upcoming] Executing selected handoff adapter: {cmd}")
            subprocess.run(cmd, shell=True, check=False)
        except Exception as e:
            print(f"[limit-upcoming] Failed to execute adapter: {e}")
