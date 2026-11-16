"""Create a daily devotion out of what is already installed.

The library holds Bibles and commentaries whose text is cut into chapters,
and generic books whose text is only prose.  This turns either into a
`Devotional` module — the same shape as the Spurgeon devotional — so the
result appears on the Today screen under "Today's reading" and opens in a
pane as a normal date-indexed devotion.

Rules the user asked for, and how they are kept:

* **Bibles are never split mid-chapter.**  Chapters are the smallest
  indivisible unit: a day either gets whole chapters or none, so a Psalm is
  never torn across two days.  When there are fewer chapters than reading
  days (the New Testament over twelve months is the real case), the chapter
  constraint is relaxed and the text is split at *sentence* boundaries
  instead — still never mid-sentence, still every day non-empty.
* **Sentences are never cut in half.**  Prose is divided at sentence ends,
  using the same boundary detector as the clause tools.
* **Even, as even as the atoms allow.**  Days are given as close to the
  average as chapter/sentence granularity permits, weighed by word count so
  Psalm 119 does not count as one "unit" the same as Psalm 117.
* **It behaves like any other devotion.**  The entries are `MM.DD` keys
  with the day's portion as the text; installing one is all the Today screen
  and the pane ever look for.

The created module records what it was made from (`raw_meta`) so it can be
listed, re-opened and deleted safely, and never opens as a different module
than the one the user asked for.
"""

from __future__ import annotations

import json
import re
import time
from bisect import bisect_left
from datetime import date, datetime, timedelta

from . import canon, clause, db, library

#: Setting holding the ids of every devotion this tool has created.  Deleting
#: and listing work off this list rather than off a `LIKE` over `raw_meta`, so
#: a module the user created by other means can never be mistaken for ours.
_CREATED_KEY = "devotion-creator/modules"

#: Average reading speed for Scripture, for the minutes-per-day estimate.
_WPM = 240

#: The longest plan this will build.  MM.DD keys repeat yearly, so a plan
#: longer than a year would double up its own dates.
_MAX_SPAN_DAYS = 366

#: Absurd end of the range: finer than this is not a plan, it is a word per day.
_MIN_WORDS_PER_DAY = 40


# ------------------------------------------------------------------ helpers --

def _created_ids() -> list[str]:
    got = db.get_setting(_CREATED_KEY, []) or []
    return [x for x in got if isinstance(x, str) and x.strip()]


def _save_created_ids(ids: list[str]) -> None:
    db.set_setting(_CREATED_KEY, list(dict.fromkeys(ids)))


def _book_order(book: str) -> tuple[int, str]:
    b = canon.BOOK_BY_OSIS.get(book)
    return (0, f"{b.ordinal:04d}") if b else (1, book or "")


def _book_name(book: str) -> str:
    b = canon.BOOK_BY_OSIS.get(book)
    return b.name if b else book


def _group(book: str) -> str:
    b = canon.BOOK_BY_OSIS.get(book)
    return b.group if b else "?"


def _atoms(module_id: str) -> list[dict]:
    """Chapters present in a module, in reading order.

    One atom per (book, chapter) with non-null coordinates, weighed by word
    count.  This is what a Bible or a commentary is cut into.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT book, chapter, SUM(COALESCE(word_count, 0)) AS words, "
        "       COUNT(*) AS units "
        "FROM unit WHERE module_id=? AND book IS NOT NULL AND book<>'' "
        "  AND chapter IS NOT NULL "
        "GROUP BY book, chapter", (module_id,)).fetchall()
    out = [{"book": r["book"], "chapter": int(r["chapter"] or 0),
             "words": int(r["words"] or 0), "units": int(r["units"] or 0)}
            for r in rows]
    out.sort(key=lambda a: (_book_order(a["book"]), a["chapter"]))
    return out


def _split_scope(atoms: list[dict], scope: str) -> list[dict]:
    if scope == "whole":
        return atoms
    if scope == "ot":
        return [a for a in atoms if _group(a["book"]) == "OT"]
    if scope == "nt":
        return [a for a in atoms if _group(a["book"]) == "NT"]
    if scope.startswith("book:"):
        osis = scope[5:]
        return [a for a in atoms if a["book"] == osis]
    if scope.startswith("ch:"):
        osis, _, ch = scope[3:].rpartition(".")
        try:
            ch = int(ch)
        except ValueError:
            return []
        return [a for a in atoms if a["book"] == osis and a["chapter"] == ch]
    return []


def scopes(module_id: str) -> dict:
    """What the scope dropdown should offer for one module."""
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "module not found"}
    atoms = _atoms(module_id)
    present = sorted({(a["book"]) for a in atoms}, key=_book_order)
    has_bible_text = m.is_bible
    scopes_out: list[dict] = []
    if atoms:
        whole_label = ("Whole Bible" if has_bible_text else "Whole book")
        scopes_out.append({"value": "whole", "label": whole_label,
                           "words": sum(a["words"] for a in atoms)})
        if any(_group(b) == "OT" for b in present):
            scopes_out.append({"value": "ot", "label": "Old Testament",
                               "words": sum(a["words"] for a in atoms
                                            if _group(a["book"]) == "OT")})
        if any(_group(b) == "NT" for b in present):
            scopes_out.append({"value": "nt", "label": "New Testament",
                               "words": sum(a["words"] for a in atoms
                                            if _group(a["book"]) == "NT")})
    if has_bible_text:
        for b in present:
            bk = canon.BOOK_BY_OSIS.get(b)
            scopes_out.append({
                "value": f"book:{b}",
                "label": f"{bk.name if bk else b} — "
                         f"{len([a for a in atoms if a['book'] == b])} chapters",
                "group": "Individual books",
            })
    else:
        for b in present:
            for a in sorted((x for x in atoms if x["book"] == b),
                            key=lambda x: x["chapter"]):
                scopes_out.append({"value": f"ch:{a['book']}.{a['chapter']}",
                                   "label": f"{_book_name(a['book'])} {a['chapter']}",
                                   "group": _book_name(a["book"])})
    return {"ok": True, "module_id": module_id, "name": m.name,
            "kind": ("bible" if has_bible_text else
                     ("chaptered" if atoms else "prose")),
            "is_bible": has_bible_text, "scopes": scopes_out,
            "words": sum(a["words"] for a in atoms),
            "atoms": len(atoms)}


def books() -> dict:
    """Chaptered, installed modules — everything this tool can build from."""
    out = []
    for m in library.list_all():
        atoms = _atoms(m.id)
        if not atoms:
            continue
        out.append({"id": m.id, "name": m.name, "type": m.type_effective,
                    "is_bible": m.is_bible,
                    "atoms": len(atoms),
                    "words": sum(a["words"] for a in atoms)})
    out.sort(key=lambda b: (not b["is_bible"], b["name"].lower()))
    return {"ok": True, "books": out}


def _reading_days(start: date, finish: date,
                  weekdays: list[int]) -> list[date]:
    wk = set(weekdays) if weekdays else set(range(7))
    if not wk:
        wk = set(range(7))
    days, d = [], start
    while d <= finish:
        if d.weekday() in wk:
            days.append(d)
        d += timedelta(days=1)
    return days


def parse_when(params: dict) -> tuple[date | None, date | None, list[int], str | None]:
    """Parse and validate the date range and weekday list from a request."""
    try:
        start = date(*[int(p) for p in str(params.get("start", "")).split("-")[:3]])
        finish = date(*[int(p) for p in str(params.get("finish", "")).split("-")[:3]])
    except (ValueError, TypeError):
        return None, None, [], "Those are not valid dates."
    if finish < start:
        return None, None, [], "The finish date is before the start date."
    if (finish - start).days > _MAX_SPAN_DAYS:
        return None, None, [], ("That is longer than a year. A devotion is keyed "
                                "by month and day, so keep it within twelve months.")
    wk = []
    for w in params.get("weekdays") or []:
        try:
            w = int(w)
        except (TypeError, ValueError):
            continue
        if 0 <= w <= 6:
            wk.append(w)
    return start, finish, wk, None


def add_months(d: date, months: int) -> date:
    """Calendar-month addition with end-of-month clamping, as the dropdown means it."""
    month = d.month - 1 + months
    year, month = divmod(month, 12)
    year += d.year
    try:
        return date(year, month + 1, d.day)
    except ValueError:
        nxt = date(year + (month + 1) // 12, (month + 1) % 12 + 1, 1) if month == 11 \
            else date(year, month + 2, 1)
        return nxt - timedelta(days=1)


# -------------------------------------------------------------- partitioning --

def _cut_points(weights: list[int], days: int) -> list[int]:
    """Where to cut `weights` into `days` groups.

    Returns the exclusive end index of each of the first `days - 1` groups.
    Chapter-atomic: a group never ends inside an atom, and every group gets at
    least one atom, so with n atoms and d days the result is as even as the
    atom sizes allow.
    """
    n = len(weights)
    if days <= 1:
        return []
    days = min(days, n)
    total = float(sum(weights))
    if total <= 0:
        base, rem = divmod(n, days)
        cuts, at = [], 0
        for i in range(1, days):
            at += base + (1 if i <= rem else 0)
            cuts.append(at)
        return cuts
    cum = [0.0] * (n + 1)
    for i, w in enumerate(weights):
        cum[i + 1] = cum[i] + w
    cuts, prev = [], 0
    for i in range(1, days):
        remaining = days - i
        lo, hi = prev + 1, n - remaining
        if lo > hi:                      # degenerate, but never lose an atom
            cuts.append(prev + 1)
            prev += 1
            continue
        ideal = total * i / days
        j = bisect_left(cum, ideal, lo, hi + 1)
        best = j
        if j - 1 >= lo and abs(cum[j - 1] - ideal) <= abs(cum[min(j, hi)] - ideal):
            best = j - 1
        elif j > hi:
            best = hi
        cuts.append(best)
        prev = best
    return cuts


def _groups(items: list, days: int, weights: list[int]) -> list[list]:
    cuts = _cut_points(weights, days)
    boundaries = [0] + cuts + [len(items)]
    out, prev = [], 0
    for b in boundaries[1:]:
        out.append(items[prev:b])
        prev = b
    return out


def _sentence_texts(text: str) -> list[str]:
    """Sentences of `text`, split at clause._SENT_END — never mid-sentence."""
    out, last = [], 0
    for m in clause._SENT_END.finditer(text):
        end = m.end(1)
        chunk = text[last:end].strip()
        if chunk:
            out.append(chunk)
        last = m.end()
    tail = text[last:].strip()
    if tail:
        out.append(tail)
    return out


def _sentence_atoms(module_id: str, atoms: list[dict]) -> list[dict]:
    """Sentences of the given chapters, in order, with word counts."""
    conn = db.connect()
    out = []
    for atom in atoms:
        rows = conn.execute(
            "SELECT text FROM unit WHERE module_id=? AND book=? AND chapter=? "
            "ORDER BY ord", (module_id, atom["book"], atom["chapter"])).fetchall()
        paragraph_break = True
        for r in rows:
            text = r["text"] or ""
            paras = text.split("\n")
            for pi, fragment in enumerate(paras):
                fragment = fragment.strip()
                if not fragment:
                    paragraph_break = True
                    continue
                for s in _sentence_texts(fragment):
                    out.append({"text": s, "words": len(s.split()),
                                "para": paragraph_break,
                                "book": atom["book"], "chapter": atom["chapter"]})
                    paragraph_break = False
                # Anything on a new line begins a new paragraph
                if pi < len(paras) - 1:
                    paragraph_break = True
    return [a for a in out if a["words"]]


def _ref_summary(atoms: list[dict]) -> str:
    """'Genesis 1–3' or 'Mal 4; Matt 1–2' for a group of chapter atoms."""
    parts, runs = [], []
    for a in atoms:
        if runs and runs[-1][0] == a["book"]:
            runs[-1][1].append(a["chapter"])
        else:
            runs.append((a["book"], [a["chapter"]]))
    for book, chapters in runs:
        name = _book_name(book)
        if len(chapters) == 1:
            parts.append(f"{name} {chapters[0]}")
        else:
            parts.append(f"{name} {min(chapters)}–{max(chapters)}")
    return "; ".join(parts)


def _prepare(module_id: str, scope: str, start: date, finish: date,
             weekdays: list[int]) -> dict:
    """Work out the whole plan without writing anything.

    Shared by the estimate (which throws it away) and the create (which
    materialises it), so what the user is shown is exactly what they get.
    """
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "module not found"}
    atoms = _atoms(module_id)
    scoped = _split_scope(atoms, scope)
    if not scoped:
        return {"ok": False, "error": ("That part of this module has no text. "
                                       "Pick a different scope.")}
    days = _reading_days(start, finish, weekdays)
    if not days:
        return {"ok": False, "error": ("Not one reading day in that range. "
                                       "Choose at least one weekday.")}
    requested_days = len(days)
    words = sum(a["words"] for a in scoped)
    if words <= 0:
        return {"ok": False, "error": "That scope has no word count to split."}
    if words / max(requested_days, 1) < _MIN_WORDS_PER_DAY and requested_days > 1:
        # A devotion of filler.  Refuse rather than produce nonsense.
        cap = max(1, words // _MIN_WORDS_PER_DAY)
        return {"ok": False, "error":
                f"That scope only holds about {words:,} words — {cap} devotions of "
                f"at least {_MIN_WORDS_PER_DAY} words. Pick a shorter period or a "
                f"larger scope.", "cap": cap}

    use_sentences = len(scoped) < requested_days
    if use_sentences:
        sentences = _sentence_atoms(module_id, scoped)
        items, weights = sentences, [s["words"] for s in sentences]
        kind = "sentences"
    else:
        items, weights = scoped, [a["words"] for a in scoped]
        kind = "chapters"
    entries = min(requested_days, len(items))
    if entries < 1:
        return {"ok": False, "error": "That scope has no text to split."}
    cal_days = days[:entries]
    groups = _groups(items, entries, weights)
    total = sum(weights) or 1
    warnings = []
    if entries < requested_days:
        warnings.append(f"That range holds {requested_days} reading days but the scope "
                        f"only fills {entries} of them — the devotion covers the first "
                        f"{entries}. Shorten the period or pick a larger scope.")
    leap = any(d.month == 2 and d.day == 29 for d in cal_days)
    if leap:
        warnings.append("A reading day falls on February 29, so that entry "
                        "appears only in leap years.")
    if use_sentences and len(scoped) < requested_days:
        if len(scoped) == 1:
            warnings.append("One chapter cannot fill that many days, so the "
                            "chapter is split at sentence boundaries — never "
                            "mid-sentence.")
        else:
            warnings.append(f"Only {len(scoped)} chapters fit that range, so "
                            "some chapters are split at sentence boundaries — "
                            "never mid-chapter would leave days empty.")
    apd = total / entries
    return {"ok": True, "module_id": module_id, "scope": scope,
            "kind": kind, "days": cal_days, "groups": groups, "m": m,
            "words": words, "atoms": len(items), "atoms_chapters": len(scoped),
            "requested_days": requested_days, "entries": entries,
            "words_per_day": round(apd),
            "minutes_per_day": max(1, round(apd / _WPM)),
            "warnings": warnings, "leap": leap}


def estimate(params: dict) -> dict:
    module_id = (params.get("module_id") or "").strip()
    scope = (params.get("scope") or "").strip() or "whole"
    start, finish, wk, err = parse_when(params)
    if err:
        return {"ok": False, "error": err}
    plan = _prepare(module_id, scope, start, finish, wk)
    if not plan.get("ok"):
        return plan
    return {"ok": True, "kind": plan["kind"], "days": len(plan["days"]),
            "entries": plan["entries"], "requested_days": plan["requested_days"],
            "atoms": plan["atoms"], "atoms_chapters": plan["atoms_chapters"],
            "words": plan["words"],
            "words_per_day": plan["words_per_day"],
            "minutes_per_day": plan["minutes_per_day"],
            "warnings": plan["warnings"],
            "start": start.isoformat(), "finish": finish.isoformat()}


# --------------------------------------------------------------- building --

_SLUG_FALLBACK = "devotion"

def _new_id(title: str, when: float) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in title).strip("-") or _SLUG_FALLBACK
    base = "-".join(w for w in base.split("-") if w)[:44]
    stamp = format(int(when) & 0xFFFFFF, "x") + format(int(when * 1000) % 1000, "02x")
    return f"created-devotion-{base}-{stamp}"


def _span_lists(group: list[dict]) -> tuple[list[str], list[str]]:
    """The chapters a day's reading covers, in reading order.

    Returned as display references ("Genesis 1") and as KB keys for the study
    anchor tools, so the study and copy buttons point at the passage precisely.
    """
    spans, keys, seen = [], [], set()
    for a in group:
        bc = (a["book"], a["chapter"])
        if bc in seen:
            continue
        seen.add(bc)
        spans.append(f"{_book_name(a['book'])} {a['chapter']}")
        keys.append(f"{a['book']}.{a['chapter']}.1")
    return spans, keys


def _day_verse_rows(conn, mid, src, i, plan_kind, group):
    """Per-verse unit rows for one day of the devotion.

    Every verse the day touches becomes a unit keyed the way a Bible module
    keys it, carrying the source module's markup span table across, plus a
    map from source unit key to the new OSIS key so Strong's numbers and other
    markers can be re-pointed onto identical text.
    """
    if plan_kind == "chapters":
        chapter_atoms = [(a["book"], a["chapter"]) for a in group]
    else:
        chapter_atoms, seen = [], set()
        for a in group:
            bc = (a["book"], a["chapter"])
            if bc not in seen:
                seen.add(bc)
                chapter_atoms.append(bc)
    rows, src_keys, keymap = [], [], {}
    # ord starts at 1 million per day so a devotion's own MM.DD entries sort
    # before their verses; 1 million slots per day is far past any real day.
    seq = i * 1_000_000
    for (book, chapter) in chapter_atoms:
        verses = conn.execute(
            "SELECT key, ord, text, markup, char_start, char_len, word_count, "
            "ref_label, verse FROM unit "
            "WHERE module_id=? AND book=? AND chapter=? ORDER BY verse",
            (src.id, book, chapter)).fetchall()
        for j, r in enumerate(verses):
            seq += 1
            vnum = int(r["verse"] or 0)
            osis = f"{book}.{chapter}.{vnum}"
            extra = {"osis": osis, "source_id": src.id}
            if j == 0:
                extra["new_ch"] = f"{_book_name(book)} {chapter}"
            rows.append((mid, osis, seq, book, chapter, vnum,
                         r["ref_label"] or osis,
                         "", r["text"] or "", r["markup"] or "{}",
                         int(r["char_start"] or 0), int(r["char_len"] or 0),
                         int(r["word_count"] or 0),
                         json.dumps(extra, ensure_ascii=False)))
            src_keys.append(r["key"])
            keymap[r["key"]] = osis
    return rows, src_keys, keymap


def _day_title(n: int, group: list[dict], kind: str) -> str:
    if kind == "chapters":
        return f"Day {n} · {_ref_summary(group)}"
    return f"Day {n}"


def _day_text_chapter(m, group: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """The text of one day, and where each chapter heading sits in it.

    Returns (text, headings) with headings as (start, length) spans, so the
    markup table can render each chapter title as a visible heading rather
    than as plain words lost in the flow of the verses.
    """
    parts, spans, offset = [], [], 0
    conn = db.connect()
    for atom in group:
        name = _book_name(atom["book"])
        rows = conn.execute(
            "SELECT verse, text FROM unit WHERE module_id=? AND book=? AND chapter=? "
            "ORDER BY verse", (m.id, atom["book"], atom["chapter"])).fetchall()
        if m.is_bible:
            para = " ".join(f"{r['verse']} {r['text'].strip()}".strip()
                            for r in rows if (r["text"] or "").strip())
        else:
            para = " ".join((r["text"] or "").strip()
                            for r in rows if (r["text"] or "").strip())
        if parts:
            offset += 2              # the "\n\n" between chapters
        heading = f"{name} {atom['chapter']}"
        spans.append((offset, len(heading)))
        block = f"{heading}\n{para}"
        parts.append(block)
        offset += len(block)
    return "\n\n".join(p for p in parts if p.strip()), spans


def _day_text_sentences(group: list[dict]) -> str:
    parts, para = [], []
    for s in group:
        if s["para"] and para:
            parts.append(" ".join(para))
            para = []
        para.append(s["text"])
    if para:
        parts.append(" ".join(para))
    return "\n\n".join(parts).strip()


_NEWLINES = re.compile(r"\n")


def _markup(text: str, headings: list[tuple[int, int]]) -> str:
    """A span table the reader can render into real paragraphs and headings.

    A break span at every newline becomes <br>; a title span at each chapter
    heading becomes the same bold heading the articles use, so the devotion
    reads as headed sections instead of a wall of text.
    """
    spans = [[m.start(), 1, "break", "", "", {}] for m in _NEWLINES.finditer(text)]
    spans += [[s, ln, "chapter", "", "", {}] for s, ln in headings]
    return json.dumps({"s": spans, "n": [], "t": "",
                       "h": text.count("\n")}, ensure_ascii=False)


def create(params: dict) -> dict:
    module_id = (params.get("module_id") or "").strip()
    scope = (params.get("scope") or "").strip() or "whole"
    title = (params.get("title") or "").strip()
    start, finish, wk, err = parse_when(params)
    if err:
        return {"ok": False, "error": err}
    plan = _prepare(module_id, scope, start, finish, wk)
    if not plan.get("ok"):
        return plan
    m = plan["m"]
    scope_meta = scopes(module_id)
    scope_label = next((s["label"] for s in scope_meta.get("scopes", [])
                        if s.get("value") == scope), scope)
    if not title:
        title = f"{m.name} — {scope_label}"
    title = title[:80]
    days = plan["days"]

    now = time.time()
    mid = _new_id(title, now)
    conn = db.connect()
    raw_meta = {
        "generated_by": "devotion-creator",
        "source_id": m.id,
        "source_name": m.name,
        "scope": scope,
        "scope_label": scope_label,
        "start": start.isoformat(),
        "finish": finish.isoformat(),
        "weekdays": sorted(wk) if wk else list(range(7)),
        "kind": plan["kind"],
        "created": now,
        "title": title,
    }
    conn.execute("DELETE FROM unit WHERE module_id=?", (mid,))
    library.register(
        conn, id=mid, name=title, type="Devotional",
        format="gbible-devotion-creator",
        lang=m.lang or "en",
        description=(f"A daily devotion generated by G-Bible from {m.name} "
                     f"({scope_label}), {start.isoformat()} to {finish.isoformat()}."),
        about=(f"Created by the G-Bible devotional creator from {m.name}. "
               f"Scripture text is reproduced from the installed copy of that "
               f"module; its licence and attribution travel with it."),
        rights=f"Created from {m.name}. {m.rights or m.name}"[:500],
        license=m.license or "",
        author="G-Bible devotional creator",
        version="1.0",
        source="", source_name="", source_url="",
        installed_at=now, entries=len(days), chapters=0, verses=0,
        priority=0, raw_meta=raw_meta,
    )
    ins, ins_fts, ins_verses, ins_marker = [], [], [], []
    for i, (day, group) in enumerate(zip(days, plan["groups"]), 1):
        if plan["kind"] == "chapters":
            text, headings = _day_text_chapter(m, group)
        else:
            text, headings = _day_text_sentences(group), []
        dt = day
        title_d = _day_title(i, group, plan["kind"])
        spans, span_keys = _span_lists(group)
        vrows, src_keys, keymap = _day_verse_rows(conn, mid, m, i, plan["kind"], group)
        markup = _markup(text, headings)
        extra = json.dumps({"generated_by": "devotion-creator", "day": i,
                            "source_id": m.id,
                            "spans": spans, "span_keys": span_keys,
                            "verses": [r[1] for r in vrows]},
                           ensure_ascii=False)
        key = f"{dt.month:02d}.{dt.day:02d}"
        ref_label = f"{dt.strftime('%b')} {dt.day}"
        ins.append((mid, key, i, None, None, None, ref_label, title_d, text,
                    markup, 0, len(text),
                    len(text.split()), extra))
        ins_verses.extend(vrows)
        if src_keys:
            # Markers (Strong's, …) sit on identical text at
            # identical positions, so copy them onto the copied verses.
            placeholders = ",".join("?" * len(src_keys))
            for mk in conn.execute(
                    "SELECT kind, value, unit_key, pos, surface FROM marker "
                    f"WHERE module_id=? AND unit_key IN ({placeholders})",
                    (m.id, *src_keys)).fetchall():
                ins_marker.append((mid, mk["kind"], mk["value"],
                                   keymap[mk["unit_key"]], mk["pos"],
                                   mk["surface"]))
        ins_fts.append((mid, key, title_d, text))
    conn.executemany(
        "INSERT OR REPLACE INTO unit(module_id,key,ord,book,chapter,verse,"
        "ref_label,title,text,markup,char_start,char_len,word_count,extra) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ins)
    conn.executemany(
        "INSERT OR REPLACE INTO unit(module_id,key,ord,book,chapter,verse,"
        "ref_label,title,text,markup,char_start,char_len,word_count,extra) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ins_verses)
    if ins_marker:
        conn.executemany(
            "INSERT OR IGNORE INTO marker(module_id,kind,value,unit_key,pos,surface) "
            "VALUES(?,?,?,?,?,?)", ins_marker)
    conn.executemany(
        "INSERT INTO unit_fts(module_id,unit_key,title,text) VALUES(?,?,?,?)",
        ins_fts)
    conn.commit()
    _save_created_ids(_created_ids() + [mid])
    db.log_history("devotion-creator", f"Created devotion {title!r}",
                   {"module_id": mid, "source_id": m.id, "scope": scope,
                    "scope_label": scope_label,
                    "start": start.isoformat(), "finish": finish.isoformat(),
                    "days": len(days)})
    return {"ok": True, "module_id": mid, "name": title, "days": len(days),
            "words_per_day": plan["words_per_day"],
            "minutes_per_day": plan["minutes_per_day"],
            "kind": plan["kind"], "warnings": plan["warnings"],
            "start": start.isoformat(), "finish": finish.isoformat()}


def mine() -> dict:
    """Devotions this tool created, newest last."""
    conn = db.connect()
    out, stale = [], []
    for mid in _created_ids():
        row = conn.execute("SELECT id, name, installed_at, entries, raw_meta, "
                           "type FROM module WHERE id=?", (mid,)).fetchone()
        if row is None or row["type"] != "Devotional":
            stale.append(mid)
            continue
        try:
            meta = json.loads(row["raw_meta"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if meta.get("generated_by") != "devotion-creator":
            stale.append(mid)
            continue
        out.append({"id": row["id"], "name": row["name"],
                    "entries": row["entries"] or 0,
                    "created": meta.get("created") or row["installed_at"] or 0,
                    "scope_label": meta.get("scope_label") or "",
                    "source_name": meta.get("source_name") or "",
                    "start": meta.get("start") or "",
                    "finish": meta.get("finish") or "",
                    "kind": meta.get("kind") or ""})
    if stale:
        _save_created_ids([x for x in _created_ids() if x not in stale])
    out.sort(key=lambda x: x["created"])
    return {"ok": True, "devotions": out}


def delete(params: dict) -> dict:
    mid = (params.get("module_id") or "").strip()
    if not mid:
        return {"ok": False, "error": "which devotion?"}
    conn = db.connect()
    row = conn.execute("SELECT raw_meta, type FROM module WHERE id=?",
                       (mid,)).fetchone()
    try:
        meta = json.loads((row["raw_meta"] if row else "") or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    if (row is None or row["type"] != "Devotional"
            or meta.get("generated_by") != "devotion-creator"
            or mid not in _created_ids()):
        return {"ok": False, "error": ("That is not a devotion created by the "
                                       "devotional creator. Delete it from My library "
                                       "or the Store instead.")}
    conn.commit()   # free the read handle `get()` opened above
    r = library.remove_module(mid, delete_files=False)
    if r.get("ok"):
        _save_created_ids([x for x in _created_ids() if x != mid])
        db.log_history("devotion-creator", f"Deleted devotion {mid}",
                       {"module_id": mid})
    return r
