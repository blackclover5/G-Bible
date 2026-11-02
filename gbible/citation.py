"""Citations, bibliographies and everything you can hand to someone else.

The problem this module is built around: **there is not enough metadata to cite
from.**  Of the installed library, an author is known for a small minority of
resources, a year for fewer, and a publisher for none — CrossWire strips
`Author`, `Publisher` and `Date` from its `.conf` files, so the fields are not in
the files we download, only in someone's head or on a title page.

That gives a citation engine exactly one honest choice: either print what it
knows and say plainly what it does not, or invent the rest.  It does the first.
Every citation built here carries a `missing` list naming the fields that were
not available, and nothing is ever filled in from a guess.  A citation that
reads

    Clarke, Adam. *Commentary*. CrossWire.

is not wrong, and it is obviously unfinished, and it says which of the two it
is.  What it will never be is

    Clarke, Adam. *Commentary on the Whole Bible*. London: B. Fellowes, 1832.

with the publisher and the year made up — which is what a naive engine produces,
and what makes a bibliography a thing readers have to check.

Two things follow from that, and they are the actual design:

**Completeness is reported, not hidden.**  `cite()` returns the string, the style,
and the list of fields it could not fill.  The interface shows that list.  A
paper with three citations flagged is saved work; a paper with three wrong ones
is a retraction.

**Missing fields are fillable.**  `set_field()` stores what the user knows, per
module and per field, and every later citation for that module uses it.  Filling
in a publisher cannot overwrite an author, and an unfilled field stays
*unfilled* rather than becoming an empty string — "unknown" and "known to be
blank" are different claims and only the first one is ever true here.

Page numbers are not produced.  Almost none of these resources carry page data,
and a locator is the part of a citation a reader actually checks; inventing one
is the single worst thing a tool like this could do.  Where a locator is
genuinely known — a passage reference, a Strong's number, a verse — it is used.

Bible passages get their own treatment, because for Bible text the citation *is*
derivable: reference, translation, and (when you ask for full form) the work the
translation was made from.  That case is complete, and completeness is real here
rather than a caveat.
"""

from __future__ import annotations

import json
import re
import time

from . import db, taxonomy

# --------------------------------------------------------------- styles ---

STYLES = {
    "sbl": "SBL (Society of Biblical Literature)",
    "mla": "MLA 9",
    "apa": "APA 7",
    "chicago": "Chicago 17 (notes–bibliography)",
    "turabian": "Turabian 9",
}

#: Fields a work needs before a citation of it can be called complete.  A title
#: and an author are the floor; the rest is what distinguishes a citation from a
#: label.
CORE_FIELDS = ("author", "year")

#: Everything that may be supplied by hand, and what the interface offers.
EDITABLE_FIELDS = (
    ("author", "Author / editor"),
    ("year", "Year"),
    ("publisher", "Publisher"),
    ("place", "Place of publication"),
    ("edition", "Edition"),
    ("series", "Series"),
    ("container", "Collection or part-of title"),
    ("isbn", "ISBN / identifier"),
    ("url", "Stable URL"),
)

#: What each kind of work legitimately needs.  A Bible needs a translator and a
#: year; an atlas needs a publisher and a year.  Demanding a publisher from a
#: dictionary is noise, and calling a citation complete on fields the genre does
#: not use is a way of looking thorough while checking nothing.
REQUIRED_FOR = {
    "Bible": ("author", "year"),
    "Commentary": ("author", "year"),
    "Lexicon": ("author", "year"),
    "Dictionary": ("author", "year"),
    "Book": ("author", "year"),
    "Article": ("author", "year"),
    "Devotional": ("author", "year"),
    "Atlas": ("publisher", "year"),
    "Map": ("publisher", "year"),
}

#: Bible translations that are old enough, and free enough, that citing the
#: source work is more use than citing the digital edition.  Kept small and
#: explicit: this is a list of facts about specific editions, and inferring
#: entries would be exactly the invention this module exists to avoid.
#: The work each edition is made from, and when that work appeared.  The values
#: are the title of the edition *without* a leading "The Holy Bible, " because
#: the citation builds that itself; keeping it in the data doubled the phrase.
SOURCE_WORKS = {
    "King James Version": ("Authorized (King James) Version", "1611"),
    "American Standard Version": ("American Standard Version", "1901"),
    "Douay-Rheims Bible": ("Douay-Rheims Bible", "1752"),
    "World English Bible": ("World English Bible", "2020"),
    "Berean Standard Bible": ("Berean Standard Bible", "2016"),
    "Brenton Septuagint Translation": ("Brenton, Lancelot C. L. The Septuagint "
                                       "of the Old Testament", "1851"),
    "Updated Brenton English Septuagint": ("Brenton, Lancelot C. L. The "
                                           "Septuagint of the Old Testament",
                                           "1851"),
}


# --------------------------------------------------------------- helpers ---

def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


#: Author values that are really notes about where a text came from.  Three of
#: the midvash modules carry "Various; see SOURCES.md in the upstream
#: repository" in their author field.  Printed as an author that reads
#: "Various; see SOURCES.md in the upstream repository. *Textus Receptus*",
#: which is not an attribution of anything.  It is dropped and the author
#: reported as unknown, which is what it is.
_NOT_AN_AUTHOR = re.compile(
    r"\bsee\s+(sources?|readme)|\bupstream\b|\brepository\b|^various$|"
    r"\bcopyright holders?\b|\bsee also\b", re.I)


def _parse_author(raw: str) -> tuple[str, str]:
    """Return (surname, given) from a messy author string.

    Catalogue author fields are inconsistent: some are "Easton, Matthew George",
    some "Matthew George Easton", some "Hertz, Joseph H. (1872-1946)", and some
    are cut off mid-word by whatever length the catalogue kept.  A name cut in
    half is reported as cut rather than completed -- "Strong, James (1822" is
    obviously broken, and quietly closing the bracket would hide that.
    """
    s = _clean(raw)
    if not s or _NOT_AN_AUTHOR.search(s):
        return "", ""
    # Life dates: keep them out of the name, they are not part of it.
    s = re.sub(r"\s*\(?\b\d{3,4}\s*[-–]\s*\d{3,4}\)?\s*$", "", s).strip()
    if s.count("(") > s.count(")"):
        # Unbalanced: the source truncated it.  Say so rather than repair it.
        s = s.rstrip("(").strip() + " [name truncated in catalogue]"
    if "," in s:
        surname, _, given = s.partition(",")
        return _clean(surname), _clean(given)
    parts = s.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def _initials(given: str) -> str:
    """Initials for APA, which wants "M. G. Easton" not "Matthew George Easton"."""
    out = []
    for part in given.replace(".", " ").split():
        out.append(part[0].upper() + ".")
    return " ".join(out)


def _year_int(raw) -> str:
    """A four-digit year, or nothing.

    Dates arrive as '2018-05-27', '1897', 'c1604', ''.  A range like '1832-1834'
    is kept whole in the bibliography but reduced to the opening year where a
    style wants a single year, which is what a reader expects to see first.
    """
    s = _clean(raw)
    if not s:
        return ""
    m = re.search(r"(1[0-9]{3}|20[0-9]{2})", s)
    return m.group(1) if m else ""


# ------------------------------------------------------------- metadata ---

def _catalog_meta(conn, module_id: str) -> dict:
    row = conn.execute(
        "SELECT id,name,type,lang,lang_name,version,abbrev,author,year,rights,"
        "license,source_name,source_url,description,about,subject "
        "FROM module WHERE id=?", (module_id,)).fetchone()
    if row is None:
        return {}
    meta = {k: ("" if row[k] is None else str(row[k]))
            for k in row.keys() if k != "id"}
    meta["id"] = module_id
    # A year printed in the title is a fact about the title, not a guess, so it
    # is legitimately recoverable: "Easton's Bible Dictionary (1897)" is from
    # 1897.  It is kept separate from the catalogue's own year field so that a
    # title-derived year can be told apart from a recorded one.
    m = re.search(r"\((1[0-9]{3}|20[0-2][0-9])\)\s*$", meta.get("name", ""))
    if m and not _year_int(meta.get("year")):
        meta["year"] = m.group(1)
        meta["year_source"] = "from the title"
    return meta


def metadata(module_id: str) -> dict:
    """Everything known about a work, with the user's own values taking priority."""
    conn = db.connect()
    meta = _catalog_meta(conn, module_id)
    if not meta:
        return {}
    supplied = {}
    for r in conn.execute(
            "SELECT field,value FROM citation_meta WHERE module_id=?",
            (module_id,)):
        if _clean(r["value"]):
            supplied[r["field"]] = _clean(r["value"])
    meta["supplied"] = supplied
    # Supplied values win; an empty supplied value is ignored so that clearing
    # a field falls back to what the catalogue knows instead of to nothing.
    for k, v in supplied.items():
        meta[k] = v
    meta["author_raw"] = meta.get("author", "")
    meta["surname"], meta["given"] = _parse_author(meta.get("author", ""))
    meta["year_clean"] = _year_int(meta.get("year"))
    meta["required"] = list(REQUIRED_FOR.get(meta.get("type") or "", CORE_FIELDS))
    meta["missing"] = [f for f in meta["required"] if not _clean(meta.get(f))]
    # Publisher is only required for some kinds, but its absence is always worth
    # knowing about when a style prints one.
    if meta.get("type") in ("Book", "Article", "Atlas", "Map") and not _clean(
            meta.get("publisher")):
        meta.setdefault("missing", []).append("publisher")
    meta["missing"] = sorted(set(meta["missing"]))
    meta["complete"] = not meta["missing"]
    return meta


def set_field(module_id: str, field: str, value: str) -> dict:
    """Record what the user knows about a field.  Empty clears it."""
    allowed = {f for f, _ in EDITABLE_FIELDS}
    if field not in allowed:
        return {"ok": False, "error": f"'{field}' is not a citation field"}
    if not metadata(module_id):
        return {"ok": False, "error": "no such module"}
    conn = db.connect()
    v = _clean(value)
    if v:
        conn.execute(
            "INSERT INTO citation_meta(module_id,field,value,updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(module_id,field) DO UPDATE SET "
            "value=excluded.value, updated_at=excluded.updated_at",
            (module_id, field, v, time.time()))
    else:
        conn.execute(
            "DELETE FROM citation_meta WHERE module_id=? AND field=?",
            (module_id, field))
    conn.commit()
    return {"ok": True, "module_id": module_id, "field": field, "value": v}


def completeness(module_ids: list[str]) -> dict:
    """How citable the library is, honestly counted."""
    metas = [m for m in (metadata(i) for i in module_ids) if m]
    complete = [m for m in metas if m["complete"]]
    missing_counts: dict[str, int] = {}
    for m in metas:
        for f in m["missing"]:
            missing_counts[f] = missing_counts.get(f, 0) + 1
    return {"total": len(metas), "complete": len(complete),
            "incomplete": len(metas) - len(complete),
            "missing_counts": dict(sorted(missing_counts.items(),
                                           key=lambda x: -x[1]))}


# --------------------------------------------------------------- citations -

def cite(module_id: str, style: str = "sbl", *, full: bool = False) -> dict:
    """A formatted citation, plus what it could not say.

    `full` is the "full form" every style guide uses for the first mention of a
    work; later mentions take a short form.  Without it you get the short form,
    which for a work you have already cited is usually what you want.
    """
    meta = metadata(module_id)
    if not meta:
        return {"ok": False, "error": "no such module"}
    if style not in STYLES:
        return {"ok": False, "error": f"unknown style '{style}'",
                "styles": sorted(STYLES)}
    fn = _FORMATTERS[style]
    text, note = fn(meta, bool(full))
    return {"ok": True, "style": style, "module_id": module_id,
            "citation": text, "note": note, "missing": meta["missing"],
            "complete": meta["complete"], "meta": meta}


def _attribution(meta: dict) -> str:
    """The licence line.  Always printed for CC-BY, because CC BY 4.0 requires
    attribution and an export that dropped it would be a licence breach."""
    lic = _clean(meta.get("license"))
    rights = _clean(meta.get("rights"))
    if lic and lic.lower() in ("public domain", "publicdomain", "pd"):
        return "Public domain."
    if lic:
        base = f"Licensed {lic}."
        return f"{base} {rights}" if rights and rights.lower() not in lic.lower() else base
    if rights:
        return rights + "."
    return ""


def _author_forms(meta: dict) -> dict:
    """The same name in the shapes the styles need."""
    surname, given = meta.get("surname", ""), meta.get("given", "")
    if surname:
        inverted = f"{surname}, {given}".strip().rstrip(",")
        natural = f"{given} {surname}".strip()
        initials = f"{_initials(given)} {surname}".strip()
        orgname = ""
    else:
        # No author is recorded, and none is invented.  The publishing
        # repository is *not* a substitute: several of these catalogues describe
        # themselves as "repository, Various; see SOURCES.md in the upstream",
        # which as an author produces "repository, Various; see SOURCES.md in
        # the upstream. Aleppo Codex."  That is worse than printing no author at
        # all, because it looks like a real attribution.  The title moves to the
        # front of the entry instead, and the missing author is reported.
        orgname = ""
        inverted = natural = initials = ""
    # APA puts initials after the surname -- "Clarke, A." -- which is a different
    # order from both the natural and the initials forms, so it is built here
    # rather than assembled by a caller that has to know the difference.
    apa_name = f"{surname}, {_initials(given)}" if surname else orgname
    # "org" is the flag the formatters test; "orgname" is the name itself.
    # Having one key do both jobs meant a sort key reading a bool as a string.
    return {"inverted": inverted, "natural": natural, "initials": initials,
            "apa": apa_name, "surname": surname, "given": given,
            "orgname": orgname, "org": not bool(surname)}


def _sentences(*parts: str) -> str:
    """Join citation fragments into a citation.

    Assembling fragments with trailing spaces and then appending another one
    produces "*Title*.Public domain." -- a space short, because the fragment
    before it happened to end in a period.  Building the list first and joining
    once removes the whole class of bug instead of patching each spot.
    """
    out = []
    for x in parts:
        x = _clean(x)
        if x:
            out.append(x if x.endswith((".", "?", "!")) else x + ".")
    return " ".join(out)


def _end(parts: list[str]) -> str:
    """Join parts and end with exactly one period.

    Assembling "n.d." and then adding a full stop of your own is how a citation
    ends up printed as "n.d..".
    """
    out = ""
    for x in parts:
        x = x.strip()
        if not x:
            continue
        out = (out + " " + x) if out else x
    if not out:
        return ""
    return out if out.endswith(".") else out + "."


def _year_for(meta: dict) -> str:
    """The year to print, unless the title already carries it.

    "American Standard Version (1901)" followed by a bare "1901" is the
    bibliography announcing the same fact twice, which is what happens whenever
    the year is recovered from the title and then also printed as the imprint.
    """
    y = meta.get("year_clean") or ""
    title = _clean(meta.get("name"))
    if y and re.search(rf"\b{re.escape(y)}\b", title):
        return ""
    return y or "n.d."


def _incomplete_note(meta: dict) -> str:
    return "" if meta["complete"] else (
        "missing: " + ", ".join(meta["missing"])
        + " — fill these in below for a citation you can hand to someone")


def _short(title: str, a: dict) -> str:
    """Short form: surname, then the title properly so called.

    Two things are trimmed, and both are about not saying the author's name
    twice in one line.  A subtitle after a colon is dropped, and a title that
    opens with the author's own name -- "Adam Clarke's Commentary ...", cited as
    "Clarke, Adam Clarke's Commentary ..." -- has that opening name removed,
    because a short form reading "Clarke, Clarke's" is noise.
    """
    t = re.split(r"[:/]", title)[0].strip() or title
    surname = a.get("surname") or ""
    if surname:
        stem = re.escape(surname)
        # "Clarke's Commentary" -> "Commentary"
        t = re.sub(rf"^(?:the\s+)?{stem}['’]s\s+", "", t, flags=re.I)
        given = a.get("given") or ""
        if given:
            first = re.escape(given.split()[0])
            t = re.sub(rf"^(?:{first}\s+)?{stem}['’]s\s+", "", t, flags=re.I)
    t = t.strip() or title
    return f"{a['surname']}, {t}" if surname else t


def _fmt_sbl(meta: dict, full: bool) -> tuple[str, str]:
    """SBL: Surname, Given. Title. Place: Publisher, Year."""
    a = _author_forms(meta)
    title = _clean(meta.get("name"))
    year = _year_for(meta)
    place, pub = _clean(meta.get("place")), _clean(meta.get("publisher"))
    if not full:
        return (_short(title, a),
                "short form — the first mention of a work takes the full entry")
    # With no author the title moves to the front and is not repeated.  Printing
    # an organisation where the author belongs *and* then the title is how you
    # end up citing the distributor instead of the work.
    head = f"{a['inverted']}. " if not a["org"] else ""
    head = f"*{title}*" if a["org"] else f"{a['inverted']}. *{title}*"
    imprint = ", ".join(x for x in (
        f"{place}: {pub}" if place and pub else (pub or place), year) if x)
    return _sentences(head, imprint, _clean(meta.get("series")),
                       _attribution(meta)), _incomplete_note(meta)


def _fmt_mla(meta: dict, full: bool) -> tuple[str, str]:
    """MLA 9: Surname, Given. Title. Publisher, Year, URL."""
    a = _author_forms(meta)
    title = _clean(meta.get("name"))
    if not full:
        return (_short(title, a) + ".",
                "short form — the first mention of a work takes the full entry")
    head = f"*{title}*" if a["org"] else f"{a['inverted']}. *{title}*"
    tail = ", ".join(x for x in (_clean(meta.get("publisher")), _year_for(meta),
                                 _clean(meta.get("url"))) if x)
    return _sentences(head, tail, _attribution(meta)), _incomplete_note(meta)


def _fmt_apa(meta: dict, full: bool) -> tuple[str, str]:
    """APA 7: Surname, G. G. (Year). Title. Publisher."""
    a = _author_forms(meta)
    title = _clean(meta.get("name"))
    if not full:
        return (_short(title, a),
                "short form — the first mention of a work takes the full entry")
    # APA dates every entry, author or not; an undated organisational work still
    # gets (n.d.), because the date is the slot the reader looks at first.
    date = _year_for(meta)
    if a["org"]:
        # _year_for returns nothing when the title already carries the year, and
        # printing the parentheses regardless left "*Title*. ()" -- brackets
        # around a date that is not there.
        head = f"*{title}*. ({date})" if date else f"*{title}*"
    else:
        head = f"{a['apa']} ({date or 'n.d.'}). *{title}*"
    tail = ", ".join(x for x in (_clean(meta.get("publisher")),
                                 _clean(meta.get("url"))) if x)
    return _sentences(head, tail, _attribution(meta)), _incomplete_note(meta)


def _fmt_chicago(meta: dict, full: bool) -> tuple[str, str]:
    """Chicago 17, bibliography entry: Surname, Given. Title. Place: Publisher, Year."""
    a = _author_forms(meta)
    title = _clean(meta.get("name"))
    if not full:
        return (_short(title, a),
                "short form — the first mention of a work takes the full entry")
    head = f"*{title}*" if a["org"] else f"{a['inverted']}. *{title}*"
    place, pub = _clean(meta.get("place")), _clean(meta.get("publisher"))
    imprint = ", ".join(x for x in (
        f"{place}: {pub}" if place and pub else (pub or place),
        _year_for(meta)) if x)
    return _sentences(head, imprint, _attribution(meta)), _incomplete_note(meta)


def _fmt_turabian(meta: dict, full: bool) -> tuple[str, str]:
    """Turabian 9.  Same shape as Chicago's bibliography entry; the difference
    that matters here is that a work with no place of publication is cited
    without one rather than with a guess."""
    return _fmt_chicago(meta, full)


_FORMATTERS = {"sbl": _fmt_sbl, "mla": _fmt_mla, "apa": _fmt_apa,
                "chicago": _fmt_chicago, "turabian": _fmt_turabian}


# ------------------------------------------------------- passage citation --

def passage_citation(ref: str, module_id: str, *, style: str = "sbl",
                     full: bool = False) -> dict:
    """Cite a passage of a Bible.

    This case *is* complete: the reference and the translation are known facts,
    not metadata that has to be supplied.  It is the one place in the app where a
    citation can be generated without asking the user for anything, and it is
    the case people cite most often.
    """
    meta = metadata(module_id)
    if not meta:
        return {"ok": False, "error": "no such module"}
    ref = _clean(ref)
    name = _clean(meta.get("name"))
    # For a Bible the *name* is the translation ("American Standard Version
    # (1901)").  The version column is often the software build -- the ASV
    # module reports "2.0" -- so it is not a translation name and citing it
    # produces "2.0. John 3:16." for a resource with no second edition.
    is_bible = (meta.get("type") or "") == "Bible"
    version = name if is_bible else (_clean(meta.get("version")) or name)
    out = {"ok": True, "ref": ref, "module_id": module_id,
           "version": version, "missing": [], "complete": True}
    abbrev = _clean(meta.get("abbrev"))
    label = f" ({abbrev})" if abbrev else f" ({version})"
    # Module names often carry the year -- "American Standard Version (1901)" --
    # so the lookup has to be on the name without it, or the one translation
    # whose source work we actually know about never matches.
    bare = re.sub(r"\s*\((1[0-9]{3}|20[0-2][0-9])\)\s*$", "", version).strip()
    src = SOURCE_WORKS.get(version) or SOURCE_WORKS.get(bare)
    if style == "sbl":
        # Scripture is cited by reference and version.  There is no page to
        # cite: these are reflowed digital texts, so the reference *is* the
        # locator, and giving a page number would be inventing one.
        if full and src:
            work, year = src
            out["citation"] = f"The Holy Bible, {work} ({year}). {ref}."
            note = "Full form, naming the source work."
        else:
            out["citation"] = f"{ref}{label}"
            note = ("Short form. Bible text is cited by version and "
                    "reference; there are no page numbers to give.")
            if full:
                # No source work on file for this version.  Say that rather
                # than quietly handing back the short form as though the full
                # form had been produced.
                out["citation"] = f"{version}. {ref}."
                note = ("Full form is not available: the source work for this "
                        f"version is not recorded. {version}, {ref}. Add the "
                        "publisher and year in the details below and this "
                        "becomes a citation you can hand to someone.")
    elif style == "apa":
        out["citation"] = f"{version} ({ref})" if not full else f"{version}. {ref}."
        note = ""
    elif style == "mla":
        out["citation"] = f"{ref}{label}." if not full else f"{version}. {ref}."
        note = ""
    elif style in ("chicago", "turabian"):
        out["citation"] = f"{ref}{label}" if not full else f"{version}. {ref}."
        note = ""
    else:
        return {"ok": False, "error": f"unknown style '{style}'"}
    att = _attribution(meta)
    out["note"] = note
    out["attribution"] = att
    return out


# ----------------------------------------------------------- bibliography --

def bibliography(module_ids: list[str], *, style: str = "sbl",
                 full: bool = True) -> dict:
    """A bibliography, sorted by the author or organisation that leads it."""
    entries, flagged = [], []
    for mid in module_ids:
        c = cite(mid, style, full=full)
        if not c.get("ok"):
            continue
        entries.append(c)
        if not c["complete"]:
            flagged.append({"module_id": mid, "missing": c["missing"],
                            "name": c["meta"].get("name")})
    def sort_key(c):
        a = _author_forms(c["meta"])
        return (a["surname"] or a["orgname"]
                or c["meta"].get("name") or "").lower()
    entries.sort(key=sort_key)
    lines = [c["citation"] for c in entries]
    return {"ok": True, "style": style, "entries": entries,
            "text": "\n\n".join(lines), "count": len(entries),
            "flagged": flagged,
            "note": (f"{len(flagged)} of {len(entries)} entries are missing "
                     "fields" if flagged else "every entry has the fields its "
                     "style needs")}


# ---------------------------------------------------------------- exports --

def _tex_escape(s: str) -> str:
    """BibTeX keys and values are LaTeX.  Unescaped braces and backslashes make
    BibTeX fail on the whole file, not just the one entry."""
    return (s.replace("\\", r"\textbackslash{}").replace("{", r"\{")
             .replace("}", r"\}").replace("&", r"\&").replace("%", r"\%")
             .replace("$", r"\$").replace("#", r"\#").replace("_", r"\_"))


_BIBTEX_TYPE = {
    "Bible": "book", "Commentary": "book", "Book": "book", "Devotional": "book",
    "Lexicon": "book", "Dictionary": "book", "Article": "article",
    "Atlas": "book", "Map": "misc", "Bio": "misc", "Person": "misc",
}


def _cite_key(mid: str, meta: dict) -> str:
    a = _author_forms(meta)
    lead = _clean(a["surname"] or a["orgname"] or meta.get("name")) or "anon"
    year = meta.get("year_clean") or "nd"
    key = re.sub(r"[^A-Za-z0-9]", "", lead)[:24] or "anon"
    return f"{key}{year}"


def bibtex(module_ids: list[str]) -> dict:
    """BibTeX, which is the way into Zotero.

    Zotero cannot read this app directly, and a .bib file is the route readers
    are pointed at for the same reason.
    """
    out = ["% G-Bible bibliography. Generated locally; no data was sent anywhere.",
           "% Fields marked unknown are genuinely unknown -- see the report "
           "below rather than trusting a guess.", ""]
    used, missing = set(), []
    for mid in module_ids:
        meta = metadata(mid)
        if not meta:
            continue
        key = _cite_key(mid, meta)
        base, n = key, 1
        while key in used:
            n += 1
            key = f"{base}{chr(ord('a') + n - 2)}"
        used.add(key)
        typ = _BIBTEX_TYPE.get(meta.get("type") or "", "misc")
        a = _author_forms(meta)
        # Every field line ends in a comma.  Without them BibTeX does not
        # complain about the entry it is reading -- it rejects the file, and
        # the error it gives points at the wrong line.
        f = []
        if a["inverted"]:
            f.append(f"  author = {{{_tex_escape(a['inverted'])}}},")
        else:
            f.append("  author = {},")
        f.append(f"  title = {{{_tex_escape(_clean(meta.get('name')))}}},")
        f.append(f"  year = {{{meta.get('year_clean') or 'n.d.'}}},")
        for field, tag in (("publisher", "publisher"), ("place", "address"),
                           ("series", "series"), ("isbn", "isbn"),
                           ("url", "url"), ("edition", "edition")):
            v = _clean(meta.get(field))
            if v:
                f.append(f"  {tag} = {{{_tex_escape(v)}}},")
        if _clean(meta.get("license")):
            f.append(f"  note = {{{_tex_escape(_attribution(meta))}}},")
        f.append(f"  gbibleid = {{{_tex_escape(mid)}}}")
        out.append(f"@{typ}{{{key},")
        out.extend(f)
        out.append("}")
        out.append("")
        if not meta["complete"]:
            missing.append({"module_id": mid, "name": meta.get("name"),
                            "missing": meta["missing"]})
    return {"ok": True, "bibtex": "\n".join(out),
            "entries": len(used), "missing": missing,
            "note": f"{len(missing)} entr{'y' if len(missing)==1 else 'ies'} "
                    "lack a field; year is marked n.d. rather than guessed"}


def ris(module_ids: list[str]) -> dict:
    """RIS, the other format Zotero imports."""
    out = []
    missing = []
    for mid in module_ids:
        meta = metadata(mid)
        if not meta:
            continue
        a = _author_forms(meta)
        typ = {"Bible": "BOOK", "Commentary": "BOOK", "Book": "BOOK",
               "Lexicon": "BOOK", "Dictionary": "BOOK", "Article": "JOUR",
               "Atlas": "BOOK", "Map": "MAP"}.get(meta.get("type") or "", "GEN")
        out.append(f"TY  - {typ}")
        if a["inverted"]:
            out.append(f"AU  - {a['inverted']}")
        out.append(f"TI  - {_clean(meta.get('name'))}")
        if meta.get("year_clean"):
            out.append(f"PY  - {meta['year_clean']}")
        for field, tag in (("publisher", "PB"), ("place", "CY"),
                           ("series", "T2"), ("isbn", "SN"), ("url", "UR"),
                           ("version", "ET"), ("license", "LA")):
            v = _clean(meta.get(field))
            if v:
                out.append(f"{tag}  - {v}")
        if _clean(meta.get("rights")):
            out.append(f"N1  - {_clean(meta.get('rights'))}")
        out.append(f"N1  - G-Bible module: {mid}")
        out.append("ER  - ")
        out.append("")
        if not meta["complete"]:
            missing.append({"module_id": mid, "name": meta.get("name"),
                            "missing": meta["missing"]})
    return {"ok": True, "ris": "\n".join(out), "entries": len(
        [l for l in out if l.startswith("TY  - ")]), "missing": missing}


def _md_escape(s: str) -> str:
    return s.replace("|", r"\|")


def csv(module_ids: list[str]) -> dict:
    """Spreadsheet export — the "Excel" option in the print/export menu."""
    cols = ["module_id", "title", "type", "author", "year", "publisher",
            "place", "version", "license", "rights", "url", "complete", "missing"]
    lines = [",".join(cols)]
    for mid in module_ids:
        m = metadata(mid)
        if not m:
            continue
        row = [mid, _clean(m.get("name")), _clean(m.get("type")),
               _clean(m.get("author")), _clean(m.get("year")),
               _clean(m.get("publisher")), _clean(m.get("place")),
               _clean(m.get("version")), _clean(m.get("license")),
               _clean(m.get("rights")), _clean(m.get("url")),
               "yes" if m["complete"] else "no",
               "; ".join(m["missing"])]
        lines.append(",".join('"' + _md_escape(v).replace('"', '""') + '"'
                              for v in row))
    return {"ok": True, "csv": "\n".join(lines), "entries": len(lines) - 1}