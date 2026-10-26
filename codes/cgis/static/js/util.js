/* cgis - shared helpers: API calls, notifications, time, geodesy. */
'use strict';

const CG = window.CG = {
  token: document.querySelector('meta[name="cgis-token"]').content,
  config: null,
  cats: [],          // catalogue layers (draw order: first = bottom)
  stas: [],          // station layers
  sectionList: [],  // cross-sections (module: CG.sections)
  activeSection: null,
  hover: null,       // {L, i} event under the cursor
  ready: false,
};

/* ------------------------------------------------------------------ API */

CG.api = async function (name, body) {
  let res;
  try {
    res = await fetch('/api/' + name, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CGIS-Token': CG.token},
      body: JSON.stringify(body || {}),
    });
  } catch (e) {
    throw new Error('server non raggiungibile (cgis è ancora in esecuzione?)');
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

CG.log = function (msg, level) {
  CG.api('log', {msg: String(msg), level: level || 'info'}).catch(() => {});
};

window.addEventListener('error', (e) => {
  CG.log('JS error: ' + e.message + ' (' + e.filename + ':' + e.lineno + ')', 'error');
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e.reason;
  CG.log('unhandled promise rejection: ' + (r && r.stack ? r.stack : r), 'error');
});

/* -------------------------------------------------------- notifications */

CG.toast = function (msg, kind, timeout, actions) {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || 'info');
  const span = document.createElement('span');
  span.textContent = msg;
  el.appendChild(span);
  (actions || []).forEach((a) => {
    const b = document.createElement('button');
    b.textContent = a.label;
    b.className = 'small';
    b.onclick = (ev) => { ev.stopPropagation(); a.fn(); el.remove(); };
    el.appendChild(b);
  });
  const close = document.createElement('button');
  close.className = 'x';
  close.textContent = '×';
  close.onclick = () => el.remove();
  el.appendChild(close);
  box.appendChild(el);
  const t = timeout === undefined ? (kind === 'error' ? 12000 : 5000) : timeout;
  if (t > 0) setTimeout(() => el.remove(), t);
  return el;
};

CG.error = function (e, prefix) {
  const msg = (prefix ? prefix + ': ' : '') + (e && e.message ? e.message : e);
  console.error(e);
  CG.toast(msg, 'error');
};

let busyCount = 0;
CG.busy = function (msg) {
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

CG.esc = function (s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

CG.debounce = function (fn, ms) {
  let t = null;
  const f = function (...args) {
    clearTimeout(t);
    t = setTimeout(() => { t = null; fn.apply(this, args); }, ms);
  };
  f.cancel = () => clearTimeout(t);
  f.flush = (...args) => { clearTimeout(t); fn(...args); };
  return f;
};

/* Run fn at most once per animation frame (last call wins). */
CG.rafThrottle = function (fn) {
  let pending = false;
  let lastArgs = null;
  const run = () => {
    if (!pending) return;
    pending = false;
    fn(...lastArgs);
  };
  return function (...args) {
    lastArgs = args;
    if (pending) return;
    pending = true;
    requestAnimationFrame(run);
    setTimeout(run, 60);      // animation frames are paused in hidden windows
  };
};

/* Parse a number field: null if empty, NaN if invalid. */
CG.parseNum = function (s) {
  if (s === null || s === undefined) return null;
  s = String(s).trim().replace(',', '.');
  if (s === '') return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : NaN;
};

CG.fmtNum = function (v, nd) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return Number(v).toFixed(nd === undefined ? 2 : nd);
};

CG.clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* Float64Array from a JSON list with nulls (-> NaN). */
CG.f64 = function (arr) {
  const n = arr.length;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const v = arr[i];
    out[i] = (v === null || v === undefined) ? NaN : v;
  }
  return out;
};

/* --------------------------------------------------------- time (UTC) */

const pad = (n, w) => String(n).padStart(w || 2, '0');

CG.fmtTime = function (t, withSeconds) {
  if (!Number.isFinite(t)) return '';
  const d = new Date(Math.round(t * 1000));
  let s = d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) +
    ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
  if (withSeconds !== false) s += ':' + pad(d.getUTCSeconds());
  return s;
};

CG.fmtDate = function (t) {
  if (!Number.isFinite(t)) return '';
  const d = new Date(Math.round(t * 1000));
  return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
};

/* Plotly date string (no timezone: Plotly dates are UTC-agnostic). */
CG.plotlyDate = function (t) {
  const d = new Date(Math.round(t * 1000));
  return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) +
    ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds()) +
    '.' + pad(d.getUTCMilliseconds(), 3);
};

/* Parse 'YYYY[-MM[-DD[ HH[:MM[:SS[.fff]]]]]]' (UTC) -> seconds, NaN if invalid. */
CG.parseTime = function (s) {
  if (s === null || s === undefined) return NaN;
  s = String(s).trim();
  const m = s.match(/^(-?\d{4})(?:-(\d{1,2})(?:-(\d{1,2})(?:[ T](\d{1,2})(?::(\d{1,2})(?::(\d{1,2})(\.\d+)?)?)?)?)?)?Z?$/);
  if (!m) return NaN;
  const Y = +m[1];
  const M = m[2] ? +m[2] : 1;
  const D = m[3] ? +m[3] : 1;
  const h = m[4] ? +m[4] : 0;
  const mi = m[5] ? +m[5] : 0;
  const se = m[6] ? +m[6] : 0;
  const fr = m[7] ? parseFloat(m[7]) : 0;
  if (M < 1 || M > 12 || D < 1 || D > 31 || h > 23 || mi > 59 || se > 59) return NaN;
  const ms = Date.UTC(Y, M - 1, D, h, mi, se);
  const chk = new Date(ms);
  if (chk.getUTCFullYear() !== Y || chk.getUTCMonth() !== M - 1 || chk.getUTCDate() !== D) return NaN;   // e.g. 31 April
  return ms / 1000 + fr;
};

/* Plotly axis value (date string or ms number) -> seconds. */
CG.plotlyToTime = function (v) {
  if (typeof v === 'number') return v / 1000;
  return CG.parseTime(String(v).replace(/\s+$/, ''));
};

/* ------------------------------------------------------------- geodesy */

const R_EARTH = 6371000.0;   // pyrocko earthradius
const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

CG.geo = {
  /* Spherical azimuth (deg) and great-circle distance (m), as cgis/geo.py. */
  inverse(lat1, lon1, lat2, lon2) {
    const p1 = lat1 * D2R, p2 = lat2 * D2R;
    const dp = p2 - p1, dl = (lon2 - lon1) * D2R;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const dist = 2 * Math.asin(Math.sqrt(CG.clamp(h, 0, 1))) * R_EARTH;
    const az = Math.atan2(Math.sin(dl) * Math.cos(p2),
      Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl));
    return {dist, az: ((az * R2D) % 360 + 360) % 360};
  },

  /* Spherical destination point (inverse of `inverse`). */
  dest(lat, lon, azDeg, distM) {
    const p1 = lat * D2R, l1 = lon * D2R, a = azDeg * D2R, d = distM / R_EARTH;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(a));
    const l2 = l1 + Math.atan2(Math.sin(a) * Math.sin(d) * Math.cos(p1),
      Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    return [p2 * R2D, l2 * R2D];
  },

  /* Point at (s, d) km in the section frame of A (azimuth az). */
  sectionPoint(lat1, lon1, azDeg, sKm, dKm) {
    const phi = azDeg * D2R;
    const n = sKm * Math.cos(phi) - dKm * Math.sin(phi);
    const e = sKm * Math.sin(phi) + dKm * Math.cos(phi);
    const dist = Math.hypot(n, e) * 1000;
    if (dist === 0) return [lat1, lon1];
    return CG.geo.dest(lat1, lon1, Math.atan2(e, n) * R2D, dist);
  },

  /* Ellipsoidal (WGS84) distance and azimuth by Vincenty, for measurements. */
  vincenty(lat1, lon1, lat2, lon2) {
    const a = 6378137.0, f = 1 / 298.257223563, b = a * (1 - f);
    const L = (lon2 - lon1) * D2R;
    const U1 = Math.atan((1 - f) * Math.tan(lat1 * D2R));
    const U2 = Math.atan((1 - f) * Math.tan(lat2 * D2R));
    const sinU1 = Math.sin(U1), cosU1 = Math.cos(U1);
    const sinU2 = Math.sin(U2), cosU2 = Math.cos(U2);
    let lam = L, lamP, iter = 0;
    let sinSig, cosSig, sig, sinAl, cos2Al, cos2SigM, sinLam, cosLam;
    do {
      sinLam = Math.sin(lam); cosLam = Math.cos(lam);
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
    if (iter >= 200) return CG.geo.inverse(lat1, lon1, lat2, lon2);   // antipodal
    const u2 = cos2Al * (a * a - b * b) / (b * b);
    const A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)));
    const B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)));
    const dSig = B * sinSig * (cos2SigM + B / 4 * (cosSig * (-1 + 2 * cos2SigM * cos2SigM) -
      B / 6 * cos2SigM * (-3 + 4 * sinSig * sinSig) * (-3 + 4 * cos2SigM * cos2SigM)));
    const dist = b * A * (sig - dSig);
    const az = Math.atan2(cosU2 * sinLam, cosU1 * sinU2 - sinU1 * cosU2 * cosLam);
    return {dist, az: ((az * R2D) % 360 + 360) % 360};
  },

  /* Web Mercator world pixel coordinates at zoom 0 (256 px world). */
  mercX(lon) { return (lon + 180) / 360 * 256; },
  mercY(lat) {
    const la = CG.clamp(lat, -85.0511287798, 85.0511287798) * D2R;
    return (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * 256;
  },
};

/* Ray casting point-in-polygon on [[lat, lon], ...]. */
CG.pointInPolygon = function (lat, lon, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const yi = poly[i][0], xi = poly[i][1], yj = poly[j][0], xj = poly[j][1];
    if (((yi > lat) !== (yj > lat)) &&
        (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
};

CG.fmtKm = function (m) {
  if (!Number.isFinite(m)) return '—';
  return m < 1000 ? m.toFixed(0) + ' m' : (m / 1000).toFixed(m < 10000 ? 3 : 2) + ' km';
};

CG.niceStep = function (span, target) {
  if (!(span > 0)) return 1;
  const raw = span / (target || 5);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * mag) return m * mag;
  return 10 * mag;
};

/* Stamp for default file names (local time). */
CG.stamp = function () {
  const d = new Date();
  return d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '_' +
    pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds());
};
