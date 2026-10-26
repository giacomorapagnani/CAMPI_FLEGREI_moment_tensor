'''
Sessions saved as YAML (pyrocko.guts) in ``codes/cgis/sessions``.

A session stores the loaded files (paths relative to the project root), the
map view, all settings, the cross-sections and the lasso polygon. The last
state is autosaved to ``_last.yaml`` so that ``python3 cgis -res`` resumes it.
'''

import os
import os.path as op
import re
import time

from pyrocko import guts
from pyrocko.guts import Object, String, Float, Int, List, Dict, Any

from . import paths

guts_prefix = 'cgis'

AUTOSAVE_NAME = '_last'
SESSION_VERSION = 1


class SessionError(Exception):
    pass


class LayerState(Object):
    kind = String.T(help="'catalog' or 'stations'")
    path = String.T()
    options = Dict.T(String.T(), Any.T(), optional=True)


class SectionState(Object):
    label = String.T()
    lat1 = Float.T()
    lon1 = Float.T()
    lat2 = Float.T()
    lon2 = Float.T()
    width_km = Float.T()
    options = Dict.T(String.T(), Any.T(), optional=True)


class ViewState(Object):
    lat = Float.T()
    lon = Float.T()
    zoom = Float.T()
    basemap = String.T(optional=True)


class Session(Object):
    version = Int.T(default=SESSION_VERSION)
    saved = String.T(optional=True)
    layers = List.T(LayerState.T())
    view = ViewState.T(optional=True)
    settings = Dict.T(String.T(), Any.T(), optional=True)
    sections = List.T(SectionState.T())
    lasso = List.T(List.T(Float.T()), optional=True)


_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\- ]{0,100}$')


def check_name(name):
    name = (name or '').strip()
    if name.endswith('.yaml'):
        name = name[:-5]
    if name == AUTOSAVE_NAME:
        return name
    if not _NAME_RE.match(name):
        raise SessionError(
            'nome di sessione non valido %r: usa lettere, cifre, spazi, . _ -'
            % name)
    return name


def session_path(name_or_path, allow_path=False):
    '''
    Path of a session given its name (saved in the sessions folder) or,
    when ``allow_path`` is set (opening a file), an explicit file path.
    '''
    s = str(name_or_path).strip()
    if allow_path and (os.sep in s or s.endswith(('.yaml', '.yml'))):
        p = paths.resolve(s)
        if op.isfile(p):
            return p
    return op.join(paths.SESSIONS_DIR, check_name(s) + '.yaml')


def _clean(obj):
    '''Make JSON data safe for YAML (no NaN/inf, plain types only).'''
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        return obj if obj == obj and abs(obj) != float('inf') else None
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    return str(obj)


def from_state(state):
    '''Build a Session from the JSON state sent by the viewer.'''
    try:
        layers = []
        for la in state.get('layers', []):
            layers.append(LayerState(
                kind=str(la['kind']),
                path=paths.rel(paths.resolve(la['path'])),
                options=_clean(la.get('options') or {})))
        sections = []
        for se in state.get('sections', []):
            sections.append(SectionState(
                label=str(se['label']),
                lat1=float(se['lat1']), lon1=float(se['lon1']),
                lat2=float(se['lat2']), lon2=float(se['lon2']),
                width_km=float(se['width_km']),
                options=_clean(se.get('options') or {})))
        view = None
        v = state.get('view')
        if v:
            view = ViewState(lat=float(v['lat']), lon=float(v['lon']),
                             zoom=float(v['zoom']),
                             basemap=v.get('basemap'))
        lasso = None
        if state.get('lasso'):
            lasso = [[float(p[0]), float(p[1])] for p in state['lasso']]
        return Session(
            saved=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            layers=layers, view=view,
            settings=_clean(state.get('settings') or {}),
            sections=sections, lasso=lasso)
    except (KeyError, TypeError, ValueError) as e:
        raise SessionError('invalid session state: %s' % e)


def to_state(session):
    '''JSON state for the viewer (paths made absolute).'''
    layers = []
    missing = []
    for la in session.layers:
        p = paths.resolve(la.path)
        if not op.exists(p):
            missing.append(la.path)
        layers.append({'kind': la.kind, 'path': p,
                       'options': la.options or {}})
    return {
        'saved': session.saved,
        'layers': layers,
        'missing': missing,
        'view': None if session.view is None else {
            'lat': session.view.lat, 'lon': session.view.lon,
            'zoom': session.view.zoom, 'basemap': session.view.basemap},
        'settings': session.settings or {},
        'sections': [{
            'label': s.label, 'lat1': s.lat1, 'lon1': s.lon1,
            'lat2': s.lat2, 'lon2': s.lon2, 'width_km': s.width_km,
            'options': s.options or {}} for s in session.sections],
        'lasso': session.lasso,
    }


def save(state, name):
    sess = from_state(state)
    fn = session_path(name)
    paths.ensure_dir(op.dirname(fn))
    tmp = fn + '.tmp'
    sess.dump(filename=tmp)
    os.replace(tmp, fn)          # atomic: never leave a half written file
    return fn


def load(name_or_path):
    fn = session_path(name_or_path, allow_path=True)
    if not op.exists(fn):
        raise SessionError('sessione non trovata: %s' % fn)
    try:
        sess = guts.load(filename=fn)
    except Exception as e:
        raise SessionError('impossibile leggere la sessione %s: %s' % (fn, e))
    if not isinstance(sess, Session):
        raise SessionError('%s non è una sessione cgis' % fn)
    state = to_state(sess)
    state['name'] = op.splitext(op.basename(fn))[0]
    state['file'] = fn
    return state


def list_sessions():
    if not op.isdir(paths.SESSIONS_DIR):
        return []
    out = []
    for fn in os.listdir(paths.SESSIONS_DIR):
        if fn.endswith('.yaml'):
            full = op.join(paths.SESSIONS_DIR, fn)
            out.append({'name': fn[:-5],
                        'mtime': op.getmtime(full),
                        'saved': time.strftime(
                            '%Y-%m-%d %H:%M',
                            time.localtime(op.getmtime(full)))})
    out.sort(key=lambda x: -x['mtime'])
    return out


def delete(name):
    fn = session_path(name)
    if op.exists(fn):
        os.remove(fn)
