"""The Latin Library (thelatinlibrary.com) — patristic works in Latin.

Pages are plain HTML: a `<p class=pagehead>` title followed by `<p>` blocks,
some of which hold a section number ("1.1.1") and some of which hold the
Latin text.  A work is usually split across several pages (one per book),
and each page is what the Store offers as a single item.
"""

from __future__ import annotations

import re
from typing import Iterator

from .. import markup
from ..indexer import UnitIn
from ..markup import Seg

_SECTION_RE = re.compile(r"^\s*(?:[IVXLC]+\.|[0-9]+(?:\.[0-9]+)*)\s*$")


def _strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    from html import unescape
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _paragraphs(html: str) -> list[str]:
    # Pull <p>...</p> contents.  The pagehead and borders are handled separately.
    out = []
    for m in re.finditer(r"<p\b[^>]*>(.*?)</p>", html, re.S | re.I):
        txt = _strip_tags(m.group(1))
        if txt:
            out.append(txt)
    return out


def _title(html: str) -> str:
    m = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S | re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if t:
            return t
    m = re.search(r'<p class=pagehead>(.*?)</p>', html, re.S | re.I)
    if m:
        t = _strip_tags(m.group(1))
        if t:
            return t
    return "Latin text"


def units_from_page(html: str, *, title: str = "", source: str = "") -> Iterator[UnitIn]:
    title = title or _title(html)
    paras = _paragraphs(html)
    # Drop the pagehead (first paragraph if it equals the title) and borders.
    if paras and paras[0] == title:
        paras = paras[1:]

    # Group paragraphs into sections: a paragraph that is just a section number
    # labels the following text paragraphs.
    sections: list[tuple[str, list[str]]] = []
    current_label = ""
    current_body: list[str] = []
    for p in paras:
        if _SECTION_RE.match(p) and len(p) <= 20:
            if current_body:
                sections.append((current_label, current_body))
                current_body = []
            current_label = p
        else:
            current_body.append(p)
    if current_body:
        sections.append((current_label, current_body))

    if not sections:
        sections = [("", paras)]

    n = 0
    for label, body in sections:
        text = "\n\n".join(body).strip()
        if not text:
            continue
        n += 1
        key = label if label else f"section {n}"
        # Pack very long sections into smaller units.
        if len(text) > 24000:
            # split at paragraph boundaries
            chunk = ""
            ci = 0
            for para in body:
                if chunk and len(chunk) + len(para) > 24000:
                    ci += 1
                    yield UnitIn(key=f"{key}.{ci}", label=f"{key} ({ci})",
                                 title=title, segs=[Seg("text", chunk.strip())])
                    chunk = para
                else:
                    chunk = (chunk + "\n\n" + para) if chunk else para
            if chunk.strip():
                ci += 1
                yield UnitIn(key=f"{key}.{ci}" if ci > 1 else key,
                             label=f"{key} ({ci})" if ci > 1 else key,
                             title=title, segs=[Seg("text", chunk.strip())])
        else:
            yield UnitIn(key=key, label=key, title=title,
                         segs=[Seg("text", text)])


def sniff_latinlib(data: bytes | None = None, name: str = "") -> bool:
    if data:
        head = data[:2000].lower()
        return (b"thelatinlibrary.com" in head or b"latinlibrary.css" in head
                or b"pagehead" in head)
    return name.lower().endswith((".html", ".shtml")) and "latin" in name.lower()
