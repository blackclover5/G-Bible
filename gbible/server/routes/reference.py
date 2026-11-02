from .common import *

# ------------------------------------------------------------------- maps
@endpoint("maps/list")
def _maps_list(parts, q):
    """Every installed historical map, with whether it has been aligned.

    `calibrated` is the honest bit: a scan has no coordinates of its own, so a
    map can be listed and fully readable and still have nowhere to put a place
    until somebody has said where two of them are on the picture.
    """
    return _ok(maps=maps.maps())


@endpoint("maps/get")
def _maps_get(parts, q):
    return maps.map_detail(q.get("id", ""))


@endpoint("maps/places")
def _maps_places(parts, q):
    """The gazetteer, searched by name, by alternative name, or by reference.

    Separate from the older `places` route because this one can also answer
    "what is within 30km of here", which is the question a reader has while
    looking at a map and the one a bounding box cannot answer without cutting
    off the answer.
    """
    near = radius = None
    if q.get("lat") and q.get("lon"):
        try:
            near = (float(q["lat"]), float(q["lon"]))
            radius = float(q.get("radius_km") or 50)
        except (TypeError, ValueError):
            near = None
    return _ok(places=maps.places(q.get("q") or "", near=near,
                                  radius_km=radius,
                                  limit=int(q.get("limit") or 400)))


@endpoint("maps/calibrate")
def _maps_calibrate(parts, q):
    """Align a map from two control points, or forget the alignment."""
    mid = q.get("id", "")
    if q.get("clear"):
        return maps.clear_calibration(mid)
    return maps.set_calibration(mid, _obj(q.get("a")) or {}, _obj(q.get("b")) or {})


# ------------------------------------------------------------------- geocode
@endpoint("maps/geocode")
def _maps_geocode(parts, q):
    """Turn a modern place name into coordinates, with Nominatim.

    This is the other half of the gazetteer.  334 Bible places is a thin
    gazetteer -- Gilead, Jericho, Hebron, Beersheba, Nazareth, Moab are all
    missing from it -- and the reader still wants to know where the place they
    just read about ended up.  Nominatim answers that for the modern world
    rather than for the biblical one, which is exactly what is wanted and no
    more than that: the answer is a modern location, and it is labelled as one.

    Both refusals the registry can raise -- the service switched off, no
    network -- come back as a normal answer with the hint attached, because a
    missing geocoder is an inconvenience and not a fault in the reader's
    library.
    """
    term = (q.get("q") or "").strip()
    if not term:
        return _ok(query="", places=[], note="Type a place name.")
    try:
        return _ok(**maps.geocode(term, limit=int(q.get("limit") or 6),
                                  region=q.get("region", "near_east")))
    except apireg.ApiError as e:
        return _ok(query=term, places=[], error=str(e),
                   hint=getattr(e, "hint", ""))


@endpoint("maps/reverse")
def _maps_reverse(parts, q):
    """The modern names at a point, for a click on the base map."""
    try:
        lat = float(q.get("lat"))
        lon = float(q.get("lon"))
    except (TypeError, ValueError):
        return _ok(names=[], error="Give a latitude and a longitude.")
    try:
        return _ok(**maps.reverse(lat, lon))
    except apireg.ApiError as e:
        return _ok(names=[], error=str(e), hint=getattr(e, "hint", ""))


# --------------------------------------------------------------------- media
@endpoint("media/status")
def _media_status(parts, q):
    """Whether image search is switched on, before anything is sent."""
    return _ok(**media.status())


@endpoint("media/images")
def _media_images(parts, q):
    """Openverse image search, filtered to licences that permit reuse.

    The service gate, the rate limit and the week-long answer cache all live in
    the registry, so this endpoint is a thin translation of parameters; the
    refusal arrives as `error` plus the hint naming the screen to visit.
    """
    try:
        return _ok(**media.search(
            q.get("q", ""), page=int(q.get("page") or 1),
            source=q.get("source", ""), licence=q.get("license", ""),
            limit=int(q.get("limit") or 24)))
    except apireg.ApiError as e:
        return _ok(query=q.get("q", ""), results=[], count=0,
                   error=str(e), hint=getattr(e, "hint", ""))


@endpoint("media/audio")
def _media_audio(parts, q):
    """Openverse audio search, filtered to licences that permit reuse."""
    try:
        return _ok(**media.search(
            q.get("q", ""), page=int(q.get("page") or 1),
            source=q.get("source", ""), licence=q.get("license", ""),
            limit=int(q.get("limit") or 24), kind="audio"))
    except apireg.ApiError as e:
        return _ok(query=q.get("q", ""), results=[], count=0,
                   error=str(e), hint=getattr(e, "hint", ""))


@endpoint("media/sources")
def _media_sources(parts, q):
    return _ok(**media.sources())


@endpoint("bibleproject/search")
def _bp_search(parts, q):
    from ... import bibleproject as _bp
    return _ok(**_bp.search(q.get("q", ""), limit=int(q.get("limit") or 3)))


@endpoint("bibleproject/videos")
def _bp_videos(parts, q):
    from ... import bibleproject as _bp
    return _ok(**_bp.search(q.get("q", ""), limit=int(q.get("limit") or 3)))


# ------------------------------------------------------------------ grammar
@endpoint("grammar/health")
def _grammar_health(parts, q):
    """What is installed, and how much of the grammar that is."""
    return _ok(**grammar.health())


@endpoint("grammar/sections")
def _grammar_sections(parts, q):
    """The contents of the grammar: its sections, in order, numbered."""
    return _ok(**{"sections": grammar.sections(q.get("id", "")),
                  "modules": grammar.modules()})


@endpoint("grammar/read")
def _grammar_read(parts, q):
    """One section, rendered.  `unit` already does this; this names the job."""
    return _ok(**grammar.read(q.get("id", ""), q.get("key", "")))


@endpoint("grammar/search")
def _grammar_search(parts, q):
    """Full-text search inside the grammar."""
    return _ok(**grammar.search(q.get("q", ""), module_id=q.get("id", ""),
                                limit=int(q.get("limit") or 20)))


@endpoint("grammar/morph")
def _grammar_morph(parts, q):
    """What the grammar says about one morphology code.

    The other half of the word study: a reader who has clicked `HVqp3ms` wants
    the grammar, and this is the panel that answers.  The code is decoded with
    the same decoder Morph Search uses, so the two agree about what a code says.
    """
    return _ok(**grammar.morph(q.get("code", ""),
                               limit=int(q.get("limit") or 6)))


# --------------------------------------------------------------- Eusebius
@endpoint("eusebian/health")
def _eusebian_health(parts, q):
    """What the installed Eusebian table covers, and where it falls short."""
    return _ok(**eusebian.health())


@endpoint("eusebian/lookup")
def _eusebian_lookup(parts, q):
    """Every verse sharing one Ammonian number, column by column.

    The blank columns are the answer as much as the filled ones: which Gospels
    are empty is what says whether this is a four-way parallel or something only
    John has.
    """
    return eusebian.lookup(q.get("n") or q.get("q") or "")


@endpoint("eusebian/harmony")
def _eusebian_harmony(parts, q):
    canon_no = q.get("canon")
    if canon_no in (None, ""):
        canon_no = None
    else:
        try:
            canon_no = int(canon_no)
        except (TypeError, ValueError):
            return {"ok": False, "error": "canon must be a number from 1 to 10"}
    return eusebian.harmony(
        canon=canon_no,
        limit=min(2000, int(q.get("limit") or 400)),
        start=int(q.get("start") or 1))


@endpoint("eusebian/notation")
def _eusebian_notation(parts, q):
    """The Ammonian number for one verse.

    `ref` accepts what a reader would type -- "John 1:1" -- as well as the unit
    key, because the reader is looking at a verse, not at a database row.
    """
    raw = (q.get("ref") or q.get("q") or "").strip()
    keys = []
    if raw:
        r = canon.parse_ref(raw, q.get("v11n") or "KJV")
        if r:
            keys = [r.start.osis_id()]
        keys.append(raw.replace(" ", "."))
    for k in keys:
        n = eusebian.notation(k)
        if n:
            return _ok(ref=raw, key=k, notation=n)
    return _ok(ref=raw, notation="", note="no Ammonian number for that verse here")


