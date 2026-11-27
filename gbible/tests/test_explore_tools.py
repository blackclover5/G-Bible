"""Regressions from the Study tools → Explore Scripture audit."""

import os
import shutil
import tempfile
import unittest


class CanonRangeTests(unittest.TestCase):
    def test_chapter_range_expands_every_chapter(self):
        from gbible import canon
        refs = list(canon.parse_ref("Gen 1-3").refs())
        self.assertEqual(len(refs), 80)
        self.assertEqual(refs[0], canon.Ref("Gen", 1, 1))
        self.assertEqual(refs[-1], canon.Ref("Gen", 3, 24))
        self.assertFalse(any(r.verse == 0 for r in refs))


class NtUseTests(unittest.TestCase):
    def test_no_quotation_was_commented_out(self):
        from gbible import ntuseot
        pairs = {(a, b) for a, b, *_ in ntuseot.QUOTATIONS}
        self.assertEqual(len(ntuseot.QUOTATIONS), 186)
        for pair in (("Mark 7:6", "Isa 29:13"),
                     ("1John 3:15", "Gen 4:8"),
                     ("Rev 19:11", "Deut 10:17")):
            self.assertIn(pair, pairs)
        with open(ntuseot.__file__, encoding="utf-8") as fh:
            self.assertNotIn("\\n", fh.read())

    def test_verse_count_is_not_the_truncated_page(self):
        from gbible import ntuseot
        r = ntuseot.for_verse("crosswire-kjv", "John.3.16", "crosswire-asv")
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["count"], len(r["matches"]))
        self.assertEqual(r["more"], r["count"] > len(r["matches"]))


class WordListTests(unittest.TestCase):
    def test_strongs_total_respects_module_filter_and_orders_canonically(self):
        from gbible import db, wordlist
        db.init()
        all_rows = wordlist._from_strongs("H3068", limit=5, offset=0)
        filtered = wordlist._from_strongs("H3068", limit=5, offset=0,
                                          module_id="crosswire-kjv")
        self.assertLess(filtered["total"], all_rows["total"])
        self.assertTrue(filtered["more"])
        self.assertEqual(filtered["items"][0]["book"], "Gen")

    def test_stored_limit_cannot_raise_a_callers_cap(self):
        from gbible import db, wordlist
        db.init()
        w = wordlist.save({"name": "Audit cap", "kind": "strongs",
                           "query": "H3068", "options": {"limit": 5000}})
        try:
            r = wordlist.occurrences(w["id"], limit=5)
            self.assertLessEqual(len(r["items"]), 5)
        finally:
            wordlist.remove(w["id"])


class MapsTests(unittest.TestCase):
    def test_alternative_names_are_substring_searchable(self):
        from gbible import maps
        for term, name in (("banah", "Abana"), ("dullami", "Adullam"),
                           ("maleki", "Amalek")):
            page = maps.places_page(term)
            self.assertIn(name, [p["name"] for p in page["places"]], term)

    def test_places_page_reports_total_and_more(self):
        from gbible import maps
        page = maps.places_page("", limit=5)
        self.assertGreater(page["total"], 5)
        self.assertTrue(page["more"])
        self.assertEqual(len(page["places"]), 5)

    def test_near_east_viewbox_is_lon_lat_lon_lat(self):
        from gbible import maps
        south, west, north, east = maps.NEAR_EAST
        self.assertEqual(f"{west},{north},{east},{south}", "31.5,35.5,37.5,29.0")


class SrsTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-srs-")
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

    def test_canonical_aliases_do_not_make_two_cards(self):
        from gbible import srs
        a = srs.add("Jn 3:16")
        b = srs.add("John 3:16")
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b["already"])


if __name__ == "__main__":
    unittest.main()
