#!/usr/bin/env python3
"""Build the CCEL Fathers catalogue for the Store.

The Christian Classics Ethereal Library (ccel.org, hosted on the campus of
Calvin University) keeps the Ante-Nicene Fathers and the Nicene and Post-Nicene
Fathers as one ThML file per volume.  This writes `store/data/ccel_fathers.json`,
listing **one item per work** -- Irenaeus's *Against Heresies*, Chrysostom's
*Homilies on Romans* -- rather than one item per volume, because the Store's
granularity is the thing a reader chooses between, and nobody wants a volume of
nine Fathers to read one of them.

Two sources, for two different facts:

* the 26 author-index pages (`/index/author/A`…) give each work its proper title
  and its author's proper name.  CCEL's own ThML heads disagree with them --
  Barnabas's epistle is filed under `authorID=ignatius`, and several titles carry
  underscores -- so the index wins where they differ.
* the volume files give what the index cannot: which division each work is, the
  volume's own first-publication date, and `<DC.Rights>Public Domain</DC.Rights>`,
  read from the file rather than assumed by this script.

Downloads are cached, so a second run costs nothing:

    python3 tools/build_ccel_fathers.py            # build the catalogue
    python3 tools/build_ccel_fathers.py --refresh  # ignore the cache
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import taxonomy                                   # noqa: E402
from gbible.formats import thml                               # noqa: E402

CACHE = ROOT / ".cache" / "ccel"
OUT = ROOT / "gbible" / "store" / "data" / "ccel_fathers.json"
HOME = "https://www.ccel.org"

VOLUMES = ([f"anf{n:02d}" for n in range(1, 11)] +
           [f"npnf1{n:02d}" for n in range(1, 15)] +
           [f"npnf2{n:02d}" for n in range(1, 15)])

SERIES = {"anf": "Ante-Nicene Fathers", "npnf1": "Nicene and Post-Nicene Fathers, "
                                                   "Series I",
          "npnf2": "Nicene and Post-Nicene Fathers, Series II"}

#: When each series was published.  The Ante-Nicene volumes carry their own
#: `<firstPublished>`; the Nicene ones do not, and Schaff's NPNF came out in
#: 1887.  The year is what decides whether a Public Domain claim is safe
#: (`taxonomy.pd_dated_ok`), so it is recorded per series rather than guessed.
SERIES_YEAR = {"anf": "1885", "npnf1": "1887", "npnf2": "1887"}

#: How long to wait between requests.  CCEL is a small library run by volunteers,
#: and a catalogue build is not a reason to hammer it.
PAUSE = 0.35
UA = "gbible-bible-catalogue/1.0 (offline Bible app; CCEL catalogue builder)"

ATTRIBUTION = (
    "Text from the Christian Classics Ethereal Library (CCEL), ccel.org, hosted "
    "on the campus of Calvin University. The edition is in the public domain; "
    "CCEL's own copyright policy notes that the site design and any special "
    "contents are Harry Plantinga's, © 1993-2020. CCEL's Theological Markup "
    "Language is © 1997-2025 CCEL and contributors.")


def fetch(url: str, *, name: str = "", refresh: bool = False) -> str:
    """Fetch a URL, cached under `.cache/ccel`."""
    path = CACHE / (name or url.rsplit("/", 1)[-1])
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    path.write_bytes(r.read())
                break
            except Exception as exc:                       # noqa: BLE001
                if attempt == 3:
                    raise RuntimeError(f"{url}: {exc}") from exc
                time.sleep(2 * (attempt + 1))
        time.sleep(PAUSE)
    return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# CCEL's author index: work slug -> (title, author name)
# --------------------------------------------------------------------------

_AUTHOR_RE = re.compile(
    r'href="/ccel/([a-z_0-9]+)\?show=worksBy"[^>]*title="View works by [^"]*"',
    re.I)
# The name is the text between the anchor's tags and nothing else.  Letting it
# run to the end of the author's block picks up the works list too, so a
# Clement of Rome entry came out as "Clement of Rome, St. (?-99) [Author Info]
# First Epistle to the Corinthians Ancient Homily...".
_AUTHOR_NAME_RE = re.compile(r'href="/ccel/[a-z_0-9]+\?show=worksBy"[^>]*>\s*([^<]*?)\s*<',
                             re.I | re.S)
_WORK_RE = re.compile(r'href\s*=\s*"\s*(?:https://ccel\.org)?/ccel/[a-z_0-9]+/'
                      r'([a-z_0-9]+)\s*"\s*>\s*([^<]+?)\s*</a>', re.S)


def _strip_tags(s: str) -> str:
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def author_index(refresh: bool) -> tuple[dict, dict]:
    """(work_id -> [(title, author_id, author_name)], author_id -> name).

    A work slug can appear under two authors -- "Epistles of Ignatius" is under
    Ignatius of Antioch, while "Ignatius" is Ignatius of Loyola and owns works of
    his own -- so the mapping keeps every candidate and `pick_work` chooses.
    """
    works: dict[str, list[tuple[str, str, str]]] = {}
    names: dict[str, str] = {}
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        page = fetch(f"{HOME}/index/author/{letter}", name=f"authors-{letter}.html",
                     refresh=refresh)
        blocks = page.split('id="author_link_')
        for block in blocks[1:]:
            head = block[:1200]
            m = _AUTHOR_RE.search(head)
            if not m:
                continue
            slug = m.group(1).lower()
            nm = _AUTHOR_NAME_RE.search(head)
            name = _strip_tags(nm.group(1)) if nm else ""
            name = re.sub(r"\s*\[Author\s*Info\]\s*$", "", name).strip()
            if name:
                names[slug] = name
            for wslug, wtitle in _WORK_RE.findall(block):
                works.setdefault(wslug.lower(), []).append(
                    (_strip_tags(wtitle), slug, name))
    return works, names


def pick_work(candidates: list[tuple[str, str, str]], author_id: str
              ) -> tuple[str, str, str]:
    """Choose between authors who share a work slug.

    The volume file's own `authorID` is the tie-breaker, because it is the one
    that came with the text; only when it names nobody on the index is the first
    candidate taken.
    """
    if not candidates:
        return ("", "", "")
    if author_id:
        for cand in candidates:
            if cand[1] == author_id:
                return cand
    return candidates[0]


# --------------------------------------------------------------------------
# The volumes
# --------------------------------------------------------------------------

def volume_xml(slug: str, refresh: bool) -> str:
    return fetch(f"{HOME}/ccel/s/schaff/{slug}.xml", name=f"{slug}.xml",
                 refresh=refresh)


def volume_series(slug: str) -> str:
    if slug.startswith("npnf1"):
        return SERIES["npnf1"]
    if slug.startswith("npnf2"):
        return SERIES["npnf2"]
    return SERIES["anf"]


def series_key(slug: str) -> str:
    if slug.startswith("npnf1"):
        return "npnf1"
    if slug.startswith("npnf2"):
        return "npnf2"
    return "anf"


def _fallback_name(slug: str) -> str:
    """A readable author for a slug CCEL gives no name for.

    CCEL's own index lists `justin_martyr` as Justin Martyr's name, which is to
    say it lists the slug.  A capitalised slug is a worse thing to show than the
    slug, and better than nothing.
    """
    words = [w for w in (slug or "").replace("-", "_").split("_") if w]
    return " ".join(w[:1].upper() + w[1:] for w in words)


def author_name_for(it_author: str, author_id: str) -> str:
    if it_author and it_author != author_id:
        return it_author
    return _fallback_name(author_id)


def _abbrev(title: str) -> str:
    """A short form, the way the Library's own abbreviations are short.

    The Library column is narrow and these titles are whole sentences -- "The
    Homilies on the Statues to the People of Antioch" -- so the leading article
    goes and the rest is cut at a word.
    """
    t = re.sub(r"^(?:The|A|An)\s+", "", (title or "").strip(), flags=re.I).strip()
    if len(t) <= 32:
        return t
    return (t[:32].rsplit(" ", 1)[0] or t[:32]).rstrip(",;:- ")


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------

_SUBJECT_HINTS = (
    ("homil", "Commentaries"),
    ("sermon", "Preaching"),
    ("exposition", "Commentaries"),
    ("commentary", "Commentaries"),
    ("apolog", "Apologetics"),
    ("refutation", "Apologetics"),
    ("against the", "Theological"),
    ("creed", "Creeds & Confessions"),
    ("confession", "Theological"),
    ("canons of the", "Church History"),
    ("martyrdom", "Biographies"),
    ("spurious", "Canon / Apocrypha"),
    ("gospel of", "Gospel"),
)


def subjects_for(title: str, author: str) -> list[str]:
    out = ["Church History", "Ancient History"]
    low = title.lower()
    for needle, subject in _SUBJECT_HINTS:
        if needle in low:
            if subject not in out:
                out.append(subject)
            break
    if "lactantius" in author.lower() or "eusebius" in author.lower():
        out.append("Biblical History")
    return [s for s in out if s in taxonomy.SUBJECT_SET]


# --------------------------------------------------------------------------
# The build
# --------------------------------------------------------------------------

def build(refresh: bool = False) -> dict:
    print("reading CCEL's author index ...", flush=True)
    index, authors = author_index(refresh)
    print(f"  {len(index)} works, {len(authors)} authors")

    items: list[dict] = []
    skipped: list[dict] = []
    seen: dict[str, str] = {}
    for n, slug in enumerate(VOLUMES, 1):
        try:
            src = volume_xml(slug, refresh)
        except RuntimeError as exc:
            print(f"  [{n}/{len(VOLUMES)}] {slug}: {exc}", flush=True)
            skipped.append({"volume": slug, "why": str(exc)})
            continue
        meta = thml.volume_meta(src)
        # The same call the installer makes, so an item the Store offers is an
        # item the installer can find.
        works = thml.volume_works(src)
        how = "per-work heads" if thml.find_works(src) else "divisions"
        lic = taxonomy.normalise_license(meta.rights)
        year = meta.first_published or SERIES_YEAR[series_key(slug)]
        ok, why = taxonomy.redistributable({"license": lic, "year": year})
        epub_url = f"{HOME}/ccel/s/schaff/{slug}/cache/{slug}.epub"
        txt_url = f"{HOME}/ccel/s/schaff/{slug}/cache/{slug}.txt"
        print(f"  [{n}/{len(VOLUMES)}] {slug}: {len(works):3d} works by {how} "
              f"({meta.rights or 'no rights'}, {year})", flush=True)
        if not works:
            skipped.append({"volume": slug, "why": "no works found in the file"})
            continue
        if not ok or not taxonomy.license_ok(lic):
            skipped.append({"volume": slug, "why": why or f"licence {lic}"})
            continue
        for w in works:
            indexed = pick_work(index.get(w.work_id) or [], w.author_id)
            title = indexed[0] or w.title
            author_name = author_name_for(
                indexed[2] or w.author or authors.get(w.author_id, ""),
                w.author_id)
            item_id = w.work_id
            if item_id in seen:
                # The same work in two volumes is a catalogue bug upstream; keep
                # both, disambiguated, rather than offering one silently.
                item_id = f"{slug}-{w.work_id}"
            seen[w.work_id] = slug
            series = volume_series(slug)
            # A division has no author/work page of its own -- CCEL published
            # these files before the per-work addresses existed -- so its own
            # address is the one that opens.
            page_url = w.page_url if how == "per-work heads" else w.url
            items.append({
                "id": item_id,
                "title": title,
                "abbrev": _abbrev(title),
                "author": author_name or "Anonymous",
                "year": year,
                "lang": meta.language or "eng",
                "lang_name": taxonomy.language_name(meta.language or "eng"),
                "license": "Public Domain",
                "category": "Book",
                "subjects": subjects_for(title, author_name),
                "attribution": ATTRIBUTION,
                "rights": (f"Public domain in the United States. Edition: "
                           f"{series}, volume {slug[-2:]} "
                           f"(CCEL {meta.editor or 'Schaff'}), first published "
                           f"{year}."),
                "description": (f"{title} — {author_name or w.author_id}. From "
                                f"{series}, volume {slug[-2:]}, edited by "
                                f"{meta.editor or 'Philip Schaff'} and first "
                                f"published {year}. Read online at CCEL."),
                "download_url": f"{HOME}/ccel/s/schaff/{slug}.xml",
                "page_url": page_url,
                "size_bytes": len(src.encode("utf-8")),
                "downloads": [
                    {"format": "thml", "url": f"{HOME}/ccel/s/schaff/{slug}.xml"},
                    {"format": "epub", "url": epub_url},
                    {"format": "text", "url": txt_url},
                ],
                # What the importer needs to find this work inside the volume.
                "work": w.work_id,
                "volume": slug,
                "div": w.div_id,
                "volume_title": f"{series}, volume {slug[-2:]}"
                                f" ({meta.title})",
            })

    catalog = {
        "repository": "ccel-fathers",
        "generated": int(time.time()),
        "source": thml.CCEL_FATHERS,
        "license": "Public Domain",
        "count": len(items),
        "items": items,
        "skipped": skipped,
        "authors": authors,
        "schema": {
            "items": ("One item per work, not per volume: `download_url` is the "
                      "ThML file of the volume the work sits in and `div` names "
                      "the division inside it."),
            "licence": ("The volume's own <DC.Rights> is read from the file and "
                        "checked against taxonomy.redistributable; a volume that "
                        "does not say it is public domain is skipped and listed "
                        "in `skipped`."),
            "authors": ("Names and titles come from CCEL's author index pages, "
                        "which disagree with the ThML heads on Barnabas and on "
                        "several titles; the index wins."),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {OUT} with {len(items)} works from "
          f"{len(VOLUMES) - len(skipped)} volumes ({len(skipped)} skipped)")
    return catalog


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the cached downloads")
    args = ap.parse_args()
    catalog = build(refresh=args.refresh)
    if not catalog["items"]:
        raise SystemExit("no works found; nothing written")


if __name__ == "__main__":
    main()