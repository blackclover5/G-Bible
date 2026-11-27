/* ============================================================== Printing */
/* e-Sword-style WYSIWYG print: anything you are looking at becomes a clean,
 * paper-looking document -- serif type, a real header (module name, section,
 * reference), license attribution at the foot, margins and page flow handled
 * by the browser's print engine.  The app itself never prints: panes, tabs
 * and sidebars are working chrome, not a page.  What goes on paper is the
 * content, re-rendered as a document. */
const Print = {
  /* The paper stylesheet.  Deliberately quiet: one sans for chrome-ish labels
   * (module, reference), one serif for the text itself. */
  _css() {
    return `
@page { size: auto; margin: 17mm 15mm 19mm; }
* { box-sizing: border-box; }
body {
  font-family: Georgia, 'Times New Roman', 'Nimbus Roman', serif;
  font-size: 11.5pt; line-height: 1.6; color: #1a1a1a; margin: 0;
}
.paper-header {
  margin: 0 0 15pt; padding-bottom: 8pt;
  border-bottom: 2.2pt solid #b39355;
}
.paper-module {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-weight: 700; font-size: 8pt; letter-spacing: .22em;
  text-transform: uppercase; color: #7a5a1e;
}
.paper-section {
  font-size: 20pt; font-weight: 700; line-height: 1.18;
  margin: 5pt 0 3pt; color: #111;
}
.paper-ref {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-size: 9pt; color: #555;
}
.paper-body { }
.paper-body p, .paper-body li { orphans: 3; widows: 3; }
.paper-body h1, .paper-body h2, .paper-body h3, .paper-body h4 {
  page-break-after: avoid; break-after: avoid;
}
/* The reader renders its own section heading; print has our header instead. */
.docheading { display: none; }
.unitheading, .st-h {
  font-variant: small-caps; font-weight: 700; color: #111;
  border-bottom: .75pt solid #c9c9c9; padding-bottom: 2pt;
  margin: 13pt 0 6pt; font-size: 12.5pt; letter-spacing: .03em;
  page-break-after: avoid; break-after: avoid;
}
.st-sec.open .st-h, .st-sec .st-h { page-break-inside: avoid; }
.st-sec { page-break-inside: avoid; }
.st-sec.st-sec { page-break-inside: auto; }
.st-n { color: #7a5a1e; }
.verse { }
.vnum {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-size: .68em; font-weight: 700; color: #7a5a1e;
  vertical-align: super; padding-right: 3px; text-decoration: none;
}
.vnum:hover { background: none; }
.fn { color: #7a5a1e; text-decoration: none; font-size: .85em; }
.snums, .snum {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-size: .62em; vertical-align: super; color: #666; text-decoration: none;
}
.morphs { font-family: Helvetica, Arial, sans-serif; font-size: .6em;
  vertical-align: super; color: #7c5bd6; text-decoration: none; }
.wj { color: #8b0000; }
.supplied { color: #666; font-style: italic; }
.alt { color: #666; }
a { color: inherit; text-decoration: none; }
.paper-footer {
  border-top: .75pt solid #bbb; margin-top: 16pt; padding-top: 6pt;
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-size: 7.5pt; color: #777; line-height: 1.5;
}
.paper-footer b { color: #555; }
img { max-width: 100%; }
table { border-collapse: collapse; }
td, th { border: .5pt solid #ccc; padding: 3pt 6pt; font-size: 9.5pt; }
@media print {
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
`;
  },

  _frame() {
    let f = document.getElementById('print-frame');
    if (!f) {
      f = document.createElement('iframe');
      f.id = 'print-frame';
      f.title = 'Print';
      f.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
      document.body.appendChild(f);
    }
    return f;
  },

  _write(html) {
    const f = this._frame();
    const doc = f.contentDocument || f.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    const go = () => { try { f.contentWindow.focus(); f.contentWindow.print(); }
      catch (e) { /* iframe print blocked in some shells */ } };
    if (doc.readyState === 'complete') setTimeout(go, 80);
    else f.onload = () => setTimeout(go, 80);
  },

  _strip(node) {
    const clone = node.cloneNode(true);
    clone.removeAttribute('id');
    clone.classList.add('paper-body');
    /* Everything interactive is working chrome, not content. */
    clone.querySelectorAll(
      'button, select, input, textarea, iframe, script, style, '
      + '.pane-tools, .sgroups-bar, .morph-versions-picker, .morph-versions-out'
    ).forEach(x => x.remove());
    /* Anchors all become plain text: a printed page shows the words, not a link. */
    clone.querySelectorAll('a').forEach(a => {
      const sp = document.createElement('span');
      sp.textContent = a.textContent;
      if (a.className) sp.className = a.className;
      a.replaceWith(sp);
    });
    /* The loading spinner / empty states are app chrome too, if present. */
    clone.querySelectorAll('.st-loading, .empty').forEach(x => x.remove());
    return clone;
  },

  _moduleName(meta) {
    if (!meta) return 'G-Bible';
    return meta.moduleName || 'G-Bible';
  },

  _doc(title, bodyHtml, meta) {
    const moduleName = this._moduleName(meta);
    const section = (meta && meta.section) ? meta.section : '';
    const ref = (meta && meta.refLabel) ? meta.refLabel : '';
    const license = (meta && meta.license) || '';
    /* The section IS the title unless a reference exists; when both exist the
     * title is the reference-bearing section heading (a book/article name). */
    const docTitle = section || ref || moduleName;
    const footBits = [];
    if (license) footBits.push('<b>' + esc(moduleName) + '</b> — ' + esc(license));
    else footBits.push('<b>' + esc(moduleName) + '</b>');
    footBits.push('Printed from G-Bible · ' + new Date().toLocaleDateString());
    const html = '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
      + '<title>' + esc(title || docTitle) + '</title>\n'
      + '<style>' + this._css() + '</style>\n'
      + '</head>\n<body>\n'
      + '<div class="paper-header"><div class="paper-module">' + esc(moduleName)
      + '</div>'
      + (section ? '<div class="paper-section">' + esc(section) + '</div>' : '')
      + (ref ? '<div class="paper-ref">' + esc(ref) + '</div>' : '')
      + '</div>\n'
      + bodyHtml + '\n'
      + '<div class="paper-footer">' + footBits.join('<br>') + '</div>\n'
      + '</body>\n</html>';
    return html;
  },

  /* The generic primitive.  `node` is anything user-visible: a pane body, a
   * modal body, a search sink.  `meta`: { moduleName, section, refLabel,
   * license }. */
  printNode(node, meta) {
    if (!node) { toast('Nothing to print.', 'warn'); return; }
    const clone = this._strip(node);
    const html = this._doc((meta && meta.section) || (meta && meta.refLabel)
                              || this._moduleName(meta),
                            clone.outerHTML, meta || {});
    this._write(html);
  },

};
window.Print = Print;
