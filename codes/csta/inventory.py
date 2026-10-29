'''
Station catalogues read from StationXML with pyrocko.

A catalogue is an ordered set of stations keyed by NET.STA. Each station
(:class:`Entry`) keeps its StationXML epochs as pyrocko ``Station`` objects,
with all their channels and responses, so that stations copied between
catalogues are written back unchanged.

Entries and Station objects are never modified in place: catalogues and the
undo history share them, and merges build new (shallow-copied) objects.

Pyrocko station files (.pf) and text tables (.txt, .csv) are converted to
StationXML objects without responses; their catalogues are read-only.
'''

import copy
import hashlib
import math
import os
import os.path as op
import re
import shutil
import tempfile
import textwrap
import time
from collections import OrderedDict

from pyrocko import model, util
from pyrocko.io import stationxml

from cgis.stations import channel_class, CLASS_ORDER

from . import __version__, paths


class InventoryError(Exception):
    pass


# ------------------------------------------------------------------ values

def _val(x):
    '''Value of a stationxml quantity (or plain number), None if missing.'''
    if x is None:
        return None
    v = getattr(x, 'value', x)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x, nd=6):
    v = _val(x)
    return None if v is None else round(v, nd)


def _t(t):
    return None if t is None else round(float(t), 3)


def tstr(t, fmt='%Y-%m-%d'):
    if t is None:
        return None
    try:
        return util.time_to_str(t, format=fmt)
    except Exception:
        return None


def _desc(eq):
    '''First non-empty description of a sensor / data logger.'''
    if eq is None:
        return None
    for attr in ('description', 'model', 'type', 'manufacturer'):
        s = getattr(eq, attr, None)
        if s and str(s).strip().lower() not in ('none', ''):
            return str(s).strip()
    return None


def _sensitivity(ch):
    resp = ch.response
    if resp is None:
        return None
    return resp.instrument_sensitivity


def has_response(ch):
    s = _sensitivity(ch)
    return s is not None and _val(s.value) is not None


def _units(u):
    return None if u is None else (u.name or None)


def _dist_m(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 0.
    d2r = math.pi / 180.
    a = (math.sin((lat2 - lat1) * d2r / 2.)**2 +
         math.cos(lat1 * d2r) * math.cos(lat2 * d2r) *
         math.sin((lon2 - lon1) * d2r / 2.)**2)
    return 2. * 6371000. * math.asin(min(1., math.sqrt(a)))


def group_codes(codes):
    '''[(loc, code), ...] -> 'HH[ENZ] 00.HN[ENZ]' '''
    groups = OrderedDict()
    for loc, code in sorted(set(codes)):
        groups.setdefault((loc, code[:2]), []).append(code[2:])
    out = []
    for (loc, prefix), comps in groups.items():
        s = prefix + ('[%s]' % ''.join(comps) if len(comps) > 1
                      else comps[0])
        out.append((loc + '.' if loc else '') + s)
    return ' '.join(out)


# ---------------------------------------------------- epochs and signatures

def _ch_key(ch):
    return (ch.location_code or '', ch.code or '', _t(ch.start_date))


def _st_key(st):
    return _t(st.start_date)


def _start(st):
    return st.start_date if st.start_date is not None else -1e30


def _ch_sig(ch):
    s = _sensitivity(ch)
    sens = _val(s.value) if s is not None else None
    nstages = len(ch.response.stage_list) if ch.response is not None else -1
    return (ch.location_code or '', ch.code or '', _t(ch.start_date),
            _t(ch.end_date), _r(ch.latitude), _r(ch.longitude),
            _r(ch.elevation, 2), _r(ch.depth, 2), _r(ch.azimuth, 3),
            _r(ch.dip, 3), _r(ch.sample_rate),
            None if sens is None else float('%.6g' % sens), nstages,
            _desc(ch.sensor))


def _st_sig(st):
    return (_t(st.start_date), _t(st.end_date), _r(st.latitude),
            _r(st.longitude), _r(st.elevation, 2),
            tuple(sorted((_ch_sig(c) for c in st.channel_list), key=repr)))


_NET_PROPS = [p for p in stationxml.Network.T.propnames
              if p != 'station_list']


def _net_template(n):
    '''Network attributes without its stations.'''
    return stationxml.Network(**{p: getattr(n, p) for p in _NET_PROPS})


def _merge_station(a, b):
    '''Epoch ``a`` plus the channel epochs of ``b`` that it lacks.'''
    have = {_ch_key(c) for c in a.channel_list}
    extra = [c for c in b.channel_list if _ch_key(c) not in have]
    if not extra:
        return a
    new = copy.copy(a)
    new.channel_list = list(a.channel_list) + extra
    if new.selected_number_channels is not None:
        new.selected_number_channels = len(new.channel_list)
    return new


def _combine(net, sta, stations, network):
    '''Entry from station epochs; epochs with the same start are merged.'''
    epochs = OrderedDict()
    for st in stations:
        k = _st_key(st)
        epochs[k] = _merge_station(epochs[k], st) if k in epochs else st
    return Entry(net, sta, list(epochs.values()), network)


def merge_entries(a, b):
    '''
    Union of two versions of a station: all station epochs, and all channel
    epochs (same location, code and start date counted once, ``a`` wins).
    '''
    return _combine(a.net, a.sta, list(a.epochs) + list(b.epochs), a.network)


class Entry:
    '''All the epochs of one NET.STA (immutable once created).'''

    def __init__(self, net, sta, epochs, network):
        self.net = net
        self.sta = sta
        self.epochs = sorted(epochs, key=_start)
        self.network = network
        self._sig = None
        self._summary = None

    @property
    def key(self):
        return '%s.%s' % (self.net, self.sta)

    def channels(self):
        return [c for st in self.epochs for c in st.channel_list]

    @property
    def sig(self):
        '''Content hash: two versions with the same sig are identical.'''
        if self._sig is None:
            s = repr(tuple(_st_sig(st) for st in self.epochs))
            self._sig = hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]
        return self._sig

    def summary(self):
        if self._summary is not None:
            return self._summary

        now = time.time()
        last = self.epochs[-1]
        chans = self.channels()
        codes = [(c.location_code or '', c.code or '') for c in chans]
        classes = sorted({channel_class(code) for (_, code) in codes},
                         key=CLASS_ORDER.index) or ['OTHER']
        sensors = []
        for c in chans:
            s = _desc(c.sensor)
            if s and s not in sensors:
                sensors.append(s)
        srs = sorted({v for v in (_val(c.sample_rate) for c in chans)
                      if v is not None})
        end = None if any(st.end_date is None for st in self.epochs) \
            else max(st.end_date for st in self.epochs)
        site = None
        if last.site is not None and last.site.name:
            site = str(last.site.name)

        self._summary = {
            'key': self.key,
            'net': self.net,
            'sta': self.sta,
            'lat': _r(last.latitude),
            'lon': _r(last.longitude),
            'elev': _r(last.elevation, 1),
            'site': site,
            'start': tstr(self.epochs[0].start_date),
            'end': tstr(end),
            'active': any(st.end_date is None or st.end_date > now
                          for st in self.epochs),
            'periods': [[_t(st.start_date), _t(st.end_date)]
                        for st in self.epochs],
            'cls': classes[0],
            'classes': classes,
            'chans': group_codes(codes),
            'bands': sorted({code[:2] for (_, code) in codes if code}),
            'sensors': sensors,
            'srs': srs,
            'nchan': len(chans),
            'nepo': len(self.epochs),
            'noresp': sum(1 for c in chans if not has_response(c)),
            'sig': self.sig,
        }
        return self._summary

    def short(self):
        s = self.summary()
        return '%d canali · %s → %s · %s' % (
            s['nchan'], s['start'] or '?', s['end'] or 'oggi',
            s['chans'] or 'nessun canale')

    def detail(self):
        epochs = []
        for st in self.epochs:
            chans = []
            for c in sorted(st.channel_list, key=lambda c: (
                    c.location_code or '', c.code or '', _start(c))):
                s = _sensitivity(c)
                chans.append({
                    'loc': c.location_code or '',
                    'code': c.code or '',
                    'start': tstr(c.start_date, '%Y-%m-%d %H:%M'),
                    'end': tstr(c.end_date, '%Y-%m-%d %H:%M'),
                    'lat': _r(c.latitude),
                    'lon': _r(c.longitude),
                    'elev': _r(c.elevation, 1),
                    'depth': _r(c.depth, 1),
                    'az': _r(c.azimuth, 1),
                    'dip': _r(c.dip, 1),
                    'sr': _r(c.sample_rate),
                    'sensor': _desc(c.sensor),
                    'logger': _desc(c.data_logger),
                    'sens': None if s is None else _val(s.value),
                    'sens_f': None if s is None else _val(s.frequency),
                    'units_in': None if s is None else _units(s.input_units),
                    'units_out': None if s is None
                    else _units(s.output_units),
                    'nstages': len(c.response.stage_list)
                    if c.response is not None else None,
                })
            epochs.append({
                'start': tstr(st.start_date, '%Y-%m-%d %H:%M'),
                'end': tstr(st.end_date, '%Y-%m-%d %H:%M'),
                'lat': _r(st.latitude),
                'lon': _r(st.longitude),
                'elev': _r(st.elevation, 1),
                'site': str(st.site.name) if st.site is not None
                and st.site.name else None,
                'channels': chans,
            })
        net = self.network
        return {
            'key': self.key,
            'sig': self.sig,
            'network': {'code': self.net,
                        'description': getattr(net, 'description', None)},
            'epochs': epochs,
        }


def describe_diff(a, b, la='A', lb='B'):
    '''Short list (Italian) of the differences between two versions.'''
    out = []
    sa, sb = a.summary(), b.summary()
    d = _dist_m(sa['lat'], sa['lon'], sb['lat'], sb['lon'])
    if d > 1.:
        out.append('posizione diversa di %.0f m' % d)
    if sa['elev'] is not None and sb['elev'] is not None \
            and abs(sa['elev'] - sb['elev']) > 0.5:
        out.append('quota %g m / %g m' % (sa['elev'], sb['elev']))

    ca = {(c.location_code or '', c.code or '') for c in a.channels()}
    cb = {(c.location_code or '', c.code or '') for c in b.channels()}
    if ca - cb:
        out.append('canali solo in %s: %s' % (la, group_codes(ca - cb)))
    if cb - ca:
        out.append('canali solo in %s: %s' % (lb, group_codes(cb - ca)))
    if len(a.epochs) != len(b.epochs):
        out.append('epoche della stazione: %d / %d'
                   % (len(a.epochs), len(b.epochs)))

    ea = {_ch_key(c): c for c in a.channels()}
    eb = {_ch_key(c): c for c in b.channels()}
    if len(ea) != len(eb):
        out.append('epoche dei canali: %d / %d' % (len(ea), len(eb)))

    what = OrderedDict()
    for k in sorted(set(ea) & set(eb), key=repr):
        x, y = ea[k], eb[k]
        if _ch_sig(x) == _ch_sig(y):
            continue
        sx, sy = _ch_sig(x), _ch_sig(y)
        code = (k[0] + '.' if k[0] else '') + k[1]
        for label, i0, i1 in (('fine epoca', 3, 4), ('coordinate', 4, 8),
                              ('orientazione', 8, 10),
                              ('campionamento', 10, 11),
                              ('sensibilità', 11, 12),
                              ('stadi di risposta', 12, 13),
                              ('sensore', 13, 14)):
            if sx[i0:i1] != sy[i0:i1]:
                what.setdefault(label, set()).add(code)
    for label, codes in what.items():
        codes = sorted(codes)
        out.append('%s diversa: %s%s' % (
            label, ', '.join(codes[:6]),
            ' …' if len(codes) > 6 else ''))

    if not out:
        out.append('differenze minori nei metadati')
    return out


# --------------------------------------------------------------- catalogue

class Catalog:
    '''
    kind: 'xml' (one StationXML file), 'dir' (folder of StationXML files),
    'pf' / 'txt' (read-only, no responses), 'new' (built in csta).
    '''

    def __init__(self, cid, name, kind, path=None):
        self.id = cid
        self.name = name
        self.kind = kind
        self.path = path
        self.entries = OrderedDict()
        self.headers = []     # header of each source file
        self.history = []     # csta comments found in the source files
        self.log = []         # operations of this session
        self.letter = ''
        self.color = '#888888'
        self.rev = 0
        self.saved_rev = 0

    @property
    def readonly(self):
        return self.kind in ('pf', 'txt')

    @property
    def dirty(self):
        return self.rev != self.saved_rev

    def clone(self):
        c = copy.copy(self)
        c.entries = OrderedDict(self.entries)
        c.log = list(self.log)
        return c

    def payload(self):
        nets = OrderedDict()
        stations = []
        nchan = noresp = 0
        for e in self.entries.values():
            s = e.summary()
            stations.append(s)
            nets[e.net] = nets.get(e.net, 0) + 1
            nchan += s['nchan']
            noresp += s['noresp']
        starts = [s['start'] for s in stations if s['start']]
        ends = [s['end'] for s in stations]
        return {
            'id': self.id,
            'name': self.name,
            'kind': self.kind,
            'readonly': self.readonly,
            'path': paths.rel(self.path) if self.path else None,
            'letter': self.letter,
            'color': self.color,
            'dirty': self.dirty,
            'n': len(stations),
            'nchan': nchan,
            'noresp': noresp,
            'nets': nets,
            'start': min(starts) if starts else None,
            'end': None if (not ends or None in ends) else max(ends),
            'nfiles': len(self.headers),
            'headers': self.headers[:3],
            'log': self.log[-20:],
            'stations': stations,
        }


def _read_history(path):
    '''csta comments written in a previous save of this file.'''
    try:
        with open(path, 'rb') as f:
            head = f.read(65536).decode('utf-8', 'replace')
    except OSError:
        return []
    return [m.strip() for m in re.findall(r'<!--\s*(csta\b.*?)-->', head,
                                          re.S)]


def _load_xml_file(path):
    with open(path, 'rb') as f:
        head = f.read(4096).lower()
    if b'quakeml' in head:
        raise InventoryError('%s è un catalogo QuakeML, non un file di '
                             'stazioni' % op.basename(path))
    try:
        sx = stationxml.load_xml(filename=path)
    except Exception as e:
        raise InventoryError('impossibile leggere %s come StationXML: %s'
                             % (op.basename(path),
                                str(e) or type(e).__name__))
    if not hasattr(sx, 'network_list'):
        raise InventoryError('%s non è un file StationXML'
                             % op.basename(path))
    header = {
        'file': paths.rel(path),
        'source': sx.source,
        'sender': sx.sender,
        'module': sx.module,
        'created': tstr(sx.created),
        'schema': sx.schema_version,
    }
    pairs = []
    for n in sx.network_list:
        tmpl = _net_template(n)
        pairs.extend((tmpl, st) for st in n.station_list)
    return header, pairs


def _from_pyrocko(stations):
    sx = stationxml.FDSNStationXML.from_pyrocko_stations(stations)
    pairs = []
    for n in sx.network_list:
        tmpl = _net_template(n)
        pairs.extend((tmpl, st) for st in n.station_list)
    return pairs


def _load_pf(path):
    try:
        stations = model.load_stations(path)
    except Exception as e:
        raise InventoryError(
            'impossibile leggere %s come file di stazioni pyrocko: %s'
            % (op.basename(path), str(e) or type(e).__name__))
    return _from_pyrocko(stations)


_COLUMNS = OrderedDict([
    ('net', ('net', 'network', 'netcode', 'rete')),
    ('sta', ('sta', 'station', 'stat', 'stazione', 'code', 'codice')),
    ('lat', ('lat', 'latitude', 'latitudine')),
    ('lon', ('lon', 'long', 'longitude', 'lng', 'longitudine')),
    ('elev', ('elev', 'elevation', 'alt', 'altitude', 'height', 'quota')),
])


def _load_table(path):
    '''Text table with a header line (CSV, FDSN text, whitespace).'''
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except OSError as e:
        raise InventoryError('impossibile leggere %s: %s'
                             % (op.basename(path), e))
    if not lines:
        raise InventoryError('%s è vuoto' % op.basename(path))

    first = lines[0].lstrip('#').strip()
    delim = next((d for d in '|,;\t' if d in first), None)

    def split(ln):
        return [x.strip() for x in (ln.split(delim) if delim
                                    else ln.split())]

    header = [h.lower() for h in split(first)]
    idx = {}
    for k, names in _COLUMNS.items():
        for i, h in enumerate(header):
            if h in names and k not in idx and i not in idx.values():
                idx[k] = i
    if not all(k in idx for k in ('sta', 'lat', 'lon')):
        raise InventoryError(
            '%s: la prima riga deve indicare le colonne (almeno station, '
            'lat, lon); trovate: %s' % (op.basename(path), ', '.join(header)))

    stations = []
    for ln in lines[1:]:
        if ln.lstrip().startswith('#'):
            continue
        row = split(ln)
        try:
            lat = float(row[idx['lat']])
            lon = float(row[idx['lon']])
            sta = row[idx['sta']]
        except (IndexError, ValueError):
            continue
        net = row[idx['net']] if 'net' in idx and idx['net'] < len(row) \
            else ''
        if not net and '.' in sta:
            net, sta = sta.split('.')[:2]
        try:
            elev = float(row[idx['elev']]) if 'elev' in idx else 0.
        except (IndexError, ValueError):
            elev = 0.
        stations.append(model.Station(network=net, station=sta, lat=lat,
                                      lon=lon, elevation=elev))
    if not stations:
        raise InventoryError('nessuna stazione leggibile in %s'
                             % op.basename(path))
    return _from_pyrocko(stations)


def _entries_from_pairs(pairs):
    groups = OrderedDict()
    for tmpl, st in pairs:
        g = groups.setdefault((tmpl.code or '', st.code or ''), [tmpl, []])
        g[1].append(st)
    entries = OrderedDict()
    for (net, sta), (tmpl, sts) in groups.items():
        e = _combine(net, sta, sts, tmpl)
        entries[e.key] = e
    return entries


def load_catalog(cid, path):
    path = op.normpath(path)
    if op.isdir(path):
        files = sorted(f for f in os.listdir(path)
                       if f.lower().endswith('.xml') and not f.startswith('.'))
        if not files:
            raise InventoryError('nessun file .xml nella cartella %s'
                                 % paths.rel(path))
        cat = Catalog(cid, op.basename(path), 'dir', path)
        pairs = []
        for f in files:
            header, p = _load_xml_file(op.join(path, f))
            cat.headers.append(header)
            cat.history.extend(_read_history(op.join(path, f)))
            pairs.extend(p)
    elif not op.isfile(path):
        raise InventoryError('file non trovato: %s' % paths.rel(path))
    else:
        ext = op.splitext(path)[1].lower()
        with open(path, 'rb') as f:
            head = f.read(2048).lstrip()
        is_xml = ext == '.xml' or head.startswith(b'<?xml') \
            or b'FDSNStationXML' in head
        if is_xml:
            cat = Catalog(cid, op.basename(path), 'xml', path)
            header, pairs = _load_xml_file(path)
            cat.headers.append(header)
            cat.history = _read_history(path)
        elif ext == '.pf':
            cat = Catalog(cid, op.basename(path), 'pf', path)
            pairs = _load_pf(path)
        else:
            cat = Catalog(cid, op.basename(path), 'txt', path)
            pairs = _load_table(path)

    cat.entries = _entries_from_pairs(pairs)
    if not cat.entries:
        raise InventoryError('nessuna stazione in %s' % paths.rel(path))
    return cat


# ------------------------------------------------------------------ output

def _atomic_write(path, data, backup=True):
    '''Write via a temporary file; an existing file is kept as .bak.'''
    d = op.dirname(path) or '.'
    paths.ensure_dir(d)
    existed = op.isfile(path)
    if existed and backup:
        shutil.copy2(path, path + '.bak')
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.csta_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        if existed:
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _comment(cat, nets, now):
    lines = ['csta %s - %s UTC' % (__version__,
                                   tstr(now, '%Y-%m-%d %H:%M:%S')),
             'catalogo: %s' % cat.name,
             'stazioni: %d (%s)' % (
                 sum(nets.values()),
                 ', '.join('%s: %d' % (k or '-', v) for k, v in nets.items()))]
    if cat.headers:
        lines.append('file di origine:')
        for h in cat.headers[:50]:
            lines.append('  %s (%s)' % (h['file'], ', '.join(
                str(h[k]) for k in ('source', 'sender', 'created')
                if h.get(k))))
        if len(cat.headers) > 50:
            lines.append('  … altri %d file' % (len(cat.headers) - 50))
    if cat.log:
        lines.append('operazioni:')
        lines.extend('  - ' + ln for ln in cat.log)
    if cat.history:
        lines.append('storia precedente:')
        for h in cat.history:
            # the first line lost its indentation in _read_history
            lines.extend('  ' + ln.rstrip() for ln in
                         textwrap.dedent('  ' + h).splitlines())
    text = '\n'.join('  ' + ln for ln in lines)
    # '--' is not allowed inside XML comments
    while '--' in text:
        text = text.replace('--', '- -')
    return '<!--\n%s\n-->\n' % text


def build_xml(cat):
    nets = OrderedDict()
    for key in sorted(cat.entries):
        e = cat.entries[key]
        nets.setdefault(e.net, [e.network, []])[1].extend(e.epochs)
    network_list = []
    for code in sorted(nets):
        tmpl, stations = nets[code]
        kw = {p: getattr(tmpl, p) for p in _NET_PROPS}
        kw['selected_number_stations'] = len({s.code for s in stations})
        network_list.append(stationxml.Network(station_list=stations, **kw))
    h = cat.headers[0] if cat.headers else {}
    return stationxml.FDSNStationXML(
        schema_version=max([float(x['schema']) for x in cat.headers
                            if x.get('schema')] or [1.1]),
        source=h.get('source') or 'csta',
        sender=h.get('sender'),
        module='csta %s' % __version__,
        created=time.time(),
        network_list=network_list)


def write_xml(cat, path):
    if cat.readonly:
        raise InventoryError(
            '%s non ha risposte strumentali: non può essere salvato come '
            'StationXML (esportalo come .pf)' % cat.name)
    now = time.time()
    nets = OrderedDict()
    for e in cat.entries.values():
        nets[e.net] = nets.get(e.net, 0) + 1
    xml = build_xml(cat).dump_xml(header=True)
    i = xml.find('?>') + 2 if xml.startswith('<?xml') else 0
    xml = xml[:i].rstrip() + ('\n' if i else '') + _comment(cat, nets, now) \
        + xml[i:].lstrip()
    _atomic_write(path, xml.encode('utf-8'))


def to_pyrocko(cat):
    '''
    Pyrocko stations (one per NET.STA.LOC) from the latest epoch of each
    station; per channel code the latest channel epoch is used.
    '''
    out = []
    for key in sorted(cat.entries):
        e = cat.entries[key]
        st = e.epochs[-1]
        by_loc = OrderedDict()
        for ch in sorted(st.channel_list, key=_start):
            by_loc.setdefault(ch.location_code or '', OrderedDict())[
                ch.code] = ch
        if not by_loc:
            by_loc[''] = OrderedDict()
        for loc, chs in by_loc.items():
            first = next(iter(chs.values()), None)
            out.append(model.Station(
                network=e.net, station=e.sta, location=loc,
                lat=_val(st.latitude), lon=_val(st.longitude),
                elevation=_val(st.elevation) or 0.,
                depth=(_val(first.depth) if first is not None else 0.) or 0.,
                channels=[model.Channel(code, azimuth=_val(c.azimuth),
                                        dip=_val(c.dip))
                          for code, c in sorted(chs.items())]))
    return out


def write_pf(cat, path):
    d = op.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.csta_', suffix='.pf')
    os.close(fd)
    try:
        model.dump_stations(to_pyrocko(cat), tmp)
        with open(tmp, 'rb') as f:
            data = f.read()
    finally:
        os.unlink(tmp)
    _atomic_write(path, data)


def write_list(cat, path):
    keys = sorted(e.key if e.net else e.sta for e in cat.entries.values())
    _atomic_write(path, ('\n'.join(keys) + '\n').encode('utf-8'))
