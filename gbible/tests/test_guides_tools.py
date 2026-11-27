"""Guides tool-button regressions."""

import os
import shutil
import tempfile
import unittest


class GuidesToolTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-guidetools-")
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

    def test_outline_export_contains_headings(self):
        from gbible import docs
        for ref in ("John 3", "John"):
            r = docs.export_outline_doc(ref)
            self.assertTrue(r["ok"], r)
            self.assertIn("<h3>", r["html"], ref)

    def test_outline_export_escapes_titles(self):
        from gbible import db, db as _db, docs
        conn = _db.connect()
        # An outline title with markup must not become markup in the export.
        conn.execute("INSERT INTO outline_node(id,source,book,chapter,path,depth,title,refs,ord) "
                     "VALUES('x','t','Gen',1,'/x',0,'<script>x</script>','\"Gen 1:1\"',1)")
        conn.commit()
        r = docs.export_outline_doc("Gen 1")
        self.assertTrue(r["ok"])
        self.assertNotIn("<script>x</script>", r["html"])

    def test_diagram_export_accepts_module(self):
        from gbible import clause
        r = clause.diagram_export("John 3:16", module_id="no-such")
        # Unknown module must not silently fall back to another translation.
        self.assertFalse(r.get("ok"))


if __name__ == "__main__":
    unittest.main()
