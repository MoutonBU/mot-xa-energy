"""Small interface helpers: toasts with Undo, empty-state hints, drag-and-drop, the progress strip and the "What's new" window."""
import os
import re

import math
import sys

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, QSize, QTimer, Qt, QUrl, QVariantAnimation
from PySide6.QtGui import QImage, QPixmap, QTransform, QBrush, QColor, QDesktopServices, QIcon, QCursor, QPalette, QPainter, QPen, QRadialGradient
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


def splash_show(app, logo_pixmap=None):
    """the logo fades in with a thin red line while the program builds its window"""
    w = QWidget(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    w.setFixedSize(420, 240)
    w.setStyleSheet("QWidget{background:#16171a;}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(24, 24, 24, 30)
    lb = QLabel()
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if logo_pixmap is not None and not logo_pixmap.isNull():
        lb.setPixmap(logo_pixmap.scaledToHeight(110, Qt.TransformationMode.SmoothTransformation))
    else:
        lb.setText("<b style='color:#eceef0;font-size:22px'>MCP Architecture &amp; Interiors</b>")
    lay.addWidget(lb)
    bar = QFrame(w)
    bar.setFixedHeight(3)
    bar.setStyleSheet("background:#ff4056;")
    scr = app.primaryScreen().availableGeometry()
    w.move(scr.center().x() - 210, scr.center().y() - 120)
    w.setWindowOpacity(0.0)
    w.show()
    bar.setGeometry(0, 237, 10, 3)
    bar.show()
    an = QVariantAnimation(w)
    an.setStartValue(0.0)
    an.setEndValue(1.0)
    an.setDuration(900)
    an.setEasingCurve(QEasingCurve.Type.OutCubic)

    def step(v):
        w.setWindowOpacity(min(1.0, float(v) * 2.0))
        bar.setGeometry(0, 237, int(420 * float(v)), 3)
    an.valueChanged.connect(step)
    w._an = an
    an.start()
    for _ in range(6):
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
from PySide6.QtGui import QIcon as _QIcon, QTextDocument
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


def mail_fix_images(body, doc, inline, remote_ok, maxw=700):
    """Make every picture in an email either show or vanish (never Qt's big grey 'missing picture' box).
    cid: pictures come from the attachments, data: pictures are decoded, web pictures show only when fetched (inline['url:...'])."""
    seen = {}
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
                return "<span style='color:#8a9099;font-size:11px'>[picture not loaded%s]</span>" % ((": " + _html.escape(str(why))) if why else "")
            return ""
        key = seen.get(src)
        if key is None:
            hk = hash(data)
            img = _PIXC.get(hk)
            if img is None:
                img = mail_pixmap(data)
                if not img.isNull():
                    if len(_PIXC) > 60:
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
            if td >= 0:
                tm = re.search(r"(?is)\bwidth\s*=\s*[\"']?\s*([\d.]+)\s*%", m.string[td:m.string.find(">", td) + 1])
                if tm:
                    share = float(tm.group(1)) / 100.0
            target = int(imgw * pct / 100.0 * share)
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
        t2 = _ATTR_DROP.sub("", tag)
        t2 = _SRC_RE.sub('src="%s" width="%d" height="%d"' % (rk, target, h), t2, 1)
        return t2
    dims = {}
    pix = {}
    made = set()
    dpr = _dpr()
    return mail_round(mail_fit_widths(mail_maxwidth(_IMG_RE.sub(one, mail_fix_rows(mail_drop_hidden(body))), maxw), maxw), doc)


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


def mail_pdf_pixmap(data, height):
    """The first page of a PDF as a picture of the given height (PyMuPDF, which the program already contains)."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        pg = doc[0]
        sc = height / float(pg.rect.height or 1)
        pix = pg.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        doc.close()
        return QPixmap.fromImage(img)
    except Exception:
        return QPixmap()


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
    tb = ""
    for _h, cells in rows:
        tds = ""
        for idx, x0, x1, kind in cells:
            img = '<img src="cid:mcpsig%d" width="100%%" alt="%s" style="display:block;width:100%%;height:auto;border:0;">' % (idx, _html.escape(alt.get(kind, "") or "Signature"))
            if kind:
                img = '<a href="%s" style="text-decoration:none;">%s</a>' % (_html.escape(href[kind]), img)
            tds += '<td width="%.3f%%" style="padding:0;font-size:0;line-height:0;">%s</td>' % ((x1 - x0) * 100.0 / float(cells[-1][2]), img)
        tb += '<table width="100%%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;table-layout:fixed;"><tr>%s</tr></table>' % tds
    html = '<br><table width="620" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:620px;"><tr><td style="border-radius:12px;overflow:hidden;">%s</td></tr></table>' % tb
    plain = "\n".join(x for x in (lt.get("name", ""), lt.get("role", ""), lt.get("phone", ""), lt.get("email", ""), web) if x)
    if len(_SIGC) > 4:
        _SIGC.clear()
    _SIGC[key] = (html, jp, plain)
    return _SIGC[key]


def mail_compose(S, to="", cc="", bcc="", subject="", html_body="", plain_body="", files=(), in_reply_to="", references="", signature=True):
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
    msg.set_content(plain_full or " ")
    msg.add_alternative(html_full, subtype="html")
    for _i, _b in enumerate(sig_jp):
        msg.get_payload()[1].add_related(_b, maintype="image", subtype="jpeg", cid="<mcpsig%d>" % _i, filename="signature%d.jpg" % _i, disposition="inline")
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
        return _QSize(400, self.H)

    def _cols(self, r):
        return QRect(r.left() + 26, r.top() + 12, 20, 20), QRect(r.left() + 56, r.top() + 10, 24, 24)

    def _st(self, opt):
        key = (opt.font.toString(), self.page.is_light())
        if getattr(self, "_key", None) != key:
            self._key = key
            bg, fg, mute, line = self.page.colors()
            fn = _QFont(opt.font)
            fn.setBold(False)
            fb = _QFont(opt.font)
            fb.setBold(True)
            fs = _QFont(opt.font)
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
            cb, st = self._cols(opt.rect)
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
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

    def minimumSizeHint(self):
        return _QSize(0, 20)

    def _fit(self):
        w = max(200, self.viewport().width())
        self.document().setTextWidth(w)
        self.horizontalScrollBar().setValue(0)
        self.setFixedHeight(int(self.document().size().height()) + 14)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def wheelEvent(self, e):
        e.ignore()                                   # the wheel scrolls the page, not each message


class MailCompose(_QD):
    """New email, reply, reply to all or forward, with my signature. Sends through the Gmail account that is signed in."""

    def __init__(self, page, to="", cc="", subject="", html_body="", in_reply_to="", references="", thread_id=""):
        super().__init__(page)
        self.page, self.S = page, page.S
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
        self.sig = _QCheck("Add my signature")
        self.sig.setChecked(True)
        bar.addWidget(self.bcc_btn)
        bar.addWidget(att)
        bar.addWidget(self.sig)
        bar.addStretch(1)
        v.addLayout(bar)
        self.att_lbl = _QL("")
        self.att_lbl.setWordWrap(True)
        v.addWidget(self.att_lbl)
        self.body = _QTE()
        self.body.setAcceptRichText(True)
        if html_body:
            self.body.setHtml(html_body)
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
        (self.subject if to else self.to).setFocus()

    def _show_cc(self):
        for k in ("cc", "bcc"):
            self._extra[k][0].show()
            self._extra[k][1].show()
        self.bcc_btn.hide()

    def _attach(self):
        fs, _ = _QFD.getOpenFileNames(self, "Attach files")
        if fs:
            self.files += fs
            self.att_lbl.setText("Attached: " + ", ".join(os.path.basename(f) for f in self.files))

    def build(self):
        return mail_compose(self.S, self.to.text().strip(), self.cc.text().strip(), self.bcc.text().strip(), self.subject.text().strip(),
                            self._html(), self.body.toPlainText(), self.files, self.in_reply_to, self.references, self.sig.isChecked())

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
        lg = _QL()
        if icon is not None and not icon.isNull():
            lg.setPixmap(icon.scaledToHeight(int(40 * _dpr()), Qt.TransformationMode.SmoothTransformation))
            lg.setFixedHeight(40)
            lg.setScaledContents(False)
        top.addWidget(lg)
        n = len(rows)
        top.addWidget(_QL("<div style='font-size:18px;font-weight:800;color:%s'>%s</div><div style='font-size:12px;color:%s'>Gmail</div>" % (
            pal[1], "New email" if n == 1 else "%d new emails" % n, pal[2])), 1)
        v.addLayout(top)
        for r in rows[:3]:
            lab = _QL("<b style='font-size:14px'>%s</b><br><span style='font-size:13px'>%s</span><br><span style='color:%s;font-size:12px'>%s</span>" % (
                _html.escape(r["from"]), _html.escape(r["subject"] or "(no subject)"), pal[2], _html.escape(r["snippet"])))
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

    def __init__(self, host, S, is_light, get_M):
        super().__init__()
        self.host, self.S, self.is_light, self.get_M = host, S, is_light, get_M
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
        self.set_btn = _QPB("Settings  \u25be")
        self.set_btn.setToolTip("Your email signature and the new-mail pop-up")
        self.set_btn.clicked.connect(self._settings_menu)
        top.addWidget(self.set_btn)
        root.addLayout(top)
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
        self.refresh_btn.clicked.connect(lambda: self.load_list(reset=False))
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
        self.timer.timeout.connect(self._tick)
        self.timer.start(3000)
        self._hid = None
        self._busy = False
        self._last_full = 0.0
        self._fill_side()
        self._refresh_state()
        self.restyle()

    # ----------------------------------------------------------------- look
    MAIL_BLUE = "#4aa3df"                      # the Mail card's colour on the home screen

    def _pal(self):
        """The program's palette in the Mail card's blue: selection, accents and the hot tint all follow it."""
        import app_shell
        old = app_shell.ACC[0]
        app_shell.ACC[0] = self.MAIL_BLUE
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
            "#mailpage QLineEdit:focus{border:1px solid %(accent)s;}" %
            dict(bg=bg, fg=fg, line=line, rail=p["rail"], pline=p["line"], accent=p["accent"], hover=p["hover"], muted=p["muted"], sel=p["sel"], hotline=p["hotline"]))
        self.cats.setDrawBase(False)
        self.compose_btn.setStyleSheet("QPushButton{background:%s;color:#ffffff;font-weight:700;font-size:14px;padding:14px 22px;border-radius:12px;text-align:left;border:none;} "
                                       "QPushButton:hover{background:%s;}" % (self.MAIL_BLUE, "#6bb8ea"))
        self.side.setStyleSheet("QListWidget{background:transparent;color:%s;border:none;outline:0;} QListWidget::item{padding:7px 12px;border-radius:9px;} "
                                "QListWidget::item:selected{background:%s;color:%s;font-weight:700;border-left:3px solid %s;} QListWidget::item:hover{background:%s;}"
                                % (p["text"], p["sel"], p["text"], p["accent"], p["hover"]))
        self.list.setStyleSheet("QListWidget{background:%s;border:1px solid %s;border-radius:14px;outline:0;}" % (bg, p["line"]))
        self.thread_host.setStyleSheet("background:%s;" % bg)
        self.connect_box.setStyleSheet("QFrame{background:%s;border:none;}" % bg)
        self._row_cache_reset()

    def _settings_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("My email signature...", self._edit_signature)
        a = m.addAction("Pop-up when new mail arrives")
        a.setCheckable(True)
        a.setChecked(bool(self.S.get("mail_notify", True)))
        a.toggled.connect(self._set_notify)
        m.exec(self.set_btn.mapToGlobal(self.set_btn.rect().bottomLeft()))

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
    def run(self, fn, cb):
        def work():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, str(e)
            try:
                self._done.emit(cb, res, err)
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

    # ------------------------------------------------------------- new-mail pop-up (works while the window is hidden in the tray)
    def _notify_tick(self):
        S = self.S
        if getattr(self, "_nbusy", False) or not S.get("mail_notify", True) or not self.ready() or self.mo.gmail_blocked():
            return
        self._nbusy = True
        mo = self.mo

        def work():
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
                             "tid": g.get("threadId", mid)})
            return h.get("historyId") or hid, rows

        def done(res, err):
            self._nbusy = False
            if err or not res:
                return
            hid, rows = res
            if hid:
                S["mail_notify_hid"] = hid
            if rows:
                self._show_toast(rows)
                self._topen.clear()
                if self.isVisible() and self.label == "INBOX" and not self.query and self.stack.currentIndex() == 0:
                    self.load_labels(quiet=True)
                    self.load_list(reset=False, quiet=True)               # the new mail is in the list the moment the pop-up shows
        self.run(work, done)

    def _show_toast(self, rows):
        try:
            w = self.window()
            if w.isActiveWindow() and self.isVisible() and self.host.main_tabs.currentWidget() is self:
                return                                              # you are looking at the mail right now
            old = getattr(self, "_toast", None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            ic = self.host.windowIcon().pixmap(64, 64) if hasattr(self.host, "windowIcon") else None
            bg_, fg_, mute_, line_ = self.colors()
            t = MailToast(rows, ic, self._toast_open, (bg_, fg_, mute_, "#2a2e35" if not self.is_light() else "#f1f3f5", self.MAIL_BLUE))
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
            self.open_thread(row.get("tid", ""), row.get("subject", ""))
        except Exception:
            pass

    def _tick(self):
        # Gmail has no push to a desktop app, so ask for the tiny mailbox change marker every 3 s and reload only when it moves
        import time as _t0
        if self._busy or self.mo.gmail_blocked() or _t0.time() < getattr(self, "_pause", 0) or not (self.isVisible() and self.ready() and self._loaded and self.stack.currentIndex() == 0 and not self.search.hasFocus()):
            return
        import time as _t
        self._busy = True

        def done(res, err):
            self._busy = False
            if err or not res:
                return
            changed = self._hid is not None and res != self._hid
            self._hid = res
            if changed or _t.time() - self._last_full > 90:
                self._last_full = _t.time()
                self._topen.clear()
                self.load_labels(quiet=True)
                self.load_list(reset=False, quiet=True)
        self.run(lambda: self.mo.gmail_call(self.S, "GET", "profile").get("historyId", ""), done)

    # ------------------------------------------------------------- sidebar
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.stack.currentIndex() == 1 and getattr(self, "msgs", None) and abs(self.sa.viewport().width() - getattr(self, "_rw", 0)) > 80:
            QTimer.singleShot(250, self._rerender)

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
                x0 = self.side.visualItemRect(it).left() + 14 + fm.horizontalAdvance("    " * info[0])
                if x0 - 6 <= ev.position().x() <= x0 + fm.horizontalAdvance("\u25be ") + 8:
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
            sg = lambda ls: [(x.get("id"), x.get("name"), (x.get("color") or {}).get("backgroundColor")) for x in ls]
            if sg(labs) != sg(self.labels):
                self.labels = labs
                self.lcol = {x.get("id"): (x.get("color") or {}).get("backgroundColor") or MAIL_NOCOL for x in labs}
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
                    params["labelIds"] = ["INBOX", MAIL_CATEGORIES[max(0, min(cat, len(MAIL_CATEGORIES) - 1))][0]]
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
            if len(self._lcache) > 40:
                self._lcache.pop(next(iter(self._lcache)))
            if not same:
                self._fill_list()
            self.say("")
        self.run(work, done)

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
            it.setSizeHint(_QSize(400, _MailRow.H))
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

    def modify(self, tids, add=(), remove=(), trash=False, cb=None):
        if self._need_modify() or not tids:
            return

        def work():
            for t in tids:
                if trash:
                    self.mo.gmail_call(self.S, "POST", "threads/%s/trash" % t, body={})
                else:
                    self.mo.gmail_call(self.S, "POST", "threads/%s/modify" % t, body={"addLabelIds": list(add), "removeLabelIds": list(remove)})
            return True

        def done(res, err):
            if err:
                self.say(err, True)
                return
            self._lcache.clear()
            self._topen.clear()
            if not trash:
                for t in tids:                                              # the squares in front of the rows follow at once
                    for r_ in self.rows:
                        if r_["id"] == t:
                            ls = (set(r_.get("labels") or []) | set(add)) - set(remove)
                            r_["labels"] = sorted(ls)
                            k_ = self._row_of(t)
                            if k_ >= 0:
                                self.list.item(k_).setData(ROLE_LABS, self._label_cols(r_["labels"]))
                self.list.viewport().update()
            if cb:
                cb()
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
        with self._tlock.setdefault(tid, _th.Lock()):                      # a click on a conversation that is being fetched waits for it instead of fetching again
            hit = self._topen.get(tid)
            if hit and _time.time() - hit[0] < 900:
                return hit[1]
            return self._fetch_thread2(tid)

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
            return True

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
        # the first few conversations are loaded in the background so the first clicks open at once
        ids = [r["id"] for r in self.rows[:12] if r["id"] not in self._topen and r["id"] not in self._tbusy]
        if not ids or not self.ready():
            return
        self._tbusy.update(ids)

        def work():
            for t in ids:
                try:
                    if self.mo.gmail_load() > 0.6 or self.mo.gmail_blocked():
                        break                                         # never spend the quota the user needs
                    self._fetch_thread(t)
                    self._thread_images(t)
                except Exception:
                    pass
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
        QTimer.singleShot(150, go)

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
        self.thread_lay.addWidget(MailPulse(self.MAIL_BLUE), 0, Qt.AlignmentFlag.AlignHCenter)
        self.thread_lay.addStretch(1)

        def work():
            return self._fetch_thread(tid)

        def done(res, err):
            if tid != self.cur:
                return
            self._clear_thread()
            if err:
                self.thread_lay.addWidget(_QL("Could not open it: " + err))
                return
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
                _html.escape(mail_name(fr)), _html.escape(_parseaddr(fr)[1]), mute, _html.escape(mail_date_text(m.get("internalDate", 0)) + "  " + mail_header(m, "Date")[:25]), mute,
                _html.escape(to or "me"), _html.escape(("   cc " + cc) if cc else "")))
            hd.setTextFormat(Qt.TextFormat.RichText)
            hd.setWordWrap(True)
            hd.setMinimumWidth(0)
            hd.setSizePolicy(_QSP.Policy.Ignored, _QSP.Policy.Preferred)
            cv.addWidget(hd)
            b = _AutoBrowser()
            body = html
            page_bg = None
            if body:
                body = re.sub(r"(?is)<(script|iframe|object|embed|link)\b.*?(</\1>|/>)", "", body)
                body = re.sub(r"(?is)<script.*?>.*?</script>", "", body)
            else:
                body = "<pre style='font-family:Arial;white-space:pre-wrap'>%s</pre>" % _html.escape(plain or m.get("snippet", ""))
            # received emails stay on white, as the sender designed them (the dark rendering cut the corners of the signature banner)
            b.setStyleSheet("QTextBrowser{background:%s;color:%s;border-radius:6px;padding:6px;}" % (page_bg or "#ffffff", "#eceef0" if page_bg else "#202124"))
            body = mail_fix_images(body, b.document(), inline, bool(self.S.get("mail_images")), max(320, self.sa.viewport().width() - 90))
            hidden = [] if self.S.get("mail_images") else [u for u in mail_web_images(html) if not mail_trusted_image(u)]
            if hidden:
                bar = _QPB("Show pictures from the web in this email")
                bar.clicked.connect(self._show_pictures)
                cv.addWidget(bar)
            b.setHtml(body)
            cv.addWidget(b)
            used = {x.lower() for x in re.findall(r"(?i)cid:([^\"'\s>)]+)", html or "")}
            files = [a for a in atts if a["name"] and not (a["cid"] and a["cid"].lower() in used)]
            if files:
                # attachment buttons wrap onto as many rows as the width needs (one long row made the whole email wider than the window)
                avail = max(300, self.sa.viewport().width() - 70)
                fmb = _QFM(self.font())
                rows, cur, used_w = [], [], 0
                for a in files[:60]:
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
                tools = _HB()
                if len(files) >= 2:
                    sa_ = _QPB("Save all (%d)" % len(files))
                    sa_.setToolTip("Save every attachment of this email into one folder you choose (it remembers the folder)")
                    sa_.clicked.connect(lambda _=False, fl=files, mid=m["id"]: self._save_all(mid, fl))
                    tools.addWidget(sa_)
                tools.addStretch(1)
                th_ = [a for a in files if ((a["mime"] in ("image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp")) or a["mime"] == "application/pdf" or a["name"].lower().endswith(".pdf"))
                       and a["size"] < 8000000][:16]
                thumbs = _HB()
                thumbs.addStretch(1)
                if th_:
                    cv.addLayout(thumbs)
                    if len(th_) <= 4:
                        self._thumbs(m["id"], th_, thumbs)
                    else:                                              # many pictures or drawings: fetched only when you ask (saves Gmail quota and time)
                        pb = _QPB("Show previews (%d)" % len(th_))
                        pb.setToolTip("Download and show a small preview of each PDF and picture")
                        pb.clicked.connect(lambda _=False, mid=m["id"], th_=th_, lay=thumbs, b=pb: (b.setEnabled(False), b.setText("Loading previews..."), self._thumbs(mid, th_, lay, b)))
                        tools.insertWidget(1 if len(files) >= 2 else 0, pb)
                cv.addLayout(tools)
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
                    data = mail_b64(a["data"]) if a.get("data") else self.mo.gmail_bytes(self.S, "messages/%s/attachments/%s" % (mid, a["id"]))
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
            data = mail_b64(a["data"]) if a.get("data") else self.mo.gmail_bytes(self.S, "messages/%s/attachments/%s" % (mid, a["id"]))
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
        quote = re.sub(r"(?is)<(script|style|iframe|object|embed|link)\b.*?(</\1>|/>)", "", quote)
        if kind == "forward":
            head = "<br><br>---------- Forwarded message ----------<br>From: %s<br>Date: %s<br>Subject: %s<br>To: %s<br><br>" % (
                _html.escape(mail_header(m, "From")), _html.escape(mail_header(m, "Date")), _html.escape(subj), _html.escape(mail_header(m, "To")))
            body = head + quote
            to = ""
        else:
            body = "<br><br>On %s, %s wrote:<blockquote style='margin:0 0 0 8px;border-left:2px solid #bbb;padding-left:10px'>%s</blockquote>" % (
                _html.escape(when), _html.escape(mail_name(mail_header(m, "From"))), quote)
        d = MailCompose(self, to, cc, subj2, body, in_reply_to=mail_header(m, "Message-ID") or mail_header(m, "Message-Id"),
                        references=mail_header(m, "References"), thread_id="" if kind == "forward" else (self.thread_view or {}).get("id", ""))
        d.exec()

    def compose(self):
        MailCompose(self).exec()

    def after_send(self):
        self._topen.clear()
        if self.label == "SENT" or self.label == "INBOX":
            self.load_list(reset=False, quiet=True)
