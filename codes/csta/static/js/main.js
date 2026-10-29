/* csta - start-up: configuration from the server, then the catalogues
 * opened from the command line (or the file chooser when there are none). */
'use strict';

(async function () {
  let init;
  try {
    init = await CS.api('init');
  } catch (e) {
    document.body.innerHTML = '<p style="padding:20px">csta: ' + CS.esc(e.message) + '</p>';
    return;
  }
  CS.config = init;
  document.title = 'csta ' + init.version;

  CS.map.init();
  CS.table.init();
  CS.ui.init();
  CS.setState(init.state);

  if (!init.state.catalogs.length) CS.ui.openFiles();
})();
