"""Resource taxonomy.

The library is organised into two orthogonal facets, and that distinction
matters for how the Store filters and how the workspace groups panes:

* **type**    - the semantically load-bearing facet.  "Categories of books, more
                specific than the Subject choices."  Drives default parallel
                sets, pane grouping and search scoping.
* **subject** - the broad domain.  "Counselling", "Theological", "Archaeology"...

A third, orthogonal field is **index_types** (*milestone types*).  Two
resources can only be linked when their milestone types intersect -- that single
rule is the whole synchronisation engine, so it is modelled explicitly here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Milestone / index types
# --------------------------------------------------------------------------

INDEX_BIBLE_VERSE = "bibleVerse"      # Book.Chapter.Verse
INDEX_PAGE = "pageNumber"            # a monograph page
INDEX_HEADWORD = "headword"          # dictionary / lexicon / concordance article
INDEX_STRONGS = "strongsNumber"      # H0430 / G0011
INDEX_LEMMA = "lemma"                # the underlying lexical form
INDEX_MORPH = "morphology"           # a morphology code
INDEX_DATE = "date"                  # MMM.DD  (devotional / lectionary)
INDEX_TOPIC = "topic"                # a factbook topic
INDEX_PERSON = "person"
INDEX_PLACE = "place"
INDEX_SENSE = "sense"
INDEX_CULTURE = "culture"
INDEX_SECTION = "section"            # a chapter / a work
INDEX_ARTICLE = "article"            # an essay / journal article unit
INDEX_EVENT = "event"                # a dated event (FactBook timeline)

INDEX_TYPES: dict[str, str] = {
    INDEX_BIBLE_VERSE: "Bible verse",
    INDEX_PAGE: "Page number",
    INDEX_HEADWORD: "Headword",
    INDEX_STRONGS: "Strong's number",
    INDEX_LEMMA: "Lemma",
    INDEX_MORPH: "Morphology code",
    INDEX_DATE: "Date (M.D.)",
    INDEX_TOPIC: "Topic",
    INDEX_PERSON: "Person",
    INDEX_PLACE: "Place",
    INDEX_SENSE: "Sense",
    INDEX_CULTURE: "Cultural concept",
    INDEX_EVENT: "Event",
    INDEX_SECTION: "Section / chapter",
    INDEX_ARTICLE: "Article",
}

# Which index types each type can link on.  A resource's effective index set is
# the union of the ones its type allows, intersected with what the data actually
# contains.
TYPE_INDEX_TYPES: dict[str, tuple[str, ...]] = {
    "Bible": (INDEX_BIBLE_VERSE,),
    "StudyBible": (INDEX_BIBLE_VERSE,),
    "ParallelBible": (INDEX_BIBLE_VERSE,),
    "OriginalLanguage": (INDEX_BIBLE_VERSE, INDEX_LEMMA, INDEX_STRONGS, INDEX_MORPH),
    "Apologetics": (INDEX_BIBLE_VERSE,),
    "Commentary": (INDEX_BIBLE_VERSE,),
    "StudyGuide": (INDEX_BIBLE_VERSE,),
    "SermonOutline": (INDEX_BIBLE_VERSE,),
    "Harmony": (INDEX_BIBLE_VERSE,),
    "CrossReference": (INDEX_BIBLE_VERSE,),
    "Lectionary": (INDEX_DATE, INDEX_BIBLE_VERSE),
    "Concordance": (INDEX_STRONGS, INDEX_LEMMA, INDEX_BIBLE_VERSE),
    "Lexicon": (INDEX_HEADWORD, INDEX_STRONGS, INDEX_LEMMA),
    "Dictionary": (INDEX_HEADWORD,),
    "Glossary": (INDEX_HEADWORD,),
    "Grammar": (INDEX_HEADWORD, INDEX_MORPH),
    "Syntax": (INDEX_BIBLE_VERSE,),
    "FactBook": (INDEX_TOPIC, INDEX_PERSON, INDEX_PLACE, INDEX_SENSE, INDEX_CULTURE, INDEX_EVENT),
    "Devotional": (INDEX_DATE, INDEX_SECTION),
    "Book": (INDEX_SECTION, INDEX_PAGE, INDEX_TOPIC),
    "Essay": (INDEX_ARTICLE,),
    "Atlas": (INDEX_PLACE,),
    "Map": (INDEX_PLACE,),
    "Illustration": (INDEX_PLACE,),
    "TopicalBible": (INDEX_TOPIC, INDEX_BIBLE_VERSE),
    "Media": (INDEX_SECTION,),
    "Manuscript": (INDEX_BIBLE_VERSE,),
    "Other": (INDEX_SECTION,),
}


# --------------------------------------------------------------------------
# Resource types
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceType:
    id: str
    label: str
    group: str
    # index into a "reference" unit of the reader
    reader: str          # verse | article | book | date | image | search
    singular: str = ""


TYPES: list[ResourceType] = [
    # --- Biblical text family ---
    ResourceType("Bible", "Bible", "Text", "verse"),
    ResourceType("StudyBible", "Study Bible", "Text", "verse"),
    ResourceType("ParallelBible", "Parallel / interlinear", "Text", "verse"),
    ResourceType("OriginalLanguage", "Original language text", "Text", "verse"),
    ResourceType("Manuscript", "Ancient manuscript", "Text", "verse"),
    ResourceType("Apologetics", "Apologetics", "Text", "verse"),
    # --- Commentaries & study ---
    ResourceType("Commentary", "Commentary", "Commentary", "verse"),
    ResourceType("StudyGuide", "Bible study / guide", "Commentary", "verse"),
    ResourceType("SermonOutline", "Sermon outline", "Commentary", "verse"),
    ResourceType("Harmony", "Harmony / synopsis", "Commentary", "verse"),
    ResourceType("CrossReference", "Cross-reference index", "Commentary", "verse"),
    ResourceType("TopicalBible", "Topical Bible", "Commentary", "verse"),
    # --- Language ---
    ResourceType("Lexicon", "Lexicon", "Language", "article"),
    ResourceType("Concordance", "Concordance", "Language", "article"),
    ResourceType("Dictionary", "Dictionary", "Language", "article"),
    ResourceType("Glossary", "Glossary", "Language", "article"),
    ResourceType("Grammar", "Grammar / morphology", "Language", "article"),
    ResourceType("Syntax", "Syntax treebank", "Language", "verse"),
    # --- Reference ---
    ResourceType("FactBook", "FactBook", "Reference", "topic"),
    ResourceType("Lectionary", "Lectionary", "Reference", "date"),
    # --- Dated ---
    ResourceType("Devotional", "Devotional", "Devotional", "date"),
    # --- Books ---
    ResourceType("Book", "Book", "Book", "book"),
    ResourceType("Essay", "Essay / article", "Book", "article"),
    # --- Visual ---
    ResourceType("Atlas", "Atlas", "Visual", "image"),
    ResourceType("Map", "Map", "Visual", "image"),
    ResourceType("Illustration", "Illustration", "Visual", "image"),
    ResourceType("Media", "Media", "Visual", "image"),
    # Audio is listed separately from Media because it is not a picture: it is
    # played, and a recording has a licence of its own that the user must be
    # able to see and assert.
    ResourceType("Audio", "Audio", "Audio", "audio"),
    # --- Fallback ---
    ResourceType("Other", "Other", "Other", "book"),
]

TYPE_BY_ID: dict[str, ResourceType] = {t.id: t for t in TYPES}

TYPE_GROUPS = ("Text", "Commentary", "Language", "Reference", "Devotional",
               "Book", "Visual", "Audio", "Other")


def reader_for(type_id: str) -> str:
    t = TYPE_BY_ID.get(type_id)
    return t.reader if t else "book"


def index_types_for(type_id: str) -> tuple[str, ...]:
    return TYPE_INDEX_TYPES.get(type_id, (INDEX_SECTION,))


# --------------------------------------------------------------------------
# Subjects  (the second, orthogonal facet)
# --------------------------------------------------------------------------

SUBJECTS: list[str] = [
    # Bible & text
    "OT",
    "NT",
    "Biblical Text",
    "Commentaries",
    "Textual Criticism",
    "Canon / Apocrypha",
    # Theology
    "Theological",
    "Systematic Theology",
    "Biblical Theology",
    "Christology",
    "Soteriology",
    "Eschatology",
    "Pneumatology",
    "Anthropology",
    "Hamartiology",
    "Angelology",
    "Providence",
    # Church
    "Church History",
    "Creeds & Confessions",
    "Discipleship",
    "Worship",
    "Missions",
    "Ministry / Leadership",
    "Preaching",
    "Sermon Preparation",
    "Pastoral Care",
    "Counselling",
    "Spiritual Formation",
    "Devotional",
    "Prayer",
    "Sanctification",
    "Sacred Music",
    # History & culture
    "Biblical History",
    "Ancient History",
    "Archaeology",
    "Culture / Customs",
    "Geography",
    # Language
    "Hebrew",
    "Greek",
    "Aramaic",
    "Latin",
    "Linguistics",
    "Translation",
    "Textual Imaging",
    # People
    "Biblical People",
    "Biblical Places",
    "Biographies",
    # Apologetics & related
    "Apologetics",
    "Philosophy",
    "Science & Faith",
    "Ethics",
    "Social Issues",
    # Ministry practice
    "Education",
    "Family",
    "Youth",
    "Health & Wholeness",
    "Community",
    # Literary
    "Literary Analysis",
    "Genre",
    "Poetry & Psalms",
    "Wisdom Literature",
    "Apocalyptic",
    "Gospel",
    "Epistles",
    "Pentateuch",
    "Historical Books",
    "Prophets",
    "General Reading",
]

SUBJECT_SET = set(SUBJECTS)


def normalise_subjects(raw) -> list[str]:
    out: list[str] = []
    for s in raw or ():
        s = str(s).strip()
        if not s:
            continue
        # Case-insensitive match against the controlled vocabulary.
        hit = next((k for k in SUBJECTS if k.lower() == s.lower()), None)
        if hit is None:
            hit = s  # keep unknown subjects rather than dropping them
        if hit not in out:
            out.append(hit)
    return out


def fix_text(text: str | None) -> str:
    """Repair mojibake in text that came from a third party.

    CrossWire's catalogue and two of its .conf files carry a stray byte pair
    where an apostrophe belongs, so a possessor reads "Naveߴs Topical Bible"
    and a French description reads "quߴelle".  Decoded as UTF-8 those two bytes
    are U+07F4 NKO HIGH TONE APOSTROPHE -- a real character in the wrong place,
    which is why it survives every encoding round-trip and reaches the screen
    intact.  It is not a decoding mistake we chose, it is a mistake in the
    upstream file, and U+07F4 does not appear in any English, French, German or
    Latin title in the catalogue.

    So it is repaired at the point the text is read rather than by special-
    casing two module ids: the ids are not the only affected entries, six of
    the 232 CrossWire items carry it, and new copies of the catalogue will
    arrive with it again.  If CrossWire ever fixes their own data this returns
    the string untouched, because the character is simply absent -- there is no
    stored rewrite to undo.

    Only this one character is touched, and only when it sits between two
    letters, so genuinely multilingual titles are left alone.
    """
    if not text:
        return ""
    return _STRAY_APOSTROPHE.sub("\\g<1>'\\g<2>", str(text))


# U+07F4 wedged between two word characters is a mangled apostrophe.
_STRAY_APOSTROPHE = re.compile(r"(\w)\u07f4(\w)")


# --------------------------------------------------------------------------
# Licences -- only these may be offered by the Store
# --------------------------------------------------------------------------

LICENSES: dict[str, dict] = {
    "Public Domain": {
        "code": "PD",
        "redistributable": True,
        "share_alike": False,
        "commercial": True,
        "attribution": False,
        "note": "No copyright. Free to copy, modify and redistribute.",
    },
    "CC0": {
        "code": "CC0",
        "redistributable": True,
        "share_alike": False,
        "commercial": True,
        "attribution": False,
        "note": "Public domain dedication. No conditions.",
    },
    "CC-BY-4.0": {
        "code": "CC-BY-4.0",
        "redistributable": True,
        "share_alike": False,
        "commercial": True,
        "attribution": True,
        "note": "Attribution required.",
    },
    "CC-BY-3.0": {
        "code": "CC-BY-3.0",
        "redistributable": True,
        "share_alike": False,
        "commercial": True,
        "attribution": True,
        "note": "Attribution required.",
    },
    "CC-BY-2.5": {
        "code": "CC-BY-2.5",
        "redistributable": True,
        "share_alike": False,
        "commercial": True,
        "attribution": True,
        "note": "Attribution required.",
    },
    "CC-BY-SA-4.0": {
        "code": "CC-BY-SA-4.0",
        "redistributable": True,
        "share_alike": True,
        "commercial": True,
        "attribution": True,
        "note": "Attribution required; derivatives must share alike.",
    },
    "CC-BY-SA-3.0": {
        "code": "CC-BY-SA-3.0",
        "redistributable": True,
        "share_alike": True,
        "commercial": True,
        "attribution": True,
        "note": "Attribution required; derivatives must share alike.",
    },
    "OFL-1.1": {
        "code": "OFL-1.1",
        "redistributable": True,
        "share_alike": True,
        "commercial": True,
        "attribution": False,
        "note": "SIL Open Font License -- fonts only.",
    },
}

# Aliases seen in the wild, mapped onto the controlled vocabulary above.
LICENSE_ALIASES = {
    "public domain": "Public Domain",
    "pd": "Public Domain",
    "publicdomain": "Public Domain",
    "no copyright": "Public Domain",
    "cc0": "CC0",
    "cc-0": "CC0",
    "creative commons: cc0": "CC0",
    "creative commons zero": "CC0",
    "cc by 4.0": "CC-BY-4.0",
    "cc-by-4.0": "CC-BY-4.0",
    "creative commons: by 4.0": "CC-BY-4.0",
    "cc by 3.0": "CC-BY-3.0",
    "cc by 2.5": "CC-BY-2.5",
    "cc by-sa 4.0": "CC-BY-SA-4.0",
    "cc by-sa 3.0": "CC-BY-SA-3.0",
    "creative commons attribution 4.0 international": "CC-BY-4.0",
    "creative commons attribution-sharealike 4.0 international": "CC-BY-SA-4.0",
    "cc-by-sa": "CC-BY-SA-4.0",
    "gfdl": "Public Domain",   # GFDL text of PD works is still PD text
    "copyrighted; freely distributable": "Public Domain",
    "gpl": "CC-BY-SA-4.0",     # treat conservatively
    "creative commons attribution 4.0": "CC-BY-4.0",
    "creative commons attribution 3.0": "CC-BY-3.0",
    "creative commons attribution 2.5": "CC-BY-2.5",
    "creative commons attribution-sharealike 4.0": "CC-BY-SA-4.0",
    "creative commons attribution-sharealike 3.0": "CC-BY-SA-3.0",
    "creative commons by 4.0": "CC-BY-4.0",
    "creative commons by 3.0": "CC-BY-3.0",
    "creative commons by-sa 4.0": "CC-BY-SA-4.0",
    "attribution 4.0 international": "CC-BY-4.0",
    "by-nc-sa": "Copyrighted",
    "by-nd": "Copyrighted",
    "by-nc": "Copyrighted",
    "non-commercial": "Copyrighted",
    "noncommercial": "Copyrighted",
    "free non-commercial distribution": "Copyrighted",
    "copyrighted; permission to distribute granted to crosswire": "CC-BY-4.0",
    "copyrighted; permission granted to distribute non-commercially in sword format": "Copyrighted",
    "copyrighted; free non-commercial distribution": "Copyrighted",
    "public domain (p.d.)": "Public Domain",
    "pd-self": "Public Domain",
    "free to use": "Public Domain",
}

# Licences we must never bundle.
LICENSE_DENY = {
    "cc-by-nc", "cc-by-nd", "cc-by-nc-sa", "cc-by-nc-nd", "copyrighted",
    "unknown", "proprietary", "all rights reserved",
}


def _flat(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_LICENSE_ALIAS_FLAT = {_flat(k): v for k, v in LICENSE_ALIASES.items()}
_LICENSE_DENY_FLAT = {_flat(d) for d in LICENSE_DENY}
_LICENSE_CANON_FLAT = {_flat(k): k for k in LICENSES}


def normalise_license(raw: str | None) -> str:
    """Map a licence string from any source onto the controlled vocabulary.

    Anything we cannot positively identify as freely redistributable becomes
    'Copyrighted' so the Store refuses to offer it -- the conservative default.
    """
    # A missing or blank licence is the case that matters most, and it used to
    # be read as "Public Domain" -- which is the one thing this function is
    # documented never to do.  Plenty of real sources simply omit the field: a
    # SWORD .conf with no DistributionLicense line, a repository entry with no
    # licence key.  Every one of those was being waved through as public domain,
    # and the default was invisible because the string it produced looked like a
    # decision rather than an absence.  An unstated licence is not a permission.
    if raw is None or not str(raw).strip():
        return "Copyrighted"
    s = str(raw).strip()
    low = s.lower()
    if low in LICENSE_ALIASES:
        return LICENSE_ALIASES[low]
    flat = _flat(s)
    for deny in _LICENSE_DENY_FLAT:
        if deny and deny in flat:
            return "Copyrighted"
    if flat in _LICENSE_ALIAS_FLAT:
        return _LICENSE_ALIAS_FLAT[flat]
    if flat in _LICENSE_CANON_FLAT:
        return _LICENSE_CANON_FLAT[flat]
    if "public domain" in low or flat in ("pd", "unlicense", "unlicensed", "none"):
        return "Public Domain"
    return "Copyrighted"


def license_ok(raw: str | None) -> bool:
    """Only freely-redistributable licences may be offered in the Store."""
    return normalise_license(raw) in LICENSES


# --------------------------------------------------------------------------
# Languages
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Language:
    code: str
    name: str


# ISO 639-2/T (and the 639-1 two-letter forms eBible actually uses) -> English
# name.  This is the mapping the Store's language dropdown is built from.
LANG_NAME: dict[str, str] = {
    "aar": "Afar", "abk": "Abkhazian", "afr": "Afrikaans", "aka": "Akan",
    "alb": "Albanian", "sqi": "Albanian", "als": "Albanian", "amh": "Amharic",
    "ara": "Arabic", "arg": "Aragonese", "arm": "Armenian", "hye": "Armenian",
    "asm": "Assamese", "ava": "Avaric", "ave": "Avestan", "aym": "Aymara",
    "ayr": "Aymara", "aze": "Azerbaijani", "bak": "Bashkir", "bam": "Bambara",
    "baq": "Basque", "eus": "Basque", "bel": "Belarusian", "ben": "Bengali",
    "bih": "Bihari", "bis": "Bisaya", "bod": "Tibetan", "tib": "Tibetan",
    "bos": "Bosnian", "bre": "Breton", "bul": "Bulgarian", "bur": "Burmese",
    "mya": "Burmese", "cat": "Catalan", "ceb": "Cebuano", "cha": "Chamorro",
    "chi": "Chinese", "zho": "Chinese", "cmn": "Chinese", "yue": "Cantonese",
    "cop": "Coptic", "cze": "Czech", "ces": "Czech", "dan": "Danish",
    "div": "Dhivehi", "dut": "Dutch", "nld": "Dutch", "dyu": "Dyula",
    "dzo": "Dzongkha", "ell": "Greek", "gre": "Greek", "grc": "Greek (Ancient)",
    "eng": "English", "en": "English", "epo": "Esperanto", "est": "Estonian",
    "ewe": "Ewe", "fao": "Faroese", "per": "Persian", "fas": "Persian",
    "fij": "Fijian", "fin": "Finnish", "fre": "French", "fra": "French",
    "ful": "Fulah", "geo": "Georgian", "kat": "Georgian", "ger": "German",
    "deu": "German", "gla": "Scottish Gaelic", "glg": "Galician", "glv": "Manx",
    "gre2": "Ancient Greek", "grn": "Guarani", "guj": "Gujarati", "hat": "Haitian",
    "hau": "Hausa", "hlt": "Hausa", "haw": "Hawaiian", "heb": "Hebrew",
    "hbo": "Hebrew (Biblical)", "hbr": "Hebrew", "hin": "Hindi", "hmn": "Hmong",
    "hrv": "Croatian", "hun": "Hungarian", "hye2": "Armenian", "ibo": "Igbo",
    "ice": "Icelandic", "ido": "Ido", "iii": "Sichuan Yi", "iku": "Inuktitut",
    "ile": "Interlingue", "ina": "Interlingua", "ind": "Indonesian", "ipk": "Inupiaq",
    "isl": "Icelandic", "ita": "Italian", "jav": "Javanese", "jpn": "Japanese",
    "kal": "Greenlandic", "khm": "Khmer", "kik": "Kikuyu", "kld": "Kildi",
    "kin": "Kinyarwanda", "kir": "Kyrgyz", "kom": "Komi", "kon": "Kongo",
    "kor": "Korean", "kua": "Kwangali", "kur": "Kurdish", "lao": "Lao",
    "lat": "Latin", "lav": "Latvian", "lij": "Ligurian", "lim": "Limburgish",
    "lin": "Lingala", "lit": "Lithuanian", "ltz": "Luxembourgish",
    "lub": "Luba-Katanga", "lug": "Ganda", "luo": "Luo", "lus": "Lushai",
    "mac": "Macedonian", "mkd": "Macedonian", "mah": "Marshallese",
    "mal": "Malayalam", "mao": "Maori", "mri": "Maori", "mar": "Marathi",
    "may": "Malay", "msa": "Malay", "mlg": "Malagasy", "mlt": "Maltese",
    "mon": "Mongolian", "mri2": "Maori", "msa2": "Malay", "nau": "Nauru",
    "nav": "Navajo", "nbl": "Ndebele", "nde": "North Ndebele", "ndo": "North Ndebele",
    "nep": "Nepali", "nno": "Norwegian Nynorsk", "nob": "Norwegian Bokmal",
    "nor": "Norwegian", "nya": "Chichewa", "oci": "Occitan", "oji": "Ojibwa",
    "ori": "Oriya", "orm": "Oromo", "oss": "Ossetian", "pan": "Punjabi",
    "per2": "Persian", "pli": "Pali", "pol": "Polish", "por": "Portuguese",
    "pus": "Pashto", "que": "Quechua", "roa": "Romance", "ron": "Romanian",
    "rum": "Romanian", "run": "Rundi", "rus": "Russian", "sag": "Sango",
    "san": "Sanskrit", "sin": "Sinhalese", "slo": "Slovak", "slk": "Slovak",
    "slv": "Slovenian", "sme": "Northern Sami", "smo": "Samoan", "sna": "Shona",
    "snd": "Sindhi", "som": "Somali", "sot": "Southern Sotho", "spa": "Spanish",
    "spn": "Spanish", "srd": "Sardinian", "srp": "Serbian", "ssw": "Swati",
    "sun": "Sundanese", "swa": "Swahili", "swh": "Swahili", "swe": "Swedish",
    "tah": "Tahitian", "tam": "Tamil", "tat": "Tatar", "tel": "Telugu",
    "tgk": "Tajik", "tgl": "Tagalog", "tha": "Thai", "tib": "Tibetan",
    "tir": "Tigrinya", "ton": "Tongan", "tsn": "Tswana", "tso": "Tsonga",
    "tuk": "Turkmen", "tur": "Turkish", "twi": "Twi", "uig": "Uighur",
    "ukr": "Ukrainian", "umb": "Umbundu", "urd": "Urdu", "uzb": "Uzbek",
    "ven": "Venda", "vie": "Vietnamese", "vol": "Volapuk", "wel": "Welsh",
    "cym": "Welsh", "wln": "Walloon", "wol": "Wolof", "xho": "Xhosa",
    "yid": "Yiddish", "ydd": "Yiddish", "yor": "Yoruba", "zap": "Zapotec",
    "zul": "Zulu",
    # Three-letter BCP-47 / SIL style codes seen in SWORD conf Lang= fields
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
    "da": "Danish", "no": "Norwegian", "fi": "Finnish", "pl": "Polish",
    "cs": "Czech", "sk": "Slovak", "hu": "Hungarian", "ro": "Romanian",
    "ru": "Russian", "uk": "Ukrainian", "sr": "Serbian", "hr": "Croatian",
    "bg": "Bulgarian", "el": "Greek", "he": "Hebrew", "ar": "Arabic",
    "tr": "Turkish", "fa": "Persian", "ur": "Urdu", "hi": "Hindi",
    "bn": "Bengali", "pa": "Punjabi", "gu": "Gujarati", "mr": "Marathi",
    "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam",
    "si": "Sinhalese", "th": "Thai", "lo": "Lao", "km": "Khmer",
    "my": "Burmese", "id": "Indonesian", "tl": "Tagalog", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "ka": "Georgian", "hy": "Armenian",
    "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "is": "Icelandic",
    "sw": "Swahili", "zu": "Zulu", "xh": "Xhosa", "af": "Afrikaans",
    "haw": "Hawaiian", "ht": "Haitian", "la": "Latin", "eo": "Esperanto",
    "chr": "Cherokee", "iku": "Inuktitut", "nv": "Navajo", "oj": "Ojibwa",
    "crk": "Cree", "wro": "Chinook Jargon", "dif": "Diba", "kky": "Kikuyu",
    "kld": "Kildi", "ksa": "Khasa", "kln": "Kalenjin", "ada": "Adangme",
    "alu": "Alur", "amh": "Amharic", "bbc": "Batak Toba", "gmy": "Gayo",
    "kek": "Kekchi", "kkj": "Kakata", "mwr": "Marwari", "noa": "Nimadi",
    "raj": "Rajasthani", "tcy": "Tocobaram", "unm": "Unami", "suj": "Subeji",
    "bfq": "Badaga", "gaa": "Ga", "kok": "Konkani", "mni": "Manipuri",
    "syl": "Sylheti", "ctg": "Chittagonian", "rkt": "Rangpuri", "bft": "Balti",
    "phr": "Pahari", "kfy": "Komi-Zyrian", "xal": "Kalmyk", "lez": "Lezghian",
    "tab": "Tabasaran", "agq": "Aghem", "kon2": "Kikongo", "suj2": "Subeji",
    "apc": "North Levantine Arabic", "prs": "Dari", "pes": "Iranian Persian",
    "aze": "Azerbaijani", "tuk": "Turkmen", "uig": "Uighur", "kir": "Kyrgyz",
    "tgk": "Tajik", "tat": "Tatar", "bak": "Bashkir", "chm": "Mari",
    "mhr": "Meadow Mari", "krc": "Karachay-Balkar", "kum": "Kumyk",
    "sah": "Yakut", "evn": "Evenki", "kef": "Khanty", "udm": "Udmurt",
    "kom": "Komi", "chv": "Chuvash", "myv": "Erzya", "mya": "Burmese",
    "syr": "Syriac", "syc": "Classical Syriac", "peo": "Old Persian",
    "ave": "Avestan", "arc": "Aramaic", "sam": "Samaritan Aramaic",
    "jrb": "Judeo-Arabic", "yhd": "Judeo-German", "lad": "Ladino",
    "roa": "Romance", "gsw": "Swiss German", "nds": "Low German",
    "vls": "Flemish", "zea": "Zeelandic", "li": "Limburgish",
    "srn": "Sranan Tongo", "acm": "Mesopotamian Arabic",
    "pbt": "Southern Pashto", "bal": "Baluchi", "kby": "Kanuri",
    "kbd": "Kabardian", "nog": "Nogai", "lez2": "Lezghian",
    "inh": "Ingush", "bxr": "Russia Buriat", "niv": "Gilyak",
    "mhr2": "Eastern Mari", "chm2": "Hill Mari", "xal2": "Kalmyk Oirat",
    "sah2": "Yakut", "unr": "Mundari", "kru": "Kurukh", "kha": "Khasi",
    "lus": "Lushai", "kok2": "Kokborok", "bfy": "Baghelkhandi",
    "noe": "Nimadi", "mwr2": "Marwari", "raj2": "Rajasthani",
    "smp": "Samite", "taj": "Tajaki", "bft2": "Balti", "wbl": "Wakhi",
    "tcv": "Tetum", "prs2": "Dari", "khw": "Khowar", "phr2": "Pahari",
    "xnr": "Kangri", "bfi": "British Sign Language", "ase": "American Sign Language",
}

LANGUAGES: list[Language] = []
_seen: set[str] = set()
for _c, _n in LANG_NAME.items():
    if _c in _seen:
        continue
    _seen.add(_c)
    LANGUAGES.append(Language(_c, _n))
LANGUAGES.sort(key=lambda l: (l.name, l.code))

LANG_BY_CODE: dict[str, Language] = {}
for _l in LANGUAGES:
    LANG_BY_CODE.setdefault(_l.code.lower(), _l)
    LANG_BY_CODE.setdefault(_l.name.lower(), _l)


def language_name(code: str | None) -> str:
    if not code:
        return "Unknown"
    c = code.strip()
    # ISO 639-2 uses "und" for a language that was never identified. It is not
    # a language, so it has no entry in the tables below, and letting it fall
    # through leaked the bare code into the Library's facet list.
    if c.lower() in ("und", "zxx", "mul"):
        return "Undetermined"
    if c in LANG_NAME:
        return LANG_NAME[c]
    low = c.lower()
    if low in LANG_BY_CODE:
        return LANG_BY_CODE[low].name
    if c.lower() in LANG_NAME:
        return LANG_NAME[c.lower()]
    # substring fallback, e.g. "eng-GB" -> "English"
    base = c.split("-")[0]
    if base in LANG_NAME:
        return LANG_NAME[base]
    for k, v in LANG_NAME.items():
        if k.startswith(base) and len(k) <= 4:
            return v
    # Nothing in the tables knows this one. Echoing the bare code made the
    # Library's facet list read "tlh" and "gez" as if they were names, so spell
    # out what happened instead and keep the code for anyone who needs it.
    return f"Unknown ({c})" if len(c) <= 8 else c


def language_options() -> list[tuple[str, str]]:
    """(English name, canonical code) sorted by name, for the Store dropdown."""
    best: dict[str, str] = {}
    for code, name in LANG_NAME.items():
        if len(code) == 3 and name not in best:
            best[name] = code
    return sorted(((n, c) for n, c in best.items()), key=lambda x: x[0])


# --------------------------------------------------------------------------
# Publication date matters as much as the licence string
# --------------------------------------------------------------------------
# A licence string is only the claim.  In the United States copyright runs from
# the date of publication, not from the death of the author, and every work
# published from 1930 onwards is still in copyright there today.  So an
# upstream that labels a 1930-1934 Bible translation "Public Domain" is making a
# statement that is true in most of the world and false in the one jurisdiction
# with the most users, and a tool that repeats it is repeating the error.
#
# Nothing that claims Public Domain and carries a publication year of 1930 or
# later is offered, unless it appears below with a reason.  The licence gate
# cannot see this: the string is "Public Domain" and the string passes.

#: Works published before this year are public domain in the US on age alone.
PD_SAFE_BEFORE = 1930

#: Public-domain claims on recent works, each with the evidence for the claim.
#: These are works whose authors or publishers *dedicated* them to the public
#: domain, which is a grant and not a date, so it holds regardless of when they
#: were published.  Remove one only if the dedication is withdrawn.
PD_DEDICATIONS: dict[str, str] = {
    "eng-web": "World English Bible: the World Bible Translation Center released "
               "it into the public domain by dedication in 2020.",
    "engwebp": "World English Bible (portrait): dedicated to the public domain by "
               "the World Bible Translation Center.",
    "eng-web-c": "World English Bible Catholic edition: dedicated to the public "
                 "domain by the World Bible Translation Center.",
    "eng-webbe": "World English Bible British edition (with deuterocanonical "
                 "books): dedicated to the public domain by the World Bible "
                 "Translation Center.",
    "engwebpb": "World English Bible British edition: dedicated to the public "
                "domain by the World Bible Translation Center.",
    "en-web": "World English Bible as catalogued by midvash, dated 2000. The same "
              "dedicated work as the eBible entries above; the date differs "
              "because that catalogue records the earlier revision, and the "
              "2020 revision is the one formally dedicated.",
    "grcmt": "Robinson-Pierpont Greek New Testament (2018): the authors placed it "
             "in the public domain, and eBible.org states the dedication.",
}


def pd_dated_ok(item: dict) -> tuple[bool, str]:
    """Is a Public Domain claim on a recent work actually safe to offer?

    Returns (allowed, reason).  `reason` is empty when allowed, and otherwise
    explains the refusal in words meant for a user rather than a log.
    """
    lic = normalise_license(item.get("license"))
    iid = str(item.get("id") or "").strip()
    if lic not in ("Public Domain", "CC0"):
        return (True, "")            # a current, explicit grant: date is irrelevant
    if iid in PD_DEDICATIONS:
        return (True, "")
    # An installed module's id is prefixed with the repository it came from
    # -- "ebible-eng-web" -- while the dedications are keyed by the item's
    # own id, "eng-web".  So the same material was judged legal in the Store
    # and illegal by the audit the moment it was installed, and the audit is
    # the one that decides whether the library as a whole is shippable.
    src = str(item.get("source") or item.get("repo") or "").strip()
    if src and iid.startswith(src + "-"):
        bare = iid[len(src) + 1:]
        if bare in PD_DEDICATIONS:
            return (True, "")
    raw = item.get("year") or item.get("year_from") or ""
    try:
        year = int(str(raw).strip())
    except (TypeError, ValueError):
        return (True, "")            # no year to judge it by
    if year < PD_SAFE_BEFORE:
        return (True, "")
    return (False,
            f"published {year} and offered as Public Domain, but copyright in the "
            f"United States runs from publication, so anything from "
            f"{PD_SAFE_BEFORE} onwards is still protected there. A few recent "
            f"works are listed as exceptions where the authors dedicated them to "
            f"the public domain; this one is not one of them.")


def redistributable(item: dict) -> tuple[bool, str]:
    """The full check: licence first, then the publication date."""
    lic = normalise_license(item.get("license"))
    if lic not in LICENSES:
        return (False, f"licence '{lic}' is not freely redistributable")
    return pd_dated_ok(item)
