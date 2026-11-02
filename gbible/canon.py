"""Canonical Bible structure: books, versification schemes, reference parsing.

The reference model here is the load-bearing piece of the whole application.
The key insight (see docs/ARCHITECTURE.md) is that a resource's position is a
*milestone cursor*, and two resources can only be linked when their milestone
types intersect.  Everything about verses, chapters and books lives here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, NamedTuple

# --------------------------------------------------------------------------
# Books
# --------------------------------------------------------------------------
# (osis_id, usfm_id, name, short_name, group, ordinal, [abbreviations...])
# group: OT | NT | AP (apocrypha/deuterocanonical)

_P66 = [
    ("Gen", "GEN", "Genesis", "Gen", "OT", 1, ["ge", "gen", "genesi", "genesis", "gn"]),
    ("Exod", "EXO", "Exodus", "Exod", "OT", 2, ["ex", "exo", "exod", "exodus", "exo.", "exod."]),
    ("Lev", "LEV", "Leviticus", "Lev", "OT", 3, ["le", "lev", "levi", "levit", "leviticus"]),
    ("Num", "NUM", "Numbers", "Num", "OT", 4, ["nu", "num", "numb", "numbers"]),
    ("Deut", "DEUT", "Deuteronomy", "Deut", "OT", 5, ["de", "deu", "deut", "deuteronomy", "dt"]),
    ("Josh", "JOSH", "Joshua", "Josh", "OT", 6, ["jos", "josh", "joshu", "joshua"]),
    ("Judg", "JDG", "Judges", "Judg", "OT", 7, ["jdg", "judg", "judge", "judges"]),
    ("Ruth", "RUT", "Ruth", "Ruth", "OT", 8, ["ru", "ruth"]),
    ("1Sam", "1SA", "1 Samuel", "1Sam", "OT", 9, ["1sa", "1sam", "1 sam", "1sam.", "1samuel", "1samuel", "1 sm", "i sam", "1s", "1samuel", "first samuel"]),
    ("2Sam", "2SA", "2 Samuel", "2Sam", "OT", 10, ["2sa", "2sam", "2 sam", "2sam.", "2samuel", "2 sm", "ii sam", "2s", "second samuel"]),
    ("1Kgs", "1KI", "1 Kings", "1Kgs", "OT", 11, ["1ki", "1kgs", "1 kgs", "1k.", "1kings", "1 kings", "1 ki", "i kgs", "1 k", "first kings"]),
    ("2Kgs", "2KI", "2 Kings", "2Kgs", "OT", 12, ["2ki", "2kgs", "2 kgs", "2k.", "2kings", "2 kings", "2 ki", "ii kgs", "2 k", "second kings"]),
    ("1Chr", "1CH", "1 Chronicles", "1Chr", "OT", 13, ["1ch", "1chr", "1 chr", "1chr.", "1chron", "1 chronicles", "1 ch", "i chr", "1 c", "first chronicles"]),
    ("2Chr", "2CH", "2 Chronicles", "2Chr", "OT", 14, ["2ch", "2chr", "2 chr", "2chr.", "2chron", "2 chronicles", "2 ch", "ii chr", "2 c", "second chronicles"]),
    ("Ezra", "EZR", "Ezra", "Ezra", "OT", 15, ["ezr", "ezra"]),
    ("Neh", "NEH", "Nehemiah", "Neh", "OT", 16, ["neh", "nehemi", "nehemiah"]),
    ("Esth", "EST", "Esther", "Esth", "OT", 17, ["est", "esth", "esther", "esther"]),
    ("Job", "JOB", "Job", "Job", "OT", 18, ["job"]),
    ("Ps", "PSA", "Psalms", "Ps", "OT", 19, ["ps", "psa", "psalm", "psalms", "pss"]),
    ("Prov", "PRO", "Proverbs", "Prov", "OT", 20, ["pr", "pro", "prov", "proverb", "proverbs", "prv"]),
    ("Eccl", "ECC", "Ecclesiastes", "Eccl", "OT", 21, ["ec", "ecc", "eccl", "eccl.", "eccles", "ecclesiastes", "qoh"]),
    ("Song", "SNG", "Song of Solomon", "Song", "OT", 22, ["ss", "sng", "song", "songs", "song of songs", "canticles", "cant"]),
    ("Isa", "ISA", "Isaiah", "Isa", "OT", 23, ["is", "isa", "isai", "isaiah", "isaias"]),
    ("Jer", "JER", "Jeremiah", "Jer", "OT", 24, ["je", "jer", "jere", "jerem", "jeremiah", "jrm"]),
    ("Lam", "LAM", "Lamentations", "Lam", "OT", 25, ["la", "lam", "lament", "lamentations"]),
    ("Ezek", "EZK", "Ezekiel", "Ezek", "OT", 26, ["ez", "ezk", "ezek", "ezekiel", "eze"]),
    ("Dan", "DAN", "Daniel", "Dan", "OT", 27, ["da", "dan", "dani", "daniel", "dnl"]),
    ("Hos", "HOS", "Hosea", "Hos", "OT", 28, ["ho", "hos", "hose", "hosea"]),
    ("Joel", "JOL", "Joel", "Joel", "OT", 29, ["jl", "jol", "joel"]),
    ("Amos", "AMO", "Amos", "Amos", "OT", 30, ["am", "amo", "amos"]),
    ("Obad", "OBA", "Obadiah", "Obad", "OT", 31, ["ob", "oba", "obad", "obad.", "obadiah"]),
    ("Jonah", "JON", "Jonah", "Jonah", "OT", 32, ["jon", "jona", "jonah"]),
    ("Mic", "MIC", "Micah", "Mic", "OT", 33, ["mi", "mic", "mica", "micah"]),
    ("Nah", "NAH", "Nahum", "Nah", "OT", 34, ["na", "nah", "nahum"]),
    ("Hab", "HAB", "Habakkuk", "Hab", "OT", 35, ["hb", "hab", "haba", "habak", "habakkuk"]),
    ("Zeph", "ZEP", "Zephaniah", "Zeph", "OT", 36, ["ze", "zep", "zeph", "zephaniah"]),
    ("Hag", "HAG", "Haggai", "Hag", "OT", 37, ["ha", "hag", "haggai"]),
    ("Zech", "ZEC", "Zechariah", "Zech", "OT", 38, ["zc", "zech", "zechar", "zechariah"]),
    ("Mal", "MAL", "Malachi", "Mal", "OT", 39, ["ml", "mal", "malachi"]),
    ("Matt", "MAT", "Matthew", "Matt", "NT", 40, ["mt", "mat", "matt", "matth", "matthew", "mathew"]),
    ("Mark", "MRK", "Mark", "Mark", "NT", 41, ["mk", "mrk", "mark", "mr", "markus"]),
    ("Luke", "LUK", "Luke", "Luke", "NT", 42, ["lk", "luk", "luke", "lu"]),
    ("John", "JHN", "John", "John", "NT", 43, ["jn", "jhn", "john", "joh", "johann", "iohannes"]),
    ("Acts", "ACT", "Acts", "Acts", "NT", 44, ["ac", "act", "acts", "acf", "acta"]),
    ("Rom", "ROM", "Romans", "Rom", "NT", 45, ["ro", "rom", "roma", "romans", "roa"]),
    ("1Cor", "1CO", "1 Corinthians", "1Cor", "NT", 46, ["1co", "1cor", "1 cor", "1cor.", "1corinth", "1 corinthians", "i cor", "1 c", "1co.", "1corint"]),
    ("2Cor", "2CO", "2 Corinthians", "2Cor", "NT", 47, ["2co", "2cor", "2 cor", "2cor.", "2corinth", "2 corinthians", "ii cor", "2 c", "2co.", "2corint"]),
    ("Gal", "GAL", "Galatians", "Gal", "NT", 48, ["ga", "gal", "galat", "galatians"]),
    ("Eph", "EPH", "Ephesians", "Eph", "NT", 49, ["ep", "eph", "ephes", "ephesian"]),
    ("Phil", "PHP", "Philippians", "Phil", "NT", 50, ["php", "phil", "phili", "philip", "philippians", "philipp", "phi"]),
    ("Col", "COL", "Colossians", "Col", "NT", 51, ["col", "colo", "coloss", "colossians"]),
    ("1Thess", "1TH", "1 Thessalonians", "1Thess", "NT", 52, ["1th", "1thess", "1 thess", "1thes", "1 thessalonians", "1thess.", "1 thessal", "i thess", "1 th"]),
    ("2Thess", "2TH", "2 Thessalonians", "2Thess", "NT", 53, ["2th", "2thess", "2 thess", "2thes", "2 thessalonians", "2thess.", "2 thessal", "ii thess", "2 th"]),
    ("1Tim", "1TI", "1 Timothy", "1Tim", "NT", 54, ["1ti", "1tim", "1 tim", "1tim.", "1timoth", "1 timothy", "i tim", "1 tm", "1ti."]),
    ("2Tim", "2TI", "2 Timothy", "2Tim", "NT", 55, ["2ti", "2tim", "2 tim", "2tim.", "2timoth", "2 timothy", "ii tim", "2 tm", "2ti."]),
    ("Titus", "TIT", "Titus", "Titus", "NT", 56, ["ti", "tit", "titus", "tit."]),
    ("Phlm", "PHM", "Philemon", "Phlm", "NT", 57, ["phm", "phlm", "philem", "philemon"]),
    ("Heb", "HEB", "Hebrews", "Heb", "NT", 58, ["he", "heb", "hebr", "hebrew"]),
    ("Jas", "JAS", "James", "Jas", "NT", 59, ["ja", "jas", "jame", "james", "jac", "james."]),
    ("1Pet", "1PE", "1 Peter", "1Pet", "NT", 60, ["1pe", "1pet", "1 pet", "1pet.", "1peter", "1 peter", "i pet", "1 pt", "1pe."]),
    ("2Pet", "2PE", "2 Peter", "2Pet", "NT", 61, ["2pe", "2pet", "2 pet", "2pet.", "2peter", "2 peter", "ii pet", "2 pt", "2pe."]),
    ("1John", "1JN", "1 John", "1John", "NT", 62, ["1jn", "1jhn", "1 jn", "1john", "1 joh", "1john.", "i john", "1 jhn", "1jn."]),
    ("2John", "2JN", "2 John", "2John", "NT", 63, ["2jn", "2jhn", "2 jn", "2john", "2 joh", "2john.", "ii john", "2 jhn", "2jn."]),
    ("3John", "3JN", "3 John", "3John", "NT", 64, ["3jn", "3jhn", "3 jn", "3john", "3 joh", "3john.", "3 jhn", "3jn."]),
    ("Jude", "JUD", "Jude", "Jude", "NT", 65, ["jud", "jude", "jude."]),
    ("Rev", "REV", "Revelation", "Rev", "NT", 66, ["re", "rev", "revel", "revelation", "revelations", "apocalypse"]),
]

# Deuterocanonical / apocrypha, with their KJA ordinals (the KJV+Apocrypha order).
_AP_KJA = [
    ("Tob", "TOB", "Tobit", "Tob", "AP", 67, ["tob", "tobit", "tobi", "tob.", "book of tob"]),
    ("Jdt", "JDT", "Judith", "Jdt", "AP", 68, ["jdt", "judith", "judi"]),
    ("Rest", "ESG", "Rest of Esther", "RestEsth", "AP", 69, ["rest", "rest of esther", "addition to esther", "restesther", "additions to esther"]),
    ("Wis", "WIS", "Wisdom of Solomon", "Wis", "AP", 70, ["wis", "wisd", "wisdom", "wisdom of solomon", "wisd. of sol", "wisdomsol"]),
    ("Sir", "SIR", "Ecclesiasticus", "Sir", "AP", 71, ["sir", "sire", "eccl", "ecclesiasticus", "ecclus", "sirach"]),
    ("Bar", "BAR", "Baruch", "Bar", "AP", 72, ["bar", "baru", "baruch", "bar."]),
    ("EpJer", "EJR", "Epistle of Jeremiah", "EpJer", "AP", 73, ["epjer", "ep jer", "epistle of jeremiah"]),
    ("PrAzar", "AZA", "Azariah", "PrAzar", "AP", 74, ["prazar", "azariah", "prayer of azariah", "song of azariah"]),
    ("Sus", "SUS", "Susanna", "Sus", "AP", 75, ["sus", "susa", "susanna", "story of susanna"]),
    ("Bel", "BEL", "Bel and the Dragon", "Bel", "AP", 76, ["bel", "bel and the dragon", "belbel"]),
    ("1Macc", "1MA", "1 Maccabees", "1Macc", "AP", 77, ["1ma", "1macc", "1 macc", "1maccab", "1maccabees", "1 mac"]),
    ("2Macc", "2MA", "2 Maccabees", "2Macc", "AP", 78, ["2ma", "2macc", "2 macc", "2maccab", "2maccabees", "2 mac"]),
    ("PrMan", "MAN", "The Prayer of Manasses", "PrMan", "AP", 79, ["prman", "manas", "manasseh", "prayer of manasses"]),
    ("1Esd", "1ES", "1 Esdras", "1Esd", "AP", 80, ["1esd", "1 esd", "1 esdras", "esdras 1", "1esdras"]),
    ("2Esd", "2ES", "2 Esdras", "2Esd", "AP", 81, ["2esd", "2 esd", "2 esdras", "esdras 2", "2esdras"]),
    ("Ps151", "P51", "Psalm 151", "Ps151", "AP", 82, ["ps151", "ps 151", "psalm 151"]),
]


class Book(NamedTuple):
    osis: str
    usfm: str | None
    name: str
    short: str
    group: str
    ordinal: int
    abbrevs: tuple[str, ...]

    @property
    def testament(self) -> str:
        return "NT" if self.group == "NT" else "OT"


def _mk(rows) -> list[Book]:
    return [Book(r[0], r[1], r[2], r[3], r[4], r[5], tuple(r[6])) for r in rows]


BOOKS_66 = _mk(_P66)
BOOKS_AP = _mk(_AP_KJA)
BOOKS_KJA = BOOKS_66 + BOOKS_AP
BOOKS_CATHOLIC = BOOKS_66 + BOOKS_AP

# Canonical (Protestant) 66, in order.
BOOKS = BOOKS_66

_BY_KEY: dict[str, Book] = {}


def _normalise_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\s.]+", " ", s)
    s = s.replace(".", "")
    return s.strip()


for _b in BOOKS_KJA:
    for _k in (_b.osis, _b.usfm, _b.name, _b.short, *_b.abbrevs):
        if _k:
            _BY_KEY.setdefault(_normalise_key(_k), _b)
# Common alternate spellings that no author would have included.
_BY_KEY.update({
    "1 jn": BOOKS[61], "2 jn": BOOKS[62], "3 jn": BOOKS[63],
    "1 john": BOOKS[61], "2 john": BOOKS[62], "3 john": BOOKS[63],
    "1 samuel": BOOKS[8], "2 samuel": BOOKS[9],
    "1 kings": BOOKS[10], "2 kings": BOOKS[11],
    "1 chronicles": BOOKS[12], "2 chronicles": BOOKS[13],
    "1 corinthians": BOOKS[45], "2 corinthians": BOOKS[46],
    "1 thessalonians": BOOKS[51], "2 thessalonians": BOOKS[52],
    "1 timothy": BOOKS[53], "2 timothy": BOOKS[54],
    "1 peter": BOOKS[59], "2 peter": BOOKS[60],
    "i john": BOOKS[61], "ii john": BOOKS[62], "iii john": BOOKS[63],
    "song of song": BOOKS[21], "song of songs": BOOKS[21],
    "revelation of john": BOOKS[65], "revelations": BOOKS[65],
    "philippians": BOOKS[49], "habakkuk": BOOKS[34], "malachi": BOOKS[38],
})
_BY_KEY.pop("para", None)


def lookup_book(token: str) -> Book | None:
    """Resolve a book name / abbreviation.  Returns None if unrecognised."""
    if not token:
        return None
    key = _normalise_key(token)
    b = _BY_KEY.get(key)
    if b is not None:
        return b
    # Tolerate trailing punctuation noise such as "Gen." or "1 Sam."
    key2 = key.rstrip(" ,;:")
    if key2 != key:
        b = _BY_KEY.get(key2)
        if b is not None:
            return b
    # "1 sam" / "1samuel" already covered; handle roman-numeral prefixes
    m = re.match(r"^(i{1,3}|iv|v|vi{0,3})\s+(.+)$", key)
    if m:
        roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7"}[m.group(1)]
        b = _BY_KEY.get(f"{roman} {m.group(2)}")
        if b is not None:
            return b
    return None


BOOK_BY_OSIS: dict[str, Book] = {b.osis: b for b in BOOKS_KJA}
BOOK_BY_USFM: dict[str, Book] = {b.usfm: b for b in BOOKS_KJA if b.usfm}
# The USFM "standard abbreviations" (usfm.org) are what real files use in
# \id markers, <book id> elements and per-book file names.  They differ from
# the OSIS codes in the canonical table for a handful of books -- DEU/JOS/NAM
# most notably -- and a reader that only knows the OSIS spellings silently
# drops whole books from a volume.  Merge the standard list so any of them
# resolves.
_USFM_STANDARD = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1Sam",
    "2SA": "2Sam", "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr",
    "2CH": "2Chr", "EZR": "Ezra", "NEH": "Neh", "EST": "Esth", "JOB": "Job",
    "PSA": "Ps", "PRO": "Prov", "ECC": "Eccl", "SNG": "Song", "ISA": "Isa",
    "JER": "Jer", "LAM": "Lam", "EZK": "Ezek", "DAN": "Dan", "HOS": "Hos",
    "JOL": "Joel", "AMO": "Amos", "OBA": "Obad", "JON": "Jonah",
    "MIC": "Mic", "NAM": "Nah", "HAB": "Hab", "ZEP": "Zeph", "HAG": "Hag",
    "ZEC": "Zech", "MAL": "Mal", "MAT": "Matt", "MRK": "Mark",
    "LUK": "Luke", "JHN": "John", "ACT": "Acts", "ROM": "Rom",
    "1CO": "1Cor", "2CO": "2Cor", "GAL": "Gal", "EPH": "Eph",
    "PHP": "Phil", "COL": "Col", "1TH": "1Thess", "2TH": "2Thess",
    "1TI": "1Tim", "2TI": "2Tim", "TIT": "Titus", "PHM": "Phlm",
    "HEB": "Heb", "JAS": "Jas", "1PE": "1Pet", "2PE": "2Pet",
    "1JN": "1John", "2JN": "2John", "3JN": "3John", "JUD": "Jude",
    "REV": "Rev",
}
for _usfm_code, _osis in _USFM_STANDARD.items():
    BOOK_BY_USFM.setdefault(_usfm_code, BOOK_BY_OSIS.get(_osis))
BOOK_BY_ORDINAL: dict[int, Book] = {b.ordinal: b for b in BOOKS_KJA}
# German book names.  The SWORD repository is heavily German, and a commentary
# whose notes are headed "Apostelgeschichte 1:1" cannot be reached by reference
# without them -- it would only ever be findable by searching its text.
_BOOK_ALT_DE: dict[str, str] = {
    "genesis": "Gen", "1. mose": "Gen", "mose": "Exod", "2. mose": "Exod",
    "exodus": "Exod", "leviticus": "Lev", "3. mose": "Lev",
    "numeri": "Num", "4. mose": "Num", "deuteronomium": "Deut",
    "5. mose": "Deut", "josua": "Josh", "joshua": "Josh",
    "richter": "Judg", "rut": "Ruth", "1. samuel": "1Sam",
    "2. samuel": "2Sam", "1. könige": "1Kgs", "2. könige": "2Kgs",
    "1. chronik": "1Chr", "2. chronik": "2Chr", "esra": "Ezra",
    "nehemia": "Neh", "esther": "Esth", "hiob": "Job", "psalm": "Ps",
    "psalmen": "Ps", "sprüche": "Prov", "sprichwörter": "Prov",
    "prediger": "Eccl", "hohe lied": "Song", "lieder der liebe": "Song",
    "jesaja": "Isa", "jeremia": "Jer", "klagelieder": "Lam",
    "hesekiel": "Ezek", "daniel": "Dan", "hes Joel": "Joel",
    "amos": "Amos", "obadja": "Obad", "jona": "Jonah", "mich a": "Mic",
    "nahum": "Nah", "habakuk": "Hab", "sefanja": "Zeph", "haggai": "Hag",
    "sacharia": "Zech", "maleachi": "Mal",
    "mattäus": "Matt", "markus": "Mrk", "lukas": "Luk", "johannes": "John",
    "apostelgeschichte": "Acts", "apostel geschichte": "Acts",
    "römer": "Rom", "1. korinther": "1Cor", "2. korinther": "2Cor",
    "galater": "Gal", "epheser": "Eph", "philipper": "Phil",
    "kolosser": "Col", "1. thessalonicher": "1Thess",
    "2. thessalonicher": "2Thess", "1. timotheus": "1Tim",
    "2. timotheus": "2Tim", "titus": "Titus", "philemon": "Phlm",
    "hebräer": "Heb", "jakobus": "Jas", "1. petrus": "1Pet",
    "2. petrus": "2Pet", "1. johannes": "1John", "2. johannes": "2John",
    "3. johannes": "3John", "judas": "Jude", "offenbarung": "Rev",
    "offenbarung johannis": "Rev",
}

BOOK_BY_NAME: dict[str, Book] = {b.name.lower(): b for b in BOOKS_KJA}

# Fold the German names in under their lower-cased spelling.
for _de, _osis in _BOOK_ALT_DE.items():
    _b = BOOK_BY_OSIS.get(_osis)
    if _b is not None:
        BOOK_BY_NAME.setdefault(_de.lower(), _b)

# e-Sword / MySword / BibleWorks 1..66 book-id order, Protestant.
BOOKS_BY_ESWORD_ID = list(BOOKS_66)


def book_by_esword_id(i: int) -> Book | None:
    return BOOKS_BY_ESWORD_ID[i - 1] if 1 <= i <= len(BOOKS_BY_ESWORD_ID) else None


# --------------------------------------------------------------------------
# Versification
# --------------------------------------------------------------------------
# Per-chapter verse counts for the KJV scheme.  Indexed by osis id.
_KJV_VC: dict[str, tuple[int, ...]] = {
    "Gen": (31, 25, 24, 26, 32, 22, 24, 22, 29, 32, 32, 20, 18, 24, 21, 16, 27, 33, 38, 18, 34, 24, 20, 67, 34, 35, 46, 22, 35, 43, 55, 32, 20, 31, 29, 43, 36, 30, 23, 23, 57, 38, 34, 34, 28, 34, 31, 22, 33, 26),
    "Exod": (22, 25, 22, 31, 23, 30, 25, 32, 35, 29, 10, 51, 22, 31, 27, 36, 16, 27, 25, 26, 36, 31, 33, 18, 40, 37, 21, 43, 46, 38, 18, 35, 23, 35, 35, 38, 29, 31, 43, 38),
    "Lev": (17, 16, 17, 35, 19, 30, 38, 36, 24, 20, 47, 8, 59, 57, 33, 34, 16, 30, 37, 27, 24, 33, 44, 23, 55, 46, 34),
    "Num": (54, 34, 51, 49, 31, 27, 89, 26, 23, 36, 35, 16, 33, 45, 41, 50, 13, 32, 22, 29, 35, 41, 30, 25, 18, 65, 23, 31, 40, 16, 54, 42, 56, 29, 34, 13),
    "Deut": (46, 37, 29, 49, 33, 25, 26, 20, 29, 22, 32, 32, 18, 29, 23, 22, 20, 22, 21, 20, 23, 30, 25, 22, 19, 19, 26, 68, 29, 20, 30, 52, 29, 12),
    "Josh": (18, 24, 17, 24, 15, 27, 26, 35, 27, 43, 23, 24, 33, 15, 63, 10, 18, 28, 51, 9, 45, 34, 16, 33),
    "Judg": (36, 23, 31, 24, 31, 40, 25, 35, 57, 18, 40, 15, 25, 20, 20, 31, 13, 31, 30, 48, 25),
    "Ruth": (22, 23, 18, 22),
    "1Sam": (28, 36, 21, 22, 12, 21, 17, 22, 27, 27, 15, 25, 23, 52, 35, 23, 58, 30, 24, 42, 15, 23, 29, 22, 44, 25, 12, 25, 11, 31, 13),
    "2Sam": (27, 32, 39, 12, 25, 23, 29, 18, 13, 19, 27, 31, 39, 33, 37, 23, 29, 33, 43, 26, 22, 51, 39, 25),
    "1Kgs": (53, 46, 28, 34, 18, 38, 51, 66, 28, 29, 43, 33, 34, 31, 34, 34, 24, 46, 21, 43, 29, 53),
    "2Kgs": (18, 25, 27, 44, 27, 33, 20, 29, 37, 36, 21, 21, 25, 29, 38, 20, 41, 37, 37, 21, 26, 20, 37, 20, 30),
    "1Chr": (54, 55, 24, 43, 26, 81, 40, 40, 44, 14, 47, 40, 14, 17, 29, 43, 27, 17, 19, 8, 30, 19, 32, 31, 31, 32, 34, 21, 30),
    "2Chr": (17, 18, 17, 22, 14, 42, 22, 18, 31, 19, 23, 16, 22, 15, 19, 14, 19, 34, 11, 37, 20, 12, 21, 27, 28, 23, 9, 27, 36, 27, 21, 33, 25, 33, 27, 23),
    "Ezra": (11, 70, 13, 24, 17, 22, 28, 36, 15, 44),
    "Neh": (11, 20, 32, 23, 19, 19, 73, 18, 38, 39, 36, 47, 31),
    "Esth": (22, 23, 15, 17, 14, 14, 10, 17, 32, 3),
    "Job": (22, 13, 26, 21, 27, 30, 21, 22, 35, 22, 20, 25, 28, 22, 35, 22, 16, 21, 29, 29, 34, 30, 17, 25, 6, 14, 23, 28, 25, 31, 40, 22, 33, 37, 16, 33, 24, 41, 30, 24, 34, 17),
    "Ps": (6, 12, 8, 8, 12, 10, 17, 9, 20, 18, 7, 8, 6, 7, 5, 11, 15, 50, 14, 9, 13, 31, 6, 10, 22, 12, 14, 9, 11, 12, 24, 11, 22, 22, 28, 12, 40, 22, 13, 17, 13, 11, 5, 26, 17, 11, 9, 14, 20, 23, 19, 9, 6, 7, 23, 13, 11, 11, 17, 12, 8, 12, 11, 10, 13, 20, 7, 35, 36, 5, 24, 20, 28, 23, 10, 12, 20, 72, 13, 19, 16, 8, 18, 12, 13, 17, 7, 18, 52, 17, 16, 15, 5, 23, 11, 13, 12, 9, 9, 5, 8, 28, 22, 35, 45, 48, 43, 13, 31, 7, 10, 10, 9, 8, 18, 19, 2, 29, 176, 7, 8, 9, 4, 8, 5, 6, 5, 6, 8, 8, 3, 18, 3, 3, 21, 26, 9, 8, 24, 13, 10, 7, 12, 15, 21, 10, 20, 14, 9, 6),
    "Prov": (33, 22, 35, 27, 23, 35, 27, 36, 18, 32, 31, 28, 25, 35, 33, 33, 28, 24, 29, 30, 31, 29, 35, 34, 28, 28, 27, 28, 27, 33, 31),
    "Eccl": (18, 26, 22, 16, 20, 12, 29, 17, 18, 20, 10, 14),
    "Song": (17, 17, 11, 16, 16, 13, 13, 14),
    "Isa": (31, 22, 26, 6, 30, 13, 25, 22, 21, 34, 16, 6, 22, 32, 9, 14, 14, 7, 25, 6, 17, 25, 18, 23, 12, 21, 13, 29, 24, 33, 9, 20, 24, 17, 10, 22, 38, 22, 8, 31, 29, 25, 28, 28, 25, 13, 15, 22, 26, 11, 23, 15, 12, 17, 13, 12, 21, 14, 21, 22, 11, 12, 19, 12, 25, 24),
    "Jer": (19, 37, 25, 31, 31, 30, 34, 22, 26, 25, 23, 17, 27, 22, 21, 21, 27, 23, 15, 18, 14, 30, 40, 10, 38, 24, 22, 17, 32, 24, 40, 44, 26, 22, 19, 32, 21, 28, 18, 16, 18, 22, 13, 30, 5, 28, 7, 47, 39, 46, 64, 34),
    "Lam": (22, 22, 66, 22, 22),
    "Ezek": (28, 10, 27, 17, 17, 14, 27, 18, 11, 22, 25, 28, 23, 23, 8, 63, 24, 32, 14, 49, 32, 31, 49, 27, 17, 21, 36, 26, 21, 26, 18, 32, 33, 31, 15, 38, 28, 23, 29, 49, 26, 20, 27, 31, 25, 24, 23, 35),
    "Dan": (21, 49, 30, 37, 31, 28, 28, 27, 27, 21, 45, 13),
    "Hos": (11, 23, 5, 19, 15, 11, 16, 14, 17, 15, 12, 14, 16, 9),
    "Joel": (20, 32, 21),
    "Amos": (15, 16, 15, 13, 27, 14, 17, 14, 15),
    "Obad": (21,),
    "Jonah": (17, 10, 10, 11),
    "Mic": (16, 13, 12, 13, 15, 16, 20),
    "Nah": (15, 13, 19),
    "Hab": (17, 20, 19),
    "Zeph": (18, 15, 20),
    "Hag": (15, 23),
    "Zech": (21, 13, 10, 14, 11, 15, 14, 23, 17, 12, 17, 14, 9, 21),
    "Mal": (14, 17, 18, 6),
    "Matt": (25, 23, 17, 25, 48, 34, 29, 34, 38, 42, 30, 50, 58, 36, 39, 28, 27, 35, 30, 34, 46, 46, 39, 51, 46, 75, 66, 20),
    "Mark": (45, 28, 35, 41, 43, 56, 37, 38, 50, 52, 33, 44, 37, 72, 47, 20),
    "Luke": (80, 52, 38, 44, 39, 49, 50, 56, 62, 42, 54, 59, 35, 35, 32, 31, 37, 43, 48, 47, 38, 71, 56, 53),
    "John": (51, 25, 36, 54, 47, 71, 53, 59, 41, 42, 57, 50, 38, 31, 27, 33, 26, 40, 42, 31, 25),
    "Acts": (26, 47, 26, 37, 42, 15, 60, 40, 43, 48, 30, 25, 52, 28, 41, 40, 34, 28, 41, 38, 40, 30, 35, 27, 27, 32, 44, 31),
    "Rom": (32, 29, 31, 25, 21, 23, 25, 39, 33, 21, 36, 21, 14, 23, 33, 27),
    "1Cor": (31, 16, 23, 21, 13, 20, 40, 13, 27, 33, 34, 31, 13, 40, 58, 24),
    "2Cor": (24, 17, 18, 18, 21, 18, 16, 24, 15, 18, 33, 21, 14),
    "Gal": (24, 21, 29, 31, 26, 18),
    "Eph": (23, 22, 21, 32, 33, 24),
    "Phil": (30, 30, 21, 23),
    "Col": (29, 23, 25, 18),
    "1Thess": (10, 20, 13, 18, 28),
    "2Thess": (12, 17, 18),
    "1Tim": (20, 15, 16, 16, 25, 21),
    "2Tim": (18, 26, 17, 22),
    "Titus": (16, 15, 15),
    "Phlm": (25,),
    "Heb": (14, 18, 19, 16, 14, 20, 28, 13, 28, 39, 40, 29, 25),
    "Jas": (27, 26, 18, 17, 20),
    "1Pet": (25, 25, 22, 19, 14),
    "2Pet": (21, 22, 18),
    "1John": (10, 29, 24, 21, 21),
    "2John": (13,),
    "3John": (14,),
    "Jude": (25,),
    "Rev": (20, 29, 22, 11, 14, 17, 17, 13, 21, 11, 19, 17, 18, 20, 8, 21, 18, 24, 21, 15, 27, 21),
}

_AP_VC: dict[str, tuple[int, ...]] = {
    "Tob": (136, 0, 0, 0, 0, 0, 0, 21, 6, 13, 59, 0, 0, 14),
    "Jdt": (16, 626),
    "Rest": (176,),
    "Wis": (16, 365, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 21, 25, 22),
    "Sir": (566, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 84, 0, 0, 417, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 34, 35, 30, 23, 260),
    "Bar": (217,),
    "EpJer": (67,),
    "PrAzar": (67,),
    "Sus": (63,),
    "Bel": (41,),
    "1Macc": (195, 0, 0, 61, 68, 63, 50, 32, 73, 89, 74, 53, 53, 49, 41, 24),
    "2Macc": (188, 0, 0, 0, 0, 31, 42, 36, 29, 38, 38, 45, 26, 46, 39),
    "PrMan": (259,),
    "1Esd": (399, 0, 0, 0, 0, 0, 0, 0, 55),
    "2Esd": (879, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 579),
    "Ps151": (7,),
}


# Schemes in the SWORD conf; map to our book set + verse counts.
_V11N_SCHEMES: dict[str, tuple[list[Book], dict[str, tuple[int, ...]]]] = {
    "KJV": (BOOKS_66, _KJV_VC),
    "KJVA": (BOOKS_KJA, {**_KJV_VC, **_AP_VC}),
    "NRSV": (BOOKS_66, _KJV_VC),
    "NRSVA": (BOOKS_66, _KJV_VC),
    "Catholic": (BOOKS_CATHOLIC, {**_KJV_VC, **_AP_VC}),
    "Catholic2": (BOOKS_CATHOLIC, {**_KJV_VC, **_AP_VC}),
    "Vulg": (BOOKS_CATHOLIC, {**_KJV_VC, **_AP_VC}),
    # These differ in order / book set, not in verse counts for the shared books.
    "Calvin": (BOOKS_66, _KJV_VC),
    "LXX": (BOOKS_KJA, {**_KJV_VC, **_AP_VC}),
    "Leningrad": (BOOKS_66, _KJV_VC),
    "Luther": (BOOKS_66, _KJV_VC),
    "MT": (BOOKS_66, _KJV_VC),
    "Segond": (BOOKS_66, _KJV_VC),
    "Synodal": (BOOKS_66, _KJV_VC),
    "SynodalProt": (BOOKS_66, _KJV_VC),
    "Orthodox": (BOOKS_66, _KJV_VC),
    "German": (BOOKS_66, _KJV_VC),
    "Darby_Fr": (BOOKS_66, _KJV_VC),
}


def verse_counts(scheme: str, osis: str) -> tuple[int, ...]:
    _, counts = _V11N_SCHEMES.get(scheme, _V11N_SCHEMES["KJV"])
    vc = counts.get(osis)
    if vc is not None:
        return vc
    # Greek / Hebrew transliterations differ; fall back on ordinal position.
    b = BOOK_BY_OSIS.get(osis)
    if b is not None:
        return _KJV_VC.get(BOOKS_BY_ESWORD_ID[b.ordinal - 1].osis, ()) if b.ordinal <= 66 else ()
    return ()


def books_for(scheme: str) -> list[Book]:
    return _V11N_SCHEMES.get(scheme, _V11N_SCHEMES["KJV"])[0]


def chapter_count(scheme: str, osis: str) -> int:
    return len(verse_counts(scheme, osis))


def verse_count(scheme: str, osis: str, chapter: int) -> int:
    vc = verse_counts(scheme, osis)
    if 1 <= chapter <= len(vc):
        return vc[chapter - 1]
    return 0


def last_verse(scheme: str, osis: str, chapter: int) -> int:
    return verse_count(scheme, osis, chapter)


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------

class Ref(NamedTuple):
    """A canonical milestone.  chapter/verse of 0 mean 'book level' / 'chapter level'."""
    book: str          # osis id
    chapter: int = 0
    verse: int = 0

    @property
    def label(self) -> str:
        return format_ref(self)

    @property
    def sort_key(self) -> tuple:
        b = BOOK_BY_OSIS.get(self.book)
        return (b.ordinal if b else 999, self.chapter, self.verse)

    def __str__(self) -> str:
        return format_ref(self)

    def osis_id(self) -> str:
        if self.chapter and self.verse:
            return f"{self.book}.{self.chapter}.{self.verse}"
        if self.chapter:
            return f"{self.book}.{self.chapter}"
        return self.book

    def next_verse(self) -> "Ref":
        return next_ref(self)

    def prev_verse(self) -> "Ref":
        return prev_ref(self)


def format_ref(ref: Ref, *, full: bool = False) -> str:
    b = BOOK_BY_OSIS.get(ref.book)
    name = (b.name if b and full else b.short if b else ref.book)
    if ref.chapter and ref.verse:
        return f"{name} {ref.chapter}:{ref.verse}"
    if ref.chapter:
        return f"{name} {ref.chapter}"
    return name


def _same_book_chain(order: list[Book]) -> dict[str, int]:
    return {b.osis: i for i, b in enumerate(order)}


_KJV_ORDER = _same_book_chain(BOOKS_66)
_KJA_ORDER = _same_book_chain(BOOKS_KJA)
_CATH_ORDER = _same_book_chain(BOOKS_CATHOLIC)


def _order_map(scheme: str) -> dict[str, int]:
    s = (scheme or "KJV")
    if s in ("KJVA", "NRSVA", "LXX"):
        return _KJA_ORDER
    if s in ("Catholic", "Catholic2", "Vulg"):
        return _CATH_ORDER
    return _KJV_ORDER


def next_ref(ref: Ref, scheme: str = "KJV") -> Ref:
    om = _order_map(scheme)
    cur = om.get(ref.book, -1)
    order = books_for(scheme)
    for step in range(0, len(order) + 1):
        i = cur + step
        if i >= len(order):
            break
        bk = order[i]
        if step == 0:
            if ref.verse < verse_count(scheme, bk.osis, ref.chapter):
                return Ref(bk.osis, ref.chapter, ref.verse + 1)
            if ref.chapter < chapter_count(scheme, bk.osis):
                return Ref(bk.osis, ref.chapter + 1, 1)
        else:
            if chapter_count(scheme, bk.osis):
                return Ref(bk.osis, 1, 1)
    return ref


def prev_ref(ref: Ref, scheme: str = "KJV") -> Ref:
    om = _order_map(scheme)
    cur = om.get(ref.book, 0)
    order = books_for(scheme)
    for step in range(0, len(order) + 1):
        i = cur - step
        if i < 0:
            break
        bk = order[i]
        if step == 0:
            if ref.verse > 1:
                return Ref(bk.osis, ref.chapter, ref.verse - 1)
            if ref.chapter > 1:
                cc = chapter_count(scheme, bk.osis)
                return Ref(bk.osis, ref.chapter - 1, verse_count(scheme, bk.osis, cc) or 1)
        else:
            cc = chapter_count(scheme, bk.osis)
            if cc:
                return Ref(bk.osis, cc, verse_count(scheme, bk.osis, cc) or 1)
    return ref


def next_chapter(ref: Ref, scheme: str = "KJV") -> Ref:
    """The next chapter of this book, and at the book's end the start of the
    next one.  This is the reader's "Next chapter" button: within a book it
    must move one chapter, "Genesis 1" -> "Genesis 2", not land on Exodus."""
    cc = chapter_count(scheme, ref.book)
    if cc and ref.chapter < cc:
        return Ref(ref.book, ref.chapter + 1, 1)
    om = _order_map(scheme)
    order = books_for(scheme)
    i = om.get(ref.book, -1) + 1
    while i < len(order):
        bk = order[i]
        i += 1
        if chapter_count(scheme, bk.osis):
            return Ref(bk.osis, 1, 1)
    return ref


def prev_chapter(ref: Ref, scheme: str = "KJV") -> Ref:
    """The previous chapter of this book, and at its first chapter the last
    chapter of the book before it."""
    if ref.chapter > 1:
        cc = ref.chapter - 1
        return Ref(ref.book, cc, verse_count(scheme, ref.book, cc) or 1)
    om = _order_map(scheme)
    order = books_for(scheme)
    i = om.get(ref.book, 0) - 1
    while i >= 0:
        bk = order[i]
        i -= 1
        cc = chapter_count(scheme, bk.osis)
        if cc:
            return Ref(bk.osis, cc, verse_count(scheme, bk.osis, cc) or 1)
    return ref


def next_book(ref: Ref, scheme: str = "KJV") -> Ref:
    """First chapter of the next book in the canon."""
    om = _order_map(scheme)
    order = books_for(scheme)
    i = om.get(ref.book, -1) + 1
    while i < len(order):
        bk = order[i]
        i += 1
        if chapter_count(scheme, bk.osis):
            return Ref(bk.osis, 1, 1)
    return ref


def prev_book(ref: Ref, scheme: str = "KJV") -> Ref:
    """Last chapter of the previous book in the canon."""
    om = _order_map(scheme)
    order = books_for(scheme)
    i = om.get(ref.book, 0) - 1
    while i >= 0:
        bk = order[i]
        i -= 1
        cc = chapter_count(scheme, bk.osis)
        if cc:
            return Ref(bk.osis, cc, verse_count(scheme, bk.osis, cc) or 1)
    return ref


# Ranges ------------------------------------------------------------------

class RefRange(NamedTuple):
    start: Ref
    end: Ref

    def label(self) -> str:
        if self.start == self.end:
            return format_ref(self.start)
        if self.start.book == self.end.book and self.start.chapter == self.end.chapter:
            if self.end.verse:
                return f"{format_ref(self.start)}-{self.end.verse}"
            return format_ref(self.start)
        if self.start.book == self.end.book and self.start.verse == self.end.verse == 0:
            return f"{format_ref(self.start)}-{self.end.chapter}"
        if self.start.verse == self.end.verse and self.end.verse:
            return f"{format_ref(self.start)}-{self.end.chapter}"
        return f"{format_ref(self.start)}-{format_ref(self.end)}"

    def refs(self, scheme: str = "KJV") -> Iterable[Ref]:
        cur = self.start
        if self.end.verse == 0 and self.start.chapter == self.end.chapter:
            # chapter-only range
            for c in range(self.start.chapter, self.end.chapter + 1):
                n = verse_count(scheme, self.start.book, c)
                for v in range(1, (n or 1) + 1):
                    yield Ref(self.start.book, c, v)
            return
        limit = self.end
        guard = 0
        while guard < 40000:
            guard += 1
            if cur == limit:
                yield cur
                return
            yield cur
            if cur.sort_key > limit.sort_key:
                return
            nxt = next_ref(cur, scheme)
            if nxt == cur:
                return
            cur = nxt


# Parsing ------------------------------------------------------------------

_BOOK_ALT = "|".join(sorted(
    {k for k in _BY_KEY if k and re.fullmatch(r"[a-z0-9 ]+", k)},
    key=len, reverse=True,
))

# NOTE: built with re.VERBOSE originally, which silently stripped the spaces
# inside multi-word abbreviations ("1 Jn" -> "1jn").  Do NOT re-add VERBOSE.
_REF_RE = re.compile(
    r"^\s*(?:(?P<book>" + _BOOK_ALT + r")\.?\s*)?"
    r"(?:(?P<chapter>\d+)\s*[:.]\s*(?P<verse>\d+)"
    r"(?:\s*[-–—]\s*(?:(?P<chapter2>\d+)\s*[:.]\s*)?(?P<verse2>\d+))?"
    r"|(?P<chapter_only>\d+)(?:\s*[-–—]\s*(?P<chapter_only2>\d+))?"
    r"|(?P<versecount>\d+))?\s*$",
    re.IGNORECASE,
)


def parse_ref(text: str, scheme: str = "KJV") -> RefRange | None:
    """Parse a user-typed reference.  Accepts Gen / Gen 1 / Gen 1:1 / Gen 1:1-5 /
    1 Jn 1:9 / Jn3.16 / Rev 22 / Rev 22:21-22:4.  Returns None if unparsable."""
    if not text:
        return None
    raw = text.strip()
    t = unicodedata.normalize("NFKC", raw)
    t = t.replace("\u00a0", " ")
    m = _REF_RE.match(t)
    if not m:
        return None
    g = m.groupdict()
    book_tok = (g.get("book") or "").strip()
    bk = lookup_book(book_tok) if book_tok else None
    if book_tok and bk is None:
        return None

    # Bare numbers with no book: a chapter number for the implied book.
    ch = g.get("chapter")
    vs = g.get("verse")
    if ch and vs:
        end_v = int(g.get("verse2") or vs)
        end_c = int(g.get("chapter2") or ch)
        start = Ref(bk.osis, int(ch), int(vs)) if bk else Ref("", int(ch), int(vs))
        end = Ref(bk.osis, end_c, end_v) if bk else Ref("", end_c, end_v)
        if bk is None:
            return None
        return RefRange(start, end) if start != end else RefRange(start, start)
    if g.get("chapter_only"):
        c1 = int(g["chapter_only"])
        c2 = int(g.get("chapter_only2") or c1)
        if bk is None:
            return None
        return RefRange(Ref(bk.osis, c1, 0), Ref(bk.osis, c2, 0))
    if g.get("versecount"):
        n = int(g["versecount"])
        if bk is None:
            return None
        return RefRange(Ref(bk.osis, 1, 1), Ref(bk.osis, 1, n))
    if bk is not None:
        return RefRange(Ref(bk.osis, 0, 0), Ref(bk.osis, 0, 0))
    return None


def is_valid_ref(text: str) -> bool:
    return parse_ref(text) is not None


def scan_refs(text: str, *, dedupe: bool = True) -> list[dict]:
    """Find Bible references embedded in arbitrary text.

    Returns a list of {ref, label, start, end} for each reference found,
    in order of appearance.  A book name with no chapter is deliberately not
    reported: "John said" is not a reference.

    With `dedupe` on, a reference cited several times in one text is reported
    once, at its first occurrence.  The reader's reference linker needs the
    opposite: every occurrence becomes a link, and it passes `dedupe=False`.
    """
    if not text:
        return []
    pat = re.compile(
        r"(?<!\w)(?P<book>" + _BOOK_ALT + r")\.?\s*(?P<rest>\d[\d\s:.\-\u2013\u2014]*)",
        re.IGNORECASE,
    )
    out = []
    seen = set()
    for m in pat.finditer(text):
        cand = m.group(0).strip()
        # Try the whole match, then trim trailing punctuation/whitespace.
        rr = None
        trimmed = cand
        while len(trimmed) >= 4:
            rr = parse_ref(trimmed)
            if rr is not None:
                break
            trimmed = trimmed[:-1].rstrip()
        if rr is None:
            continue
        # The reference may not fill the raw match ("Acts 5:16." ends in a
        # full stop): the span has to stop where the reference itself stops,
        # or the link swallows the punctuation after it.
        start, end = m.start(), m.start() + len(trimmed)
        try:
            label = rr.label()
        except Exception:  # noqa: BLE001
            label = trimmed
        if dedupe:
            if label in seen:
                continue
            seen.add(label)
        out.append({"ref": label, "label": label, "start": start, "end": end})
    return out


def find_all_refs(text: str, scheme: str = "KJV") -> list[RefRange]:
    """Scan free text for scripture references (for the Auto-Reference feature)."""
    out: list[RefRange] = []
    pat = re.compile(
        r"\b(1|2|3)?\s?[A-Za-z]{2,10}\.?\s+\d{1,3}(?::\d{1,3})?"
        r"(?:\s*[-–]\s*\d{1,3}(?::\d{1,3})?)?\b"
    )
    for m in pat.finditer(text or ""):
        rr = parse_ref(m.group(0), scheme)
        if rr:
            out.append(rr)
    return out


def parse_osis_id(s: str) -> Ref | None:
    """'Gen.1.1' / 'Gen.1' / 'Gen' / 'Gen.1.1-Gen.1.5' -> Ref."""
    if not s:
        return None
    s = s.strip()
    if "-" in s and "." in s:
        head = s.split("-")[0]
        return parse_osis_id(head)
    parts = s.split(".")
    b = BOOK_BY_OSIS.get(parts[0]) or lookup_book(parts[0])
    if b is None:
        return None
    ch = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    v = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return Ref(b.osis, ch, v)


def parse_osis_ref(s: str) -> RefRange | None:
    if not s:
        return None
    if "-" in s:
        a, _, b = s.partition("-")
        ra, rb = parse_osis_id(a), parse_osis_id(b)
        if ra and rb:
            return RefRange(ra, rb)
        return None
    r = parse_osis_id(s)
    return RefRange(r, r) if r else None


# Groups -------------------------------------------------------------------

TESTAMENTS = ("OT", "NT", "AP")


def normalise_strongs(raw: str) -> str:
    """'h0430' | 'H430' | 'G11' | 'g976' | '0430' -> 'H0430' / 'G0011'."""
    if not raw:
        return ""
    s = raw.strip().upper().lstrip("S")
    if s and s[0] in "GH":
        prefix, digits = s[0], s[1:]
    elif s and s[0] in "GH0" or (s[:1].isdigit()):
        digits = re.sub(r"\D", "", s)
        prefix = "H" if int(digits or 0) < 1000 and not s.startswith(("G", "g")) else "G"
        if s[:1] in "Gg":
            prefix, digits = "G", re.sub(r"\D", "", s[1:])
    else:
        return ""
    if not digits.isdigit():
        return ""
    return f"{prefix}{int(digits):04d}"


def strongs_osis(raw: str) -> str:
    """Strong's number -> OSIS lemma form used in modules: 'H0430' / 'G0011'."""
    return normalise_strongs(raw)


def strongs_num(strongs: str) -> tuple[str, int]:
    """'H0430' -> ('H', 430)."""
    s = normalise_strongs(strongs)
    if not s:
        return ("", 0)
    return (s[0], int(s[1:]))


# --------------------------------------------------------------------------
# Transliteration: saying the word out loud
# --------------------------------------------------------------------------

#: Greek.  A conventional academic transliteration -- what a teacher would put
#: on the board -- not phonetics.  It exists so "θεός" can be read as "theos"
#: and looked up, which is the whole point.
_GREEK = (
    ("α", "a"), ("β", "b"), ("γ", "g"), ("δ", "d"), ("ε", "e"), ("ζ", "z"),
    ("η", "e"), ("θ", "th"), ("ι", "i"), ("κ", "k"), ("λ", "l"), ("μ", "m"),
    ("ν", "n"), ("ξ", "x"), ("ο", "o"), ("π", "p"), ("ρ", "r"), ("σ", "s"),
    ("ς", "s"), ("τ", "t"), ("υ", "y"), ("φ", "ph"), ("χ", "ch"), ("ψ", "ps"),
    ("ω", "o"),
    ("ου", "ou"), ("αι", "ai"), ("ει", "ei"), ("αυ", "au"), ("ευ", "eu"),
)

#: Hebrew.  Consonants carry the word; the vowel points are not pronounced in
#: unpointed text, so an unpointed Hebrew word transliterates to its consonants.
_HEBREW = (
    ("א", "'"), ("ב", "b"), ("ג", "g"), ("ד", "d"), ("ה", "h"), ("ו", "v"),
    ("ז", "z"), ("ח", "kh"), ("ט", "t"), ("י", "y"), ("כ", "k"), ("ך", "kh"),
    ("ל", "l"), ("מ", "m"), ("ם", "m"), ("נ", "n"), ("ן", "n"), ("ס", "s"),
    ("ע", "'"), ("פ", "p"), ("ף", "f"), ("צ", "ts"), ("ץ", "ts"), ("ק", "q"),
    ("ר", "r"), ("ש", "sh"), ("ת", "t"),
    # niqqud: shown as nothing, because unpointed Hebrew has no vowels here
    ("ָ", ""), ("ַ", ""), ("ֶ", ""), ("ֵ", ""), ("ִ", ""), ("ֹ", ""),
    ("ֻ", ""), ("ּ", ""), ("ֲ", ""), ("ֱ", ""), ("ֳ", ""), ("ֵ", ""),
    ("ְ", ""), ("ֲ", ""), ("ִ", ""), ("ֵ", ""), ("ַ", ""), ("ֶ", ""),
)

# dict() of the pair as written -- Greek letter to Latin.  Using reversed() here
# produced {latin: greek}, so _GREEK_CHARS held Latin letters and *nothing*
# was ever detected as Greek: every word came back "this reads as Latin".
_GREEK_MAP = dict(_GREEK)
_HEBREW_MAP = dict(_HEBREW)
_GREEK_CHARS = set(_GREEK_MAP)
_HEBREW_CHARS = set(_HEBREW_MAP)


def transliterate(text: str) -> dict:
    """Say a Greek or Hebrew word in Latin letters.

    Returns the transliteration *and* what kind of script it was, because
    "mwtlw" with no indication of which language it is from is not much help.
    The English gloss is not attempted here: guessing a meaning for a Hebrew
    word is how a transliterator ends up confidently wrong.
    """
    import unicodedata as _ud
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "error": "no word"}
    # Decompose and drop the combining marks first.  "ό" is a different
    # codepoint from "ο" and no table keyed on the plain letter will ever see
    # it, which is how "lόgos" came out with the accent still attached -- and
    # Hebrew pointed text was worse, since every niqqud is a combining mark.
    t = "".join(c for c in _ud.normalize("NFD", raw)
                if not _ud.combining(c))
    t = _ud.normalize("NFC", t).casefold()
    greek = [c for c in t if c in _GREEK_CHARS]
    hebrew = [c for c in t if c in _HEBREW_CHARS]
    if greek and len(greek) >= len(hebrew):
        out = []
        i = 0
        while i < len(t):
            for two, tr in _GREEK:
                if t.startswith(two, i):
                    out.append(tr)
                    i += len(two)
                    break
            else:
                if t[i] in _GREEK_CHARS:
                    out.append(_GREEK_MAP[t[i]])
                else:
                    out.append(t[i])
                i += 1
        return {"ok": True, "script": "Greek", "input": raw,
                "transliteration": "".join(out)}
    if hebrew:
        out = []
        for c in t:
            if c in _HEBREW_MAP:
                out.append(_HEBREW_MAP[c])
            else:
                out.append(c)
        return {"ok": True, "script": "Hebrew", "input": raw,
                "transliteration": "".join(out)}
    return {"ok": False,
            "error": "no Greek or Hebrew letters there — this reads as Latin already"}


# --------------------------------------------------------------------------
# Gematria: the numeric value of a Hebrew word
# --------------------------------------------------------------------------

#: Standard (mispar hechri) values.  Final forms carry the same value as their
#: non-final counterparts, so a word's value does not change with position.
_GEMATRIA = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8,
    "ט": 9, "י": 10, "כ": 20, "ך": 20, "ל": 30, "מ": 40, "ם": 40,
    "נ": 50, "ן": 50, "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90,
    "ץ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400,
}


def gematria(text: str) -> dict:
    """Return the numeric value of a Hebrew word (mispar hechri).

    Greek has no native gematria in this app, and Latin letters are not
    converted.  Only Hebrew letters are counted; vowel points (niqqud) and
    non-Hebrew characters are ignored, never valued as zero-and-counted.
    """
    import unicodedata as _ud
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "error": "no word"}
    t = "".join(c for c in _ud.normalize("NFD", raw)
                if not _ud.combining(c))
    t = _ud.normalize("NFC", t)
    letters = [c for c in t if c in _GEMATRIA]
    if not letters:
        return {"ok": False,
                "error": "no Hebrew letters there — gematria applies to Hebrew"}
    total = sum(_GEMATRIA[c] for c in letters)
    # Per-letter breakdown so the result can be checked rather than trusted.
    breakdown = [{"letter": c, "value": _GEMATRIA[c]} for c in letters]
    return {"ok": True, "script": "Hebrew", "input": raw,
            "value": total, "letters": breakdown}
