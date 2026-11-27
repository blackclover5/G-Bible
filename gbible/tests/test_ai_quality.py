"""Tests for retrieval quality: coverage, resolution, review."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gbible import ai, canon, db, refresolve


class _Provider:
    id = "ollama"
    name = "test"


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-ai-quality-")
        self.old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = self.home
        self.addCleanup(shutil.rmtree, self.home, True)

        def restore():
            if self.old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = self.old
        self.addCleanup(restore)
        db.init()

    def test_explicit_reference_resolution(self):
        refs = refresolve.explicit_refs("Why, in Numbers 20:12, did Moses fail?")
        self.assertIn(canon.Ref("Num", 20, 12), refs)

    def test_coverage_sees_subject_words(self):
        q = "Why was Moses not allowed to enter the promised land?"
        good = [{"label": "Num 20:12", "text":
                 "Moses did not believe the Lord; he shall not bring the "
                 "people into the land which I gave them."}]
        bad = [{"label": "Gen 1:1", "text": "In the beginning God created."}]
        self.assertGreater(ai.retrieval_coverage(q, good), 0.3)
        self.assertLess(ai.retrieval_coverage(q, bad), 0.2)
        self.assertEqual(ai.retrieval_coverage(q, []), 0.0)

    def test_retry_question_drops_scaffolding(self):
        retry = ai.retry_question(
            "Why was Moses not allowed to enter the promised land?")
        self.assertIn("moses", retry)
        self.assertNotIn("why", retry)
        self.assertLessEqual(len(retry.split()), 7)

    def test_chapter_reference_is_not_exploded_into_verses(self):
        refs = refresolve.explicit_refs("What happened in Numbers 20?")
        self.assertIn(canon.Ref("Num", 20), refs)
        self.assertNotIn(canon.Ref("Num", 20, 1), refs)

    def test_settings_normalise_invalid_values(self):
        saved = ai.set_settings(review_backend="banana",
                                max_sources="not-a-number")
        self.assertEqual(saved["review_backend"], "auto")
        self.assertEqual(saved["max_sources"], 20)

    def test_garbled_review_does_not_rewrite_a_grounded_answer(self):
        sources = [{"n": 1, "label": "Num 20:12", "module_name": "Bible",
                    "text": "Moses did not believe the Lord and struck the rock, "
                            "so he did not enter the land."}]
        answer = "Moses did not believe the Lord [1]."
        with patch.object(ai, "_complete", return_value="not JSON at all"):
            revised, grounded, _reason = ai.reviewed_answer(
                "Why?", [], answer, sources, _Provider(), "m")
        self.assertEqual(revised, answer)
        self.assertTrue(grounded)


if __name__ == "__main__":
    unittest.main()
