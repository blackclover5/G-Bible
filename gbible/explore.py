"""Psalms explorer and Bible-books stats — counted off installed text.

* **Psalms**: superscription (the psalm's own title line where the edition
  carries one), length, and mood tags from keyword sets matched against the
  psalm's words. Heuristic throughout, and labelled as such: tags describe
  vocabulary, not form-critical categories.
* **Books**: per-book chapters, verses and words for one installed Bible —
  the numbers behind any "compare the books" view.
"""

from __future__ import annotations

import re

from . import canon, db, library


def _bible(module_id: str = ""):
    if module_id:
        m = library.get(module_id)
        if m is not None and m.is_bible:
            return m
    mods = [m for m in library.list_all() if m.is_bible]
    if not mods:
        return None
    try:
        from . import workspace as _ws
        fav = _ws.top_bible_module()
        if fav is not None and fav.is_bible:
            return fav
    except Exception:  # noqa: BLE001
        pass
    mods.sort(key=lambda m: (m.lang != "eng"))
    return mods[0]


_MOODS = [
    ("lament", ("weep", "tear", "cry", "afflict", "trouble", "sorrow",
                "mourn", "groan", "anguish", "despair", "forsaken", "enemy",
                "enemies", "how long")),
    ("praise", ("praise", "hallelujah", "sing", "glory", "exalt", "bless",
                "blessed", "magnify", "rejoice")),
    ("thanksgiving", ("thank", "thanks", "delivered", "answered", "mercies",
                      "goodness")),
    ("trust", ("trust", "refuge", "shield", "fortress", "rock", "shepherd",
               "deliver", "hope")),
    ("royal", ("king", "throne", "anointed", "reign", "kingdom", "sceptre")),
    ("wisdom", ("wise", "wisdom", "fool", "folly", "instruction", "law",
                "statutes", "precepts", "meditate")),
    ("penitential", ("sin", "iniquity", "transgression", "forgive", "mercy",
                     "cleanse", "contrite", "repent")),
    ("imprecatory", ("curse", "destroy them", "vengeance", "shame them",
                     "let them be")),
]


def psalms_explorer(module_id: str = "") -> dict:
    m = _bible(module_id)
    if m is None:
        return {"ok": False, "error": "No Bible installed"}
    conn = db.connect()
    rows = conn.execute("SELECT chapter, verse, title, text FROM unit "
                        "WHERE module_id=? AND book='Ps' ORDER BY chapter, verse",
                        (m.id,)).fetchall()
    by_ch: dict[int, list] = {}
    for r in rows:
        by_ch.setdefault(r["chapter"], []).append(r)
    out = []
    for ch in sorted(by_ch):
        units = by_ch[ch]
        full = " ".join(u["text"] or "" for u in units).lower()
        words = re.findall(r"[a-z']+", full)
        # Short psalms cannot reach a count of two; ask less of them.
        bar = 2 if len(words) >= 150 else 1
        moods = sorted({name for name, keys in _MOODS
                        if sum(full.count(k) for k in keys) >= bar})
        supra = (units[0]["title"] or "").strip()
        first = re.sub(r"\s+", " ", units[0]["text"] or "").strip()
        if not supra or supra.lower() in ("psalms", "psalm", "psalter"):
            supra = first[:110] + ("…" if len(first) > 110 else "")
        out.append({"psalm": ch, "ref": f"Ps {ch}", "verses": len(units),
                    "words": len(words), "superscription": supra,
                    "moods": moods})
    return {"ok": True, "module_id": m.id, "bible": m.name, "psalms": out,
            "count": len(out),
            "note": "Moods are keyword vocabulary tags, not form-critical "
                    "categories; superscriptions are the edition's own titles."}


def books_stats(module_id: str = "") -> dict:
    m = _bible(module_id)
    if m is None:
        return {"ok": False, "error": "No Bible installed"}
    conn = db.connect()
    rows = conn.execute("SELECT book, chapter, verse, text FROM unit "
                        "WHERE module_id=? AND book<>'' ORDER BY book, chapter, verse",
                        (m.id,)).fetchall()
    tally: dict[str, dict] = {}
    for r in rows:
        d = tally.setdefault(r["book"], {"chapters": set(), "verses": 0,
                                         "words": 0})
        d["chapters"].add(r["chapter"])
        d["verses"] += 1
        d["words"] += len(re.findall(r"\S+", r["text"] or ""))
    # Traditional genre and authorship.  These are the conventional
    # attributions a reader expects from a "books explorer" view -- not
    # claims about composition, and labelled as such in the UI.
    _GENRE = {
        "Gen": "Law", "Exod": "Law", "Lev": "Law", "Num": "Law", "Deut": "Law",
        "Josh": "History", "Judg": "History", "Ruth": "History",
        "1Sam": "History", "2Sam": "History", "1Kgs": "History",
        "2Kgs": "History", "1Chr": "History", "2Chr": "History",
        "Ezra": "History", "Neh": "History", "Esth": "History",
        "Job": "Wisdom", "Ps": "Poetry", "Prov": "Wisdom", "Eccl": "Wisdom",
        "Song": "Poetry", "Isa": "Prophecy", "Jer": "Prophecy",
        "Lam": "Poetry", "Ezek": "Prophecy", "Dan": "Apocalyptic",
        "Hos": "Prophecy", "Joel": "Prophecy", "Amos": "Prophecy",
        "Obad": "Prophecy", "Jonah": "Prophecy", "Mic": "Prophecy",
        "Nah": "Prophecy", "Hab": "Prophecy", "Zeph": "Prophecy",
        "Hag": "Prophecy", "Zech": "Prophecy", "Mal": "Prophecy",
        "Matt": "Gospel", "Mark": "Gospel", "Luke": "Gospel", "John": "Gospel",
        "Acts": "History", "Rom": "Epistle", "1Cor": "Epistle",
        "2Cor": "Epistle", "Gal": "Epistle", "Eph": "Epistle",
        "Phil": "Epistle", "Col": "Epistle", "1Thess": "Epistle",
        "2Thess": "Epistle", "1Tim": "Epistle", "2Tim": "Epistle",
        "Titus": "Epistle", "Phlm": "Epistle", "Heb": "Epistle",
        "Jas": "Epistle", "1Pet": "Epistle", "2Pet": "Epistle",
        "1John": "Epistle", "2John": "Epistle", "3John": "Epistle",
        "Jude": "Epistle", "Rev": "Apocalyptic",
    }
    _AUTHOR = {
        "Gen": "Moses (traditional)", "Exod": "Moses (traditional)",
        "Lev": "Moses (traditional)", "Num": "Moses (traditional)",
        "Deut": "Moses (traditional)", "Josh": "Joshua (traditional)",
        "Judg": "Samuel (traditional)", "Ruth": "Samuel (traditional)",
        "1Sam": "Samuel (traditional)", "2Sam": "Samuel/Gad/Nathan (traditional)",
        "1Kgs": "Jeremiah (traditional)", "2Kgs": "Jeremiah (traditional)",
        "1Chr": "Ezra (traditional)", "2Chr": "Ezra (traditional)",
        "Ezra": "Ezra", "Neh": "Nehemiah", "Esth": "Mordecai (traditional)",
        "Job": "unknown", "Ps": "David and others", "Prov": "Solomon",
        "Eccl": "Solomon (traditional)", "Song": "Solomon (traditional)",
        "Isa": "Isaiah", "Jer": "Jeremiah", "Lam": "Jeremiah (traditional)",
        "Ezek": "Ezekiel", "Dan": "Daniel", "Hos": "Hosea", "Joel": "Joel",
        "Amos": "Amos", "Obad": "Obadiah", "Jonah": "Jonah", "Mic": "Micah",
        "Nah": "Nahum", "Hab": "Habakkuk", "Zeph": "Zephaniah",
        "Hag": "Haggai", "Zech": "Zechariah", "Mal": "Malachi",
        "Matt": "Matthew", "Mark": "Mark", "Luke": "Luke", "John": "John",
        "Acts": "Luke", "Rom": "Paul", "1Cor": "Paul", "2Cor": "Paul",
        "Gal": "Paul", "Eph": "Paul", "Phil": "Paul", "Col": "Paul",
        "1Thess": "Paul", "2Thess": "Paul", "1Tim": "Paul", "2Tim": "Paul",
        "Titus": "Paul", "Phlm": "Paul", "Heb": "unknown",
        "Jas": "James", "1Pet": "Peter", "2Pet": "Peter",
        "1John": "John", "2John": "John", "3John": "John", "Jude": "Jude",
        "Rev": "John",
    }
    books = []
    for osis, d in tally.items():
        b = canon.BOOK_BY_OSIS.get(osis)
        books.append({"osis": osis, "name": b.name if b else osis,
                      "group": b.group if b else "",
                      "genre": _GENRE.get(osis, "Other"),
                      "author": _AUTHOR.get(osis, "unknown"),
                      "testament": ("OT" if (b and b.group in ("OT",)) else
                                    ("NT" if (b and b.group == "NT") else "")),
                      "chapters": len(d["chapters"]), "verses": d["verses"],
                      "words": d["words"]})
    order = {b.osis: i for i, b in enumerate(canon.BOOKS_66)}
    books.sort(key=lambda x: order.get(x["osis"], 999))
    return {"ok": True, "module_id": m.id, "bible": m.name, "books": books,
            "totals": {"books": len(books),
                       "chapters": sum(b["chapters"] for b in books),
                       "verses": sum(b["verses"] for b in books),
                       "words": sum(b["words"] for b in books)}}
