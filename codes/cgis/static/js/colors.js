/* cgis - colour maps (same anchors as cgis/colormaps.py) and legends. */
'use strict';

CG.colors = (function () {
  const N = 256;
  const lutCache = {};

  function hexToRgb(h) {
    h = String(h).replace('#', '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const v = parseInt(h, 16);
    if (!Number.isFinite(v) || h.length !== 6) return [128, 128, 128];
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }

  /* 256-entry LUT {rgb: Uint8Array(3N), css: [..]} interpolated in RGB. */
  function lut(name, reverse) {
    const key = name + (reverse ? '_r' : '');
    if (lutCache[key]) return lutCache[key];
    let anchors = (CG.config.cmaps[name] || CG.config.cmaps.viridis).map(hexToRgb);
    if (reverse) anchors = anchors.slice().reverse();
    const n = anchors.length - 1;
    const rgb = new Uint8Array(3 * N);
    const css = new Array(N);
    for (let k = 0; k < N; k++) {
      const pos = k / (N - 1) * n;
      const i0 = Math.min(n - 1, Math.floor(pos));
      const f = pos - i0;
      const c = [0, 1, 2].map((j) => Math.round(anchors[i0][j] * (1 - f) + anchors[i0 + 1][j] * f));
      rgb[3 * k] = c[0]; rgb[3 * k + 1] = c[1]; rgb[3 * k + 2] = c[2];
      css[k] = 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
    }
    return (lutCache[key] = {rgb, css, name, reverse});
  }

  function index(v, vmin, vmax) {
    if (!Number.isFinite(v)) return -1;
    const span = vmax - vmin;
    if (!(span > 0)) return N >> 1;
    return Math.round(CG.clamp((v - vmin) / span, 0, 1) * (N - 1));
  }

  const NAN_CSS = 'rgb(160,160,160)';
  const NAN_HEX = '#a0a0a0';

  const CATEGORICAL = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#17becf', '#bcbd22', '#7f7f7f', '#393b79',
    '#637939', '#8c6d31', '#843c39', '#7b4173'];

  const FAULTING = {
    normal: {label: 'Normale', color: '#2166ac'},
    reverse: {label: 'Inversa', color: '#d6604d'},
    strike: {label: 'Trascorrente', color: '#1b9e77'},
  };

  function cssToHex(css) {
    const m = String(css).match(/rgb\((\d+),(\d+),(\d+)\)/);
    if (!m) return css;
    return '#' + [m[1], m[2], m[3]].map((x) => (+x).toString(16).padStart(2, '0')).join('');
  }

  /* ---- time axis ticks for the colour bar ---- */
  function timeTicks(t0, t1, nmax) {
    const span = t1 - t0;
    const day = 86400;
    const steps = [
      [1, 'h'], [6, 'h'], [1, 'd'], [7, 'd'], [1, 'M'], [3, 'M'], [6, 'M'],
      [1, 'Y'], [2, 'Y'], [5, 'Y'], [10, 'Y'], [20, 'Y'], [50, 'Y']];
    const approx = {h: 3600, d: day, M: 30.44 * day, Y: 365.25 * day};
    let st = steps[steps.length - 1];
    for (const s of steps) {
      if (span / (s[0] * approx[s[1]]) <= nmax) { st = s; break; }
    }
    const out = [];
    const d0 = new Date(t0 * 1000);
    let y = d0.getUTCFullYear(), mo = d0.getUTCMonth(), dd = d0.getUTCDate(), hh = d0.getUTCHours();
    let t;
    const next = () => {
      if (st[1] === 'Y') { y = Math.floor(y / st[0]) * st[0]; t = Date.UTC(y, 0, 1) / 1000; y += st[0]; }
      else if (st[1] === 'M') { mo = Math.floor(mo / st[0]) * st[0]; t = Date.UTC(y, mo, 1) / 1000; mo += st[0]; if (mo >= 12) { y += Math.floor(mo / 12); mo %= 12; } }
      else if (st[1] === 'd') { t = Date.UTC(y, mo, dd) / 1000; const n = new Date((t + st[0] * day) * 1000); y = n.getUTCFullYear(); mo = n.getUTCMonth(); dd = n.getUTCDate(); }
      else { t = Date.UTC(y, mo, dd, hh) / 1000; const n = new Date((t + st[0] * 3600) * 1000); y = n.getUTCFullYear(); mo = n.getUTCMonth(); dd = n.getUTCDate(); hh = n.getUTCHours(); }
      return t;
    };
    for (let k = 0; k < 400; k++) {
      const tt = next();
      if (tt > t1) break;
      if (tt >= t0) out.push(tt);
    }
    const fmt = (tt) => {
      const d = new Date(tt * 1000);
      if (st[1] === 'Y') return String(d.getUTCFullYear());
      if (st[1] === 'M') return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0');
      if (st[1] === 'd') return CG.fmtDate(tt);
      return CG.fmtTime(tt, false).slice(5);
    };
    return out.map((tt) => ({v: tt, label: fmt(tt)}));
  }

  function numTicks(v0, v1, nmax) {
    const step = CG.niceStep(v1 - v0, nmax);
    const out = [];
    const start = Math.ceil(v0 / step - 1e-9) * step;
    for (let v = start; v <= v1 + 1e-9 * step; v += step) {
      const r = Math.abs(v) < 1e-12 ? 0 : v;
      out.push({v: r, label: String(+r.toFixed(6))});
    }
    return out;
  }

  /* Colour bar as an HTML string (canvas painted afterwards). */
  function colorbarHTML(id, label) {
    return '<div class="cbar"><div class="cbar-label">' + CG.esc(label) + '</div>' +
      '<canvas id="' + id + '" width="220" height="30"></canvas></div>';
  }

  function paintColorbar(canvas, L, vmin, vmax, isTime) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const W = 220, H = 30, bh = 10, padX = 12;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const w = W - 2 * padX;
    for (let x = 0; x < w; x++) {
      const k = Math.round(x / (w - 1) * 255);
      ctx.fillStyle = L.css[k];
      ctx.fillRect(padX + x, 1, 1.5, bh);
    }
    ctx.strokeStyle = '#333'; ctx.lineWidth = 0.8;
    ctx.strokeRect(padX + 0.5, 1.5, w - 1, bh - 1);
    ctx.fillStyle = '#222'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
    if (!(vmax > vmin)) return;
    const ticks = isTime ? timeTicks(vmin, vmax, 4) : numTicks(vmin, vmax, 5);
    for (const tk of ticks) {
      const x = padX + (tk.v - vmin) / (vmax - vmin) * w;
      ctx.beginPath(); ctx.moveTo(x, bh + 1); ctx.lineTo(x, bh + 4); ctx.stroke();
      ctx.fillText(tk.label, CG.clamp(x, 14, W - 14), bh + 15);
    }
  }

  return {lut, index, hexToRgb, cssToHex, NAN_CSS, NAN_HEX, CATEGORICAL, FAULTING,
    colorbarHTML, paintColorbar, timeTicks, numTicks, N};
})();
