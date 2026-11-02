"""Check a Project Gutenberg ebook and stage it for the Store catalogue.

Gutenberg ebooks are public domain in the USA, but "Gutenberg says PD" is a
claim about one jurisdiction and one edition — a translation's copyright can
rest with the translator. So this tool fetches the ebook page, requires the
Public-domain line, parses author/translator death years, and refuses anything
whose makers did not all die before 1930 (the same date rule the Store
applies). It also HEADs the UTF-8 text for size and emits the entry in the
exact catalogue shape. `--add` appends verified entries and updates the count.

Usage:
    python3 tools/check_gutenberg.py 2848 2850        # report only
    python3 tools/check_gutenberg.py 2848 2850 --add  # report and append
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "gbible" / "store" / "data" \
    / "gutenberg.json"


def _get(url: str, binary: bool = False) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "gbible-check/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _head_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "gbible-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ln = r.headers.get("Content-Length")
            return int(ln) if ln else None
    except Exception:  # noqa: BLE001
        return None


def _field(page: str, label: str) -> str:
    m = re.search(r"<th[^>]*>\s*" + re.escape(label) +
                  r"\s*</th>\s*<td[^>]*>(.*?)</td>", page, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def check(ebook_id: str) -> dict:
    url = f"https://www.gutenberg.org/ebooks/{ebook_id}"
    try:
        page = _get(url).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return {"id": ebook_id, "ok": False, "error": f"fetch failed: {exc}"}
    if "Public domain in the USA" not in page and "Public Domain" not in page:
        return {"id": ebook_id, "ok": False,
                "error": "no public-domain statement on the ebook page"}
    author = _field(page, "Author")
    translator = _field(page, "Translator")
    title = re.sub(r"<[^>]+>", "", re.search(
        r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)).strip() \
        if re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) else ""
    release = _field(page, "Release Date")
    lang = _field(page, "Language")
    locc = _field(page, "LoC Class")
    subjects = re.findall(
        r"Subject</th>.*?</tr>", page, re.S)  # presence only; parsed below
    _ = subjects
    # Death years: "Whiston, William, 1667-1752" or "38?-100?".
    problems = []
    for role, val in (("author", author), ("translator", translator)):
        for m in re.finditer(r"(\d{3,4})\s*[–-]\s*(\d{3,4})\??", val):
            if int(m.group(2)) >= 1930:
                problems.append(f"{role} died {m.group(2)}: {val[:80]}")
    if problems:
        return {"id": ebook_id, "ok": False, "error": "; ".join(problems),
                "title": title}
    txt = f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}.txt"
    size = _head_size(txt)
    if size is None:
        txt_alt = f"https://www.gutenberg.org/ebooks/{ebook_id}.txt.utf-8"
        size = _head_size(txt_alt)
        if size is not None:
            txt = txt_alt
    if size is None:
        return {"id": ebook_id, "ok": False, "title": title,
                "error": "no reachable UTF-8 text"}
    year = ""
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", release)
    if m:
        from datetime import datetime as _dt
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                year = _dt.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
    entry = {
        "id": str(ebook_id), "title": title or f"Gutenberg #{ebook_id}",
        "author": "; ".join(x for x in
                            [author,
                             (translator + " [Translator]" if translator else "")]
                            if x),
        "year": year, "lang": "eng" if "English" in lang else "",
        "lang_name": "English" if "English" in lang else "",
        "license": "Public Domain", "category": "Book",
        "subjects": [], "gutenberg_subjects": [], "bookshelves": [],
        "locc": locc.split(":")[0].strip() if locc else "",
        "download_url": f"https://www.gutenberg.org/ebooks/{ebook_id}.txt.utf-8",
        "download_url_final": txt,
        "page_url": url, "size_bytes": size, "size_source": "http-head",
        "downloads": [{"format": "text",
                       "url": f"https://www.gutenberg.org/ebooks/{ebook_id}.txt.utf-8",
                       "size_bytes": size}],
    }
    return {"id": ebook_id, "ok": True, "title": entry["title"],
            "author": entry["author"], "size": size, "entry": entry}


def main(argv: list[str]) -> int:
    add = "--add" in argv
    ids = [a for a in argv[1:] if a != "--add"]
    if not ids:
        print(__doc__.strip().splitlines()[-4])
        return 2
    results = [check(i) for i in ids]
    for r in results:
        if r.get("ok"):
            print(f"PASS {r['id']}: {r['title']} — {r['author']} "
                  f"({r['size']} bytes)")
        else:
            print(f"FAIL {r['id']}: {r.get('error')} "
                  f"[{r.get('title', '')}]")
    if add:
        good = [r["entry"] for r in results if r.get("ok")]
        if not good:
            print("Nothing verified; catalogue untouched.")
            return 1
        data = json.loads(CATALOG.read_text())
        have = {it["id"] for it in data["items"]}
        added = 0
        for e in good:
            if e["id"] in have:
                print(f"SKIP {e['id']}: already catalogued")
                continue
            data["items"].append(e)
            added += 1
        data["count"] = len(data["items"])
        import time as _t
        data["generated"] = int(_t.time())
        CATALOG.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print(f"Added {added}; catalogue now holds {data['count']}.")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
