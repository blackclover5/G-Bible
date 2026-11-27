"""The recommended-set prompt must stop once the modules are actually there.

Modules installed by a seed, a restore or a local import need not have a
store_item row.  Counting only that mapping made the prompt reappear on every
launch even when the whole recommended set was installed.
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


class RecommendedPromptTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db, library
        self.db = db
        self.library = library
        self.conn = db.connect()

    def test_status_counts_installed_modules_without_store_item_rows(self):
        from gbible import recommended
        from gbible.server.routes.store import _recommended_status
        repo, item = recommended.RECOMMENDED[0]
        mid = self.library.slugify(f"{repo}-{item}")
        self.conn.execute(
            "INSERT INTO module(id,name,type,installed_at) VALUES(?,?,?,?)",
            (mid, "Seeded module", "Bible", 1))
        self.conn.commit()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM store_item").fetchone()[0], 0)
        st = _recommended_status([], {})
        self.assertEqual(st["total"], len(recommended.RECOMMENDED))
        self.assertGreaterEqual(st["installed"], 1)
        self.assertFalse(st["dismissed"])

    def test_dismiss_is_persisted(self):
        from gbible.server.routes.store import _recommended_dismiss
        _recommended_dismiss([], {})
        self.assertTrue(self.db.get_setting("recommended_prompt_dismissed", False))


if __name__ == "__main__":
    unittest.main()
