const Preach = {
  on: false,
  paneId: '',
  saved: null,
  font: 'serif',
  size: 1.9,
  paging: false,
  timer: { left: 0, total: 20 * 60, running: false, started: false, id: 0 },
  bar: null,
  ref: null,
  idle: 0,

  /* Which pane is on the stage.  The active one if there is one, otherwise the
   * first pane with something in it -- an empty workspace should say so rather
   * than open a black screen. */
  target() {
    const panes = (S.layout && S.layout.panes) || [];
    if (!panes.length) return null;
    const shown = $('.pane[data-pane]');
    if (shown && shown.dataset.pane) {
      const p = panes.find(x => x.id === shown.dataset.pane);
      if (p) return p;
    }
    return panes[0];
  },

  async enter() {
    if (this.on) return;
    const pane = this.target();
    if (!pane) { toast('Open a Bible first — there is nothing to preach from.'); return; }
    const m = modById(pane.module_id);
    if (!m) { toast('That pane has no resource open.', 'warn'); return; }

    this.on = true;
    this.paneId = pane.id;
    /* Hide the other tiles rather than the other panes: a tile can hold several
     * tabs, and hiding the tile hides whichever of them is showing. */
    const tileId = App.tileKey(pane.tile_id);
    const tile = $('.tile[data-tile="' + tileId + '"]');
    $$(`.tile[data-tile]`).forEach(t => {
      if (t !== tile) t.dataset.preachHide = '1';
    });
    /* The chosen pane may not be the visible tab of its tile.  showPane() is
     * async because it repaints, so the class goes on now and the bar is built
     * only once the pane is actually there. */
    document.body.classList.add('preaching', this.font);
    await App.showPane(tileId, pane.id);
    /* Read the size off the pane *after* the repaint: showPane replaces the
     * layout's pane object, and the size that is really on screen is the one
     * in the new one. */
    const shown = (S.layout.panes || []).find(x => x.id === pane.id) || pane;
    this.saved = { textSize: shown.text_size || 100 };
    if (shown.text_size) {
      this.size = Math.round(shown.text_size / 100 * 1.9 * 10) / 10;
    }
    document.documentElement.style.setProperty('--preach-size', this.size + 'rem');
    this.build(m, shown);
    this.bind();
    if (document.documentElement.requestFullscreen) {
      /* Fullscreen is a request, not a command: it can be refused, and a
       * refusal is not an error worth reporting.  Preaching mode works
       * without it -- it is already a full-window surface. */
      document.documentElement.requestFullscreen().catch(() => {});
    }
    this.applyPaging();
  },

  exit() {
    if (!this.on) return;
    this.on = false;
    document.body.classList.remove('preaching', 'serif', 'sans', 'mono');
    $$(`.tile[data-preach-hide]`).forEach(t => { delete t.dataset.preachHide; });
    if (this.bar) { this.bar.remove(); this.bar = null; }
    if (this.ref) { this.ref.remove(); this.ref = null; }
    clearInterval(this.timer.id);
    /* The idle timer had `this.bar.classList.add('idle')` inside it, and it
     * outlived the bar: leave preaching mode, and up to four seconds later the
     * timer fired on a null bar and threw "Cannot read properties of null
     * (reading 'classList')" -- an uncaught error in the console of whatever
     * the reader opened next.  Cancel it, and check anyway, because a timer
     * already queued cannot be called back. */
    clearTimeout(this.idle);
    this.timer.running = false;
    document.removeEventListener('mousemove', this._wake);
    document.removeEventListener('keydown', this._keys, true);
    if (this.saved && this.paneId) {
      const p = (S.layout.panes || []).find(x => x.id === this.paneId);
      if (p) p.text_size = this.saved.textSize;
    }
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    /* The reader pane was hidden by hiding its tile, and by showPane() above the
     * layout object may name a different pane now.  Repaint from the layout so
     * what comes back is what was there. */
    App.renderWorkspace();
  },

  toggle() { this.on ? this.exit() : this.enter(); },

  build(m, pane) {
    const ref = el('div', '', '');
    ref.id = 'preach-ref';
    const label = (pane.cursor && pane.cursor.ref) || '';
    ref.innerHTML = (label ? '<b>' + esc(label) + '</b>' : '')
      + '<span class="mod">' + esc(m.name) + '</span>';
    document.body.appendChild(ref);
    this.ref = ref;

    const bar = el('div', '');
    bar.id = 'preach-bar';
    const b = (label, fn, cls) => {
      const x = el('button', cls || '', label);
      x.onclick = fn;
      bar.appendChild(x);
      return x;
    };
    b('Prev', () => this.step(-1));
    b('Next', () => this.step(1));
    bar.appendChild(el('span', 'sep'));
    const paging = b('Paging', () => {
      this.paging = !this.paging;
      paging.classList.toggle('on', this.paging);
      this.applyPaging();
    });
    paging.classList.toggle('on', this.paging);
    bar.appendChild(el('span', 'sep'));
    ['serif', 'sans', 'mono'].forEach(f => {
      const x = b(f[0].toUpperCase() + f.slice(1), () => {
        this.font = f;
        document.body.classList.remove('serif', 'sans', 'mono');
        document.body.classList.add(f);
        $$(`#preach-bar button[data-font]`).forEach(z => z.classList.remove('on'));
        x.classList.add('on');
        x.dataset.font = f;
      });
      x.dataset.font = f;
      if (f === this.font) x.classList.add('on');
    });
    bar.appendChild(el('span', 'sep'));
    const sizes = el('input');
    sizes.type = 'range'; sizes.min = '1'; sizes.max = '3.4'; sizes.step = '0.1';
    sizes.value = String(this.size);
    sizes.title = 'Type size';
    sizes.oninput = () => {
      this.size = parseFloat(sizes.value);
      document.documentElement.style.setProperty('--preach-size', this.size + 'rem');
    };
    bar.appendChild(sizes);
    bar.appendChild(el('span', 'sep'));
    const clock = el('span', '', '0:00');
    clock.id = 'preach-timer';
    bar.appendChild(clock);
    b('20m', () => this.setTimer(20 * 60));
    b('40m', () => this.setTimer(40 * 60));
    b('60m', () => this.setTimer(60 * 60));
    const go = b(this.timer.running ? 'Stop' : 'Start', () => this.runTimer());
    go.id = 'preach-timer-go';
    bar.appendChild(el('span', 'sep'));
    b('Copy', () => this.copyText());
    b('Citation', () => {
      const p = (S.layout.panes || []).find(x => x.id === this.paneId);
      Cite.copy(p ? p.module_id : '', (p && p.cursor && p.cursor.ref) || '');
    });
    bar.appendChild(el('span', 'sep'));
    b('Close  (Esc)', () => this.exit());
    document.body.appendChild(bar);
    this.bar = bar;
    this.pointer = null;
    this.clock = clock;
    this.paint();
  },

  setTimer(seconds) {
    this.timer.total = seconds;
    this.timer.left = seconds;
    /* Choosing a length resets the run: the clock goes back to counting down
       from the new figure rather than staying at zero from the last one. */
    this.timer.started = false;
    this.paint();
  },

  runTimer() {
    const t = this.timer;
    t.running = !t.running;
    const go = $('#preach-timer-go');
    if (go) go.textContent = t.running ? 'Stop' : 'Start';
    clearInterval(t.id);
    if (t.running) {
      if (!t.left) t.left = t.total;
      t.started = true;
      t.id = setInterval(() => {
        t.left = Math.max(0, t.left - 1);
        this.paint();
        if (!t.left) { this.runTimer(); toast('Time.', 'warn'); }
      }, 1000);
    }
    this.paint();
  },

  paint() {
    if (!this.clock) return;
    /* Show what is left, not `left || total`.

       `0 || 20` is 20, so the moment the timer reached zero the display went
       back to the full twenty minutes -- in red, which made it look like a
       deliberate state -- while the person holding it could not tell it had
       run out.  Once a run has begun the remaining time is the only honest
       thing to show, and zero stays zero. */
    const t = this.timer;
    const s = t.started ? (t.left || 0) : t.total;
    const m = Math.floor(s / 60), r = s % 60;
    this.clock.textContent = m + ':' + String(r).padStart(2, '0');
    this.clock.style.color = t.running ? 'var(--accent)'
      : (t.started && !t.left ? 'var(--red)' : 'var(--fg-3)');
  },

  /* Paging puts one verse on the screen at a time; scrolling is a continuous
   * document.  Paging is what a pulpit wants, and it is the reason this mode
   * exists rather than just making the type bigger. */
  applyPaging() {
    const bodies = $$('.pane-body');
    if (!bodies.length) return;
    bodies.forEach(b => {
      /* Paging turns off smooth scrolling: with it on, an arrow key animates
       * through the gap between verses instead of cutting to the next one. */
      b.style.scrollBehavior = this.paging ? 'auto' : '';
      if (!this.paging) {
        $$('.verse', b).forEach(v => {
          v.style.display = '';
          v.classList.remove('on');
        });
      }
    });
    if (this.paging) this.page(0);
  },

  page(n) {
    const body = $('.pane-body');
    const verses = $$('.verse', body || document);
    if (!verses.length) return;
    const i = Math.max(0, Math.min(verses.length - 1, n));
    verses.forEach((v, k) => {
      v.style.display = k === i ? '' : 'none';
      v.classList.toggle('on', k === i);
    });
    this.pageIndex = i;
    const r = this.ref;
    if (r) {
      const lab = verses[i].querySelector('.vnum');
      const txt = lab ? lab.textContent : '';
      r.innerHTML = '<b>' + esc(txt || '') + '</b>';
    }
  },

  step(d) {
    if (!this.paging) {
      const body = $('.pane-body');
      if (body) body.scrollBy({ top: d * body.clientHeight * 0.85,
                                 behavior: 'smooth' });
      return;
    }
    this.page((this.pageIndex || 0) + d);
  },

  async copyText() {
    const body = $('.pane-body');
    if (!body) return;
    const on = $('.verse.on', body);
    const html = on ? on.innerText : body.innerText;
    try {
      await navigator.clipboard.writeText(String(html || '').trim());
      toast('Copied.');
    } catch (e) {
      modal('Copy', '<textarea class="ct-out" rows="10">'
        + esc(String(html || '').trim()) + '</textarea>',
        [{ label: 'Close', cls: 'btn' }]);
    }
  },

  /* The bar fades out of the way so it is not in the photograph, and comes
   * back on any key or mouse movement.  It must not fade out *while the
   * pointer is on it*: `idle` also sets `pointer-events: none`, so a reader
   * who reached for Citation, hesitated, and then clicked found dead buttons
   * and no way to wake them without moving away and back.  Four seconds
   * rather than two and a half, because a deliberate reach is slower than a
   * flick of the wrist. */
  wake(e) {
    if (!this.bar) return;
    if (e && e.clientX !== undefined) this.pointer = { x: e.clientX, y: e.clientY };
    this.bar.classList.remove('idle');
    clearTimeout(this.idle);
    this.idle = setTimeout(() => {
      if (!this.bar) return;
      if (this._pointerOnBar()) { this.wake(); return; }
      this.bar.classList.add('idle');
    }, 4000);
  },

  /* Where is the pointer, as far as the bar is concerned?

   * Read from the last mouse position rather than from pointerenter and
   * pointerleave.  Those fire on hit-testing, and a bar that is mid-fade has
   * `pointer-events: none` -- so the move that wakes it is a move the bar
   * never sees, and it faded back out with the pointer resting squarely on the
   * Copy button and no way to click it.  Comparing coordinates works whatever
   * order the events arrive in. */
  _pointerOnBar() {
    const p = this.pointer;
    if (!p || !this.bar) return false;
    const r = this.bar.getBoundingClientRect();
    return p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom;
  },

  onKey(e) {
    if (!this.on) return;
    /* A modal owns the keyboard while it is up.

     * Escape is handled twice over: a document-level listener closes the modal
     * and this one exits preaching.  Both ran on the same keypress, so opening
     * Citation -- or Copy, whose clipboard write can fail and fall back to a
     * textarea -- and pressing Escape to dismiss it dropped the reader out of
     * preaching as well, back into the workspace, at the wrong verse, with the
     * window rearranged.  Same for the arrows: they paged behind the dialog. */
    const modalUp = $('#modal-bg') && $('#modal-bg').classList.contains('on');
    if (modalUp) return;
    if (e.key === 'Escape') { e.preventDefault(); this.exit(); return; }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    /* Arrows page.  Some platforms use down/right and up/left, and so does this --
     * except in paging mode where the space bar also turns the page, because
     * the person holding it is holding a book in the other hand. */
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(e.key)) {
      e.preventDefault(); this.step(1);
    }
    if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) {
      e.preventDefault(); this.step(-1);
    }
    if (e.key === 'f' || e.key === 'F') {
      const p = (S.layout.panes || []).find(x => x.id === this.paneId);
      if (p) Reader.focusRef(p, '', '');
    }
  },

  /* Bound listeners need stable identities so `exit()` can remove exactly what
   `enter()` added.  They get their own names rather than shadowing the methods
   they call: `this.wake = () => this.wake()` looks like a harmless wrapper and
   is not -- the assignment replaces the method, so the arrow calls itself,
   every mouse move overflows the stack, and the key handler never gets as far
   as Escape.  Preaching mode then had to be closed with the button, because the
   key that was supposed to close it was busy recursing. */
  bind() {
    this._wake = (e) => this.wake(e);
    this._keys = (e) => this.onKey(e);
    document.addEventListener('mousemove', this._wake);
    /* Capture, not bubble.  There is a document-level Escape handler that
     * closes modals, registered when the page loaded -- so before preaching
     * mode starts.  On Escape it runs first, the modal is already closed by
     * the time a bubble-phase handler looks, and a handler asking "is a modal
     * open?" at that point is always told no.  In the capture phase this
     * handler runs before it, so the question has an answer. */
    document.addEventListener('keydown', this._keys, true);
    this.wake();
  },
};

/* ====================================================== selection cards ===
   Select text, get a card: the quotation, where it is, and the citation you
   would paste into a footnote.

   Some platforms call this the Selection Menu and put it behind a right-click; the
   useful part is that the citation is built for you, with the licence attached,
   which is the step everybody gets wrong.  Here it appears on its own when you
   finish selecting inside a reading pane -- no click, so no menu to dismiss,
   and nothing is written to the database until you ask.

   The card is a card and not a quotation: it can be copied whole, cited, turned
   into a note, or added to a word list.  What it will not do is guess.  A
   selection that spans two verses is reported as spanning two verses.          */