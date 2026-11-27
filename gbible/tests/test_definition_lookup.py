"""Word definitions must reach headword dictionaries, not just Strong's.

Smith's, Easton and Webster are keyed by printed headword.  The old word paths
only asked for a Strong's number, so those resources could never answer a word
click; this is the shared lookup used by the definition popup and hover tip.
"""

import os
import shutil
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


class DefinitionLookupTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db
        self.conn = db.connect()

    def _module(self, mid, name, type_):
        self.conn.execute(
            "INSERT INTO module(id,name,type,installed_at) VALUES(?,?,?,1)",
            (mid, name, type_))
        self.conn.execute(
            "INSERT INTO unit(module_id,key,ord,ref_label,text) VALUES(?,?,?,?,?)",
            (mid, 'AARON', 1, 'AARON', 'the first high priest'))

    def test_headword_dictionary_is_found(self):
        from gbible import study
        self._module('smith', "Smith's Bible Dictionary", 'Dictionary')
        self.conn.commit()
        r = study.definition(word='aaron')
        self.assertTrue(r['ok'])
        self.assertTrue(any(e['module_id'] == 'smith' for e in r['entries']))

    def test_strongs_gloss_and_headword_entries_combine(self):
        from gbible import study
        self._module('smith', "Smith's Bible Dictionary", 'Dictionary')
        self.conn.execute("INSERT INTO strongs(strongs,word,lemma) VALUES('G0025','agapao','agapao')")
        self.conn.commit()
        r = study.definition(word='AARON', num='G0025')
        self.assertEqual(r['num'], 'G0025')
        self.assertEqual(r['strongs']['number'], 'G0025')
        self.assertTrue(any(e['module_id'] == 'smith' for e in r['entries']))

    def test_dictionary_section_follows_name_in_topics(self):
        from gbible import study
        for mid, name, type_, text in (
                ('nave', "Nave's Topical Bible", 'FactBook', 'Aaron the priest'),
                ('hitchcock', "Hitchcock's Bible Names", 'FactBook', 'a teacher'),
                ('smith', "Smith's Bible Dictionary", 'Dictionary',
                 'the first high priest')):
            self._module(mid, name, type_)
            self.conn.execute(
                "UPDATE unit SET text=? WHERE module_id=?", (text, mid))
        self.conn.commit()
        r = study.fact_guide('AARON', per_section=3)
        self.assertTrue(r['ok'])
        kinds = [s['kind'] for s in r['sections']]
        self.assertLess(kinds.index('name'), kinds.index('dictionary'))
        self.assertLess(kinds.index('dictionary'), kinds.index('article'))
        self.assertEqual(kinds.count('dictionary'), 1)

    def test_word_bundle_resolves_a_surface_word(self):
        from gbible import study
        self.conn.execute(
            "INSERT INTO marker(module_id,unit_key,kind,value,pos,surface) "
            "VALUES('m','John.3.16','strongs','G0025',1,'love')")
        self.conn.commit()
        r = study.word_bundle('', word='love')
        self.assertTrue(r['ok'])
        self.assertEqual(r['number'], 'G0025')
        self.assertIn('headword', r)
        self.assertIn('morph_codes', r)


if __name__ == "__main__":
    unittest.main()
