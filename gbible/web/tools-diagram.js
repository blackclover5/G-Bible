const Diagram = {
  /* One colour per part of speech, fixed, so a noun is the same colour in every
   * verse you look at.  Chosen to stay legible on the dark ground and to stay
   * apart for the commonest eight. */
  COLOURS: {
    V: '#6ea8fe', N: '#63c68a', R: '#f0b429', C: '#b78cf5', T: '#ef6b73',
    P: '#8fd6c0', D: '#d7b3ff', M: '#ffb4a2', S: '#9fd0ff', K: '#ffd166',
    A: '#c9d4a8', F: '#e8b4b8', X: '#8b93ad', H: '#b0e0c0', Z: '#d4c08a',
    Y: '#a8c8e0', O: '#c8b0a0', Q: '#e0c8a0', B: '#b8d8e0', L: '#d8c8e0',
    W: '#c0c0c0',
  },
  colour(tag) { return this.COLOURS[tag] || '#8b93ad'; },

  async open(ref, moduleId) {
    modal('Sentence diagram', '<div class="st-loading">Analysing…</div>',
      [{ label: 'Export', cls: 'btn', close: false,
         fn: async () => {
           const d = await api('clause/diagram_export', { ref });
           if (!d.ok) { toast(d.error || 'Nothing to export.', 'warn'); return; }
           const blob = new Blob([d.html], { type: 'text/html' });
           const a = document.createElement('a');
           a.href = URL.createObjectURL(blob);
           a.download = d.filename || 'diagram.html';
           a.click();
           setTimeout(() => URL.revokeObjectURL(a.href), 5000);
         } },
       { label: 'Open it', cls: 'btn', close: false, fn: () => { /* set below */ } },
       { label: 'Close', cls: 'btn' }]);
    const r = await api('clause/diagram', { ref, module: moduleId || '' });
    const body = $('#modal-body');
    if (!r.ok) {
      body.innerHTML = '<div class="warn">' + esc(r.error || 'no diagram') + '</div>';
      const btns = $$('#modal-foot button');
      if (btns[0]) btns[0].remove();
      return;
    }
    body.innerHTML = this.paint(r);
    this.wire(r);
  },

  async openFlow(ref, moduleId) {
    modal('Propositional flow (English)', '<div class="st-loading">Analysing…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const r = await api('clause/diagram', { ref, module: moduleId || '' });
    const body = $('#modal-body');
    if (!r.ok) { body.innerHTML = '<div class="warn">' + esc(r.error || 'no diagram') + '</div>'; return; }
    if (!r.tagged || !r.clauses || !r.clauses.length) {
      body.innerHTML = '<div class="warn">No dependency parse available. '
        + 'Install the English parser (spaCy + en_core_web_sm) for a '
        + 'propositional flow; without it only the punctuation-based sentence '
        + 'diagram is offered.</div>';
      return;
    }
    let h = '<div class="tiny muted" style="margin-bottom:8px">'
      + esc(r.ref) + ' · ' + esc(r.module)
      + ' · English dependency parse. Each clause is indented under the '
      + 'clause that governs it.</div>';
    if (r.tag_note) h += '<div class="ol-src">' + esc(r.tag_note) + '</div>';
    (r.clauses || []).forEach(c => {
      const depth = Math.max(0, Math.min(6, c.depth || 0));
      h += '<div style="margin-left:' + (depth * 1.6) + 'em;margin-bottom:8px;'
        + 'border-left:2px solid var(--acc);padding-left:8px">';
      h += '<div class="tiny muted">Clause ' + (c.index + 1)
        + (c.verb ? ' — ' + esc(c.verb) : '')
        + (c.dep ? ' <span class="muted">(' + esc(c.dep) + ')</span>' : '')
        + '</div>';
      h += '<div style="font-size:14px;line-height:1.4">' + esc(c.text) + '</div>';
      h += '</div>';
    });
    h += '<div class="sd-txt" style="margin-top:10px">' + esc(r.text) + '</div>';
    body.innerHTML = h;
  },

  paint(r) {
    let h = '<div class="tiny muted" style="margin-bottom:8px">'
      + esc(r.ref) + ' · ' + esc(r.module) + '</div>';
    if (r.tag_note) h += '<div class="ol-src">' + esc(r.tag_note) + '</div>';

    /* The legend names the parts of speech in words, not in letters.  The
     * letters exist so a noun keeps one colour from verse to verse; "N" on its
     * own tells a reader nothing. */
    const names = {};
    (r.words || []).forEach(w => {
      if (w.pos_tag && w.pos_label && !names[w.pos_tag]) names[w.pos_tag] = w.pos_label;
    });
    const legend = (r.order || []).map(t =>
      '<span style="background:' + this.colour(t) + '" title="' + esc(t) + '">'
      + esc(names[t] || t) + '</span>').join('');
    if (legend) h += '<div class="sd-legend">' + legend + '</div>';

    (r.clauses || []).forEach(c => {
      h += '<div class="sd-clause">'
        + '<div class="sd-head"><span class="tiny muted">Clause '
        + (c.index + 1)
        + (c.verb ? ' — governed by <b style="color:var(--accent)">'
            + esc(c.verb) + '</b>' : '')
        + (c.marker ? ' <span class="sd-marker">' + esc(c.marker)
            + '</span>' : '') + '</span></div>'
        + '<div class="sd-words">';
      if (!c.words.length) {
        h += '<div class="sd-word"><span class="w">'
          + esc(c.text.slice(0, 40)) + '</span>'
          + '<span class="f">no morphology</span></div>';
      }
      c.words.forEach(w => {
        const bits = [w.pos_label || w.pos_tag];
        if (w.tense) bits.push(w.tense);
        if (w.mood) bits.push(w.mood);
        if (w.person) bits.push(w.person);
        if (w.gender) bits.push(w.gender);
        if (w.number) bits.push(w.number);
        /* What it is attached to, and how.  This is the part that was missing:
         * knowing a word is a noun does not tell you it is the object of
         * "loved" rather than standing in the phrase "the world to come". */
        if (w.role) bits.push(w.head && w.head !== w.surface
          ? w.role + ' “' + w.head + '”' : w.role);
        h += '<div class="sd-word" title="' + esc(w.code) + '">'
          + '<span class="w">' + esc(w.surface || '—') + '</span>'
          + '<span class="t" style="background:' + this.colour(w.pos_tag) + '">'
          + esc(w.pos_label || w.pos_tag || '?') + '</span>'
          + '<span class="f">' + esc(bits.filter(Boolean).join(' · ')) + '</span>'
          + '</div>';
      });
      h += '</div></div>';
    });

    /* The distribution, as a chart, because "what are the words in this verse
     * made of" is a question about proportion. */
    if (r.chart && r.chart.ok && (r.chart.series || []).length) {
      const max = r.chart.max || 1;
      h += '<div class="dash-h" style="margin-top:14px">' + esc(r.chart.title)
        + '</div>' + r.chart.series.map(s =>
          '<div class="chart-sm"><span class="lbl">' + esc(s.label)
          + '</span><span class="bar" style="width:'
          + Math.max(2, Math.round(s.value / max * 180)) + 'px"></span>'
          + '<span class="v">' + s.value + '</span></div>').join('');
    }

    /* The text with the clauses marked, because the layout only makes sense
     * against the sentence it came from. */
    let marked = '';
    (r.clauses || []).forEach(c => {
      marked += '<span style="border-bottom:2px solid ' + this.colour(
        (c.words[0] || {}).pos_tag || 'X') + '">' + esc(c.text) + '</span> ';
    });
    h += '<div class="sd-txt">' + (marked || esc(r.text)) + '</div>';
    return h;
  },

  wire(r) {
    const btns = $$('#modal-foot button');
    if (btns[0]) btns[0].onclick = () => {
      closeModal();
      const m = S.modules.find(x => x.id === r.module_id);
      if (m) { App.show('workspace'); Workspace.openModule(m.id, { key: r.key }); }
    };
  },

  /* Open the diagram for whatever reference box the caller names. */
  async openFrom(boxId) {
    const ref = ($(boxId) || {}).value || ($('#g-ref') || {}).value || '';
    if (!ref.trim()) { toast('Type a reference first, e.g. John 3:16.', 'warn'); return; }
    await this.open(ref.trim());
  },

  /* Is there a dependency parse?  Asked before the reader presses Find, so the
   * two relations that need one are offered only when they can work.  An
   * option that refuses when pressed is worse than an option never offered. */
  async parser() {
    const host = $('#clause-parser');
    if (!host) return null;
    const r = await api('clause/parser');
    const sel = $('#cl-rel');
    if (sel) {
      const want = sel.value;
      sel.innerHTML = (r.relations || []).map(x =>
        '<option value="' + esc(x.value) + '">' + esc(x.label) + '</option>').join('');
      if ((r.relations || []).some(x => x.value === want)) sel.value = want;
    }
    host.innerHTML = r.available
      ? 'Grammar from <b>' + esc(r.model) + '</b>, a dependency parser. '
        + 'Every result names the verb that governs the word, so you can check it.'
      : '<span style="color:var(--warn,#d9a441)">No dependency parser: '
        + esc(r.reason) + '</span> With one, this finds what is the '
        + '<i>object of a verb</i>, which punctuation cannot tell. The other '
        + 'relations still work.';
    return r;
  },

  /* Clause search: one or two words, and what the grammar says about them. */
  async search(a, b, relation) {
    const host = $('#clause-results');
    if (!host) return;
    if (!a || !a.trim()) {
      host.innerHTML = '<div class="empty">Type a word to look for.</div>';
      return;
    }
    host.innerHTML = '<div class="st-loading">Working out the grammar…</div>';
    const r = await api('clause/search', {
      a, b, relation: relation || 'same', book: ($('#cl-book') || {}).value || '',
      limit: 120 });
    if (!r.ok) {
      host.innerHTML = '<div class="warn">' + esc(r.error)
        + (r.needs === 'parser'
           ? '<br><span class="tiny muted">' + esc(r.reason) + '</span>' : '')
        + '</div>';
      return;
    }
    /* Precise about what was examined.  `candidates` is how many verses hold
     * the word at all; `scanned` is how many of those were actually parsed.
     * Printing "135 of 10137 checked" claimed a coverage that did not happen. */
    let h = '<div class="tiny muted">' + r.total + ' found'
      + (r.scanned ? ' · ' + r.scanned + ' verse'
          + (r.scanned === 1 ? '' : 's') + ' parsed' : '')
      + (r.candidates > (r.scanned || 0)
          ? ' · of ' + r.candidates + ' that contain the word'
          : (r.candidates ? ' · of ' + r.candidates + ' checked' : ''))
      + ' · ' + esc(r.method) + '</div>'
      + '<div class="ol-src">' + esc(r.note) + '</div>';
    if (r.more) {
      h += '<div class="tiny muted">Narrow it by book, or raise the scan '
        + 'limit, to look at the remaining ' + r.more + '.</div>';
    }
    (r.hits || []).forEach(x => {
      h += '<div class="wl-row"><span class="ref" data-open="'
        + esc(x.key) + '" data-mod="' + esc(x.module_id) + '">'
        + esc(x.label) + '</span>'
        + '<span class="txt">'
        /* Why this verse matched, in a sentence naming the governing verb.
           A result you cannot check is a result you have to take on faith. */
        + (x.evidence && x.evidence.why
            ? '<b style="color:var(--accent)">' + esc(x.evidence.why) + '</b> '
            : '')
        + ((x.clauses || []).map(c =>
            '<span class="muted">' + (c.verb ? '[' + esc(c.verb) + '] ' : '')
            + esc(c.text.slice(0, 62)) + '</span>').join(' | '))
        + '</span></div>';
    });
    host.innerHTML = h || '<div class="empty">'
      + this.emptyFor(relation) + '</div>';
    $$('[data-open]', host).forEach(x => {
      x.onclick = () => {
        App.show('workspace');
        Workspace.openModule(x.dataset.mod, { key: x.dataset.open });
      };
    });
  },

  emptyFor(relation) {
    if (relation === 'object') {
      return 'Nowhere that word is the object of a verb'
        + (this._parserOk === false ? ' — and that needs a dependency parser'
            + ', which is not installed' : '')
        + '. Try the subject, or one of the clause relations.';
    }
    if (relation === 'subject') return 'Nowhere that word is the subject of a verb.';
    if (relation === 'prepositional') return 'Nowhere that word is the object of a preposition.';
    if (relation === 'different') return 'No verse puts them in different clauses of one sentence.';
    if (relation === 'sentence') return 'No verse has both in one sentence.';
    return 'No verse has both words under one and the same verb.';
  },
};

/* ============================================================== workflows ===
   A saved arrangement of panes with a sequence attached.

   A layout tells you where the windows go.  A workflow tells you what to open,
   in what order, at whichever passage you happen to be at -- which is the part
   worth saving, because nobody retypes the same five-pane drill and nobody
   wants to re-open the same four resources every Sunday.

   Built by capture rather than by hand: whatever is open becomes step one, and
   the rest is editing.  A step can also name a *slot* -- "a commentary" --
   rather than a particular book, so a flow made while reading Genesis still
   opens a commentary when you run it on Romans.                          */