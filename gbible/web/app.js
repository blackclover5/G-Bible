const App = {
  async boot() {
    // Wire the UI first.  bind() attaches every nav button, and it used to run
    // last -- after five sequential network round-trips -- so a single failed or
    // slow request left the page rendering but completely unresponsive, with no
    // error shown anywhere.  Interactive-but-empty beats dead.
    this.bind();
    Appearance.init();
    try {
      const st = await api('status');
      $('#status').innerHTML = st.total
        ? `${st.total} module${st.total === 1 ? '' : 's'} · ${esc(st.size_label)}`
        : 'no modules — visit the <b>Store</b>';
      const tax = await api('taxonomy');
      S.tax = tax; S.types = tax.types; S.subjects = tax.subjects; S.langs = tax.languages;
      await this.loadLibrary();
      RecommendedPrompt.maybeShow().catch(() => {});
      await this.loadWorkspace();
      // Load the highlights up front: mark() reads this cache while painting a
      // pane, so without this a page reload shows no marks at all until
      // something else happens to trigger a load.  Deliberately not awaited --
      // a failure here must never stop the reader from opening.
      Highlights.load().catch(() => {});
      Highlights.loadPalettes().catch(() => {});
      // The tags too, for the same reason: the reader marks a tagged verse as
      // it paints, and a pane painted before the tags arrived would show no
      // mark until something else happened to trigger a reload.
      Tags.load().catch(() => {});
      ClickSearch.load().catch(() => {});
      this.fillSelectors();
      // The user may have clicked a view before its data landed; repaint it now
      // that the data is here.
      if (S.view === 'library') Library.load();
      if (S.view === 'today') Dashboard.load();
    } catch (err) {
      // Say so.  A dead UI with a silent console is the hardest kind of bug.
      const msg = (err && err.message) || String(err);
      $('#status').innerHTML = `<span style="color:#f0a0a5">could not load: ${esc(msg)}</span>`;
      console.error('gbible boot failed', err);
      toast('Could not reach the local server: ' + msg, 'err');
    }
  },

  async loadLibrary() {
    const r = await api('library', { links: 1 });
    S.modules = r.modules || [];
    S.links = r.links || {};
  },

  /* Populate the Store's category / subject / language filters.
   *
   * This is what boot() calls after loading the taxonomy.  It was referenced but
   * never defined, so the call threw -- which is what left the whole page
   * unresponsive, because it happened just before bind().  The three selects
   * were read by Store.fetch() but never given any options, so filtering the
   * catalogue by type, subject or language silently matched nothing.
   */
  fillSelectors() {
    const add = (sel, items, keep) => {
      if (!sel || sel.options.length > 1) return;   // already filled
      const prev = keep && sel.value;
      for (const [value, label] of items) {
        sel.appendChild(el('option', '', esc(label)));
        sel.lastChild.value = value;
      }
      if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    };
    // value must be the type id -- Store.fetch() sends it as `category`.
    add($('#f-cat'), (S.types || []).map(t => [t.id, t.label]));
    // Subjects are bare strings ("OT", "NT"), sent as-is.
    add($('#f-subj'), (S.subjects || []).map(s => [s, s]));
    // Languages arrive as [name, code]; the API wants the code.
    add($('#f-lang'), (S.langs || []).map(([n, c]) => [c, n]));
    /* The book ranges are named sets the server builds from the canon table,
     * so they are fetched rather than hard-coded here -- a list written in
     * the front end would drift from the canon table the moment a book were
     * renamed.  Filled once: `add` returns early if the select already has
     * options, so re-entering boot cannot duplicate them. */
    if ($('#s-range') && $('#s-range').options.length <= 1) {
      api('search/ranges').then((r) => {
        const sel = $('#s-range');
        if (!sel) return;
        (r.ranges || []).forEach(g => {
          const o = el('option', '', esc(g.name) + ' (' + g.count + ')');
          o.value = g.name;
          sel.appendChild(o);
        });
      }).catch(() => {});
    }
  },

  async loadWorkspace() {
    const r = await api('workspace');
    S.layout = r.layout;
    S.arrangements = r.arrangements || {};
    S.guide = r.guide || {};
    S.linkSets = r.link_sets || ['A', 'B', 'C', 'D', 'E', 'F'];
    S.linkGroups = (await api('workspace/linksets')).groups || {};
    this.renderWorkspace();
  },

  show(v) {
    S.view = v;
    $$('#nav button[data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === v));
    $$('#nav .nav-menu').forEach(w => {
      const btn = w.querySelector('.menu-btn');
      const openBtn = w.querySelector('button[data-view="' + v + '"]');
      btn.classList.toggle('on', !!openBtn);
    });
    $$('.view').forEach(n => n.classList.toggle('on', n.id === 'v-' + v));
    if (v === 'store') Store.load();
    if (v === 'library') Library.load();
    if (v === 'concordance') Study.loadConcordance();
    if (v === 'maps') MapsUI.load();
    if (v === 'media') Media.load();
    if (v === 'ntuseot') Study.loadNtuSeOt();
    if (v === 'apis') Apis.load();
    if (v === 'ai') Ai.load();
    if (v === 'aisettings') AiSettings.load();
    if (v === 'notes') Notes.load();
    if (v === 'today') Dashboard.load();
    if (v === 'guides') { Guides.load(); }
    if (v === 'sermon-manager') {
      const smTab = $('#sm-tab'); if (smTab) smTab.value = 'sermon-manager';
      SermonHub.load();
    }
    if (v === 'organise') { Organise.load(); }
    if (v === 'search') { Search.loadTemplates(); }
    if (v === 'wordlists') { WordLists.load(); }
    if (v === 'memorization') { Memorization.load(); }
    if (v === 'workflows') { Flows.load(); }
    if (v === 'sync') Sync.load();
    if (v === 'plans') { Plans.load(); }
    if (v === 'prayer') { Prayer.load(); }
    if (v === 'clippings') { Clippings.load(); }
  },

  /* ------------------------------------------------------------ tiles */
  rowsToTree(rows) {
    /* Row-based layouts are wrapped in a vertical stack of one row each.  Each
     * row is made flush with no explicit size, so two old columns keep their
     * relative size by loading exactly what they were saved as.  New splits use
     * the tree form, and that is why splitting never had an arrangement name
     * again: it is no longer a fixed template. */
    if (!rows || !rows.length) return { kind: 'group', dir: 'row', ratios: [1.0], children: [{ kind: 'tile', id: 't0_0' }] };
    const groups = rows.map((row, ri) => ({
      kind: 'group',
      dir: 'row',
      /* A row with one pane in it is the full width of that row.  Ratios only
       * divide a row between *several* panes: a lone [0.5] row was rendered at
       * half width with the other half of the workspace left empty, which is
       * what "Bible Left / 3 Right" used to do. */
      ratios: (row.length === 1 ? [1.0] : row).map(x => Number(x) || 1),
      children: row.map((_, ci) => ({ kind: 'tile', id: 't' + ri + '_' + ci })),
    }));
    if (groups.length === 1) {
      // A single row was the normal case; do not wrap it in another tier, it
      // would add an invisible nesting level and throw off every later split.
      return groups[0];
    }
    return { kind: 'group', dir: 'column', ratios: groups.map(() => 1), children: groups };
  },

  ensureTiles() {
    const t = S.layout.tiles;
    if (!t) return this.rowsToTree([[1.0]]);
    if (Array.isArray(t)) return this.rowsToTree(t);
    if (t.kind === 'tile') {
      return { kind: 'group', dir: 'row', ratios: [1.0], children: [t] };
    }
    return t;
  },

  leafTileIds(node) {
    if (!node) return [];
    if (Array.isArray(node)) {
      const ids = [];
      node.forEach((row, ri) => {
        if (!Array.isArray(row)) return;
        row.forEach((_, ci) => ids.push('t' + ri + '_' + ci));
      });
      return ids;
    }
    if (node.kind === 'tile') return [node.id];
    return (node.children || []).flatMap(c => this.leafTileIds(c));
  },

  tileById(node, id) {
    if (!node) return null;
    if (node.kind === 'tile' && node.id === id) return node;
    if (!node.children) return null;
    for (const c of node.children) {
      const hit = this.tileById(c, id);
      if (hit) return hit;
    }
    return null;
  },

  findTileNode(node, id) {
    if (!node || !node.children) return null;
    for (let i = 0; i < node.children.length; i++) {
      const child = node.children[i];
      if (child.kind === 'tile' && child.id === id) return { node: child, parent: node, index: i };
      const hit = this.findTileNode(child, id);
      if (hit) return hit;
    }
    return null;
  },

  removeTileLeaf(node, id) {
    if (!node || typeof node !== 'object') return node;
    if (node.kind === 'tile') return node.id === id ? null : node;
    node.children = (node.children || [])
      .map(c => this.removeTileLeaf(c, id))
      .filter(Boolean);
    if (node.children.length === 0) return null;
    if (node.children.length === 1) return node.children[0];
    return node;
  },

  /* Replace one tile node with a new group containing the old tile and the new
   * one.  Nesting one more group inside the same slot gives same-size children
   * without touching any of the panes already in the old tile. */
  splitTile(tree, id, dir, newId) {
    const tileId = newId || ('t' + Math.random().toString(36).slice(2, 8));
    if (tree && tree.kind === 'tile' && tree.id === id) {
      const replacement = {
        kind: 'group',
        dir: dir,
        ratios: [0.5, 0.5],
        children: [tree, { kind: 'tile', id: tileId }],
      };
      return { tree: replacement, newId: tileId };
    }
    const hit = this.findTileNode(tree, id);
    if (!hit) return null;
    const replacement = {
      kind: 'group',
      dir: dir,
      ratios: [0.5, 0.5],
      children: [hit.node, { kind: 'tile', id: tileId }],
    };
    hit.parent.children[hit.index] = replacement;
    return { tree: tree, newId: tileId };
  },

  renderWorkspace() {
    const host = $('#tiles');
    host.innerHTML = '';
    if (!S.layout) { host.appendChild(el('div', 'empty', 'No workspace yet.')); return; }
    const panes = S.layout.panes || [];
    const tree = this.ensureTiles();
    const leaves = this.leafTileIds(tree);
    /* A pane filed under a tile the tree does not ask for renders nowhere:
       silently lost, with no error anywhere.  It has to be *re-filed*, not
       re-bucketed in a local map -- renderTile buckets the panes again from
       S.layout, so writing to a map here changed nothing and the pane stayed
       invisible.  The home is the first tile, the one every older layout would
       have opened. */
    const first = leaves[0];
    if (first) {
      panes.forEach(p => {
        if (!leaves.includes(this.tileKey(p.tile_id))) p.tile_id = first;
      });
    }

    /* Keep the tree the DOM was built from as the layout's own.  Rows are the
     * stored form and every `ensureTiles` builds a new object from them, so a
     * divider dragged after an arrangement edited a copy: the panes moved, the
     * save sent the untouched ratios back, and the split snapped back to even
     * on the next load.  Splitting already adopts the tree this way. */
    S.layout.tiles = tree;

    const root = el('div', 'layout-root');
    this.renderNode(tree, root, 1);
    host.appendChild(root);
  },

  /* Render one node.  The ratio the parent group reserved for this child is
   * applied to self:flex.  Handles live inside a group, not inside leaves, so
   * moving a divider never has to know why sibling is a tile or a split. */
  renderNode(node, parent, ratio) {
    if (!node || typeof node !== 'object') return null;
    if (node.kind === 'tile') {
      const wrap = el('div', 'tile-slot');
      wrap.style.flex = String(ratio || 1);
      wrap.appendChild(this.renderTile(node.id));
      parent.appendChild(wrap);
      return wrap;
    }
    const g = el('div', 'layout-group ' + (node.dir === 'row' ? 'lyt-row' : 'lyt-col'));
    g.style.flex = String(ratio || 1);
    const kids = [];
    node.children.forEach((child, ci) => {
      const childEl = this.renderNode(child, g, (node.ratios && node.ratios[ci]) || 1);
      if (childEl) kids.push(childEl);
      if (ci < node.children.length - 1) {
        const h = el('div', 'layout-handle ' + (node.dir === 'row' ? 'vx' : 'hx'));
        this.bindResize(h, g, node, ci, kids);
        g.appendChild(h);
      }
    });
    g._kids = kids;
    g._group = node;
    parent.appendChild(g);
    return g;
  },

  renderTile(tileId) {
    const tile = el('div', 'tile');
    tile.dataset.tile = tileId;
    /* The slot owns the ratio: it is the fraction of the group this pane takes
     * along the group's axis.  The slot is a column, and the tile is its only
     * child, so the tile has to fill it -- `flex: 0.5` on the tile meant half
     * of the slot's *height*, which is why every arrangement with a ratio under
     * one left the bottom half of the pane empty.  Flex factors are also scaled
     * by their sum, so 0.34 rendered a third of the height, not all of it. */
    tile.style.flex = '1 1 0%';
    const tabs = el('div', 'tile-tabs');
    const byTile = new Map();
    (S.layout.panes || []).forEach(p => {
      const t = this.tileKey(p.tile_id);
      if (!byTile.has(t)) byTile.set(t, []);
      byTile.get(t).push(p);
    });
    const list = byTile.get(tileId) || [];
    (list.length ? list : []).forEach((p, idx) => {
      const m = modById(p.module_id);
      const tabName = m ? m.name
        : (p.view === 'guide' ? 'Passage'
          : (p.view === 'wordstudy' ? 'Word Study' : '(closed)'));
      const tab = el('div', 'tile-tab' + (idx === 0 ? ' on' : ''));
      if (p.link_set) tab.appendChild(el('span', 'ls ' + p.link_set, p.link_set));
      tab.appendChild(el('span', 'modname', tabName));
      const x = el('span', 'x', '✕');
      x.onclick = (e) => { e.stopPropagation(); Workspace.closePane(p.id); };
      x.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); Study.menu(e.clientX, e.clientY, [
        { label: 'Add another pane beside', fn: () => Workspace.split(p.id, 'row') },
        { label: 'Split this pane below', fn: () => Workspace.split(p.id, 'column') },
        { label: 'Float in new window', fn: () => Workspace.floatPane(p.id) },
        { label: 'Fullscreen reading', fn: () => Workspace.fullscreen(p.id) },
        { label: 'Copy location', fn: () => Workspace.copyLocation(p.id) },
        { label: 'Mark progress here', fn: () => Workspace.markHere(p.id) },
        { label: 'Close pane', fn: () => Workspace.closePane(p.id) },
      ]); };
      tab.appendChild(x);
      tab.draggable = true;
      tab.addEventListener('dragstart', (ev) => {
        ev.dataTransfer.setData('text/plain', p.id);
        ev.dataTransfer.effectAllowed = 'move';
      });
      tab.addEventListener('dragover', (ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        tab.classList.add('dragover');
      });
      tab.addEventListener('dragleave', () => tab.classList.remove('dragover'));
      tab.addEventListener('drop', (ev) => {
        ev.preventDefault();
        tab.classList.remove('dragover');
        const srcId = ev.dataTransfer.getData('text/plain');
        if (!srcId || srcId === p.id) return;
        const panes = (S.layout && S.layout.panes) || [];
        const srcIdx = panes.findIndex(x => x.id === srcId);
        const dstIdx = panes.findIndex(x => x.id === p.id);
        if (srcIdx < 0 || dstIdx < 0) return;
        const [moved] = panes.splice(srcIdx, 1);
        moved.tile_id = p.tile_id;
        let insertAt = dstIdx;
        if (srcIdx < dstIdx) insertAt--;
        if (insertAt < 0) insertAt = 0;
        panes.splice(insertAt, 0, moved);
        App.saveCurrentTree().then(() => App.loadWorkspace());
      });
      tab.onclick = (ev) => { if (ev.target.classList.contains('x')) return; this.showPane(tileId, p.id); };
      tabs.appendChild(tab);
    });
    const add = el('div', 'tile-tab', '<span style="color:var(--fg-3)">+</span>');
    add.onclick = () => Workspace.pickModule(tileId);
    tabs.appendChild(add);
    tile.appendChild(tabs);
    const active = list[0];
    const pane = el('div', 'pane');
    pane.dataset.pane = active ? active.id : '';
    tile.appendChild(pane);
    if (active) this.fillPane(pane, active);
    else pane.appendChild(el('div', 'empty', 'Open a resource with +'));
    return tile;
  },

  bindResize(handle, groupEl, node, index, kids) {
    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      const start = { x: e.clientX, y: e.clientY };
      const rectA = kids[index].getBoundingClientRect();
      const rectB = kids[index + 1].getBoundingClientRect();
      const sum = node.dir === 'row' ? rectA.width + rectB.width : rectA.height + rectB.height;
      const startRatio = (node.ratios && node.ratios[index]) || 1;
      const startRatioNext = (node.ratios && node.ratios[index + 1]) || 1;
      const totalRatio = startRatio + startRatioNext;
      const onMove = (ev) => {
        const delta = node.dir === 'row' ? ev.clientX - start.x : ev.clientY - start.y;
        const ratioMoved = (delta / Math.max(1, sum)) * totalRatio;
        const min = Math.max(0.12, totalRatio * 0.12);
        let a = startRatio + ratioMoved;
        a = Math.max(min, Math.min(totalRatio - min, a));
        const b = totalRatio - a;
        if (node.ratios) node.ratios[index] = a;
        if (node.ratios) node.ratios[index + 1] = b;
        kids[index].style.flex = String(a);
        kids[index + 1].style.flex = String(b);
      };
      const onUp = async () => {
        handle.releasePointerCapture(e.pointerId);
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onUp);
        await App.saveCurrentTree();
      };
      handle.addEventListener('pointermove', onMove);
      handle.addEventListener('pointerup', onUp);
    });
  },

  /* A pane saved as "t0_2" must file under "t0_2", not "t0": a pane in a
   * bucket no tile asks for renders nowhere.  A bare "t0" from an older save
   * means the first tile. */
  tileKey(id) {
    const v = (id || '').trim();
    // Was /^t\d+_\d+$/ only, which sent a pane filed under a custom split tile
    // back into the first tile.  A pane in a custom split would then render nowhere.
    return (v && v !== 't0' && v !== 't') ? v : 't0_0';
  },

  async saveCurrentTree() {
    const lay = S.layout;
    if (!lay || !lay.id) return lay;
    const r = await post('workspace/save', {
      id: lay.id, name: lay.name || 'Layout',
      tiles: this.ensureTiles(), panes: lay.panes || [],
    });
    if (r && r.layout) S.layout = r.layout;
    return S.layout;
  },

  showPane(tileId, paneId) {
    const tid = this.tileKey(tileId);
    const panes = (S.layout.panes || []).filter(p => this.tileKey(p.tile_id) === tid);
    const idx = panes.findIndex(p => p.id === paneId);
    if (idx < 0) return;
    /* "The first tile that has tabs" is not the tile you asked for: selecting a
     * tab in the third column moved the first column instead.  Ask for the tile
     * by id, and only fall back if the layout predates the attribute. */
    let tile = $('.tile[data-tile="' + tid + '"]');
    if (!tile) tile = $$('.tile').find(t => t.querySelector('.tile-tab'));
    if (!tile) return;
    const tabs = $$('.tile-tab', tile);
    tabs.forEach((t, k) => t.classList.toggle('on', k === idx));
    const pane = $('.pane', tile);
    if (pane) { pane.dataset.pane = panes[idx].id; this.fillPane(pane, panes[idx]); }
  },

  async fillPane(pane, p) {
    pane.innerHTML = '';
    const m = modById(p.module_id);
    const tools = el('div', 'pane-tools');
    const body = el('div', 'pane-body');
    pane.appendChild(tools); pane.appendChild(body);
    tools.appendChild(el('span', 'mod', m ? m.name : (p.view === 'guide' ? 'Passage' : '(none)')));
    /* Resolves the verse a button should act on: the user's clicked selection,
     * falling back to the first item in the pane, then to verse 1 of the current
     * chapter. Defined once here so every verse button (Study, Visual, Compare,
     * Info, Merge, Interlinear…) shares the same resolution. */
    const here = () => {
      if (p.selectedVerse) return p.selectedVerse;
      const c = p._content || {};
      const it = (c.items || [])[0];
      if (!it) {
        const ref = p.cursor.ref || '';
        const parts = ref.split(/[\s:]/);
        if (parts[0]) {
          const book = parts[0];
          const chapter = parts[1] || '1';
          return { key: book + '.' + chapter + '.1', label: book + ' ' + chapter + ':1' };
        }
        return null;
      }
      return { key: it.key, label: c.ref_label || it.label || '' };
    };
    if (!m && p.view !== 'guide') { body.appendChild(el('div', 'empty', 'No resource in this tab.')); return; }
    if (p.view === 'guide') {
      const refBox = el('input', 'refbox');
      refBox.value = (p.cursor && (p.cursor.ref || p.cursor.key)) || '';
      refBox.placeholder = 'Jn 3:16';
      refBox.onkeydown = (e) => { if (e.key === 'Enter') { Study.openPassage(refBox.value, p.cursor && p.cursor.guide, body); } };
      tools.appendChild(refBox);
      const ref = (p.cursor && (p.cursor.ref || p.cursor.key)) || '';
      if (ref) Study.openPassage(ref, (p.cursor && p.cursor.guide) || 'passage', body);
      else body.innerHTML = '<div class="empty">Type a reference and press Enter.</div>';
      return;
    }
    if (p.view === 'wordstudy') {
      const numBox = el('input', 'refbox');
      numBox.value = (p.cursor && p.cursor.number) || '';
      numBox.placeholder = 'G2316 / H430';
      const render = async (num) => {
        body.innerHTML = '<div class="st-loading">Gathering…</div>';
        const r = await api('study/word', { number: num });
        if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error || 'failed') + '</div>'; return; }
        let h = '<div class="st-ref">' + esc(r.number) + '</div>';
        if (r.word || r.lemma) h += '<div class="st-body"><b>' + esc(r.word) + '</b> '
          + esc(r.lemma) + ' · ' + (r.total || 0) + ' occurrences</div>';
        if ((r.entries || []).length) {
          h += '<div class="st-sec open"><div class="st-h">Lexicon entries</div>'
            + r.entries.map(e => '<div class="st-note"><div class="st-src">' + esc(e.module || '')
            + '</div><div class="st-body">' + esc(e.text || '') + '</div></div>').join('') + '</div>';
        }
        if ((r.by_book || []).length) {
          h += '<div class="st-sec"><div class="st-h">By book</div>'
            + r.by_book.map(([b, n]) => '<span style="margin-right:8px">' + esc(b) + ' ' + n + '</span>').join('') + '</div>';
        }
        body.innerHTML = h;
        $$('.st-h', body).forEach(hh => hh.onclick = () => hh.parentElement.classList.toggle('open'));
      };
      numBox.onkeydown = (e) => { if (e.key === 'Enter') { p.cursor = p.cursor || {}; p.cursor.number = numBox.value; Reader.saveNow && Reader.saveNow(p); render(numBox.value); } };
      tools.appendChild(numBox);
      const n = (p.cursor && p.cursor.number) || '';
      if (n) render(n);
      else body.innerHTML = '<div class="empty">Type a Strong’s number and press Enter.</div>';
      return;
    }

    /* -- reader-specific controls -- */
    if (m.reader === 'verse') {
      const box = el('input', 'refbox');
      box.value = p.cursor.ref || '';
      box.placeholder = 'Jn 3:16';
      box.onkeydown = (e) => {
        if (e.key !== 'Enter') return;
        // Dismiss the suggestion list before navigating.  It stays anchored
        // under the box and hangs over the first lines of the chapter, where it
        // silently swallowed the next click -- a right-click meant for a verse
        // landed on the dropdown, so the verse could not be identified and the
        // action was filed against the wrong one.
        Reader.suggest(box, '');
        box.blur();
        Reader.go(p, box.value);
      };
      box.oninput = debounce(() => Reader.suggest(box, box.value), 180);
      box.onblur = () => Reader.suggest(box, '');
      const prev = el('button', '', '◀'); prev.title = 'Previous book';
      prev.onclick = () => Reader.step(p, 'prevbook');
      const next = el('button', '', '▶'); next.title = 'Next book';
      next.onclick = () => Reader.step(p, 'nextbook');
      const pc = el('button', '', '❮'); pc.title = 'Previous chapter';
      pc.onclick = () => Reader.step(p, 'prevchapter');
      const nc = el('button', '', '❯'); nc.title = 'Next chapter';
      nc.onclick = () => Reader.step(p, 'nextchapter');
      tools.append(prev, pc, box, nc, next);
      /* Pack 6: parallel prev/next steps through same-type resources in
       * priority order; the edition toggle swaps study/clean rendering. */
      const parP = el('button', '', '‹‖'); parP.title = 'Previous parallel resource';
      parP.onclick = async () => {
        const r = await Workspace.parallelStep(p.module_id, -1);
        if (!r || !r.ok) toast('No parallel resource.', 'warn');
      };
      const parN = el('button', '', '‖›'); parN.title = 'Next parallel resource';
      parN.onclick = async () => {
        const r = await Workspace.parallelStep(p.module_id, 1);
        if (!r || !r.ok) toast('No parallel resource.', 'warn');
      };
      const ed = el('button', '', '¶'); ed.title = 'Toggle reader’s edition (clean text)';
      ed.onclick = () => {
        const clean = !(p.options && p.options.show_notes === false);
        Workspace.edition(p.id, clean ? 'clean' : 'study');
      };
      const vf = el('button', '', 'F'); vf.title = 'Filters — highlight saved queries here (click for list)';
      vf.onclick = () => VisualFilters.dialog();
      vf.ondblclick = (e) => {
        e.stopPropagation();
        VisualFilters.on = !VisualFilters.on;
        toast('Filters ' + (VisualFilters.on ? 'on.' : 'off.'));
        if (S.layout) App.loadWorkspace();
      };
      tools.append(parP, parN, ed, vf);
      /* Multiple Book Display: optional parallel resource in this tab. */
      const parSel = el('select', '');
      parSel.title = 'Parallel resource in this tab (Multiple Book Display)';
      parSel.appendChild(new Option('Parallel: none', ''));
      (S.modules || []).filter(x => x.reader === 'verse' && x.id !== m.id)
        .forEach(x => parSel.appendChild(new Option(x.name || x.id, x.id)));
      parSel.value = (p.options && p.options.parallel) || '';
      parSel.onchange = async () => {
        p.options = p.options || {};
        p.options.parallel = parSel.value || '';
        await post('workspace/pane', { pane: p.id, options: p.options });
        if (S.layout) App.loadWorkspace();
      };
      tools.appendChild(parSel);
      /* Visual Copy: render the current verse as a shareable image. */
      const vis = el('button', '', 'Visual');
      vis.title = 'Visual copy — render this verse as an image';
      vis.onclick = async () => {
        try {
          const v = here();
          if (!v) { toast('No verse selected. Click a verse first.', 'warn'); return; }
          // Read only the selected verse (by its key), not the whole chapter.
          const r = await api('read', { id: m.id, cursor: { keys: [v.key] }, span: 'verse', context: 0 });
          if (!r.ok || !r.items || !r.items.length) { toast('Nothing to copy.', 'warn'); return; }
          const it = r.items[0];
          const ref = it.label || v.label || '';
          const text = (it.text || '').trim();
          if (!text) { toast('This verse has no text to render.', 'warn'); return; }
          const canvas = document.createElement('canvas');
          canvas.width = 1080; canvas.height = 540;
          const ctx = canvas.getContext('2d');
          if (!ctx) { toast('Cannot render image.', 'warn'); return; }
          // background
          const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
          grad.addColorStop(0, '#1e2a3a'); grad.addColorStop(1, '#0f1724');
          ctx.fillStyle = grad; ctx.fillRect(0, 0, canvas.width, canvas.height);
          // text
          ctx.fillStyle = '#f5f1e8';
          ctx.font = 'italic 34px Georgia, serif';
          ctx.textAlign = 'center';
          // wrap text
          const words = text.split(' ');
          const lines = []; let line = '';
          const maxW = canvas.width - 120;
          words.forEach(w => {
            const test = line ? line + ' ' + w : w;
            if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = w; }
            else line = test;
          });
          if (line) lines.push(line);
          const lineH = 46;
          const startY = (canvas.height - lines.length * lineH) / 2 - 10;
          lines.forEach((ln, i) => ctx.fillText(ln, canvas.width / 2, startY + i * lineH));
          // reference
          ctx.font = 'bold 22px Georgia, serif';
          ctx.fillStyle = '#c9a961';
          ctx.fillText(ref + (m.name ? '  ·  ' + m.name : ''), canvas.width / 2, startY + lines.length * lineH + 30);
          // download
          const done = (blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = (ref.replace(/[^a-z0-9]+/gi, '-') || 'verse') + '.png';
            document.body.appendChild(a); a.click(); a.remove();
            URL.revokeObjectURL(url);
            toast('Saved image.');
          };
          if (canvas.toBlob) { canvas.toBlob(done, 'image/png'); }
          else { done(canvas.msToBlob ? canvas.msToBlob() : null); }
        } catch (e) {
          toast('Visual copy failed: ' + (e && e.message ? e.message : String(e)), 'warn');
        }
      };
      tools.appendChild(vis);
      /* Pack 6: reading-plan ribbons — days covering this chapter. Guarded:
       * a ribbon failure must never break the reader. */
      try {
        const mref = (p.cursor && p.cursor.ref) || '';
        const mm = mref.match(/^(\d?\s?[A-Za-z]+)\s+(\d+)/);
        if (mm) {
          api('reading/ribbons', { book: mm[1].trim(), chapter: mm[2] })
            .then(r => {
              (r.ribbons || []).slice(0, 3).forEach(rb => {
                const tag = el('span', 'chip', '◈ ' + (rb.title || rb.plan)
                  + (rb.day ? ' · day ' + rb.day : ''));
                tag.title = 'Reading plan: ' + (rb.ref || '');
                tag.style.cursor = 'pointer';
                tag.onclick = () => { App.show('workspace'); };
                tools.appendChild(tag);
              });
            }).catch(() => {});
        }
      } catch (e) { /* ribbons are decorative */ }
    } else {
      const box = el('input', 'refbox'); box.style.width = '160px';
      box.placeholder = m.type === 'Devotional' ? '1.15' : (m.type === 'Map' ? 'place' : 'search…');
      box.value = p.cursor.key || p.cursor.date || '';
      box.onkeydown = (e) => { if (e.key === 'Enter') Reader.go(p, box.value); };
      tools.appendChild(box);
    }

    const ls = el('select', '');
    ls.appendChild(new Option('Link: none', ''));
    const sets = S.linkSets || ['A', 'B', 'C', 'D', 'E', 'F'];
    sets.forEach(L => ls.appendChild(new Option('Link ' + L, L)));
    ls.value = p.link_set || '';
    ls.onchange = async () => {
      await post('workspace/pane', { pane: p.id, link_set: ls.value });
      await App.loadWorkspace();
    };
    tools.appendChild(ls);

    const size = el('input', ''); size.type = 'range'; size.min = 70; size.max = 190;
    size.value = p.text_size || 100; size.style.width = '70px';
    size.title = 'Text size';
    size.onchange = async () => {
      await post('workspace/pane', { pane: p.id, text_size: size.value });
      body.style.fontSize = (size.value / 100) + 'em';
    };
    tools.appendChild(size);
    tools.appendChild(el('span', 'muted tiny',
      fmtBytes(m.size_bytes) + (m.has_strongs ? ' · Strong’s' : '') +
      (m.license ? ' · ' + m.license : '')));

    body.style.fontSize = ((p.text_size || 100) / 100) + 'em';
    if (m.has_strongs && m.reader === 'verse') {
      const t = el('button', '', 'Strongs');
      t.title = 'Show Strong’s numbers';
      t.onclick = () => { Reader.toggle(p, body, 'show_strongs', t); };
      tools.appendChild(t);
    }
    if (m.has_notes) {
      const t = el('button', 'on', 'Notes');
      t.onclick = () => { Reader.toggle(p, body, 'show_notes', t); };
      tools.appendChild(t);
    }
    if (m.has_redletter) {
      const t = el('button', 'on', 'WJ'); t.title = 'Words of Christ';
      t.onclick = () => { Reader.toggle(p, body, 'show_red', t); };
      tools.appendChild(t);
    }
    const h = el('button', 'on', 'Headings'); h.title = 'Headings';
    h.onclick = () => { Reader.toggle(p, body, 'show_headings', h); };
    tools.appendChild(h);
    const mem = el('button', '', 'Mem'); mem.title = 'Memorise this passage';
    mem.onclick = () => {
      const c = p._content;
      const text = (c && c.items) ? c.items.map(it => it.text || '').join('\n\n').trim() : '';
      if (!text) { toast('Nothing to memorise yet.', 'warn'); return; }
      Memorise.open(text, (c && c.section_title) || (m ? m.name : ''));
    };
    tools.appendChild(mem);
    const srs = el('button', '', 'SRS'); srs.title = 'Spaced repetition — add this passage';
    srs.onclick = async () => {
      const c = p._content;
      const ref = (c && c.ref_label) ? c.ref_label : ((p.cursor && p.cursor.ref) || '');
      if (!ref) { toast('No reference to add.', 'warn'); return; }
      const r = await api('srs/add', { ref: ref, id: m.id, key: (c && c.items && c.items[0] ? c.items[0].key : '') });
      toast(r.ok ? ('Added to SRS: ' + ref + (r.already ? ' (already there)' : '')) : (r.error || 'failed'));
    };
    tools.appendChild(srs);
    if (m.reader === 'verse') {
      const v = el('button', '', '1/line'); v.title = 'One verse per line';
      v.onclick = () => { Reader.toggle(p, body, 'verse_per_line', v); };
      tools.appendChild(v);
    }
      const more = el('button', '', '⋯'); more.title = 'Panel menu';
      more.onclick = () => PanelMenu(p, m, body);
      tools.appendChild(more);

      /* One click for everything installed that bears on this verse.
       *
       * The current verse is resolved when the button is *clicked*, not now.
       * It was read here from `r`, a variable that does not exist in this
       * function: the pane is built first and only then read, so there is no
       * result yet.  That threw "r is not defined" on every pane fill, which
       * aborted the rest of the toolbar -- so the Study, Compare and Interlinear
       * buttons had never once appeared in the reader, and the only way into
       * the study panel was right-click. */
      if (m.reader === 'verse') {
        // If the user has clicked a verse, remember it so buttons use that verse
        // instead of always the first one in the pane.
        p.selectedVerse = p.selectedVerse || null;
        const study = el('button', '', 'Study');
        study.title = 'Commentaries, cross-references, topics, places, words';
        study.onclick = () => { const v = here(); if (v) Study.openVerse(m.id, v.key, v.label); };
        tools.appendChild(study);
        const pg = el('button', '', 'Passage');
        pg.title = 'Passage for the open verse';
        pg.onclick = () => { const v = here(); if (v) Study.openPassage(v.label); };
        tools.appendChild(pg);
        const info = el('button', '', 'Info');
        info.title = 'Follow-pane card: text, people, places, library coverage';
        info.onclick = () => { const v = here(); if (v) InfoPane.open(v.label); };
        tools.appendChild(info);
        const cmp = el('button', '', 'Compare');
        cmp.title = 'The same verse in several translations';
        cmp.onclick = () => { const v = here(); if (v) Study.openCompare(v.label); };
        const mrg = el('button', 'btn tiny', 'Merge');
        mrg.title = 'Fuse several translations into one text, marking where they differ';
        mrg.onclick = () => { const v = here(); if (v) Study.openMerge(v.label); };
        cmp.after(mrg);
        tools.appendChild(cmp);
        // Interlinear needs a tagged resource; offer it when there is one.
        if (m.has_morph || m.has_strongs) {
          const il = el('button', '', 'Interlinear');
          il.title = 'Word by word: form, lemma, morphology, gloss';
          il.onclick = () => { const v = here(); if (v) Study.openInterlinear(m.id, v.key, v.label); };
          tools.appendChild(il);
          const ril = el('button', '', 'Rev. interlinear');
          ril.title = 'Reverse interlinear: English on top, original language beneath';
          ril.onclick = () => { const v = here(); if (v) Study.openReverseInterlinear(m.id, v.key, v.label); };
          tools.appendChild(ril);
        }
        // Copy the current chapter's verses to the clipboard, formatted.
        const cpy = el('button', '', 'Copy');
        cpy.title = 'Copy this chapter\'s verses to the clipboard';
        cpy.onclick = async () => {
          const v = here();
          if (!v) return;
          const parts = String(v.key || '').split('.');
          const book = parts[0] || '';
          const chapter = parseInt(parts[1] || '0', 10) || 0;
          const r = await api('bible/chapter', { id: m.id, book, chapter });
          if (!r.ok || !r.verses || !r.verses.length) { toast('Nothing to copy.', 'warn'); return; }
          const head = (m.name || m.id) + ' \u2014 ' + book + ' ' + chapter;
          const body = r.verses.map(x => (x.verse + '. ' + x.text)).join('\n');
          const text = head + '\n\n' + body;
          try {
            await navigator.clipboard.writeText(text);
            toast('Copied ' + r.verses.length + ' verses.');
          } catch (e) {
            toast('Could not reach the clipboard.', 'warn');
          }
        };
        tools.appendChild(cpy);
        // Read aloud, in a voice running on this machine.  Where it is not
        // installed Speech falls back to the browser's own engine.
        const say = el('button', '', '\u25B6\uFE0E');
        say.title = 'Read this chapter aloud';
        say.onclick = () => Speech.speak(p, say);
        tools.appendChild(say);
        // Right-click a word in the pane for the same menu.  Same rule as the
        // buttons above: the current verse is read at click time, so this used
        // the same two out-of-scope names and threw "key is not defined" the
        // first time anybody right-clicked a verse.
        body.oncontextmenu = (e) => {
          e.preventDefault();
          const sel = String(window.getSelection() || '').trim()
                      || S.lastSelection || '';
          const word = sel || (e.target.textContent || '').trim().slice(0, 40);

          /* Text nodes don't have .closest(), so step up to the parent
           * element first.  Also, closest() searches UP the tree, so it
           * finds the vnum link only when clicking ON it, not when clicking
           * on verse text.  Use querySelector to search DOWN into the verse
           * span for the verse number link instead. */
          const t = e.target.nodeType === Node.TEXT_NODE ? e.target.parentElement : e.target;
          const vnum = (t.matches && t.matches('a.vnum')) ? t : t.querySelector('a.vnum');
          const vspan = t.closest('.verse');
          const verseNo = (vnum ? vnum.textContent : '').trim()
                          || (vspan && vspan.previousElementSibling
                              ? vspan.previousElementSibling.textContent.trim() : '');
          let key = vnum ? vnum.dataset.k : '';
          if (!key && vspan) {
            const inner = vspan.querySelector('a.vnum[data-k]');
            key = inner ? inner.dataset.k : '';
          }
          /* Clicked in the gap between two verse spans, or in the margin: no
           * verse is under the pointer, and falling back to the pane's first
           * item filed the action against John 3:1 when the user had aimed at
           * John 3:16.  Take the verse whose box is nearest the click instead. */
          if (!key) {
            let best = null, bestD = Infinity;
            const spans = body.querySelectorAll('.verse');
            for (const sp of spans) {
              const r = sp.getBoundingClientRect();
              if (!r.height) continue;
              const d = (e.clientY < r.top) ? r.top - e.clientY
                        : (e.clientY > r.bottom ? e.clientY - r.bottom : 0);
              if (d < bestD) { bestD = d; best = sp; }
            }
            const inner = best && best.querySelector('a.vnum[data-k]');
            if (inner) key = inner.dataset.k;
          }
          const fb = here() || { key: p.cursor.ref, label: p.cursor.ref || '' };
          const c = p._content || {};
          // Construct the label from the clicked verse's key (OSIS: "Gen.3.6")
          // so it always matches the verse actually right-clicked, not the
          // chapter's first-verse label from c.ref_label.
          let label;
          if (key) {
            const parts = key.split('.');
            label = parts[0] + ' ' + parts[1] + ':' + parts[2];
          } else {
            label = c.ref_label || fb.label || '';
            if (verseNo && label && label.indexOf(':') < 0) label += ':' + verseNo;
          }
          Study.wordMenu(e.clientX, e.clientY, word, m,
                         key || fb.key, label || verseNo, sel);
        };
      }

    await Reader.render(p, m, body, tools);
  },
};

const RecommendedPrompt = {
  slides: [
    { title: 'Read side by side', kicker: 'WORKSPACE', body: 'Open a Bible beside a commentary, dictionary or another translation. Link panes together so related passages stay in step while you study.' },
    { title: 'Search beyond a verse', kicker: 'POWERFUL SEARCH', body: 'Search your installed library and narrow results with filters. Explore words and phrases across books instead of relying on one resource at a time.' },
    { title: 'Explore the original languages', kicker: 'WORD STUDY', body: 'Follow Strong’s numbers, consult lexica, explore morphology and use the concordance to see how a word appears in context.' },
    { title: 'See the bigger picture', kicker: 'GUIDES & MAPS', body: 'Use Passage, cross-references, timelines, Bible places, maps, genealogy and gospel harmony to connect people, places and events.' },
    { title: 'Keep your study together', kicker: 'PERSONAL TOOLS', body: 'Save notes, highlights and clips; organise passages; and build reading plans, word lists and memorisation practice.' },
    { title: 'Make it your own', kicker: 'OPTIONAL EXTRAS', body: 'Adjust the appearance, read passages aloud, import personal books and explore the optional AI assistant when you choose to configure it.' },
  ],
  slideIndex: 0,
  running: false,
  job: null,
  cancelRequested: false,
  maybeShow: async function() {
    const st = await api('recommended/status');
    if (!st || !st.ok || st.dismissed) return;
    if (st.total > 0 && st.installed >= st.total) {
      await post('recommended/dismiss', {});
      return;
    }
    this.show(st);
  },
  show: function(st) {
    this.running = false; this.job = null; this.cancelRequested = false; this.slideIndex = 0;
    modal('Install recommended modules?',
      '<div class="st-body" style="margin-bottom:10px">'
      + 'This looks like a fresh library. Install the recommended set of '
      + st.total + ' modules (Bibles, commentaries, maps, lexica and more)? '
      + 'This may take a while and needs network access.'
      + '</div>'
      + '<label class="tiny" style="display:block;margin-bottom:8px">'
      + '<input type="checkbox" id="rec-dismiss"> Do not show this again'
      + '</label><div id="rec-progress" class="tiny muted"></div>',
      [
        { label: 'Install recommended', cls: 'btn primary', close: false,
          fn: () => this.install() },
        { label: 'Skip', cls: 'btn', close: false, fn: () => this.skip() },
      ]);
  },
  renderSlide: function() {
    const body = document.getElementById('modal-body');
    if (!body) return;
    const slide = this.slides[this.slideIndex];
    const count = this.slideIndex + 1;
    body.innerHTML = '<div class="rec-slideshow" style="min-height:218px;display:flex;flex-direction:column;justify-content:center;text-align:center;padding:10px 8px 4px">'
      + '<div class="tiny muted" style="letter-spacing:.12em;font-weight:700;margin-bottom:10px">' + slide.kicker + '</div>'
      + '<h2 style="font-size:1.35rem;line-height:1.25;margin:0 0 12px">' + slide.title + '</h2>'
      + '<p style="max-width:440px;align-self:center;line-height:1.65;margin:0 auto 18px">' + slide.body + '</p>'
      + '<div style="display:flex;align-items:center;justify-content:center;gap:18px;margin-bottom:12px">'
      + '<button type="button" id="rec-prev" class="btn" aria-label="Previous feature" ' + (this.slideIndex === 0 ? 'disabled' : '') + '>&lt;</button>'
      + '<span class="tiny muted">Feature ' + count + ' of ' + this.slides.length + '</span>'
      + '<button type="button" id="rec-next" class="btn" aria-label="Next feature" ' + (this.slideIndex === this.slides.length - 1 ? 'disabled' : '') + '>&gt;</button>'
      + '</div></div>'
      + '<div style="margin:4px 0 8px" aria-label="Recommended installation progress">'
      + '<div style="height:5px;border-radius:99px;background:var(--line);overflow:hidden">'
      + '<div id="rec-progress-fill" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" style="height:100%;width:0%;border-radius:99px;background:var(--accent,var(--primary,#4f8b6a));transition:width .25s ease"></div>'
      + '</div><div id="rec-progress-percent" class="tiny muted" style="text-align:right;font-size:.68rem;margin-top:3px">0%</div></div>'
      + '<div id="rec-progress" class="tiny muted" style="border-top:1px solid var(--line);padding-top:8px;margin-top:4px;min-height:34px;font-size:.72rem;line-height:1.45">Preparing installation…</div>';
    document.getElementById('rec-prev').onclick = () => { if (this.slideIndex > 0) { this.slideIndex--; this.renderSlide(); this.updateProgress(); } };
    document.getElementById('rec-next').onclick = () => { if (this.slideIndex < this.slides.length - 1) { this.slideIndex++; this.renderSlide(); this.updateProgress(); } };
  },
  updateProgress: function(jobData) {
    const prog = document.getElementById('rec-progress');
    if (!prog) return;
    const j = jobData || this.lastJobData || {};
    this.lastJobData = j;
    const msg = j.message || 'Installing recommended modules…';
    const failures = j.failures || (j.result && j.result.failures) || [];
    const details = failures.slice(-3).map(f => `${f.repo}/${f.item}: ${f.error}`);
    const total = Math.max(0, Number(j.total) || 0);
    const done = Math.max(0, Number(j.done) || 0);
    const pct = total ? Math.max(0, Math.min(100, Math.round(done * 100 / total))) : 0;
    const fill = document.getElementById('rec-progress-fill');
    const percent = document.getElementById('rec-progress-percent');
    if (fill) { fill.style.width = pct + '%'; fill.setAttribute('aria-valuenow', String(pct)); }
    if (percent) percent.textContent = pct + '% (' + done + ' of ' + total + ')';
    prog.textContent = msg + (details.length ? ' · Latest failures: ' + details.join(' · ') : '');
    if (failures.length > 3) prog.textContent += ` · ${failures.length - 3} earlier failure(s) omitted`;
  },
  setInstallButton: function(disabled) {
    const btn = document.querySelectorAll('#modal-foot button')[0];
    if (btn) { btn.disabled = !!disabled; btn.style.opacity = disabled ? '.5' : ''; }
  },
  skip: async function() {
    if (!this.running || !this.job) {
      const cb = document.getElementById('rec-dismiss');
      if (cb && cb.checked) await post('recommended/dismiss', {});
      closeModal();
      return;
    }
    if (this.cancelRequested) return;
    this.cancelRequested = true;
    const buttons = document.querySelectorAll('#modal-foot button');
    if (buttons[1]) { buttons[1].disabled = true; buttons[1].textContent = 'Stopping…'; }
    const prog = document.getElementById('rec-progress');
    if (prog) prog.textContent = 'Stopping after the current item. The page will refresh with everything installed so far…';
    await post('recommended/cancel', { job: this.job });
    this.poll();
  },
  install: async function() {
    if (this.running) return;
    this.running = true;
    this.setInstallButton(true);
    const cb = document.getElementById('rec-dismiss');
    if (cb) cb.checked = true;
    this.renderSlide();
    const prog = document.getElementById('rec-progress');
    if (prog) prog.textContent = 'Starting installation…';
    const r = await post('recommended/install', {});
    if (!r || !r.ok) {
      this.running = false; this.setInstallButton(false);
      if (prog) prog.textContent = 'Could not start: ' + ((r && r.error) || 'unknown error');
      return;
    }
    this.job = r.job;
    this.poll();
  },
  poll: async function() {
    if (!this.job) return;
    const jr = await api('store/job', { job: this.job });
    const j = (jr && jr.job) || {};
    this.lastJobData = j;
    this.updateProgress(j);
    if (j.state === 'done' || j.state === 'cancelled') {
      this.running = false;
      if (j.state === 'done') await post('recommended/dismiss', {});
      // Refresh after either normal completion or Skip so the page reflects
      // exactly the resources that completed before the worker stopped.
      setTimeout(() => location.reload(), 900);
      return;
    }
    if (j.state === 'error') {
      this.running = false; this.setInstallButton(false);
      const prog = document.getElementById('rec-progress');
      if (prog) prog.textContent = 'Error: ' + (j.message || 'installation failed');
      return;
    }
    setTimeout(() => this.poll(), 1000);
  },
};