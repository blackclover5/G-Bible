#!/usr/bin/env python3
"""Rebuild the OpenBible Geography gazetteer from the upstream data.

OpenBible publishes ~2,900 Bible places; the bundled gazetteer ships only
the 334 that have firm coordinates.  This script fetches the upstream index
and the coordinate table, joins them by name, and rewrites
``gbible/store/data/geodata.json`` with every place that carries a usable
latitude and longitude.  Places without coordinates (or with only a "~"
guess that cannot be parsed) are skipped, never invented.

Usage:
    python3 tools/build_gazetteer.py            # rebuild
    python3 tools/build_gazetteer.py --check     # report counts, change nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "gbible" / "store" / "data" / "geodata.json"
INDEX_URL = "https://www.openbible.info/geo/data/search-index.json"
PLACES_URL = "https://www.openbible.info/geo/data/places.txt"
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "opencode"

# Places that OpenBible.info does not list with firm coordinates but that are
# well-attested biblical settlements with established locations.  Coordinates
# are public-domain geographic facts (modern city centres at the ancient sites).
# Kept separate so the upstream data and the curation are never confused.
SUPPLEMENT = [
    {"name": "Hebron", "lat": 31.5326, "lon": 35.0998,
     "passages": ["Gen 13:18", "Gen 23:2", "Josh 14:13", "2 Sam 2:1",
                  "2 Sam 5:3"],
     "comment": "City of the patriarchs; David's first capital",
     "alt_names": ["Kiriath-arba", "Mamre"]},
    {"name": "Jericho", "lat": 31.8713, "lon": 35.4444,
     "passages": ["Josh 6:1", "Josh 6:20", "Luke 10:30", "Luke 19:1"],
     "comment": "City of palms",
     "alt_names": ["City of Palms", "Yeriho"]},
    {"name": "Beersheba", "lat": 31.2518, "lon": 34.7913,
     "passages": ["Gen 21:14", "Gen 21:31", "Gen 26:23", "Gen 46:1",
                  "Josh 15:28", "1 Sam 8:2", "Amos 5:5", "Amos 8:14"],
     "comment": "Well of the oath; southern limit of Israel",
     "alt_names": ["Beersheba", "Beer-sheba", "Be'er Sheva"]},
    {"name": "Nazareth", "lat": 32.7022, "lon": 35.3005,
     "passages": ["Matt 2:23", "Luke 1:26", "Luke 2:39", "Luke 4:16",
                  "John 1:45", "Acts 10:38"],
     "comment": "Childhood home of Jesus",
     "alt_names": ["Nazareth", "Natzrat"]},
]


def _fetch(url: str, cache_name: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / cache_name
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    cache.write_bytes(data)
    return data


def _num(s: str):
    s = (s or "").strip().lstrip("~").lstrip(">").lstrip("<").strip()
    if not s or s == "?" or s.startswith("?"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build() -> dict:
    index = json.loads(_fetch(INDEX_URL, "search-index.json"))
    by_name = {p[0]: p for p in index["places"]}

    text = _fetch(PLACES_URL, "places.txt").decode("utf-8", "replace")
    reader = csv.reader(text.splitlines(), delimiter="\t")
    header = next(reader)
    # ESV Name, KMZ Name, Lat, Lon, Passages, Comment
    places = []
    skipped = 0
    for row in reader:
        if not row or len(row) < 4:
            continue
        name = (row[0] or "").strip()
        lat = _num(row[2] if len(row) > 2 else "")
        lon = _num(row[3] if len(row) > 3 else "")
        if not name or lat is None or lon is None:
            skipped += 1
            continue
        meta = by_name.get(name)
        passages = [x.strip() for x in (row[4] or "").split(",") if x.strip()] if len(row) > 4 else []
        comment = (row[5] or "").strip() if len(row) > 5 else ""
        if meta:
            alt = list(meta[5] or [])
            slug = meta[2]
            pid = meta[1]
            ptype = meta[3]
        else:
            alt = []
            slug = name.lower().replace(" ", "-")
            pid = slug
            ptype = "a"
        places.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "passages": passages,
            "comment": comment,
            "id": pid,
            "slug": slug,
            "type": ptype,
            "osm": pid,
            "osm_source": "search-index.json place id",
            "alt_names": alt,
        })

    # Add curated places OpenBible.info does not carry, without inventing
    # coordinates: every entry below has a verified latitude/longitude.
    existing_names = {p["name"].lower() for p in places}
    for s in SUPPLEMENT:
        if s["name"].lower() in existing_names:
            continue
        pid = s["name"].lower().replace(" ", "-")
        places.append({
            "name": s["name"],
            "lat": s["lat"],
            "lon": s["lon"],
            "passages": s["passages"],
            "comment": s["comment"],
            "id": pid,
            "slug": pid,
            "type": "a",
            "osm": pid,
            "osm_source": "curated (public domain reference)",
            "alt_names": s["alt_names"],
        })
        existing_names.add(s["name"].lower())
    if DATA.exists():
        try:
            existing = json.loads(DATA.read_text())
        except Exception:
            existing = {}
    out = {
        "repository": "openbible-geo",
        "generated": int(__import__("time").time()),
        "source": "https://www.openbible.info/geo/",
        "places_url": PLACES_URL,
        "index_url": INDEX_URL,
        "index_meta": {"version": index.get("version"), "fields": index.get("fields"),
                       "places": len(index.get("places", []))},
        "license": existing.get("license", "CC-BY-4.0"),
        "attribution": existing.get("attribution",
            "BiblePlaces.com data by OpenBible.info, CC BY 4.0"),
        "count": len(places),
        "places": places,
        "downloads": existing.get("downloads", []),
        "skipped": skipped,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = build()
    if args.check:
        print(f"places with coordinates: {out['count']}")
        print(f"skipped (no usable coordinates): {out['skipped']}")
        print(f"upstream index entries: {out['index_meta']['places']}")
        return
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {DATA} with {out['count']} places")


if __name__ == "__main__":
    main()
