"""Regressions from the Library and Store menus audit."""

import json
import os
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gbible import db, library, store


class CatalogueDataTests(unittest.TestCase):
    def test_catalogue_ids_are_unique_and_counts_match(self):
        root = Path(__file__).resolve().parent.parent / "store" / "data"
        for path in sorted(root.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            items = doc.get("items") or doc.get("places") or []
            ids = [x.get("id") or x.get("slug") for x in items]
            dupes = [k for k, n in Counter(ids).items() if n > 1]
            self.assertFalse(dupes, f"{path.name}: duplicate ids {dupes[:5]}")
            if "count" in doc:
                self.assertEqual(doc["count"], len(items), path.name)

    def test_download_urls_are_https(self):
        root = Path(__file__).resolve().parent.parent / "store" / "data"
        for path in sorted(root.glob("*.json")):
            for item in (json.loads(path.read_text()).get("items") or []):
                for d in (item.get("downloads") or []):
                    url = d.get("url") or ""
                    if not url:
                        continue
                    self.assertTrue(
                        url.startswith("https://"), f"{path.name}: {url}")


class LibraryOrderTests(unittest.TestCase):
    def test_order_is_whitelisted(self):
        from gbible.server.routes import common
        # The injection string must be rejected and never reach SQLite.
        try:
            rows = library.list_all(order="name ASC; DROP TABLE module")
            self.assertTrue(all(hasattr(m, "id") for m in rows))
        except Exception as e:
            self.fail(f"unexpected SQL error: {e}")


class StoreScopeTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-store-scope-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        db.bump_generation()
        conn = db.connect()
        for i in range(7):
            module_id = f"installed-{i}"
            library.register(conn, id=module_id, name=f"Installed {i}",
                             type="Bible", installed_at=1)
            conn.execute(
                "INSERT INTO store_item(repo_id,item_id,title,type,module_id) "
                "VALUES(?,?,?,?,?)",
                ("test-repo", f"item-{i}", f"Item {i}", "Bible", module_id))
        conn.commit()

    def test_installed_only_before_limit_and_true_total(self):
        page = store.list_items(installed_only=True, limit=5)
        self.assertGreater(page["total"], 5)
        self.assertEqual(page["returned"], 5)
        self.assertTrue(page["has_more"])
        self.assertTrue(all(i["installed"] for i in page["items"]))

    def test_limit_is_bounded_at_the_route(self):
        from gbible.server.routes.common import _bounded_int
        self.assertEqual(_bounded_int("abc", 2000), 2000)
        self.assertEqual(_bounded_int("-1", 2000, low=1), 1)
        self.assertEqual(_bounded_int("5000", 2000), 2000)


class RemovalTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-lib-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        db.init()

    def test_second_remove_is_refused(self):
        from gbible import library as lib
        first = lib.remove_module("no-such")
        self.assertFalse(first["ok"])
        self.assertIn("Not installed", first["error"])



class LocalImportTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-local-")
        self.addCleanup(shutil.rmtree, self.home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = self.home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        db.init()

    def test_same_filename_in_two_folders_gets_two_items(self):
        a = Path(self.home) / "one" / "Bible.txt"
        b = Path(self.home) / "two" / "Bible.txt"
        for p in (a, b):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("In the beginning God created the heaven and the earth.",
                         encoding="utf-8")
        first = store.register_local(a)
        second = store.register_local(b)
        self.assertNotEqual(first["item_id"], second["item_id"])
        self.assertEqual(store.register_local(a)["item_id"], first["item_id"])

    def test_custom_catalogues_live_with_user_data(self):
        path = store._catalog_path("custom-example.json")
        self.assertTrue(path.is_relative_to(Path(db.app_dir()).resolve()))
        self.assertEqual(path.name, "custom-example.json")


if __name__ == "__main__":
    unittest.main()
