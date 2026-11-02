const GUIDE_COVERED = ['commentaries', 'people', 'places', 'crossrefs'];

/* The configured guide, rendered.
 *
 * `openPassage` fetched `guide/run` and then rendered only its own five fixed
 * sections, so every section the reader had configured -- and every section
 * added to the guide since -- was fetched and thrown away.  The guide selector
 * at the top of the panel switched between guides that all looked identical,
 * and `guide/config` was written by the editor and read by nothing.
 *
 * Folded rather than laid out flat: a section with nothing installed says so
 * in one muted line, which is the point of it, but ten such lines is noise on
 * every passage. */
function configuredGuideHtml(g) {
  const cfg = (g && g.ok ? g.sections || [] : [])
    .filter(s => GUIDE_COVERED.indexOf(s.id) < 0);
  if (!cfg.length) return '';
  const row = (it) => {
    const head = it.title || it.event || it.name || it.word
      || it.subject || it.label || '';
    const txt = it.text || it.comment || it.gloss || it.preview || '';
    const per = it.pericopes ? Object.keys(it.pericopes)
      .map(k => esc(k) + ' ' + esc(it.pericopes[k])).join(' · ') : '';
    const open = (it.module_id && it.key)
      ? '<div class="tiny"><a href="#" data-open="' + esc(it.module_id)
        + '" data-key="' + esc(it.key) + '">Open in a pane</a></div>' : '';
    return '<div class="st-note">'
      + (head ? '<div class="st-src">' + esc(head) + '</div>' : '')
      + (txt ? '<div class="st-body">' + esc(txt) + '</div>' : '')
      + (per ? '<div class="st-body">' + per + '</div>' : '')
      + open + '</div>';
  };
  const withItems = cfg.filter(s => (s.items || []).length);
  const bare = cfg.filter(s => !(s.items || []).length && s.note);
  return '<details class="st-sec"><summary class="st-h">Configured guide'
    + ' <span class="tiny muted">· ' + cfg.length + ' section'
    + (cfg.length === 1 ? '' : 's') + '</span></summary>'
    + (withItems.length
      ? withItems.map(s => '<div class="st-head">' + esc(s.title || s.id)
        + ' <span class="muted tiny">· ' + s.items.length
        + (s.note ? ' · ' + esc(s.note) : '') + '</span></div>'
        + s.items.map(row).join('')).join('')
      : '')
    + bare.map(s => '<div class="tiny muted">' + esc(s.title || s.id)
      + ': ' + esc(s.note) + '</div>').join('')
    + '</details>';
}
