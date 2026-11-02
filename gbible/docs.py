"""Documents pack: clippings, quotations, cards, study questions, prayer
templates, plan manager, built-in lectionary selection, sermon helpers,
workflow library, canvas, reminders.

Everything here is assembled from installed content or plain settings — no
cloud, no AI, no invented text. Where some platforms hold proprietary datasets
(sermon outlines, lectionary), this offers the honest local equivalent and says
what it is.
"""

from __future__ import annotations

import time
import uuid

from . import canon, db, library, pptx as _pptx

WPM = 200  # reading-speed estimate for time estimates


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:11]}"


# ---------------------------------------------------------------- clippings

def clippings() -> list[dict]:
    try:
        v = db.get_setting("clippings", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def save_clipping(heading: str, clipping_id: str = "") -> dict:
    all_c = clippings()
    cid = clipping_id or _id("clip")
    rec = next((c for c in all_c if c.get("id") == cid), None)
    if rec is None:
        rec = {"id": cid, "heading": (heading or "").strip() or "Untitled",
               "items": [], "created_at": time.time()}
        all_c.append(rec)
    else:
        rec["heading"] = (heading or "").strip() or rec["heading"]
    db.set_setting("clippings", all_c)
    return {"ok": True, "clipping": rec}


def add_clip_item(clipping_id: str, quote: str, module_id: str = "",
                  ref: str = "", unit_key: str = "") -> dict:
    all_c = clippings()
    rec = next((c for c in all_c if c.get("id") == clipping_id), None)
    if rec is None:
        return {"ok": False, "error": "No such clipping"}
    m = library.get(module_id) if module_id else None
    rec["items"].append({"id": _id("ci"), "quote": quote,
                         "module_id": module_id,
                         "source": m.name if m else "",
                         "ref": ref, "unit_key": unit_key,
                         "added_at": time.time()})
    db.set_setting("clippings", all_c)
    return {"ok": True, "clipping": rec}


def remove_clip_item(clipping_id: str, item_id: str) -> dict:
    all_c = clippings()
    rec = next((c for c in all_c if c.get("id") == clipping_id), None)
    if rec is None:
        return {"ok": False, "error": "No such clipping"}
    rec["items"] = [i for i in rec["items"] if i.get("id") != item_id]
    db.set_setting("clippings", all_c)
    return {"ok": True, "clipping": rec}


def delete_clipping(clipping_id: str) -> dict:
    db.set_setting("clippings",
                   [c for c in clippings() if c.get("id") != clipping_id])
    return {"ok": True, "removed": clipping_id}


def selection_card(quote: str, module_id: str = "", ref: str = "") -> dict:
    """A text-selection card: quote + source + licence, ready to copy or keep."""
    m = library.get(module_id) if module_id else None
    card = {"quote": quote, "source": m.name if m else "", "ref": ref,
            "license": m.license if m else "",
            "rights": m.rights if m else ""}
    return {"ok": True, "card": card}


# ------------------------------------------------------------- quotations

def quotations(term: str, limit: int = 8) -> dict:
    """Short memorable lines from installed books mentioning a term.

    Extractive: units under 300 characters from Book/Devotional modules that
    contain the term. Ranked shorter first — quotability is brevity.
    """
    from . import search as _search
    try:
        opts = _search.SearchOpts(scope="books", limit=100, snippets=False,
                                  smart=False, fast=True)
        res = _search.search(term, opts)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    hits = res.get("hits") or res.get("results") or []
    conn = db.connect()
    out = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        mid, key = h.get("module_id", ""), h.get("key", "")
        r = conn.execute("SELECT text, title, ref_label, m.name, m.type "
                         "FROM unit u JOIN module m ON m.id=u.module_id "
                         "WHERE u.module_id=? AND u.key=?", (mid, key)).fetchone()
        if r is None or r["type"] not in ("Book", "Devotional"):
            continue
        text = (r["text"] or "").strip()
        if not text or len(text) > 300:
            continue
        out.append({"quote": text, "source": r["name"], "title": r["title"],
                    "ref": r["ref_label"], "module_id": mid, "key": key})
        if len(out) >= limit:
            break
    return {"ok": True, "term": term, "items": out,
            "note": "Lines from installed books — not a quotation database."}


# ---------------------------------------------------------- study questions

def study_questions(ref: str) -> dict:
    """Extractive study questions for a passage: observation / interpretation /
    application prompts built from the text's own headings and names.

    Templates, not generated prose: every question names what it came from.
    """
    from . import study
    f = next(iter(canon.parse_ref(ref).refs()), None) \
        if canon.parse_ref(ref) else None
    if f is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    conn = db.connect()
    heads = conn.execute(
        "SELECT title FROM unit WHERE book=? AND chapter=? AND title<>'' "
        "LIMIT 5", (f.book, f.chapter or 0)).fetchone()
    head = (heads["title"] if heads else "")
    try:
        names = [n.get("word") or n.get("name") or ""
                 for n in (study.fact_tags(
                     f"{f.book} {f.chapter}:{f.verse or 1}", limit=6) or [])]
    except Exception:  # noqa: BLE001
        names = []
    names = [n for n in names if n][:4]
    nomin = f"{f.book} {f.chapter}" + (f":{f.verse}" if f.verse else "")
    qs = [
        {"q": f"What happens in {nomin} — who acts, and what changes?",
         "from": "observation of the passage",
         "kind": "observe"},
        {"q": f"Which words are repeated in {nomin}, and what do they stress?",
         "from": "observation of the passage",
         "kind": "observe"},
    ]
    if head:
        qs.append({"q": f"The heading reads {head!r} — does the passage earn it?",
                   "from": "section heading", "kind": "interpret"})
    for n in names:
        qs.append({"q": f"What does {n} do here, and why does it matter?",
                   "from": "name in the passage", "kind": "interpret"})
    qs += [
        {"q": "Which other passage says the same thing most nearly?",
         "from": "cross-references", "kind": "interpret"},
        {"q": "What would obeying this passage change this week?",
         "from": "application template", "kind": "apply"},
    ]
    return {"ok": True, "ref": ref, "questions": qs}


# ------------------------------------------------------ prayer templates

def prayer_templates() -> list[dict]:
    try:
        v = db.get_setting("prayer_templates", [])
    except Exception:  # noqa: BLE001
        return []
    if v:
        return v if isinstance(v, list) else []
    return [
        {"id": "pt-daily", "name": "Daily", "body": "",
         "frequency_days": 1},
        {"id": "pt-weekly", "name": "Weekly", "body": "",
         "frequency_days": 7},
    ]


def save_prayer_template(name: str, body: str = "", frequency_days: int = 1,
                         tid: str = "") -> dict:
    try:
        all_t = db.get_setting("prayer_templates", prayer_templates())
    except Exception:  # noqa: BLE001
        all_t = []
    if not isinstance(all_t, list):
        all_t = []
    tid = tid or _id("pt")
    rec = {"id": tid, "name": (name or "").strip() or "Untitled",
           "body": body or "", "frequency_days": max(0, int(frequency_days or 1))}
    all_t = [t for t in all_t if t.get("id") != tid] + [rec]
    db.set_setting("prayer_templates", all_t)
    return {"ok": True, "template": rec}


def delete_prayer_template(tid: str) -> dict:
    try:
        all_t = db.get_setting("prayer_templates", [])
    except Exception:  # noqa: BLE001
        all_t = []
    if not isinstance(all_t, list):
        all_t = []
    all_t = [t for t in all_t if t.get("id") != tid]
    db.set_setting("prayer_templates", all_t)
    return {"ok": True}


def prayer_due() -> dict:
    """Prayer notes with next-due dates from their template frequency."""
    from . import notes as _notes
    try:
        items = _notes.listing(kind="prayer") or []
    except Exception:  # noqa: BLE001
        items = []
    tmpl = {t["id"]: t for t in prayer_templates()}
    now = time.time()
    out = []
    for n in items:
        d = dict(n) if not isinstance(n, dict) else n
        meta = d.get("meta") or {}
        if isinstance(meta, str):
            try:
                import json as _j
                meta = _j.loads(meta)
            except Exception:  # noqa: BLE001
                meta = {}
        t = tmpl.get(meta.get("template", ""), {})
        freq = (meta.get("frequency_days") or t.get("frequency_days") or 1)
        last = d.get("updated_at") or d.get("created_at") or now
        due = last + freq * 86400
        out.append({**d, "frequency_days": freq, "due_at": due,
                    "overdue": due <= now})
    out.sort(key=lambda x: x["due_at"])
    return {"ok": True, "items": out}


# ------------------------------------------------------------ plan manager

def plan_manager() -> dict:
    """All plans grouped: Today (due) / Anytime (self-paced) / Later /
    Archived, with time estimates. Self-paced vs scheduled comes from the
    plan's stored pace; archived from the archived list."""
    from . import readingplan as _rp
    try:
        archived = db.get_setting("plans_archived", [])
        paces = db.get_setting("plan_paces", {})
    except Exception:  # noqa: BLE001
        archived, paces = [], {}
    if not isinstance(archived, list):
        archived = []
    if not isinstance(paces, dict):
        paces = {}
    groups = {"today": [], "anytime": [], "later": [], "archived": []}
    for p in _rp.plans():
        pid = p["id"]
        if pid in archived:
            groups["archived"].append(p)
            continue
        pace = (paces.get(pid) or "")
        if pace in ("open", "anytime"):
            groups["anytime"].append({**p, "pace": pace})
            continue
        try:
            d = _rp.day(pid, 0)
            nxt = d.get("day") if d.get("ok") else None
        except Exception:  # noqa: BLE001
            nxt = None
        est = estimate_day(pid, nxt) if nxt else {}
        entry = {**p, "next_day": nxt,
                 "minutes": (est.get("minutes") if est.get("ok") else None)}
        (groups["today"] if nxt else groups["later"]).append(entry)
    return {"ok": True, "groups": groups}


def set_plan_pace(plan_id: str, pace: str) -> dict:
    """Pace: a goal like '15min', 'finish:2026-12-31', 'open', or '' scheduled."""
    try:
        paces = db.get_setting("plan_paces", {})
    except Exception:  # noqa: BLE001
        paces = {}
    if not isinstance(paces, dict):
        paces = {}
    if pace:
        paces[plan_id] = pace
    elif plan_id in paces:
        del paces[plan_id]
    db.set_setting("plan_paces", paces)
    return {"ok": True, "plan": plan_id, "pace": pace}


def set_plan_archived(plan_id: str, archived: bool = True) -> dict:
    try:
        lst = db.get_setting("plans_archived", [])
    except Exception:  # noqa: BLE001
        lst = []
    if not isinstance(lst, list):
        lst = []
    if archived and plan_id not in lst:
        lst.append(plan_id)
    if not archived and plan_id in lst:
        lst.remove(plan_id)
    db.set_setting("plans_archived", lst)
    return {"ok": True, "plan": plan_id, "archived": bool(archived)}


def estimate_day(plan_id: str, n: int = 0) -> dict:
    """Minutes for a plan day at 200 wpm, counted off installed Bible text."""
    from . import readingplan as _rp
    try:
        d = _rp.day(plan_id, n)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not d.get("ok"):
        return {"ok": False, "error": d.get("error", "no such day")}
    bibles = [m for m in library.list_all() if m.is_bible]
    if not bibles:
        return {"ok": False, "error": "No Bible installed"}
    mid = bibles[0].id
    conn = db.connect()
    words = 0
    for ref in d.get("passages") or []:
        rr = canon.parse_ref(ref, bibles[0].v11n)
        if rr is None:
            continue
        for r in rr.refs():
            row = conn.execute("SELECT text FROM unit WHERE module_id=? "
                               "AND key=?", (mid, r.osis_id())).fetchone()
            if row and row["text"]:
                words += len(row["text"].split())
    # Devotional days carry their own text instead of passages.
    if not words and d.get("text"):
        words = len(d["text"].split())
    minutes = max(1, round(words / WPM)) if words else None
    return {"ok": True, "plan": plan_id, "day": d.get("day"),
            "words": words, "minutes": minutes}


def skip_to_latest(plan_id: str) -> dict:
    """Jump to the first unread day, marking skipped days read without
    counting them as studied: they are checked off, matching the Skip feature.
    """
    from . import readingplan as _rp
    try:
        d = _rp.day(plan_id, 0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not d.get("ok"):
        return {"ok": False, "error": d.get("error", "no such plan")}
    n = d.get("day") or 1
    for i in range(1, n):
        try:
            _rp.set_progress(plan_id, i, True)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "plan": plan_id, "day": n, "skipped": n - 1}


def export_plans() -> dict:
    from . import readingplan as _rp
    try:
        prog = _rp.progress()
        paces = db.get_setting("plan_paces", {})
    except Exception:  # noqa: BLE001
        prog, paces = {}, {}
    return {"ok": True, "progress": prog, "paces": paces if isinstance(paces, dict) else {}}


def import_plans(payload: dict) -> dict:
    from . import readingplan as _rp
    data = dict(payload or {})
    prog = data.get("progress") if isinstance(data.get("progress"), dict) else {}
    paces = data.get("paces") if isinstance(data.get("paces"), dict) else {}
    cur = _rp.progress()
    cur.update(prog)
    db.set_setting(_rp.PROGRESS_KEY, cur)
    try:
        old = db.get_setting("plan_paces", {})
    except Exception:  # noqa: BLE001
        old = {}
    if not isinstance(old, dict):
        old = {}
    old.update(paces)
    db.set_setting("plan_paces", old)
    return {"ok": True, "plans": len(prog)}


# -------------------------------------------------- built-in lectionary

# A simple 52-week selection of key passages — labelled as such, never as
# the Revised Common Lectionary, which is copyrighted.
BUILTIN_LECTIONARY = [
    "Gen 1:1-2:3", "Gen 12:1-9", "Gen 22:1-19", "Exod 3:1-15", "Exod 12:1-14",
    "Exod 20:1-17", "Deut 6:4-9", "Josh 1:1-9", "Ruth 1:6-22", "1 Sam 3:1-18",
    "2 Sam 7:1-17", "1 Kgs 3:3-14", "Ps 1", "Ps 8", "Ps 19", "Ps 23",
    "Ps 42", "Ps 51", "Ps 90", "Ps 103", "Ps 121", "Ps 139", "Prov 3:1-12",
    "Eccl 3:1-8", "Isa 6:1-8", "Isa 9:2-7", "Isa 40:1-11", "Isa 53",
    "Jer 1:4-10", "Mic 6:6-8", "Hab 3:17-19", "Mal 3:1-4", "Matt 5:1-12",
    "Matt 6:5-13", "Matt 28:16-20", "Mark 1:1-8", "Mark 12:28-34",
    "Luke 1:26-38", "Luke 2:1-20", "Luke 15:11-32", "John 1:1-14",
    "John 3:1-17", "John 14:1-7", "Acts 2:1-13", "Rom 8:1-11", "1 Cor 13",
    "Gal 5:16-25", "Eph 2:1-10", "Phil 2:5-11", "Heb 11:1-12", "Rev 21:1-7",
    "Ps 150",
]


def builtin_lectionary() -> dict:
    return {"ok": True, "weeks": len(BUILTIN_LECTIONARY),
            "readings": [{"week": i + 1, "ref": r}
                         for i, r in enumerate(BUILTIN_LECTIONARY)],
            "note": "A simple built-in selection of key passages — not the "
                    "Revised Common Lectionary."}


# ---------------------------------------------------------------- sermon

def sermon_outline(note_id: str) -> dict:
    from . import notes as _notes
    n = _notes.get(note_id)
    if not n:
        return {"ok": False, "error": "No such note"}
    meta = n.get("meta") or {}
    if isinstance(meta, str):
        try:
            import json as _j
            meta = _j.loads(meta)
        except Exception:  # noqa: BLE001
            meta = {}
    return {"ok": True, "id": note_id,
            "outline": meta.get("outline") or []}


def sermon_save_outline(note_id: str, outline: list) -> dict:
    from . import notes as _notes
    n = _notes.get(note_id)
    if not n:
        return {"ok": False, "error": "No such note"}
    meta = n.get("meta") or {}
    if isinstance(meta, str):
        try:
            import json as _j
            meta = _j.loads(meta)
        except Exception:  # noqa: BLE001
            meta = {}
    meta["outline"] = [str(s) for s in (outline or [])]
    _notes.save({"id": note_id, "meta": meta})
    return {"ok": True, "id": note_id, "outline": meta["outline"]}


def sermon_calendar() -> dict:
    try:
        v = db.get_setting("sermon_calendar", {})
    except Exception:  # noqa: BLE001
        return {}
    return v if isinstance(v, dict) else {}


def sermon_schedule(date: str, note_id: str = "") -> dict:
    cal = sermon_calendar()
    if note_id:
        cal[date] = note_id
    elif date in cal:
        del cal[date]
    db.set_setting("sermon_calendar", cal)
    return {"ok": True, "calendar": cal}


def sermon_markers(ref: str) -> dict:
    """Sermon and Bible-study notes whose own text names this passage.

    Some platforms surface these as markers beside the passage.  A note qualifies when
    its title, body or recorded reference mentions the passage, so a sermon
    prepared on John 3:16 is found at John 3:16 even if it was never anchored
    to a verse.
    """
    from . import notes as _notes
    sermons, studies = [], []
    try:
        items = _notes.listing() or []
    except Exception:  # noqa: BLE001
        items = []
    for n in items:
        d = dict(n) if not isinstance(n, dict) else n
        kind = d.get("kind") or "note"
        if kind not in ("sermon", "note"):
            continue
        blob = " ".join(str(d.get(k) or "") for k in ("title", "body", "ref_label"))
        if not (ref and ref.lower() in blob.lower()):
            continue
        item = {"id": d.get("id"), "title": d.get("title") or "(untitled)",
                "kind": kind,
                "preview": (d.get("body") or "")[:180]}
        if kind == "sermon":
            sermons.append(item)
        else:
            studies.append(item)
    return {"ok": True, "ref": ref, "sermons": sermons, "studies": studies}


# --------------------------------------------------- sermon builder & manager

def _sermon_meta(note: dict) -> dict:
    """Extract the sermon meta fields, tolerating string-encoded JSON."""
    meta = note.get("meta") or {}
    if isinstance(meta, str):
        try:
            import json as _j
            meta = _j.loads(meta)
        except Exception:  # noqa: BLE001
            meta = {}
    return meta


def sermon_builder_get(note_id: str) -> dict:
    """The full structure of a sermon note: outline, introduction, points,
    illustrations, conclusion and delivery notes."""
    from . import notes as _notes
    n = _notes.get(note_id)
    if not n:
        return {"ok": False, "error": "No such sermon note"}
    meta = _sermon_meta(n)
    return {"ok": True, "id": note_id,
            "title": n.get("title") or "",
            "ref_label": n.get("ref_label") or "",
            "body": n.get("body") or "",
            "outline": meta.get("outline") or [],
            "introduction": meta.get("introduction") or "",
            "points": meta.get("points") or [],
            "illustrations": meta.get("illustrations") or [],
            "conclusion": meta.get("conclusion") or "",
            "delivery": meta.get("delivery") or "",
            "series": meta.get("series") or "",
            "scheduled": meta.get("scheduled") or "",
            "tags": n.get("tags") or [],
            "meta": meta}


def sermon_builder_save(note_id: str, structure: dict) -> dict:
    """Save the full structure of a sermon note.

    Only the sermon-specific fields are updated; the note's title, body and
    tags are left alone so the note list and sync are not disturbed.
    """
    from . import notes as _notes
    n = _notes.get(note_id)
    if not n:
        return {"ok": False, "error": "No such sermon note"}
    meta = _sermon_meta(n)
    for field in ("introduction", "points", "illustrations", "conclusion",
                  "delivery", "series", "scheduled"):
        val = structure.get(field, "")
        if isinstance(val, list):
            meta[field] = [str(s) for s in val if str(s).strip()]
        elif isinstance(val, str):
            meta[field] = val.strip()
    if isinstance(structure.get("outline"), list):
        meta["outline"] = [str(s) for s in structure["outline"] if str(s).strip()]
    _notes.save({"id": note_id, "meta": meta})
    return {"ok": True, "id": note_id, "saved": True}


def sermon_import(text: str, title: str = "", series: str = "") -> dict:
    """Create a sermon note from imported text.

    The first non-empty line becomes the title (unless one is given); the rest
    becomes the body.  Nothing is parsed into outline/points -- the imported
    text is kept verbatim so a sermon written elsewhere arrives intact, and the
    reader can structure it in the Sermon Builder afterwards.
    """
    from . import notes as _notes
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "no text to import"}
    lines = [ln for ln in text.splitlines()]
    if not title:
        # first non-empty line
        for ln in lines:
            if ln.strip():
                title = ln.strip()
                break
        if not title:
            title = "Imported sermon"
    # body = everything after the first non-empty line
    body_lines = []
    seen = False
    for ln in lines:
        if not seen and ln.strip() == title:
            seen = True
            continue
        body_lines.append(ln)
    body = "\\n".join(body_lines).strip()
    # If the whole text was one line, keep it as body too.
    if not body:
        body = text
    meta = {}
    if series:
        meta["series"] = series
    rec = _notes.save({"kind": "sermon", "title": title, "body": body,
                       "meta": meta})
    return {"ok": True, "id": rec.get("id"), "title": title}


def sermon_manager() -> dict:
    """All sermon notes, with their status, series and schedule.

    A sermon is *scheduled* when it has a date in the calendar, *draft* when it
    has content but no date, and *empty* when it has neither.  Series are
    collected from the notes' own series field.
    """
    from . import notes as _notes
    try:
        items = _notes.listing(kind="sermon") or []
    except Exception:  # noqa: BLE001
        items = []
    cal = sermon_calendar()
    # Invert the calendar: note_id -> date.
    date_of = {}
    for d, nid in cal.items():
        if nid:
            date_of[nid] = d
    series_set: set[str] = set()
    rows = []
    for n in items:
        d = dict(n) if not isinstance(n, dict) else n
        meta = _sermon_meta(d)
        series = meta.get("series") or ""
        if series:
            series_set.add(series)
        nid = d.get("id") or ""
        scheduled = date_of.get(nid, "")
        # A sermon built in the Sermon Builder keeps its content in `meta`, not
        # in `body` -- the body is only filled by the outline finder.  Judging
        # "has content" by the body alone therefore reported every builder-made
        # sermon as empty while listing its points in the same row.
        has_content = bool(
            (d.get("body") or "").strip()
            or (meta.get("outline") or [])
            or (meta.get("points") or [])
            or (meta.get("introduction") or "").strip()
            or (meta.get("conclusion") or "").strip()
            or (meta.get("delivery") or "").strip()
            or (meta.get("illustrations") or []))
        status = "scheduled" if scheduled else ("draft" if has_content else "empty")
        rows.append({
            "id": nid,
            "title": d.get("title") or "Untitled",
            "ref_label": d.get("ref_label") or "",
            "series": series,
            "scheduled": scheduled,
            "status": status,
            "outline_count": len(meta.get("outline") or []),
            "points_count": len(meta.get("points") or []),
            "tags": d.get("tags") or [],
            "updated_at": d.get("updated_at") or 0,
        })
    rows.sort(key=lambda r: (r["scheduled"] or "9999", r["title"]))
    return {"ok": True, "sermons": rows,
            "series": sorted(series_set),
            "counts": {
                "total": len(rows),
                "scheduled": sum(1 for r in rows if r["status"] == "scheduled"),
                "draft": sum(1 for r in rows if r["status"] == "draft"),
                "empty": sum(1 for r in rows if r["status"] == "empty"),
            }}


# -------------------------------------------------------- workflow library

WORKFLOW_LIBRARY = [
    {"name": "Basic Bible Study",
     "note": "Read, observe, interpret, apply — five steps.",
     "steps": [
         {"kind": "open", "slot": "bible", "note": "1. Read the passage twice."},
         {"kind": "search", "query": "", "note": "2. List what repeats."},
         {"kind": "open", "slot": "commentary",
          "note": "3. Check one commentary."},
         {"kind": "outline", "note": "4. Outline the passage."},
         {"kind": "open", "slot": "notes",
          "note": "5. Write one application."}]},
    {"name": "Inductive Study",
     "note": "Observation, interpretation, application.",
     "steps": [
         {"kind": "open", "slot": "bible", "note": "1. Observe: who, what, where."},
         {"kind": "clause", "note": "2. Find the verbs and their subjects."},
         {"kind": "word", "note": "3. Study the key word."},
         {"kind": "open", "slot": "commentary",
          "note": "4. Compare with a commentary."},
         {"kind": "open", "slot": "notes", "note": "5. Apply."}]},
    {"name": "Word Study",
     "note": "From a word to its uses.",
     "steps": [
         {"kind": "word", "note": "1. Look up the Strong's number."},
         {"kind": "open", "slot": "lexicon", "note": "2. Read every lexicon."},
         {"kind": "search", "query": "", "note": "3. Survey occurrences."},
         {"kind": "open", "slot": "notes", "note": "4. Summarise the sense."}]},
    {"name": "Devotional Reading",
     "note": "Slow reading for the day.",
     "steps": [
         {"kind": "open", "slot": "devotional", "note": "1. Read today's entry."},
         {"kind": "open", "slot": "bible", "note": "2. Read its passage."},
         {"kind": "open", "slot": "notes", "note": "3. Journal one line."}]},
    {"name": "Sermon Preparation",
     "note": "From text to outline.",
     "steps": [
         {"kind": "open", "slot": "bible", "note": "1. Read and re-read."},
         {"kind": "outline", "note": "2. Structure the text."},
         {"kind": "open", "slot": "commentary",
          "note": "3. Consult commentaries."},
         {"kind": "search", "query": "", "note": "4. Gather cross-references."},
         {"kind": "open", "slot": "notes",
          "note": "5. Draft the outline."}]},
]


def workflow_library() -> dict:
    return {"ok": True, "workflows": WORKFLOW_LIBRARY}


def workflow_install(name: str) -> dict:
    from . import workflow as _wf
    tpl = next((w for w in WORKFLOW_LIBRARY if w["name"] == name), None)
    if tpl is None:
        return {"ok": False, "error": f"Unknown workflow {name!r}"}
    return _wf.save({"name": tpl["name"], "note": tpl["note"]},
                    tpl["steps"])


# ---------------------------------------------------------------- canvas

def canvases() -> list[dict]:
    try:
        v = db.get_setting("canvases", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def save_canvas(name: str, elements: list | None = None,
                canvas_id: str = "") -> dict:
    all_c = canvases()
    cid = canvas_id or _id("cv")
    rec = next((c for c in all_c if c.get("id") == cid), None)
    if rec is None:
        rec = {"id": cid, "name": (name or "").strip() or "Untitled",
               "elements": [], "updated_at": time.time()}
        all_c.append(rec)
    else:
        if name:
            rec["name"] = name
    if elements is not None:
        rec["elements"] = elements
    rec["updated_at"] = time.time()
    db.set_setting("canvases", all_c)
    return {"ok": True, "canvas": rec}


def delete_canvas(canvas_id: str) -> dict:
    db.set_setting("canvases",
                   [c for c in canvases() if c.get("id") != canvas_id])
    return {"ok": True, "removed": canvas_id}


# --------------------------------------------------------------- reminders

def reminders() -> dict:
    """Due badges: unread plan days + overdue prayers, in one place."""
    from . import readingplan as _rp
    plans_due = []
    try:
        mgr = plan_manager()
        plans_due = mgr.get("groups", {}).get("today", [])
    except Exception:  # noqa: BLE001
        plans_due = []
    try:
        prayers = [p for p in prayer_due().get("items", []) if p.get("overdue")]
    except Exception:  # noqa: BLE001
        prayers = []
    return {"ok": True,
            "plans_due": [{"id": p.get("id"), "title": p.get("title"),
                           "next_day": p.get("next_day")}
                          for p in plans_due],
            "prayers_due": [{"id": p.get("id"), "title": p.get("title")}
                            for p in prayers]}


# ---------------------------------------------------------------- flashcards
# Drill over your own lists: the front names the place, the back shows the
# text. State is one small setting so a session survives a restart.

def flash_start(source: str, source_id: str, limit: int = 200) -> dict:
    cards = []
    title = ""
    if source == "wordlist":
        from . import wordlist as _wl
        try:
            res = _wl.occurrences(source_id, limit=min(limit, 2000))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "no such list")}
        title = (res.get("list") or {}).get("name", "")
        seen = set()
        for it in (res.get("pinned") or []) + (res.get("items") or []):
            key = (it.get("module_id"), it.get("unit_key"))
            if key in seen:
                continue
            seen.add(key)
            back = (it.get("snippet") or it.get("surface")
                    or it.get("text") or "").strip()
            if it.get("gloss"):
                back += f"\n— {it['gloss']}"
            cards.append({"front": it.get("ref_label") or it.get("term") or "?",
                          "back": back or "(open to read)",
                          "module_id": it.get("module_id") or "",
                          "unit_key": it.get("unit_key") or ""})
            if len(cards) >= limit:
                break
    elif source == "passage":
        from . import organise as _org
        items = _org.passage_items(source_id)
        if not items:
            return {"ok": False, "error": "That list is empty"}
        conn = db.connect()
        for it in items[:limit]:
            text, mid = "", it.get("module_id") or ""
            if mid:
                r = conn.execute("SELECT text FROM unit WHERE module_id=? "
                                 "AND key=?", (mid, it.get("unit_key"))).fetchone()
                if r:
                    text = (r["text"] or "").strip()
            cards.append({"front": it.get("ref_label") or it.get("unit_key"),
                          "back": text or "(open to read)",
                          "module_id": mid,
                          "unit_key": it.get("unit_key") or ""})
        lists = {l["id"]: l for l in _org.passage_lists()}
        title = lists.get(source_id, {}).get("name", "")
    else:
        return {"ok": False, "error": "Flashcards need a word list or passage list"}
    if not cards:
        return {"ok": False, "error": "Nothing to drill on"}
    sess = {"source": source, "source_id": source_id, "title": title,
            "cards": cards, "pos": 0, "known": [], "unknown": []}
    db.set_setting("flash_session", sess)
    return {"ok": True, "total": len(cards), "title": title}


def flash_state() -> dict:
    try:
        sess = db.get_setting("flash_session", None)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "No session"}
    if not sess or not sess.get("cards"):
        return {"ok": False, "error": "No session — start one first"}
    pos = min(sess.get("pos", 0), len(sess["cards"]) - 1)
    card = sess["cards"][pos]
    return {"ok": True, "title": sess.get("title", ""), "pos": pos,
            "total": len(sess["cards"]), "card": card,
            "known": len(sess.get("known", [])),
            "unknown": len(sess.get("unknown", [])),
            "done": pos >= len(sess["cards"]) - 1
                    and (len(sess.get("known", [])) + len(sess.get("unknown", []))
                         >= len(sess["cards"]))}


def flash_score(known: bool) -> dict:
    try:
        sess = db.get_setting("flash_session", None)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "No session"}
    if not sess or not sess.get("cards"):
        return {"ok": False, "error": "No session"}
    pos = min(sess.get("pos", 0), len(sess["cards"]) - 1)
    (sess["known"] if known else sess["unknown"]).append(pos)
    sess["pos"] = min(pos + 1, len(sess["cards"]) - 1)
    # Stepping past the last card ends the round; stay on it, marked done.
    if pos >= len(sess["cards"]) - 1:
        sess["pos"] = len(sess["cards"]) - 1
    db.set_setting("flash_session", sess)
    return flash_state()


# --------------------------------------------------------------------------
# Pack 6: reader editions, pronunciation guide, outline export, ribbons.
# --------------------------------------------------------------------------

READER_EDITIONS = {
    "study": {"show_strongs": False, "show_notes": True, "show_headings": True,
              "show_red": True, "show_xrefs": True, "verse_per_line": False,
              "about": "Full study text with notes, headings and references."},
    "clean": {"show_strongs": False, "show_notes": False, "show_headings": False,
              "show_red": False, "show_xrefs": False, "verse_per_line": False,
              "about": "Reader's edition: running text, no verse numbers, "
                       "footnotes, headings or cross-references."},
}


def reader_editions() -> dict:
    return {"ok": True, "editions": READER_EDITIONS}


_GREEK_SOUND = {
    "α": "a as in father", "β": "b", "γ": "g (n before κ γ χ)",
    "δ": "d", "ε": "e as in met", "ζ": "dz", "η": "ay as in obey",
    "θ": "th as in thin", "ι": "i as in machine", "κ": "k",
    "λ": "l", "μ": "m", "ν": "n", "ξ": "x as in axe", "ο": "o as in obey",
    "π": "p", "ρ": "r (rolled)", "σ": "s", "ς": "s (final)", "τ": "t",
    "υ": "u as in lute", "φ": "ph as in phone", "χ": "ch as in loch",
    "ψ": "ps", "ω": "o as in tone",
}

_HEBREW_SOUND = {
    "א": "aleph — silent", "ב": "bet — b/v", "ג": "gimel — g",
    "ד": "dalet — d", "ה": "he — h", "ו": "vav — v/o/u", "ז": "zayin — z",
    "ח": "het — throaty ch", "ט": "tet — t", "י": "yod — y/i",
    "כ": "kaf — k/kh", "ך": "kaf final — kh", "ל": "lamed — l",
    "מ": "mem — m", "ם": "mem final — m", "נ": "nun — n", "ן": "nun final — n",
    "ס": "samekh — s", "ע": "ayin — silent/deep", "פ": "pe — p/f",
    "ף": "pe final — f", "צ": "tsade — ts", "ץ": "tsade final — ts",
    "ק": "qof — q", "ר": "resh — r", "ש": "shin/sin — sh/s", "ת": "tav — t",
}


def pronounce_guide(word: str) -> dict:
    """Letter-by-letter pronunciation guide plus transliteration.

    Erasmian Greek and simple Modern-Sephardic-flavoured Hebrew — a reading
    aid, not a historical claim; the panel says which convention it follows.
    """
    import unicodedata as _u
    from . import study as _study
    w = (word or "").strip()
    if not w:
        return {"ok": False, "error": "No word given"}
    is_greek = any("\u0370" <= c <= "\u03ff" or "\u1f00" <= c <= "\u1fff"
                   for c in w)
    is_hebrew = any("\u0590" <= c <= "\u05ff" for c in w)
    if not (is_greek or is_hebrew):
        return {"ok": False,
                "error": "Neither Greek nor Hebrew — nothing to sound out"}
    table = _GREEK_SOUND if is_greek else _HEBREW_SOUND
    letters = []
    for c in _u.normalize("NFD", w):
        if _u.combining(c):
            continue
        base = _u.normalize("NFC", c).lower()
        sound = table.get(base, table.get(base.upper(), ""))
        letters.append({"letter": c, "sound": sound or "—"})
    try:
        trans = _study.pronounce(w) if hasattr(_study, "pronounce") else {}
    except Exception:  # noqa: BLE001
        trans = {}
    convention = ("Erasmian Greek — the classroom convention, not a claim "
                  "about Koine speech." if is_greek else
                  "Letter names with simple sounds — pointed vowels are not "
                  "reconstructed.")
    return {"ok": True, "word": w,
            "script": "greek" if is_greek else "hebrew",
            "transliteration": (trans.get("transliteration")
                                if isinstance(trans, dict) else ""),
            "letters": letters, "convention": convention}


def export_outline_doc(ref: str) -> dict:
    """Outline for a chapter or book as an HTML document.

    Word, Pages, LibreOffice and PowerPoint all open HTML — so one honest
    HTML file is the Word/PowerPoint export, with no proprietary writer.
    """
    from . import outline as _outline
    from . import publish as _publish
    f = next(iter(canon.parse_ref(ref).refs()), None) \
        if canon.parse_ref(ref) else None
    if f is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    data = _outline.chapter(f.book, f.chapter or 0) \
        if f.chapter else _outline.book_outline(f.book)
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error", "no outline here")}
    heads = data.get("headings") or data.get("chapters") or []
    lines = []
    for h in heads:
        if isinstance(h, dict):
            t = h.get("title") or h.get("head") or ""
            r = h.get("ref") or h.get("osis") or ""
            lines.append(f"<h3>{r} — {t}</h3>" if r else f"<h3>{t}</h3>")
        else:
            lines.append(f"<p>{h}</p>")
    body = (f"<h1>Outline: {ref}</h1>"
            f"<p><em>Source: {data.get('source', '')} — "
            f"{data.get('attribution', '')}</em></p>") + "\n".join(lines)
    page = _publish._html_page(f"Outline: {ref}", body,
                               _publish.attribution_block([]))
    fname = f"outline-{ref.replace(' ', '-').replace(':', '-')}.html"
    return {"ok": True, "filename": fname, "html": page,
            "note": "HTML opens in Word, Pages, LibreOffice and PowerPoint."}


def reading_ribbons(book: str, chapter: int) -> dict:
    """Plan days covering one chapter — the margin-ribbon data.

    Scans plan overviews for days whose reference resolves to this chapter.
    Honest about cost: overviews are small (hundreds of rows), so this is a
    single request, not per-verse.
    """
    from . import readingplan as _rp
    ribbons = []
    b = canon.lookup_book((book or "").strip())
    osis = b.osis if b else (book or "").strip()
    try:
        plans = _rp.plans()
    except Exception:  # noqa: BLE001
        return {"ok": True, "ribbons": []}
    for p in plans:
        pid = p.get("id", "")
        try:
            ov = _rp.overview(pid)
        except Exception:  # noqa: BLE001
            continue
        for it in ov.get("items") or []:
            for cand in (it.get("ref") or "", it.get("title") or ""):
                rr = canon.parse_ref(cand)
                if rr is None:
                    continue
                f = next(iter(rr.refs()), None)
                if f is not None and f.book == osis and (f.chapter or 0) == chapter:
                    ribbons.append({"plan": pid, "title": p.get("title"),
                                    "day": it.get("n"), "ref": cand})
                    break
    return {"ok": True, "book": book, "chapter": chapter, "ribbons": ribbons}


def sermon_export(note_id: str, kind: str = "slides") -> dict:
    """A sermon note as slides (one point per section) or a handout (outline
    with room to write). Plain HTML: Word, PowerPoint and browsers all open
    it, so this is the slides/handout export with no proprietary writer."""
    from . import notes as _notes
    from . import publish as _pub
    import html as _h
    n = _notes.get(note_id)
    if not n:
        return {"ok": False, "error": "No such note"}
    meta = n.get("meta") or {}
    if isinstance(meta, str):
        try:
            import json as _j
            meta = _j.loads(meta)
        except Exception:  # noqa: BLE001
            meta = {}
    outline = meta.get("outline") or []
    title = n.get("title") or "Sermon"
    body = (n.get("body") or "").strip()
    if kind == "pptx":
        pr = _pptx.Presentation(title=title, author="G-Bible")
        pr.add_slide(title, [n.get("ref_label")] if n.get("ref_label") else [])
        for s in outline or ["(no outline points yet)"]:
            pr.add_slide(s, [])
        if body:
            pr.add_slide("Notes", [body])
        data = pr.build(attribution="Your own sermon notes.")
        fname = f"sermon-{note_id}-pptx.pptx"
        return {"ok": True, "filename": fname, "binary": data,
                "bytes": len(data), "kind": "pptx"}
    if kind == "handout":
        parts = [f"<h1>{_h.escape(title)}</h1>"]
        if n.get("ref_label"):
            parts.append(f"<p><em>{_h.escape(n['ref_label'])}</em></p>")
        parts.append("<h2>Outline</h2><ol>")
        parts += [f"<li>{_h.escape(s)}<br><br>___</li>" for s in outline]
        parts.append("</ol>")
        if body:
            parts.append(f"<h2>Notes</h2><p>{_h.escape(body)}</p>")
    else:
        kind = "slides"
        parts = [f"<h1>{_h.escape(title)}</h1>"]
        if n.get("ref_label"):
            parts.append(f"<p><em>{_h.escape(n['ref_label'])}</em></p>")
        for s in outline or ["(no outline points yet)"]:
            parts.append(f"<section><h2>{_h.escape(s)}</h2></section>")
        if body:
            parts.append(f"<section><h2>Notes</h2><p>{_h.escape(body)}</p></section>")
    page = _pub._html_page(f"{title} ({kind})", "\n".join(parts),
                           _pub.attribution_block([]))
    fname = f"sermon-{note_id}-{kind}.html"
    return {"ok": True, "filename": fname, "html": page, "kind": kind}


# ------------------------------------------------------- highlight palettes
# Named color sets for highlighting. Colors themselves are the five the
# reader knows how to paint; a palette chooses a subset and a default.

PALETTE_COLORS = ["yellow", "green", "blue", "pink", "orange"]


def highlight_palettes() -> dict:
    try:
        pals = db.get_setting("highlight_palettes", [])
        active = db.get_setting("highlight_palette_active", "")
    except Exception:  # noqa: BLE001
        return {"palettes": [], "active": "", "colors": PALETTE_COLORS}
    if not isinstance(pals, list):
        pals = []
    if not any(p.get("id") == active for p in pals):
        active = ""
    return {"palettes": pals, "active": active, "colors": PALETTE_COLORS}


def save_palette(name: str, colors: list[str], pid: str = "") -> dict:
    clean = [c for c in (colors or []) if c in PALETTE_COLORS] or ["yellow"]
    try:
        pals = db.get_setting("highlight_palettes", [])
    except Exception:  # noqa: BLE001
        pals = []
    if not isinstance(pals, list):
        pals = []
    pid = pid or _id("hp")
    rec = {"id": pid, "name": (name or "").strip() or "Untitled palette",
           "colors": clean, "default": clean[0]}
    pals = [p for p in pals if p.get("id") != pid] + [rec]
    db.set_setting("highlight_palettes", pals)
    return {"ok": True, "palette": rec}


def delete_palette(pid: str) -> dict:
    try:
        pals = db.get_setting("highlight_palettes", [])
    except Exception:  # noqa: BLE001
        pals = []
    db.set_setting("highlight_palettes",
                   [p for p in (pals or []) if p.get("id") != pid])
    try:
        if db.get_setting("highlight_palette_active", "") == pid:
            db.set_setting("highlight_palette_active", "")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "removed": pid}


def activate_palette(pid: str) -> dict:
    try:
        pals = db.get_setting("highlight_palettes", [])
    except Exception:  # noqa: BLE001
        pals = []
    if pid and not any(p.get("id") == pid for p in (pals or [])):
        return {"ok": False, "error": "No such palette"}
    db.set_setting("highlight_palette_active", pid or "")
    return {"ok": True, "active": pid or ""}
