"""The previously missing features: word notes, reader topics, guide meaning,
and choosing which side of a restore conflict wins.
"""

import os
import shutil
import tempfile
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


class MissingFeatureTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db
        self.db = db
        db.bump_generation()

    def _bible(self, mid, name):
        from gbible import indexer, markup
        unit = indexer.UnitIn(
            key="John.3.16", label="John 3:16",
            segs=list(markup.parse_osis(
                '<w lemma="strong:G2316">God</w> so loved the world.')),
            book="John", chapter=3, verse=16)
        indexer.run_import(mid, iter([unit]), type="Bible", name=name)

    def test_word_note_follows_the_same_word_into_another_translation(self):
        from gbible import notes
        self._bible("bible-a", "A")
        self._bible("bible-b", "B")
        saved = notes.save({
            "id": "wordnote", "kind": "note", "title": "On love",
            "body": "God is love.", "module_id": "bible-a",
            "unit_key": "John.3.16", "ref_label": "John 3:16", "tags": [],
            "meta": {"anchor_strongs": "G2316", "anchor_word": "God",
                     "word_pos": 1},
        })
        self.assertEqual(saved["meta"]["anchor_strongs"], "G2316")
        marks = notes.word_marks("bible-b", ["John.3.16"])
        self.assertEqual([m["id"] for m in marks["John.3.16"]], ["wordnote"])
        self.assertEqual(marks["John.3.16"][0]["word_pos"], 1)

    def test_tagged_words_carry_word_ordinals(self):
        from gbible import markup
        segs = list(markup.parse_osis(
            '<w lemma="strong:G2316">God</w> so loved '
            '<w lemma="strong:G2316">God</w>.'))
        html = markup.segs_html(segs)
        self.assertIn('data-s="G2316" data-p="1"', html)
        self.assertIn('data-s="G2316" data-p="4"', html)

    def test_visual_copy_supplies_text_for_a_real_image(self):
        from gbible import study
        self._bible("bible-a", "A")
        r = study.visual_copy("John 3:16")
        self.assertTrue(r.get("ok"))
        # The browser draws a PNG from `text`; the ASCII `content` is kept
        # only for older text-only callers.
        self.assertIn("God so loved", r.get("text") or "")
        self.assertEqual(r.get("label"), "John 3:16")
        self.assertIn("G", r.get("content") or "")

    def test_reader_topic_tags_feed_the_topics_guide(self):
        from gbible import study
        conn = self.db.connect()
        conn.execute("INSERT INTO tag(id,name) VALUES('t1','Grace')")
        conn.execute("INSERT INTO tag_item(id,tag_id,kind,module_id,unit_key,"
                     "book,chapter,verse) VALUES('ti1','t1','verse','b','k',"
                     "'John',3,16)")
        conn.commit()
        self.assertEqual([i["title"] for i in
                          study.my_topics_at(conn, "John", 3, 16)], ["Grace"])
        self.assertTrue(any(i["title"].startswith("Grace")
                            for i in study.my_topics_for_term(conn, "grace")))

    def test_guide_sources_can_be_reranked_by_meaning(self):
        from gbible import ai
        from gbible.indexer import UnitIn
        from gbible.indexer import run_import
        from gbible.markup import Seg
        run_import("fb", iter([UnitIn(
            key="A", label="A", title="A",
            segs=[Seg("text", "one")])]),
            type="FactBook", name="A fact book")
        run_import("fb2", iter([UnitIn(
            key="B", label="B", title="B",
            segs=[Seg("text", "two")])]),
            type="FactBook", name="Another fact book")
        provider = mock.Mock(id="fake")
        sources = ai.fact_sources("A", provider=provider, question="A")
        self.assertTrue(sources)
        self.assertEqual([s["n"] for s in sources],
                         list(range(1, len(sources) + 1)))

    def test_apply_chosen_takes_only_the_selected_record(self):
        from gbible import gbz, notes
        self._bible("bible-a", "A")
        notes.save({"id": "n1", "kind": "note", "title": "Original",
                    "body": "from the backup", "module_id": "bible-a",
                    "unit_key": "John.3.16", "ref_label": "John 3:16",
                    "tags": [], "meta": {}})
        data = gbz.create_gbz()["data"]
        notes.save({"id": "n1", "kind": "note", "title": "Changed locally",
                    "body": "mine", "module_id": "bible-a",
                    "unit_key": "John.3.16", "ref_label": "John 3:16",
                    "tags": [], "meta": {}})
        out = gbz.apply_chosen(data, [
            {"kind": "note", "id": "n1", "choice": "theirs"}])
        self.assertEqual(out["applied"], [{"kind": "note", "id": "n1"}])
        self.assertEqual(notes.get("n1")["title"], "Original")


if __name__ == "__main__":
    unittest.main()
