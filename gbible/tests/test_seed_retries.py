"""Transient external download failures should not fail seeding immediately."""

import unittest
import urllib.error
from unittest.mock import Mock, patch

from tools.seed import _install_seed_item, _is_transient_gutenberg_error
from tools.selftest import _missing_required_readers


class SeedRetryTests(unittest.TestCase):
    def test_missing_book_is_optional_but_other_readers_remain_required(self):
        seen = {"verse", "article", "topic", "date", "image"}
        self.assertEqual(_missing_required_readers(seen), set())
        self.assertEqual(
            _missing_required_readers({"verse", "article", "date", "image"}),
            {"topic"},
        )

    def test_gutenberg_503_retries_and_succeeds(self):
        store = Mock()
        store.install.side_effect = [
            urllib.error.HTTPError(
                "https://www.gutenberg.org/ebooks/57218.txt.utf-8",
                503, "Service Unavailable", None, None),
            {"ok": True},
        ]

        with patch("tools.seed.time.sleep") as sleep:
            result = _install_seed_item(store, "gutenberg", "57218")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(store.install.call_count, 2)
        sleep.assert_called_once_with(5.0)

    def test_non_transient_gutenberg_error_is_not_retried(self):
        store = Mock()
        store.install.side_effect = urllib.error.HTTPError(
            "https://www.gutenberg.org/ebooks/57218.txt.utf-8",
            404, "Not Found", None, None)

        with patch("tools.seed.time.sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                _install_seed_item(store, "gutenberg", "57218")

        self.assertEqual(store.install.call_count, 1)
        sleep.assert_not_called()

    def test_persistent_gutenberg_503_is_classified_as_optional(self):
        store = Mock()
        error = urllib.error.HTTPError(
            "https://www.gutenberg.org/ebooks/57218.txt.utf-8",
            503, "Service Unavailable", None, None)
        store.install.side_effect = error

        with patch("tools.seed.time.sleep"):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                _install_seed_item(store, "gutenberg", "57218")

        self.assertIs(raised.exception, error)
        self.assertTrue(_is_transient_gutenberg_error(raised.exception))
