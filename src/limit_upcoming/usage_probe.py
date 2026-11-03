from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from limit_upcoming.models import UsageSnapshot, UsageTier, UsageWindow


def determine_tier(effective_percent: Optional[float], stale: bool = False) -> UsageTier:
    if effective_percent is None or stale:
        return UsageTier.UNKNOWN
    if effective_percent < 80.0:
        return UsageTier.SAFE
    elif effective_percent < 88.0:
        return UsageTier.WATCH
    elif effective_percent < 93.0:
        return UsageTier.WARNING_PRE_LIMIT
    else:
        return UsageTier.CRITICAL_HANDOFF


def determine_action(tier: UsageTier) -> str:
    if tier == UsageTier.SAFE:
        return "CONTINUE"
    elif tier == UsageTier.WATCH:
        return "KEEP_EDITS_ATOMIC"
    elif tier == UsageTier.WARNING_PRE_LIMIT:
        return "WRAP_UP_CURRENT_EDIT_AND_DRAFT_BUNDLE"
    elif tier == UsageTier.CRITICAL_HANDOFF:
        return "FREEZE_EDITS_AND_BUNDLE"
    return "MANUAL_CHECKPOINT_RECOMMENDED"


class CodexLocalProbe:
    """Reads OpenAI Codex CLI local session JSONL files (0-token, offline)."""

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or (Path.home() / ".codex" / "sessions")

    def find_latest_session_file(self) -> Optional[Path]:
        if not self.sessions_dir.exists():
            return None
        jsonl_files = list(self.sessions_dir.glob("*/*/*/*.jsonl"))
        if not jsonl_files:
            # Fallback recursive glob
            jsonl_files = list(self.sessions_dir.glob("**/*.jsonl"))
        if not jsonl_files:
            return None
        return max(jsonl_files, key=lambda f: f.stat().st_mtime)

    def scan_file_for_rate_limits(
        self, file_path: Path, max_bytes: int = 262144
    ) -> Optional[Dict[str, Any]]:
        """Read backward from end of file to find the latest valid rate_limits and token usage."""
        if not file_path.exists():
            return None

        file_size = file_path.stat().st_size
        if file_size == 0:
            return None

        bytes_to_read = min(file_size, max_bytes)
        with open(file_path, "rb") as f:
            f.seek(file_size - bytes_to_read)
            chunk = f.read(bytes_to_read)

        lines = chunk.decode("utf-8", errors="ignore").splitlines()
        # Scan backward
        latest_info: Optional[Dict[str, Any]] = None
        latest_rate_limits: Optional[Dict[str, Any]] = None

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            # Codex schema: {"type": "event_msg", "payload": {"type": "token_count", "info": ..., "rate_limits": ...}}
            payload = data.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "token_count":
                continue

            if latest_info is None and "info" in payload:
                latest_info = payload.get("info")

            rl = payload.get("rate_limits")
            if latest_rate_limits is None and isinstance(rl, dict):
                primary = rl.get("primary")
                secondary = rl.get("secondary")
                if primary is not None or secondary is not None:
                    latest_rate_limits = rl

            if latest_info is not None and latest_rate_limits is not None:
                break

        if latest_rate_limits is None and latest_info is None:
            return None

        return {
            "info": latest_info,
            "rate_limits": latest_rate_limits,
            "mtime": file_path.stat().st_mtime,
        }

    def probe(self, specific_file: Optional[Path] = None) -> UsageSnapshot:
        target_file = specific_file or self.find_latest_session_file()
        if not target_file:
            return UsageSnapshot(
                provider="codex",
                detection_mode="local_passive_0token",
                tier=UsageTier.UNKNOWN,
                recommended_action=determine_action(UsageTier.UNKNOWN),
            )

        data = self.scan_file_for_rate_limits(target_file)
        if not data:
            return UsageSnapshot(
                provider="codex",
                detection_mode="local_passive_0token",
                tier=UsageTier.UNKNOWN,
                recommended_action=determine_action(UsageTier.UNKNOWN),
            )

        rl = data.get("rate_limits") or {}
        info = data.get("info") or {}
        mtime = data.get("mtime", time.time())
        age_s = max(0.0, time.time() - mtime)

        primary_win: Optional[UsageWindow] = None
        secondary_win: Optional[UsageWindow] = None
        p_raw = rl.get("primary")
        s_raw = rl.get("secondary")

        now = int(time.time())
        stale = False

        if isinstance(p_raw, dict) and "used_percent" in p_raw:
            p_resets_at = p_raw.get("resets_at")
            primary_win = UsageWindow(
                used_percent=float(p_raw["used_percent"]),
                window_minutes=int(p_raw.get("window_minutes", 300)),
                resets_at=p_resets_at,
            )
            if p_resets_at and p_resets_at < now:
                stale = True

        if isinstance(s_raw, dict) and "used_percent" in s_raw:
            s_resets_at = s_raw.get("resets_at")
            secondary_win = UsageWindow(
                used_percent=float(s_raw["used_percent"]),
                window_minutes=int(s_raw.get("window_minutes", 10080)),
                resets_at=s_resets_at,
            )
            if s_resets_at and s_resets_at < now:
                stale = True

        # Calculate effective used percent: max of primary and secondary
        candidates: List[float] = []
        if primary_win:
            candidates.append(primary_win.used_percent)
        if secondary_win:
            candidates.append(secondary_win.used_percent)

        effective_pct = max(candidates) if candidates else None

        # Context window usage calculation
        context_pct: Optional[float] = None
        context_window = info.get("model_context_window")
        last_usage = info.get("last_token_usage") or {}
        last_tokens = last_usage.get("total_tokens")
        if context_window and last_tokens and context_window > 0:
            context_pct = round((last_tokens / context_window) * 100.0, 2)

        tier = determine_tier(effective_pct, stale=stale)
        action = determine_action(tier)

        return UsageSnapshot(
            provider="codex",
            detection_mode="local_passive_0token",
            primary_window=primary_win,
            secondary_window=secondary_win,
            effective_used_percent=effective_pct,
            context_used_percent=context_pct,
            tier=tier,
            recommended_action=action,
            snapshot_age_s=round(age_s, 1),
            stale=stale,
            raw_data=rl,
        )


class ClaudeLocalProbe:
    """Reads Claude Code cached statusline or hook JSON (0-token, experimental)."""

    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or (
            Path.home() / ".cache" / "limit_upcoming" / "claude_status.json"
        )

    def probe(self) -> UsageSnapshot:
        if not self.cache_file.exists():
            return UsageSnapshot(
                provider="claude",
                detection_mode="cache_file_not_found",
                tier=UsageTier.UNKNOWN,
                recommended_action=determine_action(UsageTier.UNKNOWN),
            )

        try:
            mtime = self.cache_file.stat().st_mtime
            age_s = max(0.0, time.time() - mtime)
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return UsageSnapshot(
                provider="claude",
                detection_mode="cache_file_invalid",
                tier=UsageTier.UNKNOWN,
                recommended_action=determine_action(UsageTier.UNKNOWN),
            )

        rl = data.get("rate_limits") or {}
        five_h = rl.get("five_hour") or {}
        seven_d = rl.get("seven_day") or {}
        ctx = data.get("context_window") or {}

        primary_win: Optional[UsageWindow] = None
        secondary_win: Optional[UsageWindow] = None
        now = int(time.time())
        stale = False

        if "used_percentage" in five_h:
            p_resets_at = five_h.get("resets_at")
            primary_win = UsageWindow(
                used_percent=float(five_h["used_percentage"]),
                window_minutes=300,
                resets_at=p_resets_at,
            )
            if p_resets_at and p_resets_at < now:
                stale = True

        if "used_percentage" in seven_d:
            s_resets_at = seven_d.get("resets_at")
            secondary_win = UsageWindow(
                used_percent=float(seven_d["used_percentage"]),
                window_minutes=10080,
                resets_at=s_resets_at,
            )
            if s_resets_at and s_resets_at < now:
                stale = True

        candidates: List[float] = []
        if primary_win:
            candidates.append(primary_win.used_percent)
        if secondary_win:
            candidates.append(secondary_win.used_percent)

        effective_pct = max(candidates) if candidates else None
        context_pct = float(ctx.get("used_percentage")) if "used_percentage" in ctx else None

        tier = determine_tier(effective_pct, stale=stale)
        action = determine_action(tier)

        return UsageSnapshot(
            provider="claude",
            detection_mode="cache_file_0token",
            primary_window=primary_win,
            secondary_window=secondary_win,
            effective_used_percent=effective_pct,
            context_used_percent=context_pct,
            tier=tier,
            recommended_action=action,
            snapshot_age_s=round(age_s, 1),
            stale=stale,
            raw_data=data,
        )


def probe_usage(
    provider: str = "auto",
    codex_file: Optional[Path] = None,
    claude_cache: Optional[Path] = None,
) -> UsageSnapshot:
    """Probe local usage snapshot. Zero-token, offline."""
    if provider == "codex":
        return CodexLocalProbe().probe(specific_file=codex_file)
    elif provider == "claude":
        return ClaudeLocalProbe(cache_file=claude_cache).probe()
    elif provider == "auto":
        # Check codex first
        codex_probe = CodexLocalProbe()
        snapshot = codex_probe.probe(specific_file=codex_file)
        if snapshot.tier != UsageTier.UNKNOWN and snapshot.effective_used_percent is not None:
            return snapshot

        # Check claude next
        claude_probe = ClaudeLocalProbe(cache_file=claude_cache)
        c_snapshot = claude_probe.probe()
        if c_snapshot.tier != UsageTier.UNKNOWN and c_snapshot.effective_used_percent is not None:
            return c_snapshot

        # Fallback to whatever codex found even if UNKNOWN
        return snapshot

    return UsageSnapshot(
        provider=provider,
        detection_mode="unsupported",
        tier=UsageTier.UNKNOWN,
        recommended_action=determine_action(UsageTier.UNKNOWN),
    )


class AdaptiveCheckDecider:
    """Determines whether an active check is justified based on edit count and last known usage."""

    @staticmethod
    def should_check(last_known_pct: Optional[float], edits_since_last_check: int) -> bool:
        if last_known_pct is None:
            return edits_since_last_check >= 5
        if last_known_pct < 70.0:
            return edits_since_last_check >= 10
        elif last_known_pct < 85.0:
            return edits_since_last_check >= 3
        elif last_known_pct < 92.0:
            return edits_since_last_check >= 1
        return True
