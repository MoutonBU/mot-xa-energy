"""The import window: shows the drawing, lets you set the units and scale, pick a closed outline from the list or click the corners yourself
(clicks snap to line ends and crossings). Used for the stand, the house and the carport."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget, QCheckBox)

import site_dxf

UNITS = (("millimetres", 0.001), ("centimetres", 0.01), ("metres", 1.0))


class Preview(QWidget):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.setMinimumSize(560, 460)
        self.setMouseTracking(True)
        self.s, self.cx, self.cy = 1.0, 0.0, 0.0
        self.pick = False
        self.pts = []
        self.hover = None
        self.sel = None
        self._pan = None
        self.snaps = []
        self.street_poly = None

    def fit(self):
        L = self.dlg.lines_m
        if not L:
            return
        xs = [v for l in L for v in (l[0], l[2])]
        ys = [v for l in L for v in (l[1], l[3])]
        w, h = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
        self.s = min((self.width() - 20) / w, (self.height() - 20) / h)
        self.cx, self.cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        self.update()

    def pt(self, x, y):
        return QPointF(self.width() / 2 + (x - self.cx) * self.s, self.height() / 2 - (y - self.cy) * self.s)

    def inv(self, p):
        return ((p.x() - self.width() / 2) / self.s + self.cx, -(p.y() - self.height() / 2) / self.s + self.cy)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#8aa0c8"), 0.8))
        for l in self.dlg.lines_m:
            p.drawLine(self.pt(l[0], l[1]), self.pt(l[2], l[3]))
        p.setPen(QColor("#2a7d2a"))
        p.setFont(QFont("Arial", 8))
        for t, x, y in self.dlg.texts_m:
            p.drawText(self.pt(x, y), t)
        if self.sel is not None:
            poly = self.dlg.shapes[self.sel]["poly"]
            p.setPen(QPen(QColor("#d6209a"), 2.5))
            p.setBrush(QColor(214, 32, 154, 40))
            p.drawPolygon(QPolygonF([self.pt(*q) for q in poly]))
        if self.street_poly:
            sp = self.street_poly
            p.setPen(QPen(QColor("#d6209a"), 3))
            p.setBrush(QColor(214, 32, 154, 40))
            p.drawPolygon(QPolygonF([self.pt(*q) for q in sp]))
            p.setPen(QColor("#d6209a"))
            p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            for i, q in enumerate(sp):
                p.drawText(self.pt(*q) + QPointF(6, -6), str(i + 1))
            if self.hover and self.dlg.street_mode:
                i = self.edge_at(self.hover)
                p.setPen(QPen(QColor("#e00000"), 6))
                p.drawLine(self.pt(*sp[i]), self.pt(*sp[(i + 1) % len(sp)]))
        elif self.pts:
            p.setPen(QPen(QColor("#d6209a"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            qs = [self.pt(*q) for q in self.pts]
            p.drawPolyline(QPolygonF(qs + ([self.pt(*self.hover)] if self.hover else [])))
            p.setBrush(QColor("#d6209a"))
            for q in qs:
                p.drawEllipse(q, 4, 4)
        if self.hover and self.pick:
            p.setPen(QPen(QColor("#d6209a"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self.pt(*self.hover), 7, 7)

    def edge_at(self, w):
        sp = self.street_poly
        n = len(sp)
        def dist(i):
            a, b = sp[i], sp[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((w[0] - a[0]) * dx + (w[1] - a[1]) * dy) / L2))
            return math.hypot(a[0] + t * dx - w[0], a[1] + t * dy - w[1])
        return min(range(n), key=dist)

    def _snap(self, w):
        best, bd = None, 12.0 / self.s
        for l in self.dlg.lines_m:
            for q in ((l[0], l[1]), (l[2], l[3])):
                d = math.hypot(q[0] - w[0], q[1] - w[1])
                if d < bd:
                    best, bd = q, d
        return best or w

    def mouseMoveEvent(self, e):
        if self._pan:
            dx, dy = e.position().x() - self._pan[0].x(), e.position().y() - self._pan[0].y()
            self.cx, self.cy = self._pan[1] - dx / self.s, self._pan[2] + dy / self.s
            self.update()
            return
        if self.dlg.street_mode:
            self.hover = self.inv(e.position())
            self.update()
        elif self.pick:
            self.hover = self._snap(self.inv(e.position()))
            self.update()

    def mousePressEvent(self, e):
        if e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan = (e.position(), self.cx, self.cy)
        elif e.button() == Qt.MouseButton.LeftButton and self.dlg.street_mode:
            self.dlg.street_chosen(self.edge_at(self.inv(e.position())))
        elif e.button() == Qt.MouseButton.LeftButton and self.pick:
            self.pts.append(self._snap(self.inv(e.position())))
            self.dlg.note()
            self.update()

    def mouseReleaseEvent(self, _e):
        self._pan = None

    def mouseDoubleClickEvent(self, e):
        if self.pick and len(self.pts) >= 3:
            self.dlg.use_clicked()

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        w = self.inv(e.position())
        self.s *= f
        p = self.pt(*w)
        self.cx += (p.x() - e.position().x()) / self.s
        self.cy -= (p.y() - e.position().y()) / self.s
        self.update()


class ImportDialog(QDialog):
    def __init__(self, parent, drawing, role):
        super().__init__(parent)
        self.setWindowTitle("Import the %s from a drawing" % role)
        self.drawing, self.role = drawing, role
        self.result = None
        self.street_mode = False
        self.street_edge = None
        self.lines_m, self.texts_m, self.shapes = [], [], []
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.unit = QComboBox()
        for n, f in UNITS:
            self.unit.addItem(n, f)
        u = drawing["unit"]
        self.unit.setCurrentIndex(min(range(3), key=lambda i: abs(UNITS[i][1] - u)))
        self.scale = QDoubleSpinBox()
        self.scale.setRange(1, 5000)
        self.scale.setDecimals(0)
        self.scale.setValue(1)
        self.scale.setPrefix("1 : ")
        self.scale.setToolTip("Leave at 1 : 1 if the drawing is drawn full size (most are). Use 1 : 200 only if the drawing units are paper millimetres of a 1:200 sheet.")
        row.addWidget(QLabel("Drawing units"))
        row.addWidget(self.unit)
        row.addWidget(QLabel("Drawn at"))
        row.addWidget(self.scale)
        self.size_lbl = QLabel("")
        row.addWidget(self.size_lbl, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.prev = Preview(self)
        row.addWidget(self.prev, 3)
        side = QVBoxLayout()
        side.addWidget(QLabel("Closed outlines found:"))
        self.lw = QListWidget()
        self.lw.currentRowChanged.connect(self._sel)
        self.lw.itemDoubleClicked.connect(lambda *_: self.use_selected())
        side.addWidget(self.lw, 1)
        b = QPushButton("Use the selected outline")
        b.clicked.connect(self.use_selected)
        side.addWidget(b)
        self.pk = QPushButton("Click the corners myself")
        self.pk.setCheckable(True)
        self.pk.toggled.connect(self._pick)
        side.addWidget(self.pk)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        side.addWidget(self.hint)
        row2 = QHBoxLayout()
        ub = QPushButton("Undo corner")
        ub.clicked.connect(self._undo)
        ob = QPushButton("Use my corners")
        ob.clicked.connect(self.use_clicked)
        row2.addWidget(ub)
        row2.addWidget(ob)
        side.addLayout(row2)
        self.under_cb = QCheckBox("Show this drawing's lines under the plan")
        self.under_cb.setChecked(role == "stand")
        self.under_cb.setVisible(role == "stand")
        side.addWidget(self.under_cb)
        cb = QPushButton("Cancel")
        cb.clicked.connect(self.reject)
        side.addWidget(cb)
        row.addLayout(side, 1)
        v.addLayout(row, 1)
        self._auto_scale()
        if role == "stand":
            self.pk.setChecked(True)                        # you click the corners of the stand, 1, 2, 3 ... and then the street side
        self.unit.currentIndexChanged.connect(self.rebuild)
        self.scale.valueChanged.connect(self.rebuild)
        self.resize(1000, 640)
        self.rebuild()

    RANGES = {"stand": (60, 6000), "house": (30, 900), "carport": (8, 150)}

    def _auto_scale(self):
        """drawings are full size, or drawn in paper units at 1:N. Keep the units the file says (or the size suggests) when the whole drawing then comes out a
        believable size on the ground (5 m to 1.5 km across). Otherwise try 1:200, 1:100, 1:50, 1:500 ... until it does, so a drawing saved 'at 1:200'
        lands at true size. The size is always shown, and both boxes can be changed by hand."""
        d = self.drawing
        span = max(d["span"]) or 1.0
        self.auto_note = ""
        base = UNITS[self.unit.currentIndex()][1]
        if 5 <= span * base <= 1500:
            self.auto_note = "Full size: %s, drawn at 1 : 1." % UNITS[self.unit.currentIndex()][0]
        elif span * base > 1500:
            for i in (0, 1):
                if 5 <= span * UNITS[i][1] <= 1500:
                    self.unit.setCurrentIndex(i)
                    self.auto_note = "Worked out from the size: %s, drawn at 1 : 1." % UNITS[i][0]
                    break
        else:
            for s in (200, 100, 50, 500, 20, 1000, 10, 2000):
                for i in sorted(range(3), key=lambda i: abs(UNITS[i][1] - d["unit"])):
                    if 5 <= span * UNITS[i][1] * s <= 1500:
                        self.unit.setCurrentIndex(i)
                        self.scale.setValue(s)
                        self.auto_note = "Worked out from the size: %s, drawn at 1 : %d." % (UNITS[i][0], s)
                        break
                else:
                    continue
                break
        self.rebuild()

    def factor(self):
        return self.unit.currentData() * self.scale.value()

    def rebuild(self, *_a):
        f = self.factor()
        d = self.drawing
        self.lines_m = [(l[0] * f, l[1] * f, l[2] * f, l[3] * f, l[4]) for l in d["lines"]]
        self.texts_m = [(t, x * f, y * f) for t, x, y in d["texts"]]
        self.shapes = site_dxf.outlines(d, f)
        self.lw.blockSignals(True)
        self.lw.clear()
        for s in self.shapes:
            xs, ys = [p[0] for p in s["poly"]], [p[1] for p in s["poly"]]
            self.lw.addItem("%.1f m2   %.1f x %.1f m   %d corners" % (s["area"], max(xs) - min(xs), max(ys) - min(ys), len(s["poly"])))
        self.lw.blockSignals(False)
        w, h = d["span"][0] * f, d["span"][1] * f
        lo, hi = self.RANGES.get(self.role, (8, 6000))
        bad = False
        self.size_lbl.setText("The drawing is %.1f x %.1f m at these settings.%s" % (w, h, "  CHECK THE SCALE: no outline is the size of a %s." % self.role if bad else ""))
        self.prev.pts = []
        self.prev.sel = None
        self.hint.setText(getattr(self, "auto_note", "") if self.shapes else "No closed outline in this drawing (the lines do not meet). Click the corners yourself: tick the button, click each corner (it snaps to line ends), then Use my corners.")
        self.prev.fit()

    def _sel(self, i):
        self.prev.sel = i if i >= 0 else None
        self.prev.update()

    def _pick(self, on):
        self.prev.pick = on
        self.prev.pts = []
        self.note()
        self.prev.update()

    def _undo(self):
        if self.prev.pts:
            self.prev.pts.pop()
            self.note()
            self.prev.update()

    def note(self):
        n = len(self.prev.pts)
        if self.prev.pick:
            self.hint.setText("%d corners. Click the next corner in order round the outline, then Use my corners (or double-click)." % n)

    def use_selected(self):
        i = self.lw.currentRow()
        if 0 <= i < len(self.shapes):
            self.result = [tuple(p) for p in self.shapes[i]["poly"]]
            self._finish()

    def use_clicked(self):
        if len(self.prev.pts) >= 3:
            self.result = [tuple(p) for p in self.prev.pts]
            self._finish()

    def _finish(self):
        if self.role != "stand":
            self.accept()
            return
        self.street_mode = True
        self.prev.pick = False
        self.prev.street_poly = list(self.result)
        self.hint.setText("Now click the side of the stand that faces the street.")
        self.prev.update()

    def street_chosen(self, i):
        self.street_edge = i
        self.street_mode = False
        self.accept()

    def underlay(self):
        """the drawing's lines in metres, when asked for"""
        return [(l[0], l[1], l[2], l[3]) for l in self.lines_m] if self.under_cb.isChecked() else []
