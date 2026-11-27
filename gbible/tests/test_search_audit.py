"""Search regressions from the Search audit."""

import os
import shutil
import tempfile
import unittest


class SearchEngineTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-search-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        from gbible import db, indexer, library, search
        db.init()
        self.search = search
        self.library = library
        conn = db.connect()
        library.register(conn, id="fz", name="fz", type="Bible", v11n="KJV")
        idx = indexer.Indexer("fz")
        for key, text in [
            ("TST.1.1", "God heard the prayer of his people."),
            ("TST.1.2", "They kept the faith and were faithful."),
            ("TST.1.3", "The people rejoiced and were glad."),
        ]:
            from gbible import markup
            idx.add(indexer.UnitIn(
                key=key, label=key,
                segs=[markup.Seg("text", text)],
                book="TST", chapter=1, verse=int(key.rsplit(".", 1)[1])))
        idx.finalise()

    def test_set_operators_do_not_raise(self):
        for query in ("faith IN lord", "faith INTERSECTS lord",
                      "faith NOT IN lord", "faith NOT INTERSECTS lord"):
            r = self.search.search(query,
                                   self.search.SearchOpts(modules=["fz"], limit=5))
            self.assertTrue(r.get("ok"), (query, r.get("error")))

    def test_limit_and_offset_are_honoured(self):
        opts = self.search.SearchOpts(modules=["fz"], limit=2, offset=0)
        first = self.search.search("people", opts)
        self.assertLessEqual(len(first["hits"]), 2)
        opts2 = self.search.SearchOpts(modules=["fz"], limit=2, offset=2)
        second = self.search.search("people", opts2)
        self.assertTrue(second.get("ok"))


class SearchRouteTests(unittest.TestCase):
    def test_query_string_booleans_are_parsed(self):
        from gbible.server.routes.common import _flag, _bounded_int
        self.assertFalse(_flag("false"))
        self.assertFalse(_flag("0"))
        self.assertTrue(_flag("true"))
        self.assertEqual(_bounded_int("abc", 200), 200)
        self.assertEqual(_bounded_int("-5", 200, low=1), 1)


if __name__ == "__main__":
    unittest.main()
