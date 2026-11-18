"""Security boundaries for portable backups."""

import shutil
import tempfile
import unittest


class BackupSecurityTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-backup-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        import os
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = self.home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old

        self.addCleanup(restore)

    def test_plain_backup_excludes_ai_credentials_by_default(self):
        from gbible import db, gbz
        db.connect()
        out = gbz.create_gbz()
        inspected = gbz.inspect_gbz(out["data"])
        self.assertFalse(inspected["has_ai_credentials"])
        self.assertFalse(inspected["has_ai_usage"])

    def test_credentials_require_a_passphrase_and_are_encrypted(self):
        from gbible import db, gbz
        db.connect()

        with self.assertRaises(gbz.GzError):
            gbz.create_gbz(include_ai=True)

        out = gbz.create_gbz(
            include_ai=True,
            credential_passphrase="test-only-passphrase",
        )
        self.assertTrue(gbz.is_encrypted(out["data"]))
        inspected = gbz.inspect_gbz(
            out["data"],
            passphrase="test-only-passphrase",
        )
        self.assertTrue(inspected["ok"])

