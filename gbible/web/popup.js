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

  async ref(m, key) {
    const r = await api('unit', { id: m.id, key });
    if (!r.ok) return;
    const it = r.item;
    const label = it.label || key;
    const xrefs = await api('xrefs', { id: m.id, key });
    let html = '<div class="ph">' + esc(m.name) + ' · ' + esc(label) + '</div><div class="pb">'
      + it.html + '</div><div class="pf">';
    (xrefs.refs || []).slice(0, 8).forEach(x =>
      html += '<a href="#" data-k="' + esc(x.key) + '">' + esc(x.label) + '</a>');
    html += '<span class="pc">' + esc(m.license || '') + '</span></div>';
    const ev = window.event;
    this.show(html, (ev && ev.clientX) || window.innerWidth / 2, (ev && ev.clientY) || 200);
    const p = this.node;
    p.onclick = (e) => {
      const a = e.target.closest('a[data-k]');
      if (a) { e.preventDefault(); Reader.focusRef(m, a.dataset.k); this.hide(); }
    };
  },

  async strongs(num) {
    // The old popup listed a dozen occurrences and told you to go open a
    // lexicon pane.  Now it opens the full word study: every lexicon entry you
    // have, the occurrence count, and the distribution by book.
    Study.openWord(num);
  },

  note(text, title) {
    this.show('<div class="ph">Footnote</div><div class="pb">' + esc(text)
      + '</div><div class="pf"><span class="pc">' + esc(title || '') + '</span></div>',
      window.innerWidth / 2, 200);
  },
};
document.addEventListener('click', (e) => {
  if (!e.target.closest('#popup') && !e.target.closest('.snum') && !e.target.closest('.vnum')) {
    Popup.hide();
    $('#refsugg').style.display = 'none';
  }
});

/* ========================================================== Workspace */
