/* csta - sidebar (catalogues, selection, operations, filters), toolbar,
 * keyboard shortcuts and the calls that change the catalogues. */
'use strict';

CS.ui = (function () {
  const $ = (id) => document.getElementById(id);

  /* ------------------------------------------------------ server calls */

  /* Run an operation; stations in conflict are resolved in a dialog and
   * the call is repeated with the chosen policy. */
  async function runOp(name, body, busyMsg) {
    let done = CS.busy(busyMsg || 'Operazione in corso…');
    try {
      let res = await CS.api(name, body);
      if (res.conflicts) {
        done();
        const policy = await CS.dlg.conflicts(res.conflicts, res.labels);
        if (!policy) return null;
        done = CS.busy(busyMsg || 'Operazione in corso…');
        res = await CS.api(name, Object.assign({}, body, {policy}));
      }
      if (res.state) CS.setState(res.state);
      if (res.msg) CS.toast(res.msg, 'ok');
      return res;
    } catch (e) {
      CS.error(e);
      return null;
    } finally {
      done();
    }
  }

  async function openFiles(files) {
    if (!files) files = await CS.dlg.openFiles();
    if (!files || !files.length) return;
    const res = await runOp('load', {files}, 'Lettura dei file…');
    if (!res) return;
    for (const e of res.errors || []) CS.toast(e, 'error');
    for (const w of res.warnings || []) CS.toast(w, 'warn');
    if (res.loaded && res.loaded.length) {
      const names = res.loaded.map((id) => CS.catById.get(id)).filter(Boolean)
        .map((c) => c.letter + ' · ' + c.name + ' (' + c.n + ' stazioni)');
      CS.toast('Aperti: ' + names.join(', '), 'ok');
    }
  }

  async function newCatalog() {
    const name = await CS.dlg.prompt('Nuovo catalogo', 'Nome (diventa il nome del file al salvataggio)', 'stations_nuovo');
    if (name) await runOp('new', {name});
  }

  function defaultXmlPath(c) {
    if (c.kind === 'xml' && c.path) return CS.stem(c.path) + '_mod.xml';
    const dir = c.path ? (c.kind === 'dir' ? CS.dirname(c.path) : CS.dirname(c.path)) : CS.config.dirs.meta_rel;
    return (dir || CS.config.dirs.meta_rel) + '/' + CS.stem(c.name).replace(/[^\w.+-]+/g, '_') + '.xml';
  }

  async function saveCatalog(c, saveAs) {
    if (c.readonly) {
      CS.toast(c.name + ' non ha risposte strumentali: non si può salvare come StationXML (usa Esporta .pf)', 'error');
      return;
    }
    if (!c.n) { CS.toast(c.name + ' è vuoto', 'info'); return; }
    if (!saveAs && c.kind === 'xml' && c.path) {
      const ok = await CS.dlg.confirm('Salva ' + CS.esc(c.name),
        '<p>Sovrascrivere <code>' + CS.esc(c.path) + '</code>?</p><p class="muted">Il file attuale viene copiato in <code>' +
        CS.esc(c.path) + '.bak</code>.</p>', 'Sovrascrivi');
      if (ok) await runOp('save', {id: c.id}, 'Salvataggio…');
      return;
    }
    const path = await CS.dlg.outputPath('Salva ' + CS.esc(c.letter + ' · ' + c.name) + ' come StationXML',
      defaultXmlPath(c), 'xml');
    if (!path) return;
    await saveTo('save', {id: c.id, path}, 'Salvataggio…');
  }

  async function exportCatalog(c, fmt) {
    const def = (c.path ? CS.dirname(c.path) : CS.config.dirs.meta_rel) + '/' + CS.stem(c.name) +
      (fmt === 'pf' ? '.pf' : '_lista.txt');
    const title = fmt === 'pf' ? 'Esporta ' + CS.esc(c.letter) + ' come stazioni pyrocko (.pf)'
      : 'Esporta ' + CS.esc(c.letter) + ' come lista di codici NET.STA';
    const path = await CS.dlg.outputPath(title, def, fmt === 'pf' ? 'pf' : 'list',
      fmt === 'pf' ? 'Una stazione per NET.STA.LOC con i canali dell\'ultima epoca.' : null);
    if (!path) return;
    await saveTo('export', {id: c.id, fmt, path}, 'Esportazione…');
  }

  /* save / export with confirmation when the file exists */
  async function saveTo(name, body, msg) {
    let done = CS.busy(msg);
    try {
      let res = await CS.api(name, body);
      if (res.exists) {
        done();
        const ok = await CS.dlg.confirm('File esistente', '<p><code>' + CS.esc(res.path) +
          '</code> esiste già. Sovrascriverlo?</p><p class="muted">La versione attuale viene copiata in <code>' +
          CS.esc(res.path) + '.bak</code>.</p>', 'Sovrascrivi');
        if (!ok) return;
        done = CS.busy(msg);
        res = await CS.api(name, Object.assign({}, body, {overwrite: true}));
      }
      if (res.state) CS.setState(res.state);
      if (res.msg) CS.toast(res.msg, 'ok');
    } catch (e) {
      CS.error(e);
    } finally {
      done();
    }
  }

  async function closeCatalog(c) {
    if (c.dirty && !c.readonly) {
      const ok = await CS.dlg.confirm('Chiudi ' + CS.esc(c.name), '<p>' + CS.esc(c.letter + ' · ' + c.name) +
        ' ha modifiche non salvate. Chiuderlo comunque?</p><p class="muted">Puoi riaprirlo con Annulla (⌘Z).</p>', 'Chiudi', true);
      if (!ok) return;
    }
    await runOp('close', {id: c.id});
  }

  async function renameCatalog(c) {
    const name = await CS.dlg.prompt('Rinomina ' + CS.esc(c.letter), 'Nome', c.name);
    if (name) await runOp('rename', {id: c.id, name});
  }

  function undo() { if (CS.state.undo) runOp('undo', {}); }
  function redo() { if (CS.state.redo) runOp('redo', {}); }

  /* -------------------------------------------------- catalogue cards */

  function catCard(c) {
    const nets = Object.entries(c.nets).map(([k, v]) => (k || '?') + (Object.keys(c.nets).length > 1 ? ' ' + v : '')).join(', ');
    const tags = [];
    if (c.readonly) tags.push('<span class="tag ro" title="Senza risposte strumentali: solo confronti e selezioni">sola lettura</span>');
    if (c.kind === 'new') tags.push('<span class="tag new">nuovo</span>');
    if (c.kind === 'dir') tags.push('<span class="tag ro">' + c.nfiles + ' file</span>');
    if (c.noresp && !c.readonly) tags.push('<span class="tag warn" title="Epoche di canale senza risposta strumentale">' + c.noresp + ' senza risposta</span>');
    return '<div class="cat' + (CS.hidden.has(c.id) ? ' hidden-cat' : '') + '" data-id="' + c.id + '">' +
      '<div class="cat-head"><input type="checkbox" class="vis" title="Mostra / nascondi"' + (CS.hidden.has(c.id) ? '' : ' checked') + '>' +
      '<span class="badge" style="background:' + c.color + '">' + c.letter + '</span>' +
      '<span class="cname" title="' + CS.esc(c.path || c.name) + '">' + CS.esc(c.name) + '</span>' +
      (c.dirty && !c.readonly ? '<span class="dirty" title="Modifiche non salvate">●</span>' : '') +
      '<button class="icon menu-btn" title="Azioni">⋯</button></div>' +
      '<div class="cat-info">' + c.n + ' stazioni · ' + c.nchan + ' ep. canale' + (nets ? ' · ' + CS.esc(nets) : '') +
      (c.start ? ' · ' + c.start.slice(0, 4) + '→' + (c.end ? c.end.slice(0, 4) : 'oggi') : '') + tags.join('') + '</div>' +
      '<div class="cat-info muted">' + CS.esc(c.path || 'non salvato') + '</div></div>';
  }

  function renderCats() {
    const el = $('cat-list');
    if (!CS.cats.length) {
      el.innerHTML = '<div class="empty">Nessun catalogo. Usa <b>＋ Apri</b> per caricare file da META_DATA, ' +
        'o <b>＋ Nuovo catalogo</b>.</div>';
    } else {
      el.innerHTML = CS.cats.map(catCard).join('');
    }
    $('empty-hint').style.display = CS.cats.length ? 'none' : 'block';
    $('btn-undo').disabled = !CS.state.undo;
    $('btn-undo').title = CS.state.undo ? 'Annulla: ' + CS.state.undo + ' (⌘Z)' : 'Annulla (⌘Z)';
    $('btn-redo').disabled = !CS.state.redo;
    $('btn-redo').title = CS.state.redo ? 'Ripeti: ' + CS.state.redo + ' (⇧⌘Z)' : 'Ripeti (⇧⌘Z)';
    renderCatSelects();
    renderFilterOptions();
  }

  function menuFor(c, x, y) {
    const items = [
      ['save', 'Salva', !c.readonly && c.kind === 'xml' && c.path],
      ['saveas', 'Salva come…', !c.readonly],
      ['pf', 'Esporta stazioni pyrocko (.pf)…', true],
      ['list', 'Esporta lista NET.STA…', true],
      null,
      ['selall', 'Seleziona le sue stazioni', true],
      ['seladd', 'Aggiungi le sue stazioni alla selezione', true],
      ['selrm', 'Togli le sue stazioni dalla selezione', true],
      null,
      ['info', 'Informazioni e operazioni…', true],
      ['rename', 'Rinomina…', true],
      ['close', 'Chiudi', true, 'danger'],
    ];
    const m = $('menu');
    m.innerHTML = items.map((it) => (it === null ? '<hr>' : '<button data-act="' + it[0] + '"' + (it[2] ? '' : ' disabled') +
      (it[3] ? ' class="' + it[3] + '"' : '') + '>' + it[1] + '</button>')).join('');
    m.classList.add('open');
    const w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.min(x, window.innerWidth - w - 8) + 'px';
    m.style.top = Math.min(y, window.innerHeight - h - 8) + 'px';
    m.onclick = (e) => {
      const b = e.target.closest('button[data-act]');
      if (!b) return;
      closeMenu();
      const keys = c.stations.map((s) => s.key);
      ({
        save: () => saveCatalog(c, false),
        saveas: () => saveCatalog(c, true),
        pf: () => exportCatalog(c, 'pf'),
        list: () => exportCatalog(c, 'list'),
        selall: () => ensureVisible(c, () => CS.select(keys, 'replace')),
        seladd: () => ensureVisible(c, () => CS.select(keys, 'add')),
        selrm: () => CS.select(keys, 'remove'),
        info: () => CS.dlg.catInfo(c),
        rename: () => renameCatalog(c),
        close: () => closeCatalog(c),
      })[b.dataset.act]();
    };
  }

  function closeMenu() { $('menu').classList.remove('open'); }

  function ensureVisible(c, fn) {
    if (CS.hidden.has(c.id)) CS.setHidden(c.id, false);
    fn();
  }

  /* ---------------------------------------------- operation selectors */

  const opt = (c) => '<option value="' + c.id + '">' + CS.esc(c.letter + ' · ' + c.name) + (c.readonly ? ' (sola lettura)' : '') + '</option>';

  function fillSelect(el, cats, keep, fallbackIndex) {
    const prev = keep ? el.value : null;
    el.innerHTML = cats.map(opt).join('');
    if (prev && cats.some((c) => c.id === prev)) el.value = prev;
    else if (cats.length) el.value = cats[Math.min(fallbackIndex || 0, cats.length - 1)].id;
  }

  function renderCatSelects() {
    fillSelect($('op-src'), CS.cats, true, 0);
    fillSelect($('op-dst'), CS.cats, true, 1);
    fillSelect($('set-a'), CS.cats, true, 0);
    fillSelect($('set-b'), CS.cats, true, 1);
    updateOpButtons();
    updateSetHint();
  }

  function selectedIn(cid) {
    const c = CS.catById.get(cid);
    if (!c) return [];
    const keys = new Set(c.stations.map((s) => s.key));
    return [...CS.sel].filter((k) => keys.has(k));
  }

  function updateOpButtons() {
    const src = CS.catById.get($('op-src').value);
    const dst = CS.catById.get($('op-dst').value);
    const nsrc = src ? selectedIn(src.id).length : 0;
    const okPair = src && dst && src !== dst && !src.readonly && !dst.readonly && nsrc > 0;
    $('op-copy').disabled = !okPair;
    $('op-move').disabled = !okPair;
    $('op-delete').disabled = !(src && !src.readonly && nsrc > 0);
    $('op-newsel').disabled = !CS.sel.size;
    const n = (x) => (x ? ' (' + x + ')' : '');
    $('op-copy').textContent = 'Copia' + n(nsrc);
    $('op-move').textContent = 'Sposta' + n(nsrc);
    $('op-delete').textContent = 'Elimina da ' + (src ? src.letter : '«Da»') + n(nsrc);
  }

  function updateSetHint() {
    const a = CS.catById.get($('set-a').value), b = CS.catById.get($('set-b').value);
    const op = $('set-op').value;
    $('set-run').disabled = !(a && b && a !== b);
    if (!a || !b) { $('set-hint').textContent = 'Servono almeno due cataloghi.'; return; }
    if (a === b) { $('set-hint').textContent = 'Scegli due cataloghi diversi.'; return; }
    const ka = new Set(a.stations.map((s) => s.key)), kb = new Set(b.stations.map((s) => s.key));
    let n = 0;
    if (op === 'union') n = new Set([...ka, ...kb]).size;
    else if (op === 'inter') n = [...ka].filter((k) => kb.has(k)).length;
    else if (op === 'diff') n = [...ka].filter((k) => !kb.has(k)).length;
    else n = [...ka].filter((k) => !kb.has(k)).length + [...kb].filter((k) => !ka.has(k)).length;
    const text = {union: 'stazioni di ' + a.letter + ' o ' + b.letter, inter: 'stazioni sia in ' + a.letter + ' sia in ' + b.letter,
      diff: 'stazioni di ' + a.letter + ' che non sono in ' + b.letter,
      sym: 'stazioni in uno solo dei due'}[op];
    $('set-hint').textContent = 'Nuovo catalogo con le ' + text + ': ' + n + ' stazioni.';
  }

  /* ----------------------------------------------------------- filters */

  function renderFilterOptions() {
    const fill = (id, values, labels, allLabel) => {
      const el = $(id);
      const prev = el.value;
      el.innerHTML = '<option value="">' + allLabel + '</option>' +
        values.map((v) => '<option value="' + CS.esc(v) + '">' + CS.esc(labels ? labels[v] || v : (v || '(senza rete)')) + '</option>').join('');
      el.value = values.includes(prev) ? prev : '';
      if (el.value !== prev) {
        CS.filters[{'f-net': 'net', 'f-band': 'band', 'f-cls': 'cls'}[id]] = el.value;
      }
    };
    const rows = CS.rows;
    fill('f-net', [...new Set(rows.map((r) => r.net))].sort(), null, 'tutte');
    fill('f-band', [...new Set(rows.flatMap((r) => r.bands))].sort(), null, 'tutti');
    const used = new Set(rows.flatMap((r) => r.classes));
    fill('f-cls', CS.config.classes.order.filter((k) => used.has(k)), CS.config.classes.labels, 'tutti');
  }

  function readFilters() {
    const f = CS.filters;
    f.text = $('f-text').value;
    f.net = $('f-net').value;
    f.band = $('f-band').value;
    f.cls = $('f-cls').value;
    f.state = $('f-state').value;
    f.pres = $('f-pres').value;
    const bad = [];
    const num = (id, key) => {
      const v = CS.parseNum($(id).value);
      $(id).classList.toggle('bad', Number.isNaN(v));
      if (Number.isNaN(v)) bad.push(id);
      f[key] = Number.isNaN(v) ? null : v;
    };
    const date = (id, key, end) => {
      const v = CS.parseDate($(id).value, end);
      $(id).classList.toggle('bad', Number.isNaN(v));
      f[key] = Number.isNaN(v) ? null : v;
    };
    date('f-t0', 't0', false);
    date('f-t1', 't1', true);
    num('f-rmax', 'rmax');
    num('f-lat0', 'lat0');
    num('f-lon0', 'lon0');
    const rIncomplete = [f.rmax, f.lat0, f.lon0].some((v) => v !== null) && [f.rmax, f.lat0, f.lon0].some((v) => v === null);
    $('f-info').textContent = rIncomplete ? 'Per il filtro di distanza servono km, lat e lon.' : '';
    CS.applyFilters();
  }

  function resetFilters() {
    for (const id of ['f-text', 'f-t0', 'f-t1', 'f-rmax', 'f-lat0', 'f-lon0']) { $(id).value = ''; $(id).classList.remove('bad'); }
    for (const id of ['f-net', 'f-band', 'f-cls', 'f-state', 'f-pres']) $(id).value = '';
    readFilters();
  }

  /* --------------------------------------------------------- selection */

  function updateSelInfo() {
    const n = CS.sel.size;
    let hidden = 0;
    for (const k of CS.sel) if (!CS.shownKeys.has(k)) hidden++;
    $('sel-info').innerHTML = n ? n + (n === 1 ? ' stazione selezionata' : ' stazioni selezionate') +
      (hidden ? ' <span class="hid">(' + hidden + ' nascoste dai filtri)</span>' : '') : 'Nessuna stazione selezionata';
    $('sel-zoom').disabled = !n;
    updateOpButtons();
  }

  async function pasteList(text, source) {
    const r = await CS.dlg.stationList(text, source);
    if (!r) return;
    const p = CS.parseList(r.text);
    CS.select(p.keys, r.mode);
    CS.toast(p.keys.length + ' stazioni ' + {replace: 'selezionate', add: 'aggiunte', remove: 'tolte'}[r.mode] +
      (p.missing.length ? ' · non trovati: ' + p.missing.slice(0, 10).join(', ') + (p.missing.length > 10 ? ' …' : '') : ''),
    p.missing.length ? 'warn' : 'ok');
  }

  async function listFromFile() {
    let path = null;
    try {
      const r = await CS.api('dialog_open', {kind: 'list'});
      if (r.available) {
        if (!r.files.length) return;
        path = r.files[0];
      }
    } catch (e) { CS.error(e); return; }
    if (!path) {
      path = await CS.dlg.prompt('Lista da file', 'Percorso del file (relativo al progetto o a META_DATA)', 'BLACKLIST/');
      if (!path) return;
    }
    try {
      const r = await CS.api('read_list', {path});
      await pasteList(r.text, r.path);
    } catch (e) { CS.error(e); }
  }

  /* -------------------------------------------------------- operations */

  async function doCopy(move) {
    const src = $('op-src').value, dst = $('op-dst').value;
    const keys = selectedIn(src);
    if (!keys.length) return;
    await runOp('copy', {src, dst, keys, move});
  }

  async function doDelete() {
    const c = CS.catById.get($('op-src').value);
    if (!c) return;
    const keys = selectedIn(c.id);
    if (!keys.length) { CS.toast('Nessuna delle stazioni selezionate è in ' + c.letter, 'info'); return; }
    const ok = await CS.dlg.confirm('Elimina da ' + CS.esc(c.letter),
      '<p>Eliminare ' + keys.length + ' stazioni da <b>' + CS.esc(c.letter + ' · ' + c.name) + '</b>?</p><p class="small">' +
      CS.esc(keys.slice(0, 40).join(', ') + (keys.length > 40 ? ' …' : '')) + '</p>' +
      '<p class="muted">Il file non cambia finché non salvi; puoi annullare con ⌘Z.</p>', 'Elimina', true);
    if (ok) await runOp('delete', {id: c.id, keys});
  }

  async function doNewFromSelection() {
    if (!CS.sel.size) return;
    const writable = CS.cats.filter((c) => !c.readonly);
    if (!writable.length) { CS.toast('Nessun catalogo StationXML aperto', 'error'); return; }
    const srcOpts = '<option value="__all">tutti i cataloghi visibili (in ordine)</option>' +
      writable.map(opt).join('');
    const html = '<label class="field"><span>Nome</span><input type="text" id="ns-name" value="stations_selezione"></label>' +
      '<label class="field"><span>Prendi le stazioni da</span><select id="ns-src">' + srcOpts + '</select></label>' +
      '<p class="muted small">' + CS.sel.size + ' stazioni selezionate. Se una stazione è in più cataloghi con contenuto ' +
      'diverso, ti verrà chiesto quale versione usare.</p>';
    let body = null;
    const v = await CS.dlg.modal({title: 'Nuovo catalogo dalla selezione', html,
      buttons: [{label: 'Annulla', value: null}, {label: 'Crea', value: true, primary: true}],
      check: (_, b) => { body = {name: b.querySelector('#ns-name').value.trim(), src: b.querySelector('#ns-src').value}; return !!body.name; },
    });
    if (!v) return;
    const sources = body.src === '__all' ? CS.visibleCats().filter((c) => !c.readonly).map((c) => c.id) : [body.src];
    if (!sources.length) { CS.toast('Nessun catalogo StationXML visibile', 'error'); return; }
    await runOp('new_from', {keys: [...CS.sel], sources, name: body.name});
  }

  async function doSetOp() {
    const a = CS.catById.get($('set-a').value), b = CS.catById.get($('set-b').value);
    const op = $('set-op').value;
    if (!a || !b || a === b) return;
    const word = {union: 'unione', inter: 'intersezione', diff: 'differenza', sym: 'solo_in_uno'}[op];
    const name = await CS.dlg.prompt('Nuovo catalogo: ' + CS.esc(CS.config.setops[op] + ' di ' + a.letter + ' e ' + b.letter),
      'Nome', 'stations_' + word + '_' + a.letter + '_' + b.letter);
    if (name) await runOp('setop', {op, a: a.id, b: b.id, name});
  }

  /* --------------------------------------------------- splitter, keys */

  function initSplitter() {
    const bottom = $('bottom');
    bottom.style.height = CS.clamp(CS.settings.bottomH || 300, 80, window.innerHeight - 200) + 'px';
    let y0 = 0, h0 = 0;
    const move = (e) => {
      bottom.style.height = CS.clamp(h0 + (y0 - e.clientY), 60, window.innerHeight - 160) + 'px';
      CS.map.map.invalidateSize();
    };
    const up = () => {
      document.body.classList.remove('resizing');
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      CS.settings.bottomH = bottom.offsetHeight;
      CS.saveSettings();
    };
    $('splitter').addEventListener('mousedown', (e) => {
      y0 = e.clientY;
      h0 = bottom.offsetHeight;
      document.body.classList.add('resizing');
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
      e.preventDefault();
    });
  }

  function onKey(e) {
    if (document.querySelector('.modal-wrap')) return;
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();

    if (mod && k === 'z' && !typing) { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && k === 'y' && !typing) { e.preventDefault(); redo(); return; }
    if (mod && k === 'a' && !typing) { e.preventDefault(); CS.select(CS.shown.map((r) => r.key), 'replace'); return; }
    if (e.key === 'Escape') {
      if (typing) { e.target.blur(); return; }
      closeMenu();
      if (CS.map.mode) { if (CS.map.mode === 'measure') CS.map.clearMeasure(); CS.map.cancel(); return; }
      if (document.getElementById('measure-box').style.display === 'block') { CS.map.clearMeasure(); return; }
      if (CS.sel.size) CS.select([], 'replace');
      return;
    }
    if (e.key === 'Enter' && CS.map.mode && !typing) { e.preventDefault(); CS.map.enter(e); return; }
    if (typing || mod || e.altKey) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); if (CS.sel.size) doDelete(); return; }
    const act = {
      r: () => CS.map.toggle('rect'), l: () => CS.map.toggle('lasso'), c: () => CS.map.toggle('circle'),
      d: () => CS.map.toggle('measure'), f: () => CS.map.fitShown(),
      z: () => CS.sel.size && CS.map.fitKeys([...CS.sel]),
      i: () => CS.sel.size === 1 && showDetail([...CS.sel][0]),
      o: () => openFiles(), '?': () => CS.dlg.help(),
    }[e.key === '?' ? '?' : k];
    if (act) { e.preventDefault(); act(); }
  }

  function showDetail(key) { return CS.dlg.detail(key); }

  /* -------------------------------------------------------------- init */

  function init() {
    $('btn-open').onclick = () => openFiles();
    $('btn-open2').onclick = () => openFiles();
    $('btn-new').onclick = newCatalog;
    $('btn-undo').onclick = undo;
    $('btn-redo').onclick = redo;
    $('btn-rect').onclick = () => CS.map.toggle('rect');
    $('btn-lasso').onclick = () => CS.map.toggle('lasso');
    $('btn-circle').onclick = () => CS.map.toggle('circle');
    $('btn-measure').onclick = () => CS.map.toggle('measure');
    $('btn-fit').onclick = () => CS.map.fitShown();
    $('btn-help').onclick = () => CS.dlg.help();
    $('btn-detail').onclick = () => { if (CS.sel.size === 1) showDetail([...CS.sel][0]); };

    $('opt-color').value = CS.settings.color;
    $('opt-color').onchange = () => { CS.settings.color = $('opt-color').value; CS.saveSettings(); CS.map.render(); };
    $('opt-labels').checked = !!CS.settings.labels;
    $('opt-labels').onchange = () => { CS.settings.labels = $('opt-labels').checked; CS.saveSettings(); CS.map.render(); };

    // catalogue cards (delegated)
    $('cat-list').addEventListener('click', (e) => {
      const card = e.target.closest('.cat');
      if (!card) return;
      const c = CS.catById.get(card.dataset.id);
      if (e.target.classList.contains('vis')) { CS.setHidden(c.id, !e.target.checked); return; }
      if (e.target.closest('.menu-btn')) {
        e.stopPropagation();
        const r = e.target.getBoundingClientRect();
        menuFor(c, r.left, r.bottom + 2);
      }
    });
    $('cat-list').addEventListener('dblclick', (e) => {
      const card = e.target.closest('.cat');
      if (card && e.target.classList.contains('cname')) CS.dlg.catInfo(CS.catById.get(card.dataset.id));
    });
    $('cat-list').addEventListener('contextmenu', (e) => {
      const card = e.target.closest('.cat');
      if (!card) return;
      e.preventDefault();
      menuFor(CS.catById.get(card.dataset.id), e.clientX, e.clientY);
    });
    document.addEventListener('mousedown', (e) => { if (!e.target.closest('#menu')) closeMenu(); });

    // selection
    $('sel-all').onclick = () => CS.select(CS.shown.map((r) => r.key), 'replace');
    $('sel-none').onclick = () => CS.select([], 'replace');
    $('sel-invert').onclick = () => CS.select(CS.shown.map((r) => r.key).filter((k) => !CS.sel.has(k))
      .concat([...CS.sel].filter((k) => !CS.shownKeys.has(k))), 'replace');
    $('sel-paste').onclick = () => pasteList('', null);
    $('sel-file').onclick = listFromFile;
    $('sel-zoom').onclick = () => CS.map.fitKeys([...CS.sel]);

    // operations
    $('op-src').onchange = updateOpButtons;
    $('op-dst').onchange = updateOpButtons;
    $('op-copy').onclick = () => doCopy(false);
    $('op-move').onclick = () => doCopy(true);
    $('op-delete').onclick = doDelete;
    $('op-newsel').onclick = doNewFromSelection;
    for (const id of ['set-a', 'set-b', 'set-op']) $(id).onchange = updateSetHint;
    $('set-run').onclick = doSetOp;

    // filters
    const deb = CS.debounce(readFilters, 200);
    for (const id of ['f-text', 'f-t0', 'f-t1', 'f-rmax', 'f-lat0', 'f-lon0']) $(id).addEventListener('input', deb);
    for (const id of ['f-net', 'f-band', 'f-cls', 'f-state', 'f-pres']) $(id).addEventListener('change', readFilters);
    $('f-reset').onclick = resetFilters;

    CS.on('state', renderCats);
    CS.on('sel', updateSelInfo);

    initSplitter();
    window.addEventListener('resize', CS.debounce(() => CS.map.map.invalidateSize(), 100));
    // the catalogues live in the server: reloading the page loses nothing
    document.addEventListener('keydown', onKey);
  }

  return {init, openFiles, showDetail, runOp};
})();
