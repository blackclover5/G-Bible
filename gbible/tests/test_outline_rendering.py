"""Outline dictionaries (Nave, Torrey) render as a list, not raw arrow text.

The stored text is left alone; this is presentation only.  Summaries show the
headings instead of the first 320 characters of a reference chain.
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


OUTLINE = "\n \n\n→ Lineage of  Ex 6:16-20 ;  Jos 21:4 , 10 \n\n→ Marriage of  Ex 6:23 \n\n•  See  AARONITES \n"


class OutlineRenderingTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db
        db.connect()

    def test_outline_segments_have_headings_and_clean_references(self):
        from gbible import markup
        segs = markup.segs_from_outline(OUTLINE)
        titles = [s.text for s in segs if s.kind == "title"]
        self.assertEqual(titles, ["Lineage of", "Marriage of"])
        html = markup.segs_html(segs)
        self.assertIn('data-t="outline"', html)
        self.assertNotIn("→", html)
        self.assertIn("Ex 6:16-20; Jos 21:4, 10", html)
        self.assertIn("See also ", html)
        self.assertIn('data-entry="AARONITES"', html)
        self.assertNotIn("•", html)

    def test_reader_detects_outline_text(self):
        from types import SimpleNamespace
        from gbible import library
        segs = library._segs_of(SimpleNamespace(
            text=OUTLINE, key="AARON", extra={"_mid": "nave"}))
        self.assertTrue(any(s.kind == "title" for s in segs))
        entryref = next(s for s in segs if s.kind == "entryref")
        self.assertEqual(entryref.attrs.get("module"), "nave")

    def test_summary_uses_headings_but_prose_is_unchanged(self):
        from gbible import study
        self.assertEqual(study._summary_text(OUTLINE),
                         "Lineage of · Marriage of")
        self.assertEqual(study._summary_text("A plain prose article."),
                         "A plain prose article.")


if __name__ == "__main__":
    unittest.main()
