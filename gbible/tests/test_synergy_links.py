"""The cross-tool links are backed by accurate reference lookups."""

import unittest
from unittest import mock

from gbible import canon, genealogy, refmatch, study, timeline


class RefMatchTests(unittest.TestCase):
    def test_whole_book_and_chapter_milestones(self):
        self.assertEqual(refmatch.milestones("Hos"), [("Hos", 0, 0)])
        self.assertEqual(refmatch.milestones("Josh 21"), [("Josh", 21, 0)])
        self.assertTrue(refmatch.intersects(
            refmatch.parse_cited("Hos"),
            [refmatch.milestones("Hos 1:2")]))
        self.assertTrue(refmatch.intersects(
            refmatch.parse_cited("Josh 21"),
            [refmatch.milestones("Josh 21:30")]))

    def test_shorthand_and_ranges(self):
        self.assertTrue(refmatch.intersects(
            refmatch.parse_cited("Gen 21:1–24; 26"),
            [refmatch.milestones("Gen 26:12")]))
        self.assertTrue(refmatch.intersects(
            refmatch.parse_cited("Gen 11:26–25:10"),
            [refmatch.milestones("Gen 1:1-50:26")]))


class PlaceLookupTests(unittest.TestCase):
    def test_no_cross_book_tail_match(self):
        names = [p["name"] for p in study.places_at("Gen", 3, 6)]
        self.assertNotIn("Jerusalem", names)
        self.assertNotIn("Nineveh", names)

    def test_verse_and_chapter(self):
        self.assertIn("Abdon", [p["name"] for p in study.places_at("Josh", 21, 30)])
        self.assertIn("Abdon", [p["name"] for p in study.places_at("Josh", 21, 0)])


class TimelineLookupTests(unittest.TestCase):
    def test_whole_book_and_shorthand(self):
        self.assertIn("Hosea", [e["title"] for e in timeline.at("Hos 1:2")["events"]])
        self.assertIn("Isaac", [e["title"] for e in timeline.at("Gen 26:12")["events"]])
        self.assertIn("Zedekiah",
                      [e["title"] for e in timeline.at("2 Kgs 25:1")["events"]])

    def test_range_and_limit(self):
        titles = [e["title"] for e in timeline.at("Gen 1:1-50:26")["events"]]
        self.assertIn("Abraham", titles)
        self.assertIn("Joseph", titles)
        self.assertEqual(len(timeline.at("Ex 12:3", limit=1)["events"]), 1)
        self.assertEqual(timeline.at("Ex 12:3", limit=0)["events"], [])
        self.assertFalse(timeline.at("not a reference")["ok"])


class PeopleLookupTests(unittest.TestCase):
    def test_people_in_uses_parsed_genealogy_keys(self):
        graph = {"ok": True, "people": {
            "enoch": {"name": "Enoch", "refs": ["Gen.4.18", "Gen.5.21"]},
            "other": {"name": "Other", "refs": ["Joel.3.6"]},
        }}
        with mock.patch.object(genealogy, "build", return_value=graph):
            refs = list(canon.parse_ref("Gen 4:18").refs())
            names = [p["name"] for p in study._people_in(None, refs)]
        self.assertEqual(names, ["enoch"])


if __name__ == "__main__":
    unittest.main()
