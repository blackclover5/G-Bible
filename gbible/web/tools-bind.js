/* Ctrl/⌘+K: one searchable list of every view and tool the app already has.
 * View commands go straight through App.show; tool commands click the button
 * that owns the action, so its handler is not duplicated here. */
const CommandPalette = {
  commands() {
    const out = [];
    $$('#nav button[data-view]').forEach(b => {
      const label = (b.textContent || '').trim();
      if (label) out.push({ label, group: 'Go to', run: () => App.show(b.dataset.view) });
    });
    $$('#nav .menu-pop button').forEach(b => {
      const label = (b.textContent || '').trim();
      if (!label || b.dataset.view) return;   // views are already in "Go to"
      const host = b.closest('.menu-pop');
      const trigger = host && host.parentElement && host.parentElement.querySelector('.menu-btn');
      const group = (trigger && trigger.textContent || 'Tools').trim();
      out.push({ label, group, run: () => b.click() });
    });
    return out;
  },
  open() {
    const all = this.commands();
    let shown = all.slice();
    let idx = 0;
    modal('Command palette',
      '<input type="search" id="cmd-q" placeholder="Type a command…" style="width:100%">'
      + '<div id="cmd-list" style="margin-top:8px;max-height:50vh;overflow:auto"></div>',
      [{ label: 'Close', cls: 'btn' }]);
    const list = $('#cmd-list');
    const paint = () => {
      const term = (($('#cmd-q').value || '') + '').trim().toLowerCase();
      shown = all.filter(c => (c.label + ' ' + c.group).toLowerCase().includes(term)).slice(0, 60);
      if (idx >= shown.length) idx = 0;
      list.innerHTML = shown.map((c, i) =>
        '<button class="btn" data-cmd="' + i + '" style="display:block;width:100%;'
        + 'text-align:left;margin-bottom:3px' + (i === idx
          ? ';outline:2px solid var(--accent)' : '') + '">'
        + '<span class="tiny muted">' + esc(c.group) + ' · </span>' + esc(c.label) + '</button>').join('')
        || '<div class="empty">No commands match.</div>';
      list.querySelectorAll('[data-cmd]').forEach(b => {
        b.onmouseenter = () => { idx = +b.dataset.cmd; };
        b.onclick = () => {
          idx = +b.dataset.cmd;
          const c = shown[idx];
          closeModal(); if (c) c.run();
        };
      });
      const active = list.children[idx];
      if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
    };
    $('#cmd-q').oninput = paint;
    $('#cmd-q').onkeydown = (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(shown.length - 1, idx + 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(0, idx - 1); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); const c = shown[idx]; if (c) { closeModal(); c.run(); } }
    };
    paint();
  },
};

App.bind = function () {
  $('#top-export').onclick = () => Export.dialog();
  $('#ws-printpane').onclick = () => Export.open('pane');

  /* Memorization controls are bound here, not in Memorization.load(): that
   * load awaits two requests, and a click during them used to do nothing. */
  const addMemCard = async () => {
    const input = $('#mem-ref');
    const ref = (input && input.value || '').trim();
    if (!ref) { toast('Type a reference first.', 'warn'); return; }
    // Resolve the reference so the card can carry a module and unit key;
    // without them the review screen has no verse text to show.
    let cursor = {};
    const parsed = await api('reference', { ref });
    const bible = S.modules.find(m => m.is_bible && m.reader === 'verse')
      || S.modules.find(m => m.is_bible);
    if (parsed && parsed.ok && bible) {
      cursor = { module_id: bible.id, unit_key: parsed.key };
    }
    const r = await api('srs/add', Object.assign({ ref }, cursor));
    if (r && r.ok) {
      toast(r.already ? 'Already a card.' : 'Card added.', r.already ? 'warn' : '');
      if (input) input.value = '';
      Memorization.load();
    } else toast((r && r.error) || 'Could not add.', 'err');
  };
  const memAdd = $('#mem-add'); if (memAdd) memAdd.onclick = addMemCard;
  const memRef = $('#mem-ref');
  if (memRef) memRef.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); addMemCard(); }
  };
  const memReview = $('#mem-review');
  if (memReview) memReview.onclick = () => SRS.open();
  $$('#nav button[data-view]').forEach(b => b.onclick = () => { App.show(b.dataset.view);
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    $$('#nav .menu-btn').forEach(x => x.setAttribute('aria-expanded', 'false'));
  });
  $$('#nav .menu-btn').forEach(b => b.onclick = (ev) => {
    ev.stopPropagation();
    const panel = $('#menu-' + b.dataset.menu);
    const open = panel && !panel.classList.contains('open');
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    $$('#nav .menu-btn').forEach(x => x.setAttribute('aria-expanded', 'false'));
    if (panel && open) { panel.classList.add('open'); b.setAttribute('aria-expanded', 'true'); }
  });
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('#nav .nav-menu') || ev.target.closest('#nav .menu-pop button')) {
      $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
      $$('#nav .menu-btn').forEach(x => x.setAttribute('aria-expanded', 'false'));
    }
    /* Clicking anywhere outside a verse span deselects the selected verse.
     * If the click lands on a verse span or its verse number, leave the
     * selection as-is so the reader can keep working with that verse. */
    if (!ev.target.closest('.verse')) {
      (S.layout && S.layout.panes || []).forEach(p => {
        if (p.selectedVerse) { p.selectedVerse = null; }
      });
      $$('.verse.selected').forEach(x => x.classList.remove('selected'));
    }
  });
  $('#menu-appearance').onclick = async () => {
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    await Appearance.show();
  };
  $('#menu-ra-settings').onclick = async () => {
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    await Speech.showSettings();
  };
  const pgBtn = $('#menu-passage-guide');
  if (pgBtn) pgBtn.onclick = async () => {
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    // Use the first pane's reference if available
    const p = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null;
    const ref = p && p.cursor && (p.cursor.ref || p.cursor.key);
    if (ref) Study.configureGuide();
    else toast('Open a passage first.', 'warn');
  };
  const aboutBtn = $('#menu-about');
  if (aboutBtn) aboutBtn.onclick = () => {
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    About.show();
  };
  document.addEventListener('keydown', (e) => {
    // The palette works even while typing in another field.
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault(); CommandPalette.open(); return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      e.preventDefault();
      // Reading a chapter? Find on that page rather than jumping to the
      // library search.  Panes without a find box fall back to global search.
      const paneEl = e.target && e.target.closest ? e.target.closest('.pane') : null;
      if (paneEl && typeof PaneFind !== 'undefined' && PaneFind.focus(paneEl)) return;
      App.show('search');
      setTimeout(() => { const q = $('#sq'); if (q) { q.focus(); q.select(); } }, 50);
      return;
    }
    if (e.key === 'Escape') {
      const modalUp = $('#modal-bg') && $('#modal-bg').classList.contains('on');
      if (modalUp) { closeModal(); Popup.hide(); e.preventDefault(); }
      /* $() returns a truthy safe-null proxy when nothing matches, so a plain
       * `if ($(...))` would run this block on every Escape.  Ask the document
       * directly to get a real null when no menu is open. */
      const openMenu = document.querySelector('#nav .menu-pop.open');
      if (openMenu) {
        const trigger = openMenu.parentElement && openMenu.parentElement.querySelector('.menu-btn');
        $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
        $$('#nav .menu-btn').forEach(x => x.setAttribute('aria-expanded', 'false'));
        if (trigger) trigger.focus({ preventScroll: true });
        e.preventDefault();
      }
    }
    if (e.key === '?' && !(e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'))) {
      e.preventDefault();
      Shortcuts.show();
    }
  });

  $('#sq').onkeydown = (e) => { if (e.key === 'Enter') Search.go(); };
  $('#sq').oninput = debounce(() => Search.suggestNow().catch(() => {}), 260);
  $('#s-go').onclick = () => Search.go();
  $('#s-case').onclick = (e) => { S.search.opts.match_case = !S.search.opts.match_case;
    e.target.classList.toggle('on', S.search.opts.match_case); Search.go(); };
  $('#s-forms').onclick = (e) => { S.search.opts.match_all_forms = !S.search.opts.match_all_forms;
    e.target.classList.toggle('on', S.search.opts.match_all_forms); Search.go(); };
  const inf = $('#s-inferred');
  if (inf) {
    inf.classList.toggle('on', !!S.search.opts.include_resolved);
    inf.onclick = (e) => {
      S.search.opts.include_resolved = !S.search.opts.include_resolved;
      e.target.classList.toggle('on', !!S.search.opts.include_resolved);
      Search.go();
    };
  }
  $('#s-ctx').onclick = (e) => { S.search.opts.context = S.search.opts.context ? 0 : 2;
    e.target.classList.toggle('on', !!S.search.opts.context); Search.go(); };
  $('#s-sort').onchange = (e) => { S.search.opts.sort = e.target.value; Search.go(); };
  $('#s-range').onchange = () => {
    if (($('#sq').value || '').trim()) Search.go();
  };
  /* ---- Search type selector: 8 experiences, each with its own query,
       filters, and results. Switching preserves each type's query. ---------- */
  $$('.stype-btn').forEach(b => {
    b.onclick = (e) => {
      const btn = e.currentTarget;
      const nt = btn.dataset.type;
      if (nt === Search.type) return;
      /* Save the active type's query. */
      const ot = Search.type || 'all';
      Search.saveTypeQuery(ot);
      /* Switch active button. */
      $$('.stype-btn').forEach(x => {
        x.classList.toggle('active', x === btn);
      });
      Search.type = nt;
      /* Show/hide type-specific filters.  Restore the saved query *after*
       * populating the selects: restoring into an empty <select> silently
       * dropped the previous choice. */
      Search.showTypeFilters(nt);

      /* Bible search: offer the installed translations and let a passage
       * narrow the query.  These selects used to be saved and restored but
       * never read, so changing them had no effect at all. */
      if (nt === 'bible') {
        const sb = $('#s-bible-translation');
        if (sb && !sb._populated) {
          const bibles = (S.modules || []).filter(m => m.is_bible);
          sb.innerHTML = '<option value="">All translations</option>'
            + bibles.map(m => '<option value="' + esc(m.id) + '">'
              + esc(m.name) + '</option>').join('');
          sb._populated = true;
        }
      }

      /* Books search: a collection is a module and a type is its taxonomy id. */
      if (nt === 'books') {
        const bc = $('#s-books-collection');
        if (bc && !bc._populated) {
          const books = (S.modules || []).filter(m => !m.is_bible);
          bc.innerHTML = '<option value="">All collections</option>'
            + books.map(m => '<option value="' + esc(m.id) + '">'
              + esc(m.name) + '</option>').join('');
          bc._populated = true;
        }
        const bt = $('#s-books-type');
        if (bt && !bt._populated) {
          const types = Array.from(new Set(
            (S.modules || []).map(m => m.type).filter(Boolean))).sort();
          bt.innerHTML = '<option value="">All types</option>'
            + types.map(x => '<option value="' + esc(x) + '">'
              + esc(x) + '</option>').join('');
          bt._populated = true;
        }
      }

      /* Media: the service publishes the sources it will answer for and the
       * licences it allows.  Both selects were permanently empty otherwise. */
      if (nt === 'media') {
        const ms = $('#s-media-source'), ml = $('#s-media-license');
        if (ms && !ms._populated) {
          api('media/status').then(r => {
            if (!r || r.ok === false) return;
            const opts = xs => xs.map(x => '<option value="' + esc(x) + '">'
                                        + esc(x) + '</option>').join('');
            ms.innerHTML = '<option value="">All sources</option>'
              + opts(r.sources || []);
            ml.innerHTML = '<option value="">All licenses</option>'
              + opts(r.reusable || []);
            ms._populated = ml._populated = true;
            if (Search.type === 'media') Search.restoreTypeQuery('media');
          }).catch(() => {});
        }
      }

      /* The Maps "type" filter had one static option and no data behind it. */
      if (nt === 'maps') {
        const mt = $('#s-map-type');
        if (mt && !mt._populated) {
          api('maps/places', { limit: 1000 }).then(r => {
            if (!r || r.ok === false) return;
            const types = Array.from(new Set((r.places || [])
              .map(p => p.type).filter(Boolean))).sort();
            mt.innerHTML = '<option value="">All places</option>'
              + types.map(t => '<option value="' + esc(t) + '">' + esc(t)
                + '</option>').join('');
            mt._populated = true;
          }).catch(() => {});
        }
      }

      /* Populate the Topics source dropdown with the installed fact books. */
      if (nt === 'topics') {
        const sts = $('#s-topics-source');
        if (sts && !sts._populated) {
          const facts = (S.modules || []).filter(m => m.type === 'FactBook');
          sts.innerHTML = '<option value="">All sources</option>'
            + facts.map(m => '<option value="' + esc(m.id) + '">'
              + esc(m.name) + ' (' + esc(m.lang || '') + ')</option>').join('');
          sts._populated = true;
        }
      }

      /* Attach the @ popup for morph search inputs when switching to morph. */
      if (nt === 'morph') {
        const smr = $('#s-morph-resource');
        if (smr && !smr._populated) {
          const tagged = (S.modules || []).filter(m => m.has_morph);
          smr.innerHTML = '<option value="">All tagged resources</option>'
            + tagged.map(m => '<option value="' + esc(m.id) + '">'
              + esc(m.name) + ' (' + esc(m.lang || '') + ')</option>').join('');
          smr._populated = true;
        }
        const input = $('#s-morph-word');
        if (input && !input._atPopupAttached) {
          attachMorphAtPopup(input, () => ($('#s-morph-resource') || {}).value || '',
                                     () => (($('#s-morph-passage') || {}).value || '').trim());
          input._atPopupAttached = true;
        }
      }

      Search.restoreTypeQuery(nt);
      Search.go();
    };
  });

  /* The morph word input is only relevant for the Morph type. */
  $('#s-morph-word').onkeydown = (e) => { if (e.key === 'Enter') Search.go(); };
  $('#s-scope').onclick = (e) => {
    const opts = [['', 'All resources'], ['bible', 'Bibles only'], ['books', 'Books only']];
    const cur = opts.findIndex(o => o[0] === S.search.opts.scope);
    const nx = opts[(cur + 1) % opts.length];
    S.search.opts.scope = nx[0];
    e.target.textContent = nx[1];
    Search.go();
  };
  /* Which link set a word-click searches from. Some platforms link a search
   * panel to a link set; here the button sets it, and ClickSearch.arm() does
   * the rest: panes on that set search on plain word clicks. */
  const plb = document.createElement('button');
  plb.id = 's-panelink';
  plb.title = 'Word clicks search from link set… (none off)';
  plb.textContent = 'Click: off';
  // The type filters are hidden when their type is not active. Putting this
  // global control after #s-scope made it disappear in seven of eight types.
  (document.querySelector('.search-bar') || $('#s-filters-all')).appendChild(plb);
  const paintPl = () => {
    plb.textContent = ClickSearch.linkSet ? 'Click: ' + ClickSearch.linkSet : 'Click: off';
  };
  paintPl();
  ClickSearch.onChange = paintPl;
  plb.onclick = async () => {
    const sets = [''].concat(S.linkSets || ['A', 'B', 'C', 'D', 'E', 'F']);
    const nx = sets[(sets.indexOf(ClickSearch.linkSet) + 1) % sets.length];
    const r = await post('search/panel_link', { action: 'set', link_set: nx });
    if (r && r.ok !== false) { ClickSearch.linkSet = nx; paintPl(); await App.loadWorkspace(); }
  };
  const wsLayouts = $('#ws-layouts');
  if (wsLayouts) wsLayouts.onclick = () => Workspace.layoutsDialog();
  const wsClear = $('#ws-clearlinks');
  if (wsClear) wsClear.onclick = async () => { await Workspace.clearLinks(); };
  const wsClose = $('#ws-closeall');
  if (wsClose) wsClose.onclick = async () => { await Workspace.closeAll(); };
  const wsReopen = $('#ws-reopen');
  if (wsReopen) wsReopen.onclick = async () => {
    let id = null;
    try { id = localStorage.getItem('gbible:last-module'); } catch (e) {}
    if (!id) { toast('No recently opened resource.', 'warn'); return; }
    await Workspace.openModule(id, {});
  };
  const wsFs = $('#ws-fullscreen');
  if (wsFs) wsFs.onclick = async () => {
    const p = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null;
    if (p) await Workspace.fullscreen(p.id);
    else toast('No pane open.', 'warn');
  };
  /* ws-passageguide button removed — Passage guide is now in the Bible pane */
  const wsGp = $('#ws-guidepane');
  if (wsGp) wsGp.onclick = async () => {
    const p = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null;
    const ref = p && p.cursor && (p.cursor.ref || p.cursor.key);
    const r = ref || prompt('Reference for the guide pane:', 'John 3:16');
    if (r) await Workspace.openGuidePane(r);
  };
  const wsWsp = $('#ws-wordstudypane');
  if (wsWsp) wsWsp.onclick = async () => {
    const num = prompt('Strong’s number for the word study pane:', 'G2316');
    if (num) await Workspace.openWordStudyPane(num);
  };

  Search.help();

  /* ---- Tools menu items ------------------------------------------------ */
  $('#tc-copy-bible-verses').onclick = async () => {
    // Seed from the verse in front of the reader rather than a fixed example.
    const ref = prompt('Reference to copy:', Export.ref() || 'John 3:16');
    if (!ref) return;
    const p = await api('reference', { ref });
    if (!p || p.ok === false) { toast('Cannot read that reference.', 'warn'); return; }
    // Prefer the Bible on the focused pane; fall back to any installed one.
    // Never assume KJV is installed — it may have been removed.
    const tab = document.querySelector('.tile-tab.on');
    const tile = tab && tab.closest('.tile');
    const paneId = tile && (tile.querySelector('.pane') || {}).dataset.pane;
    const pane = paneId && (S.layout && S.layout.panes || []).find(x => x.id === paneId);
    const bible = (pane && modById(pane.module_id) && modById(pane.module_id).is_bible
        && modById(pane.module_id))
      || (S.modules || []).find(m => m.is_bible && m.installed_at)
      || (S.modules || []).find(m => m.is_bible);
    if (!bible) { toast('No Bible is installed.', 'warn'); return; }
    // A `ref` cursor with span:'verse' still reads the whole chapter.  Address
    // the resolved unit key directly so exactly one verse is copied.
    const r = await api('read', { id: bible.id, cursor: { keys: [p.key] },
                                  span: 'verse', context: 0 });
    if (!r.ok || !r.items || !r.items.length) { toast('Could not read that verse.', 'warn'); return; }
    const text = (r.items[0].text || '').trim();
    await Clipboard.write(text);
  };
  $('#tc-text-comparison').onclick = async () => {
    const ref = prompt('Reference to compare across translations:', 'John 3:16');
    if (!ref) return;
    App.show('workspace');
    const bibles = (S.modules || []).filter(m => m.is_bible && m.installed_at).slice(0, 4);
    if (!bibles.length) { toast('No Bibles installed.', 'warn'); return; }
    for (const b of bibles) {
      await Workspace.openModule(b.id, { ref });
    }
    await App.loadWorkspace();
    toast(bibles.length === 1
      ? 'Opened ' + bibles[0].name + '.'
      : 'Opened ' + bibles.length + ' translations in this pane’s tabs.');
  };
  $('#vf-visual-filters').onclick = async () => {
    await VisualFilters.dialog();
  };

  /* ---- New tools menu items ------------------------------------------------ */
  $('#tc-info-tool').onclick = async () => {
    const ref = (prompt('Reference to look up:', Export.ref() || 'John 3:16') || '').trim();
    if (!ref) return;
    const r = await api('info-tool', { ref: ref });
    if (!r.ok) { toast(r.error || 'Failed to load info.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Info Tool: ' + esc(r.ref_label || ref) + '</div>';
    if (r.verses && r.verses.length) {
      h += '<div class="st-sec"><div class="st-h">Verses</div>';
      r.verses.forEach(v => {
        h += '<div class="st-note"><div class="st-t">' + esc(v.ref) + '</div><div class="st-body">' + esc(v.text) + '</div></div>';
      });
      h += '</div>';
    }
    if (r.strongs && r.strongs.length) {
      h += '<div class="st-sec"><div class="st-h">Strong\'s Numbers</div>' + esc(r.strongs.join(', ')) + '</div>';
    }
    if (r.morphology && r.morphology.length) {
      h += '<div class="st-sec"><div class="st-h">Morphology</div>' + esc(r.morphology.join(', ')) + '</div>';
    }
    if (r.topics && r.topics.length) {
      h += '<div class="st-sec"><div class="st-h">Topics</div>' + esc(r.topics.join(', ')) + '</div>';
    }
    if (r.cross_references && r.cross_references.length) {
      h += '<div class="st-sec"><div class="st-h">Cross-References</div>' + r.cross_references.map(x => '<a href="#" data-ref="' + esc(x) + '">' + esc(osisToRef(x)) + '</a>').join(', ') + '</div>';
    }
    if (r.notes && r.notes.length) {
      h += '<div class="st-sec"><div class="st-h">Notes</div>' + r.notes.map(n => '<div class="st-body">' + esc(n) + '</div>').join('');
    }
    modal('Info Tool', h, [{ label: 'Close', cls: 'btn' }]);
  };

  $('#tc-bibliography').onclick = () => {
    // Cite.bibliography() is the richer path: style choice, flagged gaps and
    // every export format. The old menu modal was a lossy duplicate of it.
    Cite.bibliography();
  };

  $('#tc-books-search').onclick = async () => {
    const q = (prompt('Search books for:', '') || '').trim();
    if (!q) return;
    const r = await api('books-search', { q: q, limit: 20 });
    if (!r.ok) { toast(r.error || 'Failed to search.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Books Search: "' + esc(q) + '"</div>';
    if (!(r.results || []).length) h += '<div class="empty">No matches.</div>';
    r.results.forEach(hit => {
      h += '<div class="st-note"><div class="st-t"><a href="#" data-ref="'
        + esc(hit.ref) + '">' + esc(hit.ref) + '</a></div><div class="st-body">'
        + esc(hit.text) + '</div><div class="tiny muted">' + esc(hit.module) + '</div></div>';
    });
    h += '</div>';
    modal('Books Search', h, [{ label: 'Close', cls: 'btn' }]);
  };

  $('#tc-search-synopsis').onclick = async () => {
    const q = (prompt('Search synopsis for:', '') || '').trim();
    if (!q) return;
    const r = await api('search-synopsis', { q: q });
    if (!r.ok) { toast(r.error || 'Failed to get synopsis.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Search Synopsis: "' + esc(q) + '"</div>';
    if (!(r.synopsis || []).length) h += '<div class="empty">No matches.</div>';
    r.synopsis.forEach(s => {
      h += '<div class="st-note"><div class="st-t">' + esc(s.module) + '</div><div class="st-body">'
        + (s.sample_ref
            ? '<a href="#" data-ref="' + esc(s.sample_ref) + '">' + esc(s.sample) + '</a>'
            : esc(s.sample))
        + '</div><div class="tiny muted">' + s.count + ' matches</div></div>';
    });
    h += '</div>';
    modal('Search Synopsis', h, [{ label: 'Close', cls: 'btn' }]);
  };

  $('#tc-insights').onclick = async () => {
    const ref = (prompt('Get insights for:', Export.ref() || 'John 3:16') || '').trim();
    if (!ref) return;
    const r = await api('insights', { ref: ref });
    if (!r.ok) { toast(r.error || 'Failed to get insights.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Insights: ' + esc(r.ref) + '</div>';
    if (!(r.sections || []).length) {
      h += '<div class="empty">No insights for this reference.</div>';
    }
    r.sections.forEach(s => {
      h += '<div class="st-sec"><div class="st-h">' + esc(s.title) + '</div><div class="st-body">' + esc(s.content) + '</div></div>';
    });
    h += '</div>';
    modal('Insights', h, [{ label: 'Close', cls: 'btn' }]);
  };

  $('#tc-sermon-import').onclick = () => {
    // A sermon is long and multi-line: prompts are single-line and the old
    // api() call put the whole text in a GET URL, which fails on real sermons.
    modal('Import a sermon',
      '<div class="st-body">Paste the sermon text. The first non-empty line is '
      + 'used as the title when you leave the title box blank.</div>'
      + '<label class="st-lbl">Sermon text</label>'
      + '<textarea id="si-text" rows="12" style="width:100%"></textarea>'
      + '<label class="st-lbl">Title (optional)</label>'
      + '<input id="si-title" style="width:100%">'
      + '<label class="st-lbl">Series (optional)</label>'
      + '<input id="si-series" style="width:100%">',
      [{ label: 'Cancel', cls: 'btn' },
       { label: 'Import', cls: 'btn primary', close: false, fn: async () => {
         const text = ($('#si-text') || {}).value || '';
         if (!text.trim()) { toast('Paste the sermon text first.', 'warn'); return; }
         const r = await post('sermon-import', {
           text, title: ($('#si-title') || {}).value || '',
           series: ($('#si-series') || {}).value || '' });
         if (!r || r.ok === false) {
           toast((r && r.error) || 'Failed to import sermon.', 'err'); return;
         }
         closeModal();
         toast('Sermon imported: ' + r.title);
       } }]);
  };

  $('#tc-sermon-documents').onclick = async () => {
    const r = await api('sermon-documents', {});
    if (!r.ok) { toast(r.error || 'Failed to load sermons.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Sermon Documents ('
      + esc(r.count) + ')</div>';
    if (!(r.sermons || []).length) h += '<div class="empty">No sermons yet.</div>';
    (r.sermons || []).forEach(s => {
      h += '<div class="st-note"><div class="st-t">' + esc(s.title) + '</div><div class="st-body">' + esc((s.text || '').slice(0, 200)) + '</div></div>';
    });
    h += '</div>';
    modal('Sermon Documents', h, [{ label: 'Close', cls: 'btn' }]);
    wireModalFolds();
  };

  $('#tc-visual-copy').onclick = async () => {
    const ref = (prompt('Reference for visual copy:', Export.ref() || 'John 3:16') || '').trim();
    if (!ref) return;
    // Use the Bible already on the focused pane; otherwise any installed Bible.
    const focused = ((S.layout && S.layout.panes) || []).find(p => p.is_focus);
    const bible = (focused && modById(focused.module_id) && modById(focused.module_id).is_bible
        && modById(focused.module_id))
      || (S.modules || []).find(m => m.is_bible && m.lang === 'eng')
      || (S.modules || []).find(m => m.is_bible);
    const r = await api('visual-copy', { ref, module_id: bible ? bible.id : '' });
    if (!r.ok) { toast(r.error || 'Failed to create visual copy.', 'err'); return; }
    const source = r.module || (bible ? bible.name : '');
    VisualCopy.save(r.label || r.ref || ref, r.text || '', source);
    if (r.note) toast(r.note, 'warn');
  };

  $('#tc-confessional-docs').onclick = async () => {
    const r = await api('confessional-documents', {});
    if (!r.ok) { toast(r.error || 'Failed to load confessional documents.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Confessional Documents'
      + ((r.sources || []).length ? ' · ' + esc(r.sources.join(', ')) : '') + '</div>';
    if (!(r.documents || []).length) h += '<div class="empty">No confessional documents found in the installed sources.</div>';
    (r.documents || []).forEach(d => {
      h += '<div class="st-note"><div class="st-t">' + esc(d.title) + '</div><div class="st-body">' + esc(d.text) + '</div><div class="tiny muted">' + esc(d.module) + '</div></div>';
    });
    h += '</div>';
    modal('Confessional Documents', h, [{ label: 'Close', cls: 'btn' }]);
    wireModalFolds();
  };

  $('#tc-catholic-readings').onclick = () => {
    const show = async (date) => {
      if (!date) return;
      const r = await api('catholic-daily-readings', { date: date });
      if (!r.ok) { toast(r.error || 'Failed to load daily readings.', 'err'); return; }
      let h = '<div class="st-sec open"><div class="st-h">Catholic Daily Readings'
        + (r.season ? ' - ' + esc(r.season) : '') + '</div>';
      if (!(r.readings || []).length) h += '<div class="empty">No readings for that date.</div>';
      (r.readings || []).forEach(x => {
        h += '<div class="st-note"><div class="st-t">' + esc(x.title) + '</div><div class="st-body">' + esc(x.text) + '</div><div class="tiny muted">' + esc(x.module) + '</div></div>';
      });
      h += '</div>';
      modal('Catholic Daily Readings', h, [{ label: 'Close', cls: 'btn' }]);
    wireModalFolds();
    };
    DatePicker.open({ anchor: $('#tc-catholic-readings'),
      label: 'Date for daily readings', allowClear: false, onPick: show });
  };

  $('#tc-popular-quotes').onclick = async () => {
    const r = await api('popular-quotes', {});
    if (!r.ok) { toast(r.error || 'Failed to load popular quotes.', 'err'); return; }
    let h = '<div class="st-sec open"><div class="st-h">Popular Quotes</div>'
      + '<div class="tiny muted">' + esc(r.metric || '') + '</div>';
    if (!(r.quotes || []).length) h += '<div class="empty">No cross-references to rank.</div>';
    (r.quotes || []).forEach(q => {
      h += '<div class="st-note"><div class="st-t"><a href="#" data-ref="'
        + esc(q.ref) + '">' + esc(q.ref) + '</a></div><div class="st-body">'
        + esc(q.text) + '</div><div class="tiny muted">' + esc(q.count)
        + ' cross-references' + (q.module ? ' · ' + esc(q.module) : '') + '</div></div>';
    });
    h += '</div>';
    modal('Popular Quotes', h, [{ label: 'Close', cls: 'btn' }]);
    wireModalFolds();
  };

  const sf = debounce(() => Store.fetch(), 320);
  ['#f-repo', '#f-lang', '#f-cat', '#f-subj', '#f-slot', '#f-sort'].forEach(s =>
    $(s).onchange = () => { Store.syncRepoButton(); Store.fetch(); });
  $('#f-repo-del').onclick = () => Store.dropRepo();
  $('#f-repo-add').onclick = () => Store.addRepo();
  $('#f-q').oninput = sf;
  $('#f-inst').onchange = () => Store.fetch();
  $('#s-browse').onclick = () => Search.browse();
  const sSmart = $('#s-smart');
  if (sSmart) sSmart.onclick = () => Search.smart();
  $('#s-save').onclick = async () => {
    const q = ($('#sq').value || '').trim();
    if (!q) { toast('Nothing to save yet.', 'warn'); return; }
    const name = prompt('Name this search', q.slice(0, 40));
    if (!name) return;
    const s = await api('search/template', { action: 'save', name: name, query: q });
    if (!s || s.ok === false) { toast((s && s.error) || 'Could not save.', 'err'); return; }
    toast('Saved as "' + name + '"');
    Search.loadTemplates();
  };
  const oTab = $('#o-tab');
  if (oTab) oTab.onchange = () => Organise.load();

  const catBtn = $('#l-cat');
  if (catBtn) catBtn.onclick = () => Catalogue.open();

  /* --- clause search and the sentence diagram -------------------------- */
  const clGo = () => Diagram.search(($('#cl-a') || {}).value || '',
    ($('#cl-b') || {}).value || '', ($('#cl-rel') || {}).value || 'same');
  const clBtn = $('#cl-go');
  if (clBtn) clBtn.onclick = clGo;
  /* Asking once at startup rather than on first click: the relations that need
     a parser should not be in the list at all when there is none. */
  const clPanel = $('#clause-panel');
  if (clPanel) {
    Diagram.parser().then(r => { Diagram._parserOk = !!(r && r.available); })
      .catch(() => { Diagram._parserOk = false; });
  }
  ['#cl-a', '#cl-b'].forEach(id => {
    const n = $(id);
    if (n) n.onkeydown = (e) => { if (e.key === 'Enter') clGo(); };
  });
  const clD = $('#cl-diagram');
  if (clD) clD.onclick = () => Diagram.openFrom('#cl-ref');
  /* Visual query builder: a verse's own words as dropdowns, so the query is
   * built by pointing. Every offered word is really in the verse. */
  const clLoad = $('#cl-load');
  if (clLoad) clLoad.onclick = async () => {
    const ref = $('#cl-ref').value.trim();
    if (!ref) { toast('Type a reference first.', 'warn'); return; }
    const r = await api('clause/tokens', { ref });
    if (!r.ok) { toast(r.error || 'No words.', 'warn'); return; }
    ['#cl-wa', '#cl-wb'].forEach((id, i) => {
      const s = $(id);
      s.innerHTML = (r.words || []).map((w, j) =>
        '<option' + (j === i ? ' selected' : '') + '>' + esc(w) + '</option>').join('');
    });
    toast((r.words || []).length + ' words from ' + (r.ref || ref) + '.');
  };
  const clUse = $('#cl-use');
  if (clUse) clUse.onclick = () => {
    const a = $('#cl-wa'), b = $('#cl-wb');
    if (a && a.value) $('#cl-a').value = a.value;
    if (b && b.value) $('#cl-b').value = b.value;
    clGo();
  };

  /* --- word lists and workflows ---------------------------------------- */
  const wlQ = $('#wl-q');
  if (wlQ) wlQ.oninput = debounce(() => WordLists.load(), 320);
  const wlL = $('#wl-limit');
  if (wlL) wlL.onchange = () => WordLists.load();
  $('#o-chart').onchange = () => Organise.load();
  $('#o-word').onkeydown = (e) => { if (e.key === 'Enter') Organise.load(); };
  $('#v-organise').onclick = async (e) => {
    const t = e.target;
    if (t.id === 'o-cadd') {
      const name = $('#o-cname').value.trim();
      if (!name) { toast('Give the collection a name.', 'warn'); return; }
      const r = await api('collection', { action: 'save', name: name });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not create the collection.', 'err'); return; }
      Organise.load(); return;
    }
    if (t.id === 'o-ladd') {
      const name = $('#o-lname').value.trim();
      if (!name) { toast('Give the list a name.', 'warn'); return; }
      const r = await api('passagelist', { action: 'save', name: name });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not create the list.', 'err'); return; }
      Organise.load(); return;
    }
    const cs = t.closest('a[data-csearch]');
    if (cs) {
      const c = (Organise.collections.find(x => x.id === cs.dataset.csearch)) || {};
      S.search.mods = (c.modules || []).map(x => x.module_id || x);
      App.show('search'); Search.go();
      toast('Searching ' + (c.name || 'that collection'));
      return;
    }
    if (t.closest('a[data-copen]')) {
      const c = Organise.collections.find(x => x.id === t.closest('a').dataset.copen);
      const ids = ((c && c.modules) || []).map(x => x.module_id || x).slice(0, 4);
      if (!ids.length) { toast('That collection is empty.', 'warn'); return; }
      for (const id of ids) await Workspace.openModule(id, {});
      return;
    }
    const cd = t.closest('a[data-cdel]');
    if (cd) {
      e.preventDefault();
      if (!confirm('Delete this collection?')) return;
      const r = await api('collection', { action: 'delete', id: cd.dataset.cdel });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not delete the collection.', 'err'); return; }
      Organise.load();
    }
    const lo = t.closest('a[data-lopen]');
    if (lo) { e.preventDefault(); await Organise.openList(lo.dataset.lopen); return; }
    const lr0 = t.closest('a[data-lread]');
    if (lr0) {
      e.preventDefault();
      /* "read" is filtered reading: exactly these references, in this order,
       * resolved against one Bible.  It differs from "open" in that a passage
       * the chosen resource does not contain is reported rather than skipped,
       * because a list assembled from several translations routinely names a
       * verse one of them numbers differently -- and silently dropping those
       * would leave a reading that quietly omits half its points.
       *
       * The resource is the one the list was built from, counted across its
       * items.  Falling back to "the first Bible installed" reads a Basque New
       * Testament for a list written in English, because that is what sorts
       * first. */
      const d = await api('passagelist', { id: lr0.dataset.lread });
      const items = d.items || [];
      if (!items.length) { toast('That list is empty.', 'warn'); return; }
      const refs = items.map(i => i.ref_label).filter(Boolean);
      if (!refs.length) { toast('That list has no readable references.', 'warn'); return; }
      const tally = {};
      items.forEach(i => { if (i.module_id) tally[i.module_id] = (tally[i.module_id] || 0) + 1; });
      const ranked = Object.keys(tally).sort((a, b) => tally[b] - tally[a]);
      const bible = ranked.map(id => modById(id)).find(m => m && m.is_bible)
        || S.modules.find(m => m.is_bible && m.lang === 'eng')
        || S.modules.find(m => m.is_bible);
      if (!bible) { toast('No Bible is installed.', 'warn'); return; }
      const list = (Organise.lists || []).find(x => x.id === lr0.dataset.lread);
      await Study.readFiltered(bible.id, refs, (list && list.name) || 'Passages');
      return;
    }
    const lf = t.closest('a[data-lflash]');
    if (lf) { e.preventDefault(); Flashcards.open('passage', lf.dataset.lflash); return; }
    const ld = t.closest('a[data-ldel]');
    if (ld) {
      e.preventDefault();
      if (!confirm('Delete this list and its passages?')) return;
      const r = await post('passagelist', { action: 'delete', id: ld.dataset.ldel });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not delete the list.', 'err'); return; }
      Organise.load(); return;
    }
    const lr = t.closest('a[data-lrm]');
    if (lr) {
      e.preventDefault();
      const r = await post('passagelist', { action: 'remove', item: lr.dataset.lrm });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not remove the item.', 'err'); return; }
      Organise.load(); return;
    }
    const lm = t.closest('a[data-lmove]');
    if (lm) {
      e.preventDefault();
      const r = await post('passagelist', { action: 'move', item: lm.dataset.lmove,
                                             delta: lm.dataset.d });
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not move the item.', 'err'); return; }
      Organise.load(); return;
    }
    const tp = t.closest('a[data-tpl]');
    if (tp) {
      const tpl = Organise.templates.find(x => x.id === tp.dataset.tpl);
      // into the box, not just the state: Search.go() reads the box, so setting
      // S.search.q alone would run the previous search again
      if (tpl) { $('#sq').value = tpl.query; App.show('search'); Search.go(); }
      return;
    }
    const td = t.closest('a[data-tpldel]');
    if (td) { await api('search/template', { action: 'delete', id: td.dataset.tpldel });
              if (S.view === 'organise') Organise.load(); }
  };

  $('#ou-nt').onchange = () => { Study._ouDefaulted = true; Study.loadNtuSeOt(); };
  $('#ou-ot').onchange = () => Study.loadNtuSeOt();
  $('#cg-ref').onkeydown = (e) => { if (e.key === 'Enter') Study.loadConcordance(); };
  $('#cg-word').onkeydown = (e) => { if (e.key === 'Enter') Study.loadConcordance(); };
  $('#cg-tagged').onchange = () => Study.loadConcordance();
  $('#cg-mod').onchange = () => Study.loadConcordance();
  /* The maps view wires its own controls in MapsUI.wire() (bindings live
   * next to the state they mutate); nothing here touches the map. */
  /* Image search is a button for the same reason as the modern lookup: the
   * quota is 100 requests a day and 5 an hour, so a keystroke-driven search
   * spends it on prefixes.  Changing a filter does re-search, because that is
   * the reader narrowing a result set they already asked for -- and the answer
   * to a narrower query is usually a fresh one. */
  if ($('#md-go')) {
    $('#md-go').onclick = () => Media.search(1);
    $('#md-q').onkeydown = (e) => {
      if (e.key === 'Enter') Media.search(1);
    };
    $('#md-lic').onchange = () => Media.search(1);
    $('#md-src').onchange = () => Media.search(1);
  }
  $('#g-tab').onchange = () => Guides.load();
  $('#sm-tab').onchange = () => {
    if ($('#sm-tab').value === 'sermon-editor') history.pushState(null, '', window.location.pathname);
    SermonHub.load();
  };
  $('#g-trad').onchange = () => Guides.load();
  $('#g-ref').onkeydown = (e) => { if (e.key === 'Enter') Guides.load(); };
  $('#g-name').onkeydown = (e) => { if (e.key === 'Enter') Guides.load(); };
  $('#g-term').onkeydown = (e) => {
    if (e.key !== 'Enter') return;
    /* Enter in the grammar tab searches; in the counseling tab it filters.  Both
     * reload the tab, which each renderer interprets its own way, and the
     * grammar panel reads the box itself rather than being told which tab it is
     * in. */
    Guides.load();
  };
  $('#n-kind').onchange = () => Notes.load();
  $('#n-prayer-filter').onchange = () => Notes.load();
  $('#n-q').oninput = debounce(() => Notes.load(), 250);
  $('#n-new').onclick = () => { App.show('notes'); Notes.new(); };
  $('#n-export').onclick = () => Export.open('notes');
  $('#n-clear').onclick = async () => {
    /* Destructive, and the undo is not ours to offer: one confirmation naming
     * what will go, and then every kind the filter can reach — the current
     * filter selects a view, not a set of notes. */
    const kind = $('#n-kind').value;
    const count = Notes.items.length;
    if (!count) { toast('There is nothing to clear.'); return; }
    const scope = kind === '' ? 'all notes, journal entries, sermon outlines and prayer lists'
      : (kind === 'note' ? 'all notes' : 'all ' + kind + ' entries');
    if (!confirm('Delete ' + scope + '?\n\n' + count + ' item' + (count === 1 ? '' : 's')
      + ' will be permanently removed from this computer.')) return;
    let deleted = 0;
    for (const n of Notes.items) {
      const r = await api('notes/delete', { id: n.id });
      if (r && r.ok !== false) deleted++;
    }
    Notes.current = null;
    await Notes.load();
    $('#notes-edit').innerHTML = '<div class="empty">Choose a note, or press <b>New</b>.</div>';
    if (deleted < count) {
      toast((count - deleted) + ' could not be deleted.', 'err');
    } else {
      toast(deleted + ' deleted.');
    }
  };

  $('#f-sync').onclick = async () => {
    const b = $('#f-sync'); b.disabled = true; b.textContent = 'Refreshing…';
    const r = await post('store/sync', {});
    if (!r || r.ok === false) {
      b.disabled = false; b.textContent = 'Refresh catalogues';
      toast((r && r.error) || 'Could not refresh catalogues.', 'err');
      return;
    }
    Store._repos = null; await Store.load();
    b.disabled = false; b.textContent = 'Refresh catalogues';
    toast('Catalogues refreshed.');
  };
  $('#f-import').onclick = () => ImportWizard.open();
  const fUpd = $('#f-updates');
  if (fUpd) fUpd.onclick = async () => {
    const r = await api('store/updates');
    if (!r.ok) { toast(r.error || 'Could not check for updates.', 'err'); return; }
    const unverified = r.unchecked || 0;
    if (!r.count) {
      toast(unverified
        ? 'Nothing to update among the resources with recorded versions. '
          + unverified + ' more could not be checked (no version recorded).'
        : 'All installed modules are up to date.', 'ok');
      return;
    }
    const caveat = unverified
      ? '\n\n' + unverified + ' other resource(s) have no recorded version '
        + 'and could not be checked.'
      : '';
    if (!confirm(r.count + ' update(s) available. Install them now?' + caveat)) return;
    let done = 0, failed = 0, skipped = 0;
    for (const u of (r.updates || [])) {
      toast('Updating ' + u.title + '…');
      const jr = await post('store/install',
        { repo: u.repo, item: u.item, force: 1 });
      if (!jr || jr.ok === false || !jr.job) {
        toast((jr && jr.error) || 'Could not start that update.', 'err');
        failed++;
        continue;
      }
      // Poll with a bound so a stuck job cannot hang the dialog forever.
      let finished = false, error = '';
      for (let attempt = 0; attempt < 120 && !finished; attempt++) {
        await new Promise(res => setTimeout(res, 500));
        const js = await api('store/job', { job: jr.job });
        if (!js || js.ok === false || !js.job) { error = (js && js.error) || 'Job vanished.'; break; }
        const j = js.job;
        if (j.state === 'done') {
          finished = true;
          if (j.result && j.result.already) skipped++;
          else done++;
        }
        else if (j.state === 'error' || j.state === 'cancelled') {
          error = j.error || j.message || 'The update failed.'; break;
        }
      }
      if (error) { toast(u.title + ': ' + error, 'err'); failed++; }
    }
    toast((done ? 'Updated ' + done + ' resource(s). ' : '')
      + (skipped ? skipped + ' were already current. ' : '')
      + (failed ? failed + ' failed.' : 'Refreshing library…'));
    await App.loadLibrary();
    if (typeof Store !== 'undefined' && Store.fetch) Store.fetch();
    if (typeof Store !== 'undefined') Store._repos = null;
  };
  ['#l-type', '#l-lang', '#l-src'].forEach(s => $(s).onchange = () => Library.paint());
  $('#l-q').oninput = debounce(() => Library.paint(), 250);
  $('#l-detail').onchange = () => Library.paint();
  $('#l-attr').onclick = () => Library.attribution();
  $('#l-biblio').onclick = () => Cite.bibliography();
  $('#l-tags').onclick = () => Library.tags();
  $('#l-avail').onclick = () => Library.coverage();
  $('#l-prio').onclick = () => Library.prioritise();
  const plExport = $('#pl-export'); if (plExport) plExport.onclick = () => Plans.exportJSON();
  const plImport = $('#pl-import'); if (plImport) plImport.onclick = () => Plans.importJSON();
  const plLect = $('#pl-lectionary'); if (plLect) plLect.onclick = () => Plans.lectionary();
  const plNew = $('#pl-new'); if (plNew) plNew.onclick = () => Plans.newPlan();
  const clNew = $('#cl-new'); if (clNew) clNew.onclick = async () => {
    const heading = prompt('Name the new clip', 'Clip');
    if (!heading) return;
    const r = await post('clipping', { action: 'save', heading });
    if (!r || r.ok === false) { toast((r && r.error) || 'Could not create the clip.', 'err'); return; }
    if (r.clipping) Clippings._id = r.clipping.id;
    Clippings.load();
  };
  const clQ = $('#cl-q'); if (clQ) clQ.oninput = debounce(() => Clippings.load(), 250);
  const gExport = $('#g-oexport'); if (gExport) gExport.onclick = () => Outlines.exportDoc();
  const gb = $('#g-browser'); if (gb) gb.onclick = () => Study.openBibleBrowser();
  const gob = $('#g-obrowser'); if (gob) gob.onclick = () => Study.openOutlineBrowser();
  const grs = $('#g-refscan'); if (grs) grs.onclick = () => Study.openReferenceScanner();
  const gng = $('#g-namesgod'); if (gng) gng.onclick = () => Study.openNamesForGod();
  const gss = $('#g-sensesearch'); if (gss) gss.onclick = () => Study.openSenseSearch();
  const gsx = $('#g-syntax'); if (gsx) gsx.onclick = () => {
    App.show('search');
    setTimeout(() => {
      const p = $('#clause-panel'); if (!p) return;
      const d = p.tagName === 'DETAILS' ? p : p.querySelector('details');
      if (d) d.open = true;
      p.scrollIntoView({ behavior: 'smooth' });
      const a = $('#cl-a'); if (a) a.focus();
    }, 100);
  };
  $('#f-transfers').onclick = () => Store.transfers();

  /* How citable this library actually is.  Kept in the Library rather than
   * buried, because it is the fact that governs everything else here: a
   * citation cannot be better than the metadata behind it. */
  $('#l-cite').onclick = async () => {
    const c = await api('cite/completeness');
    if (!c || c.ok === false) { toast((c && c.error) || 'Could not check citations.', 'err'); return; }
    modal('How citable this library is',
      '<div class="st-body">'
      + '<p>Of <b>' + c.total + '</b> installed resources, <b>' + c.complete
      + '</b> have every field their citation needs and <b>' + c.incomplete
      + '</b> do not.</p>'
      + '<p>That is not a criticism of the library — it is mostly that '
      + 'CrossWire strips the author, publisher and date out of the files it '
      + 'ships. A citation here says what it knows and names what it does '
      + 'not; nothing is guessed.</p>'
      + '<table class="ct-table">'
      + Object.entries(c.missing_counts || {}).map(([k, v]) =>
        '<tr><td>' + esc(k) + '</td><td class="n">' + v + '</td></tr>').join('')
      + '</table>'
      + '<div class="ct-do">Pick a resource, then <b>Citation for this '
      + 'resource</b> from its menu, to fill in what you know. It is stored '
      + 'once and used by every later citation.</div></div>',
      [{ label: 'Close', cls: 'btn' },
       { label: 'Build a bibliography', cls: 'btn primary',
         fn: () => Cite.bibliography() }]);
  };

  const preach = el('button', 'btn tiny', 'Preach');
  preach.title = 'Full screen, one pane, large type  (Ctrl+P)';
  preach.onclick = () => Preach.toggle();

  const study = el('button', 'btn tiny', 'Study layout');
  study.onclick = async () => {
    const r = await post('workspace/study', {});
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not build the study layout.', 'err');
      return;
    }
    await App.loadWorkspace();
    toast('Layout: Bible and commentary linked (set A); lexicon and FactBook '
      + 'look up on click, because they share no verse milestone with a Bible.');
  };

  /* Place the layout / study / preach buttons in the workspace bar, next to
     the Word study pane button, rather than beside the Settings menu. */
  const wsBar = $('#workspace-bar');
  if (wsBar) {
    const ref = $('#ws-wordstudypane');
    if (ref) {
      ref.after(preach);
      ref.after(study);
    }
  }

  document.addEventListener('keydown', (e) => {
    // Escape and "/" are handled by the consolidated listener above; adding
    // them here fired both handlers on every press.
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); App.show('store'); }
    if (e.key === 'w' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); App.show('workspace'); }
    /* Preaching mode. F is the mnemonic some platforms use for full screen, and
     * it is the one a presenter reaches for without looking. */
    if (e.key === 'p' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault(); Preach.toggle();
    }
  });

  /* The selection card, on finishing a selection inside a reading pane.
   *
   * mouseup rather than a context menu, because the useful part -- the citation
   * -- is something you want without a right-click.  And it is delayed a
   * moment: at mouseup the selection rectangle is not final, and a card placed
   * against the wrong box jumps when the browser settles it. */
  let cardTimer = 0;
  document.addEventListener('mouseup', (e) => {
    if (e.target.closest('#selcard, #modal-bg, #popup, .ctxmenu')) return;
    if (e.target.closest('input, textarea, .ct-out')) return;
    const pane = e.target.closest('.pane-body');
    if (!pane) { return; }
    clearTimeout(cardTimer);
    const sel = String(window.getSelection() || '');
    if (sel.replace(/\s+/g, ' ').trim().length < 3) { SelCard.hide(); return; }
    cardTimer = setTimeout(() => {
      const now = String(window.getSelection() || '');
      if (now.replace(/\s+/g, ' ').trim().length < 3) { SelCard.hide(); return; }
      const host = e.target.closest('.pane');
      const pane = (S.layout.panes || []).find(
        x => x.id === (host ? host.dataset.pane : ''));
      /* Where the selection *starts*. A selection running past the end of the
       * verse is still quoted from the verse it began in, and the card says so
       * rather than pretending the whole thing is one verse. */
      const verse = e.target.closest('.verse');
      SelCard.fromPane(e.target, pane ? pane.module_id : '',
        verse ? (verse.dataset.k || '') : '',
        verse ? (verse.dataset.label || '') : '');
    }, 190);
  }, true);
};

// Uncaught errors are logged by the global handlers in core.js; adding a
// second pair here only doubled the console noise.

/* ==================================================== preaching mode =====
   Full screen, one pane, no chrome, type you can read from the front.

   Some platforms open a sermon in a new tab and hand it to a presentation view.
   This does the same job against whatever is already on screen, because a pane
   is already a reading surface and rebuilding it into a document would throw away
   the link sets, the text size and the translation the reader chose.

   Two deliberate omissions.  It does not pick a passage: a preaching mode that
   chose for you would be choosing the sermon, and which text you preach from is
   the one decision that is yours.  And it does not remember what you were
   reading -- pressing Escape puts the workspace back exactly as it was, because
   a display mode that rearranged the desk on the way out would be a worse
   surprise than it is a convenience.

   What it borrows from some platform's controls is the shape: paging or scrolling,
   a typeface, five sizes, and a timer that keeps its last setting.          */