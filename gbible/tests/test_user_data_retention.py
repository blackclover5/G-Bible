"""Removing a module must never remove the reader's own data.

The content index is disposable: it can be rebuilt from the module files.
Notes, highlights, cards, lists and collections are not -- they are the study,
and a repair step must leave every one of them exactly where it was.
"""

import os
import shutil
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


class UserDataRetentionTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db
        self.db = db

    def test_mark_removed_keeps_every_user_row(self):
        from gbible import library
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at) VALUES(?,?,?,?)",
            ("gone-bible", "Gone Bible", "Bible", 1))
        conn.execute(
            "INSERT INTO note(id,title,body,module_id,unit_key,ref_label) "
            "VALUES('n1','My note','text','gone-bible','John.3.16','John 3:16')")
        conn.execute(
            "INSERT INTO highlight(id,module_id,unit_key,quote,color) "
            "VALUES('h1','gone-bible','John.3.16','God so loved','yellow')")
        conn.execute(
            "INSERT INTO srs_card(id,ref,module_id,unit_key,due) "
            "VALUES('s1','John 3:16','gone-bible','John.3.16','2026-01-01')")
        conn.execute(
            "INSERT INTO collection(id,name) VALUES('c1','Favourites')")
        conn.execute(
            "INSERT INTO collection_item(collection_id,module_id) "
            "VALUES('c1','gone-bible')")
        conn.execute(
            "INSERT INTO word_list(id,name,query) VALUES('w1','Words','love')")
        conn.execute(
            "INSERT INTO word_list_item(id,list_id,term,module_id,unit_key,ref_label) "
            "VALUES('i1','w1','love','gone-bible','John.3.16','John 3:16')")
        conn.commit()

        library.mark_removed(conn, "gone-bible")
        conn.commit()

        # The module is gone from the library ...
        m = conn.execute(
            "SELECT installed_at FROM module WHERE id='gone-bible'").fetchone()
        self.assertIsNotNone(m)
        self.assertEqual(m["installed_at"], 0)
        # ... but nothing the reader wrote along with it is gone.
        for table, key in (("note", "n1"), ("highlight", "h1"),
                           ("srs_card", "s1"), ("collection_item", "c1"),
                           ("word_list_item", "i1")):
            with self.subTest(table=table):
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE "
                    + ("collection_id" if table == "collection_item" else "id")
                    + "=?", (key,)).fetchone()
                self.assertIsNotNone(row, f"{table} row was lost")
                self.assertEqual(row["module_id"], "gone-bible")

    def test_removed_module_is_labelled_not_shown_as_live(self):
        from gbible import dashboard, library, organise
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at) VALUES(?,?,?,?)",
            ("gone-bible", "Gone Bible", "Bible", 1))
        conn.execute(
            "INSERT INTO collection(id,name) VALUES('c1','Favourites')")
        conn.execute(
            "INSERT INTO collection_item(collection_id,module_id) "
            "VALUES('c1','gone-bible')")
        from gbible import db
        db.set_setting("workspace_layout", {
            "id": "lay1", "panes": [{"id": "p1", "module_id": "gone-bible",
                                     "cursor": {"ref": "John 3:16"}}]})
        conn.commit()

        library.mark_removed(conn, "gone-bible")
        conn.commit()

        # Metadata is still readable (licence/attribution, restore) ...
        self.assertIsNotNone(library.get("gone-bible"))
        # ... but nothing treats it as a resource the reader can open.
        self.assertIsNone(library.get_installed("gone-bible"))
        cols = organise.collections()
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["modules"][0]["name"],
                         "(removed) gone-bible")
        self.assertFalse(cols[0]["modules"][0]["installed"])
        # The saved pane and its cursor are still in the layout, just not
        # offered as a "Continue" card that would open nothing.
        lay = self.db.get_setting("workspace_layout", {})
        self.assertEqual(lay["panes"][0]["module_id"], "gone-bible")
        self.assertEqual(lay["panes"][0]["cursor"]["ref"], "John 3:16")
        self.assertEqual(dashboard._where_you_left_off(), [])

        from gbible import workflow
        step = workflow.resolve({"kind": "open", "module_id": "gone-bible"})
        self.assertEqual(step["action"], "skip")
        self.assertIn("no longer installed", step["reason"])


if __name__ == "__main__":
    unittest.main()
