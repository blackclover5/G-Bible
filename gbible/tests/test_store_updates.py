"""Check updates must see seeded modules and admit what it cannot check."""

import os
import shutil
import tempfile
import unittest


class StoreUpdatesTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-updates-")
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

    def test_seeded_module_is_linked_and_versionless_one_is_reported(self):
        from gbible import db, library, store
        from gbible.server.routes.store import _store_updates
        conn = db.connect()
        # A seeded CrossWire module: same name the installer would produce, but
        # no store_item.module_id link, as with a first-run seed.
        mid = library.slugify("crosswire-kjv")
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at,version) "
            "VALUES(?,?,?,?,?)", (mid, "KJV", "Bible", 1, "3.0"))
        conn.execute(
            "INSERT INTO store_item(repo_id,item_id,title,version,type) "
            "VALUES('crosswire','kjv','KJV','3.1','Bible')")
        # A second resource whose catalogue has no version.
        mid2 = library.slugify("ebible-engwebp")
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at,version) "
            "VALUES(?,?,?,?,?)", (mid2, "WEB", "Bible", 1, ""))
        conn.execute(
            "INSERT INTO store_item(repo_id,item_id,title,version,type) "
            "VALUES('ebible','engwebp','WEB','','Bible')")
        conn.commit()

        r = _store_updates(None, {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["linked"], 2)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["updates"][0]["module_id"], mid)
        self.assertEqual(r["updates"][0]["available_version"], "3.1")
        self.assertEqual(r["unchecked"], 1)
        self.assertEqual(r["unchecked_examples"][0]["module_id"], mid2)
        self.assertIn("no version", r["note"])

    def test_link_repair_is_idempotent(self):
        from gbible import db, library, store
        self.assertEqual(store.link_installed_modules(), 0)


if __name__ == "__main__":
    unittest.main()
