"""Analysis backend: a result set with its tags, as rows and facets.

The analysis view re-runs a search and attaches the tags from the marker table
in batches, so a facet counts the whole result set rather than the page the
browser was shown.  These tests check the tag columns, the facets, sorting and
the empty case.
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


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import analysis, db, indexer, library, markup
        self.analysis, self.db = analysis, db
        db.bump_generation()
        self.conn = db.connect()
        self.library = library
        self.library.register(self.conn, id="an", name="Sample Bible",
                              type="Bible", v11n="KJV",
                              installed_at=1.0)
        idx = indexer.Indexer("an")
        tagged = [markup.Seg("text", "God is "),
                  markup.Seg("strongs", "faith", "G4102", "robinson:N-NSF",
                             {"lemma": "πίστις"})]
        plain = [markup.Seg("text", "Faith without works is dead.")]
        idx.add(indexer.UnitIn(key="TST.1.1", label="TST 1:1", segs=tagged,
                               book="TST", chapter=1, verse=1))
        idx.add(indexer.UnitIn(key="TST.1.2", label="TST 1:2", segs=plain,
                               book="TST", chapter=1, verse=2))
        idx.finalise()

    def test_rows_carry_tags(self):
        r = self.analysis.analyse("faith", max_hits=10)
        self.assertTrue(r["ok"])
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["analyzed"], 2)
        row = next(x for x in r["rows"] if x["key"] == "TST.1.1")
        self.assertEqual(row["book"], "TST")
        self.assertEqual(row["chapter"], 1)
        self.assertEqual(row["verse"], 1)
        self.assertEqual(row["lemmas"], ["πίστις"])
        self.assertEqual(row["morphs"], ["robinson:N-NSF"])
        self.assertEqual(row["strongs"], ["G4102"])

    def test_facets_count_the_whole_result_set(self):
        r = self.analysis.analyse("faith", max_hits=1)
        self.assertEqual(r["analyzed"], 1)
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["facets"]["book"][0],
                         {"label": "TST", "count": 1})
        self.assertEqual(r["facets"]["module"][0]["label"],
                         "Sample Bible (an)")

    def test_sort_and_direction(self):
        r = self.analysis.analyse("faith", max_hits=10,
                                  sort="reference", descending=False)
        self.assertEqual([x["key"] for x in r["rows"]],
                         ["TST.1.1", "TST.1.2"])
        r = self.analysis.analyse("faith", max_hits=10,
                                  sort="reference", descending=True)
        self.assertEqual([x["key"] for x in r["rows"]],
                         ["TST.1.2", "TST.1.1"])

    def test_unknown_sort_falls_back_to_score(self):
        r = self.analysis.analyse("faith", max_hits=10, sort="not-a-column")
        self.assertTrue(r["rows"])

    def test_empty_query(self):
        r = self.analysis.analyse("", max_hits=10)
        self.assertTrue(r["ok"])
        self.assertEqual(r["analyzed"], 0)
        self.assertEqual(r["columns"], self.analysis.COLUMNS)


if __name__ == "__main__":
    unittest.main()
