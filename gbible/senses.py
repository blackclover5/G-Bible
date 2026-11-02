"""Word senses grouped from installed public-domain lexica.

Not a sense inventory — no open one exists for Biblical Greek/Hebrew at the
depth some commercial platforms license. What the installed lexica *do* hold is
wordings: the
concordance's `word (transliteration): definition` line, Abbott-Smith's and
Dodson's first lines, Strong's own glosses. Identical wordings across works
are gathered into one sense with its sources named, so agreement across
lexica reads as one line and disagreement as several. Every line says where
it came from.
"""

from __future__ import annotations

import re

from . import canon, db


def _candidates(text: str) -> list[str]:
    """Plausible one-line glosses from an article's opening."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return []
    # Concordance shape: `word (transliteration): definition`.
    m = re.match(r"^[^:]{1,60}:\s*(.+)$", t)
    if m:
        t = m.group(1).strip()
    outs = []
    for chunk in re.split(r"[;·•]", t):
        c = chunk.strip().strip(".")
        # A gloss is short; the etymology essay that follows is not.
        if 2 <= len(c) <= 140 and re.search(r"[a-zA-Z\u0370-\u03ff\u0590-\u05ff]", c):
            outs.append(c)
        if len(outs) >= 4:
            break
    return outs


def _norm(gloss: str) -> str:
    g = gloss.lower()
    g = re.sub(r"\([^)]*\)", "", g)
    g = re.sub(r"[^a-z\u0370-\u03ff\u0590-\u05ff ]", "", g)
    return re.sub(r"\s+", " ", g).strip()


def senses_for(num: str, limit: int = 12) -> dict:
    from . import study
    n = canon.normalise_strongs(num or "")
    if not n:
        return {"ok": False, "error": f"Cannot read {num!r} as a Strong's number"}
    conn = db.connect()
    try:
        entries = study.lexicon_entries_for(conn, n, limit=12)
    except Exception:  # noqa: BLE001
        entries = []
    groups: dict[str, dict] = {}
    for e in entries:
        for cand in _candidates(e.get("text", "")):
            k = _norm(cand)
            if not k:
                continue
            g = groups.setdefault(k, {"gloss": cand, "sources": [],
                                      "count": 0})
            if e["module"] not in g["sources"]:
                g["sources"].append(e["module"])
            g["count"] += 1
    senses = sorted(groups.values(),
                    key=lambda g: (-len(g["sources"]), -g["count"], g["gloss"]))
    return {"ok": True, "num": n, "senses": senses[:limit],
            "lexica": len(entries),
            "note": "Grouped wordings from installed lexica — agreement "
                    "across works reads as one line. Not a sense inventory."}
