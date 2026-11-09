"""API Settings.

Every network service the app knows about, in one list, with the three facts a
user needs: what it is, whether it needs a key, and where its website is.

Nothing here is required to use the app.  The local library, the search engine
and the reader all work offline; an API is an *additional* source you can point
the app at.  That is why `key_required` defaults to False and the UI says "No API
required" rather than presenting a wall of credentials.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from typing import Any

from .. import db

AUTH_NONE, AUTH_QUERY, AUTH_HEADER, AUTH_BEARER, AUTH_BASIC = (
    "none", "query", "header", "bearer", "basic")


@dataclass
class Api:
    id: str
    name: str
    vendor: str
    category: str                     # scripture | lexicon | maps | study | meta
    base_url: str = ""
    doc_url: str = ""
    site_url: str = ""
    key_required: bool = False
    auth: str = AUTH_NONE
    key_name: str = ""
    rate_limit: str = ""
    terms_url: str = ""
    license: str = ""
    notes: str = ""
    key_hint: str = ""
    formats: str = ""
    offline_ok: bool = False


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------
# Grouped by what the user is trying to do.  Anything whose licence forbids
# redistribution is marked as read-only / unavailable so the app never suggests
# it as a download source.

APIS: list[Api] = [
    # ---------------------------------------------------------------- Bible text
    Api("bible-api-com", "Bible API (bible-api.com)", "bible-api.com",
        "scripture", "https://bible-api.com", "https://bible-api.com/docs",
        "https://bible-api.com", False, AUTH_NONE, "", "Undocumented rate limit",
        "https://bible-api.com/terms", "Free to use",
        "Returns one verse as JSON. Simple, no key, and the translation set "
        "includes versions that are not freely redistributable, so this is a "
        "read-only lookup, not a download source.", "", "JSON"),
    Api("bolls-bible", "Bolls Bible API", "bolls.life",
        "scripture", "https://bolls.life", "https://bolls.life/api-docs",
        "https://bolls.life", True, AUTH_HEADER, "x-api-key",
        "10,000 requests/day", "https://bolls.life/terms",
        "Free for non-commercial use",
        "Broadest translation coverage of the free APIs, including audio, "
        "parallel translations and Strong's. Free key from the site. Do not "
        "redistribute the texts it returns unless their licence permits.",
        "Key issued at https://bolls.life", "JSON"),
    Api("scripture-api", "Scripture API (scrip.app)", "scrip.app",
        "scripture", "https://api.scrip.app", "https://scrip.app",
        "https://scrip.app", False, AUTH_NONE, "", "60 requests/minute",
        "https://scrip.app/terms", "Mixed - per-translation",
        "Multiple translations per call, Strong's numbers included, plus verse "
        "ranges. No key needed.", "", "JSON"),
    Api("bible-api-1", "bible-api (bibleapi.dev family)", "bibleapi.dev",
        "scripture", "https://bibleapi.dev/api", "https://bibleapi.dev/api",
        "https://bibleapi.dev", True, AUTH_QUERY, "api_key",
        "Varies by plan", "https://bibleapi.dev/terms", "Mixed",
        "REST schema with Strong's, morphology, topic tagging and verse ranges. "
        "Free tier available.", "Key from https://bibleapi.dev", "JSON"),
    Api("free-bible-api", "Free Bible API (getbible)", "getbible.net",
        "scripture", "https://getbible.net/api", "https://getbible.net/v2/docs",
        "https://getbible.net", True, AUTH_HEADER, "X-API-Key",
        "Plan dependent", "https://getbible.net/v2/terms", "Mixed",
        "JSON, XML and TEI. Strong's and a growing translation list.",
        "Key from https://getbible.net/v2", "JSON|XML|TEI"),
    Api("bible-gateway", "Bible Gateway API", "Bible Gateway / Zefania",
        "scripture", "https://biblegateway.com/api", "https://developers.biblegateway.com",
        "https://biblegateway.com", True, AUTH_QUERY, "key",
        "1,000 requests/day on the free tier",
        "https://developers.biblegateway.com/terms", "Mixed - per-version",
        "Very large catalogue including paid translations. Read-only lookup; the "
        "free versions are the only ones that may be redistributed.",
        "Key from developers.biblegateway.com", "JSON"),
    Api("biblecloud", "BibleCloud (Bolls Cloud)", "biblecloud.io",
        "scripture", "https://biblecloud.io/api", "https://biblecloud.io/api-documentation/",
        "https://biblecloud.io", True, AUTH_QUERY, "key",
        "Plan dependent", "https://biblecloud.io/terms", "Mixed",
        "Full Bible text, audio, video, books and study content as an API.",
        "Key from biblecloud.io", "JSON"),
    Api("api-bible", "API.Bible", "api.bible",
        "scripture", "https://api.bible", "https://api.bible/documentation",
        "https://api.bible", True, AUTH_HEADER, "X-API-Key",
        "Plan dependent", "https://api.bible/legal/terms",
        "Free for non-commercial use",
        "Broad catalogue with Strong's, morphology and translations. Free "
        "non-commercial key.", "Key from api.bible", "JSON"),
    Api("bible-one-api", "bible.one API", "bible.one",
        "scripture", "https://bible.one/api", "https://bible.one/api",
        "https://bible.one", False, AUTH_NONE, "", "Undocumented",
        "https://bible.one/terms", "Public domain subset",
        "Public-domain translations only, no key, no rate limit published.",
        "", "JSON"),
    Api("bible-search", "Bible Search API (bible-search.io)", "bible-search.io",
        "scripture", "https://bible-search.io/api", "https://bible-search.io",
        "https://bible-search.io", True, AUTH_QUERY, "api_key",
        "Undocumented", "https://bible-search.io/terms", "Mixed",
        "Full-text Bible search rather than verse lookup.",
        "Key from bible-search.io", "JSON"),
    Api("bible-midvash", "Midrash / Midvash Bible API", "Midvash",
        "scripture", "https://api.midvash.com", "https://github.com/midvash/bible-api",
        "https://midvash.com", True, AUTH_QUERY, "api_key",
        "Undocumented", "https://midvash.com/terms", "Copyrighted",
        "Midrash, Tanakh and Talmud text. Read-only reference; the content is "
        "copyrighted and may not be redistributed.", "Key from api.midvash.com",
        "JSON"),
    Api("berean-standard-bible", "Berean Standard Bible", "BSB Publishing, LLC",
        "scripture", "https://bible.helloao.org/api/BSB",
        "https://ebible.org/engbsb", "https://berean.bible",
        False, AUTH_NONE, "", "n/a", "https://ebible.org/engbsb/copyright.htm",
        "Public Domain",
        "Not an API but a text, listed because it is one of the few modern-sounding "
        "English translations that is genuinely free. 31,039 verses in 1,186 "
        "chapters -- its own versification, not the KJV's 31,102 -- and it installs "
        "from the eBible.org Store entry as USFM with Strong's on every word. BSB "
        "is also the worked example in the Free Use Bible API's documentation.",
        "", "USFM|SWORD|HTML"),
    Api("free-use-bible-api", "Free Use Bible API", "AO Lab",
        "scripture", "https://bible.helloao.org/api",
        "https://bible.helloao.org/docs/reference",
        "https://bible.helloao.org", False, AUTH_NONE, "",
        "None published - no limits", "https://www.helloao.org/free-api",
        "Public domain and free-to-redistribute texts only",
        "No key, no rate limit, no tracking. 1,000+ translations in 700+ "
        "languages, plus a commentary set and datasets, with formatting and "
        "footnotes preserved. "
        "/api/available_translations.json, /api/{tr}/books.json, "
        "/api/{tr}/{book}/{chapter}.json and a .simple.json variant, "
        "/api/available_commentaries.json, /api/available_datasets.json. "
        "The project is MIT on GitHub (HelloAOLab/bible-api), so the texts it "
        "carries can be installed locally, not merely looked up.",
        "", "JSON"),
    Api("openbible-info", "OpenBible.info", "openbible.info",
        "study", "https://openbible.info", "https://openbible.info/geo/",
        "https://openbible.info", False, AUTH_NONE, "", "n/a",
        "https://openbible.info/", "CC BY 4.0 for its own data",
        "Geocoding for every identifiable place in the Bible "
        "(openbible.info/geo) - this is the source of the 334-place coordinate "
        "set the Store installs, and it is safely redistributable. "
        "IMPORTANT: its Topical Bible and 340,000 cross-references are built on "
        "the English Standard Version, which is still in copyright, so those "
        "two features may be read but never bundled. The Labs section is "
        "experiments, some AI-generated, and is not a data source.",
        "", "HTML|JSON|KML"),
    Api("gnosis", "Gnosis Bible API", "Gnosis",
        "scripture", "", "", "https://gnosis.bible",
        True, AUTH_NONE, "", "Undocumented", "", "Proprietary",
        "Aggregates translations from many vendors under one key. Access is by "
        "account rather than a plain API key, and licence terms are per "
        "translation. Needs an account; the app cannot register for you.",
        "Account from gnosis.bible", "JSON"),
    Api("step-bible", "STEP Bible", "STEP Bible Trust",
        "scripture", "", "http://www.stepbible.org/wiki/index.php/Select_a_translation",
        "http://www.stepbible.org", False, AUTH_NONE, "", "n/a",
        "http://www.stepbible.org/wiki/index.php?title=Step_Bible_copyrights",
        "Free for non-commercial use; redistribution restricted",
        "Windows desktop application with its own interlinear data (morphology, "
        "Strong's, Hebrew/Aramaic glosses). Not redistributable -- install it "
        "separately and read the files directly. This app will read its data "
        "files if you point it at them, but it cannot download them.", "", "own"),
    Api("sword-api", "SWORD Project (local engine)", "CrossWire Bible Society",
        "scripture", "", "https://wiki.crosswire.org/DevTools:SWORD_Engine",
        "https://www.crosswire.org", False, AUTH_NONE, "", "n/a",
        "https://www.crosswire.org/software/sw/", "Public Domain modules",
        "Not an API but a reference implementation. Included because the module "
        "formats this app reads are the same ones it reads.", "", "own"),
    Api("ebible-api", "eBible.org (files)", "eBible.org",
        "scripture", "https://ebible.org", "https://ebible.org/find/",
        "https://ebible.org", False, AUTH_NONE, "", "Be polite",
        "https://ebible.org/rights.html", "Per-module; public domain set used",
        "The primary source of freely redistributable translations. No key; the "
        "app downloads and installs from here directly.", "", "USFM|SWORD|OSIS|HTML"),
    Api("unbound-door43", "Door43 / unbound (files)", "Door43",
        "scripture", "https://git.door43.org", "https://door43.org",
        "https://door43.org", False, AUTH_NONE, "", "n/a",
        "https://door43.org/en/copyright-and-licensing/", "CC BY-SA 4.0",
        "Open translation work. Share-alike, so the Store marks these "
        "separately and they are not bundled by default.", "", "USFM|TSV"),
    Api("openscriptures-api", "Open Scriptures (files)", "Open Scriptures",
        "scripture", "https://github.com/openscriptures",
        "https://openscriptures.github.io", "https://openscriptures.github.io",
        False, AUTH_NONE, "", "n/a", "https://creativecommons.org/licenses/by/4.0/",
        "CC BY 4.0",
        "The most useful open data in this space: the Open Scriptures Hebrew "
        "Bible with full morphology, and the SBL Greek New Testament. Both are "
        "CC BY 4.0 and install from the Store with attribution recorded.",
        "", "XML|USFM"),
    Api("crosswire-api", "CrossWire SWORD repository (files)",
        "CrossWire Bible Society", "scripture", "https://crosswire.org/ftpmirror",
        "https://wiki.crosswire.org/Zipped_modules", "https://www.crosswire.org",
        False, AUTH_NONE, "", "n/a", "https://crosswire.org/rights.html",
        "Public Domain modules used",
        "The SWORD module repository. The Store reads the public-domain subset.",
        "", "SWORD"),

    # ---------------------------------------------------------------- Lexicon
    Api("stepbible-lexicon", "STEP lexicon data (files)", "STEP Bible Trust",
        "lexicon", "", "http://www.stepbible.org/wiki/index.php/Lexicons",
        "http://www.stepbible.org", False, AUTH_NONE, "", "n/a",
        "http://www.stepbible.org/wiki/index.php?title=Step_Bible_copyrights",
        "Free for non-commercial use; redistribution restricted",
        "The best free Hebrew/Greek lexicons with morphology, but not "
        "redistributable. Read locally if you have it; the Store will not offer "
        "it for download.", "", "own"),
    Api("stepbible-data", "STEPBible-Data (GitHub)", "STEP Bible Trust / Tyndale House",
        "lexicon", "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master",
        "https://github.com/STEPBible/STEPBible-Data",
        "https://github.com/STEPBible/STEPBible-Data", False, AUTH_NONE, "", "n/a",
        "https://github.com/STEPBible/STEPBible-Data/blob/master/README.md",
        "CC BY 4.0",
        "A separate, freely redistributable dataset (TAGNT, TAHOT, TBESH, TBESG, "
        "TFLSJ, TIPNR, morphology codes, versification, variant/edition data) "
        "released by STEP Bible / Tyndale House under CC BY 4.0. Unlike the "
        "STEP Bible desktop app, this one MAY be bundled and installed. "
        "Attribution: 'STEP Bible' linked to www.STEPBible.org.", "", "TSV"),
    Api("macula-greek", "MACULA Greek (Clear Bible)", "Clear Bible / Biblica",
        "lexicon", "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main",
        "https://github.com/Clear-Bible/macula-greek",
        "https://github.com/Clear-Bible/macula-greek", False, AUTH_NONE, "", "n/a",
        "https://github.com/Clear-Bible/macula-greek/blob/main/LICENSE.md",
        "CC BY 4.0",
        "Syntax trees, morphology, word senses, semantic frames, participant "
        "referents and synonyms for the Greek NT (SBLGNT), CC BY 4.0 by "
        "Biblica/Clear Bible. The Louw-Nida (@ln/@domain) fields come from "
        "MARBLE 'used with permission' — treat that subset as permission-dependent. "
        "Freely downloadable; not yet wired into the Store installer.", "", "XML|TSV"),
    Api("macula-hebrew", "MACULA Hebrew (Clear Bible)", "Clear Bible",
        "lexicon", "https://raw.githubusercontent.com/Clear-Bible/macula-hebrew/main",
        "https://github.com/Clear-Bible/macula-hebrew",
        "https://github.com/Clear-Bible/macula-hebrew", False, AUTH_NONE, "", "n/a",
        "https://github.com/Clear-Bible/macula-hebrew/blob/main/LICENSE.md",
        "CC BY 4.0",
        "Syntax trees, morphology and word senses for the Hebrew Bible (WLC), "
        "CC BY 4.0 by Clear Bible. Freely downloadable; not yet wired into the "
        "Store installer.", "", "XML|TSV"),
    Api("bdb-lexicon", "Brown-Driver-Briggs (files)", "Open Scriptures",
        "lexicon", "https://github.com/openscriptures",
        "https://github.com/openscriptures/HebrewLexicon",
        "https://en.wikisource.org/wiki/A_Hebrew_and_English_Lexicon_(Brown-Driver-Briggs)",
        False, AUTH_NONE, "", "n/a", "https://creativecommons.org/licenses/by/4.0/",
        "CC BY 4.0 (openscriptures edition)",
        "The standard Hebrew lexicon, in structured XML. Installable.", "", "XML"),
    Api("strongs-lexicon", "Strong's dictionaries (files)", "Open Scriptures",
        "lexicon", "https://github.com/openscriptures/strongs",
        "https://github.com/openscriptures/strongs",
        "https://en.wikisource.org/wiki/Strong%27s_Exhaustive_Concordance",
        False, AUTH_NONE, "", "n/a", "https://creativecommons.org/licenses/by/4.0/",
        "Public domain text; CC BY 4.0 in this edition",
        "Strong's Greek and Hebrew, the concordance and the Hebrew/Greek "
        "lexical definitions. Installable from the Store.", "", "XHTML"),
    Api("os-morphhb", "OSHB morphology (files)", "Open Scriptures",
        "lexicon", "https://github.com/openscriptures/morphhb",
        "https://openscriptures.github.io/morphhb/",
        "https://openscriptures.github.io", False, AUTH_NONE, "", "n/a",
        "https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0",
        "Every Hebrew word tagged with a morphology code and a Strong's number, "
        "plus the code table. The most useful thing in this list for original "
        "language work, and fully installable.", "", "XML|TSV"),
    Api("sblgnt", "SBL Greek New Testament (files)", "SBL / publisher",
        "lexicon", "https://github.com/logosBible/SBLGNT",
        "https://github.com/logosBible/SBLGNT",
        "https://sblgnt.com", False, AUTH_NONE, "", "n/a",
        "https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0",
        "The SBL Greek New Testament, released under CC BY 4.0. "
        "Lexically tagged, which makes it a real word-study resource here.",
        "", "TXT|USFM"),
    Api("glosser", "Glosser / Morpho API", "Publisher",
        "lexicon", "", "https://www.logos.com/bible-software-help",
        "https://glosser.lgs.org", True, AUTH_BEARER, "Bearer",
        "Plan dependent", "https://www.logos.com/terms",
        "Proprietary - output only",
        "Morphological analysis of a word you paste in. Requires a "
        "subscription. The app can send a word and show the analysis, but cannot "
        "redistribute the results as a module.", "Account", "JSON"),

    # ---------------------------------------------------------------- Maps
    Api("openbible-geo", "OpenBible Geography", "OpenBible.info / BiblePlaces.com",
        "maps", "https://www.openbible.info/geo/", "https://www.openbible.info",
        "https://www.openbible.info", False, AUTH_NONE, "", "n/a",
        "https://www.openbible.info/", "CC BY 4.0",
        "Bible place coordinates with their passages, plus KML overlays for "
        "Google Earth. Installs straight into the map pane.", "", "TSV|KML|KMZ"),
    Api("bibleatlas", "Bible Atlas", "Bible Atlas",
        "maps", "", "", "https://bibleatlas.org", False, AUTH_NONE, "", "n/a",
        "", "Mixed",
        "A place-reference site rather than an API. Useful for cross-checking a "
        "place name, which is why it is listed.", "", "HTML"),
    Api("theographic", "Theographic Bible Metadata", "Theographic",
        "maps", "", "", "https://theographic.org", False, AUTH_NONE, "", "n/a",
        "https://theographic.org/", "CC BY 4.0 (data)",
        "Geocoded place data for Bible passages: a place's coordinates, the "
        "passages that mention it and its modern location. Comparable to the "
        "OpenBible data and useful for cross-checking.", "", "JSON"),
    Api("nominatim", "Nominatim (OpenStreetMap)", "OpenStreetMap Foundation",
        "maps", "https://nominatim.openstreetmap.org",
        "https://nominatim.org/release-docs/latest/api/Overview/",
        "https://www.openstreetmap.org", False, AUTH_NONE, "",
        "1 request/second", "https://operations.osmfoundation.org/policies/nominatim/",
        "ODbL (data)",
        "Geocoding for modern place names, so 'Bethlehem' resolves to a modern "
        "map location. Identifying a User-Agent is required by their policy.",
        "", "JSON"),
    Api("wikimedia-commons", "Wikimedia Commons", "Wikimedia Foundation",
        "maps", "https://commons.wikimedia.org/w/api.php",
        "https://commons.wikimedia.org/w/api.php",
        "https://commons.wikimedia.org", False, AUTH_NONE, "",
        "Be polite; 429 under rapid requests",
        "https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
        "Public Domain / CC0 / CC BY / CC BY-SA",
        "Historical maps, atlases and photographs. The Store installs the "
        "public-domain, CC0 and CC BY subset; CC BY-SA is excluded because of the "
        "share-alike condition.", "", "JPG|PNG|SVG"),
    Api("natural-earth", "Natural Earth", "Natural Earth",
        "maps", "https://www.naturalearthdata.com",
        "https://www.naturalearthdata.com/downloads/",
        "https://www.naturalearthdata.com", False, AUTH_NONE, "", "n/a",
        "https://www.naturalearthdata.com/about/terms-of-use/", "Public Domain",
        "Public-domain base geography for drawing a simple map without any tile "
        "service.", "", "SHP|GEOJSON"),

    # ---------------------------------------------------------------- Images
    Api("openverse", "Openverse", "WordPress Foundation",
        "media", "https://api.openverse.org/v1", "https://api.openverse.org/v1/",
        "https://openverse.org", False, AUTH_NONE, "",
        "Anonymous: 100/day, 5/hour", "https://api.openverse.org/v1/",
        "Per-item (CC0, PDM and CC BY)",
        "A single search across many open image sources, filtered to licences "
        "that permit reuse. Useful for finding an illustration the Store does not "
        "carry.", "", "JSON"),

    # ---------------------------------------------------------------- Verses / media
    Api("bible-audio", "Bible audio (BibleGateway / YouVersion shape)",
        "various", "media", "", "", "https://www.bibleaudio.com", False,
        AUTH_NONE, "", "varies", "", "Per-recording",
        "Chapter audio from the CrossWire and Crossway families. The app plays "
        "local files you already have; it does not bundle any.", "", "MP3"),
    Api("commons-audio", "Wikimedia Commons audio", "Wikimedia Foundation",
        "media", "https://commons.wikimedia.org/w/api.php",
        "https://commons.wikimedia.org/w/api.php",
        "https://commons.wikimedia.org", False, AUTH_NONE, "", "Be polite",
        "https://commons.wikimedia.org/wiki/Commons:Licensing",
        "Per-file", "Public-domain and CC recordings of scripture readings.",
        "", "OGG|MP3|WAV"),

    # ---------------------------------------------------------------- Metadata
    Api("midvash-bible-data", "BibleData (midvash/bible-data)", "Midvash",
        "scripture", "https://raw.githubusercontent.com/midvash/bible-data/main",
        "https://github.com/midvash/bible-data",
        "https://midvash.github.io/bible-data/", False, AUTH_NONE, "",
        "n/a", "https://github.com/midvash/bible-data/blob/main/SOURCES.md",
        "Public domain (per version); MIT for the code",
        "33 machine-readable Bible texts across 22 languages on one consistent "
        "OSIS-keyed schema, shipped three ways per version: whole-Bible JSON, "
        "one JSON per book, and an indexed SQLite file. Every version is public "
        "domain except the Westminster Leningrad Codex, which carries its own "
        "licence and is therefore excluded. Includes the Aleppo Codex, the "
        "Vulgate, Clementine, Textus Receptus and luther1912. Fully "
        "redistributable, so this is a real install source and not just a lookup.",
        "", "JSON|SQLite"),
    Api("jburson-bible-data", "BibleData (jburson/bible-data)", "jburson",
        "scripture", "https://raw.githubusercontent.com/jburson/bible-data/master",
        "https://github.com/jburson/bible-data",
        "https://github.com/jburson/bible-data", False, AUTH_NONE, "", "n/a",
        "https://github.com/jburson/bible-data", "Mixed - permission required",
        "The other well-known project called BibleData. Carries the usual "
        "markup DSL and footnote offsets, but it bundles ESV, NIV, NASB, NKJV and "
        "CSB, so it needs the copyright holders' permission and must not be "
        "redistributed. Listed so the name resolves, not offered as a source.",
        "", "JSON"),
    Api("bible-databases", "The Bible Database Project (scrollmapper)",
        "scrollmapper",
        "meta", "https://github.com/scrollmapper/bible_databases",
        "https://github.com/scrollmapper/bible_databases",
        "https://github.com/scrollmapper/bible_databases", False, AUTH_NONE, "",
        "n/a", "https://github.com/scrollmapper/bible_databases/blob/master/LICENSE",
        "MIT (tooling); texts vary",
        "Per-translation CSV/JSON/SQL dumps. WARNING: the repository bundles "
        "NIV, ESV and NASB, which are not freely redistributable. Only the "
        "public-domain versions may be used here.", "", "CSV|JSON|SQL|SQLite"),
    Api("bible-api-versions", "Bible version metadata", "wldeh/bible-api",
        "meta", "https://github.com/wldeh/bible-api",
        "https://github.com/wldeh/bible-api",
        "https://github.com/wldeh/bible-api", False, AUTH_NONE, "", "n/a",
        "https://github.com/wldeh/bible-api", "MIT",
        "A useful index of translation ids, languages and scopes. The copyright "
        "field is empty for most entries, so treat it as a reference table, not "
        "as a licence source.", "", "JSON"),
    Api("osis-core", "OSIS Core (schema)", "eBible.org / Bible Technologies",
        "meta", "https://ebible.org/osisCore.2.1.1.xsd",
        "https://ebible.org/osis/", "https://ebible.org", False, AUTH_NONE, "",
        "n/a", "https://ebible.org/osis/", "Public Domain schema",
        "The authoritative OSIS schema. The importers here are written against "
        "it.", "", "XSD"),
    Api("usfx", "USFX (schema)", "eBible.org", "meta", "https://ebible.org/usfx/",
        "https://ebible.org/usfx/", "https://ebible.org", False, AUTH_NONE, "",
        "n/a", "https://ebible.org/usfx/", "Public Domain", "USFX metadata schema.",
        "", "XSD"),
    Api("paratext-usfm", "USFM reference", "Paratext / SIL", "meta",
        "", "https://paratext.github.io/usfm/", "https://paratext.github.io",
        False, AUTH_NONE, "", "n/a", "https://paratext.github.io/usfm/",
        "Public Domain documentation",
        "The USFM specification the USFM importer follows.", "", "HTML"),
    Api("biblehub-api", "BibleHub", "biblehub.com", "meta", "", "",
        "https://biblehub.com", False, AUTH_NONE, "", "n/a", "", "Mixed",
        "A reference site rather than an API; several lexicon and grammar texts "
        "originate here. Licence varies by work, so nothing is bundled "
        "automatically.", "", "HTML"),
]

API_BY_ID = {a.id: a for a in APIS}

# Categories actually present in the `api` table, not just the ones this
# module's own list uses.  "study" is openbible-info, and "translate" holds the
# two translation providers, which live in their own registry but share the
# table -- both were missing here, so the settings screen's filter had no
# button that could ever show either of them.
CATEGORIES = ["scripture", "lexicon", "maps", "media", "study", "meta",
              "translate"]


# --------------------------------------------------------------------------
# Registry in the database
# --------------------------------------------------------------------------

def sync() -> int:
    conn = db.connect()
    n = 0
    for pos, a in enumerate(APIS):
        conn.execute(
            "INSERT INTO api(id,name,vendor,category,base_url,doc_url,site_url,"
            "key_required,auth,key_name,rate_limit,terms_url,license,notes,"
            "enabled,position) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "vendor=excluded.vendor, category=excluded.category, "
            "base_url=excluded.base_url, doc_url=excluded.doc_url, "
            "site_url=excluded.site_url, key_required=excluded.key_required, "
            "auth=excluded.auth, key_name=excluded.key_name, "
            "rate_limit=excluded.rate_limit, terms_url=excluded.terms_url, "
            "license=excluded.license, notes=excluded.notes, position=excluded.position",
            (a.id, a.name, a.vendor, a.category, a.base_url, a.doc_url,
             a.site_url, int(a.key_required), a.auth, a.key_name, a.rate_limit,
             a.terms_url, a.license, a.notes, 0, pos))
        n += 1
    conn.commit()
    return n


def list_apis(*, category: str | None = None, enabled_only: bool = False) -> list[dict]:
    conn = db.connect()
    if not conn.execute("SELECT COUNT(*) c FROM api").fetchone()["c"]:
        sync()
    q = "SELECT * FROM api"
    a: list = []
    if category:
        q += " WHERE category=?"
        a.append(category)
    elif enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY category, position, name"
    out = []
    for r in conn.execute(q, a):
        d = dict(r)
        # Never hand the key itself back to the browser.  `key_set` is all a
        # settings screen needs: it can say "key set", offer Clear, and offer an
        # empty field to replace it.  Returning the value meant rendering it into
        # a visible input, which put somebody else's credential on the page in
        # clear text where a screenshot, or any script, could read it.
        d["key_set"] = bool(key_for(d["id"]))
        d["key"] = ""
        d["key_required_label"] = ("No API required" if not d["key_required"]
                                   else (d["key_name"] or "API key required"))
        d["has_website"] = bool(d["site_url"] or d["doc_url"])
        # `key_set`, not `key`.  The two lines above blank `key` on purpose, so
        # testing it answered "is the key the empty string" -- always true --
        # and every key-requiring service reported "needs key" even with a key
        # stored.  It then looked broken in the one direction that annoys:
        # having supplied a key and still being told to supply one.
        if d["key_required"] and not d["key_set"]:
            d["status"] = "needs key"
        elif d["base_url"]:
            d["status"] = "available"
        else:
            # No base_url means there is nothing to call.  Previously this
            # branch tested `base_url or site_url`, and every record in the
            # catalogue has a site_url, so "reference only" was unreachable and
            # the selftest asserting a legal status was asserting nothing.
            d["status"] = "reference only"
        out.append(d)
    return out


def get_api(api_id: str) -> dict | None:
    for a in list_apis():
        if a["id"] == api_id:
            return a
    return None


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
# They live beside the database, not in it, and for the same reason sync
# credentials do: `gbible.db` is the file people copy, back up and attach to a
# support email.  A key for somebody else's account travelling with it is not a
# thing this project should do by default.
#
# They used to be written to the `api_key` table in plain text, which is the
# opposite of the rule `docs/sync.md` states and enforces for sync passwords.
# `tools/migrate_api_keys.py` moves any that were already stored; the table is
# kept so the schema does not move under anybody's feet, and it is emptied.


def credentials_path():
    return db.app_dir() / "api-credentials.json"


def _read_credentials() -> dict:
    p = credentials_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # A file that will not parse is not a reason to serve no keys at all,
        # but it is a reason not to overwrite it either: refuse rather than
        # clobber credentials the user still has.
        return {}


def _write_credentials(creds: dict) -> None:
    """Write the credential file, 0600, because it holds passwords."""
    import os
    p = credentials_path()
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(creds, fh)


def set_key(api_id: str, value: str) -> dict:
    value = (value or "").strip()
    creds = _read_credentials()
    if value:
        creds[api_id] = {"value": value, "set_at": time.time()}
    else:
        creds.pop(api_id, None)
    _write_credentials(creds)
    # Keep the old table honest rather than merely unused, so a database carried
    # to somebody else does not still contain the key.
    try:
        conn = db.connect()
        conn.execute("DELETE FROM api_key WHERE api_id=?", (api_id,))
        conn.commit()
    except Exception:                                     # noqa: BLE001
        pass
    return {"ok": True, "api_id": api_id, "key_set": bool(value)}


def set_enabled(api_id: str, enabled: bool) -> dict:
    conn = db.connect()
    conn.execute("UPDATE api SET enabled=? WHERE id=?", (int(bool(enabled)), api_id))
    conn.commit()
    return {"ok": True, "api_id": api_id, "enabled": bool(enabled)}


def key_for(api_id: str) -> str:
    """The key for `api_id`, from the credential file.

    Falls back to the `api_key` table so a library that has not been migrated
    yet keeps working; `tools/migrate_api_keys.py` moves what is there.
    """
    got = _read_credentials().get(api_id) or {}
    if got.get("value"):
        return str(got["value"])
    try:
        conn = db.connect()
        r = conn.execute("SELECT value FROM api_key WHERE api_id=?",
                         (api_id,)).fetchone()
    except Exception:                                     # noqa: BLE001
        return ""
    return (r["value"] if r else "") or ""


def summary() -> dict:
    rows = list_apis()
    return {
        "total": len(rows),
        "no_key_required": sum(1 for r in rows if not r["key_required"]),
        "needs_key": sum(1 for r in rows if r["key_required"]),
        "keys_set": sum(1 for r in rows if r["key_set"]),
        "enabled": sum(1 for r in rows if r["enabled"]),
        "by_category": {c: sum(1 for r in rows if r["category"] == c)
                        for c in CATEGORIES},
    }


# --------------------------------------------------------------------------
# Calling an API
# --------------------------------------------------------------------------

class ApiError(Exception):
    """A refused or failed API call.

    `hint` carries what to *do* about it.  translate.py refuses with the same
    shape, and for the same reason: "service switched off" is a dead end on its
    own, while "switch it on in API Settings" is an instruction, and a caller
    can show it next to the button that performs it.
    """

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def is_enabled(api_id: str) -> bool:
    """Whether the reader has switched this service on.  Default: no."""
    r = db.connect().execute("SELECT enabled FROM api WHERE id=?",
                             (api_id,)).fetchone()
    return bool(r and r["enabled"])


# Nominatim's usage policy requires an identifying User-Agent and limits
# anonymous use to one request a second; Openverse's anonymous tier is
# 100/day and 5/hour.  Those were display strings.  This is the minimum
# behaviour that keeps them honest, per-process.
_LAST_CALL: dict[str, float] = {}

#: Minimum seconds between two calls to the same service.
_THROTTLE = {"nominatim": 1.05}


def _throttle(api_id: str) -> None:
    gap = _THROTTLE.get(api_id)
    if not gap:
        return
    import time as _time
    wait = gap - (_time.time() - _LAST_CALL.get(api_id, 0.0))
    if wait > 0:
        _time.sleep(wait)
    _LAST_CALL[api_id] = _time.time()


#: A service answering with more than this is not a service we asked a question
#: of.  Nothing in this registry returns anything close to 8 MB.
_MAX_BYTES = 8 * 1024 * 1024
_RETRY_STATUS = (403, 429, 500, 502, 503, 504)
_USER_AGENT = "GBible/1.0 (local Bible study app)"


def _error_detail(e: Exception) -> str:
    """What the service said about the failure, in its own words.

    DRF services -- which is what Openverse is -- answer a rejected request with
    a JSON body carrying the rule that rejected it.  Reading it turns "HTTP 401"
    into "page_size may not exceed 20 for anonymous requests", which is the
    difference between a bug report and a fix.
    """
    try:
        import json as _json
        raw = e.read()                       # type: ignore[attr-defined]
        if not raw or len(raw) > 20000:
            return ""
        d = _json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                # noqa: BLE001
        return ""
    if isinstance(d, dict):
        for k in ("detail", "error", "message", "reason"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:300]
            if isinstance(v, dict):
                inner = " ".join(str(x) for x in v.values() if isinstance(x, str))
                if inner.strip():
                    return inner.strip()[:300]
        if isinstance(d.get("errors"), list) and d["errors"]:
            return str(d["errors"][0])[:300]
    return ""


def _fetch(url: str, *, timeout: int, attempts: int = 3) -> tuple[str, bytes]:
    """GET with a size cap and a bounded retry.  Returns (content-type, body).

    Copied in shape from importers/runner._fetch_retry, which already does this
    correctly for bulk installs; reusing it rather than inventing a second one
    is also why the TLS-bypass context it uses is deliberately *not* reused --
    that is acceptable for a mirror serving files and not for an interactive
    call on behalf of the reader.
    """
    import time as _time
    import urllib.error
    import urllib.request
    delay = 0.8
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/plain, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "") if r.headers else ""
                clen = r.headers.get("Content-Length") if r.headers else None
                if clen and clen.isdigit() and int(clen) > _MAX_BYTES:
                    raise ApiError(
                        f"response is {int(clen)} bytes, over the "
                        f"{_MAX_BYTES} byte limit")
                raw = r.read(_MAX_BYTES + 1)
                if len(raw) > _MAX_BYTES:
                    raise ApiError(
                        f"response exceeds the {_MAX_BYTES} byte limit")
            return ctype, raw
        except urllib.error.HTTPError as e:
            last = e
            # A service that explains itself in the body is worth reading.  The
            # alternative is what this raised before: "HTTP Error 401:
            # Unauthorized" for a service whose actual complaint was "page_size
            # may not exceed 20 for anonymous requests" -- a rule the caller can
            # act on, in a message that says nothing at all.
            detail = _error_detail(e)
            if detail and e.code not in _RETRY_STATUS:
                raise ApiError(f"{url.split('?')[0]}: {detail}")
            if e.code not in _RETRY_STATUS or i == attempts - 1:
                raise
            wait = delay
            try:
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.strip().isdigit():
                    wait = min(30.0, float(ra.strip()))
            except Exception:
                pass
            _time.sleep(wait)
            delay = min(8.0, delay * 2)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if i == attempts - 1:
                raise
            _time.sleep(delay)
            delay = min(8.0, delay * 2)
    raise last


def cache_get(api_id: str, key: str, kind: str = "call",
              max_age: float = 86400) -> Any | None:
    """A previous answer to the same question, if it is still fresh.

    Repeatable lookups -- a place name that has already been resolved, a
    licence check -- otherwise re-ask on every keystroke, and the quota for
    several of these services is small enough that a reader exploring the
    catalogue would exhaust it without noticing.
    """
    r = db.connect().execute(
        "SELECT payload, fetched FROM api_cache WHERE api_id=? AND kind=? "
        "AND key=?", (api_id, kind, key)).fetchone()
    if not r or (time.time() - r["fetched"]) > max_age:
        return None
    try:
        out = json.loads(r["payload"])
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(out, dict):
        out["cached"] = True
    return out


def cache_put(api_id: str, key: str, payload: Any, kind: str = "call") -> None:
    """Record an answer.  A cache fault must never lose the answer."""
    try:
        db.connect().execute(
            "INSERT OR REPLACE INTO api_cache(api_id,kind,key,payload,fetched)"
            " VALUES(?,?,?,?,?)",
            (api_id, kind, key,
             json.dumps(payload, ensure_ascii=False)[:4_000_000],
             time.time()))
        db.connect().commit()
    except Exception:                                     # noqa: BLE001
        pass


def call(api_id: str, path: str = "", *, params: dict | None = None,
         timeout: int = 30) -> Any:
    """Call a configured API with its key applied.  Read-only, GET only.

    Four things this must do that it did not, each of which turned a "call an
    API" feature into a way for the application to make requests nobody asked
    for, slowly, without limit.

    **It must require the service to be switched on.**  Nothing here consulted
    the `enabled` column, so `call()` fired for a service the user had never
    touched -- which matters because this is the function every future feature
    would sit on.  The gate refuses with a hint naming the screen, the way
    translate() does, rather than failing silently.

    **It must not fall back to the human website.**  Ten of the 45 records are
    reference pages with no API -- Theographic, STEP Bible, sword-api, the
    Gnosis site.  Resolving those against `site_url` meant `call("theographic")`
    issued a real GET to the marketing page and returned its HTML as if it were
    data.  A record with no `base_url` now raises, which is also what makes
    `status == "reference only"` reachable instead of dead code.

    **It must bound the response and retry.**  `r.read()` with no cap is one
    unlucky endpoint returning 200 MB into memory, and a single 429 from a rate
    limit aborted the call with nothing to show for it.

    **It must not hammer a service.**  `rate_limit` was a display string, so
    Nominatim's "1 request/second" -- which their usage policy requires, and
    which gets an app blocked -- was text in a settings screen rather than
    behaviour.
    """
    import urllib.parse
    import urllib.request

    a = API_BY_ID.get(api_id)
    if a is None:
        raise ApiError(f"unknown API {api_id}")
    if not is_enabled(api_id):
        raise ApiError(
            f"{a.name} is switched off.",
            hint="Open API Settings and switch "
                 f"'{a.name}' on. Nothing is sent anywhere until you do.")
    # No site_url fallback: a service with no base_url is a reference page, and
    # GETting its home page would return a web page dressed up as an answer.
    base = (a.base_url or "").rstrip("/")
    if not base:
        raise ApiError(f"{a.name} has no API endpoint; it is a reference site",
                       hint=f"See {a.doc_url or a.site_url or 'its documentation'}.")
    url = base + ("/" + path.lstrip("/") if path else "")
    q = dict(params or {})
    key = key_for(api_id)
    headers = {"User-Agent": _USER_AGENT,
               "Accept": "application/json, text/plain, */*"}
    if key:
        if a.auth == AUTH_QUERY and a.key_name:
            q[a.key_name] = key
        elif a.auth == AUTH_HEADER and a.key_name:
            headers[a.key_name] = key
        elif a.auth == AUTH_BEARER:
            headers["Authorization"] = f"Bearer {key}"
        elif a.auth == AUTH_BASIC:
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(
                key.encode()).decode()
    if q:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    _throttle(api_id)
    ctype, raw = _fetch(url, timeout=timeout)
    if "json" in ctype:
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise ApiError(f"{a.name} returned malformed JSON: {e}") from e
    return raw.decode("utf-8", "replace")
