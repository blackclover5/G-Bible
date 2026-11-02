const SelCard = {
  node: null,
  anchor: null,
  text: '',
  moduleId: '',
  key: '',
  label: '',
  hideId: 0,

  async show(anchor, text, moduleId, key, label) {
    if (!text || text.length < 2) return;
    this.hide();
    this.anchor = anchor;
    this.text = text;
    this.moduleId = moduleId || '';
    this.key = key || '';
    this.label = label || '';

    const node = this.node || (this.node = $('#selcard') || this.build());
    node.innerHTML = '<div class="quote">' + esc(text.length > 900
      ? text.slice(0, 900) + '…' : text) + '</div>'
      + '<div class="where"><b>' + esc(label || 'this passage') + '</b>'
      + (this.moduleId ? '<span>' + esc((modById(this.moduleId) || {}).name || '') + '</span>' : '')
      + '<span class="n">' + text.length.toLocaleString() + ' characters</span></div>'
      + '<div class="cite" id="sc-cite">Building the citation…</div>'
      + '<div class="acts">'
      + '<button class="primary" id="sc-copy">Copy quote + citation</button>'
      + '<button id="sc-quote">Quote only</button>'
      + '<button id="sc-note">Note</button>'
      + '<button id="sc-list">Word list</button>'
      + '<button id="sc-ai">Explain</button>'
      + '<button id="sc-more">More…</button>'
      + '</div>'
      + '<div class="note">The citation includes the licence, because a '
      + 'quotation without one is not a citation.</div>';

    this.place(anchor);
    node.classList.add('on');
    this.wire(node);
    this.cite(node);
  },

  build() {
    const n = el('div');
    n.id = 'selcard';
    document.body.appendChild(n);
    document.addEventListener('mousedown', (e) => {
      if (!e.target.closest('#selcard')) SelCard.hide();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') SelCard.hide();
    });
    window.addEventListener('scroll', () => SelCard.hide(), true);
    return n;
  },

  place(anchor) {
    const n = this.node;
    const r = anchor.getBoundingClientRect
      ? anchor.getBoundingClientRect()
      : { left: anchor.x, top: anchor.y, bottom: anchor.y, right: anchor.x, height: 0 };
    n.style.left = '0px';
    n.style.top = '0px';
    const w = n.offsetWidth, h = n.offsetHeight;
    const left = Math.max(8, Math.min(window.innerWidth - w - 12,
      r.left + r.width / 2 - w / 2));
    let top = r.bottom + 8;
    if (top + h > window.innerHeight - 10) top = Math.max(8, r.top - h - 8);
    n.style.left = left + 'px';
    n.style.top = top + 'px';
  },

  async cite(node) {
    const out = $('#sc-cite', node);
    if (!this.moduleId) {
      out.textContent = 'No resource in this pane, so there is nothing to cite. '
        + 'Copy the text as it stands.';
      return;
    }
    const ref = this.label && /^\s*[1-3]?\s?[A-Za-z]+\s+\d/.test(this.label)
      ? this.label : '';
    const c = ref
      ? await api('cite/passage', { ref, id: this.moduleId, style: 'sbl', full: 1 })
      : await api('cite/get', { id: this.moduleId, style: 'sbl', full: 1 });
    const a = await api('cite/attribution', { ids: this.moduleId });
    const text = ((c.citation || '') + '\n' + (a.text || '')).trim();
    if (!text || c.error) {
      out.innerHTML = '<span style="color:var(--fg-3)">'
        + esc(c.error || 'this resource has no citation recorded') + '</span>';
      return;
    }
    out.textContent = text;
    this.citeText = text;
    this.citeShort = c.citation || '';
  },

  wire(node) {
    const on = (id, fn) => { const b = $('#' + id, node); if (b) b.onclick = fn; };
    on('sc-copy', () => this.copy(true));
    on('sc-quote', () => this.copy(false));
    on('sc-note', () => this.note(false));
    on('sc-list', () => {
      const w = WordLists.addOccurrence(this.text, this.label,
        this.moduleId, this.key);
      this.hide();
      toast(w ? 'Added to ' + w.name + '.' : 'Could not add it to a list.',
            w ? '' : 'warn');
    });
    on('sc-more', () => this.more());
    /* Explain / summarise / translate all land in the assistant panel, which
     * already knows how to stream, cite and stop -- so the selection card needs
     * no streaming of its own. */
    on('sc-ai', () => { this.hide(); Ai.ask('explain', this.text, this.label); });
  },

  more() {
    modal('This selection', '<div id="sc-full">' + esc(this.text) + '</div>'
      + '<div class="st-tools">'
      + '<button class="btn" id="sc-hl">Highlight in the text</button>'
      + '<div class="hl-colors" style="align-self:center;margin-right:8px">'
      + Highlights.activeColors().map(color =>
          '<button class="hl-swatch hl-swatch-' + color + '" data-color="' + color + '" title="' + color + '"></button>'
        ).join('')
      + '</div>'
      + '<button class="btn" id="sc-pl">Add to a passage list</button>'
      + '<button class="btn" id="sc-clip">Clip this selection</button>'
      + '<button class="btn" id="sc-notes">To the notes document</button>'
      + '<button class="btn" id="sc-pal" title="Named color sets for highlighting">Palettes</button>'
      + '</div>'
      + '<div class="st-tools">'
      + '<span class="tiny muted" style="align-self:center">AI:</span>'
      + '<button class="btn" id="sc-ai-ask" title="Put this passage in front of the assistant and ask your own question about it">Ask…</button>'
      + '<button class="btn" id="sc-ai-explain">Explain this</button>'
      + '<button class="btn" id="sc-ai-summarize">Summarise this</button>'
      + '<button class="btn" id="sc-ai-translate">Translate this…</button>'
      + '</div>'
      + '<div class="ct-out" id="sc-cite2">'
      + esc(this.citeText || 'building…') + '</div>', [
      { label: 'Close', cls: 'btn' }]);
    $$('#modal-body .hl-swatch').forEach(sw => {
      sw.style.background = 'var(--mark)';
      const colors = {
        yellow: '#f6e27a', green: '#bfe6a8', blue: '#b3d9f2',
        pink: '#f4bfd4', orange: '#f6cda2',
      };
      sw.style.background = colors[sw.dataset.color] || '#f6e27a';
      sw.onclick = async () => {
        const color = sw.dataset.color || 'yellow';
        await Highlights.add(this.moduleId, this.key, this.label, color,
          this.text);
        closeModal(); toast('Highlighted.');
      };
    });
    $('#sc-hl').onclick = async () => {
      await Highlights.add(this.moduleId, this.key, this.label, 'yellow',
        this.text);
      closeModal(); toast('Highlighted.');
    };
    $('#sc-pl').onclick = () => this.toPassageList();
    const scClip = $('#sc-clip');
    if (scClip) scClip.onclick = async () => {
      closeModal();
      await Clippings.capture(this.text, this.moduleId, this.label, this.key);
    };
    $('#sc-notes').onclick = () => { closeModal(); this.note(true); };
    const scPal = $('#sc-pal');
    if (scPal) scPal.onclick = () => Highlights.palettesDialog();
    const aiBtn = (id, fn) => { const b = $('#' + id); if (b) b.onclick = fn; };
    aiBtn('sc-ai-ask', () => {
      closeModal();
      // The passage becomes the context of the next question, and the reader
      // asks their own question about it -- which is a different thing from
      // asking for an explanation of it.
      App.show('ai');
      Ai.attach(this.text, this.label, this.moduleId, this.key);
    });
    aiBtn('sc-ai-explain', () => { closeModal(); Ai.ask('explain', this.text, this.label); });
    aiBtn('sc-ai-summarize', () => { closeModal(); Ai.ask('summarize', this.text, this.label); });
    aiBtn('sc-ai-translate', () => { closeModal(); Ai.translateText(this.text, this.label); });
    setTimeout(() => {
      const c = $('#sc-cite2');
      if (c && this.citeText) c.textContent = this.citeText;
    }, 60);
  },

  /* A quotation is a note with a citation in it.  Both forms go through the
   * same call; the blockquote is what makes the first one read as a quote
   * rather than as prose that happens to contain scripture. */
  async note(plain) {
    const body = (plain ? this.text
      : '> ' + this.text.split('\n').join('\n> '))
      + (this.citeText ? '\n\n' + this.citeText : '');
    const r = await post('notes/save', { kind: 'note',
      title: this.label || 'Selection', body,
      module_id: this.moduleId, unit_key: this.key, ref_label: this.label });
    this.hide();
    if (!r.ok) { toast(r.error || 'Could not save it.', 'err'); return; }
    App.show('notes');
    toast('Saved as a note.');
  },

  /* Put the passage into a passage list, making one if there is none. */
  async toPassageList() {
    const lists = await api('passagelist');
    const all = lists.lists || [];
    const body = '<div id="sc-pl"></div>';
    modal('Add to a passage list', body, [
      { label: 'Cancel', cls: 'btn' },
      { label: 'New list', cls: 'btn', close: false, fn: async () => {
        const name = prompt('Name the new list', this.label || 'Passages');
        closeModal();
        if (!name) return;
        const made = await api('passagelist', { action: 'save', name });
        await api('passagelist', { action: 'add', id: made.id, key: this.key,
          ref: this.label, module: this.moduleId });
        toast('List created.');
      } }]);
    const host = $('#sc-pl');
    if (!all.length) {
      host.innerHTML = '<div class="empty tiny">No lists yet — press '
        + '<b>New list</b>.</div>';
      return;
    }
    host.innerHTML = all.map(l => '<div class="store-list"><div class="item" '
      + 'data-pl="' + esc(l.id) + '"><div><b>' + esc(l.name) + '</b>'
      + '<div class="tiny muted">' + (l.count || 0) + ' passages</div></div>'
      + '</div></div>').join('');
    $$('.item', host).forEach(x => {
      x.onclick = async () => {
        const r = await api('passagelist', { action: 'add', id: x.dataset.pl,
          key: this.key, ref: this.label, module: this.moduleId });
        closeModal();
        toast(r.unchanged ? 'Already in that list.' : 'Added.');
      };
    });
  },

  async copy(withCite) {
    const text = withCite
      ? (this.text + '\n\n' + (this.citeText || '')).trim()
      : this.text;
    try {
      await navigator.clipboard.writeText(text);
      toast(withCite ? 'Quote and citation copied.' : 'Quote copied.');
    } catch (e) {
      modal('Copy', '<textarea class="ct-out" rows="8">' + esc(text)
        + '</textarea>', [{ label: 'Close', cls: 'btn' }]);
    }
    this.hide();
  },

  hide() {
    if (this.node) this.node.classList.remove('on');
  },

  /* Called from the pane's mouseup.  Works from the live selection, and falls
   * back to the recorded one: the click that ends a drag can collapse the
   * selection before the handler runs, which is why S.lastSelection exists. */
  fromPane(anchor, moduleId, key, label) {
    const sel = window.getSelection ? String(window.getSelection() || '') : '';
    const text = (sel || S.lastSelection || '').replace(/\s+/g, ' ').trim();
    if (text.length < 2) { this.hide(); return; }
    this.show(anchor, text, moduleId, key, label);
  },
};

/* ============================================================ word lists ===
   Every occurrence of a term, kept.

   The distinction from a search is the whole point: a search is a question and
   this is the answer you keep.  A list holds the *query*, not the results, so
   it is re-run every time it is opened and cannot drift out of step with the
   library -- remove a translation and the list is right again without being
   rebuilt.  On top of that the reader may keep occurrences by hand, in their
   own order, with their own notes, and those survive everything.

   A list is also printable and exportable, and converts to a passage list so
   the verses it found can actually be read in sequence.                       */
/* ============================================================== Flashcards */