"""Structured morphology search: decode the tag vocabulary, then match exactly.

The old `morph:` path asked the marker table for `value LIKE '%fragment%'`.
That finds a tag *spelling*, so one query could not span the Hebrew and Greek
schemes, and a fragment that happened to sit inside an unrelated tag matched a
word that did not carry the requested feature at all.  These tests cover the
three resolved shapes -- exact tag, decoded fragment and explicit features --
and the fact that the search engine consumes concrete tag values.
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


class MorphSearchTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, indexer, library, markup, morphq, search
        self.db, self.indexer, self.library = db, indexer, library
        self.markup, self.morphq, self.search = markup, morphq, search
        self.conn = db.connect()

    def _install(self, mid, rows):
        """rows: (key, book, chapter, verse, word, lemma, morph)."""
        self.library.register(self.conn, id=mid, name=mid, type="Bible", v11n="KJV")
        idx = self.indexer.Indexer(mid)
        for key, book, chapter, verse, word, lemma, morph in rows:
            segs = list(self.markup.parse_osis(
                f'<w lemma="{lemma}" morph="{morph}">{word}</w>'))
            idx.add(self.indexer.UnitIn(key=key, label=f"{book} {chapter}:{verse}",
                                        segs=segs, book=book,
                                        chapter=chapter, verse=verse))
        idx.finalise()

    def _install_sample(self):
        self._install("grc", [
            ("TST.1.1", "TST", 1, 1, "Suffer", "strong:G863",
             "MACULA:V-AAI-3S"),
            ("TST.1.2", "TST", 1, 2, "loves", "strong:G25",
             "MACULA:V-PAI-3S"),
            ("TST.1.3", "TST", 1, 3, "beginning", "strong:H7225",
             "HNcmsa"),
        ])

    def _hits(self, q):
        return self.search.search(
            q, self.search.SearchOpts(modules=["grc"], smart=False))

    # ---------------------------------------------------------- resolver ---

    def test_exact_tag_resolves_exactly(self):
        self._install_sample()
        res = self.morphq.resolve_query("MACULA:V-AAI-3S")
        self.assertEqual(res["mode"], "exact")
        self.assertEqual(res["codes"], ["MACULA:V-AAI-3S"])

    def test_explicit_features_are_decoded_with_aliases(self):
        self._install_sample()
        res = self.morphq.resolve_query("tense=aorist voice=active")
        self.assertIn("MACULA:V-AAI-3S", res["codes"])
        self.assertNotIn("MACULA:V-PAI-3S", res["codes"])
        # person=3 is an alias for the decoded "third"
        self.assertEqual(set(self.morphq.resolve_query("person=3")["codes"]),
                         {"MACULA:V-AAI-3S", "MACULA:V-PAI-3S"})

    def test_negated_feature(self):
        self._install_sample()
        res = self.morphq.resolve_query("pos=verb not:tense=aorist")
        self.assertEqual(res["codes"], ["MACULA:V-PAI-3S"])

    def test_features_span_tag_schemes(self):
        self._install_sample()
        # Hebrew HNcmsa and Greek N-NSM are the same grammatical shape; a
        # substring search for either tag can never find both.
        res = self.morphq.resolve_query("pos=noun gender=masculine number=singular")
        self.assertIn("HNcmsa", res["codes"])
        # The Greek sample is a verb, so add a noun from a second scheme.
        self._install("grc2", [("TST.2.1", "TST", 2, 1, "word",
                                "strong:G3056", "MACULA:N-NSM")])
        res = self.morphq.resolve_query("pos=noun gender=masculine number=singular")
        self.assertIn("HNcmsa", res["codes"])
        self.assertIn("MACULA:N-NSM", res["codes"])

    def test_scheme_feature_matches_unprefixed_hebrew_tags(self):
        self._install_sample()
        res = self.morphq.resolve_query("scheme=OSHB pos=noun")
        self.assertIn("HNcmsa", res["codes"])
        self.assertNotIn("MACULA:V-AAI-3S", res["codes"])

    def test_bare_fragment_decodes_instead_of_substring(self):
        self._install_sample()
        res = self.morphq.resolve_query("V-AAI-3S")
        self.assertEqual(res["mode"], "features")
        self.assertIn("MACULA:V-AAI-3S", res["codes"])

    # ------------------------------------------------------------ search ---

    def test_dotted_morph_scopes_are_morphology_requests(self):
        self._install_sample()
        for q in ("morph.g:V-AAI-3S", "morph.h:HNcmsa"):
            term = self.search.parse(q).terms[0]
            self.assertTrue(term.is_morph, q)
            self.assertEqual(term.datatype, q.split(":")[0], q)
        got = self._hits("morph.g:V-AAI-3S")
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])

    def test_search_matches_by_feature_not_tag_spelling(self):
        self._install_sample()
        got = self._hits('morph:"tense=aorist voice=active"')
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["hits"][0]["key"], "TST.1.1")

    def test_search_bare_fragment_finds_tagged_scheme(self):
        self._install_sample()
        got = self._hits("morph:V-AAI-3S")
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["hits"][0]["key"], "TST.1.1")

    def test_search_exact_tag_still_works(self):
        self._install_sample()
        got = self._hits("morph:MACULA:V-PAI-3S")
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["hits"][0]["key"], "TST.1.2")

    def test_morph_combined_with_a_word(self):
        self._install_sample()
        got = self._hits('morph:"pos=verb tense=aorist" AND Suffer')
        self.assertEqual([h["key"] for h in got["hits"]], ["TST.1.1"])

    def test_marker_terms_obey_the_boolean_tree(self):
        # A marker term used to be declared satisfied for every candidate row,
        # which made AND widen to the text hits and made NOT exclude everything.
        self._install("mix", [
            ("TST.1.1", "TST", 1, 1, "Suffer", "strong:G863", "MACULA:V-AAI-3S"),
            ("TST.1.2", "TST", 1, 2, "Suffer", "strong:G25", "MACULA:V-PAI-3S"),
            ("TST.1.3", "TST", 1, 3, "Other", "strong:G26", "MACULA:V-PAI-3S"),
        ])

        def hits(q):
            got = self.search.search(
                q, self.search.SearchOpts(modules=["mix"], smart=False))
            return {h["key"] for h in got["hits"]}

        self.assertEqual(hits('morph:"tense=aorist" AND Suffer'), {"TST.1.1"})
        self.assertEqual(hits('Suffer NOT morph:"tense=aorist"'), {"TST.1.2"})
        self.assertEqual(hits('Suffer OR morph:"tense=aorist"'),
                         {"TST.1.1", "TST.1.2"})
        self.assertEqual(
            hits('morph:"tense=aorist" OR morph:"tense=present"'),
            {"TST.1.1", "TST.1.2", "TST.1.3"})
        # Strong's terms travel the same per-term hit sets.
        self.assertEqual(hits('strongs:G863 AND Suffer'), {"TST.1.1"})
        self.assertEqual(hits('Suffer NOT strongs:G863'), {"TST.1.2"})


if __name__ == "__main__":
    unittest.main()
