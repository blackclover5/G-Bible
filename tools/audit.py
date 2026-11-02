"""Audit every catalogue item: can it be downloaded, and can it be read?

    python3 tools/audit.py                    # probe every item (downloads)
    python3 tools/audit.py --repo crosswire   # one repository
    python3 tools/audit.py --install          # actually install each one
    python3 tools/audit.py --limit 40         # stop after N

The probe pass fetches each item's payload, sniffs it, and records what came
back.  That is enough to find the whole catalogue's failure modes -- dead URLs,
HTML error pages served with a 200, formats nothing can read -- without paying
for a full install of 900 modules.

The install pass is slower and needs `GBIBLE_HOME`, but it is the only way to be
sure a module actually yields text once parsed.

Findings are grouped by cause rather than listed one by one, because the useful
question is not "did TSK fail" but "how many things fail this way and why".
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db, store                                    # noqa: E402
from gbible.formats import sniff                                # noqa: E402
from gbible.importers.runner import canonical_url, fetch        # noqa: E402

# Payloads above this are not worth downloading just to find out whether the
# URL is alive.
PROBE_CAP = 24 * 1024 * 1024


def _sniff_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0]


def probe(repo: str, it: dict) -> dict:
    """Fetch one item's payload and classify what came back."""
    dls = it.get("downloads") or []
    url = (dls[0].get("url") if dls else "") or it.get("download_url") or ""
    row = {"repo": repo, "item": it.get("item_id"), "id": it.get("id"),
           "title": it.get("title", "")[:60], "url": url,
           "want": (dls[0].get("format") if dls else it.get("format", "")) or "",
           "status": "?", "detail": "", "kind": "", "bytes": 0}
    # Wikisource has no file to fetch at all: the handler enumerates pages
    # through the MediaWiki API, so probing a URL would only ever report a
    # false failure.
    if repo == "wikisource":
        row["status"] = "API-DRIVEN"
        row["detail"] = "enumerated through the MediaWiki API"
        return row
    # Multi-file repositories keep their file list in `extra` and leave a
    # <BASE>/... template in download_url; probing the template 404s.
    files = ((it.get("extra") or {}).get("files") or []) if \
        isinstance(it.get("extra"), dict) else []
    if files:
        url = files[0]
        row["url"] = url
        row["want"] = row["want"] or "file-list"
    if not url:
        # Some repositories are catalogue-driven: the geodata handler builds each
        # place's payload from a shared index rather than a per-item file, so
        # there is nothing to probe.  Say so instead of calling it a failure.
        extra = it.get("extra") if isinstance(it.get("extra"), dict) else {}
        row["status"] = ("CATALOGUE-DRIVEN" if (extra.get("lat") is not None
                                                or repo == "openbible-geo")
                         else "NO-URL")
        row["detail"] = "built from the repository index" if \
            row["status"] == "CATALOGUE-DRIVEN" else "no download URL"
        return row
    url = canonical_url(url)
    row["url"] = url
    t0 = time.time()
    try:
        data = fetch(url, timeout=90, max_bytes=PROBE_CAP)
    except Exception as e:                                   # noqa: BLE001
        row["status"] = "UNREACHABLE"
        row["detail"] = f"{type(e).__name__}: {str(e)[:90]}"
        return row
    row["bytes"] = len(data)
    row["ms"] = int((time.time() - t0) * 1000)
    # A server that 404s often answers 200 with a small HTML page.  A real
    # XML document may also begin with `<!DOCTYPE ...>` (CCEL's NPNF volumes do,
    # naming the ThML DTD), so the doctype check is restricted to the HTML ones
    # and to documents that actually contain an <html> element.
    head = data[:400].lstrip()
    low = data[:200].lower()
    is_html = (b"<!doctype html" in low or b"<!doctype xhtml" in low
               or b"<html" in low[:200])
    if head[:1] == b"<" and is_html:
        row["status"] = "HTML-NOT-DATA"
        row["detail"] = f"{len(data)} bytes of HTML, not a module"
        return row
    if len(data) < 400 and b"404" in data[:200]:
        row["status"] = "DEAD"
        row["detail"] = data[:80].decode("utf-8", "replace").replace("\n", " ")
        return row
    kind = sniff(data, name=_sniff_name(url))
    row["kind"] = kind
    if kind in ("unknown", "text"):
        # `text` is only a failure when the catalogue promised something richer
        row["status"] = "OK" if row["want"] in ("text", "plain", "", "file-list") \
            else "NO-READER"
        row["detail"] = "" if row["status"] == "OK" else f"sniffed as {kind}"
    else:
        row["status"] = "OK"
    return row


def classify_install_error(exc: BaseException) -> str:
    """Bucket an install failure into a cause, for grouping."""
    m = str(exc)
    low = m.lower()
    if "lzss" in low:
        return "lzss-unsupported"
    if "no mods.d" in low or "no .conf" in low:
        return "no-conf-in-archive"
    if "no verses parsed" in low or "no entries recognised" in low \
            or "no text to read" in low or "no units" in low:
        return "parsed-but-empty"
    if "no .dat" in low or "no .bbi" in low or "no .idx" in low:
        return "data-file-missing"
    if "ztext" in low or "zcom" in low or "driver" in low:
        return "unsupported-driver"
    if "every page came back empty" in low or "no wikisource pages" in low:
        return "wikisource-empty"
    if "licence" in low or "license" in low:
        return "licence-refused"
    if "sworderror" in low or "badsword" in low:
        return "sword-parse-error"
    if type(exc).__name__ in ("IncompleteRead", "HTTPError", "URLError",
                              "TimeoutError", "RemoteDisconnected"):
        return "network"
    return f"other:{type(exc).__name__}"


def main(argv: list[str]) -> int:
    def arg(flag: str, default: str = "") -> str:
        return argv[argv.index(flag) + 1] if flag in argv else default

    only = arg("--repo")
    do_install = "--install" in argv
    limit = int(arg("--limit", "0") or 0)
    db.init()
    if not any(r["item_count"] for r in store.repos()):
        store.sync_all()

    by_driver = "--by-driver" in argv
    repos = [only] if only else [r.id for r in store.REPOSITORIES if r.id != "local"]
    rows: list[dict] = []
    total = 0
    for repo in repos:
        items = store.list_items(repo=repo, limit=100000)["items"]
        if by_driver:
            seen, pick = set(), []
            for it in items:
                ex = it.get("extra") or {}
                drv = (ex.get("moddrv") or it.get("format") or "?")
                if drv in seen:
                    continue
                seen.add(drv)
                pick.append(it)
            items = pick
            print(f"  one item per driver: {len(items)}", flush=True)
        print(f"\n=== {repo}: {len(items)} items", flush=True)
        for it in items:
            if limit and total >= limit:
                break
            total += 1
            if do_install:
                t0 = time.time()
                try:
                    res = store.install(repo, str(it["item_id"]), force=True)
                    ok = bool(res.get("ok"))
                    units = ((res.get("stats") or {}).get("units") or 0)
                    row = {"repo": repo, "item": it["item_id"],
                           "title": it["title"][:60], "status": "OK" if ok else "FAIL",
                           "detail": f"{units} units in {time.time()-t0:.0f}s",
                           "url": "", "want": it.get("format", ""), "kind": "",
                           "bytes": 0}
                    if ok and not units:
                        row["status"] = "EMPTY"
                except Exception as e:                       # noqa: BLE001
                    row = {"repo": repo, "item": it["item_id"],
                           "title": it["title"][:60],
                           "status": "FAIL", "url": "", "want": "",
                           "kind": "", "bytes": 0,
                           "detail": f"{classify_install_error(e)}: "
                                     f"{str(e)[:110]}"}
            else:
                row = probe(repo, it)
            rows.append(row)
            if row["status"] != "OK":
                print(f"  {row['status']:14} {row['item']:<24} "
                      f"{row['title'][:44]:46} {row['detail'][:60]}", flush=True)
        if limit and total >= limit:
            break

    ok = sum(1 for r in rows if r["status"] == "OK")
    cd = sum(1 for r in rows
             if r["status"] in ("CATALOGUE-DRIVEN", "API-DRIVEN"))
    print(f"\n{'=' * 72}\n{ok}/{len(rows)} OK"
          + (f"  (+{cd} catalogue-driven)" if cd else ""))
    bad = Counter()
    for r in rows:
        if r["status"] in ("OK", "CATALOGUE-DRIVEN", "API-DRIVEN"):
            continue
        bad[r["detail"].split(":")[0] if r["status"] in
            ("UNREACHABLE", "DEAD", "HTML-NOT-DATA", "NO-READER",
             "NO-URL", "TEMPLATE-URL") else r["status"]] += 1
    print("\nfailures by cause:")
    for cause, n in bad.most_common():
        print(f"  {n:4}  {cause}")
    per_repo = Counter((r["repo"], r["status"]) for r in rows)
    print("\nby repository:")
    for repo in repos:
        good = per_repo[(repo, "OK")]
        tot = sum(n for (rp, _s), n in per_repo.items() if rp == repo)
        note = ""
        extra_n = (per_repo[(repo, "CATALOGUE-DRIVEN")]
                   + per_repo[(repo, "API-DRIVEN")])
        if extra_n:
            note = f"  (+{extra_n} not file-downloaded)"
        print(f"  {repo:16} {good}/{tot}{note}")

    out = Path("/tmp/opencode/audit.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(__import__("json").dumps(rows, indent=1), encoding="utf-8")
        print(f"\nfull report: {out}")
    except OSError:
        pass
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
