"""USFM parser: the nesting case that produced "one word red".

In eBible's USFM, every Strong's word inside \\wj … \\wj* is wrapped in
\\w word|strong="G2316"\\w* (or \\+w … \\+w*).  Those inner segments used to
lose the wj flag, so only the spaces rendered red.  These tests pin the fix:
a red word inside a red block must come out red; narration must not.
"""

import re
import unittest

from gbible.formats import usfm
from gbible import markup


SAMPLE = """\\id MAT
\\h Test
\\mt Test
\\c 5
\\v 17 \\wj “Don’t \\w think|strong="G3543"\\w* that I came to \\w destroy|strong="G2647"\\w* the \\w law|strong="G3551"\\w* or the \\w prophets|strong="G4396"\\w*.”\\wj*
\\v 18 \\w Mary|strong="G3137"\\w* went there.
"""

NESTED = """\\id MAT
\\c 1
\\v 39 \\wj “\\+w Come|strong="G2064"\\+w* \\+w and|strong="G2532"\\+w* \\+w see|strong="G3708"\\+w*.”\\wj*
"""


def _units(text):
    doc = usfm.UsfmDoc(text, usfm_id="MAT")
    return list(doc.units())


def _plain(html):
    return re.sub(r"<[^>]+>", "", html)


class UsfmRedTests(unittest.TestCase):
    def test_verse_17_is_red_wherever_it_should_be(self):
        units = _units(SAMPLE)
        v17 = next(u for u in units if u.key == "Matt.5.17")
        for s in v17.segs:
            # whitespace between markers may stay unmarked; real speech may not
            if not s.text.strip():
                continue
            red = (s.attrs or {}).get("wj") or s.kind == "red"
            self.assertTrue(red, f"utterance lost the red marker: {s}")

    def test_narration_is_not_red(self):
        units = _units(SAMPLE)
        v18 = next(u for u in units if u.key == "Matt.5.18")
        html = markup.segs_html(v18.segs, markup.RenderOpts())
        self.assertNotIn('class="wj"', html)
        self.assertIn("Mary", _plain(html))

    def test_inner_strongs_inherit_the_wj_marker(self):
        units = _units(NESTED)
        v = units[0]
        strongs = [s for s in v.segs if s.kind == "strongs"]
        self.assertTrue(strongs, "expected Strong's segments to survive")
        for s in strongs:
            self.assertEqual((s.attrs or {}).get("wj"), "1",
                             f"strongs word lost the wj marker: {s}")

    def test_render_roundtrip_covers_whole_utterance(self):
        units = _units(SAMPLE)
        v17 = next(u for u in units if u.key == "Matt.5.17")
        text, spans = markup.segs_flatten(v17.segs, notes=True)
        blob = markup.spans_to_json(text, spans)
        html = markup.segs_html(markup.segs_from_span(text, blob),
                                markup.RenderOpts())
        plain = _plain(html)
        self.assertIn("Don’t", plain)
        self.assertIn("prophets", plain)
        self.assertGreater(html.count('class="wj"'), 5)

    def test_single_usfm_file_parses(self):
        units = list(usfm.usfm_from_text(SAMPLE, name="test.usfm"))
        self.assertEqual(len(units), 2)


if __name__ == "__main__":
    unittest.main()
