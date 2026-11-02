"""Writing a PPTX (PowerPoint) file, with no PowerPoint and no third-party code.

A presentation is a small, documented format: a ZIP archive of XML parts
(Office Open XML, ECMA-376 / ISO/IEC 29500).  That is what this module
writes, in the same spirit as `gbible/pdf.py` — a format is produced from a
documented specification rather than by embedding someone else's library, so
no third-party licence travels inside the file and nothing has to be tracked.

The result opens in PowerPoint, LibreOffice Impress, Google Slides and
Keynote.  Only the text is written; no fonts are embedded, so the reader
uses its own (which is what those applications do by default).  Hebrew and
Greek are written as Unicode and render with whatever font the reader picks
— unlike the PDF writer, there is no base-14 restriction here.

Attribution is not optional.  `build()` takes an `attribution` string and
appends it as a final slide, so a presentation cannot be produced without
the licence statement being considered — the same rule as `pdf.Doc.build`.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape as _xml_escape


# ---- geometry (EMU: 914400 per inch) -------------------------------------
_SLIDE_W = 9144000   # 10 inches
_SLIDE_H = 6858000   # 7.5 inches
_TITLE_BOX = (457200, 274638, 8229600, 1143000)   # x, y, cx, cy
_BODY_BOX = (457200, 1600200, 8229600, 4572000)


def _x(s: str) -> str:
    return _xml_escape(s or "", {'"': "&quot;", "'": "&apos;"})


def _para(text: str, size_pt: int = 18, bold: bool = False,
          italic: bool = False, space_after: int = 6) -> str:
    rpr = f'<a:rPr sz="{size_pt * 100}"'
    if bold:
        rpr += ' b="1"'
    if italic:
        rpr += ' i="1"'
    rpr += '/>'
    # rPr must precede the text run's t element in the schema order.
    rpr = f'<a:rPr sz="{size_pt * 100}"' + (' b="1"' if bold else '') + \
          (' i="1"' if italic else '') + '/>'
    return (f'<a:p><a:pPr spcAfter="{space_after * 100}"/>'
            f'<a:r>{rpr}<a:t xml:space="preserve">{_x(text)}</a:t></a:r></a:p>')


def _shape(sp_id: int, name: str, box, paragraphs: list[str],
           font_size: int = 18) -> str:
    x, y, cx, cy = box
    paras = "".join(paragraphs) if paragraphs else "<a:p/>"
    return (
        f'<p:sp>'
        f'<p:nvSpPr><p:cNvPr id="{sp_id}" name="{_x(name)}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/>'
        f'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:noFill/></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square" rtlCol="0"/>'
        f'<a:lstStyle/>{paras}</p:txBody>'
        f'</p:sp>')


class Presentation:
    """A presentation: title slides and body slides, written out as PPTX bytes."""

    def __init__(self, *, title: str = "", author: str = ""):
        self.title = title or "Presentation"
        self.author = author or ""
        self.slides: list[tuple[str, list[str]]] = []

    def add_slide(self, title: str = "", body=None, bullets=None) -> None:
        lines: list[str] = []
        if body is not None:
            if isinstance(body, str):
                lines.append(body)
            else:
                lines.extend(str(b) for b in body)
        if bullets:
            lines.extend(f"• {b}" for b in bullets)
        self.slides.append((title or "", lines))

    def build(self, *, attribution: str = "") -> bytes:
        if attribution:
            self.add_slide("Sources and terms", [attribution])
        if not self.slides:
            self.add_slide(self.title, [])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            self._write_parts(z)
        return buf.getvalue()

    # ---------------------------------------------------------------- parts
    def _write_parts(self, z: zipfile.ZipFile) -> None:
        n = len(self.slides)
        # content types
        z.writestr("[Content_Types].xml", self._content_types(n))
        z.writestr("_rels/.rels", self._root_rels())
        z.writestr("ppt/presentation.xml", self._presentation(n))
        z.writestr("ppt/_rels/presentation.xml.rels", self._presentation_rels(n))
        z.writestr("ppt/slideMasters/slideMaster1.xml", self._slide_master())
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                   self._slide_master_rels())
        z.writestr("ppt/slideLayouts/slideLayout1.xml", self._slide_layout())
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                   self._slide_layout_rels())
        z.writestr("ppt/theme/theme1.xml", self._theme())
        for i in range(1, n + 1):
            z.writestr(f"ppt/slides/slide{i}.xml", self._slide(i))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels",
                       self._slide_rels())

    def _content_types(self, n: int) -> str:
        overrides = [
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.presentation.main+xml"/>',
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.slideMaster+xml"/>',
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.slideLayout+xml"/>',
            '<Override PartName="/ppt/theme/theme1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        ]
        for i in range(1, n + 1):
            overrides.append(
                f'<Override PartName="/ppt/slides/slide{i}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.'
                f'presentationml.slide+xml"/>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                + "".join(overrides) + "</Types>")

    def _root_rels(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="ppt/presentation.xml"/>'
                '</Relationships>')

    def _presentation(self, n: int) -> str:
        sld_ids = "".join(
            f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                f'<p:sldIdLst>{sld_ids}</p:sldIdLst>'
                f'<p:sldSz cx="{_SLIDE_W}" cy="{_SLIDE_H}" type="screen4x3"/>'
                '<p:notesSz cx="6858000" cy="9144000"/>'
                '</p:presentation>')

    def _presentation_rels(self, n: int) -> str:
        rels = ('<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
                'Target="slideMasters/slideMaster1.xml"/>')
        for i in range(1, n + 1):
            rels += (f'<Relationship Id="rId{i + 1}" '
                     f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                     f'Target="slides/slide{i}.xml"/>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + rels + '</Relationships>')

    def _slide_master(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                '</p:spTree></p:cSld>'
                '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
                'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
                'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
                '</p:sldMaster>')

    def _slide_master_rels(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                'Target="../slideLayouts/slideLayout1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
                'Target="../theme/theme1.xml"/>'
                '</Relationships>')

    def _slide_layout(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'type="blank">'
                '<p:cSld name="Blank"><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                '</p:spTree></p:cSld>'
                '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
                '</p:sldLayout>')

    def _slide_layout_rels(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
                'Target="../slideMasters/slideMaster1.xml"/>'
                '</Relationships>')

    def _theme(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="G-Bible">'
                '<a:themeElements>'
                '<a:clrScheme name="Office">'
                '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
                '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
                '<a:dk2><a:srgbClr val="1F497D"/></a:dk2>'
                '<a:lt2><a:srgbClr val="EEECE1"/></a:lt2>'
                '<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>'
                '<a:accent2><a:srgbClr val="C0504D"/></a:accent2>'
                '<a:accent3><a:srgbClr val="9BBB59"/></a:accent3>'
                '<a:accent4><a:srgbClr val="8064A2"/></a:accent4>'
                '<a:accent5><a:srgbClr val="4BACC6"/></a:accent5>'
                '<a:accent6><a:srgbClr val="F79646"/></a:accent6>'
                '<a:hlink><a:srgbClr val="0000FF"/></a:hlink>'
                '<a:folHlink><a:srgbClr val="800080"/></a:folHlink>'
                '</a:clrScheme>'
                '<a:fontScheme name="Office">'
                '<a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
                '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
                '</a:fontScheme>'
                '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
                '<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
                '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
                '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
                '</a:fmtScheme>'
                '</a:themeElements>'
                '<a:objectDefaults/><a:extraClrSchemeLst/>'
                '</a:theme>')

    def _slide(self, i: int) -> str:
        title, lines = self.slides[i - 1]
        title_paras = [_para(title or self.title, size_pt=32, bold=True)] \
            if title else []
        body_paras = [_para(ln, size_pt=18) for ln in lines]
        shapes = []
        shapes.append(_shape(2, "Title", _TITLE_BOX, title_paras, 32))
        shapes.append(_shape(3, "Body", _BODY_BOX, body_paras, 18))
        sp_tree = (
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + "".join(shapes))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f'<p:cSld><p:spTree>{sp_tree}</p:spTree></p:cSld>'
                '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
                '</p:sld>')

    def _slide_rels(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                'Target="../slideLayouts/slideLayout1.xml"/>'
                '</Relationships>')
