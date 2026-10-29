/* csta - station table: one row per NET.STA shown on the map, a column per
 * visible catalogue. Click selects, ⌘/Ctrl-click toggles, Shift-click
 * selects a range, double click opens the details. */
'use strict';

CS.table = (function () {
  const sort = {col: 'key', desc: false};
  let order = [];          // keys in display order
  let anchor = null;       // last clicked key (Shift ranges)
  const trByKey = new Map();

  const COLS = [
    {id: 'key', label: 'Stazione', get: (r) => CS.code(r)},
    {id: 'site', label: 'Sito', get: (r) => r.site || ''},
    {id: 'lat', label: 'Lat', num: true, get: (r) => r.lat, fmt: (r) => CS.fmtNum(r.lat, 5)},
    {id: 'lon', label: 'Lon', num: true, get: (r) => r.lon, fmt: (r) => CS.fmtNum(r.lon, 5)},
    {id: 'elev', label: 'Quota m', num: true, get: (r) => r.elev, fmt: (r) => CS.fmtNum(r.elev, 0)},
    {id: 'chans', label: 'Canali', get: (r) => r.chans || ''},
    {id: 'nchan', label: 'Ep. canali', num: true, get: (r) => r.nchan, title: 'Epoche di canale (tutte le epoche)'},
    {id: 'srs', label: 'Hz', get: (r) => r.srs.join(', '), sortv: (r) => r.srs.length ? r.srs[r.srs.length - 1] : -1},
    {id: 'sensors', label: 'Sensori', get: (r) => r.sensors.join(', ')},
    {id: 'start', label: 'Inizio', get: (r) => r.start || ''},
    {id: 'end', label: 'Fine', get: (r) => r.end || '', fmt: (r) => (r.end ? r.end : (r.start ? 'attiva' : '—')),
      sortv: (r) => r.end || '9999'},
  ];

  function catCols() {
    return CS.visibleCats().map((c) => ({
      id: 'cat:' + c.id, cat: c, label: c.letter,
      get: (r) => (r.versions.has(c.id) ? (r.versions.get(c.id).sig !== r.sig ? 2 : 1) : 0),
    }));
  }

  function sortValue(col, r) {
    if (col.sortv) return col.sortv(r);
    return col.get(r);
  }

  function compare(a, b) {
    if (a === b) return 0;
    if (a === null || a === undefined || a === '') return 1;
    if (b === null || b === undefined || b === '') return -1;
    if (typeof a === 'number' && typeof b === 'number') return a - b;
    return String(a).localeCompare(String(b), 'it', {numeric: true});
  }

  function cellHTML(col, r) {
    if (col.cat) {
      const v = r.versions.get(col.cat.id);
      if (!v) return '<td class="catcell"></td>';
      const neq = v.sig !== r.sig;
      return '<td class="catcell" title="' + CS.esc(col.cat.letter + ' · ' + col.cat.name) +
        (neq ? ' — versione diversa dal primo catalogo' : '') + '"><span class="dot" style="background:' +
        col.cat.color + '"></span>' + (neq ? '<span class="neq"> ≠</span>' : '') + '</td>';
    }
    const txt = col.fmt ? col.fmt(r) : col.get(r);
    return '<td' + (col.num ? ' class="num"' : '') + ' title="' + CS.esc(txt) + '">' + CS.esc(txt) + '</td>';
  }

  function render() {
    const cols = COLS.concat(catCols());
    const thead = document.querySelector('#tbl thead');
    thead.innerHTML = '<tr>' + cols.map((c) =>
      '<th data-col="' + c.id + '" class="' + (c.cat ? 'catcol ' : '') + (sort.col === c.id ? 'sorted' + (sort.desc ? ' desc' : '') : '') +
      '"' + (c.cat ? ' style="color:' + c.cat.color + '" title="' + CS.esc(c.cat.letter + ' · ' + c.cat.name) + '"'
        : (c.title ? ' title="' + CS.esc(c.title) + '"' : '')) + '>' + CS.esc(c.label) + '</th>').join('') + '</tr>';

    const col = cols.find((c) => c.id === sort.col) || cols[0];
    const rows = CS.shown.slice().sort((a, b) => {
      const d = compare(sortValue(col, a), sortValue(col, b));
      return (sort.desc ? -d : d) || compare(a.key, b.key);
    });
    order = rows.map((r) => r.key);

    const tbody = document.querySelector('#tbl tbody');
    if (!rows.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="' + cols.length + '">' +
        (CS.rows.length ? 'Nessuna stazione con i filtri attuali' : 'Nessuna stazione') + '</td></tr>';
    } else {
      tbody.innerHTML = rows.map((r) => '<tr data-key="' + CS.esc(r.key) + '" class="' +
        (CS.sel.has(r.key) ? 'sel ' : '') + (r.active ? '' : 'closed') + '">' +
        cols.map((c) => cellHTML(c, r)).join('') + '</tr>').join('');
    }
    trByKey.clear();
    tbody.querySelectorAll('tr[data-key]').forEach((tr) => trByKey.set(tr.dataset.key, tr));
    updateCount();
  }

  function updateSelection() {
    for (const [key, tr] of trByKey) tr.classList.toggle('sel', CS.sel.has(key));
    updateCount();
  }

  function updateCount() {
    const n = CS.shown.length, tot = CS.rows.length;
    let s = n + (n === tot ? '' : ' di ' + tot) + ' stazioni';
    if (n !== tot) s += ' (filtrate)';
    s += ' · ' + CS.sel.size + ' selezionate';
    document.getElementById('tbl-count').textContent = s;
    document.getElementById('btn-detail').disabled = CS.sel.size !== 1;
  }

  function reveal(key) {
    const tr = trByKey.get(key);
    if (!tr) return;
    const wrap = document.getElementById('table-wrap');
    const head = document.querySelector('#tbl thead').offsetHeight;
    const top = tr.offsetTop, bottom = top + tr.offsetHeight;
    if (top - head < wrap.scrollTop || bottom > wrap.scrollTop + wrap.clientHeight) {
      wrap.scrollTop = top - head - wrap.clientHeight / 3;
    }
  }

  function init() {
    const thead = document.querySelector('#tbl thead');
    thead.addEventListener('click', (e) => {
      const th = e.target.closest('th');
      if (!th) return;
      const id = th.dataset.col;
      if (sort.col === id) sort.desc = !sort.desc;
      else { sort.col = id; sort.desc = false; }
      render();
    });

    const tbody = document.querySelector('#tbl tbody');
    tbody.addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-key]');
      if (!tr) return;
      const key = tr.dataset.key;
      if (e.shiftKey && anchor && order.includes(anchor)) {
        const i0 = order.indexOf(anchor), i1 = order.indexOf(key);
        const range = order.slice(Math.min(i0, i1), Math.max(i0, i1) + 1);
        CS.select(range, (e.metaKey || e.ctrlKey) ? 'add' : 'replace');
      } else if (e.metaKey || e.ctrlKey) {
        CS.select([key], 'toggle');
        anchor = key;
      } else {
        CS.select([key], 'replace');
        anchor = key;
      }
      CS.map.panTo(key);
    });
    tbody.addEventListener('dblclick', (e) => {
      const tr = e.target.closest('tr[data-key]');
      if (tr) CS.ui.showDetail(tr.dataset.key);
    });
    tbody.addEventListener('mouseover', (e) => {
      const tr = e.target.closest('tr[data-key]');
      CS.setHover(tr ? tr.dataset.key : null, 'table');
    });
    tbody.addEventListener('mouseleave', () => CS.setHover(null, 'table'));

    CS.on('rows', render);
    CS.on('sel', updateSelection);
    CS.on('reveal', reveal);
    CS.on('hover', (old, key, src) => {
      if (old && trByKey.has(old)) trByKey.get(old).classList.remove('hover');
      if (key && trByKey.has(key)) {
        trByKey.get(key).classList.add('hover');
        if (src === 'map') reveal(key);
      }
    });
  }

  return {init, render, get order() { return order; }};
})();
