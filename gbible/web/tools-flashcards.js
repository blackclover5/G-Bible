const Flashcards = {
  /* Drill over your own lists. The front names the place, the back shows the
   * text — flip, then mark known or unknown. Score survives in the session. */
  async open(source, id) {
    const r = await post('flash', { action: 'start', source, id });
    if (!r.ok) { toast(r.error || 'Nothing to drill on.', 'warn'); return; }
    this.show();
  },
  async show() {
    const r = await api('flash', {});
    if (!r.ok) { toast(r.error || 'No session.', 'warn'); return; }
    const c = r.card || {};
    const pct = r.total ? Math.round(100 * (r.known + r.unknown) / r.total) : 0;
    modal('Flashcards — ' + (r.title || ''),
      '<div class="tiny muted">Card ' + (r.pos + 1) + ' of ' + r.total
      + ' · ✓ ' + r.known + ' · ✗ ' + r.unknown + ' · ' + pct + '% scored</div>'
      + '<div class="dash-card" style="margin:10px 0;min-height:90px">'
      + '<div class="dash-h">' + esc(c.front || '?') + '</div>'
      + '<div id="fl-back" style="display:none;white-space:pre-wrap;margin-top:6px">'
      + esc(c.back || '') + '</div></div>'
      + '<div class="row wrap"><button class="btn primary" id="fl-flip">Flip</button>'
      + '<button class="btn" id="fl-yes" disabled>✓ Knew it</button>'
      + '<button class="btn" id="fl-no" disabled>✗ Missed it</button>'
      + ((c.module_id && c.unit_key)
        ? '<button class="btn" id="fl-open">Open verse</button>' : '')
      + '</div>'
      + (r.done ? '<div class="tiny muted" style="margin-top:6px">Round complete — '
        + 'start again any time from the list.</div>' : ''),
      [{ label: 'Close', cls: 'btn' }]);
    $('#fl-flip').onclick = () => {
      $('#fl-back').style.display = '';
      $('#fl-yes').disabled = false;
      $('#fl-no').disabled = false;
    };
    const score = async (known) => {
      await post('flash', { action: 'score', known });
      this.show();
    };
    $('#fl-yes').onclick = () => score(true);
    $('#fl-no').onclick = () => score(false);
    const op = $('#fl-open');
    if (op) op.onclick = () => {
      closeModal();
      App.show('workspace');
      Workspace.openModule(c.module_id, { ref: c.front, span: 'verse' });
    };
  },
};
