const Appearance = {
  KEY: 'gbible:appearance',
  defaults() {
    return {
      theme: 'dark',
      bodyFont: 'sans',
      bodySize: 15,
      bodyColor: '#e6e8f0',
      headingFont: 'sans',
      headerSize: 18,
      headerColor: '#ffd166',
    };
  },
  load() {
    try {
      const raw = localStorage.getItem(this.KEY);
      if (raw) return Object.assign(this.defaults(), JSON.parse(raw));
    } catch (e) {}
    return this.defaults();
  },
  apply(opts) {
    const o = Object.assign(this.defaults(), opts || {});
    document.documentElement.setAttribute('data-theme', o.theme || 'dark');
    try { localStorage.setItem(this.KEY, JSON.stringify(o)); } catch (e) {}
    return o;
  },
  init() {
    const o = this.load();
    document.documentElement.setAttribute('data-theme', o.theme || 'dark');
    const root = document.documentElement;
    root.style.setProperty('--body-size', (o.bodySize || 15) + 'px');
    root.style.setProperty('--heading-size', (o.headerSize || 18) + 'px');
    root.style.setProperty('--fg', o.bodyColor || '#e6e8f0');
    root.style.setProperty('--accent-2', o.headerColor || '#ffd166');
    root.style.setProperty('--body-font', this.family(o.bodyFont));
    root.style.setProperty('--heading-font', this.family(o.headingFont));
  },
  family(name) {
    if (name === 'serif') return 'Georgia, "Times New Roman", serif';
    if (name === 'mono') return 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace';
    return 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
  },
  async show() {
    const current = this.load();
    const themeOpts = [
      ['dark', 'Dark'],
      ['light', 'Light'],
      ['sepia', 'Sepia'],
      ['contrast', 'High contrast']
    ];
    const fontOpts = [
      ['sans', 'System / sans serif'],
      ['serif', 'Serif'],
      ['mono', 'Monospace']
    ];

    /* The color inputs track the chosen theme's default look.  This keeps a
     * user from accidentally saving dark-mode body text into a light theme. */
    const themeColors = {
      dark: { bodyColor: '#e6e8f0', headerColor: '#ffd166' },
      light: { bodyColor: '#212837', headerColor: '#9a6700' },
      sepia: { bodyColor: '#4a3e30', headerColor: '#7c5200' },
      contrast: { bodyColor: '#ffffff', headerColor: '#ffd400' },
    };
    modal('Appearance',
      '<div class="st-body" style="margin-bottom:6px">Simple costuming for reading. Leave these alone unless you prefer something else.</div>'
      + '<label class="st-lbl">Theme</label><select id="app-theme">' + themeOpts.map(o => '<option value="'+o[0]+'"' + (o[0]===current.theme?' selected':'') + '>'+o[1]+'</option>').join('') + '</select>'
      + '<label class="st-lbl">Body font</label><select id="app-body-font">' + fontOpts.map(o => '<option value="'+o[0]+'"' + (o[0]===current.bodyFont?' selected':'') + '>'+o[1]+'</option>').join('') + '</select>'
      + '<label class="st-lbl">Body size</label><input id="app-body-size" type="number" min="13" max="20" step="1" value="'+(current.bodySize||15)+'">'
      + '<label class="st-lbl">Body color</label><input id="app-body-color" type="color" value="'+(current.bodyColor||'#e6e8f0')+'">'
      + '<label class="st-lbl">Header font</label><select id="app-head-font">' + fontOpts.map(o => '<option value="'+o[0]+'"' + (o[0]===current.headingFont?' selected':'') + '>'+o[1]+'</option>').join('') + '</select>'
      + '<label class="st-lbl">Header size</label><input id="app-head-size" type="number" min="14" max="26" step="1" value="'+(current.headerSize||18)+'">'
      + '<label class="st-lbl">Header color</label><input id="app-head-color" type="color" value="'+(current.headerColor||'#ffd166')+'">'
      + '<div class="tiny muted" style="margin-top:8px">These affect the page layout and panes globally.</div>',
      [{ label: 'Save', cls: 'primary', fn: () => {
        const o = {
          theme: $('#app-theme').value,
          bodyFont: $('#app-body-font').value,
          bodySize: Number($('#app-body-size').value || 15),
          bodyColor: $('#app-body-color').value,
          headingFont: $('#app-head-font').value,
          headerSize: Number($('#app-head-size').value || 18),
          headerColor: $('#app-head-color').value,
        };
        this.apply(o);
        this.init();
        closeModal();
      } },
      { label: 'Reset', cls: 'btn', fn: () => {
        localStorage.removeItem(this.KEY);
        this.init();
        closeModal();
        toast('Appearance settings reset.', 'warn');
      } },
      { label: 'Cancel', cls: 'btn', fn: () => {} }]);
    $('#app-theme').onchange = () => {
      const c = themeColors[document.querySelector('#app-theme').value];
      if (c) {
        document.querySelector('#app-body-color').value = c.bodyColor;
        document.querySelector('#app-head-color').value = c.headerColor;
      }
    };
  },
};
