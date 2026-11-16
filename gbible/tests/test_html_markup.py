"""HTML parsing: the three ways Jesus' words are encoded.

class="wj" (OSIS-derived HTML Bibles), <q who="Jesus">, and red colour runs
(e-Sword 9+ stores Jesus' words as color:#ff0000).  The negative controls
matter just as much: a green span and a plain span must NOT come out red,
and a red span containing nested styling keeps everything inside it red.
"""

import re
import unittest

from gbible import markup


def _render(html_segment):
    return markup.segs_html(markup.parse_html(html_segment),
                            markup.RenderOpts())


def _plain(html):
    return re.sub(r"<[^>]+>", "", html)


class WjClassTests(unittest.TestCase):
    def test_class_wj_is_red(self):
        out = _render('<span class="wj">I am the way</span>')
        self.assertIn('class="wj"', out)
        self.assertIn("I am the way", _plain(out))

    def test_nested_styling_inside_wj_stays_red(self):
        out = _render('<span class="wj">it <b>is</b> <i>written</i></span>')
        self.assertIn('class="wj"', out)
        self.assertIn("it", _plain(out))
        self.assertIn("is", _plain(out))
        self.assertIn("written", _plain(out))


class JesusSpeakerTests(unittest.TestCase):
    def test_q_who_jesus_is_red(self):
        out = _render('<q who="Jesus">Follow me</q> narration')
        self.assertIn('class="wj"', out)
        red = "".join(re.findall(r'<span class="wj">(.*?)</span>', out))
        self.assertIn("Follow me", _plain(red))


class ColorRedTests(unittest.TestCase):
    def test_style_color_hex_is_red(self):
        out = _render('<span style="color: #ff0000">Follow me</span> and he left')
        red = "".join(re.findall(r'<span class="wj">(.*?)</span>', out))
        self.assertIn("Follow me", _plain(red))
        self.assertNotIn("and he left", _plain(red))

    def test_style_color_name_is_red(self):
        out = _render('<span style="color: red">Follow me</span>')
        self.assertIn('class="wj"', out)

    def test_font_color_is_red(self):
        out = _render('<font color="#ff0000">Follow me</font>')
        self.assertIn('class="wj"', out)

    def test_green_is_plain(self):
        out = _render('<span style="color: #00cc00">not red</span> narration')
        self.assertNotIn('class="wj"', out)

    def test_plain_span_is_plain(self):
        out = _render('<span>plain words</span>')
        self.assertNotIn('class="wj"', out)

    def test_narration_outside_red_span_is_plain(self):
        out = _render('narration <span style="color:#ff0000">Follow me</span> and again')
        red = "".join(re.findall(r'<span class="wj">(.*?)</span>', out))
        self.assertIn("Follow me", _plain(red))
        self.assertNotIn("narration", _plain(red))
        self.assertNotIn("and again", _plain(red))


if __name__ == "__main__":
    unittest.main()
