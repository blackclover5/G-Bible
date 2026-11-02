"""Bible facts: weights, measures, money and the calendar.

Reference data shipped with the app (public domain facts).  Loaded once per
process and served by the ``guides/biblefacts`` endpoint.  Nothing here is
computed or guessed: the tables are the reference values as recorded in
standard public-domain Bible dictionaries.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_DATA = _ROOT / "data" / "bible_facts.json"

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_DATA.read_text(encoding="utf-8"))
    return _cache


def bible_facts() -> dict:
    d = load()
    return {
        "title": d.get("title", ""),
        "source": d.get("source", ""),
        "license": d.get("license", ""),
        "weights": d.get("weights", []),
        "measures_dry": d.get("measures_dry", []),
        "measures_liquid": d.get("measures_liquid", []),
        "money": d.get("money", []),
        "calendar_months": d.get("calendar_months", []),
        "festivals": d.get("festivals", []),
    }
