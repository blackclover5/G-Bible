"""Guide AI improvements: shared gathering, scope, priority, deep research.

These are backend checks; the per-entry Summarise button and the citation flash
are front-end wiring and are checked by syntax plus a browser smoke test.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock


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


class GuideImprovementTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import ai, db, indexer, library, markup, study
        self.ai, self.db, self.study = ai, db, study
        db.bump_generation()
        ai._GUIDE_CACHE.clear()
        conn = db.connect()
        self.mods = {}
        for mid, name, priority in (
                ("fb-high", "Torrey's Topical Textbook", 20),
                ("fb-low", "Nave's Topical Bible", 1)):
            unit = indexer.UnitIn(
                key="JOHN", label="JOHN", title="JOHN",
                segs=[markup.Seg("text", f"An article on John from {name}.")],
                book="", chapter=0, verse=0)
            indexer.run_import(mid, iter([unit]), type="FactBook", name=name,
                               priority=priority)
            self.mods[mid] = library.get(mid)
        # A real guide needs at least one Bible for the related-verses section;
        # with none, only the FactBook sections are produced, which is fine.

    def test_guide_is_gathered_once_for_questions_and_answer(self):
        with mock.patch.object(self.study, "fact_guide",
                               wraps=self.study.fact_guide) as gather:
            self.ai.fact_sources("John")
            self.ai.fact_sources("John")
        self.assertEqual(gather.call_count, 1)

    def test_cache_is_scoped_by_module_set(self):
        all_sources = self.ai.fact_sources("John")
        one = self.ai.fact_sources(
            "John", module_ids=["fb-low"])
        self.assertTrue(all_sources)
        self.assertTrue(one)
        self.assertTrue(all(s.get("module_id") == "fb-low" for s in one))
        self.assertNotEqual(
            {s.get("module_id") for s in one},
            {s.get("module_id") for s in all_sources})

    def test_explicit_empty_scope_reads_nothing(self):
        self.assertIsNone(self.ai.guide_scope_modules(""))
        self.assertEqual(self.ai.guide_scope_modules("collection:missing"), [])
        with self.assertRaises(self.ai.AiError):
            self.ai.fact_sources("John", module_ids=[])

    def test_module_priority_orders_factbook_entries(self):
        guide = self.study.fact_guide("John")
        articles = [i for s in guide["sections"] if s["kind"] == "article"
                    for i in s["items"]]
        self.assertEqual([i["module_id"] for i in articles],
                         ["fb-high", "fb-low"])

    def test_deep_research_setting_and_request_override(self):
        saved = self.ai.get_settings()
        try:
            out = self.ai.set_settings(deep_research=True)
            self.assertTrue(out["deep_research"])
            self.assertTrue(self.ai.get_settings()["deep_research"])
            with mock.patch.object(self.ai, "_library_sources",
                                   return_value=[]) as gather:
                self.ai.build_context("faith", 8, use_library=True,
                                      use_mine=False, deep_research=True)
            self.assertEqual(gather.call_args.args[1], 30)
            out = self.ai.set_settings(deep_research=False)
            self.assertFalse(out["deep_research"])
        finally:
            self.ai.set_settings(deep_research=False)

    def test_request_override_beats_saved_deep_research(self):
        self.ai.set_settings(deep_research=True)
        try:
            with mock.patch.object(self.ai, "_library_sources",
                                   return_value=[]) as gather:
                self.ai.build_context("faith", 8, use_library=True,
                                      use_mine=False, deep_research=False)
            self.assertFalse(gather.call_args.kwargs.get("deep"))
            with mock.patch.object(self.ai, "_library_sources",
                                   return_value=[]) as gather:
                self.ai.build_context("faith", 8, use_library=True,
                                      use_mine=False, deep_research=True)
            self.assertTrue(gather.call_args.kwargs.get("deep"))
        finally:
            self.ai.set_settings(deep_research=False)

    def test_action_sources_accepts_deep_research(self):
        with mock.patch.object(self.ai, "build_context",
                               return_value=[]) as build:
            self.ai.action_sources("explain", "Gen 1:1", "Gen 1:1", True, 8,
                                   deep_research=True)
        self.assertTrue(build.call_args.kwargs.get("deep_research"))

    def test_deep_research_is_off_by_default(self):
        # get_settings() fills defaults into the saved dict; clear it first.
        self.db.set_setting("ai", {})
        self.assertFalse(self.ai.get_settings().get("deep_research"))


class GuideSectionDataTests(unittest.TestCase):
    """Sections that advertise 'more' must actually be able to show it."""

    def setUp(self):
        _scratch_home(self)
        from gbible import db, library, study
        db.bump_generation()
        conn = db.connect()
        library.register(conn, id="section-bible", name="Section Test Bible",
                         type="Bible", installed_at=1)
        conn.execute(
            "INSERT INTO unit(module_id,key,ord,book,chapter,verse,text,ref_label) "
            "VALUES('section-bible','Gen.4.18',1,'Gen',4,18,'Jared lived','Gen 4:18')")
        conn.commit()
        self.study = study

    def test_crossrefs_read_the_panel_directions(self):
        from gbible import guides
        panel = {
            "ok": True,
            "outgoing": [{"label": f"John 3:{n}", "osis": f"John.3.{n}"}
                         for n in range(1, 5)],
            "incoming": [],
        }
        with mock.patch.object(self.study, "crossref_panel",
                               return_value=panel):
            r = guides.run_section("crossrefs", "John 3:16", {"limit": 3})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(x.get("ref") for x in r["items"]))
        self.assertEqual(r["more"], r["total"] > 3)

    def test_people_pagination_reports_a_truthful_total(self):
        from gbible import guides
        names = [{"word": name} for name in
                 ("Adam", "Cain", "Enoch", "Irad", "Mehujael")]
        with mock.patch.object(self.study, "fact_tags", return_value=names) as tags:
            first = guides.run_section("people", "Gen 4:18", {"limit": 2})
            second = guides.run_section("people", "Gen 4:18",
                                        {"limit": 2, "offset": 2})
        self.assertTrue(first["ok"])
        self.assertGreater(first["total"], 2)
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["more"])
        self.assertNotEqual([x["word"] for x in first["items"]],
                            [x["word"] for x in second["items"]])
        self.assertEqual(tags.call_args.kwargs["limit"], 2000)

    def test_section_limit_is_clamped(self):
        from gbible import guides
        with mock.patch.object(self.study, "places_at",
                               return_value=[{"name": "Test place"}]):
            r = guides.run_section("places", "Josh 21", {"limit": -5})
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(len(r["items"]), 1)


if __name__ == "__main__":
    unittest.main()
