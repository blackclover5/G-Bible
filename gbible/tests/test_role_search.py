"""Clause-role search over a CoNLL-U treebank.

No treebank is installed in the shipped library, so these tests import a tiny
synthetic one through the same reader and indexer a real .conllu file uses.
A role is a relation, not a tag: `subject:Jesus object:Peter` has to find the
clause where those words play those parts, and nothing where they do not.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path


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


_FIXTURE = """# sent_id = John 3:16
1\tIn\tin\tADP\tIN\t_\t2\tcase\t_
2\tthe\tthe\tDET\tDT\t_\t3\tdet\t_
3\tbeginning\tbeginning\tNOUN\tNN\t_\t4\tobl\t_
4\tJesus\tJesus\tPROPN\tNNP\t_\t5\tnsubj\t_
5\tloved\tlove\tVERB\tVBD\t_\t0\troot\t_
6\tPeter\tPeter\tPROPN\tNNP\t_\t5\tobj\t_

# sent_id = John 3:17
1\tPeter\tPeter\tPROPN\tNNP\t_\t2\tnsubj\t_
2\tsaw\tsee\tVERB\tVBD\t_\t0\troot\t_
3\tJesus\tJesus\tPROPN\tNNP\t_\t2\tobj\t_
"""


class RoleSearchTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, formats, indexer, search
        self.db, self.search = db, search
        db.bump_generation()
        path = Path(self.home) / "tiny.conllu"
        path.write_text(_FIXTURE, encoding="utf-8")
        units = list(formats.conllu.load_conllu(path, source="tiny"))
        self.assertEqual(len(units), 2)
        st = indexer.run_import("tiny-syntax", iter(units), type="Syntax",
                                name="Tiny treebank", license="CC BY-SA 4.0")
        self.assertEqual(st["units"], 2)

    def _keys(self, q):
        r = self.search.search(q, self.search.SearchOpts(modules=["tiny-syntax"],
                                                         smart=False))
        return sorted(h["key"] for h in r["hits"])

    def test_roles_are_indexed(self):
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT role, value FROM syntax_role ORDER BY role, value").fetchall()
        pairs = {(r["role"], r["value"]) for r in rows}
        self.assertIn(("subject", "jesus"), pairs)
        self.assertIn(("object", "peter"), pairs)
        self.assertIn(("verb", "love"), pairs)

    def test_subject_and_object(self):
        self.assertEqual(self._keys("subject:Jesus"), ["John.3.16"])
        self.assertEqual(self._keys("object:Peter"), ["John.3.16"])
        self.assertEqual(self._keys("subject:Peter"), ["John.3.17"])
        self.assertEqual(self._keys("object:Jesus"), ["John.3.17"])

    def test_roles_combine_in_one_clause(self):
        self.assertEqual(self._keys("subject:Jesus object:Peter"),
                         ["John.3.16"])
        self.assertEqual(self._keys("subject:Peter object:Jesus"),
                         ["John.3.17"])
        self.assertEqual(self._keys("subject:Jesus object:Jesus"), [])

    def test_verb_and_any_role(self):
        self.assertEqual(self._keys("verb:love"), ["John.3.16"])
        self.assertEqual(self._keys("verb:see"), ["John.3.17"])
        self.assertEqual(self._keys("role:Jesus"),
                         ["John.3.16", "John.3.17"])

    def test_folding_and_boolean(self):
        self.assertEqual(self._keys("subject:jesus"), ["John.3.16"])
        self.assertEqual(self._keys("subject:Jesus NOT object:Peter"), [])

    def test_no_treebank_is_not_an_error(self):
        from gbible import library
        conn = self.db.connect()
        library.mark_removed(conn, "tiny-syntax")
        conn.commit()
        self.assertEqual(self._keys("subject:Jesus"), [])


_PRONOUN_FIXTURE = """# sent_id = John 3:16
1\tJesus\tJesus\tPROPN\tNNP\tGender=Masc|Number=Sing\t2\tnsubj\t_
2\tcame\tcome\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 3:17
1\tHe\the\tPRON\tPRP\tPerson=3|Gender=Masc|Number=Sing\t2\tnsubj\t_
2\ttaught\tteach\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 3:18
1\tPeter\tPeter\tPROPN\tNNP\tGender=Masc|Number=Sing\t2\tnsubj\t_
2\tasked\task\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 3:19
1\tHe\the\tPRON\tPRP\tPerson=3|Gender=Masc|Number=Sing\t2\tnsubj\t_
2\tanswered\tanswer\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 3:20
1\tJesus\tJesus\tPROPN\tNNP\tGender=Masc|Number=Sing\t2\tnsubj\t_
2\tPeter\tPeter\tPROPN\tNNP\tGender=Masc|Number=Sing\t3\tconj\t_
3\tcame\tcome\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 3:21
1\tHe\the\tPRON\tPRP\tPerson=3|Gender=Masc|Number=Sing\t2\tnsubj\t_
2\tspoke\tspeak\tVERB\tVBD\t_\t0\troot\t_
"""


class CoreferenceTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, formats, indexer, search
        self.db, self.search = db, search
        db.bump_generation()
        path = Path(self.home) / "pronouns.conllu"
        path.write_text(_PRONOUN_FIXTURE, encoding="utf-8")
        indexer.run_import("pronouns",
                           iter(formats.conllu.load_conllu(path, source="p")),
                           type="Syntax", name="Pronoun treebank")

    def test_only_unambiguous_pronouns_are_resolved(self):
        rows = self.db.connect().execute(
            "SELECT unit_key, value, surface, resolved FROM syntax_role "
            "WHERE resolved=1 ORDER BY unit_key").fetchall()
        self.assertEqual(
            [(r["unit_key"], r["value"], r["surface"]) for r in rows],
            [("John.3.17", "jesus", "He"),
             ("John.3.19", "peter", "He")])
        # John 3:21 has both Jesus and Peter in the window, so nothing is
        # guessed there.
        self.assertEqual(self.db.connect().execute(
            "SELECT count(*) FROM syntax_role WHERE unit_key='John.3.21' "
            "AND resolved=1").fetchone()[0], 0)

    def test_role_query_finds_the_pronoun_and_names_the_resolution(self):
        got = self.search.search(
            "subject:Jesus", self.search.SearchOpts(modules=["pronouns"],
                                                    smart=False))
        keys = sorted(h["key"] for h in got["hits"])
        self.assertEqual(keys, ["John.3.16", "John.3.17", "John.3.20"])
        inferred = next(h for h in got["hits"] if h["key"] == "John.3.17")
        self.assertIn("subject:jesus ← He", inferred["role_notes"])

    def test_ambiguous_pronoun_is_not_attributed_to_either_name(self):
        for q in ("subject:Jesus", "subject:Peter"):
            got = self.search.search(
                q, self.search.SearchOpts(modules=["pronouns"], smart=False))
            self.assertNotIn("John.3.21", [h["key"] for h in got["hits"]], q)

    def test_gender_from_a_nearby_determiner(self):
        fixture = """# sent_id = John 4:1
1\tὁ\tthe\tDET\tDT\tGender=Masc|Number=Sing\t2\tdet\t_
2\tJesus\tJesus\tPROPN\tNNP\t_\t3\tnsubj\t_
3\tcame\tcome\tVERB\tVBD\t_\t0\troot\t_

# sent_id = John 4:2
1\the\the\tPRON\tPRP\tPerson=3|Gender=Masc|Number=Sing\t2\tnsubj\t_
2\ttaught\tteach\tVERB\tVBD\t_\t0\troot\t_
"""
        from gbible import formats, indexer
        path = Path(self.home) / "article.conllu"
        path.write_text(fixture, encoding="utf-8")
        mid = "article-treebank"
        indexer.run_import(mid,
                           iter(formats.conllu.load_conllu(path, source="a")),
                           type="Syntax", name="Article treebank")
        rows = self.db.connect().execute(
            "SELECT unit_key, value, surface FROM syntax_role "
            "WHERE resolved=1 AND module_id=?", (mid,)).fetchall()
        self.assertEqual([(r["unit_key"], r["value"], r["surface"]) for r in rows],
                         [("John.4.2", "jesus", "he")])

    def test_inferred_matches_can_be_switched_off(self):
        opts = self.search.SearchOpts(modules=["pronouns"], smart=False,
                                      include_resolved=False)
        got = self.search.search("subject:Jesus", opts)
        self.assertEqual([h["key"] for h in got["hits"]],
                         ["John.3.16", "John.3.20"])
        got = self.search.search("subject:Peter", opts)
        self.assertEqual([h["key"] for h in got["hits"]], ["John.3.18"])


if __name__ == "__main__":
    unittest.main()
