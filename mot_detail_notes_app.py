"""
MCP Architecture & Interiors - Detail Notes
Desktop app (same look and Python environment as the SANS Calc).

Open or drag in a DWG/DXF of a detail -> it reads the materials, writes the callout
notes (AI if an API key is saved, otherwise rules), places them with leaders and
saves <name>_noted.dwg + <name>_notes.txt into the "outputs" folder next to this file.
"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QGraphicsPathItem, QInputDialog, QCheckBox, QFrame, QTabWidget, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsEllipseItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter,
                               QListWidget, QListWidgetItem, QTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import detail_catalog as cat
import detail_to_dwg as core

HERE = Path(__file__).resolve().parent
# the installed program lives in a read-only folder: the notes and edits go to the user's own folder instead
OUT_DIR = (Path.home() / "MCP_XA_Energy" / "DetailNotes_outputs") if getattr(sys, "frozen", False) else (HERE / "outputs")
APP_NAME = "MCP Architecture & Interiors - Detail Notes"
CALC_SETTINGS = Path(os.environ.get("APPDATA") or Path.home()) / "MCP_LightVent" / "settings.json"
OWN_SETTINGS = Path(os.environ.get("APPDATA") or Path.home()) / "MCP_DetailNotes" / "settings.json"
RED = "#C8102E"

QSS = f"""
QWidget {{ background:#18181a; color:#e8e8ea; font-size:13px; }}
QFrame#panel {{ background:#1b1b1d; border:1px solid #2c2c30; border-radius:18px; }}
QFrame#section {{ background:#1b1b1d; border:1px solid #2c2c30; border-radius:12px; }}
QLabel {{ background:transparent; }}
QLabel#pill {{ background:{RED}; color:white; font-weight:700; border-radius:8px; padding:5px 14px; }}
QLabel#muted {{ color:#9a9aa2; }}
QLabel#brand {{ font-size:19px; font-weight:800; }}
QLabel#sub {{ color:#a8a8b0; font-size:11px; }}
QLabel#offline {{ background:#1d1d20; border:1px solid #34343a; border-radius:14px; padding:5px 16px; font-weight:700; }}
QLabel#status {{ color:#a8a8b0; }}
QPushButton {{ background:#232326; color:#e8e8ea; border:1px solid #38383d; padding:9px 18px; border-radius:9px; }}
QPushButton:hover {{ border:1px solid {RED}; background:#2a2a2e; }}
QPushButton:disabled {{ color:#6a6a72; border:1px solid #2c2c30; }}
QPushButton#primary {{ background:{RED}; border:1px solid {RED}; color:white; font-weight:700; }}
QPushButton#primary:hover {{ background:#e0243f; }}
QTabWidget::pane {{ border:0; }}
QTabBar::tab {{ background:transparent; color:#a8a8b0; padding:10px 22px; margin-right:6px; border-bottom:2px solid transparent; font-size:14px; }}
QTabBar::tab:selected {{ color:white; font-weight:700; background:#232326; border-radius:9px; border-bottom:2px solid {RED}; }}
QTableWidget {{ background:#1b1b1d; gridline-color:#2a2a2e; border:1px solid #2c2c30; border-radius:8px; selection-background-color:#5a0a18; }}
QHeaderView::section {{ background:#222226; color:#cfcfd4; padding:5px; border:0; }}
QLineEdit, QDoubleSpinBox {{ background:#151517; border:1px solid #34343a; padding:6px 8px; border-radius:7px; }}
QCheckBox::indicator {{ width:17px; height:17px; border:1px solid #4a4a52; border-radius:4px; background:#151517; }}
QCheckBox::indicator:checked {{ background:{RED}; border:1px solid {RED}; }}
QGraphicsView {{ border:1px solid #2c2c30; border-radius:8px; }}
QSplitter::handle {{ background:transparent; }}
"""


# ---------------------------------------------------------------- settings
def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, indent=2), encoding="utf-8")


def api_key():
    return (os.environ.get("ANTHROPIC_API_KEY") or read_json(CALC_SETTINGS).get("api_key", "")).strip()


def api_model():
    return (read_json(CALC_SETTINGS).get("model") or "").strip() or core.MODEL


def ai_request(prompt, image_b64, key, model):
    body = {"model": model, "max_tokens": 4000, "system": core.STYLE_GUIDE,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"Claude said: {msg or e.reason} (code {e.code})")
    except urllib.error.URLError as e:
        raise RuntimeError(f"No internet connection ({e.reason})")
    return "".join(p.get("text", "") for p in data.get("content", []))


class Worker(QThread):
    done = Signal(object)
    fail = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as ex:
            self.fail.emit(str(ex))


# ---------------------------------------------------------------- preview
class View(QGraphicsView):
    clicked = Signal(float, float, int)      # x, y (drawing units), 1 = left / 2 = right
    moved = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#1a1a1a"))
        self.setMouseTracking(True)
        self.scale(1, -1)  # DXF y is up
        self.tool = None
        self.snaps = None                    # numpy array of snap points
        self._pan = None
        self._mark = None
        self._rub = None

    def set_tool(self, on):
        self.tool = on
        self.setDragMode(QGraphicsView.DragMode.NoDrag if on else QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.show_snap(0, 0, False)
        self.rubber(None)

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def fit(self):
        sc = self.scene()
        if sc and not sc.itemsBoundingRect().isEmpty():
            self.fitInView(sc.itemsBoundingRect().adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)

    # ---- snapping to the drawing's own points
    def snap(self, sp):
        x, y = sp.x(), sp.y()
        if self.snaps is None or len(self.snaps) == 0:
            return x, y, False
        import numpy as np
        tol = 14 / max(abs(self.transform().m11()), 1e-9)
        d = np.hypot(self.snaps[:, 0] - x, self.snaps[:, 1] - y)
        i = int(d.argmin())
        if d[i] <= tol:
            return float(self.snaps[i, 0]), float(self.snaps[i, 1]), True
        return x, y, False

    def _pt(self, e):
        if self.tool in ("spec", "edit", "del"):      # picking a part needs the exact spot, not the nearest corner
            p = self.mapToScene(e.position().toPoint())
            return p.x(), p.y(), False
        return self.snap(self.mapToScene(e.position().toPoint()))

    def show_snap(self, x, y, on):
        sc = self.scene()
        if sc is None:
            return
        try:
            gone = self._mark is None or self._mark.scene() is not sc
        except RuntimeError:          # the scene was rebuilt and took the marker with it
            gone = True
        if gone:
            self._mark = QGraphicsEllipseItem(-5, -5, 10, 10)
            self._mark.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
            self._mark.setPen(QPen(QColor("#00e5ff"), 2))
            self._mark.setZValue(1e7)
            sc.addItem(self._mark)
        self._mark.setPos(x, y)
        self._mark.setVisible(bool(on))

    def rubber(self, pts, closed=False):
        sc = self.scene()
        if sc is None:
            return
        try:
            gone = self._rub is None or self._rub.scene() is not sc
        except RuntimeError:
            gone = True
        if gone:
            self._rub = QGraphicsPathItem()
            pen = QPen(QColor("#00e5ff"), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._rub.setPen(pen)
            self._rub.setZValue(1e7)
            sc.addItem(self._rub)
        if not pts or len(pts) < 2:
            self._rub.setVisible(False)
            return
        path = QPainterPath()
        path.moveTo(*pts[0])
        for q in pts[1:]:
            path.lineTo(*q)
        if closed:
            path.closeSubpath()
        self._rub.setPath(path)
        self._rub.setVisible(True)

    # ---- mouse: tools draw with left click, right click finishes, middle button pans
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.tool and e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            x, y, _ = self._pt(e)
            self.clicked.emit(x, y, 1 if e.button() == Qt.MouseButton.LeftButton else 2)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.tool:
            x, y, on = self._pt(e)
            self.show_snap(x, y, on)
            self.moved.emit(x, y)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
            return
        if self.tool:
            return
        super().mouseReleaseEvent(e)


def collect_snaps(doc):
    """end points / corners of everything in the detail, for snapping"""
    import numpy as np
    from ezdxf import path as ezpath
    pts = []
    for e in doc.modelspace():
        try:
            t = e.dxftype()
            if t == "LINE":
                pts += [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif t == "LWPOLYLINE":
                pts += [(p[0], p[1]) for p in e.get_points()]
            elif t == "HATCH":
                for pth in ezpath.from_hatch(e):
                    pts += [(v.x, v.y) for v in pth.control_vertices]
        except Exception:
            continue
        if len(pts) > 60000:
            break
    return np.array(pts, dtype=float) if pts else None


def build_scene(doc):
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.pyqt import PyQtBackend
    scene = QGraphicsScene()
    Frontend(RenderContext(doc), PyQtBackend(scene)).draw_layout(doc.modelspace(), finalize=True)
    return scene


def marked_image_b64(scene, items):
    markers = []
    for it in items:
        e = QGraphicsEllipseItem(-11, -11, 22, 22)
        e.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
        e.setBrush(QColor(RED))
        e.setPen(QColor("white"))
        e.setPos(*it["point"])
        e.setZValue(1e6)
        t = QGraphicsSimpleTextItem(str(it["id"]), e)
        f = t.font()
        f.setBold(True)
        f.setPointSize(9)
        t.setFont(f)
        t.setBrush(QColor("white"))
        r = t.boundingRect()
        t.setPos(-r.width() / 2, -r.height() / 2)
        scene.addItem(e)
        markers.append(e)
    v = View()
    v.setScene(scene)
    v.resize(1500, 1100)
    v.show()
    QApplication.processEvents()
    v.fit()
    QApplication.processEvents()
    img = v.grab().toImage()
    v.hide()
    for m in markers:
        scene.removeItem(m)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(ba)).decode()


# ---------------------------------------------------------------- settings dialog
class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.key = QLineEdit(api_key())
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Anthropic API key (shared with the SANS Calc)")
        form.addRow("API key", self.key)
        row = QHBoxLayout()
        self.oda = QLineEdit(core.find_oda() or "")
        b = QPushButton("Browse...")
        b.clicked.connect(self.browse)
        row.addWidget(self.oda)
        row.addWidget(b)
        form.addRow("ODA File Converter", row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "ODAFileConverter.exe", "", "Program (*.exe)")
        if p:
            self.oda.setText(p)

    def save(self):
        d = read_json(CALC_SETTINGS)
        if self.key.text().strip() != d.get("api_key", ""):
            d["api_key"] = self.key.text().strip()
            d.setdefault("provider", "Claude (Anthropic)")
            write_json(CALC_SETTINGS, d)
        o = read_json(OWN_SETTINGS)
        o["oda"] = self.oda.text().strip()
        write_json(OWN_SETTINGS, o)
        if o["oda"]:
            os.environ["ODA_CONVERTER"] = o["oda"]


# ---------------------------------------------------------------- main window
def load_custom():
    return [d for d in read_json(OWN_SETTINGS).get("custom_specs", []) if d.get("label") and d.get("note")]


def save_custom(entry):
    o = read_json(OWN_SETTINGS)
    lst = [d for d in o.get("custom_specs", []) if d.get("label") != entry["label"]]
    lst.append(entry)
    o["custom_specs"] = lst
    write_json(OWN_SETTINGS, o)


class SpecDialog(QDialog):
    """Pick a specification from the catalog for one part of the detail. The note can be edited before it is used."""

    def __init__(self, parent, title, cat_name, measured=None, current="", name=""):
        super().__init__(parent)
        self.name = name
        self.setWindowTitle("Choose specification")
        self.resize(980, 640)
        self.note = ""
        self.custom = load_custom()
        self.measured = measured
        v = QVBoxLayout(self)
        head = QLabel("<b>%s</b>" % title + (f"  &middot;  drawn thickness about <b>{measured} mm</b>" if measured else ""))
        v.addWidget(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the whole catalog, e.g. 170, purlin, DPC, gutter, 50 x 50...")
        self.search.setClearButtonEnabled(True)
        v.addWidget(self.search)
        row = QHBoxLayout()
        self.cats = QListWidget()
        self.cats.setMaximumWidth(250)
        self.opts = QListWidget()
        row.addWidget(self.cats)
        row.addWidget(self.opts, 1)
        v.addLayout(row, 1)
        v.addWidget(QLabel("Note on the drawing (you can change the wording):"))
        self.text = QTextEdit()
        self.text.setMaximumHeight(90)
        self.text.setAcceptRichText(False)
        v.addWidget(self.text)
        br = QHBoxLayout()
        self.cnt = QLabel(f"{cat.count()} specifications in the catalog")
        self.cnt.setObjectName("muted")
        br.addWidget(self.cnt)
        br.addStretch()
        bs = QPushButton("Save this note to My specs...")
        bs.clicked.connect(self.save_mine)
        bo = QPushButton("Use this note")
        bo.setObjectName("primary")
        bo.setDefault(True)
        bo.clicked.connect(self.use)
        bc = QPushButton("Cancel")
        bc.clicked.connect(self.reject)
        for b_ in (bs, bc, bo):
            br.addWidget(b_)
        v.addLayout(br)
        self._cur = current
        self._fill_cats()
        names = [self.cats.item(i).text() for i in range(self.cats.count())]
        self.cats.setCurrentRow(names.index(cat_name) if cat_name in names else 0)
        self.cats.currentRowChanged.connect(lambda *_: self._fill_opts())
        self.opts.currentRowChanged.connect(self._pick)
        self.opts.itemDoubleClicked.connect(lambda *_: self.use())
        self.search.textChanged.connect(self._search)
        self._fill_opts(select=True)
        if current:
            self.text.setPlainText(current)

    def _all(self):
        d = {k: list(v) for k, v in cat.CATALOG.items()}
        if self.custom:
            d["My specs"] = [(c["label"], c["note"]) for c in self.custom]
        return d

    def _fill_cats(self):
        self.cats.clear()
        for k in self._all():
            self.cats.addItem(k)

    def _fill_opts(self, select=False):
        if self.search.text().strip():
            return
        k = self.cats.currentItem().text() if self.cats.currentItem() else None
        opts = self._all().get(k, [])
        self._show(opts, [None] * len(opts))
        if select and opts:
            m_ = re.search(r"(\d+)\s*mm", self.name or "")
            self.opts.setCurrentRow(cat.match_index(opts, self.name, float(m_.group(1)) if m_ else self.measured))

    def _show(self, opts, cats):
        self.opts.blockSignals(True)
        self.opts.clear()
        self._notes = []
        for (lab, note), c in zip(opts, cats):
            it = QListWidgetItem(lab if not c else f"{lab}   [{c}]")
            it.setToolTip(note)
            self.opts.addItem(it)
            self._notes.append(note)
        self.opts.blockSignals(False)

    def _search(self, txt):
        t = txt.strip().lower()
        if not t:
            self._fill_opts()
            return
        words = t.split()
        hits, cats = [], []
        for k, lst in self._all().items():
            for lab, note in lst:
                hay = (lab + " " + note + " " + k).lower()
                if all(w in hay for w in words):
                    hits.append((lab, note))
                    cats.append(k)
        self._show(hits, cats)
        self.cnt.setText(f"{len(hits)} found")
        if hits:
            self.opts.setCurrentRow(0)

    def _pick(self, r):
        if 0 <= r < len(self._notes):
            self.text.setPlainText(self._notes[r])

    def save_mine(self):
        txt = " ".join(self.text.toPlainText().split())
        if not txt:
            return
        lab, ok = QInputDialog.getText(self, "My specs", "Short name for this spec in the list:")
        if ok and lab.strip():
            e = {"label": lab.strip(), "note": txt}
            save_custom(e)
            self.custom = load_custom()
            self.search.clear()
            self._fill_cats()
            names = [self.cats.item(i).text() for i in range(self.cats.count())]
            self.cats.setCurrentRow(names.index("My specs"))

    def use(self):
        self.note = " ".join(self.text.toPlainText().split())
        if self.note:
            self.accept()


class Win(QMainWindow):
    def __init__(self, embedded=False):
        super().__init__()
        self.embedded = embedded
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 860)
        for n in ("mcp_logo.ico", "mcp_logo.png"):
            if (HERE / n).exists():
                self.setWindowIcon(QIcon(str(HERE / n)))
                break
        oda = read_json(OWN_SETTINGS).get("oda")
        if oda and os.path.exists(oda):
            os.environ["ODA_CONVERTER"] = oda
        self.src = None
        self.work_dxf = None
        self.items, self.texts, self.mmu = [], [], 1.0
        self.worker = None
        self.last_out = None
        self.first_apply = True
        self.report = []
        self.added = {}
        self.setAcceptDrops(True)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 14, 26, 18)

        # header: centred logo + title, status pill top-right
        head = QVBoxLayout()
        head.setSpacing(2)
        row = QHBoxLayout()
        row.addStretch()
        self.pill_online = QLabel("Offline")
        self.pill_online.setObjectName("offline")
        row.addWidget(self.pill_online)
        head.addLayout(row)
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if (HERE / "mcp_logo.png").exists():
            from PySide6.QtGui import QPixmap
            logo.setPixmap(QPixmap(str(HERE / "mcp_logo.png")).scaledToHeight(64, Qt.TransformationMode.SmoothTransformation))
        head.addWidget(logo)
        from PySide6.QtGui import QFont
        t = QLabel("MCP ARCHITECTURE & INTERIORS")
        t.setObjectName("brand")
        f = t.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        t.setFont(f)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(t)
        sub = QLabel("Detail Notes  \u00b7  Callouts, Brickwork & Colours")
        sub.setObjectName("sub")
        f2 = sub.font()
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        sub.setFont(f2)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(sub)
        hw = QWidget()
        hw.setLayout(head)
        outer.addWidget(hw)
        if embedded:      # inside the suite the tab already has the program's own header
            hw.hide()

        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 22, 26, 18)
        self.tabs = QTabWidget()
        pl.addWidget(self.tabs)
        outer.addWidget(panel, 1)

        def section(title):
            """red pill heading above a rounded box; returns the box's layout"""
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 6)
            v.setSpacing(0)
            pill = QLabel(title)
            pill.setObjectName("pill")
            pr = QHBoxLayout()
            pr.setContentsMargins(14, 0, 0, 0)
            pr.addWidget(pill)
            pr.addStretch()
            v.addLayout(pr)
            box = QFrame()
            box.setObjectName("section")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(16, 14, 16, 14)
            v.addWidget(box)
            return w, bl

        # ---- tab 1: Home
        home = QWidget()
        hl = QVBoxLayout(home)
        hl.setContentsMargins(0, 14, 0, 0)

        w1, l1 = section("Step 1   Your detail")
        d1 = QLabel("Drag a DWG or DXF of your detail anywhere into this window, or open one. "
                    "The notes are written and saved for you.")
        d1.setObjectName("muted")
        d1.setWordWrap(True)
        l1.addWidget(d1)
        self.lbl_file = QLabel("No detail opened yet.")
        l1.addWidget(self.lbl_file)
        r1 = QHBoxLayout()
        self.btn_open = QPushButton("Open DWG / DXF...")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self.pick_file)
        self.btn_folder = QPushButton("Open outputs folder")
        self.btn_folder.clicked.connect(self.open_outputs)
        self.btn_set = QPushButton("Settings...")
        self.btn_set.clicked.connect(self.settings)
        for b_ in (self.btn_open, self.btn_folder, self.btn_set):
            r1.addWidget(b_)
        r1.addStretch()
        l1.addLayout(r1)
        hl.addWidget(w1)

        w2, l2 = section("Step 2   Look")
        d2 = QLabel("Fills follow the house colours, and brick walls are drawn as real bricks with mortar joints.")
        d2.setObjectName("muted")
        l2.addWidget(d2)
        r2 = QHBoxLayout()
        self.house_cols = QCheckBox("Match house colours")
        self.house_cols.setChecked(True)
        self.do_brick = QCheckBox("Draw brickwork as real bricks")
        self.do_brick.setChecked(True)
        self.brick_h = QDoubleSpinBox()
        self.brick_h.setRange(40, 150)
        self.brick_h.setValue(85)
        self.brick_h.setSuffix(" mm brick")
        self.joint = QDoubleSpinBox()
        self.joint.setRange(5, 20)
        self.joint.setValue(10)
        self.joint.setSuffix(" mm mortar")
        for w_ in (self.house_cols, self.do_brick, self.brick_h, self.joint):
            r2.addWidget(w_)
        r2.addStretch()
        l2.addLayout(r2)
        self.draw_missing = QCheckBox("Also draw missing elements to SA practice (purlins, brickforce, DPM, DPC...)")
        self.draw_missing.setChecked(False)
        l2.addWidget(self.draw_missing)
        hl.addWidget(w2)

        w3, l3 = section("Step 3   Notes")
        r3 = QHBoxLayout()
        self.scale = QDoubleSpinBox()
        self.scale.setRange(1, 500)
        self.scale.setValue(10)
        self.scale.setPrefix("Scale 1 : ")
        self.text_mm = QDoubleSpinBox()
        self.text_mm.setRange(1, 10)
        self.text_mm.setValue(3.0)
        self.text_mm.setSuffix(" mm text")
        self.note_w = QDoubleSpinBox()
        self.note_w.setRange(30, 250)
        self.note_w.setValue(65)
        self.note_w.setSuffix(" mm wide")
        self.clear_old = QCheckBox("Clear existing text && leaders first")
        self.number_notes = QCheckBox("Number the notes")
        self.number_notes.setChecked(True)
        self.number_notes.setToolTip("Put 1, 2, 3... in front of each callout, the same numbers as the saved notes list.")
        for w_ in (self.scale, self.text_mm, self.note_w, self.clear_old, self.number_notes):
            r3.addWidget(w_)
        r3.addStretch()
        l3.addLayout(r3)
        d3 = QLabel("Everything updates by itself when you change a setting or edit a note.")
        d3.setObjectName("muted")
        l3.addWidget(d3)
        hl.addWidget(w3)

        w4, l4 = section("Step 4   Completeness check")
        self.lbl_report = QLabel("Open a detail to check it against SA practice.")
        self.lbl_report.setObjectName("muted")
        self.lbl_report.setWordWrap(True)
        self.lbl_report.setTextFormat(Qt.TextFormat.RichText)
        l4.addWidget(self.lbl_report)
        hl.addWidget(w4)
        hl.addStretch()
        self.tabs.addTab(home, "Setup")

        # ---- tab 2: preview + notes
        nt = QWidget()
        nl = QVBoxLayout(nt)
        nl.setContentsMargins(0, 14, 0, 0)
        top = QHBoxLayout()
        b_open = QPushButton("Open DWG / DXF...")
        b_open.setObjectName("primary")
        b_open.clicked.connect(self.pick_file)
        b_fold = QPushButton("Outputs folder")
        b_fold.clicked.connect(self.open_outputs)
        b_set = QPushButton("Settings...")
        b_set.clicked.connect(self.settings)
        for b_ in (b_open, b_fold, b_set):
            top.addWidget(b_)
        self.lbl_file2 = QLabel("Open a detail, then click a part of it to choose its specification.")
        self.lbl_file2.setObjectName("muted")
        top.addWidget(self.lbl_file2, 1)
        nl.addLayout(top)
        tbm = QHBoxLayout()                       # the two modes: auto, or by clicking
        tb = QHBoxLayout()                        # extra drawing tools (hidden until asked for)
        self.user = []
        self.uid = 0
        self.overrides = {}
        self.hgeo = {}
        self.edit_doc = None
        self.tool = None
        self.specs = {}
        self.pend = []
        self.roof_dir = None
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_btns = {}
        self.btn_auto = QPushButton("Auto note everything")
        self.btn_auto.setObjectName("primary")
        self.btn_auto.setToolTip("Writes a note for every part of the detail in one go. You can still change any note afterwards.")
        self.btn_auto.clicked.connect(self.auto_all)
        tbm.addWidget(self.btn_auto)
        tbm.addSpacing(14)
        tbm.addWidget(QLabel("or by hand:"))
        for key, label in (("spec", "Click a part and choose its spec"), ("pan", "Pan / zoom"), ("sheet", "Roof sheet"), ("purlin", "Purlin"), ("box", "Fill box"),
                           ("line", "Line"), ("note", "Note"), ("edit", "Edit fill"), ("del", "Delete")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            self.tool_btns[key] = b
            (tbm if key in ("spec", "pan") else tb).addWidget(b)
        self.tool_btns["spec"].setChecked(True)
        self.mat_combo = QComboBox()
        for k, (lab, _rgb, _n) in core.USER_MATS.items():
            self.mat_combo.addItem(lab, k)
        self.mat_combo.setToolTip("Material for the Fill box tool")
        tb.addWidget(self.mat_combo)
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo_user)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo_user)
        self.hist, self.redo = [], []
        from PySide6.QtGui import QKeySequence, QShortcut
        for keys_, fn_ in (("Ctrl+Z", self.undo_user), ("Ctrl+Y", self.redo_user), ("Ctrl+Shift+Z", self.redo_user),
                           ("Esc", lambda: (self.tool_btns["pan"].setChecked(True), self.set_tool("pan")))):
            sc_ = QShortcut(QKeySequence(keys_), self)
            sc_.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc_.activated.connect(fn_)
        self.btn_clear_user = QPushButton("Clear mine")
        self.btn_clear_user.clicked.connect(self.clear_user)
        tb.addWidget(self.btn_clear_user)
        tb.addStretch()
        tbm.addStretch()
        tbm.addWidget(self.btn_undo)
        tbm.addWidget(self.btn_redo)
        self.btn_more = QPushButton("More tools")
        self.btn_more.setCheckable(True)
        self.btn_more.setToolTip("Draw your own roof sheets, purlins, fill boxes and lines, edit a fill, delete your own elements")
        tbm.addWidget(self.btn_more)
        nl.addLayout(tbm)
        self.more = QWidget()
        self.more.setLayout(tb)
        tb.setContentsMargins(0, 0, 0, 0)
        self.more.setVisible(False)
        self.btn_more.toggled.connect(self.more.setVisible)
        nl.addWidget(self.more)
        self.tool_hint = QLabel("")
        self.tool_hint.setObjectName("muted")
        nl.addWidget(self.tool_hint)
        split = QSplitter()
        self.view = View()
        self.view.clicked.connect(self.on_click)
        self.view.moved.connect(self.on_move)
        self.view.setScene(QGraphicsScene())
        split.addWidget(self.view)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Note (edit freely)", "Check", "Material"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        split.addWidget(self.table)
        split.setSizes([760, 600])
        nl.addWidget(split, 1)
        br = QHBoxLayout()
        self.btn_gen = QPushButton("Suggest notes for everything (optional)")
        self.btn_gen.clicked.connect(self.generate)
        self.btn_gen.setEnabled(False)
        self.btn_apply = QPushButton("Save now")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(lambda: self.apply_and_save())
        self.btn_apply.setEnabled(False)
        self.btn_choose = QPushButton("Choose spec for selected note")
        self.btn_choose.clicked.connect(lambda: self.row_spec(self.table.currentRow()))
        self.btn_remove = QPushButton("Remove selected note")
        self.btn_remove.clicked.connect(self.remove_note)
        br.addWidget(self.btn_choose)
        br.addWidget(self.btn_remove)
        br.addStretch()
        self.btn_gen.setVisible(False)
        br.addWidget(self.btn_apply)
        nl.addLayout(br)
        self.tabs.addTab(nt, "Detail")
        self.tabs.tabBar().moveTab(1, 0)          # the workspace comes first, the settings second
        self.tabs.setCurrentIndex(0)

        # auto-update: any change redraws + saves after a short pause
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.auto_apply)
        for sp in (self.scale, self.text_mm, self.note_w, self.brick_h, self.joint):
            sp.valueChanged.connect(lambda *_: self.timer.start())
        for cb_ in (self.clear_old, self.number_notes, self.house_cols, self.do_brick, self.draw_missing):
            cb_.toggled.connect(lambda *_: self.timer.start())
        self.table.itemChanged.connect(lambda *_: self.timer.start())
        self.table.cellDoubleClicked.connect(lambda r, c: self.row_spec(r) if c != 1 else None)
        from PySide6.QtGui import QKeySequence as _QKS, QShortcut as _QSC
        _del = _QSC(_QKS("Delete"), self.table)
        _del.setContext(Qt.ShortcutContext.WidgetShortcut)
        _del.activated.connect(self.remove_note)
        self.status = QLabel("Drag a DWG or DXF of your detail into this window.")
        self.status.setObjectName("status")
        outer.addWidget(self.status)
        self.refresh_pill()
        self.set_tool("spec")

    # ---- helpers
    def show_report(self, report, drawing=True):
        if not report:
            self.lbl_report.setText("Nothing to check for this detail type.")
            return
        bits = []
        for label, st in report:
            if st == "ok":
                bits.append(f'<span style="color:#7ddc8f">&#10004; {label}</span>')
            elif st == "added" and drawing:
                bits.append(f'<span style="color:#ff5a6e"><b>+ {label} &mdash; was missing, drawn</b></span>')
            elif st == "added":
                bits.append(f'<span style="color:#e6b450">&#9888; {label} &mdash; missing (tick "Draw missing elements")</span>')
            else:
                bits.append(f'<span style="color:#e6b450">&#9888; {label} &mdash; not in the detail, add by hand</span>')
        self.lbl_report.setText("<br>".join(bits))

    def refresh_pill(self):
        on = bool(api_key())
        self.pill_online.setText("AI on" if on else "Offline")
        self.pill_online.setStyleSheet(f"border:1px solid {RED};" if on else "")

    def say(self, msg):
        self.status.setText(msg)
        QApplication.processEvents()

    def settings(self):
        d = SettingsDialog(self)
        if d.exec():
            d.save()
            self.refresh_pill()

    def open_outputs(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUT_DIR)))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith((".dwg", ".dxf")):
                self.open_file(u.toLocalFile())
                break

    def pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open detail", str(Path.home() / "Desktop"),
                                           "Drawings (*.dwg *.dxf)")
        if p:
            self.open_file(p)

    def need_oda(self):
        """DWG needs ODA File Converter. Offer ways forward; True if it is now available."""
        box = QMessageBox(self)
        box.setWindowTitle("DWG reader needed")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("To read .dwg files this app needs ODA File Converter, which is not installed yet.")
        box.setInformativeText(
            "Option 1: install it (opendesign.com - check their current licence terms), then choose "
            "\"I have it - find it\".\n\n"
            "Option 2: no install - in Archicad use File > Save As > DXF for the detail and drop that "
            ".dxf here. It works the same, and you get a .dxf back to open in Archicad and save as DWG.")
        b_web = box.addButton("Get ODA File Converter", QMessageBox.ButtonRole.ActionRole)
        b_find = box.addButton("I have it - find it...", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_web:
            QDesktopServices.openUrl(QUrl("https://www.opendesign.com/guestfiles/oda_file_converter"))
            return False
        if c is b_find:
            p, _ = QFileDialog.getOpenFileName(self, "Find ODAFileConverter.exe",
                                               "C:\\Program Files", "ODAFileConverter.exe (*.exe)")
            if p and "odafileconverter" in p.lower():
                os.environ["ODA_CONVERTER"] = p
                o = read_json(OWN_SETTINGS)
                o["oda"] = p
                write_json(OWN_SETTINGS, o)
                return True
        return False

    # ---- open
    def open_file(self, path):
        try:
            self.src = Path(path)
            self.say("Reading drawing...")
            if self.src.suffix.lower() == ".dwg":
                if not core.find_oda() and not self.need_oda():
                    self.say("Ready.")
                    return
                self.say("Converting DWG...")
                self.work_dxf = core.oda_convert(self.src, "DXF")
                if not self.work_dxf:
                    raise RuntimeError("ODA File Converter could not convert this DWG. Save it as .dxf and open that.")
            else:
                self.work_dxf = self.src
            doc = core.load_doc(self.work_dxf)
            self.mmu = core.mm_per_unit(doc)
            self.items, self.texts, self.extents = core.extract_items(doc)
            if not self.items:
                raise RuntimeError("No hatches found - export the detail with its fills/hatches.")
            plan = core.completeness(doc, self.texts, self.items, self.mmu,
                                     self.brick_h.value(), self.joint.value(), True)
            self.added = {}
            nid = len(self.items) + 1
            for a in plan["adds"]:
                it = {"id": nid, "layer": core.ADD_LAYER, "pattern": a["label"], "color": 7,
                      "area": a["area"], "point": a["point"], "bbox": a["bbox"], "count": 1,
                      "poly": a["geom"], "synthetic": True, "key": a["key"], "note": a["note"]}
                self.items.append(it)
                self.added[a["key"]] = it
                nid += 1
            self.report = plan["report"]
            self.show_report(self.report, self.draw_missing.isChecked())
            self.user, self.uid = [], 0
            self.edit_doc, self.hgeo = doc, {}
            self.overrides = dict(read_json(self.edits_path()).get("overrides", {}))
            try:
                for el in read_json(self.edits_path()).get("elements", []):
                    el["pts"] = [tuple(p) for p in el["pts"]]
                    if el.get("dir"):
                        el["dir"] = tuple(el["dir"])
                    self.uid = max(self.uid, el["uid"])
                    self.user.append(el)
                    if el["type"] != "line":
                        self.items.append(core.user_item(el, self.mmu, nid))
                        nid += 1
            except Exception:
                pass
            self.specs = {}
            self.table.setRowCount(0)
            for hid, sp in (read_json(self.edits_path()).get("specs", {}) or {}).items():
                try:
                    self.restore_spec(hid, sp)
                except Exception:
                    traceback.print_exc()
            self.roof_dir = core.roof_direction(doc)
            self.view.snaps = collect_snaps(doc)
            self.view.setScene(build_scene(doc))
            self.view.fit()
            self.first_apply = True
            self.btn_gen.setEnabled(True)
            self.btn_apply.setEnabled(True)
            self.lbl_file.setText(f"Opened: {self.src}")
            self.lbl_file2.setText(f"Opened: {self.src.name}   -   click a part of the detail to choose its specification")
            self.say(f"{self.src.name}: {len(self.items)} materials found. Click a part of the detail to choose its specification.")
            self.timer.start()               # show the detail in house colours and real bricks straight away
        except Exception as ex:
            traceback.print_exc()
            QMessageBox.warning(self, "Could not open", str(ex))
            self.say("Ready.")

    # ---- your own detailing
    HINTS = {
        "spec": "Click a part of the detail (concrete, brick, stone, insulation, waterproofing...) and choose what it is from the catalog. Double-click a note in the list to change it.",
        "pan": "Drag to move the drawing, wheel to zoom.",
        "sheet": "Roof sheet: click the start, then the end of the roof line. The sheet profile snaps to the drawing and gets its own note.",
        "purlin": "Purlin: click where the 76 x 50 purlin goes (it follows the roof slope).",
        "box": "Fill box: pick a material in the list, click two opposite corners.",
        "line": "Line: click the points, right-click to finish.",
        "note": "Note: click the spot, then type the note text.",
        "edit": "Edit fill: click any fill in the drawing (e.g. the yellow box over the gutter) to recolour it as another material or delete it.",
        "del": "Delete: click one of your own elements to remove it.",
    }

    def set_tool(self, key):
        self.tool = None if key == "pan" else key
        self.pend = []
        self.view.set_tool(self.tool)
        self.tool_hint.setText(self.HINTS[key] + ("  (middle mouse button pans)" if self.tool else ""))

    def on_move(self, x, y):
        t = self.tool
        if t in ("sheet", "line") and self.pend:
            self.view.rubber(self.pend + [(x, y)])
        elif t == "box" and self.pend:
            (x0, y0) = self.pend[0]
            self.view.rubber([(x0, y0), (x, y0), (x, y), (x0, y)], closed=True)
        else:
            self.view.rubber(None)

    def on_click(self, x, y, btn):
        t = self.tool
        if not self.items:
            return
        if t == "spec":
            if btn == 1 or btn == 0 or btn is None:
                self.pick_spec(x, y)
            return
        if btn == 2:
            if t == "line" and len(self.pend) >= 2:
                self.add_user({"type": "line", "pts": list(self.pend)})
            self.pend = []
            self.view.rubber(None)
            return
        if t == "sheet":
            self.pend.append((x, y))
            if len(self.pend) == 2:
                if self.pend[0] != self.pend[1]:
                    self.add_user({"type": "sheet", "pts": list(self.pend), "note": core.NOTE_SHEET})
                self.pend = []
                self.view.rubber(None)
        elif t == "purlin":
            d = None
            for el in reversed(self.user):
                if el["type"] == "sheet":
                    a, b = el["pts"]
                    L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                    d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
                    break
            d = d or self.roof_dir or (1.0, 0.0)
            self.add_user({"type": "purlin", "pts": [(x, y)], "dir": d, "note": core.NOTE_PURLIN})
        elif t == "box":
            self.pend.append((x, y))
            if len(self.pend) == 2:
                mat = self.mat_combo.currentData()
                self.add_user({"type": "rect", "pts": list(self.pend), "mat": mat,
                               "note": core.USER_MATS[mat][2]})
                self.pend = []
                self.view.rubber(None)
        elif t == "line":
            self.pend.append((x, y))
        elif t == "note":
            text, ok = QInputDialog.getText(self, "Add note", "Note text:")
            if ok and text.strip():
                self.add_user({"type": "note", "pts": [(x, y)], "note": text.strip()})
        elif t == "edit":
            self.edit_fill(x, y)
        elif t == "del":
            self.delete_near(x, y)

    def add_user(self, el, rec=True):
        if rec:
            self.hist.append(("add", el))
            self.redo = []
        self.uid += 1
        el["uid"] = self.uid
        self.user.append(el)
        nid = max([i["id"] for i in self.items] + [0]) + 1
        if el["type"] != "line":                     # plain lines carry no note
            self.items.append(core.user_item(el, self.mmu, nid))
        self.user_changed()

    def remove_user(self, uid):
        self.user = [e for e in self.user if e["uid"] != uid]
        self.items = [i for i in self.items if i.get("user") != uid]

    def edit_fill(self, x, y):
        """pick the smallest original fill under the click and recolour / delete it"""
        from shapely.geometry import Point
        if self.edit_doc is None:
            return
        pt, best = Point(x, y), None
        for h in self.edit_doc.modelspace().query("HATCH"):
            if h.dxf.layer.startswith("MOT_"):
                continue
            hid = str(h.dxf.handle)
            if hid not in self.hgeo:
                try:
                    self.hgeo[hid] = core.hatch_geometry(h)
                except Exception:
                    self.hgeo[hid] = None
            g = self.hgeo[hid]
            if g is not None and g.contains(pt) and (best is None or g.area < best[0].area):
                best = (g, h)
        if not best:
            self.say("No fill under that point.")
            return
        g, h = best
        ring = list(core._polys(g)[0].exterior.coords) if core._polys(g) else []
        self.view.rubber(ring, closed=True)
        hid = str(h.dxf.handle)
        cur = self.overrides.get(hid)
        choices = ["Keep as drawn"] + ["Make it: " + v[0] for v in core.USER_MATS.values()] + ["Delete this fill"]
        keys = [None] + list(core.USER_MATS.keys()) + ["delete"]
        name = core.clean_name(h.dxf.pattern_name) if not h.dxf.solid_fill else "solid fill"
        item, ok = QInputDialog.getItem(self, "Edit fill", f"{h.dxf.layer} / {name}\nWhat should this fill be?",
                                        choices, keys.index(cur) if cur in keys else 0, False)
        self.view.rubber(None)
        if not ok:
            return
        act = keys[choices.index(item)]
        if act is None:
            self.overrides.pop(hid, None)
        else:
            self.overrides[hid] = act
        self.save_edits()
        self.timer.start()

    def delete_near(self, x, y):
        from shapely.geometry import LineString, Point
        tol = 12 / max(abs(self.view.transform().m11()), 1e-9)
        pt, best = Point(x, y), None
        for el in self.user:
            g = core.user_geometry(el, self.mmu)
            if g is None:
                g = LineString(el["pts"]) if len(el["pts"]) > 1 else Point(el["pts"][0])
            d = pt.distance(g)
            if d <= tol and (best is None or d < best[0]):
                best = (d, el["uid"])
        if best:
            el_ = next((e for e in self.user if e["uid"] == best[1]), None)
            if el_ is not None:
                self.hist.append(("del", el_))
                self.redo = []
            self.remove_user(best[1])
            self.user_changed()

    def undo_user(self):
        """Undo the last thing you drew or deleted (Ctrl+Z)."""
        if self.hist:
            kind, el = self.hist.pop()
            if kind == "add":
                self.remove_user(el["uid"])
            else:
                self.add_user(el, rec=False)
            self.redo.append((kind, el))
            self.user_changed()
        elif self.user:                       # elements loaded from the saved edits file
            self.remove_user(self.user[-1]["uid"])
            self.user_changed()

    def redo_user(self):
        """Put back what Undo took away (Ctrl+Y)."""
        if not self.redo:
            return
        kind, el = self.redo.pop()
        if kind == "add":
            self.add_user(el, rec=False)
        else:
            self.remove_user(el["uid"])
        self.hist.append((kind, el))
        self.user_changed()

    def clear_user(self):
        if self.user and QMessageBox.question(self, "Clear", "Remove everything you drew by hand?") \
                == QMessageBox.StandardButton.Yes:
            for el in list(self.user):
                self.remove_user(el["uid"])
            self.hist, self.redo = [], []
            self.user_changed()

    def sync_rows(self):
        """one table row per element you drew; rows of removed elements go"""
        ids = {i["id"] for i in self.items}
        self.table.blockSignals(True)
        have = set()
        for r in range(self.table.rowCount() - 1, -1, -1):
            iid = int(self.table.item(r, 0).text())
            if iid not in ids:
                self.table.removeRow(r)
            else:
                have.add(iid)
        for it in self.items:
            if it.get("user") and it["id"] not in have and self.table.columnCount():
                r = self.table.rowCount()
                self.table.insertRow(r)
                a = QTableWidgetItem(str(it["id"]))
                a.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, 0, a)
                self.table.setItem(r, 1, QTableWidgetItem(it["note"]))
                c = QTableWidgetItem("YOURS")
                c.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, 2, c)
                m = QTableWidgetItem(it["pattern"])
                m.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, 3, m)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()

    def user_changed(self):
        if self.table.rowCount() > 0:
            self.sync_rows()
        self.save_edits()
        self.timer.start()

    def edits_path(self):
        return OUT_DIR / (self.src.stem + "_edits.json")

    def save_edits(self):
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            write_json(self.edits_path(), {"elements": self.user, "overrides": self.overrides, "specs": self.specs})
        except Exception:
            traceback.print_exc()

    # ---- catalog: choose the specification of a part of the detail
    def hatch_at(self, x, y):
        """smallest original fill under the point -> (hatch, geometry) or None"""
        from shapely.geometry import Point
        if self.edit_doc is None:
            return None
        pt, best = Point(x, y), None
        for h in self.edit_doc.modelspace().query("HATCH"):
            if h.dxf.layer.startswith("MOT_"):
                continue
            hid = str(h.dxf.handle)
            if hid not in self.hgeo:
                try:
                    self.hgeo[hid] = core.hatch_geometry(h)
                except Exception:
                    self.hgeo[hid] = None
            g = self.hgeo[hid]
            if g is not None and g.contains(pt) and (best is None or g.area < best[1].area):
                best = (h, g)
        return best

    def _piece(self, g, pt):
        polys = core._polys(g)
        return next((p for p in polys if p.contains(pt)), polys[0] if polys else g)

    def _new_item(self, h, piece, x, y, hid):
        pattern = "SOLID" if h.dxf.solid_fill else (h.dxf.pattern_name or "")
        x0, y0, x1, y1 = piece.bounds
        nid = max([i["id"] for i in self.items] + [0]) + 1
        it = {"id": nid, "layer": h.dxf.layer, "pattern": pattern, "color": 7, "area": piece.area, "point": (x, y),
              "bbox": (x1 - x0, y1 - y0), "count": 1, "poly": piece, "picked": hid}
        self.items.append(it)
        return it

    def pick_spec(self, x, y):
        from shapely.geometry import Point
        if not self.items:
            return
        pt = Point(x, y)
        for el in reversed(self.user):                       # your own elements first
            g = core.user_geometry(el, self.mmu)
            if g is not None and g.contains(pt):
                it = next((i for i in self.items if i.get("user") == el["uid"]), None)
                if it:
                    self.spec_for_item(it)
                    return
        hit = self.hatch_at(x, y)
        if not hit:
            self.say("No fill under that point. Click inside a coloured part of the detail.")
            return
        h, g = hit
        hid = str(h.dxf.handle)
        it = next((i for i in self.items if i.get("picked") == hid), None)
        new = it is None
        if new:
            it = self._new_item(h, self._piece(g, pt), x, y, hid)
        else:
            it["point"] = (x, y)                              # the dot goes where you clicked
        self.view.rubber(list(core._polys(g)[0].exterior.coords) if core._polys(g) else None, closed=True)
        ok = self.spec_for_item(it)
        self.view.rubber(None)
        if not ok and new:
            self.items = [i for i in self.items if i is not it]

    def _row_of(self, iid):
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == iid:
                return r
        return -1

    def spec_for_item(self, it):
        """Open the catalog for this part. True when a note was chosen."""
        r = self._row_of(it["id"])
        cur = self.table.item(r, 1).text() if r >= 0 else ""
        name = core.clean_name(it["pattern"]) or it["layer"]
        dlg = SpecDialog(self, f"{name}  ({it['layer']})", cat.guess_category(it["layer"], it["pattern"]),
                         core.measured_mm(it, self.mmu), cur, name)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.note:
            return False
        self.set_row_note(it, dlg.note)
        if it.get("picked"):
            self.specs[it["picked"]] = {"note": dlg.note, "x": it["point"][0], "y": it["point"][1]}
        elif it.get("user"):
            for el in self.user:
                if el["uid"] == it["user"]:
                    el["note"] = dlg.note
            it["note"] = dlg.note
        self.save_edits()
        self.timer.start()
        return True

    def set_row_note(self, it, txt):
        r = self._row_of(it["id"])
        self.table.blockSignals(True)
        if r < 0:
            r = self.table.rowCount()
            self.table.insertRow(r)
            a = QTableWidgetItem(str(it["id"]))
            a.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, a)
            c = QTableWidgetItem("YOURS" if it.get("user") else "")
            c.setForeground(QColor(RED))
            c.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, c)
            m = QTableWidgetItem(core.clean_name(it["pattern"]) or it["layer"])
            m.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 3, m)
        self.table.setItem(r, 1, QTableWidgetItem(txt))
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 170)
        self.btn_apply.setEnabled(True)

    def restore_spec(self, hid, sp):
        """Bring back a note chosen earlier for a part (the saved edits file keeps them by the part's handle)."""
        from shapely.geometry import Point
        h = self.edit_doc.entitydb.get(hid) if self.edit_doc is not None else None
        if h is None or h.dxftype() != "HATCH":
            return
        g = core.hatch_geometry(h)
        if g is None or g.is_empty:
            return
        self.hgeo[hid] = g
        x, y = float(sp.get("x", 0)), float(sp.get("y", 0))
        it = self._new_item(h, self._piece(g, Point(x, y)), x, y, hid)
        self.specs[hid] = {"note": sp["note"], "x": x, "y": y}
        self.set_row_note(it, sp["note"])

    def row_spec(self, r):
        if r < 0 or r >= self.table.rowCount():
            self.say("Select a note in the list first.")
            return
        iid = int(self.table.item(r, 0).text())
        it = next((i for i in self.items if i["id"] == iid), None)
        if it:
            self.spec_for_item(it)

    def remove_note(self):
        r = self.table.currentRow()
        if r < 0 or r >= self.table.rowCount():
            return
        iid = int(self.table.item(r, 0).text())
        it = next((i for i in self.items if i["id"] == iid), None)
        if it and it.get("picked"):
            self.specs.pop(it["picked"], None)
            self.items = [i for i in self.items if i is not it]
            self.table.removeRow(r)
        else:                                     # your own element or a suggested note: its note is just emptied
            self.table.blockSignals(True)
            self.table.setItem(r, 1, QTableWidgetItem(""))
            self.table.blockSignals(False)
            if it and it.get("user"):
                for el in self.user:
                    if el["uid"] == it["user"]:
                        el["note"] = ""
        self.save_edits()
        self.timer.start()

    # ---- generate
    def generate(self):
        if not self.items:
            return
        key = api_key()
        self.btn_gen.setEnabled(False)
        if key:
            self.say("Asking Claude to read the detail and write the notes...")
            orig = [i for i in self.items if not i.get("synthetic")]
            prompt = core.ai_prompt(orig, self.texts, self.mmu)
            img = marked_image_b64(self.view.scene(), orig)
            model = api_model()
            self.worker = Worker(lambda: core.parse_notes(ai_request(prompt, img, key, model)))
            self.worker.done.connect(self.notes_ready)
            self.worker.fail.connect(self.ai_failed)
            self.worker.start()
        else:
            self.say("No API key saved - using rule-based notes (Settings to add a key).")
            self.notes_ready(None)

    def ai_failed(self, msg):
        QMessageBox.warning(self, "AI step failed", f"{msg}\n\nUsing rule-based notes instead.")
        self.notes_ready(None)

    def notes_ready(self, ai):
        by_id = {i["id"]: i for i in self.items}
        rows = []
        if ai:
            rows = [(n["id"], n["note"], n["verify"]) for n in ai if n["id"] in by_id]
        orig = [i for i in self.items if not i.get("synthetic")]
        if not rows:
            seen = {}
            for it in sorted(orig, key=lambda i: -i["area"]):
                if max(it["bbox"]) * self.mmu < 15:
                    continue                       # specks under 15 mm
                txt, ver = core.rule_note(it["layer"], it["pattern"], core.measured_mm(it, self.mmu))
                if txt.strip().lower() in seen:    # one callout per identical note
                    continue
                seen[txt.strip().lower()] = True
                rows.append((it["id"], txt, ver))
        rows = [r for r in rows if not by_id[r[0]].get("picked")]
        for it in self.items:                       # parts whose specification you chose from the catalog stay as chosen
            if it.get("picked") and it["picked"] in self.specs:
                rows.append((it["id"], self.specs[it["picked"]]["note"], False))
        have_txt = {r[1].strip().lower() for r in rows}
        for it in self.items:                       # elements the tool adds itself
            if it.get("synthetic"):
                if it["note"].strip().lower() in have_txt:
                    continue                        # that note is already on the drawing: no second callout
                have_txt.add(it["note"].strip().lower())
                rows.append((it["id"], it["note"], False))
        # top-to-bottom like the drawing
        rows.sort(key=lambda r: -by_id[r[0]]["point"][1])
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (iid, txt, ver) in enumerate(rows):
            a = QTableWidgetItem(str(iid))
            a.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, QTableWidgetItem(txt))
            c = QTableWidgetItem(("YOURS" if by_id[iid].get("user") else "ADDED") if by_id[iid].get("synthetic") else ("VERIFY" if ver else ""))
            c.setForeground(QColor(RED))
            c.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, c)
            it = by_id[iid]
            m = QTableWidgetItem(core.clean_name(it["pattern"]) or it["layer"])
            m.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 3, m)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 170)
        self.btn_gen.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self.tabs.setCurrentIndex(0)
        self.apply_and_save()

    # ---- apply
    def auto_apply(self):
        if self.items and self.btn_apply.isEnabled():
            self.apply_and_save()

    def auto_all(self):
        """Auto mode: write the notes for every part of the detail."""
        if not self.items:
            self.say("Open a detail first.")
            return
        self.generate()

    def apply_and_save(self):
        try:
            import ezdxf
            from ezdxf import bbox as ezbbox
            by_id = {i["id"]: i for i in self.items}
            doc = core.load_doc(self.work_dxf)
            msp = doc.modelspace()
            if self.clear_old.isChecked():
                for e in list(msp):
                    if e.dxftype() in ("MTEXT", "TEXT", "LEADER", "MULTILEADER", "WIPEOUT"):
                        msp.delete_entity(e)
            if self.overrides:
                core.apply_overrides(doc, self.overrides, self.mmu)
            live = {i["key"]: True for i in self.items if i.get("user")}
            if self.draw_missing.isChecked():
                plan = core.completeness(doc, self.texts, [i for i in self.items if not i.get("synthetic")],
                                         self.mmu, self.brick_h.value(), self.joint.value(),
                                         self.do_brick.isChecked())
                core.draw_adds(doc, plan["adds"])
                for a in plan["adds"]:
                    it = self.added.get(a["key"])
                    if it:
                        it.update(point=a["point"], poly=a["geom"], bbox=a["bbox"])
                        live[a["key"]] = True
                self.report = plan["report"]
            self.show_report(self.report, self.draw_missing.isChecked())
            notes = []
            for r in range(self.table.rowCount()):
                iid = int(self.table.item(r, 0).text())
                txt = " ".join(self.table.item(r, 1).text().split())
                if by_id[iid].get("synthetic") and not live.get(by_id[iid]["key"]):
                    continue
                if by_id[iid].get("picked") and by_id[iid]["picked"] in self.specs:
                    self.specs[by_id[iid]["picked"]]["note"] = txt
                if by_id[iid].get("user"):                 # keep your edited wording
                    by_id[iid]["note"] = txt
                    for el in self.user:
                        if el["uid"] == by_id[iid]["user"]:
                            el["note"] = txt
                if txt:
                    notes.append({"id": iid, "note": txt, "item": by_id[iid],
                                  "verify": self.table.item(r, 2).text() in ("VERIFY", "ADDED")})
            if self.house_cols.isChecked() or self.do_brick.isChecked():
                core.restyle(doc, self.mmu, self.brick_h.value(), self.joint.value(),
                             colours=self.house_cols.isChecked(), coursing=self.do_brick.isChecked())
            if self.user:
                core.draw_user(doc, self.user, self.mmu)
            ext = ezbbox.extents(msp)
            extents = (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
            ordered = core.place_notes(doc, notes, extents, self.mmu, self.scale.value(),
                                       self.text_mm.value(), self.note_w.value(), 12, self.number_notes.isChecked())
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            self.save_edits()
            stem = self.src.stem + "_noted"
            dxf_out = OUT_DIR / (stem + ".dxf")
            core.save_doc(doc, dxf_out)
            final = dxf_out
            if self.src.suffix.lower() == ".dwg":
                dwg = core.oda_convert(dxf_out, "DWG")
                if dwg:
                    shutil.copy(dwg, OUT_DIR / (stem + ".dwg"))
                    final = OUT_DIR / (stem + ".dwg")
                    dxf_out.unlink(missing_ok=True)
            with open(OUT_DIR / (self.src.stem + "_notes.txt"), "w", encoding="utf-8") as f:
                for i, n in enumerate(ordered, 1):
                    f.write(f"{i}. {n['note']}" + ("   [VERIFY]" if n["verify"] else "") + "\n")
                f.write("\nCompleteness check (SA practice):\n")
                for label, st in self.report:
                    f.write(f"  {label}: " + {"ok": "in detail", "added": "was missing - drawn by the tool",
                                              "manual": "NOT in detail - add by hand"}[st] + "\n")
            keep = None if self.first_apply else (self.view.transform(),
                                                  self.view.mapToScene(self.view.viewport().rect().center()))
            self.view.setScene(build_scene(doc))
            if keep:
                self.view.setTransform(keep[0])
                self.view.centerOn(keep[1])
            else:
                self.view.fit()
            self.first_apply = False
            self.last_out = final
            lead = ("leaders: no overlaps" if core.LAST_CONFLICTS[0] == 0
                    else f"leaders: {core.LAST_CONFLICTS[0]} spots still close, nudge by hand")
            warn = ""
            if self.src.suffix.lower() == ".dwg" and final.suffix.lower() == ".dxf":
                warn = "  - DWG could not be written, saved as DXF: open it in Archicad and Save As DWG"
            self.say(f"Saved: {final}   ({lead}){warn}")
        except Exception as ex:
            traceback.print_exc()
            QMessageBox.warning(self, "Could not save", str(ex))


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = Win()
    w.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        w.open_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
