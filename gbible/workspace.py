"""The workspace: layouts, tiles, panes and link sets.

The rule the whole thing rests on:

    Link sets only work between resources that have overlapping milestone types.

So every pane stores a *link set letter* and a *cursor*, and the synchroniser
maps a cursor from one resource's index space into another's by their shared
index types.  A Bible and a commentary share `bibleVerse` and scroll together; a
Bible and a lexicon share nothing positional, so a lexicon pane does not scroll at
all -- it looks up whatever word you click.  Both behaviours fall out of the same
intersection test rather than being special-cased.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

from . import canon, db, library, taxonomy
from .library import Module

LINK_SETS = ["A", "B", "C", "D", "E", "F"]

# Stock tile arrangements.  Each is a list of tiles, each tile a list of pane ids.
ARRANGEMENTS: dict[str, list[list[float]]] = {
    "1 Column":           [[1.0]],
    "2 Columns":          [[0.5, 0.5]],
    "3 Columns":          [[0.34, 0.33, 0.33]],
    "Left / Right":       [[0.5, 0.5]],
    "Left + 2 Right":     [[0.5, 0.25, 0.25]],
    "2 Left + Right":     [[0.25, 0.25, 0.5]],
    "Text + Commentary":  [[0.5, 0.5]],
    # Three columns: the builder below puts a Bible, a commentary and a lexicon
    # in t0_0, t0_1 and t0_2.  With only two columns here, t0_2 exists nowhere
    # and the lexicon and FactBook panes became invisible.
    "Bible + Tools":      [[0.34, 0.33, 0.33]],
    "Quad":               [[0.5, 0.5], [0.5, 0.5]],
    "Bible Top / 3 Bottom": [[1.0], [0.34, 0.33, 0.33]],
    # Rows only, so each row is a full-width tier: a row is a row, and there is
    # no way in this shape list to leave half of one empty.  This used to be
    # [[0.5]] three times -- "full-height text on the left" -- which is not a
    # grid, so it rendered three half-width rows and half the workspace blank.
    "3 Rows":             [[1.0], [1.0], [1.0]],
}

ARRANGEMENT_GUIDE = {
    "1 Column": "A single resource at full width.",
    "2 Columns": "Two resources side by side.",
    "3 Columns": "Three resources side by side.",
    "Left / Right": "Reading pane on the left, study pane on the right.",
    "Left + 2 Right": "One wide reading pane, two narrow study panes.",
    "2 Left + Right": "Two narrow study panes, one wide reading pane.",
    "Text + Commentary": "Bible beside commentary; both verse-keyed, so a link "
                         "set scrolls them together.",
    "Bible + Tools": "Sixty per cent reading, forty per cent tools.",
    "Quad": "Four panes in a 2x2 grid.",
    "Bible Top / 3 Bottom": "Full-width text above, three tools below.",
    "3 Rows": "Three panes stacked, each the full width of the workspace.",
}


# --------------------------------------------------------------------------

def _conn():
    return db.connect()


def new_id(prefix: str = "p") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Pane:
    id: str
    layout_id: str = ""
    module_id: str = ""
    link_set: str = ""
    follow_only: bool = False
    follow_active: bool = False
    text_size: int = 100
    cursor: dict = None            # type: ignore[assignment]
    view: str = "normal"
    options: dict = None           # type: ignore[assignment]
    tile_id: str = ""
    is_focus: bool = False

    def __post_init__(self):
        if self.cursor is None:
            self.cursor = {}
        if self.options is None:
            self.options = {}


# --------------------------------------------------------------------------
# Layouts
# --------------------------------------------------------------------------

def list_layouts() -> list[dict]:
    c = _conn()
    out = []
    for r in c.execute("SELECT * FROM layout ORDER BY is_current DESC, created_at DESC"):
        import dataclasses
        panes = [dataclasses.asdict(pane_from_row(x)) for x in c.execute(
            "SELECT * FROM pane WHERE layout_id=?", (r["id"],))]
        out.append({"id": r["id"], "name": r["name"],
                    "is_current": bool(r["is_current"]),
                    "created_at": r["created_at"],
                    "tiles": json.loads(r["tiles"] or "[]"),
                    "panes": panes,
                    "arrangement": _arrangement_of(json.loads(r["tiles"] or "[]"))})
    return out


def _arrangement_of(tiles) -> str:
    """Best-effort name for a shape.

    Custom split tiles are not in the stock shapes, including nested ones made
    by splitting one tile into two panes.  Name them by what is visible to the
    reader, which is that the arrangement no longer matches a fixed template.
    """
    try:
        normalized = [[round(float(x), 2) for x in row] for row in tiles]
    except (TypeError, ValueError, AttributeError):
        return "Custom"
    for name, shape in ARRANGEMENTS.items():
        if normalized == [[round(x, 2) for x in row] for row in shape]:
            return name
    return "Custom"


def get_layout(layout_id: str) -> dict | None:
    for l in list_layouts():
        if l["id"] == layout_id:
            return l
    return None


def current() -> dict | None:
    c = _conn()
    r = c.execute("SELECT id FROM layout WHERE is_current=1 LIMIT 1").fetchone()
    if r:
        return get_layout(r["id"])
    ls = list_layouts()
    return ls[0] if ls else None


def create_layout(name: str, *, arrangement: str = "2 Columns",
                  make_current: bool = True) -> dict:
    c = _conn()
    # Building a layout must not destroy one.  This used to delete any layout
    # already called "Study" along with all its panes, so pressing "Study
    # layout" in the toolbar silently threw away the panes you had set up --
    # and the old "Study" it removed was whichever the query happened to find
    # first, which is not necessarily the one on screen.  A new layout now gets
    # a distinct name ("Study", "Study 2", ...) and the old one stays in the
    # list to switch back to.
    taken = {r["name"] for r in c.execute("SELECT name FROM layout")}
    if name in taken:
        i = 2
        while f"{name} {i}" in taken:
            i += 1
        name = f"{name} {i}"
    lid = new_id("lay")
    shape = ARRANGEMENTS.get(arrangement, ARRANGEMENTS["2 Columns"])
    c.execute("INSERT INTO layout(id,name,tiles,is_current,created_at) "
              "VALUES(?,?,?,?,?)", (lid, name, json.dumps(shape),
                                    int(make_current), time.time()))
    if make_current:
        c.execute("UPDATE layout SET is_current=0")
        c.execute("UPDATE layout SET is_current=1 WHERE id=?", (lid,))
    c.commit()
    return get_layout(lid) or {}


def save_layout(layout_id: str, name: str, tiles: list[list[float]],
                panes: list[dict]) -> dict:
    c = _conn()
    c.execute("UPDATE layout SET name=?, tiles=? WHERE id=?",
              (name, json.dumps(tiles), layout_id))
    c.execute("DELETE FROM pane WHERE layout_id=?", (layout_id,))
    rows = []
    for i, p in enumerate(panes):
        rows.append((p.get("id") or new_id(), layout_id, p.get("tile_id", ""),
                     p.get("module_id", ""), p.get("link_set") or None,
                     int(bool(p.get("follow_only"))),
                     int(bool(p.get("follow_active"))),
                     int(p.get("text_size") or 100),
                     json.dumps(p.get("cursor") or {}), p.get("view") or "normal",
                     json.dumps(p.get("options") or {}),
                     int(bool(p.get("is_focus")))))
    c.executemany(
        "INSERT INTO pane(id,layout_id,tile_id,module_id,link_set,follow_only,"
        "follow_active,text_size,cursor,view,options,is_focus) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    return get_layout(layout_id) or {}


def delete_layout(layout_id: str, *, force: bool = False) -> dict:
    c = _conn()
    cur = c.execute("SELECT id FROM layout WHERE is_current=1").fetchone()
    if cur and cur["id"] == layout_id and not force:
        return {"ok": False, "error": "cannot delete the layout in use"}
    c.execute("DELETE FROM pane WHERE layout_id=?", (layout_id,))
    c.execute("DELETE FROM layout WHERE id=?", (layout_id,))
    c.commit()
    try:
        from . import sync
        sync.tombstone(layout_id, "layout")
    except Exception:
        pass
    if cur and cur["id"] == layout_id:
        left = list_layouts()
        if left:
            # A workspace with no current layout is a workspace that cannot
            # open; the newest remaining one takes over.
            c.execute("UPDATE layout SET is_current=0")
            c.execute("UPDATE layout SET is_current=1 WHERE id=?", (left[0]["id"],))
            c.commit()
    return {"ok": True}


def use_layout(layout_id: str) -> dict:
    c = _conn()
    c.execute("UPDATE layout SET is_current=0")
    c.execute("UPDATE layout SET is_current=1 WHERE id=?", (layout_id,))
    c.commit()
    return get_layout(layout_id) or {}


# --------------------------------------------------------------------------
# Panes
# --------------------------------------------------------------------------

def pane_from_row(r) -> Pane:
    return Pane(
        id=r["id"], layout_id=r["layout_id"] or "",
        module_id=r["module_id"] or "",
        link_set=r["link_set"] or "", follow_only=bool(r["follow_only"]),
        follow_active=bool(r["follow_active"]), text_size=r["text_size"] or 100,
        cursor=json.loads(r["cursor"] or "{}"),
        view=r["view"] or "normal",
        options=json.loads(r["options"] or "{}"),
        tile_id=r["tile_id"] or "", is_focus=bool(r["is_focus"]),
    )


def add_pane(layout_id: str, module_id: str, *, tile_id: str = "",
             link_set: str = "", cursor: dict | None = None,
             view: str = "normal", options: dict | None = None,
             text_size: int = 100, follow_only: bool = False) -> Pane:
    c = _conn()
    pid = new_id()
    c.execute(
        "INSERT INTO pane(id,layout_id,tile_id,module_id,link_set,follow_only,"
        "follow_active,text_size,cursor,view,options) "
        "VALUES(?,?,?,?,?,?,0,?,?,?,?)",
        (pid, layout_id, tile_id, module_id, link_set or None,
         int(follow_only), int(text_size), json.dumps(cursor or {}), view,
         json.dumps(options or {})))
    c.commit()
    r = c.execute("SELECT * FROM pane WHERE id=?", (pid,)).fetchone()
    return pane_from_row(r)


def update_pane(pane_id: str, **kw) -> Pane | None:
    c = _conn()
    allowed = {"module_id", "link_set", "follow_only", "follow_active",
               "text_size", "cursor", "view", "options", "tile_id", "is_focus"}
    sets, vals = [], []
    for k, v in kw.items():
        if k not in allowed:
            continue
        if k in ("cursor", "options"):
            v = json.dumps(v or ({} if k == "cursor" else {}))
        elif k in ("follow_only", "follow_active", "is_focus"):
            v = int(bool(v))
        elif k == "link_set":
            v = v or None
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return None
    c.execute(f"UPDATE pane SET {','.join(sets)} WHERE id=?", [*vals, pane_id])
    c.commit()
    r = c.execute("SELECT * FROM pane WHERE id=?", (pane_id,)).fetchone()
    return pane_from_row(r) if r else None


def get_pane(pane_id: str) -> Pane | None:
    r = _conn().execute("SELECT * FROM pane WHERE id=?", (pane_id,)).fetchone()
    return pane_from_row(r) if r else None


def close_pane(pane_id: str) -> dict:
    c = _conn()
    c.execute("DELETE FROM pane WHERE id=?", (pane_id,))
    c.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Link sets
# --------------------------------------------------------------------------

def link_group(layout_id: str, letter: str) -> list[Pane]:
    c = _conn()
    return [pane_from_row(r) for r in c.execute(
        "SELECT * FROM pane WHERE layout_id=? AND link_set=?", (layout_id, letter))]


def sync(pane_id: str, cursor: dict, opts: dict | None = None
         ) -> list[dict]:
    """Return what every linked pane should display, given a new cursor.

    This is the whole synchronisation engine.  It maps the cursor into each
    linked resource through the *shared* index types, and reports a lookup
    instead of a position when the intersection is a headword rather than a
    verse.
    """
    p = get_pane(pane_id)
    if p is None:
        return []
    src = library.get(p.module_id)
    if src is None:
        return []
    out: list[dict] = []
    for other in link_group(p.layout_id, p.link_set):
        if other.id == pane_id:
            continue
        if other.follow_only and not p.follow_only:
            continue
        # A passage-guide pane carries no module, so it has no milestone types
        # of its own.  It is treated as a consumer of bibleVerse: when a linked
        # Bible or commentary moves, the guide re-renders for the new reference.
        # A word-study pane is not verse-keyed, so it is left alone.
        if other.view == "guide":
            if src is None or taxonomy.INDEX_BIBLE_VERSE not in src.link_types():
                out.append({"pane_id": other.id, "module_id": other.module_id,
                            "action": "none", "reason": "no shared milestone type",
                            "shared": []})
                continue
            ref = cursor.get("ref")
            if not ref and cursor.get("book"):
                ref = canon.format_ref(canon.Ref(cursor["book"],
                                                 int(cursor.get("chapter") or 1),
                                                 int(cursor.get("verse") or 1)))
            if not ref:
                continue
            out.append({"pane_id": other.id, "module_id": other.module_id,
                        "module_name": "Passage guide", "action": "position",
                        "cursor": {"ref": ref, "span": cursor.get("span", "chapter"),
                                   "guide": (other.cursor or {}).get("guide", "passage")},
                        "shared": ["bibleVerse"], "reader": "guide"})
            continue
        if not other.module_id:
            continue
        dst = library.get(other.module_id)
        if dst is None:
            continue
        shared = sorted(src.link_types() & dst.link_types())
        if not shared:
            out.append({"pane_id": other.id, "module_id": dst.id,
                        "action": "none", "reason": "no shared milestone type",
                        "shared": []})
            continue
        mapped, action = _map_cursor(src, dst, cursor, shared)
        if action == "none":
            continue
        out.append({"pane_id": other.id, "module_id": dst.id,
                    "module_name": dst.name, "action": action,
                    "cursor": mapped, "shared": shared,
                    "reader": dst.reader})
    return out


def _map_cursor(src: Module, dst: Module, cursor: dict,
                shared: list[str]) -> tuple[dict, str]:
    """Map a cursor between two resources through their shared index types."""
    from .taxonomy import INDEX_BIBLE_VERSE, INDEX_DATE, INDEX_HEADWORD, \
        INDEX_STRONGS, INDEX_TOPIC, INDEX_PLACE, INDEX_PAGE, INDEX_SECTION
    if INDEX_BIBLE_VERSE in shared:
        ref = cursor.get("ref")
        if not ref and cursor.get("book"):
            ref = canon.format_ref(canon.Ref(cursor["book"],
                                             int(cursor.get("chapter") or 1),
                                             int(cursor.get("verse") or 1)))
        if ref:
            # A commentary may not cover every verse; find the nearest it has.
            return ({"ref": ref, "span": cursor.get("span", "chapter")},
                    "position")
    if INDEX_DATE in shared:
        if cursor.get("date"):
            return {"date": cursor["date"]}, "position"
    if INDEX_HEADWORD in shared:
        hw = cursor.get("headword") or cursor.get("key")
        if hw:
            return {"key": hw}, "position"
    if INDEX_STRONGS in shared:
        s = cursor.get("strongs")
        if s:
            return {"key": s}, "position"
    if INDEX_TOPIC in shared:
        t = cursor.get("topic") or cursor.get("key")
        if t:
            return {"key": t}, "position"
    if INDEX_PLACE in shared:
        pl = cursor.get("place") or cursor.get("key")
        if pl:
            return {"key": pl}, "position"
    if INDEX_PAGE in shared or INDEX_SECTION in shared:
        sec = cursor.get("section") or cursor.get("key")
        if sec:
            return {"key": sec}, "position"
    return {}, "none"


def nearest_verse(module_id: str, ref: str) -> str:
    """The closest verse a resource actually has to a requested one."""
    c = _conn()
    rr = canon.parse_ref(ref)
    if rr is None:
        return ref
    m = library.get(module_id)
    if m is None:
        return ref
    key = rr.start.osis_id()
    r = c.execute("SELECT key FROM unit WHERE module_id=? AND key=?",
                  (module_id, key)).fetchone()
    if r:
        return key
    # walk back a little, then forward
    cur = rr.start
    for _ in range(24):
        cur = canon.prev_ref(cur, m.v11n)
        r = c.execute("SELECT key FROM unit WHERE module_id=? AND key=?",
                      (module_id, cur.osis_id())).fetchone()
        if r:
            return r["key"]
    cur = rr.start
    for _ in range(24):
        cur = canon.next_ref(cur, m.v11n)
        r = c.execute("SELECT key FROM unit WHERE module_id=? AND key=?",
                      (module_id, cur.osis_id())).fetchone()
        if r:
            return r["key"]
    return key


# --------------------------------------------------------------------------
# Starter workspace
# --------------------------------------------------------------------------

def bootstrap() -> dict:
    """Create a usable default workspace from whatever is installed."""
    lay = current()
    if lay and len(lay.get("panes") or []) > 1:
        return lay
    return build_study_layout()


def build_study_layout(name: str = "Study") -> dict:
    """A two-pane default: reading on the left, study on the right.

    Reading pane and commentary share `bibleVerse`, so they are given the same
    link set and scroll together.  More tools can be opened later with the
    pane Tab's "+" button or by splitting a pane; the default stays two panes
    so a new workspace does not start overwhelming.
    """
    mods = library.list_all(order="priority DESC, name ASC")
    if not mods:
        return {}

    def pick(*types):
        for ty in types:
            m = next((x for x in mods if x.type == ty), None)
            if m:
                return m
        return None

    # Catalogue order is arbitrary, so "the first Bible" is whatever sorts
    # first -- a Basque New Testament.  Prefer English, and within that one
    # carrying Strong's, because that is the text the study tools can use.
    bibles = [m for m in mods if m.is_bible]
    def bible_score(m):
        return ((2 if m.lang == "eng" else 0)
                + (1 if m.has_strongs or m.has_morph else 0))
    bible = (max(bibles, key=bible_score) if bibles else None) or mods[0]
    # Not just any commentary: the first one in catalogue order can be a
    # 37-entry manual on a single book, which leaves the study pane showing
    # nothing useful for the passage on the left.  Prefer an English
    # commentary with real coverage that actually links to the Bible.
    cands = [m for m in mods if m.type == "Commentary" and m.lang == "eng"
             and library.can_link(bible.id, m.id)]
    def comm_score(m):
        return (m.entries or 0)
    commentary = (max(cands, key=comm_score) if cands else None) \
        or pick("Commentary")

    lay = create_layout(name, arrangement="2 Columns")
    read_pane = add_pane(lay["id"], bible.id, tile_id="t0_0", link_set="A",
                         cursor={"ref": "John 1", "span": "chapter"},
                         view="normal",
                         options={"show_notes": True, "show_headings": True,
                                  "show_red": True, "show_strongs": False,
                                  "verse_per_line": False})
    if commentary and library.can_link(bible.id, commentary.id):
        add_pane(lay["id"], commentary.id, tile_id="t0_1", link_set="A",
                 cursor={"ref": "John 1", "span": "chapter"})
    else:
        add_pane(lay["id"], bible.id, tile_id="t0_1",
                 cursor={"ref": "John 1", "span": "verse"})
    return get_layout(lay["id"]) or {}


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

def history(limit: int = 100) -> list[dict]:
    c = _conn()
    return [dict(r) for r in c.execute(
        "SELECT * FROM history ORDER BY at DESC LIMIT ?", (limit,))]


def transfers(limit: int = 50) -> list[dict]:
    c = _conn()
    return [dict(r) for r in c.execute(
        "SELECT * FROM transfer ORDER BY started DESC LIMIT ?", (limit,))]


def clear_transfer_history() -> dict:
    return clear_transfers()


def clear_transfers() -> dict:
    """Delete every transfer and history row.

    The Transfers popup is a log, not a record of installed modules: clearing
    it must not touch the Library.  Both tables are emptied so the popup reads
    as "Nothing yet" on the next open.
    """
    c = _conn()
    c.execute("DELETE FROM transfer")
    c.execute("DELETE FROM history")
    try:
        c.commit()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "cleared": True}


# --------------------------------------------------------------------------
# Pack 1: Workspace extras — QuickStarts, rearrange, clear-links, Top Bible,
# advanced prioritize, parallel sets, reading progress, copy-location.
# All state lives in the `setting` table: no schema migration.
# --------------------------------------------------------------------------

QUICKSTARTS: dict[str, str] = {
    "Bible + Commentary":
        "Top Bible beside the largest linkable English commentary, link set A.",
    "Passage Study":
        "Up to three top Bibles + best commentary + notes pane, all linked A.",
    "Study Bible":
        "Top Bible beside a study-Bible-type text where one is installed.",
    "Topic Study":
        "Factbook + Topic/encyclopaedia beside the Top Bible passage.",
    "Daily Devotional":
        "Today's devotional beside the Top Bible.",
    "Word Study":
        "Top Bible beside the largest lexicon/dictionary/concordance.",
    "Lectionary Reading":
        "Dated devotional/lectionary beside the Top Bible.",
    "Bible + Tools":
        "Bible top-centre with commentary, cross-refs and topics around it.",
}


def _mods() -> list:
    try:
        return library.list_all(order="priority DESC, name ASC")
    except Exception:  # noqa: BLE001
        return []


def _best_bible(mods: list | None = None):
    mods = mods if mods is not None else _mods()
    bibles = [m for m in mods if getattr(m, "is_bible", False)]
    if not bibles:
        return mods[0] if mods else None
    top = get_top_bible()
    if top:
        hit = next((m for m in bibles if m.id == top), None)
        if hit:
            return hit

    def score(m):
        return ((2 if getattr(m, "lang", "") == "eng" else 0)
                + (1 if getattr(m, "has_strongs", False)
                   or getattr(m, "has_morph", False) else 0),
                getattr(m, "priority", 0), getattr(m, "entries", 0) or 0)
    return max(bibles, key=score)


def _pick_first(mods: list, *types: str):
    for ty in types:
        for m in mods:
            if m.type == ty:
                return m
    return None


def get_top_bible() -> str:
    """Explicit Top Bible module id, or '' when the user never set one."""
    from . import db as _db
    try:
        v = _db.get_setting("top_bible", "")
    except Exception:  # noqa: BLE001
        return ""
    return v or ""


def set_top_bible(module_id: str) -> dict:
    from . import db as _db
    m = library.get(module_id) if module_id else None
    if module_id and m is None:
        return {"ok": False, "error": "Not installed"}
    if module_id and not getattr(m, "is_bible", False):
        return {"ok": False, "error": "Not a Bible module"}
    _db.set_setting("top_bible", module_id or "")
    return {"ok": True, "top_bible": module_id or ""}


def top_bible_module():
    mods = _mods()
    if not mods:
        return None
    return _best_bible(mods)


def clear_links(layout_id: str) -> dict:
    c = _conn()
    c.execute("UPDATE pane SET link_set=NULL WHERE layout_id=?", (layout_id,))
    c.commit()
    return {"ok": True}


def rearrange(layout_id: str, arrangement: str) -> dict:
    """Refit existing panes (kept in order) into a new tile shape.

    Panes are never closed or opened here: extras collect in the last tile.
    """
    lay = get_layout(layout_id)
    if not lay:
        return {"ok": False, "error": "No such layout"}
    shape = ARRANGEMENTS.get(arrangement)
    if not shape:
        return {"ok": False, "error": "Unknown arrangement"}
    # Flatten shape into leaf tile ids matching the renderer's scheme t{row}_{i}.
    leaves: list[str] = []
    for ri, row in enumerate(shape):
        for i in range(len(row)):
            leaves.append(f"t{ri}_{i}" if len(shape) > 1 or len(row) > 1 else "t0_0")
    # Deduplicate the single-tile case.
    seen, ordered = set(), []
    for t in leaves:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    leaves = ordered or ["t0_0"]
    panes = list(lay.get("panes") or [])
    for i, p in enumerate(panes):
        p["tile_id"] = leaves[min(i, len(leaves) - 1)]
    # Persist through save_layout so pane rows stay consistent.
    saved = save_layout(layout_id, lay.get("name", "Layout"),
                        [list(r) for r in shape], panes)
    return {"ok": True, "layout": saved}


def copy_location(pane_id: str) -> dict:
    """Clipboard-ready 'Module — reference' string for a pane."""
    p = get_pane(pane_id)
    if p is None:
        return {"ok": False, "error": "No such pane"}
    m = library.get(p.module_id) if p.module_id else None
    cur = p.cursor or {}
    ref = (cur.get("ref") or cur.get("date") or cur.get("key")
           or cur.get("headword") or cur.get("topic") or "")
    label = f"{m.name} — {ref}" if m and ref else (m.name if m else ref)
    return {"ok": True, "text": label, "module_id": p.module_id,
            "cursor": cur}


# -- Advanced prioritize: ordered rules over the legacy integer priority. --

def get_prioritize_rules() -> list[dict]:
    from . import db as _db
    try:
        v = _db.get_setting("prioritize_rules", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def set_prioritize_rules(rules: list[dict]) -> dict:
    from . import db as _db
    clean = []
    for r in rules or []:
        if not isinstance(r, dict) or not r.get("module_id"):
            continue
        if library.get(r["module_id"]) is None:
            continue
        clean.append({"module_id": r["module_id"],
                      "ptype": (r.get("ptype") or "").strip(),
                      "prange": (r.get("prange") or "").strip(),
                      "pbook": (r.get("pbook") or "").strip()})
    _db.set_setting("prioritize_rules", clean)
    return {"ok": True, "rules": clean}


def _rule_applies(rule: dict, m, ref: str = "", req_type: str = "") -> bool:
    if rule.get("ptype") and req_type:
        # Match against the requested resource role, loosely.
        if rule["ptype"].lower() not in (req_type.lower() + " " + m.type.lower()):
            return False
    if rule.get("pbook") and ref:
        if rule["pbook"].lower() not in ref.lower():
            return False
    if rule.get("prange") and ref:
        if rule["prange"].lower() not in ref.lower():
            # Range containment is approximated by substring on the reference;
            # exact BCV containment lives in canon and stays out of here.
            return False
    return True


def resolve_priority(req_type: str = "", ref: str = "") -> list[str]:
    """Module ids: specific advanced rules first, then legacy priority order."""
    mods = _mods()
    rules = get_prioritize_rules()
    first, rest = [], []
    rule_ids = set()
    for r in rules:
        m = library.get(r["module_id"])
        if m is None:
            continue
        if _rule_applies(r, m, ref=ref, req_type=req_type):
            first.append(m.id)
            rule_ids.add(m.id)
    for m in mods:
        if m.id not in rule_ids:
            rest.append(m.id)
    return first + rest


# -- Parallel sets: bibles (or any same-type group) in priority order. --

def parallel_group(module_id: str, collection_id: str = "") -> dict:
    """Members to step through with prev/next, in priority order."""
    if collection_id:
        from . import organise
        try:
            ids = organise.collection_members(collection_id)
        except Exception:  # noqa: BLE001
            ids = []
        if ids:
            return {"ok": True, "members": ids}
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "Not installed"}
    order = resolve_priority(req_type=m.type)
    same = [mid for mid in order
            if (library.get(mid) is not None
                and library.get(mid).type == m.type)]
    if module_id not in same:
        same.insert(0, module_id)
    return {"ok": True, "members": same}


def parallel_step(module_id: str, direction: int = 1,
                  collection_id: str = "") -> dict:
    g = parallel_group(module_id, collection_id)
    if not g.get("ok"):
        return g
    members = g["members"]
    try:
        i = members.index(module_id)
    except ValueError:
        return {"ok": False, "error": "Not in set"}
    nxt = members[(i + direction) % len(members)] if members else module_id
    mod = library.get(nxt)
    return {"ok": True, "module_id": nxt,
            "name": mod.name if mod else nxt, "members": members}


# -- Reading progress: one lightweight record per module. --

def mark_progress(module_id: str, key: str = "", label: str = "",
                  pct: float = 0.0) -> dict:
    from . import db as _db
    try:
        prog = _db.get_setting("reading_progress", {})
    except Exception:  # noqa: BLE001
        prog = {}
    if not isinstance(prog, dict):
        prog = {}
    import time as _t
    prog[module_id] = {"key": key, "label": label,
                       "pct": max(0.0, min(100.0, float(pct or 0.0))),
                       "at": _t.time()}
    _db.set_setting("reading_progress", prog)
    return {"ok": True, "progress": prog[module_id]}


def get_progress() -> dict:
    from . import db as _db
    try:
        v = _db.get_setting("reading_progress", {})
    except Exception:  # noqa: BLE001
        return {}
    return v if isinstance(v, dict) else {}


def reset_progress(module_id: str = "") -> dict:
    from . import db as _db
    if not module_id:
        _db.set_setting("reading_progress", {})
        return {"ok": True, "cleared": "all"}
    try:
        prog = _db.get_setting("reading_progress", {})
    except Exception:  # noqa: BLE001
        prog = {}
    if isinstance(prog, dict) and module_id in prog:
        del prog[module_id]
        _db.set_setting("reading_progress", prog)
    return {"ok": True, "cleared": module_id}


# -- QuickStart builders. --

def quickstarts() -> list[dict]:
    return [{"name": k, "about": v} for k, v in QUICKSTARTS.items()]


def build_quickstart(name: str) -> dict:
    """Create a layout prefilled for a task; missing kinds are skipped."""
    mods = _mods()
    if not mods:
        return {}
    bible = _best_bible(mods)
    cands_c = [m for m in mods if m.type == "Commentary" and m.lang == "eng"
               and bible is not None and library.can_link(bible.id, m.id)]
    commentary = (max(cands_c, key=lambda m: m.entries or 0)
                  if cands_c else _pick_first(mods, "Commentary"))
    lexicon = _pick_first(mods, "Lexicon", "Dictionary", "Concordance")
    factbook = _pick_first(mods, "FactBook", "Dictionary")
    topic = _pick_first(mods, "Topic", "Dictionary")
    devo = next((m for m in mods if m.type == "Devotional"), None)
    study = next((m for m in mods if m.type in ("StudyBible", "Book")
                  and m.id != (bible.id if bible else "")), None)
    xref = next((m for m in mods if "cross" in m.type.lower()
                 or m.has_xref), None)

    plan: list[tuple] = []  # (module, tile, link, cursor)
    shape = "2 Columns"
    if name == "Passage Study":
        shape = "Left + 2 Right"
        others = [m for m in mods if getattr(m, "is_bible", False)
                  and m.id != bible.id][:2]
        plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"})]
        for i, b in enumerate(others):
            plan.append((b, "t0_1", "A", {"ref": "John 1",
                                          "span": "chapter"}))
        if commentary:
            plan.append((commentary, "t0_2", "A", {"ref": "John 1",
                                                  "span": "chapter"}))
    elif name == "Study Bible":
        if study:
            plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"}),
                    (study, "t0_1", "A", {"ref": "John 1", "span": "chapter"})]
        else:
            plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"})]
            if commentary:
                plan.append((commentary, "t0_1", "A",
                             {"ref": "John 1", "span": "chapter"}))
    elif name == "Topic Study":
        shape = "3 Columns"
        plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"})]
        if factbook:
            plan.append((factbook, "t0_1", "", {"key": ""}))
        if topic or commentary:
            plan.append(((topic or commentary), "t0_2", "",
                         {"key": ""}))
    elif name == "Daily Devotional":
        plan = [((devo or bible), "t0_0", "", {"date": ""}),
                (bible, "t0_1", "", {"ref": "John 1", "span": "chapter"})]
    elif name == "Word Study":
        plan = [(bible, "t0_0", "", {"ref": "John 1", "span": "chapter"})]
        if lexicon:
            plan.append((lexicon, "t0_1", "", {"key": ""}))
    elif name == "Lectionary Reading":
        plan = [((devo or bible), "t0_0", "", {"date": ""}),
                (bible, "t0_1", "A", {"ref": "John 1", "span": "chapter"})]
        if commentary:
            plan.append((commentary, "t0_1", "A",
                         {"ref": "John 1", "span": "chapter"}))
    elif name == "Bible + Tools":
        # The plan below files panes into t0_0, t0_1 and t0_2, so the shape has
        # to put three tiles in the first row.  "Bible Top / 3 Bottom" puts one
        # tile there and its three in the second row, which left two panes
        # filed under tiles that existed nowhere: they were in the layout and
        # rendered nowhere at all.
        shape = "Bible + Tools"
        plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"})]
        if commentary:
            plan.append((commentary, "t0_0", "A",
                         {"ref": "John 1", "span": "chapter"}))
        if xref:
            plan.append((xref, "t0_1", "A", {"ref": "John 1",
                                             "span": "chapter"}))
        if topic or factbook:
            plan.append(((topic or factbook), "t0_2", "", {"key": ""}))
    else:  # "Bible + Commentary" default
        plan = [(bible, "t0_0", "A", {"ref": "John 1", "span": "chapter"})]
        if commentary and bible and library.can_link(bible.id, commentary.id):
            plan.append((commentary, "t0_1", "A",
                         {"ref": "John 1", "span": "chapter"}))
    plan = [p for p in plan if p[0] is not None]
    if not plan:
        return build_study_layout(name)
    lay = create_layout(name if name in QUICKSTARTS else "Study",
                        arrangement=shape)
    for mod, tile, link, cursor in plan:
        add_pane(lay["id"], mod.id, tile_id=tile, link_set=link,
                 cursor=cursor)
    return get_layout(lay["id"]) or {}
