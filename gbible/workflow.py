"""Study workflows: a saved arrangement of panes *with a sequence*.

A layout says "Bible on the left, notes on the right".  A workflow says "read
this, then look up this word, then open the outline here, and stop".  The
difference is the ordering, and the ordering is the part that is worth saving:
nobody retypes the same five-pane drill, and nobody wants to re-open the same
four resources at the same passage every Sunday.

So a workflow is captured from a workspace rather than built from nothing.
`capture()` takes the panes you have open, in the order you have them open, and
writes them down; from then on it is editable, reorderable, and runnable at any
passage.  Steps can also be added by intent rather than by example -- "the first
commentary for this book", "a search for this topic", "the outline" -- which is
how a flow can be shared between passages instead of tied to the one you
happened to be reading.

A workflow does not touch the library.  Running one only opens panes, exactly
as clicking would, so a broken step costs you a pane and nothing else.
"""

from __future__ import annotations

import json
import time
import uuid

from . import db, library, placement

STEP_KINDS = ("open", "search", "outline", "word", "clause")


def _id(prefix: str = "wf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:11]}"


def _row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "note": r["note"] or "",
            "ref": r["ref"] or "", "layout_id": r["layout_id"] or "",
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _step_row(r) -> dict:
    def loads(v, default):
        try:
            return json.loads(v) if v else default
        except (json.JSONDecodeError, TypeError):
            return default
    return {"id": r["id"], "workflow_id": r["workflow_id"],
            "position": r["position"], "kind": r["kind"],
            "module_id": r["module_id"] or "", "slot": r["slot"] or "",
            "cursor": loads(r["cursor"], {}), "query": r["query"] or "",
            "link_set": r["link_set"] or "", "text_size": r["text_size"] or 100,
            "options": loads(r["options"], {}), "note": r["note"] or ""}


# ------------------------------------------------------------------- CRUD

def _pick(data: dict, field: str, old: dict):
    """The new value for a column, or the one already stored.

    `None` means "not mentioned", so a partial update leaves the rest alone.
    An absent key and an explicit empty string are different: one is silence,
    the other is an instruction to clear the field.
    """
    v = data.get(field)
    return old.get(field, "") if v is None else v


def save(data: dict, steps: list | None = None) -> dict:
    """Create or update a workflow, and optionally replace its steps."""
    conn = db.connect()
    now = time.time()
    wid = (data.get("id") or "").strip() or _id()
    row = conn.execute("SELECT * FROM workflow WHERE id=?", (wid,)).fetchone()
    # A partial update -- "just reorder the steps" -- may leave the name out,
    # in which case the stored one stands rather than the save being refused.
    name = (data.get("name") or (_row(row)["name"] if row is not None else "")
            or "").strip()
    if not name:
        return {"ok": False, "error": "a workflow needs a name"}
    if row is None:
        conn.execute(
            "INSERT INTO workflow(id,name,note,ref,layout_id,created_at,"
            "updated_at) VALUES(?,?,?,?,?,?,?)",
            (wid, name, data.get("note") or "", data.get("ref") or "",
             data.get("layout_id") or "", now, now))
    else:
        old = _row(row)
        # One binding per column, in order.  This had a leftover `name,` from
        # the INSERT above it, so every update to an existing workflow raised
        # "Incorrect number of bindings supplied" -- which means renaming one, or
        # saving an edited step list, never worked at all.
        conn.execute(
            "UPDATE workflow SET name=?,note=?,ref=?,updated_at=? WHERE id=?",
            (_pick(data, "name", old), _pick(data, "note", old),
             _pick(data, "ref", old), now, wid))
    if steps is not None:
        _replace_steps(conn, wid, steps)
    conn.commit()
    return get(wid) or {}


def _replace_steps(conn, wid: str, steps: list) -> None:
    conn.execute("DELETE FROM workflow_step WHERE workflow_id=?", (wid,))
    for i, s in enumerate(steps):
        kind = (s.get("kind") or "open").strip()
        if kind not in STEP_KINDS:
            kind = "open"
        conn.execute(
            "INSERT INTO workflow_step(id,workflow_id,position,kind,module_id,"
            "slot,cursor,query,link_set,text_size,options,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id("ws"), wid, i, kind, s.get("module_id") or "",
             s.get("slot") or "", json.dumps(s.get("cursor") or {}),
             s.get("query") or "", s.get("link_set") or "",
             int(s.get("text_size") or 100),
             json.dumps(s.get("options") or {}), s.get("note") or ""))


def get(workflow_id: str) -> dict | None:
    conn = db.connect()
    r = conn.execute("SELECT * FROM workflow WHERE id=?",
                     (workflow_id,)).fetchone()
    if not r:
        return None
    out = _row(r)
    out["steps"] = [_step_row(s) for s in conn.execute(
        "SELECT * FROM workflow_step WHERE workflow_id=? ORDER BY position",
        (workflow_id,))]
    out["ok"] = True
    return out


def listing() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute(
            "SELECT w.*, (SELECT count(*) FROM workflow_step s "
            "WHERE s.workflow_id=w.id) AS steps FROM workflow w "
            "ORDER BY COALESCE(w.updated_at, w.created_at) DESC"):
        d = _row(r)
        d["steps"] = r["steps"]
        out.append(d)
    return out


def remove(workflow_id: str) -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM workflow_step WHERE workflow_id=?", (workflow_id,))
    cur = conn.execute("DELETE FROM workflow WHERE id=?", (workflow_id,))
    conn.commit()
    if cur.rowcount:
        try:
            from . import sync
            sync.tombstone(workflow_id, "workflow")
        except Exception:
            pass
    return {"ok": cur.rowcount > 0}


# --------------------------------------------------------------- capturing

def capture(layout_id: str = "", *, name: str = "", ref: str = "") -> dict:
    """Save the workspace as it stands as a workflow.

    Panes become steps in the order the tiles list them, which is left to right
    and top to bottom -- the order you would read them in.
    """
    from . import workspace

    lay = workspace.get_layout(layout_id) if layout_id else workspace.current()
    if not lay:
        return {"ok": False, "error": "there is no workspace to save"}
    panes = lay.get("panes") or []
    if not panes:
        return {"ok": False, "error": "open something first -- an empty "
                                     "workspace is not a workflow"}
    steps = []
    for p in panes:
        # A layout hands back pane dicts, not Pane objects, so read them as
        # dicts -- an attribute access here fails on the very first capture.
        mid = p.get("module_id") or ""
        m = library.get(mid)
        steps.append({
            "kind": "open",
            "module_id": mid,
            "slot": (m.slot if m else ""),
            "cursor": p.get("cursor") or {},
            "link_set": p.get("link_set") or "",
            "text_size": p.get("text_size") or 100,
            "options": p.get("options") or {},
            "note": m.name if m else "",
        })
    start = ref or _ref_of(panes)
    return save({"name": name or f"Workflow: {lay.get('name', 'workspace')}",
                 "note": f"Captured from the {lay.get('name', 'workspace')} "
                         f"layout, {len(steps)} panes.",
                 "ref": start, "layout_id": lay.get("id", "")}, steps)


def _ref_of(panes: list) -> str:
    for p in panes:
        cur = p.get("cursor") or {}
        if cur.get("ref"):
            return cur["ref"]
        key = cur.get("key") or ""
        if key and key.count(".") >= 2:
            return key.replace(".", " ")
    return ""


# ---------------------------------------------------------------- running

def resolve(step: dict, ref: str = "") -> dict:
    """Work out what one step should actually open, at `ref`.

    A step that names a module opens that module.  A step that names a *slot*
    picks the best installed resource for the slot at this passage, which is
    what makes a flow reusable between books: "a commentary" stays a commentary
    when you move from Genesis to Romans.
    """
    out = dict(step)
    out["action"] = "skip"
    if step["kind"] == "search":
        if not step.get("query"):
            out["action"] = "skip"
            return out
        out["action"] = "search"
        return out
    mid = step.get("module_id") or ""
    if not mid and step.get("slot"):
        mid = _best_in_slot(step["slot"], ref)
    if not mid:
        out["reason"] = ("no resource installed for this step"
                         if step.get("slot") else "this step names no resource")
        return out
    if library.get(mid) is None:
        out["reason"] = f"{mid} is no longer installed"
        return out
    out["action"] = "open"
    out["module_id"] = mid
    cursor = dict(step.get("cursor") or {})
    if ref:
        cursor["ref"] = ref
    out["cursor"] = cursor
    return out


def _best_in_slot(slot: str, ref: str) -> str:
    """The highest-priority installed resource that goes in this slot."""
    rows = db.connect().execute(
        "SELECT id, type FROM module WHERE installed_at>0 AND enabled=1 "
        "ORDER BY priority DESC, favorite DESC, name").fetchall()
    for r in rows:
        if placement.slot_for_type(r["type"]).id == slot:
            return r["id"]
    return ""


def run(workflow_id: str, ref: str = "") -> dict:
    """The list of things to open, in order.

    Returned rather than performed: the front end knows about tiles, link sets
    and text sizes, and a step it cannot honour should cost a pane, not the
    whole flow.
    """
    w = get(workflow_id)
    if not w:
        return {"ok": False, "error": "no such workflow"}
    target = ref or w["ref"]
    out: list[dict] = []
    for i, s in enumerate(w["steps"]):
        r = resolve(s, target)
        r["position"] = i
        out.append(r)
    return {"ok": True, "workflow": {"id": w["id"], "name": w["name"],
                                     "note": w["note"]},
            "ref": target, "steps": out,
            "usable": sum(1 for s in out if s["action"] != "skip"),
            "skipped": [s for s in out if s["action"] == "skip"]}


def available_slots() -> list[dict]:
    """The slots a step can ask for by intent rather than by module id."""
    out = []
    for s in placement.SLOTS:
        n = db.connect().execute(
            "SELECT count(*) c FROM module WHERE installed_at>0 AND enabled=1 "
            "AND type IN ({})".format(
                ",".join("?" * len(placement.types_for_slot(s.id)))
                or "''"), placement.types_for_slot(s.id)).fetchone()["c"]
        out.append({"id": s.id, "label": s.label, "glyph": s.glyph,
                    "reader": s.reader, "installed": n})
    return out