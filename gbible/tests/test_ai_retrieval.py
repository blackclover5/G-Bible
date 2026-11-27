"""Retrieval retries when the first searches find too little to ground an answer."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gbible import ai, db


class RetrievalRetryTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-ai-retrieval-")
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

    def test_thin_phrase_search_retries_the_distinctive_words(self):
        queries = []

        def fake_search(q, opts):
            queries.append(q)
            if q == "courage":
                return {"hits": [{
                    "module_id": "test-commentary", "key": "k1",
                    "module_name": "Test Commentary", "module_type": "Commentary",
                    "label": "k1", "title": "Courage",
                    "text": "A passage about courage in the face of fear.",
                }]}
            return {"hits": []}

        with patch.object(ai.search, "search", side_effect=fake_search):
            sources = ai._library_sources(
                "What does the Bible say about courage and fear?", 5,
                provider=None, smart_query=False)

        self.assertTrue(sources)
        self.assertIn("courage", queries)
        # The phrase query and the single-word retry are different searches.
        self.assertGreater(len(queries), 1)
        self.assertNotEqual(queries[0], queries[-1])
        self.assertIn("courage", sources[0]["text"])

    def test_distinctive_terms_are_bounded(self):
        terms = ai._reformulated_terms(
            "What does the Bible say about courage and fear?")
        self.assertLessEqual(len(terms), 3)
        self.assertIn("courage", terms)
        self.assertNotIn("bible", terms)


if __name__ == "__main__":
    unittest.main()
