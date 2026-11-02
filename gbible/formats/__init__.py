"""Format detection and dispatch.

`sniff()` decides what a payload is; `load()` turns it into UnitIn objects.
Keeping detection in one place means the Store can accept a bare file drop and
still know whether it got a SWORD module, a USFM zip, an e-Sword database or a
plain book.
"""

from __future__ import annotations

import io
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Iterator

from .. import canon, markup
from ..indexer import UnitIn
from . import conllu, esword, epub, latinlib, plain, sword, thml, usfm, xmlbible

FORMATS = ("sword", "sword-zip", "usfm", "usfx", "osis", "esword9", "esword-legacy",
           "esword-zip", "epub", "text", "wikitext", "osm-kml", "image", "conllu",
           "thml", "latinlib", "unknown")


def sniff(data: bytes | None = None, path: Path | None = None,
          name: str = "") -> str:
    name = (name or (path.name if path else "")).lower()
    ext = Path(name).suffix.lower()

    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"):
        return "image"
    if ext in (".kmz", ".kml"):
        return "osm-kml"
    if ext in (".bblx", ".cmtx", ".dctx", ".devx", ".mapx", ".harx", ".brpx",
               ".notx", ".topx", ".refx", ".lstx", ".memx", ".prlx", ".ovlx"):
        return "esword9"
    if ext in (".bbl", ".cmt", ".dct", ".dev", ".bmap", ".mybible", ".bzz", ".bzs"):
        return "esword-legacy"
    if ext in (".bzu",):
        return "esword-legacy"
    if ext in (".epub",):
        return "epub"
    if ext in (".zip", ".bzz2"):
        pass
    if ext in (".usfm",):
        return "usfm"
    if ext in (".usfx",):
        return "usfx"
    if ext in (".osis", ".osis.xml"):
        return "osis"
    if ext in (".txt", ".text", ".md", ".utf-8", ".utf8", ".utf-16"):
        return "text"
    if ext in (".wiki", ".wikitext"):
        return "wikitext"
    if conllu.sniff_conllu(data, name):
        return "conllu"

    if data is not None:
        if data[:16] == b"SQLite format 3\x00":
            return "esword9"
        if xmlbible.sniff_usfx(data):
            return "usfx"
        if xmlbible.sniff_osis(data):
            return "osis"
        if thml.sniff_thml(data):
            return "thml"
        if latinlib.sniff_latinlib(data):
            return "latinlib"
        if data[:2] == b"PK":
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
                names = zf.namelist()
                if epub.sniff(data):
                    # Checked before the zip tests: an EPUB is a zip, and the
                    # SWORD and e-Sword branches below would otherwise claim
                    # any EPUB that happened to carry a .conf or an image.
                    return "epub"
                if any(n.startswith("mods.d/") and n.endswith(".conf") for n in names):
                    return "sword-zip"
                if any(n.lower().endswith(".usfm") for n in names):
                    return "usfm"
                if any(n.lower().endswith((".bblx", ".cmtx", ".dctx", ".devx", ".mapx")) for n in names):
                    return "esword-zip"
                if any(n.lower().endswith(".mod") for n in names):
                    return "esword-zip"
                if any(n.lower().endswith((".jpg", ".png", ".svg")) for n in names):
                    return "image"
                if names and all(n.endswith(".txt") for n in names):
                    return "text"
            except zipfile.BadZipFile:
                pass
        if data[:3] == b"BZh":
            return "esword-legacy"
        if data[:4] == b"\x1f\x8b\x08\x00":
            return "text"
    if ext in (".zip",):
        return "sword-zip"
    # Content, not just the name: Project Gutenberg serves `/ebooks/14026.txt.utf-8`
    # and other repositories append their own suffixes, so a decodable,
    # NUL-free payload with real prose in it is text whatever it is called.
    if data is not None and not ext:
        head = data[:2048]
        if head and b"\x00" not in head:
            try:
                s = head.decode("utf-8")
            except UnicodeDecodeError:
                s = ""
            if s and sum(ch.isprintable() or ch in "\r\n\t" for ch in s) / len(s) > 0.9:
                return "text"
    return "text" if (name.endswith((".txt", ".md", ".utf-8"))) else "unknown"


# --------------------------------------------------------------------------

def _first_book_for(bzs) -> str:
    """The OSIS id of the first book in a .bzs, from its file name.

    SWORD splits a module into one file per testament and names them `nt` and
    `ot` (also `ps`, `ntdeut`, ...).  Without this a marker-less New Testament
    gets its block numbers counted from Genesis and every reference is wrong.
    """
    name = Path(str(bzs)).name.lower()
    ot = [b.osis for b in canon.BOOKS_66[:39]]
    nt = [b.osis for b in canon.BOOKS_66[39:]]
    if name.startswith("nt"):
        return nt[0]
    if name.startswith(("ot", "ps")):
        return ot[0]
    return ""


def load_sword_zip(data: bytes, *, keep_notes: bool = True,
                   wanted_books: set[str] | None = None
                   ) -> tuple[sword.Conf, Iterator[UnitIn], dict]:
    """Read a SWORD package (CrossWire zip, eBible SWORD build)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    conf_name = sword.find_conf(zf)
    conf = sword.Conf(zf.read(conf_name).decode("utf-8", "replace"), conf_name)
    prefix = sword.data_prefix(zf, conf)
    drv = (conf.get("ModDrv") or "zText").strip()
    src_type = conf.get("SourceType") or ("OSIS" if drv.startswith("z") else "Plaintext")
    compress = conf.get("CompressType") or ("ZIP" if drv.startswith("z") else "ZIP")
    encoding = conf.get("Encoding") or "UTF-8"
    meta = conf.all()

    if drv in ("zText", "zText4", "zCom", "zCom4"):
        sets = _zgroups(zf, prefix)
        if not sets:
            raise sword.SwordError("no .bzs/.bzv/.bzz triple in package")

        def units() -> Iterator[UnitIn]:
            for bzs, bzv, bzz in sets:
                z = sword.ZText(_zpath(zf, bzs), _zpath(zf, bzv), _zpath(zf, bzz),
                                encoding=encoding, source_type=src_type,
                                compress=compress)
                # Needed to walk a marker-less module's verse sequence: the
                # book for a block is its number within *its own testament*, so
                # `nt` block 1 is Matthew and `ot` block 1 is Genesis.
                z.versification = conf.get("Versification") or ""
                z.first_book = _first_book_for(bzs)
                # A bible is indexed by osisID chapter markers.  A chapter-blocked
                # commentary is not -- its verse anchors are in the text, so it
                # needs the anchoring reader instead.  Picking the wrong one
                # yields either nothing or nonsense.
                if drv.startswith("zCom") and not z.has_osis_chapters():
                    gen = z.units_anchored()
                else:
                    gen = z.units()
                for u in gen:
                    if wanted_books and u.book and u.book not in wanted_books:
                        continue
                    yield u
        return conf, units(), meta

    if drv in ("RawText", "RawText4", "RawCom", "RawCom4", "HREFCom", "RawFiles"):
        def raw() -> Iterator[UnitIn]:
            for n in sorted(zf.namelist()):
                if not n.startswith(prefix) or n.endswith("/"):
                    continue
                low = n.lower()
                # `.vss` / `.idx` / `.bbi` are the driver's own binary indexes,
                # not content.  They used to be installed as units, so a
                # commentary came out as five "notes" called nt, ot, nt.vss,
                # ot.vss and intro.txt.
                if low.endswith((".vss", ".idx", ".bbi", ".bdb", ".map")):
                    continue
                data = zf.read(n)
                if b"\x00" in data[:2000]:
                    continue                       # binary, not text
                base = Path(n).stem
                text = data.decode(sword._pyenc(encoding), "replace")
                # Same rule as the note path: a body carrying markup is parsed
                # as markup even when the conf says ThML, or the tags are shown
                # to the reader verbatim.
                if src_type.lower() == "osis" or "<" in text:
                    segs = markup.parse_osis(text)
                else:
                    segs = markup.parse_plain(text)
                # A RawCom file is a sequence of notes, each opened by a bare
                # reference on its own line.  Installing the file as one unit
                # makes a 10,000-note commentary a single unsearchable row, so
                # it is split into notes keyed by their reference.
                notes = sword.split_rawcom_notes(text)
                if len(notes) > 1:
                    for key, body in notes:
                        # A note body is markup even when the conf says ThML
                        # rather than OSIS: Ansorg's German commentary is HTML
                        # (<FONT>, <LI>, <td>).  parse_osis treats those tags as
                        # transparent and drops them; parse_plain would show
                        # them to the reader verbatim.
                        s = (markup.parse_osis(body)
                             if src_type.lower() == "osis" or "<" in body
                             else markup.parse_plain(body))
                        if not s:
                            continue
                        # Resolve the book name where we can, so a German
                        # commentary is reachable by reference and not only by
                        # searching its text.
                        key = sword.canonicalise_note_key(key)
                        # The verse reader finds a unit by its book and chapter
                        # *columns*, not by its key, so a note keyed "John 3:1"
                        # has to carry them or it is invisible to a reference
                        # lookup even though it is present and searchable.
                        osis, chapter, verse = sword.split_note_key(key)
                        yield UnitIn(key=key, label=key, segs=s, markup=body,
                                     title=key, book=osis or "",
                                     chapter=chapter, verse=verse,
                                     extra={"source_file": base})
                    continue
                yield UnitIn(key=base, label=base, segs=segs, markup=text,
                             title=base)
        return conf, raw(), meta

    if drv in ("RawLD", "RawLD4"):
        names = _lexdict_files(zf, prefix, conf, (".dat",))
        if not names:
            raise sword.SwordError(
                f"no .dat for the {drv} driver under {prefix!r}")

        def rawld() -> Iterator[UnitIn]:
            for n in names:
                tmp = _extract(zf, n)
                try:
                    for key, body in sword.read_rawld(
                            tmp, case_insensitive=conf.get("CaseInsensitiveKeys", "true")
                            .lower() != "false"):
                        key = _clean_key(key)
                        if not key or not body.strip():
                            continue
                        # RawLD ends every line with "<br />\n".  The parser
                        # turns the tag into a break and keeps the newline as
                        # text, so every line ends up doubled.  Drop the newline
                        # that follows the tag and the text reads correctly.
                        body = re.sub(r"(?i)<br\s*/>\s*\n?", "<br />", body)
                        if plain.looks_like_html(body):
                            segs = markup.parse_html(body)
                        elif src_type.lower() in ("tei", "thml"):
                            segs = markup.parse_teithml(body)
                        else:
                            segs = markup.parse_plain(body)
                        yield UnitIn(key=key, label=key, segs=segs,
                                     markup=body, title=key)
                finally:
                    tmp.unlink(missing_ok=True)
        return conf, rawld(), meta

    if drv in ("zLD", "zLD4"):
        members = _lexdict_files(zf, prefix, conf, (".dat", ".zdt", ".idx", ".zdx"))
        if not members:
            raise sword.SwordError(
                f"no dictionary data for the {drv} driver under {prefix!r}")

        def zld() -> Iterator[UnitIn]:
            # The reader needs .dat/.idx (or .zdt) side by side on disk, so the
            # whole DataPath is unpacked into one scratch directory.
            tmpdir = Path(tempfile.mkdtemp(prefix="gbible-zld-"))
            try:
                for n in members:
                    dst = tmpdir / Path(n).name
                    if not dst.exists():
                        dst.write_bytes(zf.read(n))
                for base in sorted({str(tmpdir / Path(n).with_suffix("").name)
                                    for n in members}):
                    for key, body in sword.read_zld(Path(base)):
                        key = _clean_key(key)
                        if not key or not body.strip():
                            continue
                        # RawLD ends every line with "<br />\n".  The parser
                        # turns the tag into a break and keeps the newline as
                        # text, so every line ends up doubled.  Drop the newline
                        # that follows the tag and the text reads correctly.
                        body = re.sub(r"(?i)<br\s*/>\s*\n?", "<br />", body)
                        # A tag whose attribute value has no closing quote
                        # cannot be matched by the tag parser, so the closing
                        # quote and bracket that follow it are read as text.
                        # Abbott-Smith (Strong's) has this in
                        # <checked-cfb except="rongs numbers?>">, whose last
                        # three characters are transposed, so its entries opened
                        # with a stray `">`.  The quote inside `[^"<>]` blocks
                        # every well-formed tag, so nothing else is touched.
                        body = re.sub(r'(<[A-Za-z][^<>]*?="[^"<>]*?)>">', r'\1>', body)
                        yield UnitIn(key=key, label=key,
                                     segs=markup.parse_teithml(body),
                                     markup=body, title=key)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return conf, zld(), meta

    if drv in ("RawGenBook", "RawGenBook2"):
        def genbook() -> Iterator[UnitIn]:
            # The text lives in `.bdt`; `.dat`/`.idx` are the driver's own
            # bookmark index.  Reading `.dat` yielded nothing, so every
            # RawGenBook -- 32 modules, including Calvin's Institutes and
            # John Owen's works -- installed empty.
            bdts = _lexdict_files(zf, prefix, conf, (".bdt",))
            for n in sorted(bdts):
                tmp = _extract(zf, n)
                try:
                    raw = tmp.read_text(encoding=encoding, errors="replace")
                except OSError:
                    continue
                finally:
                    tmp.unlink(missing_ok=True)
                sections = sword.split_genbook_sections(raw)
                for i, (title, body) in enumerate(sections, 1):
                    # A RawGenBook body is markup even when the conf does not say
                    # "osis": Calvin's Institutes and Josephus are HTML-ish
                    # (<p>, <scripref>) with no <title> at all.  parse_osis
                    # treats those tags (and leaves text alone in a plain file),
                    # whereas parse_plain would show the raw tags to the reader.
                    segs = markup.parse_osis(body) if \
                        src_type.lower() == "osis" or "<" in body \
                        else markup.parse_plain(body)
                    if not segs:
                        continue
                    key = title or f"section {i}"
                    yield UnitIn(key=key, label=key, segs=segs, markup=body,
                                 title=title or key, extra={"section": i})
                if sections:
                    continue
            for n in sorted(_lexdict_files(zf, prefix, conf, (".dat", ".idx"))):
                tmp = _extract(zf, n)
                try:
                    for key, body in sword.read_rawld(tmp):
                        key = _clean_key(key)
                        if not key or not body.strip():
                            continue
                        # RawLD ends every line with "<br />\n".  The parser
                        # turns the tag into a break and keeps the newline as
                        # text, so every line ends up doubled.  Drop the newline
                        # that follows the tag and the text reads correctly.
                        body = re.sub(r"(?i)<br\s*/>\s*\n?", "<br />", body)
                        yield UnitIn(key=key, label=key,
                                     segs=plain.parse_body(body), title=key)
                finally:
                    tmp.unlink(missing_ok=True)
        return conf, genbook(), meta

    raise sword.SwordError(f"unsupported ModDrv={drv}")


def _clean_key(k: str) -> str:
    """A lexicon headword as plain text.

    SWORD RawLD keys are sometimes an HTML fragment (a whole <LI> line in the
    Condensed Biblical Cyclopedia), and a key is what the reader shows as the
    article title -- so tags are stripped rather than displayed.
    """
    k = re.sub(r"<[^>]+>", " ", k or "")
    k = markup.unescape(k)
    return markup.collapse(k).strip()[:120]


def _lexdict_files(zf, prefix: str, conf, suffixes: tuple[str, ...]) -> list[str]:
    """Members of a lexdict driver.

    The DataPath names the file *base* for these drivers, so the base is stripped
    off to find the directory and then used to select the exact file set.
    """
    dp = (conf.get("DataPath") or "").strip().replace("\\", "/")
    if dp.startswith("./"):
        dp = dp[2:]
    base = ""
    if dp and not dp.endswith("/"):
        base = dp.rsplit("/", 1)[-1]
    out = []
    for n in zf.namelist():
        if not n.startswith(prefix) or not n.lower().endswith(suffixes):
            continue
        if base and Path(n).stem not in (base, base.rsplit(".", 1)[0]):
            continue
        out.append(n)
    return sorted(out)


def _zgroups(zf: zipfile.ZipFile, prefix: str) -> list[tuple[str, str, str]]:
    bzs = sword.list_entries(zf, prefix, (".bzs", ".czs"))
    bzv = sword.list_entries(zf, prefix, (".bzv", ".czv"))
    bzz = sword.list_entries(zf, prefix, (".bzz", ".czz"))
    out = []
    for s in bzs:
        stem = Path(s).stem
        v = next((x for x in bzv if Path(x).stem == stem), None)
        d = next((x for x in d_ if Path(x).stem == stem), None) \
            if (d_ := bzz) else None
        if not (v and d):
            continue
        # A New-Testament-only module still ships empty `ot.*` files, and
        # walking a zero-byte index is what made the Cherokee NT fail outright
        # rather than simply yielding its Testament.
        try:
            if zf.getinfo(s).file_size == 0 or zf.getinfo(d).file_size == 0:
                continue
        except KeyError:
            continue
        out.append((s, v, d))
    return out


class _ZPath:
    """A lazily-extracted member of a zip, cleaned up with the ZipFile."""

    def __init__(self, zf: zipfile.ZipFile, name: str, tmpdir: Path):
        self.zf, self.name, self.tmpdir = zf, name, tmpdir
        self._p: Path | None = None

    @property
    def path(self) -> Path:
        if self._p is None:
            self._p = self.tmpdir / Path(self.name).name
            self._p.write_bytes(self.zf.read(self.name))
        return self._p

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, k):
        return getattr(self.path, k)


def _zpath(zf, name):
    return _ZPath(zf, name, Path(tempfile.mkdtemp(prefix="gbible-")))


def _extract(zf: zipfile.ZipFile, name: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix="gbible-")) / Path(name).name
    p.write_bytes(zf.read(name))
    return p


# --------------------------------------------------------------------------

def load_esword9(path: Path, *, type_hint: str | None = None
                 ) -> tuple[dict, Iterator[UnitIn]]:
    return esword.esword_units(path, type_hint=type_hint)


def load_usfm_zip(data: bytes, *, keep_notes: bool = True) -> Iterator[UnitIn]:
    return usfm.usfm_from_zip(zipfile.ZipFile(io.BytesIO(data)),
                             keep_notes=keep_notes)


def load_usfm_file(path: Path, *, keep_notes: bool = True) -> Iterator[UnitIn]:
    return usfm.usfm_from_dir(path.parent, keep_notes=keep_notes)


def load_epub(data: bytes, *, kind: str = "Book", source: str = ""
              ) -> tuple[dict, Iterator[UnitIn]]:
    """A personal book.  Returns (metadata, units) -- the metadata is the
    EPUB's own, so author, language and rights come from the file."""
    return epub.load(data, kind=kind, source=source)


def load_epub_file(path: Path, **kw) -> tuple[dict, Iterator[UnitIn]]:
    return epub.load_file(path, **kw)


def load_text(path: Path, *, kind: str = "", source: str = "") -> Iterator[UnitIn]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    h = kind or plain.detect_kind(path, raw, "")
    if h in ("Commentary", "StudyGuide", "SermonOutline", "Harmony"):
        k = h
    elif h == "Lexicon" or h == "Dictionary":
        k = "Lexicon"
    else:
        k = "Book"
    return plain.units_from_articles(raw, kind=k, source=source or path.stem)


def load_plain_bytes(data: bytes, *, kind: str = "Book", source: str = "",
                     encoding: str = "utf-8") -> Iterator[UnitIn]:
    raw = data.decode(sword._pyenc(encoding), "replace")
    return plain.units_from_articles(raw, kind=kind, source=source)


def load_wikitext(pages: list[tuple[str, str]], *, kind: str = "Commentary"
                  ) -> Iterator[UnitIn]:
    return plain.units_from_wikitext_pages(pages, kind=kind)
