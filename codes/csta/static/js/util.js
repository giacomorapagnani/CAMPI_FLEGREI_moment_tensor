/* csta - shared helpers: API calls, notifications, formatting, geodesy. */
'use strict';

const CS = window.CS = {
  token: document.querySelector('meta[name="csta-token"]').content,
  config: null,
  state: {catalogs: [], undo: null, redo: null},
  cats: [],            // catalogue payloads, in sidebar order
  hidden: new Set(),   // ids of hidden catalogues
  rows: [],            // one row per NET.STA of the visible catalogues
  rowByKey: new Map(),
  shown: [],           // rows passing the filters (map and table)
  sel: new Set(),      // selected NET.STA keys
  hover: null,         // key under the cursor (map or table)
  settings: {color: 'cat', labels: false, basemap: 'osm', bottomH: 300},
};

/* ------------------------------------------------------------------ API */

CS.api = async function (name, body) {
  let res;
  try {
    res = await fetch('/api/' + name, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSTA-Token': CS.token},
      body: JSON.stringify(body || {}),
    });
  } catch (e) {
    throw new Error('server non raggiungibile (csta è ancora in esecuzione?)');
  }
  let data;
  try {
    data = await res.json();
  } catch (e) {
    throw new Error('risposta non valida dal server (HTTP ' + res.status + ')');
  }
  if (!data.ok) throw new Error(data.error || ('errore HTTP ' + res.status));
  return data;
};

CS.log = function (msg, level) {
  CS.api('log', {msg: String(msg), level: level || 'info'}).catch(() => {});
};

window.addEventListener('error', (e) => {
  CS.log('JS error: ' + e.message + ' (' + e.filename + ':' + e.lineno + ')', 'error');
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e.reason;
  CS.log('unhandled promise rejection: ' + (r && r.stack ? r.stack : r), 'error');
});

/* -------------------------------------------------------- notifications */

CS.toast = function (msg, kind, timeout) {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || 'info');
  const span = document.createElement('span');
  span.textContent = msg;
  el.appendChild(span);
  const close = document.createElement('button');
  close.className = 'x';
  close.textContent = '×';
  close.onclick = () => el.remove();
  el.appendChild(close);
  box.appendChild(el);
  const t = timeout === undefined ? (kind === 'error' ? 12000 : kind === 'warn' ? 9000 : 5000) : timeout;
  if (t > 0) setTimeout(() => el.remove(), t);
  return el;
};

CS.error = function (e, prefix) {
  const msg = (prefix ? prefix + ': ' : '') + (e && e.message ? e.message : e);
  console.error(e);
  CS.toast(msg, 'error');
};

let busyCount = 0;
CS.busy = function (msg) {
  busyCount++;
  const el = document.getElementById('busy');
  document.getElementById('busy-msg').textContent = msg || '';
  // show only if the operation takes a while
  const timer = setTimeout(() => { if (busyCount > 0) el.classList.add('on'); }, 250);
  let done = false;
  return () => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    busyCount = Math.max(0, busyCount - 1);
    if (busyCount === 0) el.classList.remove('on');
  };
};

/* ----------------------------------------------------------- utilities */

CS.esc = function (s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

CS.debounce = function (fn, ms) {
  let t = null;
  const f = function (...args) {
    clearTimeout(t);
    t = setTimeout(() => { t = null; fn.apply(this, args); }, ms);
  };
  f.cancel = () => clearTimeout(t);
  return f;
};

/* Parse a number field: null if empty, NaN if invalid. */
CS.parseNum = function (s) {
  if (s === null || s === undefined) return null;
  s = String(s).trim().replace(',', '.');
  if (s === '') return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : NaN;
};

/* 'YYYY[-MM[-DD]]' (UTC) -> seconds; null if empty, NaN if invalid. */
CS.parseDate = function (s, end) {
  s = String(s || '').trim();
  if (!s) return null;
  const m = s.match(/^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$/);
  if (!m) return NaN;
  const Y = +m[1], M = m[2] ? +m[2] : (end ? 12 : 1);
  if (M < 1 || M > 12) return NaN;
  const last = new Date(Date.UTC(Y, M, 0)).getUTCDate();
  const D = m[3] ? +m[3] : (end ? last : 1);
  if (D < 1 || D > last) return NaN;
  // the end of a day / month / year is included
  return Date.UTC(Y, M - 1, D) / 1000 + (end ? 86400 - 0.001 : 0);
};

CS.fmtNum = function (v, nd) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return Number(v).toFixed(nd === undefined ? 2 : nd);
};

CS.fmtKm = function (m) {
  if (!Number.isFinite(m)) return '—';
  return m < 1000 ? m.toFixed(0) + ' m' : (m / 1000).toFixed(m < 10000 ? 3 : 2) + ' km';
};

CS.clamp = (v, a, b) => Math.max(a, Math.min(b, v));

CS.stem = function (name) {
  return String(name || 'catalogo').replace(/\.[A-Za-z0-9]{1,5}$/, '');
};

CS.dirname = function (p) {
  const i = String(p || '').lastIndexOf('/');
  return i > 0 ? p.slice(0, i) : '';
};

/* Display code of a station: NET.STA, or STA when the network is unknown. */
CS.code = (r) => (r.net ? r.net + '.' + r.sta : r.sta);

/* --------------------------------------------------------- settings */

(function () {
  try {
    const s = JSON.parse(localStorage.getItem('csta.settings') || '{}');
    Object.assign(CS.settings, s);
  } catch (e) { /* storage not available */ }
})();

CS.saveSettings = CS.debounce(() => {
  try { localStorage.setItem('csta.settings', JSON.stringify(CS.settings)); } catch (e) { /* ignore */ }
}, 300);

/* ------------------------------------------------------------- geodesy */

const R_EARTH = 6371000.0;   // same sphere as Leaflet circles
const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

CS.geo = {
  /* Spherical azimuth (deg) and great-circle distance (m). */
  inverse(lat1, lon1, lat2, lon2) {
    const p1 = lat1 * D2R, p2 = lat2 * D2R;
    const dp = p2 - p1, dl = (lon2 - lon1) * D2R;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const dist = 2 * Math.asin(Math.sqrt(CS.clamp(h, 0, 1))) * R_EARTH;
    const az = Math.atan2(Math.sin(dl) * Math.cos(p2),
      Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl));
    return {dist, az: ((az * R2D) % 360 + 360) % 360};
  },

  /* Vincenty inverse on WGS84: distance (m) and initial azimuth (deg). */
  vincenty(lat1, lon1, lat2, lon2) {
    const a = 6378137.0, f = 1 / 298.257223563, b = a * (1 - f);
    const L = (lon2 - lon1) * D2R;
    const U1 = Math.atan((1 - f) * Math.tan(lat1 * D2R));
    const U2 = Math.atan((1 - f) * Math.tan(lat2 * D2R));
    const sinU1 = Math.sin(U1), cosU1 = Math.cos(U1), sinU2 = Math.sin(U2), cosU2 = Math.cos(U2);
    let lam = L, lamP, iter = 0;
    let sinSig, cosSig, sig, sinAl, cos2Al, cos2SigM, sinLam, cosLam;
    do {
      sinLam = Math.sin(lam);
      cosLam = Math.cos(lam);
      sinSig = Math.sqrt((cosU2 * sinLam) ** 2 + (cosU1 * sinU2 - sinU1 * cosU2 * cosLam) ** 2);
      if (sinSig === 0) return {dist: 0, az: 0};
      cosSig = sinU1 * sinU2 + cosU1 * cosU2 * cosLam;
      sig = Math.atan2(sinSig, cosSig);
      sinAl = cosU1 * cosU2 * sinLam / sinSig;
      cos2Al = 1 - sinAl * sinAl;
      cos2SigM = cos2Al !== 0 ? cosSig - 2 * sinU1 * sinU2 / cos2Al : 0;
      const C = f / 16 * cos2Al * (4 + f * (4 - 3 * cos2Al));
      lamP = lam;
      lam = L + (1 - C) * f * sinAl * (sig + C * sinSig * (cos2SigM + C * cosSig * (-1 + 2 * cos2SigM * cos2SigM)));
    } while (Math.abs(lam - lamP) > 1e-12 && ++iter < 200);
    if (iter >= 200) return CS.geo.inverse(lat1, lon1, lat2, lon2);   // antipodal
    const u2 = cos2Al * (a * a - b * b) / (b * b);
    const A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)));
    const B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)));
    const dSig = B * sinSig * (cos2SigM + B / 4 * (cosSig * (-1 + 2 * cos2SigM * cos2SigM) -
      B / 6 * cos2SigM * (-3 + 4 * sinSig * sinSig) * (-3 + 4 * cos2SigM * cos2SigM)));
    const dist = b * A * (sig - dSig);
    const az = Math.atan2(cosU2 * sinLam, cosU1 * sinU2 - sinU1 * cosU2 * cosLam);
    return {dist, az: ((az * R2D) % 360 + 360) % 360};
  },
};

/* Ray casting point-in-polygon on [[lat, lon], ...]. */
CS.pointInPolygon = function (lat, lon, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const yi = poly[i][0], xi = poly[i][1], yj = poly[j][0], xj = poly[j][1];
    if (((yi > lat) !== (yj > lat)) &&
        (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
};
