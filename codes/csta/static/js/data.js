/* csta - station rows of the visible catalogues, filters, selection.
 *
 * A row is one NET.STA: its displayed attributes are those of the first
 * catalogue (sidebar order) that contains it; ``cats`` lists the visible
 * catalogues containing it and ``differs`` tells whether their versions
 * differ. The selection is a set of NET.STA keys. */
'use strict';

(function () {
  const events = {};
  CS.on = (name, fn) => (events[name] = events[name] || []).push(fn);
  CS.emit = (name, ...args) => (events[name] || []).forEach((fn) => fn(...args));

  CS.filters = {text: '', net: '', band: '', cls: '', state: '', t0: null, t1: null,
    pres: '', rmax: null, lat0: null, lon0: null};

  CS.catById = new Map();
  CS.shownKeys = new Set();

  CS.visibleCats = () => CS.cats.filter((c) => !CS.hidden.has(c.id));

  function buildRows() {
    const rows = new Map();
    for (const c of CS.cats) {
      if (CS.hidden.has(c.id)) continue;
      for (const s of c.stations) {
        let r = rows.get(s.key);
        if (!r) {
          r = Object.assign({}, s, {cats: [], versions: new Map(), differs: false});
          rows.set(s.key, r);
        }
        r.cats.push(c.id);
        r.versions.set(c.id, s);
        if (s.sig !== r.sig) r.differs = true;
      }
    }
    CS.rows = [...rows.values()];
    CS.rowByKey = rows;
    for (const k of [...CS.sel]) if (!rows.has(k)) CS.sel.delete(k);
  }

  /* New state from the server (after every operation). */
  CS.setState = function (state) {
    const wasEmpty = !CS.rows.length;
    CS.state = state;
    CS.cats = state.catalogs;
    CS.catById = new Map(CS.cats.map((c) => [c.id, c]));
    for (const id of [...CS.hidden]) if (!CS.catById.has(id)) CS.hidden.delete(id);
    buildRows();
    CS.emit('state');
    CS.applyFilters();
    if (wasEmpty && CS.rows.length) CS.emit('fit');
  };

  CS.setHidden = function (cid, hidden) {
    if (hidden) CS.hidden.add(cid); else CS.hidden.delete(cid);
    buildRows();
    CS.emit('state');
    CS.applyFilters();
  };

  CS.applyFilters = function () {
    const f = CS.filters;
    const nvis = CS.visibleCats().length;
    const text = f.text.trim().toLowerCase();
    const useT = f.t0 !== null || f.t1 !== null;
    const t0 = f.t0 === null ? -Infinity : f.t0;
    const t1 = f.t1 === null ? Infinity : f.t1;
    const useR = f.rmax !== null && f.lat0 !== null && f.lon0 !== null;

    CS.shown = CS.rows.filter((r) => {
      if (text && !(CS.code(r).toLowerCase().includes(text) ||
                    (r.site || '').toLowerCase().includes(text))) return false;
      if (f.net && r.net !== f.net) return false;
      if (f.band && !r.bands.includes(f.band)) return false;
      if (f.cls && !r.classes.includes(f.cls)) return false;
      if (f.state === 'active' && !r.active) return false;
      if (f.state === 'closed' && r.active) return false;
      if (useT && !r.periods.some((p) => (p[0] === null || p[0] <= t1) &&
                                         (p[1] === null || p[1] >= t0))) return false;
      if (f.pres === 'all' && r.cats.length < nvis) return false;
      if (f.pres === 'one' && r.cats.length !== 1) return false;
      if (f.pres === 'multi' && r.cats.length < 2) return false;
      if (f.pres === 'diff' && !r.differs) return false;
      if (useR && CS.geo.vincenty(f.lat0, f.lon0, r.lat, r.lon).dist > f.rmax * 1000) return false;
      return true;
    });
    CS.shownKeys = new Set(CS.shown.map((r) => r.key));
    CS.emit('rows');
    CS.emit('sel');
  };

  /* mode: 'replace' | 'add' | 'remove' | 'toggle' */
  CS.select = function (keys, mode) {
    keys = keys.filter((k) => CS.rowByKey.has(k));
    if (!mode || mode === 'replace') CS.sel = new Set(keys);
    else if (mode === 'add') keys.forEach((k) => CS.sel.add(k));
    else if (mode === 'remove') keys.forEach((k) => CS.sel.delete(k));
    else if (mode === 'toggle') keys.forEach((k) => (CS.sel.has(k) ? CS.sel.delete(k) : CS.sel.add(k)));
    CS.emit('sel');
  };

  /* Selection mode of the area tools: Shift adds, Alt removes. */
  CS.modeFromEvent = (e) => (e && e.altKey ? 'remove' : e && (e.shiftKey || e.metaKey || e.ctrlKey) ? 'add' : 'replace');

  CS.setHover = function (key, src) {
    if (CS.hover === key) return;
    const old = CS.hover;
    CS.hover = key;
    CS.emit('hover', old, key, src);
  };

  /* Codes from a pasted list or a file: NET.STA, NET.STA.LOC.CHA or STA
   * (all the networks), separated by spaces, commas or new lines; text
   * after '#' is ignored. */
  CS.parseList = function (text) {
    const tokens = [];
    for (let line of String(text || '').split(/\r?\n/)) {
      line = line.replace(/#.*$/, '');
      for (const t of line.split(/[\s,;|]+/)) if (t) tokens.push(t.toUpperCase());
    }
    const byKey = new Map();
    const bySta = new Map();
    for (const r of CS.rows) {
      byKey.set(r.key.toUpperCase(), r.key);
      const s = r.sta.toUpperCase();
      if (!bySta.has(s)) bySta.set(s, []);
      bySta.get(s).push(r.key);
    }
    const keys = new Set();
    const missing = [];
    for (const t of tokens) {
      const parts = t.split('.');
      let found = [];
      if (parts.length >= 2 && parts[1]) {
        const k = byKey.get(parts[0] + '.' + parts[1]);
        found = k ? [k] : (bySta.get(parts[1]) || []).filter((x) => !CS.rowByKey.get(x).net);
      } else {
        found = bySta.get(parts[0]) || [];
      }
      if (found.length) found.forEach((k) => keys.add(k));
      else missing.push(t);
    }
    return {keys: [...keys], missing, n: tokens.length};
  };
})();
