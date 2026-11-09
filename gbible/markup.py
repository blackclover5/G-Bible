"""Markup: every input format is normalised into one segment stream.

A `Segment` is the app's atom of text.  Formats (OSIS, ThML/TEI, USFM, HTML,
plain text) are all parsed into a list of segments, and everything downstream --
rendering to the UI, extracting plain text for search, emitting Strong's /
lemma / morphology markers -- works off that one representation.

This is deliberate.  The alternative (a renderer per format) multiplies the
cross-linking work by the number of formats, and the whole point of the linking
engine is that a link written once works in every pane.
"""

from __future__ import annotations

import html as _html
import functools
import re
from typing import Iterable, NamedTuple


class Seg(NamedTuple):
    kind: str          # text|strongs|note|xref|heading|title|add|alt|red|name|img|break|para
    text: str = ""
    value: str = ""    # Strong's number, morph code, target key, note id
    lemma: str = ""
    attrs: dict = {}

    def is_text(self) -> bool:
        return self.kind in ("text", "add", "alt", "red", "name", "title", "strongs")


# --------------------------------------------------------------------------
# Entity / text normalisation
# --------------------------------------------------------------------------

_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": "\u00a0", "ndash": "\u2013", "mdash": "\u2014",
    "hellip": "\u2026", "lsquo": "\u2018", "rsquo": "\u2019",
    "ldquo": "\u201c", "rdquo": "\u201d", "deg": "\u00b0",
    "middot": "\u00b7", "bull": "\u2022", "dagger": "\u2020",
    "sect": "\u00a7", "para": "\u00b6", "copy": "\u00a9",
    "reg": "\u00ae", "trade": "\u2122", "prime": "\u2032",
    "Prime": "\u2033", "larr": "\u2190", "rarr": "\u2192",
    "harr": "\u2194", "times": "\u00d7", "divide": "\u00f7",
    "minus": "\u2212", "plusmn": "\u00b1", "frac12": "\u00bd",
    "sup1": "\u00b9", "sup2": "\u00b2", "sup3": "\u00b3", "sup4": "\u2074",
    "eacute": "\u00e9", "egrave": "\u00e8", "ecirc": "\u00ea", "agrave": "\u00e0",
    "ccedil": "\u00e7", "uuml": "\u00fc", "ouml": "\u00f6", "auml": "\u00e4",
    "szlig": "\u00df", "ntilde": "\u00f1", "aacute": "\u00e1", "iacute": "\u00ed",
    "oacute": "\u00f3", "uacute": "\u00fa", "aring": "\u00e5", "oslash": "\u00f8",
    "aelig": "\u00e6", "curren": "\u00a4", "percnt": "%", "vert": "|",
    "sol": "/", "commat": "@", "lowbar": "_", "num": "#", "dollar": "$",
    "excl": "!", "quest": "?", "lpar": "(", "rpar": ")", "ast": "*",
    "period": ".", "comma": ",", "semi": ";", "colon": ":",
    "zwj": "\u200d", "zwnj": "\u200c", "shy": "\u00ad",
}

_ENTITY_RE = re.compile(r"&(#x?[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")


def unescape(text: str) -> str:
    if "&" not in text:
        return text

    def sub(m: re.Match) -> str:
        ent = m.group(1)
        if ent.startswith("#"):
            try:
                cp = int(ent[2:], 16) if ent[1] in "xX" else int(ent[1:])
                return chr(cp)
            except (ValueError, OverflowError):
                return m.group(0)
        v = _ENTITIES.get(ent)
        if v is not None:
            return v
        v2 = _ENTITIES.get(ent.lower())
        if v2 is not None:
            return v2
        if ent in ("gt", "GT", "Gt", "lt", "LT", "Lt", "amp", "AMP", "Amp"):
            return _ENTITIES[ent.lower()]
        return m.group(0)

    return _ENTITY_RE.sub(sub, text)


def _strip_tags(s: str) -> str:
    """Remove tags and resolve entities, leaving displayable text."""
    return unescape(re.sub(r"<[^>]+>", "", s or ""))


def collapse(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", text or "")


# --------------------------------------------------------------------------
# MediaWiki templates
# --------------------------------------------------------------------------

#: Templates that carry no article text at all.  A table of contents, a
#: category marker, a maintenance banner: the reader wants the prose, not the
#: apparatus someone used to organise the page it came from.
_DROP_TEMPLATES = frozenset({
    # "auxtoc", not "autotoc": the Catholic Encyclopedia's is `{{AuxTOC|`, and
    # a dropped TOC is 7,000 characters of volume listing that the reader did
    # not ask for and cannot use.
    "auxtoc", "autotoc", "toc", "aux", "hr", "clear", "import enwiki",
    "sccategory", "textquality", "pp-protected", "about", "coord",
    "notability", "use dmy dates", "use mdy dates", "short description",
    "portal", "wikt", "wikispecies", "wikiquote", "wikinews", "references",
    "further reading", "external links", "see also",
})

#: Named parameters that are page furniture, not article text.  A value that
#: looks like one of these -- short, and with no sentence in it -- is dropped.
#: A value that does *not* look like furniture is kept whatever its key, because
#: the Catholic Encyclopedia importer lost the `|` that separated its metadata
#: from its text and the article body arrived glued to the `wikipedia`
#: parameter.  Dropping that parameter on its key alone deletes the article.
_FURNITURE = frozenset({
    "contributor", "article", "volume", "wikipedia", "page", "title",
    "author", "edition", "year", "lang", "sort", "sortkey", "short",
    "short description", "image", "align", "width", "date", "month",
    "year2", "isbn", "doi", "translator", "editor", "publisher", "place",
    "chapter", "verse", "section", "column", "sub", "sup",
})

#: Named parameters whose value *is* the text, whatever it looks like.
_TEXT_KEYS = frozenset({"text", "content", "body", "1"})

_NAMED = re.compile(r"^[A-Za-z][\w \-]*\s*=")

#: Templates whose first positional argument is a size or a section number, not
#: content.  Proofreading apparatus on Wikisource: `{{fs|90%|...}}` is text set
#: at 90%, `{{GHGpar-heading|7|...}}` is a numbered heading, and
#: `{{GHGmargin-letter|3|t}}` points at the letter *t* in the margin.
_NUMBERED_TEMPLATES = frozenset({
    "fs", "ghgpar-heading", "ghgmargin-letter", "ghgmargin-letter-fmt",
})

#: Templates that are a block in their own right rather than something wrapped
#: round a word.  Their text is a heading, and heading needs either side of it:
#: `{{larger|HEBREW GRAMMAR}}` sits on its own line, so without the spaces the
#: grammar opened "HEBREW GRAMMARINTRODUCTION The Semitic Languages".  Inline
#: templates like `{{sc|JERUSALEM}}` must *not* get them -- a space inside a word
#: is worse than a missing one.
_BLOCK_TEMPLATES = frozenset({
    "larger", "smaller block/s", "smaller block", "fine block", "center",
    "ghgpar-heading", "fs", "fs90", "fs85", "font-size90", "font-size85",
    "font-size110", "font-size120", "poem", "verse", "signature",
})
_TMPL = re.compile(r"\{\{([^{}]*)\}\}")
#: A template the importer never closed: runs to the end of the text.
_OPEN = re.compile(r"\{\{([^{}]*)\s*$")
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_STRAY = re.compile(r"\{\{|\}\}")


#: A cheap "is there anything here at all?" test.  This runs on every article
#: in the library, most of which have nothing to do, so it must not cost more
#: than a substring test: `"<" in text` rejects almost everything instantly, and
#: only the survivors pay for a regex.  The alternatives were both worse -- an
#: unconditional pass costs a `collapse()` over 1.18 million units, and widening
#: the substring test to `"<"` alone catches any verse containing a comparison
#: sign and sends it through the whole pipeline.
_PROOF_TRIGGER = re.compile(
    r"<(?:noinclude|references|pagequality|section|!--|/?div|p|br|span|sup|"
    r"li|ul|h[1-6]|blockquote|center|figcaption|hr|table)\b", re.I)


def strip_wikitext(text: str) -> str:
    """Unwrap MediaWiki markup left in Wikisource-derived text.

    Wikisource stores a page as wikitext and the article is usually *inside* a
    template rather than beside it.  The Catholic Encyclopedia's importer kept
    that wrapper, so every one of its 9,935 articles opened, in the reader's
    pane, with the literal characters `{{CE13| contributor = ...`, and
    Gesenius' grammar was the same in all 173 sections.  So the fix is not to
    delete the braces -- that deletes the article, because the article is the
    template's argument -- but to read the template the way Wikisource does and
    keep what it carries:

      * positional arguments are kept;
      * a named argument in a *text* key is kept whatever it looks like;
      * a named argument in a *furniture* key is dropped when it looks like
        furniture, and kept when it does not -- see `_FURNITURE`;
      * presentation templates keep their content and lose their styling;
      * navigational and maintenance templates are dropped whole;
      * `[[A|B]]` becomes B and `[[A]]` becomes A;
      * braces left unbalanced by the importer are removed rather than shown.

    Nested templates are unwrapped inside out and the pass repeats until there
    is nothing left to expand, so `{{CE13|...{{sc|x}}...}}` comes out right.  The
    cap is a guard against the braces that do not balance, which real Wikisource
    has.

    **Cached, because this runs on every article the app renders.**  The search
    check that compares the positional index against the text path reads a very
    large number of units, and the 9,935 that carry templates are the Catholic
    Encyclopedia; without a cache this doubled that check's runtime, from 439s
    to 974s.  Measured at 3.6ms an article, and only on template-bearing text --
    the other 1.17 million units return at the `in` test above and cost nothing.

    The bound is sized to the working set rather than picked round.  A cache
    smaller than the ~10,100 template-bearing units *thrash*: two full passes
    over the encyclopedia measured the same 45s cold and warm, which is a cache
    that costs memory and buys nothing.  16,384 covers the whole set with room
    for a second one, at roughly 45MB of article text -- which is a fair trade
    for halving a check the project actually runs.
    """
    if not text or not _has_markup(text):
        return text or ""
    return _strip_cached(text)


def strip_wikitext_uncached(text: str) -> str:
    """`strip_wikitext` without its cache.

    For callers that already hold a cheap identity for the text -- the reader,
    which knows the module and the unit key -- and would otherwise pay to hash
    several kilobytes of article on every render only to compare strings.  See
    `library._segs_of`, which caches on `(module id, unit key)` instead.
    """
    if not text or not _has_markup(text):
        return text or ""
    return _strip_uncached(text)


def _has_markup(text: str) -> bool:
    """Is there anything in here for this function to do?"""
    if "{{" in text or "[[" in text:
        return True
    return "<" in text and bool(_PROOF_TRIGGER.search(text))


@functools.lru_cache(maxsize=16384)
def _strip_cached(text: str) -> str:
    return _strip_uncached(text)


def _strip_uncached(text: str) -> str:
    out = text
    for _ in range(6):
        nxt = _TMPL.sub(lambda m: _expand_template(m.group(1)), out)
        nxt = _LINK.sub(lambda m: _expand_link(m.group(1)), nxt)
        nxt = collapse(unescape(nxt))
        if nxt == out:
            break
        out = nxt
        # Stop as soon as there is nothing left to expand, rather than running
        # out the six passes.  Most articles are one nested level deep and
        # needed two passes; the other four were re-scanning clean text.
        if "{{" not in nxt and "[[" not in nxt:
            break
    # An unterminated template.  The importer dropped the closing braces of the
    # outer wrapper -- the Catholic Encyclopedia's articles open `{{CE13|...`
    # with four braces and close two -- so no `{{...}}` can ever match and the
    # loop above leaves the template sitting there as literal text.  Whatever is
    # still open runs to the end of the string, so it is matched that way and
    # expanded like any other.
    for _ in range(4):
        if "{{" not in out:
            break
        nxt = _OPEN.sub(lambda m: _expand_template(m.group(1)), out)
        if nxt == out:
            break
        out = nxt
    # Whatever braces survive are the importer's, not the reader's.  Dropping
    # them is safe because by this point every well-formed template has already
    # been expanded, so a brace that is still here was never going to become
    # anything.
    out = _STRAY.sub("", out).strip()
    out = _strip_proofreading(out)

    # And the last line of defence.  Some articles cannot be unwrapped safely:
    # the importer mangled `{{sc|Dacier, a French philologist}}` into
    # `{{sc, a French philologist}}`, which leaves the braces unbalanced with
    # the malformed one *inside* the wrapper, and unwrapping that returns 45
    # characters where there were 4,367.  Showing a reader the braces is an
    # embarrassment; showing them 45 characters instead of an article is a
    # lie.  So when unwrapping would throw away more than half the text, the
    # text is kept as it was and nothing is claimed.
    if len(text) > 200 and len(out) * 2 < len(text):
        return collapse(unescape(text)).strip()
    return out


def _looks_like_furniture(value: str) -> bool:
    """Short, and with no sentence in it."""
    v = (value or "").strip()
    if not v or len(v) > 120:
        return False
    return not re.search(r"[.;:!?]\s|\.\s*$", v)


def _split_args(body: str) -> tuple[str, list[tuple[bool, str, str]]]:
    """`a|b=k|c` -> (`a`, [(is_named, key, value)]).

    Split on the top-level `|` only: an argument may itself contain braces and
    brackets, and splitting inside those throws the structure away.
    """
    parts, buf, depth_b, depth_s = [], [], 0, 0
    for ch in body:
        if ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
        elif ch == "[":
            depth_s += 1
        elif ch == "]":
            depth_s -= 1
        if ch == "|" and depth_b <= 0 and depth_s <= 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    name = parts[0].strip().lower() if parts else ""
    out: list[tuple[bool, str, str]] = []
    for i, p in enumerate(parts[1:]):
        m = _NAMED.match(p.strip())
        if m:
            # `m.end()` covers the `=`, so the key is everything before it with
            # the sign stripped -- and it must be stripped, or "contributor ="
            # is looked up in the furniture set, misses, and the contributor's
            # name is printed at the top of the article.
            out.append((True, p.strip()[:m.end()].rstrip("= \t").lower(),
                        p.strip()[m.end():]))
        else:
            out.append((False, str(i + 1), p))
    return name, out


def _expand_template(body: str) -> str:
    name, args = _split_args(body)
    if not name:
        return ""
    # No `|` anywhere means this was never a template call -- it is prose that
    # happens to contain braces, or a template the importer truncated.  It is
    # returned as it stands: expanding it would delete everything after the
    # brace, which is how "Before {{broken and after" became "Before".
    if not args and ("|" not in body or " " in name):
        return body
    if name in _DROP_TEMPLATES:
        return ""
    if name == "ghgbible-ref":
        return _bible_ref(args)
    if name == "ghgpar":
        pos = [v for _n, _k, v in args if not _n]
        if len(pos) >= 2:
            return f"§{pos[0].strip()} {pos[1].strip()}"
        return "§" + " ".join(v.strip() for v in pos)
    # `ghgpar-heading` is in both sets -- it drops a number *and* is a block --
    # so the block answer is known before the numbered branch is taken.
    block_pre = name in _BLOCK_TEMPLATES
    if name in _NUMBERED_TEMPLATES:
        # `{{fs|90%|text}}`, `{{GHGpar-heading|3|The Hebrew Language}}`,
        # `{{GHGmargin-letter|2|t}}`: the first argument is a size or a section
        # number and belongs to the page, not the sentence.  Kept, it reads
        # "90%B. Stade, Lehrb..." -- a percentage welded to a bibliography.
        # The rest of the arguments are the content and are kept.
        kept = [v for _n, _k, v in args[1:]]
        body = "".join(kept)
        return f" {body} " if block_pre else body
    block = name in _BLOCK_TEMPLATES
    keep: list[str] = []
    #: The same list with the page furniture also removed.  That is the normal
    #: answer, because a contributor's name is not part of the article.  But if
    #: it comes out empty then what was being called furniture *was* the
    #: article -- a short body with no full stop in it reads exactly like a
    #: contributor's name -- and the fuller list is used instead.  Deleting an
    #: article is the one outcome this whole function must never have, so the
    #: empty case is the one that decides which list wins.
    lean: list[str] = []
    named = {k: v for is_named, k, v in args if is_named}
    for is_named, key, value in args:
        if not is_named:
            keep.append(value)
            lean.append(value)
            continue
        if key in _TEXT_KEYS:
            keep.append(value)
            lean.append(value)
            continue
        if key in _FURNITURE:
            if _looks_like_furniture(value):
                keep.append(value)
                continue
            # The importer lost the `|` out of `[[Some Page|Aarhus]]`, so the
            # link's target and its label arrived glued together and the
            # article body came after them attached to the `wikipedia`
            # parameter.  The duplicated title is recoverable: it is the
            # `article` value, and it appears at the start of a run that
            # contains no sentence punctuation.
            if key == "wikipedia":
                value = _drop_glued_title(value, named.get("article", ""))
            keep.append(value)
            lean.append(value)
            continue
        keep.append(value)
        lean.append(value)
    out_text = "".join(lean) if "".join(lean).strip() else "".join(keep)
    return f" {out_text} " if block else out_text


def _drop_glued_title(value: str, article: str) -> str:
    """`Ancient See of AarhusAarhus (Arusia), in Denmark` -> `Aarhus (Arusia)...`."""
    art = (article or "").strip()
    if not art:
        return value
    at = value.find(art)
    if at <= 0:
        return value
    prefix = value[:at]
    if re.search(r"[.;:!?]", prefix):
        return value                     # real prose before it; leave it alone
    rest = value[at:]
    # The link's *target* ended with the article name too -- "[[Ancient See of
    # Aarhus|Aarhus]]" -- so after taking the body at the right place the name
    # is still doubled at the front.  One more step, and only when the second
    # copy is glued straight onto the first: a space or comma after it means it
    # is the article genuinely repeating itself, which is real text.
    if rest.startswith(art) and len(rest) > len(art):
        nxt = rest[len(art):]
        if nxt[:1].isalnum():
            rest = nxt
    return rest


def _bible_ref(args: list[tuple[bool, str, str]]) -> str:
    """`{{GHGbible-ref|book=Is|chapter=13|verse=19}}` -> `Is 13:19`."""
    got = {k: v.strip() for _n, k, v in args if _n}
    book = got.get("book") or ""
    ch = got.get("chapter") or ""
    vs = got.get("verse") or ""
    if book and ch:
        return f"{book} {ch}" + (f":{vs}" if vs else "")
    if book:
        return book
    # No usable keys: whatever was passed positionally is better than nothing.
    return " ".join(v.strip() for _n, _k, v in args if v.strip())


def _expand_link(body: str) -> str:
    parts = body.split("|")
    return parts[-1].strip() if len(parts) > 1 else parts[0].strip()


# --------------------------------------------------------------------------
# Proofreading markup
# --------------------------------------------------------------------------

#: Elements whose *contents* are apparatus, not article.  A `<references>` is
#: the generated list of footnotes, and `<noinclude>` is the part of a page that
#: is documentation for transcribers -- "pagequality 4, user
#: Kathleen.wright5" is Wikisource's own editorial metadata, and it was
#: appearing at the top of every section of the grammar.
#:
#: `<ref>` is deliberately **not** here.  Its contents are the footnote text, and
#: in the grammar those are the references themselves -- "B. Stade, Lehrb. der
#: hebr. Gramm., Lpz. 1879, § 2 ff." -- so removing them deletes the
#: bibliography from every section.  Their tags go with the general tag strip
#: below and the text stays.
_PROOF_DROP = re.compile(
    r"<(noinclude|references|templatestyles)\b[^>]*>.*?</\1\s*>"
    r"|<(noinclude|references)\b[^>]*/>"
    r"|<pagequality\b[^>]*/?>|<section\b[^>]*/?>",
    re.I | re.S)

#: `<!-- proofread: something -->`
_PROOF_COMMENT = re.compile(r"<!--.*?-->", re.S)

#: Block-level wrappers become a **space**, not nothing.  The grammar sets each
#: page heading in its own centred `<div>`, and removing those tags without a
#: space welded the words together: "HEBREW GRAMMARINTRODUCTION The Semitic
#: Languages in General".  Inline wrappers are the opposite case -- `<sup>` round
#: a footnote numeral wants no space -- so the two are handled separately.
_PROOF_BLOCK = re.compile(
    r"</?(?:div|p|br|li|ul|ol|tr|td|th|h[1-6]|blockquote|section|center|"
    r"figcaption|hr|table)\b[^>]*>", re.I)

#: Anything else left over is a wrapper rather than content -- `<sup>`,
#: `<span id=...>` -- so the tag goes and the text inside it stays.  Unwrapping
#: rather than deleting is the important choice: a `<sup>` around a footnote
#: marker can be dropped, but the same rule applied to a `<div>` would delete the
#: paragraph inside it.
_PROOF_TAG = re.compile(r"<[^>]+>")


def _strip_proofreading(text: str) -> str:
    """Remove a proofread scan's apparatus, keeping the article.

    Text pulled from Wikisource's `Page:` namespace arrives with the
    transcriber's scaffolding still attached: `<noinclude>` blocks carrying the
    page's quality rating and editor's name, `<section>` markers, HTML comments,
    and `<div>`/`<span>`/`<sup>` wrappers used to centre a heading or raise a
    numeral.  None of it is the grammar; all of it is in the reader's way.
    """
    if not text or "<" not in text:
        return text
    out = _PROOF_DROP.sub(" ", text)
    out = _PROOF_COMMENT.sub(" ", out)
    out = _PROOF_BLOCK.sub(" ", out)
    out = _PROOF_TAG.sub("", out)
    return collapse(unescape(out)).strip()


# --------------------------------------------------------------------------
# OSIS
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<(/?)([A-Za-z0-9_.:-]+)((?:\s+[^<>]*?)?)(/?)>", re.S)
_ATTR_RE = re.compile(r"([A-Za-z0-9_.:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')")

_SKIP_OSIS = {
    "header", "titlePage", "revisionDesc", "work", "workPrefix", "teiHeader",
    "refSystem", "castList", "castItem", "castGroup", "actor", "role", "roleDesc",
    "contributor", "creator", "publisher", "identifier", "source", "language",
    "relation", "coverage", "rights", "scope", "osis", "osisText", "osisCorpus",
}

_NOTE_PLACEMENT = {
    "foot": "foot", "margin": "foot", "inline": "inline", "end": "end", "center": "foot",
}


class _Frame:
    """One open element while parsing markup.

    Children are collected into a single ordered list, because document order is
    part of the text: `<q who="Jesus">For <w>God</w> so loved</q>` must emit
    "For", the Strong's-tagged "God", then " so loved" -- in that order.  A
    parser that keeps a separate string buffer for the element's own text
    silently reorders inline content.

    The element's own segment is *derived* from that list on close.
    """

    __slots__ = ("kind", "tag", "attrs", "buf", "emit", "meta")

    def __init__(self, kind: str, attrs: dict, emit, meta: dict | None = None,
                 tag: str = ""):
        self.kind = kind
        self.tag = tag or kind
        self.attrs = attrs
        self.buf: list[Seg] = []
        self.emit = emit
        self.meta = meta or {}


def _run(segs: list[Seg]) -> list[Seg]:
    """Coalesce adjacent plain-text segments and drop empties."""
    out: list[Seg] = []
    for s in segs:
        if s.kind in ("text", "add", "alt", "red", "name", "title", "strongs"):
            if s.kind == "strongs" and not s.text:
                out.append(s)
                continue
            t = collapse(s.text)
            if not t:
                continue
            prev = out[-1] if out else None
            if (prev is not None and prev.kind == s.kind
                    and prev.value == s.value and prev.lemma == s.lemma
                    and prev.attrs == s.attrs):
                out[-1] = prev._replace(text=prev.text + " " + t)
            else:
                out.append(s._replace(text=t))
        else:
            out.append(s)
    return out


_TAGMATCH = _TAG_RE

# <?xml ... ?> and <!DOCTYPE ...> at the head of a document -- not elements.
_XML_PREAMBLE = re.compile(
    r"^\s*(?:<\?xml\b[^>]*\?>\s*|<!--.*?-->\s*|<!DOCTYPE\b[^>]*>\s*)+",
    re.I | re.S)

# Frame kind -> how its children are turned into the parent's segments.
#   'inline-text'  : fold the children's text into one segment of `kind`
#   'inline-mark'   : keep the children, restyling their text
#   'transparent'  : keep the children unchanged
_TRANSPARENT = {"seg", "foreign", "div", "list", "lg", "p", "block", "quote",
                "illustration", "lgGroup", "closer", "salute", "signed",
                "inscription", "speaker", "speech", "mentioned"}


def parse_osis(src: str, *, keep_footnotes: bool = True) -> list[Seg]:
    """Parse an OSIS fragment into segments.

    Handles what actually occurs in Bible modules: <w lemma morph>, <note> of
    every type, <reference>, <q who>, <transChange>, <divineName>, <hi type>,
    <lb>/<lg>, <title>/<head>, <figure>, <milestone>, <seg>, <list>/<item>,
    <name type>, <foreign>, and the x-importer/x-p/x-milestone structural divs.
    """
    if not src:
        return []
    # An XML declaration and a DOCTYPE are not elements: the tag pattern starts
    # with a name, so both are left as literal text at the head of the document
    # ("<!doctype html public ...>" was showing as the first line of Rieger's
    # autobiography).  Drop them before parsing.
    src = _XML_PREAMBLE.sub(" ", src)
    root: list[Seg] = []
    stack: list[_Frame] = []
    pos = 0

    def add(seg: Seg) -> None:
        (stack[-1].buf if stack else root).append(seg)

    for m in _TAGMATCH.finditer(src):
        chunk = src[pos:m.start()]
        pos = m.end()
        if chunk:
            add(Seg("text", unescape(chunk)))
        closing, name, rawattrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        name_l = name.lower()
        attrs = {}
        for am in _ATTR_RE.finditer(rawattrs or ""):
            attrs[am.group(1).lower()] = unescape(am.group(2)[1:-1])

        if not closing:
            if name_l in _SKIP_OSIS:
                if not selfclose:
                    stack.append(_Frame("skip", attrs, None, tag=name_l))
                continue
            if name_l == "w":
                lemma = ""
                lg = attrs.get("lemma", "")
                ms = re.findall(r"strong:([A-Za-z0-9]+)", lg)
                lemma = " ".join(sorted({x.upper() for x in ms})) if ms else lg
                if selfclose:
                    add(Seg("strongs" if lemma else "text", "", lemma,
                            attrs.get("morph", "")))
                else:
                    stack.append(_Frame("w", attrs, _emit_w,
                                        {"lemma": lemma,
                                         "morph": attrs.get("morph", "")},
                                        tag="w"))
                continue
            if name_l in ("lb", "br"):
                add(Seg("break", "\n"))
                continue
            if name_l == "milestone":
                if attrs.get("type", "") in ("x-p", "x-added", "x-extra", "x-para"):
                    add(Seg("break", "\n"))
                continue
            if name_l == "figure":
                add(Seg("img", attrs.get("src", ""), attrs.get("osisref", ""),
                        "", {"caption": attrs.get("title", ""),
                             "caption2": attrs.get("caption", "")}))
                continue
            if name_l in ("chapter", "verse"):
                add(Seg("title", "", attrs.get("osisid", ""), "",
                        {"t": "chapter" if name_l == "chapter" else "verse"}))
                continue
            if name_l == "reference":
                tgt = (attrs.get("osisref") or attrs.get("ref")
                       or attrs.get("osisid") or "")
                if tgt:
                    add(Seg("xref", "", tgt))
                continue
            if name_l == "catchword":
                if not selfclose:
                    stack.append(_Frame("catchword", attrs, _emit_catchword,
                                        tag=name_l))
                continue
            if not selfclose:
                kind = _FRAME_KIND.get(name_l, "seg")
                if name_l == "q" and not _osis_speaker_is_jesus(
                        attrs.get("who", "")):
                    # OSIS uses <q> for ordinary quotations too. Only an
                    # explicit Jesus speaker attribution means red letters.
                    kind = "seg"
                stack.append(_Frame(kind, attrs, _EMIT.get(kind, _emit_transparent),
                                    tag=name_l))
            continue

        # closing tag
        idx = -1
        for i in range(len(stack) - 1, -1, -1):
            if stack[i].tag == name_l:
                idx = i
                break
        if idx < 0:
            continue
        frame = stack[idx]
        # Anything still open above this frame is unbalanced markup, and the
        # slice below used to delete those frames together with the text they had
        # collected.  Abbott-Smith (Strong's) wraps entries in
        # <checked-cfb except="rongs numbers?">, whose attribute is missing its
        # closing quote, so the element has no close tag; when </entry> then
        # arrived it threw the whole article away and stored an empty one.  Flush
        # the unclosed frames into the frame being closed, innermost first, so a
        # missing close tag costs a stray tag rather than the text.  Well-formed
        # markup has nothing above idx, so this is a no-op there.
        for inner in reversed(stack[idx + 1:]):
            if inner.emit is not None:
                inner.emit(inner, frame.buf, keep_footnotes)
        del stack[idx:]
        parent = stack[-1].buf if stack else root
        if frame.emit is not None:
            frame.emit(frame, parent, keep_footnotes)

    tail = src[pos:]
    if tail:
        (stack[-1].buf if stack else root).append(Seg("text", unescape(tail)))
    # A wrapper tag that is never closed leaves its frame on the stack at EOF,
    # and its buffered children used to be dropped with it -- so one unbalanced
    # tag silently blanked the whole article (Abbott-Smith with Strong's wraps
    # several entries in <checked-cfb except="rongs numbers?">, which is missing
    # its closing quote and so has no matching close tag).  Flush whatever is
    # still open, innermost first, so a malformed tag costs the reader a stray
    # tag rather than the entry.  "skip" frames still drop, as they must.
    while stack:
        frame = stack.pop()
        parent = stack[-1].buf if stack else root
        if frame.emit is not None:
            frame.emit(frame, parent, keep_footnotes)
    return _run(root)


def _text_of(segs: list[Seg]) -> str:
    return "".join(s.text for s in segs if s.is_text())


def _emit_w(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    lemma = f.meta.get("lemma", "")
    morph = f.meta.get("morph", "")
    parent.append(Seg("strongs" if lemma else "text", _text_of(f.buf), lemma, morph))
    for s in f.buf:
        if not s.is_text():
            parent.append(s)


def _emit_transparent(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.extend(f.buf)


def _emit_block(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.append(Seg("para", "\n"))
    parent.extend(f.buf)


def _emit_item(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.append(Seg("text", "\u2022 "))
    parent.extend(f.buf)


def _emit_note(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    body = _text_of(f.buf)
    if keep_notes:
        parent.append(Seg("note", body, f.attrs.get("osisid", ""),
                          f.attrs.get("type", "explanation"),
                          {"placement": _NOTE_PLACEMENT.get(
                              f.attrs.get("placement", "foot"), "foot"),
                           "ref": f.attrs.get("osisref", "")}))


def _emit_title(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.append(Seg("title", _text_of(f.buf), "", "",
                      {"t": f.attrs.get("type", "")}))


def _emit_head(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.append(Seg("heading", _text_of(f.buf), "", "",
                      {"level": f.attrs.get("level", "")}))


def _emit_catchword(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    parent.append(Seg("catchword", _text_of(f.buf), f.attrs.get("osisid", "")))


def _restyle(kind: str, extra_attrs: dict | None = None):
    def go(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
        for s in f.buf:
            if s.is_text():
                d = dict(s.attrs)
                d.update(extra_attrs or {})
                parent.append(s._replace(kind=kind, attrs=d))
            else:
                parent.append(s)
    return go


def _emit_q(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    """<q who="Jesus"> -- mark the children as words of Christ, order intact."""
    for s in f.buf:
        if s.is_text():
            d = dict(s.attrs)
            d["wj"] = "1"
            parent.append(s._replace(attrs=d))
        else:
            parent.append(s)


def _osis_speaker_is_jesus(raw: str) -> bool:
    """Return true only for an explicit OSIS Jesus speaker identifier."""
    return any(re.fullmatch(r"#?Jesus", token, re.I)
               for token in re.split(r"[\s,;]+", (raw or "").strip()) if token)


def _emit_divine(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    for s in f.buf:
        if s.is_text():
            parent.append(s._replace(kind="name", value="divine"))
        else:
            parent.append(s)


def _emit_name(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    for s in f.buf:
        if s.is_text():
            parent.append(s._replace(kind="name", value=f.attrs.get("type", "")))
        else:
            parent.append(s)


def _emit_transchange(f: _Frame, parent: list[Seg], keep_notes: bool) -> None:
    kind = {"added": "add", "alternate": "alt", "unclear": "text",
            "expanded": "add"}.get(f.attrs.get("type", ""), "add")
    for s in f.buf:
        parent.append(s._replace(kind=kind) if s.is_text() else s)


_FRAME_KIND = {
    "w": "w", "note": "note", "title": "title", "head": "head",
    "q": "q", "transchange": "transchange", "divinename": "divine",
    "divine": "divine", "name": "name", "lg": "block", "l": "block",
    "p": "block", "item": "item", "list": "seg", "catchword": "catchword",
    "seg": "seg", "foreign": "seg", "hi": "hi", "blockquote": "seg",
    "figure": "seg", "div": "seg", "lb": "seg", "verse": "seg",
    "chapter": "seg", "speaker": "seg", "speech": "seg", "mentioned": "seg",
    "closer": "seg", "salute": "seg", "signed": "seg", "inscription": "seg",
    "date": "seg", "abbr": "seg", "hi2": "seg", "label": "seg", "term": "seg",
    "index": "seg", "seq": "seg", "lggroup": "seg",
}

_EMIT = {
    "w": _emit_w,
    "note": _emit_note,
    "title": _emit_title,
    "head": _emit_head,
    "catchword": _emit_catchword,
    "q": _emit_q,
    "divine": _emit_divine,
    "name": _emit_name,
    "lg": _emit_block, "l": _emit_block, "p": _emit_block,
    "item": _emit_item,
    "seg": _emit_transparent, "hi": _emit_transparent,
    "transchange": _emit_transchange,
    "block": _emit_block, "skip": None,
}

# --------------------------------------------------------------------------
# ThML / TEI  (Barnes, Strong's, most SWORD dictionaries)
# --------------------------------------------------------------------------

def parse_teithml(src: str, *, keep_footnotes: bool = True) -> list[Seg]:
    segs = parse_osis(src, keep_footnotes=keep_footnotes)
    # Scripref tags carry the target; convert to xref segments.
    for m in re.finditer(r"<scripref\b[^>]*>(.*?)</scripref>", src or "", re.S | re.I):
        pass
    return segs


# --------------------------------------------------------------------------
# e-Sword / MySword USFM-ish inline markup
# --------------------------------------------------------------------------

_ES_RE = re.compile(
    r"\\w\s+(?P<inner>[^\\]*?)\\w\*"
    r"|\{(?P<brace>[^{}]*)\}"
    r"|~(?P<tilde>[A-Za-z0-9]+)"
    r"|<(?P<red>[^<>]{0,400}?)>",
    re.S,
)


def parse_esword_inline(src: str) -> list[Seg]:
    """e-Sword / MySword inline markup.

    Tagging, in the notation e-Sword uses in its docs and .mod help:
      word|strong="H0430"   a word carrying a Strong's number
      ~H0430               Strong's number attached to the previous word
      {note text}          a footnote
      <red words>          words of Christ
    """
    segs: list[Seg] = []
    pos = 0
    for m in _ES_RE.finditer(src or ""):
        if m.start() > pos:
            segs.append(Seg("text", collapse(unescape(src[pos:m.start()]))))
        if m.group("inner") is not None:
            raw = m.group("inner")
            parts = raw.split("|")
            word = parts[0]
            strong = ""
            for p in parts[1:]:
                sm = re.search(r'strong="?([A-Za-z0-9]+)"?', p)
                if sm:
                    strong = sm.group(1)
            segs.append(Seg("strongs" if strong else "text", collapse(unescape(word)),
                            strong))
        elif m.group("tilde"):
            segs.append(Seg("strongs", "", m.group("tilde")))
        elif m.group("brace") is not None:
            segs.append(Seg("note", collapse(unescape(m.group("brace"))), "", "note",
                            {"placement": "foot"}))
        elif m.group("red") is not None:
            segs.append(Seg("red", collapse(unescape(m.group("red")))))
        pos = m.end()
    if pos < len(src or ""):
        segs.append(Seg("text", collapse(unescape(src[pos:]))))
    return [s for s in segs if s.text or s.kind in ("strongs", "note", "red", "break")]


_GBF_TAG_RE = re.compile(r"<(/?)([A-Za-z]{2})([^>]*)>")


def parse_gbf_inline(src: str) -> list[Seg]:
    """Parse the GBF markup used inside a single SWORD verse.

    GBF is a token format rather than XML. In particular, `<FR>...<Fr>` marks
    Jesus' words, `<WGn>` / `<WHn>` annotate the preceding word, and `<RF>...<Rf>`
    carries a footnote. Unrecognized tags are stripped while their surrounding
    text remains in order.
    """
    if not src:
        return []
    out: list[Seg] = []
    note: list[str] | None = None
    red = False
    pos = 0

    def add_text(raw: str) -> None:
        if not raw:
            return
        if note is not None:
            note.append(raw)
        else:
            out.append(Seg("red" if red else "text", unescape(raw)))

    for match in _GBF_TAG_RE.finditer(src):
        add_text(src[pos:match.start()])
        pos = match.end()
        closing, tag, arg = match.groups()
        if tag == "FR" and not closing:
            red = True
        elif tag == "Fr" and not closing:
            red = False
        elif tag == "RF" and not closing:
            note = []
        elif tag == "Rf" and not closing and note is not None:
            body = " ".join("".join(note).split())
            if body:
                out.append(Seg("note", body, "", "footnote",
                               {"placement": "foot"}))
            note = None
        elif not closing and tag in ("WG", "WH"):
            number = re.match(r"\s*(\d+)", arg or "")
            if number and out and out[-1].is_text():
                prev = out.pop()
                tail = re.search(r"(\S+)(\s*)$", prev.text)
                if tail:
                    prefix = prev.text[:tail.start(1)]
                    if prefix:
                        out.append(prev._replace(text=prefix))
                    word = tail.group(1)
                    strong = tag[1] + number.group(1)
                    attrs = dict(prev.attrs)
                    if red:
                        attrs["wj"] = "1"
                    out.append(Seg("strongs", word, strong, "", attrs))
                    if tail.group(2):
                        out.append(Seg("text", tail.group(2)))
                else:
                    out.append(prev)
                    out.append(Seg("strongs", "", tag[1] + number.group(1)))
            elif number:
                out.append(Seg("strongs", "", tag[1] + number.group(1)))
        elif not closing and tag == "RX":
            target = (arg or "").strip()
            if target:
                out.append(Seg("xref", "", target))
    add_text(src[pos:])
    if note is not None:
        body = " ".join("".join(note).split())
        if body:
            out.append(Seg("note", body, "", "footnote", {"placement": "foot"}))
    return _run(out)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_HTML_KEEP = {
    "b": "strong", "strong": "strong", "i": "em", "em": "em", "u": "u",
    "sup": "sup", "sub": "sub", "small": "small", "big": "big",
    "h1": "h3", "h2": "h3", "h3": "h3", "h4": "h4", "h5": "h4", "h6": "h4",
    "p": "p", "div": "div", "span": "span", "br": "br", "li": "li", "ul": "ul",
    "ol": "ol", "blockquote": "blockquote", "a": "a", "img": "img",
    "table": "table", "tr": "tr", "td": "td", "th": "th", "hr": "hr",
    "sup1": "sup", "sup2": "sup", "sup3": "sup",
}


def parse_html(src: str) -> list[Seg]:
    """Tolerant HTML/RTF-fragment reader.

    e-Sword 9+ stores Scripture as HTML or RTF, so this is not optional.  It is
    deliberately forgiving: unknown tags become transparent, script/style content
    is dropped.
    """
    segs: list[Seg] = []
    if not src:
        return segs
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", src)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    pos = 0
    stack: list[tuple[str, dict]] = []
    for m in _TAG_RE.finditer(s):
        txt = s[pos:m.start()]
        if txt:
            segs.append(Seg("text", collapse(unescape(_strip_tags(txt)))))
        pos = m.end()
        closing, name, rawattrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        attrs = {}
        for am in _ATTR_RE.finditer(rawattrs or ""):
            attrs[am.group(1).lower()] = unescape(am.group(2)[1:-1])
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    stack.pop(i)
                    break
            continue
        if name in ("br", "hr"):
            segs.append(Seg("break", "\n"))
        elif name == "img":
            segs.append(Seg("img", attrs.get("src", ""), "", "",
                            {"alt": attrs.get("alt", "")}))
        elif name == "p" or name == "div":
            segs.append(Seg("para", "\n"))
        elif not selfclose:
            stack.append((name, attrs))
    tail = s[pos:]
    if tail:
        segs.append(Seg("text", collapse(unescape(_strip_tags(tail)))))
    return _run([x for x in segs
                 if x.text or x.kind in ("strongs", "note", "img", "break", "para")])


# --------------------------------------------------------------------------
# RTF  (e-Sword .bblx Details.Comments and many .dev/.dct payloads)
# --------------------------------------------------------------------------

_RTF_CTRL = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?|\\([^a-zA-Z])|([{}])|([^<>{}]|\n)+")


def parse_rtf(src: str) -> str:
    """Strip RTF control words down to plain text.  Deliberately minimal -- it
    only has to cope with the subset e-Sword and BibleTime emit."""
    if not src or not src.lstrip().startswith(r"{\rtf"):
        return src or ""
    out: list[str] = []
    skip_depth = None
    depth = 0
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            if src[i + 1:i + 2] == "'" and i + 3 < n:
                try:
                    out.append(chr(int(src[i + 2:i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            m = _RTF_CTRL.match(src, i)
            if not m:
                i += 1
                continue
            if m.group(2) is not None and m.group(1) == "u":
                try:
                    cp = int(m.group(2))
                    if cp < 0:
                        cp += 65536
                    out.append(chr(cp))
                except ValueError:
                    pass
            i = m.end()
            continue
        if c == "{":
            depth += 1
            if skip_depth is None and src[max(0, i - 40):i].lower().endswith(("fonttbl", "colortbl", "stylesheet", "info", "pict")):
                skip_depth = depth
        elif c == "}":
            if skip_depth is not None and depth == skip_depth:
                skip_depth = None
            depth -= 1
        elif c in "\r\n":
            out.append(" ")
        elif skip_depth is None:
            out.append(c)
        i += 1
    t = "".join(out)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    return t.strip()


# --------------------------------------------------------------------------
# Wikitext  (Wikisource)
# --------------------------------------------------------------------------

def parse_wikitext(src: str) -> list[Seg]:
    """Wikisource wikitext -> segments.

    PD works on Wikisource use: `== headings ==`, `'''bold'''` (verse numbers in
    the old commentaries), `''italic''`, `[[link|label]]`, `[http://x label]`,
    `<ref>` footnotes, `<div class="poem">`, `{{templates}}`, and em-dash
    transcription conventions.
    """
    segs: list[Seg] = []
    if not src:
        return segs
    lines = src.split("\n")
    in_ref = False
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        # strip trailing navigation / metadata blocks
        if s in ("{{TOC right}}", "{{ppb}}", "}}", "{{header") or s.startswith("|{{") \
           or s.startswith("| title") or s.startswith("| author") or s.startswith("| section") \
           or s.startswith("| previous") or s.startswith("| next") or s.startswith("| notes") \
           or s.startswith("|}") or s.startswith("{{header") or s.startswith("{{about") \
           or s.startswith("{{Use") or s.startswith("{{pp") or s.startswith("{{unsourced"):
            if s == "{{header":
                in_ref = True
            elif s.startswith("}}") and in_ref:
                in_ref = False
            continue
        if in_ref:
            continue
        if s.startswith("<references/>") or s.startswith("{{cite"):
            continue
        # headings
        m = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", s)
        if m:
            segs.append(Seg("heading", "", "", "", {"level": len(m.group(1))}))
            segs.append(Seg("title", _wt_inline(m.group(2))))
            continue
        if s.startswith("----"):
            segs.append(Seg("break", "\n"))
            continue
        if s.startswith("*") or s.startswith("#"):
            segs.append(Seg("text", "\u2022 "))
            s = s.lstrip("*#: ")
        if s.startswith("{{") and s.endswith("}}"):
            inner = s[2:-2]
            name = inner.split("|")[0].strip().lower()
            if name in ("rh", "center", "sc", "small", "big", "blockquote"):
                segs.append(Seg("text", _wt_inline(inner.split("|", 1)[1] if "|" in inner else "")))
            continue
        # ref footnotes
        for rm in re.finditer(r"<ref[^>]*>(.*?)</ref>", s, re.S | re.I):
            segs.append(Seg("note", _wt_inline(rm.group(1)).strip()))
            s = s[:rm.start()] + " " + s[rm.end():]
        segs.append(Seg("text", _wt_inline(s)))
    return [x for x in segs if x.text or x.kind in ("heading", "title", "break", "note", "img")]


_WT_REF_PATTERNS = [
    (re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\](?!\|)"), r"\1"),
    (re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\|(?:[^\]]*)\]\]"), r"\1"),
    (re.compile(r"\[https?://[^\s\]]+\s+([^\]]*)\]"), r"\1"),
    (re.compile(r"\[https?://[^\s\]]*\]"), ""),
    (re.compile(r"\[(?:[^\]]*)\]"), ""),
    (re.compile(r"'''''(.*?)'''''"), r"\1"),
    (re.compile(r"'''(.*?)'''"), r"\1"),
    (re.compile(r"''(.*?)''"), r"\1"),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"&nbsp;?"), " "),
    (re.compile(r"&amp;?"), "&"),
    (re.compile(r"&lt;?"), "<"),
    (re.compile(r"&gt;?"), ">"),
    (re.compile(r"&#(\d+);"), lambda m: chr(int(m.group(1)))),
]


def _wt_inline(s: str) -> str:
    out = s or ""
    for pat, rep in _WT_REF_PATTERNS:
        out = pat.sub(rep, out)
    out = re.sub(r"\[(?:[^\]]*)\]\s*", "", out)
    return collapse(out).strip()


# --------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------

def parse_plain(src: str, *, line_breaks: bool = True) -> list[Seg]:
    segs: list[Seg] = []
    for i, line in enumerate((src or "").split("\n")):
        line = line.rstrip()
        if not line.strip():
            continue
        if i:
            segs.append(Seg("break", "\n"))
        stripped = line.strip()
        if re.fullmatch(r"#{1,6}\s+\S.*", stripped) and len(stripped) < 90:
            segs.append(Seg("heading", "", "", "", {}))
            segs.append(Seg("title", stripped.lstrip("#").strip()))
        elif re.fullmatch(r"(?:CHAPTER|Chapter)\s+[0-9IVXLC]+.*", stripped) and len(stripped) < 90:
            segs.append(Seg("heading", "", "", "", {}))
            segs.append(Seg("title", stripped))
        else:
            segs.append(Seg("text", stripped))
    return segs


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def segs_flatten(segs: Iterable[Seg], *, notes: bool = True
                 ) -> tuple[str, list[tuple[int, int, Seg]]]:
    """Flatten segments to text, recording where each segment landed.

    The offsets are what let the indexer store a compact span table instead of
    the original markup: the searchable text is the plain text, and the display
    layer re-derives Strong's, footnotes, supplied words and words of Christ
    from the spans.  That keeps one stored copy of the words and makes every
    input format render identically.
    """
    parts: list[str] = []
    spans: list[tuple[int, int, Seg]] = []
    pos = 0
    for s in segs:
        if s.is_text():
            t = s.text
        elif s.kind in ("break", "para"):
            t = "\n"
        elif s.kind == "note" and notes and s.text:
            t = " " + s.text
        else:
            continue
        if not t:
            continue
        spans.append((pos, len(t), s))
        parts.append(t)
        pos += len(t)
    return "".join(parts), spans


def segs_text(segs: Iterable[Seg], *, notes: bool = True) -> str:
    raw, _ = segs_flatten(segs, notes=notes)
    t = re.sub(r"[ \t\u00a0]+", " ", raw)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def spans_to_json(text: str, spans: list[tuple[int, int, Seg]],
                   notes: "list[Seg] | None" = None) -> str:
    """Compact, lossless-enough serialisation of the non-text decoration."""
    import json
    out = {"s": [], "n": [], "t": "", "h": 0}
    for start, ln, s in spans:
        if s.kind in ("break", "para"):
            out["h"] += 1
            continue
        if s.kind == "note":
            out["n"].append([s.value or "", s.lemma or "note", s.text,
                             (s.attrs or {}).get("placement", "foot")])
            continue
        if s.kind in ("title", "heading"):
            out["t"] = s.text
            continue
        if s.kind == "text" and not s.value and not s.lemma and not s.attrs:
            continue
        out["s"].append([start, ln, s.kind, s.value or "", s.lemma or "",
                         s.attrs or {}])
    # Notes are deliberately kept out of the searchable text (see
    # segs_for_search), but their bodies are preserved here so they render as
    # footnotes rather than disappearing.  They carry no position of their own
    # in the text, so they are appended as a list rather than woven into spans.
    for nseg in (notes or ()):
        if nseg.kind != "note" or not nseg.text:
            continue
        out["n"].append([nseg.value or "", nseg.lemma or "note", nseg.text,
                         (nseg.attrs or {}).get("placement", "foot")])
    return json.dumps(out, ensure_ascii=False)


def segs_from_span(text: str, blob: str | None) -> list[Seg]:
    """Rebuild segments from stored text + span table."""
    import json
    if not text:
        return []
    segs: list[Seg] = []
    if not blob:
        return [Seg("text", text)]
    try:
        d = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return [Seg("text", text)]
    cuts = sorted({0, len(text)} |
                  {p for a, _l, *_ in d.get("s", []) for p in (a, a + _l)})
    cuts = [c for c in cuts if 0 <= c <= len(text)]
    decorated = {}
    for a, ln, kind, val, lemma, attrs in d.get("s", []):
        for p in range(a, a + ln):
            decorated[p] = (kind, val, lemma, attrs or {})
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b <= a:
            continue
        chunk = text[a:b]
        if not chunk:
            continue
        first = decorated.get(a)
        if first and all(decorated.get(p) == first for p in range(a, b)):
            kind, val, lemma, attrs = first
            segs.append(Seg(kind, chunk, val, lemma, attrs))
        else:
            segs.append(Seg("text", chunk))
    for osid, ntype, ntext, place in d.get("n", []):
        segs.append(Seg("note", ntext, osid, ntype, {"placement": place}))
    if d.get("t"):
        segs.insert(0, Seg("title", d["t"]))
    return _run(segs)


_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(s: str) -> str:
    return "".join(_ESC.get(c, c) for c in (s or ""))


class RenderOpts:
    def __init__(self, *, show_strongs=False, show_notes=True, show_headings=True,
                 show_red=True, show_xrefs=True, verse_per_line=False,
                 show_add=True, base_ref="", font_scale=100):
        self.show_strongs = show_strongs
        self.show_notes = show_notes
        self.show_headings = show_headings
        self.show_red = show_red
        self.show_xrefs = show_xrefs
        self.verse_per_line = verse_per_line
        self.show_add = show_add
        self.base_ref = base_ref
        self.font_scale = font_scale


def segs_html(segs: Iterable[Seg], o: RenderOpts | None = None) -> str:
    o = o or RenderOpts()
    out: list[str] = []

    def with_red(h: str, marked: bool) -> str:
        return f'<span class="wj">{h}</span>' if marked and o.show_red else h

    for s in segs:
        wj = bool(s.attrs.get("wj"))
        if s.kind == "text":
            h = esc(s.text)
            out.append(f'<span class="wj">{h}</span>' if (wj and o.show_red) else h)
        elif s.kind == "add":
            h = f'<i class="supplied">{esc(s.text)}</i>' if o.show_add else esc(s.text)
            out.append(with_red(h, wj))
        elif s.kind == "alt":
            out.append(with_red(f'<span class="alt">{esc(s.text)}</span>', wj))
        elif s.kind == "red":
            out.append(f'<span class="wj">{"".join(esc(t) for t in s.text)}</span>'
                       if o.show_red else esc(s.text))
        elif s.kind == "name":
            h = f'<span class="pname" data-kind="{esc(s.value)}">{esc(s.text)}</span>'
            out.append(with_red(h, wj))
        elif s.kind == "strongs":
            w = esc(s.text)
            if o.show_strongs and s.value:
                nums = s.value.split()
                w += ('<sup class="snums">'
                      + " ".join(f'<a class="snum" data-s="{n}" href="#">{n}</a>' for n in nums)
                      + "</sup>")
            if s.lemma and o.show_strongs:
                w += f'<sup class="morphs" title="morphology">{esc(s.lemma)}</sup>'
            out.append(f'<span class="wj">{w}</span>' if (wj and o.show_red) else w)
        elif s.kind == "note":
            if o.show_notes and s.text:
                nid = "n" + _hashid(s.value or s.text)
                out.append(
                    f'<a class="fn" id="{nid}" href="#note-{nid}" data-note="{esc(s.text)}"'
                    f' title="{esc(_short(s.text, 90))}"><sup>{_sup_num(s.value)}</sup></a>')
            elif s.text:
                out.append(f'<span class="fntext">{esc(s.text)}</span>')
        elif s.kind == "title":
            if o.show_headings:
                out.append(f'<span class="docheading" data-t="{esc(s.attrs.get("t", ""))}">'
                           f'{esc(s.text)}</span>')
        elif s.kind == "heading":
            if o.show_headings:
                out.append('<h3 class="unitheading">')
        elif s.kind == "break":
            out.append("<br>" if not o.verse_per_line else "</p><p>")
        elif s.kind == "para":
            out.append("<br>")
        elif s.kind == "img":
            src = s.text
            if src:
                out.append(f'<figure><img loading="lazy" src="{esc(src)}" '
                           f'alt="{esc(s.attrs.get("alt", "") or s.attrs.get("caption", ""))}"></figure>')
        elif s.kind == "xref":
            tgt = esc(s.value or "")
            out.append(f'<a href="#" data-ref="{tgt}">{tgt}</a>')
    return "".join(out)


def _hashid(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:8]


def _sup_num(osisid: str) -> str:
    m = re.search(r"!(\w+)$", osisid or "")
    return esc(m.group(1)) if m else "+"


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "")
    return s if len(s) <= n else s[:n - 1] + "\u2026"


def segs_for_search(segs: Iterable[Seg]) -> str:
    """Plain text used for the search index -- notes excluded by default so a
    footnote's wording does not outrank the passage that contains it."""
    return segs_text(segs, notes=False)


def markers_from_segs(segs: Iterable[Seg], *, base_word: int = 0) -> list[Seg]:
    """Strong's / lemma / morph markers carried by these segments.

    Returned as pseudo-segments so the indexer can walk one list.
    """
    out = []
    for s in segs:
        if s.kind == "strongs" and s.value:
            for n in s.value.split():
                out.append(Seg("marker", "", n, "", {"kind": "strongs"}))
            if s.lemma:
                for m in s.lemma.split():
                    out.append(Seg("marker", "", m, "", {"kind": "morph"}))
        elif s.kind == "note" and s.value:
            out.append(Seg("marker", "", s.value, "", {"kind": "note"}))
    return out
