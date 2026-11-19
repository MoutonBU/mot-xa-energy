"""Building lines: draw the stand, set the building lines on each boundary, place the buildings, and see at once what
encroaches. Works out coverage and floor area ratio, and writes a departure motivation to adapt."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF, QImage
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import tool_base as tb
from tool_base import ToolBase

KINDS = ["Street", "Side", "Rear", "Other"]
REASONS = [
    ("nb_light", "It does not take light, ventilation or privacy from the neighbours."),
    ("char", "It fits the character of the street, and similar departures exist nearby."),
    ("shape", "The shape or slope of the stand limits where a building can go."),
    ("serv", "A servitude, tree or service limits where the building can go."),
    ("consent", "The neighbours have given written consent."),
    ("traffic", "It does not affect traffic safety or sight lines."),
    ("min", "It is the smallest departure that makes the building workable."),
]
EPS = 0.005


def corner_name(i):
    return chr(65 + i % 26) + (str(i // 26) if i >= 26 else "")


# ---------------------------------------------------------------- geometry
def signed_area(v):
    return 0.5 * sum(v[i][0] * v[(i + 1) % len(v)][1] - v[(i + 1) % len(v)][0] * v[i][1] for i in range(len(v)))


def edge_dist(v, i, p, sign):
    """How far point p is inside boundary i (negative: outside the stand)."""
    a, b = v[i], v[(i + 1) % len(v)]
    ex, ey = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(ex, ey) or 1.0
    return sign * (ex * (p[1] - a[1]) - ey * (p[0] - a[0])) / ln


def envelope(v, sbs):
    """The area inside every building line (clip the stand by a line parallel to each boundary)."""
    if len(v) < 3:
        return []
    sign = 1.0 if signed_area(v) >= 0 else -1.0
    poly = [tuple(p) for p in v]
    for i, sb in enumerate(sbs):
        if sb <= 0 or not poly:
            continue
        out = []
        f = lambda p: edge_dist(v, i, p, sign) - sb
        for k in range(len(poly)):
            p, q = poly[k], poly[(k + 1) % len(poly)]
            fp, fq = f(p), f(q)
            if fp >= 0:
                out.append(p)
            if (fp >= 0) != (fq >= 0):
                t = fp / (fp - fq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        poly = out
    return poly


def is_convex(v):
    if len(v) < 4:
        return True
    s = 0
    for i in range(len(v)):
        a, b, c = v[i], v[(i + 1) % len(v)], v[(i + 2) % len(v)]
        z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(z) > 1e-9:
            if s and (z > 0) != (s > 0):
                return False
            s = z
    return True


def analyse(v, edges, buildings, max_cov, max_far, floor_area):
    """Per building: how far it goes into each building line. Plus coverage and floor area ratio."""
    n = len(v)
    out = {"area": abs(signed_area(v)) if n >= 3 else 0.0, "buildings": []}
    sign = 1.0 if n >= 3 and signed_area(v) >= 0 else -1.0
    cov = 0.0
    for b in buildings:
        x, y, w, d = b["x"], b["y"], b["w"], b["d"]
        corners = [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]
        enc = []
        for i in range(n):
            sb = max(0.0, edges[i]["sb"]) if i < len(edges) else 0.0
            worst = max(sb - edge_dist(v, i, p, sign) for p in corners)
            if worst > EPS:
                dist = sb - worst
                enc.append({"edge": i, "kind": edges[i]["kind"] if i < len(edges) else "Other", "sb": sb, "by": worst, "dist": dist})
        out["buildings"].append({"name": b["name"], "enc": enc, "area": w * d})
        if b.get("cov", True):
            cov += w * d
    out["cov_area"] = cov
    out["cov_pct"] = 100.0 * cov / out["area"] if out["area"] else 0.0
    out["cov_ok"] = (not max_cov) or out["cov_pct"] <= max_cov + 1e-6
    out["far"] = floor_area / out["area"] if out["area"] else 0.0
    out["far_ok"] = (not max_far) or out["far"] <= max_far + 1e-6
    return out


class PlanView(QWidget):
    """The stand, its building lines and the buildings, drawn on a sheet. Drag a building to move it."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.drag = None
        self.sel = -1
        self._map = None

    def _fit(self, v, blds, W, H):
        xs = [p[0] for p in v] + [b["x"] for b in blds] + [b["x"] + b["w"] for b in blds]
        ys = [p[1] for p in v] + [b["y"] for b in blds] + [b["y"] + b["d"] for b in blds]
        if not xs:
            xs, ys = [0, 10], [0, 10]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        pad = 46
        s = min((W - 2 * pad) / max(x1 - x0, 1e-6), (H - 2 * pad) / max(y1 - y0, 1e-6))
        ox = (W - (x1 - x0) * s) / 2
        oy = (H - (y1 - y0) * s) / 2
        return lambda p: QPointF(ox + (p[0] - x0) * s, H - oy - (p[1] - y0) * s), s, (x0, y0, ox, oy, H)

    def draw(self, p, W, H):
        pg = self.page
        v, edges, blds = pg.verts(), pg.edges(), pg.buildings()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(0, 0, W, H, QColor("#fbfbf8"))
        if len(v) < 3:
            p.setPen(QColor("#777777"))
            p.drawText(QRectF(0, 0, W, H), int(Qt.AlignmentFlag.AlignCenter), "Enter the corners of the stand\nor press Make a rectangle.")
            self._map = None
            return
        to, s, inv = self._fit(v, blds, W, H)
        self._map = (s, inv)
        sbs = [e["sb"] for e in edges]
        stand = QPolygonF([to(q) for q in v])
        p.setPen(QPen(QColor("#222222"), 2))
        p.setBrush(QColor("#efede2"))
        p.drawPolygon(stand)
        env = envelope(v, sbs)
        if len(env) >= 3:
            p.setBrush(QColor(46, 158, 91, 38))
            pen = QPen(QColor("#C8102E"), 1.6, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawPolygon(QPolygonF([to(q) for q in env]))
        an = analyse(v, edges, blds, 0, 0, 0)
        for i, b in enumerate(blds):
            bad = bool(an["buildings"][i]["enc"])
            r = QRectF(to((b["x"], b["y"] + b["d"])), to((b["x"] + b["w"], b["y"])))
            p.setBrush(QColor(200, 16, 46, 120) if bad else QColor(60, 120, 200, 110))
            p.setPen(QPen(QColor("#C8102E") if bad else QColor("#2a5fa8"), 3 if i == self.sel else 1.6))
            p.drawRect(r)
            p.setPen(QColor("#111111"))
            f = QFont("Arial")
            f.setPixelSize(12 if W < 900 else 19)
            p.setFont(f)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), b["name"])
        f = QFont("Arial")
        f.setPixelSize(11 if W < 900 else 17)
        p.setFont(f)
        cen = QPointF(sum(to(q).x() for q in v) / len(v), sum(to(q).y() for q in v) / len(v))
        for i in range(len(v)):
            a, b = to(v[i]), to(v[(i + 1) % len(v)])
            m = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            dx, dy = m.x() - cen.x(), m.y() - cen.y()
            ln = math.hypot(dx, dy) or 1
            tp = QPointF(m.x() + dx / ln * 34, m.y() + dy / ln * 16)
            p.setPen(QColor("#333333"))
            k = edges[i]["kind"] if i < len(edges) else ""
            txt = "%s %s" % (k, ("%.1f m" % edges[i]["sb"]) if i < len(edges) and edges[i]["sb"] else "")
            p.drawText(QRectF(tp.x() - 80, tp.y() - 10, 160, 20), int(Qt.AlignmentFlag.AlignCenter), txt.strip())
            p.setPen(QPen(QColor("#222222"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(a, 8 if W < 900 else 12, 8 if W < 900 else 12)
            p.drawText(QRectF(a.x() - 12, a.y() - 12, 24, 24), int(Qt.AlignmentFlag.AlignCenter), corner_name(i))
        # scale bar
        length = 10 if s * 10 < W * 0.45 else 5
        x0, y0 = 14, H - 16
        p.setPen(QPen(QColor("#222222"), 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + s * length, y0))
        p.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        p.drawLine(QPointF(x0 + s * length, y0 - 4), QPointF(x0 + s * length, y0 + 4))
        p.setPen(QColor("#222222"))
        p.drawText(QPointF(x0 + s * length + 6, y0 + 5), "%d m" % length)

    def paintEvent(self, _e):
        p = QPainter(self)
        self.draw(p, self.width(), self.height())
        p.end()

    def snapshot(self, W=1000, H=720):
        img = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(img)
        self.draw(p, W, H)
        p.setPen(QPen(QColor("#999999"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, W - 1, H - 1)
        p.end()
        return img

    # ---- dragging buildings
    def _world(self, pt):
        if not self._map:
            return None
        s, (x0, y0, ox, oy, H) = self._map
        return (x0 + (pt.x() - ox) / s, y0 + (H - oy - pt.y()) / s)

    def mousePressEvent(self, e):
        w = self._world(e.position())
        if w is None:
            return
        blds = self.page.buildings()
        for i in range(len(blds) - 1, -1, -1):
            b = blds[i]
            if b["x"] <= w[0] <= b["x"] + b["w"] and b["y"] <= w[1] <= b["y"] + b["d"]:
                self.sel = i
                self.drag = (i, w[0] - b["x"], w[1] - b["y"])
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.page.select_building(i)
                self.update()
                return
        self.sel = -1
        self.update()

    def mouseMoveEvent(self, e):
        w = self._world(e.position())
        if w is None:
            return
        if self.drag:
            i, dx, dy = self.drag
            self.page.move_building(i, round((w[0] - dx) * 20) / 20, round((w[1] - dy) * 20) / 20)
        else:
            over = any(b["x"] <= w[0] <= b["x"] + b["w"] and b["y"] <= w[1] <= b["y"] + b["d"] for b in self.page.buildings())
            self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, _e):
        self.drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)


def spin(lo, hi, val, dec=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class SitePage(ToolBase):
    KEY = "site"
    TITLE = "Building lines"
    STEP_NAMES = ["The stand", "The buildings", "The result"]
    STEP_HINTS = ["Describe the stand: its corners in metres and the building line on each boundary. A plain rectangle takes two numbers.",
                  "Place each building by its corner position and size, or drag it in the plan. Red means it goes over a building line.",
                  "What complies, what encroaches and by how much, coverage and floor area ratio, and a departure motivation to adapt."]

    def __init__(self, win):
        super().__init__(win)
        self._busy = False
        self.plan = PlanView(self)
        # ---- step 1
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The stand")
        row = QHBoxLayout()
        self.erf = QLineEdit()
        self.erf.setPlaceholderText("Erf number and suburb or town")
        self.zoning = QLineEdit()
        self.zoning.setPlaceholderText("for example Residential zone I")
        row.addWidget(QLabel("Erf"))
        row.addWidget(self.erf, 2)
        row.addWidget(QLabel("Zoning"))
        row.addWidget(self.zoning, 2)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("Corners of the stand", "Metres, measured from any corner. Go round the stand in order. A rectangle is the quickest start.")
        rr = QHBoxLayout()
        self.q_w, self.q_d = spin(1, 5000, 20, 2, " m"), spin(1, 5000, 30, 2, " m")
        rr.addWidget(QLabel("Width"))
        rr.addWidget(self.q_w)
        rr.addWidget(QLabel("Depth"))
        rr.addWidget(self.q_d)
        mk = QPushButton("Make a rectangle")
        mk.setToolTip("Sets four corners. The bottom boundary is the street.")
        mk.clicked.connect(self.make_rect)
        rr.addWidget(mk)
        rr.addStretch(1)
        bv.addLayout(rr)
        self.vt = QTableWidget(0, 3)
        self.vt.setHorizontalHeaderLabels(["Corner", "X (m)", "Y (m)"])
        self.vt.verticalHeader().setVisible(False)
        self.vt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.vt.setMinimumHeight(150)
        self.vt.itemChanged.connect(self._verts_edited)
        bv.addWidget(self.vt)
        br = QHBoxLayout()
        a1, a2 = QPushButton("Add a corner"), QPushButton("Remove last corner")
        a1.clicked.connect(lambda: self.add_vertex())
        a2.clicked.connect(self.remove_vertex)
        br.addWidget(a1)
        br.addWidget(a2)
        br.addStretch(1)
        bv.addLayout(br)
        self.area_lbl = QLabel("")
        self.area_lbl.setObjectName("xaSub")
        bv.addWidget(self.area_lbl)
        v1.addWidget(bx)
        bx, bv = self.box("Building lines", "Set the distance to keep clear on each boundary. Check the numbers against your zoning scheme.")
        qr = QHBoxLayout()
        self.q_street, self.q_side, self.q_rear = spin(0, 50, 4.0, 2, " m"), spin(0, 50, 2.0, 2, " m"), spin(0, 50, 3.0, 2, " m")
        for lab, w_ in (("Street", self.q_street), ("Side", self.q_side), ("Rear", self.q_rear)):
            qr.addWidget(QLabel(lab))
            qr.addWidget(w_)
        ap = QPushButton("Apply to the boundaries")
        ap.setToolTip("Fills the table below from the kind of each boundary.")
        ap.clicked.connect(self.apply_quick)
        qr.addWidget(ap)
        qr.addStretch(1)
        bv.addLayout(qr)
        self.et = QTableWidget(0, 3)
        self.et.setHorizontalHeaderLabels(["Boundary", "Kind", "Building line (m)"])
        self.et.verticalHeader().setVisible(False)
        self.et.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.et.setMinimumHeight(150)
        bv.addWidget(self.et)
        v1.addWidget(bx)
        bx, bv = self.box("Limits", "Coverage is the share of the stand the buildings cover. FAR is the floor area divided by the stand area. Use 0 for no limit.")
        lr = QHBoxLayout()
        self.max_cov, self.max_far, self.floor_area = spin(0, 100, 60, 1, " %"), spin(0, 20, 0, 2), spin(0, 100000, 0, 2, " m2")
        for lab, w_ in (("Coverage limit", self.max_cov), ("FAR limit", self.max_far), ("Floor area", self.floor_area)):
            lr.addWidget(QLabel(lab))
            lr.addWidget(w_)
        self.follow = QCheckBox("Follow the area schedule")
        self.follow.setChecked(True)
        self.follow.setToolTip("Uses the floor area that counts for FAR in the Area schedule.")
        lr.addWidget(self.follow)
        lr.addStretch(1)
        bv.addLayout(lr)
        v1.addWidget(bx)
        v1.addStretch(1)
        # ---- step 2
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Buildings on the stand", "X and Y are the lower left corner of the building, in metres, from the same corner as the stand.")
        self.bt = QTableWidget(0, 6)
        self.bt.setHorizontalHeaderLabels(["Name", "X (m)", "Y (m)", "Width (m)", "Depth (m)", "In coverage"])
        self.bt.verticalHeader().setVisible(False)
        self.bt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bt.setMinimumHeight(220)
        self.bt.itemChanged.connect(self._bld_edited)
        self.bt.itemSelectionChanged.connect(self._sel_changed)
        bv.addWidget(self.bt)
        br = QHBoxLayout()
        for text, fn in (("Add a building", lambda: self.add_building()), ("Remove selected", self.remove_building),
                         ("Centre it on the stand", self.centre_building)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        self.live_lbl = QLabel("")
        self.live_lbl.setWordWrap(True)
        bv.addWidget(self.live_lbl)
        v2.addWidget(bx)
        v2.addStretch(1)
        # ---- step 3
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("What complies", "")
        self.res_t = QTableWidget(0, 3)
        self.res_t.setHorizontalHeaderLabels(["Check", "Result", "Detail"])
        self.res_t.verticalHeader().setVisible(False)
        self.res_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.res_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.res_t.setMinimumHeight(180)
        bv.addWidget(self.res_t)
        v3.addWidget(bx)
        bx, bv = self.box("Departure motivation", "Only needed when a building goes over a building line. Tick the reasons that are true, then adapt the text.")
        self.reason_cb = {}
        for k, t in REASONS:
            c = QCheckBox(t)
            c.toggled.connect(self._reason_toggled)
            self.reason_cb[k] = c
            bv.addWidget(c)
        self.motiv = QPlainTextEdit()
        self.motiv.setMinimumHeight(200)
        self.motiv.textChanged.connect(self._motiv_edited)
        bv.addWidget(self.motiv)
        mr = QHBoxLayout()
        wb = QPushButton("Write it again")
        wb.setToolTip("Replaces the text with a fresh draft from the numbers and the ticked reasons.")
        wb.clicked.connect(lambda: self.write_motivation(force=True))
        cp = QPushButton("Copy the text")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.motiv.toPlainText()))
        mr.addWidget(wb)
        mr.addWidget(cp)
        mr.addStretch(1)
        bv.addLayout(mr)
        v3.addWidget(bx)
        bx, bv = self.box("Reports")
        rr = QHBoxLayout()
        for text, fn in (("Preview the PDF", self.preview), ("Save the PDF...", self.export)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            rr.addWidget(b)
        rr.addStretch(1)
        bv.addLayout(rr)
        v3.addWidget(bx)
        v3.addStretch(1)
        self._motiv_user = False
        self.build_frame([p1, p2, p3], side=self.plan)
        self.make_rect()
        self.restore()
        self._after_edit()

    # ---- reading the tables
    def verts(self):
        out = []
        for r in range(self.vt.rowCount()):
            x, y = self.vt.item(r, 1), self.vt.item(r, 2)
            out.append((tb.num(x.text() if x else 0), tb.num(y.text() if y else 0)))
        return out

    def edges(self):
        out = []
        for r in range(self.et.rowCount()):
            cb, sp = self.et.cellWidget(r, 1), self.et.cellWidget(r, 2)
            out.append({"kind": cb.currentText() if cb else "Side", "sb": sp.value() if sp else 0.0})
        return out

    def buildings(self):
        out = []
        t = self.bt
        g = lambda r, c: tb.num(t.item(r, c).text() if t.item(r, c) else 0)
        for r in range(t.rowCount()):
            nm = t.item(r, 0).text().strip() if t.item(r, 0) else ""
            out.append({"name": nm or "Building %d" % (r + 1), "x": g(r, 1), "y": g(r, 2), "w": g(r, 3), "d": g(r, 4),
                        "cov": bool(t.item(r, 5) and t.item(r, 5).checkState() == Qt.CheckState.Checked)})
        return out

    # ---- the stand
    def set_vertices(self, vs, edges=None):
        self._busy = True
        try:
            old = edges or self.edges()
            self.vt.setRowCount(0)
            for i, (x, y) in enumerate(vs):
                self.vt.insertRow(i)
                c = QTableWidgetItem(corner_name(i))
                c.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.vt.setItem(i, 0, c)
                for k, val in ((1, x), (2, y)):
                    it = QTableWidgetItem("%.2f" % val)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.vt.setItem(i, k, it)
            self.et.setRowCount(0)
            n = len(vs)
            for i in range(n):
                self.et.insertRow(i)
                lab = QTableWidgetItem("%s to %s" % (corner_name(i), corner_name((i + 1) % n)))
                lab.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.et.setItem(i, 0, lab)
                e = old[i] if i < len(old) else {"kind": "Side", "sb": self.q_side.value()}
                cb = QComboBox()
                cb.addItems(KINDS)
                cb.setCurrentText(e["kind"])
                cb.currentTextChanged.connect(lambda _t: self._after_edit(True))
                sp = spin(0, 100, e["sb"], 2, " m")
                sp.valueChanged.connect(lambda _v: self._after_edit(True))
                self.et.setCellWidget(i, 1, cb)
                self.et.setCellWidget(i, 2, sp)
        finally:
            self._busy = False

    def make_rect(self):
        w, d = self.q_w.value(), self.q_d.value()
        self.set_vertices([(0, 0), (w, 0), (w, d), (0, d)],
                          [{"kind": "Street", "sb": self.q_street.value()}, {"kind": "Side", "sb": self.q_side.value()},
                           {"kind": "Rear", "sb": self.q_rear.value()}, {"kind": "Side", "sb": self.q_side.value()}])
        self._after_edit(True)

    def add_vertex(self):
        v = self.verts()
        last = v[-1] if v else (0.0, 0.0)
        self.set_vertices(v + [(last[0] + 5, last[1] + 5)])
        self._after_edit(True)

    def remove_vertex(self):
        v = self.verts()
        if len(v) > 3:
            self.set_vertices(v[:-1])
            self._after_edit(True)

    def apply_quick(self):
        m = {"Street": self.q_street.value(), "Side": self.q_side.value(), "Rear": self.q_rear.value()}
        self._busy = True
        for r in range(self.et.rowCount()):
            k = self.et.cellWidget(r, 1).currentText()
            if k in m:
                self.et.cellWidget(r, 2).setValue(m[k])
        self._busy = False
        self._after_edit(True)

    def _verts_edited(self, _it):
        if not self._busy:
            self._after_edit(True)

    # ---- the buildings
    def add_building(self, d=None):
        d = d or {}
        self._busy = True
        try:
            r = self.bt.rowCount()
            self.bt.insertRow(r)
            v = self.verts()
            if d:
                vals = [d.get("name", ""), d.get("x", 0), d.get("y", 0), d.get("w", 10), d.get("d", 10)]
            else:
                bw, bd = 10.0, 8.0
                if v:
                    xs, ys = [p[0] for p in v], [p[1] for p in v]
                    vals = ["Building %d" % (r + 1), round((min(xs) + max(xs)) / 2 - bw / 2, 2), round((min(ys) + max(ys)) / 2 - bd / 2, 2), bw, bd]
                else:
                    vals = ["Building %d" % (r + 1), 0, 0, bw, bd]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val if isinstance(val, str) else "%.2f" % val)
                if c:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.bt.setItem(r, c, it)
            f = QTableWidgetItem("")
            f.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            f.setCheckState(Qt.CheckState.Checked if d.get("cov", True) else Qt.CheckState.Unchecked)
            self.bt.setItem(r, 5, f)
        finally:
            self._busy = False
        self._after_edit(True)

    def remove_building(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()}, reverse=True) or ([self.bt.rowCount() - 1] if self.bt.rowCount() else [])
        for r in rows:
            self.bt.removeRow(r)
        self._after_edit(True)

    def centre_building(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()}) or ([0] if self.bt.rowCount() else [])
        v = self.verts()
        if not v:
            return
        cx, cy = sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)
        bl = self.buildings()
        self._busy = True
        for r in rows:
            self.bt.item(r, 1).setText("%.2f" % (cx - bl[r]["w"] / 2))
            self.bt.item(r, 2).setText("%.2f" % (cy - bl[r]["d"] / 2))
        self._busy = False
        self._after_edit(True)

    def _bld_edited(self, _it):
        if not self._busy:
            self._after_edit(True)

    def _sel_changed(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        self.plan.sel = rows[0] if rows else -1
        self.plan.update()

    def select_building(self, i):
        self.bt.selectRow(i)

    def move_building(self, i, x, y):
        if i >= self.bt.rowCount():
            return
        self._busy = True
        self.bt.item(i, 1).setText("%.2f" % x)
        self.bt.item(i, 2).setText("%.2f" % y)
        self._busy = False
        self._after_edit(True)

    # ---- results
    def current_floor_area(self):
        if self.follow.isChecked():
            ap = getattr(self.win, "area_page", None)
            if ap is not None and ap.total_area() > 0:
                return ap.far_area()
        return self.floor_area.value()

    def result(self):
        return analyse(self.verts(), self.edges(), self.buildings(), self.max_cov.value(), self.max_far.value(), self.current_floor_area())

    def encroachments(self):
        an = self.result()
        return [(b["name"], e) for b in an["buildings"] for e in b["enc"]]

    def _after_edit(self, user=False):
        if self._busy:
            return
        v = self.verts()
        if self.follow.isChecked():
            ap = getattr(self.win, "area_page", None)
            if ap is not None and ap.total_area() > 0:
                self._busy = True
                self.floor_area.setValue(ap.far_area())
                self._busy = False
        a = abs(signed_area(v)) if len(v) >= 3 else 0
        note = "" if is_convex(v) else "  The stand is not convex, so the check near inside corners is approximate."
        self.area_lbl.setText("Stand area: %.2f m2.%s" % (a, note))
        an = self.result()
        enc = [(b["name"], e) for b in an["buildings"] for e in b["enc"]]
        if not an["buildings"]:
            self.live_lbl.setText("No buildings yet. Press Add a building.")
        elif enc:
            self.live_lbl.setText("<span style='color:#d8303f'><b>%d building line problem%s.</b></span> See the plan (red)." % (len(enc), "" if len(enc) == 1 else "s"))
        else:
            self.live_lbl.setText("<span style='color:#2e9e5b'><b>Every building is inside the building lines.</b></span>")
        self.fill_results(an)
        if not self._motiv_user:
            self.write_motivation()
        self.plan.update()
        if user:
            self.changed()

    def fill_results(self, an):
        t = self.res_t
        t.setRowCount(0)
        rows = []
        for b in an["buildings"]:
            if b["enc"]:
                rows.append((b["name"] + " - building lines", "Over", "; ".join("%s line %s: over by %.2f m (%.2f m from the boundary)" %
                                                                                (e["kind"].lower(), self._edge_name(e["edge"]), e["by"], e["dist"]) for e in b["enc"]), False))
            else:
                rows.append((b["name"] + " - building lines", "OK", "Inside every building line", True))
        rows.append(("Coverage", "OK" if an["cov_ok"] else "Over", "%.1f %% of the stand%s" % (an["cov_pct"], (" (limit %.1f %%)" % self.max_cov.value()) if self.max_cov.value() else ""), an["cov_ok"]))
        rows.append(("Floor area ratio", "OK" if an["far_ok"] else "Over", "%.2f%s" % (an["far"], (" (limit %.2f)" % self.max_far.value()) if self.max_far.value() else "") +
                     ("" if self.current_floor_area() else "  - no floor area yet (fill the Area schedule)"), an["far_ok"]))
        for lab, res, det, ok in rows:
            r = t.rowCount()
            t.insertRow(r)
            for c, val in enumerate((lab, res, det)):
                it = QTableWidgetItem(val)
                if c == 1:
                    it.setForeground(QColor("#2e9e5b") if ok else QColor("#e0243a"))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                t.setItem(r, c, it)
        t.setColumnWidth(0, 200)
        t.setColumnWidth(1, 70)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        t.setWordWrap(True)
        t.resizeRowsToContents()

    def _edge_name(self, i):
        n = len(self.verts())
        return "%s to %s" % (corner_name(i), corner_name((i + 1) % n)) if n else ""

    # ---- the departure motivation
    def _reason_toggled(self, _c):
        self.write_motivation(force=True)
        self.changed()

    def _motiv_edited(self):
        if not getattr(self, "_writing", False):
            self._motiv_user = True
            self.changed()

    def motivation_text(self):
        an = self.result()
        enc = [(b["name"], e) for b in an["buildings"] for e in b["enc"]]
        site = (self.erf.text().strip() or (getattr(self.win, "rd", {}) or {}).get("details") or "the stand")
        if not enc:
            return "No departure is needed on %s: every building is inside the building lines." % site
        lines = ["APPLICATION FOR A DEPARTURE FROM THE BUILDING LINES", site, "",
                 "The proposed building work goes over the following building lines:"]
        for nm, e in enc:
            lines.append("- %s goes %.2f m into the %.2f m %s building line (boundary %s), which leaves %.2f m to the boundary." %
                         (nm, e["by"], e["sb"], e["kind"].lower(), self._edge_name(e["edge"]), e["dist"]))
        picked = [t for k, t in REASONS if self.reason_cb[k].isChecked()]
        lines += ["", "Motivation:"]
        lines += ["%d. %s" % (i + 1, t) for i, t in enumerate(picked)] if picked else ["(Tick the reasons that are true above, or write your own here.)"]
        lines += ["", "Approval is respectfully requested for a relaxation of the building line(s) as shown on the attached site plan."]
        return "\n".join(lines)

    def write_motivation(self, force=False):
        if force:
            self._motiv_user = False
        if self._motiv_user:
            return
        self._writing = True
        self.motiv.setPlainText(self.motivation_text())
        self._writing = False

    # ---- state
    def state(self):
        return {"erf": self.erf.text(), "zoning": self.zoning.text(), "verts": [list(p) for p in self.verts()], "edges": self.edges(),
                "max_cov": self.max_cov.value(), "max_far": self.max_far.value(), "floor_area": self.floor_area.value(),
                "follow": self.follow.isChecked(), "buildings": self.buildings(),
                "reasons": [k for k, c in self.reason_cb.items() if c.isChecked()],
                "motivation": self.motiv.toPlainText() if self._motiv_user else "", "q": [self.q_street.value(), self.q_side.value(), self.q_rear.value()]}

    def set_state(self, d):
        d = d or {}
        self._busy = True
        self.erf.setText(d.get("erf", ""))
        self.zoning.setText(d.get("zoning", ""))
        self.max_cov.setValue(d.get("max_cov", 60))
        self.max_far.setValue(d.get("max_far", 0))
        self.floor_area.setValue(d.get("floor_area", 0))
        self.follow.setChecked(d.get("follow", True))
        q = d.get("q") or [4.0, 2.0, 3.0]
        self.q_street.setValue(q[0]), self.q_side.setValue(q[1]), self.q_rear.setValue(q[2])
        for k, c in self.reason_cb.items():
            c.setChecked(k in (d.get("reasons") or []))
        self._busy = False
        if d.get("verts"):
            self.set_vertices([tuple(p) for p in d["verts"]], d.get("edges"))
        else:
            self.make_rect()
        self._busy = True
        self.bt.setRowCount(0)
        self._busy = False
        for b in d.get("buildings") or []:
            self.add_building(b)
        self._motiv_user = bool(d.get("motivation"))
        if self._motiv_user:
            self._writing = True
            self.motiv.setPlainText(d["motivation"])
            self._writing = False
        self._after_edit()

    # ---- the report
    def report_resources(self):
        return {"plan": self.plan.snapshot()}

    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        an = self.result()
        t = lambda v: "yes" if v else "no"
        body = '<p style="font-size:11pt;"><b>%s</b>%s &nbsp;|&nbsp; stand area %.2f m2</p>' % (
            tb.esc(self.erf.text() or rd.get("details") or "Stand"), (" &nbsp;|&nbsp; " + tb.esc(self.zoning.text())) if self.zoning.text() else "", an["area"])
        body += '<p align="center"><img src="plan" width="620"></p>'
        body += '<p style="font-size:8pt; color:#555555;">Green: the area inside every building line. Red dashed line: the building lines.</p>'
        body += "<h3>Building lines</h3>" + tb.table(["Boundary", "Kind", "Building line m"],
                                                     [[self._edge_name(i), e["kind"], "%.2f" % e["sb"]] for i, e in enumerate(self.edges())], aligns=["left", "left", "right"])
        rows = []
        for b in an["buildings"]:
            if b["enc"]:
                for e in b["enc"]:
                    rows.append(([b["name"], "%s %s" % (e["kind"], self._edge_name(e["edge"])), "%.2f" % e["sb"], "%.2f" % e["dist"], "%.2f" % e["by"]], "#fde3e6"))
            else:
                rows.append((([b["name"], "all", "", "", "complies"]), "#e4f4ea"))
        body += "<h3>Buildings</h3>" + tb.table(["Building", "Building line", "Required m", "Distance m", "Over by m"], rows,
                                                 aligns=["left", "left", "right", "right", "right"])
        body += "<h3>Coverage and floor area ratio</h3>" + tb.table(
            ["Check", "Result", "Limit", "Complies"],
            [["Coverage", "%.1f %% (%.2f m2)" % (an["cov_pct"], an["cov_area"]), ("%.1f %%" % self.max_cov.value()) if self.max_cov.value() else "none", t(an["cov_ok"])],
             ["Floor area ratio", "%.2f (%.2f m2)" % (an["far"], self.current_floor_area()), ("%.2f" % self.max_far.value()) if self.max_far.value() else "none", t(an["far_ok"])]])
        mot = self.motiv.toPlainText().strip()
        if any(b["enc"] for b in an["buildings"]) and mot:
            body += "<h3>Departure motivation</h3><p>%s</p>" % tb.esc(mot).replace("\n", "<br>")
        return tb.report_doc_html("Building lines", "Building lines, coverage and floor area ratio", body, rd)

    def write_motivation_pdf(self, path):
        rd = getattr(self.win, "rd", {}) or {}
        body = "<p>%s</p>" % tb.esc(self.motiv.toPlainText()).replace("\n", "<br>")
        d, w = tb.write_pdf(path, tb.report_doc_html("Departure motivation", "Application for a departure from the building lines", body, rd), "Departure motivation")
        tb.print_doc(d, w)
