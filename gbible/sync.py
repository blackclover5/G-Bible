"""Annotation sync between installs, per the contract in docs/sync.md.

What this moves is the record of a reader's own work: notes, highlights,
reading progress, pane layouts, collections, passage lists, saved searches,
favourites, tags, word lists, workflows, memorisation cards, citation metadata,
the list of installed modules, and the settings that describe how they read.
The library itself (module files and the positional index) is never synced --
a Bible is large and re-installable from the Store, and moving it would make
every sync a download.  What does travel is the list of module ids, so a new
computer knows what to install.

The shape of it:

  * every entity becomes a **record** -- a JSON envelope carrying an id, a
    revision, a hybrid logical clock stamp and the payload itself;
  * a **manifest** at the root of the sync folder lists every record any
    device knows, with its hash, so a client can decide what to move without
    fetching anything it already has;
  * two devices that have never met agree on who won an edit, because ordering
    comes from a clock that is advanced by *observing* the other device rather
    than from either device's wall clock.  A laptop that comes back with a dead
    battery and a clock three months behind must not be able to silently
    overwrite a month of notes.

Deletes are recorded as **tombstones**, because notes, highlights, collections
and templates are deleted outright in this database.  A delete that is not
recorded comes back on the next sync from any device that was not watching.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import db

# ------------------------------------------------------------------- layout

#: Bump for a change that breaks the wire format.  A reader reads every version
#: directory it knows; a v2 client keeps writing v1 while a v1 peer exists.
FOLDER_VERSION = "v1"

#: The folder itself is the target's: the reader names it when they choose a
#: target (a directory, or a path inside their cloud account), and sync puts
#: `v1/` inside it.  Nesting one more folder here would only double up.
MANIFEST = "manifest.json"

#: How long a tombstone is kept before it is safe to forget.  Long enough that
#: a device in a drawer for a season still hears about the delete.
TOMBSTONE_KEEP = 90 * 86400


#: The kinds of record that travel, and the folder each lives in.
KINDS = {
    "note": "notes",
    "highlight": "highlights",
    "plan-mark": "plan-marks",
    "layout": "layouts",
    "collection": "collections",
    "passage-list": "passage-lists",
    "passage": "passages",
    "template": "templates",
    "favourite": "favourites",
    "setting": "settings",
    "tag": "tags",
    "word-list": "word-lists",
    "workflow": "workflows",
    "srs-card": "srs-cards",
    "citation-meta": "citation-metas",
}

#: Kinds that can be merged rather than won.  `plan-mark` is a set of days read,
#: which is additive: a day marked on a phone and a day marked on a desktop are
#: both true, and there is no conflict to resolve.
MERGEABLE = ("plan-mark",)

#: Settings that travel.  Everything not here is device-local on purpose:
#: `flash_session` is transient UI state and `highlight_palette_active` is which
#: palette this screen happens to be showing.
SETTINGS_ALLOWLIST = (
    "reading-plan/progress", "module_tags", "highlight_palettes", "top_bible",
    "prioritize_rules", "visual_filters", "plan_paces", "plans_archived",
    "sermon_calendar", "notebooks", "clippings", "canvases", "print_books",
    "guide_configs", "collection_rules", "search_panel_link",
    "prayer_templates", "installed_modules",
)

#: Interval choices in minutes; 0 is manual, -1 is "when the app quits".
INTERVALS = ((0, "Only when I press Sync now"), (5, "Every 5 minutes"),
             (15, "Every 15 minutes"), (60, "Hourly"), (-1, "When the app closes"))

# ------------------------------------------------------------------ settings

K_CONFIG = "sync.config"
K_DEVICE = "sync.device_id"
K_COUNTER = "sync.counter"
K_LAST_RUN = "sync.last_run"
K_LAST_OK = "sync.last_ok"
K_LAST_ERROR = "sync.last_error"
K_LAST_SUMMARY = "sync.last_summary"


class SyncError(Exception):
    """Sync could not run.  The message is meant to be read by a person."""


# -------------------------------------------------------------------- state

def device_id() -> str:
    """This install's identity in the hybrid clock.

    Generated once and kept: a new device id is a new participant, and a reader
    who reinstalls and gets a new id simply looks like a third device, which is
    harmless, whereas a *reused* id makes two installs indistinguishable and
    their clocks stop ordering anything.
    """
    did = db.get_setting(K_DEVICE)
    if not did:
        did = uuid.uuid4().hex[:12]
        db.set_setting(K_DEVICE, did)
    return did


#: Reading progress lives in a setting whose per-plan sets are the records.
PROGRESS_KEY = "reading-plan/progress"


def _now() -> float:
    return time.time()


# ------------------------------------------------------- files and credentials

def credentials_path() -> Path:
    return db.app_dir() / "sync-credentials.json"


def _read_credentials() -> dict:
    p = credentials_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_credentials(creds: dict) -> None:
    """Credentials live beside the database, not in it.

    `gbible.db` is the file people copy, back up and attach to a support email;
    a sync password must not travel with it.  0600 because it is a password.
    """
    p = credentials_path()
    try:
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(creds, fh)
    except OSError as e:
        raise SyncError(f"Could not write {p}: {e}") from e


def credentials_for(name: str) -> dict:
    return _read_credentials().get(name) or {}


def save_credentials(name: str, password: str) -> None:
    if not name:
        return
    creds = _read_credentials()
    if password:
        creds[name] = {"password": password}
    else:
        creds.pop(name, None)
    _write_credentials(creds)


def relpath(kind: str, rid: str) -> str:
    """Where a record lives in the folder.

    The id is quoted because a setting key can contain a slash
    (`reading-plan/progress`) and the folder keeps one file per record.  The
    root and the version are part of the path so that a breaking change can add
    `v2/` beside `v1/` and a reader of both can merge them.
    """
    sub = KINDS.get(kind, "_" + kind)
    return f"{FOLDER_VERSION}/{sub}/{urllib.parse.quote(str(rid), safe='')}.json"


# --------------------------------------------------------------- the envelope

def payload_hash(payload) -> str:
    """A stable hash of a payload, so "same content" needs no transfer."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _envelope(kind: str, rid: str, payload, *, rev=None, clock=None,
              deleted: bool = False) -> dict:
    return {
        "schema": 1,
        "kind": kind,
        "id": rid,
        "rev": rev if rev is not None else 1,
        "updated_at": round(_now(), 3),
        "clock": clock or {"dev": device_id(), "ctr": 0},
        "hash": "" if deleted else payload_hash(payload),
        "deleted": deleted,
        "payload": payload,
    }


# ---------------------------------------------------------- the local snapshot

#: Records are collected from the modules that own them.  Each returns payloads
#: whose `id` (or `rid`, for kinds whose id is not called that) identifies them.
def _collect_notes() -> list[dict]:
    from . import notes
    return notes.listing(limit=1_000_000)


def _collect_highlights() -> list[dict]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT id, module_id, unit_key, quote, color, note, created_at, "
        "COALESCE(updated_at, created_at) AS updated_at FROM highlight")]


def _collect_plan_marks() -> list[dict]:
    from . import readingplan
    prog = readingplan.progress() or {}
    out = []
    for plan, days in prog.items():
        out.append({"id": "plan-" + str(plan), "plan": str(plan),
                    "days": sorted(int(d) for d in (days or []))})
    return out


def _collect_layouts() -> list[dict]:
    from . import workspace
    out = []
    for lay in workspace.list_layouts():
        out.append({"id": lay["id"], "name": lay.get("name") or "",
                    "tiles": lay.get("tiles"),
                    "panes": lay.get("panes") or []})
    return out


def _collect_collections() -> list[dict]:
    from . import organise
    out = []
    for c in organise.collections():
        out.append({"id": c["id"], "name": c.get("name") or "",
                    "note": c.get("note") or "",
                    "pinned": list(organise.collection_items(c["id"]) or [])})
    return out


def _collect_passage_lists() -> list[dict]:
    from . import organise
    return [{"id": p["id"], "name": p.get("name") or "",
             "note": p.get("note") or ""} for p in organise.passage_lists()]


def _collect_passages() -> list[dict]:
    from . import organise
    out = []
    for p in organise.passage_lists():
        for it in organise.passage_items(p["id"]):
            out.append({"id": it["id"], "list_id": it["list_id"],
                        "unit_key": it.get("unit_key") or "",
                        "ref_label": it.get("ref_label") or "",
                        "module_id": it.get("module_id") or "",
                        "position": int(it.get("position") or 0)})
    return out


def _collect_templates() -> list[dict]:
    from . import organise
    return [{"id": t["id"], "name": t.get("name") or "",
             "query": t.get("query") or "",
             "options": t.get("options") or {}} for t in organise.templates()]


def _collect_favourites() -> list[dict]:
    from . import organise
    return [{"id": m["id"], "module_id": m["id"]}
            for m in organise.favourites()]


def _collect_settings() -> list[dict]:
    out = []
    for key in SETTINGS_ALLOWLIST:
        val = db.get_setting(key)
        if val is None:
            continue
        out.append({"id": key, "key": key, "value": val})
    # Also sync the list of installed module IDs so a new computer
    # knows what to install from the Store.
    try:
        from . import library
        installed = [m.id for m in library.list_all()]
        if installed:
            out.append({"id": "installed_modules", "key": "installed_modules",
                        "value": installed})
    except Exception:
        pass
    return out


def _collect_tags() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM tag"):
        tid = r["id"]
        items = [dict(ir) for ir in conn.execute(
            "SELECT id, tag_id, kind, module_id, unit_key, book, chapter, "
            "verse, created_at FROM tag_item WHERE tag_id=?", (tid,))]
        out.append({"id": tid, "name": r["name"] or "",
                    "color": r["color"] or "",
                    "created_at": r["created_at"],
                    "items": items})
    return out


def _collect_word_lists() -> list[dict]:
    from . import wordlist
    out = []
    for wl in wordlist.listing():
        lid = wl["id"]
        items = []
        try:
            items = wordlist.pinned_items(lid) or []
        except Exception:
            pass
        out.append({"id": lid, "name": wl.get("name") or "",
                    "note": wl.get("note") or "",
                    "query": wl.get("query") or "",
                    "kind": wl.get("kind") or "term",
                    "options": wl.get("options") or {},
                    "created_at": wl.get("created_at"),
                    "updated_at": wl.get("updated_at"),
                    "items": items})
    return out


def _collect_workflows() -> list[dict]:
    from . import workflow
    out = []
    for wf in workflow.listing():
        wid = wf["id"]
        steps = []
        try:
            full = workflow.get(wid)
            steps = (full or {}).get("steps", []) or []
        except Exception:
            pass
        out.append({"id": wid, "name": wf.get("name") or "",
                    "note": wf.get("note") or "",
                    "ref": wf.get("ref") or "",
                    "layout_id": wf.get("layout_id") or "",
                    "created_at": wf.get("created_at"),
                    "updated_at": wf.get("updated_at"),
                    "steps": steps})
    return out


def _collect_srs_cards() -> list[dict]:
    from . import srs
    try:
        return [dict(c) if not isinstance(c, dict) else c
                for c in (srs.all_cards() or [])]
    except Exception:
        return []


def _collect_citation_meta() -> list[dict]:
    conn = db.connect()
    out = []
    # Group by module_id so one record per module
    mods = [r["module_id"] for r in conn.execute(
        "SELECT DISTINCT module_id FROM citation_meta")]
    for mid in mods:
        rows = conn.execute(
            "SELECT field, value, updated_at FROM citation_meta "
            "WHERE module_id=?", (mid,)).fetchall()
        fields = {r["field"]: r["value"] for r in rows}
        out.append({"id": mid, "module_id": mid, "fields": fields})
    return out


_COLLECTORS = {
    "note": _collect_notes,
    "highlight": _collect_highlights,
    "plan-mark": _collect_plan_marks,
    "layout": _collect_layouts,
    "collection": _collect_collections,
    "passage-list": _collect_passage_lists,
    "passage": _collect_passages,
    "template": _collect_templates,
    "favourite": _collect_favourites,
    "setting": _collect_settings,
    "tag": _collect_tags,
    "word-list": _collect_word_lists,
    "workflow": _collect_workflows,
    "srs-card": _collect_srs_cards,
    "citation-meta": _collect_citation_meta,
}


#: Applying somebody else's record to this database.  Deliberately written
#: against each module's own writes where they exist, so a synced note is a
#: note everything else knows about.
def _apply_note(p: dict) -> None:
    from . import notes
    notes.save(p)


def _apply_highlight(p: dict) -> None:
    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO highlight(id,module_id,unit_key,quote,color,"
        "note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (p.get("id") or "", p.get("module_id") or "", p.get("unit_key") or "",
         p.get("quote") or "", p.get("color") or "yellow",
         p.get("note") or "", float(p.get("created_at") or _now()),
         float(p.get("updated_at") or _now())))
    conn.commit()


def _apply_plan_mark(p: dict) -> None:
    from . import readingplan
    plan = str(p.get("plan") or "")
    if not plan:
        return
    allp = readingplan.progress() or {}
    days = set(int(d) for d in (allp.get(plan) or []))
    days |= set(int(d) for d in (p.get("days") or []))
    allp[plan] = sorted(days)
    db.set_setting(PROGRESS_KEY, allp)


def _apply_layout(p: dict) -> None:
    from . import workspace
    lid = p.get("id") or ""
    if not lid:
        return
    conn = db.connect()
    if conn.execute("SELECT 1 FROM layout WHERE id=?", (lid,)).fetchone() is None:
        # save_layout() updates; a record from another device has no row here
        # yet, and updating nothing would leave its panes orphaned.
        conn.execute("INSERT INTO layout(id,name,tiles,is_current,created_at) "
                     "VALUES(?,?,?,0,?)",
                     (lid, p.get("name") or "Layout",
                      json.dumps(p.get("tiles") or []), _now()))
        conn.commit()
    workspace.save_layout(lid, p.get("name") or "Layout", p.get("tiles") or [],
                          p.get("panes") or [])


def _apply_collection(p: dict) -> None:
    from . import organise
    organise.save_collection(p.get("name") or "", p.get("note") or "",
                             list(p.get("pinned") or []),
                             collection_id=p.get("id") or "")


def _apply_passage_list(p: dict) -> None:
    from . import organise
    organise.save_passage_list(p.get("name") or "", p.get("note") or "",
                               list_id=p.get("id") or "")


def _apply_passage(p: dict) -> None:
    conn = db.connect()
    if conn.execute("SELECT 1 FROM passage_list WHERE id=?",
                    (p.get("list_id") or "",)).fetchone() is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO passage_item(id,list_id,unit_key,ref_label,"
        "module_id,position,added_at) VALUES(?,?,?,?,?,?,?)",
        (p.get("id") or "", p.get("list_id") or "", p.get("unit_key") or "",
         p.get("ref_label") or "", p.get("module_id") or "",
         int(p.get("position") or 0), _now()))
    conn.commit()


def _apply_template(p: dict) -> None:
    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO search_template(id,name,query,options,created_at)"
        " VALUES(?,?,?,?,?)",
        (p.get("id") or "", p.get("name") or "", p.get("query") or "",
         json.dumps(p.get("options") or {}), _now()))
    conn.commit()


def _apply_favourite(p: dict) -> None:
    from . import library
    library.set_favorite(p.get("module_id") or p.get("id") or "", True)


def _apply_setting(p: dict) -> None:
    key = p.get("key") or p.get("id") or ""
    if key in SETTINGS_ALLOWLIST or key == "installed_modules":
        db.set_setting(key, p.get("value"))


def _apply_tag(p: dict) -> None:
    conn = db.connect()
    tid = p.get("id") or ""
    if not tid:
        return
    if conn.execute("SELECT 1 FROM tag WHERE id=?", (tid,)).fetchone():
        conn.execute("UPDATE tag SET name=?, color=? WHERE id=?",
                     (p.get("name") or "", p.get("color") or "", tid))
    else:
        conn.execute("INSERT INTO tag(id,name,color,created_at) VALUES(?,?,?,?)",
                     (tid, p.get("name") or "", p.get("color") or "",
                      float(p.get("created_at") or _now())))
    conn.commit()
    # Remove items that no longer exist on the remote
    remote_ids = {it.get("id") for it in (p.get("items") or []) if it.get("id")}
    local_items = conn.execute(
        "SELECT id FROM tag_item WHERE tag_id=?", (tid,)).fetchall()
    for lr in local_items:
        if lr["id"] not in remote_ids:
            conn.execute("DELETE FROM tag_item WHERE id=?", (lr["id"],))
    conn.commit()
    # Add new items
    for it in (p.get("items") or []):
        iid = it.get("id") or ""
        if not iid:
            continue
        if conn.execute("SELECT 1 FROM tag_item WHERE id=?", (iid,)).fetchone():
            continue
        conn.execute(
            "INSERT OR IGNORE INTO tag_item(id,tag_id,kind,module_id,unit_key,"
            "book,chapter,verse,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (iid, tid, it.get("kind") or "verse", it.get("module_id") or "",
             it.get("unit_key") or "", it.get("book") or "",
             it.get("chapter"), it.get("verse"),
             float(it.get("created_at") or _now())))
    conn.commit()
    conn.commit()


def _apply_word_list(p: dict) -> None:
    from . import wordlist
    lid = p.get("id") or ""
    if not lid:
        return
    if wordlist.get(lid) is None:
        wordlist.save({"id": lid, "name": p.get("name") or "",
                      "note": p.get("note") or "",
                      "query": p.get("query") or "",
                      "kind": p.get("kind") or "term",
                      "options": p.get("options") or {},
                      "created_at": p.get("created_at"),
                      "updated_at": p.get("updated_at")})
    for it in (p.get("items") or []):
        try:
            wordlist.pin(lid, it)
        except Exception:
            pass


def _apply_workflow(p: dict) -> None:
    from . import workflow
    wid = p.get("id") or ""
    if not wid:
        return
    if workflow.get(wid) is None:
        workflow.save({"id": wid, "name": p.get("name") or "",
                      "note": p.get("note") or "",
                      "ref": p.get("ref") or "",
                      "layout_id": p.get("layout_id") or "",
                      "created_at": p.get("created_at"),
                      "updated_at": p.get("updated_at")},
                     steps=p.get("steps") or [])


def _apply_srs_card(p: dict) -> None:
    cid = p.get("id") or ""
    if not cid:
        return
    conn = db.connect()
    if conn.execute("SELECT 1 FROM srs_card WHERE id=?", (cid,)).fetchone():
        return
    conn.execute(
        "INSERT OR IGNORE INTO srs_card(id,ref,module_id,unit_key,ease,"
        "interval_days,due,reps,lapses,created_at,last_reviewed) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (cid, p.get("ref") or "", p.get("module_id") or "",
         p.get("unit_key") or "", float(p.get("ease") or 2.5),
         int(p.get("interval") or p.get("interval_days") or 0), p.get("due") or "",
         int(p.get("reps") or 0), int(p.get("lapses") or 0),
         float(p.get("created_at") or _now()),
         p.get("last_reviewed")))
    conn.commit()


def _apply_citation_meta(p: dict) -> None:
    mid = p.get("module_id") or p.get("id") or ""
    if not mid:
        return
    conn = db.connect()
    for field, value in (p.get("fields") or {}).items():
        conn.execute(
            "INSERT OR REPLACE INTO citation_meta(module_id,field,value,updated_at) "
            "VALUES(?,?,?,?)",
            (mid, field, str(value), _now()))
    conn.commit()


_APPLIERS = {
    "note": _apply_note,
    "highlight": _apply_highlight,
    "plan-mark": _apply_plan_mark,
    "layout": _apply_layout,
    "collection": _apply_collection,
    "passage-list": _apply_passage_list,
    "passage": _apply_passage,
    "template": _apply_template,
    "favourite": _apply_favourite,
    "setting": _apply_setting,
    "tag": _apply_tag,
    "word-list": _apply_word_list,
    "workflow": _apply_workflow,
    "srs-card": _apply_srs_card,
    "citation-meta": _apply_citation_meta,
}


def _delete_note(rid: str) -> None:
    from . import notes
    notes.remove(rid)


def _delete_highlight(rid: str) -> None:
    conn = db.connect()
    conn.execute("DELETE FROM highlight WHERE id=?", (rid,))
    conn.commit()


def _delete_plan_mark(rid: str) -> None:
    from . import readingplan
    readingplan.clear_progress(rid[len("plan-"):] if rid.startswith("plan-")
                               else rid)


def _delete_layout(rid: str) -> None:
    """Delete a layout that no longer exists elsewhere.

    `workspace.delete_layout` refuses to delete the layout in use, which is
    right for a click and wrong for a sync: a layout removed on the other
    device has to go here too.  If it leaves no current layout, the newest
    remaining one becomes current, because the app needs a workspace.
    """
    from . import workspace
    conn = db.connect()
    was_current = conn.execute(
        "SELECT is_current FROM layout WHERE id=?", (rid,)).fetchone()
    conn.execute("DELETE FROM pane WHERE layout_id=?", (rid,))
    conn.execute("DELETE FROM layout WHERE id=?", (rid,))
    conn.commit()
    if was_current and was_current["is_current"]:
        left = workspace.list_layouts()
        if left:
            conn.execute("UPDATE layout SET is_current=0")
            conn.execute("UPDATE layout SET is_current=1 WHERE id=?",
                         (left[0]["id"],))
            conn.commit()


def _delete_collection(rid: str) -> None:
    from . import organise
    organise.delete_collection(rid)


def _delete_passage_list(rid: str) -> None:
    from . import organise
    organise.delete_passage_list(rid)


def _delete_passage(rid: str) -> None:
    from . import organise
    organise.remove_passage(rid)


def _delete_template(rid: str) -> None:
    from . import organise
    organise.delete_template(rid)


def _delete_favourite(rid: str) -> None:
    from . import library
    library.set_favorite(rid, False)


def _delete_setting(rid: str) -> None:
    conn = db.connect()
    conn.execute("DELETE FROM setting WHERE key=?", (rid,))
    conn.commit()


def _delete_tag(rid: str) -> None:
    conn = db.connect()
    conn.execute("DELETE FROM tag_item WHERE tag_id=?", (rid,))
    conn.execute("DELETE FROM tag WHERE id=?", (rid,))
    conn.commit()


def _delete_word_list(rid: str) -> None:
    from . import wordlist
    try:
        wordlist.remove(rid)
    except Exception:
        pass


def _delete_workflow(rid: str) -> None:
    from . import workflow
    try:
        workflow.remove(rid)
    except Exception:
        pass


def _delete_srs_card(rid: str) -> None:
    from . import srs
    try:
        srs.remove(rid)
    except Exception:
        pass


def _delete_citation_meta(rid: str) -> None:
    conn = db.connect()
    conn.execute("DELETE FROM citation_meta WHERE module_id=?", (rid,))
    conn.commit()


_DELETERS = {
    "note": _delete_note,
    "highlight": _delete_highlight,
    "plan-mark": _delete_plan_mark,
    "layout": _delete_layout,
    "collection": _delete_collection,
    "passage-list": _delete_passage_list,
    "passage": _delete_passage,
    "template": _delete_template,
    "favourite": _delete_favourite,
    "setting": _delete_setting,
    "tag": _delete_tag,
    "word-list": _delete_word_list,
    "workflow": _delete_workflow,
    "srs-card": _delete_srs_card,
    "citation-meta": _delete_citation_meta,
}


# ------------------------------------------------------- merge, and the run

def _merge_payload(kind: str, local: dict, remote: dict) -> dict:
    """Combine two versions where a combination is the right answer.

    Returns the merged payload, or None to fall through to last-writer-wins.
    Reading progress is a set of days marked read, and a set is additive: two
    devices marking different days produce the union of both, and neither
    reader's tick loses.  The revision is the greater of the two, so the merged
    record does not look older than either side.
    """
    if kind == "plan-mark":
        days = sorted(set(int(d) for d in (local.get("days") or []))
                      | set(int(d) for d in (remote.get("days") or [])))
        return dict(local, days=days)
    return None


def _clock_key(stamp: dict) -> tuple:
    return (int((stamp or {}).get("ctr") or 0), str((stamp or {}).get("dev") or ""))


class Syncer:
    """One sync run.

    Holds everything the run needs in one object because the run is a
    conversation with a folder: read the manifest, fetch what is missing, decide
    each record, write the changed ones, and only then rewrite the manifest.  A
    run that is interrupted between those steps leaves the old manifest in place
    and is simply an incomplete sync.
    """

    def __init__(self, target, dev: str):
        self.target = target
        self.dev = dev
        self.pushed = 0
        self.pulled = 0
        self.conflicts = 0
        self.skipped = 0
        self.notes: list[str] = []
        self._manifest: dict = {"records": {}}
        self._max_ctr = 0

    # -- folder I/O --------------------------------------------------------

    def _read_json(self, relpath: str):
        raw = self.target.read(relpath)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _write_json(self, relpath: str, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.target.write(relpath, body)

    def _manifest_path(self) -> str:
        """The manifest sits beside the records, inside the version folder.

        Kept there rather than at the root so that a v2 can be added beside it:
        a reader understands the version whose directory it can read, and the
        two manifests are not the same file.
        """
        return f"{FOLDER_VERSION}/{MANIFEST}"

    def _read_manifest(self) -> dict:
        m = self._read_json(self._manifest_path())
        if not isinstance(m, dict) or not isinstance(m.get("records"), dict):
            return {"records": {}}
        return m

    def _fetch_remote(self, entry: dict) -> dict | None:
        rid = entry.get("id") or entry.get("_id") or ""
        if not rid:
            return None
        return self._read_json(relpath(entry.get("kind") or "", rid))

    # -- the clock ---------------------------------------------------------

    def _observe(self, stamp: dict) -> None:
        """Take the other device's counter forward, always.

        This is what makes the clock work: a device that has only ever *read*
        still advances its counter, so the writer's counter can never fall
        behind something it has already seen.  Wall clocks are never consulted
        for ordering.
        """
        try:
            self._max_ctr = max(self._max_ctr, int((stamp or {}).get("ctr") or 0))
        except (TypeError, ValueError):
            pass

    def _stamp(self) -> dict:
        return {"dev": self.dev, "ctr": self._max_ctr + 1}

    # -- the run -----------------------------------------------------------

    def run(self) -> dict:
        started = _now()
        self._manifest = self._read_manifest()
        remote = self._manifest.get("records") or {}

        local = self._local()
        meta = self._meta()

        # Every stamp the other side has ever issued, before anything is
        # decided: the counter must be ahead of all of it.
        for entry in remote.values():
            self._observe(entry.get("clock"))
        for row in meta.values():
            self._observe(row.get("clock"))

        ids = set(local) | set(remote)

        for rid in sorted(ids):
            self._one(rid, local.get(rid), remote.get(rid), meta.get(rid))

        # Tombstones that have outlived their usefulness are forgotten, here
        # and in the folder.
        self._gc_tombstones()
        # The manifest is written from what is known *now*, not from the
        # snapshot taken at the start: a record pushed during this run is a
        # record the other side must be able to see next time.
        self._write_manifest(local, self._meta())

        return {"ok": True, "pushed": self.pushed, "pulled": self.pulled,
                "conflicts": self.conflicts, "skipped": self.skipped,
                "records": len(local), "notes": self.notes,
                "seconds": round(_now() - started, 2)}

    def _local(self) -> dict:
        out: dict = {}
        for kind, fn in _COLLECTORS.items():
            try:
                for p in fn() or []:
                    rid = str(p.get("id") or "")
                    if rid:
                        out[rid] = {"kind": kind, "payload": p}
            except Exception as e:                      # keep syncing the rest
                self.notes.append(f"{kind}: {e}")
        return out

    def _meta(self) -> dict:
        conn = db.connect()
        return {r["id"]: dict(r) for r in conn.execute("SELECT * FROM sync_meta")}

    def _tombstones(self) -> dict:
        conn = db.connect()
        return {r["id"]: dict(r) for r in conn.execute(
            "SELECT * FROM sync_tombstone")}

    def _remember(self, rid: str, kind: str, rev: int, clock: dict, hsh: str,
                  updated_at: float | None = None, *, base: str = "") -> None:
        conn = db.connect()
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta(id,kind,rev,dev,ctr,updated_at,"
            "hash,base) VALUES(?,?,?,?,?,?,?,?)",
            (rid, kind, int(rev), str((clock or {}).get("dev") or ""),
             int((clock or {}).get("ctr") or 0),
             float(updated_at or _now()), hsh, base or ""))
        conn.commit()

    def _tombstone_row(self, rid: str, kind: str) -> None:
        """Record a delete locally so the next sync sends it on."""
        conn = db.connect()
        stamp = self._stamp()
        self._max_ctr = max(self._max_ctr, stamp["ctr"])
        conn.execute(
            "INSERT OR REPLACE INTO sync_tombstone(id,kind,deleted_at,rev,dev,ctr)"
            " VALUES(?,?,?,?,?,?)",
            (rid, kind, _now(), 1, stamp["dev"], stamp["ctr"]))
        conn.commit()

    # -- one record --------------------------------------------------------

    def _one(self, rid: str, lrec, rentry, metarow) -> None:
        """Decide one record: push it, pull it, keep both, or leave it alone.

        The question is always "did each side change it since they last agreed",
        and the answer comes from two hashes kept per record: `hash`, the
        content of the version the folder holds, and `base`, the content that
        version was written against.  `base` is what makes a concurrent edit
        visible: if the other device built its change on something that is not
        the version here, the two changes were made without knowledge of each
        other, and one of them must be kept rather than dropped.
        """
        kind = ((lrec or {}).get("kind") or (metarow or {}).get("kind")
                or (rentry or {}).get("kind") or "")
        if not kind or (kind not in _APPLIERS and kind not in _COLLECTORS):
            # A kind this build does not know travels through untouched.
            self.skipped += 1
            return

        lhash = payload_hash(lrec["payload"]) if lrec else ""
        mhash = (metarow or {}).get("hash") or ""
        rhash = (rentry or {}).get("hash") or ""
        rbase = (rentry or {}).get("base") or ""
        rclock = (rentry or {}).get("clock") or {}
        rrev = int((rentry or {}).get("rev") or 1)

        local_changed = bool(lrec) and (not metarow or lhash != mhash)
        remote_changed = bool(rentry) and bool(rhash) and (not metarow
                                                          or rhash != mhash)

        # Both hold it and it is the same content.
        if lrec and rentry and rhash and lhash == rhash \
                and not (rentry or {}).get("deleted"):
            self._remember(rid, kind, rrev, rclock, lhash,
                           (rentry or {}).get("updated_at"), base=rbase)
            self.skipped += 1
            return

        # ---- we do not have it -------------------------------------------
        if lrec is None:
            rec = self._fetch_remote(rentry) if rentry else None
            if rec is None:
                # Either a tombstone we have not heard of, or a record whose
                # file is missing.  Our own delete travels either way.
                self._push_tombstone(rid, kind)
                return
            if rec.get("deleted"):
                if metarow and not mhash:
                    # We already hold this delete and it is unchanged: pulling
                    # it again would be work that never ends, and the manifest
                    # would otherwise show the same record moving for ever.
                    self.skipped += 1
                    return
                self._delete_local(kind, rid)
                self._remember(rid, kind, rec.get("rev") or 1,
                               rec.get("clock") or {}, "",
                               rec.get("updated_at"), base="")
                self._tombstone_row(rid, kind)
                self.pulled += 1
                return
            if not remote_changed and metarow:
                # We deleted it and the other side never touched it: the delete
                # is newer information, so it wins.
                self._push_tombstone(rid, kind)
                return
            self._apply_remote(kind, rid, rec)
            return

        # ---- we have it --------------------------------------------------
        rec = self._fetch_remote(rentry) if rentry else None

        if rec is None:
            if rentry and (rentry or {}).get("deleted") and not local_changed:
                self._delete_local(kind, rid)
                self._remember(rid, kind, rrev, rclock, "",
                               (rentry or {}).get("updated_at"), base="")
                self._tombstone_row(rid, kind)
                self.pulled += 1
                return
            self._push(rid, kind, lrec["payload"], base=mhash)
            return

        if rec.get("deleted"):
            if not local_changed:
                self._delete_local(kind, rid)
                self._remember(rid, kind, rec.get("rev") or 1,
                               rec.get("clock") or {}, "",
                               rec.get("updated_at"), base="")
                self._tombstone_row(rid, kind)
                self.pulled += 1
                return
            # We edited a record the other side deleted.  The edit is newer,
            # so it wins and the record comes back on the other device.
            self._push(rid, kind, lrec["payload"], base=mhash)
            return

        # Both alive, and the content differs.
        merged = _merge_payload(kind, lrec["payload"], rec.get("payload") or {})
        if merged is not None:
            # Additive kinds merge; nothing is won or lost.
            self._push(rid, kind, merged, base=mhash)
            return

        if rbase and rbase == lhash:
            # Their change was written against exactly the version held here,
            # so it is the newer one and there is nothing of ours to lose.
            self._apply_remote(kind, rid, rec)
            return

        if not local_changed and (not rbase or rbase == mhash):
            # We have not touched it since we last agreed, and their change
            # starts from that same version: an ordinary advance.
            self._apply_remote(kind, rid, rec)
            return

        if not remote_changed:
            self._push(rid, kind, lrec["payload"], base=mhash)
            return

        # Both sides changed it since they last agreed.
        self._resolve_conflict(kind, rid, lrec["payload"], rec, metarow or {})

    # -- moves -------------------------------------------------------------

    def _resolve_conflict(self, kind: str, rid: str, local_payload: dict,
                          rec: dict, metarow: dict) -> None:
        """Pick a winner and keep the loser.

        The winner is decided by the clock, then by revision, and only then by
        wall time -- which is why a device with a dead battery cannot win by
        being confidently wrong.  The loser is written as an ordinary record
        under a new id, so both versions exist on both devices afterwards.
        """
        mine = _clock_key(metarow.get("clock") or {})
        theirs = _clock_key(rec.get("clock") or {})
        mrev = int(metarow.get("rev") or 1)
        rrev = int(rec.get("rev") or 1)
        if theirs == mine:
            theirs_win = rrev > mrev
        else:
            theirs_win = theirs > mine

        if theirs_win:
            self._conflict_copy(kind, rid, local_payload)
            self._apply_remote(kind, rid, rec)
        else:
            self._push(rid, kind, local_payload,
                       base=metarow.get("hash") or "")
            self._conflict_copy(kind, rid, rec.get("payload") or {},
                                keep_id=rec.get("id") or rid)

    def _push(self, rid: str, kind: str, payload, *, base: str = "") -> None:
        stamp = self._stamp()
        self._max_ctr = max(self._max_ctr, stamp["ctr"])
        row = db.connect().execute(
            "SELECT rev FROM sync_meta WHERE id=?", (rid,)).fetchone()
        rev = ((row["rev"] if row else 0) or 0) + 1
        self._write_json(relpath(kind, rid),
                         _envelope(kind, rid, payload, rev=rev, clock=stamp))
        self._remember(rid, kind, rev, stamp, payload_hash(payload), base=base)
        self.pushed += 1

    def _push_tombstone(self, rid: str, kind: str) -> None:
        entry = (self._manifest.get("records") or {}).get(rid) or {}
        if entry.get("deleted") and entry.get("clock", {}).get("dev") == self.dev:
            self.skipped += 1              # already sent, and unchanged
            return
        conn = db.connect()
        row = conn.execute("SELECT * FROM sync_tombstone WHERE id=?",
                           (rid,)).fetchone()
        if row is None:
            if conn.execute("SELECT 1 FROM sync_meta WHERE id=?",
                            (rid,)).fetchone() is None:
                return                      # never synced: nothing to remember
            self._tombstone_row(rid, kind)
            row = conn.execute("SELECT * FROM sync_tombstone WHERE id=?",
                               (rid,)).fetchone()
        stamp = {"dev": row["dev"], "ctr": row["ctr"]}
        self._observe(stamp)
        self._write_json(relpath(kind, rid),
                         _envelope(kind, rid, None, rev=row["rev"],
                                   clock=stamp, deleted=True))
        self._remember(rid, kind, row["rev"], stamp, "", base="")

    def _apply_remote(self, kind: str, rid: str, rec: dict) -> None:
        payload = rec.get("payload") or {}
        try:
            _APPLIERS[kind](payload)
        except Exception as e:
            self.notes.append(f"could not apply {kind} {rid}: {e}")
            return
        self._remember(rid, kind, rec.get("rev") or 1, rec.get("clock") or {},
                       payload_hash(payload), rec.get("updated_at"),
                       base=rec.get("base") or "")

    def _delete_local(self, kind: str, rid: str) -> None:
        fn = _DELETERS.get(kind)
        if not fn:
            return
        try:
            fn(rid)
        except Exception as e:
            self.notes.append(f"could not delete {kind} {rid}: {e}")

    def _conflict_copy(self, kind: str, rid: str, payload: dict,
                       *, keep_id: str = "") -> None:
        """Write a losing version as an ordinary record under a new id.

        Silently dropping a reader's words is the one outcome sync must never
        have.  The copy is a real record from here on, so it travels to the
        other device and both sides end up holding both versions.
        """
        if kind == "setting":
            # A setting has one value per key, so there is nothing to copy: a
            # second version of `top_bible` is not a thing a reader can hold.
            return
        new_payload = dict(payload)
        stamp = self._stamp()
        self._max_ctr = max(self._max_ctr, stamp["ctr"])
        cid = f"{rid}-conflict-{uuid.uuid4().hex[:6]}"
        for key in ("title", "name"):
            if new_payload.get(key):
                new_payload[key] = f"{new_payload[key]} (conflicted)"
                break
        new_payload["id"] = cid
        self._write_json(relpath(kind, cid),
                         _envelope(kind, cid, new_payload, rev=1, clock=stamp))
        # The copy is a real record here too, or the next sync would see it as
        # something the other device wrote and pull it back for no reason.
        try:
            _APPLIERS[kind](new_payload)
        except Exception as e:
            self.notes.append(f"could not keep a copy of {keep_id or rid}: {e}")
            return
        self._remember(cid, kind, 1, stamp, payload_hash(new_payload),
                       base=(keep_id and payload_hash(payload)) or "")
        self.conflicts += 1
        self.notes.append(f"kept a version of {keep_id or rid} as "
                          f"{(new_payload.get('title') or new_payload.get('name') or cid)!r}")

    # -- the manifest ------------------------------------------------------

    def _write_manifest(self, local: dict, meta: dict) -> None:
        """Rewrite the manifest from this device's post-sync knowledge.

        Written last, and atomically, because it is the index everything else
        is found by.  A run interrupted before this point leaves the old
        manifest in place, which is simply an incomplete sync.
        """
        records: dict = {}
        for rid, row in meta.items():
            records[rid] = _manifest_entry(rid, row)
        tomb = self._tombstones()
        for rid, row in tomb.items():
            records[rid] = {"id": rid, "kind": row["kind"], "rev": row["rev"],
                            "hash": "", "base": "", "deleted": True,
                            "updated_at": row["deleted_at"],
                            "clock": {"dev": row["dev"], "ctr": row["ctr"]}}
        self._write_json(self._manifest_path(), {
            "schema": 1,
            "generated_at": round(_now(), 3),
            "generated_by": self.dev,
            "records": records,
        })

    def _gc_tombstones(self) -> None:
        """Forget deletes old enough that no device can still be behind.

        Keeping them for ever would grow the folder without bound; dropping
        them too early resurrects a note on a device that was switched off for a
        season.  Ninety days is the safe side of that trade.
        """
        conn = db.connect()
        cutoff = _now() - TOMBSTONE_KEEP
        rows = conn.execute(
            "SELECT id, kind FROM sync_tombstone WHERE deleted_at < ?",
            (cutoff,)).fetchall()
        for r in rows:
            try:
                self.target.remove(relpath(r["kind"], r["id"]))
            except Exception:
                pass
            conn.execute("DELETE FROM sync_tombstone WHERE id=?", (r["id"],))
            conn.execute("DELETE FROM sync_meta WHERE id=?", (r["id"],))
        if rows:
            conn.commit()


def _manifest_entry(rid: str, row: dict) -> dict:
    return {"id": rid, "kind": row.get("kind") or "",
            "rev": int(row.get("rev") or 1),
            "hash": row.get("hash") or "",
            "base": row.get("base") or "",
            "deleted": bool(row.get("deleted")),
            "updated_at": row.get("updated_at") or 0,
            "clock": {"dev": row.get("dev") or "", "ctr": int(row.get("ctr") or 0)}}


# --------------------------------------------------------------- tombstones

def tombstone(rec_id: str, kind: str) -> None:
    """Record a delete so the next sync does not resurrect it.

    Called from the module that owns the row, at the moment of deletion.  Only
    recorded when the record had been synced: one created and deleted while sync
    was off was never anywhere else, and remembering it would only grow the
    folder.
    """
    conn = db.connect()
    if conn.execute("SELECT 1 FROM sync_meta WHERE id=?",
                    (rec_id,)).fetchone() is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO sync_tombstone(id,kind,deleted_at,rev,dev,ctr)"
        " VALUES(?,?,?,?,?,?)",
        (rec_id, kind, _now(), 1, device_id(), _counter()))
    conn.commit()


def _counter() -> int:
    return int(db.get_setting(K_COUNTER, 0) or 0)


# ------------------------------------------------------------ configuration

def config() -> dict:
    """The saved sync configuration, with no secrets in it."""
    cfg = db.get_setting(K_CONFIG) or {}
    return cfg if isinstance(cfg, dict) else {}


def configured() -> bool:
    return bool(config().get("kind"))


def _target_from_config(cfg: dict):
    from . import synctargets
    return synctargets.probe(cfg)


def intervals():
    return [{"value": v, "label": l} for v, l in INTERVALS]


def save_config(cfg: dict) -> dict:
    """Store a target and its policy, proving the target answers first.

    The probe is the point: a typo in a URL or a missing folder is found when
    the reader presses Save rather than at the next silent interval, which is
    when nobody is watching.
    """
    cfg = dict(cfg or {})
    kind = (cfg.get("kind") or "").strip()
    if not kind:
        db.set_setting(K_CONFIG, {})
        db.set_setting(K_LAST_ERROR, "")
        return {}

    # Policy is kept even if the target probe fails below?  No: a configuration
    # that cannot reach its target is not a configuration.
    interval = int(cfg.get("interval") or 0)
    if interval not in [v for v, _ in INTERVALS]:
        interval = 15
    out = {
        "kind": kind,
        "name": (cfg.get("name") or kind).strip(),
        "interval": interval,
        "wifi_only": bool(cfg.get("wifi_only")),
    }
    if kind == "filesystem":
        out["path"] = (cfg.get("path") or "").strip()
    elif kind in ("webdav", "nextcloud"):
        if kind == "nextcloud":
            # A reader types a server and a user name, not the five path
            # segments that lead to their files.  Building it here keeps that
            # knowledge in one place.
            from . import synctargets
            out["url"] = synctargets.nextcloud_url(cfg.get("server") or "",
                                                   cfg.get("user") or "")
        else:
            out["url"] = (cfg.get("url") or "").strip()
        out["user"] = (cfg.get("user") or "").strip()

    target = _target_from_config(_with_password(out, cfg))
    db.set_setting(K_CONFIG, out)
    db.set_setting(K_LAST_ERROR, "")
    return out


def _with_password(out: dict, cfg: dict) -> dict:
    """Attach the saved password for the probe without ever storing it here."""
    password = (cfg.get("password") or "")
    if password:
        save_credentials(out.get("name") or out["kind"], password)
    return dict(out, password=credentials_for(out.get("name") or "").get("password", "")
                if not password else password)


# ------------------------------------------------------------------ metering

def metered() -> bool | None:
    """Is this connection metered?  True, False, or None when nobody knows.

    NetworkManager is the only source that answers on Linux without a desktop
    session to ask, and it is often absent.  Returning None -- "cannot tell" --
    lets the caller say so rather than guess, because an option that silently
    does nothing is worse than one that is missing.
    """
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "GENERAL.METERED", "device", "show"],
                           capture_output=True, timeout=5, text=True)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    values = [line.split(":", 1)[-1].strip().lower()
              for line in (r.stdout or "").splitlines() if ":" in line]
    if any(v == "yes" for v in values):
        return True
    if any(v == "no" for v in values):
        return False
    return None


# ---------------------------------------------------------------------- run

_lock = threading.Lock()


def run(force: bool = False) -> dict:
    """Sync once, in this thread.  Returns a summary for the caller to show."""
    with _lock:
        cfg = config()
        if not cfg.get("kind"):
            raise SyncError("Sync is not set up yet.")
        if cfg.get("wifi_only") and not force:
            m = metered()
            if m is True:
                db.set_setting(K_LAST_ERROR,
                               "Waiting for an unmetered connection.")
                return {"ok": True, "skipped": "metered"}
            if m is None:
                db.set_setting(K_LAST_ERROR,
                               "Wi-Fi only is on, but whether this connection "
                               "is metered cannot be told (NetworkManager not "
                               "found). Sync is paused until it can.")
                return {"ok": True, "skipped": "unknown-metered"}

        db.set_setting(K_LAST_RUN, _now())
        try:
            from . import synctargets
            target = synctargets.from_config(cfg)
            summary = Syncer(target, device_id()).run()
        except Exception as e:
            db.set_setting(K_LAST_ERROR, str(e))
            raise
        db.set_setting(K_LAST_OK, _now())
        db.set_setting(K_LAST_ERROR, "")
        db.set_setting(K_LAST_SUMMARY, summary)
        return summary


def status() -> dict:
    cfg = config()
    counts: dict = {}
    try:
        conn = db.connect()
        for r in conn.execute("SELECT kind, COUNT(*) c FROM sync_meta "
                              "GROUP BY kind"):
            counts[r["kind"]] = r["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM sync_tombstone").fetchone()["c"]
    except Exception:
        pending = 0
    return {"configured": bool(cfg.get("kind")), "kind": cfg.get("kind") or "",
            "name": cfg.get("name") or "", "path": cfg.get("path") or "",
            "url": cfg.get("url") or "", "user": cfg.get("user") or "",
            "interval": cfg.get("interval", 0), "wifi_only": bool(cfg.get("wifi_only")),
            "last_run": db.get_setting(K_LAST_RUN, 0) or 0,
            "last_ok": db.get_setting(K_LAST_OK, 0) or 0,
            "last_error": db.get_setting(K_LAST_ERROR, "") or "",
            "summary": db.get_setting(K_LAST_SUMMARY, {}) or {},
            "device_id": device_id(), "metered": metered(),
            "counts": counts, "tombstones": pending,
            "intervals": intervals(), "kinds": dict(KINDS)}


def disable() -> None:
    db.set_setting(K_CONFIG, {})
    db.set_setting(K_LAST_ERROR, "")


# ------------------------------------------------------------------ worker

_worker: threading.Thread | None = None
_wake = threading.Event()
_stop = False

#: How often the worker wakes to see whether a sync is due.  Shorter than the
#: shortest interval so the first sync after boot is not late by much.
_TICK = 20


def start_worker() -> None:
    """Start the interval worker.  Idempotent, and never a reason to fail boot.

    Sync is optional: if it cannot start, the app opens and reads exactly as
    before, and the Settings screen offers Sync now.
    """
    global _worker, _stop
    if _worker and _worker.is_alive():
        return
    _stop = False
    try:
        _worker = threading.Thread(target=_loop, name="gbible-sync", daemon=True)
        _worker.start()
    except Exception:
        _worker = None


def _loop() -> None:
    while not _stop:
        _wake.wait(_TICK)
        _wake.clear()
        if _stop:
            return
        cfg = config()
        interval = int(cfg.get("interval") or 0)
        if interval <= 0:
            continue
        last_ok = float(db.get_setting(K_LAST_OK, 0) or 0)
        if _now() - last_ok < interval * 60:
            continue
        try:
            run()
        except Exception as e:
            db.set_setting(K_LAST_ERROR, str(e))


def _final_sync() -> None:
    """The "when the app closes" interval.

    Registered once, and only while that interval is chosen.  A sync that fails
    on the way out is not worth blocking the exit for.
    """
    cfg = config()
    if int(cfg.get("interval") or 0) != -1:
        return
    try:
        run(force=True)
    except Exception:
        pass


def on_quit_interval() -> None:
    atexit.register(_final_sync)
