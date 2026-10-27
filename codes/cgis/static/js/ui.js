/* cgis - user interface: toolbar, side panel (layers, style, filters),
 * legend, tabs, splitter, dialogs and figure export. */
'use strict';

CG.ui = (function () {
  const $ = (id) => document.getElementById(id);

  /* ============================================================ modals */

  let modalClose = null;

  function modal(o) {
    closeModal();
    const root = $('modal-root');
    const wrap = document.createElement('div');
    wrap.className = 'modal-wrap';
    wrap.innerHTML = '<div class="modal' + (o.wide ? ' wide' : '') + '"><div class="modal-head">' + CG.esc(o.title) +
      '<button class="x" title="Chiudi (Esc)">×</button></div><div class="modal-body"></div><div class="modal-foot"></div></div>';
    const body = wrap.querySelector('.modal-body');
    if (typeof o.body === 'string') body.innerHTML = o.body; else if (o.body) body.appendChild(o.body);
    const foot = wrap.querySelector('.modal-foot');
    const close = () => {
      if (!wrap.parentNode) return;
      wrap.remove();
      if (modalClose === close) modalClose = null;
      if (o.onClose) o.onClose();
    };
    for (const b of (o.buttons || [])) {
      const btn = document.createElement('button');
      btn.textContent = b.label;
      if (b.primary) btn.className = 'primary';
      btn.onclick = async () => {
        if (b.fn) {
          const r = await b.fn(close, body);
          if (r === false) return;
        }
        close();
      };
      foot.appendChild(btn);
    }
    wrap.querySelector('.x').onclick = close;
    wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });
    root.appendChild(wrap);
    modalClose = close;
    if (o.onOpen) o.onOpen(body, close);
    const first = body.querySelector('input[type=text], select');
    if (first && o.focus !== false) first.focus();
    return close;
  }

  function closeModal() {
    if (modalClose) { modalClose(); return true; }
    return false;
  }

  function prompt(title, value, fn) {
    modal({
      title, body: '<input type="text" class="wide" id="prompt-in" value="' + CG.esc(value || '') + '">',
      buttons: [{label: 'Annulla'}, {label: 'OK', primary: true, fn: (close, body) => fn(body.querySelector('#prompt-in').value)}],
      onOpen: (body, close) => {
        const inp = body.querySelector('#prompt-in');
        inp.select();
        inp.onkeydown = (e) => { if (e.key === 'Enter') { fn(inp.value); close(); } };
      },
    });
  }

  function confirm(msg, fn) {
    modal({title: 'Conferma', body: '<p>' + CG.esc(msg) + '</p>', focus: false,
      buttons: [{label: 'Annulla'}, {label: 'OK', primary: true, fn: () => fn()}]});
  }

  /* ===================================================== file loading */

  /* Load a catalogue. Text tables whose columns are not recognised open
   * the column dialog; ``opts.replace`` reloads an existing layer in place
   * (e.g. with new columns). */
  async function loadCatalog(path, options, opts) {
    opts = opts || {};
    const style = Object.assign({}, options || {});
    let mapping = style.mapping || null;
    delete style.mapping;
    const label = path.split('/').pop();
    let p = null;
    for (;;) {
      const done = CG.busy('Caricamento ' + label + '…');
      let err = null;
      p = null;
      try {
        p = await CG.api('catalog_load', {path, mapping});
      } catch (e) {
        err = e;
      } finally {
        done();
      }
      if (err) {
        if (mapping && opts.lastPreview) {
          // the columns chosen in the dialog did not work: let the user fix them
          CG.error(err, 'colonne');
          mapping = await columnDialog(path, mapping, opts.lastPreview);
          if (!mapping) return null;
          continue;
        }
        CG.error(err, 'catalogo');
        return null;
      }
      if (p.needs_mapping) {
        opts.lastPreview = p.preview;
        mapping = await columnDialog(path, p.guess, p.preview);
        if (!mapping) return null;
        continue;
      }
      break;
    }

    const old = opts.replace || null;
    if (!old && CG.cats.some((L) => L.path === p.path)) {
      CG.api('catalog_remove', {id: p.id}).catch(() => {});
      if (!opts.quiet) CG.toast('Catalogo già caricato: ' + p.name, 'info');
      return null;
    }
    const L = CG.makeCatalogLayer(p, old ? old.style : style);
    L.mapping = p.mapping || null;
    const first = CG.cats.length === 0 && CG.stas.length === 0;
    if (old && CG.cats.includes(old)) {
      CG.cats.splice(CG.cats.indexOf(old), 1, L);
      CG.api('catalog_remove', {id: old.id}).catch(() => {});
      if (CG.hover && CG.hover.L === old) CG.hover = null;
    } else {
      CG.cats.push(L);
    }
    renderLayers();
    CG.invalidate('data');
    if (first && opts.fit !== false) CG.mapLayer.fitTo([L]);
    CG.sections.projectLayer(L);
    CG.session.changed();
    if (!opts.quiet) {
      const parts = [p.n + ' eventi'];
      parts.push(p.has_mag ? 'magnitudo ✓' : 'senza magnitudo');
      if (p.has_mt) parts.push(p.mt.idx.length + ' tensori momento');
      if (p.n_skipped) parts.push(p.n_skipped + ' righe scartate (senza tempo/coordinate)');
      const actions = L.mapping ? [{label: 'Colonne…', fn: () => editColumns(L)}] : [];
      CG.toast(p.name + ': ' + parts.join(' · '), 'ok', L.mapping ? 9000 : 5000, actions);
    }
    return L;
  }

  /* --------------------------------------------------- column dialog */

  const TIME_KINDS = [
    ['column', 'una colonna (data e ora, secondi epoch o anno decimale)'],
    ['ymd', 'colonne anno, mese, giorno, ora, minuti, secondi'],
    ['name', 'dal nome dell\'evento (…_AAAA_MM_GG_hh_mm_ss)'],
    ['none', 'nessun tempo (stessa data per tutti)'],
  ];
  const MT_KINDS = [
    ['none', 'nessuno'],
    ['sdr', 'strike, dip, rake'],
    ['ned', '6 componenti NED: mnn mee mdd mne mnd med'],
    ['use', '6 componenti USE/GMT: mrr mtt mff mrt mrf mtf (= m1…m6)'],
  ];
  const MT_LABELS = {sdr: ['strike', 'dip', 'rake'], ned: ['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
    use: ['mrr', 'mtt', 'mff', 'mrt', 'mrf', 'mtf']};

  /* Ask which column is what. Resolves to a mapping, or null. */
  function columnDialog(path, guess, preview) {
    return new Promise((resolve) => {
      let mp = JSON.parse(JSON.stringify(guess));
      if (mp.mt && mp.mt.kind === 'gmt') mp.mt.kind = 'use';
      let pv = preview;
      let answered = false;
      const body = document.createElement('div');
      body.className = 'coldlg';

      const colOptions = (sel, optional) => {
        const first = pv.rows[0] || [];
        return (optional ? '<option value="">—</option>' : '<option value="">(scegli)</option>') +
          pv.names.map((n, i) => {
            const v = (first[i] || '').slice(0, 22);
            return '<option value="' + i + '"' + (sel === i ? ' selected' : '') + '>' +
              CG.esc(n + (v ? '  ·  ' + v : '')) + '</option>';
          }).join('');
      };
      const sel = (id, value, optional) => '<select id="' + id + '">' + colOptions(value, optional) + '</select>';
      const opt = (list, value) => list.map(([v, l]) => '<option value="' + v + '"' + (v === value ? ' selected' : '') +
        '>' + CG.esc(l) + '</option>').join('');

      const draw = () => {
        const t = mp.time || {kind: 'column', cols: [null, null]};
        const tc = t.cols || [];
        let timeHTML = '';
        if (t.kind === 'column') {
          timeHTML = '<label class="form-row"><span>Data / ora</span>' + sel('cd-t0', tc[0], false) + '</label>' +
            '<label class="form-row"><span>Ora (se separata)</span>' + sel('cd-t1', tc[1] === undefined ? null : tc[1], true) + '</label>';
        } else if (t.kind === 'ymd') {
          timeHTML = ['anno', 'mese', 'giorno', 'ora', 'minuti', 'secondi'].map((l, k) =>
            '<label class="form-row"><span>' + l + '</span>' + sel('cd-y' + k, tc[k] === undefined ? null : tc[k], k >= 3) + '</label>').join('');
        }
        const m = mp.mt || {kind: 'none', cols: []};
        const mtHTML = m.kind === 'none' ? '' : MT_LABELS[m.kind].map((l, k) =>
          '<label class="form-row"><span>' + l + '</span>' + sel('cd-m' + k, (m.cols || [])[k], false) + '</label>').join('');
        const table = '<div class="cd-preview"><table><tr>' + pv.names.map((n) => '<th>' + CG.esc(n) + '</th>').join('') +
          '</tr>' + pv.rows.map((r) => '<tr>' + r.map((c) => '<td>' + CG.esc(c) + '</td>').join('') + '</tr>').join('') +
          '</table></div>';
        body.innerHTML =
          '<p class="muted small">' + CG.esc(path.split('/').pop()) + ' · ' + pv.n_rows + ' righe. ' +
          'Indica il significato delle colonne (le scelte vengono salvate nella sessione).</p>' +
          '<div class="row"><label>Separatore</label><select id="cd-delim">' +
          opt(Object.entries(pv.delimiters), pv.delimiter) + '</select>' +
          '<label class="chk"><input type="checkbox" id="cd-header"' + (pv.header ? ' checked' : '') +
          '> la prima riga è l\'intestazione</label></div>' + table +
          '<div class="form">' +
          '<div class="form-sep">Tempo</div>' +
          '<label class="form-row" style="grid-column: 1 / -1"><span>Tempo da</span><select id="cd-tkind">' +
          opt(TIME_KINDS, t.kind) + '</select></label>' + timeHTML +
          '<div class="form-sep">Posizione</div>' +
          '<label class="form-row"><span>Latitudine</span>' + sel('cd-lat', mp.lat, false) + '</label>' +
          '<label class="form-row"><span>Longitudine</span>' + sel('cd-lon', mp.lon, false) + '</label>' +
          '<label class="form-row"><span>Profondità</span>' + sel('cd-dep', mp.depth, true) + '</label>' +
          '<label class="form-row"><span>Unità</span><select id="cd-dunit">' +
          opt([['km', 'km'], ['m', 'metri']], mp.depth_unit) + '</select></label>' +
          '<label class="form-row" style="grid-column: 1 / -1"><span>Verso</span><select id="cd-dsign">' +
          opt([['down', 'profondità positiva verso il basso'], ['up', 'quota: valori negativi sotto il livello del mare']],
            mp.depth_sign) + '</select></label>' +
          '<div class="form-sep">Evento</div>' +
          '<label class="form-row"><span>Magnitudo</span>' + sel('cd-mag', mp.mag, true) + '</label>' +
          '<label class="form-row"><span>Tipo magnitudo</span>' + sel('cd-mtype', mp.magtype_col, true) + '</label>' +
          '<label class="form-row"><span>Nome / ID</span>' + sel('cd-name', mp.name, true) + '</label>' +
          '<label class="form-row"><span>Tipo fisso</span><input type="text" id="cd-mtfix" value="' +
          CG.esc(mp.mag_type || '') + '" placeholder="es. ML"></label>' +
          '<div class="form-sep">Meccanismo focale</div>' +
          '<label class="form-row" style="grid-column: 1 / -1"><span>Tensore</span><select id="cd-mtkind">' +
          opt(MT_KINDS, m.kind) + '</select></label>' + mtHTML +
          '</div>';

        const num = (id) => {
          const el = body.querySelector('#' + id);
          return el && el.value !== '' ? parseInt(el.value, 10) : null;
        };
        const read = () => {
          const tk = body.querySelector('#cd-tkind').value;
          let cols = [];
          if (tk === 'column') cols = [num('cd-t0'), num('cd-t1')];
          else if (tk === 'ymd') cols = [0, 1, 2, 3, 4, 5].map((k) => num('cd-y' + k));
          const mk = body.querySelector('#cd-mtkind').value;
          const mcols = mk === 'none' ? [] : MT_LABELS[mk].map((_, k) => num('cd-m' + k));
          mp = Object.assign(mp, {
            time: {kind: tk, cols},
            lat: num('cd-lat'), lon: num('cd-lon'), depth: num('cd-dep'),
            depth_unit: body.querySelector('#cd-dunit').value,
            depth_sign: body.querySelector('#cd-dsign').value,
            mag: num('cd-mag'), magtype_col: num('cd-mtype'), name: num('cd-name'),
            mag_type: body.querySelector('#cd-mtfix').value.trim() || null,
            mt: {kind: mk, cols: mcols},
          });
        };
        body._read = read;
        body.querySelector('#cd-tkind').onchange = () => {
          read();
          const k = body.querySelector('#cd-tkind').value;
          mp.time = {kind: k, cols: k === 'ymd' ? [null, null, null, null, null, null] : [null, null]};
          draw();
        };
        body.querySelector('#cd-mtkind').onchange = () => { read(); draw(); };
        const reinspect = async () => {
          read();
          try {
            const r = await CG.api('catalog_inspect', {path, delimiter: body.querySelector('#cd-delim').value,
              header: body.querySelector('#cd-header').checked});
            pv = r.preview;
            mp = r.guess;
            if (mp.mt && mp.mt.kind === 'gmt') mp.mt.kind = 'use';
            draw();
          } catch (e) { CG.error(e, 'colonne'); }
        };
        body.querySelector('#cd-delim').onchange = reinspect;
        body.querySelector('#cd-header').onchange = reinspect;
      };
      draw();
      modal({
        title: 'Colonne del catalogo', body, wide: true, focus: false,
        buttons: [{label: 'Annulla'}, {label: 'Carica', primary: true, fn: () => {
          body._read();
          const t = mp.time;
          if (mp.lat === null || mp.lon === null) { CG.toast('Scegli latitudine e longitudine', 'error'); return false; }
          if (t.kind === 'column' && t.cols[0] === null) { CG.toast('Scegli la colonna del tempo', 'error'); return false; }
          if (t.kind === 'ymd' && t.cols.slice(0, 3).some((c) => c === null)) { CG.toast('Scegli anno, mese e giorno', 'error'); return false; }
          if (t.kind === 'name' && mp.name === null) { CG.toast('Per il tempo dal nome scegli la colonna del nome', 'error'); return false; }
          if (mp.mt.kind !== 'none' && mp.mt.cols.some((c) => c === null)) { CG.toast('Scegli tutte le colonne del tensore', 'error'); return false; }
          mp.delimiter = pv.delimiter;
          mp.header = pv.header;
          answered = true;
          resolve(mp);
          return true;
        }}],
        onClose: () => { if (!answered) resolve(null); },
      });
    });
  }

  /* Change the columns of a text catalogue already loaded. */
  async function editColumns(L) {
    if (!L.mapping || !CG.cats.includes(L)) return;
    let r;
    try {
      r = await CG.api('catalog_inspect', {path: L.path, delimiter: L.mapping.delimiter, header: L.mapping.header});
    } catch (e) { CG.error(e, 'colonne'); return; }
    const mp = await columnDialog(L.path, L.mapping, r.preview);
    if (!mp) return;
    await loadCatalog(L.path, {mapping: mp}, {replace: L, fit: false, lastPreview: r.preview});
  }

  async function loadStations(path, options, opts) {
    opts = opts || {};
    const done = CG.busy('Caricamento ' + path.split('/').pop() + '…');
    try {
      const p = await CG.api('stations_load', {path});
      if (CG.stas.some((L) => L.path === p.path)) {
        CG.api('stations_remove', {id: p.id}).catch(() => {});
        if (!opts.quiet) CG.toast('Stazioni già caricate: ' + p.name, 'info');
        return null;
      }
      const L = CG.makeStationLayer(p, options);
      const first = CG.cats.length === 0 && CG.stas.length === 0;
      CG.stas.push(L);
      CG.mapLayer.renderStations();
      renderLayers();
      updateLegend();
      if (first && opts.fit !== false) CG.mapLayer.fitTo([L]);
      CG.sections.projectLayer(L);
      CG.session.changed();
      if (!opts.quiet) CG.toast(p.name + ': ' + p.n + ' stazioni', 'ok');
      return L;
    } catch (e) {
      CG.error(e, 'stazioni');
      return null;
    } finally {
      done();
    }
  }

  function removeLayer(L) {
    if (L.kind === 'catalog') {
      CG.cats.splice(CG.cats.indexOf(L), 1);
      CG.api('catalog_remove', {id: L.id}).catch(() => {});
      if (CG.hover && CG.hover.L === L) CG.hover = null;
      CG.invalidate('data');
    } else {
      CG.stas.splice(CG.stas.indexOf(L), 1);
      CG.api('stations_remove', {id: L.id}).catch(() => {});
      CG.mapLayer.renderStations();
      updateLegend();
      CG.sections.render();
    }
    renderLayers();
    CG.session.changed();
  }

  function addFileDialog(kind) {
    const isCat = kind === 'catalog';
    const body = document.createElement('div');
    body.innerHTML =
      '<div class="row">' + (CG.config.dialogs !== 'none' ? '<button id="af-browse" class="primary">Sfoglia…</button>' : '') +
      '<input type="text" id="af-path" class="wide" placeholder="percorso del file (relativo alla cartella del progetto o assoluto)">' +
      '<button id="af-load">Carica</button></div>' +
      '<div class="row"><input type="text" id="af-filter" class="wide" placeholder="filtra i file in ' +
      (isCat ? 'CAT/' : 'META_DATA/') + '…"></div><div id="af-list" class="file-list"><span class="muted">caricamento elenco…</span></div>';
    const close = modal({title: isCat ? 'Aggiungi catalogo' : 'Aggiungi stazioni', body, wide: true, buttons: [{label: 'Chiudi'}]});
    const load = (p) => {
      if (!p) return;
      close();
      (isCat ? loadCatalog : loadStations)(p);
    };
    const browse = body.querySelector('#af-browse');
    if (browse) {
      browse.onclick = async () => {
        try {
          const r = await CG.api('dialog_open', {kind});
          if (!r.available) { CG.toast('Finestra di dialogo non disponibile: scrivi il percorso', 'info'); return; }
          if (!r.paths.length) return;
          close();
          for (const p of r.paths) await (isCat ? loadCatalog : loadStations)(p);
        } catch (e) { CG.error(e); }
      };
    }
    const pathIn = body.querySelector('#af-path');
    body.querySelector('#af-load').onclick = () => load(pathIn.value.trim());
    pathIn.onkeydown = (e) => { if (e.key === 'Enter') load(pathIn.value.trim()); };
    CG.api('files_list', {kind}).then((r) => {
      const list = body.querySelector('#af-list');
      const loaded = new Set((isCat ? CG.cats : CG.stas).map((L) => L.path));
      const draw = () => {
        const q = body.querySelector('#af-filter').value.toLowerCase();
        const files = r.files.filter((f) => f.toLowerCase().includes(q));
        list.innerHTML = files.length ? files.slice(0, 500).map((f) =>
          '<div class="file' + (loaded.has(f) ? ' loaded' : '') + '" data-p="' + CG.esc(f) + '">' + CG.esc(f) +
          (loaded.has(f) ? ' <span class="muted">(caricato)</span>' : '') + '</div>').join('')
          : '<span class="muted">nessun file</span>';
        list.querySelectorAll('.file').forEach((d) => { d.onclick = () => load(d.dataset.p); });
      };
      body.querySelector('#af-filter').oninput = draw;
      draw();
    }).catch((e) => { body.querySelector('#af-list').textContent = e.message; });
  }

  /* ======================================================= layer list */

  function swatch(L) {
    if (L.kind === 'stations') return '<span class="swatch tri"></span>';
    if (L.style.color) return '<span class="swatch" style="background:' + L.style.color + '"></span>';
    return '<span class="swatch grad"></span>';
  }

  function renderLayers() {
    const box = $('layer-list');
    const all = CG.cats.concat(CG.stas);
    if (!all.length) {
      box.innerHTML = '<div class="empty">Nessun dato caricato.<br>Usa ＋ Catalogo / ＋ Stazioni.</div>';
      return;
    }
    box.innerHTML = '';
    for (const L of all) {
      const row = document.createElement('div');
      row.className = 'layer';
      const info = L.kind === 'catalog'
        ? L.n + ' ev. · ' + (L.hasMag ? 'M' : 'no M') + (L.hasMT ? ' · ' + L.mt.idx.length + ' MT' : '')
        : L.n + ' stazioni';
      row.innerHTML =
        '<div class="layer-head"><input type="checkbox" class="vis"' + (L.style.visible ? ' checked' : '') + ' title="Mostra/nascondi">' +
        swatch(L) + '<span class="lname" title="' + CG.esc(L.path) + '">' + CG.esc(L.name) + '</span>' +
        '<span class="linfo">' + info + '</span>' +
        '<button class="icon opt" title="Opzioni">⚙</button>' +
        '<button class="icon zoom" title="Zoom sul layer">⌖</button>' +
        (L.kind === 'catalog' ? '<button class="icon up" title="Sposta sopra">↑</button>' : '') +
        '<button class="icon del" title="Rimuovi">✕</button></div>' +
        '<div class="layer-opts" style="display:none"></div>';
      const opts = row.querySelector('.layer-opts');
      row.querySelector('.vis').onchange = (e) => {
        L.style.visible = e.target.checked;
        if (L.kind === 'catalog') CG.invalidate('data');
        else { CG.mapLayer.renderStations(); updateLegend(); CG.sections.render(); }
        CG.session.changed();
      };
      row.querySelector('.opt').onclick = () => {
        const open = opts.style.display === 'none';
        opts.style.display = open ? 'block' : 'none';
        if (open) fillLayerOptions(L, opts);
      };
      row.querySelector('.zoom').onclick = () => CG.mapLayer.fitTo([L]);
      const up = row.querySelector('.up');
      if (up) up.onclick = () => {
        // "above" = drawn later = later in the list
        const k = CG.cats.indexOf(L);
        if (k < CG.cats.length - 1) {
          CG.cats.splice(k, 1); CG.cats.splice(k + 1, 0, L);
          renderLayers(); CG.invalidate('draw'); CG.plots.update(); CG.session.changed();
        }
      };
      row.querySelector('.del').onclick = () => confirm('Rimuovere ' + L.name + '?', () => removeLayer(L));
      box.appendChild(row);
    }
  }

  function fillLayerOptions(L, el) {
    if (L.kind === 'stations') {
      el.innerHTML = '<label class="chk"><input type="checkbox" class="lab"' + (L.style.labels ? ' checked' : '') +
        '> etichette</label><div class="muted small">' + CG.esc(L.path) + '</div>';
      el.querySelector('.lab').onchange = (e) => {
        L.style.labels = e.target.checked;
        CG.mapLayer.renderStations();
        CG.session.changed();
      };
      return;
    }
    const s = L.style;
    el.innerHTML =
      '<div class="row"><label>Colore</label><select class="cmode"><option value="auto">profondità / tempo</option>' +
      '<option value="fixed">fisso</option></select><input type="color" class="ccol" value="' + (s.color || '#808080') + '"></div>' +
      '<div class="row"><label>Opacità</label><input type="range" class="op" min="0.05" max="1" step="0.05" value="' +
      (s.opacity === null ? CG.settings.opacity : s.opacity) + '"><label class="chk"><input type="checkbox" class="opg"' +
      (s.opacity === null ? ' checked' : '') + '> globale</label></div>' +
      '<div class="row"><label>Dimensione ×</label><input type="range" class="sz" min="0.2" max="3" step="0.1" value="' + s.sizeScale +
      '"><span class="val">' + s.sizeScale + '</span></div>' +
      (L.hasMT ? '<div class="row"><label class="chk"><input type="checkbox" class="bb"' + (s.beachballs ? ' checked' : '') +
        '> beachball</label></div>' : '') +
      '<div class="row"><label class="chk"><input type="checkbox" class="pl"' + (s.plots ? ' checked' : '') +
      '> nei grafici e nelle sezioni</label></div>' +
      '<div class="row"><button class="small exp">esporta eventi visibili…</button>' +
      (L.mapping ? '<button class="small cols">colonne…</button>' : '') + '</div>' +
      '<div class="muted small">' + CG.esc(L.path) + (L.nSkipped ? '<br>' + L.nSkipped + ' eventi scartati' : '') + '</div>';
    const cm = el.querySelector('.cmode'), cc = el.querySelector('.ccol');
    cm.value = s.color ? 'fixed' : 'auto';
    cc.style.visibility = s.color ? 'visible' : 'hidden';
    const setColor = () => {
      s.color = cm.value === 'fixed' ? cc.value : null;
      cc.style.visibility = s.color ? 'visible' : 'hidden';
      renderLayersKeepOpen(L);
      CG.invalidate('style');
    };
    cm.onchange = setColor;
    cc.oninput = CG.debounce(setColor, 80);
    const op = el.querySelector('.op'), opg = el.querySelector('.opg');
    op.oninput = () => { s.opacity = +op.value; opg.checked = false; CG.invalidate('style'); };
    opg.onchange = () => { s.opacity = opg.checked ? null : +op.value; CG.invalidate('style'); };
    const sz = el.querySelector('.sz');
    sz.oninput = () => { s.sizeScale = +sz.value; el.querySelector('.val').textContent = s.sizeScale; CG.invalidate('style'); };
    const bb = el.querySelector('.bb');
    if (bb) bb.onchange = () => { s.beachballs = bb.checked; CG.invalidate('style'); };
    el.querySelector('.pl').onchange = (e) => { s.plots = e.target.checked; CG.invalidate('style'); };
    const colsBtn = el.querySelector('.cols');
    if (colsBtn) colsBtn.onclick = () => editColumns(L);
    el.querySelector('.exp').onclick = () => {
      exportEvents([{id: L.id, indices: CG.visibleIndices(L)}], L.name.replace(/\.[^.]+$/, '') + '_sel');
    };
  }

  function renderLayersKeepOpen(L) {
    // refresh only the swatch of a layer
    const rows = $('layer-list').querySelectorAll('.layer');
    const all = CG.cats.concat(CG.stas);
    const k = all.indexOf(L);
    if (k >= 0 && rows[k]) {
      const sw = rows[k].querySelector('.swatch');
      if (sw) sw.outerHTML = swatch(L);
    }
  }

  /* ===================================================== style panel */

  function cmapKey() { return CG.settings.colorBy === 'time' ? 'cmapTime' : 'cmapDepth'; }
  function revKey() { return CG.settings.colorBy === 'time' ? 'revTime' : 'revDepth'; }
  function rangeKey() { return CG.settings.colorBy === 'time' ? 'rangeTime' : 'rangeDepth'; }

  /* set an input value unless the user is editing it */
  function setVal(id, v) {
    const el = $(id);
    if (el && document.activeElement !== el) el.value = v;
  }

  function syncStyle() {
    const st = CG.settings;
    const sel = $('st-cmap');
    if (!sel.options.length) {
      sel.innerHTML = Object.keys(CG.config.cmaps).map((k) => '<option value="' + k + '">' +
        CG.esc(k.replace(/_/g, ' ')) + '</option>').join('');
    }
    sel.value = st[cmapKey()];
    $('st-rev').checked = st[revKey()];
    const rng = st[rangeKey()];
    const isTime = st.colorBy === 'time';
    const auto = CG.cats.length ? CG.colorRange() : null;
    const fmt = (v) => (v === null ? '' : (isTime ? CG.fmtDate(v) : String(+v.toFixed(3))));
    setVal('st-vmin', fmt(rng[0]));
    setVal('st-vmax', fmt(rng[1]));
    $('st-vmin').placeholder = auto ? (isTime ? CG.fmtDate(auto.autoMin) : auto.autoMin.toFixed(2)) : 'auto';
    $('st-vmax').placeholder = auto ? (isTime ? CG.fmtDate(auto.autoMax) : auto.autoMax.toFixed(2)) : 'auto';
    const sz = st.size;
    $('st-size').value = sz.base; $('st-size-v').textContent = sz.base;
    $('st-growth').value = sz.growth; $('st-growth-v').textContent = sz.growth;
    setVal('st-mref', sz.ref);
    setVal('st-nomag', sz.nomag);
    $('st-opacity').value = st.opacity; $('st-opacity-v').textContent = st.opacity;
    $('st-bbtype').value = st.bbType;
    $('st-bb').checked = st.bbShow;
    $('st-bbscale').value = st.bbScale; $('st-bbscale-v').textContent = st.bbScale;
    $('st-outside').value = st.outside;
    $('st-attr').value = st.attr;
    setVal('st-tagkey', st.tagKey);
    $('row-tagkey').style.display = st.attr === 'tag' ? '' : 'none';
    document.querySelectorAll('#seg-color button').forEach((b) => b.classList.toggle('on', b.dataset.v === st.colorBy));
  }

  function setColorBy(v) {
    CG.settings.colorBy = v;
    syncStyle();
    CG.invalidate('style');
  }

  function bindStyle() {
    const st = () => CG.settings;
    document.querySelectorAll('#seg-color button').forEach((b) => { b.onclick = () => setColorBy(b.dataset.v); });
    $('st-cmap').onchange = (e) => { st()[cmapKey()] = e.target.value; CG.invalidate('style'); };
    $('st-rev').onchange = (e) => { st()[revKey()] = e.target.checked; CG.invalidate('style'); };
    const rangeIn = () => {
      const isTime = st().colorBy === 'time';
      const parse = (s) => {
        s = s.trim();
        if (s === '') return null;
        return isTime ? CG.parseTime(s) : CG.parseNum(s);
      };
      const a = parse($('st-vmin').value), b = parse($('st-vmax').value);
      if (Number.isNaN(a) || Number.isNaN(b)) { CG.toast(isTime ? 'Data non valida (AAAA-MM-GG)' : 'Valore non valido', 'error'); syncStyle(); return; }
      if (a !== null && b !== null && !(b > a)) { CG.toast('La scala deve avere max > min', 'error'); syncStyle(); return; }
      st()[rangeKey()] = [a, b];
      CG.invalidate('style');
    };
    $('st-vmin').onchange = rangeIn;
    $('st-vmax').onchange = rangeIn;
    $('st-auto').onclick = () => { st()[rangeKey()] = [null, null]; syncStyle(); CG.invalidate('style'); };
    const slider = (id, set) => {
      $(id).oninput = (e) => { set(+e.target.value); $(id + '-v').textContent = e.target.value; CG.invalidate('style'); };
    };
    slider('st-size', (v) => { st().size.base = v; });
    slider('st-growth', (v) => { st().size.growth = v; });
    slider('st-opacity', (v) => { st().opacity = v; });
    slider('st-bbscale', (v) => { st().bbScale = v; });
    const numIn = (id, set) => {
      $(id).onchange = (e) => {
        const v = CG.parseNum(e.target.value);
        if (v === null || Number.isNaN(v)) { CG.toast('Valore non valido', 'error'); syncStyle(); return; }
        set(v); CG.invalidate('style');
      };
    };
    numIn('st-mref', (v) => { st().size.ref = v; });
    numIn('st-nomag', (v) => { st().size.nomag = CG.clamp(v, 0.5, 60); });
    $('st-bbtype').onchange = (e) => { st().bbType = e.target.value; CG.invalidate('style'); };
    $('st-bb').onchange = (e) => { st().bbShow = e.target.checked; CG.invalidate('style'); };
    $('st-outside').onchange = (e) => { st().outside = e.target.value; CG.invalidate('style'); };
    $('st-attr').onchange = (e) => {
      st().attr = e.target.value;
      $('row-tagkey').style.display = st().attr === 'tag' ? '' : 'none';
      if (st().attr === 'tag' && !st().tagKey) suggestTagKey();
      CG.invalidate('style');
    };
    $('st-tagkey').onchange = (e) => { st().tagKey = e.target.value.trim(); CG.invalidate('style'); };
  }

  function suggestTagKey() {
    const counts = new Map();
    for (const L of CG.cats) {
      if (!L.tagMap) continue;
      for (const m of L.tagMap) if (m) for (const k of Object.keys(m)) counts.set(k, (counts.get(k) || 0) + 1);
    }
    let best = '', n = 0;
    for (const [k, c] of counts) if (c > n) { best = k; n = c; }
    if (best) { CG.settings.tagKey = best; $('st-tagkey').value = best; }
  }

  /* ========================================================= filters */

  function syncFilters() {
    const f = CG.settings.filters;
    const v = (x) => (x === null ? '' : x);
    $('f-magmin').value = v(f.magMin); $('f-magmax').value = v(f.magMax);
    $('f-depmin').value = v(f.depMin); $('f-depmax').value = v(f.depMax);
    $('f-nomag').checked = f.includeNoMag;
    updateLassoInfo();
  }

  function bindFilters() {
    const f = () => CG.settings.filters;
    const pair = (a, b, ka, kb) => {
      const h = () => {
        const x = CG.parseNum($(a).value), y = CG.parseNum($(b).value);
        if (Number.isNaN(x) || Number.isNaN(y)) { CG.toast('Valore non valido', 'error'); syncFilters(); return; }
        if (x !== null && y !== null && x > y) { CG.toast('min deve essere ≤ max', 'error'); syncFilters(); return; }
        f()[ka] = x; f()[kb] = y;
        CG.invalidate('filter');
      };
      $(a).onchange = h; $(b).onchange = h;
    };
    pair('f-magmin', 'f-magmax', 'magMin', 'magMax');
    pair('f-depmin', 'f-depmax', 'depMin', 'depMax');
    $('f-nomag').onchange = (e) => { f().includeNoMag = e.target.checked; CG.invalidate('filter'); };
    $('f-lasso-clear').onclick = () => {
      CG.settings.lasso = null;
      CG.tools.drawLasso();
      updateLassoInfo();
      CG.invalidate('filter');
    };
    $('f-reset').onclick = () => {
      CG.settings.filters = CG.defaults().filters;
      CG.settings.lasso = null;
      CG.tools.drawLasso();
      syncFilters();
      CG.invalidate('filter');
    };
    $('f-export').onclick = () => {
      const items = CG.cats.filter((L) => L.style.visible).map((L) => ({id: L.id, indices: CG.visibleIndices(L)}))
        .filter((it) => it.indices.length);
      exportEvents(items, 'cgis_eventi_visibili');
    };
  }

  function updateLassoInfo() {
    const ls = CG.settings.lasso;
    $('f-lasso-info').textContent = ls && ls.length >= 3 ? 'Lazo attivo (' + ls.length + ' vertici)' : 'Lazo: nessuno (L)';
    $('f-lasso-clear').disabled = !(ls && ls.length >= 3);
  }

  function updateCounts() {
    const c = CG.counts || {nvis: 0, nbase: 0, ntot: 0};
    $('counts').textContent = c.ntot ? 'Visibili ' + c.nvis + ' · dopo i filtri ' + c.nbase + ' · totali ' + c.ntot : '';
    $('tb-count').textContent = c.ntot ? c.nvis + ' / ' + c.ntot + ' eventi' : '';
  }

  /* ========================================================== legend */

  function updateLegend() {
    const box = $('legend');
    const cs = CG.colorState;
    const parts = [];
    const anyAuto = CG.cats.some((L) => L.style.visible && !L.style.color);
    if (anyAuto && cs.lut) {
      if (cs.categories) {
        parts.push('<div class="leg-title">' + CG.esc(cs.label) + '</div>' + cs.categories.slice(0, 15).map((c) =>
          '<div class="leg-item"><span class="dot" style="background:' + c.color + '"></span>' + CG.esc(c.label) + '</div>').join('') +
          (cs.categories.length > 15 ? '<div class="muted">… ' + (cs.categories.length - 15) + ' altri</div>' : '') +
          '<div class="leg-item"><span class="dot" style="background:' + CG.colors.NAN_HEX + '"></span>altri / senza dato</div>');
      } else {
        parts.push(CG.colors.colorbarHTML('leg-cbar', cs.label));
      }
    }
    // magnitude sizes
    let mmin = Infinity, mmax = -Infinity;
    for (const L of CG.cats) {
      if (!L.style.visible) continue;
      for (let i = 0; i < L.n; i++) {
        const m = L.mag[i];
        if (m < mmin) mmin = m;
        if (m > mmax) mmax = m;
      }
    }
    if (Number.isFinite(mmin)) {
      const lo = Math.ceil(mmin), hi = Math.floor(mmax);
      let mags = [];
      for (let m = lo; m <= hi; m++) mags.push(m);
      if (!mags.length) mags = [Math.round((mmin + mmax) * 5) / 10];
      const step = Math.ceil(mags.length / 4);
      mags = mags.reverse().filter((_, k) => k % step === 0).reverse();
      const rs = mags.map((m) => CG.radius(m));
      const H = Math.max(...rs) * 2 + 4;
      let x = 4;
      const items = mags.map((m, k) => {
        const r = rs[k];
        const cx = x + r;
        x += 2 * r + 22;
        return '<circle cx="' + cx + '" cy="' + (H / 2) + '" r="' + r + '" fill="#ccc" stroke="#333" stroke-width="0.7"/>' +
          '<text x="' + (cx + r + 3) + '" y="' + (H / 2 + 4) + '" font-size="11">' + m + '</text>';
      }).join('');
      parts.push('<div class="leg-title">Magnitudo</div><svg width="' + Math.min(x, 260) + '" height="' + H + '">' + items + '</svg>');
    }
    // station classes
    const classes = new Map();
    for (const L of CG.stas) {
      if (!L.style.visible) continue;
      for (const s of L.stations) if (!classes.has(s.cls)) classes.set(s.cls, [L.classLabels[s.cls], L.classColors[s.cls]]);
    }
    if (classes.size) {
      parts.push('<div class="leg-title">Stazioni</div>' + Array.from(classes.values()).map(([lab, col]) =>
        '<div class="leg-item"><svg width="14" height="12"><polygon points="7,1 13,11 1,11" fill="' + col +
        '" stroke="#000"/></svg>' + CG.esc(lab) + '</div>').join(''));
    }
    box.innerHTML = parts.join('');
    box.style.display = parts.length ? 'block' : 'none';
    const cv = $('leg-cbar');
    if (cv) {
      const range = cs.attrRange || [cs.vmin, cs.vmax];
      CG.colors.paintColorbar(cv, cs.lut, range[0], range[1], cs.isTime && !cs.attrRange);
    }
    syncStyle();
  }

  /* ===================================================== tabs, layout */

  function showTab(tab) {
    CG.settings.tab = tab;
    document.querySelectorAll('#tabs button[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('on', p.dataset.pane === tab));
    if (CG.settings.panelCollapsed) setCollapsed(false);
    if (tab === 'sec') CG.sections.showTab();
    else CG.plots.showTab(tab);
    CG.session.changed();
  }

  function applyPanelHeight() {
    const b = $('bottom');
    const h = CG.settings.panelCollapsed ? null : CG.clamp(CG.settings.panelHeight, 140, window.innerHeight - 160);
    b.style.height = h === null ? '' : h + 'px';
    b.classList.toggle('collapsed', !!CG.settings.panelCollapsed);
    $('btn-panel-toggle').textContent = CG.settings.panelCollapsed ? '▴' : '▾';
    if (CG.mapLayer.map) CG.mapLayer.map.invalidateSize({pan: false});
    resizePlots();
  }

  const resizePlots = CG.debounce(() => {
    if (CG.settings.tab === 'sec') CG.sections.resize(); else CG.plots.resize();
  }, 60);

  function setCollapsed(c) {
    CG.settings.panelCollapsed = c;
    applyPanelHeight();
    if (!c) {
      if (CG.settings.tab === 'sec') CG.sections.showTab(); else CG.plots.update();
    }
  }

  function initSplitter() {
    const sp = $('splitter');
    let drag = null;
    sp.addEventListener('pointerdown', (e) => {
      drag = {y: e.clientY, h: $('bottom').offsetHeight};
      sp.setPointerCapture(e.pointerId);
      document.body.classList.add('resizing');
      e.preventDefault();
    });
    sp.addEventListener('pointermove', (e) => {
      if (!drag) return;
      CG.settings.panelCollapsed = false;
      CG.settings.panelHeight = drag.h - (e.clientY - drag.y);
      applyPanelHeight();
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      document.body.classList.remove('resizing');
      CG.session.changed();
    };
    sp.addEventListener('pointerup', end);
    sp.addEventListener('pointercancel', end);
  }

  function setSidebar(open) {
    CG.settings.sidebar = open;
    $('sidebar').classList.toggle('closed', !open);
    $('sidebar-toggle').textContent = open ? '◀' : '▶';
    setTimeout(() => { CG.mapLayer.map.invalidateSize({pan: false}); resizePlots(); }, 220);
  }

  /* ===================================================== save dialogs */

  /* Ask for an output path: native dialog, or a typed path. */
  async function askSavePath(format, name, title) {
    const r = await CG.api('dialog_save', {format, name, title});
    if (r.available) return r.path;          // null when cancelled
    return new Promise((resolve) => {
      const def = CG.config.dirs.plots + '/' + name.replace(/\.[^.]+$/, '') + '.' + format;
      let answered = false;
      modal({
        title: title || 'Salva', body: '<p>Percorso del file:</p><input type="text" id="sp-path" class="wide" value="' + CG.esc(def) + '">',
        buttons: [{label: 'Annulla'}, {label: 'Salva', primary: true, fn: (close, body) => {
          answered = true;
          let p = body.querySelector('#sp-path').value.trim();
          if (p && !p.toLowerCase().endsWith('.' + format)) p += '.' + format;
          resolve(p || null);
        }}],
        onClose: () => { if (!answered) resolve(null); },
      });
    });
  }

  function savedToast(path) {
    CG.toast('Salvato: ' + path, 'ok', 10000, [{label: 'Mostra', fn: () => CG.api('reveal', {path}).catch((e) => CG.error(e))}]);
  }

  async function exportEvents(items, name) {
    items = items.filter((it) => it.indices && it.indices.length);
    if (!items.length) { CG.toast('Nessun evento da esportare', 'info'); return; }
    try {
      const r0 = await CG.api('dialog_save', {format: 'pf', name: name + '.pf', title: 'Salva eventi',
        dir: CG.config.dirs.cat});
      let path = r0.path;
      if (!r0.available) {
        path = await new Promise((resolve) => {
          let ok = false;
          modal({title: 'Salva eventi', body: '<input type="text" id="ev-path" class="wide" value="' +
            CG.esc(CG.config.dirs.cat + '/' + name + '.pf') + '">',
          buttons: [{label: 'Annulla'}, {label: 'Salva', primary: true, fn: (c, b) => { ok = true; resolve(b.querySelector('#ev-path').value.trim()); }}],
          onClose: () => { if (!ok) resolve(null); }});
        });
      }
      if (!path) return;
      const done = CG.busy('Scrittura eventi…');
      try {
        const r = await CG.api('catalog_export', {path, items});
        CG.toast(r.n + ' eventi salvati in ' + r.path, 'ok', 10000,
          [{label: 'Carica', fn: () => loadCatalog(r.path)}, {label: 'Mostra', fn: () => CG.api('reveal', {path: r.path})}]);
      } finally { done(); }
    } catch (e) { CG.error(e, 'esportazione eventi'); }
  }

  /* ---- request pieces shared by the figure exports ---- */

  function exportStyle(symbolScale) {
    const st = CG.settings;
    const cs = CG.colorState;
    const isTime = st.colorBy === 'time';
    const out = {
      color_by: st.colorBy,
      cmap: isTime ? st.cmapTime : st.cmapDepth,
      reverse: isTime ? st.revTime : st.revDepth,
      vmin: cs.vmin, vmax: cs.vmax,
      size: st.size,
      bb_type: st.bbType,
      bb_scale: st.bbScale,
      symbol_scale: symbolScale || 1,
    };
    if (st.attr) {
      out.attr = {mode: st.attr, label: cs.label, categories: cs.categories,
        range: cs.attrRange};
    }
    return out;
  }

  function exportLayers(opts) {
    const st = CG.settings;
    const greyOutside = st.outside === 'grey' && CG.timeWindow() !== null;
    const out = [];
    for (const L of CG.cats) {
      if (!L.style.visible || (opts.plotsOnly && !L.style.plots)) continue;
      const idx = [], grey = [], colors = [];
      for (let i = 0; i < L.n; i++) {
        if (L.vis[i]) { idx.push(i); if (st.attr && !L.style.color) colors.push(CG.colors.cssToHex(L.colors[i])); }
        else if (greyOutside && L.base[i]) grey.push(i);
      }
      const o = {id: L.id, name: L.name, indices: idx, grey, color: L.style.color, opacity: CG.layerOpacity(L),
        size_scale: L.style.sizeScale, beachballs: opts.beachballs !== false && st.bbShow && L.style.beachballs};
      if (st.attr && !L.style.color) o.colors = colors;
      out.push(o);
    }
    return out;
  }

  function formHTML(fields) {
    return '<div class="form">' + fields.map((f) => {
      if (f.type === 'sep') return '<div class="form-sep">' + CG.esc(f.label) + '</div>';
      let inp;
      if (f.type === 'select') {
        inp = '<select id="' + f.id + '">' + f.options.map(([v, l]) => '<option value="' + v + '"' +
          (String(v) === String(f.value) ? ' selected' : '') + '>' + CG.esc(l) + '</option>').join('') + '</select>';
      } else if (f.type === 'check') {
        return '<label class="chk form-chk"><input type="checkbox" id="' + f.id + '"' + (f.value ? ' checked' : '') + '> ' +
          CG.esc(f.label) + '</label>';
      } else if (f.type === 'color') {
        inp = '<input type="color" id="' + f.id + '" value="' + f.value + '">';
      } else {
        inp = '<input type="text" id="' + f.id + '" value="' + CG.esc(f.value === null || f.value === undefined ? '' : f.value) +
          '"' + (f.placeholder ? ' placeholder="' + CG.esc(f.placeholder) + '"' : '') + (f.cls ? ' class="' + f.cls + '"' : '') + '>';
      }
      return '<label class="form-row"><span>' + CG.esc(f.label) + '</span>' + inp + '</label>';
    }).join('') + '</div>';
  }

  function readForm(body, ids) {
    const out = {};
    for (const id of ids) {
      const el = body.querySelector('#' + id);
      if (!el) continue;
      out[id] = el.type === 'checkbox' ? el.checked : el.value;
    }
    return out;
  }

  async function runExport(kind, req, format, defName, title) {
    const path = await askSavePath(format, defName, title);
    if (!path) return false;
    req.path = path;
    const done = CG.busy('Creazione figura (PyGMT)…');
    try {
      const r = await CG.api('export_' + kind, req);
      savedToast(r.path);
      return true;
    } catch (e) {
      CG.error(e, 'export');
      return false;
    } finally { done(); }
  }

  /* ---------------------------------------------------- map export */

  let lastMapOpts = null;

  function openMapExport(bounds) {
    if (CG.tools.mode) CG.tools.cancel(false);
    const map = CG.mapLayer.map;
    const b = bounds || map.getBounds();
    const o = lastMapOpts || {};
    const anyMT = CG.cats.some((L) => L.style.visible && L.hasMT);
    const fields = [
      {type: 'sep', label: 'Area'},
      {id: 'ex-lonmin', label: 'Lon min', value: b.getWest().toFixed(4), cls: 'num'},
      {id: 'ex-lonmax', label: 'Lon max', value: b.getEast().toFixed(4), cls: 'num'},
      {id: 'ex-latmin', label: 'Lat min', value: b.getSouth().toFixed(4), cls: 'num'},
      {id: 'ex-latmax', label: 'Lat max', value: b.getNorth().toFixed(4), cls: 'num'},
      {type: 'sep', label: 'Figura'},
      {id: 'ex-format', label: 'Formato', type: 'select', value: o.format || 'pdf', options: [['pdf', 'PDF'], ['svg', 'SVG'], ['png', 'PNG (300 dpi)']]},
      {id: 'ex-width', label: 'Larghezza (cm)', value: o.width || 16, cls: 'num'},
      {id: 'ex-title', label: 'Titolo', value: o.title || ''},
      {id: 'ex-symbol', label: 'Scala simboli', value: o.symbol || 1, cls: 'num'},
      {type: 'sep', label: 'Sfondo'},
      {id: 'ex-topo', label: 'Topografia', type: 'select', value: o.topo || 'pyrocko', options: [
        ['pyrocko', 'pyrocko SRTM (~90 m, globale)'], ['gmt', 'GMT earth_relief (fino a 30 m)'], ['none', 'nessuna (solo costa)']]},
      {id: 'ex-palette', label: 'Palette', type: 'select', value: o.palette || 'gray', options: CG.config.topo_palettes.map((p) => [p, p])},
      {id: 'ex-water', label: 'Colore mare', type: 'color', value: o.water || '#a8b4bc'},
      {id: 'ex-bathy', label: 'Batimetria (ETOPO1 con pyrocko: grande download la prima volta)', type: 'check', value: !!o.bathy},
      {type: 'sep', label: 'Elementi'},
      {id: 'ex-sta', label: 'Stazioni', type: 'check', value: o.sta !== undefined ? o.sta : CG.stas.some((L) => L.style.visible)},
      {id: 'ex-stalab', label: 'Etichette stazioni', type: 'check', value: o.stalab !== undefined ? o.stalab : CG.stas.some((L) => L.style.labels)},
      {id: 'ex-bb', label: 'Beachball (' + CG.settings.bbType + ')', type: 'check', value: anyMT && CG.settings.bbShow},
      {id: 'ex-sec', label: 'Tracce delle sezioni', type: 'check', value: o.sec !== undefined ? o.sec : CG.sectionList.length > 0},
      {id: 'ex-cbar', label: 'Barra colori', type: 'check', value: o.cbar !== undefined ? o.cbar : true},
      {id: 'ex-mleg', label: 'Legenda magnitudo', type: 'check', value: o.mleg !== undefined ? o.mleg : true},
      {id: 'ex-sleg', label: 'Legenda stazioni', type: 'check', value: o.sleg !== undefined ? o.sleg : true},
      {id: 'ex-scale', label: 'Scala grafica', type: 'check', value: o.scale !== undefined ? o.scale : true},
    ];
    const body = document.createElement('div');
    body.innerHTML = '<div class="row"><button id="ex-rect">⬚ Seleziona area sulla mappa</button>' +
      '<button id="ex-view">Vista attuale</button></div>' + formHTML(fields) +
      '<p class="muted small">Eventi, colori, filtri e finestra temporale sono quelli attuali del visualizzatore.</p>';
    modal({
      title: 'Salva figura della mappa', body, wide: true,
      buttons: [{label: 'Annulla'}, {label: 'Salva…', primary: true, fn: async (close, body) => {
        const v = readForm(body, fields.map((f) => f.id).filter(Boolean));
        const num = (k) => CG.parseNum(v[k]);
        const region = [num('ex-lonmin'), num('ex-lonmax'), num('ex-latmin'), num('ex-latmax')];
        if (region.some((x) => x === null || Number.isNaN(x))) { CG.toast('Coordinate non valide', 'error'); return false; }
        if (!(region[1] > region[0] && region[3] > region[2])) { CG.toast('Serve lon max > lon min e lat max > lat min', 'error'); return false; }
        if (region[2] < -85 || region[3] > 85) { CG.toast('Latitudine fuori dai limiti (±85°)', 'error'); return false; }
        const width = num('ex-width');
        if (!(width >= 4 && width <= 60)) { CG.toast('Larghezza tra 4 e 60 cm', 'error'); return false; }
        const symbol = num('ex-symbol');
        if (!(symbol > 0)) { CG.toast('Scala simboli non valida', 'error'); return false; }
        lastMapOpts = {format: v['ex-format'], width, title: v['ex-title'], symbol, topo: v['ex-topo'], palette: v['ex-palette'],
          water: v['ex-water'], bathy: v['ex-bathy'], sta: v['ex-sta'], stalab: v['ex-stalab'], sec: v['ex-sec'],
          cbar: v['ex-cbar'], mleg: v['ex-mleg'], sleg: v['ex-sleg'], scale: v['ex-scale']};
        const req = {
          region,
          style: exportStyle(symbol),
          layers: exportLayers({beachballs: v['ex-bb']}),
          stations: v['ex-sta'] ? CG.stas.filter((L) => L.style.visible).map((L) => ({id: L.id, labels: v['ex-stalab']})) : [],
          sections: v['ex-sec'] ? CG.sectionList.map((S) => ({label: S.label, lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2, width_km: S.width})) : [],
          options: {width_cm: width, title: v['ex-title'], topo: v['ex-topo'], palette: v['ex-palette'], water: v['ex-water'],
            bathymetry: v['ex-bathy'], stations: v['ex-sta'], colorbar: v['ex-cbar'], mag_legend: v['ex-mleg'],
            station_legend: v['ex-sleg'], scalebar: v['ex-scale']},
        };
        close();
        await runExport('map', req, v['ex-format'], 'cgis_mappa_' + CG.stamp(), 'Salva figura');
        return true;
      }}],
      onOpen: (body, close) => {
        body.querySelector('#ex-rect').onclick = () => {
          close();
          CG.tools.setMode('rect', {done: (bb) => openMapExport(bb || b)});
        };
        body.querySelector('#ex-view').onclick = () => {
          const vb = map.getBounds();
          body.querySelector('#ex-lonmin').value = vb.getWest().toFixed(4);
          body.querySelector('#ex-lonmax').value = vb.getEast().toFixed(4);
          body.querySelector('#ex-latmin').value = vb.getSouth().toFixed(4);
          body.querySelector('#ex-latmax').value = vb.getNorth().toFixed(4);
        };
      },
    });
  }

  /* ------------------------------------------------ plot / section export */

  function openPlotExport() {
    const tab = CG.settings.tab;
    if (!CG.cats.length) { CG.toast('Nessun dato da salvare', 'info'); return; }
    if (tab === 'sec') return openSectionExport();
    if (tab === 'cum' || tab === 'fmd') return openPlotlyExport(tab);
    if (tab === 'pt') return openStereonetExport();
    return openTimeExport(tab);
  }

  function openSectionExport() {
    const S = CG.activeSection;
    if (!S) { CG.toast('Nessuna sezione attiva', 'info'); return; }
    const anyMT = CG.cats.some((L) => L.style.visible && L.hasMT);
    const fields = [
      {id: 'sx-format', label: 'Formato', type: 'select', value: 'pdf', options: [['pdf', 'PDF'], ['svg', 'SVG'], ['png', 'PNG (300 dpi)']]},
      {id: 'sx-width', label: 'Larghezza (cm)', value: 16, cls: 'num'},
      {id: 'sx-height', label: 'Altezza (cm)', value: 8, cls: 'num'},
      {id: 'sx-true', label: 'Scala reale (l\'altezza segue le distanze)', type: 'check', value: S.trueScale},
      {id: 'sx-zmin', label: 'Profondità min (km)', value: S.zmin, placeholder: 'auto', cls: 'num'},
      {id: 'sx-zmax', label: 'Profondità max (km)', value: S.zmax, placeholder: 'auto', cls: 'num'},
      {id: 'sx-title', label: 'Titolo', value: 'Sezione ' + S.label + '–' + S.label + '′'},
      {id: 'sx-symbol', label: 'Scala simboli', value: 1, cls: 'num'},
      {id: 'sx-topo', label: 'Profilo topografico (pyrocko SRTM)', type: 'check', value: S.showTopo},
      {id: 'sx-bb', label: 'Beachball', type: 'check', value: anyMT && S.showBB && CG.settings.bbShow},
      {id: 'sx-sta', label: 'Stazioni nel corridoio', type: 'check', value: S.showSta && CG.stas.length > 0},
      {id: 'sx-inset', label: 'Mappa con la traccia', type: 'check', value: true},
      {id: 'sx-cbar', label: 'Barra colori', type: 'check', value: true},
      {id: 'sx-mleg', label: 'Legenda magnitudo', type: 'check', value: true},
    ];
    modal({
      title: 'Salva sezione ' + S.label + '–' + S.label + '′', body: formHTML(fields), wide: true,
      buttons: [{label: 'Annulla'}, {label: 'Salva…', primary: true, fn: async (close, body) => {
        const v = readForm(body, fields.map((f) => f.id));
        const n = (k) => CG.parseNum(v[k]);
        const zmin = n('sx-zmin'), zmax = n('sx-zmax');
        if ([n('sx-width'), n('sx-height'), n('sx-symbol'), zmin, zmax].some((x) => Number.isNaN(x))) { CG.toast('Valore non valido', 'error'); return false; }
        if (zmin !== null && zmax !== null && !(zmax > zmin)) { CG.toast('Profondità: max > min', 'error'); return false; }
        const req = {
          section: {label: S.label, lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2, width_km: S.width},
          style: exportStyle(n('sx-symbol') || 1),
          layers: exportLayers({plotsOnly: true, beachballs: v['sx-bb']}),
          stations: v['sx-sta'] ? CG.stas.filter((L) => L.style.visible).map((L) => ({id: L.id, labels: true})) : [],
          options: {width_cm: n('sx-width') || 16, height_cm: n('sx-height') || 8, true_scale: v['sx-true'],
            depth_min: zmin, depth_max: zmax, title: v['sx-title'], topo: v['sx-topo'], beachballs: v['sx-bb'],
            stations: v['sx-sta'], inset: v['sx-inset'], colorbar: v['sx-cbar'], mag_legend: v['sx-mleg']},
        };
        close();
        await runExport('section', req, v['sx-format'], 'cgis_sezione_' + S.label + '_' + CG.stamp(), 'Salva sezione');
        return true;
      }}],
    });
  }

  function openTimeExport(tab) {
    const div = document.getElementById('plot-' + tab);
    const ykind = tab === 'td' ? 'depth' : 'mag';
    let t0 = null, t1 = null, y0 = null, y1 = null;
    try {
      const xa = div._fullLayout.xaxis, ya = div._fullLayout.yaxis;
      t0 = CG.plotlyToTime(xa.range[0]); t1 = CG.plotlyToTime(xa.range[1]);
      y0 = Math.min(ya.range[0], ya.range[1]); y1 = Math.max(ya.range[0], ya.range[1]);
    } catch (e) { /* not drawn: automatic ranges */ }
    const fields = [
      {id: 'tx-format', label: 'Formato', type: 'select', value: 'pdf', options: [['pdf', 'PDF'], ['svg', 'SVG'], ['png', 'PNG (300 dpi)']]},
      {id: 'tx-width', label: 'Larghezza (cm)', value: 18, cls: 'num'},
      {id: 'tx-height', label: 'Altezza (cm)', value: 7, cls: 'num'},
      {id: 'tx-t0', label: 'Da (UTC)', value: Number.isFinite(t0) ? CG.fmtTime(t0, false) : '', placeholder: 'auto'},
      {id: 'tx-t1', label: 'A (UTC)', value: Number.isFinite(t1) ? CG.fmtTime(t1, false) : '', placeholder: 'auto'},
      {id: 'tx-y0', label: ykind === 'depth' ? 'Profondità min' : 'Magnitudo min', value: Number.isFinite(y0) ? +y0.toFixed(3) : '', placeholder: 'auto', cls: 'num'},
      {id: 'tx-y1', label: ykind === 'depth' ? 'Profondità max' : 'Magnitudo max', value: Number.isFinite(y1) ? +y1.toFixed(3) : '', placeholder: 'auto', cls: 'num'},
      {id: 'tx-title', label: 'Titolo', value: ''},
      {id: 'tx-symbol', label: 'Scala simboli', value: 1, cls: 'num'},
      {id: 'tx-win', label: 'Evidenzia finestra temporale', type: 'check', value: CG.timeWindow() !== null},
      {id: 'tx-cbar', label: 'Barra colori', type: 'check', value: true},
    ];
    modal({
      title: 'Salva grafico ' + (tab === 'td' ? 'tempo–profondità' : 'tempo–magnitudo'), body: formHTML(fields), wide: true,
      buttons: [{label: 'Annulla'}, {label: 'Salva…', primary: true, fn: async (close, body) => {
        const v = readForm(body, fields.map((f) => f.id));
        const tt = (k) => (v[k].trim() === '' ? null : CG.parseTime(v[k]));
        const n = (k) => CG.parseNum(v[k]);
        const a = tt('tx-t0'), b = tt('tx-t1');
        if (Number.isNaN(a) || Number.isNaN(b)) { CG.toast('Data non valida', 'error'); return false; }
        const ya = n('tx-y0'), yb = n('tx-y1');
        if (Number.isNaN(ya) || Number.isNaN(yb)) { CG.toast('Valore non valido', 'error'); return false; }
        const tmw = CG.settings.time;
        const win = v['tx-win'] && CG.timeWindow() ? [tmw.mode === 'cumulative' ? CG.timebar.domain[0] : tmw.t0, tmw.t1] : null;
        const layers = exportLayers({plotsOnly: true, beachballs: false})
          .filter((o) => !CG.cats.find((x) => x.id === o.id).noTime);
        // in time plots all filtered events are shown, out-of-window ones in grey
        for (const o of layers) {
          if (CG.timeWindow() === null) continue;
          const L = CG.cats.find((x) => x.id === o.id);
          o.grey = [];
          for (let i = 0; i < L.n; i++) if (L.base[i] && !L.vis[i]) o.grey.push(i);
        }
        const req = {style: exportStyle(n('tx-symbol') || 1), layers,
          options: {y: ykind, width_cm: n('tx-width') || 18, height_cm: n('tx-height') || 7, t0: a, t1: b, y0: ya, y1: yb,
            title: v['tx-title'], window: win, colorbar: v['tx-cbar']}};
        close();
        await runExport('timeplot', req, v['tx-format'], 'cgis_' + (tab === 'td' ? 'tempo_profondita_' : 'tempo_magnitudo_') + CG.stamp(), 'Salva grafico');
        return true;
      }}],
    });
  }

  function openStereonetExport() {
    const o = CG.settings.pt;
    const fields = [
      {id: 'px-format', label: 'Formato', type: 'select', value: 'pdf', options: [['pdf', 'PDF'], ['svg', 'SVG'], ['png', 'PNG (300 dpi)']]},
      {id: 'px-width', label: 'Larghezza (cm)', value: 10, cls: 'num'},
      {id: 'px-title', label: 'Titolo', value: ''},
      {id: 'px-net', label: 'Reticolo', type: 'check', value: true},
    ];
    modal({
      title: 'Salva stereonet assi P/T', body: formHTML(fields) +
        '<p class="muted small">Assi, colori e asse medio come nel pannello (le curve di densità non sono esportate).</p>',
      buttons: [{label: 'Annulla'}, {label: 'Salva…', primary: true, fn: async (close, body) => {
        const v = readForm(body, fields.map((f) => f.id));
        const axes = ['p', 't', 'b'].filter((a) => o[a]);
        if (!axes.length) { CG.toast('Seleziona almeno un asse', 'error'); return false; }
        const req = {style: exportStyle(1), layers: exportLayers({plotsOnly: true, beachballs: false}),
          options: {axes, color_mode: o.color, mean: o.mean, width_cm: CG.parseNum(v['px-width']) || 10,
            title: v['px-title'], net: v['px-net']}};
        close();
        await runExport('stereonet', req, v['px-format'], 'cgis_assi_PT_' + CG.stamp(), 'Salva stereonet');
        return true;
      }}],
    });
  }

  function openPlotlyExport(tab) {
    const fields = [
      {id: 'qx-format', label: 'Formato', type: 'select', value: 'svg', options: [['svg', 'SVG (vettoriale)'], ['png', 'PNG']]},
      {id: 'qx-w', label: 'Larghezza (px)', value: 1000, cls: 'num'},
      {id: 'qx-h', label: 'Altezza (px)', value: 500, cls: 'num'},
    ];
    modal({
      title: 'Salva grafico', body: formHTML(fields),
      buttons: [{label: 'Annulla'}, {label: 'Salva…', primary: true, fn: async (close, body) => {
        const v = readForm(body, fields.map((f) => f.id));
        const w = CG.clamp(CG.parseNum(v['qx-w']) || 1000, 200, 6000);
        const h = CG.clamp(CG.parseNum(v['qx-h']) || 500, 150, 6000);
        close();
        const fmt = v['qx-format'];
        const path = await askSavePath(fmt, 'cgis_' + (tab === 'cum' ? 'cumulativo_' : 'gutenberg_richter_') + CG.stamp(), 'Salva grafico');
        if (!path) return true;
        const done = CG.busy('Esportazione…');
        try {
          const content = await CG.plots.toImage(tab, fmt, w, h);
          const r = await CG.api('export_raw', {path, content});
          savedToast(r.path);
        } catch (e) { CG.error(e, 'export'); } finally { done(); }
        return true;
      }}],
    });
  }

  /* ============================================================ help */

  function showHelp() {
    modal({title: 'cgis – aiuto', wide: true, focus: false, buttons: [{label: 'Chiudi', primary: true}], body:
      '<table class="help">' +
      '<tr><td><kbd>D</kbd></td><td>misura distanze (clic sui punti, doppio clic/Invio per finire, Esc per cancellare)</td></tr>' +
      '<tr><td><kbd>X</kbd></td><td>nuova sezione: clic su A e su B; gli estremi si trascinano, larghezza nel pannello Sezioni</td></tr>' +
      '<tr><td><kbd>[</kbd> <kbd>]</kbd></td><td>riduci / aumenta la larghezza della sezione attiva</td></tr>' +
      '<tr><td><kbd>L</kbd></td><td>selezione a lazo (filtra gli eventi nel poligono)</td></tr>' +
      '<tr><td><kbd>S</kbd></td><td>salva la figura della mappa (PDF/SVG/PNG, area da rettangolo o coordinate)</td></tr>' +
      '<tr><td><kbd>C</kbd></td><td>colore per profondità ↔ origin time</td></tr>' +
      '<tr><td><kbd>Spazio</kbd></td><td>play / pausa della finestra temporale</td></tr>' +
      '<tr><td><kbd>Esc</kbd></td><td>annulla lo strumento attivo / chiudi la finestra</td></tr>' +
      '<tr><td><kbd>?</kbd></td><td>questo aiuto</td></tr>' +
      '</table>' +
      '<p>Passa con il cursore su un evento per i dettagli (tutti i tag inclusi): l\'evento è evidenziato anche nei grafici e nella sezione. ' +
      'Clic su un evento per fissare il riquadro. Nel grafico tempo–profondità lo strumento <i>Box select</i> imposta finestra temporale e filtro.</p>' +
      '<p>Sessioni: salvate in <code>' + CG.esc(CG.config.dirs.sessions) + '</code>; l\'ultima è salvata automaticamente. ' +
      'Da terminale: <code>python3 cgis -res</code> (ultima) o <code>python3 cgis -res nome</code>.</p>' +
      '<p class="muted small">Tempi in UTC. Mappe di base: OpenStreetMap, Esri, OpenTopoMap, CARTO. Topografia delle figure: pyrocko (SRTMGL3/ETOPO1) o GMT earth_relief.</p>'});
  }

  /* ============================================================ init */

  function init() {
    $('btn-add-cat').onclick = () => addFileDialog('catalog');
    $('btn-add-sta').onclick = () => addFileDialog('stations');
    $('btn-save').onclick = () => openMapExport();
    $('btn-help').onclick = showHelp;
    $('btn-plot-export').onclick = openPlotExport;
    $('btn-panel-toggle').onclick = () => setCollapsed(!CG.settings.panelCollapsed);
    $('sidebar-toggle').onclick = () => setSidebar(!CG.settings.sidebar);
    document.querySelectorAll('#tabs button[data-tab]').forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });

    // session menu
    const menu = $('menu-session');
    $('btn-session').onclick = (e) => { e.stopPropagation(); menu.classList.toggle('open'); };
    document.addEventListener('click', () => menu.classList.remove('open'));
    menu.querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        menu.classList.remove('open');
        if (b.dataset.act === 'save') CG.session.saveDialog();
        else if (b.dataset.act === 'open') CG.session.openDialog();
        else if (b.dataset.act === 'new') confirm('Svuotare la sessione (i file non vengono toccati)?', () => CG.session.clear());
      };
    });

    // FMD and P/T controls
    const fmdIn = () => {
      const f = CG.settings.fmd;
      const bin = CG.parseNum($('fmd-bin').value), corr = CG.parseNum($('fmd-corr').value), mc = CG.parseNum($('fmd-mc').value);
      if (!(bin > 0) || Number.isNaN(corr) || Number.isNaN(mc)) { CG.toast('Valore non valido', 'error'); return; }
      f.bin = bin; f.corr = corr === null ? 0 : corr; f.mc = mc; f.mcMode = $('fmd-mcmode').value;
      CG.plots.update(); CG.session.changed();
    };
    for (const id of ['fmd-bin', 'fmd-corr', 'fmd-mc', 'fmd-mcmode']) $(id).onchange = fmdIn;
    const ptIn = () => {
      const o = CG.settings.pt;
      o.p = $('pt-p').checked; o.t = $('pt-t').checked; o.b = $('pt-b').checked;
      o.color = $('pt-color').value; o.mean = $('pt-mean').checked; o.density = $('pt-density').checked;
      CG.plots.update(); CG.session.changed();
    };
    for (const id of ['pt-p', 'pt-t', 'pt-b', 'pt-color', 'pt-mean', 'pt-density']) $(id).onchange = ptIn;

    bindStyle();
    bindFilters();
    initSplitter();
    window.addEventListener('resize', CG.debounce(() => applyPanelHeight(), 100));
  }

  function syncAll() {
    syncStyle();
    syncFilters();
    const f = CG.settings.fmd;
    $('fmd-bin').value = f.bin; $('fmd-corr').value = f.corr; $('fmd-mc').value = f.mc === null ? '' : f.mc;
    $('fmd-mcmode').value = f.mcMode;
    const o = CG.settings.pt;
    $('pt-p').checked = o.p; $('pt-t').checked = o.t; $('pt-b').checked = o.b;
    $('pt-color').value = o.color; $('pt-mean').checked = o.mean; $('pt-density').checked = o.density;
    document.querySelectorAll('#tabs button[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === CG.settings.tab));
    document.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('on', p.dataset.pane === CG.settings.tab));
    setSidebar(CG.settings.sidebar !== false);
    applyPanelHeight();
    CG.timebar.render();
  }

  return {
    init, syncAll, syncStyle, syncFilters, updateLegend, updateCounts, updateLassoInfo, renderLayers,
    loadCatalog, loadStations, removeLayer, showTab, setColorBy, openMapExport, exportEvents,
    modal, closeModal, modalOpen: () => !!modalClose, prompt, confirm, showHelp, askSavePath, savedToast,
  };
})();
