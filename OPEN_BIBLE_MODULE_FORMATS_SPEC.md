# Open-Source Bible Module File Formats — Technical Specification for Importer Authors

Research date: 2026-09-26. Every HTTP claim below was verified with a real GET
(`urllib.request` + browser `User-Agent`). Status codes are inline. Sample modules,
dump scripts and downloaded files are in `/tmp/opencode/bible-research/`.

## Read this first — the three facts that will save you the most time

1. **In a CrossWire SWORD `zText`/`zCom` module, verse boundaries are NOT in the markup.**
   The `<verse>` elements are stripped by the importer; boundaries come *only* from the
   binary `.bzv` index. Verified: CrossWire `KJV.zip` and eBible `engweb2025eb.zip` both
   contain **zero** `<verse>` elements. Do not regex for verses in SWORD modules.
2. **eBible.org no longer publishes `catalog.json`, `collection.json`, `manifest.xml`, or
   `eBible-manifest.xml`.** Every one of those URLs 404s and the Wayback Machine has *zero*
   snapshots of any of them. What eBible *does* publish is in §2.
3. **e-Sword >= 9 is plain SQLite.** e-Sword <= 8 is `.bbl`/`.cmt`/`.dct`/`.dev` + `.mod` +
   `.bzs`/`.bzv`/`.bzz` (same container family as SWORD zText). The `.bzu` container could
   **not** be verified by download — see §3.6 for exactly what is and is not proven.

## Contents

1. [CrossWire SWORD](#1-crosswire-sword)
2. [eBible.org](#2-ebibleorg)
3. [e-Sword](#3-e-sword)
4. [MySword / MyBible](#4-mysword--mybible)
5. [Door43 / unfoldingWord](#5-door43--unfoldingword)
6. [BibleTime / Zefania XML](#6-bibletime--zefania-xml)
7. [Plain text, CSV, TSV, PDF](#7-plain-text-csv-tsv-pdf)
8. [Consolidated verified URL table](#8-consolidated-verified-url-table)

---

# 1. CrossWire SWORD

## 1.1 Package structure (verified by unzipping real modules)

A SWORD "package" is a **plain zip** whose entries mirror the on-disk SWORD module tree,
rooted at the SWORD module library root. Exactly two kinds of entry:

```
mods.d/<lowercased-modname>.conf        # the manifest
modules/<type>/<driver>/<modname>/...    # the data
```

Verified contents of `KJV.zip` (4,026,621 bytes, HTTP 200):

```
     6313  mods.d/kjv.conf
      336  modules/texts/ztext/kjv/nt.bzs
    82460  modules/texts/ztext/kjv/nt.bzv
  1748682  modules/texts/ztext/kjv/nt.bzz
      480  modules/texts/ztext/kjv/ot.bzs
    241150  modules/texts/ztext/kjv/ot.bzv
  2159539  modules/texts/ztext/kjv/ot.bzz
```

`Barnes.zip` (commentary) uses the **`c`** prefix instead of `b`:

```
       437  mods.d/barnes.conf
      3120  modules/comments/zcom/barnes/nt.czs
     82460  modules/comments/zcom/barnes/nt.czv
   6018995  modules/comments/zcom/barnes/nt.czz
```

`2BabDict.zip` (RawLD dictionary) and `StrongsGreek.zip` (zLD dictionary):

```
       360  mods.d/2babdict.conf
     37736  modules/lexdict/rawld/2babdict/2babdict.dat
      1590  modules/lexdict/rawld/2babdict/2babdict.idx
      1593  mods.d/strongsgreek.conf
     97688  modules/lexdict/zld/strongsgreek/dict.dat
     45936  modules/lexdict/zld/strongsgreek/dict.idx
    718266  modules/lexdict/zld/strongsgreek/dict.zdt
      1536  modules/lexdict/zld/strongsgreek/dict.zdx
```

### Canonical `DataPath` values (CrossWire wiki, verbatim)

| ModDrv | Recommended `DataPath` |
|---|---|
| `RawText` / `RawText4` | `./modules/texts/rawtext/mymodule/` |
| `zText` / `zText4` | `./modules/texts/ztext/mymodule/` |
| `RawCom` / `RawCom4` | `./modules/comments/rawcom/mymodule/` , `./modules/comments/rawcom4/mymodule/` |
| `zCom` / `zCom4` | `./modules/comments/zcom/mymodule/` , `./modules/comments/zcom4/mymodule/` |
| `HREFCom` | `./modules/comments/hrefcom/mymodule/` |
| `RawFiles` | `./modules/comments/rawfiles/mymodule/` |
| `RawLD` / `RawLD4` | `./modules/lexdict/rawld/mymodule/mymodule` (no trailing slash) |
| `RawLD` devotional | `./modules/lexdict/rawld/devotionals/mymodule/mymodule` |
| `RawLD` glossary | `./modules/lexdict/rawld/glossaries/mymodule/mymodule` |
| `zLD` | `./modules/lexdict/zld/mymodule/mymodule` |
| `RawGenBook` | `./modules/genbook/rawgenbook/mymodule/mymodule` |

Lexicon/dictionary `DataPath` has **no trailing slash** — the last path component is both
the directory and the filename prefix.

### `RawGenBook` / `RawGenBook2` — two shapes

The `.bdt` is a single document, and how it is divided into articles depends on the module.

* **OSIS shape.** Sections are delimited by top-level `<title>` elements (`Didache` 17,
  `Westminster` 341, `Imitation` 356).  A `<title>` carrying `type="x-..."` is a subtitle and
  belongs to the section above it, not a new one.
* **HTML shape.** Some modules use `<h1>`..`<h4>` and have **no `<title>` at all**:
  `Institutes` (Calvin) has 7 `<h1>`, 17 `<h2>`, 106 `<h3>`; `Josephus` has 19 `<h3>` and no
  `<title>`.  Split on the heading level that appears most often, so a *chapter* rather than a
  whole book becomes the unit.  The body is then HTML-flavoured (`<p>`, 3,605 `<scripref>`
  in Institutes) even though the conf does not say `SourceType=OSIS`, so it must go through the
  OSIS/HTML parser rather than a plain-text one.

The `.dat` / `.idx` beside a `.bdt` are the driver's own *bookmark* index, not a lexicon: a
RawGenBook whose `.bdt` yields no sections must not be read as if `.dat` were text, because
that produces a few units of binary noise.  The first real `.dat` here was 20,050 bytes for
4 bookmarks against a 4.1 MB document — the giveaway.

## 1.2 The `.conf` file — INI format

UTF-8 INI. Single `[ModName]` section, must be the first line. `ModName` and `Abbreviation`
are restricted to PCRE class `[A-Za-z0-9_]`. Filename convention `lowercase(ModName).conf`.
Key order is immaterial. `#`/`##` start a comment; blank lines allowed (since 2021).
Max line length 1024 chars. A trailing `\` continues the value onto the next line; this is a
*rendering* feature (acts like `<br/>`), not line wrapping. Localization: append `_` +
BCP-47 locale to any localizable key (`Description_fr=`, `Description_pt-BR=`,
`Description_zh-Hans=`). A localized form is only honoured if the unlocalized form also exists.

### Required

| Key | Values | Notes |
|---|---|---|
| `[ModName]` | `[A-Za-z0-9_]+` | first line, unique |
| `Abbreviation` | `[A-Za-z0-9_]+` | optional; defaults to ModName |
| `Description` | string, 1 line | user-visible title |
| `DataPath` | rel. path starting `./modules` | a directory must end `/` |
| `ModDrv` | `RawText` `RawText4` `zText` `zText4` `RawCom` `RawCom4` `zCom` `zCom4` `HREFCom` `RawFiles` `RawLD` `RawLD4` `zLD` `RawGenBook` | case-sensitive |
| `SourceType` | `Plaintext` `OSIS` `TEI` (+ legacy `GBF` `ThML`) | default `Plaintext` |
| `Encoding` | `UTF-8` `UTF-16` `SCSU` (+ legacy `Latin-1`) | default `Latin-1`, which means **cp1252** |
| `CompressType` | `ZIP` `LZSS` `BZIP2` `XZ` | default `LZSS`; use `ZIP` |
| `BlockType` | `BOOK` `CHAPTER` `VERSE` | default `CHAPTER`; Bibles `BOOK` |
| `BlockCount` | int | zLD only; default `200` |
| `Versification` | `Calvin` `Catholic` `Catholic2` `Darby_Fr` `German` `KJV` `KJVA` `LXX` `Leningrad` `Luther` `MT` `NRSV` `NRSVA` `Orthodox` `Segond` `Synodal` `SynodalProt` `Vulg` | default `KJV` |
| `CipherKey` | string; empty value means locked | encrypted modules |
| `KeyType` | `TreeKey` `VerseKey` | RawGenBook; default `TreeKey` |
| `CaseSensitiveKeys` | `true` | suppress UPPERCASE normalisation |

### Rendering / features

| Key | Values |
|---|---|
| `GlobalOptionFilter` | `UTF8Cantillation` `UTF8GreekAccents` `UTF8HebrewPoints` `UTF8ArabicPoints` `OSISLemma` `OSISMorphSegmentation` `OSISStrongs` `OSISFootnotes` `OSISScripref` `OSISMorph` `OSISHeadings` `OSISVariants` `OSISRedLetterWords` `OSISGlosses` `OSISXlit` `OSISEnum` `OSISReferenceLinks` `OSISRuby`(deprecated), plus legacy `GBFStrongs` `GBFFootnotes` `GBFMorph` `GBFHeadings` `GBFRedLetterWords` `ThMLStrongs` `ThMLFootnotes` `ThMLScripref` `ThMLMorph` `ThMLHeadings` `ThMLVariants` `ThMLLemma`. Repeats. **Applied in listed order** — `OSISLemma` must precede `OSISStrongs`. |
| `Direction` | `LtoR` `RtoL` `BiDi` — default `LtoR` |
| `DisplayLevel` | int — default 1 (GenBook) |
| `Font` | string |
| `OSISqToTick` | `true`/`false` — **deprecated**; use `marker=""` on `<q>` |
| `Feature` | `StrongsNumbers` `GreekDef` `HebrewDef` `GreekParse` `HebrewParse` `DailyDevotion` `Glossary` `Images` `NoParagraphs`. Repeats. |
| `GlossaryFrom` / `GlossaryTo` | language identifier |
| `PreferredCSSXHTML` | filename inside `DataPath` |
| `LocalStripFilter` | search-time text stripper name (e.g. `GBFPlain`) |
| `CaseInsensitiveKeys` | `true`/`false` — LexDict only |
| `StrongsPadding` | `true`/`false` — LexDict only; default `true` |
| `LangSortOrder` | e.g. `AaBbCcDdEe...` — xulsword only |

### Informational / installer

`About`, `SwordVersionDate` (ISO `yyyy-mm-dd`), `Version` (numeric, e.g. `3.1` or `617.0`),
`History_<x.x>` (repeats; key equals the version), `MinimumVersion` (default `1.5.1a`),
`Category`, `LCSH`, `Lang`, `InstallSize` (bytes), `Obsoletes` (repeats, ModName),
`OSISVersion` (current `2.1.1`), `Companion` (`ModName[, ModName]`).

`Category` enumerated values: `Biblical Texts`, `Commentaries`, `Lexicons / Dictionaries`,
`Glossaries`, `Daily Devotional`, `Generic Books`, `Maps`, `Images`,
`Cults / Unorthodox / Questionable Material`, `Essays`.

`Lang` is BCP-47, regex `^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$` — e.g. `en`, `sr-Latn`,
`en-GB`, `zh-Hant`.

### Copyright / licensing (exact enumerated strings — use verbatim)

`Copyright`, `CopyrightHolder`, `CopyrightDate` (ISO year), `CopyrightNotes`,
`CopyrightContactName`, `CopyrightContactNotes`, `CopyrightContactAddress`,
`CopyrightContactEmail`, `ShortPromo`, `ShortCopyright`, `DistributionNotes`, `TextSource`,
`UnlockInfo`.

`DistributionLicense` must be exactly one of:

```
Public Domain
Copyrighted
Copyrighted; Permission to distribute granted to CrossWire
Copyrighted; Permission granted to distribute non-commercially in SWORD format
Copyrighted; Free non-commercial distribution
Copyrighted; Freely distributable
GFDL
GPL
Creative Commons: BY-NC-ND 4.0
Creative Commons: BY-NC-SA 4.0
Creative Commons: BY-NC 4.0
Creative Commons: BY-ND 4.0
Creative Commons: BY-SA 4.0
Creative Commons: BY 4.0
Creative Commons: CC0
```

### RTF subset allowed in conf values

Only `\qc` (centre), `\par`, `\pard`, and `\uNNNN?` (signed 16-bit; add 65536 if negative).
Prefer raw UTF-8 over `\uNNNN`. Always put a space before a URL if the previous token ends
in one.

### Real `.conf` (verbatim, `mods.d/kjv.conf` from `KJV.zip`, abridged in the middle only)

```ini
## Sword module configuration file

## Required elements
# Module Unique Identifier.
[KJV]

# Short description of the module.
Description=King James Version (1769) with Strongs Numbers and Morphology  and CatchWords

# Path to the module data files relative to the SWORD module library root directory.
DataPath=./modules/texts/ztext/kjv/

# Driver used for reading the module.
ModDrv=zText

## Required elements with defaults
# Markup used in the module.
SourceType=OSIS

# How the text in the conf and in the module are encoded.
Encoding=UTF-8

# Compression algorithm.
CompressType=ZIP

# How much of the work is compressed into a block.
BlockType=BOOK

# Versification employed by a Bible module.
Versification=KJV

## Elements required for proper rendering
GlobalOptionFilter=OSISFootnotes
GlobalOptionFilter=OSISHeadings
GlobalOptionFilter=OSISRedLetterWords
GlobalOptionFilter=OSISLemma
GlobalOptionFilter=OSISStrongs
GlobalOptionFilter=OSISMorph

# Module features.
Feature=NoParagraphs
Feature=StrongsNumbers

## General informatic and installer elements
About=This is the King James Version of the Holy Bible ... \par  The Strong's numbers in the OT were obtained from The Bible Foundation: http://www.bf.org. ... \par\par Inquiries and comments may be directed to:\par\par CrossWire Bible Society\par modules@crosswire.org\par http://www.crosswire.org
SwordVersionDate=2023-07-19
Version=3.1
History_1.1=Fixed .conf file GlobalOptionFilters
History_2.8=(2015-12-20) Moved Ps 119 acrostic titles before verse number. ...
History_3.1=(2023-07-19) Conf version updated to 3.1 to match KJVA version.
MinimumVersion=1.5.9
LCSH=Bible.English
Lang=en
OSISVersion=2.1.1

## Copyright and Licensing related elements
DistributionLicense=GPL
TextSource=https://gitlab.com/crosswire-bible-society/kjv
InstallSize=4232647
```

Minimal legacy-style conf (`mods.d/barnes.conf`, verbatim, complete):

```ini
[Barnes]
DataPath=./modules/comments/zcom/barnes/
ModDrv=zCom
BlockType=CHAPTER
CompressType=ZIP
Lang=en
Encoding=UTF-8
SourceType=ThML
Version=1.1
History_1.1=Made numerous (mostly formatting) corrections and replaced some omitted cross-references
Description=Barnes' New Testament Notes
About=Barnes' New Testament Notes
DistributionLicense=Public Domain
LCSH=Bible. N.T.--Commentaries.
SwordVersionDate=2002-01-01
InstallSize=6104575
```

## 1.3 `zText` / `zCom` binary layout (reverse-engineered and proven)

Three files per testament. **`b` prefix for texts, `c` prefix for commentaries**, i.e.
`ot.bzs`/`ot.bzv`/`ot.bzz` vs `ot.czs`/`ot.czv`/`ot.czz`. The suffix letters never change.
Bibles split by testament; commentaries generally have one file set (often named `nt.*`
even when covering both testaments — `Barnes` uses `nt.czs` for the whole NT).

### `.bzs` / `.czs` — block table

**A flat array of 12-byte records. `numBlocks = filesize / 12`. No header.**
All integers **little-endian uint32**, three per record:

```
struct BlockRecord {
    uint32 blockStart;        // byte offset of the compressed block inside the .bzz/.czz
    uint32 compressedSize;    // bytes occupied in the .bzz/.czz
    uint32 uncompressedSize;  // bytes after decompression
}
```

Verified: `KJV` OT `.bzs` = 480 bytes -> 40 blocks; NT = 336 -> 28 blocks. Records are
contiguous: `blocks[i].blockStart == blocks[i-1].blockStart + blocks[i-1].compressedSize`
(exact across all 40 records; final end offset 1748682 == `.bzz` size).

**Block 0 is special.** It is *not* a book. `KJV` block 0 decompresses to exactly 83 bytes:

```
<milestone type="x-importer" subType="x-osis2mod" n="$Rev: 3769 $ (SWORD: 1.9.0)"/>
```

an importer-provenance milestone at `.bzz` offset 0, compressed size 1110. Consequently
`numBlocks == nBooks + 1` for `BlockType=BOOK` modules built by `osis2mod`.

**Do NOT assume one block per book.** eBible's `engweb2025eb` OT has **64 blocks for 52
books** — the importer splits large books. Always go through `.bzs`.

### `.bzz` / `.czz` — the block data

A **concatenation of independent compression streams**, one per block, at the exact offsets
in `.bzs`. For `CompressType=ZIP` each block is an independent **zlib** stream —
`zlib.decompress(bzz[start:start+csize])` verified working, with exact uncompressed size
match (1,675,097 bytes for Matthew). Alternatives: `LZSS` (Lempel-Ziv-Storer-Szymanski,
SWORD native, no public codec), `BZIP2`, `XZ`.

### `.bzv` / `.czv` — the verse index

**A flat array of 10-byte records. `numEntries = filesize / 10`. No header.**
All integers **little-endian**:

```
struct VerseRecord {          // 10 bytes
    uint32 blockNumber;       // index into the .bzs block table
    uint32 verseStart;        // byte offset within the DECOMPRESSED block
    uint16 verseLength;       // byte length within the DECOMPRESSED block
}
```

Verified counts: `KJV` OT 241,150 / 10 = 24,115 entries; NT 82,460 / 10 = 8,246.
`Barnes` NT `.czv` is also 82,460 bytes (same `Versification=KJV`, 8,246 entries).
JSword's `ZVerseBackend.java` documents the same two-index model and notes entry size may be
6 or 8 for other block types — but 10 bytes is what `BlockType=BOOK|CHAPTER` modules in the
wild use. Always validate `filesize % 10 == 0` and fall back to a linear scan of the block
text otherwise.

### The verse-ordinal model (this is the crux)

```
numEntries = 2 + nBooks + sum_over_chapters(1 + nVerses)
```

The index contains, in order:

* **2 dummy leading records** — index 0 is `{block 0, start 0, len 0}` (empty); index 1 is
  the `<milestone type="x-importer" .../>` block;
* **one record per book** — holds the `<div type="book">` and `<title type="main">` header
  (SWORD's book-0 / chapter-0 / verse-0 pseudo-verse);
* **one record per chapter** — holds the `<chapter osisID="X.Y">` element and
  `<title type="chapter">` (the verse-0 pseudo-verse);
* **one record per verse** — holds that verse's markup.

**Arithmetically proven on real data:**

| Module | Testament | `.bzv` entries | books | chapters | verses | `2+b+c+v` |
|---|---|---|---|---|---|---|
| `KJV` (`Versification=KJV`) | OT | 24,115 | 39 | 929 | 23,145 | **24,115** OK |
| `KJV` | NT | 8,246 | 27 | 260 | 7,957 | **8,246** OK |
| `engweb2025eb` (`Versification=NRSVA` + Apocrypha) | NT | 8,248 | 27 | 260 | 7,959 | **8,248** OK |
| `engweb2025eb` | OT | 31,027 | 52 | 1,118 | 29,855 | **31,027** OK |

So: **`bzvIndex = 2 + bookHeaderIndex + (chapters before this one) + (verse - 1)`** — two
pseudo-ordinals (`book.0.0` and `book.chapter.0`) exist between every pair of real verses.

Empirically confirmed offsets in `KJV` OT (block 1):

```
ord 0   blk=0  len=0     (empty)
ord 1   blk=0  len=83    <milestone type="x-importer" subType="x-osis2mod" n="$Rev: 3769 $ (SWORD: 1.9.0)"/>
ord 2   blk=1  len=195   <div type="bookGroup"/> <div osisID="Gen" type="book"/> <title type="main">THE FIRST BOOK OF MOSES CALLED GENESIS</title>
ord 3   blk=1  len=105   <chapter chapterTitle="CHAPTER 1." osisID="Gen.1" sID="gen30"/> <title type="chapter">CHAPTER 1.</title>
ord 4   blk=1  len=265   <w lemma="strong:H07225">In the beginning</w> ...            <- Gen 1:1
ord 5   blk=1  len=609   ...                                                          <- Gen 1:2
ord 35  blk=1  len=105   <chapter osisID="Gen.2" .../>                                 <- Gen 2:0
ord 36  blk=1  len=213   <w lemma="strong:H08064">Thus the heavens</w> ...              <- Gen 2:1
```

**Practical advice:** the ordinal arithmetic depends on the conf's `Versification`, so do
one of these rather than hardcoding a v11n table:

* **(a)** parse the block text and align on the `<chapter osisID="Book.Ch">` and
  `<div osisID="Book" type="book">` markers you actually find. They are present in every
  CrossWire/eBible SWORD module tested. Note each `<chapter>` marker appears **twice** in
  the block stream (once closing the preceding chapter, once opening this one), so dedupe
  on `osisID`.
* **(b)** use a v11n table (JSword's `BibleBook`, or pysword's `books.py`) and calibrate the
  constant offset against the module's first chapter.
* **(c)** read book/chapter/verse numbers out of OSIS `sID` / `osisRef` attributes that
  appear inside `<note>`, `<reference>`, `<lg>` etc. within the block.

### Reference algorithm (this is what actually ran successfully)

```python
import struct, zlib
blocks = [struct.unpack('<III', bzs[12*i:12*i+12]) for i in range(len(bzs)//12)]
blk, start, ln = struct.unpack('<IIH', bzv[10*i:10*i+10])
s, c, u = blocks[blk]
raw = zlib.decompress(bzz[s:s+c])          # cache per block
verse_bytes = raw[start:start+ln]          # UTF-8
```

## 1.4 Text encoding in SWORD modules

* `Encoding=UTF-8` is the norm. **Text is raw UTF-8, not entity-escaped.** CrossWire modules
  do **not** use `&lt;`/`&gt;`/`&amp;` for markup (verified: `KJV` Gen 1:1 contains literal
  `<w lemma="strong:H07225">`). eBible/e-Sword/HTML-adjacent formats *do* escape.
* Non-Hebrew UTF-8 modules must be Unicode **NFC**. Biblical Hebrew must be handled
  specially — do not blindly NFC-normalise (see the SBL Hebrew Font User Manual p.9 and
  Corrigendum 5 sequences; consider inserting a Combining Grapheme Joiner).
* `Encoding=Latin-1` means **cp1252**, not ISO-8859-1. Read it with `cp1252` explicitly.
* `Encoding=UTF-16` and `SCSU` exist in the enum but no module in the wild uses them.

## 1.5 Book / chapter detection in SWORD

Structural (preferred, `.bzv`-driven) as in §1.3. Markup-based fallbacks in order of
reliability:

* `<div ... osisID="Gen" sID="gen29" type="book"/>` — book boundary (`sID` values are
  `genNNN` in osis2mod output and carry no cross-module meaning).
* `<div ... type="bookGroup"/>` — testament boundary (`subType="x-OT"` / `"x-NT"`).
* `<chapter chapterTitle="CHAPTER 1." osisID="Gen.1" sID="gen30"/>` — chapter boundary.
  The attribute set varies: CrossWire `KJV` uses `chapterTitle`; eBible's Haiola output uses
  `<chapter n="1" osisID="Gen.1" sID="Gen.1.seID.00001"/>`.
* `<title type="main">` / `<title type="chapter">` — the header text.
* `<milestone marker="P" type="x-p"/>` — paragraph break (CrossWire renders this as a pilcrow).
* `<transChange type="added">` (italic supplied words), `type="alternate"` (variants).
* `<q who="Jesus">` — words of Christ (with `OSISqToTick=false` and `marker=""` to suppress
  the quotation mark).
* `<divineName>Lord</divineName>`, `<foreign>`, `<seg>`,
  `<w lemma="strong:H0430" morph="strongMorph:TH8804">`.

### Real OSIS samples (verbatim, so you can regex-test against them)

CrossWire `KJV`, `ot.bzz` block 1, records 2-4:

```xml
<div canonical="true" sID="gen28" subType="x-OT" type="bookGroup"/> <div canonical="true" osisID="Gen" sID="gen29" type="book"/> <title type="main">THE FIRST BOOK OF MOSES CALLED GENESIS</title>
<chapter chapterTitle="CHAPTER 1." osisID="Gen.1" sID="gen30"/> <title type="chapter">CHAPTER 1.</title>
<w lemma="strong:H07225">In the beginning</w> <w lemma="strong:H0430">God</w> <w lemma="strong:H0853 strong:H01254" morph="strongMorph:TH8804">created</w> <w lemma="strong:H08064">the heaven</w> <w lemma="strong:H0853">and</w> <w lemma="strong:H0776">the earth</w>.
<w lemma="strong:H0776">And the earth</w> <w lemma="strong:H01961" morph="strongMorph:TH8804">was</w> <w lemma="strong:H08414">without form</w> <w lemma="strong:H0922">and void</w>; <w lemma="strong:H02822">and darkness</w> <transChange type="added">was</transChange> <w lemma="strong:H06440">upon the face</w> <w lemma="strong:H08415">of the deep</w>. <w lemma="strong:H07307">And the Spirit</w> <w lemma="strong:H0430">of God</w> <w lemma="strong:H07363" morph="strongMorph:TH8764">moved</w> <w lemma="strong:H05921">upon</w> <w lemma="strong:H06440">the face</w> <w lemma="strong:H04325">of God</w>.
```

Greek with Robinson morphology (KJV NT, ord 4):

```xml
<w lemma="strong:G976 lemma.TR:..." morph="robinson:...">...</w> <w lemma="strong:G11 lemma.TR:..." ...>...</w>
```

eBible `engweb2025eb` (Haiola output, `ot.bzz` block 1) — real `ε`/`θ` elisions aside, verbatim shape:

```xml
<div canonical="true" sID="gen3" type="bookGroup"/><title>Old Testament</title><div canonical="true" osisID="Gen" sID="gen4" type="book"/><title short="Genesis" type="main">The First Book of Moses, Commonly Called Genesis</title> <chapter n="1" osisID="Gen.1" sID="Gen.1.seID.00001"/> <div sID="gen5" type="majorSection"/><div sID="gen6" type="x-p"/> <w lemma="strong:H8064">In</w> <w lemma="strong:H1254">the</w> <w lemma="strong:H7225">beginning</w>, <w lemma="strong:H8064">God</w><note osisID="Gen.1.1!note.1" osisRef="Gen.1.1" placement="foot" type="translation"><reference osisRef="Gen.1.1" type="source">1:1 </reference>The Hebrew word rendered "God" is "..." (Elohim).</note> <w lemma="strong:H1254">created</w>
```

The `<note osisID="Gen.1.1!note.1" osisRef="Gen.1.1" placement="foot" type="translation">`
is the canonical way footnotes and cross-references are distinguished:
`type="translation"` = footnote, `type="crossReference"` = scripref, `type="explanation"` = note.

## 1.6 Commentaries (`zCom`, `HREFCom`, `RawFiles`)

`zCom` is byte-for-byte the same container as `zText` (`.czs`/`.czv`/`.czz`) with
`BlockType=CHAPTER` typically. Verse ordinals use the same pseudo-verse model.

`Barnes` is `SourceType=ThML`; the tags actually present in the block stream are exactly:

```
<br/>, <i>, <blockquote>, <scripRef>
```

i.e. minimal ThML: `<br/>` line breaks, `<i>` italic, `<blockquote>` for quotations,
`<scripRef>Ref</scripRef>` for cross-references. **No `<verse>` elements.**

`HREFCom` — each "entry" is just a URL to the entry body (experimental, network-dependent;
do not implement).

`RawFiles` — one text file per entry inside `DataPath`; recommended for Personal Commentary
and by far the easiest commentary driver to implement.

## 1.7 Lexicons and dictionaries

### `RawLD` (uncompressed) — verified with `2BabDict`

`DataPath=./modules/lexdict/rawld/2babdict/2babdict` (no trailing slash) -> `2babdict.dat`
+ `2babdict.idx`.

`.dat` is flat text; entries are framed as `KEY\r\nCONTENT\r\n`:

```
AAKBAR\r\n[Chaldean] A mouse, also signifies "The mighty one", ... <i>See: <term>Gheber</term></i>\n\r\n
ABER\r\nSignifies a "wing".\n\r\n
ABIR\r\nSynonym of Gheber.\n\r\n
ADAD\r\n"The One God."\n\r\n
```

A plain linear scan yields 265 clean entries (`AAKBAR`, `ABER`, `ABIR`, `ADAD`, `ADONAI`,
`ADON`, `ADONIS`, `AGATHODAEMON`, `AGNI`, `AITHIO PAIS`, ... , `ZOROASTER`, `ZURO-ASHA`);
strip the trailing `\n\r\n` from each CONTENT. **Do this rather than trusting `.idx`.**

`.idx` (1,590 bytes = 795 `uint16` LE) is SWORD's offset/length table; it interleaves start,
size and end-of-entry values (the 2-byte `\r\n` separator accounted for) — leading values
`0, 229, 231, 0, 26, 259, 0, 25, 286, ...`. The exact record shape is undocumented by
CrossWire ("Our module file format is proprietary in the sense that we see no need to
document it"); the linear scan is exact and cheap, so prefer it.

Keys are normalised to UPPERCASE unless `CaseInsensitiveKeys=true`. Markup is ThML/TEI-lite
(`<term>`, `<i>`). Strong's keys (`G5485`, `H0430`) are recognised and zero-padded unless
`StrongsPadding=false`.

### `zLD` (compressed) — verified with `StrongsGreek`

`DataPath=./modules/lexdict/zld/strongsgreek/dict` -> `dict.dat`, `dict.idx`, `dict.zdt`,
`dict.zdx`.

The four files work together, and none of them is read on its own without the others.

* `dict.zdx` — a **block table**: `count` × `(startInZdt, compressedLength)` `uint32` pairs
  (verified: `(0,4730) / (4732,3533) / (8267,3791) ...` — each block starts 2 bytes after the
  previous one ends, because every compressed block on disk is followed by a `\r\n` that is
  *not* part of it).

* `dict.zdt` — **not one zlib stream**.  It is `count` separately-compressed blocks, each a
  zlib stream (magic `78 9c`) sitting at the offset given by `.zdx`.  Decompressing one block
  yields a single `uint32` entry count, then `count` × `(offsetInBlock, length)` `uint32`
  pairs, then the concatenated TEI entry texts:
  `count=30`, pairs `(244,2848) / (3092,581) / (3673,284) ...`, and the text begins at byte
  244 (= 4 + 30*8), exactly where the first `<entryFree n="0">` was found; every pair is
  `offset` and `length`, and the next entry begins where the previous one ends.

* `dict.dat` — `count` × `KEY \r\n (u32 block) (u32 entry) \r\n` records.  The block number
  picks a decompressed block from `.zdx`/`.zdt`; the entry number indexes that block's
  offset/length table, giving `blockText[offset : offset+length]`:
  `00000\r\n 0 0 \r\n` = title page (block 0, entry 0), `00001\r\n 0 1 \r\n` = "ἄλφα".
  The file is 97,688 bytes for 5,742 records (key `\r\n` + 8 + `\r\n` each).

* `dict.idx` (45,936 bytes = 11,484 `uint32`) is a *key* index of `(offsetInDat, recordLength)`
  pairs into `.dat` (`0,15 / 17,15 / 34,15 / 51,15 ...` — step 17), used only for binary
  search by key; it is not needed to read the entries in order.

* `dict.zdt` block body content is TEI: `<entryFree n="0">...</entryFree>`, `<lb/>` line breaks,
  `<orth>ἄλφα</orth>`, transliteration and `<def>`.  `SourceType=TEI`;
  `Feature=GreekDef` / `HebrewDef` / `GreekParse` / `HebrewParse`.
  `StrongsGreek` `Version=2.0` switched from ThML to a "lexicon template with standard
  elements for each entry including Greek lexical form, transliteration and pronunciation".

**Aliases.** `AbbottSmithStrongs` (`abbottsmithstrongs`) stores each headword *twice*: once
under the Greek lemma (`Α`) with the real article, and once under the Strong's number
(`00001`) with the body `@LINK α\0`.  An `@LINK` body names another key in the same
module and is a pointer, not an article, so it is resolved to the target's body and a
dangling link is dropped (20 of them).  Entries are NUL-terminated; the terminator is
stripped.  Resolved, the module reads 11,394 records over 380 blocks.

**Corrupt wrapper tag.** In the same module a few entries open with
`<checked-cfb except="rongs numbers?>">` — the last three characters are transposed, so
the attribute value has no closing quote.  Such a tag cannot be matched by a tag parser, and
combined with a missing close tag it cost the whole article (see §2.3 "Unbalanced markup");
the tag is repaired before parsing, so only the stray `">` is lost.  A well-formed
tag cannot match that pattern because its own closing quote blocks the value character class.

`RawLD4` / `zLD4` / `zText4` / `zCom4` are the same formats with 4-byte length fields instead
of 2/4, for entries larger than 64 KiB. `MinimumVersion=1.8` required.

## 1.8 Mirrors, real filenames, and repository lists

### Verified mirror indexes (HTTP 200)

* `https://crosswire.org/ftpmirror/pub/sword/packages/` — contains only `mac/`, `rawzip/`, `win/`
* `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/` — **463 `.zip` files**
* `https://crosswire.org/ftpmirror/pub/sword/packages/win/` — 235 `.zip` files
* `https://crosswire.org/ftpmirror/pub/sword/packages/mac/` — 229 `.zip` files
* `https://crosswire.org/ftpmirror/pub/sword/raw/` — the **uncompressed** tree
  (`mods.d/`, `mods.d.tar.gz`, `modules/`, `packages/`, `tmp/`, `zipup.sh`, `locales.d/`);
  `.../raw/modules/texts/ztext/kjv/` serves `nt.bzs nt.bzv nt.bzz ot.bzs ot.bzv ot.bzz` individually
* `https://crosswire.org/ftpmirror/pub/sword/raw/mods.d/2babdict.conf` — 200 `text/plain`
* `https://crosswire.org/ftpmirror/pub/sword/frontend/win32/` — `latest-is-v1.7.3`,
  `v0.0/ v1.0/ v1.2/ v1.4/ v1.5/ v1.7/`
* `https://ebible.org/sword/zip/` — browsable (`aai2009eb.zip`, `engweb2025eb.zip`, ...)

`https://ftp.sword-tools.org/pub/sword/packages/` -> **DNS failure** (host does not resolve).
Do not use it; use `crosswire.org/ftpmirror`.

### `win/` vs `rawzip/` — important

`win/*.zip` is a self-extracting **Inno Setup / InstallShield installer** (verified:
`win/KJV.zip` is 4,724,029 bytes and its zip entries are `DATA.TAG` and `SETUP.INI` — an
installer stub, not a plain zip). **`rawzip/` is the plain zip and is what an importer wants.**

### Real `rawzip/` filenames (463, verified listing)

Bibles: `KJV.zip` `KJVA.zip` `WEB.zip` `ESV.zip` `ESV2011.zip` `NLT.zip` `NIV.zip` `NASB.zip`
`LEB.zip` `YLT.zip` `Darby.zip` `DRC.zip` `Geneva.zip` `Geneva1599.zip` `BBE.zip` `BWE.zip`
`JPS.zip` `LXX.zip` `Tisch.zip` `TR.zip` `SBLGNT.zip` `SBLGNTApp.zip` `MorphGNT.zip` `OSHB.zip`
`HebrewGreek.zip` `Aleppo.zip` `MKJV.zip` `PorLitCal2020.zip` `PorLitCal2022.zip`
`PorLitCal2023.zip` `PorLitCal2024.zip` `RusCARS.zip` `RusSynodal.zip` `VieLCCMN.zip`
`VieLCCMNCT.zip` `Zefania`-era `GerLeoNA28.zip` `GerLutherpredigten.zip` `GerNeUe.zip`
`UlB`→`ULB.zip` `UKJV.zip` `Vulgar`→`Vulgate.zip` `Webster.zip` `Wycliffe.zip` `zh`
→`ZhEnglish.zip` `ZhHanzi.zip` `ZhPinyin.zip`.

Lexicons/dictionaries: `2BabDict.zip` `StrongsGreek.zip` `StrongsHebrew.zip`
`BDBGlosses_Strongs.zip` `ChisStrongsGreek.zip` `ChisStrongsHebrew.zip`
`ChitStrongsGreek.zip` `ChitStrongsHebrew.zip` `FreStrongsGreek.zip` `FreStrongsHebrew.zip`
`AbbottSmith.zip` `AbbottSmithStrongs.zip` `RusCARSDict.zip` `RusCARSTDICT.zip` `MLStrong.zip`
`DBD.zip` `Nave.zip` `FreLXXGiguet.zip` `FreLXXTheo.zip` `UrdGVDevanagari.zip` `UrduGeo.zip`
`UrduGeoBangla.zip` `UrduGeoDeva.zip` `UrduGeoRoman.zip` `HunKNB.zip`.

Commentaries: `Barnes.zip` `Clarke.zip` `JFB.zip` `DutKingComm.zip` `DutKingComments.zip`
`GerKingComm.zip` `GerKingComments.zip` `Lightfoot.zip` `BulpCarigradNT.zip` `BulpVeren.zip`
`CalvinCommentaries.zip` `Catena.zip` `AmTract.zip` `GerAugustinus.zip` `Personal.zip`
`Barnes`-adjacent `Cawdrey.zip` `Nave.zip` `Torrey.zip` `TSK.zip` `WLC.zip` `RWebster.zip`.

Devotionals/other: `Daily.zip` `Wesley.zip` `Family.zip` `Imitation.zip` `Practice.zip`
`VarApp.zip` `MapM.zip` `Sentiment.zip` `FreLitCal2021.zip` `FreLitCal2025.zip`
`FreLitCal2026.zip` `Pilgrim.zip` `RLT.zip` `Diaglott.zip` `Didache.zip` `Enoch.zip`
`Jubilees.zip` `Josephus.zip` `Spurious.zip` `KJV.zip` `KJVPCE.zip` `Orthodoxy.zip`.

The full 463-name listing is saved at `/tmp/opencode/bible-research/sword_rawzip_list.txt`.

### Verified sample module downloads (all HTTP 200, all parsed successfully)

| URL | Bytes | Notes |
|---|---|---|
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/KJV.zip` | 4,026,621 | zText/OSIS, `Versification=KJV` |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/Barnes.zip` | 5,812,827 | zCom/ThML |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/2BabDict.zip` | 16,960 | RawLD |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/StrongsGreek.zip` | 561,494 | zLD/TEI |
| `https://eBible.org/sword/zip/engweb2025eb.zip` | 3,953,791 | zText/OSIS, `Versification=NRSVA` |

### `masterRepoList.conf` (the install-manager source list) — HTTP 200, verbatim

```ini
[Repos]
20220529224400=HTTPSPackagePreference=CrossWire|crosswire.org|/ftpmirror/pub/sword/raw
20081216195754=FTPSource=CrossWire|ftp.crosswire.org|/pub/sword/raw
20260902022400=HTTPSPackagePreference=CrossWire Beta|crosswire.org|/ftpmirror/pub/sword/betaraw
20090224125400=FTPSource=CrossWire Beta|ftp.crosswire.org|/pub/sword/betaraw
20260902023000=HTTPSPackagePreference=Bible.org|crosswire.org|/ftpmirror/pub/bible.org/sword
20260902040300=HTTPPackagePreference=Xiphos|ftp.xiphos.org|/pub/xiphos
20260902024500=HTTPSPackagePreference=CrossWire Attic|crosswire.org|/ftpmirror/pub/sword/atticraw
20260902024800=HTTPSPackagePreference=CrossWire Wycliffe|crosswire.org|/ftpmirror/pub/sword/wyclifferaw
20260902021100=HTTPSPackagePreference=eBible.org|ebible.org|/sword
20260902025200=HTTPSPackagePreference=Deutsche Bibelgesellschaft|crosswire.org|/ftpmirror/pub/sword/dbgraw
20260902021300=HTTPSPackagePreference=Lockman Foundation|crosswire.org|/ftpmirror/pub/sword/lockmanraw
```

Format: `<timestamp>=<Key>=<Label>|<host>|<path>`, keys `FTPSource`, `HTTPSSource`,
`HTTPPackagePreference`, `HTTPSPackagePreference`.

## 1.9 The `INSTALL` / `install.conf` mechanism — what is actually true

The popular description is wrong for the current CrossWire tree:

* **The 463 `rawzip/*.zip` module packages contain NO `install.conf`** — verified by unzipping
  four of them. They are pure `mods.d/...` + `modules/...` trees.
* The `win/*.zip` and `mac/*.zip` variants are **self-extracting installers**, not
  `install.conf` packages.
* An `install.conf` appears in **CrossWire update bundles** (the `frontend/win32/v1.7/`
  releases, e.g. `sword-win32-1.7.3.exe`), currently only shipped as `.exe`. It is an INI
  consumed by SWORD's `installmgr` (and JSword's `InstallManager`) to drive unattended
  multi-module installation/update, with `[General]` and per-module sections.
* I could **not** fetch a live `install.conf` to quote verbatim — every current distribution
  path ships `.exe` instead. **If you need update-bundle support you must shell out to
  `sword`'s `installmgr`/`diatheke` or parse the installer stub; there is no longer a
  plain-zip update package on `crosswire.org`.**
* `installmgr` is **not** a valid `.conf` key in the current wiki spec. The valid keys are
  exactly those in §1.2.
* `zip -r -D zip/mybook.zip mods.d/mybook.conf modules/genbook/rawgenbooks/mybook` is the
  documented way to build a zipped module (`-r` recurse, `-D` no directory entries) —
  from `https://wiki.crosswire.org/Zipped_modules`.

## 1.10 CrossWire licensing of the *format* vs the *content*

* The **SWORD engine** is GPL (with the usual SWORD linking exception for front-ends).
* CrossWire's own position, verbatim from `https://wiki.crosswire.org/File_Formats`:
  "Other than the source code for the SWORD API, there is no documentation for the file
  format of a SWORD module. The intention is that the SWORD API (or the JSword
  implementation) is used directly or via other language bindings. ... Our module file
  format is proprietary in the sense that we see no need to document it and certainly no
  need to stick to it."
  **You may read and write the format; there is no claim on it. Content licensing is entirely
  per-module and carried in `DistributionLicense` + the `Copyright*` keys — read those, do
  not assume.**
* `wiki.crosswire.org` documentation is GFDL 1.3.

---

# 2. eBible.org

## 2.1 `catalog.json` / `collection.json` / `manifest.xml` / `eBible-manifest.xml` — GONE

I probed exhaustively. **Every one of these returns 404 from `ebible.org`, and the Wayback
Machine has zero snapshots of any of them:**

| URL | Status |
|---|---|
| `https://ebible.org/Scriptures/catalog.json` | **404** |
| `https://ebible.org/Scriptures/catalog_v2.json` | **404** |
| `https://ebible.org/Scriptures/collections/catalog.json` | **404** |
| `https://ebible.org/Scriptures/collections.json` | **404** |
| `https://ebible.org/Scriptures/eng-scripture-2020.zip` | **404** |
| `https://ebible.org/Scriptures/eng-scripture-2020/eng-scripture-2020.zip` | **404** |
| `https://ebible.org/Scriptures/eng-web.zip` | **404** |
| `https://ebible.org/Scriptures/eng-web/manifest.xml` | **404** |
| `https://ebible.org/Scriptures/manifest.php` | **404** |
| `https://ebible.org/find/catalog.json` | **404** |
| `https://ebible.org/find/devdetails.php?id=eng-web` | **404** |
| `https://ebible.org/find/shortcodes.php` | **404** |
| `https://ebible.org/find/osis.php` | **404** |
| `https://ebible.org/find/formats.php` | **404** |
| `https://ebible.org/Scriptures/eng-web/` | **404** |
| `https://ebible.org/Scriptures/dir.php` | 200 |

Wayback availability API confirms it:
`http://archive.org/wayback/available?url=ebible.org/Scriptures/catalog.json` returns
`{"url": "ebible.org/Scriptures/catalog.json", "archived_snapshots": {}}` (empty object).

The site was redesigned: the read UI moved to `/find/`, downloads became per-format zips.
**Do not build an importer against `catalog.json`.** Scrape `/find/index.php` (contains
`details.php?id=<id>` for every translation) and/or `/Scriptures/dir.php` (contains every
downloadable filename with size + mtime).

## 2.2 What eBible.org actually serves (all HTTP 200, verified)

### Translation index

* `https://ebible.org/find/index.php` — full translation list (~1,400 `details.php?id=...`
  links). Sortable: `index.php?sort=e|l|t|v`.
* `https://ebible.org/find/country.php?c=US` — by territory.
* `https://ebible.org/find/details.php?id=eng-web` — per-translation page. Metadata table:
  `Language: [eng] | English | English`, `Dialect: American`, `Title:`, `Abbreviation: WEB`,
  `ID: ENGWEB or eng-web`, licence line. Then a per-format download table.
* `https://ebible.org/find/details.php?id=302` — 200; numeric legacy IDs still resolve.

### File directory listing

`https://ebible.org/Scriptures/dir.php` — `text/html` listing of every file in `/Scriptures/`
with size + mtime. Verified first rows:

```
Adzera Scripture Files-20260130T224104Z-3-001.zip   916366003
KateBibleScan.zip                                   87984251
TonganRWV.zip                                        1533725
aai_browserBible.zip  aai_html.zip  aai_readaloud.zip
aai_usfm.zip          aai_usfx.zip  aai_vpl.zip     aai_xetex.zip
aak_browserBible.zip  aak_html.zip  aak_readaloud.zip
aak_usfm.zip          aak_usfx.zip  aak_vpl.zip     aak_xetex.zip
```

**Naming convention (no exceptions observed):** `<translationID>_<format>.zip`, where
`<format>` is one of `html`, `readaloud`, `usfm`, `usfx`, `vpl`, `xetex`, `browserBible`,
`_word`. Plus a handful of idiosyncratic names (`KateBibleScan.zip`,
`Adzera Scripture Files-<ISO8601Z>-3-001.zip`).

Format semantics: `readaloud` = plain text, canon only, one file per chapter. `usfm`/`usfx`
= Paratext. `vpl` = BibleWorks (VPL) + SQL. `browserBible` =
`github.com/digitalbiblesociety/browserbible-3`. `xetex` = `scripts.sil.org/xetex`.

### Verified working sample downloads

| URL | Status / bytes | Contents verified |
|---|---|---|
| `https://eBible.org/sword/zip/engweb2025eb.zip` | 200, `application/zip`, 3,953,791 | 7 entries: `mods.d/engweb2025eb.conf` (3,839 B) + `ot/nt.{bzs,bzv,bzz}` |
| `https://ebible.org/Scriptures/eng-web_usfx.zip` | 200, 3,299,041 | `BookNames.xml` (7,183), `eng-webmetadata.xml` (13,436), `eng-web_usfx.xml` (18,896,104), `eng-web-VernacularAdditional.xml` (300), `eng-web-VernacularParms.xml` (25,956), `copr.htm` (3,445), `keys.asc` (21,585), `gentiumplus.css` (9,565) |
| `https://ebible.org/Scriptures/eng-web_usfm.zip` | 200, 3,244,556 | first member `00-FRT/eng-web.usfm` — one file per book, named `<NN>-<ABBR>` |
| `https://ebible.org/Scriptures/eng-web_html.zip` | listed on details page | |
| `https://ebible.org/Scriptures/eng-web_readaloud.zip` | listed | |
| `https://ebible.org/Scriptures/eng-web_vpl.zip` | listed | |
| `https://ebible.org/Scriptures/eng-web_xetex.zip` | listed | |
| `https://ebible.org/Scriptures/eng-web_browserBible.zip` | listed | |
| `https://eBible.org/epub/eng-web.epub` | listed | |
| `https://ebible.org/pdf/eng-web/` | listed (PDF file list) | |
| `https://ebible.org/eng-web/` | mobile HTML | |
| `https://ebible.org/eng-web/mp3/`, `/eng-web/pwa/`, `/scriptures/org.ebible.engweb.apk` | listed | |

### The eBible SWORD conf (verbatim, `engweb2025eb.conf`)

```ini
[engweb2025eb]
Abbreviation=WEB
Description=World English Bible Classic
DataPath=./modules/texts/ztext/engweb2025eb/
ModDrv=zText
SourceType=OSIS
Encoding=UTF-8
CompressType=ZIP
BlockType=BOOK
Versification=NRSVA
OSISqToTick=false
Font=Gentium Plus
Feature=StrongsNumbers
GlobalOptionFilter=OSISStrongs
GlobalOptionFilter=OSISFootnotes
GlobalOptionFilter=OSISScripref
GlobalOptionFilter=OSISHeadings
GlobalOptionFilter=OSISRedLetterWords
About=The World English Bible The World English Bible is in the Public Domain. That means that it is not copyrighted. However, "World English Bible" is a Trademark of eBible.org. ...
SwordVersionDate=2026-09-22
Version=617.0
History_617.0=Automatically generated on 2026-09-22 from source files dated 2026-09-22 using Haiola (http://haiola.org)
MinimumVersion=1.7.0
Category=Biblical Texts
LCSH=Bible. English.
Lang=en
InstallSize=4223077
OSISVersion=2.1.1
Copyright=PUBLIC DOMAIN
CopyrightNotes=This work is not copyrighted. It is in the Public Domain. You may copy and publish this work freely, but you may not claim copyright on it.
DistributionLicense=Public Domain
ShortCopyright=PUBLIC DOMAIN
TextSource=https://eBible.org/Scriptures/
Obsoletes=engWEB2015eb
Obsoletes=eng_web2015
Obsoletes=WEB
Obsoletes=engWEBc2015
```

Note the newer keys: `Abbreviation`, `Category`, `Copyright`, `CopyrightNotes`,
`ShortCopyright`, `Obsoletes`, `OSISqToTick`, `Font`, `Versification=NRSVA`, and
`Version=617.0` (auto-generated build counter, not a semver).

### Changelog

`https://ebible.org/Scriptures/changelog.txt` — 200, `text/plain`, 73,067 bytes: dated history
of per-translation file changes since 2012-12-14. Its header states that appending a
translation ID to `https://ebible.org/find/details.php?id=<id>` gives the metadata.

### Also live and useful

* `https://ebible.org/osis/` (200) — OSIS doc hub, links the OSIS 2.1 User Manual PDF,
  the schema, and the OXES documentation.
* `https://ebible.org/usfx/` (200) — USFX spec.
* `https://ebible.org/bible/gbf.htm` (200) — General Bible Format tagging spec
  (plain ASCII text, lines limited to 254 chars).
* `https://ebible.org/osisCore.2.1.1.xsd` (200, 94,067 bytes) — **the authoritative OSIS
  2.1.1 schema**. Target namespace `http://www.bibletechnologies.net/2003/OSIS/namespace`.
* `https://ebible.org/robots.txt` (200, 55 bytes) — only
  `User-agent: Baiduspider` / `Disallow: /index.php/component`.

## 2.3 OSIS markup (the eBible/SWORD interchange format)

**Ground truth is the XSD.** It declares 744 elements, 142 named types/attribute groups, and
231 attribute names.

### The 231 attribute names (complete global attribute set)

```
ID  POS  TEIform  align  alt  annotateRef  annotateType  annotateWork  canonical  catalog
chapterTitle  cols  eID  editions  end  event  expansion  file-as  gloss  href  index
lemma  level  level1  level2  level3  level4  location  marker  morph  n  osisID
osisIDWork  osisRef  osisRefWork  osisWork  path  placement  regular  resp  rights  role
rows  sID  scope  script  see  short  size  src  start  subType  type  use  who
witness  xlit
```

### The element set (deduplicated from the schema's content models)

```
osis  osisCorpus  osisText  header  titlePage  revisionDesc  work  workPrefix  teiHeader
refSystem  castList  castItem  castGroup  actor  role  roleDesc  contributor  creator
subject  date  description  publisher  type  format  identifier  source  language  relation
coverage  rights  scope  index  div  p  q  seg  w  head  title  a  abbr  date  divineName
foreign  hi  index  lb  milestone  name  note  reference  speaker  transChange
milestoneStart  milestoneEnd  inscription  list  mentioned  closer  figure  lg  salute  seq
signed  speech  table  verse  chapter  caption  head  item  l  cell  row  label  catchWord
rdg  rdgGrp  term
```

### Practical element semantics

| Element | Attributes | Meaning |
|---|---|---|
| `osis` / `osisText` | `osisIDWork`, `osisRefWork` | document root; `osisText` is one corpus member |
| `header` | | Dublin-Core-like TEI header |
| `div` | `type` (`book` `bookGroup` `majorSection` `section` `paragraph` `x-p` `x-OT` `x-NT`), `subType`, `canonical`, `sID`, `osisID` | structural division |
| `title` | `type` (`main` `chapter` `subTitle` `heading` `section` `part`), `level`, `short`, `placement`, `sID` | heading text |
| `chapter` | `osisID` (`Gen.1`), `sID`, `chapterTitle`, `n` | chapter boundary; self-closing/milestone in practice |
| `verse` | `osisID` (`Gen.1.1`), `sID`, `canonical` | verse; **stripped by SWORD importers** — see §1.3 |
| `milestone` | `type` (`x-p`, `x-importer`, `x-osis2mod`, `x-added`, ...), `subType`, `marker`, `n`, `ref` | point event, no children |
| `milestoneStart` / `milestoneEnd` | `type` (`x-...`, `x-orig`, `x-kg`), `ref`, `sID` | paired span events |
| `w` | `lemma` (`strong:H0430`, `lemma.TR:<text>`), `morph` (`strongMorph:TH8804`, `robinson:...`), `xlit` | a word with lexical/morphological data |
| `seg` | `type` | arbitrary sub-span |
| `note` | `type` (`translation` `explanation` `crossReference` `footnote`), `subType`, `placement` (`foot` `margin` `inline` `end` `center`), `osisID` (`Gen.1.1!note.1`), `osisRef`, `sID`, `ref` | footnote / scripref |
| `reference` | `osisRef`, `type` (`source`), `sID` | an inline scripture reference |
| `q` | `who` (`Jesus`), `marker` (empty means no quote glyph), `sID` | quotation / words of Christ |
| `transChange` | `type` (`added` `alternate` `unclear` `expanded`), `sID` | translation difference |
| `lb` / `lg` / `l` | `sID` | line break / line group / poetic line |
| `list` / `item` | `type`, `n` | |
| `p` | `sID`, `version` | paragraph |
| `figure` / `caption` | `src`, `size`, `align`, `scale`, `title` | image; `src` is a relative path resolved against `DataPath` |
| `hi` | `type` (`italic` `bold` `sup` `sub`), `rend` | generic typographic |
| `divineName` | | divine name, e.g. `Lord` |
| `foreign` | `n` (`Heb`, `Greek`), `xml:lang` | foreign-script run |
| `name` | `type` (`person` `place` `group`), `n` | proper name |
| `catchWord` | `osisID` | catchword |
| `rdg` / `rdgGrp` | `type` (`variant`), `witness` | textual variant |
| `abbr` | `expansion` | e.g. `<abbr expansion="Saint">ST.</abbr>` |
| `speaker` / `speech` | `who` | drama |
| `table` / `row` / `cell` | `cols`, `rows`, `align` | |
| `salute` / `signed` / `closer` / `inscription` / `date` | | letter structure |
| `mentioned` | `who` | participant mention |
| `seq` | `seq` | sequence |
| `label`, `term`, `head`, `index` | | |

Named taxonomy types declared in the schema (use these values for `type`/`subType`):
`divType`, `noteType`, `annotationType`, `referenceType`, `segType`, `titleType`, `hiType`,
`changeType`, `quoteType`, `rdgType`, `lineType`, `lineGroupType`, `eventType`, `nameType`,
`typeType`, `subjectType`, `milestonePt`, `milestoneSe`, `calendar`, `languageType`,
`languageUsage`, `roleType`, `tableRole`, `titlePlacement`, `notePlacement`, `osisQuotes`,
`osisNotes`, `osisRdg`, `osisSegs`, `osisTitles`, `osisLine`, `osisLineGroup`, `osisHi`, etc.

**Encoding rules.**

* `osisID` / `sID` follow the OSIS ID regex: `Book`, `Book.Chapter`, `Book.Chapter.Verse`,
  ranges with `.` and `-` (e.g. `Gen.1.1-Gen.1.6`), `!` for non-canonical anchors
  (`Gen.1.1!note.1`, `Gen.1.1!w.2`), and `-` inside segment suffixes.
* `osisRef` is the reference-bearing variant; `osisRefWork` / `osisWork` / `osisIDWork`
  reference another corpus.
* Attribute *order* is irrelevant.
* For `SourceType=OSIS`/`TEI`/`ThML`, each verse, dictionary entry and book division must be
  well-formed XML or front-ends will silently drop text.
* Unicode NFC (except Biblical Hebrew) — see §1.4.

**Unbalanced markup.** Real modules are not always well-formed, so a reader must not let one
bad tag cost it the text.  Two cases matter, and both are handled by flushing rather than
discarding:

* An element that is never closed.  When a close tag arrives for an *ancestor* while a
  descendant is still open, the descendant's already-collected text must be emitted into the
  closing frame before it is popped, not deleted with it.  (`AbbottSmithStrongs` wraps entries
  in `<checked-cfb except="rongs numbers?>">`; the attribute's closing quote is missing, so the
  element has no close tag at all, and `</entry>` arriving afterwards used to throw the whole
  article away and store an empty one.)
* Frames still open at end of input are flushed innermost-first rather than dropped.

A "skip" frame (TEI header, `header`/`work`/`creator`/...) still drops its content, as it must.

### Where the verse number lives differs between OSIS corpora

Both Open Scriptures sets are OSIS with `<w lemma morph>` words, but they disagree about how a
verse is identified, so a reader that assumes one shape silently reads zero verses from the
other:

| | verse id | example |
|---|---|---|
| SBLGNT | `eid` carries the verse | `<verse osisID="Matt.1.1" eid="Matt.1.1!v1">` |
| OSHB / morphhb | `osisID` only | `<verse osisID="Gen.1.1">` |

Chapter likewise: SBLGNT marks `<chapter eid="...!c1">` and ends it with a `!p` milestone, while
morphhb has neither — take chapter and verse from the parsed `osisID` instead.

OSHB also writes its lemma in a form no Strong's regex expects: an optional initial letter and a
slash (`b/7225`), a bare number (`430`), or a number with the letter trailing (`1254 a`).  There
is no `H`/`G` prefix, and a path with no prefix of its own is a Hebrew lemma.  Morphology rides
along in `morph` (`HR/Ncfsa`, `HNcmpa`) and must not be mistaken for the lemma.

## 2.4 USFX and OSIS whole-Bible files (open-bibles, eBible)

`seven1m/open-bibles` ships 42 of these, one file per translation, 5–19 MB each.  Three things
about them are not in either schema and each one silently loses the Bible if missed.

**A verse's words are the element's `tail`, not its text.**  Both formats mark verses with
self-closing elements, so the text follows the tag:

```xml
<usfx>  <v id="1"/>In the beginning God created the heaven and the earth.<ve/>  </usfx>
<osis>  <verse osisID="Gen.1.1" sID="Gen.1.1.seID.00002" n="1"/>In the beginning God created
        the heaven and the earth. <verse eID="Gen.1.1.seID.00002"/>  </osis>
```

An OSIS verse is a *milestone pair*: the `osisID`+`n` element opens it, the bare `eID` element
closes it.  Reading only the opening element's `text` yields an empty verse; reading the
closing element's tail as content splices whitespace into the next verse.

**`<book>` elements nest in USFX.**  A whole Bible is one file and the books are nested rather
than siblings: `<usfx><book id="GEN">…<book id="EXO">…</book></book>`.  Iterating every
`<book>` while the walker also descends into nested ones walks Genesis once per containing
book — 66 times, giving 699,675 units where there are 31,102.  Walk each `<book>` once, on its
own content, and never descend into a nested `<book>`.

**The chapter owns its verses in OSIS.**  The shape is `div[@type=book] > chapter > verse`, and
a walker that handles `chapter` without recursing into it finds the chapters and then no verses
at all — zero units, with no error to explain it.

### Numbering, and two upstream defects

* OSIS may carry the number in `n` or only in `osisID`; the Albanian file has
  `<chapter osisID='Gen.1'>` with no `n` anywhere, and reading `n` alone gives 0 for every
  verse, all of which are then discarded as unnumbered.
* `eng-bbe.usfx.xml` is **truncated** — it stops after Rev 22:21 with no closing tag.
* `heb-leningrad.usfx.xml` has 38 `<book>` and **39** `</book>`, and its books are in a
  scrambled order (`HAG`, `1CH`, `DEU`, …, with `GEN` ninth).  It parses after dropping the
  unmatched close, but its chapters are not in canonical sequence, so next/previous navigation
  follows the file, not the Bible.

Both defects are worth repairing rather than refusing: a strict parse loses all 21,583 verses
that *are* present.  Rebuilding the tag stream against a stack — drop a close that matches
nothing, close whatever is left open — recovers them, and a well-formed file never reaches that
path.  Say so in the module's description rather than letting a short Bible look complete.

## 2.5 eBible licensing

* The *World English Bible* is public domain, **but "World English Bible" is a trademark of
  eBible.org**. From the conf: *"You may copy, publish, proclaim, distribute, redistribute,
  sell, give away, quote, memorize, read publicly, broadcast, transmit, share, back up, post
  on the Internet, print, reproduce, preach, teach from, and use the World English Bible as
  much as you want, and others may also do so. All we ask is that if you CHANGE the actual
  text of the World English Bible in any way, you not call the result the World English Bible
  any more."*
* Per-translation licence is on the `details.php` page and in the SWORD conf's
  `DistributionLicense` / `Copyright*` keys.
* Explicit: *"Pictures included with Scriptures and other documents on this site are
  licensed just for use with those Scriptures and documents. For other uses, please contact
  the respective copyright owners."*

---

# 3. e-Sword

**Two completely different formats depending on version.** e-Sword 9.0 (2010) replaced every
module type with a single-file **SQLite** database. Extension map, verbatim from the
e-Sword 9 Converter's README:

| e-Sword <= 8 | e-Sword >= 9 |
|---|---|
| `.bbl` Bible | `.bblx` |
| `.brp` Bible Reading Plan | `.brpx` |
| `.cmt` Commentary | `.cmtx` |
| `.dev` Devotional | `.devx` |
| `.dct` Dictionary | `.dctx` |
| `.map` Graphics & Maps | `.mapx` |
| `.har` Harmony | `.harx` |
| `.mem` Memory Verses | `.memx` |
| `.ovl` Overlay | `.ovlx` |
| `.prl` Prayer Request | `.prlx` |
| `.not` Study Note | `.notx` |
| `.top` Topic Note | `.topx` / `.refx` |
| `.lst` Verse List | `.lstx` |
| (never converted) Illustrations | `.ill` |

Current release: **e-Sword v15.2.0**, free,
`https://www.e-sword.com/files/e-sword_1520_setup.exe` (200, 57,136,261 bytes, InstallShield
stub; `7z` cannot open it and it yields no plain strings — the payload is compressed).

## 3.1 e-Sword 9+ (`.bblx`) — VERIFIED from a real module

Downloaded `Mizo.zip` (200, 1,952,262 bytes) from
`https://archive.org/download/MizoE-swordBible/Mizo.zip`; it contains a single 5,859,328-byte
`Mizo.bblx`. **It is a plain SQLite 3 database** (`SQLite format 3\0` magic). Exact DDL read
from `sqlite_master`:

```sql
CREATE TABLE Details (Description NVARCHAR(255), Abbreviation NVARCHAR(50),
                      Comments TEXT, Version INT, Font NVARCHAR(50),
                      RightToLeft BOOL, OT BOOL, NT BOOL, Apocrypha BOOL, Strong BOOL);
CREATE TABLE Bible (Book INT, Chapter INT, Verse INT, Scripture TEXT);
CREATE INDEX BookChapterVerseIndex ON Bible (Book, Chapter, Verse);
CREATE TABLE Copyright ( ID int, Author char(255), Title char( 255), Place char(255),
                         Publisher char(255), [Year] Char(20), Edition char(20),
                         Copyright Memo, Notes Memo);
CREATE TABLE metadata (id counter constraint primarykey primary key,
                        element_title varchar(255), element_description memo,
                        taxonomy varchar(255));
```

Actual `Details` row from that module (verbatim):

```
Description   = 'mizo'
Abbreviation  = 'MIZO'
Comments      = '{\rtf1\ansi\ansicpg1252\deff0\...  Generated by Ben''s e-Sword Tool 2.1.0.1 on 13-Jan-12 11:24:18 PM...}'
Version       = '2'
Font          = 'DEFAULT'
RightToLeft   = 'None'
OT            = '1'
NT            = '1'
Apocrypha     = '0'
Strong        = '0'
```

Findings on real data:

* `Book` is **1..66** in Protestant order (verified: `31` = Obadiah in the Mizo
  versification, `max(Book)=66`, `max(Chapter)=150` (Psalms), `max(Verse)=176`
  (Psalm 119)). Row count 31,051 = OSIS 31,102 minus the module's 51 missing verses.
* Booleans are stored as the **strings** `'1'`, `'0'`, and `'None'` in this module — cast
  defensively.
* `Comments`, `Copyright`, `Notes` hold **RTF** (`\rtf1\ansi\ansicpg1252` ...) and/or HTML.
  `Copyright` here held 5 rows, 4 all-NULL plus 1 with RTF in the `Copyright` column.
* `Bible.Scripture` in this module is plain text; other `.bblx` files use **HTML**
  (`<i>`, `<span style="color: #ff0000">`) or RTF depending on `Details.Version`
  (`Version = 4` is documented to mean HTML).
* `metadata` was empty in this file. Some modules encrypt the database (this sample did
  not).

### The other e-Sword >= 9 types

Same pattern — a `Details` single-row table plus a content table. Known/expected:
`.cmtx` Commentary, `.dctx` Dictionary, `.devx` Devotional (keyed `MM.DD`), `.mapx` Maps,
`.notx` / `.topx` / `.lstx` / `.memx` / `.harx` / `.prlx` / `.ovlx` / `.brpx` / `.ill`.

**Robust strategy: do not hardcode table or column names.** Open the SQLite file, read
`sqlite_master`, then locate tables case-insensitively and probe columns with
`PRAGMA table_info`. This is exactly what And Bible does for MySword/MyBible
(`MySwordBook.kt` does `select * from details`, lowercases `columnNames`, then
`.indexOf("title")`, `"description"`, `"abbreviation"`, `"version"`, `"rightToLeft"`,
`"strong"`, `"language"`). Empty `Details` fields default to `""`; missing booleans -> false.

## 3.2 e-Sword <= 8 (`.bbl` + `.mod` + `.bzs`/`.bzv`/`.bzz`)

The three data files are the **same binary family as CrossWire SWORD's `zText`**
(`.bzs` = block table, `.bzv` = verse index, `.bzz` = compressed blocks); e-Sword and
CrossWire co-developed this container and third-party parsers such as `pysword` treat them
identically. The genuine difference is the metadata file.

### The `.mod` file

A **tab-separated** flat text file, one record per module, sitting next to the data file
(same basename, `.mod`). Key names in the e-Sword module-creation convention:

| Key | Meaning |
|---|---|
| **IDtab** | module ID / short tab name (the leading identifier column) |
| **name** | full display name |
| **abbrev** | short abbreviation shown in the translation dropdown |
| **version** | module version string |
| **Category** | `Bible` `Commentary` `Dictionary` `Devotional` `Images` `Audio` `Other` (also seen: `Maps`, `Book`, `Topic`) |
| **Description** / **About** | long description |
| **Font** | default font |
| **RightToLeft** | `0` / `1` |
| **OT** / **NT** / **Apocrypha** | `1` present |
| **Strong** | `1` module carries Strong's numbers |
| **Lang** / **Language** | language code |
| **VersionDate** | date |
| **Copyright** / **Comments** | licensing and notes |
| **encryption** / **passphrase** | present when password-protected |

**Honesty flag.** The exact `.mod` key spelling is documented only in third-party sources.
e-Sword publishes no format spec: the 2014 e-Sword User's Guide (downloaded, full-text
searched) contains **zero** occurrences of `.mod`, `IDtab`, `bzs`, `bzv`, `bzz`, `bzu` or
"tab-separated". **Write the `.mod` reader schema-tolerantly:** split on `\t` and `\r\n`,
build a `dict` from the first record, then look up keys case-insensitively with fallback
lists (`IDtab|id|Id`, `name|Name|Title`, `abbrev|Abbreviation`). `Category` is the only field
you cannot safely guess — map it case-insensitively and default to `Other`.

## 3.3 Text markup in e-Sword modules

### e-Sword 9+ (`.bblx` / `.cmtx` / ...)

**HTML or RTF**, per `Details.Version` (`4` => HTML). That is the whole markup. Red letters
are plain inline styling:

```html
<span style="color: #ff0000">Surely I come quickly.</span>
```

No special tag language. Strip tags (and RTF control words) and you are done.

### e-Sword <= 8 (`.bbl` / `.cmt` / `.dct` / `.dev`)

Rich inline markup, RTF-flavoured, with these widely-implemented conventions — **I could not
verify these against a live v8 module file, see §3.6**:

* `myb` — a *block* delimiter for the module body.
* `{nnn}` and `~nnn` — **Strong's number** notation. `~` places the number as a superscript
  after the word; `{...}` places it in parentheses/brackets after the word. `H`/`G` prefix
  distinguishes Hebrew/Greek (`~H0430`, `~G976`).
* `s` — a superscript run, used for Strong's and morphology.
* Red-letter tagging: the words of Christ are wrapped in a colour/formatting run
  (e-Sword's own `{font ...}`/RTF colour, or a `<b>`-style tag pair depending on build).
* `{{...}}` — an **image placeholder**; the body is a filename (optionally with
  `|`-separated geometry) resolved relative to the module's image folder.
* Morphology in interlinear modules is a run beginning with `=`; treat any `=`-prefixed run
  as a morphology block.

Given the uncertainty, **the defensible engineering choice for e-Sword <= 8 is to convert to
e-Sword 9+/SQLite first** (the free `e-SwordPCModuleConverter` does this) and read the
SQLite. If you must read v8 directly, target only plain-text modules.

## 3.4 e-Sword file-format summary

| Content | <= 8 | >= 9 |
|---|---|---|
| Bible | `.bbl` + `.mod` + `.bzs/.bzv/.bzz` | `.bblx` (SQLite) |
| Commentary | `.cmt` + `.mod` + `.czs/.czv/.czz` | `.cmtx` (SQLite) |
| Dictionary | `.dct` + `.mod` + `.dat/.idx` | `.dctx` (SQLite) |
| Devotional | `.dev` + `.mod` | `.devx` (SQLite) |
| Maps/images | `.map` + image folder | `.mapx` (SQLite) |
| Audio | — | separate media, not a module DB |

## 3.5 e-Sword module download catalogue — NOT PUBLICLY DOCUMENTED, obvious URLs dead

Verified 404/403:

```
404  https://www.e-sword.com/download/          (and /download/bibles.xml, /modules.xml)
404  https://www.e-sword.com/modules/
404  https://www.e-sword.com/api/
404  https://www.e-sword.com/esources.xml
404  https://www.e-sword.com/list/bibles.xml
404  https://www.e-sword.com/catalog/bibles.xml
404  https://www.e-sword.com/categories/bibles.xml
404  https://www.e-sword.com/downloads/bibles.xml
404  https://www.e-sword.net/download/bibles.xml
403  https://www.e-sword.com/bibles.xml         (nginx 403, no autoindex)
403  https://www.e-sword.com/files/             (nginx 403, no autoindex)
403  https://www.e-sword.net/bibles.xml
```

Live e-Sword pages (all 200): `/`, `/downloads.html`, `/faq.html`, `/tutorial.html`,
`/links.html`, `/history.html`, `/changes.html`, `/android/`, `/index.html`.
`downloads.html` links only `files/e-sword_1520_setup.exe` and `links/berean.html`.

**Conclusion:** e-Sword's in-app "Download" catalogue is fetched by the Windows/Android
client from an endpoint no longer served from a discoverable public path. The installer EXE
is an opaque InstallShield blob (no extractable strings; `7z` refuses it), so the URL could
not be recovered from it either.

Practical alternatives for an importer (all verified reachable):

* `http://www.biblesupport.com/e-sword-downloads/` plus
  `.../category/2-bibles/`, `.../category/3-commentaries/`, `.../category/7-dictionaries/`,
  `.../category/6-devotionals/`, `.../category/50-reference-library/`,
  `.../category/26-mysword-modules/` — HTTP 200, but **plain HTTP only** (HTTPS fails with
  `SSL: WRONG_VERSION_NUMBER`). File pages look like `.../file/<id>-<slug>/`; the real
  download URL is generated by the forum's `public/js/ips.downloads.js`.
* `https://www.eswordlibrary.com/` — WordPress, 2,085 files. REST namespace
  `download-monitor/v1`; `https://www.eswordlibrary.com/wp-json/download-monitor/v1/downloads`
  returns **403 `rest_forbidden`** (authentication required).
* `https://bible.zone/` (200) — MyBible modules.
* `https://archive.org/` — e.g. `MizoE-swordBible/Mizo.zip` (used in §3.1).

## 3.6 `.bzu` / `.bzz` — what is and is not proven

The question was whether `.bzu` is "just a bzip2 of a `.mod` file". **Honest answer: I could
not verify it.**

**Proven:** e-Sword >= 9 modules are single SQLite files (§3.1, real file dissected).
e-Sword <= 8 modules are loose files `<name>.bbl`/`.cmt`/`.dct`/`.dev` + `<name>.mod` + the
`.bzs`/`.bzv`/`.bzz` (or `.czs`/`.czv`/`.czz`) data triple, per the extension tables in §3.1
and §3.2 and per the third-party converter's file-type list.

**Not proven:** any live `.bzu` or `.bzz` file. Every `.bzu` URL I could reach sits behind an
auth wall (BibleSupport, E-Sword Library) or a JS interstitial; both e-Sword download hosts
404/403; the e-Sword User's Guide (2014) mentions none of them.

**Reasonable but unverified assumption:** the extension strongly implies `bz` = **bzip2**, so
`.bzu` is very likely a bzip2 stream that decompresses to the loose module files (the
`.bbl`/`.cmt`/... data triple **plus** the `.mod` metadata) — a single-file distribution
wrapper for what the installer would otherwise scatter into `C:\Program Files\e-Sword\`.
File-type databases (filesuffix.com, datatypes.net) describe `.bzz` as an "E-Sword Bible
Module file ... used in the Data category", but those pages are auto-generated and cite no
primary source.

**Close the gap in 10 minutes:**

```bash
# 1. obtain any .bzu (BibleSupport over plain HTTP, or copy from an e-Sword install dir)
curl -o mod.bzu 'http://www.biblesupport.com/...'
file mod.bzu

# 2. try bzip2 with a small skip, then zip, then tar
python3 - <<'EOF'
import bz2, io, zipfile, tarfile
raw = open('mod.bzu','rb').read()
for skip in range(0, 16):
    try:
        out = bz2.decompress(raw[skip:])
        print('bzip2 OK, skip', skip, '->', out[:400]); break
    except Exception:
        pass
else:
    print('not plain bzip2')
for kind, mod in (('zip', zipfile.ZipFile), ('tar', tarfile.open)):
    try:
        print(kind, mod(io.BytesIO(raw)).namelist()[:20])
    except Exception as e:
        print(kind, 'fail', e)
EOF

# 3. once unpacked, dump the .mod with repr() to recover the exact tab-separated key
#    spellings, and run the section 1.3 parser on the .bzs/.bzv/.bzz triple.
#    If the decompressed payload is itself a zip, recurse with zipfile.
```

## 3.7 e-Sword licensing

* **The e-Sword application is freeware** — no cost, no licence fee, but it is **closed
  source and not open source**; there is no published source licence. Rick Meyers /
  eStudySource retain all rights. You may not redistribute the app as open source.
* **Module licensing is per-module and NOT uniform.** Third-party modules range from public
  domain to copyright-protected to paid "Premium" e-Sword modules. The e-Sword 9 Converter
  README states explicitly: *"Never convert any e-Sword 8.x module that contains copyrighted
  material"* and *"Never convert any e-Sword 8.x Premium module."*
* **Password-protected modules must not be cracked.** Same source: *"Never convert any
  e-Sword 8.x password protected module that you did not originally create."* Some `.bblx`
  files are encrypted at the SQLite level and the encryption scheme is unpublished — do not
  attempt to break it.
* Always read `Details` / `Copyright` / `Comments` and honour the terms recorded there.

---

# 4. MySword / MyBible

MySword is Android; **MyBible** is the same format for desktop (`bible.zone`). Authoritative
spec: **`https://www.mysword.info/modules-format`** (HTTP 200, live, dated 09 April 2015,
~19,000 chars).

## 4.1 It is SQLite

> *"MySword uses SQLite database with an extension of `mybible` for the modules as well as
> other things like settings, bookmarks, highlights, etc."*

## 4.2 File naming and module types

`mysword.jp` **no longer resolves** (DNS failure for `mysword.jp` and `www.mysword.jp`). The
live host is `https://www.mysword.info/`.

Content module extension = a 3-letter type tag **before** `.mybible`:

| Tag | Type |
|---|---|
| `bbl` | Bible |
| `bok` | Book |
| `cmt` | Commentary |
| `dct` | Dictionary |
| `jor` | Journal |
| *(none)* | Personal Notes (structure is actually similar to Commentary) |

**`.bymy` and `.bymo` are not MySword format names.** They are `bible.zone` / MyBible
**bundle** containers: `.bymy` = bundle of MySword/MyBible modules, `.bymo` = a bundle of
MySword/MyBible overlays. The `MyBible Modules Format` spec (Google Doc
`d/12rf4Pqy13qhnAW31uKkaWNTBDTtRbNW0s7cM0vcimlA`; archived PDF at
`https://archive.org/download/mybible-modules-spec-rev-2021-07-31/MyBible%20Modules%20Format.pdf`)
covers "Module Files / Zipped Module Files / Zipping of Related Modules (MyBible version
before 4.8.0) / Bundling of Different Materials Within a ZIP / Module Types / INFO Table".
Treat a `.bymy`/`.bymo` as a **zip** and recurse; the real work is the SQLite file inside.

Also referenced: the MySword user-data folder `mysword/` (bookmarks, highlights, settings —
also SQLite `.mybible`), and MySword graphics / fonts / `<lang>/` subfolders.

## 4.3 Schema — VERIFIED against a real module

Downloaded `https://mysword-bible.info/download/getfile.php?file=kjvlite.bbl.mybible.gz`
(200, `application/x-gzip`, 1,874,198 bytes) -> gunzip -> 5,668,864 bytes starting
`SQLite format 3\0`. Exact `sqlite_master`:

```sql
CREATE TABLE "Bible" ("Book" INT,"Chapter" INT,"Verse" INT,"Scripture" TEXT);
CREATE UNIQUE INDEX "bible_key" ON "Bible" ("Book" ASC, "Chapter" ASC, "Verse" ASC);
CREATE TABLE "Details" ("Title" NVARCHAR(255), "Description" TEXT, "Abbreviation" NVARCHAR(50),
  "Comments" TEXT, "Version" TEXT, "VersionDate" DATETIME, "PublishDate" DATETIME,
  "Publisher" TEXT, "Author" TEXT, "Creator" TEXT, "Source" TEXT, "EditorialComments" TEXT,
  "Language" NVARCHAR(3), "RightToLeft" BOOL, "OT" BOOL, "NT" BOOL, "Strong" BOOL,
  "VerseRules" TEXT);
```

Real `Details` row (verbatim, long fields truncated with a note):

```
Title              = "King James Version of 1611/1769 with Strong's numbers"
Description        = "King James Version of 1611/1769 with Strong's numbers"
Abbreviation       = 'KJVLite'
Comments           = "This is the King James Version of the Holy Bible ... public domain,
                     except in the United Kingdom, where it is governed by Crown copyright."
Version            = '2.9.4'
VersionDate        = '2023-06-16 00:00:00'
PublishDate        = 1769
Publisher          = None
Author             = None
Creator            = 'Costas Stergiou (root@theword.gr) + (wm@theword.net)'
Source             = None
EditorialComments  = '<p>version 2.9.4 [MySword] Fixed note of Psa 89:33 fall should be fail</p>
                     <p>version 1.3.2 Corrected the wrong abbreviation of KJV to KJVLite</p> ...'
Language           = 'eng'
RightToLeft        = 0
OT                 = 1
NT                 = 1
Strong             = 1
VerseRules         = None
```

Counts: 31,102 verses, `max(Book)=66`, `max(Chapter)=150`, `max(Verse)=176` — **Protestant
1..66**, identical to e-Sword/SWORD, not OSIS abbreviations.

Real verse rows (verbatim):

```
Book=43 Chapter=3 Verse=14  '<FR>And as Moses lifted up the serpent in the wilderness, even so must the Son of man be lifted up:<Fr>'
Book=1  Chapter=1 Verse=1   'In the beginning God created the heaven and the earth.'
Book=1  Chapter=1 Verse=2   'And the earth was without form, and void; and darkness <FI>was<Fi> upon the face of the deep. And the Spirit of God moved upon the face of the waters.<CM>'
```

Note that `Version` is a **TEXT** column here (`'2.9.4'`) whereas e-Sword's is INT.

## 4.4 `Details` fields (authoritative, from mysword.info)

| Field | Meaning |
|---|---|
| `Abbreviation` | **No spaces** — the space is the delimiter in internal links. Use `_` or `-` instead. |
| `VersionDate` | `YYYY-MM-DD`; drives the update prompt |
| `Language` | **3-letter** ISO code (note `eng`, not `en`) |
| `RightToLeft` | 0 = LTR, 1 = RTL |
| `OT` / `NT` | 1 = present (Bible only) |
| `Strong` | 1 = Strong's present (Bible/Dictionary) |
| `paragraphindent` | default 1 (first-line indent on); 0 = no indent |
| `VerseRules` | The-Word-style regex rewrite rules, one per line: `<RegEx><TAB><Replacement><TAB><AlternateReplacement><TAB><ToggleName>`; the last two are optional; groups referenced as `$1`, `$2` |
| `wordnanc` | Dictionary: alternate un-accented key field |
| `relativeorder` | Dictionary: display order (default alphabetical) |
| `CustomCSS` | all types: CSS applied to the module's HTML |
| `readOnly` | Journal/Book: read-only flag |
| `Title`, `Description`, `Comments`, `Version`, `PublishDate`, `Publisher`, `Author`, `Creator`, `Source`, `EditorialComments` | bibliographic / HTML |

`VerseRules` examples shipped by the spec (the "space" is really a TAB):

```
<font color=(blue|red)>(.*?)</font>	<span class='$1'>$2</span>
<O>(.*?)<o>	<span class='orange'>$1</span>
<v>(.*?)<v>	<span class='violet'>$1</span>
<K>(.*?)( )?<k>	<span class='red' dir='rtl'>[</span>$1<span class='red' dir='rtl'>]</span>$2
<R>(.*?)( )?<r>	<span class='blue' dir='rtl'>(</span>$1$2
<q>	<Q><span class='blue' dir='rtl'>)</span><q>
```

## 4.5 MySword Bible tags (GBF-derived, from The Word)

Start tag **ALL CAPS**, end tag **First cap + rest lowercase**. Angles are literal.

| Tag | Meaning |
|---|---|
| `<CM>` | paragraph end marker (**not** `<p>`) |
| `<FI>...<Fi>` | italicised / added words |
| `<FO>...<Fo>` | OT quotation (rendered as `<span class='ot'>`; style via `CustomCSS`) |
| `<FR>...<Fr>` | words of Jesus, in red |
| `<FU>...<Fu>` | underlined words |
| `<WG####>` | Strong's **Greek** (e.g. `<WG5485>`) |
| `<WH####>` | Strong's **Hebrew** (e.g. `<WH2617>`) |
| `<WTCODE>` | morphology code (e.g. `<WTN-NSF>`) |
| `<RF>...<Rf>` | translator's note. Optional note-link text: `<RF q=a>...<Rf>` |
| `<RXref>` | cross-reference; `ref` = `b.c.v` or `b.c.v-tv` (e.g. `<RX43.3.16>`) |
| `<TS>...<Ts>` | title. `<TS1>`, `<TS2>`... are also treated as plain titles |
| `<PI0>`-`<PI7>` | poetry indent (0..7) |
| `<PF0>`-`<PF7>` | first-line indent (0..7) |
| `<CI>` | space separator (currently) |

Interlinear tags: `<Q>...<q>` interlinear block; `<E>...<e>` **or** `<T>...<t>` English;
`<X>...<x>` transliteration; `<D>` ignored; `<H>...<h>` Hebrew (ignored); `<G>...<g>` Greek
(ignored); `<wh>` Hebrew word marker (ignored); `<wg>` Greek word marker (ignored); `<wt>`
ignored.

Real interlinear sample from the spec (HiSB, Hebrew) — note `<WH7225>` and the middle-dot
transliteration:

```
<Q><H><wh>בְּ<D>רֵאשִׁ֖ית<WH7225><h><X>be·re·Shit<x><T>In the beginning<t><q> <Q><H><wh>בָּרָ֣א<WH1254><h><X>ba·Ra<x><T>created<t><q> <Q><H><wh>אֱלֹהִ֑ים<WH430><h><X>E·lo·Him;<x><T>God<t><q>
```

And Greek (ABP) — note `<E>...<e>` here rather than `<T>...<t>`:

```
<TS>The Creation<Ts><Q><wg>εν<WG1722><E> In<e><q> <Q><wg>αρχή<WG746><E> <FI>the<Fi> beginning<e><q> <Q><wg>εποίησεν ο θεός<WG4160><WG3588><WG2316><E> God made<e><q>
```

HTML tags are also accepted for Bibles but explicitly *not recommended*.

## 4.6 MySword internal link scheme (`href` targets)

For Book/Commentary/Dictionary/Journal, content is plain HTML and links are the main
structure. The `href` value is a **pseudo-scheme**, not a URL:

* **Bible** — `b` + BibleReference: `b43.3.16`, `bJoh 3:16`, `b43.3.16-18`, `bJohn 3:16-18`,
  and with a translation `bJoh 3:16-18/NET`, `b43.3.16.NET`. Optional `&w=1` suffix means
  "open the whole chapter" in a popup. (Ranges plus a translation are not supported in
  numeric form.)
* **Commentary** — `c43.3.16` (same commentary, numeric only, no spaces) or
  `c-TSK Joh 3:16` (`c-` + abbreviation + **space** + reference).
* **Personal Notes** — `n` + BibleReference.
* **Dictionary** — `dWord` or `d-DICT Word` (`d-` + abbreviation + space + word).
* **Journal** — topic link, same space-delimited convention.

Spec example: `<a href='b43.3.16'>John 3:16</a>`.

## 4.7 Real MySword download URLs (all HTTP 200)

Base: `https://mysword-bible.info/download/getfile.php?file=<NAME>`

Bibles: `kjv.bbl.mybible.gz` `kjvlite.bbl.mybible.gz` `kjv2000.bbl.mybible.gz`
`asv.bbl.mybible.gz` `bbe.bbl.mybible.gz` `byz.bbl.mybible.gz` `drc.bbl.mybible.gz`
`dutsv.bbl.mybible.gz` `emtv.bbl.mybible.gz` `erv.bbl.mybible.gz` `gerlut.bbl.mybible.gz`
`gerelb.bbl.mybible.gz` `leb.bbl.mybible.gz` `net.bbl.mybible.gz` `nheb.bbl.mybible.gz`
`rogt.bbl.mybible.gz` `web.bbl.mybible.gz` `webbe.bbl.mybible.gz` `webu.bbl.mybible.gz`
`ylt.bbl.mybible.gz` `ulb.bbl.mybible.gz` `akjv.bbl.mybible.gz` `sblgnt.bbl.mybible.gz`
`alxx.bbl.mybible.gz` `greek.bbl.mybible.gz` `lxx.bbl.mybible.gz` `opv.bbl.mybible.gz`
`pev.bbl.mybible.gz` `easyenglish.bbl.mybible.gz` — and 200+ more.

**Distribution is inconsistent: handle all three forms** — `.bbl.mybible` (bare),
`.bbl.mybible.gz` (gzip), `.bbl.mybible.zip` (zip). Example zip:
`...getfile.php?file=AConservativeVersionReverseInterlinear.bbl.mybible.zip`.

Commentaries/dictionaries/devotionals/books use the same endpoint with `.cmt.mybible`,
`.dct.mybible`, `.jor.mybible`, `.bok.mybible`.

Also live: `https://www.mysword.info/download-mysword/{bibles,bibles-indigenous,commentaries,
devotionals,dictionaries,books,fonts,graphics,languages,migration-tools,3rd-party-modules}`,
and `https://mysword-bible.info/download/getfile.php?file=MySwordMigrationTools-4.0.zip`.

## 4.8 And Bible's MySword-as-SWORD bridge (reference implementation)

And Bible exposes MySword modules to its SWORD-based engine by synthesising a conf
(`app/src/main/java/net/bible/service/sword/mysword/MySwordBook.kt`, branch `current-stable`):

```ini
[<initials>]
Description=...
Abbreviation=...
Category=...
AndBibleMySwordModule=1
AndBibleDbFile=<moduleFileName>
Lang=...
Version=0.0
Encoding=UTF-8
LCSH=Bible
SourceType=OSIS
ModDrv=zText
BlockType=BOOK
Versification=KJVA
# + Feature=GreekDef / Feature=HebrewDef for Strong's dictionaries
# + GlobalOptionFilter=OSISStrongs / OSISMorph when Strong present
```

with the MySword file placed at `./modules/texts/MyBible/<Name>/module.mybible`. Category is
derived **from the file extension's 3-letter tag** (`bbl` -> `Biblical Texts`, `cmt` ->
`Commentaries`, `dct` -> `Lexicons / Dictionaries`, else illegal). `MySwordBookMap.kt`
contains the explicit 1..66 `BibleBook` ordinal list.

## 4.9 MySword licensing

* MySword the **app** is free for personal use; its terms live on `mysword.info`
  (`/mysword-bible-privacy-policy` is the closest live page; `mysword.jp` is dead).
* MyBible (desktop) is a separate product at `bible.zone`.
* **Modules are individually licensed** — the format has no uniform licence. Read
  `Details.Comments` / `EditorialComments`. The KJV example is honest about the UK
  Crown-copyright carve-out. Respect per-module terms.
* The format spec page is published for module authors; the underlying Bible texts carry
  their own licences (usually CC-BY or public domain).

---

# 5. Door43 / unfoldingWord

## 5.1 `catalog.door43.org` is DEAD — but the content is not

| Endpoint | Result |
|---|---|
| `https://catalog.door43.org/` | **DNS failure** (`Name or service not known`) |
| `https://catalog.door43.org/api/catalog.json` | **DNS failure** |
| `https://api.door43.org/` | **DNS failure** |
| `https://api.door43.org/v1/catalog/` | **DNS failure** |
| `https://api.unfoldingword.org/door43.html` (the "Door43 Resource Catalog v3" doc) | **404** (S3 `NoSuchKey`; the doc page is gone) |
| `https://api.unfoldingword.org/` | 200 — the index still lists `door43.html`, `dcs.html`, `td.html`, `ts.html`, `uw.html`, `tk.html`, all of which now 404 |
| `https://door43.org/` | 200 |
| `https://door43.org/api/v1/catalog` | 404 |
| `https://door43.org/en/library/` | 200 (its JS at `door43-library.netlify.app` is 404) |
| `https://git.door43.org/` | 200 — **live Gitea, `{"version":"1.27.3+dcs"}`** |
| `https://cdn.door43.org/` | 200 (`binary/octet-stream`, 0 bytes at `/`) — S3-backed CDN |
| `https://dw.door43.org` | old DokuWiki, read-only (linked from `/en/about/`) |

**The live data store is a Gitea instance.** Verified working endpoints:

* `GET https://git.door43.org/api/v1/version` -> 200
* `GET /api/v1/orgs/{org}/repos?limit=&page=` -> 200
* `GET /api/v1/repos/search?q=...&limit=` -> 200 `{"ok":true,"data":[...]}`
* `GET /api/v1/repos/{owner}/{repo}/contents/{path}` -> 200 (JSON listing)
* `GET /api/v1/repos/{owner}/{repo}/raw/{path}` -> 200 (raw bytes) — **use this**
* `GET /api/v1/repos/{owner}/{repo}/git/trees/HEAD?recursive=1` -> 200 (full file list)

Repo namespace `unfoldingWord` (e.g. `unfoldingWord/fr_ulb`, `unfoldingWord/en_tn`,
`unfoldingWord/en_ubc`, `unfoldingWord/hbo_uhb`).
Current client SDKs: `unfoldingWord/catalog-next-toolkit`,
`unfoldingWord/python-dcs-catalog-client`, `unfoldingWord/dcs` (a Gitea fork).

## 5.2 Two repo generations, both still live

### (a) Whole-Bible repos — `<NN>-<BOOK>.usfm` at repo root

Verified listing of `https://git.door43.org/api/v1/repos/unfoldingWord/fr_ulb/contents/`
(200): `41-MAT.usfm  42-MRK.usfm  43-LUK.usfm  44-JHN.usfm  45-ACT.usfm  46-ROM.usfm
47-1CO.usfm  48-2CO.usfm  49-GAL.usfm  50-EPH.usfm  51-PHP.usfm  52-COL.usfm  53-1TH.usfm
54-2TH.usfm  55-1TI.usfm  56-2TI.usfm  57-TIT.usfm  58-PHM.usfm  59-HEB.usfm  60-JAS.usfm
61-1PE.usfm  62-2PE.usfm  63-1JN.usfm  64-2JN.usfm  65-3JN.usfm  66-JUD.usfm  67-REV.usfm`
plus `LICENSE.md`, `README.md`, `manifest.yaml`.

Naming: `<2-digit USFM book number>-<3-letter USFM book id>.usfm`. UTF-8 plain USFM.
`unfoldingWord/en_ubc` (commentary) instead uses **lowercase** per-book directories
(`1jn/ 2jn 3jn act eph gal gen heb jhn jud luk php rut tit`, plus a `Greek Words/` dir) and
`manifest.yaml`.

Real USFM head from
`https://git.door43.org/api/v1/repos/unfoldingWord/fr_ulb/raw/41-MAT.usfm`
(200, 144,047 bytes) — verbatim:

```
\id MAT
\ide UTF-8
\h Matthieu
\toc1 Matthieu
\toc2 Matthieu
\toc3 mat
\mt Matthieu

\s5
\c 1
\p 
\v 1 Le livre de la généalogie de Jésus-Christ, fils de David, et fils d'Abraham. 
\v 2 Abraham était le père d'Isaac, et Isaac le père de Jacob, et Jacob le père de Juda et de ses frères. 
\v 3 Juda était le père de Pharès et de Zara, ...
\s5
\v 4 Aram était le père d'Aminadab. ...
```

Note the `\s5` section markers and `\p` paragraph markers. **Verses wrap across `\s`
boundaries** (`\v 3` then `\s5` then `\v 4`) — a verse runs from its `\v` to the next
`\v` / `\c` / `\p`.

### (b) Per-book "package" repos — `<lang>_<book>_text_<resource>`

Naming convention, verified via `GET /api/v1/repos/search?q=_ulb` (200):
`<langISO3>_<book3>_text_ulb`, `_text_udb`, plus `<lang>_<book>_ulb` / `_udb` and
`_text_tq` / `_text_tn` / `_text_tw` variants. Examples returned by the API:
`aa_mat_text_ulb`, `aa_mrk_text_ulb`, `fr_ulb`, `ab_tit_text_udb`, `am_1co_text_udb`.

Verified listing of `cap/aa_mrk_text_ulb` (200):

```
01/                (dir)
03/                (dir)
07/                (dir)
LICENSE.md
manifest.json
```

and `/git/trees/HEAD?recursive=1` gives:

```
01
01/01.txt
03
03/26.txt
07
07/11.txt
07/14.txt
LICENSE.md
manifest.json
```

So: **`<NN>/<NN>.txt`** = chapter NN (zero-padded to 2 digits), containing that chapter's
USFM. The translationCore/desk-style repos use the same convention for verses
(`01/01.md`, `01/19.md`, and cross-book relative links such as `../../heb/04/16.md` appear
inside the TSV note bodies). Chapter dirs and verse files are both zero-padded to 2 digits.

## 5.3 The manifests — exact fields

### `manifest.yaml` (whole-Bible repos) — VERIFIED, verbatim from `unfoldingWord/fr_ulb`

```yaml
---

dublin_core:
  conformsto: 'rc0.2'
  contributor:
    - 'Akwesse Confort Clarisse'
    - 'Asaanbil Ndego Ndebang Azure'
    - 'CABTAL'
    - ... 36 entries ...
    - 'Door43 World Missions Community'
  creator: 'Door43 World Missions Community'
  description: 'An unrestricted literal Bible'
  format: 'text/usfm'
  identifier: 'ulb'
  issued: '2017-09-15'
  language:
    identifier: 'fr'
    title: 'français, langue française'
    direction: 'ltr'
  modified: '2017-09-15'
  publisher: 'Door43'
  relation:
    - 'fr/tn'
    - 'fr/tq'
    - 'fr/tw'
  rights: 'CC BY-SA 4.0'
  source:
    -
      identifier: 'English ULB'
      language: 'en'
      version: '7'
  subject: 'Bible'
  title: 'French ULB'
  type: 'bundle'
  version: '7.1'

checking:
  checking_entity:
    - 'Edjanga Jean Jacques, CBC Pastor'
    - ... 10 entries ...
  checking_level: '3'

projects:
  -
    title: 'Matthieu '
    versification: 'ufw'
    identifier: 'mat'
    sort: 40
    path: './41-MAT.usfm'
    categories: [ 'bible-nt' ]
  -
    title: 'Marc '
    versification: 'ufw'
    identifier: 'mrk'
    sort: 41
    path: './42-MRK.usfm'
    categories: [ 'bible-nt' ]
  ...
```

Field notes:

* `conformsto: 'rc0.2'` — the **Resource Container v0.2** spec (`unfoldingWord/rc-schema` is
  the published JSON Schema for it).
* Dublin Core fields present: `contributor` (list), `creator`, `description`, `format`,
  `identifier`, `issued`, `language{identifier,title,direction}`, `modified`, `publisher`,
  `relation` (list), `rights`, `source[]`, `subject`, `title`, `type`, `version`.
* `format` observed: `text/usfm`, `text/markdown`.
* `type` observed: `bundle` (whole-Bible), `help` (commentary/notes).
* `subject` observed: `Bible`, `Bible Commentary`.
* `language.identifier` is **ISO 639-1 here** (`fr`, `en`) — contrast `manifest.json` below,
  which uses 639-3.
* `rights` observed: `CC BY-SA 4.0`.
* `versification: 'ufw'` = **unfoldingWord Format for the Word**, a versification scheme
  distinct from KJV/OSIS.
* `categories` observed: `bible-nt` (there is a matching `bible-ot`).
* `sort` = the book's USFM ordinal, as a **number** (40, 41, 42, ...).
* `identifier` = the 3-letter **USFM** book id (`mat`, `mrk`, `luk`).
* `fr_ulb/manifest.yaml` has a **UTF-8 BOM** — strip it before YAML parsing.
  `en_ubc/manifest.yaml` has no BOM and uses non-indented YAML lists.

### `manifest.json` (per-book package repos) — VERIFIED, verbatim from `cap/aa_mrk_text_ulb`

```json
{
	"package_version": 6,
	"format": "usfm",
	"generator": {
		"name": "ts-desktop",
		"build": "28"
	},
	"target_language": {
		"id": "aa",
		"name": "Afaraf",
		"direction": "ltr"
	},
	"project": {
		"id": "mrk",
		"name": "Mark"
	},
	"type": {
		"id": "text",
		"name": "Text"
	},
	"resource": {
		"id": "ulb",
		"name": "Unlocked Literal Bible"
	},
	"source_translations": [
		{
			"language_id": "en",
			"resource_id": "ulb",
			"checking_level": 3,
			"date_modified": 20160223,
			"version": "4"
		}
	],
	"parent_draft": {},
	"translators": [
		"QATest1",
		"Chris Whitfield",
		"cap"
	],
	"finished_chunks": []
}
```

Note: `target_language.id` is ISO **639-3** (`aa`); `format` includes `usfm`;
`generator.name` observed as `ts-desktop` (older: `tc-desktop`); `parent_draft` is an object
here (older: a repo-name string). JSON is **tab-indented**.

## 5.4 The TSV format — VERIFIED, exact headers and real rows

### Translation Notes — `tn_<BOOK>.tsv`

Verified listing of `unfoldingWord/en_tn` (200): 66 files `tn_GEN.tsv` `tn_EXO.tsv` ...
`tn_REV.tsv`, plus `manifest.yaml`, `media.yaml`, `LICENSE.md`, and
`.gitea/workflows/validate_tn_files.py` (43,554 bytes) — **use that validator as your schema
oracle.**

`https://git.door43.org/api/v1/repos/unfoldingWord/en_tn/raw/tn_REV.tsv` -> 200,
`text/plain`, 566,526 bytes, 1,335 lines (1 header + 1,334 data rows). Header, verbatim:

```
Reference	ID	Tags	SupportReference	Quote	Occurrence	Note
```

7 tab-separated columns. Real rows (verbatim; only the `Note` bodies are abbreviated here):

```
1:1	rkh9		rc://*/ta/man/translate/figs-abstractnouns	...Greek quote...	1	If your language does not use an abstract noun for the idea of **revelation**, you could express the same idea in another way. Alternate translation: [The things that God revealed to Jesus Christ] ...
1:1	kv41		rc://*/ta/man/translate/figs-possession	...Greek quote...	1	This phrase could mean: (1) that this book is a **revelation** that came to Jesus from God. ...
1:1	ik5v		rc://*/ta/man/translate/figs-explicit	...Greek quote...	1	Here, **his servants** refers to people who believe in Jesus Christ ...
1:intro	u1e2								0	# Revelation 1 Chapter Introduction\n\n## Structure and Formatting\n...
front:intro	xx8l								0	# Introduction to Revelation\n\n## Part 1: General Introduction\n...
```

Field semantics:

| Column | Notes |
|---|---|
| `Reference` | `book:verse` (`1:1`, `1:2-3` for a range), `book:intro` for a chapter intro, `front:intro` for book front matter. Books use USFM 3-letter ids (`rev`, `gen`). |
| `ID` | 4-char note id (`rkh9`, `kv41`, `ik5v`, `u1e2`, `xx8l`), unique per file. |
| `Tags` | flag list; empty in `en_tn`. |
| `SupportReference` | `rc://*/ta/man/translate/<topic>` — a **resource-container URI**; `rc://*/tw/dict/bible/kt/<word>` for key terms. The `*` is the resource id. |
| `Quote` | the source-language (Greek/Hebrew) snippet, NFC. |
| `Occurrence` | `0` = applies to the whole reference; `1..n` = which occurrence of `Quote` in that verse. |
| `Note` | Markdown with **literal two-character `\n` escapes** (not real newlines!) and links like `[1:1-20](../01/01.md)`, `[chapter 1](../01/01.md)`, `[Hebrews 4:16](../../heb/04/16.md)`. **You must unescape `\n` to newlines and rewrite the relative `.md` links to your own book paths.** |

### Translation Questions — `tq_<BOOK>.tsv`

`unfoldingWord/en_tq` has 66 `tq_*.tsv` files. Verified
`https://git.door43.org/api/v1/repos/unfoldingWord/en_tq/raw/tq_MRK.tsv` -> 200,
47,414 bytes. Header, verbatim:

```
Reference	ID	Tags	Quote	Occurrence	Question	Response
```

7 columns — **no `SupportReference`, but `Question` + `Response` instead of `Note`.**
Real rows, verbatim:

```
1:2-3	a4zc			0	What did the prophet Isaiah predict would happen before the Lord came?	Isaiah predicted that God would send a messenger, a voice of someone calling out in the wilderness, to prepare the way of the Lord.
1:4	g2v6			0	What did John come preaching?	John came preaching a baptism of repentance for the forgiveness of sins.
3:6	acwq			0	What did the Pharisees do when Jesus healed the man?	The Pharisees went out and plotted to put Jesus to death.
```

### Key Terms

`unfoldingWord/en_tw` (966 entries) uses `bible/config.yaml` plus one Markdown file per term:
`bible/kt/abomination.md`, `bible/kt/adoption.md`, `bible/kt/adultery.md`, ...

### Parser rules

* Delimiter is a **literal TAB**, UTF-8, LF line endings, **no quoting** — use
  `csv.reader(..., delimiter='\t', quoting=csv.QUOTE_NONE)`. `QUOTE_NONE` is essential: the
  `Note`/`Response` fields are full of `"` characters.
* **The first line is the header** — use it, do not hardcode positions.
* The column set varies by resource type. Probe the header.
* Fields may in principle contain tabs; the reference implementations split on tab and cap
  the count (`validate_tn_files.py` / `validate_tq_files.py` are the authority).
* Existing machine-readable parsers: `unfoldingWord/usfm-js`,
  `unfoldingWord/usfm-js-wrapper`, `unfoldingWord/uw-tsv-parser` ("A Parser and Converter for
  Lossless TSV"), `unfoldingWord/tsv-groupdata-parser`.

## 5.5 Door43 licensing

* Everything on door43.org is CC BY-SA 4.0 by default — stated on every page footer:
  *"The content of this page ... from Door43 is licensed under a Creative Commons
  Attribution-ShareAlike 4.0 International License"* — and per-resource `rights:` in
  `manifest.yaml` (verified `rights: 'CC BY-SA 4.0'`).
* `checking_level` is 0-3 (translation/checking maturity); `checking_entity` lists checkers;
  `source[]` records the upstream resource, its language, and its version.
* Policy pages: `/en/legal/`, `/en/copyright-and-licensing/`,
  `/en/copyright-violations/`, `/en/translation-guidelines/`, `/en/statement-of-faith/`.
* Resource Container JSON Schema: `unfoldingWord/rc-schema` ("JSON Schema for Resource
  Container v0.2").
* `unfoldingWord/dw_redirects` and `dw.door43.org` hold the legacy DokuWiki content.

---

# 6. BibleTime / Zefania XML ("zformat", "zModules") — brief

## 6.1 What "zformat" actually was

BibleTime 1.x had a backend that read **Zefania XML** modules, implemented in
`src/frontend/zformat.cpp` (plus `zrend.cpp` for rendering), and it was **removed in
BibleTime 2.0**. I could not retrieve the source: `bibletime/bibletime` on GitHub is now a
JavaScript re-write (its `src/frontend/` contains `.js`), and the
`bibletime/historic-bibletime-svn` mirror (58,315 paths) contains **no** `zformat*`,
`zcom*` or `zrend*` file. `inventingrobots.org` and `cgit.kde.org` do not resolve. So the
BibleTime wrapper is unavailable — but the *format* it wrapped is fully documented and
available.

**Zefania XML** was created by the Theological Initiative Freiburg (Jens Grabner) and is the
basis for MyBible. It is a plain XML Bible text — trivially parseable.

## 6.2 Structure

No namespace (elements are uppercase, unprefixed). The schema hint is embedded as
`xsi:noNamespaceSchemaLocation="zef2005.xsd"`.

```xml
<?xml version="1.0" encoding="utf-8"?>
<XMLBIBLE xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:noNamespaceSchemaLocation="zef2005.xsd"
          biblename="Albanian Version" status="v" version="2.0.1.18"
          type="x-bible" revision="0">
  <INFORMATION>
    <title>Albanian Version</title>
    <creator></creator>
    <subject>The Holy Bibe</subject>
    <description>Albanian</description>
    <publisher>Free Bible Software Group</publisher>
    <contributors>
       The Unbound Bible
       Biola University: Administrative Computing
       ...
    </contributors>
    <date>2009-01-20</date>
    <format>Zefania XML Bible Markup Language</format>
    <identifier>ALB1</identifier>
    <source>ftp://unboundftp.biola.edu/pub/albanian_utf8.zip</source>
    <language>ALB</language>
    <coverage>provide the bible to the world</coverage>
    <rights></rights>
    <type />
  </INFORMATION>
  <BIBLEBOOK bnumber="1" bname="1 Mose" bsname="1Mo">
    <CHAPTER cnumber="1">
      <VERS vnumber="1"> Në fillim Perëndia krijoi qiejt dhe tokën.</VERS>
      <VERS vnumber="2"> Toka ishte pa trajtë, ...</VERS>
      ...
```

`<INFORMATION>` is a **Dublin Core** block.

* Root `<XMLBIBLE>`: `biblename`, `status` (`v`), `version`, `type` (`x-bible`), `revision`.
* `<BIBLEBOOK>`: `bnumber` (**1-based book ordinal**), `bname` (localised name), `bsname`
  (short name).
* `<CHAPTER>`: `cnumber`.
* `<VERS>`: `vnumber`. **Content is XML-escaped** (`&quot;`, `&amp;`) per normal XML rules.

## 6.3 Schemas

`zef2005.xsd` and `zef2014.xsd` (Tom Baccei / Wolfgang Schultz, GPL). The 2014 schema
(`https://raw.githubusercontent.com/kohelet-net-admin/zefania-xml-bibles/master/Schema/zef2014.xsd`,
16,281 bytes, HTTP 200) declares only **8 elements** —
`xmlbible, biblebook, chapter, verse, prolog, headline, emphasis, remark` — and **7
attributes** — `book, cn, id, ix, language, vn, xd`. Note the 2014 revision uses
`book`/`cn`/`vn` instead of `bnumber`/`cnumber`/`vnumber`, and adds `language`, `id`, `ix` on
the root. **Parse both dialects**; the 2005 dialect is far more common in the wild.

## 6.4 Where to get real Zefania modules

`https://github.com/kohelet-net-admin/zefania-xml-bibles` (HTTP 200) — 547 entries, all as
**unzipped** XML (not inside zips), which is ideal for test fixtures:

```
Bibles/<LANGCODE>/<Name>/SF_<YYYY-MM-DD>_<LANG>_<ID>_(<TITLE>).xml
Dictionaries/...
Schema/zef2005.xsd
Schema/zef2014.xsd
Schema/iso639_codes.xml
Bibles/downloads.csv          # index of all download URLs
Dictionaries/downloads.csv
```

Verified live sample:
`https://raw.githubusercontent.com/kohelet-net-admin/zefania-xml-bibles/master/Bibles/ALB/Albanian%20Version/SF_2009-01-20_ALB_ALB1_(ALBANIAN%20VERSION).xml`
-> 200, 5,518,988 bytes. Upstream sources: `http://sourceforge.net/projects/zefania-sharp/files/`
and `http://bgfdb.de/zefania.de/`.

## 6.5 "zpython" and MySword-compatible export

* **"zpython" is not a document format** — it is the Python-scripting hook inside the
  **Zefania Bible / Online Bible** desktop app family (forks: `apachesep/Zefania-Bible`,
  `NothinRandom/Zefania-Bible`). It post-processes search results and implements extra
  plugins; it does not define a file layout. If your target is "Zefania plus a Python
  plugin", emit Zefania XML (§6.2) and let the plugin run.
* **MySword-compatible export** is fully specified in §4: write a SQLite DB with `Details`
  (the 18 columns listed) plus `Bible(Book, Chapter, Verse, Scripture)` plus
  `CREATE UNIQUE INDEX bible_key ON Bible (Book, Chapter, Verse)`, name the file
  `<Name>.bbl.mybible`, and convert your markup to MySword tags (§4.5) or to plain HTML/RTF.
  `Book` must be the **1..66 Protestant ordinal**, not a USFM id.

## 6.6 BibleTime itself (current)

BibleTime >= 2.0 is **SWORD-only** and has no native format of its own; the
zModules/zformat backend is gone. `https://www.bibletime.org/` and `https://bibletime.info/`
are live (the .org site served a Korean-language page in my test — language negotiation).
Repo `https://github.com/bibletime/bibletime`, branch `master`, 590 tree entries (its
`src/backend` tree is TypeScript/JS now).

---

# 7. Plain text, CSV, TSV, PDF

## 7.1 `.txt`

* eBible `readaloud` (`https://ebible.org/Scriptures/eng-web_readaloud.zip`): *"Plain text
  canon only chapter files"*, one file per chapter, canon only (apocrypha excluded).
  Filenames follow the same `<NN>-<ABBR>` scheme as their USFM zip (whose first member is
  `00-FRT/eng-web.usfm`).
* BibleWorks VPL (`https://ebible.org/Scriptures/eng-web_vpl.zip`): "BibleWorks import (VPL)
  + SQL". VPL is verse-per-line — one line per verse in versification order, with a header
  block naming version/book/chapter. **There is no book/chapter delimiter**, so you must
  consume the header or count verses against a versification table.
* Plain SWORD `ModDrv=RawText` modules: one text file per testament, verse-marked per the
  module's `SourceType`. Legacy `Encoding=Latin-1` modules are cp1252.
* Encoding: assume UTF-8, fall back to cp1252. Strip a BOM if present. Watch for `\r\n` vs
  `\n` and trailing-space verse markers.

## 7.2 CSV

No Bible-specific standard. Realistic shapes:

* Rows = verses; columns `book, chapter, verse, text` (optionally `strongs`, `book_name`,
  `translation`, `license`, `footnotes`).
* Dialect is a mess: delimiter `,` vs `;` vs tab; quoting `"` vs `'`; embedded newlines; BOM;
  a leading `sep=,` line. Sniff with `csv.Sniffer` on the first 64 KB and hard-fall-back to
  tab if the header has no comma.
* `sep=;` plus cp1252 is the classic Excel-export trap.
* For a *defined* shape prefer the e-Sword `.bblx` SQLite or the Door43 TSV, both of which
  have a fixed schema.

## 7.3 TSV

Two real, fixed schemas exist and are already covered:

* **Door43 `tn_*.tsv` / `tq_*.tsv`** — 7 columns, tab-delimited, `QUOTE_NONE`, header row,
  literal `\n` escapes in the last column (§5.4).
* **MySword `VerseRules`** — tab-separated 4-field rules inside the `Details` table (§4.4).

There is **no** Bible-text TSV standard. The BibleNLP eBible corpus projects emit
JSON/CSV, not TSV.

## 7.4 PDF — libraries available in this environment

Verified with `importlib.metadata` on this machine (Python 3.13):

| Package | Version | Status |
|---|---|---|
| `pdfminer.six` | **20260107** | installed |
| `pdfplumber` | **0.11.10** | installed |
| `charset-normalizer` | 3.4.2 | installed (dependency) |
| `pypdf` | — | not installed |
| `PyMuPDF` (`fitz`) | — | not installed |
| `camelot-py` | — | not installed |
| `tabula-py` | — | not installed |
| `pikepdf` | — | not installed |
| `ocrmypdf` | — | not installed |
| `reportlab` | — | not installed |
| `tika` | — | not installed |

`pdfplumber.__version__ == '0.11.10'`, `pdfminer.__version__ == '20260107'`.

**You already have the right two.**

* **`pdfminer.six`** — the low-level engine. Use for layout-faithful text extraction
  (`LAParams`), character-level bounding boxes, and for the
  `pdfminer.pdfdocument` / `pdfpage` / `pdfinterp` / `converter` layers when subclassing.
  `high_level.extract_text()` for the simple case.
* **`pdfplumber`** — the right default for Bible PDFs. Wraps pdfminer and adds
  `page.extract_text(layout=True)`, `page.extract_words()`, `page.extract_text_lines()`,
  `page.crop(x0, top, x1, bottom)`, `page.chars` / `.rects` / `.lines` / `.images`,
  `page.find_tables()` -> `page.extract_table()` / `extract_tables()`, `page.filter(fn)`.
  Bible PDFs are heavily columnar (two columns, superscript verse numbers, Strong's numbers,
  red letters encoded as colour runs), so the practical recipe is
  `extract_text_lines()` + `crop()` + `page.chars` (to discriminate font/size/colour of
  Strong's numbers and red letters).
* Also worth installing if you may:
  * **`pypdf`** (pure Python, Apache-2.0/BSD) — fast page splitting, metadata, easiest
    per-page text without layout mode; good for pre-filtering.
  * **`PyMuPDF`** (AGPL) — much faster rasterisation plus built-in table/image extraction,
    but **AGPL is a licensing decision you must make deliberately**.
  * **`camelot-py`** (MIT) / **`tabula-py`** (Apache-2.0, needs a JVM) — if your PDFs have
    ruled tables (many study Bibles do).
  * **`ocrmypdf` / `tesseract`** — only for scanned PDFs.
* **Cheapest path: prefer archive.org's text companions.** archive.org publishes `*_djvu.txt`
  (plain OCR text) and `*_chocr.html.gz` next to every PDF. Verified:
  `https://archive.org/download/e-sword_guide-2014/e-sword_guide_djvu.txt` -> 200,
  472,546 bytes, `text/plain`, first bytes
  `"e-Sword User's Guide \nRevision: 8/1/2014 \n\ne-Sword 10.4 \n\n\nBy: Rick Meyers \n"`.
  The same pattern exists for the Bible collections, e.g.
  `https://archive.org/details/bible-collection` with files
  `American King James Version_text.pdf`, `..._djvu.txt`, `..._page_numbers.json`.
  **Do this before writing any PDF code.**

---

# 8. Consolidated verified URL table

Every row was fetched with a browser `User-Agent` on 2026-09-26.

## SWORD

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://crosswire.org/ftpmirror/pub/sword/packages/` | 200 | `text/html` 1302 | `<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">` |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/` | 200 | `text/html` | `Index of /ftpmirror/pub/sword/packages/rawzip` (463 `.zip`) |
| `https://crosswire.org/ftpmirror/pub/sword/packages/win/` | 200 | `text/html` | `Index of .../packages/win` (235 `.zip`) |
| `https://crosswire.org/ftpmirror/pub/sword/packages/mac/` | 200 | `text/html` | `Index of .../packages/mac` (229 `.zip`) |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/KJV.zip` | 200 | `application/zip` 4,026,621 | `PK` + `modules/texts/ztext/kjv/nt.bzs` |
| `https://crosswire.org/ftpmirror/pub/sword/packages/win/KJV.zip` | 200 | `application/zip` 4,724,029 | `PK` + `DATA.TAG`, `SETUP.INI` (installer stub) |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/Barnes.zip` | 200 | `application/zip` 5,812,827 | `PK` |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/2BabDict.zip` | 200 | `application/zip` 16,960 | `PK` |
| `https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/StrongsGreek.zip` | 200 | `application/zip` 561,494 | `PK` |
| `https://crosswire.org/ftpmirror/pub/sword/masterRepoList.conf` | 200 | `text/plain` 1,691 | `[Repos]` then `20220529224400=HTTPSPackagePreference=CrossWire|crosswire.org|/ftpmirror/pub/sword/raw` |
| `https://crosswire.org/ftpmirror/pub/sword/raw/` | 200 | `text/html` 2,319 | `locales.d/ mods.d.tar.gz mods.d/ modules/ packages/ tmp/ zipup.sh` |
| `https://crosswire.org/ftpmirror/pub/sword/raw/modules/texts/ztext/kjv/` | 200 | `text/html` | `nt.bzs nt.bzv nt.bzz ot.bzs ot.bzv ot.bzz` |
| `https://crosswire.org/ftpmirror/pub/sword/raw/mods.d/2babdict.conf` | 200 | `text/plain` 360 | `[2BabDict]` then `DataPath=./modules/lexdict/rawld/2babdict/2babdict` then `ModDrv=RawLD` |
| `https://crosswire.org/ftpmirror/pub/sword/raw/mods.d/strongsgreek.conf` | 200 | `text/plain` 1,593 | `## Sword module configuration file` |
| `https://crosswire.org/ftpmirror/pub/sword/raw/modules/lexdict/` | 200 | `text/html` | `rawld/ rawld4/ zld/` |
| `https://crosswire.org/ftpmirror/pub/sword/frontend/win32/` | 200 | `text/html` 2,106 | `latest-is-v1.7.3 v0.0/ v1.0/ v1.2/ v1.4/ v1.5/ v1.7/` |
| `https://crosswire.org/ftpmirror/pub/sword/frontend/win32/v1.7/` | 200 | `text/html` 1,229 | `sword-starter-win32-1.7.3.exe`, `sword-win32-1.7.3.exe` |
| `https://crosswire.org/ftpmirror/pub/sword/updates/` | **404** | | |
| `https://ftp.sword-tools.org/pub/sword/packages/` | **ERR** | | DNS `Name or service not known` |
| `https://wiki.crosswire.org/DevTools:conf_Files` | 200 | `text/html` | `DevTools:conf Files - CrossWire Bible Society` |
| `https://wiki.crosswire.org/Zipped_modules` | 200 | `text/html` | `Zipped modules - CrossWire Bible Society` |
| `https://wiki.crosswire.org/DevTools:Modules` | 200 | `text/html` | `DevTools:Modules - CrossWire Bible Society` |
| `https://wiki.crosswire.org/File_Formats` | 200 | `text/html` | `File Formats - CrossWire Bible Society` |
| `https://raw.githubusercontent.com/crosswire/jsword/master/src/main/java/org/crosswire/jsword/book/sword/ZVerseBackend.java` | 200 | `text/plain` 21,407 | `/* A backend to read compressed data verse based files...` |

## eBible

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://ebible.org/` | 200 | `text/html` | eBible.org home |
| `https://ebible.org/find/` | 200 | `text/html` | `Bible List` |
| `https://ebible.org/find/index.php` | 200 | `text/html` | ~1,400 `details.php?id=...` links |
| `https://ebible.org/find/details.php?id=eng-web` | 200 | `text/html` | `World English Bible Classic` |
| `https://ebible.org/find/details.php?id=302` | 200 | `text/html` | numeric legacy id resolves |
| `https://ebible.org/Scriptures/dir.php` | 200 | `text/html` | `File Directory` + `<id>_<format>.zip` table |
| `https://ebible.org/Scriptures/changelog.txt` | 200 | `text/plain` 73,067 | `This is a log of` (dated per-translation change log) |
| `https://eBible.org/sword/zip/engweb2025eb.zip` | 200 | `application/zip` 3,953,791 | `PK` + `mods.d/engweb2025eb.conf` |
| `https://ebible.org/sword/zip/` | 200 | `text/html` | `Index of /sword/zip/` with `aai2009eb.zip` etc. |
| `https://ebible.org/sword/` | 200 | `text/html` | `Index of /sword/` with `locales.d/`, `modules/` |
| `https://ebible.org/Scriptures/eng-web_usfx.zip` | 200 | `application/zip` 3,299,041 | `PK` + `BookNames.xml` |
| `https://ebible.org/Scriptures/eng-web_usfm.zip` | 200 | `application/zip` 3,244,556 | `PK` + `00-FRT/eng-web.usfm` |
| `https://ebible.org/osisCore.2.1.1.xsd` | 200 | `application/octet-stream` 94,067 | `<?xml version="1.0" encoding="UTF-8"?>` + `xs:schema targetNamespace="http://www.bibletechnologies.net/2003/OSIS/namespace"` |
| `https://ebible.org/osis/` | 200 | `text/html` | `OSIS - Open Scriptural Information Standard` |
| `https://ebible.org/usfx/` | 200 | `text/html` | `Unified Scripture Format XML (USFX)` |
| `https://ebible.org/bible/gbf.htm` | 200 | `text/html` | `General Bible Format Tagging Specification` |
| `https://ebible.org/robots.txt` | 200 | `text/plain` 55 | `User-agent: Baiduspider` |
| `https://ebible.org/Scriptures/catalog.json` | **404** | | nginx 404 |
| `https://ebible.org/find/catalog.json` | **404** | | nginx 404 |
| `https://ebible.org/Scriptures/collections.json` | **404** | | nginx 404 |
| `https://ebible.org/Scriptures/eng-scripture-2020.zip` | **404** | | nginx 404 |
| `https://ebible.org/Scriptures/eng-web.zip` | **404** | | nginx 404 |
| `https://ebible.org/Scriptures/eng-web/manifest.xml` | **404** | | nginx 404 |
| `https://ebible.org/find/shortcodes.php` | **404** | | nginx 404 |
| `http://archive.org/wayback/available?url=ebible.org/Scriptures/catalog.json` | 200 | `application/json` 71 | `{"url": "ebible.org/Scriptures/catalog.json", "archived_snapshots": {}}` |

## e-Sword

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://www.e-sword.com/` | 200 | `text/html` 12,852 | `<!DOCTYPE html>` + `<title>e-Sword: Free Bible Study for the PC</title>` |
| `https://www.e-sword.com/downloads.html` | 200 | `text/html` 10,257 | links `files/e-sword_1520_setup.exe` |
| `https://www.e-sword.com/files/e-sword_1520_setup.exe` | 200 | `application/octet-stream` 57,136,261 | `MZ` (PE / InstallShield stub) |
| `https://www.e-sword.com/faq.html` | 200 | `text/html` 8,701 | e-Sword FAQ |
| `https://www.e-sword.com/tutorial.html` | 200 | `text/html` 16,722 | e-Sword tutorial |
| `https://www.e-sword.com/history.html` | 200 | `text/html` 20,265 | release history |
| `https://www.e-sword.com/changes.html` | 200 | `text/html` 6,365 | change log |
| `https://www.e-sword.com/android/` | 200 | `text/html` 9,919 | e-Sword for Android |
| `https://www.e-sword.com/download/` | **404** | | `e-Sword | Error 404` |
| `https://www.e-sword.com/modules/` | **404** | | `e-Sword | Error 404` |
| `https://www.e-sword.com/esources.xml` | **404** | | `e-Sword | Error 404` |
| `https://www.e-sword.com/bibles.xml` | **403** | | `e-Sword | Error 403` |
| `https://www.e-sword.com/files/` | **403** | | `e-Sword | Error 403` |
| `https://archive.org/download/MizoE-swordBible/Mizo.zip` | 200 | `application/zip` 1,952,262 | `PK` + `Mizo.bblx` (a SQLite DB) |
| `https://archive.org/download/e-sword_guide-2014/e-sword_guide_djvu.txt` | 200 | `text/plain` 472,546 | `e-Sword User's Guide` |
| `https://raw.githubusercontent.com/buric/e-sword-bblx-generator/main/README.md` | 200 | `text/plain` 3,879 | `# How to create a Bible module for e-Sword` |
| `https://raw.githubusercontent.com/GoodOlClint/e-Sword9Converter/master/README.md` | 200 | `text/plain` 4,751 | `# eSword 9 Converter` + the 8.x-to-9.x extension table |
| `http://www.biblesupport.com/e-sword-downloads/` | 200 | `text/html` 8,701-ish | e-Sword Downloads index (HTTP only; HTTPS = `WRONG_VERSION_NUMBER`) |
| `https://www.biblesupport.com/` | **ERR** | | `SSL: WRONG_VERSION_NUMBER` |
| `https://www.eswordlibrary.com/wp-json/download-monitor/v1` | 200 | `application/json` | route list incl. `/download-monitor/v1/downloads` |
| `https://www.eswordlibrary.com/wp-json/download-monitor/v1/downloads?per_page=20` | **403** | | `{"code":"rest_forbidden","message":"Authentication failed"}` |

## MySword

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://www.mysword.info/` | 200 | `text/html` | `MySword - Free Android Bible` |
| `https://www.mysword.info/modules-format` | 200 | `text/html` | `MySword Modules' Format` (the spec) |
| `https://www.mysword.info/download-mysword/bibles` | 200 | `text/html` 144,648 | ~260 `getfile.php?file=*.bbl.mybible[.gz|.zip]` links |
| `https://mysword-bible.info/download/getfile.php?file=kjvlite.bbl.mybible.gz` | 200 | `application/x-gzip` 1,874,198 | `1f 8b 08 08` (gzip); gunzips to a 5,668,864-byte SQLite DB |
| `https://mysword.jp/` | **ERR** | | DNS `Name or service not known` |
| `https://sites.google.com/site/myswordjp/` | 200 | `text/html` | Google sign-in wall |
| `https://raw.githubusercontent.com/AndBible/and-bible/current-stable/app/src/main/java/net/bible/service/sword/mysword/MySwordBook.kt` | 200 | `text/plain` 17,930 | `/* Copyright (c) 2022-2023 Martin Denham...` |
| `https://raw.githubusercontent.com/AndBible/and-bible/current-stable/app/src/main/java/net/bible/service/sword/mysword/MySwordBookMap.kt` | 200 | `text/plain` 2,400 | `val books = arrayOf(BibleBook.GEN, ...)` |

## Door43

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://git.door43.org/` | 200 | `text/html` | Gitea login page |
| `https://git.door43.org/api/v1/version` | 200 | `application/json` 24 | `{"version":"1.27.3+dcs"}` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/fr_ulb/contents/` | 200 | `application/json` | 27 `41-MAT.usfm`-style entries + `manifest.yaml` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/fr_ulb/raw/manifest.yaml` | 200 | `text/plain` 5,755 | BOM + `dublin_core:` / `conformsto: 'rc0.2'` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/fr_ulb/raw/41-MAT.usfm` | 200 | `text/plain` 144,047 | `\id MAT` |
| `https://git.door43.org/api/v1/repos/cap/aa_mrk_text_ulb/raw/manifest.json` | 200 | `text/plain` 620 | `{"package_version": 6, "format": "usfm", ...` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/en_tn/raw/tn_REV.tsv` | 200 | `text/plain` 566,526 | `Reference\tID\tTags\tSupportReference\tQuote\tOccurrence\tNote` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/en_tq/raw/tq_MRK.tsv` | 200 | `text/plain` 47,414 | `Reference\tID\tTags\tQuote\tOccurrence\tQuestion\tResponse` |
| `https://git.door43.org/api/v1/repos/unfoldingWord/en_ubc/raw/manifest.yaml` | 200 | `text/plain` 7,837 | `dublin_core:` (no BOM) |
| `https://git.door43.org/api/v1/repos/search?q=_ulb&limit=20` | 200 | `application/json` | `{"ok":true,"data":[...]}` |
| `https://door43.org/` | 200 | `text/html` 7,465 | Door43 home |
| `https://door43.org/en/library/` | 200 | `text/html` 8,109 | `Library` |
| `https://door43.org/api/v1/catalog` | **404** | | `Page Not Found` |
| `https://cdn.door43.org/` | 200 | `binary/octet-stream` 0 | (empty; S3 bucket root) |
| `https://catalog.door43.org/` | **ERR** | | DNS `Name or service not known` |
| `https://api.door43.org/` | **ERR** | | DNS `Name or service not known` |
| `https://api.unfoldingword.org/` | 200 | `text/html` | `uW and Door43 API Information` index |
| `https://api.unfoldingword.org/door43.html` | **404** | | S3 `NoSuchKey` (catalog v3 doc removed) |
| `https://api.unfoldingword.org/ts/` | **404** | | S3 `NoSuchKey` |
| `https://raw.githubusercontent.com/unfoldingWord/catalog-next-toolkit/main/README.md` | 200 | `text/plain` 3,382 | `# catalog-next-toolkit` |

## Zefania / BibleTime

| URL | Status | Content-Type / bytes | First bytes |
|---|---|---|---|
| `https://raw.githubusercontent.com/kohelet-net-admin/zefania-xml-bibles/master/Schema/zef2014.xsd` | 200 | `text/plain` 16,281 | BOM + `<?xml version="1.0"?>` + `xsd:schema` |
| `https://raw.githubusercontent.com/kohelet-net-admin/zefania-xml-bibles/master/Bibles/ALB/Albanian%20Version/SF_2009-01-20_ALB_ALB1_(ALBANIAN%20VERSION).xml` | 200 | `text/plain` 5,518,988 | BOM + `<?xml version="1.0" encoding="utf-8"?>` + `<XMLBIBLE ... biblename="Albanian Version" ...>` |
| `https://github.com/kohelet-net-admin/zefania-xml-bibles` | 200 | `text/html` | 547 entries (via the trees API) |
| `https://raw.githubusercontent.com/bibletime/bibletime/master/src/frontend/zformat.cpp` | **404** | | not in repo (JS re-write) |
| `https://api.github.com/repos/bibletime/historic-bibletime-svn/git/trees/master?recursive=1` | 200 | `application/json` 20,070,516 | 58,315 paths, **no** `zformat`/`zcom`/`zrend` |
| `https://www.bibletime.org/` | 200 | `text/html` | served a Korean-language page (lang negotiation) |
| `https://bibletime.info/` | 200 | `text/html` | BibleTime home |
| `https://inventingrobots.org/...` | **ERR** | | DNS `Name or service not known` |
| `https://cgit.kde.org/bibletime.git/plain/src/frontend/zformat.cpp` | **ERR** | | DNS `Name or service not known` |

---

## Appendix: reproducible verification

The verification helper used throughout (drop in `/tmp`):

```python
import urllib.request
def get(url, n=400):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=25)
    d = r.read(n)
    print(r.status, r.headers.get('Content-Type'), d[:200])
```

Note: `www.e-sword.com` and `www.biblesupport.com` need a lenient TLS context
(`ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE`)
or plain HTTP respectively.
