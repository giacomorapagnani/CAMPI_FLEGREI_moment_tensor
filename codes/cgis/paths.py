'''
Project layout: the code lives in ``codes/cgis``, catalogues in ``CAT``,
station metadata in ``META_DATA``, figures go to ``PLOTS/cgis`` and sessions
to ``codes/cgis/sessions``. Paths stored in sessions are relative to the
project root so that they survive moving the project.
'''

import os
import os.path as op

PACKAGE_DIR = op.dirname(op.abspath(__file__))
CODES_DIR = op.dirname(PACKAGE_DIR)
PROJECT_ROOT = op.dirname(CODES_DIR)

CAT_DIR = op.join(PROJECT_ROOT, 'CAT')
META_DIR = op.join(PROJECT_ROOT, 'META_DATA')
PLOTS_DIR = op.join(PROJECT_ROOT, 'PLOTS', 'cgis')
SESSIONS_DIR = op.join(PACKAGE_DIR, 'sessions')
STATIC_DIR = op.join(PACKAGE_DIR, 'static')

CATALOG_EXTENSIONS = ('.pf', '.yaml', '.yml', '.xml', '.qml', '.quakeml')
STATION_EXTENSIONS = ('.xml', '.pf', '.txt', '.yaml', '.yml')


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def rel(path):
    '''Path relative to the project root when inside it, else absolute.'''
    path = op.abspath(path)
    try:
        r = op.relpath(path, PROJECT_ROOT)
    except ValueError:      # different drive (Windows)
        return path
    if r.startswith('..'):
        return path
    return r


def resolve(path):
    '''
    Absolute path for user/session supplied paths. Relative paths are tried
    against the current directory first, then against the project root.
    '''
    path = op.expanduser(str(path).strip())
    if op.isabs(path):
        return op.normpath(path)
    cand = op.abspath(path)
    if op.exists(cand):
        return cand
    return op.normpath(op.join(PROJECT_ROOT, path))


def list_files(base, extensions, max_depth=4, limit=2000):
    '''Recursive listing of data files below ``base`` (relative paths).'''
    out = []
    if not op.isdir(base):
        return out
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        if root.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        for fn in sorted(files):
            if fn.startswith('.'):
                continue
            if fn.lower().endswith(extensions):
                out.append(rel(op.join(root, fn)))
                if len(out) >= limit:
                    return out
    return out
