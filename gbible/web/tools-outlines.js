const Outlines = {
  book: 'Gen',
  chapter: 1,

  async load() {
    const body = $('#g-body');
    if (!body) return;
    body.innerHTML = '<div class="st-loading">Reading the outline…</div>';
    const meta = await api('outline/meta');
    if (!meta.ok || !meta.current || !meta.current.installed) {
      body.innerHTML = '<div class="empty">No outline data is installed. '
        + '<div class="tiny muted" style="margin-top:8px">Build it with '
        + '<code>python3 tools/build_outlines.py</code>.</div></div>';
      return;
    }
    const ref = ($('#g-ref') || {}).value || '';
    const at = await this.split(ref);
    this.book = at.book || this.book || 'Gen';
    this.chapter = at.chapter || this.chapter || 1;
    await this.paint(body, meta.current);
  },

  /* Export the outline as an HTML document.
   *
   * One format, deliberately.  Word, Pages, LibreOffice and PowerPoint all
   * open HTML, so a single honest file is the export to all of them -- a
   * proprietary writer per application would be four writers to keep correct
   * and would carry no more of the outline than the HTML does.  The file is
   * downloaded, not displayed, so opening it does not navigate the app away. */
  async exportDoc() {
    const book = this.book, chapter = this.chapter;
    const ref = chapter ? this.name(book) + ' ' + chapter : this.name(book);
    const r = await api('export/outline', { ref });
    if (!r.ok) { toast(r.error || 'No outline for that.', 'warn'); return; }
    const blob = new Blob([r.html || ''], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = r.filename || 'outline.html';
    document.body.appendChild(a);
    a.click();
    a.remove();
    /* Revoked on the next turn, not immediately: Safari has been known to
     * abort a download whose object URL is gone the instant click() returns. */
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast(r.note || 'Outline downloaded.');
  },

  /* Which book and chapter the reference box names.
   *
   * Splitting it here would mean a second, worse copy of the reference parser
   * -- one that would not know that "Jn" is John, or that "1 Jn" is not
   * "1 John".  So the server is asked: it already has the canon, and the
   * chapter guide already accepts the same string. */
  async split(ref) {
    if (!ref) return {};
    const g = await api('guides/chapter', { ref });
    if (!g.ok) return {};
    const m = String(g.ref || '').match(/^(.+?)\s+(\d+)/);
    return m ? { book: m[1], chapter: parseInt(m[2], 10) } : {};
  },

  /* The full book name, from the server, which has the canon.

     Guessing it here meant a heading reading "GEN 1" -- the OSIS abbreviation
     upper-cased by the table of chapter links -- because `S.tax` carries types,
     subjects and languages, and has no book names in it at all.
   */
  name(book) {
    return this.serverName || book;
  },

  async paint(body, meta) {
    const r = await api('outline/chapter', { book: this.book, chapter: this.chapter });
    if (!r.ok) {
      body.innerHTML = '<div class="warn">' + esc(r.error) + '</div>';
      return;
    }
    let h = '<div class="ol-src"><b>' + esc(r.title) + '</b> — '
      + esc(r.attribution) + '<br>' + esc(r.note || '') + '</div>';
    this.serverName = r.book_name || this.book;
    const name = this.name(this.book);
    h += '<div class="dash-h">' + esc(name) + ' ' + this.chapter + '</div>';
    if (!r.sections.length) {
      h += '<div class="empty">' + esc(r.note_outline
        || 'This commentary gives no outline for this chapter.') + '</div>';
    } else {
      h += '<div class="ol-tree">';
      r.sections.forEach(s => {
        const sub = (s.verses || []).slice(0, 6);
        h += '<div class="ol-sec">'
          + (s.ref ? '<span class="ref" data-verses="' + esc(sub.join('|'))
              + '">' + esc(s.ref) + '</span>' : '<span class="ref"></span>')
          + '<span class="t">' + esc(s.title) + '</span>'
          + '<span class="go">open</span></div>';
        h += s.verses && s.verses.length
          ? '<div class="ol-sub">' + s.verses.map(v =>
              '<span class="ref" data-open="' + esc(v) + '">' + esc(v)
              + '</span>').join(' · ') + '</div>'
          : '';
      });
      h += '</div>';
    }
    /* The whole Bible, so a chapter can be reached without typing it. */
    const bo = await api('outline/book', { book: this.book });
    if (bo.ok && bo.index) {
      h += '<div class="dash-h" style="margin-top:18px">Every chapter of '
        + esc(name) + '</div><div class="ol-tree">'
        + bo.index.map(c => '<div class="ol-ch' + (c.chapter === this.chapter
            ? ' on' : '') + '" data-ch="' + c.chapter + '">'
          + 'Chapter ' + c.chapter + '<span class="n">' + c.points + '</span>'
          + '</div>').join('') + '</div>';
    }
    body.innerHTML = h;
  },

  /* ------------------------------------------------ Eusebian canon tables
   *
   * The ten tables Eusebius drew, laid out as the tables: canon by canon, row
   * by row, four Gospel columns.  The shape is the point -- a reader asking
   * "what do the others have at this place" needs to see the blank cell, and a
   * list of verses cannot show it.
   *
   * It opens on the health report rather than a table, because the module
   * Crosswire ships under this name is not the canon table and the reader needs
   * to know that before they spend five minutes reading one empty column.
   */
  async eusebian(body) {
    const want = ($('#g-eusec').value || '').trim();
    const canonSel = $('#g-eus');
    const canon = canonSel ? canonSel.value : '';
    const [health, r] = await Promise.all([
      api('eusebian/health'),
      want
        ? api('eusebian/lookup', { n: want })
        : api('eusebian/harmony', { canon, limit: 300 }),
    ]);
    if (!health.available) {
      body.innerHTML = '<div class="dash-card"><div class="dash-h">'
        + 'Not installed</div><p class="muted">'
        + health.notes.map(esc).join('</p><p class="muted">') + '</p></div>';
      return;
    }
    let h = '<div class="dash-card"><div class="dash-h">'
      + 'Eusebian canon tables</div>';
    if (!health.usable) {
      h += '<div class="eu-warn">'
        + health.notes.map(esc).join('</p><p>') + '</div>';
    }
    h += '<div class="tiny muted">'
      + health.sections.toLocaleString() + ' numbered sections · '
      + health.complete_pct + '% of the sections usually counted'
      + (health.shared_sections
        ? ' · ' + health.shared_sections + ' numbers shared between Gospels'
        : ' · no number is shared between Gospels')
      + '</div>';
    if (health.books) {
      h += '<table class="kv eu-books"><tr><th>Gospel</th><th>Sections here'
        + '</th><th>Usually</th><th>Missing</th></tr>'
        + health.books.map(b => '<tr><td>' + esc(b.name) + '</td><td>'
          + b.have + '</td><td>' + b.expected + '</td><td>'
          + (b.missing || '—') + '</td></tr>').join('')
        + '</table>';
    }
    if (health.malformed_count) {
      h += '<details class="eu-details"><summary class="tiny">'
        + health.malformed_count + ' entries with an impossible number</summary>'
        + health.malformed.map(x => '<div class="tiny muted">'
          + esc(x.verse) + ' = ' + esc(String(x.value)) + ' — '
          + esc(x.why) + '</div>').join('') + '</details>';
    }
    if (health.duplicate_modules && Object.keys(health.duplicate_modules).length) {
      h += '<p class="tiny muted">Identical duplicate modules installed: '
        + Object.keys(health.duplicate_modules).map(esc).join(', ')
        + '. One is read; removing the others changes nothing.</p>';
    }
    h += '</div>';

    if (want) {
      if (!r.ok) {
        body.innerHTML = h + '<div class="dash-card"><p class="muted">'
          + esc(r.error) + '</p></div>';
        return;
      }
      h += '<div class="dash-card"><div class="dash-h">' + esc(r.notation)
        + ' — ' + esc(r.canon.en) + '</div>';
      if (r.columns.filter((c) => c.present).length < 2) {
        h += '<p class="muted">Only one Gospel has this number, so there is '
          + 'nothing here to compare it with. See the note above.</p>';
      }
      h += '<table class="eu-grid"><tr>'
        + r.columns.map(c => '<th>' + esc(c.name) + '</th>').join('')
        + '</tr><tr>'
        + r.columns.map(c => '<td' + (c.present ? '' : ' class="eu-blank"')
          + '>' + (c.present
            ? '<div>' + esc(c.first) + ' – ' + esc(c.last) + '</div>'
              + '<div class="tiny muted">' + c.count + ' verses</div>'
              + '<div class="eu-verses">' + c.verses.map(v =>
                '<a href="#" data-openref="' + esc(v) + '">' + esc(v)
                + '</a>').join('') + '</div>'
            : '<span class="muted">—</span>')
          + '</td>').join('')
        + '</tr></table></div>';
      body.innerHTML = h;
      return;
    }

    if (!r.ok) { body.innerHTML = h + '<p class="muted">'
      + esc(r.error) + '</p>'; return; }
    const pick = ['<div class="eu-canonpick">'
      + '<span class="tiny muted">Table</span>']
      .concat(r.canon_list.map(c =>
        '<button class="btn eu-canonbtn' + (String(c.n) === String(canon)
          ? ' primary' : '') + '" data-eu="'
          + c.n + '" title="' + esc(c.en) + '">' + esc(c.roman) + '</button>'))
      .concat(['</div>']).join('');
    h += pick;
    (r.canons || []).forEach((c) => {
      if (!c.rows.length) {
        h += '<div class="dash-card eu-empty"><div class="dash-h">Canon '
          + esc(c.roman) + ' — ' + esc(c.en) + '</div>'
          + '<p class="muted">No sections for this table are in the installed '
          + 'module. The table is described above; the data for it is not '
          + 'here.</p></div>';
        return;
      }
      h += '<div class="dash-card"><div class="dash-h">Canon '
        + esc(c.roman) + ' — ' + esc(c.en) + ' <span class="tiny muted">('
        + c.rows.length + ' rows)</span></div>'
        + '<table class="eu-grid"><tr>'
        + ['Matt', 'Mark', 'Luke', 'John'].map(b => '<th>' + esc(b)
          + '</th>').join('')
        + '</tr>'
        + c.rows.map(row => '<tr class="eu-row">'
          + '<td class="eu-num"><a href="#" data-eusec="'
            + esc(row.notation) + '" title="Look up '
            + esc(row.notation) + '">' + esc(row.section) + '</a></td>'
          + row.cells.map(cell => '<td' + (cell.verses.length
            ? '' : ' class="eu-blank"') + '>'
            + (cell.verses.length
              ? '<a href="#" data-openref="' + esc(cell.verses[0])
                + '">' + esc(cell.verses[0]) + '</a>'
                + (cell.verses.length > 1
                  ? '<span class="tiny muted"> +' + (cell.verses.length - 1)
                    + '</span>' : '')
              : '<span class="muted">—</span>')
            + '</td>').join('')
          + '</tr>').join('')
        + '</table></div>';
    });
    body.innerHTML = h;
    const tabs = $('#g-eus');
    if (tabs) {
      tabs.innerHTML = '<option value="">All ten</option>'
        + r.canon_list.map(c => '<option value="' + c.n + '"'
          + (String(c.n) === String(canon) ? ' selected' : '') + '>'
          + esc(c.roman) + ' — ' + esc(c.en) + '</option>').join('');
      tabs.style.display = '';
      tabs.onchange = () => Guides.load();
    }
  },


  wire(body) {
    $$('.ol-ch', body).forEach(x => {
      x.onclick = async () => {
        this.chapter = parseInt(x.dataset.ch, 10);
        const refBox = $('#g-ref');
        if (refBox) refBox.value = this.book + ' ' + this.chapter;
        await this.paint(body, (await api('outline/meta')).current);
      };
    });
    $$('[data-open]', body).forEach(x => {
      x.onclick = () => this.openInBible(x.dataset.open);
    });
    $$('[data-verses]', body).forEach(x => {
      x.onclick = () => {
        const first = (x.dataset.verses || '').split('|')[0];
        if (first) this.openInBible(first);
      };
    });
  },

  openInBible(ref) {
    closeModal();
    App.show('workspace');
    const m = S.modules.find(x => x.is_bible && x.reader === 'verse');
    if (!m) { toast('No Bible is installed.', 'warn'); return; }
    Workspace.openModule(m.id, { ref, span: 'verse' });
  },
};

/* ====================================================== sentence diagram ===
   A verse laid out by clause, by part of speech, and by what each word hangs
   off.

   Three sources, and the panel names the one that answered, because they are
   not equally exact:

   * a tagged original-language module -- the morphology is in the database, so
     the tags are the module's own;
   * an English Bible with the parser installed -- a dependency parse, so the
     clauses are the subtrees of real verbs and each word says what it is
     attached to;
   * an English Bible without it -- clause structure from punctuation and a
     conjunction list, no parts of speech, and the panel says so instead of
     inventing them.

   It used to be only the first and third.  "This is not a parser" was true and
   is no longer, and leaving it would have understated what the diagram now
   knows.                                                      */