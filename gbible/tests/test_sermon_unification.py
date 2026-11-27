"""Sermons created anywhere must land in the one canonical store.

The Study Tools importer used to write a private ``sermons`` table that the
Sermon Manager, Editor, backup and sync never saw.  Both paths now use `note`
rows with kind='sermon', and any old rows are migrated across without deletion.
"""

import os
import shutil
import tempfile
import time
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


class SermonUnificationTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db
        self.db = db
        self.conn = db.connect()

    def test_legacy_sermon_is_migrated_without_deletion(self):
        from gbible import sermon_migrate
        self.conn.execute(
            "CREATE TABLE sermons (id TEXT PRIMARY KEY, title TEXT, series TEXT, "
            "text TEXT, created_at REAL)")
        self.conn.execute(
            "INSERT INTO sermons VALUES('old1','Old title','Old series',"
            "'Old body',1000)")
        self.conn.commit()

        self.assertEqual(sermon_migrate.migrate_legacy_sermons(), 1)
        self.assertEqual(sermon_migrate.migrate_legacy_sermons(), 0)
        row = self.conn.execute(
            "SELECT * FROM note WHERE id='legacy-old1'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "sermon")
        self.assertEqual(row["title"], "Old title")
        self.assertEqual(row["body"], "Old body")
        self.assertIn("Old series", row["meta"])
        # The original row is still there: nothing was deleted.
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM sermons").fetchone()[0], 1)

    def test_study_tools_import_is_visible_to_the_manager(self):
        from gbible import docs, study
        r = study.sermon_import("First line\nSecond line", "Imported", "Series A")
        self.assertTrue(r["ok"])
        manager = docs.sermon_manager()
        self.assertEqual(manager["counts"]["total"], 1)
        row = manager["sermons"][0]
        self.assertEqual(row["title"], "Imported")
        self.assertEqual(row["series"], "Series A")
        listed = study.sermon_documents()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["sermons"][0]["text"], "First line\nSecond line")

    def test_builder_edits_are_saved_to_the_note(self):
        from gbible import docs, notes
        notes.save({"id": "n2", "kind": "sermon", "title": "Old title",
                    "body": "Old text", "ref_label": ""})
        r = docs.sermon_builder_save("n2", {
            "title": "New title", "body": "New text",
            "ref_label": "John 3:16", "points": ["one"],
        })
        self.assertTrue(r["ok"])
        n = notes.get("n2")
        self.assertEqual(n["title"], "New title")
        self.assertEqual(n["body"], "New text")
        self.assertEqual(n["ref_label"], "John 3:16")
        self.assertEqual(n["meta"]["points"], ["one"])

    def test_scheduling_writes_both_calendar_and_note(self):
        from gbible import docs, notes
        notes.save({"id": "n4", "kind": "sermon", "title": "Both"})
        docs.sermon_schedule("2027-01-09", "n4")
        self.assertEqual(docs.sermon_calendar().get("2027-01-09"), "n4")
        self.assertEqual(notes.get("n4")["meta"]["scheduled"], "2027-01-09")
        # The Editor's save path writes the calendar too.
        docs.sermon_builder_save("n4", {"scheduled": "2027-02-10"})
        self.assertEqual(docs.sermon_calendar().get("2027-02-10"), "n4")
        self.assertNotIn("2027-01-09", docs.sermon_calendar())

    def test_manager_sees_a_meta_only_scheduled_date(self):
        from gbible import docs, notes
        notes.save({"id": "n5", "kind": "sermon", "title": "Legacy date",
                    "meta": {"scheduled": "2027-03-11"}})
        row = next(s for s in docs.sermon_manager()["sermons"] if s["id"] == "n5")
        self.assertEqual(row["scheduled"], "2027-03-11")
        self.assertEqual(row["status"], "scheduled")

    def test_unschedule_removes_the_note_from_the_calendar(self):
        from gbible import docs
        docs.sermon_schedule("2026-12-25", "n3")
        self.assertIn("2026-12-25", docs.sermon_calendar())
        docs.sermon_schedule("", "n3")
        self.assertNotIn("2026-12-25", docs.sermon_calendar())
        self.assertNotIn("", docs.sermon_calendar())

    def test_documents_shows_series_and_text_from_notes(self):
        from gbible import notes, study
        notes.save({"id": "n1", "kind": "sermon", "title": "Hand-written",
                    "body": "Body text", "meta": {"series": "Hand-made"}})
        d = study.sermon_documents()
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["sermons"][0]["series"], "Hand-made")
        self.assertEqual(d["sermons"][0]["text"], "Body text")


if __name__ == "__main__":
    unittest.main()
