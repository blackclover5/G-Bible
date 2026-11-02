const Cite = {
  STYLES: null,
  FIELDS: null,
  /* Which formats each dialog offers is decided by the backend, in
   * `publish.document_formats`, and arrived with `cite/styles`.
   *
   * These were a hardcoded copy of all eight formats, which is how a passage
   * export came to offer BibTeX, RIS and CSV: `passage_document` writes five, so
   * those three buttons always failed, and because the failure was an HTTP 500
   * rather than a refusal, the anchor went on to save the error page as a file
   * called `John-3-16.bib`. A list kept in two places is a list one of them is
   * out of date. */
  DOCUMENTS: null,

  async _meta() {
    if (!this.STYLES) {
      const r = await api('cite/styles');
      this.STYLES = r.styles || [];
      this.FIELDS = r.fields || [];
      this.DOCUMENTS = r.document || {};
    }
  },

  /* The formats one document can be written as, in the order to offer them.
   * Falls back to the five every document supports rather than to the full list:
   * a wrong offer is a failed download, and a narrower offer is only a missing
   * convenience until the backend is reached. */
  _formats(kind) {
    const got = (this.DOCUMENTS || {})[kind];
    if (got && got.length) {
      return got.map(f => [f.id, f.label || f.id.toUpperCase()]);
    }
    return ['md', 'txt', 'html', 'rtf', 'pdf']
      .map(id => [id, id.toUpperCase()]);
  },

  /* Show the citation for one work, with its gaps and a way to fill them. */
  async open(moduleId, ref, short) {
    if (!moduleId) return;
    await this._meta();
    /* `short` is offered from the panel menu, where "Clarke, Commentary" is
     * usually what is wanted -- the full entry has already appeared in the
     * bibliography once, and the second reference to the same commentary in a
     * note is a short one. */
    const [style, full] = ['sbl', short !== true];
    const m = modById(moduleId) || {};
    modal('Cite: ' + (m.name || moduleId),
      '<div class="st-loading">Building…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const c = await api('cite/get', { id: moduleId, style, full: 1 });
    const body = $('#modal-body');
    if (!c.ok) { body.innerHTML = '<div class="st-body">' + esc(c.error) + '</div>'; return; }
    const meta = c.meta || {};

    const styleRow = '<div class="ct-styles">' + this.STYLES.map(s =>
      '<button class="ct-style' + (s.id === style ? ' on' : '') +
      '" data-style="' + esc(s.id) + '" title="' + esc(s.label) + '">' +
      esc(s.label.replace(/\(.*\)/, '')) + '</button>').join('') + '</div>';

    // The gap report.  Not a warning icon: a sentence saying what is missing.
    const gap = c.complete
      ? '<div class="ct-ok">Every field this style needs is filled in.</div>'
      : '<div class="ct-gap"><b>This citation is unfinished.</b> Missing: ' +
        c.missing.join(', ') + '. Nothing has been guessed — fill in what you ' +
        'know below and this becomes a citation you can hand to someone.' +
        '</div>';

    const editor = this.FIELDS.map(f => {
      const v = meta[f.id] || '';
      const missing = (c.missing || []).includes(f.id);
      return '<label class="ct-row' + (missing ? ' is-missing' : '') + '">' +
        '<span>' + esc(f.label) + '</span>' +
        '<input data-field="' + esc(f.id) + '" value="' + esc(v) +
        '" placeholder="' + (missing ? 'not recorded' : '') + '"></label>';
    }).join('');

    body.innerHTML =
      styleRow +
      '<div class="ct-out" id="ct-out">' + esc(c.citation) + '</div>' +
      (c.note ? '<div class="ct-note">' + esc(c.note) + '</div>' : '') +
      gap +
      (ref ? '<div class="ct-passage" id="ct-passage"></div>' : '') +
      '<details class="ct-details"><summary>Details you can fill in</summary>' +
      editor + '</details>' +
      '<div class="ct-lic" id="ct-lic"></div>';

    const paint = async (st, fl) => {
      const r = await api('cite/get', { id: moduleId, style: st, full: fl ? 1 : 0 });
      $('#ct-out').textContent = r.citation || r.error;
    };
    $$('.ct-style', body).forEach(b => {
      b.onclick = async () => {
        $$('.ct-style', body).forEach(x => x.classList.remove('on'));
        b.classList.add('on');
        await paint(b.dataset.style, full);
      };
    });
    $$('input[data-field]', body).forEach(inp => {
      inp.onchange = async () => {
        await api('cite/field', {
          id: moduleId, field: inp.dataset.field, value: inp.value,
        });
        await paint(style, full);
        // Re-render so the gap strip and the highlight update with it.  `short`
        // has to be carried across: it is a third argument, so dropping it here
        // silently flipped a short-form citation back to the full entry.
        this.open(moduleId, ref, short);
      };
    });
    if (ref) {
      const p = await api('cite/passage', { ref, id: moduleId, style, full: 1 });
      $('#ct-passage').innerHTML =
        '<div class="ct-ph-label">This passage</div>' +
        '<div class="ct-ph">' + esc(p.citation || p.error) + '</div>' +
        (p.note ? '<div class="ct-note">' + esc(p.note) + '</div>' : '') +
        '<div class="ct-do">This kind of citation is complete: the reference ' +
        'and the translation are facts, not metadata.</div>';
    }
    const lic = await api('cite/attribution', { ids: moduleId });
    $('#ct-lic').innerHTML = (lic.lines || []).map(l =>
      '<div class="ct-lic-line">' + esc(l) + '</div>').join('');
  },

  /* Copy a citation with its attribution, the way a footnote is wanted. */
  async copy(moduleId, ref) {
    const c = await api('cite/passage', { ref, id: moduleId, style: 'sbl', full: 1 });
    const a = await api('cite/attribution', { ids: moduleId });
    const text = (c.citation || '') + '\n' + (a.text || '');
    try {
      await navigator.clipboard.writeText(text);
      toast('Citation copied, with its licence.');
    } catch (e) {
      modal('Citation', '<textarea class="ct-out" rows="6">' + esc(text) +
        '</textarea>', [{ label: 'Close', cls: 'btn' }]);
    }
  },

  /* The bibliography, built from favourites, a collection, or everything. */
  async bibliography(presetIds) {
    await this._meta();
    let ids = presetIds || [];
    if (!ids.length) {
      const fav = (await api('favorites')).favorites || [];
      ids = fav.map(f => f.id);
    }
    modal('Bibliography',
      '<div class="st-loading">Building…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const body = $('#modal-body');
    const draw = async (style, fmt) => {
      const r = await api('cite/bibliography', { ids: ids.join(','), style });
      if (!r.ok) { body.innerHTML = esc(r.error); return; }
      const gap = r.flagged && r.flagged.length
        ? '<div class="ct-gap"><b>' + r.flagged.length + ' of ' + r.count +
          ' entries are missing fields.</b> They are marked rather than filled ' +
          'in with a guess. Open one to supply what you know.</div>'
        : '<div class="ct-ok">Every entry has the fields its style needs.</div>';
      body.innerHTML =
        '<div class="ct-styles">' + this.STYLES.map(s =>
          '<button class="ct-style' + (s.id === style ? ' on' : '') +
          '" data-style="' + esc(s.id) + '">' +
          esc(s.label.replace(/\(.*\)/, '')) + '</button>').join('') + '</div>' +
        gap +
        '<div class="ct-bib">' + r.entries.map(e =>
          '<div class="ct-entry' + (e.complete ? '' : ' is-incomplete') + '">' +
          esc(e.citation.replace(/\*/g, '')) +
          (e.complete ? '' : '<span class="ct-tag">missing ' +
            esc(e.missing.join(', ')) + '</span>') + '</div>').join('') +
        '</div>' +
        '<div class="ct-exports">' + this._formats('bibliography').map(f =>
          '<button class="ct-fmt" data-fmt="' + f[0] + '" title="' + esc(f[1]) +
          '">' + esc(f[0].toUpperCase()) + '</button>').join('') +
        '<button class="ct-fmt ct-print" data-fmt="__print">Print</button>' +
        '</div>';
      $$('.ct-style', body).forEach(b => {
        b.onclick = () => draw(b.dataset.style, fmt);
      });
      $$('.ct-fmt', body).forEach(b => {
        b.onclick = () => {
          if (b.dataset.fmt === '__print') return Cite._printBib(ids, style);
          const url = '/file/bibliography?ids=' + encodeURIComponent(ids.join(',')) +
            '&style=' + style + '&fmt=' + b.dataset.fmt;
          Cite._save(url, 'bibliography.' + b.dataset.fmt);
        };
      });
    };
    if (!ids.length) {
      body.innerHTML = '<div class="st-body">No favourites yet, so there is nothing ' +
      'to build a bibliography from. Choose what to cite instead.</div>';
      return Cite._pickSources(picked => Cite.bibliography(picked));
    }
    await draw('sbl', 'md');
  },

  /* Choose what goes in the bibliography.
   *
   * Without this the feature had no door: both Library buttons called
   * `Cite.bibliography()` with no argument, which fell back to favourites, so a
   * reader with no favourites got the message "call Cite.bibliography([...ids])
   * from the console" -- which is not an answer to a request made in a browser.
   * It offers the three things a person actually means by "my sources": the
   * favourites, one collection, or everything installed.
   */
  async _pickSources(onPick) {
    modal('Bibliography: choose resources',
      '<div class="st-loading">Reading your library…</div>',
      [{ label: 'Cancel', cls: 'btn' }]);
    const body = $('#modal-body');
    const lib = await api('library');
    const mods = (lib.modules || []).filter(m => m.installed_at);
    const favs = (await api('favorites')).favorites || [];
    // `collection` returns the whole set in one call: each entry carries its own
    // `modules` list and a `count`, so there is no per-collection request to make.
    const cols = (await api('collection')).collections || [];
    const opt = (id, label, n) =>
      '<button class="btn ct-pick" data-src="' + esc(id) + '">' +
      esc(label) + ' <span class="muted tiny">(' + n + ')</span></button>';
    body.innerHTML =
      '<div class="st-body" style="display:flex;gap:8px;flex-wrap:wrap">' +
      opt('fav', 'My favourites', favs.length) +
      opt('all', 'Everything installed', mods.length) +
      cols.map(c => opt('col:' + c.id, c.name, c.count)).join('') +
      '</div>';
    $$('.ct-pick', body).forEach(b => {
      b.onclick = () => {
        const src = b.dataset.src;
        let ids = [];
        if (src === 'all') ids = mods.map(m => m.id);
        else if (src === 'fav') ids = favs.map(f => f.id);
        else {
          const c = cols.find(x => 'col:' + x.id === src);
          ids = ((c && c.modules) || []).map(m => m.module_id);
        }
        closeModal();
        Cite.bibliography(ids);
      };
    });
  },

  async _printBib(ids, style) {
    const r = await api('cite/bibliography', { ids: ids.join(','), style });
    if (!r.ok) return;
    Cite._printHtml(
      '<h1>Bibliography</h1><p class="meta">' + esc(
        r.entries.length + ' entries') + '</p>' +
      r.entries.map(e => '<p class="entry">' + esc(
        e.citation.replace(/\*/g, '')) + '</p>').join(''),
      'Bibliography');
  },

  /* Export one passage, in whatever format, with the licences attached. */
  async exportPassage(ref, moduleIds) {
    await this._meta();
    const ids = (moduleIds && moduleIds.length) ? moduleIds :
      ((S.layout && S.layout.panes) || []).map(p => p.module_id);
    modal('Export: ' + ref, '<div class="st-loading">…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const body = $('#modal-body');
    body.innerHTML =
      '<div class="ct-do">Every format below carries the licence of the ' +
      'material it quotes, because CC BY 4.0 requires attribution and an ' +
      'export without it would be a breach of the licence.</div>' +
      '<div class="ct-exports">' + this._formats('passage').map(f =>
        '<button class="ct-fmt" data-fmt="' + f[0] + '" title="' + esc(f[1]) +
        '">' + esc(f[0].toUpperCase()) + '</button>').join('') +
      '<button class="ct-fmt ct-print" data-fmt="__print">Print</button></div>';
    $$('.ct-fmt', body).forEach(b => {
      b.onclick = () => {
        if (b.dataset.fmt === '__print') {
          const url = '/file/passage?ref=' + encodeURIComponent(ref) +
            '&ids=' + encodeURIComponent(ids.join(',')) + '&fmt=html';
          fetch(url).then(r => r.text()).then(h => Cite._printHtml(h, ref));
          return;
        }
        const url = '/file/passage?ref=' + encodeURIComponent(ref) +
          '&ids=' + encodeURIComponent(ids.join(',')) + '&fmt=' + b.dataset.fmt;
        Cite._save(url, ref.replace(/[^A-Za-z0-9]+/g, '-') + '.' + b.dataset.fmt);
      };
    });
  },

  /* Print a generated document rather than the application.
   * Printing the app itself gives you panes, tabs and sidebars; what a person
   * wants on paper is the document. */
  _printHtml(html, title) {
    let f = document.getElementById('print-frame');
    if (!f) {
      f = document.createElement('iframe');
      f.id = 'print-frame';
      f.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
      document.body.appendChild(f);
    }
    const doc = f.contentDocument || f.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    const go = () => { try { f.contentWindow.print(); } catch (e) {} };
    if (doc.readyState === 'complete') setTimeout(go, 120);
    else f.onload = () => setTimeout(go, 120);
  },

  /* Downloads go through a real anchor so the browser names the file and the
   * export never passes through a data: URL of unbounded size. */
  _save(url, filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  },
};

/* Sections a passage view already lays out well, and so are not repeated in
 * the configured-guide block below. */