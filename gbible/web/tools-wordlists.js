const WordLists = {
  current: '',
  data: null,
  side: null,

  async load() {
    const host = $('#wl-body');
    if (!host) return;
    host.innerHTML = '<div class="empty">Loading…</div>';
    const r = await api('wordlist', { q: ($('#wl-q') || {}).value || '' });
    if (!r.ok) { host.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    this.lists = r.lists || [];
    const side = $('#wl-side');
    if (side) {
      side.innerHTML = this.lists.length
        ? this.lists.map(l => '<div class="item' + (l.id === this.current ? ' on' : '')
            + '" data-id="' + esc(l.id) + '"><span>' + esc(l.name) + '</span>'
            + '<span class="n">' + (l.pinned || 0) + '</span></div>').join('')
        : '<div class="empty tiny">No lists yet.</div>';
      $$('.item', side).forEach(x => {
        x.onclick = () => { this.current = x.dataset.id; this.load(); };
      });
    }
    if (!this.lists.length) {
      host.innerHTML = '<div class="empty">A word list keeps every place a word '
        + 'occurs, so it is still there tomorrow.<br><br>'
        + 'Make one from any search result, from a Strong\'s number, or from a '
        + 'morphology code — right-click a hit, or use <b>New</b> above.</div>';
      return;
    }
    if (!this.current || !this.lists.some(l => l.id === this.current)) {
      this.current = this.lists[0].id;
    }
    await this.open(this.current);
  },

  async open(id) {
    const host = $('#wl-body');
    if (!host) return;
    this.current = id;
    host.innerHTML = '<div class="empty">Loading…</div>';
    const r = await api('wordlist/occurrences', { id, limit: ($('#wl-limit') || {}).value || 1500 });
    if (!r.ok) { host.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    this.data = r;
    this.paint(host, r);
    const side = $('#wl-side');
    if (side) $$('.item', side).forEach(x =>
      x.classList.toggle('on', x.dataset.id === id));
  },

  paint(host, r) {
    const l = r.list;
    const kept = r.pinned || [];
    const items = r.items || [];
    const keptKeys = new Set(kept.map(k => k.module_id + '|' + k.unit_key));

    /* A distribution, because "where is this word" is usually asked as "how
     * much of each book", and a bar per book answers it at a glance.
     *
     * Counted over the kept rows as well as the live results: a list made from
     * search results holds its occurrences as kept items, so tallying only the
     * re-run results drew no chart at all for exactly the lists with the most
     * in them. */
    const tally = {};
    kept.concat(items).forEach(i => {
      const b = i.book || this.bookOfRef(i.ref_label) || '—';
      tally[b] = (tally[b] || 0) + 1;
    });
    const bars = Object.keys(tally).map(b => ({ label: b, value: tally[b] }))
      .sort((a, b) => b.value - a.value).slice(0, 24);
    const max = bars.length ? bars[0].value : 1;

    const row = (i, keptRow) => '<div class="wl-row' + (keptRow ? ' kept' : '') + '">'
      + '<span class="ref" data-go="' + esc(i.module_id) + '" data-key="'
        + esc(i.unit_key) + '">' + esc(i.ref_label || '—') + '</span>'
      + (keptRow ? '' : '<span class="term">' + esc(i.term || '') + '</span>')
      + '<span class="txt">' + esc((i.snippet || i.text || '').trim()) + '</span>'
      + '<span class="n">' + esc(i.module_id ? (modById(i.module_id) || {}).name || '' : '') + '</span>'
      + '<span class="n">'
      + (keptRow
          ? '<button class="btn" data-up="' + esc(i.id) + '">↑</button>'
            + '<button class="btn" data-note="' + esc(i.id) + '" title="Note">✎</button>'
            + '<button class="btn" data-unpin="' + esc(i.id) + '">✕</button>'
          : '<button class="btn" data-pin="' + esc(i.id) + '" title="Keep this one">+</button>')
      + '</span></div>';

    let h = '<div class="wl-bar">'
      + '<b style="font-size:14px">' + esc(l.name) + '</b>'
      + '<span class="tiny muted">' + esc(l.kind) + '</span>'
      + (l.query ? '<code class="tiny">' + esc(l.query) + '</code>' : '')
      + '<input type="search" id="wl-note" placeholder="Note for this list" value="'
        + esc(l.note || '') + '" style="flex:1;min-width:120px">'
      + '<button class="btn" id="wl-save">Save</button>'
      + '<button class="btn" id="wl-rename">Rename</button>'
      + '<button class="btn" id="wl-pl" title="Read these verses in order">As a passage list</button>'
      + '<button class="btn" id="wl-fl" title="Drill these occurrences as flashcards">Flashcards</button>'
      + '<button class="btn" id="wl-x">Export</button>'
      + '<button class="btn danger" id="wl-del">Delete</button>'
      + '</div>'
      + '<div class="wl-sum">' + (r.total || 0).toLocaleString()
      + ' occurrence' + ((r.total || 0) === 1 ? '' : 's') + ' now'
      + (kept.length ? ' · ' + kept.length + ' kept by hand' : '')
      + (!l.query && kept.length
          // A list captured from a result set holds the rows it was given and
          // no query, so there is nothing to re-run.  Say that, rather than
          // reporting "0 occurrences" as though the list had come up empty.
          ? ' — kept from a search result; it does not re-run, because it has '
            + 'no query of its own' : '')
      + (r.source === 'strongs'
          ? ' · ' + esc(r.number) + ' ' + esc(r.word || r.lemma || '')
          : '')
      + (r.gloss ? ' · ' + esc(r.gloss) : '')
      + '</div>'
      + (r.note ? '<div class="ol-src">' + esc(r.note) + '</div>' : '');

    if (bars.length > 1) {
      h += '<div style="padding:0 8px 8px">' + bars.map(b =>
        '<div class="chart-sm"><span class="lbl" title="' + esc(b.label) + '">'
        + esc(b.label) + '</span><span class="bar" style="width:'
        + Math.max(2, Math.round(b.value / max * 220)) + 'px"></span>'
        + '<span class="v">' + b.value + '</span></div>').join('') + '</div>';
    }

    if (kept.length) {
      h += '<div class="tiny muted" style="padding:4px 8px">Kept by hand</div>'
        + kept.map(i => row(i, true)).join('');
    }
    h += '<div class="tiny muted" style="padding:4px 8px">Every occurrence</div>';
    h += items.length
      ? items.map(i => row(i, keptKeys.has(i.module_id + '|' + i.unit_key))).join('')
      : '<div class="empty">Nothing found. ' + esc(r.note || '') + '</div>';
    host.innerHTML = h;
    this.wire(host, l);
  },

  wire(host, l) {
    const act = async (path, params, msg) => {
      const r = await api(path, params);
      if (!r.ok) { toast(r.error || 'That did not work.', 'err'); return; }
      if (msg) toast(msg);
      await this.open(this.current);
    };
    $$('[data-go]', host).forEach(x => {
      x.onclick = () => {
        const m = modById(x.dataset.go);
        if (!m) { toast('That resource is not installed.', 'warn'); return; }
        closeModal();
        App.show('workspace');
        Workspace.openModule(x.dataset.go, { key: x.dataset.key });
      };
    });
    const on = (sel, fn) => $$(sel, host).forEach(x => { x.onclick = fn(x); });
    on('[data-pin]', x => () => act('wordlist',
      { action: 'pin', id: this.current, term: '', module: x.dataset.pin.split('|')[0],
        key: x.dataset.pin.split('|')[1], label: '' }, 'Kept.'));
    on('[data-unpin]', x => () => act('wordlist',
      { action: 'unpin', item: x.dataset.unpin }, 'Removed.'));
    on('[data-up]', x => () => act('wordlist',
      { action: 'move', item: x.dataset.up, delta: -1 }));
    on('[data-note]', x => () => this.annotate(x.dataset.note));
    const save = $('#wl-save', host);
    if (save) save.onclick = () => act('wordlist', { action: 'save', id: l.id,
      name: l.name, note: $('#wl-note', host).value }, 'Saved.');
    const ren = $('#wl-rename', host);
    if (ren) ren.onclick = () => {
      const name = prompt('Name this list', l.name);
      if (name) act('wordlist', { action: 'save', id: l.id, name }, 'Renamed.');
    };
    const del = $('#wl-del', host);
    if (del) del.onclick = async () => {
      if (!confirm('Delete "' + l.name + '"?  The occurrences come back if you '
                 + 'run the search again; anything you kept by hand goes with it.'))
        return;
      await act('wordlist', { action: 'delete', id: l.id }, 'Deleted.');
      this.current = '';
      this.load();
    };
    const pl = $('#wl-pl', host);
    if (pl) pl.onclick = async () => {
      const r = await api('wordlist', { action: 'passagelist', id: l.id });
      if (!r.ok) { toast(r.error || 'Nothing to make a list from.', 'err'); return; }
      toast(r.added + ' passages added to "' + r.list.name + '".');
      App.show('organise');
    };
    const ex = $('#wl-x', host);
    if (ex) ex.onclick = () => this.exportDialog(l);
    const fl = $('#wl-fl', host);
    if (fl) fl.onclick = () => Flashcards.open('wordlist', l.id);
  },

  annotate(itemId) {
    modal('Note on this occurrence', '<div class="st-body">'
      + '<label class="ct-row"><span>Gloss</span>'
      + '<input id="an-gloss" placeholder="what this form is doing here"></label>'
      + '<label class="ct-row"><span>Note</span>'
      + '<textarea id="an-note" rows="4"></textarea></label>'
      + '</div>', [
      { label: 'Cancel', cls: 'btn' },
      { label: 'Save', cls: 'btn primary', close: false, fn: async () => {
        await api('wordlist', { action: 'note', item: itemId,
          gloss: $('#an-gloss').value, note: $('#an-note').value });
        closeModal();
        await this.open(this.current);
      } }]);
  },

  exportDialog(l) {
    modal('Export "' + l.name + '"',
      '<div class="st-body">A word list exports as a spreadsheet, as plain text '
      + 'for a notes program, or as Markdown. Every occurrence comes with its '
      + 'reference, its resource and the verse text.</div>'
      + '<div class="ct-exports">'
      + ['csv', 'txt', 'md'].map(f => '<button class="ct-fmt" data-f="' + f
        + '">' + f.toUpperCase() + '</button>').join('') + '</div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('.ct-fmt').forEach(b => {
      b.onclick = () => {
        const f = b.dataset.f;
        const url = '/file/wordlist?id=' + encodeURIComponent(this.current)
          + '&fmt=' + f + '&name=' + encodeURIComponent(l.name + '.' + f);
        Cite._save(url, l.name + '.' + f);
        closeModal();
      };
    });
  },

  /* Add one occurrence by hand, from a selection or a search hit. */
  async addOccurrence(text, label, moduleId, key) {
    if (!this.lists || !this.lists.length) {
      const name = prompt('No word lists yet. Name this one:', text.slice(0, 40));
      if (!name) return null;
      const made = await api('wordlist', { action: 'from-results', name,
        hits: [{ term: text, module_id: moduleId, key, label }] });
      if (!made.ok) { toast(made.error || 'Could not make a list.', 'err'); return null; }
      this.current = made.list.id;
      await this.load();
      return made.list;
    }
    modal('Add to a word list',
      '<div class="st-body">Which list should hold '
      + '<b>' + esc((label || 'this occurrence')) + '</b>?</div>'
      + '<div id="wl-pick"></div>', [
      { label: 'Cancel', cls: 'btn' },
      { label: 'New list', cls: 'btn', close: false, fn: async () => {
        const name = prompt('Name the new list', text.slice(0, 40));
        closeModal();
        if (!name) return;
        const made = await api('wordlist', { action: 'from-results', name,
          hits: [{ term: text, module_id: moduleId, key, label }] });
        if (made.ok) { this.current = made.list.id; await this.load(); }
      } }]);
    const host = $('#wl-pick');
    host.innerHTML = this.lists.map(x =>
      '<div class="store-list"><div class="item" data-id="' + esc(x.id) + '">'
      + '<div><b>' + esc(x.name) + '</b><div class="tiny muted">'
      + esc(x.kind) + (x.query ? ' · ' + esc(x.query) : '') + '</div></div>'
      + '</div></div>').join('');
    $$('.item', host).forEach(x => {
      x.onclick = async () => {
        await api('wordlist', { action: 'pin', id: x.dataset.id, term: text,
          surface: text, module: moduleId, key, label });
        closeModal();
        toast('Added.');
      };
    });
    return this.lists[0];
  },

  /* A list of every occurrence of one term.  The list stores the query, so it
   * is re-run every time it is opened and finds occurrences in books this
   * search never reached -- which is the reason to have a word list rather than
   * a folder of search results. */
  async fromQuery(term) {
    const t = String(term || '').trim();
    if (!t) return;
    const r = await api('wordlist', { action: 'from-search', query: '"' + t + '"' });
    if (!r.ok) { toast(r.error || 'Could not make that list.', 'err'); return; }
    toast('A word list for every “' + t + '”.');
    App.show('wordlists');
    this.current = r.list.id;
    await this.load();
  },

  /* The book a kept row belongs to, read off its reference.

   * The rows a search produced carry no book column -- the search engine has
   * no such field -- so a list captured from results has to take it from the
   * label.  First word of "Gen 1:1", "1 John 2:3" and so on; a kept row with no
   * usable label is counted under "—" rather than guessed at.
   */
  bookOfRef(label) {
    const m = String(label || '').trim().match(
      /^((?:[1-3]\s?)?[A-Za-z][A-Za-z.]*)/);
    return m ? m[1] : '';
  },

  /* Called from the search results: keep what is on screen. */
  async fromResults(hits, name) {
    const rows = hits.map(h => ({ term: (h.matched && h.matched[0]) || '',
      text: h.text || '', module_id: h.module_id, key: h.key,
      label: h.label, chapter: h.chapter, verse: h.verse }));
    const n = name || prompt('Name this word list',
      rows.length ? rows[0].term : 'Word list');
    if (!n) return;
    /* POST, not GET.  Four hundred hits with their verse text is a few hundred
       kilobytes, and `api()` puts parameters in the query string -- which came
       back as a "URI too long" HTML page that `response.json()` then choked on,
       so the button silently did nothing.  Bulk data belongs in a body. */
    const r = await post('wordlist', { action: 'from-results', name: n,
                                        hits: rows });
    if (!r.ok) { toast(r.error || 'Could not save it.', 'err'); return; }
    toast('Kept ' + rows.length + ' occurrences as "' + n + '".');
    App.show('wordlists');
    this.current = r.list.id;
    await this.load();
  },
};

/* ============================================================== outlines ===
   The section headings of a chapter, and what each covers.

   This used to answer every request with a note saying no outline data was
   installed, which was honest and useless.  An outline is editorial -- nobody
   can derive one from the text -- so this reads one that was actually written:
   Jamieson, Fausset and Brown's, which is public domain, covers all 66 books
   and every chapter, and ships with the program.

   Whose outline it is, is on the panel the whole time.  An outline shown
   without its author reads like the shape of the text, and that is the specific
   mistake this feature can make, so it does not make it.  Six chapters JFB does
   not outline say so instead of showing an empty list.                          */