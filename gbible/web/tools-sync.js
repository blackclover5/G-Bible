const Sync = {
  st: null,

  async load() {
    const host = $('#sync-body');
    host.innerHTML = '<div class="loading">Loading…</div>';
    let r;
    try { r = await api('sync/status'); }
    catch (e) { host.innerHTML = '<div class="empty">' + esc(e.message || e) + '</div>'; return; }
    /* A server that does not know this screen answers `ok: false` rather than
       throwing, so the form would render against nothing and the first button
       pressed would fail with a route error that means nothing to a reader.
       Say what is wrong instead. */
    if (r && r.ok === false) {
      host.innerHTML = '';
      const card = el('div', 'dash-card');
      card.appendChild(el('div', 'dash-h', 'Sync did not answer'));
      card.appendChild(el('div', 'st-body',
        esc(r.error || 'The server did not answer.')));
      card.appendChild(el('div', 'tiny muted',
        'Restart G-Bible (stop it and run it again) and open this screen once more. '
        + 'A server that was already running does not load the new code.'));
      host.appendChild(card);
      $('#sync-summary').textContent = '';
      return;
    }
    this.st = r;
    host.innerHTML = '';
    host.appendChild(this.stateCard(r));
    host.appendChild(this.restoreCard(r));
    host.appendChild(this.formCard(r));
    $('#sync-summary').innerHTML = this.summaryLine(r);
  },

  summaryLine(r) {
    if (!r.configured) {
      return 'One backup file — gbible-backup.gbz — keeps your notes, plans, '
        + 'tags, layouts and reading settings in one place, attached to the '
        + 'target you choose. Appearance, AI conversations and keys stay local '
        + 'unless you export them from the Backup screen.';
    }
    const when = r.last_ok ? relTime(r.last_ok) : 'never';
    const where = r.kind === 'nextcloud' ? ('to Nextcloud' + (r.user ? ' — ' + r.user : ''))
      : r.kind === 'webdav' ? 'to the WebDAV server'
      : 'to ' + (r.path || 'a folder');
    let s = 'gbible-backup.gbz on <b>' + esc(where) + '</b>'
      + ' · last synced ' + esc(when);
    if (r.last_size) s += ' · ' + Math.round(r.last_size / 1024) + ' KB';
    if (r.last_error) s += ' · <span style="color:var(--red)">' + esc(r.last_error) + '</span>';
    return s;
  },

  /* One door to an honest description of what sync actually moves. */
  scopeButton() {
    const b = el('button', 'btn', 'What travels?');
    b.title = 'See exactly what a sync or backup carries';
    b.onclick = () => this.showScope();
    return b;
  },

  async showScope() {
    let r;
    try { r = await api('sync/scope'); }
    catch (e) { toast((e && e.message) || 'Could not load scope.', 'err'); return; }
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not load scope.', 'err');
      return;
    }
    const h = [];
    (r.notes || []).forEach(n => h.push('<div class="tiny muted">'
      + esc(n) + '</div>'));

    h.push('<div class="st-sec open"><div class="st-h">Record kinds that travel</div><div class="st-body">');
    (r.kinds || []).forEach(k => {
      const tag = k.ai_inclusive_only
        ? ' <span class="tiny" style="color:var(--error)">encrypted AI-inclusive backup only</span>'
        : '';
      h.push('<div>' + esc(k.label) + tag
        + '<span class="tiny muted"> — ' + esc(k.folder) + '</span></div>');
    });
    h.push('</div></div>');

    h.push('<div class="st-sec open"><div class="st-h">Settings that travel</div><div class="st-body tiny">'
      + (r.settings || []).map(s => esc(s.label)).join(' · ')
      + '</div></div>');

    h.push('<div class="st-sec open"><div class="st-h">Stays on this device</div><div class="st-body">');
    (r.local_only || []).forEach(x => h.push('<div><b>' + esc(x.title) + '</b> — '
      + esc(x.detail) + '</div>'));
    h.push('</div></div>');

    h.push('<div class="st-sec open"><div class="st-h">AI data</div><div class="st-body">'
      + esc((r.ai || {}).detail || '') + '</div></div>');

    const del = r.deletion || {};
    const enc = r.encryption || {};
    h.push('<div class="st-sec open"><div class="st-h">Deletes &amp; encryption</div><div class="st-body">'
      + esc(del.detail || '')
      + '<div class="tiny muted">Tombstones kept ' + esc(del.retention_days)
      + ' days · deletes off by default.</div>'
      + esc(enc.detail || '')
      + '</div></div>');

    modal('What travels?', h.join(''), [{ label: 'Close', cls: 'btn primary' }]);
  },

  stateCard(r) {
    const card = el('div', 'dash-card');
    const h = el('div', 'dash-h', r.configured ? 'Sync' : 'Not set up');
    card.appendChild(h);
    if (!r.configured) {
      card.appendChild(el('div', 'st-body',
        'One button does the backup: pick a target below (this computer, '
        + 'WebDAV or Nextcloud), press Sync now, and G-Bible writes '
        + 'gbible-backup.gbz there. Restoring pulls the same file back.'));
      const bar = el('div', 'row', '');
      bar.style.marginTop = '10px';
      bar.appendChild(this.scopeButton());
      card.appendChild(bar);
      return card;
    }
    const rows = el('div', 'sync-rows');
    const line = (k, v) => {
      const d = el('div', 'sync-row');
      d.appendChild(el('span', 'k', k));
      d.appendChild(el('span', 'v', v));
      rows.appendChild(d);
    };
    line('Where gbible-backup.gbz goes',
      r.kind === 'nextcloud' ? esc('Nextcloud — ' + (r.user || ''))
      : r.kind === 'webdav' ? esc(r.url) : esc(r.path));
    line('Last backup', r.last_ok
      ? relTime(r.last_ok) + (r.last_size ? ' · ' + Math.round(r.last_size / 1024) + ' KB' : '')
      : 'never yet');
    line('This device', esc(r.device_id) + ' <span class="tiny muted">'
      + (r.metered === null ? '(connection cannot be checked)'
        : r.metered ? '(metered connection)' : '(unmetered)') + '</span>');
    line('Encryption', r.encrypt ? 'on (passphrase required to read the backup)'
      : 'off (the backup is readable by anyone who can read the target)');
    card.appendChild(rows);
    const bar = el('div', 'row', '');
    bar.style.marginTop = '10px';
    const now = el('button', 'btn primary', 'Sync now');
    now.onclick = () => this.runNow(now);
    bar.appendChild(now);
    const off = el('button', 'btn', 'Turn sync off');
    off.onclick = async () => {
      const res = await post('sync/configure', { kind: '' });
      if (!res || res.ok === false) {
        toast((res && res.error) || 'Could not turn sync off.', 'err');
        return;
      }
      toast('Sync turned off. Nothing was deleted.');
      App.show('sync');
    };
    bar.appendChild(off);
    bar.appendChild(this.scopeButton());
    card.appendChild(bar);
    return card;
  },

  restoreCard(r) {
    const card = el('div', 'dash-card');
    card.appendChild(el('div', 'dash-h', 'Restore from a .gbz backup'));
    card.appendChild(el('div', 'st-body',
      'One artefact, two ends. Sync writes gbible-backup.gbz to the target you '
      + 'configure — this computer, WebDAV, Nextcloud. Restoring reads it back from '
      + 'the same place. Nothing is merged from half a backup: if the file is there '
      + 'and the modules are installed, everything comes back, notes to layouts to '
      + 'AI settings.'));
    card.appendChild(el('div', 'tiny muted',
      'If you turn on encryption in the target below, the backup is unreadable without '
      + 'the passphrase. Keep it like a password — and off shared folders. Sync passwords '
      + 'never travel in it.'));

    const del = el('label', 'tiny');
    del.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:.5rem';
    del.innerHTML = '<input type="checkbox" id="bk-apply-deletes"> '
      + 'Apply deletes from the backup — removes records this device already '
      + 'knows and whose delete is newer. Leave off for a purely additive restore.';
    card.appendChild(del);
    const parts = [
      { key: 'computer', label: 'From this computer…',
        hint: 'Pick a .gbz file wherever it lives on this machine.' },
      { key: 'webdav',   label: 'From WebDAV',
        hint: 'the same file on the WebDAV server you synced to.' },
      { key: 'nextcloud',label: 'From Nextcloud',
        hint: 'the same file on the Nextcloud you synced to.' },
    ];

    const wrap = el('div', 'row wrap', '');
    wrap.style.marginTop = '.5rem';
    wrap.style.gap = '.5rem';
    parts.forEach(p => {
      const btn = el('button', 'btn', '');
      btn.appendChild(el('div', 'tiny muted', ''));
      const title = document.createElement('div');
      title.textContent = p.label;
      btn.appendChild(title);
      const sub = document.createElement('div');
      sub.className = 'tiny muted';
      sub.textContent = p.hint;
      btn.appendChild(sub);
      const configuredFor = (r.kind === 'webdav' && p.key === 'webdav')
        || (r.kind === 'nextcloud' && p.key === 'nextcloud');
      if (p.key === 'computer') {
        btn.onclick = () => this.chooseBackup();
      } else if (configuredFor) {
        btn.onclick = () => this.restoreRemote();
      } else {
        btn.disabled = true;
        btn.title = 'Not configured yet — set ' + (p.key === 'webdav' ? 'WebDAV' : 'Nextcloud')
          + ' above first, sync once, then this button works.';
        const note = document.createElement('div');
        note.className = 'tiny';
        note.style.color = 'var(--amber)';
        note.textContent = 'Not configured';
        btn.appendChild(note);
      }
      wrap.appendChild(btn);
    });
    card.appendChild(wrap);
    const aiExp = el('button', 'btn', 'Export with AI data…');
    aiExp.title = 'Create an encrypted backup including AI conversations, usage and API keys';
    aiExp.style.marginTop = '.5rem';
    aiExp.onclick = () => this.exportWithAI();
    card.appendChild(aiExp);
    const result = el('div', '', '');
    result.id = 'bk-result'; result.style.display = 'none'; result.style.marginTop = '.75rem';
    card.appendChild(result);
    const preview = el('div', '', '');
    preview.id = 'bk-preview'; preview.style.display = 'none'; preview.style.marginTop = '.75rem';
    card.appendChild(preview);
    return card;
  },

  /* The AI-inclusive archive is the one exception to "keys stay local".  It is
   * only reachable here, behind a passphrase the reader chooses, so the claim
   * in the What-travels panel is a door the reader can actually walk through. */
  exportWithAI() {
    modal('Encrypted backup with AI data',
      '<div class="st-body">This is the only archive that carries your AI '
      + 'conversations, usage history and API keys. It is always encrypted with '
      + 'a passphrase you choose — G-Bible cannot recover it for you. Ordinary '
      + 'sync backups leave all of that behind.</div>'
      + '<label class="st-lbl" style="margin-top:.6rem">Passphrase (at least 12 characters)</label>'
      + '<input type="password" id="ai-exp-pw" style="width:100%" autocomplete="new-password">'
      + '<label class="st-lbl" style="margin-top:.5rem">Confirm passphrase</label>'
      + '<input type="password" id="ai-exp-pw2" style="width:100%" autocomplete="new-password">'
      + '<div class="tiny muted" id="ai-exp-msg" style="margin-top:.5rem"></div>',
      [{ label: 'Cancel', cls: 'btn' },
       { label: 'Create encrypted backup', cls: 'btn primary', close: false,
         fn: async () => {
           const pw = ($('#ai-exp-pw') || {}).value || '';
           const pw2 = ($('#ai-exp-pw2') || {}).value || '';
           const msg = $('#ai-exp-msg');
           if (pw.length < 12) { msg.textContent = 'Use at least 12 characters.'; return; }
           if (pw !== pw2) { msg.textContent = 'The two passphrases do not match.'; return; }
           msg.textContent = 'Building the encrypted archive…';
           // Appearance lives in localStorage, so the backup cannot see it
          // unless the UI sends it. It is the one setting a restored machine
          // cannot otherwise recover.
          const appearance = (typeof Appearance !== 'undefined' && Appearance.load)
            ? Appearance.load() : null;
          const r = await post('backup/export', {
            include_ai: 1, passphrase: pw, appearance });
           if (!r || r.ok === false) {
             msg.textContent = (r && r.error) || 'Could not build the backup.';
             return;
           }
           try {
             const bin = atob(r.data_base64);
             const bytes = new Uint8Array(bin.length);
             for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
             const url = URL.createObjectURL(new Blob([bytes]));
             const a = document.createElement('a');
             a.href = url; a.download = r.filename || 'gbible-backup.gbz';
             document.body.appendChild(a); a.click(); a.remove();
             setTimeout(() => URL.revokeObjectURL(url), 1000);
             closeModal();
             toast('Saved ' + (r.filename || 'encrypted backup'));
           } catch (e) {
             msg.textContent = 'Could not save the file: ' + (e && e.message || e);
           }
         }}]);
  },

  async restoreRemote() {
    // Confirm before touching this machine's data, using a fresh snapshot:
    // the cached one may be from a failed load and misname the destination.
    const fresh = await api('sync/status');
    const r = (fresh && fresh.ok !== false && fresh.status) || this.st;
    const target = r && r.kind === 'nextcloud'
      ? 'Nextcloud (' + (r.user || '') + ')'
      : 'the WebDAV server';
    const applyDeletes = !!($('#bk-apply-deletes') && $('#bk-apply-deletes').checked);
    const what = applyDeletes
      ? ' Records deleted on the other device will also be removed here.'
      : ' Your current records stay where they differ — this only adds what is missing.';
    if (!confirm('Restore from ' + target + '?' + what)) return;
    const result = $('#bk-result'); const preview = $('#bk-preview');
    if (preview) { preview.style.display = 'none'; preview.innerHTML = ''; }
    if (!result) return;
    result.style.display = '';
    result.innerHTML = '<div class="tiny">Restoring from ' + esc(target) + '…</div>';
    let out = await post('sync/restore', { apply_deletes: applyDeletes ? 1 : 0 });
    if (!out || out.ok === false) {
      if (/passphrase|encrypted/i.test((out && out.error) || '')) {
        const pw = prompt('This backup is encrypted. Enter the passphrase:');
        if (pw) {
          result.innerHTML = '<div class="tiny">Restoring from ' + esc(target) + '…</div>';
          out = await post('sync/restore', {
            passphrase: pw, apply_deletes: applyDeletes ? 1 : 0 });
        }
      }
    }
    if (!out || out.ok === false) {
      result.innerHTML = '<div class="st-body" style="color:var(--error)">'
        + esc((out && out.error) || 'Restore failed.') + '</div>';
      return;
    }
    if (out.appearance) {
      try {
        localStorage.setItem('gbible:appearance', JSON.stringify(out.appearance));
      } catch (e) { /* cosmetic; never block a restore */ }
    }
    this._stashRestore(out);
    result.innerHTML = '<div class="st-body"><b>Restore complete — refreshing…</b></div>';
    toast('Restored from ' + target + ' — refreshing…', 'ok');
    setTimeout(() => location.reload(), 400);
  },

  _stashRestore(out) {
    try {
      sessionStorage.setItem('gbible:last-restore', JSON.stringify({
        applied: Number(out.applied) || 0,
        existed: Number(out.existed) || 0,
        conflict: Number(out.conflict) || 0,
        conflicts: out.conflicts || [],
        deletes: (out.tombstones_applied || []).length,
        deletes_skipped: (out.tombstones_skipped || []).length,
        ai_keys_added: Number(out.ai_keys_added) || 0,
        ai_keys_kept: Number(out.ai_keys_kept) || 0,
        missing: out.modules_missing || [],
        notes: out.notes || [],
        errors: out.errors || [],
      }));
    } catch (e) { /* storage unavailable — the banner just will not show */ }
  },

  async chooseBackup() {
    window.ImportWizard._browse(null, 'gbz', async (path) => {
      if (!/\.gbz$/i.test(path)) {
        toast('That is not a .gbz backup. Choose the file ending in .gbz.', 'err');
        return;
      }
      const result = $('#bk-result');
      if (result) { result.style.display = 'none'; result.innerHTML = ''; }
      const preview = $('#bk-preview');
      if (preview) { preview.style.display = ''; preview.innerHTML = '<div class="tiny">Reading…</div>'; }
      let info = await post('backup/preview', { path });
      if (!preview) return;
      if (!info || info.ok === false) {
        if (/passphrase|encrypted/i.test((info && info.error) || '')) {
          const pw = prompt('This backup is encrypted. Enter the passphrase:');
          if (pw === null) {
            preview.innerHTML = '<div class="st-body" style="color:var(--error)">Restore cancelled.</div>';
            return;
          }
          this._backupPassphrase = pw;
          info = await post('backup/preview', { path, passphrase: pw });
        }
      }
      if (!info || info.ok === false) {
        preview.innerHTML = '<div class="st-body" style="color:var(--error)">'
          + esc((info && info.error) || 'Could not read that backup.') + '</div>';
        return;
      }
      const c = info.counts || {};
      const kindNames = { 'ai-chat': 'AI chat', 'morph-query': 'saved morph search',
                          'word-list': 'word list', 'passage-list': 'passage list',
                          'srs-card': 'SRS card', 'citation-meta': 'citation set' };
      const kinds = Object.keys(c).filter(k => Number(c[k]) > 0)
        .map(k => c[k] + ' ' + (kindNames[k] || k) + (Number(c[k]) === 1 ? '' : 's')).join(' · ') || 'no records';
      const total = Number(info.records) || 0;
      const missing = info.modules_missing || [];
      let h = '<div class="st-body"><b>' + esc(total + ' record' + (total === 1 ? '' : 's'))
        + '</b> · ' + esc(kinds) + '</div>';
      if (info.has_ai_usage) {
        h += '<div class="tiny" style="margin-top:.5rem">'
          + esc((Number(info.ai_usage_records) || 0) + ' AI usage record' + (Number(info.ai_usage_records) === 1 ? '' : 's') + ' will be restored (or kept, if this machine already has some).') + '</div>';
      }
      if (info.has_ai_credentials) {
        h += '<div class="tiny" style="color:var(--amber);margin-top:.5rem">'
          + 'This backup contains your AI settings and API keys. Keys that already '
          + 'exist here will keep their current values — only missing ones are added.'
          + '</div>';
      }
      this._backupHasCredentials = !!info.has_ai_credentials;
      if (missing.length) {
        h += '<div class="tiny" style="color:var(--amber);margin-top:.5rem">'
          + 'You do not have: ' + esc(missing.join(', ')) + '.</div>'
          + '<div class="tiny muted">Their records still restore; they simply stay '
          + 'unreadable until you install the matching module from the Store.</div>';
      }
      const conflicts = info.conflicts || [];
      if (conflicts.length) {
        h += '<div class="tiny" style="margin-top:.5rem;color:var(--amber)">'
          + conflicts.length + ' record' + (conflicts.length === 1 ? '' : 's')
          + ' differ from this machine. Choose what to keep:</div>';
        conflicts.forEach((c, i) => {
          h += '<div class="tiny" style="margin-top:4px">'
            + esc(c.kind + ' · ' + (c.label || c.id))
            + ' <label><input type="radio" name="bk-c-' + i
            + '" value="mine" checked> Keep mine</label>'
            + ' <label><input type="radio" name="bk-c-' + i
            + '" value="theirs"> Take theirs</label></div>';
        });
      } else {
        h += '<div class="tiny muted" style="margin-top:.5rem">Restoring never deletes and never overwrites what is already on this machine.</div>';
      }
      h += '<div class="row" style="margin-top:.5rem">'
        + '<button class="btn primary" id="bk-go">Restore</button>'
        + '<button class="btn" id="bk-cancel">Cancel</button>'
        + (missing.length ? '<button class="btn" id="bk-open-store">Open Store</button>' : '')
        + '</div>';
      preview.innerHTML = h;
      const go = $('#bk-go');
      if (go) go.onclick = () => {
        if (!conflicts.length) { this.applyRestore(path); return; }
        const decisions = conflicts.map((c, i) => {
          const picked = document.querySelector(
            'input[name="bk-c-' + i + '"]:checked');
          return { kind: c.kind, id: c.id,
                   choice: picked ? picked.value : 'mine' };
        });
        this.applyChosen(path, decisions);
      };
      const cancel = $('#bk-cancel');
      if (cancel) cancel.onclick = () => { preview.style.display = 'none'; preview.innerHTML = ''; };
      const openStore = $('#bk-open-store'); if (openStore) openStore.onclick = () => App.show('store');
    });
  },

  async applyChosen(path, decisions) {
    const result = $('#bk-result'); const preview = $('#bk-preview');
    if (preview) { preview.style.display = 'none'; preview.innerHTML = ''; }
    if (!result) return;
    result.style.display = '';
    result.innerHTML = '<div class="tiny">Applying your choices…</div>';
    const pw = this._backupPassphrase || '';
    this._backupPassphrase = '';
    const r = await post('backup/apply-chosen', {
      path, passphrase: pw, decisions,
    });
    if (!r || r.ok === false) {
      result.innerHTML = '<div class="st-body" style="color:var(--error)">'
        + esc((r && r.error) || 'Restore failed.') + '</div>';
      return;
    }
    this._stashRestore(r);
    result.innerHTML = '<div class="st-body"><b>Applied ' + ((r.applied || []).length)
      + ' chosen records — refreshing…</b></div>';
    toast('Restored your choices — refreshing G-Bible…', 'ok');
    setTimeout(() => location.reload(), 400);
  },

  async applyRestore(path) {
    const result = $('#bk-result'); const preview = $('#bk-preview');
    if (preview) { preview.style.display = 'none'; preview.innerHTML = ''; }
    if (!result) return;
    result.style.display = '';
    result.innerHTML = '<div class="tiny">Restoring…</div>';
    const pw = this._backupPassphrase || '';
    this._backupPassphrase = '';
    const r = await post('backup/apply', {
      path,
      passphrase: pw,
      include_ai: this._backupHasCredentials ? 1 : 0,
      apply_deletes: ($('#bk-apply-deletes') && $('#bk-apply-deletes').checked) ? 1 : 0,
    });
    if (!r || r.ok === false) {
      result.innerHTML = '<div class="st-body" style="color:var(--error)">'
        + esc((r && r.error) || 'Restore failed.') + '</div>';
      return;
    }
    /* Appearance lives in this browser's storage, not the database — the
       server cannot apply it.  Write it now so the reload boots with it. */
    if (r.appearance) {
      try {
        localStorage.setItem('gbible:appearance', JSON.stringify(r.appearance));
      } catch (e) { /* cosmetic; never block a restore over it */ }
    }
    /* The restore changed settings, keys and records under the running app.
       Hand a short summary to the next boot and reload — a clean page is the
       reliable way to pick it all up.  The boot hook renders the summary. */
    const missing = r.modules_missing || [];
    this._stashRestore(r);
    result.innerHTML = '<div class="st-body"><b>Restore complete — refreshing…</b></div>';
    toast('Restored — refreshing G-Bible…', 'ok');
    setTimeout(() => location.reload(), 400);
  },

  async missingModules() {
    const r = await api('sync/missing_modules');
    if (!r || r.ok === false) return null;   // do not claim "everything synced"
    return r.missing || [];
  },

  async installMissing(missing) {
    const host = $('#modal-body');
    if (host) {
      host.innerHTML = '<div class="tiny">Installing the missing resources…</div>';
    }
    try {
      const r = await post('sync/install_missing_modules', { modules: missing });
      if (!r || r.ok === false) {
        toast((r && r.error) || 'Could not install those resources.', 'err');
        return;
      }
      const done = (r.installed || []).length;
      const already = (r.already || []).length;
      const failed = (r.failed || []).length;
      const unknown = (r.not_found || []).length;
      const summary = 'Installed ' + done + ', already present ' + already
        + (failed ? ', failed ' + failed : '')
        + (unknown ? ', not in the Store ' + unknown : '');
      if (host) host.innerHTML = '<div class="st-body">' + esc(summary) + '</div>';
      toast(summary, failed || unknown ? 'warn' : 'ok');
    } catch (e) {
      toast('Install failed: ' + (e.message || e), 'err');
    }
  },

  async showSyncCompleteModal() {
    try {
      const missing = await this.missingModules();
      if (missing === null) {
        const body = '<div class="st-body"><b>Backup written.</b></div>'
          + '<div class="tiny muted">The module check could not be read, so it '
          + 'is not known whether every referenced resource is installed.</div>';
        modal('Sync complete', body, [{ label: 'Done', cls: 'btn primary' }]);
        return;
      }
      let body;
      if (missing.length) {
        body = '<div class="st-body"><b>Everything synced.</b></div>'
          + '<div class="tiny muted" style="margin-top:.5rem">One honest note: some of your records reference modules that aren&apos;t installed yet. They were synced — they will just be unreadable until you install the matching modules.</div>'
          + '<div class="tiny" style="margin-top:.5rem;color:var(--amber)">Not installed yet: ' + esc(missing.join(', ')) + '</div>';
      } else {
        body = '<div class="st-body"><b>Everything synced.</b></div>'
          + '<div class="tiny muted">Your notes, highlights and plans are now up to date on this machine.</div>';
      }
      modal("Sync complete", body, [
        { label: 'Done', cls: 'btn primary', hidePrint: true },
        ...(missing.length ? [
          { label: 'Install these now', cls: 'btn primary', close: false,
            fn: () => this.installMissing(missing) },
          { label: 'Open Store', cls: 'btn', fn: () => App.show('store') },
        ] : []),
      ]);
    } catch (e) {
      /* a failed info pop-up must never mask a successful sync */
    }
  },

  formCard(r) {
    const card = el('div', 'dash-card');
    card.appendChild(el('div', 'dash-h', r.configured ? 'Change target' : 'From this computer · WebDAV · Nextcloud'));
    card.appendChild(el('div', 'st-body',
      'Pressing Sync now writes one file — gbible-backup.gbz — to the target below. '
      + 'Restoring pulls the same file back. Everything you need travels; modules never do, '
      + 'so your notes stay yours.'));
    const kind = r.kind || '';
    const wrap = el('div', 'sync-form');

    const sel = el('select', 'st-lbl');
    [['', 'Choose where the backup lives…'],
     ['filesystem', 'From this computer (a folder, or a drive attached to it)'],
     ['webdav', 'WebDAV'],
     ['nextcloud', 'Nextcloud']].forEach(([v, l]) => {
      const o = el('option', '', l); o.value = v;
      if (kind === v) o.selected = true;
      sel.appendChild(o);
    });
    const row = (label, input, hint) => {
      const d = el('div', 'sync-field');
      d.appendChild(el('label', 'st-lbl', label));
      d.appendChild(input);
      if (hint) d.appendChild(el('div', 'tiny muted', hint));
      wrap.appendChild(d);
      return d;
    };
    row('Target', sel);

    const fs = el('input', 'st-lbl'); fs.type = 'text'; fs.id = 'sync-path';
    fs.value = r.path || '';
    fs.placeholder = '/home/you/gbible-sync';
    const fsRow = el('div', '', '');
    fsRow.style.cssText = 'display:flex;gap:6px;align-items:center';
    fsRow.appendChild(fs);
    const browse = el('button', 'btn');
    browse.id = 'sync-fs-browse';
    browse.textContent = 'Browse…';
    browse.onclick = () => {
      ImportWizard._browse(fs.value || '', 'pick-folder', (chosen) => {
        const input = document.getElementById('sync-path');
        if (input) input.value = chosen;
      });
    };
    fsRow.appendChild(browse);
    fs.style.flex = '1';
    const fsHint = 'It must already exist. A second disk or a NAS counts.';
    const fsWrap = el('div', 'sync-field');
    fsWrap.appendChild(el('label', 'st-lbl', 'Folder'));
    fsWrap.appendChild(fsRow);
    fsWrap.appendChild(el('div', 'tiny muted', fsHint));
    wrap.appendChild(fsWrap);

    const srv = el('input', 'st-lbl'); srv.type = 'text'; srv.id = 'sync-server';
    srv.value = (r.url || '').replace(/^https?:\/\/[^/]+\/remote\.php\/dav\/files\/[^/]+\/?/, '');
    srv.placeholder = 'cloud.example.com';
    row('Server', srv, 'The address of your Nextcloud, without https://');

    const usr = el('input', 'st-lbl'); usr.type = 'text'; usr.id = 'sync-user';
    usr.value = r.user || '';
    row('User name', usr);

    const wu = el('input', 'st-lbl'); wu.type = 'text'; wu.id = 'sync-url';
    wu.value = r.url || '';
    wu.placeholder = 'https://cloud.example.com/remote.php/dav/files/you/gbible-sync';
    row('WebDAV URL', wu, 'The folder that holds the sync files. Must be https.');

    const pw = el('input', 'st-lbl'); pw.type = 'password'; pw.id = 'sync-pw';
    pw.placeholder = r.kind && r.kind !== 'filesystem' ? 'saved — leave blank to keep' : '';
    row('App password', pw, 'For Nextcloud, use an app password, not your login. '
      + 'It is kept in a file only this app can read, not in your library.');

    const iv = el('select', 'st-lbl'); iv.id = 'sync-interval';
    (r.intervals || []).forEach(o => {
      const op = el('option', '', o.label); op.value = o.value;
      if (Number(r.interval || 0) === Number(o.value)) op.selected = true;
      iv.appendChild(op);
    });
    row('How often', iv, 'The app syncs in the background while it is open.');

    const wifi = el('input', ''); wifi.type = 'checkbox'; wifi.id = 'sync-wifi';
    wifi.checked = !!r.wifi_only;
    const wifiLabel = el('label', '', '');
    wifiLabel.style.cssText = 'display:inline-flex;align-items:center;gap:8px;cursor:pointer';
    wifiLabel.appendChild(wifi);
    wifiLabel.appendChild(el('span', 'st-lbl', 'Skip sync on metered connections'));
    const wf = el('div', 'sync-field');
    wf.appendChild(wifiLabel);
    wf.appendChild(el('div', 'tiny muted', r.metered === null
      ? 'Whether this connection is metered cannot be told (NetworkManager was '
        + 'not found), so sync stays paused until it can.'
      : 'Metered connections — a phone hotspot, say — will be left alone.'));
    wrap.appendChild(wf);

    const ab = el('input', 'st-lbl'); ab.type = 'number'; ab.id = 'sync-autobackup'; ab.min = '0'; ab.max = '168';
    ab.value = r.auto_backup_hours || 0;
    row('Auto-backup (hours)', ab, '0 disables. Writes a timestamped .gbz to data/backups in the background.');

    const show = () => {
      const v = sel.value;
      fsWrap.style.display = v === 'filesystem' ? '' : 'none';
      srv.parentElement.style.display = v === 'nextcloud' ? '' : 'none';
      usr.parentElement.style.display = v === 'nextcloud' ? '' : 'none';
      wu.parentElement.style.display = v === 'webdav' ? '' : 'none';
      pw.parentElement.style.display = (v === 'filesystem' || !v) ? 'none' : '';
      wf.style.display = v ? '' : 'none';
    };
    sel.onchange = show;
    show();
    card.appendChild(wrap);

    const enc = el('input', ''); enc.type = 'checkbox'; enc.id = 'sync-encrypt';
    enc.checked = !!r.encrypt;
    const encLabel = el('label', '', '');
    encLabel.style.cssText = 'display:inline-flex;align-items:center;gap:8px;cursor:pointer';
    encLabel.appendChild(enc);
    encLabel.appendChild(el('span', 'st-lbl', 'Encrypt the sync file'));
    const encWrap = el('div', 'sync-field');
    encWrap.appendChild(encLabel);
    encWrap.appendChild(el('div', 'tiny muted', 'Protects the backup on the target with a passphrase. '
      + 'Use at least 12 characters. The same passphrase must be set on every device that reads it.'));
    wrap.appendChild(encWrap);

    const encPw = el('input', 'st-lbl'); encPw.type = 'password'; encPw.id = 'sync-enc-pw';
    encPw.placeholder = r.encrypt ? 'saved — leave blank to keep' : '';
    const encPwRow = el('div', 'sync-field');
    encPwRow.appendChild(el('label', 'st-lbl', 'Encryption passphrase'));
    encPwRow.appendChild(encPw);
    wrap.appendChild(encPwRow);

    const bar = el('div', 'row', '');
    bar.style.marginTop = '10px';
    const save = el('button', 'btn primary', 'Save and sync once');
    save.onclick = () => this.save(save);
    bar.appendChild(save);
    card.appendChild(bar);
    return card;
  },

  async save(btn) {
    const kind = $('#sync-body').querySelector('.sync-form select').value;
    const out = { kind: kind, interval: $('#sync-interval').value,
                  wifi_only: $('#sync-wifi').checked ? 1 : 0,
                  encrypt: $('#sync-encrypt').checked ? 1 : 0,
                  auto_backup_hours: parseInt($('#sync-autobackup').value, 10) || 0 };
    if ($('#sync-enc-pw').value) out.passphrase = $('#sync-enc-pw').value;
    if (kind === 'filesystem') out.path = $('#sync-path').value.trim();
    if (kind === 'nextcloud') {
      out.server = $('#sync-server').value.trim();
      out.user = $('#sync-user').value.trim();
    }
    if (kind === 'webdav') {
      out.url = $('#sync-url').value.trim();
      out.user = $('#sync-user').value.trim();
    }
    if (kind && kind !== 'filesystem' && $('#sync-pw').value) {
      out.password = $('#sync-pw').value;
    }
    btn.disabled = true; btn.textContent = 'Checking the target…';
    let r = null;
    try { r = await post('sync/configure', out); }
    catch (e) { toast(e.message || 'Could not save that target.', 'err'); }
    btn.disabled = false; btn.textContent = 'Save and sync';
    if (!r || r.ok === false) { toast((r && r.error) || 'Could not save that target.', 'err'); return; }
    if (!kind) { toast('Sync turned off. Nothing was deleted.'); App.show('sync'); return; }
    // The button says it syncs, so it syncs: the reader pressed it once and
    // expects the first transfer to have happened.
    await this.runNow(btn);
  },

  async runNow(btn) {
    btn.disabled = true; const old = btn.textContent; btn.textContent = 'Syncing…';
    let r;
    // Honour the saved network policy on a manual press too. Only an explicit
    // "sync anyway" after a metered skip sends force.
    try { r = await post('sync/run', {}); }
    catch (e) { toast(e.message || 'Sync failed.', 'err'); }
    btn.disabled = false; btn.textContent = old;
    if (!r) return;
    if (r.skipped) {
      const unknown = r.skipped === 'unknown-metered';
      const label = r.error || r.last_error || 'Sync was skipped.';
      if (!confirm(label + (unknown
        ? '\n\nSync anyway? The connection may be metered.'
        : '\n\nSync anyway?'))) { toast(label, 'warn'); return; }
      btn.disabled = true; btn.textContent = 'Syncing…';
      try { r = await post('sync/run', { force: 1 }); }
      catch (e) { toast(e.message || 'Sync failed.', 'err'); }
      btn.disabled = false; btn.textContent = old;
      if (!r || r.ok === false || r.skipped) {
        toast((r && (r.error || r.last_error)) || 'Sync failed.', 'err'); return;
      }
    }
    if (r.ok === false) { toast(r.error || 'Sync failed.', 'err'); return; }
    {
      const bits = [];
      if (r.records) bits.push(r.records + ' records');
      if (r.bytes) bits.push(Math.round(r.bytes / 1024) + ' KB');
      toast(bits.length ? 'Backed up: ' + bits.join(', ') + '.'
        : 'Backup written.', 'ok');
      /* Synced successfully — tell the reader if any of the personal records
         they just received reference modules that aren't installed, so they
         know why their notes can't be opened. */
      this.showSyncCompleteModal().catch(() => {});
    }
    App.show('sync');
  },
};

function relTime(t) {
  const d = (Date.now() / 1000) - Number(t || 0);
  if (d < 45) return 'just now';
  if (d < 3600) return Math.round(d / 60) + ' min ago';
  if (d < 86400) return Math.round(d / 3600) + 'h ago';
  return Math.round(d / 86400) + ' days ago';
}

/* Everything below this line is definitions: `App.boot()` above runs
   synchronously as far as its first await, and it calls bind(), which
   reaches these objects.  A `const` declared after that call is still in
   its temporal dead zone and throws a ReferenceError, so new sections go
   ABOVE the boot call, not below it.                                     */