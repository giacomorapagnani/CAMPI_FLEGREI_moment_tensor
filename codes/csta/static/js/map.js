/* csta - Leaflet map: base maps, station markers, tooltip, legend and the
 * tools (rectangle, lasso, circle selection; distance measurement). */
'use strict';

CS.map = (function () {
  let map = null;
  let group = null;
  const markers = new Map();     // key -> L.marker
  const baseLayers = {};

  const BASEMAPS = {
    osm: {label: 'OpenStreetMap', url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      opts: {maxNativeZoom: 19, attribution: '&copy; OpenStreetMap contributors'}},
    sat: {label: 'Satellite (Esri)', url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      opts: {maxNativeZoom: 19, attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics'}},
    topo: {label: 'Topografia (OpenTopoMap)', url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      opts: {maxNativeZoom: 17, subdomains: 'abc', attribution: '&copy; OpenStreetMap, SRTM | &copy; OpenTopoMap (CC-BY-SA)'}},
    relief: {label: 'Rilievo (Esri)', url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
      opts: {maxNativeZoom: 19, attribution: 'Tiles &copy; Esri'}},
  };

  const SEL = '#e8175d';
  const NET_COLORS = ['#3a86ff', '#ff6b35', '#2a9d8f', '#9b5de5', '#f15bb5', '#e09f00', '#00a6c8', '#8d6e63'];
  const STATE_COLORS = {active: '#2e9e44', closed: '#9e9e9e'};
  const TRI = '11,2 20,18 2,18';

  /* ------------------------------------------------------------ colours */

  let netColor = new Map();

  function updateNetColors() {
    const nets = [...new Set(CS.rows.map((r) => r.net))].sort();
    netColor = new Map(nets.map((n, i) => [n, NET_COLORS[i % NET_COLORS.length]]));
  }

  function fills(r) {
    const mode = CS.settings.color;
    if (mode === 'cls') return [(CS.config.classes.colors[r.cls]) || '#999'];
    if (mode === 'net') return [netColor.get(r.net) || '#999'];
    if (mode === 'state') return [r.active ? STATE_COLORS.active : STATE_COLORS.closed];
    return r.cats.map((cid) => (CS.catById.get(cid) || {}).color || '#999');
  }

  function triangleSVG(colors, sel, hov) {
    let h = '<svg width="22" height="20" viewBox="0 0 22 20">';
    if (hov) h += '<circle cx="11" cy="12" r="14" fill="rgba(255,214,0,0.55)" stroke="#333" stroke-width="1"/>';
    if (sel) h += '<polygon points="' + TRI + '" fill="' + SEL + '" stroke="' + SEL + '" stroke-width="7" stroke-linejoin="round"/>';
    if (colors.length === 1) {
      h += '<polygon points="' + TRI + '" fill="' + colors[0] + '"/>';
    } else {
      // vertical stripes, one per catalogue (nested svg = clip rectangle)
      const w = 18 / colors.length;
      colors.forEach((c, i) => {
        const x = (2 + i * w).toFixed(2);
        h += '<svg x="' + x + '" y="0" width="' + w.toFixed(2) + '" height="20" viewBox="' + x + ' 0 ' +
          w.toFixed(2) + ' 20"><polygon points="' + TRI + '" fill="' + c + '"/></svg>';
      });
    }
    h += '<polygon points="' + TRI + '" fill="none" stroke="#111" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    return h;
  }

  function makeIcon(r) {
    const sel = CS.sel.has(r.key);
    const hov = CS.hover === r.key;
    const label = CS.settings.labels ? '<span class="sta-label">' + CS.esc(r.sta) + '</span>' : '';
    return L.divIcon({className: 'sta-icon' + (sel ? ' sel' : ''), html: triangleSVG(fills(r), sel, hov) + label,
      iconSize: [22, 20], iconAnchor: [11, 13]});
  }

  function refreshMarker(key) {
    const mk = markers.get(key);
    const r = CS.rowByKey.get(key);
    if (!mk || !r) return;
    const sel = CS.sel.has(key);
    const hov = CS.hover === key;
    mk.setIcon(makeIcon(r));
    mk.setZIndexOffset(hov ? 3000 : sel ? 1000 : 0);
    mk._csSel = sel;
  }

  /* ------------------------------------------------------------ tooltip */

  const tipEl = () => document.getElementById('tooltip');

  function tipHTML(r) {
    let h = '<div class="tt-title">' + CS.esc(CS.code(r)) + '</div>';
    if (r.site) h += '<div class="tt-sub">' + CS.esc(r.site) + '</div>';
    h += '<table>' +
      '<tr><td>Lat, Lon</td><td>' + CS.fmtNum(r.lat, 5) + ', ' + CS.fmtNum(r.lon, 5) + '</td></tr>' +
      '<tr><td>Quota</td><td>' + (r.elev !== null ? CS.fmtNum(r.elev, 0) + ' m' : '—') + '</td></tr>' +
      '<tr><td>Canali</td><td>' + CS.esc(r.chans || '—') + (r.srs.length ? ' · ' + r.srs.join(', ') + ' Hz' : '') + '</td></tr>' +
      '<tr><td>Sensori</td><td>' + CS.esc(r.sensors.join(', ') || '—') + '</td></tr>' +
      '<tr><td>Attiva</td><td>' + (r.start || '?') + ' → ' + (r.end || 'oggi') + '</td></tr>' +
      '</table><div class="tt-sec">Cataloghi</div>';
    for (const cid of r.cats) {
      const c = CS.catById.get(cid);
      const v = r.versions.get(cid);
      const neq = v.sig !== r.sig;
      h += '<div class="tt-cat"><span class="badge sm" style="background:' + c.color + '">' + c.letter + '</span>' +
        CS.esc(c.name) + (neq ? ' <span class="neq" title="versione diversa">≠</span> <span class="muted">' +
        v.nchan + ' canali</span>' : '') + '</div>';
    }
    if (CS.sel.has(r.key)) h += '<div class="tt-sec" style="color:' + SEL + '">selezionata</div>';
    return h;
  }

  function showTip(r, ev) {
    const el = tipEl();
    el.innerHTML = tipHTML(r);
    el.style.display = 'block';
    const w = el.offsetWidth, h = el.offsetHeight;
    let x = ev.clientX + 16, y = ev.clientY + 14;
    if (x + w > window.innerWidth - 6) x = ev.clientX - w - 12;
    if (y + h > window.innerHeight - 6) y = Math.max(6, ev.clientY - h - 10);
    el.style.left = x + 'px';
    el.style.top = y + 'px';
  }

  function hideTip() { tipEl().style.display = 'none'; }

  /* ------------------------------------------------------------ markers */

  function render() {
    group.clearLayers();
    markers.clear();
    updateNetColors();
    for (const r of CS.shown) {
      if (r.lat === null || r.lon === null) continue;
      const mk = L.marker([r.lat, r.lon], {icon: makeIcon(r), keyboard: false, bubblingMouseEvents: true,
        zIndexOffset: CS.sel.has(r.key) ? 1000 : 0});
      mk._csSel = CS.sel.has(r.key);
      mk.on('mouseover', (e) => {
        if (tools.mode) return;
        CS.setHover(r.key, 'map');
        showTip(r, e.originalEvent);
      });
      mk.on('mousemove', (e) => { if (!tools.mode && tipEl().style.display === 'block') showTip(r, e.originalEvent); });
      mk.on('mouseout', () => { CS.setHover(null, 'map'); hideTip(); });
      mk.on('click', (e) => {
        if (tools.mode) return;      // the click reaches the map (tool)
        const oe = e.originalEvent;
        CS.select([r.key], oe.altKey ? 'remove' : (oe.shiftKey || oe.metaKey || oe.ctrlKey) ? 'toggle' : 'replace');
        CS.emit('reveal', r.key);
      });
      mk.on('dblclick', (e) => {
        if (tools.mode) return;
        L.DomEvent.stopPropagation(e);   // no map zoom
        CS.ui.showDetail(r.key);
      });
      group.addLayer(mk);
      markers.set(r.key, mk);
    }
    updateLegend();
  }

  function updateSelection() {
    for (const [key, mk] of markers) {
      if (mk._csSel !== CS.sel.has(key)) refreshMarker(key);
    }
  }

  /* ------------------------------------------------------------- legend */

  function legItem(colors, label) {
    return '<div class="leg-item">' + triangleSVG(colors, false, false) + '<span>' + label + '</span></div>';
  }

  function updateLegend() {
    const el = document.getElementById('legend');
    if (!CS.rows.length) { el.style.display = 'none'; return; }
    const mode = CS.settings.color;
    let h = '';
    if (mode === 'cat') {
      for (const c of CS.visibleCats()) h += legItem([c.color], '<b>' + c.letter + '</b> ' + CS.esc(c.name));
      if (CS.visibleCats().length > 1) h += '<div class="muted" style="margin-top:3px">a strisce: in più cataloghi</div>';
    } else if (mode === 'cls') {
      const used = new Set(CS.rows.map((r) => r.cls));
      for (const k of CS.config.classes.order) {
        if (used.has(k)) h += legItem([CS.config.classes.colors[k]], CS.esc(CS.config.classes.labels[k]));
      }
    } else if (mode === 'net') {
      for (const [n, c] of netColor) h += legItem([c], CS.esc(n || '(senza rete)'));
    } else {
      h += legItem([STATE_COLORS.active], 'attiva oggi') + legItem([STATE_COLORS.closed], 'chiusa');
    }
    h += '<div class="leg-item">' + triangleSVG(['#ffffff'], true, false) + '<span>selezionata</span></div>';
    el.innerHTML = h;
    el.style.display = 'block';
  }

  /* -------------------------------------------------------------- tools */

  const tools = {mode: null, off: null, enter: null};
  const HINTS = {
    rect: 'Rettangolo: trascina sulla mappa · Maiusc aggiunge, Alt toglie · Esc annulla',
    lasso: 'Lazo: clic per i vertici · doppio clic / Invio per chiudere · Maiusc aggiunge, Alt toglie · Esc annulla',
    circle: 'Cerchio: clic sul centro, poi clic sul raggio · Maiusc aggiunge, Alt toglie · Esc annulla',
    measure: 'Distanza: clic per i punti · doppio clic / Invio per finire · Esc cancella',
  };
  const BUTTONS = {rect: 'btn-rect', lasso: 'btn-lasso', circle: 'btn-circle', measure: 'btn-measure'};
  let toolsRenderer = null;
  let measureGroup = null;

  function bind(events) {
    for (const [k, f] of Object.entries(events)) map.on(k, f);
    return () => { for (const [k, f] of Object.entries(events)) map.off(k, f); };
  }

  const samePixel = (a, b) => map.latLngToContainerPoint(a).distanceTo(map.latLngToContainerPoint(b)) < 4;

  function setMode(m) {
    if (tools.mode) cancel();
    if (!m) return;
    if (m === 'measure') clearMeasure();
    tools.mode = m;
    document.getElementById('map').classList.add('crosshair');
    const hint = document.getElementById('mode-hint');
    hint.textContent = HINTS[m];
    hint.style.display = 'block';
    map.doubleClickZoom.disable();
    hideTip();
    document.getElementById(BUTTONS[m]).classList.add('on');
    const h = ({rect: rectTool, lasso: lassoTool, circle: circleTool, measure: measureTool})[m]();
    tools.off = h.off;
    tools.enter = h.enter || null;
  }

  function cancel() {
    if (tools.off) tools.off();
    tools.off = tools.enter = null;
    tools.mode = null;
    document.getElementById('map').classList.remove('crosshair');
    document.getElementById('mode-hint').style.display = 'none';
    map.doubleClickZoom.enable();
    map.dragging.enable();
    for (const id of Object.values(BUTTONS)) document.getElementById(id).classList.remove('on');
  }

  function toggle(m) {
    if (tools.mode === m) {
      if (m === 'measure') clearMeasure();
      cancel();
    } else {
      setMode(m);
    }
  }

  function selectWhere(test, ev) {
    const keys = CS.shown.filter((r) => r.lat !== null && test(r)).map((r) => r.key);
    const mode = CS.modeFromEvent(ev);
    CS.select(keys, mode);
    const verb = {replace: 'Selezionate', add: 'Aggiunte', remove: 'Tolte'}[mode];
    CS.toast(verb + ' ' + keys.length + ' stazioni', 'info', 2500);
  }

  function rectTool() {
    map.dragging.disable();
    let start = null;
    let rect = null;
    const off = bind({
      mousedown: (e) => {
        start = e.latlng;
        rect = L.rectangle([start, start], {color: SEL, weight: 2, dashArray: '5,4', fillOpacity: 0.06,
          renderer: toolsRenderer, interactive: false}).addTo(map);
      },
      mousemove: (e) => { if (start) rect.setBounds([start, e.latlng]); },
      mouseup: (e) => {
        if (!start) return;
        const b = L.latLngBounds(start, e.latlng);
        const tiny = samePixel(start, e.latlng);
        start = null;
        rect.remove();
        rect = null;
        if (tiny) return;
        selectWhere((r) => b.contains([r.lat, r.lon]), e.originalEvent);
        cancel();
      },
    });
    return {off() { off(); if (rect) rect.remove(); }};
  }

  function lassoTool() {
    const pts = [];
    const g = L.layerGroup().addTo(map);
    const line = L.polyline([], {color: SEL, weight: 2, renderer: toolsRenderer, interactive: false}).addTo(g);
    const rubber = L.polyline([], {color: SEL, weight: 1.5, dashArray: '4,4', renderer: toolsRenderer,
      interactive: false}).addTo(g);
    let done = false;

    function close(ev) {
      if (done) return;
      done = true;
      if (pts.length >= 3) {
        const poly = pts.map((p) => [p.lat, p.lng]);
        selectWhere((r) => CS.pointInPolygon(r.lat, r.lon, poly), ev);
      } else {
        CS.toast('Il lazo richiede almeno 3 vertici', 'info');
      }
      cancel();
    }

    const off = bind({
      click: (e) => {
        if (done) return;
        if (pts.length && samePixel(pts[pts.length - 1], e.latlng)) return;
        pts.push(e.latlng);
        line.setLatLngs(pts);
      },
      dblclick: (e) => close(e.originalEvent),
      mousemove: (e) => {
        if (done || !pts.length) return;
        rubber.setLatLngs([pts[pts.length - 1], e.latlng, pts[0]]);
      },
    });
    return {off() { off(); g.remove(); }, enter: close};
  }

  function circleTool() {
    let center = null;
    const g = L.layerGroup().addTo(map);
    let circle = null;
    let label = null;
    const off = bind({
      click: (e) => {
        if (!center) {
          center = e.latlng;
          L.circleMarker(center, {radius: 3.5, color: SEL, weight: 2, fillColor: '#fff', fillOpacity: 1,
            renderer: toolsRenderer, interactive: false}).addTo(g);
          return;
        }
        const r = CS.geo.inverse(center.lat, center.lng, e.latlng.lat, e.latlng.lng).dist;
        if (!(r > 0)) return;
        const c = center;
        selectWhere((row) => CS.geo.inverse(c.lat, c.lng, row.lat, row.lon).dist <= r, e.originalEvent);
        cancel();
      },
      mousemove: (e) => {
        if (!center) return;
        const r = CS.geo.inverse(center.lat, center.lng, e.latlng.lat, e.latlng.lng).dist;
        if (!(r > 0)) return;
        if (!circle) {
          circle = L.circle(center, {radius: r, color: SEL, weight: 2, dashArray: '6,5', fillOpacity: 0.05,
            renderer: toolsRenderer, interactive: false}).addTo(g);
          label = L.tooltip({permanent: true, direction: 'right', className: 'measure-label', offset: [8, 0]})
            .setLatLng(e.latlng).setContent(CS.fmtKm(r)).addTo(map);
        } else {
          circle.setRadius(r);
          label.setLatLng(e.latlng).setContent(CS.fmtKm(r));
        }
      },
    });
    return {off() { off(); g.remove(); if (label) label.remove(); }};
  }

  function clearMeasure() {
    if (measureGroup) { measureGroup.remove(); measureGroup = null; }
    document.getElementById('measure-box').style.display = 'none';
  }

  function measureTool() {
    clearMeasure();
    const g = L.layerGroup().addTo(map);
    measureGroup = g;
    const box = document.getElementById('measure-box');
    const pts = [];
    const line = L.polyline([], {color: '#d00', weight: 2.5, renderer: toolsRenderer, interactive: false}).addTo(g);
    const rubber = L.polyline([], {color: '#d00', weight: 1.5, dashArray: '5,5', renderer: toolsRenderer,
      interactive: false}).addTo(g);
    let finished = false;

    function total() {
      let t = 0;
      for (let k = 1; k < pts.length; k++) t += CS.geo.vincenty(pts[k - 1].lat, pts[k - 1].lng, pts[k].lat, pts[k].lng).dist;
      return t;
    }

    function info(cur) {
      const t = total();
      let h = '<b>Distanza</b> (WGS84)<br>Totale: <b>' + CS.fmtKm(t) + '</b>';
      if (pts.length > 1) {
        const a = pts[pts.length - 2], b = pts[pts.length - 1];
        const g2 = CS.geo.vincenty(a.lat, a.lng, b.lat, b.lng);
        h += '<br>Ultimo tratto: ' + CS.fmtKm(g2.dist) + ' · az. ' + g2.az.toFixed(1) + '°';
      }
      if (cur) h += '<br><span class="muted">al cursore: ' + CS.fmtKm(cur.dist) + ' · az. ' + cur.az.toFixed(1) + '°</span>';
      box.innerHTML = h;
      box.style.display = 'block';
    }

    function finish() {
      if (finished) return;
      finished = true;
      rubber.setLatLngs([]);
      tools.off = null;      // keep the measurement on the map
      off();
      cancel();
    }

    const off = bind({
      click: (e) => {
        if (finished) return;
        if (pts.length && samePixel(pts[pts.length - 1], e.latlng)) return;
        pts.push(e.latlng);
        line.setLatLngs(pts);
        L.circleMarker(e.latlng, {radius: 3.5, color: '#d00', weight: 2, fillColor: '#fff', fillOpacity: 1,
          renderer: toolsRenderer, interactive: false}).addTo(g)
          .bindTooltip(pts.length > 1 ? CS.fmtKm(total()) : 'inizio', {permanent: true, direction: 'right',
            className: 'measure-label', offset: [6, 0]});
        info();
      },
      dblclick: () => finish(),
      mousemove: (e) => {
        if (finished || !pts.length) return;
        const p = pts[pts.length - 1];
        rubber.setLatLngs([p, e.latlng]);
        info(CS.geo.vincenty(p.lat, p.lng, e.latlng.lat, e.latlng.lng));
      },
    });
    return {off() { off(); clearMeasure(); }, enter: finish};
  }

  /* --------------------------------------------------------------- view */

  let pendingFit = null;

  function fitRows(rows, maxZoom) {
    const pts = rows.filter((r) => r.lat !== null).map((r) => [r.lat, r.lon]);
    if (!pts.length) return;
    map.invalidateSize();
    const size = map.getSize();
    if (!size.x || !size.y) {
      // hidden window: fit when the map gets a size
      pendingFit = [rows, maxZoom];
      return;
    }
    if (pts.length === 1) { map.setView(pts[0], Math.max(map.getZoom(), 12)); return; }
    map.fitBounds(L.latLngBounds(pts).pad(0.12), {maxZoom: maxZoom || 14});
  }

  function init() {
    map = L.map('map', {zoomControl: true, worldCopyJump: true, preferCanvas: false, boxZoom: false});
    map.setView([40.83, 14.12], 10);
    map.createPane('cstaTools').style.zIndex = 650;
    toolsRenderer = L.svg({pane: 'cstaTools', padding: 0.5});

    for (const [k, b] of Object.entries(BASEMAPS)) {
      baseLayers[k] = L.tileLayer(b.url, Object.assign({maxZoom: 19, crossOrigin: true}, b.opts));
    }
    const names = {};
    for (const [k, b] of Object.entries(BASEMAPS)) names[b.label] = baseLayers[k];
    const start = baseLayers[CS.settings.basemap] ? CS.settings.basemap : 'osm';
    baseLayers[start].addTo(map);
    L.control.layers(names, {}, {position: 'topright', collapsed: true}).addTo(map);
    L.control.scale({imperial: false, position: 'bottomright'}).addTo(map);
    map.on('baselayerchange', (e) => {
      for (const [k, l] of Object.entries(baseLayers)) if (l === e.layer) CS.settings.basemap = k;
      CS.saveSettings();
    });
    map.on('zoomstart movestart', hideTip);
    // a fit still waiting for a visible map is dropped when the view moves
    map.on('zoomstart movestart', () => { pendingFit = null; });
    map.on('resize', () => {
      if (pendingFit) { const [rows, z] = pendingFit; pendingFit = null; fitRows(rows, z); }
    });

    group = L.layerGroup().addTo(map);

    CS.on('rows', render);
    CS.on('state', updateLegend);
    CS.on('sel', updateSelection);
    CS.on('hover', (old, key) => { if (old) refreshMarker(old); if (key) refreshMarker(key); });
    CS.on('fit', () => fitRows(CS.shown.length ? CS.shown : CS.rows));
  }

  return {
    init,
    get map() { return map; },
    get mode() { return tools.mode; },
    render,
    toggle,
    cancel,
    enter(ev) { if (tools.enter) tools.enter(ev); },
    clearMeasure,
    fitShown() { fitRows(CS.shown); },
    fitKeys(keys) { fitRows(keys.map((k) => CS.rowByKey.get(k)).filter(Boolean), 15); },
    panTo(key) {
      const r = CS.rowByKey.get(key);
      if (r && r.lat !== null && !map.getBounds().pad(-0.05).contains([r.lat, r.lon])) map.panTo([r.lat, r.lon]);
    },
    hideTip,
  };
})();
