"""The reader's own material: notes, highlights and clippings.

Everything in here belongs to the reader and to nobody else.  The notes they
wrote, the passages they marked, the excerpts they gathered.  None of it is an
installed resource, so none of it is in the search engine's corpus, and before
this module existed the assistant could not see any of it: it answered from the
library alone, which means it could not answer the question a reader is most
likely to ask their own Bible software -- *what did I think about this?*

Why a separate module rather than a new scope in the search engine
--------------------------------------------------------------------
The search engine ranks published material: millions of units, a positional
index, a full-text table, a query language.  The reader's own material is a
different corpus answering a different question.  "What does the Bible say
about faith" wants the best commentary; "what did I write about faith" wants
the reader's own words, and would be badly served by a ranking tuned to find
scholarship.  So the two are retrieved separately, ranked separately, and
merged afterwards -- with the reader's own material *marked* as theirs all the
way to the answer, because a private note and a published commentary are not
the same kind of thing and a reader must never be left guessing which is
which.

What is in here
---------------
  * **notes** -- the `note` table: notes, journal entries, sermons, prayers
  * **highlights** -- the `highlight` table: passages the reader marked
  * **clippings** -- excerpts the reader gathered, with their source and ref

Notebooks are deliberately *not* here.  A notebook is a view over notes (a
kind, a tag or a query), so the notes it holds are already in the corpus and
are found there.  Counting them twice would answer the same question twice.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter

from . import db


#: What each kind of the reader's own material is called in a citation.  It
#: says *whose* it is, because the whole point of keeping it apart from the
#: library is that the reader can tell the two apart.
_KIND_NAMES = {
    "note": "my note",
    "journal": "my journal",
    "sermon": "my sermon",
    "prayer": "my prayer",
    "highlight": "my highlight",
    "clipping": "my clipping",
}


# ==========================================================================
# The corpus
# ==========================================================================

def _tags(raw) -> list[str]:
    """The tag list of a note, or nothing when it has none or is unreadable."""
    try:
        v = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(t) for t in v] if isinstance(v, list) else []


def _notes(keys: list[str] | None = None) -> list[dict]:
    """The `note` table: notes, journal entries, sermons and prayer lists.

    `keys`, when given, restricts the result to the notes anchored to those
    units.  See `anchored_sources`.
    """
    sql = ("SELECT id,kind,title,body,module_id,unit_key,ref_label,tags,"
           "created_at,updated_at FROM note")
    a: list = []
    if keys is not None:
        if not keys:
            return []
        sql += f" WHERE unit_key IN ({','.join('?' * len(keys))})"
        a = list(keys)
    try:
        rows = db.connect().execute(sql, a).fetchall()
    except Exception:                                    # noqa: BLE001
        return []
    out: list[dict] = []
    for r in rows:
        title = (r["title"] or "").strip()
        body = (r["body"] or "").strip()
        if not title and not body:
            continue
        kind = r["kind"] or "note"
        out.append({
            "id": "note:" + r["id"],
            "own_id": r["id"],
            "kind": kind,
            "title": title or "(untitled)",
            "text": body or title,
            # A tag is often the only word that links a note to the subject it
            # is about: a note whose body is "see below" and whose tag is
            # "atonement" is found by the tag and by nothing else.
            "extra": " ".join(_tags(r["tags"])),
            "ref": r["ref_label"] or "",
            "module_id": r["module_id"] or "",
            "unit_key": r["unit_key"] or "",
            "when": r["updated_at"] or r["created_at"] or 0.0,
            # One note is one document, so it gets a folder of its own and
            # cannot be crowded out by anything else.
            "folder": "note:" + r["id"],
        })
    return out


def _highlights(keys: list[str] | None = None) -> list[dict]:
    """The passages the reader marked.

    A highlight is two things at once: the passage, which is somebody else's
    text, and the reader's decision to mark it, which is theirs.  The passage
    is what makes the highlight findable, and the note the reader attached is
    what makes it *theirs* -- so the note is kept with it and the model is
    told which is which.
    """
    sql = ("SELECT h.id,h.module_id,h.unit_key,h.quote,h.note,h.label,"
           "h.created_at,u.ref_label,m.name AS module_name "
           "FROM highlight h "
           "LEFT JOIN unit u ON u.module_id=h.module_id AND u.key=h.unit_key "
           "LEFT JOIN module m ON m.id=h.module_id")
    a: list = []
    if keys is not None:
        if not keys:
            return []
        sql += f" WHERE h.unit_key IN ({','.join('?' * len(keys))})"
        a = list(keys)
    try:
        rows = db.connect().execute(sql, a).fetchall()
    except Exception:                                    # noqa: BLE001
        return []
    out: list[dict] = []
    for r in rows:
        quote = (r["quote"] or "").strip()
        note = (r["note"] or "").strip()
        if not quote and not note:
            continue
        text = quote
        if note:
            text = (quote + "\n\n" if quote else "") + \
                   "The reader's own note on it: " + note
        label = r["ref_label"] or r["label"] or r["module_name"] or "a passage"
        out.append({
            "id": "highlight:" + r["id"],
            "own_id": r["id"],
            "kind": "highlight",
            "title": label,
            "text": text,
            "extra": " ".join(x for x in (r["label"], r["module_name"]) if x),
            "ref": r["ref_label"] or "",
            "module_id": r["module_id"] or "",
            "unit_key": r["unit_key"] or "",
            "when": r["created_at"] or 0.0,
            "folder": "highlight:" + r["id"],
        })
    return out


def _clippings() -> list[dict]:
    """The excerpts the reader gathered, with the source they came from.

    One document per *excerpt*, not per clipping.  A clipping is a folder and
    the folder is not what a question matches -- the excerpt is.  The heading
    still rides along, because "Sermon on faith" says what the excerpt was
    gathered *for*, and that is often the only thing that links it to a
    subject.
    """
    try:
        rows = db.get_setting("clippings", [])
    except Exception:                                    # noqa: BLE001
        return []
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for c in rows:
        if not isinstance(c, dict):
            continue
        heading = (c.get("heading") or "").strip() or "Clipping"
        cid = c.get("id") or ""
        for it in c.get("items") or []:
            if not isinstance(it, dict):
                continue
            quote = (it.get("quote") or "").strip()
            if not quote:
                continue
            iid = it.get("id") or ""
            out.append({
                "id": "clip:" + iid,
                "own_id": iid,
                "kind": "clipping",
                "title": heading,
                "text": quote,
                "extra": " ".join(x for x in (it.get("source"),
                                              it.get("ref")) if x),
                "ref": it.get("ref") or "",
                "module_id": it.get("module_id") or "",
                "unit_key": it.get("unit_key") or "",
                "when": it.get("added_at") or 0.0,
                # Every excerpt of one clipping shares a folder, so a single
                # clipping of forty excerpts cannot take every slot.
                "folder": "clip:" + cid,
            })
    return out


def documents() -> list[dict]:
    """Every piece of the reader's own material, as one flat list.

    The shape is the same for all three kinds -- a title, a body, a date, and
    enough identity to open it again -- because the caller should not have to
    know which of the three it is holding, and because the ranking below
    treats them alike.
    """
    return _notes() + _highlights() + _clippings()


def count() -> dict:
    """How much of the reader's own material there is, by kind.

    The settings screen shows this, because a toggle that says "include my own
    material" and then quietly includes nothing is a lie told by omission.
    """
    c = Counter(d["kind"] for d in documents())
    return {"total": sum(c.values()), "by_kind": dict(c)}


# ==========================================================================
# Material anchored to a passage
# ==========================================================================

def _verse_keys(ref: str) -> list[str]:
    """The unit keys of the verses a reference names.

    A Bible unit is keyed by its OSIS id and its place in the text
    ("John.3.16"), and that is the key the reader's note is anchored to, so
    the two meet here.
    """
    try:
        from . import canon
        rng = canon.parse_ref(ref or "")
    except Exception:                                    # noqa: BLE001
        return []
    if not rng:
        return []
    out: list[str] = []
    try:
        for r in rng.refs():
            if r.chapter and r.verse:
                out.append(r.osis_id())
    except Exception:                                    # noqa: BLE001
        return []
    return out


def anchored_sources(ref: str, limit: int = 3) -> list[dict]:
    """The reader's own material anchored to a passage.

    A note taken on a verse is *about* that verse, whatever words it uses.  A
    note that says "conditional immortality -- see Morris" shares no terms at
    all with the verse it was taken on, so a text search will never find it;
    the anchor is the only thing that connects the two.  Which is why the
    notes on a passage have to be found by the anchor and not by their words.

    This is the same distinction the sermon research draws between a passage
    as a *location* and a subject as a *question*: "explain this verse" is a
    location, and the reader's own writing on it is part of the place.
    """
    if not (ref or "").strip() or limit <= 0:
        return []
    keys = _verse_keys(ref)
    if not keys:
        return []
    docs = _notes(keys) + _highlights(keys)
    out: list[dict] = []
    for d in docs:
        c = _citation(d, 0.0)
        c["n"] = len(out) + 1
        out.append(c)
        if len(out) >= limit:
            break
    return out


# ==========================================================================
# The question
# ==========================================================================

#: Ordinary English function words.  They carry no meaning for a question
#: about a subject, and leaving them in would let them count against a
#: The ordinary English function words, from the tokenizer's own list: a note
#: that says "the" often would otherwise look like a better answer than the
#: one that says what it is about.
_STOP = db.STOP_WORDS

#: Words that describe the *request* rather than its subject.  "What did I
#: write in my notes about justification?" asks about justification; "write",
#: "notes" and "my" are the reader saying where to look, not what they are
#: looking for.  Left in, they match any document that happens to contain the
#: word "note" and pull it above the one that discusses the subject.
_REQUEST = {
    "my", "mine", "i", "me", "myself", "we", "our", "us", "you", "your",
    "note", "notes", "journal", "diary",
    "highlight", "highlights", "highlighted",
    "clip", "clips", "clipped", "clipping", "clippings",
    "wrote", "write", "written", "writing",
    "say", "says", "said", "tell", "told",
    "find", "show", "list", "give", "please", "recall", "remember",
    "about",
}

#: How many distinct content terms a question may contribute.  A long passage
#: used as a query -- the *explain* action grounds on the passage text -- would
#: otherwise flood the coverage score with terms nobody asked about.
_MAX_TERMS = 12


def _content_terms(question: str) -> list[str]:
    """The content words of a question, as folded-and-stemmed token keys.

    The same folding and stemming the search engine uses, so "faith" and
    "faithful" meet, and a note written in the reader's own words is found by
    a question that reaches for a different one.
    """
    words = [w for (w, _s, _e) in db.words(question or "")]
    kept = [w for w in words
            if w.lower() not in _STOP and w.lower() not in _REQUEST]
    if not kept:
        # A question made entirely of words we drop ("what did I write?")
        # still has to find something, so the request words are used after all.
        kept = [w for w in words if w.lower() not in _STOP]
    if not kept:
        kept = words
    out: list[str] = []
    seen: set[str] = set()
    for w in kept:
        k = db.token_key(w)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
            if len(out) >= _MAX_TERMS:
                break
    return out


# ==========================================================================
# Ranking
# ==========================================================================

#: BM25's two constants, the same values the search engine uses, so the two
#: corpora are ranked on the same scale of "this document answers this
#: question".
_K1 = 1.2
_B = 0.75

#: How many times a word in a title counts.  A note called "Atonement" is
#: about atonement; a note that happens to use the word once in its body may
#: not be.
_TITLE_BOOST = 3


def _tokens(text: str) -> list[str]:
    return [db.token_key(w) for (w, _s, _e) in db.words(text or "")]


def own_sources(question: str, limit: int = 4) -> list[dict]:
    """The reader's own material that bears on `question`, ranked and citable.

    The records have the same shape as the ones the search engine produces, so
    the assistant can number them and cite them beside the library's passages
    without either path knowing about the other.
    """
    docs = documents()
    if not docs or limit <= 0:
        return []
    terms = _content_terms(question)
    if not terms:
        return []

    # The corpus, tokenised once.
    freqs: list[Counter] = []
    lengths: list[int] = []
    df: Counter = Counter()
    for d in docs:
        tf: Counter = Counter()
        for t in _tokens(d["title"]):
            tf[t] += _TITLE_BOOST
        for t in _tokens(d["text"]):
            tf[t] += 1
        for t in _tokens(d.get("extra", "")):
            tf[t] += 1
        freqs.append(tf)
        lengths.append(sum(tf.values()))
        df.update(tf.keys())
    n = len(docs)
    avgdl = (sum(lengths) / n) or 1.0

    scored: list[tuple[float, int]] = []
    for i, tf in enumerate(freqs):
        dl = lengths[i] or 1
        s = 0.0
        hit = 0
        for t in terms:
            f = tf.get(t, 0)
            if not f:
                continue
            hit += 1
            dfn = df.get(t, 0)
            idf = math.log(1.0 + (n - dfn + 0.5) / (dfn + 0.5))
            s += idf * (f * (_K1 + 1.0)) / \
                (f + _K1 * (1.0 - _B + _B * dl / avgdl))
        if not hit:
            continue
        # Coverage: a document that matches every term of the question is more
        # likely to be the one the reader meant than one that matches a single
        # term three times.  The same correction the search engine applies.
        s *= 0.5 + 0.5 * (hit / len(terms))
        scored.append((s, i))
    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], x[1]))

    # One clipping must not fill every slot.  A folder of forty excerpts from
    # one commentary is forty documents that look alike, and two of them is a
    # better answer than four of the same thing.
    per_folder: Counter = Counter()
    out: list[dict] = []
    for s, i in scored:
        d = docs[i]
        folder = d.get("folder") or d["id"]
        if per_folder[folder] >= 2:
            continue
        per_folder[folder] += 1
        c = _citation(d, s)
        c["n"] = len(out) + 1
        out.append(c)
        if len(out) >= limit:
            break
    return out


def _date(ts) -> str:
    """A short date, or '' when there is not one worth showing."""
    try:
        if not ts:
            return ""
        return time.strftime("%d %b %Y", time.localtime(float(ts))).lstrip("0")
    except Exception:                                    # noqa: BLE001
        return ""


def _citation(d: dict, score: float) -> dict:
    """One piece of the reader's own material, in the shape the assistant cites.

    `module_id` is empty on purpose.  The reader's own material is not an
    installed resource, and a citation that carried a module id would be one
    the interface could try to open as though it were a book.
    """
    kind = d["kind"]
    when = _date(d.get("when") or 0)
    name = _KIND_NAMES.get(kind, "my own material")
    label = d.get("title") or name
    text = (d.get("text") or "").strip()
    if len(text) > 1200:
        text = text[:1200].rsplit(" ", 1)[0] + " …"
    return {
        "n": 0,                           # the caller numbers them
        "module_id": "",                  # not a module, and must not be one
        "module_name": f"{name} · {when}" if when else name,
        "label": label,
        "title": label,
        "type": "My" + kind.capitalize(),
        "text": text,
        "key": d.get("unit_key") or "",
        "own": {
            "kind": kind,
            "id": d.get("own_id") or "",
            "folder": d.get("folder") or "",
            "ref": d.get("ref") or "",
            "module_id": d.get("module_id") or "",
            "unit_key": d.get("unit_key") or "",
            "date": when,
        },
        "score": round(score, 4),
    }
