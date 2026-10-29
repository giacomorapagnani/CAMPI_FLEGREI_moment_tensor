'''
Application state: the open catalogues, the undo/redo history and the
operations between catalogues.

Every operation that changes the catalogues pushes a snapshot first.
Snapshots are cheap: catalogues are copied, their entries are shared
(entries are immutable, see inventory.py).

Stations present in two catalogues with different content are conflicts:
the operation then returns them without changing anything, and is repeated
with a policy: 'a' (keep the first / destination version), 'b' (use the
second / source version) or 'merge' (union of the epochs).
'''

import functools
import os.path as op
import threading
from collections import OrderedDict

from . import paths
from .inventory import Catalog, InventoryError, load_catalog, \
    merge_entries, describe_diff, write_xml, write_pf, write_list

PALETTE = ['#1f77b4', '#e4572e', '#2a9d8f', '#b5179e', '#e09f00',
           '#6a4c93', '#43aa8b', '#8d6e63', '#577590', '#d1495b']
MAX_UNDO = 100
POLICIES = ('a', 'b', 'merge')
SETOPS = OrderedDict([
    ('union', 'unione'),
    ('inter', 'intersezione'),
    ('diff', 'differenza'),
    ('sym', 'differenza simmetrica'),
])


def _locked(f):
    @functools.wraps(f)
    def g(self, *args, **kwargs):
        with self.lock:
            return f(self, *args, **kwargs)
    return g


def _unique(keys):
    return list(OrderedDict.fromkeys(str(k) for k in (keys or [])))


def _klist(keys, n=40):
    keys = list(keys)
    s = ', '.join(keys[:n])
    if len(keys) > n:
        s += ' … (+%d)' % (len(keys) - n)
    return s


def _src(cat):
    return '%s (%s)' % (cat.name, paths.rel(cat.path)) if cat.path \
        else cat.name


def _conflicts(triples, la, lb):
    '''[(key, a, b)] -> the stations whose two versions differ.'''
    out = []
    for k, a, b in triples:
        if a.sig != b.sig:
            out.append({'key': k, 'a': a.short(), 'b': b.short(),
                        'diff': describe_diff(a, b, la, lb)})
    return out


def _headers(*cats):
    out = []
    for c in cats:
        out.extend(h for h in c.headers if h not in out)
    return out


def _pick(a, b, policy):
    if a.sig == b.sig or policy == 'a':
        return a
    if policy == 'b':
        return b
    return merge_entries(a, b)


def _out(path, ext, force_ext=True):
    try:
        return paths.resolve_out(path, ext, force_ext=force_ext)
    except ValueError as e:
        raise InventoryError(str(e))


def _check_policy(policy):
    if policy is not None and policy not in POLICIES:
        raise InventoryError('criterio sconosciuto: %s' % policy)


class State:

    def __init__(self):
        self.lock = threading.RLock()
        self.catalogs = OrderedDict()
        self.undo_stack = []
        self.redo_stack = []
        self._counter = 0
        self._rev = 0
        self._ncreated = 0

    # ------------------------------------------------------------ helpers

    def _new_id(self):
        self._counter += 1
        return 'c%d' % self._counter

    def _add(self, cat):
        '''Letters are never reused in a session (A, B, ..., Z, AA, ...).'''
        i = self._ncreated
        self._ncreated += 1
        letter = ''
        n = i
        while True:
            letter = chr(65 + n % 26) + letter
            n = n // 26 - 1
            if n < 0:
                break
        cat.letter = letter
        cat.color = PALETTE[i % len(PALETTE)]
        self.catalogs[cat.id] = cat

    def get(self, cid):
        try:
            return self.catalogs[cid]
        except KeyError:
            raise InventoryError('catalogo sconosciuto: %s' % cid)

    def _push(self, label):
        self.undo_stack.append(
            (label, [c.clone() for c in self.catalogs.values()]))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack = []

    def _touch(self, cat, line):
        self._rev += 1
        cat.rev = self._rev
        cat.log.append(line)

    def _check_writable(self, cat):
        if cat.readonly:
            raise InventoryError(
                '%s è in sola lettura (file senza risposte strumentali)'
                % cat.name)

    def _check_target(self, cat, path):
        '''Never overwrite a file open as another catalogue.'''
        ap = op.abspath(path)
        for c in self.catalogs.values():
            if c is not cat and c.path and (
                    op.abspath(c.path) == ap or
                    (c.kind == 'dir' and ap.startswith(
                        op.abspath(c.path) + op.sep))):
                raise InventoryError(
                    '%s fa parte del catalogo aperto %s · %s: chiudilo '
                    'prima di sovrascriverlo'
                    % (paths.rel(path), c.letter, c.name))
        if op.isdir(path):
            raise InventoryError('%s è una cartella' % paths.rel(path))

    # ------------------------------------------------------------ queries

    @_locked
    def payload(self):
        return {
            'catalogs': [c.payload() for c in self.catalogs.values()],
            'undo': self.undo_stack[-1][0] if self.undo_stack else None,
            'redo': self.redo_stack[-1][0] if self.redo_stack else None,
        }

    @_locked
    def unsaved(self):
        return ['%s · %s' % (c.letter, c.name)
                for c in self.catalogs.values()
                if c.dirty and not c.readonly]

    @_locked
    def detail(self, key):
        versions = []
        for c in self.catalogs.values():
            e = c.entries.get(key)
            if e is not None:
                versions.append((c, e))
        if not versions:
            raise InventoryError('stazione %s non trovata' % key)
        out = []
        c0, e0 = versions[0]
        for c, e in versions:
            d = e.detail()
            d['cat'] = c.id
            d['diff'] = [] if c is c0 or e.sig == e0.sig \
                else describe_diff(e0, e, c0.letter, c.letter)
            out.append(d)
        return {'key': key, 'versions': out}

    # ------------------------------------------------------------- undo

    @_locked
    def undo(self):
        if not self.undo_stack:
            raise InventoryError('niente da annullare')
        label, snap = self.undo_stack.pop()
        self.redo_stack.append(
            (label, [c.clone() for c in self.catalogs.values()]))
        self.catalogs = OrderedDict((c.id, c.clone()) for c in snap)
        return {'msg': 'Annullato: %s' % label}

    @_locked
    def redo(self):
        if not self.redo_stack:
            raise InventoryError('niente da ripetere')
        label, snap = self.redo_stack.pop()
        self.undo_stack.append(
            (label, [c.clone() for c in self.catalogs.values()]))
        self.catalogs = OrderedDict((c.id, c.clone()) for c in snap)
        return {'msg': 'Ripetuto: %s' % label}

    # ------------------------------------------------------- catalogues

    @_locked
    def load(self, files):
        loaded, errors, warnings = [], [], []
        open_paths = {op.abspath(c.path) for c in self.catalogs.values()
                      if c.path}
        for path in files:
            if op.abspath(path) in open_paths:
                errors.append('%s è già aperto' % paths.rel(path))
                continue
            try:
                cat = load_catalog(self._new_id(), path)
            except InventoryError as e:
                errors.append(str(e))
                continue
            open_paths.add(op.abspath(path))
            loaded.append(cat)
            if any(not e.net for e in cat.entries.values()):
                warnings.append(
                    '%s: codice di rete assente, le sue stazioni non '
                    'coincidono con quelle (NET.STA) degli altri cataloghi'
                    % cat.name)
        if loaded:
            self._push('apri %s' % ', '.join(c.name for c in loaded))
            for cat in loaded:
                self._add(cat)
        return {'loaded': [c.id for c in loaded], 'errors': errors,
                'warnings': warnings}

    @_locked
    def new_empty(self, name):
        name = (name or '').strip() or 'nuovo'
        cat = Catalog(self._new_id(), name, 'new')
        self._push('nuovo catalogo %s' % name)
        self._add(cat)
        return {'id': cat.id, 'msg': 'Creato il catalogo vuoto %s · %s'
                % (cat.letter, name)}

    @_locked
    def rename(self, cid, name):
        cat = self.get(cid)
        name = (name or '').strip()
        if not name:
            raise InventoryError('nome vuoto')
        if name == cat.name:
            return {}
        self._push('rinomina %s' % cat.letter)
        cat.name = name
        return {}

    @_locked
    def close(self, cid):
        cat = self.get(cid)
        self._push('chiudi %s · %s' % (cat.letter, cat.name))
        del self.catalogs[cid]
        return {'msg': 'Chiuso %s · %s (Annulla per riaprirlo)'
                % (cat.letter, cat.name)}

    # ------------------------------------------------------- operations

    @_locked
    def delete(self, cid, keys):
        cat = self.get(cid)
        self._check_writable(cat)
        present = [k for k in _unique(keys) if k in cat.entries]
        if not present:
            raise InventoryError('nessuna delle stazioni selezionate è in %s'
                                 % cat.name)
        self._push('elimina %d stazioni da %s' % (len(present), cat.letter))
        for k in present:
            del cat.entries[k]
        self._touch(cat, 'eliminate %d stazioni: %s'
                    % (len(present), _klist(present)))
        return {'msg': 'Eliminate %d stazioni da %s · %s'
                % (len(present), cat.letter, cat.name)}

    @_locked
    def copy(self, src_id, dst_id, keys, policy=None, move=False):
        _check_policy(policy)
        src, dst = self.get(src_id), self.get(dst_id)
        if src is dst:
            raise InventoryError('origine e destinazione coincidono')
        self._check_writable(dst)
        if src.readonly:
            raise InventoryError(
                'le stazioni di %s non hanno risposte strumentali: non '
                'possono entrare in un catalogo StationXML' % src.name)
        present = [k for k in _unique(keys) if k in src.entries]
        if not present:
            raise InventoryError('nessuna delle stazioni selezionate è in %s'
                                 % src.name)

        # a = version already in the destination, b = incoming one
        both = [(k, dst.entries[k], src.entries[k]) for k in present
                if k in dst.entries]
        if policy is None:
            conf = _conflicts(both, dst.letter, src.letter)
            if conf:
                return {'conflicts': conf, 'labels': {
                    'a': {'tag': dst.letter, 'choice': 'quella di %s · %s '
                          '(già presente)' % (dst.letter, dst.name)},
                    'b': {'tag': src.letter, 'choice': 'quella di %s · %s'
                          % (src.letter, src.name)}}}

        plan = OrderedDict()
        added = replaced = merged = kept = 0
        for k in present:
            e = src.entries[k]
            old = dst.entries.get(k)
            if old is None:
                plan[k] = e
                added += 1
            elif old.sig == e.sig:
                kept += 1
            else:
                new = _pick(old, e, policy)
                if new is old:
                    kept += 1
                else:
                    plan[k] = new
                    if policy == 'merge':
                        merged += 1
                    else:
                        replaced += 1

        verb = 'sposta' if move else 'copia'
        if not plan and not move:
            return {'msg': 'Nessuna modifica: le %d stazioni sono già in %s'
                    % (len(present), dst.letter)}

        self._push('%s %d stazioni %s → %s'
                   % (verb, len(present), src.letter, dst.letter))
        for k, e in plan.items():
            dst.entries[k] = e
        if plan:
            dst.headers = _headers(dst, src)
            self._touch(dst, '%s da %s: %s' % (
                'spostate' if move else 'copiate', _src(src),
                _klist(plan)))
        if move:
            for k in present:
                del src.entries[k]
            self._touch(src, 'spostate in %s: %s'
                        % (dst.name, _klist(present)))

        parts = []
        if added:
            parts.append('%d aggiunte' % added)
        if replaced:
            parts.append('%d sostituite' % replaced)
        if merged:
            parts.append('%d unite' % merged)
        if kept:
            parts.append('%d già presenti' % kept)
        return {'msg': '%s %s → %s: %s' % (
            'Spostate' if move else 'Copiate', src.letter, dst.letter,
            ', '.join(parts))}

    @_locked
    def setop(self, op_name, a_id, b_id, name=None, policy=None):
        _check_policy(policy)
        if op_name not in SETOPS:
            raise InventoryError('operazione sconosciuta: %s' % op_name)
        A, B = self.get(a_id), self.get(b_id)
        if A is B:
            raise InventoryError('scegli due cataloghi diversi')
        ka, kb = A.entries, B.entries
        if op_name == 'union':
            keys = list(ka) + [k for k in kb if k not in ka]
        elif op_name == 'inter':
            keys = [k for k in ka if k in kb]
        elif op_name == 'diff':
            keys = [k for k in ka if k not in kb]
        else:
            keys = [k for k in ka if k not in kb] + \
                [k for k in kb if k not in ka]
        if not keys:
            raise InventoryError('il risultato non contiene stazioni')

        both = [(k, ka[k], kb[k]) for k in keys if k in ka and k in kb]
        # a read-only catalogue can only be a "mask": its versions are
        # never used
        if both and A.readonly and B.readonly:
            raise InventoryError('entrambi i cataloghi sono in sola lettura')
        if both and policy is None and not (A.readonly or B.readonly):
            conf = _conflicts(both, A.letter, B.letter)
            if conf:
                return {'conflicts': conf, 'labels': {
                    'a': {'tag': A.letter, 'choice': 'quella di %s · %s'
                          % (A.letter, A.name)},
                    'b': {'tag': B.letter, 'choice': 'quella di %s · %s'
                          % (B.letter, B.name)}}}

        result = OrderedDict()
        bad = []
        for k in keys:
            if k in ka and k in kb:
                if A.readonly:
                    e = kb[k]
                elif B.readonly:
                    e = ka[k]
                else:
                    e = _pick(ka[k], kb[k], policy)
            elif k in ka:
                e = ka[k]
                if A.readonly:
                    bad.append(k)
            else:
                e = kb[k]
                if B.readonly:
                    bad.append(k)
            result[k] = e
        if bad:
            raise InventoryError(
                '%d stazioni del risultato verrebbero da un catalogo in sola '
                'lettura (senza risposte): %s' % (len(bad), _klist(bad, 10)))

        name = (name or '').strip() or '%s_%s_%s' % (
            op_name, A.letter, B.letter)
        cat = Catalog(self._new_id(), name, 'new')
        cat.entries = result
        cat.headers = _headers(*[c for c in (A, B) if not c.readonly])
        self._push('%s %s, %s' % (SETOPS[op_name], A.letter, B.letter))
        self._add(cat)
        self._touch(cat, '%s di %s e %s' % (SETOPS[op_name], _src(A),
                                            _src(B)))
        return {'id': cat.id, 'msg': 'Creato %s · %s: %d stazioni (%s di %s '
                'e %s)' % (cat.letter, name, len(result), SETOPS[op_name],
                           A.letter, B.letter)}

    @_locked
    def new_from(self, keys, source_ids, name=None, policy=None):
        '''
        New catalogue with the selected stations, taken from the sources in
        the given order ('a' = first version found, 'b' = last one).
        '''
        _check_policy(policy)
        sources = [self.get(cid) for cid in source_ids]
        writable = [c for c in sources if not c.readonly]
        if not writable:
            raise InventoryError('nessun catalogo StationXML tra le origini')

        versions = OrderedDict()
        ignored = []
        for k in _unique(keys):
            vs = [(c, c.entries[k]) for c in writable if k in c.entries]
            if vs:
                versions[k] = vs
            elif any(k in c.entries for c in sources):
                ignored.append(k)
        if not versions:
            raise InventoryError('nessuna delle stazioni selezionate è nei '
                                 'cataloghi StationXML di origine')

        def other(vs):
            '''The last version that differs from the first one.'''
            diff = [e for _, e in vs[1:] if e.sig != vs[0][1].sig]
            return diff[-1] if diff else vs[0][1]

        if policy is None:
            triples = [(k, vs[0][1], other(vs)) for k, vs in versions.items()]
            conf = _conflicts(triples, 'primo', 'altro')
            if conf:
                order = ', '.join(c.letter for c in writable)
                return {'conflicts': conf, 'labels': {
                    'a': {'tag': 'primo', 'choice': 'quella del primo catalogo '
                          'che la contiene (ordine: %s)' % order},
                    'b': {'tag': 'altro', 'choice': 'l\'altra versione (del '
                          'catalogo più in basso con contenuto diverso)'}}}

        result = OrderedDict()
        for k, vs in versions.items():
            if policy == 'b':
                result[k] = other(vs)
            elif policy == 'merge':
                e = vs[0][1]
                for _, x in vs[1:]:
                    if x.sig != e.sig:
                        e = merge_entries(e, x)
                result[k] = e
            else:
                result[k] = vs[0][1]

        name = (name or '').strip() or 'selezione'
        cat = Catalog(self._new_id(), name, 'new')
        cat.entries = result
        cat.headers = _headers(*writable)
        self._push('nuovo catalogo dalla selezione')
        self._add(cat)
        self._touch(cat, 'selezione da %s: %s' % (
            ', '.join(_src(c) for c in writable), _klist(result)))
        msg = 'Creato %s · %s con %d stazioni' % (cat.letter, name,
                                                  len(result))
        if ignored:
            msg += ' (%d ignorate: solo in cataloghi in sola lettura)' \
                % len(ignored)
        return {'id': cat.id, 'msg': msg}

    # ----------------------------------------------------------- output

    def _mark_saved(self, cat, path):
        name = op.basename(path)
        cat.path, cat.kind, cat.name = path, 'xml', name
        cat.saved_rev = cat.rev
        # the file identity is not part of the undo history
        for _, snap in self.undo_stack + self.redo_stack:
            for c in snap:
                if c.id == cat.id:
                    c.path, c.kind, c.name = path, 'xml', name
                    c.saved_rev = cat.rev

    @_locked
    def save(self, cid, path=None, overwrite=False):
        cat = self.get(cid)
        if cat.readonly:
            raise InventoryError(
                '%s non ha risposte strumentali: non può essere salvato '
                'come StationXML (usa Esporta .pf)' % cat.name)
        if not cat.entries:
            raise InventoryError('%s è vuoto' % cat.name)
        if path is None:
            if cat.kind != 'xml' or not cat.path:
                return {'need_path': True}
            path = cat.path
        else:
            path = _out(path, '.xml')
            if op.exists(path) and not overwrite:
                return {'exists': True, 'path': paths.rel(path)}
        self._check_target(cat, path)
        write_xml(cat, path)
        self._mark_saved(cat, path)
        return {'msg': 'Salvato %s (%d stazioni)' % (paths.rel(path),
                                                     len(cat.entries)),
                'path': paths.rel(path)}

    @_locked
    def export(self, cid, fmt, path, overwrite=False):
        cat = self.get(cid)
        if fmt not in ('pf', 'list'):
            raise InventoryError('formato sconosciuto: %s' % fmt)
        if not cat.entries:
            raise InventoryError('%s è vuoto' % cat.name)
        path = _out(path, '.pf' if fmt == 'pf' else '.txt',
                    force_ext=(fmt == 'pf'))
        if op.exists(path) and not overwrite:
            return {'exists': True, 'path': paths.rel(path)}
        self._check_target(cat, path)
        if fmt == 'pf':
            write_pf(cat, path)
        else:
            write_list(cat, path)
        return {'msg': 'Esportato %s (%d stazioni)' % (paths.rel(path),
                                                       len(cat.entries)),
                'path': paths.rel(path)}
