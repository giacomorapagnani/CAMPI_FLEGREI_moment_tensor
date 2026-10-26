/* cgis - Leaflet map: base maps, event canvas (circles + beachballs),
 * hover picking, tooltip, stations. */
'use strict';

CG.mapLayer = (function () {
  let map = null;
  let evLayer = null;
  let staGroup = null;
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
    light: {label: 'Chiaro (CARTO)', url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      opts: {maxNativeZoom: 20, subdomains: 'abcd', attribution: '&copy; OpenStreetMap &copy; CARTO'}},
  };

  /* --------------------------------------------------------- beachballs */

  function buildPaths(polys) {
    if (!polys) return null;
    return polys.map((p) => {
      const path = new Path2D();
      const xy = p[2];
      path.moveTo(xy[0], xy[1]);
      for (let k = 2; k < xy.length; k += 2) path.lineTo(xy[k], xy[k + 1]);
      return {fill: p[0], edge: p[1], path};
    });
  }

  /* Draw a beachball (unit-radius pyrocko paths, y north/up). */
  function drawBeachball(ctx, x, y, r, paths, color, dpr) {
    ctx.save();
    ctx.setTransform(dpr * r, 0, 0, -dpr * r, dpr * x, dpr * y);
    ctx.beginPath();
    ctx.arc(0, 0, 1, 0, 2 * Math.PI);
    ctx.fillStyle = '#fff';
    ctx.fill();
    if (paths) {
      ctx.lineWidth = 0.8 / r;
      for (const p of paths) {
        if (p.fill < 0) continue;
        const c = p.fill === 1 ? color : '#fff';
        ctx.fillStyle = c;
        ctx.strokeStyle = c;
        ctx.fill(p.path);
        ctx.stroke(p.path);
      }
      ctx.strokeStyle = '#1e1e1e';
      ctx.lineWidth = 1.0 / r;
      for (const p of paths) if (p.edge) ctx.stroke(p.path);
    } else {
      ctx.fillStyle = color;
      ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(0, 0, 1, 0, 2 * Math.PI);
    ctx.strokeStyle = '#1e1e1e';
    ctx.lineWidth = 1.0 / r;
    ctx.stroke();
    ctx.restore();
  }

  function ensureBeachballs(L, type) {
    if (!L.hasMT || L.bb[type] || L.bbPending[type]) return;
    L.bbPending[type] = true;
    CG.api('catalog_beachballs', {id: L.id, type}).then((res) => {
      const m = new Map();
      res.idx.forEach((ev, k) => m.set(ev, buildPaths(res.polys[k])));
      L.bb[type] = m;
      CG.invalidate('draw');
    }).catch((e) => CG.error(e, 'beachball')).finally(() => { L.bbPending[type] = false; });
  }

  /* ------------------------------------------------------- event layer */

  const EventLayer = L.Layer.extend({
    onAdd(m) {
      this._map = m;
      const pane = m.getPane('cgEvents');
      this._canvas = L.DomUtil.create('canvas', 'cg-canvas leaflet-zoom-animated', pane);
      this._hl = L.DomUtil.create('canvas', 'cg-canvas leaflet-zoom-animated', m.getPane('cgHighlight'));
      this._hit = {x: [], y: [], r: [], L: [], i: [], grid: new Map()};
      m.on('moveend', this._reset, this);
      m.on('resize', this._reset, this);
      m.on('zoomanim', this._animateZoom, this);
      this._reset();
    },
    onRemove(m) {
      L.DomUtil.remove(this._canvas);
      L.DomUtil.remove(this._hl);
      m.off('moveend', this._reset, this);
      m.off('resize', this._reset, this);
      m.off('zoomanim', this._animateZoom, this);
    },
    _animateZoom(e) {
      if (!this._topLeftLatLng || !this._map._latLngToNewLayerPoint) return;
      const scale = this._map.getZoomScale(e.zoom);
      const offset = this._map._latLngToNewLayerPoint(this._topLeftLatLng, e.zoom, e.center);
      L.DomUtil.setTransform(this._canvas, offset, scale);
      L.DomUtil.setTransform(this._hl, offset, scale);
    },
    _reset() {
      const m = this._map;
      const size = m.getSize();
      const pad = 0.3;
      const px = Math.round(size.x * pad), py = Math.round(size.y * pad);
      const tl = m.containerPointToLayerPoint([-px, -py]).round();
      this._tl = tl;
      this._topLeftLatLng = m.layerPointToLatLng(tl);
      this._w = size.x + 2 * px;
      this._h = size.y + 2 * py;
      const dpr = window.devicePixelRatio || 1;
      this._dpr = dpr;
      for (const c of [this._canvas, this._hl]) {
        L.DomUtil.setPosition(c, tl);
        c.style.transform = '';
        L.DomUtil.setPosition(c, tl);
        c.width = Math.round(this._w * dpr);
        c.height = Math.round(this._h * dpr);
        c.style.width = this._w + 'px';
        c.style.height = this._h + 'px';
      }
      this.draw();
      drawHighlight();
    },

    /* canvas coordinates of a layer event */
    _xform() {
      const m = this._map;
      const s = Math.pow(2, m.getZoom());
      const o = m.getPixelOrigin();
      return {s, ox: -o.x - this._tl.x, oy: -o.y - this._tl.y};
    },

    draw() {
      if (!this._map) return;
      const ctx = this._canvas.getContext('2d');
      const dpr = this._dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const hit = this._hit = {x: [], y: [], r: [], L: [], i: [], grid: new Map()};
      if (!CG.ready) return;
      const {s, ox, oy} = this._xform();
      const W = this._w, H = this._h;
      const st = CG.settings;
      const greyOutside = st.outside === 'grey' && CG.timeWindow() !== null;
      const cell = 24;

      CG.cats.forEach((Ly, li) => {
        if (!Ly.style.visible || !Ly.order) return;
        const order = Ly.order, vis = Ly.vis, base = Ly.base, r = Ly.r;
        const x0 = Ly.x0, y0 = Ly.y0, colors = Ly.colors;
        const showBB = st.bbShow && Ly.style.beachballs && Ly.hasMT;
        let bbMap = null;
        if (showBB) {
          ensureBeachballs(Ly, st.bbType);
          bbMap = Ly.bb[st.bbType] || null;
        }
        const alpha = CG.layerOpacity(Ly);

        if (greyOutside) {
          ctx.globalAlpha = 0.35;
          ctx.fillStyle = '#9a9a9a';
          ctx.beginPath();
          for (let k = 0; k < order.length; k++) {
            const i = order[k];
            if (!base[i] || vis[i]) continue;
            const x = x0[i] * s + ox, y = y0[i] * s + oy, rr = r[i] * 0.7;
            if (x < -rr || y < -rr || x > W + rr || y > H + rr) continue;
            ctx.moveTo(x + rr, y);
            ctx.arc(x, y, rr, 0, 2 * Math.PI);
          }
          ctx.fill();
        }

        ctx.globalAlpha = alpha;
        ctx.lineWidth = 0.6;
        ctx.strokeStyle = 'rgba(30,30,30,0.75)';
        const bbList = [];
        for (let k = 0; k < order.length; k++) {
          const i = order[k];
          if (!vis[i]) continue;
          const x = x0[i] * s + ox, y = y0[i] * s + oy;
          let rr = r[i];
          if (showBB && Ly.mtIdx[i] >= 0) {
            rr *= st.bbScale;
            if (x < -rr || y < -rr || x > W + rr || y > H + rr) continue;
            bbList.push(i);
          } else {
            if (x < -rr || y < -rr || x > W + rr || y > H + rr) continue;
            ctx.beginPath();
            ctx.arc(x, y, rr, 0, 2 * Math.PI);
            ctx.fillStyle = colors[i];
            ctx.fill();
            ctx.stroke();
          }
          // hit-test grid (later entries are drawn on top)
          const h = hit.x.length;
          hit.x.push(x); hit.y.push(y); hit.r.push(rr); hit.L.push(li); hit.i.push(i);
          const key = Math.floor(x / cell) * 100003 + Math.floor(y / cell);
          let b = hit.grid.get(key);
          if (!b) hit.grid.set(key, (b = []));
          b.push(h);
        }
        // beachballs on top of the circles of the same layer
        for (const i of bbList) {
          const x = x0[i] * s + ox, y = y0[i] * s + oy;
          const paths = bbMap ? bbMap.get(i) : null;
          ctx.globalAlpha = alpha;
          drawBeachball(ctx, x, y, r[i] * st.bbScale, paths, colors[i], dpr);
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      });
      ctx.globalAlpha = 1;

      // cumulative mode: recent events
      if (st.time.mode === 'cumulative' && st.time.t1 !== null) {
        const rec = CG.recentSeconds();
        const tlim = st.time.t1 - rec;
        ctx.strokeStyle = '#e00000';
        ctx.lineWidth = 1.5;
        for (const Ly of CG.cats) {
          if (!Ly.style.visible) continue;
          const scale = (st.bbShow && Ly.style.beachballs) ? st.bbScale : 1;
          for (let i = 0; i < Ly.n; i++) {
            if (!Ly.vis[i] || Ly.t[i] <= tlim) continue;
            const x = Ly.x0[i] * s + ox, y = Ly.y0[i] * s + oy;
            const rr = Ly.r[i] * (Ly.mtIdx[i] >= 0 ? scale : 1) + 2;
            ctx.beginPath();
            ctx.arc(x, y, rr, 0, 2 * Math.PI);
            ctx.stroke();
          }
        }
      }
    },

    pick(containerPoint) {
      const hit = this._hit;
      if (!hit || !hit.x.length) return null;
      const lp = this._map.containerPointToLayerPoint(containerPoint);
      const x = lp.x - this._tl.x, y = lp.y - this._tl.y;
      const cell = 24;
      const cx = Math.floor(x / cell), cy = Math.floor(y / cell);
      let best = -1, bestTop = -1, bestD = Infinity;
      for (let dx = -3; dx <= 3; dx++) {
        for (let dy = -3; dy <= 3; dy++) {
          const b = hit.grid.get((cx + dx) * 100003 + (cy + dy));
          if (!b) continue;
          for (const h of b) {
            const d = Math.hypot(hit.x[h] - x, hit.y[h] - y);
            if (d <= hit.r[h] + 1.5 && h > bestTop) bestTop = h;
            if (d < bestD) { bestD = d; best = h; }
          }
        }
      }
      const h = bestTop >= 0 ? bestTop : (bestD <= 6 ? best : -1);
      if (h < 0) return null;
      return {L: CG.cats[hit.L[h]], i: hit.i[h]};
    },

    eventPoint(Ly, i) {
      const {s, ox, oy} = this._xform();
      return [Ly.x0[i] * s + ox, Ly.y0[i] * s + oy];
    },
  });

  /* ---------------------------------------------------------- highlight */

  function drawHighlight() {
    if (!evLayer || !evLayer._hl) return;
    const c = evLayer._hl;
    const ctx = c.getContext('2d');
    const dpr = evLayer._dpr || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    const hv = CG.hover;
    if (!hv || !hv.L || !hv.L.style.visible) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [x, y] = evLayer.eventPoint(hv.L, hv.i);
    const st = CG.settings;
    let r = hv.L.r[hv.i] || 4;
    if (st.bbShow && hv.L.style.beachballs && hv.L.mtIdx[hv.i] >= 0) r *= st.bbScale;
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#ffffff';
    ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 2 * Math.PI); ctx.stroke();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#000000';
    ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 2 * Math.PI); ctx.stroke();
  }

  /* ------------------------------------------------------------ tooltip */

  function eventHTML(Ly, i) {
    const f = CG.fmtNum;
    const rows = [];
    rows.push('<div class="tt-title">' + CG.esc(Ly.names[i] || ('evento ' + i)) + '</div>');
    rows.push('<div class="tt-sub">' + CG.esc(Ly.name) + '</div>');
    const tb = [];
    tb.push(['Origin time (UTC)', CG.esc(Ly.tstr[i])]);
    tb.push(['Lat, Lon', f(Ly.lat[i], 5) + ', ' + f(Ly.lon[i], 5)]);
    tb.push(['Profondità', Number.isFinite(Ly.dep[i]) ? f(Ly.dep[i], 3) + ' km' : '—']);
    if (Number.isFinite(Ly.mag[i])) {
      const mt = Ly.magType && Ly.magType[i] ? ' (' + CG.esc(Ly.magType[i]) + ')' : '';
      tb.push(['Magnitudo', f(Ly.mag[i], 2) + mt]);
    }
    if (Ly.info && Ly.info[i]) for (const kv of Ly.info[i]) tb.push([CG.esc(kv[0]), CG.esc(kv[1])]);
    let html = rows.join('') + '<table>' + tb.map((r) => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('') + '</table>';
    if (Ly.tags && Ly.tags[i] && Ly.tags[i].length) {
      html += '<div class="tt-sec">Tag</div><table>' + Ly.tags[i].map((s) => {
        const k = s.indexOf(':');
        return k >= 0 ? '<tr><td>' + CG.esc(s.slice(0, k)) + '</td><td>' + CG.esc(s.slice(k + 1)) + '</td></tr>'
          : '<tr><td colspan="2">' + CG.esc(s) + '</td></tr>';
      }).join('') + '</table>';
    }
    const k = Ly.mtIdx[i];
    if (k >= 0) {
      const m = Ly.mt;
      const v = (key, nd) => f(m[key][k], nd);
      html += '<div class="tt-sec">Tensore momento</div><table>' +
        '<tr><td>Mw / M0</td><td>' + v('mw', 2) + ' / ' + (m.m0[k] !== null ? Number(m.m0[k]).toExponential(2) + ' Nm' : '—') + '</td></tr>' +
        '<tr><td>Piano 1 (s/d/r)</td><td>' + v('s1', 0) + ' / ' + v('d1', 0) + ' / ' + v('r1', 0) + '</td></tr>' +
        '<tr><td>Piano 2 (s/d/r)</td><td>' + v('s2', 0) + ' / ' + v('d2', 0) + ' / ' + v('r2', 0) + '</td></tr>' +
        '<tr><td>ISO / CLVD / DC</td><td>' + v('iso', 0) + '% / ' + v('clvd', 0) + '% / ' + v('dc', 0) + '%</td></tr>' +
        '<tr><td>P (trend/plunge)</td><td>' + v('p_tr', 0) + '° / ' + v('p_pl', 0) + '°</td></tr>' +
        '<tr><td>T (trend/plunge)</td><td>' + v('t_tr', 0) + '° / ' + v('t_pl', 0) + '°</td></tr>' +
        '</table>';
    }
    return html;
  }

  const tip = () => document.getElementById('tooltip');

  function showTooltip(html, clientX, clientY) {
    const el = tip();
    el.innerHTML = html;
    el.style.display = 'block';
    const w = el.offsetWidth, h = el.offsetHeight;
    let x = clientX + 16, y = clientY + 16;
    if (x + w > window.innerWidth - 8) x = clientX - w - 16;
    if (y + h > window.innerHeight - 8) y = Math.max(8, clientY - h - 16);
    el.style.left = Math.max(8, x) + 'px';
    el.style.top = Math.max(8, y) + 'px';
  }

  function hideTooltip() { tip().style.display = 'none'; }

  /* Set the hovered event (from the map, a plot or a section). */
  function setHover(hv, source) {
    const same = (CG.hover && hv && CG.hover.L === hv.L && CG.hover.i === hv.i) || (!CG.hover && !hv);
    CG.hover = hv;
    if (same) return;
    drawHighlight();
    CG.plots.highlight(source);
    CG.sections.highlight(source);
  }

  /* --------------------------------------------------------------- init */

  function init() {
    map = L.map('map', {
      zoomControl: true,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      wheelPxPerZoomLevel: 90,
      maxZoom: 19,
      worldCopyJump: false,
      doubleClickZoom: true,
    }).setView([41.0, 14.0], 6);
    map.createPane('cgEvents').style.zIndex = 450;
    map.createPane('cgHighlight').style.zIndex = 455;
    map.createPane('cgTools').style.zIndex = 470;
    map.getPane('cgEvents').style.pointerEvents = 'none';
    map.getPane('cgHighlight').style.pointerEvents = 'none';
    CG.toolsRenderer = L.svg({pane: 'cgTools', padding: 0.5});

    for (const [k, b] of Object.entries(BASEMAPS)) {
      baseLayers[k] = L.tileLayer(b.url, Object.assign({maxZoom: 19, crossOrigin: true}, b.opts));
    }
    const names = {};
    for (const [k, b] of Object.entries(BASEMAPS)) names[b.label] = baseLayers[k];
    const startBase = baseLayers[CG.settings.basemap] ? CG.settings.basemap : 'osm';
    baseLayers[startBase].addTo(map);
    L.control.layers(names, {}, {position: 'topright', collapsed: true}).addTo(map);
    L.control.scale({imperial: false, position: 'bottomright'}).addTo(map);
    map.on('baselayerchange', (e) => {
      for (const [k, l] of Object.entries(baseLayers)) if (l === e.layer) CG.settings.basemap = k;
      CG.session.changed();
    });
    map.on('moveend', () => CG.session.changed());

    evLayer = new EventLayer();
    evLayer.addTo(map);
    staGroup = L.layerGroup().addTo(map);

    const onMove = CG.rafThrottle((e) => {
      if (CG.tools && CG.tools.blocksHover()) { setHover(null, 'map'); hideTooltip(); return; }
      const t = e.originalEvent && e.originalEvent.target;
      if (t && t.closest && t.closest('.leaflet-marker-icon, .leaflet-popup, .leaflet-control')) {
        setHover(null, 'map'); hideTooltip(); return;
      }
      const hv = evLayer.pick(e.containerPoint);
      setHover(hv, 'map');
      if (hv) showTooltip(eventHTML(hv.L, hv.i), e.originalEvent.clientX, e.originalEvent.clientY);
      else hideTooltip();
    });
    map.on('mousemove', onMove);
    map.on('mouseout', () => { setHover(null, 'map'); hideTooltip(); });
    map.on('zoomstart movestart', hideTooltip);
    map.on('click', (e) => {
      if (CG.tools && CG.tools.mode) return;
      const hv = evLayer.pick(e.containerPoint);
      if (hv) {
        L.popup({maxWidth: 420, className: 'cg-popup'})
          .setLatLng([hv.L.lat[hv.i], hv.L.lon[hv.i]])
          .setContent(eventHTML(hv.L, hv.i))
          .openOn(map);
      }
    });
    return map;
  }

  /* ------------------------------------------------------------ stations */

  function triangleSVG(color) {
    return '<svg width="16" height="14" viewBox="0 0 16 14"><polygon points="8,1 15,13 1,13" fill="' +
      color + '" stroke="#000" stroke-width="1.2"/></svg>';
  }

  function stationHTML(Ls, st) {
    let h = '<div class="tt-title">' + CG.esc(st.net + '.' + st.sta) + '</div>';
    if (st.site) h += '<div class="tt-sub">' + CG.esc(st.site) + '</div>';
    h += '<table>' +
      '<tr><td>Lat, Lon</td><td>' + CG.fmtNum(st.lat, 5) + ', ' + CG.fmtNum(st.lon, 5) + '</td></tr>' +
      '<tr><td>Quota</td><td>' + (st.elev !== null ? CG.fmtNum(st.elev, 0) + ' m' : '—') + '</td></tr>' +
      '<tr><td>Tipo</td><td>' + st.classes.map((c) => CG.esc(Ls.classLabels[c] || c)).join(', ') + '</td></tr>' +
      '<tr><td>Attiva</td><td>' + (st.start || '?') + ' → ' + (st.end || 'oggi') + '</td></tr>' +
      '</table>';
    if (st.channels.length) {
      h += '<div class="tt-sec">Canali</div><table>' + st.channels.map((c) =>
        '<tr><td>' + CG.esc((c.loc ? c.loc + '.' : '') + c.code) + (c.sr ? ' ' + c.sr + ' Hz' : '') + '</td><td>' +
        CG.esc(c.sensor || '—') + (c.start ? '<br><span class="muted">' + c.start + ' → ' + (c.end || 'oggi') + '</span>' : '') +
        '</td></tr>').join('') + '</table>';
    }
    return h;
  }

  function renderStations() {
    staGroup.clearLayers();
    for (const Ls of CG.stas) {
      if (!Ls.style.visible) continue;
      for (const st of Ls.stations) {
        const color = Ls.classColors[st.cls] || '#999';
        const label = Ls.style.labels ? '<span class="sta-label">' + CG.esc(st.sta) + '</span>' : '';
        const icon = L.divIcon({className: 'sta-icon', html: triangleSVG(color) + label,
          iconSize: [16, 14], iconAnchor: [8, 10]});
        // clicks bubble to the map, so that the tools also work over stations
        const mk = L.marker([st.lat, st.lon], {icon, keyboard: false, riseOnHover: true,
          bubblingMouseEvents: true});
        mk.bindTooltip(stationHTML(Ls, st), {direction: 'top', offset: [0, -8], className: 'cg-tip', opacity: 1});
        staGroup.addLayer(mk);
      }
    }
  }

  /* -------------------------------------------------------------- misc */

  function fitTo(layers) {
    let la0 = Infinity, la1 = -Infinity, lo0 = Infinity, lo1 = -Infinity;
    for (const Ly of layers) {
      if (Ly.kind === 'catalog') {
        for (let i = 0; i < Ly.n; i++) {
          la0 = Math.min(la0, Ly.lat[i]); la1 = Math.max(la1, Ly.lat[i]);
          lo0 = Math.min(lo0, Ly.lon[i]); lo1 = Math.max(lo1, Ly.lon[i]);
        }
      } else {
        for (const st of Ly.stations) {
          la0 = Math.min(la0, st.lat); la1 = Math.max(la1, st.lat);
          lo0 = Math.min(lo0, st.lon); lo1 = Math.max(lo1, st.lon);
        }
      }
    }
    if (!Number.isFinite(la0)) return;
    if (la1 - la0 < 1e-3 && lo1 - lo0 < 1e-3) map.setView([la0, lo0], 13);
    else map.fitBounds([[la0, lo0], [la1, lo1]], {padding: [30, 30], maxZoom: 15});
  }

  return {
    init,
    get map() { return map; },
    redraw() { if (evLayer) { evLayer.draw(); drawHighlight(); } },
    drawHighlight,
    renderStations,
    setHover,
    hideTooltip,
    eventHTML,
    drawBeachball,
    buildPaths,
    fitTo,
    setBasemap(k) {
      if (!baseLayers[k]) return;
      for (const l of Object.values(baseLayers)) if (map.hasLayer(l)) map.removeLayer(l);
      baseLayers[k].addTo(map);
      CG.settings.basemap = k;
    },
    BASEMAPS,
  };
})();
