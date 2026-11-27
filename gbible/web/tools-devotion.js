/* Devotional creator: pick a Bible or chaptered book, choose a date range,
 * and G-Bible builds the daily portions into a real devotion module.
 *
 * The rules it follows are kept server-side (gbible/devotion_creator.py):
 * Bibles are chapter-atomic, everything is sentence-safe, days are weighed
 * by word count, and the result is keyed MM.DD so it behaves like any other
 * installed devotional on the Today screen. */

const DevotionCreator = {
  books: [],
  _bound: false,
  _suggestedTitle: '',

  iso(d) {
    const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  },

  addMonths(d, months) {
    const day = d.getDate();
    const out = new Date(d.getFullYear(), d.getMonth() + months, 1);
    const last = new Date(out.getFullYear(), out.getMonth() + 1, 0).getDate();
    out.setDate(Math.min(day, last));
    return out;
  },

  weekdayList() {
    return $$('#dc-days .dc-day.on').map(b => Number(b.dataset.w));
  },

  params() {
    return {
      module_id: $('#dc-book').value,
      scope: $('#dc-scope').value,
      start: $('#dc-start').value,
      finish: $('#dc-finish').value,
      title: ($('#dc-title') || {}).value || '',
      weekdays: this.weekdayList(),
    };
  },

  async load() {
    if (!this._bound) this.bind();
    const r = await api('devotion/books');
    if (!r || r.ok === false) {
      $('#dc-estimate').textContent = 'Could not load books: '
        + ((r && r.error) || 'unknown error');
      return;
    }
    const sel = $('#dc-book');
    this.books = r.books || [];
    if (!this.books.length) {
      sel.innerHTML = '<option value="">No chaptered books installed</option>';
      $('#dc-scope').innerHTML = '<option value="">—</option>';
      $('#dc-estimate').textContent = 'Nothing to build from yet. Install a Bible or a chaptered book from the Store.';
      await this.refreshMine();
      return;
    }
    sel.innerHTML = this.books.map(b =>
      '<option value="' + esc(b.id) + '">' + esc(b.name) + ' <span class="muted">· '
      + (b.is_bible ? 'Bible' : esc(b.type)) + '</span></option>').join('');
    // Only seed the form the first time.  Coming back to this view used to
    // silently replace dates the reader had already chosen.
    if (!this._initialised) {
      this._initialised = true;
      const today = new Date();
      $('#dc-start').value = this.iso(today);
      $('#dc-months').value = '6';
      $('#dc-finish').value = this.iso(this.addMonths(today, 6));
    }
    await this.refreshScopes();
    await this.refreshMine();
  },

  bind() {
    this._bound = true;
    $('#dc-book').onchange = () => { this.refreshScopes(); };
    $('#dc-scope').onchange = () => { this.applySuggestion(this.suggestTitle()); this.estimate(); };
    DatePicker.attach($('#dc-start'), { label: 'Start date' });
    DatePicker.attach($('#dc-finish'), { label: 'Finish date' });
    $('#dc-start').onchange = () => { this.applyMonths(); this.estimate(); };
    $('#dc-finish').onchange = () => { this.estimate(); };
    $('#dc-months').onchange = () => { this.applyMonths(); this.estimate(); };
    $$('#dc-days .dc-day').forEach(b => b.onclick = () => {
      if (b.classList.contains('on') && $$('#dc-days .dc-day.on').length === 1) {
        toast('Keep at least one reading day.', 'warn');
        return;
      }
      b.classList.toggle('on');
      this.estimate();
    });
    $$('#v-devotions [data-preset]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      const p = a.dataset.preset;
      $$('#dc-days .dc-day').forEach(b => {
        const w = Number(b.dataset.w);
        b.classList.toggle('on', p === 'all' || (p === 'week' && w >= 1 && w <= 5) || (p === 'sun' && w === 0));
      });
      this.estimate();
    });
    $('#dc-title').addEventListener('input', () => {
      // A name the reader typed is theirs; stop suggesting over it.
      const cur = $('#dc-title').value;
      if (cur !== this._suggestedTitle) this._suggestedTitle = null;
    });
    $('#dc-create').onclick = () => this.create();
  },

  applyMonths() {
    const months = Number($('#dc-months').value) || 1;
    const startText = $('#dc-start').value;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(startText || '');
    if (!m) return;
    const start = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    $('#dc-finish').value = this.iso(this.addMonths(start, months));
  },

  scopeLabel() {
    const sel = $('#dc-scope');
    return (sel.options[sel.selectedIndex] || {}).text || '';
  },

  suggestTitle() {
    const sel = $('#dc-book');
    const name = (this.books.find(b => b.id === sel.value) || {}).name || 'Devotion';
    const scope = this.scopeLabel().split(' · ')[0];
    return name + ' — ' + scope;
  },

  applySuggestion(suggested) {
    // Only fill the box while it holds our own suggestion.
    if (this._suggestedTitle === null) return;
    const cur = $('#dc-title').value;
    if (!cur || cur === this._suggestedTitle) $('#dc-title').value = suggested;
    this._suggestedTitle = suggested;
  },

  async refreshScopes() {
    const sel = $('#dc-book');
    const scopeSel = $('#dc-scope');
    if (!sel.value) { scopeSel.innerHTML = '<option value="">—</option>'; return; }
    const r = await api('devotion/scopes', { module_id: sel.value });
    if (!r.ok) {
      scopeSel.innerHTML = '<option value="">' + esc(r.error || 'Could not read this book') + '</option>';
      this.estimate();
      return;
    }
    const scopes = r.scopes || [];
    const head = scopes.filter(s => !s.group);
    const groups = [];
    scopes.filter(s => s.group).forEach(s => {
      const g = groups.find(x => x.label === s.group);
      if (g) g.items.push(s); else groups.push({ label: s.group, items: [s] });
    });
    let html = head.map(s => '<option value="' + esc(s.value) + '">' + esc(s.label) + '</option>').join('');
    for (const g of groups) {
      html += '<optgroup label="' + esc(g.label) + '">'
        + g.items.map(s => '<option value="' + esc(s.value) + '">' + esc(s.label) + '</option>').join('')
        + '</optgroup>';
    }
    scopeSel.innerHTML = html;
    this.applySuggestion(this.suggestTitle());
    await this.estimate();
  },

  async estimate() {
    const seq = ++this._estimateSeq;
    const est = $('#dc-estimate');
    const warns = $('#dc-warnings');
    $('#dc-result').innerHTML = '';
    if (!$('#dc-book').value || !$('#dc-scope').value) {
      est.textContent = 'Pick a book and a part to see the plan.';
      warns.innerHTML = '';
      return;
    }
    const r = await post('devotion/estimate', this.params());
    if (seq !== this._estimateSeq) return;   // a newer estimate has won
    if (!r.ok) {
      est.innerHTML = '<span class="warn">' + esc(r.error || 'Cannot plan that.') + '</span>';
      warns.innerHTML = '';
      return;
    }
    est.innerHTML = '<b>' + r.days.toLocaleString() + ' day devotion</b> · '
      + r.words_per_day.toLocaleString() + ' words a day ≈ '
      + r.minutes_per_day + ' minute' + (r.minutes_per_day === 1 ? '' : 's')
      + ' · ' + (r.kind === 'chapters'
          ? r.atoms_chapters.toLocaleString() + ' whole chapters, never split'
          : r.atoms.toLocaleString() + ' sentences')
      + '<div class="tiny muted" style="margin-top:2px">'
      + esc(r.start) + ' → ' + esc(r.finish) + '</div>';
    warns.innerHTML = (r.warnings || []).map(w =>
      '<li class="warn-line">' + esc(w) + '</li>').join('');
  },

  async refreshModules() {
    /* A module created after boot is not in S.modules, and every pane resolves
     * its resource through that list. Refresh it so the new devotion can be
     * opened straight into a pane. */
    const r = await api('library');
    if (r && r.modules) S.modules = r.modules;
  },

  async create() {
    if (!$('#dc-book').value || !$('#dc-scope').value) {
      toast('Pick a book and a part first.', 'warn');
      return;
    }
    const btn = $('#dc-create');
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = 'Creating…';
    const r = await post('devotion/create', this.params());
    btn.disabled = false;
    btn.textContent = old;
    if (!r.ok) {
      $('#dc-result').innerHTML = '<div class="warn">' + esc(r.error || 'Could not create the devotion.') + '</div>';
      return;
    }
    toast('Created "' + r.name + '" — ' + r.days + ' days.');
    $('#dc-result').innerHTML =
      '<div class="org-card" style="margin-top:10px;border-color:var(--accent)">'
      + '<div class="org-h"><b>Created "' + esc(r.name) + '"</b></div>'
      + '<div class="st-body">' + r.days + ' daily entries, from ' + esc(r.start) + ' to ' + esc(r.finish)
      + '. It is ready to read in your existing Bible or book pane. The devotional pane is no longer needed.</div>'
      + '<div class="org-new" style="margin-top:8px"><button class="btn primary" id="dc-open-new">Start devotional</button></div>'
      + '</div>';
    $('#dc-open-new').onclick = () => DevotionalContext.activate('dev:' + r.module_id, 1);
    await this.refreshMine();
    await this.refreshModules();
  },

  async refreshMine() {
    const host = $('#dc-list');
    if (!host) return;
    const r = await api('devotion/mine');
    if (!r || r.ok === false) {
      host.innerHTML = '<div class="tiny muted">Could not load your devotions: '
        + esc((r && r.error) || 'unknown error') + '.</div>';
      return;
    }
    const list = r.devotions || [];
    $('#dc-mine-count').textContent = list.length ? '· ' + list.length : '';
    if (!list.length) {
      host.innerHTML = '<div class="tiny muted">Nothing created yet. Your devotions will appear here.</div>';
      return;
    }
    host.innerHTML = list.map(d =>
      '<div class="org-card"><div class="org-h"><b>' + esc(d.name) + '</b>'
      + '<span class="org-a">'
      + '<a href="#" data-dc-open="' + esc(d.id) + '">open</a>'
      + '<a href="#" class="danger" data-dc-delete="' + esc(d.id) + '">delete</a>'
      + '</span></div>'
      + '<div class="tiny muted">' + (d.entries || 0) + ' days · ' + esc(d.scope_label || '')
      + '<br>from ' + esc(d.source_name || 'your library') + '</div>'
      + '</div>').join('');
    host.querySelectorAll('[data-dc-open]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      DevotionalContext.activate('dev:' + a.dataset.dcOpen, 0);
    });
    host.querySelectorAll('[data-dc-delete]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const id = a.dataset.dcDelete;
      const card = a.closest('.org-card');
      const name = card ? card.querySelector('b').textContent : 'this devotion';
      if (!confirm('Delete "' + name + '"? Its daily entries are removed from your library. This cannot be undone.')) return;
      const res = await post('devotion/delete', { module_id: id });
      if (!res.ok) { toast(res.error || 'Could not delete.', 'err'); return; }
      toast('Deleted "' + name + '".');
      await this.refreshMine();
      await this.refreshModules();
    });
  },
};
