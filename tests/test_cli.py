import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from private_desktop.cli import client_config, main


class LauncherTests(unittest.TestCase):
    def test_archive_config_uses_absolute_archive(self):
        with patch.object(sys, "argv", ["private-desktop.pyz"]):
            config = client_config()["mcpServers"]["private-desktop"]
        self.assertEqual(config["command"], sys.executable)
        self.assertTrue(config["args"][0].endswith("private-desktop.pyz"))
        self.assertEqual(config["args"][-1], "mcp")

    def test_installed_config_uses_module(self):
        with patch.object(sys, "argv", ["private-desktop"]):
            config = client_config()["mcpServers"]["private-desktop"]
        self.assertEqual(config["args"], ["-m", "private_desktop", "mcp"])

    def test_config_does_not_require_docker(self):
        output = io.StringIO()
        with patch("private_desktop.cli.Sandbox") as sandbox, contextlib.redirect_stdout(output):
            self.assertEqual(main(["client-config"]), 0)
        sandbox.assert_not_called()
        self.assertIn("mcpServers", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
