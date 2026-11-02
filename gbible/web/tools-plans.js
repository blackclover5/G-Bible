const Plans = {
  GROUPS: [
    ['today', 'Due today', 'A plan with an unread day waiting for you.'],
    ['anytime', 'Anytime', 'Self-paced: no schedule attached.'],
    ['later', 'Later', 'Started, or not yet due.'],
    ['archived', 'Archived', 'Finished, or put away deliberately.'],
  ],

  async load() {
    const main = $('#pl-main');
    main.innerHTML = '<div class="st-loading">Loading…</div>';
    const r = await api('plans/manager');
    if (!r.ok) { main.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    const g = r.groups || {};
    const total = this.GROUPS.reduce((n, gr) => n + (g[gr[0]] || []).length, 0);
    $('#plans-summary').textContent = total + ' plan'
      + (total === 1 ? '' : 's') + ' · day numbers, not dates — day 0 is the '
      + 'first day you have not marked';
    $('#pl-side').innerHTML = this.GROUPS.map(gr =>
      '<div class="org-card"><div class="org-h"><b>' + esc(gr[1]) + '</b>'
      + '<span class="muted tiny"> · ' + ((g[gr[0]] || []).length)
      + '</span></div><div class="tiny muted">' + esc(gr[2]) + '</div></div>')
      .join('');
    if (!total) {
      main.innerHTML = '<div class="empty">No reading plans yet. One is '
        + 'offered on the Today screen when a devotional is installed.</div>';
      return;
    }
    main.innerHTML = this.GROUPS.map(([k, label]) => {
      const rows = g[k] || [];
      if (!rows.length) return '';
      return '<div class="dash-card"><div class="dash-h">' + esc(label)
        + ' <span class="muted">· ' + rows.length + '</span></div>'
        + rows.map(p => '<div class="org-card"><div class="org-h"><b>'
          + esc(p.title || p.name || p.id) + '</b>'
          + (p.next_day ? '<span class="muted tiny"> · day ' + p.next_day
            + '</span>' : '')
          + (p.minutes ? '<span class="muted tiny"> · ~' + p.minutes
            + ' min</span>' : '')
          + (p.pace ? '<span class="muted tiny"> · ' + esc(p.pace) + '</span>' : '')
          + '<span class="org-a">'
          + '<a href="#" data-plgo="' + esc(p.id) + '">read</a>'
          + '<a href="#" data-plpace="' + esc(p.id) + '">pace</a>'
          + (k === 'today' ? '<a href="#" data-plskip="' + esc(p.id)
            + '">skip to latest</a>' : '')
          + (k === 'archived' ? '<a href="#" data-plarch="' + esc(p.id)
            + '" data-arch="0">restore</a>'
            : '<a href="#" data-plarch="' + esc(p.id) + '" data-arch="1"'
            + ' class="danger">archive</a>')
          + (p.kind === 'custom'
            ? '<a href="#" data-pldelete="' + esc(p.id)
            + '" class="danger">delete</a>'
            : '')
          + '</span></div></div>').join('') + '</div>';
    }).join('');
    main.querySelectorAll('[data-plgo]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      Dashboard.showPlanDay(a.dataset.plgo, 0);
    });
    main.querySelectorAll('[data-plpace]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      this.pace(a.dataset.plpace);
    });
    main.querySelectorAll('[data-plskip]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const s = await post('plans/manager', { action: 'skip', plan: a.dataset.plskip });
      if (!s.ok) { toast(s.error || 'Could not skip.', 'err'); return; }
      toast('Skipped ' + s.skipped + ' day' + (s.skipped === 1 ? '' : 's')
        + ' — now at day ' + s.day + '.');
      this.load();
    });
    main.querySelectorAll('[data-plarch]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      /* data-arch carries the *destination* state rather than being inferred
       * from the link's text, so the same handler archives and restores
       * correctly and neither direction depends on being in a named group. */
      const to = a.dataset.arch !== '0';
      await post('plans/manager', { action: 'archive', plan: a.dataset.plarch,
        archived: to });
      this.load();
    });
    main.querySelectorAll('[data-pldelete]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      if (!confirm('Delete this custom reading plan? Progress will also be removed.')) return;
      const r = await post('readingplan/delete', { name: a.dataset.pldelete });
      if (!r.ok) { toast(r.error || 'Could not delete.', 'err'); return; }
      toast('Deleted ' + r.name + '.');
      this.load();
    });
  },

  /* A pace is one of four things, and inferring which from a free-text box
   * produces plans that quietly lie about when they are due.  All four are
   * spelled out before one is accepted. */
  pace(planId) {
    modal('Pace', '<div class="st-body">A pace decides whether this plan shows '
      + 'a day waiting for you or sits in <i>Anytime</i>.</div>'
      + '<div class="org-new" style="margin-top:8px">'
      + '<input id="pl-pv" placeholder="15min, finish:2026-12-31, or open"'
      + ' style="flex:1">'
      + '<button class="btn primary" id="pl-psave">Set</button>'
      + '<button class="btn" id="pl-pclear" title="Back to scheduled">Clear</button>'
      + '</div>'
      + '<div class="tiny muted"><b>15min</b> — a daily goal, shown on the '
      + 'Today screen.<br><b>finish:2026-12-31</b> — spread over a date.<br>'
      + '<b>open</b> — self-paced, no schedule.<br><b>Clear</b> — back to '
      + 'scheduled.</div>', [{ label: 'Close', cls: 'btn' }]);
    $('#pl-psave').onclick = async () => {
      await post('plans/manager', { action: 'pace', plan: planId,
        pace: $('#pl-pv').value.trim() });
      closeModal(); this.load();
    };
    $('#pl-pclear').onclick = async () => {
      await post('plans/manager', { action: 'pace', plan: planId, pace: '' });
      closeModal(); this.load();
    };
  },

  exportJSON() {
    api('plans/manager', { action: 'export' }).then((r) => {
      const text = JSON.stringify({ progress: r.progress || {},
        paces: r.paces || {} }, null, 2);
      modal('Reading plan progress',
        '<div class="tiny muted" style="margin-bottom:6px">Copy this into the '
        + 'Import box on another machine. Progress and paces only — the plans '
        + 'themselves are built from your installed material, so copying these '
        + 'across copies no text.</div>'
        + '<textarea class="st-text" id="pl-exp" rows="14" style="width:100%">'
        + esc(text) + '</textarea>', [
        { label: 'Close', cls: 'btn' },
        { label: 'Copy', cls: 'btn primary', close: false, fn: async () => {
          await Clipboard.write(text);
        } }]);
    });
  },

  importJSON() {
    modal('Import reading plan progress',
      '<div class="tiny muted" style="margin-bottom:6px">Paste what the Export '
      + 'button gave you. Progress you already have is kept; the pasted values '
      + 'win where the two disagree.</div>'
      + '<textarea class="st-text" id="pl-imp" rows="14" style="width:100%"></textarea>',
      [{ label: 'Close', cls: 'btn' },
       { label: 'Import', cls: 'btn primary', close: false, fn: async () => {
         let payload;
         try { payload = JSON.parse($('#pl-imp').value || '{}'); }
         catch (err) { toast('That is not JSON.', 'err'); return; }
         const r = await post('plans/manager', { action: 'import', payload });
         closeModal();
         toast(r.ok ? 'Imported ' + (r.plans || 0) + ' plan(s).'
           : (r.error || 'Failed.'), r.ok ? '' : 'err');
         Plans.load();
       } }]);
  },

  /* A custom reading plan: the reader's own passage sequence, saved by name.
   * The passages are entered one per line, in the order they should be read.
   * Progress is kept the same way as every other plan -- day numbers, not
   * dates -- so a custom plan resumes after a gap like the rest. */
  newPlan() {
    modal('New reading plan',
      '<div class="tiny muted" style="margin-bottom:8px">Enter one passage '
      + 'per line, in the order you want to read them. Each line becomes '
      + 'one day of the plan.</div>'
      + '<div class="org-new" style="margin-bottom:8px">'
      + '<input id="rp-name" placeholder="Plan name" style="flex:1">'
      + '</div>'
      + '<textarea id="rp-refs" rows="12" style="width:100%" '
      + 'placeholder="Genesis 1&#10;Genesis 2&#10;Genesis 3&#10;..."></textarea>'
      + '<div class="tiny muted" style="margin-top:6px">Or paste a list of '
      + 'references separated by commas or semicolons.</div>',
      [{ label: 'Cancel', cls: 'btn' },
       { label: 'Create', cls: 'btn primary', close: false, fn: async () => {
         const name = ($('#rp-name').value || '').trim();
         if (!name) { toast('Name the plan.', 'warn'); return; }
         const raw = $('#rp-refs').value || '';
         const refs = raw.split(/[\n,;]+/).map(s => s.trim())
           .filter(Boolean);
         if (!refs.length) { toast('Add at least one passage.', 'warn'); return; }
         const r = await post('readingplan/create', { name, refs });
         if (!r.ok) { toast(r.error || 'Could not create.', 'err'); return; }
         closeModal();
         toast('Plan "' + name + '" created — ' + r.days + ' days.');
         this.load();
       } }]);
  },

  lectionary() {
    api('plans/manager', { action: 'lectionary' }).then((r) => {
      const rows = r.readings || [];
      modal('The built-in lectionary',
        '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.note) + ' '
        + r.weeks + ' weeks.</div>'
        + '<div class="org-items" style="max-height:56vh;overflow:auto">'
        + rows.map(x => '<span class="org-item"><a href="#">' + esc(x.ref)
          + '</a></span>').join('') + '</div>',
        [{ label: 'Close', cls: 'btn' }]);
      $$('#modal-body .org-item a').forEach(a => a.onclick = (e) => {
        e.preventDefault();
        closeModal();
        App.show('workspace');
        Reader.openRefAnywhere(a.textContent);
      });
    });
  },
};

/* ============================================================= Prayer
 *
 * A prayer note is a note with a next-due date, and the date comes from the
 * template's frequency rather than a number typed into each prayer.  So
 * "daily" and "weekly" are properties of the template, and changing one
 * changes every prayer that uses it. */