#!/usr/bin/env python3
"""Build the Latin Patristic catalogue for the Store.

Source: The Latin Library (thelatinlibrary.com), Christian section.  Public-
domain Latin texts of the Fathers, one item per work (or per book where the
work is split into books, matching the CCEL Fathers granularity).

Downloads are cached under .cache/latinlib/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE = ROOT / ".cache" / "latinlib"
OUT = ROOT / "gbible" / "store" / "data" / "latin_patristic.json"
HOME = "https://thelatinlibrary.com"

# Curated patristic authors: slug -> (display name, dates).
AUTHORS = {
    "ambrose": ("Ambrose of Milan", "c.340-397"),
    "arnobius": ("Arnobius of Sicca", "c.255-c.330"),
    "august": ("Augustine of Hippo", "354-430"),
    "cassiodorus": ("Cassiodorus", "c.485-c.585"),
    "commodianus": ("Commodianus", "3rd c."),
    "egeria": ("Egeria", "4th c."),
    "ennodius": ("Ennodius of Pavia", "473-521"),
    "eucherius": ("Eucherius of Lyon", "c.380-c.450"),
    "eugippius": ("Eugippius", "5th-6th c."),
    "greg": ("Gregory the Great", "c.540-604"),
    "hydatius": ("Hydatius of Aquae Flaviae", "c.400-c.470"),
    "isidore": ("Isidore of Seville", "c.560-636"),
    "jerome": ("Jerome", "c.347-420"),
    "junillus": ("Junillus", "6th c."),
    "lactantius": ("Lactantius", "c.250-c.325"),
    "leothegreat": ("Leo the Great", "c.400-461"),
    "macarius": ("Macarius of Alexandria", "4th-5th c."),
    "macarius1": ("Macarius the Great", "c.300-391"),
    "novatian": ("Novatian", "c.200-c.258"),
    "paulinus.poemata": ("Paulinus of Nola", "354-431"),
    "perp": ("Passion of Perpetua and Felicitas", "3rd c."),
    "prud": ("Prudentius", "348-c.413"),
    "prosperus": ("Prosper of Aquitaine", "c.390-c.455"),
    "sedulius": ("Sedulius", "5th c."),
    "sulpiciusseverus": ("Sulpicius Severus", "c.363-c.425"),
    "tertullian": ("Tertullian", "c.155-c.220"),
    "vicentius": ("Vincent of Lerins", "d. c.445"),
}

NAV_LABELS = {"Christian Latin", "The Latin Library", "The Classics Page",
              "Index", "Ius Romanum", "Miscellany", "Neo-Latin",
              "Christian Creeds", "Hymni et cantica"}


def fetch(url: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = url.replace("https://", "").replace("http://", "").replace("/", "_")
    p = CACHE / key
    if p.exists() and not REFRESH:
        return p.read_text(encoding="utf-8", errors="replace")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gbible/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print("  fetch failed", url, e, file=sys.stderr)
        return ""
    p.write_text(data, encoding="utf-8")
    time.sleep(0.2)
    return data


REFRESH = False


def work_links(html: str, base_url: str):
    """Return list of (href, label) work links on an author page."""
    out = []
    seen = set()
    for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]+)</[aA]>', html):
        href, label = m.group(1).strip(), m.group(2).strip()
        if not label or label in NAV_LABELS:
            continue
        if href.startswith("http") and "thelatinlibrary.com" not in href:
            continue
        if href.startswith("/"):
            href = HOME + href
        elif not href.startswith("http"):
            href = urljoin(base_url, href)
        if "thelatinlibrary.com" not in href:
            continue
        if href in (base_url,):
            continue
        if href.endswith((".css", ".ico", ".jpg", ".png")):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((href, label))
    return out


def main():
    global REFRESH
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    REFRESH = args.refresh

    items = []
    for slug, (name, dates) in AUTHORS.items():
        author_url = f"{HOME}/{slug}.html"
        html = fetch(author_url)
        if not html:
            # try without .html already? slug may be a path
            print("SKIP (no fetch)", slug)
            continue
        links = work_links(html, author_url)
        if len(links) >= 2:
            # index page: each link is a work
            for href, label in links:
                wid = re.sub(r"[^a-z0-9]+", "_",
                             (name + " " + label).lower()).strip("_")[:60]
                items.append(make_item(wid, label, name, dates, href))
        else:
            # single work on this page: the page itself
            # title from <title> or pagehead
            title = name
            m = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S | re.I)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
            ph = re.search(r'<p class=pagehead>(.*?)</p>', html, re.S | re.I)
            if ph:
                title = re.sub(r"\s+", " ", ph.group(1)).strip()
            wid = re.sub(r"[^a-z0-9]+", "_", (name + " " + title).lower()).strip("_")[:60]
            items.append(make_item(wid, title, name, dates, author_url))
        print(f"{slug}: {len(links)} links -> "
              f"{sum(1 for i in items if i['author_slug']==slug)} items")

    # de-dupe by download_url
    seen = set()
    uniq = []
    for it in items:
        if it["download_url"] in seen:
            continue
        seen.add(it["download_url"])
        uniq.append(it)
    items = uniq

    out = {
        "repository": "latin-patristic",
        "generated": int(time.time()),
        "source": HOME + "/christian.html",
        "license": "Public Domain",
        "count": len(items),
        "items": items,
        "skipped": [],
        "schema": {"note": "One item per work page on thelatinlibrary.com"},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, "with", len(items), "items")


def make_item(wid, label, name, dates, href):
    return {
        "id": wid,
        "title": label,
        "abbrev": label[:32],
        "author": f"{name} ({dates})",
        "year": "",
        "lang": "lat",
        "lang_name": "Latin",
        "license": "Public Domain",
        "category": "Book",
        "subjects": ["Church History", "Ancient History", "Theological"],
        "attribution": ("Text from The Latin Library (thelatinlibrary.com). "
                        "Public domain."),
        "rights": "Public domain.",
        "description": f"{label} — {name}. From The Latin Library.",
        "download_url": href,
        "page_url": href,
        "size_bytes": 0,
        "downloads": [{"format": "html", "url": href}],
        "work": href.rsplit("/", 1)[-1],
        "author_slug": name.lower().replace(" ", "_"),
        "author_name": name,
    }


if __name__ == "__main__":
    main()
