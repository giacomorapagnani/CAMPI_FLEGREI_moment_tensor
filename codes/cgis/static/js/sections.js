/* cgis - cross-sections: drawn with two clicks (X), endpoints draggable,
 * width set in the panel (or with [ and ]). Event projection, topography
 * profile and rotated beachballs are computed by pyrocko on the server. */
'use strict';

CG.sections = (function () {
  const PLOT_SIZE = 0.7;
  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  let counter = 0;
  let plotMap = [];
  let dirty = true;
  let lastRender = 0;
  let trailing = null;

  const div = () => document.getElementById('plot-sec');
  const overlay = () => document.getElementById('sec-overlay');
  const $ = (id) => document.getElementById(id);

  function nextLabel() {
    const used = new Set(CG.sectionList.map((s) => s.label));
    for (let k = 0; k < 2600; k++) {
      const lab = k < 26 ? LETTERS[k] : LETTERS[k % 26] + Math.floor(k / 26);
      if (!used.has(lab)) return lab;
    }
    return 'S' + counter;
  }

  function defaultWidth(lengthKm) {
    const w = 0.2 * lengthKm;
    if (!(w > 0)) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(w)));
    return CG.clamp(Math.round(w / mag) * mag, 0.05, 100);
  }

  /* ------------------------------------------------------------- map */

  function corridorLatLngs(S) {
    const h = S.width / 2;
    return [[0, -h], [S.length, -h], [S.length, h], [0, h]].map(([s, d]) =>
      CG.geo.sectionPoint(S.lat1, S.lon1, S.azimuth, s, d));
  }

  function endIcon(text, active) {
    return L.divIcon({className: 'sec-end' + (active ? ' active' : ''), html: '<span>' + CG.esc(text) + '</span>',
      iconSize: [22, 22], iconAnchor: [11, 11]});
  }

  function drawOnMap(S) {
    const map = CG.mapLayer.map;
    if (S.map) S.map.group.remove();
    const group = L.layerGroup().addTo(map);
    const act = S === CG.activeSection;
    const corridor = L.polygon(corridorLatLngs(S), {color: '#111', weight: act ? 1.5 : 1, dashArray: '6,4',
      fillColor: '#000', fillOpacity: act ? 0.06 : 0.03, renderer: CG.toolsRenderer}).addTo(group);
    const line = L.polyline([[S.lat1, S.lon1], [S.lat2, S.lon2]], {color: act ? '#000' : '#444',
      weight: act ? 3 : 2, renderer: CG.toolsRenderer}).addTo(group);
    const mA = L.marker([S.lat1, S.lon1], {icon: endIcon(S.label, act), draggable: true, keyboard: false,
      title: 'Trascina per spostare l\'estremo'}).addTo(group);
    const mB = L.marker([S.lat2, S.lon2], {icon: endIcon(S.label + '′', act), draggable: true, keyboard: false,
      title: 'Trascina per spostare l\'estremo'}).addTo(group);
    const select = () => {
      if (CG.tools.mode) return;          // clicks belong to the active tool
      setActive(S);
      CG.ui.showTab('sec');
    };
    corridor.on('click', select);
    line.on('click', select);
    const onDrag = () => {
      const a = mA.getLatLng(), b = mB.getLatLng();
      S.lat1 = a.lat; S.lon1 = a.lng; S.lat2 = b.lat; S.lon2 = b.lng;
      const g = CG.geo.inverse(S.lat1, S.lon1, S.lat2, S.lon2);
      if (!(g.dist > 0)) return;
      S.length = g.dist / 1000; S.azimuth = g.az;
      line.setLatLngs([a, b]);
      corridor.setLatLngs(corridorLatLngs(S));
      projectDebounced(S);
    };
    for (const m of [mA, mB]) {
      m.on('drag', onDrag);
      m.on('dragend', () => { setActive(S); refresh(S, true); CG.session.changed(); });
      m.on('dragstart', () => CG.mapLayer.hideTooltip());
      m.on('click', select);
    }
    S.map = {group, corridor, line, mA, mB};
  }

  /* Restyle the map layers of a section (active / inactive) in place. */
  function styleOnMap(S) {
    if (!S.map) return;
    const act = S === CG.activeSection;
    S.map.corridor.setStyle({weight: act ? 1.5 : 1, fillOpacity: act ? 0.06 : 0.03});
    S.map.line.setStyle({color: act ? '#000' : '#444', weight: act ? 3 : 2});
    S.map.mA.setIcon(endIcon(S.label, act));
    S.map.mB.setIcon(endIcon(S.label + '′', act));
  }

  function updateCorridor(S) {
    if (S.map) S.map.corridor.setLatLngs(corridorLatLngs(S));
  }

  /* ---------------------------------------------------------- server */

  async function refresh(S, withTopo) {
    const seq = ++S.seq;
    try {
      const res = await CG.api('section_project', {
        lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2,
        cats: CG.cats.map((L) => L.id), stas: CG.stas.map((L) => L.id)});
      if (seq !== S.seq || !CG.sectionList.includes(S)) return;
      S.length = res.length_km;
      S.azimuth = res.azimuth;
      for (const L of CG.cats) {
        const p = res.cats[L.id];
        if (p) L.secProj[S.uid] = {s: CG.f64(p.s), d: CG.f64(p.d)};
      }
      for (const L of CG.stas) {
        const p = res.stas[L.id];
        if (p) L.secProj[S.uid] = {s: CG.f64(p.s), d: CG.f64(p.d)};
      }
      S.bb = {};
      S.geomVersion++;
      updateCorridor(S);
      if (withTopo) fetchTopo(S);
      if (S === CG.activeSection) { dirty = true; render(); }
    } catch (e) {
      CG.error(e, 'sezione ' + S.label);
    }
  }
  const projectDebounced = CG.debounce((S) => refresh(S, false), 150);

  async function projectLayer(Ly) {
    if (!CG.sectionList.length) return;
    await Promise.all(CG.sectionList.map(async (S) => {
      try {
        const body = {lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2, cats: [], stas: []};
        (Ly.kind === 'catalog' ? body.cats : body.stas).push(Ly.id);
        const res = await CG.api('section_project', body);
        const p = (Ly.kind === 'catalog' ? res.cats : res.stas)[Ly.id];
        if (p) Ly.secProj[S.uid] = {s: CG.f64(p.s), d: CG.f64(p.d)};
      } catch (e) {
        CG.error(e, 'sezione ' + S.label);
      }
    }));
    dirty = true;
    render();
  }

  async function fetchTopo(S) {
    S.topoError = null;
    if (!S.showTopo) return;
    const seq = S.seq;
    try {
      const res = await CG.api('topo_profile', {lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2, n: 500});
      if (seq !== S.seq) return;
      S.topo = {s: CG.f64(res.s), elev: CG.f64(res.elev), source: res.source};
    } catch (e) {
      S.topo = null;
      S.topoError = e.message;
      CG.toast('Topografia non disponibile: ' + e.message, 'error');
    }
    if (S === CG.activeSection) { dirty = true; render(); }
  }

  function inCorridor(S, proj, i) {
    const s = proj.s[i], d = proj.d[i];
    return Math.abs(d) <= S.width / 2 && s >= 0 && s <= S.length;
  }

  /* rotated beachballs for the MT events in the corridor */
  function ensureBeachballs(S, Ly, type) {
    const proj = Ly.secProj[S.uid];
    if (!proj || !Ly.hasMT) return null;
    const key = Ly.id + ':' + type;
    S.bb = S.bb || {};
    let entry = S.bb[key];
    if (!entry) entry = S.bb[key] = {map: new Map(), pending: new Set()};
    const need = [];
    for (const ev of Ly.mt.idx) {
      if (!entry.map.has(ev) && !entry.pending.has(ev) && inCorridor(S, proj, ev)) need.push(ev);
    }
    if (need.length) {
      need.forEach((ev) => entry.pending.add(ev));
      const version = S.geomVersion;
      CG.api('section_beachballs', {id: Ly.id, indices: need, azimuth: S.azimuth, type}).then((res) => {
        if (version !== S.geomVersion) return;
        res.idx.forEach((ev, k) => entry.map.set(ev, CG.mapLayer.buildPaths(res.polys[k])));
        drawOverlay();
      }).catch((e) => CG.error(e, 'beachball sezione')).finally(() => need.forEach((ev) => entry.pending.delete(ev)));
    }
    return entry.map;
  }

  /* ------------------------------------------------------------ plot */

  function plotLayers() {
    return CG.cats.filter((L) => L.style.visible && L.style.plots);
  }

  function render() {
    const S = CG.activeSection;
    if (CG.settings.tab !== 'sec' || CG.settings.panelCollapsed) return;
    const d = div();
    syncControls();
    if (!S) {
      Plotly.purge(d);
      clearOverlay();
      $('sec-info').innerHTML = '<span class="muted">Nessuna sezione. Premi X (o ✂ Sezione) e fai due clic sulla mappa.</span>';
      dirty = false;
      return;
    }
    const st = CG.settings;
    const traces = [];
    plotMap = [];
    const grey = {x: [], y: []};
    const greyOutside = st.outside === 'grey' && CG.timeWindow() !== null;
    let nIn = 0;
    for (const Ly of plotLayers()) {
      const proj = Ly.secProj[S.uid];
      if (!proj) continue;
      const showBB = S.showBB && st.bbShow && Ly.style.beachballs && Ly.hasMT;
      const x = [], y = [], c = [], sz = [], lc = [], idx = [];
      for (let i = 0; i < Ly.n; i++) {
        if (!Ly.base[i] || !Number.isFinite(Ly.dep[i]) || !inCorridor(S, proj, i)) continue;
        if (!Ly.vis[i]) {
          if (greyOutside) { grey.x.push(proj.s[i]); grey.y.push(Ly.dep[i]); }
          continue;
        }
        const bb = showBB && Ly.mtIdx[i] >= 0;
        x.push(proj.s[i]); y.push(Ly.dep[i]);
        c.push(bb ? 'rgba(0,0,0,0)' : Ly.colors[i]);
        lc.push(bb ? 'rgba(0,0,0,0)' : 'rgba(30,30,30,0.6)');
        sz.push(2 * Ly.r[i] * PLOT_SIZE * (bb ? st.bbScale : 1));
        idx.push(i);
      }
      nIn += idx.length;
      plotMap.push({L: Ly, idx});
      traces.push({type: 'scattergl', mode: 'markers', x, y, name: Ly.name,
        marker: {color: c, size: sz, opacity: CG.layerOpacity(Ly), line: {width: 0.5, color: lc}},
        hovertemplate: 'dist. %{x:.2f} km<br>prof. %{y:.2f} km<extra>' + CG.esc(Ly.name) + '</extra>'});
    }
    const data = [{type: 'scattergl', mode: 'markers', x: grey.x, y: grey.y, hoverinfo: 'skip',
      marker: {color: 'rgba(150,150,150,0.35)', size: 4}}].concat(traces);
    const offset = 1;

    const topo = S.showTopo && S.topo;
    // stations in the corridor
    const sx = [], sy = [], sc = [], st_ = [];
    if (S.showSta) {
      for (const Ls of CG.stas) {
        if (!Ls.style.visible) continue;
        const proj = Ls.secProj[S.uid];
        if (!proj) continue;
        Ls.stations.forEach((sta, k) => {
          if (!inCorridor(S, proj, k)) return;
          let e = sta.elev;
          if ((e === null || e === undefined) && topo) e = interp(topo.s, topo.elev, proj.s[k]);
          sx.push(proj.s[k]);
          sy.push(topo ? (Number.isFinite(e) ? e : 0) : null);
          sc.push(Ls.classColors[sta.cls] || '#999');
          st_.push(sta.sta);
        });
      }
    }
    if (topo) {
      data.push({type: 'scatter', mode: 'lines', x: Array.from(topo.s), y: Array.from(topo.elev), yaxis: 'y2',
        fill: 'tozeroy', fillcolor: 'rgba(200,200,195,0.8)', line: {color: '#333', width: 1.3},
        hovertemplate: '%{y:.0f} m<extra>' + CG.esc(topo.source) + '</extra>'});
      if (sx.length) {
        data.push({type: 'scatter', mode: 'markers+text', x: sx, y: sy, yaxis: 'y2', text: st_, textposition: 'top center',
          textfont: {size: 9}, marker: {symbol: 'triangle-up', size: 11, color: sc, line: {width: 1, color: '#000'}},
          hovertemplate: '%{text}<extra></extra>'});
      }
    }

    const yaxis = {title: {text: 'Profondità (km)'}, gridcolor: '#eee', zeroline: true, zerolinecolor: '#bbb',
      domain: topo ? [0, 0.76] : [0, 1]};
    if (S.zmin !== null && S.zmax !== null && S.zmax > S.zmin) yaxis.range = [S.zmax, S.zmin];
    else yaxis.autorange = 'reversed';
    if (S.trueScale) { yaxis.scaleanchor = 'x'; yaxis.scaleratio = 1; }
    const annotations = [
      {text: '<b>' + CG.esc(S.label) + '</b>', x: 0, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', showarrow: false, font: {size: 13}},
      {text: '<b>' + CG.esc(S.label) + '′</b>', x: S.length, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', showarrow: false, font: {size: 13}},
    ];
    if (!topo && sx.length) {
      // stations along the top of the depth axis
      sx.forEach((x, k) => annotations.push({x, xref: 'x', y: 1, yref: 'paper', text: '▲', showarrow: false,
        font: {color: sc[k], size: 12}, yanchor: 'top', hovertext: st_[k]}));
    }
    const layout = {
      margin: {l: 58, r: 18, t: 22, b: 38},
      font: {family: '-apple-system, Helvetica, Arial, sans-serif', size: 11},
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#fff',
      showlegend: false, hovermode: 'closest', dragmode: 'zoom',
      uirevision: S.uid + ':' + S.geomVersion + ':' + (S.trueScale ? 1 : 0) + ':' + S.zmin + ':' + S.zmax + ':' + (topo ? 1 : 0),
      xaxis: {title: {text: 'Distanza lungo ' + S.label + '–' + S.label + '′ (km)'}, range: [0, S.length],
        gridcolor: '#eee', zeroline: false},
      yaxis,
      annotations,
      shapes: hlShapes(S),
    };
    if (topo) {
      layout.yaxis2 = {domain: [0.8, 1], title: {text: 'Quota (m)'}, gridcolor: '#eee', zeroline: true,
        zerolinecolor: '#7090c0', anchor: 'x'};
    }
    const d0 = d;
    Plotly.react(d0, data, layout, {displaylogo: false, scrollZoom: true,
      modeBarButtonsToRemove: ['toImage', 'lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines',
        'hoverClosestCartesian', 'hoverCompareCartesian']});
    if (!d0._cgBound) {
      d0._cgBound = true;
      d0.on('plotly_hover', (ev) => {
        const p = ev.points && ev.points[0];
        if (!p) return;
        const m = plotMap[p.curveNumber - offset];
        if (m) CG.mapLayer.setHover({L: m.L, i: m.idx[p.pointNumber]}, 'sec');
      });
      d0.on('plotly_unhover', () => CG.mapLayer.setHover(null, 'sec'));
      d0.on('plotly_afterplot', drawOverlay);
      d0.on('plotly_relayouting', clearOverlay);
    }
    const nTot = plotLayers().reduce((a, Ly) => {
      const proj = Ly.secProj[S.uid];
      if (!proj) return a;
      let n = 0;
      for (let i = 0; i < Ly.n; i++) if (Ly.base[i] && Number.isFinite(Ly.dep[i]) && inCorridor(S, proj, i)) n++;
      return a + n;
    }, 0);
    $('sec-info').innerHTML = 'Lunghezza ' + S.length.toFixed(2) + ' km · azimut ' + S.azimuth.toFixed(1) +
      '°<br>' + nIn + ' eventi visibili nel corridoio (' + nTot + ' con i filtri)' +
      (S.topoError ? '<br><span class="err">topografia: ' + CG.esc(S.topoError) + '</span>' :
        (topo ? '<br><span class="muted">topografia: ' + CG.esc(topo.source) + '</span>' : ''));
    dirty = false;
    drawOverlay();
  }

  function interp(xs, ys, x) {
    if (!xs.length) return NaN;
    if (x <= xs[0]) return ys[0];
    for (let k = 1; k < xs.length; k++) {
      if (x <= xs[k]) {
        const f = (x - xs[k - 1]) / (xs[k] - xs[k - 1]);
        return ys[k - 1] * (1 - f) + ys[k] * f;
      }
    }
    return ys[ys.length - 1];
  }

  function clearOverlay() {
    const c = overlay();
    if (c) c.getContext('2d').clearRect(0, 0, c.width, c.height);
  }

  function drawOverlay() {
    const S = CG.activeSection;
    const d = div();
    const c = overlay();
    if (!S || !c || !d._fullLayout || !d._fullLayout.xaxis || CG.settings.tab !== 'sec') return;
    const st = CG.settings;
    const dpr = window.devicePixelRatio || 1;
    const W = d.clientWidth, H = d.clientHeight;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
      c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
      c.style.width = W + 'px'; c.style.height = H + 'px';
    }
    const ctx = c.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    if (!(S.showBB && st.bbShow)) return;
    const xa = d._fullLayout.xaxis, ya = d._fullLayout.yaxis;
    if (!xa || !ya || !xa.l2p || !ya.l2p) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.save();
    ctx.beginPath();
    ctx.rect(xa._offset, ya._offset, xa._length, ya._length);
    ctx.clip();
    for (const Ly of plotLayers()) {
      if (!Ly.style.beachballs || !Ly.hasMT) continue;
      const proj = Ly.secProj[S.uid];
      if (!proj) continue;
      const paths = ensureBeachballs(S, Ly, st.bbType);
      const list = [];
      for (const ev of Ly.mt.idx) {
        if (Ly.vis[ev] && Number.isFinite(Ly.dep[ev]) && inCorridor(S, proj, ev)) list.push(ev);
      }
      list.sort((a, b) => Ly.r[b] - Ly.r[a]);
      ctx.globalAlpha = CG.layerOpacity(Ly);
      for (const ev of list) {
        const x = xa._offset + xa.l2p(proj.s[ev]);
        const y = ya._offset + ya.l2p(Ly.dep[ev]);
        const r = Ly.r[ev] * PLOT_SIZE * st.bbScale;
        CG.mapLayer.drawBeachball(ctx, x, y, r, paths ? paths.get(ev) : null, Ly.colors[ev], dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    }
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function hlShapes(S) {
    const hv = CG.hover;
    if (!S || !hv || !hv.L.vis[hv.i] || !hv.L.style.plots) return [];
    const proj = hv.L.secProj[S.uid];
    if (!proj || !inCorridor(S, proj, hv.i) || !Number.isFinite(hv.L.dep[hv.i])) return [];
    // same size as the symbol in the section (beachballs are larger)
    const st = CG.settings;
    const bb = S.showBB && st.bbShow && hv.L.style.beachballs && hv.L.mtIdx[hv.i] >= 0;
    const R = hv.L.r[hv.i] * PLOT_SIZE * (bb ? st.bbScale : 1) + 4;
    return [['#fff', 4], ['#000', 2]].map(([color, width]) => ({type: 'circle', xref: 'x', yref: 'y',
      xsizemode: 'pixel', ysizemode: 'pixel', xanchor: proj.s[hv.i], yanchor: hv.L.dep[hv.i],
      x0: -R, x1: R, y0: -R, y1: R, line: {color, width}, layer: 'above'}));
  }

  function highlight(source) {
    const S = CG.activeSection;
    const d = div();
    if (!S || source === 'sec' || CG.settings.tab !== 'sec' || !d._fullLayout) return;
    Plotly.relayout(d, {shapes: hlShapes(S)}).catch(() => {});
  }

  /* --------------------------------------------------------- controls */

  function syncControls() {
    const sel = $('sec-select');
    const S = CG.activeSection;
    sel.innerHTML = CG.sectionList.map((s) => '<option value="' + s.uid + '"' + (s === S ? ' selected' : '') + '>' +
      CG.esc(s.label + '–' + s.label + '′') + '</option>').join('') || '<option value="">—</option>';
    const dis = !S;
    for (const id of ['sec-width', 'sec-width-r', 'sec-zmin', 'sec-zmax', 'sec-true', 'sec-bb', 'sec-topo', 'sec-sta',
      'sec-rename', 'sec-delete', 'sec-events']) $(id).disabled = dis;
    if (!S) return;
    if (document.activeElement !== $('sec-width')) $('sec-width').value = +S.width.toFixed(3);
    const r = $('sec-width-r');
    r.max = Math.max(20, Math.ceil(S.length));
    r.value = S.width;
    if (document.activeElement !== $('sec-zmin')) $('sec-zmin').value = S.zmin === null ? '' : S.zmin;
    if (document.activeElement !== $('sec-zmax')) $('sec-zmax').value = S.zmax === null ? '' : S.zmax;
    $('sec-true').checked = S.trueScale;
    $('sec-bb').checked = S.showBB;
    $('sec-topo').checked = S.showTopo;
    $('sec-sta').checked = S.showSta;
  }

  function setActive(S) {
    const prev = CG.activeSection;
    CG.activeSection = S;
    if (prev && prev !== S && CG.sectionList.includes(prev)) styleOnMap(prev);
    if (S) styleOnMap(S);
    dirty = true;
    render();
    syncControls();
  }

  function setWidth(S, w) {
    if (!(w > 0)) return;
    S.width = CG.clamp(+w, 0.01, 2000);
    updateCorridor(S);
    syncControls();
    if (S === CG.activeSection) { dirty = true; render(); }
    CG.session.changed();
  }

  function remove(S) {
    S.map && S.map.group.remove();
    const k = CG.sectionList.indexOf(S);
    if (k >= 0) CG.sectionList.splice(k, 1);
    for (const Ly of CG.cats.concat(CG.stas)) delete Ly.secProj[S.uid];
    if (CG.activeSection === S) setActive(CG.sectionList[CG.sectionList.length - 1] || null);
    syncControls();
    CG.session.changed();
  }

  function init() {
    $('sec-select').onchange = (e) => {
      const S = CG.sectionList.find((s) => s.uid === e.target.value);
      if (S) setActive(S);
    };
    const widthInput = () => {
      const S = CG.activeSection;
      const v = CG.parseNum($('sec-width').value);
      if (S && v > 0) setWidth(S, v);
    };
    $('sec-width').onchange = widthInput;
    $('sec-width').onkeydown = (e) => { if (e.key === 'Enter') widthInput(); };
    $('sec-width-r').oninput = (e) => { const S = CG.activeSection; if (S) setWidth(S, +e.target.value); };
    const zInput = () => {
      const S = CG.activeSection;
      if (!S) return;
      const a = CG.parseNum($('sec-zmin').value), b = CG.parseNum($('sec-zmax').value);
      if (Number.isNaN(a) || Number.isNaN(b)) { CG.toast('Profondità non valida', 'error'); return; }
      if (a !== null && b !== null && !(b > a)) { CG.toast('Profondità: max deve essere maggiore di min', 'error'); return; }
      S.zmin = a; S.zmax = b;
      if ((a === null) !== (b === null)) {
        // one bound only: fill the other from the data
        const ys = [];
        for (const Ly of plotLayers()) {
          const proj = Ly.secProj[S.uid];
          if (proj) for (let i = 0; i < Ly.n; i++) if (Ly.vis[i] && inCorridor(S, proj, i) && Number.isFinite(Ly.dep[i])) ys.push(Ly.dep[i]);
        }
        if (ys.length) {
          if (a === null) S.zmin = Math.min(...ys);
          else S.zmax = Math.max(...ys);
        } else { S.zmin = null; S.zmax = null; }
      }
      dirty = true; render(); CG.session.changed();
    };
    $('sec-zmin').onchange = zInput;
    $('sec-zmax').onchange = zInput;
    const flag = (id, key, fn) => {
      $(id).onchange = (e) => {
        const S = CG.activeSection;
        if (!S) return;
        S[key] = e.target.checked;
        if (fn) fn(S);
        dirty = true; render(); CG.session.changed();
      };
    };
    flag('sec-true', 'trueScale');
    flag('sec-bb', 'showBB');
    flag('sec-topo', 'showTopo', (S) => { if (S.showTopo && !S.topo) fetchTopo(S); });
    flag('sec-sta', 'showSta');
    $('sec-rename').onclick = () => {
      const S = CG.activeSection;
      if (!S) return;
      CG.ui.prompt('Nome della sezione', S.label, (v) => {
        v = (v || '').trim();
        if (!v) return;
        if (CG.sectionList.some((s) => s !== S && s.label === v)) { CG.toast('Nome già usato', 'error'); return; }
        S.label = v.slice(0, 20);
        drawOnMap(S); dirty = true; render(); CG.session.changed();
      });
    };
    $('sec-delete').onclick = () => {
      const S = CG.activeSection;
      if (S) CG.ui.confirm('Eliminare la sezione ' + S.label + '–' + S.label + '′?', () => remove(S));
    };
    $('sec-events').onclick = () => {
      const S = CG.activeSection;
      if (!S) return;
      const items = [];
      for (const Ly of plotLayers()) {
        const proj = Ly.secProj[S.uid];
        if (!proj) continue;
        const idx = [];
        for (let i = 0; i < Ly.n; i++) if (Ly.vis[i] && inCorridor(S, proj, i)) idx.push(i);
        if (idx.length) items.push({id: Ly.id, indices: idx});
      }
      CG.ui.exportEvents(items, 'sezione_' + S.label);
    };
    window.addEventListener('resize', CG.debounce(() => { if (CG.settings.tab === 'sec') resize(); }, 150));
  }

  function resize() {
    const d = div();
    if (d && d.data) {
      try { Plotly.Plots.resize(d); } catch (e) { /* ignore */ }
    }
    drawOverlay();
  }

  /* ------------------------------------------------------------ API */

  function create(lat1, lon1, lat2, lon2, opts) {
    opts = opts || {};
    const g = CG.geo.inverse(lat1, lon1, lat2, lon2);
    if (!(g.dist > 0)) { CG.toast('Gli estremi della sezione coincidono', 'error'); return null; }
    const o = opts.options || {};
    const S = {
      uid: 'S' + (++counter), label: opts.label || nextLabel(),
      lat1, lon1, lat2, lon2,
      width: opts.width_km > 0 ? opts.width_km : defaultWidth(g.dist / 1000),
      length: g.dist / 1000, azimuth: g.az,
      zmin: o.zmin === undefined ? null : o.zmin,
      zmax: o.zmax === undefined ? null : o.zmax,
      trueScale: !!o.trueScale,
      showBB: o.showBB === undefined ? true : !!o.showBB,
      showTopo: o.showTopo === undefined ? true : !!o.showTopo,
      showSta: o.showSta === undefined ? true : !!o.showSta,
      topo: null, topoError: null, bb: {}, seq: 0, geomVersion: 0, map: null,
    };
    CG.sectionList.push(S);
    drawOnMap(S);
    if (!opts.restoring) {
      setActive(S);
      CG.ui.showTab('sec');
    }
    refresh(S, true);
    CG.session.changed();
    return S;
  }

  function update() {
    dirty = true;
    if (CG.settings.tab !== 'sec') return;
    const now = performance.now();
    const minGap = CG.timebar && CG.timebar.playing ? 200 : 0;
    clearTimeout(trailing);
    if (now - lastRender >= minGap) { lastRender = now; render(); }
    else trailing = setTimeout(() => { lastRender = performance.now(); render(); }, minGap);
  }

  function clearAll() {
    for (const S of CG.sectionList.slice()) { S.map && S.map.group.remove(); }
    CG.sectionList.length = 0;
    CG.activeSection = null;
    for (const Ly of CG.cats.concat(CG.stas)) Ly.secProj = {};
    syncControls();
  }

  return {
    init, create, update, render: () => { dirty = true; render(); }, highlight, resize, setActive, setWidth,
    remove, clearAll, projectLayer, inCorridor, syncControls,
    showTab() { if (dirty) render(); else resize(); },
    redrawMap() { for (const S of CG.sectionList) drawOnMap(S); },
  };
})();
