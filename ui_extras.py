"""Small interface helpers: toasts with Undo, empty-state hints, drag-and-drop, the progress strip and the "What's new" window."""
import os
import re

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

GREEN, AMBER, GREY, RED = "#2e9e5b", "#d9a21b", "#8a8f98", "#C8102E"


def palette_for(light):
    """(background, text, muted text, border) for the current look."""
    return ("#ffffff", "#1c1f24", "#5d6470", "#d4d7dc") if light else ("#24262b", "#eceef0", "#a8a09a", "#3a3d44")


# ---------------------------------------------------------------- toast
class Toast(QFrame):
    """A small message at the bottom of the window that goes away by itself, with an optional action button (Undo, Open folder)."""

    def __init__(self, win, is_light):
        super().__init__(win)
        self.win, self.is_light = win, is_light
        self._action = None
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        lay.setSpacing(12)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(False)
        lay.addWidget(self.lbl)
        self.btn = QPushButton("")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._clicked)
        lay.addWidget(self.btn)
        self.x = QPushButton("✕")
        self.x.setFixedWidth(28)
        self.x.setFlat(True)
        self.x.clicked.connect(self.hide)
        lay.addWidget(self.x)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        win.installEventFilter(self)
        self.hide()

    def _style(self):
        bg, tx, mu, bd = palette_for(self.is_light())
        self.setStyleSheet(
            "#toast{background:%s;border:1px solid %s;border-left:5px solid %s;border-radius:10px;}"
            "#toast QLabel{color:%s;background:transparent;font-size:13px;}"
            "#toast QPushButton{color:%s;background:transparent;border:none;padding:6px 10px;font-weight:700;}"
            "#toast QPushButton:hover{background:rgba(200,16,46,40);border-radius:6px;}" % (bg, bd, RED, tx, RED))
        self.x.setStyleSheet("QPushButton{color:%s;font-weight:400;}" % mu)

    def show_message(self, text, action_text="", action=None, ms=9000):
        self._style()
        self.lbl.setText(text)
        self._action = action
        self.btn.setText(action_text)
        self.btn.setVisible(bool(action_text and action))
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def _clicked(self):
        a, self._action = self._action, None
        self.hide()
        if a:
            a()

    def place(self):
        w = self.win
        self.setMaximumWidth(max(300, w.width() - 60))
        self.adjustSize()
        self.move(QPoint(max(10, (w.width() - self.width()) // 2), w.height() - self.height() - 46))

    def eventFilter(self, o, e):
        if o is self.win and e.type() in (QEvent.Type.Resize, QEvent.Type.Move) and self.isVisible():
            self.place()
        return False


def open_folder_of(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path))))


# ---------------------------------------------------------------- empty state
class EmptyHint(QObject):
    """Shows a friendly 'what to do' text over a table while it has no rows."""

    def __init__(self, table, title, hint, is_light):
        super().__init__(table)
        self.table, self.is_light = table, is_light
        self.lbl = QLabel(table.viewport())
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl.setWordWrap(True)
        self._title, self._hint = title, hint
        table.viewport().installEventFilter(self)
        m = table.model()
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.layoutChanged):
            sig.connect(self.sync)
        self.sync()

    def restyle(self):
        _bg, tx, mu, bd = palette_for(self.is_light())
        self.lbl.setText("<div style='font-size:16px;font-weight:700;color:%s'>%s</div><div style='font-size:12px;color:%s'>%s</div>"
                         % (tx, self._title, mu, self._hint))
        self.lbl.setStyleSheet("background:transparent;border:2px dashed %s;border-radius:14px;padding:18px;" % bd)

    def sync(self, *_a):
        try:
            empty = self.table.rowCount() == 0
        except RuntimeError:                      # the table is already gone (window closing)
            return
        if empty:
            self.restyle()
            self.place()
        self.lbl.setVisible(empty)

    def place(self):
        r = self.table.viewport().rect().adjusted(24, 16, -24, -16)
        r.setTop(r.top() + 28)                         # leave the header line alone
        self.lbl.setGeometry(r)

    def eventFilter(self, o, e):
        try:
            if o is self.table.viewport() and e.type() == QEvent.Type.Resize:
                self.place()
        except RuntimeError:
            pass
        return False


# ---------------------------------------------------------------- drag and drop
class DropFilter(QObject):
    """Lets a widget accept dropped files: handler(list of paths) is called with the ones whose extension is wanted (folders are opened)."""

    def __init__(self, widget, exts, handler):
        super().__init__(widget)
        self.exts, self.handler = tuple(x.lower() for x in exts), handler
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _paths(self, e):
        out = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                out += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith(self.exts)]
            elif p.lower().endswith(self.exts):
                out.append(p)
        return out

    def eventFilter(self, o, e):
        t = e.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove) and e.mimeData().hasUrls() and self._paths(e):
            e.acceptProposedAction()
            return True
        if t == QEvent.Type.Drop and e.mimeData().hasUrls():
            ps = self._paths(e)
            if ps:
                e.acceptProposedAction()
                QTimer.singleShot(0, lambda: self.handler(ps))
                return True
        return False


# ---------------------------------------------------------------- progress strip
class _Step(QLabel):
    def __init__(self, cb):
        super().__init__("")
        self.cb = cb
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setContentsMargins(8, 3, 8, 3)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.cb()


class StepStrip(QWidget):
    """A slim line of steps with a dot each (green done, amber needs a look, grey not started). Click a step to go there."""

    def __init__(self, win, steps, is_light):
        super().__init__()
        self.win, self.steps, self.is_light = win, steps, is_light
        self.items = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)
        for i, (key, label, tab) in enumerate(steps):
            w = _Step(lambda t=tab: win.goto_main_tab(t))
            self.items[key] = (w, label)
            lay.addWidget(w)
            if i < len(steps) - 1:
                a = QLabel("\u203A")
                a.setStyleSheet("color:#8a8f98;background:transparent;")
                lay.addWidget(a)
        lay.addStretch(1)
        self.setFixedHeight(28)

    def update_states(self, states):
        """states: {key: (state, tip)} where state is 'done', 'look' or 'todo'."""
        _bg, tx, mu, _bd = palette_for(self.is_light())
        for key, (w, label) in self.items.items():
            st, tip = states.get(key, ("todo", ""))
            col = {"done": GREEN, "look": AMBER}.get(st, GREY)
            w.setText("<span style='color:%s;font-size:14px'>\u25CF</span>&nbsp;<span style='color:%s;font-size:12px'>%s</span>"
                      % (col, tx if st != "todo" else mu, label))
            w.setToolTip(tip)
            w.setStyleSheet("background:transparent;")


# ---------------------------------------------------------------- what's new
def _vtuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", s))


def notes_since(md_text, last):
    """The bullet entries of RELEASE_NOTES.md whose version (the x.y.z after the title) is newer than `last` (a tuple)."""
    out = []
    for line in md_text.splitlines():
        m = re.match(r"^- \*\*(.*?),\s*(\d+\.\d+\.\d+)\*\*:?\s*(.*)$", line.strip())
        if m and _vtuple(m.group(2)) > last:
            out.append((_vtuple(m.group(2)), m.group(1), m.group(3)))
    return out


def whats_new_dialog(win, items, current):
    d = QDialog(win)
    d.setWindowTitle("What's new in version %s" % ".".join(str(x) for x in current))
    d.resize(680, 560)
    v = QVBoxLayout(d)
    head = QLabel("<div style='font-size:19px;font-weight:700'>What's new</div>"
                  "<div style='color:#8a8f98'>Since the version you used before. Everything is also under File &gt; Release notes.</div>")
    v.addWidget(head)
    tb = QTextBrowser()
    html = ""
    for _ver, title, text in items[:25]:
        html += "<p><b>%s</b> <span style='color:#8a8f98'>(%s)</span><br>%s</p>" % (title, ".".join(str(x) for x in _ver), text)
    tb.setHtml(html or "<p>No new entries.</p>")
    v.addWidget(tb, 1)
    row = QHBoxLayout()
    row.addStretch(1)
    ok = QPushButton("Got it")
    ok.setDefault(True)
    ok.clicked.connect(d.accept)
    row.addWidget(ok)
    v.addLayout(row)
    d.exec()
