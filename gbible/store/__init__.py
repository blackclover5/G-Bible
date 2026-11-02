"""The Store: repositories, catalogues, and install / remove.

Every repository is a static JSON catalogue shipped with the app, refreshed by a
scraper, and re-checked for licence before an item is offered.  A module is only
ever installed from an item whose licence passes `taxonomy.license_ok`; nothing
else can reach the library, so the legal guarantee is enforced in one place
rather than remembered by the caller.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .. import db, library, placement, taxonomy

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass
class RepoDef:
    id: str
    name: str
    vendor: str
    home: str
    kind: str                      # catalog | files | web
    catalog: str                   # JSON filename in DATA_DIR ("" if none)
    note: str = ""
    license_note: str = ""
    order: int = 0


REPOSITORIES: list[RepoDef] = [
    RepoDef("ebible", "eBible.org", "eBible.org / Bible Digital Library",
            "https://ebible.org", "catalog", "ebible.json",
            "USFM and SWORD packages. Public-domain translations only.",
            "Each module's own licence; the catalogue keeps only public-domain ones.",
            10),
    RepoDef("crosswire", "CrossWire SWORD", "CrossWire Bible Society",
            "https://crosswire.org", "catalog", "crosswire.json",
            "The SWORD module repository. Catalogue restricted to public-domain modules.",
            "Public-domain modules only; CC-BY-NC and CC-BY-ND modules are excluded.",
            20),
    RepoDef("wikisource", "Wikisource", "Wikimedia Foundation",
            "https://en.wikisource.org", "catalog", "wikisource.json",
            "Public-domain commentaries, concordances and dictionaries.",
            "All works are out of copyright. Content is fetched from the MediaWiki API.",
            30),
    RepoDef("openscriptures", "Open Scriptures", "Open Scriptures",
            "https://github.com/openscriptures", "catalog", "openscriptures.json",
            "Morphology-tagged Hebrew (OSHB) and the SBL Greek New Testament.",
            "CC BY 4.0 — attribution required and recorded in the Library.",
            40),
    RepoDef("stepbible-data", "STEPBible-Data", "STEP Bible Trust / Tyndale House",
            "https://github.com/STEPBible/STEPBible-Data", "catalog",
            "stepbible_data.json",
            "CC BY 4.0 datasets: brief lexica (TBESH/TBESG), full LSJ (TFLSJ), "
            "and individualised proper names with genealogy and geolocation (TIPNR). "
            "Installed as searchable text modules.",
            "CC BY 4.0 — attribution to 'STEP Bible' (www.STEPBible.org) required.",
            45),
    RepoDef("macula", "MACULA (Clear Bible)", "Clear Bible / Biblica",
            "https://github.com/Clear-Bible/macula-greek", "catalog",
            "macula.json",
            "CC BY 4.0 word-level linguistic data for the Greek NT (SBLGNT): "
            "morphology, glosses, word senses, semantic frames, participant "
            "referents. Installed as searchable text modules.",
            "CC BY 4.0 by Biblica/Clear Bible. The Louw-Nida (@ln) fields come "
            "from MARBLE 'used with permission'.",
            46),
    RepoDef("gutenberg", "Project Gutenberg", "Project Gutenberg",
            "https://www.gutenberg.org", "catalog", "gutenberg.json",
            "Books and devotionals in the public domain.",
            "All works are out of copyright in the United States.",
            50),
    RepoDef("wikimedia", "Wikimedia Commons", "Wikimedia Foundation",
            "https://commons.wikimedia.org", "catalog", "commons.json",
            "Maps, atlases and illustrations.",
            "Public Domain, CC0 and CC BY only; CC BY-SA images are excluded.",
            60),
    RepoDef("openbible-geo", "OpenBible Geography", "OpenBible.info / BiblePlaces.com",
            "https://www.openbible.info", "catalog", "geodata.json",
            "Bible place coordinates and the KML overlay for the map pane.",
            "CC BY 4.0. Map tiles derived from OpenStreetMap are not bundled.",
            70),
    RepoDef("midvash", "Midvash open data", "Midvash",
            "https://github.com/midvash/bible-data", "catalog", "midvash.json",
            "33 machine-readable Bible texts in 22 languages, one OSIS-keyed "
            "schema, shipped as whole-Bible JSON, per-book JSON or an indexed "
            "SQLite file. One download per version.",
            "Public domain per version. The Westminster Leningrad Codex carries "
            "its own licence and is therefore not listed.",
            80),
    RepoDef("open-bibles", "Open Bibles", "seven1m",
            "https://github.com/seven1m/open-bibles", "catalog", "openbibles.json",
            "USFX and OSIS texts, one file per translation. USFX carries a "
            "Strong's number on every word.",
            "Public Domain, CC BY 4.0 and CC BY-SA 4.0, per the repository's own "
            "table. The nine Zefania-XML files are not offered.",
            75),
    RepoDef("ccel-fathers", "CCEL Fathers",
            "Christian Classics Ethereal Library / Calvin University",
            "https://www.ccel.org/fathers", "catalog", "ccel_fathers.json",
            "The Fathers in English: the Ante-Nicene Fathers and the Nicene and "
            "Post-Nicene Fathers, offered as one item per work -- Irenaeus, "
            "Justin Martyr, Athanasius, Augustine, Chrysostom, Jerome -- rather "
            "than as the thirty-eight volumes they are printed in. Text in "
            "CCEL's own Theological Markup Language, so a Father's chapters "
            "stay chapters and the editors' footnotes stay footnotes.",
            "Public domain in the United States: Schaff's editions were "
            "published 1867-1887, and each volume's own <DC.Rights> is read "
            "from the file before it is offered. CCEL's site design and any "
            "special contents are Harry Plantinga's, © 1993-2020, and are not "
            "part of what is installed.",
            45),
    RepoDef("latin-patristic", "Latin Fathers",
            "The Latin Library (thelatinlibrary.com)",
            "https://thelatinlibrary.com/christian.html", "catalog",
            "latin_patristic.json",
            "Patristic works in Latin: Ambrose, Augustine, Jerome, Tertullian, "
            "Isidore, Leo the Great and others, offered one work (or one book) "
            "at a time.",
            "Public domain. Text scraped from The Latin Library, which hosts "
            "out-of-copyright Latin texts; original-language, not translated.",
            46),
    RepoDef("local", "This computer", "", "", "files", "",
            "Import a module file from disk. Accepts SWORD, USFM, e-Sword, "
            "MySword, plain text and EPUB-derived text.", "", 99),
]

REPO_BY_ID: dict[str, RepoDef] = {r.id: r for r in REPOSITORIES}


def _custom_repos_path() -> Path:
    from .. import db
    return Path(db.app_dir()) / "custom_repos.json"


def _disabled_repos_path() -> Path:
    from .. import db
    return Path(db.app_dir()) / "disabled_repos.json"


_DISABLED_REPOS: set[str] = set()
_p = _disabled_repos_path()
if _p.exists():
    try:
        _DISABLED_REPOS = set(json.loads(_p.read_text(encoding="utf-8")) or [])
    except (OSError, json.JSONDecodeError, TypeError):
        _DISABLED_REPOS = set()


def _load_custom_repos() -> None:
    p = _custom_repos_path()
    if not p.exists():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for entry in (raw if isinstance(raw, list) else []):
        try:
            rd = RepoDef(**entry)
        except (TypeError, ValueError):
            continue
        if rd.id in REPO_BY_ID:
            continue
        REPOSITORIES.append(rd)
        REPO_BY_ID[rd.id] = rd


def _save_custom_repos() -> None:
    p = _custom_repos_path()
    custom = [r for r in REPOSITORIES
              if r.id not in _BUILTIN_REPO_IDS]
    p.write_text(json.dumps([r.__dict__ for r in custom], indent=2),
                 encoding="utf-8")


_BUILTIN_REPO_IDS = {r.id for r in REPOSITORIES}

_load_custom_repos()


# --------------------------------------------------------------------------
# Catalogue loading
# --------------------------------------------------------------------------

def load_catalog(repo_id: str) -> dict:
    r = REPO_BY_ID.get(repo_id)
    if not r or not r.catalog:
        return {}
    p = DATA_DIR / r.catalog
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def repo_items(repo_id: str) -> list[dict]:
    """Normalised, licence-checked item list for a repository."""
    raw = load_catalog(repo_id)
    out: list[dict] = []
    for it in raw.get("items", []) or []:
        lic = taxonomy.normalise_license(it.get("license") or raw.get("license"))
        if not taxonomy.license_ok(lic):
            # The gate.  Nothing that is not freely redistributable is offered.
            continue
        # A licence string is a claim; the publication date can contradict it.
        # Works from 1930 onwards labelled "Public Domain" are still copyright
        # in the United States, so they are not offered unless they carry a
        # documented dedication.  Without this, a 1934 Bible translation whose
        # upstream simply says "public domain" is offered as redistributable.
        ok, _why = taxonomy.redistributable({**it, "license": lic})
        if not ok:
            continue
        item = dict(it)
        item["license"] = lic
        item["repo"] = repo_id
        item["repo_name"] = REPO_BY_ID[repo_id].name
        item["subjects"] = taxonomy.normalise_subjects(it.get("subjects"))
        item["category"] = _category(it, repo_id)
        item["lang"] = _lang(it, repo_id)
        item["lang_name"] = it.get("lang_name") or taxonomy.language_name(item["lang"])
        item["description"] = _strip_html(it.get("description") or it.get("about") or "")
        out.append(item)
    if repo_id == "openbible-geo":
        out = _geo_items(raw)
    if repo_id == "local":
        out = _local_items()
    return out


def _local_items() -> list[dict]:
    """Files already imported from this computer.

    "This computer" has no catalogue file, so its items live in the database
    instead: the import path records the file it was given, and the Store then
    lists what is already there.  Without this the import could never be
    repeated and the entry was a dead end -- `_find_item` had nothing to match
    against, so "Import a file..." failed before it started.
    """
    conn = db.connect()
    out: list[dict] = []
    for r in conn.execute(
            "SELECT * FROM store_item WHERE repo_id='local' "
            "ORDER BY title").fetchall():
        d = dict(r)
        try:
            subjects = json.loads(d.get("subject") or "[]")
        except (json.JSONDecodeError, TypeError):
            subjects = []
        out.append({
            "id": d["item_id"], "title": d["title"], "category": d["type"],
            "type": d["type"], "subjects": subjects,
            "lang": d.get("lang") or "", "license": d.get("license") or "",
            "attribution": d.get("rights") or "", "rights": d.get("rights") or "",
            "description": d.get("description") or "",
            "download_url": "", "path": d.get("download_url") or "",
            "size_bytes": d.get("size_bytes"), "format": d.get("format") or "",
            "repo": "local", "repo_name": REPO_BY_ID["local"].name,
            "year": d.get("year") or "",
            # The author lives in `extra` because the store_item table has no
            # column for it, and without it the installed module came out
            # anonymous however well the EPUB filled it in.
            "author": _extra_of(d).get("creator", ""),
        })
    return out


def _extra_of(row) -> dict:
    try:
        v = row["extra"]
        return json.loads(v) if isinstance(v, str) and v else (v or {})
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return {}


def register_local(path: Path, *, fmt: str = "", title: str = "",
                   category: str = "", extra: dict | None = None) -> dict:
    """Record a file chosen with "Import a file…" so it can be installed."""
    p = Path(path)
    item_id = library.slugify(p.stem) or "book"
    from .. import formats
    kind = fmt or formats.sniff(p.read_bytes() if p.is_file() else None, path=p)
    # An EPUB carries its own title and rights; anything else is named after
    # the file, because a library entry called "book" cannot be cited.
    meta: dict = dict(extra or {})
    if kind == "epub":
        try:
            found, _units = formats.load_epub(p.read_bytes())
            meta = {**found, **meta}
        except Exception:
            meta = dict(extra or {})
    elif kind == "thml":
        # A CCEL volume says the same things in its own head, and its licence is
        # the one thing worth having: read here, because a local import is
        # recorded against this row and the installer's own values lose to
        # whatever was recorded first.
        try:
            from ..formats import thml as _thml
            vm = _thml.volume_meta(p.read_text(encoding="utf-8",
                                               errors="replace"))
            meta = {**{"title": vm.title, "creator": vm.author or vm.editor,
                       "language": vm.language, "date": vm.first_published,
                       "rights": vm.rights, "description": vm.description,
                       "publisher": vm.url}, **meta}
        except Exception:
            meta = dict(extra or {})
    conn = db.connect()
    lic = taxonomy.normalise_license(meta.get("rights")
                                    or meta.get("publisher") or "")
    conn.execute(
        "INSERT INTO store_item(repo_id,item_id,title,type,subject,lang,"
        "license,rights,year,description,download_url,page_url,format,"
        "size_bytes,extra) VALUES('local',?,?,?,'[]',?,?,?,?,?,?,'',?,?,?) "
        "ON CONFLICT(repo_id,item_id) DO UPDATE SET title=excluded.title, "
        "type=excluded.type, lang=excluded.lang, license=excluded.license, "
        "rights=excluded.rights, description=excluded.description, "
        "download_url=excluded.download_url, format=excluded.format, "
        "size_bytes=excluded.size_bytes, extra=excluded.extra",
        (item_id, title or meta.get("title") or p.stem,
         category or _local_type(kind, meta), (meta.get("language") or "")[:8],
         lic, (meta.get("rights") or meta.get("publisher") or "")[:600],
         str(meta.get("date") or "")[:4], (meta.get("description") or "")[:4000],
         str(p), kind, p.stat().st_size if p.is_file() else 0,
         json.dumps(meta, default=str)[:4000]))
    conn.execute("INSERT OR REPLACE INTO repo(id,name,vendor,home,kind,note,"
                 "priority) VALUES('local',?,'','','files','',99)",
                 (REPO_BY_ID["local"].name,))
    conn.commit()
    return {"ok": True, "item_id": item_id, "format": kind, "path": str(p)}


def _local_type(kind: str, meta: dict) -> str:
    """What an imported file most likely is.

    A judgement, and the front end says so: the user picks from the list if
    this is wrong.  Guessing "Book" for an unknown file is better than
    refusing, but it is not a claim.
    """
    if kind in ("sword", "sword-zip", "usfm", "usfx", "osis"):
        return "Bible"
    if kind == "epub":
        desc = (meta.get("description") or "").lower()
        if "commentar" in desc:
            return "Commentary"
        return "Book"
    return "Book"


def _category(it: dict, repo_id: str) -> str:
    c = (it.get("category") or "").strip()
    alias = {
        "biblical texts": "Bible", "text": "Bible", "monograph": "Book",
        "commentaries": "Commentary", "bible commentary": "Commentary",
        "lexicons / dictionaries": "Lexicon", "lexicons": "Lexicon",
        "dictionaries": "Dictionary", "glossaries": "Glossary",
        "glossary": "Glossary", "daily devotional": "Devotional",
        "devotionals": "Devotional", "devotional": "Devotional",
        "generic books": "Book", "books": "Book", "maps": "Map", "map": "Map",
        "images": "Illustration", "atlas": "Atlas", "essays": "Essay",
        "concordance": "Concordance", "grammar": "Grammar",
        "topical bible": "FactBook", "factbook": "FactBook",
        "original language": "OriginalLanguage", "hebrew bible": "OriginalLanguage",
        "greek new testament": "OriginalLanguage", "lectionary": "Lectionary",
    }
    c = alias.get(c.lower(), c)
    if c in taxonomy.TYPE_BY_ID:
        return c
    return "Other"


def _lang(it: dict, repo_id: str) -> str:
    l = (it.get("lang") or it.get("language") or it.get("lang_code") or "")
    l = str(l).strip()
    if not l:
        return "und"
    if repo_id == "ebible" and len(l) == 3:
        return l
    return l


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"&amp;?", "&", s)
    s = re.sub(r"&quot;?", '"', s)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _geo_items(raw: dict) -> list[dict]:
    places = raw.get("places", []) or raw.get("items", [])
    return [{
        "id": f"{p.get('slug') or p.get('name','')}".strip().lower().replace(" ", "-"),
        "title": p.get("name", ""),
        "category": "Atlas",
        "subjects": ["Geography", "Biblical Places"],
        "lang": "eng",
        "lang_name": "English",
        "license": "CC-BY-4.0",
        "attribution": raw.get("attribution", ""),
        "lat": p.get("lat"),
        "lon": p.get("lon"),
        "passages": p.get("passages", []),
        "comment": p.get("comment", ""),
        "alt_names": p.get("alt_names", []),
        "repo": "openbible-geo",
        "repo_name": REPO_BY_ID["openbible-geo"].name,
        "description": " ".join(filter(None, [p.get("comment", ""),
                                              " ".join(p.get("passages", [])[:6])])),
        "is_place": True,
    } for p in places if p.get("name")]


# --------------------------------------------------------------------------
# Sync into the database (so the Store can filter and report install state)
# --------------------------------------------------------------------------

def sync(repo_id: str, *, force: bool = False) -> dict:
    conn = db.connect()
    r = REPO_BY_ID.get(repo_id)
    if not r:
        return {"ok": False, "error": "unknown repository"}
    if repo_id == "local":
        conn.execute("INSERT OR REPLACE INTO repo(id,name,vendor,home,kind,note,"
                     "priority) VALUES(?,?,?,?,?,?,?)",
                     (r.id, r.name, r.vendor, r.home, r.kind, r.note, r.order))
        conn.commit()
        return {"ok": True, "repo": r.id, "items": 0}

    items = repo_items(repo_id)
    conn.execute("INSERT OR REPLACE INTO repo(id,name,vendor,home,kind,note,"
                 "priority,item_count) VALUES(?,?,?,?,?,?,?,?)",
                 (r.id, r.name, r.vendor, r.home, r.kind, r.note, r.order, len(items)))
    # Preserve install state across a re-sync.
    known = {row["item_id"]: row["module_id"]
             for row in conn.execute(
                 "SELECT item_id, module_id FROM store_item WHERE repo_id=? "
                 "AND module_id IS NOT NULL", (repo_id,))}
    n = 0
    for it in items:
        _upsert_item(conn, repo_id, it, known.get(str(it.get("id"))))
        n += 1
    # Drop items that have disappeared from the catalogue and are not installed.
    ids = [str(it.get("id")) for it in items]
    if ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM store_item WHERE repo_id=? AND module_id IS NULL "
                     f"AND item_id NOT IN ({ph})", [repo_id, *ids])
    conn.execute("UPDATE repo SET last_sync=?, item_count=? WHERE id=?",
                 (time.time(), n, repo_id))
    conn.commit()
    return {"ok": True, "repo": repo_id, "items": n}


# Formats the app can install directly.  Anything else in a catalogue is a
# fallback mirror, and the first of these wins.  `thml` comes before `text`
# because a CCEL work is offered as one division of a volume and the volume's
# ThML is what the importer reads; the plain text of the same volume is the
# mirror, and picking it would record a download the installer never fetches.
_PREFERRED_FORMATS = ("usfm", "sword", "sword-zip", "sqlite", "json",
                      "usfx", "osis", "thml", "text", "wikitext", "xml", "kml",
                      "kmz", "image")


def _upsert_item(conn, repo_id: str, it: dict, module_id: str | None) -> None:
    dls = it.get("downloads") or []
    primary = ""
    fmt = ""
    size = it.get("size_bytes")
    for d in dls:
        if d.get("format") in _PREFERRED_FORMATS:
            primary = d.get("url", "")
            fmt = d.get("format", "")
            size = d.get("size_bytes") or size
            break
    if not primary:
        primary = it.get("download_url") or it.get("url") or ""
        fmt = it.get("format", "")
    if not fmt:
        # The catalogue may only name the format inside `downloads`; without
        # this the Library and the browser show a blank format and the audit
        # cannot tell what a payload was supposed to be.
        fmt = next((d.get("format", "") for d in dls if d.get("format")), "")
    if not size:
        size = it.get("size_bytes")
    year = str(it.get("year") or "")
    conn.execute(
        "INSERT INTO store_item(repo_id,item_id,title,type,subject,lang,lang_name,"
        "license,rights,version,author,year,year_from,year_to,description,"
        "download_url,page_url,format,size_bytes,checksum,module_id,extra) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(repo_id,item_id) DO UPDATE SET "
        " title=excluded.title, type=excluded.type, subject=excluded.subject, "
        " lang=excluded.lang, lang_name=excluded.lang_name, license=excluded.license, "
        " rights=excluded.rights, version=excluded.version, author=excluded.author, "
        " year=excluded.year, description=excluded.description, "
        " download_url=excluded.download_url, page_url=excluded.page_url, "
        " format=excluded.format, size_bytes=excluded.size_bytes, "
        " module_id=COALESCE(store_item.module_id, excluded.module_id), "
        " extra=excluded.extra",
        (repo_id, str(it.get("id")), it.get("title", ""), it.get("category", "Other"),
         json.dumps(it.get("subjects", [])), it.get("lang", ""),
         it.get("lang_name", ""), it.get("license", ""),
         it.get("attribution") or it.get("rights") or "", str(it.get("version") or ""),
         it.get("author", ""), year, _year_from(year), None,
         (it.get("description") or "")[:2000], primary, it.get("page_url", ""),
         fmt, size, it.get("checksum"), module_id,
         json.dumps(_trim_extra(it))))


def _trim_extra(it: dict) -> dict:
    keep = ("id", "abbrev", "modname", "datapath", "moddrv", "sourcetype",
            "api", "page_prefix", "top_pages", "subpage_count", "downloads",
            "files", "page_url", "commons_file", "attribution", "status",
            "lat", "lon", "passages", "comment", "alt_names", "is_place",
            "bookshelf", "feeds", "kmz", "license_url", "subtitle", "info_url",
            "cross_references", "footnotes", "figures", "category_source")
    return {k: it[k] for k in keep if k in it}


def _year_from(y: str) -> int | None:
    m = re.search(r"(1[0-9]{3}|20[0-9]{2})", y or "")
    return int(m.group(1)) if m else None


def sync_all() -> dict:
    out = {}
    for r in REPOSITORIES:
        if r.id in _DISABLED_REPOS:
            continue
        try:
            out[r.id] = sync(r.id)
        except Exception as e:
            out[r.id] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


# --------------------------------------------------------------------------
# Querying / faceting
# --------------------------------------------------------------------------

def list_items(*, repo: str | None = None, lang: str | None = None,
               category: str | None = None, subject: str | None = None,
               search: str | None = None, installed_only: bool = False,
               sort: str = "title", limit: int = 2000,
               slot: str | None = None) -> dict:
    conn = db.connect()
    placed: dict[str, dict] = {}
    # (id, name, source) for everything actually installed -- the only thing
    # that can answer "do I already have this?".
    installed = [(m.id, m.name, m.source) for m in library.list_all()]
    layouts: tuple = ()
    try:
        from .. import workspace
        layouts = tuple(workspace.list_layouts() or ())
    except Exception:
        layouts = ()
    q = ["SELECT s.*, (m.installed_at > 0) AS installed, m.name AS module_name, "
         "m.type AS module_type, m.verses AS module_verses, m.entries AS module_entries "
         "FROM store_item s LEFT JOIN module m ON m.id = s.module_id WHERE 1=1"]
    a: list = []
    if repo:
        q.append(" AND s.repo_id=?")
        a.append(repo)
    if lang:
        q.append(" AND s.lang=?")
        a.append(lang)
    if category:
        q.append(" AND s.type=?")
        a.append(category)
    if subject:
        q.append(" AND s.subject LIKE ?")
        a.append(f'%"{subject}"%')
    if search:
        q.append(" AND (s.title LIKE ? OR s.description LIKE ? OR s.author LIKE ?)")
        a += [f"%{search}%"] * 3
    order = {
        "slot": "s.type ASC, s.title ASC",
        "title": "s.title ASC",
        "-title": "s.title DESC",
        "lang": "s.lang_name ASC, s.title ASC",
        "year": "s.year_from ASC, s.title ASC",
        "-year": "s.year_from DESC, s.title ASC",
        "size": "s.size_bytes ASC",
        "-size": "s.size_bytes DESC",
        "installed": "installed DESC, s.title ASC",
        "category": "s.type ASC, s.title ASC",
    }.get(sort, "s.title ASC")
    q.append(f" ORDER BY {order}")
    # Placement is derived, not a column, so a slot filter has to run in Python.
    # Applying the SQL limit first would silently drop every matching row
    # whenever the alphabetical head of the catalogue is a different type.
    sql_limit = 0 if slot else int(limit or 0)
    if sql_limit:
        q.append(" LIMIT ?")
        a.append(sql_limit)
    rows = [dict(r) for r in conn.execute("".join(q), a)]

    if installed_only:
        rows = [r for r in rows if r.get("installed")]

    # "Goes in" is applied after the SQL filter because placement is derived
    # from the type and the override table, not stored in a column.
    if slot:
        rows = [r for r in rows
                if (placement.preview(r["repo_id"], r["item_id"],
                                      r.get("type") or "Other",
                                      r.get("title") or "")["slot"] == slot)]
    if slot and limit:
        rows = rows[:int(limit)]

    # Facets computed over the *filtered* set minus their own dimension, which is
    # what makes a facet useful: choosing a subject should still let you see all
    # the languages available under it.
    facets = {
        "repo": _facet(conn, repo, lang, category, subject, search, "repo_id"),
        "lang": _facet(conn, repo, None, category, subject, search, "lang"),
        "category": _facet(conn, repo, lang, None, subject, search, "type"),
        "subject": _subject_facet(conn, repo, lang, category, None, search),
        "license": _facet(conn, repo, lang, category, subject, search, "license"),
    }
    for r in rows:
        r["subject"] = _json(r.get("subject"))
        r["extra"] = _json_obj(r.get("extra"))
        r["lang_label"] = r.get("lang_name") or taxonomy.language_name(r.get("lang"))
        r["size_label"] = human_size(r.get("size_bytes"))
        _decorate(r, layouts, installed)
    return {"items": rows, "facets": facets, "total": len(rows),
            "slots": _slot_summary(rows)}


def _slot_summary(rows) -> list[dict]:
    """Placement slots present in this result set, with counts.

    The browser groups by these, so the grouping is computed once on the server
    from the same placement table the installer uses, and the counts come from
    the filtered set rather than from the whole catalogue.
    """
    from .. import placement
    n: dict[str, int] = {}
    for r in rows:
        slot = (r.get("placement") or {}).get("slot")
        if slot:
            n[slot] = n.get(slot, 0) + 1
    out = []
    for s in placement.SLOTS:
        if s.id in n:
            out.append({"id": s.id, "label": s.label, "reader": s.reader,
                        "glyph": s.glyph, "note": s.note, "count": n[s.id]})
    return out


def _decorate(r: dict, layouts, installed) -> None:
    """Attach placement and conflict information to one catalogue row.

    `layouts` is every saved layout, so a module can be reported as open in a
    pane; `installed` is (id, name, source) for everything in the library.
    """
    from .. import placement, taxonomy
    # Some upstream catalogues carry a mangled apostrophe in a title.  Repair it
    # here, on the way out, so the Store shows the title a reader would expect
    # and so a search for it matches; nothing is written back, so a corrected
    # upstream catalogue simply makes this a no-op.
    for k in ("title", "description", "author"):
        if r.get(k):
            r[k] = taxonomy.fix_text(r[k])
    item_id = str(r.get("item_id"))
    p = placement.preview(r["repo_id"], item_id, r.get("type") or "Other",
                          r.get("title") or "")
    r["placement"] = p
    if r.get("module_id"):
        r["in_use"] = placement.panes_using(r["module_id"], layouts)
    else:
        r["in_use"] = []
    r["duplicates"] = placement.duplicates_of_names(
        r.get("title") or "", r.get("repo_id") or "", str(r.get("item_id") or ""),
        installed)


def _facet(conn, repo, lang, category, subject, search, col) -> list[dict]:
    q = [f"SELECT {col} k, COUNT(*) n FROM store_item WHERE 1=1"]
    a: list = []
    if repo and col != "repo_id":
        q.append(" AND repo_id=?")
        a.append(repo)
    if lang and col != "lang":
        q.append(" AND lang=?")
        a.append(lang)
    if category and col != "type":
        q.append(" AND type=?")
        a.append(category)
    if subject and col != "subject":
        q.append(" AND subject LIKE ?")
        a.append(f'%"{subject}"%')
    if search:
        q.append(" AND (title LIKE ? OR description LIKE ? OR author LIKE ?)")
        a += [f"%{search}%"] * 3
    q.append(f" GROUP BY {col} ORDER BY n DESC, k ASC")
    out = []
    for r in conn.execute("".join(q), a):
        k = r["k"] or ""
        if not k:
            continue
        out.append({"key": k, "n": r["n"],
                    "label": _facet_label(col, k)})
    return out


def _facet_label(col: str, k: str) -> str:
    if col == "type":
        t = taxonomy.TYPE_BY_ID.get(k)
        return t.label if t else k
    if col == "lang":
        return taxonomy.language_name(k)
    if col == "repo_id":
        r = REPO_BY_ID.get(k)
        return r.name if r else k
    if col == "license":
        return k
    return k


def _subject_facet(conn, repo, lang, category, subject, search) -> list[dict]:
    q = ["SELECT subject FROM store_item WHERE subject IS NOT NULL"]
    a: list = []
    if repo:
        q.append(" AND repo_id=?")
        a.append(repo)
    if lang:
        q.append(" AND lang=?")
        a.append(lang)
    if category:
        q.append(" AND type=?")
        a.append(category)
    if search:
        q.append(" AND (title LIKE ? OR description LIKE ?)")
        a += [f"%{search}%"] * 2
    counts: dict[str, int] = {}
    for r in conn.execute("".join(q), a):
        for s in _json(r["subject"]):
            counts[s] = counts.get(s, 0) + 1
    order = {s: i for i, s in enumerate(taxonomy.SUBJECTS)}
    return [{"key": k, "n": v, "label": k}
            for k, v in sorted(counts.items(),
                               key=lambda x: (order.get(x[0], 999), -x[1]))]


def _json(s, default: list | None = None):
    """Parse a JSON column that holds a list (e.g. `subject`).

    Kept separate from `_json_obj` because a dict is also valid in these
    columns, and coercing a dict to `[]` is how every store item's `extra`
    metadata -- downloads, coordinates, attribution -- silently disappeared.
    """
    try:
        v = json.loads(s or "[]")
    except (json.JSONDecodeError, TypeError):
        return [] if default is None else default
    if isinstance(v, list):
        return v
    return [] if default is None else default


def _json_obj(s):
    """Parse a JSON column that holds an object (e.g. `extra`)."""
    try:
        v = json.loads(s or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def repos() -> list[dict]:
    conn = db.connect()
    out = []
    for r in REPOSITORIES:
        if r.id in _DISABLED_REPOS:
            continue
        row = conn.execute("SELECT last_sync, item_count FROM repo WHERE id=?",
                           (r.id,)).fetchone()
        n = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0 AND id LIKE ?",
            (f"{r.id}-%",)).fetchone()["c"]
        out.append({"id": r.id, "name": r.name, "vendor": r.vendor,
                    "home": r.home, "kind": r.kind, "note": r.note,
                    "license_note": r.license_note,
                    "item_count": (row["item_count"] if row else 0),
                    "installed_count": n,
                    "removable": r.id != "local",
                    "bundled": bool(r.catalog),
                    "last_sync": (row["last_sync"] if row else None)})
    return out


def remove_repo(repo_id: str, *, remove_installed: bool = False,
                permanent: bool = False, allow_installed: bool = False) -> dict:
    """Forget a repository: its catalogue rows go, and optionally its modules.

    Two separate effects, because they are two different decisions.  Dropping
    the catalogue is harmless and reversible -- "Refresh catalogues" brings the
    rows back.  Removing the installed modules deletes downloaded text, so it
    only happens when explicitly asked for, and the caller is told exactly which
    modules were affected *before* it does it via `repo_removal_preview`.
    """
    r = REPO_BY_ID.get(repo_id)
    if not r:
        return {"ok": False, "error": f"unknown repository: {repo_id}"}
    if repo_id == "local":
        return {"ok": False,
                "error": "'This computer' is not a downloadable repository; "
                         "remove individual modules from the Library instead."}
    conn = db.connect()
    items = conn.execute("SELECT COUNT(*) c FROM store_item WHERE repo_id=?",
                         (repo_id,)).fetchone()["c"]
    installed = [dict(x) for x in conn.execute(
        "SELECT id, name FROM module WHERE installed_at>0 AND id LIKE ?",
        (f"{repo_id}-%",))]
    if installed and not remove_installed and not allow_installed:
        return {"ok": False, "needs_confirmation": True,
                "error": f"{len(installed)} module(s) from {r.name} are still "
                         f"installed. Remove them too?",
                "modules": installed, "catalogue_items": items}
    removed_modules = []
    for m in installed:
        library.remove_module(m["id"])
        removed_modules.append(m)
    conn.execute("DELETE FROM store_item WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM repo WHERE id=?", (repo_id,))
    conn.commit()
    # If this was a user-added repository, forget it entirely (definition + file).
    if repo_id not in _BUILTIN_REPO_IDS:
        rd = REPO_BY_ID.get(repo_id)
        cat = getattr(rd, "catalog", "") if rd else ""
        REPOSITORIES[:] = [x for x in REPOSITORIES if x.id != repo_id]
        REPO_BY_ID.pop(repo_id, None)
        if cat:
            try:
                (DATA_DIR / cat).unlink()
            except OSError:
                pass
        _save_custom_repos()
    db.log_history("remove-repo", f"Removed repository {r.name}",
                   {"repo": repo_id, "items": items,
                    "modules": [m["id"] for m in removed_modules]})
    if permanent:
        _DISABLED_REPOS.add(repo_id)
        _disabled_repos_path().write_text(
            json.dumps(sorted(_DISABLED_REPOS)), encoding="utf-8")
        # A user-added repository is already gone from the in-memory list.
        if repo_id not in _BUILTIN_REPO_IDS:
            REPOSITORIES[:] = [x for x in REPOSITORIES if x.id != repo_id]
            REPO_BY_ID.pop(repo_id, None)
            _save_custom_repos()
    return {"ok": True, "repo": repo_id, "name": r.name,
            "catalogue_items": items, "removed_modules": removed_modules,
            "reinstorable": bool(r.catalog) and not permanent,
            "permanent": permanent}



def add_repo(source: str, *, name: str = "") -> dict:
    """Add a repository.

    `source` is either the id of a repository this app already knows about
    (in which case it is re-synced) or a URL pointing at a JSON catalogue.
    The catalogue is fetched and validated before anything is recorded: a dead
    host, a non-JSON answer, or a catalogue with no usable items all fail here
    with a message, and nothing is added.
    """
    import urllib.parse
    source = (source or "").strip()
    if not source:
        return {"ok": False, "error": "a repository URL or id is required"}

    # A known repository: just bring it back / refresh it.
    if source in _DISABLED_REPOS:
        _DISABLED_REPOS.discard(source)
        _disabled_repos_path().write_text(
            json.dumps(sorted(_DISABLED_REPOS)), encoding="utf-8")
    if source in REPO_BY_ID:
        r = sync(source)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "could not sync")}
        return {"ok": True, "repo": source, "name": REPO_BY_ID[source].name,
                "items": r.get("items", 0), "readded": True}

    url = source
    from pathlib import Path as _P
    local_path = None
    if url.startswith("file://"):
        local_path = _P(urllib.parse.urlsplit(url).path)
    elif _P(url).is_file():
        local_path = _P(url)

    import urllib.request, urllib.error, ssl, urllib.parse
    if local_path is not None:
        try:
            raw = local_path.read_bytes()
        except Exception as exc:
            return {"ok": False, "error": "repository unreachable: %s" % exc}
    else:
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "error": "unknown repository: %s" % source}
        ctx = ssl.create_default_context()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GBible/1.0",
                                                      "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read()
        except Exception as exc:
            return {"ok": False, "error": "repository unreachable: %s" % exc}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": "not a valid catalogue: %s" % exc}
    if not isinstance(data, dict):
        return {"ok": False, "error": "catalogue is not a JSON object"}
    items = data.get("items") or data.get("places") or []
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "catalogue has no items"}

    if local_path is not None:
        host = local_path.stem or "repo"
        home = str(local_path)
    else:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc or "repo"
        home = data.get("home") or ("%s://%s" % (parsed.scheme, parsed.netloc))
    slug = re.sub(r"[^a-z0-9]+", "-", str(host).lower()).strip("-") or "repo"
    base = slug
    i = 2
    while slug in REPO_BY_ID:
        slug = "%s-%d" % (base, i)
        i += 1
    repo_name = (name or data.get("name") or data.get("title")
                 or host).strip() or host
    vendor = data.get("vendor") or host
    note = data.get("note") or data.get("description") or ""
    license_note = data.get("license_note") or ""

    catalog_name = "custom-%s.json" % slug
    (DATA_DIR / catalog_name).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")

    rd = RepoDef(id=slug, name=repo_name, vendor=vendor, home=home,
                 kind="catalog", catalog=catalog_name, note=note,
                 license_note=license_note, order=999)
    REPOSITORIES.append(rd)
    REPO_BY_ID[rd.id] = rd
    # A freshly added repository is, by definition, one the user wants back.
    # Clear any stale "permanently deleted" flag so it shows in the dropdown.
    if rd.id in _DISABLED_REPOS:
        _DISABLED_REPOS.discard(rd.id)
        _disabled_repos_path().write_text(
            json.dumps(sorted(_DISABLED_REPOS)), encoding="utf-8")
    _save_custom_repos()

    r = sync(rd.id)
    if not r.get("ok"):
        REPOSITORIES[:] = [x for x in REPOSITORIES if x.id != rd.id]
        REPO_BY_ID.pop(rd.id, None)
        try:
            (DATA_DIR / catalog_name).unlink()
        except OSError:
            pass
        _save_custom_repos()
        return {"ok": False, "error": r.get("error", "sync failed")}
    if not r.get("items"):
        REPOSITORIES[:] = [x for x in REPOSITORIES if x.id != rd.id]
        REPO_BY_ID.pop(rd.id, None)
        try:
            (DATA_DIR / catalog_name).unlink()
        except OSError:
            pass
        _save_custom_repos()
        return {"ok": False,
                "error": "repository added, but no usable items "
                         "(unsuitable or all items failed the licence check)"}
    return {"ok": True, "repo": rd.id, "name": rd.name,
            "items": r.get("items", 0), "added": True}


add_repository = add_repo


def repo_removal_preview(repo_id: str) -> dict:
    """What removing this repository would touch, before anything happens."""
    r = REPO_BY_ID.get(repo_id)
    if not r:
        return {"ok": False, "error": f"unknown repository: {repo_id}"}
    conn = db.connect()
    items = conn.execute("SELECT COUNT(*) c FROM store_item WHERE repo_id=?",
                         (repo_id,)).fetchone()["c"]
    installed = [dict(x) for x in conn.execute(
        "SELECT id, name, type FROM module WHERE installed_at>0 AND id LIKE ?",
        (f"{repo_id}-%",))]
    return {"ok": True, "repo": repo_id, "name": r.name,
            "catalogue_items": items, "installed": installed,
            "removable": repo_id != "local",
            "bundled": bool(r.catalog)}


def store_item_row(repo_id: str, item_id: str):
    conn = db.connect()
    return conn.execute(
        "SELECT * FROM store_item WHERE repo_id=? AND item_id=?",
        (repo_id, str(item_id))).fetchone()


def human_size(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


# --------------------------------------------------------------------------
# Install / remove
# --------------------------------------------------------------------------

class InstallError(Exception):
    pass


def install(repo_id: str, item_id: str, *, fmt: str = "",
            force: bool = False) -> dict:
    """Download, convert and index one store item.  Synchronous and blocking;
    the server runs it in a worker thread and streams progress."""
    from ..importers import runner
    return runner.install(repo_id, item_id, fmt=fmt, force=force)


def remove(module_id: str) -> dict:
    return library.remove_module(module_id)


def installed_summary() -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT type, COUNT(*) n FROM module WHERE installed_at>0 GROUP BY type "
        "ORDER BY n DESC").fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM module WHERE installed_at>0"
                         ).fetchone()["c"]
    size = conn.execute("SELECT COALESCE(SUM(size_bytes),0) s FROM module "
                        "WHERE installed_at>0").fetchone()["s"]
    return {"by_type": [{"type": r["type"],
                         "label": taxonomy.TYPE_BY_ID[r["type"]].label
                         if r["type"] in taxonomy.TYPE_BY_ID else r["type"],
                         "n": r["n"]} for r in rows],
            "total": total, "size_bytes": size, "size_label": human_size(size)}
