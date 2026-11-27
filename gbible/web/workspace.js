const Workspace = {
  async openModule(moduleId, cursor, opts) {
    const lay = S.layout;
    if (!lay) { toast('No workspace is open.', 'warn'); return; }
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
      cursor: cursor || {}, options: opts || {},
      // Workflow options arrive nested; the server expects these top-level.
      text_size: (opts && opts.text_size) || 100,
      link_set: (opts && opts.link_set) || link });
    if (!r || !r.ok || !r.pane) {
      toast('Could not open the resource'
        + (r && r.error ? ': ' + r.error : ''), 'err');
      return;
    }
    /* Keep the local layout in sync and re-render instead of a full reload. */
    if (S.layout && r.pane) {
      if (!S.layout.panes) S.layout.panes = [];
      S.layout.panes.push(r.pane);
    }
    try { localStorage.setItem('gbible:last-module', moduleId); } catch (e) {}
    App.renderWorkspace();
    /* A tile draws tp[0] -- the first pane filed under it -- so a pane added to
     * a tile that already has one is saved correctly and then never shown.  The
     * Library's Open button looked like it did nothing.  Select the new pane. */
    const p = r.pane;
    App.showPane(tile, p.id);
    return p;
  },

  async openModuleIn(tile, moduleId, cursor, opts) {
    const lay = S.layout;
    const r = await post('workspace/pane', {
      action: 'add', layout: lay.id, module: moduleId, tile: tile,
      cursor: cursor || {}, options: opts || {}, link_set: '' });
    if (!r || !r.ok || !r.pane) {
      toast('Could not open the resource'
        + (r && r.error ? ': ' + r.error : ''), 'err');
      return;
    }
    if (S.layout && r.pane) {
      if (!S.layout.panes) S.layout.panes = [];
      S.layout.panes.push(r.pane);
    }
    App.renderWorkspace();
    const p = r.pane;
    App.showPane(tile, p.id);
    try { localStorage.setItem('gbible:last-module', moduleId); } catch (e) {}
    return p;
  },

  /* Switch the module (translation) shown in an existing pane, keeping the
   * pane, its tile, its link set and its cursor (reading position).  This is
   * what makes swapping translations in a parallel arrangement direct: no new
   * pane is created, no link relationship is lost, and the reader stays where
   * it was. */
  async switchModule(paneId, moduleId) {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const p = (lay.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    const m = (S.modules || []).find(x => x.id === moduleId);
    if (!m) { toast('That resource is not installed.', 'warn'); return; }
    if (p.module_id === moduleId) return p;
    const r = await post('workspace/pane', {
      pane: paneId,
      module_id: moduleId,
    });
    if (!r || !r.pane) { toast('Could not switch translation.', 'warn'); return; }
    /* Keep the local pane record in sync so the UI reflects the change at once.
     * link_set, tile_id and cursor are intentionally untouched. */
    p.module_id = moduleId;
    const pane = $('.pane[data-pane="' + paneId + '"]');
    if (pane) App.showPane(p.tile_id || 't0', paneId);
    return r.pane;
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
    else {
      if (S.layout) { S.layout.tiles = tree; if (!S.layout.panes) S.layout.panes=[]; if(!S.layout.panes.includes(r.pane)) S.layout.panes.push(r.pane); }
    }
    App.renderWorkspace();
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
    if (S.layout && r.pane) {
      if (!S.layout.panes) S.layout.panes = [];
      S.layout.panes.push(r.pane);
    }
    App.renderWorkspace();
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
    if (S.layout && r.pane) {
      if (!S.layout.panes) S.layout.panes = [];
      S.layout.panes.push(r.pane);
    }
    App.renderWorkspace();
    App.showPane(tile, r.pane.id);
    return r.pane;
  },

  async floatPane(paneId) {
    const p = (S.layout.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    // Make the requested pane active first: a tile shows only its first pane,
    // so floating an inactive tab used to copy the wrong pane's body.
    await App.showPane(p.tile_id, p.id);
    const tile = document.querySelector('.tile[data-tile="'
      + App.tileKey(p.tile_id) + '"]');
    const paneEl = tile ? tile.querySelector('.pane[data-pane="' + p.id + '"]') : null;
    const html = paneEl ? paneEl.outerHTML.replace(/<div class="pane-tools"[\s\S]*?<\/div>/, '') : '';
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

  /* Move a pane into another slot of the layout, optionally in front of a
   * specific tab there.  One central path is used by the toolbar dropdown, the
   * tab right-click menu and drag-and-drop, so all three collapse an emptied
   * source tile the same way. */
  async movePane(paneId, targetTileId, beforePaneId) {
    const lay = S.layout;
    if (!lay || !lay.id) return false;
    const panes = lay.panes || [];
    const idx = panes.findIndex(x => x.id === paneId);
    if (idx < 0) return false;
    const srcTile = App.tileKey(panes[idx].tile_id);
    const dstTile = App.tileKey(targetTileId);
    const leaves = App.leafTileIds(App.ensureTiles());
    if (!leaves.includes(dstTile)) { toast('That pane is not available.', 'warn'); return false; }
    if (srcTile === dstTile && !beforePaneId) return false;
    /* Re-file locally first: pruning saves the whole layout (panes included),
     * so the new tile_id is persisted along with the collapsed tree.  Placing
     * the moved pane first in its new slot makes it the visible tab there. */
    const [moved] = panes.splice(idx, 1);
    moved.tile_id = dstTile;
    let at = beforePaneId
      ? panes.findIndex(x => x.id === beforePaneId)
      : panes.findIndex(x => App.tileKey(x.tile_id) === dstTile);
    if (at < 0) at = panes.length;
    panes.splice(at, 0, moved);
    lay.panes = panes;
    await App.pruneEmptyTiles({ forceSave: true });
    return true;
  },

  async closeAll() {
    const lay = S.layout;
    if (!lay || !lay.id) { toast('No workspace is open.', 'warn'); return; }
    const panes = (lay.panes || []).slice();
    const results = await Promise.all(panes.map(p =>
      post('workspace/pane', { action: 'close', pane: p.id }).catch(() => null)));
    if (results.some(r => !r || r.ok === false)) {
      toast('Some panes could not be closed.', 'warn');
      await App.loadWorkspace();
      return;
    }
    if (S.layout) S.layout.panes = [];
    /* Collapse every emptied slot down to a single empty pane. */
    await App.pruneEmptyTiles();
    toast('All panes closed.');
  },

  async closePane(paneId) {
    const r = await post('workspace/pane', { action: 'close', pane: paneId });
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not close that pane.', 'err');
      return;
    }
    // Drop the pane locally instead of a full reload.
    if (S.layout && S.layout.panes) {
      S.layout.panes = S.layout.panes.filter(p => p.id !== paneId);
    }
    /* Collapse the tile this pane was in (and any other empty slots) before
     * rendering: the old code rendered the still-split tree first, so the
     * closed pane's empty slot flashed on screen until the next render. */
    await App.pruneEmptyTiles();
  },

  async propagate(p) {
    const links = await api('workspace/link', { pane: p.id, cursor: p.cursor });
    for (const L of (links.links || [])) {
      if (L.action === 'none') continue;
      const t = S.layout.panes.find(x => x.id === L.pane_id);
      if (!t) continue;
      t.cursor = Object.assign({}, t.cursor, L.cursor);
      if (L.shared.indexOf('bibleVerse') >= 0 && L.cursor.ref) {
        t.cursor.ref = L.cursor.ref;
      }
      if (L.shared.indexOf('strongs') >= 0 && L.cursor.strongs) {
        t.cursor.number = L.cursor.strongs;
        t.cursor.strongs = L.cursor.strongs;
      }
      // Persist the moved cursor: the old code only changed memory, so a
      // reload put every linked pane back where it had been.
      post('workspace/pane', { pane: t.id, cursor: t.cursor }).catch(() => {});
      const pane = $('.pane[data-pane="' + t.id + '"]');
      if (pane) await App.fillPane(pane, t);
    }
    /* The Info follow-pane tracks the cursor that just moved. */
    try {
      const ref = (p.cursor && p.cursor.ref) || '';
      if (ref) InfoPane.maybeRefresh(ref);
    } catch (e) { /* never break linking */ }
  },

  /* After a workspace is restored, bring every linked pane to the same passage.
   * Each pane stores its own cursor, so a link set whose panes were saved at
   * different positions needs one pass to bring them together.  We pick the
   * first pane in each link set that has a ref cursor and propagate it to the
   * rest; the server maps the cursor through shared milestone types (Bible and
   * commentary scroll together; a lexicon looks up on click instead). */
  async restoreLinks() {
    const panes = (S.layout && S.layout.panes) || [];
    const bySet = new Map();
    for (const p of panes) {
      const ls = p.link_set || '';
      if (!bySet.has(ls)) bySet.set(ls, []);
      bySet.get(ls).push(p);
    }
    for (const [ls, members] of bySet) {
      if (!ls) continue;
      const leader = members.find(p => p.cursor
        && (p.cursor.ref || p.cursor.date || p.cursor.key));
      if (!leader) continue;
      await this.propagate(leader);
    }
  },

  /* Pack 1 extras: arrangements without closing panes, one-click unlink,
   * QuickStart layouts, Top Bible, parallel prev/next, reading progress,
   * copy-location. All thin wrappers over the JSON API. */
  async arrange(name) {
    const r = await post('workspace/arrange', { arrangement: name });
    if (r.layout) { S.layout = r.layout; App.renderWorkspace(); }
    else await App.loadWorkspace();
  },
  async clearLinks() {
    await post('workspace/clear_links', {});
    if (S.layout && S.layout.panes) {
      S.layout.panes.forEach(p => { p.link_set = ''; });
    }
    App.renderWorkspace();
    toast('All link sets cleared.');
  },
  async quickstarts() { return api('workspace/quickstarts', {}); },
  async quickstart(name) {
    const r = await post('workspace/quickstart', { name });
    if (r.layout) { S.layout = r.layout; App.renderWorkspace(); }
    else await App.loadWorkspace();
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
  async parallelStep(moduleId, dir, collectionId, paneId) {
    const r = await api('workspace/parallel', {
      module: moduleId, direction: dir > 0 ? 'next' : 'prev',
      collection: collectionId || '' });
    if (r.ok && r.module_id) {
      // Cycle the resource in the *current* pane: opening a new pane with an
      // empty cursor dropped the reader at the next Bible's first chapter,
      // which defeats the point of comparing the same verse across versions.
      if (paneId) await this.switchModule(paneId, r.module_id);
      else this.openModule(r.module_id, {});
    }
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
    const [qs, tb, listed] = await Promise.all([
      this.quickstarts().catch(() => ({ quickstarts: [] })),
      this.topBible().catch(() => ({})),
      api('workspace/layouts').catch(() => ({ layouts: [] })),
    ]);
    const names = Object.keys(S.arrangements || {});
    const saved = (listed && listed.layouts) || [];
    const cur = S.layout || {};
    const row = (label, body) => '<h4 style="margin:12px 0 4px">' + label + '</h4>' + body;
    const savedRows = saved.map(l => {
      const active = l.id === cur.id ? ' <span style="color:var(--accent)">(current)</span>' : '';
      const btns = '<button class="btn tiny" data-use="' + esc(l.id) + '">Open</button>'
        + ' <button class="btn tiny danger" data-del="' + esc(l.id) + '">Delete</button>';
      const panes = (l.panes || []).length;
      const mods = (l.panes || []).map(p => {
        const m = (S.modules || []).find(x => x.id === p.module_id);
        return m ? m.name : (p.view || '(empty)');
      }).join(', ');
      return '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">'
        + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
        + esc(l.name) + active + '</span>'
        + '<span class="tiny muted" style="white-space:nowrap">' + panes + ' pane(s)</span>'
        + '<span class="tiny muted">' + esc(mods) + '</span>'
        + btns + '</div>';
    }).join('') || '<div class="empty tiny">No saved layouts yet.</div>';
    modal('Layouts',
      row('Rearrange open panes — nothing closes',
        '<div class="row wrap">' + names.map(n =>
          '<button class="btn" data-arr="' + esc(n) + '">' + esc(n) + '</button>').join('')
        + '</div>')
      + row('Start from a task',
        '<div class="row wrap">' + (qs.quickstarts || []).map(q =>
          '<button class="btn" data-qs="' + esc(q.name) + '" title="' + esc(q.about || '') + '">'
          + esc(q.name) + '</button>').join('') + '</div>')
      + row('Saved layouts',
        '<div id="saved-layouts">' + savedRows + '</div>'
        + '<div style="margin-top:8px;display:flex;gap:6px">'
        + '<input id="save-layout-name" placeholder="Name this layout…" style="flex:1;min-width:140px;'
        + 'background:var(--bg-3);border:1px solid var(--line-2);color:var(--fg);'
        + 'padding:4px 8px;border-radius:5px;font-size:12px">'
        + '<button class="btn" id="save-layout">Save current</button></div>'
        + '<div class="tiny muted" style="margin-top:4px">Saving keeps every open pane, its '
        + 'translation, reading position and link set.</div>')
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
    $$('#modal-body button[data-use]').forEach(b => b.onclick = async () => {
      closeModal(); await this.useLayout(b.dataset.use);
    });
    $$('#modal-body button[data-del]').forEach(b => b.onclick = async () => {
      const id = b.dataset.del;
      if (!confirm('Delete this layout? Its panes are removed too.')) return;
      closeModal(); await this.deleteLayout(id);
    });
    const cl = $('#modal-body button[data-clear]');
    if (cl) cl.onclick = async () => { closeModal(); await this.clearLinks(); };
    $('#save-layout').onclick = async () => {
      const name = ($('#save-layout-name').value || '').trim() || 'Layout';
      closeModal();
      await this.saveLayoutAs(name);
    };
  },

  /* Save the current workspace as a named layout, then make it current. */
  async saveLayoutAs(name) {
    const lay = S.layout;
    if (!lay) { toast('No workspace to save.', 'warn'); return; }
    const r = await post('workspace/save', {
      id: lay.id, name: name,
      tiles: App.ensureTiles(), panes: lay.panes || [],
    });
    if (!r || !r.layout) { toast('Could not save layout.', 'warn'); return; }
    S.layout = r.layout;
    await this.useLayout(r.layout.id);
    toast('Layout saved: ' + name);
  },

  /* Switch to a saved layout and reload the workspace. */
  async useLayout(layoutId) {
    const r = await post('workspace/use', { id: layoutId });
    if (!r || !r.layout) { toast('Could not open that layout.', 'warn'); return; }
    S.layout = r.layout;
    App.renderWorkspace();
    toast('Layout opened.');
  },

  /* Delete a saved layout and refresh the list. */
  async deleteLayout(layoutId) {
    const r = await post('workspace/delete', { id: layoutId, force: '1' });
    if (!r || r.ok === false) { toast('Could not delete layout.', 'warn'); return; }
    await this.layoutsDialog();
  },
  async fullscreen(paneId) {
    const p = (S.layout.panes || []).find(x => x.id === paneId);
    if (!p) { toast('That pane is no longer open.', 'warn'); return; }
    const m = (S.modules || []).find(x => x.id === p.module_id);
    if (!m) {
      // Guide, word-study and factbook panes have no module to read: clone
      // what is already rendered instead of showing an empty dialog.
      const live = document.querySelector('.pane[data-pane="' + p.id + '"] .pane-body');
      modal(p.view || 'Pane',
        '<div style="font-size:1.15em;line-height:1.7;max-height:70vh;overflow:auto">'
        + (live ? live.innerHTML : '<div class="empty">Nothing to show in fullscreen.</div>')
        + '</div>', [{ label: 'Close', cls: 'btn' }]);
      return;
    }
    const r = await api('read', { id: p.module_id, cursor: p.cursor || {},
      options: p.options || {}, span: 'chapter' }).catch(() => null);
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not read that pane.', 'err');
      return;
    }
    const items = r.items || [];
    modal(m.name + (p.cursor && p.cursor.ref ? ' — ' + p.cursor.ref : ''),
      '<div style="font-size:1.25em;line-height:1.7;max-height:70vh;overflow:auto">'
      + (items.length ? items.map(i => i.html || '').join('')
        : '<div class="empty">No text at this reference.</div>') + '</div>',
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
    const pp = (S.layout && S.layout.panes || []).find(x => x.id === paneId);
    if (pp) pp.options = r.options;
    App.renderWorkspace();
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
  const setO = (k, v) => post('workspace/pane', { pane: p.id, [k]: v }).then(() => {
    const pp = (S.layout && S.layout.panes || []).find(x => x.id === p.id);
    if (pp) pp[k] = v;
    App.renderWorkspace();
  });
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
       m.has_notes ? 'footnotes' : '', m.has_xref ? 'cross-references' : '']
       .filter(Boolean).join(', ') + '</td></tr>'
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
      toast('Re-indexed ' + m.name + ' — ' + (r.units || 0) + ' units.');
    };
  }
}

/* ============================================================== Search */
const Search = {
  limit: 400,   // grown by "Show more"; the reader can reach every match
  smartToken: 0,
  /* One result → several tools.  The tools already exist; this is only the
   * wire that hands them the reference the reader was looking at. */
  sendTo(h, x, y) {
      const items = [{ section: 'THIS RESULT' }];
      if (h.strongs && h.strongs.length) {
        items.push({ label: 'Word study: ' + esc(h.strongs[0]),
          fn: () => Reader.openWordStudyPane(h.strongs[0]) });
        items.push({ label: 'Concordance: ' + esc(h.strongs[0]),
          fn: () => Study.openConcordance(h.strongs[0]) });
      }
      if (h.label) {
        items.push({ label: 'Passage Guide: ' + esc(h.label),
          fn: () => Reader.openGuidePane(h.label, 'passage') });
        items.push({ label: 'Exegetical Guide: ' + esc(h.label),
          fn: () => Reader.openGuidePane(h.label, 'exegetical') });
        items.push('-');
        items.push({ section: 'USE THIS PASSAGE' });
        items.push({ label: 'Sermon research: ' + esc(h.label), fn: () => {
          const gr = $('#g-ref'); if (gr) gr.value = h.label;
          $('#sm-tab').value = 'sermon-manager';
          App.show('sermon-manager');
        } });
        items.push({ label: 'Places on a map: ' + esc(h.label), fn: async () => {
          const v = await api('study/verse', { id: h.module_id, key: h.key });
          const names = ((v && v.places) || []).map(p => p.name).filter(Boolean);
          if (!names.length) { toast('No gazetteer place is tagged here.', 'warn'); return; }
          MapsUI.showPlace(names[0]);
          if (names.length > 1) toast('Also named here: ' + names.slice(1).join(', '));
        } });
        items.push({ label: 'Timeline and events',
          fn: () => Study.showTimelineFor(h.label) });
      }
      if (items.length === 1) {
        items.push({ label: 'No tools for this result', fn: () => {} });
      }
    Study.menu(x, y, items);
  },

  /* 'group' = one collapsible section per resource, 'flat' = the old list. */
  group: 'group',
  goToken: 0,

  /* The results view has two shapes: the ordinary reading list, and the
   * analysis grid (a sortable table with the result set's tags and facets). */
  view: 'results',
  analysisSort: 'score',
  analysisDir: 'desc',
  analysisToken: 0,

  /* Which search experience is active: all | bible | books | morph | topics
   * | media | documents | maps. Each has its own query, filters, and results. */
  type: 'all',

  /* Each search type keeps its own query so switching categories never loses
   * what you were typing. Keys match the data-type values of .stype-btn. */
  queries: {
    all: '', bible: '', books: '', morph: '', topics: '', media: '',
    documents: '', maps: ''
  },

  /* morphMode is kept for API compatibility; the search bar uses
   * Search.type === 'morph' instead. */
  morphMode: false,

  /* Keep the hits as a passage list -- the verses, in passage order.
   *
   * One version only.  Keys mean different things in different translations, so
   * a list built across five of them is a list of nothing; and the first hit's
   * resource is the one the search ranked highest, which is the one you were
   * reading. */
  async toPassageList(hits) {
    if (!hits || !hits.length) { toast('No results to save.', 'warn'); return; }
    const name = prompt('Name this passage list',
      ((S.search && S.search.q) || 'Passages').slice(0, 40));
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

  /* Save the current type's query from its input(s) into Search.queries[type]. */
  saveTypeQuery(t) {
    const sq = $('#sq');
    const mw = $('#s-morph-word');
    if (t === 'morph') {
      this.queries.morph = (mw && mw.value) || '';
      this.queries.morph_resource = ($('#s-morph-resource') || {}).value || '';
      this.queries.morph_passage = ($('#s-morph-passage') || {}).value || '';
    } else if (t === 'bible') {
      this.queries.bible = (sq && sq.value) || '';
      this.queries.bible_passage = ($('#s-bible-passage') || {}).value || '';
      this.queries.bible_translation = ($('#s-bible-translation') || {}).value || '';
    } else if (t === 'books') {
      this.queries.books = (sq && sq.value) || '';
      this.queries.books_collection = ($('#s-books-collection') || {}).value || '';
      this.queries.books_type = ($('#s-books-type') || {}).value || '';
    } else if (t === 'topics') {
      this.queries.topics = (sq && sq.value) || '';
      this.queries.topics_source = ($('#s-topics-source') || {}).value || '';
    } else if (t === 'media') {
      this.queries.media = (sq && sq.value) || '';
      this.queries.media_source = ($('#s-media-source') || {}).value || '';
      this.queries.media_license = ($('#s-media-license') || {}).value || '';
    } else if (t === 'documents') {
      this.queries.documents = (sq && sq.value) || '';
      this.queries.documents_kind = ($('#s-docs-kind') || {}).value || '';
    } else if (t === 'maps') {
      this.queries.maps = (sq && sq.value) || '';
      this.queries.maps_type = ($('#s-map-type') || {}).value || '';
    } else {
      /* 'all' — the default text search. */
      this.queries.all = (sq && sq.value) || '';
    }
  },

  /* Restore the saved query for type t into its input(s). */
  restoreTypeQuery(t) {
    const sq = $('#sq');
    const mw = $('#s-morph-word');
    if (t === 'morph') {
      /* Morph search uses its own input; hide the main one. */
      if (sq) { sq.value = ''; sq.style.display = 'none'; }
      if (mw) { mw.value = this.queries.morph || ''; mw.style.display = ''; }
      const mr = $('#s-morph-resource'); if (mr) mr.value = this.queries.morph_resource || '';
      const mp = $('#s-morph-passage'); if (mp) mp.value = this.queries.morph_passage || '';
    } else if (t === 'bible') {
      if (sq) { sq.value = this.queries.bible || ''; sq.style.display = ''; }
      const p = $('#s-bible-passage'); if (p) p.value = this.queries.bible_passage || '';
      const tr = $('#s-bible-translation'); if (tr) tr.value = this.queries.bible_translation || '';
      if (mw) mw.style.display = 'none';
    } else if (t === 'books') {
      if (sq) { sq.value = this.queries.books || ''; sq.style.display = ''; }
      const c = $('#s-books-collection'); if (c) c.value = this.queries.books_collection || '';
      const ty = $('#s-books-type'); if (ty) ty.value = this.queries.books_type || '';
      if (mw) mw.style.display = 'none';
    } else if (t === 'topics') {
      if (sq) { sq.value = this.queries.topics || ''; sq.style.display = ''; }
      const s = $('#s-topics-source'); if (s) s.value = this.queries.topics_source || '';
      if (mw) mw.style.display = 'none';
    } else if (t === 'media') {
      if (sq) { sq.value = this.queries.media || ''; sq.style.display = ''; }
      const ms = $('#s-media-source'); if (ms) ms.value = this.queries.media_source || '';
      const ml = $('#s-media-license'); if (ml) ml.value = this.queries.media_license || '';
      if (mw) mw.style.display = 'none';
    } else if (t === 'documents') {
      if (sq) { sq.value = this.queries.documents || ''; sq.style.display = ''; }
      const k = $('#s-docs-kind'); if (k) k.value = this.queries.documents_kind || '';
      if (mw) mw.style.display = 'none';
    } else if (t === 'maps') {
      if (sq) { sq.value = this.queries.maps || ''; sq.style.display = ''; }
      const mt = $('#s-map-type'); if (mt) mt.value = this.queries.maps_type || '';
      if (mw) mw.style.display = 'none';
    } else {
      /* 'all' — the default text search. */
      if (sq) { sq.value = this.queries.all || ''; sq.style.display = ''; }
      if (mw) mw.style.display = 'none';
    }
  },

  /* Show the filter div for the active type, hide all others. */
  showTypeFilters(t) {
    $$('.s-filters').forEach(f => {
      f.style.display = f.id === 's-filters-' + t ? '' : 'none';
    });
  },

  /* The saved searches, as chips above the results. */
  async loadTemplates() {
    const host = $('#search-tpl');
    if (!host) return;
    const r = await api('search/template');
    if (!r || r.ok === false) { host.innerHTML = ''; host.style.display = 'none'; return; }
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
    if (!r || r.ok === false) { toast((r && r.error) || 'Could not load the gallery.', 'err'); return; }
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
      const s = await api('search/template', { action: 'save', name: b.dataset.name,
        query: b.dataset.keep });
      if (!s || s.ok === false) { toast((s && s.error) || 'Could not save.', 'err'); return; }
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
      '<div class="bq-row"><label>Clause role</label>'
      + '<select id="bq-role"><option value="">any role</option>'
      + ['subject', 'object', 'indirect_object', 'oblique', 'verb']
        .map(r => '<option>' + r + '</option>').join('') + '</select>'
      + words('roleword', 'Jesus') + '</div>' +
      '<div class="bq-row"><label>Morphology</label>'
      + words('morph', 'tense=aorist') + '</div>' +
      '<div class="bq-row"><label>Fuzzy word</label>' + words('fuzzy', 'prayr')
      + '<span class="muted tiny">finds the closest spelling in your library</span></div>' +
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
      role: val('role'), role_term: val('roleword'),
      morph: val('morph'), fuzzy: val('fuzzy'),
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
      if (!r || r.ok === false) {
        $('#bq-err').textContent = (r && r.error) || 'Could not build that query.';
        return;
      }
      $('#bq-query').textContent = r.query || '(nothing yet)';
      $('#bq-err').textContent = '';
    };
    const queue = () => { clearTimeout(timer); timer = setTimeout(refresh, 120); };
    $$('#modal-body input, #modal-body select').forEach(
      e => { e.oninput = queue; e.onchange = queue; });
    await refresh();
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
      const s = await api('search/template', { action: 'save', name: name, query: q });
      if (!s || s.ok === false) { toast((s && s.error) || 'Could not save.', 'err'); return; }
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
    if (aiOff()) {
      toast('AI Assistant is not set up. Enable it in Settings → AI Assistant.',
            'warn');
      App.show('aisettings');
      return;
    }
    const box = $('#sq');
    const host = $('#search-hint');
    const q = (box.value || '').trim();
    if (!q) { toast('Type a question first.', 'warn'); return; }
    const seq = ++this.smartToken;
    if (typeof Ai === 'undefined' || !Ai.provider()) {
      toast('Set up a provider first (Settings → AI).', 'err');
      App.show('aisettings');
      return;
    }
    host.style.display = '';
    host.innerHTML = '<span class="tiny muted">Asking the model for a '
      + 'query…</span>';
    const r = await api('ai/smart-search', { q });
    if (seq !== this.smartToken || (box.value || '').trim() !== q) return;
    if (!r.ok) {
      host.innerHTML = '<span class="tiny" style="color:var(--error)">'
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

  /* The analysis grid.  The backend re-runs the query and returns rows with
   * their tags plus facets, so sorting and the facet line describe the whole
   * bounded result set rather than the page the reader was shown. */
  downloadText(name, text, mime) {
    const blob = new Blob([text], { type: (mime || 'text/plain') + ';charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  analysisExport(raw, q, fmt) {
    const rows = raw.rows || [];
    const columns = (raw.columns || []).map(c => c.key);
    const cell = (r, key) => {
      const v = key === 'resolution' ? r.resolution
        : key === 'reference' ? r.label
          : key === 'module_name' ? r.module_name
            : key === 'matched' ? (r.matched || []).join(', ')
              : key === 'lemmas' ? (r.lemmas || []).join(', ')
                : key === 'morphs' ? (r.morphs || []).join(', ')
                  : key === 'strongs' ? (r.strongs || []).join(' ')
                    : r[key];
      return v == null ? '' : String(v);
    };
    if (fmt === 'csv') {
      const escCsv = (v) => '"' + String(v).replace(/"/g, '""') + '"';
      const lines = [columns.map(escCsv).join(',')];
      rows.forEach(r => lines.push(columns.map(k => escCsv(cell(r, k))).join(',')));
      return lines.join('\n');
    }
    const lines = ['# Analysis: ' + (q || ''), '',
      'Query: `' + (q || '') + '`  ',
      'Results analyzed: ' + rows.length + '  ',
      'Query time: ' + (raw.ms || 0) + ' ms', '', '## Facets', ''];
    Object.keys(raw.facets || {}).forEach(k => {
      const items = raw.facets[k] || [];
      if (!items.length) return;
      lines.push('- **' + k + '**: ' + items.map(x => x.label + ' (' + x.count + ')').join(', '));
    });
    lines.push('', '## Hits', '',
      '| ' + columns.join(' | ') + ' |',
      '| ' + columns.map(() => '---').join(' | ') + ' |');
    rows.forEach(r => lines.push('| ' + columns.map(k =>
      cell(r, k).replace(/\|/g, '\\|').replace(/\n/g, ' ')).join(' | ') + ' |'));
    return lines.join('\n');
  },

  async renderAnalysis(host, q) {
    const token = ++this.analysisToken;
    // Analyse exactly what the results pane answered, including the resolved
    // passage scope and translation filter. The old code re-sent the raw box
    // text and all modules, so Analysis described a different result set.
    const last = this.lastQuery || {};
    const loading = el('div', 'tiny muted', 'Building analysis…');
    host.appendChild(loading);
    let raw;
    try {
      raw = await api('search/analysis', {
        q: last.q || q, scope: S.search.opts.scope,
        modules: last.mods || S.search.mods || [],
        match_case: S.search.opts.match_case,
        match_all_forms: S.search.opts.match_all_forms,
        include_resolved: S.search.opts.include_resolved ? 1 : 0,
        max_hits: 1000, sort: this.analysisSort, dir: this.analysisDir });
    } catch (e) {
      if (token === this.analysisToken) {
        loading.textContent = 'Analysis failed: ' + ((e && e.message) || e);
      }
      return;
    }
    /* A second search may have started while this one was in flight.  Its
     * token wins; writing this answer into the shared host would put an old
     * result set under a new query. */
    if (token !== this.analysisToken) return;
    loading.remove();
    if (!raw.ok) {
      host.appendChild(el('div', 'warn', esc(raw.error || 'Analysis failed.')));
      return;
    }
    host.appendChild(el('div', 'tiny muted',
      'Analyzed ' + raw.analyzed + ' of ' + raw.total + ' results'
      + (raw.ms == null ? '' : ' · ' + raw.ms + ' ms')));
    const exportBar = el('div', 'sgroups-bar');
    [['csv', 'Export CSV'], ['md', 'Export Markdown']].forEach(([fmt, label]) => {
      const b = el('button', 'btn tiny', label);
      b.title = 'Save this analysis, with its facets, as a ' + fmt + ' file';
      b.onclick = () => this.downloadText(
        'gbible-analysis-' + Date.now() + '.' + (fmt === 'csv' ? 'csv' : 'md'),
        this.analysisExport(raw, q, fmt), fmt === 'csv' ? 'text/csv' : 'text/markdown');
      exportBar.appendChild(b);
    });
    host.appendChild(exportBar);
    (raw.warnings || []).forEach(w =>
      host.appendChild(el('div', 'tiny muted', esc(w))));
    const names = { book: 'Book', module: 'Resource', type: 'Kind',
                    lemma: 'Lemma', morph: 'Morphology', strongs: 'Strong’s' };
    const drill = (kind, label) => {
      if (kind === 'lemma') return 'lemma:' + label;
      if (kind === 'morph') return 'morph:' + label;
      if (kind === 'strongs') return 'strongs:' + label;
      if (kind === 'book' && label && label !== '—') {
        return 'bible:"' + label + '"';
      }
      return '';
    };
    Object.keys(names).forEach(k => {
      const items = (raw.facets && raw.facets[k]) || [];
      if (!items.length) return;
      const line = el('div', 'tiny muted');
      line.appendChild(document.createTextNode(names[k] + ': '));
      items.slice(0, 12).forEach((x, i) => {
        const term = drill(k, x.label);
        const chip = term ? el('button', 'btn tiny') : el('span');
        chip.textContent = x.label + ' ' + x.count;
        if (term) {
          chip.title = 'Add ' + term + ' to the search';
          chip.onclick = () => {
            if (Search.type !== 'all' && Search.type !== 'bible') {
              const all = document.querySelector('.stype-btn[data-type="all"]');
              if (all) all.click();
            }
            const box = $('#sq');
            const base = (box.value || '').trim();
            box.value = base ? base + ' ' + term : term;
            App.show('search');
            Search.go();
          };
        }
        line.appendChild(chip);
        if (i < items.length - 1) {
          line.appendChild(document.createTextNode(' · '));
        }
      });
      host.appendChild(line);
    });
    const cols = (raw.columns || []).concat([{ key: 'tools', label: 'Tools' }]);
    const table = el('table', 'analysis-table');
    table.style.cssText = 'width:100%;border-collapse:collapse;'
      + 'font-size:12px;margin-top:8px';
    const head = el('tr');
    head.style.cssText = 'border-bottom:1px solid var(--line)';
    cols.forEach(c => {
      const th = el('th');
      th.style.cssText = 'text-align:left;padding:4px 6px;cursor:pointer;'
        + 'white-space:nowrap';
      th.textContent = c.label + (this.analysisSort === c.key
        ? (this.analysisDir === 'desc' ? ' ↓' : ' ↑') : '');
      th.onclick = () => {
        if (this.analysisSort === c.key) {
          this.analysisDir = this.analysisDir === 'desc' ? 'asc' : 'desc';
        } else {
          this.analysisSort = c.key;
          this.analysisDir = 'desc';
        }
        this.go();
      };
      head.appendChild(th);
    });
    const thead = el('thead');
    thead.appendChild(head);
    table.appendChild(thead);
    const body = el('tbody');
    (raw.rows || []).forEach(r => {
      const tr = el('tr');
      tr.style.cssText = 'border-bottom:1px solid var(--line);cursor:pointer';
      const values = {
        reference: r.label, module_name: r.module_name, book: r.book,
        score: r.score, lemmas: (r.lemmas || []).join(', '),
        morphs: (r.morphs || []).join(', '),
        strongs: (r.strongs || []).join(' '),
        matched: (r.matched || []).join(', '),
        resolution: r.resolution || ''
      };
      cols.forEach(c => {
        const td = el('td');
        td.style.cssText = 'padding:3px 6px;vertical-align:top';
        if (c.key === 'tools') {
          const add = (label, fn, title) => {
            const b = el('button', 'btn tiny', label);
            b.title = title || label;
            b.onclick = (e) => { e.stopPropagation(); fn(e); };
            td.appendChild(b);
          };
          add('send to…', (e) => {
            const box = e.currentTarget.getBoundingClientRect();
            Search.sendTo(r, box.left, box.bottom);
          }, 'Open this result in a study tool');
          if (r.module_type === 'Syntax' || r.resolution) {
            add('Syntax tree',
              () => SyntaxTree.tree(r.module_id, r.key, r.label),
              'Show the stored dependency tree');
          }
        } else {
          const v = values[c.key];
          td.textContent = v == null ? '' : String(v);
        }
        tr.appendChild(td);
      });
      tr.onclick = () => {
        const m = modById(r.module_id);
        if (!m) return;
        const p = S.layout.panes.find(x => x.module_id === r.module_id);
        if (p && m.reader === 'verse') {
          p.cursor = { ref: r.label, span: 'chapter' };
          Reader.reload(p, m);
        } else Workspace.openModule(r.module_id,
          m.reader === 'verse' ? { ref: r.label, span: 'chapter' } : { key: r.key });
        App.show('workspace');
      };
      body.appendChild(tr);
    });
    table.appendChild(body);
    host.appendChild(table);
  },

  setType(type) {
    const b = document.querySelector('.stype-btn[data-type="' + type + '"]');
    if (b && b.onclick) b.onclick({ currentTarget: b });
  },

  async go() {
    // Templates, the Browse gallery and workflows inject a query into #sq.
    // In Morph that box is not read, so the injected query silently did
    // nothing. If the morph word box is empty, switch to All first.
    if (this.type === 'morph'
        && !(($('#s-morph-word') || {}).value || '').trim()
        && (($('#sq') || {}).value || '').trim()) {
      this.setType('all');
      return;                 // setType's click already called go()
    }
    // The dispatch below awaits a network call.  A newer query may finish
    // first; without a token the older reply would repaint the pane and then
    // trigger an analysis of a query nobody is looking at.
    const token = ++this.goToken;
    ++this.analysisToken;   // never let an older analysis repaint this search
    /* Save the active type's query before we possibly overwrite the input. */
    this.saveTypeQuery(this.type);

    let q = '';
    // A new query starts from the first page; "Show more" is the only thing
    // that grows the limit.
    const queryKey = this.type + '|' + ($('#sq').value || '');
    if (queryKey !== this._lastQueryKey) { this.limit = 400; this._lastQueryKey = queryKey; }
    let r;
    // Filters live in the per-type strip above the query box.  They used to be
    // saved and restored but never sent to the server, so changing them did
    // nothing; these two carry the Bible translation and passage into search.
    let scopedModules = null;
    let scopedPassage = '';
    /* Only the main text endpoint can be re-run as an analysis.  The morph,
     * topic, media and map paths build their own hit shapes. */
    let usedMain = false;
    const host = $('#search-results');
    const t = this.type;

    /* ---- Read the query from the right input for each type ---------------- */
    if (t === 'morph') {
      const mw = $('#s-morph-word');
      const w = (mw && mw.value ? mw.value : '').trim();
      if (!w) {
        host.innerHTML = '<div class="empty">Type a word, then @ to pick a '
          + 'grammatical form (e.g. λογος@VF), or enter a morphology code '
          + '(e.g. HNcmsa, V-PAI-3S).</div>';
        return;
      }
      const m = w.match(/^(.+?)\s*@\s*(.+)$/);
      q = m ? ('morph:' + m[2]) : ('morph:' + w);
      $('#sq').value = q;
      S.search.q = q;
    } else if (t === 'bible') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type a Bible search query.</div>';
        return;
      }
      S.search.q = q;
      const tr = ($('#s-bible-translation') || {}).value || '';
      if (tr) scopedModules = [tr];
      scopedPassage = (($('#s-bible-passage') || {}).value || '').trim();
    } else if (t === 'books') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type something to search books for.</div>';
        return;
      }
    } else if (t === 'topics') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type a topic, person, place, or subject.</div>';
        return;
      }
    } else if (t === 'media') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type something to search images for.</div>';
        return;
      }
    } else if (t === 'documents') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type something to search notes and documents for.</div>';
        return;
      }
    } else if (t === 'maps') {
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type a place name or Bible reference.</div>';
        return;
      }
    } else {
      /* 'all' — combined text search across the library. */
      q = ($('#sq').value || '').trim();
      if (!q) {
        host.innerHTML = '<div class="empty">Type something to search for.</div>';
        return;
      }
      S.search.q = q;
    }

    host.innerHTML = '<div class="loading">Searching…</div>';

    /* ---- Dispatch to the right API per search type ---------------------- */
    if (t === 'morph') {
      /* Morph search goes to the dedicated study/morph endpoint. */
      const mid = ($('#s-morph-resource') || {}).value || '';
      const ref = (($('#s-morph-passage') || {}).value || '').trim();
      r = await api('study/morph', { code: q.replace(/^morph:/, ''), module_id: mid,
                                    ref, limit: 300 });
      if (!r.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(r.error || 'search failed')));
        return;
      }
      /* Normalize morph results into the common hit shape. */
      const hits = (r.hits || []).map(x => ({
        module_id: x.module_id,
        key: x.key,
        label: x.ref ? (x.ref.label || x.ref.book + ' ' + x.ref.chapter + ':' + x.ref.verse) : x.key,
        module_name: (S.modules || []).find(m => m.id === x.module_id)?.name || x.module_id,
        snippet_html: '<span class="tiny muted">' + esc(x.surface || x.code) + '</span>',
        matched: [x.code],
        rank: 1
      }));
      r = { ok: true, hits, total: r.total || hits.length, ms: null, warnings: [],
            smart: [], operators: [], groups: {}, group_meta: {} };
    } else if (t === 'books') {
      const collection = ($('#s-books-collection') || {}).value || '';
      const btype = ($('#s-books-type') || {}).value || '';
      const module_ids = collection ? [collection] : [];
      const raw = await api('books-search', { q, module_ids, type: btype, limit: 400 });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const hits = (raw.results || []).map(x => ({
        module_id: x.module_id || '',
        key: x.key || x.ref || '',
        label: x.ref || x.title || x.key || '',
        module_name: x.module || '',
        snippet_html: '<span class="tiny muted">' + esc((x.text || '').slice(0, 160)) + '</span>',
        matched: [],
        rank: 1
      }));
      r = { ok: true, hits, total: raw.count || hits.length, more: !!raw.more,
            ms: null, warnings: [], smart: [], operators: [], groups: {}, group_meta: {} };
    } else if (t === 'topics') {
      const source = ($('#s-topics-source') || {}).value || '';
      /* Topics is the FactBook: search the books' headings for the entry a
       * reader means, and open the Topics guide when a hit is clicked.
       * (This used to dispatch a text LIKE match across every module, which
       * counted Bible verses as "results" and never surfaced the entries.) */
      const raw = await api('factbook-search', { q, module_ids: source ? [source] : [],
                                                 limit: 400 });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const hits = (raw.results || []).map(x => ({
        module_id: x.module_id || '',
        key: x.key || '',
        label: x.title || x.key || '',
        module_name: x.module || '',
        snippet_html: '<span class="tiny muted">' + esc((x.text || '').slice(0, 200)) + '</span>'
          + (x.length && x.length > 1500
            ? ' <span class="tiny">(full entry, ' + esc(x.length) + ' chars)</span>'
            : ''),
        matched: [],
        rank: 1
      }));
      r = { ok: true, hits, total: raw.count || hits.length, more: !!raw.more,
            ms: null, warnings: [], smart: [], operators: [], groups: {}, group_meta: {} };
    } else if (t === 'media') {
      const source = ($('#s-media-source') || {}).value || '';
      const license = ($('#s-media-license') || {}).value || '';
      const raw = await api('media/images', { q, source, license: license, limit: 48 });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const hits = (raw.results || []).map(x => ({
        module_id: 'media',
        key: x.id || '',
        label: x.title || x.id || '',
        module_name: 'Media',
        snippet_html: '<span class="tiny muted">' + esc(x.source || '') + '</span>'
          + ' <span class="tiny">' + esc((x.license || '')) + '</span>',
        matched: [],
        rank: 1,
        media_url: x.url || '',
        media_thumb: x.thumbnail || ''
      }));
      r = { ok: true, hits, total: raw.count || hits.length, ms: null, warnings: [],
            smart: [], operators: [], groups: {}, group_meta: {} };
    } else if (t === 'documents') {
      const kind = ($('#s-docs-kind') || {}).value || '';
      const raw = await api('notes/list', { q, kind, limit: 400 });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const hits = (raw.notes || []).map(x => ({
        module_id: 'documents',
        key: x.id || '',
        label: x.title || x.key || '',
        module_name: 'Documents',
        snippet_html: '<span class="tiny muted">' + esc(x.kind || '') + '</span>'
          + ' <span class="tiny">' + esc((x.body || x.preview || x.text || '').slice(0, 160)) + '</span>',
        matched: [],
        rank: 1
      }));
      r = { ok: true, hits, total: raw.total || hits.length,
            more: !!raw.more, ms: null, warnings: [],
            smart: [], operators: [], groups: {}, group_meta: {} };
    } else if (t === 'maps') {
      const raw = await api('maps/places', { q, limit: 400 });
      if (!raw.ok) {
        host.innerHTML = '';
        host.appendChild(el('div', 'warn', esc(raw.error || 'search failed')));
        return;
      }
      const mapTypeFilter = ($('#s-map-type') || {}).value || '';
      const places = (raw.places || []).filter(p => !mapTypeFilter || p.type === mapTypeFilter);
      const hits = places.map(x => ({
        module_id: 'maps',
        key: x.key || '',
        label: x.label || x.name || '',
        module_name: 'Maps',
        snippet_html: '<span class="tiny muted">' + esc((x.book || '') + ' ' + (x.chapter || '') + ':' + (x.verse || '')).trim() + '</span>',
        matched: [],
        rank: 1
      }));
      r = { ok: true, hits, total: hits.length, ms: null, warnings: [],
            smart: [], operators: [], groups: {}, group_meta: {} };
    } else {
      /* 'all' / 'bible' — combined text search via the main endpoint.  A
       * passage filter is resolved to a canonical ref and added as a search
       * scope, which the query engine already understands. */
      let finalQ = q;
      if (scopedPassage) {
        const rr = await api('reference', { ref: scopedPassage });
        if (token !== this.goToken) return;
        // Use the OSIS key, not the display label: "John 3:16" would tokenise
        // as "ref:John" plus "3:16" and match nothing.
        if (rr && rr.ok && rr.key) finalQ = q + ' ref:' + rr.key;
        else toast('Passage not recognised: ' + scopedPassage, 'warn');
      }
      const mods = scopedModules || S.search.mods || [];
      const range = scopedPassage ? '' : ($('#s-range').value || '');
      if (range) {
        const raw = await api('search/ranges', { action: 'search', q: finalQ,
          range, opts: { scope: S.search.opts.scope,
                         modules: mods,
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
        r.rangeNote = raw.truncated
          ? 'More matched outside the ' + raw.range + ' window than were '
            + 'searched, so this may be short of the whole range.'
          : '';
      } else {
        usedMain = true;
        this.lastQuery = { q: finalQ, mods };
        r = await api('search', {
          q: finalQ, scope: S.search.opts.scope, match_case: S.search.opts.match_case,
          modules: mods,
          match_all_forms: S.search.opts.match_all_forms,
          include_resolved: S.search.opts.include_resolved ? 1 : 0,
          context: S.search.opts.context, sort: S.search.opts.sort,
          limit: this.limit });
      }
    }
    if (token !== this.goToken) return;
    host.innerHTML = '';
    if (!r.ok) {
      this.view = 'results';   // an error must not leave a later search in Analysis
      host.appendChild(el('div', 'warn', esc(r.error)));
      return;
    }
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
    /* Analysis is a second reading of the same result set, not a second
     * search the reader has to remember.  It only applies to the main text
     * endpoint; the specialized modes build their own hit shapes. */
    // A search type or query with no results has no Analysis tab to switch
    // back from, so never leave the view stuck in that mode.
    if (!usedMain || !r.hits || !r.hits.length) this.view = 'results';
    if (usedMain && r.hits && r.hits.length) {
      const tabs = el('div', 'sgroups-bar');
      const list = el('button', 'btn tiny'
        + (this.view === 'analysis' ? '' : ' primary'), 'Results');
      list.onclick = () => { this.view = 'results'; this.go(); };
      const grid = el('button', 'btn tiny'
        + (this.view === 'analysis' ? ' primary' : ''), 'Analysis');
      grid.onclick = () => { this.view = 'analysis'; this.go(); };
      tabs.appendChild(list);
      tabs.appendChild(grid);
      host.appendChild(tabs);
      if (this.view === 'analysis') {
        this.renderAnalysis(host, q);
        return;
      }
    }

    if ((S.search.mods || []).length) {
      const names = S.search.mods.map(id => modLabel(id));
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

    if (r.truncated || r.more || (r.total && r.hits.length < r.total)) {
      const note = el('div', 'tiny muted',
        `Showing ${r.hits.length} of ${r.total} matches, grouped by resource. `
        + 'A resource may show fewer rows than its count.');
      host.appendChild(note);
      const moreBtn = el('button', 'btn tiny', 'Show ' + this.limit + ' more');
      moreBtn.style.marginTop = '4px';
      moreBtn.onclick = () => {
        this.limit += 400;
        this.go();
      };
      host.appendChild(moreBtn);
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
        + '<button class="btn tiny hit-send" title="Send this result to a study tool">send to…</button>'
        + '<span class="rank">' + h.rank + '</span></div>'
        + '<div class="sn">' + h.snippet_html + '</div>'
        + (h.context && h.context.length
          ? '<div class="tiny muted" style="margin-top:5px">'
          + h.context.map(c => '<span style="margin-right:10px' + (c.current
            ? ';color:var(--accent)' : '') + '">' + esc(c.label) + '</span>').join('')
          + '</div>' : '');
      const send = n.querySelector('.hit-send');
      if (send) send.onclick = (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        Search.sendTo(h, ev.clientX, ev.clientY);
      };
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
    /* Add Versions -- show the same search side by side across
     * translations.  Offer the other tagged resources and render each
     * selection as its own column of verse hits. */
    if (this.type === 'morph') {
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
          + '<span class="t">' + esc(meta.name || modLabel(mid)) + '</span>'
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
          if (open && meta.reader === 'verse' && !head.querySelector('button.scope')) {
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
    const q = ($('#sq') || {}).value || '';
    const r = await api('search/help', { q });
    const h = $('#search-help');
    if (!h) return;
    h.innerHTML = '<h4>Query language</h4>';
    if (!r || r.ok === false) {
      h.appendChild(el('div', 'note', esc((r && r.error) || 'Could not load the query help.')));
      return;
    }
    (r.warnings || []).forEach(w => h.appendChild(el('div', 'note', esc(w))));
    (r.operators || []).forEach(o => {
      h.appendChild(el('div', 'note', esc(o.note)));
      const c = el('code', '', esc(o.syntax));
      c.onclick = () => {
        if (this.type !== 'all') this.setType('all');
        $('#sq').value = o.syntax; $('#sq').focus();
      };
      h.appendChild(c);
    });
  },
};

/* ======================================================== Module Browser */
/* Rebuilt from scratch.  The old Store was a flat list of interchangeable
   rows; this one is organised by *where the module goes*, says so before you
   download it, warns when something is already installed or already open in a
   pane, and can forget a repository entirely. */

/* ============================================== Morphology @ helper ===
   Reusable @ morphology popup. When the user types a word followed by @,
   look up the word's grammatical forms and show a dropdown. Clicking a form
   replaces the trailing @ with the selected morphology code.

   Usage: attachMorphAtPopup(inputElement, resourceGetter, passageGetter)
     resourceGetter: a function or string returning the module_id to search
       ('' means every tagged resource).
     passageGetter:  an optional function returning the passage to limit the
       search to (e.g. "John 3"), or '' for the whole text.

   This was deleted with the Study Tools Morph pane (d89d682) while the
   search bar's Morph type still calls it, which left `love@` doing
   nothing at all.  Restored here, sharing the same CSS. */
function attachMorphAtPopup(input, resourceGetter, passageGetter) {
  if (!input) return;
  let timer = 0;
  const parent = input.parentElement;
  if (!parent) return;
  parent.style.position = 'relative';

  const popup = document.createElement('div');
  popup.className = 'morph-at-popup';
  popup.style.display = 'none';
  parent.appendChild(popup);

  const clearForms = () => { popup.innerHTML = ''; popup.style.display = 'none'; };

  const getModuleId = () => {
    if (typeof resourceGetter === 'function') return resourceGetter();
    return resourceGetter || '';
  };
  const getRef = () => {
    if (typeof passageGetter === 'function') return passageGetter();
    return passageGetter || '';
  };

  const showForms = async (raw) => {
    const w = (raw || '').replace(/@\s*$/, '').trim();
    if (!w) { clearForms(); return; }
    const mid = getModuleId();
    const ref = getRef();
    popup.innerHTML = '<div class="tiny muted" style="padding:8px">looking up forms…</div>';
    popup.style.display = '';
    /* Module left empty searches every tagged resource — the same set the
     * "All tagged resources" dropdown searches. */
    const r = await api('morph/wordforms', { module_id: mid, word: w,
                                             limit: 12, ref });
    popup.innerHTML = '';
    if (!r.ok || !r.forms || !r.forms.length) {
      popup.innerHTML = '<div class="tiny muted" style="padding:8px">no tagged forms found for "' + esc(w) + '"</div>';
      return;
    }
    /* Show the scope the forms were found in, so it is clear the dropdown
     * is restricted. */
    const scopeBits = [];
    if (!mid) scopeBits.push('all tagged resources');
    if (ref) scopeBits.push(ref);
    if (scopeBits.length) {
      const d = document.createElement('div');
      d.className = 'tiny muted';
      d.style.cssText = 'padding:6px 10px 0;border-bottom:1px solid var(--line)';
      d.textContent = 'Forms in ' + scopeBits.join(' · ');
      popup.appendChild(d);
    }
    r.forms.forEach(f => {
      const btn = document.createElement('button');
      const feat = Study._morphLabel(f.features);
      btn.innerHTML = '<div style="display:flex; justify-content:space-between">'
        + '<b>' + esc(w) + '</b>'
        + '<span class="tiny muted">' + esc(f.code) + ' · ' + Number(f.count || 0).toLocaleString() + '</span></div>'
        + '<div class="feat">' + esc(feat) + '</div>';
      btn.onclick = () => {
        /* Replace the trailing @ with the selected code. */
        const val = input.value;
        const at = val.lastIndexOf('@');
        if (at >= 0) {
          input.value = val.slice(0, at + 1) + f.code;
        } else {
          input.value = f.code;
        }
        clearForms();
        input.focus();
      };
      popup.appendChild(btn);
    });
  };

  input.oninput = (e) => {
    clearTimeout(timer);
    if (/@\s*$/.test(e.target.value)) {
      timer = setTimeout(() => showForms(e.target.value), 250);
    } else {
      clearForms();
    }
  };

  /* Close popup when clicking outside. */
  document.addEventListener('click', (ev) => {
    if (ev.target !== input && !popup.contains(ev.target)) {
      clearForms();
    }
  });
}
