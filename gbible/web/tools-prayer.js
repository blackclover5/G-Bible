const Prayer = {
  _tpl: '',

  async load() {
    const side = $('#pt-side');
    const main = $('#pt-main');
    main.innerHTML = '<div class="st-loading">Loading…</div>';
    const [t, due] = await Promise.all([
      api('prayer/template'), api('prayer/template', { action: 'due' })]);
    const tpls = t.templates || [];
    const items = due.items || [];
    const again = items.filter(p => p.overdue).length;
    $('#prayer-summary').textContent = tpls.length + ' template'
      + (tpls.length === 1 ? '' : 's') + ' · ' + items.length + ' prayer'
      + (items.length === 1 ? '' : 's') + (again ? ' · ' + again + ' due again' : '');
    if (!this._tpl || !tpls.some(x => x.id === this._tpl)) {
      this._tpl = tpls.length ? tpls[0].id : '';
    }
    side.innerHTML = (tpls.length ? tpls.map(x => {
      const freq = x.frequency_days || 1;
      const freqLabel = freq === 0 ? 'manual' : ('every ' + freq + ' day' + (freq === 1 ? '' : 's'));
      return '<div class="org-card"><div class="org-h"><b>' + esc(x.name) + '</b>'
        + '<span class="muted tiny"> · ' + freqLabel + '</span></div></div>';
    }).join('') : '<div class="empty tiny">No templates.</div>')
      + '<div class="org-new" style="margin-top:8px">'
      + '<button class="btn" id="pt-new">New Template</button></div>';
    side.querySelectorAll('.org-card').forEach((card, i) => {
      card.onclick = () => { this._tpl = tpls[i].id; this.load(); };
      if (tpls[i].id === this._tpl) card.classList.add('on');
    });
    const newBtn = side.querySelector('#pt-new');
    if (newBtn) newBtn.onclick = async () => {
      const r = await post('prayer/template', { action: 'save', id: '',
        name: 'New Template', body: '', frequency_days: 0 });
      if (r.ok) { this._tpl = r.template.id; this.load(); }
      else toast(r.error || 'Could not create template.', 'err');
    };
    const cur = tpls.find(x => x.id === this._tpl);
    let h = '<div class="dash-card"><div class="dash-h">'
      + esc(cur ? cur.name : 'No template') + '</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">The body becomes a '
      + 'new prayer each time you use it, so it is a starting point rather '
      + 'than something to write afresh each morning.</div>'
      + '<div class="org-new" style="flex-wrap:wrap">'
      + '<input id="pt-name" placeholder="name" value="'
      + esc(cur ? cur.name : '') + '" style="width:130px">'
      + '<input id="pt-freq" type="number" min="0" max="365" value="'
      + (cur ? cur.frequency_days : 1) + '" style="width:70px"'
      + ' title="Days between repetitions (0 = manual only)">'
      + '<button class="btn primary" id="pt-save">Save</button>'
      + '<button class="btn" id="pt-use">Use this template</button>'
      + (cur ? '<button class="btn danger" id="pt-delete" style="margin-left:8px">Delete</button>' : '')
      + '</div>'
      + '<textarea class="st-text" id="pt-body" rows="7"'
      + ' style="width:100%;margin-top:8px" placeholder="- one line per petition">'
      + esc(cur ? (cur.body || '') : '') + '</textarea></div>';
    h += '<div class="dash-card"><div class="dash-h">Due'
      + ' <span class="muted">· ' + items.length + '</span></div>';
    if (!items.length) {
      h += '<div class="empty">No prayer notes yet. Open <b>Notes</b>, choose '
        + '<b>Prayer</b> in the kind list, and write one.</div>';
    } else {
      h += items.map(p => {
        const days = Math.round((p.due_at - Date.now() / 1000) / 86400);
        return '<div class="org-card"><div class="org-h"><b>'
          + esc(p.title || '(untitled)') + '</b>'
          + '<span class="muted tiny"> · ' + (p.overdue ? 'due again'
            : 'again in ' + Math.max(0, days) + ' day' + (days === 1 ? '' : 's'))
          + '</span>'
          + '<span class="org-a"><a href="#" data-prnote="' + esc(p.id)
          + '">open</a></span></div></div>';
      }).join('');
    }
    h += '</div>';
    main.innerHTML = h;
    $('#pt-save').onclick = async () => {
      const r = await post('prayer/template', { action: 'save', id: this._tpl,
        name: $('#pt-name').value, body: $('#pt-body').value,
        frequency_days: $('#pt-freq').value });
      toast(r.ok ? 'Saved.' : (r.error || 'Could not save.'), r.ok ? '' : 'err');
      if (r.ok) this.load();
    };
    $('#pt-use').onclick = async () => {
      const body = $('#pt-body').value.trim();
      if (!body) { toast('The template has no body yet.', 'warn'); return; }
      const name = prompt('Name this prayer', $('#pt-name').value || 'Prayer');
      if (!name) return;
      await post('notes/save', { kind: 'prayer', title: name, body,
        meta: { template: this._tpl,
                frequency_days: cur ? (cur.frequency_days || 1) : 1 } });
      App.show('notes');
      toast('Prayer added.');
    };
    main.querySelectorAll('[data-prnote]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      App.show('notes');
      Notes.edit(a.dataset.prnote);
    });
    const del = $('#pt-delete');
    if (del) del.onclick = async () => {
      if (!confirm('Delete this prayer template?')) return;
      const r = await post('prayer/template', { action: 'delete', id: this._tpl });
      toast(r.ok ? 'Deleted.' : (r.error || 'Could not delete.'), r.ok ? '' : 'err');
      if (r.ok) { this._tpl = ''; this.load(); }
    };
  },
};

/* ========================================================= Clippings
 *
 * A clipping is a folder of excerpts.  Unlike a notebook it keeps the text
 * itself, so it still reads after the module it came from is removed — which
 * is the whole point of clipping something rather than only bookmarking it. */