"""BibleProject videos, linked and embedded, never stored.

BibleProject's usage rules are explicit: do not edit their resources, do not
upload or store them anywhere, do not put them behind a paywall, and always
credit them.  This module therefore does none of those things.  It fetches a
search page and a video page on demand, extracts the link to the video that
BibleProject itself hosts on Mux, and hands that link to the front end, which
plays it straight from BibleProject's host.  Nothing is downloaded into the
module store and nothing is cached as media -- only the metadata and the link
are cached, and only for a week.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from . import db  # noqa: F401  (kept for symmetry with other modules)
from .api import registry as apireg

SERVICE = "bibleproject"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TTL = 7 * 24 * 3600


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _meta(html: str, name: str) -> str:
    for pat in (r'<meta[^>]+property="%s"[^>]+content="([^"]*)"' % re.escape(name),
                r'<meta[^>]+content="([^"]*)"[^>]+property="%s"' % re.escape(name),
                r'<meta[^>]+name="%s"[^>]+content="([^"]*)"' % re.escape(name)):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def _video(slug: str) -> dict | None:
    slug = slug.strip("/")
    if not slug:
        return None
    url = "https://bibleproject.com/videos/" + slug + "/"
    try:
        html = _fetch(url)
    except Exception:  # noqa: BLE001
        return None
    title = _meta(html, "og:title") or ""
    if not title:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else slug
    # og:title carries " - Royal Priest Theme" suffix; keep the clean title.
    title = title.split(" - ")[0].strip() or slug
    desc = _meta(html, "og:description") or _meta(html, "description")
    thumb = _meta(html, "og:image")
    # BibleProject has changed its page markup over time. Prefer the direct
    # Mux stream when present, but don't drop a valid result if the stream is
    # now rendered client-side: the Factbook can still link to the official page.
    m = re.search(r"(?:https?:)?//stream\.mux\.com/[^\"'\\<> ]+?/(?:high|medium|low)\.mp4", html)
    video_url = (m.group(0) if m else "")
    if video_url.startswith("//"):
        video_url = "https:" + video_url
    return {
        "slug": slug,
        "title": title,
        "description": desc,
        "page_url": url,
        "video_url": video_url,
        "thumbnail": thumb,
    }


def search(term: str, *, limit: int = 3) -> dict:
    term = (term or "").strip()
    if not term:
        return {"ok": True, "term": "", "videos": []}
    key = "search-v2|" + term.lower() + "|" + str(limit)
    hit = apireg.cache_get(SERVICE, key, kind="search", max_age=_TTL)
    if isinstance(hit, dict):
        return hit
    try:
        url = "https://bibleproject.com/search/?q=" + urllib.parse.quote(term)
        html = _fetch(url)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "term": term, "videos": [],
                "error": str(e)}
    slugs: list[str] = []
    seen: set[str] = set()
    # Search results may use relative or absolute links, single or double
    # quotes, and query/tracking suffixes. Extract only canonical video paths.
    for m in re.finditer(r"""href\s*=\s*[\"']([^\"']*?/videos/([a-z0-9-]+)/?)(?:[?#][^\"']*)?[\"']""", html, re.I):
        slug = m.group(2).lower()
        if slug in seen or slug in ("all", "search"):
            continue
        seen.add(slug)
        slugs.append(slug)
        if len(slugs) >= max(limit * 3, 8):
            break
    videos = []
    for slug in slugs:
        v = _video(slug)
        if v:
            videos.append(v)
        if len(videos) >= limit:
            break
    payload = {"ok": True, "term": term, "videos": videos,
               "credit": "BibleProject is the author and owner of this content. "
                         "To find more BibleProject resources, visit bibleproject.com."}
    apireg.cache_put(SERVICE, key, payload, kind="search")
    return payload