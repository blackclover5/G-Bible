"""Plain-text and article-structured readers.

Anything that is not verse-keyed is handled here: commentaries, dictionaries,
lexicons-as-text, books, devotionals-as-text, and the Wikisource/Gutenberg
eBook pipeline.  The common shape is "split the text into addressable articles",
which is what makes a commentary linkable to a Bible at all -- a commentary
whose paragraphs carry no verse reference cannot participate in link sets, and
that is a property of the source, not of the reader.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .. import canon, markup
from ..indexer import UnitIn
from ..markup import Seg


# --------------------------------------------------------------------------
# Article splitting
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+.+"
    r"|(?:CHAPTER|Chapter|CHAPTER|CHAPTER)\s+[0-9IVXLC]+[^\n]{0,80}"
    r"|(?:BOOK|Book)\s+[0-9IVXLC]+[^\n]{0,80}"
    r"|(?:PART|Part|SECTION|Section)\s+[0-9IVXLC]+[^\n]{0,80}"
    r"|\d{1,3}\.\s+[A-Z][^\n]{0,70}"
    r"|[A-Z][A-Z0-9 \-'’,.]{6,70}$"
    r")$"
)

# Old-school commentaries anchor each verse with a bold marker:
#   Matthew Henry:  :'''2.''' Let us learn hence ...
#   Clarke/Barnes:   **2.** ...
_VERSE_ANCHOR_RES = [
    re.compile(r"^\s*:?\s*'''(\d{1,3})[a-z]?(?:[.:]?)'''"),
    re.compile(r"^\s*:?\s*\*\*(\d{1,3})[a-z]?(?:[.:]?)\*\*"),
    re.compile(r"^\s*:?\s*'''(\d{1,3})[a-z]?\.'''\s*"),
    re.compile(r"^\s*\[?(\d{1,3})\]?\.\s+\S"),
    re.compile(r"^\s*Verse(?:s)?\s+(\d{1,3})\b", re.I),
    re.compile(r"^\s*\(?\s*v(?:er)?\.?\s*(\d{1,3})"),
]


_HTMLISH = re.compile(
    r"(?is)<\s*(?:html|body|div|p|span|br|li|ul|ol|h[1-6]|table|tr|td|"
    r"scripref|reference|sup|i|b|font|a|strong|em)\b[^>]*>")


def _strip_tags(s: str) -> str:
    return markup.unescape(re.sub(r"<[^>]+>", "", s or ""))


def looks_like_html(text: str) -> bool:
    """SWORD commentaries and e-Sword modules are often HTML or ThML inside a
    .dat file.  Reading them as plain text puts `<SCRIPREF PASSAGE="Lev 19:18">`
    in front of the user, so they are detected and parsed properly."""
    head = (text or "")[:4000]
    hits = len(_HTMLISH.findall(head))
    return hits >= 3 or (hits >= 1 and _ENTITY_RE.search(head) is not None)


def parse_body(text: str, *, wiki: bool = False) -> list:
    if looks_like_html(text):
        return markup.parse_html(text)
    if wiki or _looks_wiki(text.split("\n")):
        return markup.parse_wikitext(text)
    return markup.parse_plain(text)


def detect_kind(path: Path, text: str, hint: str = "") -> str:
    """Guess whether a plain-text file is verse-keyed, article-keyed or a book."""
    head = text[:4000]
    if re.search(r"^\s*\\?\s*(?:Verse|V\.?)\s+\d", head, re.M) and \
       len(re.findall(r"(?mi)^\s*(?:verse|v\.)\s*\d+", text)) > 20:
        return "verse"
    if any(r.search(t) for r in _VERSE_ANCHOR_RES for t in text.split("\n")[:400] if t.strip()) \
       and len(text) > 20000:
        return "commentary"
    if hint:
        return hint
    return "book"


def units_from_articles(text: str, *, kind: str = "Commentary",
                        source: str = "", keep_notes: bool = True,
                        title_from: str = "") -> Iterator[UnitIn]:
    """Split a text into articles, keyed by reference where possible."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_gutenberg(text)
    lines = text.split("\n")

    # ---- try verse anchoring first -----------------------------------
    if kind in ("Commentary", "StudyGuide", "SermonOutline", "Harmony") or \
       detect_kind(Path(source or "x"), text, "") == "commentary":
        got = list(_verse_anchored(lines, keep_notes=keep_notes))
        if got and len(got) > 8:
            yield from got
            return

    # ---- heading-based sections ---------------------------------------
    sections: list[tuple[str, str, list[str]]] = []
    cur_title = title_from or source or "Section 1"
    cur: list[str] = []
    for ln in lines:
        if _HEADING_RE.match(ln) and len(ln.strip()) < 90:
            if any(x.strip() for x in cur):
                sections.append((cur_title, "", cur))
            cur_title = ln.strip().lstrip("#").strip()
            cur = []
            continue
        cur.append(ln)
    if any(x.strip() for x in cur):
        sections.append((cur_title, "", cur))

    if len(sections) <= 1:
        # one big blob: split on blank-line paragraphs, grouped into chunks.
        # `_paragraph_blocks` yields (index, lines); unpacking it as a bare
        # list made `title` the integer index and `"\n".join` a TypeError, so
        # every Project Gutenberg book -- which is exactly this path -- failed.
        for n, blk in _paragraph_blocks(lines):
            title = (blk[0].strip() if blk and blk[0].strip()
                     else f"Section {n}")
            segs = parse_body("\n".join(blk))
            yield UnitIn(key=f"s{n}", label=title, segs=segs, title=title)

    for i, (title, _sub, body) in enumerate(sections, 1):
        segs = markup.parse_wikitext("\n".join(body)) if _looks_wiki(body) \
            else markup.parse_plain("\n".join(body))
        key = _key_for_title(title, i)
        yield UnitIn(key=key, label=title, segs=segs, title=title)


def _key_for_title(title: str, i: int) -> str:
    rr = canon.parse_ref(title) or canon.parse_ref(_loosen(title))
    if rr:
        return rr.start.osis_id()
    m = re.search(r"\b(\d{1,3})\b", title)
    if m:
        return f"c{m.group(1)}"
    m = re.search(r"\b([A-Z][A-Za-z]{2,})\b", title)
    if m:
        return "t" + m.group(1)[:24]
    return f"s{i}"


def _loosen(title: str) -> str:
    """'CHAP. I.' / 'Ver. 3' style headings -> something parse_ref accepts."""
    t = title
    m = re.match(r"\s*(?:Chap(?:ter)?\.?|Ver(?:se)?\.?)\s*([0-9IVXLC]+)", t, re.I)
    if m:
        v = _roman(m.group(1))
        return f"1 {v}" if v else ""
    return t


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
          "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "l": 50, "c": 100,
          "d": 500, "m": 1000}


def _roman(s: str) -> int:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    total, prev = 0, 0
    for ch in reversed(s):
        v = _ROMAN.get(ch, 0)
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total or 0


def _verse_anchored(lines: list[str], *, keep_notes: bool = True) -> Iterator[UnitIn]:
    """Matthew Henry / Clarke / Barnes style: bold verse numbers anchor the text.

    A running `Book Chapter` is tracked from the headings, so `'''2.'''` becomes
    Gen.1.2 rather than an orphan.
    """
    book = ""
    chapter = 0
    cur_key = ""
    cur: list[str] = []
    n = 0

    def flush() -> UnitIn | None:
        nonlocal cur_key, cur
        if not cur_key or not any(x.strip() for x in cur):
            cur_key, cur = "", []
            return None
        body = "\n".join(cur)
        segs = parse_body(body)
        u = UnitIn(key=cur_key, label=_label(cur_key), segs=segs,
                   title=_title_from_key(cur_key))
        cur_key, cur = "", []
        return u

    for ln in lines:
        m = re.match(r"^\s*#*\s*(?:Chapter|CHAPTER)\s+([0-9IVXLC]+)", ln)
        if m:
            u = flush()
            if u:
                yield u
            chapter = _roman(m.group(1))
            if book:
                cur_key = ""
            continue
        m = re.match(r"^\s*#*\s*(?:Book|BOOK)\s+([0-9IVXLC]+)", ln)
        if m:
            u = flush()
            if u:
                yield u
            chapter = 0
            continue
        m = _book_from_heading(ln)
        if m:
            u = flush()
            if u:
                yield u
            book, chapter = m, 0
            continue
        anchor = None
        for r in _VERSE_ANCHOR_RES:
            am = r.match(ln)
            if am:
                anchor = int(am.group(1))
                break
        if anchor is not None and book:
            u = flush()
            if u:
                yield u
            n += 1
            cur_key = f"{book}.{chapter or 1}.{anchor}"
            cur = [ln]
            continue
        if cur_key:
            cur.append(ln)
    u = flush()
    if u:
        yield u


_BOOK_HEAD = re.compile(
    r"^\s*#*\s*(?:The\s+)?(First|Second|Third|1st|2nd|3rd)?\s*"
    r"(Book of\s+)?(Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|"
    r"Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Esther|Job|Psalms?|Proverbs|"
    r"Ecclesiastes|Song of Solomon|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|"
    r"Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|"
    r"Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|"
    r"Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|"
    r"Hebrews|James|Peter|John|Jude|Revelation)\b",
    re.I)


def _book_from_heading(ln: str):
    m = _BOOK_HEAD.match(ln)
    if not m:
        return None
    ord_part = (m.group(1) or "").lower()
    name = m.group(3).lower()
    if name in ("samuel", "kings", "chronicles", "corinthians", "thessalonians",
                "timothy", "peter", "john"):
        lead = {"first": "1", "second": "2", "third": "3", "1st": "1",
                "2nd": "2", "3rd": "3"}.get(ord_part, "1")
        cand = f"{lead} {name}"
    else:
        cand = name
    b = canon.lookup_book(cand)
    return b.osis if b else None


def _label(key: str) -> str:
    p = key.split(".")
    if len(p) == 3 and p[1].isdigit() and p[2].isdigit():
        return canon.format_ref(canon.Ref(p[0], int(p[1]), int(p[2])))
    return key


def _title_from_key(key: str) -> str:
    return _label(key)


def _looks_wiki(lines: list[str]) -> bool:
    for ln in lines[:80]:
        if re.search(r"\[\[|\{\{|'''|</?ref|<div", ln):
            return True
    return False


_ENTITY_RE = re.compile(r"&#\d+;|&[a-z]+;|\s\+[A-Za-z0-9]{1,12}\s\d{1,3}:\d{1,3}",
                        re.I)

_GUT_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                         re.I | re.S)
_GUT_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                       re.I | re.S)


def _strip_gutenberg(text: str) -> str:
    m = _GUT_START.search(text)
    if m:
        text = text[m.end():]
    m = _GUT_END.search(text)
    if m:
        text = text[:m.start()]
    return text


def _paragraph_blocks(lines: list[str], size: int = 3
                      ) -> Iterator[tuple[int, list[str]]]:
    block: list[str] = []
    empties = 0
    n = 0
    for ln in lines:
        if not ln.strip():
            empties += 1
            if empties >= 2 and block:
                n += 1
                yield n, block
                block = []
                empties = 0
            continue
        empties = 0
        block.append(ln)
    if block:
        n += 1
        yield n, block


# --------------------------------------------------------------------------
# Wikisource
# --------------------------------------------------------------------------

def units_from_wikitext_pages(pages: list[tuple[str, str]], *,
                              kind: str = "Commentary",
                              keep_notes: bool = True) -> Iterator[UnitIn]:
    """pages: [(page_title, wikitext)].

    The old-school commentaries are published one page per chapter
    (`.../Volume 1/Genesis/Chapter 1`), with each verse marked by a bold number.
    The page title therefore supplies book+chapter and the body is split on those
    anchors, which is what makes the result verse-keyed and therefore linkable.
    """
    for title, text in pages:
        book, chapter = _page_to_ref(title)
        if book and chapter:
            got = False
            for u in _verse_anchored([f"CHAPTER {chapter}"] + text.split("\n"),
                                     keep_notes=keep_notes):
                got = True
                yield u
            if got:
                continue
        segs = markup.parse_wikitext(text)
        if not segs:
            continue
        head = next((s.text for s in segs if s.kind in ("title", "heading")), "")
        label = head or title
        yield UnitIn(key=_key_for_title(label, 0) or title[:60],
                     label=label, segs=segs, title=head or label)


def _page_to_ref(title: str) -> tuple[str, int]:
    m = re.search(r"/([^/]+)/Chapter\s+(\d+)\s*$", title)
    if not m:
        return "", 0
    b = canon.lookup_book(m.group(1))
    return (b.osis, int(m.group(2))) if b else ("", 0)
