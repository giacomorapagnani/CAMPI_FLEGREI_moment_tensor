/* cgis - bottom panel plots (Plotly): time-depth, time-magnitude,
 * cumulative number/moment, Gutenberg-Richter, P/T axes stereonet. */
'use strict';

CG.plots = (function () {
  const PLOT_SIZE = 0.7;      // symbol size factor of the plots w.r.t. the map
  const state = {
    td: {dirty: true, map: [], hl: -1},
    tm: {dirty: true, map: [], hl: -1},
    cum: {dirty: true},
    fmd: {dirty: true},
    pt: {dirty: true, map: [], hl: -1},
  };
  const CONFIG = {displaylogo: false, responsive: false, scrollZoom: true,
    modeBarButtonsToRemove: ['toImage', 'lasso2d', 'autoScale2d', 'toggleSpikelines',
      'hoverClosestCartesian', 'hoverCompareCartesian']};

  const el = (tab) => document.getElementById('plot-' + tab);
  const active = () => CG.settings.tab;

  function baseLayout(extra) {
    return Object.assign({
      margin: {l: 58, r: 18, t: 8, b: 36},
      font: {family: '-apple-system, Helvetica, Arial, sans-serif', size: 11},
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: '#ffffff',
      showlegend: false,
      hovermode: 'closest',
      dragmode: 'zoom',
      // zoom/pan survive the time-window updates, reset when layers change
      uirevision: active() + ':' + plotLayers().map((L) => L.uid).join(','),
    }, extra || {});
  }

  function windowShapes() {
    const w = CG.timeWindow();
    const tm = CG.settings.time;
    if (!w) return [];
    const t0 = tm.mode === 'cumulative' ? null : tm.t0;
    const shapes = [];
    if (t0 !== null) {
      shapes.push({type: 'rect', xref: 'x', yref: 'paper', x0: CG.plotlyDate(t0), x1: CG.plotlyDate(tm.t1),
        y0: 0, y1: 1, fillcolor: 'rgba(255,190,60,0.16)', line: {width: 0}, layer: 'below'});
    }
    shapes.push({type: 'line', xref: 'x', yref: 'paper', x0: CG.plotlyDate(tm.t1), x1: CG.plotlyDate(tm.t1),
      y0: 0, y1: 1, line: {color: '#e08000', width: 1.5}});
    if (t0 !== null) {
      shapes.push({type: 'line', xref: 'x', yref: 'paper', x0: CG.plotlyDate(t0), x1: CG.plotlyDate(t0),
        y0: 0, y1: 1, line: {color: '#e08000', width: 1.5}});
    }
    return shapes;
  }

  function plotLayers() {
    return CG.cats.filter((L) => L.style.visible && L.style.plots);
  }

  /* layers with a time axis (catalogues without times are left out) */
  function timeLayers() {
    return plotLayers().filter((L) => !L.noTime);
  }

  /* Highlight rings as pixel-sized layout shapes: cheap to update, and
   * unlike restyling a trace they do not reset the axis types. */
  /* Ring around a point of radius ``r`` px (as on the map: white halo,
   * black line, 4 px outside the symbol). */
  function ringShapes(points, r, xref, yref) {
    const R = (r || 7) + 4;
    const out = [];
    for (const [x, y] of points) {
      for (const [color, width] of [['#fff', 4], ['#000', 2]]) {
        out.push({type: 'circle', xref: xref || 'x', yref: yref || 'y', xsizemode: 'pixel', ysizemode: 'pixel',
          xanchor: x, yanchor: y, x0: -R, x1: R, y0: -R, y1: R, line: {color, width}, layer: 'above'});
      }
    }
    return out;
  }

  /* ----------------------------------------------- time-depth / time-mag */

  function timePlot(tab, yKey) {
    const div = el(tab);
    const st = state[tab];
    const grey = {x: [], y: []};
    const traces = [];
    st.map = [];
    const greyOutside = CG.timeWindow() !== null;
    for (const L of timeLayers()) {
      const x = [], y = [], c = [], s = [], idx = [];
      const yy = yKey === 'dep' ? L.dep : L.mag;
      const tt = CG.plotlyTimes(L);
      for (let i = 0; i < L.n; i++) {
        if (!L.base[i] || !Number.isFinite(yy[i])) continue;
        if (!L.vis[i]) {
          if (greyOutside) { grey.x.push(tt[i]); grey.y.push(yy[i]); }
          continue;
        }
        x.push(tt[i]); y.push(yy[i]); c.push(L.colors[i]);
        s.push(2 * L.r[i] * PLOT_SIZE); idx.push(i);
      }
      st.map.push({L, idx});
      traces.push({type: 'scattergl', mode: 'markers', x, y, name: L.name,
        marker: {color: c, size: s, opacity: CG.layerOpacity(L), line: {width: 0.5, color: 'rgba(30,30,30,0.6)'}},
        hovertemplate: '%{x|%Y-%m-%d %H:%M:%S}<br>' + (yKey === 'dep' ? 'prof. %{y:.2f} km' : 'M %{y:.2f}') + '<extra>' + CG.esc(L.name) + '</extra>'});
    }
    const greyTrace = {type: 'scattergl', mode: 'markers', x: grey.x, y: grey.y, hoverinfo: 'skip',
      marker: {color: 'rgba(150,150,150,0.35)', size: 4}};
    const data = [greyTrace].concat(traces);
    st.offset = 1;
    st.baseShapes = windowShapes();
    const layout = baseLayout({
      xaxis: {type: 'date', gridcolor: '#eee', zeroline: false},
      yaxis: {title: {text: yKey === 'dep' ? 'Profondità (km)' : 'Magnitudo'}, gridcolor: '#eee',
        autorange: yKey === 'dep' ? 'reversed' : true, zeroline: false},
      shapes: st.baseShapes.concat(hlShapes(tab)),
    });
    Plotly.react(div, data, layout, CONFIG);
    if (!div._cgBound) bindTimeEvents(div, tab, yKey);
    st.dirty = false;
  }

  function bindTimeEvents(div, tab, yKey) {
    div._cgBound = true;
    div.on('plotly_hover', (ev) => {
      const p = ev.points && ev.points[0];
      if (!p) return;
      const m = state[tab].map[p.curveNumber - state[tab].offset];
      if (!m) return;
      CG.mapLayer.setHover({L: m.L, i: m.idx[p.pointNumber]}, tab);
    });
    div.on('plotly_unhover', () => CG.mapLayer.setHover(null, tab));
    div.on('plotly_click', (ev) => {
      const p = ev.points && ev.points[0];
      if (!p) return;
      const m = state[tab].map[p.curveNumber - state[tab].offset];
      if (!m) return;
      const i = m.idx[p.pointNumber];
      CG.mapLayer.map.panTo([m.L.lat[i], m.L.lon[i]]);
    });
    // box selection -> time window + depth/magnitude filter
    div.on('plotly_selected', (ev) => {
      if (!ev || !ev.range || !ev.range.x) return;
      const t0 = CG.plotlyToTime(ev.range.x[0]);
      const t1 = CG.plotlyToTime(ev.range.x[1]);
      const y0 = Math.min(ev.range.y[0], ev.range.y[1]);
      const y1 = Math.max(ev.range.y[0], ev.range.y[1]);
      if (!(t1 > t0)) return;
      CG.timebar.setWindow(t0, t1, 'window');
      const f = CG.settings.filters;
      if (yKey === 'dep') { f.depMin = +y0.toFixed(3); f.depMax = +y1.toFixed(3); }
      else { f.magMin = +y0.toFixed(2); f.magMax = +y1.toFixed(2); }
      CG.ui.syncFilters();
      CG.invalidate('filter');
      Plotly.relayout(div, {dragmode: 'zoom'});
      CG.toast('Selezione applicata come finestra temporale e filtro (azzera filtri per annullare)', 'info');
    });
  }

  /* --------------------------------------------------------- cumulative */

  function cumPlot() {
    const div = el('cum');
    const data = [];
    timeLayers().forEach((L, k) => {
      const ts = [], m0 = [];
      for (let i = 0; i < L.n; i++) {
        if (!L.base[i]) continue;
        ts.push(i);
      }
      ts.sort((a, b) => L.t[a] - L.t[b]);
      const x = new Array(ts.length), yn = new Array(ts.length), ym = new Array(ts.length);
      const tt = CG.plotlyTimes(L);
      let cm = 0;
      ts.forEach((i, j) => {
        x[j] = tt[i];
        yn[j] = j + 1;
        const kk = L.mtIdx[i];
        let mo = kk >= 0 && L.mt.m0[kk] ? L.mt.m0[kk] : NaN;
        if (!Number.isFinite(mo) && Number.isFinite(L.mag[i])) mo = Math.pow(10, 1.5 * L.mag[i] + 9.1);
        if (Number.isFinite(mo)) cm += mo;
        ym[j] = cm;
      });
      const col = L.style.color || CG.colors.CATEGORICAL[k % CG.colors.CATEGORICAL.length];
      data.push({type: 'scattergl', mode: 'lines', x, y: yn, name: L.name + ' – N',
        line: {color: col, width: 2, shape: 'hv'}, hovertemplate: '%{x|%Y-%m-%d}<br>N = %{y}<extra>' + CG.esc(L.name) + '</extra>'});
      if (cm > 0) {
        data.push({type: 'scattergl', mode: 'lines', x, y: ym, yaxis: 'y2', name: L.name + ' – M0',
          line: {color: col, width: 1.5, dash: 'dot', shape: 'hv'},
          hovertemplate: '%{x|%Y-%m-%d}<br>ΣM0 = %{y:.3e} Nm<extra>' + CG.esc(L.name) + '</extra>'});
      }
    });
    const layout = baseLayout({
      margin: {l: 58, r: 70, t: 8, b: 36},
      showlegend: true,
      legend: {orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: {size: 10}},
      xaxis: {type: 'date', gridcolor: '#eee'},
      yaxis: {title: {text: 'Numero cumulativo'}, gridcolor: '#eee', rangemode: 'tozero'},
      yaxis2: {title: {text: 'Momento cumulativo (Nm)'}, overlaying: 'y', side: 'right', showgrid: false,
        exponentformat: 'e', rangemode: 'tozero'},
      shapes: windowShapes(),
    });
    Plotly.react(div, data, layout, CONFIG);
    state.cum.dirty = false;
  }

  /* ------------------------------------------------- Gutenberg-Richter */

  function fmdStats(mags, binw, mcMode, corr, mcManual) {
    const bin = (m) => Math.round(m / binw) * binw;
    const bm = mags.map(bin);
    const counts = new Map();
    for (const m of bm) {
      const k = m.toFixed(6);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    const keys = Array.from(counts.keys()).map(Number).sort((a, b) => a - b);
    const nonc = keys.map((k) => counts.get(k.toFixed(6)));
    const cum = [];
    let acc = 0;
    for (let j = keys.length - 1; j >= 0; j--) { acc += nonc[j]; cum[j] = acc; }
    let mc;
    if (mcMode === 'manual' && Number.isFinite(mcManual)) mc = bin(mcManual);
    else {
      let jmax = 0;
      for (let j = 1; j < nonc.length; j++) if (nonc[j] > nonc[jmax]) jmax = j;
      mc = keys[jmax] + (Number.isFinite(corr) ? corr : 0);
      mc = bin(mc);
    }
    const sel = bm.filter((m) => m >= mc - 1e-9);
    const n = sel.length;
    let b = NaN, sb = NaN, a = NaN;
    if (n >= 2) {
      const mean = sel.reduce((s, v) => s + v, 0) / n;
      const denom = mean - (mc - binw / 2);
      if (denom > 0) {
        b = Math.LOG10E / denom;
        const v = sel.reduce((s, x) => s + (x - mean) ** 2, 0) / (n * (n - 1));
        sb = 2.3 * b * b * Math.sqrt(v);
        a = Math.log10(n) + b * mc;
      }
    }
    return {keys, nonc, cum, mc, n, b, sb, a};
  }

  function fmdPlot() {
    const div = el('fmd');
    const f = CG.settings.fmd;
    const data = [];
    const info = [];
    plotLayers().forEach((L, k) => {
      const mags = [];
      for (let i = 0; i < L.n; i++) if (L.vis[i] && Number.isFinite(L.mag[i])) mags.push(L.mag[i]);
      if (mags.length < 2) return;
      const s = fmdStats(mags, f.bin > 0 ? f.bin : 0.1, f.mcMode, f.corr, f.mc);
      const col = L.style.color || CG.colors.CATEGORICAL[k % CG.colors.CATEGORICAL.length];
      data.push({type: 'bar', x: s.keys, y: s.nonc, name: L.name + ' (non cum.)', marker: {color: col, opacity: 0.35},
        width: (f.bin > 0 ? f.bin : 0.1) * 0.9, hovertemplate: 'M %{x:.2f}: %{y}<extra></extra>'});
      data.push({type: 'scatter', mode: 'markers', x: s.keys, y: s.cum, name: L.name + ' (cum.)',
        marker: {color: col, size: 6, line: {width: 0.5, color: '#222'}}, hovertemplate: 'N(≥%{x:.2f}) = %{y}<extra></extra>'});
      if (Number.isFinite(s.b)) {
        const mx = s.keys[s.keys.length - 1];
        const xs = [s.mc, mx];
        data.push({type: 'scatter', mode: 'lines', x: xs, y: xs.map((m) => Math.pow(10, s.a - s.b * m)),
          line: {color: col, width: 2, dash: 'dash'}, hoverinfo: 'skip', name: 'fit'});
        data.push({type: 'scatter', mode: 'lines', x: [s.mc, s.mc], y: [0.8, s.n * 1.5],
          line: {color: col, width: 1, dash: 'dot'}, hoverinfo: 'skip', name: 'Mc'});
      }
      info.push('<b>' + CG.esc(L.name) + '</b><br>N = ' + mags.length + ', Mc = ' + s.mc.toFixed(2) +
        '<br>b = ' + (Number.isFinite(s.b) ? s.b.toFixed(2) + ' ± ' + s.sb.toFixed(2) : '—') +
        ' (N≥Mc: ' + s.n + ')<br>a = ' + (Number.isFinite(s.a) ? s.a.toFixed(2) : '—'));
    });
    const layout = baseLayout({
      barmode: 'overlay',
      xaxis: {title: {text: 'Magnitudo'}, gridcolor: '#eee'},
      yaxis: {title: {text: 'Numero di eventi'}, type: 'log', gridcolor: '#eee'},
    });
    Plotly.react(div, data, layout, CONFIG);
    document.getElementById('fmd-info').innerHTML = info.join('<hr>') ||
      '<span class="muted">Nessun evento visibile con magnitudo.</span>';
    state.fmd.dirty = false;
  }

  /* ------------------------------------------------------ P/T stereonet */

  function eqArea(trend, plunge) {
    const r = Math.SQRT2 * Math.sin((90 - plunge) * Math.PI / 360);
    const t = trend * Math.PI / 180;
    return [r * Math.sin(t), r * Math.cos(t)];
  }

  function axisVector(trend, plunge) {
    const t = trend * Math.PI / 180, p = plunge * Math.PI / 180;
    return [Math.cos(p) * Math.cos(t), Math.cos(p) * Math.sin(t), Math.sin(p)];
  }

  /* Principal eigenvector of the orientation tensor (power iteration). */
  function meanAxis(list) {
    if (!list.length) return null;
    const T = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (const [tr, pl] of list) {
      const v = axisVector(tr, pl);
      for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) T[a][b] += v[a] * v[b];
    }
    let v = [1, 0.5, 0.25];
    for (let k = 0; k < 200; k++) {
      const w = [0, 1, 2].map((a) => T[a][0] * v[0] + T[a][1] * v[1] + T[a][2] * v[2]);
      const n = Math.hypot(w[0], w[1], w[2]);
      if (!(n > 0)) return null;
      v = w.map((x) => x / n);
    }
    if (v[2] < 0) v = v.map((x) => -x);
    const trend = ((Math.atan2(v[1], v[0]) * 180 / Math.PI) % 360 + 360) % 360;
    const plunge = Math.asin(CG.clamp(v[2], -1, 1)) * 180 / Math.PI;
    return [trend, plunge];
  }

  function densityTrace(list, color) {
    const ng = 61, kappa = 20;
    const xs = [], vecs = list.map(([tr, pl]) => axisVector(tr, pl));
    for (let j = 0; j < ng; j++) xs.push(-1 + 2 * j / (ng - 1));
    const z = [];
    for (let jy = 0; jy < ng; jy++) {
      const row = [];
      for (let jx = 0; jx < ng; jx++) {
        const x = xs[jx], y = xs[jy];
        const r = Math.hypot(x, y);
        if (r > 1) { row.push(null); continue; }
        const plunge = 90 - 2 * Math.asin(CG.clamp(r / Math.SQRT2, 0, 1)) * 180 / Math.PI;
        const trend = Math.atan2(x, y) * 180 / Math.PI;
        const u = axisVector(trend, plunge);
        let d = 0;
        for (const v of vecs) d += Math.exp(kappa * (Math.abs(u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) - 1));
        row.push(d);
      }
      z.push(row);
    }
    return {type: 'contour', x: xs, y: xs, z, hoverinfo: 'skip', showscale: false,
      contours: {coloring: 'lines'}, line: {width: 1.2}, colorscale: [[0, color], [1, color]], ncontours: 6};
  }

  function ptPlot() {
    const div = el('pt');
    const o = CG.settings.pt;
    const show = ['p', 't', 'b'].filter((a) => o[a]);
    const sym = {p: 'circle', t: 'triangle-up', b: 'square'};
    const fixed = {p: '#2b6cb0', t: '#d62828', b: '#7a7a7a'};
    const names = {p: 'P', t: 'T', b: 'B'};
    const data = [];
    const shapes = [];
    // net
    const circ = (r) => ({type: 'circle', xref: 'x', yref: 'y', x0: -r, x1: r, y0: -r, y1: r,
      line: {color: r === 1 ? '#000' : '#bbb', width: r === 1 ? 1.5 : 0.8, dash: r === 1 ? 'solid' : 'dot'}});
    for (const pl of [30, 60]) shapes.push(circ(Math.SQRT2 * Math.sin((90 - pl) * Math.PI / 360)));
    for (let az = 0; az < 180; az += 30) {
      const a = az * Math.PI / 180;
      shapes.push({type: 'line', x0: -Math.sin(a), y0: -Math.cos(a), x1: Math.sin(a), y1: Math.cos(a),
        line: {color: '#ddd', width: 0.8}});
    }
    shapes.push(circ(1));
    state.pt.map = [];
    let nmt = 0;
    const lists = {p: [], t: [], b: []};
    for (const L of plotLayers()) {
      if (!L.hasMT) continue;
      const idx = [];
      for (let i = 0; i < L.n; i++) if (L.vis[i] && L.mtIdx[i] >= 0) idx.push(i);
      nmt += idx.length;
      for (const a of show) {
        const x = [], y = [], c = [], ii = [];
        for (const i of idx) {
          const k = L.mtIdx[i];
          const tr = L.mt[a + '_tr'][k], pl = L.mt[a + '_pl'][k];
          if (tr === null || pl === null) continue;
          const p = eqArea(tr, pl);
          x.push(p[0]); y.push(p[1]); c.push(o.color === 'fixed' ? fixed[a] : L.colors[i]); ii.push(i);
          lists[a].push([tr, pl]);
        }
        state.pt.map.push({L, idx: ii});
        data.push({type: 'scatter', mode: 'markers', x, y, name: names[a],
          marker: {symbol: sym[a], color: c, size: 9, line: {width: 0.7, color: '#111'}},
          hovertemplate: names[a] + '<extra>' + CG.esc(L.name) + '</extra>'});
      }
    }
    const nPoints = data.length;
    if (o.density) for (const a of show) if (lists[a].length >= 3) data.push(densityTrace(lists[a], fixed[a]));
    const info = ['N = ' + nmt + ' MT visibili'];
    if (o.mean) {
      for (const a of show) {
        const m = meanAxis(lists[a]);
        if (!m) continue;
        const p = eqArea(m[0], m[1]);
        data.push({type: 'scatter', mode: 'markers', x: [p[0]], y: [p[1]], hoverinfo: 'skip',
          marker: {symbol: 'star', size: 18, color: fixed[a], line: {width: 1.2, color: '#000'}}});
        info.push(names[a] + ' medio: ' + m[0].toFixed(0) + '° / ' + m[1].toFixed(0) + '°');
      }
    }
    state.pt.offset = 0;
    state.pt.baseShapes = shapes.slice();
    state.pt.nPoints = nPoints;
    const ax = {range: [-1.12, 1.12], showgrid: false, zeroline: false, showticklabels: false, ticks: ''};
    const layout = baseLayout({
      margin: {l: 10, r: 10, t: 10, b: 10},
      xaxis: Object.assign({}, ax, {constrain: 'domain'}),
      yaxis: Object.assign({}, ax, {scaleanchor: 'x', scaleratio: 1, constrain: 'domain'}),
      shapes: shapes.concat(hlShapes('pt')),
      annotations: [['N', 0, 1.06], ['E', 1.06, 0], ['S', 0, -1.06], ['W', -1.06, 0]].map(([t, x, y]) =>
        ({text: '<b>' + t + '</b>', x, y, showarrow: false, font: {size: 12}})),
      dragmode: false,
    });
    Plotly.react(div, data, layout, Object.assign({}, CONFIG, {scrollZoom: false}));
    if (!div._cgBound) {
      div._cgBound = true;
      div.on('plotly_hover', (ev) => {
        const p = ev.points && ev.points[0];
        if (!p || p.curveNumber >= state.pt.nPoints) return;
        const m = state.pt.map[p.curveNumber];
        if (m) CG.mapLayer.setHover({L: m.L, i: m.idx[p.pointNumber]}, 'pt');
      });
      div.on('plotly_unhover', () => CG.mapLayer.setHover(null, 'pt'));
    }
    document.getElementById('pt-info').innerHTML = info.join('<br>');
    state.pt.dirty = false;
  }

  /* ------------------------------------------------------- highlight */

  function hlShapes(tab) {
    const hv = CG.hover;
    if (!hv || !hv.L.vis[hv.i] || !hv.L.style.plots) return [];
    if (tab === 'td' || tab === 'tm') {
      if (hv.L.noTime) return [];
      const v = tab === 'td' ? hv.L.dep[hv.i] : hv.L.mag[hv.i];
      return Number.isFinite(v) ? ringShapes([[CG.plotlyDate(hv.L.t[hv.i]), v]], hv.L.r[hv.i] * PLOT_SIZE) : [];
    }
    if (tab === 'pt') {
      const k = hv.L.mtIdx[hv.i];
      if (k < 0) return [];
      const pts = [];
      for (const a of ['p', 't', 'b']) {
        if (!CG.settings.pt[a]) continue;
        const tr = hv.L.mt[a + '_tr'][k], pl = hv.L.mt[a + '_pl'][k];
        if (tr !== null && pl !== null) pts.push(eqArea(tr, pl));
      }
      return ringShapes(pts, 4.5);
    }
    return [];
  }

  function applyHighlight(tab) {
    const st = state[tab];
    const div = el(tab);
    if (!st || !st.baseShapes || !div || !div._fullLayout) return;
    Plotly.relayout(div, {shapes: st.baseShapes.concat(hlShapes(tab))}).catch(() => {});
  }

  const highlightThrottled = CG.rafThrottle((source) => {
    const tab = active();
    if (tab === source) return;
    if (['td', 'tm', 'pt'].includes(tab) && !state[tab].dirty) applyHighlight(tab);
  });

  /* --------------------------------------------------------- dispatch */

  function emptyPlot(tab, msg) {
    const div = el(tab);
    Plotly.react(div, [], baseLayout({
      uirevision: 'empty',
      xaxis: {visible: false}, yaxis: {visible: false},
      annotations: [{text: msg, xref: 'paper', yref: 'paper', x: 0.5, y: 0.5, showarrow: false,
        font: {size: 13, color: '#888'}}],
    }), CONFIG);
    if (state[tab]) { state[tab].dirty = false; state[tab].baseShapes = null; }
  }

  function render(tab) {
    if (CG.settings.panelCollapsed) return;
    if (!plotLayers().length) {
      emptyPlot(tab, CG.cats.length ? 'Nessun catalogo visibile nei grafici' :
        'Nessun dato: aggiungi un catalogo con ＋ Catalogo');
      if (tab === 'fmd') document.getElementById('fmd-info').innerHTML = '';
      if (tab === 'pt') document.getElementById('pt-info').innerHTML = '';
      return;
    }
    try {
      if (tab === 'td') timePlot('td', 'dep');
      else if (tab === 'tm') timePlot('tm', 'mag');
      else if (tab === 'cum') cumPlot();
      else if (tab === 'fmd') fmdPlot();
      else if (tab === 'pt') ptPlot();
    } catch (e) {
      CG.error(e, 'grafico');
    }
  }

  let lastRender = 0;
  let trailing = null;

  /* Called by the update pipeline. During animation the redraw rate of the
   * (expensive) plots is limited; the last state is always drawn. */
  function update(timeOnly) {
    for (const k of Object.keys(state)) state[k].dirty = true;
    const tab = active();
    if (!(tab in state)) return;
    const now = performance.now();
    const minGap = CG.timebar && CG.timebar.playing ? 180 : 0;
    clearTimeout(trailing);
    if (now - lastRender >= minGap) {
      lastRender = now;
      render(tab);
    } else {
      trailing = setTimeout(() => { lastRender = performance.now(); render(active()); }, minGap);
    }
  }

  function showTab(tab) {
    if (tab in state && state[tab].dirty) render(tab);
    resize();
  }

  function resize() {
    const tab = active();
    const div = el(tab);
    if (div && div.data) {
      try { Plotly.Plots.resize(div); } catch (e) { /* not drawn yet */ }
    }
    if (tab === 'sec') CG.sections.resize();
  }

  /* Export the current plot as SVG/PNG through Plotly (vector SVG). */
  async function toImage(tab, format, width, height) {
    const div = el(tab);
    if (!div || !div.data) throw new Error('il grafico è vuoto');
    // WebGL traces are rasterised in SVG: render a vector copy
    const data = div.data.map((t) => Object.assign({}, t, {type: t.type === 'scattergl' ? 'scatter' : t.type}));
    const tmp = document.createElement('div');
    tmp.style.position = 'fixed'; tmp.style.left = '-10000px'; tmp.style.top = '0';
    tmp.style.width = width + 'px'; tmp.style.height = height + 'px';
    document.body.appendChild(tmp);
    try {
      const layout = Object.assign({}, div.layout, {width, height, paper_bgcolor: '#fff'});
      await Plotly.newPlot(tmp, data, layout, {staticPlot: true});
      return await Plotly.toImage(tmp, {format, width, height, scale: format === 'png' ? 3 : 1});
    } finally {
      Plotly.purge(tmp);
      tmp.remove();
    }
  }

  return {update, highlight: highlightThrottled, showTab, resize, render, toImage, fmdStats, meanAxis, eqArea};
})();
