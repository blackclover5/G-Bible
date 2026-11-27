"""Settings regressions: error logging, reset, and AI defaults."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path


class SettingsBackendTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-settings-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        from gbible import db
        db.init()
        self.home = Path(home)

    def test_throwing_endpoint_is_logged(self):
        from gbible.server.routes import common
        @common.endpoint("test_throwing_endpoint")
        def _boom(parts, q):
            raise ValueError("deliberate settings test failure")
        r = common.route("test_throwing_endpoint", {})
        self.assertTrue(r["ok"] is False)
        log = self.home / "error-log.jsonl"
        self.assertTrue(log.is_file(), "a failed API call was not logged")
        self.assertIn("deliberate settings test failure",
                      log.read_text(encoding="utf-8"))

    def test_reset_removes_credentials_and_log(self):
        from gbible import db
        from gbible.server.routes.personal import _app_reset
        for name in ("api-credentials.json", "sync-credentials.json",
                     "github-token.json", "error-log.jsonl"):
            (self.home / name).write_text("secret")
        (self.home / "backups").mkdir()
        # Prevent the endpoint's delayed os._exit from killing the test runner.
        import time
        # Keep the patch active until the delayed worker has run: otherwise the
        # real os._exit(0) kills the test runner with it.
        with mock.patch("os._exit", side_effect=lambda code: None):
            _app_reset([], {"confirm": "RESET"})
            time.sleep(1.1)
        for name in ("api-credentials.json", "sync-credentials.json",
                     "github-token.json", "error-log.jsonl"):
            self.assertFalse((self.home / name).exists(), name)
        self.assertFalse((self.home / "backups").exists())

    def test_deep_research_has_a_default(self):
        from gbible import ai
        s = ai.get_settings()
        self.assertIn("deep_research", s)


if __name__ == "__main__":
    unittest.main()
