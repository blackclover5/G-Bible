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
      if (!r || r.ok === false || !(r.styles || []).length) return;
      this.STYLES = r.styles;
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
  async open(moduleId, ref, short, styleWanted) {
    if (!moduleId) return;
    await this._meta();
    /* `short` is offered from the panel menu, where "Clarke, Commentary" is
     * usually what is wanted -- the full entry has already appeared in the
     * bibliography once, and the second reference to the same commentary in a
     * note is a short one. */
    const style = styleWanted || 'sbl';
    const full = short !== true;
    modal('Cite: ' + modLabel(moduleId),
      '<div class="st-loading">Building…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const c = await api('cite/get', { id: moduleId, style, full: full ? 1 : 0 });
    const body = $('#modal-body');
    if (!c || c.ok === false) {
      body.innerHTML = '<div class="warn">' + esc((c && c.error) || 'Could not build the citation.') + '</div>';
      return;
    }
    const meta = c.meta || {};

    const styleRow = '<div class="ct-styles">' + this.STYLES.map(s =>
      '<button class="ct-style' + (s.id === style ? ' on' : '') +
      '" data-style="' + esc(s.id) + '" title="' + esc(s.label) + '">' +
      esc(s.label.replace(/\(.*\)/, '')) + '</button>').join('') + '</div>';

    // The gap report.  Not a warning icon: a sentence saying what is missing.
    const gap = c.complete
      ? '<div class="ct-ok">Every field this style needs is filled in.</div>'
      : '<div class="ct-gap"><b>This citation is unfinished.</b> Missing: ' +
        esc((c.missing || []).join(', ')) + '. Nothing has been guessed — fill in what you ' +
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

    $$('.ct-style', body).forEach(b => {
      b.onclick = async () => {
        // A partial repaint left the old gap report and missing-field marks
        // on screen under the new style's citation.
        await this.open(moduleId, ref, short, b.dataset.style);
      };
    });
    $$('input[data-field]', body).forEach(inp => {
      inp.onchange = async () => {
        const r = await api('cite/field', {
          id: moduleId, field: inp.dataset.field, value: inp.value,
        });
        if (!r || r.ok === false) {
          toast((r && r.error) || 'Could not save that field.', 'err'); return;
        }
        // Re-render with the current style and short/full choice: a partial
        // repaint used to leave the old gap report on screen.
        this.open(moduleId, ref, short, style);
      };
    });
    if (ref) {
      const p = await api('cite/passage', { ref, id: moduleId, style, full: full ? 1 : 0 });
      if (!p || p.ok === false) {
        $('#ct-passage').innerHTML = '<div class="warn">'
          + esc((p && p.error) || 'Could not cite this passage.') + '</div>';
      } else {
        $('#ct-passage').innerHTML =
          '<div class="ct-ph-label">This passage</div>' +
          '<div class="ct-ph">' + esc(p.citation) + '</div>' +
          (p.note ? '<div class="ct-note">' + esc(p.note) + '</div>' : '') +
          '<div class="ct-do">This kind of citation is complete: the reference ' +
          'and the translation are facts, not metadata.</div>';
      }
    }
    const lic = await api('cite/attribution', { ids: moduleId });
    $('#ct-lic').innerHTML = (!lic || lic.ok === false)
      ? '<div class="tiny muted">' + esc((lic && lic.error)
        || 'Licence information could not be read.') + '</div>'
      : (lic.lines || []).map(l =>
        '<div class="ct-lic-line">' + esc(l) + '</div>').join('');
  },

  /* Copy a citation with its attribution, the way a footnote is wanted. */
  async copy(moduleId, ref) {
    const c = await api('cite/passage', { ref, id: moduleId, style: 'sbl', full: 1 });
    const a = await api('cite/attribution', { ids: moduleId });
    if (!c || c.ok === false || !a || a.ok === false) {
      toast((c && c.error) || (a && a.error) || 'Could not build the citation.', 'err');
      return;
    }
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
        '</div>';
      $$('.ct-style', body).forEach(b => {
        b.onclick = () => draw(b.dataset.style, fmt);
      });
      $$('.ct-fmt', body).forEach(b => {
        b.onclick = () => {
          const url = '/file/bibliography?ids=' + encodeURIComponent(ids.join(',')) +
            '&style=' + style + '&fmt=' + b.dataset.fmt;
          Cite.download(url, 'bibliography.' + b.dataset.fmt);
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

  /* Fetch first, then save the bytes we actually received.  An anchor alone
   * saved the server's error page as a file called *.pdf and still toasted
   * "Saved", which is a promise the app could not keep. */
  async download(url, filename) {
    try {
      const r = await fetch(url, {
        headers: { 'X-GBible-CSRF-Token': CSRF_TOKEN } });
      if (!r.ok) {
        toast('Could not build that file (HTTP ' + r.status + ').', 'err');
        return false;
      }
      const blob = await r.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 30000);
      return true;
    } catch (e) {
      toast((e && e.message) || 'Could not build that file.', 'err');
      return false;
    }
  },
};

/* Sections a passage view already lays out well, and so are not repeated in
 * the configured-guide block below. */