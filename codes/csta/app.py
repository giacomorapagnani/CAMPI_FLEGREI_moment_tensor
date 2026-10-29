'''
Command line entry point: load the files given on the command line, start
the local server and open the editor (Qt window, or the web browser as
fallback).
'''

import argparse
import logging
import os.path as op
import signal
import sys
import time
import webbrowser

from cgis.dialogs import Dialogs, default_dialogs

from . import __version__, paths
from .server import AppState, start_server
from .state import State

logger = logging.getLogger('csta')


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog='csta',
        description='Editor of station catalogues (StationXML): view, '
                    'compare, select, copy/move/delete stations and build '
                    'new catalogues.')
    p.add_argument('files', nargs='*', metavar='FILE',
                   help='StationXML files (or folders of StationXML files, '
                        'or read-only .pf/.txt station lists) to open; '
                        'names are also looked up in META_DATA')
    p.add_argument('--browser', action='store_true',
                   help='open in the web browser instead of the Qt window')
    p.add_argument('--no-open', action='store_true',
                   help='only run the server (print its address)')
    p.add_argument('--no-dialogs', action='store_true',
                   help='no native file dialogs (paths are typed in the '
                        'page)')
    p.add_argument('--port', type=int, default=0,
                   help='server port (default: a free port)')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('--version', action='version', version=__version__)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='csta: %(message)s')
    for name in ('pyrocko', 'matplotlib', 'PIL'):
        logging.getLogger(name).setLevel(logging.WARNING)

    state = State()
    files = []
    for fn in args.files:
        path = paths.resolve(fn)
        if not op.exists(path):
            print('csta: file non trovato: %s (cercato anche in %s)'
                  % (fn, paths.rel(paths.META_DIR)), file=sys.stderr)
            return 1
        files.append(path)
    if files:
        logger.info('lettura di %d file…', len(files))
        res = state.load(files)
        for msg in res['errors'] + res['warnings']:
            logger.warning(msg)
        # opening the start files is not an undoable operation
        state.undo_stack = []

    use_qt = not (args.browser or args.no_open)
    if use_qt:
        from cgis.window import qt_available, QtDialogs
        if not qt_available():
            logger.warning('PyQt5 QtWebEngine not available: '
                           'using the web browser')
            use_qt = False

    if args.no_dialogs:
        dialogs = Dialogs()
    else:
        dialogs = QtDialogs() if use_qt else default_dialogs()

    app = AppState(state=state, dialogs=dialogs)
    srv = start_server(app, port=args.port)
    url = srv.url
    logger.info('editor at %s', url)

    def confirm_close():
        unsaved = state.unsaved()
        if unsaved:
            return ('Modifiche non salvate in:\n\n%s\n\nChiudere csta '
                    'comunque?' % '\n'.join(unsaved))
        return None

    try:
        if use_qt:
            from cgis.window import run_window
            return run_window(url, dialogs, title='csta',
                              confirm_close=confirm_close)

        if not args.no_open:
            webbrowser.open(url)
        print('csta running at %s - press Ctrl+C to quit' % url)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        unsaved = state.unsaved()
        if unsaved:
            logger.warning('modifiche non salvate perse in: %s',
                           ', '.join(unsaved))
        return 0
    finally:
        srv.shutdown()
