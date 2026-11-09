"""USFM 2.x / 3.x reader.

Used by eBible.org, Paratext and most open translation repositories.  A USFM
module is a zip of one file per book, named `<NN>-<USFM-ABBR><module-id>.usfm`,
which is also where the canonical book order comes from -- more reliable than
guessing from the chapter count, because eBible's USFM chapter numbering
follows the 1611 versification (Genesis has 50 chapters, not 48).

Markers carrying inline character data are turned straight into Segments, so
eBible's own Strong's tagging (`\\w word|strong="H7225"\\w*`) survives into the
index with no second pass.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Iterator

from .. import canon, markup
from ..indexer import UnitIn
from ..markup import Seg


class UsfmError(Exception):
    pass


# A USFM marker: \name, optionally prefixed with the "plus" delimiter (\+w) so
# older parsers do not recognise it.  eBible emits \+w around every Strong's-
# tagged word, so the delimiter has to be part of the token, not a literal.
_TOKEN_RE = re.compile(r"\\\+?([A-Za-z0-9_]+)(\*)?((?:[^\n\\]|\\(?![A-Za-z0-9_+]))*)")

# Front matter and markers whose text is not scripture.
_SKIP = {
    "usfm", "ide", "cvs", "sts", "periph", "toc", "toc1", "toc2", "toc3",
    "mt", "mt1", "mt2", "mt3", "mt4", "rm", "rb", "rv", "sxt", "coa", "pr",
    "rem", "fig", "figure", "caption", "attrib", "ms", "ms1", "ms2", "mss",
    "eph", "ph", "ph1", "ph2", "ph3", "ps", "ps1", "ps2", "ps3", "ip", "ip1",
    "ip2", "ip3", "iq", "iq1", "iq2", "ie", "im", "im1", "im2", "ior", "iot",
    "io1", "io2", "is", "is1", "is2", "ipr", "ic", "lit", "mr", "sr", "sp",
    "va", "vp", "z", "zm", "zp", "free", "fe", "fe1", "fe2", "fe3", "fr",
    "s", "s1", "s2", "s3", "s4", "r", "q", "q1", "q2", "q3", "q4", "qi",
    "qm", "qm1", "qm2", "qm3", "qs", "qc", "qr", "po", "pc", "mi", "nb",
    "cls", "cp", "lit",
}

# Book-title / heading markers we DO keep, as unit titles.
_TITLE_MARKERS = {"h", "h1", "h2", "h3", "h4", "mt", "mt1", "mt2", "mt3", "mt4"}

_NOTE_MARKERS = {"f", "fe", "fe1", "fe2", "fdc", "ef", "efm", "ef1", "ef2",
                 "x", "xdc", "xr", "xnt", "ex", "exdc", "rem"}
_XREF_ONLY = {"x", "xdc", "xr", "xnt", "exdc", "ef1", "ef2", "fe1", "fe2"}

# Inline styled characters -> segment kind
_INLINE_STYLE = {
    "add": "add", "addce": "add", "addsl": "add", "addpn": "add",
    "transChange": "alt", "alt": "alt", "unclear": "text",
    # USFM explicitly brackets words of Jesus; never infer these from quotes.
    "wj": "red",
}


class UsfmDoc:
    def __init__(self, text: str, *, usfm_id: str = "", module_id: str = "",
                 title: str = "", keep_notes: bool = True):
        self.raw = text.replace("\r\n", "\n").replace("\r", "\n")
        self.usfm_id = usfm_id or ""
        self.module_id = module_id
        self.keep_notes = keep_notes
        self.title = title
        self.book = _resolve_book(self.usfm_id)

    # ------------------------------------------------------------------
    def units(self) -> Iterator[UnitIn]:
        if self.book is None:
            return
        segs: list[Seg] = []
        chapter = 0
        verse = 0
        book_title = ""
        sec_title = ""
        pending_key = ""
        notes: list[dict] = []
        buf: list[str] = []
        style_stack: list[str] = []
        pos = 0
        raw = self.raw

        def flush_text() -> None:
            # Newlines in USFM are source formatting, not structure: paragraph
            # breaks are carried by \p / \q / \m markers, which already emit a
            # paragraph segment.  Everything else is inline whitespace.
            t = markup.collapse(markup.unescape("".join(buf).replace("\n", " ")))
            buf.clear()
            if not t:
                return
            seg = Seg(style_stack[-1] if style_stack else "text", t)
            (notes[-1]["segs"] if notes else segs).append(seg)

        def push(seg: Seg) -> None:
            (notes[-1]["segs"] if notes else segs).append(seg)

        # A generator cannot both yield and be nested inside flush_text, so the
        # units are collected here and yielded at the end.  A bible is at most a
        # few tens of thousands of verses, which is nothing next to the source
        # text we just read.
        out: list[UnitIn] = []

        for m in _TOKEN_RE.finditer(raw):
            text = raw[pos:m.start()]
            pos = m.end()
            if text:
                buf.append(text)
            marker = m.group(1)
            closed = bool(m.group(2))
            rest = m.group(3) or ""
            mk = marker.lower()

            if mk == "c":
                flush_text()
                mc = re.match(r"\s*(\d+)", rest)
                if mc:
                    chapter = int(mc.group(1))
                    verse = 0
                    sec_title = ""
                continue
            if mk == "v":
                # A \v marker OPENS a verse: everything already accumulated
                # belongs to the previous one, and the text after it belongs to
                # this one.  Getting this backwards shifts the whole book.
                flush_text()
                mv = re.match(r"\s*(\d+)([^\s|]*)\s*(\|([^|]*)\|)?(.*)", rest, re.S)
                if not mv:
                    continue
                if pending_key:
                    out.append(_mk(self.book, pending_key, segs,
                                   sec_title or self.book.name,
                                   extra={"doc_title": book_title or self.title}))
                verse = int(mv.group(1))
                pending_key = f"{self.book.osis}.{chapter}.{verse}"
                segs = []
                tail = mv.group(5)
                if tail.strip():
                    buf.append(tail)
                continue
            if mk == "id":
                flush_text()
                if not self.usfm_id:
                    self.usfm_id = rest.split()[0] if rest.split() else ""
                    self.book = _resolve_book(self.usfm_id) or self.book
                continue
            if mk in ("h", "h1") and not closed:
                flush_text()
                sec_title = markup.collapse(rest).strip()
                continue
            if mk in _TITLE_MARKERS:
                flush_text()
                if not book_title:
                    book_title = markup.collapse(rest).strip()
                continue
            if mk == "w" and not closed:
                flush_text()
                body, attrs = _split_attr(rest)
                strong = ""
                ms = re.search(r'strong="?([A-Za-z0-9]+)"?', attrs)
                if ms:
                    strong = ms.group(1)
                # the space between \w and its content is a separator, not text
                t = markup.collapse(markup.unescape(body).replace("\n", " ")).strip()
                if t:
                    push(Seg("strongs" if strong else "text", t, strong))
                continue
            if mk in _INLINE_STYLE and not closed:
                flush_text()
                style_stack.append(_INLINE_STYLE[mk])
                body, attrs = _split_attr(rest)
                t = markup.collapse(markup.unescape(body).replace("\n", " ")).strip()
                if t:
                    push(Seg(_INLINE_STYLE[mk], t))
                continue
            if mk in _NOTE_MARKERS and not closed:
                flush_text()
                kind = "crossReference" if mk in _XREF_ONLY else "note"
                notes.append({"kind": kind, "segs": [], "ref": rest.strip()})
                continue
            if notes and closed:
                flush_text()
                n = notes.pop()
                if self.keep_notes:
                    body = markup.collapse(
                        markup.unescape("".join(s.text for s in n["segs"])))
                    push(Seg("note", body, n["ref"] or "", n["kind"],
                             {"placement": "foot"}))
                continue
            if mk == "q" and not closed:
                flush_text()
                segs.append(Seg("para", " "))
                continue
            if mk in _SKIP:
                flush_text()
                if closed and style_stack and _INLINE_STYLE.get(mk):
                    style_stack.pop()
                continue
            if style_stack and closed and _INLINE_STYLE.get(mk):
                flush_text()
                style_stack.pop()
            # Unknown marker: pass its text through.
            if rest and not rest.startswith("*"):
                flush_text()
                buf.append(rest)

        flush_text()
        if pending_key:
            out.append(_mk(self.book, pending_key, segs,
                           sec_title or self.book.name,
                           extra={"doc_title": book_title or self.title}))
        yield from out


def _mk(book, key: str, segs: list[Seg], title: str,
        extra: dict | None = None) -> UnitIn:
    parts = key.split(".")
    return UnitIn(key=key, label=_label(key), segs=markup._run(segs),
                  markup="", book=parts[0], chapter=int(parts[1]),
                  verse=int(parts[2]), title=title, extra=dict(extra or {}))


def _split_attr(rest: str) -> tuple[str, str]:
    if "|" not in rest:
        return rest, ""
    body, _, attrs = rest.partition("|")
    return body, attrs


def _label(key: str) -> str:
    p = key.split(".")
    if len(p) < 3:
        return key
    return canon.format_ref(canon.Ref(p[0], int(p[1]), int(p[2])))


_NONCANON = {
    "HEB": "Gen", "GRC": "Gen", "DUT": "Gen", "SLA": "Gen", "MAC": "Gen",
    "ARO": "Rev", "BES": "Job", "GLS": "Gen", "KJV": "Gen", "WEB": "Gen",
    "GEN": "Gen", "MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John",
    "ACT": "Acts", "ROM": "Rom", "COR": "1Cor", "GAL": "Gal", "EPH": "Eph",
    "PHP": "Phil", "COL": "Col", "THS": "1Thess", "TIM": "1Tim", "TIT": "Titus",
    "PHM": "Phlm", "HEB2": "Heb", "JAS": "Jas", "PET": "1Pet", "JUD": "Jude",
    "REV": "Rev", "PSA": "Ps", "PRO": "Prov", "ECC": "Eccl", "SNG": "Song",
    "ISA": "Isa", "JER": "Jer", "LAM": "Lam", "EZE": "Ezek", "DAN": "Dan",
    "HOS": "Hos", "JOL": "Joel", "AMO": "Amos", "OBA": "Obad", "JON": "Jonah",
    "MIC": "Mic", "NAA": "Nah", "HAB": "Hab", "ZEP": "Zeph", "HAG": "Hag",
    "ZEC": "Zech", "MAL": "Mal", "EXO": "Exod", "LEV": "Lev", "NUM": "Num",
    "DEU": "Deut", "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth",
}


def _resolve_book(usfm_id: str):
    if not usfm_id:
        return None
    u = usfm_id.strip().upper()[:3]
    b = canon.BOOK_BY_USFM.get(u)
    if b:
        return b
    osis = _NONCANON.get(u)
    return canon.BOOK_BY_OSIS.get(osis) if osis else None


# --------------------------------------------------------------------------
# Zip / directory entry points
# --------------------------------------------------------------------------

def usfm_from_zip(zf: zipfile.ZipFile, *, keep_notes: bool = True,
                  wanted: set[str] | None = None) -> Iterator[UnitIn]:
    names = sorted((n for n in zf.namelist() if n.lower().endswith(".usfm")),
                   key=_bookfile_sort)
    for n in names:
        m = re.match(r"(?:^|/)(\d{2})-([A-Za-z0-9]{3})(.*)\.usfm$", n, re.I)
        if not m:
            continue
        usfm_id = m.group(2)
        if wanted and usfm_id.upper() not in wanted:
            continue
        raw = zf.read(n).decode("utf-8", "replace")
        doc = UsfmDoc(raw, usfm_id=usfm_id, module_id=m.group(3).strip("-_"),
                      keep_notes=keep_notes)
        if doc.book is None:
            continue
        yield from doc.units()


def _bookfile_sort(n: str) -> tuple:
    m = re.match(r"(?:^|/)(\d{2})-", n)
    return (int(m.group(1)) if m else 99, n)


def usfm_from_dir(root: Path, *, keep_notes: bool = True) -> Iterator[UnitIn]:
    for p in sorted(root.rglob("*.usfm")):
        raw = p.read_text(encoding="utf-8", errors="replace")
        m_id = re.search(r"^\\id\s+(\S+)", raw, re.M)
        doc = UsfmDoc(raw, usfm_id=m_id.group(1) if m_id else "",
                      keep_notes=keep_notes)
        if doc.book is None:
            b = canon.lookup_book(p.stem.split("-")[0])
            if b is None:
                continue
            doc.book = b
        yield from doc.units()
