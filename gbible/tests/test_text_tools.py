"""Regressions from the Study tools → Text tools audit."""

import os
import shutil
import tempfile
import unittest

from gbible import db, study


def _scratch_home(test_case):
    home = tempfile.mkdtemp(prefix="gbible-text-tools-")
    test_case.addCleanup(shutil.rmtree, home, True)
    old = os.environ.get("GBIBLE_HOME")
    os.environ["GBIBLE_HOME"] = home

    def restore():
        if old is None:
            os.environ.pop("GBIBLE_HOME", None)
        else:
            os.environ["GBIBLE_HOME"] = old
    test_case.addCleanup(restore)
    return home


def _require_modules(*ids):
    from gbible import library
    missing = [mid for mid in ids if library.get_installed(mid) is None]
    if missing:
        raise unittest.SkipTest("not installed: " + ", ".join(missing))


class TextToolsBackendTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import library
        db.bump_generation()
        conn = db.connect()
        library.register(conn, id="text-tools-bible", name="Test Bible",
                         type="Bible", author="Jane Doe", year="2020",
                         installed_at=1)
        for verse in range(16, 22):
            conn.execute(
                "INSERT INTO unit(module_id,key,ord,book,chapter,verse,text,ref_label) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ("text-tools-bible", f"John.3.{verse}", verse, "John", 3,
                 verse, "Grace and mercy endure through the ages.",
                 f"John 3:{verse}"))
        conn.commit()

    def test_search_synopsis_links_to_a_real_unit(self):
        r = study.search_synopsis("grace")
        self.assertTrue(r["ok"])
        self.assertTrue(r["synopsis"])
        for s in r["synopsis"]:
            self.assertTrue(s["sample_ref"], s)

    def test_insights_are_labelled_for_what_they_actually_are(self):
        r = study.insights("John 3:16")
        self.assertTrue(r["ok"])
        titles = [s["title"] for s in r["sections"]]
        self.assertTrue(any("Common words" in t for t in titles), titles)
        self.assertTrue(any("excerpt" in t.lower() for t in titles), titles)
        self.assertFalse(any("Key Themes" in t for t in titles), titles)

    def test_read_verse_span_returns_one_verse(self):
        _require_modules('crosswire-kjv',)
        from gbible import library
        chapter = library.read("crosswire-kjv", {"ref": "John 3:16"},
                               span="chapter")
        verse = library.read("crosswire-kjv", {"ref": "John 3:16"},
                             span="verse")
        self.assertGreater(len(chapter.items), 1)
        self.assertEqual(len(verse.items), 1)
        self.assertEqual(verse.items[0].label, "John 3:16")

    def test_compare_reports_skipped_modules_and_ranges(self):
        _require_modules('crosswire-kjv', 'crosswire-asv')
        r = study.compare("John 3:16-17",
                          ["crosswire-kjv", "crosswire-asv", "no-such"])
        self.assertTrue(r["ok"])
        self.assertTrue(r["note"])
        self.assertIn("no-such", [s["module_id"] for s in r["skipped"]])

    def test_books_search_reports_a_true_total(self):
        r = study.books_search("grace", limit=5)
        self.assertGreater(r["count"], 5)
        self.assertEqual(r["returned"], 5)
        self.assertTrue(r["more"])
        wild = study.books_search("%", limit=5)
        self.assertLess(wild["count"], r["count"])

    def test_bibliography_honours_the_requested_style(self):
        r = study.bibliography(style="apa")
        self.assertEqual(r["style"], "apa")
        self.assertTrue(r["entries"])
        self.assertTrue(all(e["citation"] for e in r["entries"]))

    def test_info_tool_notes_do_not_repeat_strongs_numbers(self):
        r = study.info_tool("John 3:16")
        self.assertTrue(r["ok"])
        self.assertFalse(set(r["notes"]) & set(r["strongs"]))


if __name__ == "__main__":
    unittest.main()
