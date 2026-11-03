import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from limit_upcoming.handoff_guard import HandoffGuard
from limit_upcoming.models import UsageSnapshot, UsageTier, UsageWindow


class TestHandoffGuard(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo_p = Path(self.tmpdir)

        # Init git repo
        subprocess.run(["git", "init"], cwd=str(self.repo_p), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(self.repo_p), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(self.repo_p), capture_output=True, check=True)
        (self.repo_p / "main.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "main.py"], cwd=str(self.repo_p), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.repo_p), capture_output=True, check=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("limit_upcoming.handoff_guard.probe_usage")
    def test_guard_safe_tier(self, mock_probe):
        mock_probe.return_value = UsageSnapshot(
            provider="codex",
            detection_mode="local_passive_0token",
            effective_used_percent=70.0,
            tier=UsageTier.SAFE,
        )

        guard = HandoffGuard(repo_dir=self.repo_p, warning_threshold=88.0, critical_threshold=93.0)
        code, out_p, manifest, snapshot = guard.check_and_act()

        self.assertEqual(code, 0)
        self.assertIsNone(out_p)
        self.assertIsNone(manifest)
        self.assertEqual(snapshot.tier, UsageTier.SAFE)

    @patch("limit_upcoming.handoff_guard.probe_usage")
    def test_guard_warning_tier_creates_draft(self, mock_probe):
        mock_probe.return_value = UsageSnapshot(
            provider="codex",
            detection_mode="local_passive_0token",
            effective_used_percent=90.0,
            tier=UsageTier.WARNING_PRE_LIMIT,
        )

        guard = HandoffGuard(repo_dir=self.repo_p, warning_threshold=88.0, critical_threshold=93.0)
        code, out_p, manifest, snapshot = guard.check_and_act(goal="Refactor checkpoint")

        self.assertEqual(code, 1)
        self.assertIsNotNone(out_p)
        self.assertTrue(out_p.exists())
        self.assertEqual(out_p.name, "latest-draft")
        self.assertIsNotNone(manifest)
        self.assertIn("PRE-LIMIT DRAFT", manifest.notes)

    @patch("limit_upcoming.handoff_guard.probe_usage")
    def test_guard_critical_tier_creates_final_bundle(self, mock_probe):
        mock_probe.return_value = UsageSnapshot(
            provider="codex",
            detection_mode="local_passive_0token",
            effective_used_percent=96.0,
            tier=UsageTier.CRITICAL_HANDOFF,
        )

        guard = HandoffGuard(repo_dir=self.repo_p, warning_threshold=88.0, critical_threshold=93.0)
        code, out_p, manifest, snapshot = guard.check_and_act(goal="Urgent handoff")

        self.assertEqual(code, 2)
        self.assertIsNotNone(out_p)
        self.assertTrue(out_p.exists())
        self.assertTrue(out_p.name.startswith("bundle-"))
        self.assertIsNotNone(manifest)
        self.assertIn("CRITICAL HANDOFF", manifest.notes)


if __name__ == "__main__":
    unittest.main()
