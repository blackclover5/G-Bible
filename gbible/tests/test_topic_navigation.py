"""Following a link into a keyed (FactBook) module lands on the entry.

The shared "Open in a pane" link always called Reader.focusRef, which used a
Bible-reference cursor.  library._read_topic ignores `ref`, found no unit and
showed the first article in the book -- so Thompson opened at the front no
matter which entry the link named.  This covers the reader end of that seam.
"""

import os
import shutil
import tempfile
import unittest


def _scratch_home(test_case):
    home = tempfile.mkdtemp(prefix="gbible-topic-test-")
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


class TopicCursorTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db, library
        self.db, self.library = db, library
        self.conn = db.connect()
        self.conn.execute(
            "INSERT INTO module(id,name,type,source,installed_at) "
            "VALUES ('tcr','Thompson Chain Topics','FactBook','test',1)")
        for ord_, key, title in [
            (1, "AARON", "Aaron"),
            (2, "JOHN, THE APOSTLE", "John the Apostle"),
            (3, "JOHN THE BAPTIST", "John the Baptist"),
        ]:
            self.conn.execute(
                "INSERT INTO unit(module_id,key,ord,ref_label,title,text,extra) "
                "VALUES ('tcr',?,?,?,?,?,'{}')",
                (key, ord_, key, title, "body of " + title))
        self.conn.commit()
        self.m = library.Module(id="tcr", name="Thompson Chain Topics",
                                type="FactBook")
        self.o = library._opts({})

    def read(self, key):
        return self.library._read_topic(self.m, {"key": key}, self.o, 1)

    def keys(self, key):
        return [it.key for it in self.read(key).items]

    def test_exact_key_opens_that_entry(self):
        self.assertEqual(self.keys("JOHN, THE APOSTLE"), ["JOHN, THE APOSTLE"])

    def test_prefix_returns_the_named_entries_not_the_front(self):
        self.assertEqual(self.keys("JOHN"),
                         ["JOHN, THE APOSTLE", "JOHN THE BAPTIST"])

    def test_case_does_not_matter(self):
        self.assertEqual(self.keys("john"),
                         ["JOHN, THE APOSTLE", "JOHN THE BAPTIST"])

    def test_heading_fallback_finds_an_entry(self):
        self.assertEqual(self.keys("Apostle"), ["JOHN, THE APOSTLE"])

    def test_unknown_key_shows_first_entry_with_a_notice(self):
        c = self.read("ZZZ")
        self.assertEqual([it.key for it in c.items], ["AARON"])
        self.assertTrue(any("ZZZ" in n for n in c.notices))

    def test_like_wildcards_in_a_topic_are_literal(self):
        self.conn.execute(
            "INSERT INTO unit(module_id,key,ord,ref_label,title,text,extra) "
            "VALUES ('tcr','50%',4,'50%','Fifty percent','body','{}')")
        self.conn.commit()
        self.assertEqual(self.keys("50%"), ["50%"])


class AiCitationTests(unittest.TestCase):
    def test_library_citations_carry_the_unit_key(self):
        """A FactBook hit has no verse number in its label, so the key is the
        only thing a citation chip can open.  Dropping it made AI citations of
        a person or topic render but do nothing. """
        _scratch_home(self)
        from gbible import ai
        hit = {
            "module_id": "tcr", "module_name": "Thompson Chain Topics",
            "module_type": "FactBook", "key": "JOHN, THE APOSTLE",
            "label": "John", "title": "John the Apostle", "text": "the body",
            "score": 1.0,
        }
        original = ai.search.search
        ai.search.search = lambda q, opts: {
            "ok": True, "hits": [dict(hit)], "total": 1}
        self.addCleanup(setattr, ai.search, "search", original)
        found = ai._library_sources("John", 3, provider=None,
                                    smart_query=False)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["key"], "JOHN, THE APOSTLE")


if __name__ == "__main__":
    unittest.main()
