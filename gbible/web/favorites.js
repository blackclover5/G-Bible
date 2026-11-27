/* ========================================================== Favorites */
/* The unified favorites panel: one place for every module you starred.
   Open in the workspace or unfavorite in place. Anything else that stars a
   module (the Library's star, the store, sync) writes to the same flag. */
const Favorites = {
  async load() {
    if (!this._wired) {
      this._wired = true;
      $('#fv-q').addEventListener('input',
        (typeof debounce === 'function') ? debounce(() => this.load(), 150) : () => this.load());
      $('#fv-clear').onclick = async () => {
        const mods = (S.modules || []).filter(m => m.favorite);
        if (!mods.length) { toast('There is nothing to unfavorite.', 'warn'); return; }
        if (!confirm('Unfavorite all ' + mods.length + ' modules?')) return;
        const rs = await Promise.all(mods.map(m =>
          api('favorites', { action: 'set', id: m.id, value: '0' })));
        if (rs.some(r => !r || r.ok === false)) {
          toast('Some modules could not be unfavorited.', 'err');
        } else {
          mods.forEach(m => { m.favorite = false; });
          toast('Cleared favorites.', 'ok');
        }
        this.load();
        if (Library && Library.paint) Library.paint();
      };
    }
    const host = $('#fv-list');
    const count = $('#fv-count');
    if (!host) return;
    host.innerHTML = '<div class="st-loading">Loading…</div>';
    const q = (($('#fv-q') || {}).value || '').trim().toLowerCase();
    const r = await api('favorites');
    if (r && r.ok !== false) {
      const ids = new Set((r.favorites || []).map(f => f.id || f.module_id || f));
      (S.modules || []).forEach(m => { m.favorite = ids.has(m.id); });
    }
    const mods = (S.modules || []).filter(m => m.favorite);
    const rows = q
      ? mods.filter(m => (m.name + ' ' + (m.description || '') + ' ' + (m.author || ''))
          .toLowerCase().includes(q))
      : mods;
    count.textContent = rows.length + ' favorite' + (rows.length === 1 ? '' : 's');
    if (!rows.length) {
      host.innerHTML = '<div class="empty">'
        + (mods.length ? 'No matches.' : 'Nothing starred yet — click the ☆ on any module in your Library.')
        + '</div>';
      return;
    }
    const groups = {};
    rows.forEach(m => {
      const g = m.type_label || m.type || 'Other';
      (groups[g] = groups[g] || []).push(m);
    });
    host.innerHTML = '';
    Object.keys(groups).sort().forEach(g => {
      host.appendChild(el('h3', '', esc(g)));
      groups[g].sort((a, b) => (a.name || '').localeCompare(b.name || ''))
        .forEach(m => {
          const n = el('div', 'item');
          const b = el('div', ''); b.style.flex = '1'; b.style.minWidth = '0';
          b.appendChild(el('div', 't', esc(m.name)));
          b.appendChild(el('div', 'm',
            (m.lang_name ? '<span>' + esc(m.lang_name) + '</span> ' : '')
            + (m.license ? '<span class="chip ' + liccls(m.license) + '">' + esc(m.license) + '</span>' : '')
            + (m.format ? '<span>' + esc(m.format) + '</span>' : '')));
          n.appendChild(b);
          const a = el('div', 'actions');
          const star = el('button', 'btn star on', '★');
          star.title = 'Remove from favourites';
          star.onclick = async (e) => {
            e.stopPropagation();
            const r = await api('favorites', { action: 'set', id: m.id, value: '0' });
            if (r.ok) {
              m.favorite = false;
              toast('Removed from favourites.', 'ok');
              Favorites.load();
              if (Library && Library.paint) Library.paint();
            } else toast('Could not update favourites.', 'err');
          };
          a.appendChild(star);
          const open = el('button', 'btn primary', 'Open');
          open.onclick = () => { Workspace.openModule(m.id); App.show('workspace'); };
          a.appendChild(open);
          n.appendChild(a);
          host.appendChild(n);
        });
    });
  },
};
