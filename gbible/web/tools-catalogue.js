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
      + '<option value="type">by kind</option>'
      + '<option value="lang">by language</option>'
      + '<option value="source">by source</option>'
      + '<option value="author">by author</option>'
      + '</select></label>'
      + '<label>Format <select id="ct-f">'
      + '<option value="pdf">PDF — for handing to someone</option>'
      + '<option value="csv">CSV — a spreadsheet</option>'
      + '<option value="html">HTML</option>'
      + '<option value="txt">Plain text</option>'
      + '<option value="md">Markdown</option>'
      + '</select></label>'
      + '<label><input type="checkbox" id="ct-d" checked> every column</label>'
      + '</div>'
      + '<div class="ct-exports" id="ct-go"></div>'
      + '<div class="tiny muted">A PDF prints one resource per line with its '
      + 'licence, which is the column that matters.</div>';

    const url = (f) => '/file/catalog?fmt=' + encodeURIComponent(f)
      + '&group=' + encodeURIComponent($('#ct-g').value)
      + '&detail=' + ($('#ct-d').checked ? '1' : '0');

    const build = () => {
      const f = $('#ct-f').value;
      $('#ct-go').innerHTML = (f === 'html' || f === 'pdf'
        ? '<button class="ct-fmt ct-print" id="ct-print">Print it</button>' : '')
        + '<button class="ct-fmt" id="ct-dl">Download</button>';
      $('#ct-dl').onclick = () => {
        Cite._save(url(f), 'library-catalogue.' + f);
        toast('Saved library-catalogue.' + f + '.');
      };
      const pr = $('#ct-print');
      /* Printed through the same iframe the passage exporter uses, so the
       * browser's own print dialog gets the app's own print stylesheet rather
       * than a screenshot of a document. */
      if (pr) pr.onclick = async () => {
        const r = await fetch(url('html'));
        Cite._printHtml(await r.text(), 'Library catalogue');
      };
    };
    $('#ct-g').onchange = build;
    $('#ct-d').onchange = build;
    build();
  },
};

/* ==================================================================== Sync
 *
 * Annotations, moved between installs.  The folder layout, the manifest and the
 * merge rules are the server's (see docs/sync.md); what lives here is the door
 * into them: pick a target, pick how often, see what happened.
 *
 * Two things it deliberately does not do.  It does not show a password back
 * once saved, and it does not let a target be chosen that cannot be reached --
 * the server probes before it stores, so a mistyped path is found here rather
 * than at 3am when the app quietly fails to sync.
 */