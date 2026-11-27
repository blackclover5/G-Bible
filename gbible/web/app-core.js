const App = {
  async boot() {
    // Wire the UI first.  bind() attaches every nav button, and it used to run
    // last -- after five sequential network round-trips -- so a single failed or
    // slow request left the page rendering but completely unresponsive, with no
    // error shown anywhere.  Interactive-but-empty beats dead.
    this.bind();
    try {
      const meta = document.querySelector('meta[name="gbible-version"]');
      const v = meta ? meta.content : '';
      const last = localStorage.getItem('gbible:last-version');
      if (v && v !== '__GBIBLE_VERSION__' && last && last !== v) {
        toast('Updated to ' + v + '. See About for release notes.', 'ok');
      }
      if (v) localStorage.setItem('gbible:last-version', v);
    } catch (e) {}
    /* The pill is the quickest honest answer to "did anything break?". */
    const pill = document.getElementById('status-errors');
    if (pill) {
      pill.onclick = () => { if (typeof Logs !== 'undefined') Logs.open(); else App.show('logs'); };
    }
    if (typeof refreshErrorPill === 'function') refreshErrorPill();
    Appearance.init();
    try {
      const st = await api('status');
      if (!st || st.ok === false) throw new Error((st && st.error) || 'Could not read status.');
      $('#status').innerHTML = st.total
        ? `${st.total} module${st.total === 1 ? '' : 's'} · ${esc(st.size_label)}`
        : 'no modules — visit the <b>Store</b>';
      // The AI Assistant is opt-in.  This is the one call that is allowed
      // before it is enabled; everything else is gated server-side too.
      try {
        const aiState = await api('ai/status');
        S.aiEnabled = !!(aiState && aiState.enabled);
      } catch (e) { S.aiEnabled = false; }
      applyAiGate();
      const tax = await api('taxonomy');
      if (!tax || tax.ok === false) throw new Error((tax && tax.error) || 'Could not read resource categories.');
      S.tax = tax; S.types = tax.types; S.subjects = tax.subjects; S.langs = tax.languages;
      if (!await this.loadLibrary()) throw new Error('Could not load the library.');
      // Tour runs first; the recommended-modules prompt only appears after
      // the tour complete(s) or is dismissed — they used to fire together.
      if (typeof Tour !== 'undefined') {
        Tour.maybeStart()
            .then(() => RecommendedPrompt.maybeShow().catch(() => {}))
            .catch(() => {});
      } else {
        RecommendedPrompt.maybeShow().catch(() => {});
      }
      if (!await this.loadWorkspace()) throw new Error('Could not load the workspace.');
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
      this.restoreNotice();
    } catch (err) {
      // Say so.  A dead UI with a silent console is the hardest kind of bug.
      const msg = (err && err.message) || String(err);
      $('#status').innerHTML = `<span style="color:#f0a0a5">could not load: ${esc(msg)}</span>`;
      console.error('gbible boot failed', err);
      toast('Could not reach the local server: ' + msg, 'err');
    }
  },

  /* A .gbz restore just applied and the page reloaded to pick everything up.
     Say what landed in a small banner instead of a dialog — modal() replaces
     whatever it holds, so a restore notice opened beside the guided tour or
     the recommended-modules prompt would simply erase it, or be erased.
     A dismissible banner coexists with both without a fight. */
  async restoreNotice() {
    let s = null;
    try { s = JSON.parse(sessionStorage.getItem('gbible:last-restore') || 'null'); } catch (e) { return; }
    if (!s) return;
    // Remove only after the banner is on screen; if rendering throws, the
    // notice stays and can be shown on the next load.
    const applied = Number(s.applied) || 0;
    const bits = [applied + ' record' + (applied === 1 ? '' : 's') + ' restored'];
    if (Number(s.existed)) bits.push(s.existed + ' already here');
    if (Number(s.conflict)) {
      const named = Array.isArray(s.conflicts) ? s.conflicts.slice(0, 3)
        .map(x => x.kind + ' ' + x.id).join(', ') : '';
      bits.push(s.conflict + ' kept yours'
        + (named ? ' (' + named + (Number(s.conflict) > 3 ? ', …' : '') + ')' : ''));
    }
    if (Number(s.deletes)) bits.push(s.deletes + ' deleted');
    if (Number(s.deletes_skipped)) {
      bits.push(s.deletes_skipped + ' deletes skipped (revision unknown)');
    }
    if (s.ai_keys_added || s.ai_keys_kept) {
      bits.push('AI keys: ' + (s.ai_keys_added || 0) + ' restored, '
        + (s.ai_keys_kept || 0) + ' already set');
    }
    const missing = Array.isArray(s.missing) ? s.missing : [];
    const notes = Array.isArray(s.notes) ? s.notes.filter(Boolean) : [];
    const errors = Array.isArray(s.errors) ? s.errors.filter(Boolean) : [];

    const bar = document.createElement('div');
    bar.style.cssText = 'position:fixed;bottom:22px;left:50%;transform:translateX(-50%);'
      + 'z-index:150;background:#1d2130;border:1px solid #3a4060;color:#e6e8f0;'
      + 'border-radius:10px;padding:10px 12px 10px 14px;max-width:80vw;'
      + 'box-shadow:0 10px 34px #000c;display:flex;gap:12px;align-items:flex-start;'
      + 'font-size:12.5px;line-height:1.45';
    const detail = [];
    detail.push('<div><b>Restore complete.</b><div class="tiny muted" style="margin-top:2px">'
      + esc(bits.join(' · ')) + '</div>');
    errors.forEach(x => detail.push('<div class="tiny" style="color:#f0a0a5">Not applied: ' + esc(x) + '</div>'));
    notes.forEach(x => detail.push('<div class="tiny muted">' + esc(x) + '</div>'));
    if (missing.length) {
      detail.push('<div class="tiny" style="color:var(--amber);margin-top:2px">Not installed yet: <b>'
        + esc(missing.join(', ')) + '</b> — those records stay unreadable until the matching modules are installed.</div>');
    }
    detail.push('</div>');
    bar.innerHTML = detail.join('');

    const right = document.createElement('div');
    right.style.cssText = 'display:flex;flex-direction:column;gap:6px;flex:none;align-items:flex-end';
    const closeBtn = document.createElement('button');
    closeBtn.className = 'btn tiny'; closeBtn.textContent = 'Dismiss';
    closeBtn.onclick = () => { try { bar.remove(); } catch (e) {} };
    right.appendChild(closeBtn);
    if (missing.length) {
      const openBtn = document.createElement('button');
      openBtn.className = 'btn tiny primary'; openBtn.textContent = 'Open Store';
      openBtn.onclick = () => { try { bar.remove(); } catch (e) {} App.show('store'); };
      right.appendChild(openBtn);
    }
    bar.appendChild(right);
    document.body.appendChild(bar);
    try { sessionStorage.removeItem('gbible:last-restore'); } catch (e) { /* harmless */ }
    // Let it stay as long as it needs; the reader closes it.
  },

  async loadLibrary() {
    const r = await api('library', { links: 1 });
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not load the library.', 'err');
      return false;
    }
    S.modules = r.modules || [];
    S.links = r.links || {};
    return true;
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
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not load the workspace.', 'err');
      return false;
    }
    S.layout = r.layout;
    S.arrangements = r.arrangements || {};
    S.guide = r.guide || {};
    S.linkSets = r.link_sets || ['A', 'B', 'C', 'D', 'E', 'F'];
    const sets = await api('workspace/linksets');
    if (!sets || sets.ok === false) {
      toast((sets && sets.error) || 'Could not load link sets.', 'err');
      return false;
    }
    S.linkGroups = sets.groups || {};
    this.renderWorkspace();
    /* Linked panes were saved with their own cursors; bring them into step so
     * a restored link set shows the same passage everywhere. */
    try { await Workspace.restoreLinks(); } catch (e) { /* never block a restore */ }
    return true;
  },

  show(v) {
    // The Assistant view does not exist until the reader enables it.  Send
    // anyone who reaches it another way (a saved view, a link) to the setup
    // card instead of an empty chat panel.
    if (v === 'ai' && aiOff()) v = 'aisettings';
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
      // Do not clobber a tab chosen just before calling show(): the Sermons
      // "edit" link sets it to the editor, then calls show() to open the view,
      // and used to be bounced straight back to the home tab.
      const smTab = $('#sm-tab');
      if (smTab && !['sermon-manager', 'sermons', 'sermon-editor'].includes(smTab.value))
        smTab.value = 'sermon-manager';
      SermonHub.load();
    }
    if (v === 'organise') { Organise.load(); }
    if (v === 'search') { Search.loadTemplates(); }
    if (v === 'wordlists') { WordLists.load(); }
    if (v === 'memorization') { Memorization.load(); }
    if (v === 'workflows') { Flows.load(); }
    if (v === 'sync') Sync.load();
    if (v === 'logs') Logs.load();
    if (v === 'plans') { Plans.load(); }
    if (v === 'devotions') { DevotionCreator.load(); }
    if (v === 'prayer') { Prayer.load(); }
    if (v === 'clippings') { Clippings.load(); }
    if (v === 'favorites') { Favorites.load(); }
    if (v === 'canvas') { Canvas.load(); }
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
    const kids = [], kept = [];
    (node.children || []).forEach((c, i) => {
      const pruned = this.removeTileLeaf(c, id);
      if (pruned) { kids.push(pruned); kept.push(i); }
    });
    if (!kids.length) return null;
    /* Keep each surviving child's own share: dropping a tile from a 3-column
     * group must not leave three ratios for two children, or the split that
     * follows snaps back to the wrong size. */
    if (node.ratios) node.ratios = kept.map(i => node.ratios[i] || 1);
    if (kids.length === 1) return kids[0];
    node.children = kids;
    return node;
  },

  /* Collapse layout slots left empty after a pane is closed or moved away.
   * removeTileLeaf folds a group down when only one child survives, so a
   * two-pane layout whose commentary is closed comes back as one pane.  When
   * every pane is gone we still keep a single empty tile so there is somewhere
   * for the "+" button to open a resource.  forceSave is used by a move whose
   * source tile is still occupied: the order/tile change must be persisted even
   * though there is no empty tile to prune. */
  async pruneEmptyTiles(opts) {
    const lay = S.layout;
    if (!lay || !lay.id) { this.renderWorkspace(); return false; }
    const panes = lay.panes || [];
    const tree = this.ensureTiles();
    const leaves = this.leafTileIds(tree);
    if (!leaves.length) { this.renderWorkspace(); return false; }
    const occupied = new Set(panes.map(p => this.tileKey(p.tile_id)));
    let next = tree, changed = false;
    if (!occupied.size) {
      next = { kind: 'tile', id: leaves[0] };
      changed = true;
    } else {
      leaves.forEach(t => {
        if (occupied.has(t)) return;
        const pruned = this.removeTileLeaf(next, t);
        if (pruned) { next = pruned; changed = true; }
      });
    }
    if (changed || (opts && opts.forceSave)) {
      lay.tiles = next;
      await this.saveCurrentTree();
    }
    this.renderWorkspace();
    return changed;
  },

  /* A short label for a pane's tab/move destination: its resource name, or the
   * kind of study pane when it has no resource. */
  paneLabel(p) {
    const m = modById(p.module_id);
    if (m) return m.name;
    if (p.view === 'guide') return 'Passage Guide';
    if (p.view === 'wordstudy') return 'Word Study';
    if (p.view === 'factbook') return 'Factbook';
    return 'Study pane';
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
    const remembered = this._activePane && this._activePane[tileId];
    const activeIdx = Math.max(0, list.findIndex(p => p.id === remembered));
    (list.length ? list : []).forEach((p, idx) => {
      const m = modById(p.module_id);
      const tabName = m ? m.name
        : (p.view === 'guide' ? 'Passage'
          : (p.view === 'wordstudy' ? 'Word Study' : '(closed)'));
      const tab = el('div', 'tile-tab' + (idx === activeIdx ? ' on' : ''));
      if (p.link_set) tab.appendChild(el('span', 'ls ' + p.link_set, p.link_set));
      tab.appendChild(el('span', 'modname', esc(tabName)));
      const x = el('span', 'x', '✕');
      x.onclick = (e) => { e.stopPropagation(); Workspace.closePane(p.id); };
      tab.appendChild(x);
      /* Right-click anywhere on the tab, not just its ✕, so a pane can be
       * moved to another layout slot without hunting for a tiny target. */
      tab.oncontextmenu = (e) => {
        e.preventDefault(); e.stopPropagation();
        const items = [
          { label: 'Add another pane beside', fn: () => Workspace.split(p.id, 'row') },
          { label: 'Split this pane below', fn: () => Workspace.split(p.id, 'column') },
        ];
        const others = App.leafTileIds(App.ensureTiles())
          .filter(t => t !== App.tileKey(p.tile_id));
        if (others.length) {
          items.push('-', { section: 'MOVE TO PANE' });
          others.forEach(t => {
            const there = (S.layout.panes || []).filter(x => App.tileKey(x.tile_id) === t);
            const label = there.length
              ? there.map(x => App.paneLabel(x)).join(', ')
              : 'Empty pane';
            items.push({ label: label + ' →', fn: () => Workspace.movePane(p.id, t) });
          });
          items.push('-');
        }
        items.push(
          { label: 'Float in new window', fn: () => Workspace.floatPane(p.id) },
          { label: 'Fullscreen reading', fn: () => Workspace.fullscreen(p.id) },
          { label: 'Copy location', fn: () => Workspace.copyLocation(p.id) },
          { label: 'Mark progress here', fn: () => Workspace.markHere(p.id) },
          { label: 'Close pane', fn: () => Workspace.closePane(p.id) },
        );
        Study.menu(e.clientX, e.clientY, items);
      };
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
        ev.preventDefault(); ev.stopPropagation();
        tab.classList.remove('dragover');
        const srcId = ev.dataTransfer.getData('text/plain');
        if (!srcId || srcId === p.id) return;
        /* Dropping onto a tab moves the pane into that tab's slot and makes it
         * the active tab there.  Dropping on empty tile space (handled below)
         * just files it in that slot. */
        Workspace.movePane(srcId, p.tile_id, p.id);
      });
      tab.onclick = (ev) => { if (ev.target.classList.contains('x')) return; this.showPane(tileId, p.id); };
      tabs.appendChild(tab);
    });
    const add = el('div', 'tile-tab', '<span style="color:var(--fg-3)">+</span>');
    add.onclick = () => Workspace.pickModule(tileId);
    /* The + tab is a .tile-tab too, so the tile-level drop handler skips it;
     * give it its own drop behaviour so dragging onto it files the pane here. */
    add.addEventListener('dragover', (ev) => {
      ev.preventDefault(); ev.dataTransfer.dropEffect = 'move';
      add.classList.add('dragover');
    });
    add.addEventListener('dragleave', () => add.classList.remove('dragover'));
    add.addEventListener('drop', (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      add.classList.remove('dragover');
      const srcId = ev.dataTransfer.getData('text/plain');
      if (srcId) Workspace.movePane(srcId, tileId);
    });
    tabs.appendChild(add);
    tile.appendChild(tabs);
    const active = list[0];
    const pane = el('div', 'pane');
    pane.dataset.pane = active ? active.id : '';
    tile.appendChild(pane);
    if (active) this.fillPane(pane, active);
    else pane.appendChild(el('div', 'empty', 'Open a resource with +'));
    /* The whole tile is a drop target, not just its tabs: a resource can now be
     * dragged straight into an empty slot (e.g. My Bible into the other pane of
     * a two-pane layout).  Tab drops are handled on the tab itself. */
    tile.addEventListener('dragover', (ev) => {
      if (ev.target.closest && ev.target.closest('.tile-tab')) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      tile.classList.add('tile-drop');
    });
    tile.addEventListener('dragleave', (ev) => {
      if (tile.contains(ev.relatedTarget)) return;
      tile.classList.remove('tile-drop');
    });
    tile.addEventListener('drop', (ev) => {
      if (ev.target.closest && ev.target.closest('.tile-tab')) return;
      ev.preventDefault(); ev.stopPropagation();
      tile.classList.remove('tile-drop');
      const srcId = ev.dataTransfer.getData('text/plain');
      if (srcId) Workspace.movePane(srcId, tileId);
    });
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
    let tile = document.querySelector('.tile[data-tile="' + tid + '"]');
    if (!tile) tile = $$('.tile').find(t => t.querySelector('.tile-tab'));
    if (!tile || !tile.querySelectorAll) return;
    const tabs = $$('.tile-tab', tile);
    tabs.forEach((t, k) => t.classList.toggle('on', k === idx));
    // Track focus on the model too: article/map links and Print use it.
    (S.layout.panes || []).forEach(x => { x.is_focus = x.id === panes[idx].id; });
    this._activePane = this._activePane || {};
    this._activePane[tid] = panes[idx].id;
    const pane = $('.pane', tile);
    if (pane) { pane.dataset.pane = panes[idx].id; this.fillPane(pane, panes[idx]); }
  },

  async fillPane(pane, p) {
    pane.innerHTML = '';
    const m = modById(p.module_id);
    const tools = el('div', 'pane-tools');
    const body = el('div', 'pane-body');
    pane.appendChild(tools); pane.appendChild(body);
    const modLabel = el('span', 'mod', esc(m ? m.name : (p.view === 'guide' ? 'Passage' : '(none)')));
    tools.appendChild(modLabel);
    /* Move this pane into another slot of the layout.  Added before the view
     * branches below so it is available on every kind of pane, including
     * Passage Guides and Word Study panes. */
    const movers = App.leafTileIds(App.ensureTiles())
      .filter(t => t !== App.tileKey(p.tile_id));
    if (movers.length) {
      const mv = el('select', 'move-pane');
      mv.title = 'Move this pane to another layout pane';
      mv.innerHTML = '<option value="">→ move to…</option>' + movers.map(t => {
        const there = (S.layout.panes || []).filter(x => App.tileKey(x.tile_id) === t);
        const label = there.length
          ? there.map(x => App.paneLabel(x)).join(', ')
          : 'Empty pane';
        return '<option value="' + esc(t) + '">' + esc(label) + '</option>';
      }).join('');
      mv.onchange = () => { if (mv.value) Workspace.movePane(p.id, mv.value); };
      tools.appendChild(mv);
    }
    /* Translation switcher: swap this pane's Bible for another installed one,
     * keeping the pane, its link set and its reading position. */
    if (m && m.is_bible) {
      const others = (S.modules || []).filter(x => x.is_bible && x.id !== m.id);
      if (others.length) {
        const sel = el('select', 'mod-switch');
        sel.title = 'Switch translation in this pane';
        sel.innerHTML = '<option value="">→ translation</option>'
          + others.map(b => '<option value="' + esc(b.id) + '">' + esc(b.name) + '</option>').join('');
        sel.onchange = async () => {
          if (!sel.value) return;
          await Workspace.switchModule(p.id, sel.value);
          sel.selectedIndex = 0;
        };
        tools.appendChild(sel);
      }
    }
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
      const gtype = (p.cursor && p.cursor.guide) || 'passage';
      refBox.onkeydown = async (e) => {
        if (e.key !== 'Enter') return;
        const ref = refBox.value.trim();
        if (!ref) return;
        p.cursor = Object.assign({}, p.cursor, { ref, guide: gtype });
        await Study.openGuidePane(gtype, ref, body);
        await Reader.saveNow(p);
      };
      tools.appendChild(refBox);
      const ref = (p.cursor && (p.cursor.ref || p.cursor.key)) || '';
      if (ref) Study.openGuidePane(gtype, ref, body);
      else body.innerHTML = '<div class="empty">Type a reference and press Enter.</div>';
      return;
    }
    if (p.view === 'wordstudy') {
      const numBox = el('input', 'refbox');
      numBox.value = (p.cursor && (p.cursor.number || p.cursor.strongs)) || '';
      numBox.placeholder = 'G2316 / H430';
      const render = async (num) => {
        body.innerHTML = '<div class="st-loading">Gathering…</div>';
        const r = await api('word-study', { num, limit: 30 });
        if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error || 'failed') + '</div>'; return; }
        p.cursor = p.cursor || {}; p.cursor.number = num;
        Reader.saveNow && Reader.saveNow(p);
        const s = r.sections || {};
        let h = '<div class="st-ref">' + esc(r.headword || num) + '</div>';
        if (r.gloss) h += '<div class="st-body"><b>' + esc(r.headword || num) + '</b> '
          + esc(r.lemma || '') + ' · ' + esc(r.gloss) + '</div>';
        /* Lemma — lexicon articles. */
        if (s.lemma && s.lemma.length) {
          h += '<div class="st-sec open"><div class="st-h">Lemma</div>'
            + s.lemma.map(x => '<div class="st-note"><div class="st-src">' + esc(x.module || '')
            + '</div><div class="st-body">' + esc(x.text || '') + '</div></div>').join('') + '</div>';
        }
        /* Translation — how each Bible renders this word. */
        if (s.translation && s.translation.length) {
          h += '<div class="st-sec"><div class="st-h">Translation</div>'
            + s.translation.map(t => '<div class="st-note"><div class="st-src">'
            + esc(t.module || '') + ' (' + t.count.toLocaleString() + '×)</div>'
            + '<div class="st-body">' + t.renderings.map(r => esc(r[0]) + ' ' + r[1].toLocaleString() + '×').join(' · ')
            + '</div></div>').join('') + '</div>';
        }
        /* Senses. */
        if (s.senses && s.senses.length) {
          h += '<div class="st-sec"><div class="st-h">Senses</div>'
            + s.senses.map(x => '<div class="st-note"><div class="st-body"><b>'
            + esc(x.sense || '') + '</b> ' + esc(x.definition || '') + '</div></div>').join('') + '</div>';
        }
        /* Example uses. */
        if (s.example_uses && s.example_uses.length) {
          h += '<div class="st-sec"><div class="st-h">Example Uses</div>'
            + s.example_uses.map(x => '<div class="st-note"><a href="#" data-ref="'
            + esc(x.ref) + '" class="pg-ref">' + esc(x.ref) + '</a> <span class="tiny muted">'
            + esc(x.surface || '') + '</span></div>').join('') + '</div>';
        }
        /* Clause participants. */
        if (s.clause_participants && s.clause_participants.length) {
          h += '<div class="st-sec"><div class="st-h">Clause Participants</div>'
            + s.clause_participants.map(x => '<span style="margin-right:8px">' + esc(x) + '</span>').join('') + '</div>';
        }
        /* Textual searches — where in each Bible. */
        if (s.textual_searches && s.textual_searches.length) {
          h += '<div class="st-sec"><div class="st-h">Textual Searches</div>'
            + s.textual_searches.map(t => '<div class="st-note"><div class="st-src">'
            + esc(t.module || '') + ' (' + t.count.toLocaleString() + ' hits)</div>'
            + '<div class="st-body">' + t.sample.map(s => '<a href="#" data-ref="'
            + esc(s.ref) + '" class="pg-ref">' + esc(s.ref) + '</a> ' + esc(s.surface || '')).join(' · ')
            + '</div></div>').join('') + '</div>';
        }
        body.innerHTML = h;
        body.querySelectorAll('.pg-ref').forEach(a => {
          a.onclick = (e) => { e.preventDefault(); const ref = a.dataset.ref;
            App.show('workspace'); const pane = (S.layout && S.layout.panes && S.layout.panes[0]);
            if (pane) Reader.go(pane, ref); };
        });
      };
      numBox.onkeydown = (e) => { if (e.key === 'Enter') { render(numBox.value); } };
      tools.appendChild(numBox);
      const n = (p.cursor && (p.cursor.number || p.cursor.strongs)) || '';
      if (n) render(n);
      else body.innerHTML = '<div class="empty">Type a Strong’s number and press Enter.</div>';
      return;
    }

    if (p.view === 'factbook') {
      const termBox = el('input', 'refbox');
      termBox.value = (p.cursor && p.cursor.term) || '';
      termBox.placeholder = 'Person, place, or topic';
      const render = async (term) => {
        body.innerHTML = '<div class="st-loading">Gathering…</div>';
        const r = await api('factbook', { q: term, per_section: 10 });
        if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error || 'failed') + '</div>'; return; }
        p.cursor = p.cursor || {}; p.cursor.term = term;
        Reader.saveNow && Reader.saveNow(p);
        let h = '<div class="st-ref">' + esc(term) + '</div>';
        const sections = r.sections || [];
        sections.forEach(sec => {
          const items = sec.items || [];
          if (!items.length) return;
          h += '<div class="st-sec open"><div class="st-h">' + esc(sec.label || sec.kind)
            + (sec.note ? ' <span class="tiny muted">' + esc(sec.note) + '</span>' : '')
            + '</div>';
          h += items.map(it => '<div class="st-note"><div class="st-src">'
            + esc(it.module || '') + '</div><div class="st-t">' + esc(it.title || it.key)
            + '</div><div class="st-body">' + esc(it.text || '') + '</div></div>').join('');
          h += '</div>';
        });
        if (!h || h === '<div class="st-ref">' + esc(term) + '</div>') {
          h += '<div class="empty">No fact-book entries found for "' + esc(term) + '".</div>';
        }
        body.innerHTML = h;
      };
      termBox.onkeydown = (e) => { if (e.key === 'Enter') { render(termBox.value); } };
      tools.appendChild(termBox);
      const t = (p.cursor && p.cursor.term) || '';
      if (t) render(t);
      else body.innerHTML = '<div class="empty">Type a person, place, or topic and press Enter.</div>';
      return;
    }

    /* -- reader-specific controls -- */
    /* One suite of controls for every reader: a Bible pane and a devotional
     * pane differ only in the picker (a calendar instead of books and
     * chapters); parallax stepping, edition toggle, filters, multiple display,
     * Visual, the study suite, copy and read-aloud behave the same on both.
     * `anchor()` is what the study suite reads: a verse on a Bible pane, the
     * day's first span on a devotional. */
    const anchor = () => {
      if (m.reader === 'verse') {
        const v = here();
        return v ? { key: v.key, label: v.label, source: m.id } : null;
      }
      if (m.reader === 'date') {
        const c = p._content || {};
        const it = (c.items || [])[0];
        const ex = (it && it.extra) || {};
        const spans = ex.spans || [];
        return {
          key: (ex.span_keys && ex.span_keys[0]) || '',
          label: spans[0] || (c.section_title || (it && it.title) || ''),
          source: ex.source_id || '',
          item: it,
        };
      }
      return null;
    };
    /* Parallel resources: Bibles cycle Bibles, devotionals cycle devotionals —
     * the server filters by type, so the same two buttons serve both. */
    const parP = el('button', '', '‹‖'); parP.title = 'Previous parallel resource';
    parP.onclick = async () => {
      const r = await Workspace.parallelStep(p.module_id, -1, '', p.id);
      if (!r || !r.ok) toast('No parallel resource.', 'warn');
    };
    const parN = el('button', '', '‖›'); parN.title = 'Next parallel resource';
    parN.onclick = async () => {
      const r = await Workspace.parallelStep(p.module_id, 1, '', p.id);
      if (!r || !r.ok) toast('No parallel resource.', 'warn');
    };
    const ed = el('button', '', '¶'); ed.title = 'Toggle reader’s edition (clean text)';
    ed.onclick = () => {
      const clean = !(p.options && p.options.show_notes === false);
      Workspace.edition(p.id, clean ? 'clean' : 'study');
    };
    const vf = el('button', '', 'F');
    vf.title = 'Filters — click for the list, double-click to turn highlighting on/off';
    let vfTimer = null;
    vf.onclick = (e) => {
      // A double-click fires two click events; waiting lets the dblclick
      // handler cancel the pending dialog instead of opening it twice.
      if (e.detail > 1) return;
      vfTimer = setTimeout(() => VisualFilters.dialog(), 220);
    };
    vf.ondblclick = (e) => {
      e.stopPropagation();
      clearTimeout(vfTimer);
      VisualFilters.on = !VisualFilters.on;
      try { localStorage.setItem('gbible:vf-on', VisualFilters.on ? '1' : '0'); }
      catch (err) { /* private browsing: the in-memory toggle still works */ }
      toast('Filters ' + (VisualFilters.on ? 'on.' : 'off.'));
      if (S.layout) App.loadWorkspace();
    };
    const vis = el('button', '', 'Visual');
    vis.title = m.reader === 'date'
      ? 'Visual copy — render this day as an image'
      : 'Visual copy — render this verse as an image';
    vis.onclick = async () => {
      try {
        const a = anchor();
        if (!a || !a.key) { toast('Nothing to copy.', 'warn'); return; }
        /* Read only the key the action needs — a verse on a Bible pane, an
         * entry on a devotional — not the whole chapter, and not the whole
         * devotion. */
        const r = await api('read', { id: m.id, cursor: { keys: [a.key] },
                                     span: 'verse', context: 0 });
        if (!r.ok || !r.items || !r.items.length) { toast('Nothing to copy.', 'warn'); return; }
        const it = r.items[0];
        const ref = it.title || it.label || a.label || '';
        let text = (it.text || '').trim();
        if (m.reader === 'date') {
          /* A whole devotion day does not fit on a card; its first sentence
           * does. The image is for sharing one line, not a full devotion. */
          const mt = /^[^.!?]*[.!?]/.exec(text);
          text = mt ? mt[0].trim() : text.slice(0, 220);
        }
        if (!text) { toast('Nothing to render.', 'warn'); return; }
        VisualCopy.save(ref, text, m.name);
      } catch (e) {
        toast('Visual copy failed: ' + (e && e.message ? e.message : String(e)), 'warn');
      }
    };
    /* Multiple Book Display: optional parallel resource in this tab. Both
     * reader kinds filter by their own; a devotional pane pairs with another
     * devotional. */
    const parSel = el('select', '');
    parSel.title = 'Parallel resource in this tab (Multiple Book Display)';
    parSel.appendChild(new Option('Parallel: none', ''));
    (S.modules || []).filter(x => x.reader === m.reader && x.id !== m.id)
      .forEach(x => parSel.appendChild(new Option(x.name || x.id, x.id)));
    parSel.value = (p.options && p.options.parallel) || '';
    parSel.onchange = async () => {
      p.options = p.options || {};
      p.options.parallel = parSel.value || '';
      await post('workspace/pane', { pane: p.id, options: p.options });
      if (S.layout) App.loadWorkspace();
    };
    const mkNavBtn = (label, title, fn) => { const b = el('button', '', label); b.title = title; b.onclick = fn; return b; };

    if (m.reader === 'verse') {
      const pickerWrap = el('div', 'ref-picker-wrap');
      const box = el('button', 'refbox ref-picker-trigger', 'Choose passage');
      box.type = 'button';
      box.setAttribute('aria-haspopup', 'dialog');
      box.setAttribute('aria-expanded', 'false');
      box.title = 'Choose a book and chapter';
      const picker = el('div', 'ref-picker-popover');
      picker.hidden = true;
      picker.setAttribute('role', 'dialog');
      picker.setAttribute('aria-label', 'Choose a Bible book and chapter');
      picker.innerHTML = '<div class="ref-picker-col"><div class="ref-picker-heading">Book</div>'
        + '<div class="ref-picker-books" role="listbox" aria-label="Books"></div></div>'
        + '<div class="ref-picker-col"><div class="ref-picker-heading">Chapter</div>'
        + '<div class="ref-picker-chapters" role="listbox" aria-label="Chapters"></div></div>';
      pickerWrap.append(box, picker);
      tools.appendChild(pickerWrap);

      let pickerBooks = [];
      let activeBook = null;
      let pickerCloseEvents = null;
      const closePicker = () => {
        picker.hidden = true;
        box.setAttribute('aria-expanded', 'false');
        if (pickerCloseEvents) {
          document.removeEventListener('pointerdown', pickerCloseEvents.outside, true);
          pickerCloseEvents = null;
        }
      };
      const currentParts = () => {
        const ref = String((p.cursor && p.cursor.ref) || '');
        const mt = ref.match(/^(.+?)\s+(\d+)(?::.*)?$/);
        return mt ? { book: mt[1], chapter: Number(mt[2]) } : { book: '', chapter: 0 };
      };
      const drawChapters = () => {
        const host = $('.ref-picker-chapters', picker);
        if (!host) return;
        host.innerHTML = '';
        if (!activeBook) {
          host.innerHTML = '<div class="ref-picker-empty">Select a book</div>';
          return;
        }
        const current = currentParts();
        const count = Number(activeBook.chapters || 0);
        for (let chapter = 1; chapter <= count; chapter++) {
          const b = el('button', 'ref-picker-choice ref-picker-chapter', String(chapter));
          b.type = 'button';
          b.setAttribute('role', 'option');
          b.setAttribute('aria-selected', String(current.book.toLowerCase() === activeBook.name.toLowerCase()
            && current.chapter === chapter));
          if (current.book.toLowerCase() === activeBook.name.toLowerCase()
              && current.chapter === chapter) b.classList.add('current');
          b.onclick = async (e) => {
            e.stopPropagation();
            const ref = activeBook.name + ' ' + chapter;
            closePicker();
            await Reader.go(p, ref);
          };
          host.appendChild(b);
        }
      };
      const drawBooks = () => {
        const host = $('.ref-picker-books', picker);
        if (!host) return;
        host.innerHTML = '';
        pickerBooks.forEach(book => {
          const b = el('button', 'ref-picker-choice ref-picker-book', book.name);
          b.type = 'button';
          b.setAttribute('role', 'option');
          b.setAttribute('aria-selected', String(activeBook && activeBook.osis === book.osis));
          if (activeBook && activeBook.osis === book.osis) b.classList.add('selected');
          b.onclick = (e) => {
            e.stopPropagation();
            activeBook = book;
            drawBooks();
            drawChapters();
          };
          host.appendChild(b);
        });
      };
      const loadPicker = async () => {
        const [canon, available] = await Promise.all([
          api('books', { scheme: m.v11n || 'KJV' }),
          api('library/outline', { id: m.id }),
        ]);
        if (!canon.ok || !available.ok) {
          toast('Could not load the book and chapter list.', 'warn');
          return false;
        }
        const inModule = new Map((available.books || []).map(b => [b.osis, b]));
        pickerBooks = (canon.books || []).filter(b => inModule.has(b.osis))
          .map(b => Object.assign({}, b, { chapters: inModule.get(b.osis).chapters }));
        const current = currentParts();
        activeBook = pickerBooks.find(b => [b.name, b.short, b.osis, ...(b.abbrevs || [])]
          .some(n => String(n || '').toLowerCase() === current.book.toLowerCase()))
          || pickerBooks[0] || null;
        drawBooks();
        drawChapters();
        return true;
      };
      box.onclick = async (e) => {
        e.stopPropagation();
        if (!picker.hidden) { closePicker(); return; }
        if (!await loadPicker()) return;
        picker.hidden = false;
        box.setAttribute('aria-expanded', 'true');
        pickerCloseEvents = {
          outside: (ev) => { if (!pickerWrap.contains(ev.target)) closePicker(); },
        };
        document.addEventListener('pointerdown', pickerCloseEvents.outside, true);
      };
      const prev = el('button', '', '◀'); prev.title = 'Previous book';
      prev.onclick = () => Reader.step(p, 'prevbook');
      const next = el('button', '', '▶'); next.title = 'Next book';
      next.onclick = () => Reader.step(p, 'nextbook');
      const pc = el('button', '', '❮'); pc.title = 'Previous chapter';
      pc.onclick = () => Reader.step(p, 'prevchapter');
      const nc = el('button', '', '❯'); nc.title = 'Next chapter';
      nc.onclick = () => Reader.step(p, 'nextchapter');
      tools.append(prev, pc, pickerWrap, nc, next);
    } else if (m.reader === 'date') {
      /* Same shape as a Bible pane, with a month calendar in place of the
       * book-and-chapter picker. ◀ ❮ [date] ❯ ▶ — the two pairs both step a
       * day, exactly as book/chapter step a verse pane. */
      const parseKey = (s) => {
        const mm = /^(\d{1,2})\.(\d{1,2})/.exec(String(s || ''));
        const now = new Date();
        return mm ? new Date(now.getFullYear(), Number(mm[1]) - 1, Number(mm[2]))
                  : new Date(now);
      };
      const pad = (n) => String(n).padStart(2, '0');
      const mmdd = (d) => pad(d.getMonth() + 1) + '.' + pad(d.getDate());
      const longDate = (d) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
      const cur = parseKey(p.cursor && (p.cursor.date || p.cursor.key));
      const pickerWrap = el('div', 'ref-picker-wrap');
      const box = el('button', 'refbox ref-picker-trigger', longDate(cur));
      box.type = 'button';
      box.setAttribute('aria-haspopup', 'dialog');
      box.setAttribute('aria-expanded', 'false');
      box.title = 'Choose a date';
      box.setAttribute('aria-label', 'Current date');
      const picker = el('div', 'ref-picker-popover');
      picker.hidden = true;
      picker.setAttribute('role', 'dialog');
      picker.setAttribute('aria-label', 'Choose a date');
      picker.innerHTML = '<div class="ref-picker-col" style="min-width:250px">'
        + '<div class="ref-picker-heading cal-head">'
        + '<button class="btn tiny" id="pcal-prev" type="button" title="Previous month">‹</button>'
        + '<span class="dp-controls">'
        + '<select class="dp-month" id="pcal-monthsel" aria-label="Month"></select>'
        + '<select class="dp-year" id="pcal-yearsel" aria-label="Year"></select>'
        + '</span>'
        + '<button class="btn tiny" id="pcal-next" type="button" title="Next month">›</button>'
        + '</div>'
        + '<div class="pcal-grid" id="pcal-days"></div>'
        + '<div class="ref-picker-chapters" style="padding:4px">'
        + '<button class="ref-picker-choice ref-picker-chapter" id="pcal-today" type="button">Today</button>'
        + '</div></div>';
      pickerWrap.append(box, picker);
      tools.appendChild(pickerWrap);
      let pickerView = new Date(cur.getFullYear(), cur.getMonth(), 1);
      let pickerCloseEvents = null;
      const closePicker = () => {
        picker.hidden = true;
        box.setAttribute('aria-expanded', 'false');
        if (pickerCloseEvents) {
          document.removeEventListener('pointerdown', pickerCloseEvents.outside, true);
          pickerCloseEvents = null;
        }
      };
      const monthSel = $('#pcal-monthsel', picker);
      const yearSel = $('#pcal-yearsel', picker);
      ['January', 'February', 'March', 'April', 'May', 'June', 'July',
       'August', 'September', 'October', 'November', 'December']
        .forEach((name, i) => {
          const o = el('option', '', name); o.value = String(i); monthSel.appendChild(o);
        });
      const y0 = new Date().getFullYear();
      for (let y = y0 - 30; y <= y0 + 30; y++) {
        const o = el('option', '', String(y)); o.value = String(y); yearSel.appendChild(o);
      }
      const drawCalendar = () => {
        const host = $('#pcal-days', picker);
        monthSel.value = String(pickerView.getMonth());
        yearSel.value = String(pickerView.getFullYear());
        host.innerHTML = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
          .map(d => '<div class="pcal-dow">' + d + '</div>').join('');
        const first = new Date(pickerView.getFullYear(), pickerView.getMonth(), 1).getDay();
        const dim = new Date(pickerView.getFullYear(), pickerView.getMonth() + 1, 0).getDate();
        for (let b = 0; b < first; b++) host.appendChild(el('span', 'pcal-blank'));
        for (let d = 1; d <= dim; d++) {
          const b = el('button', 'pcal-day', String(d));
          b.type = 'button';
          if (cur.getFullYear() === pickerView.getFullYear()
              && cur.getMonth() === pickerView.getMonth() && cur.getDate() === d) {
            b.classList.add('current');
          }
          b.onclick = (e) => {
            e.stopPropagation();
            const chosen = new Date(pickerView.getFullYear(), pickerView.getMonth(), d);
            closePicker();
            Reader.go(p, mmdd(chosen));
          };
          host.appendChild(b);
        }
      };
      box.onclick = (e) => {
        e.stopPropagation();
        if (!picker.hidden) { closePicker(); return; }
        drawCalendar();
        picker.hidden = false;
        box.setAttribute('aria-expanded', 'true');
        pickerCloseEvents = {
          outside: (ev) => { if (!pickerWrap.contains(ev.target)) closePicker(); },
        };
        document.addEventListener('pointerdown', pickerCloseEvents.outside, true);
      };
      $('#pcal-prev', picker).onclick = (e) => {
        e.stopPropagation();
        pickerView = new Date(pickerView.getFullYear(), pickerView.getMonth() - 1, 1);
        drawCalendar();
      };
      $('#pcal-next', picker).onclick = (e) => {
        e.stopPropagation();
        pickerView = new Date(pickerView.getFullYear(), pickerView.getMonth() + 1, 1);
        drawCalendar();
      };
      monthSel.onchange = () => {
        pickerView = new Date(pickerView.getFullYear(), Number(monthSel.value), 1);
        drawCalendar();
      };
      yearSel.onchange = () => {
        pickerView = new Date(Number(yearSel.value), pickerView.getMonth(), 1);
        drawCalendar();
      };
      $('#pcal-today', picker).onclick = (e) => {
        e.stopPropagation();
        closePicker();
        Reader.go(p, mmdd(new Date()));
      };
      const step = (days) => {
        const s = String((p.cursor && (p.cursor.date || p.cursor.key)) || '');
        const mm = /^(\d{1,2})\.(\d{1,2})/.exec(s);
        const now = new Date();
        const d = mm ? new Date(now.getFullYear(), Number(mm[1]) - 1, Number(mm[2]))
                     : new Date(now);
        d.setDate(d.getDate() + days);
        Reader.go(p, mmdd(d));
      };
      const prev = mkNavBtn('◀', 'Previous day', () => step(-1));
      const next = mkNavBtn('▶', 'Next day', () => step(1));
      const pc = mkNavBtn('❮', 'Previous day', () => step(-1));
      const nc = mkNavBtn('❯', 'Next day', () => step(1));
      tools.append(prev, pc, pickerWrap, nc, next);
    } else {
      /* A map or a search-backed resource: this box takes a place name or a
       * headword, and the person typing knows which. */
      const box = el('input', 'refbox'); box.style.width = '160px';
      box.placeholder = m.type === 'Map' ? 'place' : 'search…';
      box.value = p.cursor.key || p.cursor.date || '';
      box.onkeydown = (e) => { if (e.key === 'Enter') Reader.go(p, box.value); };
      tools.appendChild(box);
    }
    tools.append(parP, parN, ed, vf);
    tools.appendChild(parSel);
    tools.appendChild(vis);
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

    // Find within this pane.  Ctrl+F while reading uses this rather than the
    // library search, so looking up a word does not leave the passage.
    if (typeof PaneFind !== 'undefined') PaneFind.attach(pane, body, tools);

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
      const t = el('button', (p.options && p.options.show_notes === false) ? '' : 'on', 'Notes');
      t.onclick = () => { Reader.toggle(p, body, 'show_notes', t); };
      tools.appendChild(t);
    }
    if (m.reader === 'verse') {
      const t = el('button', (p.options && p.options.show_red === false) ? '' : 'on', 'WJ'); t.title = 'Words of Christ (red, where the Bible tags them)';
      t.onclick = () => { Reader.toggle(p, body, 'show_red', t); };
      tools.appendChild(t);
    }
    const h = el('button', (p.options && p.options.show_headings === false) ? '' : 'on', 'Headings'); h.title = 'Headings';
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
      const ref = (c && c.section_title) ? c.section_title
        : ((c && c.ref_label) ? c.ref_label : ((p.cursor && p.cursor.ref) || ''));
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

      /* One click for everything installed that bears on this passage.
       * Each button resolves the passage at click time (see `v` below), so it
       * follows the verse the reader last selected rather than a stale verse
       * captured while the toolbar was still being built. */
      if (m.reader === 'verse' || m.reader === 'date') {
        // Resolve the passage when a button is clicked, not when the toolbar
        // is built.  Capturing it here gave every button the chapter's first
        // verse, because the reader resets the selection on each repaint.
        const v = () => anchor();
        // If the user has clicked a verse, remember it so buttons use that verse
        // instead of always the first one in the pane.
        p.selectedVerse = p.selectedVerse || null;
        const study = el('button', '', 'Study');
        study.title = 'Commentaries, cross-references, topics, places, words';
        study.onclick = () => { const a = v(); if (a) Study.openVerse(a.source, a.key, a.label); };
        tools.appendChild(study);
        const pg = el('button', '', 'Passage');
        pg.title = 'Passage for the open verse';
        pg.onclick = () => { const a = v(); if (a) Study.openPassage(a.label); };
        tools.appendChild(pg);
        const info = el('button', '', 'Info');
        info.title = 'Follow-pane card: text, people, places, library coverage';
        info.onclick = () => { const a = v(); if (a) InfoPane.open(a.label); };
        tools.appendChild(info);
        const cmp = el('button', '', 'Compare');
        cmp.title = 'The same passage in several translations';
        cmp.onclick = () => { const a = v(); if (a) Study.openCompare(a.label); };
        const mrg = el('button', 'btn tiny', 'Merge');
        mrg.title = 'Fuse several translations into one text, marking where they differ';
        mrg.onclick = () => { const a = v(); if (a) Study.openMerge(a.label); };
        tools.append(cmp, mrg);
        // Interlinear needs a tagged resource; offer it when there is one.
        if (m.has_morph || m.has_strongs) {
          const il = el('button', '', 'Interlinear');
          il.title = 'Word by word: form, lemma, morphology, gloss';
          il.onclick = () => { const a = v(); if (a) Study.openInterlinear(a.source, a.key, a.label); };
          tools.appendChild(il);
          const ril = el('button', '', 'Rev. interlinear');
          ril.title = 'Reverse interlinear: English on top, original language beneath';
          ril.onclick = () => { const a = v(); if (a) Study.openReverseInterlinear(a.source, a.key, a.label); };
          tools.appendChild(ril);
        }
        // Copy the passage to the clipboard, formatted.
        const cpy = el('button', '', 'Copy');
        cpy.title = m.reader === 'date' ? 'Copy this entry to the clipboard'
                                        : 'Copy this chapter\'s verses to the clipboard';
        cpy.onclick = async () => {
          if (m.reader === 'date') {
            const head = (m.name || m.id)
              + ((p._content && p._content.section_title) ? ' — ' + p._content.section_title : '');
            const text = (p._content && p._content.items ? p._content.items : [])
              .map(it => it.text || '').filter(Boolean).join('\n\n');
            try {
              await navigator.clipboard.writeText(head + '\n\n' + text);
              toast('Copied this entry.');
            } catch (e) {
              toast('Could not reach the clipboard.', 'warn');
            }
            return;
          }
          const a = v();
          if (!a) return;
          const parts = String(a.key || '').split('.');
          const book = parts[0] || '';
          const chapter = parseInt(parts[1] || '0', 10) || 0;
          const r = await api('bible/chapter', { id: m.id, book, chapter });
          if (!r.ok || !r.verses || !r.verses.length) { toast('Nothing to copy.', 'warn'); return; }
          const head = (m.name || m.id) + ' — ' + book + ' ' + chapter;
          const body2 = r.verses.map(x => (x.verse + '. ' + x.text)).join('\n');
          try {
            await navigator.clipboard.writeText(head + '\n\n' + body2);
            toast('Copied ' + r.verses.length + ' verses.');
          } catch (e) {
            toast('Could not reach the clipboard.', 'warn');
          }
        };
        tools.appendChild(cpy);
        // Read aloud, in a voice running on this machine. Where it is not
        // installed Speech falls back to the browser's own engine.
        const say = el('button', '', '\u25B6\uFE0E');
        say.title = 'Read this aloud';
        say.onclick = () => Speech.speak(p, say);
        tools.appendChild(say);
        // Right-click a word in the pane for the same menu.  Same rule as the
        // buttons above: the current verse is read at click time, so this used
        // the same two out-of-scope names and threw "key is not defined" the
        // first time anybody right-clicked a verse.  Verse-anchored only — a
        // devotional has no verse spans for the pointer to land on.
        if (m.reader !== 'verse') body.oncontextmenu = null;
        else
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
          // Prefer the user's actual text selection. Otherwise use the
          // complete text of the verse under the pointer.
          const targetKey = key || fb.key;
          const targetVerse = (c.items || []).find(it => it.key === targetKey);
          const highlightText = sel || (targetVerse && targetVerse.text) || '';

          Study.wordMenu(e.clientX, e.clientY, word, m,
                         targetKey, label || verseNo, highlightText);
        };
      }

    await Reader.render(p, m, body, tools);
  },
};

/* ============================================================== Reader */

const RecommendedPrompt = {
  slides: [
    { title: 'Read side by side', kicker: 'WORKSPACE', body: 'Open a Bible beside a commentary, dictionary or another translation. Link panes together so related passages stay in step while you study.' },
    { title: 'Search beyond a verse', kicker: 'POWERFUL SEARCH', body: 'Search your installed library and narrow results with filters. Explore words and phrases across books instead of relying on one resource at a time.' },
    { title: 'Explore the original languages', kicker: 'WORD STUDY', body: 'Follow Strong’s numbers, consult lexica, explore morphology and use the concordance to see how a word appears in context.' },
    { title: 'See the bigger picture', kicker: 'GUIDES & MAPS', body: 'Use Passage, cross-references, timelines, Bible places, maps, genealogy and gospel harmony to connect people, places and events.' },
    { title: 'Keep your study together', kicker: 'PERSONAL TOOLS', body: 'Save notes, highlights and clips; organise passages; and build reading plans, word lists and memorisation practice.' },
    { title: 'Make it your own', kicker: 'OPTIONAL EXTRAS', body: 'Adjust the appearance, read passages aloud, import personal books, check for updates, and enable the optional AI assistant in Settings when you want it.' },
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
          hidePrint: true,
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
    this.dismissAfterInstall = !!(cb && cb.checked);
    this.renderSlide();
    const prog = document.getElementById('rec-progress');
    if (prog) prog.textContent = 'Starting installation…';
    const r = await post('recommended/install', {
      dismiss: this.dismissAfterInstall ? 1 : 0
    });
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
    if (!jr || !jr.ok || !jr.job) {
      this.running = false;
      this.setInstallButton(false);
      const prog = document.getElementById('rec-progress');
      if (prog) prog.textContent =
        'Could not check installation progress: ' +
        ((jr && jr.error) || 'server did not return the job');
      return;
    }

    const j = jr.job;
    this.lastJobData = j;
    this.updateProgress(j);

    if (j.state === 'done' || j.state === 'cancelled') {
      this.running = false;

      const result = j.result || {};
      const failed = Number(result.failed || (j.failures || []).length || 0);

      if (failed > 0) {
        this.job = null;
        this.setInstallButton(false);
        const btn = document.querySelectorAll('#modal-foot button')[0];
        if (btn) btn.textContent = 'Retry installation';

        const prog = document.getElementById('rec-progress');
        if (prog) {
          prog.textContent =
            `${failed} module(s) failed. Your successful installations are preserved. ` +
            'You can retry; already-installed modules will be skipped. ' +
            ((j.failures || []).slice(0, 3).map(f =>
              `${f.repo}/${f.item}: ${f.error}`).join(' · '));
        }
        return;
      }

      // Refresh the library after successful completion or cancellation.
      // The backend dismisses the prompt only if the checkbox was selected.
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
