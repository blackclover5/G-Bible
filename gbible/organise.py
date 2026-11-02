"""Collections, passage lists, search templates, favourites and charts.

These are the parts of a study environment that are about *arranging* what is
installed rather than reading it: a named set of resources, a set of references
read side by side, a query worth keeping, and a few resources worth keeping
close.

Nothing here invents content.  A collection is a list of module ids; a passage
list is a list of unit keys the user chose, each stored with the module it came
from because unit keys are module-specific ("John 3:16" in one module,
"John.3.16" in another).  Charts are counted off the same tables the rest of the
app reads, so they cannot drift from what is installed.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from . import db, library


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:11]}"


def _tombstone(rec_id: str, kind: str) -> None:
    """Record a delete so sync does not bring it back.  See sync.tombstone."""
    try:
        from . import sync
        sync.tombstone(rec_id, kind)
    except Exception:
        pass


# ------------------------------------------------------------------ favourites

def favourites() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute(
            "SELECT id, name, type, lang FROM module WHERE favorite=1 "
            "AND installed_at>0 "
            "ORDER BY type, name"):
        out.append(dict(r))
    return out


def set_favourite(module_id: str, value: bool) -> dict:
    library.set_favorite(module_id, value)
    return {"module_id": module_id, "favorite": bool(value)}


# ----------------------------------------------------------------- collections

def collections() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM collection ORDER BY created_at"):
        members = collection_members(r["id"])
        items = []
        for mid in members:
            m = library.get(mid)
            items.append({"module_id": mid, "name": m.name if m else mid,
                          "type": m.type if m else ""})
        d = dict(r)
        d["rule"] = collection_rule(r["id"]).get("rule", "")
        out.append({**d, "count": len(members), "modules": items})
    return out


def collection_rule(collection_id: str) -> dict:
    """Rule + manual overrides for a collection, stored in settings.

    No schema change: `collection_rules` maps id -> {rule, plus, minus}.
    """
    try:
        all_rules = db.get_setting("collection_rules", {})
    except Exception:  # noqa: BLE001
        all_rules = {}
    if not isinstance(all_rules, dict):
        return {"rule": "", "plus": [], "minus": []}
    d = all_rules.get(collection_id) or {}
    return {"rule": d.get("rule", ""),
            "plus": list(d.get("plus") or []),
            "minus": list(d.get("minus") or [])}


def set_collection_rule(collection_id: str, rule: str = "",
                        plus: list | None = None,
                        minus: list | None = None) -> dict:
    try:
        all_rules = db.get_setting("collection_rules", {})
    except Exception:  # noqa: BLE001
        all_rules = {}
    if not isinstance(all_rules, dict):
        all_rules = {}
    d = dict(all_rules.get(collection_id) or {})
    if rule is not None:
        d["rule"] = rule
    if plus is not None:
        d["plus"] = [m for m in plus if library.get(m) is not None]
    if minus is not None:
        d["minus"] = list(minus)
    all_rules[collection_id] = d
    db.set_setting("collection_rules", all_rules)
    return {"id": collection_id, **collection_rule(collection_id),
            "members": collection_members(collection_id)}


#: field -> module attribute it matches against (substring, case-insensitive).
_RULE_FIELDS = {
    "type": "type", "lang": "lang", "language": "lang",
    "author": "author", "source": "source", "series": "version",
    "publisher": "source_name", "subject": "subject",
    "title": "name", "name": "name", "license": "license",
    "licence": "license", "format": "format",
}


def match_rule(rule: str) -> list[str]:
    """Module ids matching a rule like `type:commentary lang:eng ANDNOT mytag:x`.

    Terms are field:value (substring match); bare words match name/author/type.
    AND is implicit, ANDNOT/NOT negates the next term. New installs match
    automatically because this is evaluated live, never snapshotted.
    """
    mods = library.list_all(order="priority DESC, name ASC")
    tags = module_tags()
    tokens = (rule or "").split()
    if not tokens:
        return [m.id for m in mods]
    clauses: list[tuple[bool, str, str]] = []  # (negated, field, value)
    negate = False
    for tok in tokens:
        up = tok.upper()
        if up in ("AND", "&", "+"):
            continue
        if up in ("ANDNOT", "NOT", "-"):
            negate = True
            continue
        if ":" in tok:
            f, v = tok.split(":", 1)
            clauses.append((negate, f.lower(), v.lower()))
        else:
            clauses.append((negate, "", tok.lower()))
        negate = False
    out = []
    for m in mods:
        ok = True
        for neg, field, val in clauses:
            hit = _module_hit(m, field, val, tags.get(m.id, []))
            if neg and hit:
                ok = False
                break
            if not neg and not hit:
                ok = False
                break
        if ok:
            out.append(m.id)
    return out


def _module_hit(m, field: str, val: str, mytags: list[str]) -> bool:
    if field in ("mytag", "tag", "tags"):
        return any(val in (t or "").lower() for t in mytags)
    if field in ("has", "feature"):
        feats = {"strongs": m.has_strongs, "morph": m.has_morph,
                 "notes": m.has_notes, "xref": m.has_xref,
                 "redletter": m.has_redletter}
        return bool(feats.get(val))
    attr = _RULE_FIELDS.get(field, "")
    if attr == "subject":
        subj = m.subject if isinstance(m.subject, list) else []
        return any(val in (s or "").lower() for s in subj)
    if attr:
        return val in str(getattr(m, attr, "") or "").lower()
    if field:
        return False
    blob = " ".join([m.name or "", m.abbrev or "", m.author or "", m.type or "",
                     " ".join(m.subject if isinstance(m.subject, list) else [])])
    return val in blob.lower()


def collection_members(collection_id: str) -> list[str]:
    """Live members: rule matches + manual plus, minus manual minus, plus any
    legacy pinned items. Legacy items behave as pinned (plus)."""
    conn = db.connect()
    pinned = [r["module_id"] for r in conn.execute(
        "SELECT module_id FROM collection_item WHERE collection_id=? "
        "ORDER BY position", (collection_id,))]
    rd = collection_rule(collection_id)
    members = match_rule(rd["rule"]) if rd.get("rule") else []
    seen, ordered = set(), []
    for mid in members + pinned + list(rd.get("plus") or []):
        if mid and mid not in seen and library.get(mid) is not None:
            seen.add(mid)
            ordered.append(mid)
    minus = set(rd.get("minus") or [])
    return [m for m in ordered if m not in minus]


def collection_items(collection_id: str) -> list[str]:
    return collection_members(collection_id)


def save_collection(name: str, note: str = "", modules: list | None = None,
                    collection_id: str = "") -> dict:
    """Create or update a collection.  Names are not unique: two sets of study
    resources can plausibly both be called "Greek", and silently merging them
    would be worse than two rows."""
    conn = db.connect()
    name = (name or "").strip() or "Untitled collection"
    if collection_id and conn.execute(
            "SELECT 1 FROM collection WHERE id=?", (collection_id,)).fetchone():
        conn.execute("UPDATE collection SET name=?, note=? WHERE id=?",
                     (name, note, collection_id))
    else:
        collection_id = collection_id or _id("col")
        conn.execute("INSERT INTO collection(id,name,note,created_at) "
                     "VALUES(?,?,?,?)", (collection_id, name, note, time.time()))
    if modules is not None:
        conn.execute("DELETE FROM collection_item WHERE collection_id=?",
                     (collection_id,))
        for i, mid in enumerate(modules):
            if not mid:
                continue
            conn.execute("INSERT OR REPLACE INTO collection_item"
                         "(collection_id,module_id,position,added_at) "
                         "VALUES(?,?,?,?)", (collection_id, mid, i, time.time()))
    conn.commit()
    return {"id": collection_id, "name": name,
            "modules": collection_items(collection_id)}


def add_to_collection(collection_id: str, module_id: str) -> dict:
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM collection WHERE id=?",
                        (collection_id,)).fetchone():
        return {"error": "no such collection"}
    # Adding something already in the set is a no-op.  `INSERT OR REPLACE`
    # against the (collection_id, module_id) primary key does not do that: it
    # deletes the existing row and inserts a new one, and the new row's
    # position is the current count -- so the module jumped from wherever it
    # was to the end of the collection, and the order the reader had built was
    # quietly rewritten by a click that was supposed to change nothing.
    have = conn.execute("SELECT 1 FROM collection_item "
                        "WHERE collection_id=? AND module_id=?",
                        (collection_id, module_id)).fetchone()
    if have:
        return {"id": collection_id, "modules": collection_items(collection_id),
                "unchanged": True}
    n = conn.execute("SELECT count(*) c FROM collection_item WHERE collection_id=?",
                     (collection_id,)).fetchone()["c"]
    conn.execute("INSERT OR REPLACE INTO collection_item"
                 "(collection_id,module_id,position,added_at) VALUES(?,?,?,?)",
                 (collection_id, module_id, n, time.time()))
    conn.commit()
    return {"id": collection_id, "modules": collection_items(collection_id)}


def delete_collection(collection_id: str) -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM collection_item WHERE collection_id=?",
                 (collection_id,))
    conn.execute("DELETE FROM collection WHERE id=?", (collection_id,))
    conn.commit()
    _tombstone(collection_id, "collection")
    return {"removed": collection_id}


# --------------------------------------------------------------- passage lists

def passage_lists() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM passage_list ORDER BY created_at"):
        n = conn.execute("SELECT count(*) c FROM passage_item WHERE list_id=?",
                         (r["id"],)).fetchone()["c"]
        out.append({**dict(r), "count": n})
    return out


def passage_items(list_id: str) -> list[dict]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM passage_item WHERE list_id=? ORDER BY position, added_at",
        (list_id,))]


def save_passage_list(name: str, note: str = "", list_id: str = "") -> dict:
    conn = db.connect()
    name = (name or "").strip() or "Untitled list"
    if list_id and conn.execute("SELECT 1 FROM passage_list WHERE id=?",
                                (list_id,)).fetchone():
        conn.execute("UPDATE passage_list SET name=?, note=? WHERE id=?",
                     (name, note, list_id))
    else:
        list_id = list_id or _id("pl")
        conn.execute("INSERT INTO passage_list(id,name,note,created_at) "
                     "VALUES(?,?,?,?)", (list_id, name, note, time.time()))
    conn.commit()
    return {"id": list_id, "name": name}


def add_passage(list_id: str, unit_key: str, ref_label: str = "",
                module_id: str = "") -> dict:
    """Add a reference.  Repeats are refused rather than duplicated: a parallel
    list with the same verse twice is a mistake, and silently allowing it makes
    the list harder to trust."""
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM passage_list WHERE id=?",
                        (list_id,)).fetchone():
        return {"error": "no such passage list"}
    if conn.execute("SELECT 1 FROM passage_item WHERE list_id=? AND unit_key=?",
                    (list_id, unit_key)).fetchone():
        return {"id": list_id, "unchanged": True, "items": passage_items(list_id)}
    n = conn.execute("SELECT count(*) c FROM passage_item WHERE list_id=?",
                     (list_id,)).fetchone()["c"]
    conn.execute("INSERT INTO passage_item"
                 "(id,list_id,unit_key,ref_label,module_id,position,added_at) "
                 "VALUES(?,?,?,?,?,?,?)",
                 (_id("pi"), list_id, unit_key, ref_label, module_id, n,
                  time.time()))
    conn.commit()
    return {"id": list_id, "items": passage_items(list_id)}


def remove_passage(item_id: str) -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM passage_item WHERE id=?", (item_id,))
    conn.commit()
    _tombstone(item_id, "passage")
    return {"removed": item_id}


def move_passage(item_id: str, delta: int) -> dict:
    """Move an item one place up or down, then renumber so positions stay dense."""
    conn = db.connect()
    r = conn.execute("SELECT * FROM passage_item WHERE id=?", (item_id,)).fetchone()
    if r is None:
        return {"error": "no such item"}
    items = passage_items(r["list_id"])
    ids = [i["id"] for i in items]
    if item_id not in ids:
        return {"error": "item not in list"}
    at = ids.index(item_id)
    to = max(0, min(len(ids) - 1, at + (1 if delta > 0 else -1)))
    if to != at:
        ids.insert(to, ids.pop(at))
        for pos, iid in enumerate(ids):
            conn.execute("UPDATE passage_item SET position=? WHERE id=?",
                         (pos, iid))
    conn.commit()
    return {"id": r["list_id"], "items": passage_items(r["list_id"])}


def delete_passage_list(list_id: str) -> dict:
    conn = db.connect()
    items = [r["id"] for r in conn.execute(
        "SELECT id FROM passage_item WHERE list_id=?", (list_id,))]
    conn.execute("DELETE FROM passage_item WHERE list_id=?", (list_id,))
    conn.execute("DELETE FROM passage_list WHERE id=?", (list_id,))
    conn.commit()
    _tombstone(list_id, "passage-list")
    for iid in items:
        _tombstone(iid, "passage")
    return {"removed": list_id}


# ----------------------------------------------------------- search templates

def templates() -> list[dict]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM search_template ORDER BY created_at"):
        d = dict(r)
        try:
            d["options"] = json.loads(d.get("options") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["options"] = {}
        out.append(d)
    return out


def save_template(name: str, query: str, options: dict | None = None) -> dict:
    conn = db.connect()
    name = (name or "").strip() or query[:40] or "Untitled search"
    q = (query or "").strip()
    if not q:
        return {"error": "a template needs a query"}
    existing = conn.execute(
        "SELECT id FROM search_template WHERE name=? AND query=?", (name, q)
    ).fetchone()
    tid = existing["id"] if existing else _id("st")
    conn.execute(
        "INSERT OR REPLACE INTO search_template(id,name,query,options,created_at)"
        " VALUES(?,?,?,?,?)",
        (tid, name, q, json.dumps(options or {}), time.time()))
    conn.commit()
    return {"id": tid, "name": name, "query": q}


def delete_template(template_id: str) -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM search_template WHERE id=?", (template_id,))
    conn.commit()
    _tombstone(template_id, "template")
    return {"removed": template_id}


# Built-in starting points. Queries are plain engine syntax — tapping one
# fills the box and runs it, and saving keeps a copy the user can edit.
TEMPLATE_GALLERY = [
    {"name": "Word study starter", "query": "love NEAR hope",
     "about": "Two words near each other, anywhere in the library."},
    {"name": "Exact phrase", "query": '"kingdom of God"',
     "about": "Order and adjacency, no stemming."},
    {"name": "Original language", "query": "strongs:G2316",
     "about": "Every tagged occurrence of a Strong's number."},
    {"name": "Nearby words", "query": "faith WITHIN 5 WORDS lord",
     "about": "Proximity with a real window, not an exact gap."},
    {"name": "Ordered pair", "query": "prophets BEFORE law",
     "about": "First term precedes the second."},
    {"name": "Exclusion", "query": "love NOT hate",
     "about": "Present with the other absent."},
    {"name": "Morphology", "query": "morph.g:VF",
     "about": "Tagged words by morphology code; a prefix is enough."},
    {"name": "At a passage", "query": 'bible:"Gen 1:1"',
     "about": "Passages and cross-references only."},
    {"name": "Topic articles", "query": "topic:faith",
     "about": "Fact-book articles rather than every use of the word."},
]


def template_gallery() -> dict:
    saved = {t["query"] for t in templates()}
    return {"ok": True,
            "gallery": [{**g, "saved": g["query"] in saved}
                        for g in TEMPLATE_GALLERY]}


# ----------------------------------------------------------------- charts

def charts(kind: str = "", arg: str = "") -> dict:
    """A bar chart of something countable.  Counted off the same tables the rest
    of the app reads, so a chart cannot disagree with the library."""
    conn = db.connect()
    kind = (kind or "type").lower()

    if kind in ("type", ""):
        rows = conn.execute(
            "SELECT type, count(*) n FROM module WHERE installed_at>0 "
            "GROUP BY type ORDER BY n DESC, type").fetchall()
        return _chart("Installed resources by kind",
                      [{"label": r["type"], "value": r["n"]} for r in rows])

    if kind == "lang":
        rows = conn.execute(
            "SELECT lang, count(*) n FROM module WHERE installed_at>0 "
            "GROUP BY lang ORDER BY n DESC").fetchall()
        return _chart("Installed resources by language",
                      [{"label": r["lang"] or "—", "value": r["n"]} for r in rows])

    if kind == "source":
        rows = conn.execute(
            "SELECT source, count(*) n FROM module WHERE installed_at>0 "
            "GROUP BY source ORDER BY n DESC").fetchall()
        return _chart("Installed resources by source",
                      [{"label": r["source"] or "—", "value": r["n"]}
                       for r in rows])

    if kind == "bible":
        rows = conn.execute(
            "SELECT m.id, m.name, m.entries FROM module m "
            "WHERE m.installed_at>0 AND m.type='Bible' "
            "ORDER BY m.entries DESC").fetchall()
        return _chart("Verses installed per translation",
                      [{"label": r["name"], "value": r["entries"] or 0,
                        "id": r["id"]} for r in rows])

    if kind == "word":
        # Occurrences of a Strong's number, by book.  Goes through word_bundle so
        # the chart and the word study cannot disagree about the count.
        from . import study
        try:
            wb = study.word_bundle(arg)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "series": []}
        if not wb.get("ok"):
            return {"ok": False, "error": wb.get("error", "no such word"),
                    "series": []}
        # word_bundle hands back (book, count) tuples, not dicts.
        dist = wb.get("by_book") or []
        return _chart(f"Occurrences of {wb.get('num', arg)} by book",
                      [{"label": d[0], "value": d[1]} for d in dist])

    if kind in ("morph", "morphology"):
        return _morph_chart(arg)

    return {"ok": False, "error": f"unknown chart {kind!r}"}


def _morph_chart(arg: str) -> dict:
    """How the words of a passage break down by part of speech.

    `arg` is either a morphology filter -- "pos=V" or "pos=N,tense=ximpf" -- or
    a passage, in which case the breakdown is of that verse.  With neither, it
    reports the whole library, which is the more interesting answer anyway:
    which parts of speech this library's tagged texts actually use.

    Counted off the marker table through morphq, so the bars and the morph
    search results are the same numbers.
    """
    from . import clause, morphq
    arg = (arg or "").strip()
    if not arg:
        f = morphq.facets()
        return _chart("Parts of speech across the tagged texts",
                      [{"label": r["value"], "value": r["n"]}
                       for r in (f.get("pos") or [])])

    if _FILTER_ARG.match(arg):
        try:
            q = morphq.query(limit=1, **_filters(arg))
        except Exception as exc:
            return {"ok": False, "error": str(exc), "series": []}
        # morphq.query pages its results rather than returning a facet table, so
        # the distribution is tallied from one page of them.  The page is large
        # enough to be the shape of the answer, and `total` carries the real
        # count underneath it.
        tally: dict[str, int] = {}
        for r in q.get("results") or []:
            lab = (r.get("features") or {}).get("pos_label") or "untagged"
            tally[lab] = tally.get(lab, 0) + (r.get("count") or 0)
        series = [{"label": k, "value": v}
                  for k, v in sorted(tally.items(), key=lambda x: -x[1])]
        return _chart(f"Where {arg} occurs, by part of speech", series)

    # A passage: John 3:16, or a unit key.
    unit = _unit_for(arg)
    if not unit:
        return {"ok": False,
                "error": f"{arg!r} is not a passage this library has",
                "series": []}
    mid, key = unit
    d = clause.diagram(mid, key, ref=arg)
    if not d.get("ok"):
        return {"ok": False, "error": d.get("error", "no such verse"),
                "series": []}
    series = [{"label": k["label"] or k["tag"], "value": k["n"]}
              for k in d.get("kinds") or []]
    title = f"Parts of speech in {d.get('ref') or arg}"
    if not series:
        title += "  —  no morphology in this module"
    return _chart(title, series)


#: A morphology filter, as opposed to a passage.  Anchored on the field names
#: so that "John 3:16" is a verse and not a filter that happens to have a
#: colon in it.
_FILTER_ARG = re.compile(
    r"^(pos|gender|number|state|conjugation|tense|person|participle|scheme|"
    r"pos_particle)\s*=")


def _filters(arg: str) -> dict:
    """`pos=N,tense=ximpf` -> {'pos': 'N', 'tense': 'ximpf'}"""
    allowed = ("pos", "gender", "number", "state", "conjugation", "tense",
               "person", "participle", "scheme", "pos_particle")
    out: dict = {}
    for part in arg.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k in allowed:
            out[k] = v.strip()
    return out


def _unit_for(ref: str, *, tagged: bool = True) -> tuple[str, str] | None:
    """A reference or a `Book.Chapter.Verse` key to (module, unit key).

    With `tagged` (the default) only modules carrying morphology are
    considered.  That is right for a sentence diagram: a tagged Hebrew verse
    gets its own grammar rather than one worked out from its surface.  Callers
    that can also serve an English verse from a dependency parse should ask
    again with `tagged=False` rather than report the verse as absent, which is
    what happened to every Gospel and Epistle reference here.
    """
    from . import canon
    conn = db.connect()
    key = ""
    if ref.count(".") >= 2:
        key = ref
    else:
        try:
            rr = canon.parse_ref(ref)
        except Exception:
            rr = None
        if rr:
            first = next(iter(rr.refs()), None)
            key = first.osis_id() if first else ""
    if not key:
        return None
    sql = ("SELECT u.module_id, u.key FROM unit u JOIN module m "
           "ON m.id=u.module_id WHERE u.key=? AND u.book<>'' "
           "AND m.installed_at>0")
    if tagged:
        sql += " AND m.has_morph=1"
    sql += (" ORDER BY m.has_morph DESC, m.priority DESC, m.favorite DESC LIMIT 1")
    row = conn.execute(sql, (key,)).fetchone()
    return (row["module_id"], row["key"]) if row else None


def _chart(title: str, series: list[dict]) -> dict:
    vals = [s["value"] or 0 for s in series]
    top = max(vals) if vals else 0
    return {"ok": True, "title": title, "series": series,
            "max": top, "total": sum(vals),
            "bars": len(series)}


# -------------------------------------------------------------- browser query

BROWSER_FIELDS = [
    {"field": "all", "label": "Must contain all of",
     "kind": "words", "help": "every one of these words, in any order"},
    {"field": "any", "label": "Must contain any of",
     "kind": "words", "help": "at least one of these"},
    {"field": "none", "label": "Must not contain",
     "kind": "words", "help": "excluded, like NOT in the search box"},
    {"field": "anchor", "label": "Near this word",
     "kind": "word", "help": "the left side of a proximity search"},
    {"field": "within_words", "label": "Within how many words",
     "kind": "number", "help": "of the other word"},
    {"field": "anchor2", "label": "of this word",
     "kind": "word", "help": "the right side of the proximity search"},
    {"field": "before", "label": "Followed by",
     "kind": "word", "help": "this word comes first"},
    {"field": "after", "label": "Before",
     "kind": "word", "help": "this word comes second"},
    {"field": "strongs", "label": "Strong's number",
     "kind": "text", "help": "e.g. G2316"},
    {"field": "heading", "label": "Subject heading",
     "kind": "text", "help": "a Factbook heading"},
    {"field": "bible", "label": "Reference",
     "kind": "text", "help": 'e.g. John 3:16 or "Gen 1"'},
    {"field": "type", "label": "Kind of resource",
     "kind": "choice", "help": "Bible, Commentary, Lexicon ..."},
]


def _term(value: str) -> str:
    """One search term.  A value with a space is a phrase and has to be quoted,
    or the engine reads it as two separate words."""
    v = (value or "").strip().strip('"')
    if not v:
        return ""
    return f'"{v}"' if " " in v else v


def browser_query(spec: dict) -> dict:
    """Turn a form into a query string the search engine actually accepts.

    Every form here was checked against the engine rather than guessed.  The
    first version emitted `word:"faith"` and a bare `AND` left behind by a blank
    field; both produce a query that parses to something other than what the
    form says -- and `-word:"world"` even came back with *more* results than
    without it.  The forms below are the ones measured:

        faith lord                     juxtaposition is AND
        faith NOT world                exclusion
        faith OR hope                  alternatives
        (faith OR hope) AND lord       grouped
        faith WITHIN 5 WORDS lord      proximity
        faith BEFORE hope              order
        strongs:G2316                  field
    """
    parts: list[str] = []

    def terms(words: list | None) -> list[str]:
        return [t for t in (_term(w) for w in (words or [])) if t]

    # "all of" is AND, and the engine's AND is juxtaposition -- measured:
    # `faith lord` and `faith AND lord` both give 7665.
    all_of = " ".join(terms(spec.get("all")))
    if all_of:
        parts.append(all_of)

    # "any of" is OR, and needs the group so it cannot swallow a neighbour.
    any_of = terms(spec.get("any"))
    if any_of:
        parts.append(any_of[0] if len(any_of) == 1
                     else "(" + " OR ".join(any_of) + ")")
    for w in spec.get("none") or []:
        t = _term(w)
        if t:
            parts.append(f"NOT {t}")

    a1 = _term(spec.get("anchor") or "")
    a2 = _term(spec.get("anchor2") or "")
    if a1 and a2:
        try:
            n = int(str(spec.get("within_words") or 0).strip() or 0)
        except ValueError:
            n = 0
        if n > 0:
            parts.append(f"{a1} WITHIN {n} WORDS {a2}")
        else:
            parts.append(f"{a1} NEAR {a2}")
    elif a1 and a2 == "" and spec.get("anchor"):
        parts.append(a1)

    for key, op in (("before", "BEFORE"), ("after", "AFTER")):
        first = _term(spec.get(key) or "")
        second = _term(spec.get("anchor2") if key == "before" else spec.get("anchor"))
        if first and second:
            parts.append(f"{first} {op} {second}")

    for field in ("strongs", "heading", "bible"):
        v = (spec.get(field) or "").strip().strip('"')
        if v:
            parts.append(f'{field}:{v}' if " " not in v else f'{field}:"{v}"')
    for field in ("type", "lang"):
        v = (spec.get(field) or "").strip()
        if v:
            parts.append(f'{field}:{v}')

    return {"ok": True, "query": " AND ".join(parts)}


# --------------------------------------------------------------------------
# Pack 2: personal tags, notebooks, library query syntax, availability.
# Tags/notebooks live in `setting` so no schema migration is needed.
# --------------------------------------------------------------------------

def module_tags() -> dict:
    """module_id -> [tag]. Personal tags; community tags need a community."""
    try:
        v = db.get_setting("module_tags", {})
    except Exception:  # noqa: BLE001
        return {}
    return v if isinstance(v, dict) else {}


def set_module_tags(module_id: str, tags: list[str]) -> dict:
    if library.get(module_id) is None:
        return {"ok": False, "error": "Not installed"}
    try:
        all_tags = db.get_setting("module_tags", {})
    except Exception:  # noqa: BLE001
        all_tags = {}
    if not isinstance(all_tags, dict):
        all_tags = {}
    clean = sorted({(t or "").strip() for t in (tags or []) if (t or "").strip()})
    if clean:
        all_tags[module_id] = clean
    elif module_id in all_tags:
        del all_tags[module_id]
    db.set_setting("module_tags", all_tags)
    return {"ok": True, "module_id": module_id, "tags": clean}


def notebooks() -> list[dict]:
    """Named filters over notes: {id, name, kind, tag, query}."""
    try:
        v = db.get_setting("notebooks", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def save_notebook(name: str, kind: str = "", tag: str = "",
                  query: str = "", notebook_id: str = "") -> dict:
    try:
        all_nb = db.get_setting("notebooks", [])
    except Exception:  # noqa: BLE001
        all_nb = []
    if not isinstance(all_nb, list):
        all_nb = []
    name = (name or "").strip() or "Untitled notebook"
    nb_id = notebook_id or _id("nb")
    nb = {"id": nb_id, "name": name, "kind": kind or "",
          "tag": tag or "", "query": query or ""}
    all_nb = [n for n in all_nb if n.get("id") != nb_id] + [nb]
    db.set_setting("notebooks", all_nb)
    return {"ok": True, "notebook": nb}


def delete_notebook(notebook_id: str) -> dict:
    try:
        all_nb = db.get_setting("notebooks", [])
    except Exception:  # noqa: BLE001
        all_nb = []
    db.set_setting("notebooks",
                   [n for n in (all_nb or []) if n.get("id") != notebook_id])
    return {"ok": True, "removed": notebook_id}


def notebook_notes(notebook_id: str) -> list[dict]:
    """Notes belonging to a notebook: kind/tag/query must all match."""
    nbs = notebooks()
    nb = next((n for n in nbs if n.get("id") == notebook_id), None)
    if nb is None:
        return []
    from . import notes as _notes
    items = _notes.list_notes() if hasattr(_notes, "list_notes") else []
    if not items and hasattr(_notes, "list"):
        try:
            items = _notes.list()
        except Exception:  # noqa: BLE001
            items = []
    out = []
    for n in items:
        d = dict(n) if not isinstance(n, dict) else n
        if nb.get("kind") and d.get("kind") != nb["kind"]:
            continue
        if nb.get("tag"):
            tags = d.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, TypeError):
                    tags = [tags]
            if nb["tag"] not in (tags or []):
                continue
        if nb.get("query"):
            blob = " ".join(str(d.get(k) or "") for k in ("title", "body"))
            if nb["query"].lower() not in blob.lower():
                continue
        out.append(d)
    return out


def library_query(q: str) -> list[dict]:
    """Filter installed modules with `field:value` syntax.

    Fields: title/name, author, type, subject, lang/language, source,
    publisher, series(version), license/licence, mytag/tag, has:strongs|morph|
    notes|xref|redletter. Bare words match name/author/type. Shares the same
    matcher as collection rules so the two cannot disagree.
    """
    mods = library.list_all(order="priority DESC, name ASC")
    tags = module_tags()
    tokens = (q or "").split()
    if not tokens:
        return [{"id": m.id, "name": m.name, "type": m.type,
                 "author": m.author, "lang": m.lang, "kind": "digital"} for m in mods]
    clauses: list[tuple[bool, str, str]] = []
    negate = False
    for tok in tokens:
        up = tok.upper()
        if up in ("AND", "&", "+"):
            continue
        if up in ("ANDNOT", "NOT", "-"):
            negate = True
            continue
        if ":" in tok:
            f, v = tok.split(":", 1)
            clauses.append((negate, f.lower(), v.lower()))
        else:
            clauses.append((negate, "", tok.lower()))
        negate = False
    out = []
    for m in mods:
        hit_all = all((not _module_hit(m, f, v, tags.get(m.id, [])) if neg
                       else _module_hit(m, f, v, tags.get(m.id, [])))
                      for neg, f, v in clauses)
        if hit_all:
            out.append({"id": m.id, "name": m.name, "type": m.type,
                        "author": m.author, "lang": m.lang, "kind": "digital"})
    # Print books on the shelf, matched against the same query: a title or
    # author match counts, and an ISBN matches itself exactly.
    needle = " ".join(v for _, f, v in clauses if not f) or (q or "")
    for b in print_books():
        blob = " ".join([b.get("title", ""), b.get("author", ""),
                         b.get("publisher", "")]).lower()
        if needle.lower() in blob or (b.get("isbn") and b["isbn"] in (q or "")):
            out.append({"id": b["id"], "name": b["title"] + " (print)",
                        "type": "Print", "author": b.get("author", ""),
                        "lang": "", "kind": "print"})
    return out


def availability() -> list[dict]:
    """Local availability per module: installed, units, and where the files are.

    `files` is four-valued and the distinction matters:

        present   the recorded path is there
        moved     it is not, but the module's own folder is under the library
                  this process is actually using -- the whole project was moved
                  or copied to a new machine and the recorded absolute paths
                  still name the old one
        missing   neither, so the files really are gone
        n/a       no path recorded (an installed-from-index-only module)

    Reporting only present/missing made a moved library report every module as
    missing, which is both alarming and wrong: the text is all in the database,
    which travelled with the project, so the library reads perfectly well.  It
    is only re-indexing and "add audio" that need the folder on disk.
    """
    here = str(db.app_dir())
    out = []
    for m in library.list_all(installed_only=False):
        files = "n/a"
        if m.path or m.folder:
            # module_dir prefers the library in use and falls back to the
            # recorded path, so "present" means present *now*. `moved` names the
            # case where the recorded value is the thing that is wrong; after
            # repair_paths() has run it no longer arises, which is the point of
            # repairing it rather than only tolerating it.
            if library.module_dir(m.id) is not None:
                files = "present"
            elif not (m.path or "").startswith(here):
                files = "moved"
            else:
                files = "missing"
        out.append({"id": m.id, "name": m.name, "installed": m.installed_at > 0,
                    "units": m.entries or m.verses or 0,
                    "files": files})
    return out


# ------------------------------------------------------- print-book catalog
# Books you own on paper. No barcode camera here — decoding needs native or
# mobile code this project does not ship — so the path is: read the ISBN off
# the book (or its barcode digits), type it, and the checksum says whether
# you typed it right. Catalogue entries are searchable alongside the digital
# library through library_query.

def validate_isbn(raw: str) -> dict:
    """ISBN-10/13 checksum. Hyphens and spaces are ignored."""
    digits = re.sub(r"[^0-9Xx]", "", raw or "")
    if len(digits) == 10:
        if not re.fullmatch(r"[0-9]{9}[0-9Xx]", digits):
            return {"ok": False, "error": "Not a 10-digit ISBN"}
        total = sum((10 - i) * (10 if c in "Xx" else int(c))
                    for i, c in enumerate(digits))
        if total % 11:
            return {"ok": False, "error": "ISBN-10 checksum fails — check the digits"}
        return {"ok": True, "isbn": digits, "kind": "ISBN-10"}
    if len(digits) == 13 and digits.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3)
                    for i, c in enumerate(digits))
        if total % 10:
            return {"ok": False, "error": "ISBN-13 checksum fails — check the digits"}
        return {"ok": True, "isbn": digits, "kind": "ISBN-13"}
    return {"ok": False, "error": "An ISBN is 10 or 13 digits"}


def print_books() -> list[dict]:
    try:
        v = db.get_setting("print_books", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def save_print_book(title: str, author: str = "", isbn: str = "",
                    publisher: str = "", year: str = "", note: str = "",
                    pid: str = "") -> dict:
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "A print book needs a title"}
    norm_isbn = ""
    if (isbn or "").strip():
        chk = validate_isbn(isbn)
        if not chk.get("ok"):
            return {"ok": False, "error": chk.get("error", "bad ISBN")}
        norm_isbn = chk["isbn"]
    all_b = print_books()
    if norm_isbn and any(b.get("isbn") == norm_isbn and b.get("id") != pid
                         for b in all_b):
        return {"ok": False, "error": "That ISBN is already catalogued"}
    pid = pid or _id("pb")
    rec = {"id": pid, "title": title, "author": (author or "").strip(),
           "isbn": norm_isbn, "publisher": (publisher or "").strip(),
           "year": (year or "").strip(), "note": (note or "").strip(),
           "added_at": time.time()}
    all_b = [b for b in all_b if b.get("id") != pid] + [rec]
    db.set_setting("print_books", all_b)
    return {"ok": True, "book": rec}


def delete_print_book(pid: str) -> dict:
    db.set_setting("print_books",
                   [b for b in print_books() if b.get("id") != pid])
    return {"ok": True, "removed": pid}


def lookup_isbn(raw: str) -> dict:
    """Look up a print book's metadata from Open Library by ISBN.

    Open Library's data is freely reusable. The app never stores anything it
    does not have to: the caller decides whether to save the result into the
    print-book catalogue via save_print_book. A failed or missing lookup
    returns ok=False with a reason rather than a guess, so the user types the
    details themselves instead of trusting a wrong record.
    """
    chk = validate_isbn(raw)
    if not chk.get("ok"):
        return {"ok": False, "error": chk.get("error", "bad ISBN")}
    isbn = chk["isbn"]
    import urllib.request, json as _j
    url = ("https://openlibrary.org/api/books?bibkeys=ISBN:" + isbn
           + "&format=json&jscmd=data")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GBible/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = _j.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Open Library unreachable: {e}",
                "isbn": isbn}
    key = "ISBN:" + isbn
    rec = data.get(key) if isinstance(data, dict) else None
    if not rec:
        return {"ok": False, "error": "No record for that ISBN on Open Library",
                "isbn": isbn}
    authors = [a.get("name") for a in (rec.get("authors") or [])
               if a.get("name")]
    publishers = [p.get("name") for p in (rec.get("publishers") or [])
                  if p.get("name")]
    return {"ok": True, "isbn": isbn, "kind": chk["kind"],
            "title": (rec.get("title") or "").strip(),
            "author": ", ".join(authors),
            "publisher": ", ".join(publishers),
            "year": str(rec.get("publish_date") or "").strip(),
            "source": "Open Library (openlibrary.org)",
            "cover": ((rec.get("cover") or {}).get("medium")
                      or (rec.get("cover") or {}).get("small") or "")}
