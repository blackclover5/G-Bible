const Flows = {
  current: '',
  slots: [],
  steps: [],

  async load() {
    const host = $('#wf-body');
    if (!host) return;
    const r = await api('workflow');
    const s = await api('workflow', { action: 'slots' });
    this.slots = (s.slots || []).filter(x => x.installed > 0);
    if (!host) return;
    const list = (r.workflows || []);
    $('#wf-side').innerHTML = list.length
      ? list.map(w => '<div class="item' + (w.id === this.current ? ' on' : '')
        + '" data-id="' + esc(w.id) + '"><span>' + esc(w.name) + '</span>'
        + '<span class="n">' + w.steps + '</span></div>').join('')
        + '<div class="tiny muted" style="padding:6px 8px">'
        + '<button class="btn" id="wf-cap">Save this workspace as a workflow</button>'
        + '<button class="btn" id="wf-lib">Start from a template</button>'
        + '</div>'
      : '<div class="empty tiny">No workflows yet.</div>'
        + '<div class="tiny muted" style="padding:6px 8px">'
        + '<button class="btn" id="wf-cap">Save this workspace</button>'
        + '<button class="btn" id="wf-lib">Start from a template</button></div>';
    const cap = $('#wf-cap');
    if (cap) cap.onclick = () => this.capture();
    const lib = $('#wf-lib');
    if (lib) lib.onclick = () => this.library();
    $$('#wf-side .item').forEach(x => {
      x.onclick = () => { this.current = x.dataset.id; this.load(); };
    });
    if (!list.length) {
      host.innerHTML = '<div class="empty">A workflow is a layout with a '
        + 'sequence: "read this, then look up this word, then open the outline '
        + 'here".<br><br>Open the panes you use and press <b>Save this '
        + 'workspace</b> to start from them.</div>';
      return;
    }
    if (!this.current || !list.some(w => w.id === this.current)) {
      this.current = list[0].id;
    }
    await this.open(this.current);
  },

  /* The template library: five starting points.
   *
   * Installing one gives you an ordinary workflow you can then edit, rather
   * than a special mode -- there is no second kind of workflow here, and a
   * template that could not be changed after installing would be a demo
   * rather than a starting point. */
  async library() {
    const r = await api('workflows/library');
    const tpls = r.workflows || [];
    modal('Workflow templates',
      '<div class="tiny muted" style="margin-bottom:8px">A sequence of '
      + 'steps, not a layout: each one says what to open or look up, and every '
      + 'step is editable afterwards.</div>'
      + tpls.map(t => '<div class="dash-card"><div class="dash-h">'
        + esc(t.name) + '</div>'
        + '<div class="tiny muted" style="margin-bottom:6px">' + esc(t.note)
        + '</div>'
        + '<ol class="st-points">' + (t.steps || []).map(s =>
            '<li>' + esc(s.note || s.kind) + '</li>').join('') + '</ol>'
        + '<button class="btn primary" data-wfl="' + esc(t.name)
        + '">Install this</button></div>').join(''),
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-wfl]').forEach(b => b.onclick = async () => {
      const res = await post('workflows/library', { action: 'install',
        name: b.dataset.wfl });
      closeModal();
      if (!res.ok) { toast(res.error || 'Could not install that.', 'err'); return; }
      const made = res.workflow || res;
      this.current = made.id || '';
      this.load();
      toast('Installed "' + b.dataset.wfl + '".');
    });
  },

  async open(id) {
    const host = $('#wf-body');
    host.innerHTML = '<div class="empty">Loading…</div>';
    const r = await api('workflow', { action: 'get', id });
    if (!r.ok || !r.workflow) {
      host.innerHTML = '<div class="warn">' + esc(r.error || 'gone') + '</div>';
      return;
    }
    this.wf = r.workflow;
    this.steps = (r.workflow.steps || []).map(s => ({ ...s }));
    this.paint(host, r.workflow);
  },

  paint(host, wf) {
    let h = '<div class="wl-bar">'
      + '<b style="font-size:14px">' + esc(wf.name) + '</b>'
      + '<input type="text" id="wf-name" value="' + esc(wf.name) + '" style="width:170px">'
      + '<input type="search" id="wf-ref" placeholder="starts at, e.g. John 3" value="'
        + esc(wf.ref || '') + '" style="width:150px">'
      + '<button class="btn primary" id="wf-save">Save</button>'
      + '<button class="btn" id="wf-run">Run it here</button>'
      + '<button class="btn" id="wf-add">Add a step</button>'
      + '<button class="btn danger" id="wf-del">Delete</button>'
      + '</div>';
    if (wf.note) h += '<div class="tiny muted" style="padding:0 8px 8px">'
      + esc(wf.note) + '</div>';
    this.steps.forEach((s, i) => {
      const mod = s.module_id ? modById(s.module_id) : null;
      h += '<div class="wf-step"><span class="ix">' + (i + 1) + '</span>'
        + '<span class="what"><b>' + esc(s.kind === 'search'
            ? 'Search' : (s.kind === 'outline' ? 'Outline' : 'Open')) + '</b> '
          + (s.kind === 'search'
              ? esc(s.query || '(no query)')
              : (mod ? esc(mod.name)
                     : esc((this.slots.find(x => x.id === s.slot) || {}).label
                           || s.module_id || 'nothing chosen')))
          + '<div class="sub">' + esc(s.note || s.kind) + '</div></span>'
        + '<select data-kind="' + i + '">' + ['open', 'search', 'outline']
            .map(k => '<option value="' + k + '"' + (s.kind === k ? ' selected' : '')
              + '>' + k + '</option>').join('') + '</select>'
        + '<select data-pick="' + i + '"><option value="">choose…</option>'
        + '<optgroup label="By role">'
        + this.slots.map(x => '<option value="slot:' + esc(x.id) + '"'
            + (s.slot === x.id && !s.module_id ? ' selected' : '') + '>'
            + esc(x.label) + ' (' + x.installed + ')</option>').join('')
        + '</optgroup><optgroup label="Installed">'
        + S.modules.filter(m => m.reader !== 'verse' || true).map(m =>
            '<option value="mod:' + esc(m.id) + '"'
            + (s.module_id === m.id ? ' selected' : '') + '>'
            + esc(m.name) + '</option>').join('')
        + '</optgroup></select>'
        + '<input data-q="' + i + '" placeholder="query" value="'
          + esc(s.query || '') + '" style="width:120px">'
        + '<button class="btn" data-up="' + i + '" title="Move up">↑</button>'
        + '<button class="btn" data-rm="' + i + '" title="Remove">✕</button>'
        + '</div>';
    });
    h += '<div class="tiny muted" style="padding:8px">A step that names a role '
      + 'rather than a book keeps working when you run it on a different passage; '
      + 'one that names a book always opens that book.</div>';
    host.innerHTML = h;
    this.wire(host, wf);
  },

  wire(host, wf) {
    const save = async () => {
      const r = await post('workflow', { action: 'save', id: wf.id,
        name: $('#wf-name', host).value, ref: $('#wf-ref', host).value,
        note: wf.note, layout_id: wf.layout_id, steps: this.steps });
      if (!r.ok) { toast(r.error || 'Could not save.', 'err'); return; }
      toast('Workflow saved.');
      await this.load();
    };
    $('#wf-save', host).onclick = save;
    $('#wf-run', host).onclick = () => this.run(wf.id,
      $('#wf-ref', host).value || wf.ref || '');
    $('#wf-add', host).onclick = () => {
      this.steps.push({ kind: 'open', module_id: '', slot: 'bible',
                        cursor: {}, options: {}, text_size: 100 });
      this.paint(host, wf);
    };
    $('#wf-del', host).onclick = async () => {
      if (!confirm('Delete "' + wf.name + '"?')) return;
      await api('workflow', { action: 'delete', id: wf.id });
      this.current = '';
      this.load();
    };
    $$('[data-kind]', host).forEach(x => {
      x.onchange = () => { this.steps[+x.dataset.kind].kind = x.value;
        this.paint(host, wf); };
    });
    $$('[data-pick]', host).forEach(x => {
      x.onchange = () => {
        const s = this.steps[+x.dataset.pick];
        const v = x.value;
        if (v.startsWith('slot:')) { s.slot = v.slice(5); s.module_id = ''; }
        else { s.module_id = v.slice(4); s.slot = ''; }
        this.paint(host, wf);
      };
    });
    $$('[data-q]', host).forEach(x => {
      x.onchange = () => { this.steps[+x.dataset.q].query = x.value; };
    });
    $$('[data-up]', host).forEach(x => {
      x.onclick = () => {
        const i = +x.dataset.up;
        if (!i) return;
        const t = this.steps[i - 1];
        this.steps[i - 1] = this.steps[i];
        this.steps[i] = t;
        this.paint(host, wf);
      };
    });
    $$('[data-rm]', host).forEach(x => {
      x.onclick = () => { this.steps.splice(+x.dataset.rm, 1); this.paint(host, wf); };
    });
  },

  async capture() {
    const name = prompt('Name this workflow',
      'Workflow: ' + ((S.layout && S.layout.name) || 'workspace'));
    if (!name) return;
    const r = await api('workflow', { action: 'capture', name });
    if (!r.ok) { toast(r.error || 'Could not save that.', 'err'); return; }
    toast('Captured ' + r.steps.length + ' panes.');
    App.show('workflows');
    this.current = r.id;
    await this.load();
  },

  /* Open the panes.  A step that cannot be honoured costs a pane, not the flow,
   * and the skipped ones are named at the end so it is clear what did not run. */
  async run(id, ref) {
    const r = await api('workflow', { action: 'run', id, ref });
    if (!r.ok) { toast(r.error || 'gone', 'err'); return; }
    App.show('workspace');
    let opened = 0;
    for (const step of r.steps) {
      if (step.action === 'skip') continue;
      if (step.action === 'search') {
        App.show('search');
        $('#sq').value = step.query || '';
        $('#s-go').click();
        opened++;
        continue;
      }
      if (step.action === 'outline') {
        Outlines.book = (step.cursor || {}).book || 'Gen';
        Outlines.chapter = (step.cursor || {}).chapter || 1;
        App.show('guides');
        $('#g-tab').value = 'outline';
        opened++;
        continue;
      }
      const m = modById(step.module_id);
      if (!m) continue;
      await Workspace.openModule(step.module_id,
        step.cursor && Object.keys(step.cursor).length ? step.cursor
          : { ref: r.ref }, { text_size: step.text_size,
                              link_set: step.link_set });
      opened++;
    }
    const skipped = r.skipped || [];
    toast(opened + ' opened'
      + (skipped.length ? ' · ' + skipped.length + ' step'
          + (skipped.length === 1 ? '' : 's') + ' skipped (nothing installed)'
          : '') + '.', skipped.length ? 'warn' : '');
  },
};

/* ============================================================ translation ===
   Machine-translate a set of hits, or a passage.

   There were forty-five APIs registered and every one of them switched off, with
   no feature anywhere that used them.  This is that feature, and it is the only
   thing in the app that sends text off the machine -- so it says so on the
   button that does it, in the dialog it opens, and in the panel it draws.

   The panel never claims more than it has.  A translation that came back
   unchanged is marked as such, because a panel showing the original text under
   a heading that says "Spanish" is worse than no panel.  And the disclaimer is
   above the results, not in a footnote nobody opens: machine translation of
   scripture is for finding your way, not for quoting.                        */