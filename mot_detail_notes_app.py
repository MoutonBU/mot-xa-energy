"""
MCP Architecture & Interiors - Detail Notes
Desktop app (same look and Python environment as the SANS Calc).

Open or drag in a DWG/DXF of a detail -> it reads the materials, writes the callout
notes (AI if an API key is saved, otherwise rules), places them with leaders and
saves <name>_noted.dwg + <name>_notes.txt into the "outputs" folder next to this file.
"""
import base64
import copy
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

from PySide6.QtCore import QSize, QEventLoop, QBuffer, QPointF, QRectF, QVariantAnimation, QEasingCurve, QByteArray, QIODevice, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QAbstractItemView, QApplication, QButtonGroup, QComboBox, QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem, QRubberBand, QInputDialog, QCheckBox, QFrame, QTabWidget, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsEllipseItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter,
                               QListWidget, QListWidgetItem, QTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import detail_catalog as cat
import detail_smart as smart
import detail_refs as refs
import detail_icons as icons
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
QSplitter::handle {{ background:#232326; border-radius:3px; margin:2px 1px; }}
QSplitter::handle:hover {{ background:{RED}; }}
QPushButton[compact="true"] {{ padding:6px 12px; border-radius:8px; }}
QPushButton#chip {{ background:#202024; border:1px solid #34343a; border-radius:12px; padding:4px 12px; color:#cfcfd4; }}
QPushButton#chip:hover {{ border:1px solid {RED}; color:white; }}
QTreeWidget {{ background:#1b1b1d; border:1px solid #2c2c30; border-radius:10px; padding:4px; outline:0; }}
QTreeWidget::item {{ padding:6px 4px; border-radius:6px; }}
QTreeWidget::item:selected {{ background:#4a0f1c; color:white; }}
QTreeWidget::item:hover {{ background:#26262b; }}
QListWidget {{ background:#1b1b1d; border:1px solid #2c2c30; border-radius:10px; padding:4px; outline:0; }}
QPushButton:checked {{ background:#3a1018; border:1px solid {RED}; color:white; }}
QPushButton#canvasbtn {{ background:rgba(24,24,26,215); border:1px solid #3a3a40; padding:0; border-radius:8px; min-width:30px; max-width:30px; min-height:30px; max-height:30px; font-size:16px; font-weight:700; }}
QPushButton#canvasbtn:hover {{ border:1px solid {RED}; background:rgba(50,20,26,230); }}
QLabel#canvaschip {{ background:rgba(24,24,26,215); border:1px solid #3a3a40; border-radius:8px; padding:5px 10px; color:#cfcfd4; }}
QLabel#busychip {{ background:rgba(209,31,58,235); border-radius:8px; padding:5px 12px; color:white; font-weight:700; }}
QTableWidget {{ alternate-background-color:#1f1f22; }}
QTableWidget::item {{ padding:4px 6px; }}
QTableWidget::item:hover {{ background:#26262b; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#3a3a40; border-radius:5px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{RED}; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:#3a3a40; border-radius:5px; min-width:30px; }}
QScrollBar::handle:horizontal:hover {{ background:{RED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
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


SMART_SYSTEM = (
    "You are a South African architectural technologist writing ONE construction-detail callout note in spec voice. "
    "The person types a few words for the element (e.g. 'concrete coping'). Expand them into the complete note: size and "
    "material where given or standard, then the detailing that goes with it in South African practice (falls and slopes, "
    "drips or throatings, DPC/DPM, laps, fixings, treatment, joints), and a SANS reference only where you are confident "
    "(SANS 10400 parts K walls, L roofs, J floors, H foundations, R stormwater, P drainage, N glazing, XA energy, "
    "SANS 10100-1 concrete, SANS 1783 and 10005 timber, SANS 952/248 DPM/DPC). Do not invent brand names or numbers: write "
    "'to Eng. design' or 'to manufacturer's spec' instead. Metric mm only, thousands with a space (1 200). "
    "At most 260 characters, one or two sentences, no leading number, no quotes, no explanation. Return only the note text.")


def ai_text(prompt, key, model):
    body = {"model": model, "max_tokens": 400, "system": SMART_SYSTEM,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"Claude said: {msg or e.reason} (code {e.code})")
    except urllib.error.URLError as e:
        raise RuntimeError(f"No internet connection ({e.reason})")
    return " ".join("".join(p.get("text", "") for p in data.get("content", [])).split()).strip(' "')


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
    """Detail preview. Drag = move the drawing, wheel = zoom, click a note = select it (Ctrl adds),
    Shift+drag = select every note in a box, Delete = remove the selected notes, F = fit, Esc = clear."""
    clicked = Signal(float, float, int)      # x, y (drawing units), 1 = left / 2 = right
    moved = Signal(float, float)
    note_clicked = Signal(int, bool)         # note id (-1 = empty space), add to selection
    box_selected = Signal(list, bool)
    note_opened = Signal(int)
    delete_req = Signal()
    note_moved = Signal(int, float, float)   # note id, new top-left x, y (drawing units)
    target_moved = Signal(int, float, float) # note id, new x, y of its leader dot

    def __init__(self):
        super().__init__()
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing |
                                  QGraphicsView.OptimizationFlag.DontSavePainterState)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#1a1a1a"))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scale(1, -1)  # DXF y is up
        self.tool = None
        self.snaps = None                    # numpy array of snap points
        self._pan = None
        self._mark = None
        self._rub = None
        self.boxes = {}                      # note id -> (x0, y0, x1, y1) of its text on the drawing
        self.targets = {}                    # note id -> (x, y) of its leader dot
        self.sel = set()
        self.hover = None
        self._ov = {}
        self._press = None
        self._last = None
        self._moved = False
        self._band = None
        self._band0 = None
        self._shift = False
        self._dragn = None                   # (note id, press point in the scene) while a note is being dragged
        self._ghost = None
        self._dragd = None                   # (note id) while a leader dot is being dragged
        self.last_free = False
        self._fit_scale = None
        self._zoom_goal = None
        self._zoom_anim = None
        self._aa_timer = QTimer(self)
        self._aa_timer.setSingleShot(True)
        self._aa_timer.timeout.connect(lambda: self.setRenderHint(QPainter.RenderHint.Antialiasing, True))
        self._build_controls()

    def set_tool(self, on):
        self.tool = on
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.show_snap(0, 0, False)
        self.rubber(None)

    # ---- smooth, clamped zoom; no antialiasing while things move, so panning and zooming stay fluid
    def _fast(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._aa_timer.start(160)

    def zoom_by(self, factor):
        cur = abs(self.transform().m11())
        base = self._fit_scale or cur
        goal = (self._zoom_goal or cur) * factor
        goal = max(base * 0.25, min(base * 120, goal))
        self._zoom_goal = goal
        if self._zoom_anim is None:
            self._zoom_anim = QVariantAnimation(self)
            self._zoom_anim.setDuration(130)
            self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._zoom_anim.valueChanged.connect(self._zoom_step)
            self._zoom_anim.finished.connect(self._zoom_done)
        self._zoom_anim.stop()
        self._zoom_anim.setStartValue(cur)
        self._zoom_anim.setEndValue(goal)
        self._fast()
        self._zoom_anim.start()

    def _zoom_step(self, v):
        cur = abs(self.transform().m11())
        if cur > 0 and v > 0:
            self.scale(v / cur, v / cur)
            self._update_chip()

    def _zoom_done(self):
        self._zoom_goal = None
        self._update_chip()

    def wheelEvent(self, e):
        self.zoom_by(1.25 if e.angleDelta().y() > 0 else 1 / 1.25)

    # ---- small controls on the canvas: zoom, fit, busy badge
    def _build_controls(self):
        vp = self.viewport()
        self._chip = QLabel("100%", vp)
        self._chip.setObjectName("canvaschip")
        self._btns = []
        for txt, tip, fn in (("+", "Zoom in", lambda: self.zoom_by(1.4)), ("\u2212", "Zoom out", lambda: self.zoom_by(1 / 1.4)),
                             ("\u2922", "Show the whole detail (F)", lambda: self.fit())):
            b = QPushButton(txt, vp)
            b.setObjectName("canvasbtn")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            self._btns.append(b)
        self._busy = QLabel("Updating\u2026", vp)
        self._busy.setObjectName("busychip")
        self._busy.hide()
        self._place_controls()

    def _place_controls(self):
        vp = self.viewport()
        x = vp.width() - 12
        for b in reversed(self._btns):
            x -= b.width() or 30
            b.move(x, 12)
            x -= 6
        self._chip.adjustSize()
        self._chip.move(max(8, x - self._chip.width()), 14)
        self._busy.adjustSize()
        self._busy.move(14, 14)

    def _update_chip(self):
        base = self._fit_scale or abs(self.transform().m11())
        self._chip.setText(f"{abs(self.transform().m11()) / base * 100:.0f}%" if base else "")
        self._place_controls()

    def set_busy(self, on):
        self._busy.setVisible(bool(on))
        self._busy.raise_()
        if on:
            self._place_controls()
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_controls()

    def drawForeground(self, painter, rect):
        sc = self.scene()
        if sc is not None and not sc.items():
            painter.save()
            painter.resetTransform()
            painter.setPen(QColor("#6a6a72"))
            f = painter.font()
            f.setPointSize(13)
            painter.setFont(f)
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             "Drop a DWG or DXF of your detail here\nor use Open detail")
            painter.restore()

    # ---- notes on the drawing: highlight, hit test
    def set_boxes(self, boxes, targets):
        self.boxes, self.targets = dict(boxes), dict(targets)
        self._ov = {}
        sc = self.scene()
        if sc is None:
            return
        for iid, (x0, y0, x1, y1) in self.boxes.items():
            rp = QPainterPath()
            rad = min(x1 - x0, y1 - y0) * 0.06
            rp.addRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), rad, rad)
            r = QGraphicsPathItem(rp)
            r.setZValue(9e6)
            ring = None
            if iid in self.targets:
                ring = QGraphicsEllipseItem(-9, -9, 18, 18)
                ring.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
                ring.setPos(*self.targets[iid])
                ring.setZValue(9e6)
                sc.addItem(ring)
            sc.addItem(r)
            self._ov[iid] = (r, ring)
        self._style()

    def set_selected(self, ids):
        self.sel = set(ids)
        self._style()

    def _style(self):
        for iid, (r, ring) in self._ov.items():
            try:
                on, hov = iid in self.sel, iid == self.hover
                if on:
                    r.setBrush(QColor(255, 214, 0, 70))
                    pen = QPen(QColor("#ffd600"), 2)
                elif hov:
                    r.setBrush(QColor(0, 229, 255, 35))
                    pen = QPen(QColor("#00e5ff"), 1.5)
                else:
                    r.setBrush(Qt.BrushStyle.NoBrush)
                    pen = QPen(Qt.PenStyle.NoPen)
                pen.setCosmetic(True)
                r.setPen(pen)
                if ring is not None:
                    rp = QPen(QColor("#ffd600"), 3)
                    rp.setCosmetic(True)
                    ring.setPen(rp if on else QPen(Qt.PenStyle.NoPen))
            except RuntimeError:
                pass

    def dot_at(self, p):
        tol = 9 / max(abs(self.transform().m11()), 1e-9)
        best = None
        for iid, (tx, ty) in self.targets.items():
            d = max(abs(tx - p.x()), abs(ty - p.y()))
            if d <= tol and (best is None or d < best[0]):
                best = (d, iid)
        return best[1] if best else None

    def _show_ghost(self, a, b):
        try:
            gone = self._ghost is None or self._ghost.scene() is not self.scene()
        except RuntimeError:          # the scene was rebuilt and took the line with it
            gone = True
        if gone:
            self._ghost = QGraphicsLineItem()
            gp = QPen(QColor("#ffd600"), 1.5, Qt.PenStyle.DashLine)
            gp.setCosmetic(True)
            self._ghost.setPen(gp)
            self._ghost.setZValue(9e6)
            self.scene().addItem(self._ghost)
        self._ghost.setLine(a[0], a[1], b[0], b[1])
        self._ghost.setVisible(True)

    def _hide_ghost(self):
        try:
            if self._ghost is not None:
                self._ghost.setVisible(False)
        except RuntimeError:
            self._ghost = None

    def note_at(self, p):
        best = None
        for iid, (x0, y0, x1, y1) in self.boxes.items():
            if x0 <= p.x() <= x1 and y0 <= p.y() <= y1:
                a = (x1 - x0) * (y1 - y0)
                if best is None or a < best[0]:
                    best = (a, iid)
        if best:
            return best[1]
        tol = 10 / max(abs(self.transform().m11()), 1e-9)
        for iid, (tx, ty) in self.targets.items():
            if abs(tx - p.x()) <= tol and abs(ty - p.y()) <= tol:
                return iid
        return None

    def fit(self):
        sc = self.scene()
        if sc and not sc.itemsBoundingRect().isEmpty():
            r = sc.itemsBoundingRect()
            self.fitInView(r.adjusted(-r.width() * 0.03, -r.height() * 0.03, r.width() * 0.03, r.height() * 0.03),
                           Qt.AspectRatioMode.KeepAspectRatio)
            self._fit_scale = abs(self.transform().m11())
            self._update_chip()

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

    # ---- mouse: drag pans, a click picks/draws, Shift+drag selects a box of notes, middle button also pans
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
            self._last = e.position()
            self._moved = False
            self._shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            sp = self.mapToScene(e.position().toPoint())
            dot = self.dot_at(sp)
            if dot is not None and not self._shift:
                self._dragd = dot                # pressing on a leader dot: a drag moves where the note points
                return
            hit = self.note_at(sp)
            bx = self.boxes.get(hit) if hit is not None else None
            if bx and bx[0] <= sp.x() <= bx[2] and bx[1] <= sp.y() <= bx[3] and not self._shift:
                self._dragn = (hit, sp)          # pressing on a note's text: a drag moves that note
            return
        if e.button() == Qt.MouseButton.RightButton and self.tool:
            x, y, _ = self._pt(e)
            self.clicked.emit(x, y, 2)
            return
        super().mousePressEvent(e)

    def _scroll_by(self, d):
        self._fast()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self._scroll_by(d)
            return
        if self._press is not None:
            if not self._moved and (e.position() - self._press).manhattanLength() > 5:
                self._moved = True
                if self._shift:
                    self._band0 = self._press.toPoint()
                    self._band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
                else:
                    self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._moved and self._dragd is not None:
                p1 = self.mapToScene(e.position().toPoint())
                x0, y0, x1, y1 = self.boxes[self._dragd]
                self._show_ghost((x0, (y0 + y1) / 2), (p1.x(), p1.y()))
                ov = self._ov.get(self._dragd)
                if ov and ov[1] is not None:
                    tx, ty = self.targets[self._dragd]
                    ov[1].setPen(QPen(QColor("#ffd600"), 3))
                    ov[1].setPos(p1.x(), p1.y())
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
                return
            if self._moved and self._dragn is not None:
                nid, p0 = self._dragn
                p1 = self.mapToScene(e.position().toPoint())
                it = self._ov.get(nid)
                if it:
                    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
                    it[0].setPos(dx, dy)
                    it[0].setBrush(QColor(255, 214, 0, 110))
                    x0, y0, x1, y1 = self.boxes[nid]
                    tgt = self.targets.get(nid)
                    if tgt:
                        self._show_ghost((x0 + dx, (y0 + y1) / 2 + dy), tgt)
                    self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
                return
            if self._moved:
                if self._band is not None:
                    from PySide6.QtCore import QRect
                    self._band.setGeometry(QRect(self._band0, e.position().toPoint()).normalized())
                    self._band.show()
                else:
                    self._scroll_by(e.position() - self._last)
                self._last = e.position()
            return
        sp = self.mapToScene(e.position().toPoint())
        h = self.note_at(sp)
        if h != self.hover:
            self.hover = h
            self._style()
        if self.tool:
            x, y, on = self._pt(e)
            self.show_snap(x, y, on and h is None)
            self.moved.emit(x, y)
        self.viewport().setCursor(Qt.CursorShape.SizeAllCursor if (h is not None or self.dot_at(sp) is not None) else
                                  (Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
            return
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            add = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            if self._dragd is not None and self._moved:
                p1 = self.mapToScene(e.position().toPoint())
                nid = self._dragd
                self._dragd = None
                self._hide_ghost()
                self.target_moved.emit(nid, p1.x(), p1.y())
                self._press = None
                self._moved = False
                self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
                return
            self._dragd = None
            if self._dragn is not None and self._moved:
                nid, p0 = self._dragn
                p1 = self.mapToScene(e.position().toPoint())
                x0, y0, x1, y1 = self.boxes[nid]
                self._dragn = None
                self._hide_ghost()
                self.last_free = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
                self.note_moved.emit(nid, x0 + p1.x() - p0.x(), y1 + p1.y() - p0.y())
                self._press = None
                self._moved = False
                self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
                return
            self._dragn = None
            if self._band is not None:
                a = self.mapToScene(self._band0)
                b = self.mapToScene(e.position().toPoint())
                r = QRectF(a, b).normalized()
                ids = [i for i, (x0, y0, x1, y1) in self.boxes.items() if r.intersects(QRectF(x0, y0, x1 - x0, y1 - y0))]
                self._band.hide()
                self._band.deleteLater()
                self._band = None
                self.box_selected.emit(ids, bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier))
            elif not self._moved:
                sp = self.mapToScene(e.position().toPoint())
                hit = self.note_at(sp)
                if hit is not None:
                    self.note_clicked.emit(hit, add)
                elif self.tool:
                    x, y, _ = self._pt(e)
                    self.clicked.emit(x, y, 1)
                else:
                    self.note_clicked.emit(-1, add)
            self._press = None
            self._moved = False
            self.viewport().setCursor(Qt.CursorShape.CrossCursor if self.tool else Qt.CursorShape.ArrowCursor)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._press = None
        self._dragn = None
        self._dragd = None
        if e.button() == Qt.MouseButton.LeftButton:
            hit = self.note_at(self.mapToScene(e.position().toPoint()))
            if hit is not None:
                self.note_opened.emit(hit)

    def leaveEvent(self, e):
        if self.hover is not None:
            self.hover = None
            self._style()
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        k, m = e.key(), e.modifiers()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_req.emit()
        elif k == Qt.Key.Key_Escape:
            self.note_clicked.emit(-1, False)
        elif k == Qt.Key.Key_F:
            self.fit()
        elif k == Qt.Key.Key_A and m & Qt.KeyboardModifier.ControlModifier:
            self.box_selected.emit(list(self.boxes), False)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.3)
        elif k == Qt.Key.Key_Minus:
            self.zoom_by(1 / 1.3)
        else:
            super().keyPressEvent(e)


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


def approved_set():
    return set(read_json(OWN_SETTINGS).get("approved", []))


def approve_notes(texts, on=True):
    o = read_json(OWN_SETTINGS)
    cur = set(o.get("approved", []))
    for t in texts:
        n = refs.norm(t)
        if n:
            (cur.add if on else cur.discard)(n)
    o["approved"] = sorted(cur)
    write_json(OWN_SETTINGS, o)


def mapping_get(name):
    return read_json(OWN_SETTINGS).get("mapping", {}).get(refs.norm(name))


def mapping_set(name, note):
    o = read_json(OWN_SETTINGS)
    m = o.get("mapping", {})
    m[refs.norm(name)] = note
    o["mapping"] = m
    write_json(OWN_SETTINGS, o)


def ref_text(category):
    """-> (short, long) or None"""
    return refs.ref_for(category)


class OptionDelegate(QStyledItemDelegate):
    """One option = a bold title and a muted preview of its note, so you can choose without opening each one."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 58)

    def paint(self, painter, option, index):
        from PySide6.QtGui import QFontMetrics
        painter.save()
        r = option.rect.adjusted(4, 2, -4, -2)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if sel:
            painter.setBrush(QColor("#4a0f1c"))
            painter.setPen(QPen(QColor(RED), 1))
        elif hov:
            painter.setBrush(QColor("#26262b"))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, 8, 8)
        f = painter.font()
        f.setBold(True)
        f.setPointSize(11)
        painter.setFont(f)
        painter.setPen(QColor("#f2f2f4"))
        tag = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        tr = r.adjusted(12, 6, -12, 0)
        painter.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         QFontMetrics(f).elidedText(title, Qt.TextElideMode.ElideRight, tr.width() - (150 if tag else 0)))
        f.setBold(False)
        f.setPointSize(9)
        painter.setFont(f)
        if tag:
            painter.setPen(QColor("#9aa0a6"))
            painter.drawText(tr, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                             QFontMetrics(f).elidedText(tag, Qt.TextElideMode.ElideRight, 190))
        painter.setPen(QColor("#9a9aa2"))
        note = index.data(Qt.ItemDataRole.UserRole) or ""
        br = r.adjusted(12, 28, -12, -4)
        painter.drawText(br, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         QFontMetrics(f).elidedText(note, Qt.TextElideMode.ElideRight, br.width()))
        painter.restore()


class SpecDialog(QDialog):
    """Pick a specification from the catalog for one part of the detail. The note can be edited before it is used."""

    def __init__(self, parent, title, cat_name, measured=None, current="", name="", typed=""):
        super().__init__(parent)
        self.name = name
        self.setWindowTitle("Choose specification")
        self.resize(980, 640)
        self.note = ""
        self.custom = load_custom()
        self.measured = measured
        v = QVBoxLayout(self)
        v.setSpacing(10)
        head = QLabel("<span style='font-size:15px'><b>%s</b></span>" % title +
                      (f"   <span style='color:#9aa0a6'>drawn thickness about <b style='color:#e8e8ea'>{measured} mm</b></span>" if measured else ""))
        v.addWidget(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001F50E  Type what it is  (e.g. concrete coping)  and the note is written for you")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(40)
        v.addWidget(self.search)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        lab_ = QLabel("Try:")
        lab_.setObjectName("muted")
        chips.addWidget(lab_)
        for ex in icons.EXAMPLES:
            cb = QPushButton(ex)
            cb.setObjectName("chip")
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.clicked.connect(lambda _=False, t=ex: self.search.setText(t))
            chips.addWidget(cb)
        chips.addStretch()
        v.addLayout(chips)
        row = QHBoxLayout()
        self.cats = QTreeWidget()
        self.cats.setHeaderHidden(True)
        self.cats.setIndentation(14)
        self.cats.setMaximumWidth(290)
        self.cats.setMinimumWidth(230)
        self.cats.setUniformRowHeights(True)
        self.cats.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.opts = QListWidget()
        self.opts.setItemDelegate(OptionDelegate(self.opts))
        self.opts.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.opts.setMouseTracking(True)
        self.opts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row.addWidget(self.cats)
        row.addWidget(self.opts, 1)
        v.addLayout(row, 1)
        nl_ = QLabel("Your note  <span style='color:#9aa0a6'>(change the wording if you like)</span>")
        nl_.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(nl_)
        self.text = QTextEdit()
        self.text.setMaximumHeight(84)
        self.text.setAcceptRichText(False)
        v.addWidget(self.text)
        self.ref_lbl = QLabel("")
        self.ref_lbl.setWordWrap(True)
        self.ref_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.ref_lbl)
        self.text.textChanged.connect(self._ref)
        # the less-used controls fold away
        self.more_btn = QPushButton("More options  \u25B8")
        self.more_btn.setObjectName("chip")
        self.more_btn.setCheckable(True)
        more = QWidget()
        mh = QHBoxLayout(more)
        mh.setContentsMargins(0, 0, 0, 0)
        self.remember = QCheckBox(f"Remember this note for \u201c{name}\u201d" if name else "Remember")
        self.remember.setChecked(bool(name) and name.upper() not in ("SOLID", "WOOD"))
        self.remember.setVisible(bool(name))
        mh.addWidget(self.remember)
        mh.addStretch()
        self.appr_btn = QPushButton("Approve this wording")
        self.appr_btn.setToolTip("Marks this exact wording as checked by you against the standard. It then shows a green tick everywhere.")
        self.appr_btn.clicked.connect(self.toggle_approve)
        mh.addWidget(self.appr_btn)
        bs = QPushButton("Save to My specs...")
        bs.clicked.connect(self.save_mine)
        mh.addWidget(bs)
        more.setVisible(False)
        self.more_btn.toggled.connect(lambda on: (more.setVisible(on), self.more_btn.setText("More options  " + ("\u25BE" if on else "\u25B8"))))
        br = QHBoxLayout()
        self.cnt = QLabel(f"{cat.count()} specifications")
        self.cnt.setObjectName("muted")
        br.addWidget(self.more_btn)
        br.addWidget(self.cnt)
        br.addStretch()
        self.ai_btn = QPushButton("Write it with AI")
        self.ai_btn.setToolTip("Asks Claude to write the full detailed note from the words you typed (needs the internet and your API key).")
        self.ai_btn.clicked.connect(self.ask_ai)
        self.ai_btn.setVisible(bool(api_key()))
        br.addWidget(self.ai_btn)
        bo = QPushButton("Use this note")
        bo.setObjectName("primary")
        bo.setDefault(True)
        bo.clicked.connect(self.use)
        bc = QPushButton("Cancel")
        bc.clicked.connect(self.reject)
        br.addWidget(bc)
        br.addWidget(bo)
        v.addWidget(more)
        v.addLayout(br)
        self._cur = current
        self.cat_name, self.title = cat_name, title
        self._fill_cats()
        self._select_cat(cat_name)
        self.cats.currentItemChanged.connect(lambda *_: self._fill_opts())
        self.opts.currentRowChanged.connect(self._pick)
        self.opts.itemDoubleClicked.connect(lambda *_: self.use())
        self.search.textChanged.connect(self._search)
        self._fill_opts(select=True)
        if current:
            self.text.setPlainText(current)
        if typed:
            self.search.setText(typed)
        self._ref()

    def category_now(self):
        return refs.category_of(self.text.toPlainText()) or self.cat_name

    def _ref(self):
        txt = self.text.toPlainText()
        if not txt.strip():
            self.ref_lbl.setText("")
            return
        r = ref_text(self.category_now())
        ok = refs.norm(txt) in approved_set()
        bits = []
        bits.append("<span style='color:#43a047'>&#10004; approved by you</span>" if ok else
                    "<span style='color:#ffb300'>not yet checked by you</span>")
        bits.append(f"reference: <b>{r[1]}</b> <span style='color:#9aa0a6'>(part level - confirm the clause)</span>"
                    if r else "<span style='color:#9aa0a6'>no reference for this group - check the standard yourself</span>")
        self.ref_lbl.setText("  |  ".join(bits))
        self.appr_btn.setText("Remove approval" if ok else "Approve this wording")

    def toggle_approve(self):
        txt = " ".join(self.text.toPlainText().split())
        if txt:
            approve_notes([txt], on=refs.norm(txt) not in approved_set())
            self._ref()

    def _all(self):
        d = {k: list(v) for k, v in cat.CATALOG.items()}
        if self.custom:
            d["My specs"] = [(c["label"], c["note"]) for c in self.custom]
        return d

    def _fill_cats(self):
        self.cats.clear()
        self._cat_items = {}
        data = self._all()
        used = set()
        for ic, fam, groups in icons.FAMILIES:
            groups = [g for g in groups if g in data]
            if not groups:
                continue
            top = QTreeWidgetItem([f"{ic}  {fam}"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setData(0, Qt.ItemDataRole.UserRole, None)
            self.cats.addTopLevelItem(top)
            for g in groups:
                used.add(g)
                ch = QTreeWidgetItem([f"{icons.ICONS.get(g, '')}  {g}"])
                ch.setData(0, Qt.ItemDataRole.UserRole, g)
                ch.setToolTip(0, f"{len(data[g])} specifications")
                top.addChild(ch)
                self._cat_items[g] = ch
        for g in data:                              # anything not placed in a family
            if g not in used:
                ch = QTreeWidgetItem([g])
                ch.setData(0, Qt.ItemDataRole.UserRole, g)
                self.cats.addTopLevelItem(ch)
                self._cat_items[g] = ch

    def _select_cat(self, name):
        it = self._cat_items.get(name) or next(iter(self._cat_items.values()), None)
        if it is None:
            return
        self.cats.collapseAll()
        if it.parent() is not None:
            it.parent().setExpanded(True)
        self.cats.setCurrentItem(it)

    def _cur_cat(self):
        it = self.cats.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def _fill_opts(self, select=False):
        if self.search.text().strip():
            return
        k = self._cur_cat()
        if k is None and self.cats.currentItem() is not None:          # a family heading: open it, show its first group
            top = self.cats.currentItem()
            top.setExpanded(True)
            if top.childCount():
                self.cats.setCurrentItem(top.child(0))
            return
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
            it = QListWidgetItem(lab)
            it.setData(Qt.ItemDataRole.UserRole, note)
            it.setData(Qt.ItemDataRole.UserRole + 1, (icons.ICONS.get(c, "") + "  " + c) if c else "")
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
        note, rec = smart.smart_note(txt.strip())
        label = f"\u270E  Write it from what I typed:  {txt.strip()}" + (f"   [{rec}]" if rec else "")
        self._show([(label, note)] + hits, [None] + cats)
        self.cnt.setText(f"{len(hits)} catalog matches  -  the first line is the note written from your words")
        self.opts.setCurrentRow(0)

    def ask_ai(self):
        typed = self.search.text().strip() or self.title
        key = api_key()
        if not key:
            return
        ctx = [n for _l, n in cat.CATALOG.get(self.cat_name, [])[:3]]
        prompt = (f"Element typed: {typed}\nMaterial in the drawing: {self.title}\n"
                  + (f"Thickness measured from the drawing: about {self.measured} mm\n" if self.measured else "")
                  + "Examples of the house style:\n- " + "\n- ".join(ctx) + "\n\nWrite the note.")
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("Writing...")
        self._w = Worker(lambda: ai_text(prompt, key, api_model()))
        self._w.done.connect(self._ai_done)
        self._w.fail.connect(self._ai_fail)
        self._w.start()

    def _ai_done(self, txt):
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("Write it with AI")
        if txt:
            self.text.setPlainText(txt)

    def _ai_fail(self, msg):
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("Write it with AI")
        QMessageBox.warning(self, "AI", f"{msg}\n\nThe note written from your words is still available.")

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
            self._select_cat("My specs")

    def use(self):
        self.note = " ".join(self.text.toPlainText().split())
        self.cat_final = self.category_now()
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
        self.undo_stack, self.redo_stack, self._prev, self._restoring = [], [], None, False
        self.tpl = None
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
        self.btn_tpl = QPushButton("Templates")
        self.btn_tpl.setToolTip("Pick a common detail (parapet with coping, slab at the wall, window head...) and click its parts in turn: every note is written for you")
        self.btn_tpl.clicked.connect(self.template_menu)
        tbm.addWidget(self.btn_tpl)
        self.btn_tpl_stop = QPushButton("Stop template")
        self.btn_tpl_stop.setVisible(False)
        self.btn_tpl_stop.clicked.connect(self.stop_template)
        tbm.addWidget(self.btn_tpl_stop)
        self.chk_align = QCheckBox("Keep notes in line")
        self.chk_align.setChecked(True)
        self.chk_align.setToolTip("A note you move snaps to the straight column of the others. Hold Alt while dropping to place it freely.")
        tbm.addWidget(self.chk_align)
        self.ptr_combo = QComboBox()
        for lab_, key_ in (("Pointer: dot", "dot"), ("Pointer: arrow", "arrow"), ("Pointer: ring", "ring"),
                           ("Pointer: tick", "tick"), ("Pointer: none", "none")):
            self.ptr_combo.addItem(lab_, key_)
        self.ptr_combo.setToolTip("The end of the leader. With notes selected it changes those notes; with none selected it changes all of them.")
        self.ptr_combo.activated.connect(self.on_pointer_pick)
        tbm.addWidget(self.ptr_combo)
        self.btn_arrange = QPushButton("Reset note positions")
        self.btn_arrange.setToolTip("Drag any note on the drawing to move it. This puts them all back in a neat column.")
        self.btn_arrange.clicked.connect(self.auto_arrange)
        tbm.addWidget(self.btn_arrange)
        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setToolTip("Show the whole detail (key F)")
        self.btn_fit.clicked.connect(lambda: self.view.fit())
        tbm.addWidget(self.btn_fit)
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
        self.view.note_clicked.connect(self.on_note_click)
        self.view.box_selected.connect(self.on_box_select)
        self.view.note_opened.connect(lambda iid: self.row_spec(self._row_of(iid)))
        self.view.delete_req.connect(self.remove_note)
        self.view.note_moved.connect(self.on_note_moved)
        self.view.target_moved.connect(self.on_target_moved)
        self.note_pos, self.note_tgt = {}, {}
        self.ptr_default, self.note_ptr = "dot", {}
        self.note_boxes, self.note_targets = {}, {}
        self.xa_provider = None              # set by the suite: returns {'zone','roof','heavy','light'}
        self._syncing = False
        self.view.setScene(QGraphicsScene())
        split.addWidget(self.view)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Note (edit freely)", "Check", "Material", "Reference"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.on_table_sel)
        split.addWidget(self.table)
        split.setSizes([800, 560])
        split.setHandleWidth(8)
        split.setChildrenCollapsible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        nl.addWidget(split, 1)
        self.lbl_checks = QLabel("")
        self.lbl_checks.setObjectName("muted")
        self.lbl_checks.setWordWrap(True)
        self.lbl_checks.setTextFormat(Qt.TextFormat.RichText)
        nl.addWidget(self.lbl_checks)
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
        self.btn_remove = QPushButton("Remove selected notes")
        self.btn_remove.clicked.connect(self.remove_note)
        self.btn_approve = QPushButton("Mark selected as checked")
        self.btn_approve.setToolTip("You have checked these notes against SANS 10400 / the NHBRC manual: they get a green tick")
        self.btn_approve.clicked.connect(self.approve_selected)
        self.btn_batch = QPushButton("Batch: whole folder...")
        self.btn_batch.setToolTip("Write standard notes for every detail in a folder, and a notes schedule for each. Details you already worked on keep your notes.")
        self.btn_batch.clicked.connect(lambda: self.batch_folder())
        self.btn_sched = QPushButton("Notes schedule (PDF)...")
        self.btn_sched.clicked.connect(self.export_schedule)
        br.addWidget(self.btn_choose)
        br.addWidget(self.btn_remove)
        br.addWidget(self.btn_approve)
        br.addWidget(self.btn_sched)
        br.addWidget(self.btn_batch)
        br.addStretch()
        self.btn_gen.setVisible(False)
        br.addWidget(self.btn_apply)
        nl.addLayout(br)
        for b_ in nt.findChildren(QPushButton):
            b_.setProperty("compact", True)
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
        self.table.itemChanged.connect(lambda *_: (self.refresh_refs(), self.commit(), self.timer.start()))
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
            self.note_pos = {k: tuple(v) for k, v in (read_json(self.edits_path()).get("note_pos", {}) or {}).items()}
            self.note_tgt = {k: tuple(v) for k, v in (read_json(self.edits_path()).get("note_tgt", {}) or {}).items()}
            _e = read_json(self.edits_path())
            self.ptr_default = _e.get("pointer", "dot")
            self.note_ptr = dict(_e.get("note_ptr", {}) or {})
            self.ptr_combo.setCurrentIndex(max(0, self.ptr_combo.findData(self.ptr_default)))
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
            self.undo_stack, self.redo_stack, self.tpl = [], [], None
            self._prev = self.snap()
            self.timer.start()               # show the detail in house colours and real bricks straight away
        except Exception as ex:
            traceback.print_exc()
            QMessageBox.warning(self, "Could not open", str(ex))
            self.say("Ready.")

    # ---- your own detailing
    HINTS = {
        "spec": "Click a part to choose its spec. Drag a note anywhere, and drag its dot to change what it points at. Click a note to select (Ctrl adds), Shift+drag selects a box, Delete removes. Drag empty space to move the drawing, wheel zooms, F fits.",
        "pan": "Drag to move the drawing, wheel to zoom. Click a note to select it, Delete removes it.",
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
        self.tool_hint.setText(self.HINTS[key])

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
            elif btn == 2 and self.tpl:
                self.tpl_next()
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
        self.commit()
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
            self.remove_user(best[1])
            self.user_changed()

    # ---- undo / redo: every change to the notes, your elements and fills (Ctrl+Z / Ctrl+Y)
    def _rows_state(self):
        out = []
        for r in range(self.table.rowCount()):
            a = self.table.item(r, 0)
            if a is None:
                continue
            g = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) is not None else "")
            out.append((int(a.text()), g(1), g(2), g(3)))
        return out

    def snap(self):
        st = {"rows": self._rows_state(), "specs": copy.deepcopy(self.specs), "user": copy.deepcopy(self.user),
              "overrides": copy.deepcopy(self.overrides), "uid": self.uid, "pos": dict(self.note_pos), "tgt": dict(self.note_tgt), "ptr": (self.ptr_default, dict(self.note_ptr)),
              "items": [(i, i.get("point")) for i in self.items]}
        st["sig"] = json.dumps([st["rows"], st["specs"], st["user"], st["overrides"], st["pos"], st["tgt"], st["ptr"]], sort_keys=True, default=str)
        return st

    def commit(self):
        """call after a change: the state before it becomes one undo step"""
        if self._restoring or not self.items:
            return
        st = self.snap()
        if self._prev is not None and st["sig"] != self._prev["sig"]:
            self.undo_stack.append(self._prev)
            self.undo_stack = self.undo_stack[-80:]
            self.redo_stack = []
        self._prev = st

    def _fill_rows(self, rows):
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (iid, txt, chk, mat) in enumerate(rows):
            a = QTableWidgetItem(str(iid))
            a.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, QTableWidgetItem(txt))
            c = QTableWidgetItem(chk)
            c.setForeground(QColor(RED))
            c.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, c)
            m = QTableWidgetItem(mat)
            m.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 3, m)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 130)
        self.refresh_refs()

    def restore(self, st):
        self._restoring = True
        try:
            self.specs = copy.deepcopy(st["specs"])
            self.user = copy.deepcopy(st["user"])
            self.overrides = copy.deepcopy(st["overrides"])
            self.note_pos = dict(st["pos"])
            self.note_tgt = dict(st["tgt"])
            self.ptr_default, self.note_ptr = st["ptr"][0], dict(st["ptr"][1])
            self.ptr_combo.setCurrentIndex(max(0, self.ptr_combo.findData(self.ptr_default)))
            self.uid = max(self.uid, st["uid"])
            self.items = []
            for i, pt in st["items"]:
                if pt is not None:
                    i["point"] = pt
                self.items.append(i)
            self._fill_rows(st["rows"])
            self.view.set_selected(set())
            self.btn_apply.setEnabled(True)
            self.save_edits()
            self.timer.start()
        finally:
            self._restoring = False
        self._prev = self.snap()

    def undo_user(self):
        if not self.undo_stack:
            self.say("Nothing to undo.")
            return
        self.redo_stack.append(self.snap())
        self.restore(self.undo_stack.pop())
        self.say("Undone.")

    def redo_user(self):
        if not self.redo_stack:
            self.say("Nothing to redo.")
            return
        self.undo_stack.append(self.snap())
        self.restore(self.redo_stack.pop())
        self.say("Redone.")

    # ---- reference / approval column and the checks under the list
    def note_category(self, note, it):
        c = refs.category_of(note)
        if c:
            return c
        if it is not None:
            sp = self.specs.get(it.get("picked") or "", {})
            if sp.get("cat"):
                return sp["cat"]
            return cat.guess_category(it["layer"], it["pattern"])
        return ""

    def xa_fill(self, note, it):
        """When the suite knows the climate zone, put the real XA minimum R-value into insulation notes."""
        if not self.xa_provider or "R-value per SANS 10400-XA" not in note:
            return note
        try:
            d = self.xa_provider()
            txt = f"{it['layer']} {it['pattern']} {note}".lower() if it else note.lower()
            if re.search(r"ceiling|roof|rafter|truss|purlin", txt) or (self.roof_dir and not re.search(r"wall|cavity|brick|floor|slab", txt)):
                r, what = d["roof"], "roof / ceiling"
            elif re.search(r"light|frame|timber|steel", txt) and re.search(r"wall", txt):
                r, what = d["light"], "light-weight wall"
            elif re.search(r"wall|cavity|brick", txt):
                r, what = d["heavy"], "masonry wall"
            else:
                return note
            if not r:
                return note
            return note.replace("min. R-value per SANS 10400-XA",
                                f"min. total R-value {r:g} m\u00b2K/W for the {what} (SANS 10400-XA, climate zone {d['zone']})")
        except Exception:
            return note

    def refresh_refs(self):
        appr = approved_set()
        by_id = {i["id"]: i for i in self.items}
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            a, n = self.table.item(r, 0), self.table.item(r, 1)
            if a is None or n is None:
                continue
            note = n.text()
            ref = ref_text(self.note_category(note, by_id.get(int(a.text()))))
            ok = refs.norm(note) in appr and bool(note.strip())
            if ok:
                txt, col = "✔ " + (ref[0] if ref else "approved"), "#43a047"
            elif ref:
                txt, col = ref[0], "#ffb300"
            else:
                txt, col = "no reference", "#9aa0a6"
            c = QTableWidgetItem(txt)
            c.setFlags(Qt.ItemFlag.ItemIsEnabled)
            c.setForeground(QColor(col))
            c.setToolTip((("Approved by you.\n" if ok else "Not yet checked by you.\n") +
                          (ref[1] + "\n" + refs.CLAUSE_WARNING if ref else "No reference for this group: check the standard yourself.")))
            self.table.setItem(r, 4, c)
        self.table.blockSignals(False)

    def approve_selected(self):
        ids = self.sel_ids() or ({int(self.table.item(self.table.currentRow(), 0).text())}
                                 if self.table.currentRow() >= 0 else set())
        texts = []
        for r in range(self.table.rowCount()):
            a = self.table.item(r, 0)
            if a is not None and int(a.text()) in ids and self.table.item(r, 1) is not None:
                texts.append(self.table.item(r, 1).text())
        if not texts:
            self.say("Select the notes you have checked against the standard first.")
            return
        approve_notes(texts)
        self.refresh_refs()
        self.say(f"{len(texts)} note(s) marked as checked by you.")

    def refresh_checks(self):
        by_id = {i["id"]: i for i in self.items}
        rows = self._rows_state()
        have = {r[0] for r in rows}
        msgs = []
        for iid, note, chk, _m in rows:
            it = by_id.get(iid)
            if not note.strip() or it is None or it.get("synthetic") or it.get("user"):
                continue
            m = core.measured_mm(it, self.mmu)
            lead_ = re.match(r"\s*(\d+(?:\.\d+)?)\s*mm", note)       # only a size the note starts with is a thickness
            nums = [float(lead_.group(1))] if lead_ else []
            tol = max(12.0, 0.2 * m) if m else 0
            if m and nums and not any(abs(n - m) <= tol for n in nums):
                msgs.append(("warn", f"#{iid}: drawn about {m:g} mm but the note says {nums[0]:g} mm - check the note or the drawing"))
        seen = {}
        for iid, note, _c, _m in rows:
            k = refs.norm(note)
            if k and k in seen:
                msgs.append(("warn", f"#{seen[k]} and #{iid} have the same wording - one callout is enough"))
            seen.setdefault(k, iid)
        missing = []
        for it in sorted([i for i in self.items if not i.get("synthetic") and not i.get("user")], key=lambda i: -i["area"]):
            if it["id"] in have or max(it["bbox"]) * self.mmu < 30:
                continue
            nm = core.clean_name(it["pattern"]) or it["layer"]
            if nm not in missing:
                missing.append(nm)
        if missing:
            msgs.append(("info", f"{len(missing)} part(s) without a note yet: " + ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else "")))
        appr = approved_set()
        n_un = sum(1 for _i, n, _c, _m in rows if n.strip() and refs.norm(n) not in appr)
        if rows:
            msgs.append(("info", f"{len(rows) - n_un} of {len(rows)} notes approved by you"))
        ver = [r[0] for r in rows if r[2] in ("VERIFY", "ADDED") and r[1].strip()]
        if ver:
            msgs.append(("warn", "VERIFY on #" + ", #".join(str(v) for v in ver) + " (size read from the drawing or part drawn by the tool)"))
        col = {"warn": "#ffb300", "info": "#9aa0a6"}
        parts = [f"<span style='color:{col[k]}'>{'&#9888;' if k == 'warn' else '&bull;'} {m}</span>" for k, m in msgs]
        msgs = sorted(msgs, key=lambda m: m[0] != "warn")          # warnings first
        parts = [f"<span style='color:{col[k]}'>{'&#9888;' if k == 'warn' else '&bull;'} {m}</span>" for k, m in msgs]
        self.lbl_checks.setToolTip("<br>".join(parts))
        if not parts:
            self.lbl_checks.setText("<span style='color:#43a047'>&#10004; No problems found.</span>")
        else:
            more = f" <span style='color:#9aa0a6'>(+{len(parts) - 2} more - hover)</span>" if len(parts) > 2 else ""
            self.lbl_checks.setText("&nbsp;&nbsp;".join(parts[:2]) + more)
        self.lbl_checks.setMaximumHeight(44)

    def export_schedule(self, path=None):
        if not self.items or not self.table.rowCount():
            self.say("Add some notes first.")
            return
        import datetime
        from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument
        from PySide6.QtCore import QMarginsF
        default = str(OUT_DIR / (self.src.stem + "_notes_schedule.pdf"))
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save notes schedule", default, "PDF (*.pdf)")
        if not path:
            return
        appr = approved_set()
        by_id = {i["id"]: i for i in self.items}
        rows_html = []
        for k, (iid, note, chk, mat) in enumerate([r for r in self._rows_state() if r[1].strip()], 1):
            ref = ref_text(self.note_category(note, by_id.get(iid)))
            ok = refs.norm(note) in appr
            st = ("checked" if ok else "NOT yet checked") + (f" - {ref[1]}" if ref else " - no reference")
            rows_html.append(f"<tr><td>{k}</td><td>{note}{'  <b>[VERIFY]</b>' if chk in ('VERIFY', 'ADDED') else ''}</td>"
                             f"<td>{mat}</td><td>{st}</td></tr>")
        html = (f"<h2>Notes schedule - {self.src.stem}</h2><p>{datetime.date.today():%d %B %Y}</p>"
                "<table border='1' cellspacing='0' cellpadding='4' width='100%'>"
                "<tr><th>No.</th><th>Note</th><th>Material</th><th>Reference / status</th></tr>"
                + "".join(rows_html) + "</table>"
                "<p><small>These notes support, and do not replace, the competent person's judgement and the engineer's design. "
                "References are at part level only: confirm the clause in the current edition of SANS 10400 and the "
                "NHBRC Home Building Manual before issuing. Items marked VERIFY were read from the drawing and must be confirmed.</small></p>")
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        w.setPageMargins(QMarginsF(15, 15, 15, 15))
        d = QTextDocument()
        d.setHtml(html)
        d.print_(w)
        self.say(f"Notes schedule saved: {path}")

    # ---- batch: every detail in a folder
    def batch_folder(self, folder=None):
        from PySide6.QtWidgets import QProgressDialog
        folder = folder or QFileDialog.getExistingDirectory(self, "Folder with your details (DXF" + (" / DWG" if core.find_oda() else "") + ")")
        if not folder:
            return
        files = sorted(f for f in Path(folder).iterdir()
                       if f.suffix.lower() in (".dxf",) + ((".dwg",) if core.find_oda() else ())
                       and "_noted" not in f.stem)
        if not files:
            self.say("No DXF files found in that folder.")
            return
        prog = QProgressDialog("Writing notes...", "Stop", 0, len(files), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        done, failed = [], []
        for n, f in enumerate(files):
            prog.setValue(n)
            prog.setLabelText(f"{f.name}  ({n + 1} of {len(files)})")
            QApplication.processEvents()
            if prog.wasCanceled():
                break
            try:
                self.open_file(str(f))
                QApplication.processEvents()
                if not self.items:
                    raise RuntimeError("no materials found")
                if not self.table.rowCount():       # nothing saved for this detail yet: write the standard notes
                    self.generate(use_ai=False)
                self.apply_and_save()
                QApplication.processEvents()
                self.export_schedule(str(OUT_DIR / (f.stem + "_notes_schedule.pdf")))
                done.append(f.name)
            except Exception as ex:
                traceback.print_exc()
                failed.append(f"{f.name}: {ex}")
        prog.setValue(len(files))
        msg = f"Done: {len(done)} detail(s) noted, saved with a notes schedule in {OUT_DIR}."
        if failed:
            msg += "  Could not do: " + "; ".join(failed)
        self.say(msg)
        QMessageBox.information(self, "Batch finished", msg + "\n\nOpen each detail to check the notes: they are the standard wording and still need your approval.")

    # ---- templates: click the parts in turn, each note is written for you
    def template_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        for name, steps in refs.TEMPLATES:
            m.addAction(name, lambda n=name, st=steps: self.start_template(n, st))
        m.exec(self.btn_tpl.mapToGlobal(self.btn_tpl.rect().bottomLeft()))

    def start_template(self, name, steps):
        if not self.items:
            self.say("Open a detail first.")
            return
        self.tpl = {"name": name, "steps": list(steps), "i": 0}
        self.btn_tpl_stop.setVisible(True)
        self.set_tool("spec")
        self.tpl_hint()

    def tpl_hint(self):
        t = self.tpl
        if not t:
            self.btn_tpl_stop.setVisible(False)
            self.tool_hint.setText(self.HINTS["spec"])
            return
        lab, _w = t["steps"][t["i"]]
        self.tool_hint.setText(f"Template: {t['name']}  -  step {t['i'] + 1} of {len(t['steps'])}: click {lab}.  "
                               "Right-click skips this step, Stop template ends it.")

    def tpl_next(self):
        if not self.tpl:
            return
        self.tpl["i"] += 1
        if self.tpl["i"] >= len(self.tpl["steps"]):
            self.say(f"Template '{self.tpl['name']}' finished. Check each note, then approve the ones you have verified.")
            self.tpl = None
        self.tpl_hint()

    def stop_template(self):
        self.tpl = None
        self.tpl_hint()

    def clear_user(self):
        if self.user and QMessageBox.question(self, "Clear", "Remove everything you drew by hand?") \
                == QMessageBox.StandardButton.Yes:
            for el in list(self.user):
                self.remove_user(el["uid"])
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
        self.refresh_refs()

    def user_changed(self):
        if self.table.rowCount() > 0:
            self.sync_rows()
        self.commit()
        self.save_edits()
        self.timer.start()

    def edits_path(self):
        return OUT_DIR / (self.src.stem + "_edits.json")

    def save_edits(self):
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            write_json(self.edits_path(), {"elements": self.user, "overrides": self.overrides, "specs": self.specs,
                                           "note_pos": {k: list(v) for k, v in self.note_pos.items()},
                                           "note_tgt": {k: list(v) for k, v in self.note_tgt.items()},
                                           "pointer": self.ptr_default, "note_ptr": self.note_ptr})
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
        self.tpl_next()

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
                         core.measured_mm(it, self.mmu), cur, name,
                         typed=(self.tpl["steps"][self.tpl["i"]][1] if self.tpl and not cur else ""))
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.note:
            return False
        dlg.note = self.xa_fill(dlg.note, it)
        self.set_row_note(it, dlg.note)
        if it.get("picked"):
            self.specs[it["picked"]] = {"note": dlg.note, "x": it["point"][0], "y": it["point"][1], "cat": dlg.cat_final}
            if dlg.remember.isChecked() and name:
                mapping_set(name, dlg.note)
        elif it.get("user"):
            for el in self.user:
                if el["uid"] == it["user"]:
                    el["note"] = dlg.note
            it["note"] = dlg.note
        self.commit()
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
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 130)
        self.refresh_refs()
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
        self.specs[hid] = {"note": sp["note"], "x": x, "y": y, "cat": sp.get("cat", "")}
        self.set_row_note(it, sp["note"])

    def row_spec(self, r):
        if r < 0 or r >= self.table.rowCount():
            self.say("Select a note in the list first.")
            return
        iid = int(self.table.item(r, 0).text())
        it = next((i for i in self.items if i["id"] == iid), None)
        if it:
            self.spec_for_item(it)

    # ---- selection: the list and the drawing always show the same notes
    def sel_ids(self):
        ids = set()
        for r in sorted({i.row() for i in self.table.selectedIndexes()}):
            it = self.table.item(r, 0)
            if it is not None:
                ids.add(int(it.text()))
        return ids

    def item_key(self, it):
        """a key for a note that stays the same when the detail is reopened"""
        if it.get("picked"):
            return "h:" + str(it["picked"])
        if it.get("user"):
            return "u:" + str(it["user"])
        if it.get("key"):
            return "k:" + str(it["key"])
        return "i:" + str(it["id"])

    def on_note_moved(self, iid, x, y):
        it = next((i for i in self.items if i["id"] == iid), None)
        if it is None:
            return
        colx = core.LAST_COLUMN_X[0]
        if self.chk_align.isChecked() and colx is not None and not self.view.last_free:
            w_ = (self.note_boxes[iid][2] - self.note_boxes[iid][0]) if iid in self.note_boxes else 0
            if abs(x - colx) <= 1.5 * w_:
                x = colx                      # close to the column: line up with the other notes
        self.note_pos[self.item_key(it)] = (x, y)
        self.commit()
        self.save_edits()
        self.timer.start()
        self.say("Note moved. Drag it again to adjust, or press \u201cAuto-arrange notes\u201d to put them back in a column.")

    def on_target_moved(self, iid, x, y):
        it = next((i for i in self.items if i["id"] == iid), None)
        if it is None:
            return
        self.note_tgt[self.item_key(it)] = (x, y)
        self.commit()
        self.save_edits()
        self.timer.start()
        self.say("Pointer moved. Drag the dot again to adjust it.")

    def on_pointer_pick(self, _i):
        style = self.ptr_combo.currentData()
        ids = self.sel_ids()
        if ids:
            for it in self.items:
                if it["id"] in ids:
                    self.note_ptr[self.item_key(it)] = style
        else:
            self.ptr_default, self.note_ptr = style, {}
        self.commit()
        self.save_edits()
        self.timer.start()

    def auto_arrange(self):
        if self.note_pos or self.note_tgt:
            self.note_pos, self.note_tgt = {}, {}
            self.commit()
            self.save_edits()
            self.timer.start()

    def on_table_sel(self):
        if self._syncing:
            return
        ids = self.sel_ids()
        self.view.set_selected(ids)
        if len(ids) == 1 and next(iter(ids)) in self.note_boxes:
            x0, y0, x1, y1 = self.note_boxes[next(iter(ids))]
            self.view.ensureVisible(QRectF(x0, y0, x1 - x0, y1 - y0), 60, 60)

    def select_ids(self, ids):
        self._syncing = True
        try:
            self.table.clearSelection()
            sm = self.table.selectionModel()
            from PySide6.QtCore import QItemSelectionModel as _SM
            first = None
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if it is not None and int(it.text()) in ids:
                    sm.select(self.table.model().index(r, 0),
                              _SM.SelectionFlag.Select | _SM.SelectionFlag.Rows)
                    first = r if first is None else first
            if first is not None:
                self.table.scrollToItem(self.table.item(first, 1))
        finally:
            self._syncing = False
        self.view.set_selected(self.sel_ids())

    def on_note_click(self, iid, additive):
        cur = self.sel_ids()
        if iid < 0:
            ids = cur if additive else set()
        elif additive:
            ids = cur ^ {iid}
        else:
            ids = {iid}
        self.select_ids(ids)

    def on_box_select(self, ids, additive):
        self.select_ids((self.sel_ids() | set(ids)) if additive else set(ids))

    def remove_note(self):
        """Remove every selected note (list and drawing)."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and 0 <= self.table.currentRow() < self.table.rowCount():
            rows = [self.table.currentRow()]
        if not rows:
            return
        self._syncing = True
        for r in rows:
            if r >= self.table.rowCount() or self.table.item(r, 0) is None:
                continue
            iid = int(self.table.item(r, 0).text())
            it = next((i for i in self.items if i["id"] == iid), None)
            if it and it.get("picked"):
                self.specs.pop(it["picked"], None)
                self.items = [i for i in self.items if i is not it]
                self.table.removeRow(r)
            elif it and it.get("user"):                # your own element keeps its row, its note is emptied
                self.table.blockSignals(True)
                self.table.setItem(r, 1, QTableWidgetItem(""))
                self.table.blockSignals(False)
                for el in self.user:
                    if el["uid"] == it["user"]:
                        el["note"] = ""
            else:                                     # a suggested note: its row goes
                self.table.removeRow(r)
        self._syncing = False
        self.view.set_selected(set())
        self.btn_apply.setEnabled(self.table.rowCount() > 0)
        self.commit()
        self.save_edits()
        self.timer.start()

    # ---- generate
    def generate(self, use_ai=True):
        if not self.items:
            return
        key = api_key() if use_ai else ""
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
            if use_ai:
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
                remembered = mapping_get(core.clean_name(it["pattern"]) or "") if core.clean_name(it["pattern"]).upper() not in ("", "SOLID") else None
                if remembered:
                    txt, ver = remembered, False       # a note you chose before for this material name
                else:
                    txt, ver = core.rule_note(it["layer"], it["pattern"], core.measured_mm(it, self.mmu))
                    txt = self.xa_fill(txt, it)
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
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 130)
        self.btn_gen.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self.tabs.setCurrentIndex(0)
        self.refresh_refs()
        self.commit()
        self.apply_and_save()

    # ---- apply
    def auto_apply(self):
        if self.view._press is not None or self.view._dragn is not None:
            self.timer.start()                 # never redraw under your hand while you are dragging
            return
        if self.items and self.btn_apply.isEnabled():
            self.apply_and_save()

    def auto_all(self):
        """Auto mode: write the notes for every part of the detail."""
        if not self.items:
            self.say("Open a detail first.")
            return
        self.generate()

    def apply_and_save(self):
        self.view.set_busy(True)
        try:
            self._apply_and_save()
        finally:
            self.view.set_busy(False)

    def _apply_and_save(self):
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
                                       self.text_mm.value(), self.note_w.value(), 12, self.number_notes.isChecked(),
                                       manual={i["id"]: self.note_pos[self.item_key(i)] for i in self.items
                                               if self.item_key(i) in self.note_pos},
                                       targets={i["id"]: self.note_tgt[self.item_key(i)] for i in self.items
                                                if self.item_key(i) in self.note_tgt},
                                       pointer=self.ptr_default,
                                       pointers={i["id"]: self.note_ptr[self.item_key(i)] for i in self.items
                                                 if self.item_key(i) in self.note_ptr})
            self.note_boxes = {n["id"]: n["box"] for n in ordered if "box" in n}
            self.note_targets = {n["id"]: n["target"] for n in ordered if "target" in n}
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
            sc_ = build_scene(doc)
            sc_.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
            self.view.setScene(sc_)
            self.view.set_boxes(self.note_boxes, self.note_targets)
            self.view.set_selected(self.sel_ids())
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
            self.refresh_checks()
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
