'''
Project layout (shared with cgis): station metadata in ``META_DATA``, the
code in ``codes/csta``. Leaflet is served from the cgis vendor folder.
'''

import os
import os.path as op

from cgis.paths import PROJECT_ROOT, META_DIR, rel, ensure_dir  # noqa: F401
from cgis.paths import STATIC_DIR as CGIS_STATIC_DIR

PACKAGE_DIR = op.dirname(op.abspath(__file__))
STATIC_DIR = op.join(PACKAGE_DIR, 'static')
VENDOR_DIR = op.join(CGIS_STATIC_DIR, 'vendor')

XML_EXTENSIONS = ('.xml',)
# read-only inputs: no instrument responses
TEXT_EXTENSIONS = ('.pf', '.txt', '.csv')
EXTENSIONS = XML_EXTENSIONS + TEXT_EXTENSIONS


def resolve(name):
    '''
    Absolute path of a user supplied file name: absolute paths as they are,
    relative ones tried against the current directory, META_DATA and the
    project root (in this order).
    '''
    name = op.expanduser(str(name).strip())
    if op.isabs(name):
        return op.normpath(name)
    for base in (os.getcwd(), META_DIR, PROJECT_ROOT):
        cand = op.normpath(op.join(base, name))
        if op.exists(cand):
            return cand
    return op.normpath(op.join(META_DIR, name))


def resolve_out(name, ext, force_ext=True):
    '''
    Absolute path of an output file. Relative names starting with a project
    folder (e.g. META_DATA/x.xml, BLACKLIST/x.txt) are taken from the project
    root, the others are put in META_DATA. ``ext`` is appended when missing
    (with ``force_ext=False`` only when the name has no extension at all).
    '''
    name = op.expanduser(str(name or '').strip())
    if not name or name.endswith(os.sep):
        raise ValueError('nome del file mancante')
    if not op.isabs(name):
        first = name.split(os.sep, 1)[0]
        base = PROJECT_ROOT if first not in ('', '.', '..') and op.isdir(
            op.join(PROJECT_ROOT, first)) else META_DIR
        name = op.join(base, name)
    name = op.normpath(name)
    cur = op.splitext(name)[1].lower()
    if (force_ext and cur != ext) or not cur:
        name += ext
    return name


def _n_xml(d):
    try:
        return sum(1 for f in os.listdir(d)
                   if f.lower().endswith('.xml') and not f.startswith('.'))
    except OSError:
        return 0


def list_inputs(base=META_DIR, max_depth=4, limit=2000):
    '''
    Station files below ``base`` and folders holding several StationXML
    files (loaded as one catalogue), with paths relative to the project.
    '''
    out = []
    if not op.isdir(base):
        return out
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        if root.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        if root != base:
            n = _n_xml(root)
            if n >= 2:
                out.append({'path': rel(root), 'kind': 'dir', 'n': n,
                            'size': None})
        for fn in sorted(files):
            if fn.startswith('.') or not fn.lower().endswith(EXTENSIONS):
                continue
            full = op.join(root, fn)
            try:
                size = op.getsize(full)
            except OSError:
                size = None
            out.append({'path': rel(full), 'kind': 'file', 'n': None,
                        'size': size})
            if len(out) >= limit:
                return out
    return out
