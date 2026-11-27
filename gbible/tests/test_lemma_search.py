"""Lemma search must find the headwords that are actually indexed.

`lemma:` used to ask the morphology marker table for a literal substring of a
Greek headword.  Headwords live in `kind='lemma'`, so every such search came
back empty -- even for a word indexed hundreds of times.  These tests install
a tiny tagged module and check exact, folded, partial, dotted and combined
queries.
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


class LemmaSearchTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, indexer, library, markup, morphq, search
        self.db, self.indexer, self.library = db, indexer, library
        self.markup, self.morphq, self.search = markup, morphq, search
        self.conn = db.connect()
        self.library.register(self.conn, id="gk", name="gk",
                              type="Bible", v11n="KJV")
        idx = indexer.Indexer("gk")

        def unit(key, word, lemma, text_extra=""):
            segs = [self.markup.Seg("text", text_extra + "God "),
                    self.markup.Seg("strongs", word, "G25", "",
                                    {"lemma": lemma})]
            idx.add(indexer.UnitIn(key=key, label=key, segs=segs,
                                   book="TST", chapter=1,
                                   verse=int(key.rsplit(".", 1)[1])))

        unit("TST.1.1", "love", "ἀγαπάω")
        unit("TST.1.2", "word", "λόγος")
        idx.finalise()

    def _hits(self, q):
        return self.search.search(
            q, self.search.SearchOpts(modules=["gk"], smart=False))

    def test_resolver_folds_accents_and_case(self):
        for value in ("ἀγαπάω", "αγαπαω", "ΑΓΑΠΑΩ"):
            res = self.morphq.resolve_lemma(value)
            self.assertEqual(res["mode"], "exact", value)
            self.assertEqual(res["codes"], ["ἀγαπάω"], value)

    def test_partial_headword_falls_back_to_substring(self):
        res = self.morphq.resolve_lemma("ἀγαπ")
        self.assertEqual(res["mode"], "substring")
        self.assertEqual(res["codes"], ["ἀγαπάω"])

    def test_exact_lemma_search(self):
        got = self._hits("lemma:ἀγαπάω")
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["hits"][0]["key"], "TST.1.1")
        self.assertIn("ἀγαπάω", got["hits"][0]["matched"])

    def test_unaccented_and_uppercase_queries(self):
        for q in ("lemma:αγαπαω", "lemma:ΑΓΑΠΑΩ"):
            self.assertEqual([h["key"] for h in self._hits(q)["hits"]],
                             ["TST.1.1"], q)

    def test_dotted_scope_forms(self):
        for q in ("lemma.g:ἀγαπάω", "lemma.h:ἀγαπάω"):
            term = self.search.parse(q).terms[0]
            self.assertEqual(term.lemma, "ἀγαπάω", q)
            self.assertEqual([h["key"] for h in self._hits(q)["hits"]],
                             ["TST.1.1"], q)

    def test_partial_headword_reports_warning(self):
        got = self._hits("lemma:ἀγαπ")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])
        self.assertTrue(any("partial form" in w for w in got["warnings"]))

    def test_lemma_obeys_the_boolean_tree(self):
        self.assertEqual([h["key"] for h in
                          self._hits("lemma:ἀγαπάω AND God")["hits"]],
                         ["TST.1.1"])
        self.assertEqual([h["key"] for h in
                          self._hits("God NOT lemma:ἀγαπάω")["hits"]],
                         ["TST.1.2"])


if __name__ == "__main__":
    unittest.main()
