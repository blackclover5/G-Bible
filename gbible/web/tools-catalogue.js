const Catalogue = {
  async open() {
    modal('Library catalogue', '<div class="st-loading">Reading the library…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const s = await api('catalog/summary');
    if (!s.ok) { $('#modal-body').innerHTML = '<div class="warn">'
      + esc(s.error || '') + '</div>'; return; }

    const bar = (l, n) => '<div class="dash-h" style="margin-top:10px">'
      + esc(l) + ' <span class="tiny muted">' + n + '</span></div>'
      + '<div>' + s[l].slice(0, 12).map(x =>
        '<div class="chart-sm"><span class="lbl">' + esc(x.label)
        + '</span><span class="v">' + x.n + '</span></div>').join('') + '</div>';

    $('#modal-body').innerHTML =
      '<div class="st-body">' + s.total + ' resources installed'
      + (s.blank_author ? ' · <b>' + s.blank_author + '</b> have no author '
          + 'recorded, which is what the source said' : '') + '.</div>'
      + bar('by_type', s.by_type.length)
      + bar('by_lang', s.by_lang.length)
      + bar('by_source', s.by_source.length)
      + '<div class="dash-h" style="margin-top:14px">Make one</div>'
      + '<div class="st-tools" style="gap:6px;flex-wrap:wrap">'
      + '<label>Grouped <select id="ct-g">'
      + (s.groups || []).map(g => '<option value="' + esc(g) + '">'
        + esc(g) + '</option>').join('')
      + '</select></label>'
      + '<label>Format <select id="ct-f">'
      + (s.formats || []).map(f => '<option value="' + esc(f) + '">'
        + esc(f) + '</option>').join('')
      + '</select></label>'
      + '<label><input type="checkbox" id="ct-d" checked> every column</label>'
      + '</div>'
      + '<div class="ct-exports" id="ct-go"></div>'
      + '<div class="tiny muted">With “every column” on, each row carries its '
      + 'licence. Turned off, a PDF prints only titles, types and abbreviations.</div>';

    const url = (f) => '/file/catalog?fmt=' + encodeURIComponent(f)
      + '&group=' + encodeURIComponent($('#ct-g').value)
      + '&detail=' + ($('#ct-d').checked ? '1' : '0');

    const build = () => {
      // Read the format when the button is clicked: changing only the format
      // select used to leave the download on the old value and extension.
      $('#ct-go').innerHTML = '<button class="ct-fmt" id="ct-dl">Download</button>';
      $('#ct-dl').onclick = async () => {
        const f = $('#ct-f').value;
        const ok = await Cite.download(url(f), 'library-catalogue.' + f);
        if (ok) toast('Saved library-catalogue.' + f + '.');
      };
    };
    ['#ct-g', '#ct-d', '#ct-f'].forEach(id => { const e = $(id); if (e) e.onchange = build; });
    build();
  },
};
