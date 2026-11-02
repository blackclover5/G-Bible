const SermonFinder = {
  async load(body) {
    const ref = ($('#g-ref') || {}).value || '';
    const query = ref.trim();
    body.innerHTML = '<div class="dash-card"><div class="dash-h">Sermons'
      + '</div><div class="tiny muted" style="margin-bottom:8px">Points from '
      + 'installed sermon works that bear on a passage.</div>'
      + '<div class="st-tools" style="gap:6px">'
      + '<input id="sm-ref" value="' + esc(query) + '" placeholder="e.g. John 3"'
      + ' style="width:140px">'
      + '<button class="btn primary" id="sm-go">Find</button>'
      + '</div><div id="sm-out"></div></div>';
    const go = () => { const gr = $('#g-ref'); if (gr) gr.value = $('#sm-ref').value; this.run(body); };
    $('#sm-go').onclick = go;
    $('#sm-ref').onkeydown = (e) => { if (e.key === 'Enter') go(); };
    if (query) this.run(body);
    else $('#sm-out').innerHTML = '<div class="empty tiny">Type a passage.</div>';
  },

  async run(body) {
    const ref = ($('#sm-ref').value || '').trim();
    const out = $('#sm-out');
    if (!ref) { out.innerHTML = '<div class="empty">Type a passage.</div>'; return; }
    out.innerHTML = '<div class="st-loading">Looking…</div>';
    const r = await api('preach/outlines', { ref });
    if (!r.ok) { out.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    const items = r.items || [];
    if (!items.length) {
      out.innerHTML = '<div class="empty">' + esc(r.note || 'Nothing found.')
        + '</div>';
      return;
    }
    out.innerHTML = items.map((s, i) =>
      '<div class="dash-card"><div class="dash-h">' + esc(s.module) + '</div>'
      + '<div class="st-t">' + esc(s.title) + '</div>'
      + '<ul class="st-points">' + (s.points || []).map(p => '<li>' + esc(p)
        + '</li>').join('') + '</ul>'
      + '<div class="row" style="gap:6px">'
      + '<button class="btn tiny" data-smnote="' + i + '">Start a sermon note</button>'
      + '<button class="btn tiny" data-smopen="' + i + '">Open the work</button>'
      + '</div></div>').join('')
      + '<div class="tiny muted">' + esc(r.note || '') + '</div>';
    out.querySelectorAll('[data-smopen]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      const s = items[+a.dataset.smopen];
      App.show('workspace');
      Workspace.openModule(s.module_id, {});
    });
    out.querySelectorAll('[data-smnote]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const s = items[+a.dataset.smnote];
      await post('notes/save', { kind: 'sermon', title: s.title, ref_label: ref,
        module_id: s.module_id,
        body: (s.points || []).map(p => '- ' + p).join('\n')
          + '\n\n— ' + s.module + '\n\nSource: ' + s.module });
      App.show('notes');
      toast('Started a sermon note from these points.');
    });
  },
};

/* ==================================================== Sermon Builder
 *
 * A structured sermon note: introduction, points, illustrations, conclusion
 * and delivery notes.  The outline comes from installed sermon works; the
 * structure is the reader's own.  Nothing is composed or invented. */
const SermonBuilder = {
  _noteId: '',

  async load(body) {
    body.innerHTML = '<div class="st-loading">Loading…</div>';
    /* If there is a note id in the URL, load that; otherwise start fresh. */
    const params = new URLSearchParams(window.location.search);
    const noteId = params.get('note') || '';
    if (noteId) {
      const r = await api('sermon', { action: 'builder_get', id: noteId });
      if (r.ok) { this._noteId = noteId; this._render(body, r); return; }
    }
    this._noteId = '';
    this._render(body, {
      title: '', ref_label: '', outline: [], introduction: '',
      points: [], illustrations: [], conclusion: '', delivery: '',
      series: '', scheduled: '',
    });
  },

  _render(body, d) {
    const field = (id, label, val, placeholder) =>
      '<div class="org-card"><div class="org-h"><b>' + label + '</b></div>'
      + '<textarea id="' + id + '" rows="3" style="width:100%" '
      + 'placeholder="' + esc(placeholder || '') + '">'
      + esc(val || '') + '</textarea></div>';
    body.innerHTML =
      '<div class="row" style="gap:6px;margin-bottom:8px">'
      + '<button class="btn" id="sb-back">← Sermons</button>'
      + '<input id="sb-title" placeholder="Sermon title" value="'
      + esc(d.title || '') + '" style="flex:1">'
      + '<input id="sb-ref" placeholder="Passage (e.g. John 3:16)" value="'
      + esc(d.ref_label || '') + '" style="width:180px">'
      + '</div>'
      + '<div class="row" style="gap:6px;margin-bottom:8px">'
      + '<input id="sb-series" placeholder="Series name" value="'
      + esc(d.series || '') + '" style="flex:1">'
      + '<input id="sb-scheduled" placeholder="Scheduled date (YYYY-MM-DD)"'
      + ' value="' + esc(d.scheduled || '') + '" style="width:180px">'
      + '</div>'
      + '<div class="org-card" id="sb-research">'
      + '<div class="org-h"><b>Research</b><span class="org-a">'
      + '<button class="btn tiny" id="sb-r-outline">outline ideas</button>'
      + '<button class="btn tiny" id="sb-r-illustration">illustrations</button>'
      + '<button class="btn tiny" id="sb-r-exposition">exposition notes</button>'
      + '</span></div>'
      + '<div class="tiny muted">The assistant reads the passage, your '
      + 'commentaries and any installed sermon works, and returns sourced notes. '
      + 'It does not write the sermon — that part is yours.</div>'
      + '<div id="sb-ai-out"></div></div>'
      + field('sb-intro', 'Introduction', d.introduction,
        'How will you open? What question does this passage raise?')
      + '<div class="org-card"><div class="org-h"><b>Points</b>'
      + '<span class="org-a"><button class="btn tiny" id="sb-add-point">'
      + 'add point</button></span></div>'
      + '<div id="sb-points">'
      + (d.points || []).map((p, i) => this._pointRow(p, i)).join('')
      + '</div></div>'
      + field('sb-illus', 'Illustrations', (d.illustrations || []).join('\n'),
        'Stories, examples, quotes -- one per line')
      + field('sb-conc', 'Conclusion', d.conclusion,
        'How will you close? What is the response you are asking for?')
      + field('sb-delivery', 'Delivery notes', d.delivery,
        'Timing, emphasis, transitions, slides needed')
      + '<div class="row" style="gap:6px;margin-top:10px">'
      + '<button class="btn primary" id="sb-save">Save sermon</button>'
      + '<button class="btn" id="sb-export">Export slides</button>'
      + '<button class="btn" id="sb-export-handout">Export handout</button>'
      + '<button class="btn" id="sb-export-pptx">Export PPTX</button>'
      + (this._noteId ? '<button class="btn danger" id="sb-delete">Delete</button>' : '')
      + '</div>';
    this._wire(body);
    const back = body.querySelector('#sb-back');
    if (back) back.onclick = () => { history.pushState(null, '', window.location.pathname); $('#sm-tab').value = 'sermon-manager'; SermonHub.load(); };
  },

  _pointRow(text, i) {
    return '<div class="row" style="gap:6px;margin-bottom:4px">'
      + '<input class="sb-point" data-idx="' + i + '" value="'
      + esc(text || '') + '" style="flex:1" placeholder="Point ' + (i + 1) + '">'
      + '<button class="btn tiny" data-sbdel="' + i + '">remove</button>'
      + '</div>';
  },

  _wire(body) {
    const research = (kind) => async () => {
      const ref = ($('#sb-ref').value || '').trim();
      if (!ref) { toast('Enter the passage first.', 'warn'); return; }
      await Ai.ensure();
      const blocked = Ai.blocked && Ai.blocked();
      if (blocked) { toast(blocked, 'warn'); return; }
      const out = $('#sb-ai-out');
      out.innerHTML = '<div class="tiny muted" style="margin-top:6px">Researching '
        + esc(ref) + '…</div>';
      let text = '';
      let cites = [];
      await Ai.streamTo({
        action: kind, ref, theme: ($('#sb-title').value || '').trim(),
      }, {
        onSources: (ev) => { cites = ev.citations || []; },
        onDelta: (t) => {
          text += t;
          out.innerHTML = '<div style="margin-top:6px;line-height:1.55">'
            + Ai.render(text) + '</div>';
        },
        onError: (err, hint) => {
          out.innerHTML = '<div class="warn" style="margin-top:6px">'
            + esc((err || 'Research failed.') + (hint ? ' ' + hint : ''))
            + '</div>';
        },
        onFinally: () => {
          if (!text) return;
          // Citations render through the assistant's own list, so a chip opens
          // the passage here exactly as it does in the chat panel.
          if (cites.length) out.appendChild(Ai.sourceList(cites));
          const target = kind === 'illustration' ? 'illustrations' : 'points';
          const add = el('button', 'btn tiny', 'Add to ' + target);
          add.style.marginTop = '6px';
          add.title = 'Adds the list-shaped lines to your sermon. Edit them '
            + 'there — they are research, not your manuscript.';
          add.onclick = () => this._adopt(target, text, body);
          out.appendChild(add);
        },
      });
    };
    const ro = $('#sb-r-outline');
    if (ro) ro.onclick = research('outline');
    const ri = $('#sb-r-illustration');
    if (ri) ri.onclick = research('illustration');
    const re = $('#sb-r-exposition');
    if (re) re.onclick = research('exposition');

    $('#sb-add-point').onclick = () => {
      const pts = this._getPoints();
      pts.push('');
      this._render(body, this._gather(body, pts));
    };
    body.querySelectorAll('[data-sbdel]').forEach(b => b.onclick = () => {
      const pts = this._getPoints();
      pts.splice(+b.dataset.sbdel, 1);
      this._render(body, this._gather(body, pts));
    });
    $('#sb-save').onclick = async () => {
      const structure = this._gather(body);
      const title = structure.title || 'Untitled sermon';
      const ref = structure.ref_label || '';
      if (!this._noteId) {
        const r = await post('notes/save', { kind: 'sermon', title, ref_label: ref });
        if (!r.ok) { toast(r.error || 'Could not save.', 'err'); return; }
        /* `notes/save` returns the note nested under `note`, not at the top
         * level.  Reading `r.id` gave undefined, so every subsequent save
         * posted an empty id and the server answered "No such sermon note" --
         * the note was created and then nothing was ever written to it. */
        this._noteId = (r.note && r.note.id) || r.id || '';
        if (!this._noteId) { toast('Could not create the note.', 'err'); return; }
      }
      const r = await post('sermon', { action: 'builder_save', id: this._noteId, structure });
      if (!r.ok) { toast(r.error || 'Could not save.', 'err'); return; }
      toast('Sermon saved.');
    };
    $('#sb-export').onclick = () => this._export('slides');
    $('#sb-export-handout').onclick = () => this._export('handout');
    const pptxBtn = $('#sb-export-pptx');
    if (pptxBtn) pptxBtn.onclick = () => {
      if (!this._noteId) { toast('Save the sermon first.', 'warn'); return; }
      const url = '/file/sermon-pptx?id=' + encodeURIComponent(this._noteId);
      Cite._save(url, 'sermon.pptx');
    };
    const del = $('#sb-delete');
    if (del) del.onclick = async () => {
      if (!this._noteId) return;
      await post('notes/delete', { id: this._noteId });
      this._noteId = '';
      toast('Sermon deleted.');
      this.load(body);
    };
  },

  _getPoints() {
    return Array.from(document.querySelectorAll('.sb-point'))
      .map(n => n.value.trim()).filter(Boolean);
  },

  /* Take the list-shaped lines the model produced and put them where they
   * belong: the reader's own fields, which they then edit.
   *
   * Two deliberate limits.  Only lines that read as a heading or a bullet are
   * taken -- a paragraph is refused -- so a model that ignored the "short
   * headings, not prose" instruction cannot smuggle a sermon in through this
   * button.  And nothing is re-rendered: the research stays on screen beside the
   * fields it was added to, because the citations are the point of having run it
   * and wiping them the moment they are used would make the numbers meaningless.
   */
  _adopt(target, text, body) {
    const lines = (text || '').split('\n')
      .map(s => s.trim())
      .filter(Boolean)
      .map(s => s.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, '').trim())
      .filter(s => s && s.length <= 160)
      // A full sentence is not an outline point, however the model labelled it.
      .filter(s => !(s.endsWith('.') && s.split(/\s+/).length > 8));
    if (!lines.length) {
      toast('Nothing list-shaped to add.', 'warn');
      return;
    }
    if (target === 'illustrations') {
      const ta = $('#sb-illus');
      const cur = (ta.value || '').replace(/\s*$/, '');
      ta.value = (cur ? cur + '\n' : '') + lines.join('\n');
    } else {
      const wrap = $('#sb-points');
      const start = wrap.querySelectorAll('.sb-point').length;
      lines.forEach((l, k) => {
        const row = document.createElement('div');
        row.innerHTML = this._pointRow(l, start + k);
        wrap.appendChild(row);
      });
      // New rows arrive with unwired remove buttons; the counterpart of the
      // ones `_wire` connected, so they behave the same.
      wrap.querySelectorAll('[data-sbdel]').forEach(b => b.onclick = () => {
        const pts = this._getPoints();
        pts.splice(+b.dataset.sbdel, 1);
        this._render(body, this._gather(body, pts));
      });
    }
    toast('Added ' + lines.length + ' line' + (lines.length === 1 ? '' : 's')
          + ' — edit them to make them yours.');
  },

  _gather(body, points) {
    return {
      title: $('#sb-title').value.trim(),
      ref_label: $('#sb-ref').value.trim(),
      series: $('#sb-series').value.trim(),
      scheduled: $('#sb-scheduled').value.trim(),
      introduction: $('#sb-intro').value.trim(),
      points: points || this._getPoints(),
      illustrations: ($('#sb-illus').value || '').split('\n').map(s => s.trim()).filter(Boolean),
      conclusion: $('#sb-conc').value.trim(),
      delivery: $('#sb-delivery').value.trim(),
    };
  },

  async _export(kind) {
    if (!this._noteId) { toast('Save the sermon first.', 'warn'); return; }
    const r = await api('sermon', { action: 'export', id: this._noteId, kind });
    if (!r.ok) { toast(r.error || 'Could not export.', 'err'); return; }
    const blob = new Blob([r.html], { type: 'text/html' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'sermon.' + (kind === 'slides' ? 'slides' : 'handout') + '.html';
    a.click();
  },
};

/* ==================================================== Sermon Manager
 *
 * All sermon notes with their status, series and schedule.  The view is a
 * table: what is drafted, what is scheduled, what series it belongs to. */
const SermonManager = {
  async load(body) {
    body.innerHTML = '<div class="st-loading">Loading…</div>';
    const r = await api('sermon', { action: 'manager' });
    if (!r.ok) { body.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    const sermons = r.sermons || [];
    const counts = r.counts || {};
    const series = r.series || [];
    let h = '<div class="row" style="gap:10px;margin-bottom:10px">'
      + '<div class="dash-card" style="flex:1"><div class="dash-h">'
      + (counts.total || 0) + ' sermons</div><div class="tiny muted">'
      + (counts.scheduled || 0) + ' scheduled · '
      + (counts.draft || 0) + ' draft · '
      + (counts.empty || 0) + ' empty</div></div>'
      + (series.length ? '<div class="dash-card" style="flex:1"><div class="dash-h">'
        + series.length + ' series</div><div class="tiny muted">'
        + esc(series.join(', ')) + '</div></div>' : '')
      + '</div>';
    h += '<div class="row" style="margin-bottom:10px">'
      + '<button class="btn" id="sm-import">Import sermon…</button>'
      + '<button class="btn" id="sm-find-toggle">Find sermon material</button>'
      + '<span class="tiny muted">Manage your sermons or research installed sermon works.</span>'
      + '</div><div id="sm-find-panel" style="display:none;margin-bottom:10px"></div>';
    if (!sermons.length) {
      h += '<div class="empty">No sermons yet. Start one in the Sermon '
        + 'Sermon Editor, or import one above.</div>';
      body.innerHTML = h;
      this.wireImport(body);
      this.wireFinder(body);
      return;
    }
    h += '<div class="org-items" style="max-height:60vh;overflow:auto">'
      + sermons.map(s =>
          '<div class="org-card"><div class="org-h"><b>'
        + esc(s.title) + '</b>'
        + (s.scheduled ? '<span class="muted tiny"> · ' + esc(s.scheduled) + '</span>' : '')
        + '<span class="org-a">'
        + '<a href="#" data-smedit="' + esc(s.id) + '">edit</a>'
        + (s.scheduled
          ? '<a href="#" data-smunsched="' + esc(s.id) + '">unschedule</a>'
          : '<a href="#" data-smsched="' + esc(s.id) + '">schedule</a>')
        + '<a href="#" data-smexport="' + esc(s.id) + '">export</a>'
        + '</span></div>'
        + '<div class="tiny muted">'
        + (s.ref_label ? esc(s.ref_label) + ' · ' : '')
        + (s.series ? 'series: ' + esc(s.series) + ' · ' : '')
        + esc(s.status)
        + (s.points_count ? ' · ' + s.points_count + ' points' : '')
        + (s.outline_count ? ' · ' + s.outline_count + ' outline items' : '')
        + '</div></div>').join('')
      + '</div>';
    body.innerHTML = h;
    this.wireImport(body);
    this.wireFinder(body);
    body.querySelectorAll('[data-smedit]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      history.pushState(null, '', '?note=' + encodeURIComponent(a.dataset.smedit));
      $('#sm-tab').value = 'sermon-editor';
      App.show('sermon-manager');
    });
    body.querySelectorAll('[data-smsched]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const date = prompt('Date (YYYY-MM-DD):');
      if (!date) return;
      await post('sermon', { action: 'schedule', date, id: a.dataset.smsched });
      this.load(body);
    });
    body.querySelectorAll('[data-smunsched]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      await post('sermon', { action: 'schedule', date: '', id: a.dataset.smunsched });
      this.load(body);
    });
    body.querySelectorAll('[data-smexport]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const r = await api('sermon', { action: 'export', id: a.dataset.smexport, kind: 'slides' });
      if (!r.ok) { toast(r.error || 'Could not export.', 'err'); return; }
      const blob = new Blob([r.html], { type: 'text/html' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'sermon.slides.html';
      link.click();
    });
  },
  wireFinder(body) {
    const btn = body.querySelector('#sm-find-toggle');
    const panel = body.querySelector('#sm-find-panel');
    if (!btn || !panel) return;
    btn.onclick = async () => {
      const opening = panel.style.display === 'none';
      panel.style.display = opening ? '' : 'none';
      if (opening) await SermonFinder.load(panel);
    };
  },
  wireImport(body) {
    const btn = body.querySelector('#sm-import');
    if (!btn) return;
    btn.onclick = async () => {
      const title = prompt('Title (leave blank to use first line):') || '';
      const text = prompt('Paste the sermon text:');
      if (!text) return;
      const series = prompt('Series (optional):') || '';
      const r = await post('sermon', { action: 'import', text, title, series });
      if (!r || !r.ok) { toast((r && r.error) || 'Import failed.', 'err'); return; }
      toast('Imported: ' + (r.title || ''), 'ok');
      this.load(body);
    };
  },
};


/* ===================================================== Sermon Manager hub
 * The Tools entry owns both sermon workflows; Guides remains focused on study. */
const SermonHub = {
  async load() {
    const tab = ($('#sm-tab') || {}).value || 'sermon-manager';
    const body = $('#sm-body');
    if (!body) return;
    body.innerHTML = '<div class="st-loading">Loading…</div>';
    if (tab === 'sermon-editor') return SermonBuilder.load(body);
    if (tab === 'sermons') return SermonManager.load(body);
    return this.loadHome(body);
  },
  async loadHome(body) {
    const r = await api('sermon', { action: 'manager' });
    if (!r.ok) { body.innerHTML = '<div class="warn">' + esc(r.error || 'Could not load Sermon Manager.') + '</div>'; return; }
    const counts = r.counts || {};
    const series = r.series || [];
    body.innerHTML = '<div class="row" style="gap:10px;flex-wrap:wrap;margin-bottom:14px">'
      + '<div class="dash-card" style="flex:1;min-width:150px"><div class="dash-h">' + (counts.total || 0) + ' sermons</div><div class="tiny muted">Your sermon library</div></div>'
      + '<div class="dash-card" style="flex:1;min-width:150px"><div class="dash-h">' + (counts.draft || 0) + ' drafts</div><div class="tiny muted">In progress</div></div>'
      + '<div class="dash-card" style="flex:1;min-width:150px"><div class="dash-h">' + (counts.scheduled || 0) + ' scheduled</div><div class="tiny muted">On your calendar</div></div>'
      + (series.length ? '<div class="dash-card" style="flex:1;min-width:150px"><div class="dash-h">' + series.length + ' series</div><div class="tiny muted">' + esc(series.join(', ')) + '</div></div>' : '')
      + '</div>'
      + '<div class="dash-card" style="margin-bottom:12px"><h3 style="margin-top:0">Welcome to Sermon Manager</h3>'
      + '<p class="muted">Your home for organizing sermons, tracking drafts and schedules, and preparing your next message.</p>'
      + '<div class="row" style="gap:8px;flex-wrap:wrap">'
      + '<button class="btn primary" id="sm-home-sermons">Open Sermons</button>'
      + '<button class="btn" id="sm-home-editor">Open Sermon Editor</button>'
      + '</div></div>'
      + '<div class="tiny muted">Use the menu above to switch between Sermon Manager, Sermons, and Sermon Editor. You can return here at any time by selecting Sermon Manager.</div>';
    const sermonsBtn = body.querySelector('#sm-home-sermons');
    const editorBtn = body.querySelector('#sm-home-editor');
    if (sermonsBtn) sermonsBtn.onclick = () => { $('#sm-tab').value = 'sermons'; this.load(); };
    if (editorBtn) editorBtn.onclick = () => { history.pushState(null, '', window.location.pathname); $('#sm-tab').value = 'sermon-editor'; this.load(); };
  },
};

/* ======================================================= Reading plans
 *
 * Every plan, grouped by what it is asking of you: a day waiting, no
 * schedule, not yet due, or put away.  The grouping is read from the stored
 * pace and the archived list, so a plan moves between sections by changing
 * one control here rather than by being re-created and losing its history. */