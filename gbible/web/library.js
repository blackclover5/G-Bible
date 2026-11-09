const Store = {
  /* What actually got downloaded, and what else the app has done.
   *
   * Both lists exist on the server already and neither was reachable, which is
   * the worst kind of gap: an install that half-worked leaves a row here and
   * nowhere to read it. */
  async transfers() {
    const r = await api('store/transfers');
    const ts = r.transfers || [];
    const hs = r.history || [];
    const when = (t) => new Date((t.finished || t.started || 0) * 1000)
      .toISOString().replace('T', ' ').slice(0, 16);
    const section = (label, note, body) =>
      '<div class="st-sec open"><div class="st-h">' + esc(label) + '</div>'
      + '<div class="tiny muted">' + esc(note) + '</div>' + body + '</div>';
    let h = '';
    if (ts.length) {
      h += section('Downloads and imports', 'the last ' + ts.length + ' transfers',
        '<table class="kv"><tbody>' + ts.map(t =>
          '<tr><td class="tiny muted">' + esc(when(t)) + '</td>'
          + '<td class="tiny">' + esc(t.kind || '') + '</td>'
          + '<td>' + esc(t.title || t.item_id || '') + '</td>'
          + '<td class="tiny">' + esc(t.status || '')
          + (t.message ? ' — ' + esc(t.message) : '') + '</td></tr>').join('')
        + '</tbody></table>');
    }
    if (hs.length) {
      h += section('Other activity', 'what the app did, most recent first',
        '<table class="kv"><tbody>' + hs.map(x =>
          '<tr><td class="tiny muted">' + esc(when(x)) + '</td>'
          + '<td class="tiny">' + esc(x.kind || '') + '</td>'
          + '<td>' + esc(x.text || '') + '</td></tr>').join('')
        + '</tbody></table>');
    }
    if (!h) {
      h = '<div class="empty">Nothing yet. Install something and it appears '
        + 'here.</div>';
    }
    modal('Recent transfers', h, [
      { label: 'Clear', cls: 'btn danger', close: false, fn: async () => {
          const r = await api('store/transfers/clear');
          if (r && r.ok) {
            toast('Transfers cleared', 'ok');
            Store.transfers();
          } else {
            toast((r && r.error) || 'Could not clear transfers', 'err');
          }
        } },
      { label: 'Close', cls: 'btn' },
    ]);
  },


  async load() {
    if (!this._repos) await this.repos();
    await this.fetch();
  },

  async repos() {
    const r = await api('store/repos');
    this._repos = r.repos || [];
    const sel = $('#f-repo');
    const cur = sel.value;
    sel.innerHTML = '<option value="">All repositories</option>'
      + this._repos.map(x => '<option value="' + esc(x.id) + '">'
        + esc(x.name) + ' — ' + (x.installed_count || 0) + ' of '
        + x.item_count + ' installed</option>').join('');
    sel.value = cur;
    this.syncRepoButton();
  },

  syncRepoButton() {
    const id = $('#f-repo').value;
    const r = this._repos.find(x => x.id === id);
    const b = $('#f-repo-del');
    if (!r) { b.disabled = true; b.title = 'Pick a repository first'; return; }
    b.disabled = !r.removable;
    b.title = r.removable
      ? 'Stop offering "' + r.name + '" and forget its ' + r.item_count + ' catalogue entries'
      : (r.id === 'local' ? '"This computer" is not a repository to remove' : 'Not removable');
  },

  /* ---- remove a repository, with a confirmation that names what it costs -- */
  async dropRepo() {
    const id = $('#f-repo').value;
    if (!id) { toast('Pick a repository to remove first', 'err'); return; }
    const pv = await api('store/repo/preview', { repo: id });
    if (!pv.ok) { toast(pv.error || 'Cannot remove that', 'err'); return; }
    const installed = pv.installed || [];
    let msg = 'Remove the "' + pv.name + '" repository?\n\n'
      + '  • ' + pv.catalogue_items + ' catalogue entries are forgotten.'
      + ' They come back if you ever re-add or refresh the repository.';
    if (installed.length) {
      msg += '\n\n' + installed.length + ' downloaded module(s) from it are still installed:'
        + '\n' + installed.map(m => '  • ' + m.name).join('\n')
        + '\n\nDeleting them frees the disk space, and you can install them again later.'
        + '\n\nRemove the repository AND those modules?';
    } else {
      msg += '\n\nNothing is installed from it, so nothing else is deleted.';
    }
    modal('Remove repository', '<div class="st-body" style="white-space:pre-wrap">'
      + esc(msg) + '</div>'
      + '<label style="display:flex;align-items:center;gap:6px;margin-top:10px">'
      + '<input type="checkbox" id="rr-perm"> '
      + '<span>Or permanently delete the repository (it will not come back on Refresh; '
      + 're-add it with the + button if you change your mind).</span></label>',
      [{ label: 'Remove', cls: 'btn danger', fn: async () => {
          const permanent = !!($('#rr-perm') && $('#rr-perm').checked);
          const btn = $('#f-repo-del');
          if (btn) { btn.disabled = true; btn.textContent = '\u2026'; }
          toast('Removing ' + pv.name + ' and its modules\u2026', 'warn');
          const r = await post('store/repo/remove', {
            repo: id, modules: installed.length ? '1' : '',
            permanent: permanent ? '1' : '' });
          if (btn) { btn.disabled = false; btn.textContent = '\u2212'; }
          if (!r.ok) { toast(r.error || 'Could not remove', 'err'); return; }
          toast('Removed ' + r.name + ' (' + r.catalogue_items + ' entries, '
            + (r.removed_modules || []).length + ' modules being deleted in the background)'
            + (r.permanent ? ' \u2014 permanently.' : '.'));
          $('#f-repo').value = '';
          this._repos = null;
          await this.repos();
          await App.loadLibrary();
          this.fetch();
          closeModal();
        } },
        { label: 'Cancel', fn: () => {} }]);

  },

  async addRepo() {
    modal('Add a repository',
      '<div class="st-body" style="margin-bottom:8px">Paste a repository URL. It must '
      + 'point at a JSON catalogue the app can read. A dead host or an unsuitable '
      + 'catalogue is rejected and nothing is added.</div>'
      + '<label class="st-lbl">Repository URL</label>'
      + '<input id="ra-url" type="url" style="width:100%" placeholder="https://example.org/catalogue.json">'
      + '<label class="st-lbl" style="margin-top:8px">Name (optional)</label>'
      + '<input id="ra-name" type="text" style="width:100%" placeholder="My repository">',
      [{ label: 'Add', cls: 'primary', fn: async () => {
          const url = ($('#ra-url') || {}).value || '';
          const name = ($('#ra-name') || {}).value || '';
          if (!url.trim()) { toast('A URL is required.', 'err'); return; }
          const r = await api('store/repo/add', { url: url.trim(), name: name.trim() });
          if (!r || !r.ok) { toast((r && r.error) || 'Could not add that repository.', 'err'); return; }
          toast('Added ' + (r.name || r.repo) + ' (' + (r.items || 0) + ' items).');
          this._repos = null;
          await this.repos();
          $('#f-repo').value = r.repo;
          this.syncRepoButton();
          await App.loadLibrary();
          this.fetch();
          closeModal();
        } },
        { label: 'Cancel', fn: () => {} }]);
  },

  async fetch() {
    const host = $('#store-list');
    host.innerHTML = '<div class="loading">Loading…</div>';
    const slot = $('#f-slot').value;
    const r = await api('store/items', {
      repo: $('#f-repo').value, lang: $('#f-lang').value,
      category: $('#f-cat').value, subject: $('#f-subj').value,
      q: $('#f-q').value, installed_only: $('#f-inst').checked,
      sort: $('#f-sort').value, slot: slot, limit: 3000 });
    if (!r.ok) { host.innerHTML = '<div class="warn">' + esc(r.error) + ' <button class="btn tiny" id="store-retry">Retry</button></div>';
  const rb = $('#store-retry'); if (rb) rb.onclick = () => this.fetch(); return; }
    S.store.items = r.items; S.store.facets = r.facets; S.store.slots = r.slots || [];
    const inst = r.items.filter(x => x.installed).length;
    $('#store-count').textContent = r.total + ' item' + (r.total === 1 ? '' : 's')
      + (inst ? '  ·  ' + inst + ' installed' : '')
      + '  ·  free licences only';

    // "Goes in" is the primary filter, so it is filled from the server's
    // placement summary rather than from a hard-coded list in the client.
    const ss = $('#f-slot'), sv = ss.value;
    ss.innerHTML = '<option value="">Everything</option>'
      + S.store.slots.map(s => '<option value="' + esc(s.id) + '">'
        + esc(s.glyph || '') + '  ' + esc(s.label) + ' (' + s.count + ')</option>').join('');
    ss.value = sv;

    this.facets(r.facets);
    host.innerHTML = '';
    if (!r.items.length) {
      host.appendChild(el('div', 'empty',
        'Nothing matches. Try clearing a filter, or "Refresh catalogues".'));
      return;
    }
    this.render(host, r.items);
  },

  /* Group by placement slot unless the user asked for a specific order. */
  render(host, items) {
    const group = $('#f-sort').value === 'slot';
    if (!group) { items.forEach(it => host.appendChild(this.row(it))); return; }
    const by = new Map();
    for (const it of items) {
      const s = (it.placement && it.placement.slot) || 'other';
      if (!by.has(s)) by.set(s, []);
      by.get(s).push(it);
    }
    const order = S.store.slots.map(s => s.id);
    for (const [slot, list] of by) {
      if (!order.includes(slot)) order.push(slot);
    }
    for (const slot of order) {
      const list = by.get(slot);
      if (!list || !list.length) continue;
      const meta = S.store.slots.find(s => s.id === slot);
      const head = el('div', 'slot-head',
        '<span class="glyph">' + esc((meta && meta.glyph) || '•') + '</span>'
        + '<span class="nm">' + esc((meta && meta.label) || slot) + '</span>'
        + '<span class="n">' + list.length + '</span>');
      if (meta && meta.note) head.title = meta.note;
      host.appendChild(head);
      list.forEach(it => host.appendChild(this.row(it, slot)));
    }
  },

  facets(f) {
    const host = $('#store-facets');
    host.innerHTML = '';
    const block = (title, list, cur, onPick) => {
      if (!list || !list.length) return;
      host.appendChild(el('h4', '', esc(title)));
      if (cur) {
        const c = el('div', 'store-chip on',
          '<span>✕ ' + esc(cur) + '</span><span class="n">clear</span>');
        c.onclick = () => onPick('');
        host.appendChild(c);
      }
      list.slice(0, 26).forEach(x => {
        const n = el('div', 'store-chip' + (x.key === cur ? ' on' : ''),
          '<span>' + esc(x.label) + '</span><span class="n">' + x.n + '</span>');
        n.onclick = () => onPick(x.key === cur ? '' : x.key);
        host.appendChild(n);
      });
    };
    block('Repository', f.repo, $('#f-repo').value,
      v => { $('#f-repo').value = v; this.syncRepoButton(); this.fetch(); });
    block('Category', f.category, $('#f-cat').value,
      v => { $('#f-cat').value = v; this.fetch(); });
    block('Language', f.lang, $('#f-lang').value,
      v => { $('#f-lang').value = v; this.fetch(); });
    block('Subject', f.subject, $('#f-subj').value,
      v => { $('#f-subj').value = v; this.fetch(); });
    block('Licence', f.license, '', () => {});
  },

  /* Everything the user needs to decide before clicking Install. */
  row(it, slot) {
    const p = it.placement || {};
    const n = el('div', 'item' + (it.installed ? ' installed' : ''));

    const body = el('div', '');
    body.style.flex = '1';
    body.style.minWidth = '0';

    const t = el('div', 't', esc(it.title));
    body.appendChild(t);

    const m = el('div', 'm');
    m.innerHTML = '<span class="chip slot-chip" title="This module is read in '
        + esc(p.reader || '?') + ' mode, so it opens in the '
        + esc(p.slot_label || '?') + ' pane">'
        + esc(p.glyph || '') + ' ' + esc(p.slot_label || it.type) + '</span>'
      + (p.reclassified
          ? '<span class="chip fix" title="' + esc(p.reclassified_why)
            + '">filed as ' + esc(p.type_label) + ', not ' + esc(p.reclassified_from) + '</span>'
          : '')
      + '<span>' + esc(it.lang_label || it.lang) + '</span>'
      + (it.year ? '<span>' + esc(String(it.year).slice(0, 4)) + '</span>' : '')
      + (it.license ? '<span class="chip ' + liccls(it.license) + '">'
        + esc(it.license) + '</span>' : '')
      + (it.size_label ? '<span>' + esc(it.size_label) + '</span>' : '')
      + (it.format ? '<span>' + esc(it.format) + '</span>' : '')
      + (it.subjects || []).slice(0, 3).map(s =>
        '<span class="chip">' + esc(s) + '</span>').join('');
    body.appendChild(m);

    if (it.description) {
      body.appendChild(el('div', 'd', esc(String(it.description).slice(0, 240))));
    }

    /* "Already in use" -- either a duplicate of something installed, or open
       in a pane right now.  Both are things the user asked to be told. */
    const warn = el('div', 'warn-list');
    (it.duplicates || []).forEach(d => {
      const w = el('div', 'warn-line dup',
        '⚠ Already installed as <b>' + esc(d.name) + '</b> from '
        + esc(d.repo || 'another repository') + ' — installing this too gives '
        + 'you two copies in search results.');
      w.onclick = () => Workspace.openModule(d.module_id);
      warn.appendChild(w);
    });
    (it.in_use || []).forEach(u => {
      warn.appendChild(el('div', 'warn-line inuse',
        '◉ Open in the <b>' + esc(u.layout || 'workspace') + '</b> layout'
        + (u.link_set ? ' (link set ' + esc(u.link_set) + ')' : '')
        + ' — removing it will empty that pane.'));
    });
    if (warn.children.length) body.appendChild(warn);

    n.appendChild(body);

    const a = el('div', 'actions');
    if (it.installed) {
      const open = el('button', 'btn primary', 'Open');
      open.onclick = () => Workspace.openModule(it.module_id);
      a.appendChild(open);
      const rm = el('button', 'btn danger', 'Remove');
      rm.onclick = async () => {
        const inUse = (it.in_use || []).length;
        let msg = 'Remove "' + it.title + '"? Its files and index are deleted from disk.\n'
          + 'You can install it again from here at any time.';
        if (inUse) {
          msg += '\n\nIt is currently open in ' + inUse
            + ' pane(s); those panes will be cleared.';
        }
        if (!confirm(msg)) return;
        const r = await api('store/remove', { id: it.module_id });
        if (r.ok) {
          toast('Removed ' + (r.name || it.title) + ' — back in the catalogue, '
            + 'ready to reinstall.');
          await App.loadLibrary(); await App.loadWorkspace(); this.fetch();
        } else toast(r.error || 'Could not remove', 'err');
      };
      a.appendChild(rm);
    } else {
      const b = el('button', 'btn primary', 'Install');
      if ((it.duplicates || []).length) {
        b.title = 'You already have this from another repository. Installing '
          + 'again adds a second copy.';
      }
      b.onclick = () => this.doInstall(it, b);
      a.appendChild(b);
    }
    if (it.page_url) {
      const l = el('a', 'btn', 'Source');
      l.href = it.page_url; l.target = '_blank'; l.rel = 'noopener';
      a.appendChild(l);
    }
    n.appendChild(a);
    return n;
  },

  async doInstall(it, btn) {
    btn.disabled = true; btn.textContent = '…';
    const spin = $('#install-spinner');
    if (spin) spin.hidden = false;
    const r = await post('store/install', {
      repo: it.repo_id || it.repo || $('#f-repo').value, item: it.item_id });
    if (!r.ok) { toast(r.error || 'Install failed', 'err'); btn.disabled = false; btn.textContent = 'Install';
      if (spin) spin.hidden = true; return; }
    if (r.already) { toast('Already installed.'); btn.textContent = 'Installed';
      if (spin) spin.hidden = true; return; }
    const job = r.job;
    const poll = async () => {
      const j = (await api('store/job', { job: job })).job;
      if (!j) return;
      btn.textContent = j.message ? j.message.slice(0, 18) : '…';
      btn.title = j.message || '';
      if (j.state === 'done') {
        if (spin) spin.hidden = true;
        const p = (j.result && j.result.placement) || null;
        const units = (j.result && j.result.stats && j.result.stats.units) || 0;
        toast('Installed ' + it.title + ' — ' + units + ' units'
          + (p ? ', into the ' + p.slot_label + ' pane' : '') + '.');
        await App.loadLibrary(); await App.loadWorkspace();
        this._repos = null; await this.repos();
        this.fetch();
        return;
      }
      if (j.state === 'error') {
        if (spin) spin.hidden = true;
        toast(j.message, 'err'); btn.disabled = false; btn.textContent = 'Install'; return; }
      setTimeout(poll, 400);
    };
    poll();
  },
};

/* ================================================== visual filters (facets) */
/* Some platforms call this Visual Filters, and the thing worth copying is not the
 * looks but the counting: every option shows how many items you would get if
 * you ticked it, computed against all the *other* groups.  That way a zero
 * tells you the combination is impossible before you click it, and a non-zero
 * beside a ticked box tells you what widening would buy you. */
const Facets = {
  state: { type: new Set(), lang: new Set(), license: new Set(),
           format: new Set(), source: new Set(), feature: new Set() },
  sort: 'name',
  _host: null,

  GROUPS: [
    { id: 'type', label: 'Type',
      value: (m) => m.type_label || m.type || '—',
      raw: (m) => m.type || '' },
    { id: 'lang', label: 'Language',
      value: (m) => m.lang_name || m.lang || '—',
      raw: (m) => m.lang || '' },
    { id: 'license', label: 'Licence',
      value: (m) => m.license || '—',
      raw: (m) => m.license || '' },
    { id: 'format', label: 'Format',
      value: (m) => m.format || '—',
      raw: (m) => m.format || '' },
    { id: 'feature', label: 'Has',
      value: (m) => {
        if (m.has_strongs) return "Strong's tagging";
        if (m.has_xref) return 'Cross-references';
        if (m.has_notes) return 'Notes';
        if (m.has_outline) return 'Outline';
        if (m.type === 'Audio') return 'Audio';
        if (m.type === 'Grammar') return 'Grammar';
        if (m.type === 'Atlas' || m.type === 'Map') return 'Maps';
        if (m.type === 'OriginalLanguage') return 'Original language';
        return '';
      },
      raw: (m) => (m.has_strongs ? 'strongs' : m.has_xref ? 'xref' : 'notes') },
    { id: 'source', label: 'Repository',
      value: (m) => m.source_name || m.source || '—',
      raw: (m) => m.source || '' },
  ],

  SORTS: [
    ['name', 'A–Z'], ['type', 'Type'], ['size', 'Size'],
    ['units', 'Size in words'], ['lang', 'Language'],
  ],

  mount(host) {
    this._host = host;
    return host;
  },

  /* The text box and the legacy selects narrow the set before facets count,
   * so a facet count reflects what you would actually get.
   *
   * Two modes, chosen by what was typed.  Plain words are matched here, on the
   * already-loaded list, which is instant and cannot fail.  Anything with a
   * `field:value` or an AND/NOT in it is sent to the server instead, because
   * those fields -- author, publisher, series, licence, your own tags, whether
   * a Bible carries Strong's -- are not all on the module list the front end
   * holds, and a filter that silently ignored them would be worse than none.
   *
   * The set the server returns is cached against the exact query, so a facet
   * re-count after one of these does not re-ask, and backspacing to a plain
   * word returns to the local path immediately. */
  async baseSet() {
    const t = $('#l-type') ? $('#l-type').value : '';
    const lg = $('#l-lang') ? $('#l-lang').value : '';
    const src = $('#l-src') ? $('#l-src').value : '';
    const raw = ($('#l-q') && $('#l-q').value || '').trim();
    const q = raw.toLowerCase();
    const bySelect = (m) => (!t || m.type === t) && (!lg || m.lang === lg)
      && (!src || m.source === src);
    if (!q || !Facets.isQuery(raw)) {
      this._qcache = null;
      return (S.modules || []).filter(m => bySelect(m)
        && (!q || (m.name + ' ' + (m.author || '') + ' ' + (m.description || ''))
          .toLowerCase().includes(q)));
    }
    if (this._qcache && this._qcache.key === raw) return this._qcache.set;
    const r = await api('library/query', { q: raw });
    if (!r.ok) {
      // The server refused the query. Fall back to the local path rather than
      // showing nothing, and say so -- a filter that empties the list without
      // explanation reads as an empty library.
      this._qcache = null;
      toast(r.error || 'Could not run that query; filtering by name instead.',
            'warn');
      return (S.modules || []).filter(m => bySelect(m)
        && (m.name + ' ' + (m.author || '')).toLowerCase().includes(q));
    }
    /* The endpoint also matches your print shelf, whose entries have no
     * installed module behind them. They are counted here and dropped, since
     * a facet panel cannot facet a row it cannot render -- the shelf has its
     * own panel under the list. */
    const ids = new Set((r.results || [])
      .filter(x => x.kind !== 'print').map(x => x.id));
    this._qcache = { key: raw, set: (S.modules || []).filter(m =>
      bySelect(m) && ids.has(m.id)) };
    return this._qcache.set;
  },

  /* Does this look like a field query rather than a phrase to find?  A colon
   * with something either side of it, or an explicit AND/NOT.  Plain text
   * containing a colon -- "Rev 1:1" typed into the box -- must not be
   * mistaken for one, so the left side has to look like a field name. */
  isQuery(raw) {
    const s = String(raw || '');
    if (/\b(and|not|andnot)\b/i.test(s)) return true;
    return /(^|\s)[A-Za-z_][\w]{1,20}:/.test(s);
  },

  accepts(m) {
    for (const g of this.GROUPS) {
      const on = this.state[g.id];
      if (on.size && !on.has(g.raw(m))) return false;
    }
    return true;
  },

  /* Count each option against every other group, not its own: with "Bible"
   * already ticked, the Bible row must still show what is left after Bible,
   * or the count double-counts itself. */
  counts(base) {
    const out = {};
    for (const g of this.GROUPS) {
      const tally = new Map();
      for (const m of base) {
        let ok = true;
        for (const o of this.GROUPS) {
          if (o.id === g.id) continue;
          const on = this.state[o.id];
          if (on.size && !on.has(o.raw(m))) { ok = false; break; }
        }
        if (!ok) continue;
        const v = g.raw(m);
        if (!v) continue;
        tally.set(v, (tally.get(v) || 0) + 1);
      }
      out[g.id] = tally;
    }
    return out;
  },

  async refresh() {
    if (!this._host) return [];
    const base = await this.baseSet();
    const cnt = this.counts(base);
    const shown = base.filter(m => this.accepts(m));
    const host = this._host;
    host.innerHTML = '';

    const total = (S.modules || []).length;
    const head = el('div', 'facet-head');
    head.innerHTML = '<span class="caret">\u25b8</span>'
      + '<div class="fh"><span>Showing ' + shown.length
      + ' of ' + total + '</span></div>';
    if (shown.length !== total) {
      const clr = el('span', 'clr', 'clear all');
      clr.onclick = () => { this.clear(); };
      $('.fh', head).appendChild(clr);
    }
    const sortWrap = el('div', 'facet-sort');
    this.SORTS.forEach(([id, label]) => {
      const b = el('span', 's' + (this.sort === id ? ' on' : ''), label);
      b.onclick = () => { this.sort = id; Library.paint(); };
      sortWrap.appendChild(b);
    });
    head.appendChild(sortWrap);
    host.appendChild(head);

    for (const g of this.GROUPS) {
      const vals = [...cnt[g.id].keys()].sort((a, b) =>
        cnt[g.id].get(b) - cnt[g.id].get(a) || String(a).localeCompare(String(b)));
      if (!vals.length) continue;
      const box = el('div', 'facet');
      const fh = el('div', 'fh');
      fh.appendChild(el('span', '', g.label));
      if (this.state[g.id].size) {
        const c = el('span', 'clr', '×');
        c.onclick = () => { this.state[g.id].clear(); Library.paint(); };
        fh.appendChild(c);
      }
      box.appendChild(fh);
      /* The label has to come from a real module. Counting gives us the raw
       * value ("eng", "openbible-geo"), and asking the group to prettify that
       * alone lost the friendly name -- every language read as its ISO code and
       * every repository as its slug, because the prettifier looks for
       * lang_name/source_name, which a bare {lang:'eng'} does not carry. */
      const label = (v) => {
        const m = (S.modules || []).find(x => g.raw(x) === v);
        return m ? g.value(m) : String(v);
      };
      vals.slice(0, 40).forEach(v => {
        const n = cnt[g.id].get(v);
        const on = this.state[g.id].has(v);
        const row = el('div', 'facet-opt' + (on ? ' on' : '') + (n ? '' : ' zero'));
        row.appendChild(el('span', 'box'));
        row.appendChild(el('span', 'nm', esc(label(v))));
        row.appendChild(el('span', 'n', String(n)));
        row.title = label(v) + ' — ' + n + ' item' + (n === 1 ? '' : 's');
        row.onclick = () => {
          const s = this.state[g.id];
          if (s.has(v)) s.delete(v); else s.add(v);
          Library.paint();
        };
        box.appendChild(row);
      });
      host.appendChild(box);
    }
    /* The whole filter band collapses.  With a large library the groups are
     * worth having open, but the complaint that prompted all of this was being
     * unable to see the library at all, so reclaiming the height has to be one
     * click rather than a reload.  It starts closed: the groups run to 600px,
     * so opening them by default put the first module below the fold on every
     * visit.  The count and the sort stay visible either way.
     * The handlers are attached on every render, not just the first: `host`
     * is emptied above, so a handler bound once went away with its old header
     * and the caret silently stopped working after the first repaint. */
    if (!this._open) host.classList.add('collapsed');
    const onToggle = (e) => {
      e.stopPropagation();
      const closed = host.classList.toggle('collapsed');
      this._open = !closed;
      head.querySelector('.caret').textContent = closed ? '\u25b8' : '\u25be';
    };
    head.onclick = onToggle;
    head.tabIndex = 0;
    head.setAttribute('role', 'button');
    head.setAttribute('aria-expanded', String(this._open));
    head.setAttribute('aria-label', 'Show or hide the filters');
    head.onkeydown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(e); }
    };
    /* The caret shows the state the band is actually in, so reopening the pane
     * never leaves a triangle claiming filters are hidden when they are not. */
    head.querySelector('.caret').textContent =
      host.classList.contains('collapsed') ? '\u25b8' : '\u25be';
    return Library.sortInto(shown, this.sort);
  },

  clear() {
    Object.values(this.state).forEach(s => s.clear());
    Library.paint();
  },
};

/* ============================================================== Library */
const Library = {
  async load() {
    const r = await api('library');
    S.modules = r.modules;
    const ts = $('#l-type'), ls = $('#l-lang'), ss = $('#l-src');
    // The markup ships each of these with a default "All ..." option, so
    // `!ts.options.length` was false and this block never ran -- the three
    // Library filters stayed empty for good.  "More than one option" means
    // already populated.
    if (ts.options.length > 1) { this.paint(); return; }
    const addTo = (sel, pairs, fallback) => {
      const keep = sel.options[0] ? sel.options[0].text : fallback;
      sel.innerHTML = '<option value="">' + keep + '</option>'
        + pairs.map(([v, l]) => '<option value="' + esc(v) + '">'
          + esc(l) + '</option>').join('');
    };
    addTo(ts, (S.types || []).map(t => [t.id, t.label]), 'All types');
    const langs = [...new Map(S.modules.filter(m => m.lang)
      .map(m => [m.lang, m.lang_name])).entries()].sort((a, b) =>
        (a[1] || a[0]).localeCompare(b[1] || b[0]));
    addTo(ls, langs, 'All languages');
    const srcs = [...new Map(S.modules.filter(m => m.source)
      .map(m => [m.source, m.source_name || m.source])).entries()]
      .sort((a, b) => (a[1] || a[0]).localeCompare(b[1] || b[0]));
    addTo(ss, srcs, 'All sources');
    this.paint();
  },

  async paint() {
    const host = $('#library-list');
    if (!this._facetPanel) {
      this._facetPanel = Facets.mount($('#library-facets'));
    }
    /* Warn about a Bible that is missing the end of its chapters.  Asked for
     * once: this walks every chapter of every Bible and is not cheap. */
    if (!this._integrityAsked) {
      this._integrityAsked = true;
      api('library/integrity').then(r => {
        const bad = (r && r.truncated) || [];
        const abridged = (r && r.abridged) || [];
        if (!bad.length && !abridged.length) return;
        const host = $('#library-list');
        const box = el('div', 'integrity-warn');
        const n = bad.length + abridged.length;
        // `short` is a count of chapters, not text, so the one-line label is
        // built from the percentages the endpoint already reports.
        const titles = bad.map(t => esc(t.name + ' \u2014 ' + t.percent_short
                                        + '% of chapters cut short'))
          .concat(abridged.map(t => esc(t.name + ' \u2014 '
                                         + t.percent_absent + '% of chapters '
                                         + 'not included')));
        /* One line, with the detail behind a toggle.  It used to print a whole
         * paragraph per Bible, and with a long translation title that was a
         * screenful -- so the warning about your library was covering your
         * library.  The names are still there, just folded. */
        const lead = [];
        if (bad.length) {
          lead.push('<b>' + bad.length + ' truncated</b>');
        }
        if (abridged.length) {
          lead.push('<b>' + abridged.length + ' abridged edition'
            + (abridged.length === 1 ? '' : 's') + '</b>');
        }
        box.innerHTML = '<span class="iw-summary">\u26a0 ' + lead.join(', ')
          + ' \u2014 some chapters will not open</span>'
          + '<span class="iw-names">' + titles.join('; ') + '</span>'
          + '<span class="iw-toggle" role="button" tabindex="0">details</span>'
          + '<div class="iw-detail">'
          + bad.concat(abridged).map(t => '<div>' + esc(t.warning) + '</div>').join('')
          + '</div>';
        const toggle = box.querySelector('.iw-toggle');
        const flip = () => box.classList.toggle('open');
        toggle.onclick = flip;
        toggle.onkeydown = (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); }
        };
        host.parentElement.insertBefore(box, host);
      });
    }
    /* Facets.refresh() sorts what it returns, so the list and the panel are
     * always describing the same array in the same order.  It is awaited and
     * guarded by a token because baseSet() can now go to the server for a
     * field query: typing `author:calvin NOT greek` fires one request per
     * keystroke, and without a token the slower earlier reply lands last and
     * paints the list for a query you have already finished typing. */
    const token = (this._paintToken = (this._paintToken || 0) + 1);
    const rows = await Facets.refresh();
    if (token !== this._paintToken) return;
    this.paintList(rows, $('#l-detail').checked);
  },

  /* Which modules survive the current filters.  Facets owns the whole rule so
   * the panel's counts and the list can never disagree about what is showing. */
  /* In-place, so the array the facet panel counted is the array that gets
   * painted. Returns it, because Facets.refresh() hands the same one back. */
  sortInto(mods, how) {
    const name = (m) => (m.name || '').toLowerCase();
    const cmp = {
      name: (a, b) => name(a).localeCompare(name(b)),
      type: (a, b) => (a.type_label || a.type || '').localeCompare(b.type_label || b.type || '')
                       || name(a).localeCompare(name(b)),
      size: (a, b) => (b.size_bytes || 0) - (a.size_bytes || 0),
      units: (a, b) => (b.units || 0) - (a.units || 0),
      lang: (a, b) => (a.lang_name || a.lang || '').localeCompare(b.lang_name || b.lang || '')
                       || name(a).localeCompare(name(b)),
    }[how] || ((a, b) => name(a).localeCompare(name(b)));
    return mods.sort(cmp);
  },

  filtered() {
    const q = ($('#l-q').value || '').toLowerCase();
    const t = $('#l-type').value, lg = $('#l-lang').value, s = $('#l-src').value;
    return S.modules.filter(m =>
      (!t || m.type === t) && (!lg || m.lang === lg) && (!s || m.source === s)
      && (!q || (m.name + ' ' + (m.author || '') + ' ' + (m.description || ''))
        .toLowerCase().includes(q))
      && Facets.accepts(m));
  },

  paintList(mods, det) {
    const host = $('#library-list');
    host.innerHTML = '';
    $('#status').innerHTML = `${S.modules.length} installed · `
      + S.modules.reduce((a, m) => a + (m.size_bytes || 0), 0);
    if (!mods.length) {
      host.appendChild(el('div', 'empty',
        S.modules.length
          ? 'Nothing matches these filters.'
          : 'Nothing installed yet — go to the Store.'));
      return;
    }
    const groups = {};
    mods.forEach(m => { (groups[m.type_label || m.type] = groups[m.type_label || m.type] || []).push(m); });
    Object.keys(groups).sort().forEach(g => {
      host.appendChild(el('h3', '', esc(g)));
      groups[g].forEach(m => {
        const n = el('div', 'item');
        const b = el('div', ''); b.style.flex = '1'; b.style.minWidth = '0';
        b.appendChild(el('div', 't', esc(m.name)));
        b.appendChild(el('div', 'm',
          '<span>' + esc(m.lang_name || m.lang || '—') + '</span>'
          + (m.license ? '<span class="chip ' + liccls(m.license) + '">' + esc(m.license) + '</span>' : '')
          + (m.format ? '<span>' + esc(m.format) + '</span>' : '')
          + (m.size_label ? '<span>' + esc(m.size_label) + '</span>' : '')
          + (m.has_strongs ? '<span class="chip">Strong’s</span>' : '')
          + (m.has_notes ? '<span class="chip">notes</span>' : '')
          + (m.has_xref ? '<span class="chip">xrefs</span>' : '')
          + (m.units ? '<span>' + m.units.toLocaleString() + ' units</span>' : '')
          + (m.source_name ? '<span>' + esc(m.source_name) + '</span>' : '')
          + (m.error ? '<span class="err">' + esc(m.error) + '</span>' : '')));
        if (det) {
          b.appendChild(el('div', 'd', esc(m.description || '')));
          const meta = el('div', 'tiny muted');
          meta.innerHTML = 'Milestone types: ' + esc((m.index_types || []).join(', '))
            + (m.v11n ? ' · versification ' + esc(m.v11n) : '')
            + (m.rights ? ' · ' + esc(m.rights) : '');
          b.appendChild(meta);
        }
        n.appendChild(b);
        const a = el('div', 'actions');
        // Favourite and collection controls.  The favourite column has been in
        // the schema since the beginning with no way to set it, which is the
        // same as not having the feature.
        const star = el('button', 'btn star' + (m.favorite ? ' on' : ''),
                        m.favorite ? '\u2605' : '\u2606');
        star.title = m.favorite ? 'Remove from favourites' : 'Add to favourites';
        star.onclick = async (e) => {
          e.stopPropagation();
          const want = !m.favorite;
          await api('favorites', { action: 'set', id: m.id,
                                   value: want ? '1' : '0' });
          m.favorite = want;
          star.textContent = want ? '\u2605' : '\u2606';
          star.classList.toggle('on', want);
          star.title = want ? 'Remove from favourites' : 'Add to favourites';
        };
        a.appendChild(star);
        const plus = el('button', 'btn', '\uFF0B');
        plus.title = 'Add to a collection';
        plus.onclick = (e) => { e.stopPropagation(); Organise.addModuleToCollection(m.id); };
        a.appendChild(plus);
        const o = el('button', 'btn primary', 'Open');
        o.onclick = () => { Workspace.openModule(m.id); App.show('workspace'); };
        a.appendChild(o);
        if (S.links[m.id] && S.links[m.id].length) {
          const l = el('button', 'btn', 'Linkable: ' + S.links[m.id].length);
          l.title = S.links[m.id].map(x => (modById(x) || {}).name).join('\n');
          a.appendChild(l);
        }
        const r = el('button', 'btn danger', 'Remove');
        r.onclick = async () => {
          if (!confirm('Remove "' + m.name + '"?')) return;
          const x = await api('store/remove', { id: m.id });
          if (x.ok) { toast('Removed.'); await App.loadLibrary(); await App.loadWorkspace(); Library.paint(); }
        };
        a.appendChild(r);
        n.appendChild(a);
        host.appendChild(n);
      });
    });
  },

  async tags() {
    const r = await api('library/tags');
    const mine = r.tags || {};
    const tagged = Object.keys(mine);
    const names = [...new Set(tagged.flatMap(k => mine[k] || []))].sort();
    const mod = S.modules.find(m => mine[m.id]);
    modal('Tags',
      '<div class="tiny muted" style="margin-bottom:8px">Label your own '
      + 'modules. Tags are yours alone — there is no community here to share '
      + 'them with. Search for a tag with <code>mytag:to-sermon</code> in the '
      + 'Library filter box.</div>'
      + (names.length ? '<div class="tiny" style="margin-bottom:8px">'
        + 'In use: ' + names.map(t => '<span class="chip">' + esc(t)
          + '</span>').join(' ') + '</div>' : '')
      + (tagged.length ? tagged.map(id => {
          const m = modById(id);
          if (!m) return '';
          return '<div class="org-card"><div class="org-h"><b>' + esc(m.name)
            + '</b><span class="org-a">'
            + (mine[id] || []).map(t => '<span class="chip">' + esc(t)
              + '</span>').join(' ') + '</span></div>'
            + '<div class="tiny"><a href="#" data-tagmod="' + esc(id)
            + '">edit</a></div></div>';
        }).join('')
        : '<div class="empty">Nothing tagged yet.</div>')
      + '<div class="tiny muted" style="margin-top:10px">To tag something, '
      + 'use <b>Tags</b> on its row in the Library, or run '
      + '<code>mytag:name</code> to see what you already have.</div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-tagmod]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      this.tagOne(a.dataset.tagmod);
    });
  },

  async tagOne(moduleId) {
    const m = modById(moduleId);
    if (!m) return;
    const r = await api('library/tags');
    const mine = (r.tags || {})[moduleId] || [];
    modal('Tags for ' + m.name,
      '<div class="tiny muted" style="margin-bottom:8px">One tag per space '
      + 'or comma. Tags are searchable afterwards.</div>'
      + '<input id="lt-v" value="' + esc(mine.join(', ')) + '"'
      + ' placeholder="to-sermon, 2026" style="width:100%">'
      + '<div class="tiny muted" style="margin-top:8px">Clearing every tag '
      + 'removes them; the module itself is untouched.</div>', [
      { label: 'Cancel', cls: 'btn' },
      { label: 'Save', cls: 'btn primary', close: false, fn: async () => {
        const tags = $('#lt-v').value.split(/[\s,]+/).map(x => x.trim())
          .filter(Boolean);
        const res = await post('library/tags', { action: 'set',
          id: moduleId, tags });
        closeModal();
        toast(res.ok ? 'Tags saved.' : (res.error || 'Could not save.'),
              res.ok ? '' : 'err');
        if (res.ok) Library.paint();
      } }]);
  },

  /* Coverage: what is installed, and whether the files are actually there.
   *
   * "Installed" and "present" are different claims, and a module row can say
   * the first while the second is false -- which is why the column is here
   * rather than folded into the library list where it would be one more thing
   * to read past. */
  /* Your own order for your own resources.
   *
   * Two levels, because two different questions are being asked.
   *
   * The simple one is "which commentary do I read first" -- a single order over
   * the library, set by dragging or by the arrows here. It is a number on the
   * module row, and it is what the chapter guide, the passage guide and the
   * parallel stepper all fall back to.
   *
   * The advanced one is "but not here" -- put this one first *for commentary
   * lookups*, or for a book, or for a range. Those are rules rather than an
   * order, and they are consulted before the order above wherever a resource is
   * chosen for you.
   *
   * Both existed and neither was reachable, which made the chapter guide's
   * ordering alphabetical: every module sat at priority 0, so the sort fell
   * through to the module name and Adam Clarke led every list because of the A.
   */
  async prioritise() {
    const r = await api('library');
    const mods = (r.modules || []).filter(m => m.installed_at > 0);
    const rules = await api('workspace/prioritize_rules');
    const current = (rules.rules || []);

    const types = [...new Set(mods.map(m => m.type))].sort();
    const ranges = (await api('search/ranges')).ranges || [];

    /* The simple order is expressed as a running integer rather than a list
     * swap, because the server stores one number per module and a dialog that
     * shuffled those numbers on every arrow press would have to write the whole
     * library each time. */
    const ordered = mods.slice().sort((a, b) =>
      (b.priority || 0) - (a.priority || 0)
      || (a.name || '').localeCompare(b.name || ''));

    const row = (m) =>
      '<div class="org-card" data-pm="' + esc(m.id) + '">'
      + '<div class="org-h"><b>' + esc(m.name) + '</b>'
      + '<span class="muted tiny"> · ' + esc(m.type_label || m.type) + '</span>'
      + '<span class="org-a">'
      + '<a href="#" class="pm-up" title="earlier">↑</a>'
      + '<a href="#" class="pm-down" title="later">↓</a>'
      + '</span></div></div>';

    const ruleRow = (rule) => {
      const m = modById(rule.module_id);
      /* data-pmid carries the module the rule is about. Save reads it back from
       * the DOM, so every row must carry it -- including the ones loaded from
       * the server, not just the ones added in this session. Without it, saving
       * the dialog turns every pre-existing rule into one about `undefined`,
       * which the server then discards, so opening and closing the dialog would
       * quietly delete the reader's rules. */
      return '<div class="org-card" data-pmid="' + esc(rule.module_id || '') + '">'
        + '<div class="org-h"><b>' + esc(m ? m.name : rule.module_id) + '</b>'
        + '<span class="org-a"><a href="#" class="pr-x" class="danger">'
        + 'remove</a></span></div>'
        + '<div class="row wrap" style="gap:6px;margin-top:6px">'
        + '<select class="pr-type"><option value="">any resource</option>'
        + types.map(t => '<option value="' + esc(t) + '"'
          + (rule.ptype === t ? ' selected' : '') + '>' + esc(t) + '</option>')
          .join('') + '</select>'
        + '<select class="pr-range"><option value="">anywhere</option>'
        + ranges.map(x => '<option value="' + esc(x.name) + '"'
          + (rule.prange === x.name ? ' selected' : '') + '>'
          + esc(x.name) + '</option>').join('') + '</select>'
        + '<input class="pr-book" placeholder="book, e.g. Psalms"'
        + ' value="' + esc(rule.pbook || '') + '" style="width:110px">'
        + '</div><div class="tiny muted">Use this one first'
        + (rule.ptype ? ' for a ' + esc(rule.ptype) : '')
        + (rule.prange ? ' anywhere in ' + esc(rule.prange) : '')
        + (rule.pbook ? ' at ' + esc(rule.pbook) : '')
        + '. Blank parts match anything.</div></div>';
    };

    modal('Prioritise your resources',
      '<div class="tiny muted" style="margin-bottom:8px">The order below is '
      + 'yours. It decides what the chapter guide lists first, and what the '
      + 'parallel stepper reaches first.</div>'
      + '<div id="pm-list">' + ordered.map(row).join('') + '</div>'
      + '<h4 style="margin:16px 0 4px">Rules</h4>'
      + '<div class="tiny muted" style="margin-bottom:6px">A rule beats the '
      + 'order above, but only where it matches. Use it when one commentary '
      + 'should lead on Psalms and another on Romans.</div>'
      + '<div id="pm-rules">' + (current.length
          ? current.map(ruleRow).join('')
          : '<div class="tiny muted">No rules.</div>') + '</div>'
      + '<div class="org-new"><select id="pm-newmod" style="flex:1">'
      + mods.slice().sort((a, b) => (a.name || '').localeCompare(b.name || ''))
        .map(m => '<option value="' + esc(m.id) + '">' + esc(m.name)
          + '</option>').join('')
      + '</select><button class="btn" id="pm-newrule">Add a rule</button>'
      + '</div>'
      + '<div class="tiny muted" style="margin-top:10px">Both are saved to '
      + 'this machine and travel with the library in sync.</div>', [
      { label: 'Close', cls: 'btn' },
      { label: 'Save', cls: 'btn primary', close: false, fn: async () => {
        /* Write the order as a descending run of integers, so the arrows'
         * meaning survives: first row highest. Done in one pass at the end so
         * moving a row does not cost sixteen writes. */
        const cards = $$('#modal-body #pm-list .org-card');
        let value = cards.length;
        for (const c of cards) {
          await post('library/priority', { id: c.dataset.pm, value: value });
          value -= 1;
        }
        const rules = $$('#modal-body #pm-rules .org-card').map((c) => ({
          module_id: c.dataset.pmid,
          ptype: c.querySelector('.pr-type').value,
          prange: c.querySelector('.pr-range').value,
          pbook: c.querySelector('.pr-book').value.trim(),
        })).filter(x => x.module_id);
        await post('workspace/prioritize_rules', { action: 'set', rules });
        closeModal();
        await App.loadLibrary();
        toast('Order saved.');
      } }]);

    const move = (d) => (e) => {
      e.preventDefault();
      const c = e.target.closest('.org-card');
      const sib = d < 0 ? c.previousElementSibling : c.nextElementSibling;
      if (!sib) return;
      if (d < 0) c.parentElement.insertBefore(c, sib);
      else c.parentElement.insertBefore(sib, c);
    };
    $$('#modal-body .pm-up').forEach(a => a.onclick = move(-1));
    $$('#modal-body .pm-down').forEach(a => a.onclick = move(1));

    $('#pm-newrule').onclick = () => {
      const id = $('#pm-newmod').value;
      const host = $('#pm-rules');
      /* Drop the "no rules" placeholder first, or it stays above the new row. */
      if (!host.querySelector('.org-card')) host.innerHTML = '';
      const card = el('div', 'org-card');
      card.innerHTML = ruleRow({ module_id: id });
      host.appendChild(card);
    };
    $$('#modal-body .pr-x').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      e.target.closest('.org-card').remove();
    });
  },

  async coverage() {
    const r = await api('library/availability');
    const rows = r.availability || [];
    const installed = rows.filter(x => x.installed);
    const missing = installed.filter(x => x.files === 'missing');
    const moved = installed.filter(x => x.files === 'moved');
    /* "Installed", "the files are here" and "the text is still in the index"
     * are three different claims. The database travels with the project, so a
     * library whose *folder* moved still reads perfectly -- only re-indexing
     * and adding audio need the files. Saying "missing" for that would be
     * alarming and wrong, so the moved case is named as its own thing. */
    const label = { present: 'present', moved: 'moved here',
                    missing: 'missing', 'n/a': '—' };
    modal('Library coverage',
      '<div class="tiny muted" style="margin-bottom:8px">' + rows.length
      + ' module' + (rows.length === 1 ? '' : 's') + ' known · '
      + installed.length + ' installed'
      + (moved.length ? ' · <b>' + moved.length
        + ' recorded a path from an earlier location</b>, found here anyway'
        : '')
      + (missing.length ? ' · <b>' + missing.length
        + ' with no files anywhere</b>' : '') + '</div>'
      + (moved.length ? '<div class="notice">The recorded absolute paths point '
        + 'somewhere this is no longer looking. The text is in the database and '
        + 'reads normally; what is affected is re-indexing those modules and '
        + 'adding audio from them.</div>' : '')
      + '<table class="kv"><thead><tr><th>Module</th><th>Installed</th>'
      + '<th>Units</th><th>Files</th></tr></thead><tbody>'
      + rows.slice().sort((a, b) => (b.installed - a.installed)
        || ({ missing: 0, moved: 1, present: 2, 'n/a': 3 })[a.files]
        - ({ missing: 0, moved: 1, present: 2, 'n/a': 3 })[b.files]
        || (a.name || '').localeCompare(b.name || '')).map(x =>
        '<tr' + (x.installed && x.files === 'missing'
          ? ' style="color:#e0a050"' : '') + '>'
        + '<td class="tiny">' + esc(x.name) + '</td>'
        + '<td>' + (x.installed ? 'yes' : 'no') + '</td>'
        + '<td>' + Number(x.units || 0).toLocaleString() + '</td>'
        + '<td class="tiny">' + esc(label[x.files] || x.files) + '</td></tr>')
        .join('')
      + '</tbody></table>'
      + (missing.length ? '<div class="tiny muted" style="margin-top:8px">A '
        + 'module with no files can still be searched where its text is in the '
        + 'index, but re-indexing it will fail. Re-import it from the Store to '
        + 'put the files back.</div>' : ''),
      [{ label: 'Close', cls: 'btn' }]);
  },

  async attribution() {
    const r = await api('library/attribution');
    let html = '<div class="legal">Everything installed here is public domain, CC0, CC-BY or '
      + 'CC-BY-SA. Attribution is recorded per module and must be reproduced if you '
      + 'redistribute the library.</div><table class="kv">';
    (r.entries || []).forEach(e => {
      html += '<tr><td>' + esc(e.license || '') + '</td><td><b>' + esc(e.name)
        + '</b>' + (e.author ? ' — ' + esc(e.author) : '')
        + (e.rights ? '<div class="tiny muted">' + esc(e.rights) + '</div>' : '')
        + (e.source_url ? '<div class="tiny"><a href="' + esc(e.source_url)
          + '" target="_blank" rel="noopener">' + esc(e.source_name || e.source_url)
          + '</a></div>' : '') + '</td></tr>';
    });
    html += '</table>';
    modal('Attribution', html, [{ label: 'Close', cls: 'btn' }]);
  },
};

/* ================================================================= Apis */
const Apis = {
  async load() {
    const host = $('#api-list');
    host.innerHTML = '<div class="loading">Loading…</div>';
    const r = await api('apis', { category: S.api.category });
    S.api = r;
    const sm = r.summary || {};
    $('#api-summary').innerHTML =
      sm.total + ' services listed · <b>' + sm.no_key_required
      + ' need no API key</b> · ' + sm.needs_key + ' need a key · '
      + sm.keys_set + ' key' + (sm.keys_set === 1 ? '' : 's') + ' saved. '
      + 'Nothing here is required: the app works entirely offline on installed material.';
    host.innerHTML = '';
    const cats = [{ id: '', label: 'All' }].concat(
      (r.categories || []).map(c => ({ id: c, label: c })));
    const bar = el('div', 'row wrap');
    bar.style.marginBottom = '10px';
    cats.forEach(c => {
      const b = el('button', 'btn' + (S.api.category === c.id ? ' primary' : ''), c.label);
      b.onclick = () => { S.api.category = c.id; Apis.load(); };
      bar.appendChild(b);
    });
    host.appendChild(bar);
    (r.apis || []).forEach(a => host.appendChild(this.row(a)));
  },

  row(a) {
    const n = el('div', 'api');
    const b = el('div', 'body');
    b.appendChild(el('div', 'n', esc(a.name)));
    b.appendChild(el('div', 'v', esc(a.vendor)));
    if (a.notes) b.appendChild(el('div', 'no', esc(a.notes)));
    const meta = el('div', 'meta');
    const parts = [];
    if (a.key_required) {
      parts.push('<span class="chip no">Needs ' + esc(a.key_name || 'an API key')
        + (a.auth && a.auth !== 'none' ? ' (' + esc(a.auth) + ')' : '') + '</span>');
    } else {
      parts.push('<span class="chip pd">No API required</span>');
    }
    if (a.license) parts.push('<span class="chip ' + liccls(a.license) + '">'
      + esc(a.license) + '</span>');
    if (a.rate_limit) parts.push('Limit: ' + esc(a.rate_limit));
    if (a.formats) parts.push('Formats: ' + esc(a.formats));
    parts.push('<span class="chip">' + esc(a.category) + '</span>');
    meta.innerHTML = parts.join(' · ');
    b.appendChild(meta);
    const links = [];
    if (a.site_url) links.push('<a href="' + esc(a.site_url) + '" target="_blank" rel="noopener">Website</a>');
    if (a.doc_url) links.push('<a href="' + esc(a.doc_url) + '" target="_blank" rel="noopener">Docs</a>');
    if (a.base_url) links.push('<a href="' + esc(a.base_url) + '" target="_blank" rel="noopener">Endpoint</a>');
    if (a.terms_url) links.push('<a href="' + esc(a.terms_url) + '" target="_blank" rel="noopener">Terms</a>');
    if (links.length) {
      const l = el('div', 'meta'); l.innerHTML = links.join(' · '); b.appendChild(l);
    }
    n.appendChild(b);
    const r = el('div', 'right');
    if (a.key_required) {
      const inp = el('input', 'key');
      inp.type = 'password';
      inp.placeholder = a.key_set
        ? (a.key_name ? a.key_name + ' (replace)' : 'Replace key')
        : (a.key_name ? a.key_name + ' (paste key)' : 'API key');
      // The key is never sent back here, and never rendered.  `key_set` says
      // there is one; this field only ever writes a new one.  The old code
      // asked the server for the value and then put it in a `type=text` input,
      // which is somebody else's credential sitting in clear text on the page
      // where a screenshot, or any script, could read it.
      const save = el('button', 'btn', a.key_set ? 'Replace key' : 'Save key');
      save.onclick = async () => {
        if (!inp.value) { toast('Paste a key first'); return; }
        await post('apis/key', { id: a.id, key: inp.value });
        inp.value = '';
        toast('Key saved for ' + a.name);
        Apis.load();
      };
      r.append(inp, save);
      if (a.key_set) {
        r.appendChild(el('div', 'tiny muted', 'A key is stored.'));
        const clear = el('button', 'btn danger', 'Clear');
        clear.onclick = async () => {
          await post('apis/key', { id: a.id, key: '' });
          inp.value = '';
          toast('Key cleared for ' + a.name);
          Apis.load();
        };
        r.append(clear);
      }
    } else {
      r.appendChild(el('div', 'tiny muted', 'No API required'));
    }
    const t = el('button', 'btn' + (a.enabled ? ' primary' : ''),
      a.enabled ? 'Enabled' : 'Enable');
    t.onclick = async () => { await post('apis/enable', { id: a.id, enabled: !a.enabled }); Apis.load(); };
    r.appendChild(t);
    n.appendChild(r);
    return n;
  },
};

/* ====================================================== Maps & Places
 *
 * Four scanned historical maps and a gazetteer of Bible places, joined up.
 *
 * The join needs a calibration, and the calibration is the interesting part.
 * A scanned map has no coordinates: the longitude down its left edge is not
 * the longitude of anything.  So this does not place the places until somebody
 * has named two of them on the picture -- and then it asks for exactly two,
 * because two fix a scale and an angle and that is what a flat scan needs.
 *
 * The picker is a real picker rather than two coordinates to type, because the
 * whole request is "click Jerusalem on this sheet", and offering a lat/lon box
 * for it would be asking the reader to do the map's job.
 */
const MapsUI = {
  cur: null,          // the map detail as the server last sent it
  cal: null,          // being calibrated: {a:{place,x,y}, b:{...}}
  find: '',

  async load() {
    if (!MapsUI.gaz) await MapsUI.gazetteer();
    if (!MapsUI.cur) await MapsUI.list();
    await MapsUI.search();
  },

  /* The whole gazetteer, fetched once.  334 places is a small response and
   * having it here means naming a clicked point is a local lookup rather than a
   * round trip, and works on a map that has no places placed on it yet. */
  gaz: null,

  async gazetteer() {
    const r = await api('maps/places', { limit: 1000 });
    MapsUI.gaz = (r && r.places) || [];
    return MapsUI.gaz;
  },

  async findPlace(name) {
    const want = (name || '').trim().toLowerCase();
    if (!want) return null;
    if (!MapsUI.gaz) await MapsUI.gazetteer();
    /* Ambiguity is settled first, not last.  The gazetteer distinguishes some
     * places with a number -- "Mount Hor 1", "Mount Hor 2" -- and those really
     * are two places with different coordinates, so taking the first match would
     * silently calibrate the map against the wrong one and produce an overlay
     * that is wrong everywhere without looking it. */
    const exact = MapsUI.gaz.filter((p) =>
      (p.name || '').toLowerCase() === want);
    if (exact.length === 1) return exact[0];
    if (exact.length > 1) {
      toast('"' + name + '" is ' + exact.length + ' different places here — '
        + exact.map((p) => p.name).join(', ') + '. Click its label on the '
        + 'map instead.', 'warn');
      return null;
    }
    const partial = MapsUI.gaz.filter((p) =>
      (p.name || '').toLowerCase().startsWith(want));
    return partial.length === 1 ? partial[0] : null;
  },

  /* ---------------------------------------------------- the map list */
  async list() {
    const host = $('#mp-places');
    host.innerHTML = '<div class="loading">Loading maps…</div>';
    const r = await api('maps/list');
    if (!r.ok) { host.innerHTML = '<p class="muted">No maps available.</p>'; return; }
    const head = el('div', 'mp-maps');
    head.appendChild(el('h3', 'tiny muted', 'Installed maps'));
    r.maps.forEach((m) => {
      const b = el('button', 'mp-mapbtn' + (MapsUI.cur && MapsUI.cur.map.id === m.id ? ' on' : ''));
      b.appendChild(el('span', 'mp-mapname', esc(m.name)));
      const tags = el('span', 'mp-tags');
      tags.appendChild(el('span', 'mp-tag' + (m.calibrated ? ' good' : ' warn'),
        m.calibrated ? 'aligned' : 'not aligned'));
      if (!m.size) tags.appendChild(el('span', 'mp-tag bad', 'image missing'));
      tags.appendChild(el('span', 'mp-tag', (m.size ? m.size.width + '×' + m.size.height : '—')));
      b.appendChild(tags);
      b.onclick = () => MapsUI.open(m.id);
      head.appendChild(b);
    });
    host.appendChild(head);
  },

  /* ---------------------------------------------- one map, and its places */
  async open(id) {
    const stage = $('#mp-stage');
    stage.innerHTML = '<div class="loading">Loading…</div>';
    const d = await api('maps/get', { id });
    if (!d.ok) { stage.innerHTML = '<p class="muted">' + esc(d.error || 'No such map.') + '</p>'; return; }
    MapsUI.cur = d;
    MapsUI.cal = null;
    $('#mp-title').textContent = d.map.title || d.map.name;
    $('#mp-mapnote').innerHTML = d.note ? '<p class="mp-note">' + esc(d.note) + '</p>' : '';
    $('#mp-attr').innerHTML = MapsUI.attribution(d.map);
    $('#mp-badges').innerHTML = '';
    const badges = $('#mp-badges');
    badges.appendChild(el('span', 'mp-tag' + (d.calibration ? ' good' : ' warn'),
      d.calibration ? 'aligned' : 'not aligned'));
    if (d.size) {
      badges.appendChild(el('span', 'mp-tag', d.size.width + '×' + d.size.height
        + (d.size.kind ? ' ' + d.size.kind : '')));
    }
    if (d.count !== undefined) {
      badges.appendChild(el('span', 'mp-tag', d.count + ' places on this map'));
    }
    if (!d.map.url) {
      stage.innerHTML = '<p class="muted">This map\'s image is not in the library.</p>';
    } else if (d.size && d.calibration && (d.places || []).length) {
      MapsUI.paint(d);
    } else {
      const img = new Image();
      img.className = 'mp-img';
      img.src = d.map.url;
      img.alt = d.map.title || d.map.name;
      stage.innerHTML = '';
      stage.appendChild(img);
      stage.appendChild(MapsUI.calibrateBar());
      stage.onclick = null;
    }
    await MapsUI.list();
  },

  /* The image with the places on it, in a box that keeps the sheet's shape. */
  paint(d) {
    const stage = $('#mp-stage');
    stage.innerHTML = '';
    stage.onclick = null;
    const frame = el('div', 'mp-frame');
    frame.style.aspectRatio = d.size.width + ' / ' + d.size.height;
    const img = new Image();
    img.className = 'mp-img';
    img.src = d.map.url;
    img.alt = d.map.title || d.map.name;
    img.draggable = false;
    frame.appendChild(img);
    d.places.forEach((p) => {
      const dot = el('button', 'mp-dot');
      dot.style.left = (p.x / d.size.width * 100) + '%';
      dot.style.top = (p.y / d.size.height * 100) + '%';
      dot.title = p.name + (p.comment ? ' — ' + p.comment : '');
      dot.onclick = (ev) => {
        ev.stopPropagation();
        MapsUI.showPlace(p);
      };
      frame.appendChild(dot);
    });
    stage.appendChild(frame);
    stage.appendChild(MapsUI.calibrateBar());
  },

  /* ------------------------------------------------------- calibration */
  calibrateBar() {
    const bar = el('div', 'mp-calbar');
    const d = MapsUI.cur;
    if (d && d.calibration) {
      const c = d.calibration;
      bar.appendChild(el('span', 'tiny muted',
        'Aligned from ' + esc(c.a.name) + ' and ' + esc(c.b.name) + '.'));
      const reset = el('button', 'btn tiny', 'Realign');
      reset.onclick = async () => {
        await post('maps/calibrate', { id: d.map.id, clear: true });
        toast('Alignment cleared.', 'ok');
        await MapsUI.open(d.map.id);
      };
      bar.appendChild(reset);
      return bar;
    }
    /* No button without an image to click on: the calibration is two clicks on
     * the sheet, and offering it when there is no sheet is a button that cannot
     * be finished. */
    if (!d || !d.size) {
      bar.appendChild(el('span', 'tiny muted',
        'This map needs its image before places can be placed on it.'));
      return bar;
    }
    const start = el('button', 'btn primary', 'Put the places on this map');
    start.onclick = () => MapsUI.beginCalibration();
    bar.appendChild(start);
    bar.appendChild(el('span', 'tiny muted',
      'Click two places you can find on the picture.'));
    return bar;
  },

  beginCalibration() {
    const d = MapsUI.cur;
    if (!d || !d.size) return;
    MapsUI.cal = { step: 0, controls: d.controls || [], picks: [] };
    MapsUI.paintCalibration();
    toast('Click ' + (d.controls[0] ? d.controls[0].name : 'the first place')
      + ' on the map.', 'ok');
  },

  paintCalibration() {
    const d = MapsUI.cur;
    const stage = $('#mp-stage');
    stage.innerHTML = '';
    const frame = el('div', 'mp-frame picking');
    frame.style.aspectRatio = d.size.width + ' / ' + d.size.height;
    const img = new Image();
    img.className = 'mp-img';
    img.src = d.map.url;
    img.draggable = false;
    frame.appendChild(img);
    (d.places || []).forEach((p) => {
      const dot = el('button', 'mp-dot');
      dot.style.left = (p.x / d.size.width * 100) + '%';
      dot.style.top = (p.y / d.size.height * 100) + '%';
      dot.title = p.name;
      dot.onclick = (ev) => {
        ev.stopPropagation();
        MapsUI.pickAt(p.name);
      };
      frame.appendChild(dot);
    });
    MapsUI.cal.picks.forEach((pk) => {
      const dot = el('span', 'mp-pick');
      dot.style.left = (pk.x / d.size.width * 100) + '%';
      dot.style.top = (pk.y / d.size.height * 100) + '%';
      dot.title = pk.name;
      dot.textContent = pk.label;
      frame.appendChild(dot);
    });
    frame.onclick = (ev) => {
      const r = frame.getBoundingClientRect();
      /* Clicks arrive in CSS pixels, and the calibration is stored in the
       * sheet's own pixels, so the click is scaled by the ratio between what
       * is on screen and how big the sheet actually is.  Without this the
       * alignment is right for one window size and wrong for every other --
       * and it looks right on the one it was made at, which is worse. */
      const x = (ev.clientX - r.left) / r.width * d.size.width;
      const y = (ev.clientY - r.top) / r.height * d.size.height;
      MapsUI.pickAt(null, x, y);
    };
    stage.appendChild(frame);
    const bar = el('div', 'mp-calbar');
    bar.appendChild(el('span', 'tiny muted', MapsUI.promptText()));
    const cancel = el('button', 'btn tiny', 'Cancel');
    cancel.onclick = () => MapsUI.open(d.map.id);
    bar.appendChild(cancel);
    stage.appendChild(bar);
    $('#mp-mapnote').innerHTML = '';
  },

  promptText() {
    const c = MapsUI.cal;
    if (!c) return '';
    const want = c.controls[c.step];
    const wantName = want ? want.name : 'a place far from the first';
    if (c.step === 0) return 'Click ' + wantName + ' on the picture.';
    if (c.step === 1) return 'Now click ' + wantName + '.';
    return 'Two points chosen.';
  },

  /* A click either names a place -- by hitting one of the known dots -- or
   * gives raw coordinates, in which case the reader is asked which place it
   * is.  Guessing from the nearest dot would be the other obvious thing to do
   * and it is wrong: the dot is at the gazetteer's coordinate, and the label on
   * a historical sheet is often a mile from the modern fix. */
  pickAt(name, x, y) {
    const c = MapsUI.cal;
    if (!c) return;
    const want = c.controls[c.step];
    const label = String(c.step + 1);
    if (name) {
      const pl = (MapsUI.cur.places || []).find((p) => p.name === name)
        || (want && want.name === name ? want : null);
      if (pl) {
        c.picks.push({ name: pl.name, lat: pl.lat, lon: pl.lon,
          x: pl.x, y: pl.y, label });
        c.step += 1;
        return MapsUI.afterPick();
      }
    }
    if (x === undefined || y === undefined) return;
    /* A free click is only meaningful if the reader says what it is, so the
     * wanted place's own coordinates are offered as a one-tap confirmation
     * rather than a numeric box. */
    const inp = el('input', 'mp-inp');
    inp.placeholder = (want ? want.name : 'place name') + ' — name this point';
    const go = el('button', 'btn primary tiny', 'Use this point');
    go.onclick = async () => {
      const nm = inp.value.trim();
      /* Looked up in the gazetteer, not in `cur.places`.  That list is the
       * places *already projected onto this map*, so on an unaligned map --
       * which is the only time this prompt is reachable -- it is empty, and a
       * lookup against it always failed and the calibration could never be
       * completed. */
      const pl = await MapsUI.findPlace(nm);
      if (!pl) { toast('No place called ' + nm + ' in the gazetteer.', 'warn'); return; }
      c.picks.push({ name: pl.name, lat: pl.lat, lon: pl.lon, x, y, label });
      c.step += 1;
      MapsUI.afterPick();
    };
    const holder = el('div', 'mp-pickbox');
    holder.appendChild(inp);
    holder.appendChild(go);
    $('#mp-stage').appendChild(holder);
    inp.focus();
  },

  afterPick() {
    const c = MapsUI.cal;
    if (c.picks.length >= 2) return MapsUI.commit();
    MapsUI.paintCalibration();
  },

  async commit() {
    const c = MapsUI.cal;
    const d = MapsUI.cur;
    const r = await post('maps/calibrate', {
      id: d.map.id,
      a: { name: c.picks[0].name, lat: c.picks[0].lat, lon: c.picks[0].lon,
        x: c.picks[0].x, y: c.picks[0].y },
      b: { name: c.picks[1].name, lat: c.picks[1].lat, lon: c.picks[1].lon,
        x: c.picks[1].x, y: c.picks[1].y },
    });
    if (!r.ok) { toast(r.error || 'Could not align that map.', 'warn'); return; }
    toast(r.note || 'Aligned.', 'ok');
    await MapsUI.open(d.map.id);
  },

  /* ------------------------------------------------- the gazetteer side */
  async search() {
    const host = $('#mp-places');
    /* The map list is kept and the place list replaced *below* it, rather than
     * the map list being removed and re-added.  Removing it put the maps at the
     * bottom of the column, under four hundred places, so the first thing the
     * reader had to find to use the feature was last. */
    const keep = host.querySelector('.mp-maps');
    const r = await api('maps/places', { q: MapsUI.find, limit: 400 });
    if (!r.ok) return;
    const list = el('div', 'mp-list');
    list.appendChild(el('h3', 'tiny muted', esc(
      (MapsUI.find ? 'Places matching “' + MapsUI.find + '”' : 'All places')
      + ' — ' + (r.places || []).length)));
    (r.places || []).forEach((p) => list.appendChild(MapsUI.placeRow(p)));
    if (keep) host.replaceChildren(keep, list);
    else host.replaceChildren(list);
    $('#mp-count').textContent = (r.places || []).length + ' places';
  },

  placeRow(p) {
    const row = el('div', 'mp-row');
    row.appendChild(el('span', 'mp-pname', p.name));
    const meta = el('span', 'tiny muted');
    const bits = [];
    if (p.distance_km !== undefined && p.distance_km !== null) {
      bits.push(Math.round(p.distance_km) + ' km away');
    }
    bits.push(p.lat.toFixed(2) + ', ' + p.lon.toFixed(2));
    meta.textContent = bits.join(' · ');
    row.appendChild(meta);
    if (p.comment) row.appendChild(el('span', 'tiny muted', esc(p.comment)));
    const refs = el('span', 'mp-refs');
    (p.passages || []).slice(0, 4).forEach((ref) => {
      const a = el('a', 'mp-ref', esc(ref));
      a.href = '#';
      a.dataset.openref = ref;
      refs.appendChild(a);
    });
    if ((p.passages || []).length > 4) {
      refs.appendChild(el('span', 'tiny muted',
        '+' + (p.passages.length - 4) + ' more'));
    }
    row.appendChild(refs);
    return row;
  },

  async showPlace(p) {
    const host = $('#mp-places');
    const d = el('div', 'mp-pop');
    d.appendChild(el('h3', '', esc(p.name)));
    if (p.comment) d.appendChild(el('p', 'tiny muted', esc(p.comment)));
    d.appendChild(el('p', 'tiny muted',
      (p.lat != null ? p.lat.toFixed(4) : '?') + ', ' + (p.lon != null ? p.lon.toFixed(4) : '?')));
    const refs = el('div', 'mp-refs');
    (p.passages || []).forEach((ref) => {
      const a = el('a', 'mp-ref', esc(ref));
      a.href = '#';
      a.dataset.openref = ref;
      refs.appendChild(a);
    });
    d.appendChild(refs);
    const near = await api('maps/places', {
      lat: p.lat, lon: p.lon, radius_km: 25, limit: 12,
    });
    if (near.ok && (near.places || []).length > 1) {
      d.appendChild(el('h4', 'tiny muted', 'Within 25 km'));
      const ul = el('div', 'mp-near');
      near.places.forEach((n) => {
        if (n.name === p.name) return;
        const b = el('button', 'mp-nearrow');
        b.appendChild(el('span', '', esc(n.name)));
        b.appendChild(el('span', 'tiny muted',
          Math.round(n.distance_km) + ' km'));
        b.onclick = () => MapsUI.showPlace(n);
        ul.appendChild(b);
      });
      d.appendChild(ul);
    }
    host.appendChild(d);
    d.scrollIntoView({ block: 'nearest' });
  },

  /* ------------------------------------------- the modern map, by name
   *
   * The gazetteer above is the Bible's: 334 places, and Gilead, Jericho,
   * Hebron, Beersheba, Nazareth, Moab are all missing from it.  Nominatim is
   * the other kind of gazetteer -- the modern one -- and the two are kept apart
   * in the UI as well as in the response, because "Bethlehem" the modern town in
   * Judea and "Bethlehem" the modern town in Pennsylvania are both on the
   * modern map and only one is in the Bible.
   *
   * The search is bounded to the Near East by default, which is a choice the
   * reader can see and undo: Nominatim ranks by modern prominence, so an
   * unbounded search for Bethlehem returns Pennsylvania four times before Judea.
   */
  async geocode() {
    const box = $('#mp-geo-q');
    const out = $('#mp-geo-out');
    if (!box || !out) return;
    const term = (box.value || '').trim();
    if (!term) { out.innerHTML = ''; return; }
    const region = $('#mp-geo-near') && $('#mp-geo-near').checked
      ? 'near_east' : '';
    out.innerHTML = '<div class="tiny muted">Looking up…</div>';
    const r = await api('maps/geocode', { q: term, region, limit: 8 });
    if (r.error) {
      out.innerHTML = '<div class="mp-geowarn">' + esc(r.error)
        + (r.hint ? ' <span class="tiny muted">' + esc(r.hint) + '</span>' : '')
        + '</div>';
      return;
    }
    const places = r.places || [];
    let h = '<div class="tiny muted">' + esc(r.note || '') + '</div>';
    if (!places.length && region) {
      /* Nothing inside the region is a real answer for a reader who knows the
       * place exists, so offer the wider search rather than reporting an empty
       * box and leaving it there. */
      const wide = el('button', 'btn tiny', 'Search everywhere instead');
      wide.onclick = async () => {
        $('#mp-geo-near').checked = false;
        await MapsUI.geocode();
      };
      out.innerHTML = h;
      out.appendChild(wide);
      return;
    }
    h += '<div class="mp-geolist">';
    places.forEach((p) => {
      h += '<div class="mp-georow">'
        + '<button class="mp-geoname" data-geo="' + esc(p.url) + '" '
        + 'title="Show on the base map">' + esc(p.name) + '</button>'
        + '<span class="tiny muted">' + esc(p.kind || 'place') + ' · '
        + p.lat.toFixed(4) + ', ' + p.lon.toFixed(4)
        + (p.country ? ' · ' + esc(p.country) : '') + '</span>'
        + '<a class="tiny" href="' + esc(p.url)
        + '" target="_blank" rel="noopener noreferrer">OpenStreetMap ↗</a>'
        + '</div>';
    });
    h += '</div><div class="tiny muted">' + esc(r.attribution || '') + '</div>';
    out.innerHTML = h;
    $$('.mp-geoname', out).forEach((b) => {
      b.onclick = () => {
        const p = places.find((x) => x.url === b.dataset.geo);
        if (p) MapsUI.showModern(p);
      };
    });
  },

  /* A modern location on the OSM base map, with the Bible places near it.
   *
   * The neighbours come from the gazetteer in the browser, for the same reason
   * the place card does: 334 places is not worth a round trip, and "which Bible
   * places are near this modern town" is the question the reader arrived with.
   */
  showModern(p) {
    const stage = $('#mp-stage');
    if (!stage) return;
    stage.innerHTML = '';
    const host = el('div', 'atlas-map');
    stage.appendChild(host);
    /* Neighbours come from the gazetteer in the browser, for the same reason the
     * place card does: 334 places is not worth a round trip, and "which Bible
     * places are near this modern town" is the question the reader arrived with.
     * Forty kilometres and a cap, because Kiryat Ekron has 129 gazetteer places
     * within sixty and drawing all of them is a solid yellow blob with the one
     * answer in the middle of it -- which is the opposite of an answer. */
    const nearAll = (MapsUI.gaz || []).filter((b) => {
      if (!isFinite(b.lat) || !isFinite(b.lon)) return false;
      const dx = (b.lon - p.lon) * Math.cos(p.lat * Math.PI / 180);
      const dy = b.lat - p.lat;
      return Math.hypot(dx, dy) * 111 < 40;
    }).sort((a, b) => Math.hypot(a.lon - p.lon, a.lat - p.lat)
      - Math.hypot(b.lon - p.lon, b.lat - p.lat));
    const near = nearAll.slice(0, 40);
    const markers = near.map((b) => ({
      lat: b.lat, lon: b.lon, label: b.name,
      onPick: () => MapsUI.showPlace(b),
    }));
    markers.unshift({
      lat: p.lat, lon: p.lon, label: p.name, color: '#3f8f4f', onPick: () => {},
    });
    Atlas.mount(host, markers, { lat: p.lat, lon: p.lon, z: 8, height: 420 });
    $('#mp-title').textContent = p.name + ' — modern location';
    const note = el('div', 'mp-mapnote');
    note.innerHTML = '<p class="mp-note">'
      + esc(p.display || p.name)
      + (near.length ? ' · ' + near.length + ' Bible place'
        + (near.length === 1 ? '' : 's') + ' from the gazetteer within 40 km'
        + (nearAll.length > near.length ? ' of ' + nearAll.length
          + '; the nearest are marked' : '')
        + (nearAll.length === 1 ? '' : ' and yellow')
        : ' · no Bible gazetteer place within 40 km')
      + '</p><p class="tiny muted">A modern location from OpenStreetMap, not a '
      + 'biblical site: the Bible gazetteer is the list on the left. Tiles '
      + '© OpenStreetMap contributors, ODbL.</p>';
    stage.appendChild(note);
    const bar = el('div', 'mp-calbar');
    const back = el('button', 'btn', 'Back to the scanned maps');
    back.onclick = async () => {
      MapsUI.cur = null;
      await MapsUI.list();
      $('#mp-stage').innerHTML = '<p class="muted">Pick a map on the left, '
        + 'or search for a place.</p>';
      $('#mp-title').textContent = 'Choose a map';
    };
    bar.appendChild(back);
    stage.appendChild(bar);
  },

  attribution(m) {
    const bits = [];
    if (m.license) bits.push(esc(m.license));
    if (m.author) bits.push(esc(m.author));
    if (m.source) {
      bits.push('<a href="' + esc(m.source) + '" target="_blank" '
        + 'rel="noopener noreferrer">source</a>');
    }
    if (m.attribution) bits.push(esc(m.attribution));
    return bits.join(' · ');
  },
};

/* ============================================================== Grammar
 *
 * The grammar as a book: a contents list on the left, the section on the
 * right.
 *
 * It opens on the coverage report, because that is the thing a reader of a
 * grammar in this library needs before trusting it: Gesenius is 173 sections
 * here, the Wikisource index lists 351 pages and marks itself incomplete, and
 * the difference is not a half-install that re-indexing would fix -- the other
 * 178 pages are not transcribed on Wikisource at all.  Saying so first stops
 * the reader concluding that a section on some late topic is missing by
 * accident.
 *
 * The other thing this does is answer the word study's question.  A reader who
 * has clicked `HVqp3ms` wants to know what the grammar says about it, and the
 * answer is sections ranked by how much of that code they discuss -- not the
 * whole book, and not the paradigms, which contain every feature and explain
 * none.
 */
const Grammar = {
  mid: '',
  secs: null,

  /* Opened from the word study, already asking a question. */
  async openWith(code) {
    $('#g-tab').value = 'grammar';
    $('#g-term').value = '';
    Grammar.code = code || '';
    App.show('guides');
    await Grammar.load($('#g-body'));
  },

  code: '',

  async load(body) {
    const term = ($('#g-term').value || '').trim();
    const [health, sec] = await Promise.all([
      api('grammar/health'), api('grammar/sections'),
    ]);
    Grammar.mid = (sec.modules && sec.modules[0] && sec.modules[0].id) || '';
    Grammar.secs = sec.sections || [];
    if (!health.available) {
      body.innerHTML = '<div class="dash-card"><div class="dash-h">'
        + 'No grammar installed</div><p class="muted">'
        + health.notes.map(esc).join('</p><p class="muted">') + '</p></div>';
      return;
    }
    let h = '<div class="dash-card"><div class="dash-h">'
      + esc(health.modules[0].name) + '</div>';
    if (health.notes.length) {
      h += '<div class="eu-warn">'
        + health.notes.map(esc).join('</p><p>') + '</div>';
    }
    h += '<div class="tiny muted">' + health.sections.toLocaleString()
      + ' sections · ' + (health.chars / 1e6).toFixed(1) + ' MB'
      + (health.modules[0].author ? ' · ' + esc(health.modules[0].author) : '')
      + (health.modules[0].license ? ' · ' + esc(health.modules[0].license)
        : '') + '</div></div>';
    body.innerHTML = h + '<div id="gm-out"></div>'
      + '<div class="gm-side"><div class="tiny muted" id="gm-count">'
      + Grammar.secs.length + ' sections</div>'
      + '<div id="gm-list" class="gm-list"></div></div>';
    Grammar.list();
    await Grammar.show(Grammar.code ? 'morph' : (term ? 'search' : 'first'));
  },

  list() {
    const host = $('#gm-list');
    if (!host) return;
    host.innerHTML = Grammar.secs.map((s) =>
      '<button class="gm-row' + (s.empty ? ' gm-empty' : '') + '" data-k="'
      + esc(s.key) + '"><b>' + (s.number === null ? '·'
        : String(s.number).padStart(3, '0')) + '</b><span>'
      + esc(s.title || s.key) + '</span><span class="tiny muted">'
      + Math.round((s.chars || 0) / 1000) + 'k</span></button>').join('');
    $$('.gm-row', host).forEach((b) => {
      b.onclick = () => Grammar.open(b.dataset.k);
    });
  },

  async open(key) {
    const out = $('#gm-out');
    out.innerHTML = '<div class="st-loading">Loading…</div>';
    const r = await api('grammar/read', { id: Grammar.mid, key });
    if (!r.ok) { out.innerHTML = '<p class="muted">' + esc(r.error) + '</p>'; return; }
    out.innerHTML = '<div class="ph">' + esc(r.module) + ' · '
      + esc(r.title.split('/').pop()) + '</div><div class="pb">' + r.html
      + '</div><div class="pf"><span class="pc">'
      + esc((Grammar.secs.find((s) => s.key === key) || {}).chars
        + ' characters') + '</span></div>';
    $$('#gm-out a[data-k]').forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); Grammar.open(a.dataset.k); };
    });
  },

  async search() {
    const q = ($('#g-term').value || '').trim();
    const out = $('#gm-out');
    if (!q) { await Grammar.open(Grammar.secs[0].key); return; }
    out.innerHTML = '<div class="st-loading">Searching the grammar…</div>';
    const r = await api('grammar/search', { q, id: Grammar.mid, limit: 30 });
    if (!r.ok) { out.innerHTML = '<p class="muted">' + esc(r.error) + '</p>'; return; }
    let h = '<div class="tiny muted">' + esc(r.note) + ' · '
      + (r.results || []).length + ' of ' + (r.total || 0) + '</div>';
    if (!(r.results || []).length) {
      out.innerHTML = h + '<p class="muted">Nothing in the grammar for that '
        + 'term.</p>';
      return;
    }
    h += '<div class="gm-hits">';
    r.results.forEach((x) => {
      h += '<div class="gm-hit"><button class="gm-hitk" data-k="'
        + esc(x.key) + '">' + esc(x.label) + '</button>'
        + '<div class="tiny">' + x.snippet + '</div></div>';
    });
    h += '</div>';
    out.innerHTML = h;
    $$('.gm-hitk', out).forEach((b) => {
      b.onclick = () => Grammar.open(b.dataset.k);
    });
  },

  /* The word study's question, answered. */
  async morph() {
    const out = $('#gm-out');
    const code = (Grammar.code || '').trim();
    if (!code) { await Grammar.open(Grammar.secs[0].key); return; }
    out.innerHTML = '<div class="st-loading">Finding the sections…</div>';
    const r = await api('grammar/morph', { code, limit: 8 });
    if (!r.ok) { out.innerHTML = '<p class="muted">' + esc(r.error) + '</p>'; return; }
    let h = '<div class="dash-card"><div class="dash-h">' + esc(code)
      + ' in the grammar</div><div class="tiny muted">'
      + (r.features || []).map((f) => esc(f.label)).join(' · ') + '</div>';
    if (!(r.sections || []).length) {
      h += '<p class="muted">' + esc(r.note) + '</p></div>';
      out.innerHTML = h;
      return;
    }
    h += '<p class="tiny muted">' + esc(r.note) + '</p></div>';
    h += '<div class="gm-hits">';
    r.sections.forEach((s) => {
      h += '<div class="dash-card gm-morph"><div class="gm-hitk">'
        + esc(s.title) + '</div><div class="tiny muted">treats '
        + s.matched.map((m) => esc(m.label)).join(', ')
        + ' · ' + s.features + ' of ' + (r.features || []).length
        + ' features</div>';
      (s.snippets || []).forEach((sn) => {
        h += '<blockquote class="gm-snip"><span class="tiny muted">'
          + esc(sn.label) + ': </span>' + esc(sn.text) + '</blockquote>';
      });
      h += '<button class="btn tiny" data-k="' + esc(s.key) + '">Read §'
        + esc((Grammar.secs.find((x) => x.key === s.key) || {}).number
          || s.key) + '</button></div>';
    });
    h += '</div>';
    out.innerHTML = h;
    $$('[data-k]', out).forEach((b) => {
      b.onclick = () => Grammar.open(b.dataset.k);
    });
  },

  async show(which) {
    if (which === 'morph') return await Grammar.morph();
    if (which === 'search') return await Grammar.search();
    if (Grammar.secs.length) await Grammar.open(Grammar.secs[0].key);
  },
};

/* ============================================================== Media
 *
 * Images, from Openverse: one index over Flickr, Wikimedia, museums and
 * libraries, filtered to licences that permit reuse.
 *
 * This is the first feature in the application that fetches anything from a
 * service the reader has to switch on, and it is built so that fact is visible
 * rather than managed silently.  The panel asks `media/status` before it searches
 * anything; if the service is off it says so and names the screen to visit, and
 * no request is made.  The quota is small (100 a day, 5 an hour for an
 * anonymous caller) so the query is a button and not a keystroke, and answers
 * come back cached for a week.
 *
 * Attribution is not decoration here.  Every card carries the licence and the
 * credit line Openverse builds for the result, and the "copy" button puts that
 * sentence -- not the picture URL -- on the clipboard, because the sentence is
 * what a reader needs when they use the image somewhere.
 */
const Media = {
  page: 1,
  lastQuery: '',

  async load() {
    Media.status = { enabled: true };
    await Media.fillSources();
    const out0 = $('#md-out');
    if (out0) { out0.classList.remove('md-grid'); out0.style.display = 'block';
      out0.style.overflowX = 'hidden'; out0.style.overflowY = 'auto'; }
    if (Media.lastQuery) await Media.search(1);
    else {
      out0.innerHTML = '<div class="dash-card"><p class="muted">'
        + 'Biblical media only: BibleProject videos. Type a term and search.</p></div>';
    }
  },

  async fillSources() {
    const sel = $('#md-src');
    if (!sel) return;
    // Media is biblical only: BibleProject (videos).
    sel.innerHTML = '';
    const o = document.createElement('option');
    o.value = 'bibleproject';
    o.textContent = 'BibleProject (videos)';
    sel.appendChild(o);
    const lic = $('#md-lic'); if (lic) lic.style.display = 'none';
    const kind = $('#md-kind'); if (kind) kind.style.display = 'none';
  },

  /* Open the view already asking for something: a place card, a selection. */
  async openWith(term) {
    $('#md-q').value = term || '';
    App.show('media');
    await Media.load();
    if (term) await Media.search(1);
  },

  async search(page) {
    const q = ($('#md-q').value || '').trim();
    Media.lastQuery = q;
    Media.page = page || 1;
    const out = $('#md-out');
    out.classList.remove('md-grid');
    out.style.display = 'block';
    out.style.overflowX = 'hidden';
    out.style.overflowY = 'auto';
    out.innerHTML = '<div class="st-loading">Searching…</div>';
    $('#md-count').textContent = '';
    // BibleProject (videos)
    try {
      const bp = await api('bibleproject/search', { q: q || 'Bible', limit: 6 });
      if (bp && bp.ok && (bp.videos || []).length) {
        out.innerHTML = '<div class="dash-card"><div class="dash-h">BibleProject '
          + 'videos</div>'
          + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:10px 0">'
          + (bp.videos || []).map((v) => '<div>'
            + '<video controls preload="metadata" poster="' + esc(v.thumbnail || '') + '" '
            + 'src="' + esc(v.video_url) + '" style="width:100%;max-height:220px"></video>'
            + '<div class="md-title">' + esc(v.title) + '</div>'
            + '<div class="tiny muted">' + esc(v.description || '') + '</div>'
            + '<div class="tiny"><a href="' + esc(v.page_url) + '" '
            + 'target="_blank" rel="noopener noreferrer">Open on BibleProject</a></div>'
            + '</div>').join('')
          + '</div>'
          + '<div class="tiny muted" style="margin-top:6px">' + esc(bp.credit || '') + '</div>'
          + '</div>';
        $('#md-count').textContent = (bp.videos || []).length + ' videos';
        $('#md-note').textContent = 'Played from BibleProject\'s own host; '
          + 'nothing is stored here.';
      } else {
        out.innerHTML = '<div class="dash-card"><p class="muted">No videos found '
          + 'for that term.</p></div>';
        $('#md-note').textContent = (bp && bp.error) ? bp.error : '';
      }
    } catch (e) {
      out.innerHTML = '<div class="dash-card"><p class="muted">Offline: '
        + 'BibleProject needs a connection.</p></div>';
    }
  },

  cache: [],

  card(it, i) {
    Media.cache[i] = it;
    const thumb = it.thumbnail || it.url;
    /* A licence with a condition on it is marked on the card, not hidden and
     * not quietly shown as though it were CC0: a non-commercial picture used in
     * a commercial project is the mistake this line exists to prevent. */
    const cond = it.reusable ? '' :
      '<div class="md-cond">' + esc(it.withheld_reason || 'licence restricted')
      + '</div>';
    const isAudio = !!(it.duration) || /\.(mp3|ogg|wav|flac|m4a|aac)$/i.test(it.url || '');
    const preview = isAudio
      ? '<audio controls preload="none" src="' + esc(it.url) + '" style="width:100%"></audio>'
      + (it.duration ? '<div class="tiny muted">' + Math.round(it.duration) + ' s</div>' : '')
      : (thumb ? '<img loading="lazy" src="' + esc(thumb) + '" data-full="'
        + esc(it.url) + '" alt="' + esc(it.title) + '">'
        : '<div class="md-noimg">no preview</div>');
    return '<figure class="md-card' + (it.reusable ? '' : ' restricted') + '">'
      + '<a href="' + esc(it.landing_url || it.url) + '" target="_blank"'
      + ' rel="noopener noreferrer">' + preview + '</a>'
      + '<figcaption>'
      + '<div class="md-title">' + esc(it.title) + '</div>'
      + '<div class="tiny muted">' + esc(it.creator) + '</div>'
      + '<div class="md-lic">' + esc(it.license_name) + ' · '
      + esc(it.source) + '</div>' + cond
      + '<button class="btn tiny md-copy" data-i="' + i + '">Copy credit</button>'
      + '<button class="btn tiny md-slide" data-i="' + i + '">Copy to slides</button>'
      + '</figcaption></figure>';
  },

  /* A broken preview is Openverse's thumbnail proxy failing, not a missing
   * picture: it fetches the thumbnail from the source and answers 424 when the
   * source will not serve it, which two of the three Masoretic results did.  So
   * the card falls back to the source's own image, and to a written placeholder
   * if even that fails -- a card with a broken-image icon in it reads as a dead
   * link and the picture is very much there.
   */
  wirePreviews(host) {
    $$('.md-card img', host).forEach((img) => {
      img.onerror = () => {
        if (img.dataset.full && img.getAttribute('src') !== img.dataset.full) {
          img.src = img.dataset.full;
          return;
        }
        img.replaceWith(el('div', 'md-noimg',
          'preview unavailable — open the source'));
      };
    });
  },
};

/* ====================================================== Quotations
 *
 * Short lines out of the books you have installed, on a word you name.
 *
 * This is extractive, and says so: it finds units under 300 characters that
 * mention the term and ranks the briefest first.  It is not a database of
 * things Spurgeon said.  Nothing is matched against who wrote a line, and no
 * quotation is trimmed to make it fit -- the whole unit is shown or nothing
 * is, so a quotation can always be found and checked in its source. */
