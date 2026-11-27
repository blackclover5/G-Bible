"""Analysis view: a search result set as a table and a set of facets.

A search answers "which units match"; analysis asks "what is this result set
made of".  The answer is a grid of hits with their original-language tags
attached, plus counts by resource, book, lemma, morphology and Strong's number.
It is deliberately built from a fresh search rather than from hits sent by the
client: a client only holds the page it was shown, while the truthful answer
counts every hit the query found, up to a bounded cap.

The tag columns are read in batches off the `marker` table.  One query per hit
would turn a five-thousand-hit analysis into five thousand round trips; chunked
`IN` lookups keep it to a handful.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from . import db, search

#: Columns offered to the sortable grid, in display order.  A caller can render
#: only the ones it wants; the keys are the contract.
COLUMNS = [
    {"key": "reference", "label": "Reference"},
    {"key": "module_name", "label": "Resource"},
    {"key": "book", "label": "Book"},
    {"key": "score", "label": "Relevance"},
    {"key": "lemmas", "label": "Lemmas"},
    {"key": "morphs", "label": "Morphology"},
    {"key": "strongs", "label": "Strong's numbers"},
    {"key": "matched", "label": "Matched terms"},
    {"key": "resolution", "label": "Resolution"},
]

#: The search engine's per-module candidate window.  Asking for more than this
#: makes `total` and `analyzed` disagree in a way no UI can explain.
MAX_HITS = 8000
_DEFAULT_HITS = 5000
_CHUNK = 400


def _chunks(items, n=_CHUNK):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _tags_for(hits: list) -> dict[tuple[str, str], dict]:
    """Book/chapter/verse and tag counts keyed by (module_id, unit_key)."""
    conn = db.connect()
    out: dict[tuple[str, str], dict] = {}

    def slot(mid: str, key: str) -> dict:
        return out.setdefault((mid, key), {
            "book": "", "chapter": 0, "verse": 0,
            "lemma": Counter(), "morph": Counter(), "strongs": Counter(),
        })

    # Hits arrive in relevance order, so consecutive ones are usually from
    # different modules.  Group by module first; each batch below can then use
    # one module_id plus a list of keys.
    per_module: dict[str, list[str]] = defaultdict(list)
    for mid, key in hits:
        per_module[mid].append(key)
    for mid, keys in per_module.items():
        for chunk in _chunks(keys):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT module_id, key, book, chapter, verse FROM unit "
                    f"WHERE module_id=? AND key IN ({ph})", [mid, *chunk]):
                s = slot(r["module_id"], r["key"])
                s["book"] = r["book"] or ""
                s["chapter"] = r["chapter"] or 0
                s["verse"] = r["verse"] or 0
            for r in conn.execute(
                    f"SELECT module_id, unit_key, kind, value FROM marker "
                    f"WHERE module_id=? AND unit_key IN ({ph}) "
                    f"AND kind IN ('lemma','morph','strongs')", [mid, *chunk]):
                s = slot(r["module_id"], r["unit_key"])
                s[r["kind"]][r["value"]] += 1
    return out


def _facet(counter: dict, *, with_id: bool = False) -> list[dict]:
    out = []
    for label, count in sorted(counter.items(), key=lambda x: (-x[1], str(x[0]))):
        item = {"label": str(label), "count": count}
        if with_id:
            item["id"] = label
        out.append(item)
    return out


def _sort_key(row: dict, sort: str):
    if sort == "score":
        return row["score"]
    if sort == "reference":
        return (row["book"], row["chapter"], row["verse"], row["label"])
    if sort in ("lemmas", "morphs", "strongs", "matched"):
        values = row[sort]
        return (len(values), ", ".join(values))
    return str(row.get(sort) or "")


def analyse(q: str, *, opts: search.SearchOpts | None = None,
            max_hits: int = _DEFAULT_HITS, sort: str = "score",
            descending: bool = True) -> dict:
    """Run a search and return its hits as a sortable grid plus facets."""
    q = q or ""
    max_hits = max(1, min(int(max_hits or _DEFAULT_HITS), MAX_HITS))
    base = opts or search.SearchOpts()
    analysis_opts = search.SearchOpts(
        modules=list(base.modules), scope=base.scope,
        match_case=base.match_case, match_all_forms=base.match_all_forms,
        match_forms=base.match_forms, include_resolved=base.include_resolved,
        limit=max_hits, offset=0, sort="relevance",
        snippets=False, context=0, smart=False,
    )
    result = search.search(q, analysis_opts)
    if not result.get("ok"):
        return {**result, "rows": [], "facets": {}, "columns": COLUMNS,
                "analyzed": 0}

    hits = result.get("hits") or []
    tags = _tags_for([(h["module_id"], h["key"]) for h in hits])
    rows: list[dict] = []
    by_book: Counter = Counter()
    by_module: Counter = Counter()
    by_type: Counter = Counter()
    by_lemma: Counter = Counter()
    by_morph: Counter = Counter()
    by_strongs: Counter = Counter()

    for h in hits:
        t = tags.get((h["module_id"], h["key"]), {})
        lemmas = sorted(t.get("lemma", {}), key=lambda x: (-t["lemma"][x], x))
        morphs = sorted(t.get("morph", {}), key=lambda x: (-t["morph"][x], x))
        strongs = sorted(t.get("strongs", {}), key=lambda x: (-t["strongs"][x], x))
        row = {
            "key": h["key"],
            "label": h.get("label") or "",
            "ref": h.get("label") or "",
            "module_id": h["module_id"],
            "module_name": h.get("module_name") or "",
            "module_type": h.get("module_type") or "",
            "book": t.get("book") or "",
            "chapter": t.get("chapter") or 0,
            "verse": t.get("verse") or 0,
            "score": h.get("score") or 0.0,
            "lemmas": lemmas,
            "morphs": morphs,
            "strongs": strongs,
            "matched": list(h.get("matched") or []),
            "resolution": ", ".join(h.get("role_notes") or []),
            "text": (h.get("text") or "")[:300],
        }
        rows.append(row)
        by_book[row["book"] or "—"] += 1
        by_module[f'{row["module_name"]} ({row["module_id"]})'] += 1
        by_type[row["module_type"] or "—"] += 1
        by_lemma.update(lemmas)
        by_morph.update(morphs)
        by_strongs.update(strongs)

    if sort not in {c["key"] for c in COLUMNS} | {"reference"}:
        sort = "score"
    rows.sort(key=lambda r: _sort_key(r, sort), reverse=descending)

    return {
        "ok": True,
        "query": result.get("query", q),
        "total": result.get("total", len(rows)),
        "analyzed": len(rows),
        "truncated": result.get("total", len(rows)) > len(rows),
        "columns": COLUMNS,
        "rows": rows,
        "facets": {
            "book": _facet(by_book),
            "module": _facet(by_module),
            "type": _facet(by_type),
            "lemma": _facet(by_lemma),
            "morph": _facet(by_morph),
            "strongs": _facet(by_strongs),
        },
        "warnings": result.get("warnings") or [],
        "ms": result.get("ms", 0),
    }
