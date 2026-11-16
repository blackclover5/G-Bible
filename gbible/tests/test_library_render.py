"""Reader path: a stored unit with a Jesus-marked span renders red.

This is the path between "the data is in the database" and "the user sees
red" — the seam that broke silently for months.  Uses a throwaway GBIBLE_HOME.
"""

import json
import os
import shutil
import sqlite3
import tempfile
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


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, library, markup
        self.db = db
        self.library = library
        self.markup = markup
        self.conn = db.connect()
        segs = list(markup.parse_osis(
            '<w lemma="strong:G2316">God</w> said, '
            '<q marker="" who="Jesus"><w lemma="strong:G863">Suffer</w> '
            'it to be so</q> and it was.'))
        text, spans = markup.segs_flatten(segs, notes=True)
        blob = markup.spans_to_json(text, spans)
        self.conn.execute(
            "INSERT INTO module(id, name, type, source, installed_at) "
            "VALUES ('m1','Bible','Bible','test',1)")
        self.conn.execute(
            "INSERT INTO unit(module_id, key, ord, ref_label, text, markup, "
            "extra) VALUES ('m1','TST.1.1',1,'TST 1:1',?,?,'{}')",
            (text, blob))
        self.conn.commit()

    def _item(self, opts):
        row = self.conn.execute(
            "SELECT * FROM unit WHERE module_id='m1'").fetchone()
        o = self.library._opts(opts)
        return self.library._mk_item(row, o)

    def test_default_renders_red_span(self):
        it = self._item({})
        self.assertIn('class="wj"', it.html)
        self.assertIn("Suffer", it.html)

    def test_show_red_false_renders_plain(self):
        it = self._item({"show_red": False})
        self.assertNotIn('class="wj"', it.html)
        self.assertIn("Suffer", it.html)

    def test_unknown_options_are_ignored(self):
        o = self.library._opts({"show_red": True, "bogus": "hello",
                                "show_headings": False})
        self.assertTrue(o.show_red)
        self.assertFalse(o.show_headings)
        self.assertFalse(hasattr(o, "bogus"))


class OptionsRoundTripTests(unittest.TestCase):
    def test_pane_defaults_roundtrip(self):
        from gbible import library
        o = library._opts(None)
        self.assertTrue(o.show_red)
        self.assertTrue(o.show_notes)


if __name__ == "__main__":
    unittest.main()
