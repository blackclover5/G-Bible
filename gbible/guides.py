"""Exegetical guides: the canon, the gospel harmonies, and what a chapter holds.

Three different kinds of thing, and the difference matters:

* The **canon** is arithmetic.  Which books, in which order, how many chapters
  and verses, per tradition.  All of it is in `canon`, so nothing here is
  asserted that is not computed.

* A **gospel harmony** is a reference table, not data: the traditional
  alignment of the four narratives by event.  Authorities differ in how they
  cut the sections, so this is one standard layout, labelled as such, and it
  points at your own Bible for the text rather than restating it.

* A **chapter guide** is derived from what you have installed -- the topics,
  commentaries and cross-references that actually bear on a chapter.  It is
  emphatically *not* an editorial outline, and it says so.
"""

from __future__ import annotations

from . import canon, db, library

# --------------------------------------------------------------------------
# canon

# The 39 and 27 are the New Testament by full name and by short name, which
# `canon` does not expose as constants -- only the 66, the KJA list, the
# Catholic list and the apocrypha.
_NT_FULL = tuple(b.name for b in canon.BOOKS_66 if b.group == "NT")
_NT_SHORT = tuple(b.short for b in canon.BOOKS_66 if b.group == "NT")

_TAB = {
    "66": (canon.BOOKS_66, "Protestant 66"),
    "39": (tuple(b for b in canon.BOOKS_66 if b.group == "NT"),
           "Protestant 39 — the New Testament, full names (Matthew, Mark, …)"),
    "27": (tuple(b for b in canon.BOOKS_66 if b.group == "NT"),
           "Protestant 27 — the same New Testament, abbreviations (Matt, Mk, …)"),
    "kja": (canon.BOOKS_KJA, "KJV / Protestant 66"),
    "catholic": (canon.BOOKS_CATHOLIC, "Catholic (with deuterocanonical)"),
    "ap": (canon.BOOKS_AP, "Apocrypha only"),
}

# The traditional shape of the 66, in canonical order.  Counts are exact: the
# Old Testament is 5 + 12 + 5 + 5 + 12 = 39, the New Testament 4 + 1 + 21 + 1 = 27.
_GROUP_OF = [
    (5, "Pentateuch"), (12, "Historical books"), (5, "Wisdom & poetry"),
    (5, "Major prophets"), (12, "Minor prophets"),
    (4, "Gospels"), (1, "Acts"), (21, "Epistles"), (1, "Revelation"),
]


def canon_table(tradition: str = "66", v11n: str = "KJV") -> dict:
    """One canon table: the books, in order, with their real sizes."""
    books, label = _TAB.get((tradition or "66").lower(), _TAB["66"])
    out = []
    for b in books:
        ch = canon.chapter_count(v11n, b.osis)
        vs = sum(canon.verse_count(v11n, b.osis, c)
                 for c in range(1, ch + 1))
        out.append({"osis": b.osis, "usfm": b.usfm, "name": b.name,
                    "short": b.short, "group": b.group, "ordinal": b.ordinal,
                    "chapters": ch, "verses": vs})
    # roll the first six groups so the reader sees the shape
    groups, i = [], 0
    for n, name in _GROUP_OF:
        chunk = out[i:i + n]
        if not chunk:
            break
        groups.append({"label": name, "books": [b["osis"] for b in chunk]})
        i += n
    rest = out[i:]
    if rest:
        groups.append({"label": "Remaining", "books": [b["osis"] for b in rest]})
    return {"ok": True, "tradition": tradition, "label": label,
            "v11n": v11n, "count": len(out),
            "chapters": sum(b["chapters"] for b in out),
            "verses": sum(b["verses"] for b in out),
            "groups": groups, "books": out}


def canon_charts() -> list[dict]:
    """Every tradition, with how the counts differ."""
    out = []
    for key in ("66", "39", "27", "catholic", "ap"):
        t = canon_table(key)
        out.append({"key": key, "label": t["label"], "count": t["count"],
                    "chapters": t["chapters"], "verses": t["verses"]})
    return out


# --------------------------------------------------------------------------
# gospel harmony

# The traditional alignment, grouped by event.  Section boundaries differ
# between authorities; this follows the common five-part shape (birth and
# infancy, ministry, Galilean ministry, passion, resurrection) and each entry
# names the pericope in each gospel so your own text supplies the words.
_HARMONY: list[tuple[str, list[tuple[str, str]]]] = [
    ("The setting", [("Mark", "1:1"), ("Matthew", "1:1"), ("Luke", "1:1"),
                     ("John", "1:1")]),
    ("Birth and infancy", [("Mark", "—"), ("Matthew", "1:18-25"),
                          ("Luke", "2:1-7"), ("John", "1:14-18")]),
    ("Baptism and temptation", [("Mark", "1:9-13"), ("Matthew", "3:13-4:11"),
                                ("Luke", "3:21-4:13"), ("John", "1:19-28")]),
    ("Calling the first disciples", [("Mark", "1:16-20"), ("Matthew", "4:18-22"),
                                     ("Luke", "5:1-11"), ("John", "1:35-51")]),
    ("First miracle: Capernaum", [("Mark", "1:21-28"), ("Matthew", "4:12-13"),
                                  ("Luke", "4:31-38"), ("John", "2:1-11")]),
    ("Call of Matthew", [("Mark", "2:15-17"), ("Matthew", "9:9-13"),
                         ("Luke", "5:27-32"), ("John", "—")]),
    ("Cure of the paralytic", [("Mark", "2:1-12"), ("Matthew", "9:1-8"),
                               ("Luke", "5:17-26"), ("John", "—")]),
    ("Cure of the man with a withered hand", [("Mark", "3:1-6"),
                                              ("Matthew", "12:9-14"),
                                              ("Luke", "6:6-11"), ("John", "—")]),
    ("Calling of the twelve", [("Mark", "3:13-19"), ("Matthew", "5:1-12"),
                               ("Luke", "6:12-16"), ("John", "—")]),
    ("Sermon on the mount", [("Mark", "4:1-20"), ("Matthew", "5:1-7:23"),
                             ("Luke", "6:17-49"), ("John", "—")]),
    ("Healing of the centurion's servant", [("Mark", "4:35-41"),
                                            ("Matthew", "8:1-13"),
                                            ("Luke", "7:1-10"),
                                            ("John", "4:46-54")]),
    ("Raising of Jairus' daughter", [("Mark", "5:21-43"), ("Matthew", "9:18-26"),
                                     ("Luke", "8:40-56"), ("John", "—")]),
    ("Feeding of the five thousand", [("Mark", "6:30-44"), ("Matthew", "14:13-21"),
                                      ("Luke", "9:10-17"), ("John", "6:1-15")]),
    ("Walking on the water", [("Mark", "6:45-52"), ("Matthew", "14:22-33"),
                              ("Luke", "9:18-22"), ("John", "6:16-21")]),
    ("Confession of Peter at Caesarea", [("Mark", "8:27-33"), ("Matthew", "16:13-23"),
                                         ("Luke", "9:18-22"), ("John", "—")]),
    ("Transfiguration", [("Mark", "9:2-8"), ("Matthew", "17:1-8"),
                         ("Luke", "9:28-36"), ("John", "—")]),
    ("The boy demon-possessed", [("Mark", "9:14-29"), ("Matthew", "17:14-21"),
                                 ("Luke", "9:37-43"), ("John", "—")]),
    ("Second feeding", [("Mark", "8:1-10"), ("Matthew", "15:32-39"),
                        ("Luke", "9:37-43  "), ("John", "6:30-44")]),
    ("Confession of Peter's denial", [("Mark", "14:27-31"), ("Matthew", "26:31-35"),
                                      ("Luke", "22:31-34"), ("John", "13:36-38")]),
    ("Entry into Jerusalem", [("Mark", "11:1-11"), ("Matthew", "21:1-11"),
                              ("Luke", "19:1-11"), ("John", "12:12-19")]),
    ("Cleansing of the temple", [("Mark", "11:15-18"), ("Matthew", "21:12-13"),
                                ("Luke", "19:45-46"), ("John", "2:13-22")]),
    ("The good Samaritan", [("Mark", "—"), ("Matthew", "—"),
                            ("Luke", "10:25-37"), ("John", "—")]),
    ("Washing of the feet", [("Mark", "—"), ("Matthew", "—"),
                             ("Luke", "22:24-27"), ("John", "13:1-17")]),
    ("Last Supper", [("Mark", "14:12-31"), ("Matthew", "26:17-35"),
                     ("Luke", "22:7-38"), ("John", "13:17-38")]),
    ("Agony in Gethsemane", [("Mark", "14:32-42"), ("Matthew", "26:36-46"),
                             ("Luke", "22:39-46"), ("John", "—")]),
    ("Betrayal and arrest", [("Mark", "14:43-52"), ("Matthew", "26:47-56"),
                             ("Luke", "22:47-53"), ("John", "18:1-12")]),
    ("Trial before the Sanhedrin", [("Mark", "14:53-72"), ("Matthew", "26:57-27:2"),
                                   ("Luke", "22:54-71"), ("John", "18:12-24")]),
    ("Peter's denial", [("Mark", "14:53-72"), ("Matthew", "26:57-75"),
                        ("Luke", "22:54-62"), ("John", "18:15-27")]),
    ("Trial before Pilate", [("Mark", "15:1-15"), ("Matthew", "27:1-14"),
                             ("Luke", "23:1-5"), ("John", "18:28-19:16")]),
    ("Carrying of the cross", [("Mark", "15:21-22"), ("Matthew", "27:31-32"),
                               ("Luke", "23:26-27"), ("John", "19:16-17")]),
    ("Crucifixion", [("Mark", "15:22-37"), ("Matthew", "27:33-50"),
                     ("Luke", "23:33-46"), ("John", "19:17-37")]),
    ("Death and burial", [("Mark", "15:41-47"), ("Matthew", "27:50-66"),
                          ("Luke", "23:47-56"), ("John", "19:31-42")]),
    ("Resurrection", [("Mark", "16:1-8"), ("Matthew", "28:1-10"),
                      ("Luke", "24:1-12"), ("John", "20:1-18")]),
    ("Appearances and Great Commission", [("Mark", "16:9-20"),
                                          ("Matthew", "28:16-20"),
                                          ("Luke", "24:13-53"),
                                          ("John", "20:19-23; 21:1-25")]),
    ("Ascension", [("Mark", "16:19-20"), ("Matthew", "28:16-20"),
                   ("Luke", "24:50-53"), ("John", "—")]),
]

_GOSPELS = ("Mark", "Matthew", "Luke", "John")


def harmony() -> dict:
    rows = []
    for event, refs in _HARMONY:
        by = {g: p for g, p in refs if g in _GOSPELS}
        rows.append({"event": event,
                     "refs": [{"gospel": g, "pericope": by.get(g, "—")}
                              for g in _GOSPELS]})
    return {"ok": True, "rows": rows, "gospels": list(_GOSPELS),
            "note": "A standard alignment of the four narratives by event. "
                    "Section boundaries differ between authorities; the words "
                    "are in your Bible, not here."}


# Well-established Old Testament parallels: same events told twice (or
# thrice). References are facts, not prose, and each row is checkable in any
# installed Bible — which is why this table can ship where a commentary
# cannot.
_OT_PARALLELS: list[tuple[str, list[str]]] = [
    ("David's song of deliverance", ["2 Sam 22", "Ps 18"]),
    ("Death of Saul", ["1 Sam 31", "1 Chr 10"]),
    ("Covenant with David", ["2 Sam 7", "1 Chr 17"]),
    ("Dedication of the temple", ["1 Kgs 8", "2 Chr 5", "2 Chr 6", "2 Chr 7"]),
    ("Reigns of Abijam and Asa", ["1 Kgs 15:1-24", "2 Chr 13", "2 Chr 14",
                                  "2 Chr 15", "2 Chr 16"]),
    ("Hezekiah and Sennacherib", ["2 Kgs 18", "2 Kgs 19", "2 Chr 32",
                                  "Isa 36", "Isa 37"]),
    ("Josiah's reform", ["2 Kgs 22", "2 Kgs 23:1-27", "2 Chr 34", "2 Chr 35"]),
    ("Fall of Jerusalem", ["2 Kgs 25", "2 Chr 36", "Jer 52"]),
    ("Cyrus's decree", ["2 Chr 36:22-23", "Ezra 1:1-4"]),
    ("The Ten Commandments", ["Exod 20:1-17", "Deut 5:6-21"]),
    ("The nations' future", ["Isa 2:2-4", "Mic 4:1-3"]),
    ("Edom judged", ["Obad 1-9", "Jer 49:7-16"]),
    ("Twin psalms of the poor", ["Ps 14", "Ps 53"]),
    ("A prayer repeated", ["Ps 40:13-17", "Ps 70"]),
    ("Mornings in the Psalter", ["Ps 57:7-11", "Ps 60:5-12", "Ps 108"]),
]


def ot_parallels() -> dict:
    return {"ok": True,
            "rows": [{"event": e, "passages": p} for e, p in _OT_PARALLELS],
            "note": "Same events told more than once — check each in your "
                    "own Bible."}


# --------------------------------------------------------------------------
# chapter guide

def _priority_rank(ref: str = "", req_type: str = "") -> dict[str, int]:
    """module id -> rank, from the reader's own priority order and rules.

    Three separate places rank commentaries for the reader -- this module's
    chapter guide, this module's passage guide, and study.commentaries_at -- and
    until they all asked this one question they disagreed.  The chapter guide
    ranked by nothing at all (a bare GROUP BY, so whatever order SQLite
    happened to produce), the passage guide ranked by the priority column, which
    every module sat at zero on, and the word study ranked by module name.  One
    answer here means one order everywhere.
    """
    from . import workspace as _ws
    try:
        return {mid: i for i, mid in enumerate(
            _ws.resolve_priority(req_type=req_type, ref=ref))}
    except Exception:               # an ordering preference must lose a note
        return {}


def chapter_guide(ref: str, *, module_id: str = "") -> dict:
    """What your installed library actually has for a chapter.

    Not an editorial outline -- there is no outline data installed.  This is
    what is *here*: the topics that mention the chapter, the commentaries
    anchored in it, and the cross-references pointing into it.
    """
    from . import study
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r}"}
    f = next(iter(rr.refs()), None)
    if f is None:
        return {"ok": False, "error": f"cannot read {ref!r}"}
    conn = db.connect()
    rank = _priority_rank(ref=canon.format_ref(f), req_type="commentary")

    # A bare book name is a first-class request, not a malformed one: every book
    # in the canon table links here, and answering "no chapter in that
    # reference" made all 66 of them a dead click.  Given one, report the whole
    # book -- which commentaries cover it, and which chapters have topics --
    # and say plainly that the span is the book.
    if not f.chapter:
        chapters = conn.execute(
            "SELECT DISTINCT u.chapter c FROM unit u JOIN module m"
            " ON m.id=u.module_id WHERE u.book=? AND m.type='Commentary'"
            " AND u.chapter>0 ORDER BY c", (f.book,)).fetchall()
        per = [r["c"] for r in chapters]
        commentaries = conn.execute(
            "SELECT u.module_id, m.name, count(*) c FROM unit u "
            "JOIN module m ON m.id=u.module_id "
            "WHERE u.book=? AND m.type='Commentary' GROUP BY u.module_id",
            (f.book,)).fetchall()
        commentaries = sorted(commentaries, key=lambda r: (
            rank.get(r["module_id"], 10 ** 6), r["name"]))
        topics = conn.execute(
            "SELECT u.module_id, m.name, u.title, substr(u.text,1,300) t "
            "FROM unit u JOIN module m ON m.id=u.module_id "
            "WHERE m.type='FactBook' AND u.text LIKE ? LIMIT 12",
            (f"%{f.book} %",)).fetchall()
        return {
            "ok": True, "ref": f.book, "book": f.book, "whole_book": True,
            "commentaries": [{"module_id": r["module_id"], "module": r["name"],
                              "notes": r["c"]} for r in commentaries],
            "topics": [{"module_id": r["module_id"], "module": r["name"],
                        "title": r["title"], "text": r["t"]} for r in topics],
            "chapters_covered": len(per),
            "first_chapter": per[0] if per else 1,
            "outline": None,
            "outline_note": "Whole book, not a chapter: every commentary in your "
                            "library that covers " + f.book + ", and the topic "
                            "entries that mention it.",
            "_lo": per[0] if per else 1,
            "_hi": per[-1] if per else 1,
            "_span": len(per) or 1,
            "_unref": 0,
        }

    osis = f"{f.book}.{f.chapter}.%"

    commentaries = conn.execute(
        "SELECT u.module_id, m.name, count(*) c FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "WHERE u.book=? AND u.chapter=? AND m.type='Commentary' "
        "GROUP BY u.module_id", (f.book, f.chapter)).fetchall()
    # No ORDER BY above, so the order was whatever the GROUP BY produced. See
    # _priority_rank for why the reader's order is asked for explicitly here.
    commentaries = sorted(commentaries, key=lambda r: (
        rank.get(r["module_id"], 10 ** 6), r["name"]))
    topics = conn.execute(
        "SELECT u.module_id, m.name, u.title, substr(u.text,1,300) t "
        "FROM unit u JOIN module m ON m.id=u.module_id "
        "WHERE m.type='FactBook' AND u.text LIKE ? LIMIT 12",
        (f"%{f.book} {f.chapter}:%",)).fetchall()
    span = 20
    lo, hi = max(1, f.chapter), max(1, f.chapter)
    mentioned = conn.execute(
        "SELECT DISTINCT u.module_id, m.name FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "JOIN xref x ON x.module_id=u.module_id AND x.to_key=u.key "
        "WHERE m.type='FactBook' AND x.to_key LIKE ? LIMIT 12", (osis,)).fetchall()
    return {
        "ok": True, "ref": f"{f.book} {f.chapter}",
        "commentaries": [{"module_id": r["module_id"], "module": r["name"],
                          "notes": r["c"]} for r in commentaries],
        "topics": [{"module_id": r["module_id"], "module": r["name"],
                    "title": r["title"], "text": r["t"]} for r in topics],
        "outline": None,
        "outline_note": "No outline data is installed. The Berean and the other "
                        "USFX texts here carry Strong's but no study outlines, "
                        "so there is nothing to show rather than something to "
                        "invent.",
        "_lo": lo, "_hi": hi, "_span": span, "_unref": len(mentioned),
    }


# --------------------------------------------------------------------------
# Pack 4: customizable guide framework.
#
# A guide is an ordered list of sections; each section searches one part of
# the installed library for the guide's key (a passage, word or topic) and
# collates it one way. Sections run standalone too (single-stack guides).
# Config lives in `setting.guide_configs`: no schema change, and a user with
# no config gets the defaults below.
# --------------------------------------------------------------------------

SECTION_DEFS: dict[str, dict] = {
    "commentaries": {"title": "Commentaries", "kinds": ["passage"],
                     "about": "Every installed commentary anchored at the "
                              "verse, chapter or book."},
    "crossrefs": {"title": "Cross-references", "kinds": ["passage"],
                  "about": "Outgoing and incoming cross-references."},
    "parallel": {"title": "Parallel passages", "kinds": ["passage"],
                 "about": "Harmony pericopes and parallel-marked xrefs for "
                          "the same event."},
    "literary": {"title": "Literary typing", "kinds": ["passage"],
                 "about": "Genre of the book, from the canon table."},
    "media": {"title": "Media resources", "kinds": ["passage"],
              "about": "Installed images and maps mentioning the passage."},
    "topics": {"title": "Topics", "kinds": ["passage", "topic"],
               "about": "Fact-book articles citing the passage or topic."},
    "places": {"title": "Places", "kinds": ["passage"],
               "about": "Gazetteer places named by the passage."},
    "people": {"title": "People", "kinds": ["passage"],
               "about": "Names in the passage with their meanings."},
    "variants": {"title": "Text comparison", "kinds": ["passage"],
                 "about": "How installed translations render the verse."},
    "grammars": {"title": "Grammars", "kinds": ["passage"],
                 "about": "Installed books mentioning the passage — PD "
                          "grammars and manuals where you own them, labelled "
                          "as mentions, not as a grammar database."},
    "extrabiblical": {"title": "Ancient literature", "kinds": ["passage"],
                      "about": "Installed books outside the canon mentioning "
                               "the passage (Josephus, Tacitus and the like "
                               "where installed)."},
    "words": {"title": "Words", "kinds": ["passage"],
              "about": "Strong's numbers in the verse with occurrence counts."},
    "dictionaries": {"title": "Dictionaries", "kinds": ["word", "topic"],
                     "about": "Short glosses for the term."},
    "articles": {"title": "Articles", "kinds": ["word", "topic"],
                 "about": "Full encyclopaedia entries for the term."},
    "occurrences": {"title": "Occurrences", "kinds": ["word"],
                    "about": "Every tagged occurrence of the Strong's number."},
    "syntax": {"title": "Syntax", "kinds": ["passage"],
               "about": "Stored treebank analysis at the verse, where a "
                        "CoNLL-U module is installed."},
    "sermon": {"title": "Sermon outlines", "kinds": ["passage"],
               "about": "Installed sermon-form works bearing on the passage, "
                        "in the authors' own points."},
    "markers": {"title": "Your sermons & studies", "kinds": ["passage"],
                "about": "Sermon notes and Bible studies you have tagged with "
                         "this passage, with a preview of each."},
    "counsel": {"title": "Counsel", "kinds": ["topic"],
                "about": "Seed passages plus what the installed library holds "
                         "on a pastoral topic."},
    "citedby": {"title": "Cited by", "kinds": ["passage"],
                "about": "Outgoing cross-references and incoming citations, "
                         "grouped by resource."},
    "important": {"title": "Important words", "kinds": ["passage"],
                  "about": "The verse's words ranked by how often installed "
                           "commentaries discuss them."},
}

DEFAULT_GUIDES: dict[str, list[dict]] = {
    "passage": [{"id": "commentaries", "limit": 10, "sort": "priority"},
                {"id": "crossrefs", "limit": 10},
                {"id": "parallel", "limit": 10},
                {"id": "topics", "limit": 6},
                {"id": "places", "limit": 12},
                {"id": "people", "limit": 12},
                {"id": "media", "limit": 8},
                {"id": "literary", "limit": 1},
                {"id": "citedby", "limit": 0},
                {"id": "sermon", "limit": 6},
                {"id": "markers", "limit": 10}],
    "exegetical": [{"id": "words", "limit": 40},
                   {"id": "important", "limit": 10},
                   {"id": "syntax", "limit": 1},
                   {"id": "variants", "limit": 12},
                   {"id": "grammars", "limit": 8},
                   {"id": "commentaries", "limit": 10, "sort": "priority"}],
    "word": [{"id": "dictionaries", "limit": 8},
             {"id": "articles", "limit": 6},
             {"id": "occurrences", "limit": 50}],
    "topic": [{"id": "articles", "limit": 6},
              {"id": "dictionaries", "limit": 8},
              {"id": "topics", "limit": 6},
              {"id": "counsel", "limit": 8},
              {"id": "media", "limit": 8}],
    "wordstudy": [{"id": "dictionaries", "limit": 10},
                  {"id": "articles", "limit": 8},
                  {"id": "occurrences", "limit": 80},
                  {"id": "important", "limit": 5},
                  {"id": "syntax", "limit": 1}],
    "sermon_starter": [{"id": "sermon", "limit": 10},
                       {"id": "markers", "limit": 10},
                       {"id": "commentaries", "limit": 10, "sort": "priority"},
                       {"id": "topics", "limit": 6},
                       {"id": "counsel", "limit": 6},
                       {"id": "crossrefs", "limit": 10},
                       {"id": "parallel", "limit": 6}],
}

#: Guides the user has created themselves, by name.  Stored in the same
#: guide_configs setting as the presets, under a reserved key prefix, so one
#: setting holds both and a guide can never be saved over a preset by accident.
_CUSTOM_PREFIX = "custom:"


def guide_presets() -> list[str]:
    """Every preset guide name, in display order."""
    return ["passage", "exegetical", "word", "topic", "wordstudy",
            "sermon_starter"]


def guide_list() -> list[dict]:
    """Every guide available: presets plus the user's own, with which is which."""
    from . import db as _db
    try:
        all_c = _db.get_setting("guide_configs", {})
    except Exception:  # noqa: BLE001
        all_c = {}
    if not isinstance(all_c, dict):
        all_c = {}
    custom = sorted(k[len(_CUSTOM_PREFIX):] for k in all_c
                    if k.startswith(_CUSTOM_PREFIX))
    out = []
    for name in guide_presets():
        secs = all_c.get(name)
        out.append({"name": kind_label(name), "id": name, "preset": True,
                    "sections": len(secs) if isinstance(secs, list) else len(DEFAULT_GUIDES.get(name, []))})
    for name in custom:
        secs = all_c.get(_CUSTOM_PREFIX + name, [])
        out.append({"name": name, "id": name, "preset": False,
                    "sections": len(secs) if isinstance(secs, list) else 0})
    return out


def kind_label(name: str) -> str:
    """A preset's display name.  Custom guides use their own name directly."""
    return {"passage": "Passage guide",
            "exegetical": "Exegetical guide",
            "word": "Word guide",
            "topic": "Topic guide",
            "wordstudy": "Word study guide",
            "sermon_starter": "Sermon starter guide",
            }.get(name, name)


def guide_create(name: str, sections: list[dict] | None = None) -> dict:
    """Save a user-defined guide under a name of the reader's choosing.

    The name is stored as-is (it is displayed), but namespaced under a prefix
    so it can never collide with a preset -- saving "passage" does nothing
    rather than overwriting the passage guide's defaults.
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Name the guide."}
    if len(name) > 60:
        return {"ok": False, "error": "Keep the name under 60 characters."}
    if name.lower() in [p.lower() for p in guide_presets()]:
        return {"ok": False, "error": f"{name!r} is a built-in guide name."}
    from . import db as _db
    try:
        all_c = _db.get_setting("guide_configs", {})
    except Exception:  # noqa: BLE001
        all_c = {}
    if not isinstance(all_c, dict):
        all_c = {}
    key = _CUSTOM_PREFIX + name
    clean = []
    for s in sections or []:
        if not isinstance(s, dict) or s.get("id") not in SECTION_DEFS:
            continue
        clean.append({"id": s["id"],
                      "limit": max(1, min(200, int(s.get("limit") or 10))),
                      "sort": (s.get("sort") or "priority")})
    all_c[key] = clean
    _db.set_setting("guide_configs", all_c)
    return {"ok": True, "name": name, "sections": clean}


def guide_delete(name: str) -> dict:
    """Remove a user-defined guide.  Presets cannot be deleted."""
    name = (name or "").strip()
    from . import db as _db
    try:
        all_c = _db.get_setting("guide_configs", {})
    except Exception:  # noqa: BLE001
        return {"ok": True, "name": name}
    if not isinstance(all_c, dict):
        all_c = {}
    key = _CUSTOM_PREFIX + name
    was = key in all_c
    all_c.pop(key, None)
    _db.set_setting("guide_configs", all_c)
    return {"ok": True, "name": name, "deleted": was}


def guide_sections() -> list[dict]:
    return [{"id": k, **v} for k, v in SECTION_DEFS.items()]


def get_config(guide: str) -> list[dict]:
    from . import db as _db
    try:
        all_c = _db.get_setting("guide_configs", {})
    except Exception:  # noqa: BLE001
        all_c = {}
    if not isinstance(all_c, dict):
        all_c = {}
    # Custom guides are stored under a prefix; presets are stored bare.
    key = guide if guide in all_c else _CUSTOM_PREFIX + guide
    if key in all_c:
        secs = all_c[key]
        if isinstance(secs, list) and secs:
            return [s for s in secs if s.get("id") in SECTION_DEFS]
    return [dict(s) for s in DEFAULT_GUIDES.get(guide, DEFAULT_GUIDES["passage"])]


def set_config(guide: str, sections: list[dict]) -> dict:
    from . import db as _db
    clean = []
    for s in sections or []:
        if not isinstance(s, dict) or s.get("id") not in SECTION_DEFS:
            continue
        clean.append({"id": s["id"],
                      "limit": max(1, min(200, int(s.get("limit") or 10))),
                      "sort": (s.get("sort") or "priority"),
                      "collection": (s.get("collection") or "")})
    try:
        all_c = _db.get_setting("guide_configs", {})
    except Exception:  # noqa: BLE001
        all_c = {}
    if not isinstance(all_c, dict):
        all_c = {}
    # A preset is stored bare; a custom guide is prefixed.  Saving to a preset
    # name edits that preset's config; saving to a custom name edits the custom
    # guide.  The two never collide.
    key = guide if guide in DEFAULT_GUIDES else _CUSTOM_PREFIX + guide
    all_c[key] = clean or [dict(s) for s in DEFAULT_GUIDES["passage"]]
    _db.set_setting("guide_configs", all_c)
    return {"ok": True, "guide": guide, "sections": all_c[key]}


def _ref_parts(key: str):
    rr = canon.parse_ref(key)
    if rr is None:
        return None
    return next(iter(rr.refs()), None)


def _era_of(year: str) -> str:
    try:
        y = int(str(year).strip()[:4])
    except (ValueError, TypeError):
        return "Unknown"
    if y < 1900:
        return "Classic"
    if y < 1950:
        return "Modern"
    return "Contemporary"


def sec_commentaries(key: str, limit: int = 10, sort: str = "priority",
                     offset: int = 0, collection: str = "") -> dict:
    from . import study
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    mods = {m.id: m for m in library.list_all()}
    if collection:
        from . import organise
        want = set(organise.collection_members(collection))
    else:
        want = set()
    rows = study.commentaries_at(conn, f.book, f.chapter or 0, f.verse or 0) or []
    items = []
    for r in (rows if isinstance(rows, list) else rows.get("notes", [])):
        mid = r.get("module_id") if isinstance(r, dict) else None
        if not mid or mid not in mods:
            continue
        if want and mid not in want:
            continue
        m = mods[mid]
        items.append({"module_id": mid, "module": m.name, "author": m.author,
                      "series": m.version or "", "denomination": "Unknown",
                      "type": m.type, "era": _era_of(m.year),
                      "priority": m.priority, "note": r})
    sk = (sort or "priority").lower()
    if sk == "author":
        items.sort(key=lambda x: ((x["author"] or "zzz"), x["module"]))
    elif sk == "series":
        items.sort(key=lambda x: ((x["series"] or "zzz"), x["module"]))
    elif sk == "type":
        items.sort(key=lambda x: (x["type"], x["module"]))
    elif sk == "era":
        items.sort(key=lambda x: (x["era"], x["module"]))
    elif sk == "denomination":
        items.sort(key=lambda x: (x["denomination"], x["module"]))
    else:
        # "Priority" is the reader's own order, not the database's. Sorting on
        # the priority column alone ranked every module at 0 and fell through
        # to alphabetical -- so the chapter guide showed Adam Clarke first
        # because of the A, not because you read Clarke -- and the advanced
        # rules, which do carry an order, were consulted nowhere in this
        # function. resolve_priority applies those rules for this passage and
        # then falls back to the priority column, which is the same order the
        # parallel stepper uses, so one list of rules means the same thing
        # everywhere it is consulted.
        from . import workspace as _ws
        try:
            rank = {mid: i for i, mid in
                    enumerate(_ws.resolve_priority(
                        req_type="commentary",
                        ref=f"{f.book} {f.chapter or 0}:{f.verse or 1}"))}
        except Exception:                       # rules must never break a guide
            rank = {}
        items.sort(key=lambda x: (
            rank.get(x["module_id"], 10 ** 6), -(x["priority"] or 0), x["module"]))
    total = len(items)
    return {"ok": True, "total": total, "items": items[offset:offset + limit],
            "more": total > offset + limit, "sort": sort or "priority"}


def sec_crossrefs(key: str, limit: int = 10, offset: int = 0, **_) -> dict:
    from . import study
    try:
        panel = study.crossref_panel(key)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    items = panel.get("refs") or panel.get("items") or []
    total = len(items)
    return {"ok": True, "total": total, "items": items[offset:offset + limit],
            "more": total > offset + limit}


def sec_parallel(key: str, limit: int = 10, **_) -> dict:
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    out = []
    if f.book in ("Matt", "Mark", "Luke", "John"):
        for row in harmony()["rows"]:
            for cell in row["refs"]:
                if cell["gospel"] == f.book or (
                        cell["gospel"] == {"Matt": "Matthew"}.get(f.book, f.book)):
                    pass
            per = {c["gospel"]: c["pericope"] for c in row["refs"]}
            if any(p != "—" for p in per.values()):
                out.append({"event": row["event"], "pericopes": per})
    conn = db.connect()
    rr = canon.parse_ref(key)
    osis = next(iter(rr.refs())).osis_id() if rr else key
    for r in conn.execute(
            "SELECT module_id, from_key, to_key FROM xref WHERE kind='parallel' "
            "AND (from_key=? OR to_key=?) LIMIT 20", (osis, osis)).fetchall():
        out.append({"event": "Parallel-marked cross-reference",
                    "from": r["from_key"], "to": r["to_key"],
                    "module_id": r["module_id"]})
    # Old Testament parallels: does this verse sit inside one?
    try:
        vref = canon.parse_ref(f"{f.book} {f.chapter}:{f.verse or 1}")
        vkey = next(iter(vref.refs())).osis_id() if vref else ""
    except Exception:  # noqa: BLE001
        vkey = ""
    if vkey:
        for event, passages in _OT_PARALLELS:
            hit = False
            for ps in passages:
                prr = canon.parse_ref(ps)
                if prr is None:
                    continue
                for r in prr.refs():
                    if r.book == f.book and (r.chapter or 0) == (f.chapter or 0):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                out.append({"event": event, "passages": passages})
    return {"ok": True, "total": len(out), "items": out[:limit],
            "more": len(out) > limit}


def sec_literary(key: str, **_) -> dict:
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    b = canon.BOOK_BY_OSIS.get(f.book)
    group = b.group if b else "Unknown"
    genre = {"OT": "Old Testament narrative, law, poetry or prophecy — see "
                   "canon group below.",
             "NT": "New Testament gospel, history, epistle or apocalypse — "
                   "see canon group below."}.get(group, group)
    table = canon_table("66")
    glabel = next((g["label"] for g in table["groups"] if f.book in g["books"]),
                  group)
    return {"ok": True, "book": f.book, "group": group, "genre": glabel,
            "note": genre}


def sec_media(key: str, limit: int = 8, **_) -> dict:
    """Maps and atlas places that bear on this passage.

    Matching used to be `title LIKE '%Exodus 2%'`, which could only ever find a
    row whose text happened to contain that string -- and the atlas places do
    not: their references are stored in `extra.passages` as abbreviated OSIS
    ("Josh.21.30"), while the column being searched holds prose.  So the section
    found nothing for most passages while appearing to work.  It now matches the
    reference that is actually recorded, through `json_each`, which is also an
    indexable join rather than a scan of every place's prose.

    A `Map` module is a historical image with no passage references at all --
    the four in this library are a 1624 Exodus route, a twelve-tribes map, an
    1794 Anville map and a map of the Crusader states.  Matching those by
    filename ("Exodus" appears in the Ortelius one) put an image in front of a
    verse on the strength of its file name, so they are listed on their own
    instead and only when no specific passage was asked about.
    """
    conn = db.connect()
    f = _ref_parts(key)
    ids: list[str] = []
    rows: list = []
    if f and f.chapter:
        prefix = f"{f.book}.{f.chapter}"
        rows = conn.execute(
            "SELECT u.module_id, m.name, u.key, u.title FROM unit u "
            "JOIN module m ON m.id=u.module_id "
            "WHERE m.type='Atlas' AND m.installed_at>0 "
            "AND EXISTS (SELECT 1 FROM json_each(u.extra, '$.passages') j "
            "WHERE j.value LIKE ?) ORDER BY m.name LIMIT ?",
            (prefix + ".%", limit)).fetchall()
        ids = [r["module_id"] for r in rows]
    # Historical maps have no verses behind them, so they are a fallback for
    # "show me the media" rather than an answer to "what is this verse".
    if not rows and not (f and f.chapter):
        rows = conn.execute(
            "SELECT u.module_id, m.name, u.key, u.title FROM unit u "
            "JOIN module m ON m.id=u.module_id "
            "WHERE m.type='Map' AND m.installed_at>0 "
            "ORDER BY m.name LIMIT ?", (limit,)).fetchall()
        ids = [r["module_id"] for r in rows]
    items = [{"module_id": r["module_id"], "module": r["name"],
              "key": r["key"], "title": r["title"], "map": "image"}
             for r in rows[:limit]]
    return {"ok": True, "total": len(rows), "items": items,
            "more": len(rows) > limit}


def sec_topics(key: str, limit: int = 6, **_) -> dict:
    from . import study
    f = _ref_parts(key)
    conn = db.connect()
    if f is None:
        t = study.topic_guide(key, per_section=limit)
        return {"ok": True, "items": _guide_items(t, "topic")[:limit]}
    rows = study.topics_at(conn, f.book, f.chapter or 0, f.verse or 0) or []
    items = list(rows[:limit]) if isinstance(rows, list) else []
    return {"ok": True, "total": len(rows) if isinstance(rows, list) else 0,
            "items": items}


def sec_places(key: str, limit: int = 12, **_) -> dict:
    from . import study
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    rows = study.places_at(f.book, f.chapter or 0, f.verse or 0) or []
    return {"ok": True, "total": len(rows), "items": rows[:limit],
            "more": len(rows) > limit}


def sec_people(key: str, limit: int = 12, **_) -> dict:
    from . import study
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    try:
        bundle = study.verse_bundle("", "")  # shape probe, ignored
    except Exception:  # noqa: BLE001
        bundle = {}
    del bundle
    # Names come from the fact-tag index over the verse text.
    try:
        names = study.fact_tags(f"{f.book} {f.chapter}:{f.verse or 1}",
                                limit=limit) or []
    except Exception:  # noqa: BLE001
        names = []
    void = conn  # keep linters quiet about the unused handle
    del void
    return {"ok": True, "total": len(names), "items": names[:limit],
            "more": len(names) > limit}


def sec_variants(key: str, limit: int = 12, **_) -> dict:
    from . import study
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    rows = conn.execute(
        "SELECT u.module_id, m.name, substr(u.text,1,400) t FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "WHERE u.book=? AND u.chapter=? AND u.verse=? AND m.type='Bible' "
        "ORDER BY m.priority DESC LIMIT ?", (f.book, f.chapter, f.verse or 1,
                                             limit)).fetchall()
    items = [{"module_id": r["module_id"], "module": r["name"],
              "text": r["t"]} for r in rows]
    diff = len({(r["t"] or "").strip() for r in rows}) > 1
    del study
    return {"ok": True, "ref": key, "differ": diff, "items": items,
            "note": "Renderings from installed translations — a comparison, "
                    "not an apparatus."}


def sec_grammars(key: str, limit: int = 8, **_) -> dict:
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    like = f"%{f.book} {f.chapter}:%"
    rows = conn.execute(
        "SELECT u.module_id, m.name, u.title, substr(u.text,1,300) t FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "WHERE m.type IN ('Book','Dictionary','Grammar') AND u.text LIKE ? "
        "LIMIT ?",
        (like, limit)).fetchall()
    items = [{"module_id": r["module_id"], "module": r["name"],
              "title": r["title"], "text": r["t"],
              "subject": _grammar_subject(
                  (r["title"] or "") + " " + (r["t"] or ""))}
             for r in rows]
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(it["subject"], []).append(it)
    return {"ok": True, "total": len(rows), "items": items,
            "groups": [{"subject": s, "items": g} for s, g in
                       sorted(groups.items())],
            "note": "Mentions in installed books, grouped by subject — not a "
                    "grammar database."}


_GRAMMAR_SUBJECTS = [
    ("Nouns and nominals", ("noun", "nominal", "case", "genitive", "dative",
                            "accusative", "declension", "article")),
    ("Verbs", ("verb", "tense", "aorist", "imperfect", "perfect", "pluperfect",
               "mood", "subjunctive", "optative", "imperative", "voice",
               "middle", "passive", "participle", "infinitive", "conjugation")),
    ("Pronouns", ("pronoun", "demonstrative", "relative", "reflexive")),
    ("Prepositions and particles", ("preposition", "particle", "conjunction",
                                    "adverb", "negation", "interjection")),
    ("Adjectives", ("adjective", "comparative", "superlative")),
    ("Sentences and clauses", ("clause", "sentence", "syntax", "conditional",
                               "purpose", "result", "temporal")),
]


def _grammar_subject(blob: str) -> str:
    low = blob.lower()
    for subject, keys in _GRAMMAR_SUBJECTS:
        if any(k in low for k in keys):
            return subject
    return "General"


def sec_extrabiblical(key: str, limit: int = 8, **_) -> dict:
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    like = f"%{f.book} {f.chapter}:%"
    rows = conn.execute(
        "SELECT u.module_id, m.name, u.title, substr(u.text,1,300) t FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "WHERE m.type='Book' AND (m.name LIKE '%Josephus%' "
        "OR m.name LIKE '%Tacitus%' OR m.name LIKE '%Apostolic%' "
        "OR m.name LIKE '%Eusebius%' OR u.text LIKE ?) LIMIT ?",
        (like, limit)).fetchall()
    return {"ok": True, "total": len(rows),
            "items": [{"module_id": r["module_id"], "module": r["name"],
                       "title": r["title"], "text": r["t"]} for r in rows],
            "note": "Only what is installed. Install Josephus or Tacitus from "
                    "the Store for this to fill in."}


def sec_words(key: str, limit: int = 40, **_) -> dict:
    from . import study
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    conn = db.connect()
    bibles = [m.id for m in library.list_all()
              if m.is_bible and (m.has_strongs or m.has_morph)]
    if not bibles:
        return {"ok": True, "items": [],
                "note": "No tagged Bible installed."}
    mid = bibles[0]
    key_osis = f"{f.book}.{f.chapter}.{f.verse or 1}"
    rows = study.strongs_in_unit(conn, mid, key_osis) or []
    return {"ok": True, "module_id": mid, "total": len(rows),
            "items": rows[:limit], "more": len(rows) > limit}


def sec_syntax(key: str, limit: int = 1, **_) -> dict:
    from . import syntax as _sx
    f = _ref_parts(key)
    if f is None:
        return {"ok": False, "error": f"Cannot read {key!r}"}
    mods = [m for m in library.list_all() if m.type == "Syntax"]
    if not mods:
        return {"ok": True, "items": [],
                "note": "No syntax treebank installed. Import a CoNLL-U file "
                        "from 'This computer' with its licence stated."}
    osis = f"{f.book}.{f.chapter}.{f.verse or 1}"
    items = []
    for m in mods[:3]:
        t = _sx.syntax_sentence(m.id, osis)
        if t.get("ok"):
            items.append({"module_id": m.id, "module": m.name,
                          "tree": t["tree"], "text": t["text"]})
        if len(items) >= limit:
            break
    if not items:
        return {"ok": True, "items": items,
                "note": "Installed treebanks have no tree at this verse."}
    return {"ok": True, "items": items}


def sec_sermon(key: str, limit: int = 6, **_) -> dict:
    from . import preach as _pr
    out = _pr.sermon_outlines(key, limit)
    out.setdefault("section", "sermon")
    out.setdefault("title", SECTION_DEFS["sermon"]["title"])
    return out


def _preview(text: str, limit: int = 320) -> str:
    """The first of a note's body, cut at a word and marked as cut.

    Truncation is marked rather than silent, because a preview that stops
    mid-sentence and reads like the whole note is worse than a shorter one
    that admits it.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip() + "…"


def sec_markers(key: str, limit: int = 10, **_) -> dict:
    """The reader's own sermon notes and Bible studies on this passage.

    Tagged sermons and studies surface as previews on the passage. The
    equivalent here is the `note` table's `sermon` and `journal` kinds, which
    already carry the ref in `ref_label` or in the body. A note with no ref
    cannot be said to bear on this passage, so it is not offered -- an empty
    panel here means "you have not tagged this one", not "the feature is
    broken".
    """
    from . import notes as _notes
    out = []
    for kind in ("sermon", "journal"):
        try:
            items = _notes.listing(kind=kind, limit=200) or []
        except Exception:  # noqa: BLE001
            items = []
        ql = (key or "").lower()
        for n in items:
            d = dict(n) if not isinstance(n, dict) else n
            blob = " ".join(str(d.get(k) or "")
                            for k in ("title", "body", "ref_label"))
            if ql and ql in blob.lower():
                out.append({
                    "id": d.get("id", ""),
                    "kind": kind,
                    "title": d.get("title") or "Untitled",
                    "ref_label": d.get("ref_label") or "",
                    "preview": _preview(d.get("body") or ""),
                    "text": _preview(d.get("body") or ""),
                    "updated_at": d.get("updated_at") or 0,
                })
    out.sort(key=lambda r: -r["updated_at"])
    return {"ok": True, "section": "markers",
            "title": SECTION_DEFS["markers"]["title"],
            "items": out[:limit],
            "note": ("Your own notes, read from this workspace — not "
                     "generated." if out else
                     "No sermon or study notes tagged with this passage yet.")}


def sec_counsel(key: str, limit: int = 8, **_) -> dict:
    from . import preach as _pr
    out = _pr.counsel_guide(key, limit)
    if not out.get("ok"):
        # A topic guide key that is not a counsel topic is not an error here;
        # the section simply has nothing for it.
        return {"ok": True, "section": "counsel",
                "title": SECTION_DEFS["counsel"]["title"], "items": [],
                "note": out.get("error", "")}
    out.setdefault("section", "counsel")
    out.setdefault("title", SECTION_DEFS["counsel"]["title"])
    return out


def sec_citedby(key: str, limit: int = 0, collection: str = "",
                  **_) -> dict:
    from . import lookup as _lu
    out = _lu.cited_by(key, None, collection or "")
    out.setdefault("section", "citedby")
    out.setdefault("title", SECTION_DEFS["citedby"]["title"])
    return out


def sec_important(key: str, limit: int = 10, **_) -> dict:
    from . import lookup as _lu
    out = _lu.important_words(key, limit)
    out.setdefault("section", "important")
    out.setdefault("title", SECTION_DEFS["important"]["title"])
    return out


def sec_term(section: str, term: str, limit: int = 8) -> dict:
    """Word/topic sections: dictionaries, articles, occurrences."""
    from . import study
    conn = db.connect()
    if section == "occurrences":
        try:
            rows = study.occurrences_of(conn, term) or []
        except Exception:  # noqa: BLE001
            rows = []
        items = list(rows[:limit]) if isinstance(rows, list) else []
        return {"ok": True, "total": len(rows) if isinstance(rows, list) else 0,
                "items": items}
    try:
        guide = study.topic_guide(term, per_section=limit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if section == "dictionaries":
        return {"ok": True, "items": _guide_items(guide, "dictionary")[:limit]}
    return {"ok": True, "items": _guide_items(guide, "topic")[:limit]}


def _guide_items(guide: dict, kind: str) -> list[dict]:
    """The items of one section of a gathered guide.

    The guides answer with sections, and a section runner that asked the
    guide for a flat "articles" list was asking for a shape it has never
    had -- so it found nothing and the section came back empty.
    """
    for sec in (guide or {}).get("sections") or []:
        if sec.get("kind") == kind:
            return sec.get("items") or []
    return []


SECTION_RUNNERS = {
    "commentaries": sec_commentaries, "crossrefs": sec_crossrefs,
    "parallel": sec_parallel, "literary": sec_literary, "media": sec_media,
    "topics": sec_topics, "places": sec_places, "people": sec_people,
    "variants": sec_variants, "grammars": sec_grammars,
    "extrabiblical": sec_extrabiblical, "words": sec_words,
    "syntax": sec_syntax, "sermon": sec_sermon, "counsel": sec_counsel,
    "citedby": sec_citedby, "important": sec_important, "markers": sec_markers,
}


def run_section(section: str, key: str, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    if section in ("dictionaries", "articles", "occurrences"):
        out = sec_term(section, key, int(opts.get("limit") or 8))
        return {"ok": out.get("ok", True), "section": section,
                "title": SECTION_DEFS[section]["title"], **out}
    fn = SECTION_RUNNERS.get(section)
    if fn is None:
        return {"ok": False, "error": f"Unknown section {section!r}"}
    try:
        out = fn(key, limit=int(opts.get("limit") or 10),
                 sort=opts.get("sort", "priority"),
                 offset=int(opts.get("offset") or 0),
                 collection=opts.get("collection", ""))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "section": section, "error": str(exc)}
    out.setdefault("section", section)
    out.setdefault("title", SECTION_DEFS[section]["title"])
    return out


def run_guide(guide: str, key: str) -> dict:
    """Run every configured section, in the reader's order, for one key.

    Each result carries the section's own id and title so a caller can render
    the whole guide without a second request to look the names up -- and, more
    to the point, so that *this* is the one place a passage view gets its
    section list from.  The passage modal used to ask for `study/passage`
    instead, which returns its own hardcoded five sections, and so ignored the
    configuration entirely: the guide editor wrote a setting that nothing read.
    """
    secs = get_config(guide)
    out = []
    for s in secs:
        r = run_section(s["id"], key, s)
        d = SECTION_DEFS.get(s["id"], {})
        r["id"] = s["id"]
        r["title"] = d.get("title", s["id"])
        out.append(r)
    return {"ok": True, "guide": guide, "key": key, "sections": out}
