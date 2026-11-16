"""OSIS: <q who="Jesus"> is the only span that becomes red.

Ordinary <q> (different speaker, no speaker, or empty who) must stay plain;
a who=Jesus quotation marks ONLY its own subtree — words in Strong's tags
alongside it must not lose that marker, and narration outside it must not
receive it.
"""

import re
import unittest

from gbible import markup

JESUS = ('<w lemma="strong:G2316">God</w> said, '
         '<q marker="" who="Jesus"><w lemma="strong:G863">Suffer</w> it to be so '
         '<w lemma="strong:G737">now</w>: for thus it becometh us</q> and it was.')

ORDINARY_Q = ('<w lemma="strong:G2316">God</w> said, '
              '<q marker="" who="Moses"><w lemma="strong:G863">Suffer</w></q> and it was.')

NO_WHO = ('<w lemma="strong:G2316">God</w> said, '
          '<q marker="\u201C"><w lemma="strong:G863">Suffer</w></q> and it was.')


def _wj_of(html):
    return re.findall(r'<span class="wj">(.*?)</span>', html)


def _roundtrip(segs):
    text, spans = markup.segs_flatten(segs, notes=True)
    blob = markup.spans_to_json(text, spans,
                                notes=[s for s in segs if s.kind == "note"])
    return markup.segs_from_span(text, blob)


class OsisSpeakerTests(unittest.TestCase):
    def test_jesus_quote_is_red_end_to_end(self):
        html = markup.segs_html(markup.parse_osis(JESUS),
                                markup.RenderOpts())
        red = _wj_of(html)
        self.assertTrue(red, "expected red spans in the Jesus quotation")
        self.assertIn("Suffer", "".join(red))
        self.assertIn("it to be so", "".join(red))

    def test_narration_before_and_after_is_plain(self):
        html = markup.segs_html(markup.parse_osis(JESUS),
                                markup.RenderOpts())
        # "God" and "it was" live outside the quotation and must not be red.
        self.assertNotIn("God", "".join(_wj_of(html)))

    def test_ordinary_speaker_is_plain(self):
        html = markup.segs_html(markup.parse_osis(ORDINARY_Q),
                                markup.RenderOpts())
        self.assertNotIn('class="wj"', html)

    def test_absent_speaker_is_plain(self):
        html = markup.segs_html(markup.parse_osis(NO_WHO),
                                markup.RenderOpts())
        self.assertNotIn('class="wj"', html)

    def test_roundtrip_preserves_the_marker(self):
        segs = markup.parse_osis(JESUS)
        rebuilt = _roundtrip(segs)
        html = markup.segs_html(rebuilt, markup.RenderOpts())
        self.assertTrue(_wj_of(html))
        plain = markup.segs_html(rebuilt, markup.RenderOpts(show_red=False))
        self.assertNotIn('class="wj"', plain)


class OsisXmlBibleTests(unittest.TestCase):
    """The open-bibles loader (xmlbible.load_osis) marks spans too."""

    def test_load_osis_marks_jesus_words(self):
        from gbible.formats import xmlbible
        doc = ('<?xml version="1.0"?>'
               '<osis xmlns:osis="http://www.bibles.org/2003/OSIS/namespace">'
               '<osisText osisIDWork="testosis" osisRefWork="Bible">'
               '<div type="book" osisID="Mat" canonical="true">'
               '<chapter osisID="Mat.3">'
               '<verse osisID="Mat.3.15" sID="s1"/>'
               'But Jesus answering said unto him, '
               '<q marker="" who="Jesus"><w lemma="strong:G863" '
               'morph="robinson:V-PPM-2S">Suffer</w> to be so</q> '
               'then he permitted him.'
               '<verse osisID="Mat.3.15" eID="s1"/>'
               '</chapter></div></osisText></osis>').encode()
        units, _meta = xmlbible.load_osis(doc)
        self.assertEqual(len(units), 1)
        segs = units[0]["segs"]
        red = [s for s in segs if (s.attrs or {}).get("wj") or s.kind == "red"]
        self.assertTrue(red, "expected red segments in the Jesus quote")
        self.assertTrue(any("Suffer" in s.text for s in red),
                        "expected 'Suffer' to be among the red spans")

    def test_load_osis_milestone_q_is_red(self):
        # open-bibles writes Jesus' words as milestone quotations:
        #   <q who="Jesus" sID="M1" marker=""/>suffer the words<q eID="M1"/>
        from gbible.formats import xmlbible
        doc = ('<?xml version="1.0"?>'
               '<osis xmlns:osis="http://www.bibles.org/2003/OSIS/namespace">'
               '<osisText osisIDWork="testosis" osisRefWork="Bible">'
               '<div type="book" osisID="Mat" canonical="true">'
               '<chapter osisID="Mat.3">'
               '<verse osisID="Mat.3.15" sID="v1"/>'
               'But Jesus answering said unto him, '
               '<q who="Jesus" marker="" sID="q1"/>'
               '<w lemma="strong:G863" morph="robinson:V-PPM-2S">Suffer</w> '
               'it to be so.'
               '<q eID="q1"/>'
               ' Then he permitted him.'
               '<verse osisID="Mat.3.15" eID="v1"/>'
               '</chapter></div></osisText></osis>').encode()
        units, _meta = xmlbible.load_osis(doc)
        self.assertEqual(len(units), 1)
        segs = units[0]["segs"]
        red = [s for s in segs
               if s.kind == "red" or (s.attrs or {}).get("wj")]
        self.assertTrue(red, "milestone quotation was not marked red")
        self.assertTrue(any("Suffer" in s.text for s in red))
        plain_text = "".join(s.text for s in segs
                             if s.kind != "red" and not (s.attrs or {}).get("wj"))
        self.assertIn("Then he permitted him.", plain_text)

    def test_load_osis_milestone_q_spans_verse_boundary(self):
        from gbible.formats import xmlbible
        doc = ('<?xml version="1.0"?>'
               '<osis xmlns:osis="http://www.bibles.org/2003/OSIS/namespace">'
               '<osisText osisIDWork="testosis" osisRefWork="Bible">'
               '<div type="book" osisID="Mat" canonical="true">'
               '<chapter osisID="Mat.4">'
               '<verse osisID="Mat.4.4" sID="v1"/>'
               'But Jesus answered and said, '
               '<q who="Jesus" marker="" sID="q1"/>'
               'It is written, <w lemma="strong:G999">Man</w>'
               '<verse osisID="Mat.4.4" eID="v1"/>'
               '<verse osisID="Mat.4.5" sID="v2"/>'
               'shall not live by bread alone.'
               '<q eID="q1"/> And he hungered.'
               '<verse osisID="Mat.4.5" eID="v2"/>'
               '</chapter></div></osisText></osis>').encode()
        units, _meta = xmlbible.load_osis(doc)
        self.assertEqual(len(units), 2)
        for u in units:
            red = [s for s in u["segs"]
                   if s.kind == "red" or (s.attrs or {}).get("wj")]
            self.assertTrue(red, f"quotation broke across verse boundary: {u['key']}")
        tail = "".join(s.text for s in units[1]["segs"]
                       if s.kind == "text" and not (s.attrs or {}).get("wj"))
        self.assertIn("And he hungered.", tail)

    def test_load_osis_plain_when_not_tagged(self):
        from gbible.formats import xmlbible
        doc = ('<?xml version="1.0"?>'
               '<osis xmlns:osis="http://www.bibles.org/2003/OSIS/namespace">'
               '<osisText osisIDWork="testosis" osisRefWork="Bible">'
               '<div type="book" osisID="Mat" canonical="true">'
               '<chapter osisID="Mat.1">'
               '<verse osisID="Mat.1.1" sID="s1"/>'
               'The book of the genealogy of Jesus Christ.'
               '<verse osisID="Mat.1.1" eID="s1"/>'
               '</chapter></div></osisText></osis>').encode()
        units, _meta = xmlbible.load_osis(doc)
        segs = units[0]["segs"]
        red = [s for s in segs if (s.attrs or {}).get("wj") or s.kind == "red"]
        self.assertEqual(red, [])


if __name__ == "__main__":
    unittest.main()
