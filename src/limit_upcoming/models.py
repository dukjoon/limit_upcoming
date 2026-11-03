from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class UsageTier(str, Enum):
    SAFE = "SAFE"                       # < 80%
    WATCH = "WATCH"                     # 80% - 87%
    WARNING_PRE_LIMIT = "WARNING_PRE_LIMIT"  # 88% - 92%
    CRITICAL_HANDOFF = "CRITICAL_HANDOFF"    # >= 93%
    UNKNOWN = "UNKNOWN"                 # Detection not available / stale


@dataclass
class UsageWindow:
    used_percent: float
    window_minutes: int
    resets_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UsageSnapshot:
    provider: str
    detection_mode: str  # e.g., "local_passive_0token", "cache_file", "unsupported"
    primary_window: Optional[UsageWindow] = None
    secondary_window: Optional[UsageWindow] = None
    effective_used_percent: Optional[float] = None
    context_used_percent: Optional[float] = None
    tier: UsageTier = UsageTier.UNKNOWN
    recommended_action: str = "CONTINUE"
    snapshot_age_s: Optional[float] = None
    stale: bool = False
    raw_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["tier"] = self.tier.value
        return res


@dataclass
class ExcludedFile:
    path: str
    size_bytes: int
    reason: str  # "secret_pattern", "binary_or_non_utf8", "size_limit_exceeded"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IncludedFile:
    path: str
    size_bytes: int
    sha256: str
    category: str  # "untracked", "staged_diff", "unstaged_diff"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationRecord:
    command: str
    exit_code: int
    timed_out: bool
    duration_ms: float
    stdout: str
    stderr: str
    environment: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BundleManifest:
    version: str
    created_at: str
    repository: Dict[str, Any]
    goal: str
    notes: Optional[str]
    generation_duration_ms: float
    total_bundle_bytes: int
    usage_snapshot: Optional[Dict[str, Any]] = None
    included_files: List[Dict[str, Any]] = field(default_factory=list)
    excluded_files: List[Dict[str, Any]] = field(default_factory=list)
    verification_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
