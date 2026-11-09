const Study = {
  current: null,

  sec(title, body, n) {
    if (!body) return '';
    return '<div class="st-sec"><div class="st-h">' + esc(title)
      + (n != null ? ' <span class="st-n">' + n + '</span>' : '')
      + '</div><div class="st-b">' + body + '</div></div>';
  },

  refLinks(refs) {
    return (refs || []).map(r =>
      '<a href="#" data-ref="' + esc(r.osis || r.label) + '">'
      + esc(r.label) + '</a>').join(' · ');
  },

  verseHtml(b) {
    let h = '<div class="st-ref">' + esc(b.ref.label) + '</div>';
    const c = b.crossrefs || {};
    if (c.tsk_entry) {
      h += this.sec('Treasury of Scripture Knowledge',
        '<div class="st-body">' + esc(c.tsk_entry.text) + '</div>');
    }
    if ((c.outgoing || []).length) {
      h += this.sec('Cross-references from here',
        this.refLinks(c.outgoing.slice(0, 60)));
    }
    if ((c.incoming || []).length) {
      h += this.sec('Cited by', this.refLinks(c.incoming.slice(0, 60)));
    }
    h += this.sec('Commentaries', (b.commentaries || []).map(n =>
      '<div class="st-note"><div class="st-src">' + esc(n.module)
      + (n.granularity !== 'verse' ? ' <span class="chip">' + n.granularity
        + '</span>' : '') + '</div><div class="st-body">'
      + esc(n.text) + '</div></div>').join(''),
      (b.commentaries || []).length);
    h += this.sec('Topics', (b.topics || []).map(t =>
      '<div class="st-note"><div class="st-src">' + esc(t.module)
      + '</div><div class="st-t">' + esc(t.title) + '</div><div class="st-body">'
      + esc(t.text) + '</div></div>').join(''), (b.topics || []).length);
    h += this.sec('Places', (b.places || []).map(p =>
      '<div class="st-place"><b>' + esc(p.name) + '</b>'
      + (p.comment ? '<div class="st-body">' + esc(p.comment) + '</div>' : '')
      + (p.lat != null && p.lon != null
        ? ' <a href="#" data-geo="' + esc(p.lat) + ',' + esc(p.lon) + '">'
          + esc(p.lat) + ', ' + esc(p.lon) + '</a>' : '')
      + '</div>').join(''), (b.places || []).length);
    if ((b.words || []).length) {
      h += this.sec('Words', '<div class="st-words">' + b.words.map(w =>
        '<a href="#" data-word="' + esc(w.number) + '"><b>'
        + esc(w.number) + '</b> ' + esc((w.surfaces || []).join(' '))
        + ' <span class="muted">' + (w.count || 0) + '</span></a>').join('')
        + '</div>');
    }
    if ((b.morph || []).length) {
      h += this.sec('Morphology (OSHB)', '<div class="st-words">'
        + b.morph.map(m => '<a href="#" data-word="' + esc(m.number) + '">'
          + esc((m.surfaces || []).join(' ')) + ' <span class="muted">'
          + esc(m.number) + '</span></a>').join('') + '</div>');
    }
    return h;
  },

  wordHtml(b) {
    let h = '<div class="st-ref">' + esc(b.number)
      + (b.word ? ' <span class="muted">' + esc(b.word) + '</span>' : '')
      + ' <span class="chip">' + (b.total || 0) + ' occurrences</span></div>';
    h += this.sec('Lexicon entries', (b.entries || []).map(e =>
      '<div class="st-note"><div class="st-src">' + esc(e.module)
      + '</div><div class="st-body">' + esc(e.text) + '</div></div>').join(''),
      (b.entries || []).length);
    if ((b.by_book || []).length) {
      h += this.sec('By book', '<div class="st-words">' + b.by_book.map(x =>
        '<span class="chip">' + esc(x[0]) + ' ' + x[1] + '</span>').join('')
        + '</div>');
    }
    const occ = (b.occurrences || []).slice(0, 60);
    if (occ.length) {
      h += this.sec('Occurrences', occ.map(o =>
        '<div class="tiny" style="margin:2px 0">'
        + (o.ref ? '<a href="#" data-ref="' + esc(o.ref.label) + '">'
          + esc(o.ref.label) + '</a>' : esc(o.key))
        + ' — <b>' + esc((o.surface || '').trim()) + '</b></div>').join(''));
    }
    return h;
  },

  /* Turn decoded morphology features into a human-readable label, the way
   * Logos presents the grammatical form you can pick after typing a word + @.
   */
  _morphLabel(f) {
    const parts = [];
    const push = (v) => { if (v) parts.push(String(v)); };
    push(f.pos);
    push(f.gender);
    push(f.number);
    push(f.case);
    push(f.state);
    push(f.conjugation);
    push(f.tense);
    push(f.voice);
    push(f.mood);
    if (f.person) parts.push(f.person + (f.person === 'third' ? ' person' : ''));
    push(f.degree);
    push(f.participle);
    return parts.join(', ') || (f.scheme ? f.scheme + ' code' : 'code');
  },

  async openMorph(initial) {
    if (!initial) return this.openMorphBuilder();
    const mods = (S.modules || []).filter(m => m.has_morph);
    const resOpts = mods.map(m => '<option value="' + esc(m.id) + '">'
      + esc(m.name) + ' (' + esc(m.lang || '') + ')</option>').join('');
    modal('Morph search', '<div class="st-body">Search the morphology of tagged '
      + 'texts. Type a word or lemma and press <b>@</b> to pick its grammatical '
      + 'form (as in Logos), or enter a code prefix directly '
      + '(<code>HNcmsa</code>, <code>HTd/</code>, <code>V-PAI-3S</code>).</div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">'
      + '<label>Resource <select id="morph-resource"><option value="">All tagged resources</option>'
      + resOpts + '</select></label></div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0">'
      + '<label>Word / lemma <input id="morph-word" style="flex:1;background:var(--bg-3);'
      + 'border:1px solid var(--line-2);color:var(--fg);padding:6px;border-radius:6px"'
      + ' placeholder="a word, then @"></label>'
      + '<div id="morph-forms" style="display:flex;flex-direction:column;gap:4px;max-height:260px;overflow-y:auto"></div>'
      + '</div>'
      + '<div style="display:flex;gap:6px;margin:6px 0">'
      + '<input id="morph-q" style="flex:1;background:var(--bg-3);'
      + 'border:1px solid var(--line-2);color:var(--fg);padding:6px;'
      + 'border-radius:6px" placeholder="or code prefix" value="'
      + esc(initial || '') + '">'
      + '<button class="btn primary" id="morph-go">Search</button></div>'
      + '<div id="morph-out"></div>',
      [{ label: 'Close', cls: 'btn' }]);

    const resource = $('#morph-resource');
    if (mods.length && !resource.value) resource.value = mods[0].id;
    let selectedCode = '';
    const forms = $('#morph-forms');
    const wordIn = $('#morph-word');
    let timer = 0;
    const clearForms = () => { forms.innerHTML = ''; selectedCode = ''; };
    const showForms = async (raw) => {
      const w = (raw || '').replace(/@\s*$/, '').trim();
      if (!w) { clearForms(); return; }
      const mid = resource.value || '';
      if (!mid) {
        forms.innerHTML = '<div class="tiny muted">Pick a tagged resource first.</div>';
        selectedCode = '';
        return;
      }
      forms.innerHTML = '<div class="st-loading tiny">looking up forms…</div>';
      const r = await api('morph/wordforms', { module_id: mid, word: w, limit: 12 });
      forms.innerHTML = '';
      if (!r.ok || !r.forms || !r.forms.length) {
        forms.innerHTML = '<div class="tiny muted">no tagged forms found for "'
          + esc(w) + '"</div>';
        selectedCode = '';
        return;
      }
      r.forms.forEach(f => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn morph-form-chip';
        btn.title = f.code;
        btn.style.cssText = 'text-align:left;width:100%;padding:6px 8px';
        const feat = this._morphLabel(f.features);
        btn.innerHTML = '<div style="display:flex;justify-content:space-between">'
          + '<b>' + esc(w) + '</b><span class="tiny muted">' + esc(f.code)
          + ' · ' + f.count.toLocaleString() + '</span></div>'
          + '<div class="tiny muted">' + esc(feat) + '</div>';
        btn.onclick = () => { selectedCode = f.code; $('#morph-q').value = f.code; clearForms(); go(); };
        forms.appendChild(btn);
      });
    };
    wordIn.oninput = (e) => {
      clearTimeout(timer);
      if (/@\s*$/.test(e.target.value)) timer = setTimeout(() => showForms(e.target.value), 250);
      else clearForms();
    };
    resource.onchange = clearForms;
    const moduleName = (mid) => {
      const m = (S.modules || []).find(x => x.id === mid);
      return m ? m.name + (m.lang ? ' · ' + m.lang : '') : mid;
    };
    const renderColumn = (mid, hits) => {
      const rows = (hits || []).map(x => '<a href="#" data-ref="'
        + esc((x.ref && x.ref.label) || x.key) + '" title="' + esc(x.code) + '">'
        + esc((x.surface || x.code)) + '</a>').join('') || '<div class="tiny muted">none</div>';
      return '<div style="border:1px solid var(--line-2);border-radius:8px;padding:8px;min-width:210px">'
        + '<div class="dash-h" style="font-size:13px">' + esc(moduleName(mid)) + '</div>'
        + '<div class="st-words" style="margin-top:6px">' + rows + '</div></div>';
    };
    const go = async () => {
      const code = ($('#morph-q').value || '').trim() || selectedCode;
      if (!code) return;
      $('#morph-out').innerHTML = '<div class="st-loading">Searching…</div>';
      const r = await api('study/morph', { code, limit: 300 });
      if (!r.ok) { $('#morph-out').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
      let h = '<div class="tiny muted" style="margin:6px 0">' + r.total
        + ' words tagged</div>';
      (r.schemes || []).forEach(s => {
        h += '<div class="st-src">' + esc(s.scheme) + ' — ' + s.count
          + ' shown · ' + esc((s.codes || []).slice(0, 6).join(', ')) + '</div>';
      });
      h += '<div class="st-words" style="margin-top:8px">';
      (r.hits || []).forEach(x => {
        h += '<a href="#" data-ref="'
          + esc((x.ref && x.ref.label) || x.key) + '" title="' + esc(x.code) + '">'
          + esc((x.surface || x.code)) + '</a>';
      });
      h += '</div>';
      /* Add Versions -- Logos shows the same search side by side across
       * translations.  Group this search's hits by module, offer the other
       * tagged modules, and render each selection as its own column. */
      const byModule = {};
      (r.hits || []).forEach(x => { (byModule[x.module_id] = byModule[x.module_id] || []).push(x); });
      const others = mods.filter(m => !byModule[m.id]);
      if (others.length || Object.keys(byModule).length > 1) {
        h += '<div style="margin-top:10px"><div class="dash-h" style="font-size:13px;margin-bottom:4px">Add versions</div>'
          + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">'
          + others.map(m => '<label style="display:flex;align-items:center;gap:4px"><input type="checkbox" class="mv-sel" value="'
          + esc(m.id) + '"> ' + esc(m.name) + ' (' + esc(m.lang || '') + ')</label>').join('')
          + '</div><button class="btn" id="morph-compare">Compare selected versions</button>'
          + '<div id="morph-versions" style="display:flex;gap:8px;overflow-x:auto;padding:8px 0"></div></div>';
      }
      $('#morph-out').innerHTML = h;
      this.wire($('#morph-out'));
      $('#morph-out').querySelectorAll('#morph-compare').forEach(b => {
        b.onclick = async () => {
          const sel = [...$('#morph-out').querySelectorAll('.mv-sel:checked')].map(i => i.value);
          const out = $('#morph-versions');
          out.innerHTML = '<div class="st-loading">Loading versions…</div>';
          await Promise.all(sel.map(async (mid) => {
            const rr = await api('study/morph', { code, module_id: mid, limit: 60 });
            const col = document.createElement('div');
            col.innerHTML = renderColumn(mid, (rr.ok && rr.hits) ? rr.hits : []);
            out.appendChild(col);
          }));
          out.querySelector('.st-loading')?.remove();
        };
      });
    };
    $('#morph-go').onclick = go;
    $('#morph-q').onkeydown = (e) => { if (e.key === 'Enter') go(); };
    wordIn.onkeydown = (e) => { if (e.key === 'Enter') go(); };
    if (initial) go();
  },

  async openMorphBuilder() {
    const resources = (S.modules || []).filter(m => m.has_morph);
    modal('Morph search', '<div class="st-body">Build ordered word patterns from the tags available in an installed resource. Words in one pattern are searched in sequence; add an OR alternative to search another pattern. A word can also be excluded from the selected verse or chapter.</div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0"><label>Tagged resource <select id="morph-resource">' + resources.map(m => '<option value="' + esc(m.id) + '">' + esc(m.name) + '</option>').join('') + '</select></label><label>Search field <select id="morph-field"><option value="">Any field</option></select></label><label>Passage <input id="morph-ref" placeholder="e.g. John 1"></label><label>Match within <select id="morph-boundary"><option value="verse">Verse</option><option value="chapter">Chapter</option></select></label><label>Maximum words between <input id="morph-gap" type="number" min="0" max="10" value="0" style="width:64px"></label></div><div id="morph-groups"></div><datalist id="morph-lemmas"></datalist><div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0"><button class="btn" id="morph-or">Add OR alternative</button><button class="btn primary" id="morph-go">Search</button><button class="btn" id="morph-code-mode">Morph code search</button></div><div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0"><input id="morph-save-name" placeholder="Name this query"><button class="btn" id="morph-save">Save query</button><select id="morph-saved"></select><button class="btn" id="morph-load">Load</button><button class="btn" id="morph-delete">Delete saved</button><span class="tiny muted">Saved in this library</span></div><div id="morph-out"></div>', [{label:'Close',cls:'btn'}]);
    if (!resources.length) { $('#morph-groups').innerHTML='<div class="st-body">No installed modules advertise morphology tags. Install a tagged Hebrew or Greek text, then reopen Morph Search.</div>'; $('#morph-go').disabled=true; return; }
    let facets={}, groupCount=0;
    const fields=['pos','case','number','gender','tense','voice','mood','person','state','degree','conjugation','participle','pos_particle','scheme'];
    const addWord = (group) => {
      const container=group.querySelector('.morph-terms'); if(container.querySelectorAll('.morph-term').length>=6)return; const n=container.querySelectorAll('.morph-term').length+1, box=document.createElement('div'); box.className='st-note morph-term'; box.style.cssText='display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0;padding:8px';
      box.innerHTML='<b>Word '+n+'</b>'+fields.map(k=>'<label>'+k+' <select data-feature="'+k+'"><option value="">Any</option>'+((facets[k]||[]).map(x=>'<option value="'+esc(x.value)+'">'+esc(x.value)+' ('+x.n+')</option>').join(''))+'</select></label>').join('')+'<label>Form <input data-feature="form" placeholder="exact surface form"></label><label>Lemma <input data-feature="lemma" list="morph-lemmas" data-lemma placeholder="type to find a lemma"></label><label><input type="checkbox" data-exclude> Exclude if present in range</label>'+(n>1?'<button class="btn" data-remove>Remove</button>':'');
      const lemmaInput=box.querySelector('[data-lemma]'); let lemmaTimer=0; lemmaInput.oninput=()=>{clearTimeout(lemmaTimer);lemmaTimer=setTimeout(async()=>{const r=await api('morph/suggest',{module_id:$('#morph-resource').value,q:lemmaInput.value.trim()});const list=$('#morph-lemmas');list.innerHTML=(r.suggestions||[]).map(x=>'<option value="'+esc(x.lemma)+'"></option>').join('');},180);};
      const rm=box.querySelector('[data-remove]'); if(rm)rm.onclick=()=>{box.remove();[...container.querySelectorAll('.morph-term')].forEach((x,i)=>x.querySelector('b').textContent='Word '+(i+1));}; container.appendChild(box);
    };
    const addGroup = () => {
      if(groupCount>=6)return; const n=++groupCount, group=document.createElement('div'); group.className='st-note morph-group'; group.style.cssText='margin:8px 0;padding:8px'; group.innerHTML='<div style="display:flex;gap:8px;align-items:center"><b>Alternative '+n+'</b><button class="btn" data-add-word>Add word</button>'+(n>1?'<button class="btn" data-remove-group>Remove alternative</button>':'')+'</div><div class="morph-terms"></div>';
      group.querySelector('[data-add-word]').onclick=()=>addWord(group); const rm=group.querySelector('[data-remove-group]'); if(rm)rm.onclick=()=>{group.remove();groupCount--;[...document.querySelectorAll('#morph-groups .morph-group')].forEach((x,i)=>x.querySelector('b').textContent='Alternative '+(i+1));}; $('#morph-groups').appendChild(group); addWord(group); addWord(group); addWord(group);
    };
    const load=async()=>{ $('#morph-groups').innerHTML='<div class="st-loading">Loading available tags…</div>';groupCount=0;const module_id=$('#morph-resource').value,[r,fr]=await Promise.all([api('morph/facets',{module_id}),api('morph/fields',{module_id})]);facets=r.facets||{};const field=$('#morph-field');field.innerHTML='<option value="">Any field</option>'+((fr.fields||[]).map(x=>'<option value="'+esc(x.value)+'">'+esc(x.label)+' ('+x.n+')</option>').join(''));$('#morph-groups').innerHTML='';addGroup(); };
    $('#morph-resource').onchange=load; $('#morph-or').onclick=addGroup; $('#morph-code-mode').onclick=()=>this.openMorphCode(''); await load();
    let savedQueries=[];
    const refreshSaved=async()=>{const r=await api('morph/saved',{action:'list'});savedQueries=r.saved||[];const sel=$('#morph-saved');sel.innerHTML=savedQueries.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.name)+'</option>').join('');};
    const snapshot=()=>({name:$('#morph-save-name').value.trim(),module_id:$('#morph-resource').value,search_field:$('#morph-field').value,ref:$('#morph-ref').value.trim(),boundary:$('#morph-boundary').value,gap:$('#morph-gap').value,groups:[...document.querySelectorAll('#morph-groups .morph-group')].map(group=>[...group.querySelectorAll('.morph-term')].map(box=>{const f={};box.querySelectorAll('[data-feature]').forEach(x=>{if(x.value)f[x.dataset.feature]=x.value;});f.exclude=!!box.querySelector('[data-exclude]').checked;return f;}))});
    const restore=async saved=>{if(saved.module_id&&!resources.some(m=>m.id===saved.module_id)){$('#morph-out').innerHTML='<div class="st-body">That saved query uses a tagged resource that is not currently installed.</div>';return;}if(saved.module_id&&saved.module_id!==$('#morph-resource').value){$('#morph-resource').value=saved.module_id;await load();}$('#morph-field').value=saved.search_field||'';$('#morph-ref').value=saved.ref||'';$('#morph-boundary').value=saved.boundary||'verse';$('#morph-gap').value=saved.gap||'0';$('#morph-groups').innerHTML='';groupCount=0;(saved.groups||[]).slice(0,6).forEach(words=>{addGroup();const all=$$('#morph-groups .morph-group'),group=all[all.length-1],container=group.querySelector('.morph-terms');while(container.children.length>(words.length||3))container.lastElementChild.remove();while(container.children.length<(words.length||3))addWord(group);(words||[]).forEach((f,i)=>{const box=container.children[i];box.querySelectorAll('[data-feature]').forEach(x=>{x.value=f[x.dataset.feature]||'';});box.querySelector('[data-exclude]').checked=!!f.exclude;});});if(!groupCount)addGroup();};
    await refreshSaved();
    $('#morph-save').onclick=async()=>{const q=snapshot();if(!q.name){$('#morph-save-name').focus();return;}const r=await api('morph/saved',{action:'save',name:q.name,query:JSON.stringify(q)});if(!r.ok){$('#morph-out').innerHTML='<div class="st-body">'+esc(r.error||'Could not save this query.')+'</div>';return;}await refreshSaved();$('#morph-saved').value=r.saved.id;};
    $('#morph-load').onclick=async()=>{const row=savedQueries.find(x=>x.id===$('#morph-saved').value);if(row){try{await restore(JSON.parse(row.query_json));$('#morph-save-name').value=row.name;}catch(e){$('#morph-out').innerHTML='<div class="st-body">That saved query could not be read.</div>';}}};
    $('#morph-delete').onclick=async()=>{const id=$('#morph-saved').value;if(!id)return;const r=await api('morph/saved',{action:'delete',id});if(r.ok)await refreshSaved();};
    let resultRows=[], resultView='passages';
    const renderResults=()=>{
      const tabs='<div style="display:flex;gap:6px;margin:8px 0"><button class="btn '+(resultView==='passages'?'primary':'')+'" data-view="passages">Passages</button><button class="btn '+(resultView==='aligned'?'primary':'')+'" data-view="aligned">Aligned</button><button class="btn '+(resultView==='analysis'?'primary':'')+'" data-view="analysis">Analysis</button></div>';
      const markText=x=>{const text=x.text||'';const spans=(x.matched||[]).filter(w=>Number.isInteger(w.start)&&Number.isInteger(w.end)&&w.end>w.start).sort((a,b)=>a.start-b.start);let out='',at=0;spans.forEach(w=>{if(w.start<at)return;out+=esc(text.slice(at,w.start))+'<mark>'+esc(text.slice(w.start,w.end))+'</mark>';at=w.end;});return out+esc(text.slice(at));};
      let body='';
      if(resultView==='passages') body=resultRows.map(x=>'<div class="st-note" style="margin:6px 0"><a href="#" data-ref="'+esc(x.ref||x.key)+'"><b>'+esc(x.ref||x.key)+'</b></a><div class="st-body">'+markText(x)+'</div><div class="tiny muted">'+(x.matched||[]).map(w=>'#'+w.position+' '+(w.surface||'')+' · '+w.morph+(w.lemma?' · '+w.lemma:'')).map(esc).join(' &nbsp; ')+'</div></div>').join('');
      if(resultView==='aligned') { const nWords=Math.max(0,...resultRows.map(x=>(x.matched||[]).length)); body='<div style="overflow:auto"><table class="kv"><thead><tr><th>Passage</th>'+Array.from({length:nWords},(_,i)=>'<th>Word '+(i+1)+'</th>').join('')+'</tr></thead><tbody>'+resultRows.map(x=>'<tr><td><a href="#" data-ref="'+esc(x.ref||x.key)+'">'+esc(x.ref||x.key)+'</a></td>'+Array.from({length:nWords},(_,i)=>{const w=(x.matched||[])[i];return '<td>'+(w?'<b>'+esc(w.surface||'')+'</b><br><span class="tiny muted">'+esc(w.morph||'')+'</span>':'')+'</td>';}).join('')+'</tr>').join('')+'</tbody></table></div>'; }
      if(resultView==='analysis') body=resultRows.map(x=>'<div class="st-note" style="margin:6px 0"><a href="#" data-ref="'+esc(x.ref||x.key)+'"><b>'+esc(x.ref||x.key)+'</b></a>'+(x.matched||[]).map((w,i)=>{const features=Object.entries(w.features||{}).filter(([k,v])=>v!=null&&v!==''&&!['raw','scheme','stem','particles','pos_label'].includes(k)).map(([k,v])=>k+': '+(Array.isArray(v)?v.join(', '):v)).join(' · ');return '<div class="st-body"><b>Word '+(i+1)+': '+esc(w.surface||'')+'</b> · '+esc(w.ref||'')+'<br>Morphology: '+esc(w.morph||'')+(features?'<br>'+esc(features):'')+(w.strongs?'<br>Strong’s: '+esc(w.strongs):'')+'<br>Lemma: '+esc(w.lemma||'')+'</div>';}).join('')+'</div>').join('');
      $('#morph-out').innerHTML='<div class="tiny muted">'+resultRows.length+' '+($('#morph-boundary').value==='chapter'?'chapters':'verses')+' loaded</div>'+tabs+body+(groupOffsets.some(x=>x!==null)?'<button class="btn" data-more style="margin:8px 0">Load more results</button>':'');
      $('#morph-out').querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{resultView=b.dataset.view;renderResults();}); this.wire($('#morph-out'));
      const more=$('#morph-out').querySelector('[data-more]'); if(more)more.onclick=()=>fetchPage(false);
    };
    let activeTerms=[], groupOffsets=[];
    const fetchPage=async reset=>{if(reset){resultRows=[];groupOffsets=activeTerms.map(()=>0);$('#morph-out').innerHTML='<div class="st-loading">Searching…</div>';}const requests=activeTerms.map((terms,i)=>groupOffsets[i]===null?Promise.resolve(null):api('morph/pattern',{module_id:$('#morph-resource').value,terms:JSON.stringify(terms),search_field:$('#morph-field').value,ref:$('#morph-ref').value.trim(),max_gap:$('#morph-gap').value,boundary:$('#morph-boundary').value,limit:100,offset:groupOffsets[i]}));const pages=await Promise.all(requests);const bad=pages.find(r=>r&&!r.ok);if(bad){$('#morph-out').innerHTML='<div class="st-body">'+esc(bad.error)+'</div>';return;}const unique=new Map(resultRows.map(x=>[x.key,x]));pages.forEach((r,i)=>{if(!r)return;groupOffsets[i]=r.next||null;(r.results||[]).forEach(x=>{if(!unique.has(x.key))unique.set(x.key,x);});});resultRows=[...unique.values()];renderResults();};
    $('#morph-go').onclick=async()=>{activeTerms=[...document.querySelectorAll('#morph-groups .morph-group')].map(group=>[...group.querySelectorAll('.morph-term')].map(box=>{const f={};box.querySelectorAll('[data-feature]').forEach(x=>{if(x.value)f[x.dataset.feature]=x.value;});f.exclude=!!box.querySelector('[data-exclude]').checked;return f;}));resultView='passages';await fetchPage(true);};
  },

  /* Morph code mode: search the tagged texts by a raw morphology code prefix
   * (e.g. HNcms finds every common masculine singular noun, HTd/ every article).
   * The builder's pattern mode builds word-by-word feature sequences; code mode
   * is the direct prefix search that powers the Morph button on the search bar.
   */
  async openMorphCode(initial) {
    return this.openMorph(initial);
  },

  _isFunctionWord(w) {
    const morph = (w.morph || []).join(' ').toUpperCase();
    // Greek Robinson codes
    if (/^T[-_]/.test(morph) || morph === 'T') return true;       // article
    if (morph.indexOf('CONJ') === 0 || morph === 'CONJ') return true; // conjunction
    if (morph.indexOf('PREP') === 0) return true;                  // preposition
    if (morph.indexOf('PRT') === 0) return true;                   // particle
    // Hebrew OSHB codes (H-prefixed)
    if (morph.indexOf('HT') === 0) return true;                    // article
    if (morph === 'HC' || morph.indexOf('HC ') === 0) return true; // conjunction
    if (morph.indexOf('HR') === 0 || morph.indexOf('HTO') === 0) return true; // preposition
    if (morph.indexOf('HD') === 0) return true;                    // demonstrative/definite
    // Strong's fallback for common function words
    const FUN = new Set(['H0853','H0834','H0413','H05921','H04480','H03588',
      'H0432','G2532','G3588','G1722','G1519','G1537','G0575','G3739','G3754',
      'G1161','G0235','G1063','G3767','G3361','G3303']);
    if ((w.strongs || []).some(s => FUN.has(String(s).toUpperCase()))) return true;
    return false;
  },

  async openInterlinear(moduleId, key, label) {
    modal('Interlinear: ' + (label || ''), '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/interlinear', { id: moduleId, key });
    if (!b.ok) {
      $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error) + '</div>';
      return;
    }
    const short = (code) => String(code || '')
      .replace(/^robinson:/, '').replace(/^strongMorph:/, '').replace(/^H/, '');
    const words = b.words || [];
    const fn = (w) => this._isFunctionWord(w);
    let reader = false;
    const render = () => {
      const vis = reader ? words.filter(w => !fn(w)) : words;
      let h = '<div class="st-ref">' + esc(b.ref)
        + ' <span class="tiny muted">' + esc(b.module) + ' · '
        + b.tagged + ' words tagged'
        + (reader ? ' · reader\'s edition' : '') + '</span></div>';
      h += '<div class="tiny" style="margin:6px 0"><label>'
        + '<input type="checkbox" id="il-reader"' + (reader ? ' checked' : '') + '> Reader\'s edition (hide function words)</label></div>';
      h += '<div class="il">'
        + '<div class="il-r il-h">word</div><div class="il-r il-l">'
        + vis.map(x => '<a href="#" data-word="' + esc((x.strongs || [''])[0])
          + '">' + esc(x.form) + '</a>').join(' ')
        + '</div>'
        + '<div class="il-r il-l il-s">' + vis.map(x =>
          esc((x.strongs || []).join(',') || '·')).join(' ') + '</div>'
        + '<div class="il-r il-l il-m">' + vis.map(x =>
          esc(x.morph.map(short).join(',') || '·')).join(' ') + '</div>'
        + '<div class="il-r il-l il-g">' + vis.map(x =>
          esc(x.gloss || '')).join(' ') + '</div>'
        + '</div>';
      $('#modal-body').innerHTML = h;
      const tog = $('#il-reader');
      tog.onchange = () => { reader = tog.checked; render(); };
      this.wire($('#modal-body'));
    };
    render();
  },

  async openReverseInterlinear(moduleId, key, label) {
    modal('Reverse interlinear: ' + (label || ''), '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/reverse_interlinear', { id: moduleId, key });
    if (!b.ok) {
      $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error) + '</div>';
      return;
    }
    const short = (code) => String(code || '')
      .replace(/^robinson:/, '').replace(/^strongMorph:/, '').replace(/^H/, '');
    const words = b.words || [];
    const fn = (w) => this._isFunctionWord(w);
    let reader = false;       // reader's edition: hide function words
    let clean = false;        // clean: hide strongs/morphology
    const render = () => {
      const vis = reader ? words.filter(w => !fn(w)) : words;
      let h = '<div class="st-ref">' + esc(b.ref)
        + ' <span class="tiny muted">' + esc(b.module) + ' · '
        + b.tagged + ' words tagged · reverse'
        + (reader ? ' · reader\'s edition' : '') + '</span></div>';
      h += '<div class="tiny" style="margin:6px 0;display:flex;gap:12px;flex-wrap:wrap">'
        + '<label><input type="checkbox" id="ril-reader"' + (reader ? ' checked' : '') + '> Reader\'s edition (hide function words)</label>'
        + '<label><input type="checkbox" id="ril-clean"' + (clean ? ' checked' : '') + '> Clean (hide Strong\'s/morphology)</label>'
        + '</div>';
      h += '<div class="il il-rev' + (clean ? ' reader' : '') + '" id="ril-body">'
        + vis.map(x => {
        const orig = x.original ? '<div class="ril-orig">' + esc(x.original)
          + ' <button class="btn tiny" data-speak="' + esc(x.original) + '" title="Pronounce (browser voice)">🔊</button></div>'
          : '<div class="ril-orig muted">·</div>';
        const sn = (x.strongs || []).join(',') || '·';
        const gl = x.gloss || '';
        const morph = (x.morph || []).map(short).join(',') || '';
        return '<div class="ril-word">'
          + '<div class="ril-en">' + esc(x.form) + '</div>'
          + orig
          + '<div class="ril-sn">' + esc(sn) + '</div>'
          + '<div class="ril-morph">' + esc(morph) + '</div>'
          + '<div class="ril-gloss">' + esc(gl) + '</div>'
          + '</div>';
      }).join('')
        + '</div>';
      $('#modal-body').innerHTML = h;
      const rTog = $('#ril-reader');
      const cTog = $('#ril-clean');
      rTog.onchange = () => { reader = rTog.checked; render(); };
      cTog.onchange = () => { clean = cTog.checked; render(); };
      $$('#modal-body button[data-speak]').forEach(btn => {
        btn.onclick = (e) => {
          e.preventDefault();
          const w = btn.dataset.speak;
          try {
            const u = new SpeechSynthesisUtterance(w);
            // prefer a Greek/Hebrew voice if available
            const voices = speechSynthesis.getVoices();
            const v = voices.find(vv => /greek|hebrew|heb|ell/i.test(vv.lang + ' ' + vv.name));
            if (v) u.voice = v;
            u.rate = 0.8;
            speechSynthesis.cancel();
            speechSynthesis.speak(u);
          } catch (e) { toast('Pronunciation unavailable.', 'warn'); }
        };
      });
      this.wire($('#modal-body'));
    };
    render();
  },


  /* The assistant's section at the top of a topic guide.
   *
   * It is added only when the assistant can actually answer: a provider is
   * chosen, it has a key if it needs one, and there is a model to answer with.
   * With nothing configured the guide looks exactly as it always has, because
   * an empty box at the top of a study tool is worse than no box at all.
   *
   * The answer is generated as soon as the guide opens and cached for the
   * session: a topic asked once is free to ask again, so moving between a
   * topic and the passage it refers to does not spend the reader's tokens
   * twice over.
   */
  async guideAi(host, term, opts) {
    opts = opts || {};
    const lens = opts.lens || '';
    const action = opts.action === 'fact' ? 'fact' : 'topic';
    await Ai.ensure();
    if (Ai.blocked()) return false;

    const sec = el('div', 'st-sec ai-sec');
    sec.id = 'st-sec-ai';
    const head = el('div', 'st-h');
    const count = el('span', 'st-n');
    head.innerHTML = 'AI ';
    head.appendChild(count);
    head.appendChild(document.createTextNode(' '));
    const note = el('span', 'tiny muted');
    const lensNames = { theological: 'theological lens',
                        counseling: 'counseling lens' };
    note.textContent = 'answered from your installed material on ' + term
      + (lens ? ' (' + (lensNames[lens] || lens) + ')' : '');
    head.appendChild(note);
    sec.appendChild(head);
    // Folded by default, and the header is what opens it.  The answer is
    // generated either way: the reader asked for a guide, and the guide is
    // what they get -- the assistant's reading of it is there when they want
    // it rather than shouted at them.
    head.onclick = () => sec.classList.toggle('open');
    head.title = 'Click to fold or unfold this section';
    const body = el('div', 'st-body');
    sec.appendChild(body);

    // The suggested questions sit *outside* the folded body, so they are
    // visible the moment the guide opens.  They are the thing that makes the
    // section worth opening -- a guide that only lists what is in it is a
    // list -- and hiding them behind a fold would defeat the point.
    const asks = el('div', 'ai-topic-asks');
    const asksHead = el('div', 'tiny muted ai-asks-head');
    asksHead.textContent = 'Questions to ask';
    sec.appendChild(asksHead);
    sec.appendChild(asks);

    // First, because it is the thing a reader opening a guide is most likely
    // to want, and the only section that can answer a question about the
    // subject rather than list what is on it.
    const first = $('.st-sec', host);
    if (first) host.insertBefore(sec, first);
    else host.appendChild(sec);

    const out = el('div');
    body.appendChild(out);

    const hist = [];
    let busy = false;
    let lastCites = [];
    // Declared up here, with the other state, because `ask` closes over it
    // and a function that closes over a `let` declared after it is a trap
    // waiting for the day somebody calls it earlier.
    let followBtn = null;
    const overview = action === 'fact'
      ? Ai.factOverview(term, lens) : Ai.topicOverview(term);

    // The form is declared before `ask`, because `ask` uses it -- and because a
    // function that closes over a `const` declared after it is a trap waiting
    // for the day somebody calls it earlier.
    const form = el('div', 'ai-topic-form');
    const inp = el('input', 'ai-topic-in');
    inp.placeholder = 'Ask something about ' + term + '…';
    const go = el('button', 'btn tiny', 'Ask');
    form.appendChild(inp);
    form.appendChild(go);

    const ask = async (q) => {
      if (busy) return;
      busy = true;
      // The questions go quiet while a call is running.  Without this a
      // reader who clicks one while the overview is still arriving gets
      // nothing at all, and no sign that anything was wrong.
      asks.classList.add('ai-busy');
      go.disabled = true;
      inp.value = '';
      count.textContent = 'working…';
      const r = await Ai.guide(out, term, q, hist, { action, lens });
      if (r.text) {
        hist.push({ role: 'user', content: q,
                    // The overview is asked with an instruction the model was
                    // given, not one the reader typed.  It is marked so that
                    // carrying the exchange into the chat panel shows it as
                    // what it is rather than as something the reader said.
                    internal: q === overview });
        hist.push({ role: 'assistant', content: r.text });
        lastCites = r.cites || [];
        // The key tells the two guides apart: they read different corpora,
        // so an answer about the term is not an answer about the topic.
        Ai.cacheTopic(action + ':' + lens + ':' + term, r.text, r.cites);
        // Now there is an exchange to carry into the panel.
        if (followBtn) followBtn.disabled = false;
        // The badge says what is behind the fold, so a reader who never opens
        // the section still knows there is something in it.
        count.textContent = (r.cites ? r.cites.length : 0) + ' sources';
      } else {
        count.textContent = 'unavailable';
      }
      busy = false;
      asks.classList.remove('ai-busy');
      go.disabled = false;
    };
    go.onclick = () => { const q = (inp.value || '').trim(); if (q) ask(q); };
    inp.onkeydown = (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const q = (inp.value || '').trim();
      if (q) ask(q);
    };

    // The questions are written by the model from the guide's own material,
    // so they are about what is actually installed rather than about the
    // subject in general.  The generic ones are shown first, so the row is
    // never empty and never a blank space while the model thinks.
    const showQuestions = (qs) => {
      asks.innerHTML = '';
      (qs || []).forEach(q => {
        const text = (typeof q === 'string' ? q : q.question) || '';
        if (!text) return;
        const c = el('button', 'btn tiny', text);
        c.title = (typeof q === 'object' && q.answer) ? q.answer : '';
        c.onclick = () => ask(text);
        asks.appendChild(c);
      });
      // The way out of the guide and into the conversation.  The exchange
      // goes with the reader, so the question they were pursuing is still
      // the question they are asking.  It is not live until there is an
      // exchange to carry -- there is nothing to continue yet.
      followBtn = el('button', 'btn tiny ai-follow',
                     'Ask a follow-up question…');
      followBtn.title = 'Open the assistant panel with this exchange in it, '
        + 'and carry on there.';
      followBtn.disabled = !hist.length;
      followBtn.onclick = () => {
        App.show('ai');
        Ai.adoptTopic(hist, lastCites, term);
      };
      asks.appendChild(followBtn);
    };
    showQuestions((opts.fallback || []).map(q => ({ question: q, answer: '' })));
    Ai.guideQuestions(term, { action, lens }).then(qs => {
      if (qs && qs.length) showQuestions(qs);
    }).catch(() => {});

    body.appendChild(form);

    // If the guide is closed while the answer is still arriving, the call is
    // aborted rather than left running to completion in the background: the
    // reader asked for the guide, and the guide has gone.
    const prev = _modalCleanup;
    _modalCleanup = () => {
      if (Ai.ctrl) { Ai.ctrl.abort(); Ai.ctrl = null; }
      if (prev) { try { prev(); } catch (e) { /* the guide's own cleanup */ } }
    };

    const cached = Ai.topicCache[action + ':' + lens + ':' + term];
    if (cached) {
      // Already answered this topic: show it again without spending anything.
      if (cached.cites && cached.cites.length) {
        out.appendChild(Ai.sourceList(cached.cites));
      }
      const b = el('div', 'ai-body');
      b.innerHTML = Ai.render(cached.text);
      out.appendChild(b);
      count.textContent = (cached.cites ? cached.cites.length : 0) + ' sources';
      hist.push({ role: 'user', content: overview, internal: true });
      hist.push({ role: 'assistant', content: cached.text });
      lastCites = cached.cites || [];
      // The questions were written from the same material, so they are worth
      // keeping too: a topic asked once costs one call, not one per visit.
      // They are fetched above, and resolve out of the cache without a call.
      if (followBtn) followBtn.disabled = false;
      return true;
    }
    await ask(overview);
    return true;
  },

  async openBibleBrowser() {
    modal('Bible Browser', '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/biblebrowser', {});
    if (!b.ok) {
      $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error || 'Failed') + '</div>';
      return;
    }
    const places = b.places || [];
    const entries = b.entries || [];
    let tab = 'places';
    let q = '';
    const render = () => {
      const ql = q.trim().toLowerCase();
      const match = (s) => !ql || String(s || '').toLowerCase().indexOf(ql) >= 0;
      let list = [];
      if (tab === 'places') {
        list = places.filter(p => match(p.name) || (p.alt || []).some(match) ||
          (p.passages || []).some(match));
      } else {
        list = entries.filter(e => match(e.name) || match(e.module));
      }
      let h = '<div class="tiny" style="margin:6px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
        + '<input type="search" id="bb-q" placeholder="Filter…" value="' + esc(q) + '" style="flex:1;min-width:160px">'
        + '<button class="btn tiny' + (tab === 'places' ? ' on' : '') + '" data-tab="places">Places (' + places.length + ')</button>'
        + '<button class="btn tiny' + (tab === 'entries' ? ' on' : '') + '" data-tab="entries">Entries (' + entries.length + ')</button>'
        + '</div>';
      h += '<div class="st-body" style="max-height:60vh;overflow:auto">';
      if (tab === 'places') {
        list.slice(0, 300).forEach(p => {
          h += '<div class="st-note"><div class="st-t">' + esc(p.name) + '</div>'
            + '<div class="tiny muted">' + esc((p.alt || []).join(', ')) + '</div>'
            + '<div class="tiny">' + esc((p.passages || []).slice(0, 6).join(', ')) + '</div>'
            + '<div class="tiny"><a href="#" data-map="' + esc(p.name) + '">Open on map</a>'
            + ' <a href="#" data-ref="' + esc((p.passages || [])[0] || '') + '">Open in Bible</a></div>'
            + '</div>';
        });
      } else {
        list.slice(0, 300).forEach(e => {
          const kindBadge = e.kind === 'person' ? '<span class="chip tiny">person</span>'
            : e.kind === 'thing' ? '<span class="chip tiny">thing</span>'
            : '<span class="chip tiny">entry</span>';
          h += '<div class="st-note"><div class="st-t">' + esc(e.name) + ' ' + kindBadge + '</div>'
            + '<div class="tiny muted">' + esc(e.module) + '</div>'
            + '<div class="tiny"><a href="#" data-fact="' + esc(e.name) + '">Open Topics</a>'
            + ' <a href="#" data-ref="' + esc(e.name) + '">Open in Bible</a></div>'
            + '</div>';
        });
      }
      if (list.length > 300) {
        h += '<div class="tiny muted">Showing 300 of ' + list.length + '.</div>';
      }
      if (!list.length) h += '<div class="tiny muted">Nothing matches.</div>';
      h += '</div>';
      $('#modal-body').innerHTML = h;
      const inp = $('#bb-q');
      inp.oninput = () => { q = inp.value; render(); };
      $$('#modal-body button[data-tab]').forEach(btn => {
        btn.onclick = () => { tab = btn.dataset.tab; render(); };
      });
      $$('#modal-body a[data-fact]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Study.openFact(a.dataset.fact); };
      });
      $$('#modal-body a[data-map]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); MapsUI.showPlace && MapsUI.showPlace(a.dataset.map); };
      });
      $$('#modal-body a[data-ref]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); const ref = a.dataset.ref; if (ref) { App.show('workspace'); Reader.go((S.layout && S.layout.panes && S.layout.panes[0]) || null, ref); } };
      });
      this.wire($('#modal-body'));
    };
    render();
  },

  async openOutlineBrowser() {
    modal('Outline Browser', '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('outline/browser', {});
    if (!b.ok) {
      $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error || 'Failed') + '</div>';
      return;
    }
    const books = b.books || [];
    let openBook = books.length ? books[0].book : '';
    const render = async () => {
      let h = '<div class="tiny muted" style="margin:6px 0">' + esc(b.title || '') + ' · ' + esc(b.source || '') + '</div>';
      h += '<div class="st-body" style="max-height:60vh;overflow:auto">';
      books.forEach(bk => {
        const isOpen = bk.book === openBook;
        h += '<div class="st-sec' + (isOpen ? ' open' : '') + '">'
          + '<div class="st-h" data-book="' + esc(bk.book) + '" style="cursor:pointer">' + esc(bk.name || bk.book)
          + ' <span class="st-n">' + bk.chapters + ' ch · ' + bk.points + ' pts</span></div>';
        if (isOpen) {
          h += '<div style="padding-left:12px">';
          (bk.index || []).forEach(c => {
            h += '<div class="tiny" style="margin:2px 0"><a href="#" data-chap="' + esc(bk.book) + ':' + c.chapter + '">'
              + 'Ch ' + c.chapter + '</a> <span class="muted">(' + c.points + ')</span></div>';
          });
          if (!(bk.index || []).length) h += '<div class="tiny muted">No headings.</div>';
          h += '</div>';
        }
        h += '</div>';
      });
      h += '</div>';
      $('#modal-body').innerHTML = h;
      $$('#modal-body .st-h[data-book]').forEach(hh => {
        hh.onclick = () => { openBook = hh.dataset.book; render(); };
      });
      $$('#modal-body a[data-chap]').forEach(a => {
        a.onclick = async (e) => {
          e.preventDefault();
          const [book, ch] = a.dataset.chap.split(':');
          // Open in Bible pane as well as showing outline
          App.show('workspace');
          const pane = (S.layout && S.layout.panes && S.layout.panes[0]);
          if (pane) Reader.go(pane, book + ' ' + ch);
          const r = await api('outline/chapter', { book, chapter: ch });
          if (!r.ok) { toast('No outline.', 'warn'); return; }
          let txt = (r.sections || []).map(s => (s.title || '')).join('\n');
          modal('Outline: ' + book + ' ' + ch, '<div class="st-body">' + esc(txt || 'No headings.') + '</div>',
            [{ label: 'Close', cls: 'btn' }]);
        };
      });
      this.wire($('#modal-body'));
    };
    await render();
  },

  async openReferenceScanner() {
    modal('Reference Scanner', '<div class="st-loading">Paste text…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    let text = '';
    const render = async () => {
      const r = await api('reference/scan', { text });
      const refs = (r.ok && r.refs) ? r.refs : [];
      let h = '<div style="margin:6px 0"><textarea id="rs-text" rows="6" style="width:100%" placeholder="Paste a paragraph containing Bible references…">' + esc(text) + '</textarea></div>'
        + '<div class="tiny muted">' + refs.length + ' reference' + (refs.length === 1 ? '' : 's') + ' found.</div>'
        + '<div class="st-body" style="max-height:40vh;overflow:auto;margin-top:8px">';
      refs.forEach(x => {
        h += '<div class="st-note"><div class="st-t">' + esc(x.label) + '</div>'
          + '<div class="tiny"><a href="#" data-ref="' + esc(x.label) + '">Open passage</a></div></div>';
      });
      if (!refs.length) h += '<div class="tiny muted">No references found.</div>';
      h += '</div>';
      $('#modal-body').innerHTML = h;
      const ta = $('#rs-text');
      ta.oninput = () => { text = ta.value; };
      ta.onblur = () => render();
      $$('#modal-body a[data-ref]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Study.openPassage(a.dataset.ref); };
      });
      this.wire($('#modal-body'));
    };
    // initial with empty text
    await render();
  },

  async openNamesForGod() {
    modal('Names for God', '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/biblebrowser', {});
    if (!b.ok) { $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error || 'Failed') + '</div>'; return; }
    const terms = /god|lord|yahweh|jehovah|elohim|adonai|almighty|creator|savior|saviour|messiah|christ|shepherd|rock|king/i;
    const entries = (b.entries || []).filter(e => terms.test(e.name));
    let h = '<div class="tiny muted" style="margin:6px 0">' + entries.length + ' entries</div>'
      + '<div class="st-body" style="max-height:60vh;overflow:auto">';
    entries.slice(0, 500).forEach(e => {
      h += '<div class="st-note"><div class="st-t">' + esc(e.name) + '</div>'
        + '<div class="tiny muted">' + esc(e.module) + '</div>'
        + '<div class="tiny"><a href="#" data-fact="' + esc(e.name) + '">Open Topics</a></div></div>';
    });
    if (entries.length > 500) h += '<div class="tiny muted">Showing 500 of ' + entries.length + '.</div>';
    if (!entries.length) h += '<div class="tiny muted">Nothing found.</div>';
    h += '</div>';
    $('#modal-body').innerHTML = h;
    $$('#modal-body a[data-fact]').forEach(a => {
      a.onclick = (e) => { e.preventDefault(); Study.openFact(a.dataset.fact); };
    });
    this.wire($('#modal-body'));
  },

  async openSenseSearch() {
    modal('Sense Search', '<div class="st-loading">…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    let concept = '';
    const run = async () => {
      const r = await api('study/sensesearch', { q: concept });
      let h = '<div style="margin:6px 0;display:flex;gap:6px">'
        + '<input id="ss-q" type="search" placeholder="concept, e.g. love, covenant" value="' + esc(concept) + '" style="flex:1">'
        + '<button class="btn" id="ss-go">Search</button></div>';
      if (!r.ok) {
        h += '<div class="st-body">' + esc(r.error || 'Failed') + '</div>';
      } else {
        h += '<div class="tiny muted">' + esc(r.note || '') + '</div>';
        h += '<div class="tiny muted" style="margin:4px 0">Strong\'s: ' + (r.numbers || []).join(', ') + '</div>';
        h += '<div class="st-body" style="max-height:50vh;overflow:auto;margin-top:6px">';
        (r.verses || []).forEach(v => {
          h += '<div class="st-note"><div class="st-t">' + esc(v.ref) + '</div>'
            + '<div class="st-body">' + esc(v.text) + '</div>'
            + '<div class="tiny"><a href="#" data-ref="' + esc(v.ref) + '">Open</a></div></div>';
        });
        if (!(r.verses || []).length) h += '<div class="tiny muted">No verses.</div>';
        h += '</div>';
      }
      $('#modal-body').innerHTML = h;
      const inp = $('#ss-q');
      inp.onkeydown = (e) => { if (e.key === 'Enter') { concept = inp.value; run(); } };
      $('#ss-go').onclick = () => { concept = inp.value; run(); };
      $$('#modal-body a[data-ref]').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Study.openPassage(a.dataset.ref); };
      });
      this.wire($('#modal-body'));
      inp.focus();
    };
    await run();
  },

  /* Inline search: find a word inside the resource that is open in a pane.
   * This searches within a document while you read it; this does the same
   * across every pane, so a hit can point at the note that quotes it. */
  async inlineFind(term) {
    if (!term || term.length < 2) return;
    $$('mark.inf-hit').forEach(m => m.replaceWith(document.createTextNode(m.textContent)));
    const lower = term.toLowerCase();
    const hits = [];
    const panes = (S.layout && S.layout.panes) || [];
    panes.forEach((p, i) => {
      const paneEl = document.querySelector('.pane[data-pane="' + p.id + '"]');
      if (!paneEl) return;
      const body = paneEl.querySelector('.pane-body');
      if (!body) return;
      const text = (body.innerText || '').toLowerCase();
      if (text.indexOf(lower) === -1) return;
      let n = 0, at = text.indexOf(lower);
      while (at !== -1 && n < 500) { n++; at = text.indexOf(lower, at + lower.length); }
      // Highlight the first hit.  surroundContents throws if the match straddles
      // an element boundary, so the range is only split when it is inside one
      // text node; otherwise the hit is counted and left unmarked.
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      let node, marked = false;
      while (!marked && (node = walker.nextNode())) {
        const idx = (node.nodeValue || '').toLowerCase().indexOf(lower);
        if (idx === -1) continue;
        try {
          const span = document.createRange();
          span.setStart(node, idx);
          span.setEnd(node, idx + term.length);
          const mark = document.createElement('mark');
          span.surroundContents(mark);
          mark.className = 'inf-hit';
          marked = true;
        } catch (e) { /* spans markup: count it, just don't mark it */ }
      }
      hits.push({ pane: i, module: p.module_id, title: p.module_id, count: n });
    });
    modal('“' + term + '” in open panes',
      '<div class="st-body">' + (hits.length
        ? hits.map(h => '<div class="inf-row"><b>' + esc(h.title) + '</b> — '
            + h.count + ' match' + (h.count === 1 ? '' : 'es') + '</div>').join('')
        : 'Not in any open pane.') + '</div>',
      // Clearing on close as well as on the next search: a mark left behind in
      // the pane body is indistinguishable from real highlighting in the text,
      // so it has to go when the search that made it goes.
      [{ label: 'Close', cls: 'btn' }]);
    _modalCleanup = () => $$('mark.inf-hit').forEach(m =>
      m.replaceWith(document.createTextNode(m.textContent)));
  },

  /* Word find: a puzzle made out of the words of a passage you are reading. */
  async openWordFind(ref) {
    if (!ref) return;
    modal('Word find: ' + ref, '<div class="st-loading">Building…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/wordfind', { ref, size: 14, seed: 0 });
    const body = $('#modal-body');
    if (!b.ok) { body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    let h = '<div class="pg-src tiny muted">' + esc(b.note)
      + ' · every word taken from the passage itself</div>'
      + '<div class="wf-grid" style="--n:' + b.size + '">'
      + b.grid.map(row => '<div class="wf-row">' + row.split('')
          .map(c => '<span>' + esc(c) + '</span>').join('') + '</div>').join('')
      + '</div>'
      + '<div class="wf-list"><b>Words to find:</b> '
      + b.words.map(w => '<span>' + esc(w) + '</span>').join('') + '</div>';
    if (b.dropped && b.dropped.length) {
      h += '<div class="tiny muted" style="margin-top:6px">Left out because they '
        + 'do not fit the grid: ' + esc(b.dropped.join(', ')) + '</div>';
    }
    body.innerHTML = h;
  },

  /* Transliterate a Greek or Hebrew word into Latin letters, and speak it
   * using the browser's built-in speech synthesis. */
  async pronounce(word) {
    const w = (word || '').trim();
    if (!w) return;
    modal('Pronouncing ' + w, '<div class="st-loading">…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/pronounce', { word: w });
    const body = $('#modal-body');
    if (!b.ok) { body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    const isGreek = /[\u0370-\u03ff\u1f00-\u1fff]/.test(w);
    const isHebrew = /[\u0590-\u05ff]/.test(w);
    const lang = isGreek ? 'el-GR' : (isHebrew ? 'he-IL' : 'en-US');
    const speak = () => {
      if (!('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(w);
      u.lang = lang;
      u.rate = 0.9;
      u.pitch = 1;
      window.speechSynthesis.speak(u);
    };
    body.innerHTML = '<div class="st-body">'
      + '<div style="font-size:28px;line-height:1.4">' + esc(b.input) + '</div>'
      + '<div class="row" style="gap:8px;margin:10px 0">'
      + '<button class="btn primary" id="pr-speak" title="Speak this word (browser text-to-speech)">🔊 Speak</button>'
      + '<button class="btn" id="pr-stop" title="Stop speaking">⏹ Stop</button>'
      + '</div>'
      + '<div style="font-size:20px;margin:8px 0">' + esc(b.transliteration) + '</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">' + esc(b.script)
      + ' in Latin letters</div>'
      + '<div class="tiny muted" style="margin-top:8px">How the word is spelled '
      + 'out, not what it means. The letter-by-letter guide is a separate '
      + 'question: this one is how it sounds.</div></div>';
    const spk = $('#pr-speak');
    const stp = $('#pr-stop');
    if (spk) spk.onclick = () => speak();
    if (stp) stp.onclick = () => { window.speechSynthesis.cancel(); };
  },

  /* Numeric value of a Hebrew word (mispar hechri). */
  async gematria(word) {
    const w = (word || '').trim();
    if (!w) return;
    modal('Gematria: ' + w, '<div class="st-loading">…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/gematria', { word: w });
    const body = $('#modal-body');
    if (!b.ok) { body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    let h = '<div class="st-body">'
      + '<div style="font-size:26px">' + esc(b.input) + '</div>'
      + '<div style="font-size:22px;margin:8px 0">' + esc(String(b.value)) + '</div>'
      + '<div class="tiny muted" style="margin-bottom:8px">mispar hechri (standard values)</div>'
      + '<div style="font-family:monospace;font-size:13px;line-height:1.6">';
    (b.letters || []).forEach(l => {
      h += esc(l.letter) + ' = ' + l.value + '  ';
    });
    h += '</div>'
      + '<div class="tiny muted" style="margin-top:8px">Hebrew letters only; vowel points are '
      + 'ignored. A tool of curiosity, not of doctrine.</div></div>';
    body.innerHTML = h;
  },


  /* Cross-references for a reference, as a panel of its own.
   *
   * The verse guide shows these, but as one section among five.  This is the one
   * worth having on its own because a cross-reference index is *topical*: the
   * Treasury of Scripture Knowledge indexes subjects, so John 3:16 -- the most
   * quoted verse in the New Testament -- has no entry in it at all, because it
   * states no topic.  A panel that only showed this verse's entry would be empty
   * more often than not and would look broken.  So it shows both directions, and
   * says which is which: what this verse's own entry cites, and -- the one that
   * carries most verses -- which entries elsewhere in the index cite this verse.
   */
async openCrossrefs(ref) {
    if (!ref) return;
    modal('Cross-references: ' + ref,
      '<div class="st-loading">Gathering…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/crossrefs', { ref });
    const body = $('#modal-body');
    if (!b.ok) {
      body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>';
      return;
    }
    if (b.notice) {
      body.innerHTML = '<div class="st-body">' + esc(b.notice) + '</div>';
      return;
    }
    const src = '<div class="pg-src tiny muted">'
      + b.modules.map(m => esc(m.abbrev || m.name) + ' (' + m.entries + ')').join(' · ')
      + '</div>';
    const link = (label, extra) =>
      '<a href="#" data-ref="' + esc(label) + '"'
      + (extra ? ' data-key="' + esc(extra) + '"' : '') + '>' + esc(label) + '</a>';
    let h = src;

    if (b.entry) {
      h += '<div class="st-sec open"><div class="st-h">This verse in '
        + esc(b.entry.module_id.replace(/-tsk$/, ' TSK')) + '</div>'
        + '<div class="st-body">' + esc(b.entry.text) + '</div></div>';
    } else {
      h += '<div class="ct-do">This index has no entry at ' + esc(b.ref)
        + '. That is a fact about a topical index, not a gap: entries are filed '
        + 'under the subjects a passage raises, and this verse states none. '
        + 'The references below are the ones that cite it.</div>';
    }

    if (b.outgoing && b.outgoing.length) {
      h += '<div class="st-sec open"><div class="st-h">Cited here '
        + '<span class="tiny muted">' + b.outgoing.length + '</span></div>'
        + '<div class="xr-chips">' + b.outgoing.map(x => link(x.label)).join('')
        + '</div></div>';
    }
    if (b.incoming && b.incoming.length) {
      h += '<div class="st-sec open"><div class="st-h">Cites this verse '
        + '<span class="tiny muted">' + b.incoming.length + '</span></div>'
        + '<div class="xr-rows">' + b.incoming.map(x =>
          '<div class="st-note"><div class="st-src">'
          + link(x.label, x.key) + '</div>'
          + '<div class="st-body">' + esc(x.text) + '</div></div>').join('')
        + '</div></div>';
    }
    if (!b.entry && !(b.outgoing || []).length && !(b.incoming || []).length) {
      h += '<div class="st-body">Nothing in the installed indices cites this '
        + 'verse, and it has no entry of its own.</div>';
    }
body.innerHTML = h;
    $$('#modal-body a[data-ref]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      Reader.openRefAnywhere(a.dataset.ref.replace('.', ' '));
    });
    $$('.st-h', body).forEach(hh => {
      hh.onclick = () => hh.parentElement.classList.toggle('open');
      hh.title = 'Click to fold or unfold this section';
    });
    body.insertBefore(this.guideChrome(body), body.firstChild);
    this.wire(body);
  },

  /* The Passage guide: a tool some platforms do not have built in.
   * Everything in it is read out of material already installed. */
  async openPassage(ref, guide, host) {
    if (!ref) return;
    const gname = guide || 'passage';
    const target = host || null;
    if (!target) {
      modal('Passage: ' + ref, '<div class="st-loading">Gathering…</div>',
        [{ label: 'Close', cls: 'btn' }]);
    }
    const [b, g] = await Promise.all([
      api('study/passage', { ref }).catch(() => ({ ok: false })),
      api('guide/run', { guide: gname, key: ref }).catch(() => ({ ok: false })),
    ]);
    const body = target || $('#modal-body');
    if (!body) return;
    if (!target) { /* modal already painted */ }
    if (!b.ok) { body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    let h = '<div class="pg-src tiny muted">' + esc(b.ref)
      + ' · ' + b.verses + ' verse' + (b.verses === 1 ? '' : 's')
      + ' · every section read from your installed resources</div>';

    const sec = (label, note, inner) =>
      h += '<div class="st-sec open"><div class="st-h">' + esc(label)
        + (note ? ' <span class="tiny muted">' + esc(note) + '</span>' : '')
        + '</div>' + inner + '</div>';

    /* The AI section is offered only when there is text to work on, and it works
     * from the passage as installed rather than from a question: the reader
     * already has the passage on screen, so the assistant's job is to explain or
     * condense what is there.  One translation is used, not all of them -- five
     * copies of the same verses would only make the summary repeat itself. */
    const aiText = (b.texts && b.texts.length) ? b.texts[0].text : '';
    if (aiText) {
      sec('AI', b.texts[0].module,
        '<div class="st-tools">'
        + '<button class="btn" id="pg-ai-sum">Summarise this passage</button>'
        + '<button class="btn" id="pg-ai-exp">Explain this passage</button>'
        + '<button class="btn" id="pg-ai-tr">Translate this passage…</button>'
        + '<span class="tiny muted" style="align-self:center">Opens the '
        + 'assistant panel.</span></div>');
    }

    if (b.texts && b.texts.length) {
      sec('Text', b.texts.length + ' translations', b.texts.map(t =>
        '<div class="st-note"><div class="st-src">' + esc(t.module)
        + '</div><div class="st-body">' + esc(t.text) + '</div></div>').join(''));
    }
    if (b.named && b.named.length) {
      sec('People', 'names in the passage, with their meanings',
        '<div class="pg-named">' + b.named.map(n =>
          '<div class="pg-name"><span class="w">' + esc(n.word)
          + '</span><span class="g">' + esc(n.gloss)
          + '</span><span class="s">' + esc(n.source) + '</span></div>').join('')
        + '</div>');
    }
    if (b.places && b.places.length) {
      sec('Places', 'from the gazetteer', b.places.map(p =>
        '<div class="pg-place"><span class="w">' + esc(p.name) + '</span>'
        + (p.lat ? '<span class="ll">' + esc(p.lat) + ', ' + esc(p.lon) + '</span>' : '')
        + (p.comment ? '<div class="tiny muted">' + esc(p.comment) + '</div>' : '')
        + '</div>').join(''));
    }
    if (b.commentary && b.commentary.length) {
      sec('Commentary', b.commentary.length + ' entries', b.commentary.map(c =>
        '<div class="st-note"><div class="st-src">' + esc(c.module)
        + '</div><div class="st-t">' + esc(c.title) + '</div>'
        + '<div class="st-body">' + esc(c.text) + '</div>'
        + '<div class="tiny"><a href="#" data-open="' + esc(c.module_id)
        + '" data-key="' + esc(c.key) + '">Open in a pane</a></div></div>').join(''));
    }
    if (b.xrefs && b.xrefs.length) {
      sec('Cross-references', b.xrefs.length + ' links',
        '<div class="pg-xref">' + b.xrefs.map(x =>
          '<a href="#">' + esc(x.label.replace('.', ' ')) + '</a>').join('')
        + '</div>');
    }
    const _markerItems = (b.sermons || []).concat(b.studies || []);
    if (_markerItems.length) {
      sec('Sermons & studies', _markerItems.length + ' item'
        + (_markerItems.length === 1 ? '' : 's'),
        _markerItems.map(m =>
          '<div class="st-note"><div class="st-src">' + esc(m.kind)
          + '</div><div class="st-t">' + esc(m.title) + '</div>'
          + (m.preview ? '<div class="st-body">' + esc(m.preview) + '</div>' : '')
          + '</div>').join(''));
    }
    h += configuredGuideHtml(g);
    body.innerHTML = h;
    body.insertBefore(this.guideChrome(body, gname), body.firstChild);
    $$('.st-h', body).forEach(hh => {
      hh.onclick = () => hh.parentElement.classList.toggle('open');
      hh.title = 'Click to fold or unfold this section';
    });
    const aiGo = (id, fn) => { const btn = $('#' + id, body); if (btn) btn.onclick = fn; };
    aiGo('pg-ai-sum', () => Ai.ask('summarize', aiText, b.ref));
    aiGo('pg-ai-exp', () => Ai.ask('explain', aiText, b.ref));
    aiGo('pg-ai-tr', () => Ai.translateText(aiText, b.ref));
    this.wire(body);
  },

  /* ------------------------------------------------- guide pane renderer
   *
   * A guide pane can show any of: Passage, Word Study, Exegetical.
   * Each is a collapsible-section report collated from the installed library.
   */
  async openGuidePane(gtype, ref, host) {
    if (!ref) return;
    const target = host || null;
    if (!target) {
      modal(gtype.charAt(0).toUpperCase() + gtype.slice(1) + ': ' + ref,
        '<div class="st-loading">Gathering…</div>',
        [{ label: 'Close', cls: 'btn' }]);
    }
    const body = target || $('#modal-body');
    if (!body) return;
    if (gtype === 'passage') {
      const b = await api('study/passage', { ref }).catch(() => ({ ok: false }));
      if (!b.ok) { body.innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
      let h = '<div class="pg-src tiny muted">' + esc(b.ref)
        + ' · ' + b.verses + ' verse' + (b.verses === 1 ? '' : 's')
        + ' · every section read from your installed resources</div>';
      const sec = (label, note, inner) =>
        h += '<div class="st-sec open"><div class="st-h">' + esc(label)
          + (note ? ' <span class="tiny muted">' + esc(note) + '</span>' : '')
          + '</div>' + inner + '</div>';
      const aiText = (b.texts && b.texts.length) ? b.texts[0].text : '';
      if (aiText) {
        sec('AI', b.texts[0].module,
          '<div class="st-tools">'
          + '<button class="btn" id="pg-ai-sum">Summarise this passage</button>'
          + '<button class="btn" id="pg-ai-exp">Explain this passage</button>'
          + '<button class="btn" id="pg-ai-tr">Translate this passage…</button>'
          + '<span class="tiny muted" style="align-self:center">Opens the '
          + 'assistant panel.</span></div>');
      }
      if (b.texts && b.texts.length) {
        sec('Text', b.texts.length + ' translations', b.texts.map(t =>
          '<div class="st-note"><div class="st-src">' + esc(t.module)
          + '</div><div class="st-body">' + esc(t.text) + '</div></div>').join(''));
      }
      if (b.named && b.named.length) {
        sec('People', 'names in the passage, with their meanings',
          '<div class="pg-named">' + b.named.map(n =>
            '<div class="pg-name"><span class="w">' + esc(n.word)
            + '</span><span class="g">' + esc(n.gloss)
            + '</span><span class="s">' + esc(n.source) + '</span></div>').join('')
          + '</div>');
      }
      if (b.places && b.places.length) {
        sec('Places', 'from the gazetteer', b.places.map(p =>
          '<div class="pg-place"><span class="w">' + esc(p.name) + '</span>'
          + (p.lat ? '<span class="ll">' + esc(p.lat) + ', ' + esc(p.lon) + '</span>' : '')
          + (p.comment ? '<div class="tiny muted">' + esc(p.comment) + '</div>' : '')
          + '</div>').join(''));
      }
      if (b.commentary && b.commentary.length) {
        sec('Commentary', b.commentary.length + ' entries', b.commentary.map(c =>
          '<div class="st-note"><div class="st-src">' + esc(c.module)
          + '</div><div class="st-t">' + esc(c.title) + '</div>'
          + '<div class="st-body">' + esc(c.text) + '</div>'
          + '<div class="tiny"><a href="#" data-open="' + esc(c.module_id)
          + '" data-key="' + esc(c.key) + '">Open in a pane</a></div></div>').join(''));
      }
      if (b.xrefs && b.xrefs.length) {
        sec('Cross-references', b.xrefs.length + ' links',
          '<div class="pg-xref">' + b.xrefs.map(x =>
            '<a href="#">' + esc(x.label.replace('.', ' ')) + '</a>').join('')
          + '</div>');
      }
      const _markerItems = (b.sermons || []).concat(b.studies || []);
      if (_markerItems.length) {
        sec('Sermons & studies', _markerItems.length + ' item'
          + (_markerItems.length === 1 ? '' : 's'),
          _markerItems.map(m =>
            '<div class="st-note"><div class="st-src">' + esc(m.kind)
            + '</div><div class="st-t">' + esc(m.title) + '</div>'
            + (m.preview ? '<div class="st-body">' + esc(m.preview) + '</div>' : '')
            + '</div>').join(''));
      }
      h += configuredGuideHtml(gtype);
      body.innerHTML = h;
      body.insertBefore(this.guideChrome(body, gtype), body.firstChild);
      $$('.st-h', body).forEach(hh => {
        hh.onclick = () => hh.parentElement.classList.toggle('open');
        hh.title = 'Click to fold or unfold this section';
      });
      const aiGo = (id, fn) => { const btn = $('#' + id, body); if (btn) btn.onclick = fn; };
      aiGo('pg-ai-sum', () => Ai.ask('summarize', aiText, b.ref));
      aiGo('pg-ai-exp', () => Ai.ask('explain', aiText, b.ref));
      aiGo('pg-ai-tr', () => Ai.translateText(aiText, b.ref));
      this.wire(body);
    }
    else if (gtype === 'word-study') {
      const r = await api('word-study', { num: ref, limit: 30 }).catch(() => ({ ok: false }));
      if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error || 'failed') + '</div>'; return; }
      const s = r.sections || {};
      let h = '<div class="pg-src tiny muted">' + esc(r.headword || ref)
        + ' · Strong’s ' + esc(r.num) + '</div>';
      const sec = (label, note, inner) =>
        h += '<div class="st-sec open"><div class="st-h">' + esc(label)
          + (note ? ' <span class="tiny muted">' + esc(note) + '</span>' : '')
          + '</div>' + inner + '</div>';
      if (r.gloss) {
        sec('Lemma', r.lemma || '',
          '<div class="st-body"><b>' + esc(r.headword || ref) + '</b> · '
          + esc(r.gloss) + '</div>');
      }
      if (s.lemma && s.lemma.length) {
        sec('Lexicon', 'articles from your installed lexica',
          s.lemma.map(x => '<div class="st-note"><div class="st-src">' + esc(x.module || '')
          + '</div><div class="st-body">' + esc(x.text || '') + '</div></div>').join(''));
      }
      if (s.translation && s.translation.length) {
        sec('Translation', 'how each Bible renders this word',
          s.translation.map(t => '<div class="st-note"><div class="st-src">'
          + esc(t.module || '') + ' (' + t.count.toLocaleString() + '×)</div>'
          + '<div class="st-body">' + t.renderings.map(r => esc(r[0]) + ' ' + r[1].toLocaleString() + '×').join(' · ')
          + '</div></div>').join(''));
      }
      if (s.senses && s.senses.length) {
        sec('Senses', 'meanings taken by this word',
          s.senses.map(x => '<div class="st-note"><div class="st-body"><b>'
          + esc(x.sense || '') + '</b> ' + esc(x.definition || '') + '</div></div>').join(''));
      }
      if (s.example_uses && s.example_uses.length) {
        sec('Example Uses', 'where this word occurs',
          s.example_uses.map(x => '<div class="st-note"><a href="#" data-ref="'
          + esc(x.ref) + '" class="pg-ref">' + esc(x.ref) + '</a> <span class="tiny muted">'
          + esc(x.surface || '') + '</span></div>').join(''));
      }
      if (s.textual_searches && s.textual_searches.length) {
        sec('Textual Searches', 'where this word occurs in each Bible',
          s.textual_searches.map(t => '<div class="st-note"><div class="st-src">'
          + esc(t.module || '') + ' (' + t.count.toLocaleString() + ' hits)</div>'
          + '<div class="st-body">' + t.sample.map(s => '<a href="#" data-ref="'
          + esc(s.ref) + '" class="pg-ref">' + esc(s.ref) + '</a> ' + esc(s.surface || '')).join(' · ')
          + '</div></div>').join(''));
      }
      body.innerHTML = h;
      body.querySelectorAll('.pg-ref').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); const ref = a.dataset.ref;
          App.show('workspace'); const pane = (S.layout && S.layout.panes && S.layout.panes[0]);
          if (pane) Reader.go(pane, ref); };
      });
    }
    else if (gtype === 'exegetical') {
      const r = await api('exegetical-guide', { ref }).catch(() => ({ ok: false }));
      if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error || 'failed') + '</div>'; return; }
      const s = r.sections || {};
      let h = '<div class="pg-src tiny muted">' + esc(r.ref)
        + ' · ' + r.verses + ' verse' + (r.verses === 1 ? '' : 's') + '</div>';
      const sec = (label, note, inner) =>
        h += '<div class="st-sec open"><div class="st-h">' + esc(label)
          + (note ? ' <span class="tiny muted">' + esc(note) + '</span>' : '')
          + '</div>' + inner + '</div>';
      if (s.word_by_word && s.word_by_word.length) {
        sec('Word by Word', 'grammar, morphology, gloss for each word',
          s.word_by_word.map(v => '<div class="st-note"><div class="st-src">'
          + esc(v.ref) + '</div><div class="st-body">'
          + v.words.map(w => '<span class="wbw-word"><b>' + esc(w.form)
          + '</b>' + (w.strongs && w.strongs.length ? ' <span class="tiny muted">[' + w.strongs.join(', ') + ']</span>' : '')
          + (w.morph && w.morph.length ? ' <span class="tiny muted">(' + w.morph.join(', ') + ')</span>' : '')
          + (w.gloss ? ' <span class="wbw-gloss">' + esc(w.gloss) + '</span>' : '') + '</span>').join(' ')
          + '</div></div>').join(''));
      }
      if (s.commentaries && s.commentaries.length) {
        sec('Commentaries', s.commentaries.length + ' entries',
          s.commentaries.map(c => '<div class="st-note"><div class="st-src">' + esc(c.module)
          + '</div><div class="st-t">' + esc(c.title) + '</div>'
          + '<div class="st-body">' + esc(c.text) + '</div></div>').join(''));
      }
      if (s.grammars && s.grammars.length) {
        sec('Grammars', 'grammar articles mentioning this passage',
          s.grammars.map(g => '<div class="st-note"><div class="st-src">' + esc(g.module)
          + '</div><div class="st-t">' + esc(g.title) + '</div>'
          + '<div class="st-body">' + esc(g.text) + '</div></div>').join(''));
      }
      if (s.visualizations && s.visualizations.length) {
        sec('Visualizations', 'text structure diagrams',
          s.visualizations.map(v => '<div class="st-note"><div class="st-src">'
          + esc(v.ref) + '</div><div class="st-body">' + esc(v.tree || '(diagram)') + '</div></div>').join(''));
      }
      if (s.important_words && s.important_words.length) {
        sec('Important Words', 'frequent in the commentaries on this passage',
          s.important_words.map(w => '<span style="margin:2px 6px 2px 0" class="chip">' + esc(w.word)
          + ' <span class="tiny">' + w.count + '×</span></span>').join(''));
      }
      body.innerHTML = h;
    }
  },

  /* ------------------------------------------------- verse-level panels
   *
   * Four small answers to four small questions, each of which used to have an
   * endpoint and no way to reach it.  They live together because they are all
   * reached from the same place -- right-click a verse -- and each one opens a
   * modal over the text rather than a new pane, so the verse you asked about
   * is still on screen behind it. */

  async openImportant(ref) {
    if (!ref) return;
    const r = await api('words/important', { ref });
    if (!r.ok) { toast(r.error || 'Could not read that verse.', 'warn'); return; }
    const items = r.items || [];
    modal('The words that matter here: ' + ref,
      '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.note)
      + ' · ' + (r.commentaries || 0) + ' commentary entries at this verse '
      + 'or chapter.</div>'
      + (items.length ? items.map(w => '<div class="org-card"><div class="org-h">'
          + '<b>' + esc(w.number) + '</b>'
          + '<span class="org-a">' + (w.surfaces || []).slice(0, 4).map(s =>
              '<a href="#" data-impw="' + esc(s) + '">' + esc(s) + '</a>').join(' · ')
          + '</span></div>'
          + '<div class="tiny muted">' + (w.mentions
              ? w.mentions + ' mention' + (w.mentions === 1 ? '' : 's')
                + ' in those commentaries'
              : 'no commentary here mentions it') + '</div></div>').join('')
        : '<div class="empty">No tagged words at this verse. A Bible carrying '
          + 'Strong\'s numbers or morphology is needed.</div>'), [
      { label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-impw]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      Study.openWord(a.dataset.impw);
    });
  },

  async openCitedBy(ref) {
    if (!ref) return;
    const r = await api('citedby', { ref });
    if (!r.ok) { toast(r.error || 'Could not read that reference.', 'warn'); return; }
    const side = (name, map) => {
      const names = Object.keys(map || {});
      if (!names.length) return '';
      return '<div class="st-sec open"><div class="st-h">' + esc(name) + '</div>'
        + names.map(n => '<div class="tiny" style="margin:3px 0"><b>'
          + esc(n) + '</b> — '
          + (map[n] || []).map(k => '<a href="#" data-eqr="'
            + esc(k) + '">' + esc(k.replace(/\./g, ' ')) + '</a>').join(', ')
          + '</div>').join('') + '</div>';
    };
    modal('Cited by: ' + ref,
      '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.note)
      + '</div>'
      + '<div class="tiny" style="margin-bottom:8px">'
      + (r.cited_by_count || 0) + ' cross-reference table'
      + (r.cited_by_count === 1 ? '' : 's') + ' cite it · '
      + (r.cites_count || 0) + ' it cites · scope: ' + esc(r.scope) + '</div>'
      + side('Cited by', r.incoming) + side('Cites', r.outgoing),
      [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body [data-eqr]').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      App.show('workspace');
      Reader.openRefAnywhere(a.dataset.eqr.replace(/\./g, ' '));
    });
  },

  async openQuestions(ref) {
    if (!ref) return;
    const r = await api('questions', { ref });
    if (!r.ok) { toast(r.error || 'Could not read that reference.', 'warn'); return; }
    const qs = r.questions || [];
    modal('Study questions: ' + ref,
      '<div class="tiny muted" style="margin-bottom:8px">Built from this '
      + 'passage&#8217;s own headings and names, by template. Each one says '
      + 'where it came from — they are prompts, not answers.</div>'
      + qs.map((q, i) => '<div class="org-card"><div class="org-h"><b>'
        + esc(q.q) + '</b><span class="org-a"><span class="tiny muted">'
        + esc(q.from) + '</span></span></div></div>').join('')
      + '<div class="row" style="gap:6px;margin-top:10px">'
      + '<button class="btn primary" id="q-save">Save all as a note</button>'
      + '<button class="btn" id="q-clip">To a clip</button></div>',
      [{ label: 'Close', cls: 'btn' }]);
    $('#q-save').onclick = async () => {
      const body = qs.map(q => '**' + q.kind + '** — ' + q.q
        + '\n  <small>' + q.from + '</small>').join('\n\n');
      await post('notes/save', { kind: 'note', title: 'Study questions: ' + ref,
        ref_label: ref, body });
      closeModal();
      toast('Saved as a note.');
    };
    $('#q-clip').onclick = () => {
      const text = ref + '\n\n' + qs.map(q => q.q + '\n  — ' + q.from).join('\n');
      closeModal();
      Clippings.capture(text, '', ref, '');
    };
  },

  /* The pronunciation guide is the letter-by-letter breakdown, which is a
   * different question from the transliteration Study.pronounce gives: one
   * tells you how it looks, the other how it sounds. */
  async openPronounceGuide(word) {
    if (!word) return;
    const r = await api('pronounce/guide', { word });
    if (!r.ok) { toast(r.error || 'Nothing to sound out.', 'warn'); return; }
    modal('Pronouncing ' + r.word,
      '<div class="tiny muted" style="margin-bottom:8px">' + esc(r.convention)
      + '</div>'
      + (r.transliteration ? '<div class="dash-h" style="margin-bottom:8px">'
        + esc(r.transliteration) + '</div>' : '')
      + '<div class="org-items">'
      + (r.letters || []).map(l => '<span class="org-item" title="'
        + esc(l.sound) + '"><b style="font-size:1.4em">' + esc(l.letter)
        + '</b><br><span class="tiny muted">' + esc(l.sound) + '</span></span>')
        .join('') + '</div>', [{ label: 'Close', cls: 'btn' }]);
  },

  /* Everything an installed cross-reference table links this verse to.
   *
   * Which resource is asked matters and is said out loud.  A Bible carrying a
   * cross-reference table gives parallel passages -- what this feature is for.
   * A topical work's table links verses to *headings* instead, so the same
   * question returns "CONDESCENSION OF GOD, GIFTS FROM GOD".  That is a real
   * answer to a different question, so the two kinds are separated here rather
   * than listed together with the links all looking the same.
   *
   * A shape test is used to tell them apart because the endpoint returns bare
   * keys and the front end has no canon table of its own to ask.  "1Cor.3.22"
   * is three dot-separated parts with the last part a number; "GIFTS FROM GOD"
   * is neither. */
  async openEquivalent(ref, moduleId) {
    if (!ref) return;
    const xrefBibles = S.modules.filter(m => m.is_bible && m.has_xref);
    const anyXref = S.modules.filter(m => m.has_xref);
    let mid = moduleId;
    let why = '';
    if (xrefBibles.length) {
      mid = xrefBibles[0].id;
      why = 'the cross-reference table in ' + xrefBibles[0].name;
    } else if (anyXref.length) {
      mid = anyXref[0].id;
      why = 'no Bible you have installed carries a cross-reference table, so '
        + 'this comes from the one in ' + anyXref[0].name;
    } else if (mid && modById(mid)) {
      why = 'that resource carries no cross-reference table';
    } else {
      toast('Nothing installed carries a cross-reference table.', 'warn');
      return;
    }
    const r = await api('search/equivalent', { id: mid, ref });
    if (!r.ok) { toast(r.error || 'Could not read that reference.', 'warn'); return; }
    const keys = (r.equivalent || []).filter(k => k !== r.key);
    const isRef = (k) => /^[A-Za-z0-9]+\.[A-Za-z0-9]+\.\d+$/.test(k)
      || /^\d?\s?[A-Za-z]+\s+\d+/.test(k);
    const passages = keys.filter(isRef);
    const topics = keys.filter(k => !isRef(k));
    const chips = (rows, opener) => '<div class="org-items"'
      + ' style="max-height:44vh;overflow:auto">' + rows.map(k =>
          '<span class="org-item"><a href="#" data-key="' + esc(k) + '">'
          + esc(opener(k)) + '</a></span>')
        .join('') + '</div>';
    modal('Linked with ' + ref,
      '<div class="tiny muted" style="margin-bottom:8px">' + esc(why) + '.'
      + '</div>'
      + (passages.length
          ? '<div class="st-sec open"><div class="st-h">Passages ('
            + passages.length + ')</div>'
            + chips(passages, osisToRef) + '</div>'
          : '')
      + (topics.length
          ? '<div class="st-sec open"><div class="st-h">Headings ('
            + topics.length + ') — a topical table links verses to entries, '
            + 'not to passages</div>' + chips(topics, k => k) + '</div>'
          : '')
      + (!keys.length ? '<div class="empty">That table links this verse to '
        + 'nothing.</div>' : ''),
      [{ label: 'Close', cls: 'btn' },
       { label: 'Read these in one pane', cls: 'btn primary', close: false,
         fn: async () => {
           if (!passages.length) {
             toast('That table has no passages to read here.', 'warn');
             return;
           }
           const bible = S.modules.find(m => m.is_bible && m.lang === 'eng')
             || S.modules.find(m => m.is_bible);
           if (!bible) { toast('No Bible is installed.', 'warn'); return; }
           await Study.readFiltered(bible.id, passages.map(osisToRef), ref);
         } }]);
    $$('#modal-body .org-item a').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      const key = a.dataset.key;
      const text = a.textContent.trim();
      closeModal();
      if (isRef(key)) {
        App.show('workspace');
        Reader.openRefAnywhere(text);
        return;
      }
      /* A heading is not a reference, so it goes to the Factbook rather
       * than being handed to the reference parser, which would either fail
       * or -- worse -- guess something. */
      App.show('workspace');
      Study.openFact(text);
    });
  },

  /* Read exactly these references, in this order, in one pane.
   *
   * Uses the filtered-reading endpoint rather than building a cursor here, so
   * the resolution is done by the same parser the reader uses and a reference
   * that cannot be resolved is *reported* instead of quietly vanishing -- a
   * filtered view that silently dropped half its verses would be worse than no
   * filtered view at all. */
  async readFiltered(moduleId, refs, name) {
    if (!moduleId || !refs || !refs.length) return;
    const r = await api('bible/filtered', { id: moduleId, refs });
    if (!r.ok) { toast(r.error || 'Could not read those passages.', 'warn'); return; }
    const keys = (r.items || []).map(i => i.key);
    if (!keys.length) { toast('None of those passages are in that resource.', 'warn'); return; }
    const lay = S.layout || { panes: [] };
    let p = lay.panes.find(x => x.module_id === moduleId);
    if (!p) p = await Workspace.openModule(moduleId, {});
    if (!p) return;
    p.cursor = { keys, list_name: name || (refs.length + ' passages') };
    /* Written before the layout is re-read: loadWorkspace() takes the panes
     * back from the server, so a cursor still sitting in memory is thrown away
     * and the pane comes back on whatever it was showing before. */
    await Reader.saveNow(p);
    App.show('workspace');
    await App.loadWorkspace();
    App.showPane(p.tile_id || 't0', p.id);
    const missing = r.missing || [];
    toast(keys.length + ' passages'
      + (missing.length ? ' · ' + missing.length + ' not in this resource: '
        + missing.slice(0, 3).join(', ') + (missing.length > 3 ? '…' : '')
        : ''));
  },

  /* The guide editor: which sections a passage guide shows, in what order,
   * and how many of each.
   *
   * A fixed section list answers one reader's library and not another's.  This
   * lets the list be changed *and* stores the change, so the guide a reader
   * configures once is the guide they get every time -- which is the whole
   * difference between a setting and a one-off dialog.
   *
   * The sections offered are read from the server rather than written here, so
   * a section added to SECTION_DEFS appears without a matching edit in the
   * front end, and one removed cannot be configured back into existence.
   *
   * Chosen sections are listed first and off ones below a divider, never
   * interleaved.  Interleaving makes the move-up and move-down controls
   * useless: a chosen section with an unchosen one above it cannot move up,
   * because the slot it would enter is not itself chosen. */
  async configureGuide(ref, moduleId) {
    const defs = await api('guide/sections');
    const cur = await api('guide/config', { guide: 'passage' });
    const all = defs.sections || [];
    const byId = {};
    (cur.sections || []).forEach((s) => {
      if (s && s.id) byId[s.id] = s;
    });
    if (!all.length) { toast('No guide sections are defined.', 'warn'); return; }
    const chosen = (cur.sections || []).map((s) => all.find(d => d.id === s.id))
      .filter(Boolean);
    const rest = all.filter((d) => !byId[d.id]);

    const row = (def, limit) =>
      '<div class="org-card" data-gs="' + esc(def.id) + '" data-on="1">'
      + '<div class="org-h">'
      + '<span style="display:flex;gap:6px;align-items:center;flex:1">'
      + '<b>' + esc(def.title) + '</b></span>'
      + '<span class="org-a tiny muted">' + esc((def.kinds || []).join(', '))
      + '</span></div>'
      + '<div class="tiny muted">' + esc(def.about || '') + '</div>'
      + '<div class="row" style="gap:6px;margin-top:6px">'
      + '<label class="tiny">show <input type="number" class="gs-lim" min="1"'
      + ' max="200" value="' + esc(limit || 10) + '" style="width:64px">'
      + ' of these</label>'
      + '<button class="btn tiny" data-gsdrop="' + esc(def.id)
      + '" title="remove this section">remove</button>'
      + '<span class="org-a">'
      + '<a href="#" class="gs-up" title="move up">↑</a>'
      + '<a href="#" class="gs-down" title="move down">↓</a>'
      + '</span></div></div>';

    const offRow = (def) =>
      '<div class="org-card" data-gs="' + esc(def.id) + '">'
      + '<div class="org-h"><b>' + esc(def.title) + '</b>'
      + '<span class="org-a"><button class="btn tiny" data-gsadd="'
      + esc(def.id) + '">add</button></span></div>'
      + '<div class="tiny muted">' + esc(def.about || '') + '</div></div>';

    const paint = () => {
      $('#modal-body').innerHTML =
        '<div class="tiny muted" style="margin-bottom:8px">Tick the sections '
        + 'you want and set how many of each. The order is the order they '
        + 'appear, and this is remembered for next time.</div>'
        + '<div id="gs-on">' + (chosen.length
            ? chosen.map(d => row(d, byId[d.id] && byId[d.id].limit)).join('')
            : '<div class="empty tiny">No sections chosen. Add one below.</div>')
        + '</div>'
        + '<h4 style="margin:14px 0 6px">More sections</h4>'
        + '<div id="gs-off">' + (rest.length
            ? rest.map(offRow).join('')
            : '<div class="tiny muted">Every section is in the guide.</div>')
        + '</div>'
        + '<div class="tiny muted" style="margin-top:8px">The default guide '
        + 'leaves a few thorough sections out — they are slow, not wrong — so '
        + 'adding them is a deliberate act.</div>';
      wire();
    };

    const wire = () => {
      const on = $('#gs-on');
      const move = (d) => (e) => {
        e.preventDefault();
        const c = e.target.closest('.org-card');
        const sib = d < 0 ? c.previousElementSibling : c.nextElementSibling;
        if (!sib) return;
        if (d < 0) on.insertBefore(c, sib);
        else on.insertBefore(sib, c);
      };
      on.querySelectorAll('.gs-up').forEach(a => a.onclick = move(-1));
      on.querySelectorAll('.gs-down').forEach(a => a.onclick = move(1));
      on.querySelectorAll('[data-gsdrop]').forEach(b => b.onclick = () => {
        const def = all.find(d => d.id === b.dataset.gsdrop);
        const i = chosen.findIndex(d => d.id === b.dataset.gsdrop);
        if (i < 0) return;
        chosen.splice(i, 1);
        rest.unshift(def);
        paint();
      });
      $('#gs-off').querySelectorAll('[data-gsadd]').forEach(b => b.onclick = () => {
        const def = all.find(d => d.id === b.dataset.gsadd);
        const i = rest.findIndex(d => d.id === b.dataset.gsadd);
        if (i < 0) return;
        rest.splice(i, 1);
        chosen.push(def);
        paint();
      });
      on.querySelectorAll('.gs-lim').forEach(n => {
        n.onchange = () => {
          const id = n.closest('.org-card').dataset.gs;
          const v = Math.max(1, Math.min(200, parseInt(n.value, 10) || 10));
          n.value = v;
          if (byId[id]) byId[id].limit = v;
        };
      });
    };

    modal('Configure Passage', '', [
      { label: 'Cancel', cls: 'btn' },
      { label: 'Reset to default', cls: 'btn', close: false, fn: async () => {
        await post('guide/config', { action: 'set', guide: 'passage', sections: [] });
        closeModal();
        toast('Back to the default guide.');
      } },
      { label: 'Save', cls: 'btn primary', close: false, fn: async () => {
        const secs = on.querySelectorAll('.org-card[data-on]');
        if (!secs.length) {
          toast('Add at least one section, or press Reset.', 'warn');
          return;
        }
        const payload = Array.from(secs).map(c => {
          const lim = c.querySelector('.gs-lim');
          return { id: c.dataset.gs, limit: lim ? (parseInt(lim.value, 10) || 10) : 10 };
        });
        const r = await post('guide/config', { action: 'set', guide: 'passage',
          sections: payload });
        closeModal();
        toast(r.ok ? 'Guide saved — ' + payload.length + ' sections.'
          : (r.error || 'Could not save that.'), r.ok ? '' : 'err');
      } }]);
    paint();
    void ref; void moduleId;
  },


  /* Create a new named guide from the same section editor.  The only
   * difference from configureGuide is that the result is saved under a name
   * the reader chooses, rather than overwriting a preset. */
  async createGuide(ref) {
    const defs = await api('guide/sections');
    const all = defs.sections || [];
    if (!all.length) { toast('No guide sections are defined.', 'warn'); return; }

    modal('New guide', '',
      [{ label: 'Cancel', cls: 'btn' },
       { label: 'Create', cls: 'btn primary', close: false, fn: async () => {
         const name = ($('#cg-name').value || '').trim();
         if (!name) { toast('Name the guide.', 'warn'); return; }
         const secs = Array.from(
           document.querySelectorAll('#cg-sections .org-card[data-on]')
         ).map(c => {
           const lim = c.querySelector('.gs-lim');
           return { id: c.dataset.gs,
             limit: lim ? (parseInt(lim.value, 10) || 10) : 10 };
         });
         if (!secs.length) { toast('Add at least one section.', 'warn'); return; }
         const r = await post('guide/create', { name, sections: secs });
         if (!r.ok) { toast(r.error || 'Could not create.', 'err'); return; }
         closeModal();
         toast('Guide "' + name + '" saved — ' + secs.length + ' sections.');
         this.openPassage(ref, name);
       } }]);

    const body = $('#modal-body');
    body.innerHTML =
      '<div class="org-new" style="margin-bottom:10px">'
      + '<input id="cg-name" placeholder="Guide name" style="flex:1">'
      + '</div>'
      + '<div id="cg-sections">'
      + all.map(d =>
          '<div class="org-card" data-gs="' + esc(d.id) + '" data-on="1">'
          + '<div class="org-h"><b>' + esc(d.title) + '</b>'
          + '<span class="org-a"><button class="btn tiny" data-cgdrop="'
          + esc(d.id) + '">remove</button></span></div>'
          + '<div class="tiny muted">' + esc(d.about || '') + '</div>'
          + '<div class="row" style="gap:6px;margin-top:6px">'
          + '<label class="tiny">show <input type="number" class="gs-lim"'
          + ' min="1" max="200" value="10" style="width:64px"> of these</label>'
          + '</div></div>').join('')
      + '</div>'
      + '<div class="tiny muted" style="margin-top:8px">Pick the sections you '
      + 'want, set how many of each, and name the guide. It appears beside '
      + 'the built-in guides.</div>';

    body.querySelectorAll('[data-cgdrop]').forEach(b => b.onclick = () => {
      const card = b.closest('.org-card');
      if (card) card.remove();
    });
  },



  /* You can collapse or expand every section of a guide from one control.
   * Two guides with the same handful of controls is worth having once, here. */
  guideChrome(host, currentGuide) {
    const bar = el('div', 'guide-bar');
    const mk = (label, fn) => {
      const btn = el('button', 'btn tiny', label);
      btn.onclick = fn;
      bar.appendChild(btn);
    };
    const secs = () => $$('.st-sec', host);
    mk('expand all', () => secs().forEach(x => x.classList.add('open')));
    mk('collapse all', () => secs().forEach(x => x.classList.remove('open')));
    /* The guide itself is a choice, so it is selectable: which template runs.
     * The presets are the app's own; custom ones are the reader's.  Both are
     * fetched from the server, so a guide added there appears here without a
     * matching edit in the front end.
     *
     * The selector shows the guide that actually ran rather than defaulting to
     * the passage guide, so opening a guide and switching to another does not
     * silently reset which one you are looking at. */
    const running = currentGuide || 'passage';
    const sel = el('select', 'btn tiny');
    sel.title = 'Which guide to run';
    api('guide/list').then((r) => {
      if (!r.ok) return;
      const guides = r.guides || [];
      if (!guides.some(g => g.id === running)) return;
      sel.innerHTML = guides.map(g =>
        '<option value="' + esc(g.id) + '"'
        + (g.id === running ? ' selected' : '') + '>'
        + esc(g.name) + (g.preset ? '' : ' (yours)') + '</option>').join('');
      sel.onchange = () => {
        const title = $('#modal-title').textContent.replace(/^Passage: /, '')
          .replace(/^Topics: /, '');
        if (title && sel.value) {
          closeModal();
          this.openPassage(title, sel.value);
        }
      };
      /* Only a guide the reader made can be removed; a preset is part of the
       * app and deleting one would leave a hole with nothing to fill it. */
      const here = guides.find(g => g.id === running);
      if (here && !here.preset) {
        const del = el('button', 'btn tiny danger', 'delete guide');
        del.onclick = async () => {
          if (!confirm('Delete the guide "' + here.name + '"?')) return;
          const res = await post('guide/delete', { name: here.id });
          closeModal();
          toast(res.ok ? 'Guide deleted.'
            : (res.error || 'Could not delete that.'), res.ok ? '' : 'err');
        };
        sel.parentNode.insertBefore(del, sel.nextSibling);
      }
    }).catch(() => {});
    bar.appendChild(sel);
    /* The section list is a choice, so it is editable: which sections appear
     * and how many of each. Saved, not just applied once -- otherwise this is
     * a dialog you re-answer every time you open a passage. */
    const cfg = el('button', 'btn tiny', 'sections\u2026');
    cfg.onclick = () => {
      const title = $('#modal-title').textContent.replace(/^Passage: /, '');
      closeModal();
      this.configureGuide(title);
    };
    bar.appendChild(cfg);
    /* A guide can be created, not just edited: pick the sections, name it, and
     * it is saved alongside the presets. */
    const newG = el('button', 'btn tiny', 'new guide');
    newG.onclick = () => {
      const title = $('#modal-title').textContent.replace(/^Passage: /, '')
        .replace(/^Topics: /, '');
      closeModal();
      this.createGuide(title);
    };
    bar.appendChild(newG);
    bar.appendChild(el('span', 'tiny muted', 'fold a section by clicking its heading'));
    return bar;
  },

  /* The FactBook guide: what a fact book is actually for.  Three sections,
   * each answering a different question about the term -- what the name meant,
   * where the place is, and what the reference works say in full. */
  /* BibleProject videos for a term, appended as a section.  Used by the Topic
     guide in every branch so the videos show even when no topic entries cover
     the term. */
  bibleProjectBlock(body, term) {
    const bpHost = el('div', 'st-sec open');
    bpHost.innerHTML = '<div class="st-h">BibleProject videos</div>'
      + '<div class="st-loading">Loading…</div>';
    body.appendChild(bpHost);
    (async () => {
      try {
        const bp = await api('bibleproject/search', { q: term, limit: 4 });
        if (bp && bp.ok && (bp.videos || []).length) {
          bpHost.innerHTML = '<div class="st-h">BibleProject videos</div>'
            + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin:8px 0">'
            + (bp.videos || []).map((v) => '<div>'
            + (v.video_url
              ? '<video controls preload="metadata" poster="' + esc(v.thumbnail || '') + '" '
                + 'src="' + esc(v.video_url) + '" style="width:100%;max-height:180px"></video>'
              : (v.thumbnail ? '<a href="' + esc(v.page_url) + '" target="_blank" rel="noopener noreferrer">'
                + '<img loading="lazy" src="' + esc(v.thumbnail) + '" alt="" style="width:100%;max-height:180px;object-fit:cover"></a>'
                : '<div class="tiny muted">Watch this video on BibleProject’s website.</div>'))
            + '<div class="st-t">' + esc(v.title) + '</div>'
            + '<div class="tiny muted">' + esc((v.description || '').slice(0, 120)) + '</div>'
            + '<div class="tiny"><a href="' + esc(v.page_url) + '" '
            + 'target="_blank" rel="noopener noreferrer">Open on BibleProject</a></div>'
            + '</div>').join('')
            + '</div>'
            + '<div class="tiny muted" style="margin-top:4px">' + esc(bp.credit || '') + '</div>';
        } else {
          bpHost.innerHTML = '<div class="st-h">BibleProject videos</div>'
            + '<div class="tiny muted">No matching videos were returned here.</div>';
        }
      } catch (e) {
        bpHost.innerHTML = '<div class="st-h">BibleProject videos</div>'
          + '<div class="tiny muted">Offline: BibleProject needs a connection.</div>';
      }
    })();
  },

  async openFact(term, lens) {
    if (!term) return;
    const lensVal = lens || '';
    modal('Topics: ' + term, '<div class="st-loading">Gathering…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const body = $('#modal-body');
    /* A lens is a different question asked of the same entries.  The selector
     * is rendered before the data so it is visible immediately; changing it
     * re-runs the query rather than leaving the reader to wonder. */
    const lensBar = '<div class="row" style="gap:6px;margin-bottom:8px">'
      + '<span class="tiny muted">Lens:</span>'
      + '<select id="fact-lens" class="btn tiny">'
      + '<option value=""' + (!lensVal ? ' selected' : '') + '>All entries</option>'
      + '<option value="theological"'
      + (lensVal === 'theological' ? ' selected' : '') + '>Theological</option>'
      + '<option value="counseling"'
      + (lensVal === 'counseling' ? ' selected' : '') + '>Counseling</option>'
      + '</select></div>';
    body.innerHTML = lensBar + '<div class="st-loading">Gathering…</div>';
    /* Wired after every render, because every render replaces the body and so
     * replaces the selector with it.  An unbound selector looks like a control
     * that does nothing, which is worse than not offering the lens at all. */
    const bindLens = () => {
      const s = $('#fact-lens');
      if (!s) return;
      s.onchange = (e) => {
        closeModal();
        this.openFact(term, e.target.value);
      };
    };
    bindLens();
    const b = await api('study/fact', { q: term, n: 8, lens: lensVal });
    if (!b.ok) {
      body.innerHTML = lensBar + '<div class="st-body">' + esc(b.error)
        + '</div>';
      bindLens();
      this.bibleProjectBlock(body, term);
      return;
    }
    if (!b.sections || !b.sections.length) {
      body.innerHTML = lensBar
        + '<div class="st-body">No topic entries cover '
        + esc(term) + '.</div>'
        + '<div class="tiny muted" style="margin-top:8px">Available topic sources: '
        + esc((b.factbooks || []).join(', ') || 'none') + '</div>';
      bindLens();
      this.bibleProjectBlock(body, term);
      return;
    }
    const books = b.factbooks || [];
    /* The lens bar is part of the rendered HTML rather than something written
     * into the body beforehand: `body.innerHTML = h` below replaces the whole
     * body, so a selector added earlier was wiped the moment the entries
     * arrived.  It has to be part of what is rendered. */
    let h = lensBar + '<div class="fact-src tiny muted">'
      + b.matched + ' entr' + (b.matched === 1 ? 'y' : 'ies') + ' matched in '
      + books.length + ' topic source' + (books.length === 1 ? '' : 's')
      + ' · ' + esc(books.join(', ')) + '</div>';
    b.sections.forEach(sec => {
      // Labelled counts: "3 1" beside PLACE read as a stray number.
      const counts = [];
      if (sec.items.length) counts.push(sec.items.length + (sec.items.length === 1 ? ' entry' : ' entries'));
      if (sec.geo && sec.geo.length) counts.push(sec.geo.length + ' located');
      h += '<div class="st-sec open"><div class="st-h">' + esc(sec.label)
        + (counts.length ? ' <span class="st-n">' + esc(counts.join(' · ')) + '</span>' : '')
        + (sec.note ? ' <span class="tiny muted">' + esc(sec.note) + '</span>' : '')
        + '</div>';
      (sec.geo || []).forEach(g => {
        h += '<div class="fact-geo"><span class="nm">' + esc(g.name) + '</span>'
          + (g.lat ? '<span class="ll">' + esc(g.lat) + ', ' + esc(g.lon) + '</span>' : '')
          + (g.refs ? '<div class="tiny muted">' + esc(g.refs.slice(0, 220)) + '</div>' : '')
          + '</div>';
      });
      sec.items.forEach(it => {
        h += '<div class="st-note"><div class="st-src">' + esc(it.module)
          + (it.length && it.length > it.text.length
            ? ' <span class="muted tiny">(' + it.length + ' chars)</span>' : '')
          + '</div><div class="st-t">' + esc(it.title) + '</div>'
          + '<div class="st-body">' + esc(it.text) + '</div>'
          + (it.module_id
            ? '<div class="tiny"><a href="#" data-open="' + esc(it.module_id)
              + '" data-key="' + esc(it.key) + '">Open in a pane</a></div>' : '')
          + '</div>';
      });
      h += '</div>';
    });
    body.innerHTML = h;
    body.insertBefore(this.guideChrome(body), body.firstChild);
    bindLens();
    $$('.st-h', body).forEach(hh => {
      hh.onclick = () => hh.parentElement.classList.toggle('open');
      hh.title = 'Click to fold or unfold this section';
    });
    this.wire(body);

    // BibleProject videos for this term, fetched on demand and appended
    // below the entries.  Played from BibleProject's own host; nothing is
    // stored here.
    this.bibleProjectBlock(body, term);

    // The assistant at the head of the fact book, with the questions the
    // lens makes.  The curated questions are the fallback, and are shown only
    // when the assistant is not there to write better ones.
    const factHost = el('div');
    // After the lens bar: the lens is the control, and the assistant's
    // questions and overview answer the question the lens sets.
    const lensSel = $('#fact-lens', body);
    const lensRow = lensSel ? lensSel.closest('.row') : null;
    body.insertBefore(factHost, lensRow ? lensRow.nextSibling
                                         : body.firstChild);
    const hadAi = await this.guideAi(factHost, term, {
      action: 'fact', lens: lensVal, fallback: b.questions || [],
    });
    if (!hadAi && b.questions && b.questions.length) {
      const q = el('div', 'st-sec open');
      q.innerHTML = '<div class="st-h">Questions to ask</div>'
        + b.questions.map(qq => '<div class="tiny" style="margin:3px 0">'
        + esc(qq) + '</div>').join('');
      factHost.appendChild(q);
    }
  },

  /* Compare: one verse in several translations.
   *
   * Two views, because they answer different questions.  Side by side shows the
   * versions; the aligned view shows *where* they part company, marking each
   * differing run in every column.  The alignment is the one the merge view uses,
   * computed in the backend, so the two views cannot disagree about what differs.
   */
async openCompare(ref) {
    modal('Compare: ' + ref, '<div class="st-loading">Loading…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const body = $('#modal-body');
    /* Which texts go side by side.
     *
     * This was hardcoded to the server's six English defaults, so the witnesses
     * -- SBLGNT, Textus Receptus, the Aleppo and Leningrad codices -- could only
     * be reached through the Apparatus tab, which offers no selection and
     * aligns every edition at once.  Asking for a comparison was therefore not
     * possible for anyone whose question is about the Greek or the Hebrew, which
     * is the only question that makes a witness comparison worth opening. */
    const WITNESS = ['Bible', 'OriginalLanguage', 'Manuscript'];
    const choices = (S.modules || []).filter(m => WITNESS.indexOf(m.type) >= 0);
    const byLang = {};
    choices.forEach(m => {
      const k = m.lang_name || m.lang || 'Unknown';
      (byLang[k] = byLang[k] || []).push(m);
    });
    const langs = Object.keys(byLang).sort();
    let b = null, ids = [], view = false;

    /* The tick boxes are read back off the DOM rather than captured in a
     * closure, for the reason modal()'s innerHTML forces everywhere else in
     * this file: a node captured here is a node the repaint has thrown away. */
    const pickerHtml = () => '<details class="cmp-pick"'
      + (choices.length > 14 ? '' : ' open') + '>'
      + '<summary class="st-head">Versions shown (' + ids.length + ' of '
      + choices.length + ')<span class="muted tiny"> · tick to change</span>'
      + '</summary>'
      + langs.map(k => '<div class="st-head tiny">' + esc(k)
        + ' <span class="muted">· ' + byLang[k].length + '</span></div>'
        + byLang[k].map(m => '<label class="cmp-opt"><input type="checkbox" '
          + 'data-cmp="' + esc(m.id) + '"'
          + (ids.indexOf(m.id) >= 0 ? ' checked' : '') + '> '
          + esc(m.abbrev || m.name)
          + (m.type === 'Bible' ? ''
             : ' <span class="muted tiny">' + esc(m.type) + '</span>')
          + '</label>').join('')).join('')
      + '</details>';

    const reload = async (aligned) => {
      body.innerHTML = '<div class="st-loading">Loading…</div>';
      const r = await api('compare', { ref, modules: ids.join(',') });
      if (!r.ok) {
        body.innerHTML = '<div class="st-body">' + esc(r.error || 'Nothing to compare.') + '</div>';
        return;
      }
      b = r;
      paint(aligned);
    };

    /* One place that re-attaches the controls, because all three views rewrite
     * the modal's innerHTML and each used to wire its own buttons -- which is
     * how the picker would have ended up working on the first view and doing
     * nothing on the other two. */
    const wire = () => {
      $$('.cmp-view button', body).forEach(x =>
        x.onclick = () => paint(x.dataset.view === 'diff' ? true
          : (x.dataset.view === 'app' ? 'app' : false)));
      $$('.cmp-pick input[data-cmp]', body).forEach(x =>
        x.onchange = () => {
          const on = $$('.cmp-pick input[data-cmp]:checked', body)
            .map(y => y.dataset.cmp);
          if (on.length < 2) {
            toast('A comparison needs at least two versions.');
            x.checked = ids.indexOf(x.dataset.cmp) >= 0;
            return;
          }
          ids = on;
          reload(view);
        });
    };

    b = await api('compare', { ref });
    if (!b.ok) { $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    ids = (b.columns || []).map(c => c.module_id).filter(Boolean);
    if (!ids.length) {
      $('#modal-body').innerHTML = '<div class="st-body">No installed version '
        + 'has that verse.</div>';
      return;
    }
    const paint = (aligned) => {
      view = aligned;
      const head = '<div class="cmp-view">' +
        '<button class="btn' + (aligned ? '' : ' on') + '" data-view="plain">Side by side</button>' +
        '<button class="btn' + (aligned ? ' on' : '') + '" data-view="diff">Where they differ</button>' +
        '<button class="btn" data-view="app">Apparatus</button>' +
        '</div>' + pickerHtml();
      if (aligned === 'app') {
        body.innerHTML = head + '<div class="st-loading" id="cmp-wait">Collating editions…</div>';
        api('apparatus/collate', { ref }).then(d => {
          if (!d.ok) {
            $('#cmp-wait').textContent = d.error || 'Nothing to collate.';
            return;
          }
          /* The headline figure is per language family, not one number for
           * everything.  A single "93.3% agreement" across Basque, Bulgarian,
           * Chinese, Thai and English at once was not a measurement of anything,
           * and it buried the Greek-versus-Greek and Hebrew-versus-Hebrew
           * comparisons underneath.  Each family is aligned on its own now and
           * says so, including when it has only one edition and so no figure
           * to give. */
          const fams = d.families || [];
          const note = '<div class="ct-do">' + esc(d.note || '')
            + (d.agreement != null ? ' ' + d.variants + ' of ' + d.words
              + ' word groups differ — ' + d.agreement + '% agreement.' : '')
            + '</div>';
          const edHtml = fams.length
            ? fams.map(fm => '<div class="st-head">' + esc(fm.family)
              + ' <span class="muted tiny">· ' + fm.editions.length
              + (fm.agreement != null
                 ? ' · ' + fm.variants + ' of ' + fm.words
                   + ' word groups differ · ' + fm.agreement + '% agreement'
                 : ' · ' + esc(fm.note || 'nothing to compare'))
              + '</span></div>'
              + fm.editions.map(e =>
                '<div class="cmp-c"><div class="st-src">' + esc(e.abbrev || e.name)
                + ' <span class="muted tiny">' + esc([e.type, e.lang].filter(Boolean).join(' · '))
                + '</span></div><div class="st-body">' + esc(e.text) + '</div></div>').join('')
              ).join('')
            : '<div class="cmp">' + (d.editions || []).map(e =>
              '<div class="cmp-c"><div class="st-src">' + esc(e.abbrev || e.name)
              + ' <span class="muted tiny">' + esc([e.type, e.lang].filter(Boolean).join(' · '))
              + '</span></div><div class="st-body">' + esc(e.text) + '</div></div>').join('')
              + '</div>';
          const miss = (d.missing || []).map(e => esc(e.name)).join(', ');
          body.innerHTML = head + note + edHtml
            + (miss ? '<div class="tiny muted">No text here in: ' + miss + '.</div>' : '');
          const scan = document.createElement('div');
          scan.className = 'tiny';
          scan.style.marginTop = '8px';
          scan.innerHTML = '<a href="#" id="cmp-scan">Scan this chapter for disagreement</a>'
            + '<div id="cmp-scanout"></div>';
          body.appendChild(scan);
          $('#cmp-scan').onclick = (ev) => {
            ev.preventDefault();
            const m = (ref || '').match(/^(.*\S)\s+(\d+)(?::\d+)?$/);
            api('apparatus/chapter', { book: m ? m[1] : ref, chapter: m ? m[2] : 0 }).then(s => {
              if (!s.ok) { $('#cmp-scanout').textContent = s.error; return; }
$('#cmp-scanout').innerHTML = (s.verses || []).slice(0, 12).map(v =>
                '<div class="wl-row"><span class="ref">' + esc(v.ref) + '</span>'
                + '<span class="txt">' + esc(v.family || 'witnesses') + ' · '
                + v.readings + ' readings · '
                + v.agreement + '% agreement · ' + v.editions + ' witnesses'
                + (v.translations_available
                   ? ' · ' + v.translations_available + ' translations not ranked'
                   : '') + '</span></div>').join('')
              || '<div class="tiny muted">No verse here has two witnesses in one language.</div>';
            });
          };
          wire();
        });
        return;
      }
      if (!aligned) {
        body.innerHTML = head + '<div class="cmp">' + b.columns.map(c =>
          '<div class="cmp-c"><div class="st-src">' + esc(c.abbrev || c.module)
          + '</div><div class="st-body">' + esc(c.text) + '</div></div>').join('')
          + '</div>';
      } else {
        body.innerHTML = head + '<div class="st-loading" id="cmp-wait">Aligning…</div>';
        api('compare/diff', { ref, modules: ids.join(',') }).then(d => {
          if (!d.ok) {
            $('#cmp-wait').textContent = d.error || 'Could not align these.';
            return;
          }
          const note = d.agreement == null ? '' :
            '<div class="ct-do">' + esc(d.variants) + ' of ' + d.words +
            ' word groups differ across the ' + d.columns.length +
            ' translations shown — ' + d.agreement + '% agreement. A dropped '
            + 'word counts as a difference, so a version that omits what the '
            + 'others have is not scored as agreeing with them.</div>';
          body.innerHTML = head + note + '<div class="cmp">' + d.columns.map(c =>
            '<div class="cmp-c"><div class="st-src">' +
            esc(c.abbrev || c.name) + '</div><div class="st-body">' +
            c.runs.map(r => r.t === 'variant'
              ? '<mark class="cmp-diff">' + esc(r.w) + '</mark>'
              : esc(r.w)).join(' ') + '</div></div>').join('') + '</div>';
          wire();
        });
      }
      wire();
    };
    paint(false);
  },

  /* Version merging needs a *passage* to be worth opening -- merging one verse
   * is just Compare with extra steps -- so this asks for a range and then
   * offers the translations, defaulting to a spread of versifications rather
   * than whatever happens to be first. */
  async openMerge(ref) {
    const bible = (S.modules || []).filter(m => m.type === 'Bible');
    if (bible.length < 2) {
      modal('Merge translations', '<div class="st-body">Merging needs two or '
        + 'more translations installed. You have ' + bible.length + '.</div>',
        [{ label: 'Close', cls: 'btn' }]);
      return;
    }
    const rr = ref || 'John 3:1-16';
    /* Default to English, and to a spread of versifications.  Taking the first
     * three off the list gave Basque, Church Slavonic and a private translation
     * -- technically a merge, but useless for reading, and the agreement
     * figure across three unrelated languages means nothing at all. */
    const eng = bible.filter(m => (m.lang || '') === 'eng');
    const seed = eng.length >= 2 ? eng : bible;
    const picks = new Set();
    const schemes = new Set();
    for (const m of seed) {
        if (picks.size >= 3) break;
        const sch = m.v11n || m.source || m.id;
        if (schemes.has(sch) && picks.size < seed.length) continue;
        schemes.add(sch);
        picks.add(m.id);
    }
    for (const m of seed) { if (picks.size >= 3) break; picks.add(m.id); }
    /* modal() assigns to innerHTML, so this has to be a string, not a node --
     * passing an element writes "[object HTMLDivElement]".  The checkboxes are
     * therefore read back off the DOM by index rather than captured in a
     * closure, which also means the set cannot drift from what is on screen. */
    const opts = bible.map((m, i) =>
      `<label class="mg-opt"><input type="checkbox" data-mg="${esc(m.id)}" `
      + `id="mg-i${i}"${picks.has(m.id) ? ' checked' : ''}> `
      + esc((m.abbrev || m.name) + (m.version ? ' (' + m.version + ')' : '')
            + (m.lang && m.lang !== 'eng' ? ' · ' + m.lang : ''))
      + '</label>').join('');
    modal('Merge translations',
      '<div class="st-body" style="margin-bottom:8px">Merged from '
      + bible.length + ' installed translations. Agreement is computed between '
      + 'the ones you tick, so two old versions and one modern one will show you '
      + 'disagreements that are really only dialects.</div>'
      + '<label class="st-lbl">Passage <input id="mg-ref" value="' + esc(rr) + '" '
      + 'style="width:14em;margin-left:6px"></label>'
      + '<div class="mg-pick">' + opts + '</div>',
      [
        // close:false, or modal() closes the dialog the moment fn() runs and
        // the merged text lands in a hidden box.
        { label: 'Merge', cls: 'btn primary', close: false, fn: async () => {
            const on = $$('#modal-body .mg-opt input:checked')
              .map(x => x.dataset.mg);
            if (on.length < 2) { toast('Tick at least two translations.'); return; }
            await Study.renderMerge($('#mg-ref').value.trim(), on);
          } },
        { label: 'Close', cls: 'btn' },
      ]);
  },

  async renderMerge(ref, ids) {
    // #modal does not exist -- the dialog elements are #modal-bg, #modal-title
    // and #modal-body -- so this guard returned on every call and the Merge
    // button appeared to do nothing at all.
    if (!$('#modal-body')) { toast('The dialog is not there.'); return; }
    $('#modal-title').textContent = 'Merged: ' + ref;
    $('#modal-body').innerHTML = '<div class="st-loading">Aligning…</div>';
    const r = await api('study/merge', { ref, modules: ids });
    if (!r.ok) {
      $('#modal-body').innerHTML = '<div class="st-body">' + esc(r.error) + '</div>';
      return;
    }
    const host = document.createElement('div');
    const p = { cursor: {}, options: {} };
    Reader.merged(r, { id: '__merge__', name: 'merge' }, host);
    $('#modal-body').innerHTML = '';
    $('#modal-body').appendChild(host);
  },

  /* =============================================== New Testament use of OT */
  ouMods(sel) {
    if (!this._ouMods) {
      this._ouMods = (S.modules || []).filter(m => m.type === 'Bible');
      const byId = new Map(this._ouMods.map(m => [m.id, m]));
      ['#ou-nt', '#ou-ot'].forEach((q) => {
        const el2 = $(q);
        el2.innerHTML = this._ouMods.map(m =>
          '<option value="' + esc(m.id) + '">' + esc(m.name) + '</option>').join('');
      });
      // No default chosen here: the pickers default to the first option, which
      // is a New Testament in Basque, and the whole view then reports nothing.
      // The server works out which Bibles have both testaments and the load
      // below sets the fields from that.
    }
    return this._ouMods;
  },

  async loadNtuSeOt() {
    if (S.view !== 'ntuseot') return;
    this.ouMods();
    /* Ask the server which installed Bibles actually carry both testaments,
     * rather than guessing from a name or a unit count. */
    if (!this._ouDefaulted) {
      const cap = await api('ntuseot/modules');
      if (cap.ok && cap.both && cap.both.length) {
        $('#ou-nt').value = cap.both[0].id;
        $('#ou-ot').value = cap.both[0].id;
      }
      this._ouDefaulted = true;
    }
    const nt = $('#ou-nt').value, ot = $('#ou-ot').value;
    const host = $('#ou-results');
    host.innerHTML = '<div class="loading">Checking every reference against the text…</div>';
    const r = await api('ntuseot/list', { nt, ot });
    host.innerHTML = '';
    if (!r.ok) { host.appendChild(el('div', 'warn', esc(r.error))); return; }
    $('#ou-head').innerHTML = esc(r.nt) + ' / ' + esc(r.ot)
      + ' · ' + r.verified_count + ' verified quotations · '
      + r.allusion_count + ' allusions · ' + r.listed + ' references checked';
    (r.notes || []).forEach(n => host.appendChild(el('div', 'notice', esc(n))));

    if (r.unverified && r.unverified.length) {
      const d = el('div', 'notice');
      d.innerHTML = '<b>' + r.unverified_count + ' references were rejected</b> and are '
        + 'not shown: ' + r.unverified
          .map(u => esc(u.nt + ' → ' + u.ot)).join(', ');
      host.appendChild(d);
    }

    const section = (title, rows, cls) => {
      if (!rows.length) return;
      host.appendChild(el('h3', '', esc(title) + ' (' + rows.length + ')'));
      const box = el('div', 'ou-list');
      rows.forEach(q => {
        const row = el('div', 'ou-item ' + cls);
        const head = el('div', 'ou-h');
        const a = el('a', 'ref', q.nt_label);
        a.href = '#';
        a.onclick = (e) => { e.preventDefault(); Reader.openRefAnywhere(q.nt_label); };
        head.appendChild(a);
        head.appendChild(el('span', 'arrow', '→'));
        const b = el('a', 'ref', q.ot_label);
        b.href = '#';
        b.onclick = (e) => { e.preventDefault(); Reader.openRefAnywhere(q.ot_label); };
        head.appendChild(b);
        /* Base this on shared passages, not on `run`.  An allusion can still
         * share a single word in order -- "1 words in order" is not an
         * explanation of why it is not a quotation. */
        const evid = q.passages
          ? q.run + ' words in order · ' + q.passages + ' shared passage'
            + (q.passages === 1 ? '' : 's')
          : 'no shared wording';
        head.appendChild(el('span', 'tiny muted', evid));
        if (q.claimed !== q.kind) {
          const warn = el('span', 'chip warn', 'listed as ' + q.claimed);
          warn.title = 'This is shown as an ' + q.kind + ' because the two verses '
            + 'do not share wording in these translations.';
          head.appendChild(warn);
        }
        row.appendChild(head);
        const two = el('div', 'ou-two');
        two.innerHTML = '<div><span class="lab">'
          + esc(q.nt_label) + '</span> ' + esc(q.nt_text) + '</div>'
          + '<div><span class="lab">' + esc(q.ot_label) + '</span> ' + esc(q.ot_text) + '</div>';
        row.appendChild(two);
        box.appendChild(row);
      });
      host.appendChild(box);
    };
    section('Quotations — the two verses share wording', r.quotations, 'q');
    section('Allusions — a real reference, but these translations word it differently',
            r.allusions, 'a');
    host.appendChild(el('div', 'st-tools', ''
      + '<button class="btn" id="ou-find">Find unlisted matches</button>'
      + '<button class="btn" id="ou-verse">What does this verse borrow?</button>'
      + '<input type="search" id="ou-vref" placeholder="e.g. Matt 1:21"'
      + ' style="width:130px">'
      + '<span class="tiny muted">Unlisted matches are verses that share '
      + 'wording with the Old Testament but are not on the reference list. '
      + 'They are candidates, not findings.</span>'));
    $('#ou-find').onclick = () => this.unlisted(nt, ot);
    $('#ou-verse').onclick = () => this.borrowed(nt, ot);
  },

  /* The reference list is a list.  This is the text: which New Testament
   * verses share wording with an Old Testament verse whether or not anybody
   * wrote the link down.  Every row carries its evidence so a candidate can
   * be judged, and the heading says plainly that it is a candidate. */
  async unlisted(nt, ot) {
    const host = $('#ou-results');
    const prev = host.innerHTML;
    host.innerHTML = '<div class="loading">Comparing the two testaments…</div>';
    const r = await api('ntuseot/find', { nt, ot, min_hits: 2, limit: 300 });
    if (!r.ok) {
      host.innerHTML = prev;
      toast(r.error || 'Could not compare them.', 'err');
      return;
    }
    /* The endpoint's key is `verses`, with the total in `verse_count` and a
     * `truncated` flag when the window cut it short. */
    const rows = r.verses || [];
    if (!rows.length) {
      host.innerHTML = prev;
      toast('No New Testament verse shares Old Testament wording beyond what '
        + 'the reference list already records.', '');
      return;
    }
    host.innerHTML = '<div class="st-tools"><button class="btn" id="ou-back">'
      + '← Back to the reference list</button><span class="tiny muted">'
      + rows.length + ' verse' + (rows.length === 1 ? '' : 's')
      + (r.truncated ? ' (more found than shown)' : '')
      + ' share wording with the Old Testament and are not on the list. '
      + 'A candidate is not a quotation: read it before you use it.'
      /* Parenthesised. Written as `... + cond ? a : b` this parses as
       * `(... + cond) ? a : b`, so the entire header becomes the *condition*
       * and innerHTML is assigned just the note -- which is exactly what
       * happened: a panel containing one sentence of prose and no results. */
      + ((r.notes || []).length ? ' ' + esc(r.notes[1]) : '')
      + '</span></div>'
      + rows.map(x => {
        const q = (x.quotes || [])[0] || {};
        return '<div class="ou-item a"><div class="ou-h">'
          + '<a class="ref" href="#">' + esc(x.label) + '</a>'
          + '<span class="tiny muted">' + (x.run || 0) + ' words in order · '
          + (x.windows || 0) + ' windows · score ' + esc(x.score)
          + (q.ot_label ? ' · from ' + esc(q.ot_label) : '') + '</span></div>'
          + '<div class="ou-two"><div>' + esc(x.text) + '</div>'
          + (q.ot_text ? '<div><span class="lab">' + esc(q.ot_label || '')
            + '</span> ' + esc(q.ot_text) + '</div>' : '') + '</div>'
          + ((x.shared || []).length ? '<div class="tiny muted">shared: '
            + esc(x.shared.join(', ')) + '</div>' : '')
          + '</div>';
      }).join('')
      + (r.notes || []).slice(2).map(n => '<div class="tiny muted"'
        + ' style="margin-top:8px">' + esc(n) + '</div>').join('');
    $('#ou-back').onclick = () => this.loadNtuSeOt();
    host.querySelectorAll('a.ref').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      Reader.openRefAnywhere(a.textContent);
    });
  },

  /* One verse, and the Old Testament verses it shares wording with. */
  async borrowed(nt, ot) {
    const ref = ($('#ou-vref').value || '').trim();
    if (!ref) { toast('Type a verse first.', 'warn'); return; }
    const r = await api('ntuseot/verse', { nt, ref, ot });
    if (!r.ok) { toast(r.error || 'Could not read that verse.', 'warn'); return; }
    const matches = r.matches || [];
    modal('What ' + r.ref + ' borrows',
      '<div class="st-body">' + esc(r.text) + '</div>'
      + '<div class="tiny muted" style="margin:6px 0">' + esc(r.module)
      + ' against ' + esc(r.ot_module) + ' · ' + r.words + ' words · '
      + r.count + ' match' + (r.count === 1 ? '' : 'es') + '</div>'
      + (matches.length ? matches.map(m =>
          '<div class="ou-item a"><div class="ou-h">'
          + '<a class="ref" href="#">' + esc(m.ot_label) + '</a>'
          + '<span class="tiny muted">' + (m.run || 0) + ' words in order · '
          + (m.windows || 0) + ' windows · shared: '
          + esc((m.shared || []).join(', ')) + '</span></div>'
          + '<div class="ou-two"><div>' + esc(m.ot_text) + '</div></div></div>')
          .join('') : '<div class="empty">No shared wording found.</div>')
      + (r.notes || []).map(n => '<div class="tiny muted">'
        + esc(n) + '</div>').join(''), [{ label: 'Close', cls: 'btn' }]);
    $$('#modal-body a.ref').forEach(a => a.onclick = (e) => {
      e.preventDefault();
      closeModal();
      App.show('workspace');
      Reader.openRefAnywhere(a.textContent);
    });
  },

  /* Populate the resource picker once, with the verse-capable resources first:
   * a concordance over a lexicon is a list of headwords, which is true but
   * rarely what someone opening this view wanted. */
  concordanceMods() {
    if (this._cgMods) return this._cgMods;
    /* Only resources keyed by verse.  The picker listed every installed module,
     * so Strong's Exhaustive Concordance appeared in it -- and choosing it gave
     * "No words matched", because its 14,199 entries are keyed by Strong's
     * number and a chapter concordance asks for verses.  A dropdown entry that
     * cannot work is worse than a missing one. */
    const rank = (m) => (m.type === 'Bible' ? 0 : m.reader === 'verse' ? 1
      : m.has_strongs ? 2 : 3);
    this._cgMods = (S.modules || [])
      .filter(m => m.type !== 'Concordance' && m.reader !== 'article')
      .slice().sort((a, b) =>
        rank(a) - rank(b) || (a.name || '').localeCompare(b.name || ''));
    const sel = $('#cg-mod');
    sel.innerHTML = this._cgMods.map(m =>
      '<option value="' + esc(m.id) + '">' + esc(m.name) + '</option>').join('');
    const first = this._cgMods.find(m => m.type === 'Bible' && m.has_strongs)
      || this._cgMods.find(m => m.type === 'Bible') || this._cgMods[0];
    if (first) sel.value = first.id;
    return this._cgMods;
  },

  async loadConcordance() {
    if (S.view !== 'concordance') return;   // App.show() drives this
    this.concordanceMods();
    const id = $('#cg-mod').value;
    const ref = ($('#cg-ref').value || 'John 3').trim();
    const word = ($('#cg-word').value || '').trim();
    if (!id) return;
    $('#cg-results').innerHTML = '<div class="loading">Indexing\u2026</div>';
    await this.openChapterConcordance(id, ref, word, $('#cg-tagged').checked);
  },

  /* The concordance lives in its own view so a chapter's 149 entries can be
   * scanned without pushing the reader out of the way. */
  /* Named distinctly from the existing Study.openConcordance(num, offset),
   * which pages through a Strong's lexicon article.  Two methods of the same
   * name on one object: the later silently replaced the earlier, and this one
   * was simply unreachable. */
  async openChapterConcordance(moduleId, ref, word, taggedOnly) {
    const m = modById(moduleId);
    if (!m) { toast('That resource is not available.'); return; }
    if (!$('#v-concordance')) return;
    /* Deliberately does not call App.show().  show() is what triggers
     * loadConcordance(), which calls this -- so switching views from in here
     * re-entered and the pane sat on "Indexing…" forever.  Navigation belongs
     * to the caller. */
    this.concordanceMods();
    $('#cg-mod').value = moduleId;
    if (ref) $('#cg-ref').value = ref;
    if (word !== undefined) $('#cg-word').value = word;
    if (taggedOnly !== undefined) $('#cg-tagged').checked = !!taggedOnly;
    const res = await api('concordance', { id: moduleId, ref: $('#cg-ref').value,
      word: $('#cg-word').value || '', tagged_only: $('#cg-tagged').checked });
    const host = $('#cg-results');
    host.innerHTML = '';
    if (!res.ok) { host.appendChild(el('div', 'warn', esc(res.error))); return; }
    $('#cg-head').innerHTML = '<b>' + esc(res.module) + '</b> \u00b7 ' + esc(res.ref)
      + ' \u00b7 ' + res.distinct + ' distinct word'
      + (res.distinct === 1 ? '' : 's') + ' \u00b7 ' + res.occurrences + ' uses'
      + (res.tagged_words ? ' \u00b7 ' + res.tagged_words + ' tagged' : '');
    (res.notes || []).forEach(n => host.appendChild(el('div', 'notice', esc(n))));

    if (!res.entries.length) {
      host.appendChild(el('div', 'empty', 'No words matched.'));
      return;
    }
    const list = el('div', 'cg-list');
    res.entries.forEach(e => {
      const row = el('div', 'cg-entry');
      const head = el('div', 'cg-e');
      const forms = e.forms.map(f => f.word).slice(0, 5).join(', ');
      head.innerHTML = '<span class="n">' + e.count + '</span>'
        + (e.strongs ? '<span class="s">' + esc(e.strongs.split(' ')[0]) + '</span>' : '')
        + '<span class="w">' + esc(forms) + '</span>'
        + (e.forms.length > 1 ? '<span class="tiny muted">' + e.forms.length + ' forms</span>' : '')
        + (e.tagged ? '' : '<span class="tiny muted" title="no Strong\'s tagging; matched by spelling">spelling</span>');
      if (e.strongs) {
        head.onclick = (ev) => {
          if (ev.target.closest('.n')) return;
          Popup.strongs(e.strongs.split(' ')[0]);
        };
        head.title = 'Open the lexicon entry';
      }
      row.appendChild(head);
      const occ = el('div', 'cg-occ');
      e.occurrences.forEach(o => {
        const line = el('div', 'cg-line');
        const ref = el('a', 'ref', o.ref);
        ref.href = '#';
        ref.onclick = (ev) => { ev.preventDefault(); Reader.openRefAnywhere(o.ref); };
        line.appendChild(ref);
        const txt = el('span', 'txt');
        txt.appendChild(document.createTextNode(o.before));
        const mk = el('b', '', o.word);
        txt.appendChild(mk);
        txt.appendChild(document.createTextNode(o.after));
        line.appendChild(txt);
        occ.appendChild(line);
      });
      row.appendChild(occ);
      list.appendChild(row);
    });
    host.appendChild(list);
  },

  async openVerse(moduleId, key, label) {
    modal(label || 'Study', '<div class="st-loading">Gathering…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/verse', { id: moduleId, key });
    if (!b.ok) { $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    $('#modal-body').innerHTML = this.verseHtml(b);
    this.wire($('#modal-body'));
  },

  async openWord(num) {
    Popup.hide();
    modal('Strong’s ' + num, '<div class="st-loading">Gathering…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const b = await api('study/word', { number: num });
    if (!b.ok) { $('#modal-body').innerHTML = '<div class="st-body">' + esc(b.error) + '</div>'; return; }
    /* Two ways out of a word.  The interlinear starts from a verse and shows its
     * words; the reverse interlinear starts from the word and shows every verse
     * it is in.  The concordance is the same walk in a form built for reading
     * straight through. */
    const tools = '<div class="st-tools">'
      + '<button class="btn" id="w-rev">Reverse interlinear</button>'
      + '<button class="btn" id="w-conc">Concordance</button>'
      + '</div>';
    $('#modal-body').innerHTML = tools + this.wordHtml(b);
    this.wire($('#modal-body'));
    $('#w-rev').onclick = () => this.openReverse(num);
    $('#w-conc').onclick = () => this.openConcordance(num);
    /* Senses, grouped from installed lexica. Decorative: the word panel is
     * complete without it, so a failure just leaves no section. */
    api('sense/for', { num }).then(s => {
      if (!s || !s.ok || !(s.senses || []).length) return;
      const host = $('#modal-body');
      if (!host) return;
      const d = document.createElement('div');
      d.className = 'st-senses';
      d.innerHTML = '<div class="st-head">Senses <span class="muted tiny">'
        + esc(s.lexica || 0) + ' lexica</span></div>'
        + s.senses.map(x => '<div class="wl-row"><span class="txt">'
          + esc(x.gloss) + '</span><span class="n">'
          + esc((x.sources || []).join(' · ')) + '</span></div>').join('')
        + '<div class="tiny muted">' + esc(s.note || '') + '</div>';
      host.appendChild(d);
    }).catch(() => {});
  },

  async openReverse(num, offset) {
    offset = offset || 0;
    Popup.hide();
    modal('Reverse interlinear · ' + num,
      '<div class="st-loading">Gathering occurrences…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const r = await api('morph/reverse', { num: num, limit: 30, offset: offset });
    const body = $('#modal-body');
    if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
    let h = '<div class="st-head"><b>' + esc(r.word || num) + '</b> '
      + '<span class="muted">' + esc(r.num) + '</span>'
      + (r.gloss ? ' <span class="muted tiny">' + esc(r.gloss) + '</span>' : '')
      + '</div>';
    h += '<div class="tiny muted">' + r.total.toLocaleString()
      + ' occurrences · showing ' + r.occurrences.length
      + ' · text in <b>' + esc(r.script) + '</b></div>';
    /* The script is stated rather than assumed: a "reverse interlinear" that is
     * really English, because the Greek here is untagged, must say so. */
    if (r.note) h += '<div class="warn">' + esc(r.note) + '</div>';
    h += '<table class="rev"><tbody>' + r.occurrences.map(o =>
      '<tr><td class="rev-ref"><a href="#" data-ref="' + esc(o.ref) + '">'
      + esc(o.ref) + '</a></td>'
      + '<td class="rev-w">' + esc(o.surface) + '</td>'
      + '<td class="rev-l">' + esc(o.line) + '</td></tr>').join('')
      + '</tbody></table>';
    if (r.next) {
      h += '<div class="tiny" style="margin-top:8px">'
        + '<a href="#" id="rev-more">Show '
        + Math.min(30, r.total - r.next) + ' more</a></div>';
    }
    body.innerHTML = h;
    body.querySelectorAll('a[data-ref]').forEach(a => {
      a.onclick = (e) => {
        e.preventDefault();
        App.show('workspace');
        Reader.openRefAnywhere(a.dataset.ref);
      };
    });
    const more = body.querySelector('#rev-more');
    if (more) more.onclick = (e) => {
      e.preventDefault();
      this.openReverse(num, r.next);
    };
  },

  async openConcordance(num, offset) {
    offset = offset || 0;
    Popup.hide();
    modal('Concordance · ' + num,
      '<div class="st-loading">Gathering occurrences…</div>',
      [{ label: 'Close', cls: 'btn' }]);
    const r = await api('morph/concordance', { num: num, limit: 50, offset: offset });
    const body = $('#modal-body');
    if (!r.ok) { body.innerHTML = '<div class="st-body">' + esc(r.error) + '</div>'; return; }
    let h = '<div class="st-head"><b>' + esc(r.headword || num) + '</b> '
      + (r.gloss ? ' <span class="muted tiny">' + esc(r.gloss) + '</span>' : '')
      + '</div>';
    h += '<div class="tiny muted">' + r.total.toLocaleString()
      + ' occurrences in <b>' + esc(r.script) + '</b></div>';
    if (r.note) h += '<div class="warn">' + esc(r.note) + '</div>';
    if (r.forms && r.forms.length) {
      h += '<div class="morph-samples">' + r.forms.slice(0, 16).map(f =>
        '<span class="chip">' + esc(f.surface) + ' <span class="muted">'
        + f.n.toLocaleString() + '</span></span>').join(' ') + '</div>';
    }
    h += '<table class="rev"><tbody>' + r.entries.map(e =>
      '<tr><td class="rev-ref"><a href="#" data-ref="' + esc(e.ref) + '">'
      + esc(e.ref) + '</a></td>'
      + '<td class="rev-w">' + esc(e.surface) + '</td>'
      + '<td class="rev-l">' + esc(e.line) + '</td></tr>').join('')
      + '</tbody></table>';
    if (r.next) {
      h += '<div class="tiny" style="margin-top:8px"><a href="#" id="conc-more">Show '
        + Math.min(50, r.total - r.next) + ' more</a></div>';
    }
    body.innerHTML = h;
    body.querySelectorAll('a[data-ref]').forEach(a => {
      a.onclick = (e) => {
        e.preventDefault();
        App.show('workspace');
        Reader.openRefAnywhere(a.dataset.ref);
      };
    });
    const more = body.querySelector('#conc-more');
    if (more) more.onclick = (e) => {
      e.preventDefault();
      this.openConcordance(num, r.next);
    };
  },

  wire(root) {
    root.onclick = (e) => {
      const w = e.target.closest('a[data-word]');
      if (w) { e.preventDefault(); this.openWord(w.dataset.word); return; }
      const r = e.target.closest('a[data-ref]');
      if (r) {
        e.preventDefault();
        closeModal();
        Reader.openRefAnywhere(r.dataset.ref);
        return;
      }
      const g = e.target.closest('a[data-geo]');
      if (g) {
        e.preventDefault();
        const [lat, lon] = g.dataset.geo.split(',').map(Number);
        window.open('https://www.openstreetmap.org/?mlat=' + lat + '&mlon='
          + lon + '#map=13/' + lat + '/' + lon, '_blank', 'noopener');
        return;
      }
      const m = e.target.closest('a[data-m]');
      if (m) {
        e.preventDefault();
        closeModal();
        Reader.focusRef(modById(m.dataset.m), m.dataset.k);
        return;
      }
      const o = e.target.closest('a[data-open]');
      if (o) {
        e.preventDefault();
        closeModal();
        const mod = modById(o.dataset.open);
        if (mod) Reader.focusRef(mod, o.dataset.key);
        return;
      }
    };
  },

  /* The right-click menu.  Everything in it is a query against something
   * already installed, so the menu is the same everywhere a word or a verse
   * can be pointed at. */
  menu(x, y, items) {
    const old = $('#ctxmenu');
    if (old) old.remove();
    const m = el('div', 'ctxmenu');
    m.id = 'ctxmenu';
    items.forEach(it => {
      if (it === '-') { m.appendChild(el('div', 'ctx-sep')); return; }
      if (it && it.section) {
        const heading = el('div', 'ctx-section', it.section);
        m.appendChild(heading);
        return;
      }
      const row = el('div', 'ctx-row');
      const b = el('button', '', it.label);
      b.onclick = () => { dismiss(); it.fn(it.color || 'yellow'); };
      row.appendChild(b);
      if (it.colors && it.colors.length) {
        const swatches = el('div', 'hl-colors');
        it.colors.forEach(color => {
          const sw = el('button', 'hl-swatch hl-swatch-' + color);
          sw.title = color;
          sw.style.background = it.swatch && it.swatch[color] ? it.swatch[color] : '';
          sw.onclick = (e) => { e.stopPropagation(); dismiss(); it.fn(color); };
          swatches.appendChild(sw);
        });
        row.appendChild(swatches);
      }
      m.appendChild(row);
    });
    document.body.appendChild(m);
    const w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x)) + 'px';
    m.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y)) + 'px';
    const close = (e) => { if (!m.contains(e.target)) dismiss(); };
    const onKey = (e) => { if (e.key === 'Escape') dismiss(); };
    const dismiss = () => {
      m.remove();
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', onKey);
    };
    setTimeout(() => document.addEventListener('click', close), 0);
    document.addEventListener('keydown', onKey);
    const firstAction = m.querySelector('.ctx-row button');
    if (firstAction) firstAction.focus({ preventScroll: true });
  },

  wordMenu(x, y, word, m, unitKey, ref, selText, strongs) {
    const items = [];
    if (word) {
      items.push({ section: 'QUICK ACTIONS' });
      items.push({ label: 'Copy word', fn: () => navigator.clipboard.writeText(word) });
      items.push({ section: 'WORD & TOPIC STUDY' });
      items.push({ label: 'Word find from ' + ref, fn: () => Study.openWordFind(ref) });
      if (/[\u0370-\u03ff]/.test(word) || /[\u0590-\u05ff]/.test(word)) {
        items.push({ label: 'Pronounce “' + word + '”',
          fn: () => Study.pronounce(word) });
        items.push({ label: 'How to sound out “' + word + '” letter by letter',
          fn: () => Study.openPronounceGuide(word) });
        if (/[\u0590-\u05ff]/.test(word)) {
          items.push({ label: 'Gematria of “' + word + '”',
            fn: () => Study.gematria(word) });
        }
      }
      items.push({ label: 'Bible Browser', fn: () => Study.openBibleBrowser() });
      items.push({ label: 'Topics for “' + word + '”', fn: () => Study.openFact(word) });
    }
    if (ref) {
      items.push({ section: 'PASSAGE RESEARCH' });
      items.push({ label: 'Cross-references for ' + ref,
                   fn: () => Study.openCrossrefs(ref) });
      items.push({ label: 'Cite / export this', fn: () => Cite.exportPassage(ref) });
      items.push({ label: 'Citation for this resource',
                   fn: () => Cite.open(m.id, ref) });
      items.push({ label: 'Copy citation with attribution',
                   fn: () => Cite.copy(m.id, ref) });
      items.push({ label: 'What this verse takes from the Old Testament',
                   fn: () => { App.show('ntuseot'); Study.loadNtuSeOt(); } });
      items.push({ label: 'Concordance for this chapter',
                   // Set the fields *before* switching view: App.show() is what
                   // triggers the load, so switching first fetched the defaults
                   // (John 3 in some other translation) and then ran a second
                   // request to correct it.
                   fn: () => {
                     if (m.reader === 'verse') $('#cg-mod').value = m.id;
                     $('#cg-ref').value = chapterOf(ref);
                     $('#cg-word').value = '';
                     App.show('concordance');
                   } });
      // Reader.repaint, not this.repaint: this arrow belongs to Study.wordMenu,
      // so `this` is Study, which has no repaint and threw
      // "this.repaint is not a function" on the first highlight ever made.
      // unitKey and ref arrive as parameters; `v` is local to the contextmenu
      // handler and does not exist here, so naming it threw on every click.
      items.push({ label: 'Outline of this chapter',
                   fn: () => {
                     const at = String(ref).match(/^(.+?)\s+(\d+)/);
                     Outlines.book = at ? at[1] : 'Gen';
                     Outlines.chapter = at ? parseInt(at[2], 10) : 1;
                     $('#g-tab').value = 'outline';
                     App.show('guides');
                   } });
      items.push({ label: 'Sentence diagram of this verse',
                   fn: () => Diagram.open(ref, m.id) });
      items.push({ label: 'Propositional flow (English) of this verse',
                   fn: () => Diagram.openFlow(ref, m.id) });
      items.push({ label: 'Which words the commentaries discuss here',
                   fn: () => Study.openImportant(ref) });
      items.push({ label: 'Who cites this verse',
                   fn: () => Study.openCitedBy(ref) });
      items.push({ label: 'Study questions for this passage',
                   fn: () => Study.openQuestions(ref) });
      items.push({ label: 'Everything a cross-reference table links it to',
                   fn: () => Study.openEquivalent(ref, m.id) });
      items.push({ label: 'Clause search from this verse',
                   fn: () => {
                     $('#cl-a').value = (word || '').trim();
                     $('#cl-b').value = '';
                     App.show('search');
                     $('#clause-results').innerHTML = '<div class="empty tiny">'
                       + 'Type a second term and press <b>Find</b>. Both terms '
                       + 'in one clause, or in two, is a different question '
                       + 'and a different answer.</div>';
                   } });
      items.push({ label: 'Preach from this verse',
                   fn: () => { Preach.enter(); } });
      items.push('-');
      items.push({ section: 'ORGANIZE & SAVE' });
      items.push({ label: 'Add to a passage list',
                   fn: () => Organise.addToPassageList(m.id, unitKey, ref) });
      items.push({ label: 'Add this resource to a collection',
                   fn: () => Organise.addModuleToCollection(m.id) });
      items.push('-');
      /* A term list is a query, not a set of rows kept from these results: the
       * whole point is that it keeps finding occurrences in books this search
       * did not reach, and in books installed tomorrow.
       *
       * Offered only for an actual word.  `wordMenu` falls back to the clicked
       * element's text when the click was not on a word, so right-clicking the
       * body of a verse offered "every occurrence of '1:1In the beginning was
       * the Word, and th'" -- a list of one thing, under a name nobody would
       * choose.  A word is short and has no sentence punctuation in it. */
      if (word && word.length <= 40 && !/[.;:,—""]/.test(word)) {
        items.push({ label: 'Every occurrence of “' + word + '” as a word list',
          fn: () => WordLists.fromQuery(word) });
      }
      /* ---- Logos-style study panes --------------------------------------
       * Open a linked Word Study, Passage Guide or Exegetical Guide pane for
       * this word or verse.  These open in the current pane's link set so the
       * guide follows the Bible as the reader moves. */
      if (strongs) {
        items.push({ section: 'OPEN IN STUDY PANES' });
        items.push({ label: 'Word Study: ' + strongs,
          fn: () => Reader.openWordStudyPane(strongs) });
      }
      items.push({ label: 'Passage Guide: ' + ref,
        fn: () => Reader.openGuidePane(ref, 'passage') });
      items.push({ label: 'Exegetical Guide: ' + ref,
        fn: () => Reader.openGuidePane(ref, 'exegetical') });
      items.push({ label: 'Translate this verse  (sends text off this computer)',
                   fn: () => Translate.passage(ref, m.id) });
      items.push({ section: 'PERSONAL STUDY' });
      items.push({
        label: 'Highlight selection',
        color: 'yellow',
        colors: Highlights.activeColors(),
        swatch: {
          yellow: '#f6e27a',
          green: '#bfe6a8',
          blue: '#b3d9f2',
          pink: '#f4bfd4',
          orange: '#f6cda2',
        },
        fn: async (color) => {
          await Highlights.add(m.id, unitKey, ref, color, selText);
          await Reader.repaint();
        } });
      items.push({ label: 'Note on this verse', fn: () => Notes.addHere(m, unitKey, ref, word) });
      /* The label says what is being tagged, because the menu is the same
       * everywhere a word or a verse can be pointed at -- and on a
       * commentary the thing tagged is the entry, not a verse. */
      items.push({ label: (m.is_bible ? 'Tag this verse…' : 'Tag this…'),
                   fn: () => Tags.picker(ref, m.id, unitKey) });
    }
    this.menu(x, y, items);
  },
};

/* ============================================================== Highlights
 *
 * The table and the endpoint have been here from the start; nothing used them,
 * which is the same as not having the feature.  Three parts:
 *
 *   add()   take the user's text selection and store it against the unit
 *   mark()  re-appear the stored quotes inside the rendered text
 *   list()  everything highlighted, on the dashboard
 *
 * mark() works on text nodes rather than on innerHTML.  Rewriting innerHTML to
 * splice in <mark> would destroy the Strong's <span>s and the verse-number
 * links the reader just built, and would have to re-escape everything in
 * between.  Splitting text nodes touches nothing else.
 */
/* =========================================================== Info pane */
