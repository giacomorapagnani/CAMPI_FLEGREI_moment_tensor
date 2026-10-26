'''
Command line entry point: parse arguments, start the local server and open
the viewer (Qt window, or the web browser as fallback).
'''

import argparse
import logging
import os.path as op
import signal
import sys
import time
import webbrowser

from . import __version__, paths, session
from .dialogs import Dialogs, default_dialogs
from .server import AppState, start_server

logger = logging.getLogger('cgis')


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog='cgis',
        description='Interactive viewer for seismic catalogues, focal '
                    'mechanisms and stations.')
    p.add_argument('-res', '--resume', nargs='?', const=session.AUTOSAVE_NAME,
                   metavar='SESSION',
                   help='resume a session saved in codes/cgis/sessions '
                        '(name or path); without a name the last session')
    p.add_argument('-c', '--catalog', action='append', default=[],
                   metavar='FILE', help='catalogue to load (repeatable)')
    p.add_argument('-s', '--stations', action='append', default=[],
                   metavar='FILE', help='station file to load (repeatable)')
    p.add_argument('--browser', action='store_true',
                   help='open in the web browser instead of the Qt window')
    p.add_argument('--no-open', action='store_true',
                   help='only run the server (print its address)')
    p.add_argument('--no-dialogs', action='store_true',
                   help='no native file dialogs (paths are typed in the '
                        'page)')
    p.add_argument('--port', type=int, default=0,
                   help='server port (default: a free port)')
    p.add_argument('--list', action='store_true',
                   help='list the saved sessions and exit')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('--version', action='version', version=__version__)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='cgis: %(message)s')
    for name in ('pyrocko', 'matplotlib', 'PIL'):
        logging.getLogger(name).setLevel(logging.WARNING)

    if args.list:
        sessions = session.list_sessions()
        if not sessions:
            print('no saved sessions in %s' % paths.SESSIONS_DIR)
        for s in sessions:
            print('%-30s %s' % (s['name'], s['saved']))
        return 0

    startup = {'catalogs': [], 'stations': [], 'session': None}
    if args.resume:
        try:
            startup['session'] = session.load(args.resume)
        except session.SessionError as e:
            print('cgis: %s' % e, file=sys.stderr)
            avail = [s['name'] for s in session.list_sessions()]
            if avail:
                print('available sessions: %s' % ', '.join(avail),
                      file=sys.stderr)
            return 1
        logger.info('resuming session %s', startup['session']['file'])

    for kind, files in (('catalogs', args.catalog),
                        ('stations', args.stations)):
        for fn in files:
            path = paths.resolve(fn)
            if not op.isfile(path):
                print('cgis: file not found: %s' % fn, file=sys.stderr)
                return 1
            startup[kind].append(path)

    use_qt = not (args.browser or args.no_open)
    if use_qt:
        from .window import qt_available, QtDialogs
        if not qt_available():
            logger.warning('PyQt5 QtWebEngine not available: '
                           'using the web browser')
            use_qt = False

    if args.no_dialogs:
        dialogs = Dialogs()
    else:
        dialogs = QtDialogs() if use_qt else default_dialogs()
    paths.ensure_dir(paths.SESSIONS_DIR)

    app = AppState(dialogs=dialogs, startup=startup)
    srv = start_server(app, port=args.port)
    url = srv.url
    logger.info('viewer at %s', url)

    try:
        if use_qt:
            from .window import run_window
            return run_window(url, dialogs)

        if not args.no_open:
            webbrowser.open(url)
        print('cgis running at %s - press Ctrl+C to quit' % url)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
    finally:
        srv.shutdown()
