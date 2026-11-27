"""Research & ministry regressions: honest sources, validated limits."""

import os
import shutil
import tempfile
import unittest


class ResearchToolTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-research-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        from gbible import db, study
        db.init()
        from gbible import library
        conn = db.connect()
        library.register(conn, id="rb", name="Research Bible", type="Bible",
                         v11n="KJV", lang="eng", installed_at=1)
        conn.commit()
        self.study = study

    def test_confessional_and_lecture_features_admit_missing_sources(self):
        c = self.study.confessional_documents()
        self.assertFalse(c["ok"])
        self.assertEqual(c["documents"], [])
        self.assertIn("No confessional", c["error"])
        r = self.study.catholic_daily_readings("2026-11-25")
        self.assertFalse(r["ok"])
        self.assertEqual(r["readings"], [])
        self.assertIn("Lectionary", r["error"])

    def test_visual_copy_honours_module_and_reports_ranges(self):
        from gbible import library, db
        conn = db.connect()
        library.register(conn, id="tstb", name="Test Bible", type="Bible",
                         v11n="KJV", lang="eng", installed_at=1)
        conn.execute("INSERT INTO unit(module_id,key,ord,book,chapter,verse,text,ref_label) "
                     "VALUES('tstb','Gen.1.1',1,'Gen',1,1,'In the beginning','Gen 1:1')")
        conn.commit()
        r = self.study.visual_copy("Gen 1:1-2", module_id="tstb")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["module"], "Test Bible")
        self.assertEqual(r["ref"], "Gen 1:1")
        self.assertIn("first verse", r["note"])
        self.assertFalse(self.study.visual_copy("Gen 1:1",
                                                module_id="no-such")["ok"])

    def test_popular_quotes_uses_ref_xrefs_and_bible_text(self):
        r = self.study.popular_quotes(limit=3)
        self.assertTrue(r["ok"])
        self.assertIn("ref", r.get("metric", ""))
        for q in r["quotes"]:
            self.assertTrue(q["module"])
            self.assertTrue(q["text"])

    def test_bibliography_rejects_unknown_style_and_reports_skips(self):
        r = self.study.bibliography(["rb"], style="bogus")
        self.assertFalse(r["ok"])
        self.assertIn("styles", r)
        r2 = self.study.bibliography(["no-such"], style="sbl")
        self.assertFalse(r2["ok"])

    def test_limits_are_bounded_at_route(self):
        from gbible.server.routes.common import _bounded_int
        self.assertEqual(_bounded_int("abc", 20, low=1, high=200), 20)
        self.assertEqual(_bounded_int("-1", 20, low=1, high=200), 1)
        self.assertEqual(_bounded_int("9999", 20, low=1, high=200), 200)

    def test_confessional_documents_survive_a_non_numeric_limit(self):
        # A stale build interpolated `limit` straight into "LIMIT {limit}",
        # so ?limit=abc raised "no such column: abc" with a full traceback.
        from gbible import db
        conn = db.connect()
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at) "
            "VALUES('conf1','Westminster Confession','Book',1)")
        conn.execute(
            "INSERT INTO unit(module_id,key,ord,ref_label,title,text) "
            "VALUES('conf1','c1',1,'Chapter 1','Of Scripture','the text')")
        conn.commit()
        from gbible.server.routes.study import _confessional_documents
        r = _confessional_documents(["confessional-documents"],
                                    {"doc_type": "abc", "limit": "abc"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 0)
        self.assertNotIn("error", r)


if __name__ == "__main__":
    unittest.main()
