/* Shared devotional reading context.
 * A devotional plan owns assignments and progress, never a duplicate reader.
 * Existing resource panes render the assigned source and receive temporary
 * day markers while this context is active. */
const DevotionalContext = {
  active: null,
  // Original state of any workspace pane temporarily borrowed by a devotional.
  // Keep this across day changes so moving to Day 2 never snapshots Day 1.
  paneSnapshots: {},
  snapshotPane(p) {
    if (!p || !p.id || this.paneSnapshots[p.id]) return;
    this.paneSnapshots[p.id] = { module_id: p.module_id,
      cursor: JSON.parse(JSON.stringify(p.cursor || {})) };
  },
  async activate(plan, day) {
    // Starting a different plan ends the previous borrowed-pane session first.
    if (this.active && this.active.plan !== plan) await this.restorePanes();
    if (!this.active) this.paneSnapshots = {};
    const d = await api('readingplan/day', { plan, day: day || 0 });
    if (!d || !d.ok) { toast((d && d.error) || 'Could not open this devotional.', 'warn'); return; }
    this.active = { plan, day: d.day, total: d.total, title: d.title,
      sourceId: d.source_id || '', sourceKey: d.source_key || '', sourceKeys: d.source_keys || [], sourceKind: d.source_kind || 'resource',
      passages: d.passages || [], head: d.head || '', done: !!d.done };
    App.show('workspace');
    await this.openAssignedSource();
  },
  async openAssignedSource() {
    const c = this.active;
    if (!c) return;
    const source = (S.modules || []).find(m => m.id === c.sourceId);
    const ref = (c.passages || [])[0] || '';
    const cursor = source && source.is_bible ? { refs: c.passages, ref, span: 'chapter' }
      : (c.sourceKeys.length ? { keys: c.sourceKeys, list_name: c.passages.join(' · ') }
        : { key: c.sourceKey || '', ref, span: 'chapter' });
    if (source && (ref || c.sourceKey || c.sourceKeys.length)) {
      // Reuse an existing source pane. For Bible readings, if the selected
      // translation is not open yet, repurpose an existing Bible pane rather
      // than creating a second Bible-shaped reading surface.
      const existing = (S.layout && S.layout.panes || []).find(p => p.module_id === source.id);
      if (existing) {
        this.snapshotPane(existing);
        existing.cursor = cursor;
        const node = $('.pane[data-pane="' + existing.id + '"]');
        if (node) { App.showPane(existing.tile_id || 't0', existing.id); await App.fillPane(node, existing); }
        else await Workspace.openModule(source.id, cursor);
      } else if (source.is_bible) {
        const biblePane = (S.layout && S.layout.panes || []).find(p => {
          const mod = (S.modules || []).find(x => x.id === p.module_id);
          return mod && mod.is_bible;
        });
        if (biblePane) {
          this.snapshotPane(biblePane);
          await Workspace.switchModule(biblePane.id, source.id);
          biblePane.cursor = cursor;
          const node = $('.pane[data-pane="' + biblePane.id + '"]');
          if (node) { App.showPane(biblePane.tile_id || 't0', biblePane.id); await App.fillPane(node, biblePane); }
        } else await Workspace.openModule(source.id, cursor);
      } else {
        await Workspace.openModule(source.id, cursor);
      }
    } else if (ref) {
      await Reader.openRefAnywhere(ref);
    } else {
      toast('This devotional has no linked reading location.', 'warn');
    }
    this.refreshVisiblePanes();
  },
  async move(delta) {
    if (!this.active) return;
    const next = Math.max(1, Math.min(this.active.total, this.active.day + delta));
    await this.activate(this.active.plan, next);
  },
  async markDone() {
    const c = this.active;
    if (!c) return;
    const r = await api('readingplan/mark', { plan: c.plan, day: c.day, done: c.done ? 0 : 1 });
    if (r && r.ok !== false) c.done = !c.done;
    this.refreshVisiblePanes();
  },
  async restorePanes() {
    const snapshots = this.paneSnapshots || {};
    this.active = null;
    this.paneSnapshots = {};
    for (const [paneId, saved] of Object.entries(snapshots)) {
      const p = (S.layout && S.layout.panes || []).find(x => x.id === paneId);
      if (!p) continue; // The user may have closed the pane during the session.
      if (saved.module_id && p.module_id !== saved.module_id)
        await Workspace.switchModule(paneId, saved.module_id);
      p.cursor = JSON.parse(JSON.stringify(saved.cursor || {}));
      const node = $('.pane[data-pane="' + paneId + '"]');
      if (node) await App.fillPane(node, p);
      if (Reader && Reader.saveNow) await Reader.saveNow(p);
    }
    this.refreshVisiblePanes();
  },
  async exit() {
    await this.restorePanes();
    toast('Devotional reading mode closed.');
  },
  refreshVisiblePanes() {
    if (!S.layout) return;
    document.querySelectorAll('.pane').forEach(node => {
      const id = node.dataset.pane;
      const p = (S.layout.panes || []).find(x => x.id === id);
      if (p) {
        const m = (S.modules || []).find(x => x.id === p.module_id);
        const body = node.querySelector('.pane-body');
        if (body && m) this.decorate(p, m, body);
      }
    });
  },
  decorate(p, m, body) {
    body.querySelectorAll('.devotional-context-banner,.devotional-day-marker').forEach(x => x.remove());
    const c = this.active;
    if (!c || m.id !== c.sourceId) return;
    const banner = el('div', 'devotional-context-banner');
    banner.innerHTML = '<div><b>' + esc(c.title) + '</b><span>Day ' + c.day + ' of ' + c.total
      + (c.done ? ' · Completed' : '') + (c.passages.length ? ' · ' + esc(c.passages.join(' · ')) : '') + '</span></div>'
      + '<div class="devotional-context-actions"><button class="btn tiny" data-dc-prev>‹</button>'
      + '<button class="btn tiny" data-dc-done>' + (c.done ? 'Undo' : 'Mark read') + '</button>'
      + '<button class="btn tiny" data-dc-next>›</button><button class="btn tiny" data-dc-exit>×</button></div>';
    body.insertBefore(banner, body.firstChild);
    banner.querySelector('[data-dc-prev]').onclick = () => this.move(-1);
    banner.querySelector('[data-dc-next]').onclick = () => this.move(1);
    banner.querySelector('[data-dc-done]').onclick = () => this.markDone();
    banner.querySelector('[data-dc-exit]').onclick = () => this.exit();
    // Every chapter boundary in the assigned reading gets the same day label.
    const chapterHeads = body.querySelectorAll('.chapter-head');
    if (chapterHeads.length) {
      chapterHeads.forEach(h => h.appendChild(el('span', 'devotional-day-marker', 'Day ' + c.day)));
    } else {
      // Headings can be hidden by reader preferences. Mark the first verse of
      // each chapter directly so the day marker remains visible regardless.
      const firstVerses = [];
      let lastChapter = '';
      body.querySelectorAll('.verse[data-k]').forEach(v => {
        const parts = (v.dataset.k || '').split('.');
        const chapter = parts.length >= 2 ? parts.slice(0, 2).join('.') : '';
        if (chapter && chapter !== lastChapter) firstVerses.push(v);
        if (chapter) lastChapter = chapter;
      });
      if (firstVerses.length) firstVerses.forEach(v =>
        v.parentNode.insertBefore(el('span', 'devotional-day-marker', 'Day ' + c.day), v));
      else body.querySelectorAll('.docheading,h1').forEach(h =>
        h.appendChild(el('span', 'devotional-day-marker', 'Day ' + c.day)));
    }
  },
};
