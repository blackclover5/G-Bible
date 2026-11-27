const Popup = {
  node: null,
  show(html, x, y) {
    const p = this.node || (this.node = $('#popup'));
    p.innerHTML = html;
    p.classList.add('on');
    const w = p.offsetWidth, h = p.offsetHeight;
    p.style.left = Math.min(window.innerWidth - w - 12, Math.max(6, x - w / 2)) + 'px';
    p.style.top = Math.min(window.innerHeight - h - 12, y + 12) + 'px';
  },
  hide() { if (this.node) this.node.classList.remove('on'); },

  async ref(m, key, x, y) {
    const px = Number(x) || window.innerWidth / 2;
    const py = Number(y) || 200;
    const r = await api('unit', { id: m.id, key });
    if (!r || r.ok === false || !r.item) {
      this.show('<div class="ph">' + esc(m.name) + '</div><div class="pb">'
        + esc((r && r.error) || 'Could not read that passage.') + '</div>', px, py);
      return;
    }
    const it = r.item;
    const label = it.label || key;
    const xrefs = await api('xrefs', { id: m.id, key });
    let html = '<div class="ph">' + esc(m.name) + ' · ' + esc(label) + '</div><div class="pb">'
      + it.html + '</div><div class="pf">';
    (xrefs && xrefs.ok !== false ? (xrefs.refs || []) : []).slice(0, 8).forEach(x =>
      html += '<a href="#" data-k="' + esc(x.key) + '">' + esc(x.label) + '</a>');
    html += '<span class="pc">' + esc(m.license || '') + '</span></div>';
    this.show(html, px, py);
    const p = this.node;
    p.onclick = (e) => {
      const a = e.target.closest('a[data-k]');
      if (a) { e.preventDefault(); Reader.focusRef(m, a.dataset.k); this.hide(); }
    };
  },

  /* One definition popup for a word.  It deliberately shows BOTH key types:
   * a Strong's gloss (lexicons/concordances) and headword entries from
   * installed dictionaries such as Smith's, Easton and Webster.  The old
   * Popup.strongs opened a full modal and could never reach a headword book. */
  async definition(word, num, x, y) {
    const px = Number(x) || window.innerWidth / 2;
    const py = Number(y) || 200;
    this.show('<div class="ph">Looking up ' + esc(word || num) + '…</div>', px, py);
    const r = await api('definition', { word: word || '', num: num || '' });
    if (!r || !r.ok) {
      this.show('<div class="ph">Definition</div><div class="pb">'
        + esc((r && r.error) || 'No definition found.') + '</div>', px, py);
      return;
    }
    let html = '<div class="ph">' + esc(word || num)
      + (num ? ' <span class="muted">' + esc(num) + '</span>' : '') + '</div>';
    if (r.strongs && r.strongs.gloss) {
      html += '<div class="pb"><b>Strong’s ' + esc(r.strongs.number) + '</b>'
        + (r.strongs.form ? ' · ' + esc(r.strongs.form) : '')
        + '<br>' + esc(r.strongs.gloss) + '</div>';
    }
    (r.entries || []).slice(0, 6).forEach(e => {
      html += '<div class="pb"><b>' + esc(e.module) + '</b> · '
        + esc(e.title) + '<br>' + esc(e.text)
        + ' <a href="#" data-defmod="' + esc(e.module_id) + '" data-defkey="'
        + esc(e.key) + '">open</a></div>';
    });
    if (!r.entries || !r.entries.length) {
      html += '<div class="pb stub-empty">No dictionary entry for that word.</div>';
    }
    html += '<div class="pf">'
      + (num ? '<button class="btn tiny" data-def-full>Full word study</button>' : '')
      + (word ? '<button class="btn tiny" data-def-topics>Topics</button>' : '')
      + '<button class="btn tiny" data-def-close>Close</button></div>';
    this.show(html, px, py);
    const p = this.node;
    p.onclick = (ev) => {
      const a = ev.target.closest('a[data-defmod]');
      if (a) {
        ev.preventDefault();
        const m = modById(a.dataset.defmod);
        if (m) { this.hide(); Reader.focusRef(m, a.dataset.defkey); }
        return;
      }
      if (ev.target.closest('[data-def-full]')) {
        this.hide(); Study.openWord(num || word); return;
      }
      if (ev.target.closest('[data-def-topics]')) {
        this.hide(); Study.openFact(word); return;
      }
      if (ev.target.closest('[data-def-close]')) { this.hide(); }
    };
  },

  async strongs(num, x, y, word) {
    return this.definition(word || '', num, x, y);
  },

  async word(word, x, y) {
    return this.definition(word, '', x, y);
  },

  async morph(code, x, y) {
    const px = Number(x) || window.innerWidth / 2;
    const py = Number(y) || 200;
    const r = await api('morph/decode', { code });
    const label = r && r.ok ? (r.label || '') : '';
    this.show('<div class="ph">' + esc(code) + '</div><div class="pb">'
      + esc(label || 'Could not decode this code.') + '</div>'
      + '<div class="pf"><span class="pc">morphological form</span></div>', px, py);
  },

  note(text, title) {
    this.show('<div class="ph">Footnote</div><div class="pb">' + esc(text)
      + '</div><div class="pf"><span class="pc">' + esc(title || '') + '</span></div>',
      window.innerWidth / 2, 200);
  },
};
document.addEventListener('click', (e) => {
  if (!e.target.closest('#popup') && !e.target.closest('.snum')
      && !e.target.closest('.morphs') && !e.target.closest('.vnum')) {
    Popup.hide();
    $('#refsugg').style.display = 'none';
  }
});

