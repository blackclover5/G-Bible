"""CCEL ThML — the patristic volumes behind the Early Church Fathers.

The Christian Classics Ethereal Library keeps the Ante-Nicene Fathers and the
Nicene and Post-Nicene Fathers as one ThML file per volume (`anf01`…`anf10`,
`npnf101`…`npnf114`, `npnf201`…`npnf214`), and each file carries every work it
contains, already marked up.  One volume of ANF holds 864 chapters, 4,917
editorial footnotes and 3,005 scripture citations, which is most of what a reader
wants from a Father and none of which is in the plain-text or EPUB builds.

Two facts about the format drive everything here.

**A work is a `<div>`, and the editors chose the level.**  Irenaeus's *Against
Heresies* divides into books (`div2`) and each book into chapters (`div3`);
Clement's single letter divides into nothing at all.  A reader that assumed one
shape would produce either 864 empty units or one unreadable blob, so the reader
takes the deepest division that actually has children and falls back to packing
paragraphs when a work is a single undivided stretch of prose.

**Every work announces itself immediately before its div**, in a `<ThML.head>`:

    <ThML.head><electronicEdInfo>
      <authorID>irenaeus</authorID>
      <workID>against_heresies_i</workID>
      <versionID>anf01</versionID>
      <DC><DC.Title>Against Heresies: Book I</DC.Title>
      <DC.Identifier scheme="URL">http://www.ccel.org/ccel/schaff/anf01.ix.ii.html
    ...

That is the only place in the file saying which Father a division belongs to, and
it is what lets the Store offer *Against Heresies* on its own instead of only
the volume it happens to sit in.  The head is a sibling of the div and *precedes*
the div it describes, so the pairing is positional -- scan for "a head, then the
next div" -- rather than anything found by looking inside a div.

The volume's own head has the same shape and is skipped: its URL is `anf01.html`
where a work's is `anf01.ix.ii.html`.  Everything a Store row needs about the
volume comes out of that head too -- title, editor, first publication, and an
explicit `<DC.Rights>Public Domain</DC.Rights>` -- so the licence is read from the
file rather than asserted by the catalogue.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from typing import Iterator

from .. import markup
from ..indexer import UnitIn
from ..markup import Seg

#: Where the text comes from, for attribution strings.
CCEL_HOME = "https://www.ccel.org"
CCEL_FATHERS = "https://www.ccel.org/fathers"

#: A division longer than this is split at paragraph boundaries.  The longest
#: undivided work in these volumes is a long letter rather than a book with
#: chapters; one unit of 60,000 characters is a scroll nobody reads, and a unit
#: is also what a search result points at.  Chapters are unaffected.
MAX_UNIT_CHARS = 24_000


@dataclass(frozen=True)
class Work:
    """One contained work, as announced by its `<ThML.head>`."""

    work_id: str
    author_id: str
    title: str
    div_id: str
    version: str
    url: str
    level: int = 1
    author: str = ""

    @property
    def page_url(self) -> str:
        """The address a reader would visit for this work."""
        if self.work_id and self.author_id and self.version:
            return (f"{CCEL_HOME}/ccel/{self.author_id}/{self.work_id}"
                    f"/{self.version}")
        return self.url or CCEL_HOME

    def with_author(self, name: str) -> "Work":
        return replace(self, author=name)


@dataclass
class VolumeMeta:
    """What the volume head says about the volume itself."""

    slug: str = ""
    title: str = ""
    editor: str = ""
    author: str = ""
    author_id: str = ""
    description: str = ""
    pub_history: str = ""
    first_published: str = ""
    rights: str = ""
    language: str = "eng"
    url: str = ""
    dc_type: str = ""
    contributors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

# The prologue before `<ThML>` differs between CCEL's two sets: the Ante-Nicene
# files go straight from the declaration to a comment, while the Nicene ones
# carry a `<!DOCTYPE ThML PUBLIC ...>` naming the ThML DTD.  Both are allowed,
# along with the processing instructions that sit inside those comments.
_THML_PROLOGUE = (r"<\?xml[^>]*\?>\s*(?:<!DOCTYPE[^>]*>\s*)?"
                  r"(?:<!--.*?-->\s*|<\?.*?\?>\s*)*<ThML\b")
_THML_HEAD_BYTES = re.compile(_THML_PROLOGUE.encode(), re.S)


def sniff_thml(data: bytes | None = None, name: str = "") -> bool:
    """Is this a CCEL ThML document?"""
    if data:
        return bool(_THML_HEAD_BYTES.match(data[:4096]))
    return name.lower().endswith(".thml")


# --------------------------------------------------------------------------
# The volume head
# --------------------------------------------------------------------------

def _strip(elem) -> str:
    """An element's text, markup removed and whitespace collapsed."""
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", markup.unescape("".join(elem.itertext()))).strip()


def _find(el, tag: str):
    for child in el.iter():
        if isinstance(child.tag, str) and child.tag.lower() == tag.lower():
            return child
    return None


def _plain(el, tag: str) -> str:
    return _strip(_find(el, tag))


def _dc(root, name: str) -> str:
    """`<DC.Title>` and its siblings, whose tag names ThML namespaces with a dot."""
    return _strip(_find(root, f"dc.{name}"))


def _absolute(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return CCEL_HOME + u
    return u


def volume_meta(src: str) -> VolumeMeta:
    """Read the volume's own head.

    `rights` is the field that matters: the Store will not offer a work whose
    file does not itself say it is public domain.
    """
    m = VolumeMeta()
    head = re.search(r"<ThML\.head\b.*?</ThML\.head\s*>", src, re.S | re.I)
    if not head:
        return m
    el = _parse_fragment(head.group(0))
    if el is None:
        return m
    m.slug = _plain(el, "bookID")
    m.title = _dc(el, "Title") or m.slug
    m.rights = _dc(el, "Rights")
    m.language = _dc(el, "Language") or "eng"
    m.url = _absolute(_dc(el, "Identifier"))
    m.dc_type = _dc(el, "Type")
    m.first_published = _plain(el, "firstPublished")
    m.description = _plain(el, "description")
    m.pub_history = _plain(el, "pubHistory")
    creators: list[tuple[str, str, str]] = []
    for child in el.iter():
        if isinstance(child.tag, str) and child.tag.lower() == "dc.creator":
            creators.append(((child.get("sub") or "").lower(),
                             (child.get("scheme") or "").lower(), _strip(child)))
    m.editor = next((n for sub, _sc, n in creators if sub == "file-as"
                     and n), next((n for _s, _c, n in creators if n), ""))
    # `<DC.Creator sub="Author">` is the only place a Schaff volume says whose
    # Fathers it contains: in these volumes the author is Augustine while the
    # editor is Schaff, and the editor's name is the one every other field uses.
    m.author = next((n for sub, _sc, n in creators
                     if sub == "author" and _sc in ("", "short-form") and n), "")
    m.author_id = next((n for sub, sc, n in creators
                        if sub == "author" and sc == "ccel" and n), "")
    m.contributors = [n for sub, _sc, n in creators if n and sub != "file-as"]
    return m


def _parse_fragment(xml: str):
    try:
        return ET.fromstring(f"<ThML>{xml}</ThML>")
    except ET.ParseError:
        return None


# --------------------------------------------------------------------------
# The work inventory
# --------------------------------------------------------------------------

# A head, or a div opening tag, scanned as one alternation so that "the head that
# came before this div" is a thing the scan can know.  The divisions nest
# unevenly and a head sits *outside* the div it describes, so a tree walk would
# attribute every work to the division before it.
_HEAD_OR_DIV_RE = re.compile(r"<ThML\.head\b.*?</ThML\.head\s*>"
                             r"|<div(\d)\b([^>]*)>", re.S | re.I)
_ID_ATTR_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.I)
# CCEL quotes every attribute with `"`, and the value pattern says so: an
# apostrophe inside a title -- "St. Augustin's Life and Work", "Translator's
# Preface" -- otherwise ends the value early and the title arrives truncated to
# "St. Augustin".
_ATTR_RE = re.compile(r"""([\w:.\-]+)\s*=\s*["']([^"]*)["']""")
# The tag name is captured with any attributes: `<DC.Identifier scheme="URL">`
# carries them and without this the URL that says *which division* a head
# describes is never read, so every head looks like the volume's own.  The body
# is `[^<]*` on purpose: the fields wanted are leaves, and allowing markup
# inside would match `<ThML.head>…</ThML.head>` first and swallow the rest.
_FIELD_RE = re.compile(r"<([A-Za-z_][\w.\-]*)\b[^>]*>([^<]*)</\1\s*>")


def find_works(src: str) -> list[Work]:
    """Every work the volume contains, in document order.

    A head naming no division (`anf01.html`) or repeating the volume slug is the
    volume's own head, and describes no work anybody can ask for.
    """
    out: list[Work] = []
    pending: dict | None = None
    claimed: set[str] = set()
    for m in _HEAD_OR_DIV_RE.finditer(src):
        if not m.group(1):
            pending = _head_fields(m.group(0))
            continue
        if not pending:
            continue
        div_id = _ID_ATTR_RE.search(m.group(2) or "")
        div_id = div_id.group(1) if div_id else ""
        if not div_id or div_id in claimed:
            pending = None
            continue
        claimed.add(div_id)
        out.append(Work(pending["work_id"], pending["author_id"],
                        pending["title"], div_id, pending["version"],
                        pending["url"], int(m.group(1))))
        pending = None
    return out


def _head_fields(head: str) -> dict | None:
    fields = {tag.lower(): re.sub(r"\s+", " ", markup.unescape(body)).strip()
              for tag, body in _FIELD_RE.findall(head)}
    work_id = fields.get("workid", "")
    if not work_id:
        return None
    version = fields.get("versionid", "")
    url = _absolute(fields.get("dc.identifier", ""))
    if work_id == version or not _names_a_division(url):
        return None
    return {"work_id": work_id, "author_id": fields.get("authorid", ""),
            "title": fields.get("dc.title") or work_id.replace("_", " "),
            "version": version, "url": url}


def _names_a_division(url: str) -> bool:
    """`…/anf01.html` is the volume; `…/anf01.ix.ii.html` is one work inside it."""
    return url.rsplit("/", 1)[-1].count(".") >= 2


# Divisions that are the book's furniture rather than its content.  The list is
# matched whole against the title and the words are matched inside it, because
# both shapes occur: one volume's division is called "Prefaces." and another's
# "Prefaces to the Books of Kings", while an index is nearly always titled for
# the work it indexes -- "The Confessions of St. Augustin: Index of Subjects" --
# which no exact list would catch.
_FRONT_MATTER = frozenset({
    "title page", "title pages", "preface", "prefaces", "editor's preface",
    "translator's preface", "contents", "table of contents", "index",
    "indexes", "index of subjects", "indexes of subjects", "subject indexes",
    "index of texts", "general index", "copyright", "about the author",
    "reviews", "errata", "editorial preface", "transcriber's note",
})
_FRONT_WORDS = ("index", "contents", "synopsis", "title page")


def is_front_matter(title: str) -> bool:
    t = re.sub(r"\s+", " ", markup.unescape(title or "")).strip().rstrip(".").lower()
    if t in _FRONT_MATTER:
        return True
    return any(w in t for w in _FRONT_WORDS)


def find_divisions(src: str, *, volume: str = "", author_id: str = "",
                   author: str = "") -> list[Work]:
    """Works taken from a volume's own top-level divisions.

    CCEL added a `<ThML.head>` naming each contained work to the Ante-Nicene
    volumes; the twenty-eight Nicene ones never got them.  There the top-level
    divisions *are* the works -- "The Confessions", "Homilies on S. Ignatius",
    "The Canons of the Councils of Ancyra and Laodicea" -- so those are used
    instead, with the front and back matter left out: a title page, a list of
    contents and an index are not something anyone installs to read.
    """
    out: list[Work] = []
    claimed = {w.div_id for w in find_works(src)}
    for m in re.finditer(r"<div1\b([^>]*)>", src, re.I):
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        div_id = attrs.get("id", "")
        # Unescaped because the division titles come from the file as text, not
        # from a parser: "&amp;c." is how CCEL writes "etc.", and it would
        # otherwise reach the Store listing as "&amp;c.".
        title = re.sub(r"\s+", " ", markup.unescape(attrs.get("title")
                                                    or attrs.get("shorttitle")
                                                    or "")).strip().rstrip(".")
        if not div_id or not title or is_front_matter(title) or div_id in claimed:
            continue
        out.append(Work(work_id=f"{volume}-{div_id}" if volume else div_id,
                        author_id=author_id, author=author, title=title,
                        div_id=div_id, version=volume,
                        url=f"{CCEL_HOME}/ccel/schaff/{volume}.{div_id}.html",
                        level=1))
    return out


# --------------------------------------------------------------------------
# Finding one work inside the volume
# --------------------------------------------------------------------------

def volume_works(src: str) -> list[Work]:
    """Every work a volume contains, however this one happens to be divided.

    One function on purpose: the catalogue builder and the installer have to
    agree on what a "work" is, or the Store can offer an item the installer then
    cannot find -- which is what happened when the two disagreed about the
    Nicene volumes, and every one of them refused to install.
    """
    works = find_works(src)
    if works:
        return works
    meta = volume_meta(src)
    return find_divisions(src, volume=meta.slug, author_id=meta.author_id,
                          author=meta.author)


def slice_div(src: str, div_id: str) -> str:
    """The XML of one division, opening tag to matching close tag.

    Divisions nest but are not regular, so the close tag is found by counting
    the same tag: a `<div2>` holds dozens of `<div3>`s, and matching the first
    `</div2>` would silently return a fragment.
    """
    m = re.search(rf'<div(\d)\b[^>]*\bid\s*=\s*["\']{re.escape(div_id)}["\'][^>]*>',
                  src, re.I)
    if not m:
        return ""
    tag = f"div{m.group(1)}"
    open_re = re.compile(rf"<{tag}\b", re.I)
    close = f"</{tag}>"
    depth, pos = 1, m.end()
    while depth:
        nxt_open = open_re.search(src, pos)
        nxt_close = src.find(close, pos)
        if nxt_close < 0:
            return src[m.start():]
        if nxt_open and nxt_open.start() < nxt_close:
            depth += 1
            pos = nxt_open.end()
            continue
        depth -= 1
        pos = nxt_close + len(close)
    return src[m.start():pos]


# --------------------------------------------------------------------------
# Divisions to units
# --------------------------------------------------------------------------

_DIV_TAG_RE = re.compile(r"div(\d)", re.I)


def _child_divs(el) -> list:
    return [c for c in el if isinstance(c.tag, str)
            and _DIV_TAG_RE.fullmatch(c.tag)]


def units_for_work(src: str, work: Work, *, keep_notes: bool = True,
                   max_chars: int = MAX_UNIT_CHARS) -> Iterator[UnitIn]:
    """Addressable units for one work: one per division, or one for undivided
    prose, and never longer than `max_chars`."""
    frag = slice_div(src, work.div_id)
    if not frag:
        return
    # The fragment is wrapped so that a div carrying a comment before its first
    # child still parses; the wrapper is not the work, so step into it.
    root = ET.fromstring(f"<ThML>{frag}</ThML>")
    div = root if _DIV_TAG_RE.fullmatch(root.tag) else next(iter(root), None)
    if div is None:
        return
    parts = _child_divs(div)
    lead = _own_text(div, parts, keep_notes=keep_notes)

    if not parts:
        yield from _emit_units([(work.title or work.work_id, lead, work.div_id)],
                              work, max_chars=max_chars)
        return
    if len(markup.segs_text(lead, notes=False)) >= 400:
        # Prose of its own before the first division -- an introduction, or the
        # opening of a letter that the editors then divided.  A heading alone is
        # not worth a unit: it is the work's title.
        yield from _emit_units([(f"{work.title} (opening)", lead, work.div_id)],
                              work, max_chars=max_chars)
    yield from _emit_units([(_div_title(p), _segs(p, keep_notes=keep_notes),
                             _div_id(p) or work.work_id)
                            for p in parts], work, max_chars=max_chars)


def _own_text(el, skip: list, *, keep_notes: bool) -> list:
    """The division's own content, with its child divisions left out."""
    out: list[Seg] = []
    kids = set(id(c) for c in skip)
    if el.text:
        out.append(Seg("text", markup.collapse(el.text)))
    for child in el:
        if id(child) not in kids:
            out.extend(_segs(child, keep_notes=keep_notes))
        if child.tail:
            out.append(Seg("text", markup.collapse(child.tail)))
    return _tidy(out)


def _emit_units(rows: list[tuple[str, list, str]], work: Work, *,
                max_chars: int) -> Iterator[UnitIn]:
    n = 0
    for title, segs, div_id in rows:
        n += 1
        key = div_id or f"{work.work_id}.{n}"
        for i, chunk in enumerate(_split_long(segs, max_chars), 1):
            label = title if i == 1 else f"{title}, § {i}"
            yield UnitIn(key=key if i == 1 else f"{key}.{i}",
                         label=label, segs=chunk, title=label,
                         extra={"work": work.work_id, "author": work.author_id})


def _div_title(el) -> str:
    return re.sub(r"\s+", " ", (el.get("title") or el.get("shorttitle")
                                or el.get("n") or "").strip()) or "Section"


def _div_id(el) -> str:
    return (el.get("id") or "").strip()


def _split_long(segs: list[Seg], max_chars: int) -> Iterator[list[Seg]]:
    """Pack paragraphs into units no longer than `max_chars`.

    Splitting happens at paragraph boundaries so no sentence is cut in half, and
    a single paragraph over the limit is kept whole rather than mangled.
    """
    if len(markup.segs_text(segs, notes=False)) <= max_chars:
        yield segs
        return
    blocks: list[list[Seg]] = []
    cur: list[Seg] = []
    size = 0
    for s in segs:
        cur.append(s)
        if s.kind in ("para", "break"):
            blocks.append(cur)
            cur, size = [], 0
        else:
            size += len(s.text)
    if cur:
        blocks.append(cur)
    batch: list[Seg] = []
    batch_len = 0
    for block in blocks:
        block_len = len(markup.segs_text(block, notes=False))
        if batch and batch_len + block_len > max_chars:
            yield batch
            batch, batch_len = [], 0
        batch.extend(block)
        batch_len += block_len
    if batch:
        yield batch


# --------------------------------------------------------------------------
# ThML to segments
# --------------------------------------------------------------------------

# Elements carrying the file's plumbing rather than its text.  `<pb>` is a page
# break into a scan, `<style>` is CCEL's own CSS, `<index>` is the back-of-book
# index -- and a `<pb>` left in would put the address of a page in a PDF into the
# middle of a sentence.
_DROP = frozenset({
    "pb", "figure", "graphic", "gap", "index", "style", "opener", "closer",
    "bkg", "front", "back", "imprint", "titlepage", "docimprint", "bibl",
    "biblfull", "msidentifier", "witdetail", "editionstmt", "publicationstmt",
    "encodingdesc", "extdep", "extlink", "funder", "sponsor", "respstmt", "idno",
    "seriesstmt", "notesstmt", "projectdesc", "langusage", "revisiondesc",
    "workprefix", "browsehead", "toc", "tableofcontents", "divinegroup",
})

# Text CCEL supplies or cannot read: shown the way the reader marks supplied
# words rather than passed through as if it were certain.
_TRANSTEXT = {"supplied": "add", "unclear": "add", "reg": "add"}

_BLOCK = frozenset({"p", "lg", "l", "item", "quote", "cit", "center", "div",
                    "blockquote", "address", "stage", "dd", "dt", "hi", "salute",
                    "signed"})

_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _segs(el, *, keep_notes: bool = True) -> list[Seg]:
    """One element's segments.

    The walk is over the tree rather than a re-serialisation because three
    things have to be decided per element and a string round trip loses them: a
    `<scripRef>` keeps its printed citation as well as its target, a `<pb>` keeps
    the text that follows it, and a dropped `<index>` does not take a paragraph
    with it.  The segments produced are the same kinds `markup.parse_osis` makes,
    so a Father renders here exactly as any other module does.
    """
    out: list[Seg] = []
    _walk(el, out, keep_notes=keep_notes)
    return _tidy(out)


def _walk(el, out: list[Seg], *, keep_notes: bool) -> None:
    tag = el.tag if isinstance(el.tag, str) else ""
    name = tag.lower()
    if name in _DROP:
        _tail(el, out)
        return
    if name in ("note", "endnote"):
        body = _strip(el)
        if keep_notes and body:
            place = "end" if name == "endnote" else (
                "end" if (el.get("place") or "").lower() == "end" else "foot")
            # `n` is CCEL's own footnote number (1..N within the volume);
            # stash it as an osis-style `!N` so the reader renders the
            # superscript numeral instead of a generic "+".  `id` is the
            # per-note anchor and is a better key when present.
            note_no = el.get("n") or ""
            value = ("!" + note_no) if note_no else (el.get("id") or "")
            out.append(Seg("note", body, value,
                           el.get("type") or "explanation",
                           {"placement": place}))
            # Two citations in three in these volumes are in a footnote rather
            # than in the text -- an editor's note is most of where the
            # scripture is named.  A note is stored as one piece of text, so
            # its references would otherwise be the one citation the module
            # cannot point at.  They are recorded here, with no words of their
            # own, so the unit is known to cite what its notes cite.
            _citations(el, out)
        _tail(el, out)
        return
    if name == "scripref":
        target = _osis_target(el.get("osisRef") or el.get("osisref") or "")
        if target:
            out.append(Seg("xref", "", target))
        shown = el.get("passage") or _strip(el)
        if shown:
            out.append(Seg("text", re.sub(r"\s+", " ", shown)))
        _tail(el, out)
        return
    if name in _HEADINGS:
        head = _strip(el)
        if head:
            out.append(Seg("heading", head, "", "", {"level": name[1]}))
        _tail(el, out)
        return
    if name == "verse":
        oid = el.get("osisID") or el.get("osisid") or ""
        if oid:
            out.append(Seg("title", "", oid, "", {"t": "verse"}))
        _tail(el, out)
        return
    if name in _TRANSTEXT:
        out.append(Seg(_TRANSTEXT[name], ""))
        _children(el, out, keep_notes=keep_notes)
        _tail(el, out)
        return
    if name in _BLOCK:
        out.append(Seg("para", "\n"))
    _children(el, out, keep_notes=keep_notes)
    if name in _BLOCK:
        out.append(Seg("para", "\n"))
    _tail(el, out)


def _citations(el, out: list[Seg]) -> None:
    """Record the scripture a subtree names, without repeating its words."""
    for child in el.iter():
        if not isinstance(child.tag, str) or child.tag.lower() != "scripref":
            continue
        target = _osis_target(child.get("osisRef") or child.get("osisref") or "")
        if target:
            out.append(Seg("xref", "", target))


def _children(el, out: list[Seg], *, keep_notes: bool) -> None:
    if el.text:
        _text(el.text, out)
    for child in el:
        _walk(child, out, keep_notes=keep_notes)


def _tail(el, out: list[Seg]) -> None:
    """The text following an element belongs to its parent, not to the element."""
    if el.tail:
        _text(el.tail, out)


def _text(raw: str, out: list[Seg]) -> None:
    t = markup.collapse(raw)
    if t:
        out.append(Seg("text", t))


def _tidy(segs: list[Seg]) -> list[Seg]:
    """Collapse whitespace and join adjacent text, as `parse_osis` does.

    Written out rather than imported from `markup` because that one is private to
    its parser, and because the work here has already produced final segments:
    all that is left is the clean-up pass.
    """
    out: list[Seg] = []
    for s in segs:
        if s.kind in ("text", "add", "alt", "red", "name", "title", "strongs",
                      "heading"):
            t = markup.collapse(s.text)
            if not t and not (s.kind == "strongs" and not s.value):
                if s.kind == "title" and not t:
                    out.append(s)          # a marker with no words still counts
                continue
            prev = out[-1] if out else None
            if (prev is not None and prev.kind == s.kind
                    and prev.value == s.value and prev.lemma == s.lemma
                    and prev.attrs == s.attrs):
                out[-1] = prev._replace(text=f"{prev.text} {t}")
            else:
                out.append(s._replace(text=t))
        else:
            out.append(s)
    while out and out[0].kind in ("para", "break"):
        out.pop(0)
    while out and out[-1].kind in ("para", "break"):
        out.pop()
    return out


def _osis_target(raw: str) -> str:
    """`Bible:1Pet.5.1-1Pet.5.5` -> `1Pet.5.1-1Pet.5.5`.

    CCEL qualifies scripture references with a corpus prefix that
    `canon.parse_osis_ref` does not know about.  The prefix is dropped and the
    rest must still look like a reference, so a malformed one is dropped rather
    than stored as a target nothing can open.
    """
    parts = []
    for piece in (raw or "").split("-"):
        piece = piece.strip()
        if ":" in piece:
            piece = piece.split(":", 1)[1].strip()
        parts.append(piece)
    out = "-".join(p for p in parts if p)
    return out if out and out.count(".") >= 1 else ""