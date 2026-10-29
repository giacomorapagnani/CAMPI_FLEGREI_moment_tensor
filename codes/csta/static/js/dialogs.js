/* csta - modal dialogs: generic modal / confirm / prompt, file chooser,
 * output path, conflicts, station lists, station details, help. */
'use strict';

CS.dlg = (function () {
  /* Generic modal. ``buttons``: [{label, value, primary, danger}]; resolves
   * with the value of the clicked button (null on Esc / ×). ``check(value,
   * body)`` may return false to keep the modal open. */
  function modal({title, html, size, buttons, onOpen, check, footLeft}) {
    return new Promise((resolve) => {
      const wrap = document.createElement('div');
      wrap.className = 'modal-wrap';
      wrap.innerHTML = '<div class="modal ' + (size || '') + '"><div class="modal-head"><span>' + title +
        '</span><button class="x" title="Chiudi (Esc)">×</button></div><div class="modal-body"></div>' +
        '<div class="modal-foot">' + (footLeft || '') + '<span class="grow"></span></div></div>';
      const body = wrap.querySelector('.modal-body');
      if (typeof html === 'string') body.innerHTML = html; else if (html) body.appendChild(html);
      const foot = wrap.querySelector('.modal-foot');
      let primary = null;
      (buttons || [{label: 'Chiudi', value: true, primary: true}]).forEach((b) => {
        const el = document.createElement('button');
        el.textContent = b.label;
        if (b.primary) { el.className = b.danger ? 'danger solid' : 'primary'; primary = b; }
        else if (b.danger) el.className = 'danger';
        el.onclick = () => finish(b.value);
        foot.appendChild(el);
      });
      async function finish(value) {
        if (value !== null && check) {
          const ok = await check(value, body);
          if (ok === false) return;
        }
        document.removeEventListener('keydown', onKey, true);
        wrap.remove();
        resolve(value);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(null); }
        else if (e.key === 'Enter' && primary && e.target.tagName !== 'TEXTAREA') {
          e.preventDefault(); e.stopPropagation(); finish(primary.value);
        }
      }
      wrap.querySelector('.x').onclick = () => finish(null);
      wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) finish(null); });
      document.addEventListener('keydown', onKey, true);
      document.body.appendChild(wrap);
      CS.map.hideTip();
      if (onOpen) onOpen(body, finish);
      const first = body.querySelector('input[type=text], textarea');
      if (first) { first.focus(); if (first.select) first.select(); }
    });
  }

  function confirm(title, html, okLabel, danger) {
    return modal({title, html, buttons: [
      {label: 'Annulla', value: null},
      {label: okLabel || 'OK', value: true, primary: true, danger},
    ]}).then((v) => v === true);
  }

  function prompt(title, label, value) {
    const html = '<label class="field"><span>' + label + '</span><input type="text" id="dlg-in" value="' +
      CS.esc(value || '') + '"></label>';
    let out = null;
    return modal({title, html, buttons: [{label: 'Annulla', value: null}, {label: 'OK', value: true, primary: true}],
      check: (v, body) => { out = body.querySelector('#dlg-in').value.trim(); return !!out; },
    }).then((v) => (v ? out : null));
  }

  /* ------------------------------------------------------ open files */

  function fmtSize(n) {
    if (n === null || n === undefined) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' kB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function kindOf(f) {
    if (f.kind === 'dir') return ['dir', 'cartella · ' + f.n + ' xml'];
    const ext = f.path.split('.').pop().toLowerCase();
    if (ext === 'xml') return ['xml', 'StationXML'];
    if (ext === 'pf') return ['ro', 'pyrocko · sola lettura'];
    return ['ro', 'testo · sola lettura'];
  }

  async function openFiles() {
    let list;
    try {
      list = await CS.api('files');
    } catch (e) {
      CS.error(e, 'elenco dei file');
      return null;
    }
    const open = new Set(CS.cats.map((c) => c.path).filter(Boolean));
    const html = '<p class="muted">File in <code>' + CS.esc(list.base) + '</code>. Le cartelle con più ' +
      'StationXML si aprono come un unico catalogo. I file .pf e .txt non hanno risposte strumentali: si ' +
      'aprono in sola lettura (per confronti e selezioni).</p>' +
      '<div class="field inline"><input type="text" id="of-filter" placeholder="cerca, oppure scrivi nomi di file ' +
      'separati da spazi e premi Invio"></div>' +
      '<div class="file-list" id="of-list">' + (list.files.length ? list.files.map((f, i) => {
        const [kc, kl] = kindOf(f);
        const isOpen = open.has(f.path);
        const name = f.path.startsWith(list.base + '/') ? f.path.slice(list.base.length + 1) : f.path;
        return '<label class="' + (isOpen ? 'open' : '') + '" data-name="' + CS.esc(name.toLowerCase()) + '">' +
          '<input type="checkbox" data-i="' + i + '"' + (isOpen ? ' disabled' : '') + '>' +
          '<span class="fname" title="' + CS.esc(f.path) + '">' + CS.esc(name) + (f.kind === 'dir' ? '/' : '') + '</span>' +
          '<span class="kind ' + kc + '">' + kl + '</span><span class="fmeta">' +
          (isOpen ? 'già aperto' : fmtSize(f.size)) + '</span></label>';
      }).join('') : '<div class="empty" style="padding:10px">Nessun file in ' + CS.esc(list.base) + '</div>') + '</div>';
    const browse = CS.config.dialogs !== 'none' ? '<button id="of-browse">Sfoglia…</button>' : '';
    let chosen = [];
    const res = await modal({
      title: 'Apri file di stazioni', html, size: 'wide', footLeft: browse,
      buttons: [{label: 'Annulla', value: null}, {label: 'Apri', value: 'open', primary: true}],
      onOpen: (body, finish) => {
        const filter = body.querySelector('#of-filter');
        filter.addEventListener('input', () => {
          const q = filter.value.trim().toLowerCase();
          body.querySelectorAll('#of-list label').forEach((l) => {
            l.style.display = !q || q.split(/\s+/).some((w) => l.dataset.name.includes(w)) ? '' : 'none';
          });
        });
        const btn = document.getElementById('of-browse');
        if (btn) {
          btn.onclick = async () => {
            try {
              const r = await CS.api('dialog_open', {kind: 'stations'});
              if (r.files.length) { chosen = r.files; finish('browse'); }
            } catch (e) { CS.error(e); }
          };
        }
      },
      check: (v, body) => {
        if (v !== 'open') return true;
        const boxes = [...body.querySelectorAll('#of-list input:checked')];
        chosen = boxes.map((b) => list.files[+b.dataset.i].path);
        if (!chosen.length) {
          // typed names (looked up in META_DATA by the server)
          chosen = body.querySelector('#of-filter').value.split(/[\s,]+/).filter(Boolean);
        }
        if (!chosen.length) { CS.toast('Seleziona almeno un file', 'info', 2500); return false; }
        return true;
      },
    });
    return res ? chosen : null;
  }

  /* ----------------------------------------------------- output path */

  async function outputPath(title, defPath, kind, note) {
    const html = (note ? '<p>' + note + '</p>' : '') +
      '<label class="field"><span>File</span><span class="inline"><input type="text" id="op-path" value="' +
      CS.esc(defPath) + '">' + (CS.config.dialogs !== 'none' ? '<button id="op-browse">Sfoglia…</button>' : '') +
      '</span></label><p class="muted small">Percorso relativo alla cartella del progetto se inizia con una sua ' +
      'cartella (es. <code>META_DATA/…</code>, <code>BLACKLIST/…</code>), altrimenti il file va in ' +
      '<code>' + CS.esc(CS.config.dirs.meta_rel) + '</code>.</p>';
    let out = null;
    const v = await modal({
      title, html, buttons: [{label: 'Annulla', value: null}, {label: 'Salva', value: true, primary: true}],
      onOpen: (body) => {
        const b = body.querySelector('#op-browse');
        if (b) {
          b.onclick = async () => {
            try {
              const r = await CS.api('dialog_save', {kind, path: body.querySelector('#op-path').value});
              if (r.path) body.querySelector('#op-path').value = r.path;
            } catch (e) { CS.error(e); }
          };
        }
      },
      check: (_, body) => { out = body.querySelector('#op-path').value.trim(); return !!out; },
    });
    return v ? out : null;
  }

  /* -------------------------------------------------------- conflicts */

  function conflicts(list, labels) {
    const A = labels.a, B = labels.b;
    const items = list.map((c) => '<div class="conf-item"><b>' + CS.esc(c.key) + '</b>' +
      '<div class="ver">' + CS.esc(A.tag) + ': ' + CS.esc(c.a) + '</div><div class="ver">' + CS.esc(B.tag) + ': ' +
      CS.esc(c.b) + '</div><ul>' + c.diff.map((d) => '<li>' + CS.esc(d) + '</li>').join('') + '</ul></div>').join('');
    const html = '<p>' + list.length + (list.length === 1 ? ' stazione è' : ' stazioni sono') +
      ' in entrambi con contenuto diverso:</p><div class="conf-list">' + items + '</div>' +
      '<p style="margin-top:10px"><b>Quale versione usare?</b> (vale per tutte le stazioni elencate)</p>' +
      '<label class="choice"><input type="radio" name="pol" value="a" checked><span><b>' + CS.esc(A.tag) + '</b>: ' + CS.esc(A.choice) + '</span></label>' +
      '<label class="choice"><input type="radio" name="pol" value="b"><span><b>' + CS.esc(B.tag) + '</b>: ' + CS.esc(B.choice) + '</span></label>' +
      '<label class="choice"><input type="radio" name="pol" value="merge"><span><b>unisci le due versioni</b>: tutte le epoche di ' +
      'stazione e di canale; le epoche di canale uguali (stesso codice, location e inizio) contano una volta sola, con i ' +
      'metadati di ' + CS.esc(A.tag) + '</span></label>';
    let pol = null;
    return modal({title: 'Stazioni in conflitto', html, size: 'wide',
      buttons: [{label: 'Annulla', value: null}, {label: 'Procedi', value: true, primary: true}],
      check: (_, body) => { pol = body.querySelector('input[name=pol]:checked').value; return true; },
    }).then((v) => (v ? pol : null));
  }

  /* ----------------------------------------------------- station list */

  async function stationList(text, source) {
    const html = (source ? '<p class="muted">Da <code>' + CS.esc(source) + '</code></p>' : '') +
      '<p>Codici <code>NET.STA</code>, <code>NET.STA.LOC.CHA</code> o solo <code>STA</code> (tutte le reti), ' +
      'separati da spazi, virgole o righe; il testo dopo <code>#</code> è ignorato.</p>' +
      '<textarea id="sl-text" rows="10">' + CS.esc(text || '') + '</textarea>' +
      '<div class="btn-row">' +
      '<label class="choice"><input type="radio" name="slm" value="replace" checked> sostituisci la selezione</label>' +
      '<label class="choice"><input type="radio" name="slm" value="add"> aggiungi</label>' +
      '<label class="choice"><input type="radio" name="slm" value="remove"> togli</label></div>' +
      '<div id="sl-info" class="muted small"></div>';
    let out = null;
    const v = await modal({title: 'Seleziona da una lista', html, size: 'wide',
      buttons: [{label: 'Annulla', value: null}, {label: 'Seleziona', value: true, primary: true}],
      onOpen: (body) => {
        const ta = body.querySelector('#sl-text');
        const upd = () => {
          const p = CS.parseList(ta.value);
          body.querySelector('#sl-info').textContent = p.n ? p.keys.length + ' stazioni trovate' +
            (p.missing.length ? ' · non trovati: ' + p.missing.slice(0, 15).join(', ') +
              (p.missing.length > 15 ? ' …' : '') : '') : '';
        };
        ta.addEventListener('input', CS.debounce(upd, 150));
        upd();
      },
      check: (_, body) => {
        out = {text: body.querySelector('#sl-text').value, mode: body.querySelector('input[name=slm]:checked').value};
        return true;
      },
    });
    return v ? out : null;
  }

  /* ---------------------------------------------------------- details */

  function n(v, nd) { return v === null || v === undefined ? '—' : CS.fmtNum(v, nd); }

  async function detail(key) {
    let d;
    try { d = await CS.api('detail', {key}); } catch (e) { CS.error(e); return; }
    let h = '<div class="detail">';
    for (const v of d.versions) {
      const c = CS.catById.get(v.cat);
      if (!c) continue;
      h += '<h4><span class="badge" style="background:' + c.color + '">' + c.letter + '</span>' + CS.esc(c.name) +
        (v.diff.length ? ' <span class="neq">≠</span>' : '') + '</h4>';
      if (v.diff.length) {
        h += '<div class="small muted">Differenze rispetto a ' + CS.esc(CS.catById.get(d.versions[0].cat).letter) +
          ':</div><ul class="diff">' + v.diff.map((x) => '<li>' + CS.esc(x) + '</li>').join('') + '</ul>';
      }
      if (v.network.description) h += '<div class="small muted">Rete ' + CS.esc(v.network.code) + ': ' + CS.esc(v.network.description) + '</div>';
      for (const ep of v.epochs) {
        h += '<div class="epoch">Epoca ' + (ep.start || '?') + ' → ' + (ep.end || 'oggi') +
          ' · ' + n(ep.lat, 5) + ', ' + n(ep.lon, 5) + ' · ' + n(ep.elev, 0) + ' m' +
          (ep.site ? ' · ' + CS.esc(ep.site) : '') + '</div>';
        if (!ep.channels.length) { h += '<div class="muted small">nessun canale</div>'; continue; }
        h += '<table><tr><th>Canale</th><th>Inizio</th><th>Fine</th><th>Hz</th><th>Az</th><th>Dip</th><th>Prof. m</th>' +
          '<th>Sensore</th><th>Datalogger</th><th>Sensibilità</th><th>Stadi</th></tr>' +
          ep.channels.map((ch) => '<tr><td><b>' + CS.esc((ch.loc ? ch.loc + '.' : '') + ch.code) + '</b></td>' +
            '<td>' + (ch.start || '?') + '</td><td>' + (ch.end || 'oggi') + '</td><td>' + n(ch.sr, 0) + '</td>' +
            '<td>' + n(ch.az, 0) + '</td><td>' + n(ch.dip, 0) + '</td><td>' + n(ch.depth, 0) + '</td>' +
            '<td class="wrap">' + CS.esc(ch.sensor || '—') + '</td><td class="wrap">' + CS.esc(ch.logger || '—') + '</td>' +
            '<td>' + (ch.sens === null ? '<span class="err">assente</span>' : ch.sens.toExponential(4) + ' ' +
              CS.esc((ch.units_in || '?') + '→' + (ch.units_out || '?')) + (ch.sens_f !== null ? ' @' + ch.sens_f + ' Hz' : '')) +
            '</td><td>' + (ch.nstages === null ? '—' : ch.nstages) + '</td></tr>').join('') + '</table>';
      }
    }
    h += '</div>';
    const r = CS.rowByKey.get(key);
    await modal({title: CS.esc(r ? CS.code(r) : key) + (r && r.site ? ' <span class="muted">· ' + CS.esc(r.site) + '</span>' : ''),
      html: h, size: 'xwide'});
  }

  /* ------------------------------------------------------------- info */

  function catInfo(c) {
    let h = '<table class="help">' +
      '<tr><td>File</td><td>' + (c.path ? '<code>' + CS.esc(c.path) + '</code>' : '— (non ancora salvato)') + '</td></tr>' +
      '<tr><td>Tipo</td><td>' + ({xml: 'StationXML', dir: 'cartella di StationXML (' + c.nfiles + ' file)',
        pf: 'stazioni pyrocko (sola lettura)', txt: 'tabella di testo (sola lettura)', new: 'nuovo catalogo'})[c.kind] + '</td></tr>' +
      '<tr><td>Stazioni</td><td>' + c.n + ' · ' + Object.entries(c.nets).map(([k, v]) => (k || '?') + ': ' + v).join(', ') + '</td></tr>' +
      '<tr><td>Epoche canale</td><td>' + c.nchan + (c.noresp ? ' · <span class="err">' + c.noresp + ' senza risposta</span>' : '') + '</td></tr>' +
      '<tr><td>Periodo</td><td>' + (c.start ? c.start + ' → ' + (c.end || 'oggi') : 'date non disponibili') + '</td></tr>';
    for (const hd of c.headers) {
      h += '<tr><td>Origine</td><td><code>' + CS.esc(hd.file) + '</code><br>' + CS.esc([hd.source, hd.sender, hd.module]
        .filter(Boolean).join(' · ')) + (hd.created ? '<br>creato ' + hd.created : '') + '</td></tr>';
    }
    if (c.nfiles > c.headers.length) h += '<tr><td></td><td class="muted">… altri ' + (c.nfiles - c.headers.length) + ' file</td></tr>';
    h += '</table>';
    if (c.log.length) {
      h += '<h4 style="margin:10px 0 4px">Operazioni di questa sessione</h4><ul class="small">' +
        c.log.map((l) => '<li>' + CS.esc(l) + '</li>').join('') + '</ul>' +
        '<p class="muted small">Al salvataggio vengono scritte in un commento all\'inizio del file XML.</p>';
    }
    return modal({title: '<span class="badge" style="background:' + c.color + '">' + c.letter + '</span> ' + CS.esc(c.name),
      html: h, size: 'wide'});
  }

  function help() {
    const html = '<table class="help">' +
      '<tr><td><kbd>O</kbd></td><td>apri file di stazioni</td></tr>' +
      '<tr><td>clic</td><td>seleziona una stazione (mappa o tabella)</td></tr>' +
      '<tr><td><kbd>⌘</kbd>/<kbd>Ctrl</kbd> + clic</td><td>aggiunge / toglie una stazione</td></tr>' +
      '<tr><td><kbd>Maiusc</kbd> + clic</td><td>intervallo di righe (tabella)</td></tr>' +
      '<tr><td>doppio clic, <kbd>I</kbd></td><td>dettagli: epoche, canali, sensori, sensibilità</td></tr>' +
      '<tr><td><kbd>R</kbd> <kbd>L</kbd> <kbd>C</kbd></td><td>selezione a rettangolo, lazo, cerchio (<kbd>Maiusc</kbd> aggiunge, <kbd>Alt</kbd> toglie)</td></tr>' +
      '<tr><td><kbd>D</kbd></td><td>misura distanze</td></tr>' +
      '<tr><td><kbd>⌘A</kbd></td><td>seleziona tutte le stazioni visibili</td></tr>' +
      '<tr><td><kbd>Esc</kbd></td><td>annulla lo strumento / deseleziona</td></tr>' +
      '<tr><td><kbd>Canc</kbd></td><td>elimina le selezionate dal catalogo «Da»</td></tr>' +
      '<tr><td><kbd>⌘Z</kbd> / <kbd>⇧⌘Z</kbd></td><td>annulla / ripeti</td></tr>' +
      '<tr><td><kbd>F</kbd> / <kbd>Z</kbd></td><td>adatta la mappa alle stazioni visibili / selezionate</td></tr>' +
      '</table>' +
      '<p style="margin-top:10px">Le stazioni sono identificate da <code>NET.STA</code>: la stessa stazione in più cataloghi ' +
      'è un solo simbolo (a strisce, un colore per catalogo) e una sola riga. <span class="neq">≠</span> indica una versione ' +
      'diversa da quella del primo catalogo che la contiene.</p>' +
      '<p>Copiando, spostando o unendo cataloghi ogni stazione porta con sé tutte le sue epoche, i canali e le risposte ' +
      'strumentali. Se una stazione è già nel catalogo di destinazione con contenuto diverso, csta chiede quale versione ' +
      'tenere (o di unirle).</p>' +
      '<p>Salvando un file esistente, la versione precedente resta in <code>nome.xml.bak</code>. Ogni file salvato contiene ' +
      'all\'inizio un commento con i file di origine e le operazioni fatte.</p>';
    return modal({title: 'csta ' + CS.esc(CS.config.version) + ' — aiuto', html, size: 'wide'});
  }

  return {modal, confirm, prompt, openFiles, outputPath, conflicts, stationList, detail, catInfo, help};
})();
