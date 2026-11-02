"""Images: the one thing the library cannot supply and the reader will want.

Everything else in this application is text that arrived with a module, and the
Store is where more of it comes from.  A picture of a place, a person, a
painting of the exodus, a photograph of the Dead Sea -- none of that is
something a SWORD repository carries, and none of it is something this project
can host.  So the media gap is a *search* problem, not a download problem, and
Openverse is the search: one index over Flickr, Wikimedia, museums, libraries and
a dozen others, filtered to licences that permit reuse.

Two things make this worth building rather than a link out to the Openverse
website.

**The licence is the product.**  An image search that mixes CC0 with
non-commercial and no-derivatives results and shows them in one grid is a
licence problem wearing a search box's clothes.  So the licence is a filter that
defaults to the three that permit reuse without conditions the reader would then
have to honour invisibly -- `cc0`, `pdm`, `by` -- and everything withheld is
counted and named in the response, because "twelve results, nine of them were
non-commercial" is information and a silent drop is not.  The same line the Store
draws for CC BY-SA applies here: a share-alike image is not offered by default.

**The anonymous quota is small enough that the cache is the feature.**  Openverse
allows an unauthenticated caller 100 requests a day and 5 an hour.  A reader
typing "Bethlehem" gets several pages of suggestions for that word before the
hour is gone, so an answer is cached for a week in the existing `api_cache` table
and a repeat search costs nothing.  A key raises the limit and the Settings
screen says so; adding one is still the reader's decision.

The attribution Openverse builds for each result is kept verbatim and shown with
the image.  This project's rule is that attribution is not optional on anything
it puts in front of somebody, and an image found by somebody else is no
different from a module installed from the Store -- it has an author and a
licence and both are named.
"""
from __future__ import annotations

from .api import registry as apireg

#: The service this module talks to.  Named once so the id cannot drift between
#: the endpoint, the cache key and the enablement check.
SERVICE = "openverse"

#: Licences offered without being asked for.  `cc0` and `pdm` are public-domain
#: dedications with nothing to honour; `by` requires a credit line, which this
#: module always shows.  Everything else -- non-commercial, no-derivatives,
#: share-alike -- changes what the reader may do with the result, so it is
#: behind an explicit choice rather than a filter chip.
REUSABLE = ("cc0", "pdm", "by")

#: Shown beside a withheld result so the reader can see what was passed over.
_WITHHELD = {
    "by-sa": "share-alike: reuse is conditional on licensing your own work alike",
    "by-nc": "non-commercial only",
    "by-nd": "no derivatives: it may not be cropped or edited",
    "by-nc-sa": "non-commercial and share-alike",
    "by-nc-nd": "non-commercial, no derivatives",
    "sampling+": "sampling licence: terms apply",
    "nc-sampling+": "non-commercial sampling licence: terms apply",
    "deviations": "deviations licence: terms apply",
    "nc-deviations": "non-commercial deviations licence: terms apply",
}

#: An answer older than this is asked again.  A week, because the quota is
#: 100 a day and an image that exists today exists next week too.
_TTL = 7 * 24 * 3600

#: Providers kept for the Media panel.  The panel is meant for biblical work, so
#: nature, science, space, marine and maker sites are dropped and only the
#: museums, archives, libraries and general photo pools that actually carry
#: biblical imagery remain.  The list is keyed on Openverse's source_name.
BIBLICAL_SOURCES = {
    "flickr", "wikimedia", "europeana", "rawpixel", "met",
    "wellcome_collection", "brooklynmuseum", "smk", "clevelandmuseum",
    "rijksmuseum", "smithsonian_portrait_gallery",
    "smithsonian_american_art_museum", "smithsonian_african_art_museum",
    "smithsonian_freer_gallery_of_art", "smithsonian_hirshhorn_museum",
    "smithsonian_libraries", "nypl", "bib_gulbenkian", "svgsilh",
    "stocksnap", "wordpress", "digitaltmuseum",
}

#: Page sizes, anonymous and authenticated.  Openverse refuses a page larger than
#: 20 for a caller with no key -- and says so in a 401 whose body names the rule,
#: which is how this number was found.  Asking for 24 got a hard failure; asking
#: for what the service will actually answer is the whole fix.
_PAGE_ANON = 20
_PAGE_KEYED = 50
_PAGE = 20


def _page_size(limit: int) -> int:
    """What this reader's quota allows us to ask for in one page."""
    cap = _PAGE_KEYED if apireg.key_for(SERVICE) else _PAGE_ANON
    return max(1, min(cap, int(limit or _PAGE)))


def _normalise(r: dict) -> dict:
    """One search result, in this project's shape.

    The fields kept are the ones a reader has to decide with: what the picture
    is, who made it, what licence it carries, where it came from, and the page
    to go to for the full record.  `attribution` is Openverse's own sentence and
    is kept whole -- rewriting it is how attribution requirements get lost.
    """
    lic = (r.get("license") or "").lower()
    ver = (r.get("license_version") or "").strip()
    return {
        "id": r.get("id"),
        "title": (r.get("title") or "").strip() or "Untitled",
        "creator": (r.get("creator") or "").strip() or "Unknown",
        "creator_url": r.get("creator_url") or "",
        "license": lic,
        "license_version": ver,
        "license_name": (lic.upper() + (" " + ver if ver else "")) if lic else "—",
        "license_url": r.get("license_url") or "",
        "source": r.get("source") or r.get("provider") or "",
        "provider": r.get("provider") or "",
        "landing_url": r.get("foreign_landing_url") or "",
        "url": r.get("url") or "",
        "thumbnail": r.get("thumbnail") or r.get("url") or "",
        "width": r.get("width") or 0,
        "height": r.get("height") or 0,
        "attribution": (r.get("attribution") or "").strip(),
        "tags": [t.get("name") for t in (r.get("tags") or [])
                 if isinstance(t, dict) and t.get("name")][:8],
        "duration": r.get("duration") or None,
        "filetype": (r.get("filetype") or "").lower(),
        "category": r.get("category") or "",
        "reusable": lic in REUSABLE,
        "withheld_reason": _WITHHELD.get(lic, "" if lic in REUSABLE
                                         else "licence not recognised"),
    }


def search(query: str, *, page: int = 1, source: str = "",
           licence: str = "", limit: int = _PAGE, kind: str = "images") -> dict:
    """Search Openverse for images.

    **The licence filter is sent to the service, not applied to its answer
    afterwards.**  Asking for a page of twenty and then dropping the seven that
    may not be reused leaves the reader scrolling through a third of a page for
    every page they ask for -- a search for "Dead Sea scroll" returned 7 usable
    images out of 20 fetched, and the remaining thirteen were spent on results
    that could never be shown.  Openverse filters on exactly the same licence
    codes, so the query is asked in the form it can answer, the count it reports
    is the count the reader can use, and the reuse test here stays as a net for
    anything that slips through.

    `licence` is passed straight through when the reader chooses a wider set
    (share-alike, or everything), so "show me the non-commercial ones" is one
    click rather than a client-side guess about what a licence code means.

    Raises `registry.ApiError` when the service is switched off or has no
    network, which the endpoint reports with the hint the registry supplies
    rather than as a fault.
    """
    q = " ".join((query or "").split())
    if not q:
        return {"ok": True, "query": "", "results": [], "count": 0,
                "withheld": 0, "note": "Type something to search for."}
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    limit = _page_size(limit)

    kind = (kind or "images").lower().strip()
    if kind not in ("images", "audio"):
        kind = "images"

    params: dict = {"q": q, "page_size": limit, "page": page,
                    "license": licence or ",".join(REUSABLE)}
    if source:
        params["source"] = source

    key = kind + "|" + "|".join(str(params[k]) for k in ("q", "page_size", "page",
                                            "source", "license") if k in params)
    cached = apireg.cache_get(SERVICE, key, kind=kind, max_age=_TTL)
    if cached is not None:
        return _shape(cached, q, page, key, wide=bool(licence), cached=True)

    raw = apireg.call(SERVICE, kind + "/", params=params)
    if not isinstance(raw, dict):
        return {"ok": False, "error": "Openverse answered with something "
                                      "that was not a result set."}
    apireg.cache_put(SERVICE, key, raw, kind=kind)
    return _shape(raw, q, page, key, wide=bool(licence))


def _shape(raw: dict, q: str, page: int, key: str, wide: bool = False,
           cached: bool = False) -> dict:
    """Turn one Openverse answer into what the panel shows.

    Withheld results are counted and the reasons gathered rather than dropped,
    whatever the filter: a reader who has widened the licence filter to see
    everything needs to be told which of the twelve on screen carries a
    condition, and one who has not needs to know the search was restricted.
    """
    rows = [r for r in (raw.get("results") or []) if isinstance(r, dict)]
    items = [_normalise(r) for r in rows]
    # The panel is for biblical media only: drop results from providers that
    # are not on the curated list, even when "All sources" is selected.
    items = [i for i in items if (i.get("source") or i.get("provider") or "")
             .strip().lower() in BIBLICAL_SOURCES]
    kept = [i for i in items if i["reusable"]]
    dropped = [i for i in items if not i["reusable"]]
    reasons: dict[str, int] = {}
    for d in dropped:
        reasons[d["withheld_reason"]] = reasons.get(d["withheld_reason"], 0) + 1
    total = raw.get("result_count")
    # When the reader has asked for everything, everything is shown -- with the
    # condition named on the card, because a non-commercial image offered
    # unmarked is how a picture ends up in a commercial project.  When the
    # reader has not, only the three licences that permit reuse are listed and
    # the rest are counted.
    shown = items if wide else kept
    return {
        "ok": True,
        "query": q,
        "page": page,
        "pages": raw.get("page_count") or 0,
        "total": total if isinstance(total, int) else 0,
        "results": shown,
        "withheld": len(dropped),
        "withheld_reasons": reasons,
        "cached": cached,
        "note": _note(kept, dropped, reasons, total, wide),
    }


def _note(kept: list, dropped: list, reasons: dict, total, wide: bool) -> str:
    bits = []
    if isinstance(total, int):
        bits.append(f"{total:,} indexed")
    if dropped:
        wh = ", ".join(f"{n} {r}" for r, n in sorted(reasons.items()))
        bits.append(f"{len(dropped)} " + ("marked with the condition on the "
                     "card" if wide else "not shown") + f" ({wh})")
    if not wide:
        bits.append("licences permitting reuse only — the licence filter "
                    "widens it")
    bits.append("cached for a week; anonymous use is 100 a day and 5 an hour")
    return " · ".join(bits)


def sources() -> dict:
    """The sources Openverse indexes, for the filter dropdown.

    Cached for a month and allowed to fail soft: the list is a convenience, and
    a filter that cannot be populated should not stop a search.
    """
    key = "sources"
    hit = apireg.cache_get(SERVICE, key, kind="sources", max_age=30 * 86400)
    if hit is not None:
        # Filter cached lists too, so a stale cache from before the biblical-only
        # change cannot resurrect the removed providers.
        if isinstance(hit, dict) and isinstance(hit.get("sources"), list):
            hit = dict(hit)
            hit["sources"] = [s for s in hit["sources"]
                              if (s.get("id") or "").strip().lower()
                              in BIBLICAL_SOURCES]
        return hit
    try:
        raw = apireg.call(SERVICE, "images/stats/", params={})
    except apireg.ApiError:
        return {"ok": False, "sources": [], "error": "source list unavailable"}
    rows = raw if isinstance(raw, list) else (raw or {}).get("results") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("source_name") or "").strip().lower()
        if sid and sid not in BIBLICAL_SOURCES:
            continue
        name = r.get("display_name") or r.get("source_name")
        if name:
            out.append({"name": str(name),
                        "id": str(r.get("source_name") or name),
                        "count": r.get("media_count") or 0,
                        "url": r.get("source_url") or ""})
    out.sort(key=lambda s: (-(s["count"] or 0), s["name"]))
    payload = {"ok": True, "sources": out}
    apireg.cache_put(SERVICE, key, payload, kind="sources")
    return payload


def source_id(name: str) -> str:
    """The search parameter for a source name, which is the id and not the label.

    Openverse filters on `source_name` ("wikimedia") while the list it publishes
    for the dropdown is the display name ("Wikimedia Commons"), so sending the
    label filters on nothing and returns an empty page that looks like "no
    images" rather than "you asked with the wrong word".
    """
    want = (name or "").strip().lower()
    for s in sources().get("sources") or []:
        if want in ((s.get("name") or "").lower(), (s.get("id") or "").lower()):
            return s.get("id") or s.get("name") or ""
    return want


def status() -> dict:
    """Whether the reader has switched this service on, and what it will cost.

    The panel needs this before it sends anything, because the refusal the
    registry raises names the screen to visit and the panel can offer the button
    rather than quoting an error.
    """
    a = apireg.API_BY_ID.get(SERVICE)
    return {
        "ok": True,
        "id": SERVICE,
        "name": (a.name if a else SERVICE),
        "enabled": apireg.is_enabled(SERVICE),
        "rate_limit": (a.rate_limit if a else ""),
        "license": (a.license if a else ""),
        "site": (a.site_url if a else ""),
        "terms": (a.terms_url if a else ""),
        "reusable": list(REUSABLE),
        "note": "Nothing is sent anywhere until this service is switched on "
                "in API Settings. Answers are cached for a week.",
    }