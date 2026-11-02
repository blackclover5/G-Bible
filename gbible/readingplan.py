"""A reading plan with day numbers, built from what is installed.

Why this is not just the devotional for today's date
----------------------------------------------------

`readingplan` already reads the day's entry from every installed devotional, and
that is the honest reading of what a devotional is: it was written for a
calendar.  But a calendar is not a plan.  A plan has **day numbers** -- day 1, day
2, day 137 -- because the thing a reader actually wants is *how far through am I*
and *what was day 90*, and a date cannot answer either.  A plan also names the
passages, so pressing on a day takes you to the text rather than to a meditation
about it.

So this offers three kinds, and says which one it is:

* **From a devotional.**  The devotional's own entries, numbered by their
  position rather than their month-day, so a book that starts on an arbitrary date
  -- most of them do -- still has a day 1.
* **Through the Bible.**  A generated passage path in canonical order, so the
  plan is scripture rather than commentary on scripture.
* **The lectionary.**  Only where the material is installed: a lectionary module
  is a dated set of readings, and pretending to build one would mean inventing
  the church's calendar.

Progress is kept in `setting`, one key per plan.  No new table: the shape of this
is a small list of day numbers, and a table with a schema would be a migration to
store less than a JSON value does.
"""

from __future__ import annotations

import re

from . import canon, db, library

PROGRESS_KEY = "reading-plan/progress"
CUSTOM_KEY = "reading-plan/custom"


def custom_plans() -> dict:
    """User-defined plans: name -> list of passage references."""
    got = db.get_setting(CUSTOM_KEY, {}) or {}
    return got if isinstance(got, dict) else {}


#: Plan ids the built-in plans already answer to.  A user-defined plan is
#: addressed by its name, so a plan called "bible" would otherwise shadow
#: Through the Bible: `day()` looks custom plans up first, and the 638-day
#: computed plan would quietly become whatever the reader had typed under that
#: name.  These names are refused rather than silently renamed, so the plan the
#: reader asked for is never not the plan they get.
_RESERVED_PLAN_NAMES = {"bible"}


def save_custom_plan(name: str, refs: list[str]) -> dict:
    """Save a user-defined reading plan from a list of passage references."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Name the plan."}
    if len(name) > 60:
        return {"ok": False, "error": "Keep the name under 60 characters."}
    if name.lower() in _RESERVED_PLAN_NAMES:
        return {"ok": False, "error":
                f"{name!r} is a built-in plan's name. Choose another."}
    if name.startswith(("dev:", "lection:")):
        return {"ok": False, "error":
                "A plan name cannot start with 'dev:' or 'lection:' — those "
                "identify the built-in devotional and lectionary plans."}
    clean = []
    for r in refs:
        r = (r or "").strip()
        if r and r not in clean:
            clean.append(r)
    if not clean:
        return {"ok": False, "error": "Add at least one passage."}
    all_c = custom_plans()
    all_c[name] = clean
    db.set_setting(CUSTOM_KEY, all_c)
    return {"ok": True, "name": name, "days": len(clean), "refs": clean}


def delete_custom_plan(name: str) -> dict:
    """Remove a user-defined plan.  Built-in plans cannot be deleted."""
    all_c = custom_plans()
    was = name in all_c
    all_c.pop(name, None)
    db.set_setting(CUSTOM_KEY, all_c)
    # Clear any progress for this plan too.
    allp = progress()
    allp.pop(name, None)
    db.set_setting(PROGRESS_KEY, allp)
    return {"ok": True, "name": name, "deleted": was}


def _custom_days(name: str) -> list[dict]:
    """A custom plan's days, in order."""
    refs = custom_plans().get(name, [])
    out = []
    for i, ref in enumerate(refs, 1):
        rr = canon.parse_ref(ref)
        f = next(iter(rr.refs()), None) if rr else None
        out.append({
            "n": i,
            "key": ref,
            "title": (f"{f.book} {f.chapter}" if f and f.book else ref),
            "ref": ref,
            "osis": (f.osis_id() if f else ""),
        })
    return out


# --------------------------------------------------------------- progress --

def progress(plan: str = "") -> dict:
    """Which days of which plans have been read."""
    got = db.get_setting(PROGRESS_KEY, {}) or {}
    return got if isinstance(got, dict) else {}


def set_progress(plan: str, day: int, done: bool = True) -> dict:
    """Mark a day read or unread.  Returns the plan's whole set."""
    if not plan:
        raise ValueError("which plan?")
    allp = progress()
    days = set(allp.get(plan) or [])
    if done:
        days.add(int(day))
    else:
        days.discard(int(day))
    allp[plan] = sorted(days)
    db.set_setting(PROGRESS_KEY, allp)
    return {"plan": plan, "days": sorted(days),
            "count": len(days)}


def clear_progress(plan: str) -> dict:
    allp = progress()
    allp.pop(plan, None)
    db.set_setting(PROGRESS_KEY, allp)
    return {"plan": plan, "days": []}


# ------------------------------------------------------------------ plans --

def plans() -> list[dict]:
    """Every plan this library can offer, with how long each one is."""
    out: list[dict] = []
    for m in library.list_all():
        if m.type != "Devotional" or not m.installed_at:
            continue
        days = _devotional_days(m.id)
        if not days:
            continue
        out.append({
            "id": f"dev:{m.id}",
            "kind": "devotional",
            "title": m.name,
            "sub": f"{len(days)} days · from this devotional",
            "days": len(days),
            "module_id": m.id,
        })
    bt = bible_plan()
    if bt["days"]:
        out.append({
            "id": "bible",
            "kind": "bible",
            "title": "Through the Bible",
            "sub": f"{bt['days']} days · {bt['chapters']:,} chapters, "
                   f"canonical order",
            "days": bt["days"],
        })
    # A lectionary module is a dated set of readings.  Offered only if one is
    # actually installed: the church's calendar is not something to synthesise.
    for m in library.list_all():
        if not m.installed_at:
            continue
        if "lection" in (m.type or "").lower() or "lection" in (m.name or "").lower():
            n = db.connect().execute(
                "SELECT COUNT(*) c FROM unit WHERE module_id=?",
                (m.id,)).fetchone()["c"]
            if n:
                out.append({
                    "id": f"lection:{m.id}", "kind": "lectionary",
                    "title": m.name, "sub": f"{n} dated readings",
                    "days": n, "module_id": m.id,
                })
    # User-defined plans, stored by name.
    for name, refs in custom_plans().items():
        out.append({
            "id": name, "kind": "custom",
            "title": name, "sub": f"{len(refs)} days · your own plan",
            "days": len(refs),
        })
    return out


def _devotional_days(module_id: str) -> list[dict]:
    """A devotional's entries in the order they were meant to be read."""
    rows = db.connect().execute(
        "SELECT key, title, book, chapter, verse, ord FROM unit "
        "WHERE module_id=? ORDER BY ord", (module_id,)).fetchall()
    out = []
    for i, r in enumerate(rows, 1):
        key = r["key"] or ""
        rr = canon.parse_ref(key)
        f = next(iter(rr.refs()), None) if rr else None
        out.append({
            "n": i,
            "key": key,
            "title": r["title"] or key,
            "ref": (f"{f.book} {f.chapter}" if f and f.book else ""),
            "osis": (f.osis_id() if f else ""),
        })
    return out


#: Chapters per day, chosen so that a year is about the right length and the
#: Psalms and the Gospels are not left to the end.  A single chunking rule --
#: "as many chapters as will fit in the day's word budget" -- would put Genesis
#: and Malachi at opposite ends of a year, which is how a through-the-Bible plan
#: comes to be abandoned in Leviticus.
_BIBLE_SECTIONS = [
    # (books, chapters per day)
    ("Gen", 3), ("Exod", 3), ("Lev", 2), ("Num", 3), ("Deut", 3),
    ("Josh", 3), ("Judg", 3), ("Ruth", 1), ("1Sam", 2), ("2Sam", 2),
    ("1Kgs", 2), ("2Kgs", 2), ("1Chr", 2), ("2Chr", 2), ("Ezra", 1),
    ("Neh", 1), ("Esth", 1), ("Job", 2), ("Ps", 2), ("Prov", 2),
    ("Eccl", 1), ("Song", 1), ("Isa", 3), ("Jer", 3), ("Lam", 1),
    ("Ezek", 3), ("Dan", 2), ("Hos", 1), ("Joel", 1), ("Amos", 1),
    ("Obad", 1), ("Jonah", 1), ("Mic", 1), ("Nah", 1), ("Hab", 1),
    ("Zeph", 1), ("Hag", 1), ("Zech", 2), ("Mal", 1),
    ("Matt", 2), ("Mark", 1), ("Luke", 2), ("John", 2), ("Acts", 3),
    ("Rom", 2), ("1Cor", 2), ("2Cor", 1), ("Gal", 1), ("Eph", 1),
    ("Phil", 1), ("Col", 1), ("1Thess", 1), ("2Thess", 1), ("1Tim", 1),
    ("2Tim", 1), ("Titus", 1), ("Phlm", 1), ("Heb", 2), ("Jas", 1),
    ("1Pet", 1), ("2Pet", 1), ("1John", 1), ("2John", 1), ("3John", 1),
    ("Jude", 1), ("Rev", 2),
]


#: Which books the library actually has text for, keyed on the unit count so an
#: install invalidates it.
_BOOKS_CACHE: tuple = ()


def _books_with_text() -> dict:
    """OSIS book -> chapter count, for every book this library can open.

    One `DISTINCT` query, not one per book.  Asking book by book meant 66 full
    scans of a 1.2 million row table with no index on `unit.book`, and the
    dashboard waited **eight seconds** for it on every load -- which is the
    measure of how a question that looks trivial can be the slowest thing in an
    application.  The answer is cached against the unit count, because that is
    what changes when a module is installed or removed.
    """
    global _BOOKS_CACHE
    conn = db.connect()
    total = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
    if _BOOKS_CACHE and _BOOKS_CACHE[0] == total:
        return _BOOKS_CACHE[1]
    rows = conn.execute(
        "SELECT DISTINCT book FROM unit WHERE book IS NOT NULL AND book<>''"
    ).fetchall()
    have = {r["book"]: (canon.chapter_count("KJV", r["book"]) or 1)
            for r in rows if r["book"] in canon.BOOK_BY_OSIS}
    _BOOKS_CACHE = (total, have)
    return have


def bible_plan() -> dict:
    """A passage path through the whole Bible, in canonical order.

    Computed from the books the reader has, so a library with only the New
    Testament gets a New Testament plan and says how much of the Bible that is,
    rather than offering 1,189 days of which 929 cannot be opened.
    """
    have = _books_with_text()
    if not have:
        return {"days": 0, "chapters": 0, "items": [],
                "books": 0, "of": len(canon.BOOKS_66)}
    days: list[dict] = []
    n = 0
    chapters = 0
    covered: set[str] = set()
    for osis, per in _BIBLE_SECTIONS:
        if osis not in have:
            continue
        covered.add(osis)
        total = have[osis]
        at = 1
        while at <= total:
            last = min(total, at + per - 1)
            n += 1
            chapters += last - at + 1
            days.append({
                "n": n,
                "title": (f"{canon.BOOK_BY_OSIS[osis].name} {at}"
                          if at == last else
                          f"{canon.BOOK_BY_OSIS[osis].name} {at}-{last}"),
                "ref": f"{osis} {at}" if at == last else f"{osis} {at}-{last}",
                "osis": osis,
            })
            at = last + 1
    return {"days": n, "chapters": chapters, "items": days,
            # How many of the 66 the plan actually reaches.  Not how many books
            # the library holds: that includes the apocrypha, which a
            # canonical-order plan does not read, so quoting it made a 66-book
            # plan claim to cover 81.
            "books": len(covered), "of": len(canon.BOOKS_66),
            "extra_books": sorted(set(have) - set(canon.BOOKS_66[i].osis
                                                    for i in range(66)))}


# --------------------------------------------------------------- one day --

def day(plan_id: str, n: int = 0) -> dict:
    """One day of a plan, with its passages and whether it is read.

    `n` is the day number.  Zero means "today's day": the first day not yet
    marked, which is the useful reading of "today" in a plan and the one that
    makes the plan resumable after a gap.
    """
    plan_id = (plan_id or "").strip()
    if not plan_id:
        avail = plans()
        if not avail:
            return {"ok": False, "error":
                    "no reading plan is available from this library"}
        plan_id = avail[0]["id"]
    n = int(n or 0)
    done = set(progress().get(plan_id) or [])

    # A custom plan named after a built-in is refused at creation, but one
    # saved before that rule existed could still be in the setting.  Reserving
    # the name at lookup as well means the built-in always wins, so the worst
    # case is that such a plan is unreachable rather than that the Bible plan
    # is silently replaced by it.
    if (plan_id in custom_plans()
            and plan_id.lower() not in _RESERVED_PLAN_NAMES
            and not plan_id.startswith(("dev:", "lection:"))):
        days = _custom_days(plan_id)
        if not days:
            return {"ok": False, "error": "that plan has no passages"}
        if not n:
            n = next((d["n"] for d in days if d["n"] not in done), days[-1]["n"])
        row = next((d for d in days if d["n"] == n), None)
        if row is None:
            return {"ok": False, "error":
                    f"that plan has {len(days)} days, not {n}"}
        return {
            "ok": True, "plan": plan_id, "kind": "custom",
            "title": plan_id, "total": len(days), "day": row["n"],
            "done": row["n"] in done, "head": row["title"],
            "ref": row["ref"], "osis": row["osis"], "text": "",
            "passages": [row["ref"]],
        }

    if plan_id.startswith("dev:"):
        mid = plan_id[4:]
        days = _devotional_days(mid)
        if not days:
            return {"ok": False, "error": "that devotional has no dated entries"}
        if not n:
            n = next((d["n"] for d in days if d["n"] not in done), days[-1]["n"])
        row = next((d for d in days if d["n"] == n), None)
        if row is None:
            return {"ok": False, "error":
                    f"that plan has {len(days)} days, not {n}"}
        m = library.get(mid)
        reading = db.connect().execute(
            "SELECT text, title FROM unit WHERE module_id=? AND key=?",
            (mid, row["key"])).fetchone()
        return {
            "ok": True, "plan": plan_id, "kind": "devotional",
            "title": (m.name if m else "Devotional"),
            "total": len(days), "day": row["n"], "done": row["n"] in done,
            "head": row["title"], "ref": row["ref"], "osis": row["osis"],
            "text": ((reading["text"] or "") if reading else ""),
            "passages": ([row["ref"]] if row["ref"] else []),
        }

    if plan_id.startswith("lection:"):
        mid = plan_id[9:]
        rows = db.connect().execute(
            "SELECT key, title, book, chapter, verse, text FROM unit "
            "WHERE module_id=? ORDER BY ord", (mid,)).fetchall()
        if not rows:
            return {"ok": False, "error": "that lectionary has no readings"}
        if not n:
            n = next((i for i in range(1, len(rows) + 1) if i not in done), 1)
        if n < 1 or n > len(rows):
            return {"ok": False, "error":
                    f"that plan has {len(rows)} days, not {n}"}
        r = rows[n - 1]
        m = library.get(mid)
        ref = ""
        if r["book"]:
            f = canon.Ref(r["book"], r["chapter"] or 1, r["verse"] or 0)
            ref = canon.format_ref(f)
        return {
            "ok": True, "plan": plan_id, "kind": "lectionary",
            "title": (m.name if m else "Lectionary"),
            "total": len(rows), "day": n, "done": n in done,
            "head": r["title"] or f"Day {n}", "ref": ref, "osis": "",
            "text": (r["text"] or ""), "passages": ([ref] if ref else []),
        }

    bp = bible_plan()
    if not bp["days"]:
        return {"ok": False, "error": "no Bible text installed"}
    if plan_id != "bible":
        # An unrecognised id used to fall through to the Bible plan, so a typo in
        # a saved link or a plan that has been uninstalled since opened as a
        # different plan without saying so.  Answering the question that was
        # asked is not the same as answering a question that was not.
        return {"ok": False, "error":
                f"{plan_id!r} is not a reading plan in this library",
                "available": [p["id"] for p in plans()]}
    if not n:
        n = next((d["n"] for d in bp["items"] if d["n"] not in done), 1)
    row = next((d for d in bp["items"] if d["n"] == n), None)
    if row is None:
        return {"ok": False, "error":
                f"that plan has {bp['days']} days, not {n}"}
    return {
        "ok": True, "plan": plan_id, "kind": "bible",
        "title": "Through the Bible", "total": bp["days"], "day": n,
        "done": n in done, "head": row["title"], "ref": row["ref"],
        "osis": row["osis"], "text": "",
        "passages": [row["ref"]],
        "note": (f"{bp['books']} of {bp['of']} books are installed, so this "
                 f"plan covers what your library actually contains."),
    }


def overview(plan_id: str = "") -> dict:
    """The whole plan as a list, so a reader can see the shape of it.

    Every kind of plan is answered here.  Falling through to the Bible plan for
    a plan this function did not recognise is the same fault `day()` had: a
    four-day custom plan answered with 638 days of Genesis, which reads as a
    working feature showing the wrong thing.
    """
    if (plan_id in custom_plans()
            and plan_id.lower() not in _RESERVED_PLAN_NAMES
            and not plan_id.startswith(("dev:", "lection:"))):
        days = _custom_days(plan_id)
        return {"ok": True, "plan": plan_id, "kind": "custom",
                "total": len(days),
                "items": [{"n": d["n"], "title": d["title"], "ref": d["ref"]}
                          for d in days]}
    if plan_id.startswith("dev:"):
        mid = plan_id[4:]
        days = _devotional_days(mid)
        return {"ok": True, "plan": plan_id, "kind": "devotional",
                "total": len(days),
                "items": [{"n": d["n"], "title": d["title"], "ref": d["ref"]}
                          for d in days]}
    if plan_id.startswith("lection:"):
        mid = plan_id[9:]
        rows = db.connect().execute(
            "SELECT book, chapter, title FROM unit WHERE module_id=? ORDER BY ord",
            (mid,)).fetchall()
        items = []
        for i, r in enumerate(rows, 1):
            ref = ""
            if r["book"]:
                ref = canon.format_ref(
                    canon.Ref(r["book"], r["chapter"] or 1, 0))
            items.append({"n": i, "title": r["title"] or f"Day {i}",
                          "ref": ref})
        return {"ok": True, "plan": plan_id, "kind": "lectionary",
                "total": len(items), "items": items}
    bp = bible_plan()
    return {"ok": True, "plan": plan_id or "bible", "kind": "bible",
            "total": bp["days"],
            "items": [{"n": d["n"], "title": d["title"], "ref": d["ref"]}
                      for d in bp["items"]]}