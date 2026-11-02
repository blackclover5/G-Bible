"""Build the bundled Bible outlines from Jamieson, Fausset & Brown (1871).

    python3 tools/build_outlines.py            # download and rebuild the data file
    python3 tools/build_outlines.py --epub PATH
    python3 tools/build_outlines.py --check    # report what is bundled, no download

Why this exists
---------------
Every request for a Bible outline used to be answered with "no outline data is
installed", which was true and useless.  An outline is editorial -- nobody can
derive one from the text -- so it has to come from a book.

JFB is the right book for this:

  * It is public domain.  The 1871 first American edition is out of copyright
    everywhere it matters, and CrossWire -- which distributes the same work in
    its own SWORD package -- records it as "Public Domain".  That matters here
    because the project licence covers the software and explicitly not the
    material, and tools/license_audit.py checks what is committed.
  * It covers all 66 books, so the outline browser has no gaps and nothing
    marked "coming soon".
  * CCEL serves it as an EPUB whose spine is one XHTML file per chapter, so each
    chapter is independently addressable and the parse is plain regex over
    markup -- no XML namespaces, no build step.

The shape of the file
---------------------
The spine is a three-level dotted path, and the levels are *testament, book,
chapter*:

    jfb.x.i.i.html      Old Testament, book 1 (Genesis), chapter 1
    jfb.xi.xlvi.i.html  New Testament, book 46 (John), chapter 1
    jfb.xiv.i.i.html    the three apocryphal books, which we skip

There is no book name anywhere in the path, so the book has to come from the
spine's *order* -- which is canonical order -- cross-checked against the chapter
label and the first scripture reference in the file's own text.  Guessing the
book from the filename is how you get 39 chapters of Psalms filed under Genesis.

What is kept
------------
Only the skeleton: for each chapter, its numbered sections, their verse ranges,
their headings and any sub-headings.  The commentary prose, the word glosses and
the per-verse notes are dropped -- 24 MB of text that belongs in a commentary
resource, not in an outline index.  What survives is about 1.3 MB of JSON, 350 KB
gzipped, and it is the whole of what the outline browser draws.

Licence
-------
CCEL's electronic wrapper for JFB carries a "Copyright 2010 CCEL" notice in its
front matter (`jfb.about.html`).  That covers CCEL's own editorial additions and
packaging, not the 1871 text, and this build drops the front matter entirely: the
file contains nothing but the 1871 chapter headings.  The attribution string the
app displays says so, rather than quietly claiming more than we took.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import urllib.request
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import canon                                              # noqa: E402

OUT = ROOT / "gbible" / "data" / "outlines.json.gz"
EPUB_URL = "https://ccel.org/ccel/j/jamieson/jfb/cache/jfb.epub"

SOURCE = "jfb1871"
TITLE = "Jamieson, Fausset & Brown"
ATTRIBUTION = ("Critical and Explanatory Commentary on the Whole Bible (1871), "
               "via CCEL — Public Domain")
#: Shown beside the outline rather than hidden, because an outline with no
#: voice is easily mistaken for the shape of the text itself.
NOTE = ("These headings are Jamieson, Fausset and Brown's own. JFB is a Reformed "
        "commentary from 1871 and it argues; read it as one reading of the text, "
        "not as the shape the text has.")

#: Spine roots that are part of the 66-book canon.  `xiv` is the apocrypha.
OT_ROOT, NT_ROOT = "x", "xi"
OT_BOOKS = 39          # Genesis .. Malachi
NT_BOOKS = 27          # Matthew .. Revelation

_TAG = re.compile(r"<[^>]+>")
_SC = re.compile(r'<span class="sc">(.*?)</span>', re.S)
_SCRIP = re.compile(r'class="scripRef"[^>]*>(.*?)</a>', re.S)
_SECTION = re.compile(r'<div class="Commentary"[^>]*>(.*?)\n</div>', re.S)
_CHAPTER_LABEL = re.compile(r"(?:CHAPTER|PSALM)\s+([0-9]+|[ivxl]+)", re.I)
#: A block that opens on a bold verse number is a continuation, not a point.
_VERSE_NOTE = re.compile(r"^\s*<b>\s*(\d+[.:]?\d*)")
#: A bare capitalised name is a scholar being quoted, not a section heading:
#: JFB runs "Olshausen" and "Alford" in the same small-caps span as a heading.
_PROPER_NOUN = re.compile(r"^\s*[A-Z][a-z]{2,}\.?\s*$")
#: A point opens with its verse range, before any prose.
_LEADS_WITH_REF = re.compile(r'^\s*<a[^>]*class="scripRef"')
#: "Ge 1:1, 2", "Mt 9:9", "Phm 1-25", "Ps 119:1-8; 105:  — a run of references.
_REF = re.compile(
    r"((?:[1-3]?[A-Za-z]{1,4}\s+)?\d+(?::\d+(?:-\d+)?)?"
    r"(?:\s*(?:,|and|;|ff?\.?|–|-)\s*[0-9:;\s]*)*)")


def _text(s: str) -> str:
    s = _TAG.sub("", s).replace("<", "")
    return re.sub(r"\s+", " ", unescape(s)).strip()


def _spine() -> list[tuple[str, str]]:
    """[(id, href)] in reading order, from the package document."""
    with zipfile.ZipFile(_EPUB) as z:
        doc = ElementTree.fromstring(z.read("META-INF/container.xml"))
        rootfile = next(e.get("full-path") for e in doc.iter()
                        if e.tag.endswith("rootfile"))
        opf = ElementTree.fromstring(z.read(rootfile))
        href = {e.get("id"): e.get("href") for e in opf.iter()
                if e.tag.endswith("item") and e.get("id")}
        out = []
        for e in opf.iter():
            if e.tag.endswith("itemref"):
                h = href.get(e.get("idref"))
                if h:
                    out.append((e.get("idref"), h))
        return out


_EPUB: Path | None = None


def parse(epub_path: Path) -> dict:
    """Read the EPUB and return {osis: {chapter: [section, ...]}}."""
    global _EPUB
    _EPUB = epub_path
    spine = _spine()
    # Canonical order, taken from the app's own book list rather than a table
    # here: if the canon ever changes, the outlines follow it.
    names = [b.osis for b in canon.BOOKS_66]
    books: dict[str, dict] = {}

    with zipfile.ZipFile(epub_path) as z:
        members = set(z.namelist())
        order: list[tuple[str, int, int, str]] = []   # root, book ix, chapter, href
        counters = {OT_ROOT: 0, NT_ROOT: 0}
        last_bk: dict[str, str] = {OT_ROOT: "", NT_ROOT: ""}
        for sid, href in spine:
            parts = sid.split(".")
            if len(parts) != 3:
                continue                      # front matter, book divider
            root, bk, ch = parts
            if root not in counters:
                continue                      # the apocrypha
            # The book ordinal changes only when the second path element does.
            # Counting the chapter files instead runs the counter into the
            # hundreds and files every chapter under one arbitrary book.
            if bk != last_bk[root]:
                last_bk[root] = bk
                counters[root] += 1
            order.append((root, counters[root] - 1, int(_roman(ch)), href))

        # The two roots number their books independently, so each has to be
        # offset into `names` or every New Testament book lands on an Old one.
        offsets = {OT_ROOT: 0, NT_ROOT: OT_BOOKS}
        for root, bidx, chapter, href in order:
            ix = offsets[root] + bidx
            name = names[ix] if ix < len(names) else ""
            member = "OEBPS/" + href
            if member not in members:
                member = href if href in members else None
            if not name or member is None:
                continue
            raw = z.read(member).decode("utf-8", "replace")
            label = _CHAPTER_LABEL.search(raw)
            if label:
                # Trust the file's own chapter number over the path: it is in
                # the text the reader will see, and a mislabelled path would
                # file a chapter under the wrong neighbour.  It also copes with
                # the Psalms, whose files are numbered by superscription and so
                # carry "PSALM 148" where the path says "cxlviii".
                chapter = _roman(label.group(1))
            if not chapter:
                continue                      # a superscription, not a chapter
            # Record the chapter even when it yields no points.  Obadiah and
            # Jude are a single chapter of verse notes with no outline in JFB,
            # and "this commentary does not outline it" is something the app
            # can say; a missing key is a hole it would have to guess about.
            books.setdefault(name, {})[str(chapter)] = _sections(raw)
    return books


def _sections(raw: str) -> list[dict]:
    """The outline points of one chapter, in order.

    A JFB section comes in one of two shapes.  Either it opens with its verse
    range and then a small-caps heading -- that is an outline point -- or it
    opens with a bold verse number and runs on into commentary about single
    verses, which continues the point above it rather than starting a new one.
    Getting that second shape wrong produced an outline of Genesis 1 in which
    "Isa 34:11" was a heading, because a cross-reference quoted halfway through
    a note on verse 2 had been read as the section's own subject.
    """
    out: list[dict] = []
    for block in _SECTION.findall(raw):
        paras = re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)
        if not paras:
            continue
        head = paras[0]

        if _VERSE_NOTE.match(head):
            continue          # a continuation: the point above already covers it

        # A point names its subject in small caps.  The verse range may come
        # before the heading ("Ge 1:1, 2  The Creation of...") or after it
        # ("PART I—PROLOGUE ... — (Job 1:1-22 ...)"), so take the references
        # from the head of the paragraph either way rather than assuming an
        # order.  Only the ones near the front are this section's own; a
        # reference quoted later belongs to the commentary inside it, and
        # reading one of those as the subject is how "Isa 34:11" became the
        # heading of Genesis 1:2.
        ref = ", ".join(t for t in
                        (_text(m.group(1)) for m in _SCRIP.finditer(head)
                         if m.start() < 160) if t)[:120]

        title = ""
        for h in (_text(x) for x in _SC.findall(head)):
            if not 0 < len(h) <= 200:
                continue          # a paragraph of prose in small caps
            if _PROPER_NOUN.match(h):
                continue          # the name of a scholar being quoted
            title = h
            break
        if not title:
            # No heading.  If the paragraph still opens on the passage, that
            # passage is the honest label.  If it does not, the block is prose
            # about this chapter rather than a point in its outline.
            if not _LEADS_WITH_REF.match(head) or not ref:
                continue
            title = ref
        o = {"title": title}
        if ref and ref != title:
            o["ref"] = ref
        sub = [h for h in (_text(x) for x in _SC.findall(head))
               if h != title and 8 < len(h) <= 120
               and len(h.split()) >= 2
               and not _PROPER_NOUN.match(h)][:12]
        if sub:
            o["sub"] = sub
        out.append(o)
    return out


_ROMAN_RE = re.compile(r"^m*(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_ROMAN_VAL = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman(s: str) -> int:
    """`cxlviii` -> 148.  A lookup table stops at 31, and the Psalms alone run to
    150, so every psalm past the thirty-first would land on Psalm 31."""
    t = s.lower().strip()
    if t.isdigit():
        return int(t)
    if not t or not _ROMAN_RE.match(t):
        return 0
    total = 0
    prev = 0
    for ch in reversed(t):
        v = _ROMAN_VAL[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def build(epub: Path, out_path: Path) -> dict:
    raw = parse(epub)
    order = {b.osis: i for i, b in enumerate(canon.BOOKS_66)}
    books = {k: v for k, v in sorted(raw.items(), key=lambda kv: order.get(kv[0], 999))
             if k in order and v}
    payload = {"source": SOURCE, "title": TITLE, "attribution": ATTRIBUTION,
               "note": NOTE, "books": books}
    blob = json.dumps(payload, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wb", compresslevel=9) as f:
        f.write(blob)
    return {"books": len(books),
            "chapters": sum(len(v) for v in books.values()),
            "sections": sum(len(s) for v in books.values() for s in v.values()),
            "raw_bytes": len(blob),
            "gz_bytes": out_path.stat().st_size}


def audit(data: dict) -> list[str]:
    """Complain about anything that would show up as a gap in the browser."""
    bad: list[str] = []
    for b in canon.BOOKS_66:
        want = canon.chapter_count("KJV", b.osis)
        got = set(data.get(b.osis, {}))
        # Apocryphal passages inside an otherwise canonical book can add a
        # chapter; a shortfall is a real gap, an excess is not.
        missing = [c for c in range(1, want + 1) if str(c) not in got]
        if missing:
            shown = ", ".join(str(c) for c in missing[:8])
            bad.append(f"{b.name}: {len(missing)} of {want} chapters missing "
                       f"({shown}{'...' if len(missing) > 8 else ''})")
    return bad


def unoutlined(data: dict) -> list[str]:
    """Chapters JFB covers but does not outline, so the app can say so."""
    out = []
    for book, chapters in data.items():
        empty = [c for c, s in chapters.items() if not s]
        if empty:
            name = next((b.name for b in canon.BOOKS_66 if b.osis == book), book)
            out.append(f"{name} {', '.join(sorted(empty, key=int))}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        if not OUT.exists():
            print(f"{OUT} is not built.  Run:  python3 tools/build_outlines.py")
            return 1
        with gzip.open(OUT, "rt", encoding="utf-8") as f:
            d = json.load(f)
        books = d["books"]
        print(f"{d['title']} ({d['source']}) -- {d['attribution']}")
        print(f"  {len(books)} books, "
              f"{sum(len(v) for v in books.values())} chapters, "
              f"{sum(len(s) for v in books.values() for s in v.values())} sections")
        print(f"  {OUT.stat().st_size:,} bytes gzipped")
        bad = audit(books)
        print("  every chapter present" if not bad
              else "  GAPS:\n    " + "\n    ".join(bad))
        thin = unoutlined(books)
        print(f"  {len(thin)} chapter(s) the commentary covers but does not "
              f"outline" if thin else "  every chapter has at least one point")
        for t in thin:
            print("    " + t)
        return 1 if bad else 0

    epub = args.epub
    if not epub:
        import tempfile
        epub = Path(tempfile.gettempdir()) / "jfb.epub"
        if not epub.exists():
            print(f"Downloading {EPUB_URL} ...")
            urllib.request.urlretrieve(EPUB_URL, epub)
    stats = build(epub, OUT)
    print(f"Wrote {OUT}")
    print(f"  {stats['books']} books, {stats['chapters']} chapters, "
          f"{stats['sections']} sections")
    print(f"  {stats['raw_bytes']:,} bytes raw, {stats['gz_bytes']:,} gzipped")
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        bad = audit(json.load(f)["books"])
    if bad:
        print("  GAPS:\n    " + "\n    ".join(bad))
        return 1
    print("  every chapter of all 66 books present")
    thin = unoutlined(json.load(gzip.open(OUT, "rt", encoding="utf-8"))["books"]) \
        if OUT.exists() else []
    if thin:
        print(f"  {len(thin)} chapter(s) covered but not outlined: "
              + "; ".join(thin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())