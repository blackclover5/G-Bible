const Clippings = {
  _id: '',

  async load() {
    const side = $('#cl-side');
    const main = $('#cl-main');
    main.innerHTML = '<div class="st-loading">Loading…</div>';
    const r = await api('clipping');
    const rows = r.clippings || [];
    if (!this._id || !rows.some(x => x.id === this._id)) {
      this._id = rows.length ? rows[0].id : '';
    }
    side.innerHTML = rows.length ? rows.map(c =>
      '<div class="org-card"><div class="org-h"><b>' + esc(c.heading) + '</b>'
      + '<span class="muted tiny"> · ' + ((c.items || []).length)
      + '</span></div></div>').join('')
      : '<div class="empty tiny">No clips yet.</div>';
    side.querySelectorAll('.org-card').forEach((card, i) => {
      card.onclick = () => { this._id = rows[i].id; this.load(); };
      if (rows[i].id === this._id) card.classList.add('on');
    });
    const cur = rows.find(x => x.id === this._id);
    if (!cur) {
      main.innerHTML = '<div class="empty">A clip gathers excerpts. Select '
        + 'text in a pane and choose <b>Clip this selection</b>, or press '
        + '<b>New clip</b> to start one.</div>';
      return;
    }
    const q = ($('#cl-q').value || '').trim().toLowerCase();
    const all = cur.items || [];
    const items = all.filter(i => !q || (i.quote || '').toLowerCase().includes(q)
      || (i.source || '').toLowerCase().includes(q) || (i.ref || '').toLowerCase().includes(q));
    let h = '<div class="dash-card"><div class="dash-h">'
      + '<input id="cl-head" value="' + esc(cur.heading) + '"'
      + ' style="background:transparent;border:0;font:inherit;font-weight:600;'
      + 'color:inherit;flex:1;min-width:120px">'
      + '<span class="org-a"><a href="#" id="cl-rename">save name</a>'
      + '<a href="#" id="cl-citeall" title="Copy every excerpt with its source">copy all</a>'
      + '<a href="#" id="cl-del" class="danger">delete clip</a></span></div>';
    if (!items.length) {
      h += '<div class="empty">'
        + (all.length ? 'Nothing here matches that filter.' : 'Empty.') + '</div>';
    } else {
      h += items.map((i, n) => '<div class="st-note"><div class="st-body">'
        + esc(i.quote) + '</div>'
        + '<div class="tiny muted">— ' + esc(i.source || 'unknown source')
        + (i.ref ? ' · ' + esc(i.ref) : '') + '</div>'
        + '<div class="row" style="gap:6px;margin-top:4px">'
        + '<button class="btn tiny" data-clcopy="' + n + '">Copy</button>'
        + (i.module_id ? '<button class="btn tiny" data-clopen="' + n
          + '">Open</button>' : '')
        + '<button class="btn tiny" data-clnote="' + n + '">To notes</button>'
        + '<button class="btn tiny danger" data-clrm="' + esc(i.id)
        + '" title="Remove this excerpt">×</button>'
        + '</div></div>').join('');
    }
    h += '<div class="tiny muted" style="margin-top:8px">A clip holds the '
      + 'excerpt itself, so it keeps working after the resource it came from '
      + 'is removed.</div>';
    main.innerHTML = h + '</div>';
    $('#cl-rename').onclick = async (e) => {
      e.preventDefault();
      await post('clipping', { action: 'save', id: cur.id,
        heading: $('#cl-head').value });
      toast('Renamed.');
    };
    $('#cl-del').onclick = async (e) => {
      e.preventDefault();
      if (!confirm('Delete "' + cur.heading + '"?')) return;
      await post('clipping', { action: 'delete', id: cur.id });
      this._id = '';
      this.load();
    };
    $('#cl-citeall').onclick = async () => {
      await Clipboard.write([cur.heading, ''].concat(items.map(i =>
        i.quote + '\n— ' + [i.source, i.ref].filter(Boolean).join(', ')))
        .join('\n\n'));
    };
    main.querySelectorAll('[data-clrm]').forEach(b => b.onclick = async (e) => {
      e.preventDefault();
      await post('clipping', { action: 'remove', id: cur.id, item: b.dataset.clrm });
      this.load();
    });
    main.querySelectorAll('[data-clcopy]').forEach(b => b.onclick = async (e) => {
      e.preventDefault();
      const i = items[+b.dataset.clcopy];
      await Clipboard.write(i.quote + '\n\n— '
        + [i.source, i.ref].filter(Boolean).join(', '));
    });
    main.querySelectorAll('[data-clopen]').forEach(b => b.onclick = (e) => {
      e.preventDefault();
      const i = items[+b.dataset.clopen];
      App.show('workspace');
      Workspace.openModule(i.module_id, i.unit_key ? { key: i.unit_key } : {});
    });
    main.querySelectorAll('[data-clnote]').forEach(b => b.onclick = async (e) => {
      e.preventDefault();
      const i = items[+b.dataset.clnote];
      await post('notes/save', { kind: 'note', title: cur.heading,
        body: '> ' + i.quote.split('\n').join('\n> ') + '\n\n— '
          + [i.source, i.ref].filter(Boolean).join(', ') });
      toast('Saved as a note.');
    });
  },

  /* Called from the selection card.  Makes a clipping if there is none,
   * because a clipping you must create before you may use one is a clipping
   * most people never make. */
  async capture(quote, moduleId, ref, unitKey) {
    if (!quote || !quote.trim()) return;
    const r = await api('clipping');
    const rows = r.clippings || [];
    let cid = rows.length ? await this.pick(rows) : '';
    if (cid === null) return;
    if (!cid) {
      const heading = prompt('Name the new clip', ref || quote.slice(0, 40));
      if (!heading) return;
      const made = await post('clipping', { action: 'save', heading });
      cid = made.clipping ? made.clipping.id : '';
    }
    if (!cid) return;
    await post('clipping', { action: 'add', id: cid, quote, module: moduleId,
      ref, key: unitKey });
    this._id = cid;
    toast('Added to the clip.');
  },

  /* Resolves to a clipping id, '' for "make a new one", or null for cancel.
   * The Escape and backdrop paths resolve null too: leaving the promise
   * unsettled would leave the caller awaiting a dialog that is already gone. */
  pick(rows) {
    return new Promise((resolve) => {
      let settled = false;
      const done = (v) => { if (!settled) { settled = true; resolve(v); } };
      modal('Add to a clip',
        rows.map(c => '<div class="store-list"><div class="item">'
          + '<a href="#" data-pick="' + esc(c.id) + '"><b>' + esc(c.heading)
          + '</b></a><span class="m">' + ((c.items || []).length)
          + ' excerpts</span></div></div>').join('')
        + '<div class="org-new"><input id="cl-pick-new"'
        + ' placeholder="Or name a new clip" style="flex:1">'
        + '<button class="btn primary" id="cl-pick-add">Create</button></div>',
        [{ label: 'Cancel', cls: 'btn', fn: () => done(null) }]);
      _modalCleanup = () => done(null);
      $$('#modal-body [data-pick]').forEach(a => a.onclick = (e) => {
        e.preventDefault();
        const id = a.dataset.pick;
        done(id);
        closeModal();
      });
      $('#cl-pick-add').onclick = () => {
        const heading = $('#cl-pick-new').value.trim();
        done(heading ? { heading } : null);
        closeModal();
      };
    }).then(async (choice) => {
      if (choice && typeof choice === 'object') {
        const made = await post('clipping', { action: 'save',
          heading: choice.heading });
        return made.clipping ? made.clipping.id : '';
      }
      return choice;
    });
  },
};

/* ================================================================= bind */