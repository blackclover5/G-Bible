/* ================================================= Local module import wizard
   e-Sword-style module import, built into the Store.  Two doors:
     1. Pick a single file with the in-app browser — it detects the format
        and shows you what it is before you commit.
     2. Pick a folder — everything importable inside it is listed with a
        checkbox, then everything you tick gets installed in one background
        job with per-file progress.
   Nothing leaves this computer; path typing still works for power users. */
const ImportWizard = {
  /* ------------------------------------------------------------------ open */
  open() {
    modal('Import modules',
      '<div class="legal tiny" style="margin-bottom:10px">Imports a module file you already have on this computer. '
      + 'Nothing is uploaded. Detect the format first, then choose to import.</div>'
      + '<label class="tiny muted" for="iw-path">File or folder</label>'
      + '<div class="row" style="gap:6px;margin:4px 0 8px"><input id="iw-path" '
      + 'style="flex:1;min-width:0" placeholder="/path/to/module.zip">'
      + '<button class="btn" id="iw-browse" title="Browse this computer">Browse…</button>'
      + '<button class="btn" id="iw-folder" title="Import every importable file in a folder">Import a folder…</button>'
      + '</div>'
      + '<div id="iw-preview"></div>'
      + '<div class="iw-personal" style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line)">'
      + '<div class="tiny muted" style="margin-bottom:6px">Import a personal book (PDF, EPUB or plain text) into your library:</div>'
      + '<div class="row" style="gap:6px"><input id="iw-pb-path" style="flex:1" placeholder="/path/to/book.epub">'
      + '<button class="btn" id="iw-pb-go">Import book</button></div>'
      + '<div id="iw-pb-out" class="tiny" style="margin-top:6px"></div></div>',
      [
        { label: 'Import', cls: 'btn primary', close: false,
          fn: () => this._importFile() },
        { label: 'Close', cls: 'btn' },
      ]);
    const pathEl = $('#iw-path');
    pathEl.value = this.lastPath || '';
    pathEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.inspect();
    });
    pathEl.addEventListener('input', debounce(() => this.inspect(), 350));
    $('#iw-browse').onclick = () => this._browseForFile();
    $('#iw-folder').onclick = () => this._folderFlow();
    const pbGo = $('#iw-pb-go');
    if (pbGo) pbGo.onclick = async () => {
      const path = ($('#iw-pb-path').value || '').trim();
      if (!path) { toast('Type a file path.', 'warn'); return; }
      const r = await api('personal-books', { action: 'import', path });
      const out = $('#iw-pb-out');
      if (r.ok) {
        if (out) out.textContent = 'Imported "' + r.title + '" (' + r.unit_count + ' units).';
        toast('Imported "' + r.title + '".');
      } else {
        if (out) out.textContent = r.error || 'Import failed.';
        toast(r.error || 'Import failed.', 'err');
      }
    };
    this.inspect();
  },

  /* ------------------------------------------------------------- inspect */
  async inspect() {
    const path = ($('#iw-path').value || '').trim();
    const host = $('#iw-preview');
    if (!host) return;
    if (!path) { host.innerHTML = ''; return; }
    host.innerHTML = '<div class="st-loading">Reading…</div>';
    const r = await api('store/inspect', { path });
    if (!r.ok) {
      host.innerHTML = '<div class="warn">' + esc(r.error || 'not a file') + '</div>';
      return;
    }
    const bits = [];
    if (r.format) bits.push('<span class="st-src">' + esc(r.format) + '</span>');
    bits.push(esc(this._size(r.size || 0)));
    if (r.abbrev) bits.push('abbrev ' + esc(r.abbrev));
    let h = '<div class="tiny" style="margin-bottom:6px">' + bits.join(' · ') + '</div>';
    const row = (k, v) => '<div class="tiny"><span class="muted" style="display:inline-block;min-width:88px">'
      + esc(k) + '</span> ' + esc(v) + '</div>';
    if (r.title) h += row('Title', r.title);
    if (r.author) h += row('Author', r.author);
    if (r.lang) h += row('Language', r.lang);
    if (r.version) h += row('Version', r.version);
    if (r.category) h += row('Category', r.category);
    if (r.license) h += row('License', r.license);
    if (r.units != null) h += row('Contents', String(r.units) + ' item(s)');
    if (r.modules && r.modules.length) {
      h += row('Modules', r.modules.length + ' in this package');
    }
    if (r.error) h += '<div class="tiny muted" style="margin-top:4px">Preview warning: ' + esc(r.error) + '</div>';
    if (!r.title && !r.description && !r.category) {
      h += '<div class="tiny muted" style="margin-top:4px">No metadata read; the importer will decide the format from the contents.</div>';
    }
    host.innerHTML = h;
  },

  /* ---------------------------------------------------------- file picker */
  _browseForFile(initialPath) {
    this._browse(initialPath, 'file', (chosen) => {
      /* The browser replaced the wizard's body in the shared modal view --
       * re-open the wizard with the chosen file so the user sees the preview. */
      this.lastPath = chosen;
      this.open();
    });
  },

  _folderFlow() {
    this._browse(null, 'folder', (chosen) => {
      this._showFolder(chosen);
    });
  },

  /* Shared directory picker.  mode: 'file' chooses a file, 'folder' chooses
   * the folder itself.  Callback gets the chosen absolute path. */
  async _browse(initialPath, mode, done) {
    let cwd = initialPath || (window.__lastBrowsePath || '~');
    /* The backup restore shows only .gbz files and never hidden entries —
       the rest of the filesystem is none of the backup's business. */
    const extra = (mode === 'gbz') ? { only_ext: 'gbz' } : {};
    const paint = async (path) => {
      const r = await api('store/browse', Object.assign({ path }, extra));
      if (!r.ok) { toast(r.error || 'cannot open folder', 'err'); return; }
      cwd = r.path;
      window.__lastBrowsePath = cwd;
      const body = $('#iw-browse-body');
      if (!body) return;
      let h = '<div class="tiny" style="margin-bottom:6px"><b>' + esc(cwd) + '</b></div>';
      if (r.parent) {
        h += '<button class="btn tiny" id="iw-up">⬑ up one level</button> ';
      }
      h += '<button class="btn tiny" id="iw-home">⌂ home</button>';
      h += '<button class="btn tiny" id="iw-root" title="Go to the filesystem root — reaches /media, /mnt, other drives">⤒ root</button>';
      if (mode === 'folder') {
        h += '<button class="btn tiny primary" id="iw-pick-folder" style="float:right">Import everything importable in this folder…</button>';
      } else if (mode === 'pick-folder') {
        h += '<button class="btn tiny primary" id="iw-pick-folder" style="float:right">Use this folder</button>';
      }
      h += '<div class="iw-list" style="display:flex;flex-direction:column;gap:2px;max-height:52vh;overflow:auto;margin-top:8px;border:1px solid var(--line);border-radius:6px;padding:4px">';
      r.entries.forEach((e) => {
        const icon = e.is_dir ? '▸' : '∙';
        h += '<button class="iw-row tiny" data-path="' + esc(e.path) + '" data-dir="' + (e.is_dir ? '1' : '0') + '">'
          + '<span style="width:14px">' + icon + '</span>'
          + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(e.name) + '</span>'
          + (e.is_dir ? '' : '<span class="muted">' + esc(this._size(e.size)) + '</span>')
          + '</button>';
      });
      if (!r.entries.length) h += '<div class="tiny muted" style="padding:8px">'
        + (mode === 'gbz' ? 'No .gbz backups in this folder.' : 'Empty folder.') + '</div>';
      h += '</div>';
      body.innerHTML = h;
      const up = $('#iw-up'); if (up) up.onclick = () => paint(r.parent);
      const home = $('#iw-home'); if (home) home.onclick = () => paint(r.home);
      const root = $('#iw-root'); if (root) root.onclick = () => paint('/');
      const pick = $('#iw-pick-folder'); if (pick) pick.onclick = () => { this._closeBrowse(); done(cwd); };
      $$('.iw-row', body).forEach(row => {
        row.onclick = () => {
          if (row.dataset.dir === '1') { paint(row.dataset.path); return; }
          this._closeBrowse();
          done(row.dataset.path);
        };
      });
    };
    modal(mode === 'folder' ? 'Choose a folder'
      : mode === 'gbz' ? 'Choose backup (.gbz)'
      : 'Import a file',
      '<div id="iw-browse-body"><div class="st-loading">Loading…</div></div>',
      [{ label: 'Cancel', cls: 'btn' }]);
    this._browseOpen = true;
    paint(cwd);
  },

  _closeBrowse() {
    this._browseOpen = false;
    closeModal();
    /* re-open the wizard itself if it was dismissed by the browser */
  },

  /* ----------------------------------------------------- folder import */
  async _showFolder(path) {
    closeModal();
    modal('Import a folder',
      '<div class="tiny muted" id="iw-fo-path">' + esc(path) + '</div>'
      + '<div id="iw-folder-list" style="max-height:55vh;overflow:auto;margin:8px 0;border:1px solid var(--line);border-radius:6px;padding:4px">'
      + '<div class="st-loading">Scanning…</div></div>'
      + '<div class="tiny muted" id="iw-folder-sum"></div>',
      [
        { label: 'Import selected', cls: 'btn primary', close: false,
          fn: () => this._importFolder() },
        { label: 'Close', cls: 'btn' },
      ]);
    const r = await api('store/folder', { path, recursive: 1 });
    if (!r.ok) { $('#iw-folder-list').innerHTML = '<div class="warn">' + esc(r.error) + '</div>'; return; }
    this._folderFiles = r.files;
    const host = $('#iw-folder-list');
    if (!r.files.length) {
      host.innerHTML = '<div class="empty">Nothing importable in there. '
        + 'Supported: .zip SWORD modules, .bbl/.cmt/.dct/.bblx (e-Sword), .usfm, .epub, .txt, .kml.</div>';
      $('#iw-folder-sum').textContent = '';
      return;
    }
    let h = '<label class="tiny muted" style="display:block;margin-bottom:4px"><input type="checkbox" id="iw-selall" checked> Select all (' + r.files.length + ' files, ' + this._size(r.size) + ')</label>';
    this._folderFiles.forEach((f, i) => {
      h += '<label class="iw-frow tiny" style="display:flex;gap:8px;align-items:baseline;padding:3px 4px;border-radius:4px;cursor:pointer">'
        + '<input type="checkbox" class="iw-fsel" data-i="' + i + '" checked>'
        + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(f.name) + '</span>'
        + '<span class="muted">' + esc(f.format) + '</span>'
        + '<span class="muted">' + esc(this._size(f.size)) + '</span>'
        + '</label>';
    });
    host.innerHTML = h;
    this._sumFolder();
    $('#iw-selall').onchange = (e) => {
      $$('.iw-fsel', host).forEach(c => { c.checked = e.target.checked; });
      this._sumFolder();
    };
    $$('.iw-fsel', host).forEach(c => c.onchange = () => this._sumFolder());
  },

  _sumFolder() {
    const host = $('#iw-folder-list');
    if (!host || !this._folderFiles) return;
    const boxes = $$('.iw-fsel', host);
    const sel = this._folderFiles.filter((f, i) => boxes[i] && boxes[i].checked);
    const size = sel.reduce((acc, f) => acc + (f.size || 0), 0);
    $('#iw-folder-sum').textContent = sel.length + ' selected · ' + this._size(size);
  },

  async _importFolder() {
    const host = $('#iw-folder-list');
    const boxes = $$('.iw-fsel', host);
    const paths = this._folderFiles.filter((f, i) => boxes[i] && boxes[i].checked).map(f => f.path);
    if (!paths.length) { toast('Tick at least one file.', 'warn'); return; }
    const r = await post('store/import-folder', { paths });
    if (!r.ok) { toast(r.error || 'could not start', 'err'); return; }
    this._trackFolderJob(r.job, r.total);
  },

  _trackFolderJob(job, total) {
    modal('Importing ' + total + ' files…',
      '<div class="tiny muted" id="iw-fold-status">Starting…</div>'
      + '<div style="height:6px;border-radius:99px;background:var(--line);overflow:hidden;margin:10px 0">'
      + '<div id="iw-fold-fill" style="height:100%;width:0%;background:var(--accent);transition:width .3s"></div>'
      + '</div><div class="tiny muted" id="iw-fold-fail"></div>',
      [{ label: 'Stop after current file', cls: 'btn', close: false,
         fn: async () => { await post('recommended/cancel', { job }); } },
       { label: 'Close', cls: 'btn', close: true }]);
    const poll = async () => {
      const jr = await api('store/job', { job });
      const j = (jr && jr.job) || {};
      const done = Number(j.done) || 0;
      const failed = j.failed || [];
      const pct = total ? Math.min(100, Math.round(done * 100 / total)) : 100;
      const fill = $('#iw-fold-fill'); if (fill) fill.style.width = pct + '%';
      const st = $('#iw-fold-status');
      if (st) st.textContent = j.message || ('imported ' + done + ' of ' + total);
      const fe = $('#iw-fold-fail');
      if (fe) {
        fe.innerHTML = failed.length
          ? '<span class="warn">' + failed.length + ' failed: '
            + esc(failed.slice(-3).map(f => f.path.split('/').pop() + ': ' + f.error).join(' · ')) + '</span>'
          : '';
      }
      if (j.state === 'done' || j.state === 'cancelled') {
        setTimeout(() => { closeModal(); App.loadLibrary(); App.loadWorkspace(); }, 700);
        return;
      }
      setTimeout(poll, 900);
    };
    poll();
  },

  /* ------------------------------------------------------------- import */
  async _importFile() {
    const path = ($('#iw-path') || {}).value;
    const p = (path || '').trim();
    if (!p) { toast('Point me at a file first.', 'warn'); return; }
    const r = await post('store/import', { path: p });
    if (!r.ok) { toast(r.error || 'import failed', 'err'); return; }
    this.lastPath = p;
    const status = $('#iw-preview');
    if (status) status.innerHTML = '<div class="st-loading">Importing…</div>';
    const poll = async () => {
      const j = (await api('store/job', { job: r.job })).job;
      if (!j) return;
      if (j.state === 'done') { toast('Imported.'); closeModal(); await App.loadLibrary(); await App.loadWorkspace(); return; }
      if (j.state === 'error') { toast(j.message, 'err'); return; }
      setTimeout(poll, 800);
    };
    poll();
  },

  _size(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  },
};
window.ImportWizard = ImportWizard;
