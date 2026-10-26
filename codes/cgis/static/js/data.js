/* cgis - data model: layers, settings, filters, colours, sizes and the
 * update pipeline (any change calls CG.invalidate(level); one flush per frame
 * recomputes what depends on it). */
'use strict';

CG.defaults = function () {
  return {
    colorBy: 'depth',              // 'depth' | 'time'
    attr: '',                      // '' | 'faulting' | 'clvd' | 'iso' | 'tag'
    tagKey: '',
    cmapDepth: CG.config ? CG.config.default_cmaps.depth : 'RdYlBu',
    cmapTime: CG.config ? CG.config.default_cmaps.time : 'viridis',
    revDepth: false,
    revTime: false,
    rangeDepth: [null, null],      // null = automatic
    rangeTime: [null, null],
    size: {base: 4, growth: 1.8, ref: 1.0, nomag: 4, min: 1.5, max: 60},
    opacity: 0.85,
    bbType: 'deviatoric',
    bbShow: true,
    bbScale: 1.6,
    outside: 'hide',               // events outside the time window
    filters: {magMin: null, magMax: null, depMin: null, depMax: null, includeNoMag: true},
    lasso: null,                   // [[lat, lon], ...]
    time: {mode: 'all', t0: null, t1: null, speed: 1, loop: false, recentDays: null},
    basemap: 'osm',
    tab: 'td',
    panelHeight: 300,
    panelCollapsed: false,
    sidebar: true,
    fmd: {bin: 0.1, mcMode: 'maxc', corr: 0.2, mc: null},
    pt: {p: true, t: true, b: false, color: 'auto', mean: true, density: false},
  };
};

CG.settings = null;   // set in main.js once the config is known

/* --------------------------------------------------------------- layers */

let layerCounter = 0;

CG.makeCatalogLayer = function (p, options) {
  const n = p.n;
  const L = {
    kind: 'catalog',
    uid: 'L' + (++layerCounter),
    id: p.id,
    name: p.name,
    path: p.path,
    n,
    nSkipped: p.n_skipped || 0,
    lat: CG.f64(p.lat),
    lon: CG.f64(p.lon),
    dep: CG.f64(p.depth),
    t: CG.f64(p.time),
    mag: CG.f64(p.mag),
    names: p.names,
    tstr: p.tstr,
    magType: p.mag_type,
    tags: p.tags,
    info: p.info,
    mt: p.mt,
    hasMag: p.has_mag,
    hasMT: p.has_mt,
    mtIdx: new Int32Array(n).fill(-1),
    x0: new Float64Array(n),
    y0: new Float64Array(n),
    style: Object.assign({visible: true, plots: true, color: null, opacity: null,
      sizeScale: 1, beachballs: true}, options || {}),
    // derived (CG.flush)
    colors: new Array(n),
    r: new Float32Array(n),
    order: null,
    base: new Uint8Array(n),
    vis: new Uint8Array(n),
    bb: {},           // beachball type -> Map(event index -> Path2D list)
    bbPending: {},
    secProj: {},      // section uid -> {s: Float64Array, d: Float64Array}
  };
  if (p.mt) p.mt.idx.forEach((ev, k) => { L.mtIdx[ev] = k; });
  for (let i = 0; i < n; i++) {
    L.x0[i] = CG.geo.mercX(L.lon[i]);
    L.y0[i] = CG.geo.mercY(L.lat[i]);
  }
  // pre-compute tag lookups ("key:value")
  L.tagMap = null;
  if (L.tags) {
    L.tagMap = new Array(n);
    for (let i = 0; i < n; i++) {
      const tg = L.tags[i];
      if (!tg) continue;
      const m = {};
      for (const s of tg) {
        const k = s.indexOf(':');
        const key = k >= 0 ? s.slice(0, k).trim() : s.trim();
        if (!(key in m)) m[key] = k >= 0 ? s.slice(k + 1).trim() : '';
      }
      L.tagMap[i] = m;
    }
  }
  return L;
};

CG.makeStationLayer = function (p, options) {
  return {
    kind: 'stations',
    uid: 'L' + (++layerCounter),
    id: p.id,
    name: p.name,
    path: p.path,
    n: p.n,
    stations: p.stations,
    classLabels: p.class_labels,
    classColors: p.class_colors,
    style: Object.assign({visible: true, labels: false}, options || {}),
    markers: null,
    secProj: {},
  };
};

CG.layerOpacity = (L) => (L.style.opacity === null || L.style.opacity === undefined)
  ? CG.settings.opacity : L.style.opacity;

/* ------------------------------------------------------- symbol sizes */

CG.radius = function (m, scale) {
  const s = CG.settings.size;
  let r;
  if (!Number.isFinite(m)) r = s.nomag;
  else r = CG.clamp(s.base * Math.pow(s.growth, m - s.ref), s.min, s.max);
  return r * (scale || 1);
};

/* -------------------------------------------------------------- colours */

CG.colorState = {lut: null, vmin: 0, vmax: 1, isTime: false, label: '', categories: null};

function autoRange(values) {
  let lo = Infinity, hi = -Infinity;
  for (const L of CG.cats) {
    if (!L.style.visible || L.style.color) continue;
    const arr = values(L);
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo)) return [0, 1];
  if (lo === hi) return [lo - 0.5, hi + 0.5];
  return [lo, hi];
}

CG.colorRange = function () {
  const st = CG.settings;
  const isTime = st.colorBy === 'time';
  const manual = isTime ? st.rangeTime : st.rangeDepth;
  const auto = autoRange((L) => isTime ? L.t : L.dep);
  let vmin = manual[0] === null ? auto[0] : manual[0];
  let vmax = manual[1] === null ? auto[1] : manual[1];
  if (!(vmax > vmin)) vmax = vmin + (isTime ? 86400 : 1);
  return {vmin, vmax, autoMin: auto[0], autoMax: auto[1]};
};

function faultClass(rake) {
  if (!Number.isFinite(rake)) return null;
  if (rake > 30 && rake < 150) return 'reverse';
  if (rake < -30 && rake > -150) return 'normal';
  return 'strike';
}

/* Colour each event of each layer according to the settings. */
CG.computeColors = function () {
  const st = CG.settings;
  const isTime = st.colorBy === 'time';
  const lut = CG.colors.lut(isTime ? st.cmapTime : st.cmapDepth, isTime ? st.revTime : st.revDepth);
  const rng = CG.colorRange();
  const cs = CG.colorState;
  cs.lut = lut; cs.vmin = rng.vmin; cs.vmax = rng.vmax; cs.isTime = isTime;
  cs.label = isTime ? 'Origin time' : 'Profondità (km)';
  cs.categories = null;
  cs.attr = st.attr;
  cs.attrRange = null;

  let cats = null;
  if (st.attr === 'faulting') {
    cats = Object.keys(CG.colors.FAULTING).map((k) => ({key: k, label: CG.colors.FAULTING[k].label, color: CG.colors.FAULTING[k].color}));
  } else if (st.attr === 'tag') {
    const vals = new Map();
    for (const L of CG.cats) {
      if (!L.tagMap || !L.style.visible) continue;
      for (let i = 0; i < L.n; i++) {
        const m = L.tagMap[i];
        if (m && st.tagKey in m && !vals.has(m[st.tagKey])) vals.set(m[st.tagKey], vals.size);
      }
    }
    const keys = Array.from(vals.keys());
    if (keys.every((k) => k.trim() !== '' && Number.isFinite(Number(k)))) keys.sort((a, b) => Number(a) - Number(b));
    else keys.sort((a, b) => a.localeCompare(b, undefined, {numeric: true}));
    cats = keys.map((k, j) => ({key: k, label: k, color: CG.colors.CATEGORICAL[j % CG.colors.CATEGORICAL.length]}));
  }
  if (cats) {
    cs.categories = cats;
    cs.label = st.attr === 'faulting' ? 'Stile di fagliazione' : 'Tag ' + st.tagKey;
  }
  const catColor = cats ? new Map(cats.map((c) => [c.key, c.color])) : null;
  if (st.attr === 'clvd' || st.attr === 'iso') {
    cs.attrRange = st.attr === 'clvd' ? [0, 100] : [-100, 100];
    cs.label = st.attr === 'clvd' ? '% CLVD' : '% ISO';
  }

  for (const L of CG.cats) {
    const fixed = L.style.color;
    for (let i = 0; i < L.n; i++) {
      let c;
      if (fixed) {
        c = fixed;
      } else if (st.attr === 'faulting') {
        const k = L.mtIdx[i];
        const cl = k >= 0 ? faultClass(L.mt.r1[k]) : null;
        c = cl ? catColor.get(cl) : CG.colors.NAN_HEX;
      } else if (st.attr === 'tag') {
        const m = L.tagMap ? L.tagMap[i] : null;
        c = (m && st.tagKey in m) ? catColor.get(m[st.tagKey]) : CG.colors.NAN_HEX;
      } else if (st.attr === 'clvd' || st.attr === 'iso') {
        const k = L.mtIdx[i];
        let v = NaN;
        if (k >= 0) v = st.attr === 'clvd' ? Math.abs(L.mt.clvd[k]) : L.mt.iso[k];
        const j = CG.colors.index(v === null ? NaN : v, cs.attrRange[0], cs.attrRange[1]);
        c = j < 0 ? CG.colors.NAN_HEX : lut.css[j];
      } else {
        const v = isTime ? L.t[i] : L.dep[i];
        const j = CG.colors.index(v, rng.vmin, rng.vmax);
        c = j < 0 ? CG.colors.NAN_CSS : lut.css[j];
      }
      L.colors[i] = c;
    }
  }
};

/* Sizes and draw order (large first, so that small events stay visible). */
CG.computeSizes = function () {
  for (const L of CG.cats) {
    const sc = L.style.sizeScale || 1;
    for (let i = 0; i < L.n; i++) L.r[i] = CG.radius(L.mag[i], sc);
    const order = new Uint32Array(L.n);
    for (let i = 0; i < L.n; i++) order[i] = i;
    const r = L.r;
    order.sort((a, b) => r[b] - r[a]);
    L.order = order;
  }
};

/* ------------------------------------------------------------- filters */

CG.timeDomain = function () {
  let lo = Infinity, hi = -Infinity;
  for (const L of CG.cats) {
    if (!L.style.visible) continue;
    for (let i = 0; i < L.n; i++) {
      const t = L.t[i];
      if (t < lo) lo = t;
      if (t > hi) hi = t;
    }
  }
  if (!Number.isFinite(lo)) return null;
  if (hi === lo) { lo -= 43200; hi += 43200; }
  return [lo, hi];
};

CG.computeBase = function () {
  const f = CG.settings.filters;
  const lasso = CG.settings.lasso;
  let bbox = null;
  if (lasso && lasso.length >= 3) {
    bbox = [Infinity, -Infinity, Infinity, -Infinity];
    for (const p of lasso) {
      bbox[0] = Math.min(bbox[0], p[0]); bbox[1] = Math.max(bbox[1], p[0]);
      bbox[2] = Math.min(bbox[2], p[1]); bbox[3] = Math.max(bbox[3], p[1]);
    }
  }
  for (const L of CG.cats) {
    const base = L.base;
    if (!L.style.visible) { base.fill(0); continue; }
    for (let i = 0; i < L.n; i++) {
      let ok = 1;
      const m = L.mag[i];
      if (Number.isFinite(m)) {
        if (f.magMin !== null && m < f.magMin) ok = 0;
        else if (f.magMax !== null && m > f.magMax) ok = 0;
      } else if (!f.includeNoMag) {
        ok = 0;
      }
      if (ok) {
        const d = L.dep[i];
        if (f.depMin !== null && !(d >= f.depMin)) ok = 0;
        else if (f.depMax !== null && !(d <= f.depMax)) ok = 0;
      }
      if (ok && bbox) {
        const la = L.lat[i], lo = L.lon[i];
        if (la < bbox[0] || la > bbox[1] || lo < bbox[2] || lo > bbox[3] ||
            !CG.pointInPolygon(la, lo, lasso)) ok = 0;
      }
      base[i] = ok;
    }
  }
};

/* Current time window [t0, t1] (null when everything is shown). */
CG.timeWindow = function () {
  const tm = CG.settings.time;
  if (tm.mode === 'all' || tm.t1 === null) return null;
  if (tm.mode === 'cumulative') return [-Infinity, tm.t1];
  return [tm.t0, tm.t1];
};

CG.recentSeconds = function () {
  const tm = CG.settings.time;
  if (tm.recentDays !== null && tm.recentDays !== undefined && tm.recentDays >= 0) return tm.recentDays * 86400;
  const dom = CG.timeDomain();
  return dom ? 0.02 * (dom[1] - dom[0]) : 0;
};

CG.computeVis = function () {
  const w = CG.timeWindow();
  let nvis = 0, nbase = 0, ntot = 0;
  for (const L of CG.cats) {
    const base = L.base, vis = L.vis, t = L.t;
    ntot += L.n;
    for (let i = 0; i < L.n; i++) {
      const v = base[i] && (!w || (t[i] >= w[0] && t[i] <= w[1])) ? 1 : 0;
      vis[i] = v;
      nvis += v;
      nbase += base[i];
    }
  }
  CG.counts = {nvis, nbase, ntot};
};

/* Indices of the visible events of a layer (optionally with MT only). */
CG.visibleIndices = function (L, mtOnly) {
  const out = [];
  for (let i = 0; i < L.n; i++) {
    if (L.vis[i] && (!mtOnly || L.mtIdx[i] >= 0)) out.push(i);
  }
  return out;
};

/* ------------------------------------------------------ update pipeline */

const LEVELS = ['data', 'style', 'filter', 'time', 'draw'];
const pending = new Set();
let scheduled = false;
let plotsTimeOnly = true;

CG.invalidate = function (level) {
  pending.add(level);
  if (level !== 'time' && level !== 'draw' && level !== 'hover') plotsTimeOnly = false;
  if (!scheduled) {
    scheduled = true;
    // animation frame normally; the timeout covers hidden/minimised windows
    // where animation frames are paused
    const run = () => { if (scheduled) CG.flush(); };
    requestAnimationFrame(run);
    setTimeout(run, 120);
  }
};

CG.flush = function () {
  scheduled = false;
  if (!CG.ready) return;
  const p = new Set(pending);
  pending.clear();
  const timeOnly = plotsTimeOnly;
  plotsTimeOnly = true;
  const has = (lv) => {
    const k = LEVELS.indexOf(lv);
    for (const x of p) if (LEVELS.indexOf(x) <= k && LEVELS.indexOf(x) >= 0) return true;
    return false;
  };
  try {
    if (p.has('data')) {
      CG.timebar.updateDomain();
    }
    if (has('style')) {
      CG.computeColors();
      CG.computeSizes();
      CG.ui.updateLegend();
    }
    if (has('filter')) CG.computeBase();
    if (has('time')) {
      CG.computeVis();
      CG.ui.updateCounts();
    }
    CG.mapLayer.redraw();
    if (has('time')) {
      CG.plots.update(timeOnly);
      CG.sections.update(timeOnly);
    }
    if (p.has('data') || p.has('style') || p.has('filter') || p.has('time')) CG.session.changed();
  } catch (e) {
    CG.error(e, 'aggiornamento');
  }
};
