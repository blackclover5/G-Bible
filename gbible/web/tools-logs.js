/* Logs — the app's own error log.  Nothing leaves this machine unless the
 * reader presses Report on one entry, which opens a pre-filled GitHub issue
 * in their browser — they read it and press submit themselves. */
const Logs = {
  async load() {
    const host = $('#logs-body');
    host.innerHTML = '<div class="loading">Loading…</div>';
    const r = await api('logs/list', { limit: 200 });
    const entries = (r && r.entries) || [];
    const count = entries.length;
    setStatusErrors(count);
    if (!count) {
      host.innerHTML = '<div class="empty">Nothing logged. If something breaks, it shows up here.</div>';
      return;
    }
    const gh = await api('logs/report/status');
    let h = '<div class="tiny muted" style="margin:8px 0">' + count
      + ' entr' + (count === 1 ? 'y' : 'ies') + ' — newest last. '
      + (gh && gh.authorized
          ? '<a href="#" id="logs-gh-forget">GitHub authorised — sign out</a>'
          : 'Not signed in to GitHub — one is asked the first time you report.')
      + '</div>';
    entries.forEach((e, i) => {
      const when = new Date(Number(e.t || 0) * 1000);
      const time = isNaN(when.getTime()) ? '' : when.toLocaleString();
      h += '<details class="logs-entry"><summary>'
        + '<span class="logs-src">' + esc(e.source || 'error') + '</span>'
        + '<span class="logs-msg">' + esc((e.message || '').slice(0, 160)) + '</span>'
        + '<span class="logs-time tiny muted">' + esc(time) + '</span>'
        + '</summary>'
        + '<div class="logs-detail">'
        + '<div class="tiny muted" style="margin:6px 0 2px">Full message</div>'
        + '<pre class="logs-pre">' + esc(e.message || '') + '</pre>'
        + (e.tb ? '<div class="tiny muted" style="margin:6px 0 2px">Stack trace</div><pre class="logs-pre">' + esc(e.tb) + '</pre>' : '')
        + '<div style="margin-top:8px"><button class="btn tiny" data-report="' + i + '">Report this error</button></div>'
        + '</div></details>';
    });
    host.innerHTML = h;
    host.querySelectorAll('[data-report]').forEach(btn => {
      btn.onclick = () => this.report(entries[Number(btn.dataset.report)]);
    });
    const clear = $('#logs-clear');
    if (clear) clear.onclick = async () => {
      if (!confirm('Clear the error log? This can not be undone.')) return;
      const r2 = await post('logs/clear', {});
      toast('Logs cleared.');
      this.load();
    };
    const close = $('#logs-close');
    if (close) close.onclick = () => App.show('today');
    const forget = $('#logs-gh-forget');
    if (forget) forget.onclick = async (e) => {
      e.preventDefault();
      if (!confirm('Forget G-Bible\u2019s GitHub authorization? You can re-authorize anytime.')) return;
      await post('logs/report/forget', {});
      toast('Signed out of GitHub.');
      this.load();
    };
  },

  _ghBody(e) {
    const version = (document.querySelector('meta[name="gbible-version"]') || {}).content || 'unknown';
    const when = new Date((Number(e.t) || Date.now() / 1000) * 1000);
    return [
      '**G-Bible ' + version + '**',
      'Source: ' + (e.source || 'unknown'),
      'Time: ' + when.toISOString().replace('T', ' ').slice(0, 19) + 'Z',
      '',
      '**Message**',
      '```',
      (e.message || '').slice(0, 1200),
      '```',
      e.tb ? '**Stack**\n```\n' + e.tb.slice(0, 1800) + '\n```' : ''
    ].filter(Boolean).join('\n');
  },

  async report(e) {
    const body = this._ghBody(e);
    const version = (document.querySelector('meta[name="gbible-version"]') || {}).content || '';
    const title = 'Bug: ' + String(e.message || 'unknown error').slice(0, 70);
    // If this machine is already authorised, no ceremony — file directly.
    const status = await api('logs/report/status');
    if (status && status.authorized) {
      const ok = confirm('File this error as a GitHub issue now?\n\n' + title);
      if (!ok) return;
      return this._fileIssue(title, body);
    }
    // Otherwise run the device flow.
    const r = await post('logs/report/start', {});
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not contact GitHub.', 'err');
      return;
    }
    this._pollStop = false;
    this._ghInterval = Number(r.interval) || 5;
    const deviceCode = r.device_code;
    const html = '<p>'
      + 'G-Bible will file this issue as you on <b>blackclover5/G-Bible</b>. '
      + 'Authorize G-Bible for <code>Issues: write</code> at:'
      + '</p>'
      + '<p><a href="' + esc(r.verification_uri) + '" target="_blank" rel="noopener">'
      + esc(r.verification_uri) + '</a></p>'
      + '<div class="gh-auth-code">' + esc(r.user_code) + '</div>'
      + '<p class="tiny muted">Code expires in ~15 minutes.</p>'
      + '<p class="tiny muted" id="gh-status">Waiting for you to authorize G-Bible in your browser…</p>';
    const buttons = [
      { label: 'Cancel', cls: 'btn' },
      { label: "I've entered the code", cls: 'btn primary', close: false,
        fn: () => this._fileWhenReady(e, body, title, deviceCode) },
    ];
    modal('Authorize G-Bible to file issues', html, buttons);
    this._pollForGitHub(deviceCode, this._ghInterval, async () => {
      await this._fileWhenReady(e, body, title, deviceCode);
    });
  },

  async _fileWhenReady(e, body, title, deviceCode) {
    // GitHub issues the token once per device code — if our server already has one, use it.
    const status = await api('logs/report/status');
    if (status && status.authorized) {
      await this._fileIssue(title, body);
      return;
    }
    const r = await post('logs/report/poll', { device_code: deviceCode });
    if (r && r.authorized) {
      await this._fileIssue(title, body);
      return;
    }
    const s = $('#gh-status');
    if (s) s.textContent = 'Not authorized yet — enter the code at github.com/login/device, then press the button again.';
  },

  async _pollForGitHub(deviceCode, interval, done) {
    let tries = 0;
    const tick = async () => {
      if (this._pollStop) return;
      const r = await post('logs/report/poll', { device_code: deviceCode });
      if (r && r.authorized) {
        const s = $('#gh-status'); if (s) { s.textContent = 'Authorized — filing…'; }
        await this._fileIssue(title, body);
        return;
      }
      if (r && r.ok === false) {
        const s = $('#gh-status');
        if (s) s.textContent = 'GitHub said: ' + esc(r.error || 'authorization failed') + '.';
        return;
      }
      tries += 1;
      const s = $('#gh-status');
      if (s && r && r.slow_down) {
        s.textContent = 'GitHub wants us to slow down — retrying in 10s…';
        setTimeout(tick, 10000);
        return;
      }
      if (s) s.textContent = 'Waiting for authorization… (' + (tries * (interval || 5)) + 's)';
      if (tries > 140) {
        if (s) s.textContent = 'Timed out waiting. Click “I\'ve entered the code” once you finish.';
        return;
      }
      setTimeout(tick, interval * 1000);
    };
    tick();
  },

  async _fileIssue(title, body) {
    const r = await post('logs/report/file', { title, body });
    if (!r || r.ok === false) {
      toast((r && r.error) || 'Could not file the issue.', 'err');
      return;
    }
    closeModal();
    toast('Filed as issue #' + r.number, 'ok');
    window.open(r.url, '_blank', 'noopener');
  },

  async clientError(message, stack, src) {
    try {
      await post('logs/client-error', { message: String(message).slice(0, 480),
                                        stack: String(stack || '').slice(0, 2000),
                                        source: src || 'ui' });
      refreshErrorPill();
    } catch (e) { /* never cascade an error about an error */ }
  },
};

function setStatusErrors(count) {
  const pill = $('#status-errors');
  if (!pill) return;
  pill.hidden = !(count > 0);
  pill.textContent = count === 1 ? 'Error found' : count + ' errors found';
}

async function refreshErrorPill() {
  try {
    const r = await api('logs/count');
    setStatusErrors(Number((r && r.count) || 0));
  } catch (e) { /* stay quiet; the pill simply stays */ }
}

/* Surface G-Bible's own faults to the log.  Extension errors and "browser
   faults" are ignored — only errors raised by our own files qualify. */
window.addEventListener('error', (e) => {
  try {
    if (e && e.filename && /(extension:|moz-extension:|chrome-extension:)/i.test(e.filename)) return;
    if (e && e.filename && /(^https?:|^chrome|^moz|^data:)/i.test(e.filename) && !e.filename.includes(window.location.hostname)) return;
    Logs.clientError(e && e.message ? e.message : String(e),
                     (e && e.error && e.error.stack) || '',
                     'ui');
  } catch (_) { /* ignore */ }
}, true);
window.addEventListener('unhandledrejection', (e) => {
  try {
    const reason = e && e.reason;
    const msg = reason && reason.message ? reason.message
              : reason && reason.toString ? String(reason)
              : String(reason);
    const stack = reason && reason.stack ? reason.stack : '';
    Logs.clientError(msg, stack, 'ui');
  } catch (_) { /* ignore */ }
});

/* The pill reflects reality from the first moment the app boots. */
(function refresh() {
  try { refreshErrorPill(); } catch (e) { /* ignore */ }
})();
