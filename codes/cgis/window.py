'''
Application window: PyQt5 + QtWebEngine showing the viewer page served by
the local server. Native file dialogs requested by the page (through the
server threads) are executed here, in the Qt main thread.
'''

import logging
import threading

from .dialogs import Dialogs, qt_filter

logger = logging.getLogger('cgis')


def qt_available():
    try:
        from PyQt5 import QtWebEngineWidgets  # noqa: F401
        return True
    except Exception:
        return False


class QtDialogs(Dialogs):
    kind = 'qt'

    def __init__(self):
        self._bridge = None

    def attach(self, bridge):
        self._bridge = bridge

    def _call(self, req):
        if self._bridge is None:
            return None
        if threading.current_thread() is threading.main_thread():
            self._bridge.run(req)
        else:
            req['event'] = threading.Event()
            self._bridge.request.emit(req)
            req['event'].wait()
        return req.get('result')

    def open_files(self, title, start_dir, file_kind, multiple=True):
        return self._call({'op': 'open', 'title': title, 'dir': start_dir,
                           'kind': file_kind, 'multiple': multiple})

    def save_file(self, title, start_path, file_kind):
        return self._call({'op': 'save', 'title': title, 'path': start_path,
                           'kind': file_kind})


def run_window(url, dialogs, title='cgis', confirm_close=None):
    '''
    ``confirm_close``: optional callable returning a question (or None) to
    ask before the window closes, e.g. about unsaved changes.
    '''
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5 import QtWebEngineWidgets  # noqa: F401 (before QApplication)
    from PyQt5.QtWebEngineWidgets import (QWebEngineView, QWebEnginePage,
                                          QWebEngineSettings)

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        [title])
    app.setApplicationName(title)

    class Bridge(QtCore.QObject):
        request = QtCore.pyqtSignal(object)

        def __init__(self, parent):
            QtCore.QObject.__init__(self)
            self._parent = parent
            self.request.connect(self.run, QtCore.Qt.QueuedConnection)

        def run(self, req):
            try:
                if req['op'] == 'open':
                    flt = qt_filter(req['kind'])
                    if req['multiple']:
                        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
                            self._parent, req['title'], req['dir'], flt)
                    else:
                        f, _ = QtWidgets.QFileDialog.getOpenFileName(
                            self._parent, req['title'], req['dir'], flt)
                        files = [f] if f else []
                    req['result'] = list(files)
                else:
                    f, _ = QtWidgets.QFileDialog.getSaveFileName(
                        self._parent, req['title'], req['path'],
                        qt_filter(req['kind']))
                    req['result'] = f or ''
            except Exception as e:
                logger.error('file dialog failed: %s', e)
                req['result'] = None
            finally:
                ev = req.get('event')
                if ev is not None:
                    ev.set()

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, msg, line, source):
            if level >= QWebEnginePage.WarningMessageLevel:
                logger.warning('[js] %s (%s:%d)', msg, source, line)

        def acceptNavigationRequest(self, qurl, nav_type, is_main_frame):
            # external links open in the system browser
            if is_main_frame and qurl.host() not in ('127.0.0.1',
                                                     'localhost'):
                QtGui.QDesktopServices.openUrl(qurl)
                return False
            return QWebEnginePage.acceptNavigationRequest(
                self, qurl, nav_type, is_main_frame)

    class Window(QtWidgets.QMainWindow):
        def closeEvent(self, ev):
            msg = confirm_close() if confirm_close else None
            if msg:
                Box = QtWidgets.QMessageBox
                if Box.question(self, title, msg, Box.Yes | Box.No,
                                Box.No) != Box.Yes:
                    ev.ignore()
                    return
            ev.accept()

    win = Window()
    win.setWindowTitle(title)
    view = QWebEngineView(win)
    page = Page(view)
    view.setPage(page)
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard,
                          True)
    win.setCentralWidget(view)

    bridge = Bridge(win)
    dialogs.attach(bridge)

    screen = app.primaryScreen().availableGeometry()
    win.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))
    win.move(screen.x() + int(screen.width() * 0.05),
             screen.y() + int(screen.height() * 0.03))
    view.load(QtCore.QUrl(url))
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec_()
