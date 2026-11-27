/* AI Assistant -- chat over the installed library.
 *
 * The answer is streamed, not awaited whole: a model takes tens of seconds and
 * the reader should watch it arrive.  The transport is the server's SSE endpoint
 * (`/api/ai/stream`), read through a fetch body reader -- the same request the
 * `post()` helper makes, only consumed while it is still open.
 *
 * Two things are deliberately visible in the UI, because they are the reasons
 * A grounded assistant is trusted and a plain chatbot is not:
 *   - the sources are shown *before* the answer, so they cannot be reconstructed
 *     after the fact to fit a reply;
 *   - a source chip opens the passage in the workspace, so a claim can be
 *     checked in one click instead of being taken on faith.
 */
const Ai = {
  providers: [],
  settings: {},
  history: [],        // [{role, content}] -- sent back for continuity
  chatId: '',         // the conversation this is, once it has been written down
  context: null,      // a passage the reader has put in front of the assistant
  sources: [],        // citations for the current answer
  ctrl: null,         // AbortController for the in-flight stream
  sending: false,     // whether the Send button is currently acting as Stop
  tip: null,          // the citation tooltip, when one is showing
  editing: -1,        // the index of the question being edited, or -1
  modelsFor: {},      // provider id -> models discovered from the server
  probeResult: {},    // provider id -> last probe() reply (Test status)
  ownCount: {},       // how much of the reader's own material there is
  topicCache: {},     // topic -> {text, cites} -- a topic asked once is free
                        // to ask again, for as long as the app is open
  topicCacheOrder: [],  // the topics in the cache, oldest first
  topicQuestionsCache: {},  // topic -> [questions], written in a call of
                        // their own and therefore kept apart from the answer
  topicQuestionsOrder: [],  // same bounded lifetime as the answers

  els() {
    return {
      chat: $('#ai-chat'), head: $('#ai-head'), note: $('#ai-note'),
      input: $('#ai-input'), send: $('#ai-send'),
      model: $('#ai-model'), lib: $('#ai-use-library'),
      mine: $('#ai-use-mine'), deep: $('#ai-deep-research'),
      scope: $('#ai-scope'), recent: $('#ai-recent'),
    };
  },

  /* The scopes the library can be narrowed to.
   *
   * A scope is the reader's *intent* -- "the commentary collection" -- and
   * not the list of resources it resolves to, so a book added to a collection
   * is included the moment it is added.  The library is a great deal of
   * material, and a reader asking about one commentary does not want the
   * answer drawn from two hundred atlases.
   */
  async loadScopes() {
    const e = Ai.els();
    if (!e.scope) return;
    let r;
    try { r = await api('ai/scope'); } catch (err) { return; }
    const cur = (r && r.scope) || Ai.settings.scope || '';
    e.scope.innerHTML = '';
    const groups = new Map();
    (r.scopes || []).forEach(s => {
      const g = s.group || '';
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(s);
    });
    groups.forEach((items, g) => {
      const parent = g ? document.createElement('optgroup') : e.scope;
      if (g) { parent.label = g; e.scope.appendChild(parent); }
      items.forEach(s => {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = s.label;
        if (s.id === cur) o.selected = true;
        parent.appendChild(o);
      });
    });
    e.scope.onchange = async () => {
      await post('ai/settings', { scope: e.scope.value });
      Ai.settings.scope = e.scope.value;
      const t = e.scope.selectedOptions && e.scope.selectedOptions[0];
      toast('Reading ' + ((t && t.textContent) || 'the library'));
    };
  },

  /* The conversations the reader has had.
   *
   * A modal rather than a dropdown, because each conversation has three
   * things to do with it -- open it, rename it, forget it -- and a dropdown
   * with three-dots menus in it is a lot of machinery for a list of five
   * items.
   */
  async recent() {
    let r;
    try { r = await api('ai/chats'); } catch (e) { return; }
    const chats = r.chats || [];
    const body = chats.length
      ? chats.map(c => '<div class="org-card" data-chat="' + esc(c.id) + '">'
          + '<div class="org-h"><b>' + esc(c.title) + '</b>'
          + '<span class="muted tiny"> · ' + c.turns + ' turn'
          + (c.turns === 1 ? '' : 's') + '</span></div>'
          + '<div class="row" style="gap:6px;margin-top:4px">'
          + '<button class="btn tiny" data-open="' + esc(c.id) + '">Open</button>'
          + '<button class="btn tiny" data-rename="' + esc(c.id) + '">Rename</button>'
          + '<button class="btn tiny danger" data-del="' + esc(c.id) + '">Delete</button>'
          + '</div></div>').join('')
      : '<div class="empty">No conversations yet. The ones you have are kept '
        + 'on this machine.</div>';
    modal('Recent conversations', body, [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-open]').forEach(b => b.onclick = async () => {
      closeModal();
      await Ai.openChat(b.dataset.open);
    });
    $$('#modal-body [data-rename]').forEach(b => b.onclick = async () => {
      const title = prompt('Name this conversation:', (b.closest('.org-card')
        .querySelector('b') || {}).textContent || '');
      if (!title || !title.trim()) return;
      await post('ai/chats', { action: 'rename', id: b.dataset.rename,
                               title: title.trim() });
      Ai.recent();
    });
    $$('#modal-body [data-del]').forEach(b => b.onclick = async () => {
      if (!confirm('Delete this conversation? It cannot be recovered.')) return;
      await post('ai/chats', { action: 'delete', id: b.dataset.del });
      if (b.dataset.del === Ai.chatId) {
        Ai.chatId = '';
        Ai.history = [];
        Ai.sources = [];
        Ai.renderChat();
      }
      Ai.recent();
    });
  },

  /* Open a conversation and carry on in it. */
  async openChat(id) {
    let r;
    try { r = await api('ai/chats', { action: 'open', id: id }); }
    catch (e) { return; }
    const chat = r && r.chat;
    if (!chat) return;
    Ai.chatId = chat.id;
    Ai.history = (chat.turns || []).map(t => ({
      role: t.role, content: t.content, citations: t.citations || [],
    }));
    Ai.sources = [];
    Ai.renderChat();
    App.show('ai');
  },

  /* Pick the conversation back up.
   *
   * Not done when a conversation is already open: the reader may be in the
   * middle of one, and a panel that silently replaced what they were
   * reading with something older would be worse than one that started blank.
   */
  async restore() {
    if (Ai.history.length) return;
    let r;
    try { r = await api('ai/chats', { action: 'open', id: 'latest' }); }
    catch (e) { return; }
    const chat = r && r.chat;
    if (!chat || !chat.turns || !chat.turns.length) return;
    Ai.chatId = chat.id;
    Ai.history = chat.turns.map(t => ({
      role: t.role, content: t.content, citations: t.citations || [],
    }));
    Ai.renderChat();
  },

  /* Write the exchange down.
   *
   * The whole exchange is written each time, so a question the reader edited
   * and asked again replaces the attempt rather than sitting beside it.  A
   * failure to save is not worth interrupting the reader for: the answer is
   * on screen either way, and the conversation is a convenience.
   */
  async persist() {
    if (!Ai.history.length) return;
    try {
      const r = await post('ai/chats', { action: 'save', id: Ai.chatId,
                                          turns: Ai.history });
      if (r && r.chat && r.chat.id) Ai.chatId = r.chat.id;
    } catch (e) { /* the answer is on screen; it is only not kept */ }
  },

  async load() {
    if (aiOff()) return;
    const r = await api('ai/providers');
    Ai.providers = r.providers || [];
    Ai.settings = r.settings || {};
    Ai.ownCount = r.mine || {};
    const e = Ai.els();
    if (e.lib) e.lib.checked = Ai.settings.use_library !== false;
    if (e.mine) e.mine.checked = Ai.settings.use_mine !== false;
    if (e.deep) e.deep.checked = !!Ai.settings.deep_research;
    // These three live in the chat header, not the settings modal. They must
    // write through to the same settings, or ticking them changes nothing.
    const wireBar = (box, key, label) => {
      if (!box || box.onchange) return;
      box.onchange = async () => {
        const r = await post('ai/settings', { [key]: box.checked });
        if (!r || r.ok === false) {
          box.checked = !box.checked;
          toast((r && r.error) || 'Could not change ' + label + '.', 'err');
          return;
        }
        Ai.settings[key] = box.checked;
        toast(label + ' ' + (box.checked ? 'on' : 'off'));
      };
    };
    wireBar(e.lib, 'use_library', 'Use my library');
    wireBar(e.mine, 'use_mine', 'My own material');
    wireBar(e.deep, 'deep_research', 'Deep research');
    Ai.renderModels();
    Ai.renderHead();
    Ai.loadScopes();
    if (e.send) e.send.onclick = () => {
      if (Ai.sending) Ai.stop(); else Ai.send();
    };
    if (e.input) {
      e.input.onkeydown = (ev) => {
        // Enter sends; Shift+Enter is a newline -- the convention every chat
        // box uses, and the one that stops a half-typed question being sent.
        if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); Ai.send(); }
      };
    }
    if (e.model) e.model.onchange = () => Ai.saveModel();
    const cfgBtn = $('#ai-settings');
    if (cfgBtn) cfgBtn.onclick = () => App.show('aisettings');
    const clearBtn = $('#ai-clear');
    if (clearBtn) clearBtn.onclick = () => Ai.newChat();
    if (e.recent) e.recent.onclick = () => Ai.recent();
    const expBtn = $('#ai-export');
    if (expBtn) expBtn.onclick = () => Ai.exportChat();
    const plusBtn = $('#ai-plus');
    if (plusBtn) plusBtn.onclick = () => Ai.openBooks();
    if (!Ai.history.length) Ai.renderChat();
    // Pick the conversation back up where it was left.  The reader asked a
    // question on Sunday and is asking it again on Wednesday; the answer from
    // Sunday is worth more than the tokens to re-derive it.
    Ai.restore();
    // Ask the provider what it actually has, without blocking the panel: the
    // preset list shows first, and discovery quietly replaces it when the
    // server answers.  A server that is not running is a normal state here,
    // not an error to show on load.
    Ai.discover().catch(() => {});
  },

  /* Providers and settings are needed by anything that sends a request, not just
   * by the chat panel -- the Sermon Builder's research box sends one without the
   * panel ever having been opened.  This fetches them once and does nothing
   * after that, so a caller never has to know whether `load()` has run. */
  async ensure() {
    if (Ai.providers.length && Ai.settings.provider) return;
    if (Ai.ensuring) return Ai.ensuring;
    Ai.ensuring = (async () => {
      try {
        const r = await api('ai/providers');
        Ai.providers = r.providers || [];
        Ai.settings = r.settings || {};
        Ai.ownCount = r.mine || {};
      } catch (e) { /* leave the defaults; the caller reports the failure */ }
      Ai.ensuring = null;
    })();
    return Ai.ensuring;
  },

  provider() {
    return Ai.providers.find(p => p.id === Ai.settings.provider)
        || Ai.providers[0];
  },

  /* A one-line reason the assistant cannot be used yet, or '' when it can.
   * Callers show this instead of sending a request that is certain to fail. */
  blocked() {
    if (aiOff()) return 'AI Assistant is not set up. Open Settings → AI Assistant to enable it.';
    const p = Ai.provider();
    if (!p) return 'No AI provider is configured. Open Settings → AI.';
    // A key is missing before a model is missing: it is the first thing that
    // stops a free tier working, and "no API key" is a much clearer thing to
    // be told than a request that fails on the way out.
    if (p.key_required && !p.key_set) {
      return 'No API key for ' + p.name
        + '. Open Settings → AI and paste one.';
    }
    if (!Ai.settings.model && !Ai.modelList(p).length) {
      return 'No model is chosen for ' + p.name
        + '. Open Settings → AI and press Test.';
    }
    return '';
  },

  /* The models to offer for a provider: what the server told us it has, or the
   * preset list if it has not answered.  One place decides this so the chat
   * picker and the settings picker can never disagree. */
  modelList(p) {
    const found = p && Ai.modelsFor[p.id];
    return (found && found.length) ? found : ((p && p.models) || []);
  },

  /* Record discovered models and, if the saved model is not among them, move to
   * one that is.  A stale name -- an Ollama tag that was deleted -- is the most
   * likely reason a working setup suddenly 404s, and re-pointing at a model
   * that demonstrably exists is the fix that needs no debugging. */
  async adoptModels(providerId, models) {
    if (!models || !models.length) return;
    Ai.modelsFor[providerId] = models;
    if (providerId === Ai.settings.provider
        && models.indexOf(Ai.settings.model) < 0) {
      Ai.settings.model = models[0];
      await post('ai/settings', { model: models[0] });
    }
  },

  async discover() {
    const p = Ai.provider();
    if (!p) return;
    const r = await api('ai/models', { provider: p.id });
    Ai.probeResult[p.id] = r;
    if (!r.ok) return;
    await Ai.adoptModels(p.id, r.models);
    Ai.renderModels();
    Ai.renderHead();
  },

  renderHead() {
    const e = Ai.els();
    if (!e.head) return;
    const link = ' · <a href="#" id="ai-head-cfg">change</a>';
    const wire = () => {
      const cfg = $('#ai-head-cfg');
      if (cfg) cfg.onclick = (ev) => { ev.preventDefault(); App.show('aisettings'); };
    };
    const p = Ai.provider();
    if (!p) { e.head.textContent = 'No provider configured.'; return; }
    const where = p.local ? 'on this machine' : 'cloud';
    e.head.innerHTML = 'Provider: <b>' + esc(p.name) + '</b> (' + where
      + ') · model <b>' + esc(Ai.settings.model || '—') + '</b>' + link;
    wire();
    if (e.note) {
      e.note.innerHTML = p.local
        ? 'Private: the passages and your question stay on this machine.'
        : (p.free
          ? 'Free tier: no charge for the calls, but this is still the cloud — '
            + 'the passages relevant to your question and the question itself '
            + 'are sent to ' + esc(p.name) + '.'
          : 'Cloud: the passages relevant to your question and the question '
            + 'itself are sent to ' + esc(p.name) + '.');
    }
  },

  renderModels() {
    const e = Ai.els();
    if (!e.model) return;
    const p = Ai.provider();
    e.model.innerHTML = '';
    const models = Ai.modelList(p);
    if (!models.length) {
      const o = document.createElement('option');
      o.value = ''; o.textContent = 'no models — press Test';
      e.model.appendChild(o);
      return;
    }
    models.forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      if (m === Ai.settings.model) o.selected = true;
      e.model.appendChild(o);
    });
  },

  async saveModel() {
    const e = Ai.els();
    Ai.settings.model = e.model.value;
    await post('ai/settings', { model: e.model.value });
    Ai.renderHead();
  },

  renderChat() {
    const e = Ai.els();
    if (!e.chat) return;
    if (!Ai.history.length) {
      e.chat.innerHTML = '<div class="ai-empty">Ask a question and G-Bible '
        + 'answers from the books you have installed, citing each one. '
        + 'Under <b>Settings → AI</b> you can choose a local server or a '
        + 'cloud provider.</div>';
      return;
    }
    e.chat.innerHTML = '';
    Ai.history.forEach((m, i) => e.chat.appendChild(Ai.bubble(m, i)));
    e.chat.scrollTop = e.chat.scrollHeight;
  },

  bubble(m, i) {
    const b = el('div', 'ai-msg ' + (m.role === 'user' ? 'user' : 'bot'));
    if (m.role === 'user' && Ai.editing === i) {
      b.appendChild(Ai.editBox(m, i));
      return b;
    }
    const body = el('div', 'ai-body');
    body.innerHTML = m.role === 'user' ? esc(m.content) : Ai.render(m.content);
    b.appendChild(body);
    if (m.role === 'assistant' && m.backend) {
      const tag = el('div', 'ai-backend');
      const local = m.backend === 'local';
      tag.innerHTML = '<span class="chip ' + (local ? 'pd' : 'no') + '">'
        + (local ? 'Answered by a local server' : 'Answered via API')
        + '</span>';
      b.appendChild(tag);
    }
    if (m.role === 'assistant' && m.webStatus) {
      b.appendChild(el('div', 'ai-web-status', m.webStatus));
    }
    if (m.role === 'user') {
      // The pencil.  Asking again is not the same as adding to the
      // conversation: the turns from the edited question onward are
      // *replaced*, so the reader is left with one exchange and not two
      // versions of it.
      const pen = el('button', 'ai-edit', '\u270e');
      pen.title = 'Ask this again -- the answer is replaced, not kept';
      pen.onclick = () => { Ai.editing = i; Ai.renderChat(); };
      b.appendChild(pen);
    }
    if (m.role === 'assistant' && m.citations && m.citations.length) {
      const web = m.citations.filter(c => c.external && c.url);
      const local = m.citations.filter(c => !c.external);
      if (local.length) b.appendChild(Ai.sourceList(local));
      if (web.length) {
        const cited = new Set(Array.from(
          (m.content || '').matchAll(/\[(\d+)\]/g), x => Number(x[1])));
        const used = web.filter(c => cited.has(Number(c.n)));
        const checked = web.filter(c => !cited.has(Number(c.n)));
        const box = el('div', 'ai-web-used');
        const addPages = (heading, pages) => {
          if (!pages.length) return;
          box.appendChild(el('div', 'ai-web-used-h', heading));
          pages.forEach(c => {
            const a = el('a', 'ai-web-site', c.module_name || c.title || c.url);
            a.href = c.url;
            a.target = '_blank';
            a.rel = 'noopener';
            a.title = c.title || c.url;
            box.appendChild(a);
          });
        };
        addPages('Websites cited', used);
        addPages('Pages checked, not cited', checked);
        b.appendChild(box);
      }
    }
    return b;
  },

  /* The editor for a question the reader wants to ask again.
   *
   * The scope in the header applies to the new question, so the reader can
   * narrow what the assistant reads and ask again in one go.
   */
  editBox(m, i) {
    const box = el('div', 'ai-editbox');
    const ta = el('textarea', 'ai-edit-in');
    ta.value = m.content || '';
    ta.rows = 2;
    box.appendChild(ta);
    const row = el('div', 'ai-edit-row');
    const save = el('button', 'btn tiny primary', 'Ask again');
    const cancel = el('button', 'btn tiny', 'Cancel');
    row.appendChild(save);
    row.appendChild(cancel);
    box.appendChild(row);
    const go = () => {
      const q = (ta.value || '').trim();
      if (!q) { toast('Ask something.', 'warn'); return; }
      Ai.editing = -1;
      Ai.history = Ai.history.slice(0, i);
      Ai.renderChat();
      Ai.run({ question: q }, q);
    };
    save.onclick = go;
    ta.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); }
      if (e.key === 'Escape') { Ai.editing = -1; Ai.renderChat(); }
    };
    cancel.onclick = () => { Ai.editing = -1; Ai.renderChat(); };
    setTimeout(() => { ta.focus(); }, 30);
    return box;
  },

  /* The fragment of a source, with the words that carried the claim marked.
   *
   * The marks come from the server, which compared the answer's sentence with
   * the source's; they are offsets into the fragment text, so the words are
   * wrapped in place rather than looked up again here. */
  fragmentHtml(frag) {
    const text = (frag && frag.fragment) || '';
    const marks = (frag && frag.marks) || [];
    if (!text || !marks.length) return esc(text);
    let out = '', at = 0;
    marks.forEach(m => {
      const a = Math.max(0, m[0] || 0);
      const b = Math.min(text.length, m[1] || 0);
      if (a < at || b <= a) return;
      out += esc(text.slice(at, a)) + '<mark>' + esc(text.slice(a, b))
           + '</mark>';
      at = b;
    });
    return out + esc(text.slice(at));
  },

  /* A small tooltip, for the citation chips.
   *
   * The native title attribute cannot mark anything, and the whole point of
   * the fragment is which words are marked.  So the chip gets its own, and
   * the title is left empty rather than showing a second, unmarked copy over
   * the top of it.
   */
  showTip(anchor, html) {
    Ai.hideTip();
    const t = el('div', 'ai-tip');
    t.innerHTML = html;
    document.body.appendChild(t);
    const r = anchor.getBoundingClientRect();
    const b = t.getBoundingClientRect();
    let left = r.left;
    if (left + b.width > window.innerWidth - 8) {
      left = window.innerWidth - b.width - 8;
    }
    if (left < 8) left = 8;
    let top = r.bottom + 6;
    if (top + b.height > window.innerHeight - 8) {
      top = r.top - b.height - 6;
    }
    t.style.left = left + 'px';
    t.style.top = Math.max(8, top) + 'px';
    Ai.tip = t;
  },

  hideTip() {
    if (Ai.tip) { Ai.tip.remove(); Ai.tip = null; }
  },

  /* Citation markers in the prose are turned into the numbers the source list
   * beneath uses, and nothing else is interpreted: the model's output is text,
   * not markup, and running it through a Markdown renderer would let it emit
   * links and images the reader did not ask for. */
  /* One rendered assistant answer.  The model's output is never trusted as
   * HTML: everything is `esc`d first, and the only tags on the page are ones
   * this function itself generates -- the citation chips, and a small planned
   * subset of Markdown (headings, bold, italics, lists, quotations, code
   * fences) that every model leans towards when it explains things.  Render
   * those, rather than show their marks, and an answer reads like a written
   * page instead of a wall of escaped punctuation.  Anything outside the
   * subset stays literal, so text that happens to contain a stray asterisk
   * still reads as text. */
  render(text) {
    let html = esc(text || '');
    html = html.replace(/\[(\d+)\]/g, '<span class="ai-cite">[$1]</span>');
    return Ai.blocks(html);
  },

  /* The block pass, over already-escaped text: paragraphs from runs of
   * consecutive lines, a heading from a leading `#`, a quotation from a
   * leading `>`, a list from lines that start `- `, `* `, a bullet, or a
   * number with a stop or bracket, and a fenced code block from ``` lines.
   * A stream cut mid-fence simply emits its text as a code block, and a cut
   * mid-list emits the items it received -- nothing is dropped while the
   * model is still typing.  Every block's contents go through Ai.inline, so
   * no tag is ever emitted but what this code produced. */
  blocks(html) {
    const lines = html.split('\n');
    const out = [];
    let para = [];          // lines of the paragraph being built
    let list = null;        // 'ul' or 'ol' while a list is open
    let quote = [];         // lines of the quotation being built
    let code = null;        // lines of the fenced block being built

    const closePara = () => {
      if (para.length) { out.push('<p>' + Ai.inline(para.join('<br>')) + '</p>'); para = []; }
    };
    const closeList = () => {
      if (list) { out.push('</' + list + '>'); list = null; }
    };
    const closeQuote = () => {
      if (quote.length) { out.push('<blockquote>' + Ai.inline(quote.join('<br>')) + '</blockquote>'); quote = []; }
    };
    const closeCode = () => {
      if (code !== null) { out.push('<pre class="ai-code">' + code.join('<br>') + '</pre>'); code = null; }
    };
    const closeAll = () => { closePara(); closeList(); closeQuote(); };

    for (const raw of lines) {
      const line = raw.trim();
      let m;
      if (code !== null) {
        if (/^`{3,}$/.test(line)) { closeCode(); }
        else code.push(line);
        continue;
      }
      if (/^`{3,}/.test(line)) { closeAll(); closeCode(); code = []; continue; }
      if (!line) { closeAll(); continue; }
      if ((m = line.match(/^#{1,4}\s+(.+)$/))) {
        closeAll();
        out.push('<div class="ai-h">' + Ai.inline(m[1]) + '</div>');
        continue;
      }
      if ((m = line.match(/^&gt;\s?(.*)$/))) {  // '>' -- esc already had it
        closeAll();
        quote.push(m[1]);
        continue;
      }
      if ((m = line.match(/^[-*\u2022]\s+(.*)$/))) {
        if (list !== 'ul') { closeAll(); list = 'ul'; out.push('<ul>'); }
        out.push('<li>' + Ai.inline(m[1]) + '</li>');
        continue;
      }
      if ((m = line.match(/^\d{1,2}[.)]\s+(.*)$/))) {
        if (list !== 'ol') { closeAll(); list = 'ol'; out.push('<ol>'); }
        out.push('<li>' + Ai.inline(m[1]) + '</li>');
        continue;
      }
      closeAll();
      para.push(line);
    }
    closeCode();
    closeAll();
    return out.join('');
  },

  /* The inline pass, over one block's escaped text: code spans first, then
   * bold, then italics -- each applied only between characters this pass
   * already knows about, so a heading, a citation chip or a list item all get
   * the same treatment and none of them ever sees a tag the others wrote.
   * Italics are the guarded one: an emphasis has to open after whitespace, a
   * bracket or the start of the line, and close before whitespace or
   * punctuation, so "3*4 and 5*6" and a lone footnote marker keep their
   * asterisks and read as arithmetic and a footnote.  Bold runs first, so
   * **pairs are gone** before this looks at single. */
  inline(s) {
    return s
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(\[])\*([^*\s][^*]*?)\*(?=$|[\s.,;:!?)\]])/g,
               '$1<em>$2</em>');
  },

  /* Briefly mark the passage a citation opened so the reader can see which
   * verse the chip landed on.  The pane
   * is rebuilt on focus, so wait for that before looking for the element. */
  async flashCite(key) {
    if (!key) return;
    await new Promise(r => setTimeout(r, 0));
    const sel = '[data-k="' + (window.CSS && CSS.escape ? CSS.escape(key)
      : String(key).replace(/["\\]/g, '\\$&')) + '"]';
    const node = document.querySelector('.verse' + sel)
      || document.querySelector(sel);
    if (!node) return;
    if (node._citeFlashT) clearTimeout(node._citeFlashT);
    node.classList.remove('cite-flash');
    // Force a reflow so a second flash on the same verse restarts the CSS
    // animation instead of continuing the first one.
    void node.offsetWidth;
    node.classList.add('cite-flash');
    try {
      node.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    } catch (e) { /* jsdom / older engines */ }
    node._citeFlashT = setTimeout(() => {
      node.classList.remove('cite-flash');
      node._citeFlashT = null;
    }, 2200);
  },

  sourceList(cites) {
    const w = el('div', 'ai-sources');
    cites.forEach(c => {
      const name = c.label || c.title || c.module_name;
      const chip = el('button', 'ai-src');
      chip.innerHTML = '<b>[' + c.n + ']</b> ' + esc(name)
        + ' <span class="tiny muted">— ' + esc(c.module_name) + '</span>'
        + (c.external ? ' <span class="tiny">web</span>' : '');
      chip.title = c.text || '';
      // The fragment: the part of the source this answer actually leaned on,
      // with the words it leaned on marked.  The server compared the two
      // texts; the reader is shown the result.
      if (c.fragment && c.fragment.fragment) {
        chip.classList.add('has-frag');
        chip.title = '';
        const show = () => Ai.showTip(chip,
          '<div class="ai-tip-src">' + esc(c.module_name || '') + '</div>'
          + '<div class="ai-tip-frag">'
          + Ai.fragmentHtml(c.fragment) + '</div>'
          + '<div class="ai-tip-note">The words this answer relied on.'
          + '</div>');
        chip.onmouseenter = show;
        chip.onfocus = show;
        chip.onmouseleave = () => Ai.hideTip();
        chip.onblur = () => Ai.hideTip();
      }
      const mod = c.module_id ? modById(c.module_id) : null;
      // The reader's own material opens the thing itself, and it is checked
      // first: a note titled "Notes on John 3" reads exactly like a Bible
      // reference, and opening it as one would send the reader to a verse
      // instead of to their own words.
      if (c.own) {
        chip.classList.add('own');
        chip.title = (c.text || '') + '\n\nOpens your own '
          + (c.own.kind || 'material') + '.';
        chip.onclick = () => Ai.openOwn(c.own);
      } else if (c.external && c.url) {
        // An outside page is not a library resource: open the exact page the
        // reader approved, in a new tab, with no access back to this window.
        chip.classList.add('wr-src');
        chip.title = (c.text || '') + '\n\nOpens the outside page in a new tab.';
        chip.onclick = () => window.open(c.url, '_blank', 'noopener');
      } else if (mod && mod.reader && mod.reader !== 'verse'
                 && mod.reader !== 'audio') {
        // A FactBook, dictionary or book citation names an *entry*, not a
        // verse: "John" in Thompson is not "John 1:1" in a Bible. Check the
        // module first, so a heading with a number in it ("1 JOHN") is not
        // mistaken for a reference and sent to a Bible instead.
        chip.title = (c.text || '') + '\n\nOpens this entry in '
          + (mod.name || 'the library') + '.';
        chip.onclick = async () => {
          await Ai.openEntry(mod, c);
          await Ai.flashCite(c.key);
        };
      } else if (/^[1-3]?\s?[A-Za-z]{2,}/.test(name) && /\d/.test(name)) {
        // A label that reads as a Bible reference opens; a commentary page label
        // ("Verse 8") does not, and says so rather than opening something wrong.
        chip.onclick = () => Reader.openRefAnywhere(name.replace(/\./g, ' '));
      } else if (c.module_id && c.key && mod) {
        chip.title = (c.text || '') + '\n\nOpens this entry in a pane.';
        chip.onclick = async () => {
          await Reader.focusRef(mod, c.key);
          await Ai.flashCite(c.key);
        };
      }
      w.appendChild(chip);
    });
    return w;
  },

  /* Open a citation that points at an entry in a keyed resource.
   *
   * The key is best: it is the module's own address for the article.  A guide
   * can quote an entry without carrying its key though, and then the chip used
   * to have no click handler at all -- the AI looked as if it simply would not
   * open Thompson.  Fall back to a heading search in that same module, so
   * "John" lands on John rather than on the first page of the book. */
  async openEntry(mod, c) {
    let key = (c.key || '').trim();
    if (!key && mod.reader === 'topic') {
      const term = (c.label || c.title || '').trim();
      if (term) {
        const r = await api('factbook-search', {
          q: term, module_ids: [mod.id], limit: 10 });
        const results = r.results || [];
        const fold = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
        const want = fold(term);
        const hit = results.find(x => fold(x.key) === want
          || fold(x.title) === want) || results[0];
        if (hit) key = hit.key || '';
      }
    }
    App.show('workspace');
    if (!key) { toast('That entry has no key to open.', 'warn'); return; }
    return Reader.focusRef(mod, key);
  },

  /* Open one of the reader's own documents from a citation.
   *
   * A citation that cannot be opened is a claim the reader has to take on
   * trust, which is the one thing the whole design is trying to avoid.  So
   * each kind opens the thing it names: a note opens in the editor, a
   * highlight opens the verse it marked, a clipping opens its folder. */
  openOwn(own) {
    const kind = (own && own.kind) || '';
    if (kind === 'note' || kind === 'journal' || kind === 'sermon'
        || kind === 'prayer') {
      App.show('notes');
      Notes.edit(own.id);
      return;
    }
    if (kind === 'highlight') {
      const mod = modById(own.module_id);
      if (mod) { App.show('workspace'); Reader.focusRef(mod, own.unit_key); }
      else if (own.ref) { App.show('workspace'); Reader.openRefAnywhere(own.ref); }
      return;
    }
    if (kind === 'clipping') {
      // The clipping id is the folder, not the excerpt: the folder is what the
      // reader recognises, and the excerpt is inside it.
      const folder = (own.folder || '').replace(/^clip:/, '');
      if (folder && typeof Clippings !== 'undefined') Clippings._id = folder;
      App.show('clippings');
      return;
    }
    if (own.ref) { App.show('workspace'); Reader.openRefAnywhere(own.ref); }
  },

  /* Put a passage in front of the assistant, for the reader to ask about.
   *
   * This is one thing reached three ways -- the selection card's "Ask", the
   * "+" button on an open book, and the passage guide -- and it is the same
   * thing each time: the passage becomes the context of the next question,
   * rather than the question itself.
   *
   * A question like "what does Paul mean by this?" is about a *place*, and
   * the search engine cannot find a place from those words.  The passage
   * itself has to be supplied, or the answer is about something else.
   */
  attach(text, label, moduleId, key, moduleName) {
    if (aiOff()) { toast('AI Assistant is not set up.', 'warn'); return; }
    const t = (text || '').trim();
    if (!t) { toast('Nothing to attach.', 'warn'); return; }
    Ai.context = { text: t, label: label || '', module_id: moduleId || '',
                   key: key || '', module_name: moduleName || '' };
    Ai.renderContext();
    const e = Ai.els();
    if (e.input) e.input.focus();
  },

  renderContext() {
    const host = $('#ai-context');
    if (!host) return;
    host.innerHTML = '';
    const c = Ai.context;
    if (!c || !c.text) { host.style.display = 'none'; return; }
    host.style.display = '';
    const box = el('div', 'ai-ctx');
    const head = el('span', 'ai-ctx-label');
    head.textContent = c.label || 'a passage';
    box.appendChild(head);
    const txt = el('span', 'ai-ctx-text');
    const t = c.text.length > 220 ? c.text.slice(0, 220) + '…' : c.text;
    txt.textContent = t;
    box.appendChild(txt);
    const x = el('button', 'ai-ctx-x', '×');
    x.title = 'Remove this passage';
    x.onclick = () => { Ai.context = null; Ai.renderContext(); };
    box.appendChild(x);
    host.appendChild(box);
  },

  /* The books the reader has open, to put the text of into the question.
   *
   * The reader often wants to ask about the passage in front of them without
   * having to select it and copy it.  Each open pane is read at the cursor
   * it is at, so what comes back is the passage they are actually looking
   * at and not the whole book.
   */
  async openBooks() {
    const panes = (S.layout && S.layout.panes) || [];
    const seen = {};
    const books = [];
    panes.forEach(p => {
      if (!p.module_id || seen[p.module_id]) return;
      const m = modById(p.module_id);
      if (!m) return;
      seen[p.module_id] = 1;
      books.push({ id: p.module_id, name: m.name, pane: p });
    });
    if (!books.length) {
      toast('Open a book in the workspace first.', 'warn');
      return;
    }
    const rows = [];
    for (const b of books) {
      let text = '', label = b.name, key = '';
      try {
        const r = await api('read', { id: b.id, cursor: b.pane.cursor || {},
                                      options: b.pane.options || {},
                                      span: 'verse', context: 0 });
        const items = r.items || [];
        text = items.map(i => i.text || '').join(' ').trim();
        label = r.ref_label || (items[0] && items[0].label) || b.name;
        key = (items[0] && items[0].key) || '';
      } catch (e) { /* a pane that cannot be read is simply left out */ }
      if (text) rows.push({ id: b.id, name: b.name, label, text, key });
    }
    if (!rows.length) {
      toast('Nothing readable in the open panes.', 'warn');
      return;
    }
    const body = rows.map(r => '<div class="org-card">'
      + '<div class="org-h"><b>' + esc(r.label) + '</b>'
      + '<span class="muted tiny"> · ' + esc(r.name) + '</span></div>'
      + '<div class="tiny" style="margin:4px 0 6px;max-height:70px;'
      + 'overflow:hidden;opacity:.8">' + esc(r.text.slice(0, 200)) + '</div>'
      + '<button class="btn tiny" data-use="' + esc(r.id) + '">Ask about this</button>'
      + '</div>').join('');
    modal('What are you reading?', body, [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-use]').forEach(bt => bt.onclick = () => {
      const r = rows.find(x => x.id === bt.dataset.use);
      if (!r) return;
      closeModal();
      App.show('ai');
      Ai.attach(r.text, r.label, r.id, r.key, r.name);
    });
  },

  /* The conversation as a Markdown file, or as text to paste.
   *
   * A file and not a link: a link would put the conversation in a URL, where
   * it is copied into browser history and the URL bar and wherever a link is
   * pasted -- and a conversation is the reader's own writing.  A file the
   * reader attaches to a message themselves is a share they chose.
   *
   * Both ways are offered because both are wanted: pasting into a message is
   * the common case, and the file is the one that keeps the formatting.
   */
  async exportChat() {
    if (!Ai.history.length) { toast('Nothing to export yet.', 'warn'); return; }
    const first = Ai.history.find(h => h.role === 'user');
    const title = (first && first.content) || '';
    let r;
    try {
      r = await post('ai/chat-export', { turns: Ai.history, title: title });
    } catch (e) { r = null; }
    if (!r || !r.ok || !r.markdown) {
      toast('Could not export the conversation.', 'err');
      return;
    }
    const md = r.markdown;
    const name = r.filename || 'conversation.md';
    modal('Export this conversation', '<div class="st-body">'
      + esc(md.slice(0, 400)) + (md.length > 400 ? '…' : '')
      + '</div><div class="tiny muted" style="margin-top:8px">'
      + 'A Markdown document, with each answer’s sources beneath it. '
      + 'It stays a file you send yourself — there is no link.'
      + '</div>', [
        { label: 'Copy', cls: 'btn primary', fn: async () => {
            await Clipboard.write(md);
          } },
        { label: 'Download', cls: 'btn', fn: () => {
            const blob = new Blob([md], { type: 'text/markdown' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = name;
            a.click();
            URL.revokeObjectURL(a.href);
            toast('Exported.');
          } },
        { label: 'Close', cls: 'btn' },
      ]);
  },

  newChat() {
    Ai.history = [];
    Ai.sources = [];
    // A new conversation, not a new name for the old one: the old one stays
    // in the recent list, because the reader may want it back.
    Ai.chatId = '';
    Ai.renderChat();
  },

  /* Send and Stop are one button, so there is no mistaking whether the
   * assistant is working: while a turn is in flight the same primary action
   * reads "Stop" and is styled as a danger action.  Clicking it again aborts
   * the stream; when the answer finishes it becomes "Send" once more.
   */
  setSending(on) {
    Ai.sending = !!on;
    const e = Ai.els();
    if (e.send) {
      e.send.textContent = Ai.sending ? 'Stop' : 'Send';
      e.send.classList.toggle('primary', !Ai.sending);
      e.send.classList.toggle('danger', Ai.sending);
      e.send.title = Ai.sending
        ? 'Stop the assistant — it is still working'
        : 'Send your question';
    }
  },

  stop() {
    if (Ai.ctrl) { Ai.ctrl.abort(); Ai.ctrl = null; }
    // Give immediate feedback; onFinally() will settle it again when the
    // aborted stream actually unwinds.
    Ai.setSending(false);
  },

  async send() {
    if (Ai.sending) return;   // Enter pressed mid-turn: never start a second one
    const e = Ai.els();
    const q = (e.input.value || '').trim();
    if (!q) return;
    e.input.value = '';
    await Ai.run({ question: q }, q);
  },

  /* Explain / summarise / translate a selection.
   *
   * The selection card and the passage guide call this; it puts the reader in
   * the assistant panel with the text already sent.  The panel is the one place
   * AI output lives, so an explanation cites like an answer does and there is no
   * second rendering of model output to keep in step. */
  async ask(kind, text, label, target) {
    const t = (text || '').trim();
    if (!t) { toast('Nothing to work on.', 'warn'); return; }
    App.show('ai');
    const verb = { explain: 'Explain', summarize: 'Summarise',
                   translate: 'Translate' }[kind] || kind;
    let what = label || '';
    if (!what) what = t.length > 56 ? t.slice(0, 56) + '…' : t;
    const display = verb + ' ▸ ' + what + (target ? ' → ' + target : '');
    return Ai.run({ action: kind, text: t, label: label || '',
                    target: target || '' }, display);
  },

  /* Translate asks for its target first, because "Arabic" and "Hebrew" are not
   * things to guess at from the text. */
  async translateText(text, label) {
    const target = prompt('Translate into which language?', 'English');
    if (!target || !target.trim()) return;
    return Ai.ask('translate', text, label, target.trim());
  },

  async run(req, display) {
    if (aiOff()) {
      toast('AI Assistant is not set up. Enable it in Settings → AI Assistant.',
            'warn');
      App.show('aisettings');
      return;
    }
    const e = Ai.els();
    if (!Ai.provider()) {
      toast('Choose a provider first (Settings → AI)', 'err');
      App.show('aisettings');
      return;
    }
    /* Decide about the web before the turn appears in the chat: a denial must
     * not leave an empty assistant bubble behind.  The assistant checks whether
     * the web would help, then asks for this question only. Saying no still
     * answers from the installed library. */
    let webToken = '';
    let webApproved = false;
    const previousQuestion = [...Ai.history].reverse().find(m => m.role === 'user');
    const webQuestion = !req.action && req.question
      && req.question.trim().split(/\s+/).length <= 4 && previousQuestion
      ? previousQuestion.content + ' ' + req.question
      : req.question;
    if (!req.action && req.question && await WebResearch.shouldSearch(webQuestion)) {
      if (await WebResearch.ask()) {
        webApproved = true;
        const web = await WebResearch.gather(webQuestion);
        if (web && web.token) webToken = web.token;
      }
    }
    Ai.history.push({ role: 'user', content: display });
    const bot = { role: 'assistant', content: '', citations: [] };
    Ai.history.push(bot);
    Ai.renderChat();
    const live = e.chat.lastChild ? e.chat.lastChild.querySelector('.ai-body') : null;
    const liveWeb = el('div', 'ai-web-status');
    const liveSources = el('div', 'ai-sources');
    if (e.chat.lastChild) e.chat.lastChild.insertBefore(liveWeb, null);
    if (e.chat.lastChild) e.chat.lastChild.insertBefore(liveSources, null);
    const liveBackend = el('div', 'ai-backend');
    if (e.chat.lastChild) e.chat.lastChild.insertBefore(liveBackend, liveSources);
    Ai.setSending(true);

    Ai.sources = [];
    const useLib = e.lib ? e.lib.checked : true;
    const useMine = e.mine ? e.mine.checked : true;
    const deep = e.deep ? e.deep.checked : false;
    await Ai.streamTo({
      ...req,
      // An action is not a turn in a conversation: "translate this" must not be
      // bent by whatever was asked two questions ago, so history is sent empty
      // for one even though the panel still shows the turns.
      history: req.action ? [] : Ai.history.slice(0, -2),
      use_library: useLib,
      use_mine: useMine,
      deep_research: deep,
      // The passage the reader put in front of the assistant, if any.  It
      // travels with this question and with no other: the next question is
      // a new question.
      context_text: Ai.context ? Ai.context.text : '',
      context_label: Ai.context ? Ai.context.label : '',
      context_module_id: Ai.context ? Ai.context.module_id : '',
      context_module_name: Ai.context ? Ai.context.module_name : '',
      context_key: Ai.context ? Ai.context.key : '',
      web_token: webToken,
      web_approved: webApproved,
    }, {
      onBackend: (ev) => {
        bot.backend = ev.backend || 'api';
        const local = bot.backend === 'local';
        liveBackend.innerHTML = '<span class="chip ' + (local ? 'pd' : 'no')
          + '">' + (local ? 'Answered by a local server'
                          : 'Answered via ' + esc(ev.provider || 'API'))
          + '</span>';
      },
      onSources: (ev) => {
        Ai.sources = ev.citations || [];
        bot.webStatus = ev.web_research && ev.web_research.message || '';
        if (liveWeb) liveWeb.textContent = bot.webStatus;
        if (ev.provider) Ai.settings.provider = ev.provider;
        if (ev.model) Ai.settings.model = ev.model;
        if (liveSources.parentNode) {
          liveSources.parentNode.replaceChild(Ai.sourceList(Ai.sources),
                                              liveSources);
        }
      },
      onDelta: (t) => {
        bot.content += t;
        if (live) live.innerHTML = Ai.render(bot.content);
      },
      onReplace: (ev) => {
        bot.content = ev.text || '';
        bot.webStatus = ev.web_status || bot.webStatus || '';
        if (live) live.innerHTML = Ai.render(bot.content);
        if (liveWeb) liveWeb.textContent = bot.webStatus;
      },
      onStatus: (ev) => {
        if (liveWeb) liveWeb.textContent = ev.text || '';
      },
      onError: (err, hint) => {
        bot.content = (err || 'The provider refused the request.')
          + (hint ? '\n\n' + hint : '');
        if (live) live.innerHTML = Ai.render(bot.content);
      },
      onAbort: () => { bot.content += '\n\n_(stopped)_'; },
      onFragments: (frags) => {
        // Which words of each source the answer leaned on.  They are
        // attached to the sources themselves, so the final render picks them
        // up with everything else.
        (frags || []).forEach(f => {
          const c = (Ai.sources || []).find(x => x.n === f.n);
          if (c) c.fragment = f;
        });
      },
      onFinally: () => {
        if (!bot.content) bot.content = '(no answer)';
        // A newer question may already have taken over the button.  Only the
        // last stream standing gets to put it back to "Send".
        if (!Ai.ctrl) Ai.setSending(false);
        bot.citations = Ai.sources;
        Ai.renderChat();
        // The passage has served its purpose: it belongs to the question that
        // was asked about it, and the next question is a new one.
        Ai.context = null;
        Ai.renderContext();
        // The exchange is written down as it happens, so a closed app is not
        // a lost conversation.
        Ai.persist();
      },
    });
  },

  /* One SSE request, dispatched to callbacks.
   *
   * Factored out of `run` because the Sermon Builder reads the same endpoint: it
   * renders through `Ai.render` and `Ai.sourceList` too, so model output has one
   * renderer even though it has two homes.  Keeping the "sources arrive before
   * the answer" property in one place is what stops a second caller from quietly
   * forgetting it.
   */
  async streamTo(req, h) {
    h = h || {};
    // Create the controller before the first await, so Stop pressed straight
    // after Send always has something to abort -- even on the first question,
    // while provider settings are still being fetched.
    const ctrl = new AbortController();
    Ai.ctrl = ctrl;
    try {
      await Ai.ensure();
      const r = await fetch('/api/ai/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-GBible-CSRF-Token': CSRF_TOKEN,
        },
        signal: ctrl.signal,
        body: JSON.stringify({
          ...req,
          provider: Ai.settings.provider,
          model: Ai.settings.model,
          use_library: req.use_library !== undefined
            ? req.use_library : Ai.settings.use_library !== false,
          use_mine: req.use_mine !== undefined
            ? req.use_mine : Ai.settings.use_mine !== false,
          scope: req.scope !== undefined
            ? req.scope : (Ai.settings.scope || ''),
          smart_query: req.smart_query !== undefined
            ? req.smart_query : Ai.settings.smart_query !== false,
          deep_research: req.deep_research !== undefined
            ? req.deep_research : !!((Ai.settings && Ai.settings.deep_research)),
          web_token: req.web_token || '',
        }),
      });
      if (!r.ok) {
        if (h.onError) h.onError('The assistant could not be reached '
                                 + '(HTTP ' + r.status + ').', '');
        return;
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        // SSE frames are separated by a blank line; a frame may arrive split
        // across two reads, so only whole frames are consumed.
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, i).trim();
          buf = buf.slice(i + 2);
          if (!frame.startsWith('data:')) continue;
          let ev;
          try { ev = JSON.parse(frame.slice(5).trim()); }
          catch (err) { continue; }
          if (ev.type === 'backend') { if (h.onBackend) h.onBackend(ev); }
          else if (ev.type === 'sources') { if (h.onSources) h.onSources(ev); }
          else if (ev.type === 'delta') { if (h.onDelta) h.onDelta(ev.text || ''); }
          else if (ev.type === 'replace') { if (h.onReplace) h.onReplace(ev); }
          else if (ev.type === 'status') { if (h.onStatus) h.onStatus(ev); }
          else if (ev.type === 'fragments') {
            if (h.onFragments) h.onFragments(ev.fragments || []);
          }
          else if (ev.type === 'error') { if (h.onError) h.onError(ev.error, ev.hint || ''); }
          else if (ev.type === 'done') { if (h.onDone) h.onDone(); }
        }
      }
    } catch (err) {
      if (err && err.name === 'AbortError') { if (h.onAbort) h.onAbort(); }
      else if (h.onError) { h.onError((err && err.message) || String(err), ''); }
    } finally {
      if (Ai.ctrl === ctrl) Ai.ctrl = null;
      if (h.onFinally) h.onFinally();
    }
  },

  /* One question about a topic, answered from that topic guide's own installed
   * material and rendered *in the guide* rather than in the assistant panel.
   *
   * The corpus is the guide itself -- the topical articles, the glosses and
   * the verses it names -- so the answer is about the books the reader
   * actually has, not about the model's memory of the subject.
   *
   * It renders through the same functions as the chat (`Ai.render` for the
   * text, `Ai.sourceList` for the citations), so an answer here looks and
   * behaves exactly like an answer in the assistant panel, and the sources
   * appear before the answer does -- the property that makes the answer
   * checkable rather than merely plausible.
   */
  async guide(host, term, question, history, opts) {
    opts = opts || {};
    const action = opts.action === 'fact' ? 'fact' : 'topic';
    const lens = opts.lens || '';
    const out = el('div', 'ai-topic');
    const srcHost = el('div');
    const body = el('div', 'ai-body');
    out.appendChild(srcHost);
    out.appendChild(body);
    host.appendChild(out);
    let text = '';
    let cites = [];
    await Ai.streamTo({
      action, topic: term, term, lens, question,
      // A follow-up is a follow-up: "what about the second one?" means nothing
      // without the answer it follows.  So this guide's exchange is kept --
      // never the reader's unrelated chat history.
      history: (history || []).slice(-6),
    }, {
      onSources: (ev) => {
        cites = ev.citations || [];
        if (cites.length) srcHost.replaceWith(Ai.sourceList(cites));
      },
      onDelta: (t) => {
        text += t;
        body.innerHTML = Ai.render(text);
      },
      onError: (err, hint) => {
        body.innerHTML = '<div class="warn">' + esc(
          (err || 'The provider refused the request.')
          + (hint ? ' ' + hint : '')) + '</div>';
      },
    });
    return { text: text, cites: cites };
  },

  /* The question an unanswered topic guide asks for itself.
   *
   * It asks for the thing a reader opening a topic guide wants and cannot get
   * from a list of articles: what this subject means, what the Bible says
   * about it, and -- the part that makes the answer worth reading -- where the
   * sources are thin or disagree.  A summary that hid the disagreements would
   * be less useful than the articles it came from.
   */
  topicOverview(topic) {
    return 'Give me an overview of this topic from the sources: what it means, '
      + 'what the cited verses show about it, and where the sources disagree '
      + 'or fall short.';
  },

  /* The questions a topic guide should offer.
   *
   * They are written by the model from the guide's own material, in a call
   * of its own.  The guide deliberately waits for the overview before making
   * that call: two concurrent generations on a local model only slow each
   * other down.  The generic set is shown first, so the row is never empty
   * while the model thinks -- and it is what is left if the model cannot be
   * reached at all.
   */
  /* One cache key per answer: the scope changes which books the guide may
   * read, so the same term under two scopes is two different answers. */
  guideKey(action, lens, term) {
    const scope = (Ai.settings && Ai.settings.scope) || '';
    return action + ':' + (lens || '') + ':' + scope + ':'
      + (term || '').trim();
  },

  async guideQuestions(term, opts) {
    opts = opts || {};
    await Ai.ensure();
    const action = opts.action === 'fact' ? 'fact' : 'topic';
    const lens = opts.lens || '';
    const key = Ai.guideKey(action, lens, term);
    if (Ai.topicQuestionsCache[key]) return Ai.topicQuestionsCache[key];
    let qs = [];
    try {
      const scope = (Ai.settings && Ai.settings.scope) || '';
      const r = action === 'fact'
        ? await api('ai/fact-questions', { term: (term || '').trim(), lens: lens, scope })
        : await api('ai/topic-questions', { topic: (term || '').trim(), scope });
      qs = (r && r.questions) || [];
    } catch (e) {
      qs = [];
    }
    // A guide asked once costs one call, not one per visit.  The questions
    // are kept beside the answer rather than inside it, because they are
    // written in a call of their own and can arrive first.
    if (qs.length) Ai.topicQuestionsCache[key] = qs;
    return qs;
  },

  /* The overview a guide opens with, in the reader's own question.
   *
   * The lens is the question the reader is asking of the term, and the
   * overview answers *that* question -- so the same term gives a different
   * overview through the theological lens and the counseling one.
   */
  factOverview(term, lens) {
    const maps = {
      theological: 'Give me an overview of this term through the theological '
        + 'lens: what it means for doctrine, what the passages show about it, '
        + 'and where the sources disagree or fall short.',
      counseling: 'Give me an overview of this term through the counseling '
        + 'lens: what it means for people, what the passages show about it, '
        + 'and where the sources disagree or fall short.',
    };
    return maps[lens] || ('Give me an overview of this term from the sources: '
      + 'what it is, what the passages show about it, and where the sources '
      + 'disagree or fall short.');
  },

  fallbackTopicQuestions(topic) {
    const t = (topic || '').trim();
    return ['What does the Bible say about ' + (t || 'this topic') + '?',
            'What are the key terms?',
            'Where do the sources disagree?',
            'What do the glosses add?'];
  },


  /* Carry a topic guide's exchange into the chat panel.
   *
   * This is what makes the topic section and the chat one thing rather than
   * two.  The reader reads an answer in the guide, decides it is worth
   * pursuing, and continues the same conversation in the panel -- with the
   * exchange already in it, so the question they were pursuing is still the
   * question they are asking.
   */
  /* Apply a scope carried over from a guide so the follow-up searches the
   * same books the guide read, even if the pane's picker has since changed. */
  async setScope(scope) {
    scope = scope || '';
    Ai.settings.scope = scope;
    const e = Ai.els();
    if (e.scope) {
      if (scope && !Array.from(e.scope.options).some(o => o.value === scope)) {
        const option = document.createElement('option');
        option.value = scope;
        option.textContent = scope;
        e.scope.appendChild(option);
      }
      e.scope.value = scope;
    }
    try { await post('ai/settings', { scope }); } catch (err) { /* cosmetic */ }
  },

  adoptTopic(hist, cites, topic, scope) {
    if (scope !== undefined) Ai.setScope(scope);
    Ai.history = (hist || []).map(h => ({
      role: h.role,
      // The overview is asked with an instruction the model was given, not
      // one the reader typed.  In the chat panel that instruction would be
      // read as something the reader had just said, so it is shown as what
      // it is: an overview of the topic.
      content: (h.role === 'user' && h.internal)
        ? 'Overview of ' + (topic || 'this topic') : h.content,
    }));
    if (cites && cites.length && Ai.history.length) {
      const last = Ai.history[Ai.history.length - 1];
      if (last.role === 'assistant') last.citations = cites;
    }
    Ai.sources = cites || [];
    Ai.renderChat();
  },

  /* Remember a topic's answer, and forget the oldest ones.
   *
   * The cache is what makes moving back to a topic free, so it is worth
   * keeping -- but a session that visits two hundred topics should not hold two
   * hundred answers in memory for as long as the app is open.  Twenty is more
   * than a reader will revisit and small enough to be free.
   */
  cacheTopic(topic, text, cites) {
    Ai.topicCache[topic] = { text: text, cites: cites };
    if (Ai.topicCacheOrder.indexOf(topic) < 0) {
      Ai.topicCacheOrder.push(topic);
    }
    while (Ai.topicCacheOrder.length > 20) {
      const old = Ai.topicCacheOrder.shift();
      delete Ai.topicCache[old];
    }
    // The questions come from a separate model call; keep the same bound so a
    // long session does not retain one list per visited guide.
    if (Ai.topicQuestionsOrder.indexOf(topic) < 0) {
      Ai.topicQuestionsOrder.push(topic);
    }
    while (Ai.topicQuestionsOrder.length > 20) {
      delete Ai.topicQuestionsCache[Ai.topicQuestionsOrder.shift()];
    }
  },
};

/* ====================================================== AI provider settings
 *
 * Keys are written here and never read back -- `key_set` is a boolean, and the
 * field only ever sends a new value.  Same rule as API Settings, and for the
 * same reason: a credential rendered into the page is a credential in any
 * screenshot the reader takes.
 */
/* Every AI settings switch posts to the same endpoint. Failures must be
 * surfaced: reloading on an ok:false answer looks like a successful change. */
async function aiSet(patch, label) {
  const r = await post('ai/settings', patch);
  if (!r || r.ok === false) {
    toast((r && r.error) || 'Could not change ' + (label || 'that setting') + '.', 'err');
    return false;
  }
  return true;
}

const AiSettings = {
  data: null,
  _seq: 0,

  /* The setup card shown in place of all AI settings until the reader opts in.
   * There is no download: enabling AI only means choosing a provider below. */
  async renderSetup() {
    const host = $('#ai-setup');
    if (!host) return;
    host.innerHTML = '<div class="api ai-setup-card"><div class="body">'
      + '<h3>AI Assistant is not set up</h3>'
      + '<p class="muted">G-Bible works entirely without AI. If you would like '
      + 'an assistant that reads your installed books and cites its sources, '
      + 'enable it and choose a provider. G-Bible downloads no model: a local '
      + 'server (Ollama, LM Studio, llama.cpp) or a cloud key supplies the '
      + 'answers. Nothing is sent until you decide.</p>'
      + '<div class="ai-setup-choices">'
      + '<button class="btn primary" id="ai-setup-api">Enable AI Assistant — '
      + 'choose a provider</button>'
      + '</div>'
      + '<div class="ai-setup-progress tiny muted" id="ai-setup-progress">'
      + '</div>'
      + '<p class="tiny muted" style="margin-top:12px">A cloud provider receives '
      + 'your question and the passages relevant to it — never the whole '
      + 'library. A local server keeps everything on this machine. You can '
      + 'disable the assistant again at any time.</p>'
      + '</div></div>';
    const btn = $('#ai-setup-api');
    if (btn) btn.onclick = async () => {
      const progress = $('#ai-setup-progress');
      if (btn) btn.disabled = true;
      try {
        const r = await post('ai/setup/start', {});
        if (!r.ok) throw new Error(r.error || 'Could not enable AI.');
        if (progress) progress.textContent = r.message || 'Enabled.';
        location.reload();
      } catch (e) {
        if (btn) btn.disabled = false;
        if (progress) progress.textContent = 'Could not enable AI: ' + e.message;
      }
    };
  },

  /* The enabled settings page: turn the assistant off again. */
  renderSetupActions() {
    const main = $('#ai-provider-main');
    if (!main) return;
    const card = el('div', 'api');
    const body = el('div', 'body');
    body.appendChild(el('div', 'n', 'Assistant installation'));
    const offBtn = el('button', 'btn danger', 'Disable AI Assistant');
    offBtn.onclick = async () => {
      if (!confirm('Disable the AI Assistant? Its controls will disappear '
                   + 'from the app. Conversations and provider keys are kept; '
                   + 'you can enable it again here later.')) return;
      const r = await post('ai/setup/disable', {});
      if (!r || r.ok === false) { toast((r && r.error) || 'Could not disable AI.', 'err'); return; }
      location.reload();
    };
    body.appendChild(offBtn);
    card.appendChild(body);
    main.insertBefore(card, main.firstChild);
  },

  async load() {
    const seq = ++this._seq;
    // A fresh app shows one card and nothing else.  The reader decides here
    // whether AI exists in their app at all; the rest of the settings page is
    // not rendered until that decision has been made.
    const setup = $('#ai-setup');
    const body = $('#ai-settings-body');
    const sum = $('#ai-settings-summary');
    if (aiOff()) {
      if (body) body.style.display = 'none';
      if (sum) sum.textContent = '';
      await this.renderSetup();
      return;
    }
    if (body) body.style.display = '';
    if (setup) setup.innerHTML = '';
    const r = await api('ai/providers');
    if (seq !== this._seq) return;
    if (!r || r.ok === false) {
      if (sum) sum.textContent = '';
      const host = $('#ai-provider-main');
      if (host) host.innerHTML = '<div class="warn">' + esc((r && r.error) || 'Could not load AI settings.') + '</div>';
      return;
    }
    this.data = r;
    const s = r.settings || {};
    // How much of the reader's own material there is to cite.  The Grounding
    // card below says so, and a switch that says "include my own material"
    // and then quietly includes nothing is a lie told by omission.
    Ai.ownCount = r.mine || {};
    if (sum) {
      sum.innerHTML = (r.summary ? r.summary.total : 0)
        + ' providers · ' + (r.summary ? r.summary.local : 0)
        + ' runs on this machine · ' + (r.summary ? r.summary.free : 0)
        + ' free tier' + ((r.summary && r.summary.free === 1) ? '' : 's')
        + ' · current: <b>' + esc(s.provider || '—')
        + '</b> / ' + esc(s.model || 'default') + '.';
    }
    this.renderSide(r.providers || [], s);
    this.renderMain(r.providers || [], s);
    this.renderSetupActions();
    this.renderUsage();
  },

  /* What the calls have been.
   *
   * This exists because the alternative -- finding out from a provider's billing
   * page -- requires the reader to work out which of the calls on it were theirs.
   * A local provider shows here too, at zero cost, because "free and stays free"
   * is the claim that makes the local option worth choosing and it should be
   * visible rather than asserted.
   */
  async renderUsage() {
    const seq = ++this._seq;
    const main = $('#ai-provider-main');
    if (!main) return;
    const old = $('#ai-usage-card');
    if (old) old.remove();
    let r;
    try { r = await api('ai/usage', { days: 30 }); }
    catch (e) { return; }
    if (seq !== this._seq) return;

    const card = el('div', 'api');
    card.id = 'ai-usage-card';
    const body = el('div', 'body');
    body.appendChild(el('div', 'n', 'Usage — last 30 days'));
    const tok = (n) => (n || 0).toLocaleString();
    if (!r.calls) {
      body.appendChild(el('div', 'no',
        'No AI calls recorded yet. Token counts are read from what the provider '
        + 'reports, so they appear here as answers stream in.'));
    } else {
      const parts = [r.calls + ' call' + (r.calls === 1 ? '' : 's')];
      if (r.failed) parts.push(r.failed + ' incomplete');
      parts.push(tok(r.total_tokens) + ' tokens');
      if (r.cost_known || r.cost) {
        parts.push((r.cost_known ? '$' : '≥ $') + (r.cost || 0).toFixed(2));
      }
      body.appendChild(el('div', 'v', parts.join(' · ')));
      const lines = (r.providers || []).map(p =>
        esc(p.name) + (p.local ? ' (local)' : '')
        + ': ' + p.calls + ' call' + (p.calls === 1 ? '' : 's')
        + ', ' + tok(p.total_tokens) + ' tokens'
        + ((p.cost_known || p.cost)
            ? ', ' + (p.cost_known ? '$' : '≥ $') + (p.cost || 0).toFixed(2)
            : ''));
      const det = el('div', 'no');
      det.innerHTML = lines.join('<br>') || '—';
      body.appendChild(det);
      if (r.note) body.appendChild(el('div', 'no muted', esc(r.note)));
      body.appendChild(el('div', 'no muted',
        'Costs are ' + esc(r.prices || 'approximate') + '.'));
    }
    const right = el('div', 'right');
    const fresh = el('button', 'btn', 'Refresh');
    fresh.onclick = () => this.renderUsage();
    right.appendChild(fresh);
    if (r.calls) {
      const clear = el('button', 'btn danger', 'Forget');
      clear.title = 'Erase the record. It stays on this machine and is not sent '
        + 'anywhere, but the numbers are yours to clear.';
      clear.onclick = async () => {
        if (!confirm('Forget all recorded usage?')) return;
        await post('ai/usage', { reset: true });
        toast('Usage cleared');
        this.renderUsage();
      };
      right.appendChild(clear);
    }
    card.appendChild(body);
    card.appendChild(right);
    main.appendChild(card);
  },

  renderSide(providers, s) {
    const side = $('#ai-provider-side');
    if (!side) return;
    side.innerHTML = '';
    providers.forEach(p => {
      const b = el('button', 'store-item' + (p.id === s.provider ? ' on' : ''));
      const pr = Ai.probeResult[p.id];
      const dot = pr ? (pr.ok ? '<span class="ai-ok">●</span> '
                               : '<span class="ai-bad">●</span> ') : '';
      b.innerHTML = dot + esc(p.name)
        + (p.free ? ' <span class="chip fr">free</span>' : '')
        + '<div class="tiny muted">' + (p.local ? 'Local' : 'Cloud')
        + (p.key_required ? (p.key_set ? ' · key set' : ' · needs key') : '')
        + '</div>';
      b.onclick = () => { this.select(p.id); };
      side.appendChild(b);
    });
  },

  renderMain(providers, s) {
    const main = $('#ai-provider-main');
    if (!main) return;
    const p = providers.find(x => x.id === s.provider) || providers[0];
    main.innerHTML = '';
    if (!p) { main.innerHTML = '<div class="empty">No providers.</div>'; return; }
    main.appendChild(el('div', 'api',
      'Answers come from the provider selected below. A local server keeps '
      + 'requests on this machine; a cloud provider receives your question '
      + 'and the passages relevant to it.'));

    const card = el('div', 'api');

    const body = el('div', 'body');
    body.appendChild(el('div', 'n', esc(p.name)));
    body.appendChild(el('div', 'v', p.local ? 'Runs on this machine' : 'Cloud service'));
    if (p.notes) body.appendChild(el('div', 'no', esc(p.notes)));
    const meta = el('div', 'meta');
    meta.innerHTML = '<span class="chip ' + (p.local ? 'pd' : 'no') + '">'
      + (p.local ? 'Private' : 'Sends data to ' + esc(p.name)) + '</span>'
      + (p.free ? ' <span class="chip fr">Free tier</span>' : '')
      + ' · '
      + esc(p.base_url || '');
    body.appendChild(meta);
    // A free tier has conditions, and they differ from one provider to the
    // next.  They are stated here rather than left for the reader to go and
    // find, because "free" without its limits is a promise the app cannot keep.
    if (p.free_note) {
      const fn = el('div', 'no muted');
      fn.style.marginTop = '4px';
      fn.textContent = p.free_note;
      body.appendChild(fn);
    }

    // Model choice for the selected provider.  Sourced from what the server
    // reported if we have asked, otherwise the preset list.
    const mrow = el('div', 'row', '');
    mrow.style.marginTop = '8px';
    const mlab = el('label', 'tiny muted', 'Model ');
    const msel = el('select', '');
    const models = Ai.modelList(p);
    if (!models.length) {
      const o = document.createElement('option');
      o.value = ''; o.textContent = 'no models — press Test';
      msel.appendChild(o);
    }
    models.forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      if (m === s.model) o.selected = true;
      msel.appendChild(o);
    });
    msel.disabled = !models.length;
    msel.onchange = async () => {
      await post('ai/settings', { model: msel.value });
      Ai.settings.model = msel.value;
      toast('Model set to ' + msel.value);
      this.load();
    };
    mlab.appendChild(msel);
    mrow.appendChild(mlab);
    body.appendChild(mrow);

    // What the last probe found, stated plainly.
    const pr = Ai.probeResult[p.id];
    if (pr) {
      const st = el('div', 'tiny');
      st.style.marginTop = '5px';
      if (pr.ok) {
        st.innerHTML = '<span class="ai-ok">●</span> Reachable — '
          + pr.models.length + ' model' + (pr.models.length === 1 ? '' : 's')
          + ' offered.'
          // A provider that filters its list says so, and says how many it
          // left out: a list that quietly dropped 450 models would look like
          // the provider only has 18.
          + (pr.hidden ? ' <span class="muted">(' + pr.hidden + ' others hidden '
                        + '— this provider is filtered to the free ones)</span>'
                       : '');
      } else {
        st.innerHTML = '<span class="ai-bad">●</span> '
          + esc(pr.error || 'Not reachable.')
          + (pr.hint ? ' <span class="muted">' + esc(pr.hint) + '</span>' : '');
      }
      body.appendChild(st);
    }

    card.appendChild(body);

    const right = el('div', 'right');
    const choose = el('button', 'btn' + (p.id === s.provider ? ' primary' : ''),
      p.id === s.provider ? 'Selected' : 'Use this');
    choose.onclick = () => { this.select(p.id); };
    right.appendChild(choose);

    const test = el('button', 'btn', 'Test');
    test.title = 'Ask this provider which models it has. Reaching it at all is '
      + 'the test; the list is the proof.';
    test.onclick = () => { this.probe(p.id, true); };
    right.appendChild(test);

    if (p.key_required) {
      const inp = el('input', 'key');
      inp.type = 'password';
      inp.placeholder = p.key_set ? (p.key_name || 'API key') + ' (replace)'
                                  : ((p.key_name || 'API key') + ' (paste key)');
      const save = el('button', 'btn', p.key_set ? 'Replace key' : 'Save key');
      save.onclick = async () => {
        if (!inp.value) { toast('Paste a key first'); return; }
        const res = await post('ai/key', { provider: p.id, key: inp.value });
        if (res.ok) { inp.value = ''; toast('Key saved for ' + p.name); this.load(); }
        else toast(res.error || 'Could not save the key', 'err');
      };
      right.append(inp, save);
      if (p.key_set) {
        const clear = el('button', 'btn danger', 'Clear');
        clear.onclick = async () => {
          await post('ai/key', { provider: p.id, key: '' });
          toast('Key cleared for ' + p.name);
          this.load();
        };
        right.appendChild(clear);
      }
    }
    card.appendChild(right);

    main.appendChild(card);

    // Global options.
    const opts = el('div', 'api');
    const ob = el('div', 'body');
    ob.appendChild(el('div', 'n', 'Grounding'));
    ob.appendChild(el('div', 'no',
      'The assistant retrieves passages from your installed library and cites '
      + 'them. Turn this off to ask the model with no library context.'));
    const orow = el('div', 'row');
    const lib = el('label', 'tiny muted');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = s.use_library !== false;
    cb.onchange = async () => {
      await post('ai/settings', { use_library: cb.checked });
      Ai.settings.use_library = cb.checked;
      toast('Library grounding ' + (cb.checked ? 'on' : 'off'));
    };
    lib.appendChild(cb);
    lib.appendChild(document.createTextNode(' Use my library'));
    orow.appendChild(lib);
    const sl = el('label', 'tiny muted', ' max sources ');
    const sn = document.createElement('input');
    sn.type = 'number'; sn.min = '1'; sn.max = '30';
    sn.value = s.max_sources || 20; sn.style.width = '60px';
    sn.onchange = async () => {
      const ok = await aiSet({ max_sources: sn.value }, 'max sources');
      if (!ok) return;
      if (Ai.settings) Ai.settings.max_sources = Number(sn.value);
      toast('Max sources set to ' + sn.value);
    };
    sl.appendChild(sn);
    orow.appendChild(sl);
    ob.appendChild(orow);

    // The reader's own material, which is a switch of its own because it
    // answers a different question: the library says what the commentators
    // wrote, this says what *the reader* wrote.
    const mineRow = el('div', 'row');
    const mine = el('label', 'tiny muted');
    const mcb = document.createElement('input');
    mcb.type = 'checkbox';
    mcb.checked = s.use_mine !== false;
    mcb.onchange = async () => {
      await post('ai/settings', { use_mine: mcb.checked });
      Ai.settings.use_mine = mcb.checked;
      toast('Your own material ' + (mcb.checked ? 'on' : 'off'));
    };
    mine.appendChild(mcb);
    mine.appendChild(document.createTextNode(' Use my own notes and highlights'));
    mineRow.appendChild(mine);
    ob.appendChild(mineRow);
    const mineCount = (Ai.ownCount && Ai.ownCount.total) || 0;
    ob.appendChild(el('div', 'no muted',
      mineCount
        ? mineCount + ' piece' + (mineCount === 1 ? '' : 's')
          + ' of your own material can be cited. They are marked as yours in '
          + 'the answer, so a note is never passed off as a commentary.'
        : 'You have no notes, highlights or clips yet, so there is '
          + 'nothing of your own for the assistant to cite.'));

    // The query the assistant searches with.  The model is asked which words
    // a source on the subject would use, because the reader's own words are
    // often the wrong ones -- a question about being anxious is answered by a
    // text about worry.  It costs one extra call per question.
    const sqRow = el('div', 'row');
    const sq = el('label', 'tiny muted');
    const sqcb = document.createElement('input');
    sqcb.type = 'checkbox';
    sqcb.checked = s.smart_query !== false;
    sqcb.onchange = async () => {
      await post('ai/settings', { smart_query: sqcb.checked });
      Ai.settings.smart_query = sqcb.checked;
      toast('Model-written search ' + (sqcb.checked ? 'on' : 'off'));
    };
    sq.appendChild(sqcb);
    sq.appendChild(document.createTextNode(
      ' Let the model choose the search words'));
    sqRow.appendChild(sq);
    ob.appendChild(sqRow);
    ob.appendChild(el('div', 'no muted',
      'The assistant asks the model which words a source on your subject '
      + 'would use, and searches for those -- because the words you would '
      + 'use and the words a commentary would use are often not the same. '
      + 'One extra call per question.'));

    // Retrieval-quality controls.  Each writes one setting and says plainly
    // what it costs, because the useful ones are not free.
    const qualityRow = (key, label, note) => {
      const row = el('div', 'row');
      const lab = el('label', 'tiny muted');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = s[key] !== false;
      box.onchange = async () => {
        await post('ai/settings', { [key]: box.checked });
        Ai.settings[key] = box.checked;
        if (key === 'deep_research') {
          const bar = $('#ai-deep-research');
          if (bar) bar.checked = box.checked;
        }
        toast(label + ' ' + (box.checked ? 'on' : 'off'));
      };
      lab.appendChild(box);
      lab.appendChild(document.createTextNode(' ' + label));
      row.appendChild(lab);
      ob.appendChild(row);
      if (note) ob.appendChild(el('div', 'no muted', note));
    };
    qualityRow('resolve_refs', 'Resolve people and events to passages',
      'Finds likely chapters from names in your question, then reads those '
      + 'chapters in full — so a person in one verse and the reason a few '
      + 'verses later both reach the model.');
    qualityRow('multi_hop', 'Search again when the first sources are thin',
      'One extra library pass with a sharper query, before the answer is '
      + 'drafted. No extra model call.');
    qualityRow('deep_research', 'Deep research',
      'Reads the maximum number of sources, always takes the second retrieval '
      + 'pass and resolves names to passages. Slower, no extra provider calls.');
    const revRow = el('div', 'row');
    const revLab = el('label', 'tiny muted', ' Review answers with ');
    const revSel = el('select', '');
    [['auto', 'a different provider when available'],
     ['same', 'the answering model'], ['api', 'the configured API']]
      .forEach(([id, text]) => {
        const o = document.createElement('option');
        o.value = id; o.textContent = text;
        if ((s.review_backend || 'auto') === id) o.selected = true;
        revSel.appendChild(o);
      });
    revSel.onchange = async () => {
      await post('ai/settings', { review_backend: revSel.value });
      Ai.settings.review_backend = revSel.value;
      toast('Answer reviewer updated');
    };
    revLab.appendChild(revSel);
    revRow.appendChild(revLab);
    ob.appendChild(revRow);
    ob.appendChild(el('div', 'no muted',
      'A model that writes an answer is a poor judge of its own mistakes. '
      + 'When a second provider is configured it audits the draft and the '
      + 'answer is revised once if the audit fails. A local provider keeps the audit on this machine.'));
    opts.appendChild(ob);
    main.appendChild(opts);
  },

  async select(providerId) {
    const r = await post('ai/settings', { provider: providerId });
    if (!r.ok) return;
    Ai.settings = r.settings || Ai.settings;
    toast('Provider set to ' + providerId);
    this.load();
    // Ask the newly selected provider what it has, quietly: this is setup, not
    // a test the reader pressed, so it should not announce a failure that the
    // status line is already showing.
    this.probe(providerId, false).catch(() => {});
  },

  /* Ask a provider which models it has -- and, by asking, whether it can be
   * reached at all.  `loud` is the whole difference between the Test button
   * (say what happened) and setup discovery (say nothing the status line is
   * not already saying). */
  async probe(providerId, loud) {
    if (loud) toast('Testing ' + this.providerName(providerId) + '…');
    const r = await api('ai/models', { provider: providerId });
    Ai.probeResult[providerId] = r;
    if (r.ok) await Ai.adoptModels(providerId, r.models);
    if (loud) {
      if (r.ok) {
        toast(this.providerName(providerId) + ' is reachable — '
              + r.models.length + ' model'
              + (r.models.length === 1 ? '' : 's') + ' offered.'
              + (r.hidden ? ' (' + r.hidden + ' others hidden — free ones only)'
                          : ''));
      } else {
        toast((r.error || 'Not reachable')
              + (r.hint ? ' ' + r.hint : ''), 'err');
      }
    }
    this.load();
  },

  providerName(id) {
    const list = (this.data && this.data.providers) || [];
    const p = list.find(x => x.id === id);
    return p ? p.name : id;
  },
};
