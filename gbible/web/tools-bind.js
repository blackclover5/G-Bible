App.bind = function () {
  $$('#nav button[data-view]').forEach(b => b.onclick = () => { App.show(b.dataset.view);
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
  });
  $$('#nav .menu-btn').forEach(b => b.onclick = (ev) => {
    ev.stopPropagation();
    const panel = $('#menu-' + b.dataset.menu);
    const open = panel && !panel.classList.contains('open');
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    if (panel && open) panel.classList.add('open');
  });
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('#nav .nav-menu')) $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
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
    if (ref) Study.configureGuide(ref, p.module_id);
    else toast('Open a passage first.', 'warn');
  };
  const aboutBtn = $('#menu-about');
  if (aboutBtn) aboutBtn.onclick = () => {
    $$('#nav .menu-pop').forEach(m => m.classList.remove('open'));
    About.show();
  };
  const cbBtn = $('#cmdbox-btn');
  if (cbBtn) cbBtn.onclick = () => CommandBox.open();
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      CommandBox.open();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      e.preventDefault();
      App.show('search');
      setTimeout(() => { const q = $('#sq'); if (q) { q.focus(); q.select(); } }, 50);
      return;
    }
    if (e.key === 'Escape') {
      const modalUp = $('#modal-bg') && $('#modal-bg').classList.contains('on');
      if (modalUp) { closeModal(); e.preventDefault(); }
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
    e.target.classList.toggle('on', S.search.opts.match_case); };
  $('#s-forms').onclick = (e) => { S.search.opts.match_all_forms = !S.search.opts.match_all_forms;
    e.target.classList.toggle('on', S.search.opts.match_all_forms); };
  $('#s-ctx').onclick = (e) => { S.search.opts.context = S.search.opts.context ? 0 : 2;
    e.target.classList.toggle('on', !!S.search.opts.context); Search.go(); };
  $('#s-sort').onchange = (e) => { S.search.opts.sort = e.target.value; Search.go(); };
  $('#s-range').onchange = () => {
    if (($('#sq').value || '').trim()) Search.go();
  };
  $('#s-morph').onclick = () => Study.openMorph(
    ($('#sq').value || '').trim().replace(/^\s*morph:\s*/i, ''));
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
  $('#s-scope').after(plb);
  const paintPl = () => {
    plb.textContent = ClickSearch.linkSet ? 'Click: ' + ClickSearch.linkSet : 'Click: off';
  };
  paintPl();
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
    await api('search/template', { action: 'save', name: name, query: q });
    toast('Saved as "' + name + '"');
    Search.loadTemplates();
  };
  $('#o-tab').onchange = () => Organise.load();

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
    Diagram.parser().then(r => { Diagram._parserOk = !!(r && r.available); });
  }
  ['#cl-a', '#cl-b'].forEach(id => {
    const n = $(id);
    if (n) n.onkeydown = (e) => { if (e.key === 'Enter') clGo(); };
  });
  const clD = $('#cl-diagram');
  if (clD) clD.onclick = () => Diagram.openFrom('#cl-book');
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
    const go = async (fn) => { e.preventDefault(); await fn(); Organise.load(); };
    if (t.id === 'o-cadd') {
      const name = $('#o-cname').value.trim();
      if (!name) { toast('Give the collection a name.', 'warn'); return; }
      await api('collection', { action: 'save', name: name });
      Organise.load(); return;
    }
    if (t.id === 'o-ladd') {
      const name = $('#o-lname').value.trim();
      if (!name) { toast('Give the list a name.', 'warn'); return; }
      await api('passagelist', { action: 'save', name: name });
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
    if (cd) { if (!confirm('Delete this collection?')) return;
              await api('collection', { action: 'delete', id: cd.dataset.cdel }); }
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
      const list = (this.lists || []).find(x => x.id === lr0.dataset.lread);
      await Study.readFiltered(bible.id, refs, (list && list.name) || 'Passages');
      return;
    }
    const lf = t.closest('a[data-lflash]');
    if (lf) { e.preventDefault(); Flashcards.open('passage', lf.dataset.lflash); return; }
    const ld = t.closest('a[data-ldel]');
    if (ld) { if (!confirm('Delete this list and its passages?')) return;
              await api('passagelist', { action: 'delete', id: ld.dataset.ldel }); }
    const lr = t.closest('a[data-lrm]');
    if (lr) { await api('passagelist', { action: 'remove', item: lr.dataset.lrm }); }
    const lm = t.closest('a[data-lmove]');
    if (lm) { await api('passagelist', { action: 'move', item: lm.dataset.lmove,
                                         delta: lm.dataset.d }); }
    const tp = t.closest('a[data-tpl]');
    if (tp) {
      const tpl = Organise.templates.find(x => x.id === tp.dataset.tpl);
      // into the box, not just the state: Search.go() reads the box, so setting
      // S.search.q alone would run the previous search again
      if (tpl) { $('#sq').value = tpl.query; App.show('search'); Search.go(); }
      return;
    }
    const td = t.closest('a[data-tpldel]');
    if (td) { await api('search/template', { action: 'delete', id: td.dataset.tpldel }); }
  };

  $('#ou-nt').onchange = () => { Study._ouDefaulted = true; Study.loadNtuSeOt(); };
  $('#ou-ot').onchange = () => Study.loadNtuSeOt();
  $('#cg-ref').onkeydown = (e) => { if (e.key === 'Enter') Study.loadConcordance(); };
  $('#cg-word').onkeydown = (e) => { if (e.key === 'Enter') Study.loadConcordance(); };
  $('#cg-tagged').onchange = () => Study.loadConcordance();
  $('#cg-mod').onchange = () => Study.loadConcordance();
  /* Debounced, not on Enter: the gazetteer answers a prefix, so typing it is
   * the interaction, and firing on every keystroke would ask the server for a
   * list the reader is about to make narrower.  200ms, the same as the search
   * box, so the two feel like one application. */
  let mpTimer = null;
  $('#mp-find').oninput = () => {
    clearTimeout(mpTimer);
    mpTimer = setTimeout(() => {
      MapsUI.find = ($('#mp-find').value || '').trim();
      MapsUI.search();
    }, 200);
  };
  $('#mp-find').onkeydown = (e) => {
    if (e.key === 'Enter') {
      clearTimeout(mpTimer);
      MapsUI.find = ($('#mp-find').value || '').trim();
      MapsUI.search();
    }
  };
  /* The modern lookup is a button, not a keystroke.  Unlike the gazetteer, this
   * one leaves the machine: Nominatim's policy is one request a second and it
   * counts them, so a search that fires as the reader types spends the quota on
   * prefixes they did not mean.  The answer is cached for a month server-side,
   * so a second search of the same name is free. */
  if ($('#mp-geo-go')) {
    $('#mp-geo-go').onclick = () => MapsUI.geocode();
    $('#mp-geo-q').onkeydown = (e) => {
      if (e.key === 'Enter') MapsUI.geocode();
    };
    $('#mp-geo-near').onchange = () => {
      if (($('#mp-geo-q').value || '').trim()) MapsUI.geocode();
    };
  }
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
  $('#n-q').oninput = debounce(() => Notes.load(), 250);
  $('#n-new').onclick = () => { App.show('notes'); Notes.new(); };
  $('#n-export').onclick = async () => {
    const r = await api('notes/export', {});
    const blob = new Blob([r.markdown], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'gbible-notes.md';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Saved gbible-notes.md');
  };
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
    for (const n of Notes.items) {
      await api('notes/delete', { id: n.id });
    }
    Notes.current = null;
    await Notes.load();
    Notes.edit(Notes.blank());
    $('#notes-edit').innerHTML = '<div class="empty">Choose a note, or press <b>New</b>.</div>';
    toast(count + ' deleted.');
  };

  $('#f-sync').onclick = async () => {
    const b = $('#f-sync'); b.disabled = true; b.textContent = 'Refreshing…';
    await post('store/sync', {});
    Store._repos = null; await Store.load();
    b.disabled = false; b.textContent = 'Refresh catalogues';
    toast('Catalogues refreshed.');
  };
  $('#f-import').onclick = () => $('#fileinput').click();
  $('#fileinput').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    toast('Copy this path into the import box: ' + f.name, 'err');
    modal('Import a local module',
      '<div class="legal">The importer reads SWORD packages, USFM zips, e-Sword modules, '
      + 'MySword books, KML/KMZ place files, images, plain text, and '
      + '<b>EPUB personal books</b> &mdash; drop a DRM-free <code>.epub</code> in here and it '
      + 'becomes a readable, searchable book with the rest of your library. Point it at a '
      + 'file path on this machine.</div>'
      + '<input id="imp-path" style="width:100%;background:var(--bg-3);border:1px solid var(--line-2);'
      + 'color:var(--fg);padding:8px;border-radius:7px" placeholder="/path/to/module.zip">',
      [{ label: 'Import', cls: 'btn primary', close: false, fn: async () => {
          const p = $('#imp-path').value.trim();
          if (!p) return;
          const r = await post('store/import', { path: p });
          if (!r.ok) { toast(r.error, 'err'); return; }
          toast('Importing… detected ' + r.sniffed);
          const poll = async () => {
            const j = (await api('store/job', { job: r.job })).job;
            if (!j) return;
            if (j.state === 'done') { toast('Imported.'); closeModal(); await App.loadLibrary(); await App.loadWorkspace(); return; }
            if (j.state === 'error') { toast(j.message, 'err'); return; }
            setTimeout(poll, 900);
          };
          poll();
        } }, { label: 'Cancel', cls: 'btn' }]);
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
    await App.loadWorkspace();
    toast('Layout: Bible and commentary linked (set A); lexicon and FactBook '
      + 'look up on click, because they share no verse milestone with a Bible.');
  };

  const layouts = el('button', 'btn', 'Layouts');
  layouts.title = 'Rearrange panes, QuickStart layouts, clear link sets';
  layouts.onclick = () => Workspace.layoutsDialog();

  /* Place the layout / study / preach buttons in the workspace bar, next to
     the Word study pane button, rather than beside the Settings menu. */
  const wsBar = $('#workspace-bar');
  if (wsBar) {
    const ref = $('#ws-wordstudypane');
    if (ref) {
      ref.after(preach);
      ref.after(study);
      // Move the Command box button to the far right.
      const cbBtn = document.getElementById('cmdbox-btn');
      if (cbBtn) {
        cbBtn.style.marginRight = '';
        wsBar.appendChild(cbBtn);
      }
    }
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeModal(); Popup.hide(); }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === '/') { e.preventDefault(); App.show('search'); $('#sq').focus(); }
    if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); App.show('store'); }
    if (e.key === 'w' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); App.show('workspace'); }
    if (e.key === 'k' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); CommandBox.open(); }
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

// Surface anything that escapes, so a silent dead UI cannot happen again.
window.addEventListener('unhandledrejection', (e) => {
  console.error('gbible: unhandled rejection', e.reason);
});
window.addEventListener('error', (e) => {
  console.error('gbible: uncaught error', e.message, e.filename + ':' + e.lineno);
});

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