import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limit_upcoming.bundle_generator import LocalBundleGenerator


class TestBundleGenerator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo_p = Path(self.tmpdir)

        # Initialize temporary git repository
        self._git(["init"])
        self._git(["config", "user.name", "Test User"])
        self._git(["config", "user.email", "test@example.com"])

        # Base file
        (self.repo_p / "base.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        (self.repo_p / "staged_file.py").write_text("# initial staged file\n", encoding="utf-8")
        self._git(["add", "base.py", "staged_file.py"])
        self._git(["commit", "-m", "Initial commit"])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git(self, args):
        return subprocess.run(
            ["git"] + args,
            cwd=str(self.repo_p),
            capture_output=True,
            text=True,
            check=True,
        )

    def test_bundle_generation_with_tracked_and_untracked(self):
        # 1. Modify base.py without git add (unstaged diff)
        (self.repo_p / "base.py").write_text("def hello():\n    return 'universe'\n", encoding="utf-8")

        # 2. Modify staged_file.py and git add (staged diff)
        (self.repo_p / "staged_file.py").write_text("# modified staged file content\n", encoding="utf-8")
        self._git(["add", "staged_file.py"])

        # 3. Create untracked valid text file
        new_text_file = self.repo_p / "new_feature.py"
        new_text_file.write_text("print('new feature content')\n", encoding="utf-8")

        # 4. Create untracked secret file (should be excluded)
        env_file = self.repo_p / ".env.local"
        env_file.write_text("API_SECRET=12345\n", encoding="utf-8")

        # 5. Create untracked binary file (should be excluded)
        bin_file = self.repo_p / "test_blob.bin"
        bin_file.write_bytes(b"\x00\x01\x02\x03\xff")

        # 6. Create untracked file exceeding size limit (max_file_bytes set to 200)
        large_file = self.repo_p / "large_data.txt"
        large_file.write_text("A" * 500, encoding="utf-8")

        # Instantiate generator with max_file_bytes=200
        generator = LocalBundleGenerator(repo_dir=self.repo_p, max_file_bytes=200)

        out_dir, manifest = generator.generate_bundle(
            goal="Test bundle generation with full edge cases",
            notes="Testing exclusions and diff captures",
            verify_commands=[
                "python3 -c \"print('Verification Step 1 Success')\"",
                "python3 -c \"import sys; sys.stderr.write('Verification Step 2 Failed'); sys.exit(7)\"",
            ],
            verify_timeout=10,
        )

        self.assertTrue(out_dir.exists())
        self.assertTrue((out_dir / "HANDOFF_BUNDLE.md").exists())
        self.assertTrue((out_dir / "manifest.json").exists())

        # Check manifest counts
        self.assertEqual(manifest.goal, "Test bundle generation with full edge cases")
        self.assertGreater(manifest.generation_duration_ms, 0.0)
        self.assertGreater(manifest.total_bundle_bytes, 0)

        # Check included files
        included_paths = {f["path"] for f in manifest.included_files}
        self.assertIn("patches/unstaged.diff", included_paths)
        self.assertIn("patches/staged.diff", included_paths)
        self.assertIn("new_feature.py", included_paths)

        # Verify untracked file copy
        copied_untracked = out_dir / "untracked_files" / "new_feature.py"
        self.assertTrue(copied_untracked.exists())
        self.assertIn("new feature content", copied_untracked.read_text(encoding="utf-8"))

        # Check excluded files
        excluded_map = {f["path"]: f["reason"] for f in manifest.excluded_files}
        self.assertIn(".env.local", excluded_map)
        self.assertEqual(excluded_map[".env.local"], "secret_pattern")

        self.assertIn("test_blob.bin", excluded_map)
        self.assertEqual(excluded_map["test_blob.bin"], "binary_or_non_utf8")

        self.assertIn("large_data.txt", excluded_map)
        self.assertEqual(excluded_map["large_data.txt"], "size_limit_exceeded")

        # Check verification records
        self.assertEqual(len(manifest.verification_records), 2)
        v1 = manifest.verification_records[0]
        self.assertEqual(v1["exit_code"], 0)
        self.assertIn("Verification Step 1 Success", v1["stdout"])

        v2 = manifest.verification_records[1]
        self.assertEqual(v2["exit_code"], 7)
        self.assertIn("Verification Step 2 Failed", v2["stderr"])

        # Check HANDOFF_BUNDLE.md contents
        md_text = (out_dir / "HANDOFF_BUNDLE.md").read_text(encoding="utf-8")
        self.assertIn("## 1. Goal & Context", md_text)
        self.assertIn("universe", md_text)  # from unstaged diff
        self.assertIn("modified staged file content", md_text)  # from staged diff
        self.assertIn("new feature content", md_text)  # from untracked file
        self.assertIn("Excluded Files (Not captured in bundle)", md_text)
        self.assertIn(".env.local", md_text)
        self.assertIn("Verification Step 1 Success", md_text)
        self.assertIn("Verification Step 2 Failed", md_text)


if __name__ == "__main__":
    unittest.main()
