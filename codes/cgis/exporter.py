'''
Figure export with PyGMT (PDF, SVG, PNG): map, cross-section, time plot and
P/T-axes stereonet. Colours, sizes and beachball types follow the viewer
settings sent with the request. SVG is converted from the GMT PDF with
pdftocairo (poppler).

Symbol sizes are given in screen pixels in the viewer; in the figures
1 px = PX_CM * symbol_scale cm.
'''

import math
import os
import os.path as op
import shutil
import subprocess
import tempfile
import threading

import numpy as num

from pyrocko import util

from . import colormaps, geo, topography
from .stations import CLASS_COLORS, CLASS_ORDER, CLASS_LABELS
from .catalog import rotated_mt, BEACHBALL_TYPES

PX_CM = 0.02
FORMATS = ('pdf', 'svg', 'png')

_gmt_lock = threading.Lock()
_tmp_counter = [0]


class ExportError(Exception):
    pass


def _pygmt():
    '''
    Import pygmt. GMT_LIBRARY_PATH is set first: otherwise pygmt runs
    ``gmt --show-library`` at every module call (~0.5 s per call).
    '''
    if not os.environ.get('GMT_LIBRARY_PATH'):
        exe = shutil.which('gmt')
        if exe:
            try:
                lib = subprocess.run([exe, '--show-library'],
                                     capture_output=True, text=True,
                                     timeout=30).stdout.strip()
                if lib and op.isfile(lib):
                    os.environ['GMT_LIBRARY_PATH'] = op.dirname(lib)
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        import pygmt
    except Exception as e:
        raise ExportError('PyGMT non disponibile: %s' % e)
    return pygmt


# ----------------------------------------------------------------- helpers


def _opt(d, key, default, typ=float):
    v = d.get(key, default)
    if v is None:
        return default
    try:
        v = typ(v)
    except (TypeError, ValueError):
        raise ExportError('invalid value for %s: %r' % (key, v))
    if typ is float and not math.isfinite(v):
        raise ExportError('invalid value for %s' % key)
    return v


def _out_path(req):
    path = req.get('path')
    if not path:
        raise ExportError('nessun file di uscita')
    path = op.abspath(op.expanduser(str(path)))
    fmt = op.splitext(path)[1].lower().lstrip('.')
    if fmt not in FORMATS:
        raise ExportError('formato .%s non supportato (usa pdf, svg o png)'
                          % fmt)
    os.makedirs(op.dirname(path), exist_ok=True)
    return path, fmt


def _gmt_text(s):
    '''Text for GMT text labels (Latin-1).'''
    s = str(s or '').replace('\u2032', "'")
    return s.encode('latin-1', 'replace').decode('latin-1')


def _gmt_label(s):
    '''Text for -B titles/labels: quotes would break the GMT arguments.'''
    return _gmt_text(s).replace('"', '').replace("'", '')


def _save(fig, path, fmt, tmp):
    if fmt == 'pdf':
        fig.savefig(path)
    elif fmt == 'png':
        fig.savefig(path, dpi=300)
    else:
        exe = shutil.which('pdftocairo')
        if exe is None:
            raise ExportError(
                'l\'export SVG richiede pdftocairo (brew install poppler)')
        pdf = op.join(tmp, 'figure.pdf')
        fig.savefig(pdf)
        p = subprocess.run([exe, '-svg', pdf, path], capture_output=True,
                           text=True)
        if p.returncode != 0:
            raise ExportError('pdftocairo non riuscito: %s' % p.stderr.strip())
    if not op.isfile(path):
        raise ExportError('la figura non è stata scritta')


_year_cache = {}


def _year_start(year):
    if year not in _year_cache:
        _year_cache[year] = util.str_to_time('%04d-01-01 00:00:00' % year)
    return _year_cache[year]


def decimal_year(t):
    '''Decimal year of pyrocko (UTC) times, vectorised.'''
    t = num.atleast_1d(num.asarray(t, dtype=float))
    out = num.full(t.shape, num.nan)
    ok = num.isfinite(t)
    if not ok.any():
        return out
    y0 = int(util.time_to_str(t[ok].min(), format='%Y'))
    y1 = int(util.time_to_str(t[ok].max(), format='%Y')) + 1
    years = num.arange(y0, y1 + 1)
    starts = num.array([_year_start(int(y)) for y in years])
    i = num.clip(num.searchsorted(starts, t[ok], side='right') - 1, 0,
                 len(years) - 2)
    out[ok] = years[i] + (t[ok] - starts[i]) / (starts[i + 1] - starts[i])
    return out


def _datetimes(t):
    '''pyrocko (UTC) times -> numpy datetime64[ms] (timezone free).'''
    return num.round(num.asarray(t, dtype=float) * 1000.).astype(
        'int64').astype('datetime64[ms]')


def _iso(t):
    return util.time_to_str(t, format='%Y-%m-%dT%H:%M:%S.3FRAC')


class Style:
    '''Viewer style: colour mapping, symbol sizes, beachballs.'''

    def __init__(self, d):
        d = d or {}
        self.color_by = d.get('color_by', 'depth')
        if self.color_by not in ('depth', 'time'):
            raise ExportError('invalid color_by: %s' % self.color_by)
        self.cmap = d.get('cmap') or (colormaps.DEFAULT_DEPTH_CMAP
                                      if self.color_by == 'depth'
                                      else colormaps.DEFAULT_TIME_CMAP)
        if self.cmap not in colormaps.CMAPS:     # e.g. from an old session
            self.cmap = colormaps.DEFAULT_DEPTH_CMAP \
                if self.color_by == 'depth' else colormaps.DEFAULT_TIME_CMAP
        self.reverse = bool(d.get('reverse', False))
        self.vmin = _opt(d, 'vmin', 0.)
        self.vmax = _opt(d, 'vmax', 1.)
        s = d.get('size') or {}
        self.base = _opt(s, 'base', 4.)
        self.growth = _opt(s, 'growth', 1.8)
        self.ref = _opt(s, 'ref', 1.)
        self.nomag = _opt(s, 'nomag', 4.)
        self.rmin = _opt(s, 'min', 1.5)
        self.rmax = _opt(s, 'max', 60.)
        self.bb_type = d.get('bb_type', 'deviatoric')
        if self.bb_type not in BEACHBALL_TYPES:
            raise ExportError('invalid beachball type: %s' % self.bb_type)
        self.bb_scale = _opt(d, 'bb_scale', 1.6)
        self.symbol_scale = _opt(d, 'symbol_scale', 1.)
        # optional colouring (faulting style, %CLVD, %ISO, tag): the
        # colours come per event from the viewer, with legend information
        self.attr = d.get('attr') or None

    def radius_px(self, mag):
        mag = num.asarray(mag, dtype=float)
        r = num.full(mag.shape, self.nomag)
        ok = num.isfinite(mag)
        r[ok] = num.clip(self.base * self.growth ** (mag[ok] - self.ref),
                         self.rmin, self.rmax)
        return r

    def diameter_cm(self, mag, layer_scale=1.):
        return 2. * self.radius_px(mag) * layer_scale * PX_CM \
            * self.symbol_scale

    def values(self, cat, idx):
        '''Colour values in CPT units (depth km or decimal year).'''
        if self.color_by == 'depth':
            return cat.depth_km[idx]
        if getattr(cat, 'no_time', False):
            return num.full(len(idx), num.nan)
        return decimal_year(cat.time[idx])

    def cpt_range(self):
        if self.color_by == 'depth':
            return self.vmin, self.vmax
        a, b = decimal_year([self.vmin, self.vmax])
        return a, b

    def label(self):
        return 'Depth (km)' if self.color_by == 'depth' \
            else 'Origin time (year)'

    def write_cpt(self, tmp):
        path = op.join(tmp, 'events.cpt')
        vmin, vmax = self.cpt_range()
        colormaps.write_cpt(path, self.cmap, vmin, vmax, self.reverse)
        return path


class Layer:
    '''One catalogue as requested for export.'''

    def __init__(self, app, d):
        self.cat = app.catalog(d.get('id'))
        n = len(self.cat.events)

        def idx(key):
            a = num.array(sorted(set(int(i) for i in d.get(key) or [])),
                          dtype=int)
            return a[(a >= 0) & (a < n)]

        self.idx = idx('indices')
        self.grey = num.setdiff1d(idx('grey'), self.idx)
        color = d.get('color')
        self.color = colormaps.hex_color(colormaps.parse_hex(color)) \
            if color else None
        self.opacity = min(1., max(0.05, _opt(d, 'opacity', 0.85)))
        self.size_scale = max(0.05, _opt(d, 'size_scale', 1.))
        self.beachballs = bool(d.get('beachballs', True)) \
            and self.cat.has_mt
        self.name = d.get('name') or self.cat.name
        self.explicit = None
        cols = d.get('colors')
        if cols is not None:
            raw = [int(i) for i in d.get('indices') or []]
            if len(cols) != len(raw):
                raise ExportError('colours and indices do not match')
            self.explicit = {
                i: colormaps.hex_color(colormaps.parse_hex(c))
                for (i, c) in zip(raw, cols)}

    @property
    def transparency(self):
        return int(round((1. - self.opacity) * 100.))


def _layers(app, req):
    return [Layer(app, d) for d in req.get('layers', [])]


def _m6_use(mt):
    '''Normalised moment tensor in GMT order (mrr mtt mff mrt mrf mtf).'''
    m6 = num.array(mt.m6_up_south_east(), dtype=float)
    norm = num.max(num.abs(m6))
    return m6 / norm if norm > 0 else m6


def _fill(layer, style, idx, cpt, tmp):
    '''Colour values and CPT for the events ``idx`` of an auto layer.'''
    if layer.explicit is None:
        return style.values(layer.cat, idx), cpt
    hexes = [layer.explicit.get(int(i), '#a0a0a0') for i in idx]
    uniq = sorted(set(hexes))
    code = {h: k for (k, h) in enumerate(uniq)}
    _tmp_counter[0] += 1
    path = op.join(tmp, 'categorical_%d.cpt' % _tmp_counter[0])
    with open(path, 'w') as f:
        for h, k in code.items():
            rgb = '%d/%d/%d' % colormaps.parse_hex(h)
            f.write('%g %s %g %s\n' % (k - 0.5, rgb, k + 0.5, rgb))
    return num.array([code[h] for h in hexes], dtype=float), path


def _plot_events(fig, layer, style, x, y, idx, cpt, tmp, mts=None,
                 grey=False):
    """
    Draw events ``idx`` of a layer at plot coordinates (x, y): circles, and
    beachballs for MT events when enabled (``mts`` maps event index to the
    moment tensor to draw, rotated for sections). Largest symbols are drawn
    first so that small events stay visible.
    """
    pygmt = _pygmt()
    if len(idx) == 0:
        return
    cat = layer.cat
    diam = style.diameter_cm(cat.mag[idx], layer.size_scale)

    if grey:
        order = num.argsort(-diam)
        fig.plot(x=x[order], y=y[order], style='c', size=diam[order] * 0.7,
                 fill='190/190/190', pen='0.15p,150/150/150',
                 transparency=40)
        return

    is_bb = num.zeros(len(idx), dtype=bool)
    if layer.beachballs and mts is not None:
        is_bb = num.array([int(i) in mts for i in idx], dtype=bool)

    circ = ~is_bb
    if circ.any():
        order = num.nonzero(circ)[0][num.argsort(-diam[circ])]
        kwargs = dict(x=x[order], y=y[order], style='c', size=diam[order],
                      pen='0.25p,40/40/40')
        if layer.transparency > 0:
            kwargs['transparency'] = layer.transparency
        if layer.color:
            kwargs['fill'] = layer.color
        else:
            kwargs['fill'], kwargs['cmap'] = _fill(layer, style, idx[order],
                                                   cpt, tmp)
        fig.plot(**kwargs)

    if is_bb.any():
        sel = num.nonzero(is_bb)[0]
        bdiam = num.maximum(diam[sel] * style.bb_scale, 0.05)
        vals, bb_cpt = _fill(layer, style, idx[sel], cpt, tmp)
        order = num.argsort(-bdiam)
        _tmp_counter[0] += 1
        fn = op.join(tmp, 'meca_%d.txt' % _tmp_counter[0])
        with open(fn, 'w') as f:
            for j in order:
                k = sel[j]
                mt = mts[int(idx[k])]
                v = vals[j] if math.isfinite(vals[j]) else 0.
                if style.bb_type == 'dc':
                    st, dp, rk = mt.both_strike_dip_rake()[0]
                    cols = (st, dp, rk, 5.)
                else:
                    cols = tuple(_m6_use(mt)) + (23,)
                f.write(' '.join('%.10g' % c for c in
                                 (x[k], y[k], v) + cols + (bdiam[j],))
                        + '\n')
        # no numeric scale: GMT reads the size (cm) from the last column
        kwargs = dict(spec=fn, scale='+m', extensionfill='white',
                      pen='0.35p,30/30/30')
        if style.bb_type == 'dc':
            kwargs['convention'] = 'aki'
        else:
            kwargs['convention'] = 'mt'
            kwargs['component'] = style.bb_type
        if layer.color:
            kwargs['compressionfill'] = layer.color
        else:
            kwargs['cmap'] = bb_cpt
        if layer.transparency > 0:
            kwargs['transparency'] = layer.transparency
        with pygmt.config(PROJ_LENGTH_UNIT='c'):
            fig.meca(**kwargs)


def _any_auto(layers):
    return any(la.color is None and len(la.idx) > 0 for la in layers)


def _ref_mags(layers):
    """Up to 4 integer magnitudes spanning the plotted range."""
    mags = num.concatenate([la.cat.mag[la.idx] for la in layers]
                           + [num.zeros(0)])
    mags = mags[num.isfinite(mags)]
    if mags.size == 0:
        return []
    lo = int(math.ceil(mags.min()))
    hi = int(math.floor(mags.max()))
    if hi < lo:
        return [float(round(float(mags.mean()), 1))]
    vals = list(range(lo, hi + 1))
    step = int(math.ceil(len(vals) / 4.))
    vals = vals[::-1][::step][::-1]       # always keep the largest
    return [float(v) for v in vals]


def _mag_legend(fig, layers, style, tmp, position, horizontal=False,
                max_width=None):
    """Magnitude legend with the same symbol sizes as the plot."""
    mags = _ref_mags(layers)
    if not mags:
        return
    scale = max((la.size_scale for la in layers if len(la.idx)),
                default=1.)
    diam = style.diameter_cm(num.array(mags), scale)
    dmax = float(diam.max())
    row = 0.3       # approximate height of a text row (cm)
    if horizontal and max_width is not None \
            and (dmax + 0.75) * len(mags) + 0.1 > max_width:
        horizontal = False
    spec = op.join(tmp, 'maglegend_%d.txt' % id(layers))
    with open(spec, 'w') as f:
        f.write('H 8p,Helvetica-Bold Magnitude\n')
        if horizontal:
            gap = max(0., dmax - row) / 2.
            f.write('G %.3fc\n' % gap)
            f.write('N %d\n' % len(mags))
            for m, d in zip(mags, diam):
                f.write('S %.3fc c %.3fc 200/200/200 0.25p,40/40/40 '
                        '%.3fc %g\n' % (dmax / 2. + 0.05, d, dmax + 0.2, m))
            f.write('G %.3fc\n' % gap)
            width = (dmax + 0.75) * len(mags) + 0.1
        else:
            for m, d in zip(mags, diam):
                gap = max(0., d - row) / 2.
                f.write('G %.3fc\n' % gap)
                f.write('S %.3fc c %.3fc 200/200/200 0.25p,40/40/40 '
                        '%.3fc %g\n' % (dmax / 2. + 0.05, d, dmax + 0.25, m))
                f.write('G %.3fc\n' % gap)
            width = dmax + 1.0
    fig.legend(spec=spec, position=position + '+w%.2fc' % max(width, 1.8),
               box='+gwhite@15+p0.4p,gray40+c0.1c')


def _colorbar(fig, style, cpt, position, tmp=None):
    '''
    Colour key below the plot: colour bar for depth/time (or %CLVD/%ISO),
    legend for categorical colours (faulting style, tags).
    '''
    attr = style.attr
    if not attr:
        fig.colorbar(cmap=cpt, position=position,
                     frame=['xaf+l%s' % style.label()])
        return
    label = _gmt_label(attr.get('label') or '')
    cats = attr.get('categories')
    if cats and tmp:
        cats = cats[:12]
        spec = op.join(tmp, 'catlegend.txt')
        ncol = min(4, len(cats) + 1)
        with open(spec, 'w') as f:
            f.write('H 8p,Helvetica-Bold %s\n' % label)
            f.write('N %d\n' % ncol)
            for c in cats:
                f.write('S 0.2c c 0.25c %s 0.25p,40/40/40 0.45c %s\n' % (
                    colormaps.hex_color(colormaps.parse_hex(c.get('color'))),
                    _gmt_text(c.get('label'))))
            f.write('S 0.2c c 0.25c 160/160/160 0.25p,40/40/40 0.45c altri\n')
        pos = position.split('+w')[0] + '+jTC+w%gc' % (ncol * 3.2)
        fig.legend(spec=spec, position=pos, box='+gwhite+p0.4p,gray40+c0.1c')
        return
    rng = attr.get('range')
    if rng and tmp:
        path = op.join(tmp, 'attr.cpt')
        colormaps.write_cpt(path, style.cmap, float(rng[0]), float(rng[1]),
                            style.reverse)
        fig.colorbar(cmap=path, position=position,
                     frame=['xaf+l%s' % label])


def _station_xy(app, req):
    out = []
    for d in req.get('stations', []):
        ss = app.station_set(d.get('id'))
        out.append((ss, bool(d.get('labels', False))))
    return out


def _station_items(sets, xy):
    """
    Station symbols to draw: ``xy(station)`` returns plot coordinates
    (x, y) or None to skip the station.
    """
    items = []
    for ss, labels in sets:
        for st in ss.stations:
            p = xy(st)
            if p is None:
                continue
            x, y = p
            if math.isfinite(x) and math.isfinite(y):
                items.append((x, y, st['cls'],
                              _gmt_text(st['sta']) if labels else None))
    return items


def _plot_stations(fig, items, size_cm=0.32):
    if not items:
        return
    xs = num.array([it[0] for it in items], dtype=float)
    ys = num.array([it[1] for it in items], dtype=float)
    cls = num.array([it[2] for it in items])
    for c in CLASS_ORDER:
        sel = cls == c
        if sel.any():
            fig.plot(x=xs[sel], y=ys[sel], style='t%.2fc' % size_cm,
                     fill=CLASS_COLORS[c], pen='0.5p,black')
    lab = [i for i, it in enumerate(items) if it[3]]
    if lab:
        fig.text(x=xs[lab], y=ys[lab], text=[items[i][3] for i in lab],
                 font='6p,Helvetica,black', justify='CB',
                 offset='0c/%.2fc' % (size_cm * 0.65))


def _section_station_items(sets, lat1, lon1, lat2, lon2, wkm, length, yfunc):
    items = []
    for ss, labels in sets:
        if not ss.stations:
            continue
        s_, d_, _, _ = geo.project(lat1, lon1, lat2, lon2,
                                   [st['lat'] for st in ss.stations],
                                   [st['lon'] for st in ss.stations])
        for st, si, di in zip(ss.stations, s_, d_):
            if abs(di) <= 0.5 * wkm and 0. <= si <= length:
                items.append((float(si), float(yfunc(st, si)), st['cls'],
                              _gmt_text(st['sta']) if labels else None))
    return items


def _station_legend_entries(sets):
    classes = []
    for ss, _ in sets:
        for s in ss.stations:
            if s['cls'] not in classes:
                classes.append(s['cls'])
    return [c for c in CLASS_ORDER if c in classes]


def _station_legend(fig, sets, tmp, position):
    classes = _station_legend_entries(sets)
    if not classes:
        return
    spec = op.join(tmp, 'stalegend.txt')
    with open(spec, 'w') as f:
        f.write('H 8p,Helvetica-Bold Stations\n')
        for c in classes:
            f.write('S 0.2c t 0.28c %s 0.5p,black 0.5c %s\n'
                    % (CLASS_COLORS[c], CLASS_LABELS[c]))
    fig.legend(spec=spec, position=position,
               box='+gwhite@15+p0.4p,gray40+c0.1c')


# -------------------------------------------------------------- topography


_RELIEF_RES = [('01s', 1), ('03s', 3), ('15s', 15), ('30s', 30), ('01m', 60),
               ('02m', 120), ('03m', 180), ('05m', 300), ('10m', 600),
               ('15m', 900), ('30m', 1800), ('01d', 3600)]


def _relief_resolution(span_deg, max_cells):
    target = span_deg * 3600. / max_cells
    ok = [name for name, sec in _RELIEF_RES if sec <= target]
    return ok[-1] if ok else _RELIEF_RES[0][0]


def _coast_resolution(span_deg):
    return 'f' if span_deg < 3 else ('h' if span_deg < 10 else
                                      ('i' if span_deg < 40 else 'l'))


def _upsample(grid, max_cells, max_factor=8.):
    '''
    Cubic resampling of a coarse DEM to the output resolution, so that the
    hillshading is computed on a smooth surface (no 90 m blocks).
    '''
    import xarray as xr
    from scipy import ndimage

    z = num.asarray(grid.values, dtype=float)
    ny, nx = z.shape
    factor = min(max_factor, max_cells / float(max(nx, ny)))
    if factor < 1.5 or nx < 4 or ny < 4:
        return grid
    lon = num.asarray(grid.coords[grid.dims[1]].values, dtype=float)
    lat = num.asarray(grid.coords[grid.dims[0]].values, dtype=float)
    nan = ~num.isfinite(z)
    zf = num.where(nan, 0., z)
    nnx = int(round((nx - 1) * factor)) + 1
    nny = int(round((ny - 1) * factor)) + 1
    zz = ndimage.zoom(zf, (nny / ny, nnx / nx), order=3, mode='nearest')
    if nan.any():
        mask = ndimage.zoom(nan.astype(num.uint8), (nny / ny, nnx / nx),
                            order=0, mode='nearest').astype(bool)
        zz[mask] = num.nan
    nny, nnx = zz.shape
    return xr.DataArray(
        zz.astype(num.float32),
        coords={'lat': num.linspace(lat[0], lat[-1], nny),
                'lon': num.linspace(lon[0], lon[-1], nnx)},
        dims=['lat', 'lon'])


def _sea_to_nan(z, sea):
    '''
    Sea cells -> NaN (painted with the water colour), except a one-cell band
    along the coast kept at 0 m. The exact coastline is then drawn by the
    GSHHG water fill: the band avoids water-coloured DEM steps on land, the
    NaN sea hides the hairline joints between the GSHHG polygons.
    '''
    from scipy import ndimage
    z = num.array(z, dtype=float)
    deep = ndimage.binary_erosion(sea, iterations=1, border_value=1)
    z[sea & ~deep] = 0.
    z[deep] = num.nan
    return z


def _draw_topography(fig, region, projection, width_cm, opts, tmp):
    pygmt = _pygmt()
    import xarray as xr

    source = opts.get('topo', 'pyrocko')
    water = colormaps.hex_color(colormaps.parse_hex(
        opts.get('water', '#a8b4bc'), (168, 180, 188)))
    bathy = bool(opts.get('bathymetry', False))
    span = max(region[1] - region[0], region[3] - region[2])
    cres = _coast_resolution(span)

    if source == 'none':
        try:
            fig.coast(land='245/245/240', water=water,
                      shorelines='0.4p,gray30', resolution=cres)
        except Exception:
            pass
        return None

    pad_x = 0.03 * (region[1] - region[0])
    pad_y = 0.03 * (region[3] - region[2])
    padded = [region[0] - pad_x, region[1] + pad_x,
              region[2] - pad_y, region[3] + pad_y]
    max_cells = int(min(4000, max(300, width_cm / 2.54 * 300)))

    if source == 'pyrocko':
        xs, ys, z, name = topography.grid(padded, max_cells=max_cells,
                                          bathymetry=bathy)
        if not bathy:
            z = _sea_to_nan(z, ~num.isfinite(z))
        grid = xr.DataArray(z.astype(num.float32),
                            coords={'lat': ys, 'lon': xs},
                            dims=['lat', 'lon'])
    elif source == 'gmt':
        res = _relief_resolution(span, max_cells)
        try:
            grid = pygmt.datasets.load_earth_relief(
                resolution=res, region=padded, registration='gridline')
        except Exception as e:
            raise ExportError('impossibile scaricare GMT earth_relief_%s: %s'
                              % (res, e))
        if not bathy:
            zg = num.asarray(grid.values, dtype=float)
            grid = grid.copy(data=_sea_to_nan(zg, ~(zg > 0.)).astype(
                num.float32))
        name = 'GMT earth_relief_%s' % res
    else:
        raise ExportError('unknown topography source: %s' % source)

    grid = _upsample(grid, max_cells)
    zvals = num.asarray(grid.values, dtype=float)
    zmax = topography.nice_max(zvals)
    zmin = float(num.nanmin(zvals)) if bathy and num.isfinite(
        zvals).any() else None
    cpt = op.join(tmp, 'topo.cpt')
    colormaps.write_topo_cpt(cpt, opts.get('palette', 'gray'), zmax,
                             colormaps.parse_hex(water), zmin)
    with pygmt.config(COLOR_NAN='%d/%d/%d' % colormaps.parse_hex(water)):
        fig.grdimage(grid=grid, cmap=cpt, shading='+a315+ne0.6',
                     region=region, projection=projection, dpi=300)
    try:
        if not bathy:
            fig.coast(water=water, resolution=cres)
        fig.coast(shorelines='0.4p,gray30', resolution=cres)
    except Exception:
        pass
    return name


# --------------------------------------------------------------------- map


def _map_scale_km(region):
    lat = 0.5 * (region[2] + region[3])
    from pyrocko import orthodrome as od
    w = od.distance_accurate50m(lat, region[0], lat, region[1]) / 1000.
    return geo.nice_floor(w / 4.)


def export_map(app, req):
    pygmt = _pygmt()

    path, fmt = _out_path(req)
    opts = req.get('options') or {}
    try:
        w, e, s, n = [float(x) for x in req['region']]
    except (KeyError, TypeError, ValueError):
        raise ExportError('area non valida')
    if not (e > w and n > s and -90. <= s and n <= 90.
            and e - w <= 360.):
        raise ExportError('area non valida: lon %g/%g lat %g/%g'
                          % (w, e, s, n))
    region = [w, e, s, n]
    width = min(60., max(4., _opt(opts, 'width_cm', 16.)))
    style = Style(req.get('style'))
    layers = _layers(app, req)
    sta_sets = _station_xy(app, req) if opts.get('stations', True) else []

    with _gmt_lock, tempfile.TemporaryDirectory(prefix='cgis_') as tmp:
        fig = pygmt.Figure()
        projection = 'M%gc' % width
        title = _gmt_label(opts.get('title', ''))
        frame = ['WSne' + ('+t"%s"' % title if title else ''), 'af']
        with pygmt.config(FORMAT_GEO_MAP='ddd.xxF',
                          FONT_ANNOT_PRIMARY='8p,Helvetica,black',
                          FONT_LABEL='9p,Helvetica,black',
                          FONT_TITLE='12p,Helvetica-Bold,black',
                          MAP_FRAME_TYPE='plain',
                          MAP_TITLE_OFFSET='6p'):
            fig.basemap(region=region, projection=projection, frame=frame)
            _draw_topography(fig, region, projection, width, opts, tmp)

            # cross-section traces
            for sec in (req.get('sections') or []):
                try:
                    la1, lo1 = float(sec['lat1']), float(sec['lon1'])
                    la2, lo2 = float(sec['lat2']), float(sec['lon2'])
                    wkm = float(sec.get('width_km', 0.))
                except (KeyError, TypeError, ValueError):
                    raise ExportError('invalid section in request')
                if wkm > 0 and opts.get('corridors', True):
                    plats, plons = geo.corridor_polygon(la1, lo1, la2, lo2,
                                                        wkm)
                    fig.plot(x=plons, y=plats, pen='0.6p,black,-',
                             fill='black@90')
                fig.plot(x=[lo1, lo2], y=[la1, la2], pen='1.3p,black')
                lab = _gmt_text(sec.get('label', ''))
                fig.text(x=[lo1, lo2], y=[la1, la2],
                         text=[lab, lab + "'"],
                         font='9p,Helvetica-Bold,black', justify='CM',
                         fill='white@20', clearance='0.05c/0.05c')

            cpt = style.write_cpt(tmp)
            for la in layers:
                cat = la.cat
                if len(la.grey):
                    _plot_events(fig, la, style, cat.lon[la.grey],
                                 cat.lat[la.grey], la.grey, cpt, tmp,
                                 grey=True)
            for la in layers:
                cat = la.cat
                mts = {i: cat.mts[cat.mt_index[i]] for i in la.idx
                       if cat.mt_index[i] >= 0} if la.beachballs else None
                _plot_events(fig, la, style, cat.lon[la.idx],
                             cat.lat[la.idx], la.idx, cpt, tmp, mts=mts)

            _plot_stations(fig, _station_items(
                sta_sets, lambda st: (st['lon'], st['lat'])))

            if opts.get('scalebar', True):
                km = _map_scale_km(region)
                fig.basemap(map_scale='jBL+w%gk+o0.4c/0.4c+f+u' % km,
                            box='+gwhite@25+p0.3p,gray40+c0.1c')

            if opts.get('mag_legend', True):
                # legend for the events inside the figure only
                inside = []
                for la in layers:
                    lo = la.cat.lon[la.idx]
                    la_ = la.cat.lat[la.idx]
                    m = (lo >= w) & (lo <= e) & (la_ >= s) & (la_ <= n)
                    inside.append(_Sub(la, la.idx[m]))
                _mag_legend(fig, inside, style, tmp, 'jTR+jTR+o0.2c')
            if sta_sets and opts.get('station_legend', True):
                _station_legend(fig, sta_sets, tmp, 'jTL+jTL+o0.2c')

            fig.basemap(frame=frame)

            if opts.get('colorbar', True) and _any_auto(layers):
                _colorbar(fig, style, cpt,
                          'JBC+w%gc/0.25c+o0c/0.9c+h' % (0.5 * width), tmp)

        _save(fig, path, fmt, tmp)
    return {'path': path}


# ----------------------------------------------------------------- section


def export_section(app, req):
    pygmt = _pygmt()

    path, fmt = _out_path(req)
    opts = req.get('options') or {}
    sec = req.get('section') or {}
    try:
        lat1, lon1 = float(sec['lat1']), float(sec['lon1'])
        lat2, lon2 = float(sec['lat2']), float(sec['lon2'])
        wkm = float(sec['width_km'])
    except (KeyError, TypeError, ValueError):
        raise ExportError('invalid section definition')
    if not wkm > 0:
        raise ExportError('la larghezza della sezione deve essere positiva')
    label = _gmt_text(sec.get('label', 'A'))
    length, azimuth = geo.section_frame(lat1, lon1, lat2, lon2)

    style = Style(req.get('style'))
    layers = _layers(app, req)
    sta_sets = _station_xy(app, req) if opts.get('stations', True) else []

    # events inside the corridor
    sel = []
    for la in layers:
        cat = la.cat
        s, d, _, _ = geo.project(lat1, lon1, lat2, lon2, cat.lat, cat.lon)
        inside = (num.abs(d) <= 0.5 * wkm) & (s >= 0.) & (s <= length)
        ii = la.idx[inside[la.idx]]
        gg = la.grey[inside[la.grey]]
        sel.append((la, s, ii, gg))

    depths = num.concatenate(
        [la.cat.depth_km[ii] for (la, _, ii, _) in sel] + [num.zeros(0)])
    depths = depths[num.isfinite(depths)]
    zmin = opts.get('depth_min')
    zmax = opts.get('depth_max')
    if depths.size:
        pad = max(0.1, 0.05 * (depths.max() - depths.min()))
        auto_min = min(0., depths.min() - pad)
        auto_max = depths.max() + pad
    else:
        auto_min, auto_max = 0., 10.
    zmin = auto_min if zmin is None else float(zmin)
    zmax = auto_max if zmax is None else float(zmax)
    if not zmax > zmin:
        raise ExportError('profondità: max deve essere maggiore di min')

    width = min(60., max(4., _opt(opts, 'width_cm', 16.)))
    if opts.get('true_scale', False):
        height = width * (zmax - zmin) / length
        if height > 60.:
            raise ExportError(
                'in scala reale la sezione sarebbe alta %.0f cm: riduci '
                'l\'intervallo di profondità o disattiva la scala reale'
                % height)
        height = max(height, 1.5)
    else:
        height = min(60., max(2., _opt(opts, 'height_cm', 8.)))

    show_topo = bool(opts.get('topo', True))
    topo_h = min(10., max(0.8, _opt(opts, 'topo_height_cm', 2.2)))
    title = _gmt_label(opts.get('title', ''))

    prof = None
    if show_topo:
        try:
            ps, pe, _ = topography.profile(
                lat1, lon1, lat2, lon2, n=600,
                bathymetry=bool(opts.get('bathymetry', False)))
            if num.isfinite(pe).any():
                prof = (ps, num.nan_to_num(pe, nan=0.))
        except topography.TopoError:
            prof = None

    with _gmt_lock, tempfile.TemporaryDirectory(prefix='cgis_') as tmp:
        fig = pygmt.Figure()
        cpt = style.write_cpt(tmp)
        with pygmt.config(FONT_ANNOT_PRIMARY='8p,Helvetica,black',
                          FONT_LABEL='9p,Helvetica,black',
                          FONT_TITLE='12p,Helvetica-Bold,black',
                          MAP_FRAME_TYPE='plain', MAP_TITLE_OFFSET='6p'):

            proj = 'X%gc/-%gc' % (width, height)
            fig.basemap(region=[0, length, zmin, zmax], projection=proj,
                        frame=['WSne' + ('+t"%s"' % title
                                         if title and prof is None else ''),
                               'xaf+lDistance along profile (km)',
                               'yaf+lDepth (km)'])
            if zmin < 0. < zmax:
                fig.plot(x=[0, length], y=[0, 0], pen='0.4p,gray50,-')

            for (la, s, ii, gg) in sel:
                if len(gg):
                    _plot_events(fig, la, style, s[gg],
                                 la.cat.depth_km[gg], gg, cpt, tmp,
                                 grey=True)
            for (la, s, ii, gg) in sel:
                cat = la.cat
                mts = {i: rotated_mt(cat.mts[cat.mt_index[i]], azimuth)
                       for i in ii if cat.mt_index[i] >= 0} \
                    if la.beachballs and opts.get('beachballs', True) \
                    else None
                y = cat.depth_km[ii]
                ok = num.isfinite(y)
                _plot_events(fig, la, style, s[ii][ok], y[ok], ii[ok], cpt,
                             tmp, mts=mts)

            # stations without a topography panel: at the top of the frame
            if sta_sets and prof is None:
                _plot_stations(fig, _section_station_items(
                    sta_sets, lat1, lon1, lat2, lon2, wkm, length,
                    lambda st, si: zmin), size_cm=0.3)

            if opts.get('colorbar', True) and _any_auto(
                    [la for (la, _, ii, _) in sel]):
                _colorbar(fig, style, cpt,
                          'JBL+jTL+w%gc/0.25c+o0.2c/1.35c+h' % (0.42 * width),
                          tmp)
            if opts.get('mag_legend', True):
                _mag_legend(
                    fig, [_Sub(la, ii) for (la, _, ii, _) in sel], style,
                    tmp, 'JBR+jTR+o0c/1.15c', horizontal=True,
                    max_width=0.5 * width)

            # topography panel on top
            if prof is not None:
                ps, pe = prof
                emax = max(10., float(pe.max()))
                emin = min(0., float(pe.min()))
                span = emax - emin
                emax += 0.15 * span
                emin -= 0.05 * span
                fig.shift_origin(yshift='%gc' % (height + 0.25))
                fig.basemap(region=[0, length, emin, emax],
                            projection='X%gc/%gc' % (width, topo_h),
                            frame=['Wsne' + ('+t"%s"' % title
                                             if title else ''),
                                   'xaf', 'ya+lElev. (m)'])
                poly_x = num.concatenate([[0.], ps, [length]])
                poly_y = num.concatenate([[emin], pe, [emin]])
                fig.plot(x=poly_x, y=poly_y, fill='215/215/210',
                         pen='0.8p,40/40/40', close=True)
                if emin < 0.:
                    fig.plot(x=[0, length], y=[0, 0], pen='0.4p,90/120/160')
                if sta_sets:
                    def elev(st, si, ps=ps, pe=pe):
                        if st['elev'] is not None:
                            return st['elev']
                        return float(num.interp(si, ps, pe))
                    _plot_stations(fig, _section_station_items(
                        sta_sets, lat1, lon1, lat2, lon2, wkm, length,
                        elev), size_cm=0.3)
                fig.text(x=[0, length], y=[emax, emax],
                         text=[label, label + "'"],
                         font='11p,Helvetica-Bold,black',
                         justify='CB', offset='0c/0.15c', no_clip=True)
            else:
                fig.text(x=[0, length], y=[zmin, zmin],
                         text=[label, label + "'"],
                         font='11p,Helvetica-Bold,black',
                         justify='CB', offset='0c/0.15c', no_clip=True)

            if opts.get('inset', True):
                # back to the bottom of the section panel, then right
                fig.shift_origin(
                    xshift='%gc' % (width + 1.2),
                    yshift='%gc' % (-(height + 0.25) if prof is not None
                                    else 0.))
                _section_inset(fig, layers, lat1, lon1, lat2, lon2, wkm,
                               label, opts)

        _save(fig, path, fmt, tmp)
    return {'path': path,
            'n': int(sum(len(ii) for (_, _, ii, _) in sel))}


class _Sub:
    '''A layer restricted to a subset of its events (for legends).'''

    def __init__(self, layer, idx):
        self.cat = layer.cat
        self.idx = idx
        self.size_scale = layer.size_scale


def _section_inset(fig, layers, lat1, lon1, lat2, lon2, wkm, label, opts):
    plats, plons = geo.corridor_polygon(lat1, lon1, lat2, lon2, wkm)
    lo0, lo1 = float(plons.min()), float(plons.max())
    la0, la1 = float(plats.min()), float(plats.max())
    pad = 0.35 * max(lo1 - lo0, la1 - la0, 0.01)
    region = [lo0 - pad, lo1 + pad, max(-89., la0 - pad),
              min(89., la1 + pad)]
    iw = 5.
    fig.basemap(region=region, projection='M%gc' % iw,
                frame=['WSne', 'af'])
    span = max(region[1] - region[0], region[3] - region[2])
    water = colormaps.hex_color(colormaps.parse_hex(
        opts.get('water', '#a8b4bc'), (168, 180, 188)))
    try:
        fig.coast(land='240/240/235', water=water,
                  shorelines='0.3p,gray40',
                  resolution=_coast_resolution(span))
    except Exception:
        pass
    for la in layers:
        if len(la.idx):
            fig.plot(x=la.cat.lon[la.idx], y=la.cat.lat[la.idx],
                     style='c0.05c', fill='90/90/90')
    fig.plot(x=plons, y=plats, pen='0.6p,black,-', fill='black@85')
    fig.plot(x=[lon1, lon2], y=[lat1, lat2], pen='1.2p,red')
    fig.text(x=[lon1, lon2], y=[lat1, lat2], text=[label, label + "'"],
             font='8p,Helvetica-Bold,black', justify='CM', fill='white@20',
             clearance='0.04c/0.04c')


# --------------------------------------------------------------- time plot


def export_timeplot(app, req):
    pygmt = _pygmt()

    path, fmt = _out_path(req)
    opts = req.get('options') or {}
    ykind = opts.get('y', 'depth')
    if ykind not in ('depth', 'mag'):
        raise ExportError('invalid y variable: %s' % ykind)
    style = Style(req.get('style'))
    layers = _layers(app, req)

    def yvals(cat, idx):
        return cat.depth_km[idx] if ykind == 'depth' else cat.mag[idx]

    allt = num.concatenate([la.cat.time[num.concatenate([la.idx, la.grey])]
                            for la in layers] + [num.zeros(0)])
    ally = num.concatenate([yvals(la.cat, num.concatenate([la.idx,
                                                           la.grey]))
                            for la in layers] + [num.zeros(0)])
    ok = num.isfinite(ally)
    if not ok.any():
        raise ExportError('nessun evento con %s da disegnare' % (
            'profondità' if ykind == 'depth' else 'magnitudo'))

    t0 = opts.get('t0')
    t1 = opts.get('t1')
    t0 = float(allt.min()) if t0 is None else float(t0)
    t1 = float(allt.max()) if t1 is None else float(t1)
    if not t1 > t0:
        t1 = t0 + 86400.
    span = t1 - t0
    t0 -= 0.02 * span
    t1 += 0.02 * span

    y0 = opts.get('y0')
    y1 = opts.get('y1')
    ymin, ymax = float(ally[ok].min()), float(ally[ok].max())
    pad = max(0.1, 0.05 * (ymax - ymin))
    y0 = ymin - pad if y0 is None else float(y0)
    y1 = ymax + pad if y1 is None else float(y1)
    if y0 > y1:
        y0, y1 = y1, y0
    if not y1 > y0:
        y1 = y0 + 1.

    width = min(60., max(4., _opt(opts, 'width_cm', 18.)))
    height = min(40., max(2., _opt(opts, 'height_cm', 7.)))
    title = _gmt_label(opts.get('title', ''))
    ylabel = 'Depth (km)' if ykind == 'depth' else 'Magnitude'
    style.symbol_scale *= _opt(opts, 'size_factor', 0.6)

    with _gmt_lock, tempfile.TemporaryDirectory(prefix='cgis_') as tmp:
        fig = pygmt.Figure()
        cpt = style.write_cpt(tmp)
        with pygmt.config(FONT_ANNOT_PRIMARY='8p,Helvetica,black',
                          FONT_LABEL='9p,Helvetica,black',
                          FONT_TITLE='12p,Helvetica-Bold,black',
                          MAP_FRAME_TYPE='plain',
                          FORMAT_DATE_MAP='yyyy-mm-dd',
                          FORMAT_CLOCK_MAP='hh:mm'):
            proj = 'X%gc/%s%gc' % (width, '-' if ykind == 'depth' else '',
                                   height)
            region = [_iso(t0), _iso(t1), y0, y1]
            fig.basemap(region=region, projection=proj,
                        frame=['WSne' + ('+t"%s"' % title if title else ''),
                               'xaf', 'yaf+l%s' % ylabel])
            win = opts.get('window')
            if win and len(win) == 2:
                w0, w1 = float(win[0]), float(win[1])
                xs = _datetimes([w0, w1, w1, w0])
                fig.plot(x=xs, y=[y0, y0, y1, y1], fill='255/215/120@55',
                         close=True)
            for la in layers:
                if len(la.grey):
                    yv = yvals(la.cat, la.grey)
                    m = num.isfinite(yv)
                    _plot_events(fig, la, style,
                                 _datetimes(la.cat.time[la.grey][m]), yv[m],
                                 la.grey[m], cpt, tmp, grey=True)
            for la in layers:
                yv = yvals(la.cat, la.idx)
                m = num.isfinite(yv)
                _plot_events(fig, la, style,
                             _datetimes(la.cat.time[la.idx][m]), yv[m],
                             la.idx[m], cpt, tmp, mts=None)
            fig.basemap(frame=['WSne', 'xaf', 'yaf'])
            if opts.get('colorbar', True) and _any_auto(layers):
                _colorbar(fig, style, cpt,
                          'JBC+w%gc/0.25c+o0c/1.1c+h' % (0.45 * width), tmp)
        _save(fig, path, fmt, tmp)
    return {'path': path}


# --------------------------------------------------------------- stereonet


def equal_area_xy(trend_deg, plunge_deg):
    '''Lower-hemisphere equal-area (Schmidt) projection, unit radius.'''
    tr = num.radians(num.asarray(trend_deg, dtype=float))
    pl = num.radians(num.asarray(plunge_deg, dtype=float))
    r = num.sqrt(2.) * num.sin((num.pi / 2. - pl) / 2.)
    return r * num.sin(tr), r * num.cos(tr)


def mean_axis(trend_deg, plunge_deg):
    '''Principal direction of the orientation tensor of axial data.'''
    tr = num.radians(num.asarray(trend_deg, dtype=float))
    pl = num.radians(num.asarray(plunge_deg, dtype=float))
    ok = num.isfinite(tr) & num.isfinite(pl)
    if ok.sum() == 0:
        return None
    v = num.vstack([num.cos(pl[ok]) * num.cos(tr[ok]),
                    num.cos(pl[ok]) * num.sin(tr[ok]),
                    num.sin(pl[ok])])
    t = num.dot(v, v.T) / ok.sum()
    w, e = num.linalg.eigh(t)
    a = e[:, -1]
    if a[2] < 0:
        a = -a
    trend = math.degrees(math.atan2(a[1], a[0])) % 360.
    plunge = math.degrees(math.asin(min(1., max(-1., a[2]))))
    return trend, plunge


def export_stereonet(app, req):
    pygmt = _pygmt()
    from .catalog import mt_info

    path, fmt = _out_path(req)
    opts = req.get('options') or {}
    style = Style(req.get('style'))
    layers = _layers(app, req)
    show = [a for a in opts.get('axes', ['p', 't']) if a in ('p', 't', 'b')]
    if not show:
        raise ExportError('nessun asse selezionato')
    fixed = opts.get('color_mode', 'auto') == 'fixed'

    data = {a: {'tr': [], 'pl': [], 'val': []} for a in show}
    n_mt = 0
    for la in layers:
        cat = la.cat
        for i in la.idx:
            k = cat.mt_index[i]
            if k < 0:
                continue
            n_mt += 1
            inf = mt_info(cat.mts[k])
            if la.color:
                val = la.color
            elif la.explicit is not None:
                val = la.explicit.get(int(i), '#a0a0a0')
            else:
                v = style.values(cat, num.array([i]))
                lo, hi = style.cpt_range()
                val = colormaps.hex_color(colormaps.map_values(
                    v, lo, hi, style.cmap, style.reverse)[0])
            for a in show:
                tr = inf.get(a + '_tr')
                pl = inf.get(a + '_pl')
                if tr is not None and pl is not None:
                    data[a]['tr'].append(tr)
                    data[a]['pl'].append(pl)
                    data[a]['val'].append(val)
    if n_mt == 0:
        raise ExportError('nessun tensore momento tra gli eventi selezionati')

    width = min(30., max(4., _opt(opts, 'width_cm', 10.)))
    title = _gmt_label(opts.get('title', ''))
    symbols = {'p': 'c', 't': 't', 'b': 's'}
    fixed_col = {'p': '#2b6cb0', 't': '#d62828', 'b': '#7a7a7a'}
    names = {'p': 'P axis', 't': 'T axis', 'b': 'B (null) axis'}
    size = 0.25 * width / 10.

    with _gmt_lock, tempfile.TemporaryDirectory(prefix='cgis_') as tmp:
        fig = pygmt.Figure()
        cpt = style.write_cpt(tmp)
        R = 1.08
        with pygmt.config(FONT_ANNOT_PRIMARY='8p,Helvetica,black',
                          FONT_TITLE='12p,Helvetica-Bold,black',
                          MAP_TITLE_OFFSET='4p'):
            fig.basemap(region=[-R, R, -R, R],
                        projection='X%gc/%gc' % (width, width),
                        frame=['+n' + ('+t"%s"' % title if title else '')])
            phi = num.linspace(0., 2. * num.pi, 361)
            if opts.get('net', True):
                for pl in (30., 60.):
                    r = num.sqrt(2.) * num.sin(math.radians(90. - pl) / 2.)
                    fig.plot(x=r * num.sin(phi), y=r * num.cos(phi),
                             pen='0.3p,170/170/170,-')
                for az in range(0, 180, 30):
                    a = math.radians(az)
                    fig.plot(x=[-math.sin(a), math.sin(a)],
                             y=[-math.cos(a), math.cos(a)],
                             pen='0.3p,190/190/190')
            fig.plot(x=num.sin(phi), y=num.cos(phi), pen='1p,black')
            for (tx, ty, txt, just, off) in (
                    (0., 1., 'N', 'CB', '0c/0.12c'),
                    (1., 0., 'E', 'LM', '0.12c/0c'),
                    (0., -1., 'S', 'CT', '0c/-0.12c'),
                    (-1., 0., 'W', 'RM', '-0.12c/0c')):
                fig.text(x=tx, y=ty, text=txt, font='9p,Helvetica-Bold',
                         justify=just, offset=off, no_clip=True)
            for a in show:
                d = data[a]
                if not d['tr']:
                    continue
                x, y = equal_area_xy(d['tr'], d['pl'])
                kw = dict(x=x, y=y, style='%s%.2fc' % (symbols[a], size),
                          pen='0.4p,black')
                if fixed:
                    kw['fill'] = fixed_col[a]
                else:
                    uniq = sorted(set(d['val']))
                    code = {h: k for (k, h) in enumerate(uniq)}
                    ccpt = op.join(tmp, 'pt_%s.cpt' % a)
                    with open(ccpt, 'w') as f:
                        for h, k in code.items():
                            rgb = '%d/%d/%d' % colormaps.parse_hex(h)
                            f.write('%g %s %g %s\n' % (k - .5, rgb, k + .5, rgb))
                    kw['fill'] = num.array([code[h] for h in d['val']],
                                           dtype=float)
                    kw['cmap'] = ccpt
                fig.plot(**kw)
            if opts.get('mean', True):
                for a in show:
                    d = data[a]
                    m = mean_axis(d['tr'], d['pl']) if d['tr'] else None
                    if m is None:
                        continue
                    x, y = equal_area_xy([m[0]], [m[1]])
                    fig.plot(x=x, y=y, style='a%.2fc' % (size * 2.),
                             fill=fixed_col[a], pen='0.8p,black')
                    fig.text(x=x, y=y, text=['%s %03.0f/%02.0f' % (
                        a.upper(), m[0], m[1])], font='7p,Helvetica,black',
                        justify='LM', offset='%.2fc/0c' % (size * 1.4),
                        fill='white@30')
            spec = op.join(tmp, 'legend.txt')
            with open(spec, 'w') as f:
                for a in show:
                    f.write('S 0.2c %s 0.22c %s 0.4p,black 0.45c %s\n' % (
                        symbols[a], fixed_col[a] if fixed else '200/200/200',
                        names[a]))
                f.write('L 7p,Helvetica L N = %d\n' % n_mt)
            fig.legend(spec=spec, position='jBL+jBL+o-0.1c/-0.3c',
                       box='+gwhite@20+p0.3p,gray50')
            if not fixed and opts.get('colorbar', True):
                _colorbar(fig, style, cpt,
                          'JBC+w%gc/0.22c+o0c/0.5c+h' % (0.6 * width), tmp)
        _save(fig, path, fmt, tmp)
    return {'path': path, 'n': n_mt}
