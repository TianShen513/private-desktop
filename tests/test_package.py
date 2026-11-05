from pathlib import Path
import os
import subprocess
import sys
import unittest
import zipfile


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, str(cls.root / "tools/build_zipapp.py")],
                       check=True, stdout=subprocess.DEVNULL)
        cls.archive = cls.root / "dist/private-desktop.pyz"

    def test_errors_have_nonzero_exit_status(self):
        result = subprocess.run([sys.executable, str(self.archive), "unknown-command"],
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_returned_failures_exit_nonzero_in_archive(self):
        environment = dict(os.environ, PRIVATE_DESKTOP_HOME="relative-path")
        result = subprocess.run([sys.executable, str(self.archive), "doctor"],
                                env=environment, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")

    def test_success_has_zero_exit_status(self):
        result = subprocess.run([sys.executable, str(self.archive), "client-config"],
                                capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"mcpServers", result.stdout)

    def test_archive_contains_pinned_sandbox_assets(self):
        with zipfile.ZipFile(self.archive) as archive:
            for name in ("Dockerfile", "entrypoint.sh", "demo.py", "checksums.txt"):
                self.assertIn("private_desktop/assets/" + name, archive.namelist())
            self.assertFalse(any("__pycache__" in name for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
