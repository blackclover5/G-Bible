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
    host.appendChild(this.formCard(r));
    $('#sync-summary').innerHTML = this.summaryLine(r);
  },

  summaryLine(r) {
    if (!r.configured) {
      return 'Your notes, highlights, reading progress, pane layouts and '
        + 'collections can travel to another computer — and to a phone — '
        + 'without the library being copied.';
    }
    const when = r.last_ok ? relTime(r.last_ok) : 'never';
    let s = 'Syncing ' + esc(r.kind === 'nextcloud' ? 'to Nextcloud'
      : r.kind === 'webdav' ? 'to a WebDAV server' : 'to ' + (r.path || 'a folder'))
      + ' · last synced ' + esc(when) + ' · ' + totalCounts(r.counts) + ' records';
    if (r.last_error) s += ' · <span style="color:var(--red)">' + esc(r.last_error) + '</span>';
    return s;
  },

  stateCard(r) {
    const card = el('div', 'dash-card');
    const h = el('div', 'dash-h', r.configured ? 'Sync' : 'Not set up');
    card.appendChild(h);
    if (!r.configured) {
      card.appendChild(el('div', 'st-body',
        'Nothing is synced yet. Choose a target below and the next sync will '
        + 'push everything you have written; nothing is changed here in the '
        + 'meantime.'));
      return card;
    }
    const rows = el('div', 'sync-rows');
    const line = (k, v) => {
      const d = el('div', 'sync-row');
      d.appendChild(el('span', 'k', k));
      d.appendChild(el('span', 'v', v));
      rows.appendChild(d);
    };
    line('Target', esc(r.kind === 'nextcloud' ? 'Nextcloud — ' + (r.user || '')
      : r.kind === 'webdav' ? esc(r.url) : esc(r.path)));
    line('Last sync', r.last_ok ? relTime(r.last_ok) : 'not yet');
    line('This device', esc(r.device_id) + ' <span class="tiny muted">'
      + (r.metered === null ? '(connection cannot be checked)'
        : r.metered ? '(metered connection)' : '(unmetered)') + '</span>');
    card.appendChild(rows);
    const counts = el('div', 'row wrap', '');
    counts.style.marginTop = '8px';
    if (Object.keys(r.counts || {}).length) {
      Object.keys(r.counts).sort().forEach(k => {
        counts.appendChild(el('span', 'sync-chip', esc(k) + ' ' + r.counts[k]));
      });
    } else {
      counts.appendChild(el('span', 'tiny muted', 'no records synced yet'));
    }
    card.appendChild(counts);
    const bar = el('div', 'row', '');
    bar.style.marginTop = '10px';
    const now = el('button', 'btn primary', 'Sync now');
    now.onclick = () => this.runNow(now);
    bar.appendChild(now);
    const off = el('button', 'btn', 'Turn sync off');
    off.onclick = async () => {
      await post('sync/configure', { kind: '' });
      toast('Sync turned off. Nothing was deleted.');
      App.show('sync');
    };
    bar.appendChild(off);
    if (r.tombstones) {
      bar.appendChild(el('span', 'tiny muted',
        r.tombstones + ' delete' + (r.tombstones === 1 ? '' : 's')
        + ' still travelling to other devices'));
    }
    card.appendChild(bar);
    return card;
  },

  formCard(r) {
    const card = el('div', 'dash-card');
    card.appendChild(el('div', 'dash-h', r.configured ? 'Change target' : 'Where to sync'));
    const kind = r.kind || '';
    const wrap = el('div', 'sync-form');

    const sel = el('select', 'st-lbl');
    [['', 'Choose a target…'],
     ['filesystem', 'A folder on this computer (or a drive attached to it)'],
     ['nextcloud', 'Nextcloud'],
     ['webdav', 'Another WebDAV server']].forEach(([v, l]) => {
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
    row('Folder', fs, 'It must already exist. A second disk or a NAS counts.');

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
    const wf = el('div', 'sync-field');
    wf.appendChild(wifi);
    wf.appendChild(el('span', 'st-lbl', 'Only over Wi-Fi or Ethernet'));
    wf.appendChild(el('div', 'tiny muted', r.metered === null
      ? 'Whether this connection is metered cannot be told (NetworkManager was '
        + 'not found), so this would pause sync until it can.'
      : 'Metered connections — a phone hotspot, say — will be left alone.'));
    wrap.appendChild(wf);

    const show = () => {
      const v = sel.value;
      fs.parentElement.style.display = v === 'filesystem' ? '' : 'none';
      srv.parentElement.style.display = v === 'nextcloud' ? '' : 'none';
      usr.parentElement.style.display = v === 'nextcloud' ? '' : 'none';
      wu.parentElement.style.display = v === 'webdav' ? '' : 'none';
      pw.parentElement.style.display = (v === 'filesystem' || !v) ? 'none' : '';
      wifi.parentElement.style.display = v ? '' : 'none';
    };
    sel.onchange = show;
    show();
    card.appendChild(wrap);

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
                  wifi_only: $('#sync-wifi').checked ? 1 : 0 };
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
    // force: the reader pressed the button, so their instruction outranks the
    // network policy -- which is otherwise the server's to apply on a timer.
    try { r = await post('sync/run', { force: 1 }); }
    catch (e) { toast(e.message || 'Sync failed.', 'err'); }
    btn.disabled = false; btn.textContent = old;
    if (!r) return;
    if (r.ok === false) { toast(r.error || 'Sync failed.', 'err'); return; }
    if (r.skipped) { toast(r.skipped === 'metered'
      ? 'Waiting for an unmetered connection.' : r.last_error || 'Skipped.', 'warn'); }
    else {
      const bits = [];
      if (r.pushed) bits.push(r.pushed + ' sent');
      if (r.pulled) bits.push(r.pulled + ' received');
      if (r.conflicts) bits.push(r.conflicts + ' conflicted');
      toast(bits.length ? 'Synced: ' + bits.join(', ') + '.'
        : 'Already up to date.', 'ok');
    }
    App.show('sync');
  },
};

function totalCounts(c) {
  let n = 0;
  for (const k in (c || {})) n += Number(c[k]) || 0;
  return String(n);
}

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