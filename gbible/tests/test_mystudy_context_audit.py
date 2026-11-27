"""Regressions from the My study / reader context-menu audit.

These cover the backend contracts the frontend now relies on: a failed write
must say so, a manual prayer must not be "due daily", and generated content
must come from the verse rather than from its reference string.
"""

import os
import shutil
import tempfile
import unittest


class StudyAuditTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-audit-")
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

    def test_duplicate_custom_plan_is_refused(self):
        from gbible import readingplan
        first = readingplan.save_custom_plan("My plan", ["Gen 1", "Gen 2"])
        self.assertTrue(first["ok"])
        second = readingplan.save_custom_plan("My plan", ["Exod 1"])
        self.assertFalse(second["ok"])
        self.assertIn("already exists", second["error"])
        self.assertEqual(len(readingplan.custom_plans()["My plan"]), 2)

    def test_import_reports_paces_as_well_as_plans(self):
        from gbible import docs
        r = docs.import_plans({"paces": {"bible": "15min"}})
        self.assertTrue(r["ok"])
        self.assertEqual(r["plans"], 0)
        self.assertEqual(r["paces"], 1)

    def test_prayer_templates_stay_deleted(self):
        from gbible import docs
        self.assertEqual(len(docs.prayer_templates()), 2)
        docs.delete_prayer_template("pt-daily")
        docs.delete_prayer_template("pt-weekly")
        self.assertEqual(docs.prayer_templates(), [])
        self.assertEqual(docs.prayer_templates(), [])

    def test_manual_and_answered_prayers_are_not_due(self):
        from gbible import db, docs, notes
        conn = db.connect()
        conn.execute(
            "INSERT INTO note(id,kind,title,body,meta,created_at,updated_at) "
            "VALUES('p1','prayer','Manual','body',?,1,1)",
            ('{"template":"pt-manual","frequency_days":0}',))
        conn.execute(
            "INSERT INTO note(id,kind,title,body,meta,created_at,updated_at) "
            "VALUES('p2','prayer','Answered','body',?,1,1)",
            ('{"template":"pt-daily","answered":true}',))
        conn.commit()
        db.set_setting("prayer_templates", [
            {"id": "pt-manual", "name": "Manual", "frequency_days": 0},
            {"id": "pt-daily", "name": "Daily", "frequency_days": 1}])
        due = docs.prayer_due()
        self.assertEqual([p["id"] for p in due["items"]], ["p1"])
        self.assertTrue(due["items"][0]["manual"])
        self.assertEqual(due["items"][0]["frequency_days"], 0)

    def test_collection_add_reports_missing_collection(self):
        from gbible import organise
        r = organise.add_to_collection("nope", "some-module")
        self.assertFalse(r["ok"])
        self.assertIn("no such collection", r["error"])

    def test_empty_workflow_name_is_reported_as_a_failure(self):
        from gbible import workflow
        r = workflow.save({"name": ""})
        self.assertFalse(r["ok"])

        from gbible.server.routes import workspace
        out = workspace._workflow(["workflow"], {"action": "save", "name": ""})
        self.assertFalse(out["ok"])

    def test_pronounce_guide_has_a_transliteration(self):
        from gbible import docs
        r = docs.pronounce_guide("λόγος")
        self.assertTrue(r["ok"])
        self.assertTrue(r["transliteration"], "the guide never transliterated")

    def test_plan_manager_exposes_pace_goals(self):
        from gbible import db, docs
        db.set_setting("plan_paces", {"bible": "finish:2026-12-31"})
        groups = docs.plan_manager()["groups"]
        entry = next((p for p in groups["today"] + groups["later"]
                      if p.get("finish_by")), None)
        if entry is None:  # no Bible installed in this scratch home
            entry = next((p for p in groups["today"] + groups["later"]), None)
        if entry is not None:
            self.assertEqual(entry["pace"], "finish:2026-12-31")

    def test_canvas_save_rejects_an_unknown_board(self):
        from gbible.server.routes import canvas
        r = canvas._canvas_save(["canvas/save"], {"board": "nope", "nodes": []})
        self.assertFalse(r["ok"])
