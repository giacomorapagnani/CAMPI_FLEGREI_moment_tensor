'''
Local HTTP server (127.0.0.1 only) between the csta page and the
catalogues. Same protocol as cgis: every API call is a POST with a JSON body
to ``/api/<name>`` carrying the per-run token (header ``X-CSTA-Token``)
embedded in the page, so that other web pages cannot use the API.

Calls that change the catalogues return the new state in ``state``.
'''

import json
import logging
import mimetypes
import os
import os.path as op
import secrets
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cgis.dialogs import Dialogs
from cgis.stations import CLASS_COLORS, CLASS_LABELS, CLASS_ORDER

from . import __version__, paths
from .inventory import InventoryError
from .state import State, SETOPS

logger = logging.getLogger('csta')

MAX_BODY = 64 * 1024 * 1024
MAX_LIST = 2 * 1024 * 1024


class ApiError(Exception):
    pass


USER_ERRORS = (ApiError, InventoryError)


class AppState:

    def __init__(self, state=None, dialogs=None):
        self.state = state or State()
        self.dialogs = dialogs or Dialogs()
        self.token = secrets.token_urlsafe(24)


def _str(req, key, default=None):
    v = req.get(key, default)
    if v is None:
        raise ApiError('parametro mancante: %s' % key)
    return str(v)


def _keys(req):
    keys = req.get('keys')
    if not isinstance(keys, list):
        raise ApiError('parametro mancante: keys')
    return [str(k) for k in keys]


def _with_state(app, res):
    out = dict(res or {})
    out['state'] = app.state.payload()
    return out


# --------------------------------------------------------------------- API


def api_init(app, req):
    return {
        'version': __version__,
        'dirs': {'project': paths.PROJECT_ROOT, 'meta': paths.META_DIR,
                 'meta_rel': paths.rel(paths.META_DIR)},
        'dialogs': app.dialogs.kind,
        'classes': {'order': list(CLASS_ORDER), 'colors': CLASS_COLORS,
                    'labels': CLASS_LABELS},
        'setops': SETOPS,
        'state': app.state.payload(),
    }


def api_files(app, req):
    return {'base': paths.rel(paths.META_DIR),
            'files': paths.list_inputs()}


def api_dialog_open(app, req):
    kind = req.get('kind', 'stations')
    if kind == 'list':
        start, title, fkind, multiple = paths.PROJECT_ROOT, \
            'Lista di stazioni', 'list', False
    else:
        start, title, fkind, multiple = paths.META_DIR, \
            'File di stazioni', 'stations', True
    files = app.dialogs.open_files(title, start, fkind, multiple=multiple)
    return {'available': files is not None, 'files': files or []}


def api_dialog_save(app, req):
    kind = req.get('kind', 'xml')
    start = paths.resolve_out(req.get('path') or 'nuovo',
                              {'xml': '.xml', 'pf': '.pf'}.get(kind, '.txt'),
                              force_ext=(kind != 'list'))
    f = app.dialogs.save_file('Salva come', start,
                              'stations' if kind == 'xml' else kind)
    return {'available': f is not None, 'path': f or ''}


def api_load(app, req):
    files = req.get('files')
    if not isinstance(files, list) or not files:
        raise ApiError('nessun file indicato')
    return _with_state(app, app.state.load(
        [paths.resolve(f) for f in files]))


def api_state(app, req):
    return {'state': app.state.payload()}


def api_new(app, req):
    return _with_state(app, app.state.new_empty(req.get('name')))


def api_rename(app, req):
    return _with_state(app, app.state.rename(_str(req, 'id'),
                                             _str(req, 'name')))


def api_close(app, req):
    return _with_state(app, app.state.close(_str(req, 'id')))


def api_delete(app, req):
    return _with_state(app, app.state.delete(_str(req, 'id'), _keys(req)))


def api_copy(app, req):
    return _with_state(app, app.state.copy(
        _str(req, 'src'), _str(req, 'dst'), _keys(req),
        policy=req.get('policy'), move=bool(req.get('move'))))


def api_setop(app, req):
    return _with_state(app, app.state.setop(
        _str(req, 'op'), _str(req, 'a'), _str(req, 'b'),
        name=req.get('name'), policy=req.get('policy')))


def api_new_from(app, req):
    sources = req.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ApiError('nessun catalogo di origine')
    return _with_state(app, app.state.new_from(
        _keys(req), [str(s) for s in sources], name=req.get('name'),
        policy=req.get('policy')))


def api_undo(app, req):
    return _with_state(app, app.state.undo())


def api_redo(app, req):
    return _with_state(app, app.state.redo())


def api_save(app, req):
    return _with_state(app, app.state.save(
        _str(req, 'id'), path=req.get('path') or None,
        overwrite=bool(req.get('overwrite'))))


def api_export(app, req):
    return _with_state(app, app.state.export(
        _str(req, 'id'), _str(req, 'fmt'), _str(req, 'path'),
        overwrite=bool(req.get('overwrite'))))


def api_detail(app, req):
    return app.state.detail(_str(req, 'key'))


def api_read_list(app, req):
    path = paths.resolve(_str(req, 'path'))
    if not op.isfile(path):
        raise ApiError('file non trovato: %s' % paths.rel(path))
    if op.getsize(path) > MAX_LIST:
        raise ApiError('%s è troppo grande per una lista di stazioni'
                       % paths.rel(path))
    with open(path, encoding='utf-8', errors='replace') as f:
        return {'path': paths.rel(path), 'text': f.read()}


def api_log(app, req):
    level = req.get('level', 'info')
    msg = str(req.get('msg', ''))[:4000]
    getattr(logger, level if level in ('info', 'warning', 'error')
            else 'info')('[page] %s', msg)
    return {}


API = {
    'init': api_init,
    'files': api_files,
    'dialog_open': api_dialog_open,
    'dialog_save': api_dialog_save,
    'load': api_load,
    'state': api_state,
    'new': api_new,
    'rename': api_rename,
    'close': api_close,
    'delete': api_delete,
    'copy': api_copy,
    'setop': api_setop,
    'new_from': api_new_from,
    'undo': api_undo,
    'redo': api_redo,
    'save': api_save,
    'export': api_export,
    'detail': api_detail,
    'read_list': api_read_list,
    'log': api_log,
}


# ----------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    server_version = 'csta/' + __version__
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
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

    def _send_static(self, root, rel):
        full = op.realpath(op.join(root, rel))
        root = op.realpath(root)
        if not full.startswith(root + os.sep) or not op.isfile(full):
            self._send(404, b'not found', 'text/plain')
            return
        with open(full, 'rb') as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
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
        elif url.startswith('/static/vendor/'):
            self._send_static(paths.VENDOR_DIR, url[len('/static/vendor/'):])
        elif url.startswith('/static/'):
            self._send_static(paths.STATIC_DIR, url[len('/static/'):])
        elif url == '/favicon.ico':
            self._send(204, b'', 'image/x-icon')
        else:
            self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        app = self.server.app
        url = self.path.split('?', 1)[0]
        if not url.startswith('/api/'):
            self._send_json(404, {'ok': False, 'error': 'not found'})
            return
        if self.headers.get('X-CSTA-Token') != app.token:
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
    th = threading.Thread(target=srv.serve_forever, name='csta-server',
                          daemon=True)
    th.start()
    return srv
