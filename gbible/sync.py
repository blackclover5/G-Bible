"""Annotation sync between installs, per the contract in docs/sync.md.

What this moves is the record of a reader's own work: notes, highlights,
reading progress, pane layouts, collections, passage lists, saved searches,
favourites, tags, word lists, workflows, memorisation cards, citation metadata,
the list of installed modules, and the settings that describe how they read.
The library itself (module files and the positional index) is never synced --
a Bible is large and re-installable from the Store, and moving it would make
every sync a download.  What does travel is the list of module ids, so a new
computer knows what to install.

**What it does today:** ``run()`` writes one complete ``.gbz`` archive to the
target.  It does not read a peer's archive or merge records automatically.
Merging happens only when the reader explicitly restores from a backup
(``sync/restore`` or the Backup screen), additively: identical records are
skipped and differing records keep the local value.  Describing this as an
automatic two-way merge would be false.

The archive carries a manifest with each record's hash and revision, and a
hybrid logical clock stamp so a restored record can be ordered against a local
one.  Deletes are recorded as **tombstones**, because notes, highlights,
collections and templates are deleted outright in this database.  A delete
that is not recorded comes back on the next restore from any device that was
not watching.  Tombstones are kept for 90 days.
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
import uuid
from pathlib import Path

from . import db, errorlog

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
    "canvas-board": "canvas-boards",
    "ai-chat": "ai-chats",
    "morph-query": "morph-queries",
}

#: Human labels for the record kinds.  Kept beside KINDS so the two cannot drift
#: apart; the UI reads these through scope() rather than keeping its own list.
KIND_LABELS = {
    "note": "Notes, journals, sermons & prayers",
    "highlight": "Highlights & bookmarks",
    "plan-mark": "Reading-plan progress",
    "layout": "Pane layouts",
    "collection": "Collections",
    "passage-list": "Passage lists",
    "passage": "Items inside passage lists",
    "template": "Saved searches",
    "favourite": "Favourite modules",
    "setting": "Reading settings (allowlisted keys only)",
    "tag": "Tags",
    "word-list": "Word lists",
    "workflow": "Workflows",
    "srs-card": "Memory-verse cards",
    "citation-meta": "Citation metadata",
    "canvas-board": "Canvas boards",
    "ai-chat": "AI conversations",
    "morph-query": "Saved morphological searches",
}

#: Friendly names for the settings keys most easily mistaken for local state.
SETTING_LABELS = {
    "reading-plan/progress": "Reading-plan progress",
    "reading-plan/custom": "Custom reading plans",
    "module_tags": "Module tags",
    "highlight_palettes": "Highlight palettes",
    "top_bible": "Preferred Bible",
    "prioritize_rules": "Module priority rules",
    "visual_filters": "Visual filters",
    "plan_paces": "Reading paces",
    "plans_archived": "Archived plans",
    "sermon_calendar": "Sermon calendar",
    "notebooks": "Notebooks",
    "clippings": "Clippings",
    "canvases": "Community canvases list",
    "print_books": "Print books",
    "guide_configs": "Guide layouts",
    "collection_rules": "Collection rules",
    "search_panel_link": "Search panel linking",
    "prayer_templates": "Prayer templates",
    "installed_modules": "List of installed module ids",
}

#: Settings that travel.  Everything not here is device-local on purpose:
#: `flash_session` is transient UI state and `highlight_palette_active` is which
#: palette this screen happens to be showing.
SETTINGS_ALLOWLIST = (
    "reading-plan/progress", "reading-plan/custom",
    "module_tags", "highlight_palettes", "top_bible",
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


def encryption_passphrase(cfg: dict | None = None) -> str:
    c = cfg if cfg is not None else config()
    name = (c.get("name") or c.get("kind") or "").strip()
    return str(credentials_for(name).get("passphrase") or "")


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
                    "pinned": list(organise.collection_pinned(c["id"]) or [])})
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


def _collect_canvas_boards() -> list[dict]:
    """Each Canvas board as one record.

    A board owns its nodes and edges, so it travels as a single record —
    the same unit of truth the app saves to the database.  Last-writer-wins
    is the right rule: the board's own updated_at is the revision.
    """
    conn = db.connect()
    out = []
    for b in conn.execute(
            "SELECT id, name, created_at, updated_at FROM canvas_board "
            "WHERE id IS NOT NULL"):
        bid = b["id"]
        nodes = [dict(n) for n in conn.execute(
            "SELECT id, kind, x, y, w, h, text, ref, color, module_id, data, "
            "created_at FROM canvas_node WHERE board_id=?", (bid,))]
        edges = [dict(e) for e in conn.execute(
            "SELECT from_id, to_id FROM canvas_edge WHERE board_id=?", (bid,))]
        out.append({"id": bid, "name": b["name"] or "Canvas",
                    "created_at": b["created_at"],
                    "updated_at": b["updated_at"] or b["created_at"] or 0.0,
                    "nodes": nodes, "edges": edges})
    return out


def _collect_ai_chats() -> list[dict]:
    """Each AI conversation, with its turns, as one record.

    Same shape of decision as a canvas board: the turns belong to the chat,
    so the unit of truth is the chat, and last-writer-wins is its revision.
    """
    conn = db.connect()
    out = []
    for r in conn.execute(
            "SELECT id, title, created_at, updated_at FROM ai_chat"):
        cid = r["id"]
        turns = [{"ord": t["ord"], "role": t["role"] or "user",
                  "content": t["content"] or "",
                  "cites": t["cites"] or ""}
                 for t in conn.execute(
                     "SELECT ord, role, content, cites FROM ai_chat_turn "
                     "WHERE chat_id=? ORDER BY ord", (cid,))]
        out.append({"id": cid, "title": r["title"] or "",
                    "created_at": r["created_at"] or 0.0,
                    "updated_at": r["updated_at"] or r["created_at"] or 0.0,
                    "turns": turns})
    return out


def _collect_morph_queries() -> list[dict]:
    """Saved morphological searches — a refined query the reader built."""
    conn = db.connect()
    out = []
    for r in conn.execute(
            "SELECT id, name, query_json, created_at, updated_at "
            "FROM saved_morph_query"):
        try:
            query = json.loads(r["query_json"])
        except (ValueError, TypeError):
            query = r["query_json"]
        out.append({"id": r["id"], "name": r["name"] or "Saved query",
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "query": query})
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
    "canvas-board": _collect_canvas_boards,
    "ai-chat": _collect_ai_chats,
    "morph-query": _collect_morph_queries,
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


def _apply_canvas_board(p: dict) -> None:
    conn = db.connect()
    bid = (p.get("id") or "").strip()
    if not bid:
        return
    nodes = p.get("nodes") or []
    edges = p.get("edges") or []
    local = conn.execute(
        "SELECT updated_at FROM canvas_board WHERE id=?", (bid,)).fetchone()
    remote_rev = float(p.get("updated_at") or p.get("created_at") or 0.0)
    if local and float(local["updated_at"] or 0.0) >= remote_rev:
        # Local is already at or ahead of this revision — keep it.
        return
    conn.execute("DELETE FROM canvas_node WHERE board_id=?", (bid,))
    conn.execute("DELETE FROM canvas_edge WHERE board_id=?", (bid,))
    conn.execute("DELETE FROM canvas_board WHERE id=?", (bid,))
    conn.execute(
        "INSERT INTO canvas_board(id,name,created_at,updated_at) "
        "VALUES(?,?,?,?)",
        (bid, p.get("name") or "Canvas",
         float(p.get("created_at") or _now()), remote_rev or _now()))
    now = time.time()
    for n in nodes:
        nid = str(n.get("id") or "")[:12]
        if not nid:
            continue
        conn.execute(
            "INSERT INTO canvas_node(id,board_id,kind,x,y,w,h,text,ref,color,"
            "module_id,data,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, bid, str(n.get("kind") or "text"),
             float(n.get("x", 0)), float(n.get("y", 0)),
             float(n.get("w", 200)), float(n.get("h", 100)),
             str(n.get("text") or ""), str(n.get("ref") or ""),
             str(n.get("color") or "yellow"),
             str(n.get("module_id") or ""), str(n.get("data") or ""),
             float(n.get("created_at") or now)))
    for e in edges:
        f = str(e.get("from_id") or "")[:12]
        t = str(e.get("to_id") or "")[:12]
        if f and t and f != t:
            conn.execute(
                "INSERT INTO canvas_edge(id,board_id,from_id,to_id) "
                "VALUES(?,?,?,?)",
                (uuid.uuid4().hex[:12], bid, f, t))
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


def _apply_ai_chat(p: dict) -> None:
    conn = db.connect()
    cid = (p.get("id") or "").strip()
    if not cid:
        raise ValueError("an AI chat needs an id")
    conn.execute(
        "INSERT OR REPLACE INTO ai_chat(id, title, created_at, updated_at) "
        "VALUES(?,?,?,?)",
        (cid, p.get("title") or "",
         float(p.get("created_at") or 0.0),
         float(p.get("updated_at") or 0.0)))
    conn.execute("DELETE FROM ai_chat_turn WHERE chat_id=?", (cid,))
    for t in p.get("turns") or []:
        try:
            ord_ = int(t.get("ord", 0))
        except (TypeError, ValueError):
            continue
        conn.execute(
            "INSERT OR REPLACE INTO ai_chat_turn"
            "(chat_id, ord, role, content, cites) VALUES(?,?,?,?,?)",
            (cid, ord_, t.get("role") or "user",
             t.get("content") or "", t.get("cites") or ""))
    conn.commit()


def _apply_morph_query(p: dict) -> None:
    conn = db.connect()
    rid = (p.get("id") or "").strip()
    name = (p.get("name") or "").strip() or "Saved query"
    query = p.get("query")
    if isinstance(query, str):
        qjson = query
    else:
        try:
            qjson = json.dumps(query, ensure_ascii=False,
                               sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            qjson = "{}"
    # Saved queries are UNIQUE(name); two machines can hold different
    # queries under one name.  The restored one gets a fresh suffix rather
    # than erasing the local one or failing outright.
    clash = conn.execute(
        "SELECT id FROM saved_morph_query WHERE name=?", (name,)).fetchone()
    if clash and (not rid or clash["id"] != rid):
        base, n = name, 2
        while conn.execute(
                "SELECT 1 FROM saved_morph_query WHERE name=?",
                (f"{base} ({n})",)).fetchone():
            n += 1
        name = f"{base} ({n})"
    if rid:
        hit = conn.execute(
            "SELECT id FROM saved_morph_query WHERE id=?", (rid,)).fetchone()
        if hit:
            conn.execute(
                "UPDATE saved_morph_query SET name=?, query_json=?, "
                "created_at=?, updated_at=? WHERE id=?",
                (name, qjson, float(p.get("created_at") or 0.0),
                 float(p.get("updated_at") or 0.0), rid))
        else:
            conn.execute(
                "INSERT INTO saved_morph_query"
                "(id, name, query_json, created_at, updated_at) "
                "VALUES(?,?,?,?,?)",
                (rid, name, qjson, float(p.get("created_at") or 0.0),
                 float(p.get("updated_at") or 0.0)))
    else:
        conn.execute(
            "INSERT INTO saved_morph_query"
            "(id, name, query_json, created_at, updated_at) VALUES(?,?,?,?,?)",
            (uuid.uuid4().hex[:12], name, qjson,
             float(p.get("created_at") or 0.0), float(p.get("updated_at") or 0.0)))
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
    "canvas-board": _apply_canvas_board,
    "ai-chat": _apply_ai_chat,
    "morph-query": _apply_morph_query,
}


def tombstone(rec_id: str, kind: str) -> None:
    """Record a delete so it can travel with the next backup.

    A `.gbz` used to omit deletes entirely: the record simply vanished from the
    snapshot, and every other device brought it back on restore.  The
    `sync_tombstone` table has existed in the schema from the start but was
    never written.  Deletes are *recorded* here and *applied* only by a restore
    that explicitly opts in (`gbz.restore_gbz(apply_deletes=True)`), so ordinary
    additive restores keep their old, non-destructive behaviour.
    """
    rid = str(rec_id or "")
    if not rid:
        return
    try:
        conn = db.connect()
        conn.execute(
            "INSERT OR REPLACE INTO sync_tombstone"
            "(id,kind,deleted_at,rev,dev,ctr) VALUES(?,?,?,?,?,?)",
            (rid, kind, _now(), 1, device_id(), 0))
        conn.commit()
    except Exception:                                       # noqa: BLE001
        # Sync bookkeeping must never make a user-visible delete fail.
        pass


def tombstones(*, max_age: float = TOMBSTONE_KEEP) -> list[dict]:
    """Deletes still worth telling other devices about."""
    try:
        cutoff = _now() - max_age
        conn = db.connect()
        # Expired tombstones are no longer useful and were otherwise kept
        # forever, growing the table on every sync.
        conn.execute("DELETE FROM sync_tombstone WHERE deleted_at<?", (cutoff,))
        conn.commit()
        rows = conn.execute(
            "SELECT id, kind, deleted_at, dev, ctr FROM sync_tombstone "
            "WHERE deleted_at>=? ORDER BY deleted_at", (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:                                       # noqa: BLE001
        return []


def remember_tombstone(rec_id: str, kind: str, deleted_at: float,
                       dev: str = "", ctr: int = 0,
                       conn=None) -> None:
    """Keep a delete learned from another device so it propagates onward.

    A caller restoring inside a transaction passes that connection: committing
    here would finish the restore halfway through and leave it non-atomic.
    """
    try:
        c = conn if conn is not None else db.connect()
        c.execute(
            "INSERT OR REPLACE INTO sync_tombstone"
            "(id,kind,deleted_at,rev,dev,ctr) VALUES(?,?,?,?,?,?)",
            (str(rec_id), kind, float(deleted_at), 1, str(dev or ""), int(ctr or 0)))
        if conn is None:
            c.commit()
    except Exception:                                       # noqa: BLE001
        pass


#: Statements that remove one record of each synced kind.  A kind absent from
#: this map is reported as skipped rather than guessed at.
_DELETERS: dict[str, tuple[str, ...]] = {
    "note": ("DELETE FROM note WHERE id=?",),
    "highlight": ("DELETE FROM highlight WHERE id=?",),
    "layout": ("DELETE FROM pane WHERE layout_id=?",
               "DELETE FROM layout WHERE id=?"),
    "collection": ("DELETE FROM collection_item WHERE collection_id=?",
                   "DELETE FROM collection WHERE id=?"),
    "passage-list": ("DELETE FROM passage_item WHERE list_id=?",
                     "DELETE FROM passage_list WHERE id=?"),
    "passage": ("DELETE FROM passage_item WHERE id=?",),
    "template": ("DELETE FROM search_template WHERE id=?",),
    "tag": ("DELETE FROM tag_item WHERE tag_id=?",
            "DELETE FROM tag WHERE id=?"),
    "favourite": ("UPDATE module SET favorite=0 WHERE id=?",),
    "word-list": ("DELETE FROM word_list_item WHERE list_id=?",
                  "DELETE FROM word_list WHERE id=?"),
    "workflow": ("DELETE FROM workflow_step WHERE workflow_id=?",
                 "DELETE FROM workflow WHERE id=?"),
    "srs-card": ("DELETE FROM srs_card WHERE id=?",),
    "canvas-board": ("DELETE FROM canvas_node WHERE board_id=?",
                     "DELETE FROM canvas_edge WHERE board_id=?",
                     "DELETE FROM canvas_board WHERE id=?"),
    "ai-chat": ("DELETE FROM ai_chat_turn WHERE chat_id=?",
                "DELETE FROM ai_chat WHERE id=?"),
    "morph-query": ("DELETE FROM saved_morph_query WHERE id=?",),
    "citation-meta": ("DELETE FROM citation_meta WHERE module_id=?",),
}


def apply_tombstones(conn, rows: list[dict]) -> dict:
    """Apply foreign deletes inside `conn`'s transaction; return what happened.

    Conservative on purpose: a delete is applied only when a `sync_meta` row
    shows this device already knows the record and its revision is older than
    the delete.  Without that evidence the record may have been created on this
    device and never sent, so removing it would be a guess with real data loss.
    """
    applied: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        kind, rid = str(row.get("kind") or ""), str(row.get("id") or "")
        when = float(row.get("deleted_at") or 0.0)
        # A plan-mark is one key in the reading-plan/progress JSON, not a row.
        # Delete just that plan; deleting the whole setting would erase every
        # other plan on this device.
        special = kind == "plan-mark"
        stmts = _DELETERS.get(kind)
        if not stmts and not special:
            skipped.append({"kind": kind, "id": rid, "why": "unsupported kind"})
            continue
        meta = conn.execute(
            "SELECT updated_at FROM sync_meta WHERE id=? AND kind=?",
            (rid, kind)).fetchone()
        if meta is None:
            skipped.append({"kind": kind, "id": rid,
                            "why": "local revision unknown"})
            continue
        if float(meta["updated_at"] or 0.0) >= when:
            skipped.append({"kind": kind, "id": rid, "why": "local edit is newer"})
            continue
        if special:
            from . import readingplan
            plan = rid[len("plan-"):] if rid.startswith("plan-") else rid
            readingplan.clear_progress(plan, notify=False)
        else:
            for sql in stmts:
                conn.execute(sql, (rid,))
        conn.execute("DELETE FROM sync_meta WHERE id=? AND kind=?", (rid, kind))
        remember_tombstone(rid, kind, when, row.get("dev", ""),
                           row.get("ctr", 0), conn=conn)
        applied.append({"kind": kind, "id": rid})
    return {"applied": applied, "skipped": skipped}


# ------------------------------------------------------------ configuration

def config() -> dict:
    """The saved sync configuration, with no secrets in it."""
    cfg = db.get_setting(K_CONFIG) or {}
    return cfg if isinstance(cfg, dict) else {}


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
        "encrypt": bool(cfg.get("encrypt")),
        "auto_backup_hours": int(cfg.get("auto_backup_hours") or 0),
    }
    # The launcher reads this top-level setting at boot; keeping both in step
    # lets an in-app change take effect without editing the environment.
    db.set_setting("auto_backup_hours", out["auto_backup_hours"])
    if cfg.get("passphrase"):
        save_credentials(out["name"], cfg.get("password") or "")
        creds = _read_credentials()
        passphrase = str(cfg.get("passphrase") or "")
        if out["encrypt"] and len(passphrase) < 12:
            raise SyncError("The encryption passphrase must be at least 12 characters.")
        creds.setdefault(out["name"], {})["passphrase"] = passphrase
        _write_credentials(creds)
    if out["encrypt"]:
        passphrase = encryption_passphrase(out)
        if len(passphrase) < 12:
            raise SyncError("Encryption is on but no valid passphrase is set.")
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
    """Build a .gbz and store it on the configured target.

    One artefact, one action: for a filesystem target that means
    `<folder>/gbible-backup.gbz`; for WebDAV/Nextcloud it means one HTTP
    upload of the same file to the same path.  The interval worker runs this
    on its own thread; the lock stops it overlapping a manual press.
    """
    with _lock:
        cfg = config()
        if not cfg.get("kind"):
            raise SyncError("Sync is not set up yet.")
        if cfg.get("wifi_only") and not force:
            m = metered()
            if m is True:
                db.set_setting(K_LAST_ERROR,
                               "Waiting for an unmetered connection.")
                return {"ok": False, "error":
                        "Waiting for an unmetered connection.",
                        "skipped": "metered"}
            if m is None:
                db.set_setting(K_LAST_ERROR,
                               "Wi-Fi only is on, but whether this connection "
                               "is metered cannot be told (NetworkManager not "
                               "found). Sync is paused until it can.")
                return {"ok": False, "error":
                        "Wi-Fi only is on, but whether this connection is "
                        "metered cannot be told. Sync is paused.",
                        "skipped": "unknown-metered"}

        started = _now()
        db.set_setting(K_LAST_RUN, started)
        try:
            from . import synctargets
            from . import gbz as _gbz
            target = synctargets.from_config(cfg)
            out = _gbz.create_gbz(appearance=None, include_ai=False)
            data = out["data"]
            if cfg.get("encrypt"):
                pw = encryption_passphrase(cfg)
                if not pw:
                    raise SyncError("Encryption is on but no passphrase is set.")
                data = _gbz.encrypt_gbz(data, pw)
            target.write(_gbz.GBZ_NAME, data)
        except Exception as e:
            db.set_setting(K_LAST_ERROR, str(e))
            errorlog.log_exception("sync", e)
            raise

        summary = {"ok": True,
                   "records": sum((out.get("counts") or {}).values()),
                   "bytes": int(out.get("size") or 0),
                   "file": _gbz.GBZ_NAME,
                   "seconds": round(_now() - started, 2)}
        db.set_setting(K_LAST_OK, _now())
        db.set_setting(K_LAST_ERROR, "")
        db.set_setting(K_LAST_SUMMARY, summary)
        return summary


def scope() -> dict:
    """An honest, machine-readable answer to 'what travels on sync?'.

    This is derived from KINDS, SETTINGS_ALLOWLIST and the backup behaviour in
    gbz.py, so the Sync screen cannot drift away from what the code does.  It
    describes the data, not how much of it is currently on this device.
    """
    kinds = []
    for key, folder in KINDS.items():
        ai_only = key == "ai-chat"
        kinds.append({"key": key, "folder": folder,
                      "label": KIND_LABELS.get(key, key),
                      "by_default": not ai_only,
                      "ai_inclusive_only": ai_only})
    return {
        "ok": True,
        "kinds": kinds,
        "settings": [{"key": k, "label": SETTING_LABELS.get(k, k)}
                     for k in SETTINGS_ALLOWLIST],
        "local_only": [
            {"title": "The library itself",
             "detail": "Module files, the search index and the genealogy graph "
                       "are re-installable from the Store. Only the list of "
                       "installed module ids travels."},
            {"title": "Which layout is open",
             "detail": "is_current belongs to the device in front of you; the "
                       "layout's tiles and panes do travel."},
            {"title": "Device-local settings",
             "detail": "flash_session and highlight_palette_active describe this "
                       "screen, not your work."},
            {"title": "Appearance",
             "detail": "Theme, font and size are chosen per device. Only an "
                       "explicit export from the Backup screen carries them."},
            {"title": "Sync passwords",
             "detail": "Never placed in a backup or sync file; kept beside the "
                       "database in a 0600 credentials file."},
        ],
        "ai": {
            "settings_travel": True,
            "conversations_by_default": False,
            "credentials_by_default": False,
            "usage_by_default": False,
            "detail": "AI provider and model settings travel in every archive. "
                      "Conversations, usage history and API keys do not: they "
                      "need an explicit AI-inclusive backup from the Backup "
                      "screen, which is always encrypted with a passphrase.",
        },
        "deletion": {
            "param": "apply_deletes", "default": False,
            "retention_days": TOMBSTONE_KEEP // 86400,
            "detail": "Deletes are remembered as tombstones, then forgotten "
                      "after the retention window. On restore, records deleted "
                      "elsewhere are only removed here if you tick 'Apply "
                      "deletes' — off by default, so a restore only adds what "
                      "is missing.",
        },
        "encryption": {
            "sync_flag": "encrypt", "min_passphrase": 12,
            "ai_forces_encryption": True,
            "detail": "A sync archive is plaintext unless you turn encryption on "
                      "and set a passphrase of at least 12 characters. An "
                      "AI-inclusive export is always encrypted.",
        },
        "notes": [
            "This describes the data; it is not a count of what is currently on "
            "this device.",
            "If you do not want your questions on another device, leave AI "
            "conversations out — ordinary sync already does.",
        ],
    }


def status() -> dict:
    cfg = config()
    summary = db.get_setting(K_LAST_SUMMARY, {}) or {}
    return {"configured": bool(cfg.get("kind")), "kind": cfg.get("kind") or "",
            "name": cfg.get("name") or "", "path": cfg.get("path") or "",
            "url": cfg.get("url") or "", "user": cfg.get("user") or "",
            "interval": cfg.get("interval", 0), "wifi_only": bool(cfg.get("wifi_only")),
            "last_run": db.get_setting(K_LAST_RUN, 0) or 0,
            "last_ok": db.get_setting(K_LAST_OK, 0) or 0,
            "last_error": db.get_setting(K_LAST_ERROR, "") or "",
            "summary": summary, "device_id": device_id(), "metered": metered(),
            "last_file": summary.get("file") or "gbible-backup.gbz",
            "last_size": int(summary.get("bytes") or 0),
            "encrypt": bool(cfg.get("encrypt")),
            "auto_backup_hours": int(cfg.get("auto_backup_hours") or
                                     db.get_setting("auto_backup_hours", 0) or 0),
            "auto_backup_last": float(db.get_setting("auto_backup_last", 0) or 0),
            "intervals": intervals(), "kinds": dict(KINDS)}


def disable() -> None:
    db.set_setting(K_CONFIG, {})
    db.set_setting(K_LAST_ERROR, "")


# ------------------------------------------------------------- auto-backup


def auto_backup() -> dict:
    """Write a timestamped local .gbz and keep the last seven."""
    from . import gbz as _gbz
    out = _gbz.create_gbz(appearance=None, include_ai=False)
    folder = Path(db.app_dir()) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"gbible-backup-{stamp}.gbz"
    target.write_bytes(out["data"])
    for old in sorted(folder.glob("gbible-backup-*.gbz"))[:-7]:
        try:
            old.unlink()
        except OSError:
            pass
    db.set_setting("auto_backup_last", _now())
    return {"ok": True, "file": target.name, "records": out.get("counts", {})}


# ------------------------------------------------------------------ worker

_worker: threading.Thread | None = None
_wake = threading.Event()
_stop = False
_atexit_registered = False

#: How often the worker wakes to see whether a sync is due.  Shorter than the
#: shortest interval so the first sync after boot is not late by much.
_TICK = 20


def start_worker() -> None:
    """Start the interval worker.  Idempotent, and never a reason to fail boot.

    Sync is optional: if it cannot start, the app opens and reads exactly as
    before, and the Settings screen offers Sync now.
    """
    global _worker, _stop, _atexit_registered
    if _worker and _worker.is_alive():
        return
    _stop = False
    try:
        _worker = threading.Thread(target=_loop, name="gbible-sync", daemon=True)
        _worker.start()
        # "When the app closes" was defined but never registered, so that
        # interval choice silently did nothing.  Register once, idempotently.
        if not _atexit_registered:
            atexit.register(_final_sync)
            _atexit_registered = True
    except Exception:
        _worker = None


def _loop() -> None:
    while not _stop:
        _wake.wait(_TICK)
        _wake.clear()
        if _stop:
            return
        cfg = config()
        # The in-app auto-backup setting is independent of the sync interval;
        # run it even when no remote target is configured.  The launcher's
        # environment variable already starts its own thread, so skip it here
        # when both would otherwise write a backup at the same time.
        hours = int(cfg.get("auto_backup_hours") or
                    db.get_setting("auto_backup_hours", 0) or 0)
        if hours > 0 and not os.environ.get("GBIBLE_AUTO_BACKUP"):
            last = float(db.get_setting("auto_backup_last", 0) or 0)
            if _now() - last >= hours * 3600:
                try:
                    auto_backup()
                except Exception as e:
                    db.set_setting(K_LAST_ERROR, f"auto-backup: {e}")
                    errorlog.log_exception("auto-backup", e)
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
            errorlog.log_exception("sync", e)


def _final_sync() -> None:
    """The "when the app closes" interval.

    Registered once, and only while that interval is chosen.  A sync that fails
    on the way out is not worth blocking the exit for.
    """
    cfg = config()
    if int(cfg.get("interval") or 0) != -1:
        return
    # The worker is a daemon thread; if it is mid-sync at exit, waiting on the
    # lock could hang shutdown.  A sync already in progress will write the
    # snapshot anyway, so skip instead of blocking.
    if _lock.locked():
        return
    try:
        run(force=True)
    except Exception as e:
        errorlog.log_exception("sync", e)


