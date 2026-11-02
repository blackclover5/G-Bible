"""Sharing what you have made with other readers.

Some platforms share documents, prayer lists and study notes between people in
a proprietary format on a proprietary server.  What is legal and portable here is
the content itself — notes, passage lists, prayer templates, canvases,
clippings — which is the reader's own.  This module packs that content into a
single shareable file (a "group pack") that another G-Bible install can read, and
unpacks one it receives, without any server, account, or third-party service.

Nothing licensed travels in a pack: only user-created records.  Module ids and
unit keys are kept so a shared note still points at the passage it was written
on, but the text of those modules stays on each reader's own device.
"""

from __future__ import annotations

import json
import time
import uuid

from . import db, notes as notes_mod, organise, docs as docs_mod


PACK_SCHEMA = 1


def _collect(note_ids=None, include_passage_lists=True,
             include_prayer_templates=True, include_canvases=True,
             include_clippings=True) -> dict:
    conn = db.connect()
    out_notes = []
    if note_ids:
        for nid in note_ids:
            n = notes_mod.get(nid)
            if n:
                out_notes.append(n)
    else:
        out_notes = notes_mod.listing(limit=100000) or []
    pack = {
        "schema": PACK_SCHEMA,
        "kind": "group-pack",
        "created_at": time.time(),
        "notes": out_notes,
    }
    if include_passage_lists:
        try:
            rows = conn.execute(
                "SELECT id, name, note FROM passage_list").fetchall()
            pack["passage_lists"] = [dict(r) for r in rows]
        except Exception:  # noqa: BLE001
            pack["passage_lists"] = []
    if include_prayer_templates:
        try:
            pack["prayer_templates"] = docs_mod.prayer_templates()
            if isinstance(pack["prayer_templates"], dict):
                pack["prayer_templates"] = pack["prayer_templates"].get("templates", [])
        except Exception:  # noqa: BLE001
            pack["prayer_templates"] = []
    if include_canvases:
        try:
            pack["canvases"] = docs_mod.canvases()
        except Exception:  # noqa: BLE001
            pack["canvases"] = []
    if include_clippings:
        try:
            pack["clippings"] = docs_mod.clippings()
        except Exception:  # noqa: BLE001
            pack["clippings"] = []
    return pack


def export_pack(note_ids=None, name: str = "") -> dict:
    """Build a shareable pack.  Returns the pack dict and a suggested filename."""
    pack = _collect(note_ids=note_ids)
    pack["name"] = (name or "").strip() or "Group pack"
    fname = "group-pack-" + time.strftime("%Y%m%d-%H%M%S") + ".json"
    return {"ok": True, "pack": pack, "filename": fname,
            "counts": {
                "notes": len(pack.get("notes", [])),
                "passage_lists": len(pack.get("passage_lists", [])),
                "prayer_templates": len(pack.get("prayer_templates", [])),
                "canvases": len(pack.get("canvases", [])),
                "clippings": len(pack.get("clippings", [])),
            }}


def import_pack(payload: dict) -> dict:
    """Unpack a received pack.  Notes get fresh ids so nothing is overwritten;
    passage lists, canvases and clippings are appended.  Returns a report."""
    data = payload or {}
    if not isinstance(data, dict):
        return {"ok": False, "error": "not a pack"}
    if data.get("schema") not in (None, PACK_SCHEMA):
        return {"ok": False, "error": "unknown pack schema"}
    report = {"notes": 0, "passage_lists": 0, "canvases": 0,
              "clippings": 0, "prayer_templates": 0, "conflicts": []}
    # Notes: fresh ids, keep content.
    for n in (data.get("notes") or []):
        if not isinstance(n, dict):
            continue
        rec = dict(n)
        rec["id"] = uuid.uuid4().hex[:12]
        # Mark provenance without touching the user's own fields.
        meta = rec.get("meta") or {}
        if isinstance(meta, str):
            try:
                import json as _j
                meta = _j.loads(meta)
            except Exception:  # noqa: BLE001
                meta = {}
        meta = dict(meta or {})
        meta.setdefault("shared_from", data.get("name") or "group pack")
        rec["meta"] = meta
        try:
            notes_mod.save(rec)
            report["notes"] += 1
        except Exception as e:  # noqa: BLE001
            report["conflicts"].append(f"note: {e}")
    # Passage lists: append with fresh ids.
    conn = db.connect()
    for pl in (data.get("passage_lists") or []):
        if not isinstance(pl, dict):
            continue
        pid = "pl" + uuid.uuid4().hex[:10]
        try:
            conn.execute(
                "INSERT INTO passage_list(id,name,note) VALUES(?,?,?)",
                (pid, (pl.get("name") or "Shared list") + " (shared)",
                 pl.get("note") or ""))
            conn.commit()
            report["passage_lists"] += 1
        except Exception as e:  # noqa: BLE001
            report["conflicts"].append(f"passage list: {e}")
    # Canvases: append.
    try:
        existing = docs_mod.canvases()
        for c in (data.get("canvases") or []):
            if not isinstance(c, dict):
                continue
            rec = dict(c)
            rec["id"] = "cv" + uuid.uuid4().hex[:10]
            rec["name"] = (rec.get("name") or "Canvas") + " (shared)"
            existing.append(rec)
            report["canvases"] += 1
        docs_mod.save_canvas if False else None
        db.set_setting("canvases", existing)
    except Exception as e:  # noqa: BLE001
        report["conflicts"].append(f"canvas: {e}")
    # Clippings: append.
    try:
        existing = docs_mod.clippings()
        for c in (data.get("clippings") or []):
            if not isinstance(c, dict):
                continue
            rec = dict(c)
            rec["id"] = "clip" + uuid.uuid4().hex[:10]
            rec["heading"] = (rec.get("heading") or "Clipping") + " (shared)"
            existing.append(rec)
            report["clippings"] += 1
        db.set_setting("clippings", existing)
    except Exception as e:  # noqa: BLE001
        report["conflicts"].append(f"clipping: {e}")
    # Prayer templates: append.
    try:
        existing = docs_mod.prayer_templates()
        if isinstance(existing, dict):
            existing = existing.get("templates", [])
        for t in (data.get("prayer_templates") or []):
            if not isinstance(t, dict):
                continue
            rec = dict(t)
            rec["id"] = "pt" + uuid.uuid4().hex[:10]
            rec["name"] = (rec.get("name") or "Template") + " (shared)"
            existing.append(rec)
            report["prayer_templates"] += 1
        db.set_setting("prayer_templates", existing)
    except Exception as e:  # noqa: BLE001
        report["conflicts"].append(f"prayer template: {e}")
    report["ok"] = True
    return report