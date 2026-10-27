/* cgis - sessions: collect / restore the full state; autosave to
 * codes/cgis/sessions/_last.yaml (resumed with `python3 cgis -res`). */
'use strict';

CG.session = (function () {
  let current = null;       // name of the current session
  let restoring = false;

  const autosave = CG.debounce(() => {
    if (!CG.ready || restoring) return;
    CG.api('session_autosave', {state: collect()}).catch((e) => console.warn('autosave', e));
  }, 2000);

  function changed() {
    if (!CG.ready || restoring) return;
    autosave();
  }

  function collect() {
    const map = CG.mapLayer.map;
    const c = map.getCenter();
    const settings = JSON.parse(JSON.stringify(CG.settings));
    delete settings.lasso;
    settings.activeSection = CG.activeSection ? CG.activeSection.label : null;
    return {
      layers: CG.cats.map((L) => ({kind: 'catalog', path: L.path,
        options: L.mapping ? Object.assign({}, L.style, {mapping: L.mapping}) : L.style}))
        .concat(CG.stas.map((L) => ({kind: 'stations', path: L.path, options: L.style}))),
      view: {lat: c.lat, lon: c.lng, zoom: map.getZoom(), basemap: CG.settings.basemap},
      settings,
      sections: CG.sectionList.map((S) => ({
        label: S.label, lat1: S.lat1, lon1: S.lon1, lat2: S.lat2, lon2: S.lon2, width_km: S.width,
        options: {zmin: S.zmin, zmax: S.zmax, trueScale: S.trueScale, showBB: S.showBB,
          showTopo: S.showTopo, showSta: S.showSta}})),
      lasso: CG.settings.lasso,
    };
  }

  /* Deep merge of saved settings onto the defaults (unknown keys dropped). */
  function merge(def, saved) {
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return def;
    const out = Array.isArray(def) ? def.slice() : Object.assign({}, def);
    for (const k of Object.keys(def)) {
      if (!(k in saved)) continue;
      const d = def[k], v = saved[k];
      if (d && typeof d === 'object' && !Array.isArray(d)) out[k] = merge(d, v);
      else if (Array.isArray(d)) out[k] = Array.isArray(v) && v.length === d.length ? v.slice() : d;
      else if (d === null) out[k] = v;
      else if (v !== null && typeof v === typeof d) out[k] = v;
    }
    return out;
  }

  function setName(n) {
    current = n || null;
    document.getElementById('session-name').textContent = current && current !== '_last' ? 'sessione: ' + current : '';
  }

  /* Remove all data (files are not touched). */
  function clear(resetSettings) {
    CG.timebar.stop();
    CG.tools.cancel(false);
    CG.tools.clearMeasure();
    for (const L of CG.cats) CG.api('catalog_remove', {id: L.id}).catch(() => {});
    for (const L of CG.stas) CG.api('stations_remove', {id: L.id}).catch(() => {});
    CG.cats.length = 0;
    CG.stas.length = 0;
    CG.hover = null;
    CG.sections.clearAll();
    if (resetSettings !== false) {
      const keep = {basemap: CG.settings.basemap, panelHeight: CG.settings.panelHeight, sidebar: CG.settings.sidebar};
      CG.settings = Object.assign(CG.defaults(), keep);
      setName(null);
    }
    CG.settings.lasso = null;
    CG.tools.drawLasso();
    CG.mapLayer.renderStations();
    CG.ui.renderLayers();
    CG.ui.syncAll();
    CG.ui.updateLegend();
    CG.invalidate('data');
    changed();
  }

  async function restore(state) {
    restoring = true;
    try {
      clear(false);
      CG.settings = merge(CG.defaults(), state.settings || {});
      // colour maps that no longer exist (removed palettes) -> defaults
      const def = CG.defaults();
      for (const k of ['cmapDepth', 'cmapTime']) {
        if (!(CG.settings[k] in CG.config.cmaps)) CG.settings[k] = def[k];
      }
      CG.settings.lasso = Array.isArray(state.lasso) && state.lasso.length >= 3 ? state.lasso : null;
      if (state.view) {
        CG.mapLayer.setBasemap(state.view.basemap || CG.settings.basemap);
        CG.mapLayer.map.setView([state.view.lat, state.view.lon], state.view.zoom, {animate: false});
      }
      CG.ui.syncAll();
      CG.tools.drawLasso();
      const missing = [];
      for (const la of state.layers || []) {
        const fn = la.kind === 'catalog' ? CG.ui.loadCatalog : CG.ui.loadStations;
        const L = await fn(la.path, la.options || {}, {quiet: true, fit: !state.view});
        if (!L) missing.push(la.path);
      }
      let active = null;
      for (const s of state.sections || []) {
        const S = CG.sections.create(s.lat1, s.lon1, s.lat2, s.lon2,
          {label: s.label, width_km: s.width_km, options: s.options || {}, restoring: true});
        if (S && s.label === (state.settings || {}).activeSection) active = S;
      }
      if (CG.sectionList.length) CG.sections.setActive(active || CG.sectionList[CG.sectionList.length - 1]);
      setName(state.name);
      CG.ui.syncAll();
      CG.ui.renderLayers();
      CG.invalidate('data');
      if (CG.settings.tab) CG.ui.showTab(CG.settings.tab);
      if (missing.length) CG.toast('File non caricati: ' + missing.join(', '), 'error', 0);
      else if (state.name) CG.toast('Sessione ripresa: ' + state.name + (state.saved ? ' (' + state.saved + ')' : ''), 'ok');
    } catch (e) {
      CG.error(e, 'ripristino sessione');
    } finally {
      restoring = false;
    }
  }

  function saveDialog() {
    const def = current && current !== '_last' ? current : 'sessione_' + CG.stamp();
    CG.ui.prompt('Nome della sessione (salvata in codes/cgis/sessions/)', def, async (name) => {
      name = (name || '').trim();
      if (!name) return;
      try {
        const r = await CG.api('session_save', {name, state: collect()});
        setName(r.name);
        CG.toast('Sessione salvata: ' + r.path + '  ·  riprendi con: python3 cgis -res ' + r.name, 'ok', 10000);
      } catch (e) { CG.error(e, 'salvataggio sessione'); }
    });
  }

  async function load(nameOrPath) {
    const done = CG.busy('Apertura sessione…');
    try {
      const st = await CG.api('session_load', {name: nameOrPath});
      await restore(st);
    } catch (e) {
      CG.error(e, 'apertura sessione');
    } finally { done(); }
  }

  async function openDialog() {
    let list = [];
    try { list = (await CG.api('session_list', {})).sessions; } catch (e) { CG.error(e); return; }
    const body = document.createElement('div');
    const draw = () => {
      body.innerHTML = (CG.config.dialogs !== 'none' ? '<div class="row"><button id="ss-browse">Sfoglia…</button></div>' : '') +
        (list.length ? '<div class="file-list">' + list.map((s) =>
          '<div class="file sess" data-n="' + CG.esc(s.name) + '"><span>' + CG.esc(s.name === '_last' ? '_last (salvataggio automatico)' : s.name) +
          '</span><span class="muted">' + CG.esc(s.saved) + '</span>' +
          (s.name !== '_last' ? '<button class="icon del" title="Elimina">✕</button>' : '') + '</div>').join('') + '</div>'
          : '<p class="muted">Nessuna sessione salvata.</p>');
      body.querySelectorAll('.sess').forEach((d) => {
        d.onclick = (e) => {
          if (e.target.classList.contains('del')) return;
          close();
          load(d.dataset.n);
        };
        const del = d.querySelector('.del');
        if (del) del.onclick = (e) => {
          e.stopPropagation();
          CG.api('session_delete', {name: d.dataset.n}).then((r) => { list = r.sessions; draw(); }).catch((err) => CG.error(err));
        };
      });
      const br = body.querySelector('#ss-browse');
      if (br) br.onclick = async () => {
        try {
          const r = await CG.api('dialog_open', {kind: 'session'});
          if (r.paths && r.paths.length) { close(); load(r.paths[0]); }
        } catch (e) { CG.error(e); }
      };
    };
    const close = CG.ui.modal({title: 'Apri sessione', body, wide: true, focus: false, buttons: [{label: 'Chiudi'}]});
    draw();
  }

  return {changed, collect, restore, clear, saveDialog, openDialog, load, get name() { return current; }};
})();
