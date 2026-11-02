"""Where does an installed module belong?

The old Store treated every catalogue entry as an interchangeable row: install
it and it appeared in a flat list, and the user was left to work out which pane
it belonged in.  That is the wrong model, and it is why "Treasury of Scripture
Knowledge" ended up filed as a commentary next to Barnes.

A module's *type* already implies how it is read -- `taxonomy.ResourceType`
carries a `reader` field, and `library.read()` dispatches on it.  Placement is
therefore not a separate guess: it is the type, read out loud.  This module is
the single place that turns a type into a named pane, so the browser, the
installer, the workspace builder and the Library all agree.

Two refinements matter in practice:

*   **Slot** is finer than reader.  A Commentary, a CrossReference and a Bible
    are all read verse-by-verse, but they go to different panes and link
    differently: a commentary scrolls with the Bible, a cross-reference set is
    looked up *at* a verse, and a Bible *is* the cursor.

*   **Overrides.**  A handful of well-known modules are filed under a type that
    is wrong for study purposes.  TSK ships as a SWORD commentary but its entire
    content is cross-references, so it belongs in the cross-reference pane.
    These are listed explicitly in `OVERRIDES` rather than inferred, because a
    silent heuristic here would be impossible for a user to audit -- and the
    whole point of the licence gate and this module is that decisions are
    visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import taxonomy


@dataclass(frozen=True)
class Slot:
    """A named destination pane."""

    id: str
    label: str
    reader: str                     # must match taxonomy ResourceType.reader
    glyph: str = ""
    # Whether a Bible and this resource can share a link set and scroll
    # together.  Positional things link; reference things are looked up.
    links_to_bible: bool = False
    # The cursor a fresh pane of this type needs before it shows anything.
    opens_with: str = ""
    note: str = ""


SLOTS: tuple[Slot, ...] = (
    # Audio plays; it does not read like an image.  It links to the Bible on
    # verse milestones so the reading pane can follow along.
    Slot("audio", "Audio", "audio", "\u25B6", links_to_bible=True,
         opens_with="Play"),
    Slot("bible", "Bible", "verse", "\u25a4", links_to_bible=True,
         opens_with="John.1.1",
         note="The primary text. Usually one per linked set."),
    Slot("parallel", "Parallel / interlinear", "verse", "\u2261",
         links_to_bible=True, opens_with="John.1.1",
         note="Verse-keyed alongside a Bible; scrolls with it."),
    Slot("original", "Original language", "verse", "\u03b1\u03b2\u03b3",
         links_to_bible=True, opens_with="John.1.1",
         note="Hebrew, Greek or Latin text with its own versification."),
    Slot("commentary", "Commentary", "verse", "\u270e", links_to_bible=True,
         opens_with="John.3",
         note="Verse notes. Shares a link set with a Bible and scrolls with it."),
    Slot("crossref", "Cross-references", "verse", "\u21c4",
         links_to_bible=True, opens_with="John.3.16",
         note="Keyed to a verse, opened by selecting a reference or a link."),
    Slot("harmony", "Harmony / synopsis", "verse", "\u2263",
         links_to_bible=True, opens_with="John.1.1"),
    Slot("outline", "Study guide / outline", "verse", "\u2637",
         links_to_bible=True, opens_with="John.1.1"),
    Slot("lexicon", "Lexicon", "article", "\u03b1", opens_with="",
         note="Looked up by the word in the Bible pane, not scrolled to it."),
    Slot("concordance", "Concordance", "article", "\u2261",
         note="Every occurrence of a form, then its Strong's entry."),
    Slot("dictionary", "Dictionary", "article", "\u00a7"),
    Slot("grammar", "Grammar / morphology", "article", "\u03bc"),
    Slot("factbook", "FactBook", "topic", "\u2756", opens_with="",
         note="Topics and people. Reached from a word or a place name."),
    Slot("lectionary", "Lectionary", "date", "\u25a5", opens_with="",
         note="Day-keyed readings."),
    Slot("devotional", "Devotional", "date", "\u2600", opens_with=""),
    Slot("book", "Book", "book", "\u25a4", opens_with="",
         note="Divided into sections and read by chapter."),
    Slot("map", "Map / image", "image", "\u25d3"),
    Slot("other", "Other", "book", "\u2022"),
)

SLOT_BY_ID: dict[str, Slot] = {s.id: s for s in SLOTS}

# type id -> slot id
TYPE_SLOT: dict[str, str] = {
    "Bible": "bible",
    "StudyBible": "bible",
    "ParallelBible": "parallel",
    "OriginalLanguage": "original",
    "Manuscript": "original",
    "Apologetics": "commentary",
    "Commentary": "commentary",
    "StudyGuide": "outline",
    "SermonOutline": "outline",
    "Harmony": "harmony",
    "CrossReference": "crossref",
    "TopicalBible": "factbook",
    "Lexicon": "lexicon",
    "Concordance": "concordance",
    "Dictionary": "dictionary",
    "Glossary": "dictionary",
    "Grammar": "grammar",
    "Syntax": "crossref",
    "FactBook": "factbook",
    "Lectionary": "lectionary",
    "Devotional": "devotional",
    "Book": "book",
    "Essay": "book",
    "Atlas": "map",
    "Map": "map",
    "Illustration": "map",
    "Media": "map",
    "Audio": "audio",
    "Other": "other",
}

# Modules the catalogue files under a type that is wrong for study purposes.
# Keyed by the SWORD module id, value is (type, why).
OVERRIDES: dict[str, tuple[str, str]] = {
    "tsk": ("CrossReference",
            "Ships as a SWORD commentary, but the content is entirely "
            "cross-references, so it belongs in the cross-reference pane."),
    "dtn": ("CrossReference",
            "Darby's Translation Notes are a cross-reference apparatus."),
    "kalendar": ("Lectionary", "A lectionary, not a commentary."),
    "prodesh": ("Lectionary", "A lectionary, not a commentary."),
    "lectionaries": ("Lectionary", "A lectionary, not a commentary."),
    "catena": ("Commentary", "A catena chains the Fathers verse by verse."),
    "tskmorph": ("CrossReference", "Cross-references with Strong's numbers."),
    "tr(idx)": ("CrossReference", "Eusebian / index apparatus."),
    "abbottsmithstrongs": ("Lexicon",
                           "An alphabetical lexicon, so an article lookup, "
                           "not a verse-keyed commentary."),
    "webster1913": ("Dictionary",
                    "An English dictionary: looked up by headword."),
    "webster1806": ("Dictionary", "An English dictionary."),
    "nave": ("FactBook", "A topical Bible: topic-keyed, not verse-keyed."),
    "torrey": ("FactBook", "A topical textbook: topic-keyed."),
    "tcr": ("FactBook", "Thompson's Chain Topics: topic-keyed."),
    "hitchcock": ("FactBook", "A names dictionary: person-keyed."),
    "scofield": ("Commentary", "Verse notes, despite the topical framing."),
    "mhc": ("Commentary", "Matthew Henry is verse-keyed commentary."),
    "mhg": ("Commentary", "Matthew Henry is verse-keyed commentary."),
    "mhcw": ("Commentary", "Matthew Henry is verse-keyed commentary."),
    "easton": ("Dictionary", "A Bible dictionary: headword lookup."),
    "smith": ("Dictionary", "A Bible dictionary: headword lookup."),
    "isbe": ("Dictionary", "An encyclopedia: headword lookup."),
    "fausset": ("Dictionary", "An encyclopedia: headword lookup."),
    "morrison": ("Dictionary", "An encyclopedia: headword lookup."),
    "amtract": ("FactBook", "A Bible dictionary in encyclopedic form."),
    # Crosswire files both Klingon glossaries as FactBook, and FactBook is what
    # topicindex.py treats as "entries are topics addressed to verses" -- so
    # they were being indexed as topics, producing nothing usable, while no
    # reader that could serve them offered them.  They are two-way word lists
    # and belong with the lexicons.  tools/fix_module_types.py corrects the
    # stored type; this is the reader slot, and both are needed because one
    # feeds topicindex and the other feeds placement.
    # Full ids, not the trailing segments: `crosswire-klven-iklingon` ends in
    # "iklingon" and `crosswire-klviklingon-en` ends in "en", and a key of
    # "en" would then match every module from that namespace whose id happens
    # to end that way.  `_override_for` tries the full id first, so writing it
    # out is both the working spelling and the safe one.
    "crosswire-klven-iklingon": ("Lexicon",
                                 "A Klingon->English word list: looked up by "
                                 "headword, not a topic addressed to "
                                 "scripture."),
    "crosswire-klviklingon-en": ("Lexicon",
                                 "An English->Klingon word list: looked up by "
                                 "headword."),
}


def _override_for(module_id: str) -> tuple[str, str] | None:
    """Look up an override by module id.

    Installed ids are namespaced -- `crosswire-tsk`, `ebible-eng-web` -- while
    the override table is written in the upstream vocabulary (`tsk`).  Match the
    full id first, then the trailing segment, so a table written either way
    works.
    """
    if module_id in OVERRIDES:
        return OVERRIDES[module_id]
    tail = module_id.rsplit("-", 1)[-1]
    return OVERRIDES.get(tail)


def type_for(module_id: str, category: str) -> str:
    """Resolve the effective type, honouring the override table."""
    ov = _override_for(module_id)
    if ov:
        return ov[0]
    return category if category in taxonomy.TYPE_BY_ID else "Other"


def types_for_slot(slot_id: str) -> list[str]:
    """The resource types that go in a slot -- the inverse of TYPE_SLOT.

    A study workflow asks for a slot ("a commentary") rather than a module id,
    so that the flow keeps working when the resource is swapped for a better
    one; this is what turns that ask back into something countable.
    """
    return sorted(t for t, s in TYPE_SLOT.items() if s == slot_id)


def slot_for_type(type_id: str) -> Slot:
    return SLOT_BY_ID.get(TYPE_SLOT.get(type_id, "other"), SLOT_BY_ID["other"])


def slot_for(module_id: str, category: str) -> Slot:
    return slot_for_type(type_for(module_id, category))


def describe(module) -> dict:
    """Everything the browser and the installer need to say where this goes."""
    t = type_for(module.id, module.type)
    s = slot_for_type(t)
    ov = _override_for(module.id)
    return {
        "type": t,
        "type_label": (taxonomy.TYPE_BY_ID[t].label
                       if t in taxonomy.TYPE_BY_ID else t),
        "slot": s.id,
        "slot_label": s.label,
        "reader": s.reader,
        "glyph": s.glyph,
        "links_to_bible": s.links_to_bible,
        "opens_with": s.opens_with,
        "note": s.note,
        "reclassified": bool(ov),
        "reclassified_from": (module.type if ov else ""),
        "reclassified_why": (ov[1] if ov else ""),
    }


def preview(repo_id: str, item_id: str, category: str, title: str = "") -> dict:
    """Placement for a catalogue entry that is not installed yet.

    The browser has to say "this goes in the cross-reference pane" *before* the
    user commits to a 10 MB download, so this works from the catalogue row and
    the id the module will be given (`<repo>-<item>`), which is enough for the
    override table to apply.
    """
    future = f"{repo_id}-{item_id}"
    t = type_for(future, category)
    s = slot_for_type(t)
    ov = _override_for(future)
    return {
        "type": t,
        "type_label": (taxonomy.TYPE_BY_ID[t].label
                       if t in taxonomy.TYPE_BY_ID else t),
        "slot": s.id,
        "slot_label": s.label,
        "reader": s.reader,
        "glyph": s.glyph,
        "links_to_bible": s.links_to_bible,
        "opens_with": s.opens_with,
        "note": s.note,
        "reclassified": bool(ov),
        "reclassified_from": (category if ov else ""),
        "reclassified_why": (ov[1] if ov else ""),
        "module_id_if_installed": future,
        "title": title,
    }


def placement_report(module) -> str:
    """One line for the install toast, naming the pane it landed in."""
    d = describe(module)
    note = f" (filed as {d['type_label']}, not {d['reclassified_from']})" \
        if d["reclassified"] else ""
    return f"{d['slot_label']} pane{note}"


# --------------------------------------------------------------------------
# "This is already in use" detection
# --------------------------------------------------------------------------

def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def duplicates_of(module, others) -> list[dict]:
    """Installed modules that are the same work under another name.

    Two signals, both conservative enough to be worth telling the user about:
    an identical normalised title, or the same SWORD module id appearing from a
    different repository.  The second is the common case -- the World English
    Bible exists on both eBible.org and CrossWire, and installing both gives
    you two copies of the same text in the search results.
    """
    key = _norm(module.name)
    out: list[dict] = []
    for o in others:
        if o.id == module.id:
            continue
        same_id = (module.source_name and o.source_name
                   and module.source_name == o.source_name)
        same_title = key and key == _norm(o.name)
        if same_id or same_title:
            out.append({
                "module_id": o.id,
                "name": o.name,
                "type": o.type,
                "repo": o.source_name or o.source or "",
                "reason": ("same module from another repository"
                           if same_id else "same title"),
            })
    return out


def duplicates_of_names(name: str, repo_id: str, item_id: str,
                        installed=()) -> list[dict]:
    """Does the user already have this, under another name or another source?

    `installed` is a sequence of (module_id, module_name, source_id).  The
    question is asked against what is *actually installed*, not against the
    catalogue, because "I already have the World English Bible" can only be
    answered by looking at the library.

    Two signals:

    *   the same work offered by a different repository -- the SWORD module id
        is the same but the repo prefix is not, which is the common case for
        the World English Bible, the ASV, Strong's and Barnes;
    *   the same title, which catches the same text arriving under a different
        name ("World English Bible Classic" vs "World English Bible").
    """
    if not item_id:
        return []
    from .library import slugify
    want_id = slugify(f"{repo_id}-{item_id}")
    key = _norm(name)
    out: list[dict] = []
    for mid, mname, msrc in installed:
        if slugify(mid) == want_id:
            continue                      # this *is* the installed module
        tail = mid.split("-", 1)[-1]
        same_module = bool(item_id) and slugify(tail) == slugify(item_id) and \
            not slugify(mid).startswith(f"{slugify(repo_id)}-")
        same_title = bool(key) and key == _norm(mname)
        if same_module or same_title:
            out.append({
                "module_id": mid,
                "name": mname,
                "repo": msrc or "",
                "reason": ("the same module from another repository"
                           if same_module else "the same title"),
            })
    return out


def panes_using(module_id: str, layouts=()) -> list[dict]:
    """Which open panes would break if this module were removed."""
    out: list[dict] = []
    for lay in layouts or ():
        for pane in lay.get("panes") or ():
            if pane.get("module_id") == module_id:
                out.append({
                    "layout": lay.get("name", ""),
                    "layout_id": lay.get("id", ""),
                    "tile": pane.get("tile_id", ""),
                    "link_set": pane.get("link_set", ""),
                })
    return out


def conflict_report(module, others, layouts=()) -> dict:
    """What the browser should warn about before/after installing something."""
    dups = duplicates_of(module, others)
    used = panes_using(module.id, layouts)
    return {
        "duplicate_of": dups,
        "used_by_panes": used,
        "severity": ("duplicate" if dups else "in-use" if used else "none"),
    }
