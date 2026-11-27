/* First-run tour. Shows once per library, on request or a fresh browser, and
   then never again. No dependencies — one overlay, plain DOM. */

const Tour = {
  steps: [
    { target: null, title: "Welcome to G-Bible",
      body: "G-Bible is a Bible study workspace that lives on your computer: your Bibles, reference works, maps, notes and plans, all beside each other. This one-minute tour shows you the map. It won't appear again.",
      next: "Show me around" },
    { target: '#nav button[data-view="today"]', title: "Home — your study day",
      body: "Opening G-Bible brings you here: your reading plan for today, your most recent highlights and notes, and your prayer list. It's the brief before you start, not a requirement." },
    { target: '#nav button[data-view="workspace"]', title: "Workspace — where you read",
      body: "The heart of the app: a grid of study panes. Open a Bible, a commentary, a lexicon — as many as you want, side by side. Right-click a pane and choose 'Split this pane' to add one beside it." },
    { target: '#nav button[data-view="search"]', title: "Search — all of your library",
      body: "Search across every resource you have installed: a word, a phrase, a Strong's number (e.g. G0026). Search understands the texts' original-language markup, not just plain text." },
    { target: '#nav button[data-view="guides"]', title: "Guides — understand a passage deeply",
      body: "Passage guide and topic guide: outlines, context, cross-references and resources for any passage. Guides are a good first stop, especially when you're preparing a sermon or a lesson." },
    { target: '#nav .menu-btn[data-menu="tools"]', title: "Study tools — underneath the heavy lifting",
      body: "Concordance, word lists, text comparison, visual filters, maps and more. Print and export live where they make sense (notes, sermons, drawings, canvas). You don't need these on day one — but they're here when study gets serious." },
    { target: '#nav .menu-btn[data-menu="documents"]', title: "My study — everything you make",
      body: "Notes, highlights, favourites, collections, canvas, prayer lists, memorisation, reading plans, devotionals and sermon management. The best of your study is kept here, on your own machine." },
    { target: '#nav .menu-btn[data-menu="library"]', title: "Library — your books and the Store",
      body: "My library is everything you've installed. Resource store is where it came from: the Store catalogue is curated and only offers works that are freely redistributable — public-domain editions and clearly licensed open data." },
    { target: '#nav .menu-btn[data-menu="settings"]', title: "Settings — configure carefully",
      body: "Appearance, synchronisation, read-aloud, the AI Assistant, and Passage guide configuration. Two honest notes: sync is still settling (only sync folders you trust), and the AI Assistant is opt-in — enable it in Settings → AI Assistant if you want it. It's a research aid, not a pope." },
    { target: null, title: "You're ready",
      body: "That's the whole tour. Nothing here will annoy you again — it is a one-time hello. When you want a slower reminder later, the docs folder has the getting-started guide this tour is based on.",
      final: true },
  ],

  el: null, idx: 0, layer: null, dim: null, card: null,

  async maybeStart() {
    try {
      const r = await api('tour/status');
      if (r && r.seen) return;             /* already taken — non-blocking */
    } catch (e) {
      return; /* never block the app on the tour's storage check */
    }
    return this.start(0);
  },

  start(i) {
    return new Promise((resolve) => {
      this._resolve = resolve;
      this.idx = i || 0;
      if (!this.el) this.build();
      this.el.hidden = false;
      this.show(this.idx);
    });
  },

  build() {
    this.el = el('div', 'tour-layer', '');
    this.el.innerHTML = '<div class="tour-hole"></div><div class="tour-card"></div>';
    this.card = this.el.querySelector('.tour-card');
    this.dim = this.el.querySelector('.tour-hole');
    $('#app').appendChild(this.el);

    this.card.addEventListener('click', (e) => {
      const t = e.target.closest('[data-tour]');
      if (t) {
        const act = t.dataset.tour;
        if (act === 'next') this.next();
        else if (act === 'prev') this.prev();
        else if (act === 'skip') this.skip();
        else if (act === 'final') this.finish();
      }
    });

    window.addEventListener('resize', () => this.show(this.idx));
    document.addEventListener('keydown', (e) => {
      if (!this.el || this.el.hidden) return;
      if (e.key === 'Escape') { this.finish(); }
      else if (e.key === 'ArrowRight') { this.next(); }
      else if (e.key === 'ArrowLeft') { this.prev(); }
    });
  },

  async show(i) {
    const n = this.steps.length;
    if (i < 0 || i >= n) i = n - 1;   // clamp, never loop forever
    this.idx = i;
    const s = this.steps[i];
    const dots = this.steps.map((_, k) =>
      '<button class="td' + (k === i ? ' on' : '') + '" data-k="' + k + '" aria-label="Step ' + (k + 1) + ' of ' + n + '"></button>'
    ).join('');
    const actions = (s.final
      ? '<button class="tour-next" data-tour="final">Done</button>'
      : '<button class="tour-skip" data-tour="skip">Skip tour</button>' +
        '<button class="tour-next" data-tour="next">' + (s.next || 'Next') + '</button>');
    this.card.innerHTML = '<h3>' + esc(s.title) + '</h3><p>' + esc(s.body) + '</p>'
      + '<div class="tour-dots">' + dots + '</div>'
      + '<div class="tour-foot">' + actions + '</div>';
    this.card.querySelectorAll('.tour-dots .td').forEach(d => {
      d.addEventListener('click', () => this.show(parseInt(d.dataset.k, 10)));
    });

    /* Position the hole over the target, or centre the card when there is no target. */
    if (s.target) {
      const elTarget = document.querySelector(s.target);
      if (elTarget) {
        const r = elTarget.getBoundingClientRect();
        const pad = 6;
        this.dim.hidden = false;
        this.dim.style.top = (r.top - pad) + 'px';
        this.dim.style.left = (r.left - pad) + 'px';
        this.dim.style.width = (r.width + pad * 2) + 'px';
        this.dim.style.height = (r.height + pad * 2) + 'px';
        this.dim.style.display = 'block';
      } else {
        this.dim.hidden = true;
      }
    } else {
      this.dim.hidden = true;
    }

    /* Place the card below the hole by default, swap to above if it doesn't fit. */
    const cr = this.card.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    if (s.target) {
      const elTarget = document.querySelector(s.target);
      const r = elTarget.getBoundingClientRect();
      const cardH = 150, gap = 14;
      let top = r.bottom + gap;
      if (top + cardH > vh) top = r.top - gap - cardH;
      let left = Math.round(r.left + (r.width / 2) - 170);
      left = Math.max(10, Math.min(vw - 350, left));
      this.card.style.top = top + 'px';
      this.card.style.left = left + 'px';
    } else {
      this.card.style.top = '12vh';
      this.card.style.left = Math.round((vw - 350) / 2) + 'px';
    }
  },

  next() { this.show(this.idx + 1); },
  prev() { this.show(this.idx - 1); },

  end(skip) {
    if (this.el) { this.el.hidden = true; }
    post('tour/seen').catch(() => {});
    /* Release any boot code waiting for the tour to finish. */
    if (this._resolve) { const r = this._resolve; this._resolve = null; r(); }
    if (!skip) toast('Tour complete — enjoy your study.', 'ok');
  },

  finish() { this.end(false); },
  skip() { this.end(true); },
};
