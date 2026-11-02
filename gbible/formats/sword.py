"""SWORD module readers.

The CrossWire / e-Sword zText / zCom container, plus the RawLD and zLD lexicon
drivers.  Everything here was verified against real modules:

  .bzs / .czs   flat array of 12-byte records, little-endian uint32 x3:
                 (blockStart, compressedSize, uncompressedSize).  No header.
                 Block 0 is an importer-provenance <milestone/>, so
                 numBlocks == nBooks + 1 -- but never assume one block per book,
                 because importers split large books.
  .bzv / .czv   flat array of 10-byte records, little-endian:
                 (blockNumber: uint32, verseStart: uint32, verseLength: uint16).
                 THESE ARE THE ONLY SOURCE OF VERSE BOUNDARIES.  There are no
                 <verse> elements in a SWORD module; do not regex for them.
  .bzz / .czz   concatenation of independent compression streams at the .bzs
                 offsets.  CompressType=ZIP means each block is its own zlib
                 stream, so zlib.decompress() on the slice is exact.

The verse index is walked as a state machine rather than by ordinal arithmetic,
because ordinal offsets depend on the module's declared Versification and real
modules disagree with each other about that.
"""

from __future__ import annotations

import configparser
import re
import struct
import zlib
from pathlib import Path
from typing import Iterator

from .. import canon, markup
from ..indexer import UnitIn
from ..markup import Seg


class SwordError(Exception):
    pass


# --------------------------------------------------------------------------
# .conf
# --------------------------------------------------------------------------

class Conf:
    """A SWORD .conf file.  One [ModName] section, UTF-8 INI."""

    def __init__(self, text: str, path: str = ""):
        self.path = path
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str          # field names are case-sensitive
        try:
            cp.read_string(text)
        except configparser.Error:
            # Some conf files in the wild are not strictly valid INI: a repeated
            # `__raw__` section, a bare key with no value, a stray continuation.
            # configparser is already non-strict, but the *fallback* below has to
            # add its holding section exactly once -- adding it per line raised
            # DuplicateSectionError on the second line and aborted the install.
            if "__raw__" not in cp.sections():
                cp.add_section("__raw__")
            for line in text.splitlines():
                if line.strip() and not line.startswith(("[", "#", ";", "\n")) \
                   and "=" in line:
                    k, _, v = line.partition("=")
                    try:
                        cp.set("__raw__", k.strip(), v.strip())
                    except (configparser.DuplicateOptionError,
                            configparser.NoSectionError):
                        pass
            # A duplicate `[__raw__]` still needs the real section to win, so
            # re-read leniently and keep whatever parsed.
            try:
                lenient = configparser.ConfigParser(interpolation=None,
                                                    strict=False)
                lenient.optionxform = str
                lenient.read_string(text)
                if lenient.sections():
                    cp = lenient
            except configparser.Error:
                pass
        self.cp = cp
        self.section = cp.sections()[0] if cp.sections() else "__raw__"
        if self.section == "__raw__" and len(cp.sections()) > 1:
            self.section = cp.sections()[1]
        self.modname = re.sub(r"[\[\]]", "", self.section)

    def get(self, key: str, default: str = "") -> str:
        v = self.cp.get(self.section, key, fallback=None)
        if v is None:
            # case-insensitive second chance
            for k in cp_opts(self.cp, self.section):
                if k.lower() == key.lower():
                    v = self.cp.get(self.section, k)
                    break
        return default if v is None else v

    def getlist(self, key: str) -> list[str]:
        out = []
        for k in cp_opts(self.cp, self.section):
            if k.lower() == key.lower():
                v = self.cp.get(self.section, k)
                if v:
                    out.extend(x.strip() for x in v.split(",") if x.strip())
        return out

    def getint(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, "").strip() or default)
        except ValueError:
            return default

    def all(self) -> dict:
        return {k: self.cp.get(self.section, k, fallback="")
                for k in cp_opts(self.cp, self.section)}


def cp_opts(cp, section):
    try:
        return cp.options(section)
    except Exception:
        return []


# --------------------------------------------------------------------------
# zText / zCom binary container
# --------------------------------------------------------------------------

_BLOCK = struct.Struct("<III")
_VERSE = struct.Struct("<IIH")


class ZText:
    def __init__(self, bzs: Path, bzv: Path, bzz: Path, *,
                 encoding: str = "UTF-8", source_type: str = "OSIS",
                 compress: str = "ZIP"):
        self.bzs = bzs
        self.bzv = bzv
        self.bzz = bzz
        self.encoding = _pyenc(encoding)
        self.source_type = source_type
        self.compress = (compress or "ZIP").upper()
        self._blocks: list[tuple[int, int, int]] | None = None
        self._cache: dict[int, bytes] = {}
        self._cache_order: list[int] = []
        # verse counter per (book, chapter) while walking the index
        self._counters: dict[tuple[str, int], int] = {}
        self._seq: tuple[str, list[tuple[int, int]]] | None = None
        self.versification = ""
        self.first_book = ""

    # -- block table --------------------------------------------------
    @property
    def blocks(self) -> list[tuple[int, int, int]]:
        if self._blocks is None:
            raw = self.bzs.read_bytes()
            if len(raw) % 12:
                # Tolerate a header variant rather than refusing to read.
                raw = raw[:len(raw) - (len(raw) % 12)]
            self._blocks = [_BLOCK.unpack_from(raw, 12 * i)
                            for i in range(len(raw) // 12)]
        return self._blocks

    def _decompress(self, blob: bytes) -> bytes:
        if self.compress == "ZIP":
            try:
                return zlib.decompress(blob)
            except zlib.error:
                # Raw deflate fallback, then LZSS (unavailable) -> bzip2/xz.
                try:
                    return zlib.decompressobj(-15).decompress(blob)
                except zlib.error:
                    pass
            try:
                return zlib.decompress(blob, -15)
            except zlib.error:
                pass
        elif self.compress == "BZIP2":
            import bz2
            try:
                return bz2.decompress(blob)
            except OSError:
                pass
        elif self.compress in ("XZ", "LZMA"):
            import lzma
            for fb in (lzma.FORMAT_XZ, lzma.FORMAT_ALONE, lzma.FORMAT_RAW):
                try:
                    return lzma.decompress(blob, format=fb)
                except (lzma.LZMAError, ValueError):
                    continue
        elif self.compress == "GZIP":
            import gzip
            try:
                return gzip.decompress(blob)
            except OSError:
                pass
        raise SwordError(
            f"unsupported CompressType={self.compress} (LZSS has no public codec; "
            "install a ZIP/BZIP2/XZ build of the module)")

    def block_bytes(self, n: int) -> bytes:
        """Decompressed block, kept as BYTES.

        The .bzv offsets are byte offsets.  Slicing the decoded str instead
        silently corrupts every entry after the first non-ASCII character in a
        block, which looks like plausible-but-wrong text rather than an error.
        """
        if n in self._cache:
            return self._cache[n]
        s, c, _u = self.blocks[n]
        with self.bzz.open("rb") as f:
            f.seek(s)
            blob = f.read(c)
        data = self._decompress(blob)
        self._cache[n] = data
        self._cache_order.append(n)
        if len(self._cache_order) > 96:
            del self._cache[self._cache_order.pop(0)]
        return data

    def block_text(self, n: int) -> str:
        return self.block_bytes(n).decode(self.encoding, "replace")

    def entry(self, i: int) -> tuple[int, int, int]:
        with self.bzv.open("rb") as f:
            f.seek(10 * i)
            raw = f.read(10)
        if len(raw) < 10:
            raise SwordError(f"verse index {i} out of range")
        return _VERSE.unpack(raw)

    def entry_count(self) -> int:
        return self.bzv.stat().st_size // 10

    # -- walking ------------------------------------------------------
    def has_osis_chapters(self, sample: int = 400) -> bool:
        """Does this module carry osisID chapter markers?

        It decides which reader to use.  A zText bible does.  A zCom commentary
        with BlockType=CHAPTER does not: its index entries are whole chunks of
        commentary and the verse anchors live in the *text*, so the osis reader
        would find no book or chapter and yield nothing.
        """
        n = min(self.entry_count(), sample)
        for i in range(n):
            try:
                blk, start, length = self.entry(i)
            except SwordError:
                break
            if length == 0:
                continue
            try:
                txt = self.block_bytes(blk)[start:start + length].decode(
                    self.encoding, "replace")
            except IndexError:
                continue
            if _CHAPTER_OPEN_RE.search(txt) and re.search(
                    r'osisID="[A-Za-z0-9]+\.\d+"', txt):
                return True
        return False

    def units_anchored(self) -> Iterator[UnitIn]:
        """Reader for chapter-blocked commentaries (zCom, BlockType=CHAPTER).

        Each index entry is a chunk of commentary.  The verse it belongs to is
        recovered from, in order of reliability:
          1. a scripture reference in the entry -- `<scriRef passage="Mt 1:3">`,
             `<reference osisRef="Matt.1.3">`;
          2. an explicit `Verse N` / `Ver. N` anchor plus the running book and
             chapter from the nearest heading;
          3. otherwise the entry stays with the reference it most recently saw,
             so commentary is never dropped.

        Result: every chunk lands on a verse, which is what makes the commentary
        linkable to a Bible at all.
        """
        book = chapter = 0
        cur_key = ""
        cur: list[str] = []
        n = self.entry_count()
        for i in range(n):
            try:
                blk, start, length = self.entry(i)
            except SwordError:
                break
            if length == 0:
                continue
            try:
                txt = self.block_bytes(blk)[start:start + length].decode(
                    self.encoding, "replace")
            except IndexError:
                continue
            if not _has_content(txt):
                continue

            head = _commentary_book(txt)
            head_verse = 0
            had_chapter = False
            head_chapter = False
            if head:
                book, ch = head[0], head[1]
                had_chapter = head_chapter = bool(ch)
                if ch:
                    chapter = ch
                if len(head) > 2:
                    head_verse = head[2]
            anchor = _verse_anchor(txt, relaxed=had_chapter) or head_verse

            # Two independent signals, and they are good for different things.
            #
            # The `Verse N` anchor states which verse the chunk is about -- but
            # says nothing about which book.  A `<scriRef passage="Jn 3:11">`
            # is the author's own attribution of book and chapter, and is the
            # only signal that survives in books whose notes carry no chapter
            # heading; its *verse*, though, is usually a cross-reference and
            # must not be used.
            #
            # So: book+chapter from the scriRef when there is one, verse from the
            # anchor when there is one, running values otherwise.
            ref = _commentary_ref(txt)
            if head_chapter:
                # An explicit "BOOK Chapter N" heading is the author's own
                # structure and outranks anything quoted inside the text.
                pass
            elif ref is not None and ref[0]:
                book = ref[0]
                if ref[1]:
                    chapter = ref[1]
            if book and chapter:
                verse = anchor or (ref[2] if ref else 0) or 1
                if not anchor and cur_key.startswith(f"{book}.{chapter}."):
                    verse = int(cur_key.rsplit(".", 1)[1])
                new_key = f"{book}.{chapter}.{verse}"
            elif book:
                chapter = chapter or 1
                new_key = f"{book}.{chapter}.{anchor or 1}"
            else:
                new_key = ""            # front matter: keep reading

            if new_key and new_key != cur_key:
                yield from self._flush_com(cur_key, cur)
                cur = []
                cur_key = new_key
            segs = _parse_by_source(txt, self.source_type)
            cur.extend(s.text for s in segs if s.is_text())
            cur.append("\n")
        yield from self._flush_com(cur_key or "front", cur)

    def _flush_com(self, key: str, body: list[str]):
        if not key or not any(x.strip() for x in body):
            return
        text = "\n".join(body).strip()
        segs = markup.parse_plain(text)
        # "Apostelgeschichte 1:1" -> ("Acts", "1:1") when the name is one we
        # know, so the note is reachable by reference.  An unrecognised name is
        # kept as written rather than dropped: the note is still readable and
        # searchable under its own label.
        head, _, tail = key.rpartition(" ")
        osis = _canonical_book(head) if head else ""
        key = f"{osis} {tail}" if osis else key
        parts = key.split(".")
        if len(parts) < 3:
            # Front matter is keyed "front"; a malformed key must not take the
            # whole install down with an IndexError.
            yield UnitIn(key=key, label=key, segs=segs, markup=text,
                         title=key)
            return
        yield UnitIn(key=key, label=canon.format_ref(canon.Ref(*parts)),
                     segs=segs, markup=text,
                     book=parts[0], chapter=parts[1], verse=parts[2])

    def units(self, *, on_book=None) -> Iterator[UnitIn]:
        """Walk the verse index and yield one UnitIn per verse.

        Book boundaries come from `<div osisID="Book" type="book"/>`; chapter
        boundaries from a `<chapter .../>` element that carries a chapter
        *number* (`n=` or `osisID="Book.N"`).

        Two details that are easy to get wrong and that silently shift every
        verse after them:
          * a chapter's *closing* marker (`<chapter eID="..."/>`) is appended to
            that chapter's last verse, so an entry containing `<chapter>` is not
            automatically a marker;
          * the closing tag is spelled `</chapter>`, which a naive
            `"<chapter" in txt` test also matches.

        **Modules with no markers at all.**  Plenty of SWORD modules -- the
        Bible in Basic English, the Conservative Version, Noyes, the 1873 Oxford
        Textus Receptus -- carry plain text with not one `<div>` or `<chapter>`
        anywhere.  Refusing them (which is what this used to do) throws away
        real, readable Bibles; deriving nothing from the index leaves the user
        with an empty pane and no explanation.  So when a block yields no
        markers, the book comes from the block number -- `BlockType=BOOK` puts
        one book per block, and block 0 is importer provenance -- and the
        chapter and verse are recovered by walking that book's verse sequence
        in the module's own versification, which is exactly the order the
        `.bzv` index lists them in.
        """
        book = ""
        chapter = 0
        yielded = 0
        saw_marker = False
        unmarked: dict[int, list[str]] = {}      # block -> texts
        n = self.entry_count()
        for i in range(n):
            blk, start, length = self.entry(i)
            if length == 0:
                continue
            try:
                txt = self.block_bytes(blk)[start:start + length].decode(
                    self.encoding, "replace")
            except IndexError:
                continue
            if _CHAPTER_OPEN_RE.search(txt):
                saw_marker = True
                mb = re.search(r'osisID="([A-Za-z0-9]+)\.(\d+)"', txt)
                mn = re.search(r'<chapter[^>]*\bn="(\d+)"', txt)
                if mb or mn:
                    if mb:
                        book = mb.group(1) or book
                        chapter = int(mb.group(2))
                    else:
                        chapter = int(mn.group(1))
                    continue
                # closing marker with no number: keep going, the verse it was
                # appended to still has to be emitted
            mb = re.search(r'osisID="([A-Za-z0-9]+)"[^>]*type="book"', txt)
            if mb and not _has_content(txt):
                saw_marker = True
                book = mb.group(1)
                if on_book:
                    on_book(book)
                continue
            if not _has_content(txt):
                continue
            if book and chapter:
                v = self._counters.get((book, chapter), 0) + 1
                self._counters[(book, chapter)] = v
                yielded += 1
                yield self._mk_unit(book, chapter, v, txt)
            else:
                unmarked.setdefault(blk, []).append(txt)

        if yielded:
            return
        if unmarked:
            offset = self._provenance_offset()
            n_yielded = 0
            for blk, texts in unmarked.items():
                for u in self._unmarked_book_units(blk, texts, offset):
                    n_yielded += 1
                    yield u
            if n_yielded:
                return
        raise SwordError(
            f"{self.bzs.name}: the text carries no book or chapter markers and "
            "its blocks could not be assigned to books, so it cannot be split "
            "into referenceable verses.")

    def _provenance_offset(self) -> int:
        """1 if block 0 is an importer-provenance block, else 0.

        SWORD's own docs say block 0 is a `<milestone/>` written by the
        importer, but that is not universal: the Bible in Basic English has
        exactly one block per book with Genesis (or Matthew) in block 0.
        Assuming a leading provenance block shifts every book by one, so Gen 1:1
        came out as Exodus.  Look at the block instead of trusting the doc.
        """
        try:
            first = self.block_text(0)
        except Exception:                   # noqa: BLE001
            return 1
        if "<milestone" in first.lower():
            return 1
        if not _has_content(first):
            return 1
        # 39 blocks for the OT and 27 for the NT is exactly the book count,
        # so there is no room for a provenance block.
        return 0

    def _unmarked_book_units(self, blk: int, texts: list[str], offset: int = 1):
        """Assign a book by block number and walk its verse sequence in order."""
        order = [b.osis for b in canon.BOOKS_66]
        if self.first_book and self.first_book in order:
            start = order.index(self.first_book)
        else:
            start = 0
        idx = start + blk - offset
        if idx < 0 or idx >= len(order):
            return
        osis = order[idx]
        counts = self._verse_sequence(osis)
        pos = 0
        for txt in texts:
            if pos < len(counts):
                chapter, verse = counts[pos]
            else:                           # more verses than the versification
                chapter = counts[-1][0] if counts else 1
                verse = (counts[-1][1] + 1) if counts else 1
            pos += 1
            yield self._mk_unit(osis, chapter, verse, txt)

    def _verse_sequence(self, osis: str) -> list[tuple[int, int]]:
        """(chapter, verse) in canonical order for this module's versification."""
        if self._seq is None or self._seq[0] != osis:
            scheme = self.versification or "KJV"
            seq: list[tuple[int, int]] = []
            for ch, n in enumerate(canon.verse_counts(scheme, osis), 1):
                for vs in range(1, n + 1):
                    seq.append((ch, vs))
            self._seq = (osis, seq)
        return self._seq[1]

    def _mk_unit(self, book: str, chapter: int, verse: int, txt: str) -> UnitIn:
        segs = _parse_by_source(txt, self.source_type)
        return UnitIn(key=f"{book}.{chapter}.{verse}",
                      label=canon.format_ref(canon.Ref(book, chapter, verse)),
                      segs=segs, markup=txt, book=book, chapter=chapter,
                      verse=verse, title=_chapter_title(segs))


# Matches only an *opening* <chapter ...>: the closing </chapter> form must not
# count, or the verse it is attached to gets discarded.
_CHAPTER_OPEN_RE = re.compile(r"<chapter[\s/>]", re.I)

# -- commentary anchoring --------------------------------------------------
_SCRIREF = re.compile(
    r"<(?:scripref|reference)\b[^>]*"
    r"(?:passage|osisref|osisRef|raw|href)\s*=\s*[\"']([^\"']+)[\"']",
    re.I)
_SCRIREF2 = re.compile(r"<(?:scripref|reference)\b[^>]*>[^<]*?</(?:scripref|reference)>",
                       re.I | re.S)
# "Verse 4."  "Ver 23."  "Verses 22, 23."  "Verses 2-16."  -- the anchor that
# says which verse a chunk of commentary is about.
_VERSE_ANCHOR = re.compile(
    r"^\s*(?:<[^>]+>\s*)*Verse[s]?\s*\.?\s*"
    r"(\d{1,3})\s*(?:[-–,]|\band\b)?\s*(\d{1,3})?\s*[.:,]?\s*"
    r"(?:<[^>]+>\s*)*", re.I)
# "MATTHEW Chapter 2" sets the chapter; "Matthew Verses 2-16" does NOT -- it is a
# verse range, and reading its number as a chapter throws the whole book off by
# one.  The keyword is captured so the two cases can be told apart.
_COM_BOOK = re.compile(
    r"^\s*(?:<[^>]+>\s*)*([A-Za-z][A-Za-z ]*?)\s+"
    r"(Chapter|Ch\.|Verses?)\s*(\w+)?(?:\s*[-–]\s*(\w+))?", re.M)
# a bare all-caps book name on its own line, e.g. "ROMANS"
_COM_BARE = re.compile(
    r"^\s*(?:<[^>]+>\s*)*([A-Z][A-Z]{2,12}(?:\s+[A-Z][A-Z]{2,12})?)\s*"
    r"(?:<[^>]+>\s*)*$", re.M)


def _b(osis: str):
    return canon.BOOK_BY_OSIS.get(osis)


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
          "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
          "twenty": 20, "first": 1, "second": 2, "third": 3, "fourth": 4,
          "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
          "tenth": 10, "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def _num(v) -> int:
    if not v:
        return 0
    s = str(v).strip().lower().strip(".")
    if s.isdigit():
        return int(s)
    return _WORDS.get(s, 0)


def _commentary_ref(txt: str):
    """(book_osis, chapter, verse) from the first scripture reference, or None."""
    for m in _SCRIREF.finditer(txt):
        raw = m.group(1)
        rr = canon.parse_ref(raw) or canon.parse_osis_ref(raw)
        if rr and rr.start.book:
            return (rr.start.book, rr.start.chapter, rr.start.verse)
    for m in _SCRIREF2.finditer(txt):
        inner = re.sub(r"<[^>]+>", "", m.group(0))
        rr = canon.parse_ref(inner)
        if rr and rr.start.book:
            return (rr.start.book, rr.start.chapter, rr.start.verse)
    return None


_VERSE_LOOSE = re.compile(r"\bVerses?\s+(\d{1,3})\b", re.I)


def _verse_anchor(txt: str, *, relaxed: bool = False) -> int:
    """The verse a chunk of commentary is about.

    Two forms occur, and the second is easy to miss:
      "Verse 4.  ..."                       -- the anchor opens the entry
      "MARK Chapter 15. <br/> Verses 1-15." -- a chapter heading and a verse
                                               range in the same entry
    `relaxed` (pass it when a chapter heading was found) searches the head of the
    text for the range as well.
    """
    lines = txt.split("\n")
    for ln in lines[:4]:
        m = _VERSE_ANCHOR.match(ln)
        if m:
            return int(m.group(1))
    if relaxed:
        m = _VERSE_LOOSE.search("\n".join(lines[:4]))
        if m:
            return int(m.group(1))
    return 0


def _commentary_book(txt: str):
    """(book osis, chapter) from a heading line, or None.

    Both "Matthew Verses 2-16" and "MATTHEW Chapter 2" occur, sometimes with
    tags before the text, so the heading is matched anywhere in the first few
    lines and the chapter is optional.
    """
    head = "\n".join(txt.split("\n")[:3])
    for m in _COM_BOOK.finditer(head):
        b = canon.lookup_book(m.group(1))
        if not b:
            continue
        kind = m.group(2).lower()
        num = _num(m.group(3) or m.group(4))
        ch = 0
        if kind.startswith("ch"):
            # "Chapter Two" as well as "Chapter 2"
            ch = num
        elif kind.startswith("verse") and num:
            # a verse-range heading: it identifies the passage, not a chapter
            return (b.osis, 0, num)
        return (b.osis, ch)
    for m in _COM_BARE.finditer(head):
        b = canon.lookup_book(m.group(1))
        if b:
            return (b.osis, 0)
    return None
_MILESTONE_ONLY = re.compile(r"^\s*(?:<milestone[^>]*/>\s*)+$")


_CONTENT_RE = re.compile(
    r"<w[\s>]|</w>|<transChange|<note[\s>]|<reference[\s>]|"
    r"<seg[\s>]|<hi[\s>]|<q[\s>]|<divineName[\s>]|<foreign[\s>]|"
    r"<(?!\s*/?\s*(?:div|chapter|milestone|title|lb|note|reference|hi|seg|"
    r"list|item|figure|p|span)\b)[A-Za-z]")


def _has_content(txt: str) -> bool:
    """Does this index entry carry actual verse text?

    Real modules emit structure-only entries (paragraph milestones, section
    dividers, empty chapter wrappers).  Counting those as verses shifts every
    subsequent number in the chapter, so they are skipped -- but an entry whose
    *text* is present must be kept even if it also carries a closing marker.
    """
    if _CONTENT_RE.search(txt):
        return True
    stripped = re.sub(r"<[^>]*>", "", txt)
    return bool(stripped.strip())


def _is_milestone_only(txt: str) -> bool:
    return not _has_content(txt)


def _read_dat_sequential(dat: Path):
    """Yield (key, body) walking .dat's own length prefixes.

    Returns a list rather than a generator so the caller can tell an empty
    dictionary from one this layout does not describe.
    """
    try:
        d = dat.read_bytes()
    except OSError:
        return []
    enc = _sniff_encoding(d)
    if enc.startswith("utf-16"):
        return []
    out = []
    pos = 0
    n = len(d)
    while pos < n:
        nl = d.find(b"\n", pos)
        if nl < 0 or nl - pos > 40:
            break
        key = d[pos:nl].decode("utf-8", "replace").strip()
        p = nl + 1
        if p + 4 > n:
            break
        ln = struct.unpack_from("<I", d, p)[0]
        p += 4
        if ln > n - p:
            break
        body = d[p:p + ln]
        out.append((key.upper(), body.decode("utf-8", "replace")))
        pos = p + ln
        # entries are separated by CRLF; tolerate either
        if d[pos:pos + 2] == b"\r\n":
            pos += 2
        elif d[pos:pos + 1] in (b"\n", b"\r"):
            pos += 1
    # a full, exact walk is the only trustworthy result
    return out if out and pos >= n - 4 else []


def _key_before(d: bytes, off: int, enc: str) -> str:
    """The entry key that precedes a body at `off`."""
    start = max(0, off - 60)
    chunk = d[start:off]
    for sep in (b"\r\n", b"\n"):
        i = chunk.rfind(sep)
        if i >= 0:
            cand = chunk[i + len(sep):]
            cand = cand.strip(b"\x00")
            if cand and len(cand) <= 40:
                return cand.decode(enc, "replace")
    return ""


def _sniff_encoding(blob: bytes) -> str:
    """Detect UTF-16 in a SWORD dictionary payload."""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    head = blob[:2048]
    if head and head.count(b"\x00") > len(head) // 3:
        return "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be"
    return "utf-8"


def _pyenc(enc: str) -> str:
    e = (enc or "UTF-8").strip()
    low = e.lower()
    if low in ("utf-8", "utf8"):
        return "utf-8"
    if low in ("latin-1", "latin1", "iso-8859-1"):
        # SWORD's "Latin-1" is really cp1252.
        return "cp1252"
    if low == "utf-16":
        return "utf-16"
    return e or "utf-8"


def _chapter_title(segs: list[Seg]) -> str:
    for s in segs:
        if s.kind == "title" and s.text:
            return s.text
    return ""


def _parse_by_source(txt: str, source_type: str) -> list[Seg]:
    st = (source_type or "Plaintext").lower()
    if st == "osis":
        return markup.parse_osis(txt)
    if st in ("tei", "thml"):
        return markup.parse_teithml(txt)
    if st in ("plaintext", "gbx", ""):
        return markup.parse_plain(txt)
    return markup.parse_osis(txt)


# --------------------------------------------------------------------------
# RawLD -- uncompressed lexicon / devotional / glossary
# --------------------------------------------------------------------------

_DAY_KEY = re.compile(r"^\s*\d{1,2}\.\d{1,2}\s*$")


def read_rawld(dat: Path, *, case_insensitive: bool = True,
               strip_trailing: str = "\n\r\n") -> Iterator[tuple[str, str]]:
    """Yield (key, body) pairs from a RawLD `.dat` file.

    Two framings occur, and assuming the wrong one silently destroys content.

    **Dated (devotionals).**  Bagster's *Daily Light* is a sequence of days
    keyed `01.15`, and a day's text runs to the next day:

        01.15
        <i>Morning</i>:<br />
        <br />
                      My soul cleaveth to the dust:<br />
                  revive thou me according to thy word.<br />

    Read as "one line of body per key", the first line becomes the whole entry
    and every following line is mistaken for a new key -- the scripture
    disappears and the module looks like it installed fine.

    **One-line (general).**  Everything else is `KEY\nCONTENT\n`, with a single
    line of content, which is what the original framing assumed.

    **Heading then an HTML block (ThML).**  The Condensed Biblical Cyclopedia
    is `HEADWORD\n<ol>\n<li>...`, with the entry running until the next heading.
    Framed as one-line, every line of the body was mistaken for the next key, so
    the module installed 1,020 entries whose names were sentences from inside the
    articles -- `BIRTH . HE WAS BORN IN`, `CAIN AND ABEL ( GENESIS 4:1-7,` --
    and 434 of them had no text at all.  A heading is a short line that is not
    markup; the body is everything up to the next one.

    So: day keys first, then a body full of markup, then the single-line
    framing.
    """
    raw = dat.read_bytes()
    for enc in ("utf-8", "cp1252", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1", "replace")
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")

    # Decide the framing from the data rather than from the module's name.
    # Day keys are sparse -- 365 of them in a file of a million characters -- so
    # the test is "are there enough of them", not "are they a large share of
    # the lines".  A line that is exactly `N.N` is not something prose does.
    sample = lines[:20000]
    dayish = sum(1 for ln in sample if _DAY_KEY.match(ln))
    dated = dayish >= 20
    # A ThML body is unmistakably markup, and the one-line framing cannot
    # represent it: measure the share of lines that open a tag.
    tagged = sum(1 for ln in sample if ln.lstrip().startswith("<"))
    html_block = (not dated) and tagged >= 20

    if dated:
        buf: list[str] = []
        key = ""
        for ln in lines:
            if _DAY_KEY.match(ln):
                if key and buf:
                    yield (key.upper() if case_insensitive else key,
                           "\n".join(buf).strip())
                key = ln.strip()
                buf = []
            elif key:
                buf.append(ln)
            # Lines before the first day key are front matter and are skipped.
        if key and buf:
            yield (key.upper() if case_insensitive else key, "\n".join(buf).strip())
        return

    if html_block:
        def _is_heading(ln: str) -> bool:
            t = ln.strip()
            if not t or len(t) > 70:
                return False
            if "<" in t or ">" in t:
                return False
            letters = [c for c in t if c.isalpha()]
            # Headwords are words; a bare number or a stray symbol is not one.
            return len(letters) >= 2

        key = ""
        buf: list[str] = []
        for ln in lines:
            if _is_heading(ln):
                if key and buf:
                    yield (key.upper() if case_insensitive else key,
                           "\n".join(buf).strip())
                key = ln.strip()
                buf = []
            elif key:
                buf.append(ln)
        if key and buf:
            yield (key.upper() if case_insensitive else key, "\n".join(buf).strip())
        return

    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl < 0:
            break
        k = text[pos:nl].strip()
        pos = nl + 1
        if not k:
            continue
        nl2 = text.find("\n", pos)
        if nl2 < 0:
            nl2 = n
        body = text[pos:nl2]
        pos = nl2 + 1
        if strip_trailing and body.endswith(strip_trailing):
            body = body[: -len(strip_trailing)]
        elif body.endswith("\n"):
            body = body[:-1]
        yield (k.upper() if case_insensitive else k), body


# --------------------------------------------------------------------------
# zLD -- compressed lexicon (dict.dat / dict.idx / dict.zdt / dict.zdx)
# --------------------------------------------------------------------------

# Ranges a real lexicon legitimately uses: Greek, Hebrew, transliteration.
_SCRIPT_RANGES = ((0x0370, 0x03FF), (0x1F00, 0x1FFF), (0x0590, 0x05FF),
                  (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF), (0x0100, 0x024F))


def _plausible(samples: list[tuple[str, str]]) -> bool:
    """Does this parse look like text, or like the wrong bytes?

    A mis-sliced dictionary decodes to CJK or replacement characters rather than
    failing, and a lexicon full of mojibake is worse than one that reports it
    could not be read -- so the output is sanity-checked before it is offered.
    Greek and Hebrew count as text, obviously: this is a Greek lexicon driver.
    """
    if not samples:
        return False
    bad = 0
    for _k, body in samples[:200]:
        if not body:
            bad += 1
            continue
        head = body[:2000]
        good = 0
        for ch in head:
            if ch == "\ufffd" or (ord(ch) < 0x20 and ch not in "\t\n\r"):
                continue
            o = ord(ch)
            if ch.isascii() or any(a <= o <= b for a, b in _SCRIPT_RANGES) \
               or (0x2000 <= o < 0x2E80) or (0xA000 <= o <= 0xFFFD):
                good += 1
        if good / max(1, len(head)) < 0.8:
            bad += 1
    if bad / len(samples[:200]) >= 0.25:
        return False
    # A correctly sliced article opens with its tag; one sliced a few bytes off
    # opens mid-tag.  Reject that too rather than showing truncated definitions.
    malformed = 0
    for _k, body in samples[:200]:
        head = body.lstrip()[:1]
        if head and head not in "<ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
            malformed += 1
        elif re.match(r"^\S*(?:\"|>)[A-Za-z]", body[:24]) and \
                not body.startswith("<entry") and not body.startswith("<div"):
            malformed += 1
    return malformed / len(samples[:200]) < 0.2


# A dictionary that yields a handful of entries has not been decoded, it has
# been misread.  Webster 1913 "parsed" to four rows before this floor existed
# and installed as a stub, which is a worse failure than refusing: the user
# gets a dictionary that is silently almost empty.
_ZLD_MIN_ENTRIES = 50


def _trustworthy(pairs) -> bool:
    """Enough entries, and they look like text."""
    if not pairs or len(pairs) < _ZLD_MIN_ENTRIES:
        return False
    return _plausible(pairs)


def read_zld(base: Path) -> Iterator[tuple[str, str]]:
    """Yield (key, body) pairs from a zLD dictionary.

    A zLD dictionary is split across four files and none of them holds the text
    in a form the other files can be read without:

        dict.dat  a sequence of  KEY\r\n <uint32 block> <uint32 entry> \r\n
        dict.idx  (offset-in-block, length) pairs, one per entry
        dict.zdx  (start-in-.zdt, compressed-length) pairs, one per block
        dict.zdt  the block texts, each compressed separately

    Each decompressed block opens with a table  <count> <(offset,length) * count>
    followed by the entry texts themselves, so  block[offset:offset+length]  is
    one entry.  Reading any one file on its own yields either nothing or
    mojibake.
    """
    dat = base.with_suffix(".dat")
    idx = base.with_suffix(".idx")
    zdt = base.with_suffix(".zdt")

    zdx = base.with_suffix(".zdx")
    if zdx.exists():
        got = list(_zld_zdx(base))
        if _trustworthy(got):
            yield from got
            return
    entries = _zld_index(base)           # [(key, offset, block, length)]
    if entries:
        blocks = _zld_blocks(zdt, entries)
        if blocks is not None:
            got = _zld_bodies(entries, blocks)
            if _trustworthy(got):
                yield from got
                return
        # modules that inline the text in .dat instead
        seq = list(_read_dat_sequential(dat))
        if _trustworthy(seq):
            yield from seq
            return
    d = dat.read_bytes() if dat.exists() else b""
    if d and idx.exists():
        raw = idx.read_bytes()
        enc = _sniff_encoding(d)
        got = []
        if len(raw) % 8 == 0:
            for i in range(len(raw) // 8):
                off, ln = struct.unpack_from("<II", raw, 8 * i)
                if off + ln > len(d) or not ln:
                    continue
                key = _key_before(d, off, enc)
                if not key:
                    continue
                got.append((key.strip().upper(),
                            d[off:off + ln].decode(enc, "replace")))
        if _trustworthy(got):
            yield from got
            return
    if zdt.exists():
        got = list(_read_zld_zdt(zdt))
        if _trustworthy(got):
            yield from got
            return
    raise SwordError(
        f"{base.name}: this SWORD zLD dictionary did not parse to a plausible "
        "set of entries, so nothing was installed rather than installing a "
        "stub that would be silently almost empty. The zLD layout "
        "(StrongsGreek, BDBGlosses_Strongs, Nave, Dodson, Abbott-Smith, "
        "Webster1913 and similar) is supported, so this points at a variant "
        "this reader has not seen.")


def _zld_zdx(base: Path) -> list[tuple[str, str]]:
    """Read a zLD module that uses a .zdx block table.

    In this layout (used by StrongsGreek, BDBGlosses_Strongs, Nave, Dodson,
    Abbott-Smith, Webster1913 and the other CrossWire lexicons), the .zdt file is
    NOT one zlib stream.  It is a sequence of blocks, each compressed on its own,
    and their positions and sizes are listed in .zdx:

        .zdx  <count blocks> x (start-in-.zdt, compressed-length)
        .zdt  per block: a zlib stream; streams are back-to-back and every
              compressed block is followed by a CRLF that is *not* part of it
        .dat  <count entries> x  KEY \r\n (u32 block) (u32 entry) \r\n

    Each decompressed block opens with the same directory that the old single
    stream tried to read from the whole file:

        <u32 count> <(u32 offset, u32 length) * count> <entry texts>

    so an entry is  block[offset : offset+length].  Entry offsets are relative to
    the start of their own decompressed block, and the block number and entry
    number come from .dat, not from the .idx file.
    """
    dat = base.with_suffix(".dat")
    zdx = base.with_suffix(".zdx")
    zdt = base.with_suffix(".zdt")
    try:
        zdx_bytes = zdx.read_bytes()
        zdt_bytes = zdt.read_bytes()
        d = dat.read_bytes()
    except OSError:
        raise SwordError(
            f"{base.name}: this SWORD zLD dictionary is missing .dat, .zdx or "
            ".zdt, so nothing was installed")
    # Blocks are either rounded up to a common stride or packed with a CRLF
    # between them; the .zdx sizes are exact for every entry found so far, and
    # decompressing byte-for-byte with an exact sizes array is the one layout
    # that works for all of them.  The CRLF that follows each compressed block
    # on disk is excluded by the .zdx length and must not be fed to zlib.
    nblocks = len(zdx_bytes) // 8
    if not nblocks:
        raise SwordError(
            f"{base.name}: this SWORD zLD dictionary has an empty .zdx, so "
            "nothing was installed")
    try:
        blocks = [zlib.decompress(zdt_bytes[o:o + ln])
                  for o, ln in (struct.unpack_from("<II", zdx_bytes, 8 * i)
                                for i in range(nblocks))]
    except zlib.error:
        raise SwordError(
            f"{base.name}: this SWORD zLD dictionary could not be decompressed, "
            "so nothing was installed")
    # Walk .dat:  KEY \r\n  u32 block  u32 entry  \r\n  ...  KEY \r\n  ...
    out: list[tuple[str, str]] = []
    pos = 0
    n = len(d)
    while pos < n and len(out) < 10 ** 9:
        nl = d.find(b"\r\n", pos)
        if nl < 0:
            nl = d.find(b"\n", pos)
        if nl < 0 or nl - pos > 40:
            break
        key = d[pos:nl].decode("utf-8", "replace")
        p = nl + 2 if d[nl:nl + 2] == b"\r\n" else nl + 1
        if p + 8 > n:
            break
        blk, entry = struct.unpack_from("<II", d, p)
        p += 8
        if p <= n and d[p:p + 2] == b"\r\n":
            p += 2
        elif p < n and d[p:p + 1] in (b"\r", b"\n"):
            p += 1
        if blk >= len(blocks):
            break
        block = blocks[blk]
        if len(block) < 4:
            break
        count = struct.unpack_from("<I", block, 0)[0]
        if entry >= count:
            break
        off, ln = struct.unpack_from("<II", block, 4 + 8 * entry)
        if off + ln > len(block):
            break
        body = block[off:off + ln]
        if key:
            out.append((key.upper(), body.decode("utf-8", "replace").rstrip("\x00")))
        pos = p
    # Some modules (e.g. Abbott-Smith with Strong's) link a numeric or
    # transliterated key to the headword's article with a SWORD @LINK body, and
    # every entry is NUL-terminated.  Resolve the alias to the real article so
    # the key reads like a dictionary article instead of "@LINK ἀνάχυσις", and
    # drop a dangling link rather than install a stub entry.
    by_key: dict[str, str] = {}
    for k, b in out:
        by_key.setdefault(k, b)
    resolved: list[tuple[str, str]] = []
    for k, b in out:
        m = re.match(r"^@LINK[ \t]*(\S.*?)\s*$", b, re.S)
        if m:
            real = by_key.get(m.group(1).upper()) or by_key.get(m.group(1))
            if real is None:
                continue
            b = real
        resolved.append((k, b))
    return resolved


def _zld_index(base: Path):
    """[(key, offset-in-block, block-number, length)] from .dat + .idx."""
    dat = base.with_suffix(".dat")
    if not dat.exists():
        return []
    try:
        d = dat.read_bytes()
    except OSError:
        return []
    # .idx holds (offset-in-block, length) pairs; .dat holds the key and the
    # BLOCK number.  The offset is not repeated in .dat -- its first uint32 is
    # always zero -- so it has to come from .idx or every entry in a block
    # collapses onto offset 0.
    pairs: list[tuple[int, int]] = []
    idx = base.with_suffix(".idx")
    if idx.exists():
        raw = idx.read_bytes()
        if len(raw) % 8 == 0 and len(raw):
            pairs = [struct.unpack_from("<II", raw, 8 * i)
                     for i in range(len(raw) // 8)]
    out: list[tuple[str, int, int, int]] = []
    pos = 0
    n = len(d)
    i = 0
    while pos < n and i < (len(pairs) or 10 ** 9):
        nl = d.find(b"\n", pos)
        if nl < 0 or nl - pos > 40:
            break
        key = d[pos:nl].decode("utf-8", "replace").strip()
        p = nl + 1
        if p + 8 > n:
            break
        _a, blk = struct.unpack_from("<II", d, p)
        p += 8
        while p < n and d[p:p + 1] in (b"\r", b"\n"):
            p += 1
        off, ln = pairs[i] if i < len(pairs) else (0, 0)
        if key:
            out.append((key, off, blk, ln))
        pos = p
        i += 1
    return out


def _zld_bodies(entries, blocks) -> list[tuple[str, str]]:
    """Slice each block into entries.

    The length in .idx is the length of the entry's *opening tag*, not of its
    body, so an entry runs from its own offset to the next entry in the same
    block.  Using the length directly truncates every article to `<entryFree`.
    """
    by_block: dict[int, list[tuple[int, int, str]]] = {}
    for i, (key, off, blk, _ln) in enumerate(entries):
        by_block.setdefault(blk, []).append((off, i, key))
    out: dict[int, str] = {}
    for blk, items in by_block.items():
        if blk >= len(blocks):
            continue
        text = blocks[blk]
        if isinstance(text, str):
            text = text.encode("utf-8", "surrogateescape")
        items.sort()
        for j, (off, i, key) in enumerate(items):
            end = items[j + 1][0] if j + 1 < len(items) else len(text)
            body = text[off:end]
            body = bytes(body).rstrip(b"\r\n \t")
            if body:
                out[i] = (key.upper(), body.decode("utf-8", "replace"))
    return [out[i] for i in sorted(out)]


def _zld_blocks(zdt: Path, entries):
    """Slice the decompressed .zdt into per-block texts.

    The stream opens with a uint32 table of (size, cumulative-end) pairs, so the
    values at ODD indices are the block *start* offsets and the text does not
    begin at byte zero.  Entry offsets are relative to the start of their own
    block, so the two tables have to be combined rather than assumed to agree.
    """
    if not zdt.exists():
        return None
    try:
        data = zlib.decompress(zdt.read_bytes())
    except zlib.error:
        return None
    if len(data) < 16:
        return None
    u32 = struct.unpack_from(f"<{len(data) // 4}I", data, 0)
    starts = [v for i, v in enumerate(u32) if i % 2 == 1 and 0 < v < len(data)]
    if not starts:
        return None
    nblocks = max((b for _k, _o, b, _l in entries), default=0) + 1
    if len(starts) < nblocks:
        return None
    out = []
    for i in range(nblocks):
        s = starts[i]
        e = starts[i + 1] if i + 1 < len(starts) else len(data)
        if e <= s or e > len(data):
            return None
        out.append(data[s:e])
    return out


_ENTRY_RE = re.compile(rb"<entryFree\b[^>]*>(.*?)(?=<entryFree|\Z)", re.S)
_TERM_RE = re.compile(rb"<term\b[^>]*>(.*?)</term>", re.S)


def _read_zld_zdt(zdt: Path) -> Iterator[tuple[str, str]]:
    """Decompressed .zdt: a uint32 boundary table, then the entry blocks.

    The table is a flat array of uint32 pairs written as (size, cumulativeEnd),
    so the values at ODD indices are the block end offsets and the text begins at
    the first of them -- not at byte zero.  Slicing from 0 reads the table as if
    it were a dictionary, which is why a naive parse returns mojibake.
    """
    try:
        data = zlib.decompress(zdt.read_bytes())
    except zlib.error:
        data = zdt.read_bytes()
    if len(data) < 16:
        return
    u32 = struct.unpack_from(f"<{len(data) // 4}I", data, 0)
    ends = [v for i, v in enumerate(u32) if i % 2 == 1 and 0 < v < len(data)]
    if not ends:
        return
    bounds = ends[1:] + [len(data)]
    for start, end in zip(ends, bounds):
        if end <= start:
            continue
        blob = data[start:end]
        for m in _ENTRY_RE.finditer(blob):
            body = m.group(1)
            tm = _TERM_RE.search(body)
            head = (tm.group(1) if tm else b"")
            key = re.sub(rb"<[^>]+>", b"", head).decode("utf-8", "replace").strip()
            if not key:
                continue
            yield (key.upper(), body.decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# Discovering a SWORD module in a zip
# --------------------------------------------------------------------------

_DRIVE_BASE = {
    "rawtext": "modules/texts/rawtext",
    "ztext": "modules/texts/ztext",
    "rawcom": "modules/comments/rawcom",
    "rawcom4": "modules/comments/rawcom4",
    "zcom": "modules/comments/zcom",
    "zcom4": "modules/comments/zcom4",
    "hrefcom": "modules/comments/hrefcom",
    "rawfiles": "modules/comments/rawfiles",
    "rawld": "modules/lexdict/rawld",
    "rawld4": "modules/lexdict/rawld4",
    "zld": "modules/lexdict/zld",
    "zld4": "modules/lexdict/zld4",
    "rawgenbook": "modules/genbook/rawgenbook",
    "rawgenbook2": "modules/genbook/rawgenbook2",
}


# A bare reference on its own line opens a note in a RawCom file.  The book is
# optional: some modules write "John 3:16", others just "3:16" inside a file
# that is one book.
_RAWCOM_REF = re.compile(
    r"^\s*(?:([1-3]?[A-Za-z][A-Za-z.]{0,14})\s+)?(\d{1,3}):(\d{1,3})\s*$")
# A second, very common RawCom style, used by the German commentaries:
#     <h4><b><font ...>Text: Johannes 3,1-21</font></b></h4>
# The book name can carry umlauts and be longer than an English abbreviation,
# and the verses are comma-separated rather than colon-separated.  Without this
# a 1.7 MB commentary parsed to three units.
_RAWCOM_REF2 = re.compile(
    r"(?:^|>)\s*(?:Text|Verse|Textstelle)?\s*:?\s*"
    r"([1-3]?[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß.\-]{0,24})\s+"
    r"(\d{1,3})\s*[,;]\s*(\d{1,3})",
    re.I)
# A third RawCom style, used by Matthias Ansorg's German commentary: the note
# opens with a "Datum:"/"Stelle:" banner and the reference is the `passage`
# attribute of a <scripRef> on that line, not the visible text.
#     <B>Stelle:</B> <scripRef passage="I Kings 2:1-I Kings 2:6;">1. K&ouml;nige 2:1-6</scripRef>
# `passage` is the canonical OSIS reference, so it is the better key.  Without
# this, 750 notes collapse into about a dozen multi-hundred-thousand-character
# units and the commentary cannot be opened by reference at all.
_RAWCOM_STELLE = re.compile(
    r"(?:Stelle|Textstelle|Verse)\s*:\s*(?:(?!</FONT>).)*?"
    r"""<scripRef[^>]*?\bpassage=["']([^"']+)["']""",
    re.I | re.S)
_RAWCOM_RULE = re.compile(r"^[$\-=\s]{3,}$")


# A RawGenBook `.bdt` is an OSIS document whose sections are delimited by
# top-level <title> elements.  Subtitles and author lines carry type="x-..."
# and belong to the section above them, not to a new one.
_GENBOOK_TITLE = re.compile(
    r"<title(?![^>]*\btype=[\"']x-)(?![^>]*\btype=[\"']psalm)[^>]*>"
    r"(.*?)</title>", re.I | re.S)
_GENBOOK_ANY_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
# Some RawGenBook files are HTML rather than OSIS and carry no <title> at all:
# Calvin's Institutes and Josephus use <h1>..<h4> instead.  Splitting on the
# deepest heading level present turns their chapters into units; without this
# the splitter finds no titles, returns nothing, and the caller falls through to
# re-reading the driver's .dat bookmark index as if it were text.
_GENBOOK_HEADING = {
    n: re.compile(rf"<\s*h{n}(?![^>]*\btype=[\"']x-)[^>]*>(.*?)<\s*/\s*h{n}\s*>",
                  re.I | re.S)
    for n in (1, 2, 3, 4)
}


def split_genbook_sections(text: str) -> list[tuple[str, str]]:
    """Split a RawGenBook `.bdt` into (title, body) sections.

    Returns an empty list when the document has no section titles, so the
    caller can fall back rather than emit one giant unreadable unit.
    """
    heads = [(m.start(), m.end(), m.group(1)) for m in _GENBOOK_TITLE.finditer(text)]
    if not heads:
        # No <title> elements: try the HTML heading that appears most often, so
        # the smallest real division (a chapter) becomes the unit rather than a
        # whole book.
        best = None
        for _n, rx in _GENBOOK_HEADING.items():
            found = [(m.start(), m.end(), m.group(1)) for m in rx.finditer(text)]
            if len(found) > 1 and (best is None or len(found) > len(best[1])):
                best = (_n, found)
        heads = best[1] if best else []
    if not heads:
        return []
    out: list[tuple[str, str]] = []
    if heads[0][0] > 0:
        pre = text[:heads[0][0]].strip()
        if pre:
            out.append(("", pre))
    for i, (start, end, title) in enumerate(heads):
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        body = text[end:stop].strip()
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
        out.append((name[:120], body))
    return [(t, b) for t, b in out if b]


def split_rawcom_notes(text: str) -> list[tuple[str, str]]:
    """Split a RawCom file into (key, body) notes.

    Returns a single-element list when the file has no recognisable notes, so
    the caller can fall back to installing the file whole.
    """
    lines = text.split("\n")
    out: list[tuple[str, str]] = []
    key = ""
    buf: list[str] = []
    seen_book = ""

    def flush():
        nonlocal buf
        body = "\n".join(buf).strip()
        buf = []
        if key and body:
            out.append((key, body))

    i = 0
    while i < len(lines):
        ln = lines[i]
        stelle = _RAWCOM_STELLE.search(ln)
        if stelle:
            # The passage attribute ends in the semicolon that separates it from
            # the next attribute ("I Kings 2:1-I Kings 2:6;"), which is not part
            # of the reference.
            passage = stelle.group(1).strip().rstrip(";,")
            if passage and (buf or not key):
                flush()
                key = passage
                buf = []
                i += 1
                continue
        m = _RAWCOM_REF.match(ln)
        m2 = None if m else _RAWCOM_REF2.search(ln)
        hit = m or m2
        if hit and (buf or not key):
            book, ch, vs = hit.group(1), hit.group(2), hit.group(3)
            if book:
                seen_book = book
            flush()
            key = f"{seen_book} {ch}:{vs}" if seen_book else f"{ch}:{vs}"
            buf = []
        elif _RAWCOM_RULE.match(ln) and not ln.strip("$"):
            # a rule closes the previous group
            flush()
            key = ""
            i += 1
            continue
        else:
            buf.append(ln)
        i += 1
    flush()
    return out


def canonicalise_note_key(key: str) -> str:
    """Rewrite a note key's book name to an OSIS id when we recognise it.

    "Apostelgeschichte 1:1" -> "Acts 1:1".  An unrecognised name is left alone:
    the note stays readable and searchable under its own label rather than
    being dropped for want of a mapping.
    """
    head, sep, tail = (key or "").rpartition(" ")
    if not sep:
        return key
    osis = _canonical_book(head)
    return f"{osis} {tail}" if osis else key


def split_note_key(key: str) -> tuple[str, int, int]:
    """("John 3:16", "1Cor.11.31", "1:11") -> (osis, chapter, verse).

    Anything that is not a book plus chapter and verse returns empty, and the
    caller leaves the unit unanchored rather than guessing.
    """
    k = (key or "").strip()
    if not k:
        return "", 0, 0
    if "." in k and k.count(".") >= 2:
        parts = k.split(".")
        book = canon.BOOK_BY_OSIS.get(parts[0])
        try:
            return (book.osis if book else ""), int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            return "", 0, 0
    head, sep, tail = k.rpartition(" ")
    if not sep or ":" not in tail:
        return "", 0, 0
    osis = _canonical_book(head)
    ch, _, vs = tail.partition(":")
    try:
        return osis, int(ch), int(vs)
    except ValueError:
        return osis, 0, 0


def _canonical_book(name: str) -> str:
    """Resolve a book name to an OSIS id, or return "" if it is not one we know."""
    n = (name or "").strip().rstrip(".")
    if not n:
        return ""
    b = canon.BOOK_BY_NAME.get(n.lower())
    if b is not None:
        return b.osis
    b = canon.BOOK_BY_NAME.get(n.lower().replace(".", ""))
    return b.osis if b is not None else ""


def find_conf(zf) -> str:
    for n in zf.namelist():
        if n.startswith("mods.d/") and n.endswith(".conf"):
            return n
    for n in zf.namelist():
        if n.endswith(".conf") and "mods" in n:
            return n
    raise SwordError("no mods.d/*.conf in package")


def data_prefix(zf, conf: Conf) -> str:
    """The directory that holds a module's data files.

    Note the RawLD / RawLD4 / zLD / zLD4 convention: their DataPath has NO
    trailing slash and its last component is a *file base name*, not a
    directory (".../zld/strongsgreek/dict" for dict.dat/dict.idx).  Appending a
    slash there -- which is correct for the text drivers -- makes every lexicon
    in the SWORD repository unreadable.
    """
    dp = conf.get("DataPath", "").strip().replace("\\", "/")
    if not dp:
        return ""
    if dp.startswith("./"):
        dp = dp[2:]
    if dp.endswith("/"):
        return dp
    drv = (conf.get("ModDrv") or "").strip()
    if drv in ("RawLD", "RawLD4", "zLD", "zLD4", "RawGenBook", "RawGenBook2"):
        return dp[: dp.rfind("/") + 1]        # directory only
    return dp + "/"


def list_entries(zf, prefix: str, suffixes: tuple[str, ...]) -> list[str]:
    out = []
    for n in zf.namelist():
        if not n.startswith(prefix):
            continue
        if n.lower().endswith(suffixes):
            out.append(n)
    return sorted(out)
