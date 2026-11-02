const Translate = {
  status: null,

  async state() {
    if (!this.status) this.status = await api('translate/status');
    return this.status;
  },

  async open(hits, opts) {
    opts = opts || {};
    const st = await this.state();
    if (!st.ok) { toast('Could not reach the translation service list.', 'err'); return; }

    const rows = (hits || []).map((h, i) => ({
      id: String(i), label: h.label || '', text: h.text || h.snippet || '',
      module_id: h.module_id || '', key: h.key || '',
    })).filter(r => r.text);
    if (!rows.length) { toast('Nothing to translate here.', 'warn'); return; }

    /* What language the selected text is in, taken from the modules it came
       from.  One language wins if they agree; when they do not, the first
       module decides and the reader can change it. */
    const srcLangs = rows.map(r => (S.modules.find(m => m.id === r.module_id) || {}).lang)
      .filter(Boolean);
    const srcCounts = {};
    srcLangs.forEach(l => { srcCounts[l] = (srcCounts[l] || 0) + 1; });
    const srcLang = srcLangs.length
      ? srcLangs.sort((a, b) => srcCounts[b] - srcCounts[a])[0] : '';
    const srcLangName = srcLang
      ? ((S.modules.find(m => m.lang === srcLang) || {}).lang_name || '') : '';

    const chars = rows.reduce((a, r) => a + r.text.length, 0);
    modal('Translate', '<div class="st-loading">Asking…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    if (!st.enabled) {
      $('#modal-body').innerHTML =
        '<div class="warn"><b>No translation service is switched on.</b>'
        + '<div class="st-body">Nothing has been sent anywhere. Enable one in '
        + 'API Settings — under <b>Translate</b> — and this will work.</div></div>'
        + this.providerList(st);
      this.wireProviders();
      return;
    }
    $('#modal-body').innerHTML =
      '<div class="st-tools" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">'
      + '<label>Into <select id="tr-lang"></select></label>'
      + '<label>From <select id="tr-src">'
      /* The source language is not a guess -- it is what the modules being
         translated are written in, and the app already knows.  Defaulting to
         "detect" meant every request went out with no source language, and
         MyMemory answers that with "INVALID LANGUAGE PAIR SPECIFIED" for every
         item: twenty identical errors where the reader expected twenty
         translations.  Where the language really is not known, "detect" stays
         available and the service may or may not manage it. */
      + (srcLang
          ? '<option value="' + esc(srcLang) + '" selected>'
            + esc(srcLangName || srcLang) + ' — from the module</option>'
          : '<option value="auto">detect</option>')
      + ['en', 'he', 'el', 'ar', 'la', 'de', 'fr', 'es']
        .filter(v => v !== srcLang)
        .map(v => '<option value="' + v + '">' + v + '</option>').join('')
      + '</select></label>'
      /* How many, and why the number is small.

         A public translation endpoint is a shared, rate-limited thing:
         MyMemory publishes 5,000 words a day per address.  Offering "translate
         400 items" and then sending 400 is how you get a dialog that never
         finishes and a provider that stops answering, so the count is chosen,
         it starts small, and the terms are a click away rather than buried. */
      + '<label>How many <select id="tr-n">'
      + [10, 20, 50, 100, rows.length].filter((v, i, a) =>
          v <= rows.length && a.indexOf(v) === i)
        .map(v => '<option value="' + v + '"' + (v === 20 ? ' selected' : '')
          + '>' + v + (v === rows.length ? ' (all)' : '') + '</option>').join('')
      + '</select></label>'
      + '<button class="btn primary" id="tr-go">Translate</button>'
      + '<span class="tiny muted">' + rows.length + ' item'
      + (rows.length === 1 ? '' : 's') + ' selected, '
      + chars.toLocaleString() + ' characters · '
      + esc(st.provider_name) + '</span></div>'
      + '<div class="ol-src">' + esc(st.disclaimer)
      + '<br>Sending to <b>' + esc(st.provider_name) + '</b>. '
      + '<a href="#" id="tr-more">what that means</a></div>'
      + '<div id="tr-out"></div>';

    const langs = await api('translate/languages', { provider: st.provider });
    const sel = $('#tr-lang');
    sel.innerHTML = (langs.languages || []).map(l =>
      '<option value="' + esc(l.code) + '"'
      + (l.code === 'es' ? ' selected' : '')
      + (l.supported === false ? ' disabled' : '') + '>' + esc(l.label)
      + (l.supported === false ? ' (not offered)' : '') + '</option>').join('');
    const sayLeft = () => {
      const n = Math.min(rows.length,
                         parseInt(($('#tr-n') || {}).value || '20', 10) || 20);
      $('#tr-go').textContent = 'Translate ' + n + ' item'
        + (n === 1 ? '' : 's') + (n < rows.length ? ' of ' + rows.length : '');
    };
    if ($('#tr-n')) $('#tr-n').onchange = sayLeft;
    sayLeft();
    $('#tr-go').onclick = async () => {
      const out = $('#tr-out');
      const n = parseInt(($('#tr-n') || {}).value || '20', 10) || 20;
      const take = rows.slice(0, n);
      out.innerHTML = '<div class="st-loading">Translating ' + take.length
        + ' of ' + rows.length + '…</div>';
      const r = await post('translate/run', { items: take, limit: take.length,
        target: sel.value, source: $('#tr-src').value, provider: st.provider });
      if (!r.ok) {
        out.innerHTML = '<div class="warn">' + esc(r.error || '')
          + (r.hint ? '<div class="st-body">' + esc(r.hint) + '</div>' : '')
          + '</div>';
        return;
      }
      out.innerHTML = this.results(r);
    };
    $('#tr-more').onclick = () => this.about(st);
  },

  results(r) {
    let h = '<div class="tiny muted" style="margin-bottom:6px">' + r.count
      + ' translated' + (r.cached ? ' · ' + r.cached + ' from the cache' : '')
      + (r.failed ? ' · ' + r.failed + ' failed' : '')
      + (r.truncated ? ' · ' + r.truncated + ' left out, too much text'
        : '') + '</div>';
    (r.rows || []).forEach(x => {
      h += '<div class="st-note"><div class="st-src">' + esc(x.label) + '</div>'
        + (x.error
            ? '<div class="warn tiny">' + esc(x.error) + '</div>'
            : '<div class="st-body">' + esc(x.text || '')
              + (x.unchanged ? ' <span class="tiny muted">(unchanged)'
                + (x.note ? ' — ' + esc(x.note) : '') + '</span>' : '')
              + '</div>')
        + '</div>';
    });
    const keep = el('div', 'st-tools');
    return h;
  },

  providerList(st) {
    return '<div class="st-body">' + (st.providers || []).map(p =>
      '<div class="wf-step' + (p.enabled ? '' : ' skipped') + '">'
      + '<span class="what"><b>' + esc(p.name) + '</b> — '
      + esc(p.vendor) + '<div class="sub">' + esc(p.notes) + '</div></span>'
      + '<button class="btn" data-en="' + esc(p.id) + '"'
      + (p.enabled ? ' disabled' : '') + '>'
      + (p.enabled ? 'on' : 'switch on') + '</button></div>').join('')
      + '</div>';
  },

  wireProviders() {
    $$('[data-en]').forEach(b => {
      b.onclick = async () => {
        const r = await api('apis/enable', { id: b.dataset.en, enabled: 1 });
        if (!r.ok) { toast(r.error || 'Could not switch it on.', 'err'); return; }
        toast('On. Nothing is sent until you press Translate.');
        this.status = null;
        closeModal();
      };
    });
  },

  about(st) {
    modal('About translating here',
      '<div class="st-body">' + esc(st.disclaimer) + '</div>'
      + '<div class="st-body"><b>Nothing leaves this computer</b> until you '
      + 'switch a provider on. Every API in this app ships switched off.</div>'
      + '<div class="st-body">' + (st.providers || []).map(p =>
        '<p><b>' + esc(p.name) + '</b> (' + esc(p.vendor) + ')<br>'
        + esc(p.notes)
        + (p.terms_url ? '<br><a href="#" data-url="' + esc(p.terms_url)
          + '">terms</a>' : '')
        + (p.license ? '<br><span class="tiny muted">' + esc(p.license)
          + '</span>' : '')
        + '</p>').join('')
      + '</div>'
      + '<div class="st-body tiny muted">Translations are cached, so running '
      + 'the same search twice costs one request.</div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('[data-url]').forEach(a => {
      a.onclick = (e) => { e.preventDefault(); window.open(a.dataset.url, '_blank'); };
    });
  },

  /* Translate one passage, from the reading pane. */
  async passage(ref, moduleId) {
    const m = modById(moduleId);
    if (!m) { toast('No resource in this pane.', 'warn'); return; }
    const c = await api('read', { module: moduleId, cursor: { ref, span: 'verse' } });
    if (!c.ok || !c.items || !c.items.length) {
      toast(c.error || 'Nothing to translate there.', 'warn'); return;
    }
    const hits = c.items.map((it, i) => ({
      label: it.label || ref, text: String(it.text || '').replace(/<[^>]+>/g, ' '),
      module_id: moduleId, key: it.key,
    }));
    await this.open(hits);
  },
};

/* ============================================================== catalogue ===
   The whole library as a printed list.

   Distinct from the bibliography, which cites what you used: this is what you
   *have*.  Grouped by kind, then language, then source -- the order in which
   anybody asks "what do I actually own" -- and every row carries its licence,
   because a catalogue is the document you hand somebody to show what you are
   permitted to use.

   Rows with no author stay in and are counted.  A catalogue is a record of
   holdings, and a work whose source never recorded an author is still
   installed; quietly dropping it would make the catalogue disagree with the
   library, which is the one thing a catalogue must never do.               */