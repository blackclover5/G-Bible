"""EPUB: personal books.

An EPUB is a zip with a fixed shape -- a `mimetype` file, a container that
points at a package document, a manifest of the files inside, and a spine giving
the reading order.  Once the spine is walked the rest is HTML, and
`markup.parse_html` already reads HTML, so an EPUB becomes a book here with the
same unit shape every other format produces.  Nothing needs to be converted
first, which is the point: some platforms call this Personal Books and so does this.

Why it matters to this app
--------------------------
Three reasons, in order of how much they are used:

  * A commentary or book in EPUB is now readable and searchable beside the
    Bibles, with the same word study, cross-reference and citation machinery --
    because it arrives as a `Book`/`Commentary` module like any other.
  * It is the format most DRM-free books actually come in.  Supporting it means
    the Store's largest class of material is not a wall.
  * CCEL's Jamieson-Fausset-Brown is distributed as an EPUB, and that is where
    this app's outline data comes from.

Deliberate limits, stated rather than worked around:

  * **No DRM.**  An encrypted EPUB is refused with a clear message.  Decryption
    is not attempted and never will be.
  * **No CSS.**  EPUB styling is dropped; text, headings, emphasis, lists,
    links, block quotes and images are kept.  Every EPUB reader that honoured
    the stylesheet would have to be a second renderer, and the useful thing
    about a personal book is the words in it.
  * **No fixed layout.**  A reflowable document only.  A fixed-layout EPUB
    (comics, scanned textbooks) is a picture of pages, and reading it needs the
    renderer this deliberately does not have; those are reported, not half-read.
  * **JavaScript is not run.**  EPUB scripting is rare and mostly DRM-ish.

The OPF metadata is read as it stands and passed up as the module's own, so
author, language, rights and date come from the file rather than being guessed
at the importer.
"""

from __future__ import annotations

import html as htmlmod
import io
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree

from .. import markup
from ..indexer import UnitIn

#: Blocks whose text is not part of the book.
_SKIP = re.compile(
    r'<(script|style|head|nav|svg)\b.*?</\1\s*>', re.S | re.I)

_HEADING = re.compile(r"<h([1-3])\b[^>]*>(.*?)</h\1\s*>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def sniff(data: bytes) -> bool:
    """Is this zip an EPUB?  The `mimetype` member is the reliable test."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "mimetype" in names:
                try:
                    if z.read("mimetype").strip() == b"application/epub+zip":
                        return True
                except (KeyError, zipfile.BadZipFile):
                    pass
            return "META-INF/container.xml" in names and any(
                n.lower().endswith((".xhtml", ".html", ".htm"))
                for n in names)
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def is_encrypted(zf: zipfile.ZipFile) -> str:
    """The reason this EPUB cannot be read, or '' if it can."""
    if "META-INF/encryption.xml" in zf.namelist():
        raw = _read(zf, "META-INF/encryption.xml").decode("utf-8", "replace")
        if not raw:
            return "the encryption file could not be read"
        if 'EncryptionMethod ID="http://www.idpf.org/2008/embedding"' in raw \
                or "<EncryptedData" in raw:
            return ("this EPUB is DRM-protected. G-Bible does not decrypt "
                    "ebooks; use a DRM-free copy.")
        return "this EPUB uses font obfuscation, which is not supported"
    return ""


# ------------------------------------------------------------------ reading

def _xml(raw: bytes):
    """Parse XML, or return None.

    Every read goes through here rather than calling ElementTree directly,
    because a real EPUB is not always well-formed: a byte-order mark, or a
    newline before the declaration, is enough to make `fromstring` raise, and
    one such file would take the whole import down instead of losing its
    navigation document.
    """
    if not raw:
        return None
    body = raw.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError:
        pass
    # Some publishers write XHTML that is not well-formed -- unclosed <br>,
    # an ampersand in an attribute.  html.parser is far more forgiving.
    try:
        import html.parser

        class _Loose(html.parser.HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.root = ElementTree.Element("html")
                self.stack = [self.root]

            def handle_starttag(self, tag, attrs):
                e = ElementTree.SubElement(self.stack[-1], tag)
                for k, v in attrs:
                    e.set(k or "", v or "")
                if tag not in ("br", "img", "hr", "meta", "link", "input"):
                    self.stack.append(e)

            def handle_endtag(self, tag):
                for i in range(len(self.stack) - 1, 0, -1):
                    if self.stack[i].tag == tag:
                        del self.stack[i:]
                        break

            def handle_data(self, data):
                if data.strip():
                    e = ElementTree.SubElement(self.stack[-1], "text")
                    e.text = data

        p = _Loose()
        p.feed(body.decode("utf-8", "replace"))
        p.close()
        return p.root
    except Exception:
        return None


def _opf_path(zf: zipfile.ZipFile) -> str:
    doc = _xml(_read(zf, "META-INF/container.xml"))
    if doc is None:
        raise ValueError("META-INF/container.xml could not be read")
    for e in doc.iter():
        if e.tag.endswith("rootfile"):
            fp = e.get("full-path")
            if fp:
                return fp
    raise ValueError("no package document in META-INF/container.xml")


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def metadata(zf: zipfile.ZipFile) -> dict:
    """Title, author, language, rights and date, as the file states them."""
    out: dict = {}
    try:
        opf = _xml(_read(zf, _opf_path(zf)))
    except ValueError:
        return out
    if opf is None:
        return out
    for e in opf.iter():
        t = _tag(e)
        if t == "meta" and e.get("property"):
            key = e.get("property").split(":")[-1]
            if e.text and key not in out:
                out[key] = e.text.strip()
        elif t in ("title", "creator", "language", "rights", "date",
                   "publisher", "description", "identifier") and e.text:
            out.setdefault(t, e.text.strip())
    return out


def _spine(zf: zipfile.ZipFile) -> list[dict]:
    """The reading order: [(href, id, media_type, linear)]."""
    opf = _xml(_read(zf, _opf_path(zf)))
    if opf is None:
        return []
    manifest: dict[str, dict] = {}
    for e in opf.iter():
        if _tag(e) != "item":
            continue
        iid = e.get("id")
        if not iid:
            continue
        manifest[iid] = {"href": e.get("href") or "",
                         "type": e.get("media-type") or "",
                         "props": e.get("properties") or ""}
    out: list[dict] = []
    for e in opf.iter():
        if _tag(e) != "itemref":
            continue
        it = manifest.get(e.get("idref") or "")
        if not it or not it["href"]:
            continue
        if "nav" in it["props"]:
            continue                    # the table of contents, not a document
        out.append({**it, "linear": e.get("linear") != "no"})
    return out


def _resolve(base: str, href: str) -> str:
    href = href.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))


def toc(zf: zipfile.ZipFile) -> list[dict]:
    """The book's own table of contents: [{title, href, depth, page}].

    Read from the EPUB rather than invented, because every chapter of the JFB
    EPUB carries the same `<title>`, and without the navigation document a
    1,319-section commentary indexes with 1,319 identical labels and no way to
    tell where you are.  The EPUB 3 nav document is preferred; the older NCX is
    read when that is absent, which is the case for most older files.
    """
    out: list[dict] = []

    def walk(node, depth: int) -> None:
        for child in node:
            t = _tag(child)
            if t == "li":
                label, href = "", ""
                sub = None
                for c2 in child:
                    t2 = _tag(c2)
                    if t2 in ("a", "span") and not label:
                        label = _text("".join(
                            e.text or "" for e in c2.iter() if _tag(e) == "text")
                            or "".join(c2.itertext()))
                        href = c2.get("href") or ""
                    elif t2 in ("ol", "ul"):
                        sub = c2
                if label:
                    out.append({"title": label, "href": href, "depth": depth,
                                "page": ""})
                if sub is not None:
                    walk(sub, depth + 1)
            elif t == "nav":
                walk(child, depth)
            elif t in ("ol", "ul"):
                # An EPUB 3 nav document is <nav><ol><li>..., so the first
                # thing below <nav> is the list itself, not a list item.  Only
                # `ol`/`ul` *inside* an `li` was handled, so the whole document
                # walked to nothing and every EPUB 3 book imported with no
                # contents at all -- silently, since the NCX fallback has
                # nothing to find either in a file that has no NCX.
                walk(child, depth)

    base = _opf_path(zf)
    opf = _xml(_read(zf, base))
    for e in (opf.iter() if opf is not None else ()):
        if _tag(e) != "item":
            continue
        if "nav" in (e.get("properties") or ""):
            doc = _read(zf, _resolve(base, e.get("href") or ""))
            if not doc:
                continue
            root = _xml(doc)
            if root is None:
                continue
            for nav in root.iter():
                if _tag(nav) == "nav":
                    walk(nav, 0)
            if out:
                return out

    # The NCX is named by the manifest when it exists at all, and it sits
    # beside the package document -- which for CCEL means OEBPS/, not the root.
    ncx = ""
    for e in (opf.iter() if opf is not None else ()):
        if _tag(e) == "spine" and e.get("toc"):
            ncx = _resolve(base, e.get("toc") or "")
    if not ncx or ncx not in zf.namelist():
        ncx = next((n for n in zf.namelist()
                    if n.lower().endswith(".ncx")), "")
    if not ncx:
        return []
    root = _xml(_read(zf, ncx))
    if root is None:
        return []
    for point in root.iter():
        if _tag(point) != "navPoint":
            continue
        label, src, depth = "", "", 0
        for c in point:
            t = _tag(c)
            if t == "navLabel":
                label = _text("".join(c.itertext()))
            elif t == "content":
                src = c.get("src") or ""
            elif t == "navPoint":
                depth = 1
        if label:
            out.append({"title": label, "href": src.split("#")[0],
                        "depth": depth, "page": ""})
    return out


def _read(zf: zipfile.ZipFile, member: str) -> bytes:
    try:
        return zf.read(member)
    except (KeyError, zipfile.BadZipFile, RuntimeError):
        return b""


def _titles(zf: zipfile.ZipFile) -> dict[str, str]:
    """href -> title, from the navigation document, keyed by resolved path."""
    base = _opf_path(zf)
    out: dict[str, str] = {}
    for row in toc(zf):
        if row["title"] and row["href"]:
            out[_resolve(base, row["href"])] = row["title"]
    return out


def _clean(raw: str) -> str:
    """The body text of one document, with its own chrome taken off."""
    s = _SKIP.sub(" ", raw)
    m = re.search(r"<body\b[^>]*>(.*)</body\s*>", s, re.S | re.I)
    if m:
        s = m.group(1)
    return s


def _first_heading(body: str) -> str:
    for m in _HEADING.finditer(body):
        t = _text(m.group(2))
        if t:
            return t
    return ""


def _text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def _key_for(href: str, index: int, title: str) -> str:
    """A stable, sortable key.

    EPUB publishers name their files anything, so the reading order is the only
    dependable sequence -- and a key has to sort in reading order or "next
    section" walks the book backwards.
    """
    stem = posixpath.splitext(posixpath.basename(href))[0]
    m = re.match(r"^(.*?)(\d+)$", stem)
    if m:
        return f"{m.group(1)[:24]}{int(m.group(2)):05d}"
    return f"s{index:05d}"


def fixed_layout(zf: zipfile.ZipFile) -> bool:
    """True when the pages are pictures and there is no flow to reflow."""
    try:
        raw = _read(zf, _opf_path(zf)).decode("utf-8", "replace")
    except ValueError:
        return False
    return "rendition:layout" in raw and "pre-paginated" in raw


def load(data: bytes, *, kind: str = "Book", source: str = "",
         base_href: str = "") -> tuple[dict, Iterator[UnitIn]]:
    """Read an EPUB into units.  Returns (metadata, units).

    The units are a generator, so the spine is walked lazily and a 9 MB
    commentary indexes in the same streaming way a SWORD module does.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    why = is_encrypted(zf)
    if why:
        raise ValueError(why)
    meta = metadata(zf)
    meta["format"] = "EPUB"
    meta["fixed_layout"] = fixed_layout(zf)
    if meta["fixed_layout"]:
        meta["warning"] = (
            "This is a fixed-layout EPUB -- the pages are images, not text. "
            "G-Bible reads reflowable books, so little will come of it.")
    k = kind if kind in ("Commentary", "Book", "StudyGuide", "Devotional",
                         "Article") else "Book"
    return meta, _units(zf, k, source or meta.get("title", ""), base_href)


_CHAPTER_LABEL = re.compile(r"<(?:p|h[1-6]|div)[^>]*>\s*"
                            r"(?:CHAPTER|PSALM)\s+([0-9]+|[ivxl]+)\s*"
                            r"(?:</[^>]+>)?", re.I)
_GENERIC_TITLE = re.compile(r"^(chapter|psalm|section|part|book)\s+"
                            r"([0-9]+|[ivxl]+)\.?$", re.I)


def _units(zf: zipfile.ZipFile, kind: str, source: str,
           base_href: str) -> Iterator[UnitIn]:
    spine = _spine(zf)
    names = set(zf.namelist())
    base = base_href or _opf_path(zf)
    titles = _titles(zf)
    fallback = ""
    book_title = ""
    index = 0
    for item in spine:
        # Resolve against the OPF, always.  This used to be `... if base_href
        # else item["href"]`, so on a normal install the spine href -- which is
        # relative to the package document, "jfb.ii.html" -- was looked up
        # un-resolved.  The fallback below still found the bytes under
        # OEBPS/, so every section read fine, but `titles.get(member)` missed
        # and all 1,319 sections of a real commentary took their names from the
        # document <title> instead of the table of contents: the same string,
        # 1,319 times, and a contents list you could not navigate.
        member = _resolve(base, item["href"])
        if member not in names:
            # Some publishers put content at the archive root, some under OEBPS.
            alt = posixpath.basename(member)
            member = next((n for n in names if n.endswith("/" + alt)), member)
            if member not in names:
                member = next((n for n in names if n == alt), member)
        if member not in names:
            continue
        try:
            raw = zf.read(member).decode("utf-8", "replace")
        except (KeyError, zipfile.BadZipFile, RuntimeError):
            continue
        index += 1
        body = _clean(raw)
        if not _text(body):
            continue

        toc_title = titles.get(member, "")
        gen = _GENERIC_TITLE.match(toc_title)
        if not gen:
            # A title like "Genesis" or "Introduction to the Pentateuch" is the
            # book; remember it so the chapters after it can be named.
            if toc_title:
                book_title = toc_title
        title = _first_heading(body) or toc_title
        if not title:
            m = _TITLE.search(raw)
            doc_title = _text(m.group(1)) if m else ""
            # Every chapter of a multi-section book often carries the same
            # <title>.  The first one is worth keeping as a name for the module;
            # after that it is noise, and a section list of 1,319 identical
            # labels is worse than none.
            if not fallback:
                fallback = doc_title
            if doc_title and doc_title != fallback:
                title = doc_title

        if gen:
            # "Chapter 50" on its own tells you nothing once the list is longer
            # than the window.  Name it after the book it is in.
            num = _roman_int(gen.group(2)) or gen.group(2)
            name = book_title or _chapter_label(body) or title
            title = f"{name} {num}".strip() if name else toc_title
        if not title:
            title = _chapter_label(body) or f"Section {index}"

        segs = markup.parse_html(body)
        if not segs:
            segs = markup.parse_plain(_text(body))
        yield UnitIn(key=_key_for(item["href"], index, title),
                     label=title[:200], segs=segs, title=title[:200],
                     markup=body,
                     extra={"source": source, "href": item["href"],
                            "spine": index, "media": item["type"]})


def _chapter_label(body: str) -> str:
    m = _CHAPTER_LABEL.search(body)
    return _text(m.group(0)) if m else ""


_ROMAN_VAL = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_int(s: str) -> int:
    t = s.lower()
    if t.isdigit():
        return int(t)
    total, prev = 0, 0
    for ch in reversed(t):
        if ch not in _ROMAN_VAL:
            return 0
        v = _ROMAN_VAL[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def load_file(path: Path, **kw) -> tuple[dict, Iterator[UnitIn]]:
    return load(path.read_bytes(), **kw)