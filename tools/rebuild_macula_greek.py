#!/usr/bin/env python3
"""Rebuild the MACULA Greek (SBLGNT) module from the local CC-BY-4.0 TSV.

The macula-macula-greek-sblgnt module is a word-level linguistic dataset:
the SBLGNT Greek text annotated with lemma, morphology, Strong's numbers,
Louw-Nida sense domains, frame, and participant referents.  The TSV ships
in the module folder (macula-greek-SBLGNT.tsv); this script turns it into a
normal Bible-shaped module (verse units with markup) plus marker rows for
Strong's, lemma, morph and Louw-Nida sense codes — the data the word study,
morph search and sense lookup rely on.

Licence: MACULA Greek Linguistic Datasets © 2022-2024 Biblica, Inc.,
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).  Attribution
is recorded in module.attribution/license, which the print flows include.

Idempotent: empties and rebuilds this module's rows in place.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from gbible import db, canon

MODULE = "macula-macula-greek-sblgnt"
BOOK = {"MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts",
        "ROM": "Rom", "1CO": "1Cor", "2CO": "2Cor", "GAL": "Gal", "EPH": "Eph",
        "PHP": "Phil", "COL": "Col", "1TH": "1Thess", "2TH": "2Thess", "1TI": "1Tim",
        "2TI": "2Tim", "TIT": "Titus", "PHM": "Phlm", "HEB": "Heb", "JAS": "Jas",
        "1PE": "1Pet", "2PE": "2Pet", "1JN": "1John", "2JN": "2John",
        "3JN": "3John", "JUD": "Jude", "REV": "Rev"}
ORDER = {osis: i for i, osis in enumerate(BOOK.values())}


def main() -> int:
    conn = db.connect()
    folder = Path(db.modules_dir()) / MODULE
    tsv = folder / "macula-greek-SBLGNT.tsv"
    if not tsv.is_file():
        print(f"macula TSV not found at {tsv}")
        return 1
    print("loading TSV…", flush=True)
    verses: dict[str, dict] = {}
    with open(tsv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            m = re.match(r"^([0-9A-Z]+)\s+(\d+):(\d+)!(\d+)$", row["ref"])
            if not m:
                continue
            osis = BOOK[m.group(1)]
            ch, v = int(m.group(2)), int(m.group(3))
            key = f"{osis}.{ch}.{v}"
            verses.setdefault(key, {"book": osis, "chapter": ch, "verse": v,
                                     "words": []})["words"].append({
                "text": row["text"], "after": row["after"],
                "strong": (row["strong"] or "").strip(),
                "morph": (row["morph"] or "").strip(),
                "lemma": (row["lemma"] or "").strip(),
                "ln": (row.get("ln") or "").strip(),
            })
    keys = sorted(verses, key=lambda k: (ORDER[verses[k]["book"]],
                                         verses[k]["chapter"], verses[k]["verse"]))
    print(f"{len(verses)} verses; building rows…", flush=True)
    conn.execute("DELETE FROM marker WHERE module_id=?", (MODULE,))
    conn.execute("DELETE FROM unit WHERE module_id=?", (MODULE,))
    unit_rows, marker_rows = [], []
    chapters = set()
    t0 = time.time()
    for i, key in enumerate(keys, start=1):
        v = verses[key]
        chapters.add((v["book"], v["chapter"]))
        text = ""
        spans = []
        pos = 1
        for w in v["words"]:
            start = len(text)
            text += w["text"] + w["after"]
            strong = ("G" + w["strong"].zfill(4)) if w["strong"] else ""
            spans.append([start, len(w["text"]), "strongs", strong, w["morph"], {}])
            surface = w["text"]
            if strong:
                marker_rows.append((MODULE, "strongs", strong, key, pos, surface,
                                    start, start + len(w["text"])))
            if w["morph"]:
                marker_rows.append((MODULE, "morph", w["morph"], key, pos, surface,
                                    start, start + len(w["text"])))
            if w["lemma"]:
                marker_rows.append((MODULE, "lemma", w["lemma"], key, pos, surface,
                                    start, start + len(w["text"])))
            for ln in w["ln"].split():
                if ln:
                    marker_rows.append((MODULE, "sense", ln, key, pos, surface,
                                        start, start + len(w["text"])))
            pos += 1
        markup = json.dumps({"s": spans, "n": [], "t": "", "h": 0},
                            ensure_ascii=False)
        ref_label = f"{v['book']} {v['chapter']}:{v['verse']}"
        unit_rows.append((MODULE, key, i, v["book"], v["chapter"], v["verse"],
                          ref_label, "", text, markup, 0, len(text),
                          len(v["words"]), "{}"))
    print("inserting units…", flush=True)
    conn.executemany(
        "INSERT INTO unit(module_id, key, ord, book, chapter, verse, ref_label,"
        " title, text, markup, char_start, char_len, word_count, extra)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", unit_rows)
    print(f"inserting {len(marker_rows)} markers…", flush=True)
    conn.executemany(
        "INSERT INTO marker(module_id, kind, value, unit_key, pos, surface,"
        " span_start, span_end) VALUES (?,?,?,?,?,?,?,?)", marker_rows)
    conn.execute(
        "UPDATE module SET chapters=?, verses=?, entries=?, has_strongs=1,"
        " has_morph=1, has_lemma=1, error='' WHERE id=?",
        (len(chapters), len(unit_rows), len(unit_rows), MODULE))
    conn.commit()
    print(f"done: {len(unit_rows)} verses, {len(marker_rows)} markers in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
