/* ============================================================== Canvas
   A freeform study board: colored cards (text or verse references) on a
   pannable, zoomable plane, connected by arrows.  Boards are stored in the
   library and print as a clean page. */
const Canvas = {
  boards: [],
  board: null,
  nodes: [],
  edges: [],
  scale: 1,
  pan: { x: 0, y: 0 },
  linking: false,
  linkFrom: null,
  selected: null,

  async load() {
    const r = await api('canvas/boards');
    this.boards = r.boards || [];
    const sel = $('#cv-board');
    if (sel) sel.innerHTML = this.boards.map(b =>
      '<option value="' + esc(b.id) + '">' + esc(b.name) + '</option>').join('');
    /* Always wire the toolbar — without boards it still needs to respond to
     * + Board so the very first click works. */
    this._wire();
    if (!this.boards.length && r.default) {
      this.boards = [{ id: r.default, name: 'My Canvas', created_at: 0, updated_at: 0 }];
      this.board = r.default;
      if (sel) sel.innerHTML = '<option value="' + esc(r.default) + '">My Canvas</option>';
    }
    const target = (!this.board || !this.boards.find(b => b.id === this.board))
      ? (r.default || (this.boards[0] && this.boards[0].id))
      : this.board;
    if (!target) { toast('Could not create a board.', 'err'); return; }
    await this.open(target);
  },

  _wire() {
    if (this._wired) return;
    this._wired = true;
    $('#cv-board').onchange = (e) => this.open(e.target.value);
    $('#cv-newboard').onclick = async () => {
      const name = prompt('Board name:', 'New study');
      if (!name) return;
      const r = await post('canvas/board', { action: 'create', name });
      if (r.ok) this.load();
    };
    $('#cv-renameboard').onclick = async () => {
      if (!this.board) return;
      const b = this.boards.find(x => x.id === this.board);
      const name = prompt('Rename board:', b ? b.name : 'Board');
      if (!name) return;
      await post('canvas/board', { action: 'rename', board: this.board, name });
      this.load();
    };
    $('#cv-delboard').onclick = async () => {
      if (!this.board || !confirm('Delete this board and its cards?')) return;
      await post('canvas/board', { action: 'remove', board: this.board });
      this.board = null;
      this.load();
    };
    $('#cv-addtext').onclick = () => this.addNode('text');
    $('#cv-addverse').onclick = () => {
      const ref = prompt('Passage reference (e.g. John 3:16):', '');
      if (!ref) return;
      this.addNode('verse', ref);
    };
    $('#cv-color').onclick = () => {
      if (!this.selected) { toast('Select a card first.', 'warn'); return; }
      const colors = ['yellow', 'blue', 'green', 'pink', 'purple'];
      const cur = this.selected.color || 'yellow';
      this.selected.color = colors[(colors.indexOf(cur) + 1) % colors.length];
      this.render(); this.save();
    };
    $('#cv-link').onclick = () => {
      this.linking = !this.linking;
      $('#cv-link').classList.toggle('on', this.linking);
      $('#cv-link').setAttribute('aria-pressed', this.linking ? 'true' : 'false');
      toast(this.linking ? 'Click a card to connect from…' : 'Link mode off.', 'ok');
      this.linkFrom = null;
    };
    $('#cv-delcard').onclick = () => {
      if (!this.selected) { toast('Select a card first.', 'warn'); return; }
      this.nodes = this.nodes.filter(n => n !== this.selected);
      this.edges = this.edges.filter(e => e.from !== this.selected.id && e.to !== this.selected.id);
      this.selected = null;
      this.render(); this.save();
    };
    $('#cv-print').onclick = () => {
      const host = $('#cv-plane');
      if (!host) return;
      Print.printNode(host, { moduleName: 'Canvas',
        section: (this.boards.find(b => b.id === this.board) || {}).name || 'Canvas' });
    };
    this._wireStage();
  },

  _wireStage() {
    const stage = $('#cv-stage');
    if (!stage || stage._cvWired) return;
    stage._cvWired = true;
    let panning = false, panOrigin = null, panStart = null;
    stage.addEventListener('pointerdown', (e) => {
      const onNode = e.target.closest('.cv-node');
      if (onNode) return;               /* node drag handled by node */
      if (this.linking) return;
      panning = true; panOrigin = { x: e.clientX, y: e.clientY };
      panStart = { ...this.pan };
      stage.setPointerCapture(e.pointerId);
      stage.classList.add('panning');
    });
    stage.addEventListener('pointermove', (e) => {
      if (!panning) return;
      this.pan.x = panStart.x + (e.clientX - panOrigin.x);
      this.pan.y = panStart.y + (e.clientY - panOrigin.y);
      this._transform();
    });
    stage.addEventListener('pointerup', (e) => {
      panning = false; stage.classList.remove('panning');
    });
    stage.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && Math.abs(e.deltaY) < 80) return;
      e.preventDefault();
      const dir = e.deltaY > 0 ? -1 : 1;
      const next = Math.min(1.6, Math.max(0.5, this.scale + dir * 0.12));
      this.scale = next;
      this._transform();
    }, { passive: false });
  },

  _transform() {
    const plane = $('#cv-plane');
    if (!plane) return;
    plane.style.transform = 'translate(' + this.pan.x + 'px,' + this.pan.y + 'px) scale(' + this.scale + ')';
  },

  async open(boardId) {
    this.board = boardId;
    const r = await post('canvas/board', { board: boardId });
    if (!r.ok) { toast('Could not load board.', 'err'); return; }
    this.nodes = (r.nodes || []).map(n => ({
      id: n.id, kind: n.kind, x: n.x, y: n.y, w: n.w, h: n.h,
      text: n.text || '', ref: n.ref || '', color: n.color || 'yellow' }));
    this.edges = (r.edges || []).map(e => ({ from: e.from_id, to: e.to_id }));
    this.selected = null;
    this.linkFrom = null;
    this._wire();
    const sel = $('#cv-board'); if (sel) sel.value = boardId;
    this.render();
  },

  addNode(kind, ref) {
    const id = 'n' + Math.random().toString(36).slice(2, 9);
    const stage = $('#cv-stage').getBoundingClientRect();
    const cx = (stage.width / 2 - this.pan.x) / this.scale;
    const cy = (stage.height / 2 - this.pan.y) / this.scale;
    this.nodes.push({
      id, kind: kind || 'text',
      x: Math.round(cx + Math.random() * 60 - 30),
      y: Math.round(cy + Math.random() * 60 - 30),
      w: 210, h: 90,
      text: '', ref: ref || '', color: 'yellow',
    });
    this.render(); this.save();
  },

  async save() {
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(async () => {
      this._saveTimer = null;
      const body = {
        action: 'save', board: this.board,
        nodes: this.nodes.map(n => ({ id: n.id, kind: n.kind, x: n.x, y: n.y,
          w: n.w, h: n.h, text: n.text, ref: n.ref, color: n.color })),
        edges: this.edges.map(e => ({ from: e.from, to: e.to })),
      };
      await post('canvas/save', body);
    }, 700);
  },

  render() {
    const nodesHost = $('#cv-nodes');
    const svg = $('#cv-edges');
    if (!nodesHost || !svg) return;
    nodesHost.innerHTML = '';
    svg.innerHTML = '';
    /* Cards */
    this.nodes.forEach(n => {
      const div = document.createElement('div');
      div.className = 'cv-node cv-' + (n.color || 'yellow')
        + (this.selected === n ? ' selected' : '')
        + (this.linkFrom === n ? ' linking' : '');
      div.style.left = n.x + 'px';
      div.style.top = n.y + 'px';
      div.style.width = n.w + 'px';
      div.style.minHeight = n.h + 'px';
      div.dataset.id = n.id;
      let html = '<div class="cv-head">'
        + (n.kind === 'verse' ? '<span class="cv-ref">' + esc(n.ref || 'verse') + '</span>' : '')
        + '<span class="spacer"></span>'
        + '<button class="cv-x" title="Delete card">×</button></div>'
        + '<textarea class="cv-text" spellcheck="false" placeholder="type…">' + esc(n.text) + '</textarea>'
        + (n.kind === 'verse'
          ? '<button class="cv-open">Open ' + esc(n.ref || 'passage') + '</button>' : '');
      div.innerHTML = html;
      const ta = div.querySelector('.cv-text');
      ta.addEventListener('input', () => { n.text = ta.value; this.save(); this.drawEdges(); });
      ta.addEventListener('pointerdown', (e) => e.stopPropagation());
      div.querySelector('.cv-x').onclick = (e) => {
        e.stopPropagation();
        this.nodes = this.nodes.filter(x => x !== n);
        this.edges = this.edges.filter(x => x.from !== n.id && x.to !== n.id);
        this.selected = null;
        this.render(); this.save();
      };
      const openBtn = div.querySelector('.cv-open');
      if (openBtn) openBtn.onclick = () => {
        const ref = n.ref; if (!ref) return;
        App.show('workspace');
        const pane = (S.layout && S.layout.panes && S.layout.panes[0]);
        if (pane) Reader.go(pane, ref);
      };
      this._drag(div, n);
      nodesHost.appendChild(div);
    });
    this.drawEdges();
    this._transform();
  },

  drawEdges() {
    const svg = $('#cv-edges');
    if (!svg) return;
    svg.innerHTML = '';
    const byId = Object.fromEntries(this.nodes.map(n => [n.id, n]));
    this.edges.forEach(e => {
      const a = byId[e.from], b = byId[e.to];
      if (!a || !b) return;
      const x1 = a.x + a.w, y1 = a.y + a.h / 2;
      const x2 = b.x, y2 = b.y + b.h / 2;
      const mx = (x1 + x2) / 2;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M ' + x1 + ' ' + y1 + ' C ' + mx + ' ' + y1 + ', ' + mx + ' ' + y2 + ', ' + x2 + ' ' + y2);
      path.setAttribute('class', 'cv-edge');
      path.setAttribute('marker-end', 'url(#cv-arrow)');
      svg.appendChild(path);
    });
    /* arrowhead marker */
    if (this.edges.length) {
      const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      defs.innerHTML = '<marker id="cv-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--accent-2)"/></marker>';
      svg.appendChild(defs);
    }
  },

  _drag(el, node) {
    el.addEventListener('pointerdown', (e) => {
      if (e.target.closest('textarea,button')) return;
      e.preventDefault();
      this.selected = node;
      if (this.linking) {
        if (!this.linkFrom) {
          this.linkFrom = node;
          this.render();
          toast('Now click the card to connect to.', 'ok');
        } else if (this.linkFrom !== node) {
          this.edges.push({ from: this.linkFrom.id, to: node.id });
          this.linkFrom = null;
          this.linking = false;
          $('#cv-link').classList.remove('on');
          $('#cv-link').setAttribute('aria-pressed', 'false');
          this.render(); this.save();
        }
        return;
      }
      const startX = e.clientX - node.x * this.scale - this.pan.x;
      const startY = e.clientY - node.y * this.scale - this.pan.y;
      el.setPointerCapture(e.pointerId);
      el.classList.add('dragging');
      const move = (ev) => {
        node.x = Math.round((ev.clientX - startX - this.pan.x) / this.scale);
        node.y = Math.round((ev.clientY - startY - this.pan.y) / this.scale);
        el.style.left = node.x + 'px';
        el.style.top = node.y + 'px';
        this.drawEdges();
      };
      const up = () => {
        el.classList.remove('dragging');
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        this.selected = node;
        this.render(); this.save();
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
    });
  },
};
window.Canvas = Canvas;
