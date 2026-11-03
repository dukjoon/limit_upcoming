from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from limit_upcoming.bundle_generator import LocalBundleGenerator
from limit_upcoming.handoff_guard import HandoffGuard
from limit_upcoming.usage_probe import probe_usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limit-upcoming",
        description="Local Evidence Bundle Generator and Proactive Usage Limit Handoff Tool",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. probe
    probe_parser = subparsers.add_parser("probe", help="Check local 0-token usage metrics")
    probe_parser.add_argument(
        "--provider",
        choices=["auto", "codex", "claude"],
        default="auto",
        help="Target provider probe (default: auto)",
    )
    probe_parser.add_argument("--codex-file", type=Path, help="Explicit path to Codex session jsonl")
    probe_parser.add_argument("--claude-cache", type=Path, help="Explicit path to Claude statusline cache json")
    probe_parser.add_argument("--compact", action="store_true", help="Print single-line compact summary")
    probe_parser.add_argument("--json", action="store_true", help="Output full JSON snapshot")

    # 2. bundle
    bundle_parser = subparsers.add_parser("bundle", help="Generate local evidence bundle immediately")
    bundle_parser.add_argument("--goal", required=True, help="Target task goal description")
    bundle_parser.add_argument("--notes", help="Current in-flight notes or unfinished tasks")
    bundle_parser.add_argument(
        "--verify-cmd",
        action="append",
        dest="verify_cmds",
        help="Optional verification command to run and record (can be repeated)",
    )
    bundle_parser.add_argument(
        "--verify-timeout",
        type=int,
        default=30,
        help="Timeout in seconds for verification commands (default: 30)",
    )
    bundle_parser.add_argument("--out-dir", type=Path, help="Custom output directory")
    bundle_parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=102400,
        help="Max file size in bytes for untracked text inclusion (default: 102400 [100KB])",
    )

    # 3. guard
    guard_parser = subparsers.add_parser("guard", help="Check threshold and conditionally stage or finalize bundle")
    guard_parser.add_argument("--goal", default="In-progress work checkpoint", help="Task goal description")
    guard_parser.add_argument("--notes", help="Current notes / in-flight edits")
    guard_parser.add_argument(
        "--verify-cmd",
        action="append",
        dest="verify_cmds",
        help="Verification command to execute if bundling is triggered",
    )
    guard_parser.add_argument(
        "--warning-threshold",
        type=float,
        default=88.0,
        help="Threshold percent to trigger draft bundle staging (default: 88.0)",
    )
    guard_parser.add_argument(
        "--critical-threshold",
        type=float,
        default=93.0,
        help="Threshold percent to freeze edits and finalize handoff (default: 93.0)",
    )
    guard_parser.add_argument(
        "--provider",
        choices=["auto", "codex", "claude"],
        default="auto",
        help="Usage probe provider",
    )
    guard_parser.add_argument("--adapter", help="Optional command to execute on critical handoff (e.g., 'open {bundle_md}')")
    guard_parser.add_argument("--force", action="store_true", help="Force critical bundle creation regardless of usage")

    # 4. hook-statusline
    hook_parser = subparsers.add_parser(
        "hook-statusline",
        help="Pipe utility for Claude Code statusline to cache JSON locally without token consumption",
    )
    hook_parser.add_argument(
        "--cache-file",
        type=Path,
        default=Path.home() / ".cache" / "limit_upcoming" / "claude_status.json",
        help="Target cache file path",
    )
    hook_parser.add_argument("--forward-cmd", help="Optional command to forward stdin to")

    return parser


def run_probe(args: argparse.Namespace) -> int:
    snapshot = probe_usage(
        provider=args.provider,
        codex_file=args.codex_file,
        claude_cache=args.claude_cache,
    )

    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.compact:
        eff_str = f"{snapshot.effective_used_percent}%" if snapshot.effective_used_percent is not None else "N/A"
        print(
            f"[{snapshot.provider}] Used: {eff_str} | Tier: {snapshot.tier.value} | Action: {snapshot.recommended_action}"
        )
        return 0

    # Normal text output
    print("=== limit-upcoming: Local Usage Probe ===")
    print(f"Provider:        {snapshot.provider}")
    print(f"Detection Mode:  {snapshot.detection_mode}")
    print(f"Effective Used:  {snapshot.effective_used_percent}%")
    if snapshot.primary_window:
        print(
            f"Primary Window:  {snapshot.primary_window.used_percent}% ({snapshot.primary_window.window_minutes}m), resets_at={snapshot.primary_window.resets_at}"
        )
    if snapshot.secondary_window:
        print(
            f"Secondary Window:{snapshot.secondary_window.used_percent}% ({snapshot.secondary_window.window_minutes}m), resets_at={snapshot.secondary_window.resets_at}"
        )
    if snapshot.context_used_percent is not None:
        print(f"Context Window:  {snapshot.context_used_percent}% used")
    print(f"Tier:            {snapshot.tier.value}")
    print(f"Recommendation:  {snapshot.recommended_action}")
    if snapshot.snapshot_age_s is not None:
        print(f"Snapshot Age:    {snapshot.snapshot_age_s}s (stale={snapshot.stale})")

    return 0


def run_bundle(args: argparse.Namespace) -> int:
    generator = LocalBundleGenerator(max_file_bytes=args.max_file_bytes)
    snapshot = probe_usage()

    print(f"[limit-upcoming] Collecting local evidence bundle for goal: '{args.goal}'...")
    out_dir, manifest = generator.generate_bundle(
        goal=args.goal,
        notes=args.notes,
        verify_commands=args.verify_cmds,
        verify_timeout=args.verify_timeout,
        usage_snapshot=snapshot,
        output_dir=args.out_dir,
    )

    print(f"[limit-upcoming] Bundle generated successfully at: {out_dir}")
    print(f"- Bundle MD:     {out_dir / 'HANDOFF_BUNDLE.md'}")
    print(f"- Manifest:      {out_dir / 'manifest.json'}")
    print(f"- Duration:      {manifest.generation_duration_ms} ms")
    print(f"- Total Bytes:   {manifest.total_bundle_bytes} bytes")
    print(f"- Included Files:{len(manifest.included_files)}")
    print(f"- Excluded Files:{len(manifest.excluded_files)}")
    if manifest.verification_records:
        print(f"- Verifications: {len(manifest.verification_records)} command(s) recorded")

    return 0


def run_guard(args: argparse.Namespace) -> int:
    guard = HandoffGuard(
        warning_threshold=args.warning_threshold,
        critical_threshold=args.critical_threshold,
        provider=args.provider,
    )

    code, out_p, manifest, snapshot = guard.check_and_act(
        goal=args.goal,
        notes=args.notes,
        verify_commands=args.verify_cmds,
        exec_adapter=args.adapter,
        force_bundle=args.force,
    )

    eff_str = f"{snapshot.effective_used_percent}%" if snapshot.effective_used_percent is not None else "N/A"

    if code == 0:
        print(f"[limit-upcoming guard] Usage is normal ({eff_str}). Continue work.")
        return 0
    elif code == 1:
        print(
            f"[limit-upcoming guard] WARNING: Usage ({eff_str}) >= {args.warning_threshold}%. Staged draft bundle at: {out_p}"
        )
        print("Recommendation: Finish in-flight single file edits cleanly. Avoid starting new multi-file changes.")
        return 1
    elif code == 2:
        print(f"[limit-upcoming guard] CRITICAL: Usage ({eff_str}) reached handoff limit! Handoff bundle created at: {out_p}")
        print("Recommendation: FREEZE all code modifications. Hand off to the next agent using the bundle above.")
        return 2

    return 0


def run_hook_statusline(args: argparse.Namespace) -> int:
    input_bytes = sys.stdin.buffer.read()
    if input_bytes:
        try:
            target_p = args.cache_file
            target_p.parent.mkdir(parents=True, exist_ok=True)
            tmp_p = target_p.with_suffix(".tmp")
            tmp_p.write_bytes(input_bytes)
            tmp_p.replace(target_p)
        except Exception as e:
            sys.stderr.write(f"[limit-upcoming hook] Failed to cache statusline JSON: {e}\n")

    if args.forward_cmd:
        import subprocess
        proc = subprocess.Popen(
            args.forward_cmd,
            shell=True,
            stdin=subprocess.PIPE,
        )
        proc.communicate(input=input_bytes)
        return proc.returncode

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 1

    if args.subcommand == "probe":
        return run_probe(args)
    elif args.subcommand == "bundle":
        return run_bundle(args)
    elif args.subcommand == "guard":
        return run_guard(args)
    elif args.subcommand == "hook-statusline":
        return run_hook_statusline(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
