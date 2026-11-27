"""Build or check the bundled public-domain Eusebian canon tables.

The CrossWire utility module ``Eusebian_num`` is the only source this uses.  It
is declared Public Domain in its own conf file and contains the ten canon tables
as one ``<EusebianNumber>`` element per section: its canon table, verse range and
the sections in the other Gospels that stand opposite it.  Nothing is inferred
or invented; the app's own per-Gospel verse index is a different half of the
apparatus and is not touched here.

    python3 tools/build_eusebian_tables.py --check
    python3 tools/build_eusebian_tables.py [path-or-url-to-Eusebian_num.zip]
"""
from __future__ import annotations

import io
import json
import re
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gbible" / "data" / "eusebian_tables.json"
URL = ("https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/"
       "Eusebian_num.zip")
CANONS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
FIELDS = ("source", "title", "attribution", "note", "license", "year", "rights")
ENTRY = re.compile(r"<EusebianNumber\s+([^>]+?)\s*/>")
ATTR = re.compile(r'(\w+)="([^"]*)"')


def _entries_from_zip(blob: bytes) -> list[dict]:
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(blob))
    conf = next((n for n in zf.namelist() if n.endswith(".conf")), None)
    if not conf or b"DistributionLicense=Public Domain" not in zf.read(conf):
        raise ValueError("the module does not declare itself Public Domain")
    zdt = next(n for n in zf.namelist() if n.endswith(".zdt"))
    zdx = next(n for n in zf.namelist() if n.endswith(".zdx"))
    data, idx = zf.read(zdt), zf.read(zdx)
    offsets = struct.unpack("<%dI" % (len(idx) // 4), idx[:len(idx) // 4 * 4])
    text = "".join(zlib.decompress(data[o:o + n]).decode("utf-8", "replace")
                   for o, n in zip(offsets[0::2], offsets[1::2]))
    out = []
    for match in ENTRY.finditer(text):
        a = dict(ATTR.findall(match.group(1)))
        if not all(k in a for k in ("id", "table", "osisRef")):
            continue
        if a["table"] not in CANONS:
            continue  # one malformed "I.IV" row in the module
        out.append({k: a[k] for k in ("id", "table", "osisRef", "assocates")})
    return sorted(out, key=lambda e: (e["id"].split(".")[0],
                                      int(e["id"].split(".")[1])))


def check() -> int:
    doc = json.loads(OUT.read_text(encoding="utf-8"))
    problems = []
    for f in FIELDS:
        if not str(doc.get(f, "")).strip():
            problems.append(f"no provenance field: {f}")
    if doc.get("license") != "Public Domain":
        problems.append("the licence is not Public Domain")
    entries = doc.get("entries") or []
    if len(entries) < 1000:
        problems.append(f"only {len(entries)} entries")
    if {e["table"] for e in entries} != CANONS:
        problems.append("not all ten canon tables are present")
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        problems.append("duplicate section ids")
    for p in problems:
        print("FAIL:", p)
    if not problems:
        print(f"PASS: {len(entries)} entries across ten tables, provenance complete")
    return 1 if problems else 0


def build(source: str) -> int:
    if source.startswith("http"):
        blob = urllib.request.urlopen(source, timeout=60).read()
    else:
        blob = Path(source).read_bytes()
    entries = _entries_from_zip(blob)
    doc = {
        "source": "CrossWire SWORD module Eusebian_num 1.1 (Eusebian Numbers)",
        "title": "Eusebian canon tables",
        "attribution": (
            "Transcribed from the public-domain SWORD module Eusebian_num, "
            "version 1.1 (2013-01-30), whose conf file states "
            "'DistributionLicense=Public Domain'. The canon tables themselves "
            "were composed by Eusebius of Caesarea about AD 340; this file "
            "contains only their section numbers, canon assignments, verse "
            "ranges and cross-references, with no modern commentary."),
        "note": ("Tables I-X, with the associated sections in the other "
                 "Gospels. A section's own number is kept in its id "
                 "(gospel.section); the table field is the canon it belongs to."),
        "license": "Public Domain",
        "year": "340",
        "rights": ("Public domain. The ancient tables carry no copyright; the "
                   "modern transcription is released as Public Domain by its "
                   "publisher, CrossWire. No known restrictions."),
        "module": "Eusebian_num",
        "module_version": "1.1",
        "module_date": "2013-01-30",
        "module_license": "DistributionLicense=Public Domain",
        "entry_count": len(entries),
        "entries": entries,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} with {len(entries)} entries")
    return check()


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check())
    if not OUT.exists() and len(sys.argv) == 1:
        raise SystemExit(build(URL))
    raise SystemExit(build(sys.argv[1] if len(sys.argv) > 1 else URL))
