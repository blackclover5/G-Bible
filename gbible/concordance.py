"""A concordance for a chapter: every word, and where it stands.

A Bible concordance is a reverse index.  You look up a word and it tells you
every place that word occurs, in context, so you can see the pattern without
reading the book through.  That is what this does, for a chapter or any range,
using the Strong's tagging the imported texts already carry.

Two decisions worth stating, because a concordance that hides them is worse than
none:

**Untagged text is still indexed, but by its surface form.**  A resource with
no Strong's markup would otherwise produce an empty concordance, which reads as
"this chapter has no words in it" rather than "this resource is untagged".  Those
entries are marked `tagged: False` so nobody mistakes a spelling match for a
lemma match -- "he", "him" and "his" are three different entries there, and the
tool says so rather than implying they are one.

**Capitalisation is not a distinction.**  "Lord" and "lord" are the same word
in a concordance; searching case-sensitively for a noun gives you a handful of
results that look like a different subject.

The context window is the whole verse, with the match marked, which is what a
reader actually wants: enough text to judge the usage without the paragraph
noise around it.
"""

from __future__ import annotations

import json
import re
import unicodedata

from . import canon, db, library

# A word is a run of letters, or letters with internal apostrophes/hyphens.
_WORD = re.compile(r"[^\W\d_]+(?:['\u2019\-][^\W\d_]+)*", re.UNICODE)


def _norm(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower().strip())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return w.replace("\u2019", "'")


def _spans(text: str, markup: str) -> list[tuple[int, int, str]]:
    """[(start, length, strongs)] from a unit's stored markup.

    Offsets are character positions in `text`.  A span the text cannot support
    -- a stale index, an edited translation -- is dropped rather than allowed to
    slice a word in half.
    """
    if not markup or not text:
        return []
    try:
        d = json.loads(markup)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for sp in d.get("s") or []:
        try:
            start, ln, kind, val = int(sp[0]), int(sp[1]), sp[2], sp[3]
        except (TypeError, ValueError, IndexError):
            continue
        if kind != "strongs" or not val:
            continue
        if start < 0 or ln <= 0 or start + ln > len(text):
            continue
        nums = " ".join(x for x in str(val).split() if re.fullmatch(r"[GH]\d+", x))
        if nums:
            out.append((start, ln, nums))
    return out


def _words(text: str, spans: list[tuple[int, int, str]]) -> list[dict]:
    """Every word in the text, with its Strong's numbers where known."""
    out = []
    for m in _WORD.finditer(text or ""):
        a, b = m.start(), m.end()
        st = ""
        for start, ln, nums in spans:
            # A Strong's span covers the word, possibly including trailing
            # punctuation; require real overlap rather than mere adjacency.
            if start < b and a < start + ln:
                st = (st + " " + nums).strip()
                break
        out.append({"word": m.group(0), "start": a, "end": b, "strongs": st})
    return out


def _entry_key(w: dict) -> tuple[str, str]:
    """Group by Strong's number when there is one, else by the word itself."""
    if w["strongs"]:
        first = w["strongs"].split()[0]
        return ("s", first)
    return ("w", _norm(w["word"]))


def _context(text: str, a: int, b: int, *, pad: int = 60) -> tuple[str, str, str]:
    """(before, match, after) around a word, trimmed to sentence-ish edges."""
    before = text[max(0, a - pad):a]
    after = text[b:b + pad]
    # Start the "before" on a word boundary so it does not begin mid-word.
    sp = before.rfind(" ")
    if sp > 0 and len(before) - sp < 14:
        before = before[sp + 1:]
    return (before, text[a:b], after)


def _strip_markup(text: str) -> str:
    """Remove the footnote markers and Strong's brackets from display text.

    Concordance lines are meant to be read; a column of "8" markers from the
    footnote apparatus is not.
    """
    text = re.sub(r"\[\d+\]", "", text or "")
    text = re.sub(r"<sup>.*?</sup>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def build(module_id: str, ref: str, *, word: str = "", tagged_only: bool = False) -> dict:
    """Every word in a chapter or range, or every use of one word in it."""
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": f"no such resource: {module_id}"}
    rr = canon.parse_ref(ref, m.v11n or "KJV")
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    verses = list(rr.refs())
    if not verses:
        return {"ok": False, "error": "no verse in that reference"}
    if len(verses) > 400:
        return {"ok": False, "error":
                f"that is {len(verses)} verses; narrow it to 400 or fewer"}

    conn = db.connect()
    want = _norm(word)
    want_s = ""
    mw = re.fullmatch(r"[GH]\d+", (word or "").strip(), re.I)
    if mw:
        want_s = word.strip().upper()

    entries: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    scanned = 0
    partial = False
    # Build every entry first, then choose.  Filtering on the surface form as we
    # go meant looking up "love" found nothing, because the word in the text is
    # "loved" -- and a concordance that cannot follow a word to its other forms
    # is an index, not a concordance.  Choosing after the fact is what lets
    # "loved" return all 66 uses of the lemma.
    want_norm = _norm(want)
    for v in verses:
        row = conn.execute(
            "SELECT key, text, markup FROM unit WHERE module_id=? AND book=? "
            "AND chapter=? AND verse=? LIMIT 1",
            (m.id, v.book, v.chapter, v.verse)).fetchone()
        if row is None or not (row["text"] or "").strip():
            continue
        scanned += 1
        text = row["text"]
        spans = _spans(text, row["markup"])
        for w in _words(text, spans):
            key = _entry_key(w)
            if tagged_only and key[0] != "s":
                continue
            e = entries.get(key)
            if e is None:
                e = {"key": key[0], "id": key[1],
                     "strongs": w["strongs"], "lemma": "", "word": w["word"],
                     "tagged": key[0] == "s", "forms": {}, "count": 0,
                     "occurrences": []}
                entries[key] = e
                order.append(key)
            e["count"] += 1
            e["forms"][w["word"]] = e["forms"].get(w["word"], 0) + 1
            if not e["strongs"]:
                e["strongs"] = w["strongs"]
            before, hit, after = _context(text, w["start"], w["end"])
            e["occurrences"].append({
                "ref": v.label, "key": row["key"], "verse": v.verse,
                "before": _strip_markup(before).lstrip(),
                "word": hit, "after": _strip_markup(after),
            })

    listed = [entries[k] for k in order]
    if want_s:
        listed = [e for e in listed if want_s in (e["strongs"] or "").split()]
    elif want_norm:
        # `forms` is still a {word: n} dict at this point; it is turned into a
        # list of pairs further down.  Iterating it as a list of objects here
        # raised "string indices must be integers".
        def has_exact(e):
            return any(_norm(w) == want_norm for w in e["forms"])
        listed = [e for e in listed if has_exact(e)]
        if not listed:
            # Fall back to a prefix match, because people look up "beget" and
            # mean "begotten".  Say so, so nobody reads it as an exact hit.
            listed = [e for e in entries.values()
                      if any(_norm(w).startswith(want_norm) for w in e["forms"])]
            if listed:
                partial = True
    if (want or want_s) and not listed:
        where = verses[0].label if len(verses) == 1 else \
            f"{verses[0].label}\u2013{verses[-1].label}"
        return {"ok": False,
                "error": f"“{word}” does not occur in {where}"}

    # Most-used first, so the word that ties the chapter together is at the top.
    listed.sort(key=lambda e: (-e["count"], e["id"]))
    for e in listed:
        e["forms"] = [{"word": w, "n": n}
                      for w, n in sorted(e["forms"].items(), key=lambda x: -x[1])]
    extra = []
    if partial:
        extra.append(f"No entry for “{word}” exactly; showing words that begin "
                     f"with it.")

    return {
        "ok": True,
        "module_id": module_id, "module": m.name,
        "ref": verses[0].label if len(verses) == 1
             else f"{verses[0].label}\u2013{verses[-1].label}",
        "verses": len(verses), "scanned": scanned,
        "word": word,
        "entries": listed,
        "distinct": len(listed),
        "occurrences": sum(e["count"] for e in listed),
        "tagged_words": sum(1 for e in listed if e["tagged"]),
        "notes": _notes(listed, m) + extra,
        "partial": partial,
    }


def _notes(entries: list[dict], m) -> list[str]:
    out = []
    if entries and all(not e["tagged"] for e in entries):
        out.append(
            f"{m.name} has no Strong's tagging, so entries here are matched by "
            f"spelling. Forms of the same word count separately, and this is not "
            f"a lemma index.")
    elif entries and any(not e["tagged"] for e in entries):
        out.append(
            "Some entries are matched by spelling because this text is not fully "
            "tagged; those forms count separately from the tagged ones.")
    return out


def completeness(module_id: str) -> dict:
    """Is this Bible whole, and if not, *how* is it not whole.

    Two very different things both look like "some verses are missing", and
    conflating them makes a tool cry wolf:

    **Truncation** -- the chapter is there and stops early.  A reference to its
    last verse simply will not resolve, with nothing on screen to suggest why.
    The King James module from CrossWire did this in 1,125 of 1,189 chapters.

    **Abridgement** -- whole chapters were never included.  That is an editorial
    decision, and the 1911 Migne "perpetual" French Vulgate omits most of the
    Old Testament on purpose.  Nothing is truncated, the edition is just
    shorter, and warning about it would be wrong.

    So the two are counted separately and reported differently.
    """
    m = library.get(module_id)
    if m is None or m.type != "Bible":
        return {"ok": False}
    conn = db.connect()
    have = {(c["book"], c["chapter"]): (c["m"] or 0)
            for c in conn.execute(
                "SELECT book, chapter, MAX(verse) m FROM unit WHERE module_id=? "
                "GROUP BY book, chapter", (module_id,))}
    expected, short = set(), []
    for bk in {b for b, _c in have}:
        for ch in range(1, (canon.chapter_count("KJV", bk) or 0) + 1):
            expected.add((bk, ch))
    for (bk, ch), maxv in have.items():
        want = canon.verse_count("KJV", bk, ch)
        if want and maxv < want:
            short.append((bk, ch, maxv, want))
    missing = expected - set(have)
    n_have = len(have) or 1
    pct_short = 100.0 * len(short) / n_have
    pct_absent = 100.0 * len(missing) / max(1, len(expected))
    # Truncation and abridgement are told apart by what is *present*, because in
    # an abridged edition a short chapter is the abridgement rather than damage
    # to it.  The French Migne Vulgate omits 80% of its chapters on purpose, so
    # half of what remains ends early -- and that is the edition, not a broken
    # index.  A text that has nearly all its chapters and still stops most of
    # them early has a problem.
    abridged = pct_absent > 10
    truncated = (not abridged) and pct_short >= 50
    out = {
        "ok": True, "name": m.name,
        "chapters": len(have), "expected_chapters": len(expected),
        "short": len(short), "missing": len(missing),
        "percent_short": round(pct_short, 1),
        "percent_absent": round(pct_absent, 1),
        "truncated": truncated, "abridged": abridged,
        "examples": [f"{b} {c}" for b, c, _m, _w in short[:6]],
    }
    if truncated:
        out["warning"] = (
            f"{m.name} is truncated: {len(short)} of its {len(have)} chapters "
            f"stop short of where they should ({round(pct_short)}%), so "
            f"references to a chapter's closing verses will not resolve -- for "
            f"example {', '.join(out['examples'][:3])}.")
    elif abridged:
        pct_miss = pct_absent
        out["warning"] = (
            f"{m.name} is an abridged edition: {len(missing)} of its "
            f"{len(expected)} chapters are not included ({round(pct_miss)}%). "
            f"That is the edition, not damage to it -- nothing is truncated -- "
            f"but a reference to an omitted chapter will not open.")
    else:
        out["warning"] = ""
    return out


def truncated_bibles() -> list:
    """Every installed Bible that is systematically incomplete."""
    out = []
    for m in library.list_all():
        if m.type != "Bible":
            continue
        c = completeness(m.id)
        if c.get("truncated"):
            out.append(c)
    return out
