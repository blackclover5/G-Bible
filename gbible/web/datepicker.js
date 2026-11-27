/* ============================================================== Date picker
 *
 * One calendar for every place the reader has to choose a date.  It never
 * writes data itself: it emits a canonical YYYY-MM-DD string to onPick, so
 * each caller keeps its own storage format and the backend needs no changes.
 *
 * The day grid reuses the .pcal-* styles already used by the devotional
 * pane's date picker.  Month and year can both be changed directly, which the
 * old in-pane grid could not do.
 */
const DatePicker = {
  _open: null,

  _pad(n) { return String(n).padStart(2, '0'); },
  _iso(d) {
    return d.getFullYear() + '-' + this._pad(d.getMonth() + 1) + '-' + this._pad(d.getDate());
  },
  _parse(s) {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(s || '').trim());
    if (!m) return null;
    const y = +m[1], mo = +m[2], d = +m[3];
    if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    const dt = new Date(y, mo - 1, d);
    return (dt.getFullYear() === y && dt.getMonth() === mo - 1 && dt.getDate() === d)
      ? dt : null;
  },

  close() {
    if (!this._open) return;
    const o = this._open;
    this._open = null;
    if (o.outside) document.removeEventListener('pointerdown', o.outside, true);
    if (o.key) document.removeEventListener('keydown', o.key, true);
    if (o.pop && o.pop.parentNode) o.pop.parentNode.removeChild(o.pop);
    if (o.anchor && o.anchor.setAttribute) o.anchor.setAttribute('aria-expanded', 'false');
  },

  open(opts) {
    this.close();
    const anchor = opts.anchor || null;
    const today = new Date();
    const chosen = this._parse(opts.value);
    const value = chosen ? this._iso(chosen) : '';
    let view = chosen
      ? new Date(chosen.getFullYear(), chosen.getMonth(), 1)
      : new Date(today.getFullYear(), today.getMonth(), 1);

    const pop = document.createElement('div');
    pop.className = 'ref-picker-popover dp-popover';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', opts.label || 'Choose a date');
    pop.innerHTML = '<div class="ref-picker-col">'
      + '<div class="cal-head">'
      + '<button type="button" class="btn tiny" data-dp="prev" title="Previous month">‹</button>'
      + '<span class="dp-controls">'
      + '<select class="dp-month" aria-label="Month"></select>'
      + '<select class="dp-year" aria-label="Year"></select>'
      + '</span>'
      + '<button type="button" class="btn tiny" data-dp="next" title="Next month">›</button>'
      + '</div>'
      + '<div class="pcal-grid dp-grid"></div>'
      + '<div class="dp-foot">'
      + '<button type="button" class="btn tiny" data-dp="today">Today</button>'
      + (opts.allowClear === false ? '' :
          '<button type="button" class="btn tiny" data-dp="clear">Clear</button>')
      + '<button type="button" class="btn tiny" data-dp="close">Close</button>'
      + '</div></div>';
    document.body.appendChild(pop);

    const months = ['January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'];
    const monthSel = pop.querySelector('.dp-month');
    const yearSel = pop.querySelector('.dp-year');
    const years = new Set();
    for (let y = today.getFullYear() - 30; y <= today.getFullYear() + 30; y++) years.add(y);
    if (chosen) years.add(chosen.getFullYear());
    [...years].sort((a, b) => a - b).forEach(y => {
      const o = document.createElement('option');
      o.value = String(y); o.textContent = String(y);
      yearSel.appendChild(o);
    });

    const pick = (d) => {
      const iso = this._iso(d);
      this.close();
      if (typeof opts.onPick === 'function') opts.onPick(iso);
    };
    const render = () => {
      monthSel.value = String(view.getMonth());
      yearSel.value = String(view.getFullYear());
      const grid = pop.querySelector('.dp-grid');
      grid.innerHTML = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
        .map(x => '<div class="pcal-dow">' + x + '</div>').join('');
      const first = new Date(view.getFullYear(), view.getMonth(), 1).getDay();
      const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
      for (let i = 0; i < first; i++) grid.appendChild(document.createElement('span')).className = 'pcal-blank';
      for (let d = 1; d <= days; d++) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'pcal-day';
        b.textContent = String(d);
        if (value === this._iso(new Date(view.getFullYear(), view.getMonth(), d)))
          b.classList.add('current');
        if (this._iso(today) === this._iso(new Date(view.getFullYear(), view.getMonth(), d)))
          b.classList.add('today');
        b.onclick = () => pick(new Date(view.getFullYear(), view.getMonth(), d));
        grid.appendChild(b);
      }
    };
    months.forEach((name, i) => {
      const o = document.createElement('option');
      o.value = String(i); o.textContent = name;
      monthSel.appendChild(o);
    });

    monthSel.onchange = () => {
      view = new Date(view.getFullYear(), Number(monthSel.value), 1);
      render();
    };
    yearSel.onchange = () => {
      view = new Date(Number(yearSel.value), view.getMonth(), 1);
      render();
    };
    pop.querySelector('[data-dp="prev"]').onclick = () => {
      view = new Date(view.getFullYear(), view.getMonth() - 1, 1); render();
    };
    pop.querySelector('[data-dp="next"]').onclick = () => {
      view = new Date(view.getFullYear(), view.getMonth() + 1, 1); render();
    };
    pop.querySelector('[data-dp="today"]').onclick = () => pick(new Date());
    pop.querySelector('[data-dp="close"]').onclick = () => this.close();
    const clearBtn = pop.querySelector('[data-dp="clear"]');
    if (clearBtn) clearBtn.onclick = () => {
      this.close();
      if (typeof opts.onPick === 'function') opts.onPick('');
    };

    const o = { pop, anchor };
    this._open = o;
    render();
    // Position after render so the size is known.
    const r = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    let left = r ? r.left : Math.max(8, (window.innerWidth - w) / 2);
    let top = r ? r.bottom + 6 : Math.max(8, (window.innerHeight - h) / 2);
    if (left + w > window.innerWidth - 8) left = Math.max(8, window.innerWidth - w - 8);
    if (top + h > window.innerHeight - 8) top = Math.max(8, (r ? r.top - h - 6 : 8));
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
    if (anchor && anchor.setAttribute) anchor.setAttribute('aria-expanded', 'true');

    o.outside = (ev) => { if (!pop.contains(ev.target) && ev.target !== anchor) this.close(); };
    document.addEventListener('pointerdown', o.outside, true);
    o.key = (ev) => { if (ev.key === 'Escape') { ev.stopPropagation(); this.close(); } };
    document.addEventListener('keydown', o.key, true);
    const firstBtn = pop.querySelector('.pcal-day.current') || pop.querySelector('[data-dp="today"]');
    if (firstBtn) firstBtn.focus();
    return pop;
  },

  /* Turn an input into a date field.  The input's value stays the canonical
   * YYYY-MM-DD string, so every existing reader of that value still works. */
  attach(input, opts) {
    if (!input || input._dpAttached) return;
    input._dpAttached = true;
    if (input.tagName === 'INPUT') {
      input.type = 'text';
      input.readOnly = true;
      if (!input.placeholder) input.placeholder = 'YYYY-MM-DD';
    }
    input.setAttribute('aria-haspopup', 'dialog');
    input.setAttribute('aria-expanded', 'false');
    const open = () => DatePicker.open(Object.assign({}, opts, {
      anchor: input, value: input.value,
      onPick: (iso) => {
        input.value = iso;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        if (opts && typeof opts.onPick === 'function') opts.onPick(iso);
      },
    }));
    input.onclick = open;
  },
};
