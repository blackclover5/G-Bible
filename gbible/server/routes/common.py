import json
import os
import re
import secrets
import threading
import time
import traceback
import urllib.parse
from pathlib import Path

from ... import ai, aichat, audio, canon, citation, clause, concordance, community, dashboard, db, \
    docs, eusebian, genealogy, grammar, guides, library, maps, markup, media, \
    merge, mine, morphq, notes, ntuseot, organise, outline, publish, readingplan, \
    search, study, sync, taxonomy, timeline, translate, tts, workspace, \
    wordfind, wordlist
#: `workflow` would shadow nothing, but the module is imported as `wordflow` so
#: that the route name, the column and the JavaScript object can all be called
#: "workflow" without one of them being renamed later.
from ... import workflow as wordflow
from ...api import registry as apireg
from ... import store
from ... import __version__ as VERSION

CSRF_TOKEN = secrets.token_urlsafe(32)
CSRF_HEADER = "X-GBible-CSRF-Token"

_jobs: dict[str, dict] = {}


#: Finished jobs kept for the client to collect.  Entries used to stay forever,
#: so every install and import added a dict -- including its whole result -- and
#: nothing was ever dropped.  Small, but unbounded, and it lives for the life of
#: the process.  The page polls a job once it finishes, so a short window is
#: plenty; anything older is dropped oldest-first.
_JOB_HISTORY = 200


def _remember_job(jid: str, entry: dict) -> None:
    with _job_lock:
        _jobs[jid] = entry
    _prune_jobs()


def _prune_jobs() -> None:
    """Drop the oldest finished jobs once there are more than we keep.

    Called with no lock held: it takes the lock itself.  The page collects a
    job's result by polling it once, so a window of a couple of hundred is far
    more than any client needs, and the alternative was keeping every install
    ever done for the life of the process.
    """
    with _job_lock:
        finished = [(e.get("started") or 0, j) for j, e in _jobs.items()
                    if e.get("state") in ("done", "cancelled", "error")]
        if len(finished) <= _JOB_HISTORY:
            return
        finished.sort()
        for _t, j in finished[:len(finished) - _JOB_HISTORY]:
            _jobs.pop(j, None)
_job_lock = threading.Lock()


# --------------------------------------------------------------------------
# Route handlers
# --------------------------------------------------------------------------

def _ok(**kw):
    return {"ok": True, **kw}


def _obj(v, default=None):
    """Query strings can only carry text, so JSON-ish parameters are decoded here.

    Without this a request like ?cursor={"ref":"John 3"} reaches the library as a
    string and fails deep inside, which is a miserable thing to debug.
    """
    if isinstance(v, dict) or v is None:
        return v if v is not None else default
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return default
    if s[0] in "{[":
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default
    if s.startswith("[") and "," in s:
        return [x for x in s.split(",") if x]
    return v


def _flag(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def route(path: str, body: dict | None = None):
    """Dispatch an API path.  Returns a JSON-serialisable dict."""
    q = body or {}
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        parts = ["status"]
    head = parts[0]
    # Try the longest registered prefix first, so an endpoint may be named with
    # more than one segment -- `store/repo/remove` must not fall back to
    # `store` and be reported as an unknown route.
    fn = None
    for n in range(len(parts), 0, -1):
        fn = ROUTES.get("/".join(parts[:n]))
        if fn is not None:
            break
    if fn is None:
        return {"ok": False, "error": f"no route for /{head}"}
    try:
        return fn(parts, q)
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if os.environ.get("GBIBLE_DEBUG"):
            out["trace"] = traceback.format_exc(limit=6)
        return out


ROUTES: dict = {}


def endpoint(name: str):
    def deco(fn):
        ROUTES[name] = fn
        return fn
    return deco


#: Routes that return a file rather than JSON.  Exports need real bytes with a
#: real MIME type and a filename in Content-Disposition: JSON-encoding them would
#: base64 them (a third larger), and `default=str` turns a bytes value into the
#: text "b'%PDF-1.4...'", which is a PDF only in the sense that a JPEG is a JPEG.
FILE_ROUTES: dict = {}


def file_route(name: str):
    def deco(fn):
        FILE_ROUTES[name] = fn
        return fn
    return deco


def _ai_error(e: Exception):
    out = {"ok": False, "error": str(e)}
    hint = getattr(e, "hint", "")
    if hint:
        out["hint"] = hint
    return out


def gloss_for(num: str) -> str:
    """Strong's number -> its dictionary headword, if a lexicon is installed."""
    if not num:
        return ""
    conn = db.connect()
    rows = conn.execute(
        "SELECT m.id FROM module m WHERE m.installed_at>0 AND m.type IN "
        "('Lexicon','Dictionary','Concordance')").fetchall()
    for row in rows:
        r = conn.execute("SELECT title, text FROM unit WHERE module_id=? AND key=?",
                         (row["id"], num)).fetchone()
        if r and (r["text"] or "").strip():
            return r["title"] or num
    return ""


def _item_dict(i) -> dict:
    """Item carries a non-JSON _segs cache; everything else is plain data."""
    return {"key": i.key, "label": i.label, "title": i.title, "text": i.text,
            "html": i.html, "extra": {k: v for k, v in (i.extra or {}).items()
                                      if not k.startswith("_")}}


def _pane_dict(p) -> dict | None:
    import dataclasses
    return dataclasses.asdict(p) if p is not None else None


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s or "")).strip("-") or "export"



__all__ = [name for name in globals() if not name.startswith("__")]
