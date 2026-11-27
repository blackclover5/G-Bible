"""In-place app updates: check, stage, apply, protect user data."""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from gbible import appupdate


class UpdateCheckTests(unittest.TestCase):
    def test_newer_release_is_detected(self):
        payload = json.dumps({
            "tag_name": "v9.9.9", "html_url": "https://example.test/release",
            "zipball_url": "https://example.test/source.zip",
            "published_at": "2026-11-24T00:00:00Z", "body": "notes",
        }).encode()
        appupdate._CACHE.clear()
        with mock.patch.object(appupdate, "_get", return_value=payload):
            r = appupdate.check(force=True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["available"])
        self.assertEqual(r["latest"], "9.9.9")

    def test_same_version_is_not_an_update(self):
        appupdate._CACHE.clear()
        payload = json.dumps({
            "tag_name": "v" + appupdate.current_version(),
            "zipball_url": "https://example.test/source.zip",
        }).encode()
        with mock.patch.object(appupdate, "_get", return_value=payload):
            r = appupdate.check(force=True)
        self.assertFalse(r["available"])


class UpdateApplyTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-upd-")
        self.root = Path(self.home) / "app"
        self.root.mkdir()
        (self.root / "gbible").mkdir()
        (self.root / "gbible" / "__init__.py").write_text("v1")
        (self.root / "run.py").write_text("old runner")
        (self.root / "data").mkdir()
        (self.root / "data" / "gbible.db").write_bytes(b"USER DATA")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "marker").write_text("keep")
        self.stage = self.root / "data" / "update-staging" / "v9.9.9" / "src"
        (self.stage / "gbible").mkdir(parents=True)
        (self.stage / "gbible" / "__init__.py").write_text("v2")
        (self.stage / "run.py").write_text("new runner")
        (self.stage / "data").mkdir()
        (self.stage / "data" / "gbible.db").write_bytes(b"OVERWRITE")
        (self.stage / ".venv").mkdir()
        (self.stage / ".venv" / "marker").write_text("OVERWRITE")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.addCleanup(self._restore)

    def _restore(self):
        appupdate._ROOT = Path(__file__).resolve().parent.parent.parent
        appupdate._STAGE = Path(__file__).resolve().parent.parent.parent / "data" / "update-staging"
        os.environ.pop("GBIBLE_NO_RESTART", None)

    def test_apply_replaces_source_but_protects_data_and_venv(self):
        from gbible import db
        old_env = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = str(self.root / "data")
        self.addCleanup(lambda: (os.environ.pop("GBIBLE_HOME", None)
                                 if old_env is None
                                 else os.environ.__setitem__("GBIBLE_HOME", old_env)))
        appupdate._ROOT = self.root
        appupdate._STAGE = self.root / "data" / "update-staging"
        os.environ["GBIBLE_NO_RESTART"] = "1"
        appupdate._CACHE["release"] = {"at": 1e12, "data": {
            "ok": True, "tag": "v9.9.9", "latest": "9.9.9",
            "available": True}}
        r = appupdate.apply("v9.9.9", confirm="APPLY")
        self.assertTrue(r["ok"], r)
        self.assertEqual((self.root / "run.py").read_text(), "new runner")
        self.assertEqual((self.root / "gbible" / "__init__.py").read_text(), "v2")
        self.assertEqual((self.root / "data" / "gbible.db").read_bytes(), b"USER DATA")
        self.assertEqual((self.root / ".venv" / "marker").read_text(), "keep")
        backups = sorted((self.root / "data" / "backups").glob("app-update-*"))
        self.assertTrue(backups)
        manifest = json.loads((backups[-1] / "manifest.json").read_text())
        self.assertIn("run.py", manifest["replaced"])
        self.assertIn("data/gbible.db", manifest["protected"])

    def test_retry_delay_accepts_seconds_and_http_date(self):
        self.assertEqual(appupdate._retry_delay("2", 9.0), 2.0)
        self.assertEqual(appupdate._retry_delay("not a date", 9.0), 9.0)
        import email.utils
        future = email.utils.formatdate(time.time() + 8, usegmt=True)
        self.assertGreaterEqual(appupdate._retry_delay(future, 0.0), 7.0)

    def test_apply_requires_confirmation(self):
        r = appupdate.apply("v9.9.9")
        self.assertFalse(r["ok"])

    def test_rollback_removes_files_the_update_added(self):
        from gbible import db
        old_env = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = str(self.root / "data")
        self.addCleanup(lambda: (os.environ.pop("GBIBLE_HOME", None)
                                 if old_env is None
                                 else os.environ.__setitem__("GBIBLE_HOME", old_env)))
        appupdate._ROOT = self.root
        appupdate._STAGE = self.root / "data" / "update-staging"
        os.environ["GBIBLE_NO_RESTART"] = "1"
        appupdate._CACHE["release"] = {"at": 1e12, "data": {
            "ok": True, "tag": "v9.9.9", "latest": "9.9.9",
            "available": True}}
        (self.stage / "brand-new.py").write_text("introduced by the update")
        applied = appupdate.apply("v9.9.9", confirm="APPLY")
        self.assertTrue(applied["ok"], applied)
        self.assertTrue((self.root / "brand-new.py").is_file())
        back = appupdate.rollback("v9.9.9")
        self.assertTrue(back["ok"], back)
        self.assertEqual(back["removed_new"], 1)
        self.assertFalse((self.root / "brand-new.py").exists())
        self.assertEqual((self.root / "run.py").read_text(), "old runner")

    def test_rollback_honours_the_requested_tag(self):
        from gbible import db
        old_env = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = str(self.root / "data")
        self.addCleanup(lambda: (os.environ.pop("GBIBLE_HOME", None)
                                 if old_env is None
                                 else os.environ.__setitem__("GBIBLE_HOME", old_env)))
        r = appupdate.rollback("v0.0.1")
        self.assertFalse(r["ok"])
        self.assertIn("backup", r["error"])


if __name__ == "__main__":
    unittest.main()
