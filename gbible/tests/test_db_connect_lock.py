"""Opening a connection must not take a write lock on an up-to-date library.

Every HTTP request can arrive on a new thread, so connect() runs often.  When
it rebuilt the schema and started a migration transaction each time, ordinary
reads contended with each other and with the indexer until SQLite raised
"database is locked".
"""

import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest


def _scratch_home(test_case):
    home = tempfile.mkdtemp(prefix="gbible-test-")
    test_case.addCleanup(shutil.rmtree, home, True)
    old = os.environ.get("GBIBLE_HOME")
    os.environ["GBIBLE_HOME"] = home

    def _restore():
        if old is None:
            os.environ.pop("GBIBLE_HOME", None)
        else:
            os.environ["GBIBLE_HOME"] = old

    test_case.addCleanup(_restore)
    return home


class ConnectLockTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db
        self.db = db
        self.conn = db.connect()

    def tearDown(self):
        conn = getattr(self.db._local, "conn", None)
        if conn is not None:
            conn.close()
            del self.db._local.conn
            del self.db._local.path

    def test_current_schema_needs_no_write_transaction(self):
        before = self.conn.in_transaction
        self.db._run_migrations(self.conn)
        self.assertFalse(before)
        self.assertFalse(self.conn.in_transaction,
                         "migration check took a write lock on a current DB")

    def test_read_works_while_another_connection_holds_a_write_lock(self):
        path = self.db.db_path() if hasattr(self.db, "db_path") else None
        if path is None:
            path = self.db.app_dir() / "gbible.db"
        writer = sqlite3.connect(str(path), timeout=5)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")       # hold the write lock
        result = {}

        def read_from_other_thread():
            try:
                result["value"] = self.db.get_setting("no-such-setting", "fallback")
            except Exception as exc:            # noqa: BLE001
                result["error"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=read_from_other_thread)
        t.start()
        t.join(timeout=5)
        writer.rollback()
        writer.close()
        self.assertFalse(t.is_alive(), "a read blocked behind a writer")
        self.assertNotIn("error", result, result.get("error"))
        self.assertEqual(result.get("value"), "fallback")


if __name__ == "__main__":
    unittest.main()
