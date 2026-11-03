import json
import tempfile
import time
import unittest
from pathlib import Path

from limit_upcoming.models import UsageTier
from limit_upcoming.usage_probe import (
    AdaptiveCheckDecider,
    ClaudeLocalProbe,
    CodexLocalProbe,
    determine_action,
    determine_tier,
)


class TestUsageProbe(unittest.TestCase):
    def test_determine_tier_and_action(self):
        self.assertEqual(determine_tier(75.0), UsageTier.SAFE)
        self.assertEqual(determine_action(UsageTier.SAFE), "CONTINUE")

        self.assertEqual(determine_tier(82.5), UsageTier.WATCH)
        self.assertEqual(determine_action(UsageTier.WATCH), "KEEP_EDITS_ATOMIC")

        self.assertEqual(determine_tier(90.0), UsageTier.WARNING_PRE_LIMIT)
        self.assertEqual(determine_action(UsageTier.WARNING_PRE_LIMIT), "WRAP_UP_CURRENT_EDIT_AND_DRAFT_BUNDLE")

        self.assertEqual(determine_tier(95.0), UsageTier.CRITICAL_HANDOFF)
        self.assertEqual(determine_action(UsageTier.CRITICAL_HANDOFF), "FREEZE_EDITS_AND_BUNDLE")

        self.assertEqual(determine_tier(None), UsageTier.UNKNOWN)
        self.assertEqual(determine_tier(95.0, stale=True), UsageTier.UNKNOWN)
        self.assertEqual(determine_action(UsageTier.UNKNOWN), "MANUAL_CHECKPOINT_RECOMMENDED")

    def test_codex_probe_parsing_with_null_and_weekly_limits(self):
        """Simulates real Codex JSONL where the last line has primary: null (subagent turn)
        and an earlier line contains valid primary (95%) and secondary (98%).
        """
        now = int(time.time())
        events = [
            # Event 1: Valid previous turn
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"input_tokens": 1000, "output_tokens": 200},
                        "last_token_usage": {"total_tokens": 500},
                        "model_context_window": 200000,
                    },
                    "rate_limits": {
                        "primary": {"used_percent": 95.0, "window_minutes": 300, "resets_at": now + 3600},
                        "secondary": {"used_percent": 98.0, "window_minutes": 10080, "resets_at": now + 86400},
                    },
                },
            },
            # Event 2: Subagent turn with null primary
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"input_tokens": 1200, "output_tokens": 250},
                        "last_token_usage": {"total_tokens": 250},
                        "model_context_window": 200000,
                    },
                    "rate_limits": {
                        "primary": None,
                        "secondary": None,
                    },
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = Path(tmpdir) / "rollout-test.jsonl"
            with open(session_file, "w", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")

            probe = CodexLocalProbe()
            snapshot = probe.probe(specific_file=session_file)

            self.assertEqual(snapshot.provider, "codex")
            self.assertIsNotNone(snapshot.primary_window)
            self.assertEqual(snapshot.primary_window.used_percent, 95.0)
            self.assertIsNotNone(snapshot.secondary_window)
            self.assertEqual(snapshot.secondary_window.used_percent, 98.0)
            # Effective used percent should be max(95.0, 98.0) = 98.0
            self.assertEqual(snapshot.effective_used_percent, 98.0)
            self.assertEqual(snapshot.tier, UsageTier.CRITICAL_HANDOFF)
            self.assertEqual(snapshot.recommended_action, "FREEZE_EDITS_AND_BUNDLE")
            self.assertFalse(snapshot.stale)

    def test_codex_probe_stale_detection(self):
        """If resets_at is in the past, snapshot should be marked stale."""
        now = int(time.time())
        ev = {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "primary": {"used_percent": 95.0, "window_minutes": 300, "resets_at": now - 100},
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = Path(tmpdir) / "rollout-stale.jsonl"
            session_file.write_text(json.dumps(ev) + "\n", encoding="utf-8")

            probe = CodexLocalProbe()
            snapshot = probe.probe(specific_file=session_file)
            self.assertTrue(snapshot.stale)
            self.assertEqual(snapshot.tier, UsageTier.UNKNOWN)

    def test_claude_probe_parsing(self):
        now = int(time.time())
        status_data = {
            "context_window": {"used_percentage": 45.0},
            "rate_limits": {
                "five_hour": {"used_percentage": 89.0, "resets_at": now + 7200},
                "seven_day": {"used_percentage": 50.0, "resets_at": now + 500000},
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "claude_status.json"
            cache_file.write_text(json.dumps(status_data), encoding="utf-8")

            probe = ClaudeLocalProbe(cache_file=cache_file)
            snapshot = probe.probe()

            self.assertEqual(snapshot.provider, "claude")
            self.assertEqual(snapshot.effective_used_percent, 89.0)
            self.assertEqual(snapshot.context_used_percent, 45.0)
            self.assertEqual(snapshot.tier, UsageTier.WARNING_PRE_LIMIT)
            self.assertEqual(snapshot.recommended_action, "WRAP_UP_CURRENT_EDIT_AND_DRAFT_BUNDLE")

    def test_adaptive_check_decider(self):
        decider = AdaptiveCheckDecider()
        self.assertFalse(decider.should_check(50.0, edits_since_last_check=4))
        self.assertTrue(decider.should_check(50.0, edits_since_last_check=10))

        self.assertFalse(decider.should_check(80.0, edits_since_last_check=2))
        self.assertTrue(decider.should_check(80.0, edits_since_last_check=3))

        self.assertTrue(decider.should_check(90.0, edits_since_last_check=1))
        self.assertTrue(decider.should_check(95.0, edits_since_last_check=0))


if __name__ == "__main__":
    unittest.main()
