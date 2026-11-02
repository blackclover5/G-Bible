const InfoPane = {
  /* A follow-pane card: what/where/who plus library coverage, refreshed as
   * linked panes move when Follow is on. A modal, not a pane, because panes
   * hold resources and this holds an answer. */
  follow: true,
  ref: '',
  async open(ref) {
    this.ref = ref;
    modal('Info — ' + ref, '<div class="st-loading">Gathering…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    await this.refresh(ref);
  },
  async refresh(ref) {
    this.ref = ref;
    const r = await api('info/lookup', { ref }).catch(() => null);
    const host = $('#modal-body');
    if (!host || !r) return;
    if (!r.ok) { host.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    host.innerHTML = '<div class="row wrap"><b>' + esc(r.ref || '') + '</b>'
      + '<span class="tiny muted">' + esc(r.bible || '') + '</span>'
      + '<button class="btn" id="info-fol">'
      + (this.follow ? 'Following ✓' : 'Follow: off') + '</button></div>'
      + (r.text ? '<div class="st-body">' + esc(r.text) + '</div>' : '')
      + '<table class="kv">'
      + '<tr><td>People</td><td>' + esc((r.people || []).map(x =>
        x.word || x.name || '').filter(Boolean).join(', ') || '—') + '</td></tr>'
      + '<tr><td>Places</td><td>' + esc((r.places || []).map(x =>
        x.name || x.place || '').filter(Boolean).join(', ') || '—') + '</td></tr>'
      + '<tr><td>Cross-references</td><td>' + (r.crossrefs || 0) + '</td></tr>'
      + '<tr><td>Commentary notes</td><td>' + (r.commentary_notes || 0) + '</td></tr>'
      + '</table>';
    $('#info-fol').onclick = () => {
      this.follow = !this.follow;
      this.refresh(this.ref);
    };
  },
  maybeRefresh(ref) {
    if (!this.follow || !this.ref) return;
    if (!$('#modal-body')) { this.ref = ''; return; }
    if (document.querySelector('#info-fol')) this.refresh(ref);
  },
};

/* ===================================================== Visual filters */
const VisualFilters = {  on: true,
  css: {
    yellow: 'background:#fff3a3', green: 'background:#c9f2c7',
    blue: 'background:#cfe6ff', pink: 'background:#ffd6e7',
    orange: 'background:#ffe0b3', underline: 'text-decoration:underline wavy',
  },

  /* Paint saved query hits onto the chapter now on screen. Verse spans carry
   * data-k, so matching is by key — never by text search, which would paint
   * lookalikes. All failures are silent: filters decorate, they never block. */
  async paintPane(p, m, body) {
    try {
      if (!this.on || !m || m.reader !== 'verse' || !body) return;
      const first = body.querySelector('.verse[data-k]');
      if (!first) return;
      const r = await api('visualfilter',
        { action: 'apply', id: m.id, key: first.dataset.k });
      if (!r || !r.ok) return;
      const names = {};
      (r.filters || []).forEach(f => { names[f.id] = f; });
      const surfacesFor = (r.surfaces || {});
      Object.entries(r.matches || {}).forEach(([fid, keys]) => {
        const f = names[fid] || {};
        const style = this.css[f.style] || this.css.yellow;
        const terms = (surfacesFor[fid] || []).filter(Boolean);
        (keys || []).forEach(k => {
          body.querySelectorAll('.verse[data-k="' + k + '"]').forEach(sp => {
            sp.title = 'Visual filter: ' + (f.name || fid);
            if (terms.length) {
              this.highlightTerms(sp, terms, style);
            } else {
              sp.setAttribute('style', (sp.getAttribute('style') || '') + ';' + style);
            }
          });
        });
      });
    } catch (e) { /* decorative */ }
  },

  highlightTerms(host, terms, style) {
    if (!host || !terms || !terms.length) return;
    const words = [...new Set(terms.map(t => String(t).trim()).filter(t => t.length > 1))];
    if (!words.length) return;
    const re = new RegExp('\\b(' + words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')\\b', 'gi');
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
        const p = n.parentElement;
        if (p && p.closest('a, button, sup, .vnum, .snum, .morphs, .fn')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const txt = node.nodeValue;
      re.lastIndex = 0;
      if (!re.test(txt)) continue;
      re.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0, m;
      while ((m = re.exec(txt))) {
        if (m.index > last) frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
        const sp = el('span', '', m[0]);
        sp.setAttribute('style', style);
        frag.appendChild(sp);
        last = m.index + m[0].length;
      }
      if (last < txt.length) frag.appendChild(document.createTextNode(txt.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
  },

  async dialog() {
    const r = await api('visualfilter', {}).catch(() => ({ filters: [] }));
    const rows = (r.filters || []).map(f =>
      '<div class="item"><div style="flex:1"><div class="t">' + esc(f.name) + '</div>'
      + '<div class="m"><code>' + esc(f.query || f.morph || '') + '</code>'
      + ' · ' + esc(f.style || 'yellow')
      + (f.enabled === false ? ' · off' : '') + '</div></div>'
      + '<button class="btn" data-tog="' + esc(f.id) + '">'
      + (f.enabled === false ? 'Enable' : 'Disable') + '</button>'
      + '<button class="btn" data-del="' + esc(f.id) + '">Delete</button></div>').join('')
      || '<div class="tiny muted">No filters yet.</div>';
    modal('Filters',
      '<div class="store-list" style="max-height:40vh;padding:0">' + rows + '</div>'
      + '<h4 style="margin-top:12px">New filter</h4>'
      + '<div class="row wrap"><input id="vf-name" placeholder="Name" style="width:130px">'
      + '<input id="vf-q" placeholder="query, e.g. faith AND lord" style="width:220px">'
      + '<input id="vf-morph" placeholder="morph, e.g. pos=V (optional)" style="width:200px">'
      + '<select id="vf-style">' + Object.keys(this.css).map(s =>
        '<option>' + s + '</option>').join('') + '</select>'
      + '<button class="btn primary" id="vf-add">Save</button></div>'
      + '<div class="tiny muted">Double-click F in a pane toolbar to turn highlighting off.</div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body button[data-del]').forEach(b => b.onclick = async () => {
      await post('visualfilter', { action: 'delete', id: b.dataset.del });
      closeModal(); this.dialog();
    });
    $$('#modal-body button[data-tog]').forEach(b => b.onclick = async () => {
      const cur = (r.filters || []).find(f => f.id === b.dataset.tog) || {};
      await post('visualfilter', { action: 'save', id: cur.id, name: cur.name,
        query: cur.query, morph: cur.morph, style: cur.style,
        enabled: cur.enabled === false });
      closeModal(); this.dialog();
    });
    const add = $('#vf-add');
    if (add) add.onclick = async () => {
      const q = $('#vf-q').value.trim();
      const mp = $('#vf-morph').value.trim();
      if (!q && !mp) { toast('A filter needs a query or morphology.', 'warn'); return; }
      await post('visualfilter', { action: 'save', name: $('#vf-name').value.trim() || q || mp,
        query: q, morph: mp, style: $('#vf-style').value });
      closeModal(); this.dialog();
      if (S.layout) App.loadWorkspace();
    };
  },
};

/* ============================================ Click-to-search (panel link) */
const ClickSearch = {
  linkSet: '',
  async load() {
    try {
      const r = await api('search/panel_link', {});
      this.linkSet = (r && r.link_set) || '';
    } catch (e) { this.linkSet = ''; }
  },
  /* When the search panel is linked to this pane's link set, a plain click on
   * a word (not a link, not a selection) runs it as a search. Drag-selecting
   * still selects: a click that extends a selection does nothing here. */
  arm(p, body) {
    try {
      if (!this.linkSet || p.link_set !== this.linkSet) return;
      if (body._clickSearchArmed) return;
      body._clickSearchArmed = true;
      body.addEventListener('click', (e) => {
        if (e.target.closest('a,button,input,select')) return;
        const sel = String(window.getSelection() || '');
        if (sel.trim()) return;
        let word = '';
        try {
          if (document.caretRangeFromPoint) {
            const range = document.caretRangeFromPoint(e.clientX, e.clientY);
            if (range && range.startContainer && range.startContainer.nodeType === 3) {
              const text = range.startContainer.textContent || '';
              let i = range.startOffset;
              const isW = (c) => /[\p{L}\p{N}']/u.test(c || '');
              let a = i, b = i;
              while (a > 0 && isW(text[a - 1])) a--;
              while (b < text.length && isW(text[b])) b++;
              word = text.slice(a, b);
            }
          }
        } catch (err) { word = ''; }
        word = (word || '').trim();
        if (word.length < 2) return;
        $('#sq').value = word;
        App.show('search');
        Search.go();
      });
    } catch (e) { /* never break the reader */ }
  },
};

const Highlights = {
  rows: [],
  byUnit: new Map(),   // "module_id::key" -> [highlight]
  byRef: new Map(),    // "book.chapter.verse" -> [highlight]
  colors: ['yellow', 'green', 'blue', 'pink', 'orange'],
  palettes: [],
  activePalette: '',

  async loadPalettes() {
    const r = await api('highlight/palettes', {}).catch(() => null);
    this.palettes = (r && r.palettes) || [];
    this.activePalette = (r && r.active) || '';
    return this.palettes;
  },

  /* Colors on offer right now: the active palette's subset, or everything. */
  activeColors() {
    const p = this.palettes.find(x => x.id === this.activePalette);
    if (p && p.colors && p.colors.length) {
      return p.colors.filter(c => this.colors.includes(c));
    }
    return this.colors;
  },

  async palettesDialog() {
    await this.loadPalettes();
    const rows = this.palettes.map(p =>
      '<div class="item"><div style="flex:1"><div class="t">' + esc(p.name)
      + (p.id === this.activePalette ? ' <span class="chip">active</span>' : '')
      + '</div><div class="m">' + esc((p.colors || []).join(', ')) + '</div></div>'
      + (p.id === this.activePalette ? '' : '<button class="btn" data-act="' + esc(p.id) + '">Use</button>')
      + '<button class="btn danger" data-del="' + esc(p.id) + '">Delete</button></div>').join('')
      || '<div class="tiny muted">No palettes — everything uses all five colors.</div>';
    modal('Highlight palettes',
      '<div class="store-list" style="max-height:40vh;padding:0">' + rows + '</div>'
      + '<h4 style="margin-top:12px">New palette</h4>'
      + '<div class="row wrap"><input id="hp-name" placeholder="Name" style="width:140px">'
      + this.colors.map(c => '<label class="tiny"><input type="checkbox" data-hpc="' + c
        + '" checked> ' + c + '</label>').join('')
      + '<button class="btn primary" id="hp-add">Save</button></div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body button[data-act]').forEach(b => b.onclick = async () => {
      await post('highlight/palettes', { action: 'activate', id: b.dataset.act });
      await this.loadPalettes();
      closeModal(); this.palettesDialog();
    });
    $$('#modal-body button[data-del]').forEach(b => b.onclick = async () => {
      await post('highlight/palettes', { action: 'delete', id: b.dataset.del });
      await this.loadPalettes();
      closeModal(); this.palettesDialog();
    });
    $('#hp-add').onclick = async () => {
      const picked = $$('#modal-body input[data-hpc]:checked').map(x => x.dataset.hpc);
      if (!picked.length) { toast('Pick at least one color.', 'warn'); return; }
      await post('highlight/palettes', { action: 'save',
        name: $('#hp-name').value.trim() || 'Untitled palette', colors: picked });
      await this.loadPalettes();
      closeModal(); this.palettesDialog();
    };
  },

  async load() {
    const r = await api('highlights');
    this.rows = r.highlights || [];
    this.byUnit.clear();
    this.byRef.clear();
    this.rows.forEach(h => {
      const k = h.module_id + '::' + h.unit_key;
      if (!this.byUnit.has(k)) this.byUnit.set(k, []);
      this.byUnit.get(k).push(h);
      /* A highlight on a verse is filed under the verse as well as under the
       * unit it was made in.
       *
       * The unit key belongs to its module -- the same verse is "John.3.16" in
       * one Bible and "John 3:16" in another -- so a highlight filed against
       * the key alone cannot follow its verse to a different translation.  The
       * canonical place is the same everywhere, and a highlight that has one
       * is found in every translation that has the verse. */
      if (h.book && h.chapter && h.verse) {
        const rk = h.book + '.' + h.chapter + '.' + h.verse;
        if (!this.byRef.has(rk)) this.byRef.set(rk, []);
        this.byRef.get(rk).push(h);
      }
    });
    return this.rows;
  },

  /* The highlights on a unit: the ones made in it, and the ones made on the
   * same verse in another translation. */
  for(moduleId, unitKey, osis) {
    const out = (this.byUnit.get(moduleId + '::' + unitKey) || []).slice();
    if (osis) {
      (this.byRef.get(osis) || []).forEach(h => {
        if (!out.some(x => x.id === h.id)) out.push(h);
      });
    }
    return out;
  },

  /* Store the current selection, if it is a selection inside this pane.
   *
   * The quote is collapsed to whitespace: the rendered text is HTML with new
   * lines and indentation between tags, and a user selecting across a line break
   * would otherwise store a quote that can never be found again. */
  async add(moduleId, unitKey, ref, color, forced, label) {
    // Clicking a menu button collapses the selection, so the text is captured
    // when the menu is built (passed in as `forced`) and only then falls back to
    // the live selection.  Reading it here found nothing and silently stored an
    // empty quote, so the highlight appeared to do nothing at all.
    const sel = window.getSelection();
    const live = sel ? sel.toString() : '';
    const quote = String(forced || live || '').replace(/\s+/g, ' ').trim();
    if (quote.length < 2) {
      toast('Select some text first, then right-click and choose '
            + 'Highlight selection.', 'warn');
      return;
    }
    // An optional label lets a reader group highlights ("sermon", "study",
    // "question") and find them again without scrolling the whole module.
    if (label === undefined) {
      label = (prompt('Label this highlight (optional):', '') || '').trim();
    }
    await api('highlights', { action: 'add', id: moduleId, key: unitKey,
                              quote: quote.slice(0, 400), color: color || 'yellow',
                              label: label || '' });
    sel.removeAllRanges();
    await this.load();
    toast('Highlighted “' + quote.slice(0, 40) + (quote.length > 40 ? '…' : '') + '”'
          + (label ? '  [' + label + ']' : ''));
    return quote;
  },

  async remove(hid) {
    await api('highlights', { action: 'delete', hid: hid });
    await this.load();
    Reader.repaint();
    if (S.view === 'today') Dashboard.paintHighlights();
  },

  /* Wrap each stored quote for this unit in <mark>.  First occurrence per text
   * node only, so a repeated word does not end up with a stripe down the page.
   *
   * The tree is re-walked for every highlight rather than collected once:
   * marking splits a text node into three, and those new nodes are not in a
   * list captured beforehand, so a second highlight in the same text node would
   * search a detached node and silently do nothing. */
  mark(root, moduleId, unitKey, osis) {
    const hs = this.for(moduleId, unitKey, osis);
    if (!hs.length) return;
    hs.forEach(h => {
      const quote = (h.quote || '').replace(/\s+/g, ' ');
      if (quote.length < 2) return;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
      let n;
      let found = false;
      while ((n = walker.nextNode())) {
        if (!n.nodeValue) continue;
        const t = n.nodeValue;
        let i = t.indexOf(quote);
        if (i < 0) i = t.toLowerCase().indexOf(quote.toLowerCase());
        if (i < 0) continue;
        found = true;
        const mk = document.createElement('mark');
        mk.className = 'hl hl-' + (h.color || 'yellow');
        mk.dataset.hid = h.id;
        mk.title = (h.label ? '[' + h.label + '] ' : '') + (h.note || 'highlight');
        mk.textContent = t.slice(i, i + quote.length);
        const after = document.createTextNode(t.slice(i + quote.length));
        const before = document.createTextNode(t.slice(0, i));
        /* Hold the parent first.  replaceChild() detaches `n`, so afterwards
         * n.parentNode is null and inserting through it threw
         * "Cannot read properties of null (reading 'insertBefore')" -- which
         * aborted Reader.paint and left the chapter blank.  Any highlight for
         * the chapter being read broke the reader. */
        const parent = n.parentNode;
        parent.replaceChild(mk, n);
        if (after.nodeValue) parent.insertBefore(after, mk.nextSibling);
        if (before.nodeValue) parent.insertBefore(before, mk);
        return;                       // first match only, for this highlight
      }
      /* The words are not in this translation -- it says the same thing in
       * other words.  The verse is still the same verse, so the highlight
       * follows it, and the whole verse is tinted rather than the words
       * marked.  A highlight that is meant to travel should not disappear
       * because the translation words them differently. */
      if (!found && h.book) {
        root.classList.add('hlv');
        root.classList.add('hlv-' + (h.color || 'yellow'));
      }
    });
  },

  async list(refLabel) {
    await this.load();
    if (!this.rows.length) return '';
    let h = '<div class="dash-h">Highlights · ' + this.rows.length
      + ' <a href="#" class="tiny muted" id="hl-pal">palettes</a></div>';
    this.rows.slice(0, 40).forEach(x => {
      const label = refLabel ? refLabel(x) : (x.unit_key || '');
      h += '<div class="hl-row">'
        + '<span class="hl-sw hl-' + esc(x.color || 'yellow') + '"></span>'
        + '<span class="hl-q">' + esc(x.quote) + '</span>'
        + (x.label ? '<span class="hl-lab">' + esc(x.label) + '</span>' : '')
        + '<span class="hl-k">' + esc(label) + '</span>'
        + '<a href="#" class="hl-go" data-m="' + esc(x.module_id)
        + '" data-k="' + esc(x.unit_key) + '">open</a>'
        + '<a href="#" class="hl-del" data-hid="' + esc(x.id) + '">×</a>'
        + '</div>';
    });
    return h;
  },
};

/* ============================================================== Tags
 *
 * A tag is a named category, and a thing can be in more than one: a passage
 * can be "grace", "Romans" and "sermon series" at the same time.  That is the
 * whole difference from a label, which can only be one thing -- so a second
 * label used to mean a second highlight of the same words.
 *
 * A tagged verse is stored by its canonical place rather than by the key of
 * the module it was tagged in, so the tag follows the passage from one
 * translation to the next.  That is the reason for tagging it rather than
 * highlighting it: the highlight is about the words, and the words differ
 * between translations; the tag is about the passage, and the passage does
 * not.
 */
const Tags = {
  tags: [],
  items: [],
  verse: null,         // the verse the reader is on, and its tags
  _seq: 0,             // which load is the latest
  byVerse: new Map(),   // "book.chapter.verse" -> [tag item]

  async load(moduleId, unitKey) {
    /* Loads overlap -- one at startup, one when a guide opens, one when the
     * dashboard paints -- and a slow answer to an old question must not
     * overwrite a newer one.  The counter says which answer is the latest,
     * and an answer that has been overtaken is dropped rather than applied. */
    const seq = ++this._seq;
    const q = (moduleId && unitKey)
      ? { module_id: moduleId, unit_key: unitKey } : {};
    const r = await api('tags', q).catch(() => null);
    if (seq !== this._seq) return this.tags;
    /* A failed load must not empty the list.  The tags are the reader's, and
     * a server that hiccups should not make them disappear -- and the picker
     * would then offer a blank list, as if they had never existed. */
    if (!r || r.ok === false) return this.tags;
    this.tags = r.tags || [];
    this.items = (r && r.items) || [];
    this.verse = (r && r.verse) || null;
    this.byVerse.clear();
    this.items.forEach(it => {
      if (!it.book || !it.chapter || !it.verse) return;
      const k = it.book + '.' + it.chapter + '.' + it.verse;
      if (!this.byVerse.has(k)) this.byVerse.set(k, []);
      this.byVerse.get(k).push(it);
    });
    return this.tags;
  },

  forVerse(osis) {
    return osis ? (this.byVerse.get(osis) || []) : [];
  },

  namesFor(osis) {
    return this.forVerse(osis).map(it => {
      const t = this.tags.find(x => x.id === it.tag_id);
      return t ? t.name : '';
    }).filter(Boolean);
  },

  async add(tagId, moduleId, unitKey) {
    await post('tags', { action: 'add', tag_id: tagId, module_id: moduleId,
                          unit_key: unitKey });
    await this.load();
  },

  async removeItem(itemId) {
    await post('tags', { action: 'remove', id: itemId });
    await this.load();
  },

  async create(name, color) {
    const r = await post('tags', { action: 'create', name: name,
                                   color: color || '' });
    await this.load();
    return r && r.tag ? r.tag : null;
  },

  async rename(id, name) {
    await post('tags', { action: 'rename', id: id, name: name });
    await this.load();
  },

  async destroy(id) {
    await post('tags', { action: 'delete', id: id });
    await this.load();
  },

  /* The picker: put this passage in a tag, or in several.
   *
   * Every tag is a row, and a row already in use is marked.  Clicking a row
   * that is not in use puts the passage in it; clicking one that is takes it
   * out again.  A passage can be in several at once, which is the point of a
   * tag and the reason it is not a label.
   */
  async picker(term, moduleId, unitKey) {
    await this.load(moduleId, unitKey);
    const here = (this.verse && this.verse.items) || [];
    const mine = new Set(here.map(x => x.tag_id));
    const body = (this.tags.length
      ? this.tags.map(t => '<label class="tag-row' + (mine.has(t.id) ? ' on' : '')
        + '"><input type="checkbox" data-tag="' + esc(t.id) + '"'
        + (mine.has(t.id) ? ' checked' : '') + '> <span>' + esc(t.name)
        + '</span><span class="muted tiny"> · ' + t.count + '</span></label>')
        .join('')
      : '<div class="empty tiny">No tags yet. Make one below.</div>');
    modal('Tag ' + (term || 'this passage'),
      '<div class="tiny muted" style="margin-bottom:8px">'
      + esc(term || '') + '</div>'
      + '<div id="tag-list">' + body + '</div>'
      + '<div class="row" style="gap:6px;margin-top:10px">'
      + '<input id="tag-new" placeholder="New tag…" style="flex:1;'
      + 'background:var(--bg-3);border:1px solid var(--line-2);color:var(--fg);'
      + 'padding:6px 9px;border-radius:7px">'
      + '<button class="btn tiny" id="tag-make">Add</button></div>',
      [{ label: 'Done', cls: 'btn primary' }]);
    const save = async (id, on) => {
      if (on) await this.add(id, moduleId, unitKey);
      else {
        const it = ((this.verse && this.verse.items) || [])
          .find(x => x.tag_id === id);
        if (it) await this.removeItem(it.id);
      }
      await Reader.repaint();
    };
    $$('#modal-body input[data-tag]').forEach(cb => {
      cb.onchange = async () => { await save(cb.dataset.tag, cb.checked); };
    });
    $('#tag-make').onclick = async () => {
      const name = ($('#tag-new').value || '').trim();
      if (!name) return;
      const t = await this.create(name);
      if (t) await this.add(t.id, moduleId, unitKey);
      await Reader.repaint();
      closeModal();
    };
  },

  /* Everything that is tagged, and what is in each tag. */
  async browse() {
    await this.load();
    if (!this.tags.length) {
      modal('Tags', '<div class="empty">No tags yet. Right-click a verse '
        + '&rarr; <b>Tag this verse</b>.</div>', [{ label: 'Close', cls: 'btn' }]);
      return;
    }
    const body = this.tags.map(t => {
      const its = this.items.filter(x => x.tag_id === t.id);
      const refs = its.map(it => {
        const r = (it.book && it.chapter && it.verse)
          ? it.book + ' ' + it.chapter + ':' + it.verse : (it.unit_key || '');
        return '<a href="#" data-open-ref="' + esc(it.unit_key || '') + '"'
          + ' data-m="' + esc(it.module_id || '') + '">' + esc(r) + '</a>';
      }).join(' · ');
      return '<div class="tag-card"><div class="org-h"><b>' + esc(t.name)
        + '</b><span class="muted tiny"> · ' + t.count + '</span></div>'
        + '<div class="tiny" style="margin-top:4px">'
        + (refs || '<span class="muted">empty</span>') + '</div>'
        + '<div class="row" style="gap:6px;margin-top:6px">'
        + '<button class="btn tiny" data-rename-tag="' + esc(t.id) + '">Rename</button>'
        + '<button class="btn tiny danger" data-del-tag="' + esc(t.id) + '">Delete</button>'
        + '</div></div>';
    }).join('');
    modal('Tags', body, [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-rename-tag]').forEach(b => b.onclick = async () => {
      const t = this.tags.find(x => x.id === b.dataset.renameTag);
      const name = prompt('Rename this tag:', t ? t.name : '');
      if (!name || !name.trim()) return;
      await this.rename(b.dataset.renameTag, name.trim());
      closeModal();
      this.browse();
    });
    $$('#modal-body [data-del-tag]').forEach(b => b.onclick = async () => {
      if (!confirm('Delete this tag? What is in it is not deleted.')) return;
      await this.destroy(b.dataset.delTag);
      closeModal();
      this.browse();
    });
    $$('#modal-body [data-open-ref]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      const mod = modById(a.dataset.m);
      if (mod) {
        App.show('workspace');
        Workspace.openModule(mod.id, { ref: a.dataset.openRef });
      }
    });
  },
};

/* ================================================================ Speech
 *
 * Read aloud, with a voice on this machine rather than in the browser.
 *
 * Kitten TTS Nano runs server-side and hands back WAV, so the voice is the same
 * one whoever reads it, it works with no network, and there is no API key.  It
 * is also optional: where it is not installed the browser's own speech engine
 * takes over, which is what this did before and still works.  `supported()`
 * is therefore "is there any way to read at all", not "is the voice installed"
 * -- the answer to that comes from /api/tts/status, asked once.
 *
 * Reading stops when it is switched off, because a voice that keeps talking
 * about John 3 after you have read John 4 is worse than no voice at all.
 */