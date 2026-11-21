"""Site services: give it the stand, the house footprint and the carport, say where the sewer connection, the water connection and the
electrical supply are, and it draws the sewer, water and electrical lines to the house, with rodding eyes, inspection eyes, the meter,
the DB, the fall and the invert depths. Move anything and everything redraws. Stands from the Blue Hills SG sheets are built in."""
import json
import math

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, QSizeF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF, QPageSize, QPageLayout, QPdfWriter, QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

import site_engine as se
import site_sheet
import tool_base as tb
from flow_layout import FlowLayout
from tool_base import ToolBase

try:
    import site_stands_data as sdata
    STANDS = sdata.STANDS
except Exception:                                   # the data file is optional: stands can still be typed in
    STANDS = {}

BROWN, BLUE, YELLOW, RED = QColor("#8a3b00"), QColor("#1e7fe0"), QColor("#c9a800"), QColor("#ff0000")
KINDS = {"sewer": "Sewer", "water": "Water", "elec": "Electrical"}


def spin(lo, hi, val, dec=2, suffix="", step=None):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setSingleStep(step or (0.1 if dec else 1))
    s.setKeyboardTracking(False)
    return s


def blank_state():
    return {"stand": {"corners": [[0, 0], [13.5, 0], [13.5, 22], [0, 22]], "setbacks": {"street": 1.0, "side": 1.0, "rear": 2.0}, "name": "Stand"},
            "house": {"cx": 9.0, "cy": 12.0, "w": 14.8, "d": 6.5, "rot": 90},
            "carport": {"cx": 3.5, "cy": 3.5, "w": 5.0, "d": 5.0, "rot": 0},
            "points": {"sewer": [12.0, 0.0], "water": [1.5, 0.0], "elec": [6.75, 0.0]},
            "ports": {}, "params": {},
            "sheet": {"road": "left", "street": "", "road_w": "13m", "street_erf": "", "stand_no": "", "north": 0.0}}


# what the finished plans say for the built-in stands: the side the road is on, the street, the north arrow
SHEET_DEFAULTS = {"2068": ("right", "THIMBLE STREET", -8.7), "2091": ("right", "CATSTAIL STREET", -8.7), "2093": ("right", "CATSTAIL STREET", -6.5),
                  "2144": ("left", "CATSTAIL STREET", -8.7), "2155": ("left", "BLUESTEM STREET", -8.7)}


# ------------------------------------------------------------------ the plan
class ServicesView(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.view = None                       # (px per m, world x at the centre, world y at the centre)
        self.auto = True
        self.mode = "select"                   # select | pt_sewer | pt_water | pt_elec | port_sewer | port_water | port_db
        self.drag = None
        self.sh = None

    # ---- view
    def bounds(self):
        r = self.page.res
        st = self.page.st
        pts = list(st["stand"]["corners"])
        for k in ("sewer", "water", "elec"):
            pts += r[k]["path"] if r else []
            pts.append(tuple(st["points"][k]))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        # the road, the street name and the dimension lines round the stand
        return min(xs) - 15, min(ys) - 10, max(xs) + 15, max(ys) + 4

    def sheet(self, W, H, s=None, centre=None, road=None):
        if s is None:
            s, cx, cy = self.current(W, H)
        else:
            cx, cy = centre
        return site_sheet.Sheet(s, (cx, cy), (W, H), road or self.page.st["sheet"].get("road", "left"))

    def fit(self):
        self.auto = True
        self.update()

    def current(self, W=None, H=None):
        W, H = W or self.width(), H or self.height()
        if self.auto or self.view is None:
            x0, y0, x1, y1 = self.bounds()
            rot = site_sheet.ROTS.get(self.page.st["sheet"].get("road", "left"), 270)
            w, h = (x1 - x0, y1 - y0) if rot in (0, 180) else (y1 - y0, x1 - x0)
            s = min((W - 30) / max(w, 1e-3), (H - 30) / max(h, 1e-3))
            self.view = (s, (x0 + x1) / 2, (y0 + y1) / 2)
        return self.view

    def zoom(self, f):
        if self.view is None:
            return
        self.auto = False
        s, cx, cy = self.view
        self.view = (min(max(s * f, 2), 400), cx, cy)
        self.update()

    def world(self, pt):
        return self.sh.inv(pt) if self.sh else (0, 0)

    # ---- drawing
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor("white"))
        self.sh = self.sheet(self.width(), self.height())
        self.view = (self.sh.s, self.sh.cx, self.sh.cy)
        self.draw(p, self.sh, interactive=True)

    def draw(self, p, sh, interactive=False):
        pg = self.page
        st, res = pg.st, pg.res
        if interactive and pg.show_under and pg.under:
            S = sh.pt
            for key, col in (("storm", QColor("#b7dcb7")), ("water", QColor("#c6defa")), ("sewer", QColor("#ecd0b6"))):
                for x1, y1, x2, y2, thick in pg.under.get(key, []):
                    p.setPen(QPen(col, 1.4 if thick else 0.7))
                    p.drawLine(S((x1, y1)), S((x2, y2)))
        site_sheet.draw(p, sh, st, res, pg.sheet_opts(), minpx=7 if interactive else 5)
        # north arrow above the plan, turned to the chosen direction
        r_px = max(sh.s * 1.5, 18)
        site_sheet.north_arrow(p, QPointF(sh.W * 0.5, r_px * 2.2 + 8) if interactive else QPointF(sh.W * 0.5, r_px * 2.6), r_px, st["sheet"].get("north", 0))
        if interactive and res:
            S = sh.pt
            for key, col in (("sewer", site_sheet.BROWN), ("water", site_sheet.BLUE), ("elec", site_sheet.YELLOW)):
                q = S(st["points"][key])
                p.setPen(QPen(QColor("black"), 1.2))
                p.setBrush(QBrush(col))
                p.drawEllipse(q, 6, 6)
            hp = res["house"]
            for pk, col in (("sewer", site_sheet.BROWN), ("water", site_sheet.BLUE), ("db", site_sheet.YELLOW)):
                pt, _n = se.port_point(hp, self.page.port_of(pk))
                q = S(pt)
                p.setPen(QPen(QColor("black"), 1.0))
                p.setBrush(QBrush(col))
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))
            if self.mode != "select":
                p.setPen(QColor("#d6209a"))
                p.setFont(QFont(self.font().family(), 9, QFont.Weight.Bold))
                p.drawText(QPointF(10, 18), {"pt_sewer": "Click where the main sewer connection is", "pt_water": "Click where the water connection is",
                                             "pt_elec": "Click where the electrical supply is", "port_sewer": "Click the house outline where the sewer leaves",
                                             "port_water": "Click the house outline where the water enters", "port_db": "Click the house outline where the DB is"}.get(self.mode, ""))

    # ---- mouse
    def mousePressEvent(self, e):
        if not self.sh:
            return
        w = self.world(e.position())
        pg = self.page
        if e.button() == Qt.MouseButton.LeftButton:
            if self.mode.startswith("pt_"):
                pg.set_point(self.mode[3:], w)
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
            if self.mode.startswith("port_"):
                pg.set_port(self.mode[5:], w)
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
            self.drag = self._hit(w, e.position())
            if self.drag is None:
                self.drag = ("pan", e.position(), self.view)
                self.auto = False
        elif e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.drag = ("pan", e.position(), self.view)
            self.auto = False

    def _hit(self, w, qp):
        pg = self.page
        s = self.view[0]
        for k in ("sewer", "water", "elec"):
            q = pg.st["points"][k]
            if math.hypot(q[0] - w[0], q[1] - w[1]) * s < 12:
                return ("pt", k)
        if pg.res:
            hp = pg.res["house"]
            for pk in ("sewer", "water", "db"):
                pt, _n = se.port_point(hp, pg.port_of(pk))
                if math.hypot(pt[0] - w[0], pt[1] - w[1]) * s < 10:
                    return ("port", pk)
            if pg.res["carport"] and se.inside(w, pg.res["carport"]):
                c = pg.st["carport"]
                return ("carport", w, (c["cx"], c["cy"]))
            if se.inside(w, hp):
                h = pg.st["house"]
                return ("house", w, (h["cx"], h["cy"]))
        return None

    def mouseMoveEvent(self, e):
        d = self.drag
        if not d or not self.sh:
            return
        pg = self.page
        if d[0] == "pan":
            s, cx, cy = d[2]
            dx, dy = e.position().x() - d[1].x(), e.position().y() - d[1].y()
            a = site_sheet.Sheet(s, (cx, cy), (self.width(), self.height()), pg.st["sheet"].get("road", "left"))
            p0 = a.inv(QPointF(self.width() / 2, self.height() / 2))
            p1 = a.inv(QPointF(self.width() / 2 - dx, self.height() / 2 - dy))
            self.view = (s, cx + p1[0] - p0[0], cy + p1[1] - p0[1])
            self.update()
            return
        w = self.world(e.position())
        if d[0] == "pt":
            pg.st["points"][d[1]] = [round(w[0], 2), round(w[1], 2)]
        elif d[0] == "port":
            hp = pg.res["house"]
            pg.st["ports"][d[1]] = se.nearest_port(hp, w)
        elif d[0] in ("house", "carport"):
            o = pg.st[d[0]]
            o["cx"] = round(d[2][0] + w[0] - d[1][0], 2)
            o["cy"] = round(d[2][1] + w[1] - d[1][1], 2)
        pg.schedule()
        self.update()

    def mouseReleaseEvent(self, _e):
        if self.drag and self.drag[0] != "pan":
            self.page.solve_now()
        self.drag = None

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)


# ------------------------------------------------------------------ the page
class SiteServicesPage(ToolBase):
    KEY = "services"
    TITLE = "Site services"
    STEP_NAMES = ["Stand and buildings", "Service points", "The lines"]
    STEP_HINTS = ["Pick the stand, set the house and the carport. Drag them in the plan, or press Suggest to place them inside the building lines.",
                  "Say where the main sewer, the water connection and the electrical supply are, and where on the house they enter. Drag the dots in the plan.",
                  "Lengths, eyes, invert depths and checks. Save the plan as a PDF or an image."]

    def __init__(self, win):
        super().__init__(win)
        self.st = blank_state()
        self.under = {}
        self.res = None
        self.show_under = True
        self._busy = False
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(140)
        self._t.timeout.connect(self.solve_now)
        self.view = ServicesView(self)
        # ---- step 1
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The stand", "Stands read from the Blue Hills SG sheets are built in. Or take the stand from the Building lines tool, or type a rectangle.")
        row = QHBoxLayout()
        self.stand_cb = QComboBox()
        self.stand_cb.addItem("Choose a stand...")
        for k in sorted(STANDS):
            self.stand_cb.addItem("Blue Hills Ext 120 - stand %s  (%.0f m2)" % (k, STANDS[k]["area"]), k)
        self.stand_cb.currentIndexChanged.connect(self._stand_picked)
        row.addWidget(self.stand_cb, 1)
        bv.addLayout(row)
        row = QHBoxLayout()
        self.q_w, self.q_d = spin(2, 500, 13.5, 2, " m"), spin(2, 500, 22, 2, " m")
        mk = QPushButton("Make a rectangle")
        mk.clicked.connect(self.make_rect)
        fb = QPushButton("Take the stand and buildings from Building lines")
        fb.clicked.connect(self.from_site_page)
        for w in (QLabel("Along the street"), self.q_w, QLabel("Depth"), self.q_d, mk):
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        bv.addWidget(fb)
        row = QHBoxLayout()
        self.sb_street, self.sb_side, self.sb_rear = spin(0, 20, 1.0, 2, " m"), spin(0, 20, 1.0, 2, " m"), spin(0, 20, 2.0, 2, " m")
        for lab, w in (("Building line: street", self.sb_street), ("side", self.sb_side), ("rear", self.sb_rear)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        self.stand_lbl = QLabel("")
        self.stand_lbl.setObjectName("xaSub")
        self.stand_lbl.setWordWrap(True)
        bv.addWidget(self.stand_lbl)
        v1.addWidget(bx)
        bx, bv = self.box("The sheet", "What goes on the plan beside the stand: the stand number, the street, which side the road is on, and where north is.")
        row = QHBoxLayout()
        self.sh_no, self.sh_street, self.sh_rw, self.sh_se = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.sh_no.setPlaceholderText("2155")
        self.sh_street.setPlaceholderText("BLUESTEM STREET")
        self.sh_rw.setPlaceholderText("13m")
        self.sh_se.setPlaceholderText("2246")
        for lab, w_, st_ in (("Stand no.", self.sh_no, 0), ("Street", self.sh_street, 2), ("Road", self.sh_rw, 0), ("Street erf", self.sh_se, 0)):
            row.addWidget(QLabel(lab))
            row.addWidget(w_, st_ or 1)
        bv.addLayout(row)
        row = QHBoxLayout()
        self.sh_road = QComboBox()
        for t_ in ("left", "right", "top", "bottom"):
            self.sh_road.addItem(t_)
        self.sh_north = spin(-360, 360, 0, 1, " deg", 5)
        row.addWidget(QLabel("The road is on the"))
        row.addWidget(self.sh_road)
        row.addWidget(QLabel("North arrow turned"))
        row.addWidget(self.sh_north)
        row.addStretch(1)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("The house", "The footprint, as the red box on your site plans. Rotation 90 puts the long side away from the street.")
        row = QHBoxLayout()
        self.h_w, self.h_d, self.h_rot = spin(1, 60, 14.8, 2, " m"), spin(1, 60, 6.5, 2, " m"), spin(-360, 360, 90, 0, " deg", 90)
        self.h_x, self.h_y = spin(-100, 500, 9, 2, " m"), spin(-100, 500, 12, 2, " m")
        for lab, w in (("Length", self.h_w), ("Width", self.h_d), ("Rotation", self.h_rot), ("Centre x", self.h_x), ("y", self.h_y)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("The carport", "")
        row = QHBoxLayout()
        self.c_on = QCheckBox("Carport")
        self.c_on.setChecked(True)
        self.c_w, self.c_d = spin(1, 30, 5, 2, " m"), spin(1, 30, 5, 2, " m")
        self.c_x, self.c_y = spin(-100, 500, 3.5, 2, " m"), spin(-100, 500, 3.5, 2, " m")
        row.addWidget(self.c_on)
        for lab, w in (("Width", self.c_w), ("Depth", self.c_d), ("Centre x", self.c_x), ("y", self.c_y)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        sg = QPushButton("Suggest placement inside the building lines")
        sg.setToolTip("Carport at the street on one side, house at the back. Where everything cannot fit, it places them and the checks show by how much.")
        sg.clicked.connect(self.suggest)
        bv.addWidget(sg)
        v1.addWidget(bx)
        v1.addStretch(1)
        # ---- step 2
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        self.pt_spin = {}
        for key, title, sub in (("sewer", "Main sewer connection", "Where your house sewer joins the main, from the SG sewer sheet. The sewer depth there sets the invert levels along the pipe."),
                                ("water", "Water connection (W.CON)", "Where the water line is brought to the stand."),
                                ("elec", "Electrical supply (EC)", "Not on the SG sheets: place it where the supply box or connection is.")):
            bx, bv = self.box(title, sub)
            row = QHBoxLayout()
            sx, sy = spin(-100, 500, 0, 2, " m"), spin(-100, 500, 0, 2, " m")
            self.pt_spin[key] = (sx, sy)
            pb = QPushButton("Click it in the plan")
            pb.clicked.connect(lambda _=False, k=key: self.arm("pt_" + k))
            ab = QPushButton("House side: click on the house")
            ab.clicked.connect(lambda _=False, k=key: self.arm("port_" + ("db" if k == "elec" else k)))
            rb = QPushButton("Automatic")
            rb.clicked.connect(lambda _=False, k=key: self.reset_port("db" if k == "elec" else k))
            for lab, w in (("x", sx), ("y", sy)):
                row.addWidget(QLabel(lab))
                row.addWidget(w)
            row.addWidget(pb)
            bv.addLayout(row)
            row = QHBoxLayout()
            row.addWidget(ab)
            row.addWidget(rb)
            row.addStretch(1)
            bv.addLayout(row)
            if key == "sewer":
                row = QHBoxLayout()
                self.p_depth, self.p_fall, self.p_ie = spin(0.3, 6, 1.5, 2, " m"), spin(20, 200, 50, 0, "", 5), spin(5, 60, 25, 0, " m", 1)
                self.p_pipe = QComboBox()
                self.p_pipe.addItems(["110", "160"])
                for lab, w in (("Depth at the main", self.p_depth), ("Fall 1 :", self.p_fall), ("Eyes at most", self.p_ie), ("Pipe", self.p_pipe)):
                    row.addWidget(QLabel(lab))
                    row.addWidget(w)
                row.addStretch(1)
                bv.addLayout(row)
            v2.addWidget(bx)
        v2.addStretch(1)
        # ---- step 3
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Checks", "")
        self.warn_lbl = QLabel("")
        self.warn_lbl.setWordWrap(True)
        bv.addWidget(self.warn_lbl)
        v3.addWidget(bx)
        bx, bv = self.box("The lines", "")
        self.svc_t = QTableWidget(0, 3)
        self.svc_t.setHorizontalHeaderLabels(["Service", "Length", "Note"])
        self.svc_t.verticalHeader().setVisible(False)
        self.svc_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.svc_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.svc_t.setMinimumHeight(120)
        bv.addWidget(self.svc_t)
        v3.addWidget(bx)
        bx, bv = self.box("Eyes and invert depths along the sewer", "Depth is below ground, measured at the pipe invert, from the depth at the main and the fall.")
        self.node_t = QTableWidget(0, 4)
        self.node_t.setHorizontalHeaderLabels(["Node", "Distance from the house", "Depth (mm)", "Where"])
        self.node_t.verticalHeader().setVisible(False)
        self.node_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.node_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.node_t.setMinimumHeight(180)
        bv.addWidget(self.node_t)
        v3.addWidget(bx)
        bx, bv = self.box("Save", "")
        row = QHBoxLayout()
        for text, fn in (("Save the plan as PDF...", self.save_pdf), ("Save as an image...", self.save_png), ("Save the setup...", self.save_json), ("Open a setup...", self.open_json)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        v3.addWidget(bx)
        v3.addStretch(1)
        self.build_frame([p1, p2, p3], side=self._panel())
        for w in (self.sb_street, self.sb_side, self.sb_rear, self.h_w, self.h_d, self.h_rot, self.h_x, self.h_y, self.c_w, self.c_d, self.c_x, self.c_y,
                  self.p_depth, self.p_fall, self.p_ie):
            w.valueChanged.connect(self._edited)
        self.c_on.toggled.connect(self._edited)
        for w_ in (self.sh_no, self.sh_street, self.sh_rw, self.sh_se):
            w_.textChanged.connect(self._edited)
        self.sh_road.currentIndexChanged.connect(self._edited)
        self.sh_north.valueChanged.connect(self._edited)
        self.p_pipe.currentIndexChanged.connect(self._edited)
        for sx, sy in self.pt_spin.values():
            sx.valueChanged.connect(self._edited)
            sy.valueChanged.connect(self._edited)
        self.solve_now()
        self.restore()

    # ---- frame bits
    def _panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QWidget()
        fl = FlowLayout(bar, 4, 4)
        for text, fn in (("Fit", self.view.fit), ("Zoom in", lambda: self.view.zoom(1.3)), ("Zoom out", lambda: self.view.zoom(1 / 1.3))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        self.under_cb = QCheckBox("Engineer's lines")
        self.under_cb.setChecked(True)
        self.under_cb.setToolTip("The sewer, water and stormwater lines from the SG sheets, faint, under the plan.")
        self.under_cb.toggled.connect(lambda on: (setattr(self, "show_under", on), self.view.update()))
        fl.addWidget(self.under_cb)
        bar.setMinimumHeight(40)
        v.addWidget(bar)
        self.hint_lbl = QLabel("")
        self.hint_lbl.setStyleSheet("color:#d6209a; font-weight:600;")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setVisible(False)
        v.addWidget(self.hint_lbl)
        v.addWidget(self.view, 1)
        return panel

    def set_hint(self, t):
        self.hint_lbl.setText(t)
        self.hint_lbl.setVisible(bool(t))

    def sheet_opts(self):
        sh = dict(self.st.get("sheet") or {})
        try:
            no = int(sh.get("stand_no", ""))
            sh["neigh"] = [no - 1, no + 1]
        except ValueError:
            sh["neigh"] = []
        return sh

    def params(self):
        return dict(se.DEFAULTS, **(self.st.get("params") or {}))

    # ---- reading the fields into the state
    def _edited(self, *_a):
        if self._busy:
            return
        st = self.st
        st["stand"]["setbacks"] = {"street": self.sb_street.value(), "side": self.sb_side.value(), "rear": self.sb_rear.value()}
        st["house"].update({"w": self.h_w.value(), "d": self.h_d.value(), "rot": self.h_rot.value(), "cx": self.h_x.value(), "cy": self.h_y.value()})
        if self.c_on.isChecked():
            st["carport"] = {"w": self.c_w.value(), "d": self.c_d.value(), "cx": self.c_x.value(), "cy": self.c_y.value(), "rot": (st.get("carport") or {}).get("rot", 0)}
        else:
            st["carport"] = None
        for k, (sx, sy) in self.pt_spin.items():
            st["points"][k] = [sx.value(), sy.value()]
        st["sheet"] = {"road": self.sh_road.currentText(), "street": self.sh_street.text().strip(), "road_w": self.sh_rw.text().strip(), "street_erf": self.sh_se.text().strip(),
                       "stand_no": self.sh_no.text().strip(), "north": self.sh_north.value()}
        if self.view.auto is False and False:
            pass
        st["params"] = {"conn_depth": self.p_depth.value(), "fall": self.p_fall.value(), "max_ie": self.p_ie.value(), "sewer_pipe": self.p_pipe.currentText(),
                        "sb_street": self.sb_street.value(), "sb_side": self.sb_side.value(), "sb_rear": self.sb_rear.value()}
        self.schedule()

    def _to_fields(self):
        self._busy = True
        try:
            st = self.st
            sb = st["stand"].get("setbacks") or {}
            for w, k in ((self.sb_street, "street"), (self.sb_side, "side"), (self.sb_rear, "rear")):
                w.setValue(sb.get(k, w.value()))
            h = st["house"]
            for w, k in ((self.h_w, "w"), (self.h_d, "d"), (self.h_rot, "rot"), (self.h_x, "cx"), (self.h_y, "cy")):
                w.setValue(h.get(k, 0))
            c = st.get("carport")
            self.c_on.setChecked(bool(c))
            if c:
                for w, k in ((self.c_w, "w"), (self.c_d, "d"), (self.c_x, "cx"), (self.c_y, "cy")):
                    w.setValue(c.get(k, 0))
            for k, (sx, sy) in self.pt_spin.items():
                sx.setValue(st["points"][k][0])
                sy.setValue(st["points"][k][1])
            sh = st.get("sheet") or {}
            self.sh_no.setText(str(sh.get("stand_no", "")))
            self.sh_street.setText(str(sh.get("street", "")))
            self.sh_rw.setText(str(sh.get("road_w", "13m")))
            self.sh_se.setText(str(sh.get("street_erf", "")))
            self.sh_road.setCurrentText(str(sh.get("road", "left")))
            self.sh_north.setValue(float(sh.get("north", 0)))
            pr = st.get("params") or {}
            self.p_depth.setValue(pr.get("conn_depth", 1.5))
            self.p_fall.setValue(pr.get("fall", 50))
            self.p_ie.setValue(pr.get("max_ie", 25))
            self.p_pipe.setCurrentText(str(pr.get("sewer_pipe", "110")))
        finally:
            self._busy = False

    # ---- solving
    def schedule(self):
        self._t.start()

    def solve_now(self):
        self._t.stop()
        try:
            self.res = se.solve(self.st)
        except Exception as e:                                  # a bad input must never take the tool down
            self.res = None
            self.warn_lbl.setText("Could not work out the lines: %s" % e)
            return
        self.fill_results()
        self.view.update()
        self.changed()

    def port_of(self, pk):
        st = self.st
        hp = self.res["house"] if self.res else se.house_poly(st["house"])
        p = (st.get("ports") or {}).get(pk)
        if p:
            return p
        tgt = st["points"]["sewer" if pk == "sewer" else "water" if pk == "water" else "elec"]
        return se.auto_port(hp, tgt, {"sewer": 0.25, "water": 0.7, "db": 0.8}[pk])

    def fill_results(self):
        r = self.res
        w = list(r["warnings"])
        self.warn_lbl.setText("<br>".join("&#9888; " + x for x in w) if w else "&#10003; Inside the building lines. Sewer depth is fine.")
        self.warn_lbl.setStyleSheet("color:#b3261e;" if w else "color:#1a7f37;")
        self.stand_lbl.setText("Stand %.0f m2.  Coverage (house + carport) %.1f%%." % (r["stand_area"], r["coverage_pct"]))
        rows = [("Sewer", "%.1f m" % r["sewer"]["length"], "%s, drop %d mm, %d eyes" % (r["sewer"]["note"], r["sewer"]["drop_mm"], sum(1 for n in r["sewer"]["nodes"] if n["kind"] in ("IE", "RE")))),
                ("Water", "%.1f m" % r["water"]["length"], r["water"]["note"]), ("Electrical", "%.1f m" % r["elec"]["length"], r["elec"]["note"])]
        self.svc_t.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, t in enumerate(row):
                self.svc_t.setItem(i, j, QTableWidgetItem(t))
        nodes = r["sewer"]["nodes"]
        self.node_t.setRowCount(len(nodes))
        for i, n in enumerate(nodes):
            vals = (n["kind"], "%.1f m" % n["chainage"], "%d" % round(n["depth"] * 1000), n["label"] if n["kind"] in ("RE", "MAIN") else "")
            for j, t in enumerate(vals):
                self.node_t.setItem(i, j, QTableWidgetItem(t))
        self._busy = True
        try:
            for k, (sx, sy) in self.pt_spin.items():
                sx.setValue(self.st["points"][k][0])
                sy.setValue(self.st["points"][k][1])
            h = self.st["house"]
            self.h_x.setValue(h["cx"])
            self.h_y.setValue(h["cy"])
            c = self.st.get("carport")
            if c:
                self.c_x.setValue(c["cx"])
                self.c_y.setValue(c["cy"])
        finally:
            self._busy = False

    # ---- actions
    def arm(self, mode):
        self.view.mode = mode
        self.set_hint({"pt_sewer": "Click in the plan where the main sewer connection is.", "pt_water": "Click in the plan where the water connection is.",
                       "pt_elec": "Click in the plan where the electrical supply is.", "port_sewer": "Click on the house outline where the sewer leaves the house.",
                       "port_water": "Click on the house outline where the water enters.", "port_db": "Click on the house outline where the DB is."}.get(mode, ""))
        self.view.update()

    def set_point(self, k, w):
        self.st["points"][k] = [round(w[0], 2), round(w[1], 2)]
        self.solve_now()

    def set_port(self, pk, w):
        self.st["ports"][pk] = se.nearest_port(self.res["house"], w)
        self.solve_now()

    def reset_port(self, pk):
        self.st["ports"].pop(pk, None)
        self.solve_now()

    def set_stand(self, corners, name="Stand", under=None, points=None, keep_buildings=False):
        c = se.clean_corners(corners)
        self.st["stand"]["corners"] = [[round(a, 2), round(b, 2)] for a, b in c]
        self.st["stand"]["name"] = name
        self.under = under or {}
        if points:
            self.st["points"] = points
        self.st["ports"] = {}
        self._to_fields()                                  # the fields must show the new stand before anything reads them back
        if not keep_buildings:
            self.suggest()
        else:
            self.solve_now()
        self.view.fit()

    def _stand_picked(self, i):
        k = self.stand_cb.itemData(i)
        if not k:
            return
        d = STANDS[k]
        road, street, north = SHEET_DEFAULTS.get(k, ("left", "", 0.0))
        self.st["sheet"] = {"road": road, "street": street, "road_w": "13m", "street_erf": "2246", "stand_no": k, "north": north}
        self.set_stand(d["corners"], "Blue Hills Ext 120 - stand " + k, under=d["layers"], points=se.default_points(d))

    def make_rect(self):
        w, d = self.q_w.value(), self.q_d.value()
        self.set_stand([[0, 0], [w, 0], [w, d], [0, d]], "Rectangle", points={"sewer": [round(w * 0.85, 2), 0.0], "water": [1.5, 0.0], "elec": [round(w / 2, 2), 0.0]})

    def suggest(self):
        self._edited()
        out = se.suggest(self.st)
        self.st["house"].update(out["house"])
        self.st["carport"] = out.get("carport")
        self._to_fields()
        self.solve_now()
        if out.get("relaxed"):
            self.set_hint("The buildings do not fit inside all the building lines on this stand. They are placed as tightly as they go; the checks show by how much.")
            QTimer.singleShot(6000, lambda: self.set_hint(""))

    def from_site_page(self):
        sp = getattr(self.win, "site_page", None)
        if sp is None:
            QMessageBox.information(self, "Site services", "The Building lines tool is not available.")
            return
        v = sp.verts()
        if len(v) < 3:
            QMessageBox.information(self, "Site services", "Draw the stand in the Building lines tool first.")
            return
        ed = sp.edges()
        si = next((i for i, e in enumerate(ed) if e["kind"] == "Street"), None)
        if si is None:
            si = min(range(len(v)), key=lambda i: (v[i][1] + v[(i + 1) % len(v)][1]) / 2)
        a, b = v[si], v[(si + 1) % len(v)]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        ex = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        ey = (-ex[1], ex[0])
        cen = (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v))
        if (cen[0] - a[0]) * ey[0] + (cen[1] - a[1]) * ey[1] < 0:
            ey = (-ey[0], -ey[1])

        def loc(p):
            return ((p[0] - a[0]) * ex[0] + (p[1] - a[1]) * ex[1], (p[0] - a[0]) * ey[0] + (p[1] - a[1]) * ey[1])
        pts = [loc(p) for p in v[si:] + v[:si]]
        if se.area(pts) < 0:
            pts = [pts[0]] + pts[1:][::-1]
        sbs = {}
        for e in ed:
            sbs.setdefault({"Street": "street", "Side": "side", "Rear": "rear"}.get(e["kind"], "side"), e["sb"])
        self.st["stand"]["setbacks"] = {k: sbs.get(k, 1.0) for k in ("street", "side", "rear")}
        bl = sp.buildings()
        got = []
        for b_ in bl[:2]:
            poly = b_["poly"] or [(b_["x"], b_["y"]), (b_["x"] + b_["w"], b_["y"]), (b_["x"] + b_["w"], b_["y"] + b_["d"]), (b_["x"], b_["y"] + b_["d"])]
            lp = [loc(q) for q in poly]
            cx, cy = sum(q[0] for q in lp) / len(lp), sum(q[1] for q in lp) / len(lp)
            e0 = (lp[1][0] - lp[0][0], lp[1][1] - lp[0][1])
            e1 = (lp[2][0] - lp[1][0], lp[2][1] - lp[1][1])
            got.append({"cx": round(cx, 2), "cy": round(cy, 2), "w": round(math.hypot(*e0), 2), "d": round(math.hypot(*e1), 2), "rot": round(math.degrees(math.atan2(e0[1], e0[0])), 1)})
        self.stand_cb.setCurrentIndex(0)
        if got:
            self.st["house"] = got[0]
            self.st["carport"] = got[1] if len(got) > 1 else None
        self.set_stand(pts, "From Building lines", keep_buildings=bool(got), points={"sewer": [round(L * 0.85, 2), 0.0], "water": [1.5, 0.0], "elec": [round(L / 2, 2), 0.0]})
        self._to_fields()
        self.solve_now()

    # ---- save and load
    def state(self):
        return json.loads(json.dumps(self.st))

    def set_state(self, d):
        if not d or "stand" not in d:
            return
        base = blank_state()
        base.update(d)
        self.st = base
        k = str(self.st["stand"].get("name", "")).split()[-1]
        self.under = STANDS[k]["layers"] if k in STANDS and "Blue Hills" in str(self.st["stand"].get("name")) else {}
        self._to_fields()
        self.solve_now()

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the setup", "site_services.json", "Setup (*.json)")
        if path:
            json.dump(self.state(), open(path, "w"), indent=1)

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a setup", "", "Setup (*.json)")
        if path:
            self.set_state(json.load(open(path)))
            self.view.fit()

    def _render(self, p, W, H, dpi=300):
        """the sheet: the plan at 1:200 on the paper if it fits (it nearly always does on A3), the title and the notes in the corner"""
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(0, 0, W, H, QColor("white"))
        x0, y0, x1, y1 = self.view.bounds()
        road = self.st["sheet"].get("road", "left")
        rot = site_sheet.ROTS.get(road, 270)
        w_m, h_m = (x1 - x0, y1 - y0) if rot in (0, 180) else (y1 - y0, x1 - x0)
        s200 = 5.0 * dpi / 25.4                                  # pixels per metre at 1:200
        fit = min(W * 0.92 / w_m, H * 0.80 / h_m)
        s = min(s200, fit)
        scale_txt = "1:200" if s >= s200 - 1e-6 else "1:%d" % round(200 * s200 / s / 10) * 1 if False else ("1:200" if s >= s200 - 1e-6 else "1:%d" % int(round(200 * s200 / s / 50.0) * 50))
        sh = site_sheet.Sheet(s, ((x0 + x1) / 2, (y0 + y1) / 2), (W, H * 0.92), road)
        p.save()
        site_sheet.draw(p, sh, self.st, self.res, self.sheet_opts(), minpx=5)
        r_px = max(s * 1.5, 18)
        site_sheet.north_arrow(p, QPointF(W * 0.5, r_px * 2.6), r_px, self.st["sheet"].get("north", 0))
        p.restore()
        name = self.st["sheet"].get("stand_no") or self.st["stand"].get("name", "Stand")
        base = H * 0.945
        p.setPen(QColor("black"))
        p.setFont(site_sheet.font(s * 0.62, True, 100))
        p.drawText(QPointF(W * 0.04, base), "Site Plan")
        p.setFont(site_sheet.font(s * 0.62, False, 100))
        p.drawText(QPointF(W * 0.04, base + s * 0.9), scale_txt)
        p.setPen(site_sheet.RED)
        p.setFont(site_sheet.font(s * 0.8, True, 100))
        p.drawText(QPointF(W * 0.20, base + s * 0.9), "To Scale if printed to A3" if scale_txt == "1:200" else "Not to scale")
        r = self.res
        p.setPen(QColor("black"))
        p.setFont(site_sheet.font(s * 0.5, False, 100))
        lines = ["Stand %s   %.0f m2   coverage %.1f%%" % (name, r["stand_area"], r["coverage_pct"]),
                 "Sewer %s, %.1f m, depth at the house %d mm.   Water %.1f m.   Electrical %.1f m." % (r["sewer"]["note"], r["sewer"]["length"], round(r["sewer"]["depth_house"] * 1000), r["water"]["length"], r["elec"]["length"])]
        for i, t in enumerate(lines):
            p.drawText(QPointF(W * 0.55, base + i * s * 0.9), t)

    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the plan", "site_services.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.write_pdf(path)

    def write_pdf(self, path):
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
        w.setPageOrientation(QPageLayout.Orientation.Landscape)
        w.setResolution(300)
        p = QPainter(w)
        self._render(p, w.width(), w.height(), 300)
        p.end()

    def save_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the plan", "site_services.png", "Image (*.png)")
        if path:
            self.write_png(path)

    def write_png(self, path, W=4960, H=3508):
        img = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(img)
        self._render(p, W, H, 300)
        p.end()
        img.save(path)
