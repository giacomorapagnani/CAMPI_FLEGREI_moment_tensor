/* cgis - time slider: all / moving window / cumulative, with play. */
'use strict';

CG.timebar = (function () {
  let domain = null;          // [tmin, tmax] of the visible catalogues
  let playing = false;
  let raf = null;
  let lastFrame = 0;
  const $ = (id) => document.getElementById(id);
  const ANIM_SECONDS = 30;     // duration of a full sweep at speed x1

  function tm() { return CG.settings.time; }

  function pos(t) {
    if (!domain) return 0;
    return CG.clamp((t - domain[0]) / (domain[1] - domain[0]), 0, 1);
  }

  function timeAt(frac) {
    return domain[0] + CG.clamp(frac, 0, 1) * (domain[1] - domain[0]);
  }

  /* Keep the window inside the domain and consistent with the mode. */
  function normalize() {
    const s = tm();
    if (!domain) return;
    const span = domain[1] - domain[0];
    if (s.mode === 'all') return;
    if (s.t1 === null || !Number.isFinite(s.t1)) s.t1 = s.mode === 'cumulative' ? domain[0] + 0.5 * span : domain[0] + 0.2 * span;
    if (s.mode === 'window') {
      if (s.t0 === null || !Number.isFinite(s.t0) || s.t0 >= s.t1) s.t0 = Math.max(domain[0], s.t1 - 0.2 * span);
    }
    s.t1 = CG.clamp(s.t1, domain[0], domain[1]);
    if (s.t0 !== null) s.t0 = CG.clamp(s.t0, domain[0], s.t1);
  }

  function render() {
    const s = tm();
    const bar = $('tb-slider');
    const enabled = s.mode !== 'all' && !!domain;
    bar.classList.toggle('disabled', !enabled);
    bar.classList.toggle('cumulative', s.mode === 'cumulative');
    $('tb-play').disabled = !enabled;
    $('tb-t0').disabled = !enabled || s.mode !== 'window';
    $('tb-t1').disabled = !enabled;
    $('tb-mode').value = s.mode;
    $('tb-speed').value = String(s.speed);
    $('tb-loop').checked = !!s.loop;
    $('tb-recent-l').style.display = s.mode === 'cumulative' ? '' : 'none';
    const h0 = bar.querySelector('.h0'), h1 = bar.querySelector('.h1'), rg = bar.querySelector('.range');
    if (!enabled) {
      h0.style.left = '0%'; h1.style.left = '100%';
      rg.style.left = '0%'; rg.style.width = '100%';
      $('tb-t0').value = domain ? CG.fmtTime(domain[0], false) : '';
      $('tb-t1').value = domain ? CG.fmtTime(domain[1], false) : '';
      return;
    }
    const p0 = s.mode === 'cumulative' ? 0 : pos(s.t0);
    const p1 = pos(s.t1);
    h0.style.left = (100 * p0) + '%';
    h1.style.left = (100 * p1) + '%';
    rg.style.left = (100 * p0) + '%';
    rg.style.width = (100 * (p1 - p0)) + '%';
    if (document.activeElement !== $('tb-t0')) $('tb-t0').value = CG.fmtTime(s.mode === 'cumulative' ? domain[0] : s.t0, false);
    if (document.activeElement !== $('tb-t1')) $('tb-t1').value = CG.fmtTime(s.t1, false);
    $('tb-play').textContent = playing ? '❚❚' : '▶';
  }

  function changed() {
    render();
    CG.invalidate('time');
  }

  /* ------------------------------------------------------------ drag */

  function initDrag() {
    const bar = $('tb-slider');
    let drag = null;
    bar.addEventListener('pointerdown', (e) => {
      const s = tm();
      if (s.mode === 'all' || !domain) return;
      stop();
      const rect = bar.getBoundingClientRect();
      const frac = (e.clientX - rect.left) / rect.width;
      const t = timeAt(frac);
      let what;
      if (e.target.classList.contains('h0')) what = 'h0';
      else if (e.target.classList.contains('h1')) what = 'h1';
      else if (e.target.classList.contains('range') && s.mode === 'window') what = 'range';
      else {
        // click on the track: move the nearest handle there
        if (s.mode === 'cumulative' || Math.abs(t - s.t1) <= Math.abs(t - s.t0)) { s.t1 = t; what = 'h1'; }
        else { s.t0 = t; what = 'h0'; }
        normalize(); changed();
      }
      drag = {what, x0: e.clientX, t0: s.t0, t1: s.t1, w: rect.width};
      bar.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    bar.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const s = tm();
      const dt = (e.clientX - drag.x0) / drag.w * (domain[1] - domain[0]);
      if (drag.what === 'h1') s.t1 = CG.clamp(drag.t1 + dt, s.mode === 'window' ? s.t0 + 1 : domain[0], domain[1]);
      else if (drag.what === 'h0') s.t0 = CG.clamp(drag.t0 + dt, domain[0], s.t1 - 1);
      else if (drag.what === 'range') {
        const len = drag.t1 - drag.t0;
        let a = drag.t0 + dt;
        a = CG.clamp(a, domain[0], domain[1] - len);
        s.t0 = a; s.t1 = a + len;
      }
      changed();
    });
    const end = () => { if (drag) { drag = null; CG.session.changed(); } };
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
  }

  /* ------------------------------------------------------------ play */

  function frame(now) {
    if (!playing) return;
    const s = tm();
    const dtWall = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 0;
    lastFrame = now;
    const span = domain[1] - domain[0];
    const adv = span / ANIM_SECONDS * s.speed * dtWall;
    if (s.mode === 'window') {
      const len = s.t1 - s.t0;
      if (s.t1 + adv >= domain[1]) {
        if (s.loop) { s.t0 = domain[0]; s.t1 = domain[0] + len; }
        else { s.t1 = domain[1]; s.t0 = domain[1] - len; changed(); stop(); return; }
      } else { s.t0 += adv; s.t1 += adv; }
    } else {
      if (s.t1 + adv >= domain[1]) {
        if (s.loop) s.t1 = domain[0];
        else { s.t1 = domain[1]; changed(); stop(); return; }
      } else s.t1 += adv;
    }
    changed();
    raf = requestAnimationFrame(frame);
  }

  function play() {
    const s = tm();
    if (!domain) return;
    if (s.mode === 'all') { s.mode = 'cumulative'; s.t1 = domain[0]; normalize(); }
    // restart from the beginning when at the end
    if (s.t1 >= domain[1] - 1e-6) {
      if (s.mode === 'window') { const len = s.t1 - s.t0; s.t0 = domain[0]; s.t1 = domain[0] + len; }
      else s.t1 = domain[0];
    }
    playing = true;
    lastFrame = 0;
    render();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    if (!playing) return;
    playing = false;
    cancelAnimationFrame(raf);
    render();
    CG.invalidate('time');   // final full-quality update of the plots
    CG.session.changed();
  }

  /* ------------------------------------------------------------ init */

  function init() {
    initDrag();
    $('tb-mode').onchange = (e) => {
      stop();
      const s = tm();
      s.mode = e.target.value;
      normalize();
      changed();
      CG.session.changed();
    };
    $('tb-play').onclick = () => (playing ? stop() : play());
    $('tb-speed').onchange = (e) => { tm().speed = +e.target.value; CG.session.changed(); };
    $('tb-loop').onchange = (e) => { tm().loop = e.target.checked; CG.session.changed(); };
    const timeInput = (which) => () => {
      const el = $(which === 't0' ? 'tb-t0' : 'tb-t1');
      const t = CG.parseTime(el.value);
      if (!Number.isFinite(t)) { CG.toast('Data non valida: usa AAAA-MM-GG [hh:mm[:ss]] (UTC)', 'error'); render(); return; }
      const s = tm();
      if (which === 't0') s.t0 = t; else s.t1 = t;
      if (s.mode === 'window' && s.t0 >= s.t1) {
        if (which === 't0') s.t1 = Math.min(domain[1], s.t0 + 86400); else s.t0 = Math.max(domain[0], s.t1 - 86400);
      }
      normalize();
      el.blur();
      changed();
      CG.session.changed();
    };
    for (const w of ['t0', 't1']) {
      const el = $('tb-' + w);
      el.onchange = timeInput(w);
      el.onkeydown = (e) => { if (e.key === 'Enter') timeInput(w)(); };
    }
    $('tb-recent').onchange = (e) => {
      const v = CG.parseNum(e.target.value);
      if (Number.isNaN(v) || (v !== null && v < 0)) { CG.toast('Valore non valido', 'error'); return; }
      tm().recentDays = v;
      CG.invalidate('draw');
      CG.session.changed();
    };
    render();
  }

  /* Recompute the time domain when catalogues change. */
  function updateDomain() {
    const d = CG.timeDomain();
    const old = domain;
    domain = d;
    if (!d) { stop(); render(); return; }
    const s = tm();
    if (old && s.mode !== 'all') {
      // keep the window where it was (clamped)
      normalize();
    } else {
      normalize();
    }
    render();
  }

  function setWindow(t0, t1, mode) {
    const s = tm();
    stop();
    s.mode = mode || s.mode;
    if (s.mode === 'all') s.mode = 'window';
    s.t0 = t0; s.t1 = t1;
    normalize();
    changed();
    CG.session.changed();
  }

  return {
    init, updateDomain, render, setWindow, stop,
    togglePlay() { if (playing) stop(); else play(); },
    get playing() { return playing; },
    get domain() { return domain; },
  };
})();
