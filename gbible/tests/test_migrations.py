"""Database migrations: the one that matters is v4 (red-letter removal).

Fresh homes come up at v4.  Existing v3 databases are migrated: the legacy
columns (module.has_redletter, module.redwords) are dropped, and any
'red-letter' field markers still sitting in the marker table from the old
indexer are purged.  Re-running must be a no-op.
"""

import os
import shutil
import sqlite3
import tempfile
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


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


class FreshDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db
        self.db = db

    def test_fresh_home_is_schema_v4_without_legacy_columns(self):
        conn = self.db.connect()
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        cols = _columns(conn, "module")
        self.assertEqual(int(ver), 4)
        self.assertNotIn("has_redletter", cols)
        self.assertNotIn("redwords", cols)
        self.assertIn("attribution", cols)

    def test_reconnect_is_a_noop(self):
        conn = self.db.connect()
        before = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        conn2 = self.db.connect()
        after = conn2.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        self.assertEqual(before, after)
        self.assertEqual(int(after), 4)


class LegacyV3DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        os.makedirs(self.home, exist_ok=True)
        path = os.path.join(self.home, "gbible.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES('schema_version','3')")
        conn.execute("""CREATE TABLE module (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL DEFAULT '',
            lang TEXT, source TEXT, abbrev TEXT,
            index_types TEXT NOT NULL DEFAULT '[]',
            has_redletter INTEGER DEFAULT 0, redwords INTEGER DEFAULT 0,
            attribution TEXT)""")
        conn.execute("INSERT INTO module VALUES('m1','Test Bible','Bible','eng',"
                     "'src','TST','[]',1,42,'x')")
        conn.execute("""CREATE TABLE marker (
            module_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
            unit_key TEXT NOT NULL, pos INTEGER, surface TEXT,
            PRIMARY KEY (module_id, kind, value, unit_key, pos)) WITHOUT ROWID""")
        conn.execute("INSERT INTO marker VALUES ('m1','field','red-letter',"
                     "'Gen.1.1',1,'In')")
        conn.execute("INSERT INTO marker VALUES ('m1','field','main-text',"
                     "'Gen.1.1',1,'In')")
        conn.execute("INSERT INTO marker VALUES ('m1','strongs','H0430',"
                     "'Gen.1.1',1,'bara')")
        conn.commit()
        conn.close()

    def test_v3_database_migrates_to_v4(self):
        from gbible import db
        conn = db.connect()
        cols = _columns(conn, "module")
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        self.assertEqual(int(ver), 4)
        self.assertNotIn("has_redletter", cols)
        self.assertNotIn("redwords", cols)

    def test_red_letter_markers_are_purged_and_rest_kept(self):
        from gbible import db
        conn = db.connect()
        rl = conn.execute(
            "SELECT COUNT(*) FROM marker WHERE kind='field' "
            "AND value='red-letter'").fetchone()[0]
        mt = conn.execute(
            "SELECT COUNT(*) FROM marker WHERE kind='field' "
            "AND value='main-text'").fetchone()[0]
        sg = conn.execute(
            "SELECT COUNT(*) FROM marker WHERE kind='strongs'").fetchone()[0]
        self.assertEqual(rl, 0)
        self.assertEqual(mt, 1)
        self.assertEqual(sg, 1)


if __name__ == "__main__":
    unittest.main()
