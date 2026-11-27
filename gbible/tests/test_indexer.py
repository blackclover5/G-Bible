"""Indexer: what it writes, and what it must not write.

The legacy indexer produced 'red-letter' field markers that counted Jesus'
words as a *search* facet — that path is gone.  The only field value it may
emit now is 'main-text', and Strong's markers must still be found.
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


class IndexerTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db
        self.db = db
        self.conn = db.connect()

    def test_index_writes_strongs_and_no_red_letter_field(self):
        from gbible import markup, indexer
        from gbible.indexer import UnitIn
        segs = list(markup.parse_osis(
            '<w lemma="strong:G2316">God</w> said, '
            '<q marker="" who="Jesus"><w lemma="strong:G863">Suffer</w> it '
            'to be so</q> and it was.'))
        unit = UnitIn(key="TST.5.17", label="TST 5:17", segs=segs,
                      book="TST", chapter=5, verse=17)
        idx = indexer.Indexer("m1")
        idx.add(unit)
        idx.finalise()

        row = self.conn.execute(
            "SELECT text, markup FROM unit WHERE module_id='m1' "
            "AND key='TST.5.17'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Suffer", row["text"])

        fields = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT value FROM marker WHERE kind='field'").fetchall()]
        self.assertNotIn("red-letter", fields)
        self.assertIn("main-text", fields)

        strongs = [r[0] for r in self.conn.execute(
            "SELECT value FROM marker WHERE kind='strongs'").fetchall()]
        self.assertTrue(any(s.startswith("G") for s in strongs))

        segs2 = markup.segs_from_span(row["text"], row["markup"])
        html = markup.segs_html(segs2, markup.RenderOpts())
        self.assertIn('class="wj"', html)

    def test_red_words_do_not_leak_into_searchable_text(self):
        from gbible import markup, indexer
        from gbible.indexer import UnitIn
        segs = list(markup.parse_osis('<q marker="" who="Jesus">Follow me'
                                      '</q> and he left.'))
        unit = UnitIn(key="TST.1.1", label="TST 1:1", segs=segs,
                      book="TST", chapter=1, verse=1)
        idx = indexer.Indexer("m1")
        idx.add(unit)
        idx.finalise()
        row = self.conn.execute(
            "SELECT text FROM unit WHERE key='TST.1.1'").fetchone()
        self.assertIn("Follow me", row["text"])
        self.assertIn("and he left.", row["text"])


    def test_repeated_key_across_batches_leaves_one_fts_row(self):
        # `unit` replaces a repeated key; FTS must do the same even when the
        # two occurrences land in different batches.  A stale row made search
        # return a verse whose text did not contain the search words.
        from gbible import indexer, markup
        from gbible.indexer import UnitIn
        ix = indexer.Indexer("m1", batch=1)
        for wording in ("first wording", "second wording"):
            ix.add(UnitIn(key="Gen.1.1", label="Gen 1:1",
                          segs=list(markup.parse_osis(wording))))
        ix.flush()
        rows = self.conn.execute(
            "SELECT unit_key, text FROM unit_fts WHERE module_id='m1'").fetchall()
        self.assertEqual([(r["unit_key"], r["text"]) for r in rows],
                         [("Gen.1.1", "second wording")])
        unit = self.conn.execute(
            "SELECT text FROM unit WHERE module_id='m1' AND key='Gen.1.1'"
        ).fetchone()
        self.assertEqual(unit["text"], "second wording")


if __name__ == "__main__":
    unittest.main()
