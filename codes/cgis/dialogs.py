'''
Native file dialogs, requested by the viewer through the local server.

* Qt window: QFileDialog, run in the Qt main thread (see window.py).
* Browser mode on macOS: AppleScript ``choose file`` via osascript.
* Otherwise: tkinter in a subprocess (its own main thread).

``open_files`` returns a list of paths ([] when cancelled) and ``save_file``
a path ('' when cancelled); both return None when no dialog is available,
in which case the viewer asks for a typed path.
'''

import json
import os.path as op
import subprocess
import sys

FILTERS = {
    'catalog': ('Catalogues', ('*.pf', '*.yaml', '*.yml', '*.xml', '*.qml',
                               '*.quakeml')),
    'stations': ('Stations', ('*.xml', '*.pf', '*.txt', '*.yaml', '*.yml')),
    'session': ('Sessions', ('*.yaml',)),
    'pdf': ('PDF', ('*.pdf',)),
    'svg': ('SVG', ('*.svg',)),
    'png': ('PNG', ('*.png',)),
    'pf': ('Pyrocko events', ('*.pf',)),
    'yaml': ('YAML', ('*.yaml',)),
    'csv': ('CSV', ('*.csv',)),
}


def qt_filter(kind):
    label, pats = FILTERS.get(kind, ('All files', ('*',)))
    return '%s (%s);;All files (*)' % (label, ' '.join(pats))


class Dialogs:
    kind = 'none'

    def open_files(self, title, start_dir, file_kind, multiple=True):
        return None

    def save_file(self, title, start_path, file_kind):
        return None


def _as_quote(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


class MacDialogs(Dialogs):
    kind = 'osascript'

    def _run(self, lines):
        args = ['osascript']
        for line in lines:
            args += ['-e', line]
        try:
            p = subprocess.run(args, capture_output=True, text=True,
                               timeout=3600)
        except (OSError, subprocess.SubprocessError):
            return None
        if p.returncode != 0:
            # -128: user cancelled
            return ''
        return p.stdout

    def open_files(self, title, start_dir, file_kind, multiple=True):
        loc = ' default location (POSIX file %s)' % _as_quote(start_dir) \
            if start_dir and op.isdir(start_dir) else ''
        mult = ' with multiple selections allowed' if multiple else ''
        lines = [
            'set theFiles to choose file with prompt %s%s%s'
            % (_as_quote(title), loc, mult),
            'if class of theFiles is not list then '
            'set theFiles to {theFiles}',
            'set out to ""',
            'repeat with f in theFiles',
            'set out to out & POSIX path of f & linefeed',
            'end repeat',
            'return out',
        ]
        out = self._run(lines)
        if out is None:
            return None
        return [x for x in out.splitlines() if x.strip()]

    def save_file(self, title, start_path, file_kind):
        d, name = op.split(start_path)
        loc = ' default location (POSIX file %s)' % _as_quote(d) \
            if d and op.isdir(d) else ''
        lines = [
            'set f to choose file name with prompt %s default name %s%s'
            % (_as_quote(title), _as_quote(name), loc),
            'return POSIX path of f',
        ]
        out = self._run(lines)
        if out is None:
            return None
        return out.strip()


_TK_SCRIPT = r'''
import json, sys
try:
    import tkinter
    from tkinter import filedialog
except Exception:
    print(json.dumps({"available": False})); sys.exit(0)
a = json.loads(sys.argv[1])
root = tkinter.Tk(); root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
types = [(a["label"], " ".join(a["patterns"])), ("All files", "*")]
if a["op"] == "open":
    if a["multiple"]:
        r = list(filedialog.askopenfilenames(
            title=a["title"], initialdir=a["dir"], filetypes=types))
    else:
        r = filedialog.askopenfilename(
            title=a["title"], initialdir=a["dir"], filetypes=types)
        r = [r] if r else []
else:
    r = filedialog.asksaveasfilename(
        title=a["title"], initialdir=a["dir"], initialfile=a["name"],
        filetypes=types) or ""
print(json.dumps({"available": True, "result": r}))
'''


class TkDialogs(Dialogs):
    kind = 'tk'

    def _run(self, args):
        try:
            p = subprocess.run(
                [sys.executable, '-c', _TK_SCRIPT, json.dumps(args)],
                capture_output=True, text=True, timeout=3600)
            res = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            return None
        if not res.get('available'):
            return None
        return res['result']

    def open_files(self, title, start_dir, file_kind, multiple=True):
        label, pats = FILTERS.get(file_kind, ('All files', ('*',)))
        return self._run({'op': 'open', 'title': title, 'dir': start_dir,
                          'multiple': multiple, 'label': label,
                          'patterns': list(pats)})

    def save_file(self, title, start_path, file_kind):
        label, pats = FILTERS.get(file_kind, ('All files', ('*',)))
        d, name = op.split(start_path)
        return self._run({'op': 'save', 'title': title, 'dir': d,
                          'name': name, 'multiple': False, 'label': label,
                          'patterns': list(pats)})


def default_dialogs():
    if sys.platform == 'darwin':
        return MacDialogs()
    return TkDialogs()
