const Speech = {
  on: false,
  rate: 1.0,
  voice: '',
  _watch: null,
  _mode: null,         // null until asked: 'server' or 'browser'
  _audio: null,        // the <audio> the server voice plays through
  _blob: null,         // its object URL, revoked once the verse is done
  _playing: null,      // resolves the current _play() when stop() cuts in
  _abort: null,
  _seq: 0,             // bumped by stop(), so late replies are thrown away
  _pane: null,         // the pane currently being read aloud
  _lines: [],          // same items, trimmed, used so verse highlighting matches spoken text

  settingsKey: 'gbible:read-aloud-settings',
  _loadedSettings: false,
  _settings: null,
  _engine: 'auto',
  _localVoice: '',
  _browserVoice: '',

  defaults() {
    /* Auto is the default: use the installed voice when there is one, fall
     * back to the browser's own voice otherwise.  Browser/local choice is here
     * because an app should not ask the user which one they want before the
     * content loads at all. */
    return { engine: 'auto', speed: this.rate, localVoice: '', browserVoice: '' };
  },

  loadSettings() {
    if (this._loadedSettings) return this._settings;
    let s = this.defaults();
    try {
      const raw = localStorage.getItem(this.settingsKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') {
          s = Object.assign(s, parsed);
        }
      }
    } catch (e) {}
    this._settings = s;
    this._loadedSettings = true;
    return s;
  },

  applySettings(s) {
    this._settings = s;
    this._loadedSettings = true;
    this.rate = Number(s.speed || 1);
    this._engine = s.engine || 'auto';
    this._localVoice = s.localVoice || '';
    this._browserVoice = s.browserVoice || '';
    try { localStorage.setItem(this.settingsKey, JSON.stringify(s)); } catch (e) {}
    /* The current mode should follow the selected engine -- auto/server/browser
     * -- instead of a stale choice from before the settings were saved. */
    if (this._engine === 'server') this._mode = 'server';
    else if (this._engine === 'browser') this._mode = 'browser';
    else this._mode = null;
  },

  engineLabel(engine) {
    if (engine === 'server') return 'Installed local voice';
    if (engine === 'browser') return 'Browser / computer voice';
    return 'Auto (local if available, browser otherwise)';
  },

  async showSettings() {
    /* Fetch the voice choices before opening the dialog.  tts/status reports
     * available installed voices, and browser voices come from the browser. */
    let serverVoices = [];
    let serverVoice = '';
    let voiceAvailable = false;
    let voiceReason = '';
    try {
      const st = await api('tts/status');
      serverVoices = st.voices || [];
      serverVoice = st.voice || '';
      voiceAvailable = !!(st && st.available);
      voiceReason = (st && st.reason) || '';
    } catch (e) {}

    let browserVoices = [];
    try {
      if ('speechSynthesis' in window) {
        browserVoices = await new Promise(resolve => {
          const seen = () => resolve(speechSynthesis.getVoices() || []);
          const direct = speechSynthesis.getVoices() || [];
          if (direct.length) return resolve(direct);
          let tries = 0;
          const iv = setInterval(() => {
            tries += 1;
            const v = speechSynthesis.getVoices() || [];
            if (v.length || tries > 4) { clearInterval(iv); resolve(v); }
          }, 400);
        });
      }
    } catch (e) {}

    const s = this.loadSettings();
    const engOpts = [
      ['auto', 'Auto (installed voice first, browser otherwise)'],
      ['server', 'Installed local voice (recommended)'],
      ['browser', 'Computer / browser voice'],
    ];
    const localOpts = serverVoices.length
      ? serverVoices.map(v => [v, v])
      : [[serverVoice || '', serverVoice || 'Default']];
    const browserOpts = [''].concat(browserVoices.map(v => v.name));

    modal('Read aloud settings', '' +
      '<div class="st-body" style="margin-bottom:6px">Choose how the app reads aloud and how fast it speaks.</div>'
      + '<label class="st-lbl">Engine</label>'
      + '<select id="rs-engine">' + engOpts.map(o =>
          '<option value="' + o[0] + '"' + (o[0] === (s.engine || 'auto') ? ' selected' : '') + '>' + o[1] + '</option>'
        ).join('') + '</select>'

      + '<label class="st-lbl">Installed voice</label>'
      + '<select id="rs-local">' + localOpts.map(o =>
          '<option value="' + o[0] + '"' + (o[0] === (s.localVoice || localOpts[0][0]) ? ' selected' : '') + '>' + (o[1] || 'Default voice') + '</option>'
        ).join('') + '</select>'

      + '<label class="st-lbl">Computer / browser voice</label>'
      + '<select id="rs-browser">' + browserOpts.map(v =>
          '<option value="' + v + '"' + ((v || '') === (s.browserVoice || '') ? ' selected' : '') + '>' + (v || 'System default') + '</option>'
        ).join('') + '</select>'

      + '<label class="st-lbl">Speed: <span id="rs-val">' + (s.speed || 1) + 'x</span></label>'
      + '<input id="rs-speed" type="range" min="0.5" max="2" step="0.25" value="' + (s.speed || 1) + '">'
      + '<div class="tiny muted">Takes effect next read. 0.5x is half speed, 2x is double.</div>'
      + '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line)">'
      + '<button id="rs-install-voice" class="btn" ' + (voiceAvailable ? 'disabled' : '') + '>Install voice model</button>'
      + ' <span id="rs-install-status" class="tiny muted">' + (voiceAvailable ? 'Voice is installed.' : (voiceReason || 'Voice not installed.')) + '</span>'
      + '<div class="tiny muted" style="margin-top:4px">Installs the read-aloud voice (~300 MB). Takes a few minutes.</div>'
      + '</div>',
      [{ label: 'Save', cls: 'primary', fn: () => {
        const settings = {
          engine: ($('#rs-engine')||{}).value || 'auto',
          speed: parseFloat(($('#rs-speed')||{}).value || '1'),
          localVoice: ($('#rs-local')||{}).value || '',
          browserVoice: ($('#rs-browser')||{}).value || '',
        };
        this.applySettings(settings);
        this.stop();
        closeModal();
      } },
      { label: 'Cancel', fn: () => {} }]);

    $('#rs-speed').oninput = () => $('#rs-val').textContent = $('#rs-speed').value + 'x';

    const installBtn = $('#rs-install-voice');
    if (installBtn && !voiceAvailable) {
      installBtn.onclick = async () => {
        installBtn.disabled = true;
        const statusEl = $('#rs-install-status');
        if (statusEl) statusEl.textContent = 'Starting install…';
        const r = await api('tts/install');
        if (!r || !r.ok || !r.job) {
          if (statusEl) statusEl.textContent = (r && r.error) || 'Could not start install.';
          installBtn.disabled = false;
          return;
        }
        const jid = r.job;
        const poll = async () => {
          const j = await api('store/job', { job: jid });
          const job = (j && j.job) || {};
          if (statusEl) statusEl.textContent = job.message || 'Installing…';
          if (job.state === 'done') {
            if (statusEl) {
              statusEl.textContent = 'Voice installed successfully. Please close and reopen G-Bible for the new voice to take effect.';
            }
            installBtn.disabled = true;
            return;
          }
          if (job.state === 'error' || job.state === 'cancelled') {
            if (statusEl) statusEl.textContent = job.message || 'Install failed.';
            installBtn.disabled = false;
            return;
          }
          setTimeout(poll, 2000);
        };
        poll();
      };
    }
  },

  supported() { return 'speechSynthesis' in window || this._mode === 'server'; },

  /* Ask once which voice to read with.  On a machine with nothing installed
   * this is the difference between offering a voice and promising one. */
  async _ask() {
    if (this._mode) return this._mode;
    try {
      const r = await api('tts/status');
      this._mode = (r && r.available) ? 'server' : 'browser';
    } catch (e) {
      this._mode = 'browser';
    }
    return this._mode;
  },

  _off() {
    this.on = false;
    $$('.pane-tools button.speaking').forEach(b => {
      b.classList.remove('speaking');
      b.textContent = '\u25B6\uFE0E';
    });
    this._clearMarks();
  },

  _clearMarks() {
    $$('.verse.speaking').forEach(el => el.classList.remove('speaking'));
    $$('.word.speaking').forEach(el => el.classList.remove('speaking'));
    $$('.pane.reading').forEach(el => el.classList.remove('reading'));
  },

  /* Mark the verse that is about to be spoken.  This is intentionally verse-level:
   * the model gives no word timestamps, so a finer highlight would be fake. The
   * verse number is the useful unit for a Bible reader anyway. */
  _markVerse(i) {
    this._clearMarks();
    const item = this._lines[i];
    if (!item || !this._paneEl) return;
    const spans = this._paneEl.querySelectorAll('.verse[data-k]');
    const el = Array.from(spans).find(v => v.dataset.k === item.key)
            || Array.from(spans).find(v => v.dataset.label === item.label);
    if (el) {
      el.classList.add('speaking');
      try { el.scrollIntoView({behavior: 'smooth', block: 'nearest'}); } catch (e) {}
    }
    $$('.pane.reading').forEach(el => el.classList.remove('reading'));
    if (this._paneEl) this._paneEl.classList.add('reading');
  },

  stop() {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    if (this._watch) { clearInterval(this._watch); this._watch = null; }
    // Anything still in flight is about a verse nobody will hear: bump the
    // sequence so its handler sees a stale run and drops it, abort the fetch,
    // and let a waiting _play() go rather than hang on an <audio> that is
    // about to have its source cleared.
    this._seq++;
    if (this._abort) { try { this._abort.abort(); } catch (e) {} this._abort = null; }
    if (this._playing) { const done = this._playing; this._playing = null; done(); }
    if (this._audio) { this._audio.pause(); this._audio.removeAttribute('src'); this._audio = null; }
    if (this._blob) { URL.revokeObjectURL(this._blob); this._blob = null; }
    this._off();
  },

  /* Speak the pane's own text.  The rendered HTML is not what gets read:
   * it would say "superscript one" and read Strong's numbers aloud. */
  async speak(pane, btn) {
    if (!this.supported()) { toast('This browser cannot read aloud.', 'warn'); return; }
    if (this.on) { this.stop(); return; }
    const c = pane._content;
    if (!c || !c.items || !c.items.length) { toast('Still loading.', 'warn'); return; }
    const units = c.items
      .map(it => ({ key: it.key, label: it.label, text: (it.text || '').trim() }))
      .filter(it => it.text);
    /* If the user clicked a verse to select it, start reading from there.
     * Otherwise start from the beginning of the chapter. */
    let startIdx = 0;
    if (pane.selectedVerse) {
      const found = units.findIndex(u => u.key === pane.selectedVerse.key);
      if (found >= 0) startIdx = found;
    }
    const parts = units.map(it => it.text);
    const st = this.loadSettings();
    this.rate = Number(st.speed || 1);
    this._engine = st.engine || 'auto';
    this._localVoice = st.localVoice || '';
    this._browserVoice = st.browserVoice || '';
    if (this._engine === 'server') this._mode = 'server';
    else if (this._engine === 'browser') this._mode = 'browser';
    else this._mode = null;
    if (!parts.length) { toast('Nothing to read here.', 'warn'); return; }
    this._pane = pane;
    // The speak entry point is handed the Workspace pane object, not a DOM element,
    // so this._pane cannot be searched as though it were an element.
    this._paneEl = (pane && pane.id) ? $('.pane[data-pane="' + pane.id + '"]') : null;
    this._lines = units;
    if (await this._ask() === 'server') return this._playServer(parts.slice(startIdx), btn, startIdx);
    return this._playBrowser(parts.slice(startIdx), btn, startIdx);
  },

  /* ---------------------------------------------------------------- server
   *
   * One verse per request, with the next one asked for while this one plays.
   * The model is quicker than speech is -- a verse costs about a second of CPU
   * for two seconds of audio -- so overlapping the two is the difference
   * between a chapter reading straight through and a chapter interrupted by a
   * gap at every single verse.  `ahead` holds the promise, not the bytes, so
   * nothing is decoded until it is its turn.
   */
  async _playServer(parts, btn, startIdx = 0) {
    const seq = ++this._seq;
    const ctrl = new AbortController();
    this._abort = ctrl;
    this.on = true;
    if (btn) { btn.classList.add('speaking'); btn.textContent = '\u25A0'; }

    // Nothing has been said yet, so if the first request fails the whole
    // reading can still go to the browser rather than stopping at verse one
    // with silence.  Past the first verse there is no such second chance.
    let ahead;
    try {
      ahead = await this._fetch(parts[0], ctrl.signal);
    } catch (e) {
      if (seq !== this._seq) return;                    // stopped while loading
      this._mode = 'browser';                           // and stop asking
      toast('Falling back to the browser voice: ' + (e.message || e), 'warn');
      this._playBrowser(parts, btn, startIdx);
      return;
    }

    let i = 0;
    try {
      while (this.on && seq === this._seq && i < parts.length) {
        // `ahead` is a promise, so it has to be awaited here and not merely
        // tested: `ahead || await ...` short-circuits and hands the promise
        // itself to _play(), where createObjectURL rejects it.  Verse one hid
        // this, being seeded already-awaited, so the chapter got exactly one
        // verse out before stopping.
        const blob = ahead ? await ahead : await this._fetch(parts[i], ctrl.signal);
    this.rate = Number(this.rate || 1);
        ahead = null;
        this._markVerse(i + startIdx);
        if (i + 1 < parts.length) {
          // A prefetch that fails is not fatal: the loop above falls back to
          // asking for the verse itself, and only the await is left with it.
          ahead = this._fetch(parts[i + 1], ctrl.signal).catch(() => null);
        }
        i++;
        await this._play(blob);
      }
    } catch (e) {
      if (seq === this._seq) toast('Read aloud stopped: ' + (e.message || e), 'warn');
    } finally {
      if (seq === this._seq) this._off();
    }
  },

  /* One verse, as a WAV.  No voice name is sent: the server picks its own. */
  async _fetch(text, signal) {
    const r = await fetch('/tts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-GBible-CSRF-Token': CSRF_TOKEN,
      },
      body: JSON.stringify({ text, speed: this.rate, voice: this._localVoice }),
      signal: signal,
    });
    if (!r.ok) {
      let why = 'HTTP ' + r.status;
      try { const j = await r.json(); if (j && j.error) why = j.error; } catch (e) {}
      throw new Error(why);
    }
    return await r.blob();
  },

  /* Play one WAV, resolving when it ends.  stop() resolves it early, so a
   * cleared source does not leave the loop waiting for an `ended` that will
   * never be sent. */
  _play(blob) {
    return new Promise((resolve, reject) => {
      const a = this._audio || (this._audio = new Audio());
      let ended = false;
      const finish = (err) => {
        if (ended) return;
        ended = true;
        if (this._playing === finish) this._playing = null;
        if (err) reject(err); else resolve();
      };
      // stop() calls this with no argument, which resolves: a verse cut short
      // ends the verse.
      this._playing = finish;
      if (this._blob) URL.revokeObjectURL(this._blob);
      this._blob = URL.createObjectURL(blob);
      a.onended = () => finish();
      a.onerror = () => finish(new Error('the audio would not play'));
      a.src = this._blob;
      a.play().catch(e => finish(e));
    });
  },

  /* --------------------------------------------------------------- browser
   *
   * The browser's own engine, used when the voice is not installed.  One
   * utterance per item: a whole chapter in one utterance is cut off by the
   * engine, and this way stopping takes effect between verses.
   */
  _playBrowser(parts, btn, startIdx = 0) {
    if (!('speechSynthesis' in window)) {
      toast('This browser cannot read aloud.', 'warn');
      return;
    }
    this.on = true;
    if (btn) { btn.classList.add('speaking'); btn.textContent = '\u25A0'; }
    speechSynthesis.cancel();
    const seq = this._seq;
    let i = 0;
    const next = () => {
      if (seq !== this._seq || !this.on || i >= parts.length) { this.stop(); return; }
      this._markVerse(i + startIdx);
      const u = new SpeechSynthesisUtterance(parts[i++]);
      u.rate = this.rate;
      if (this._browserVoice) {
        const voices = speechSynthesis && speechSynthesis.getVoices ? speechSynthesis.getVoices() : [];
        const v = voices.find(x => x.name === this._browserVoice);
        if (v) u.voice = v;
      }
      u.onend = () => setTimeout(next, 120);
      u.onerror = () => this.stop();
      speechSynthesis.speak(u);
    };
    next();
    this._watch = setInterval(() => {
      if (!speechSynthesis.speaking && !speechSynthesis.pending) next();
    }, 1000);
  },
};
