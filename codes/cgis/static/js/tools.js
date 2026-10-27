/* cgis - interactive map tools: distance measurement (D), new
 * cross-section (X), lasso selection (L), export area rectangle. */
'use strict';

CG.tools = (function () {
  let mode = null;
  let handlers = null;
  const hintEl = () => document.getElementById('mode-hint');
  const measureBox = () => document.getElementById('measure-box');

  const HINTS = {
    measure: 'Misura: clic per aggiungere punti · doppio clic / Invio per finire · Esc per cancellare',
    section: 'Sezione: clic sul punto A, poi clic sul punto B · Esc per annullare',
    lasso: 'Lazo: clic per i vertici · doppio clic / Invio per chiudere · Esc per annullare',
    rect: 'Area figura: trascina un rettangolo sulla mappa · Esc per annullare',
  };

  function setMode(m, opts) {
    if (mode) cancel(true);
    if (!m) return;
    const map = CG.mapLayer.map;
    mode = m;
    document.getElementById('map').classList.add('cg-crosshair');
    hintEl().textContent = HINTS[m];
    hintEl().style.display = 'block';
    map.doubleClickZoom.disable();
    CG.mapLayer.hideTooltip();
    map.closePopup();
    document.querySelectorAll('#toolbar .tool').forEach((b) => b.classList.remove('on'));
    const btn = {measure: 'btn-measure', section: 'btn-section', lasso: 'btn-lasso'}[m];
    if (btn) document.getElementById(btn).classList.add('on');
    handlers = ({measure: measureTool, section: sectionTool, lasso: lassoTool, rect: rectTool})[m](map, opts || {});
  }

  /* End the current mode. ``keep`` leaves the result on the map. */
  function cancel(keep) {
    const map = CG.mapLayer.map;
    if (handlers) {
      handlers.off(keep);
      handlers = null;
    }
    mode = null;
    document.getElementById('map').classList.remove('cg-crosshair');
    hintEl().style.display = 'none';
    map.doubleClickZoom.enable();
    map.dragging.enable();
    document.querySelectorAll('#toolbar .tool').forEach((b) => b.classList.remove('on'));
  }

  function bind(map, events) {
    for (const [k, f] of Object.entries(events)) map.on(k, f);
    return () => { for (const [k, f] of Object.entries(events)) map.off(k, f); };
  }

  const samePixel = (map, a, b) => map.latLngToContainerPoint(a).distanceTo(map.latLngToContainerPoint(b)) < 4;

  /* ------------------------------------------------------------ measure */

  let measureLayers = null;

  function clearMeasure() {
    if (measureLayers) { measureLayers.remove(); measureLayers = null; }
    measureBox().style.display = 'none';
  }

  function measureTool(map) {
    clearMeasure();
    const group = L.layerGroup().addTo(map);
    measureLayers = group;
    const pts = [];
    const line = L.polyline([], {color: '#d00', weight: 2.5, renderer: CG.toolsRenderer}).addTo(group);
    const rubber = L.polyline([], {color: '#d00', weight: 1.5, dashArray: '5,5', renderer: CG.toolsRenderer}).addTo(group);
    // circle centred on the first point, radius = first segment
    let circle = null;
    let finished = false;

    function setCircle(ll) {
      const c = pts[0];
      // spherical radius: the same Earth model Leaflet uses to draw the circle,
      // so that the second point lies exactly on it
      const r = CG.geo.inverse(c.lat, c.lng, ll.lat, ll.lng).dist;
      if (!(r > 0)) return;
      if (!circle) {
        circle = L.circle(c, {radius: r, color: '#d00', weight: 1.5, dashArray: '6,5', fill: false,
          interactive: false, renderer: CG.toolsRenderer}).addTo(group);
      } else {
        circle.setRadius(r);
      }
    }

    function info(extra) {
      let total = 0;
      const segs = [];
      for (let k = 1; k < pts.length; k++) {
        const g = CG.geo.vincenty(pts[k - 1].lat, pts[k - 1].lng, pts[k].lat, pts[k].lng);
        total += g.dist;
        segs.push(g);
      }
      let html = '<b>Distanza</b> (WGS84)<br>Totale: <b>' + CG.fmtKm(total) + '</b>';
      if (segs.length) {
        const g = segs[segs.length - 1];
        html += '<br>Ultimo tratto: ' + CG.fmtKm(g.dist) + ' · az. ' + g.az.toFixed(1) + '°';
      }
      if (segs.length) html += '<br>Raggio (1° tratto): ' + CG.fmtKm(segs[0].dist);
      if (extra) html += '<br><span class="muted">al cursore: ' + CG.fmtKm(extra.dist) + ' · az. ' + extra.az.toFixed(1) + '° · tot. ' + CG.fmtKm(total + extra.dist) + '</span>';
      html += '<br><span class="muted">' + Math.max(0, pts.length - 1) + ' tratti · Esc/D per cancellare</span>';
      measureBox().innerHTML = html;
      measureBox().style.display = 'block';
      return total;
    }

    function addPoint(ll) {
      if (pts.length && samePixel(map, pts[pts.length - 1], ll)) return;
      pts.push(ll);
      line.setLatLngs(pts);
      if (pts.length === 2) setCircle(ll);
      const total = info();
      L.circleMarker(ll, {radius: 3.5, color: '#d00', weight: 2, fillColor: '#fff', fillOpacity: 1,
        renderer: CG.toolsRenderer, interactive: false}).addTo(group)
        .bindTooltip(pts.length > 1 ? CG.fmtKm(total) : 'start', {permanent: true, direction: 'right', className: 'cg-measure-label', offset: [6, 0]});
    }

    function finish() {
      finished = true;
      rubber.setLatLngs([]);
      info();
      cancel(true);
    }

    const off = bind(map, {
      click: (e) => { if (!finished) addPoint(e.latlng); },
      dblclick: (e) => { if (!finished) { addPoint(e.latlng); finish(); } },
      mousemove: (e) => {
        if (finished || !pts.length) return;
        const last = pts[pts.length - 1];
        rubber.setLatLngs([last, e.latlng]);
        if (pts.length === 1) setCircle(e.latlng);
        info(CG.geo.vincenty(last.lat, last.lng, e.latlng.lat, e.latlng.lng));
      },
    });
    return {
      off(keep) {
        off();
        rubber.setLatLngs([]);
        if (!keep || pts.length < 2) clearMeasure();
      },
      enter: () => { if (pts.length >= 2) finish(); },
    };
  }

  /* ------------------------------------------------------------ section */

  function sectionTool(map) {
    const group = L.layerGroup().addTo(map);
    let A = null;
    const rubber = L.polyline([], {color: '#000', weight: 2, dashArray: '6,4', renderer: CG.toolsRenderer}).addTo(group);
    const label = L.tooltip({permanent: true, direction: 'right', className: 'cg-measure-label', offset: [10, 0]});
    const off = bind(map, {
      click: (e) => {
        if (!A) {
          A = e.latlng;
          L.circleMarker(A, {radius: 4, color: '#000', fillColor: '#fff', fillOpacity: 1, weight: 2,
            renderer: CG.toolsRenderer, interactive: false}).addTo(group);
          return;
        }
        if (samePixel(map, A, e.latlng)) return;
        const B = e.latlng;
        cancel(false);
        CG.sections.create(A.lat, A.lng, B.lat, B.lng);
      },
      mousemove: (e) => {
        if (!A) return;
        rubber.setLatLngs([A, e.latlng]);
        const g = CG.geo.inverse(A.lat, A.lng, e.latlng.lat, e.latlng.lng);
        label.setLatLng(e.latlng).setContent(CG.fmtKm(g.dist) + ' · az. ' + g.az.toFixed(1) + '°');
        if (!map.hasLayer(label)) label.addTo(map);
      },
    });
    return {off() { off(); group.remove(); if (map.hasLayer(label)) map.removeLayer(label); }, enter() {}};
  }

  /* -------------------------------------------------------------- lasso */

  let lassoLayer = null;

  function drawLasso() {
    const map = CG.mapLayer.map;
    if (lassoLayer) { lassoLayer.remove(); lassoLayer = null; }
    const poly = CG.settings.lasso;
    if (poly && poly.length >= 3) {
      lassoLayer = L.polygon(poly, {color: '#7b2cbf', weight: 2, dashArray: '6,4', fillOpacity: 0.04,
        renderer: CG.toolsRenderer, interactive: false}).addTo(map);
    }
  }

  function lassoTool(map) {
    const pts = [];
    const group = L.layerGroup().addTo(map);
    const poly = L.polyline([], {color: '#7b2cbf', weight: 2, renderer: CG.toolsRenderer}).addTo(group);
    const rubber = L.polyline([], {color: '#7b2cbf', weight: 1.5, dashArray: '4,4', renderer: CG.toolsRenderer}).addTo(group);
    let done = false;

    function close() {
      if (done) return;
      done = true;
      if (pts.length >= 3) {
        CG.settings.lasso = pts.map((p) => [p.lat, p.lng]);
        drawLasso();
        CG.ui.updateLassoInfo();
        CG.invalidate('filter');
      } else {
        CG.toast('Il lazo richiede almeno 3 vertici', 'info');
      }
      cancel(true);
    }

    const off = bind(map, {
      click: (e) => {
        if (done) return;
        if (pts.length && samePixel(map, pts[pts.length - 1], e.latlng)) return;
        pts.push(e.latlng);
        poly.setLatLngs(pts);
      },
      dblclick: () => close(),
      mousemove: (e) => {
        if (done || !pts.length) return;
        rubber.setLatLngs([pts[pts.length - 1], e.latlng, pts[0]]);
      },
    });
    return {off() { off(); group.remove(); }, enter: close};
  }

  /* --------------------------------------------- export area rectangle */

  function rectTool(map, opts) {
    map.dragging.disable();
    let start = null;
    let rect = null;
    const off = bind(map, {
      mousedown: (e) => {
        start = e.latlng;
        rect = L.rectangle([start, start], {color: '#0066cc', weight: 2, dashArray: '5,4',
          fillOpacity: 0.08, renderer: CG.toolsRenderer, interactive: false}).addTo(map);
      },
      mousemove: (e) => { if (start && rect) rect.setBounds([start, e.latlng]); },
      mouseup: (e) => {
        if (!start) return;
        const b = L.latLngBounds(start, e.latlng);
        if (rect) rect.remove();
        rect = null;
        start = null;
        const sz = map.latLngToContainerPoint(b.getNorthEast()).subtract(map.latLngToContainerPoint(b.getSouthWest()));
        cancel(false);
        if (Math.abs(sz.x) < 10 || Math.abs(sz.y) < 10) {
          CG.toast('Area troppo piccola: trascina un rettangolo', 'info');
          if (opts.done) opts.done(null);
          return;
        }
        if (opts.done) opts.done(b);
      },
    });
    return {
      off() { off(); if (rect) rect.remove(); map.dragging.enable(); },
      enter() {},
      cancelled: () => { if (opts.done) opts.done(null); },
    };
  }

  /* ----------------------------------------------------------- keyboard */

  function isTyping(e) {
    const t = e.target;
    if (!t) return false;
    if (t.tagName === 'INPUT') return !['checkbox', 'radio', 'range', 'color', 'button'].includes(t.type);
    return t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable;
  }

  function onKey(e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape') {
      if (CG.ui.closeModal()) { e.preventDefault(); return; }
      if (mode) {
        const h = handlers;
        cancel(false);
        if (h && h.cancelled) h.cancelled();
      } else {
        clearMeasure();
      }
      CG.mapLayer.map.closePopup();
      return;
    }
    if (isTyping(e) || CG.ui.modalOpen()) return;
    const k = e.key.toLowerCase();
    if (k === 'enter' && handlers) { handlers.enter(); e.preventDefault(); return; }
    if (k === 'd') { toggle('measure'); e.preventDefault(); }
    else if (k === 'x') { toggle('section'); e.preventDefault(); }
    else if (k === 'l') { toggle('lasso'); e.preventDefault(); }
    else if (k === 's') { CG.ui.openMapExport(); e.preventDefault(); }
    else if (k === 'c') { CG.ui.setColorBy(CG.settings.colorBy === 'depth' ? 'time' : 'depth'); e.preventDefault(); }
    else if (k === ' ') {
      if (document.activeElement && document.activeElement.tagName === 'BUTTON') document.activeElement.blur();
      CG.timebar.togglePlay();
      e.preventDefault();
    }
    else if (k === '?' || k === 'h') { CG.ui.showHelp(); e.preventDefault(); }
    else if (k === '[' || k === ']') {
      const s = CG.activeSection;
      if (s) {
        const f = k === ']' ? 1.25 : 0.8;
        CG.sections.setWidth(s, s.width * f);
        e.preventDefault();
      }
    }
  }

  function toggle(m) {
    if (mode === m) {
      cancel(m === 'measure' ? false : false);
      if (m === 'measure') clearMeasure();
    } else {
      if (m === 'measure' && measureLayers && !mode) { clearMeasure(); }
      setMode(m);
    }
  }

  function init() {
    document.addEventListener('keydown', onKey);
    document.getElementById('btn-measure').onclick = () => toggle('measure');
    document.getElementById('btn-section').onclick = () => toggle('section');
    document.getElementById('btn-lasso').onclick = () => toggle('lasso');
  }

  return {
    init,
    setMode,
    cancel,
    toggle,
    drawLasso,
    clearMeasure,
    get mode() { return mode; },
    blocksHover: () => mode === 'rect',
  };
})();
