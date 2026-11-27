"""Regressions from the Home (Today) view audit.

The dashboard is composed from several tables.  These tests pin the contracts
its cards rely on: one date for label and readings, honest highlight counts,
and a refused progress write for a plan day zero.
"""

import os
import shutil
import tempfile
import unittest


class HomeAuditTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-home-")
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
        self.db = db

    def test_devotional_uses_the_passed_date(self):
        from gbible import dashboard
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO module(id,name,type,installed_at) "
            "VALUES('dev1','A devotional','Devotional',1)")
        conn.execute("INSERT INTO unit(module_id,key,ord,ref_label,title,text) "
                     "VALUES('dev1','11.26',1,'11.26','For the date','the reading')")
        conn.commit()
        rows = dashboard._devotional("2026-11-26")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], "11.26")
        self.assertEqual(rows[0]["text"], "the reading")
        self.assertEqual(dashboard._devotional("2026-12-25"), [])

    def test_highlight_total_is_not_the_500_row_query_cap(self):
        from gbible.server.routes import personal
        conn = self.db.connect()
        for i in range(3):
            conn.execute(
                "INSERT INTO highlight(id,module_id,unit_key,quote,color) "
                "VALUES(?,?,?,?,?)", (f"h{i}", "m", "John.3.16", "quote", "yellow"))
        conn.commit()
        r = personal._highlights(["highlights"], {})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["highlights"]), 3)
        self.assertEqual(r["total"], 3)

    def test_missing_highlight_delete_is_a_failure(self):
        from gbible.server.routes import personal
        r = personal._highlights(["highlights"],
                                 {"action": "delete", "hid": "not-there"})
        self.assertFalse(r["ok"])

    def test_marking_plan_day_zero_is_refused(self):
        from gbible.server.routes import core
        r = core._rp_mark(["readingplan/mark"],
                          {"plan": "bible", "day": "0", "done": "1"})
        self.assertFalse(r["ok"])
        self.assertIn("starts at 1", r["error"])

    def test_prayer_day_reports_when_a_list_is_not_from_today(self):
        from gbible import notes
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO note(id,kind,title,body,ref_label,created_at,updated_at) "
            "VALUES('p1','prayer','Old list','body','2020-01-01',1,1)")
        conn.commit()
        row = notes.prayer_day()
        self.assertEqual(row["id"], "p1")
        self.assertFalse(row["dated"])
        self.assertTrue(row["for_date"])

    def test_matching_prayer_for_today_is_dated(self):
        from gbible import notes
        import time
        today = time.strftime("%Y-%m-%d", time.localtime())
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO note(id,kind,title,body,ref_label,created_at,updated_at) "
            "VALUES('p2','prayer','Today list','body',?,1,1)", (today,))
        conn.commit()
        row = notes.prayer_day()
        self.assertEqual(row["id"], "p2")
        self.assertTrue(row["dated"])
