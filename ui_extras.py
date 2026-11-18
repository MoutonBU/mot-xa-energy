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
