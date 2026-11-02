"""Historical maps, and the Bible places that can be put on them.

The library holds four scanned historical maps -- an Ortelius Exodus route, a
1794 Anville map of the Holy Land, a map of the Crusader states, and the
Twelve Tribes map -- and separately a gazetteer of 334 Bible places, every one
of them with a latitude and a longitude.  Both were there and nothing joined
them, so a reader looking at a 1794 map of the Holy Land had no way to find
Jerusalem on it, and a reader who had found Jerusalem in the gazetteer had no
way to see it on any map.

That is not a formatting problem, it is the whole point of having a map.  But
it cannot be solved by plotting the coordinates, and this is the part worth
being careful about: **a scanned historical map has no coordinate system.**  It
is a picture of a projection made by someone in 1794, and lat/lon means nothing
on it until someone says where two known places ended up in the pixels.  The
longitude that runs down the left edge of the Anville sheet is not the
longitude of anything, and no amount of reading metadata will recover it.

So this module does the honest version.  It ships no pretend alignment: a map
has no overlay until the reader calibrates it, by naming two places they can
find on the picture and clicking each one.  Two points fix a similarity
transform -- a scale, a rotation and a shift -- which is the correct model for a
sheet that has been scanned flat, and it is why exactly two are asked for rather
than the three a full affine would need.  The calibration is stored per map and
remembered, so it is asked for once and never again.

The gazetteer, meanwhile, is useful on its own without any map at all, and it is
deliberately usable that way: every place carries the verses that name it, so
the search finds "Gilead" by name, by alternative name, or by the reference that
mentions it, and goes to the text.
"""
from __future__ import annotations

import json
import math
import re
import struct
from pathlib import Path

from . import db, library, store

#: Where a calibration lives.  Settings rather than a table of its own: it is one
#: small JSON blob per map, it is only ever read whole, and a map the reader
#: never calibrates simply has no row.
_CALIB_KEY = "map_calibration:"


# --------------------------------------------------------------------------
# the gazetteer
# --------------------------------------------------------------------------

def places(term: str = "", *, limit: int = 400,
           near: tuple[float, float] | None = None,
           radius_km: float | None = None) -> list[dict]:
    """Bible places, searchable by name, by alternative name, or by reference.

    `near`/`radius_km` filter by distance from a point.  That is what makes a
    map useful rather than decorative -- "what is near here" is the question a
    reader has looking at a map, and answering it needs the distance, not the
    rectangle a bounding box would cut off.  A great-circle distance is used
    rather than a projected one because the gazetteer spans the whole Near East
    and the only place the error would matter is over a few hundred kilometres,
    where it does not.
    """
    raw = store.load_catalog("openbible-geo").get("places", [])
    t = (term or "").strip().lower()
    scored: list[tuple[int, dict]] = []
    for p in raw:
        if p.get("lat") is None or p.get("lon") is None:
            continue
        rank = 0
        if t:
            name = (p.get("name") or "").lower()
            alts = [a.lower() for a in (p.get("alt_names") or [])]
            refs = " ".join(p.get("passages") or []).lower()
            if name == t:
                rank = 4
            elif name.startswith(t):
                rank = 3
            elif t in name:
                rank = 2
            elif any(a.startswith(t) for a in alts):
                rank = 2
            elif t in alts:
                rank = 1
            elif t and t in refs:
                rank = 1
            else:
                continue
        if near is not None and radius_km is not None:
            d = _haversine(near[0], near[1], p["lat"], p["lon"])
            if d > radius_km:
                continue
            p = dict(p, distance_km=round(d, 1))
            rank = rank or 1
        scored.append((rank, p))
    if near is not None and radius_km is not None and not t:
        # Distance, not the name.  A proximity search that answered alphabetically
        # put "Achzib" -- twenty-three kilometres away -- at the head of the
        # list of everything near Jerusalem, and that reads as the nearest place
        # and is nothing of the kind.  Rank is dropped entirely in this mode
        # because a text query is not in play to outrank anything with.
        scored.sort(key=lambda rp: rp[1]["distance_km"])
    else:
        scored.sort(key=lambda rp: (-rp[0], rp[1].get("distance_km")
                                    if rp[1].get("distance_km") is not None
                                    else 0.0,
                                    (rp[1].get("name") or "")))
    out = []
    for _rank, p in scored[:max(1, limit)]:
        out.append({
            "id": p.get("id"), "slug": p.get("slug"),
            "name": p.get("name"), "alt_names": p.get("alt_names") or [],
            "lat": p["lat"], "lon": p["lon"], "type": p.get("type") or "",
            "comment": p.get("comment") or "",
            "passages": p.get("passages") or [],
            "distance_km": p.get("distance_km"),
        })
    return out


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_CONTROL_PREFERENCE = (
    # Named in the order they would be offered, most conspicuous first.  These
    # are the labels a map of this region actually carries -- an eighteenth-
    # century sheet prints Jerusalem, Hebron and Mount Carmel, not a modern
    # toponym.  Jericho would be the obvious second choice and is deliberately
    # not the fallback: it is absent from the gazetteer, so a list naming it
    # offers the reader a control that cannot be completed.
    "Jerusalem", "Hebron", "Beersheba", "Mount Carmel", "Jericho",
    "Nazareth", "Bethlehem", "Gaza", "Tyre", "Sidon", "Damascus",
    "Mount Gerizim", "Mount Ebal", "Shiloh", "Lachish", "Gath", "Megiddo",
    "Sinai", "Arnon", "Euphrates", "Lebanon",
)


def _suggested_controls() -> list[dict]:
    """Two places to offer first when calibrating.

    Any two points work; these two are offered because they are easy to find on
    a printed map.  The list is walked in preference order for the *first*
    control -- the most conspicuous place on the sheet -- and the second is then
    whichever available candidate is **farthest** from it.

    Farthest, not simply second, because the pair is what fixes the map's scale
    and its angle, and a pair a few kilometres apart fixes both badly: two
    points close together make a rotation almost unconstrained, and the result
    is a map that looks right and is subtly wrong everywhere except the two
    places it was set from.  The gazetteer installed here holds 334 places and
    most of them are minor settlements of the Hebrew Bible -- Hebron, Beersheba,
    Jericho and Nazareth are all absent -- so the widest separation available is
    not always a famous city, and asking for the widest one is how the feature
    keeps working on a gazetteer this thin.
    """
    allp = places(limit=1000)
    by_name = {(p["name"] or "").lower(): p for p in allp}
    avail = [by_name[w.lower()] for w in _CONTROL_PREFERENCE
             if w.lower() in by_name]
    if len(avail) < 2:
        return avail
    first = avail[0]
    second = max(avail[1:],
                 key=lambda p: _haversine(first["lat"], first["lon"],
                                          p["lat"], p["lon"]))
    return [first, second]


# --------------------------------------------------------------------------
# modern names, from Nominatim
# --------------------------------------------------------------------------
#
# The gazetteer above is *biblical*: 334 places, weighted towards minor
# settlements of the Hebrew Bible, and missing Gilead, Jericho, Hebron,
# Beersheba, Nazareth, Canaan and Moab.  Nominatim is the opposite: a modern
# gazetteer of the inhabited world, which resolves the names the Bible gives to
# places that still exist under other names.  It cannot answer "where was
# Ekron", because Ekron is not on the modern map; it answers "where is Bethlehem
# now", which is the question a reader has after reading about it.  Both are
# said out loud in the response rather than blended into one list.

#: A geocode older than this is asked again.  A month: toponyms change, but not
#: often, and the quota is one request a second for the rest of the internet.
_GEO_TTL = 30 * 86400

#: What kind of thing each Nominatim answer is, in words.  The raw type is a
#: code ("administrative", "village", "church") and a reader deciding between
#: three places named Beit Jala cannot tell them apart without it.
_GEO_KIND = {
    "city": "city", "town": "town", "village": "village", "hamlet": "hamlet",
    "municipality": "town", "suburb": "suburb", "neighbourhood": "neighbourhood",
    "quarter": "quarter", "borough": "district", "administrative": "administrative area",
    "state": "region", "province": "region", "county": "county",
    "region": "region", "country": "country", "continent": "continent",
    "island": "island", "islet": "islet", "lake": "lake", "river": "river",
    "peak": "mountain", "volcano": "volcano", "hill": "hill", "cave_entrance": "cave",
    "forest": "wood", "wood": "wood", "park": "park", "nature_reserve": "nature reserve",
    "attraction": "place of interest", "museum": "museum", "church": "church",
    "monument": "monument", "memorial": "memorial", "castle": "castle",
    "ruins": "ruins", "archaeological_site": "archaeological site",
    "bus_station": "bus station", "railway_station": "railway station",
    "airport": "airport", "hospital": "hospital", "school": "school",
    "hotel": "hotel", "building": "building", "house": "house",
}


#: The box the ancient Near East sits in: Sinai to the Lebanon and Syria the
#: Bible writes about, Hebron to Dan.  Damascus is in it (33.5N) and Cyprus is
#: not.  Passed to Nominatim as a viewbox so that "Bethlehem" finds the town in
#: Judea rather than the four other Bettileems with the same name.  It is a
#: default the reader can widen, not a hidden filter -- see `geocode`.
NEAR_EAST = (29.0, 31.5, 35.5, 37.5)   # south, west, north, east

_REGIONS = {"near_east": ("the ancient Near East", NEAR_EAST),
            "": ("everywhere", None)}

#: A shop is not where a city is, and a street named after Damascus is not
#: Damascus.  Nominatim ranks free text by string match and prominence, so
#: without this a search for "Tyre" returns a tyre shop and a search for
#: "Damascus" returns ten streets called Damascus Street.  Dropped rather than
#: ranked down, because the answer list is six rows long and a list of six
#: streets is not a thinner answer, it is a different one.
_GEO_DROP = ("shop", "highway", "craft", "office", "aeroway", "railway")

#: What sorts to the top.  A settlement first, because the reader typed a place
#: name; then the landforms, because "Jordan" and "Carmel" are rivers and
#: mountains before they are anything else; then whatever is left.
_GEO_RANK = {"place": 0, "boundary": 1, "natural": 2, "waterway": 3,
             "historic": 4, "man_made": 5, "tourism": 6, "amenity": 7}


def geocode(term: str, *, limit: int = 6, region: str = "near_east") -> dict:
    """Look a modern place name up, returning coordinates.

    **The search is bounded to the Near East by default, and says so.**  A plain
    Nominatim search for "Bethlehem" ranks by modern prominence and returns
    Bethlehem, Pennsylvania, followed by three more, with the town in Judea
    somewhere below -- which is a correct answer to the wrong question and reads
    in this application as a bug.  The viewbox is passed as a *bounding* box, so
    results outside it are excluded rather than demoted, and the response names
    the region so the panel can show it.

    A reader looking for a Bethlehem elsewhere asks for it: the region is one
    parameter, the UI offers it as a checkbox, and `region=""` searches
    everywhere.  Nothing is hidden either way.

    The answer is a *modern* location and is labelled `modern`, because the
    difference matters: the region filter is about which Bethlehem, not about
    turning a modern map into a biblical one, and a name the Bible uses for a
    place that no longer exists simply will not be found -- which is reported
    rather than papered over with a fuzzy match somewhere else.

    A reverse lookup is not attempted per result.  Nominatim's policy is one
    request a second and it counts every request, and six answers per search is
    already six requests the reader did not ask for individually.
    """
    from .api import registry as apireg
    label, box = _REGIONS.get(region if region is not None else "",
                               _REGIONS["near_east"])
    key = f"fwd|{region}|" + " ".join(term.lower().split())
    hit = apireg.cache_get("nominatim", key, kind="geocode", max_age=_GEO_TTL)
    if hit is not None:
        return dict(hit, cached=True)
    params: dict = {"q": term, "format": "jsonv2",
                    "limit": 10,
                    "addressdetails": 1, "namedetails": 1,
                    # Without this the name comes back in the local script --
                    # بيت لحم for Bethlehem and أريحا for Jericho -- which is a
                    # correct answer to a question this application did not
                    # ask.  The local name is kept in `local` beside it, so
                    # nothing is lost by asking in English.
                    "accept-language": "en"}
    # Two questions, because neither one alone is the right one.  The worldwide
    # search ranks by modern prominence and so finds Damascus; it also returns
    # four Bettileems and no Kafr Kanna, because Cana in Galilee is a village
    # and Cana in Italy is a comune.  The bounded search finds the local names,
    # and demotes the big city -- Nominatim's viewbox scoring prefers what lies
    # near the middle of the box, so Damascus at 33.5N loses to a gate in
    # Jerusalem at 31.8N.  Both are asked and merged, one second apart.
    asks = [dict(params)]
    if box:
        asks.append(dict(params, viewbox=",".join(str(x) for x in box),
                         bounded=1))
    seen: set[tuple] = set()
    rows: list[dict] = []
    for ask in asks:
        raw = apireg.call("nominatim", "search", params=ask)
        if not isinstance(raw, list):
            continue
        for r in raw:
            if not isinstance(r, dict):
                continue
            try:
                k = (round(float(r.get("lat")), 3), round(float(r.get("lon")), 3))
            except (TypeError, ValueError):
                continue
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
    out = []
    for r in rows:
        cat = (r.get("category") or "").lower()
        if cat in _GEO_DROP:
            continue
        try:
            lat = float(r.get("lat"))
            lon = float(r.get("lon"))
        except (TypeError, ValueError):
            continue
        # The region is *our* filter, applied to the service's answer, rather
        # than a viewbox the service then scores against -- see above.
        if box and not (box[0] <= lat <= box[2] and box[1] <= lon <= box[3]):
            continue
        addr = r.get("address") or {}
        out.append({
            "name": r.get("name") or (addr.get("city") or addr.get("town")
                                      or addr.get("village") or term),
            "local": r.get("namedetails", {}).get("name")
            if isinstance(r.get("namedetails"), dict) else "",
            "display": r.get("display_name") or "",
            "lat": lat, "lon": lon,
            "kind": _GEO_KIND.get((r.get("type") or r.get("class") or "").lower(),
                                  (r.get("type") or "").replace("_", " ")),
            "category": cat,
            "rank": _GEO_RANK.get(cat, 9),
            "osm_type": r.get("osm_type") or "",
            "osm_id": r.get("osm_id") or "",
            "importance": r.get("importance") or 0,
            "country": (addr.get("country") or ""),
            "country_code": (addr.get("country_code") or "").upper(),
            "state": addr.get("state") or addr.get("region") or "",
            "url": ("https://www.openstreetmap.org/"
                    f"{r.get('osm_type', 'node')}/{r.get('osm_id')}"),
            "place_id": r.get("place_id"),
            "source": "modern location, from OpenStreetMap",
        })
    # Settlements first, then landforms, then the rest.  Nominatim's own order
    # is by string match, which is why "Damascus" put a gate in Jerusalem above
    # the city and "Cana" put a wedding venue above the village.
    out.sort(key=lambda p: (p["rank"], -(p["importance"] or 0), p["name"]))
    payload = {"ok": True, "query": term, "places": out[:max(1, limit)],
               "cached": False,
               "region": label, "bounded": bool(box),
               "note": ("Searched " + label + ", and only places inside it are "
                        "listed. These are modern locations; the Bible "
                        "gazetteer above is the separate list of Bible "
                        "places, and a place the Bible names that no longer "
                        "exists will not be found here."
                        if out else
                        "Nothing found in " + label + " for that name. Widen "
                        "the search, or try the modern name -- Ekron is "
                        "Kiryat Ekron, and a biblical place that no longer "
                        "exists cannot be geocoded at all."),
               "attribution": "© OpenStreetMap contributors, ODbL, via "
                              "Nominatim."}
    apireg.cache_put("nominatim", key, payload, kind="geocode")
    return payload


def reverse(lat: float, lon: float) -> dict:
    """What is at this point, in modern terms.

    Used when a reader clicks the base map rather than searching: a click is a
    question about a location, and answering it with the nearest modern name is
    what makes the click worth making.
    """
    from .api import registry as apireg
    key = f"rev|{lat:.5f},{lon:.5f}"
    hit = apireg.cache_get("nominatim", key, kind="reverse", max_age=_GEO_TTL)
    if hit is not None:
        return dict(hit, cached=True)
    raw = apireg.call("nominatim", "reverse", params={
        "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2",
        "addressdetails": 1, "namedetails": 1, "zoom": 12,
    })
    addr = (raw or {}).get("address") or {}
    names = []
    for k in ("city", "town", "village", "municipality", "county", "state",
              "country"):
        v = addr.get(k)
        if v and v not in names:
            names.append(v)
    payload = {
        "ok": True, "lat": lat, "lon": lon,
        "name": (raw or {}).get("name") or (names[0] if names else ""),
        "display": (raw or {}).get("display_name") or "",
        "names": names,
        "kind": (raw or {}).get("type") or "",
        "address": addr, "cached": False,
        "attribution": "© OpenStreetMap contributors, ODbL, via Nominatim.",
    }
    apireg.cache_put("nominatim", key, payload, kind="reverse")
    return payload


# --------------------------------------------------------------------------
# the maps
# --------------------------------------------------------------------------

def maps() -> list[dict]:
    """Every installed historical map, with its licence and whether it is set up.

    `size` is read out of the image header rather than the file, because it is
    what the calibration is expressed in: the reader clicks a pixel, and a
    calibration in pixels is meaningless without knowing how many of them the
    sheet has.  Reading it also catches a truncated download, which a map whose
    attribution is present but whose image is 4k of grey is otherwise silent
    about.
    """
    out = []
    for m in library.list_all(type_="Map"):
        row = db.connect().execute(
            "SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
            (m.id,)).fetchone()
        extra = {}
        if row is not None:
            try:
                extra = json.loads(row["extra"] or "{}")
            except (json.JSONDecodeError, TypeError):
                extra = {}
        d = library.module_dir(m.id)
        fname = extra.get("image") or ""
        fpath = (d / fname) if (d and fname) else None
        out.append({
            "id": m.id, "name": m.name, "folder": m.folder or m.id,
            "url": f"/media/{m.folder or m.id}/{fname}" if fname else "",
            "filename": fname, "title": row["title"] if row else m.name,
            "caption": row["ref_label"] if row else "",
            "attribution": extra.get("attribution") or "",
            "source": extra.get("source") or "",
            "license": m.license or "", "author": m.author or "",
            "size": image_size(fpath) if fpath else None,
            "calibrated": bool(calibration(m.id)),
            "subject": m.subject or "",
        })
    return out


def map_detail(module_id: str) -> dict:
    """One map, its calibration, and as much of its gazetteer as is on it.

    When the map is calibrated the places are returned in *image pixels*, so the
    front end can place a marker without knowing any geography.  When it is not,
    they are returned with coordinates and no pixel position and an explicit
    reason, because "nothing appeared" and "this map has not been set up yet"
    are very different things to be looking at.
    """
    ms = [m for m in maps() if m["id"] == module_id]
    if not ms:
        return {"ok": False, "error": "no such map installed"}
    m = ms[0]
    cal = calibration(module_id)
    out = {"ok": True, "map": m, "calibration": cal,
           "size": m.get("size"), "controls": _suggested_controls()}
    if not m.get("url"):
        out["note"] = ("This map's image is missing from the library, so there "
                       "is nothing to show. Re-install it from the Store.")
        out["places"] = []
        return out
    if not m.get("size"):
        out["note"] = ("The image file could not be read, so the places cannot "
                       "be placed on it. Re-install it from the Store.")
        out["places"] = []
        return out
    if not cal:
        out["note"] = ("This map has not been aligned yet, so the places have "
                       "no position on it. A scanned historical map carries no "
                       "coordinates of its own: click two places you can find on "
                       "the picture and the rest will fall into place.")
        out["places"] = []
        return out
    ps = []
    for p in places(limit=1000):
        xy = project(cal, p["lat"], p["lon"])
        if xy is None:
            continue
        w, h = m["size"]["width"], m["size"]["height"]
        x, y = xy
        # A point off the sheet is a sign the two chosen controls were not on the
        # same map feature -- a harbour labelled at a different point than the
        # city, or a second Jerusalem.  Dropping it is better than a marker in
        # the corner, which reads as a real answer.
        if not (-0.02 * w <= x <= 1.02 * w and -0.02 * h <= y <= 1.02 * h):
            continue
        ps.append(dict(p, x=round(x, 1), y=round(y, 1)))
    out["places"] = ps
    out["count"] = len(ps)
    return out


# --------------------------------------------------------------------------
# calibration
# --------------------------------------------------------------------------

def calibration(module_id: str) -> dict | None:
    """The two control points a map has been aligned with, if it has any."""
    raw = db.get_setting(_CALIB_KEY + module_id)
    if isinstance(raw, str):                 # written as a JSON string once
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, dict) or not _cal_valid(raw):
        return None
    cal = dict(raw)
    cal["module_id"] = module_id
    return cal


def set_calibration(module_id: str, a: dict, b: dict) -> dict:
    """Align a map from two control points.

    `a` and `b` are `{name, lat, lon, x, y}`: a place the reader can find on the
    picture and where they clicked it.  Two, not three, because two fix a
    similarity transform and that is the right model here -- see the module
    docstring.  The two must be far enough apart to pin a rotation down; two
    points a hundred pixels apart give a scale and a shift and leave the angle
    undetermined, which shows up later as a map that is subtly, convincingly
    wrong.  So the separation is required, and reported in the message that says
    why.
    """
    m = library.get(module_id)
    if m is None or m.type != "Map":
        return {"ok": False, "error": "no such map installed"}
    size = image_size((library.module_dir(module_id) or Path(".")) /
                      _first_image(module_id))
    if not size:
        return {"ok": False, "error": "the map's image cannot be read"}
    clean = []
    for p in (a, b):
        try:
            clean.append({
                "name": str(p.get("name") or "")[:80],
                "lat": float(p["lat"]), "lon": float(p["lon"]),
                "x": float(p["x"]), "y": float(p["y"]),
            })
        except (KeyError, TypeError, ValueError):
            return {"ok": False,
                    "error": "each control needs a place and a point on the "
                             "image (name, lat, lon, x, y)"}
    ax, ay = clean[0]["x"], clean[0]["y"]
    bx, by = clean[1]["x"], clean[1]["y"]
    if math.hypot(bx - ax, by - ay) < 60:
        return {"ok": False,
                "error": "the two points are too close together to fix the "
                         "map's angle; pick two further apart."}
    if abs(clean[0]["lat"] - clean[1]["lat"]) < 1e-9 and \
            abs(clean[0]["lon"] - clean[1]["lon"]) < 1e-9:
        return {"ok": False, "error": "the two points are the same place"}
    cal = {"a": clean[0], "b": clean[1], "size": size}
    db.set_setting(_CALIB_KEY + module_id, cal)
    return {"ok": True, "calibration": dict(cal, module_id=module_id),
            "note": "Aligned. The places will be placed on this map from now on."}


def clear_calibration(module_id: str) -> dict:
    """Forget a map's alignment, so it can be done again differently."""
    conn = db.connect()
    conn.execute("DELETE FROM setting WHERE key=?", (_CALIB_KEY + module_id,))
    conn.commit()
    return {"ok": True, "still_set": calibration(module_id) is not None}


def _cal_valid(cal) -> bool:
    try:
        a, b = cal["a"], cal["b"]
        for p in (a, b):
            for k in ("lat", "lon", "x", "y"):
                float(p[k])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def project(cal: dict, lat: float, lon: float) -> tuple[float, float] | None:
    """Where a latitude and longitude fall in the pixels of an aligned map.

    A similarity transform, in a local equirectangular frame: x is longitude
    scaled by the cosine of the mean latitude and y is latitude.  Over the span
    of a single sheet that is indistinguishable from a proper projection and,
    unlike a proper one, is four lines of arithmetic with no dependency -- and
    what is being corrected for is a scan of somebody else's projection, so
    insisting on a rigorous one of our own would be misplaced precision.
    """
    a, b = cal["a"], cal["b"]
    lat0 = (a["lat"] + b["lat"]) / 2.0
    k = math.cos(math.radians(lat0))
    px1, py1 = a["lon"] * k, -a["lat"]
    px2, py2 = b["lon"] * k, -b["lat"]
    qx1, qy1 = a["x"], a["y"]
    qx2, qy2 = b["x"], b["y"]
    dvx, dvy = px2 - px1, py2 - py1
    dwx, dwy = qx2 - qx1, qy2 - qy1
    dv = math.hypot(dvx, dvy)
    dw = math.hypot(dwx, dwy)
    if dv < 1e-12 or dw < 1e-12:
        return None
    # cos and sin of the rotation, straight from the dot and cross of the two
    # vectors -- no atan2, and no branch for a mirror-image scan.
    cos_t = (dvx * dwx + dvy * dwy) / (dv * dw)
    sin_t = (dvx * dwy - dvy * dwx) / (dv * dw)
    tx = qx1 - (cos_t * px1 - sin_t * py1) * (dw / dv)
    ty = qy1 - (sin_t * px1 + cos_t * py1) * (dw / dv)
    pxx, pyy = lon * k, -lat
    return (cos_t * pxx - sin_t * pyy) * (dw / dv) + tx, \
           (sin_t * pxx + cos_t * pyy) * (dw / dv) + ty


def _first_image(module_id: str) -> str:
    row = db.connect().execute(
        "SELECT extra FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
        (module_id,)).fetchone()
    if row is None:
        return ""
    try:
        return (json.loads(row["extra"] or "{}").get("image") or "")
    except (json.JSONDecodeError, TypeError):
        return ""


# --------------------------------------------------------------------------
# image dimensions, without an image library
# --------------------------------------------------------------------------

_SOI = {b"\xff\xd8": "jpeg", b"\x89PNG": "png", b"GIF8": "gif", b"BM": "bmp",
        b"II*\x00": "tiff", b"MM\x00*": "tiff", b"RIFF": "webp"}


def image_size(path: Path | None) -> dict | None:
    """`{width, height, kind}` read from the file's own header.

    Deliberately by hand, for the same reason the rest of this project is: a
    dependency that exists only to read four integers out of a header is not a
    dependency worth taking, and the formats actually installed here are a
    handful of fixed byte layouts.  Unknown or truncated files answer None,
    which the callers turn into an honest sentence rather than a crash.
    """
    if path is None:
        return None
    try:
        if str(path).lower().endswith(".svg"):
            return _svg_size(path)
        with open(path, "rb") as fh:
            head = fh.read(32)
            if not head:
                return None
            kind = next((v for k, v in _SOI.items() if head.startswith(k)), "")
            if head.lstrip()[:4].lower() == b"<svg" or b"<svg" in head.lower():
                return _svg_size(path)
            if kind == "png" and len(head) >= 24 and head[12:16] == b"IHDR":
                w, h = struct.unpack(">II", head[16:24])
                return {"width": w, "height": h, "kind": "png"}
            if kind == "gif" and len(head) >= 10:
                w, h = struct.unpack("<HH", head[6:10])
                return {"width": w, "height": h, "kind": "gif"}
            if kind == "bmp" and len(head) >= 26:
                w, h = struct.unpack("<ii", head[18:26])
                return {"width": abs(w), "height": abs(h), "kind": "bmp"}
            if kind == "webp":
                return _webp_size(fh)
            if kind == "jpeg":
                return _jpeg_size(fh)
            if kind == "tiff":
                return _tiff_size(fh)
    except OSError:
        return None
    return None


def _svg_size(path: Path) -> dict | None:
    """Dimensions from an SVG root element.

    A vector map has no pixel size of its own, so this prefers the `viewBox` --
    which is the only value that is actually true of the drawing -- and falls
    back to `width`/`height`, which are usually there for print and are fine for
    placing a marker.  When the root carries neither, the drawing is reported at
    a nominal 1000 units square, and the map detail says so rather than
    pretending to a size nobody can rely on.

    The Twelve Tribes map installed here is an SVG, so this is not a
    hypothetical format: it is one of the four maps in this library.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    m = re.search(r'viewBox\s*=\s*["\']\s*[-\d.]+[,\s]+[-\d.]+[,\s]+'
                  r'([\d.]+)[,\s]+([\d.]+)', head, re.I)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w > 0 and h > 0:
            return {"width": round(w), "height": round(h), "kind": "svg",
                    "basis": "viewBox"}
    wm = re.search(r'\bwidth\s*=\s*["\']([\d.]+)', head, re.I)
    hm = re.search(r'\bheight\s*=\s*["\']([\d.]+)', head, re.I)
    if wm and hm:
        w, h = float(wm.group(1)), float(hm.group(1))
        if w > 0 and h > 0:
            return {"width": round(w), "height": round(h), "kind": "svg",
                    "basis": "width/height"}
    if "<svg" in head.lower():
        return {"width": 1000, "height": 1000, "kind": "svg",
                "basis": "nominal", "estimated": True}
    return None


def _jpeg_size(fh) -> dict | None:
    """Scan JPEG markers for a start-of-frame, which carries the dimensions.

    The marker has to be walked rather than read at a fixed offset: the length
    of each segment varies, and the SOF that matters is whichever comes first.
    """
    fh.seek(2)
    while True:
        b = fh.read(1)
        if not b:
            return None
        if b != b"\xff":
            continue
        m = fh.read(1)
        while m == b"\xff":
            m = fh.read(1)
        if not m:
            return None
        code = m[0]
        if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
            continue
        seg = fh.read(2)
        if len(seg) < 2:
            return None
        ln = struct.unpack(">H", seg)[0]
        if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            body = fh.read(5)
            if len(body) < 5:
                return None
            h, w = struct.unpack(">HH", body[1:5])
            return {"width": w, "height": h, "kind": "jpeg"}
        if code == 0xDA:                  # start of scan: no dimensions past here
            return None
        fh.seek(max(0, ln - 2), 1)


def _tiff_size(fh) -> dict | None:
    """TIFF tags are a little-endian or big-endian IFD; read both.

    No TIFF is installed here, so this is completeness rather than necessity --
    but a map is exactly the sort of file that arrives as a TIFF from a museum,
    and returning None for one means "re-install from the Store", which is a
    poor answer to a file that is present and readable.
    """
    fh.seek(0)
    head = fh.read(8)
    if len(head) < 8:
        return None
    le = head[:2] == b"II"
    end = "<" if le else ">"
    w = h = None
    try:
        off = struct.unpack(end + "I", head[4:8])[0]
        fh.seek(off)
        n = struct.unpack(end + "H", fh.read(2))[0]
        for _ in range(n):
            tag, typ, _cnt = struct.unpack(end + "HHI", fh.read(8))
            val = fh.read(4)
            if tag not in (256, 257):
                continue
            v = (struct.unpack(end + "H", val[:2])[0] if typ == 3
                 else struct.unpack(end + "I", val)[0])
            if tag == 256:
                w = v
            else:
                h = v
            if w is not None and h is not None:
                return {"width": w, "height": h, "kind": "tiff"}
    except (struct.error, OSError):
        return None
    return None


def _webp_size(fh) -> dict | None:
    fh.seek(12)
    tag = fh.read(4)
    try:
        if tag == b"VP8X":
            b = fh.read(10)
            w = 1 + int.from_bytes(b[4:7], "little")
            h = 1 + int.from_bytes(b[7:10], "little")
            return {"width": w, "height": h, "kind": "webp"}
        if tag == b"VP8 ":
            b = fh.read(10)
            return {"width": struct.unpack("<H", b[6:8])[0] & 0x3FFF,
                    "height": struct.unpack("<H", b[8:10])[0] & 0x3FFF,
                    "kind": "webp"}
        if tag == b"VP8L":
            b = fh.read(5)
            n = int.from_bytes(b[1:5], "little")
            return {"width": (n & 0x3FFF) + 1,
                    "height": ((n >> 14) & 0x3FFF) + 1, "kind": "webp"}
    except (struct.error, OSError, IndexError):
        return None
    return None
