"""USFX and OSIS: single-file XML Bibles.

Both formats are a flat, well-formed document of book / chapter / verse
milestones, and both are common in the open repositories (eBible.org's USFX
schema, and the OSIS files converted from it).  They are close enough to share
a reader, which is why this is one module rather than two.

The shapes that matter:

**USFX** — verses are empty `<v id="N" bcv="GEN.1.1"/>` elements that *precede*
their text, and the text sits in sibling `<p>` elements:

    <book id="GEN"><h>Genesis</h>
      <c id="1"/><s style="s1">The Creation</s>
      <p sfm="m"><v id="1" bcv="GEN.1.1"/><w s="H8064">In</w> the beginning
      <ve/></p>

The `<w s="H8064">` attribute is a Strong's number, which is why USFX is worth
supporting properly: it carries morphology-grade tagging that the plain-text
formats do not.

**OSIS** — verse milestones are self-closing and the text follows the marker,
and books are `<div type="book" osisID="Gen">`:

    <div type="book" osisID="Gen"><title>Genesis</title>
      <chapter osisRef="Gen.1" n="1"/>
      <p><verse osisID="Gen.1.1" n="1"/>In the beginning...

Note the OSIS convention of repeating a verse element with `eID` at the *end* of
the verse; those are closed and ignored, or they would double every verse.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .. import canon
from ..markup import Seg, unescape

_OSIS_NS = "{http://www.bibletechnologies.net/2003/OSIS/namespace}"


def sniff_usfx(data: bytes) -> bool:
    return b"<usfx" in data[:4096]


def sniff_osis(data: bytes) -> bool:
    head = data[:8192]
    return (b"osisText" in head or b"osisCore" in head
            or (b"<osis" in head and b"bibletechnologies" in head))


def sniff(data: bytes) -> str:
    if sniff_usfx(data):
        return "usfx"
    if sniff_osis(data):
        return "osis"
    return ""


# --------------------------------------------------------------------------
# USFX
# --------------------------------------------------------------------------

# Annotation and apparatus elements.  These are *not* scripture: skipping them
# is what keeps a footnote -- "<fr>3:16</fr><ft>Or only begotten</ft>" -- from
# being read as part of the verse.
_USFX_SKIP = ("ve", "note", "hi", "toc", "id", "p", "s", "h", "book", "bk",
              "lb", "ms", "sl", "sr", "fig", "fr", "ft", "table", "thead",
              "tbody", "row", "cell", "caption", "alt", "list", "item")
_OSIS_SKIP = ("note", "hi", "header", "title", "transChange", "figure",
              "fig", "list", "lb", "milestone", "figure", "table")


class _State:
    __slots__ = ("book", "chapter", "verse", "segs", "title")

    def __init__(self):
        self.book = ""
        self.chapter: object = ""
        self.verse = 0
        self.segs: list = []
        self.title = ""


def _flush(st, emit):
    """Close the span accumulated so far.  Called only at a milestone or at the
    end of a book -- never on the way out of a nested element, which is what
    would split a verse at every footnote."""
    segs, st.segs = st.segs, []
    if not (st.verse and st.book and st.chapter):
        return
    # ElementTree resolves the five XML entities but leaves the rest alone, so
    # "Athen&#xE6;an" and "&quot;" would reach the reader as written.  The
    # numeric forms matter: they are how this corpus spells æ, œ and ß.
    if any("&" in s.text for s in segs):
        segs = [s._replace(text=unescape(s.text)) for s in segs]
    # Notes and references share the segment stream but are not Bible text.
    text = "".join(s.text for s in segs if s.is_text())
    if not text.strip():
        return
    key = f"{st.book} {st.chapter}:{st.verse}"
    emit(key, key, text, st.book, st.chapter, st.verse, list(segs))


def _usfx_walk(el, st, emit, red=False):
    if (el.text or "").strip():
        st.segs.append(Seg("red" if red else "text", el.text))
    for child in list(el):
        tag = child.tag
        if tag == "c":
            _flush(st, emit)
            st.chapter = (child.get("id") or "").strip()
            st.verse = 0
        elif tag == "v":
            _flush(st, emit)
            try:
                st.verse = int((child.get("id") or "0").strip())
            except ValueError:
                st.verse = 0
            # In USFX the verse marker is self-closing and the verse's words are
            # the text that follows it, so the words are this element's tail.
            if child.text:
                st.segs.append(Seg("text", child.text))
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "ve":
            if child.tail:
                st.segs.append(Seg("text", child.tail))
        elif tag == "book":
            # open-bibles nests its books: <usfx><book GEN><book EXO>...</book>
            # is one file, and every <book> is walked once on its own content.
            # Descending here instead would walk Genesis once per containing
            # book and emit each verse 66 times.
            if child.tail:
                st.segs.append(Seg("text", child.tail))
        elif tag in _USFX_SKIP:
            if tag == "h":
                st.title = (child.text or "").strip()
            elif tag in ("p", "s", "id", "toc", "lb", "ms", "bk"):
                _usfx_walk(child, st, emit, red=red)  # containers carry content
        elif tag in ("f", "x"):
            body = " ".join("".join(child.itertext()).split())
            if body:
                kind = "crossReference" if tag == "x" else "explanation"
                ref = ""
                for part in child.iter():
                    if part.tag.rsplit("}", 1)[-1] in ("fr", "xo"):
                        ref = " ".join("".join(part.itertext()).split())
                        break
                st.segs.append(Seg("note", body, ref, kind,
                                   {"placement": "foot"}))
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "wj":
            _usfx_walk(child, st, emit, red=True)
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "w":
            txt = "".join(child.itertext())
            if txt:
                snum = (child.get("s") or "").strip()
                st.segs.append(Seg("strongs" if snum else ("red" if red else "text"),
                                   txt, snum, lemma=(child.get("lemma") or "").strip(),
                                   attrs={"wj": True} if red else {}))
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag in ("transChange", "seg", "add"):
            txt = "".join(child.itertext())
            if txt:
                st.segs.append(Seg("add", txt))
            if child.tail:
                st.segs.append(Seg("text", child.tail))
        else:
            _usfx_walk(child, st, emit, red=red)
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))


def _usfx_units(root):
    rows = []

    def emit(key, label, text, book, chapter, verse, segs):
        rows.append({"key": key, "label": label, "text": text, "book": book,
                     "chapter": chapter, "verse": verse, "segs": segs,
                     "markup": f"{key} {text}"})

    by_id: dict[str, str] = {}
    for code, b in canon.BOOK_BY_USFM.items():
        by_id.setdefault(code.upper(), b.osis)
        by_id.setdefault(b.osis.upper(), b.osis)
    # open-bibles nests its books (<usfx><book GEN><book EXO>...</book></book>
    # is a single file), so every <book> is walked once, on its own content only
    # -- _usfx_walk does not descend into a nested <book>.  Filtering to
    # "outermost" instead would read only the first book in the file.
    for book in root.iter("book"):
        raw = (book.get("id") or "").strip()
        osis = by_id.get(raw.upper())
        if not osis:
            continue
        st = _State()
        st.book = osis
        _usfx_walk(book, st, emit)
        _flush(st, emit)
    return rows


# --------------------------------------------------------------------------
# OSIS
# --------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _osis_nums(el, want: int):
    """The chapter (want=1) or verse (want=2) number of an OSIS element.

    A chapter/verse may number itself with `n` or only carry an `osisID`; the
    Albanian OSIS in open-bibles uses `<chapter osisID='Gen.1'>` and
    `<verse osisID='Gen.1.1'>` with no `n` at all, so reading `n` alone yields 0
    and every verse is then discarded for having no number.  Prefer `n` and fall
    back to the reference.
    """
    try:
        n = int(el.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    if n:
        return n
    oid = (el.get("osisID") or el.get("osisIDRef") or "").strip()
    ref = canon.parse_osis_id(oid) if oid else None
    if ref is None:
        return 0
    return (ref.chapter if want == 1 else ref.verse) or 0


def _osis_walk(el, st, emit, red=False):
    if (el.text or "").strip():
        st.segs.append(Seg("red" if red else "text", el.text))
    for child in list(el):
        tag = _local(child.tag)
        if tag == "chapter":
            _flush(st, emit)
            st.chapter = _osis_nums(child, 1) or ""
            st.verse = 0
            # The verses live inside the chapter (div > chapter > verse), so
            # recurse: without this the chapter's own text and every verse in
            # it are never visited and the document yields no units at all.
            _osis_walk(child, st, emit, red=red)
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "verse":
            if child.get("eID") and not child.get("osisID"):
                # A closing milestone for the verse just read.  It ends the verse
                # and starts none; its own tail is only the gap to the next tag.
                _flush(st, emit)
                st.verse = 0
                continue
            _flush(st, emit)
            st.verse = _osis_nums(child, 2)
            if list(child):
                _osis_walk(child, st, emit, red=red)  # <w>, <note>, ... inside
            elif child.text:
                st.segs.append(Seg("red" if red else "text", child.text))
            # An OSIS verse is a milestone: <verse osisID="Gen.1.1"/>In the
            # beginning...  -- the words are the element's tail, not its text.
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "note":
            body = " ".join("".join(child.itertext()).split())
            if body:
                st.segs.append(Seg("note", body,
                                   child.get("osisRef") or child.get("osisID") or "",
                                   child.get("type") or "explanation",
                                   {"placement": child.get("placement", "foot")}))
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "q" and _speaker_is_jesus(child.get("who", "")):
            _osis_walk(child, st, emit, red=True)
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag in _OSIS_SKIP:
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        elif tag == "w":
            txt = "".join(child.itertext())
            if txt:
                snum = (child.get("strongRef") or child.get("s") or "").strip()
                st.segs.append(Seg("strongs" if snum else "text", txt, snum,
                                   lemma=(child.get("lemma") or "").strip(),
                                   attrs={"wj": True} if red else {}))
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))
        else:
            _osis_walk(child, st, emit, red=red)
            if child.tail:
                st.segs.append(Seg("red" if red else "text", child.tail))


def _speaker_is_jesus(raw: str) -> bool:
    """Accept explicit OSIS Jesus identifiers; do not infer from context."""
    return any(re.fullmatch(r"#?Jesus", token, re.I)
               for token in re.split(r"[\s,;]+", (raw or "").strip()) if token)


def _osis_units(root):
    rows = []

    def emit(key, label, text, book, chapter, verse, segs):
        rows.append({"key": key, "label": label, "text": text, "book": book,
                     "chapter": chapter, "verse": verse, "segs": segs,
                     "markup": f"{key} {text}"})

    for div in root.iter():
        if _local(div.tag) != "div" or div.get("type") != "book":
            continue
        book = div.get("osisID") or ""
        if not book:
            continue
        st = _State()
        st.book = book
        _osis_walk(div, st, emit)
        _flush(st, emit)
    return rows


# --------------------------------------------------------------------------
# Entry points used by the importers
# --------------------------------------------------------------------------

def _parse_lenient(data: bytes):
    """Parse XML, repairing a document that is truncated or has a stray close.

    Two defects in this corpus are worth repairing rather than refusing:

    * A file cut off mid-element -- open-bibles' eng-bbe.usfx.xml stops after
      Rev 22:21 with nothing closed, and a strict parse loses the whole Bible
      rather than the last verse.
    * A file with one closing tag too many -- heb-leningrad.usfx.xml has 38
      `<book>` and 39 `</book>`, which is a parse error at line 1221 and again
      costs every book before it.

    Both are repaired by rebuilding the tag stream against a stack: drop a close
    that matches nothing, and close whatever is left open at the end.  A
    well-formed document is parsed strictly and never reaches the repair.
    """
    try:
        return ET.fromstring(data), False
    except ET.ParseError:
        pass
    src = data.decode("utf-8", "replace")
    out: list[str] = []
    stack: list[str] = []
    pos = 0
    for m in re.finditer(r"<(/?)([A-Za-z_][\w.:-]*)((?:\s[^<>]*?)?)(/?)>", src):
        out.append(src[pos:m.start()])
        pos = m.end()
        closing, name, _attrs, selfclose = m.groups()
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
                out.append(m.group(0))
            # else: a close that matches nothing open -- drop it.
            continue
        out.append(m.group(0))
        if not selfclose and not _attrs.rstrip().endswith("/"):
            stack.append(name)
    out.append(src[pos:])
    out.append("".join(f"</{n}>" for n in reversed(stack)))
    return ET.fromstring("".join(out)), True


def load_usfx(data: bytes):
    """Return (units, meta) for a USFX document."""
    root, repaired = _parse_lenient(data)
    lang = ""
    for el in root:
        if el.tag == "languageCode":
            lang = (el.text or "").strip()
    out = _usfx_units(root)
    if not out:
        raise ValueError("no verses parsed from USFX")
    meta = {"format": "USFX", "lang": lang}
    if repaired:
        # The caller records this in the module's description; it is not a
        # module column.
        meta["truncated"] = True
    return out, meta


def load_osis(data: bytes):
    """Return (units, meta) for an OSIS document."""
    root, repaired = _parse_lenient(data)
    lang = ""
    for el in root.iter():
        if el.tag.endswith("osisText") or el.get("xml:lang"):
            lang = el.get("xml:lang") or lang
            if lang:
                break
    out = _osis_units(root)
    if not out:
        raise ValueError("no verses parsed from OSIS")
    meta = {"format": "OSIS", "lang": lang}
    if repaired:
        meta["truncated"] = True
    return out, meta
