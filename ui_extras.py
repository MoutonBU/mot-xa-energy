"""Small interface helpers: toasts with Undo, empty-state hints, drag-and-drop, the progress strip and the "What's new" window."""
import os
import re

import math
import sys

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, QSize, QTimer, Qt, QUrl, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QCursor, QPalette, QPainter, QPen, QRadialGradient
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
        p.drawPixmap(QRectF(-w / 2.0, -hh / 2.0, w, hh), self._pm, QRectF(self._pm.rect()))
        p.end()


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
