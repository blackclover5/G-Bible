"""Turning what you have been reading into something you can hand to someone.

This is the "professional output" layer: a passage, your notes, or a
bibliography, laid out for paper or for a screen and written out in a format
somebody else can open.

**The formats, and why each one is here.**  Plain text, Markdown, HTML and RTF
because those are what a person or a word processor can actually use — RTF in
particular, since it is the one format Word, Pages and LibreOffice all open
without being asked to install anything.  PDF because a PDF is what you hand to
someone.  BibTeX and RIS because Zotero is where citation management actually
happens, and Zotero reads both.

**What is deliberately not here is Proclaim.**  Some platforms export to it, and it is
a good tool for church displays, but the format is a proprietary product from a
commercial vendor with no published specification.  Writing a file that claims to
be a Proclaim presentation without that specification would mean guessing at a
binary layout and hoping, which produces files that fail silently on the
equipment they were made for.  So the honest answer is: the features Proclaim has
— text, images and citations laid out for projection — are available here through
PDF and RTF, and the format itself is not.

**Attribution is not optional.**  Every document builder takes the licences of
the material it is about and prints them.  CC BY 4.0 requires attribution, so an
export that omitted it would be a breach of the licence on exactly the resources
this project is careful about.  The sentence is assembled from the data rather
than typed in, so it cannot be forgotten when someone exports at midnight.

Nothing here sends anything anywhere.  Every function returns a string or bytes
and the caller decides what to do with it.
"""

from __future__ import annotations

import csv
import io
import re
import time

from . import canon, citation, db, notes as notes_mod, pdf, pptx, store

FORMATS = {
    "pdf": "PDF — for handing to someone",
    "rtf": "RTF — opens in Word, Pages and LibreOffice",
    "html": "HTML — opens in anything",
    "md": "Markdown — for notes programs and git",
    "txt": "Plain text",
    "bib": "BibTeX — import into Zotero",
    "ris": "RIS — import into Zotero",
    "csv": "CSV — a spreadsheet",
    "pptx": "PPTX — opens in PowerPoint, Impress and Keynote",
}

#: Which formats each document can actually be written as.
#:
#: The front end listed all eight for a passage export while `passage_document`
#: wrote five, so BibTeX, RIS and CSV were three buttons that always failed --
#: the request came back 500 and the anchor still saved the error body as a file
#: called `John-3-16.bib`.  A bibliography has no passage text in it and a passage
#: has no bibliographic metadata in it, which is *why* the sets differ, so the
#: honest fix is for the backend to declare the sets and the dialog to read them.
#: One list, one source, no second copy to forget to update.
_DOCUMENT_FORMATS = {
    "passage": ("md", "txt", "html", "rtf", "pdf", "pptx"),
    "notes": ("md", "txt", "html", "rtf", "pdf", "pptx"),
    "bibliography": ("md", "txt", "html", "rtf", "pdf", "pptx", "bib", "ris", "csv"),
}


def document_formats(kind: str = "passage") -> list[dict]:
    """The formats a given document can be written as, with their descriptions."""
    order = _DOCUMENT_FORMATS.get(kind, ())
    return [{"id": f, "label": FORMATS[f]} for f in order if f in FORMATS]


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------- licence ---

def licence_lines(module_ids: list[str]) -> list[str]:
    """One attribution line per distinct licence in the material being used.

    Grouped by licence rather than repeated per module, because the point of an
    attribution requirement is that a reader can see what they are being asked
    to comply with -- forty copies of "Public domain" says less than one.
    """
    groups: dict[str, list[str]] = {}
    for mid in module_ids:
        m = citation.metadata(mid)
        if not m:
            continue
        lic = (m.get("license") or "").strip() or "licence not recorded"
        groups.setdefault(lic, []).append(m.get("name") or mid)
    out = []
    for lic, names in sorted(groups.items()):
        if lic.lower().replace("_", "-") in ("public domain", "publicdomain", "pd"):
            out.append(f"{len(names)} work(s): public domain, no restrictions.")
        else:
            out.append(f"{len(names)} work(s): {lic} — attribution required, "
                       f"as given below.")
    return out


def attribution_block(module_ids: list[str]) -> str:
    """The licence statement that goes on every exported document."""
    metas = [citation.metadata(m) for m in module_ids]
    metas = [m for m in metas if m]
    if not metas:
        return "No installed resources were used in this document."
    lines = [f"Produced with G-Bible, {_stamp()}.",
             "",
             "Sources and their terms of use:"]
    seen: set[str] = set()
    for m in sorted(metas, key=lambda x: (x.get("license") or "", x.get("name") or "")):
        name = m.get("name") or m["id"]
        lic = (m.get("license") or "licence not recorded").strip()
        line = f"  · {name} — {lic}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if m.get("rights") and m["rights"].strip() not in line:
            lines.append(f"      {m['rights'].strip()}")
    ccs = sorted({(m.get("license") or "").strip().upper() for m in metas} - {""})
    if any("CC-BY" in x for x in ccs):
        lines += ["",
                  "CC BY 4.0 requires attribution, a link to the licence, and "
                  "notice of changes. The list above is that notice; the licence "
                  "text is at creativecommons.org/licenses/by/4.0/."]
    return "\n".join(lines)


# ------------------------------------------------------------------ text ---

def _passage_texts(ref: str, module_ids: list[str]) -> tuple[str, list[dict]]:
    """The passage as text, read from **the modules that were asked for**.

    Each entry is `{module_id, module, text}`.

    This used to return `study.passage_guide(ref)["texts"]`, which is a pair of
    translations passage_guide picks for *its own* display -- it reads its own
    preference list and knows nothing about the caller -- and then label them
    positionally with `module_ids`.  So a request for `[KJV, ASV]` came back with
    whichever two Bibles passage_guide preferred, under the names KJV and ASV.
    The exported document therefore attributed one translation's words to another
    translation, printed the reader's name above them, and attached that reader's
    citation to the passage.  A wrong attribution in a document whose entire
    purpose is to be citable is not a cosmetic fault, and nothing about the
    output looked wrong: two real translations, two real citations, the text
    simply belonged to neither heading it was filed under.

    Reading each requested module through `library.read` fixes it at the source,
    and reports a module it could not read instead of substituting another one --
    a missing translation in an export is visible, a substituted one is not.
    """
    from . import library
    rng = canon.parse_ref(ref) if ref else None
    label = ref
    try:
        label = canon.format_ref(rng) if rng else ref
    except Exception:
        pass
    # A range has to be sliced here rather than asked for.  `_read_bible` returns
    # the whole chapter whatever the span -- the reader pane does its own slicing
    # client-side -- and `context` only sizes the surrounding verses shown as
    # greyed lines.  So "John 3:16" exported as John 3:1 to 3:36, which is what
    # the first version of this did: a whole chapter, filed under one verse, with
    # that verse's citation above it.
    cur: dict = {"ref": ref}
    out: list[dict] = []
    for mid in module_ids:
        try:
            c = library.read(mid, cur, span="range", context=0)
        except Exception as exc:
            out.append({"module_id": mid, "module": mid, "text": "",
                        "error": f"{type(exc).__name__}: {exc}"})
            continue
        items = _slice_to_range(c.items, rng)
        body = " ".join((i.text or "").strip() for i in items
                        if (i.text or "").strip())
        if not body and not items:
            body = ""
        out.append({"module_id": mid, "module": c.module_name,
                    "text": body})
    return label, out


def _slice_to_range(items, rng) -> list:
    """The items inside `rng`, or all of them when there is no range to slice by.

    A verse item's `key` is its reference -- `John 3:16` -- which is the field the
    reader itself numbers and navigates by.  `extra` is decoration (Strong's,
    lemmas, notes) and carries no reference at all.
    """
    if rng is None:
        return list(items)
    start, end = rng.start, rng.end or rng.start

    def pos(i):
        for src in (i.extra.get("ref") if isinstance(i.extra, dict) else None,
                    i.key):
            if not src:
                continue
            try:
                v = canon.parse_ref(str(src))
            except Exception:
                continue
            if v and v.start and v.start.verse:
                return (v.start.book, v.start.chapter, v.start.verse)
        return None

    got = [i for i in items
           if (p := pos(i)) is not None
           and (start.book, start.chapter, start.verse) <= p
           <= (end.book, end.chapter, end.verse)]
    # A module whose items carry no usable reference is returned whole rather
    # than filtered to nothing, and the caller reports the count.
    return got or list(items)


def _md(s: str) -> str:
    """The italics markers used everywhere else in this file's output."""
    return re.sub(r"\*([^*]+)\*", r"_\1_", s or "")


def _strip_md(s: str) -> str:
    return re.sub(r"\*([^*]+)\*", r"\1", s or "")


# ------------------------------------------------------------------- RTF ---

_RTF_ESC = {"\\": r"\\", "{": r"\{", "}": r"\}"}
_RTF_UNI = re.compile(r"[^\x20-\x7e]")


def rtf_escape(s: str) -> str:
    """RTF literal escaping, plus \\uN for anything outside ASCII.

    RTF is Latin-1 with escape codes, so a note containing an em dash or any
    Greek has to be written as \\uNNNN or it comes out as a question mark.  The
    negative form \\uNNNN? is used because that is what Word and every other
    reader actually honour.
    """
    out = []
    for ch in s or "":
        if ch in _RTF_ESC:
            out.append(_RTF_ESC[ch])
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            o = ord(ch)
            out.append(rf"\u{-(2**16) + o if o > 32767 else o}?")
    return "".join(out)


def _rtf_doc(blocks: list[dict]) -> str:
    """blocks: {text, style} where style is one of h1,h2,body,italic,small,rule."""
    head = (r"{\rtf1\ansi\ansicpg1252\deff0"
            r"{\fonttbl{\f0\froman Times New Roman;}"
            r"{\f1\fswiss Helvetica;}}"
            r"\viewkind4\uc1\pard\sa180\sl252\slmult1")
    body = []
    for b in blocks:
        style = b.get("style", "body")
        t = rtf_escape(b.get("text", ""))
        if style == "h1":
            body.append(rf"\pard\b\f1\fs32 {t}\b0\f0\fs22\par")
        elif style == "h2":
            body.append(rf"\pard\b {t}\b0\par")
        elif style == "italic":
            body.append(rf"\pard\it {t}\par")
        elif style == "small":
            body.append(rf"\pard\f1\fs17 {t}\par")
        elif style == "rule":
            body.append(r"\pard\hrulefill\par")
        else:
            body.append(rf"\pard {t}\par")
    return head + "".join(body) + "}"


# ------------------------------------------------------------- documents ---

def passage_document(ref: str, module_ids: list[str], *,
                     style: str = "sbl", fmt: str = "md",
                     title: str = "") -> dict:
    """A passage, its translation names, its citations, and its licences."""
    label, texts = _passage_texts(ref, module_ids)
    if not any(t.get("text") for t in texts):
        # Nothing readable.  Say which module and why, because "nothing to export
        # for that reference" points at the reference, which is not the problem --
        # the passage was fine and the reader was not.
        why = "; ".join(f"{t['module_id']}: {t.get('error') or 'no text'}"
                        for t in texts) or "no module was given"
        return {"ok": False, "error": f"nothing to export: {why}"}
    # `texts` is now one entry per requested module, in the order asked for, each
    # carrying its own id and reader's name.  Every format below reads the name
    # off its own entry instead of indexing into `module_ids`.
    texts = [t for t in texts if t.get("text") or t.get("error")]
    head = title or label
    cites = [citation.passage_citation(label, t["module_id"], style=style)
             for t in texts]
    cites = [c for c in cites if c.get("ok")]
    att = attribution_block([t["module_id"] for t in texts])

    def _warn() -> str:
        bad = [t for t in texts if t.get("error")]
        return ("; ".join(f"{t['module']} could not be read ({t['error']})"
                          for t in bad) + ".") if bad else ""

    if fmt == "md":
        out = [f"# {head}", ""]
        for c in cites:
            out += [f"*{c['citation']}*", ""]
        for t in texts:
            out += [f"## {t['module'] or t['module_id']}", ""]
            if t.get("error"):
                out += [f"*not available: {t['error']}*", ""]
            else:
                out += [t["text"], ""]
        out += ["---", "", "### Sources and terms", "", att, ""]
        if _warn():
            out += [_warn(), ""]
        return {"ok": True, "text": "\n".join(out), "format": "md",
                "note": _warn()}
    if fmt == "txt":
        out = [head, "=" * len(head), ""]
        out += [c["citation"] for c in cites] + [""]
        for t in texts:
            out += [t["module"] or t["module_id"], "-" * 40]
            out += [t.get("text") or f"[not available: {t.get('error')}]", ""]
        out += ["-" * 40, "Sources and terms", "", att]
        if _warn():
            out += ["", _warn()]
        return {"ok": True, "text": "\n".join(out), "format": "txt",
                "note": _warn()}
    if fmt == "html":
        rows = "".join(f"<p class=cite>{c['citation']}</p>" for c in cites)
        body = "".join(
            f"<h2>{_html(t['module'] or t['module_id'])}</h2>"
            + (f"<p class=warn>not available: {_html(t['error'])}</p>"
               if t.get("error") else f"<p class=body>{_html(t['text'])}</p>")
            for t in texts)
        html = _html_page(head, f"{rows}{body}", att)
        return {"ok": True, "text": html, "format": "html", "note": _warn()}
    if fmt == "rtf":
        blocks = [{"text": head, "style": "h1"}, {"text": "", "style": "rule"}]
        blocks += [{"text": _strip_md(c["citation"]), "style": "italic"} for c in cites]
        for t in texts:
            blocks.append({"text": t["module"] or t["module_id"], "style": "h2"})
            blocks.append({"text": t.get("text")
                           or f"[not available: {t.get('error')}]",
                           "style": "body"})
        blocks += [{"text": "", "style": "rule"},
                   {"text": "Sources and terms", "style": "h2"},
                   {"text": att, "style": "small"}]
        return {"ok": True, "text": _rtf_doc(blocks), "format": "rtf",
                "note": _warn()}
    if fmt == "pdf":
        doc = pdf.Doc(title=head, subject=f"{head} — exported from G-Bible")
        doc.text(head, font="helvetica-bold", size=17, space_after=2)
        doc.rule()
        for c in cites:
            doc.text(_strip_md(c["citation"]), font="times-italic", size=10,
                     colour=(0.25, 0.25, 0.25), space_after=2)
        for t in texts:
            doc.text(t["module"] or t["module_id"], font="helvetica-bold",
                     size=11, space_before=6, space_after=2)
            doc.text(t.get("text") or f"[not available: {t.get('error')}]",
                     font="times", size=11)
        doc.rule()
        doc.text("Sources and terms", font="helvetica-bold", size=9,
                 space_after=2)
        doc.text(att, font="helvetica", size=8, colour=(0.3, 0.3, 0.3),
                 leading=1.25)
        data = doc.build(footer=label)
        note = _warn()
        if doc.skipped_scripts:
            note = ((note + " " if note else "")
                    + f"{doc.skipped_scripts} characters of Hebrew or Greek were "
                      "left out: the base-14 PDF fonts cannot render them and "
                      "substituting another font would be quietly wrong. Use the "
                      "HTML or RTF export for those.")
        return {"ok": True, "binary": data, "format": "pdf",
                "bytes": len(data), "skipped_scripts": doc.skipped_scripts,
                "note": note}
    if fmt == "pptx":
        pr = pptx.Presentation(title=head, author="G-Bible")
        for c in cites:
            pr.add_slide(_strip_md(c["citation"]), [])
        for t in texts:
            pr.add_slide(t["module"] or t["module_id"],
                         [t.get("text") or f"[not available: {t.get('error')}]"])
        data = pr.build(attribution=att)
        return {"ok": True, "binary": data, "format": "pptx",
                "bytes": len(data), "note": _warn()}
    return {"ok": False, "error": f"unknown format '{fmt}'",
            "formats": sorted(FORMATS)}


def study_guide_document(ref: str, module_ids: list[str], *,
                        fmt: str = "md", title: str = "") -> dict:
    """A group-study handout: the passage, its citations, extractive study
    questions, and the licence block.  Templates, not generated prose — every
    question names what it came from.
    """
    label, texts = _passage_texts(ref, module_ids)
    if not any(t.get("text") for t in texts):
        why = "; ".join(f"{t['module_id']}: {t.get('error') or 'no text'}"
                        for t in texts) or "no module was given"
        return {"ok": False, "error": f"nothing to export: {why}"}
    texts = [t for t in texts if t.get("text") or t.get("error")]
    head = title or f"Study guide: {label}"
    cites = [citation.passage_citation(label, t["module_id"], style="sbl")
             for t in texts]
    cites = [c for c in cites if c.get("ok")]
    att = attribution_block([t["module_id"] for t in texts])
    try:
        from . import docs as _docs
        qs = _docs.study_questions(ref).get("questions") or []
    except Exception:  # noqa: BLE001
        qs = []
    if fmt == "md":
        out = [f"# {head}", ""]
        for c in cites:
            out += [f"*{c['citation']}*", ""]
        for t in texts:
            out += [f"## {t['module'] or t['module_id']}", ""]
            if t.get("error"):
                out += [f"*not available: {t['error']}*", ""]
            else:
                out += [t["text"], ""]
        if qs:
            out += ["## Study questions", ""]
            for q in qs:
                out += [f"- ({q.get('kind','')}) {q.get('q','')}",
                        f"  _from {q.get('from','')}_", ""]
        out += ["---", "", "### Sources and terms", "", att, ""]
        return {"ok": True, "text": "\n".join(out), "format": "md"}
    if fmt == "txt":
        out = [head, "=" * len(head), ""]
        out += [c["citation"] for c in cites] + [""]
        for t in texts:
            out += [t["module"] or t["module_id"], "-" * 40,
                    t.get("text") or f"[not available: {t.get('error')}]", ""]
        if qs:
            out += ["Study questions", "-" * 40]
            for q in qs:
                out += [f"({q.get('kind','')}) {q.get('q','')}",
                        f"   from {q.get('from','')}", ""]
        out += ["-" * 40, "Sources and terms", "", att]
        return {"ok": True, "text": "\n".join(out), "format": "txt"}
    if fmt == "html":
        rows = "".join(f"<p class=cite>{c['citation']}</p>" for c in cites)
        body = "".join(
            f"<h2>{_html(t['module'] or t['module_id'])}</h2>"
            + (f"<p class=warn>not available: {_html(t['error'])}</p>"
               if t.get("error") else f"<p class=body>{_html(t['text'])}</p>")
            for t in texts)
        if qs:
            body += "<h2>Study questions</h2><ul>"
            for q in qs:
                body += (f"<li><b>{_html(q.get('q',''))}</b> "
                         f"<span class=small>({q.get('kind','')} — "
                         f"{_html(q.get('from',''))})</span></li>")
            body += "</ul>"
        html = _html_page(head, f"{rows}{body}", att)
        return {"ok": True, "text": html, "format": "html"}
    if fmt == "rtf":
        blocks = [{"text": head, "style": "h1"}, {"text": "", "style": "rule"}]
        blocks += [{"text": _strip_md(c["citation"]), "style": "italic"} for c in cites]
        for t in texts:
            blocks.append({"text": t["module"] or t["module_id"], "style": "h2"})
            blocks.append({"text": t.get("text")
                           or f"[not available: {t.get('error')}]",
                           "style": "body"})
        if qs:
            blocks.append({"text": "Study questions", "style": "h2"})
            for q in qs:
                blocks.append({"text": f"({q.get('kind','')}) {q.get('q','')}",
                               "style": "body"})
                blocks.append({"text": f"from {q.get('from','')}", "style": "small"})
        blocks += [{"text": "", "style": "rule"},
                   {"text": "Sources and terms", "style": "h2"},
                   {"text": att, "style": "small"}]
        return {"ok": True, "text": _rtf_doc(blocks), "format": "rtf"}
    if fmt == "pdf":
        doc = pdf.Doc(title=head, subject=f"{head} — exported from G-Bible")
        doc.text(head, font="helvetica-bold", size=17, space_after=2)
        doc.rule()
        for c in cites:
            doc.text(_strip_md(c["citation"]), font="times-italic", size=10,
                     colour=(0.25, 0.25, 0.25), space_after=2)
        for t in texts:
            doc.text(t["module"] or t["module_id"], font="helvetica-bold",
                     size=11, space_before=6, space_after=2)
            doc.text(t.get("text") or f"[not available: {t.get('error')}]",
                     font="times", size=11)
        if qs:
            doc.text("Study questions", font="helvetica-bold", size=12,
                     space_before=8, space_after=2)
            for q in qs:
                doc.text(f"({q.get('kind','')}) {q.get('q','')}", font="times",
                         size=11, indent=12, space_after=1)
                doc.text(f"from {q.get('from','')}", font="helvetica", size=8,
                         colour=(0.4, 0.4, 0.4), indent=24, space_after=4)
        doc.rule()
        doc.text("Sources and terms", font="helvetica-bold", size=9,
                 space_after=2)
        doc.text(att, font="helvetica", size=8, colour=(0.3, 0.3, 0.3),
                 leading=1.25)
        data = doc.build(footer=label)
        return {"ok": True, "binary": data, "format": "pdf",
                "bytes": len(data)}
    if fmt == "pptx":
        pr = pptx.Presentation(title=head, author="G-Bible")
        for t in texts:
            pr.add_slide(t["module"] or t["module_id"],
                         [t.get("text") or f"[not available: {t.get('error')}]",])
        if qs:
            pr.add_slide("Study questions",
                         [f"({q.get('kind','')}) {q.get('q','')}" for q in qs])
        data = pr.build(attribution=att)
        return {"ok": True, "binary": data, "format": "pptx",
                "bytes": len(data)}
    return {"ok": False, "error": f"unknown format '{fmt}'",
            "formats": sorted(FORMATS)}


def notes_document(*, kind: str = "", fmt: str = "md", title: str = "") -> dict:
    """Notes, in a format you can keep."""
    items = notes_mod.listing(kind, limit=100000)
    if not items:
        return {"ok": False, "error": "no notes to export"}
    head = title or ("Notes" if not kind else f"{kind.title()} notes")
    if fmt in ("md", "txt"):
        md = notes_mod.export_markdown(kind)
        # The passage and bibliography exports both end with an attribution
        # block, and the project's own rule is that an export names its terms.
        # The two plain-text formats returned `export_markdown` verbatim, so they
        # were the only exports carrying no statement of what produced them or
        # under what licence -- and Markdown is the format most likely to be
        # pasted somewhere and forgotten about.  The note body is untouched; the
        # block is appended.
        tail = ["", "---", "", "### Produced with G-Bible", "",
                "Your own notes. Scripture and reference texts quoted in them "
                "remain under the licence of whoever wrote them; run an export "
                "from a passage or the Library to see the terms for a given "
                "resource."]
        if fmt == "md":
            return {"ok": True, "text": md.rstrip() + "\n" + "\n".join(tail),
                    "format": "md", "count": len(items)}
        out = [re.sub(r"^#{1,6}\s*", "", ln) for ln in md.splitlines()]
        out += ["", "-" * 40, "", "Produced with G-Bible", "",
                "Your own notes. Scripture and reference texts quoted in them "
                "remain under the licence of whoever wrote them; run an export "
                "from a passage or the Library to see the terms for a given "
                "resource."]
        return {"ok": True, "text": "\n".join(out), "format": "txt",
                "count": len(items)}
    if fmt == "html":
        body = ""
        for n in items:
            when = time.strftime("%Y-%m-%d", time.localtime(n["updated_at"] or 0))
            bits = [when] + ([n["ref_label"]] if n.get("ref_label") else []) \
                + ([", ".join(n["tags"])] if n.get("tags") else [])
            body += (f"<h2>{_html(n['title'] or '(untitled)')}</h2>"
                     f"<p class=meta>{_html(' · '.join(bits))}</p>"
                     f"<p class=body>{_html(n['body'])}</p>")
        return {"ok": True, "text": _html_page(head, body, ""), "format": "html",
                "count": len(items)}
    if fmt == "rtf":
        blocks = [{"text": head, "style": "h1"}, {"text": "", "style": "rule"}]
        for n in items:
            when = time.strftime("%Y-%m-%d", time.localtime(n["updated_at"] or 0))
            blocks.append({"text": n["title"] or "(untitled)", "style": "h2"})
            blocks.append({"text": when + (f"  ·  {n['ref_label']}"
                                           if n.get("ref_label") else ""),
                           "style": "small"})
            blocks.append({"text": n["body"], "style": "body"})
            if n["kind"] == "sermon" and n["meta"].get("passages"):
                blocks.append({"text": "Passages: "
                               + ", ".join(n["meta"]["passages"]),
                               "style": "italic"})
        return {"ok": True, "text": _rtf_doc(blocks), "format": "rtf",
                "count": len(items)}
    if fmt == "pdf":
        doc = pdf.Doc(title=head, subject="Notes exported from G-Bible")
        doc.text(head, font="helvetica-bold", size=17, space_after=2)
        doc.rule()
        for n in items:
            when = time.strftime("%Y-%m-%d", time.localtime(n["updated_at"] or 0))
            doc.text(n["title"] or "(untitled)", font="helvetica-bold", size=12,
                     space_before=8, space_after=1)
            meta = [when] + ([n["ref_label"]] if n.get("ref_label") else [])
            doc.text(" · ".join(meta), font="helvetica", size=8.5,
                     colour=(0.4, 0.4, 0.4), space_after=3)
            if n["body"]:
                doc.text(n["body"], font="times", size=11)
            if n["kind"] == "sermon" and n["meta"].get("passages"):
                doc.text("Passages: " + ", ".join(n["meta"]["passages"]),
                         font="times-italic", size=10, space_before=2)
        data = doc.build(footer=head)
        return {"ok": True, "binary": data, "format": "pdf",
                "count": len(items), "bytes": len(data),
                "skipped_scripts": doc.skipped_scripts}
    if fmt == "pptx":
        pr = pptx.Presentation(title=head, author="G-Bible")
        for n in items:
            when = time.strftime("%Y-%m-%d", time.localtime(n["updated_at"] or 0))
            body = [n["body"]] if n["body"] else []
            meta = [when] + ([n["ref_label"]] if n.get("ref_label") else [])
            pr.add_slide(n["title"] or "(untitled)", [n["body"]] if n["body"] else [])
        data = pr.build(attribution="Your own notes. Scripture and reference "
                                    "texts quoted in them remain under the "
                                    "licence of whoever wrote them.")
        return {"ok": True, "binary": data, "format": "pptx",
                "count": len(items), "bytes": len(data)}
    return {"ok": False, "error": f"unknown format '{fmt}'",
            "formats": sorted(FORMATS)}


def bibliography_document(module_ids: list[str], *, style: str = "sbl",
                          fmt: str = "md", title: str = "") -> dict:
    """A bibliography, sorted, with its own gaps stated.

    The report of how many entries are missing fields is part of the output
    rather than a warning in the interface, because a bibliography is the one
    document a reader checks, and an entry that is silently half-empty there is
    the failure mode that costs someone a mark.
    """
    bib = citation.bibliography(module_ids, style=style, full=True)
    if not bib.get("entries"):
        return {"ok": False, "error": "nothing to cite"}
    head = title or "Bibliography"
    gap = ""
    if bib["flagged"]:
        gap = (f"{len(bib['flagged'])} of {bib['count']} entries are missing "
               "fields. They are marked [incomplete] rather than filled in with "
               "a guess. Open each and supply what is known.")
    if fmt == "md":
        out = [f"# {head}", ""]
        if gap:
            out += [f"> {gap}", ""]
        out += [_md(c["citation"]) + ("" if c["complete"] else "  [incomplete]")
                for c in bib["entries"]]
        out += ["", "---", "", f"Style: {citation.STYLES[style]}.", "",
                "### Sources and terms", "", attribution_block(module_ids), ""]
        return {"ok": True, "text": "\n".join(out), "format": "md",
                "count": bib["count"], "flagged": len(bib["flagged"])}
    if fmt == "txt":
        out = [head, "=" * len(head), ""]
        if gap:
            out += [gap, ""]
        out += [_strip_md(c["citation"]) + ("" if c["complete"] else "  [incomplete]")
                for c in bib["entries"]]
        out += ["", f"Style: {citation.STYLES[style]}", "",
                "Sources and terms", "", attribution_block(module_ids)]
        return {"ok": True, "text": "\n".join(out), "format": "txt",
                "count": bib["count"], "flagged": len(bib["flagged"])}
    if fmt == "html":
        body = (f"<p class=meta>{_html(citation.STYLES[style])}</p>")
        if gap:
            body += f"<p class=warn>{_html(gap)}</p>"
        for c in bib["entries"]:
            mark = "" if c["complete"] else \
                " <span class=warn>[incomplete]</span>"
            body += f'<p class="entry">{_md_html(c["citation"])}{mark}</p>'
        body += ("<hr><h2>Sources and terms</h2><p class=small>"
                 + _html(attribution_block(module_ids)) + "</p>")
        return {"ok": True, "text": _html_page(head, body, ""), "format": "html",
                "count": bib["count"], "flagged": len(bib["flagged"])}
    if fmt == "rtf":
        blocks = [{"text": head, "style": "h1"}, {"text": "", "style": "rule"},
                  {"text": citation.STYLES[style], "style": "small"}]
        if gap:
            blocks.append({"text": gap, "style": "small"})
        for c in bib["entries"]:
            blocks.append({"text": _strip_md(c["citation"])
                           + ("" if c["complete"] else "  [incomplete]"),
                           "style": "body"})
        blocks += [{"text": "", "style": "rule"},
                   {"text": "Sources and terms", "style": "h2"},
                   {"text": attribution_block(module_ids), "style": "small"}]
        return {"ok": True, "text": _rtf_doc(blocks), "format": "rtf",
                "count": bib["count"], "flagged": len(bib["flagged"])}
    if fmt == "pdf":
        doc = pdf.Doc(title=head, subject=f"{citation.STYLES[style]} bibliography")
        doc.text(head, font="helvetica-bold", size=17, space_after=1)
        doc.text(citation.STYLES[style], font="helvetica", size=9,
                 colour=(0.4, 0.4, 0.4), space_after=4)
        if gap:
            doc.text(gap, font="helvetica", size=8.5, colour=(0.55, 0.2, 0.1),
                     space_after=5)
        for c in bib["entries"]:
            italic = "<i>" in c["citation"] or "*" in c["citation"]
            doc.text(_strip_md(c["citation"]), font="times", size=10.5,
                     indent=12, space_after=3, leading=1.25)
            if not c["complete"]:
                doc.text("incomplete — missing " + ", ".join(c["missing"]),
                         font="helvetica", size=7.5, colour=(0.6, 0.25, 0.1),
                         indent=24, space_after=4)
        doc.rule()
        doc.text("Sources and terms", font="helvetica-bold", size=9,
                 space_after=2)
        doc.text(attribution_block(module_ids), font="helvetica", size=8,
                 colour=(0.3, 0.3, 0.3), leading=1.25)
        data = doc.build(footer=citation.STYLES[style])
        return {"ok": True, "binary": data, "format": "pdf",
                "count": bib["count"], "flagged": len(bib["flagged"]),
                "bytes": len(data)}
    if fmt == "pptx":
        pr = pptx.Presentation(title=head, author="G-Bible")
        for c in bib["entries"]:
            pr.add_slide(_strip_md(c["citation"]),
                         ["" if c["complete"] else "incomplete — missing "
                          + ", ".join(c["missing"])])
        data = pr.build(attribution=attribution_block(module_ids))
        return {"ok": True, "binary": data, "format": "pptx",
                "count": bib["count"], "flagged": len(bib["flagged"]),
                "bytes": len(data)}
    if fmt in ("bib", "ris"):
        fn = citation.bibtex if fmt == "bib" else citation.ris
        r = fn(module_ids)
        return {"ok": True, "text": r["bibtex"] if fmt == "bib" else r["ris"],
                "format": fmt, "count": r["entries"],
                "flagged": len(r.get("missing") or [])}
    if fmt == "csv":
        return {"ok": True, "text": citation.csv(module_ids)["csv"], "format": "csv",
                "count": len(module_ids)}
    return {"ok": False, "error": f"unknown format '{fmt}'",
            "formats": sorted(FORMATS)}


# ---------------------------------------------------------------- catalog ---

#: The columns, in print order.  Group first because a catalogue is read by
#: shape -- "what Greek do I have" -- before it is read by title.
CATALOG_COLUMNS = (
    ("title", "Title"), ("type", "Kind"), ("abbrev", "Abbrev."),
    ("author", "Author"), ("year", "Year"), ("lang", "Language"),
    ("source", "Source"), ("version", "Version"), ("license", "Licence"),
    ("size", "Size"), ("modules", "Units"),
)

CATALOG_FORMATS = ("pdf", "html", "csv", "md", "txt")


def catalog_rows(*, group: str = "", include_uninstalled: bool = False
                 ) -> list[dict]:
    """Everything installed, in catalogue order.

    Counted off the module table rather than off a passed-in list, because a
    catalogue of a selection is a bibliography and already exists.
    """
    from . import library, taxonomy
    conn = db.connect()
    sql = ("SELECT id,name,abbrev,type,author,year,lang,lang_name,source,"
           "source_name,version,license,size_bytes,entries FROM module "
           "WHERE 1=1")
    a: list = []
    if not include_uninstalled:
        sql += " AND installed_at>0"
    order = {"kind": "type, name", "lang": "lang, name",
             "source": "source_name, name", "author": "author, name",
             "title": "name"}.get(group, "type, name")
    sql += f" ORDER BY {order}"
    rows = []
    for r in conn.execute(sql, a).fetchall():
        m = library.get(r["id"])
        rows.append({
            "id": r["id"],
            "title": r["name"] or "",
            "type": (taxonomy.TYPE_BY_ID[r["type"]].label
                     if m and m.type in taxonomy.TYPE_BY_ID else (r["type"] or "")),
            "abbrev": r["abbrev"] or "",
            "author": r["author"] or (m.author if m else "") or "",
            "year": r["year"] or "",
            "lang": (r["lang_name"] or r["lang"] or ""),
            "source": r["source_name"] or r["source"] or "",
            "version": r["version"] or "",
            "license": r["license"] or "",
            "size": store.human_size(r["size_bytes"] or 0)
            if r["size_bytes"] else "",
            "modules": r["entries"] or 0,
        })
    return rows


def catalog_document(*, fmt: str = "pdf", group: str = "", title: str = "",
                     detail: bool = True, filters: dict | None = None) -> dict:
    """The whole library as a printed catalogue.

    Grouped by kind, then language, then source -- the order in which a reader
    asks the question "what do I actually have".  Every resource carries its
    licence, because a catalogue is the document you hand to somebody to prove
    what you are permitted to use.

    Unlike the bibliography this document can be complete without being cited:
    it is a list of holdings, so a row with no author and no year is reported
    as such rather than omitted.
    """
    rows = catalog_rows(group=group)
    f = filters or {}
    for key in ("type", "lang", "source"):
        want = (f.get(key) or "").strip()
        if want:
            rows = [r for r in rows
                    if want.lower() in (r.get(key) or "").lower()]
    if not rows:
        return {"ok": False, "error": "no resources match"}

    heads = {"type": "by kind", "lang": "by language",
             "source": "by source", "author": "by author"}.get(group, "by kind")
    head = title or f"Library catalogue"
    total_size = sum(r.get("modules") or 0 for r in rows)
    kinds = len({r["type"] for r in rows})
    summary = (f"{len(rows)} resource{'' if len(rows) == 1 else 's'} of "
               f"{kinds} kind{'' if kinds == 1 else 's'}, {total_size:,} units.")
    blank = sum(1 for r in rows if not (r["author"] or "").strip())

    cols = [c for c in CATALOG_COLUMNS if detail or c[0] in ("title", "type", "abbrev")]

    def _cells(r: dict) -> str:
        return " | ".join(str(r.get(k, "")).replace("|", "/") for k, _ in cols)

    note = ("" if not blank else
            f"{blank} have no author recorded. That is what the source said; "
            f"nothing has been guessed.")

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([label for _, label in cols])
        for r in rows:
            w.writerow([r.get(k, "") for k, _ in cols])
        return {"ok": True, "text": buf.getvalue(), "format": "csv",
                "count": len(rows), "blank": blank}

    if fmt == "md":
        out = [f"# {head}", "", summary, "",
               "| " + " | ".join(label for _, label in cols) + " |",
               "|" + "|".join("---" for _ in cols) + "|"]
        for r in rows:
            out.append("| " + _cells(r) + " |")
        if note:
            out += ["", f"> {note}"]
        return {"ok": True, "text": "\n".join(out), "format": "md",
                "count": len(rows), "blank": blank}

    if fmt == "txt":
        w1 = max(len(r["title"]) for r in rows)
        w2 = max(len(r["type"]) for r in rows)
        out = [head, "=" * len(head), "", summary, ""]
        for r in rows:
            out.append(f"{r['title'][:w1]:<{w1}}  {r['type'][:w2]:<{w2}}  "
                       + "  ".join(f"{r.get(k, '')}" for k, _ in cols[3:]))
        if note:
            out += ["", note]
        return {"ok": True, "text": "\n".join(out), "format": "txt",
                "count": len(rows), "blank": blank}

    if fmt == "html":
        body = f"<p class=meta>{_html(summary)} &middot; {heads}</p>"
        if note:
            body += f'<p class="warn">{_html(note)}</p>'
        body += "<table><tr>" + "".join(
            f"<th>{_html(label)}</th>" for _, label in cols) + "</tr>"
        for r in rows:
            body += "<tr>" + "".join(
                f"<td>{_html(str(r.get(k, '')))}</td>" for k, _ in cols) + "</tr>"
        body += "</table>"
        return {"ok": True, "text": _html_page(head, body, ""), "format": "html",
                "count": len(rows), "blank": blank}

    if fmt == "pdf":
        doc = pdf.Doc(title=head, subject=f"{summary} {heads}")
        doc.text(head, font="helvetica-bold", size=17, space_after=1)
        doc.text(summary + f"  ·  {heads}", font="helvetica", size=9,
                 colour=(0.4, 0.4, 0.4), space_after=3)
        if note:
            doc.text(note, font="helvetica", size=8.5, colour=(0.55, 0.2, 0.1),
                     space_after=5)
        # A catalogue is scanned, not read, so it is set small and in a
        # monospaced face where the columns line up without a table.
        for r in rows:
            line = _cells(r)
            for part in doc.wrap(line, "courier", 7.2)[:2]:
                doc.text(part, font="courier", size=7.2, leading=1.2,
                         space_after=0)
            doc.text("", size=3.5, leading=1.0, space_after=0)
        data = doc.build(footer=summary)
        return {"ok": True, "binary": data, "format": "pdf",
                "count": len(rows), "blank": blank, "bytes": len(data)}

    return {"ok": False, "error": f"unknown format '{fmt}'",
            "formats": list(CATALOG_FORMATS)}


def catalog_summary() -> dict:
    """What the catalogue dialog needs before it is generated."""
    rows = catalog_rows()
    by_type: dict[str, int] = {}
    by_lang: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        by_lang[r["lang"] or "—"] = by_lang.get(r["lang"] or "—", 0) + 1
        by_source[r["source"] or "—"] = by_source.get(r["source"] or "—", 0) + 1
    return {"ok": True, "total": len(rows),
            "by_type": [{"label": k, "n": v} for k, v in
                        sorted(by_type.items(), key=lambda x: -x[1])],
            "by_lang": [{"label": k, "n": v} for k, v in
                        sorted(by_lang.items(), key=lambda x: -x[1])],
            "by_source": [{"label": k, "n": v} for k, v in
                          sorted(by_source.items(), key=lambda x: -x[1])],
            "blank_author": sum(1 for r in rows
                                if not (r["author"] or "").strip()),
            "formats": list(CATALOG_FORMATS),
            "groups": ["type", "lang", "source", "author"]}


# ------------------------------------------------------------------ HTML ---

_HTML_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _html(s: str) -> str:
    out = []
    for ch in s or "":
        if ch in _HTML_ESC:
            out.append(_HTML_ESC[ch])
        elif ch == "\n":
            out.append("<br>")
        else:
            out.append(ch)
    return "".join(out)


def _md_html(s: str) -> str:
    """Render the *italic* markers as real italics, after escaping."""
    parts = _html(s).split("*")
    return "".join(p if i % 2 == 0 else f"<i>{p}</i>"
                   for i, p in enumerate(parts))


_HTML_CSS = """
body{font:15px/1.5 Georgia,'Times New Roman',serif;max-width:44em;
 margin:3em auto;padding:0 1.5em;color:#1a1a1a;background:#fff}
h1{font-size:1.7em;margin:0 0 .2em}h2{font-size:1.15em;margin:1.6em 0 .3em}
p{margin:.7em 0}p.body{text-align:left}
p.cite{font-style:italic;color:#444;margin:.15em 0}
p.entry{padding-left:1.4em;text-indent:-1.4em}
p.meta,p.small{font-size:.85em;color:#555}
p.warn{color:#8a2b12;font-size:.85em}
hr{border:0;border-top:1px solid #ccc;margin:2em 0}
@media print{body{max-width:none;margin:0}h2{page-break-after:avoid}}
"""


def _html_page(title: str, body: str, attribution: str) -> str:
    att = f"<hr><h2>Sources and terms</h2><p class=small>{_html(attribution)}</p>" \
        if attribution else ""
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<title>{_html(title)}</title><style>{_HTML_CSS}</style></head>"
            f"<body><h1>{_html(title)}</h1>{body}{att}"
            f"<p class=small>Produced with G-Bible, {_stamp()}.</p>"
            f"</body></html>")


# --------------------------------------------------------------- printing --

def print_stylesheet() -> str:
    """The CSS that makes printing this app's output look like a document.

    Kept in one place so the browser's print path and the exported HTML agree
    with each other instead of drifting apart.
    """
    return """
@media print {
  @page { margin: 18mm 16mm; }
  html, body { background: #fff !important; }
  body { font: 11pt/1.45 Georgia, 'Times New Roman', serif; color: #000; }
  #topbar, .sidebar, .toolbar, .pane-tabs, .modal-foot, .no-print,
  #tiles-controls, .facet-bar, button, .ctxmenu { display: none !important; }
  .tile, .pane { border: 0 !important; box-shadow: none !important;
    page-break-inside: avoid; }
  .pane-body { overflow: visible !important; height: auto !important;
    max-height: none !important; }
  h1, h2, h3 { page-break-after: avoid; }
  a { color: #000; text-decoration: none; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: .8em;
    color: #555; word-break: break-all; }
  .print-only { display: block !important; }
  .cite, .st-cite { font-style: italic; }
  .pg-name, .pg-place, .st-note, .note { page-break-inside: avoid; }
  table { page-break-inside: avoid; }
  img, svg { max-width: 100% !important; page-break-inside: avoid; }
  pre, code { white-space: pre-wrap; word-wrap: break-word; }
  mark { background: none !important; }
}
.print-only { display: none; }
"""