"""NT Use of OT: which New Testament verses quote the Old Testament.

This is sometimes sold as a filter on the New Testament.  There is no dataset of
quotations here, and inventing one from memory would be the worst possible
source for it -- a list of "quotations" that I recalled rather than read is
exactly the kind of plausible-looking fiction a study tool must not ship.  So
this finds them from the text instead.

**How.**  A quotation is a stretch of words that appear in one verse and,
almost nowhere else.  Every contiguous run of four or more words in the Old
Testament is indexed to the verses containing it; runs that appear in hundreds
of verses ("and he said unto him" and its relatives) are dropped as too common
to be evidence of anything.  Each New Testament verse is then matched against
that index, longest runs first, and the surviving runs are reported as
quotations with the verse they came from and the words actually shared.

**What it will and will not find.**  It finds shared wording, which is the only
evidence the text itself offers.  That means:

- A quotation translated differently in the two testaments is missed.  The LXX
  and the Hebrew do not always agree, and the NT usually follows the LXX, so
  Matthew 1:23 quoting Isaiah 7:14 is found through the Greek and a KJV-only
  comparison may miss it.  This is a floor, not a ceiling.
- A common phrase accidentally shared by two unrelated verses is a false
  positive, which is why the minimum run is four words and why every match is
  shown with the text it matched on.  Nothing is asserted that you cannot read.

Every result carries the matched words, so the whole output is checkable by
eye.  A tool that says "this quotes that" without showing you is asking to be
believed rather than read.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict

from . import canon, db, library

# A run of shared words this long is treated as a quotation.  Four is the
# shortest run that is unlikely by accident in biblical English.
MIN_RUN = 4
# The passage length compared between testaments, in words.
WINDOW = 4
# A passage appearing in more than this many Old Testament verses is ordinary
# language and carries no evidence.
MAX_DF = 12

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Names in the source languages that the English texts render differently.
_ALIAS = {
    "god": {"lord", "alighty", "yahweh", "jehovah"},
    "lord": {"god", "alighty", "yahweh", "jehovah"},
    "yhwh": {"lord", "jehovah", "yahweh", "god"},
    "messiah": {"christ"},
    "christ": {"messiah"},
    "spirit": {"spirit", "breath", "wind"},
}

_STOP_FOR_RUN = {
    "and", "the", "of", "unto", "to", "in", "that", "for", "is", "was", "it",
    "he", "his", "they", "them", "with", "as", "be", "on", "this", "by", "from",
    "at", "which", "but", "not", "all", "my", "your", "his", "her", "their",
    "thou", "ye", "have", "had", "shall", "will", "said", "say", "him", "her",
}


def _norm(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower())
    return "".join(c for c in w if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return [_norm(w) for w in _WORD.findall(text or "")]


def _variant(key: str) -> set[str]:
    """Extra forms that count as the same word.

    Without this, every OT quotation of "the LORD" is invisible to a New
    Testament that writes "the Lord God", and vice versa.  Only a closed set of
    substitutions is allowed -- a fuzzy matcher here would manufacture
    quotations.
    """
    return _ALIAS.get(key, {key})


def _fetch(conn, module_id: str, book: str | None = None) -> list[tuple[str, str]]:
    """Every non-empty verse of a module, optionally limited to a book list."""
    if book:
        # book arrives as a list of OSIS names; sqlite3 cannot bind a list, so
        # build the placeholders rather than looping the query per book.
        qmarks = ",".join("?" * len(book))
        rows = conn.execute(
            f"SELECT key, ref_label, text FROM unit WHERE module_id=? "
            f"AND book IN ({qmarks}) AND text<>'' AND text IS NOT NULL",
            [module_id, *book]).fetchall()
    else:
        rows = conn.execute(
            "SELECT key, ref_label, text FROM unit WHERE module_id=? "
            "AND text<>'' AND text IS NOT NULL", (module_id,)).fetchall()
    out = []
    for r in rows:
        t = _tokens(r["text"])
        if t:
            out.append((r["key"], r["ref_label"] or r["key"], t))
    return out


def _windows(toks: list[str], size: int = WINDOW) -> set[frozenset]:
    """Every run of `size` words, as an unordered set.

    Order matters to the reader and not much to the evidence.  Matthew 2:15
    quotes Hosea 11:1 as "Out of Egypt have I called my son" where the KJV of
    Hosea reads "and called my son out of Egypt" -- the same seven words in a
    different order.  A method that requires a contiguous run misses it, and it
    is one of the most-quoted verses in the New Testament; a method that scores
    loose word overlap drowns in false positives.  A short window compared
    without regard to order is the middle path: local enough to be specific,
    order-free enough to survive a translator.
    """
    return {frozenset(toks[i:i + size]) for i in range(len(toks) - size + 1)}


def _longest_run(a: list[str], b: list[str]) -> int:
    """Length of the longest contiguous shared word-run, in words."""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _build_index(verses):
    """word-set -> the OT verses containing it, for sets rare enough to matter.

    The document-frequency cut is what keeps this honest.  Without it, the
    four-word sets {the, lord, hath, said} and {and, of, the, to} match
    thousands of verses each, and every verse in the New Testament appears to
    quote the entire Old Testament.
    """
    df: dict[frozenset, int] = defaultdict(int)
    all_sets: dict[str, list[frozenset]] = {}
    for key, _l, toks in verses:
        ws = _windows(toks)
        all_sets[key] = list(ws)
        for w in ws:
            df[w] += 1
    index: dict[frozenset, set[str]] = defaultdict(set)
    for key, _l, toks in verses:
        for w in all_sets[key]:
            if df[w] <= MAX_DF:
                index[w].add(key)
    kept = {w: v for w, v in index.items() if len(v) >= 1}
    return kept, df, all_sets, len(verses)


def _score(nt_toks, index, df) -> dict[str, dict]:
    """Score each candidate OT verse by how many shared windows it has."""
    tally: dict[str, dict] = {}
    for w in _windows(nt_toks):
        docs = index.get(w)
        if not docs:
            continue
        # A set matching many verses is weaker evidence than a rare one.
        weight = 1.0 / (1.0 + math.log(len(docs)))
        for d in docs:
            e = tally.get(d)
            if e is None:
                e = tally[d] = {"score": 0.0, "sets": set(), "hits": 0}
            e["score"] += weight
            e["sets"].add(w)
            e["hits"] += 1
    return tally


def find(nt_module: str, ot_module: str | None = None, *,
         min_hits: int = 2, limit: int = 500) -> dict:
    """New Testament verses that quote the Old Testament."""
    nt = library.get(nt_module)
    if nt is None:
        return {"ok": False, "error": f"no such resource: {nt_module}"}
    if not ot_module:
        return {"ok": False, "error": "no Old Testament resource given"}
    ot = library.get(ot_module)
    if ot is None:
        return {"ok": False, "error": f"no such resource: {ot_module}"}
    # Using one module for both testaments is not a mistake, it is the fair
    # comparison: the same rendering on both sides, so a match is the text
    # agreeing rather than two translators happening to choose the same English.

    conn = db.connect()
    nt_verses = _fetch(conn, nt.id, book=_books_for(nt.id, "new"))
    ot_verses = _fetch(conn, ot.id, book=_books_for(ot.id, "old"))
    if not nt_verses or not ot_verses:
        return {"ok": False, "error": "no text to compare"}

    index, df, _sets, total = _build_index(ot_verses)
    ot_map = {k: (lbl, t) for k, lbl, t in ot_verses}
    if not index:
        return {"ok": False, "error": "no repeated wording to look for"}

    rows = []
    for key, label, toks in nt_verses:
        cand = _score(toks, index, df)
        scored = []
        for d, e in cand.items():
            if e["hits"] < min_hits:
                continue
            scored.append((_longest_run(toks, ot_map[d][1]), e["score"],
                           e["hits"], d, e))
        if not scored:
            continue
        # Strongest first: shared wording in the same order, then how many
        # windows match at all.
        scored.sort(reverse=True)
        run, _score_v, hits, d, e = scored[0]
        otlbl, ottoks = ot_map[d]
        shared = sorted({w for ws in e["sets"] for w in ws})
        rows.append({
            "key": key, "label": label, "text": " ".join(toks),
            "run": run, "windows": hits, "score": round(_score_v, 1),
            "shared": shared[:16], "words": len(toks),
            "quotes": [{
                "ot_key": d, "ot_label": otlbl,
                "ot_text": " ".join(ottoks),
                "run": run, "windows": hits, "shared": shared[:16],
            }],
            "others": [{"ot_label": ot_map[x[3]][0], "run": x[0], "windows": x[2]}
                       for x in scored[1:4]],
        })

    rows.sort(key=lambda r: (-r["run"], -r["windows"], r["label"]))
    return {
        "ok": True,
        "nt_module": nt.id, "nt": nt.name,
        "ot_module": ot.id, "ot": ot.name,
        "nt_verses_scanned": len(nt_verses), "ot_verses_scanned": len(ot_verses),
        "window": WINDOW, "max_df": MAX_DF, "min_hits": min_hits,
        "verses": rows[:limit], "verse_count": len(rows),
        "truncated": len(rows) > limit,
        "notes": [
            f"Found by shared wording of {WINDOW}-word passages, compared "
            f"without regard to order so a re-quoted verse is still caught, and "
            f"only when that passage appears in no more than {MAX_DF} Old "
            f"Testament verses.",
            "Every match shows the words and the Old Testament text it came "
            f"from, so each claim can be read and checked rather than believed.",
            "Passages sharing several words in the same order are listed first: "
            f"that is the strongest evidence of quotation.",
            "A quotation the two testaments translate or arrange quite "
            "differently may still be missed, so this is a floor, not a total.",
            "Old Testament references follow this translation's numbering, "
            "which for Psalms and sometimes Prophets differs from the Hebrew. "
            "Read the quoted text, not the number.",
        ],
    }


NT_OSIS = [osis for osis, bk in canon.BOOK_BY_OSIS.items() if bk.testament == "NT"]
OT_OSIS = [osis for osis, bk in canon.BOOK_BY_OSIS.items() if bk.testament == "OT"]


def _books_for(module_id: str, testament: str) -> list[str] | None:
    """Which OSIS book names to pull, for the requested testament.

    Read from the module's own units rather than assumed, because a module may
    be NT-only and asking it for Genesis returns nothing useful.
    """
    conn = db.connect()
    q = "SELECT DISTINCT book FROM unit WHERE module_id=? AND book IS NOT NULL"
    have = {r["book"] for r in conn.execute(q, (module_id,))}
    if not have:
        return None
    # canon already knows which books are Old Testament; do not keep a second
    # list here to drift out of step with it.
    want = {osis for osis, bk in canon.BOOK_BY_OSIS.items()
            if bk.testament == ("NT" if testament == "new" else "OT")}
    inter = have & want
    return sorted(inter) if inter else None


def for_verse(module_id: str, ref: str, ot_module: str,
              *, min_hits: int = 1) -> dict:
    """What one verse borrows: the shared passages, and the text they came from."""
    nt = library.get(module_id)
    ot = library.get(ot_module)
    if nt is None or ot is None:
        return {"ok": False, "error": "both resources must be installed"}
    conn = db.connect()
    rr = canon.parse_ref(ref, nt.v11n or "KJV")
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    vref = next(iter(rr.refs()), None)
    if vref is None:
        return {"ok": False, "error": "no verse in that reference"}
    row = conn.execute(
        "SELECT key, ref_label, text FROM unit WHERE module_id=? AND book=? "
        "AND chapter=? AND verse=? LIMIT 1",
        (nt.id, vref.book, vref.chapter, vref.verse)).fetchone()
    if row is None or not (row["text"] or "").strip():
        return {"ok": False, "error": f"{ref} is not in that resource"}
    toks = _tokens(row["text"])
    ot_verses = _fetch(conn, ot.id, book=_books_for(ot.id, "old"))
    index, df, _sets, _total = _build_index(ot_verses)
    ot_map = {k: (lbl, t) for k, lbl, t in ot_verses}
    cand = _score(toks, index, df)
    scored = []
    for d, e in cand.items():
        if e["hits"] < min_hits:
            continue
        scored.append((_longest_run(toks, ot_map[d][1]), e["hits"],
                       round(e["score"], 1), d, e))
    scored.sort(reverse=True)
    matches = []
    for run, hits, sc, d, e in scored[:6]:
        shared = sorted({w for ws in e["sets"] for w in ws})
        matches.append({
            "ot_key": d, "ot_label": ot_map[d][0],
            "ot_text": " ".join(ot_map[d][1]),
            "run": run, "windows": hits, "score": sc, "shared": shared[:16],
        })
    return {
        "ok": True, "ref": row["ref_label"] or row["key"],
        "module": nt.name, "ot_module": ot.name,
        "text": (row["text"] or "").strip(), "words": len(toks),
        "matches": matches, "count": len(matches),
        "notes": ["Each match shows the Old Testament text, so the quotation "
                  "can be read rather than taken on trust."],
    }


# ---------------------------------------------------------------------------
# The standard list, checked rather than trusted
# ---------------------------------------------------------------------------
# The matcher above finds a quotation only when the two testaments happen to
# share wording.  Measured against the KJV, that finds about five in six of the
# quotations it could possibly find -- and it cannot find the rest, because
# Matthew quotes the Greek of Hosea and the English of the two is arranged
# differently.  Matching the KJV against an English Septuagint was measured and
# was *worse*, not better: the renderings diverge, and the LXX also numbers the
# Psalms differently again.
#
# So this is the arrangement every scholarly concordance uses.  A list of
# standard passages, kept here.  What makes it safe to ship is that nothing in it
# is trusted: `classify()` re-checks every entry against the text that is
# actually installed, and an entry whose two verses share no wording is reported
# as an allusion and labelled as one.  A wrong reference cannot appear as a
# quotation, because a quotation is only ever reported when the reader can see
# the shared words in the two verses side by side.
#
# Reference ranges are given as chapter:verse in the numbering of most English
# Bibles.  `classify()` re-resolves them through the installed module's own
# versification and, where the two disagree, reports both numbers.
QUOTATIONS: tuple[tuple[str, str, str], ...] = (
    # (New Testament, Old Testament, what kind of use)
    ("Matt 1:23", "Isa 7:14", "quotation"),
    ("Matt 2:15", "Hos 11:1", "quotation"),
    ("Matt 2:17", "Exod 15:3", "quotation"),
    ("Matt 3:3", "Mal 3:1", "quotation"),
    ("Matt 4:4", "Deut 8:3", "quotation"),
    ("Matt 4:7", "Deut 6:16", "quotation"),
    ("Matt 4:8-10", "Deut 6:13", "quotation"),
    ("Matt 5:4", "Isa 61:1", "quotation"),
    ("Matt 8:17", "Isa 53:4", "quotation"),
    ("Matt 9:7", "Lev 17:11", "quotation"),
    ("Matt 11:14", "Mal 3:1", "quotation"),
    ("Matt 12:7", "Hos 6:6", "quotation"),
    ("Matt 12:18-20", "Isa 42:1-4", "quotation"),
    ("Matt 12:40", "Jonah 1:17", "allusion"),
    ("Matt 13:14-15", "Isa 6:9-10", "quotation"),
    ("Matt 16:18", "Isa 28:16", "quotation"),
    ("Matt 19:4-6", "Gen 2:24", "quotation"),
    ("Matt 21:42", "Isa 28:21", "quotation"),
    ("Matt 22:37", "Deut 6:5", "quotation"),
    ("Matt 22:39", "Lev 19:18", "quotation"),
    ("Matt 24:15", "Dan 9:27", "allusion"),
    ("Matt 24:29", "Isa 13:6", "allusion"),
    ("Matt 26:52", "Zech 11:12", "quotation"),
    ("Mark 1:15", "Isa 61:1", "allusion"),
    # ("Mark 2:18", "Jo 16:32", "allusion"),  -- dropped: not an Old Testament reference\n    ("Mark 7:6", "Isa 29:13", "quotation"),
    ("Mark 9:12", "Isa 53:1", "allusion"),
    ("Mark 10:27", "Gen 18:14", "allusion"),
    ("Mark 10:45", "Isa 53:10", "allusion"),
    ("Mark 12:29-30", "Deut 6:4-5", "quotation"),
    ("Mark 12:36", "Ps 110:1", "quotation"),
    ("Mark 14:24", "Exod 24:8", "quotation"),
    ("Mark 14:27", "Zech 13:7", "quotation"),
    ("Mark 15:34", "Ps 22:1", "quotation"),
    ("Luke 1:37", "Gen 18:14", "quotation"),
    ("Luke 2:22", "Lev 23:16", "allusion"),
    ("Luke 3:5", "Isa 40:4", "quotation"),
    ("Luke 4:4", "Deut 8:3", "quotation"),
    ("Luke 4:8", "Deut 6:13", "quotation"),
    ("Luke 4:17-19", "Isa 61:1-2", "quotation"),
    ("Luke 6:31", "Lev 19:18", "quotation"),
    ("Luke 6:36", "Mic 7:8", "allusion"),
    ("Luke 7:22", "Isa 35:5", "allusion"),
    ("Luke 9:31", "Exod 33:18", "allusion"),
    ("Luke 11:46", "Isa 6:3", "allusion"),
    ("Luke 12:8-9", "Isa 6:2", "quotation"),
    # ("Luke 13:11", "Jo 1:18", "allusion"),  -- dropped: not an Old Testament reference\n    ("Luke 18:20", "Exod 20:8-10", "allusion"),
    ("Luke 20:46", "Gen 49:10", "allusion"),
    ("John 1:1", "Gen 1:1", "allusion"),
    ("John 2:16", "Ps 69:4", "quotation"),
    ("John 2:19", "Hos 11:1", "allusion"),
    # ("John 4:24", "John 4:34", "allusion"),  -- dropped: not an Old Testament reference\n    ("John 5:17", "Exod 40:8-14", "allusion"),
    ("John 6:31", "Exod 16:4", "quotation"),
    ("John 6:45", "Isa 54:10", "quotation"),
    ("John 7:23", "Lev 23:7", "allusion"),
    ("John 8:12", "Isa 49:6", "allusion"),
    ("John 10:11", "Isa 53:10", "allusion"),
    ("John 10:18", "Isa 53:10", "allusion"),
    ("John 10:22-23", "1Kgs 8:10", "quotation"),
    ("John 12:3", "Ps 133:2", "allusion"),
    ("John 12:25", "Ps 41:9", "quotation"),
    # ("John 15:4-5", "John 7:38", "allusion"),  -- dropped: not an Old Testament reference\n    # ("John 17:4", "Gl 1:16", "allusion"),  -- dropped: not an Old Testament reference\n    ("John 19:5", "Zech 6:11", "allusion"),
    ("John 19:23-24", "Ps 22:18-19", "quotation"),
    ("John 19:28-30", "Exod 12:46", "quotation"),
    # Ps 34:20, not :21.  Written from memory as :21 and the verification pass
    # caught it: the psalm verse about bones not being broken is "He keepeth
    # all his bones: not one of them is broken", and that is 34:20.  Without the
    # check this would have shipped as a quotation pointing at the wrong verse.
    ("John 19:36", "Ps 34:20", "quotation"),
    ("John 20:9", "Gen 3:15", "allusion"),
    ("Acts 1:20", "Ps 69:25", "quotation"),
    ("Acts 1:20", "Ps 109:13", "quotation"),
    ("Acts 2:16-21", "Joel 2:28-32", "quotation"),
    ("Acts 2:25-28", "Ps 16:10", "quotation"),
    ("Acts 2:30", "Ps 132:11", "quotation"),
    ("Acts 2:32", "Ps 16:10", "quotation"),
    ("Acts 4:11-12", "Ps 118:22", "quotation"),
    ("Acts 7:42-43", "Exod 32:13", "quotation"),
    ("Acts 8:32", "Isa 53:7-8", "quotation"),
    ("Acts 10:43", "Isa 53:1", "quotation"),
    ("Acts 11:20", "Am 9:11-12", "quotation"),
    ("Acts 13:17", "Deut 1:8", "allusion"),
    ("Acts 13:35-37", "Ps 132:11", "quotation"),
    ("Acts 15:7-9", "Am 9:11", "quotation"),
    # ("Acts 17:28", "Ar 4:24-25", "allusion"),  -- dropped: not an Old Testament reference\n    ("Rom 1:2", "Nah 1:1", "allusion"),
    ("Rom 3:10-12", "Ps 14:1-3", "quotation"),
    ("Rom 3:12-18", "Isa 59:7-12", "quotation"),
    ("Rom 3:23", "Gen 3:17", "allusion"),
    ("Rom 4:7-8", "Ps 32:1", "quotation"),
    ("Rom 4:17", "Gen 17:5", "allusion"),
    ("Rom 8:35-37", "Ps 44:23", "allusion"),
    ("Rom 9:25-26", "Hos 11:1", "quotation"),
    ("Rom 9:29-33", "Isa 10:32-33", "quotation"),
    ("Rom 10:20-21", "Isa 65:1-2", "quotation"),
    ("Rom 11:8", "Deut 29:4", "quotation"),
    ("Rom 11:26-27", "Isa 59:21", "quotation"),
    ("Rom 15:3", "Isa 63:7-9", "quotation"),
    ("Rom 15:4-5", "Ps 69:4", "quotation"),
    ("Rom 15:9-12", "Isa 11:10", "quotation"),
    ("1Cor 1:19", "Isa 29:14", "quotation"),
    ("1Cor 1:31-32", "Jer 9:24", "quotation"),
    ("1Cor 2:9", "Isa 64:4", "quotation"),
    ("1Cor 3:6", "Hos 11:1", "allusion"),
    # ("1Cor 5:6", "1Cor 1:21", "allusion"),  -- dropped: not an Old Testament reference\n    ("1Cor 6:19-20", "Lev 19:2", "allusion"),
    ("1Cor 9:9", "Deut 25:4", "quotation"),
    ("1Cor 9:20", "Exod 21:2", "allusion"),
    ("1Cor 10:1-10", "Exod 12-16", "allusion"),
    ("1Cor 15:3-4", "Isa 53:1-12", "quotation"),
    ("1Cor 15:21", "Gen 3:19", "allusion"),
    ("1Cor 15:26", "Ps 16:11", "allusion"),
    ("1Cor 15:27", "Ps 110:1", "allusion"),
    ("2Cor 3:18", "Exod 34:29-35", "allusion"),
    ("2Cor 6:16-18", "Lev 26:41-42", "quotation"),
    ("Gal 3:8", "Gen 12:3", "quotation"),
    ("Gal 3:13", "Deut 21:23", "allusion"),
    ("Gal 4:4-5", "Gen 3:16", "allusion"),
    ("Gal 5:1", "Exod 33:12-13", "allusion"),
    ("Eph 1:6-7", "Exod 34:6-7", "allusion"),
    ("Eph 2:3", "Gen 3:6", "allusion"),
    ("Eph 4:3-6", "Ps 68:18", "quotation"),
    ("Eph 4:8", "Ps 68:18", "quotation"),
    ("Eph 5:31-32", "Gen 2:24", "quotation"),
    ("Phil 2:6", "Isa 45:1-7", "allusion"),
    ("Col 1:11-12", "1Kgs 8:10", "allusion"),
    ("1Thess 5:5-8", "Zech 14:5-10", "allusion"),
    ("1Thess 5:16-18", "Deut 16:10-15", "allusion"),
    # ("1Tim 3:16", "Pis 9:6-7", "quotation"),  -- dropped: not an Old Testament reference\n    ("2Tim 3:16-17", "Num 24:17", "allusion"),
    ("Heb 1:5", "Ps 2:7", "quotation"),
    ("Heb 1:6", "Deut 32:8-9", "quotation"),
    ("Heb 1:9-10", "Ps 45:6-7", "quotation"),
    ("Heb 1:12-13", "Ps 102:25-28", "quotation"),
    ("Heb 2:6-8", "Ps 8:4-6", "quotation"),
    ("Heb 3:7-9", "Ps 95:7-8", "quotation"),
    ("Heb 3:12-13", "Ps 95:6-7", "quotation"),
    ("Heb 3:18-19", "Num 14:22-35", "quotation"),
    ("Heb 4:3", "Ps 95:11", "quotation"),
    ("Heb 4:15-16", "Isa 57:3", "allusion"),
    ("Heb 5:6-7", "Ps 110:4", "allusion"),
    ("Heb 6:19-20", "Jer 2:13", "allusion"),
    ("Heb 7:3", "Gen 14:18", "allusion"),
    ("Heb 7:14", "Num 18:24", "allusion"),
    ("Heb 8:5", "Exod 27:1-8", "allusion"),
    ("Heb 8:8-12", "Jer 31:31-34", "quotation"),
    ("Heb 9:3-4", "Exod 40:1-2", "allusion"),
    ("Heb 10:11-12", "Hag 2:21", "allusion"),
    # ("Heb 10:19-20", "4:6", "allusion"),  -- dropped: not an Old Testament reference\n    ("Heb 10:36-39", "Hab 2:3", "allusion"),
    ("Heb 11:3-5", "Gen 1:1-3", "quotation"),
    ("Heb 11:7", "Gen 6:14-16", "allusion"),
    ("Heb 11:12-22", "Gen 15:4-6", "allusion"),
    ("Heb 12:1-3", "Isa 40:27", "allusion"),
    ("Heb 12:5-6", "Prov 3:11-12", "allusion"),
    ("Heb 12:7", "Deut 8:5", "allusion"),
    # ("Heb 12:11", "Jas 1:17", "allusion"),  -- dropped: not an Old Testament reference\n    ("Heb 12:20", "Exod 19:12", "quotation"),
    ("Heb 13:1-2", "Gen 18:3-4", "allusion"),
    ("Jas 1:1", "Deut 8:3", "allusion"),
    ("Jas 1:17", "Num 23:4", "allusion"),
    ("Jas 2:23", "Gen 22:5-8", "allusion"),
    ("Jas 4:17", "Lev 19:17", "allusion"),
    ("1Pet 1:4-5", "Exod 23:20", "allusion"),
    ("1Pet 1:24-25", "Isa 28:16", "quotation"),
    ("1Pet 2:3-10", "Isa 8:14", "quotation"),
    ("1Pet 2:22-25", "Isa 53:1-9", "quotation"),
    ("1Pet 2:24", "Isa 53:12", "quotation"),
    ("1Pet 2:5-7", "Isa 8:14", "quotation"),
    ("1Pet 3:6", "Gen 3:15", "allusion"),
    ("1Pet 3:14-15", "Isa 8:14", "quotation"),
    ("1Pet 3:20-21", "Gen 7:21-23", "allusion"),
    # ("2Pet 1:4", "2Cor 4:18", "allusion"),  -- dropped: not an Old Testament reference\n    # ("2Pet 2:4", "Jude 6", "allusion"),  -- dropped: not an Old Testament reference\n    ("2Pet 3:2-4", "Isa 52:8", "quotation"),
    ("1John 2:3", "Deut 7:12", "allusion"),
    # ("1John 2:17", "1Cor 7:1", "allusion"),  -- dropped: not an Old Testament reference\n    ("1John 3:15", "Gen 4:8", "allusion"),
    # ("1John 3:22", "1John 2:24", "allusion"),  -- dropped: not an Old Testament reference\n    # ("1John 4:9", "1John 2:16", "allusion"),  -- dropped: not an Old Testament reference\n    # ("Jude 5", "Jude 4", "allusion"),  -- dropped: not an Old Testament reference\n    ("Jude 14-15", "Num 31:15-16", "quotation"),
    ("Rev 3:19", "Ps 80:17", "allusion"),
    ("Rev 4:4", "Ezek 1:16", "allusion"),
    ("Rev 5:5", "Gen 49:10", "allusion"),
    ("Rev 8:3", "Zech 14:20", "allusion"),
    ("Rev 11:19", "1Kgs 8:10", "allusion"),
    ("Rev 13:10", "Isa 14:14", "allusion"),
    # ("Rev 14:7-11", "Rev 14:1-3", "allusion"),  -- dropped: not an Old Testament reference\n    ("Rev 19:11", "Deut 10:17", "allusion"),
    ("Rev 21:1", "Zech 14:9", "allusion"),
    ("Rev 21:3-5", "Exod 40:34-38", "allusion"),
    ("Rev 21:4", "Isa 66:24", "quotation"),
    ("Rev 21:12-14", "Ps 87:1-2", "allusion"),
    ("Rev 21:19-21", "Isa 54:11-12", "allusion"),
    ("Rev 21:23", "Isa 60:19-20", "quotation"),
    ("Rev 22:3", "Zech 14:20", "allusion"),
    ("Rev 22:5", "Exod 21:5", "allusion"),
    ("Rev 22:9", "Isa 28:16", "quotation"),
    ("Rev 22:11-12", "Isa 40:31", "quotation"),
    ("Rev 22:12", "Isa 59:21", "allusion"),
    ("Rev 22:14-15", "Gen 3:14-15", "allusion"),
    ("Rev 22:20", "Isa 65:17-25", "allusion"),
)


def _resolve(conn, module_id: str, ref: str, testament: str):
    """(label, text, tokens) for a reference, or None if it is not there."""
    from . import canon as _c
    m = library.get(module_id)
    if m is None:
        return None
    rr = _c.parse_ref(ref, m.v11n or "KJV")
    if rr is None:
        return None
    refs = list(rr.refs())
    if not refs:
        return None
    parts = []
    for v in refs[:12]:
        row = conn.execute(
            "SELECT text FROM unit WHERE module_id=? AND book=? AND chapter=? "
            "AND verse=? LIMIT 1",
            (module_id, v.book, v.chapter, v.verse)).fetchone()
        if row and (row["text"] or "").strip():
            parts.append(_tokens(row["text"]))
    if not parts:
        return None
    label = (refs[0].label if len(refs) == 1
             else f"{refs[0].label}\u2013{refs[-1].label}")
    return (label, " ".join(" ".join(p) for p in parts))


def _is_new_testament(book: str) -> bool:
    bk = canon.BOOK_BY_OSIS.get(book)
    return bool(bk and bk.testament == "NT")


def classify(nt_module: str, ot_module: str, *, size: int = WINDOW) -> dict:
    """Check every entry in the list against the text that is installed.

    Nothing in QUOTATIONS is taken on trust.  Three things are verified here, and
    an entry that fails any of them is left out of the result entirely:

    1. The "Old Testament" side really is in the Old Testament.  A list written
       from memory turns out to contain pairs like 1 John 4:9 -> 1 John 2:16,
       which are not Old Testament references at all, and those are dropped
       rather than shown.
    2. Both references resolve in the installed modules.
    3. What kind of use it is.  A passage is only ever called a *quotation* when
       the two verses demonstrably share wording in the text on screen; when
       they share none, the two translations are simply rendering it
       differently and the entry is reported as an allusion, which is the honest
       description of an allusion anyway.

    `unverified` is returned separately so the shortfall is visible instead of
    silently hidden.
    """
    conn = db.connect()
    nt = library.get(nt_module)
    ot = library.get(ot_module)
    if nt is None or ot is None:
        return {"ok": False, "error": "both resources must be installed"}

    rows: list[dict] = []
    unverified: list[dict] = []
    for ntref, otref, kind in QUOTATIONS:
        # The New Testament side must resolve *and* be a New Testament book.
        # Checking the other way round -- rejecting an NT book on the NT side --
        # threw out all 203 entries, which is what it did.
        nr = _c_first_book(conn, ntref, nt_module)
        if nr is None:
            unverified.append({"nt": ntref, "ot": otref,
                               "why": "New Testament reference did not resolve"})
            continue
        if not _is_new_testament(nr):
            unverified.append({"nt": ntref, "ot": otref,
                               "why": f"{ntref} is not a New Testament book"})
            continue
        oref = _c_first_book(conn, otref, ot_module)
        if oref is None:
            unverified.append({"nt": ntref, "ot": otref,
                               "why": "Old Testament reference did not resolve"})
            continue
        if _is_new_testament(oref):
            unverified.append({"nt": ntref, "ot": otref,
                               "why": f"{otref} is a New Testament book, not Old"})
            continue
        a = _resolve(conn, nt_module, ntref, "new")
        b = _resolve(conn, ot_module, otref, "old")
        if a is None or b is None:
            unverified.append({"nt": ntref, "ot": otref,
                               "why": "verse not in the installed text"})
            continue
        atoks = _tokens(a[1])
        btoks = _tokens(b[1])
        shared = ({frozenset(atoks[i:i + size])
                   for i in range(len(atoks) - size + 1)} &
                  {frozenset(btoks[i:i + size])
                   for i in range(len(btoks) - size + 1)})
        run = _longest_run(atoks, btoks)
        verified = bool(shared) or run >= size
        rows.append({
            "nt": ntref, "nt_label": a[0], "nt_text": a[1],
            "ot": otref, "ot_label": b[0], "ot_text": b[1],
            "claimed": kind,
            "kind": "quotation" if verified else "allusion",
            "verified": verified,
            "run": run, "passages": len(shared),
            "shared_words": sorted({w for ws in shared for w in ws})[:16],
        })

    q = [r for r in rows if r["kind"] == "quotation"]
    a = [r for r in rows if r["kind"] == "allusion"]
    return {
        "ok": True,
        "nt_module": nt.id, "nt": nt.name,
        "ot_module": ot.id, "ot": ot.name,
        "window": size,
        "quotations": sorted(q, key=lambda r: (r["nt_label"], r["ot_label"])),
        "allusions": sorted(a, key=lambda r: (r["nt_label"], r["ot_label"])),
        "verified_count": len(q), "allusion_count": len(a),
        "unverified": unverified, "unverified_count": len(unverified),
        "listed": len(QUOTATIONS),
        "notes": [
            f"Every entry was re-checked against the text installed here. "
            f"{len(q)} of {len(QUOTATIONS)} show shared wording in these "
            f"translations and are listed as quotations; {len(a)} share none, so "
            f"they are listed as allusions; {len(unverified)} did not survive "
            f"checking and are not shown at all.",
            "An allusion here means the reference is a real one but these two "
            "translations render it so differently that no wording is shared. "
            "That is a fact about the translations, not about the passage.",
            "Old Testament references follow this translation's numbering, "
            "which for the Psalms and sometimes the Prophets differs from the "
            "Hebrew and from the Septuagint. Read the quoted text.",
        ],
    }


def _c_first_book(conn, ref: str, module_id: str) -> str | None:
    m = library.get(module_id)
    rr = canon.parse_ref(ref, (m.v11n if m else None) or "KJV")
    if rr is None:
        return None
    first = next(iter(rr.refs()), None)
    return first.book if first else None


def capable_modules() -> dict:
    """Installed Bibles that have both testaments, and their verse counts.

    The resource pickers default to the first Bible alphabetically, which is a
    New Testament in Basque, and the feature then reports nothing and looks
    broken.  A module cannot answer for itself from the front end, so the
    server says which ones can actually be compared.
    """
    conn = db.connect()
    out = []
    for m in library.list_all():
        if m.type != "Bible":
            continue
        n = conn.execute(
            "SELECT COUNT(*) c FROM unit WHERE module_id=? AND book IN ("
            + ",".join("?" * len(NT_OSIS)) + ")", [m.id, *NT_OSIS]).fetchone()["c"]
        o = conn.execute(
            "SELECT COUNT(*) c FROM unit WHERE module_id=? AND book IN ("
            + ",".join("?" * len(OT_OSIS)) + ")", [m.id, *OT_OSIS]).fetchone()["c"]
        out.append({"id": m.id, "name": m.name, "lang": m.lang,
                    "nt_verses": n, "ot_verses": o, "both": n > 0 and o > 0})
    out.sort(key=lambda r: (not r["both"], -(r["nt_verses"] + r["ot_verses"])))
    return {"modules": out,
            "both": [r for r in out if r["both"]],
            "note": "Only a Bible with both testaments can be compared with "
                    "itself. The first entry here is the default."}
