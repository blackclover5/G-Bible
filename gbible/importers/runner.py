"""Install runner: fetch a store item, convert it, index it, register it.

Every repository funnels through here so there is exactly one place that decides
what a module's metadata is, one place that checks the licence, and one place
that records the transfer for the Activity view.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import re
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Iterator

from .. import canon, db, formats, indexer, library, markup, taxonomy
from ..formats import esword, latinlib, plain, sword, thml, usfm
from ..indexer import UnitIn
from ..markup import Seg
from ..store import DATA_DIR, REPO_BY_ID, human_size, repo_items, store_item_row

UA = ("GBible/1.0 (open-source Bible study app; "
      "+https://example.invalid/gbible) Python-urllib")

_ctx = ssl.create_default_context()


class Progress:
    def __init__(self, transfer_id: str):
        self.transfer_id = transfer_id
        self.conn = db.connect()
        self.t0 = time.time()

    def __call__(self, phase: str, done: int = 0, total: int = 0, note: str = ""):
        msg = note or (f"{phase} {done}" + (f"/{total}" if total else ""))
        try:
            self.conn.execute(
                "UPDATE transfer SET message=?, started=? WHERE id=?",
                (msg[:400], time.time(), self.transfer_id))
            self.conn.commit()
        except Exception:
            pass


def _open(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    })
    if url.lower().startswith("https"):
        return urllib.request.urlopen(req, timeout=timeout, context=_ctx)
    return urllib.request.urlopen(req, timeout=timeout)


# Wikimedia and several module hosts answer 403/429 when a bulk install
# arrives faster than their rate limit expects.  Installing a 2,000-page
# dictionary is dozens of requests back to back, so a single refusal would
# otherwise abort the whole install and leave the user with nothing.
_RETRY_STATUS = (403, 429, 500, 502, 503, 504)


def _fetch_retry(url: str, *, timeout: int, attempts: int = 4):
    delay = 1.5
    last: Exception | None = None
    for i in range(attempts):
        try:
            return _open(url, timeout=timeout)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in _RETRY_STATUS or i == attempts - 1:
                raise
            # 429 and some 403s carry a Retry-After; honour it when present.
            wait = delay
            try:
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.strip().isdigit():
                    wait = min(30.0, float(ra.strip()))
            except Exception:
                pass
            time.sleep(wait)
            delay = min(20.0, delay * 2)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if i == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(20.0, delay * 2)
    raise last


_URL_FIXUPS = (
    # CrossWire's FTP host refuses the rawzip packages (HTTP 550) and has done
    # so intermittently for years.  The HTTPS ftpmirror carries identical files
    # under identical names, so prefer it and keep the path case -- the mirror
    # is case-sensitive and a lower-cased name 404s.
    ("ftp://ftp.crosswire.org/pub/sword/",
     "https://crosswire.org/ftpmirror/pub/sword/"),
    ("http://ftp.crosswire.org/pub/sword/",
     "https://crosswire.org/ftpmirror/pub/sword/"),
    ("ftp://crosswire.org/pub/sword/",
     "https://crosswire.org/ftpmirror/pub/sword/"),
)


def canonical_url(url: str) -> str:
    for bad, good in _URL_FIXUPS:
        if url.startswith(bad):
            return good + url[len(bad):]
    return url


def fetch(url: str, dest: Path | None = None, *, timeout: int = 120,
          max_bytes: int = 0, checksum: str = "") -> bytes:
    url = canonical_url(url)
    with _fetch_retry(url, timeout=timeout) as r:
        if dest is None:
            data = r.read()
        else:
            n = 0
            with dest.open("wb") as f:
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    n += len(chunk)
                    if max_bytes and n > max_bytes:
                        raise InstallErrorFailed(
                            f"download exceeded {human_size(max_bytes)}: {url}")
                    f.write(chunk)
            data = dest.read_bytes()
    _verify_checksum(data, checksum, url)
    return data


def _verify_checksum(data: bytes, checksum: str, url: str) -> None:
    value = str(checksum or "").strip().lower()
    if not value:
        return
    match = re.fullmatch(r"(?:(sha-?256|sha-?1|md5)[:=])?([0-9a-f]+)", value)
    if not match:
        raise InstallErrorFailed(f"invalid download checksum for {url}")
    algorithm = (match.group(1) or {
        64: "sha256", 40: "sha1", 32: "md5",
    }.get(len(match.group(2)), "")).replace("-", "")
    digest = match.group(2)
    try:
        expected_length = hashlib.new(algorithm).digest_size * 2
    except ValueError as exc:
        raise InstallErrorFailed(
            f"unsupported download checksum algorithm for {url}") from exc
    if len(digest) != expected_length:
        raise InstallErrorFailed(f"invalid download checksum for {url}")
    actual = hashlib.new(algorithm, data).hexdigest()
    if not hmac.compare_digest(actual, digest):
        raise InstallErrorFailed(f"download checksum mismatch for {url}")


def _checksum_for(it: dict, download: dict | None, url: str) -> str:
    if download:
        checksum = download.get("checksum") or download.get("sha256")
        if checksum:
            return str(checksum)
    primary = it.get("download_url") or it.get("url")
    if not primary or canonical_url(str(primary)) == canonical_url(url):
        return str(it.get("checksum") or it.get("sha256") or "")
    return ""


class InstallErrorFailed(Exception):
    pass


# Set only for repositories whose entire catalogue is known to be public domain
# (currently eBible.org and Wikimedia Commons, both of which publish only
# dedicated freely-licensed texts under those terms).
_UNSTATED_IS_PD = "Public Domain"


class InstallErrorIncomplete(InstallErrorFailed):
    """The upstream source is itself a stub, not a failed download.

    Worth its own class: the message is advice about the *source*, not a retry
    hint, and the Store should not offer a "try again" button for it.
    """


# --------------------------------------------------------------------------

def _find_item(repo_id: str, item_id: str) -> dict:
    for it in repo_items(repo_id):
        if str(it.get("id")) == str(item_id):
            return it
    raise InstallErrorFailed(f"item {item_id!r} not found in {repo_id!r}")


# SQLite permits only one writer at a time.  Recommended installs and manual
# installs are launched from separate server threads, and each importer performs
# many commits while indexing.  Serialize installer runs in this process so two
# large imports cannot hold competing write transactions against the same DB.
_INSTALL_LOCK = threading.Lock()


def install(repo_id: str, item_id: str, *, fmt: str = "",
            force: bool = False) -> dict:
    with _INSTALL_LOCK:
        return _install_impl(repo_id, item_id, fmt=fmt, force=force)


def _install_impl(repo_id: str, item_id: str, *, fmt: str = "",
                  force: bool = False) -> dict:
    conn = db.connect()
    repo = REPO_BY_ID.get(repo_id)
    if not repo:
        raise InstallErrorFailed(f"unknown repository {repo_id}")
    it = _find_item(repo_id, item_id)
    # The licence gate is about redistribution, and a file the reader already
    # has on their own disk is not being redistributed by anybody.  Refusing to
    # open the EPUB you downloaded yourself -- because the file says nothing
    # about its rights, which most personal ebooks do not -- is the gate
    # answering a question nobody asked.  The licence is still recorded,
    # unchanged, so citations and the attribution ledger say what the file
    # claimed and nothing more.
    if repo_id != "local":
        ok_date, why_date = taxonomy.redistributable(it)
        if not ok_date:
            raise InstallErrorFailed(
                f"not safely redistributable: {why_date}")
        lic = taxonomy.normalise_license(it.get("license"))
        if not taxonomy.license_ok(lic):
            raise InstallErrorFailed(
                f"licence '{lic}' is not freely redistributable; "
                f"refusing to install")

    mid = library.slugify(f"{repo_id}-{it.get('id')}")
    row = conn.execute("SELECT module_id FROM store_item WHERE repo_id=? AND item_id=?",
                       (repo_id, str(item_id))).fetchone()
    if row and row["module_id"]:
        existing = library.get(row["module_id"])
        if existing and existing.installed_at and not force:
            return {"ok": True, "already": True, "module_id": existing.id,
                    "name": existing.name, "stats": {}}
        mid = row["module_id"]

    tid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO transfer(id,kind,repo_id,item_id,title,status,started) "
        "VALUES(?,?,?,?,?,?,?)",
        (tid, "install", repo_id, str(item_id), it.get("title", ""), "running",
         time.time()))
    conn.commit()
    prog = Progress(tid)

    try:
        result = _install_one(repo_id, it, mid, fmt, prog, tid, conn)
    except Exception as e:
        # Preserve the original import error even if SQLite is temporarily busy
        # while recording the failure.  The connection can be in a failed
        # transaction, so rollback before attempting the status update.
        try:
            conn.rollback()
            conn.execute("UPDATE transfer SET status='error', message=?, finished=? "
                         "WHERE id=?", (f"{type(e).__name__}: {e}"[:400],
                                        time.time(), tid))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            db.log_history("install-failed", f"{it.get('title')}: {e}",
                           {"repo": repo_id, "item": item_id})
        except Exception:
            # Logging must not replace the exception that actually caused the
            # installation to fail.
            pass
        # Roll the module row back.  A reader that fails *while* indexing has
        # already inserted it, and a half-installed module then sits in the
        # Library looking present but opening to nothing -- which is the
        # confusing state this whole audit was about.
        # Each delete is independent and only targets tables that actually key
        # on module_id -- `strongs` keys on a `modules` list, and a single
        # "no such column" used to abort the whole cleanup, leaving the debris
        # behind that this was meant to remove.
        for table in _MODULE_SCOPED_TABLES:
            try:
                if not _has_column(conn, table, "module_id"):
                    continue
                conn.execute(f"DELETE FROM {table} WHERE module_id=?", (mid,))
                conn.commit()
            except Exception as cleanup_error:  # noqa: BLE001
                db.log_history("install-cleanup-failed",
                               f"{it.get('title')}: {table}: {cleanup_error}",
                               {"repo": repo_id, "item": item_id})
        try:
            conn.execute("DELETE FROM module WHERE id=?", (mid,))
            conn.commit()
        except Exception as cleanup_error:      # noqa: BLE001
            db.log_history("install-cleanup-failed",
                           f"{it.get('title')}: module: {cleanup_error}",
                           {"repo": repo_id, "item": item_id})
        raise

    # A module with no content is not an install.  Reporting success here is
    # what produced "downloaded but the archive held nothing but its .conf":
    # the row appeared in the Library with nothing to open.  Fail loudly, and
    # leave nothing half-installed.
    n_units = int(result.get("units") or 0)
    if n_units <= 0:
        conn.execute("UPDATE transfer SET status='error', message=?, finished=? "
                     "WHERE id=?",
                     ("installed nothing: the module parsed to zero units",
                      time.time(), tid))
        conn.execute("DELETE FROM unit WHERE module_id=?", (mid,))
        conn.execute("DELETE FROM module WHERE id=?", (mid,))
        conn.commit()
        db.log_history("install-empty", f"{it.get('title')}: 0 units", 
                       {"repo": repo_id, "item": item_id})
        raise InstallErrorFailed(
            f"'{it.get('title') or item_id}' downloaded but produced no "
            "readable text, so nothing "
            "was installed. This is a module the app cannot decode, not an "
            "empty work. The repository row is still here if you want to try "
            "again, and translations that do read are listed alongside it.")

    conn.execute("UPDATE transfer SET status='ok', message=?, finished=? WHERE id=?",
                 (f"Installed {n_units} units", time.time(), tid))
    conn.commit()
    conn.execute("UPDATE store_item SET module_id=? WHERE repo_id=? AND item_id=?",
                 (result["module_id"], repo_id, str(item_id)))
    conn.commit()
    # An install writes tens of thousands of rows in one transaction, which is
    # exactly how the write-ahead log reached 156 MB and stayed there.  Fold it
    # back in now rather than waiting for a commit that may never come.
    db.maybe_checkpoint(conn)
    return {"ok": True, "module_id": result["module_id"], "stats": result,
            "already": False}


def _install_one(repo_id: str, it: dict, mid: str, fmt: str, prog: Progress,
                 tid: str, conn) -> dict:
    kind = it.get("category", "Other")
    title = it.get("title", "")
    base_fields = dict(
        name=title,
        abbrev=str(it.get("abbrev") or it.get("modname") or "")[:32],
        type=kind,
        subject=taxonomy.normalise_subjects(it.get("subjects")),
        lang=it.get("lang", "und"),
        lang_name=it.get("lang_name") or taxonomy.language_name(it.get("lang")),
        version=str(it.get("version") or ""),
        source=repo_id,
        source_name=REPO_BY_ID[repo_id].name,
        source_url=it.get("page_url", "") or it.get("info_url", ""),
        license=taxonomy.normalise_license(it.get("license")),
        rights=(it.get("attribution") or it.get("rights") or "")[:600],
        description=(it.get("description") or "")[:4000],
        author=str(it.get("author") or "")[:300],
        year=str(it.get("year") or ""),
        raw_meta={"store": {"repo": repo_id, "item": str(it.get("id"))},
                  "attribution": it.get("attribution", "")},
    )

    handler = _HANDLERS.get(repo_id)
    if handler is None:
        raise InstallErrorFailed(f"no installer for repository {repo_id!r}")

    workdir = db.modules_dir() / mid
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        units, extra = handler(it, mid, prog, workdir, fmt)
        extra = dict(extra or {})
        # raw_meta_sword is not a column; it belongs inside raw_meta.  The same
        # is true of an EPUB's package metadata, which is worth keeping whole:
        # it is the only record of what the file claimed about itself.  A CCEL
        # work carries its volume and division the same way, because "which
        # division of which volume" is the whole of where that text came from.
        for blob_key, raw_key in (("raw_meta_sword", "sword"),
                                  ("raw_meta_epub", "epub"),
                                  ("raw_meta_thml", "thml")):
            payload = extra.pop(blob_key, None)
            if not payload:
                continue
            raw = base_fields.get("raw_meta") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {}
            raw = dict(raw)
            raw[raw_key] = payload
            base_fields["raw_meta"] = raw
        for k, v in extra.items():
            base_fields.setdefault(k, v)
        base_fields["folder"] = mid
        base_fields["path"] = str(workdir)
        base_fields["size_bytes"] = _dir_size(workdir)
        stats = indexer.run_import(mid, units, **base_fields)
    finally:
        pass
    return stats


def _dir_size(p: Path) -> int:
    n = 0
    for root, _d, files in os.walk(p):
        for f in files:
            try:
                n += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return n


_HANDLERS: dict[str, Callable] = {}

# Tables whose rows belong to one installed module, for install rollback.
_MODULE_SCOPED_TABLES = ("unit", "marker", "xref", "versification",
                         "unit_fts", "strongs")


def _has_column(conn, table: str, column: str) -> bool:
    try:
        return any(r[1] == column
                   for r in conn.execute(f"PRAGMA table_info({table})"))
    except Exception:                          # noqa: BLE001
        return False


def handler(repo_id: str):
    def deco(fn):
        _HANDLERS[repo_id] = fn
        return fn
    return deco


def _pick_download(it: dict, wanted: tuple[str, ...]) -> dict:
    dls = it.get("downloads") or []
    for w in wanted:
        for d in dls:
            if str(d.get("format", "")).lower() == w:
                return d
    for d in dls:
        if d.get("url"):
            return d
    if it.get("download_url"):
        return {"format": it.get("format", ""), "url": it["download_url"]}
    raise InstallErrorFailed("item has no downloadable URL")


# --------------------------------------------------------------------------
# eBible.org
# --------------------------------------------------------------------------

@handler("ebible")
def _install_ebible(it, mid, prog, workdir, fmt):
    want = ("sword", "sword-zip") if fmt == "sword" else ("usfm",)
    if fmt:
        want = (fmt,)
    d = _pick_download(it, want)
    url = d["url"]
    prog("Downloading", note=url)
    data = fetch(url, checksum=_checksum_for(it, d, url))
    kind = formats.sniff(data, name=url.rsplit("/", 1)[-1])
    extra: dict = {}
    if kind == "sword-zip":
        conf, units, meta = formats.load_sword_zip(data)
        extra["v11n"] = conf.get("Versification") or "KJV"
        extra["format"] = "SWORD"
        extra["license"] = taxonomy.normalise_license(
            conf.get("DistributionLicense") or it.get("license"))
        extra["rights"] = (conf.get("CopyrightNotes") or conf.get("Copyright")
                           or it.get("attribution", ""))[:600]
        extra["about"] = conf.get("About", "")[:2000]
        extra["abbrev"] = (conf.get("Abbreviation") or it.get("abbrev") or "")[:32]
        extra["raw_meta_sword"] = {k: v for k, v in meta.items()
                                   if k in ("ModName", "Version", "SourceType",
                                            "ModDrv", "Feature", "Category",
                                            "GlobalOptionFilter", "Lang",
                                            "About", "Description")}
    elif kind == "usfm":
        units = formats.load_usfm_zip(data)
        extra["format"] = "USFM"
    else:
        raise InstallErrorFailed(f"unexpected payload type {kind}")
    (workdir / "source.zip").write_bytes(data)
    return units, extra


# --------------------------------------------------------------------------
# CrossWire SWORD
# --------------------------------------------------------------------------

@handler("crosswire")
def _install_crosswire(it, mid, prog, workdir, fmt):
    d = _pick_download(it, ("sword-zip", "sword"))
    url = d["url"]
    prog("Downloading", note=url)
    data = fetch(url, timeout=300, checksum=_checksum_for(it, d, url))
    if data[:2] != b"PK":
        raise InstallErrorFailed(
            "the CrossWire package is a self-extracting installer, not a module "
            "package; use the rawzip mirror instead")
    conf, units, meta = formats.load_sword_zip(data)
    # Check that it actually produced readable text before believing it.
    #
    # The JFB package is a zCom4 module whose heading tables do not parse: it
    # installs 23,213 "verses" that start at Genesis 2, with every heading
    # offset by a verse, and reports success.  A reader opening Genesis 1 is
    # then told there is no chapter 1.  So the units are counted, and if the
    # package yielded nothing usable the next download for the same work is
    # tried -- which is how JFB ends up coming from CCEL as an EPUB.
    probe = []
    for u in units:
        probe.append(u)
        if len(probe) >= 40:
            break
    if not probe or not any((u.text if hasattr(u, "text") else "")
                            or u.segs for u in probe):
        alt = next((x for x in (it.get("downloads") or [])
                    if x.get("url") and x.get("format") == "epub"), None)
        if alt:
            prog("Trying the EPUB", note=alt["url"])
            raw = fetch(alt["url"], timeout=600,
                        checksum=_checksum_for(it, alt, alt["url"]))
            emeta, units = formats.load_epub(raw, kind="Commentary",
                                             source=it.get("title", ""))
            (workdir / "module.epub").write_bytes(raw)
            return units, {
                "name": (emeta.get("title") or it.get("title", ""))[:200],
                "author": (emeta.get("creator") or it.get("about", ""))[:300],
                "abbrev": it.get("abbrev", "") or "",
                "format": "EPUB (via CCEL)",
                "license": taxonomy.normalise_license(
                    emeta.get("rights") or it.get("license")),
                "rights": (emeta.get("rights") or emeta.get("publisher")
                           or it.get("attribution", ""))[:600],
                "about": (emeta.get("description") or it.get("about", ""))[:2000],
                "raw_meta_epub": {k: v for k, v in emeta.items()
                                  if k not in ("description", "rights")},
                "warning": ("the SWORD package of this work is unreadable, so "
                            "it was installed from the EPUB instead"),
            }
        raise InstallErrorFailed(
            "the package installed but produced no readable text, and there is "
            "no other copy of this work in the catalogue to fall back on")

    # The probe read the first forty units out of a generator that cannot be
    # rewound, and they were then installed missing: every SWORD module lost
    # its opening.  Barnes had no Genesis 1:1, and a lexicon was short of its
    # first forty headwords -- so the fact book had no entry for Aaron, and
    # the guide had nobody to name.  Put them back at the front.
    units = itertools.chain(probe, units)

    (workdir / "module.zip").write_bytes(data)
    lic = taxonomy.normalise_license(conf.get("DistributionLicense") or it.get("license"))
    if not taxonomy.license_ok(lic):
        raise InstallErrorFailed(f"module licence '{lic}' is not offerable")
    return units, {
        "v11n": conf.get("Versification") or "KJV",
        "format": f"SWORD/{conf.get('ModDrv', '?')}",
        "license": lic,
        "rights": (conf.get("CopyrightNotes") or conf.get("Copyright")
                   or it.get("attribution", ""))[:600],
        "about": conf.get("About", "")[:2000],
        "abbrev": (conf.get("Abbreviation") or it.get("abbrev") or "")[:32],
        "raw_meta_sword": {k: v for k, v in meta.items()
                           if k in ("ModName", "Version", "SourceType", "ModDrv",
                                    "Feature", "Category", "About", "Description",
                                    "GlobalOptionFilter", "LCSH", "History_1.1")},
    }


# --------------------------------------------------------------------------
# Midvash open data
# --------------------------------------------------------------------------

_MIDVASH_RAW = "https://raw.githubusercontent.com/midvash/bible-data/main"

# midvash/bible-data keys its verses by the OSIS *ordinal* (1 Genesis ... 66
# Revelation) in a column called book_id.  Reuse the canon table rather than
# hard-coding a second list that could drift.
_OSIS_BY_ORDINAL: dict[int, str] = {
    b.ordinal: b.osis for b in canon.BOOKS_KJA if 1 <= b.ordinal <= 66
}


@handler("midvash")
def _install_midvash(it, mid, prog, workdir, fmt):
    """Install one version from midvash/bible-data.

    The SQLite file is preferred: it is a single request, already indexed, and
    smaller than the whole-Bible JSON.  The JSON is the fallback for anyone who
    would rather not hand us a binary blob.
    """
    want = (fmt,) if fmt in ("sqlite", "json") else ("sqlite", "json")
    d = _pick_download(it, want)
    url = d["url"]
    prog("Downloading", note=url)
    data = fetch(url, timeout=300, checksum=_checksum_for(it, d, url))
    (workdir / Path(url).name).write_bytes(data)
    if url.endswith(".sqlite"):
        units = _midvash_sqlite(data, prog)
    else:
        units = _midvash_json(data, prog)
    if not units:
        raise InstallErrorFailed("no verses parsed")
    return units, {
        "format": "midvash SQLite" if url.endswith(".sqlite") else "midvash JSON",
        "license": "Public Domain",
        "v11n": "KJV",
    }


def _midvash_sqlite(data: bytes, prog) -> list[UnitIn]:
    import sqlite3
    prog("Reading verses")
    tmp = Path(tempfile.mkdtemp(prefix="gbible-midvash-")) / "v.sqlite"
    tmp.write_bytes(data)
    units: list[UnitIn] = []
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT book_id, chapter, number, text FROM verses "
            "ORDER BY book_id, chapter, number").fetchall()
    except sqlite3.Error as e:
        raise InstallErrorFailed(f"SQLite could not be read: {e}") from e
    finally:
        try:
            con.close()          # type: ignore[has-type]
        except Exception:
            pass
    seen: set[str] = set()
    for book_id, chapter, verse, text in rows:
        osis = _OSIS_BY_ORDINAL.get(int(book_id))
        if not osis or not text:
            continue
        key = f"{osis} {chapter}:{verse}"
        if key in seen:
            continue
        seen.add(key)
        units.append(UnitIn(key=key, label=key, title=f"{osis} {chapter}",
                            book=osis, chapter=int(chapter), verse=int(verse),
                            segs=[Seg("text", text or "")],
                            markup=f"{osis} {chapter}:{verse} {text or ''}"))
    return units


def _midvash_json(data: bytes, prog) -> list[UnitIn]:
    prog("Reading verses")
    doc = json.loads(data.decode("utf-8"))
    units: list[UnitIn] = []
    for b in doc.get("books") or []:
        osis = b.get("book") or ""
        if not osis and b.get("bookId"):
            osis = _OSIS_BY_ORDINAL.get(int(b["bookId"]), "")
        if not osis:
            continue
        for ch in b.get("chapters") or []:
            c = int(ch.get("chapter") or 0)
            for v in ch.get("verses") or []:
                n, text = int(v.get("number") or 0), v.get("text") or ""
                if not n or not text:
                    continue
                key = f"{osis} {c}:{n}"
                units.append(UnitIn(key=key, label=key, title=f"{osis} {c}",
                                    book=osis, chapter=c, verse=n,
                                    segs=[Seg("text", text)],
                                    markup=f"{osis} {c}:{n} {text}"))
    return units


# --------------------------------------------------------------------------
# seven1m open-bibles (USFX / OSIS)
# --------------------------------------------------------------------------

@handler("open-bibles")
def _install_open_bibles(it, mid, prog, workdir, fmt):
    """One XML file, one translation.  The file is the whole Bible, so a single
    request installs the module -- these are 10-18 MB of text, which is why the
    progress note names the book as it is parsed rather than downloading."""
    d = _pick_download(it, (fmt,) if fmt in ("usfx", "osis") else ())
    url = d["url"]
    prog("Downloading", note=url)
    data = fetch(url, timeout=600, checksum=_checksum_for(it, d, url))
    (workdir / Path(url).name).write_bytes(data)
    kind = formats.sniff(data, name=url.rsplit("/", 1)[-1])
    if kind == "usfx":
        verses, extra = formats.xmlbible.load_usfx(data)
    elif kind == "osis":
        verses, extra = formats.xmlbible.load_osis(data)
    else:
        raise InstallErrorFailed(f"not a USFX or OSIS document: {url}")
    prog("Indexing", note=f"{len(verses)} verses")

    def gen():
        # The reader's own segments are passed through rather than the flat
        # text: in USFX each word carries its Strong's number, and rebuilding
        # the verse from `text` would throw all of that away.
        for v in verses:
            yield UnitIn(key=v["key"], label=v["label"],
                         segs=v.get("segs") or [Seg("text", v["text"])],
                         title=f"{v['book']} {v['chapter']}", book=v["book"],
                         chapter=v["chapter"], verse=v["verse"],
                         markup=v["markup"])
    # An explicit, named default for this repository rather than a silent one.
    # normalise_license() treats an absent licence as "Copyrighted" -- an
    # unstated licence is not a permission -- so a curated all-PD source has to
    # say so here, in the open, rather than relying on that function to guess.
    # If this ever widens to a source that is not wholly public domain, this
    # line is the thing that has to change.
    lic = taxonomy.normalise_license(it.get("license") or _UNSTATED_IS_PD)
    if not taxonomy.license_ok(lic):
        raise InstallErrorFailed(f"licence '{lic}' is not offerable")
    if extra.pop("truncated", False):
        # The upstream file stops mid-document; say so rather than let a short
        # Bible look complete.
        extra["about"] = ((extra.get("about") or it.get("description") or "").strip()
                          + "\n\nNote: the upstream file is truncated -- it ends "
                            "part-way through, so the last book is incomplete. "
                            "Everything that was published is here."
                          ).strip()
    extra.update({"license": lic,
                  "rights": (it.get("rights") or it.get("attribution") or "")[:600],
                  "v11n": "KJV"})
    return gen(), extra


# --------------------------------------------------------------------------
# Wikisource
# --------------------------------------------------------------------------

_WS_API = "https://en.wikisource.org/w/api.php"


@handler("wikisource")
def _install_wikisource(it, mid, prog, workdir, fmt):
    prefix = it.get("page_prefix") or it.get("title")
    prog("Enumerating pages", note=prefix)
    pages = _ws_list(prefix)
    if not pages:
        raise InstallErrorFailed(f"no Wikisource pages under {prefix!r}")
    leaves = _ws_leaves(pages)
    prog("Downloading", note=f"{len(leaves)} pages")
    docs: list[tuple[str, str]] = []
    got = _ws_texts(leaves)
    # Pages that transclude rather than holding their own text.  Collected first
    # so the count can be reported and so the resolution pass can say what it
    # is doing; a work that does not transclude pays nothing for any of this.
    transcluded = [t for t in leaves if _WS_TRANSCLUDE.search(got.get(t) or "")]
    if transcluded:
        prog("Resolving transclusions", note=f"{len(transcluded)} pages")
    for i, title in enumerate(leaves, 1):
        if i % 250 == 0:
            prog("Downloading", i, len(leaves), note=title)
        txt = got.get(title) or ""
        if not txt:
            txt = _ws_text(title)          # retry the stragglers singly
        if not txt:
            continue
        if _WS_TRANSCLUDE.search(txt):
            txt = _ws_resolve_transclusion(title, txt, prog)
        if txt:
            docs.append((title, txt))
    if not docs:
        raise InstallErrorFailed("every page came back empty")
    if len(docs) < len(leaves) * 0.95:
        prog("Incomplete", note=f"{len(docs)}/{len(leaves)} pages retrieved")
    # How much of what came back is actually article text, and how much of it
    # claimed to be transcluded.  Both refusals below are decided from these two
    # numbers, so they are computed once and together.
    #
    # Two signals have to agree, and the reason is that neither suffices alone.
    # "Most pages carry no prose" on its own condemns any work whose entries are
    # legitimately short -- a dictionary of abbreviations is mostly stubs, and
    # refusing it would be a new bug.  "The page mentions a transclusion" on its
    # own is not a defect either: the Catholic Encyclopedia has real prose on the
    # same page as its `<pages index=...>` reference.  What is true is a work
    # that both transcludes and comes back empty, and only that is refused.
    _shell = 0
    _transcluded = 0
    for _t, _x in docs:
        if _WS_TRANSCLUDE.search(_x):
            _transcluded += 1
        _body = _WS_CHROME.sub("", _x)
        _body = re.sub(r"\{\{GHGpages\b[\s\S]*?\}\}", "", _body, flags=re.I)
        # Measured on the leftover prose, not on whether any segment came back.
        # parse_wikitext() keeps an unrecognised template as literal text, so
        # "{{GHGheader|" is a segment -- one that says there is no article here.
        _text = markup.segs_text(markup.parse_wikitext(_body))
        if len(_text.strip()) < _SHELL_CHARS:
            _shell += 1
    _shellwork = bool(docs and _shell / len(docs) > 0.5
                      and _transcluded / len(docs) > 0.5)
    # The same failure seen from the main page rather than the leaves: a work
    # marked {{incomplete}} whose text lives in a scanned index.  The marker
    # sits on the *root* page, which _ws_leaves drops precisely because it has
    # sub-pages -- so checking only the leaves missed it, and Brown-Driver-Briggs
    # installed from its Abbreviations and Preface alone.
    #
    # It refuses only when the leaves are shells as well.  It used to refuse on
    # the root marker alone, which was right when nothing here could read a
    # scan -- and then became wrong the moment `_ws_resolve_transclusion` could,
    # and refused Gesenius' grammar with the grammar sitting there resolved and
    # good.  A guard that outlives the reason it was written stops being a guard.
    root_txt = _ws_text(prefix) or ""
    root_stub = bool(re.search(r"\{\{\s*incomplete\b", root_txt, re.I)
                     and re.search(r"<pages\s+index=", root_txt, re.I))
    if root_stub and _shellwork and len(docs) < len(leaves) * 1.5:
        raise InstallErrorIncomplete(
            f"the main page is marked incomplete on Wikisource and its text "
            f"lives in scanned index pages this importer could not resolve, so "
            f"only {len(docs)} supporting page(s) came back. Refusing to "
            f"install it as if it were a complete work.")
    if _shellwork:
        raise InstallErrorIncomplete(
            f"{_shell} of {len(docs)} page(s) are navigation headers with no "
            f"article text, and {_transcluded} of {len(docs)} transclude their "
            f"content from a scanned or proofread index this importer could not "
            f"resolve. Refusing to install a table of contents as if it were "
            f"the book.")
    kind = it.get("category", "Commentary")
    if kind in ("Lexicon", "Dictionary", "Concordance"):
        units = _ws_articles(docs, kind,
                             numbered=kind == "Concordance")
    else:
        units = formats.load_wikitext(docs, kind=kind)
    (workdir / "pages.json").write_text(
        json.dumps([{"title": t, "len": len(x)} for t, x in docs]),
        encoding="utf-8")
    return units, {"format": "Wikisource", "lang": "eng"}


def _ws_list(prefix: str) -> list[str]:
    out: list[str] = []
    cont = {}
    for _ in range(20):
        q = {"action": "query", "list": "allpages", "apnamespace": "0",
             "apprefix": prefix, "aplimit": "500", "format": "json"}
        q.update(cont)
        url = _WS_API + "?" + urllib.parse.urlencode(q)
        try:
            data = json.loads(fetch(url, timeout=60))
        except Exception:
            break
        pages = data.get("query", {}).get("allpages", [])
        if not pages:
            break
        out += [p["title"] for p in pages]
        cont = data.get("continue", {})
        if not cont:
            break
    return out


def _ws_leaves(titles: list[str]) -> list[str]:
    """The pages that actually hold text are the deepest ones."""
    if not titles:
        return []
    depths = [(t.count("/"), t) for t in titles]
    if not depths:
        return []
    md = min(d for d, _ in depths)
    if max(d for d, _ in depths) == md:
        return sorted(titles)
    return sorted(t for d, t in depths if d >= md)


# The API caps a multi-title query at 50 for anonymous clients.  Batching turns
# a 2,000-page encyclopaedia from two thousand requests into forty, which is the
# difference between a dictionary installing in a minute and never finishing.
_WS_BATCH = 25


def _ws_text(title: str) -> str:
    return next(iter(_ws_texts([title]).values()), "")


def _ws_texts(titles: list[str]) -> dict[str, str]:
    """Fetch many pages' wikitext, keyed by page title.

    One request per batch of 25.  `formatversion=2` returns a list of pages
    rather than a title-keyed object, and redirects have to be resolved by hand
    because the resolved title is what we need to key the result on.
    """
    out: dict[str, str] = {}
    for i in range(0, len(titles), _WS_BATCH):
        batch = titles[i:i + _WS_BATCH]
        q = {"action": "query", "titles": "|".join(batch), "prop": "revisions",
             "rvprop": "content", "rvslots": "main", "formatversion": "2",
             "format": "json", "redirects": "1"}
        url = _WS_API + "?" + urllib.parse.urlencode(q)
        data = None
        for attempt in range(3):
            try:
                data = json.loads(fetch(url, timeout=90))
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if data is None or "query" not in data:
            # Never drop a batch silently.  A long download that quietly loses
            # four-fifths of its pages is worse than a slow one: the install
            # appears to succeed and the dictionary is quietly unusable.
            for title in batch:
                one = _ws_text(title)
                if one:
                    out[title] = one
                time.sleep(0.05)
            continue
        query = data.get("query", {})
        # Redirects come back as a separate list; honour them so a page that was
        # merged does not come back empty.
        alias: dict[str, str] = {}
        for r in query.get("redirects") or []:
            frm, to = r.get("from"), r.get("to")
            if frm and to:
                alias[frm] = to
        for page in query.get("pages", []) or []:
            title = page.get("title") or ""
            revs = page.get("revisions") or []
            content = ((revs[0].get("slots", {}).get("main", {}) or {}).get("content", "")
                       if revs else "")
            if not title or not content:
                continue
            out[title] = content
            for frm, to in alias.items():
                if to == title:
                    out.setdefault(frm, content)
    return out


def _ws_expand(title: str, text: str) -> str:
    """Expand the templates in a page, leaving transclusions as `<pages>` tags.

    One round trip and no HTML.  `action=parse` would render the page, which is
    what a browser wants and not what an importer wants: the result is markup
    full of navigation spans and style blocks, and the article text arrives
    buried in it.  `expandtemplates` keeps the result as wikitext, so it can go
    through `markup.parse_wikitext()` like every other page this importer
    reads.

    It does not expand a `<pages>` transclusion itself -- that needs the Index
    context -- but it *reveals* it, which is the part that was missing: the tag
    names the DjVu it comes from and the page range.
    """
    url = _WS_API + "?" + urllib.parse.urlencode({
        "action": "expandtemplates", "format": "json", "prop": "wikitext",
        "title": title, "text": text})
    data = None
    for attempt in range(3):
        try:
            data = json.loads(fetch(url, timeout=90))
            break
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    if not data or "error" in data:
        return text
    return (data.get("expandtemplates", {}) or {}).get("wikitext", "") or text


#: `<pages index="Scan.djvu" from="25" to="32" ...>` -- what a transclusion of a
#: proofread scan resolves to.
_PAGES_TAG = re.compile(r"<pages\b([^>]*)>", re.I)
_TAG_ATTR = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')

#: Page-namespace files already fetched, across the whole install.  A section's
#: range overlaps its neighbour's at the boundary, and a work can cite the same
#: leaf many times, so without this the same few kilobytes come down again and
#: again.
_SCAN_CACHE: dict[str, str] = {}


def _ws_resolve_transclusion(title: str, text: str, prog=None) -> str:
    """The text a page transcludes, fetched and spliced in.

    A work proofread from a scan keeps its text in the `Page:` namespace and
    pulls it in with `<pages index=...>`.  Fetching the article page then returns
    a shell -- a navigation header and nothing else -- which is exactly how
    Gesenius' Hebrew Grammar installed as 173 units of which 165 were the
    twelve bytes `{{GHGheader|`.  The grammar was on Wikisource the whole time,
    transcluded from *Gesenius' Hebrew Grammar (1910 Kautzsch-Cowley
    edition).djvu*, and nothing here read it.

    So: expand the page to learn which scan and which range, fetch those
    `Page:` files, and return them.  The scan's own proofreading chrome --
    `<noinclude>`, `<pagequality>`, `<references>` -- is left for the markup
    layer to strip, because deciding what is navigation and what is content is
    that layer's job, not this one's.

    Returns the original text when there is nothing to resolve or nothing comes
    back, so a page that merely *mentions* a transclusion is not damaged.  The
    caller's shell guard is what turns a continued failure into a refusal.
    """
    if not _WS_TRANSCLUDE.search(text):
        return text
    expanded = _ws_expand(title, text)
    tags = _PAGES_TAG.findall(expanded)
    if not tags:
        return text
    parts: list[str] = []
    for attrs in tags:
        a = dict(_TAG_ATTR.findall(attrs))
        index, frm, to = a.get("index", ""), a.get("from", ""), a.get("to", "")
        if not index or not (frm.isdigit() and to.isdigit()):
            continue
        lo, hi = int(frm), int(to)
        if hi < lo or hi - lo > 400:          # a whole book, not a section
            continue
        if prog is not None:
            prog("Transcluded", note=f"{index} pp.{lo}-{hi}")
        wanted = [f"Page:{index}/{n}" for n in range(lo, hi + 1)]
        missing = [w for w in wanted if w not in _SCAN_CACHE]
        if missing:
            _SCAN_CACHE.update(_ws_texts(missing))
        for w in wanted:
            got = _SCAN_CACHE.get(w)
            if got:
                parts.append(got)
    return "\n".join(parts) if parts else text


def _ws_articles(docs: list[tuple[str, str]], kind: str,
                 numbered: bool = False) -> Iterator[UnitIn]:
    """Dictionaries and concordances are keyed by their bold headword entries.

    A concordance is additionally given its Strong's numbers: the page is named
    for its range (G1 covers 1-999, G2 covers 1000-1999) and the entries on it
    are numbered in order, so the number is recoverable exactly.  Without that
    the whole point of a concordance -- clicking a number in the text and
    landing on the entry -- is unavailable.

    Two page shapes occur in practice, and getting this wrong loses most of a
    dictionary:

    *   **Many entries per page.**  Strong's concordance pages carry dozens of
        `== G2316 ==`-style sections, so the page is split on headings.
    *   **One entry per page.**  Easton's, the Jewish Encyclopedia and the
        Catholic Encyclopedia are a page *per headword*, with a navigation
        template and a single bolded lead term and no `==` headings at all.
        Splitting those on headings finds nothing, which is why Easton's used
        to install 87 articles instead of two thousand.

    So each page is tried as a multi-entry page first and falls back to being
    one article named after the page.
    """
    n = 0
    for title, text in docs:
        base = _ws_page_number(title)
        pref = "H" if re.search(r"/H\d", title) else "G"
        blocks = list(_ws_headword_blocks(text))
        if not blocks:
            one = _ws_single_article(title, text)
            if one is None:
                continue
            key, segs = one
            n += 1
            yield UnitIn(key=key, label=key, segs=segs, title=key,
                         extra={"headword": key})
            continue
        for i, (head, key, segs) in enumerate(blocks, 1):
            n += 1
            if numbered:
                # The heading is the authoritative number when it is one; only
                # fall back to counting when the page has no numeric headings.
                num = None
                digits = re.sub(r"\D", "", head)
                # The heading carries the digits ("==2316==") but not the
                # language; Greek and Hebrew pages both use bare numbers, so
                # the prefix has to come from the page name.
                if digits and pref:
                    num = pref + digits
                elif base is not None:
                    num = base + i
                if num is None:
                    yield UnitIn(key=key, label=key, segs=segs, title=key,
                                 extra={"headword": key})
                    continue
                num = num.upper()
                yield UnitIn(key=num, label=key, segs=segs, title=key,
                             extra={"headword": key, "strongs": num})
            else:
                yield UnitIn(key=key, label=key, segs=segs, title=key,
                             extra={"headword": key})
    if n == 0:
        raise InstallErrorFailed("no entries recognised")


# Navigation chrome that would otherwise be indexed as the article's text.
#
# CE13 is the Catholic Encyclopedia's per-article nav template (volume, previous,
# next, contributor).  It was missing here, so 9,918 of that encyclopaedia's
# 10,049 articles opened with a line of raw MediaWiki -- including the 867 that
# are *only* the template, which then became 867 articles whose entire text is
# "{{CE13| contributor = Anthony John Maas| article = Abaddon| volume = 1".
# Adding the name here fixes both at once: the real articles lose the header,
# and the stubs are left empty, which _ws_single_article already discards.
#
# The match must span lines.  `[^}]*` never matched this template at all,
# because on Wikisource it is written one parameter per line and the closing
# braces are on a line of their own:
#
#     {{CE13
#      |article = Aaron
#      |contributor = Charles Léon Souvay
#     }}
#
# so a single-line pattern finds no "}}" and leaves the whole thing in place.
_WS_CHROME = re.compile(
    r"\{\{(?:EBDheader|CE13|GHGheader|similar|About|header|header_approx|works)\b"
    r"[\s\S]*?\}\}", re.I)

# Evidence that a page pulls its content in from elsewhere.
_WS_TRANSCLUDE = re.compile(
    r"\{\{GHGpages\b|<pages\s+[^>]*index\s*=|\{\{\s*incomplete\b", re.I)

#: A page with less prose than this, once the navigation chrome is removed, has
#: no article in it.  A real encyclopaedia article is never this short.
_SHELL_CHARS = 200


def _ws_single_article(title: str, text: str):
    """Treat one page as one dictionary article, named after the page.

    The headword is the last path segment of the page title, which is exactly
    what the encyclopaedia pages use (".../Aaron"), cross-checked against the
    first bolded run in the body so that disambiguated titles still land on a
    sensible label.
    """
    body = _WS_CHROME.sub("", text)
    segs = markup.parse_wikitext(body)
    if not segs:
        return None
    head = re.sub(r"\s*\(\d+\)\s*$", "",      # ".../Aaron (2)" -> "Aaron"
                  title.rstrip().rsplit("/", 1)[-1]).strip()
    lead = _WS_BOLD.match(body.strip())
    key = re.sub(r"\s+", " ", (lead.group(1) if lead else head)
                 .strip(" *'"))[:80]
    if not key:
        key = head[:80]
    if not key:
        return None
    return key, segs


def _ws_page_number(title: str) -> int | None:
    """The first Strong's number on a concordance page, from its page name."""
    m = re.search(r"/([GH])(\d+)\s*$", title.strip())
    if not m:
        m = re.search(r"\b([GH])(\d+)\s*$", title.strip())
    if not m:
        return None
    return (int(m.group(2)) - 1) * 1000 + 1


_WS_HEAD = re.compile(r"^==+\s*(.+?)\s*==+\s*$", re.M)
_WS_BOLD = re.compile(r"^(?:\*+|''')(.+?)(?:\*+|''')\s*[:.]?\s*(.*)$")


def _ws_headword_blocks(text: str) -> Iterator[tuple[str, str, list]]:
    """Split a page on its `== Heading ==` sections.

    Yields (heading, key, segments).  The heading is kept because on a
    Strong's concordance page it *is* the entry number -- the page reads
    `==2316==` -- and deriving the number from position instead gets it wrong.
    """
    parts = _WS_HEAD.split(text)
    if len(parts) < 3:
        return
    for i in range(1, len(parts) - 1, 2):
        head = parts[i].strip()
        body = parts[i + 1]
        # A dictionary article's real headword is the first bolded run.
        m = _WS_BOLD.match(body.strip())
        key = m.group(1).strip(" *'") if m else head
        key = re.sub(r"\s+", " ", key)[:80]
        if not key:
            continue
        segs = markup.parse_wikitext(body)
        if not segs:
            continue
        yield head, key, segs


# --------------------------------------------------------------------------
# Open Scriptures
# --------------------------------------------------------------------------

@handler("openscriptures")
def _install_openscriptures(it, mid, prog, workdir, fmt):
    files = it.get("files") or []
    if not files:
        raise InstallErrorFailed("no file list in catalogue")
    kind = it.get("category", "OriginalLanguage")
    if kind == "OriginalLanguage" and "hbo" in str(it.get("lang")):
        return _os_morphhb(it, files, prog, workdir)
    return _os_sblgnt(it, files, prog, workdir)


def _os_morphhb(it, files, prog, workdir):
    import xml.etree.ElementTree as ET
    units: list[UnitIn] = []
    for i, f in enumerate(files, 1):
        if i % 5 == 0:
            prog("Downloading", i, len(files), note=os.path.basename(f))
        raw = fetch(f, timeout=120)
        (workdir / os.path.basename(f)).write_bytes(raw)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        units.extend(_os_verse_units(root))
    if not units:
        raise InstallErrorFailed("no verses parsed")
    return iter(units), {"format": "OSHB (USFM-lexical XML)", "license": "CC-BY-4.0"}


_USFM_LEX_NS = "{http://www.bibletechnologies.net/2003/osisCore}"


def _os_verse_units(root) -> Iterator[UnitIn]:
    cur_ch = cur_vs = 0
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "chapter" and elem.get("eid", "").endswith("!p"):
            m = re.search(r"!c(\d+)", elem.get("eid", ""))
            if m:
                cur_ch = int(m.group(1))
        elif tag == "verse":
            key = (elem.get("osisID") or "").strip()
            ref = canon.parse_osis_id(key)
            # SBLGNT numbers the verse in eid ("Gen.1.1!v1"); morphhb's OSIS
            # only carries osisID ("Gen.1.1"), so fall back to the parsed
            # reference for the chapter/verse.  Without this every morphhb verse
            # is skipped and the module installs as "no verses parsed".
            m = re.search(r"!v(\d+)", elem.get("eid", ""))
            if m:
                cur_vs = int(m.group(1))
                cur_ch = ref.chapter if ref else cur_ch
            elif ref and ref.verse:
                cur_ch, cur_vs = ref.chapter, ref.verse
            else:
                continue
            segs = _usfm_lex_segments(elem)
            if not segs:
                continue
            bk = ref
            yield UnitIn(key=key, label=canon.format_ref(
                bk or canon.Ref("Gen", cur_ch, cur_vs)), segs=segs,
                markup="", book=bk.book if bk else "", chapter=cur_ch,
                verse=cur_vs)


def _usfm_lex_segments(elem) -> list[Seg]:
    """Segments for one verse of the USFM-lexical OSHB XML.

    One `<w>` per word, and the separator between them has to be added here.
    Every other importer gets its word spacing from the source -- OSIS and
    USFM both put whitespace between elements, and `markup.segs_flatten` joins
    segments with nothing -- but this format is a stream with no whitespace
    between the `<w>` elements at all.  Joining them as they came meant the
    whole Hebrew Bible was indexed as 23,213 unsearchable blobs: a search for
    a single word in the OSHB returned nothing, and `WITHIN n WORDS` had one
    word to work with per verse.
    """
    segs: list[Seg] = []
    for w in elem.iter():
        t = w.tag.split("}")[-1]
        if t == "w":
            txt = (w.text or "")
            for ch in w:
                sub = _usfm_lex_segments(ch)
                txt += sub[0].text if sub else ""
            lemma = w.get("lemma") or w.get("x-strong") or ""
            if txt.strip():
                if segs:
                    segs.append(Seg("text", " "))
                segs.append(Seg("strongs" if lemma else "text", txt.strip(),
                                _norm_lemma(lemma), w.get("morph", "") or ""))
        elif t in ("suffix", "prefix", "suffixes", "prefixes", "acronym"):
            pass
    return segs


def _norm_lemma(l: str) -> str:
    l = (l or "").strip()
    m = re.match(r"^([GH])\s*(\d{1,5})", l)
    if m:
        return canon.normalise_strongs(m.group(1) + m.group(2))
    # OSHB writes a lemma as an optional initial letter and a slash before the
    # Strong's number ("b/7225" = the word in 7225 beginning with bet), or as a
    # bare number with the letter trailing ("430", "1254 a").  This path is
    # Hebrew-only, so a number with no G/H of its own is a Hebrew lemma.
    m = re.match(r"^[a-z]?\s*/\s*(\d{1,5})", l)
    if m:
        return canon.normalise_strongs("H" + m.group(1))
    m = re.match(r"^(\d{1,5})\b", l)
    if m:
        return canon.normalise_strongs("H" + m.group(1))
    return ""


def _os_sblgnt(it, files, prog, workdir):
    units: list[UnitIn] = []
    for i, f in enumerate(files, 1):
        prog("Downloading", i, len(files), note=os.path.basename(f))
        raw = fetch(f, timeout=90).decode("utf-8", "replace")
        (workdir / os.path.basename(f)).write_text(raw, encoding="utf-8")
        units.extend(_sbl_units(raw, os.path.basename(f)))
    if not units:
        raise InstallErrorFailed("no verses parsed")
    return iter(units), {"format": "SBLGNT (USFM text)", "license": "CC-BY-4.0",
                         "lang": "grc", "lang_name": "Greek (Ancient)"}


# SBLGNT ships one tab-separated "Book C:V<tab>text" line per verse.
_SBL_LINE = re.compile(
    r"^\s*([A-Za-z0-9]{1,8})\s+(\d+):(\d+)\s*\t\s*(.*)$")


def _sbl_units(text: str, fname: str) -> Iterator[UnitIn]:
    for raw in text.split("\n"):
        ln = raw.rstrip()
        if not ln:
            continue
        m = _SBL_LINE.match(ln)
        if not m:
            continue
        book = canon.lookup_book(m.group(1))
        if book is None:
            continue
        chapter, verse = int(m.group(2)), int(m.group(3))
        body = m.group(4).strip()
        if not body:
            continue
        segs = markup.parse_plain(body)
        yield UnitIn(key=f"{book.osis}.{chapter}.{verse}",
                     label=canon.format_ref(canon.Ref(book.osis, chapter, verse)),
                     segs=segs, markup="", book=book.osis, chapter=chapter,
                     verse=verse, extra={"lang": "grc"})


# --------------------------------------------------------------------------
# MACULA (Clear Bible, CC BY 4.0) — reuse the same line-splitting installer
# --------------------------------------------------------------------------
@handler("macula")
def _install_macula(it, mid, prog, workdir, fmt):
    return _install_stepbible_data(it, mid, prog, workdir, fmt)


# --------------------------------------------------------------------------
# STEPBible-Data (CC BY 4.0)
# --------------------------------------------------------------------------

@handler("stepbible-data")
def _install_stepbible_data(it, mid, prog, workdir, fmt):
    import urllib.parse
    d = _pick_download(it, ("text", "tsv", "txt"))
    url = d["url"]
    prog("Downloading", 0, 1, note=os.path.basename(url))
    raw = fetch(url, timeout=300, checksum=_checksum_for(it, d, url))
    fname = os.path.basename(urllib.parse.urlparse(url).path) or "data.txt"
    if not fname:
        fname = "data.txt"
    (workdir / fname).write_bytes(raw)
    text = raw.decode("utf-8", "replace")
    # Multi-record files separate records with a line beginning "$"; single-line
    # files (lexica) have one record per line.
    if re.search(r"(?m)^\$", text):
        chunks = [c.strip() for c in re.split(r"(?m)(?=^\$)", text) if c.strip()]
        # Drop the leading preamble (before the first $ separator).
        chunks = [c for c in chunks if c.startswith("$")]
    else:
        chunks = [ln for ln in text.splitlines() if ln.strip()]
    units: list[UnitIn] = []
    n = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        if i % 1000 == 0:
            prog("Indexing", i, n, note=f"{i}/{n}")
        # Keep the record's leading header line as the unit label when present.
        first = chunk.splitlines()[0].strip() if chunk.splitlines() else ""
        label = (first[:80] if first else f"record {i}")
        segs = markup.parse_plain(chunk)
        if not segs:
            continue
        units.append(UnitIn(key=f"rec-{i}", label=label, segs=segs,
                            markup="", book="", chapter=0, verse=0,
                            extra={"record": i}))
    if not units:
        raise InstallErrorFailed("no records parsed")
    return iter(units), {"format": "STEPBible-Data (TSV text)",
                        "license": "CC-BY-4.0", "lang": "eng",
                        "lang_name": "English"}


# --------------------------------------------------------------------------
# Project Gutenberg
# --------------------------------------------------------------------------

@handler("gutenberg")
def _install_gutenberg(it, mid, prog, workdir, fmt):
    url = it.get("download_url") or it.get("url")
    if not url:
        raise InstallErrorFailed("no download URL")
    prog("Downloading", note=url)
    raw = fetch(url, timeout=120,
                checksum=_checksum_for(it, None, url)).decode("utf-8", "replace")
    (workdir / "text.txt").write_text(raw, encoding="utf-8")
    kind = it.get("category", "Book")
    units = plain.units_from_articles(raw, kind=_gutenberg_kind(kind),
                                      source=it.get("title", ""))
    return units, {"format": "Plain text", "lang": "eng"}


def _gutenberg_kind(kind: str) -> str:
    return {"Devotional": "Book", "Book": "Book", "Lexicon": "Lexicon",
            "Commentary": "Commentary", "Dictionary": "Dictionary"}.get(
        kind, "Book")


# --------------------------------------------------------------------------
# CCEL Fathers (Ante-Nicene, Nicene and Post-Nicene)
# --------------------------------------------------------------------------

@handler("ccel-fathers")
def _install_ccel_fathers(it, mid, prog, workdir, fmt):
    """One work out of one of CCEL's thirty-eight ThML volumes.

    The catalogue offers a work -- Irenaeus's *Against Heresies*, Jerome's
    *Letters* -- and the download is the whole volume it sits in, because that is
    the only file CCEL publishes.  Keeping the downloaded file would mean nine
    copies of the same volume the moment a reader installed nine works from it,
    so what is saved beside the module is this work's own division of the ThML:
    the exact text that was installed, and nothing else.
    """
    url = it.get("download_url") or ""
    if not url:
        raise InstallErrorFailed("no download URL")
    work_id = str(it.get("work") or it.get("id") or "")
    prog("Downloading the volume", note=url)
    raw = fetch(url, timeout=600,
                checksum=_checksum_for(it, None, url))
    src = raw.decode("utf-8", "replace")
    if not thml.sniff_thml(raw[:4096], name=url):
        raise InstallErrorFailed(
            f"{url} is not a CCEL ThML file; the catalogue points at the "
            "volume's .xml and that is what has to come back")

    works = thml.volume_works(src)
    work = next((w for w in works if w.work_id == work_id), None)
    if work is None:
        # The catalogue was built from these files, so this only happens if CCEL
        # has renumbered a division.  Saying so is better than installing the
        # other thirty works in the volume under this one's name.
        alt = next((d.get("url") for d in (it.get("downloads") or [])
                    if d.get("format") == "epub"), "")
        raise InstallErrorFailed(
            f"the ThML file for {it.get('volume_title') or url} no longer marks "
            f"'{work_id}' as one of its works, so this one cannot be taken out "
            f"of it without installing the whole volume instead. The same text "
            f"is at {alt or it.get('page_url') or url}.")

    frag = thml.slice_div(src, work.div_id)
    (workdir / "work.thml").write_text(frag, encoding="utf-8")
    prog("Indexing", note=work.title)
    units = list(thml.units_for_work(src, work))
    if not units:
        raise InstallErrorFailed(f"'{work.title}' produced no readable chapters")
    meta = thml.volume_meta(src)
    lic = taxonomy.normalise_license(meta.rights or it.get("license"))
    if not taxonomy.license_ok(lic):
        raise InstallErrorFailed(
            f"the volume's own rights statement reads '{meta.rights}', which is "
            "not freely redistributable")
    author = str(it.get("author") or "").strip()
    volume = str(it.get("volume") or work.version or "")
    return iter(units), {
        "format": "ThML (CCEL)",
        "license": lic,
        "lang": it.get("lang") or meta.language or "eng",
        "lang_name": it.get("lang_name") or taxonomy.language_name(
            it.get("lang") or meta.language or "eng"),
        "author": author or (meta.editor or ""),
        "abbrev": f"{volume.upper()} {author or work.author_id}"[:32],
        "rights": (it.get("rights") or it.get("attribution") or "")[:600],
        "about": (it.get("description") or meta.description or "")[:2000],
        "raw_meta_thml": {"volume": volume,
                          "volume_title": it.get("volume_title", ""),
                          "work": work.work_id,
                          "div": work.div_id,
                          "volume_url": meta.url,
                          "work_url": work.page_url,
                          "first_published": meta.first_published,
                          "editor": meta.editor,
                          "units": len(units)},
    }


# --------------------------------------------------------------------------
# Latin Fathers (The Latin Library)
# --------------------------------------------------------------------------
@handler("latin-patristic")
def _install_latin_patristic(it, mid, prog, workdir, fmt):
    url = it.get("download_url") or it.get("page_url") or ""
    if not url:
        raise InstallErrorFailed("no download URL")
    prog("Downloading", note=url)
    # The Latin Library blocks the app's default User-Agent with HTTP 465,
    # so fetch with a browser UA and a small delay.
    import time as _t
    import urllib.request as _ur
    last = None
    for attempt in range(4):
        try:
            req = _ur.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en,la;q=0.8",
            })
            with _ur.urlopen(req, timeout=300) as r:
                raw = r.read()
            last = None
            break
        except Exception as e:  # noqa: BLE001
            last = e
            _t.sleep(2.0 * (attempt + 1))
    if last is not None:
        raise InstallErrorFailed(f"{type(last).__name__}: {last}")
    _verify_checksum(raw, _checksum_for(it, None, url), url)
    src = raw.decode("utf-8", "replace")
    if not latinlib.sniff_latinlib(raw[:4096]):
        raise InstallErrorFailed(f"{url} is not a Latin Library page")
    (workdir / "work.html").write_text(src, encoding="utf-8")
    prog("Indexing", note=it.get("title", ""))
    units = list(latinlib.units_from_page(src, title=it.get("title", ""),
                                         source=it.get("page_url", url)))
    if not units:
        raise InstallErrorFailed(f"'{it.get('title')}' produced no readable text")
    return iter(units), {
        "format": "HTML (The Latin Library)",
        "lang": "lat",
        "lang_name": "Latin",
        "author": it.get("author", ""),
        "about": (it.get("description") or "")[:2000],
        "rights": it.get("rights", ""),
    }


# --------------------------------------------------------------------------
# Wikimedia Commons
# --------------------------------------------------------------------------

@handler("wikimedia")
def _install_wikimedia(it, mid, prog, workdir, fmt):
    url = it.get("url") or it.get("download_url")
    if not url:
        raise InstallErrorFailed("no image URL")
    lic = taxonomy.normalise_license(it.get("license"))
    if not taxonomy.license_ok(lic):
        raise InstallErrorFailed(f"image licence '{lic}' is not offerable")
    url = url.split("?")[0]
    prog("Downloading", note=url)
    ext = Path(urllib.parse.unquote(url)).suffix or ".jpg"
    dest = workdir / (library.slugify(it.get("id", "img")) + ext)
    data = fetch(url, dest=dest, timeout=180,
                 checksum=_checksum_for(it, None, url))
    title = it.get("title", "Image")
    extra_i = {"caption": it.get("attribution", ""),
               "alt": title,
               "mime": it.get("mime", ""),
               "url": url}
    segs = [Seg("img", dest.name, "", "", extra_i),
            Seg("title", title)]
    if it.get("description"):
        segs.append(Seg("text", it["description"][:500]))
    yield_one = UnitIn(key=str(it.get("id")), label=title, segs=segs,
                       title=title, extra={"image": dest.name,
                                           "attribution": it.get("attribution", ""),
                                           "source": url})
    return iter([yield_one]), {"format": (it.get("mime") or "image").upper(),
                               "license": lic,
                               "rights": (it.get("attribution") or "")[:600]}


# --------------------------------------------------------------------------
# OpenBible geography
# --------------------------------------------------------------------------

@handler("openbible-geo")
def _install_geo(it, mid, prog, workdir, fmt):
    place = it.get("title", "")
    segs = [Seg("title", place)]
    if it.get("lat") is not None and it.get("lon") is not None:
        segs.append(Seg("text", f"Coordinates: {it['lat']}, {it['lon']}"))
    if it.get("comment"):
        segs.append(Seg("text", it["comment"]))
    refs = []
    for pr in it.get("passages", []) or []:
        rr = canon.parse_ref(pr)
        if rr:
            refs.append(rr.start.osis_id())
    if refs:
        segs.append(Seg("text", "Referenced at: " + ", ".join(it["passages"][:12])))
    if it.get("alt_names"):
        segs.append(Seg("text", "Also called: " + ", ".join(it["alt_names"][:8])))
    u = UnitIn(key=str(it.get("id")), label=place, segs=segs, title=place,
               extra={"lat": it.get("lat"), "lon": it.get("lon"),
                      "passages": refs})
    return iter([u]), {"format": "Place record", "license": "CC-BY-4.0",
                       "rights": (it.get("attribution") or "")[:600]}


# --------------------------------------------------------------------------
# Local files
# --------------------------------------------------------------------------

@handler("local")
def _install_local(it, mid, prog, workdir, fmt):
    path = Path(it.get("path") or it.get("download_url") or "")
    if not path.exists():
        raise InstallErrorFailed(f"file not found: {path}")
    data = path.read_bytes() if path.is_file() else b""
    kind = formats.sniff(data, path=path, name=path.name)
    prog("Reading", note=kind)
    extra = {"format": kind}
    if kind == "sword-zip":
        conf, units, meta = formats.load_sword_zip(data)
        extra.update({
            "v11n": conf.get("Versification") or "KJV",
            "abbrev": (conf.get("Abbreviation") or "")[:32],
            "license": taxonomy.normalise_license(
                conf.get("DistributionLicense") or "Public Domain"),
            "rights": (conf.get("CopyrightNotes") or conf.get("Copyright") or "")[:600],
            "about": conf.get("About", "")[:2000],
            "raw_meta_sword": {k: v for k, v in meta.items()
                               if k in ("ModName", "Version", "SourceType", "ModDrv")},
        })
    elif kind == "usfm":
        units = formats.load_usfm_zip(data)
    elif kind == "epub":
        meta, units = formats.load_epub(data,
                                        kind=it.get("category") or "Book",
                                        source=path.stem)
        # The EPUB states its own title, author, language and rights.  Taking
        # them from the file is the whole reason to read the metadata rather
        # than fall back to the file name: a personal book dropped into the
        # library as "book" is not a library anyone can use, and a citation
        # built from it would be a guess.
        extra.update({
            "name": (meta.get("title") or path.stem)[:200],
            "author": (meta.get("creator") or "")[:200],
            "lang": (meta.get("language") or it.get("lang") or "und")[:8],
            "about": (meta.get("description") or "")[:2000],
            "rights": (meta.get("rights") or meta.get("publisher") or "")[:600],
            "license": taxonomy.normalise_license(
                meta.get("rights") or meta.get("publisher") or ""),
            "raw_meta_epub": {k: v for k, v in meta.items()
                              if k not in ("description", "rights")},
        })
        if meta.get("fixed_layout"):
            extra["warning"] = meta.get("warning", "")
        if meta.get("date"):
            extra["year"] = str(meta["date"])[:4]
    elif kind == "esword9":
        details, units = formats.load_esword9(path, type_hint=it.get("type"))
        extra["abbrev"] = str(details.get("Abbreviation", ""))[:32]
        extra["about"] = markup.parse_rtf(str(details.get("Comments", "")))[:2000]
    elif kind == "esword-legacy":
        units = _legacy_esword(path, prog, workdir)
    elif kind in ("image",):
        dest = workdir / path.name
        dest.write_bytes(data)
        segs = [Seg("img", path.name, "", "", {"alt": path.stem})]
        units = iter([UnitIn(key=path.stem, label=path.stem, segs=segs,
                             title=path.stem, extra={"image": path.name})])
    elif kind in ("osm-kml",):
        units = _kml_places(path)
    elif kind == "conllu":
        from ..formats import conllu as _conllu
        units = _conllu.load_conllu(path, source=path.stem)
        extra.update({
            "name": path.stem[:200],
            "about": "Syntax treebank (CoNLL-U). Sentences naming a verse "
                     "link to it; the rest are searchable syntax units.",
        })
    elif kind == "thml":
        # A CCEL volume saved to disk, rather than fetched by the Store.  The
        # whole file installs as one module: the divisions it contains are the
        # same ones the Store offers individually, and a local import has no
        # catalogue entry to say which of them was wanted.
        src = data.decode("utf-8", "replace")
        vm = thml.volume_meta(src)
        works = thml.volume_works(src)
        if not works:
            raise InstallErrorFailed(
                "this ThML file contains no divisions to read")
        units = []
        for w in works:
            units.extend(thml.units_for_work(src, w))
        if not units:
            raise InstallErrorFailed("this ThML file contains no readable text")
        extra.update({
            "name": (vm.title or path.stem)[:200],
            "author": (vm.author or vm.editor or "")[:200],
            "lang": (vm.language or "und")[:8],
            "lang_name": taxonomy.language_name(vm.language or "und"),
            "year": str(vm.first_published or "")[:8],
            "license": taxonomy.normalise_license(vm.rights or it.get("license")),
            "rights": (it.get("attribution") or "")[:600],
            "about": vm.description[:2000],
            "raw_meta_thml": {"volume": vm.slug, "volume_url": vm.url,
                              "editor": vm.editor, "author": vm.author,
                              "rights_in_file": vm.rights, "works": len(works)},
        })
    else:
        units = formats.load_text(path, kind=it.get("category", ""),
                                  source=path.stem)
    if path.is_file():
        (workdir / (path.name + ".orig")).write_bytes(data)
    return units, extra


def _legacy_esword(path: Path, prog: Progress, workdir: Path) -> Iterator[UnitIn]:
    d = workdir / "esword"
    d.mkdir(exist_ok=True)
    target = d / path.name
    if not target.exists():
        target.write_bytes(path.read_bytes())
    if path.suffix.lower() == ".bzu":
        got = esword.open_bzu(target)
        if not got:
            raise InstallErrorFailed("could not read .bzu payload")
        mod, payload = got
        from ..indexer import UnitIn as UI
        text = "\n".join(b for _k, b in payload())
        return plain.units_from_articles(
            text, kind=esword.category_to_type(mod.get("category", "")),
            source=mod.get("name", path.stem))
    mod_file = target.with_suffix(".mod")
    mod = esword.read_mod(mod_file.read_text(encoding="utf-8", errors="replace")) \
        if mod_file.exists() else {}
    return esword.legacy_units(d, mod)


def _kml_places(path: Path) -> Iterator[UnitIn]:
    import xml.etree.ElementTree as ET
    blob = path.read_bytes()
    if path.suffix.lower() == ".kmz":
        zf = zipfile.ZipFile(__import__("io").BytesIO(blob))
        name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
        blob = zf.read(name)
    root = ET.fromstring(blob)
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    out = []
    for pm in root.iter():
        if pm.tag.split("}")[-1] != "Placemark":
            continue
        name = coord = desc = ""
        for ch in pm:
            tag = ch.tag.split("}")[-1]
            if tag == "name":
                name = (ch.text or "").strip()
            elif tag == "description":
                desc = re.sub(r"<[^>]+>", " ", ch.text or "").strip()
            elif tag == "Point":
                c = next((g for g in ch if g.tag.split("}")[-1] == "coordinates"), None)
                if c is not None and c.text:
                    coord = c.text.strip()
        if not name:
            continue
        segs = [Seg("title", name)]
        if coord:
            parts = coord.split(",")
            if len(parts) >= 2:
                segs.append(Seg("text", f"Coordinates: {parts[0]}, {parts[1]}"))
        if desc:
            segs.append(Seg("text", desc[:400]))
        key = library.slugify(name)
        out.append(UnitIn(key=key, label=name, segs=segs, title=name,
                          extra={"lat": coord.split(",")[0] if coord else None,
                                 "lon": coord.split(",")[1] if "," in coord else None}))
    if not out:
        raise InstallErrorFailed("no placemarks in KML")
    return iter(out)
