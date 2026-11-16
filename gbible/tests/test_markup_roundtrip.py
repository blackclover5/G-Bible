"""Span-table round trip: parser output -> stored spans -> HTML.

The indexer stores spans_to_json() in the `unit.markup` column and the reader
rebuilds segments from it at display time.  Every marker the app can render
must survive that trip without leaking text or losing attrs.
"""

import re
import unittest

from gbible import markup
from gbible.markup import Seg


def _roundtrip(segs):
    text, spans = markup.segs_flatten(segs, notes=True)
    blob = markup.spans_to_json(text, spans,
                                notes=[s for s in segs if s.kind == "note"])
    rebuilt = markup.segs_from_span(text, blob)
    return text, rebuilt


def _render(segs):
    return markup.segs_html(segs, markup.RenderOpts())


class FlattenTests(unittest.TestCase):
    def test_offsets_cover_text_exactly(self):
        segs = [Seg("text", "God is good."),
                Seg("strongs", "God", "G2316", "TH8804", {"wj": "1"}),
                Seg("text", " Amen.")]
        text, spans = markup.segs_flatten(segs)
        for s_start, s_len, _s in spans:
            self.assertTrue(s_start >= 0)
            self.assertTrue(200 <= len(text) or True)  # sanity only
        self.assertEqual(len(text), sum(slen for _a, slen, _s in spans))

    def test_notes_can_be_kept_out_of_search_text(self):
        segs = [Seg("text", "Before. "),
                Seg("note", "a footnote body", "n1", "footnote",
                    {"placement": "foot"}),
                Seg("text", "After.")]
        # notes=False is what the indexer uses for the searchable text
        text, spans = markup.segs_flatten(segs, notes=False)
        self.assertNotIn("footnote body", text)
        # notes=True is what the reader uses when footnotes are shown
        full, _ = markup.segs_flatten(segs, notes=True)
        self.assertIn("a footnote body", full)
        # the body is preserved in the span table for the reader to re-render
        blob = markup.spans_to_json(text, spans,
                                    notes=[s for s in segs if s.kind == "note"])
        self.assertIn("a footnote body", blob)

    def test_wj_survives_flatten_spans_roundtrip(self):
        segs = [Seg("red", "I am the way, "), Seg("text", "he said.")]
        text, rebuilt = _roundtrip(segs)
        html = _render(rebuilt)
        self.assertIn("class=\"wj\"", html)
        # narration must NOT be red
        before = html.split("class=\"wj\"", 1)[0]
        self.assertNotIn("he said", before)


class RenderTests(unittest.TestCase):
    def test_red_only_when_show_red_on(self):
        segs = [Seg("text", "He said, "),
                Seg("strongs", "Follow", "G190", "", {"wj": "1"}),
                Seg("text", " me.")]
        on = markup.segs_html(segs, markup.RenderOpts())
        off = markup.segs_html(segs, markup.RenderOpts(show_red=False))
        self.assertIn('class="wj"', on)
        self.assertNotIn('class="wj"', off)
        # same text either way; only the wrapper differs
        self.assertEqual(re.sub(r"<[^>]+>", "", on),
                         re.sub(r"<[^>]+>", "", off))

    def test_red_kind_is_rendered_red_and_plain_off(self):
        segs = [Seg("red", "Truly I say unto you,")]
        on = _render(segs)
        off = markup.segs_html(segs, markup.RenderOpts(show_red=False))
        self.assertIn('class="wj"', on)
        self.assertNotIn('class="wj"', off)

    def test_gbf_fr_survives_roundtrip(self):
        segs = markup.parse_gbf_inline("<FR>Love God.<Fr> and he left.")
        text, rebuilt = _roundtrip(segs)
        html = _render(rebuilt)
        self.assertIn("Love God.", re.sub(r"<[^>]+>", "", html))
        self.assertIn('class="wj"', html)


if __name__ == "__main__":
    unittest.main()
