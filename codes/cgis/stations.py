'''
Station metadata from StationXML (pyrocko.io.stationxml) or pyrocko station
files. Stations are grouped by NET.STA (all epochs), and classified by the
SEED band/instrument codes of their channels.
'''

import math
import os.path as op
import time
from collections import OrderedDict

from pyrocko import model, util

from . import paths


class StationError(Exception):
    pass


# SEED band codes with a long-period (broadband) response.
_BB_BANDS = set('FCHBMLVURPTQ')
_SP_BANDS = set('GDES')

CLASS_ORDER = ('BB', 'SP', 'ACC', 'PRESS', 'OTHER')
CLASS_COLORS = {
    'BB': '#f2b134',
    'SP': '#2a9d8f',
    'ACC': '#e76f51',
    'PRESS': '#8e7cc3',
    'OTHER': '#9e9e9e',
}

CLASS_LABELS = {
    'BB': 'Broadband',
    'SP': 'Short period',
    'ACC': 'Accelerometer',
    'PRESS': 'Pressure / infrasound',
    'OTHER': 'Other',
}


def channel_class(code):
    code = (code or '').upper()
    if len(code) < 2:
        return 'OTHER'
    band, inst = code[0], code[1]
    if inst in 'HLP':
        if band in _BB_BANDS:
            return 'BB'
        if band in _SP_BANDS:
            return 'SP'
        return 'OTHER'
    if inst in 'NG':
        return 'ACC'
    if inst == 'D':
        return 'PRESS'
    return 'OTHER'


def _tstr(t):
    if t is None:
        return None
    try:
        return util.time_to_str(t, format='%Y-%m-%d')
    except Exception:
        return None


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


def _group_channels(chans):
    '''
    Compress channels with the same location, band+instrument code, sensor,
    sample rate and epoch, e.g. HHE/HHN/HHZ -> HH[ENZ].
    '''
    groups = OrderedDict()
    for ch in chans:
        key = (ch['loc'], ch['code'][:2], ch['sensor'], ch['sr'],
               ch['start'], ch['end'])
        groups.setdefault(key, []).append(ch['code'][2:] or '')
    out = []
    for (loc, prefix, sensor, sr, start, end), comps in groups.items():
        comps = sorted(set(comps))
        code = prefix + ('[%s]' % ''.join(comps) if len(comps) > 1
                         else (comps[0] if comps else ''))
        out.append({'loc': loc, 'code': code, 'sensor': sensor, 'sr': sr,
                    'start': start, 'end': end})
    return out


def _finish(net, sta, entries):
    '''Merge all epochs of NET.STA into one station record.'''
    now = time.time()
    # latest epoch defines the plotted position
    entries.sort(key=lambda e: (e['start'] if e['start'] is not None
                                else -1e30))
    last = entries[-1]
    chans = [c for e in entries for c in e['channels']]
    classes = sorted({channel_class(c['code']) for c in chans},
                     key=CLASS_ORDER.index)
    if not classes:
        classes = ['OTHER']
    sensors = []
    for c in chans:
        if c['sensor'] and c['sensor'] not in sensors:
            sensors.append(c['sensor'])

    active = any(e['end'] is None or e['end'] > now for e in entries)

    return {
        'net': net,
        'sta': sta,
        'lat': last['lat'],
        'lon': last['lon'],
        'elev': last['elev'],
        'site': last['site'],
        'start': _tstr(entries[0]['start']),
        'end': None if any(e['end'] is None for e in entries)
        else _tstr(max(e['end'] for e in entries)),
        'active': active,
        'cls': classes[0],
        'classes': classes,
        'sensors': sensors,
        'channels': [dict(c, start=_tstr(c['start']), end=_tstr(c['end']))
                     for c in _group_channels(chans)],
    }


def _from_stationxml(path):
    from pyrocko.io import stationxml
    with open(path, 'rb') as f:
        head = f.read(4096).lower()
    if b'quakeml' in head:
        raise StationError('%s è un catalogo QuakeML: caricalo con + Catalogo'
                           % op.basename(path))
    try:
        sx = stationxml.load_xml(filename=path)
    except Exception as e:
        raise StationError('impossibile leggere %s come StationXML: %s'
                           % (op.basename(path), str(e) or type(e).__name__))
    if not hasattr(sx, 'network_list'):
        raise StationError('%s non è un file StationXML' % op.basename(path))

    entries = OrderedDict()
    for network in sx.network_list:
        for station in network.station_list:
            lat = _val(station.latitude)
            lon = _val(station.longitude)
            if lat is None or lon is None:
                continue
            chans = []
            for ch in station.channel_list:
                sensor = None
                if ch.sensor is not None:
                    for attr in ('description', 'model', 'type'):
                        s = getattr(ch.sensor, attr, None)
                        if s and str(s).strip().lower() not in ('none', ''):
                            sensor = str(s).strip()
                            break
                sr = _val(ch.sample_rate)
                chans.append({
                    'loc': ch.location_code or '',
                    'code': ch.code or '',
                    'sensor': sensor,
                    'sr': sr,
                    'start': ch.start_date,
                    'end': ch.end_date,
                })
            site = None
            if station.site is not None and station.site.name:
                site = str(station.site.name)
            entries.setdefault((network.code, station.code), []).append({
                'lat': lat, 'lon': lon,
                'elev': _val(station.elevation),
                'site': site,
                'start': station.start_date,
                'end': station.end_date,
                'channels': chans,
            })

    return [_finish(net, sta, e) for (net, sta), e in entries.items()]


def _from_pyrocko(path):
    try:
        stations = model.load_stations(path)
    except Exception as e:
        raise StationError(
            'impossibile leggere %s come file di stazioni pyrocko: %s'
            % (op.basename(path), str(e) or type(e).__name__))
    entries = OrderedDict()
    for s in stations:
        if s.lat is None or s.lon is None:
            continue
        chans = [{'loc': s.location or '', 'code': c.name, 'sensor': None,
                  'sr': None, 'start': None, 'end': None}
                 for c in s.get_channels()]
        entries.setdefault((s.network, s.station), []).append({
            'lat': s.effective_lat, 'lon': s.effective_lon,
            'elev': s.elevation, 'site': getattr(s, 'description', None) or None,
            'start': None, 'end': None, 'channels': chans})
    return [_finish(net, sta, e) for (net, sta), e in entries.items()]


class StationSet:

    def __init__(self, sid, path, stations):
        self.id = sid
        self.path = path
        self.name = op.basename(path)
        self.stations = stations

    def payload(self):
        return {
            'id': self.id,
            'name': self.name,
            'path': paths.rel(self.path),
            'n': len(self.stations),
            'stations': self.stations,
            'class_labels': CLASS_LABELS,
            'class_colors': CLASS_COLORS,
        }


def load_stations(sid, path):
    if not op.isfile(path):
        raise StationError('file non trovato: %s' % path)

    with open(path, 'rb') as f:
        head = f.read(2048).lstrip()
    is_xml = head.startswith(b'<?xml') or b'FDSNStationXML' in head \
        or path.lower().endswith('.xml')

    stations = _from_stationxml(path) if is_xml else _from_pyrocko(path)
    if not stations:
        raise StationError('nessuna stazione con coordinate in %s'
                           % op.basename(path))
    return StationSet(sid, path, stations)
