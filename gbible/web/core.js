/* G-Bible -- front end.
 *
 * The pane model mirrors the server's: a pane holds a *cursor*, never a pixel
 * offset, and a link set letter.  Navigating in one pane asks the server what
 * every linked pane should show, then moves each of them.  That is the whole
 * synchronisation rule, and it is why a commentary can be verse-locked to a
 * Bible while a lexicon pane looks words up instead of scrolling.
 */
'use strict';

// Global error handlers: never let an uncaught error kill the UI silently.
window.addEventListener('error', (e) => {
  try { console.error('uncaught', e.error || e.message); } catch (_) {}
});
window.addEventListener('unhandledrejection', (e) => {
  try { console.error('unhandled rejection', e.reason); } catch (_) {}
  e.preventDefault();
});

const S = {
  view: 'today',
  layout: null,
  modules: [],
  types: [],
  subjects: [],
  langs: [],
  links: {},
  linkGroups: {},
  tax: {},
  store: { repo: '', lang: '', category: '', subject: '', q: '', installed: false,
           sort: 'title', items: [], facets: {}, total: 0 },
  api: { items: [], summary: {}, category: '' },
  search: { q: '', opts: { match_case: false, match_all_forms: false,
                          context: 0, sort: 'relevance', scope: '' } },
  lib: { type: '', lang: '', source: '', q: '', detail: false },
  popups: {},
};
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

/* The most recent non-empty text selection, recorded as it happens.
 *
 * Reading getSelection() at the moment the menu item runs is too late: by then
 * the click that opened the menu has often collapsed the selection, and the
 * highlight stored an empty quote and did nothing at all. */
S.lastSelection = '';
document.addEventListener('selectionchange', () => {
  const t = String(window.getSelection() || '').trim();
  if (t) S.lastSelection = t;
});

/* ------------------------------------------------------------------ util */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s === null || s === undefined ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

/* Copying to the clipboard is a promise that can reject, and the rejection is
 * invisible unless somebody says so.  These features copy several things —
 * a quote, a whole clipping, a plan's progress — so the failure path is
 * shared rather than re-invented per button. */
/* "1Cor.3.22" -> "1Cor 3:22".  Cross-reference tables store OSIS ids, and
 * turning the dots into spaces produces "1Cor 3 22" -- which is not a
 * reference at all, and the reference parser either rejects it or guesses.  A
 * two-part key like "Ps.119" is a chapter, and stays one. */
function osisToRef(k) {
  const parts = String(k || '').split('.');
  if (parts.length >= 3) return parts[0] + ' ' + parts[1] + ':' + parts.slice(2).join('.');
  return parts.join(' ');
}

const Clipboard = {
  async write(text) {
    if (!text) { toast('Nothing to copy.', 'warn'); return false; }
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied.');
      return true;
    } catch (err) {
      /* The async clipboard is unavailable outside a secure context, and this
       * app is deliberately served over plain http on the loopback address,
       * so a refusal here is a real possibility rather than an edge case.
       * The old execCommand path still works and is the honest fallback. */
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px;top:0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        toast(ok ? 'Copied.' : 'Could not reach the clipboard.', ok ? '' : 'warn');
        return ok;
      } catch (e2) {
        toast('Could not reach the clipboard.', 'warn');
        return false;
      }
    }
  },
};

/* Add a value to a <select> if it is not already one of the options.  Used
 * where a free-text field and a dropdown describe the same thing and one of
 * them can hold a value the other does not: two controls that disagree is
 * worse than either one alone. */
function sel_add(select, value) {
  if (!select || !value) return;
  if ([...select.options].some(o => o.value === value)) return;
  const o = el('option', '', esc(value));
  o.value = value;
  select.appendChild(o);
}

async function api(path, params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '' || v === false) continue;
    // An object parameter has to be JSON, not String(v).  Appending it directly
    // sent the literal "[object Object]", which the server could not parse, so
    // every read fell back to its default cursor: chapter buttons appeared to
    // work and then snapped back to Genesis 1:1.
    if (v === true) qs.append(k, '1');
    else if (typeof v === 'object') qs.append(k, JSON.stringify(v));
    else qs.append(k, v);
  }
  try {
    const r = await fetch('/api/' + path + (qs.toString() ? '?' + qs : ''),
      { headers: { 'X-GBible-CSRF-Token': CSRF_TOKEN } });
    if (!r.ok) return { ok: false, error: 'HTTP ' + r.status };
    return await r.json();
  } catch (e) {
    return { ok: false, error: (e && e.message) || String(e) };
  }
}
async function post(path, body) {
  try {
    const r = await fetch('/api/' + path, {
      method: 'POST', headers: {
        'Content-Type': 'application/json',
        'X-GBible-CSRF-Token': CSRF_TOKEN,
      },
      body: JSON.stringify(body || {}) });
    if (!r.ok) return { ok: false, error: 'HTTP ' + r.status };
    return await r.json();
  } catch (e) {
    return { ok: false, error: (e && e.message) || String(e) };
  }
}
const debounce = (fn, ms) => {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};
const fmtBytes = (n) => {
  n = Number(n || 0); if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + ' ' + u[i];
};
const modById = (id) => S.modules.find(m => m.id === id);

/* Dismissal is not one path: the footer button, the Escape key and a click on
 * the backdrop all close a dialog, but only the first one runs a button's `fn`.
 * Anything a dialog leaves lying around -- a highlight in the text behind it --
 * therefore survived Escape.  This hook is run on every path. */
let _modalCleanup = null;

function modal(title, bodyHtml, buttons) {
  _modalCleanup = null;
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHtml;
  const f = $('#modal-foot'); f.innerHTML = '';
  (buttons || [{ label: 'Close', cls: 'btn' }]).forEach(b => {
    const cls = b.cls ? (b.cls.includes('btn') ? b.cls : 'btn ' + b.cls) : 'btn';
    const x = el('button', cls, b.label);
    x.onclick = () => { if (b.fn) b.fn(); if (b.close !== false) closeModal(); };
    f.appendChild(x);
  });
  $('#modal-bg').classList.add('on');
  // Move focus into the dialog for keyboard/screen-reader users.
  setTimeout(() => {
    const first = $('#modal-body input, #modal-body button, #modal-body select, #modal-body textarea, #modal-foot button');
    if (first) first.focus();
  }, 30);
}
const closeModal = () => {
  // Stop any video playing inside the dialog so audio does not keep going
  // after the popup is dismissed.
  $$('#modal-body video').forEach((v) => {
    try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) { /* ignore */ }
  });
  $('#modal-bg').classList.remove('on');
  if (_modalCleanup) { const f = _modalCleanup; _modalCleanup = null; try { f(); } catch (e) {} }
};
$('#modal-bg').onclick = (e) => { if (e.target.id === 'modal-bg') closeModal(); };

const Shortcuts = {
  show() {
    const body = '<div class="st-body">'
      + '<table class="kv"><tbody>'
      + '<tr><td><kbd>Ctrl/⌘ K</kbd></td><td>Open command box</td></tr>'
      + '<tr><td><kbd>Ctrl/⌘ F</kbd></td><td>Open search</td></tr>'
      + '<tr><td><kbd>Esc</kbd></td><td>Close modal / cancel</td></tr>'
      + '<tr><td><kbd>?</kbd></td><td>Show this list</td></tr>'
      + '<tr><td><kbd>Enter</kbd></td><td>Submit forms / search</td></tr>'
      + '</tbody></table>'
      + '<div class="tiny muted" style="margin-top:8px">Tip: many inputs support Enter to submit.</div>'
      + '</div>';
    modal('Keyboard shortcuts', body, [{ label: 'Close', cls: 'btn primary' }]);
  },
};
const About = {
  show() {
    modal('About G-Bible',
      '<div class="st-body" style="margin-bottom:10px">'
      + 'G-Bible is a local-first Bible study application. It runs entirely on '
      + 'your machine: nothing is uploaded, nothing is tracked, and no account '
      + 'is required. You install the modules you want from the Store (public '
      + 'domain and freely licensed texts), read them side by side, follow '
      + 'cross-references, look up words in the original languages, keep notes '
      + 'and clips, build reading plans, and chat with an AI assistant over '
      + 'your own library — all offline by default.'
      + '</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">'
      + 'Built with standard web technology and a local SQLite index. '
      + 'The app itself is <b>free and open source</b>, released under the '
      + '<b>MIT License</b> — you are welcome to use it, study it, modify it, '
      + 'and fork it however you like.'
      + '</div>'
      + '<div class="tiny muted">© 2026 G-Bible contributors</div>',
      [ ...(window.gbible && typeof window.gbible.checkForUpdates === 'function' ? [{ label: 'Check for Updates', cls: 'btn', fn: async () => {
          try { await window.gbible.checkForUpdates(); }
          catch (e) { toast((e && e.message) || 'Could not check for updates.', 'err'); }
        } }] : []),
        { label: 'Reset G-Bible', cls: 'btn danger', fn: async () => {
          if (!confirm('Reset G-Bible to a fresh, empty library?\n\n'
            + 'This deletes the database and every installed module, note, '
            + 'clip, and setting. The app will exit; restart it afterwards.')) return;
          const r = await post('app/reset', { confirm: 'RESET' });
          if (r && r.ok) {
            toast('Resetting. Please restart G-Bible.', 'warn');
          } else {
            toast((r && r.error) || 'Reset failed', 'err');
          }
        } },
        { label: 'Close', cls: 'btn', fn: closeModal }]);
  },
};

/* Surface unexpected errors instead of failing silently. */
window.addEventListener('unhandledrejection', (e) => {
  try { console.error('Unhandled rejection:', e.reason); } catch (err) {}
  try { toast('Something went wrong. Please retry, or restart G-Bible if it persists.', 'err'); } catch (err) {}
});
/* Any reference-shaped link anywhere follows the reference, even in containers
 * that never called wire() -- so a Bible reference is never a dead link. */
document.addEventListener('click', (e) => {
  const r = e.target && e.target.closest ? e.target.closest('a[data-ref]') : null;
  if (r) {
    e.preventDefault();
    try { closeModal(); } catch (err) { /* not in a modal */ }
    if (typeof Reader !== 'undefined' && Reader.openRefAnywhere) {
      Reader.openRefAnywhere((r.dataset.ref || '').replace(/\./g, ' '));
    }
    return;
  }
  /* Power Lookup: click a Strong's number or lemma in verse text to open
   * a Word Study pane for that word.  Works anywhere a tagged word appears. */
  const snum = e.target && e.target.closest ? e.target.closest('a.snum') : null;
  const morph = e.target && e.target.closest ? e.target.closest('.morphs') : null;
  if (snum || morph) {
    e.preventDefault();
    try { closeModal(); } catch (err) { /* not in a modal */ }
    const num = snum ? snum.dataset.s || snum.textContent : (morph.textContent || '').trim();
    if (num && typeof Reader !== 'undefined' && Reader.openWordStudyPane) {
      Reader.openWordStudyPane(num);
    }
  }
});

/* "John.3.16" and "John 3:16" both mean "John 3" here.  A concordance is a
 * chapter index, so the verse has to come off before the reference means
 * anything -- and the book may carry a number of its own ("1Cor.13.4"). */
function chapterOf(ref) {
  const s = String(ref || '').trim();
  // The spaced form has to be tried first: on "John 3:16" the dotted pattern
  // matches non-greedily as book "John 3" + colon + 16, giving "John 3 16".
  let m = s.match(/^(\S+)\s+(\d+)/);         // John 3:16 / John 3 / Ps 119
  if (m) return m[1] + ' ' + m[2];
  m = s.match(/^(.+?)[.:]\s*(\d+)/);          // John.3.16 / 1Cor.13.4
  if (m) return m[1].trim() + ' ' + m[2];
  return s;
}

function toast(msg, kind) {
  const t = el('div', 'warn', esc(msg));
  t.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);'
    + 'z-index:200;box-shadow:0 8px 30px #000b;max-width:70vw;'
    + (kind === 'err' ? 'background:#4a1e22;border-color:#6a2b30;color:#f0a0a5' : '');
  document.body.appendChild(t);
  setTimeout(() => t.remove(), kind === 'err' ? 7000 : 3400);
}

/* ================================================================ Memorise */
/* Three drills over a passage's text.  Nothing is stored: the drill is a view
 * over text already on screen, so it works for any module without a backend.
 *   hide  - Hide-a-word: ~1 in 3 words blanked; type the missing ones.
 *   first - First letter: every word reduced to its first letter + underscores.
 *   full  - Whole-chapter: read it, then flip to first-letter to test. */
const Memorise = {
  text: '', title: '', mode: 'hide', answers: [],

  open(text, title) {
    this.text = String(text || '').trim();
    this.title = title || '';
    this.mode = 'hide';
    this.render();
  },

  words() { return this.text.split(/(\s+)/); },   // keeps whitespace tokens

  render() {
    const toks = this.text.split(/(\s+)/);
    const words = toks.filter(t => t.trim().length > 0);
    let body = '<div class="mem-wrap">';
    body += '<div class="mem-title">' + esc(this.title) + '</div>';
    body += '<div class="mem-modes">';
    body += '<button class="btn ' + (this.mode==='hide'?'on':'') + '" data-m="hide">Hide-a-word</button>';
    body += '<button class="btn ' + (this.mode==='first'?'on':'') + '" data-m="first">First letter</button>';
    body += '<button class="btn ' + (this.mode==='full'?'on':'') + '" data-m="full">Whole chapter</button>';
    body += '</div>';
    if (this.mode === 'hide') {
      // blank ~1 in 3 words
      const blanks = new Set();
      words.forEach((w, i) => {
        if (w.length >= 4 && (i * 37 + w.length) % 3 === 0) blanks.add(i);
      });
      let wi = 0;
      body += '<div class="mem-text">';
      toks.forEach(tok => {
        if (!tok.trim()) { body += esc(tok).replace(/\n/g, '<br>'); return; }
        const idx = wi++;
        if (blanks.has(idx)) {
          body += '<input class="mem-blank" data-i="' + idx + '" size="' + Math.max(4, tok.length) + '" placeholder="…">';
        } else {
          body += '<span class="mem-word">' + esc(tok) + '</span>';
        }
      });
      body += '</div>';
      body += '<div class="mem-foot"><button class="btn primary" id="mem-check">Check</button> ';
      body += '<span class="muted tiny" id="mem-score"></span></div>';
    } else if (this.mode === 'first') {
      body += '<div class="mem-text">';
      toks.forEach(tok => {
        if (!tok.trim()) { body += esc(tok).replace(/\n/g, '<br>'); return; }
        const first = tok.charAt(0);
        body += '<span class="mem-first">' + esc(first) + '_'.repeat(Math.max(0, tok.length-1)) + '</span>';
      });
      body += '</div>';
      body += '<div class="mem-foot"><button class="btn" id="mem-reveal">Reveal all</button></div>';
    } else {
      body += '<div class="mem-text" id="mem-full">' + esc(this.text).replace(/\n/g, '<br>') + '</div>';
      body += '<div class="mem-foot"><button class="btn" id="mem-tofirst">Test (first letters)</button></div>';
    }
    body += '</div>';
    modal('Memorise', body, [{ label: 'Close', cls: 'btn' }]);
    // wire
    $$('#modal-body [data-m]').forEach(b => b.onclick = () => { this.mode = b.dataset.m; this.render(); });
    const check = $('#mem-check');
    if (check) check.onclick = () => this.check();
    const rev = $('#mem-reveal');
    if (rev) rev.onclick = () => {
      const t = $('#modal-body .mem-text'); if (t) t.innerHTML = esc(this.text).replace(/\n/g,'<br>');
    };
    const tf = $('#mem-tofirst');
    if (tf) tf.onclick = () => { this.mode = 'first'; this.render(); };
  },

  check() {
    const toks = this.text.split(/(\s+)/);
    const words = toks.filter(t => t.trim().length > 0);
    let wi = 0, right = 0, total = 0;
    $$('#modal-body .mem-blank').forEach(inp => {
      const idx = parseInt(inp.dataset.i, 10);
      const expected = words[idx];
      const got = inp.value.trim();
      total++;
      if (got.toLowerCase() === expected.toLowerCase()) {
        right++;
        inp.classList.add('mem-ok'); inp.classList.remove('mem-bad');
      } else {
        inp.classList.add('mem-bad'); inp.classList.remove('mem-ok');
        inp.title = 'Answer: ' + expected;
      }
    });
    const sc = $('#mem-score');
    if (sc) sc.textContent = right + ' / ' + total + ' correct';
  }
};
/* ================================================================ Command box */
/* A Ctrl+K palette: type to filter, Enter to run, arrows to move.  Commands are
 * a static list of the things a reader reaches for most often; navigation
 * commands that need a reference parse it out of the query. */
const CommandBox = {
  idx: 0, filtered: [],

  commands() {
    const cmds = [
      { id: 'workspace',  label: 'Open workspace',     hint: 'panes',     run: () => App.show('workspace') },
      { id: 'search',     label: 'Search the library',  hint: '/',         run: () => { App.show('search'); setTimeout(() => $('#sq') && $('#sq').focus(), 50); } },
      { id: 'store',      label: 'Open the Store',      hint: 'install',   run: () => App.show('store') },
      { id: 'notes',      label: 'Open notes',          hint: 'notes',     run: () => App.show('notes') },
      { id: 'dashboard',  label: 'Open dashboard',      hint: 'home',      run: () => App.show('dashboard') },
      { id: 'settings',   label: 'Settings',            hint: 'prefs',     run: () => App.show('settings') },
      { id: 'preach',     label: 'Toggle preaching mode', hint: 'F',       run: () => Preach.toggle() },
      { id: 'shortcuts', label: 'Keyboard shortcuts', hint: 'keys', run: () => Shortcuts.show() },
      { id: 'sermoncal',  label: 'Sermon calendar', hint: 'preach', run: () => SermonCal.open() },
      { id: 'passageanalysis', label: 'Passage analysis', hint: 'study', run: () => PassageAnalysis.open() },
      { id: 'memorise',   label: 'Memorise current passage', hint: 'Mem',  run: () => {
          const p = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null;
          const c = p ? p._content : null;
          const text = (c && c.items) ? c.items.map(it => it.text || '').join('\n\n').trim() : '';
          if (text) Memorise.open(text, (c && c.section_title) || '');
          else toast('Open a passage first.', 'warn');
        } },
      { id: 'goto',       label: 'Go to reference (type "John 3:16")', hint: 'navigate', run: (q) => {
          const ref = (q || '').trim();
          if (!ref) { toast('Type a reference after the command.', 'warn'); return; }
          App.show('workspace');
          const pane = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null;
          if (pane) Reader.go(pane, ref);
          else toast('No pane open.', 'warn');
        } },
    ];
    return cmds;
  },

  open() {
    this.idx = 0;
    const body = '<div class="cb-wrap">'
      + '<input id="cb-q" class="cb-q" placeholder="Type a command or a reference…" autocomplete="off">'
      + '<div id="cb-list" class="cb-list"></div>'
      + '</div>';
    modal('Command box', body, [{ label: 'Close', cls: 'btn' }]);
    const input = $('#cb-q');
    const list = $('#cb-list');
    const render = () => {
      const q = (input.value || '').toLowerCase().trim();
      this.filtered = this.commands().filter(c => !q || c.label.toLowerCase().includes(q)
        || (c.hint || '').toLowerCase().includes(q));
      // also offer "go to reference" when the query looks like a reference
      if (q && !this.filtered.some(c => c.id === 'goto')) {
        this.filtered.unshift({ id: 'goto', label: 'Go to ' + input.value.trim(), hint: 'navigate',
          run: (qq) => { App.show('workspace'); const pane = (S.layout && S.layout.panes && S.layout.panes[0]) ? S.layout.panes[0] : null; if (pane) Reader.go(pane, input.value.trim()); } });
      }
      this.idx = Math.min(this.idx, Math.max(0, this.filtered.length - 1));
      list.innerHTML = this.filtered.map((c, i) =>
        '<div class="cb-row' + (i === this.idx ? ' on' : '') + '" data-i="' + i + '">'
        + '<span class="cb-lab">' + esc(c.label) + '</span>'
        + '<span class="cb-hint">' + esc(c.hint || '') + '</span></div>').join('');
      $$('#cb-list .cb-row').forEach(row => {
        row.onclick = () => { const i = parseInt(row.dataset.i, 10); this.run(i, input.value); };
      });
    };
    input.oninput = render;
    input.onkeydown = (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); this.idx = Math.min(this.filtered.length - 1, this.idx + 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.idx = Math.max(0, this.idx - 1); render(); }
      else if (e.key === 'Enter') { e.preventDefault(); this.run(this.idx, input.value); }
    };
    render();
    setTimeout(() => input.focus(), 30);
  },

  run(i, q) {
    const c = this.filtered[i];
    if (!c) return;
    closeModal();
    try { c.run(q); } catch (e) { toast('Command failed: ' + e.message, 'err'); }
  }
};
/* ================================================================ SRS */
/* Spaced repetition review.  Cards live in the backend (srs_card table);
 * this object drives the review loop: show the reference, reveal the text,
 * rate 0-5 via four buttons, advance to the next due card. */
const SRS = {
  cards: [], i: 0,
  async open() {
    const r = await api('srs/due');
    this.cards = (r && r.cards) ? r.cards : [];
    this.i = 0;
    if (!this.cards.length) {
      toast('No cards due. Add some with the SRS button on a passage.', 'warn');
      return;
    }
    this.show();
  },
  show() {
    if (this.i >= this.cards.length) {
      modal('Spaced repetition', '<div class="empty">All done for today.</div>',
            [{ label: 'Close', cls: 'btn primary' }]);
      return;
    }
    const c = this.cards[this.i];
    const body = '<div class="srs-wrap">'
      + '<div class="srs-prog">' + (this.i + 1) + ' / ' + this.cards.length + '</div>'
      + '<div class="srs-ref">' + esc(c.ref) + '</div>'
      + '<div class="srs-text" id="srs-text">' + esc(c.text || '(no text stored)') + '</div>'
      + '<div class="srs-foot">'
      + '<button class="btn" data-g="again">Again</button>'
      + '<button class="btn" data-g="hard">Hard</button>'
      + '<button class="btn primary" data-g="good">Good</button>'
      + '<button class="btn" data-g="easy">Easy</button>'
      + '</div>'
      + '<div class="tiny muted">due ' + esc(c.due) + ' · reps ' + c.reps
      + ' · ease ' + (c.ease || 2.5).toFixed(2) + '</div>'
      + '</div>';
    modal('Spaced repetition', body, [{ label: 'Skip', cls: 'btn', fn: () => { this.i++; this.show(); }, close: false },
                                     { label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-g]').forEach(b => {
      b.onclick = async () => {
        await api('srs/review', { id: c.id, grade: b.dataset.g });
        this.i++;
        this.show();
      };
    });
  }
};
/* ================================================================ Sermon calendar */
/* A month grid over the sermon calendar setting.  Scheduling itself lives in
 * SermonManager (prompt for a date); this view just reads the calendar and
 * shows what is where, so a preacher can see the month at a glance. */
const Memorization = {
  async load() {
    const body = $('#mem-body');
    const stats = $('#mem-stats');
    body.innerHTML = '<div class="st-loading">Loading…</div>';
    const r = await api('srs/due', { limit: 200 });
    const all = await api('srs/all');
    const dueCards = (r && r.cards) ? r.cards : [];
    const allCards = (all && all.cards) ? all.cards : [];
    const st = (all && all.stats) ? all.stats : (r && r.stats) || {};
    if (stats) stats.textContent = (st.total || 0) + ' cards · '
      + (st.due || 0) + ' due today · ' + (st.today || '');
    let h = '';
    if (dueCards.length) {
      h += '<h3>Due now</h3><div class="org-items">';
      h += dueCards.map(c => '<div class="org-card"><div class="org-h"><b>'
        + esc(c.ref) + '</b><span class="org-a">'
        + '<a href="#" data-mrev="' + esc(c.id) + '">review</a> '
        + '<a href="#" data-mrm="' + esc(c.id) + '">remove</a>'
        + '</span></div>'
        + '<div class="tiny muted">' + esc((c.text || '').slice(0, 120))
        + (c.text && c.text.length > 120 ? '…' : '') + '</div></div>').join('');
      h += '</div>';
    } else {
      h += '<div class="empty">No cards due right now.</div>';
    }
    if (allCards.length) {
      h += '<h3 style="margin-top:12px">All cards (' + allCards.length + ')</h3>'
        + '<div class="org-items" style="max-height:40vh;overflow:auto">';
      h += allCards.map(c => '<div class="org-card"><div class="org-h"><b>'
        + esc(c.ref) + '</b>'
        + '<span class="tiny muted"> · due ' + esc(c.due) + ' · reps ' + (c.reps || 0)
        + '</span><span class="org-a">'
        + '<a href="#" data-mrm="' + esc(c.id) + '">remove</a>'
        + '</span></div></div>').join('');
      h += '</div>';
    }
    body.innerHTML = h;
    body.querySelectorAll('[data-mrev]').forEach(a => a.onclick = (e) => {
      e.preventDefault(); SRS.open();
    });
    body.querySelectorAll('[data-mrm]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      await api('srs/remove', { id: a.dataset.mrm });
      this.load();
    });
    const addBtn = $('#mem-add');
    if (addBtn) addBtn.onclick = async () => {
      const ref = ($('#mem-ref').value || '').trim();
      if (!ref) { toast('Type a reference first.', 'warn'); return; }
      const r = await api('srs/add', { ref });
      if (r && r.ok) { toast(r.already ? 'Already a card.' : 'Card added.', r.already ? 'warn' : ''); $('#mem-ref').value = ''; this.load(); }
      else toast((r && r.error) || 'Could not add.', 'err');
    };
    const revBtn = $('#mem-review');
    if (revBtn) revBtn.onclick = () => SRS.open();
  },
};

const SermonCal = {
  y: new Date().getFullYear(), m: new Date().getMonth(),
  async open() {
    const r = await api('sermon', { action: 'calendar' });
    this.cal = (r && r.calendar) ? r.calendar : {};
    // also fetch sermon titles for the scheduled ids
    const mgr = await api('sermon', { action: 'manager' });
    const byId = {};
    (mgr.sermons || []).forEach(s => { byId[s.id] = s; });
    this.byId = byId;
    this.render();
  },
  render() {
    const first = new Date(this.y, this.m, 1);
    const last = new Date(this.y, this.m + 1, 0);
    const startDow = first.getDay();
    const days = last.getDate();
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    let h = '<div class="sc-wrap">';
    h += '<div class="sc-nav">';
    h += '<button class="btn" id="sc-prev">◀</button>';
    h += '<span class="sc-title">' + months[this.m] + ' ' + this.y + '</span>';
    h += '<button class="btn" id="sc-next">▶</button>';
    h += '</div>';
    h += '<div class="sc-grid">';
    ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].forEach(d => { h += '<div class="sc-dow">' + d + '</div>'; });
    for (let i = 0; i < startDow; i++) h += '<div class="sc-cell empty"></div>';
    for (let d = 1; d <= days; d++) {
      const key = this.y + '-' + String(this.m+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
      const nid = this.cal[key];
      const s = nid ? this.byId[nid] : null;
      h += '<div class="sc-cell' + (nid ? ' has' : '') + '">';
      h += '<div class="sc-day">' + d + '</div>';
      if (s) h += '<div class="sc-sermon" title="' + esc(s.ref_label || '') + '">' + esc(s.title) + '</div>';
      h += '</div>';
    }
    h += '</div></div>';
    modal('Sermon calendar', h, [{ label: 'Close', cls: 'btn' }]);
    $('#sc-prev').onclick = () => { this.m--; if (this.m < 0) { this.m = 11; this.y--; } this.render(); };
    $('#sc-next').onclick = () => { this.m++; if (this.m > 11) { this.m = 0; this.y++; } this.render(); };
  }
};
/* ================================================================ Passage analysis */
/* Visuals over study/passage: translations side by side (version river /
 * compare pericopes) and a word-frequency table (word tree).  SVG-grade
 * charts are out of scope for a text-first app, so the data is rendered as
 * structured HTML that a screen reader can walk. */
const PassageAnalysis = {
  async open(ref) {
    ref = ref || prompt('Passage to analyse (e.g. John 3:16):', '');
    if (!ref) return;
    const r = await api('study/passage', { ref: ref });
    if (!r || !r.ok) { toast(r && r.error ? r.error : 'No data.', 'warn'); return; }
    let h = '<div class="pa-wrap">';
    h += '<div class="pa-ref">' + esc(r.ref || ref) + '</div>';
    h += '<div class="pa-section"><div class="pa-h">Translations (version river)</div>';
    (r.texts || []).forEach(t => {
      h += '<div class="pa-trans"><b>' + esc(t.module || t.module_id || '') + '</b>'
        + '<div class="pa-text">' + esc(t.text || '') + '</div></div>';
    });
    h += '</div>';
    // word frequency
    const words = {};
    (r.texts || []).forEach(t => {
      String(t.text || '').toLowerCase().replace(/[^a-z\s]/g, ' ').split(/\s+/).forEach(w => {
        if (w.length < 3) return;
        words[w] = (words[w] || 0) + 1;
      });
    });
    const top = Object.entries(words).sort((a,b) => b[1]-a[1]).slice(0, 25);
    h += '<div class="pa-section"><div class="pa-h">Word frequency (word tree)</div>';
    h += '<table class="pa-tbl"><tr><th>word</th><th>n</th></tr>';
    top.forEach(([w,n]) => { h += '<tr><td>' + esc(w) + '</td><td>' + n + '</td></tr>'; });
    h += '</table></div>';
    if (r.xrefs && r.xrefs.length) {
      h += '<div class="pa-section"><div class="pa-h">Cross-references (compare pericopes)</div><ul>';
      r.xrefs.forEach(x => { h += '<li>' + esc(typeof x === 'string' ? x : (x.label || x.ref || JSON.stringify(x))) + '</li>'; });
      h += '</ul></div>';
    }
    if (r.people && r.people.length) {
      h += '<div class="pa-section"><div class="pa-h">People</div><ul>';
      r.people.forEach(p => { h += '<li>' + esc(p.name || p) + '</li>'; });
      h += '</ul></div>';
    }
    if (r.places && r.places.length) {
      h += '<div class="pa-section"><div class="pa-h">Places</div><ul>';
      r.places.forEach(p => { h += '<li>' + esc(p.name || p) + '</li>'; });
      h += '</ul></div>';
    }
    h += '</div>';
    modal('Passage analysis', h, [{ label: 'Close', cls: 'btn' }]);
  }
};
/* ================================================================ I18n */
const I18n = {
  locale: 'en', dict: {},
  en: {
    'app.title': 'G-Bible', 'btn.close': 'Close', 'btn.search': 'Search',
    'nav.workspace': 'Workspace', 'nav.search': 'Search', 'nav.notes': 'Notes',
    'nav.store': 'Store', 'nav.dashboard': 'Dashboard', 'toast.loading': 'Loading…',
  },
  t(key, fallback) { return (this.dict && this.dict[key]) || this.en[key] || fallback || key; },
  async load(code) {
    this.locale = code || 'en';
    if (code && code !== 'en') {
      try { const r = await fetch('locales/' + code + '.json'); if (r.ok) this.dict = await r.json(); }
      catch (e) { this.dict = {}; }
    } else { this.dict = {}; }
  }
};
window.t = (k, f) => I18n.t(k, f);

/* ================================================================= Notes */
/* Notes, journal, sermon prep and prayer lists: one object, four intents.  The
 * editor is deliberately the same for all four; what changes is the title bar
 * and, for prayer, that the body is a list you can tick. */
const Notes = {
  items: [],
  current: null,

  async load() {
    const kind = $('#n-kind').value;
    const q = ($('#n-q').value || '').trim();
    const r = await api('notes/list', { kind, q, limit: 500 });
    this.items = r.notes || [];
    const s = r.stats || {};
    const by = s.by_kind || {};
    $('#notes-summary').textContent =
      `${s.total || 0} total · ${by.note || 0} notes · ${by.journal || 0} journal`
      + ` · ${by.sermon || 0} sermon · ${by.prayer || 0} prayer`;
    this.paintList();
  },

  paintList() {
    const host = $('#notes-list');
    host.innerHTML = '';
    if (!this.items.length) {
      host.appendChild(el('div', 'empty', 'Nothing yet.'));
      return;
    }
    this.items.forEach(n => {
      const row = el('div', 'note-row'
        + (this.current && this.current.id === n.id ? ' on' : ''));
      const when = new Date((n.updated_at || 0) * 1000)
        .toISOString().slice(0, 10);
      row.innerHTML = '<div class="note-t">' + esc(n.title || '(untitled)')
        + '</div><div class="tiny muted">' + esc(n.kind) + ' · ' + when
        + (n.ref_label ? ' · ' + esc(n.ref_label) : '') + '</div>';
      row.onclick = () => this.edit(n.id);
      host.appendChild(row);
    });
  },

  blank(kind) {
    const k = kind || $('#n-kind').value || 'note';
    return { id: '', kind: k === '' ? 'note' : k, title: '', body: '',
             module_id: '', unit_key: '', ref_label: '', tags: [],
             meta: { passages: [] } };
  },

  new() {
    this.edit(this.blank());
  },

  /* The notes attached to one verse, from a marker in the reader.  Shown in a
   * dialog rather than by switching to the Notes screen: the reader is in the
   * middle of a passage, and jumping away to read a note about the verse in
   * front of them loses their place in it.  Each one opens for editing, which
   * is the same editor the Notes screen uses. */
  showAt(label, rows) {
    modal('Notes on ' + label,
      (rows || []).map((n, i) => '<div class="st-note">'
        + '<div class="st-src">' + esc(n.kind || 'note')
        + ' · ' + esc(new Date((n.updated_at || 0) * 1000)
            .toISOString().slice(0, 10)) + '</div>'
        + (n.title ? '<div class="st-t">' + esc(n.title) + '</div>' : '')
        + '<div class="st-body">' + esc(n.body || '(no text)') + '</div>'
        + '<div class="tiny"><a href="#" data-ntedit="' + esc(n.id)
        + '">open and edit</a>'
        + (n.module_id && n.unit_key
           ? ' · <span class="muted">on '
             + esc(((modById(n.module_id) || {}).name || n.module_id))
             + '</span>' : '')
        + '</div></div>').join('')
      || '<div class="empty">No notes on that verse.</div>',
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-ntedit]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      App.show('notes');
      this.edit(a.dataset.ntedit);
    });
  },

  async edit(id) {
    let n;
    if (typeof id === 'object') n = id;
    else n = (await api('notes/get', { id })).note;
    if (!n) return;
    this.current = n;
    this.paintList();
    const host = $('#notes-edit');
    const titles = { note: 'Note', journal: 'Journal entry',
                     sermon: 'Sermon', prayer: 'Prayer list' };
    host.innerHTML =
      '<div class="store-head" style="border:0;padding:0 0 8px">'
      + '<input id="ne-title" placeholder="' + esc(titles[n.kind] || 'Note')
      + ' title" value="' + esc(n.title) + '" '
      + 'style="flex:1;background:var(--bg-3);border:1px solid var(--line-2);'
      + 'color:var(--fg);padding:8px;border-radius:7px;font-size:15px">'
      + '<button class="btn primary" id="ne-save">Save</button>'
      + '<button class="btn" id="ne-del">Delete</button></div>'
      + (n.ref_label ? '<div class="tiny muted" style="margin-bottom:6px">'
        + esc(n.ref_label) + ' · ' + esc(n.module_id || '') + '</div>' : '')
      + '<textarea id="ne-body" rows="16" style="width:100%;background:var(--bg-3);'
      + 'border:1px solid var(--line-2);color:var(--fg);padding:10px;'
      + 'border-radius:7px;font-family:inherit;font-size:13.5px" '
      + 'placeholder="' + (n.kind === 'prayer' ? 'One item per line'
        : n.kind === 'sermon' ? 'Outline, in plain text' : 'Write here')
      + '">' + esc(n.body) + '</textarea>'
      + '<div class="tiny muted" style="margin-top:6px">'
      + (n.kind === 'prayer' ? 'One request per line. '
        + '<a href="#" id="ne-md">Download as Markdown</a>'
        : 'Saved to this machine. <a href="#" id="ne-md">Download as Markdown</a>'
        + (n.kind === 'sermon' && n.id
          ? ' · <a href="#" id="ne-slides">Slides</a>'
            + ' · <a href="#" id="ne-hand">Handout</a>' : ''))
      + '</div>';
    /* The sermon-save path above collects passages with a regular expression
     * over the body.  That is a guess: it matches anything shaped like a
     * reference, including a date or a verse range inside a quotation of
     * somebody else.  This button asks the reference parser instead, shows
     * what it found, and lets you turn those into a real passage list -- so
     * the readings for a sermon are the ones you chose rather than the ones a
     * pattern happened to catch. */
    if (n.kind !== 'prayer') {
      host.insertAdjacentHTML('beforeend',
        '<div class="tiny" style="margin-top:6px">'
        + '<a href="#" id="ne-refs">Find the scripture references in this note'
        + '</a></div>');
    }
    const refsBtn = $('#ne-refs');
    if (refsBtn) {
      refsBtn.onclick = async () => {
        const text = $('#ne-body').value || '';
        if (!text.trim()) { toast('The note is empty.', 'warn'); return; }
        const found = await api('auto-refs', { text });
        const refs = found.refs || [];
        if (!refs.length) {
          toast('No scripture references found in that text.', 'warn');
          return;
        }
        modal('References in this note',
          '<div class="tiny muted" style="margin-bottom:8px">'
          + refs.length + ' reference' + (refs.length === 1 ? '' : 's')
          + ' the parser found, in the order they appear. These are the ones '
          + 'it recognises — it has no way to know which are quotations of '
          + 'somebody else.</div>'
          + '<div class="org-items" style="max-height:50vh;overflow:auto">'
          + refs.map((r, i) => '<span class="org-item"><label>'
            + '<input type="checkbox" class="nr-chk" value="' + esc(r.label)
            + '"' + (i < 99 ? ' checked' : '') + '> ' + esc(r.label)
            + '</label></span>').join('') + '</div>'
          + '<div class="st-tools" style="margin-top:10px">'
          + '<input type="search" id="nr-name" placeholder="name the list"'
          + ' value="' + esc(n.title ? n.title + ' — passages' : 'Passages')
          + '" style="flex:1">'
          + '<button class="btn primary" id="nr-make">Make a passage list</button>'
          + '</div>', [
          { label: 'Close', cls: 'btn' }]);
        $('#nr-make').onclick = async () => {
          const picked = $$('#modal-body .nr-chk')
            .filter(c => c.checked).map(c => c.value);
          if (!picked.length) { toast('Nothing ticked.', 'warn'); return; }
          const name = $('#nr-name').value.trim() || 'Passages';
          /* An English Bible by preference: the list is made of references
           * parsed with the default (KJV) versification, and "the first Bible
           * installed" is sorted by name, which can be a Basque New Testament.
           * Any Bible can still carry the list -- the user chose the passages,
           * not the translation -- but the default should be readable. */
          const bible = S.modules.find(m => m.is_bible && m.lang === 'eng')
            || S.modules.find(m => m.is_bible);
          if (!bible) { toast('No Bible is installed.', 'warn'); return; }
          const res = await api('passagelist/from_refs', { refs: picked,
            name, module: bible.id });
          closeModal();
          if (!res.ok) { toast(res.error || 'Could not make that list.', 'err'); return; }
          App.show('organise');
          $('#o-tab').value = 'lists';
          Organise.load();
          toast(res.added + ' added to "' + name + '"'
            + (res.missing && res.missing.length
              ? ' · ' + res.missing.length + ' could not be read'
              : '') + '.');
        };
      };
    }
    $('#ne-save').onclick = async () => {
      n.title = $('#ne-title').value;
      n.body = $('#ne-body').value;
      if (n.kind === 'sermon') {
        n.meta = n.meta || {};
        n.meta.text = n.body;
        n.meta.passages = (n.body.match(/\b[A-Za-z0-9]+\s+\d+:\d+[^\n]*/g) || [])
          .slice(0, 40);
      }
      await post('notes/save', n);
      toast('Saved.');
      this.current = null;
      await this.load();
    };
    $('#ne-del').onclick = async () => {
      if (!n.id) return;
      await post('notes/delete', { id: n.id });
      this.current = null;
      host.innerHTML = '<div class="empty">Choose a note, or press <b>New</b>.</div>';
      await this.load();
    };
    $('#ne-md').onclick = async (e) => {
      e.preventDefault();
      const r = await api('notes/export', { kind: n.kind });
      const blob = new Blob([r.markdown], { type: 'text/markdown' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'gbible-notes.md';
      a.click();
      URL.revokeObjectURL(a.href);
    };
    const dlSermon = async (e, kind) => {
      e.preventDefault();
      const r = await api('sermon', { action: 'export', id: n.id, kind });
      if (!r.ok) { toast(r.error || 'Nothing to export.', 'warn'); return; }
      const blob = new Blob([r.html], { type: 'text/html' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = r.filename || ('sermon-' + kind + '.html');
      a.click();
      URL.revokeObjectURL(a.href);
    };
    const sl = $('#ne-slides');
    if (sl) sl.onclick = (e) => dlSermon(e, 'slides');
    const ha = $('#ne-hand');
    if (ha) ha.onclick = (e) => dlSermon(e, 'handout');
  },

  /* Attach a note to whatever the reader is looking at. */
  async addHere(m, unitKey, refLabel, quote) {
    return this.edit({
      id: '', kind: 'note', title: quote ? quote.slice(0, 60) : (refLabel || ''),
      body: quote || '', module_id: m ? m.id : '', unit_key: unitKey || '',
      ref_label: refLabel || '', tags: [], meta: {},
    });
  },
};

/* ============================================================== Atlas */
/* A slippy map, written here rather than pulled from a library.
 *
 * The obvious build is Leaflet from a CDN.  Three reasons it is not that: this
 * project loads nothing from anywhere (the only outbound request it makes today
 * is the map tile below, and the project states that in its own documentation);
 * a CDN script cannot be pinned to a version without pinning your whole
 * application to when the CDN operator decides to ship a new one; and a map
 * viewer is about two hundred lines of arithmetic, which is not a dependency.
 *
 * What that buys is honest behaviour on failure.  Tiles come from OpenStreetMap
 * and will not always arrive -- no network, a blocked host, an offline laptop.
 * When they do not, the graticule, the coast-to-coast bounding box and every
 * marker still draw, because none of those needs a tile.  A map that becomes a
 * grey rectangle is worse than one that becomes a coordinate grid with the
 * places on it.
 *
 * Attribution is required by the ODbL and is drawn on the canvas itself, always,
 * rather than in a corner the reader can scroll away from.
 */
const Atlas = {
  TILE: 256,
  MIN: 2, MAX: 18,
  /* Web Mercator, which is the projection OSM tiles are in. */
  _px(lat, lon, z) {
    const n = Math.pow(2, z) * this.TILE;
    const x = (lon + 180) / 360 * n;
    const s = Math.sin(lat * Math.PI / 180);
    const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
    return [x, y];
  },
  _ll(x, y, z) {
    const n = Math.pow(2, z) * this.TILE;
    const lon = x / n * 360 - 180;
    const t = Math.PI - 2 * Math.PI * y / n;
    const lat = 180 / Math.PI * Math.atan(0.5 * (Math.exp(t) - Math.exp(-t)));
    return [lat, lon];
  },

  /* markers: [{lat, lon, label, kind, onPick}] */
  mount(host, markers, opts) {
    const o = Object.assign({ lat: 31.5, lon: 35.0, z: 6, height: 420 }, opts || {});
    const st = this._st = { z: o.z, cx: o.lon, cy: o.lat, markers: markers || [] };
    host.classList.add('atlas');
    host.style.height = o.height + 'px';
    host.innerHTML =
      '<canvas class="atlas-cv"></canvas>'
      + '<div class="atlas-ctl">'
      + '<button class="btn tiny" data-a="zin">+</button>'
      + '<button class="btn tiny" data-a="zout">−</button>'
      + '<button class="btn tiny" data-a="fit">Fit</button>'
      + '<span class="atlas-z tiny muted">z' + o.z + '</span>'
      + '<span class="atlas-note tiny"></span>'
      + '</div>'
      + '<div class="atlas-attr tiny">Map tiles © OpenStreetMap '
      + 'contributors, ODbL. Place data CC BY 4.0.</div>';
    const cv = host.querySelector('.atlas-cv');
    /* Wire before drawing.  `draw()` sizes the canvas from `this._host`, which
     * `_wire` sets -- so drawing first left the canvas at its 300x150 default
     * with nothing on it, and the map only appeared later, when a tile arrived
     * and called draw() again.  With no network -- the case this atlas is
     * explicitly built to survive -- no tile ever arrives and the map never
     * appeared at all. */
    this._wire(host, cv);
    this._fit(markers);
    this.draw();
    return st;
  },

  _fit(markers) {
    const st = this._st;
    const ms = (markers || []).filter(m => m && isFinite(m.lat) && isFinite(m.lon));
    if (!ms.length) return;
    let la0 = 90, la1 = -90, lo0 = 180, lo1 = -180;
    ms.forEach(m => {
      la0 = Math.min(la0, m.lat); la1 = Math.max(la1, m.lat);
      lo0 = Math.min(lo0, m.lon); lo1 = Math.max(lo1, m.lon);
    });
    st.cy = (la0 + la1) / 2;
    st.cx = (lo0 + lo1) / 2;
    // Largest zoom whose whole extent fits, so "Fit" means fit.
    for (let z = this.MAX; z >= this.MIN; z--) {
      const [x0, y0] = this._px(la1, lo0, z);
      const [x1, y1] = this._px(la0, lo1, z);
      if (Math.abs(x1 - x0) < this._w() * 0.86
        && Math.abs(y1 - y0) < this._h() * 0.72) { st.z = z; return; }
    }
    st.z = this.MIN;
  },

  _w() { return (this._host && this._host.clientWidth) || 640; },
  _h() { return (this._host && this._host.clientHeight) || 420; },

  draw() {
    const st = this._st;
    const cv = this._host && this._host.querySelector('.atlas-cv');
    if (!cv) return;
    const W = this._w(), H = this._h(), z = st.z;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(document.body);
    const bg = css.getPropertyValue('--bg-2').trim() || '#12151a';
    const line = css.getPropertyValue('--line').trim() || '#2a2f38';
    const fg = css.getPropertyValue('--fg-3').trim() || '#7b8494';
    const accent = css.getPropertyValue('--accent').trim() || '#f0b429';
    g.fillStyle = bg;
    g.fillRect(0, 0, W, H);

    const [ccx, ccy] = this._px(st.cy, st.cx, z);
    const at = ([x, y]) => [x - ccx + W / 2, y - ccy + H / 2];

    /* Tiles first, so everything drawn after sits on top of them. */
    const n = Math.pow(2, z);
    const x0 = Math.floor((ccx - W / 2) / this.TILE);
    const y0 = Math.floor((ccy - H / 2) / this.TILE);
    const x1 = Math.floor((ccx + W / 2) / this.TILE);
    const y1 = Math.floor((ccy + H / 2) / this.TILE);
    let got = 0, asked = 0;
    for (let tx = x0; tx <= x1; tx++) {
      for (let ty = y0; ty <= y1; ty++) {
        if (ty < 0 || ty >= n) continue;
        asked++;
        const img = this._tile(tx, ty, z);
        if (img && img.complete && img.naturalWidth) {
          got++;
          const [sx, sy] = at([tx * this.TILE, ty * this.TILE]);
          g.drawImage(img, sx, sy, this.TILE, this.TILE);
        }
      }
    }

    /* A graticule every 5 degrees, and the prime meridian, so the map still
     * reads as a map when no tile arrived. */
    g.strokeStyle = line;
    g.fillStyle = fg;
    g.lineWidth = 1;
    g.font = '10px system-ui, sans-serif';
    for (let lat = -80; lat <= 80; lat += 5) {
      const [, y] = this._px(lat, 0, z);
      const sy = at([0, y])[1];
      if (sy < -20 || sy > H + 20) continue;
      g.beginPath(); g.moveTo(0, sy); g.lineTo(W, sy); g.stroke();
      g.fillText(lat + '°', 4, sy - 3);
    }
    for (let lon = -180; lon <= 180; lon += 10) {
      const [x] = this._px(0, lon, z);
      const sx = at([x, 0])[0];
      if (sx < -20 || sx > W + 20) continue;
      g.beginPath(); g.moveTo(sx, 0); g.lineTo(sx, H); g.stroke();
      g.fillText(lon + '°', sx + 3, H - 5);
    }

    /* Markers, drawn after the tiles and never sorted behind them. */
    const ms = st.markers.filter(m => isFinite(m.lat) && isFinite(m.lon));
    ms.forEach(m => {
      const [x, y] = this._px(m.lat, m.lon, z);
      const [sx, sy] = at([x, y]);
      if (sx < -12 || sx > W + 12 || sy < -12 || sy > H + 12) return;
      g.beginPath();
      g.arc(sx, sy, 5.5, 0, Math.PI * 2);
      g.fillStyle = m.color || accent;
      g.fill();
      g.lineWidth = 1.5;
      g.strokeStyle = bg;
      g.stroke();
      st._hit = st._hit || [];
      st._hit.push({ x: sx, y: sy, m });
    });
    st._hit = (st._hit || []).filter(h =>
      h.x >= -12 && h.x <= W + 12 && h.y >= -12 && h.y <= H + 12);
    const note = this._host.querySelector('.atlas-note');
    if (note) {
      note.textContent = asked && !got
        ? 'no tiles loaded — showing coordinates only'
        : (asked ? got + '/' + asked + ' tiles' : '');
    }
    const zl = this._host.querySelector('.atlas-z');
    if (zl) zl.textContent = 'z' + z;
  },

  _tiles: {},
  _tile(x, y, z) {
    const key = z + '/' + x + '/' + y;
    if (this._tiles[key]) return this._tiles[key];
    const img = new Image();
    /* OSM's own tile usage policy: a fixed, identifiable referrer and no bulk
     * downloading.  This is the one outbound request the application makes, and
     * the attribution is on the canvas. */
    img.crossOrigin = 'anonymous';
    img.referrerPolicy = 'origin';
    img.src = 'https://tile.openstreetmap.org/' + z + '/' + x + '/' + y + '.png';
    img.addEventListener('load', () => this.draw());
    img.addEventListener('error', () => {});
    this._tiles[key] = img;
    return img;
  },

  _wire(host, cv) {
    this._host = host;
    let drag = null;
    cv.addEventListener('mousedown', (e) => {
      drag = { x: e.clientX, y: e.clientY, cx: this._st.cx, cy: this._st.cy,
               moved: false };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      const st = this._st;
      const [x0, y0] = this._px(st.cy, st.cx, st.z);
      const x = x0 - (e.clientX - drag.x);
      const y = y0 - (e.clientY - drag.y);
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 3) {
        drag.moved = true;
      }
      const [lat, lon] = this._ll(x, y, st.z);
      st.cy = Math.max(-85, Math.min(85, lat));
      st.cx = lon;
      this.draw();
    });
    window.addEventListener('mouseup', (e) => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      if (moved) return;
      const r = cv.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const hit = (this._st._hit || []).find(h =>
        Math.abs(h.x - px) < 9 && Math.abs(h.y - py) < 9);
      if (hit && hit.m.onPick) hit.m.onPick(hit.m);
    });
    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      this._zoomBy(e.deltaY < 0 ? 1 : -1, e);
    }, { passive: false });
    // Touch: one finger pans, two pinch.  Without the pinch it is not usable
    // on a tablet, and the pane is the same size on one as on the other.
    let touch = null;
    cv.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        touch = { d: 0, x: e.touches[0].clientX, y: e.touches[0].clientY,
                  cx: this._st.cx, cy: this._st.cy };
      } else if (e.touches.length === 2) {
        touch = { pinch: true, d: this._touchDist(e.touches) };
      }
    }, { passive: true });
    cv.addEventListener('touchmove', (e) => {
      if (!touch) return;
      e.preventDefault();
      const st = this._st;
      if (touch.pinch && e.touches.length === 2) {
        const d = this._touchDist(e.touches);
        if (touch.d) this._zoomBy((d > touch.d ? 1 : -1) * 0.6, e);
        touch.d = d;
        return;
      }
      const t = e.touches[0];
      const [x0, y0] = this._px(st.cy, st.cx, st.z);
      const [lat, lon] = this._ll(
        x0 - (t.clientX - touch.x), y0 - (t.clientY - touch.y), st.z);
      st.cy = Math.max(-85, Math.min(85, lat));
      st.cx = lon;
      this.draw();
    }, { passive: false });
    cv.addEventListener('touchend', () => { touch = null; });
    $$('[data-a]', host).forEach(b => b.onclick = () => {
      if (b.dataset.a === 'zin') this._zoomBy(1, b);
      else if (b.dataset.a === 'zout') this._zoomBy(-1, b);
      else { this._fit(this._st.markers); this.draw(); }
    });
    window.addEventListener('resize', () => this.draw());
  },

  _touchDist(t) {
    const dx = t[0].clientX - t[1].clientX;
    const dy = t[0].clientY - t[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  },

  /* Zoom keeping the point under the pointer where it can be worked out, and
   * the centre otherwise -- zooming towards the top-left corner because that is
   * what the arithmetic defaults to is the classic slippy-map bug. */
  _zoomBy(dz, ev) {
    const st = this._st;
    const nz = Math.max(this.MIN, Math.min(this.MAX, st.z + dz));
    if (nz === st.z) return;
    let ax = 0.5, ay = 0.5;
    const r = this._host.querySelector('.atlas-cv').getBoundingClientRect();
    if (ev && ev.clientX != null) {
      ax = (ev.clientX - r.left) / r.width;
      ay = (ev.clientY - r.top) / r.height;
    }
    const [fx, fy] = this._px(st.cy, st.cx, nz);
    const [lx, ly] = this._ll(fx - (ax - 0.5) * this._w(),
                             fy - (ay - 0.5) * this._h(), nz);
    st.z = nz;
    st.cy = lx;
    st.cx = ly;
    this.draw();
  },

  /* Every place in the gazetteer, on one map. */
  async showAtlas(host) {
    const r = await api('places', { limit: 400 });
    if (!r.ok) { host.innerHTML = esc(r.error || 'no places'); return; }
    /* Key on something stable.  A few entries in the gazetteer carry no `id`,
     * so `data-id` was empty for them and every one of them matched every other
     * when a place was looked up -- pressing "Abana" could open Abdon. */
    const seen = new Set();
    const list = (r.places || []).filter(p => {
      if (p.lat == null || p.lon == null || !isFinite(p.lat) || !isFinite(p.lon)) {
        return false;
      }
      const key = p.id || p.slug || ((p.name || '') + '@' + p.lat + ','
                                     + p.lon);
      if (seen.has(key)) return false;
      seen.add(key);
      p.__key = key;
      return true;
    });
    host.innerHTML = '';
    const bar = el('div', 'atlas-bar');
    const search = el('input', 'st-lbl', '');
    search.type = 'search';
    search.placeholder = 'filter ' + list.length + ' places';
    const out = el('div', 'atlas-list');
    bar.appendChild(search);
    const mapHost = el('div', 'atlas-map');
    const two = el('div', 'atlas-two');
    two.appendChild(mapHost);
    two.appendChild(out);
    host.appendChild(bar);
    host.appendChild(two);

    const paint = (term) => {
      const t = (term || '').trim().toLowerCase();
      const ms = list.filter(p => !t
        || (p.name || '').toLowerCase().includes(t)
        || (p.alt_names || []).some(a => (a || '').toLowerCase().includes(t)));
      this.mount(mapHost, ms.map(p => ({
        lat: p.lat, lon: p.lon, label: p.name, p,
        onPick: () => this.showPlace(p),
      })), {});
      out.innerHTML = ms.slice(0, 300).map(p =>
        '<button class="atlas-item" data-id="' + esc(p.__key) + '">'
        + '<b>' + esc(p.name) + '</b>'
        + '<span class="ll">' + esc(p.lat.toFixed(3)) + ', '
        + esc(p.lon.toFixed(3)) + '</span>'
        + (p.comment ? '<span class="cm tiny muted">' + esc(p.comment)
          + '</span>' : '')
        + '</button>').join('');
      $$('.atlas-item', out).forEach(b => b.onclick = () => {
        const p = ms.find(x => x.__key === b.dataset.id);
        if (p) this.showPlace(p);
      });
    };
    search.oninput = debounce(() => paint(search.value), 220);
    paint('');
  },

  showPlace(p) {
    modal(p.name || 'Place',
      '<table class="kv"><tr><td>Type</td><td>' + esc(p.type || '—') + '</td></tr>'
      + '<tr><td>Coordinates</td><td>' + esc(p.lat.toFixed(5)) + ', '
      + esc(p.lon.toFixed(5)) + '</td></tr>'
      + (p.alt_names && p.alt_names.length
        ? '<tr><td>Also</td><td>' + esc(p.alt_names.join(', ')) + '</td></tr>' : '')
      + '<tr><td>Named at</td><td>' + ((p.passages || []).slice(0, 40).map(k =>
          '<a href="#" data-openref2="' + esc(k) + '">' + esc(k) + '</a>')
          .join(', ') || '—') + '</td></tr></table>'
      + (p.comment ? '<div class="notice">' + esc(p.comment) + '</div>' : '')
      + '<div class="tiny muted" style="margin-top:8px">Place data '
      + 'CC BY 4.0, from OpenBible Geography. Tiles © OpenStreetMap '
      + 'contributors, ODbL.</div>',
      [{ label: 'Show on map', fn: () => {
          const s = Atlas._st;
          if (s) { s.cx = p.lon; s.cy = p.lat; s.z = 6; Atlas.draw(); }
        } },
       { label: 'Find pictures', fn: () => {
           closeModal();
           Media.openWith(p.name || '');
         } },
       { label: 'Close', cls: 'btn' }]);
    $$('#modal-body a[data-openref2]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      Reader.openRefAnywhere(a.dataset.openref2);
    });
  },
};

/* ============================================================== Dashboard */
const Dashboard = {
  async load() {
    const d = await api('dashboard');
    if (!d || !d.ok) {
  const r = $('#d-reading');
  if (r) r.innerHTML = '<div class="dash-h">Dashboard</div>'
    + '<div class="empty">Could not load the dashboard. '
    + '<button class="btn tiny" id="dash-retry">Retry</button></div>';
  const rb = $('#dash-retry'); if (rb) rb.onclick = () => Dashboard.load();
  return;
}
    $('#d-title').textContent = d.date || (d.weekday + ' ' + d.day);
    $('#d-lib').textContent = `${d.library.modules} modules · `
      + `${d.library.units.toLocaleString()} units`
      + (d.library.highlights ? ` · ${d.library.highlights} highlights` : '');

    // -- today's reading, from the devotionals that are installed
    const r = $('#d-reading');
    if (d.library.modules === 0) {
      r.innerHTML = '<div class="dash-h">Get started</div>'
        + '<div class="st-body">Your library is empty. Install the recommended '
        + 'set of Bibles, commentaries, maps and lexica, or browse the Store.</div>'
        + '<div class="tiny" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">'
        + '<a href="#" data-goto="store">Open Store</a>'
        + '<a href="#" id="d-rec">Install recommended</a></div>';
      const rec = $('#d-rec');
      if (rec) rec.onclick = (e) => { e.preventDefault(); (async () => { const st = await api('recommended/status'); if (st && st.ok && st.total > 0) RecommendedPrompt.show(st); })(); };
      // fall through to the rest
    } else if ((d.readings || []).length) {
      r.innerHTML = '<div class="dash-h">Today’s reading</div>'
        + d.readings.map(x =>
          '<div class="dash-item"><div class="dash-src">'
          + esc(x.module) + (x.title ? ' · ' + esc(x.title) : '')
          + '</div><div class="st-body">'
          + esc(x.text.slice(0, 900))
          + (x.text.length > 900 ? '…' : '') + '</div>'
          + '<div class="tiny"><a href="#" data-open="'
          + esc(x.module_id) + '" data-key="' + esc(x.title || '')
          + '">Open</a></div></div>').join('');
    } else {
      r.innerHTML = '<div class="dash-h">Today’s reading</div>'
        + '<div class="empty">No devotional is installed. '
        + '<a href="#" data-goto="store">Install one</a> from Modules.</div>';
    }

    /* -- the reading plan, which is a different thing from a devotional.
     *
     * The devotional above is a calendar: it was written for a date.  A plan has
     * day numbers, because the question a reader actually has is "how far
     * through am I" and "what was day 90", and a date answers neither.  It also
     * names the passages, so pressing a day takes you to the text. */
    await this.planCard();

    // -- prayer list for the day
    const p = $('#d-prayer');
    const pr = d.prayer;
    p.innerHTML = '<div class="dash-h">Prayer</div>' + (pr && pr.body
      ? '<div class="st-body">' + esc(pr.body) + '</div>'
        + '<div class="tiny"><a href="#" data-goto="notes">Edit</a></div>'
      : '<div class="empty">Nothing for today. '
        + '<a href="#" data-newprayer>Add a list</a>.</div>');

    /* -- what is due, in one place.
     *
     * A plan with an unread day and a prayer that has come round again are two
     * different tables.  This card renders both, placed under the reading plan
     * card rather than the prayer card so the grouping makes sense. */
    const due = await api('reminders').catch(() => ({ ok: false }));
    const plans = (due.plans_due || []), prayers = (due.prayers_due || []);
    if (plans.length || prayers.length) {
      const planCard = $('#d-plan');
      if (planCard) {
        planCard.insertAdjacentHTML('beforeend',
          '<div class="dash-h" style="margin-top:10px">Due</div>'
          + plans.map(x => '<div class="dash-row"><a href="#" data-goto="plans">'
            + esc(x.title || 'Reading plan') + '</a> '
            + '<span class="muted tiny">day ' + esc(x.next_day) + '</span></div>')
            .join('')
          + prayers.map(x => '<div class="dash-row"><a href="#" data-goto="prayer">'
            + esc(x.title || 'Prayer') + '</a> '
            + '<span class="muted tiny">due again</span></div>').join(''));
      }
    }

    // -- where you were
    const w = $('#d-where');
    w.innerHTML = '<div class="dash-h">Continue'
      + (d.layout ? ' <span class="muted">· ' + esc(d.layout) + '</span>' : '')
      + '</div>'
      + ((d.where || []).length
        ? d.where.slice(0, 8).map(x =>
          '<div class="dash-row"><a href="#" data-pane="' + esc(x.pane_id)
          + '"><b>' + esc(x.module) + '</b></a> '
          + (x.position
            ? '<span class="muted">' + esc(x.position)
              + (x.span ? ' · ' + esc(x.span) : '') + '</span>'
            : '<span class="muted tiny">not opened yet</span>')
          + '</div>').join('')
        : '<div class="empty">No panes in this layout.</div>');

    // -- highlights (client-side; the endpoint already existed)
    this.paintHighlights();

    // -- tags
    const tg = $('#d-tags');
    if (tg) {
      await Tags.load();
      tg.innerHTML = '<div class="dash-h">Tags'
        + (Tags.tags.length
          ? ' <span class="muted">' + Tags.tags.length + '</span>'
          : '') + '</div>'
        + (Tags.tags.length
          ? Tags.tags.map(t => '<div class="dash-row"><a href="#" '
            + 'data-tagopen="' + esc(t.id) + '">' + esc(t.name) + '</a> '
            + '<span class="muted tiny">· ' + t.count + '</span></div>').join('')
          : '<div class="empty">Nothing tagged yet. Right-click a verse '
            + '&rarr; <b>Tag this verse</b>.</div>');
    }

    // -- what you wrote
    const n = $('#d-notes');
    const st = d.notes_stats || {};
    n.innerHTML = '<div class="dash-h">Your notes <span class="muted">'
      + (st.total || 0) + '</span></div>'
      + ((d.recent_notes || []).length
        ? d.recent_notes.map(x =>
          '<div class="dash-row"><a href="#" data-note="' + esc(x.id) + '">'
          + esc(x.title || '(untitled)') + '</a> '
          + '<span class="muted tiny">' + esc(x.kind)
          + (x.ref_label ? ' · ' + esc(x.ref_label) : '') + '</span></div>').join('')
        : '<div class="empty">Nothing written yet. '
        + '<a href="#" data-goto="notes">Start a note</a>.</div>');

    this.wire();
    DashLayout.apply();
  },

  /* Which plan the card is showing, read from the control rather than from a
   captured value.
   *
   * The handlers used to close over `known`, a local computed when the card was
   * built.  Every re-render of the card rebuilt the buttons with a new closure,
   * and the click landed on whichever one the previous render left in the DOM
   * when a re-render and a click raced -- so pressing "All days" sometimes
   * opened nothing at all, with no error anywhere to explain it.  Reading the
   * control at click time cannot go stale, because the control is what the
   * reader can actually see. */
  planShown() {
    const s = $('#rp-plan');
    return (s && s.value) || 'bible';
  },

  /* The reading-plan card.
   *
   * Shows one day: which day it is, how far through the plan that is, the
   * passages, and a mark-as-read button.  Day 0 is "the first day not yet
   * marked", so the card resumes after a gap rather than resetting to day 1
   * every morning -- which is the difference between a plan and a calendar, and
   * the reason a plan is worth having separately from a devotional.
   */
  async planCard() {
    const card = $('#d-plan');
    if (!card) return;
    const p = await api('readingplan/plans');
    if (!p.ok || !(p.plans || []).length) {
      card.innerHTML = '<div class="dash-h">Reading plan</div>'
        + '<div class="empty">No plan can be built from this library yet. A plan '
        + 'needs a Bible to read or a devotional to number.</div>';
      return;
    }
    const plan = (S.plan || 'bible');
    const known = p.plans.some(x => x.id === plan) ? plan : p.plans[0].id;
    const d = await api('readingplan/day', { plan: known, day: 0 });
    if (!d.ok) {
      card.innerHTML = '<div class="dash-h">Reading plan</div>'
        + '<div class="empty">' + esc(d.error || 'Could not read the plan.')
        + '</div>';
      return;
    }
    const doneN = (p.progress && p.progress[known] || []).length;
    card.innerHTML = '<div class="dash-h">Reading plan'
      + ' <span class="muted tiny">day ' + d.day + ' of ' + d.total + '</span></div>'
      + '<select id="rp-plan" class="st-lbl" style="margin:4px 0">'
      + p.plans.map(x => '<option value="' + esc(x.id) + '"'
        + (x.id === known ? ' selected' : '') + '>' + esc(x.title) + ' — '
        + esc(x.sub) + '</option>').join('') + '</select>'
      + (d.note ? '<div class="tiny muted">' + esc(d.note) + '</div>' : '')
      + '<div class="dash-item"><div class="dash-src">'
      + esc(d.head || ('Day ' + d.day)) + '</div>'
      + (d.passages && d.passages.length
        ? '<div class="tiny"><a href="#" data-openref="'
          + esc(d.passages[0]) + '">' + esc(d.passages.join(' · ')) + '</a></div>'
        : '')
      + (d.text ? '<div class="st-body">' + esc(d.text.slice(0, 700))
        + (d.text.length > 700 ? '…' : '') + '</div>' : '')
      + '<div class="row" style="gap:8px;margin-top:6px">'
      + '<button class="btn tiny" id="rp-mark">'
      + (d.done ? 'Marked read ✓' : 'Mark as read') + '</button>'
      + '<button class="btn tiny" id="rp-prev">◀ Day ' + (d.day - 1) + '</button>'
      + '<button class="btn tiny" id="rp-next">Day ' + (d.day + 1) + ' ▶</button>'
      + '<button class="btn tiny" id="rp-all">All days</button>'
      + '</div></div>'
      + '<div class="tiny muted">' + doneN + ' of ' + d.total + ' marked read</div>';

    const sel = $('#rp-plan');
    if (sel) sel.onchange = () => { S.plan = sel.value; this.planCard(); };
    $('#rp-mark').onclick = async () => {
      await api('readingplan/mark',
        { plan: this.planShown(), day: d.day, done: d.done ? 0 : 1 });
      this.planCard();
    };
    $('#rp-prev').onclick = () =>
      this.showPlanDay(this.planShown(), Math.max(1, d.day - 1));
    $('#rp-next').onclick = () =>
      this.showPlanDay(this.planShown(), Math.min(d.total, d.day + 1));
    $('#rp-all').onclick = () => this.planOverview(this.planShown());
    $$('#d-plan a[data-openref]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      Reader.openRefAnywhere(a.dataset.openref);
    });
  },

  /* One numbered day, opened as a panel so the passage can be read beside it. */
  async showPlanDay(plan, n) {
    const d = await api('readingplan/day', { plan, day: n });
    if (!d.ok) { toast(d.error || 'No such day.', 'warn'); return; }
    S.plan = plan;
    if ((d.passages || []).length) {
      Reader.openRefAnywhere(d.passages[0]);
    }
    if (d.text) {
      modal(d.title + ' — day ' + d.day,
        '<div class="st-body">' + esc(d.text) + '</div>'
        + (d.passages && d.passages.length
          ? '<div class="tiny"><a href="#" data-openref="'
            + esc(d.passages[0]) + '">' + esc(d.passages.join(' · '))
            + '</a></div>' : ''),
        [{ label: 'Mark as read', fn: async () => {
            await api('readingplan/mark', { plan, day: d.day, done: 1 });
            this.planCard();
          } },
         { label: 'Close', cls: 'btn' }]);
      $$('#modal-body a[data-openref]').forEach(a => a.onclick = (e) => {
        e.preventDefault();
        closeModal();
        Reader.openRefAnywhere(a.dataset.openref);
      });
    }
  },

  /* The whole plan, so its shape is visible rather than discovered one day at a
   * time -- which is what a 638-day plan needs, since the alternative is not
   * knowing whether the thing is 90 days long or 900. */
  async planOverview(plan) {
    const o = await api('readingplan/overview', { plan });
    if (!o.ok) { toast(o.error || 'Could not read the plan.', 'warn'); return; }
    const done = await api('readingplan/plans');
    const marks = new Set((done.progress && done.progress[plan]) || []);
    /* The cells are built as one string rather than by appending, so a
       638-day plan is one innerHTML write instead of 638 of them -- the dialog
       then appears at once instead of filling in. */
    modal('Reading plan — ' + o.total + ' days',
      '<div class="rp-grid">' + o.items.map(it =>
        '<button class="rp-cell' + (marks.has(it.n) ? ' is-done' : '') + '"'
        + ' data-day="' + it.n + '" title="' + esc(it.title) + '">' + it.n
        + '</button>').join('') + '</div>'
      + '<div class="tiny muted">' + esc(o.kind === 'devotional'
        ? 'Days are the devotional\'s own, numbered by position.'
        : 'Canonical order, sized so no book is left to the end.')
      + ' A filled square is a day you have marked read. Press any square to '
      + 'open it.</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const grid = $('#modal-body .rp-grid');
    if (!grid || !grid.children.length) {
      /* Belt and braces: an empty grid with no error is the one failure a
         reader cannot act on, so say something rather than showing a box. */
      toast('The plan opened but listed no days.', 'warn');
      return;
    }
    $$('#modal-body .rp-cell').forEach(b => b.onclick = () => {
      closeModal();
      this.showPlanDay(plan, Number(b.dataset.day));
    });
  },

  async paintHighlights() {
    const box = $('#d-hl');
    if (!box) return;
    // The callback gets the whole highlight row, not a bare id -- passing the
    // row to a function expecting an id found no module and printed the row
    // itself, which rendered as "[object Object]".
    const modName = (row) => {
      const m = modById(row && row.module_id);
      return m ? (m.name || m.title || m.id) : ((row && row.module_id) || '');
    };
    const h = await Highlights.list(modName);
    box.innerHTML = h || '<div class="dash-h">Highlights</div>'
      + '<div class="empty">Select text in a Bible pane, then right-click '
      + '&rarr; <b>Highlight selection</b>. It comes back marked in the text.</div>';
  },

  wire() {
    const root = $('#v-today');
    root.onclick = (e) => {
      const g = e.target.closest('a[data-goto]');
      if (g) { e.preventDefault(); App.show(g.dataset.goto); return; }
      const n = e.target.closest('a[data-note]');
      if (n) { e.preventDefault(); App.show('notes'); Notes.edit(n.dataset.note); return; }
      if (e.target.closest('a[data-newprayer]')) {
        e.preventDefault();
        App.show('notes');
        Notes.edit(Notes.blank('prayer'));
        return;
      }
      const del = e.target.closest('a[data-hid]');
      if (del) { e.preventDefault(); Highlights.remove(del.dataset.hid); return; }
      if (e.target.closest('a#hl-pal')) {
        e.preventDefault(); Highlights.palettesDialog(); return;
      }
      if (e.target.closest('a[data-tagopen]')) {
        e.preventDefault(); Tags.browse(); return;
      }
      const go = e.target.closest('a[data-m]');
      if (go) {
        e.preventDefault();
        const m = modById(go.dataset.m);
        if (m) {
          App.show('workspace');
          Workspace.openModule(m.id, { ref: go.dataset.k });
        }
        return;
      }
      const pane = e.target.closest('a[data-pane]');
      if (pane) {
        e.preventDefault();
        const lay = S.layout;
        const p = lay && lay.panes.find(x => x.id === pane.dataset.pane);
        if (p) { App.show('workspace'); App.showPane(p.tile_id || 't0', p.id); }
        return;
      }
      const o = e.target.closest('a[data-open]');
      if (o) {
        e.preventDefault();
        const mod = modById(o.dataset.open);
        if (mod) { App.show('workspace'); Workspace.openModule(mod.id, {}); }
      }
    };
  },
};

/* =========================================================== Today, moved =
 *
 * The six cards of the Today pane, rearranged.
 *
 * A press held on a card arms it -- the border turns yellow -- and from then on
 * the card follows the pointer until it is dropped between two others, in
 * either column.  A press that moves first, or lands on a link or on the text
 * of a card, is an ordinary press and cancels the hold: the day's reading is
 * there to be read, and rearranging must never cost a verse.
 *
 * The order is kept in localStorage.  It is how one reader likes one screen
 * laid out, and no server round trip has any business in it.
 */
const DashLayout = {
  KEY: 'gbible:dash-layout',
  HOLD: 1000,
  SLOP: 8,

  /* What lives inside a card and must stay usable, so a press on one of these
   * is never a pickup.  Everything else -- the padding, the heading -- is empty
   * space by design, and a hold there is how the card is picked up. */
  NOGRAB: 'button, a, input, textarea, select, label, [contenteditable], '
        + '[data-nodrag], .st-body, .dash-item, .dash-row, .hl-row, .rp-grid, table',

  _st: null,

  /* Two columns of ids, as saved.  A card that exists but was never saved (one
   * added by a newer build) is reported in `rest` and lands at the end. */
  load() {
    const all = $$('#v-today .dash-card').map(c => c.id);
    let o = null;
    try {
      const raw = localStorage.getItem(this.KEY);
      if (raw) o = JSON.parse(raw);
    } catch (e) {}
    const keep = (a) => (Array.isArray(a) ? a : []).filter(x => all.includes(x));
    const left = keep(o && o.left), right = keep(o && o.right);
    return {
      left,
      right,
      rest: all.filter(x => !left.includes(x) && !right.includes(x)),
    };
  },

  read() {
    const cols = $$('#v-today .dash-col');
    if (cols.length < 2) return null;
    const ids = (col) =>
      [...col.children].filter(c => c.classList.contains('dash-card')).map(c => c.id);
    return { left: ids(cols[0]), right: ids(cols[1]) };
  },

  write(o) {
    try { localStorage.setItem(this.KEY, JSON.stringify(o)); } catch (e) {}
  },

  /* Rebuild the two columns in the saved order.  The renderers write into the
   * cards by id and never rebuild the pane itself, so a card keeps whatever
   * place in the DOM it is moved to, whatever its contents do afterwards. */
  apply() {
    if (this._st === 'drag') return;
    this._wire();
    const cols = $$('#v-today .dash-col');
    if (cols.length < 2) return;
    const byId = new Map($$('#v-today .dash-card').map(c => [c.id, c]));
    const o = this.load();
    /* Nothing saved yet: the pane keeps the order it was written in. */
    if (!o.left.length && !o.right.length) return;
    for (const col of cols) col.textContent = '';
    for (const id of o.left) {
      const c = byId.get(id);
      if (c) cols[0].appendChild(c);
    }
    for (const id of o.right) {
      const c = byId.get(id);
      if (c) cols[1].appendChild(c);
    }
    for (const id of o.rest) {
      const c = byId.get(id);
      if (c) cols[0].appendChild(c);
    }
  },

  _wire() {
    if (this._wired) return;
    this._wired = true;
    document.addEventListener('pointerdown', (e) => {
      const t = e.target instanceof Element ? e.target : null;
      if (!t) return;
      const card = t.closest('#v-today .dash-card');
      if (!card) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      if (t.closest(this.NOGRAB)) return;
      this._press(card, e);
    }, true);
    document.addEventListener('pointermove', (e) => this._move(e), true);
    document.addEventListener('pointerup', (e) => this._up(e), true);
    document.addEventListener('pointercancel', () => this._reset(), true);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this._reset();
    }, true);
    /* The native menu is what a long press otherwise raises on every touch
     * platform, so suppressing it is part of what makes a hold holdable. */
    document.addEventListener('contextmenu', (e) => {
      const t = e.target instanceof Element ? e.target : null;
      if (!t || this._st === null || !this._card) return;
      if (this._card.contains(t)) { e.preventDefault(); e.stopPropagation(); }
    }, true);
    /* A selection started during the hold means the press was a selection, not
     * a pickup.  Text comes first. */
    document.addEventListener('selectionchange', () => {
      if (this._st !== 'hold' || !this._card) return;
      const s = window.getSelection && window.getSelection();
      if (s && !s.isCollapsed && this._card.contains(s.anchorNode)) this._reset();
    });
  },

  _press(card, e) {
    this._reset();
    this._st = 'hold';
    this._card = card;
    this._x = e.clientX;
    this._y = e.clientY;
    this._pid = e.pointerId;
    this._timer = setTimeout(() => {
      this._timer = null;
      if (this._st !== 'hold') return;
      this._st = 'armed';
      card.classList.add('armed');
      const s = window.getSelection && window.getSelection();
      if (s) s.removeAllRanges();
      document.body.classList.add('dash-nosel');
    }, this.HOLD);
    /* A finger held still is not a scroll, but a browser cannot know that
     * until it has seen the press stay put, so the gesture is claimed only
     * once the press has clearly become a hold.  A drag that begins at once
     * is a scroll, and cancels the hold before this timer ever runs. */
    if (e.pointerType === 'touch') {
      this._lock = setTimeout(() => {
        this._lock = null;
        if (this._st) card.style.touchAction = 'none';
      }, 220);
    }
  },

  _move(e) {
    if (this._st === null || e.pointerId !== this._pid) return;
    const far = Math.abs(e.clientX - this._x) + Math.abs(e.clientY - this._y)
      > this.SLOP;
    if (this._st === 'hold') {
      if (far) this._reset();
      return;
    }
    if (far && !this._ghost) this._lift(e);
    if (this._ghost) this._place(e);
  },

  /* The card itself stays in the flow and moves to where it would be dropped,
   * so the drop point is never guessed at; a copy follows the pointer, which is
   * what the finger is actually holding. */
  _lift(e) {
    const card = this._card;
    if (!card) return;
    const r = card.getBoundingClientRect();
    const g = card.cloneNode(true);
    g.removeAttribute('id');
    g.className = card.className + ' dash-ghost';
    g.querySelectorAll('[id]').forEach(x => x.removeAttribute('id'));
    g.style.width = r.width + 'px';
    g.style.height = r.height + 'px';
    document.body.appendChild(g);
    this._ghost = g;
    this._off = { x: e.clientX - r.left, y: e.clientY - r.top };
    card.classList.remove('armed');
    card.classList.add('dragging');
    this._st = 'drag';
  },

  _place(e) {
    const g = this._ghost, card = this._card;
    if (!g || !card) return;
    g.style.left = (e.clientX - this._off.x) + 'px';
    g.style.top = (e.clientY - this._off.y) + 'px';
    const col = $$('#v-today .dash-col').find(c => {
      const r = c.getBoundingClientRect();
      return e.clientX >= r.left && e.clientX <= r.right;
    });
    if (!col) return;
    const kids = [...col.children].filter(c => c.classList.contains('dash-card'));
    const after = kids.find(c => {
      if (c === card) return false;
      const r = c.getBoundingClientRect();
      return e.clientY < r.top + r.height / 2;
    });
    if (after) col.insertBefore(card, after);
    else col.appendChild(card);
  },

  _up(e) {
    if (this._st === null || e.pointerId !== this._pid) return;
    const dropped = this._st === 'drag';
    this._reset();
    if (dropped) {
      const o = this.read();
      if (o) this.write(o);
    }
  },

  _reset() {
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    if (this._lock) { clearTimeout(this._lock); this._lock = null; }
    if (this._ghost) { this._ghost.remove(); this._ghost = null; }
    if (this._card) {
      this._card.classList.remove('armed', 'dragging');
      this._card.style.touchAction = '';
      this._card = null;
    }
    document.body.classList.remove('dash-nosel');
    this._st = null;
    this._pid = null;
  },
};

/* ================================================================ Guides */
/* Canon tables, the gospel harmonies, and what a chapter of your library
 * actually holds.  The canon is arithmetic and the harmony is a reference
 * table; the chapter guide is derived from what is installed, and says so. */
/* ============================================================== Organise
 *
 * Favourites, collections, passage lists, charts and saved searches.  These are
 * the parts of a study environment about *arranging* what is installed rather
 * than reading it, so they live together instead of being scattered.
 */
const Organise = {
  tab: 'favourites',
  collections: [],
  lists: [],
  templates: [],

  async load() {
    const tab = $('#o-tab').value;
    this.tab = tab;
    $('#o-chart').style.display = tab === 'charts' ? '' : 'none';
    $('#o-word').style.display = tab === 'charts' ? '' : 'none';
    $('#o-side').innerHTML = '';
    const main = $('#o-main');
    main.innerHTML = '<div class="st-loading">Loading…</div>';
    if (tab === 'favourites') return this.favourites(main);
    if (tab === 'collections') return this.collectionsView(main);
    if (tab === 'lists') return this.listsView(main);
    if (tab === 'notebooks') return this.notebooksView(main);
    if (tab === 'quotations') return Quotations.load(main);
    if (tab === 'canvases') return this.canvasesView(main);
    if (tab === 'charts') return this.chartsView(main);
    return this.templatesView(main);
  },

  async favourites(main) {
    const r = await api('favorites');
    const rows = r.favorites || [];
    main.innerHTML = '<div class="dash-card"><div class="dash-h">'
      + rows.length + ' favourite' + (rows.length === 1 ? '' : 's') + '</div>'
      + (rows.length
        ? rows.map(m => '<div class="dash-row"><a href="#" data-open="'
            + esc(m.id) + '"><b>' + esc(m.name) + '</b></a> '
            + '<span class="muted tiny">' + esc(m.type || '') + ' · '
            + esc(m.lang || '') + '</span></div>').join('')
        : '<div class="empty">Nothing starred yet. Open the Library or Modules '
          + 'and use the ☆ on a row.</div>') + '</div>';
  },

  async collectionsView(main) {
    const r = await api('collection');
    this.collections = r.collections || [];
    let h = '<div class="dash-card"><div class="dash-h">Collections '
      + '<span class="muted">· ' + this.collections.length + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">A named set of '
      + 'resources. Search the whole set at once, or open them side by side.</div>';
    h += '<div class="org-new">'
      + '<input id="o-cname" placeholder="New collection name" style="flex:1">'
      + '<button class="btn primary" id="o-cadd">Create</button></div>';
    if (!this.collections.length) {
      h += '<div class="empty">No collections yet.</div>';
    } else {
      this.collections.forEach(c => {
        const hasRule = !!(c.rule && c.rule.trim());
        h += '<div class="org-card"><div class="org-h"><b>' + esc(c.name) + '</b>'
          + '<span class="muted tiny"> · ' + (c.count || 0) + ' resources'
          + (hasRule ? ' · dynamic' : '') + '</span>'
          + '<span class="org-a">'
          + '<a href="#" data-csearch="' + esc(c.id) + '">search these</a>'
          + '<a href="#" data-copen="' + esc(c.id) + '">open</a>'
          + (hasRule ? '<a href="#" data-crule="' + esc(c.id) + '">edit rule</a>' : '')
          + '<a href="#" data-cdel="' + esc(c.id) + '" class="danger">delete</a>'
          + '</span></div>'
          + '<div class="tiny muted">' + (c.modules || []).map(x =>
              esc(x.name || x.module_id)).join(' · ') + '</div></div>';
      });
    }
    main.innerHTML = h + '</div>';
    /* Wire rule editor buttons. */
    main.querySelectorAll('a[data-crule]').forEach(a => {
      a.onclick = (e) => { e.preventDefault(); this.editCollectionRule(a.dataset.crule); };
    });
  },

  async listsView(main) {
    const r = await api('passagelist');
    this.lists = r.lists || [];
    let h = '<div class="dash-card"><div class="dash-h">Passage lists '
      + '<span class="muted">· ' + this.lists.length + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">References kept '
      + 'together to read side by side. Right-click a verse and choose '
      + '<b>Add to passage list</b>.</div>'
      + '<div class="org-new"><input id="o-lname" placeholder="New list name"'
      + ' style="flex:1"><button class="btn primary" id="o-ladd">Create</button></div>';
    if (!this.lists.length) h += '<div class="empty">No lists yet.</div>';
    for (const l of this.lists) {
      const d = await api('passagelist', { id: l.id });
      const items = d.items || [];
      h += '<div class="org-card"><div class="org-h"><b>' + esc(l.name) + '</b>'
        + '<span class="muted tiny"> · ' + items.length + '</span>'
        + '<span class="org-a"><a href="#" data-lopen="' + esc(l.id) + '">open</a>'
        + '<a href="#" data-lread="' + esc(l.id) + '"'
        + ' title="Read exactly these, in this order, in one pane">read</a>'
        + '<a href="#" data-lflash="' + esc(l.id) + '">flashcards</a>'
        + '<a href="#" data-ldel="' + esc(l.id) + '" class="danger">delete</a>'
        + '</span></div>';
      if (!items.length) { h += '<div class="tiny muted">empty</div>'; continue; }
      h += '<div class="org-items">' + items.map(i =>
        '<span class="org-item"><a href="#" data-ref="' + esc(i.ref_label || i.unit_key)
        + '">' + esc(i.ref_label || i.unit_key) + '</a>'
        + '<a href="#" class="x" data-lmove="' + esc(i.id) + '" data-d="-1">↑</a>'
        + '<a href="#" class="x" data-lmove="' + esc(i.id) + '" data-d="1">↓</a>'
        + '<a href="#" class="x danger" data-lrm="' + esc(i.id) + '">×</a>'
        + '</span>').join('') + '</div>';
      h += '</div>';
    }
    main.innerHTML = h + '</div>';
  },

  /* Edit a collection's dynamic rule.  A rule like `type:commentary lang:eng`
   * auto-matches installed modules; plus/minus lists add or remove specific
   * modules regardless of the rule. */
  async editCollectionRule(id) {
    const c = this.collections.find(x => x.id === id);
    if (!c) return;
    const cur = await api('collection', { id });
    const rule = cur.rule || '';
    const plus = (cur.plus || []).map(m => m.module_id || m).join(', ');
    const minus = (cur.minus || []).map(m => m.module_id || m).join(', ');
    modal('Edit collection rule — ' + esc(c.name),
      '<div class="tiny muted" style="margin-bottom:8px">Match modules by field, '
      + 'e.g. <code>type:commentary lang:eng</code>. Bare words match name, '
      + 'author or type. Use ANDNOT to exclude. Plus/minus add or remove '
      + 'specific modules by id.</div>'
      + '<div class="row wrap" style="margin-bottom:8px">'
      + '<label style="width:90px">Rule</label>'
      + '<input id="crule-rule" style="flex:1" value="' + esc(rule) + '">'
      + '</div>'
      + '<div class="row wrap" style="margin-bottom:8px">'
      + '<label style="width:90px">Always include</label>'
      + '<input id="crule-plus" placeholder="module ids, comma-separated" '
      + 'value="' + esc(plus) + '">'
      + '</div>'
      + '<div class="row wrap" style="margin-bottom:8px">'
      + '<label style="width:90px">Always exclude</label>'
      + '<input id="crule-minus" placeholder="module ids, comma-separated" '
      + 'value="' + esc(minus) + '">'
      + '</div>'
      + '<div class="tiny muted">Saving applies the rule live — new installs '
      + 'that match will appear automatically.</div>',
      [{ label: 'Cancel', cls: 'btn' },
       { label: 'Save rule', cls: 'btn primary', close: false, fn: async () => {
         const rule = $('#crule-rule').value.trim();
         const plus = $('#crule-plus').value.split(',').map(s => s.trim()).filter(Boolean);
         const minus = $('#crule-minus').value.split(',').map(s => s.trim()).filter(Boolean);
         const r = await post('collection', {
           action: 'rule', id, rule, plus: JSON.stringify(plus), minus: JSON.stringify(minus) });
         if (!r.ok) { toast(r.error || 'Could not save rule.', 'err'); return; }
         closeModal();
         toast('Rule saved — ' + (r.members || []).length + ' matching resources.');
         this.load();
       } }]);
  },

  /* A notebook is a saved filter over your notes, not a folder of copies:
   * kind, tag and a word to find have to all match.  Changing the filter
   * changes what the notebook holds without moving a single note. */
  async notebooksView(main) {
    const r = await api('notebook');
    const rows = r.notebooks || [];
    let h = '<div class="dash-card"><div class="dash-h">Notebooks '
      + '<span class="muted">· ' + rows.length + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">A named way of '
      + 'gathering notes. The filter is kept, not the notes, so it keeps '
      + 'working as you write more.</div>';
    h += '<div class="org-new"><input id="nb-name" placeholder="Notebook name"'
      + ' style="flex:1"><select id="nb-kind">'
      + '<option value="">Any kind</option><option value="note">Notes</option>'
      + '<option value="journal">Journal</option><option value="sermon">Sermon</option>'
      + '<option value="prayer">Prayer</option></select>'
      + '<input id="nb-tag" placeholder="tag (optional)" style="width:110px">'
      + '<input id="nb-query" placeholder="find (optional)" style="width:130px">'
      + '<button class="btn primary" id="nb-add">Create</button></div>';
    if (!rows.length) h += '<div class="empty">No notebooks yet.</div>';
    for (const n of rows) {
      const d = await api('notebook', { id: n.id });
      const notes = d.notes || [];
      h += '<div class="org-card"><div class="org-h"><b>' + esc(n.name) + '</b>'
        + '<span class="muted tiny"> · ' + notes.length + ' note'
        + (notes.length === 1 ? '' : 's') + '</span>'
        + '<span class="org-a">'
        + '<a href="#" data-nbopen="' + esc(n.id) + '">show</a>'
        + '<a href="#" data-nbdel="' + esc(n.id) + '" class="danger">delete</a>'
        + '</span></div>'
        + '<div class="tiny muted">'
        + [n.kind ? 'kind: ' + esc(n.kind) : '',
           n.tag ? 'tag: ' + esc(n.tag) : '',
           n.query ? 'find: “' + esc(n.query) + '”' : ''].filter(Boolean).join(' · ')
        + (n.kind || n.tag || n.query ? '' : ' (everything)')
        + '</div>';
      if (notes.length) {
        h += '<div class="org-items">' + notes.map(nt =>
          '<span class="org-item"><a href="#" data-nbnote="' + esc(nt.id) + '">'
          + esc(nt.title || '(untitled)') + '</a></span>').join('') + '</div>';
      }
      h += '</div>';
    }
    main.innerHTML = h + '</div>';
    $('#nb-add').onclick = async () => {
      const name = $('#nb-name').value.trim();
      if (!name) { toast('Give the notebook a name.', 'warn'); return; }
      await post('notebook', { action: 'save', name,
        kind: $('#nb-kind').value, tag: $('#nb-tag').value.trim(),
        query: $('#nb-query').value.trim() });
      this.notebooksView(main);
    };
    main.querySelectorAll('a[data-nbdel]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      await post('notebook', { action: 'delete', id: a.dataset.nbdel });
      this.notebooksView(main);
    });
    main.querySelectorAll('a[data-nbnote]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      App.show('notes');
      Notes.edit(a.dataset.nbnote);
    });
  },

  async canvasesView(main) {
    /* A canvas is boxes of your own words and verses, arranged by hand. The
     * board is plain positioned divs — no drawing library, nothing to
     * license. Element kinds the renderer knows: heading, text, verse.
     * Anything else is kept in the save and listed, never drawn. */
    const r = await api('canvas', {}).catch(() => ({ canvases: [] }));
    const all = r.canvases || [];
    let h = '<div class="dash-card"><div class="dash-h">Canvases '
      + '<span class="muted">· ' + all.length + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">Arrange your own '
      + 'notes and verses on a board. Nothing here is generated.</div>'
      + '<div class="org-new"><input id="o-vname" placeholder="New canvas name"'
      + ' style="flex:1"><button class="btn primary" id="o-vadd">Create</button></div>';
    all.forEach(c => {
      h += '<div class="org-card"><div class="org-h"><b>' + esc(c.name) + '</b>'
        + '<span class="muted tiny"> · ' + ((c.elements || []).length) + ' elements</span>'
        + '<span class="org-a"><a href="#" data-vopen="' + esc(c.id) + '">open</a>'
        + '<a href="#" data-vdel="' + esc(c.id) + '" class="danger">delete</a></span></div></div>';
    });
    main.innerHTML = h + '</div><div id="o-vboard"></div>';
    $('#o-vadd').onclick = async () => {
      const name = $('#o-vname').value.trim() || 'Untitled canvas';
      const s = await post('canvas', { action: 'save', name });
      if (s.canvas) this.editCanvas(s.canvas.id);
      else this.canvasesView(main);
    };
    main.querySelectorAll('a[data-vdel]').forEach(a => a.onclick = async (e) => {
      e.preventDefault();
      await post('canvas', { action: 'delete', id: a.dataset.vdel });
      this.canvasesView(main);
    });
    main.querySelectorAll('a[data-vopen]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      this.editCanvas(a.dataset.vopen);
    });
  },

  async editCanvas(id) {
    const r = await api('canvas', {}).catch(() => ({ canvases: [] }));
    const c = (r.canvases || []).find(x => x.id === id);
    if (!c) { toast('Canvas not found.', 'warn'); return; }
    const host = $('#o-vboard');
    host.innerHTML = '<div class="dash-card"><div class="dash-h">' + esc(c.name)
      + ' <span class="muted tiny" id="o-vmsg"></span></div>'
      + '<div class="row wrap"><button class="btn" id="o-vt">+ Text</button>'
      + '<button class="btn" id="o-vh">+ Heading</button>'
      + '<input id="o-vref" placeholder="verse ref, e.g. Jn 3:16" style="width:150px">'
      + '<button class="btn" id="o-vv">+ Verse</button>'
      + '<span class="tiny muted">link:</span>'
      + '<select id="o-va" style="max-width:110px"></select>'
      + '<select id="o-vb" style="max-width:110px"></select>'
      + '<button class="btn" id="o-varr" title="Draw a connector between two boxes">+ Arrow</button>'
      + '<button class="btn primary" id="o-vsave">Save</button></div>'
      + '<div id="o-vcv" style="position:relative;min-height:420px;border:1px solid var(--line);'
      + 'border-radius:8px;margin-top:8px;overflow:auto;background:var(--bg-1)"></div>'
      + '<div class="tiny muted">Drag boxes by their header. Double-click text to edit. '
      + 'Unknown element kinds are kept in the save and listed below, never drawn.</div>'
      + '<div id="o-varrows" style="margin-top:4px"></div>'
      + '<div id="o-vunknown" class="tiny muted"></div></div>';
    const board = $('#o-vcv');
    let els = (c.elements || []).map(e => Object.assign({}, e));
    const draw = () => {
      board.innerHTML = '';
      const unknown = [];
      const boxes = els.filter(e => ['heading', 'text', 'verse'].includes(e.kind));
      /* Connectors first, so boxes paint over the line ends. Positions are
       * box centres from the stored geometry — no measuring needed. */
      const arrows = els.filter(e => e.kind === 'arrow' && e.from && e.to);
      if (arrows.length) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
        const ctr = (id) => {
          const b = boxes.find(x => x.id === id);
          if (!b) return null;
          return { x: (b.x || 20) + (b.w || 220) / 2, y: (b.y || 20) + 24 };
        };
        arrows.forEach(a => {
          const A = ctr(a.from), B = ctr(a.to);
          if (!A || !B) return;
          const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          ln.setAttribute('x1', A.x); ln.setAttribute('y1', A.y);
          ln.setAttribute('x2', B.x); ln.setAttribute('y2', B.y);
          ln.setAttribute('stroke', 'var(--fg-3)');
          ln.setAttribute('stroke-width', '1.5');
          ln.setAttribute('marker-end', 'url(#vh)');
          svg.appendChild(ln);
        });
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = '<marker id="vh" markerWidth="8" markerHeight="8" '
          + 'refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" '
          + 'fill="none" stroke="var(--fg-3)" stroke-width="1.5"/></marker>';
        svg.appendChild(defs);
        board.appendChild(svg);
      }
      const fillArrowLists = () => {
        const opts = boxes.map(b => '<option value="' + esc(b.id) + '">'
          + esc((b.text || b.kind).slice(0, 24)) + '</option>').join('');
        $('#o-va').innerHTML = opts; $('#o-vb').innerHTML = opts;
      };
      fillArrowLists();
      els.forEach(e => {
        if (e.kind === 'arrow') return;
        if (['heading', 'text', 'verse'].indexOf(e.kind) < 0) { unknown.push(e); return; }
        const d = document.createElement('div');
        d.style.cssText = 'position:absolute;left:' + (e.x || 20) + 'px;top:' + (e.y || 20)
          + 'px;width:' + (e.w || 220) + 'px;border:1px solid var(--line);border-radius:6px;'
          + 'background:var(--bg-0);padding:0;';
        const hd = document.createElement('div');
        hd.style.cssText = 'cursor:move;padding:2px 6px;font-size:11px;color:var(--fg-3);'
          + 'border-bottom:1px solid var(--line);display:flex;justify-content:space-between';
        hd.innerHTML = '<span>' + esc(e.kind) + '</span><span data-x style="cursor:pointer">✕</span>';
        const bd = document.createElement('div');
        bd.style.cssText = 'padding:6px;white-space:pre-wrap;'
          + (e.kind === 'heading' ? 'font-weight:bold;font-size:1.1em' : '');
        bd.textContent = e.text || '';
        if (e.kind === 'verse' && e.ref) {
          const a = document.createElement('a');
          a.href = '#'; a.textContent = ' — ' + e.ref;
          a.onclick = (ev) => {
            ev.preventDefault();
            const bibles = (S.modules || []).filter(m => m.is_bible);
            const mid = e.module_id || (bibles[0] && bibles[0].id) || '';
            if (mid) { App.show('workspace'); Workspace.openModule(mid, { ref: e.ref, span: 'chapter' }); }
          };
          bd.appendChild(a);
        }
        const ta = document.createElement('textarea');
        ta.value = e.text || '';
        ta.style.cssText = 'width:100%;box-sizing:border-box;display:none';
        ta.oninput = () => { e.text = ta.value; };
        bd.ondblclick = () => { bd.style.display = 'none'; ta.style.display = ''; ta.focus(); };
        ta.onblur = () => { ta.style.display = 'none'; bd.style.display = ''; draw(); };
        d.appendChild(hd); d.appendChild(bd); d.appendChild(ta);
        hd.querySelector('[data-x]').onclick = () => {
          els = els.filter(x => x !== e); draw();
        };
        hd.onpointerdown = (ev) => {
          if (ev.target.hasAttribute('data-x')) return;
          const sx = ev.clientX - (e.x || 0), sy = ev.clientY - (e.y || 0);
          const mv = (me) => { e.x = me.clientX - sx; e.y = me.clientY - sy;
            d.style.left = e.x + 'px'; d.style.top = e.y + 'px'; };
          const up = () => {
            window.removeEventListener('pointermove', mv);
            window.removeEventListener('pointerup', up);
          };
          window.addEventListener('pointermove', mv);
          window.addEventListener('pointerup', up);
        };
        board.appendChild(d);
      });
      $('#o-vunknown').textContent = unknown.length
        ? unknown.length + ' unsupported element(s) kept but not drawn.' : '';
      const arrHost = $('#o-varrows');
      if (arrHost) {
        arrHost.innerHTML = arrows.map(a => {
          const nm = (id) => {
            const b = boxes.find(x => x.id === id);
            return esc(((b && (b.text || b.kind)) || id).slice(0, 24));
          };
          return '<span class="chip">' + nm(a.from) + ' → ' + nm(a.to)
            + ' <a href="#" data-arr="' + esc(a.id) + '">✕</a></span> ';
        }).join('');
        arrHost.querySelectorAll('a[data-arr]').forEach(x => x.onclick = (ev) => {
          ev.preventDefault();
          els = els.filter(y => y.id !== x.dataset.arr);
          draw();
        });
      }
    };
    const place = () => {
      const n = els.length;
      return { x: 20 + (n % 4) * 40, y: 20 + (n % 4) * 40, w: 220 };
    };
    $('#o-vt').onclick = () => { els.push(Object.assign({ id: 'e' + Date.now(), kind: 'text', text: 'New note' }, place())); draw(); };
    $('#o-vh').onclick = () => { els.push(Object.assign({ id: 'e' + Date.now(), kind: 'heading', text: 'Heading' }, place())); draw(); };
    $('#o-vv').onclick = async () => {
      const ref = $('#o-vref').value.trim();
      if (!ref) { toast('Type a reference first.', 'warn'); return; }
      const bibles = (S.modules || []).filter(m => m.is_bible);
      const mid = (bibles[0] && bibles[0].id) || '';
      let text = ref;
      if (mid) {
        const rd = await api('read', { id: mid, cursor: { ref, span: 'verse' } }).catch(() => null);
        if (rd && rd.items && rd.items[0]) text = rd.items[0].text || ref;
      }
      els.push(Object.assign({ id: 'e' + Date.now(), kind: 'verse', ref, text, module_id: mid }, place()));
      $('#o-vref').value = '';
      draw();
    };
    $('#o-vsave').onclick = async () => {
      $('#o-vmsg').textContent = 'Saving…';
      const s = await post('canvas', { action: 'save', id, name: c.name, elements: els });
      $('#o-vmsg').textContent = (s && s.canvas) ? 'Saved.' : 'Save failed.';
    };
    $('#o-varr').onclick = () => {
      const a = $('#o-va').value, b = $('#o-vb').value;
      if (!a || !b || a === b) { toast('Pick two different boxes.', 'warn'); return; }
      els.push({ id: 'e' + Date.now(), kind: 'arrow', from: a, to: b });
      draw();
    };
    draw();
  },

  async chartsView(main) {
    const kind = $('#o-chart').value;
    const arg = kind === 'word' ? ($('#o-word').value || '').trim() : '';
    if (kind === 'word' && !arg) {
      main.innerHTML = '<div class="dash-card"><div class="empty">Type a '
        + "Strong's number, e.g. G2316.</div></div>";
      return;
    }
    const c = await api('charts', { kind: kind, arg: arg });
    if (!c.ok) {
      main.innerHTML = '<div class="dash-card"><div class="empty">'
        + esc(c.error || 'no chart') + '</div></div>';
      return;
    }
    /* Bars as inline SVG: no chart library, no network, and the whole thing
     * scales from a phone to a wide window. */
    const rows = c.series.slice(0, 40);
    const max = c.max || 1;
    /* Labels are truncated and the bar is capped short of the right edge, so a
     * long name and a big number cannot end up printed on top of each other. */
    const rowH = 21, w = 760, labelW = 300, valW = 74;
    const clip = (t, n) => (t || '').length > n ? (t || '').slice(0, n - 1) + '\u2026'
                                                 : (t || '');
    let bars = '';
    rows.forEach((s, i) => {
      const bw = Math.max(1, Math.round((s.value / max) * (w - labelW - valW)));
      const y = i * rowH;
      const title = esc(s.label);
      bars += '<text x="0" y="' + (y + 14) + '" class="ch-l"><title>' + title
        + '</title>' + esc(clip(s.label, 40)) + '</text>'
        + '<rect x="' + labelW + '" y="' + (y + 4) + '" width="' + bw
        + '" height="13" rx="2" class="ch-b"><title>' + title + '</title></rect>'
        + '<text x="' + (w - 4) + '" y="' + (y + 14)
        + '" class="ch-v" text-anchor="end">' + (s.value || 0).toLocaleString()
        + '</text>';
    });
    main.innerHTML = '<div class="dash-card"><div class="dash-h">'
      + esc(c.title) + '</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">' + c.bars
      + ' bars · total ' + (c.total || 0).toLocaleString()
      + (c.bars > rows.length ? ' · showing the first ' + rows.length : '')
      + '</div>'
      + '<svg class="chart" viewBox="0 0 ' + w + ' ' + (rows.length * rowH + 6)
      + '" preserveAspectRatio="xMinYMin meet" width="100%" height="'
      + (rows.length * rowH + 6) + '">' + bars + '</svg>'
      + '</div>';
  },

  /* ------------------------------------------------------------- Sermon Starter */
  async sermonStarterView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Sermon Starter Guide</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Get sermon ideas, '
      + 'outlines, illustrations and related verses for any passage or topic.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="ss-q" placeholder="Passage or topic, e.g. John 3:16 or faith" style="flex:1">'
      + '<button class="btn primary" id="ss-go">Get Ideas</button></div>'
      + '<div id="ss-out"></div>';
    main.innerHTML = h;
    const go = async () => {
      const q = $('#ss-q').value.trim();
      if (!q) { toast('Type a passage or topic.', 'warn'); return; }
      const r = await api('sermon-starter', { q, limit: 10 });
      if (!r.ok) { $('#ss-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      let out = '<div class="tiny muted">' + r.starters.length + ' starter' + (r.starters.length === 1 ? '' : 's') + '</div>';
      out += r.starters.map(s => '<div class="org-card"><div class="org-h"><b>'
        + esc(s.title) + '</b><span class="muted tiny"> · ' + esc(s.theme) + '</span></div>'
        + '<div class="st-sec"><div class="st-h">Key Verses</div>'
        + (s.key_verses || []).map(v => '<div class="st-note"><a href="#" data-ref="'
        + esc(v.ref) + '" class="pg-ref">' + esc(v.ref) + '</a> ' + esc((v.text || "").slice(0, 200)) + '</div>').join('')
        + '</div>'
        + '<div class="st-sec"><div class="st-h">Main Points</div>'
        + (s.main_points || []).map(p => '<div class="st-note"><div class="st-body">' + esc(p) + '</div></div>').join('')
        + '</div>'
        + '<div class="st-sec"><div class="st-h">Illustrations</div>'
        + (s.illustrations || []).map(i => '<div class="st-note"><div class="st-body">' + esc(i) + '</div></div>').join('')
        + '</div>'
        + '<div class="st-sec"><div class="st-h">Commentaries</div>'
        + (s.commentaries || []).map(c => '<div class="st-note"><div class="st-src">' + esc(c.module || '') + '</div><div class="st-t">' + esc(c.title || '') + '</div><div class="st-body">' + esc((c.text || "").slice(0, 300)) + '</div></div>').join('')
        + '</div>'
        + '<div class="st-sec"><div class="st-h">Cross-References</div>'
        + '<div class="st-body">' + (s.cross_references || []).map(x => '<a href="#" data-ref="' + esc(x.ref) + '" class="pg-ref">' + esc(x.label || x.ref) + '</a>').join(' · ') + '</div></div></div>').join('');
      $('#ss-out').innerHTML = out;
      $('#ss-out').querySelectorAll('.pg-ref').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); const ref = a.dataset.ref; App.show('workspace'); const pane = (S.layout && S.layout.panes && S.layout.panes[0]); if (pane) Reader.go(pane, ref); };
      });
    };
    $('#ss-go').onclick = go;
    $('#ss-q').onkeydown = (e) => { if (e.key === 'Enter') go(); };
  },

  /* ------------------------------------------------------------- Q&A */
  async qaView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Questions &amp; Answers</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Ask about Bible passages '
      + 'and topics. Answers come from your installed commentaries, dictionaries '
      + 'and fact books.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="qa-q" placeholder="Question, e.g. What does baptism mean?" style="flex:1">'
      + '<button class="btn primary" id="qa-go">Ask</button></div>'
      + '<div id="qa-out"></div>';
    main.innerHTML = h;
    const go = async () => {
      const q = $('#qa-q').value.trim();
      if (!q) { toast('Type a question.', 'warn'); return; }
      const r = await api('qa', { q, limit: 20 });
      if (!r.ok) { $('#qa-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      let out = '<div class="tiny muted">' + r.count + ' answer' + (r.count === 1 ? '' : 's') + '</div>';
      out += r.questions.map(qq => '<div class="org-card"><div class="org-h"><b>'
        + esc(qq.title || qq.question) + '</b></div>'
        + '<div class="st-sec"><div class="st-h">Answer</div>'
        + '<div class="st-body">' + esc(qq.answer || "") + '</div></div>'
        + '<div class="tiny muted">' + esc(qq.module || '') + ' · ' + esc(qq.key || '') + '</div></div>').join('');
      $('#qa-out').innerHTML = out;
    };
    $('#qa-go').onclick = go;
    $('#qa-q').onkeydown = (e) => { if (e.key === 'Enter') go(); };
  },

  /* ------------------------------------------------------------- Sense Lexicon */
  async senseLexiconView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Bible Sense Lexicon</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Word sense '
      + 'disambiguation — which sense of a word is used in each passage.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="sl-q" placeholder="Word or Strong\'s number, e.g. love or G26" style="flex:1">'
      + '<button class="btn primary" id="sl-go">Look Up</button></div>'
      + '<div id="sl-out"></div>';
    main.innerHTML = h;
    const go = async () => {
      const q = $('#sl-q').value.trim();
      if (!q) { toast('Type a word or Strong\'s number.', 'warn'); return; }
      const r = await api('sense-lexicon', { q, limit: 10 });
      if (!r.ok) { $('#sl-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      let out = '<div class="st-ref">' + esc(r.word) + ' (Strong\'s ' + esc(r.num) + ')</div>';
      out += '<div class="tiny muted">' + esc(r.headword || '') + ' · ' + esc(r.lemma || '') + '</div>';
      out += '<div class="st-sec"><div class="st-h">Senses</div>'
        + (r.senses || []).map(s => '<div class="st-note"><div class="st-body"><b>'
        + esc(s.sense || '') + '</b><br>' + esc(s.definition || "") + '</div></div>').join('')
        + '</div>';
      out += '<div class="st-sec"><div class="st-h">Example Uses</div>'
        + (r.examples || []).map(e => '<div class="st-note"><a href="#" data-ref="'
        + esc(e.ref) + '" class="pg-ref">' + esc(e.ref) + '</a> <span class="tiny muted">' + esc(e.surface || "") + '</span></div>').join('')
        + '</div>';
      $('#sl-out').innerHTML = out;
      $('#sl-out').querySelectorAll('.pg-ref').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); const ref = a.dataset.ref; App.show('workspace'); const pane = (S.layout && S.layout.panes && S.layout.panes[0]); if (pane) Reader.go(pane, ref); };
      });
    };
    $('#sl-go').onclick = go;
    $('#sl-q').onkeydown = (e) => { if (e.key === 'Enter') go(); };
  },

  /* ------------------------------------------------------------- Community Tags */
  async communityTagsView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Community Tags</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">User-sourced tags for '
      + 'verses, words and topics. Tags are shared across all users.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="ct-q" placeholder="Tag, module, or reference to filter" style="flex:1">'
      + '<button class="btn primary" id="ct-go">Filter</button>'
      + '<button class="btn" id="ct-export">Export Tags</button>'
      + '<input id="ct-import-file" type="file" style="display:none">'
      + '<button class="btn" id="ct-import">Import Tags</button></div>'
      + '<div id="ct-out"></div>';
    main.innerHTML = h;
    const load = async () => {
      const q = $('#ct-q').value.trim();
      const r = await api('community-tags', { action: 'list' });
      if (!r.ok) { $('#ct-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      let tags = r.tags || [];
      if (q) tags = tags.filter(t => t.tag.toLowerCase().includes(q.toLowerCase()) || (t.ref || "").toLowerCase().includes(q.toLowerCase()));
      $('#ct-out').innerHTML = '<div class="tiny muted">' + tags.length + ' tag' + (tags.length === 1 ? '' : 's') + '</div>'
        + tags.map(t => '<div class="org-card"><div class="org-h"><span class="chip">'
        + esc(t.tag) + '</span> <span class="muted tiny">' + esc(t.module_id || '') + ' · ' + esc(t.ref || '') + '</span></div>'
        + '<div class="st-body">' + esc(t.count) + ' occurrence' + (t.count === 1 ? '' : 's') + '</div></div>').join('');
    };
    $('#ct-go').onclick = load;
    $('#ct-q').onkeydown = (e) => { if (e.key === 'Enter') load(); };
    $('#ct-export').onclick = async () => {
      const r = await api('community-tags', { action: 'list' });
      if (!r.ok) { toast(r.error || 'Export failed.', 'err'); return; }
      const data = JSON.stringify({ tags: r.tags || [], exported: new Date().toISOString() }, null, 2);
      const blob = new Blob([data], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'community-tags-' + new Date().toISOString().slice(0, 10) + '.json';
      a.click();
      URL.revokeObjectURL(url);
      toast('Tags exported.');
    };
    $('#ct-import').onclick = () => { $('#ct-import-file').click(); };
    $('#ct-import-file').onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const text = await file.text();
      let parsed;
      try { parsed = JSON.parse(text); } catch (err) { toast('Invalid JSON file.', 'err'); return; }
      const tags = parsed.tags || [];
      if (!tags.length) { toast('No tags in file.', 'warn'); return; }
      let added = 0;
      for (const t of tags) {
        const rr = await api('community-tags', {
          action: 'add', tag: t.tag, module_id: t.module_id || '', ref: t.ref || ''
        });
        if (rr.ok) added++;
      }
      toast('Imported ' + added + ' tag' + (added === 1 ? '' : 's') + '.');
      load();
    };
    load();
  },

  /* ------------------------------------------------------------- Personal Books */
  async personalBooksView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Personal Books</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Import your own books '
      + '(PDF, EPUB, plain text) as personal modules.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="pb-path" placeholder="/path/to/book.epub or /path/to/book.txt" style="flex:1">'
      + '<button class="btn primary" id="pb-import">Import</button></div>'
      + '<div id="pb-out"></div>';
    main.innerHTML = h;
    const load = async () => {
      const r = await api('personal-books', { action: 'list' });
      if (!r.ok) { $('#pb-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      $('#pb-out').innerHTML = (r.books || []).map(b => '<div class="org-card"><div class="org-h"><b>'
        + esc(b.title) + '</b><span class="muted tiny"> · ' + esc(b.format) + ' · ' + b.unit_count + ' units</span>'
        + '<span class="org-a"><button class="btn tiny" data-pbdel="' + esc(b.id) + '">delete</button></span></div></div>').join('');
      $('#pb-out').querySelectorAll('[data-pbdel]').forEach(b => {
        b.onclick = async () => {
          await api('personal-books', { action: 'delete', book_id: b.dataset.pbdel });
          load();
        };
      });
    };
    $('#pb-import').onclick = async () => {
      const path = $('#pb-path').value.trim();
      if (!path) { toast('Type a file path.', 'warn'); return; }
      const r = await api('personal-books', { action: 'import', path });
      if (!r.ok) { toast(r.error || 'Import failed.', 'err'); return; }
      toast('Imported "' + r.title + '" (' + r.unit_count + ' units).');
      $('#pb-path').value = '';
      load();
    };
    load();
  },

  /* ------------------------------------------------------------- Courses */
  async coursesView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Courses</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Video and audio courses '
      + 'for Bible study. Track your progress through lessons.</div>'
      + '<div id="courses-out"></div>';
    main.innerHTML = h;
    const load = async () => {
      const r = await api('courses', { action: 'list' });
      if (!r.ok) { $('#courses-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      $('#courses-out').innerHTML = (r.courses || []).map(c => '<div class="org-card"><div class="org-h"><b>'
        + esc(c.title) + '</b><span class="muted tiny"> · ' + (c.lesson_count || 0) + ' lessons</span>'
        + '<span class="org-a"><a href="#" data-course-open="' + esc(c.id) + '">open</a></span></div>'
        + '<div class="tiny muted">' + esc(c.description || "") + '</div></div>').join('');
      $('#courses-out').querySelectorAll('[data-course-open]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); openCourse(a.dataset.courseOpen); };
      });
    };
    const openCourse = async (id) => {
      const r = await api('courses', { action: 'open', course_id: id });
      if (!r.ok) { toast(r.error || 'Could not open course.', 'err'); return; }
      const c = r.course;
      let out = '<div class="st-ref">' + esc(c.title) + '</div>';
      if (c.author) out += '<div class="tiny muted">by ' + esc(c.author) + '</div>';
      if (c.description) out += '<div class="st-body">' + esc(c.description) + '</div>';
      out += '<div class="st-sec"><div class="st-h">Lessons</div>'
        + (r.lessons || []).map(l => {
          const done = r.progress && r.progress[l.id] ? ' ✓' : '';
          return '<div class="st-note"><a href="#" data-lesson="' + esc(l.id) + '" class="pg-ref">' + esc(l.title) + '</a>' + esc(done) + '</div>';
        }).join('') + '</div>';
      main.innerHTML = out;
      main.querySelectorAll('[data-lesson]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); openLesson(a.dataset.lesson); };
      });
    };
    const openLesson = async (id) => {
      const r = await api('courses', { action: 'lesson', lesson_id: id });
      if (!r.ok) { toast(r.error || 'Could not open lesson.', 'err'); return; }
      const l = r.lesson;
      main.innerHTML = '<div class="st-ref">' + esc(l.title) + '</div>'
        + (l.content ? '<div class="st-body">' + esc(l.content) + '</div>' : '')
        + (l.video_url ? '<div class="st-sec"><div class="st-h">Video</div>'
        + '<video controls style="width:100%;max-width:640px" src="' + esc(l.video_url) + '"></video></div>' : '')
        + (l.audio_url ? '<div class="st-sec"><div class="st-h">Audio</div>'
        + '<audio controls src="' + esc(l.audio_url) + '"></audio></div>' : '')
        + '<div class="row wrap" style="margin-top:10px">'
        + '<button class="btn" id="course-complete" data-lesson="' + esc(id) + '">Mark Complete</button>'
        + '</div>';
      $('#course-complete').onclick = async () => {
        await api('courses', { action: 'progress', course_id: main.dataset.courseId, lesson_id: id, completed: '1' });
        toast('Lesson marked complete.');
        load();
      };
      main.dataset.courseId = main.dataset.courseId || "";
    };
    load();
  },

  /* ------------------------------------------------------------- Draw on Screen */
  async drawOnScreenView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Draw on Screen</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Create drawing annotations '
      + 'over Bible text. Save, load and delete drawings.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="dw-title" placeholder="Drawing title" style="flex:1">'
      + '<button class="btn primary" id="dw-save">Save Drawing</button></div>'
      + '<div id="dw-out"></div>';
    main.innerHTML = h;
    const load = async () => {
      const r = await api('draw-on-screen', { action: 'list' });
      if (!r.ok) { $('#dw-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      $('#dw-out').innerHTML = '<div class="tiny muted">' + (r.drawings || []).length + ' drawing' + ((r.drawings || []).length === 1 ? '' : 's') + '</div>'
        + (r.drawings || []).map(d => '<div class="org-card"><div class="org-h"><b>'
        + esc(d.title) + '</b><span class="muted tiny"> · ' + new Date(d.updated_at * 1000).toLocaleString() + '</span>'
        + '<span class="org-a"><button class="btn tiny" data-dwload="' + esc(d.id) + '">load</button><button class="btn tiny danger" data-dwdel="' + esc(d.id) + '">delete</button></span></div></div>').join('');
      $('#dw-out').querySelectorAll('[data-dwdel]').forEach(b => {
        b.onclick = async () => {
          await api('draw-on-screen', { action: 'delete', drawing_id: b.dataset.dwdel });
          load();
        };
      });
      $('#dw-out').querySelectorAll('[data-dwload]').forEach(b => {
        b.onclick = async () => {
          const r = await api('draw-on-screen', { action: 'load', drawing_id: b.dataset.dwload });
          if (!r.ok) { toast(r.error || 'Could not load drawing.', 'err'); return; }
          $('#dw-drawing-data').value = r.drawing.data || "";
          toast('Drawing loaded. Use the drawing canvas to view/edit.');
        };
      });
    };
    $('#dw-save').onclick = async () => {
      const title = $('#dw-title').value.trim();
      const data = $('#dw-drawing-data').value.trim();
      if (!title || !data) { toast('Enter a title and drawing data.', 'warn'); return; }
      const r = await api('draw-on-screen', { action: 'save', drawing_id: '', data });
      if (!r.ok) { toast(r.error || 'Save failed.', 'err'); return; }
      toast('Drawing saved.');
      $('#dw-title').value = '';
      load();
    };
    // Hidden textarea for drawing data (in a real app this would be a canvas)
    h += '<textarea id="dw-drawing-data" style="display:none"></textarea>';
    load();
  },

  /* ------------------------------------------------------------- Print/Export */
  async printExportView(main) {
    let h = '<div class="dash-card"><div class="dash-h">Print / Export</div>'
      + '<div class="tiny muted" style="margin-bottom:10px">Export passages, guides, '
      + 'searches, notes, sermons and canvases to PDF, HTML, Markdown or text.</div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<label style="width:100px">Content type</label>'
      + '<select id="pe-type" style="flex:1">'
      + '<option value="passage">Passage</option>'
      + '<option value="guide">Guide</option>'
      + '<option value="search">Search</option>'
      + '<option value="notes">Notes</option>'
      + '<option value="sermon">Sermon</option>'
      + '<option value="word-study">Word Study</option>'
      + '<option value="canvas">Canvas</option></select>'
      + '<label style="width:110px;margin-left:10px">Reference/ID</label>'
      + '<input id="pe-id" style="flex:1" placeholder="e.g. John 3:16"></div>'
      + '<div class="org-new" style="margin-bottom:10px">'
      + '<label style="width:100px">Format</label>'
      + '<select id="pe-format" style="flex:1">'
      + '<option value="pdf">PDF</option>'
      + '<option value="html">HTML</option>'
      + '<option value="txt">Text</option>'
      + '<option value="md">Markdown</option>'
      + '<option value="docx">DOCX</option></select>'
      + '<button class="btn primary" id="pe-export" style="margin-left:10px">Export</button></div>'
      + '<div id="pe-out"></div>';
    main.innerHTML = h;
    $('#pe-export').onclick = async () => {
      const type = $('#pe-type').value;
      const id = $('#pe-id').value.trim();
      const fmt = $('#pe-format').value;
      if (!id) { toast('Enter a reference or ID.', 'warn'); return; }
      const r = await api('print-export', { action: 'export', content_type: type, content_id: id, format: fmt });
      if (!r.ok) { $('#pe-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      if (r.note) $('#pe-out').innerHTML = '<div class="tiny muted">' + esc(r.note) + '</div>';
      $('#pe-out').innerHTML += '<div class="st-sec"><div class="st-h">Exported Content</div>'
        + '<div class="st-body"><pre style="white-space:pre-wrap;font-family:monospace;font-size:12px">'
        + esc(r.content || "") + '</pre></div></div>'
        + '<div class="row wrap" style="margin-top:10px">'
        + '<button class="btn" id="pe-copy">Copy to Clipboard</button></div>';
      $('#pe-copy').onclick = async () => {
        await navigator.clipboard.writeText(r.content || "");
        toast('Copied to clipboard.');
      };
    };
  },

  async templatesView(main) {
    const r = await api('search/template');
    this.templates = r.templates || [];
    let h = '<div class="dash-card"><div class="dash-h">Search templates '
      + '<span class="muted">· ' + this.templates.length + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">Save a query you '
      + 'run often. Find it again under <b>Search</b>, or here.</div>';
    if (!this.templates.length) {
      h += '<div class="empty">None yet. Run a search and press '
        + '<b>Save search</b>.</div>';
    } else {
      h += this.templates.map(t =>
        '<div class="org-card"><div class="org-h"><b>' + esc(t.name) + '</b>'
        + '<code class="tiny">' + esc(t.query) + '</code>'
        + '<span class="org-a"><a href="#" data-tpl="' + esc(t.id) + '">run</a>'
        + '<a href="#" data-tpldel="' + esc(t.id) + '" class="danger">delete</a>'
        + '</span></div></div>').join('');
    }
    main.innerHTML = h + '</div>';
  },

  /* -- helpers used from elsewhere ---------------------------------- */

  async addModuleToCollection(moduleId) {
    const r = await api('collection');
    const cs = r.collections || [];
    const label = (modById(moduleId) || {}).name || moduleId;
    let items = cs.map(c => '<a href="#" data-cpick="' + esc(c.id) + '" data-m="'
      + esc(moduleId) + '">' + esc(c.name) + ' <span class="muted tiny">('
      + (c.count || 0) + ')</span></a>').join('');
    items += '<div class="org-new" style="margin-top:8px">'
      + '<input id="oc-quick" placeholder="New collection for ' + esc(label)
      + '" style="flex:1"><button class="btn primary" data-cnew="1" data-m="'
      + esc(moduleId) + '">Create</button></div>';
    modal('Add to a collection', '<div class="menu-list">' + items + '</div>');
    wireModalCollectionPick();
  },

  async addToPassageList(moduleId, unitKey, refLabel) {
    const r = await api('passagelist');
    const ls = r.lists || [];
    let items = ls.map(l => '<a href="#" data-lpick="' + esc(l.id)
      + '" data-k="' + esc(unitKey) + '" data-r="' + esc(refLabel || unitKey)
      + '" data-m="' + esc(moduleId) + '">' + esc(l.name)
      + ' <span class="muted tiny">(' + (l.count || 0) + ')</span></a>').join('');
    items += '<div class="org-new" style="margin-top:8px">'
      + '<input id="ol-quick" placeholder="New list for '
      + esc(refLabel || unitKey) + '" style="flex:1">'
      + '<button class="btn primary" data-lnew="1" data-k="' + esc(unitKey)
      + '" data-r="' + esc(refLabel || unitKey) + '" data-m="' + esc(moduleId)
      + '">Create</button></div>';
    modal('Add to a passage list', '<div class="menu-list">' + items + '</div>');
    wireModalPassagePick();
  },

  /* Open a passage list as one pane, in the order the user put them in.
   *
   * Unit keys are module-specific -- "John 3:16" in one module, "John.3.16" in
   * another -- so the module each reference was taken from is what makes it
   * readable.  A pane shows one module, so a list that mixed resources is read
   * from the one most of it came from, and the rest is reported rather than
   * quietly dropped. */
  async openList(listId) {
    const d = await api('passagelist', { id: listId });
    const items = d.items || [];
    if (!items.length) { toast('That list is empty.'); return; }
    const tally = {};
    items.forEach(i => { tally[i.module_id] = (tally[i.module_id] || 0) + 1; });
    const mod = Object.keys(tally).sort((a, b) => tally[b] - tally[a])[0];
    const mine = items.filter(i => i.module_id === mod);
    const skipped = items.length - mine.length;
    if (!mod || !modById(mod)) { toast('That resource is no longer installed.'); return; }

    const lay = S.layout || { panes: [] };
    let p = lay.panes.find(x => x.module_id === mod);
    let opened = false;
    if (!p) {
      p = await Workspace.openModule(mod, {});
      opened = !!p;
    }
    if (!p) return;
    p.cursor = { keys: mine.map(i => i.unit_key), list_name: modById(mod).name,
                 list_id: listId };
    /* Reader.saveNow, not Reader.save: save() is debounced and the next line
     * re-reads the layout from the server, which would discard the cursor
     * still in flight and leave the pane on the chapter the list was never
     * read from.  `this.save` was also wrong twice over -- Organise has no
     * save method, so it threw "this.save is not a function" on every click. */
    await Reader.saveNow(p);
    await App.loadWorkspace();
    App.showPane(p.tile_id || 't0', p.id);
    toast(mine.length + ' passages' + (skipped ? ' · ' + skipped
          + ' from another resource not shown' : ''));
  },
};

/* The two "add to…" modals pick a list or collection from a flat menu, so each
 * needs its own wiring; they share nothing but the shape. */
function wireModalCollectionPick() {
  const body = $('#modal-body');
  if (!body) return;
  body.onclick = async (e) => {
    const pick = e.target.closest('a[data-cpick]');
    if (pick) {
      e.preventDefault();
      const r = await api('collection', { action: 'add', id: pick.dataset.cpick,
                                          module: pick.dataset.m });
      const where = pick.textContent.trim().split(' ')[0];
      toast(r.unchanged ? 'Already in ' + where + '.'
                        : 'Added to ' + where);
      closeModal();
      return;
    }
    const nw = e.target.closest('[data-cnew]');
    if (nw) {
      e.preventDefault();
      const name = ($('#oc-quick') || {}).value || '';
      await api('collection', { action: 'save', name: name,
                                modules: [nw.dataset.m] });
      toast('Collection created');
      closeModal();
      if (S.view === 'organise') Organise.load();
    }
  };
}

function wireModalPassagePick() {
  const body = $('#modal-body');
  if (!body) return;
  body.onclick = async (e) => {
    const pick = e.target.closest('a[data-lpick]');
    if (pick) {
      e.preventDefault();
      const r = await api('passagelist', { action: 'add', id: pick.dataset.lpick,
                                           key: pick.dataset.k,
                                           ref: pick.dataset.r,
                                           module: pick.dataset.m });
      toast(r.unchanged ? 'Already in that list.'
                        : 'Added to ' + pick.textContent.trim().split(' ')[0]);
      closeModal();
      return;
    }
    const nw = e.target.closest('[data-lnew]');
    if (nw) {
      e.preventDefault();
      const name = ($('#ol-quick') || {}).value || '';
      const made = await api('passagelist', { action: 'save', name: name });
      await api('passagelist', { action: 'add', id: made.id, key: nw.dataset.k,
                                 ref: nw.dataset.r, module: nw.dataset.m });
      toast('List created');
      closeModal();
      if (S.view === 'organise') Organise.load();
    }
  };
}

const Guides = {
  _morphSeq: 0,

  async load() {
    const tab = $('#g-tab').value;
    const body = $('#g-body');
    body.innerHTML = '<div class="st-loading">Loading…</div>';
    $('#g-ref').style.display = (tab === 'chapter' || tab === 'outline'
      || tab === 'sermons') ? '' : 'none';
    $('#g-name').style.display = tab === 'genealogy' ? '' : 'none';
    $('#g-morph').style.display = tab === 'morph' ? '' : 'none';
    $('#g-trad').style.display = tab === 'canon' ? '' : 'none';
    $('#g-term').style.display = tab === 'counsel' ? '' : 'none';
    $('#g-eusec').style.display = tab === 'eusebian' ? '' : 'none';
    $('#g-eus').style.display = tab === 'eusebian' ? '' : 'none';
    /* One search box, used by whichever tab is open.  The grammar tab wants a
     * term, not a reference or a name, so it borrows `g-term` -- the box the
     * counseling tab already uses -- and says so in its placeholder. */
    $('#g-term').style.display =
      (tab === 'counsel' || tab === 'grammar') ? '' : 'none';
    if (tab === 'grammar') $('#g-term').placeholder = 'a word, e.g. Piel';
    else if (tab === 'counsel') $('#g-term').placeholder = 'a topic, e.g. grief';
    $('#g-oexport').style.display = tab === 'outline' ? '' : 'none';
    // wire() in a finally, so the guide's links work whichever tab rendered --
    // it used to be called from nowhere, which left every reference in the
    // canon, harmony, timeline and chapter tables inert.  Doing it here rather
    // than at the end of each renderer means a new tab cannot forget it.
    try {
      if (tab === 'canon') return await this.canon(body);
      if (tab === 'eusebian') return await this.canon(body);
      if (tab === 'harmony') return await this.harmony(body);
      if (tab === 'timeline') return await this.timeline(body);
       if (tab === 'biblefacts') return await this.biblefacts(body);
      if (tab === 'genealogy') return await this.genealogy(body);
      if (tab === 'morph') return await this.morphology(body);
      if (tab === 'grammar') return await Grammar.load(body);
      if (tab === 'outline') return await Outlines.load();
      if (tab === 'psalms') return await this.psalms(body);
      if (tab === 'books') return await this.books(body);
      if (tab === 'syntax') return await SyntaxTree.load(body);
      if (tab === 'counsel') return await Counsel.load(body);
      return await this.chapter(body);
    } finally {
      this.wire();
    }
  },

  async timeline(body) {
    /* Two views of one chronology.  The table is the reference reading: every
     * row with its passage, its note and how far the date can be trusted.  The
     * chart is the shape of it -- two thousand years in one glance, which is
     * what a list of eighty dates cannot show. */
    body.innerHTML = '<div class="tl-views">'
      + '<button class="btn on" data-tlview="table">As a table</button>'
      + '<button class="btn" data-tlview="chart">As a chart</button>'
      + '</div><div id="tl-out"></div>';
    $$('.tl-views button', body).forEach(b => b.onclick = () => {
      $$('.tl-views button', body).forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      if (b.dataset.tlview === 'chart') this.timelineChart($('#tl-out', body));
      else this.timelineTable($('#tl-out', body));
    });
    await this.timelineTable($('#tl-out', body));
  },

  /* The chronology as a number line.
   *
   * Drawn as inline SVG rather than pulled from a chart library: the project
   * ships no dependencies, and this is one axis and eighty marks.  Rows are
   * stacked into lanes so two events in the same century do not overprint each
   * other and hide one -- which on a number line two thousand years wide is not
   * a cosmetic problem, it is most of the data.
   */
  async biblefacts(body) {
     const r = await api('guides/biblefacts');
     if (!r.ok) { body.innerHTML = esc(r.error || 'failed'); return; }
     let h = '';
     const factTable = (title, rows, fields) => {
       if (!rows || !rows.length) return '';
       let t = '<div class="dash-card"><div class="dash-h">' + esc(title) + '</div>'
         + '<table class="tbl"><thead><tr>'
         + fields.map(f => '<th>' + esc(f.label) + '</th>').join('')
         + '</tr></thead><tbody>';
       rows.forEach(row => {
         t += '<tr>' + fields.map(f => '<td>' + esc(String(row[f.key] == null ? '' : row[f.key])) + '</td>').join('') + '</tr>';
       });
       t += '</tbody></table></div>';
       return t;
     };
     h += factTable('Weights', r.weights,
       [{key:'name',label:'Name'},{key:'value',label:'Value'},{key:'grams',label:'Grams'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     h += factTable('Dry measures', r.measures_dry,
       [{key:'name',label:'Name'},{key:'value',label:'Value'},{key:'litres',label:'Litres'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     h += factTable('Liquid measures', r.measures_liquid,
       [{key:'name',label:'Name'},{key:'value',label:'Value'},{key:'litres',label:'Litres'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     h += factTable('Money', r.money,
       [{key:'name',label:'Name'},{key:'value',label:'Value'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     h += factTable('Calendar months', r.calendar_months,
       [{key:'name',label:'Name'},{key:'position',label:'#'},{key:'gregorian',label:'Gregorian'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     h += factTable('Festivals', r.festivals,
       [{key:'name',label:'Name'},{key:'month',label:'When'},{key:'scripture',label:'Scripture'},{key:'note',label:'Note'}]);
     body.innerHTML = h;
   },

  async timelineChart(out) {
    const r = await api('timeline/spans');
    if (!r.ok) { out.innerHTML = esc(r.error || 'no dated events'); return; }
    const W = 1000, LANE = 15, PADL = 8, PADR = 8;
    const H = 132;
    const lo = r.min, hi = r.max;
    const x = (y) => PADL + ((y - lo) / (hi - lo)) * (W - PADL - PADR);
    const rows = r.rows.slice().sort((a, b) => a.year - b.year);
    const MIN_GAP = (W - PADL - PADR) * 0.022;
    let lastX = -1e9, lane = 0;
    const marks = [];
    rows.forEach((e) => {
      const px = x(e.year);
      // A new lane whenever the next mark would touch the last one in this one.
      if (px - lastX < MIN_GAP) lane = (lane + 1) % 5;
      else lane = 0;
      lastX = px;
      const y = 34 + lane * LANE;
      const cls = e.confidence === 'text' ? 'tl-tick is-text'
        : (e.confidence === 'secular' ? 'tl-tick is-secular' : 'tl-tick');
      marks.push(
        '<circle class="' + cls + '" cx="' + px.toFixed(1) + '" cy="' + y
        + '" r="3.2"><title>' + esc(e.when + ' · ' + e.title
          + (e.note ? ' — ' + e.note : '')) + '</title></circle>'
        + (lane === 0
          ? '<text class="tl-lab" x="' + px.toFixed(1) + '" y="' + (y - 8)
            + '" text-anchor="middle">' + esc(e.title.slice(0, 18)) + '</text>'
          : ''));
    });
    const zero = x(0);
    out.innerHTML =
      '<div class="tl-chart-note tiny muted">' + esc(r.note) + '</div>'
      + '<svg class="tl-chart" viewBox="0 0 ' + W + ' ' + H + '" '
      + 'role="img" aria-label="Biblical chronology">'
      + '<line class="tl-axis" x1="' + PADL + '" y1="24" x2="' + (W - PADR)
      + '" y2="24"/>'
      + '<line class="tl-zero" x1="' + zero.toFixed(1) + '" y1="14" x2="'
      + zero.toFixed(1) + '" y2="' + (H - 22) + '"/>'
      + '<text class="tl-era" x="' + (PADL + 4) + '" y="' + (H - 8)
      + '">BC</text>'
      + '<text class="tl-era" x="' + (W - PADR - 4) + '" y="' + (H - 8)
      + '" text-anchor="end">AD</text>'
      + marks.join('')
      + '</svg>'
      + '<div class="tl-legend tiny">'
      + '<span class="tl-key"><i class="tl-tick is-text"></i> anchored in the text</span>'
      + '<span class="tl-key"><i class="tl-tick"></i> reconstructed date</span>'
      + '<span class="tl-key"><i class="tl-tick is-secular"></i> outside the text</span>'
      + '</div>'
      + '<div class="tl-list">' + rows.map(e =>
        '<button class="tl-chip" data-year="' + e.year + '">'
        + esc(e.when + ' · ' + e.title) + '</button>').join('') + '</div>';
    $$('.tl-chip', out).forEach(b => b.onclick = () => {
      const e = rows.find(z => String(z.year) === b.dataset.year
        && b.textContent.includes(z.title));
      if (!e) return;
      modal(e.when + ' — ' + e.title,
        '<div class="st-body">' + esc(e.note || '') + '</div>'
        + (e.link ? '<div class="tiny"><a href="#" data-openref="'
          + esc(e.link) + '">' + esc(e.refs) + '</a></div>' : '')
        + '<div class="tiny muted">' + esc('date: ' + e.confidence)
        + '</div>',
        [{ label: 'Close', cls: 'btn' }]);
      $$('#modal-body a[data-openref]').forEach(a => a.onclick = (ev) => {
        ev.preventDefault();
        closeModal();
        Reader.openRefAnywhere(a.dataset.openref);
      });
    });
  },

  async timelineTable(out) {
    const r = await api('timeline/linked');
    if (!r.ok) { out.innerHTML = esc(r.error || 'failed'); return; }
    let h = '<div class="dash-card"><div class="dash-h">'
      + r.total + ' entries · ' + r.from_text + ' anchored in the text</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.note) + '</div>';
    h += '<div class="tl-kinds">' + r.kinds.map(k =>
      '<span class="chip">' + esc(k) + '</span>').join('') + '</div>';
    r.periods.forEach(p => {
      h += '<div class="tl-period"><div class="tl-pl">' + esc(p.label) + '</div>'
        + '<table class="tl"><tbody>';
      p.rows.forEach(x => {
        // The server resolves each reference and sends back an osis id to open,
        // because only it knows what the parser accepts.
        const linkable = !!x.link;
        h += '<tr><td class="tl-when">' + esc(x.when) + '</td>'
          + '<td class="tl-t"><b>' + esc(x.title) + '</b>'
          + (x.note ? ' <span class="muted tiny">' + esc(x.note) + '</span>' : '')
          /* The genealogy join: who this person was, parent to child.  A name
           * match between a curated event and an extracted family line, and the
           * panel says so rather than implying the two are one dataset. */
          + (x.person ? ' <a href="#" class="tl-person" data-person="'
              + esc(x.person.id) + '" title="'
              + esc((x.person.parents.length
                     ? 'son of ' + x.person.parents.join(', ')
                     : 'no parent in the text') + ' · '
                     + x.person.children.length + ' children') + '">'
              + esc(x.person.name)
              + (x.person.parents.length
                 ? ' <span class="muted tiny">← '
                   + esc(x.person.parents.join(', ')) + '</span>' : '')
              + '</a>' : '')
          + '</td>'
          + '<td class="tl-k">' + esc(x.kind) + '</td>'
          + '<td class="tl-r">' + (linkable
            ? '<a href="#" data-ref="' + esc(x.link) + '">'
              + esc(x.refs) + '</a>'
            : esc(x.refs || '—')) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    });
    out.innerHTML = h + '</div>';
  },

  /* Genealogy: a person, their parents, their children, and both directions
   * of the line.
   *
   * Nothing here is generated.  Every relationship was read out of the text of
   * one installed translation and keeps the verses that state it, so each link
   * opens the passage the claim came from. */
  /* Morph query: pick the grammatical features, see the words.
   *
   * The options are built from the 4,300 codes actually installed, with counts,
   * rather than from a list of every form the grammar allows -- asking for a
   * category nothing uses is a dead end with no warning. */
  async morphology(body) {
    const r = await api('morph/facets');
    if (!r.ok) { body.innerHTML = esc(r.error || 'failed'); return; }
    const f = r.facets;
    const FIELDS = [
      ['pos', 'Kind of word'], ['gender', 'Gender'], ['number', 'Number'],
      ['state', 'Noun state'], ['conjugation', 'Verb stem'],
      ['tense', 'Tense'], ['person', 'Person'],
      ['participle', 'Participle'], ['pos_particle', 'With a particle'],
    ];
    if (!this._morphForm) {
      let h = '<div class="dash-card"><div class="dash-h">Morph query</div>'
        + '<div class="tiny muted" style="margin-bottom:8px">'
        + `${f.codes.toLocaleString()} distinct codes over `
        + `${f.total.toLocaleString()} tagged words. Every option below is one `
        + 'that occurs in your text.</div><div class="morph-form">';
      FIELDS.forEach(([k, label]) => {
        const opts = f[k] || [];
        h += '<label>' + esc(label)
          + '<select id="mq-' + k + '"><option value="">any</option>'
          + opts.slice(0, 18).map(o =>
              '<option value="' + esc(o.value) + '">' + esc(o.value)
              + ' (' + o.n.toLocaleString() + ')</option>').join('')
          + '</select></label>';
      });
      h += '</div><button class="btn primary" id="mq-go">Find these words</button>'
        + '<span id="mq-out" class="tiny muted"></span></div>';
/* The sections the reader configured, which this view does not already
     * render.  `study/passage` returns its own fixed five sections and ignored
     * the guide configuration entirely, so `guide/config` -- editable, saved,
     * and offered in this very modal's toolbar -- was written and never read.
     * Every section added or removed through that editor had no effect on what
     * appeared here.  The configured guide is run for real now; the sections
     * above already render well and are not repeated. */
    body.innerHTML = h;
    // Clicking a cross-reference opens it in the Bible pane.
    $$('.pg-xref a', body).forEach((a, i) => {
      a.onclick = (e) => {
        e.preventDefault();
        Reader.openRefAnywhere(b.xrefs[i].label.replace('.', ' '));
      };
    });
      $('#mq-go').onclick = () => this.morphologyRun(body);
      // a change re-runs, so the count is never stale
      $$('#g-body select[id^=mq-]').forEach(sel => {
        sel.onchange = () => this.morphologyRun(body);
      });
      this._morphForm = true;
    }
    if (!this._morphDone) { this._morphDone = true; await this.morphologyRun(body); }
  },

  async morphologyRun(body) {
    const q = {};
    $$('#g-body select[id^=mq-]').forEach(sel => {
      if (sel.value) q[sel.id.slice(3)] = sel.value;
    });
    /* Changing four selects fires four requests, and they can answer out of
     * order -- so the panel showed 15,601 words for a filter the engine counts
     * as 9,032.  Only the newest reply is allowed to paint. */
    const mine = ++this._morphSeq;
    const r = await api('morph/query', Object.assign({ limit: 80 }, q));
    if (mine !== this._morphSeq) return;              // superseded
    const out = $('#mq-out');
    if (!r.ok) { if (out) out.textContent = r.error || 'failed'; return; }
    if (out) out.textContent = r.total.toLocaleString() + ' words in '
      + r.codes + ' codes';
    let h = '<div class="dash-card"><div class="dash-h">'
      + r.total.toLocaleString() + ' words <span class="muted">· ' + r.codes
      + ' codes</span></div>';
    h += '<table class="tl"><tbody>';
    r.results.forEach(x => {
      const f = x.features;
      h += '<tr><td class="tl-when"><code>' + esc(x.code) + '</code></td>'
        + '<td class="tl-t">' + esc(f.pos || '') + '</td>'
        + '<td class="tl-k">' + esc(f.gender || '') + '</td>'
        + '<td class="tl-r">' + esc([f.number, f.state, f.conjugation, f.tense,
                                     f.person].filter(Boolean).join(' · '))
        + '</td>'
        + '<td class="tl-r"><b>' + x.count.toLocaleString() + '</b></td></tr>';
    });
    h += '</tbody></table>';
    if (r.samples && r.samples.length) {
      h += '<div class="dash-h" style="margin-top:12px">Examples</div>'
        + '<div class="morph-samples">'
        + r.samples.slice(0, 40).map(x =>
            '<a href="#" class="chip" data-ref="' + esc(x.ref || x.key) + '">'
            + esc(x.surface || x.code) + '</a>').join(' ')
        + '</div>';
    }
    const samples = document.createElement('div');
    samples.innerHTML = h + '</div>';
    /* One results card, replaced each time.  Appending a new one per run left
     * the old unfiltered results on screen too, so the table showed every code
     * in the language next to the filter that was supposed to exclude them. */
    let host = body.querySelector('#mq-results');
    if (!host) {
      host = document.createElement('div');
      host.id = 'mq-results';
      body.appendChild(host);
    }
    host.innerHTML = samples.innerHTML;
  },

  async genealogy(body) {
    const name = ($('#g-name').value || '').trim();
    if (!name) { await this.genealogyIndex(body); return; }
    const [an, sub, per] = await Promise.all([
      api('genealogy/ancestry', { name: name, depth: 24 }),
      api('genealogy/subtree', { name: name, depth: 2 }),
      api('genealogy/person', { name: name }),
    ]);
    if (!an.ok) { body.innerHTML = esc(an.error || 'not found'); return; }
    const P = per.ok ? per.person
                     : { variants: [], parent_list: [], child_list: [] };
    const refLinks = (refs) => (refs || []).map(r =>
      '<a href="#" data-ref="' + esc(r) + '">' + esc(r) + '</a>').join(' \u00b7 ');
    let h = '<div class="dash-card"><div class="dash-h">' + esc(P.name || an.start)
      + (P.variants && P.variants.length
         ? ' <span class="muted tiny">also ' + esc(P.variants.join(', ')) + '</span>'
         : '') + '</div>';

    h += '<div class="gn-block"><div class="gn-h">Parents</div>';
    h += (P.parent_list && P.parent_list.length)
      ? P.parent_list.map(x => '<div class="gn-row"><a href="#" data-person="'
          + esc(x.id) + '">' + esc(x.name) + '</a><span class="muted tiny"> '
          + refLinks((x.refs || []).slice(0, 3)) + '</span></div>').join('')
      : '<div class="empty">no parent stated in the text read</div>';
    h += '</div>';

    h += '<div class="gn-block"><div class="gn-h">Children</div>';
    h += (P.child_list && P.child_list.length)
      ? P.child_list.map(x => '<div class="gn-row"><a href="#" data-person="'
          + esc(x.id) + '">' + esc(x.name) + '</a><span class="muted tiny"> '
          + refLinks((x.refs || []).slice(0, 2)) + '</span></div>').join('')
      : '<div class="empty">no children stated in the text read</div>';
    h += '</div>';

    if (an.levels.length > 1) {
      h += '<div class="gn-block"><div class="gn-h">Ancestry \u2014 '
        + an.generations + ' generations up</div>';
      an.levels.slice(1).forEach((lv, i) => {
        h += '<div class="gn-gen"><span class="gn-genn">' + (i + 1) + '</span>'
          + lv.map(x => '<a href="#" data-person="' + esc(x.id) + '">'
            + esc(x.name) + '</a>').join('<span class="muted"> \u00b7 </span>')
          + '</div>';
      });
      h += '</div>';
    }

    if (sub.branches && sub.branches.length) {
      h += '<div class="gn-block"><div class="gn-h">Descendants</div>';
      sub.branches.forEach(b => {
        const kids = b.children || [];
        h += '<div class="gn-gen"><span class="gn-genn">'
          + new Array(Math.max(b.depth, 1)).join('&nbsp;&nbsp;') + '</span>'
          + '<b>' + esc(b.name) + '</b> <span class="muted tiny">'
          + kids.map(c => '<a href="#" data-person="' + esc(c.id) + '">'
              + esc(c.name) + '</a>').join(', ')
          + '</span></div>';
      });
      h += '</div>';
    }
    h += '<div class="tiny muted" style="margin-top:10px">Read from the text of '
      + 'one installed translation. Every reference above is a verse the '
      + 'relationship is actually stated in.</div></div>';
    body.innerHTML = h;
  },

  async genealogyIndex(body) {
    const s = await api('genealogy/summary');
    if (!s.ok) { body.innerHTML = esc(s.error || 'failed'); return; }
    const kinds = {
      shared: 'two people who share a name',
      listed: 'one line given twice, differently',
      variant: 'a spelling variant of one name',
    };
    let h = '<div class="dash-card"><div class="dash-h">'
      + s.counts.people + ' people \u00b7 ' + s.counts.edges + ' relationships \u00b7 '
      + s.counts.refs + ' verses</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">' + esc(s.note) + '</div>'
      + '<div class="tiny">Type a name above, or try: '
      + ['Adam', 'Noah', 'Abraham', 'Jacob', 'Judah', 'David', 'Solomon',
         'Rehoboam', 'Jesus'].map(x =>
        '<a href="#" data-person="' + esc(x.toLowerCase()) + '">' + x + '</a>')
        .join(' \u00b7 ') + '</div>';

    h += '<div class="gn-block"><div class="gn-h">Where the sources differ</div>'
      + '<div class="tiny muted" style="margin-bottom:6px">'
      + esc(s.conflicts_note) + '</div>';
    ['shared', 'listed', 'variant'].forEach(k => {
      const rows = s.conflicts.filter(c => c.kind === k);
      if (!rows.length) return;
      h += '<div class="gn-conf-h">' + rows.length + ' \u2014 ' + esc(kinds[k])
        + '</div>';
      rows.slice(0, 8).forEach(c => {
        h += '<div class="gn-row"><a href="#" data-person="' + esc(c.id) + '">'
          + esc(c.name) + '</a> <span class="muted tiny">\u2190 '
          + esc(c.parent_names.join(' / ')) + ' \u00b7 '
          + esc((c.refs || []).slice(0, 3).join(', ')) + '</span></div>';
      });
      if (rows.length > 8) h += '<div class="tiny muted">\u2026and '
        + (rows.length - 8) + ' more</div>';
    });
    h += '</div>';
    if (s.partial && s.partial.length) {
      h += '<div class="gn-block"><div class="gn-h">Partial ('
        + s.partial.length + ')</div><div class="tiny muted">A list the text '
        + 'interrupted with a description, so these children are only the ones '
        + 'it named outright: ' + esc(s.partial.slice(0, 6).join('; '))
        + ' \u2026</div></div>';
    }
    h += '</div>';
    body.innerHTML = h;
  },

  async canon(body) {
    const t = $('#g-trad').value;
    const [full, charts] = await Promise.all([
      api('guides/canon', { tradition: t }),
      api('guides/canons'),
    ]);
    if (!full.ok) { body.innerHTML = esc(full.error || 'failed'); return; }
    let h = '<div class="dash-card"><div class="dash-h">' + esc(full.label)
      + '</div><div class="tiny muted" style="margin-bottom:8px">'
      + full.count + ' books · ' + full.chapters + ' chapters · '
      + full.verses.toLocaleString() + ' verses (' + esc(full.v11n) + ')</div>'
      + '<div class="canon-groups">'
      + full.groups.map(g =>
        '<div class="canon-g"><div class="canon-gl">' + esc(g.label) + '</div>'
        + '<div class="canon-b">' + g.books.map(b =>
          '<span class="canon-book" data-book="' + esc(b) + '">'
          + esc(b) + '</span>').join('') + '</div></div>').join('')
      + '</div></div>';
    if (charts && charts.charts) {
      h += '<div class="dash-card"><div class="dash-h">How the traditions differ</div>'
        + charts.charts.map(c => '<div class="dash-row"><b>' + c.count
          + ' books</b> · ' + c.chapters + ' chapters · '
          + c.verses.toLocaleString() + ' verses'
          + ' <span class="muted tiny">' + esc(c.label) + '</span></div>').join('')
        + '</div>';
    }
    body.innerHTML = h;
  },

  async harmony(body) {
    const r = await api('guides/harmony');
    if (!r.ok) { body.innerHTML = esc(r.error || 'failed'); return; }
    let h = '<div class="dash-card"><div class="dash-h">'
      + r.gospels.map((g, i) => ['Mark', 'Matthew', 'Luke', 'John'][i]).join(' · ')
      + '</div><div class="tiny muted" style="margin-bottom:8px">' + esc(r.note)
      + '</div><table class="harm"><thead><tr><th>Event</th>'
      + r.gospels.map(g => '<th>' + esc(g) + '</th>').join('')
      + '</tr></thead><tbody>';
    r.rows.forEach(row => {
      h += '<tr><td class="harm-e">' + esc(row.event) + '</td>'
        + row.refs.map(x => '<td>' + (x.pericope === '—'
          ? '<span class="muted">—</span>'
          : '<a href="#" data-ref="' + esc(x.pericope) + '">'
            + esc(x.pericope) + '</a>') + '</td>').join('')
        + '</tr>';
    });
    body.innerHTML = h + '</tbody></table></div>';
  },

  async psalms(body) {
    const r = await api('explore/psalms', {});
    if (!r.ok) { body.innerHTML = esc(r.error || 'failed'); return; }
    const moods = [...new Set((r.psalms || []).flatMap(p => p.moods || []))].sort();
    let h = '<div class="dash-card"><div class="dash-h">Psalms — ' + esc(r.bible || '')
      + ' <span class="muted">· ' + (r.count || 0) + '</span></div>'
      + '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.note || '')
      + '</div><div class="row wrap" style="margin-bottom:8px">'
      + '<button class="btn on" data-mood="">All</button>'
      + moods.map(m => '<button class="btn" data-mood="' + esc(m) + '">'
        + esc(m) + '</button>').join('') + '</div><div id="ps-rows">';
    const paint = (mood) => {
      $('#ps-rows', body).innerHTML = (r.psalms || [])
        .filter(p => !mood || (p.moods || []).includes(mood))
        .map(p => '<div class="wl-row"><span class="ref"><a href="#" data-ref="'
          + esc(p.ref) + '">' + esc(p.ref) + '</a></span>'
          + '<span class="txt">' + esc(p.superscription || '') + '</span>'
          + '<span class="n">' + p.verses + ' vv · ' + p.words + ' w</span>'
          + '<span class="n">' + esc((p.moods || []).join(', ')) + '</span></div>').join('');
    };
    body.innerHTML = h + '</div></div>';
    paint('');
    $$('[data-mood]', body).forEach(b => b.onclick = () => {
      $$('[data-mood]', body).forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      paint(b.dataset.mood);
    });
  },

  async books(body) {
    const r = await api('explore/books', {});
    if (!r.ok) { body.innerHTML = esc(r.error || 'failed'); return; }
    const t = r.totals || {};
    const books = r.books || [];
    const max = Math.max(...books.map(b => b.words), 1);
    const genres = [...new Set(books.map(b => b.genre).filter(Boolean))].sort();
    body.innerHTML = '<div class="dash-card"><div class="dash-h">Books — '
      + esc(r.bible || '') + '</div><div class="tiny muted" style="margin-bottom:8px">'
      + (t.books || 0) + ' books · ' + (t.chapters || 0) + ' chapters · '
      + (t.verses || 0).toLocaleString() + ' verses · '
      + (t.words || 0).toLocaleString() + ' words, counted off installed text. '
      + 'Genre and author are the conventional attributions, not claims about composition.</div>'
      + '<div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap">'
      + '<select id="books-genre"><option value="">All genres</option>'
      + genres.map(g => '<option value="' + esc(g) + '">' + esc(g) + '</option>').join('')
      + '</select>'
      + '<select id="books-test"><option value="">All testaments</option>'
      + '<option value="OT">Old Testament</option><option value="NT">New Testament</option></select>'
      + '<input type="search" id="books-q" placeholder="filter by name…" style="width:140px">'
      + '</div>'
      + '<div id="books-table"></div></div>';
    const render = () => {
      const g = $('#books-genre').value;
      const ts = $('#books-test').value;
      const q = ($('#books-q').value || '').toLowerCase().trim();
      let rows = books;
      if (g) rows = rows.filter(b => b.genre === g);
      if (ts) rows = rows.filter(b => b.testament === ts);
      if (q) rows = rows.filter(b => (b.name || '').toLowerCase().includes(q)
        || (b.author || '').toLowerCase().includes(q));
      const tbl = '<table class="tbl"><thead><tr>'
        + '<th>Book</th><th>Group</th><th>Genre</th><th>Author (traditional)</th>'
        + '<th>Ch</th><th>Vv</th><th>Words</th><th></th></tr></thead><tbody>'
        + rows.map(b => '<tr>'
          + '<td><a href="#" data-ref="' + esc(b.name) + ' 1">' + esc(b.name) + '</a></td>'
          + '<td>' + esc(b.group || '') + '</td>'
          + '<td>' + esc(b.genre || '') + '</td>'
          + '<td class="muted">' + esc(b.author || '') + '</td>'
          + '<td>' + b.chapters + '</td>'
          + '<td>' + b.verses + '</td>'
          + '<td>' + b.words.toLocaleString() + '</td>'
          + '<td><span style="display:inline-block;height:8px;background:var(--acc);width:'
          + Math.round(80 * b.words / max) + 'px"></span></td></tr>').join('')
        + '</tbody></table>';
      $('#books-table').innerHTML = tbl || '<div class="empty">No books match.</div>';
    };
    $('#books-genre').onchange = render;
    $('#books-test').onchange = render;
    $('#books-q').oninput = render;
    render();
  },

  async chapter(body) {
    const ref = ($('#g-ref').value || '').trim() || 'John 3';
    const g = await api('guides/chapter', { ref });
    if (!g.ok) { body.innerHTML = esc(g.error || 'failed'); return; }
    // A book-level request says so, instead of reading like a chapter with a
    // stray "Gen" in the title.
    let h = '<div class="dash-card"><div class="dash-h">' + esc(g.ref)
      + (g.whole_book
         ? ' — the whole book, in your library'
         : ' — in your library') + '</div>';
    if (g.whole_book) {
      h += '<div class="tiny muted" style="margin-bottom:8px">'
        + (g.chapters_covered || 0) + ' chapters covered by commentary'
        + ' · <a href="#" data-ref="' + esc(g.book) + ' 1">open '
        + esc(g.book) + ' 1</a></div>';
    }
    h += '<div class="dash-h" style="margin-top:10px">Commentaries</div>';
    h += (g.commentaries || []).length
      ? g.commentaries.map(c => '<div class="dash-row"><a href="#" data-open="'
        + esc(c.module_id) + '"><b>' + esc(c.module) + '</b></a> '
        + '<span class="muted">' + c.notes + ' note'
        + (c.notes === 1 ? '' : 's') + '</span></div>').join('')
      : '<div class="empty">No commentary covers'
        + (g.whole_book ? ' this book.' : ' this chapter.') + '</div>';
    h += '<div class="dash-h" style="margin-top:12px">Topics mentioning it</div>';
    h += (g.topics || []).length
      ? g.topics.map(t => '<div class="st-note"><div class="st-src">'
        + esc(t.module) + '</div><div class="st-t">' + esc(t.title)
        + '</div><div class="st-body">' + esc(t.text) + '</div></div>').join('')
      : '<div class="empty">No topic entry cites this chapter.</div>';
    h += '<div class="tiny muted" style="margin-top:12px">' + esc(g.outline_note)
      + '</div></div>';
    body.innerHTML = h;
  },

  wire() {
    $('#g-body').onclick = (e) => {
      const r = e.target.closest('a[data-ref]');
      if (r) { e.preventDefault(); App.show('workspace'); Reader.openRefAnywhere(r.dataset.ref); return; }
      const b = e.target.closest('[data-book]');
      if (b) { $('#g-ref').value = b.dataset.book; $('#g-tab').value = 'chapter'; this.load(); return; }
      const per = e.target.closest('a[data-person]');
      if (per) {
        e.preventDefault();
        // the id, not the text: the timeline label reads "Abram <- Terah", and
        // searching the genealogy for that finds nobody
        $('#g-name').value = per.dataset.person || '';
        $('#g-tab').value = 'genealogy';
        this.load();
        return;
      }
      const o = e.target.closest('a[data-open]');
      if (o) {
        e.preventDefault();
        const mod = modById(o.dataset.open);
        if (mod) { App.show('workspace'); Workspace.openModule(mod.id, {}); }
        return;
      }
      /* The Eusebian grid is a table of references, and almost every cell is a
       * reference to open -- but a cell holds a range plus a "+n" rather than a
       * link per verse, so the reference links carry data-openref and are picked
       * up by the same delegated handler the rest of the body uses.  The row
       * number is a lookup instead: clicking 1.1 in canon I asks what else
       * carries that number, which is the question the row number exists to
       * raise. */
      const openref = e.target.closest('a[data-openref]');
      if (openref) {
        e.preventDefault();
        Reader.openRefAnywhere(openref.dataset.openref);
        return;
      }
      const sec = e.target.closest('a[data-eusec]');
      if (sec) {
        e.preventDefault();
        $('#g-eusec').value = sec.dataset.eusec;
        this.load();
        return;
      }
      const eucan = e.target.closest('[data-eu]');
      if (eucan) {
        $('#g-eusec').value = '';
        $('#g-eus').value = eucan.dataset.eu;
        this.load();
      }
    };

    $('#g-eusec').onkeydown = (e) => { if (e.key === 'Enter') Guides.load(); };
  },
};

/* ================================================================== App */
