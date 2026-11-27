"""Small interface helpers: toasts with Undo, empty-state hints, drag-and-drop, the progress strip and the "What's new" window."""
import os
import re

import math
import sys

from PySide6.QtCore import QElapsedTimer, QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, QSize, QTimer, Qt, QUrl, QVariantAnimation
from PySide6.QtGui import QImage, QPixmap, QTransform, QBrush, QColor, QDesktopServices, QIcon, QCursor, QPalette, QPainter, QPen, QRadialGradient, QPainterPath, QLinearGradient, QFont
from PySide6.QtWidgets import (QAbstractButton, QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QTabWidget, QToolTip, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

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
        was = self.isVisible()
        self.show()
        self.raise_()
        self.timer.start(ms)
        if not was:                                                 # slides in from the right edge and fades up
            try:
                end = self.pos()
                an = QVariantAnimation(self)
                an.setStartValue(0.0)
                an.setEndValue(1.0)
                an.setDuration(260)
                an.setEasingCurve(QEasingCurve.Type.OutCubic)
                an.valueChanged.connect(lambda v, e=end: self.move(QPoint(e.x() + int(60 * (1.0 - float(v))), e.y())))
                self._slide = an
                an.start()
            except Exception:
                pass

    def _clicked(self):
        a, self._action = self._action, None
        self.hide()
        if a:
            a()

    def place(self):
        w = self.win
        self.setMaximumWidth(max(300, w.width() - 60))
        self.adjustSize()
        self.move(QPoint(max(10, w.width() - self.width() - 24), w.height() - self.height() - 46))

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


# ---------------------------------------------------------------- command search (Ctrl+K)
class CommandPalette(QDialog):
    """Type a few letters, press Enter: jump to a tab or run a command from any menu."""

    def __init__(self, win, commands, is_light):
        super().__init__(win, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem
        self.win, self.commands = win, commands
        self._Item = QListWidgetItem
        bg, tx, mu, bd = palette_for(is_light())
        self.setObjectName("cmdPalette")
        self.setStyleSheet(
            "#cmdPalette{background:%s;border:1px solid %s;border-radius:12px;}"
            "QLineEdit{background:transparent;border:none;border-bottom:1px solid %s;color:%s;font-size:16px;padding:10px 14px;}"
            "QListWidget{background:transparent;border:none;color:%s;font-size:13px;outline:0;}"
            "QListWidget::item{padding:7px 14px;}"
            "QListWidget::item:selected{background:rgba(200,16,46,60);color:%s;}" % (bg, bd, bd, tx, tx, tx))
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type what you want to do: send, IFC, export, register, dark mode ...")
        self.edit.textChanged.connect(self._filter)
        v.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        v.addWidget(self.list)
        self.hint = QLabel("Enter to run  ·  Up / Down to choose  ·  Esc to close")
        self.hint.setStyleSheet("color:%s;font-size:11px;padding:0 14px;" % mu)
        v.addWidget(self.hint)
        self.resize(min(640, max(420, win.width() - 80)), 420)
        self.edit.installEventFilter(self)
        self._filter("")

    def showEvent(self, e):
        w = self.win
        self.move(w.x() + (w.width() - self.width()) // 2, w.y() + 90)
        self.edit.setFocus()
        super().showEvent(e)

    def _filter(self, text):
        words = [x for x in text.lower().split() if x]
        scored = []
        for label, fn, sc in self.commands:
            low = label.lower()
            if all(w in low for w in words):
                pos = min((low.find(w) for w in words), default=0)
                scored.append((pos, len(label), label, fn, sc))
        scored.sort(key=lambda t: (t[0], t[1]))
        self.list.clear()
        for _p, _l, label, fn, sc in scored[:60]:
            it = self._Item(label + (("      " + sc) if sc else ""))
            it.setData(Qt.ItemDataRole.UserRole, fn)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, it):
        fn = it.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if fn:
            QTimer.singleShot(60, fn)

    def eventFilter(self, o, e):
        if o is self.edit and e.type() == QEvent.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._run(it)
                return True
        return False


# ---------------------------------------------------------------- tables: remembered column widths, row count, right-click menu
def _cell_text(table, r, c):
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QDoubleSpinBox, QSpinBox
    w = table.cellWidget(r, c)
    if w is not None:
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, (QDoubleSpinBox, QSpinBox)):
            return w.text()
        if isinstance(w, QAbstractButton):
            return w.text() or ("yes" if w.isChecked() else "")
        inner = w.findChild(QAbstractButton)
        if inner is not None:
            return inner.text() or ("yes" if inner.isChecked() else "")
    it = table.item(r, c)
    return it.text() if it is not None else ""


class _HeaderRelease(QObject):
    def __init__(self, header, cb):
        super().__init__(header)
        self.cb = cb
        header.viewport().installEventFilter(self)

    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.MouseButtonRelease:
            QTimer.singleShot(0, self.cb)
        return False


def remember_columns(table, key, store, save):
    """Column widths you set by dragging are kept (in `store`, a dict) and put back next time."""
    from PySide6.QtWidgets import QHeaderView
    hd = table.horizontalHeader()
    saved = store.get(key)
    if isinstance(saved, list) and len(saved) == table.columnCount():
        for c, wd in enumerate(saved):
            try:
                if hd.sectionResizeMode(c) == QHeaderView.ResizeMode.Interactive and int(wd) > 12:
                    table.setColumnWidth(c, int(wd))
            except Exception:
                pass

    def grab():
        try:
            store[key] = [table.columnWidth(c) for c in range(table.columnCount())]
            save()
        except RuntimeError:
            pass
    _HeaderRelease(hd, grab)


def count_label(table, noun="rows"):
    """A small 'N rows' label that follows the table."""
    lb = QLabel("")
    lb.setStyleSheet("color:#8a8f98;padding:0 8px;")

    def sync(*_a):
        try:
            n = table.rowCount() - sum(1 for r in range(table.rowCount()) if table.isRowHidden(r))
            lb.setText("%d %s" % (n, noun if n != 1 else noun.rstrip("s")))
        except RuntimeError:
            pass
    m = table.model()
    for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.layoutChanged):
        sig.connect(sync)
    sync()
    return lb


def table_menu(table, is_light, extras=None):
    """Right-click menu on a table: copy the selected cells, select all, plus the actions in extras [(label, fn)]."""
    from PySide6.QtWidgets import QApplication, QMenu

    def show(pos):
        m = QMenu(table)
        rows = sorted({i.row() for i in table.selectedIndexes()})
        a = m.addAction("Copy the selected rows" if len(rows) != 1 else "Copy the selected row")
        a.setEnabled(bool(rows))

        def copy():
            lines = ["\t".join(_cell_text(table, r, c) for c in range(table.columnCount())) for r in rows]
            QApplication.clipboard().setText("\n".join(lines))
        a.triggered.connect(copy)
        m.addAction("Select all", table.selectAll)
        for label, fn in (extras or []):
            if label == "-":
                m.addSeparator()
                continue
            x = m.addAction(label)
            x.setEnabled(bool(rows) or not label.lower().startswith(("remove selected", "open", "show")))
            x.triggered.connect(lambda _c=False, f=fn: f())
        m.exec(table.viewport().mapToGlobal(pos))
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show)


# ---------------------------------------------------------------- link between a register / costing and the open project
class LinkBar(QWidget):
    """One line under the Register: / Costing: list that says whether the open project is linked to it, with a button to link or unlink.
    `owner` has: host (main window), what ("register" or "costing"), linked, link_ok."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl, 1)
        self.btn = QPushButton("")
        self.btn.clicked.connect(self._click)
        lay.addWidget(self.btn)
        self.refresh()

    def project_name(self):
        h = self.owner.host
        f = getattr(h, "current_file", None)
        if f:
            return os.path.splitext(os.path.basename(f))[0]
        return str((getattr(h, "rd", {}) or {}).get("project", "") or "").strip()

    def refresh(self):
        o, p = self.owner, self.project_name()
        what = o.what
        if not p:
            self.lbl.setText("Working on its own: no project is open.")
            self.lbl.setStyleSheet("color:gray;")
            self.btn.hide()
        elif o.linked:
            self.lbl.setText("Linked to project <b>%s</b>. Opening that project brings this %s back." % (p, what))
            self.lbl.setStyleSheet("color:%s;" % GREEN)
            self.btn.setText("Unlink")
            self.btn.show()
        elif o.link_ok:
            self.lbl.setText("Not linked to project <b>%s</b> yet. Saving the project links it, or press Link now." % p)
            self.lbl.setStyleSheet("color:%s;" % AMBER)
            self.btn.setText("Link now")
            self.btn.show()
        else:
            self.lbl.setText("Not linked to project <b>%s</b>: this %s stays separate and the project keeps no copy." % (p, what))
            self.lbl.setStyleSheet("color:gray;")
            self.btn.setText("Link to this project")
            self.btn.show()

    def _click(self):
        o = self.owner
        if o.linked:
            o.linked, o.link_ok = False, False
        else:
            o.linked, o.link_ok = True, True
        try:
            o.host._mark_dirty()
        except Exception:
            pass
        self.refresh()


# ---------------------------------------------------------------- guided steps (a step bar on top, Back / Next at the bottom)
from PySide6.QtCore import Signal as _Signal


STEP_HUES = ["#5b9be6", "#36b3a6", "#e2a93f", "#a587e0", "#d9628f"]
_STEP_ICONS = (("stand", "land"), ("house", "building"), ("connection", "pin"), ("result", "results"), ("room", "room"), ("total", "calc"), ("report", "pdf"), ("rule", "clipboard"),
               ("review", "eye"), ("application", "edit"), ("checklist", "check_circle"), ("pack", "folder"), ("who", "user"), ("drawing", "layers"), ("send", "mail"), ("building", "building"))


def _step_icon(name, k):
    n = name.lower()
    for key, ico in _STEP_ICONS:
        if key in n:
            return ico
    return ("land", "layers", "results", "folder")[k % 4]


class _StepLine(QWidget):
    """a thin line under the steps that fills as you go through them, in the open tool's colour"""
    def __init__(self, bar):
        super().__init__()
        self.bar, self.v = bar, 0.0
        self.setFixedHeight(4)
        self._an = QVariantAnimation(self)
        self._an.setDuration(320)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(lambda v: (setattr(self, "v", float(v)), self.update()))

    def to(self, frac):
        self._an.stop()
        self._an.setStartValue(self.v)
        self._an.setEndValue(float(frac))
        self._an.start()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        track = QColor(128, 128, 128, 45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 2, 2)
        c = QColor(ACCENT_BASE[0] or "#d8132b")
        p.setBrush(c)
        p.drawRoundedRect(0, 0, int(r.width() * self.v), r.height(), 2, 2)
        p.end()


class StepBar(QObject):
    """The same guided look in every tool: numbered step buttons, a one-line hint for the step, and Back / Next buttons.
    `top` goes above the content, `bottom` below it. Connect `changed(int)` to show the step."""
    changed = _Signal(int)

    def __init__(self, names, hints=None, parent=None):
        super().__init__(parent)
        from flow_layout import FlowLayout
        self.names, self.hints, self.i = list(names), list(hints or []), 0
        self.top = QWidget()
        tv = QVBoxLayout(self.top)
        tv.setContentsMargins(0, 0, 0, 4)
        tv.setSpacing(4)
        row = QWidget()
        fl = FlowLayout(row, 6, 6)
        self.btns = []
        for k, t in enumerate(self.names):
            b = QPushButton("%d   %s" % (k + 1, t))
            b.setCheckable(True)
            b.setMinimumHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hue = STEP_HUES[k % len(STEP_HUES)]
            dk = QColor(hue).darker(150).name()
            b.setStyleSheet("QPushButton:checked{background:%s;color:#ffffff;font-weight:700;border:1px solid %s;}" % (dk, hue))
            try:                                                # each step has its own icon and its own muted colour
                mod = sys.modules.get("mot_xa_energy") or sys.modules.get("__main__")
                ic_ = QIcon()
                ic_.addPixmap(mod.icon_pixmap(_step_icon(t, k), hue, 18), QIcon.Mode.Normal, QIcon.State.Off)
                ic_.addPixmap(mod.icon_pixmap(_step_icon(t, k), "#ffffff", 18), QIcon.Mode.Normal, QIcon.State.On)      # white on the chosen step
                b.setIcon(ic_)
                b.setIconSize(QSize(18, 18))
            except Exception:
                pass
            b.clicked.connect(lambda _=False, k=k: self.go(k))
            fl.addWidget(b)
            self.btns.append(b)
        tv.addWidget(row)
        self.prog = _StepLine(self)
        tv.addWidget(self.prog)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")
        tv.addWidget(self.hint)
        self.bottom = QWidget()
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        self.back = QPushButton("‹  Back")
        self.back.setMinimumHeight(34)
        self.back.clicked.connect(lambda: self.go(self.i - 1))
        self.next = QPushButton("Next  ›")
        self.next.setMinimumHeight(34)
        self.next.setStyleSheet("font-weight:700; padding: 0 24px;")
        self.next.clicked.connect(lambda: self.go(self.i + 1))
        bl.addWidget(self.back)
        bl.addStretch(1)
        bl.addWidget(self.next)
        self.go(0, emit=True)

    def go(self, i, emit=True):
        i = max(0, min(int(i), len(self.names) - 1))
        self.i = i
        for k, b in enumerate(self.btns):
            b.setChecked(k == i)
        self.back.setVisible(i > 0)
        self.next.setVisible(i < len(self.names) - 1)
        if i < len(self.names) - 1:
            self.next.setText("Next: %s  ›" % self.names[i + 1].lower())
        self.hint.setText(self.hints[i] if i < len(self.hints) else "")
        self.hint.setVisible(bool(self.hint.text()))
        self.prog.to((i + 1.0) / max(1, len(self.names)))
        if ACCENT_BASE[0]:                                             # the chosen step wears the open tool's colour
            c_ = QColor(ACCENT_BASE[0])
            for k_, b_ in enumerate(self.btns):
                b_.setStyleSheet("QPushButton:checked{background:%s;color:#ffffff;font-weight:700;border:1px solid %s;}" % (c_.darker(150).name(), c_.name()))
        if emit:
            self.changed.emit(i)


class BoxSteps(StepBar):
    """A long page made of framed boxes, shown one box at a time. `boxes` are the group boxes in order."""

    def __init__(self, boxes, names, hints=None, parent=None):
        self.boxes = list(boxes)
        super().__init__(names, hints, parent)
        self.changed.connect(self._show)
        self._show(0)

    def _show(self, i):
        for k, b in enumerate(self.boxes):
            b.setVisible(k == i)
        from PySide6.QtWidgets import QScrollArea
        p = self.boxes[0].parentWidget() if self.boxes else None
        while p is not None and not isinstance(p, QScrollArea):
            p = p.parentWidget()
        if p is not None:
            p.verticalScrollBar().setValue(0)

    def reveal(self, w):
        """Show the step that holds widget w (used by the ribbon's Sections menu). True when it was one of ours."""
        while w is not None:
            if w in self.boxes:
                self.go(self.boxes.index(w))
                return True
            w = w.parentWidget()
        return False


def icon_group(title):
    """A group box with a small icon in its title when the main module provides IconGroupBox (else a plain one)."""
    import sys
    from PySide6.QtWidgets import QGroupBox
    for n in ("__main__", "mot_xa_energy"):
        cls = getattr(sys.modules.get(n), "IconGroupBox", None)
        if cls is not None:
            return cls(title)
    return QGroupBox(title)


class WelcomeTour(QDialog):
    """A short first-run tour: what the four squares are, how the step bars work, and the keyboard shortcuts."""
    PAGES = [
        ("Welcome", "This program has four squares on the home screen: Drawing register, Detail tool, Costing and SANS "
                    "(Light & ventilation, Energy XA and Coverage & FAR). Click a square to open that tool. The left bar then shows "
                    "only that tool, and Home takes you back."),
        ("Work one step at a time", "Each tool has numbered step buttons along the top, with a short hint under them. Do step 1, "
                                    "press Next, and carry on. You can click any step to jump to it. Less common options are under 'More options'."),
        ("Everything is saved for you", "The drawing register and the costing save themselves as you work. The line at the bottom "
                                        "shows what is open and whether it is saved. 'Switch tool' in the left bar moves between tools."),
        ("Keyboard shortcuts", "Alt+Right / Alt+Left: next / previous step.\nF5: run the check.\nCtrl+S: save.   Ctrl+K: search commands.\n"
                               "Ctrl+H: back to the home screen.   F1: release notes.\nYou can reopen this tour from File > Quick tour."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick tour")
        self.setMinimumSize(520, 300)
        v = QVBoxLayout(self)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:20px; font-weight:700;")
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setStyleSheet("font-size:14px;")
        self.count = QLabel("")
        self.count.setStyleSheet("color:gray;")
        v.addWidget(self.title)
        v.addWidget(self.body, 1)
        v.addWidget(self.count)
        h = QHBoxLayout()
        self.skip = QPushButton("Skip")
        self.back = QPushButton("‹  Back")
        self.next = QPushButton("Next  ›")
        self.next.setDefault(True)
        h.addWidget(self.skip)
        h.addStretch(1)
        h.addWidget(self.back)
        h.addWidget(self.next)
        v.addLayout(h)
        self.i = 0
        self.skip.clicked.connect(self.accept)
        self.back.clicked.connect(lambda: self._go(self.i - 1))
        self.next.clicked.connect(lambda: self.accept() if self.i >= len(self.PAGES) - 1 else self._go(self.i + 1))
        self._go(0)

    def _go(self, i):
        self.i = max(0, min(i, len(self.PAGES) - 1))
        t, b = self.PAGES[self.i]
        self.title.setText(t)
        self.body.setText(b)
        self.count.setText("%d of %d" % (self.i + 1, len(self.PAGES)))
        self.back.setVisible(self.i > 0)
        self.next.setText("Done" if self.i == len(self.PAGES) - 1 else "Next  ›")
        self.skip.setVisible(self.i < len(self.PAGES) - 1)


# ---------------------------------------------------------------- icon motion
ACCENT = ["#ff4056"]
ACCENT_BASE = [None]             # the open tool's own colour (None on the start screen and in the SANS tools)            # the colour of the tool that is open: icons take it on when pointed at


class AnimIcon(QLabel):
    """A big icon that comes alive: on hover it lifts, grows, wobbles once and glows; on a press it squeezes and pops back with a ring."""

    def __init__(self, pixmap, accent="#ff4056", box=104, parent=None):
        super().__init__(parent)
        self._pm = pixmap
        self._accent = QColor(accent)
        self._h = 0.0                                            # hover 0..1
        self._p = 0.0                                            # press 0..1
        self._w = 1.0                                            # wobble 0..1 (1 = at rest)
        self._r = 1.0                                            # ring 0..1 (1 = gone)
        self.setFixedSize(box, box)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._anims = {}

    def enable_spin(self, offset=0.0, period=5.5):
        """turn the icon on a vertical axis as a thin solid: the face, a dark edge made of stacked copies, and the back face.
        Drawn live from the clock (not from ready-made pictures), so the turn is as smooth as the screen allows."""
        self._spin_on = True
        self._spin_off = float(offset)
        self._spin_period = float(period)
        self._spin_t = 0.0
        pm = self._pm
        try:
            from PySide6.QtGui import QGuiApplication
            sdpr = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio()))
        except Exception:
            sdpr = 2.0
        lw = pm.width() / max(1.0, pm.devicePixelRatio())
        want = int(round(lw * sdpr * 1.5))                          # one clean downsize to just above the screen's own pixels: turning then never skips pixels, so no stepping
        if pm.width() != want:
            pm = pm.scaled(want, want, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(want / lw)
            self._pm = pm
        dpr = max(1.0, pm.devicePixelRatio())
        self._dpr = dpr
        self._sdpr = sdpr
        side = QPixmap(pm.width(), pm.height())                            # the edge has the same sharpness as the face, so nothing looks stepped
        side.setDevicePixelRatio(dpr)
        side.fill(Qt.GlobalColor.transparent)
        q = QPainter(side)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        q.drawPixmap(0, 0, pm)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        q.fillRect(side.rect(), QColor(self._accent).lighter(135))
        q.end()
        self._side = side
        self._side_rect = QRectF(side.rect())
        pw, ph = pm.width(), pm.height()                      # one picture holding the face and the dark edge side by side: all layers go out in one call
        atl = QPixmap(pw * 2, ph)
        atl.fill(Qt.GlobalColor.transparent)
        q2 = QPainter(atl)
        q2.drawPixmap(0, 0, pm)
        q2.drawPixmap(QRectF(pw, 0, pw, ph), side, QRectF(side.rect()))
        q2.end()
        self._atlas = atl
        self._aw, self._ah = pw, ph
        _SPINNERS.append(self)
        _spin_clock()

    def _run(self, name, a, b, ms, curve):
        old = self._anims.get(name)
        if old is not None:
            old.stop()
        an = QVariantAnimation(self)
        an.setStartValue(float(a))
        an.setEndValue(float(b))
        an.setDuration(ms)
        an.setEasingCurve(curve)
        an.valueChanged.connect(lambda v, n=name: self._set(n, float(v)))
        self._anims[name] = an
        an.start()

    def _set(self, name, v):
        setattr(self, "_" + name, v)
        self.update()

    def hover(self, on):
        self._run("h", self._h, 1.0 if on else 0.0, 240 if on else 200, QEasingCurve.Type.OutCubic)

    def press(self, down):
        if down:
            self._run("p", self._p, 1.0, 90, QEasingCurve.Type.OutCubic)
            self._run("r", 0.0, 1.0, 520, QEasingCurve.Type.OutCubic)
        else:
            self._run("p", self._p, 0.0, 220, QEasingCurve.Type.OutCubic)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        h, pr = max(0.0, self._h), self._p
        if h > 0.01:                                             # a soft glow behind
            g = QRadialGradient(c, self.width() * 0.5)
            col = QColor(self._accent)
            col.setAlpha(int(90 * min(h, 1.0)))
            g.setColorAt(0.0, col)
            col.setAlpha(0)
            g.setColorAt(1.0, col)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, self.width() * 0.5 * (0.7 + 0.3 * h), self.height() * 0.5 * (0.7 + 0.3 * h))
        if self._r < 0.999:                                      # a ring that spreads out from a press
            ring = QColor(self._accent)
            ring.setAlpha(int(200 * (1.0 - self._r)))
            p.setPen(QPen(ring, 2.5 * (1.0 - self._r) + 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rad = self.width() * (0.28 + 0.24 * self._r)
            p.drawEllipse(c, rad, rad)
        wob = math.sin(self._w * math.pi * 3.0) * (1.0 - self._w) * 14.0 if self._w < 1.0 else 0.0
        scale = 1.0 + 0.2 * h - 0.14 * pr
        p.translate(c.x(), c.y() - 5.0 * h + 2.0 * pr)
        p.rotate(wob)
        p.scale(scale, scale)
        w, hh = self._pm.width() / max(1.0, self._pm.devicePixelRatio()), self._pm.height() / max(1.0, self._pm.devicePixelRatio())
        if self.__dict__.get("_spin_on"):
            ang = 0.68 * math.sin(self._spin_t / self._spin_period * 2.0 * math.pi + self._spin_off)       # rocks about 40 degrees each way: smooth, always readable
            ca, sa = math.cos(ang), math.sin(ang)
            if abs(ca) < 0.08:
                ca = 0.08 if ca >= 0 else -0.08                  # edge-on it still shows the thickness
            D = 5.0
            N = max(5, min(14, int(D * abs(sa) * self.__dict__.get("_sdpr", 2.0) * 2.0) + 3))      # enough layers that the edge is solid, not stair-stepped
            dst, src = QRectF(-w / 2.0, -hh / 2.0, w, hh), QRectF(self._pm.rect())
            gl = QRadialGradient(QPointF(0.0, 0.0), w * 0.62)                          # the edge glows: a soft halo in the tool's colour, brighter as the icon tilts
            gc = QColor(self._accent)
            gc.setAlpha(int(34 + 70 * abs(sa)))
            gl.setColorAt(0.0, gc)
            gc.setAlpha(0)
            gl.setColorAt(1.0, gc)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gl)
            p.drawEllipse(QPointF(0.0, 0.0), w * 0.62, w * 0.62)
            p.restore()
            base = p.transform()
            sh = QRadialGradient(QPointF(0.0, hh / 2.0 + 9.0), w * 0.42)                  # a soft floor shadow that narrows as the icon turns
            sc_ = QColor(0, 0, 0, 70)
            sh.setColorAt(0.0, sc_)
            sc_.setAlpha(0)
            sh.setColorAt(1.0, sc_)
            p.save()
            p.translate(0.0, hh / 2.0 + 9.0)
            p.scale(0.55 + 0.45 * abs(ca), 0.16)
            p.translate(0.0, -(hh / 2.0 + 9.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sh)
            p.drawEllipse(QPointF(0.0, hh / 2.0 + 9.0), w * 0.42, w * 0.42)
            p.restore()
            base = p.transform()
            shy = 0.09 * sa                                                              # a touch of perspective: the near side is lower
            for k in sorted(range(N), key=lambda k: ((k / (N - 1.0)) - 0.5) * D * ca):      # far layers first
                z = ((k / (N - 1.0)) - 0.5) * D
                p.setTransform(QTransform(ca, shy, 0.0, 1.0, z * sa, 0.0) * base)
                if k == 0 or k == N - 1:
                    p.drawPixmap(dst, self._pm, src)
                else:
                    p.drawPixmap(dst, self._side, QRectF(self._side.rect()))
            p.setTransform(base)
        else:
            p.drawPixmap(QRectF(-w / 2.0, -hh / 2.0, w, hh), self._pm, QRectF(self._pm.rect()))
        p.end()


_SPINNERS = []
_SPIN_CK = {}


def _spin_clock():
    """one clock for every turning icon: ticks about 60 times a second, only while the program is the active window and the icon is on screen"""
    if _SPIN_CK.get("t") is not None:
        return
    from PySide6.QtCore import QElapsedTimer
    el = QElapsedTimer()
    el.start()
    tm = QTimer(QApplication.instance())
    tm.setTimerType(Qt.TimerType.PreciseTimer)
    tm.setInterval(33)

    def tick():
        t = el.elapsed() / 1000.0
        for w in list(_SPINNERS):
            try:
                if w.isVisible() and not w.visibleRegion().isEmpty():
                    w._spin_t = t
                    a_ = 0.68 * math.sin(t / w._spin_period * 2.0 * math.pi + w._spin_off)
                    if abs(a_ - w.__dict__.get("_spin_last", 9.0)) > 0.003:        # nothing to redraw while it hardly moves (the ends of the sway)
                        w._spin_last = a_
                        w.update()
            except RuntimeError:
                _SPINNERS.remove(w)
    tm.timeout.connect(tick)
    tm.start()
    _SPIN_CK["t"] = tm


_TIP = {}


def _tip_hide():
    w = _TIP.get("w")
    if w is not None:
        w.hide()


def _tip_split(b):
    t = b.toolTip().strip()
    if "<" in t and ">" in t:
        return None                                                     # rich tool tips keep their own look
    txt = (b.text() or "").replace("&&", "&").replace("&", "").strip()
    if "\n" in t:
        head, body = t.split("\n", 1)
    elif txt and txt.lower() not in t.lower()[:len(txt) + 2]:
        head, body = txt, t
    else:
        i = min([k for k in (t.find(". "), t.find(" - ")) if k > 0] or [len(t)])
        head, body = t[:i], t[i + 2:] if i < len(t) else ""
    return head.strip().rstrip("."), body.strip()


def _tip_show(b, ev):
    """a small card instead of the grey tool tip: the icon, the name in bold and what it does"""
    try:
        parts = _tip_split(b)
        if parts is None:
            return False
        head, body = parts
        w = _TIP.get("w")
        if w is None:
            w = QFrame(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(12, 9, 14, 10)
            lay.setSpacing(10)
            w._ic = QLabel()
            w._tx = QLabel()
            w._tx.setWordWrap(True)
            w._tx.setMaximumWidth(300)
            lay.addWidget(w._ic, 0, Qt.AlignmentFlag.AlignTop)
            lay.addWidget(w._tx, 1)
            w._an = QVariantAnimation(w)
            w._an.setDuration(140)
            w._an.setStartValue(0.0)
            w._an.setEndValue(1.0)
            w._an.valueChanged.connect(lambda v, w=w: w.setWindowOpacity(float(v)))
            w._tm = QTimer(w)
            w._tm.setSingleShot(True)
            w._tm.timeout.connect(w.hide)
            _TIP["w"] = w
        pal = QApplication.palette()
        dark = pal.color(QPalette.ColorRole.Window).lightness() < 128
        bg, fg, sub, bd = ("#1f2125", "#eceef0", "#9aa0a8", "#3a3f46") if dark else ("#ffffff", "#1c1f24", "#5b626b", "#d4d8de")
        w.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-left:3px solid %s;border-radius:9px;} QLabel{border:none;background:transparent;}" % (bg, bd, ACCENT[0]))
        ic = b.property("_ia_icon") or b.icon()
        if ic is not None and not ic.isNull():
            w._ic.setPixmap(ic.pixmap(QSize(24, 24)))
            w._ic.show()
        else:
            w._ic.hide()
        esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;")
        w._tx.setText("<div style='color:%s'><b>%s</b></div>%s" % (fg, esc(head), ("<div style='color:%s'>%s</div>" % (sub, esc(body))) if body else ""))
        w.adjustSize()
        g = b.mapToGlobal(QPoint(0, b.height() + 6))
        scr = QApplication.screenAt(g) or QApplication.primaryScreen()
        r = scr.availableGeometry()
        x = min(max(r.left() + 4, g.x()), r.right() - w.width() - 4)
        y = g.y() if g.y() + w.height() < r.bottom() else b.mapToGlobal(QPoint(0, 0)).y() - w.height() - 6
        w.move(x, y)
        if not w.isVisible():
            w.setWindowOpacity(0.0)
            w.show()
            w._an.start()
        w._tm.start(7000)
        return True
    except Exception:
        return False


class IconMotion(QObject):
    """Installed once on the application: the big tile icons (AnimIcon) and the small icons on buttons all move when you point at them or press them."""

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def _lock(b):
        if b.property("_ia_locked") is None:
            b.setProperty("_ia_locked", [b.minimumSize(), b.maximumSize()])
            b.setMinimumSize(b.size())
            b.setMaximumSize(b.size())

    @staticmethod
    def _unlock(b):
        old = b.property("_ia_locked")
        if old is not None:
            b.setMinimumSize(old[0])
            b.setMaximumSize(old[1])
            b.setProperty("_ia_locked", None)

    @staticmethod
    def _red(b, on):
        """the icon turns red while pointed at or pressed, and goes back to its own colour afterwards"""
        try:
            orig = b.property("_ia_icon")
            if on:
                if orig is None:
                    ic = b.icon()
                    sz = b.iconSize()
                    pm = ic.pixmap(QSize(sz.width() * 2, sz.height() * 2))
                    if pm.isNull():
                        return
                    q = QPainter(pm)
                    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    q.fillRect(pm.rect(), QColor(ACCENT[0]))
                    q.end()
                    b.setProperty("_ia_icon", ic)
                    b.setIcon(QIcon(pm))
            elif orig is not None:
                b.setIcon(orig)
                b.setProperty("_ia_icon", None)
        except Exception:
            pass

    def _to(self, b, target, ms=170):
        base = b.property("_ia_base")
        if base is None:
            base = b.iconSize()
            b.setProperty("_ia_base", base)
        cur = b.property("_ia_scale")
        cur = 1.0 if cur is None else float(cur)
        an = b.property("_ia_anim")
        if an is not None:
            an.stop()
        an = QVariantAnimation(b)
        an.setStartValue(cur)
        an.setEndValue(float(target))
        an.setDuration(ms)
        an.setEasingCurve(QEasingCurve.Type.OutCubic)

        def step(v, b=b, base=base):
            b.setProperty("_ia_scale", float(v))
            b.setIconSize(QSize(max(1, int(base.width() * float(v))), max(1, int(base.height() * float(v)))))

        def done(b=b, base=base, target=target):
            if abs(target - 1.0) < 1e-6:
                b.setIconSize(base)
                b.setProperty("_ia_base", None)
                b.setProperty("_ia_scale", None)
                self._unlock(b)
        an.valueChanged.connect(step)
        an.finished.connect(done)
        b.setProperty("_ia_anim", an)
        an.start()

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.Type.ToolTip and isinstance(obj, QAbstractButton) and obj.toolTip():
                return _tip_show(obj, ev)
            if t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide, QEvent.Type.Wheel, QEvent.Type.KeyPress):
                _tip_hide()
            if t not in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                return False
            big = getattr(obj, "_anim_icon", None)
            if big is not None:
                if t == QEvent.Type.Enter:
                    big.hover(True)
                elif t == QEvent.Type.Leave:
                    big.hover(False)
                    big.press(False)
                elif t == QEvent.Type.MouseButtonPress:
                    big.press(True)
                else:
                    big.press(False)
                return False
            if isinstance(obj, QAbstractButton) and obj.isEnabled() and not obj.icon().isNull() and obj.isVisible():
                if t == QEvent.Type.Enter:
                    self._lock(obj)
                    self._red(obj, True)
                    self._to(obj, 1.15)
                elif t == QEvent.Type.Leave:
                    self._red(obj, False)
                    self._to(obj, 1.0, 220)
                elif t == QEvent.Type.MouseButtonPress:
                    self._to(obj, 0.86, 90)
                else:
                    self._to(obj, 1.15, 200)
        except Exception:
            pass
        return False


def install_icon_motion():
    """once per program"""
    app = QApplication.instance()
    if app is None or getattr(app, "_icon_motion", None) is not None:
        return
    app._icon_motion = IconMotion(app)
    app.installEventFilter(app._icon_motion)


class _Wipe(QWidget):
    """A title card: the background is drawn once at the screen's own resolution and only moved; the icon, name and line are drawn live
    as vector text, so they are crisp on any screen, and come in one after another."""
    def __init__(self, parent, bg, col, title, sub, pm):
        super().__init__(parent)
        self.bg, self.col, self.title, self.sub, self.pm = bg, QColor(col), title, sub, pm
        self.y = 1.0                      # 1 = below the window, 0 = covering it
        self.a = 1.0                      # opacity of everything while it leaves
        self.t = 0.0                      # 0..1: the icon, name and line coming in
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @staticmethod
    def _ease(x):
        x = max(0.0, min(1.0, x))
        return 1.0 - (1.0 - x) ** 3

    def paintEvent(self, _e):
        from PySide6.QtGui import QFont, QFontMetrics
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        oy = int(self.y * h)
        p.setOpacity(self.a)
        p.drawPixmap(0, oy, self.bg)
        cx, cy = w // 2, h // 2 + oy
        e_i, e_t, e_s = self._ease((self.t - 0.05) / 0.55), self._ease((self.t - 0.25) / 0.55), self._ease((self.t - 0.45) / 0.55)
        if self.pm is not None:
            sz = 84
            q = max(0.0, min(1.0, (self.t - 0.05) / 0.6))
            back = 1.0 + 2.2 * (q - 1.0) ** 3 + 1.2 * (q - 1.0) ** 2            # ease-out-back: grows past its size and settles
            ix, iy = cx, cy - sz // 2 - 40
            p.save()
            ring = (self.t - 0.1) / 0.7                                         # a ring pulses out behind the icon and fades
            if 0.0 < ring < 1.0:
                r = 34 + 62 * self._ease(ring)
                p.setOpacity(self.a * 0.55 * (1.0 - ring))
                p.setPen(QPen(QColor(255, 255, 255), 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(ix, iy), r, r)
            p.setOpacity(self.a * e_i)
            p.translate(ix, iy + (1 - e_i) * 20)
            p.rotate(-14.0 * (1.0 - e_i))                                       # a small turn as it lands
            p.scale(max(0.01, 0.55 + 0.45 * back), max(0.01, 0.55 + 0.45 * back))
            p.drawPixmap(int(-sz / 2), int(-sz / 2), sz, sz, self.pm)
            p.restore()
        f = QFont()
        f.setPixelSize(max(30, min(64, w // 18)))
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        fm = QFontMetrics(f)
        th = fm.height()
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.setOpacity(self.a * e_t)
        ty = cy - 14 + (1 - e_t) * 26
        p.drawText(0, int(ty), w, th, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.title)
        lw = 90 * e_t
        p.fillRect(int(cx - lw / 2), int(ty + th + 10), int(lw), 4, QColor("#d8132b"))
        if self.sub:
            f2 = QFont()
            f2.setPixelSize(16)
            p.setFont(f2)
            p.setPen(QColor(255, 255, 255, 215))
            p.setOpacity(self.a * e_s)
            p.drawText(w // 6, int(ty + th + 28 + (1 - e_s) * 18), w * 2 // 3, 44, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.sub)
        f3 = QFont()
        f3.setPixelSize(11)
        f3.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        p.setFont(f3)
        p.setPen(QColor(255, 255, 255, 130))
        p.setOpacity(self.a * e_s)
        p.drawText(0, h - 40 + oy, w, 20, Qt.AlignmentFlag.AlignHCenter, "MCP ARCHITECTURE & INTERIORS")
        p.end()


def _card_bg(w, h, col, dpr):
    from PySide6.QtGui import QLinearGradient, QPixmap, QPolygonF
    from PySide6.QtCore import QPointF
    bg = QPixmap(int(w * dpr), int(h * dpr))
    bg.setDevicePixelRatio(dpr)
    q = QPainter(bg)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(col)
    g = QLinearGradient(0, h, w, 0)
    g.setColorAt(0.0, c.darker(260))
    g.setColorAt(0.55, c.darker(190))
    g.setColorAt(1.0, c.darker(130))
    q.fillRect(0, 0, w, h, g)
    q.setPen(Qt.PenStyle.NoPen)                       # two soft diagonal bands, like the MCP mark
    q.setBrush(QColor(255, 255, 255, 14))
    q.drawPolygon(QPolygonF([QPointF(w * 0.62, 0), QPointF(w * 0.78, 0), QPointF(w * 0.42, h), QPointF(w * 0.26, h)]))
    q.setBrush(QColor(255, 255, 255, 9))
    q.drawPolygon(QPolygonF([QPointF(w * 0.80, 0), QPointF(w * 0.90, 0), QPointF(w * 0.54, h), QPointF(w * 0.44, h)]))
    q.end()
    return bg


def wipe_open(win, src, col, on_covered, pm=None, ms=700, title="", sub=""):
    """Open a tool or a project with a title card: it slides up over the window while its icon, name and line come in one after another
    (700 ms), `on_covered` runs under it (the page changes, the project loads), it holds a moment and lifts away (380 ms)."""
    top = win.centralWidget() or win
    try:
        dpr = float(top.devicePixelRatioF())
    except Exception:
        dpr = 1.0
    ov = _Wipe(top, _card_bg(max(top.width(), 200), max(top.height(), 200), col, dpr), col, title, sub, pm)
    ov.setGeometry(top.rect())
    ov.show()
    ov.raise_()
    an = QVariantAnimation(ov)
    an.setDuration(ms)
    an.setStartValue(0.0)
    an.setEndValue(1.0)
    an.setEasingCurve(QEasingCurve.Type.Linear)

    def step(v):
        v = float(v)
        ov.y = (1.0 - min(1.0, v / 0.32)) ** 3          # the card arrives in the first third, then the words take their time
        ov.t = v
        ov.update()

    def covered():
        ov.y, ov.t = 0.0, 1.0
        ov.repaint()
        try:
            on_covered()
        finally:
            fa = QVariantAnimation(ov)
            fa.setDuration(380)
            fa.setStartValue(0.0)
            fa.setEndValue(1.0)
            fa.setEasingCurve(QEasingCurve.Type.InOutCubic)

            def out(v):
                ov.a = 1.0 - float(v)
                ov.y = -0.06 * float(v)            # it lifts a little as it fades
                ov.update()
            fa.valueChanged.connect(out)
            fa.finished.connect(ov.deleteLater)
            QTimer.singleShot(260, fa.start)        # hold a moment: the new page paints once under the card
            ov._fa = fa
    an.valueChanged.connect(step)
    an.finished.connect(covered)
    ov._an = an
    an.start()
    an.start()
    ov._an = an


def cascade(page, step_ms=95, rise=34, dur=480):
    """The boxes of a page come in one after another: each rises a little and fades in."""
    from PySide6.QtWidgets import QGroupBox
    from PySide6.QtCore import QPropertyAnimation, QPoint, QTimer
    boxes = []
    for g in page.findChildren(QGroupBox):
        p, top = g.parentWidget(), True
        while p is not None and p is not page:
            if isinstance(p, QGroupBox):
                top = False
                break
            p = p.parentWidget()
        if top and g.isVisible():
            boxes.append(g)
    boxes.sort(key=lambda g: (g.mapTo(page, g.rect().topLeft()).y(), g.mapTo(page, g.rect().topLeft()).x()))
    anims = []
    for k, g in enumerate(boxes[:8]):
        try:
            end = g.pos()
            eff = QGraphicsOpacityEffect(g)
            eff.setOpacity(0.0)
            g.setGraphicsEffect(eff)
            g.move(end + QPoint(0, rise))
            fa = QPropertyAnimation(eff, b"opacity", g)
            fa.setDuration(dur)
            fa.setStartValue(0.0)
            fa.setEndValue(1.0)
            fa.setEasingCurve(QEasingCurve.Type.OutCubic)
            pa = QPropertyAnimation(g, b"pos", g)
            pa.setDuration(dur + 120)
            pa.setStartValue(end + QPoint(0, rise))
            pa.setEndValue(end)
            pa.setEasingCurve(QEasingCurve.Type.OutCubic)

            def fin(g=g, eff=eff, lay=g.parentWidget().layout() if g.parentWidget() else None):
                if g.graphicsEffect() is eff:
                    g.setGraphicsEffect(None)
                if lay is not None:
                    lay.activate()
            fa.finished.connect(fin)
            QTimer.singleShot(k * step_ms, fa.start)
            QTimer.singleShot(k * step_ms, pa.start)
            anims += [fa, pa]
        except Exception:
            pass
    page._cascade = anims


class RingGauge(QWidget):
    """A small ring that fills to ok/total, with the count in the middle and a label under it. Painted by hand; the fill eases to its value."""
    def __init__(self, label="", parent=None):
        super().__init__(parent)
        self.label, self.ok, self.total, self.shown = label, 0, 0, 0.0
        self.col = QColor("#2e9e5b")
        self.setFixedHeight(118); self.setMinimumWidth(96)
        self._an = QVariantAnimation(self)
        self._an.setDuration(450)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.shown = float(v)
        self.update()

    def set_value(self, ok, total):
        self.ok, self.total = int(ok), int(total)
        self.col = QColor("#8a93a3") if not total else QColor("#2e9e5b") if ok >= total else QColor("#e0a030") if ok else QColor("#d8132b")
        tgt = (ok / total) if total else 0.0
        self._an.stop()
        self._an.setStartValue(self.shown)
        self._an.setEndValue(tgt)
        self._an.start()
        self.setToolTip("%s: %d of %d comply" % (self.label, ok, total) if total else "%s: nothing to check yet" % self.label)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        d = min(self.width(), self.height() - 22) - 10
        r = QRectF((self.width() - d) / 2.0, 4, d, d)
        pen = QPen(QColor(138, 147, 163, 70), 7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self.shown > 0.002:
            pen2 = QPen(self.col, 7)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen2)
            p.drawArc(r, 90 * 16, -int(360 * 16 * min(1.0, self.shown)))
        p.setPen(self.palette().windowText().color())
        f = p.font()
        f.setPixelSize(int(d * 0.30))
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, ("%d/%d" % (self.ok, self.total)) if self.total else "-")
        f.setPixelSize(12)
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(0, d + 8, self.width(), 18), Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()


def fade_pages(tw):
    """a tab widget: the page you switch to fades in instead of snapping"""
    if tw is None or getattr(tw, "_mot_fade", False):
        return
    tw._mot_fade = True

    def go(i):
        try:
            w = tw.widget(i)
            if w is None or not tw.isVisible() or w.graphicsEffect() is not None:
                return
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            an = QVariantAnimation(eff)
            an.setStartValue(0.0)
            an.setEndValue(1.0)
            an.setDuration(120)
            an.setEasingCurve(QEasingCurve.Type.OutCubic)
            an.valueChanged.connect(lambda v, e=eff: e.setOpacity(float(v)))

            def fin(w=w, eff=eff):
                if w.graphicsEffect() is eff:
                    w.setGraphicsEffect(None)
            an.finished.connect(fin)
            eff._an = an
            an.start()
        except Exception:
            pass
    tw.currentChanged.connect(go)


def fade_all(root):
    """every tab widget under root fades its pages (the main tabs and the tabs inside the tools)"""
    for tw in [root] + root.findChildren(QTabWidget) if isinstance(root, QTabWidget) else root.findChildren(QTabWidget):
        fade_pages(tw)


class _Busy(QWidget):
    """a thin red bar across the top of the window and a small 'working' pill, shown while a long job runs"""

    def __init__(self, win):
        super().__init__(win)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._txt = ""
        self.tm = QTimer(self)
        self.tm.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._t = (self._t + 0.035) % 1.0
        self.update()

    def start(self, txt):
        w = self.parentWidget()
        self._txt = txt
        self.setGeometry(0, 0, w.width(), 60)
        self.raise_()
        self.show()
        self.tm.start(25)

    def stop(self):
        self.tm.stop()
        self.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self.width()
        a = -0.3 + 1.6 * self._t
        x0, x1 = W * a, W * (a + 0.3)
        p.fillRect(QRectF(0, 0, W, 3), QColor(255, 64, 86, 40))
        p.fillRect(QRectF(max(0.0, x0), 0, min(W, x1) - max(0.0, x0), 3), QColor("#ff4056"))
        f = p.font()
        f.setPointSizeF(9.5)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self._txt)
        r = QRectF(W - tw - 62, 10, tw + 50, 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(31, 33, 37, 235))
        p.drawRoundedRect(r, 14, 14)
        c = QPointF(r.left() + 16, r.center().y())
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor("#ff4056"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(c.x() - 7, c.y() - 7, 14, 14), int(-self._t * 360 * 16 * 3) % (360 * 16), 100 * 16)
        p.setPen(QColor("#eceef0"))
        p.drawText(QRectF(r.left() + 30, r.top(), tw + 18, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._txt)


class busy:
    """with busy("Making the PDF..."): ... the bar shows while the block runs. It moves whenever the program lets the window redraw."""
    _depth = 0

    def __init__(self, text="Working..."):
        self.text = text
        self.b = None

    def __enter__(self):
        try:
            win = QApplication.activeWindow() or next((w for w in QApplication.topLevelWidgets() if w.isVisible()), None)
            if win is not None and busy._depth == 0:
                bar = getattr(win, "_mot_busy", None)
                if bar is None:
                    bar = win._mot_busy = _Busy(win)
                bar.start(self.text)
                self.b = bar
                QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
                QApplication.processEvents()
            busy._depth += 1
        except Exception:
            pass
        return self

    def __exit__(self, *a):
        try:
            busy._depth = max(0, busy._depth - 1)
            if self.b is not None:
                self.b.stop()
                QApplication.restoreOverrideCursor()
        except Exception:
            pass
        return False


class EmptyCard(QFrame):
    """A friendly empty screen: a soft round picture, what is missing, and one big button for the next step."""

    def __init__(self, title, hint, button="", action=None, icon=None, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyCard")
        self.setStyleSheet("QFrame#emptyCard{background:rgba(128,128,128,14);border:2px dashed rgba(128,128,128,90);border-radius:14px;} QFrame#emptyCard QLabel{border:none;background:transparent;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pic = QLabel()
        pic.setFixedSize(54, 54)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pic.setStyleSheet("QLabel{background:rgba(255,64,86,34);border-radius:27px;color:#ff4056;font-size:26px;font-weight:700;}")
        if icon is not None:
            pic.setPixmap(icon)
        else:
            pic.setText("+")
        v.addWidget(pic, 0, Qt.AlignmentFlag.AlignHCenter)
        t = QLabel("<b style='font-size:15px'>%s</b>" % title)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.setMinimumWidth(320)
        h.setMinimumHeight(58)
        h.setStyleSheet("QLabel{color:rgba(128,128,128,230);}")
        self.setMinimumHeight(236)
        v.addWidget(h)
        self.btn = None
        if button and action:
            self.btn = QPushButton(button)
            self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn.setMinimumHeight(38)
            self.btn.setStyleSheet("QPushButton{background:#d8132b;color:white;border:none;border-radius:10px;padding:8px 26px;font-weight:700;} QPushButton:hover{background:#ff4056;}")
            self.btn.clicked.connect(lambda _=False: action())
            v.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignHCenter)


class KeyHints(QObject):
    """Hold Ctrl for a moment and the keys show on the buttons that have one (the tools in the left bar: Ctrl+1 ... Ctrl+9)."""

    def __init__(self, app, rail_fn):
        super().__init__(app)
        self.rail_fn = rail_fn
        self.tags = []
        self.tm = QTimer(self)
        self.tm.setSingleShot(True)
        self.tm.timeout.connect(self.show_tags)
        app.installEventFilter(self)

    def show_tags(self):
        try:
            rail = self.rail_fn()
            if rail is None:
                return
            for idx, b in rail.nav.items():
                if idx < 9 and b.isVisible():
                    t = QLabel("Ctrl+%d" % (idx + 1), b)
                    t.setStyleSheet("QLabel{background:#d8132b;color:white;border-radius:7px;padding:1px 6px;font-size:10px;font-weight:700;}")
                    t.adjustSize()
                    t.move(b.width() - t.width() - 6, (b.height() - t.height()) // 2)
                    t.show()
                    self.tags.append(t)
        except Exception:
            pass

    def hide_tags(self):
        self.tm.stop()
        for t in self.tags:
            try:
                t.deleteLater()
            except RuntimeError:
                pass
        self.tags = []

    def eventFilter(self, o, e):
        try:
            if e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Control and not e.isAutoRepeat():
                self.tm.start(450)
            elif e.type() == QEvent.Type.KeyRelease and e.key() == Qt.Key.Key_Control and not e.isAutoRepeat():
                self.hide_tags()
            elif e.type() in (QEvent.Type.WindowDeactivate, QEvent.Type.ApplicationDeactivate):
                self.hide_tags()
        except Exception:
            pass
        return False


class _Splash(QWidget):
    """Instant start-up card: the logo pops in, a red light sweeps across it, a thin line keeps moving while the program loads."""

    def __init__(self, logo):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(440, 260)
        self.logo = logo if (logo is not None and not logo.isNull()) else None
        self.t = QElapsedTimer()
        self.t.start()
        self.fade = None
        self.tm = QTimer(self)
        self.tm.timeout.connect(self.update)
        self.tm.start(16)

    def paintEvent(self, e):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        ms = self.t.elapsed()
        p.fillRect(0, 0, W, H, QColor("#16171a"))
        p.setPen(QPen(QColor("#2a2c31"), 1))
        p.drawRect(0, 0, W - 1, H - 1)
        cx, cy = W / 2, H / 2 - 18
        k = min(1.0, ms / 650.0)
        ease = 1 - (1 - k) ** 3
        over = 1.0 + 0.10 * math.sin(min(1.0, ms / 650.0) * math.pi) * (1 - k)          # small overshoot
        pulse = 0.5 + 0.5 * math.sin(ms / 380.0)
        g = QRadialGradient(cx, cy, 120)
        g.setColorAt(0, QColor(255, 64, 86, int((40 + 35 * pulse) * ease)))
        g.setColorAt(1, QColor(255, 64, 86, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), 120, 120)
        if self.logo is not None:
            lh = 104
            sc = self.logo.scaledToHeight(lh, Qt.TransformationMode.SmoothTransformation)
            dw, dh = sc.width(), sc.height()
            img = QImage(dw, dh, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            q = QPainter(img)
            q.drawPixmap(0, 0, sc)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            ph = ((ms - 500) % 1800) / 1800.0                                          # red-white light sweep
            if ms > 500:
                x = -dw * 0.4 + ph * dw * 1.8
                lg = QLinearGradient(x - 26, 0, x + 26, dh * 0.3)
                lg.setColorAt(0, QColor(255, 255, 255, 0))
                lg.setColorAt(0.5, QColor(255, 255, 255, 190))
                lg.setColorAt(1, QColor(255, 255, 255, 0))
                q.fillRect(0, 0, dw, dh, lg)
            q.end()
            p.save()
            p.setOpacity(min(1.0, ease * 1.3))
            p.translate(cx, cy)
            p.scale(over * (0.82 + 0.18 * ease), over * (0.82 + 0.18 * ease))
            p.drawImage(QPointF(-dw / 2, -dh / 2), img)
            p.restore()
        else:
            p.setPen(QColor("#eceef0"))
            f = QFont(self.font())
            f.setPointSize(16)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(0, cy - 20, W, 40), Qt.AlignmentFlag.AlignCenter, "MCP Architecture & Interiors")
        # thin loading line: a red piece that slides along the bottom
        ly = H - 38
        p.setPen(QPen(QColor("#2a2c31"), 2))
        p.drawLine(70, ly, W - 70, ly)
        ph = (ms % 1300) / 1300.0
        seg = 90
        x0 = 70 + (W - 140 + seg) * ph - seg
        a0, a1 = max(70, x0), min(W - 70, x0 + seg)
        if a1 > a0:
            lg = QLinearGradient(x0, 0, x0 + seg, 0)
            lg.setColorAt(0, QColor(255, 64, 86, 0))
            lg.setColorAt(0.5, QColor(255, 64, 86, 255))
            lg.setColorAt(1, QColor(255, 64, 86, 0))
            p.setPen(QPen(QBrush(lg), 2))
            p.drawLine(QPointF(a0, ly), QPointF(a1, ly))
        p.end()


def splash_show(app, logo_pixmap=None):
    """appears at once (before anything slow runs) and keeps animating"""
    w = _Splash(logo_pixmap)
    scr = app.primaryScreen().availableGeometry()
    w.move(scr.center().x() - w.width() // 2, scr.center().y() - w.height() // 2)
    w.show()
    w.repaint()
    app.processEvents()
    return w


def splash_close(w):
    if w is None:
        return
    an = QVariantAnimation(w)
    an.setStartValue(1.0)
    an.setEndValue(0.0)
    an.setDuration(260)
    an.valueChanged.connect(lambda v: w.setWindowOpacity(float(v)))
    an.finished.connect(w.close)
    w._out = an
    an.start()


class ModelPopup(QWidget):
    """A card that floats beside a recent project when the mouse rests on its 3D picture: the same model, bigger, still turning."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.frames, self.title, self.key, self.i = [], "", None, 0
        self.W, self.H = 360, 230
        self.setFixedSize(self.W + 28, self.H + 58)
        self.t = QTimer(self)
        self.t.setInterval(66)
        self.t.timeout.connect(self._tick)

    def set(self, title, frames, key):
        self.title, self.frames, self.key = title, frames, key
        self.update()

    def _tick(self):
        self.i += 1
        self.update()

    def showEvent(self, e):
        self.t.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.t.stop()
        super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 64, 86, 140), 1.2))
        p.setBrush(QColor(27, 29, 34, 246))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(QColor(236, 238, 240))
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.drawText(QRectF(16, 10, self.W, 26), Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.frames:
            img = self.frames[self.i % len(self.frames)]
            dpr = img.devicePixelRatio() or 1.0
            lw, lh = img.width() / dpr, img.height() / dpr
            if abs(lw - self.W) > 2:                                  # the small pictures (until the big ones are ready) are stretched to fit
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QRectF(14, 40, self.W, self.H), img)
        p.end()


class CardModelHover(QObject):
    """Watches a recent-project card: when the mouse rests on its 3D picture, show it bigger."""

    def __init__(self, card, pic, show, hide):
        super().__init__(card)
        self.card, self.pic, self._show, self._hide = card, pic, show, hide
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.setInterval(220)
        self.t.timeout.connect(lambda: self._show(self.card, self.pic))
        card.setMouseTracking(True)
        card.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        try:
            if t == QEvent.Type.MouseMove:
                inside = self.pic.geometry().contains(ev.position().toPoint())
                if inside and not self.t.isActive() and not self.__dict__.get("_on"):
                    self.t.start()
                elif not inside:
                    self.t.stop()
                    if self.__dict__.get("_on"):
                        self._on = False
                        self._hide()
            elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
                self.t.stop()
                if self.__dict__.get("_on"):
                    self._on = False
                    self._hide()
            elif t == QEvent.Type.Timer:
                pass
        except RuntimeError:
            pass
        return False

    def mark_on(self):
        self._on = True


class SpinPic(QWidget):
    """The turning picture on a card: paints the ready-made frame straight to the screen (no pixmap made per frame)."""

    def __init__(self, img, w=120, h=70):
        super().__init__()
        self.img = img
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def show_img(self, img):
        self.img = img
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawImage(self.rect(), self.img)
        p.end()


# ==================================================================== Mail tab: a live view of the Gmail account
# Nothing is downloaded or kept: every list and message is fetched from Gmail when it is opened and drawn on screen.
import app_shell as _ZSH
import base64 as _b64
import datetime as _dt
import html as _html
import json as _json
import threading as _th
import time as _time
from email.message import EmailMessage as _EmailMessage
def _formataddr(a):
    nm, ad = a
    return '"%s" <%s>' % (nm.replace('"', ''), ad) if nm else ad


from email.utils import getaddresses as _getaddr, parseaddr as _parseaddr

from PySide6.QtCore import QRect, QSize as _QSize, Signal as _Signal
from PySide6.QtGui import QIcon as _QIcon, QTextDocument, QAction as _QAction
from PySide6.QtGui import QFont as _QFont, QFontMetrics as _QFM
from PySide6.QtWidgets import (QAbstractItemView as _AIV, QCheckBox as _QCheck, QFileDialog as _QFD, QHBoxLayout as _HB, QLineEdit as _QLE, QListWidget as _QLW,
                               QListWidgetItem as _QLWI, QMessageBox as _QMB, QPushButton as _QPB, QSplitter as _QSplit, QStackedWidget as _QStack, QStyledItemDelegate as _QSID,
                               QTabBar as _QTabBar, QTextBrowser as _QTB, QTextEdit as _QTE, QVBoxLayout as _VB, QWidget as _QW, QLabel as _QL, QDialog as _QD, QFrame as _QF,
                               QScrollArea as _QSA, QSizePolicy as _QSP, QMenu as _QMenu, QComboBox as _QCombo, QInputDialog as _QID)

MAIL_SYSTEM = [("INBOX", "Inbox"), ("STARRED", "Starred"), ("SENT", "Sent"), ("DRAFT", "Drafts"), ("SPAM", "Spam"), ("TRASH", "Trash"), ("ALL", "All Mail")]
MAIL_CATEGORIES = [("CATEGORY_PERSONAL", "Primary"), ("CATEGORY_PROMOTIONS", "Promotions"), ("CATEGORY_SOCIAL", "Social"), ("CATEGORY_UPDATES", "Updates")]
ROLE_THREAD, ROLE_SENDER, ROLE_SUBJECT, ROLE_SNIP, ROLE_DATE, ROLE_UNREAD, ROLE_STAR, ROLE_CHECK, ROLE_CLIP = [Qt.ItemDataRole.UserRole + i for i in range(1, 10)]
ROLE_LABS = Qt.ItemDataRole.UserRole + 10          # the colours of the user labels on a conversation
# Gmail only accepts colours from its own palette
MAIL_PALETTE = [("Red", "#fb4c2f"), ("Orange", "#ffad47"), ("Yellow", "#fad165"), ("Green", "#16a766"), ("Mint", "#43d692"), ("Blue", "#4a86e8"),
                ("Purple", "#a479e2"), ("Pink", "#f691b3"), ("Grey", "#999999")]
MAIL_NOCOL = "#8a93a3"
MAIL_GRID = [["#f6c5be", "#efa093", "#e66550", "#fb4c2f", "#cc3a21", "#ac2b16"],        # Gmail's own label palette: light to dark in each colour
             ["#ffe6c7", "#ffd6a2", "#ffbc6b", "#ffad47", "#eaa041", "#cf8933"],
             ["#fef1d1", "#fce8b3", "#fcda83", "#fad165", "#f2c960", "#d5ae49"],
             ["#b9e4d0", "#89d3b2", "#44b984", "#16a766", "#149e60", "#0b804b"],
             ["#c6f3de", "#a0eac9", "#68dfa9", "#43d692", "#3dc789", "#2a9c68"],
             ["#c9daf8", "#a4c2f4", "#6d9eeb", "#4a86e8", "#3c78d8", "#285bac"],
             ["#e4d7f5", "#d0bcf1", "#b694e8", "#a479e2", "#8e63ce", "#653e9b"],
             ["#fcdee8", "#fbc8d9", "#f7a7c0", "#f691b3", "#e07798", "#b65775"],
             ["#efefef", "#cccccc", "#999999", "#666666", "#434343", "#000000"]]


_PLAIN_BG = re.compile(r"(?is)bgcolor\s*=|\sbackground\s*=|background(?:-color|-image)?\s*:\s*(?!(?:#fff\b|#ffffff\b|white\b|transparent\b|none\b|inherit\b|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)))")
_CLR = re.compile(r"(?i)((?<![-\w])color\s*[:=]\s*[\"']?)(#[0-9a-f]{6}|#[0-9a-f]{3}|rgb\([^)]*\)|black|navy|blue|maroon|purple|green|gray|grey)")


def mail_plain(html):
    """True for a simple email (no pictures, no colours of its own): it can wear the program's dark look without spoiling anything."""
    if not html:
        return True
    if re.search(r"(?i)<img\b", html) or _PLAIN_BG.search(html):
        return False
    return True


def mail_lighten(html):
    """Dark text colours in a plain email become light and the blue links lighter, so it reads on the dark page."""
    def fix(m):
        c = QColor(m.group(2))
        if not c.isValid():
            m2 = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", m.group(2))
            c = QColor(int(m2.group(1)), int(m2.group(2)), int(m2.group(3))) if m2 else QColor("#000000")
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        if c.blue() > c.red() + 40 and c.blue() > c.green() and lum < 190:
            return m.group(1) + "#7cb7f0"
        if lum < 120:
            return m.group(1) + "#eceef0"
        return m.group(0)
    return _CLR.sub(fix, html)


def mail_text_on(hx):
    c = QColor(hx)
    return "#000000" if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 150 else "#ffffff"


def mail_pick_color(parent, current=""):
    """A grid of Gmail's label colours (54 of them); returns the chosen colour, "" for none, or None when cancelled."""
    from PySide6.QtWidgets import QDialog, QGridLayout, QPushButton, QVBoxLayout, QLabel
    d = QDialog(parent)
    d.setWindowTitle("Label colour")
    v = QVBoxLayout(d)
    v.addWidget(QLabel("Choose a colour for the label"))
    g = QGridLayout()
    g.setSpacing(6)
    out = {"v": None}

    def pick(hx):
        out["v"] = hx
        d.accept()
    for r, row in enumerate(MAIL_GRID):
        for c, hx in enumerate(row):
            b = QPushButton()
            b.setFixedSize(34, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            ring = "3px solid #ffffff" if hx.lower() == (current or "").lower() else "1px solid rgba(0,0,0,70)"
            b.setStyleSheet("QPushButton{background:%s;border:%s;border-radius:6px;} QPushButton:hover{border:2px solid #4aa3df;}" % (hx, ring))
            b.clicked.connect(lambda _=False, hx=hx: pick(hx))
            g.addWidget(b, r, c)
    v.addLayout(g)
    none = QPushButton("No colour")
    none.clicked.connect(lambda: pick(""))
    v.addWidget(none)
    d.exec()
    return out["v"]


def mail_swatch(col, n=14):
    pm = QPixmap(n, n)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(col))
    p.drawRoundedRect(1, 1, n - 2, n - 2, 3, 3)
    p.end()
    return _QIcon(pm)



def mail_b64(d):
    d = d or ""
    return _b64.urlsafe_b64decode(d + "=" * (-len(d) % 4))


def mail_header(msg, name):
    for h in (msg.get("payload") or {}).get("headers", []) or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def mail_parts(payload):
    """(html, plain, attachments) of one Gmail message payload. attachments: [{name, mime, size, id, cid, data}]."""
    out = {"html": [], "plain": [], "att": []}

    def walk(p):
        if not p:
            return
        mime = str(p.get("mimeType", "")).lower()
        body = p.get("body") or {}
        name = p.get("filename") or ""
        hdrs = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in p.get("headers", []) or []}
        cid = hdrs.get("content-id", "").strip("<> ")
        if name or (body.get("attachmentId") and not mime.startswith("text/")):
            out["att"].append({"name": name or "attachment", "mime": mime, "size": int(body.get("size", 0) or 0), "id": body.get("attachmentId", ""),
                               "cid": cid, "data": body.get("data", "")})
        elif mime == "text/html" and body.get("data"):
            out["html"].append(mail_b64(body["data"]).decode("utf-8", "replace"))
        elif mime == "text/plain" and body.get("data"):
            out["plain"].append(mail_b64(body["data"]).decode("utf-8", "replace"))
        for c in p.get("parts", []) or []:
            walk(c)
    walk(payload)
    return "".join(out["html"]), "\n".join(out["plain"]), out["att"]


_IMG_RE = re.compile(r"(?is)<img\b[^>]*?>")
_SRC_RE = re.compile(r"""(?is)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def mail_img_src(tag):
    m = _SRC_RE.search(tag)
    return _html.unescape((m.group(1) or m.group(2) or m.group(3) or "").strip()) if m else ""


def mail_sniff(data):
    """What a block of picture bytes really is, in a word (for the message when Qt cannot read it)."""
    h = bytes(data[:16])
    if h.startswith(b"\x89PNG"):
        return "png"
    if h.startswith(b"\xff\xd8"):
        return "jpeg"
    if h.startswith(b"GIF8"):
        return "gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if h[4:8] == b"ftyp":
        return "heic"
    low = bytes(data[:200]).lower().lstrip()
    if low.startswith((b"<svg", b"<?xml")):
        return "svg"
    if low.startswith((b"<!doc", b"<html", b"{")):
        return "a web page, not a picture"
    return "unknown (%s)" % h[:6].hex()


def mail_pixmap(data):
    """A QPixmap from picture bytes: Qt first, then OpenCV (reads webp and others the installed Qt may lack); a null pixmap when neither can."""
    img = QPixmap()
    if img.loadFromData(data) and not img.isNull():
        return img
    try:
        import cv2
        import numpy as _np
        arr = cv2.imdecode(_np.frombuffer(bytes(data), _np.uint8), cv2.IMREAD_UNCHANGED)
        if arr is not None:
            ok, png = cv2.imencode(".png", arr)
            if ok and img.loadFromData(bytes(png.tobytes())) and not img.isNull():
                return img
    except Exception:
        pass
    return QPixmap()


def mail_qimage(data):
    """Like mail_pixmap but a QImage: it can be decoded in a background thread, so opening an email only has to lay it out."""
    img = QImage()
    if img.loadFromData(data) and not img.isNull():
        return img
    try:
        import cv2
        import numpy as _np
        arr = cv2.imdecode(_np.frombuffer(bytes(data), _np.uint8), cv2.IMREAD_UNCHANGED)
        if arr is not None:
            ok, png = cv2.imencode(".png", arr)
            if ok and img.loadFromData(bytes(png.tobytes())) and not img.isNull():
                return img
    except Exception:
        pass
    return QImage()


_ORIG = {}                                     # (document id, picture resource) -> the picture's own bytes, for Save picture


def mail_warm(inline):
    """Decode the pictures of an email ahead of time (called from a background thread) into the shared cache."""
    for v in list(inline.values()):
        if isinstance(v, (bytes, bytearray)) and v:
            hk = hash(bytes(v))
            if hk not in _PIXC:
                im = QImage()
                if im.loadFromData(bytes(v)) and not im.isNull():
                    if len(_PIXC) > 120:
                        _PIXC.clear()
                    _PIXC[hk] = im


_ATTR_DROP = re.compile(r"""(?is)\s(?:width|height|style)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""")
_W_ATTR = re.compile(r"""(?is)\bwidth\s*=\s*["']?\s*(\d+)\s*(%?)""")
_W_STYLE = re.compile(r"""(?is)(?<![-\w])width\s*:\s*(\d+(?:\.\d+)?)\s*(px|%)""")


def _dpr():
    try:
        return max(1.0, float(QApplication.primaryScreen().devicePixelRatio()))
    except Exception:
        return 1.0


_TR_RE = re.compile(r"(?is)<tr\b[^>]*>((?:(?!<tr\b|<table\b).)*?)</tr>")
_TDP_RE = re.compile(r"(?is)(<td\b[^>]*?\bwidth\s*=\s*[\"']?)([\d.]+)(\s*%)")


def mail_fix_rows(body):
    """A row of cells with percentage widths that adds up to less than 100 % (signature pieces sent by earlier versions) is stretched to the full row."""
    def row(m):
        cells = re.findall(r"(?is)<td\b[^>]*>", m.group(1))
        pcts = []
        for c in cells:
            pm = re.search(r"(?is)\bwidth\s*=\s*[\"']?([\d.]+)\s*%", c)
            if not pm:
                return m.group(0)
            pcts.append(float(pm.group(1)))
        tot = sum(pcts)
        if not pcts or tot >= 99.0 or tot < 40.0:
            return m.group(0)
        k = 100.0 / tot
        return m.group(0).replace(m.group(1), _TDP_RE.sub(lambda q: q.group(1) + ("%.3f" % (float(q.group(2)) * k)) + q.group(3), m.group(1)), 1)
    return _TR_RE.sub(row, body)


def mail_drop_hidden(body):
    """Qt ignores display:none, so the dark-mode logo, the phone-only signature and other hidden parts would all show at once. They are removed."""
    body = re.sub(r"(?is)<img\b[^>]*display\s*:\s*none[^>]*>", "", body)
    for _ in range(20):
        m = re.search(r"(?is)<(div|table|span|td|tr|p)\b[^>]*display\s*:\s*none[^>]*>", body)
        if not m:
            break
        name = m.group(1).lower()
        depth, end = 1, None
        for t in re.finditer(r"(?is)<(/?)" + name + r"\b[^>]*>", body[m.end():]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = m.end() + t.end()
                break
        body = body[:m.start()] + (body[end:] if end else body[m.end():])
    return body


def mail_fit_widths(body, maxw):
    """Fixed widths wider than the window (600/900 px tables, min-width) become 100% so the email fits its view."""
    body = re.sub(r"(?is)(?:min-width|min-height)\s*:\s*[\d.]+\s*(?:px|pt|%)?\s*;?", "", body)
    body = re.sub(r"(?is)(<(?:table|td|th|div|center)\b[^>]*?\bwidth\s*=\s*[\"']?)(\d+)([\"']?)",
                  lambda m: m.group(1) + ("100%" if int(m.group(2)) > maxw else m.group(2)) + m.group(3), body)
    body = re.sub(r"(?is)(?<![-\w])width\s*:\s*(\d+(?:\.\d+)?)\s*px", lambda m: ("width:100%" if float(m.group(1)) > maxw else m.group(0)), body)
    return body


_PIXC = {}


def _sig_px_plain(body, maxw):
    """The same signature when the sender's mail service has removed our data-t / data-pw marks (Gmail does this for some senders): the structure is
    recognised by its picture names (cid:mcpsig0...) and every percentage width is turned into pixels from the table it sits in."""
    m0 = re.search(r'(?is)<table\b[^>]*table-layout\s*:\s*fixed[^>]*>\s*<tr>\s*<td\b[^>]*>\s*(?:<a\b[^>]*>\s*)?<img\b[^>]*cid:mcpsig0', body)
    if not m0:
        return body
    start = m0.start()
    depth, pos, end = 0, start, None
    for t in re.finditer(r"(?is)<(/?)table\b", body[start:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            end = start + t.end()
            end = body.find(">", end) + 1
            break
    if end is None:
        return body
    T = max(200, min(620, int(maxw)))
    stack = [float(T)]                                        # the width available to what is inside
    out, last = [], start
    for t in re.finditer(r"(?is)<(/?)(table|td)\b[^>]*>", body[start:end]):
        tag, closing, name = t.group(0), t.group(1), t.group(2).lower()
        out.append(body[last:start + t.start()])
        last = start + t.end()
        if closing:
            if len(stack) > 1:
                stack.pop()
            out.append(tag)
            continue
        wm = re.search(r'(?i)\swidth\s*=\s*["\']?\s*([\d.]+)\s*(%?)', tag)
        avail = stack[-1]
        if wm and wm.group(2):
            px = max(1, int(round(avail * float(wm.group(1)) / 100.0)))
        elif wm:
            px = max(1, int(float(wm.group(1))))
        else:
            px = int(avail)
        if name == "td" and wm and wm.group(2):
            tag = re.sub(r'(?i)\swidth\s*=\s*["\'][^"\']*["\']', "", tag, count=1)
            tag = tag[:-1] + ' width="%d" data-pw="%d">' % (px, px)
        elif name == "table" and wm and wm.group(2):
            tag = re.sub(r'(?i)\swidth\s*=\s*["\'][^"\']*["\']', "", tag, count=1)
            tag = tag[:-1] + ' width="%d">' % px
        out.append(tag)
        stack.append(float(px))
    out.append(body[last:end])
    return body[:start] + "".join(out) + body[end:]


def mail_sig_px(body, maxw):
    """Our own signature (a left picture and linked pieces on the right): the text engine sizes percentage widths inside it wrongly,
    so every piece gets its width in pixels, worked out from the width the email has."""
    m = re.search(r'<table\b[^>]*\bdata-t="(\d+)"', body)
    if not m:
        return _sig_px_plain(body, maxw)
    T = max(200, min(int(m.group(1)), int(maxw)))

    def fix(mm):
        tag = mm.group(0)
        pw = float(mm.group(1))
        px = max(1, int(round(T * pw / 100.0)))
        tag = re.sub(r'(?i)\swidth="[^"]*"', "", tag, count=1)
        return tag[:-1] + ' width="%d">' % px
    return re.sub(r'<(?:table|td)\b[^>]*\bdata-pw="([\d.]+)"[^>]*>', fix, body)


def mail_fix_images(body, doc, inline, remote_ok, maxw=700):
    """Make every picture in an email either show or vanish (never Qt's big grey 'missing picture' box).
    cid: pictures come from the attachments, data: pictures are decoded, web pictures show only when fetched (inline['url:...'])."""
    seen = {}
    body = _ZSH.zs(body)                                      # the program's zoom (Ctrl + wheel) makes the email's own sizes bigger or smaller too
    cm = [int(x) for x in re.findall(r"(?is)(?<![-\w])max-width\s*:\s*(\d+)\s*px", body)]
    cm = [x for x in cm if x >= 300]
    imgw = max(cm) if cm and max(cm) < maxw else maxw          # pictures never wider than the email's own column

    def one(m):
        tag = m.group(0)
        src = mail_img_src(tag)
        data = None
        if src.lower().startswith("cid:"):
            data = inline.get(src[4:].strip().lower())
        elif src.lower().startswith("data:") and "," in src:
            try:
                head, payload = src.split(",", 1)
                data = _b64.b64decode(payload + "=" * (-len(payload) % 4)) if "base64" in head.lower() else None
            except Exception:
                data = None
        elif src.lower().startswith(("http://", "https://")):
            data = inline.get("url:" + src)
        if not data:
            if src.lower().startswith("cid:"):
                why = inline.get("err:" + src[4:].strip().lower())
                if not why:
                    return ""                                    # still on its way (the page says "Loading pictures..."): no placeholder text, which broke the layout of cut-up banners
                return "<span style='color:#8a9099;font-size:11px'>[picture not loaded: %s]</span>" % _html.escape(str(why))
            return ""
        key = seen.get(src)
        if key is None:
            hk = hash(data)
            img = _PIXC.get(hk)
            if img is None:
                img = mail_qimage(data)
                if not img.isNull():
                    if len(_PIXC) > 120:
                        _PIXC.clear()
                    _PIXC[hk] = img
            if img.isNull():
                return "<span style='color:#8a9099;font-size:11px'>[picture could not be read: %s, %d KB]</span>" % (_html.escape(mail_sniff(data)), max(1, len(data) // 1024))
            key = "mimg:///%d" % len(seen)
            seen[src] = key
            dims[key] = (img.width(), img.height())
            pix[key] = img
        pw, ph = dims[key]
        w_attr = _W_ATTR.search(tag)
        w_sty = _W_STYLE.search(tag)
        if w_attr and not w_attr.group(2):
            target = int(w_attr.group(1))
        elif w_sty and w_sty.group(2) == "px":
            target = int(float(w_sty.group(1)))
        elif w_attr or w_sty:                                   # a percentage of its cell (a signature cut into pieces: each cell has its own share)
            pct = float((w_attr.group(1) if w_attr and w_attr.group(2) else (w_sty.group(1) if w_sty and w_sty.group(2) == "%" else 100)) or 100)
            share = 1.0
            td = m.string.rfind("<td", max(0, m.start() - 400), m.start())
            cellpx = 0
            if td >= 0:
                ttag = m.string[td:m.string.find(">", td) + 1]
                tm = re.search(r"(?is)\bwidth\s*=\s*[\"']?\s*([\d.]+)\s*%", ttag)
                if tm:
                    share = float(tm.group(1)) / 100.0
                else:
                    tp = re.search(r"(?is)\bwidth\s*=\s*[\"']?\s*(\d+)\s*[\"' >]", ttag)
                    if tp and "data-pw" in ttag:
                        cellpx = int(tp.group(1))                    # our own signature: the cell's width in pixels is the picture's width
            target = int(cellpx * pct / 100.0) if cellpx else int(imgw * pct / 100.0 * share)
        else:
            target = pw
        target = max(1, min(target, imgw))
        if target > pw * 2:
            target = pw * 2
        h = max(1, int(round(target * ph / float(max(1, pw)))))
        rk = "%s_%d_%d" % (key, target, int(dpr * 100))
        if rk not in made:
            made.add(rk)
            im2 = pix[key]
            if target != pw:                                    # a smooth resize here, because Qt's text view would otherwise squash it roughly (jagged edges)
                im2 = im2.scaled(int(target * dpr), int(h * dpr), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(rk), im2)
            _ORIG[(id(doc), rk)] = data
            if len(_ORIG) > 200:
                _ORIG.clear()
        t2 = _ATTR_DROP.sub("", tag)
        t2 = _SRC_RE.sub('src="%s" width="%d" height="%d"' % (rk, target, h), t2, 1)
        return t2
    dims = {}
    pix = {}
    made = set()
    dpr = _dpr()
    return mail_round(mail_fit_widths(mail_maxwidth(_IMG_RE.sub(one, mail_fix_rows(mail_sig_px(mail_drop_hidden(body), maxw))), maxw), maxw), doc)


_RD_OPEN = re.compile(r"""(?is)<(td|table|div|span)\b[^>]*?border-radius[^>]*>""")
_RD_RES = {}


def _css(style, name):
    ms = re.findall(r"(?is)(?<![-\w])" + name + r"\s*:\s*([^;\"']+)", style or "")
    return ms[-1].strip() if ms else ""            # the last one wins, as in CSS


def _rd_color(v):
    m = re.search(r"(?i)#[0-9a-f]{3,8}\b|rgba?\([^)]*\)", v or "")
    if m:
        c = QColor(m.group(0)) if m.group(0).startswith("#") else None
        if c is None:
            n = [float(x) for x in re.findall(r"[\d.]+", m.group(0))]
            c = QColor(int(n[0]), int(n[1]), int(n[2]), int(n[3] * 255) if len(n) > 3 and n[3] <= 1 else 255)
        return c
    c = QColor(v.strip().split()[-1]) if v and v.strip() else QColor()
    return c if c.isValid() else None


def _rd_corner(doc, r, fill, line, bw, pos):
    """One rounded corner as a picture: fill colour inside, line colour as the border, transparent outside."""
    key = "mrc:///%s_%d_%s_%s_%d_%s" % (fill.name(QColor.NameFormat.HexArgb) if fill else "n", r, line.name() if line else "n", pos, bw, id(doc))
    if key in _RD_RES:
        return key
    k = max(2, int(math.ceil(_dpr())))
    im = QPixmap(2 * r * k, 2 * r * k)
    im.fill(Qt.GlobalColor.transparent)
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    if line is not None and bw:
        p.setBrush(line)
        p.drawEllipse(0, 0, 2 * r * k, 2 * r * k)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(bw * k, bw * k, (2 * r - 2 * bw) * k, (2 * r - 2 * bw) * k)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    if fill is not None and fill.alpha() > 0:
        p.setBrush(fill)
        p.drawEllipse(bw * k, bw * k, (2 * r - 2 * bw) * k, (2 * r - 2 * bw) * k)
    p.end()
    ox = 0 if pos[1] == "l" else r * k
    oy = 0 if pos[0] == "t" else r * k
    q = im.copy(ox, oy, r * k, r * k)
    doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), q)
    _RD_RES[key] = 1
    return key


def _rd_pad(style):
    v = _css(style, "padding")
    nums = [int(float(x)) for x in re.findall(r"(-?[\d.]+)\s*(?:px)?", v)] if v else []
    if len(nums) == 1:
        nums *= 4
    elif len(nums) == 2:
        nums = [nums[0], nums[1], nums[0], nums[1]]
    elif len(nums) == 3:
        nums = [nums[0], nums[1], nums[2], nums[1]]
    elif len(nums) != 4:
        nums = [0, 0, 0, 0]
    for side, i in (("top", 0), ("right", 1), ("bottom", 2), ("left", 3)):
        m = re.search(r"(?is)padding-" + side + r"\s*:\s*(-?[\d.]+)", style or "")
        if m:
            nums[i] = int(float(m.group(1)))
    return nums


def _rd_strip(style):
    keep = []
    for d in (style or "").split(";"):
        n = d.split(":", 1)[0].strip().lower()
        if n and not (n.startswith(("border", "background", "padding", "overflow", "box-shadow"))):
            keep.append(d.strip())
    return ";".join(keep)


_RD_TAGS = {n: re.compile(r"(?is)<(/?)" + n + r"\b[^>]*>") for n in ("td", "table", "div", "span")}


def _rd_close(body, name, pos):
    depth = 1
    for m in _RD_TAGS[name].finditer(body, pos):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.start(), m.end()
    return None


def _rd_attr(tag, name):
    m = re.search(r"""(?is)\s%s\s*=\s*(?:"([^"]*)"|'([^']*)')""" % name, tag)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


def mail_round(body, doc):
    """Qt's text view cannot draw rounded corners. Every box with border-radius is rebuilt from small rounded-corner pictures
    (and small coloured pills become one picture), so cards, bars and chips look as they do in Gmail."""
    for m in reversed(list(_RD_OPEN.finditer(body))):
        tag, name = m.group(0), m.group(1).lower()
        style = _rd_attr(tag, "style")
        rad = _css(style, "border-radius")
        nums = [float(x) for x in re.findall(r"[\d.]+", rad)] if rad else []
        r = int(round(max(nums))) if nums else 0
        end = _rd_close(body, name, m.end())
        plain = re.sub(r"(?is)border-radius\s*:[^;\"']*;?", "", tag)
        if end is None or r < 2:
            body = body[:m.start()] + plain + body[m.end():]
            continue
        inner = body[m.end():end[0]]
        bgv = _css(style, "background-color") or _css(style, "background")
        fill = _rd_color(bgv) or _rd_color(_rd_attr(tag, "bgcolor"))
        bd = _css(style, "border")
        bw = 0
        line = None
        mb = re.search(r"([\d.]+)\s*px", bd) if bd else None
        if bd and mb and "none" not in bd.lower():
            bw = max(1, int(float(mb.group(1))))
            line = _rd_color(bd)
        pt, pr, pb, pl = _rd_pad(style)
        if name == "span":
            if re.search(r"<", inner) or fill is None or len(inner) > 40 or not inner.strip():
                body = body[:m.start()] + plain + body[m.end():]
                continue
            fs = _css(style, "font-size")
            px = int(float(re.search(r"[\d.]+", fs).group(0))) if re.search(r"[\d.]+", fs) else 13
            fw = _css(style, "font-weight").lower()
            f = _QFont(_css(style, "font-family").split(",")[0].strip(" \"'") or "Segoe UI")
            f.setPixelSize(px)
            f.setBold(fw in ("bold", "600", "700", "800", "900"))
            txt = _html.unescape(re.sub(r"(?is)&nbsp;", " ", inner))
            fm = _QFM(f)
            tw = fm.horizontalAdvance(txt)
            h = max(fm.height(), px) + pt + pb
            w = max(tw + pl + pr, h if r >= h // 2 else 0)
            k = max(2, int(math.ceil(_dpr())))
            im = QPixmap(w * k, h * k)
            im.fill(Qt.GlobalColor.transparent)
            pp = QPainter(im)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            pp.setPen(Qt.PenStyle.NoPen)
            pp.setBrush(fill)
            pp.drawRoundedRect(0, 0, w * k, h * k, min(r, h / 2.0) * k, min(r, h / 2.0) * k)
            f2 = _QFont(f)
            f2.setPixelSize(px * k)
            pp.setFont(f2)
            pp.setPen(_rd_color(_css(style, "color")) or QColor("#ffffff"))
            pp.drawText(0, 0, w * k, h * k, int(Qt.AlignmentFlag.AlignCenter), txt)
            pp.end()
            key = "mrc:///pill%d%s" % (len(_RD_RES), id(doc))
            _RD_RES[key] = 1
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), im)
            body = body[:m.start()] + '<img src="%s" width="%d" height="%d">' % (key, w, h) + body[end[1]:]
            continue
        r = min(r, 40)
        c = lambda pos: '<img src="%s" width="%d" height="%d" style="vertical-align:top;">' % (_rd_corner(doc, r, fill, line, bw, pos), r, r)
        bgattr = (' bgcolor="%s"' % fill.name()) if fill is not None and fill.alpha() > 0 else ""
        bl = ("border-%s:%dpx solid %s;" % ("%s", bw, line.name())) if line is not None and bw else ""
        side = lambda s: ('style="%s"' % (bl % s)) if bl else ""
        edge = lambda s: ('style="%sfont-size:1px;line-height:1px;"' % (bl % s if bl else ""))
        sp = 'valign="top" style="font-size:1px;line-height:1px;"'
        cpad = "padding:%dpx %dpx %dpx %dpx;" % (max(0, pt - r), max(0, pr - r), max(0, pb - r), max(0, pl - r))
        if name == "td":
            st2 = _rd_strip(style)
            tag2 = re.sub(r"""(?is)\sstyle\s*=\s*(?:"[^"]*"|'[^']*')""", (' style="%s"' % st2) if st2 else "", plain, 1)
            tag2 = re.sub(r"""(?is)\sbgcolor\s*=\s*(?:"[^"]*"|'[^']*')""", "", tag2)
            inner_w = "100%"
            core = inner
            head, tail = tag2, "</td>"
        elif name == "table":
            tag_t = re.sub(r"""(?is)\sstyle\s*=\s*(?:"[^"]*"|'[^']*')""", (' style="%s"' % _rd_strip(style)) if _rd_strip(style) else "", plain, 1)
            tag_t = re.sub(r"""(?is)\sbgcolor\s*=\s*(?:"[^"]*"|'[^']*')""", "", tag_t)
            tag_t = re.sub(r"""(?is)\swidth\s*=\s*(?:"[^"]*"|'[^']*')""", ' width="100%"', tag_t)
            core = tag_t + inner + "</table>"
            wv = _rd_attr(tag, "width") or _css(style, "width") or "100%"
            wv = wv if re.fullmatch(r"\d+%?", wv.strip()) else ("100%" if "%" in wv else re.sub(r"[^\d]", "", wv) or "100%")
            head, tail, inner_w = "", "", wv
            cpad = ""
        else:
            core = inner
            head, tail, inner_w = "", "", ("%dpx" % int(float(_css(style, "width")[:-2]))) if _css(style, "width").endswith("px") else "100%"
        al = _rd_attr(tag, "align")
        wrap = ('<table width="%s" cellspacing="0" cellpadding="0" border="0"%s>'
                '<tr><td width="%d" height="%d" %s>%s</td><td%s height="%d" valign="top" %s></td><td width="%d" %s>%s</td></tr>'
                '<tr><td width="%d"%s %s></td><td%s%s>%s</td><td width="%d"%s %s></td></tr>'
                '<tr><td width="%d" height="%d" %s>%s</td><td%s height="%d" valign="top" %s></td><td width="%d" %s>%s</td></tr></table>') % (
            inner_w, (' align="%s"' % al) if al and name == "table" else "",
            r, r, sp, c("tl"), bgattr, r, edge("top"), r, sp, c("tr"),
            r, bgattr, side("left"), bgattr, (' style="%s"' % cpad) if cpad else "", core, r, bgattr, side("right"),
            r, r, sp, c("bl"), bgattr, r, edge("bottom"), r, sp, c("br"))
        out = (head + wrap + tail) if name == "td" else wrap
        body = body[:m.start()] + out + body[end[1]:]
    return body


def mail_maxwidth(body, maxw=700):
    """Qt ignores max-width. An email that caps its column (max-width:680px) is shown in a centred column of that width."""
    body = re.sub(r"(?is)(?<![-\w])(?:line-height|font-size)\s*:\s*0(?:px|pt)?\s*(?:;|(?=[\"']))", "", body)     # zero-height lines would hide the pictures in them
    mm = re.search(r"(?is)<(?:table|td|div)\b[^>]*?(?<![-\w])max-width\s*:\s*(\d+)\s*px", body)
    lead = re.sub(r"(?is)<head\b.*?</head>|<style\b.*?</style>|<[^>]*>|&nbsp;|\s", "", body[:mm.start()]) if mm else "x"
    cols = [int(mm.group(1))] if mm and not lead and int(mm.group(1)) >= 300 else []     # only when the whole email sits in the capped column
    body = re.sub(r"(?is)(?<![-\w])max-width\s*:\s*[\d.]+\s*(?:px|%)\s*;?", "", body)
    if not cols or max(cols) >= maxw:
        return body
    n = max(cols)
    head = '<table width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td></td><td width="' + str(n + 24) + '" valign="top">'
    tail = '</td><td></td></tr></table>'
    m = re.search(r"(?is)<body\b[^>]*>", body)
    if m:
        e = body.lower().rfind("</body>")
        e = len(body) if e < 0 else e
        return body[:m.end()] + head + body[m.end():e] + tail + body[e:]
    return head + body + tail


def mail_pdf_image(data, height, maxw=None):
    """The first page of a PDF as a QImage (safe to make in a worker thread) of the given height, at most maxw wide (PyMuPDF, which the program already contains)."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        pg = doc[0]
        sc = height / float(pg.rect.height or 1)
        if maxw:
            sc = min(sc, maxw / float(pg.rect.width or 1))
        pix = pg.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        doc.close()
        return img
    except Exception:
        return QImage()


def mail_pdf_pixmap(data, height):
    """The first page of a PDF as a picture of the given height."""
    img = mail_pdf_image(data, height)
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def mail_dark(body):
    """Qt ignores the dark-mode rules (@media prefers-color-scheme) that the program's own designed emails carry, so in the dark theme they are applied by hand:
    the dark colours are written into the elements, the dark logo replaces the light one. Returns (html, page colour or None)."""
    m = re.search(r"(?is)@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)\s*\{(.*?)\n\}", body)
    if not m:
        return body, None
    rules = {}
    for cm in re.finditer(r"(?is)\.([\w-]+)\s*\{([^}]*)\}", m.group(1)):
        decl = {}
        for d in cm.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                k, v = k.strip().lower(), re.sub(r"(?i)\s*!important", "", v).strip()
                if k in ("background-color", "color", "border-color"):
                    decl[k] = v
        if decl:
            rules[cm.group(1)] = decl
    page = (rules.get("pg") or {}).get("background-color")
    body = re.sub(r"(?is)<img\b[^>]*\bclass\s*=\s*[\"']lgl[\"'][^>]*>", "", body)                   # the light-mode logo goes, the dark-mode one stays
    body = re.sub(r"(?is)(<img\b[^>]*\bclass\s*=\s*[\"']lgd[\"'][^>]*style\s*=\s*[\"'])[^\"']*(display\s*:\s*none;?|max-height\s*:\s*0;?|overflow\s*:\s*hidden;?|mso-hide\s*:\s*all;?)+", r"\1", body)

    def tag(t):
        t0 = t.group(0)
        cls = re.search(r"(?is)\bclass\s*=\s*[\"']([^\"']*)[\"']", t0)
        if not cls:
            return t0
        props = {}
        for c in cls.group(1).split():
            props.update(rules.get(c, {}))
        if not props:
            return t0
        sm = re.search(r"(?is)\bstyle\s*=\s*\"([^\"]*)\"", t0)
        sty = sm.group(1) if sm else ""
        if "border-color" in props:
            sty = re.sub(r"(?is)(border\s*:\s*[\d.]+px\s+\w+\s+)(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))", lambda q: q.group(1) + props["border-color"], sty)
        extra = "".join("%s:%s;" % (k, v) for k, v in props.items() if k != "border-color")
        sty2 = (sty.rstrip(";") + ";" if sty else "") + extra
        t1 = t0.replace(sm.group(0), 'style="%s"' % sty2, 1) if sm else t0[:-1] + ' style="%s">' % sty2
        if "background-color" in props:
            if re.search(r"(?is)\sbgcolor\s*=", t1):
                t1 = re.sub(r"(?is)(\sbgcolor\s*=\s*)(\"[^\"]*\"|'[^']*')", lambda q: q.group(1) + '"%s"' % props["background-color"], t1, 1)
            else:
                t1 = t1[:-1] + ' bgcolor="%s">' % props["background-color"]
        return t1
    body = re.sub(r"(?is)<(?:table|td|th|tr|div|span|b|p|body|a)\b[^>]*\bclass\s*=[^>]*>", tag, body)
    return body, page


def mail_trusted_image(url):
    """Gmail signature pictures live on Google's own servers; those show without asking (the 'Show pictures' button is for the rest of the web)."""
    u = url.lower()
    return u.startswith("https://") and ".googleusercontent.com/mail-sig/" in u


def mail_web_images(html):
    """The http(s) picture addresses in an email body (what 'Show pictures' would fetch)."""
    out = []
    for m in _IMG_RE.finditer(html or ""):
        u = mail_img_src(m.group(0))
        if u.lower().startswith(("http://", "https://")) and u not in out:
            out.append(u)
    return out


def _web_picture(url):
    import urllib.request as _ur
    req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/png,image/jpeg,image/gif,image/*;q=0.5"})
    with _ur.urlopen(req, timeout=6) as r:
        d = r.read(1500000)
    return d if len(d) > 200 else b""


def mail_date_text(ms, now=None):
    try:
        d = _dt.datetime.fromtimestamp(int(ms) / 1000.0)
    except Exception:
        return ""
    now = now or _dt.datetime.now()
    if d.date() == now.date():
        return d.strftime("%I:%M %p").lstrip("0")
    if d.year == now.year:
        return d.strftime("%b ") + str(d.day)
    return d.strftime("%d/%m/%Y")


_QUOTE_STARTS = (
    re.compile(r"(?is)<div[^>]+class=[\"'][^\"']*gmail_(?:quote|attr)"),
    re.compile(r"(?is)<div[^>]+id=[\"'](?:appendonsend|divRplyFwdMsg)"),
    re.compile(r"(?is)<blockquote\b"),
)


def mail_split_quote(html):
    """(new text, quoted text): a reply carries the whole earlier email under 'On ... wrote:'. The earlier email is already in the conversation above it,
    and what the sender's mail program made of it is often broken (logo gone, square corners), so it is hidden behind 'Show quoted text'."""
    if not html:
        return html, ""
    cut = None
    for rx in _QUOTE_STARTS:
        m = rx.search(html)
        if m and (cut is None or m.start() < cut):
            cut = m.start()
    if cut is None:
        return html, ""
    before = html[max(0, cut - 400):cut]
    w = list(re.finditer(r"(?is)(?:On|Op)\s[^<>]{0,140}?(?:wrote|skryf|het geskryf|schreef)\s*:", before))
    if w:
        cut = cut - len(before) + w[-1].start()                # the 'On ... wrote:' line goes with the quote
    return html[:cut], html[cut:]


def mail_full_date(m):
    """The time the email arrived, in my own time zone ('Thu, 26 Nov 2026  15:14'); the sender's Date header is in their zone and was cut short, so it read hours off."""
    try:
        return _dt.datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000.0).strftime("%a, %d %b %Y  %H:%M")
    except Exception:
        return mail_header(m, "Date")[:31]


def mail_name(addr_field):
    n, a = _parseaddr(addr_field or "")
    return (n or a.split("@")[0] or addr_field or "").strip().strip('"')


def mail_thread_row(th, me=""):
    """One row for the list from a Gmail thread (format=metadata): who, subject, snippet, date, unread, starred, count."""
    msgs = th.get("messages") or []
    if not msgs:
        return None
    me = (me or "").lower()
    names, seen = [], set()
    for m in msgs:
        fr = mail_header(m, "From")
        a = _parseaddr(fr)[1].lower()
        n = "me" if (me and a == me) else mail_name(fr)
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    last = msgs[-1]
    labels = set()
    for m in msgs:
        labels.update(m.get("labelIds") or [])
    first = msgs[0]
    unread = any("UNREAD" in (m.get("labelIds") or []) for m in msgs)
    shown = ", ".join(names[:3]) + ("" if len(names) <= 3 else " ..")
    attach = any(((m.get("payload") or {}).get("parts")) and any((p.get("filename") for p in (m.get("payload") or {}).get("parts", []))) for m in msgs)
    return {"id": th.get("id", ""), "sender": shown, "count": len(msgs), "subject": mail_header(first, "Subject") or "(no subject)",
            "snippet": _html.unescape(th.get("snippet") or last.get("snippet") or ""), "date": int(last.get("internalDate", 0) or 0), "unread": unread,
            "starred": "STARRED" in labels, "attach": attach, "labels": sorted(labels)}


def mail_label_tree(labels):
    """User labels in the order Gmail shows them: [(display name, indent, id)]; 'Clty Dev/Zandspruit' sits under 'Clty Dev'."""
    sysids = {k for k, _ in MAIL_SYSTEM} | {"IMPORTANT", "CHAT", "UNREAD", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
    out = []
    for lb in sorted([x for x in labels if x.get("type") == "user" or (x.get("id") not in sysids and not str(x.get("id", "")).startswith("CATEGORY_") and x.get("type") != "system")],
                     key=lambda x: str(x.get("name", "")).lower()):
        nm = str(lb.get("name", ""))
        out.append((nm.split("/")[-1], nm.count("/"), lb.get("id", ""), nm))
    return out


_SIGC = {}


def mail_sig_html(S):
    """My signature as the drawing register builds it: the banner cut into pieces, so the phone number, the email and the website are live links.
    Returns (html, [jpeg bytes for cid mcpsig0, mcpsig1, ...], plain text); cached until the signature settings change."""
    import sig_banner
    if not sig_banner.available(S):
        return "", [], ""
    key = tuple(str(S.get(k, "")) for k in ("sig_name", "sig_role", "sig_phone", "sig_email", "mail_address", "sig_photo", "sig_company"))
    hit = _SIGC.get(key)
    if hit:
        return hit
    rows, jp = sig_banner.slices(S)
    lt = sig_banner.link_text(S)
    web = "www.mcparchitecture.co.za"
    href = {"tel": "tel:" + lt.get("tel", ""), "mail": "mailto:" + lt.get("email", ""), "web": "https://" + web}
    alt = {"tel": lt.get("phone", ""), "mail": lt.get("email", ""), "web": web}
    tb = sig_banner.table_html(rows, href, alt, _html.escape, cap=620)
    html = '<br><table width="620" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:620px;"><tr><td style="border-radius:12px;overflow:hidden;">%s</td></tr></table>' % tb
    plain = "\n".join(x for x in (lt.get("name", ""), lt.get("role", ""), lt.get("phone", ""), lt.get("email", ""), web) if x)
    if len(_SIGC) > 4:
        _SIGC.clear()
    _SIGC[key] = (html, jp, plain)
    return _SIGC[key]


def mail_compose(S, to="", cc="", bcc="", subject="", html_body="", plain_body="", files=(), in_reply_to="", references="", signature=True, quote_html="", quote_plain="", quote_inline=None, pics=None):
    """The finished email: plain and HTML, my signature picture (or my signature lines) at the end, and the attachments."""
    msg = _EmailMessage()
    me = S.get("mail_address") or S.get("sig_email") or ""
    nm = str(S.get("sig_name", "") or "").strip()
    if me:
        msg["From"] = _formataddr((nm, me)) if nm else me
    for k, v in (("To", to), ("Cc", cc), ("Bcc", bcc)):
        if str(v).strip():
            msg[k] = v
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    sig_html, sig_jp, sig_text = "", [], ""
    if signature:
        try:
            sig_html, sig_jp, sig_text = mail_sig_html(S)
        except Exception:
            sig_html, sig_jp, sig_text = "", [], ""
        if not sig_html:
            try:
                from register_ext import signature_text
                sig_text = signature_text(S, "")
            except Exception:
                sig_text = ""
    html_full = "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#202124\">" + html_body + "</div>"
    plain_full = plain_body
    if sig_html:
        html_full += sig_html
        plain_full += "\n\n-- \n" + sig_text
    elif sig_text:
        html_full += "<br>-- <br>" + "<br>".join(_html.escape(x) for x in sig_text.split("\n"))
        plain_full += "\n\n-- \n" + sig_text
    if quote_html:                                                  # the original email goes below my text and signature, as it was sent (its pictures travel with it)
        html_full += quote_html
        plain_full += quote_plain
    msg.set_content(plain_full or " ")
    msg.add_alternative(html_full, subtype="html")
    _done = set()
    for _ref in re.findall(r"(?i)cid:([^\"'\s>)]+)", quote_html or ""):
        _data = (quote_inline or {}).get(_ref.lower())
        _kind = mail_sniff(_data) if _data else ""
        if _data and _ref.lower() not in _done and _kind in ("png", "jpeg", "gif", "webp"):
            _done.add(_ref.lower())
            msg.get_payload()[1].add_related(_data, maintype="image", subtype=_kind, cid="<%s>" % _ref, filename=_ref.split("@")[0][:40] + "." + ("jpg" if _kind == "jpeg" else _kind), disposition="inline")
    for _i, _b in enumerate(sig_jp):
        msg.get_payload()[1].add_related(_b, maintype="image", subtype="jpeg", cid="<mcpsig%d>" % _i, filename="signature%d.jpg" % _i, disposition="inline")
    for _cid, _png in (pics or {}).items():                      # pictures pasted into the message (screenshots): shown inside the email, not as attachments
        msg.get_payload()[1].add_related(_png, maintype="image", subtype="png", cid="<%s>" % _cid, filename=_cid + ".png", disposition="inline")
    import mimetypes
    for f in files:
        try:
            with open(f, "rb") as fh:
                data = fh.read()
            mt, _ = mimetypes.guess_type(f)
            mt = mt or "application/octet-stream"
            msg.add_attachment(data, maintype=mt.split("/")[0], subtype=mt.split("/")[1], filename=os.path.basename(f))
        except Exception:
            raise RuntimeError("could not read the attachment %s" % f)
    return msg


class _MailRow(_QSID):
    """One conversation in the list: checkbox, star, who, subject - snippet, date. Unread is bold and brighter, like Gmail."""
    H = 44

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def sizeHint(self, opt, idx):
        return _QSize(400, _ZSH.zn(self.H))

    def _cols(self, r):
        return QRect(r.left() + 26, r.top() + 12, 20, 20), QRect(r.left() + 56, r.top() + 10, 24, 24)

    def _st(self, opt):
        z = _ZSH.ZOOM[0]
        key = (opt.font.toString(), self.page.is_light(), z)
        if getattr(self, "_key", None) != key:
            self._key = key
            bg, fg, mute, line = self.page.colors()
            fn = _QFont(opt.font)
            fn.setBold(False)
            fb = _QFont(opt.font)
            fb.setBold(True)
            fs = _QFont(opt.font)
            for ft_ in (fn, fb, fs):                              # the row is drawn at the zoom with a transform: its fonts stay at the unzoomed size
                if z != 1.0 and ft_.pointSizeF() > 0:
                    ft_.setPointSizeF(ft_.pointSizeF() / z)
            fs.setPointSizeF(fs.pointSizeF() + 2)
            self._c = dict(fg=QColor(fg), mute=QColor(mute), line=QColor(line), red=QColor("#4aa3df"), white=QColor("#ffffff"), gold=QColor("#e0a800"),
                           pen_mute=QPen(QColor(mute), 1.4), pen_white=QPen(QColor("#ffffff"), 2), pen_line=QPen(QColor(line)),
                           rows={(u, s_, h): QColor(self.page.row_color(u, s_, h)) for u in (0, 1) for s_ in (0, 1) for h in (0, 1)})
            self._f = dict(n=fn, b=fb, star=fs, mn=_QFM(fn), mb=_QFM(fb))
        return self._c, self._f

    def paint(self, p, opt, idx):
        c, f = self._st(opt)
        r = opt.rect
        unread = bool(idx.data(ROLE_UNREAD))
        sel = bool(opt.state & QStyle_State_Selected)
        hov = bool(opt.state & QStyle_State_MouseOver)
        p.save()
        z = _ZSH.ZOOM[0]
        if z != 1.0:
            p.translate(r.topLeft())
            p.scale(z, z)
            r = QRect(0, 0, int(r.width() / z) + 1, int(r.height() / z) + 1)
        p.fillRect(r, c["rows"][(int(unread), int(sel), int(hov))])
        p.setPen(c["pen_line"])
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        cb, st = self._cols(r)
        labs = idx.data(ROLE_LABS) or []
        if labs:                                                   # one little square per label, in the label's own colour, before the tick box
            n_ = min(3, len(labs))
            sq = 9 if n_ > 1 else 12
            y0 = r.top() + (r.height() - (n_ * sq + (n_ - 1) * 2)) // 2
            p.setPen(Qt.PenStyle.NoPen)
            for k_ in range(n_):
                p.setBrush(QColor(labs[k_]))
                p.drawRoundedRect(r.left() + 8, y0 + k_ * (sq + 2), 12, sq, 2, 2)
        checked = bool(idx.data(ROLE_CHECK))
        p.setPen(c["pen_mute"])
        p.setBrush(c["red"] if checked else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(cb.adjusted(2, 2, -2, -2), 3, 3)
        if checked:
            p.setPen(c["pen_white"])
            p.drawLine(cb.left() + 6, cb.center().y(), cb.left() + 9, cb.center().y() + 3)
            p.drawLine(cb.left() + 9, cb.center().y() + 3, cb.left() + 15, cb.center().y() - 4)
        starred = bool(idx.data(ROLE_STAR))
        p.setFont(f["star"])
        p.setPen(c["gold"] if starred else c["mute"])
        p.drawText(st, Qt.AlignmentFlag.AlignCenter, "\u2605" if starred else "\u2606")
        ft, fm = (f["b"], f["mb"]) if unread else (f["n"], f["mn"])
        x0 = r.left() + 92
        wname = 190
        mid = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        p.setFont(ft)
        p.setPen(c["fg"])
        p.drawText(QRect(x0, r.top(), wname, r.height()), mid, fm.elidedText(idx.data(ROLE_SENDER) or "", Qt.TextElideMode.ElideRight, wname))
        dw = 84
        p.setPen(c["fg"] if unread else c["mute"])
        p.drawText(QRect(r.right() - dw - 12, r.top(), dw, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, idx.data(ROLE_DATE) or "")
        sx = x0 + wname + 12
        if idx.data(ROLE_CLIP):
            p.setFont(f["n"])
            p.setPen(c["mute"])
            p.drawText(QRect(sx, r.top(), 18, r.height()), mid, "\u29c9")
            sx += 20
        avail = r.right() - dw - 28 - sx
        subj = idx.data(ROLE_SUBJECT) or ""
        sw = min(fm.horizontalAdvance(subj) + 6, int(avail * 0.62))
        p.setFont(ft)
        p.setPen(c["fg"])
        p.drawText(QRect(sx, r.top(), sw, r.height()), mid, fm.elidedText(subj, Qt.TextElideMode.ElideRight, sw))
        rest = avail - sw - 10
        if rest > 30:
            p.setFont(f["n"])
            p.setPen(c["mute"])
            p.drawText(QRect(sx + sw + 10, r.top(), rest, r.height()), mid, f["mn"].elidedText("- " + (idx.data(ROLE_SNIP) or ""), Qt.TextElideMode.ElideRight, rest))
        p.restore()

    def editorEvent(self, ev, model, opt, idx):
        if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            z = _ZSH.ZOOM[0]
            rr = opt.rect
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
            if z != 1.0:
                cb, st = self._cols(QRect(0, 0, int(rr.width() / z), int(rr.height() / z)))
                pos = pos.__class__(int((pos.x() - rr.left()) / z), int((pos.y() - rr.top()) / z))
            else:
                cb, st = self._cols(rr)
            if cb.adjusted(-4, -4, 4, 4).contains(pos):
                model.setData(idx, not bool(idx.data(ROLE_CHECK)), ROLE_CHECK)
                self.page.update_bulk()
                return True
            if st.adjusted(-4, -4, 4, 4).contains(pos):
                self.page.toggle_star(idx.data(ROLE_THREAD), not bool(idx.data(ROLE_STAR)), idx.row())
                return True
        return False


from PySide6.QtWidgets import QStyle as _QStyle
QStyle_State_Selected = _QStyle.StateFlag.State_Selected
QStyle_State_MouseOver = _QStyle.StateFlag.State_MouseOver


class _AutoBrowser(_QTB):
    """A message body that is as tall as its text, so the whole conversation scrolls as one page like Gmail."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(_QF.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(_QSP.Policy.Ignored, _QSP.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(lambda *_: self._fit())

    def sizeHint(self):
        return _QSize(300, 40)

    def _image_at(self, pos):
        """The picture under the pointer: (resource name) or ''."""
        from PySide6.QtGui import QTextCursor
        c = self.cursorForPosition(pos)
        for p in (c.position(), c.position() - 1):
            if p < 0 or p + 1 >= self.document().characterCount():
                continue
            t = QTextCursor(self.document())
            t.setPosition(p)
            t.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
            f = t.charFormat()
            if f.isImageFormat():
                im = f.toImageFormat()
                if (id(self.document()), im.name()) not in _ORIG:
                    continue                                     # the decorative corner and pill pictures are not the email's pictures
                t.setPosition(p)
                r0 = self.cursorRect(t)
                w = int(im.width()) or 40
                if QRectF(r0.left() - 3, r0.top() - 3, w + 6, r0.height() + 6).contains(QPointF(pos)):
                    return im.name()
        return ""

    def contextMenuEvent(self, e):
        name = self._image_at(e.pos())
        m = self.createStandardContextMenu()
        if name:
            first = m.actions()[0] if m.actions() else None
            a_save = _QAction("Save picture as...", m)
            a_copy = _QAction("Copy picture", m)
            a_save.triggered.connect(lambda: self.save_picture(name))
            a_copy.triggered.connect(lambda: self.copy_picture(name))
            m.insertAction(first, a_save)
            m.insertAction(first, a_copy)
            m.insertSeparator(first)
        m.exec(e.globalPos())
        m.deleteLater()

    def _picture_bytes(self, name):
        return _ORIG.get((id(self.document()), name))

    def copy_picture(self, name):
        data = self._picture_bytes(name)
        im = mail_qimage(data) if data else QImage()
        if not im.isNull():
            QApplication.clipboard().setImage(im)

    def save_picture(self, name):
        import os as _os
        from PySide6.QtCore import QStandardPaths
        data = self._picture_bytes(name)
        if not data:
            return
        ext = {"jpeg": "jpg"}.get(mail_sniff(data), mail_sniff(data))
        if ext not in ("png", "jpg", "gif", "webp"):
            ext = "png"
        start = _os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or _os.path.expanduser("~"), "picture." + ext)
        fn, _f = _QFD.getSaveFileName(self, "Save picture", start, "Pictures (*.%s);;All files (*)" % ext)
        if not fn:
            return
        try:
            if ext == "png" and mail_sniff(data) != "png":       # a format the program converted: save it as a PNG
                mail_qimage(data).save(fn, "PNG")
            else:
                with open(fn, "wb") as f:
                    f.write(bytes(data))
        except Exception as ex:
            _QMB.warning(self, "Save picture", "Could not save the picture: %s" % ex)

    def minimumSizeHint(self):
        return _QSize(0, 20)

    def _fit(self):
        if self.__dict__.get("_fitting"):
            return                                       # setting the height resizes the view, which asked for another fit: one pass is enough
        w = max(200, self.viewport().width())
        doc = self.document()
        if w == self.__dict__.get("_fw") and self.__dict__.get("_fh") is not None and doc.revision() == self.__dict__.get("_frev"):
            return                                       # same width, same text: the height is already right (laying out a big table again is the slow part)
        self._fitting = True
        try:
            if w != self.__dict__.get("_fw"):
                doc.setTextWidth(w)
                self._fw = w
            self.horizontalScrollBar().setValue(0)
            h = int(doc.size().height()) + 14
            self._fh, self._frev = h, doc.revision()
            if self.height() != h:
                self.setFixedHeight(h)
        finally:
            self._fitting = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def wheelEvent(self, e):
        e.ignore()                                   # the wheel scrolls the page, not each message


class MailBody(_QTE):
    """The message box. Ctrl+V (or dropping a picture file) puts a picture, such as a marked-up screenshot, into the message itself."""

    def __init__(self, *a):
        super().__init__(*a)
        self.pics = {}                                            # name -> png bytes, for every picture in the message
        self._n = 0

    def canInsertFromMimeData(self, src):
        return src.hasImage() or self._files(src) != [] or super().canInsertFromMimeData(src)

    @staticmethod
    def _files(src):
        out = []
        if src.hasUrls():
            for u in src.urls():
                f = u.toLocalFile()
                if f and f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
                    out.append(f)
        return out

    def add_picture(self, img):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QTextImageFormat
        if img is None or img.isNull():
            return False
        self._n += 1
        name = "pasted%d.png" % self._n
        ba = QByteArray()
        bf = QBuffer(ba)
        bf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(bf, "PNG")
        self.pics[name] = bytes(ba)
        self.document().addResource(2, QUrl(name), img)           # 2 = QTextDocument.ResourceType.ImageResource
        fmt = QTextImageFormat()
        fmt.setName(name)
        w = min(img.width(), 640)                                 # shown (and sent) at most 640 px wide; the full picture travels with it
        fmt.setWidth(w)
        fmt.setHeight(img.height() * w / float(img.width()))
        self.textCursor().insertImage(fmt)
        return True

    def insertFromMimeData(self, src):
        if src.hasImage():
            img = src.imageData()
            if isinstance(img, QImage) and self.add_picture(img):
                return
        fl = self._files(src)
        if fl:
            for f in fl:
                self.add_picture(QImage(f))
            return
        super().insertFromMimeData(src)

    def paste_picture(self):
        cb = QApplication.clipboard()
        if cb.mimeData().hasImage():
            self.insertFromMimeData(cb.mimeData())
            return True
        return False


class MailCompose(_QD):
    """New email, reply, reply to all or forward, with my signature. Sends through the Gmail account that is signed in."""

    def __init__(self, page, to="", cc="", subject="", html_body="", in_reply_to="", references="", thread_id="", quote=None):
        super().__init__(page)
        self.page, self.S = page, page.S
        self.quote, self._qw = quote, 0
        self.in_reply_to, self.references, self.thread_id = in_reply_to, references, thread_id
        self.files = []
        self.setWindowTitle("New message")
        self.resize(760, 640)
        v = _VB(self)
        g = {}
        for key, lab in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc"), ("subject", "Subject")):
            row = _HB()
            l = _QL(lab)
            l.setFixedWidth(60)
            e = _QLE()
            row.addWidget(l)
            row.addWidget(e, 1)
            v.addLayout(row)
            g[key] = (l, e)
        self.to, self.cc, self.bcc, self.subject = (g[k][1] for k in ("to", "cc", "bcc", "subject"))
        self.to.setText(to)
        self.cc.setText(cc)
        self.subject.setText(subject)
        for k in ("cc", "bcc"):
            if not (cc if k == "cc" else ""):
                g[k][0].hide()
                g[k][1].hide()
        self._extra = g
        try:
            import contacts
            for le in (self.to, self.cc, self.bcc):
                contacts.attach(le, page.get_M)
        except Exception:
            pass
        bar = _HB()
        self.bcc_btn = _QPB("Cc / Bcc")
        self.bcc_btn.clicked.connect(self._show_cc)
        att = _QPB("Attach files...")
        att.clicked.connect(self._attach)
        pst = _QPB("Paste picture")
        pst.setToolTip("Paste a screenshot you copied (Win+Shift+S, then mark it up): it goes into the message. Ctrl+V in the message does the same.")
        pst.clicked.connect(self._paste_pic)
        self.sig = _QCheck("Add my signature")
        self.sig.setChecked(True)
        bar.addWidget(self.bcc_btn)
        bar.addWidget(att)
        bar.addWidget(pst)
        bar.addWidget(self.sig)
        bar.addStretch(1)
        v.addLayout(bar)
        self.att_lbl = _QL("")
        self.att_lbl.setWordWrap(True)
        v.addWidget(self.att_lbl)
        self.body = MailBody()
        self.body.setAcceptRichText(True)
        if html_body:
            self.body.setStyleSheet("QTextEdit{background:#ffffff;color:#202124;border:1px solid #d9dde2;border-radius:8px;padding:6px;}")   # a quoted email is drawn on white: typed text is dark on it
            self.body.setHtml(html_body)
            from PySide6.QtGui import QTextCursor as _TC
            self.body.moveCursor(_TC.MoveOperation.Start)
        if quote:
            # a reply: my own empty pane on top, the original email below it, drawn exactly as in the reading view (logo, rounded boxes)
            from PySide6.QtWidgets import QSplitter as _SP
            self.body.setStyleSheet("QTextEdit{background:#ffffff;color:#202124;border:1px solid #d9dde2;border-radius:8px;padding:6px;}")
            self.body.setPlaceholderText("Type your reply here")
            sp = _SP(Qt.Orientation.Vertical)
            sp.setChildrenCollapsible(False)
            sp.addWidget(self.body)
            host = QWidget()
            hv = _VB(host)
            hv.setContentsMargins(0, 0, 0, 0)
            self.quote_lbl = _QL(quote["head_html"])
            self.quote_lbl.setTextFormat(Qt.TextFormat.RichText)
            self.quote_lbl.setWordWrap(True)
            self.quote_lbl.setStyleSheet("color:#8a9099;")
            hv.addWidget(self.quote_lbl)
            self.qv = QTextBrowser()
            self.qv.setOpenLinks(False)
            self.qv.setStyleSheet("QTextBrowser{background:#ffffff;color:#202124;border:1px solid #d9dde2;border-radius:8px;padding:6px;}")
            hv.addWidget(self.qv, 1)
            sp.addWidget(host)
            sp.setStretchFactor(0, 1)
            sp.setStretchFactor(1, 3)
            sp.setSizes([170, 430])
            v.addWidget(sp, 1)
            self._rq = QTimer(self)
            self._rq.setSingleShot(True)
            self._rq.setInterval(150)
            self._rq.timeout.connect(self._requote)
        else:
            v.addWidget(self.body, 1)
        self.status = _QL("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = _HB()
        self.send_btn = _QPB("Send")
        self.send_btn.setStyleSheet("QPushButton{background:#4aa3df;color:#ffffff;font-weight:700;padding:8px 26px;border-radius:6px;}")
        self.send_btn.clicked.connect(self._send)
        cl = _QPB("Discard")
        cl.clicked.connect(self.reject)
        row.addWidget(self.send_btn)
        row.addWidget(cl)
        row.addStretch(1)
        v.addLayout(row)
        (self.body if (html_body or quote) else self.subject if to else self.to).setFocus()      # a reply starts in the empty pane above the quote

    def showEvent(self, e):
        super().showEvent(e)
        if self.quote:
            self._requote()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.quote and self.isVisible():
            self._rq.start()                                          # the quote is laid out again once the resizing stops, not at every step

    def _requote(self):
        q = self.quote
        w = max(320, self.qv.viewport().width() - 24)
        if not q or abs(w - self._qw) < 30:
            return
        self._qw = w
        self.qv.setHtml(mail_fix_images(q["html"], self.qv.document(), q["inline"], bool(self.S.get("mail_images")), w))

    def _show_cc(self):
        for k in ("cc", "bcc"):
            self._extra[k][0].show()
            self._extra[k][1].show()
        self.bcc_btn.hide()

    def _paste_pic(self):
        self.body.setFocus()
        if not self.body.paste_picture():
            self.status.setText("There is no picture on the clipboard. Copy a screenshot first (Win+Shift+S), then press this again.")
        else:
            self.status.setText("")

    def _attach(self):
        fs, _ = _QFD.getOpenFileNames(self, "Attach files")
        if fs:
            self.files += fs
            self.att_lbl.setText("Attached: " + ", ".join(os.path.basename(f) for f in self.files))

    def build(self):
        q = self.quote
        extra = {}
        if q:
            qp = q["plain"] or _html.unescape(re.sub(r"(?is)<(br|/p|/div|/tr)\b[^>]*>", "\n", re.sub(r"(?is)<(style|script)\b.*?</\1>", "", q["html"])))
            qp = re.sub(r"<[^>]+>", "", qp)
            extra = dict(quote_html="<br><div style='color:#5f6368;font-family:Arial,sans-serif;font-size:13px'>%s</div><blockquote style='margin:0 0 0 8px;border-left:2px solid #bbb;padding-left:10px'>%s</blockquote>" % (q["head_html"], q["html"]),
                         quote_plain="\n\n" + q["head_plain"] + "\n" + "\n".join("> " + x for x in qp.strip().splitlines()),
                         quote_inline=q["inline"])
        html, used = self._html(), {}
        for nm, png in self.body.pics.items():                        # pasted pictures become inline pictures of the email (cid), only those still in the text
            if re.search(r"src=[\"']%s[\"']" % re.escape(nm), html):
                cid = "mcppaste-" + nm.replace(".png", "")
                html = re.sub(r"src=([\"'])%s\1" % re.escape(nm), 'src="cid:%s"' % cid, html)
                used[cid] = png
        return mail_compose(self.S, self.to.text().strip(), self.cc.text().strip(), self.bcc.text().strip(), self.subject.text().strip(),
                            html, self.body.toPlainText(), self.files, self.in_reply_to, self.references, self.sig.isChecked(), pics=used, **extra)

    def _html(self):
        h = self.body.toHtml()
        m = re.search(r"<body[^>]*>(.*)</body>", h, re.S | re.I)
        return m.group(1) if m else h

    def _send(self):
        if not self.to.text().strip():
            self.status.setText("Type who it is for in To.")
            return
        try:
            msg = self.build()
        except Exception as e:
            self.status.setText(str(e))
            return
        self.send_btn.setEnabled(False)
        self.status.setText("Sending...")

        def work():
            from register_ext import deliver
            deliver(self.S, msg, thread_id=self.thread_id)
            return True
        self.page.run(work, self._sent)

    def _sent(self, ok, err):
        if err:
            self.send_btn.setEnabled(True)
            self.status.setText("Not sent: %s" % err)
            return
        self.accept()
        self.page.say("Sent.")
        self.page.after_send()


class MailPulse(_QW):
    """Shown while a conversation opens: the mail icon of the home screen, still, with rings that pulse out from it."""

    def __init__(self, col="#4aa3df", parent=None):
        super().__init__(parent)
        self._col = QColor(col)
        self._t = 0.0
        self.setFixedSize(180, 180)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1500)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        self._anim.start()

    def _tick(self, v):
        self._t = float(v)
        self.update()

    def hideEvent(self, e):
        self._anim.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.rect().center()
        for k in range(3):                                       # three rings, one third of a cycle apart
            t = (self._t + k / 3.0) % 1.0
            r = 28 + 62 * t
            col = QColor(self._col)
            col.setAlphaF(0.55 * (1.0 - t) ** 1.6)
            p.setPen(QPen(col, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(c.x(), c.y()), r, r)
        w, h = 46.0, 32.0                                         # the envelope
        x, y = c.x() - w / 2, c.y() - h / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._col)
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
        pen = QPen(QColor("#ffffff"), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPointF(x + 6, y + 8), QPointF(c.x(), y + h * 0.58))
        p.drawLine(QPointF(c.x(), y + h * 0.58), QPointF(x + w - 6, y + 8))
        p.end()


MAIL_ACC_COLS = ("#4aa3df", "#e2a93f", "#55b57a", "#a587e0", "#d9628f", "#f0795a", "#36b3a6", "#c08e5c")


class MailAcct:
    """The settings as one Gmail account of the Mail tab sees them: that account's own sign-in, address and change marker; everything else is shared.
    The main account (the one the rest of the program uses) is passed straight through, so nothing changes for it."""
    OWN = {"google_refresh": "refresh", "gmail_modify": "modify", "gmail_read": "read", "mail_address": "address", "mail_notify_hid": "hid"}

    def __init__(self, G, acct=None):
        self.G, self.a = G, acct

    def _own(self, k):
        return self.a is not None and not self.a.get("main") and k in self.OWN

    def get(self, k, d=None):
        if self._own(k):
            v = self.a.get(self.OWN[k])
            return d if v is None else v
        if k == "mail_provider" and self.a is not None and not self.a.get("main"):
            return "gmail"
        return self.G.get(k, d)

    def __getitem__(self, k):
        v = self.get(k, None)
        if v is None:
            raise KeyError(k)
        return v

    def __setitem__(self, k, v):
        if self._own(k):
            self.a[self.OWN[k]] = v
        else:
            self.G[k] = v

    def __contains__(self, k):
        return self.get(k, None) is not None

    def setdefault(self, k, d=None):
        if k not in self:
            self[k] = d
        return self.get(k)

    def pop(self, k, d=None):
        v = self.get(k, d)
        if self._own(k):
            self.a.pop(self.OWN[k], None)
        else:
            self.G.pop(k, None)
        return v


class _AccTile(_QF):
    """One Gmail account as a square like the ones on the home screen: a coloured initial, the address and what is waiting; click to switch, right-click for more."""

    def __init__(self, letter, line1, line2, col, active, pal, click, menu=None, photo=None):
        super().__init__()
        self._click, self._menu = click, menu
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(54)
        self.setMinimumWidth(170)
        self.setObjectName("acctile")
        h = _HB(self)
        h.setContentsMargins(10, 6, 14, 6)
        h.setSpacing(10)
        sq = _QL(letter)
        sq.setFixedSize(34, 34)
        sq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sq.setStyleSheet("background:%s;color:#ffffff;border-radius:9px;font-weight:800;font-size:16px;" % col)
        if photo is not None and not photo.isNull():
            d = _dpr()
            pm = QPixmap(int(34 * d), int(34 * d))
            pm.fill(Qt.GlobalColor.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            from PySide6.QtGui import QPainterPath as _QPP
            path = _QPP()
            path.addRoundedRect(0, 0, 34 * d, 34 * d, 9 * d, 9 * d)
            pp.setClipPath(path)
            pp.drawPixmap(0, 0, photo.scaled(int(34 * d), int(34 * d), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            pp.end()
            pm.setDevicePixelRatio(d)
            sq.setText("")
            sq.setPixmap(pm)
            sq.setStyleSheet("background:transparent;")
        sq.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lab = _QL("<b style='font-size:13px'>%s</b><br><span style='color:%s;font-size:11px'>%s</span>" % (_html.escape(line1), pal["muted"], _html.escape(line2)))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setStyleSheet("background:transparent;color:%s;" % pal["text"])
        lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        h.addWidget(sq)
        h.addWidget(lab, 1)
        import app_shell as _as
        bg = _as._mix(pal["rail"], col, 0.16) if active else pal["rail"]
        self.setStyleSheet("QFrame#acctile{background:%s;border:%s;border-radius:12px;} QFrame#acctile:hover{background:%s;}" % (
            bg, ("2px solid " + col) if active else ("1px solid " + pal["line"]), _as._mix(pal["hover"], col, 0.12)))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and self._menu:
            self._menu(e.globalPosition().toPoint())
        elif e.button() == Qt.MouseButton.LeftButton:
            self._click()


class ToastIcon(_QW):
    """The animated picture on a pop-up. kind "mail": an envelope flies in, its flap opens, a letter rises out and a badge pops with the number of new emails.
    kind "order": a price tag (the Orders card's picture) drops in on its string, swings, rings and gets ticked, with the number of new orders."""

    def __init__(self, kind, color, count=1, urgent=False, size=64, bg="#1d2025", parent=None):
        super().__init__(parent)
        self.bg = bg
        from PySide6.QtCore import QVariantAnimation
        self.kind, self.col, self.count, self.urgent = kind, QColor(color), max(0, int(count)), bool(urgent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._T = 0.0
        self._len = 3.4 if urgent else 4.4
        self._an = QVariantAnimation(self)
        self._an.setStartValue(0.0)
        self._an.setEndValue(self._len)
        self._an.setDuration(int(self._len * 1000))
        self._an.setLoopCount(-1)
        self._an.valueChanged.connect(self._tick)
        self._an.start()

    def _tick(self, v):
        self._T = float(v)
        self.update()

    @staticmethod
    def _pg(T, a, b):
        return max(0.0, min(1.0, (T - a) / float(b - a)))

    @staticmethod
    def _back(x):
        s = 1.70158
        x -= 1.0
        return 1 + (s + 1) * x ** 3 + s * x ** 2

    @staticmethod
    def _cub(x):
        return 1 - (1 - x) ** 3

    @staticmethod
    def _bounce(x):
        n1, d1 = 7.5625, 2.75
        if x < 1 / d1:
            return n1 * x * x
        if x < 2 / d1:
            x -= 1.5 / d1
            return n1 * x * x + 0.75
        if x < 2.5 / d1:
            x -= 2.25 / d1
            return n1 * x * x + 0.9375
        x -= 2.625 / d1
        return n1 * x * x + 0.984375

    def _spark(self, p, cx, cy, r, a):
        if a <= 0 or r <= 0:
            return
        c = QColor("#ffffff")
        c.setAlphaF(max(0.0, min(1.0, a)))
        p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        p.drawLine(QPointF(cx - r * .55, cy - r * .55), QPointF(cx + r * .55, cy + r * .55))
        p.drawLine(QPointF(cx - r * .55, cy + r * .55), QPointF(cx + r * .55, cy - r * .55))

    def _badge(self, p, cx, cy, pop):
        if pop <= 0:
            return
        r = 10.5 * pop
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff3b4d"))
        p.drawEllipse(QPointF(cx, cy), r, r)
        if pop > 0.6:
            f = p.font()
            f.setBold(True)
            f.setPixelSize(int(11 * min(1.0, pop)))
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(min(self.count, 99)))

    def paintEvent(self, _e):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 64.0, self.height() / 64.0)
        T, col, pg = self._T, self.col, self._pg
        g = QRadialGradient(QPointF(32, 34), 30)                          # the soft glow behind it, breathing
        gc = QColor(col)
        gc.setAlphaF(0.20 + 0.10 * math.sin(T * 2.4))
        g.setColorAt(0, gc)
        gc2 = QColor(col)
        gc2.setAlpha(0)
        g.setColorAt(1, gc2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(32, 34), 30, 30)
        if self.kind == "mail":
            self._paint_mail(p, T, col, pg)
        else:
            self._paint_order(p, T, col, pg)

    def _line_pen(self, col, w=1.6):
        return QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def _paint_mail(self, p, T, col, pg):
        """The Mail card's picture (thin line envelope, the program's icon style) that flies in, opens its flap and lifts a letter out."""
        k = self._back(pg(T, 0.0, 0.75))
        away = self._cub(pg(T, 3.7, 4.3))
        ping = pg(T, 0.55, 1.4)
        if 0 < ping < 1:
            c = QColor(col)
            c.setAlphaF(0.5 * (1 - ping))
            p.setPen(QPen(c, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(32, 36), 14 + 20 * ping, 14 + 20 * ping)
        fo = self._cub(pg(T, 0.85, 1.35)) * (1 - self._cub(pg(T, 3.3, 3.75)))
        lt = self._cub(pg(T, 1.3, 2.0)) * (1 - self._cub(pg(T, 3.2, 3.7)))
        bg = QColor(self.bg)
        p.save()
        p.translate(32 + (1 - k) * -30 + away * 40, 36 + (1 - k) * -34 - away * 6)
        p.rotate((1 - k) * -22)
        sc = max(0.05, 0.3 + 0.7 * k) * (1 - 0.6 * away) * 2.0
        p.scale(sc, sc)
        p.translate(-12, -12)
        pen = self._line_pen(col)
        p.setPen(pen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)                                   # the back
        apex = 13 - 12 * fo
        if fo > 0.02:                                                                    # the open flap
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline([QPointF(3.5, 7), QPointF(12, apex), QPointF(20.5, 7)])
        ly = 11 - 8.5 * lt                                                               # the letter, rising out
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(6.5, ly, 11, 9), 1, 1)
        p.setPen(self._line_pen(col, 1.1))
        p.drawLine(QPointF(8.7, ly + 3), QPointF(15.3, ly + 3))
        p.drawLine(QPointF(8.7, ly + 5.6), QPointF(13.2, ly + 5.6))
        poly = QPainterPath()
        poly.moveTo(3, 7.2)
        poly.lineTo(12, 13)
        poly.lineTo(21, 7.2)
        poly.lineTo(21, 19)
        poly.lineTo(3, 19)
        poly.closeSubpath()
        rr = QPainterPath()
        rr.addRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
        pocket = rr.intersected(poly)
        p.setBrush(bg)
        p.setPen(self._line_pen(col))
        p.drawPath(pocket)                                                               # the front pocket hides the letter's foot
        p.restore()
        self._badge(p, 51, 14, self._back(pg(T, 1.9, 2.4)) * (1 - away))
        for sx, sy, t0 in ((10, 14, 2.3), (54, 44, 2.7), (14, 52, 3.0)):
            ph = (T - t0) % 1.4
            if T > t0 and ph < 0.7 and away < 0.2:
                self._spark(p, sx, sy, 3 + 3 * math.sin(ph / 0.7 * math.pi), math.sin(ph / 0.7 * math.pi))

    def _paint_order(self, p, T, col, pg):
        """The Orders card's picture (thin line tag): drops in on its hole, swings, rings and gets ticked."""
        k = self._bounce(pg(T, 0.0, 0.8))
        away = self._cub(pg(T, 3.7, 4.2)) if not self.urgent else self._cub(pg(T, 2.9, 3.3))
        rate = 1.6 if self.urgent else 1.15
        sw = max(0.0, T - 0.55)
        ang = 28 * math.exp(-1.3 * sw) * math.cos(2 * math.pi * rate * sw) if T > 0.55 else 0.0
        ping = pg(T, 0.55, 1.3)
        if 0 < ping < 1:
            c = QColor(col)
            c.setAlphaF(0.55 * (1 - ping))
            p.setPen(QPen(c, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(32, 36), 12 + 22 * ping, 12 + 22 * ping)
        bg = QColor(self.bg)
        p.save()
        p.translate(32, 36 + (1 - k) * -46 - away * 46)
        p.scale(2.1, 2.1)
        p.translate(0, -1.5)
        p.rotate(ang)                                                                      # swings around the hole
        p.translate(-8.3, -8.3)
        pen = self._line_pen(col)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        from PySide6.QtSvg import QSvgRenderer
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1.4 1.4 0 0 1 0 2l-6.2 6.2a1.4 1.4 0 0 1-2 0z"/><circle cx="8.3" cy="8.3" r="1.3"/></svg>' % col.name())
        QSvgRenderer(svg.encode("utf-8")).render(p, QRectF(0, 0, 24, 24))
        tk = pg(T, 1.7, 2.3)
        if tk > 0:
            pts = [QPointF(9.3, 14.2), QPointF(11.6, 16.5), QPointF(16.2, 11.6)]
            seg1, seg2 = min(1.0, tk * 2), max(0.0, tk * 2 - 1)
            p.setPen(self._line_pen(QColor("#ffffff"), 2.1))
            p.drawLine(pts[0], QPointF(pts[0].x() + (pts[1].x() - pts[0].x()) * seg1, pts[0].y() + (pts[1].y() - pts[0].y()) * seg1))
            if seg2 > 0:
                p.drawLine(pts[1], QPointF(pts[1].x() + (pts[2].x() - pts[1].x()) * seg2, pts[1].y() + (pts[2].y() - pts[1].y()) * seg2))
        p.restore()
        self._badge(p, 52, 13, self._back(pg(T, 1.3, 1.8)) * (1 - away))
        if T > 2.3 and away < 0.2:
            ph = (T - 2.3) % 1.3
            if ph < 0.65:
                self._spark(p, 12, 16, 3 + 3 * math.sin(ph / 0.65 * math.pi), math.sin(ph / 0.65 * math.pi))


class MailToast(_QW):
    """The corner pop-up for new mail (like the orders one): who it is from, the subject and the first lines, with Open and Dismiss."""
    G = 14

    def __init__(self, rows, icon, on_open, pal=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._rows, self._open_cb = rows, on_open
        # pal: (card, text, muted, row background, accent): the mail tab's own dark or light colours
        self._pal = pal = pal or ("#1d2025", "#f2f4f6", "#aab0b8", "#2a2e35", "#4aa3df")
        self.setFixedWidth(420 + 2 * self.G)
        v = _VB(self)
        g = self.G
        v.setContentsMargins(g + 16, g + 12, g + 16, g + 12)
        v.setSpacing(8)
        top = _HB()
        n = len(rows)
        top.addWidget(ToastIcon("mail", "#4aa3df", n, size=64, bg=pal[0]))                  # an envelope that flies in, opens and shows the number of new emails
        top.addWidget(_QL("<div style='font-size:18px;font-weight:800;color:%s'>%s</div><div style='font-size:12px;color:%s'>Gmail</div>" % (
            pal[1], "New email" if n == 1 else "%d new emails" % n, pal[2])), 1)
        v.addLayout(top)
        for r in rows[:3]:
            lab = _QL("<b style='font-size:14px'>%s</b><br><span style='font-size:13px'>%s</span><br><span style='color:%s;font-size:12px'>%s</span>%s" % (
                _html.escape(r["from"]), _html.escape(r["subject"] or "(no subject)"), pal[2], _html.escape(r["snippet"]),
                ("<br><span style='color:%s;font-size:11px'>to %s</span>" % (pal[4], _html.escape(r["acct"]))) if r.get("multi") and r.get("acct") else ""))
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setStyleSheet("background:%s;color:%s;border-radius:9px;padding:8px 11px;" % (pal[3], pal[1]))
            v.addWidget(lab)
        if n > 3:
            more = _QL("and %d more..." % (n - 3))
            more.setStyleSheet("color:%s;" % pal[2])
            v.addWidget(more)
        bt = _HB()
        bt.setSpacing(8)
        for text, fn, look in (("Open", self._open, "background:%s;color:#ffffff;font-weight:800;" % pal[4]), ("Dismiss", self.close, "background:%s;color:%s;" % (pal[3], pal[1]))):
            b = _QPB(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(32)
            b.setStyleSheet("QPushButton{border:none;border-radius:8px;padding:0 18px;font-size:13px;%s}QPushButton:hover{border:2px solid %s;}" % (look, pal[1]))
            b.clicked.connect(fn)
            bt.addWidget(b)
        v.addLayout(bt)
        self.adjustSize()
        QTimer.singleShot(14000, self.close)

    def _open(self):
        try:
            self._open_cb(self._rows[0])
        finally:
            self.close()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self.G
        card = QRectF(self.rect()).adjusted(g, g, -g, -g)
        col = QColor(self._pal[4])
        for i in range(g, 0, -1):
            c = QColor(col)
            c.setAlphaF(max(0.0, 0.34 * (1 - i / float(g)) ** 1.6))
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(card.adjusted(-i, -i, i, i), 14 + i, 14 + i)
        p.setBrush(QColor(self._pal[0]))
        ec = QColor(self._pal[4])
        ec.setAlpha(190)
        p.setPen(QPen(ec, 2.2))
        p.drawRoundedRect(card, 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(card.left(), card.top() + 14, 5, card.height() - 28), 2.5, 2.5)


class MailPage(_QW):
    """The Mail tab: the Gmail account as a live, fast view with the program's own look. Sign-in uses the same Google permission as the rest of the program."""
    _done = _Signal(object, object, object)
    _signed = _Signal(bool, str)
    _added = _Signal(bool, str, object)

    def __init__(self, host, S, is_light, get_M):
        super().__init__()
        self.host, self.G, self.is_light, self.get_M = host, S, is_light, get_M
        self._main, self._acc_tag, self._accst, self._acc_sig = {"main": True}, 0, {}, None
        self._act = self._by_addr(S.get("mail_default")) or self._main          # the account marked as default is the one Mail opens on
        self.S = MailAcct(S, self._act)
        import mail_oauth
        self.mo = mail_oauth
        self.label, self.query, self.cat = "INBOX", "", 0
        self.tokens, self.gen, self.me = [""], 0, ""
        self.rows, self.labels, self.cur = [], [], None
        self.lcol = {}
        self.thread_view = None
        self._loaded = False
        self._done.connect(lambda cb, res, err: cb(res, err))
        self._signed.connect(self._after_signin)
        self._added.connect(self._after_added)
        self.setObjectName("mailpage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = _VB(self)
        root.setContentsMargins(8, 8, 8, 8)
        top = _HB()
        home = _QPB("\u2039  Home")
        home.setToolTip("Back to the start screen")
        home.clicked.connect(lambda: self.host.main_tabs.setCurrentIndex(self.host.launcher_idx[0]))
        sw = _QPB("Switch tool  \u25be")
        sw.setToolTip("Jump straight to another tool")
        sw.clicked.connect(lambda _=False, b=sw: getattr(self.host, "shell_rail").\
                           _switch_menu(b) if getattr(self.host, "shell_rail", None) is not None else None)
        top.addWidget(home)
        top.addWidget(sw)
        self.search = _QLE()
        self.search.setPlaceholderText("Search mail  (for example: from:dewann has:attachment)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._do_search)
        self.account = _QL("")
        top.addWidget(self.search, 1)
        top.addWidget(self.account)
        self.all_read_btn = _QPB("Mark all as read")
        self.all_read_btn.setToolTip("Marks every unread email in this account's inbox as read, in Gmail too, so the number on the home screen goes away")
        self.all_read_btn.clicked.connect(self.mark_all_read)
        top.addWidget(self.all_read_btn)
        self.set_btn = _QPB("Settings  \u25be")
        self.set_btn.setToolTip("Your email signature and the new-mail pop-up")
        self.set_btn.clicked.connect(self._settings_menu)
        top.addWidget(self.set_btn)
        root.addLayout(top)
        self.acc_bar = _QW()                                      # the Gmail accounts as squares, like the home screen
        self.acc_lay = _HB(self.acc_bar)
        self.acc_lay.setContentsMargins(0, 0, 0, 0)
        self.acc_lay.setSpacing(10)
        root.addWidget(self.acc_bar)
        self.connect_box = _QF()
        cv = _VB(self.connect_box)
        self.connect_msg = _QL("")
        self.connect_msg.setWordWrap(True)
        self.connect_msg.setTextFormat(Qt.TextFormat.RichText)
        self.connect_btn = _QPB("Sign in with Google and allow Gmail")
        self.connect_btn.setStyleSheet("QPushButton{background:#4aa3df;color:#ffffff;font-weight:700;padding:10px 24px;border-radius:6px;}")
        self.connect_btn.clicked.connect(self._signin)
        cv.addStretch(1)
        cv.addWidget(self.connect_msg, 0, Qt.AlignmentFlag.AlignHCenter)
        cv.addWidget(self.connect_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        cv.addStretch(2)
        root.addWidget(self.connect_box, 1)
        self.main = _QW()
        mh = _HB(self.main)
        mh.setContentsMargins(0, 0, 0, 0)
        left = _QF()
        left.setObjectName("mailside")
        left.setMinimumWidth(170)
        lv = _VB(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)
        self.compose_btn = _QPB("  Compose")
        self.compose_btn.setStyleSheet("QPushButton{background:#4aa3df;color:#ffffff;font-weight:700;font-size:14px;padding:14px 22px;border-radius:14px;text-align:left;}")
        self.compose_btn.clicked.connect(lambda: self.compose())
        lv.addWidget(self.compose_btn)
        self.side = _QLW()
        self.side.setFrameShape(_QF.Shape.NoFrame)
        self.side.setIconSize(_QSize(14, 14))
        self.side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # long label names are cut with ... instead of a sideways bar
        self.side.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.side.setVerticalScrollMode(_AIV.ScrollMode.ScrollPerPixel)
        self.side.currentItemChanged.connect(self._side_changed)
        self.side.itemClicked.connect(self._side_clicked)
        self.side.viewport().installEventFilter(self)
        self.side.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.side.customContextMenuRequested.connect(self._side_menu)
        lv.addWidget(self.side, 1)
        self.stack = _QStack()
        self.split = _QSplit(Qt.Orientation.Horizontal)
        self.split.setObjectName("mailsplit")
        self.split.setHandleWidth(12)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(left)
        self.split.addWidget(self.stack)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        w0 = int(self.S.get("mail_side_w") or 250)
        self.split.setSizes([max(170, min(w0, 520)), 1200])
        self._side_save = QTimer(self)
        self._side_save.setSingleShot(True)
        self._side_save.timeout.connect(self._save_side_width)
        self.split.splitterMoved.connect(lambda *_: self._side_save.start(500))
        mh.addWidget(self.split, 1)
        # the list page
        lp = _QW()
        lpv = _VB(lp)
        lpv.setContentsMargins(0, 0, 0, 0)
        tb = _HB()
        self.sel_all = _QCheck("Select all")
        self.sel_all.setToolTip("Tick every conversation on this page; then mark them read, archive, delete or label them in one go")
        self.sel_all.toggled.connect(self._select_all)
        tb.addWidget(self.sel_all)
        self.refresh_btn = _QPB("Refresh")
        self.refresh_btn.clicked.connect(lambda: self._force_refresh())
        self.bulk = []
        for txt, fn in (("Archive", lambda: self.act("archive")), ("Delete", lambda: self.act("trash")), ("Mark as read", lambda: self.act("read")), ("Mark as unread", lambda: self.act("unread"))):
            b = _QPB(txt)
            b.clicked.connect(fn)
            b.setVisible(False)
            self.bulk.append(b)
        lb = _QPB("Label as")
        lb.setVisible(False)
        self.label_menu = _QMenu(lb)
        self.label_menu.aboutToShow.connect(self._fill_label_menu)
        lb.setMenu(self.label_menu)
        self.bulk.append(lb)
        tb.addWidget(self.refresh_btn)
        for b in self.bulk:
            tb.addWidget(b)
        tb.addStretch(1)
        self.page_lbl = _QL("")
        self.prev = _QPB("<")
        self.next = _QPB(">")
        self.prev.setFixedWidth(34)
        self.next.setFixedWidth(34)
        self.prev.clicked.connect(self._prev)
        self.next.clicked.connect(self._next)
        tb.addWidget(self.page_lbl)
        tb.addWidget(self.prev)
        tb.addWidget(self.next)
        lpv.addLayout(tb)
        self.cats = _QTabBar()
        for _q, nm in MAIL_CATEGORIES:
            self.cats.addTab(nm)
        self.cats.setExpanding(False)
        self.cats.currentChanged.connect(self._cat_changed)
        lpv.addWidget(self.cats)
        self.list = _QLW()
        self.list.setFrameShape(_QF.Shape.NoFrame)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(_MailRow(self))
        self.list.setVerticalScrollMode(_AIV.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(self._open_item)
        self.list.itemEntered.connect(self._hover_item)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)
        self._topen = {}
        self._tlock = {}
        self._tpend = {}
        self._qopen = set()                                       # messages whose quoted text is shown
        self._lcache = {}
        self._tbusy = set()
        lpv.addWidget(self.list, 1)
        self.stack.addWidget(lp)
        # the reading page
        rp = _QW()
        rv = _VB(rp)
        rv.setContentsMargins(0, 0, 0, 0)
        rb = _HB()
        back = _QPB("← Back")
        back.clicked.connect(self._back)
        rb.addWidget(back)
        self.read_btns = {}
        for key, txt in (("archive", "Archive"), ("trash", "Delete"), ("unread", "Mark as unread"), ("reply", "Reply"), ("replyall", "Reply all"), ("forward", "Forward"), ("web", "Open in browser")):
            b = _QPB(txt)
            b.clicked.connect(lambda _=False, k=key: self._read_action(k))
            rb.addWidget(b)
            self.read_btns[key] = b
        rb.addStretch(1)
        rv.addLayout(rb)
        self.subject_lbl = _QL("")
        self.subject_lbl.setWordWrap(True)
        f = _QFont()
        f.setPointSize(16)
        self.subject_lbl.setFont(f)
        rv.addWidget(self.subject_lbl)
        self.sa = _QSA()
        self.sa.setWidgetResizable(True)
        self.sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sa.setFrameShape(_QF.Shape.NoFrame)
        self.thread_host = _QW()
        self.thread_lay = _VB(self.thread_host)
        self.thread_lay.setContentsMargins(0, 0, 8, 0)
        self.sa.setWidget(self.thread_host)
        rv.addWidget(self.sa, 1)
        self.stack.addWidget(rp)
        root.addWidget(self.main, 1)
        self.status = _QL("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.timer = QTimer(self)
        self._ntimer = QTimer(self)
        self._ntimer.timeout.connect(self._notify_tick)
        self._ntimer.start(3000)                               # asks Gmail for new mail every 3 s (one tiny call), also while another tool is open or the window is in the tray
        QTimer.singleShot(2000, self._notify_tick)
        QTimer.singleShot(5000, self._startup_warm)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1200)                                 # one tiny request about every second: new mail shows within a second or two of reaching Gmail
        self._hid = None
        self._busy = False
        self._last_full = 0.0
        self._disk_load()
        self._fill_side()
        self._refresh_state()
        self.restyle()

    # ---------------------------------------------- several Gmail accounts: squares to switch between them, one is the default
    def unread_total(self):
        """Unread emails in the inbox of every account (the home screen's Mail card shows it)."""
        n = 0
        try:
            for a in self._accounts():
                if a is getattr(self, "_act", None):
                    n += int(((getattr(self, "_counts_keep", {}) or {}).get("INBOX") or (0, 0))[0] or 0)
                else:
                    n += int(a.get("unread") or 0)
        except Exception:
            pass
        return n

    def _accounts(self):
        """[the main account (the one the whole program uses)] + the accounts added in the Mail tab."""
        self._main["address"] = str(self.G.get("mail_address") or "")
        self._main["color"] = self.G.get("mail_main_color") or MAIL_ACC_COLS[0]
        self._main["photo"] = self.G.get("mail_main_photo") or ""
        extra = [a for a in (self.G.get("mail_accounts") or []) if isinstance(a, dict) and a.get("address")]
        return [self._main] + extra

    def _accent(self):
        """The colour of the open account: the whole Mail tab is tinted with it."""
        c = (self._act or {}).get("color") or MAIL_ACC_COLS[0]
        return c if QColor(c).isValid() else MAIL_ACC_COLS[0]

    def _acc_set(self, a, **kw):
        for k, v in kw.items():
            if a.get("main"):
                self.G["mail_main_" + k] = v
            else:
                a[k] = v
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        if a is self._act:
            self.restyle()
        else:
            self._rebuild_acc_bar(True)

    def _acc_photo(self, a):
        p = a.get("photo")
        if p and os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                return pm
        return None

    def _pick_photo(self, a):
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(self, "Profile photo for " + str(a.get("address")), "", "Pictures (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not f:
            return
        im = QImage(f)
        if im.isNull():
            self.say("That picture could not be opened.")
            return
        sd = min(im.width(), im.height())
        im = im.copy((im.width() - sd) // 2, (im.height() - sd) // 2, sd, sd).scaled(
            128, 128, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        out = os.path.join(os.path.dirname(self.get_M().SETTINGS_PATH), "mail_photo_%s.png" % re.sub(r"[^a-z0-9]+", "_", str(a.get("address", "")).lower()))
        if not im.save(out, "PNG"):
            self.say("The photo could not be saved.")
            return
        self._acc_set(a, photo=out)
        self.say("Photo set for %s." % a.get("address"))

    def _by_addr(self, addr):
        addr = str(addr or "").strip().lower()
        if not addr:
            return None
        for a in self._accounts():
            if str(a.get("address", "")).lower() == addr:
                return a
        return None

    def _acc_key(self, a):
        return "main" if a.get("main") else str(a.get("address", "")).lower()

    def _acc_ready(self, a):
        S = MailAcct(self.G, a)
        return bool(self.mo.configured(S, "gmail") and self.mo.signed_in(S, "gmail") and S.get("gmail_modify"))

    def _rebuild_acc_bar(self, force=False):
        accs = self._accounts()
        pal = self._pal()
        dflt = self._by_addr(self.G.get("mail_default")) or self._main
        sig = (self._acc_key(self._act), self._acc_key(dflt), self.is_light(), tuple((a.get("address"), a.get("unread"), a.get("color"), a.get("photo")) for a in accs),
               self._counts_keep.get("INBOX") if hasattr(self, "_counts_keep") else None)
        shown = self.ready() or len(accs) > 1
        self.acc_bar.setVisible(shown)
        if sig == self._acc_sig and not force:
            return
        self._acc_sig = sig
        while self.acc_lay.count():
            it = self.acc_lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        if not shown:
            return
        for i, a in enumerate(accs):
            addr = str(a.get("address") or "")
            if not addr:
                continue
            active = a is self._act
            unread = ((getattr(self, "_counts_keep", {}) or {}).get("INBOX") or (0, 0))[0] if active else a.get("unread")
            bits = []
            if a is dflt:
                bits.append("\u2605 default")
            if unread:
                bits.append("%s unread" % unread)
            col = a.get("color") or MAIL_ACC_COLS[i % len(MAIL_ACC_COLS)]
            t = _AccTile(addr[:1].upper() or "?", addr, "  \u00b7  ".join(bits) or "inbox", col, active, pal,
                         lambda a=a: self._switch_account(a.get("address")), lambda pos, a=a: self._tile_menu(a, pos), self._acc_photo(a))
            t.setToolTip("%s\nClick to switch to this account; right-click for photo, colour and default" % addr)
            self.acc_lay.addWidget(t)
        add = _AccTile("+", "Add account", "another Gmail", "#8a9099", False, pal, self._add_account)
        add.setMinimumWidth(150)
        self.acc_lay.addWidget(add)
        self.acc_lay.addStretch(1)

    def _tile_menu(self, a, pos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Switch to this account", lambda: self._switch_account(a.get("address")))
        m.addAction("Make this my default account", lambda: self._make_default(a))
        m.addSeparator()
        m.addAction("Choose profile photo...", lambda: self._pick_photo(a))
        if a.get("photo"):
            m.addAction("Remove profile photo", lambda: self._acc_set(a, photo=""))
        cm = m.addMenu("Account colour")
        names = ("Blue", "Yellow", "Green", "Purple", "Pink", "Orange", "Teal", "Brown")
        for c, nm in zip(MAIL_ACC_COLS, names):
            cm.addAction(nm + ("  \u2713" if c == a.get("color") else ""), lambda c=c: self._acc_set(a, color=c))
        if not a.get("main"):
            m.addSeparator()
            m.addAction("Remove this account from Mail", lambda: self._remove_account(a))
        m.exec(pos)

    def _make_default(self, a):
        self.G["mail_default"] = str(a.get("address") or "")
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        self.say("%s is now the account Mail opens on." % a.get("address"))
        self._rebuild_acc_bar(True)

    _ST_KEYS = ("_topen", "_lcache", "labels", "lcol", "_hid", "_counts_keep", "me", "label", "query", "cat", "rows", "tokens")

    def _switch_account(self, addr):
        acc = self._by_addr(addr)
        if acc is None or acc is self._act:
            return
        self._accst[self._acc_key(self._act)] = {k: getattr(self, k, None) for k in self._ST_KEYS}
        self._act = acc
        self.S = MailAcct(self.G, acc)
        self._acc_tag += 1
        st = self._accst.get(self._acc_key(acc))
        fresh = dict(_topen={}, _lcache={}, labels=[], lcol={}, _hid=None, _counts_keep={}, me="", label="INBOX", query="", cat=0, rows=[], tokens=[""])
        for k in self._ST_KEYS:
            setattr(self, k, (st or fresh)[k] if (st or fresh).get(k) is not None else fresh[k])
        self._tlock, self._tpend, self._tbusy, self._qopen = {}, {}, set(), set()
        self._busy = False
        self._pw_busy, self.cur, self.thread_view, self.msgs = False, None, None, []
        self.gen += 1
        self.search.blockSignals(True)
        self.search.setText("")
        self.search.blockSignals(False)
        self.stack.setCurrentIndex(0)
        self._clear_thread()
        self.restyle()                                          # the whole Mail tab takes this account's colour
        if not st:
            self._disk_load()                                       # that account's last view from disk: mail on screen at once
        self.cats.blockSignals(True)
        self.cats.setCurrentIndex(self.cat)
        self.cats.blockSignals(False)
        self._loaded = False
        self._fill_side()
        self.rows = list(self.rows)
        hit = self._lcache.get((self.label, "", self.cat, ""))
        if hit:
            self.rows, self.next_token = list(hit[0]), hit[1]
        self._fill_list()
        self._refresh_state()
        self._rebuild_acc_bar(True)
        self.ensure_loaded()
        QTimer.singleShot(0, lambda: self.say(""))

    def _add_account(self):
        if not (self.mo.configured(self.G, "gmail") and self._main.get("address") is not None):
            return
        self.say("Waiting for Google in your browser: choose the Gmail account to add...")
        scratch = dict(self.G)                                      # the new sign-in is kept apart from the program's own account
        scratch["gmail_read"] = True
        scratch["gmail_modify"] = True
        scratch["google_refresh"] = ""
        self.mo.sign_in_thread(scratch, "gmail", "", lambda ok, m: self._added.emit(ok, m, scratch), extra_scope=self.mo.GMAIL_MODIFY, chooser=True)

    def _after_added(self, ok, msg, scratch):
        if not ok or not msg:
            self.say(msg or "adding the account did not finish", True)
            return
        addr = msg.strip().lower()
        old = self._by_addr(addr)
        if old is not None and old.get("main"):
            self.say("%s is already your main account." % addr)
            return
        lst = self.G.setdefault("mail_accounts", [])
        if old is not None:
            old["refresh"] = scratch.get("google_refresh", "")
            old["modify"], old["read"] = True, True
        else:
            used = {a.get("color") for a in self._accounts()}
            col = next((c for c in MAIL_ACC_COLS if c not in used), MAIL_ACC_COLS[len(lst) % len(MAIL_ACC_COLS)])
            lst.append({"address": addr, "refresh": scratch.get("google_refresh", ""), "modify": bool(scratch.get("gmail_modify", True)),
                        "read": True, "hid": "", "color": col})
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        self._rebuild_acc_bar(True)
        self._switch_account(addr)
        self.say("Added %s." % addr)

    def _remove_account(self, a):
        if a.get("main"):
            return
        if _QMB.question(self, "Remove account", "Remove %s from the Mail tab?\nThe mail stays in Gmail; you can add the account again later." % a.get("address")) != _QMB.StandardButton.Yes:
            return
        if a is self._act:
            self._switch_account(self._main.get("address"))
        self.G["mail_accounts"] = [x for x in (self.G.get("mail_accounts") or []) if x is not a]
        if str(self.G.get("mail_default") or "").lower() == str(a.get("address", "")).lower():
            self.G["mail_default"] = ""
        self._accst.pop(self._acc_key(a), None)
        try:
            import os as _o
            _o.remove(self._disk_path(a))
        except Exception:
            pass
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        self._rebuild_acc_bar(True)

    # ---------------------------------------------- the last mailbox view is kept on disk, so Mail opens with mail on screen at once
    def _disk_path(self, acc=None):
        import os as _o
        acc = acc or self._act
        nm = "mail_cache.json" if (acc is None or acc.get("main")) else "mail_cache_%s.json" % re.sub(r"[^a-z0-9]+", "_", str(acc.get("address", "")).lower())
        return _o.path.join(_o.path.dirname(self.get_M().SETTINGS_PATH), nm)

    def _disk_load(self):
        import json as _j
        try:
            if not self.ready():
                return
            with open(self._disk_path(), encoding="utf-8") as f:
                d = _j.load(f)
            if str(d.get("acct", "")).lower() != str(self.S.get("mail_address", "")).lower() or not d.get("acct"):
                return
            for k, v in (d.get("lists") or {}).items():
                lab, cat = k.rsplit("|", 1)
                self._lcache[(lab, "", int(cat), "")] = (v["rows"], v.get("next", ""), None)         # shown first, then checked against Gmail
            if d.get("labels"):
                self.labels = d["labels"]
                self.lcol = {x.get("id"): (x.get("color") or {}).get("backgroundColor") or MAIL_NOCOL for x in self.labels}
        except Exception:
            pass

    def _disk_soon(self):
        if getattr(self, "_dk_pend", False):
            return
        self._dk_pend = True
        QTimer.singleShot(4000, self._disk_save)

    def _disk_save(self):
        import json as _j
        self._dk_pend = False
        try:
            import os as _o0
            if not self.ready() or not self.S.get("mail_address") or (_o0.environ.get("MOT_TEST") and not getattr(self, "_disk_test", False)):
                return
            lists = {"%s|%d" % (k[0], k[2]): {"rows": v[0], "next": v[1]} for k, v in self._lcache.items() if not k[1] and not k[3]}
            tmp = self._disk_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _j.dump({"acct": str(self.S.get("mail_address", "")).lower(), "lists": lists, "labels": self.labels}, f)
            import os as _o
            _o.replace(tmp, self._disk_path())
        except Exception:
            pass

    # ----------------------------------------------------------------- look
    MAIL_BLUE = "#4aa3df"                      # the Mail card's colour on the home screen

    def _pal(self):
        """The program's palette in the Mail card's blue: selection, accents and the hot tint all follow it."""
        import app_shell
        old = app_shell.ACC[0]
        app_shell.ACC[0] = self._accent()
        try:
            return app_shell._palette(self.is_light())
        finally:
            app_shell.ACC[0] = old

    def colors(self):
        """(page, text, muted text, line) in the program's own dark or light look."""
        if self.is_light():
            return "#ffffff", "#1c1f23", "#6b727b", "#d9dde2"
        return "#1f2125", "#eceef0", "#8a9099", "#30353b"

    def restyle(self):
        p = self._pal()
        bg, fg, mute, line = self.colors()
        self.setStyleSheet(
            "#mailpage{background:%(bg)s;} #mailpage QLabel{color:%(fg)s;background:transparent;} #mailpage QCheckBox{color:%(fg)s;} "
            "#mailpage QFrame#mcard{border:1px solid %(line)s;border-radius:8px;} #mailpage QScrollArea{background:%(bg)s;border:none;} "
            "#mailpage QFrame#mailside{background:%(rail)s;border:1px solid %(pline)s;border-radius:14px;} "
            "#mailpage QSplitter::handle{background:transparent;} "
            "#mailpage QSplitter::handle:horizontal{margin:6px 4px;border-radius:2px;background:%(pline)s;} "
            "#mailpage QSplitter::handle:horizontal:hover{background:%(accent)s;} "
            "#mailpage QPushButton{background:%(rail)s;color:%(fg)s;border:1px solid %(pline)s;border-radius:10px;padding:6px 14px;min-height:20px;font-weight:500;} "
            "#mailpage QPushButton:hover{background:%(hover)s;} #mailpage QPushButton:disabled{color:%(muted)s;} "
            "#mailpage QPushButton::menu-indicator{width:0px;} "
            "#mailpage QTabBar{background:transparent;} "
            "#mailpage QTabBar::tab{background:%(rail)s;color:%(muted)s;border:1px solid %(pline)s;border-radius:10px;padding:7px 20px;margin:3px 6px 3px 0;} "
            "#mailpage QTabBar::tab:hover{background:%(hover)s;color:%(fg)s;} "
            "#mailpage QTabBar::tab:selected{background:%(sel)s;color:%(fg)s;border:1px solid %(hotline)s;font-weight:700;} "
            "#mailpage QLineEdit{background:%(rail)s;color:%(fg)s;border:1px solid %(pline)s;border-radius:10px;padding:6px 12px;} "
            "#mailpage QLineEdit:focus{border:1px solid %(accent)s;}" 
            "#mailpage QScrollBar:vertical{background:transparent;width:10px;margin:4px 2px;border:none;} "
            "#mailpage QScrollBar:horizontal{background:transparent;height:10px;margin:2px 4px;border:none;} "
            "#mailpage QScrollBar::handle:vertical{background:%(pline)s;border-radius:3px;min-height:36px;margin:0 1px;} "
            "#mailpage QScrollBar::handle:horizontal{background:%(pline)s;border-radius:3px;min-width:36px;margin:1px 0;} "
            "#mailpage QScrollBar::handle:vertical:hover,#mailpage QScrollBar::handle:horizontal:hover{background:%(accent)s;} "
            "#mailpage QScrollBar::add-line,#mailpage QScrollBar::sub-line{width:0;height:0;background:none;border:none;} "
            "#mailpage QScrollBar::add-page,#mailpage QScrollBar::sub-page{background:transparent;} "
            "#mailpage QAbstractScrollArea::corner{background:transparent;} " %
            dict(bg=bg, fg=fg, line=line, rail=p["rail"], pline=p["line"], accent=p["accent"], hover=p["hover"], muted=p["muted"], sel=p["sel"], hotline=p["hotline"]))
        self.cats.setDrawBase(False)
        self.compose_btn.setStyleSheet("QPushButton{background:%s;color:#ffffff;font-weight:700;font-size:14px;padding:14px 22px;border-radius:12px;text-align:left;border:none;} "
                                       "QPushButton:hover{background:%s;}" % (self._accent(), QColor(self._accent()).lighter(125).name()))
        self.side.setStyleSheet("QListWidget{background:transparent;color:%s;border:none;outline:0;} QListWidget::item{padding:7px 12px;border-radius:9px;} "
                                "QListWidget::item:selected{background:%s;color:%s;font-weight:700;border-left:3px solid %s;} QListWidget::item:hover{background:%s;}"
                                % (p["text"], p["sel"], p["text"], p["accent"], p["hover"]))
        self.list.setStyleSheet("QListWidget{background:%s;border:1px solid %s;border-radius:14px;outline:0;}" % (bg, p["line"]))
        self.thread_host.setStyleSheet("background:%s;" % bg)
        self.connect_box.setStyleSheet("QFrame{background:%s;border:none;}" % bg)
        self._row_cache_reset()
        self._rebuild_acc_bar(True)

    def _on_zoom(self):
        """The program's zoom changed (Ctrl + wheel): colours, rows and the open email are redrawn at the new size."""
        self.restyle()
        if self.ready() and self.list.count():
            self._fill_list()
        if self.cur and self.stack.currentIndex() == 1 and getattr(self, "msgs", None):
            self._clear_thread()
            self._render_thread()

    def _settings_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Add another Gmail account...", self._add_account)
        m.addAction("Make this account my default", lambda: self._make_default(self._act))
        m.addSeparator()
        m.addAction("My email signature...", self._edit_signature)
        w_ = m.addAction("Always show emails on white")
        w_.setCheckable(True)
        w_.setChecked(bool(self.S.get("mail_white")))
        w_.toggled.connect(self._set_white)
        a = m.addAction("Pop-up when new mail arrives")
        a.setCheckable(True)
        a.setChecked(bool(self.S.get("mail_notify", True)))
        a.toggled.connect(self._set_notify)
        m.exec(self.set_btn.mapToGlobal(self.set_btn.rect().bottomLeft()))

    def _set_white(self, on):
        self.S["mail_white"] = bool(on)
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        if self.cur and self.stack.currentIndex() == 1 and getattr(self, "msgs", None):
            self._clear_thread()
            self._render_thread()

    def _set_notify(self, on):
        self.S["mail_notify"] = bool(on)
        try:
            self.get_M().save_settings()
        except Exception:
            pass

    def _edit_signature(self):
        """The same signature editor as in the drawing register: name, position, phone, email and photo."""
        import register_ext
        M = self.get_M()
        if register_ext.SignatureDialog(M, self).exec():
            try:
                _SIGC.clear()
            except Exception:
                pass

    def _row_cache_reset(self):
        d = self.list.itemDelegate()
        if hasattr(d, "_key"):
            d._key = None
        self.list.viewport().update()

    def row_color(self, unread, sel, hov):
        if self.is_light():
            return "#dcedf9" if sel else "#e8ecf1" if hov else ("#ffffff" if unread else "#f2f4f7")
        return "#233647" if sel else "#2e3238" if hov else ("#24262b" if unread else "#1b1d21")

    def say(self, text, err=False):
        self.status.setText(("<span style='color:#e03050'>%s</span>" % _html.escape(text)) if err else _html.escape(text))
        self.status.setTextFormat(Qt.TextFormat.RichText)
        if text and not err:
            QTimer.singleShot(6000, lambda: self.status.setText("") if self.status.text() == _html.escape(text) else None)

    # --------------------------------------------------------------- plumbing
    def run(self, fn, cb, any_account=False):
        tag = self._acc_tag

        def cb2(res, err):
            if any_account or tag == self._acc_tag:                 # an answer for an account you have since left is dropped
                cb(res, err)

        def work():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, str(e)
            try:
                self._done.emit(cb2, res, err)
            except RuntimeError:
                pass                                              # the window was closed while this was running
        _th.Thread(target=work, daemon=True).start()

    def ready(self):
        return bool(self.mo.configured(self.S, "gmail") and self.mo.signed_in(self.S, "gmail") and self.S.get("gmail_modify"))

    def _refresh_state(self):
        ok = self.ready()
        self.connect_box.setVisible(not ok)
        self.main.setVisible(ok)
        if not ok:
            if not self.mo.configured(self.S, "gmail"):
                self.connect_msg.setText("<h3>Mail</h3>Gmail sign-in is not set up in this program yet (Email account, then Gmail).")
                self.connect_btn.setEnabled(False)
            elif self.mo.signed_in(self.S, "gmail"):
                self.connect_msg.setText("<h3>Mail</h3>To read and manage your mail here, press the button, sign in with Google and press Allow.<br>"
                                         "Google will say the program is not verified: press Advanced, then continue.<br>Nothing is copied to this computer; the mail stays in Gmail.")
                self.connect_btn.setEnabled(True)
            else:
                self.connect_msg.setText("<h3>Mail</h3>Sign in with Google and press Allow to read and manage your Gmail here.<br>"
                                         "Google will say the program is not verified: press Advanced, then continue.<br>Nothing is copied to this computer; the mail stays in Gmail.")
                self.connect_btn.setEnabled(True)
        else:
            self.account.setText(self.S.get("mail_address", ""))
        self._rebuild_acc_bar()

    def _signin(self):
        self.connect_btn.setEnabled(False)
        self.connect_msg.setText("<h3>Mail</h3>Waiting for Google in your browser...")
        self.mo.sign_in_thread(self.S, "gmail", self.S.get("mail_address", ""), lambda ok, m: self._signed.emit(ok, m), extra_scope=self.mo.GMAIL_MODIFY)

    def _after_signin(self, ok, msg):
        if ok:
            if msg and not self.S.get("mail_address"):
                self.S["mail_address"] = msg
            self.S["mail_provider"] = self.S.get("mail_provider") or "gmail"
            try:
                self.get_M().save_settings()
            except Exception:
                pass
        else:
            self.say(msg or "sign-in did not finish", True)
        self._refresh_state()
        if ok:
            self._loaded = False
            self.ensure_loaded()

    def showEvent(self, e):
        super().showEvent(e)
        self.restyle()
        self.ensure_loaded()

    def ensure_loaded(self):
        if self._loaded or not self.ready():
            return
        self._loaded = True
        self.load_labels()
        self.load_list(reset=True)
        self._prewarm()

    # ------------------------------------------------------------- new-mail pop-up (works while the window is hidden in the tray)
    def _notify_tick(self):
        G = self.G
        if getattr(self, "_nbusy", False) or not G.get("mail_notify", True) or self.mo.gmail_blocked():
            return
        accs = [a for a in self._accounts() if self._acc_ready(a)]
        if not accs:
            return
        self._nbusy = True
        mo = self.mo
        due = _time.time() - self.__dict__.get("_ucnt", 0) > 20          # the unread counts on the squares are refreshed every 20 s
        multi = len(self._accounts()) > 1

        def one(a):
            S = MailAcct(G, a)
            hid = S.get("mail_notify_hid")
            if not hid:
                return mo.gmail_call(S, "GET", "profile").get("historyId", ""), []
            try:
                h = mo.gmail_call(S, "GET", "history", {"startHistoryId": hid, "historyTypes": "messageAdded", "labelId": "INBOX", "maxResults": 50})
            except Exception:
                return mo.gmail_call(S, "GET", "profile").get("historyId", ""), []         # the marker was too old: start again from now
            ids = []
            for rec in h.get("history", []) or []:
                for ma in rec.get("messagesAdded", []) or []:
                    m = ma.get("message", {})
                    lb = m.get("labelIds") or []
                    if m.get("id") and "INBOX" in lb and "DRAFT" not in lb and m["id"] not in ids:          # mail you send to yourself is in the inbox too
                        ids.append(m["id"])
            rows = []
            for mid in ids[-5:]:
                try:
                    g = mo.gmail_call(S, "GET", "messages/" + mid, {"format": "metadata", "metadataHeaders": ["From", "Subject"]})
                except Exception:
                    continue
                hd = {x.get("name", "").lower(): x.get("value", "") for x in g.get("payload", {}).get("headers", [])}
                nm, ad = _parseaddr(hd.get("from", ""))
                rows.append({"from": nm or ad or "Unknown sender", "subject": hd.get("subject", ""), "snippet": _html.unescape(g.get("snippet", ""))[:150],
                             "tid": g.get("threadId", mid), "acct": str(S.get("mail_address", "")), "multi": multi})
            return h.get("historyId") or hid, rows

        def work():
            out = []
            for a in accs:                                               # every account is watched, whichever one is open
                try:
                    hid, rows = one(a)
                except Exception:
                    continue
                unread = None
                if due and a is not self._act:
                    try:
                        unread = mo.gmail_call(MailAcct(G, a), "GET", "labels/INBOX").get("threadsUnread")
                    except Exception:
                        unread = None
                out.append((a, hid, rows, unread))
            return out

        def done(res, err):
            self._nbusy = False
            if due:
                self._ucnt = _time.time()
            if err or not res:
                return
            allrows = []
            for a, hid, rows, unread in res:
                if hid:
                    MailAcct(G, a)["mail_notify_hid"] = hid
                if unread is not None:
                    a["unread"] = unread
                allrows += rows
                if rows and a is self._act:
                    for r_ in rows:
                        self._topen.pop(r_.get("tid"), None)             # the read-ahead of the other conversations stays
                    if self.isVisible() and self.label == "INBOX" and not self.query and self.stack.currentIndex() == 0:
                        self.load_labels(quiet=True)
                        self.load_list(reset=False, quiet=True)               # the new mail is in the list the moment the pop-up shows
            if allrows:
                self._show_toast(allrows)
            self._rebuild_acc_bar()
        self.run(work, done, any_account=True)

    def _show_toast(self, rows):
        try:
            w = self.window()
            if w.isActiveWindow() and self.isVisible() and self.host.main_tabs.currentWidget() is self:
                here = str(self.S.get("mail_address", "")).lower()
                rows = [r for r in rows if str(r.get("acct", "")).lower() != here]       # you are looking at this account's mail right now; another account's mail still pops up
                if not rows:
                    return
            old = getattr(self, "_toast", None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            ic = self.host.windowIcon().pixmap(64, 64) if hasattr(self.host, "windowIcon") else None
            bg_, fg_, mute_, line_ = self.colors()
            t = MailToast(rows, ic, self._toast_open, (bg_, fg_, mute_, "#2a2e35" if not self.is_light() else "#f1f3f5", self._accent()))
            self._toast = t
            ag = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            t.move(ag.right() - t.width() - 14, ag.bottom() - t.height() - 14)
            t.show()
            try:
                QApplication.alert(w, 0)
            except Exception:
                pass
        except Exception:
            pass

    def _toast_open(self, row):
        h = self.host
        try:
            h.showNormal()
            h.raise_()
            h.activateWindow()
            h.main_tabs.setCurrentWidget(self)
            if row.get("acct") and str(row["acct"]).lower() != str(self.S.get("mail_address", "")).lower():
                self._switch_account(row["acct"])                   # the mail came in on another account: open that one
            self.open_thread(row.get("tid", ""), row.get("subject", ""))
        except Exception:
            pass

    def _tick(self):
        # Gmail has no push to a desktop app, so ask for the tiny mailbox change marker every 3 s and reload only when it moves
        import time as _t0
        if self._busy and _t0.time() - getattr(self, "_busy_t", 0) > 12:
            self._busy = False                                       # an answer that never came back (account switched, line dropped) must not stop the mail from updating for good
        if self._busy or self.mo.gmail_blocked() or _t0.time() < getattr(self, "_pause", 0) or not (self.isVisible() and self.ready() and self._loaded and self.stack.currentIndex() == 0):
            return
        import time as _t
        self._busy = True
        self._busy_t = _t0.time()

        old_ = self._hid

        def work():
            cur = self.mo.gmail_call(self.S, "GET", "profile").get("historyId", "")
            tids = []
            if old_ is not None and cur and cur != old_:           # what changed: only those conversations lose their read-ahead copy
                try:
                    h = self.mo.gmail_call(self.S, "GET", "history", {"startHistoryId": old_, "historyTypes": "messageAdded", "maxResults": 100})
                    tids = [(ma.get("message") or {}).get("threadId") for rec in (h.get("history") or []) for ma in (rec.get("messagesAdded") or [])]
                except Exception:
                    tids = None                                      # the marker was too old: forget them all
            return cur, tids

        def done(res, err):
            self._busy = False
            if err or not res or not res[0]:
                return
            hid, tids = res
            changed = self._hid is not None and hid != self._hid
            self._hid = hid
            if changed:
                if tids is None:
                    self._topen.clear()
                for t_ in (tids or ()):
                    self._topen.pop(t_, None)
            if changed or _t.time() - self._last_full > 90:
                self._last_full = _t.time()
                self.load_labels(quiet=True)
                self.load_list(reset=False, quiet=True)
        self.run(work, done)

    # ------------------------------------------------------------- sidebar
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.stack.currentIndex() == 1 and getattr(self, "msgs", None) and abs(self.sa.viewport().width() - getattr(self, "_rw", 0)) > 80:
            t_ = self.__dict__.get("_rrt")
            if t_ is None:
                t_ = self._rrt = QTimer(self)
                t_.setSingleShot(True)
                t_.timeout.connect(self._rerender)
            t_.start(220)                                        # drawn again once, when the dragging stops (not every quarter second while it goes on)

    def _rerender(self):
        if self.stack.currentIndex() == 1 and getattr(self, "msgs", None) and abs(self.sa.viewport().width() - getattr(self, "_rw", 0)) > 80:
            self._clear_thread()
            self._render_thread()

    def _save_side_width(self):
        w = self.split.sizes()[0]
        if w >= 170 and w != self.S.get("mail_side_w"):
            self.S["mail_side_w"] = int(w)
            try:
                self.get_M().save_settings()
            except Exception:
                pass

    def _collapsed(self):
        if "mail_collapsed" not in self.S:                       # first time: every group starts closed
            names = {full for _n, _i, _l, full in mail_label_tree(self.labels)}
            return {n for n in names if any(o.startswith(n + "/") for o in names)}
        return set(self.S.get("mail_collapsed") or [])

    def _fill_side(self):
        self.side.blockSignals(True)
        self.side.clear()
        for lid, nm in MAIL_SYSTEM:
            it = _QLWI(nm)
            it.setData(Qt.ItemDataRole.UserRole, lid)
            it.setData(Qt.ItemDataRole.UserRole + 1, nm)
            self.side.addItem(it)
        hdr = _QLWI("Labels")
        hdr.setFlags(Qt.ItemFlag.NoItemFlags)
        f = hdr.font()
        f.setBold(True)
        hdr.setFont(f)
        self.side.addItem(hdr)
        new = _QLWI("+  Create label")
        new.setData(Qt.ItemDataRole.UserRole, "__NEW__")
        new.setData(Qt.ItemDataRole.UserRole + 1, "+  Create label")
        self.side.addItem(new)
        tree = mail_label_tree(self.labels)
        names = {full for _n, _i, _l, full in tree}
        coll = self._collapsed()
        for nm, ind, lid, full in tree:
            parts = full.split("/")
            if any("/".join(parts[:k]) in coll for k in range(1, len(parts))):
                continue                                           # a parent above it is collapsed
            has_kids = any(o.startswith(full + "/") for o in names)
            arrow = ("\u25b8 " if full in coll else "\u25be ") if has_kids else "    "
            base = "    " * ind + arrow + nm
            it = _QLWI(base)
            it.setData(Qt.ItemDataRole.UserRole, lid)
            it.setData(Qt.ItemDataRole.UserRole + 1, base)
            it.setData(Qt.ItemDataRole.UserRole + 2, full)
            it.setData(Qt.ItemDataRole.UserRole + 3, (ind, has_kids))
            it.setIcon(mail_swatch(self.lcol.get(lid, MAIL_NOCOL)))
            self.side.addItem(it)
        for i in range(self.side.count()):
            if self.side.item(i).data(Qt.ItemDataRole.UserRole) == self.label:
                self.side.setCurrentRow(i)
                break
        self.side.blockSignals(False)

    def eventFilter(self, obj, ev):
        if obj is self.side.viewport() and ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            it = self.side.itemAt(ev.position().toPoint())
            info = it.data(Qt.ItemDataRole.UserRole + 3) if it else None
            if info and info[1]:
                fm = _QFM(it.font())
                x0 = self.side.visualItemRect(it).left() + 14 + 14 + 14 + fm.horizontalAdvance("    " * info[0])          # the colour square sits in front of the text
                if x0 - 8 <= ev.position().x() <= x0 + fm.horizontalAdvance("\u25be ") + 12:
                    full = it.data(Qt.ItemDataRole.UserRole + 2)
                    coll = self._collapsed()
                    coll.symmetric_difference_update({full})
                    self.S["mail_collapsed"] = sorted(coll)
                    try:
                        self.get_M().save_settings()
                    except Exception:
                        pass
                    self._fill_side()
                    self._apply_counts()
                    return True
        return super().eventFilter(obj, ev)

    def _apply_counts(self):
        counts = getattr(self, "_counts_keep", {})
        for i in range(self.side.count()):
            it = self.side.item(i)
            lid = it.data(Qt.ItemDataRole.UserRole)
            if lid in counts:
                un, tot = counts[lid]
                n = tot if lid == "DRAFT" else un
                base = it.data(Qt.ItemDataRole.UserRole + 1)
                it.setText("%s   %d" % (base, n) if n else base)
                f = it.font()
                f.setBold(bool(un) and lid != "DRAFT")
                it.setFont(f)

    # ---- labels made here are made in Gmail itself
    def _label_dialog(self, title, name="", parent=""):
        d = _QD(self)
        d.setWindowTitle(title)
        v = _VB(d)
        v.addWidget(_QL("Label name"))
        le = _QLE(name)
        v.addWidget(le)
        cb = None
        if not name:
            v.addWidget(_QL("Put it inside"))
            cb = _QCombo()
            cb.addItem("(top level)", "")
            for _n, _i, _l, full in mail_label_tree(self.labels):
                cb.addItem(full, full)
            if parent:
                k = cb.findData(parent)
                cb.setCurrentIndex(max(0, k))
            v.addWidget(cb)
        cc = None
        if not name:
            v.addWidget(_QL("Colour"))
            cc = _QPB("No colour  (press to choose)")
            cc._hx = ""

            def choose(_=False, cc=cc):
                hx = mail_pick_color(d, cc._hx)
                if hx is not None:
                    cc._hx = hx
                    cc.setIcon(mail_swatch(hx) if hx else _QIcon())
                    cc.setText("Colour chosen" if hx else "No colour  (press to choose)")
            cc.clicked.connect(choose)
            v.addWidget(cc)
        row = _HB()
        row.addStretch(1)
        ok = _QPB("Create" if not name else "Rename")
        no = _QPB("Cancel")
        ok.clicked.connect(d.accept)
        no.clicked.connect(d.reject)
        ok.setDefault(True)
        row.addWidget(no)
        row.addWidget(ok)
        v.addLayout(row)
        if d.exec() != _QD.DialogCode.Accepted or not le.text().strip():
            return None
        self._dlg_col = cc._hx if cc else ""
        return le.text().strip().replace("/", "-"), (cb.currentData() if cb else "")

    def new_label(self, parent=""):
        r = self._label_dialog("Create label", "", parent)
        if not r or self._need_modify():
            return
        full = (r[1] + "/" if r[1] else "") + r[0]
        col = getattr(self, "_dlg_col", "")

        def work():
            body = {"name": full, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
            if col:
                body["color"] = {"backgroundColor": col, "textColor": mail_text_on(col)}
            return self.mo.gmail_call(self.S, "POST", "labels", body=body)

        def done(res, err):
            if err:
                self.say(err, True)
                return
            self.say("Label created in Gmail: " + full)
            self.load_labels(quiet=True)
        self.run(work, done)

    def _side_menu(self, pos):
        it = self.side.itemAt(pos)
        full = it.data(Qt.ItemDataRole.UserRole + 2) if it else None
        if not full:
            return
        lid = it.data(Qt.ItemDataRole.UserRole)
        m = _QMenu(self)
        a1 = m.addAction("New label inside it")
        a2 = m.addAction("Rename")
        a3 = m.addAction("Delete label")
        a4 = m.addAction(mail_swatch(self.lcol.get(lid, MAIL_NOCOL)), "Colour...")
        act = m.exec(self.side.viewport().mapToGlobal(pos))
        if act is a4:
            hx = mail_pick_color(self, self.lcol.get(lid, ""))
            if hx and not self._need_modify():
                self.run(lambda: self.mo.gmail_call(self.S, "PUT", "labels/" + lid, body={"id": lid, "name": full, "color": {"backgroundColor": hx, "textColor": mail_text_on(hx)}}),
                         lambda res, err: (self.say(err, True) if err else (self.say("Colour changed in Gmail"), self.load_labels(quiet=True))))
            return
        if act is a1:
            self.new_label(full)
        elif act is a2:
            r = self._label_dialog("Rename label", full.split("/")[-1])
            if r and not self._need_modify():
                newfull = "/".join(full.split("/")[:-1] + [r[0]])
                self.run(lambda: self.mo.gmail_call(self.S, "PUT", "labels/" + lid, body={"id": lid, "name": newfull}),
                         lambda res, err: (self.say(err, True) if err else (self.say("Renamed in Gmail"), self.load_labels(quiet=True))))
        elif act is a3:
            if _QMB.question(self, "Delete label", "Delete the label '%s' in Gmail? The emails stay, they just lose this label." % full) == _QMB.StandardButton.Yes and not self._need_modify():
                self.run(lambda: self.mo.gmail_call(self.S, "DELETE", "labels/" + lid),
                         lambda res, err: (self.say(err, True) if err else (self.say("Label deleted in Gmail"), self.load_labels(quiet=True))))

    def _label_cols(self, ids):
        user = {l for _n, _i, l, _f in mail_label_tree(self.labels)}
        return [self.lcol.get(i, MAIL_NOCOL) for i in (ids or []) if i in user]

    def _row_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        tid = it.data(ROLE_THREAD)
        ids = self.checked_ids() if it.data(ROLE_CHECK) else [tid]
        rows = {r["id"]: r for r in self.rows}
        have = set.intersection(*[set((rows.get(t) or {}).get("labels") or []) for t in ids]) if ids else set()
        m = _QMenu(self)
        a_open = m.addAction("Open")
        m.addSeparator()
        a_read = m.addAction("Mark as read")
        a_unr = m.addAction("Mark as unread")
        a_star = m.addAction("Star / unstar")
        m.addSeparator()
        lm = m.addMenu("Label as")
        tree = mail_label_tree(self.labels)
        acts = {}
        for nm, ind, lid, full in tree:
            a = lm.addAction(mail_swatch(self.lcol.get(lid, MAIL_NOCOL)), full)
            a.setCheckable(True)
            a.setChecked(lid in have)
            acts[a] = (lid, full)
        if tree:
            lm.addSeparator()
        a_new = lm.addAction("Create new label...")
        m.addSeparator()
        a_proj = m.addAction("Create a project from this mail") if (len(ids) == 1 and getattr(self.host, "board_page", None) is not None) else None
        m.addSeparator()
        a_arc = m.addAction("Archive")
        a_del = m.addAction("Delete")
        act = m.exec(self.list.viewport().mapToGlobal(pos))
        if act is None:
            return
        if act is a_open:
            self.open_thread(tid, it.data(ROLE_SUBJECT) or "")
        elif act is a_read:
            self.act("read", ids)
        elif act is a_unr:
            self.act("unread", ids)
        elif act is a_star:
            on = not bool(it.data(ROLE_STAR))
            for t in ids:
                r_ = self._row_of(t)
                if r_ >= 0:
                    self.toggle_star(t, on, r_)
        elif a_proj is not None and act is a_proj:
            self.project_from_mail(rows.get(tid) or {"subject": it.data(ROLE_SUBJECT) or ""})
        elif act is a_arc:
            self.act("archive", ids)
        elif act is a_del:
            self.act("trash", ids)
        elif act is a_new:
            self.new_label()
        elif act in acts:
            lid, full = acts[act]
            if lid in have:
                self.modify(ids, remove=[lid], cb=lambda: self.say("Removed " + full))
            else:
                self.modify(ids, add=[lid], cb=lambda: self.say("Labelled " + full))

    def project_from_mail(self, r):
        """A new project filled in from what the mail is about: its subject, who it is from, an erf number, urgency and a date if it names one."""
        bp = getattr(self.host, "board_page", None)
        if bp is None:
            return
        subj = re.sub(r"^\s*((re|fw|fwd|aw)\s*:\s*)+", "", str(r.get("subject") or ""), flags=re.I).strip()
        who = str(r.get("from") or "").strip()
        snip = str(r.get("snippet") or "").strip()
        blob = subj + " " + snip
        erf = re.search(r"\b(erf|stand|lot|plot)\s*(no\.?)?\s*(\d{1,6})\b", blob, re.I)
        client = " · ".join(x for x in (who if who != "Unknown sender" else "", ("Erf " + erf.group(3)) if erf else "") if x)
        pr = "urgent" if re.search(r"\b(urgent|urgently|asap|immediately|emergency)\b", blob, re.I) else ("high" if re.search(r"\b(today|deadline|tomorrow|by (monday|tuesday|wednesday|thursday|friday))\b", blob, re.I) else "normal")
        due = None
        d = re.search(r"\b(20\d\d)[-/](\d\d)[-/](\d\d)\b", blob)
        if d:
            due = "%s-%s-%s" % d.groups()
        title = subj or ("Mail from " + who if who else "New project")
        notes = "From: %s\nSubject: %s\n\n%s\n\n(Created from a mail on %s)" % (who, subj, snip, _btime.strftime("%Y-%m-%d"))
        row = {"title": title[:140], "client": client or None, "priority": pr, "due": due, "notes": notes, "status": "todo"}
        try:
            self.host.main_tabs.setCurrentWidget(bp)
        except Exception:
            pass
        bp.edit(row, "todo")

    def _fill_label_menu(self):
        self.label_menu.clear()
        tree = mail_label_tree(self.labels)
        if not tree:
            self.label_menu.addAction("No labels yet").setEnabled(False)
        for nm, ind, lid, full in tree:
            a = self.label_menu.addAction(mail_swatch(self.lcol.get(lid, MAIL_NOCOL)), full)
            a.triggered.connect(lambda _=False, lid=lid, full=full: self.modify(self.checked_ids() or ([self.cur] if self.cur else []), add=[lid],
                                                                              cb=lambda: self.say("Labelled " + full)))
        self.label_menu.addSeparator()
        self.label_menu.addAction("Create new label...").triggered.connect(lambda: self.new_label())

    def _side_clicked(self, it):
        lid = it.data(Qt.ItemDataRole.UserRole)
        if lid in (None, "__NEW__") or lid != self.label:
            return                                           # a different label is handled by _side_changed
        if self.query:
            self.search.clear()
            self.query = ""
            self.stack.setCurrentIndex(0)
            self.load_list(reset=True)
        elif self.stack.currentIndex() == 1:
            self._back()                                      # Inbox clicked again while reading: back to the list

    def _side_changed(self, cur, _prev):
        if cur is None or cur.data(Qt.ItemDataRole.UserRole) is None:
            return
        if cur.data(Qt.ItemDataRole.UserRole) == "__NEW__":
            self.side.blockSignals(True)
            for i in range(self.side.count()):
                if self.side.item(i).data(Qt.ItemDataRole.UserRole) == self.label:
                    self.side.setCurrentRow(i)
            self.side.blockSignals(False)
            self.new_label()
            return
        self.label = cur.data(Qt.ItemDataRole.UserRole)
        self.search.clear()
        self.query = ""
        self.stack.setCurrentIndex(0)
        self.load_list(reset=True)

    def load_labels(self, quiet=False):
        def work():
            labs = self.mo.gmail_call(self.S, "GET", "labels").get("labels", [])
            prof = {}
            try:
                prof = self.mo.gmail_call(self.S, "GET", "profile")
            except Exception:
                pass
            counts = {}
            ids = ["INBOX", "DRAFT"] + ([] if quiet else [x["id"] for x in labs if x.get("type") == "user"][:40])
            for lid in ids:
                try:
                    j = self.mo.gmail_call(self.S, "GET", "labels/" + lid)
                    counts[lid] = (int(j.get("threadsUnread", 0) or 0), int(j.get("threadsTotal", 0) or 0))
                except Exception:
                    pass
            return labs, prof.get("emailAddress", ""), counts, prof.get("historyId", "")

        def done(res, err):
            if err:
                if not quiet:
                    self.say(err, True)
                return
            labs, me, counts, hid0 = res
            if self._hid is None and hid0:
                self._hid = hid0
            if me:
                self.me = me.lower()
            counts = dict(getattr(self, "_counts_keep", {}), **counts)
            self._counts_keep = counts
            QTimer.singleShot(0, self._rebuild_acc_bar)
            sg = lambda ls: [(x.get("id"), x.get("name"), (x.get("color") or {}).get("backgroundColor")) for x in ls]
            if sg(labs) != sg(self.labels):
                self.labels = labs
                self.lcol = {x.get("id"): (x.get("color") or {}).get("backgroundColor") or MAIL_NOCOL for x in labs}
                self._disk_soon()
                self._fill_side()
                for i in range(self.list.count()):
                    it = self.list.item(i)
                    r_ = self.rows[i] if i < len(self.rows) else None
                    if r_:
                        it.setData(ROLE_LABS, self._label_cols(r_.get("labels")))
                self.list.viewport().update()
            self._apply_counts()
        self.run(work, done)

    # ---------------------------------------------------------------- list
    def _do_search(self):
        self.query = self.search.text().strip()
        self.stack.setCurrentIndex(0)
        self.load_list(reset=True)

    def _cat_changed(self, i):
        self.cat = i
        if self.label == "INBOX" and not self.query:
            self.load_list(reset=True)

    def _prev(self):
        if len(self.tokens) > 1:
            self.tokens.pop()
            self.load_list(reset=False, keep_tokens=True)

    def _next(self):
        if self.next_token:
            self.tokens.append(self.next_token)
            self.load_list(reset=False, keep_tokens=True)

    next_token = ""

    def load_list(self, reset=True, quiet=False, keep_tokens=False):
        if not self.ready():
            return
        if reset:
            self.tokens = [""]
        self.gen += 1
        gen = self.gen
        tok = self.tokens[-1] if self.tokens else ""
        label, query, cat = self.label, self.query, self.cat
        self.cats.setVisible(label == "INBOX" and not query)
        key = (label, query, cat, tok)
        hit = self._lcache.get(key)
        if hit and not quiet:
            self.rows, self.next_token = list(hit[0]), hit[1]
            self._fill_list()                                   # show what we had at once
            if hit[2] is not None and hit[2] == self._hid:
                self.say("")
                return                                          # nothing changed in the mailbox since: no request at all
        elif not quiet:
            self.say("Loading...")

        def work():
            return self._page(label, query, cat, tok)

        def done(res, err):
            if gen != self.gen:
                return
            if err:
                self.say(err, True)
                return
            ths, nxt = res
            rows = [r for r in (mail_thread_row(t, self.me) for t in ths if t) if r]
            sig = lambda rs: [(r["id"], r["unread"], r["starred"], r["count"], r["snippet"]) for r in rs]
            same = sig(rows) == sig(self.rows) and nxt == self.next_token and self.list.count() == len(rows)
            self.next_token = nxt
            self.rows = rows
            self._lcache[key] = (list(rows), nxt, self._hid)
            self._disk_soon()
            if len(self._lcache) > 40:
                self._lcache.pop(next(iter(self._lcache)))
            if not same:
                self._fill_list()
            self.say("")
        self.run(work, done)

    def _force_refresh(self):
        """The Refresh button: always asks Gmail again (no cached list, no 'nothing changed' shortcut), folders and counts too."""
        if not self.ready():
            return
        self._lcache.clear()
        self._topen.clear()
        self._busy = False
        self._last_full = _time.time()
        self.load_labels(quiet=True)
        self.load_list(reset=False)

    def _startup_warm(self):
        # the mailbox is read in the background as the program starts, so the first time you open Mail it is already there
        if self.ready() and not self._loaded:
            self.load_labels(quiet=True)
            self._prewarm(500)

    def _prewarm(self, delay=2500):
        """Load the first page of every folder in the background, so switching folders shows its mail at once."""
        if getattr(self, "_pw_busy", False) or not self.ready():
            return
        self._pw_busy = True

        def work():
            import time as _tp
            self.mo.background(True)                                 # it never queues in front of what you click on
            _tp.sleep(delay / 1000.0)
            jobs = [("SENT", "", 0), ("DRAFT", "", 0), ("STARRED", "", 0)] + [("INBOX", "", i) for i in range(1, len(MAIL_CATEGORIES))] + [("INBOX", "", 0), ("ALL", "", 0)]
            for lab, q, c in jobs:
                key = (lab, q, c, "")
                if key in self._lcache:
                    continue
                if self.mo.gmail_load() > 0.6 or self.mo.gmail_blocked():
                    break                                           # never take the quota the user is using
                try:
                    ths, nxt = self._page(lab, q, c, "")
                    rows = [r for r in (mail_thread_row(t, self.me) for t in ths if t) if r]
                    self._lcache[key] = (rows, nxt, self._hid)
                except Exception:
                    break                                           # busy: carry on another time
            self.mo.background(False)
            return True
        self.run(work, lambda res, err: (setattr(self, "_pw_busy", False), self._disk_soon()))

    def _page(self, label, query, cat, tok):
        """One page of the list as Gmail thread records (also used to load the other folders ahead of time)."""
        params = {"maxResults": 25}
        q = query
        if query:
            params["includeSpamTrash"] = "false"
        else:
            if label == "ALL":
                pass
            elif label in ("TRASH", "SPAM"):
                params["labelIds"] = [label]
                params["includeSpamTrash"] = "true"
            else:
                params["labelIds"] = [label]
            if label == "INBOX":
                cat = max(0, min(cat, len(MAIL_CATEGORIES) - 1))
                if cat == 0:                                   # Primary is everything that is not in another tab: mail you send to yourself has no tab label and would be lost
                    params["labelIds"] = ["INBOX"]
                    q = "-category:promotions -category:social -category:updates -category:forums"
                else:
                    params["labelIds"] = ["INBOX", MAIL_CATEGORIES[cat][0]]
        if q:
            params["q"] = q
        if tok:
            params["pageToken"] = tok
        j = self.mo.gmail_call(self.S, "GET", "threads", params)
        ids = [t["id"] for t in j.get("threads", []) or []]
        snips = {t["id"]: t.get("snippet", "") for t in j.get("threads", []) or []}
        hids = {t["id"]: t.get("historyId", "") for t in j.get("threads", []) or []}
        cache = self.__dict__.setdefault("_tcache", {})
        out = [None] * len(ids)
        import threading as _thr

        def one(i):
            try:
                hit = cache.get(ids[i])
                if hit and hids.get(ids[i]) and hit[0] == hids[ids[i]]:
                    out[i] = hit[1]
                    return
                th = self.mo.gmail_call(self.S, "GET", "threads/" + ids[i], {"format": "metadata", "metadataHeaders": ["From", "Subject"]})
                th["snippet"] = snips.get(ids[i], "") or th.get("snippet", "")
                out[i] = th
                cache[ids[i]] = (hids.get(ids[i], ""), th)
                if len(cache) > 600:
                    cache.pop(next(iter(cache)))
            except Exception:
                out[i] = None
        need = [i for i in range(len(ids)) if not (cache.get(ids[i]) and hids.get(ids[i]) and cache[ids[i]][0] == hids[ids[i]])]
        if len(need) > 1 and hasattr(self.mo, "gmail_batch"):            # all the missing conversations in ONE request
            try:
                got = self.mo.gmail_batch(self.S, ["threads/%s?format=metadata&metadataHeaders=From&metadataHeaders=Subject" % ids[i] for i in need])
            except Exception:
                got = None
            if got:
                for i, th in zip(need, got):
                    if th:
                        th["snippet"] = snips.get(ids[i], "") or th.get("snippet", "")
                        cache[ids[i]] = (hids.get(ids[i], ""), th)
        if self.mo.gmail_blocked():
            raise RuntimeError("Gmail's per-minute limit was reached; it carries on by itself in %d seconds" % (self.mo.gmail_blocked() + 1))
        nxt = [0]
        lock = _thr.Lock()

        def worker():
            while True:
                with lock:
                    i = nxt[0]
                    nxt[0] += 1
                if i >= len(ids):
                    return
                one(i)
        ws = [_thr.Thread(target=worker) for _ in range(min(12, len(ids)))]
        for w in ws:
            w.start()
        for w in ws:
            w.join()
        return out, j.get("nextPageToken", "")

    def _fill_list(self):
        sel = self.cur
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for r in self.rows:
            it = _QLWI()
            who = r["sender"] + (" %d" % r["count"] if r["count"] > 1 else "")
            it.setData(ROLE_THREAD, r["id"])
            it.setData(ROLE_SENDER, who)
            it.setData(ROLE_SUBJECT, r["subject"])
            it.setData(ROLE_SNIP, r["snippet"])
            it.setData(ROLE_DATE, mail_date_text(r["date"]))
            it.setData(ROLE_UNREAD, r["unread"])
            it.setData(ROLE_STAR, r["starred"])
            it.setData(ROLE_CHECK, False)
            it.setData(ROLE_CLIP, r["attach"])
            it.setData(ROLE_LABS, self._label_cols(r.get("labels")))
            it.setSizeHint(_QSize(400, _ZSH.zn(_MailRow.H)))
            self.list.addItem(it)
        self.list.setUpdatesEnabled(True)
        n = len(self.rows)
        start = (len(self.tokens) - 1) * 25 + 1
        self.page_lbl.setText("%d-%d" % (start, start + n - 1) if n else "No conversations")
        self.prev.setEnabled(len(self.tokens) > 1)
        self.next.setEnabled(bool(self.next_token))
        self.sel_all.blockSignals(True)
        self.sel_all.setChecked(False)
        self.sel_all.blockSignals(False)
        self.update_bulk()
        QTimer.singleShot(400, self._prefetch)

    def checked_ids(self):
        return [self.list.item(i).data(ROLE_THREAD) for i in range(self.list.count()) if self.list.item(i).data(ROLE_CHECK)]

    def update_bulk(self):
        on = bool(self.checked_ids())
        for b in self.bulk:
            b.setVisible(on)
        self.list.viewport().update()

    def _select_all(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setData(ROLE_CHECK, bool(on))
        self.update_bulk()

    def _row_of(self, tid):
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_THREAD) == tid:
                return i
        return -1

    # ----------------------------------------------------------- actions
    def _need_modify(self):
        if self.S.get("gmail_modify"):
            return False
        self.say("Press Allow Gmail again: changing mail needs one more permission.", True)
        self._refresh_state()
        return True

    def _local_apply(self, tids, add, remove, trash):
        """Show the change at once, on the screen and in every kept list, before Gmail has even been asked."""
        ts = set(tids)
        add, remove = set(add), set(remove)
        for key, ent in list(self._lcache.items()):
            lab = key[0]
            keep = []
            for r_ in ent[0]:
                if r_["id"] in ts:
                    if trash and lab not in ("TRASH", "ALL"):
                        continue
                    if (lab in remove) or (lab in ("STARRED", "UNREAD") and lab in remove):
                        continue
                    ls = (set(r_.get("labels") or []) | add) - remove
                    r_ = dict(r_, labels=sorted(ls), unread="UNREAD" in ls, starred="STARRED" in ls)
                keep.append(r_)
            self._lcache[key] = (keep, ent[1], ent[2])
        if not trash:
            for r_ in self.rows:
                if r_["id"] in ts:
                    ls = (set(r_.get("labels") or []) | add) - remove
                    r_["labels"] = sorted(ls)
                    r_["unread"] = "UNREAD" in ls
                    r_["starred"] = "STARRED" in ls
                    k_ = self._row_of(r_["id"])
                    if k_ >= 0:
                        self.list.item(k_).setData(ROLE_LABS, self._label_cols(r_["labels"]))
            self.list.viewport().update()
        for t in ts:
            self._topen.pop(t, None)

    def modify(self, tids, add=(), remove=(), trash=False, cb=None):
        if self._need_modify() or not tids:
            return
        tids = list(dict.fromkeys(tids))
        self._local_apply(tids, add, remove, trash)                 # instant: the screen does not wait for Gmail
        if cb:
            cb()
        q = list(tids)
        lk = _th.Lock()
        errs = []

        def call(t):
            if trash:
                self.mo.gmail_call(self.S, "POST", "threads/%s/trash" % t, body={})
            else:
                self.mo.gmail_call(self.S, "POST", "threads/%s/modify" % t, body={"addLabelIds": list(add), "removeLabelIds": list(remove)})

        def worker():
            while True:
                with lk:
                    if not q:
                        return
                    t = q.pop(0)
                try:
                    call(t)
                except Exception as e:
                    try:
                        call(t)                                     # one more try
                    except Exception as e2:
                        errs.append(str(e2) or str(e))

        def work():
            ws = [_th.Thread(target=worker) for _ in range(min(8, len(tids)))]       # many at once, not one after the other
            for w in ws:
                w.start()
            for w in ws:
                w.join()
            if errs:
                raise RuntimeError(errs[0])
            return True

        def done(res, err):
            if err:
                self._lcache.clear()
                self.say("Gmail did not accept the change (%s); the list is being reloaded" % err, True)
                self.load_list(reset=False, quiet=True)
                return
            self.load_labels(quiet=True)                           # the counts next to the folders
            self._disk_soon()
        self.run(work, done)

    def mark_all_read(self):
        """Every unread email in the inbox of this account becomes read (all of them, not only the ones on screen)."""
        if self._need_modify():
            return
        c = dict(getattr(self, "_counts_keep", {}) or {})
        old = c.get("INBOX") or (0, 0)
        c["INBOX"] = (0, old[1])
        self._counts_keep = c                                       # the numbers go at once; Gmail follows
        for r_ in self.rows:
            r_["unread"] = False
            r_["labels"] = [x for x in (r_.get("labels") or []) if x != "UNREAD"]
        for key, ent in list(self._lcache.items()):
            for r_ in ent[0]:
                r_["unread"] = False
                r_["labels"] = [x for x in (r_.get("labels") or []) if x != "UNREAD"]
        self.list.viewport().update()
        try:
            self._rebuild_acc_bar(force=True)
        except Exception:
            pass
        self.say("Marking all unread mail as read...")

        def work():
            n, tok = 0, None
            while True:
                prm = {"labelIds": ["INBOX", "UNREAD"], "maxResults": 500}
                if tok:
                    prm["pageToken"] = tok
                res = self.mo.gmail_call(self.S, "GET", "messages", params=prm) or {}
                ids = [m["id"] for m in (res.get("messages") or [])]
                if ids:
                    self.mo.gmail_call(self.S, "POST", "messages/batchModify", body={"ids": ids, "removeLabelIds": ["UNREAD"]})
                    n += len(ids)
                tok = res.get("nextPageToken")
                if not tok or n > 20000:
                    return n

        def done(res, err):
            if err:
                self.say("Gmail did not accept it (%s)" % err, True)
            else:
                self.say("Marked %d email%s as read" % (res, "" if res == 1 else "s"))
            self._lcache.clear()
            self.load_list(reset=False, quiet=True)
            self.load_labels(quiet=True)
        self.run(work, done)

    def toggle_star(self, tid, on, row):
        it = self.list.item(row)
        if it is None:
            return
        it.setData(ROLE_STAR, on)
        self.list.viewport().update()
        self.modify([tid], add=["STARRED"] if on else [], remove=[] if on else ["STARRED"])

    def act(self, what, ids=None):
        ids = ids or self.checked_ids() or ([self.cur] if self.cur else [])
        if not ids:
            return

        def removed():
            for t in ids:
                r = self._row_of(t)
                if r >= 0:
                    self.list.takeItem(r)
            self.rows = [x for x in self.rows if x["id"] not in ids]
            self.update_bulk()
        if what == "archive":
            self.modify(ids, remove=["INBOX"], cb=removed)
        elif what == "trash":
            self.modify(ids, trash=True, cb=removed)
        elif what in ("read", "unread"):
            def flip():
                for t in ids:
                    r = self._row_of(t)
                    if r >= 0:
                        self.list.item(r).setData(ROLE_UNREAD, what == "unread")
                        self.list.item(r).setData(ROLE_CHECK, False)
                self.update_bulk()
            self.modify(ids, add=["UNREAD"] if what == "unread" else [], remove=[] if what == "unread" else ["UNREAD"], cb=flip)

    # ------------------------------------------------------------- reading
    def _open_item(self, it):
        if self.list.viewport().mapFromGlobal(QCursor.pos()).x() < 88:
            return                                  # that click was on the tick box or the star
        tid = it.data(ROLE_THREAD)
        self.open_thread(tid, it.data(ROLE_SUBJECT) or "")
        if it.data(ROLE_UNREAD):
            it.setData(ROLE_UNREAD, False)
            self.modify([tid], remove=["UNREAD"])

    def _fetch_thread(self, tid):
        hit = self._topen.get(tid)
        if hit and _time.time() - hit[0] < 900:
            return hit[1]
        lk = self._tlock.setdefault(tid, _th.Lock())
        got = lk.acquire(timeout=3)                                        # a click on a conversation that is being fetched waits for it, but never for long
        try:
            hit = self._topen.get(tid)
            if hit and _time.time() - hit[0] < 900:
                return hit[1]
            out = self._fetch_thread2(tid)
            try:
                for r_ in out[1]:
                    mail_warm(r_[4])                                 # the pictures that came with the text are decoded here, not while the email opens
            except Exception:
                pass
            return out
        finally:
            if got:
                lk.release()

    def _fetch_thread2(self, tid):
        th = self.mo.gmail_call(self.S, "GET", "threads/" + tid, {"format": "full"})
        res = []
        todo = []
        for m in th.get("messages", []) or []:
            html, plain, atts = mail_parts(m.get("payload"))
            refs = {x.lower() for x in re.findall(r"(?i)cid:([^\"'\s>)]+)", html or "")}
            inline = {}
            for a in atts:
                if a["cid"] and a["cid"].lower() in refs and a["size"] < 12000000:
                    if a["data"]:
                        inline[a["cid"].lower()] = mail_b64(a["data"])
                    else:
                        todo.append((inline, a["cid"].lower(), lambda p="messages/%s/attachments/%s" % (m["id"], a["id"]): self.mo.gmail_bytes(self.S, p)))
            for u in mail_web_images(html)[:8]:
                if self.S.get("mail_images") or mail_trusted_image(u):
                    todo.append((inline, "url:" + u, lambda u=u: _web_picture(u)))
            res.append((m, html, plain, atts, inline))

        out = (th, res)
        self._topen[tid] = (_time.time(), out)
        if len(self._topen) > 30:
            self._topen.pop(next(iter(self._topen)))
        if todo:
            self._tpend[tid] = todo                                  # the pictures come after the text: the email opens at once
        return out

    def _thread_images(self, tid):
        """Phase two of opening: the inline pictures and web pictures, fetched in parallel. True when something was added."""
        lk0 = self._tlock.setdefault("img:" + tid, _th.Lock())
        busy = lk0.locked()                                          # another worker (the read-ahead) is already on it: wait for it, then show
        with lk0:
            todo = self._tpend.pop(tid, None)
            if not todo:
                return busy

            def get(t):
                for k in (0, 1):
                    try:
                        v = t[2]()
                        if v:
                            t[0][t[1]] = v
                        break
                    except Exception as e:
                        if k:
                            t[0]["err:" + t[1]] = str(e)[:80]
            q = list(todo[:60])
            lk = _th.Lock()

            def worker():
                while True:
                    with lk:
                        if not q:
                            return
                        t = q.pop()
                    get(t)
            ws = [_th.Thread(target=worker) for _ in range(min(10, len(q)))]
            for w in ws:
                w.start()
            for w in ws:
                w.join()
            try:
                for t in todo:
                    mail_warm(t[0])
            except Exception:
                pass
            return True

    def _retry_pictures(self):
        self._topen.pop(self.cur, None)
        self._tpend.pop(self.cur, None)
        if self.cur:
            self.open_thread(self.cur, self.subject_lbl.text())

    def _show_pictures(self):
        self.S["mail_images"] = True
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        self._topen.clear()
        if self.cur:
            self.open_thread(self.cur, self.subject_lbl.text())

    def _prefetch(self):
        """The conversations of the list on screen are loaded in the background (four at a time, newest first), so a click opens from memory."""
        ids = [r["id"] for r in self.rows[:25] if r["id"] not in self._topen and r["id"] not in self._tbusy]
        if not ids or not self.ready():
            return
        self._tbusy.update(ids)
        q = list(ids)
        lk = _th.Lock()
        stop = []

        def worker():
            self.mo.background(True)
            while not stop:
                with lk:
                    if not q:
                        return
                    t = q.pop(0)
                try:
                    if self.mo.gmail_load() > 0.6 or self.mo.gmail_blocked():
                        stop.append(1)
                        return                                        # never spend the quota the user needs
                    self._fetch_thread(t)
                    self._thread_images(t)
                except Exception:
                    stop.append(1)
                    return

        def work():
            ws = [_th.Thread(target=worker, daemon=True) for _ in range(4)]
            for w in ws:
                w.start()
            for w in ws:
                w.join()
            return True
        self.run(work, lambda res, err: self._tbusy.difference_update(ids))

    def _hover_item(self, it):
        # start fetching a conversation as soon as the pointer rests on it, so the click opens it from memory
        tid = it.data(ROLE_THREAD)
        if not tid or tid in self._topen or tid in self._tbusy or not self.ready() or self.mo.gmail_load() > 0.5 or self.mo.gmail_blocked():
            return

        def go():
            if self.list.itemAt(self.list.viewport().mapFromGlobal(QCursor.pos())) is not it or tid in self._tbusy:
                return
            self._tbusy.add(tid)

            def done(res, err):
                self._tbusy.discard(tid)
            self.run(lambda: (self._fetch_thread(tid), self._thread_images(tid)), done)
        QTimer.singleShot(40, go)

    def _slow_open(self, tid, subject):
        """Opening takes more than ten seconds: say so and offer a retry, instead of spinning for ever."""
        if self.cur != tid or self.stack.currentIndex() != 1 or getattr(self, "msgs", None) and self.thread_lay.count() > 3:
            return
        if not any(isinstance(self.thread_lay.itemAt(i).widget(), MailPulse) for i in range(self.thread_lay.count())):
            return
        lb = _QL("Gmail is slow or busy right now.")
        rb = _QPB("Try again")
        rb.clicked.connect(lambda: (self._topen.pop(tid, None), self.open_thread(tid, subject)))
        self.thread_lay.insertWidget(self.thread_lay.count() - 1, lb, 0, Qt.AlignmentFlag.AlignHCenter)
        self.thread_lay.insertWidget(self.thread_lay.count() - 1, rb, 0, Qt.AlignmentFlag.AlignHCenter)

    def _later_images(self, tid):
        """The text is already on screen; fetch the pictures and show them as they arrive (the view keeps its place)."""
        lk = self._tlock.get("img:" + tid)
        if tid not in self._tpend and not (lk and lk.locked()):
            return                                                   # nothing left to fetch

        def done(res, err):
            if err or not res or tid != self.cur or self.stack.currentIndex() != 1:
                return
            hit = self._topen.get(tid)
            if not hit:
                return
            sb = self.sa.verticalScrollBar()
            pos = sb.value()
            self.thread_view, self.msgs = hit[1]
            self._clear_thread()
            self._render_thread()
            QTimer.singleShot(0, lambda: sb.setValue(pos))
        self.run(lambda: self._thread_images(tid), done)

    def open_thread(self, tid, subject=""):
        if tid != self.cur:
            self._qopen = set()
        self.cur = tid
        self.stack.setCurrentIndex(1)
        self.subject_lbl.setText(subject)
        self._clear_thread()
        hit = self._topen.get(tid)
        if hit and _time.time() - hit[0] < 900:                       # already in memory: shown at once, no waiting and no flicker
            self.thread_view, self.msgs = hit[1]
            self._render_thread()
            self._later_images(tid)
            return
        self.thread_lay.addStretch(1)
        self.thread_lay.addWidget(MailPulse(self._accent()), 0, Qt.AlignmentFlag.AlignHCenter)
        self.thread_lay.addStretch(1)
        QTimer.singleShot(10000, lambda: self._slow_open(tid, subject))

        def work():
            out = self._fetch_thread(tid)
            if len(self._tpend.get(tid) or ()) <= 6:                 # a few pictures (a logo): given a moment to come with the text, so the email is drawn once and does not jump
                _w = _th.Thread(target=lambda: self._thread_images(tid), daemon=True)
                _w.start()
                _w.join(0.7)                                         # slower than that: the text goes first and the pictures follow
            return out

        _t_open = _time.time()

        def done(res, err):
            if tid != self.cur:
                return
            self._clear_thread()
            if err:
                self.thread_lay.addWidget(_QL("Could not open it: " + err))
                return
            self.say("Opened in %.1f s (Gmail)" % (_time.time() - _t_open))
            th, msgs = res
            self.thread_view = th
            self.msgs = msgs
            self._render_thread()
            self._later_images(tid)
        self.run(work, done)

    def _clear_thread(self):
        while self.thread_lay.count():
            w = self.thread_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()

    def _render_thread(self):
        self.thread_host.setUpdatesEnabled(False)                       # the page is drawn once, finished, not piece by piece
        try:
            self._render_thread2()
        finally:
            self.thread_host.setUpdatesEnabled(True)
            QTimer.singleShot(0, self._refit_all)

    def _show_quote(self, mid):
        self._qopen.add(mid)
        sb = self.sa.verticalScrollBar()
        pos = sb.value()
        self._clear_thread()
        self._render_thread()
        QTimer.singleShot(0, lambda: sb.setValue(pos))

    def _refit_all(self):
        for b in self.thread_host.findChildren(_AutoBrowser):
            b._fit()

    def _render_thread2(self):
        self._rw = self.sa.viewport().width()
        bg, fg, mute, line = self.colors()
        n = len(self.msgs)
        for i, (m, html, plain, atts, inline) in enumerate(self.msgs):
            card = _QF()
            card.setStyleSheet("QFrame#mcard{border:1px solid %s;border-radius:8px;}" % line)
            card.setObjectName("mcard")
            cv = _VB(card)
            fr = mail_header(m, "From")
            to = mail_header(m, "To")
            cc = mail_header(m, "Cc")
            hd = _QL("<b>%s</b> &lt;%s&gt; &nbsp; <span style='color:%s'>%s</span><br><span style='color:%s'>to %s%s</span>" % (
                _html.escape(mail_name(fr)), _html.escape(_parseaddr(fr)[1]), mute, _html.escape(mail_full_date(m)), mute,
                _html.escape(to or "me"), _html.escape(("   cc " + cc) if cc else "")))
            hd.setTextFormat(Qt.TextFormat.RichText)
            hd.setWordWrap(True)
            hd.setMinimumWidth(0)
            hd.setSizePolicy(_QSP.Policy.Ignored, _QSP.Policy.Preferred)
            cv.addWidget(hd)
            b = _AutoBrowser()
            body = html
            cut_q = False
            if i > 0 and html and m["id"] not in self._qopen:
                _hd, _qt = mail_split_quote(html)
                if _qt:
                    body, cut_q = _hd, True
                    if not re.sub(r"(?is)<[^>]+>|&nbsp;|\s", "", _hd):
                        body = "<p style='color:#8a9099'>(no new text)</p>"
            page_bg = None
            if body:
                body = re.sub(r"(?is)<(script|iframe|object|embed|link)\b.*?(</\1>|/>)", "", body)
                body = re.sub(r"(?is)<script.*?>.*?</script>", "", body)
            else:
                body = "<pre style='font-family:Arial;white-space:pre-wrap'>%s</pre>" % _html.escape(plain or m.get("snippet", ""))
            # designed emails stay on a soft light page (as the sender made them); simple ones wear the program's dark look
            page_bg, fgc, dark_mail = "#ffffff", "#202124", False
            if not self.is_light() and not self.S.get("mail_white") and mail_plain(html):
                body = mail_lighten(body)
                page_bg, fgc, dark_mail = "#25282d", "#eceef0", True
            b.setStyleSheet("QTextBrowser{background:%s;color:%s;border-radius:6px;padding:6px;}" % (page_bg, fgc))
            b.document().setDefaultStyleSheet("a{color:%s;}" % ("#7cb7f0" if dark_mail else "#1a5fb4"))
            if self.S.get("mail_white"):
                b.setStyleSheet("QTextBrowser{background:#ffffff;color:#202124;border-radius:6px;padding:6px;}")
            body = mail_fix_images(body, b.document(), inline, bool(self.S.get("mail_images")), max(320, self.sa.viewport().width() - 90))
            hidden = [] if self.S.get("mail_images") else [u for u in mail_web_images(html) if not mail_trusted_image(u)]
            if hidden:
                bar = _QPB("Show pictures from the web in this email")
                bar.clicked.connect(self._show_pictures)
                cv.addWidget(bar)
            b.resize(max(300, self.sa.viewport().width() - 60), 40)          # its real width before the text goes in, so it is the right height at once
            b.setHtml(body)
            b._fit()
            cv.addWidget(b)
            if cut_q:
                qb = _QPB("Show quoted text")
                qb.setToolTip("The earlier email this one replies to (it is in the conversation above)")
                qb.clicked.connect(lambda _=False, mid=m["id"]: self._show_quote(mid))
                cv.addWidget(qb, 0, Qt.AlignmentFlag.AlignLeft)
            if self._tpend.get(self.cur) or (lk_ := self._tlock.get("img:" + str(self.cur))) and lk_.locked():
                wl = _QL("Loading pictures...")
                wl.setStyleSheet("color:%s;" % mute)
                cv.addWidget(wl)
            elif any(k.startswith("err:") for k in inline):
                rb = _QPB("Some pictures did not load - try again")
                rb.clicked.connect(self._retry_pictures)
                cv.addWidget(rb)
            used = {x.lower() for x in re.findall(r"(?i)cid:([^\"'\s>)]+)", html or "")}
            files = [a for a in atts if a["name"] and not (a["cid"] and a["cid"].lower() in used)]
            if files:
                avail = max(300, self.sa.viewport().width() - 70)
                prev = [a for a in files if self._previewable(a)][:60]
                pids = {id(a) for a in prev}
                others = [a for a in files if id(a) not in pids]
                tools = _HB()
                if len(files) >= 2:
                    sa_ = _QPB("Save all (%d)" % len(files))
                    sa_.setToolTip("Save every attachment of this email into one folder you choose (it remembers the folder)")
                    sa_.clicked.connect(lambda _=False, fl=files, mid=m["id"]: self._save_all(mid, fl))
                    tools.addWidget(sa_)
                tools.addStretch(1)
                cv.addLayout(tools)
                if prev:                                               # PDFs and pictures: previews that fit the window; click one to open or save it
                    cv.addWidget(self._thumb_grid(m["id"], prev, avail))
                if others:                                             # other files stay buttons, wrapped onto as many rows as the width needs
                    fmb = _QFM(self.font())
                    rows, cur, used_w = [], [], 0
                    for a in others[:60]:
                        nm = a["name"] if len(a["name"]) <= 30 else a["name"][:27] + "..."
                        txt = "%s  (%s)" % (nm, ("%.1f MB" % (a["size"] / 1048576.0)) if a["size"] > 1048576 else ("%d KB" % max(1, a["size"] // 1024)))
                        w_ = fmb.horizontalAdvance(txt) + 44
                        if cur and used_w + w_ > avail:
                            rows.append(cur)
                            cur, used_w = [], 0
                        cur.append((txt, a))
                        used_w += w_ + 6
                    if cur:
                        rows.append(cur)
                    for rw in rows:
                        row = _HB()
                        for txt, a in rw:
                            bt = _QPB(txt)
                            bt.setToolTip(a["name"])
                            bt.clicked.connect(lambda _=False, a=a, mid=m["id"]: self._save_attachment(mid, a))
                            row.addWidget(bt)
                        row.addStretch(1)
                        cv.addLayout(row)
            self.thread_lay.addWidget(card)
        self.thread_lay.addStretch(1)

    @staticmethod
    def _previewable(a):
        mime, nm = a.get("mime", ""), a["name"].lower()
        return (mime in ("image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp") or mime == "application/pdf" or nm.endswith(".pdf")) and a["size"] < 25000000

    def _att_bytes(self, mid, a):
        """An attachment's bytes: from memory when it was fetched before (a preview, an earlier open), otherwise from Gmail."""
        key = (mid, a.get("id") or a["name"])
        c = self.__dict__.setdefault("_attc", {})
        hit = c.get(key)
        if hit is not None and hit[0] is not None:
            return hit[0]
        data = mail_b64(a["data"]) if a.get("data") else self.mo.gmail_bytes(self.S, "messages/%s/attachments/%s" % (mid, a["id"]))
        if len(c) > 80:
            c.clear()
        c[key] = (data, hit[1] if hit else None)
        return data

    def _thumb_grid(self, mid, prev, avail):
        """Previews of the PDFs and pictures, wrapped to the window's width; they load at once, several at a time. Click one: Open or Save."""
        from PySide6.QtWidgets import QGridLayout
        tid = self.cur
        d = _dpr()
        CW, TH = 140, 104
        cols = max(1, (avail + 8) // (CW + 8))
        host = QWidget()
        g = QGridLayout(host)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        btns = []
        fm = _QFM(self.font())
        for i, a in enumerate(prev):
            cell = QWidget()
            cl = _VB(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            b = _QPB("...")
            b.setFlat(True)
            b.setFixedSize(CW, TH)
            b.setIconSize(QSize(CW - 8, TH - 8))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(a["name"] + "  (click to open or save)")
            b.clicked.connect(lambda _=False, a=a, b=b: self._thumb_menu(mid, a, b))
            nm = _QL(fm.elidedText(a["name"], Qt.TextElideMode.ElideMiddle, CW))
            nm.setFixedWidth(CW)
            nm.setStyleSheet("font-size:11px;color:#8a9099;")
            cl.addWidget(b)
            cl.addWidget(nm)
            g.addWidget(cell, i // cols, i % cols)
            btns.append(b)
        c = self.__dict__.setdefault("_attc", {})

        def show(b, img):
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(d)
            b.setText("")
            b.setIcon(_QIcon(pm))
        todo = []
        for a, b in zip(prev, btns):
            hit = c.get((mid, a.get("id") or a["name"]))
            if hit and hit[1] is not None:
                show(b, hit[1])
            else:
                todo.append((a, b))
        if todo:
            q = list(reversed(todo))
            lk = _th.Lock()

            def worker():
                while True:
                    with lk:
                        if not q:
                            return
                        a, b = q.pop()
                    img = QImage()
                    try:
                        data = self._att_bytes(mid, a)
                        isp = a.get("mime") == "application/pdf" or a["name"].lower().endswith(".pdf")
                        img = mail_pdf_image(data, int((TH - 8) * d), int((CW - 8) * d)) if isp else mail_qimage(data)
                        if not img.isNull() and not isp:
                            img = img.scaled(int((CW - 8) * d), int((TH - 8) * d), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        key = (mid, a.get("id") or a["name"])
                        if not img.isNull() and key in c:
                            c[key] = (c[key][0], img)
                    except Exception:
                        img = QImage()
                    try:
                        self._done.emit(lambda r, e, b=b, img=img: self._thumb_done(tid, b, img, show), None, None)
                    except RuntimeError:
                        return
            for _ in range(min(6, len(q))):
                _th.Thread(target=worker, daemon=True).start()
        return host

    def _thumb_done(self, tid, b, img, show):
        if self.cur != tid or self.stack.currentIndex() != 1:
            return
        try:
            if img.isNull():
                b.setText("preview not available")
            else:
                show(b, img)
        except RuntimeError:
            pass                                                      # the email was closed before the preview arrived

    def _thumb_menu(self, mid, a, b):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Open", lambda: self.run(lambda: self._att_bytes(mid, a), lambda res, err: self._open_bytes(a["name"], res) if not err else self.say(err, True)))
        m.addAction("Save as...", lambda: self._save_attachment(mid, a))
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _thumbs(self, mid, imgs, lay, btn=None):
        """Small previews of picture attachments, fetched in the background; click one to open it."""
        tid = self.cur

        def work():
            out = []
            for a in imgs:
                try:
                    data = mail_b64(a["data"]) if a.get("data") else self.mo.gmail_bytes(self.S, "messages/%s/attachments/%s" % (mid, a["id"]))
                    out.append((a, data))
                except Exception:
                    continue
            return out

        def done(res, err):
            if err or not res or self.cur != tid or self.stack.currentIndex() != 1:
                return
            try:
                for a, data in res:
                    pm = mail_pdf_pixmap(data, int(130 * _dpr())) if (a["mime"] == "application/pdf" or a["name"].lower().endswith(".pdf")) else mail_pixmap(data)
                    if pm.isNull():
                        continue
                    d = _dpr()
                    pm2 = pm.scaledToHeight(int(110 * d), Qt.TransformationMode.SmoothTransformation) if pm.height() != int(110 * d) else pm
                    if pm2.width() > 260 * d:
                        pm2 = pm2.scaledToWidth(int(260 * d), Qt.TransformationMode.SmoothTransformation)
                    pm2.setDevicePixelRatio(d)
                    b = _QPB()
                    b.setIcon(_QIcon(pm2))
                    b.setIconSize(pm2.deviceIndependentSize().toSize())
                    b.setFlat(True)
                    b.setToolTip(a["name"] + "  (click to open)")
                    b.setCursor(Qt.CursorShape.PointingHandCursor)
                    b.clicked.connect(lambda _=False, a=a, data=data: self._open_bytes(a["name"], data))
                    lay.insertWidget(lay.count() - 1, b)
                if btn is not None:
                    btn.hide()
            except RuntimeError:
                pass                                                      # the email was closed before the previews arrived
        self.run(work, done)

    def _open_bytes(self, name, data):
        import tempfile
        d = tempfile.mkdtemp(prefix="mailatt_")
        path = os.path.join(d, re.sub(r"[\\/:*?\"<>|]", "_", name) or "attachment")
        with open(path, "wb") as f:
            f.write(data)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _save_all(self, mid, files):
        start = self.S.get("mail_save_dir") or os.path.join(os.path.expanduser("~"), "Downloads")
        dest = _QFD.getExistingDirectory(self, "Save all attachments to", start)
        if not dest:
            return
        self.S["mail_save_dir"] = dest
        try:
            self.get_M().save_settings()
        except Exception:
            pass
        self.say("Downloading %d attachment%s..." % (len(files), "" if len(files) == 1 else "s"))

        def work():
            names, lock, errs, saved = set(), _th.Lock(), [], []

            def one(a):
                try:
                    data = self._att_bytes(mid, a)
                    base, ext = os.path.splitext(re.sub(r"[\\/:*?\"<>|]", "_", a["name"]) or "attachment")
                    with lock:
                        nm, k = base + ext, 1
                        while nm.lower() in names or os.path.exists(os.path.join(dest, nm)):
                            k += 1
                            nm = "%s (%d)%s" % (base, k, ext)
                        names.add(nm.lower())
                    with open(os.path.join(dest, nm), "wb") as f:
                        f.write(data)
                    saved.append(nm)
                except Exception as e:
                    errs.append(str(e))
            ts = []
            for a in files:
                while len([t for t in ts if t.is_alive()]) >= 4:
                    _time.sleep(0.02)
                t = _th.Thread(target=one, args=(a,), daemon=True)
                t.start()
                ts.append(t)
            for t in ts:
                t.join()
            return len(saved), errs
        def done(res, err):
            if err:
                self.say(err, True)
                return
            n, errs = res
            self.say("Saved %d of %d attachments to %s%s" % (n, len(files), dest, ("  (" + errs[0] + ")") if errs else ""), bool(errs))
            if n and not os.environ.get("MOT_TEST"):
                QDesktopServices.openUrl(QUrl.fromLocalFile(dest))
        self.run(work, done)

    def _save_attachment(self, mid, a):
        dest, _ = _QFD.getSaveFileName(self, "Save attachment", os.path.join(os.path.expanduser("~"), "Downloads", a["name"]))
        if not dest:
            return
        self.say("Downloading %s..." % a["name"])

        def work():
            data = self._att_bytes(mid, a)
            with open(dest, "wb") as f:
                f.write(data)
            return dest
        self.run(work, lambda res, err: self.say(("Saved " + res) if not err else err, bool(err)))

    def _back(self):
        self.stack.setCurrentIndex(0)
        self.cur = None

    def _read_action(self, key):
        if key in ("archive", "trash", "unread"):
            if self.cur:
                self.act(key, [self.cur])
            self._back()
        elif key == "web":
            self._open_web()
        elif key in ("reply", "replyall", "forward"):
            self._reply(key)

    def _open_web(self):
        if not getattr(self, "msgs", None):
            return
        import tempfile
        import webbrowser
        m, html, plain, atts, inline = self.msgs[-1]
        body = html or "<pre>%s</pre>" % _html.escape(plain)
        for cid, data in inline.items():
            body = body.replace("cid:" + cid, "data:image/png;base64," + _b64.b64encode(data).decode())
        p = os.path.join(tempfile.mkdtemp(prefix="mailview_"), "message.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write("<meta charset='utf-8'>" + body)
        webbrowser.open("file:///" + p.replace("\\", "/"))

    def _reply(self, kind):
        if not getattr(self, "msgs", None):
            return
        m, html, plain, atts, inline = self.msgs[-1]
        subj = mail_header(m, "Subject")
        fr = mail_header(m, "Reply-To") or mail_header(m, "From")
        me = (self.S.get("mail_address") or self.me or "").lower()
        sent_by_me = _parseaddr(mail_header(m, "From"))[1].lower() == me
        to = mail_header(m, "To") if sent_by_me else fr
        cc = ""
        if kind == "replyall":
            others = [a for a in _getaddr([mail_header(m, "To"), mail_header(m, "Cc")]) if a[1] and a[1].lower() != me and a[1].lower() != _parseaddr(fr)[1].lower()]
            cc = ", ".join(_formataddr(a) for a in others)
        pre = "Fwd: " if kind == "forward" else "Re: "
        subj2 = subj if re.match(r"(?i)\s*(re|fwd?):", subj) else pre + subj
        when = mail_date_text(m.get("internalDate", 0))
        quote = html or "<pre style='font-family:Arial;white-space:pre-wrap'>%s</pre>" % _html.escape(plain or "")
        quote = re.sub(r"(?is)<(script|iframe|object|embed|link)\b.*?(</\1>|/>)", "", quote)
        if kind == "forward":
            hd_ = [("From", mail_header(m, "From")), ("Date", mail_header(m, "Date")), ("Subject", subj), ("To", mail_header(m, "To"))]
            head_html = "---------- Forwarded message ----------<br>" + "<br>".join("%s: %s" % (k_, _html.escape(v_)) for k_, v_ in hd_)
            head_plain = "---------- Forwarded message ----------\n" + "\n".join("%s: %s" % x for x in hd_)
            to = ""
        else:
            head_html = "On %s, %s wrote:" % (_html.escape(when), _html.escape(mail_name(mail_header(m, "From"))))
            head_plain = "On %s, %s wrote:" % (when, mail_name(mail_header(m, "From")))
        q_ = dict(html=quote, plain=plain or "", inline=inline, head_html=head_html, head_plain=head_plain)
        d = MailCompose(self, to, cc, subj2, "", in_reply_to=mail_header(m, "Message-ID") or mail_header(m, "Message-Id"),
                        references=mail_header(m, "References"), thread_id="" if kind == "forward" else (self.thread_view or {}).get("id", ""), quote=q_)
        d.exec()

    def compose(self):
        MailCompose(self).exec()

    def after_send(self):
        self._topen.pop(self.cur, None)
        if self.label == "SENT" or self.label == "INBOX":
            self.load_list(reset=False, quiet=True)


# ================================================================================================ Projects: a live board shared with a team
"""Projects: a live board shared with the people you invite (To do / In progress / Done), kept in your own Supabase database.
Everyone signs in with their own email; what one person adds or moves shows on the others' screens within a couple of seconds."""
import time as _btime
import urllib.error as _uerr
import urllib.parse as _uparse
import urllib.request as _ureq
from PySide6.QtCore import QDate
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget)

BROLE = Qt.ItemDataRole.UserRole
DEFAULT_URL = "https://dhofaemjobdlnztcztnd.supabase.co"
DEFAULT_KEY = "sb_publishable_nZN3jKsRsXOGoMVnrE1kbA_D-q0XYgU"          # the public key: what a person can see is decided by the database rules and their own sign-in
BOARD_ACCENT = "#9bc53d"
B_STATUSES = (("todo", "To do", "#8a9099"), ("doing", "In progress", "#e2a93f"), ("done", "Done", "#55b57a"))
B_PRIOS = (("low", "Low", "#6b9bd1"), ("normal", "Normal", "#8a9099"), ("high", "High", "#e2a93f"), ("urgent", "Urgent", "#ff3b4d"))
B_PRIO_COL = {k: c for k, _n, c in B_PRIOS}
B_ST_NAME = {k: n for k, n, _c in B_STATUSES}

class BoardError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ the connection
class BoardAPI:
    """Talks to Supabase (sign-in and the two tables) with plain web requests. Safe to call from any thread."""

    def __init__(self, G, save=None):
        self.G, self._save = G, save or (lambda: None)
        self._lock = _th.Lock()

    @property
    def url(self):
        return str(self.G.get("board_url") or DEFAULT_URL).rstrip("/")

    @property
    def key(self):
        return str(self.G.get("board_key") or DEFAULT_KEY)

    def _http(self, method, path, body=None, params=None, bearer=None, extra=None, timeout=15):
        u = self.url + path + (("?" + _uparse.urlencode(params)) if params else "")
        hdr = {"apikey": self.key, "Accept": "application/json", "Accept-Encoding": "identity"}
        if bearer:
            hdr["Authorization"] = "Bearer " + bearer
        if body is not None:
            hdr["Content-Type"] = "application/json"
        hdr.update(extra or {})
        req = _ureq.Request(u, data=_json.dumps(body).encode() if body is not None else None, headers=hdr, method=method)
        try:
            with _ureq.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                code = r.status
        except _uerr.HTTPError as e:
            raw, code = e.read(), e.code
        except Exception as e:
            raise BoardError("No connection to the board (%s)" % (getattr(e, "reason", None) or e))
        try:
            data = _json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            data = None
        if code >= 400:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("msg") or data.get("message") or data.get("error_description") or data.get("error") or ""
            err = BoardError(str(msg) or ("The board answered with an error (%d)" % code))
            err.code = code
            raise err
        return data

    # ---- sign-in
    def session(self):
        return self.G.get("board_session") or {}

    def me(self):
        return str(self.session().get("email") or "").lower()

    def signed_in(self):
        return bool(self.session().get("refresh"))

    def _store(self, tok):
        em = str(((tok.get("user") or {}).get("email")) or self.session().get("email") or "").lower()
        self.G["board_session"] = {"access": tok.get("access_token"), "refresh": tok.get("refresh_token"),
                                   "exp": _btime.time() + int(tok.get("expires_in") or 3600), "email": em}
        self._save()

    def sign_in(self, email, password):
        tok = self._http("POST", "/auth/v1/token", {"email": email.strip().lower(), "password": password}, {"grant_type": "password"})
        self._store(tok)

    def sign_up(self, email, password):
        """True when the person can sign in at once, False when an email has to be confirmed first."""
        res = self._http("POST", "/auth/v1/signup", {"email": email.strip().lower(), "password": password}) or {}
        if res.get("access_token"):
            self._store(res)
            return True
        return False

    def sign_out(self):
        self.G.pop("board_session", None)
        self._save()

    def _bearer(self, force=False):
        with self._lock:
            s = self.session()
            if not s.get("refresh"):
                raise BoardError("Sign in to the board first.")
            if force or _btime.time() > float(s.get("exp") or 0) - 60:
                try:
                    tok = self._http("POST", "/auth/v1/token", {"refresh_token": s["refresh"]}, {"grant_type": "refresh_token"})
                except BoardError as e:
                    if getattr(e, "code", 0) in (400, 401, 403):
                        self.sign_out()
                        raise BoardError("Your sign-in ran out. Please sign in again.")
                    raise
                self._store(tok)
                s = self.session()
            return s["access"]

    def _rest(self, method, table, body=None, params=None, extra=None):
        for attempt in (0, 1):
            try:
                return self._http(method, "/rest/v1/" + table, body, params, self._bearer(force=bool(attempt)), extra)
            except BoardError as e:
                if attempt == 0 and getattr(e, "code", 0) == 401:
                    continue
                raise

    # ---- the board
    def fetch(self, since=None):
        prm = {"select": "*", "order": "updated_at.asc"}
        if since:
            prm["updated_at"] = "gte." + since
        return self._rest("GET", "board_projects", params=prm) or []

    def add(self, fields):
        r = self._rest("POST", "board_projects", dict(fields), extra={"Prefer": "return=representation"})
        return (r or [None])[0]

    def change(self, pid, fields):
        r = self._rest("PATCH", "board_projects", dict(fields), {"id": "eq." + pid}, {"Prefer": "return=representation"})
        return (r or [None])[0]

    def members(self):
        return self._rest("GET", "board_members", params={"select": "*", "order": "added_at.asc"}) or []

    def add_member(self, email, name, role):
        self._rest("POST", "board_members", {"email": email.strip().lower(), "name": name.strip(), "role": role})

    def remove_member(self, email):
        self._rest("DELETE", "board_members", params={"email": "eq." + email})


# ------------------------------------------------------------------------------------------------ the cards
def board_kids(rows, pid):
    """live (not deleted) children of a project or to-do, in the order they were added"""
    ks = [r for r in rows.values() if r.get("parent_id") == pid and not r.get("deleted")]
    ks.sort(key=lambda r: (float(r.get("pos") or 0), str(r.get("created_at") or "")))
    return ks


def board_progress(rows, pid):
    """(done, total) over everything below this project, at every depth"""
    d = t = 0
    for k in board_kids(rows, pid):
        d2, t2 = board_progress(rows, k["id"])
        if t2 == 0:
            t += 1
            d += 1 if k.get("status") == "done" else 0
        else:
            t += t2
            d += d2
    return d, t


TODO_H = 27


def board_flat(rows, pid, opened, depth=0):
    """the to-dos shown under an opened card or to-do, indented by depth"""
    out = []
    if pid not in opened:
        return out
    for k in board_kids(rows, pid):
        out.append((k, depth))
        out += board_flat(rows, k["id"], opened, depth + 1)
    return out


class _BoardCardDelegate(QStyledItemDelegate):
    H = 92

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def height_for(self, r):
        if r.get("id") in self.page.open_ids:
            return self.H + 6 + TODO_H * (len(board_flat(self.page.rows, r["id"], self.page.open_ids)) + 1)
        return self.H

    def sizeHint(self, opt, idx):
        return QSize(opt.rect.width(), self.height_for(idx.data(BROLE) or {}))

    def geometry(self, rect):
        """card rectangle, where its to-do rows start"""
        card = QRectF(rect).adjusted(2, 3, -2, -3)
        return card, card.top() + self.H - 6 + 4

    def paint(self, p, opt, idx):
        r = idx.data(BROLE) or {}
        bg, fg, mute, line = self.page.colors()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(opt.rect).adjusted(2, 3, -2, -3)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        p.setPen(QPen(QColor(BOARD_ACCENT) if sel else QColor(line), 1.4))
        p.setBrush(QColor(self.page.card_bg()))
        p.drawRoundedRect(card, 9, 9)
        pc = QColor(B_PRIO_COL.get(r.get("priority"), "#8a9099"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pc)
        p.drawRoundedRect(QRectF(card.left() + 1, card.top() + 9, 4, card.height() - 18), 2, 2)
        x0 = card.left() + 16
        w = card.width() - 28
        f = QFont(p.font())
        f.setBold(True)
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QColor(fg))
        t = QFontMetrics(f).elidedText(str(r.get("title") or ""), Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QPointF(x0, card.top() + 24), t)
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(mute))
        bits = [b for b in (r.get("client"), ("→ " + self.page.who(r.get("owner"))) if r.get("owner") else "") if b]
        p.drawText(QPointF(x0, card.top() + 43), QFontMetrics(f).elidedText("  ·  ".join(bits), Qt.TextElideMode.ElideRight, int(w)))
        due = str(r.get("due") or "")
        late = bool(due) and due < _btime.strftime("%Y-%m-%d") and r.get("status") != "done"
        if due:
            p.setPen(QColor("#ff5a6a") if late else QColor(mute))
            p.drawText(QPointF(x0, card.top() + 60), ("Overdue · " if late else "Due ") + due)
        dn, tt = board_progress(self.page.rows, r.get("id"))
        if tt:
            by = card.top() + self.H - 6 - 12
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(line))
            p.drawRoundedRect(QRectF(x0, by, w - 50, 4), 2, 2)
            p.setBrush(QColor("#55b57a" if dn == tt else BOARD_ACCENT))
            p.drawRoundedRect(QRectF(x0, by, (w - 50) * dn / float(tt), 4), 2, 2)
            p.setPen(QColor(mute))
            p.drawText(QRectF(x0 + w - 44, by - 7, 44, 16), Qt.AlignmentFlag.AlignRight, "%d/%d" % (dn, tt))
        if r.get("priority") in ("high", "urgent"):
            f.setBold(True)
            p.setFont(f)
            p.setPen(pc)
            txt = dict((k, n) for k, n, _c in B_PRIOS)[r["priority"]]
            p.drawText(QRectF(card.right() - 90, card.top() + 44, 80, 16), Qt.AlignmentFlag.AlignRight, txt)
        opened = r.get("id") in self.page.open_ids
        self._chev(p, card.right() - 20, card.top() + 20, opened, mute)
        if opened:
            y0 = self.geometry(opt.rect)[1]
            p.setPen(QPen(QColor(line), 1))
            p.drawLine(QPointF(card.left() + 10, y0 - 3), QPointF(card.right() - 10, y0 - 3))
            fl = board_flat(self.page.rows, r["id"], self.page.open_ids)
            f2 = QFont(p.font())
            f2.setPixelSize(13)
            f2.setBold(False)
            for i, (k, dep) in enumerate(fl):
                yy = y0 + i * TODO_H
                x = card.left() + 12 + dep * 18
                done = k.get("status") == "done"
                haskids = bool(board_kids(self.page.rows, k["id"]))
                if haskids:
                    self._chev(p, x + 5, yy + TODO_H / 2.0, k["id"] in self.page.open_ids, mute, 4)
                bx = QRectF(x + 14, yy + TODO_H / 2.0 - 7, 14, 14)
                p.setPen(QPen(QColor("#55b57a" if done else mute), 1.5))
                p.setBrush(QColor("#55b57a") if done else Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(bx, 3, 3)
                if done:
                    p.setPen(QPen(QColor("#12161a"), 1.8))
                    p.drawLine(QPointF(bx.left() + 3, bx.center().y()), QPointF(bx.center().x() - 1, bx.bottom() - 4))
                    p.drawLine(QPointF(bx.center().x() - 1, bx.bottom() - 4), QPointF(bx.right() - 3, bx.top() + 4))
                pcol = QColor(B_PRIO_COL.get(k.get("priority"), "#8a9099"))
                tx = bx.right() + 8
                right = card.right() - 12
                tag = ""
                if k.get("priority") in ("urgent", "high", "low"):
                    tag = dict((a, b) for a, b, _c in B_PRIOS)[k["priority"]]
                tw = 0
                if tag:
                    p.setPen(Qt.PenStyle.NoPen)
                    ff = QFont(f2)
                    ff.setBold(True)
                    ff.setPixelSize(11)
                    p.setFont(ff)
                    tw = QFontMetrics(ff).horizontalAdvance(tag) + 14
                    p.setBrush(QColor(pcol.red(), pcol.green(), pcol.blue(), 46))
                    p.drawRoundedRect(QRectF(right - tw, yy + 5, tw, TODO_H - 10), 8, 8)
                    p.setPen(pcol)
                    p.drawText(QRectF(right - tw, yy + 5, tw, TODO_H - 10), Qt.AlignmentFlag.AlignCenter, tag)
                    right -= tw + 6
                dd = str(k.get("due") or "")
                if dd:
                    late = dd < _btime.strftime("%Y-%m-%d") and not done
                    p.setFont(f2)
                    p.setPen(QColor("#ff5a6a") if late else QColor(mute))
                    dw = QFontMetrics(f2).horizontalAdvance(dd) + 6
                    p.drawText(QRectF(right - dw, yy, dw, TODO_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, dd)
                    right -= dw + 6
                ft = QFont(f2)
                ft.setStrikeOut(done)
                p.setFont(ft)
                p.setPen(QColor(mute) if done else QColor(fg))
                p.drawText(QRectF(tx, yy, max(10, right - tx), TODO_H), Qt.AlignmentFlag.AlignVCenter,
                           QFontMetrics(ft).elidedText(str(k.get("title") or ""), Qt.TextElideMode.ElideRight, int(max(10, right - tx))))
            ya = y0 + len(fl) * TODO_H
            p.setFont(f2)
            p.setPen(QColor(BOARD_ACCENT))
            p.drawText(QRectF(card.left() + 14, ya, 200, TODO_H), Qt.AlignmentFlag.AlignVCenter, "+  Add a to-do")
        p.restore()

    @staticmethod
    def _chev(p, cx, cy, opened, col, sz=5):
        p.save()
        p.setPen(QPen(QColor(col), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if opened:
            p.drawPolyline([QPointF(cx - sz, cy - sz / 2.0), QPointF(cx, cy + sz / 2.0), QPointF(cx + sz, cy - sz / 2.0)])
        else:
            p.drawPolyline([QPointF(cx - sz / 2.0, cy - sz), QPointF(cx + sz / 2.0, cy), QPointF(cx - sz / 2.0, cy + sz)])
        p.restore()


class _BoardCol(QListWidget):
    dropped = _Signal(str, str)                      # project id, new status

    def __init__(self, status):
        super().__init__()
        self.status = status
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSpacing(0)

    def _hit(self, pos):
        """what the mouse is on: ('chev', card id) / ('check', id) / ('open', id) / ('row', id) / ('add', card id) / None"""
        idx = self.indexAt(pos)
        if not idx.isValid() or getattr(self, "page", None) is None:
            return None
        r = idx.data(BROLE) or {}
        pg = self.page
        rect = self.visualRect(idx)
        card, y0 = pg.delegate.geometry(rect)
        if pos.x() > card.right() - 40 and pos.y() < card.top() + 36:
            return ("chev", r.get("id"))
        if r.get("id") not in pg.open_ids or pos.y() < y0:
            return None
        fl = board_flat(pg.rows, r["id"], pg.open_ids)
        i = int((pos.y() - y0) // TODO_H)
        if i == len(fl):
            return ("add", r["id"])
        if 0 <= i < len(fl):
            k, dep = fl[i]
            x = card.left() + 12 + dep * 18
            if pos.x() < x + 13 and board_kids(pg.rows, k["id"]):
                return ("open", k["id"])
            if pos.x() < x + 32:
                return ("check", k["id"])
            return ("row", k["id"])
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self._hit(e.position().toPoint())
            if h:
                pg = self.page
                if h[0] in ("chev", "open"):
                    pg.toggle_open(h[1])
                elif h[0] == "check":
                    pg.todo_toggle(h[1])
                elif h[0] == "add":
                    pg.todo_prompt_add(h[1])
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h:
            if h[0] == "row":
                self.page.todo_rename(h[1])
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        h = self._hit(e.pos())
        if h and h[0] in ("row", "check", "open"):
            self.page.todo_menu(h[1], e.globalPos(), self)
            e.accept()
            return
        super().contextMenuEvent(e)

    def dropEvent(self, e):
        src = e.source()
        it = src.currentItem() if isinstance(src, QListWidget) else None
        if it is not None:
            r = it.data(BROLE) or {}
            if r.get("id") and r.get("status") != self.status:
                self.dropped.emit(r["id"], self.status)
        e.setDropAction(Qt.DropAction.IgnoreAction)        # the board redraws itself from the data; nothing is moved by the list
        e.ignore()


# ------------------------------------------------------------------------------------------------ the dialogs
class ProjectDialog(QDialog):
    def __init__(self, page, row=None, status="todo"):
        super().__init__(page)
        self.page, self.row = page, row or {}
        self.deleted = False
        self.setWindowTitle("Project" if row else "New project")
        self.resize(1060, 640)
        outer = QHBoxLayout(self)
        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(left, 5)
        self.title = QLineEdit(self.row.get("title", ""))
        self.title.setPlaceholderText("What needs to be done")
        self.status = QComboBox()
        for k, n, _c in B_STATUSES:
            self.status.addItem(n, k)
        self.status.setCurrentIndex([k for k, _n, _c in B_STATUSES].index(self.row.get("status") or status))
        self.prio = QComboBox()
        for k, n, _c in B_PRIOS:
            self.prio.addItem(n, k)
        self.prio.setCurrentIndex([k for k, _n, _c in B_PRIOS].index(self.row.get("priority") or "normal"))
        self.owner = QComboBox()
        self.owner.addItem("Nobody yet", "")
        for em, nm in page.people():
            self.owner.addItem("%s  (%s)" % (nm, em) if nm else em, em)
        i = self.owner.findData(str(self.row.get("owner") or "").lower())
        self.owner.setCurrentIndex(max(0, i))
        self.client = QLineEdit(self.row.get("client", "") or "")
        self.client.setPlaceholderText("Client or house (optional)")
        self.has_due = QCheckBox("Due date")
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("yyyy-MM-dd")
        d = QDate.fromString(str(self.row.get("due") or ""), "yyyy-MM-dd")
        self.has_due.setChecked(d.isValid())
        self.due.setDate(d if d.isValid() else QDate.currentDate())
        self.due.setEnabled(d.isValid())
        self.has_due.toggled.connect(self.due.setEnabled)
        self.link = QLineEdit(self.row.get("link", "") or "")
        self.link.setPlaceholderText("Link to a folder, file or email (optional)")
        self.notes = QPlainTextEdit(self.row.get("notes", "") or "")
        self.notes.setPlaceholderText("Notes")
        for lab, w in (("Title", self.title), ("Status", self.status), ("Priority", self.prio), ("Who does it", self.owner), ("Client / house", self.client)):
            v.addWidget(QLabel(lab))
            v.addWidget(w)
        hb = QHBoxLayout()
        hb.addWidget(self.has_due)
        hb.addWidget(self.due, 1)
        v.addLayout(hb)
        v.addWidget(QLabel("Link"))
        v.addWidget(self.link)
        v.addWidget(QLabel("Notes"))
        v.addWidget(self.notes, 1)
        if self.row.get("id"):
            who = self.page.who(self.row.get("updated_by"))
            v.addWidget(QLabel("<span style='color:#8a9099'>Last changed by %s</span>" % (who or "someone")))
        bar = QHBoxLayout()
        ok = QPushButton("Save")
        ok.setStyleSheet("QPushButton{background:%s;color:#12161a;font-weight:800;padding:8px 26px;border-radius:6px;}" % BOARD_ACCENT)
        ok.clicked.connect(self._ok)
        cx = QPushButton("Cancel")
        cx.clicked.connect(self.reject)
        bar.addWidget(ok)
        bar.addWidget(cx)
        bar.addStretch(1)
        if self.row.get("id"):
            dl = QPushButton("Delete")
            dl.clicked.connect(self._del)
            bar.addWidget(dl)
        v.addLayout(bar)
        outer.addWidget(self._subs_panel(), 6)
        self.finished.connect(self._unhook)

    # ---- to-dos inside the project, to any depth
    def _subs_panel(self):
        pn = QWidget()
        v = QVBoxLayout(pn)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("<span style='font-size:16px;font-weight:800'>To-dos in this project</span>"))
        self.pid = self.row.get("id")
        if not self.pid:
            lb = QLabel("Save the project first, then open it again to add to-dos and sub-to-dos under it.")
            lb.setWordWrap(True)
            lb.setStyleSheet("color:#8a9099;")
            v.addWidget(lb)
            v.addStretch(1)
            return pn
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["To-do", "Status", "Who", "Due"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 90)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tmenu)
        self.tree.itemChanged.connect(self._tchanged)
        self.tree.itemSelectionChanged.connect(self._tsel)
        v.addWidget(self.tree, 1)
        self.under = QLabel("")
        self.under.setStyleSheet("color:#8a9099;")
        v.addWidget(self.under)
        hb = QHBoxLayout()
        self.addbox = QLineEdit()
        self.addbox.setPlaceholderText("Add a to-do and press Enter  (select a to-do first to add under it)")
        self.addbox.returnPressed.connect(self._tadd)
        ab = QPushButton("Add")
        ab.clicked.connect(self._tadd)
        nb = QPushButton("Top level")
        nb.setToolTip("Clear the selection so the next to-do goes at the top level")
        nb.clicked.connect(lambda: self.tree.clearSelection())
        hb.addWidget(self.addbox, 1)
        hb.addWidget(ab)
        hb.addWidget(nb)
        v.addLayout(hb)
        v.addWidget(QLabel("<span style='color:#8a9099'>Tick the box when it is done. Double-click to rename. Right-click for status, who, due date, sub-to-do or delete.</span>"))
        self._building = False
        self.page.tree_hook = self._trefresh
        self._trefresh()
        return pn

    def _unhook(self, *_a):
        if getattr(self.page, "tree_hook", None) == getattr(self, "_trefresh", None):
            self.page.tree_hook = None

    def _trefresh(self):
        if not getattr(self, "pid", None) or self.tree.state() == QAbstractItemView.State.EditingState:
            return
        rows = self.page.rows
        keep_sel = self._tid(self.tree.currentItem()) if self.tree.selectedItems() else None
        opened = set()
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            if it.value().isExpanded():
                opened.add(it.value().data(0, BROLE))
            it += 1
        first = not hasattr(self, "_seen")
        self._seen = True
        sv = self.tree.verticalScrollBar().value()
        self._building = True
        self.tree.clear()
        today = _btime.strftime("%Y-%m-%d")
        sel_item = [None]

        def put(parent, r):
            n = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self.tree)
            n.setData(0, BROLE, r["id"])
            done = r.get("status") == "done"
            n.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            n.setCheckState(0, Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
            dn, tt = board_progress(rows, r["id"])
            n.setText(0, str(r.get("title") or ""))
            n.setText(1, B_ST_NAME.get(r.get("status"), "") + ("  %d/%d" % (dn, tt) if tt else ""))
            n.setForeground(1, QColor(dict((k, c) for k, _n, c in B_STATUSES).get(r.get("status"), "#8a9099")))
            n.setText(2, self.page.who(r.get("owner")) if r.get("owner") else "")
            due = str(r.get("due") or "")
            n.setText(3, due)
            if due and due < today and not done:
                n.setForeground(3, QColor("#ff5a6a"))
            if done:
                f = n.font(0)
                f.setStrikeOut(True)
                n.setFont(0, f)
                n.setForeground(0, QColor("#8a9099"))
            if r["id"] == keep_sel:
                sel_item[0] = n
            for c in board_kids(rows, r["id"]):
                put(n, c)
            if first or r["id"] in opened:
                n.setExpanded(True)
        for r in board_kids(rows, self.pid):
            put(None, r)
        if sel_item[0] is not None:
            self.tree.setCurrentItem(sel_item[0])
        self._building = False
        self.tree.verticalScrollBar().setValue(sv)
        self._tsel()

    def _tid(self, item):
        return item.data(0, BROLE) if item is not None else None

    def _tsel(self):
        sel = self.tree.selectedItems()
        if sel:
            r = self.page.rows.get(self._tid(sel[0]))
            self.under.setText("Next to-do goes under: <b>%s</b>" % (r.get("title") if r else ""))
        else:
            self.under.setText("Next to-do goes at the top level of this project")

    def _tadd(self):
        t = self.addbox.text().strip()
        if not t:
            return
        sel = self.tree.selectedItems()
        parent = self._tid(sel[0]) if sel else self.pid
        self.page._create({"title": t, "status": "todo", "priority": "normal", "parent_id": parent})
        self.addbox.clear()

    def _tchanged(self, item, col):
        if self._building or col != 0:
            return
        pid = self._tid(item)
        r = self.page.rows.get(pid)
        if not r:
            return
        done = item.checkState(0) == Qt.CheckState.Checked
        if done != (r.get("status") == "done"):
            self.page._apply(pid, {"status": "done" if done else "todo"})
            return
        t = str(item.data(0, Qt.ItemDataRole.EditRole) or "").strip()
        if t and t != r.get("title"):
            self.page._apply(pid, {"title": t})

    def _tmenu(self, pos):
        item = self.tree.itemAt(pos)
        if item is not None:
            self.page.todo_menu(self._tid(item), self.tree.viewport().mapToGlobal(pos), self)

    def _ok(self):
        if not self.title.text().strip():
            self.title.setFocus()
            return
        self.accept()

    def _del(self):
        if QMessageBox.question(self, "Projects", "Delete this project for everybody?") == QMessageBox.StandardButton.Yes:
            self.deleted = True
            self.accept()

    def fields(self):
        return {"title": self.title.text().strip(), "status": self.status.currentData(), "priority": self.prio.currentData(),
                "owner": self.owner.currentData() or None, "client": self.client.text().strip() or None,
                "due": self.due.date().toString("yyyy-MM-dd") if self.has_due.isChecked() else None,
                "link": self.link.text().strip() or None, "notes": self.notes.toPlainText().strip() or None}


class TeamDialog(QDialog):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("Who is on the board")
        self.resize(480, 420)
        v = QVBoxLayout(self)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        self.em = QLineEdit()
        self.em.setPlaceholderText("Their email address (the one they sign up with)")
        self.nm = QLineEdit()
        self.nm.setPlaceholderText("Their name")
        self.rl = QComboBox()
        self.rl.addItem("Member (adds and moves projects)", "member")
        self.rl.addItem("Admin (can also add and remove people)", "admin")
        for w in (self.em, self.nm, self.rl):
            v.addWidget(w)
        bar = QHBoxLayout()
        a = QPushButton("Add to the board")
        a.clicked.connect(self._add)
        r = QPushButton("Remove selected")
        r.clicked.connect(self._rm)
        c = QPushButton("Close")
        c.clicked.connect(self.accept)
        for w in (a, r):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(c)
        v.addLayout(bar)
        self._rows = []
        self.reload()

    def reload(self):
        def done(res, err):
            if err:
                self.msg.setText(err)
                return
            self._rows = res
            self.lst.clear()
            for m in res:
                it = QListWidgetItem("%s   %s   [%s]" % (m.get("name") or "", m["email"], m.get("role")))
                it.setData(BROLE, m["email"])
                self.lst.addItem(it)
        self.page.run(self.page.api.members, done)

    def _add(self):
        em, nm, rl = self.em.text().strip(), self.nm.text().strip(), self.rl.currentData()
        if "@" not in em:
            self.msg.setText("Type their email address.")
            return

        def done(res, err):
            self.msg.setText(err or "Added. Tell them to open Projects, press Create account with this email, and confirm the email Supabase sends them.")
            if not err:
                self.em.clear()
                self.nm.clear()
                self.page.load_people()
                self.reload()
        self.page.run(lambda: self.page.api.add_member(em, nm, rl), done)

    def _rm(self):
        it = self.lst.currentItem()
        if it is None:
            return
        em = it.data(BROLE)
        if em == self.page.api.me():
            self.msg.setText("You cannot remove yourself.")
            return

        def done(res, err):
            self.msg.setText(err or "Removed.")
            self.page.load_people()
            self.reload()
        self.page.run(lambda: self.page.api.remove_member(em), done)


# ------------------------------------------------------------------------------------------------ the page
class BoardPage(QWidget):
    _done = _Signal(object, object, object)

    def __init__(self, host, G, is_light, get_M):
        self.open_ids = set()
        self.tree_hook = None
        super().__init__()
        self.host, self.G, self.is_light, self.get_M = host, G, is_light, get_M
        self.setObjectName("boardpage")
        self.api = BoardAPI(G, lambda: self._save())
        self.rows = {}                  # id -> row
        self.team = []                  # [{email, name, role}]
        self.since = None
        self.loaded = False
        self.busy = False
        self.unseen = 0
        self.last_ok = 0.0
        self.is_admin = False
        self._tick_n = 0
        self._done.connect(lambda cb, res, err: cb(res, err))
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)
        self.restyle()
        QTimer.singleShot(800, self._start)

    # ---- helpers
    def _save(self):
        try:
            self.get_M().save_settings()
        except Exception:
            pass

    def run(self, fn, cb):
        def work():
            try:
                res, err = fn(), None
            except BoardError as e:
                res, err = None, str(e)
            except Exception as e:
                res, err = None, "Something went wrong (%s)" % e
            try:
                self._done.emit(cb, res, err)
            except RuntimeError:
                pass
        _th.Thread(target=work, daemon=True).start()

    def colors(self):
        return ("#ffffff", "#1c1f23", "#6b727b", "#d9dde2") if self.is_light() else ("#1f2125", "#eceef0", "#8a9099", "#30353b")

    def card_bg(self):
        return "#f6f7f9" if self.is_light() else "#272a30"

    def people(self):
        return [(m["email"], m.get("name") or "") for m in self.team]

    def who(self, email):
        email = str(email or "").lower()
        for m in self.team:
            if m["email"].lower() == email:
                return m.get("name") or email.split("@")[0]
        return email.split("@")[0] if email else ""

    # ---- layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        home = QPushButton("‹  Home")
        home.clicked.connect(lambda: self.host.main_tabs.setCurrentIndex(self.host.launcher_idx[0]))
        sw = QPushButton("Switch tool  ▾")
        sw.clicked.connect(lambda _=False, b=sw: getattr(self.host, "shell_rail")._switch_menu(b) if getattr(self.host, "shell_rail", None) is not None else None)
        top.addWidget(home)
        top.addWidget(sw)
        self.title = QLabel("<span style='font-size:20px;font-weight:800;'>Projects</span>")
        top.addWidget(self.title)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.render())
        top.addWidget(self.search, 1)
        self.mine = QCheckBox("Only mine")
        self.mine.toggled.connect(lambda _b: self.render())
        top.addWidget(self.mine)
        self.live = QLabel("")
        top.addWidget(self.live)
        self.new_btn = QPushButton("+  New project")
        self.new_btn.setStyleSheet("QPushButton{background:%s;color:#12161a;font-weight:800;padding:7px 18px;border-radius:6px;}" % BOARD_ACCENT)
        self.new_btn.clicked.connect(lambda: self.edit(None))
        top.addWidget(self.new_btn)
        self.team_btn = QPushButton("Team")
        self.team_btn.clicked.connect(lambda: TeamDialog(self).exec())
        top.addWidget(self.team_btn)
        self.who_btn = QPushButton("")
        self.who_btn.setToolTip("Sign out of the board")
        self.who_btn.clicked.connect(self._sign_out)
        top.addWidget(self.who_btn)
        root.addLayout(top)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        # sign-in
        lg = QWidget()
        lv = QVBoxLayout(lg)
        lv.addStretch(1)
        self.lmsg = QLabel("")
        self.lmsg.setWordWrap(True)
        self.lmsg.setTextFormat(Qt.TextFormat.RichText)
        self.lmsg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lmsg.setFixedWidth(520)
        self.lmsg.setMinimumHeight(70)
        lv.addWidget(self.lmsg, 0, Qt.AlignmentFlag.AlignHCenter)
        self.em = QLineEdit()
        self.em.setPlaceholderText("Your email address")
        self.pw = QLineEdit()
        self.pw.setPlaceholderText("Password")
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.returnPressed.connect(self._signin)
        for w in (self.em, self.pw):
            w.setFixedWidth(380)
            w.setMinimumHeight(36)
            lv.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        bb = QHBoxLayout()
        bb.addStretch(1)
        s1 = QPushButton("Sign in")
        s1.setStyleSheet("QPushButton{background:%s;color:#12161a;font-weight:800;padding:9px 28px;border-radius:6px;}" % BOARD_ACCENT)
        s1.clicked.connect(self._signin)
        s2 = QPushButton("Create account")
        s2.clicked.connect(self._signup)
        bb.addWidget(s1)
        bb.addWidget(s2)
        bb.addStretch(1)
        lv.addLayout(bb)
        lv.addStretch(2)
        self.stack.addWidget(lg)
        # board
        bd = QWidget()
        bh = QHBoxLayout(bd)
        bh.setContentsMargins(0, 6, 0, 0)
        bh.setSpacing(14)
        self.cols, self.heads = {}, {}
        self.delegate = _BoardCardDelegate(self)
        for k, n, c in B_STATUSES:
            box = QFrame()
            box.setObjectName("bcol")
            cv = QVBoxLayout(box)
            cv.setContentsMargins(10, 10, 10, 10)
            h = QLabel("")
            h.setTextFormat(Qt.TextFormat.RichText)
            col = _BoardCol(k)
            col.setItemDelegate(self.delegate)
            col.page = self
            col.itemDoubleClicked.connect(lambda it: self.edit(it.data(BROLE)))
            col.dropped.connect(self.move)
            ad = QPushButton("+  Add")
            ad.setFlat(True)
            ad.setStyleSheet("QPushButton{color:#8a9099;border:none;padding:7px;font-weight:700;} QPushButton:hover{color:%s;}" % BOARD_ACCENT)
            ad.setCursor(Qt.CursorShape.PointingHandCursor)
            ad.clicked.connect(lambda _=False, kk=k: self.edit(None, kk))
            cv.addWidget(h)
            cv.addWidget(col, 1)
            cv.addWidget(ad)
            bh.addWidget(box, 1)
            self.cols[k], self.heads[k] = col, h
        self.stack.addWidget(bd)
        self.status = QLabel("")
        root.addWidget(self.status)

    def restyle(self):
        bg, fg, mute, line = self.colors()
        self.setStyleSheet(
            "#boardpage{background:%(bg)s;} #boardpage QLabel{color:%(fg)s;background:transparent;} #boardpage QCheckBox{color:%(fg)s;} "
            "#boardpage QFrame#bcol{background:%(col)s;border:1px solid %(line)s;border-radius:12px;} "
            "#boardpage QListWidget{background:transparent;border:none;outline:none;} "
            "#boardpage QLineEdit{background:%(inp)s;color:%(fg)s;border:1px solid %(line)s;border-radius:6px;padding:6px 9px;}"
            % {"bg": bg, "fg": fg, "line": line, "col": "#f0f2f5" if self.is_light() else "#1a1c20", "inp": "#ffffff" if self.is_light() else "#16181b"})
        self.render()

    # ---- sign-in flow
    def _start(self):
        if self.api.signed_in():
            self.load_people(first=True)
        else:
            self._login_screen("Sign in to share projects live with your team.<br><span style='color:#8a9099'>New here? Press <b>Create account</b> with the email address that was added to the board for you.</span>")

    def _login_screen(self, msg):
        self.stack.setCurrentIndex(0)
        self.lmsg.setText("<div style='font-size:15px'>%s</div>" % msg)
        for w in (self.new_btn, self.team_btn, self.who_btn, self.search, self.mine):
            w.setVisible(False)
        self.live.setText("")
        if self.api.me() and not self.em.text():
            self.em.setText(self.api.me())

    def _signin(self):
        em, pw = self.em.text().strip(), self.pw.text()
        if "@" not in em or not pw:
            self.lmsg.setText("<div style='color:#ff5a6a'>Type your email address and password.</div>")
            return

        def done(res, err):
            if err:
                self.lmsg.setText("<div style='color:#ff5a6a;font-size:14px'>%s</div>" % err)
                return
            self.pw.clear()
            self.load_people(first=True)
        self.run(lambda: self.api.sign_in(em, pw), done)

    def _signup(self):
        em, pw = self.em.text().strip(), self.pw.text()
        if "@" not in em or len(pw) < 6:
            self.lmsg.setText("<div style='color:#ff5a6a'>Type your email address and choose a password of at least 6 characters, then press Create account.</div>")
            return

        def done(res, err):
            if err:
                self.lmsg.setText("<div style='color:#ff5a6a;font-size:14px'>%s</div>" % err)
            elif res:
                self.pw.clear()
                self.load_people(first=True)
            else:
                self.lmsg.setText("<div style='font-size:14px'>Account created. Open the email just sent to <b>%s</b> and click the confirm link. The page it opens may say \"localhost refused to connect\": that is fine, your account is confirmed. Come back here and press <b>Sign in</b> (your password is still filled in).</div>" % em)
        self.run(lambda: self.api.sign_up(em, pw), done)

    def _sign_out(self):
        self.api.sign_out()
        self.rows.clear()
        self.team = []
        self.since = None
        self.loaded = False
        self._login_screen("You are signed out.")

    # ---- loading
    def load_people(self, first=False):
        def done(res, err):
            if err:
                if not self.api.signed_in():
                    self._login_screen("<span style='color:#ff5a6a'>%s</span>" % err)
                else:
                    self.status.setText(err)
                return
            self.team = res or []
            me = self.api.me()
            mine = [m for m in self.team if m["email"].lower() == me]
            self.is_admin = bool(mine and mine[0].get("role") == "admin")
            if not mine:
                self._login_screen("You are signed in as <b>%s</b>, but this email is not on the board yet.<br>Ask the board's admin to add it under <b>Team</b>, then press Sign in again." % me)
                self.api.sign_out()
                return
            self.stack.setCurrentIndex(1)
            for w in (self.new_btn, self.who_btn, self.search, self.mine):
                w.setVisible(True)
            self.team_btn.setVisible(self.is_admin)
            self.who_btn.setText("%s  ·  Sign out" % (self.who(me) or me))
            if first or not self.loaded:
                self.since = None
                self.poll()
            else:
                self.render()
        self.run(self.api.members, done)

    def poll(self):
        if self.busy or not self.api.signed_in() or self.stack.currentIndex() != 1:
            return
        self.busy = True
        since = self.since

        def done(res, err):
            self.busy = False
            if err:
                self.live.setText("<span style='color:#ff5a6a'>● Offline</span>")
                if not self.api.signed_in():
                    self._login_screen("<span style='color:#ff5a6a'>%s</span>" % err)
                return
            self.last_ok = _btime.time()
            self.live.setText("<span style='color:%s'>● Live</span>" % BOARD_ACCENT)
            self.merge(res or [])
        self.run(lambda: self.api.fetch(since), done)

    def _tick(self):
        self._tick_n += 1
        if self.isVisible() or self._tick_n % 3 == 0:                # every 2 s while you look at it, every 6 s in the background
            self.poll()

    def merge(self, rows):
        me = self.api.me()
        first = not self.loaded
        changed = False
        notes = []
        for r in rows:
            old = self.rows.get(r["id"])
            if old is not None and old.get("updated_at") == r.get("updated_at") and old.get("deleted") == r.get("deleted"):
                continue
            changed = True
            self.rows[r["id"]] = r
            by = str(r.get("updated_by") or "").lower()
            if not first and by and by != me:
                nm = self.who(by) or "Someone"
                t = r.get("title")
                own = str(r.get("owner") or "").lower()
                oldown = str((old or {}).get("owner") or "").lower()
                sub = " (a to-do in “%s”)" % ((self.rows.get(r.get("parent_id")) or {}).get("title") or "a project") if r.get("parent_id") else ""
                if r.get("deleted"):
                    notes.append("%s removed “%s”" % (nm, t))
                elif own == me and own != oldown:
                    notes.append("%s gave you “%s”%s" % (nm, t, sub))
                elif old is None:
                    notes.append("%s added “%s”%s" % (nm, t, sub))
                elif old.get("status") != r.get("status"):
                    if r.get("status") == "done":
                        notes.append("%s finished “%s”%s" % (nm, t, sub))
                    else:
                        notes.append("%s moved “%s” to %s" % (nm, t, B_ST_NAME.get(r.get("status"), "")))
                elif own and own != oldown:
                    notes.append("%s gave “%s” to %s" % (nm, t, self.who(own) or own))
                elif old.get("priority") != r.get("priority") and r.get("priority") == "urgent":
                    notes.append("%s marked “%s” urgent" % (nm, t))
                else:
                    notes.append("%s changed “%s”" % (nm, t))
        if rows:
            self.since = max(str(r.get("updated_at") or "") for r in rows)
        self.loaded = True
        if changed:
            self.render()
        if notes:
            if not (self.isVisible() and self.host.isActiveWindow()):
                self.unseen += len(notes)
            try:
                tray = getattr(self.host, "_tray", None)
                if tray is not None and not self.host.isActiveWindow():
                    tray.showMessage("Projects", "\n".join(notes[:4]), msecs=6000)
            except Exception:
                pass
            try:
                self.host.toast(notes[0] if len(notes) == 1 else "%s, and %d more on the board" % (notes[0], len(notes) - 1), "Open",
                                lambda: self.host.main_tabs.setCurrentWidget(self), 8000)
            except Exception:
                pass

    def showEvent(self, e):
        super().showEvent(e)
        self.unseen = 0
        QTimer.singleShot(0, self.poll)

    # ---- drawing the board
    def render(self):
        q = self.search.text().strip().lower()
        me = self.api.me()
        only = self.mine.isChecked()
        for k, n, c in B_STATUSES:
            col = self.cols[k]
            keep = col.verticalScrollBar().value()
            col.blockSignals(True)
            col.clear()
            rs = [r for r in self.rows.values() if not r.get("deleted") and not r.get("parent_id") and r.get("status") == k]
            if q:
                def _hit(r):
                    if q in " ".join(str(r.get(x) or "") for x in ("title", "client", "notes", "owner")).lower():
                        return True
                    return any(_hit(c) for c in board_kids(self.rows, r["id"]))
                rs = [r for r in rs if _hit(r)]
            if only:
                rs = [r for r in rs if str(r.get("owner") or "").lower() == me]
            rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
            rs.sort(key=lambda r: (rank.get(r.get("priority"), 2), str(r.get("due") or "9999"), str(r.get("created_at") or "")))
            for r in rs:
                it = QListWidgetItem()
                it.setData(BROLE, r)
                it.setSizeHint(QSize(100, self.delegate.height_for(r)))
                col.addItem(it)
            col.blockSignals(False)
            col.verticalScrollBar().setValue(keep)
            self.heads[k].setText("<span style='font-size:15px;font-weight:800;color:%s'>●</span> <span style='font-size:15px;font-weight:800'>%s</span>"
                                  " <span style='color:#8a9099'>%d</span>" % (c, n, len(rs)))
        try:
            if getattr(self, "tree_hook", None):
                self.tree_hook()
        except Exception:
            pass

    # ---- changing things (the screen follows at once, the database after)
    def edit(self, row, status="todo"):
        dlg = ProjectDialog(self, row, status)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        f = dlg.fields()
        if row and row.get("id"):
            if dlg.deleted:
                self._apply(row["id"], {"deleted": True})
            else:
                self._apply(row["id"], f)
        else:
            self._create(f)

    def _apply(self, pid, fields):
        r = self.rows.get(pid)
        if r is None:
            return
        self.rows[pid] = dict(r, **fields)
        self.render()

        def done(res, err):
            if err:
                self.status.setText("The board did not accept the change (%s)" % err)
                self.since = None
            elif res:
                self.rows[pid] = res
                self.since = max(self.since or "", str(res.get("updated_at") or ""))
                self.render()
        self.run(lambda: self.api.change(pid, fields), done)

    def _create(self, fields):
        fields = dict(fields, pos=_btime.time())

        def done(res, err):
            if err:
                self.status.setText("The board did not accept the project (%s)" % err)
            elif res:
                self.rows[res["id"]] = res
                self.since = max(self.since or "", str(res.get("updated_at") or ""))
                self.render()
        self.run(lambda: self.api.add(fields), done)

    # ---- to-dos on the cards
    def toggle_open(self, pid):
        if pid in self.open_ids:
            self.open_ids.discard(pid)
        else:
            self.open_ids.add(pid)
        self.render()

    def todo_toggle(self, pid):
        r = self.rows.get(pid)
        if r:
            self._apply(pid, {"status": "todo" if r.get("status") == "done" else "done"})

    def todo_prompt_add(self, parent_id):
        from PySide6.QtWidgets import QInputDialog
        t, ok = QInputDialog.getText(self, "New to-do", "What needs to be done:")
        if ok and t.strip():
            self.open_ids.add(parent_id)
            self._create({"title": t.strip(), "status": "todo", "priority": "normal", "parent_id": parent_id})

    def todo_rename(self, pid):
        from PySide6.QtWidgets import QInputDialog
        r = self.rows.get(pid) or {}
        t, ok = QInputDialog.getText(self, "Rename", "To-do:", text=str(r.get("title") or ""))
        if ok and t.strip() and t.strip() != r.get("title"):
            self._apply(pid, {"title": t.strip()})

    def todo_delete(self, pid, parent=None):
        if QMessageBox.question(parent or self, "Projects", "Delete this to-do and everything under it for everybody?") == QMessageBox.StandardButton.Yes:
            def walk(i):
                for c in board_kids(self.rows, i):
                    walk(c["id"])
                    self._apply(c["id"], {"deleted": True})
            walk(pid)
            self._apply(pid, {"deleted": True})

    def todo_menu(self, pid, gpos, parent=None):
        m = QMenu(parent or self)
        pm = m.addMenu("Priority")
        for k, n, _c in reversed(B_PRIOS):
            pm.addAction(n).triggered.connect(lambda _=False, k=k: self._apply(pid, {"priority": k}))
        for k, n, _c in B_STATUSES:
            m.addAction("Mark as " + n).triggered.connect(lambda _=False, k=k: self._apply(pid, {"status": k}))
        m.addSeparator()
        wm = m.addMenu("Who does it")
        wm.addAction("Nobody").triggered.connect(lambda _=False: self._apply(pid, {"owner": None}))
        for em, nm in self.people():
            wm.addAction(nm or em).triggered.connect(lambda _=False, em=em: self._apply(pid, {"owner": em}))
        dm = m.addMenu("Due date")
        for lab, days in (("Today", 0), ("Tomorrow", 1), ("In a week", 7)):
            dm.addAction(lab).triggered.connect(lambda _=False, d=days: self._apply(pid, {"due": QDate.currentDate().addDays(d).toString("yyyy-MM-dd")}))
        dm.addAction("Pick a date…").triggered.connect(lambda _=False: self._pick_due(pid))
        dm.addAction("No date").triggered.connect(lambda _=False: self._apply(pid, {"due": None}))
        m.addSeparator()
        m.addAction("Add a sub-to-do under this").triggered.connect(lambda _=False: self.todo_prompt_add(pid))
        m.addAction("Rename").triggered.connect(lambda _=False: self.todo_rename(pid))
        m.addSeparator()
        m.addAction("Delete (with everything under it)").triggered.connect(lambda _=False: self.todo_delete(pid, parent))
        m.exec(gpos)

    def _pick_due(self, pid):
        from PySide6.QtWidgets import QInputDialog
        r = self.rows.get(pid) or {}
        t, ok = QInputDialog.getText(self, "Due date", "Date (yyyy-mm-dd):", text=str(r.get("due") or QDate.currentDate().toString("yyyy-MM-dd")))
        if ok and QDate.fromString(t.strip(), "yyyy-MM-dd").isValid():
            self._apply(pid, {"due": t.strip()})

    def move(self, pid, status):
        self._apply(pid, {"status": status})
