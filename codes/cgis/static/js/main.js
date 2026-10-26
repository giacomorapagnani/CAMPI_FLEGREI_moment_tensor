/* cgis - start-up. */
'use strict';

(async function main() {
  try {
    CG.config = await CG.api('init');
  } catch (e) {
    document.body.innerHTML = '<div style="padding:40px;font:15px sans-serif">cgis: impossibile contattare il server (' +
      CG.esc(e.message) + ').</div>';
    return;
  }
  if (typeof L === 'undefined' || typeof Plotly === 'undefined') {
    CG.toast('Librerie Leaflet/Plotly non caricate: serve una connessione internet per le mappe.', 'error', 0);
    return;
  }
  CG.settings = CG.defaults();

  CG.mapLayer.init();
  CG.tools.init();
  CG.timebar.init();
  CG.sections.init();
  CG.ui.init();
  CG.ui.syncAll();
  CG.ui.updateLegend();
  CG.ready = true;
  CG.invalidate('data');

  const su = CG.config.startup || {};
  if (su.session) {
    await CG.session.restore(su.session);
  } else {
    for (const p of su.catalogs || []) await CG.ui.loadCatalog(p);
    for (const p of su.stations || []) await CG.ui.loadStations(p);
    if (!(su.catalogs || []).length && !(su.stations || []).length) {
      CG.toast('Aggiungi un catalogo o un file di stazioni con ＋ Catalogo / ＋ Stazioni. Premi ? per l\'aiuto.', 'info', 8000);
    }
  }
  setTimeout(() => CG.mapLayer.map.invalidateSize(), 100);
})();
