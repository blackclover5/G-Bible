const Quotations = {
  async load(main) {
    const term = String(main._q || '').trim();
    const lim = main._lim || 8;
    let h = '<div class="dash-card"><div class="dash-h">Quotations</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">Short lines from '
      + 'your installed books that mention a word. The whole unit is quoted, '
      + 'never trimmed to fit.</div>'
      + '<div class="org-new"><input id="q-term" placeholder="a word or phrase"'
      + ' value="' + esc(term) + '" style="flex:1">'
      + '<input id="q-limit" type="number" min="1" max="50" value="' + esc(lim)
      + '" style="width:64px" title="How many">'
      + '<button class="btn primary" id="q-go">Find</button></div>';
    main.innerHTML = h + '<div id="q-out"></div>';
    const go = () => {
      main._q = $('#q-term').value;
      main._lim = $('#q-limit').value;
      this.load(main);
    };
    $('#q-go').onclick = go;
    $('#q-term').onkeydown = (e) => { if (e.key === 'Enter') go(); };
    const out = $('#q-out');
    if (!term) {
      out.innerHTML = '<div class="empty">Type a word.</div>';
      return;
    }
    out.innerHTML = '<div class="st-loading">Looking…</div>';
    const r = await api('quotations', { q: term, limit: lim });
    if (!r.ok) { out.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    const items = r.items || [];
    if (!items.length) {
      out.innerHTML = '<div class="empty">Nothing short enough to quote '
        + 'mentions “' + esc(term) + '”.</div>';
      return;
    }
    out.innerHTML = '<div class="tiny muted" style="margin:8px 0">'
      + items.length + ' line' + (items.length === 1 ? '' : 's') + ' · '
      + esc(r.note || '') + '</div>'
      + items.map((q, i) => '<div class="dash-card"><blockquote class="st-body">'
        + esc(q.quote) + '</blockquote>'
        + '<div class="tiny muted">— ' + esc(q.source || '')
        + (q.title ? ' <i>' + esc(q.title) + '</i>' : '')
        + (q.ref ? ' · ' + esc(q.ref) : '') + '</div>'
        + '<div class="row" style="gap:6px;margin-top:6px">'
        + '<button class="btn tiny" data-qcopy="' + i + '">Copy</button>'
        + '<button class="btn tiny" data-qnote="' + i + '">To notes</button>'
        + '</div></div>').join('');
    out.querySelectorAll('[data-qcopy]').forEach(b => b.onclick = async () => {
      const q = items[+b.dataset.qcopy];
      await Clipboard.write(q.quote + '\n\n— '
        + [q.source, q.title, q.ref].filter(Boolean).join(', '));
    });
    out.querySelectorAll('[data-qnote]').forEach(b => b.onclick = async () => {
      const q = items[+b.dataset.qnote];
      await post('notes/save', { kind: 'note',
        title: q.title || q.source || 'Quotation',
        body: '> ' + q.quote.split('\n').join('\n> ') + '\n\n— '
          + [q.source, q.title, q.ref].filter(Boolean).join(', ') });
      toast('Saved as a note.');
    });
  },
};

/* ======================================================== Syntax tree
 *
 * Dependency search over an imported CoNLL-U treebank.
 *
 * This reads a *stored* analysis and nothing else.  No treebank installed
 * means an empty panel saying so -- not a guess built from the sentence
 * diagram, which is a different thing derived from different sources and is
 * labelled as such where it appears. */
const SyntaxTree = {
  async load(body) {
    body.innerHTML = '<div class="dash-card"><div class="dash-h">Syntax'
      + '</div><div class="tiny muted" style="margin-bottom:8px">Search a '
      + 'dependency treebank you have imported. The analysis is stored in the '
      + 'file; nothing is inferred here.</div>'
      + '<div class="st-tools" style="gap:6px;flex-wrap:wrap">'
      + '<select id="sx-mod" title="Treebank"></select>'
      + '<input id="sx-upos" placeholder="upos, e.g. VERB" style="width:110px">'
      + '<input id="sx-deprel" placeholder="deprel, e.g. obj" style="width:110px">'
      + '<input id="sx-form" placeholder="form" style="width:100px">'
      + '<input id="sx-lemma" placeholder="lemma" style="width:100px">'
      + '<input id="sx-limit" type="number" min="1" max="500" value="100"'
      + ' style="width:64px" title="How many tokens">'
      + '<button class="btn primary" id="sx-go">Search</button>'
      + '</div><div id="sx-out"></div></div>';
    // The module list is built from what a probe actually returns, so an empty
    // dropdown is a real answer -- "you have none" -- rather than a guess at
    // which installed module might be one.
    const probe = await api('syntax/search', { limit: 200 });
    const sel = $('#sx-mod');
    const mods = [...new Map((probe.items || [])
      .map(i => [i.module_id, i.module])).entries()];
    if (!mods.length) {
      sel.innerHTML = '<option value="">none installed</option>';
      sel.disabled = true;
      $('#sx-out').innerHTML = '<div class="empty">' + esc(probe.note || '')
        + '</div>';
      $('#sx-go').disabled = true;
      return;
    }
    sel.innerHTML = '<option value="">All treebanks</option>'
      + mods.map(m => '<option value="' + esc(m[0]) + '">' + esc(m[1])
        + '</option>').join('');
    $('#sx-out').innerHTML = '<div class="empty tiny">Fill any field and '
      + 'press Search.</div>';
    $('#sx-go').onclick = () => this.run(body);
  },

  async run(body) {
    const out = $('#sx-out');
    out.innerHTML = '<div class="st-loading">Searching…</div>';
    const r = await api('syntax/search', {
      id: $('#sx-mod').value, upos: $('#sx-upos').value.trim(),
      deprel: $('#sx-deprel').value.trim(), form: $('#sx-form').value.trim(),
      lemma: $('#sx-lemma').value.trim(), limit: $('#sx-limit').value || 100 });
    if (!r.ok) { out.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    const items = r.items || [];
    if (!items.length) {
      out.innerHTML = '<div class="empty">' + esc(r.note || 'No token matched.')
        + '</div>';
      return;
    }
    out.innerHTML = '<div class="tiny muted" style="margin:8px 0">' + r.total
      + ' token' + (r.total === 1 ? '' : 's')
      + (r.truncated ? ' — more matched; the window was cut short' : '') + '</div>'
      + items.map((it, i) => '<div class="org-card"><div class="org-h">'
        + '<b>' + esc(it.token.form || '') + '</b>'
        + '<span class="muted tiny"> · ' + esc(it.token.upos || '?')
        + ' : ' + esc(it.token.deprel || '?') + '</span>'
        + '<span class="org-a">' + esc(it.module) + ' · ' + esc(it.ref || '')
        + '</span></div>'
        + '<div class="tiny muted">lemma: ' + esc(it.token.lemma || '—') + '</div>'
        + '<div class="tiny"><a href="#" data-sxtree="' + i + '">the whole tree</a></div>'
        + '</div>').join('');
    out.querySelectorAll('[data-sxtree]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      const it = items[+a.dataset.sxtree];
      await this.tree(it.module_id, it.key, it.ref);
    });
  },

  async tree(moduleId, key, ref) {
    const r = await api('syntax/sentence', { id: moduleId, key });
    if (!r.ok) { toast(r.error || 'No tree for that sentence.', 'warn'); return; }
    modal('Syntax: ' + (r.ref || key), '<div class="st-body">'
      + esc(r.text || '') + '</div>'
      + '<pre class="st-tree">' + esc(r.tree) + '</pre>'
      + '<div class="tiny muted">' + esc(r.note || '') + '</div>',
      [{ label: 'Close', cls: 'btn' }]);
  },
};

/* ============================================================= Counsel
 *
 * Pastoral situations, not doctrines.  The seed passages are long-settled
 * public-domain knowledge -- a reference is a fact, not prose -- and
 * everything else is read out of what is installed.  The panel says which is
 * which, because a seed passage and a search hit are not the same kind of
 * thing and should not look as though they were. */
const Counsel = {
  async load(body) {
    const t = await api('counsel/topics');
    const topics = t.topics || [];
    const wanted = ($('#g-term').value || '').trim();
    body.innerHTML = '<div class="dash-card"><div class="dash-h">Counseling'
      + '</div><div class="tiny muted" style="margin-bottom:8px">'
      + esc(t.note || '') + '</div>'
      + '<div class="st-tools" style="gap:6px;flex-wrap:wrap">'
      + '<select id="cs-topic">' + topics.map(x => '<option value="'
        + esc(x) + '">' + esc(x) + '</option>').join('') + '</select>'
      + '<button class="btn primary" id="cs-go">Guide</button>'
      + '</div><div id="cs-out"></div></div>';
    $('#cs-go').onclick = () => { $('#g-term').value = $('#cs-topic').value; this.run(body); };
    $('#cs-topic').onchange = () => { $('#g-term').value = $('#cs-topic').value; };
    // A topic typed into the Guides toolbar rather than picked from the list
    // still has to reach the guide, so it is adopted as a temporary option
    // instead of being ignored.
    if (wanted && !topics.includes(wanted)) {
      sel_add($('#cs-topic'), wanted);
    }
    if (wanted) $('#cs-topic').value = wanted;
    if (wanted) this.run(body);
    else $('#cs-out').innerHTML = '<div class="empty tiny">Choose a topic.</div>';
  },

  async run(body) {
    const topic = ($('#g-term').value || '').trim();
    const out = $('#cs-out');
    if (!topic) { out.innerHTML = '<div class="empty">Pick a topic.</div>'; return; }
    out.innerHTML = '<div class="st-loading">Gathering…</div>';
    const r = await api('counsel/guide', { topic });
    if (!r.ok) {
      const close = (r.close || []).map(c => '<a href="#" data-cs="' + esc(c)
        + '">' + esc(c) + '</a>').join(', ');
      out.innerHTML = '<div class="warn">' + esc(r.error) + '</div>'
        + (close ? '<div class="tiny">did you mean: ' + close + '</div>' : '');
      out.querySelectorAll('[data-cs]').forEach(a => a.onclick = (e) => {
        e.preventDefault();
        $('#g-term').value = a.dataset.cs;
        sel_add($('#cs-topic'), a.dataset.cs);
        $('#cs-topic').value = a.dataset.cs;
        this.run(body);
      });
      return;
    }
    const sec = (label, note, inner) =>
      '<div class="st-sec open"><div class="st-h">' + esc(label)
      + (note ? ' <span class="tiny muted">' + esc(note) + '</span>' : '')
      + '</div>' + inner + '</div>';
    let h = sec('Seed passages', 'long-settled references',
      '<div class="pg-xref">' + (r.seed_passages || []).map(p =>
        '<a href="#">' + esc(p) + '</a>').join('') + '</div>');
    if ((r.verses || []).length) {
      h += sec('In your Bibles', 'verses carrying the word',
        '<div class="pg-xref">' + r.verses.map(v => '<a href="#">'
          + esc(v) + '</a>').join('') + '</div>');
    }
    if ((r.books || []).length) {
      h += sec('In your books', r.books.length + ' hits',
        r.books.map(b => '<div class="st-note"><div class="st-src">'
          + esc(b.module_id ? ((modById(b.module_id) || {}).name || b.module_id)
            : '') + '</div>'
          + (b.ref ? '<div class="st-t">' + esc(b.ref) + '</div>' : '')
          + '<div class="st-body">' + esc(b.snippet) + '</div></div>').join(''));
    }
    h += '<div class="tiny muted" style="margin-top:8px">' + esc(r.note) + '</div>';
    out.innerHTML = h;
    out.querySelectorAll('.pg-xref a').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      App.show('workspace');
      Reader.openRefAnywhere(a.textContent);
    });
  },
};

/* ==================================================== Sermon outlines
 *
 * The authors' own points, read out of sermon-form works you own.  Nothing
 * is composed, summarised or rearranged: if no installed work mentions the
 * passage, the panel says so rather than filling the space with something
 * that reads like an outline but is nobody's. */