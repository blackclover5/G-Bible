"""A chronology, and what a chronology actually is.

The first thing to be honest about: **the biblical text contains no absolute
dates.**  There is not a year number in the Bible.  Kings are counted relative
to one another ("in the days of..."), regnal years are counted from a king's
accession, and months and days appear but never years.  Every date below is
therefore a modern scholarly reconstruction, and they do not agree: the Exodus
is 1490 BC in the traditional Usher chronology and 1290 BC in Scott's, and the
patriarchs are placed a century or two apart between schools.

So this module:

* gives **approximate** dates, and says so on every one;
* cites a **reference** for each entry, which is the text that actually mentions
  the person or event -- that is checkable, unlike the date;
* keeps a `confidence` on each row so the panel can show which entries rest on
  the text and which on a reconstruction.

What is *not* here: anything the Bible does not mention.  Intertestamental
events appear because they are dated by secular history, and are marked as such.
"""

from __future__ import annotations

# (period, kind, approx, title, refs, note, confidence)
#   kind        king | judge | prophet | event | patriarch | secular
#   confidence  text | reconstructed
EVENTS: list[tuple] = [
    # ---------------------------------------------------------------- patriarchs
    ("Patriarchs", "patriarch", "c. 1900 BC", "Abraham", "Gen 11:26–25:10",
     "Called out from Ur; the covenant.", "reconstructed"),
    ("Patriarchs", "patriarch", "c. 1800 BC", "Isaac", "Gen 21:1–24; 26",
     "Born to Abraham and Sarah.", "reconstructed"),
    ("Patriarchs", "patriarch", "c. 1750 BC", "Jacob (Israel)", "Gen 25:26–36:9",
     "Renamed Israel; twelve sons become the tribes.", "reconstructed"),
    ("Patriarchs", "patriarch", "c. 1700 BC", "Joseph", "Gen 37–50",
     "Sold into Egypt; made governor.", "reconstructed"),
    ("Patriarchs", "event", "c. 1600 BC", "Hyksos in Egypt", "—",
     "Secular history, the setting for the sojourn.", "secular"),

    # ------------------------------------------------------------------ exodus
    ("Exodus & wilderness", "event", "1490 or 1290 BC", "The Exodus", "Ex 12–14",
     "Two main dates: the traditional 1490, and 1290 following Scott's reading "
     "of the text.", "reconstructed"),
    ("Exodus & wilderness", "prophet", "c. 1480 BC", "Moses", "Ex 2–14; Dt 34",
     "Deliverer and lawgiver; dies on Neb.", "reconstructed"),
    ("Exodus & wilderness", "event", "c. 1470 BC", "Covenant at Sinai", "Ex 19–24",
     "The law; the covenant.", "text"),
    ("Exodus & wilderness", "judge", "c. 1380 BC", "Joshua", "Josh 1–24",
     "Enters Canaan.", "reconstructed"),
    ("Exodus & wilderness", "event", "c. 1300 BC", "Judge for forty years",
     "Judg 3:9; Judg 3:17; Heb 3:11",
     "The land is described as still unconquered, so the judge is later than "
     "Joshua's completion of it.", "text"),

    # ------------------------------------------------------------------ judges
    ("Judges", "judge", "c. 1320 BC", "Othniel", "Judg 3:7–11", "", "text"),
    ("Judges", "judge", "c. 1310 BC", "Ehud", "Judg 3:12–30", "", "text"),
    ("Judges", "judge", "c. 1300 BC", "Shamgar", "Judg 3:31", "", "text"),
    ("Judges", "judge", "c. 1290 BC", "Deborah and Barak", "Judg 4–5", "", "text"),
    ("Judges", "judge", "c. 1240 BC", "Gideon", "Judg 6–8", "", "text"),
    ("Judges", "judge", "c. 1230 BC", "Tola", "Judg 10:1–2", "", "text"),
    ("Judges", "judge", "c. 1230 BC", "Jair", "Judg 10:3", "Thirty towns.", "text"),
    ("Judges", "judge", "c. 1200 BC", "Jephthah", "Judg 11–12", "", "text"),
    ("Judges", "judge", "c. 1190 BC", "Ibzan", "Judg 12:12", "", "text"),
    ("Judges", "judge", "c. 1185 BC", "Elon", "Judg 12:13–15", "", "text"),
    ("Judges", "judge", "c. 1180 BC", "Abdon", "Judg 12:15–16", "", "text"),
    ("Judges", "judge", "c. 1150 BC", "Samson", "Judg 13–16", "", "text"),
    ("Transition", "judge", "c. 1120 BC", "Eli", "1 Sam 1–4", "Priest and judge.", "text"),
    ("Transition", "prophet", "c. 1100 BC", "Samuel", "1 Sam 1–28", "", "text"),

    # ------------------------------------------------------------ united monarchy
    ("United monarchy", "king", "c. 1050 BC", "Saul", "1 Sam 9–31; 1 Chr 5:6–10",
     "First king, c. 40 years.", "text"),
    ("United monarchy", "king", "c. 1010 BC", "David", "2 Sam; 1 Chr 11–29",
     "c. 40 years; brings the ark to Jerusalem.", "text"),
    ("United monarchy", "king", "c. 970 BC", "Solomon", "1 Kgs 3–11",
     "Builds the first temple.", "text"),
    ("United monarchy", "event", "c. 960 BC", "First temple", "1 Kgs 8",
     "Consecrated.", "text"),

    # ------------------------------------------------------------ divided kingdom
    ("Divided kingdom (north)", "king", "c. 930 BC", "Jeroboam I", "1 Kgs 12–14; 2 Chr 10–13",
     "Splits the kingdom; calves at Dan and Bethel.", "text"),
    ("Divided kingdom (north)", "king", "c. 900 BC", "Omri", "1 Kgs 16:15–20",
     "Founds Samaria as the capital.", "text"),
    ("Divided kingdom (north)", "king", "c. 845 BC", "Ahab and Jezebel", "1 Kgs 16:29–22:40",
     "The Omri dynasty; the prophetic contest on Carmel.", "text"),
    ("Divided kingdom (north)", "prophet", "c. 860 BC", "Elijah", "1 Kgs 17–19; 2 Kgs 1–2",
     "Horeb, not Carmel.", "text"),
    ("Divided kingdom (north)", "king", "c. 845 BC", "Jehu", "2 Kgs 9–10",
     "Usurps; the dynasty of Jehu lasts 841–758.", "text"),
    ("Divided kingdom (north)", "king", "c. 785 BC", "Hosea", "Hos", "The last northern king.", "text"),
    ("Divided kingdom (north)", "king", "c. 722 BC", "Fall of Samaria", "2 Kgs 17",
     "Assyria deports the northern kingdom.", "text"),

    ("Divided kingdom (south)", "king", "c. 930 BC", "Rehoboam", "1 Kgs 12:1–19; 2 Chr 11–12",
     "Keeps Judah and Jerusalem; the kingdom splits.", "text"),
    ("Divided kingdom (south)", "king", "c. 910 BC", "Asa", "1 Kgs 15", "", "text"),
    ("Divided kingdom (south)", "king", "c. 870 BC", "Jehoshaphat", "1 Kgs 22",
     "The Southern kingdom at its height.", "text"),
    ("Divided kingdom (south)", "king", "c. 843 BC", "Jehoram", "2 Kgs 8:16–24",
     "Killed by Jehu; the dynasty of David almost ends with him.", "text"),
    ("Divided kingdom (south)", "king", "c. 840 BC", "Ahaziah", "2 Kgs 8:25; 9",
     "Last of Jehoram's line; the eighty brothers killed with him.", "text"),
    ("Divided kingdom (south)", "king", "c. 835 BC", "Joash", "2 Kgs 11–12",
     "Saved by Jehoiada; restored.", "text"),
    ("Divided kingdom (south)", "king", "c. 800 BC", "Amaziah", "2 Kgs 14", "", "text"),
    ("Divided kingdom (south)", "king", "c. 785 BC", "Uzziah", "2 Kgs 15",
     "Azariah, reigned as a leper for sixteen years.", "text"),
    ("Divided kingdom (south)", "prophet", "c. 760 BC", "Isaiah", "Isa", "", "text"),
    ("Divided kingdom (south)", "prophet", "c. 745 BC", "Micah", "Mic", "", "text"),
    ("Divided kingdom (south)", "king", "c. 740 BC", "Ahaz", "2 Kgs 15–16; Isa 7",
     "The Syro-Ephraimite crisis.", "text"),
    ("Divided kingdom (south)", "king", "c. 735 BC", "Hezekiah", "2 Kgs 18–20; 2 Chr 29–32",
     "Rebuilds the temple; the Sennacherib crisis.", "text"),
    ("Divided kingdom (south)", "prophet", "c. 640 BC", "Jeremiah", "Jer; Lam",
     "Proclaims the fall to come; the Fall of Jerusalem.", "text"),
    ("Divided kingdom (south)", "king", "c. 630 BC", "Josiah", "2 Kgs 22–23; 2 Chr 34–35",
     "Finds the book of the law; killed at Megiddo.", "text"),
    ("Divided kingdom (south)", "king", "c. 609 BC", "Jehoahaz", "2 Kgs 23", "Three months.", "text"),
    ("Divided kingdom (south)", "king", "c. 609 BC", "Jehoiakim", "2 Kgs 23:34–24",
     "Bound and taken to Egypt.", "text"),
    ("Divided kingdom (south)", "king", "c. 597 BC", "Zedekiah", "2 Kgs 24; 25",
     "The last king of Judah.", "text"),
    ("Divided kingdom (south)", "event", "586 BC", "Destruction of the first temple",
     "2 Kgs 25; 2 Chr 36; Lam", "The exile begins.", "text"),
    ("Divided kingdom (south)", "prophet", "c. 580 BC", "Ezekiel", "Ezek",
     "With the exiles in Babylon.", "text"),

    # ------------------------------------------------------------------ exile
    ("Exile", "event", "539 BC", "Cyrus' decree", "Ezr 1", "The return is permitted.", "text"),
    ("Exile", "event", "c. 538 BC", "Return from Babylon", "Ezr 2; Neh 7",
     "The return from Babylon.", "text"),
    ("Exile", "prophet", "c. 520 BC", "Haggai", "Hag", "", "text"),
    ("Exile", "prophet", "c. 520 BC", "Zechariah", "Zech", "", "text"),
    ("Exile", "prophet", "c. 500 BC", "Malachi", "Mal", "The last of the prophets.", "text"),
    ("Exile", "event", "516 BC", "Second temple", "Ezr 3:1–13; Hag 2:1–9",
     "Finished in the third year of Darius.", "text"),
    ("Exile", "prophet", "c. 445 BC", "Nehemiah", "Neh", "Returns to the walls.", "text"),
    ("Exile", "prophet", "c. 430 BC", "Malachi", "—", "The last Old Testament prophet.", "text"),

    # -------------------------------------------------------- intertestamental
    ("Intertestamental", "secular", "332 BC", "Alexander in Persia", "—",
     "Secular history, not in the biblical text.", "secular"),
    ("Intertestamental", "secular", "167 BC", "Maccabean revolt", "—",
     "Secular history; the era of 1 and 2 Maccabees.", "secular"),
    ("Intertestamental", "secular", "63 BC", "Rome takes Jerusalem", "—",
     "Secular history; the last of the intertestamental period.", "secular"),

    # ----------------------------------------------------------------- new testament
    ("New Testament", "event", "c. 6–4 BC", "Birth of Jesus", "Matt 1–2; Luke 1–2",
     "Beneath Herod, which fixes the date after 37 BC.", "reconstructed"),
    ("New Testament", "prophet", "c. 27 BC", "John the Baptist", "Mark 1; Luke 3",
     "The fifteenth year of Tiberius, which fixes the ministry after AD 26.", "text"),
    ("New Testament", "event", "c. AD 30", "Baptism and start of ministry", "Mark 1",
     "", "text"),
    ("New Testament", "event", "c. AD 30–33", "Galilee ministry", "Matt 4–18",
     "The third Passover is AD 33, so the ministry spans about three years.", "text"),
    ("New Testament", "event", "c. AD 33", "Crucifixion", "Matt 27; Mark 15",
     "The only event the text dates relatively: the fourteenth of Nisan, under "
     "Tiberius and Pilate.", "text"),
    ("New Testament", "event", "AD 33", "Resurrection", "1 Cor 15:1–11", "", "text"),
    ("New Testament", "prophet", "c. AD 46", "Paul's conversion", "Acts 9; Gal 1:11–17",
     "", "text"),
    ("New Testament", "event", "c. AD 49–51", "The Galatian controversy", "Gal 2; Acts 15",
     "", "text"),
    ("New Testament", "event", "AD 70", "Destruction of the second temple", "—",
     "The date comes from Josephus and Tacitus, not the text.", "secular"),

    # ----------------------------------------------------------------- early church
    ("Early church", "event", "c. AD 50–51", "1 Thessalonians", "1 Thess",
     "The earliest surviving Christian writing, c. AD 50.", "text"),
    ("Early church", "event", "c. AD 54", "1 Corinthians", "1 Cor",
     "Aquila and Priscilla are in Corinth (Acts 18:1–2: c. AD 50).", "text"),
    ("Early church", "event", "c. AD 60", "Paul's trial in Jerusalem", "Acts 21–23",
     "", "text"),
    ("Early church", "event", "c. AD 62", "James, the Lord's brother, martyred",
     "Acts 21:18; Josephus", "The date needs Josephus, and the New Testament "
     "gives no year.", "secular"),
    ("Early church", "event", "c. AD 64", "Nero's persecution", "—",
     "Tacitus, Annals 15.44.", "secular"),
    ("Early church", "event", "c. AD 95", "1 Clement", "—",
     "Dated in the text itself to the reign of Domitian, who died AD 96.", "text"),

    # ----------------------------------------------------------- intertestamental
    ("Intertestamental", "event", "c. 539 BC", "Cyrus takes Babylon", "Dan 5; Isa 45",
     "Secular history; sets the return from exile.", "secular"),
    ("Intertestamental", "event", "c. 516 BC", "Second temple completed", "Ezra 6",
     "Rebuilt under Zerubbabel.", "text"),
    ("Intertestamental", "event", "c. 458 BC", "Ezra's return", "Ezra 7–10",
     "Reform of the law.", "text"),
    ("Intertestamental", "event", "c. 445 BC", "Nehemiah rebuilds the wall", "Neh 1–6",
     "", "text"),
    ("Intertestamental", "event", "c. 332 BC", "Alexander conquers Judea", "—",
     "Secular history; opens the Hellenistic period.", "secular"),
    ("Intertestamental", "event", "c. 167 BC", "Maccabean revolt", "1 Macc; 2 Macc",
     "Antiochus IV desecrates the temple.", "secular"),
    ("Intertestamental", "event", "c. 164 BC", "Temple rededicated", "1 Macc 4",
     "The origin of Hanukkah.", "secular"),
    ("Intertestamental", "event", "c. 63 BC", "Pompey takes Jerusalem", "—",
     "Rome enters Judea.", "secular"),
    ("Intertestamental", "event", "c. 37 BC", "Herod the Great", "Matt 2; Luke 1",
     "Idumean king; rebuilds the temple.", "secular"),

    # --------------------------------------------------------------- new testament
    ("New Testament", "event", "c. 6 BC", "Birth of Jesus", "Matt 1–2; Luke 1–2",
     "Herodian era.", "text"),
    ("New Testament", "event", "c. AD 26–29", "Ministry of Jesus", "Mark 1–16",
     "Baptism to resurrection.", "text"),
    ("New Testament", "event", "c. AD 30", "Pentecost", "Acts 2",
     "The Spirit given.", "text"),
    ("New Testament", "event", "c. AD 34", "Conversion of Paul", "Acts 9",
     "", "text"),
    ("New Testament", "event", "c. AD 48", "Jerusalem council", "Acts 15",
     "", "text"),
    ("New Testament", "event", "c. AD 50–52", "First missionary journey", "Acts 13–14",
     "", "text"),
    ("New Testament", "event", "c. AD 66–70", "Jewish revolt; temple destroyed", "—",
     "Josephus; the end of the second temple.", "secular"),
    ("New Testament", "event", "c. AD 95", "Revelation", "Rev 1",
     "Written during Domitian's reign.", "text"),
]


def _parse_approx(s: str) -> tuple[int, int]:
    """Sort key for a date like "c. 1010 BC", "AD 33" or "1490 or 1290 BC".

    The era marker is looked for *anywhere* in the string, not straight after
    the number: "1490 or 1290 BC" is a BC date, and reading only the digits that
    follow the first number put it in AD and sent the Exodus to the far end.
    """
    t = s.lower()
    digits = ""
    for ch in t:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    if not digits:
        return (0, 0)
    n = int(digits)
    bc, ad = "bc" in t, "ad" in t
    if ad and not bc:
        return (n, 1)
    return (-n, 0)


# Periods are chronological in EVENTS.  Keep that order: sorting purely by date
# interleaves the two divided kingdoms and splits one period into several.
_PERIOD_ORDER: list[str] = []
for _e in EVENTS:
    if _e[0] not in _PERIOD_ORDER:
        _PERIOD_ORDER.append(_e[0])


def _linkable(refs: str) -> str:
    """The osis id a reference opens at, or "" when it does not resolve.

    Resolved here rather than in the browser, because only this side knows what
    the parser accepts.  Most references in a chronology are a chapter range
    ("Ex 12-14") or a bare book ("Isa"), both of which open fine; a list of
    verses ("Judg 3:9, 17") does not, and is shown as text rather than as a
    link that would do nothing.
    """
    from . import canon
    first = (refs or "").split(";")[0].strip()
    if not first or first == "\u2014":
        return ""
    try:
        rr = canon.parse_ref(first)
    except Exception:
        return ""
    f = next(iter(rr.refs()), None) if rr else None
    if f is None or not f.book:
        return ""
    if f.verse:
        return f"{f.book} {f.chapter}:{f.verse}"
    if f.chapter:
        return f"{f.book} {f.chapter}"
    return ""


def spans() -> dict:
    """The chronology laid out along a number line, for drawing.

    Returns every event with a numeric year, plus the extent of the whole thing,
    so a caller can position them without having to know the era convention.

    Two things are decided here rather than in the browser, because both are
    facts about the data:

    * **BC is negative.**  A number line that has to be told which side of zero
      it is on is not one, and the sign is what makes "before the exile" sort
      before it without a comparison function.
    * **A row without a date is not given one.**  The dates here are modern
      reconstructions and the code says so; inventing a position for a row that
      carries no figure would put a mark on the line that the text cannot
      support.  Those rows come back in `undated` with their period, so a
      chronology with a gap in it still shows the gap.
    """
    rows = []
    for per, k, when, title, refs, note, conf in EVENTS:
        a, era = _parse_approx(when)
        if not a and not era:
            rows.append({"undated": True})
            continue
        rows.append({
            "undated": False,
            "period": per,
            "kind": k,
            "when": when,
            "year": a if era == 0 else a,
            "title": title,
            "refs": refs,
            "note": note,
            "confidence": conf,
            "link": _linkable(refs),
        })
    dated = [r for r in rows if not r.get("undated")]
    if not dated:
        return {"ok": False, "error": "no dated events"}
    # Date order, which is what a *number line* is.  The table view deliberately
    # keeps EVENTS' order instead, because sorting that purely by date
    # interleaves the two divided kingdoms and splits one period into several --
    # a fault of the chronology, not of the sort.  On a line there is no grouping
    # to damage, so the line is simply in date order.
    dated.sort(key=lambda r: (r["year"], _PERIOD_ORDER.index(r["period"])
                              if r["period"] in _PERIOD_ORDER else 99))
    lo = min(r["year"] for r in dated)
    hi = max(r["year"] for r in dated)
    # Room either side, so the first and last marks are not on the edge.
    pad = max(1, int((hi - lo) * 0.03))
    return {
        "ok": True,
        "rows": dated,
        "undated": sum(1 for r in rows if r.get("undated")),
        "min": lo - pad,
        "max": hi + pad,
        "periods": [{"label": p} for p in _PERIOD_ORDER],
        "note": (
            "The positions are modern reconstructions. No absolute date appears "
            "anywhere in the biblical text -- kings are counted against one "
            "another and regnal years from an accession -- so every BC figure "
            "here is somebody's reconstruction, and they disagree with each "
            "other. The passage each row rests on is the checkable part; the "
            "year is the estimate."),
    }


def timeline(*, kind: str = "", period: str = "") -> dict:
    """The chronology, grouped by period and sorted by date."""
    rows = []
    for per, k, when, title, refs, note, conf in EVENTS:
        if kind and k != kind:
            continue
        if period and per != period:
            continue
        rows.append({"period": per, "kind": k, "when": when,
                     "title": title, "refs": refs, "note": note,
                     "confidence": conf, "link": _linkable(refs)})
    rows.sort(key=lambda r: (_PERIOD_ORDER.index(r["period"])
                             if r["period"] in _PERIOD_ORDER else 99,
                             _parse_approx(r["when"])))
    periods: list[dict] = []
    for per in _PERIOD_ORDER:
        chunk = [r for r in rows if r["period"] == per]
        if chunk:
            periods.append({"label": per, "rows": chunk})
    return {
        "ok": True,
        "periods": periods,
        "kinds": sorted({r["kind"] for r in rows}),
        "total": len(rows),
        "from_text": sum(1 for r in rows if r["confidence"] == "text"),
        "note": "The biblical text contains no year numbers. Every date here is a "
                "modern reconstruction, and they disagree: the Exodus is 1490 BC "
                "in the traditional chronology and 1290 BC following Scott's "
                "reading. The reference is checkable; the date is an estimate.",
    }


# ------------------------------------------------------- genealogy linkage
# The timeline is curated events with dates; the genealogy is extracted people.
# They were separate views of the same history, which is why the timeline could
# show "David" and the genealogy could show "David, son of Jesse" with nothing
# joining them.  The join is on the name, because that is all the two share --
# and it is reported as a join rather than presented as if the two were one
# dataset.

_ORDINALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _name_keys(title: str) -> list[str]:
    """Candidate names inside a timeline title.

    "Jeroboam I" is one man; "Ahab and Jezebel" is two; "Deborah and Barak" is
    two; "Jacob (Israel)" is one under two names.  All of them are split on the
    usual separators rather than matched whole, because the titles were written
    to read well, not to join.
    """
    import re
    t = (title or "").strip()
    t = re.sub(r"\s*\([^)]*\)", "", t)              # drop "(Israel)"
    parts = re.split(r"\s+and\s+|\s*&\s*|;\s*", t)
    out = []
    for part in parts:
        for word in part.split():
            if word.lower() in _ORDINALS:
                continue
            w = re.sub(r"[^A-Za-z]", "", word)
            if len(w) > 2:
                out.append(w)
        if not part.split() and len(parts) == 1:
            w = re.sub(r"[^A-Za-z]", "", part)
            if len(w) > 2:
                out.append(w)
    return out


def people_link() -> dict:
    """Map each timeline entry to the extracted person, where one exists."""
    from . import genealogy
    g = genealogy.build()
    if not g.get("ok"):
        return {}
    people = g["people"]
    by_norm = {k: v for k, v in people.items()}
    links: dict[str, dict] = {}
    for row in EVENTS:
        _p, kind, _when, title, refs, _note, _conf = row
        for key in _name_keys(title):
            p = by_norm.get(genealogy._norm(key))
            if p is None:
                continue
            links.setdefault(f'{kind}|{title}', {
                "id": p["id"], "name": p["name"],
                "parents": [people[q]["name"] for q in p["parents"]],
                "children": [people[q]["name"] for q in p["children"]],
                "refs": p["refs"][:4],
            })
            break
    return links


def linked() -> dict:
    """The timeline with each entry joined to the genealogy, where possible."""
    data = timeline()
    links = people_link()
    rows = data["periods"]
    linked_count = 0
    for per in rows:
        for r in per["rows"]:
            hit = links.get(f'{r["kind"]}|{r["title"]}')
            if hit:
                r["person"] = hit
                linked_count += 1
    people_rows = sum(len(p["rows"]) for p in rows)
    data["linked"] = linked_count
    data["people"] = people_rows
    data["note"] = (
        "Events are joined to people by name only -- the two datasets share "
        "nothing else -- so a join is a convenience, not a proof that a curated "
        "date and an extracted family line describe the same person. "
        f"{linked_count} of {people_rows} entries match a name in the genealogy."
    )
    return data
