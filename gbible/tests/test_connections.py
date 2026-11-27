"""The connections between sync, guides, study tools and analysis records.

These are the pieces that were present but not wired: in-app auto-backup,
restore-to-Store, scoped guides, and the remaining tombstone delete sites.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock


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


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, sync
        self.db, self.sync = db, sync
        db.bump_generation()

    def test_auto_backup_writes_a_timestamped_archive(self):
        out = self.sync.auto_backup()
        self.assertTrue(out["ok"])
        files = list((self.db.app_dir() / "backups").glob("gbible-backup-*.gbz"))
        self.assertEqual(len(files), 1)
        self.assertGreater(float(self.db.get_setting("auto_backup_last", 0)), 0)

    def test_auto_backup_setting_is_saved_and_reported(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cfg = self.sync.save_config({
            "kind": "filesystem", "path": folder, "auto_backup_hours": 6})
        self.assertEqual(cfg["auto_backup_hours"], 6)
        self.assertEqual(self.db.get_setting("auto_backup_hours", 0), 6)
        self.assertEqual(self.sync.status()["auto_backup_hours"], 6)

    def test_plan_mark_delete_removes_only_that_plan(self):
        self.db.set_setting("reading-plan/progress",
                            {"p1": [1, 2], "p2": [3]})
        conn = self.db.connect()
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta(id,kind,rev,dev,ctr,updated_at,hash,base)"
            " VALUES(?,?,?,?,?,?,?,?)",
            ("plan-p1", "plan-mark", 1, "peer", 1, 1000.0, "", ""))
        conn.commit()
        result = self.sync.apply_tombstones(conn, [{
            "kind": "plan-mark", "id": "plan-p1", "deleted_at": 2000.0}])
        self.assertEqual(result["applied"],
                         [{"kind": "plan-mark", "id": "plan-p1"}])
        self.assertEqual(self.db.get_setting("reading-plan/progress", {}),
                         {"p2": [3]})

    def test_citation_meta_delete_by_module(self):
        conn = self.db.connect()
        conn.execute("INSERT INTO citation_meta(module_id,field,value) VALUES(?,?,?)",
                     ("mod-a", "author", "Someone"))
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta(id,kind,rev,dev,ctr,updated_at,hash,base)"
            " VALUES(?,?,?,?,?,?,?,?)",
            ("mod-a", "citation-meta", 1, "peer", 1, 1000.0, "", ""))
        conn.commit()
        result = self.sync.apply_tombstones(conn, [{
            "kind": "citation-meta", "id": "mod-a", "deleted_at": 2000.0}])
        self.assertEqual(result["applied"],
                         [{"kind": "citation-meta", "id": "mod-a"}])
        self.assertEqual(conn.execute(
            "SELECT count(*) FROM citation_meta WHERE module_id='mod-a'"
        ).fetchone()[0], 0)

    def test_citation_clear_writes_a_module_tombstone(self):
        from gbible import citation
        from gbible.indexer import run_import
        from gbible.markup import Seg
        from gbible.indexer import UnitIn
        run_import("mod-a", iter([UnitIn(key="k", label="k",
                                         segs=[Seg("text", "a module")])]),
                   type="Dictionary", name="A")
        citation.set_field("mod-a", "author", "Someone")
        citation.set_field("mod-a", "author", "")
        rows = self.db.connect().execute(
            "SELECT kind FROM sync_tombstone WHERE id='mod-a'").fetchall()
        self.assertIn("citation-meta", [r["kind"] for r in rows])

    def test_wordlist_unpin_tombstones_the_parent(self):
        from gbible import wordlist
        wid = wordlist.save({"name": "Test list"})["id"]
        iid = wordlist.pin(wid, {"term": "faith"})["id"]
        wordlist.unpin(iid)
        rows = self.db.connect().execute(
            "SELECT kind FROM sync_tombstone WHERE id=?", (wid,)).fetchall()
        self.assertIn("word-list", [r["kind"] for r in rows])

    def test_browser_query_builds_the_new_query_forms(self):
        from gbible import organise
        out = organise.browser_query({
            "role": "subject", "role_term": "Jesus",
            "morph": "tense=aorist", "fuzzy": "prayr",
        })
        self.assertIn("subject:Jesus", out["query"])
        self.assertIn('morph:"tense=aorist"', out["query"])
        self.assertIn("~prayr", out["query"])

    def test_install_missing_modules_maps_a_catalogue_id(self):
        from gbible import library, store
        from gbible.server.routes import sync as routes
        conn = self.db.connect()
        conn.execute("INSERT INTO store_item(repo_id,item_id,title,type,format) "
                     "VALUES(?,?,?,?,?)",
                     ("repo", "item", "A book", "Bible", "text"))
        conn.commit()
        mid = library.slugify("repo-item")
        with mock.patch.object(store, "install",
                               return_value={"module_id": mid}) as install:
            out = routes._sync_install_missing(None, {"modules": [mid]})
        self.assertEqual(out["installed"], [mid])
        self.assertEqual(install.call_args.args, ("repo", "item"))


if __name__ == "__main__":
    unittest.main()
