'''
Local HTTP server (127.0.0.1 only) between the viewer page and pyrocko.

Every API call is a POST with a JSON body to ``/api/<name>`` and must carry
the per-run token (header ``X-CGIS-Token``) that is embedded in the page,
so that other web pages cannot use the API.
'''

import json
import logging
import mimetypes
import os
import os.path as op
import secrets
import subprocess
import sys
import threading
import time
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as num

from . import __version__, paths, colormaps, session, geo, topography
from . import exporter
from .catalog import load_catalog, CatalogError, BEACHBALL_TYPES
from .stations import load_stations, StationError
from .dialogs import Dialogs

logger = logging.getLogger('cgis')

MAX_BODY = 512 * 1024 * 1024


class ApiError(Exception):
    pass


USER_ERRORS = (ApiError, CatalogError, StationError, session.SessionError,
               geo.GeoError, topography.TopoError, exporter.ExportError)


def _num(d, key, default=None):
    v = d.get(key, default)
    if v is None:
        if default is None:
            raise ApiError('missing parameter: %s' % key)
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ApiError('invalid number for %s: %r' % (key, v))
    if v != v or v in (float('inf'), float('-inf')):
        raise ApiError('invalid number for %s' % key)
    return v


def _round_list(a, nd):
    a = num.asarray(a, dtype=float)
    out = num.round(a, nd).tolist()
    for i in num.nonzero(~num.isfinite(a))[0]:
        out[i] = None
    return out


class AppState:

    def __init__(self, dialogs=None, startup=None):
        self.lock = threading.RLock()
        self.catalogs = OrderedDict()
        self.station_sets = OrderedDict()
        self._counter = 0
        self.dialogs = dialogs or Dialogs()
        self.startup = startup or {}
        self.token = secrets.token_urlsafe(24)
        self.last_autosave = 0.

    def new_id(self, prefix):
        with self.lock:
            self._counter += 1
            return '%s%d' % (prefix, self._counter)

    def catalog(self, cid):
        try:
            return self.catalogs[cid]
        except KeyError:
            raise ApiError('unknown catalogue id: %s' % cid)

    def station_set(self, sid):
        try:
            return self.station_sets[sid]
        except KeyError:
            raise ApiError('unknown station set id: %s' % sid)


# --------------------------------------------------------------------- API


def api_init(app, req):
    return {
        'version': __version__,
        'cmaps': {k: ['#%02x%02x%02x' % c for c in v]
                  for (k, v) in colormaps.CMAPS.items()},
        'default_cmaps': {'depth': colormaps.DEFAULT_DEPTH_CMAP,
                          'time': colormaps.DEFAULT_TIME_CMAP},
        'topo_palettes': list(colormaps.TOPO_PALETTES),
        'beachball_types': list(BEACHBALL_TYPES),
        'dirs': {'project': paths.PROJECT_ROOT, 'cat': paths.CAT_DIR,
                 'meta': paths.META_DIR, 'plots': paths.PLOTS_DIR,
                 'sessions': paths.SESSIONS_DIR},
        'dialogs': app.dialogs.kind,
        'startup': app.startup,
        'sessions': session.list_sessions(),
    }


def api_files_list(app, req):
    kind = req.get('kind')
    if kind == 'catalog':
        return {'base': paths.rel(paths.CAT_DIR),
                'files': paths.list_files(paths.CAT_DIR,
                                          paths.CATALOG_EXTENSIONS)}
    if kind == 'stations':
        return {'base': paths.rel(paths.META_DIR),
                'files': paths.list_files(paths.META_DIR,
                                          paths.STATION_EXTENSIONS)}
    raise ApiError('unknown file kind: %s' % kind)


def api_dialog_open(app, req):
    kind = req.get('kind', 'catalog')
    start = {'catalog': paths.CAT_DIR, 'stations': paths.META_DIR,
             'session': paths.SESSIONS_DIR}.get(kind, paths.PROJECT_ROOT)
    if not op.isdir(start):
        start = paths.PROJECT_ROOT
    title = {'catalog': 'Aggiungi catalogo', 'stations': 'Aggiungi stazioni',
             'session': 'Apri sessione'}.get(kind, 'Apri')
    res = app.dialogs.open_files(title, start, kind,
                                 multiple=kind != 'session')
    if res is None:
        return {'available': False, 'paths': []}
    return {'available': True, 'paths': [op.abspath(p) for p in res]}


def api_dialog_save(app, req):
    fmt = str(req.get('format', 'pdf')).lower()
    name = op.basename(str(req.get('name') or 'cgis_figure'))
    start_dir = req.get('dir') or paths.PLOTS_DIR
    paths.ensure_dir(paths.PLOTS_DIR)
    if not op.isdir(start_dir):
        start_dir = paths.PLOTS_DIR
    if not name.lower().endswith('.' + fmt):
        name = op.splitext(name)[0] + '.' + fmt
    res = app.dialogs.save_file(req.get('title') or 'Salva',
                                op.join(start_dir, name), fmt)
    if res is None:
        return {'available': False, 'path': None}
    if not res:
        return {'available': True, 'path': None}
    res = op.abspath(res)
    if not res.lower().endswith('.' + fmt):
        res += '.' + fmt
    return {'available': True, 'path': res}


def _input_path(req):
    p = str(req.get('path') or '').strip()
    if not p:
        raise ApiError('nessun file indicato')
    return paths.resolve(p)


def api_catalog_load(app, req):
    path = _input_path(req)
    cid = app.new_id('c')
    t0 = time.time()
    cat = load_catalog(cid, path)
    with app.lock:
        app.catalogs[cid] = cat
    payload = cat.payload()
    logger.info('loaded %s: %d events (%d skipped) in %.1f s',
                cat.name, len(cat.events), cat.n_skipped, time.time() - t0)
    return payload


def api_catalog_remove(app, req):
    with app.lock:
        app.catalogs.pop(req.get('id'), None)
    return {}


def api_catalog_beachballs(app, req):
    cat = app.catalog(req.get('id'))
    return cat.beachballs(req.get('type', 'deviatoric'))


def _check_out_path(path, exts):
    if not path:
        raise ApiError('nessun file di uscita')
    path = op.abspath(op.expanduser(path))
    if not path.lower().endswith(exts):
        raise ApiError('il file deve terminare con %s' % ' o '.join(exts))
    d = op.dirname(path)
    if not op.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            raise ApiError('impossibile creare la cartella %s: %s' % (d, e))
    return path


def api_catalog_export(app, req):
    from pyrocko import model
    path = _check_out_path(req.get('path'), ('.pf', '.yaml', '.yml'))
    events = []
    for item in req.get('items', []):
        cat = app.catalog(item.get('id'))
        idx = sorted(set(int(i) for i in item.get('indices', [])
                         if 0 <= int(i) < len(cat.events)))
        events.extend(cat.events[i] for i in idx)
    if not events:
        raise ApiError('nessun evento da esportare')
    events.sort(key=lambda ev: ev.time)
    fmt = 'yaml' if path.lower().endswith(('.yaml', '.yml')) else 'basic'
    model.dump_events(events, filename=path, format=fmt)
    return {'path': path, 'n': len(events)}


def api_stations_load(app, req):
    path = _input_path(req)
    sid = app.new_id('s')
    ss = load_stations(sid, path)
    with app.lock:
        app.station_sets[sid] = ss
    return ss.payload()


def api_stations_remove(app, req):
    with app.lock:
        app.station_sets.pop(req.get('id'), None)
    return {}


def api_section_project(app, req):
    lat1, lon1 = _num(req, 'lat1'), _num(req, 'lon1')
    lat2, lon2 = _num(req, 'lat2'), _num(req, 'lon2')
    length_km, azimuth = geo.section_frame(lat1, lon1, lat2, lon2)
    out = {'length_km': length_km, 'azimuth': azimuth, 'cats': {},
           'stas': {}}
    for cid in req.get('cats', []):
        cat = app.catalog(cid)
        s, d, _, _ = geo.project(lat1, lon1, lat2, lon2, cat.lat, cat.lon)
        out['cats'][cid] = {'s': _round_list(s, 5), 'd': _round_list(d, 5)}
    for sid in req.get('stas', []):
        ss = app.station_set(sid)
        lats = [st['lat'] for st in ss.stations]
        lons = [st['lon'] for st in ss.stations]
        s, d, _, _ = geo.project(lat1, lon1, lat2, lon2, lats, lons)
        out['stas'][sid] = {'s': _round_list(s, 5), 'd': _round_list(d, 5)}
    return out


def api_section_beachballs(app, req):
    cat = app.catalog(req.get('id'))
    return cat.section_beachballs(
        req.get('indices', []), _num(req, 'azimuth'),
        req.get('type', 'deviatoric'))


def api_topo_profile(app, req):
    s, elev, name = topography.profile(
        _num(req, 'lat1'), _num(req, 'lon1'), _num(req, 'lat2'),
        _num(req, 'lon2'), n=int(_num(req, 'n', 400)),
        bathymetry=bool(req.get('bathymetry', False)))
    return {'s': _round_list(s, 4), 'elev': _round_list(elev, 1),
            'source': name}


def _export(kind):
    func = getattr(exporter, 'export_' + kind)

    def f(app, req):
        return func(app, req)
    return f


def api_export_raw(app, req):
    '''Write a file produced in the page (Plotly SVG / PNG data URL).'''
    import base64
    path = _check_out_path(req.get('path'), ('.svg', '.png'))
    content = req.get('content') or ''
    if content.startswith('data:'):
        header, _, data = content.partition(',')
        if ';base64' in header:
            raw = base64.b64decode(data)
        else:
            from urllib.parse import unquote
            raw = unquote(data).encode('utf-8')
    else:
        raw = content.encode('utf-8')
    with open(path, 'wb') as f:
        f.write(raw)
    return {'path': path}


def api_session_save(app, req):
    fn = session.save(req.get('state') or {}, req.get('name'))
    return {'path': fn, 'name': op.splitext(op.basename(fn))[0],
            'sessions': session.list_sessions()}


def api_session_autosave(app, req):
    session.save(req.get('state') or {}, session.AUTOSAVE_NAME)
    app.last_autosave = time.time()
    return {}


def api_session_list(app, req):
    return {'sessions': session.list_sessions()}


def api_session_load(app, req):
    name = req.get('name') or req.get('path')
    if not name:
        raise ApiError('no session given')
    return session.load(name)


def api_session_delete(app, req):
    name = session.check_name(req.get('name'))
    if name == session.AUTOSAVE_NAME:
        raise ApiError('la sessione automatica non si può eliminare')
    session.delete(name)
    return {'sessions': session.list_sessions()}


def api_reveal(app, req):
    path = op.abspath(req.get('path') or '')
    if not op.exists(path):
        raise ApiError('file non trovato: %s' % path)
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', op.dirname(path)])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', '/select,', path])
    except OSError as e:
        raise ApiError('cannot open file browser: %s' % e)
    return {}


def api_log(app, req):
    level = req.get('level', 'info')
    msg = str(req.get('msg', ''))[:20000]
    (logger.error if level == 'error' else logger.info)('[page] %s', msg)
    return {}


API = {
    'init': api_init,
    'files_list': api_files_list,
    'dialog_open': api_dialog_open,
    'dialog_save': api_dialog_save,
    'catalog_load': api_catalog_load,
    'catalog_remove': api_catalog_remove,
    'catalog_beachballs': api_catalog_beachballs,
    'catalog_export': api_catalog_export,
    'stations_load': api_stations_load,
    'stations_remove': api_stations_remove,
    'section_project': api_section_project,
    'section_beachballs': api_section_beachballs,
    'topo_profile': api_topo_profile,
    'export_map': _export('map'),
    'export_section': _export('section'),
    'export_timeplot': _export('timeplot'),
    'export_stereonet': _export('stereonet'),
    'export_raw': api_export_raw,
    'session_save': api_session_save,
    'session_autosave': api_session_autosave,
    'session_list': api_session_list,
    'session_load': api_session_load,
    'session_delete': api_session_delete,
    'reveal': api_reveal,
    'log': api_log,
}


# ----------------------------------------------------------------- server


def _plotly_js_path():
    try:
        import plotly
    except ImportError:
        return None
    p = op.join(op.dirname(plotly.__file__), 'package_data', 'plotly.min.js')
    return p if op.isfile(p) else None


class Handler(BaseHTTPRequestHandler):
    server_version = 'cgis/' + __version__
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype, extra_headers=()):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _send_json(self, code, obj):
        try:
            body = json.dumps(obj, allow_nan=False,
                              separators=(',', ':')).encode('utf-8')
        except ValueError as e:
            logger.error('non-JSON-compliant response: %s', e)
            body = json.dumps({'ok': False, 'error': 'internal error: %s'
                               % e}).encode('utf-8')
            code = 500
        self._send(code, body, 'application/json; charset=utf-8')

    def _send_file(self, path, ctype=None):
        try:
            with open(path, 'rb') as f:
                body = f.read()
        except OSError:
            self._send(404, b'not found', 'text/plain')
            return
        if ctype is None:
            ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype.endswith('javascript'):
                ctype += '; charset=utf-8'
        self._send(200, body, ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        app = self.server.app
        url = self.path.split('?', 1)[0]
        if url in ('/', '/index.html'):
            try:
                with open(op.join(paths.STATIC_DIR, 'index.html'), 'rb') as f:
                    html = f.read().replace(b'{{TOKEN}}',
                                            app.token.encode('ascii'))
            except OSError:
                self._send(500, b'index.html missing', 'text/plain')
                return
            self._send(200, html, 'text/html; charset=utf-8')
            return

        if url == '/vendor/plotly.min.js':
            p = _plotly_js_path()
            if p:
                self._send_file(p, 'text/javascript; charset=utf-8')
            else:
                self._send(404, b'not found', 'text/plain')
            return

        if url.startswith('/static/'):
            rel = url[len('/static/'):]
            full = op.realpath(op.join(paths.STATIC_DIR, rel))
            root = op.realpath(paths.STATIC_DIR)
            if not full.startswith(root + os.sep) or not op.isfile(full):
                self._send(404, b'not found', 'text/plain')
                return
            self._send_file(full)
            return

        if url == '/favicon.ico':
            self._send(204, b'', 'image/x-icon')
            return

        self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        app = self.server.app
        url = self.path.split('?', 1)[0]
        if not url.startswith('/api/'):
            self._send_json(404, {'ok': False, 'error': 'not found'})
            return
        if self.headers.get('X-CGIS-Token') != app.token:
            self._send_json(403, {'ok': False, 'error': 'forbidden'})
            return
        name = url[len('/api/'):]
        func = API.get(name)
        if func is None:
            self._send_json(404, {'ok': False,
                                  'error': 'unknown API call: %s' % name})
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n > MAX_BODY:
                raise ApiError('request too large')
            raw = self.rfile.read(n) if n > 0 else b'{}'
            req = json.loads(raw.decode('utf-8') or '{}')
            if not isinstance(req, dict):
                raise ApiError('request must be a JSON object')
        except (ValueError, UnicodeDecodeError, ApiError) as e:
            self._send_json(400, {'ok': False,
                                  'error': 'bad request: %s' % e})
            return

        t0 = time.time()
        try:
            res = func(app, req)
            out = {'ok': True}
            out.update(res or {})
            self._send_json(200, out)
        except USER_ERRORS as e:
            logger.warning('%s: %s', name, e)
            self._send_json(400, {'ok': False, 'error': str(e)})
        except Exception as e:
            logger.error('%s failed:\n%s', name, traceback.format_exc())
            self._send_json(500, {'ok': False, 'error': '%s: %s'
                                  % (type(e).__name__, e)})
        finally:
            dt = time.time() - t0
            if dt > 2.:
                logger.info('%s took %.1f s', name, dt)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, app, port=0):
        ThreadingHTTPServer.__init__(self, ('127.0.0.1', port), Handler)
        self.app = app

    @property
    def url(self):
        return 'http://127.0.0.1:%d/' % self.server_address[1]


def start_server(app, port=0):
    srv = Server(app, port)
    th = threading.Thread(target=srv.serve_forever, name='cgis-server',
                          daemon=True)
    th.start()
    return srv
