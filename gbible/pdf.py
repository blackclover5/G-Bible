"""Writing a PDF, with no PDF library.

There are three ways to make a PDF here and only one of them is defensible in a
project that ships no third-party code:

**Bundle a JavaScript PDF library.** Adds several hundred kilobytes of someone
else's source to a repository whose whole legal position is that it contains
nothing but its own MIT code. Every licence then has to be tracked, and jsPDF
and pdfmake both carry their own.

**Print from the browser.** No dependency at all, and it produces *better* PDFs
than a library does — real fonts, selectable text, proper justification. But it
is a printer dialog, not a file, so nothing can be produced on demand or handed
to something else programmatically.

**Write the PDF.** A PDF for text is a small, documented format: a header, a
page tree, a content stream per page, and a cross-reference table. That is what
this module does, in about two hundred lines, and it is why the file can be
produced from a script with no dependency at all.

Two consequences worth stating, because they are the legal point as much as the
engineering one:

**Only the base-14 fonts are used** — Helvetica, Times, Courier and Symbol. They
are guaranteed to be present in every conforming PDF reader, and they are
specified as part of the format itself rather than licensed as software. A PDF
generator that embeds a TrueType font has to either licence it or ship it; one
that uses Times embeds nothing at all. Hebrew and Greek therefore cannot be
rendered from a Hebrew or Greek font here — those glyphs are not in the base-14
set, and substituting them would be quietly wrong — so text in those scripts is
reported rather than mangled.

**The licence travels with the document.**  CC BY 4.0 requires attribution, and
an export that silently dropped it would be a breach of the licence on the very
resources this project is careful about.  `attribution` is therefore a required
argument to the high-level entry points, not an option: the caller has to say
what is being exported and under what terms, and there is no way to produce a
PDF without that sentence being considered.

The output is a real PDF 1.4 file with selectable, searchable text.
"""

from __future__ import annotations

import re
import zlib

# Base-14 fonts, addressed by name in the PDF (no embedding, no licence).
#
# The eight faces are named individually and each maps to its own real
# `/BaseFont`.  They used to be collapsed with `fname.split("-")[0]`, which
# turned all eight into three upright faces: `times-italic` and `times-bold` both
# resolved to `/Times`.  Every italic and every bold in the document rendered as
# regular, and in a bibliography that is not a cosmetic loss -- the title of a
# work is italicised by every one of the five supported styles, so every exported
# citation came out wrong on the page in exactly the way a reader would notice
# first.  The self-test could not see it either, because it asserted the
# `/BaseFont` names were in {Times, Helvetica, Courier}, which is precisely what
# the bug produced.
FONTS = {
    "times": "F1", "times-bold": "F2", "times-italic": "F3",
    "helvetica": "F4", "helvetica-bold": "F5", "helvetica-oblique": "F6",
    "courier": "F7", "courier-bold": "F8",
}

#: Each requested face and the `/BaseFont` a conforming reader recognises.
#:
#: The names have to be Title Case.  `/BaseFont /times` is not one of the
#: fourteen, so a reader silently substitutes a default and the PDF looks fine
#: until you notice the typeface is not the one you asked for.
_BASE_FONT = {
    "times": b"Times", "times-bold": b"Times-Bold", "times-italic": b"Times-Italic",
    "helvetica": b"Helvetica", "helvetica-bold": b"Helvetica-Bold",
    "helvetica-oblique": b"Helvetica-Oblique",
    "courier": b"Courier", "courier-bold": b"Courier-Bold",
}

#: Rough advance widths, in 1/1000 em.  Times and Helvetica metrics, enough to
#: wrap and to right-align a page number without embedding an AFM file.  Word
#: wrap only has to be approximately right to be useful, and being wrong costs a
#: line, not a document.
_WIDTHS = {
    "times": {chr(c): 500 for c in range(32, 127)},
    "helvetica": {chr(c): 556 for c in range(32, 127)},
    "courier": {chr(c): 600 for c in range(32, 127)},
}
for _ch, _w in (("i", 278), ("j", 278), ("l", 278), ("f", 333), ("t", 278),
                ("r", 333), ("m", 778), ("w", 722), ("W", 944), ("M", 889),
                ("I", 333), (" ", 250)):
    _WIDTHS["times"][_ch] = _w
for _ch, _w in (("i", 222), ("j", 222), ("l", 222), ("f", 278), ("t", 278),
                ("r", 333), ("m", 833), ("w", 722), ("W", 944), ("M", 833),
                ("I", 278), (" ", 278)):
    _WIDTHS["helvetica"][_ch] = _w

# Scripts the base-14 fonts cannot render.  Text in these is kept out of the PDF
# rather than replaced with something that looks like it.
_UNRENDERABLE = re.compile(r"[\u0590-\u05ff\u0370-\u03ff\u0700-\u074f\u3040-\u30ff\uac00-\ud7af]")

#: Typographic characters the base-14 WinAnsi encodings *can* write, mapped to
#: the letter to write instead.
#:
#: The writer's filter kept ASCII 32-126 and Latin-1 160-255 and dropped
#: everything else, while `skipped_scripts` counts only the unrenderable *ranges*
#: above.  So the dashes, curly quotes and ellipsis sitting in the middle of the
#: Unicode punctuation block were dropped and not even counted -- an export that
#: reported nothing skipped while having mangled its own text.
#:
#: That is not a small thing in this application specifically: every line of
#: `publish.attribution_block` is built as `  \u00b7 {name} \u2014 {lic}`, so
#: **every PDF the app produced lost the dash in its own attribution**, and the
#: quotation marks round a book title came out as nothing.  In a bibliography,
#: whose whole job is the exact shape of the reference, a dropped title mark is
#: a wrong answer rather than an ugly one.
_TYPOGRAPHIC = {
    "\u2018": "'", "\u2019": "'", "\u201a": ",", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-",
    "\u2026": "...", "\u2020": "+", "\u2021": "+",
    "\u2030": "%", "\u2032": "'", "\u2033": '"',
    "\u00ab": '"', "\u00bb": '"', "\u2039": "'", "\u203a": "'",
    "\u2212": "-", "\u00ad": "", "\u00fb": "ff", "\ufb01": "fi",
    "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\u00b7": "*", "\u2027": "*", "\u2022": "*",
}


def _font_family(font: str) -> str:
    return "courier" if font.startswith("courier") else (
        "times" if font.startswith("times") else "helvetica")


def _text_width(s: str, font: str, size: float) -> float:
    table = _WIDTHS[_font_family(font)]
    return sum(table.get(ch, 556) for ch in s) * size / 1000.0


def _escape_pdf(s: str) -> str:
    """Escape for a PDF literal string.

    Non-Latin-1 text cannot be represented at all in the base-14 encodings, so it
    is dropped here and counted by the caller rather than being mangled into
    question marks: a PDF with '?' where the Greek was is worse than a PDF that
    says the Greek was left out.
    """
    out = []
    for ch in s:
        o = ord(ch)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= o < 127:
            out.append(ch)
        elif 160 <= o <= 255:
            out.append(ch)
        elif ch in _TYPOGRAPHIC:
            # Substituted, not dropped, so the text still reads.  See
            # `_TYPOGRAPHIC` for why this was worth fixing rather than counting.
            out.append(_TYPOGRAPHIC[ch])
        elif ch == "\t":
            out.append(" ")
    return "".join(out)


class Doc:
    """A text-only PDF, built a line at a time."""

    def __init__(self, *, title: str = "", author: str = "",
                 subject: str = "", size: str = "A4", margin: float = 56.0):
        self.title = title
        self.author = author
        self.subject = subject
        self.size = size
        self.margin = margin
        self._pages: list[list[str]] = [[]]
        self._y = self._height() - self.margin
        self._used_fonts: set[str] = set()
        self._numbered = False
        self.skipped_scripts = 0

    # -- geometry
    def _dims(self) -> tuple[float, float]:
        return (595.0, 842.0) if self.size == "A4" else (612.0, 792.0)

    def _height(self) -> float:
        return self._dims()[1]

    def _width(self) -> float:
        return self._dims()[0]

    @property
    def _content_width(self) -> float:
        return self._width() - 2 * self.margin

    def _new_page(self) -> None:
        self._pages.append([])
        self._y = self._height() - self.margin

    def _need(self, h: float) -> None:
        if self._y - h < self.margin:
            self._new_page()

    # -- content
    def wrap(self, text: str, font: str, size: float) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if cur and _text_width(trial, font, size) > self._content_width:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines or [""]

    def text(self, s: str, *, font: str = "times", size: float = 11.0,
             leading: float = 1.35, indent: float = 0.0,
             space_before: float = 0.0, space_after: float = 0.0,
             align: str = "left", colour: tuple[float, float, float] = (0, 0, 0),
             link: str = "") -> None:
        """Add a wrapped paragraph.  Non-renderable scripts are skipped."""
        s = (s or "").strip()
        if not s:
            return
        if _UNRENDERABLE.search(s):
            self.skipped_scripts += sum(len(m.group(0)) for m in
                                        _UNRENDERABLE.finditer(s))
            s = _UNRENDERABLE.sub("", s).strip()
            if not s:
                return
        self._used_fonts.add(font)
        self._y -= space_before
        step = size * leading
        usable = self._content_width - indent
        for raw in s.split("\n"):
            words, cur = raw.split(), ""
            lines = []
            for w in words:
                trial = (cur + " " + w).strip()
                if cur and _text_width(trial, font, size) > usable:
                    lines.append(cur)
                    cur = w
                else:
                    cur = trial
            lines.append(cur)
            for line in lines:
                self._need(step)
                self._y -= step
                x = self.margin + indent
                if align in ("center", "right"):
                    w = _text_width(line, font, size)
                    x += (usable - w) / 2 if align == "center" else (usable - w)
                body = _escape_pdf(line)
                if not body:
                    continue
                r, g, b = colour
                self._pages[-1].append(
                    f"BT /{FONTS[font]} {size:.1f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                    f"1 0 0 1 {x:.2f} {self._y:.2f} Tm ({body}) Tj ET")
        self._y -= space_after

    def rule(self, *, colour: tuple[float, float, float] = (0.7, 0.7, 0.7),
             width: float = 0.6, space: float = 6.0) -> None:
        self._need(space * 2)
        self._y -= space
        r, g, b = colour
        self._pages[-1].append(
            f"{r:.3f} {g:.3f} {b:.3f} RG {width} w "
            f"{self.margin:.2f} {self._y:.2f} m "
            f"{self._width() - self.margin:.2f} {self._y:.2f} l S")
        self._y -= space

    def page_numbers(self, *, font: str = "helvetica", size: float = 8.5,
                     label: str = "") -> None:
        """Stamp a footer on every page.

        Done here rather than left to the caller so it cannot be missed, and
        guarded by a flag so a second call does not stamp every page twice.
        """
        if self._numbered:
            return
        self._numbered = True
        n = len(self._pages)
        for i, page in enumerate(self._pages):
            self._used_fonts.add(font)
            txt = f"{label}  ·  {i + 1} / {n}" if label else f"{i + 1} / {n}"
            w = _text_width(txt, font, size)
            x = self._width() - self.margin - w
            page.append(
                f"BT /{FONTS[font]} {size} Tf 0.45 0.45 0.45 rg "
                f"1 0 0 1 {x:.2f} {self.margin * 0.55:.2f} Tm "
                f"({_escape_pdf(txt)}) Tj ET")

    # -- output
    def build(self, *, numbers: bool = True, footer: str = "") -> bytes:
        if numbers:
            self.page_numbers(label=footer)
        return _assemble(self)


def _assemble(doc: Doc) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    used = sorted(doc._used_fonts) or ["times"]
    # object 1: catalogue; 2: pages; 3: font resources; then page + content pairs
    page_ids: list[int] = []
    content_ids: list[int] = []
    for page in doc._pages:
        stream = zlib.compress(("\n".join(page) or "").encode("latin-1", "replace"))
        content_ids.append(add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n"
                               % len(stream) + stream + b"\nendstream"))

    n_pages = len(doc._pages)
    # Reserve ids by adding in a fixed order.
    cat_id = add(b"")          # 1
    pages_id = add(b"")        # 2
    font_ids = {}
    for fname in used:
        desc = _BASE_FONT.get(fname)
        if desc is None:
            raise KeyError(f"no base-14 face for {fname!r}; "
                           f"the PDF writer needs a real /BaseFont per face")
        font_ids[fname] = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /%s >>" % desc)
    res = b" ".join(b"/%s %d 0 R" % (FONTS[f].encode(), i)
                    for f, i in font_ids.items())
    for i in range(n_pages):
        page_ids.append(add(b""))       # placeholder, filled below
        content_ids_page = content_ids[i]

    for i in range(n_pages):
        objects[page_ids[i] - 1] = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.0f %.0f] "
            b"/Resources << /Font << %s >> >> /Contents %d 0 R >>"
            % (pages_id, doc._width(), doc._height(), res, content_ids[i]))

    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objects[pages_id - 1] = (b"<< /Type /Pages /Count %d /Kids [%s] >>"
                             % (n_pages, kids))

    info_bits = [b"/Producer (G-Bible, local, no third-party code)"]
    if doc.title:
        info_bits.append(b"/Title (" + _escape_pdf(doc.title).encode("latin-1", "replace") + b")")
    if doc.author:
        info_bits.append(b"/Author (" + _escape_pdf(doc.author).encode("latin-1", "replace") + b")")
    if doc.subject:
        info_bits.append(b"/Subject (" + _escape_pdf(doc.subject).encode("latin-1", "replace") + b")")
    info_id = add(b"<< " + b" ".join(info_bits) + b" >>")
    objects[cat_id - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, cat_id, info_id, xref))
    return bytes(out)