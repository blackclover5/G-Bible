"""Fuzzy terms actually find what the spelling hints only used to suggest.

`~word` expands a typo into an OR over the closest spellings in the library's
own vocabulary, using the same distance budget as the spelling hints.  The
expansion is reported as a warning so the reader can see what was searched.
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


class FuzzySearchTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, indexer, library, search
        self.db, self.indexer, self.library, self.search = db, indexer, library, search
        self.conn = db.connect()
        self.library.register(self.conn, id="fz", name="fz",
                              type="Bible", v11n="KJV")
        idx = indexer.Indexer("fz")
        for key, text in [
            ("TST.1.1", "God heard the prayer of his people."),
            ("TST.1.2", "They kept the faith and were faithful."),
            ("TST.1.3", "The people rejoiced and were glad."),
        ]:
            idx.add(indexer.UnitIn(
                key=key, label=key,
                segs=[self._text_seg(text)],
                book="TST", chapter=1, verse=int(key.rsplit(".", 1)[1])))
        idx.finalise()

    def _text_seg(self, text):
        from gbible import markup
        return markup.Seg("text", text)

    def _hits(self, q):
        return self.search.search(
            q, self.search.SearchOpts(modules=["fz"], smart=False))

    def test_typo_finds_the_correct_word(self):
        got = self._hits("~pryaer")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])
        self.assertTrue(any("~pryaer searched as" in w for w in got["warnings"]),
                        got["warnings"])

    def test_transposition_finds_the_correct_word(self):
        got = self._hits("~prayr")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])

    def test_correct_word_is_not_expanded(self):
        got = self._hits("~prayer")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])
        self.assertFalse(any("searched as" in w for w in got["warnings"]))

    def test_fuzzy_term_in_a_compound_query(self):
        got = self._hits("~faiht AND faithful")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.2"])
        got = self._hits("~faiht OR God")
        self.assertEqual({h["key"] for h in got["hits"]},
                         {"TST.1.1", "TST.1.2"})

    def test_quoted_tilde_is_literal(self):
        got = self._hits('"~pryaer"')
        self.assertEqual(got["total"], 0)
        self.assertFalse(any("searched as" in w for w in got["warnings"]))

    def test_scopes_are_not_fuzzied(self):
        got = self._hits("~strongs:G2316")
        self.assertEqual(got["total"], 0)
        self.assertFalse(any("searched as" in w for w in got["warnings"]))


if __name__ == "__main__":
    unittest.main()
