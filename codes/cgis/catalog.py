'''
Catalogue loading with pyrocko. A catalogue may contain, event by event,
only the location, also the magnitude, or a full moment tensor; everything
that is present is passed on to the viewer.

Magnitudes are taken only from the ``magnitude`` field or computed from the
moment tensor: magnitudes written in the tags are NOT used (tags are only
shown in the event tooltip).
'''

import math
import os.path as op
import threading
from collections import OrderedDict

import numpy as num

from pyrocko import model, util
from pyrocko import moment_tensor as pmt

from . import paths


class CatalogError(Exception):
    pass


class NeedsMapping(Exception):
    '''A text catalogue whose columns must be confirmed by the user.'''

    def __init__(self, guess, preview):
        Exception.__init__(self, 'columns to be confirmed')
        self.guess = guess
        self.preview = preview


BEACHBALL_TYPES = ('dc', 'deviatoric', 'full')


def _finite(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _round_list(arr, ndigits):
    '''JSON-ready list: rounded floats, None for NaN/inf.'''
    arr = num.asarray(arr, dtype=float)
    out = num.round(arr, ndigits).tolist()
    bad = ~num.isfinite(arr)
    if bad.any():
        for i in num.nonzero(bad)[0]:
            out[i] = None
    return out


def _axis_trend_plunge(v):
    v = num.asarray(v, dtype=float).ravel()
    norm = num.sqrt(num.sum(v**2))
    if not norm > 0.:
        return float('nan'), float('nan')
    v = v / norm
    if v[2] < 0.:                   # lower hemisphere (NED: d > 0)
        v = -v
    trend = math.degrees(math.atan2(v[1], v[0])) % 360.
    plunge = math.degrees(math.asin(min(1., max(-1., v[2]))))
    return trend, plunge


def mt_info(mt):
    '''Scalar description of a moment tensor (all values JSON friendly).'''
    info = {}
    try:
        (s1, d1, r1), (s2, d2, r2) = mt.both_strike_dip_rake()
        info.update(s1=s1, d1=d1, r1=r1, s2=s2, d2=d2, r2=r2)
    except Exception:
        pass
    try:
        info['m0'] = float(mt.scalar_moment())
        info['mw'] = float(mt.moment_magnitude())
    except Exception:
        pass
    try:
        dec = mt.standard_decomposition()
        iso_sign = 1.0 if num.trace(mt.m()) >= 0. else -1.0
        info['iso'] = iso_sign * 100. * float(dec[0][1])
        info['dc'] = 100. * float(dec[1][1])
        info['clvd'] = 100. * float(dec[2][1])
    except Exception:
        pass
    for name, func in (('p', mt.p_axis), ('t', mt.t_axis),
                       ('b', mt.null_axis)):
        try:
            tr, pl = _axis_trend_plunge(func())
            info[name + '_tr'] = tr
            info[name + '_pl'] = pl
        except Exception:
            pass
    return info


def _rdp(points, eps):
    '''Ramer-Douglas-Peucker simplification of a (N, 2) array.'''
    n = len(points)
    if n < 4:
        return points
    keep = num.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a = points[i0]
        b = points[i1]
        seg = points[i0+1:i1]
        ab = b - a
        lab = math.hypot(ab[0], ab[1])
        if lab == 0.:
            d = num.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            d = num.abs(ab[0] * (seg[:, 1] - a[1])
                        - ab[1] * (seg[:, 0] - a[0])) / lab
        k = int(num.argmax(d))
        if d[k] > eps:
            j = i0 + 1 + k
            keep[j] = True
            stack.append((i0, j))
            stack.append((j, i1))
    return points[keep]


_FILL_CODES = {'T': 1, 'P': 0}


def beachball_polygons(mt, bb_type, eps=0.01):
    '''
    Beachball geometry from pyrocko (unit radius, x east, y north in map
    view): list of ``[fill, edge, flat_xy]`` where fill is 1 (compression),
    0 (dilatation) or -1 (no fill) and edge is 1 for black outlines.
    Returns None when the beachball cannot be computed.
    '''
    from pyrocko.plot import beachball

    try:
        patches = beachball.mt2beachball(
            mt, beachball_type=bb_type, position=(0., 0.), size=1.0,
            color_t='T', color_p='P', edgecolor='E')
    except Exception:
        # pyrocko cannot draw (nearly) purely isotropic tensors: a full
        # circle, compressional for an explosion, empty for an implosion
        # or when the deviatoric/DC part is drawn
        try:
            tr = num.trace(mt.m())
        except Exception:
            return None
        phi = num.linspace(0., 2. * num.pi, 73)
        ring = num.round(num.column_stack([num.cos(phi), num.sin(phi)])
                         .ravel(), 3).tolist()
        fill = 1 if (bb_type == 'full' and tr > 0.) else 0
        return [[fill, 1, ring]]

    polys = []
    for patch in patches:
        xy = num.asarray(patch[0], dtype=float)
        if xy.ndim != 2 or len(xy) < 2 or not num.all(num.isfinite(xy)):
            continue
        fill = _FILL_CODES.get(patch[1], -1)
        edge = 1 if patch[2] == 'E' else 0
        if fill < 0 and not edge:
            continue
        xy = _rdp(xy, eps)
        polys.append([fill, edge, num.round(xy.ravel(), 3).tolist()])

    return polys or None


def section_rotation(azimuth_deg):
    '''
    Rotation from NED to the frame of a vertical section with strike
    ``azimuth_deg`` (from A to B), seen by an observer standing on the
    right-hand side of A->B: new north = up, new east = along A->B,
    new down = away from the observer. A beachball computed for the
    rotated tensor in map view is the projection of the back hemisphere on
    the section plane, with A on the left.
    '''
    phi = math.radians(azimuth_deg)
    c, s = math.cos(phi), math.sin(phi)
    return num.array([
        [0., 0., -1.],
        [c, s, 0.],
        [s, -c, 0.]])


def rotated_mt(mt, azimuth_deg):
    r = section_rotation(azimuth_deg)
    return pmt.MomentTensor(m=num.dot(r, num.dot(mt.m(), r.T)))


class Catalog:

    def __init__(self, cid, path, events, n_skipped=0, mapping=None):
        self.id = cid
        self.path = path
        self.mapping = mapping          # columns of a text catalogue
        # text catalogue without times: always visible, no time axis
        self.no_time = bool(mapping and (mapping.get('time') or {}).get(
            'kind') == 'none')
        self.name = op.basename(path)
        self.events = events
        self.n_skipped = n_skipped
        self._lock = threading.Lock()
        self._bb_cache = {}
        self._sec_bb_cache = OrderedDict()

        n = len(events)
        self.lat = num.empty(n)
        self.lon = num.empty(n)
        self.depth_km = num.full(n, num.nan)
        self.time = num.empty(n)
        self.mag = num.full(n, num.nan)
        self.mt_index = num.full(n, -1, dtype=int)
        self.mts = []
        self.mt_events = []

        for i, ev in enumerate(events):
            self.lat[i] = ev.effective_lat
            self.lon[i] = ev.effective_lon
            self.time[i] = ev.time
            if _finite(ev.depth):
                self.depth_km[i] = ev.depth / 1000.

            mt = ev.moment_tensor
            if mt is not None:
                try:
                    m0 = mt.scalar_moment()
                    ok = math.isfinite(m0) and m0 > 0. \
                        and num.all(num.isfinite(mt.m()))
                except Exception:
                    ok = False
                if ok:
                    self.mt_index[i] = len(self.mts)
                    self.mts.append(mt)
                    self.mt_events.append(i)
                else:
                    mt = None

            no_moment = bool((getattr(ev, 'extras', None) or {}).get(
                '_cgis_no_moment'))
            if _finite(ev.magnitude):
                self.mag[i] = ev.magnitude
            elif mt is not None and not no_moment:
                try:
                    mw = mt.moment_magnitude()
                    if math.isfinite(mw):
                        self.mag[i] = mw
                except Exception:
                    pass

        self.has_mag = bool(num.any(num.isfinite(self.mag)))
        self.has_mt = len(self.mts) > 0

    # ----------------------------------------------------------------- payload

    def payload(self):
        evs = self.events

        if self.no_time:
            tstr = ['non disponibile'] * len(evs)
        else:
            tstr = [util.time_to_str(ev.time,
                                     format='%Y-%m-%d %H:%M:%S.3FRAC')
                    for ev in evs]

        mag_type = [ev.magnitude_type if _finite(ev.magnitude) else None
                    for ev in evs]
        for i in self.mt_events:
            if mag_type[i] is None and not _finite(evs[i].magnitude):
                mag_type[i] = 'Mw (MT)'

        tags = [list(ev.tags) if ev.tags else None for ev in evs]

        info = []
        for ev in evs:
            items = []
            for key in ('catalog', 'region'):
                val = getattr(ev, key, None)
                if val:
                    items.append([key, str(val)])
            extras = getattr(ev, 'extras', None)
            if extras:
                for k, v in extras.items():
                    if not str(k).startswith('_'):
                        items.append([str(k), str(v)])
            info.append(items or None)

        mt = None
        if self.has_mt:
            infos = [mt_info(m) for m in self.mts]
            keys = ('s1', 'd1', 'r1', 's2', 'd2', 'r2', 'm0', 'mw', 'iso',
                    'dc', 'clvd', 'p_tr', 'p_pl', 't_tr', 't_pl', 'b_tr',
                    'b_pl')
            mt = {'idx': list(self.mt_events)}
            for k in keys:
                vals = [inf.get(k, float('nan')) for inf in infos]
                if k == 'm0':
                    mt[k] = [float('%.5g' % v) if math.isfinite(v) else None
                             for v in vals]
                else:
                    mt[k] = _round_list(vals, 4)

        return {
            'id': self.id,
            'name': self.name,
            'path': paths.rel(self.path),
            'n': len(evs),
            'n_skipped': self.n_skipped,
            'has_mag': self.has_mag,
            'has_mt': self.has_mt,
            'lat': _round_list(self.lat, 6),
            'lon': _round_list(self.lon, 6),
            'depth': _round_list(self.depth_km, 5),
            'time': _round_list(num.full(len(evs), num.nan)
                                if self.no_time else self.time, 3),
            'no_time': self.no_time,
            'mag': _round_list(self.mag, 3),
            'names': [ev.name or '' for ev in evs],
            'tstr': tstr,
            'mag_type': mag_type if any(mag_type) else None,
            'tags': tags if any(t is not None for t in tags) else None,
            'info': info if any(x is not None for x in info) else None,
            'mt': mt,
            'mapping': self.mapping,
        }

    # -------------------------------------------------------------- beachballs

    def beachballs(self, bb_type):
        if bb_type not in BEACHBALL_TYPES:
            raise CatalogError('unknown beachball type: %s' % bb_type)
        with self._lock:
            if bb_type not in self._bb_cache:
                self._bb_cache[bb_type] = {
                    'idx': list(self.mt_events),
                    'polys': [beachball_polygons(m, bb_type)
                              for m in self.mts]}
            return self._bb_cache[bb_type]

    def section_beachballs(self, indices, azimuth_deg, bb_type):
        if bb_type not in BEACHBALL_TYPES:
            raise CatalogError('unknown beachball type: %s' % bb_type)
        idx = sorted(set(int(i) for i in indices
                         if 0 <= int(i) < len(self.events)
                         and self.mt_index[int(i)] >= 0))
        key = (bb_type, round(float(azimuth_deg) % 360., 4))
        with self._lock:
            cache = self._sec_bb_cache.get(key)
            if cache is None:
                cache = {}
                self._sec_bb_cache[key] = cache
                while len(self._sec_bb_cache) > 16:
                    self._sec_bb_cache.popitem(last=False)
            else:
                self._sec_bb_cache.move_to_end(key)
            polys = []
            for i in idx:
                if i not in cache:
                    mt = self.mts[self.mt_index[i]]
                    cache[i] = beachball_polygons(
                        rotated_mt(mt, azimuth_deg), bb_type)
                polys.append(cache[i])
        return {'idx': idx, 'polys': polys}

    # ------------------------------------------------------------------ export

    def dump(self, indices, filename):
        evs = [self.events[i] for i in sorted(set(int(i) for i in indices))
               if 0 <= i < len(self.events)]
        if not evs:
            raise CatalogError('nessun evento da esportare')
        fmt = 'yaml' if filename.lower().endswith(('.yaml', '.yml')) \
            else 'basic'
        model.dump_events(evs, filename=filename, format=fmt)
        return len(evs)


def _xml_kind(path):
    with open(path, 'rb') as f:
        head = f.read(4096)
    if b'FDSNStationXML' in head:
        return 'stationxml'
    if b'quakeml' in head.lower():
        return 'quakeml'
    return 'unknown'


def _load_quakeml(path):
    from pyrocko.io import quakeml
    kind = _xml_kind(path)
    if kind == 'stationxml':
        raise CatalogError(
            '%s è un file StationXML (stazioni): caricalo con + Stazioni'
            % op.basename(path))
    try:
        qml = quakeml.QuakeML.load_xml(filename=path)
        return qml.get_pyrocko_events()
    except Exception as e:
        raise CatalogError('impossibile leggere %s come QuakeML: %s'
                           % (op.basename(path), str(e) or type(e).__name__))


def load_catalog(cid, path, mapping=None):
    '''
    Load a catalogue. Text tables may raise :class:`NeedsMapping` when
    their columns are not recognised and no ``mapping`` is given.
    '''
    if not op.isfile(path):
        raise CatalogError('file non trovato: %s' % path)

    ext = op.splitext(path)[1].lower()
    used_mapping = None
    n_text_skipped = 0
    if ext in ('.txt', '.csv', '.tsv', '.dat'):
        from . import textcat
        events, n_text_skipped, used_mapping, prev = textcat.load(
            path, mapping)
        if events is None:
            raise NeedsMapping(used_mapping, prev)
    elif ext in ('.xml', '.qml', '.quakeml'):
        events = _load_quakeml(path)
    else:
        try:
            events = model.load_events(path)
        except Exception as e:
            raise CatalogError(
                'impossibile leggere %s come catalogo pyrocko: %s'
                % (op.basename(path), str(e) or type(e).__name__))

    good = []
    n_skipped = 0
    for ev in events:
        try:
            ok = (_finite(ev.effective_lat) and _finite(ev.effective_lon)
                  and _finite(ev.time)
                  and -90. <= ev.effective_lat <= 90.)
        except Exception:
            ok = False
        if ok:
            good.append(ev)
        else:
            n_skipped += 1

    if not good:
        raise CatalogError(
            'nessun evento valido (con tempo e coordinate) in %s'
            % op.basename(path))

    return Catalog(cid, path, good, n_skipped + n_text_skipped,
                   mapping=used_mapping)
