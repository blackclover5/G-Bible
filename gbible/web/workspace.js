const Workspace = {
  async openModule(moduleId, cursor, opts) {
    const lay = S.layout;
    const used = new Set(lay.panes.map(p => (p.tile_id || 't0') + ':' + p.module_id));
    // Tile ids are generated in layout order and rendered in the same order, so
    // the first N of them are the ones actually on screen.  A new pane landing
    // in a tile that is not displayed is a pane you cannot see: following a
    // reference link appeared to do nothing, because the reference went to a
    // module whose only pane was on a hidden tile.
    const ids = App.leafTileIds(lay.tiles || [[1.0]]);
    const onScreen = new Set(ids.slice(0, $$('.tile').length));
    let tile = 't0_0', link = '';
    for (const pass of [true, false]) {
      for (const tid of ids) {
        if (pass && !onScreen.has(tid)) continue;
        if (!pass && onScreen.has(tid)) continue;
        if (used.has(tid + ':' + moduleId)) continue;
        tile = tid;
        break;
      }
      if (tile !== 't0_0' || !used.has('t0_0:' + moduleId)) break;
    }
    if (used.has(tile + ':' + moduleId)) tile = 't0_0';
    const r = await post('workspace/pane', {
      action: 'add', layout: lay.id, module: moduleId, tile: tile,
      cursor: cursor || {}, options: opts || {}, link_set: link });
    await App.loadWorkspace();
    const p = r.pane;
    /* A tile draws tp[0] -- the first pane filed under it -- so a pane added to
     * a tile that already has one is saved correctly and then never shown.  The
     * Library's Open button looked like it did nothing.  Select the new pane. */
    App.showPane(tile, p.id);
    return p;
  },

  async openModuleIn(tile, moduleId, cursor, opts) {
    const lay = S.layout;
    const r = await post('workspace/pane', {
      action: 'add', layout: lay.id, module: moduleId, tile: tile,
      cursor: cursor || {}, options: opts || {}, link_set: '' });
    await App.loadWorkspace();
    const p = r.pane;
    App.showPane(tile, p.id);
    return p;
  },

  async pickModule(tile) {
    const list = S.modules.slice().sort((a, b) =>
      (a.type + a.name).localeCompare(b.type + b.name));
    if (!list.length) { toast('Install something from the Store first.'); return; }
    const types = [...new Set(list.map(m => m.type_label || m.type))].sort();
    const langs = [...new Set(list.map(m => m.lang_name || m.lang).filter(Boolean))].sort();
    const srcs = [...new Set(list.map(m => m.source_name || m.source).filter(Boolean))].sort();
    const sel = (id, opts, ph) => '<select id="' + id + '" style="width:130px">'
      + '<option value="">' + esc(ph) + '</option>'
      + opts.map(o => '<option>' + esc(o) + '</option>').join('') + '</select>';
    modal('Open a resource',
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">'
      + sel('pm-type', types, 'All types')
      + sel('pm-lang', langs, 'All languages')
      + sel('pm-src', srcs, 'All sources')
      + '<input type="search" id="pm-q" placeholder="Search…" style="width:140px">'
      + '<label class="tiny"><input type="checkbox" id="pm-det"> Details</label>'
      + '</div>'
      + '<div class="store-list" style="max-height:55vh;padding:0" id="pm-list"></div>',
      [{ label: 'Cancel', cls: 'btn' }]);
    const paint = () => {
      const t = $('#pm-type').value, l = $('#pm-lang').value,
        s = $('#pm-src').value, q = ($('#pm-q').value || '').toLowerCase(),
        det = $('#pm-det').checked;
      const rows = list.filter(m =>
        (!t || (m.type_label || m.type) === t)
        && (!l || (m.lang_name || m.lang) === l)
        && (!s || (m.source_name || m.source) === s)
        && (!q || (m.name + ' ' + (m.author || '') + ' ' + (m.description || '')).toLowerCase().includes(q)));
      $('#pm-list').innerHTML = rows.length ? rows.map(m =>
        '<div class="item" data-id="' + esc(m.id) + '"><div style="flex:1">'
        + '<div class="t">' + esc(m.name) + '</div><div class="m">'
        + '<span class="chip">' + esc(m.type_label) + '</span>'
        + '<span>' + esc(m.lang_name || m.lang) + '</span>'
        + (m.license ? '<span class="chip ' + liccls(m.license) + '">' + esc(m.license) + '</span>' : '')
        + (det ? '<div class="tiny muted">' + esc((m.description || '').slice(0, 120)) + '</div>' : '')
        + '</div></div></div>').join('')
        : '<div class="empty">Nothing matches those filters.</div>';
      $$('#pm-list .item').forEach(n => n.onclick = () => {
        closeModal();
        this.openModuleIn(tile, n.dataset.id);
      });
    };
    ['#pm-type', '#pm-lang', '#pm-src'].forEach(id => {
      $(id).onchange = paint;
    });
    $('#pm-q').oninput = debounce(paint, 180);
    $('#pm-det').onchange = paint;
    paint();
  },

  async split(paneId, direction) {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const src = (lay.panes || []).find(x => x.id === paneId);
    if (!src) { toast('That pane is no longer open.', 'warn'); return; }
    const dir = direction === 'column' ? 'column' : 'row';
    const tileId = App.tileKey(src.tile_id);
    const tree = App.ensureTiles();
    S.layout.tiles = tree;
    const newTileId = 't' + Date.now().toString(36)
      + Math.random().toString(36).slice(2, 6);
    const done = App.splitTile(tree, tileId, dir, newTileId);
    if (!done) { toast('Could not split this pane.', 'warn'); return; }
    let r = null;
    try {
      r = await post('workspace/pane', {
        action: 'add', layout: lay.id, module: src.module_id || '',
        tile: newTileId, cursor: src.cursor || {}, view: src.view || 'normal',
        options: src.options || {}, link_set: '', text_size: src.text_size || 100 });
    } catch (e) {
      toast('Could not add a pane: ' + (e.message || e), 'warn');
      return;
    }
    if (!r || !r.pane) { toast('Could not add a pane.', 'warn'); return; }
    lay.panes.push(r.pane);
    const sv = await post('workspace/save', {
      id: lay.id, name: lay.name || 'Layout',
      tiles: tree, panes: lay.panes });
    if (sv && sv.layout) S.layout = sv.layout;
    await App.loadWorkspace();
    App.showPane(newTileId, r.pane.id);
  },

  async openGuidePane(ref) {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const ids = App.leafTileIds(lay.tiles || [[1.0]]);
    let tile = ids[0] || 't0_0';
    const r = await post('workspace/pane', {
      action: 'add', layout: lay.id, module: '', tile: tile,
      cursor: { ref: ref || '', guide: 'passage' }, view: 'guide',
      options: {}, link_set: '' });
    if (!r || !r.pane) { toast('Could not open a guide pane.', 'warn'); return; }
    await App.loadWorkspace();
    App.showPane(tile, r.pane.id);
    return r.pane;
  },

  async openWordStudyPane(number) {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const ids = App.leafTileIds(lay.tiles || [[1.0]]);
    let tile = ids[0] || 't0_0';
    const r = await post('workspace/pane', {
      action: 'add', layout: lay.id, module: '', tile: tile,
      cursor: { number: number || '' }, view: 'wordstudy',
      options: {}, link_set: '' });
    if (!r || !r.pane) { toast('Could not open a Word Study pane.', 'warn'); return; }
    await App.loadWorkspace();
    App.showPane(tile, r.pane.id);
    return r.pane;
  },

  async floatPane(paneId) {
    const p = (S.layout.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    const tile = $('.tile[data-tile="' + App.tileKey(p.tile_id) + '"]');
    const paneEl = tile ? $('.pane', tile) : null;
    const html = paneEl ? paneEl.outerHTML : '';
    const m = modById(p.module_id);
    const title = (m ? m.name : (p.view === 'guide' ? 'Passage' : (p.view === 'wordstudy' ? 'Word Study' : 'Pane')))
      + (p.cursor && (p.cursor.ref || p.cursor.number) ? ' — ' + (p.cursor.ref || p.cursor.number) : '');
    const w = window.open('', '_blank', 'width=900,height=700,menubar=no,toolbar=no');
    if (!w) { toast('Pop-up blocked — allow pop-ups for this site.', 'warn'); return; }
    w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>'
      + title.replace(/</g, '&lt;') + '</title>'
      + '<style>body{font-family:system-ui,sans-serif;margin:16px;line-height:1.5}'
      + '.pane{max-width:900px;margin:0 auto} .pane-body{font-size:1.05em}'
      + 'button,input{font:inherit}</style></head><body>'
      + '<h2>' + title.replace(/</g, '&lt;') + '</h2>'
      + html + '</body></html>');
    w.document.close();
    toast('Opened in a new window.');
  },

  async closeAll() {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const panes = (lay.panes || []).slice();
    for (const p of panes) {
      try { await post('workspace/pane', { action: 'close', pane: p.id }); } catch (e) {}
    }
    await App.loadWorkspace();
    toast('All panes closed.');
  },

  async closePane(paneId) {
    const lay = S.layout;
    const target = lay && (lay.panes || []).find(x => x.id === paneId);
    const tileId = target ? App.tileKey(target.tile_id) : null;
    await post('workspace/pane', { action: 'close', pane: paneId });
    await App.loadWorkspace();
    // A tile left with no panes in it goes away entirely -- an empty slot with
    // an "Open a resource" prompt is a tile the reader has already said they
    // are done with.  The one exception is the last tile standing: with nothing
    // left at all there would be nowhere to open the next thing from.
    if (tileId && S.layout) {
      const rest = S.layout.panes || [];
      const inTile = rest.filter(x => App.tileKey(x.tile_id) === tileId);
      const elsewhere = rest.filter(x => App.tileKey(x.tile_id) !== tileId);
      if (!inTile.length && elsewhere.length) {
        const pruned = App.removeTileLeaf(App.ensureTiles(), tileId);
        if (pruned) {
          S.layout.tiles = pruned;
          await App.saveCurrentTree();
          await App.loadWorkspace();
        }
      }
    }
  },

  async propagate(p) {
    const links = await api('workspace/link', { pane: p.id, cursor: p.cursor });
    (links.links || []).forEach(L => {
      if (L.action === 'none') return;
      const t = S.layout.panes.find(x => x.id === L.pane_id);
      if (!t) return;
      t.cursor = Object.assign({}, t.cursor, L.cursor);
      if (L.shared.indexOf('bibleVerse') >= 0 && L.cursor.ref) {
        const near = L.cursor.ref;
        t.cursor.ref = near;
      }
      if (L.shared.indexOf('strongs') >= 0 && L.cursor.strongs) {
        t.cursor.number = L.cursor.strongs;
        t.cursor.strongs = L.cursor.strongs;
      }
      const pane = $('.pane[data-pane="' + t.id + '"]');
      if (pane) App.fillPane(pane, t);
    });
    /* The Info follow-pane tracks the cursor that just moved. */
    try {
      const ref = (p.cursor && p.cursor.ref) || '';
      if (ref) InfoPane.maybeRefresh(ref);
    } catch (e) { /* never break linking */ }
  },

  /* Pack 1 extras: arrangements without closing panes, one-click unlink,
   * QuickStart layouts, Top Bible, parallel prev/next, reading progress,
   * copy-location. All thin wrappers over the JSON API. */
  async arrange(name) {
    const r = await post('workspace/arrange', { arrangement: name });
    if (r.layout) S.layout = r.layout;
    await App.loadWorkspace();
  },
  async clearLinks() {
    await post('workspace/clear_links', {});
    await App.loadWorkspace();
    toast('All link sets cleared.');
  },
  async quickstarts() { return api('workspace/quickstarts', {}); },
  async quickstart(name) {
    const r = await post('workspace/quickstart', { name });
    if (r.layout) S.layout = r.layout;
    await App.loadWorkspace();
  },
  async topBible(id) {
    if (id === undefined) return api('workspace/top_bible', {});
    const r = await post('workspace/top_bible', { action: 'set', id });
    if (!r.ok) toast(r.error || 'Could not set Top Bible.', 'warn');
    return r;
  },
  async parallel(moduleId, collectionId) {
    return api('workspace/parallel', { module: moduleId, collection: collectionId || '' });
  },
  async parallelStep(moduleId, dir, collectionId) {
    const r = await api('workspace/parallel', {
      module: moduleId, direction: dir > 0 ? 'next' : 'prev',
      collection: collectionId || '' });
    if (r.ok && r.module_id) this.openModule(r.module_id, {});
    return r;
  },
  async markProgress(moduleId, key, label, pct) {
    return post('workspace/progress', { action: 'mark', module: moduleId, key, label, pct });
  },
  async progress() { return api('workspace/progress', {}); },
  async resetProgress(moduleId) {
    return post('workspace/progress', { action: 'reset', module: moduleId || '' });
  },
  async copyLocation(paneId) {
    const r = await api('workspace/copy_location', { pane: paneId });
    if (r.ok && r.text && navigator.clipboard) {
      try { await navigator.clipboard.writeText(r.text); toast('Copied: ' + r.text); }
      catch (e) { toast(r.text); }
    } else if (r.text) toast(r.text);
    return r;
  },

  /* Pack 6 extras: layouts dialog, fullscreen reading, progress bookmark,
   * reader's-edition toggle. */
  async layoutsDialog() {
    const [qs, tb] = await Promise.all([
      this.quickstarts().catch(() => ({ quickstarts: [] })),
      this.topBible().catch(() => ({})),
    ]);
    const names = Object.keys(S.arrangements || {});
    const row = (label, body) => '<h4 style="margin:12px 0 4px">' + label + '</h4>' + body;
    modal('Layouts',
      row('Rearrange open panes — nothing closes',
        '<div class="row wrap">' + names.map(n =>
          '<button class="btn" data-arr="' + esc(n) + '">' + esc(n) + '</button>').join('')
        + '</div>')
      + row('Start from a task',
        '<div class="row wrap">' + (qs.quickstarts || []).map(q =>
          '<button class="btn" data-qs="' + esc(q.name) + '" title="' + esc(q.about || '') + '">'
          + esc(q.name) + '</button>').join('') + '</div>')
      + row('Links', '<div class="row wrap"><button class="btn" data-clear="1">'
        + 'Clear links in all panels</button></div>'
        + '<div class="tiny muted" style="margin-top:4px">Top Bible: '
        + esc((tb && tb.name) || '(automatic)') + '</div>'),
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body button[data-arr]').forEach(b => b.onclick = async () => {
      closeModal(); await this.arrange(b.dataset.arr);
    });
    $$('#modal-body button[data-qs]').forEach(b => b.onclick = async () => {
      closeModal(); await this.quickstart(b.dataset.qs);
    });
    const cl = $('#modal-body button[data-clear]');
    if (cl) cl.onclick = async () => { closeModal(); await this.clearLinks(); };
  },
  async fullscreen(paneId) {
    const p = (S.layout.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    const m = (S.modules || []).find(x => x.id === p.module_id);
    const r = await api('read', { id: p.module_id, cursor: p.cursor || {},
      options: p.options || {}, span: 'chapter' }).catch(() => null);
    const items = (r && r.items) || [];
    modal((m ? m.name : '') + (p.cursor && p.cursor.ref ? ' — ' + p.cursor.ref : ''),
      '<div style="font-size:1.25em;line-height:1.7;max-height:70vh;overflow:auto">'
      + items.map(i => i.html || '').join('') + '</div>',
      [{ label: 'Close', cls: 'btn' }]);
  },
  async markHere(paneId) {
    const p = (S.layout.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    const ref = (p.cursor && (p.cursor.ref || p.cursor.date || p.cursor.key)) || '';
    await this.markProgress(p.module_id, ref, ref, 0);
    toast(ref ? 'Bookmarked: ' + ref : 'Position bookmarked.');
  },
  async edition(paneId, preset) {
    const r = await api('reader/edition', { preset }).catch(() => null);
    if (!r || !r.options) { toast('Could not load that edition.', 'warn'); return; }
    await post('workspace/pane', { pane: paneId, options: r.options });
    await App.loadWorkspace();
    toast(preset === 'clean' ? 'Reader’s edition: running text.' : 'Study edition restored.');
  },
};

function liccls(l) {
  const s = String(l).toLowerCase();
  if (s.includes('public domain')) return 'pd';
  if (s.includes('cc0')) return 'pd';
  if (s.includes('sa')) return 'sa';
  if (s.includes('by')) return 'cc';
  return 'no';
}

/* ========================================================== PanelMenu */
function PanelMenu(p, m, body) {
  const mods = S.modules.filter(x => x.id !== m.id);
  const setO = (k, v) => post('workspace/pane', { pane: p.id, [k]: v }).then(App.loadWorkspace.bind(App));
  /* A citation for *this* resource, and its licence, whichever kind of resource
   * it is. The three citation entries in the verse reader's right-click menu were
   * the only route to them, and that menu is only wired when the pane's reader is
   * `verse` -- so a lexicon, a fact book, a grammar, a concordance or a map could
   * not be cited at all, which is backwards: those are the works a bibliography
   * is mostly made of. `p.cursor.ref` is the reference being read, if any. */
  const citeAt = (p.cursor && p.cursor.ref) || '';
  const citeButtons = '<h4 style="margin-top:14px">Cite this</h4>'
    + '<div class="row wrap" style="margin-top:6px">'
    + '<button class="btn" data-cite="full">Citation'
    + (citeAt ? '' : ' (no reference open)') + '</button>'
    + '<button class="btn" data-cite="short">Short form</button>'
    + '<button class="btn" data-cite="copy">Copy with licence</button>'
    + '</div>';
  /* Re-index reads the module's own files again and rebuilds its units.  It is
   * offered only where there is something to re-read: a module whose folder is
   * not on disk has nothing to index, and a button that can only ever report
   * "the source files are gone" is noise on the panel for a normal module.
   * The server checks and refuses anyway -- this is about not offering it.
   *
   * It also refuses when the re-parse disagrees with what is installed, which on
   * most modules it does: the installer split the file by chapters, and the
   * files it left behind are re-split more crudely here.  So in practice this
   * either repairs a module whose parse round-trips exactly, or says why it
   * will not and points at the Store. */
  const reindexable = m.installed_at > 0 && !!m.path;
  const reindexButton = reindexable
    ? '<h4 style="margin-top:14px">Maintenance</h4>'
      + '<div class="row wrap" style="margin-top:6px">'
      + '<button class="btn" data-reindex="1">Re-index from its files</button>'
      + '</div><div class="tiny muted" style="margin-top:4px">Re-reads the '
      + 'source files and rebuilds this module&#8217;s units. It downloads '
      + 'nothing and touches no other module — and it refuses if the files '
      + 're-parse to a different shape than what is installed, because '
      + 're-indexing replaces. Re-import from the Store is the reliable route.</div>'
    : (m.installed_at > 0
        ? '<div class="tiny muted" style="margin-top:12px">The files this '
          + 'module was installed from are not on disk, so it cannot be '
          + 're-indexed. Its text is in the index and searchable; re-import '
          + 'it from the Store to put the files back.</div>' : '');
  modal(m.name,
    '<table class="kv">'
    + '<tr><td>Type</td><td>' + esc(m.type_label || m.type) + '</td></tr>'
    + '<tr><td>Language</td><td>' + esc(m.lang_name || m.lang || '—') + '</td></tr>'
    + '<tr><td>Licence</td><td><span class="chip ' + liccls(m.license) + '">'
    + esc(m.license || '—') + '</span></td></tr>'
    + (m.rights ? '<tr><td>Attribution</td><td class="tiny">' + esc(m.rights) + '</td></tr>' : '')
    + '<tr><td>Source</td><td>' + (m.source_url
      ? '<a href="' + esc(m.source_url) + '" target="_blank" rel="noopener">'
        + esc(m.source_name || m.source) + '</a>' : esc(m.source_name || '—')) + '</td></tr>'
    + '<tr><td>Format</td><td>' + esc(m.format || '—') + '</td></tr>'
    + '<tr><td>Units</td><td>' + (m.units || 0).toLocaleString() + '</td></tr>'
    + (m.versification ? '<tr><td>Versification</td><td>' + esc(m.versification)
      + ' (' + esc(m.v11n_source) + ')</td></tr>' : '')
    + '<tr><td>Milestone types</td><td class="tiny">' + esc((m.index_types || []).join(', ')) + '</td></tr>'
    + '<tr><td>Features</td><td class="tiny">'
    + [m.has_strongs ? 'Strong’s' : '', m.has_morph ? 'morphology' : '',
       m.has_notes ? 'footnotes' : '', m.has_xref ? 'cross-references' : '',
       m.has_redletter ? 'words of Christ' : ''].filter(Boolean).join(', ') + '</td></tr>'
    + '</table>'
    + citeButtons
    + reindexButton
    + '<h4 style="margin-top:14px">Link with these</h4><div class="tiny muted">'
    + 'Only resources with an overlapping milestone type can be linked.</div>'
    + '<div class="row wrap" style="margin-top:6px">'
    + mods.map(x => '<button class="btn" data-open="' + esc(x.id) + '">'
      + esc(x.name) + '</button>').join('') + '</div>',
    [{ label: 'Close', cls: 'btn' }]);
  $$('#modal-body button[data-open]').forEach(b => b.onclick = () => {
    closeModal();
    Workspace.openModule(b.dataset.open, p.cursor, p.options);
  });
  $$('#modal-body button[data-cite]').forEach(b => b.onclick = () => {
    const how = b.dataset.cite;
    if (how === 'copy') {
      Cite.copy(m.id, citeAt);
      return;
    }
    closeModal();
    Cite.open(m.id, citeAt, how === 'short');
  });
  const rx = $('#modal-body button[data-reindex]');
  if (rx) {
    rx.onclick = async () => {
      rx.disabled = true;
      rx.textContent = 'Re-indexing…';
      /* This rebuilds one module's units, which on a large book is real work
       * with a visible pause, so the button says so rather than appearing to
       * have done nothing. */
      const r = await api('reindex', { id: m.id });
      closeModal();
      if (!r.ok) {
        toast(r.error || 'Could not re-index that.', 'err');
        return;
      }
      await App.loadLibrary();
      await App.loadWorkspace();
      toast('Re-indexed ' + m.name + ' — ' + (r.units || 0) + ' units.');
    };
  }
}

/* ============================================================== Search */
const Search = {
  /* 'group' = one collapsible section per resource, 'flat' = the old list. */
  group: 'group',

  /* Keep the hits as a passage list -- the verses, in passage order.
   *
   * One version only.  Keys mean different things in different translations, so
   * a list built across five of them is a list of nothing; and the first hit's
   * resource is the one the search ranked highest, which is the one you were
   * reading. */
  async toPassageList(hits) {
    if (!hits || !hits.length) { toast('No results to save.', 'warn'); return; }
    const name = prompt('Name this passage list',
      ((S.search && S.search.query) || 'Passages').slice(0, 40));
    if (!name) return;
    const made = await api('passagelist', { action: 'save', name });
    if (!made.ok) { toast(made.error || 'Could not make that list.', 'err'); return; }
    const mod = hits[0].module_id;
    let n = 0, skipped = 0;
    for (const h of hits) {
      if (h.module_id !== mod) { skipped++; continue; }
      const r = await api('passagelist', { action: 'add', id: made.id,
        key: h.key, ref: h.label, module: h.module_id });
      if (r.ok && !r.unchanged) n++;
    }
    toast(n + ' passages in "' + name + '"'
      + (skipped ? ' · ' + skipped + ' skipped (a different translation)' : '')
      + '.');
    App.show('organise');
  },

  /* The saved searches, as chips above the results. */
  async loadTemplates() {
    const host = $('#search-tpl');
    if (!host) return;
    const r = await api('search/template');
    const rows = r.templates || [];
    if (!rows.length) { host.innerHTML = ''; host.style.display = 'none'; return; }
    host.style.display = '';
    host.innerHTML = '<span class="tiny muted">Saved:&nbsp;</span>'
      + rows.map(t => '<a href="#" class="chip" data-tplrun="' + esc(t.id)
        + '" title="' + esc(t.query) + '">' + esc(t.name) + '</a>').join(' ')
      + '<a href="#" class="tiny muted" id="tpl-manage">manage</a>'
      + ' <a href="#" class="tiny muted" id="tpl-gallery">gallery</a>';
    host.onclick = async (e) => {
      const run = e.target.closest('a[data-tplrun]');
      if (run) {
        const t = rows.find(x => x.id === run.dataset.tplrun);
        if (t) { $('#sq').value = t.query; Search.go(); }
        return;
      }
      if (e.target.id === 'tpl-gallery') { Search.gallery(); return; }
      if (e.target.id === 'tpl-manage') App.show('organise');
    };
  },

  async gallery() {
    /* Built-in starting points. Tapping one fills the box and runs it;
     * saving keeps an editable copy. */
    const r = await api('search/template', { action: 'gallery' });
    modal('Search gallery',
      ((r.gallery || []).map(g => '<div class="item"><div style="flex:1">'
        + '<div class="t">' + esc(g.name) + (g.saved ? ' <span class="chip">saved</span>' : '')
        + '</div><div class="m"><code>' + esc(g.query) + '</code> — '
        + esc(g.about || '') + '</div></div>'
        + '<button class="btn" data-use="' + esc(g.query) + '">Use</button>'
        + (g.saved ? '' : '<button class="btn" data-keep="' + esc(g.query)
          + '" data-name="' + esc(g.name) + '">Save</button>') + '</div>').join('')
        || '<div class="empty">No gallery.</div>'),
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body button[data-use]').forEach(b => b.onclick = () => {
      closeModal(); $('#sq').value = b.dataset.use; App.show('search'); Search.go();
    });
    $$('#modal-body button[data-keep]').forEach(b => b.onclick = async () => {
      await api('search/template', { action: 'save', name: b.dataset.name,
        query: b.dataset.keep });
      closeModal(); Search.loadTemplates(); toast('Saved.');
    });
  },

  /* Build a search from a form, so the syntax never has to be remembered.
   * The server assembles it from forms verified against the engine, and the
   * result is shown before it runs. */
  async browse() {
    const types = ['Bible', 'StudyBible', 'Commentary', 'Lexicon', 'Dictionary',
                   'FactBook', 'Devotional', 'Book', 'OriginalLanguage', 'Atlas'];
    const langs = ['eng', 'grc', 'heb', 'lat', 'spa', 'deu', 'fra'];
    const words = (n, ph) => '<input id="bq-' + n + '" placeholder="' + ph
      + '" style="flex:1">';
    const body =
      '<div class="bq">' +
      '<div class="bq-row"><label>Must contain all of</label>'
      + words('all1', 'faith') + words('all2', 'lord') + '</div>' +
      '<div class="bq-row"><label>Must contain any of</label>'
      + words('any1', 'atonement') + words('any2', 'redemption') + '</div>' +
      '<div class="bq-row"><label>Must not contain</label>'
      + words('none1', 'modern') + words('none2', '') + '</div>' +
      '<div class="bq-row"><label>Near</label>'
      + words('anchor', 'faith') +
      '<span class="muted tiny">within</span>'
      + '<input id="bq-within" value="5" style="width:56px">'
      + '<span class="muted tiny">words of</span>'
      + words('anchor2', 'grace') + '</div>' +
      '<div class="bq-row"><label>Strong\'s</label>' + words('strongs', 'G2316')
      + '<label style="margin-left:10px">Heading</label>'
      + words('heading', 'faith') + '</div>' +
      '<div class="bq-row"><label>Reference</label>' + words('bible', 'John 3:16')
      + '<label style="margin-left:10px">Kind</label>'
      + '<select id="bq-type"><option value="">any</option>'
      + types.map(t => '<option>' + t + '</option>').join('') + '</select>'
      + '<label style="margin-left:10px">Language</label>'
      + '<select id="bq-lang"><option value="">any</option>'
      + langs.map(l => '<option>' + l + '</option>').join('') + '</select></div>' +
      '</div>' +
      '<div class="bq-out"><div class="tiny muted">This will search for</div>' +
      '<code id="bq-query"></code></div>' +
      '<div class="tiny" id="bq-err" style="color:#f0a0a5"></div>';
    modal('Build a search', body);
    const val = (id) => { const e = $('#bq-' + id); return e ? e.value : ''; };
    const spec = () => ({
      all: [val('all1'), val('all2')],
      any: [val('any1'), val('any2')],
      none: [val('none1'), val('none2')],
      anchor: val('anchor'), anchor2: val('anchor2'),
      within_words: val('within'),
      strongs: val('strongs'), heading: val('heading'), bible: val('bible'),
      type: val('type'), lang: val('lang'),
    });
    /* Debounced, and out-of-order replies are dropped.  Each keystroke fires a
     * request; typing quickly meant an older reply could land last and leave the
     * preview showing a query the form no longer described -- and "Run this
     * search" runs what is shown, so it would have searched something else. */
    let seq = 0, timer = null;
    const refresh = async () => {
      const mine = ++seq;
      const r = await api('search/browser', { spec: JSON.stringify(spec()) });
      if (mine !== seq) return;                       // a newer request won
      $('#bq-query').textContent = r.query || '(nothing yet)';
      $('#bq-err').textContent = '';
    };
    const queue = () => { clearTimeout(timer); timer = setTimeout(refresh, 120); };
    $$('#modal-body input, #modal-body select').forEach(
      e => { e.oninput = queue; e.onchange = queue; });
    await refresh();
    const go = $('#modal-body .bq-run');
    const foot = document.createElement('div');
    foot.innerHTML = '<button class="btn primary bq-run">Run this search</button>'
      + '<button class="btn" id="bq-save">Save it</button>';
    $('#modal-body').appendChild(foot);
    foot.querySelector('.bq-run').onclick = () => {
      const q = $('#bq-query').textContent;
      if (!q || q === '(nothing yet)') { toast('Fill something in first.', 'warn'); return; }
      $('#sq').value = q;
      closeModal();
      Search.go();
    };
    foot.querySelector('#bq-save').onclick = async () => {
      const q = $('#bq-query').textContent;
      if (!q || q === '(nothing yet)') { toast('Fill something in first.', 'warn'); return; }
      const name = prompt('Name this search', q.slice(0, 40));
      if (!name) return;
      await api('search/template', { action: 'save', name: name, query: q });
      toast('Saved');
      closeModal();
      Search.loadTemplates();
    };
  },

  /* Suggestions while you type, before any search runs.
   *
   * The same arithmetic the full search uses for its "smart notes" -- a
   * spelling check against the headword and Strong's vocabulary the library
   * actually holds, and a datatype hint when the word is a tagged term --
   * but run on the bare word.  Waiting for a search to notice that "agape" was
   * spelled "agapp" is one search too late: the result page can only say it
   * after showing you the wrong answer.
   *
   * Deliberately not run while an operator is being typed.  "love NEAR faith"
   * is not a spelling query, and offering to correct "NEAR" is the kind of
   * helpfulness that makes people distrust the other suggestions. */
  async suggestNow() {
    const box = $('#sq');
    const host = $('#search-hint');
    if (!box || !host) return;
    const text = (box.value || '').trim();
    const bare = /^[A-Za-z][A-Za-z'-]{2,}$/.test(text);
    if (!bare) { host.innerHTML = ''; host.style.display = 'none'; return; }
    host.style.display = '';
    host.innerHTML = '<span class="tiny muted">checking…</span>';
    const r = await api('search/spell', { q: text });
    /* A response that arrives after the box has moved on must not overwrite
     * the newer question's answer, so the text it was asked about is compared
     * against what is in the box now. */
    if ((box.value || '').trim() !== text) return;
    const notes = r.smart || [];
    if (!notes.length) { host.innerHTML = ''; host.style.display = 'none'; return; }
    host.innerHTML = notes.map(s =>
      '<span class="smartnote">' + esc(s.note) + ' '
      + '<code data-use="' + esc(s.kind === 'spelling' ? s.to
          : (s.kind === 'strongs' ? 'strongs:' + s.to : s.to)) + '">'
      + esc(s.kind === 'strongs' ? s.to : s.to) + '</code></span>').join(' ');
    host.querySelectorAll('code[data-use]').forEach(c => c.onclick = () => {
      box.value = c.dataset.use;
      this.go();
    });
  },

  /* Smart Search: a plain-English question in, a query out.
   *
   * Deliberately not a second chat panel.  The engine recalls better than a model
   * does, and the reader can see and edit the query it produced -- so the model
   * is used only for the part it is good at (knowing that "the way, the truth and
   * the life" is about John 14) and the engine does the finding. */
  async smart() {
    const box = $('#sq');
    const host = $('#search-hint');
    const q = (box.value || '').trim();
    if (!q) { toast('Type a question first.', 'warn'); return; }
    if (typeof Ai === 'undefined' || !Ai.provider()) {
      toast('Set up a provider first (Settings → AI).', 'err');
      App.show('aisettings');
      return;
    }
    host.style.display = '';
    host.innerHTML = '<span class="tiny muted">Asking the model for a '
      + 'query…</span>';
    const r = await api('ai/smart-search', { q });
    if (!r.ok) {
      host.innerHTML = '<span class="tiny" style="color:var(--red)">'
        + esc(r.error || 'The model produced no query.')
        + (r.hint ? ' — ' + esc(r.hint) : '') + '</span>';
      return;
    }
    box.value = r.query;
    host.innerHTML = '<span class="tiny muted">Smart Search turned '
      + '<i>' + esc(r.question) + '</i> into <code>' + esc(r.query)
      + '</code> — edit and search again if it missed.</span>';
    this.go();
  },

  async go() {
    let q = $('#sq').value;
    /* ---- Morph search type ------------------------------------------------
     * When Morph is the active search type, the query is built from the
     * morph word input: `love @V-PAI-3S` becomes `morph:V-PAI-3S`, which the
     * search engine already resolves against the morphology marker index.
     * Results come back as verse hits, grouped by resource, each linking to
     * the Bible pane -- the same path an ordinary text search takes. */
    if (Search.morphMode) {
      const mw = $('#s-morph-word');
      const w = (mw && mw.value ? mw.value : '').trim();
      if (!w) {
        $('#search-results').innerHTML = '<div class="empty">Type a word, '
          + 'press @ and pick a grammatical form.</div>';
        return;
      }
      const m = w.match(/^(.+?)\s*@\s*(.+)$/);
      q = m ? ('morph:' + m[2]) : ('morph:' + w);
      $('#sq').value = q;
      S.search.q = q;
    } else {
      if (!q.trim()) {
        $('#search-results').innerHTML = '<div class="empty">Type something '
          + 'to search'
          + ((S.search.mods || []).length
             ? ' — currently scoped to ' + S.search.mods.length + ' resources'
             : '') + '.</div>';
        return;
      }
      S.search.q = q;
    }
    const host = $('#search-results');
    host.innerHTML = '<div class="loading">Searching…</div>';
    /* A range is a second request path, not a filter on the first: the engine
     * has no book filter, so `search/ranges` over-fetches and then keeps the
     * hits whose books fall inside the range.  Its reply has a different shape
     * -- `hits` plus `shown`/`truncated` rather than `total`/`groups` -- so it
     * is reshaped here into what the renderer below already knows how to draw,
     * instead of the renderer growing a second branch that the two could drift
     * apart on. */
    const range = ($('#s-range').value || '');
    let r;
    if (range) {
      const raw = await api('search/ranges', { action: 'search', q,
        range, opts: { scope: S.search.opts.scope,
                       modules: S.search.mods || [],
                       match_case: S.search.opts.match_case,
                       match_all_forms: S.search.opts.match_all_forms,
                       sort: S.search.opts.sort, limit: 400 } });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const hits = raw.hits || [];
      const byMod = new Map();
      hits.forEach(h => {
        if (!byMod.has(h.module_id)) byMod.set(h.module_id, []);
        byMod.get(h.module_id).push(h);
      });
      const gmeta = {};
      byMod.forEach((v, k) => {
        const m = modById(k);
        gmeta[k] = { name: (m && m.name) || k, type: (m && m.type) || '',
                     count: v.length };
      });
      r = { ok: true, hits, total: hits.length, ms: null, warnings: [],
            smart: [], operators: [], groups: {}, group_meta: gmeta };
      /* Shown-vs-window is the honest framing here: this path may have
       * discarded hits the range excluded, and the count has to say so rather
       * than presenting a filtered total as if it were the real one. */
      r.rangeNote = raw.truncated
        ? 'More matched outside the ' + raw.range + ' window than were '
          + 'searched, so this may be short of the whole range.'
        : '';
    } else {
      r = await api('search', {
        q: q, scope: S.search.opts.scope, match_case: S.search.opts.match_case,
        modules: S.search.mods || [],
        match_all_forms: S.search.opts.match_all_forms,
        context: S.search.opts.context, sort: S.search.opts.sort, limit: 400 });
    }
    host.innerHTML = '';
    if (!r.ok) { host.appendChild(el('div', 'warn', esc(r.error))); return; }
    if (r.rangeNote) host.appendChild(el('div', 'warn', esc(r.rangeNote)));
    (r.warnings || []).forEach(w => host.appendChild(el('div', 'warn', esc(w))));
    (r.smart || []).forEach(s => {
      const d = el('div', 'smartnote');
      d.innerHTML = esc(s.note) + ' <code data-use="' + esc(s.to) + '">'
        + esc(s.to) + '</code>';
      d.querySelector('code').onclick = () => {
        $('#sq').value = s.kind === 'spelling' ? s.to : (s.kind === 'strongs'
          ? 'strongs:' + s.to : s.to);
        Search.go();
      };
      host.appendChild(d);
    });
    if ((S.search.mods || []).length) {
      const names = S.search.mods.map(id => (modById(id) || {}).name || id);
      host.appendChild(el('div', 'tiny muted',
        'Searching ' + names.length + ' resource'
        + (names.length === 1 ? '' : 's') + ': ' + names.join(', ')
        + ' · <a href="#" id="s-clearmods">search everything</a>'));
      const cl = host.querySelector('#s-clearmods');
      if (cl) cl.onclick = (e) => {
        e.preventDefault(); S.search.mods = []; Search.go();
      };
    }
    host.appendChild(el('div', 'tiny muted',
      r.total + ' result' + (r.total === 1 ? '' : 's')
      /* Timing is the search endpoint's, and the range path does not measure
       * one -- it over-fetches and then filters in Python, so quoting a number
       * here would be a figure for a different piece of work. */
      + (r.ms === null || r.ms === undefined ? '' : ' · ' + r.ms + ' ms')
      + (r.operators && r.operators.length ? ' · operators: ' + r.operators.join(', ') : '')));
     /* Search synopsis: a compact by-book tally so a big result set reads as a
      * map of where the hits are, not just a count. */
     if (r.hits && r.hits.length > 1) {
       const byBook = new Map();
       r.hits.forEach(h => {
         const b = String(h.label || '').trim().split(/\s+/)[0] || '';
         if (b) byBook.set(b, (byBook.get(b) || 0) + 1);
       });
       if (byBook.size > 1) {
         const top = [...byBook.entries()].sort((a, b) => b[1] - a[1])
           .slice(0, 12);
         host.appendChild(el('div', 'tiny muted',
           'By book: ' + top.map(([b, n]) => b + ' ' + n).join(' · ')));
       }
     }

    /* Group by resource, because 400 hits from 62 resources is not a list --
     * it is 62 things you did not ask for, and the one you wanted is at the
     * bottom because it happened to match oftenest.  Counts come from the
     * backend over *every* match, not the returned page, so a header saying
     * 1,864 is the truth even when only 400 hits were shipped. */
    const byModule = new Map();
    r.hits.forEach(h => {
      if (!byModule.has(h.module_id)) byModule.set(h.module_id, []);
      byModule.get(h.module_id).push(h);
    });
    const groups = r.groups || {};
    const gmeta = r.group_meta || {};
    const order = [...byModule.keys()].sort((a, b) =>
      (groups[b] || 0) - (groups[a] || 0)
      || ((gmeta[a] && gmeta[a].name) || '').localeCompare((gmeta[b] && gmeta[b].name) || ''));
    const grouping = order.length > 1 && Search.group !== 'flat';

    if (r.truncated) {
      host.appendChild(el('div', 'tiny muted',
        `Showing the first ${r.returned} of ${r.total} matches, grouped by resource. `
        + 'A resource may show fewer rows than its count.'));
    }

    if (!r.hits.length) {
      host.appendChild(el('div', 'empty', 'Nothing found. Try fewer terms, or check your spelling.'));
      return;
    }
    const flatHost = grouping ? null : host;
    const sink = flatHost || el('div', 'sgroups');
    if (grouping) host.appendChild(sink);

    const makeHit = (h) => {
      const n = el('div', 'hit');
      n.innerHTML = '<div class="h"><span class="ref">' + esc(h.label) + '</span>'
        + '<span class="mod">' + esc(h.module_name) + '</span>'
        + (h.strongs && h.strongs.length
          ? '<span class="tiny muted">' + esc(h.strongs.slice(0, 4).join(' ')) + '</span>' : '')
        /* Morphology codes appear in matched when the search was a morph query;
         * show them so each hit says what grammatical form was found. */
        + (h.matched && h.matched.some(m => /^[A-Z0-9/:]+$/.test(m) && m.length > 2)
          ? '<span class="tiny muted" style="color:var(--accent-2)">'
          + esc(h.matched.filter(m => /^[A-Z0-9/:]+$/.test(m) && m.length > 2)
                  .slice(0, 4).join(' · ')) + '</span>' : '')
        + '<span class="rank">' + h.rank + '</span></div>'
        + '<div class="sn">' + h.snippet_html + '</div>'
        + (h.context && h.context.length
          ? '<div class="tiny muted" style="margin-top:5px">'
          + h.context.map(c => '<span style="margin-right:10px' + (c.current
            ? ';color:var(--accent)' : '') + '">' + esc(c.label) + '</span>').join('')
          + '</div>' : '');
      n.onclick = () => {
        const m = modById(h.module_id);
        if (m) {
          const p = S.layout.panes.find(x => x.module_id === h.module_id);
          if (p && m.reader === 'verse') {
            p.cursor = { ref: h.label, span: 'chapter' };
            Reader.reload(p, m);
          } else Workspace.openModule(h.module_id,
            m.reader === 'verse' ? { ref: h.label, span: 'chapter' } : { key: h.key });
          App.show('workspace');
        }
      };
      return n;
    };
    if (!grouping) r.hits.forEach(h => sink.appendChild(makeHit(h)));

    /* The grouping toggle has to exist in both modes.  Rendering it only with
     * the groups meant that switching to the flat list removed the only way
     * to switch back. */
    if (!grouping) {
      const bar0 = el('div', 'sgroups-bar');
      const t0 = el('button', 'btn tiny', 'group by resource');
      t0.onclick = () => { Search.group = 'group'; Search.go(); };
      bar0.appendChild(t0);
      host.appendChild(bar0);
    }

    /* What to do with a result set other than read it.
     *
     * Some platforms offer "Save as Passage List" and "Save as Word List" from the
     * same place, and they are two different things: a passage list is a set of
     * verses to read in order, a word list is a set of places a word occurs.
     * Both are offered here, on the results you are looking at rather than on
     * a search you have to remember.  Translation is the third, and the only
     * one that sends anything anywhere -- so it says so on the button. */
    const acts = el('div', 'sgroups-bar');
    const keep = el('button', 'btn tiny', 'Keep as a word list');
    keep.onclick = () => WordLists.fromResults(r.hits);
    acts.appendChild(keep);
    const asList = el('button', 'btn tiny', 'Save as a passage list');
    asList.onclick = () => Search.toPassageList(r.hits);
    acts.appendChild(asList);
    const tr = el('button', 'btn tiny',
      'Translate these hits  (sends text off this computer)');
    tr.onclick = () => Translate.open(r.hits);
    acts.appendChild(tr);
    /* Add Versions -- Logos shows the same search side by side across
     * translations.  Offer the other tagged resources and render each
     * selection as its own column of verse hits. */
    if (Search.morphMode) {
      const tagged = (S.modules || []).filter(m => m.has_morph);
      const others = tagged.filter(m => !byModule.has(m.id));
      if (others.length) {
        const av = el('button', 'btn tiny', 'Add versions');
        const picker = el('div', 'morph-versions-picker');
        picker.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center';
        others.forEach(m => {
          const lab = el('label');
          lab.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:12px';
          lab.innerHTML = '<input type="checkbox" class="mv-sel" value="'
            + esc(m.id) + '"> ' + esc(m.name) + ' (' + esc(m.lang || '') + ')';
          picker.appendChild(lab);
        });
        const goAv = el('button', 'btn primary tiny', 'Compare');
        const out = el('div', 'morph-versions-out');
        out.style.cssText = 'display:flex;gap:8px;overflow-x:auto;padding:8px 0;border-top:1px solid var(--line);margin-top:6px';
        goAv.onclick = async () => {
          const sel = [...picker.querySelectorAll('.mv-sel:checked')].map(i => i.value);
          out.innerHTML = '<div class="tiny muted">Loading versions…</div>';
          await Promise.all(sel.map(async (mid) => {
            const rr = await api('search', {
              q: S.search.q, modules: [mid],
              match_case: S.search.opts.match_case,
              match_all_forms: S.search.opts.match_all_forms,
              context: S.search.opts.context, sort: S.search.opts.sort, limit: 60 });
            const col = document.createElement('div');
            col.style.cssText = 'border:1px solid var(--line-2);border-radius:8px;padding:8px;min-width:220px;flex:0 0 auto';
            const m = modById(mid);
            col.innerHTML = '<div style="font-size:12px;font-weight:600;margin-bottom:6px">'
              + esc((m && m.name) || mid) + (m && m.lang ? ' · ' + m.lang : '')
              + '</div>';
            if (!rr.ok || !rr.hits || !rr.hits.length) {
              col.innerHTML += '<div class="tiny muted">no hits</div>';
            } else {
              rr.hits.forEach(h => {
                const a = document.createElement('a');
                a.href = '#'; a.textContent = esc(h.label);
                a.title = esc(h.module_name);
                a.onclick = (ev) => {
                  ev.preventDefault();
                  const mm = modById(h.module_id);
                  if (mm) {
                    const p = S.layout.panes.find(x => x.module_id === h.module_id);
                    if (p && mm.reader === 'verse') {
                      p.cursor = { ref: h.label, span: 'chapter' };
                      Reader.reload(p, mm);
                    } else Workspace.openModule(h.module_id,
                      mm.reader === 'verse' ? { ref: h.label, span: 'chapter' } : { key: h.key });
                    App.show('workspace');
                  }
                };
                const row = el('div', '');
                row.style.cssText = 'padding:3px 0;border-bottom:1px solid var(--line-2);font-size:12px';
                row.appendChild(a);
                const code = document.createElement('span');
                code.className = 'tiny muted';
                code.textContent = '  ' + (h.matched && h.matched.some(x => /^[A-Z0-9/:]+$/.test(x))
                  ? h.matched.filter(x => /^[A-Z0-9/:]+$/.test(x)).join(' · ') : '');
                row.appendChild(code);
                col.appendChild(row);
              });
            }
            out.appendChild(col);
          }));
        };
        av.onclick = () => {
          picker.style.display = picker.style.display === 'none' ? '' : 'none';
          goAv.style.display = picker.style.display === 'none' ? 'none' : '';
        };
        acts.appendChild(av);
        acts.appendChild(picker);
        acts.appendChild(goAv);
        acts.appendChild(out);
      }
    }
    host.appendChild(acts);

    if (grouping) {
      order.forEach((mid, idx) => {
        const hits = byModule.get(mid);
        const meta = gmeta[mid] || {};
        const total = groups[mid] || hits.length;
        const wrap = el('div', 'sgroup');
        wrap.dataset.mid = mid;
        const head = el('div', 'sgroup-h');
        const shown = hits.length;
        head.innerHTML = '<span class="caret">\u25be</span>'
          + '<span class="t">' + esc(meta.name || (modById(mid) || {}).name || mid) + '</span>'
          + (meta.type ? '<span class="chip">' + esc(meta.type) + '</span>' : '')
          + '<span class="n">' + (shown < total
            ? `${shown} of ${total.toLocaleString()}`
            : total.toLocaleString()) + '</span>';
        head.title = shown < total
          ? `${total.toLocaleString()} matches in this resource; ${shown.toLocaleString()} were returned. `
            + 'Narrow the search or scope to this resource to see the rest.'
          : `${total.toLocaleString()} match${total === 1 ? '' : 'es'}`;
        const body = el('div', 'sgroup-b');
        hits.forEach(h => body.appendChild(makeHit(h)));
        wrap.appendChild(head);
        wrap.appendChild(body);
        head.onclick = () => {
          const open = wrap.classList.toggle('open');
          if (open && meta.reader === 'verse') {
            head.insertAdjacentHTML('beforeend',
              '<button class="btn tiny scope">open only this</button>');
          }
          const b = head.querySelector('button.scope');
          if (b) b.onclick = (e) => {
            e.stopPropagation();
            S.search.mods = [mid];
            App.show('search');
            Search.go();
          };
        };
        // Open the first few, collapse the rest.  Collapsing *every* group
        // leaves the user staring at a column of headers, which is the same
        // wall the grouping was meant to break up.
        // Only ever *removing* the class left every group shut, which is the
        // same wall of headers the grouping was meant to break up.
        if (idx < 3) wrap.classList.add('open');
        else wrap.classList.remove('open');
        sink.appendChild(wrap);
      });

      const bar = el('div', 'sgroups-bar');
      const tog = (label, fn) => {
        const b = el('button', 'btn tiny', label);
        b.onclick = fn;
        bar.appendChild(b);
      };
      tog('expand all', () => $$('.sgroup', sink).forEach(x => x.classList.add('open')));
      tog('collapse all', () => $$('.sgroup', sink).forEach(x => x.classList.remove('open')));
      tog(Search.group === 'group' ? 'show as one list' : 'group by resource', () => {
        Search.group = Search.group === 'group' ? 'flat' : 'group';
        Search.go();
      });
      host.insertBefore(bar, sink);
    }
  },

  async help() {
    const r = await api('search/help');
    const h = $('#search-help');
    h.innerHTML = '<h4>Query language</h4>';
    (r.operators || []).forEach(o => {
      h.appendChild(el('div', 'note', esc(o.note)));
      const c = el('code', '', esc(o.syntax));
      c.onclick = () => { $('#sq').value = o.syntax; $('#sq').focus(); };
      h.appendChild(c);
    });
  },
};

/* ======================================================== Module Browser */
/* Rebuilt from scratch.  The old Store was a flat list of interchangeable
   rows; this one is organised by *where the module goes*, says so before you
   download it, warns when something is already installed or already open in a
   pane, and can forget a repository entirely. */
