'''
Catalogues in text tables (.txt, .csv, .tsv, .dat).

The reader recognises the separator (comma, semicolon, tab, pipe, spaces),
the header line (also when it starts with '#') and the meaning of the
columns from their names, using the aliases in ``ALIASES`` (case, units and
punctuation are ignored: 'Depth/km', 'depth (km)' and 'DEPTH_KM' are all
'depth' in km). Without a header, or when the time or the coordinates are
not recognised, the viewer asks for the columns in a dialog; the chosen
mapping is stored in the session.

Columns that are not used become event "extras" and are shown in the
tooltip.
'''

import calendar
import csv
import io
import math
import os.path as op
import re

import numpy as num

from pyrocko import model
from pyrocko import moment_tensor as pmt

from .catalog import CatalogError

TEXT_EXTENSIONS = ('.txt', '.csv', '.tsv', '.dat')

# normalised column name -> field. Extend freely: names are compared after
# lower-casing and removing units, spaces and punctuation.
ALIASES = {
    'time': ['time', 'datetime', 'origintime', 'otime', 'ot', 'timeutc',
             'utctime', 'dateutc', 'dataora', 'tempo', 'origin', 'timestamp'],
    'date': ['date', 'data', 'day'],
    'year': ['year', 'yr', 'yyyy', 'anno'],
    'month': ['month', 'mo', 'mm', 'mese'],
    'dayofmonth': ['day', 'dd', 'dy', 'giorno'],
    'hour': ['hour', 'hr', 'hh', 'ora'],
    'minute': ['minute', 'min', 'mi', 'minuto'],
    'second': ['second', 'sec', 'ss', 'secondo', 'seconds'],
    'lat': ['lat', 'latitude', 'latitudine', 'evla', 'latdeg'],
    'lon': ['lon', 'long', 'longitude', 'longitudine', 'lng', 'evlo',
            'londeg'],
    'depth': ['depth', 'dep', 'profondita', 'prof', 'evdp', 'z', 'depthkm',
              'depthm'],
    'mag': ['magnitude', 'mag', 'magnitudo', 'mw', 'ml', 'md', 'mb', 'ms',
            'mwp', 'mlv', 'mlingv', 'preferredmagnitude', 'magvalue', 'm'],
    'magtype': ['magtype', 'magnitudetype', 'tipomag', 'tipomagnitudo'],
    'name': ['name', 'eventname', 'eventid', 'evid', 'id', 'event', 'nome',
             'publicid', 'event_id'],
    'strike': ['strike', 'strike1', 'str', 'strike_1'],
    'dip': ['dip', 'dip1', 'dip_1'],
    'rake': ['rake', 'rake1', 'slip', 'rake_1'],
}

MT_NED = ['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med']
MT_USE = ['mrr', 'mtt', 'mff', 'mrt', 'mrf', 'mtf']
MT_GMT = ['m1', 'm2', 'm3', 'm4', 'm5', 'm6']     # mrr mtt mff mrt mrf mtf

MISSING = {'', 'none', 'nan', 'null', 'na', 'n/a', '-', '--', '?', 'nd'}

_DATE_RE = re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$')
_TIME_RE = re.compile(r'^\d{1,2}:\d{2}(:\d{2}(\.\d*)?)?Z?$')
_DATETIME_RE = re.compile(
    r'^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})'
    r'(?:[T _]+(\d{1,2}):(\d{2})(?::(\d{1,2}(?:\.\d*)?))?)?\s*(?:Z|UTC)?\s*$',
    re.I)
_TOD_RE = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{1,2}(?:\.\d*)?))?\s*Z?\s*$')
_NAME_TIME_RE = re.compile(r'(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})')
_UNIT_RE = re.compile(r'^(.*?)\s*(?:[(\[]\s*([^)\]]*)\s*[)\]]|/\s*([a-z]+))\s*$',
                      re.I)


class TextCatalogError(CatalogError):
    pass


# ------------------------------------------------------------------- table


def normalize_name(name):
    '''Column name -> (key, unit): 'Depth/km' -> ('depth', 'km').'''
    s = str(name or '').strip().lstrip('#').strip()
    unit = None
    m = _UNIT_RE.match(s)
    if m and m.group(1):
        s = m.group(1)
        unit = (m.group(2) or m.group(3) or '').strip().lower() or None
    key = re.sub(r'[^a-z0-9]', '', s.lower())
    for suffix, u in (('km', 'km'), ('m', 'm')):
        # depth_km, depthm ...
        if key.startswith('dep') and key.endswith(suffix) and unit is None \
                and key not in ('dep', 'depth'):
            unit = u
    return key, unit


def _is_number(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _is_missing(s):
    return s is None or str(s).strip().lower() in MISSING


def _split_ws(line):
    '''Whitespace split keeping "date time" and "Name (unit)" together.'''
    toks = line.split()
    out = []
    for t in toks:
        if out and _DATE_RE.match(out[-1]) and _TIME_RE.match(t):
            out[-1] = out[-1] + ' ' + t
        elif out and re.match(r'^[(\[][^)\]]*[)\]]$', t) \
                and not _is_number(out[-1]):
            out[-1] = out[-1] + ' ' + t
        else:
            out.append(t)
    return out


DELIMITERS = {',': 'virgola', ';': 'punto e virgola', '\t': 'tab',
              '|': 'barra verticale', 'ws': 'spazi'}


class Table:

    def __init__(self, header, rows, delimiter, n_lines):
        self.header = header          # list of names or None
        self.rows = rows              # list of lists of strings
        self.delimiter = delimiter
        self.n_lines = n_lines
        self.ncols = max((len(r) for r in rows), default=0)
        if header is not None:
            self.ncols = max(self.ncols, len(header))

    def names(self):
        if self.header is not None:
            return [h.strip() or 'colonna %d' % (i + 1)
                    for i, h in enumerate(self.header)] + [
                'colonna %d' % (i + 1)
                for i in range(len(self.header), self.ncols)]
        return ['colonna %d' % (i + 1) for i in range(self.ncols)]

    def column(self, i, limit=None):
        rows = self.rows if limit is None else self.rows[:limit]
        return [r[i] if i < len(r) else '' for r in rows]


def _read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TextCatalogError('impossibile decodificare %s' % op.basename(path))


def _split(line, delim):
    if delim == 'ws':
        return _split_ws(line)
    return [c.strip() for c in next(csv.reader(io.StringIO(line),
                                               delimiter=delim))]


def _detect_delimiter(lines):
    best = None
    for d in ('\t', ',', ';', '|'):
        counts = [len(_split(ln, d)) for ln in lines]
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        share = counts.count(mode) / float(len(counts))
        if mode >= 3 and share >= 0.8:
            if best is None or mode > best[1]:
                best = (d, mode)
    if best:
        return best[0]
    return 'ws'


def read_table(path, delimiter=None, header=None):
    '''
    Parse a text table. ``delimiter`` (',', ';', '\\t', '|', 'ws') and
    ``header`` (True/False) override the automatic detection.
    '''
    text = _read_text(path)
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or not re.search(r'[A-Za-z0-9]', s):
            continue                # empty or separator line (----, ═══)
        lines.append(ln.rstrip('\r\n'))
    if not lines:
        raise TextCatalogError('%s è vuoto' % op.basename(path))

    first = lines[0].strip()
    comment_header = first.startswith('#') or first.startswith('%')
    body = [ln for ln in lines[1:] if not ln.strip().startswith(('#', '%'))]
    sample = body[:200] if body else lines[:1]

    delim = delimiter if delimiter in DELIMITERS else \
        _detect_delimiter(sample)

    head_line = first.lstrip('#%').strip() if comment_header else first
    head = _split(head_line, delim)

    if header is None:
        nonnum = sum(1 for h in head if h and not _is_number(h)
                     and not _DATETIME_RE.match(h) and not _is_missing(h))
        header = comment_header or nonnum >= max(1, len(head) // 2)

    rows_src = body if header else [first] + body
    rows = [_split(ln, delim) for ln in rows_src]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise TextCatalogError('%s non contiene righe di dati'
                               % op.basename(path))

    hdr = None
    if header:
        ncol = max(set(len(r) for r in rows[:200]),
                   key=[len(r) for r in rows[:200]].count)
        hdr = head
        if len(hdr) == ncol - 1:
            hdr = [''] + hdr        # e.g. "#" over an index column
        elif len(hdr) > ncol and comment_header and hdr and \
                normalize_name(hdr[0])[0] == '':
            hdr = hdr[1:]
    return Table(hdr, rows, delim, len(lines))


# ------------------------------------------------------------------ values


def parse_float(s):
    if _is_missing(s):
        return float('nan')
    try:
        return float(str(s).strip().replace(',', '.') if ',' in str(s)
                     and '.' not in str(s) else str(s).strip())
    except ValueError:
        return float('nan')


def parse_datetime(s):
    '''Date/time string (UTC) -> seconds, NaN if not understood.'''
    if _is_missing(s):
        return float('nan')
    m = _DATETIME_RE.match(str(s))
    if not m:
        return float('nan')
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h = int(m.group(4) or 0)
    mi = int(m.group(5) or 0)
    sec = float(m.group(6) or 0.)
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59
            and sec < 61):
        return float('nan')
    try:
        if d > calendar.monthrange(y, mo)[1]:
            return float('nan')
    except ValueError:
        return float('nan')
    return calendar.timegm((y, mo, d, h, mi, 0)) + sec


def parse_time_of_day(s):
    m = _TOD_RE.match(str(s or ''))
    if not m:
        return float('nan')
    h, mi = int(m.group(1)), int(m.group(2))
    sec = float(m.group(3) or 0.)
    if h > 23 or mi > 59 or sec >= 61:
        return float('nan')
    return h * 3600. + mi * 60. + sec


def numeric_time(v):
    '''Epoch seconds or decimal year -> seconds.'''
    if not math.isfinite(v):
        return float('nan')
    if 1800. < v < 2200.:
        y = int(math.floor(v))
        t0 = calendar.timegm((y, 1, 1, 0, 0, 0))
        t1 = calendar.timegm((y + 1, 1, 1, 0, 0, 0))
        return t0 + (v - y) * (t1 - t0)
    if v > 1e8:
        return v
    return float('nan')


def time_from_name(s):
    m = _NAME_TIME_RE.search(str(s or ''))
    if not m:
        return float('nan')
    y, mo, d, h, mi, sec = [int(x) for x in m.groups()]
    return parse_datetime('%04d-%02d-%02d %02d:%02d:%02d'
                          % (y, mo, d, h, mi, sec))


def _share(values, func):
    vals = [v for v in values if not _is_missing(v)]
    if not vals:
        return 0.
    return sum(1 for v in vals if math.isfinite(func(v))) / float(len(vals))


# ------------------------------------------------------------------ mapping


def default_mapping():
    return {
        'delimiter': None, 'header': None,
        'time': {'kind': 'column', 'cols': [None, None]},
        'lat': None, 'lon': None,
        'depth': None, 'depth_unit': 'km', 'depth_sign': 'down',
        'mag': None, 'magtype_col': None, 'mag_type': None,
        'name': None,
        'mt': {'kind': 'none', 'cols': []},
    }


def guess_mapping(table):
    '''
    Guess the column mapping. Returns ``(mapping, confident)``: the file
    is loaded without asking only when ``confident`` is True.
    '''
    mp = default_mapping()
    mp['delimiter'] = table.delimiter
    mp['header'] = table.header is not None
    sample = 300
    used = set()

    keys = []
    units = []
    if table.header is not None:
        for h in table.names():
            k, u = normalize_name(h)
            keys.append(k)
            units.append(u)
    else:
        keys = [''] * table.ncols
        units = [None] * table.ncols

    def find(field, prefer=None):
        aliases = ALIASES[field] if prefer is None else prefer
        for a in aliases:
            for i, k in enumerate(keys):
                if i not in used and k == a:
                    return i
        return None

    def take(i):
        if i is not None:
            used.add(i)
        return i

    by_name = table.header is not None

    # ---- name / id
    mp['name'] = take(find('name'))

    # ---- time
    t_col = find('time')
    d_col = find('date')
    if t_col is not None:
        col = table.column(t_col, sample)
        if _share(col, parse_datetime) >= 0.9:
            mp['time'] = {'kind': 'column', 'cols': [take(t_col), None]}
        elif d_col is not None and _share(col, parse_time_of_day) >= 0.9:
            mp['time'] = {'kind': 'column', 'cols': [take(d_col),
                                                     take(t_col)]}
        elif _share(col, lambda s: numeric_time(parse_float(s))) >= 0.9:
            mp['time'] = {'kind': 'column', 'cols': [take(t_col), None]}
        else:
            t_col = None
    if mp['time']['cols'][0] is None and d_col is not None:
        col = table.column(d_col, sample)
        if _share(col, parse_datetime) >= 0.9:
            mp['time'] = {'kind': 'column', 'cols': [take(d_col), None]}
    if mp['time']['cols'][0] is None:
        ymd = [find(f) for f in ('year', 'month', 'dayofmonth', 'hour',
                                 'minute', 'second')]
        if all(c is not None for c in ymd[:3]):
            for c in ymd:
                take(c)
            mp['time'] = {'kind': 'ymd', 'cols': ymd}

    # content based (no header or not recognised)
    if mp['time']['kind'] == 'column' and mp['time']['cols'][0] is None:
        for i in range(table.ncols):
            if i in used:
                continue
            col = table.column(i, sample)
            if _share(col, parse_datetime) >= 0.9 and any(
                    not _is_missing(v) for v in col):
                mp['time'] = {'kind': 'column', 'cols': [take(i), None]}
                break
    if mp['time']['kind'] == 'column' and mp['time']['cols'][0] is None:
        name_col = mp['name']
        if name_col is None:
            for i in range(table.ncols):
                if i not in used and _share(table.column(i, sample),
                                            time_from_name) >= 0.9:
                    name_col = mp['name'] = take(i)
                    break
        if name_col is not None and _share(table.column(name_col, sample),
                                           time_from_name) >= 0.9:
            mp['time'] = {'kind': 'name', 'cols': []}

    # ---- coordinates, depth, magnitude by name
    mp['lat'] = take(find('lat'))
    mp['lon'] = take(find('lon'))
    mp['depth'] = take(find('depth'))
    mag_pref = ['mw', 'magnitude', 'mag', 'magnitudo', 'preferredmagnitude',
                'magvalue', 'ml', 'mlv', 'mlingv', 'md', 'mb', 'ms', 'mwp',
                'm']
    mp['mag'] = take(find('mag', mag_pref))
    mp['magtype_col'] = take(find('magtype'))
    if mp['mag'] is not None and keys[mp['mag']] in (
            'mw', 'ml', 'md', 'mb', 'ms', 'mwp', 'mlv'):
        mp['mag_type'] = keys[mp['mag']].upper().replace('MW', 'Mw')

    # ---- moment tensor
    for kind, names in (('ned', MT_NED), ('use', MT_USE), ('gmt', MT_GMT)):
        cols = [find(None, [n]) for n in names]
        if all(c is not None for c in cols):
            for c in cols:
                take(c)
            mp['mt'] = {'kind': kind, 'cols': cols}
            break
    if mp['mt']['kind'] == 'none':
        sdr = [find('strike'), find('dip'), find('rake')]
        if all(c is not None for c in sdr):
            for c in sdr:
                take(c)
            mp['mt'] = {'kind': 'sdr', 'cols': sdr}

    # ---- content based coordinates when not named
    numeric = [i for i in range(table.ncols) if i not in used
               and _share(table.column(i, sample), parse_float) >= 0.9]
    if mp['lat'] is None or mp['lon'] is None:
        for i in numeric:
            vals = [parse_float(v) for v in table.column(i, sample)]
            vals = [v for v in vals if math.isfinite(v)]
            if not vals:
                continue
            if mp['lat'] is None and all(-90 <= v <= 90 for v in vals):
                mp['lat'] = take(i)
            elif mp['lon'] is None and all(-180 <= v <= 360 for v in vals):
                mp['lon'] = take(i)
            if mp['lat'] is not None and mp['lon'] is not None:
                break
    if not by_name:
        rest = [i for i in range(table.ncols) if i not in used
                and _share(table.column(i, sample), parse_float) >= 0.9]
        if mp['depth'] is None and rest:
            mp['depth'] = take(rest.pop(0))
        if mp['mag'] is None and rest:
            mp['mag'] = take(rest.pop(0))
        if mp['name'] is None:
            for i in range(table.ncols):
                col = table.column(i, sample)
                if i not in used and any(not _is_missing(v) for v in col) \
                        and _share(col, parse_float) < 0.5:
                    mp['name'] = take(i)
                    break

    # ---- depth unit and sign
    if mp['depth'] is not None:
        unit = units[mp['depth']] if units else None
        vals = num.array([parse_float(v)
                          for v in table.column(mp['depth'], 2000)])
        vals = vals[num.isfinite(vals)]
        if unit in ('km', 'm'):
            mp['depth_unit'] = unit
        elif vals.size:
            mp['depth_unit'] = 'm' if num.median(num.abs(vals)) > 100. \
                else 'km'
        if vals.size and num.mean(vals < 0.) >= 0.8:
            mp['depth_sign'] = 'up'

    time_ok = (mp['time']['kind'] in ('name', 'ymd')
               or mp['time']['cols'][0] is not None)
    confident = bool(by_name and time_ok and mp['lat'] is not None
                     and mp['lon'] is not None
                     and keys[mp['lat']] in ALIASES['lat']
                     and keys[mp['lon']] in ALIASES['lon'])
    return mp, confident


def check_mapping(mp, ncols):
    def ok(i):
        return i is None or (isinstance(i, int) and 0 <= i < ncols)

    if mp.get('lat') is None or mp.get('lon') is None:
        raise TextCatalogError('scegli le colonne di latitudine e longitudine')
    for k in ('lat', 'lon', 'depth', 'mag', 'magtype_col', 'name'):
        if not ok(mp.get(k)):
            raise TextCatalogError('colonna non valida per %s' % k)
    t = mp.get('time') or {}
    kind = t.get('kind')
    if kind not in ('column', 'ymd', 'name', 'none'):
        raise TextCatalogError('modalità del tempo non valida')
    cols = t.get('cols') or []
    if kind == 'column' and (not cols or cols[0] is None):
        raise TextCatalogError('scegli la colonna del tempo')
    if kind == 'ymd' and (len(cols) < 3 or any(c is None for c in cols[:3])):
        raise TextCatalogError('scegli almeno anno, mese e giorno')
    if kind == 'name' and mp.get('name') is None:
        raise TextCatalogError('per ricavare il tempo dal nome scegli la '
                               'colonna del nome')
    if not all(ok(c) for c in cols):
        raise TextCatalogError('colonna del tempo non valida')
    m = mp.get('mt') or {'kind': 'none'}
    need = {'none': 0, 'sdr': 3, 'ned': 6, 'use': 6, 'gmt': 6}
    if m.get('kind') not in need:
        raise TextCatalogError('tipo di tensore momento non valido')
    mc = m.get('cols') or []
    if need[m['kind']] and (len(mc) < need[m['kind']]
                            or any(c is None or not ok(c)
                                   for c in mc[:need[m['kind']]])):
        raise TextCatalogError('scegli tutte le colonne del tensore momento')
    if mp.get('depth_unit') not in ('km', 'm'):
        raise TextCatalogError('unità della profondità non valida')
    if mp.get('depth_sign') not in ('down', 'up'):
        raise TextCatalogError('verso della profondità non valido')


# ------------------------------------------------------------------- events


def build_events(table, mp):
    check_mapping(mp, table.ncols)
    names = table.names()
    used = {mp[k] for k in ('lat', 'lon', 'depth', 'mag', 'magtype_col',
                            'name') if mp.get(k) is not None}
    used.update(c for c in (mp['time'].get('cols') or []) if c is not None)
    used.update(c for c in (mp['mt'].get('cols') or []) if c is not None)
    # unused columns become extras, except unnamed ones (index columns)
    named = [i < len(table.header or []) and table.header[i].strip()
             .lstrip('#').strip() != '' for i in range(table.ncols)] \
        if table.header is not None else [True] * table.ncols
    extra_cols = [i for i in range(table.ncols) if i not in used
                  and named[i]]

    dfac = 1000. if mp['depth_unit'] == 'km' else 1.
    dsign = 1. if mp['depth_sign'] == 'down' else -1.
    tk = mp['time']['kind']
    tcols = mp['time'].get('cols') or []
    mtk = mp['mt']['kind']
    mtc = mp['mt'].get('cols') or []

    def cell(row, i):
        return row[i] if i is not None and i < len(row) else ''

    events = []
    skipped = 0
    for irow, row in enumerate(table.rows):
        lat = parse_float(cell(row, mp['lat']))
        lon = parse_float(cell(row, mp['lon']))
        if not (math.isfinite(lat) and math.isfinite(lon)
                and -90. <= lat <= 90.):
            skipped += 1
            continue
        name = cell(row, mp['name']).strip() if mp['name'] is not None \
            else ''

        if tk == 'column':
            raw = cell(row, tcols[0])
            if len(tcols) > 1 and tcols[1] is not None:
                t = parse_datetime(raw)
                if math.isfinite(t):
                    tod = parse_time_of_day(cell(row, tcols[1]))
                    t = t + tod if math.isfinite(tod) else float('nan')
            else:
                t = parse_datetime(raw)
                if not math.isfinite(t):
                    t = numeric_time(parse_float(raw))
        elif tk == 'ymd':
            parts = [parse_float(cell(row, c)) if c is not None else 0.
                     for c in (list(tcols) + [None] * 6)[:6]]
            if all(math.isfinite(p) for p in parts):
                y, mo, d, h, mi, s = parts
                t = parse_datetime('%04d-%02d-%02d %02d:%02d:00' % (
                    int(y), int(mo), int(d), int(h), int(mi)))
                t = t + s if math.isfinite(t) else t
            else:
                t = float('nan')
        elif tk == 'name':
            t = time_from_name(name)
        else:
            t = 0.
        if not math.isfinite(t):
            skipped += 1
            continue

        depth = parse_float(cell(row, mp['depth'])) * dfac * dsign \
            if mp['depth'] is not None else float('nan')
        mag = parse_float(cell(row, mp['mag'])) \
            if mp['mag'] is not None else float('nan')
        mag_type = None
        if mp.get('magtype_col') is not None:
            mt_s = cell(row, mp['magtype_col']).strip()
            mag_type = mt_s if not _is_missing(mt_s) else None
        if mag_type is None:
            mag_type = mp.get('mag_type') or None

        mt = None
        extras = {}
        if mtk != 'none':
            vals = [parse_float(cell(row, c)) for c in mtc]
            if all(math.isfinite(v) for v in vals):
                try:
                    if mtk == 'sdr':
                        if math.isfinite(mag):
                            mt = pmt.MomentTensor(strike=vals[0], dip=vals[1],
                                                  rake=vals[2], magnitude=mag)
                        else:
                            mt = pmt.MomentTensor(strike=vals[0], dip=vals[1],
                                                  rake=vals[2])
                            extras['_cgis_no_moment'] = 1
                    elif mtk == 'ned':
                        mt = pmt.MomentTensor(
                            mnn=vals[0], mee=vals[1], mdd=vals[2],
                            mne=vals[3], mnd=vals[4], med=vals[5])
                    else:       # use / gmt: mrr mtt mff mrt mrf mtf
                        mt = pmt.MomentTensor(
                            m_up_south_east=pmt.symmat6(*vals))
                except Exception:
                    mt = None

        for i in extra_cols:
            v = cell(row, i).strip()
            if not _is_missing(v):
                key = names[i] if names[i].strip() else 'colonna %d' % (i + 1)
                extras[key] = v

        events.append(model.Event(
            lat=lat, lon=lon, time=t,
            depth=depth if math.isfinite(depth) else None,
            magnitude=mag if math.isfinite(mag) else None,
            magnitude_type=mag_type,
            name=name or 'ev_%d' % (irow + 1),
            moment_tensor=mt,
            extras=extras or None))
    return events, skipped


def preview(table, n=8):
    return {
        'names': table.names(),
        'rows': [[(r[i] if i < len(r) else '') for i in range(table.ncols)]
                 for r in table.rows[:n]],
        'n_rows': len(table.rows),
        'delimiter': table.delimiter,
        'header': table.header is not None,
        'delimiters': DELIMITERS,
    }


def inspect(path, delimiter=None, header=None):
    table = read_table(path, delimiter=delimiter, header=header)
    mp, confident = guess_mapping(table)
    return table, mp, confident


def load(path, mapping=None):
    '''
    Returns ``(events, n_skipped, mapping, None)`` or, when the columns
    must be confirmed by the user, ``(None, 0, guess, preview)``.
    '''
    if mapping:
        table = read_table(path, delimiter=mapping.get('delimiter'),
                           header=mapping.get('header'))
        mp = default_mapping()
        mp.update(mapping)
    else:
        table, mp, confident = inspect(path)
        if not confident:
            return None, 0, mp, preview(table)
    events, skipped = build_events(table, mp)
    if not events:
        raise TextCatalogError(
            'nessun evento valido in %s: controlla le colonne scelte'
            % op.basename(path))
    return events, skipped, mp, None
