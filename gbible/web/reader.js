const Reader = {
  async render(p, m, body, tools) {
    body.innerHTML = '<div class="loading">Loading…</div>';
    const opts = Object.assign({}, p.options || {});
    /* Multiple Book Display: when a parallel resource is chosen for this pane,
     * render the main resource and the parallel one side by side in one tab. */
    const parId = opts.parallel;
    if (parId && parId !== m.id && m.reader === 'verse') {
      const pm = modById(parId);
      if (pm && pm.reader === 'verse') {
        await this.renderParallel(p, m, pm, body, tools, opts);
        return;
      }
    }
    /* Neighbouring entries, for a resource navigated by key.  Requested only
     * where there is something to do with them: every reader accepts the
     * context window, but a Bible chapter pays for one it will not read. */
    const wantCtx = opts.context != null ? opts.context
      : (m.reader === 'article' ? 6 : 0);
    const r = await api('read', {
      id: m.id, cursor: p.cursor, options: opts,
      span: p.cursor.span || 'chapter', context: wantCtx });
    if (!r.ok) { body.innerHTML = '<div class="empty">' + esc(r.error) + '</div>'; return; }
    p.cursor = r.cursor || p.cursor;
    p._content = r;
    body.className = 'pane-body' + (opts.verse_per_line ? ' verseperline' : '');
    this.paint(r, m, body, p.options || {}, p);
    /* Factbook tags: a hover definition on a name, without leaving the page.
     * Proper nouns only here, because a tooltip on every word that happens to
     * match a head trains you to ignore it. */
    if (S.factTags !== false && r.items && r.items.length) {
      const sample = r.items.slice(0, 4).map(it => it.text || '').join(' ');
      if (sample.trim().length > 2) {
        api('study/tags', { text: sample, n: 30 }).then(t => {
          if (t && t.ok && t.tags && t.tags.length) Reader.applyTags(body, t.tags);
        }).catch(() => {});
      }
    }
    if (r.ref_label && m.reader === 'verse' && tools) {
      const box = $('.refbox', tools.parentElement);
      if (box) box.value = r.ref_label;
    }
    VisualFilters.paintPane(p, m, body);
    ClickSearch.arm(p, body);
  },

  async renderParallel(p, m, pm, body, tools, opts) {
    const r1 = await api('read', { id: m.id, cursor: p.cursor, options: opts,
      span: p.cursor.span || 'chapter', context: 0 });
    const r2 = await api('read', { id: pm.id, cursor: p.cursor, options: opts,
      span: p.cursor.span || 'chapter', context: 0 });
    if (!r1.ok) { body.innerHTML = '<div class="empty">' + esc(r1.error) + '</div>'; return; }
    p.cursor = r1.cursor || p.cursor;
    p._content = r1;
    body.className = 'pane-body';
    body.innerHTML = '';
    const wrap = el('div', 'mbd-wrap');
    const col1 = el('div', 'mbd-col');
    const col2 = el('div', 'mbd-col');
    const h1 = el('div', 'mbd-head', esc(m.name || m.id));
    const h2 = el('div', 'mbd-head', esc(pm.name || pm.id));
    col1.appendChild(h1); col2.appendChild(h2);
    const v1 = el('div', 'verses'); const v2 = el('div', 'verses');
    const items2 = (r2.ok && r2.items) ? r2.items : [];
    const byKey2 = {};
    items2.forEach(it => { byKey2[it.key] = it; });
    r1.items.forEach(it => {
      const sp = el('span', 'verse');
      sp.dataset.label = it.label; sp.dataset.k = it.key;
      sp.innerHTML = '<a class="vnum" data-k="' + esc(it.key) + '">'
        + esc(it.label.split(' ').pop()) + '</a>' + it.html;
      v1.appendChild(sp);
      const it2 = byKey2[it.key];
      const sp2 = el('span', 'verse');
      if (it2) {
        sp2.dataset.label = it2.label; sp2.dataset.k = it2.key;
        sp2.innerHTML = '<a class="vnum" data-k="' + esc(it2.key) + '">'
          + esc(it2.label.split(' ').pop()) + '</a>' + it2.html;
      } else {
        sp2.innerHTML = '<span class="muted">—</span>';
      }
      v2.appendChild(sp2);
    });
    col1.appendChild(v1); col2.appendChild(v2);
    wrap.appendChild(col1); wrap.appendChild(col2);
    body.appendChild(wrap);
    if (r1.ref_label && tools) {
      const box = $('.refbox', tools.parentElement);
      if (box) box.value = r1.ref_label;
    }
    (r1.notices || []).forEach(n => body.appendChild(el('div', 'notice', esc(n))));
  },

  paint(r, m, body, opts, p) {
    body.innerHTML = '';
    if (r.section_title) {
      const h = el('div', 'docheading', esc(r.section_title));
      body.appendChild(h);
    }
    if (m.reader === 'verse') {
      // Clear any previously selected verse when the pane re-renders
      if (p) p.selectedVerse = null;
      const v = el('div', 'verses');
      r.items.forEach(it => {
        const sp = el('span', 'verse');
        /* data-label is the full reference -- "Gen 1:1", not "1".  The selection
         * card and the word list both need to cite where a selection came from,
         * and reading it off the element is the only way to be right when a
         * selection spans two verses or the pane is showing a merged set. */
        sp.dataset.label = it.label;
        sp.dataset.k = it.key;
        sp.innerHTML = '<a class="vnum" data-k="' + esc(it.key) + '">'
          + esc(it.label.split(' ').pop()) + '</a>' + it.html;
        sp.querySelector('.vnum').onclick = (e) => {
          e.stopPropagation();
          Popup.ref(m, it.key);
        };
        /* Click anywhere in the verse (except on the verse number, which opens
         * the popup) to select this verse for Study, Info, Compare, Visual Copy,
         * Copy, etc. */
        sp.onclick = () => {
          if (p) {
            p.selectedVerse = { key: it.key, label: it.label };
            document.querySelectorAll('.verse.selected').forEach(x => x.classList.remove('selected'));
            sp.classList.add('selected');
            toast('Selected ' + it.label);
          }
        };
        Reader.decorate(sp, m, it);
        Highlights.mark(sp, m.id, it.key, it.extra && it.extra.osis);
        /* A tagged verse says so.  A tag the reader cannot see is a tag they
         * will forget, and the point of tagging a passage rather than
         * highlighting it is that the tag outlives the translation. */
        const _tags = Tags.namesFor(it.extra && it.extra.osis);
        if (_tags.length) {
          sp.classList.add('vtag');
          sp.title = 'Tagged: ' + _tags.join(', ');
        }
        v.appendChild(sp);
      });
      body.appendChild(v);
      /* Notes anchored to a verse, marked on the verse itself.
       *
       * A note on John 3:16 is filed against that verse, so while you are
       * reading John 3 it should be *visible* there -- otherwise the note only
       * exists in the Notes screen and the reader has to remember which verse
       * it belongs to, which is the thing a note is for.  One request for the
       * whole pane rather than one per verse: a chapter is 31 requests on
       * every repaint otherwise, and this pane repaints on every step. */
      Reader.markNotes(v, m, r.items);
    } else if (r.kind === 'merge' || (r.versions && r.versions.length)) {
      Reader.merged(r, m, body);
    } else if (m.type === 'Audio' || m.reader === 'audio') {
      Reader.audio(r, m, body);
    } else if (m.type === 'Map' || m.type === 'Atlas') {
      Reader.map(r, m, body);
    } else if (m.reader === 'date') {
      const a = el('div', 'article');
      r.items.forEach(it => { a.appendChild(el('div', 'docheading', esc(it.title || it.label))); a.insertAdjacentHTML('beforeend', it.html); });
      body.appendChild(a);
    } else if (m.reader === 'article') {
      Reader.article(r, m, body);
    } else {
      const a = el('div', 'article');
      r.items.forEach(it => {
        if (it.title) a.appendChild(el('h1', '', esc(it.title)));
        a.insertAdjacentHTML('beforeend', it.html);
        Reader.decorate(a, m, it);
        Highlights.mark(a, m.id, it.key);
      });
      body.appendChild(a);
    }
    (r.notices || []).forEach(n => body.appendChild(el('div', 'notice', esc(n))));
    if (r.context && r.context.strongs && r.context.strongs.length) {
      const d = el('div', 'notice');
      d.innerHTML = '<b>Strong’s in this passage:</b> ' +
        r.context.strongs.map(s => '<a href="#" data-s="' + s.strongs + '">'
          + s.strongs + '</a>').join(' · ');
      d.onclick = (e) => {
        const a = e.target.closest('a[data-s]');
        if (a) { e.preventDefault(); Popup.strongs(a.dataset.s); }
      };
      body.appendChild(d);
    }
    if (r.context && r.context.xrefs && r.context.xrefs.length) {
      const d = el('div', 'notice');
      d.innerHTML = '<b>Cross-references:</b> ' +
        r.context.xrefs.slice(0, 20).map(k => '<a href="#" data-k="' + esc(k)
          + '">' + esc(k.replace('.', ' ').replace('.', ':')) + '</a>').join(' · ');
      d.onclick = (e) => {
        const a = e.target.closest('a[data-k]');
        if (a) { e.preventDefault(); Reader.focusRef(m, a.dataset.k); }
      };
      body.appendChild(d);
    }
  },

  /* An article-keyed resource: a lexicon, dictionary, encyclopaedia or
   * concordance.
   *
   * This used to be the generic branch -- heading, text, done -- which meant
   * that a reader inside one of these had exactly two ways to move: the search
   * box, which needs you to already know what is in there, and nothing else.
   * Webster has 114,712 entries, the Catholic Encyclopedia 10,049, Strong's
   * 14,199; none of them can be scrolled, and the server has been computing
   * the neighbouring entries this pane never asked for.
   *
   * So: a contents bar of what the resource contains, by letter or -- for a
   * concordance keyed by Strong's number, where an A-Z would be two letters --
   * by thousand, which is how the printed concordances are laid out; and the
   * previous and next entries either side of this one.
   */
  article(r, m, body) {
    const a = el('div', 'article');
    r.items.forEach(it => {
      if (it.title) a.appendChild(el('h1', '', esc(it.title)));
      a.insertAdjacentHTML('beforeend', it.html);
      Reader.decorate(a, m, it);
    });
    body.appendChild(a);

    const goto = (key) => {
      const p = S.layout.panes.find(x => x.is_focus) || S.layout.panes[0];
      if (!p) return;
      p.cursor = { key };
      Reader.reload(p, m);
    };

    /* Previous / next, from the neighbours the server already computes. */
    const ctx = r.context || {};
    const nb = ctx.before || [];
    const na = ctx.after || [];
    const nav = el('div', 'art-nav');
    const step = (label, list, dir) => {
      const b = el('button', 'btn tiny', label);
      b.disabled = !list.length;
      b.title = list.length ? (list[dir > 0 ? 0 : list.length - 1].title
        || list[dir > 0 ? 0 : list.length - 1].key) : 'nothing further';
      if (list.length) b.onclick = () => goto(list[dir > 0 ? 0 : list.length - 1].key);
      return b;
    };
    nav.appendChild(step('◀ previous', nb, -1));
    nav.appendChild(step('next ▶', na, 1));
    body.appendChild(nav);

    const idx = el('details', 'art-index');
    const sum = el('summary', 'st-head', 'Contents');
    idx.appendChild(sum);
    const slot = el('div', 'art-index-body');
    slot.innerHTML = '<div class="loading small">Loading…</div>';
    idx.appendChild(slot);
    body.appendChild(idx);
    const loadBucket = (bucket) => {
      api('article/index', { id: m.id, bucket: bucket || '' }).then(d => {
        if (!d || !d.ok) { slot.innerHTML = ''; return; }
        $$('.art-ab', slot).forEach(b => b.classList.toggle('on', b.dataset.b === d.bucket));
        const rows = (d.entries || []).map(e =>
          '<a href="#" class="art-ent" data-k="' + esc(e.key) + '">'
          + esc(e.title && e.title !== e.key ? e.title : e.key) + '</a>').join('');
        slot.innerHTML = (rows || '<div class="tiny muted">Nothing in this part.</div>')
          + (d.truncated ? '<div class="tiny muted">Showing the first '
            + (d.entries || []).length + ' of ' + d.total + '.</div>' : '');
        $$('.art-ent', slot).forEach(x => {
          x.onclick = (e) => { e.preventDefault(); goto(x.dataset.k); };
        });
      }).catch(() => { slot.innerHTML = ''; });
    };
    api('article/index', { id: m.id }).then(d => {
      if (!d || !d.ok) { idx.remove(); return; }
      const bar = el('div', 'art-ab-bar');
      (d.buckets || []).forEach(b => {
        const btn = el('button', 'art-ab' + (b.b === d.bucket ? ' on' : ''),
          b.b + ' <span class="muted">' + b.n + '</span>');
        btn.dataset.b = b.b;
        btn.onclick = () => loadBucket(b.b);
        bar.appendChild(btn);
      });
      slot.innerHTML = '';
      slot.appendChild(bar);
      loadBucket(d.bucket);
    }).catch(() => idx.remove());
  },

  merged(r, m, body) {
    /* One text, not a grid.  Wording every version shares reads as prose;
     * every point of disagreement is marked and opens to show each reading.
     * The whole passage is a single <audio>-free, scriptable block so it
     * selects and copies as normal text. */
    const vers = r.versions || [];
    const names = vers.map(v => v.abbrev || v.name);
    const head = el('div', 'merge-head');
    const agree = r.agreement === null || r.agreement === undefined
      ? '' : `<span class="ag">${r.agreement}% agreement</span>`;
    head.innerHTML = `<div class="h">${esc(r.ref || '')} ${agree}</div>`
      + `<div class="vs">${vers.map(v => esc(v.abbrev || v.name)).join(' · ')}</div>`;
    body.appendChild(head);

    const wrap = el('div', 'merged');
    (r.verses || []).forEach(v => {
      const p = el('div', 'mverse');
      const num = el('a', 'vnum', String(v.verse));
      num.href = '#';
      num.title = 'Open this verse in a Bible';
      num.onclick = (e) => { e.preventDefault(); Reader.openRefAnywhere(v.label); };
      p.appendChild(num);
      const t = el('span', 'mtext');
      (v.segments || []).forEach(seg => {
        if (seg.t === 'variant') {
          const s = el('span', 'mvar');
          s.textContent = seg.w;
          s.title = (seg.readings || [])
            .map(x => `${names[x.v] || x.v}: ${x.w}`).join('\n');
          const uniq = {};
          (seg.readings || []).forEach(x => { uniq[x.w] = names[x.v] || x.v; });
          s.onclick = (e) => {
            e.stopPropagation();
            const lines = (seg.readings || [])
              .map(x => `<div><b>${esc(uniq[x.w] || '')}</b> ${esc(x.w)}</div>`).join('');
            // Popup.show takes (html, x, y).  Passing the readings as the second
            // argument treated them as a pixel position and the popup showed
            // only the word.
            const r = s.getBoundingClientRect();
            Popup.hide();
            Popup.show(`<div class="mvarpop"><div class="mvhead">${
              esc(seg.w)}</div>${lines}</div>`,
              r.left + r.width / 2, r.bottom);
          };
          t.appendChild(s);
        } else {
          t.appendChild(document.createTextNode(seg.w + ' '));
        }
      });
      p.appendChild(t);
      if (v.agreement !== null && v.agreement !== undefined) {
        const a = el('span', 'vag', v.agreement + '%');
        a.title = v.variants + ' point(s) of disagreement in this verse';
        p.appendChild(a);
      }
      if (v.missing && v.missing.length) {
        const mz = el('span', 'vmiss', 'not in ' + v.missing.join(', '));
        mz.title = 'These translations do not contain this verse.';
        p.appendChild(mz);
      }
      wrap.appendChild(p);
    });
    body.appendChild(wrap);

    (r.notes || []).concat(r.caveat ? [r.caveat] : []).forEach(n =>
      body.appendChild(el('div', 'notice', esc(n))));
  },

  audio(r, m, body) {
    /* One <audio> element per recording, served from where the file already
       is.  The src is built from the stored id and key, never from a path, so
       the page can only reach what was registered. */
    const src = (it) => '/audio?id=' + encodeURIComponent(m.id)
      + '&key=' + encodeURIComponent(it.key);
    const ex_all = r.extra || {};
    const cues = ex_all.cues || {};
    const cueOrder = Object.keys(cues).sort((a, b) => cues[a][0] - cues[b][0]);
    const lic = ex_all.license || '';
    const wrap = el('div', 'audio-list');
    const head = el('div', 'audio-head');
    head.innerHTML = '<div class="h">Audio</div>'
      + (lic ? '<div class="lic">Licence: ' + esc(lic)
             + ' &middot; played from where the file already is</div>' : '');
    wrap.appendChild(head);

    /* A recording with no verse timings says so, in one line, rather than
       silently not following along -- "nothing happens" is indistinguishable
       from a broken feature. */
    if (ex_all.cue_note) {
      const n = el('div', 'audio-cues' + (cueOrder.length ? '' : ' is-none'),
        esc(ex_all.cue_note));
      wrap.appendChild(n);
    }

    /* The follow-along strip.  Every cued verse in order, so the reader can see
       where they are before pressing play, and so the current verse is a thing
       in a list rather than a colour that appears and vanishes. */
    let strip = null, marks = {}, current = null;
    if (cueOrder.length) {
      strip = el('div', 'audio-strip');
      cueOrder.forEach((k) => {
        const label = k.replace(/^([A-Za-z0-9]+)\./, '$1 ').replace(/\./g, ':');
        const b = el('button', 'audio-mark', label);
        b.title = 'Open ' + label;
        b.onclick = () => Reader._seekCue(m, k, cues, wrap);
        marks[k] = b;
        strip.appendChild(b);
      });
      wrap.appendChild(strip);
      const paint = (k) => {
        if (k === current) return;
        if (current && marks[current]) marks[current].classList.remove('on');
        current = k;
        if (!k || !marks[k]) return;
        marks[k].classList.add('on');
        marks[k].scrollIntoView({ block: 'nearest', inline: 'nearest' });
      };
      Reader._cuePaint = paint;
    } else {
      Reader._cuePaint = null;
    }

    if (!r.items || !r.items.length) {
      wrap.appendChild(el('div', 'empty', 'No audio files in this folder.'));
    }
    (r.items || []).forEach(it => {
      const ex = it.extra || {};
      const row = el('div', 'audio-row');
      const a = document.createElement('audio');
      a.controls = true;
      a.preload = 'none';
      a.src = src(it);
      a.setAttribute('data-key', it.key);
      /* Advance the strip as this file plays.  `timeupdate` is the only event a
         browser gives that fires often enough to look like following along, and
         the lookup is a binary search over a sorted list rather than a scan. */
      if (cueOrder.length) {
        a.addEventListener('timeupdate', () => {
          const t = a.currentTime;
          let lo = 0, hi = cueOrder.length - 1, at = -1;
          while (lo <= hi) {
            const mid2 = (lo + hi) >> 1;
            if (cues[cueOrder[mid2]][0] <= t + 0.25) { at = mid2; lo = mid2 + 1; }
            else hi = mid2 - 1;
          }
          if (at >= 0 && Reader._cuePaint) Reader._cuePaint(cueOrder[at]);
        });
        a.addEventListener('ended', () => {
          if (Reader._cuePaint) Reader._cuePaint(null);
        });
      }
      const meta = el('div', 'meta',
        esc(it.label || it.key)
        + '<span class="fn">' + esc(ex.name || '') + '</span>'
        + (ex.bytes ? '<span class="kb">' + Math.round(ex.bytes / 1024) + ' KB</span>' : ''));
      row.appendChild(a);
      row.appendChild(meta);
      if (ex.book) {
        const go = el('a', 'go', 'open ' + esc(it.label));
        go.href = '#';
        go.onclick = (e) => { e.preventDefault(); Reader.openRefAnywhere(it.label); };
        row.appendChild(go);
      }
      wrap.appendChild(row);
    });
    body.appendChild(wrap);
  },

  /* Click a verse in the strip.
   *
   * Two cases, and they are different enough to be worth naming.  With real cue
   * *times* the strip advances on its own, so clicking opens the verse in the
   * Bible and lets the reader follow on from there.  With one file per verse the
   * cues are all at zero -- the file's own reference is the boundary -- so
   * clicking also plays that file, which is the only thing that can make sense
   * of a zero-length cue.
   */
  _seekCue(m, osisKey, cues, wrap) {
    if (this._cuePaint) this._cuePaint(osisKey);
    const spaced = String(osisKey).replace(/\./g, ' ').replace(/ 1$/, '');
    const t = (cues[osisKey] || [])[0];
    if (t === 0 && wrap) {
      const a = Array.from(wrap.querySelectorAll('audio')).find(x =>
        (x.getAttribute('data-key') || '') === osisKey);
      if (a) { a.play(); return; }
    }
    Reader.openRefAnywhere(spaced);
  },

  /* Wrap tagged words in the already-rendered DOM, skipping anything that is
   * already a link, a button or inside a heading -- a tag inside a link breaks
   * it, and inside a heading it looks wrong. */
  applyTags(host, tags) {
    const words = tags.map(t => t.word).filter(w => w && w.length > 2);
    if (!words.length) return;
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (!n.nodeValue || n.nodeValue.length < 3) return NodeFilter.FILTER_REJECT;
        const p = n.parentElement;
        if (p && p.closest('a, button, .fb-tag, h1, h2, h3, h4, sup, .vnum'))
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    const re = new RegExp('\\b(' + words
      .map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')\\b', 'g');
    for (const node of nodes) {
      const txt = node.nodeValue;
      if (!re.test(txt)) continue;
      re.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0, m;
      const gloss = new Map(tags.map(t => [t.word.toLowerCase(), t]));
      while ((m = re.exec(txt))) {
        const word = m[0];
        if (m.index > last) frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
        const tag = gloss.get(word.toLowerCase()) || {};
        const sp = el('span', 'fb-tag', word);
        sp.title = (tag.gloss || '') + (tag.source ? '  \u2014 ' + tag.source : '');
        // `word` is a per-iteration const.  Reading `m[0]` in the handler closed
        // over the shared regex result instead, so by the time the span was
        // clicked `m` belonged to a later text node -- or was null, which threw
        // "Cannot read properties of null" and opened nothing.
        sp.onclick = (e) => { e.stopPropagation(); Study.openFact(word); };
        frag.appendChild(sp);
        last = m.index + word.length;
      }
      if (last < txt.length) frag.appendChild(document.createTextNode(txt.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
  },

  /* Mark the verses in a pane that carry one of your own notes.
   *
   * A note on John 3:16 is filed against that verse, so while you are reading
   * John 3 it should be *visible* there -- otherwise the note only exists in
   * the Notes screen and the reader has to remember which verse it belongs to,
   * which is the thing a note is for.  One request per distinct verse, and
   * skipped entirely for a pane too large for that to be worth doing: a whole
   * Bible would be 31,000 requests and nothing useful, so the cap says so
   * rather than quietly issuing them.
   *
   * A failure is swallowed.  Notes are an addition to the text; if the request
   * fails the verse is still readable and still highlightable, and a console
   * error about a marker is not something a reader can act on. */
  async markNotes(host, m, items) {
    if (!host || !m || !items || !items.length) return;
    const keys = [...new Set(items.map(i => i.key).filter(Boolean))];
    if (!keys.length || keys.length > 60) return;
    try {
      const found = await Promise.all(keys.map(k =>
        api('notes/at', { id: m.id, key: k })
          .then(r => (r.notes || []).map(n => [k, n]))
          .catch(() => [])));
      const byKey = new Map();
      found.flat().forEach(([k, n]) => {
        if (!byKey.has(k)) byKey.set(k, []);
        byKey.get(k).push(n);
      });
      if (!byKey.size) return;
      $$('.verse', host).forEach((sp) => {
        const rows = byKey.get(sp.dataset.k);
        if (!rows || !rows.length) return;
        const tag = el('button', 'notemark', String(rows.length));
        tag.title = rows.map(n => (n.title || '(untitled)') + ' — '
          + (n.kind || 'note')).join('\n');
        tag.onclick = (e) => {
          e.stopPropagation();
          Notes.showAt(sp.dataset.label, rows);
        };
        /* Appended, not prepended: the verse number is on the left and the text
         * follows it, so the one place a marker does not sit between the
         * reader and the first word is the end. */
        sp.appendChild(tag);
      });
    } catch (err) { /* a missing marker is not a broken pane */ }
  },
  decorate(host, m, it) {
    /* Strong's numbers -> lexicon popup */
    $$('.snum', host).forEach(a => {
      a.onclick = (e) => { e.stopPropagation(); Popup.strongs(a.dataset.s); };
    });
    /* footnote markers -> popup */
    $$('a.fn', host).forEach(a => {
      a.onclick = (e) => { e.stopPropagation(); Popup.note(a.dataset.note, a.title); };
    });
    /* auto-detect scripture references in the text */
    if (m.type !== 'Bible') {
      const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, null);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(n => {
        if (!n.nodeValue || n.nodeValue.length < 12) return;
        if (n.parentElement && n.parentElement.closest('a, mark, .snum')) return;
        const re = /\b(1|2|3)?\s?[A-Z][a-z]{1,9}\.?\s+\d{1,3}(?::\d{1,3})?(?:\s*[-–]\s*\d{1,3}(?::\d{1,3})?)?\b/g;
        if (!re.test(n.nodeValue)) return;
        const frag = document.createDocumentFragment();
        let last = 0; let mm;
        re.lastIndex = 0;
        while ((mm = re.exec(n.nodeValue))) {
          frag.appendChild(document.createTextNode(n.nodeValue.slice(last, mm.index)));
          const a = el('a', '', esc(mm[0]));
          a.href = '#';
          a.title = 'Open this reference';
          a.onclick = (e) => { e.preventDefault(); e.stopPropagation(); Reader.openRefAnywhere(mm[0]); };
          frag.appendChild(a);
          last = mm.index + mm[0].length;
        }
        frag.appendChild(document.createTextNode(n.nodeValue.slice(last)));
        n.parentNode.replaceChild(frag, n);
      });
    }
  },

  /* Follow a reference into a Bible, preferring one you can actually see.
   *
   * It used to take the first Bible in the catalogue, which is frequently not
   * the pane on screen: the cursor moved and the reader never changed, so
   * clicking a timeline, harmony or canon reference did nothing at all.  A
   * reference link that lands nowhere is worse than no link. */
  async openRefAnywhere(text) {
    const r = await api('reference', { ref: text });
    if (!r.ok) { toast('Cannot read that reference.', 'warn'); return; }

    const onScreen = new Set($$('.pane').map(x => x.dataset.pane).filter(Boolean));
    const panes = (S.layout && S.layout.panes) || [];
    const byId = (id) => S.modules.find(x => x.id === id);
    const isBible = (id) => { const m = byId(id); return m && m.is_bible; };

    // Which installed Bibles contain which books.  Fetched once, lazily; an
    // unknown list means "do not exclude", never "assume it is there".
    if (!S.bibleBooks) {
      S.bibleBooks = {};
      api('bible/books').then(x => { S.bibleBooks = x.books || {}; })
        .catch(() => {});
    }
    const contains = (id) => {
      const list = S.bibleBooks[id];
      return !list || !r.book || list.indexOf(r.book) >= 0;
    };

    /* Order of preference:
     *   1. a Bible already on screen that has the book
     *   2. any installed Bible that has it -- English and Strong's-tagged first,
     *      because catalogue order is arbitrary and the Study and Interlinear
     *      buttons need a tagged text
     *   3. a Bible on screen, book or no book
     * Following a link must land somewhere readable: opening Genesis 11 in a
     * New Testament shows an empty pane, which looks like a broken link. */
    const vis = panes.find(x => onScreen.has(x.id) && isBible(x.module_id)
                               && contains(x.module_id));
    let m = vis ? byId(vis.module_id) : null;
    if (!m) {
      const bibles = S.modules.filter(x => x.is_bible && contains(x.id));
      const score = (x) => (x.lang === 'eng' ? 2 : 0)
                         + (x.has_strongs || x.has_morph ? 1 : 0);
      m = bibles.sort((a, b) => score(b) - score(a))[0] || null;
    }
    if (!m) {
      const any = panes.find(x => onScreen.has(x.id) && isBible(x.module_id));
      m = any ? byId(any.module_id) : S.modules.find(x => x.is_bible);
    }
    if (m) Reader.focusRef(m, r.ref);
    else toast('No Bible is installed to follow that reference with.', 'warn');
  },

  async focusRef(m, ref) {
    const lay = S.layout || { panes: [] };
    const p = lay.panes.find(x => x.module_id === m.id);
    if (p) {
      p.cursor = { ref, span: (p.cursor && p.cursor.span) || 'chapter' };
      const pane = $('.pane[data-pane="' + p.id + '"]');
      if (pane) {
        // the pane may not be the active one in its tile
        App.showPane(p.tile_id || 't0', p.id);
        await App.fillPane(pane, p);
      } else {
        // its tile is not on screen at all: open the module where it can be seen
        await Workspace.openModule(m.id, { ref, span: 'chapter' });
        return;
      }
      this.save(p);
      return;
    }
    await Workspace.openModule(m.id, { ref, span: 'chapter' });
  },

  async reload(p, m) {
    const pane = $('.pane[data-pane="' + p.id + '"]');
    if (pane) await App.fillPane(pane, p);
  },

  /* Remember where a pane is.
   *
   * Navigation only ever changed p.cursor in the page, so the position was lost
   * on every restart and the dashboard's "continue where you left off" could
   * only ever say "not opened yet" -- true of the server's copy, and useless.
   * Debounced, because stepping through a chapter fires a lot of these. */
  save(p) {
    clearTimeout(p._saveT);
    p._saveT = setTimeout(() => {
      post('workspace/pane', { pane: p.id, cursor: p.cursor }).catch(() => {});
    }, 500);
  },

  /* Save the pane's cursor now, and wait for it.
   *
   * save() is debounced because dragging through a chapter fires it constantly
   * and each POST is wasted.  That is wrong when the next thing to happen is
   * App.loadWorkspace(): that re-reads the layout *from the server*, so a
   * debounced write still in flight is discarded and the pane is rebuilt with
   * the cursor it had before -- the new position is set in memory, visibly not
   * applied, and silently overwritten half a second later when the deferred
   * save does land.  Anything that rebuilds the layout after moving a pane has
   * to write first. */
  async saveNow(p) {
    clearTimeout(p._saveT);
    await post('workspace/pane', { pane: p.id, cursor: p.cursor });
  },

  async go(p, ref) {
    if (!ref) { p.cursor = {}; return this.reload(p, modById(p.module_id)); }
    if (p.cursor && p.cursor.span === undefined && modById(p.module_id) &&
        modById(p.module_id).reader === 'verse') p.cursor.span = 'chapter';
    const r = await api('reference', { ref });
    const m = modById(p.module_id);
    if (m && m.reader === 'verse') {
      if (r.ok) { p.cursor = Object.assign({}, p.cursor, { ref: r.ref }); }
      else p.cursor = Object.assign({}, p.cursor, { ref });
    } else {
      p.cursor = { key: ref, date: ref };
    }
    await this.reload(p, m);
    this.save(p);
    await Workspace.propagate(p);
  },

  async step(p, action) {
    const m = modById(p.module_id);
    const r = await api('read/around', { id: m.id, ref: p.cursor.ref, action });
    p.cursor = Object.assign({}, p.cursor, { ref: r.ref });
    await this.reload(p, m);
    this.save(p);
    await Workspace.propagate(p);
  },

  /* Re-render every open pane.  Adding or removing a highlight has to repaint
   * the text to show it, and there is no cheaper way than a redraw. */
  async repaint() {
    const panes = (S.layout && S.layout.panes) || [];
    for (const p of panes) {
      // Not every saved pane is on screen, and querySelector returns null for
      // those -- calling .querySelector on the null is what threw
      // "Cannot read properties of null (reading 'dataset')".
      const paneEl = document.querySelector('.pane[data-pane="' + p.id + '"]');
      if (!paneEl) continue;
      const body = paneEl.querySelector('.pane-body');
      if (body) await this.render(p, modById(p.module_id), body, null);
    }
  },

  async toggle(p, body, key, btn) {
    p.options = p.options || {};
    p.options[key] = !p.options[key];
    btn.classList.toggle('on', p.options[key]);
    await post('workspace/pane', { pane: p.id, options: p.options });
    await this.render(p, modById(p.module_id), body, $('.pane-tools', body.parentElement));
  },

  suggest(box, text) {
    const sug = $('#refsugg');
    if (!text) { sug.style.display = 'none'; return; }
    // The debounce can fire after the pane has been rebuilt, and then this box
    // is detached and closest('.pane') is null -- which threw
    // "Cannot read properties of null (reading 'dataset')" as soon as anyone
    // typed in the reference box and pressed Enter.
    const host = box.closest && box.closest('.pane');
    if (!host) { sug.style.display = 'none'; return; }
    const panes = (S.layout && S.layout.panes) || [];
    const mine = panes.find(p => p.id === host.dataset.pane) || {};
    const m = modById(box.dataset.module || mine.module_id);
    if (!m) { sug.style.display = 'none'; return; }
    const r = fetch('/api/suggest?q=' + encodeURIComponent(text), {
      headers: { 'X-GBible-CSRF-Token': CSRF_TOKEN },
    }).then(x => x.json()).catch(() => {});
    r.then((d) => {
      const list = (d.suggestions || []);
      if (!list.length) { sug.style.display = 'none'; return; }
      sug.innerHTML = '';
      list.forEach(s => {
        const n = el('div', '', esc(s.label));
        n.onclick = () => {
          const ref = s.insert || s.label;
          box.value = ref;
          sug.style.display = 'none';
          // Go there.  This only filled the box, so clicking a suggestion left
          // the reader exactly where it was and looked like a dead control.
          const pane = box.closest('.pane');
          const p = pane ? S.layout.panes.find(x => x.id === pane.dataset.pane) : null;
          if (p) Reader.go(p, ref);
          else box.focus();
        };
        sug.appendChild(n);
      });
      const b = box.getBoundingClientRect();
      sug.style.left = b.left + 'px';
      sug.style.top = (b.bottom + 2) + 'px';
      sug.style.display = 'block';
    });
  },

  map(r, m, body) {
    const it = r.items[0] || {};
    const ex = it.extra || {};
    const h = el('div', 'docheading', esc(it.title || it.label || ''));
    body.appendChild(h);
    if (ex.lat && ex.lon) {
      /* The interactive map, not the static embed.
       *
       * The embed showed one fixed tile box with no way to pan or zoom, which
       * answers "where is this" and nothing else -- you could not move one
       * degree to see what was next to it, which for a gazetteer of a river or
       * a valley is the whole question.  An atlas pane with every place on one
       * map is the same data arranged so places can be found *relative* to
       * each other. */
      const host = el('div', 'atlas-map');
      body.appendChild(host);
      const lat0 = Number(ex.lat), lon0 = Number(ex.lon);
      /* Neighbours, computed here from the gazetteer rather than asked for: 334
       * places is nothing to filter, and a "what is near this" round trip is
       * a request the reader did not know the application needed to make. */
      const near = [];
      api('places', { limit: 400 }).then(all => {
        (all.places || []).forEach(p => {
          if (p.id === ex.id || !isFinite(p.lat) || !isFinite(p.lon)) return;
          const dx = (p.lon - lon0) * Math.cos(lat0 * Math.PI / 180);
          const dy = p.lat - lat0;
          const km = Math.hypot(dx, dy) * 111;
          if (km < 220) near.push({ ...p, km });
        });
        near.sort((a, b) => a.km - b.km);
        const keep = near.slice(0, 60);
        if (Atlas._st && !keep.some(k => k.id === ex.id)) {
          keep.forEach(p => Atlas._st.markers.push({
            lat: p.lat, lon: p.lon, label: p.name,
            onPick: () => {
              const s = Atlas._st;
              if (s) { s.cx = p.lon; s.cy = p.lat; Atlas.draw(); }
              toast(p.name + ' — ' + Math.round(p.km) + ' km away');
            },
          }));
          Atlas.draw();
          if (!host.querySelector('.atlas-near')) {
            const lab = el('div', 'atlas-near tiny muted',
              keep.length + ' other named places within 220 km');
            host.appendChild(lab);
          }
        }
        const allBtn = el('button', 'btn tiny', 'All ' + (all.total || 0)
          + ' places on one map');
        allBtn.onclick = () => {
          const box = el('div');
          body.appendChild(box);
          Atlas.showAtlas(box);
        };
        body.appendChild(allBtn);
      }).catch(() => {});
      const markers = [{
        lat: lat0, lon: lon0, label: it.title || it.label, color: '#3f8f4f',
        onPick: () => {},
      }];
      Atlas.mount(host, markers, { lat: lat0, lon: lon0, z: 8, height: 360 });
      const a = el('a', 'tiny', 'Open in OpenStreetMap ↗');
      a.href = 'https://www.openstreetmap.org/?mlat=' + ex.lat
        + '&mlon=' + ex.lon + '#map=13/' + ex.lat + '/' + ex.lon;
      a.target = '_blank'; a.rel = 'noopener';
      body.appendChild(a);
      /* The one place a reader is most likely to want a photograph: a place
       * card.  The modern name, not the biblical one, because the photographs
       * that exist are of the place that is still there. */
      const pics = el('button', 'btn tiny', 'Find pictures of '
        + (it.title || it.label || 'this place'));
      pics.onclick = () => Media.openWith(it.title || it.label || '');
      body.appendChild(pics);
    } else {
      body.appendChild(el('div', 'notice', 'No coordinates for this place.'));
    }
    if (it.text) body.appendChild(el('div', 'article', esc(it.text)));
    const refs = ex.passages || [];
    if (refs.length) {
      const d = el('div', 'notice');
      d.innerHTML = '<b>Passages:</b> ' + refs.slice(0, 24).map(k => {
        const lbl = k.replace(/^([A-Za-z0-9]+)\./, '$1 ').replace(/\./g, ':');
        return '<a href="#" data-k="' + esc(k) + '">' + esc(lbl) + '</a>';
      }).join(' · ');
      d.onclick = (e) => {
        const a = e.target.closest('a[data-k]');
        if (a) {
          e.preventDefault();
          const p = S.layout.panes.find(x => x.is_focus) || S.layout.panes[0];
          p.cursor = { ref: a.dataset.k.replace('.', ' ').replace('.', ':'), span: 'chapter' };
          Reader.reload(p, modById(p.module_id));
        }
      };
      body.appendChild(d);
    }
    if (it.extra && it.extra.image) {
      const img = el('img', '');
      /* The file lives in the module's own folder under data/modules, so the
       * URL needs that folder in it.  extra.image is the bare filename the
       * importer recorded, and asking for /media/<filename> resolved one
       * directory above data/modules -- which 404s for all four maps.
       * m.folder is the directory name and happens to equal m.id for these,
       * but the folder is what the route actually wants. */
      img.src = '/media/' + (m.folder || m.id) + '/' + it.extra.image;
      img.onerror = () => {
        img.replaceWith(el('div', 'notice',
          'The image file is missing from this module\'s folder. Re-index the '
          + 'module to restore it.'));
      };
      img.alt = it.title || it.label || '';
      img.style.maxWidth = '100%';
      body.appendChild(img);
    }
  },
};

/* ============================================================== Popup */
/* ================================================================ Study */
/* One verse, or one word, and everything installed that bears on it.
 *
 * This is the panel that replaces "which tool do I open next".  Commentary,
 * cross-references, topics, places and the word list are fetched in a single
 * call and grouped here, so opening a verse shows the same information some
 * platforms assemble from the resources you own.
 */
/* ----------------------------------------------------------- Cite/Publish --
 * Citations, bibliographies, print and export.
 *
 * The screen that matters is the citation dialog, and the part of it that
 * matters is the strip that says which fields are missing.  Almost nothing in
 * this library has an author or a year recorded, so a citation that looked
 * finished would be finished by invention.  The missing fields are shown, and
 * they can be filled in once, and every later citation for that work is then
 * right.
 */