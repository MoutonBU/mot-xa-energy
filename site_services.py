"""Site services: give it the stand, the house footprint and the carport, say where the sewer connection, the water connection and the
electrical supply are, and it draws the sewer, water and electrical lines to the house, with rodding eyes, inspection eyes, the meter,
the DB, the fall and the invert depths. Move anything and everything redraws. Stands from the Blue Hills SG sheets are built in."""
import copy
import json
import math

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, QSizeF
from PySide6.QtGui import QKeySequence, QShortcut, QBrush, QColor, QFont, QPainter, QPen, QPolygonF, QPageSize, QPageLayout, QPdfWriter, QImage
from PySide6.QtWidgets import (QApplication, QFrame, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QInputDialog, QListWidget, QMenu, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

import site_dxf
import site_dxf_dialog
import site_township
import site_plans_data
try:
    from site_footprints_data import FOOTPRINTS
except Exception:
    FOOTPRINTS = []
import site_engine as se
from rotate_dialog import RotateDialog
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
            "ports": {}, "params": {}, "mains": {}, "custom": [], "frame": None, "labels": {}, "underlay": [], "underlay_cat": {}, "neighbours": [], "sewer_via": [], "water_ports": [], "dims": [], "sewer_manual": [], "main_line": [], "manholes": [], "look": {}, "notes": [], "text_edit": {}, "text_hidden": [], "pts_manual": False,
            "sheet": {"road": "left", "street": "", "road_w": "13m", "street_erf": "", "stand_no": "", "north": 0.0}}


# what the finished plans say for the built-in stands: the side the road is on, the street, the north arrow
SHEET_DEFAULTS = {"2068": ("right", "THIMBLE STREET", -8.7), "2091": ("right", "CATSTAIL STREET", -8.7), "2093": ("right", "CATSTAIL STREET", -6.5),
                  "2144": ("left", "CATSTAIL STREET", -8.7), "2155": ("left", "BLUESTEM STREET", -8.7)}


class _FootprintPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.f = None
        self.setMinimumSize(300, 260)

    def show_fp(self, f):
        self.f = f
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        if not self.f:
            return
        pl = self.f["poly"]
        w, h = max(self.f["w"], 1), max(self.f["d"], 1)
        s = min((self.width() - 30) / w, (self.height() - 30) / h)
        C = lambda q: QPointF(self.width() / 2 + q[0] * s, self.height() / 2 - q[1] * s)
        p.setPen(QPen(QColor("black"), 1.5))
        p.setBrush(QBrush(QColor(255, 0, 0, 120)))
        p.drawPolygon(QPolygonF([C(q) for q in pl]))
        p.setPen(QColor("#1a7f37"))
        for m in self.f["marks"]:
            p.drawText(C((m[1], m[2])), m[0])


# ------------------------------------------------------------------ the plan
class ServicesView(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.view = None                       # (px per m, world x at the centre, world y at the centre)
        self.auto = True
        self._mode = "select"                  # select | pt_sewer | pt_water | pt_elec | port_sewer | port_water | port_db
        self.drag = None
        self.sel = None
        self.sh = None
        self.rclick = None
        self.lite = False
        self._full = QTimer(self)
        self._full.setSingleShot(True)
        self._full.setInterval(160)
        self._full.timeout.connect(self._go_full)

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, v):
        self._mode = v
        sync = getattr(self.page, "sync_done", None)
        if sync:
            sync()

    def finish_mode(self):
        """leave whatever you were adding or picking (Done button, Esc, right-click > Done)"""
        if self._mode == "sewer_draw":
            self.page.sewer_draw_finish()
        if self._mode == "mline_add":
            self.page._ml_on = False
            self.page.commit(True)
        if self._mode in ("wmain_add", "emain_add"):
            self.page._mn_on = {}
            self.page.solve_now(False)
            self.page.commit(True)
        if self._mode != "select":
            self._mode = "select"
            self.page._dim_a = None
            self.page._wr_a = None
            self.page.set_hint("")
            self.page.sync_done()
            self.update()

    def _go_lite(self):
        """while you drag, pan or zoom the plan is drawn simply (no text, no engineer lines); it is drawn in full a moment after you stop"""
        self.lite = True
        self._full.start()

    def _go_full(self):
        if self.drag is not None:
            self._full.start()
            return
        self.lite = False
        self.update()

    # ---- view
    def bounds(self):
        r = self.page.res
        st = self.page.st
        pts = list(st["stand"]["corners"])
        for k in ("sewer", "water", "elec"):
            pts += r[k]["path"] if r else []
            pts.append(tuple(st["points"][k]))
        cs = st["stand"]["corners"]
        cen = (sum(p[0] for p in cs) / len(cs), sum(p[1] for p in cs) / len(cs))
        for nb in st.get("neighbours") or []:                         # a township stand: the stands beside it come into view too
            c = nb.get("c")
            if c and math.hypot(c[0] - cen[0], c[1] - cen[1]) < 24:
                pts += [(c[0] - 7, c[1] - 11), (c[0] + 7, c[1] + 11)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        # the road, the street name and the dimension lines round the stand; a township stand shows the road round it (the bend and the far kerb)
        if st.get("road_lines"):
            return min(xs) - 32, min(ys) - 32, max(xs) + 32, max(ys) + 26
        return min(xs) - 15, min(ys) - 10, max(xs) + 15, max(ys) + 4

    def sheet(self, W, H, s=None, centre=None, road=None):
        if s is None:
            s, cx, cy = self.current(W, H)
        else:
            cx, cy = centre
        return site_sheet.Sheet(s, (cx, cy), (W, H), road or self.page.st["sheet"].get("road", "left"), self.page.st["sheet"].get("turn", 0.0))

    def fit(self):
        self.auto = True
        self.update()

    def current(self, W=None, H=None):
        W, H = W or self.width(), H or self.height()
        if self.auto or self.view is None:
            x0, y0, x1, y1 = self.bounds()
            w, h = site_sheet.page_extent(x0, y0, x1, y1, self.page.st["sheet"].get("road", "left"), self.page.st["sheet"].get("turn", 0.0))
            s = min((W - 30) / max(w, 1e-3), (H - 30) / max(h, 1e-3))
            self.view = (s, (x0 + x1) / 2, (y0 + y1) / 2)
        return self.view

    def zoom(self, f):
        if self.view is None:
            return
        self.auto = False
        s, cx, cy = self.view
        self.view = (min(max(s * f, 2), 400), cx, cy)
        self._go_lite()
        self.update()

    def world(self, pt):
        return self.sh.inv(pt) if self.sh else (0, 0)

    # ---- drawing
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, not self.lite)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor("white"))
        self.sh = self.sheet(self.width(), self.height())
        self.view = (self.sh.s, self.sh.cx, self.sh.cy)
        self.draw(p, self.sh, interactive=True)
        if not self.lite:
            self.draw_gizmo(p)

    def draw(self, p, sh, interactive=False):
        pg = self.page
        st, res = pg.st, pg.res
        if interactive and pg.show_under and pg.under and not self.lite:
            S = sh.pt
            for key, col in (("other", QColor("#cfd6e4")), ("storm", QColor("#b7dcb7")), ("water", QColor("#c6defa")), ("sewer", QColor("#ecd0b6")), ("elec", QColor("#efdc9a"))):
                for x1, y1, x2, y2, thick in pg.under.get(key, []):
                    p.setPen(QPen(col, 1.4 if thick else 0.7))
                    p.drawLine(S((x1, y1)), S((x2, y2)))
        site_sheet.draw(p, sh, st, res, pg.sheet_opts(), minpx=7 if interactive else 5, lite=interactive and self.lite)
        # north arrow above the plan, turned to the chosen direction
        r_px = max(sh.s * 1.5, 18)
        site_sheet.north_arrow(p, pg.north_centre(sh.W, sh.H, r_px, interactive), r_px, st["sheet"].get("north", 0))
        if interactive and res:
            S = sh.pt
            dr_ = self.drag
            if dr_ and dr_[0] == "fh" and len(dr_[1]) > 1:
                p.setPen(QPen(QColor("#d6209a"), 2))
                for q1_, q2_ in zip(dr_[1][:-1], dr_[1][1:]):
                    p.drawLine(S(q1_), S(q2_))
            for c in st.get("sewer_via") or []:
                q = S(c)
                p.setPen(QPen(site_sheet.BROWN, 2))
                p.setBrush(QBrush(QColor("white")))
                p.drawRect(QRectF(q.x() - 6, q.y() - 6, 12, 12))
            for c in st.get("custom") or []:
                q = S(c["pt"])
                col = {"sewer": site_sheet.BROWN, "water": site_sheet.BLUE, "elec": site_sheet.YELLOW}.get(c["kind"], QColor("#888888"))
                p.setPen(QPen(QColor("black"), 1.2))
                p.setBrush(QBrush(col))
                p.drawPolygon(QPolygonF([QPointF(q.x(), q.y() - 7), QPointF(q.x() + 7, q.y()), QPointF(q.x(), q.y() + 7), QPointF(q.x() - 7, q.y())]))
                p.setPen(QColor("black"))
                p.setFont(QFont(self.font().family(), 8))
                p.drawText(QPointF(q.x() + 9, q.y() - 8), c.get("name", ""))
            for key, col in (("sewer", site_sheet.BROWN), ("water", site_sheet.BLUE), ("elec", site_sheet.YELLOW)):
                q = S(se.conn_point(st, key))
                p.setPen(QPen(QColor("black"), 1.2))
                p.setBrush(QBrush(col))
                p.drawEllipse(q, 6, 6)
            if res.get("carport"):                                      # the point where the entry meets the kerb: drag it to move the entry
                ek_ = S(site_sheet.entry_shape(st, res["carport"])["k"])
                p.setPen(QPen(QColor("#d6209a"), 1.5))
                p.setBrush(QBrush(QColor("white")))
                p.drawEllipse(ek_, 6, 6)
            for mh_ in st.get("manholes") or []:                      # a ring round each manhole: drag it along the main
                q = S(mh_["pt"])
                p.setPen(QPen(QColor("#d6209a"), 1.2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(q, 11, 11)
            if (st.get("look") or {}).get("storm", True):                # the stormwater arrow: drag its line to move it, its head to turn it
                sp_, sr_ = site_sheet.storm_pose(st, res)
                if sp_:
                    hd_ = S(site_sheet.storm_head(sp_, sr_))
                    p.setPen(QPen(QColor("#d6209a"), 1.5))
                    p.setBrush(QBrush(QColor("white")))
                    p.drawEllipse(hd_, 6, 6)
            hp = res["house"]
            for wp in st.get("sewer_ports") or []:
                q = S(se.port_point(hp, wp)[0])
                p.setPen(QPen(QColor("black"), 1.0))
                p.setBrush(QBrush(site_sheet.BROWN))
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))
            for wp in st.get("water_ports") or []:
                q = S(se.port_point(hp, wp)[0])
                p.setPen(QPen(QColor("black"), 1.0))
                p.setBrush(QBrush(site_sheet.BLUE))
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))
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
        if e.button() == Qt.MouseButton.LeftButton and (e.modifiers() & Qt.KeyboardModifier.AltModifier):       # Alt + drag: turn the plan about its middle
            c_ = QPointF(self.width() / 2, self.height() / 2)
            self.drag = ("turn", math.atan2(e.position().y() - c_.y(), e.position().x() - c_.x()), pg.st["sheet"].get("turn", 0.0) or 0.0)
            self.auto = False
            self._go_lite()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            if self.mode == "street":
                pg.set_street_edge(w)
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
            if self.mode == "road":
                pg.set_road_from_click(e.position())
                self.mode = "north_dir"
                pg.set_hint("Now click the direction north points. You can also drag the arrow to move it.")
                self.update()
                return
            if self.mode == "north_dir":
                pg.set_north_from_click(e.position())
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
            if self.mode == "text_add":
                pg.add_note(w)
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
            if self.mode == "dim_add":
                pg.add_dim_point(w)
                return
            if self.mode == "wport_add":
                pg.add_wport(w)
                return
            if self.mode == "sport_add":
                pg.add_sport(w)
                return
            if self.mode == "sewer_draw":
                if getattr(pg, "_sd_on", False) and getattr(pg, "_sd_mode", "sq") == "fh":      # freeform: hold and draw
                    self.drag = ("fh", [w])
                    return
                pg.sewer_draw_click(w, bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                self.update()
                return
            if self.mode == "wall_run":
                pg.wall_run_click(w)
                return
            if self.mode == "wall_pick":
                i_ = pg.wall_edge_at(w)
                if i_ is not None:
                    pg.toggle_wall(i_)
                return
            if self.mode == "mline_add":
                pg.add_mline(w)
                return
            if self.mode in ("wmain_add", "emain_add"):
                pg.add_main("water" if self.mode == "wmain_add" else "elec", w)
                return
            if self.mode == "mh_add":
                pg.add_manhole(w)
                return
            if self.mode == "via_add":
                pg.add_via(w)
                return                                          # stays armed so you can click several points; press Esc or pick another tool to stop
            if self.mode == "cust_add":
                pg.add_custom(w)
                self.mode = "select"
                pg.set_hint("")
                self.update()
                return
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
            r_ = max(self.sh.s * 1.5, 18)
            nc = pg.north_centre(self.width(), self.height(), r_)
            if math.hypot(e.position().x() - nc.x(), e.position().y() - nc.y()) < r_ * 1.4:
                self.drag = ("north",)
                return
            self.drag = self._hit(w, e.position())
            self.sv_last = self.drag[1] if (self.drag and self.drag[0] == "sv") else None
            self.set_sel(self._sel_for(self.drag))
            if self.drag is not None and self.drag[0] != "label":
                self._go_lite()
            if self.drag is None:
                self.drag = ("pan", e.position(), self.view)
                self.auto = False
                self._go_lite()
        elif e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.rclick = (e.position(), w) if e.button() == Qt.MouseButton.RightButton else None
            self.drag = ("pan", e.position(), self.view)
            self.auto = False
            self._go_lite()

    def set_sel(self, sel):
        if sel != self.sel:
            self.sel = sel
            self.page.refresh_gizmo()
            self.update()

    def _sel_for(self, d):
        if d is None:
            return None
        if d[0] in ("house", "carport"):
            return (d[0],)
        if d[0] in ("sseg", "sv"):
            return ("sewer",)
        if d[0] == "eye":
            return ("eye", d[1])
        if d[0] == "sport":
            return ("sport", d[1])
        if d[0] == "pt":
            return ("point", d[1])
        if d[0] == "rot":
            return (d[1],)
        if d[0] == "label":
            return ("label", d[1])
        if d[0] == "dimend":
            return ("label", "DIM:u%d" % d[1])
        return None

    def rot_handle(self, role):
        o = self.page.st.get(role)
        if not o or not self.page.res or not self.page.res.get(role):
            return None
        c = (o["cx"], o["cy"])
        pl = self.page.res[role]
        R = max(math.hypot(q[0] - c[0], q[1] - c[1]) for q in pl) + 1.6
        a = math.radians(o.get("rot", 0.0))
        return c, R, (c[0] + R * math.cos(a), c[1] + R * math.sin(a))

    def _hit(self, w, qp):
        pg = self.page
        s = self.view[0]
        if self.sel and self.sel[0] in ("house", "carport"):
            hnd = self.rot_handle(self.sel[0])
            if hnd and math.hypot(hnd[2][0] - w[0], hnd[2][1] - w[1]) * s < 12:
                return ("rot", self.sel[0], hnd[0], pg.st[self.sel[0]].get("rot", 0.0), math.atan2(w[1] - hnd[0][1], w[0] - hnd[0][0]))
        if self.sel and self.sel[0] == "label" and self.sel[1].startswith("DIM:u"):
            try:
                k = int(self.sel[1][5:].split("#")[0])
                dm = pg.st["dims"][k]
                for which in ("a", "b"):
                    if math.hypot(dm[which][0] - w[0], dm[which][1] - w[1]) * s < 12:
                        return ("dimend", k, which)
            except Exception:
                pass
        if self.sel and self.sel[0] == "sewer" and pg.res:
            P = pg.res["sewer"]["path"]
            for k in range(1, len(P)):
                if math.hypot(P[k][0] - w[0], P[k][1] - w[1]) * s < 12:
                    return ("sv", k, [tuple(p) for p in P])
        for k in ("sewer", "water", "elec"):
            q = se.conn_point(pg.st, k)
            if math.hypot(q[0] - w[0], q[1] - w[1]) * s < 14:
                return ("pt", k)
        for i, mh_ in enumerate(pg.st.get("manholes") or []):
            if math.hypot(mh_["pt"][0] - w[0], mh_["pt"][1] - w[1]) * s < 16:
                return ("mh", i)
        if pg.res and pg.res.get("carport"):                                 # where the entry meets the kerb: drag it along the kerb
            ek_ = site_sheet.entry_shape(pg.st, pg.res["carport"])["k"]
            if math.hypot(ek_[0] - w[0], ek_[1] - w[1]) * s < 14:
                return ("entry",)
        if (pg.st.get("look") or {}).get("storm", True) and pg.res:
            sp_, sr_ = site_sheet.storm_pose(pg.st, pg.res)
            if sp_:
                hd_ = site_sheet.storm_head(sp_, sr_)
                if math.hypot(hd_[0] - w[0], hd_[1] - w[1]) * s < 14:
                    return ("storm_rot", sp_)
                if se.line_dist(w, sp_, hd_) * s < 8:
                    return ("storm_move", w, sp_)
        for i, c in enumerate(pg.st.get("custom") or []):
            if math.hypot(c["pt"][0] - w[0], c["pt"][1] - w[1]) * s < 12:
                return ("cust", i)
        for i, c in enumerate(pg.st.get("sewer_via") or []):
            if math.hypot(c[0] - w[0], c[1] - w[1]) * s < 12:
                return ("via", i)
        if pg.res:
            hp = pg.res["house"]
            for pk in ("sewer", "water", "db"):
                pt, _n = se.port_point(hp, pg.port_of(pk))
                if math.hypot(pt[0] - w[0], pt[1] - w[1]) * s < 10:
                    return ("port", pk)
            for i, wp in enumerate(pg.st.get("water_ports") or []):
                pt, _n = se.port_point(hp, wp)
                if math.hypot(pt[0] - w[0], pt[1] - w[1]) * s < 10:
                    return ("wport", i)
            for i, wp in enumerate(pg.st.get("sewer_ports") or []):
                pt, _n = se.port_point(hp, wp)
                if math.hypot(pt[0] - w[0], pt[1] - w[1]) * s < 10:
                    return ("sport", i)
            for nd in pg.res["sewer"]["nodes"]:
                if nd["kind"] in ("IE", "RE") and nd.get("key") and math.hypot(nd["pt"][0] - w[0], nd["pt"][1] - w[1]) * s < 9:
                    return ("eye", nd["key"])
            lab = self.label_at(qp)
            if lab:
                return ("label", lab, w, tuple((pg.st.get("labels") or {}).get(lab, (0.0, 0.0))))
            P = pg.res["sewer"]["path"]
            for k in range(len(P) - 1):
                if se.line_dist(w, P[k], P[k + 1]) * s < 6:
                    return ("sseg", k, [tuple(p) for p in P], w)
            if pg.res["carport"] and se.inside(w, pg.res["carport"]):
                c = pg.st["carport"]
                return ("carport", w, (c["cx"], c["cy"]))
            if se.inside(w, hp):
                h = pg.st["house"]
                return ("house", w, (h["cx"], h["cy"]))
        mn = se.mains(pg.st)
        for k in ("sewer", "water", "elec"):
            if abs(w[1] - mn[k]) * s < 5 and not (pg.res and se.inside(w, pg.st["stand"]["corners"])):
                return ("main", k)
        return None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel and self.sel[0] == "sewer" and getattr(self, "sv_last", None):
            self.page.delete_sewer_corner(self.sv_last)
            self.sv_last = None
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel and self.sel[0] == "label":
            self.page.delete_text(self.sel[1])
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel and self.sel[0] == "sport":
            self.page.remove_sport(self.sel[1])
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel and self.sel[0] == "eye":
            self.page.delete_eye(self.sel[1])
            return
        if e.key() == Qt.Key.Key_Escape and self.mode == "select" and self.sel:
            self.set_sel(None)
            return
        if e.key() == Qt.Key.Key_Escape and self.mode != "select":
            self.mode = "select"
            self.page.set_hint("")
            self.update()
            return
        super().keyPressEvent(e)

    def label_at(self, qp):
        """the text under the pointer, if any (texts are drawn in the last full redraw)"""
        sh = self.sh
        if not sh or not getattr(sh, "hits", None):
            return None
        for key, px, py, ang, w_, ht, _q, cx in reversed(sh.hits):
            dx, dy = qp.x() - px, qp.y() - py
            a = math.radians(ang)
            lx, ly = dx * math.cos(a) + dy * math.sin(a) - cx, -dx * math.sin(a) + dy * math.cos(a)
            if abs(lx) <= w_ / 2 + 4 and abs(ly) <= ht / 2 + 4:
                return key
        return None

    def hit_building(self, w):
        pg = self.page
        if pg.res and pg.res["carport"] and se.inside(w, pg.res["carport"]):
            return "carport"
        if pg.res and se.inside(w, pg.res["house"]):
            return "house"
        return None

    def context(self, gpos, w, qp=None):
        pg = self.page
        if self.mode != "select":                                 # adding points: right-click offers to stop
            m = QMenu(self)
            m.addAction("Done", self.finish_mode)
            m.addAction("Cancel", self.finish_mode)
            m.exec(gpos)
            return
        s_ = self.view[0] if self.view else 10
        if pg.res and pg.res.get("sewer"):
            P_ = pg.res["sewer"]["path"]
            for k_ in range(1, len(P_) - 1):
                if math.hypot(P_[k_][0] - w[0], P_[k_][1] - w[1]) * s_ < 12:
                    m = QMenu(self)
                    m.addAction("Delete this corner", lambda k2=k_: pg.delete_sewer_corner(k2))
                    m.addAction("Back to automatic", pg.sewer_auto)
                    m.exec(gpos)
                    return
        for i, c in enumerate(pg.st.get("sewer_via") or []):
            if math.hypot(c[0] - w[0], c[1] - w[1]) * s_ < 12:
                m = QMenu(self)
                m.addAction("Remove this sewer point", lambda i_=i: (pg.st["sewer_via"].pop(i_), pg.solve_now()))
                m.addAction("Clear all my sewer points", pg.clear_via)
                m.exec(gpos)
                return
        if pg.res and pg.res.get("carport"):
            ek_ = site_sheet.entry_shape(pg.st, pg.res["carport"])["k"]
            if math.hypot(ek_[0] - w[0], ek_[1] - w[1]) * s_ < 14:
                m = QMenu(self)
                m.addAction("Entry in front of the carport (automatic)", lambda: (pg.st["carport"].pop("entry_x", None), pg.solve_now(False), pg.commit(True)))
                m.exec(gpos)
                return
        for i, mh_ in enumerate(pg.st.get("manholes") or []):
            if math.hypot(mh_["pt"][0] - w[0], mh_["pt"][1] - w[1]) * s_ < 16:
                m = QMenu(self)
                m.addAction("Rename this manhole...", lambda i_=i: pg.rename_manhole(i_))
                m.addAction("Delete this manhole", lambda i_=i: pg.delete_manhole(i_))
                m.exec(gpos)
                return
        if (pg.st.get("look") or {}).get("storm", True) and pg.res:
            sp_, sr_ = site_sheet.storm_pose(pg.st, pg.res)
            if sp_ and se.line_dist(w, sp_, site_sheet.storm_head(sp_, sr_)) * s_ < 8:
                m = QMenu(self)
                for lab_, delta in (("Turn 90\u00b0 clockwise", -90), ("Turn 90\u00b0 anticlockwise", 90), ("Turn it round (180\u00b0)", 180), ("Turn 15\u00b0", 15)):
                    m.addAction(lab_, lambda d_=delta: pg.turn_storm(d_))
                m.addAction("Point it at the street", lambda: pg.turn_storm(None))
                m.addAction("Put it back where it was", pg.reset_storm)
                m.exec(gpos)
                return
        hp_ = pg.res["house"] if pg.res else None
        for i, wp in enumerate(pg.st.get("water_ports") or []):
            if hp_ and math.hypot(se.port_point(hp_, wp)[0][0] - w[0], se.port_point(hp_, wp)[0][1] - w[1]) * s_ < 10:
                m = QMenu(self)
                m.addAction("Remove this water point", lambda i_=i: (pg.st["water_ports"].pop(i_), pg.solve_now()))
                m.exec(gpos)
                return
        for i, wp in enumerate(pg.st.get("sewer_ports") or []):
            if hp_ and math.hypot(se.port_point(hp_, wp)[0][0] - w[0], se.port_point(hp_, wp)[0][1] - w[1]) * s_ < 10:
                m = QMenu(self)
                m.addAction("Remove this sewer outlet", lambda i_=i: pg.remove_sport(i_))
                m.exec(gpos)
                return
        lab = self.label_at(qp) if qp is not None else None
        if lab:
            m = QMenu(self)
            if lab.startswith("NOTE:"):
                k2_ = int(lab[5:].split("#")[0] or 0)
                m.addAction("Delete this text", lambda: pg.remove_note(k2_))
            m.addAction("Edit the text...", lambda: pg.edit_text(lab))
            m.addAction("Delete this text", lambda: pg.delete_text(lab))
            if lab.startswith("DIM:u"):
                k_ = int(lab[5:].split("#")[0] or 0)
                m.addAction("Remove this dimension", lambda: pg.remove_dim(k_))
            m.addAction("Put this text back", lambda: (pg.st.get("labels", {}).pop(lab, None), pg.changed(), self.update()))
            m.addAction("Put all texts back", pg.reset_labels)
            m.exec(gpos)
            return
        role = self.hit_building(w)
        if not role:
            return
        m = QMenu(self)
        if role == "carport":
            m.addAction("Cars enter from the next side", pg.entry_next)
            m.addSeparator()
        m.addAction("Rotate the %s..." % role, lambda: pg.rotate_dialog(role))
        m.addSeparator()
        for step in (90, 15, 5, 1):
            m.addAction("Turn %d\u00b0 clockwise" % step, lambda s_=step: pg.rotate_by(role, -s_))
            m.addAction("Turn %d\u00b0 anticlockwise" % step, lambda s_=step: pg.rotate_by(role, s_))
        m.addSeparator()
        m.addAction("Rotation back to 0", lambda: pg.rotate_by(role, -(pg.st[role].get("rot", 0) or 0)))
        m.exec(gpos)

    def mouseMoveEvent(self, e):
        if self._mode in ("sewer_draw", "mline_add", "wmain_add", "emain_add", "wall_pick", "wall_run") and self.sh:
            self.hover = self.world(e.position())
            self.update()
        d = self.drag
        if not d or not self.sh:
            return
        pg = self.page
        if d[0] == "pan":
            s, cx, cy = d[2]
            dx, dy = e.position().x() - d[1].x(), e.position().y() - d[1].y()
            a = site_sheet.Sheet(s, (cx, cy), (self.width(), self.height()), pg.st["sheet"].get("road", "left"), pg.st["sheet"].get("turn", 0.0))
            p0 = a.inv(QPointF(self.width() / 2, self.height() / 2))
            p1 = a.inv(QPointF(self.width() / 2 - dx, self.height() / 2 - dy))
            self.view = (s, cx + p1[0] - p0[0], cy + p1[1] - p0[1])
            self.update()
            return
        if d[0] == "fh":
            w_ = self.world(e.position())
            if math.hypot(w_[0] - d[1][-1][0], w_[1] - d[1][-1][1]) > 0.12:
                d[1].append(w_)
                self.update()
            return
        if d[0] == "turn":
            a1 = math.atan2(e.position().y() - self.height() / 2, e.position().x() - self.width() / 2)
            t = d[2] + math.degrees(a1 - d[1])
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                t = round(t / 5.0) * 5.0
            pg.set_turn(t)
            return
        if d[0] == "north":
            pg.st["sheet"]["north_pos"] = [round(e.position().x() / self.width(), 4), round(e.position().y() / self.height(), 4)]
            self.update()
            return
        w = self.world(e.position())
        if d[0] in ("pt", "port", "wport", "sport", "via", "house", "carport", "rot", "main"):
            pg.st.pop("eyes", None)                              # the run is going to change, so the eye edits no longer fit it
        if d[0] == "eye":
            pg.move_eye(d[1], w)
        elif d[0] == "pt":
            sn_ = se.snap_main(pg.st, w) if d[1] == "sewer" else None
            pg.st["points"][d[1]] = list(sn_) if sn_ else [round(w[0], 2), se.mains(pg.st)[d[1]]]
            pg.st["pts_manual"] = True
            if d[1] == "sewer" and pg.st.get("sewer_manual"):                # the run you placed follows its end to the new connection
                m_ = pg.st["sewer_manual"]
                m_[-1] = list(sn_) if sn_ else [round(w[0], 2), se.mains(pg.st)["sewer"]]
                if len(m_) > 1 and abs(m_[-2][0] - m_[-1][0]) > 1e-6 and not pg.st.get("sewer_free"):
                    m_[-2] = [round(w[0], 2), m_[-2][1]]
        elif d[0] == "wport":
            pg.st["water_ports"][d[1]] = se.nearest_port(pg.res["house"], w)
        elif d[0] == "sport":
            pg.st["sewer_ports"][d[1]] = se.nearest_port(pg.res["house"], w)
        elif d[0] == "via":
            pg.st["sewer_via"][d[1]] = [round(w[0], 2), round(w[1], 2)]
        elif d[0] == "cust":
            pg.st["custom"][d[1]]["pt"] = [round(w[0], 2), round(w[1], 2)]
        elif d[0] == "entry":
            if pg.st.get("carport"):
                pg.st["carport"]["entry_x"] = round(w[0], 2)
        elif d[0] == "mh":
            sn_ = se.snap_main(pg.st, w)
            pg.st["manholes"][d[1]]["pt"] = list(sn_) if sn_ else [round(w[0], 2), se.mains(pg.st)["sewer"]]
        elif d[0] == "storm_move":
            pg.st.setdefault("look", {})["storm_pos"] = [round(d[2][0] + w[0] - d[1][0], 2), round(d[2][1] + w[1] - d[1][1], 2)]
        elif d[0] == "storm_rot":
            a_ = math.degrees(math.atan2(w[1] - d[1][1], w[0] - d[1][0])) + 90.0
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
                a_ = round(a_ / 15.0) * 15.0
            lk_ = pg.st.setdefault("look", {})
            lk_["storm_rot"] = round(a_ % 360.0, 1)
            lk_.setdefault("storm_pos", [round(d[1][0], 2), round(d[1][1], 2)])
        elif d[0] == "label":
            pg.st.setdefault("labels", {})[d[1]] = [round(d[3][0] + w[0] - d[2][0], 2), round(d[3][1] + w[1] - d[2][1], 2)]
            self.lite = False
            self._full.start()
            self.update()
            return
        elif d[0] == "rot":
            ang = math.atan2(w[1] - d[2][1], w[0] - d[2][0])
            r = d[3] + math.degrees(ang - d[4])
            r = round(r / 15.0) * 15.0 if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else round(r)
            pg.st[d[1]]["rot"] = float(r % 360)
        elif d[0] == "dimend":
            pg.st["dims"][d[1]][d[2]] = list(pg.snap_point(w))
        elif d[0] in ("sv", "sseg"):
            pg.drag_sewer(d, w)
        elif d[0] == "main":
            pg.st.setdefault("mains", {})[d[1]] = round(min(w[1], -0.1), 2)
        elif d[0] == "port":
            hp = pg.res["house"]
            pg.st["ports"][d[1]] = se.nearest_port(hp, w)
        elif d[0] in ("house", "carport"):
            o = pg.st[d[0]]
            if d[0] == "carport":
                o.pop("entry_x", None)                                 # the entry follows the carport again
            o["cx"] = round(d[2][0] + w[0] - d[1][0], 2)
            o["cy"] = round(d[2][1] + w[1] - d[1][1], 2)
        pg.schedule(True)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag and self.drag[0] == "fh":
            stroke = self.drag[1]
            self.drag = None
            if len(stroke) >= 2:
                self.page.sewer_draw_stroke(stroke)
            else:
                self.page.sewer_draw_click(stroke[0], True)
            self.update()
        elif self.drag and self.drag[0] == "turn":
            self.page.changed()
            self.page.commit(True)
            self.drag = None
            self.auto = True
            self.update()
        elif self.drag and self.drag[0] in ("label", "north"):
            self.page.changed()
            self.page.commit(True)
        elif self.drag and self.drag[0] != "pan":
            if self.drag[0] == "rot":
                self.page._to_fields()
            self.page.solve_now(False)
            self.page.commit(True)
        elif self.drag and self.drag[0] == "pan" and self.rclick is not None and e.button() == Qt.MouseButton.RightButton:
            p0, w0 = self.rclick
            if abs(e.position().x() - p0.x()) < 4 and abs(e.position().y() - p0.y()) < 4:
                self.rclick = None
                self.drag = None
                self.context(e.globalPosition().toPoint(), w0, p0)
                return
        self.rclick = None
        self.drag = None
        self._full.start()

    def mouseDoubleClickEvent(self, e):
        if self.sh and e.button() == Qt.MouseButton.LeftButton and self.mode == "select":
            lab = self.label_at(e.position())
            if lab:
                self.page.edit_text(lab)

    def draw_main_gizmo(self, p):
        """while a main is being drawn: the stand's directions as faint guides, the line so far, the snapped next leg and a readout of angle and length"""
        pg, S = self.page, self.sh.pt
        st = pg.st
        pk = QColor("#d6209a")
        if self._mode == "mline_add":
            pts = list(st.get("main_line") or []) if getattr(pg, "_ml_on", False) else []
        else:
            k = "water" if self._mode == "wmain_add" else "elec"
            mp = (st.get("main_poly") or {}).get(k) or []
            pts = list(mp[0]) if getattr(pg, "_mn_on", {}).get(k) and mp else []
        # the stand's boundary directions through every corner, faint
        cs = st["stand"]["corners"]
        p.setPen(QPen(QColor(214, 32, 154, 70), 1, Qt.PenStyle.DotLine))
        for i in range(len(cs)):
            a, b = cs[i], cs[(i + 1) % len(cs)]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 3:
                continue
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
            p.drawLine(S((a[0] - u[0] * 40, a[1] - u[1] * 40)), S((a[0] + u[0] * 40, a[1] + u[1] * 40)))
        p.setPen(QPen(pk, 2.4))
        for a_, b_ in zip(pts[:-1], pts[1:]):
            p.drawLine(S(a_), S(b_))
        p.setBrush(QBrush(QColor("white")))
        for c in pts:
            p.drawEllipse(S(c), 5, 5)
        hv = getattr(self, "hover", None)
        if not hv:
            return
        free = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if pts:
            q, lab, ang, ln = pg.snap_main(hv, pts[-1], free)
            p.setPen(QPen(pk, 2.2, Qt.PenStyle.DashLine))
            p.drawLine(S(pts[-1]), S(q))
            p.setBrush(QBrush(pk))
            p.drawEllipse(S(q), 5, 5)
            txt = "%.2f m   %.0f deg   %s" % (ln, ang, lab)
        else:
            q = hv
            p.setBrush(QBrush(pk))
            p.drawEllipse(S(q), 5, 5)
            txt = "start of the main (x %.2f, y %.2f)" % (hv[0], hv[1])
        sp = S(q)
        f = QFont(self.font().family(), 9)
        f.setBold(True)
        p.setFont(f)
        rw_ = 14 + 7.2 * len(txt)
        r = QRectF(max(4, min(sp.x() + 12, self.width() - rw_ - 4)), max(4, sp.y() - 30), rw_, 22)
        p.setPen(QPen(pk, 1))
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("#222222"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    def draw_run_gizmo(self, p):
        """a wall run being placed: the start point, a rubber band along the boundary to the pointer and its length"""
        pg, S = self.page, self.sh.pt
        cs = pg.st["stand"]["corners"]
        pk = QColor("#d6209a")
        hv = getattr(self, "hover", None)
        a = getattr(pg, "_wr_a", None)
        sn = se.snap_to_edge(cs, hv, a[0] if a else None) if hv else None
        if not sn:
            return
        e, t, q = sn
        p.setBrush(QBrush(pk))
        p.setPen(QPen(QColor("white"), 1.5))
        p.drawEllipse(S(q), 6, 6)
        txt = None
        if a:
            ca, cb = cs[e], cs[(e + 1) % len(cs)]
            L = math.hypot(cb[0] - ca[0], cb[1] - ca[1])
            pa = (ca[0] + (cb[0] - ca[0]) * a[1], ca[1] + (cb[1] - ca[1]) * a[1])
            p.setPen(QPen(QColor("#c01919"), 7))
            p.drawLine(S(pa), S(q))
            txt = "wall %.2f m  (%.2f to %.2f m along the boundary)" % (abs(t - a[1]) * L, min(a[1], t) * L, max(a[1], t) * L)
        else:
            txt = "start here: %.2f m along boundary %d" % (t * math.hypot(cs[(e + 1) % len(cs)][0] - cs[e][0], cs[(e + 1) % len(cs)][1] - cs[e][1]), e + 1)
        sp = S(q)
        f = QFont(self.font().family(), 9)
        f.setBold(True)
        p.setFont(f)
        rw_ = 14 + 7.2 * len(txt)
        r = QRectF(max(4, min(sp.x() + 12, self.width() - rw_ - 4)), max(4, sp.y() - 32), rw_, 22)
        p.setPen(QPen(pk, 1))
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("#222222"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    def draw_wall_gizmo(self, p):
        """wall mode: each boundary shown with its number; a red thick line = wall, a grey dashed one = no wall; click an edge to switch it"""
        pg, S = self.page, self.sh.pt
        st = pg.st
        cs = st["stand"]["corners"]
        kinds = se.edge_kinds(cs)
        hv = getattr(self, "hover", None)
        near = pg.wall_edge_at(hv) if hv else None
        f = QFont(self.font().family(), 9)
        f.setBold(True)
        p.setFont(f)
        names = {"street": "front", "side": "side", "rear": "rear"}
        for i in range(len(cs)):
            a, b = cs[i], cs[(i + 1) % len(cs)]
            on = se.wall_on(st, i, kinds[i])
            col = QColor("#c01919") if on else QColor("#8a8a8a")
            p.setPen(QPen(col, 6 if on else 3, Qt.PenStyle.SolidLine if on else Qt.PenStyle.DashLine))
            p.drawLine(S(a), S(b))
            if i == near:
                p.setPen(QPen(QColor("#d6209a"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(S(a), S(b))
            m = S(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            txt = "%s %d: %s" % (names[kinds[i]], i + 1, "WALL" if on else "no wall")
            r = QRectF(m.x() - 4 * len(txt) - 6, m.y() - 11, 8 * len(txt) + 12, 22)
            p.setPen(QPen(col, 1))
            p.setBrush(QBrush(QColor(255, 255, 255, 235)))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#222222"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)

    def draw_gizmo(self, p):
        """what you can do with the selected thing: a ring to turn a building, corner handles on the sewer run, a frame round a text"""
        pg, sel = self.page, self.sel
        if self._mode in ("mline_add", "wmain_add", "emain_add") and self.sh:
            self.draw_main_gizmo(p)
        if self._mode in ("wall_pick", "wall_run") and self.sh:
            self.draw_wall_gizmo(p)
        if self._mode == "wall_run" and self.sh:
            self.draw_run_gizmo(p)
        if self._mode == "sewer_draw" and self.sh and pg.res and getattr(pg, "_sd_on", False):
            pk = QColor("#d6209a")
            S = self.sh.pt
            try:
                p0, n0 = se.port_point(pg.res["house"], pg.st["ports"]["sewer"])
                st_ = pg.st["params"].get("stub", se.DEFAULTS["stub"]) if pg.st.get("params") else se.DEFAULTS["stub"]
                q1 = (p0[0] + n0[0] * st_, p0[1] + n0[1] * st_)
                man, mds = [tuple(c) for c in pg._sd], list(pg._sdm)
                hv = getattr(self, "hover", None)
                if hv:
                    man.append((hv[0], hv[1]))
                    mds.append("free" if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else pg._sd_mode)
                mainy = se.conn_point(pg.st, "sewer")[1]
                if hv and se.main_dist(pg.st, hv) > (1.2 if se.main_line(pg.st) else max(0.3, mainy + 0.3)):    # not yet on the main: the preview ends at the pointer
                    pts = se.manual_route(q1, man[:-1] + [man[-1]], mds, man[-1][1], False)
                else:
                    pts = se.manual_route(q1, man, mds, mainy, False) if man else [q1]
                pts = [p0] + pts
                p.setPen(QPen(pk, 2.2, Qt.PenStyle.DashLine))
                for a_, b_ in zip(pts[:-1], pts[1:]):
                    p.drawLine(S(a_), S(b_))
                p.setBrush(QBrush(QColor("white")))
                p.setPen(QPen(pk, 2))
                for c in pg._sd:
                    p.drawEllipse(S(c), 6, 6)
                p.drawEllipse(S(p0), 7, 7)
            except Exception:
                pass
            return
        if not sel or not pg.res or not self.sh:
            return
        S = self.sh.pt
        pink = QColor("#d6209a")
        if sel[0] in ("house", "carport"):
            hnd = self.rot_handle(sel[0])
            if not hnd:
                return
            c, R, h = hnd
            cs, hs = S(c), S(h)
            rpx = self.sh.s * R
            p.setPen(QPen(pink, 1.4, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cs, rpx, rpx)
            p.drawLine(cs, hs)
            p.setPen(QPen(pink, 2))
            p.setBrush(QBrush(QColor("white")))
            p.drawEllipse(hs, 8, 8)
            p.drawEllipse(cs, 4, 4)
            p.setPen(pink)
            p.setFont(QFont(self.font().family(), 9, QFont.Weight.Bold))
            p.drawText(QPointF(hs.x() + 12, hs.y() - 10), "%d\u00b0" % round(pg.st[sel[0]].get("rot", 0.0)))
        elif sel[0] == "point":
            q = S(se.conn_point(pg.st, sel[1]))
            p.setPen(QPen(pink, 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(q, 13, 13)
        elif sel[0] == "eye":
            for nd in pg.res["sewer"]["nodes"]:
                if nd.get("key") == sel[1]:
                    q = S(nd["pt"])
                    p.setPen(QPen(pink, 2, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(q, 11, 11)
        elif sel[0] == "sewer":
            P = pg.res["sewer"]["path"]
            p.setPen(QPen(pink, 2))
            p.setBrush(QBrush(QColor("white")))
            for k in range(1, len(P)):
                q = S(P[k])
                p.drawRect(QRectF(q.x() - 6, q.y() - 6, 12, 12))
            p.setPen(QPen(pink, 1.4, Qt.PenStyle.DashLine))
            for k in range(len(P) - 1):
                p.drawLine(S(P[k]), S(P[k + 1]))
        elif sel[0] == "label":
            if sel[1].startswith("DIM:u"):
                try:
                    dm = pg.st["dims"][int(sel[1][5:].split("#")[0])]
                    p.setPen(QPen(pink, 2))
                    p.setBrush(QBrush(QColor("white")))
                    for which in ("a", "b"):
                        q = S(dm[which])
                        p.drawEllipse(q, 7, 7)
                except Exception:
                    pass
            for key, px, py, ang, w_, ht, _q, cx in getattr(self.sh, "hits", []):
                if key == sel[1]:
                    p.save()
                    p.translate(px, py)
                    p.rotate(ang)
                    p.setPen(QPen(pink, 1.6, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(QRectF(cx - w_ / 2 - 5, -ht / 2 - 5, w_ + 10, ht + 10))
                    p.restore()
                    break

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)


# ------------------------------------------------------------------ the page
class SiteServicesPage(ToolBase):
    KEY = "services"
    TITLE = "House placing"
    STEP_NAMES = ["Stand and house", "Connections", "Results"]
    STEP_HINTS = ["Bring in your stand, then drag the house in the plan, or press \"Place them for me\" at the bottom.",
                  "Show where the sewer, water and electricity come in. Click the plan, or drag the dots.",
                  "Pipe lengths and checks. Save the plan when you are happy."]

    def more(self, bv, text="More options"):
        """A folded-away section for the less used settings."""
        from PySide6.QtWidgets import QToolButton
        btn = QToolButton()
        btn.setText("\u25b8 " + text)
        btn.setCheckable(True)
        btn.setStyleSheet("QToolButton{border:none;text-align:left;padding:2px 0;}")
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        w.setVisible(False)
        btn.toggled.connect(lambda on: (w.setVisible(on), btn.setText(("\u25be " if on else "\u25b8 ") + text)))
        bv.addWidget(btn)
        bv.addWidget(w)
        return lay

    def __init__(self, win):
        super().__init__(win)
        self.st = blank_state()
        self.under = {}
        self.res = None
        self.show_under = True
        self._busy = False
        self._undo, self._redo, self._cst, self._ckey, self._undoing = [], [], None, None, False
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.view.finish_mode() if self.view.mode != "select" else self.view.set_sel(None)).setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for keys, fn in (("Ctrl+Z", lambda: self.undo()), ("Ctrl+Y", lambda: self.redo()), ("Ctrl+Shift+Z", lambda: self.redo())):
            QShortcut(QKeySequence(keys), self, activated=fn).setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(140)
        self._t.timeout.connect(self.solve_now)
        self.view = ServicesView(self)
        # ---- step 1
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Township drawing (all the stands)", "Open the big SG drawing once, then type a stand number: the tool finds that stand, the stands beside it and the sewer, water and electrical lines round it.")
        row = QHBoxLayout()
        tb_ = QPushButton("Open a township drawing (DXF)...")
        tb_.clicked.connect(self.open_township)
        self.tn_layers_b = QPushButton("Layers...")
        self.tn_layers_b.setToolTip("Tell the tool which drawing layer is the sewer, the water, the electrical, the stand boundaries and the roads.")
        self.tn_layers_b.clicked.connect(self.township_layers)
        self.tn_layers_b.setEnabled(False)
        row.addWidget(tb_)
        row.addWidget(self.tn_layers_b)
        row.addStretch(1)
        bv.addLayout(row)
        row = QHBoxLayout()
        self.tn_no = QLineEdit()
        self.tn_no.setPlaceholderText("Stand number, e.g. 2155")
        self.tn_no.setMaximumWidth(220)
        self.tn_no.returnPressed.connect(self.go_to_stand)
        self.tn_go = QPushButton("Go to this stand")
        self.tn_go.clicked.connect(self.go_to_stand)
        row.addWidget(self.tn_no)
        row.addWidget(self.tn_go)
        row.addStretch(1)
        bv.addLayout(row)
        self.tn_house = QCheckBox("Place the house and carport the way they are on the site plan (built-in Blue Hills Ext 120 stands)")
        self.tn_house.setChecked(True)
        bv.addWidget(self.tn_house)
        self.tn_lbl = QLabel("")
        self.tn_lbl.setObjectName("xaSub")
        self.tn_lbl.setWordWrap(True)
        bv.addWidget(self.tn_lbl)
        v1.addWidget(bx)
        bx, bv = self.box("1. Your stand", "Start here. Open your stand drawing, or just type its size.")
        row = QHBoxLayout()
        ib = QPushButton("Open a stand drawing (DXF)...")
        ib.clicked.connect(self.import_stand_dxf)
        sb_ = QPushButton("Mark the street side (click it in the plan)")
        sb_.setToolTip("After an import, click the boundary that faces the street.")
        sb_.clicked.connect(lambda: self.arm("street"))
        row.addWidget(ib)
        row.addWidget(sb_)
        row.addStretch(1)
        bv.addLayout(row)
        self.ref_lbl = QLabel("")
        self.ref_lbl.setObjectName("xaSub")
        self.ref_lbl.setWordWrap(True)
        bv.addWidget(self.ref_lbl)
        row = QHBoxLayout()
        self.q_w, self.q_d = spin(2, 500, 13.5, 2, " m"), spin(2, 500, 22, 2, " m")
        mk = QPushButton("Draw it")
        mk.clicked.connect(self.make_rect)
        fb = QPushButton("Use the stand from the Building lines tool")
        fb.clicked.connect(self.from_site_page)
        for w in (QLabel("Width along the street"), self.q_w, QLabel("Depth"), self.q_d, mk):
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        bv.addWidget(fb)
        row = QHBoxLayout()
        self.sb_street, self.sb_side, self.sb_rear = spin(0, 20, 1.0, 2, " m"), spin(0, 20, 1.0, 2, " m"), spin(0, 20, 2.0, 2, " m")
        for lab, w in (("Space to keep clear: street", self.sb_street), ("side", self.sb_side), ("rear", self.sb_rear)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        self.stand_lbl = QLabel("")
        self.stand_lbl.setObjectName("xaSub")
        self.stand_lbl.setWordWrap(True)
        bv.addWidget(self.stand_lbl)
        v1.addWidget(bx)
        bx, bv = self.box("2. Plan labels", "The stand number and street name that print on the plan.")
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
        ml = self.more(bv, "Road side and north arrow")
        row = QHBoxLayout()
        self.sh_road = QComboBox()
        for t_ in ("left", "right", "top", "bottom"):
            self.sh_road.addItem(t_)
        self.sh_north = spin(-360, 360, 0, 1, " deg", 5)
        row.addWidget(QLabel("The road is on the"))
        row.addWidget(self.sh_road)
        row.addWidget(QLabel("North arrow turned"))
        row.addWidget(self.sh_north)
        self.sh_turn = spin(-180, 180, 0, 1, " deg", 5)
        self.sh_turn.setToolTip("Turn the whole plan on the page (degrees clockwise). The north arrow turns with it.")
        sq_ = QPushButton("Square up")
        sq_.setToolTip("Turn the plan so the stand's edges run along the page")
        sq_.clicked.connect(lambda _=False: self.square_up())
        row.addWidget(QLabel("Plan turned"))
        row.addWidget(self.sh_turn)
        for txt_, d_, tip_ in (("\u21ba", -15, "Turn the plan 15 degrees anticlockwise"), ("\u21bb", 15, "Turn the plan 15 degrees clockwise")):
            b_ = QPushButton(txt_)
            b_.setToolTip(tip_)
            b_.setFixedWidth(30)
            b_.clicked.connect(lambda _=False, d=d_: (self.set_turn((self.st["sheet"].get("turn", 0.0) or 0.0) + d), self.view.fit(), self.changed(), self.commit(True)))
            row.addWidget(b_)
        row.addWidget(sq_)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        self.look_cb = {}
        for key, text in (("fill", "Green stand"), ("walls", "Boundary walls"), ("storm", "Stormwater arrow"), ("wp_box", "WP / VV box and marks"), ("upright", "Names and numbers stay level when the plan is turned")):
            cb_ = QCheckBox(text)
            cb_.setChecked(True)
            cb_.toggled.connect(lambda on, k=key: self.set_look(k, on))
            self.look_cb[key] = cb_
            row.addWidget(cb_)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        rb_ = QPushButton("Show where the road is")
        rb_.setToolTip("Click on the side of the stand where the road is. The plan turns so the street faces that way, then you click the direction of north.")
        rb_.clicked.connect(lambda: self.arm("road"))
        nb_ = QPushButton("Show where north is")
        nb_.clicked.connect(lambda: self.arm("north_dir"))
        nm_ = QPushButton("North arrow to the top")
        nm_.clicked.connect(lambda: (self.st["sheet"].__setitem__("north_pos", None), self.view.update(), self.changed()))
        for b_ in (rb_, nb_, nm_):
            row.addWidget(b_)
        row.addStretch(1)
        ml.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("3. Your house", "The red box. Drag it in the plan, turn it with the ring, or type its size.")
        row = QHBoxLayout()
        self.h_w, self.h_d, self.h_rot = spin(1, 60, 14.8, 2, " m"), spin(1, 60, 6.5, 2, " m"), spin(-360, 360, 90, 0, " deg", 90)
        self.h_x, self.h_y = spin(-100, 500, 9, 2, " m"), spin(-100, 500, 12, 2, " m")
        for lab, w in (("Length", self.h_w), ("Width", self.h_d), ("Turned", self.h_rot)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        ml = self.more(bv, "Exact position")
        row = QHBoxLayout()
        for lab, w in (("Centre x", self.h_x), ("y", self.h_y)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Pick a house from the library...", self.pick_footprint), ("Turn it...", lambda: self.rotate_dialog("house")), ("Open a house drawing (DXF)...", lambda: self.import_building_dxf("house")),
                         ("Plain box", lambda: self.plain_rect("house"))):
            b_ = QPushButton(text)
            b_.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b_)
        row.addStretch(1)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("4. Carport (optional)", "Tick it if the house has a carport.")
        row = QHBoxLayout()
        self.c_on = QCheckBox("Carport")
        self.c_on.setChecked(True)
        self.c_w, self.c_d = spin(1, 30, 5, 2, " m"), spin(1, 30, 5, 2, " m")
        self.c_x, self.c_y = spin(-100, 500, 3.5, 2, " m"), spin(-100, 500, 3.5, 2, " m")
        row.addWidget(self.c_on)
        for lab, w in (("Width", self.c_w), ("Depth", self.c_d)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        bv.addLayout(row)
        ml = self.more(bv, "Exact position")
        row = QHBoxLayout()
        for lab, w in (("Centre x", self.c_x), ("y", self.c_y)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addStretch(1)
        ml.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Turn it...", lambda: self.rotate_dialog("carport")), ("Open a carport drawing (DXF)...", lambda: self.import_building_dxf("carport")),
                         ("Plain box", lambda: self.plain_rect("carport"))):
            b_ = QPushButton(text)
            b_.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b_)
        row.addStretch(1)
        bv.addLayout(row)
        ef_ = QPushButton("Cars enter from the next side")
        ef_.setToolTip("The cars drive in on the side facing the street. Press to move the entry (and the arrows) a quarter turn round the carport.")
        ef_.clicked.connect(self.entry_next)
        bv.addWidget(ef_)
        sg = QPushButton("Place them for me (inside the building lines)")
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
        self.main_spin = {}
        for key, title, sub in (("sewer", "Sewer", "Where the house sewer joins the municipal main (see the SG sewer sheet)."),
                                ("water", "Water", "Where the water connection (W.CON) is."),
                                ("elec", "Electricity", "Where the electrical supply (EC) is. It is not on the SG sheets.")):
            bx, bv = self.box(title, sub)
            row = QHBoxLayout()
            sx, sy = spin(-100, 500, 0, 2, " m"), spin(-100, 500, 0, 2, " m")
            self.pt_spin[key] = (sx, sy)
            pb = QPushButton("Click it in the plan")
            pb.clicked.connect(lambda _=False, k=key: self.arm("pt_" + k))
            ab = QPushButton("Where it leaves the house (click the house)")
            ab.clicked.connect(lambda _=False, k=key: self.arm("port_" + ("db" if k == "elec" else k)))
            rb = QPushButton("Let the program choose")
            rb.clicked.connect(lambda _=False, k=key: self.reset_port("db" if k == "elec" else k))
            row.addWidget(pb)
            row.addWidget(ab)
            row.addStretch(1)
            bv.addLayout(row)
            ml = self.more(bv, "Exact position and settings")
            row = QHBoxLayout()
            row.addWidget(QLabel("Along the street"))
            row.addWidget(sx)
            row.addStretch(1)
            ml.addLayout(row)
            row = QHBoxLayout()
            ms = spin(0, 40, -se.DEFAULT_MAINS[key], 2, " m", 0.1)
            self.main_spin[key] = ms
            row.addWidget(QLabel("Main line is this far outside the street boundary"))
            row.addWidget(ms)
            row.addStretch(1)
            ml.addLayout(row)
            row = QHBoxLayout()
            row.addWidget(rb)
            row.addStretch(1)
            ml.addLayout(row)
            if key in ("water", "elec"):
                row = QHBoxLayout()
                nm_ = "water" if key == "water" else "electrical"
                mb2_ = QPushButton("Draw the main %s line (click along it)" % nm_)
                mb2_.setToolTip("Click along where the main %s line runs, point by point; the house connection goes to the nearest point on it. Press Done when it is drawn." % nm_)
                mb2_.clicked.connect(lambda _=False, k=key: self.arm("wmain_add" if k == "water" else "emain_add"))
                mc2_ = QPushButton("Main as in the drawing")
                mc2_.setToolTip("Take back the main as it is in the imported drawing (or the straight line along the street when there is none).")
                mc2_.clicked.connect(lambda _=False, k=key: self.clear_main(k))
                row.addWidget(mb2_)
                row.addWidget(mc2_)
                row.addStretch(1)
                bv.addLayout(row)
            if key == "water":
                row = QHBoxLayout()
                wb_ = QPushButton("Add another water point (click the house)")
                wb_.setToolTip("Up to 4 water points on the house. Each one branches off the water pipe already laid, in square runs.")
                wb_.clicked.connect(lambda: self.arm("wport_add"))
                wr_ = QPushButton("Remove the last water point")
                wr_.clicked.connect(self.remove_last_wport)
                row.addWidget(wb_)
                row.addWidget(wr_)
                row.addStretch(1)
                bv.addLayout(row)
            if key == "sewer":
                row = QHBoxLayout()
                dr_ = QPushButton("Draw the sewer (click start, corners, main)")
                dr_.setToolTip("Click where the sewer starts on the house (minimum invert), click each 90 degree corner, then click the main sewer line. The eyes go in by themselves.")
                dr_.clicked.connect(self.sewer_draw_start)
                row.addWidget(dr_)
                sb_ = QPushButton("Add another sewer outlet (click the house)")
                sb_.setToolTip("Up to 4 sewer outlets on the house. Each runs square to the sewer run and butts onto it. Drag its square on the wall to move it; select it and press Delete to remove it.")
                sb_.clicked.connect(lambda: self.arm("sport_add"))
                sr_ = QPushButton("Remove the last extra outlet")
                sr_.clicked.connect(lambda: self.remove_sport(len(self.st.get("sewer_ports") or []) - 1))
                row.addWidget(sb_)
                row.addWidget(sr_)
                row.addStretch(1)
                bv.addLayout(row)
            if key == "sewer":
                row = QHBoxLayout()
                self.p_depth, self.p_fall, self.p_ie = spin(0.3, 6, 1.5, 2, " m"), spin(20, 200, 50, 0, "", 5), spin(5, 60, 25, 0, " m", 1)
                self.p_pipe = QComboBox()
                self.p_pipe.addItems(["110", "160"])
                self.p_tail = spin(0.1, 3, 0.35, 2, " m", 0.1)
                self.p_tail.setToolTip("The rodding eye sits this far past the inspection eye where the house outlet joins the run (and past any other connection). 300 to 400 mm is usual.")
                for lab, w in (("Depth at the main", self.p_depth), ("Fall 1 :", self.p_fall), ("Eyes at most", self.p_ie), ("Rodding eye past the joint", self.p_tail), ("Pipe size", self.p_pipe)):
                    row.addWidget(QLabel(lab))
                    row.addWidget(w)
                row.addStretch(1)
                ml2 = self.more(bv, "Pipe settings (depth, fall, eyes)")
                ml2.addLayout(row)
                row = QHBoxLayout()
                vb = QPushButton("Add a sewer point: click in the plan")
                vb.setToolTip("The sewer is routed through the points you add, in order, in square runs. Drag a point to move it, right-click it to remove it.")
                vb.clicked.connect(lambda: self.arm("via_add"))
                cb_ = QPushButton("Clear my sewer points")
                cb_.clicked.connect(self.clear_via)
                row.addWidget(vb)
                row.addWidget(cb_)
                row.addStretch(1)
                ml2.addLayout(row)
                row = QHBoxLayout()
                mb_ = QPushButton("Draw the main sewer through the stand")
                mb_.setToolTip("When the municipal main crosses your stand (as on the finished plans), click along it. The connection then goes to the nearest point on it.")
                mb_.clicked.connect(lambda: self.arm("mline_add"))
                mc_ = QPushButton("Main back along the street")
                mc_.clicked.connect(self.clear_mline)
                row.addWidget(mb_)
                row.addWidget(mc_)
                row.addStretch(1)
                ml2.addLayout(row)
                row = QHBoxLayout()
                hb_ = QPushButton("Add a manhole (click on the main)")
                hb_.clicked.connect(lambda: self.arm("mh_add"))
                hr_ = QPushButton("Remove the last manhole")
                hr_.clicked.connect(self.remove_manhole)
                row.addWidget(hb_)
                row.addWidget(hr_)
                row.addStretch(1)
                ml2.addLayout(row)
            v2.addWidget(bx)
        bx, bv = self.box("Extra points (optional)", "Add a connection of your own, for example a manhole. Used when it is closer than the main.")
        row = QHBoxLayout()
        self.cu_kind = QComboBox()
        for k_, t_ in (("sewer", "Sewer"), ("water", "Water"), ("elec", "Electrical"), ("other", "Other marker")):
            self.cu_kind.addItem(t_, k_)
        self.cu_name = QLineEdit()
        self.cu_name.setPlaceholderText("Name, e.g. manhole")
        ab_ = QPushButton("Add (click the plan)")
        ab_.clicked.connect(lambda: self.arm("cust_add"))
        rb_ = QPushButton("Remove selected")
        rb_.clicked.connect(self.remove_custom)
        for w_ in (self.cu_kind, self.cu_name, ab_, rb_):
            row.addWidget(w_)
        bv.addLayout(row)
        self.cu_list = QListWidget()
        self.cu_list.setMaximumHeight(90)
        bv.addWidget(self.cu_list)
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
        bx, bv = self.box("Pipe lengths", "")
        self.svc_t = QTableWidget(0, 3)
        self.svc_t.setHorizontalHeaderLabels(["Service", "Length", "Note"])
        self.svc_t.verticalHeader().setVisible(False)
        self.svc_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.svc_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.svc_t.setMinimumHeight(120)
        bv.addWidget(self.svc_t)
        v3.addWidget(bx)
        bx, bv = self.box("Sewer eyes and depths", "Depth is below ground at the bottom of the pipe.")
        self.node_t = QTableWidget(0, 4)
        self.node_t.setHorizontalHeaderLabels(["Node", "Distance from the house", "Depth (mm)", "Where"])
        self.node_t.verticalHeader().setVisible(False)
        self.node_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.node_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.node_t.setMinimumHeight(180)
        bv.addWidget(self.node_t)
        v3.addWidget(bx)
        bx, bv = self.box("Save your plan", "The DXF opens in ArchiCAD exactly as you see it here.")
        row = QHBoxLayout()
        for text, fn in (("Save the plan as PDF...", self.save_pdf), ("Save as DXF (for ArchiCAD)...", self.save_dxf), ("Save as an image...", self.save_png), ("Save my work...", self.save_json), ("Open my work...", self.open_json)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        v3.addWidget(bx)
        v3.addStretch(1)
        self.build_frame([p1, p2, p3], side=self._panel())
        for w in (self.sb_street, self.sb_side, self.sb_rear, self.h_w, self.h_d, self.h_rot, self.h_x, self.h_y, self.c_w, self.c_d, self.c_x, self.c_y,
                  self.p_depth, self.p_fall, self.p_ie, self.p_tail):
            w.valueChanged.connect(self._edited)
        self.c_on.toggled.connect(self._edited)
        for w_ in (self.sh_no, self.sh_street, self.sh_rw, self.sh_se):
            w_.textChanged.connect(self._edited)
        self.sh_road.currentIndexChanged.connect(self._edited)
        self.sh_north.valueChanged.connect(self._edited)
        self.sh_turn.valueChanged.connect(self._edited)
        self.p_pipe.currentIndexChanged.connect(self._edited)
        for sx, sy in self.pt_spin.values():
            sx.valueChanged.connect(self._edited)
            sy.valueChanged.connect(self._edited)
        for ms in self.main_spin.values():
            ms.valueChanged.connect(self._edited)
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
        tb_ = QPushButton("Add text")
        tb_.setToolTip("Click in the plan and type a text. Drag it, double-click it to edit it.")
        tb_.clicked.connect(lambda: self.arm("text_add"))
        fl.addWidget(tb_)
        db_ = QPushButton("Add a dimension")
        db_.setToolTip("Click two points (corners snap). Drag the figure to slide the dimension up or down. Right-click the figure to remove it.")
        db_.clicked.connect(lambda: (setattr(self, "_dim_a", None), self.arm("dim_add")))
        fl.addWidget(db_)
        so_ = QCheckBox("Setting-out lines")
        so_.setChecked(True)
        so_.setToolTip("Light blue dashed lines from the boundaries to the corners of the house. They follow the house when you rotate it.")
        so_.toggled.connect(self.set_setting_out)
        self.so_cb = so_
        fl.addWidget(so_)
        wc_ = QCheckBox("Boundary walls")
        wc_.setChecked(True)
        wc_.setToolTip("The 1.2 m high pre-cast concrete walls on the side and rear boundaries (red strips with their text).")
        wc_.toggled.connect(lambda on: self.set_look("walls", on))
        self.tb_walls = wc_
        fl.addWidget(wc_)
        wp_ = QPushButton("Place walls")
        wp_.setToolTip("Choose which boundaries get the 1.2 m pre-cast wall: click a boundary on the plan to switch its wall on or off (for example no wall at the front).")
        wp_.clicked.connect(lambda: self.arm("wall_pick"))
        wr_ = QPushButton("Wall run")
        wr_.setToolTip("A wall of your own length: click where it starts and where it ends on a boundary (snaps to the boundary and to corners).")
        wr_.clicked.connect(lambda: self.arm("wall_run"))
        fl.addWidget(wr_)
        fl.addWidget(wp_)
        nb_ = QPushButton("New placing")
        nb_.setToolTip("Start again: a blank stand, house and carport, nothing left from the last one. Undo brings the old one back.")
        nb_.clicked.connect(self.new_placing)
        fl.addWidget(nb_)
        for lab, fn in (("Undo", lambda: self.undo()), ("Redo", lambda: self.redo())):
            ub_ = QPushButton(lab)
            ub_.setToolTip("%s (Ctrl+%s)" % (lab, "Z" if lab == "Undo" else "Y"))
            ub_.clicked.connect(fn)
            fl.addWidget(ub_)
        rl = QPushButton("Texts back")
        rl.setToolTip("Drag any text on the plan to move it. This puts all the texts back where they were generated.")
        rl.clicked.connect(self.reset_labels)
        fl.addWidget(rl)
        wb = QPushButton("Wide plan")
        wb.setCheckable(True)
        wb.setToolTip("Hide the steps on the left so the plan fills the window. You can also drag the divider.")
        wb.toggled.connect(self.wide_plan)
        fl.addWidget(wb)
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

    def north_centre(self, W, H, r_px, interactive=True):
        pos = (self.st.get("sheet") or {}).get("north_pos")
        if pos:
            return QPointF(pos[0] * W, pos[1] * H)
        return QPointF(W * 0.5, r_px * 2.2 + 8) if interactive else QPointF(W * 0.5, r_px * 2.6)

    def set_road_from_click(self, qp):
        """the click is where the road is: the side of the stand (as drawn on the paper) it is nearest to"""
        sh = self.view.sh
        c = self.st["stand"]["corners"]
        cen = sh.pt((sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)))
        dx, dy = qp.x() - cen.x(), qp.y() - cen.y()
        # the road is on the paper side the click is on; the plan turns so the street faces it
        side = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("bottom" if dy > 0 else "top")
        self.sh_road.setCurrentText(side)
        self.solve_now()
        self.view.fit()

    def set_north_from_click(self, qp):
        W, H = self.view.width(), self.view.height()
        r = max(self.view.sh.s * 1.5, 18)
        c = self.north_centre(W, H, r)
        ang = math.degrees(math.atan2(qp.x() - c.x(), -(qp.y() - c.y())))
        self.sh_north.setValue(round(ang, 1))

    def sheet_opts(self):
        sh = dict(self.st.get("sheet") or {})
        sh["labels"] = self.st.get("labels") or {}
        sh["text_edit"] = self.st.get("text_edit") or {}
        sh["hidden"] = self.st.get("text_hidden") or []
        sh["nb_lines"] = self.neighbour_lines()
        try:
            no = int(sh.get("stand_no", ""))
            sh["neigh"] = [] if self.st.get("neighbours") else [no - 1, no + 1]   # real neighbours come from the township drawing
        except ValueError:
            sh["neigh"] = []
        return sh

    @staticmethod
    def _seg_dist(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)

    def neighbour_lines(self):
        """the boundaries of the adjacent stands that start at a corner of this one, from the imported drawing (or the built-in sheet), kept short and clean"""
        c = [tuple(p) for p in self.st["stand"]["corners"]]
        src = self.st.get("underlay") or (self.under or {}).get("other") or []
        key = (id(src), len(src), tuple(c))
        if getattr(self, "_nb_key", None) == key:
            return self._nb
        out = []
        n = len(c)
        for ln in src:
            a, b = (ln[0], ln[1]), (ln[2], ln[3])
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 0.8:
                continue
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            # only boundary-like lines: along or square to one of the stand's own sides (not the engineers' diagonals and the like)
            if not any(abs((c[(i + 1) % n][0] - c[i][0]) * uy - (c[(i + 1) % n][1] - c[i][1]) * ux) < 0.1 * math.hypot(c[(i + 1) % n][0] - c[i][0], c[(i + 1) % n][1] - c[i][1])
                       or abs((c[(i + 1) % n][0] - c[i][0]) * ux + (c[(i + 1) % n][1] - c[i][1]) * uy) < 0.1 * math.hypot(c[(i + 1) % n][0] - c[i][0], c[(i + 1) % n][1] - c[i][1]) for i in range(n)):
                continue
            for k in c:
                if se.line_dist(k, a, b) >= 0.3:
                    continue
                t = (k[0] - a[0]) * ux + (k[1] - a[1]) * uy              # where the line passes the corner
                for end, ln_ in ((a, t), (b, L - t)):
                    if ln_ < 0.8:
                        continue
                    sgn = -1.0 if end is a else 1.0
                    far = min(ln_, 12.0)
                    q = (k[0] + ux * sgn * far, k[1] + uy * sgn * far)
                    mid = ((k[0] + q[0]) / 2, (k[1] + q[1]) / 2)
                    if se.inside(mid, c) or any(self._seg_dist(mid, c[i], c[(i + 1) % n]) < 0.15 for i in range(n)):
                        continue                                          # that part is the stand's own boundary
                    if not any(math.hypot(k[0] - o[0][0], k[1] - o[0][1]) < 0.05 and math.hypot(q[0] - o[1][0], q[1] - o[1][1]) < 0.3 for o in out):
                        out.append((k, q))
        self._nb_key, self._nb = key, out
        return out

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
        st["mains"] = {k: -ms.value() for k, ms in self.main_spin.items()}
        prev = st.get("sheet") or {}
        road_new, deg_new = self.sh_road.currentText(), self.sh_north.value()
        turn_new = self.sh_turn.value()
        turn_old = prev.get("turn", 0.0) or 0.0
        nw = st.get("north_world")
        if nw and ((prev.get("road") and road_new != prev.get("road")) or abs(turn_new - turn_old) > 1e-9):          # the road moved to another side of the page, or the plan was turned: the arrow turns, north stays
            deg_new = round(se.north_world_to_screen(nw, road_new, turn_new), 1)
            self._busy = True
            self.sh_north.setValue(deg_new)
            self._busy = False
        else:
            nw = list(se.north_screen_to_world(deg_new, road_new, turn_new))
        st["north_world"] = [round(nw[0], 4), round(nw[1], 4)]
        st["sheet"] = {"road": road_new, "street": self.sh_street.text().strip(), "road_w": self.sh_rw.text().strip(), "street_erf": self.sh_se.text().strip(),
                       "stand_no": self.sh_no.text().strip(), "north": deg_new, "turn": turn_new,
                       "north_pos": prev.get("north_pos")}
        if self.view.auto is False and False:
            pass
        st["params"] = {"conn_depth": self.p_depth.value(), "fall": self.p_fall.value(), "max_ie": self.p_ie.value(), "re_ext": self.p_tail.value(), "sewer_pipe": self.p_pipe.currentText(),
                        "sb_street": self.sb_street.value(), "sb_side": self.sb_side.value(), "sb_rear": self.sb_rear.value()}
        self.schedule()

    def _to_fields(self):
        self._busy = True
        try:
            st = self.st
            sb = st["stand"].get("setbacks") or {}
            for k_, cb_ in getattr(self, "look_cb", {}).items():
                cb_.setChecked(bool((st.get("look") or {}).get(k_, True)))
            if hasattr(self, "tb_walls"):
                self.tb_walls.setChecked(bool((st.get("look") or {}).get("walls", True)))
            if hasattr(self, "so_cb"):
                self.so_cb.setChecked(bool((st.get("sheet") or {}).get("setting_out", True)))
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
            mn = se.mains(st)
            for k, ms in self.main_spin.items():
                ms.setValue(-mn[k])
            self._fill_custom()
            sh = st.get("sheet") or {}
            self.sh_no.setText(str(sh.get("stand_no", "")))
            self.sh_street.setText(str(sh.get("street", "")))
            self.sh_rw.setText(str(sh.get("road_w", "13m")))
            self.sh_se.setText(str(sh.get("street_erf", "")))
            self.sh_road.setCurrentText(str(sh.get("road", "left")))
            self.sh_north.setValue(float(sh.get("north", 0)))
            self.sh_turn.setValue(float(sh.get("turn", 0)))
            pr = st.get("params") or {}
            self.p_depth.setValue(pr.get("conn_depth", 1.5))
            self.p_fall.setValue(pr.get("fall", 50))
            self.p_ie.setValue(pr.get("max_ie", 25))
            self.p_tail.setValue(pr.get("re_ext", 0.35))
            self.p_pipe.setCurrentText(str(pr.get("sewer_pipe", "110")))
        finally:
            self._busy = False

    # ---- solving
    def schedule(self, light=False):
        """light: the plan is being dragged, so work the lines out and redraw but leave the tables and fields until you let go"""
        self._light = light
        self._t.setInterval(40 if light else 140)
        self._t.start()

    def new_placing(self):
        self.commit(True)
        self.set_state(blank_state())
        self.under = {}
        self._src_bbox = None
        self.view.fit()
        self.set_hint("New placing: import a stand, or make a rectangle.")
        QTimer.singleShot(6000, lambda: self.set_hint(""))

    def commit(self, force=False):
        """remember the state before an edit, for Undo. While something is being dragged only the end of the drag counts."""
        if self._undoing:
            return
        d = self.view.drag
        if d is not None and d[0] != "pan" and not force:
            return
        try:
            key = json.dumps(self.st, sort_keys=True, default=str)
        except Exception:
            return
        if key == self._ckey:
            return
        if self._cst is not None:
            self._undo.append(self._cst)
            del self._undo[:-100]
        self._redo = []
        self._cst, self._ckey = copy.deepcopy(self.st), key

    def _restore(self, stt):
        self._undoing = True
        try:
            self._cst, self._ckey = copy.deepcopy(stt), json.dumps(stt, sort_keys=True, default=str)
            self.set_state(copy.deepcopy(stt))
        finally:
            self._undoing = False

    def undo(self):
        if not self._undo:
            self.set_hint("Nothing to undo.")
            return
        self._redo.append(self._cst)
        self._restore(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self._cst)
        self._restore(self._redo.pop())

    def solve_now(self, light=None):
        self.commit()
        self._t.stop()
        if light is None:
            light = getattr(self, "_light", False) and self.view.drag is not None
        self._light = False
        try:
            se.FAST = bool(light)                                # dragging: coarse routing; letting go: the exact lines
            try:
                self.res = se.solve(self.st)
            finally:
                se.FAST = False
        except Exception as e:                                  # a bad input must never take the tool down
            self.res = None
            self.warn_lbl.setText("Could not work out the lines: %s" % e)
            return
        if not light:
            self.fill_results()
            self.changed()
        self.view.update()

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
        txt = "<br>".join("&#9888; " + x for x in w) if w else "&#10003; Inside the building lines. Sewer depth is fine."
        ref = r.get("reference") or []
        if ref:
            txt += "<br><br><b>Compared with your finished plans</b><br>" + "<br>".join("&#8226; " + x for x in ref)
        self.warn_lbl.setText(txt)
        self.warn_lbl.setStyleSheet("color:#b3261e;" if w else "color:#1a7f37;")
        nr = self.nearest_reference()
        self.ref_lbl.setText("Closest stand in the reference library: Blue Hills Ext 120 stand %s (%.0f m2)." % (nr, STANDS[nr]["area"]) if nr else "")
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
                       "port_water": "Click on the house outline where the water enters.", "port_db": "Click on the house outline where the DB is.",
                       "wport_add": "Click on the house outline where another water point enters. Press Esc when done.", "sport_add": "Click on the house wall where another sewer outlet leaves the house. Press Esc when done.", "sewer_draw": "Click where the sewer starts.", "text_add": "Click in the plan where the text goes.", "dim_add": "Click the first point of the dimension (corners snap), then the second. Drag its figure to slide it. Press Esc when done.", "road": "Click on the side of the stand where the road is.", "north_dir": "Click in the direction north points. You can also drag the arrow to move it.", "via_add": "Click in the plan where the sewer must pass. Click again for the next point, in order from the house to the main. Press Esc when done.", "street": "Click the boundary that faces the street.", "wmain_add": "Click along where the main water line runs, point by point. It snaps parallel to the stand boundaries and at 45 degrees to them (Shift = free). Press Done when it is drawn.", "emain_add": "Click along where the main electrical line runs, point by point. It snaps parallel to the stand boundaries and at 45 degrees to them (Shift = free). Press Done when it is drawn.", "mline_add": "Click along where the main sewer runs, point by point (it can cross the stand). It snaps parallel to the stand boundaries and at 45 degrees to them (Shift = free). Press Done when it is drawn.", "wall_pick": "Click a boundary of the stand to switch its 1.2 m pre-cast wall on or off (red = wall, grey = none). Press Done when finished.", "wall_run": "Click on a boundary where the wall starts, then click where it ends (it snaps to the boundary and sticks to corners). Esc or Done when finished.", "mh_add": "Click on the main sewer where a manhole is. Press Esc when done.", "cust_add": "Click in the plan where your point goes."}.get(mode, ""))
        self.view.update()

    def set_point(self, k, w):
        self.st["pts_manual"] = True
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
        self.st["road_lines"] = []
        self.st["main_poly"] = {}
        self.st["main_poly_dxf"] = {}
        self.st["main_line"] = []                         # (the last stand's main is in another frame: it would send every run to the wrong place and make the search slow)
        self._ml_on = False
        self._mn_on = {}
        self.st["underlay"] = []
        self.st["underlay_cat"], self.st["neighbours"] = {}, []
        if points:
            self.st["points"] = points
        self.st["ports"] = {}
        self._to_fields()                                  # the fields must show the new stand before anything reads them back
        if not keep_buildings:
            self.suggest()
        else:
            self.solve_now()
        self.view.fit()

    def load_reference(self, k):
        """a stand from the built-in reference library (used by the checks and tests; the plan itself works on whatever stand you give it)"""
        d = STANDS[k]
        road, street, north = SHEET_DEFAULTS.get(k, ("left", "", 0.0))
        self.st["sheet"] = {"road": road, "street": street, "road_w": "13m", "street_erf": "2246", "stand_no": k, "north": north}
        self.st["frame"] = None
        self.st["pts_manual"] = True                               # the connection points of the built-in stands come from the SG sheets
        self.set_stand(d["corners"], "Blue Hills Ext 120 - stand " + k, under=d["layers"], points=se.default_points(d))

    def nearest_reference(self):
        """the built-in stand most like this one (frontage and area) - shown so you can see what the tool is leaning on"""
        if not STANDS or not self.res:
            return None
        c = self.st["stand"]["corners"]
        fr = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
        ar = abs(se.area(c))
        return min(STANDS, key=lambda k: abs(STANDS[k]["frontage"] - fr) / 5.0 + abs(STANDS[k]["area"] - ar) / 100.0)

    def make_rect(self):
        self.st["pts_manual"] = False
        w, d = self.q_w.value(), self.q_d.value()
        self.set_stand([[0, 0], [w, 0], [w, d], [0, d]], "Rectangle", points={"sewer": [round(w * 0.85, 2), 0.0], "water": [1.5, 0.0], "elec": [round(w / 2, 2), 0.0]})

    def best_sewer_point(self):
        """unless you placed the main sewer connection yourself, put it where the run from the house is shortest, so the pipe never goes round to the far side"""
        st = self.st
        if st.get("pts_manual"):
            return
        c = st["stand"]["corners"]
        L = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
        if L < 3:
            return
        keep = list(st["points"]["sewer"])
        best = None
        ml = se.main_line(st)
        if ml:                                                     # a main that runs through the stand: the shortest run to any point along it
            cand = []                                              # points along the main, only those near the stand (a long main would otherwise be tried point by point)
            for a_, b_ in zip(ml[:-1], ml[1:]):
                n_ = max(2, int(math.hypot(b_[0] - a_[0], b_[1] - a_[1]) / 1.5))
                for i in range(0, n_ + 1):
                    q = [round(a_[0] + (b_[0] - a_[0]) * i / n_, 2), round(a_[1] + (b_[1] - a_[1]) * i / n_, 2)]
                    dd = min(se.seg_dist(q, c[j], c[(j + 1) % len(c)]) for j in range(len(c)))
                    if dd <= 12.0:
                        cand.append((dd, q))
            cand.sort(key=lambda t: t[0])
            cand = [q for _, q in cand[:16]]
            for q in cand:
                st["points"]["sewer"] = q
                try:
                    r = se.solve(st)["sewer"]
                except Exception:
                    continue
                if best is None or r["length"] < best[0] - 0.05:
                    best = (r["length"], q)
            st["points"]["sewer"] = best[1] if best else keep
            return
        for i in range(0, 13):
            x = 0.6 + (L - 1.2) * i / 12.0
            st["points"]["sewer"] = [round(x, 2), 0.0]
            try:
                r = se.solve(st)["sewer"]
            except Exception:
                continue
            if best is None or r["length"] < best[0] - 0.05:
                best = (r["length"], x)
        st["points"]["sewer"] = [round(best[1], 2), 0.0] if best else keep

    def suggest(self):
        self._edited()
        out = se.suggest(self.st)
        self.st["house"].update(out["house"])
        self.st["carport"] = out.get("carport")
        self.best_sewer_point()
        self._to_fields()
        self.solve_now()
        if out.get("relaxed"):
            self.set_hint("The buildings do not fit inside all the building lines on this stand. They are placed as tightly as they go; the checks show by how much.")
            QTimer.singleShot(6000, lambda: self.set_hint(""))

    def from_site_page(self):
        sp = getattr(self.win, "site_page", None)
        if sp is None:
            QMessageBox.information(self, "House placing", "The Building lines tool is not available.")
            return
        v = sp.verts()
        if len(v) < 3:
            QMessageBox.information(self, "House placing", "Draw the stand in the Building lines tool first.")
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
            g = {"cx": round(cx, 2), "cy": round(cy, 2), "w": round(math.hypot(*e0), 2), "d": round(math.hypot(*e1), 2), "rot": round(math.degrees(math.atan2(e0[1], e0[0])), 1)}
            if len(lp) != 4:
                g["poly"] = [[round(q[0], 3), round(q[1], 3)] for q in lp]
                g["rot"] = 0.0
            got.append(g)
        self.st["frame"] = None
        if got:
            self.st["house"] = got[0]
            self.st["carport"] = got[1] if len(got) > 1 else None
        self.set_stand(pts, "From Building lines", keep_buildings=bool(got), points={"sewer": [round(L * 0.85, 2), 0.0], "water": [1.5, 0.0], "elec": [round(L / 2, 2), 0.0]})
        self._to_fields()
        self.solve_now()

    # ---- the gizmo: what the selected thing offers
    def _gizmo_widget(self):
        if getattr(self, "gz", None) is None:
            self.gz = QFrame(self.view)
            self.gz.setObjectName("xaGizmo")
            self.gz.setStyleSheet("#xaGizmo{background:rgba(30,30,34,225);border:1px solid #d6209a;border-radius:8px;} #xaGizmo QLabel{color:#ffffff;font-weight:bold;padding:0 6px;}"
                                  "#xaGizmo QPushButton{padding:3px 9px;min-width:0;}")
            QHBoxLayout(self.gz).setContentsMargins(6, 4, 6, 4)
        return self.gz

    def sync_done(self):
        """a Done button over the plan while you are adding or picking something"""
        v = getattr(self, "view", None)
        if v is None:
            return
        b = getattr(self, "done_btn", None)
        if b is None:
            b = self.done_btn = QPushButton("Done (Esc or right-click)", v)
            b.setStyleSheet("QPushButton{background:#d6209a;color:white;font-weight:bold;padding:5px 14px;border-radius:6px;}")
            b.clicked.connect(lambda: v.finish_mode())
        mp = getattr(self, "mode_panel", None)
        if mp is None:
            mp = self.mode_panel = QFrame(v)
            mp.setStyleSheet("QFrame{background:rgba(30,30,34,225);border:1px solid #d6209a;border-radius:8px;} QPushButton{padding:3px 9px;min-width:0;} QPushButton:checked{background:#d6209a;color:white;}")
            hl = QHBoxLayout(mp)
            hl.setContentsMargins(6, 4, 6, 4)
            self.mode_btns = {}
            for key, text, tip in (("sq", "Square", "The pipe turns 90 degrees to get to your click"), ("free", "Skew", "A straight line at any angle to your click (also: hold Shift)"),
                                   ("h", "Horizontal", "Force the pipe level to your click's x"), ("v", "Vertical", "Force the pipe upright to your click's y"),
                                   ("fh", "Freeform", "Hold the mouse down and draw the pipe freehand; it is kept as straight legs at any angle along your stroke")):
                bt = QPushButton(text)
                bt.setCheckable(True)
                bt.setToolTip(tip)
                bt.clicked.connect(lambda _=False, k=key: self.set_sd_mode(k))
                hl.addWidget(bt)
                self.mode_btns[key] = bt
        sp_ = getattr(self, "snap_panel", None)
        if sp_ is None:
            sp_ = self.snap_panel = QFrame(v)
            sp_.setStyleSheet("QFrame{background:rgba(30,30,34,225);border:1px solid #d6209a;border-radius:8px;} QLabel{color:white;border:0;} QPushButton{padding:3px 9px;min-width:0;} QPushButton:checked{background:#d6209a;color:white;}")
            sl = QHBoxLayout(sp_)
            sl.setContentsMargins(6, 4, 6, 4)
            self.snap_lbl = QLabel("Snap:")
            sl.addWidget(self.snap_lbl)
            self.snap_btns = {}
            for key, text, tip in (("45", "Parallel + 45\u00b0", "Every leg runs parallel, square or 45 degrees to a boundary of the stand"), ("par", "Parallel only", "Snaps only when within 12 degrees of parallel / square to a boundary"), ("free", "Free", "No snapping (also: hold Shift)")):
                bt = QPushButton(text)
                bt.setCheckable(True)
                bt.setToolTip(tip)
                bt.clicked.connect(lambda _=False, k=key: self.set_snap_mode(k))
                sl.addWidget(bt)
                self.snap_btns[key] = bt
            for key, text, tip in (("all", "All walls", "Wall on every boundary"), ("default", "Sides + rear", "The usual: walls along the sides and the rear"), ("nofront", "No front", "Walls on all but the street boundary"), ("none", "No walls", "No walls")):
                bt = QPushButton(text)
                bt.setToolTip(tip)
                bt.clicked.connect(lambda _=False, k=key: self.set_walls(k))
                sl.addWidget(bt)
                bt.setProperty("wallbtn", True)
            for text, tip, fn in (("Wall run", "Place a wall of your own length: click where it starts and where it ends on a boundary", lambda: self.arm("wall_run")),
                                  ("Undo run", "Remove the last wall run", self.undo_wall_run), ("Clear runs", "Remove all the wall runs", self.clear_wall_runs)):
                bt = QPushButton(text)
                bt.setToolTip(tip)
                bt.clicked.connect(lambda _=False, f=fn: f())
                sl.addWidget(bt)
                bt.setProperty("wallbtn", True)
        if v.mode in ("mline_add", "wmain_add", "emain_add", "wall_pick", "wall_run"):
            walls_ = v.mode in ("wall_pick", "wall_run")
            self.snap_lbl.setText("Walls:" if walls_ else "Snap:")
            for i_ in range(sp_.layout().count()):
                w_ = sp_.layout().itemAt(i_).widget()
                if isinstance(w_, QPushButton):
                    w_.setVisible(bool(w_.property("wallbtn")) == walls_)
            for k, bt in self.snap_btns.items():
                bt.setChecked(k == getattr(self, "_snap_mode", "45"))
            sp_.adjustSize()
            sp_.move(max(10, v.width() - sp_.width() - 10), b.height() + 14)
            sp_.show()
            sp_.raise_()
        else:
            sp_.hide()
        if v.mode == "select":
            b.hide()
            mp.hide()
        else:
            b.adjustSize()
            b.move(max(10, v.width() - b.width() - 10), 8)
            b.show()
            b.raise_()
            if v.mode == "sewer_draw":
                for k, bt in self.mode_btns.items():
                    bt.setChecked(k == getattr(self, "_sd_mode", "sq"))
                mp.adjustSize()
                mp.move(max(10, v.width() - mp.width() - 10), b.height() + 14)
                mp.show()
                mp.raise_()
            else:
                mp.hide()

    def refresh_gizmo(self):
        gz = self._gizmo_widget()
        lay = gz.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        sel = self.view.sel
        if not sel:
            gz.hide()
            return

        def add(text, fn, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False: fn())
            lay.addWidget(b)

        if sel[0] in ("house", "carport"):
            r = sel[0]
            lay.addWidget(QLabel(r.capitalize()))
            add("\u21ba 5\u00b0", lambda: self.rotate_by(r, 5), "Turn 5 degrees anticlockwise")
            add("\u21bb 5\u00b0", lambda: self.rotate_by(r, -5), "Turn 5 degrees clockwise")
            add("90\u00b0", lambda: self.rotate_by(r, 90), "Turn a quarter")
            add("Turn precisely...", lambda: self.rotate_dialog(r), "A slider with a live preview")
            lay.addWidget(QLabel("or drag the ring (Shift = 15\u00b0 steps)"))
        elif sel[0] == "point":
            k = sel[1]
            lay.addWidget(QLabel({"sewer": "Sewer connection (end of the line)", "water": "Water connection", "elec": "Electrical connection"}.get(k, "Connection")))
            lay.addWidget(QLabel("drag it along the main line: the run goes to it"))
            if k == "sewer":
                add("Shortest connection", self.sewer_point_auto, "Let the program put it where the run from the house is shortest")
                add("Click it in the plan", lambda: self.arm("pt_sewer"), "Click where the main sewer connection is")
        elif sel[0] == "sport":
            i_ = sel[1]
            lay.addWidget(QLabel("Extra sewer outlet"))
            lay.addWidget(QLabel("drag it along the wall to move it"))
            add("Delete", lambda: self.remove_sport(i_), "Take this outlet off (Delete key)")
            add("Add another", lambda: self.arm("sport_add"), "Click on the house wall where another sewer outlet leaves")
        elif sel[0] == "eye":
            k = sel[1]
            lay.addWidget(QLabel("Rodding eye" if k.startswith("RE") else "Inspection eye"))
            lay.addWidget(QLabel("drag it to move it"))
            add("Delete", lambda: self.delete_eye(k), "Take this eye off the plan (Delete key)")
            add("Eyes back", self.reset_eyes, "Put all the eyes back where the program places them")
        elif sel[0] == "sewer":
            lay.addWidget(QLabel("Sewer line"))
            lay.addWidget(QLabel("drag a leg to slide it; a corner stretches it (Shift = move only that corner); the last square, on the main line, is the connection"))
            add("Draw the sewer", self.sewer_draw_start, "Click the start on the house, each corner, then the main sewer line")
            add("Add a sewer outlet", lambda: self.arm("sport_add"), "Another outlet from the house: click on the wall. It runs square to the sewer run and butts onto it.")
            add("Free bends: " + ("on" if self.st.get("sewer_free") else "off"), self.toggle_free, "On: a corner moves alone and the legs next to it go slanted, everything else stays put")
            add("Eyes back", self.reset_eyes, "Put all the eyes back where the program places them")
            add("Back to automatic", self.sewer_auto, "Throw away your changes and let the program route it")
        elif sel[0] == "label":
            lay.addWidget(QLabel("Text"))
            k = sel[1]
            add("Edit...", lambda: self.edit_text(k), "Change the words (or double-click the text)")
            add("A+", lambda: self.text_style(k, "s", 1.15), "Bigger")
            add("A\u2212", lambda: self.text_style(k, "s", 1 / 1.15), "Smaller")
            add("\u21ba 15\u00b0", lambda: self.text_style(k, "r", -15.0), "Turn anticlockwise")
            add("\u21bb 15\u00b0", lambda: self.text_style(k, "r", 15.0), "Turn clockwise")
            add("Reset", lambda: self.text_reset(k), "Put the words, size, turn and place back")
            if k.startswith("NOTE:"):
                try:
                    lk = self.st["notes"][int(k[5:].split("#")[0])].get("link")
                except Exception:
                    lk = None
                lay.addWidget(QLabel("linked to " + self.link_name(lk)) if lk else QLabel("not linked"))
                add("Unlink" if lk else "Link to nearest", lambda: self.link_note(k, bool(lk)), "A linked text moves with the thing it is linked to")
            add("Delete", lambda: self.delete_text(k), "Take this text off the plan (Delete key). Texts back brings it again.")
        gz.adjustSize()
        gz.move(10, 8)
        gz.show()
        gz.raise_()

    def drag_sewer(self, d, w):
        """move a leg or a corner of the sewer run by hand; everything stays square"""
        P = [list(p) for p in d[2]]
        n = len(P)
        free = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier) or bool(self.st.get("sewer_free")) or any(m_ != "sq" for m_ in (self.st.get("sewer_modes") or []))
        if d[0] == "sv" and free:
            k = d[1]
            P[k] = [w[0], P[k][1] if k == n - 1 else w[1]]
            self.st["sewer_free"] = True
        elif d[0] == "sv":
            k = d[1]
            last = k == n - 1
            nx, ny = w[0], (P[k][1] if last else w[1])
            P[k] = [nx, ny]
            for j in (k - 1, k + 1):
                if 0 < j < n:
                    horizontal = abs(d[2][j][1] - d[2][k][1]) < 1e-3
                    if horizontal:
                        if j != n - 1:
                            P[j][1] = ny
                    else:
                        P[j][0] = nx
        else:
            k, w0 = d[1], d[3]
            a, b = d[2][k], d[2][k + 1]
            if abs(a[1] - b[1]) < 1e-3:                           # a level leg slides up and down
                dy = w[1] - w0[1]
                for j in (k, k + 1):
                    if 0 < j < n - 1:
                        P[j][1] = d[2][j][1] + dy
            else:                                                 # an upright leg slides sideways
                dx = w[0] - w0[0]
                for j in (k, k + 1):
                    if 0 < j:
                        P[j][0] = d[2][j][0] + dx
        self.st["sewer_manual"] = [[round(p[0], 2), round(p[1], 2)] for p in P[1:]]
        if any(m_ != "sq" for m_ in (self.st.get("sewer_modes") or [])):          # what was drawn skew stays skew: every point now stands exactly where it is
            self.st["sewer_free"] = True
            self.st["sewer_modes"] = []

    def delete_sewer_corner(self, k):
        """take one corner (bend) out of the sewer run; the legs either side join straight (slanted if need be)"""
        P = [list(p) for p in self.res["sewer"]["path"]]
        if not (0 < k < len(P) - 1):
            return
        del P[k]
        self.st["sewer_manual"] = [[round(p[0], 2), round(p[1], 2)] for p in P[1:]]
        self.st["sewer_free"] = True
        self.solve_now(False)
        self.commit(True)

    def sewer_point_auto(self):
        self.st["pts_manual"] = False
        self.st["sewer_manual"] = []
        self.best_sewer_point()
        self.solve_now(False)
        self.commit(True)

    def toggle_free(self):
        self.st["sewer_free"] = not self.st.get("sewer_free")
        self.refresh_gizmo()
        self.solve_now()

    # ---- the eyes
    def move_eye(self, key, w):
        q = (w[0], w[1])
        r = self.res["sewer"]
        best = None
        for pp in [r["path"]] + ([r["branch"]] if r.get("branch") else []) + list(r.get("stubs") or []):
            for i in range(len(pp) - 1):
                a, b = pp[i], pp[i + 1]
                dx, dy = b[0] - a[0], b[1] - a[1]
                l2 = dx * dx + dy * dy or 1e-9
                t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / l2))
                c = (a[0] + t * dx, a[1] + t * dy)
                dd = math.hypot(q[0] - c[0], q[1] - c[1])
                if best is None or dd < best[0]:
                    best = (dd, c)
        if best and best[0] < 0.5:
            q = best[1]                                           # on the pipe it sits on the pipe
        self.st.setdefault("eyes", {"del": [], "pos": {}}).setdefault("pos", {})[key] = [round(q[0], 3), round(q[1], 3)]

    def delete_eye(self, key):
        self.set_hint("Every inspection and rodding eye stays: the sewer needs them. Drag one along the pipe to move it.")
        QTimer.singleShot(6000, lambda: self.set_hint(""))
        return
        ed = self.st.setdefault("eyes", {"del": [], "pos": {}})
        ed.setdefault("del", [])
        if key not in ed["del"]:
            ed["del"].append(key)
        ed.setdefault("pos", {}).pop(key, None)
        self.view.set_sel(None)
        self.solve_now(False)
        self.commit(True)

    def reset_eyes(self):
        self.st.pop("eyes", None)
        self.view.set_sel(None)
        self.solve_now(False)
        self.commit(True)

    # ---- texts linked to things
    def link_name(self, lk):
        k = (lk or {}).get("k", "")
        return {"house": "the house", "carport": "the carport", "sewer": "the sewer line"}.get(k, "an eye" if k else "nothing")

    def link_anchor(self, lk):
        return site_sheet.link_anchor(self.st, self.res, lk)

    def nearest_link(self, w):
        res = self.res
        if not res:
            return None
        if res.get("carport") and se.inside(w, res["carport"]):
            return {"k": "carport"}
        if se.inside(w, res["house"]):
            return {"k": "house"}
        best = None
        for nd in res["sewer"]["nodes"]:
            if nd["kind"] in ("IE", "RE") and nd.get("key"):
                dd = math.hypot(nd["pt"][0] - w[0], nd["pt"][1] - w[1])
                if dd < 1.5 and (best is None or dd < best[0]):
                    best = (dd, {"k": "eye", "key": nd["key"]})
        if best:
            return best[1]
        P = res["sewer"]["path"]
        if any(se.line_dist(w, P[i], P[i + 1]) < 1.0 for i in range(len(P) - 1)):
            return {"k": "sewer"}
        return None

    def link_note(self, key, unlink):
        try:
            nt = self.st["notes"][int(key[5:].split("#")[0])]
        except Exception:
            return
        if unlink:
            lk = nt.pop("link", None)
            a = self.link_anchor(lk)
            if a and lk.get("a"):
                nt["pt"] = [round(nt["pt"][0] + a[0] - lk["a"][0], 2), round(nt["pt"][1] + a[1] - lk["a"][1], 2)]
        else:
            lk = self.nearest_link(tuple(nt["pt"]))
            if lk:
                a = self.link_anchor(lk)
                lk["a"] = [round(a[0], 3), round(a[1], 3)]
                nt["link"] = lk
        self.refresh_gizmo()
        self.solve_now(False)
        self.commit(True)

    def sewer_auto(self):
        self.st["sewer_modes"] = []
        self.st["sewer_free"] = False
        self.st["sewer_manual"] = []
        self.st["sewer_via"] = []
        self.solve_now()

    # ---- texts
    def _text_of(self, key):
        ed = (self.st.get("text_edit") or {}).get(key) or {}
        if ed.get("t"):
            return ed["t"]
        if key.startswith("NOTE:"):
            try:
                return self.st["notes"][int(key[5:].split("#")[0])]["t"]
            except Exception:
                return ""
        base = key[4:] if key.startswith("DIM:") else key
        return base.rsplit("#", 1)[0]

    def edit_text(self, key):
        cur = self._text_of(key)
        t, ok = QInputDialog.getText(self, "Edit the text", "Text:", QLineEdit.EchoMode.Normal, cur)
        if not ok:
            return
        if key.startswith("NOTE:"):
            try:
                self.st["notes"][int(key[5:].split("#")[0])]["t"] = t
            except Exception:
                pass
        else:
            self.st.setdefault("text_edit", {}).setdefault(key, {})["t"] = t
        self.solve_now()

    def text_style(self, key, what, f):
        ed = self.st.setdefault("text_edit", {}).setdefault(key, {})
        if what == "s":
            ed["s"] = round(min(max(ed.get("s", 1.0) * f, 0.3), 6.0), 3)
        else:
            ed["r"] = round(ed.get("r", 0.0) + f, 1)
        self.solve_now()

    def delete_text(self, key):
        if key.startswith("NOTE:"):
            self.remove_note(int(key[5:].split("#")[0] or 0))
        else:
            h = self.st.setdefault("text_hidden", [])
            if key not in h:
                h.append(key)
            self.solve_now()
        self.view.set_sel(None)

    def text_reset(self, key):
        h = self.st.get("text_hidden") or []
        if key in h:
            h.remove(key)
        (self.st.get("text_edit") or {}).pop(key, None)
        (self.st.get("labels") or {}).pop(key, None)
        self.solve_now()

    def add_note(self, w):
        t, ok = QInputDialog.getText(self, "Add a text", "Text:")
        if ok and t.strip():
            nt = {"t": t.strip(), "pt": [round(w[0], 2), round(w[1], 2)]}
            lk = self.nearest_link(w)                             # a text put on the house, carport, a sewer eye or the sewer line is linked to it and moves with it
            if lk:
                a = self.link_anchor(lk)
                if a:
                    lk["a"] = [round(a[0], 3), round(a[1], 3)]
                    nt["link"] = lk
            self.st.setdefault("notes", []).append(nt)
            self.solve_now()

    def remove_note(self, k):
        n = self.st.get("notes") or []
        if 0 <= k < len(n):
            n.pop(k)
            for key in [x for x in (self.st.get("labels") or {}) if x.startswith("NOTE:")]:
                self.st["labels"].pop(key, None)
            self.solve_now()

    def snap_point(self, w):
        st = self.st
        cands = [tuple(p) for p in st["stand"]["corners"]]
        if self.res:
            cands += [tuple(p) for p in self.res["house"]] + [tuple(p) for p in (self.res.get("carport") or [])]
            for k in ("sewer", "water", "elec"):
                cands += [tuple(n["pt"]) for n in self.res[k]["nodes"]]
        near = min(cands, key=lambda q: math.hypot(q[0] - w[0], q[1] - w[1]))
        return near if math.hypot(near[0] - w[0], near[1] - w[1]) * self.view.sh.s < 14 else (round(w[0], 3), round(w[1], 3))

    def add_dim_point(self, w):
        st = self.st
        p = self.snap_point(w)
        a = getattr(self, "_dim_a", None)
        if a is None:
            self._dim_a = p
            self.set_hint("Now the second point.")
            return
        self._dim_a = None
        st.setdefault("dims", []).append({"a": [round(a[0], 3), round(a[1], 3)], "b": [round(p[0], 3), round(p[1], 3)], "off": 1.5})
        self.set_hint("Dimension added. Drag its figure to slide it, or click the next first point.")
        self.solve_now()

    def remove_dim(self, k):
        d = self.st.get("dims") or []
        if 0 <= k < len(d):
            d.pop(k)
            for key in [x for x in (self.st.get("labels") or {}) if x.startswith("DIM:u")]:
                self.st["labels"].pop(key, None)
            self.solve_now()

    def set_setting_out(self, on):
        self.st["sheet"]["setting_out"] = bool(on)
        self.solve_now()

    def add_wport(self, w):
        wp = self.st.setdefault("water_ports", [])
        if len(wp) >= 3:
            self.set_hint("The house already has 4 water points.")
            return
        wp.append(se.nearest_port(self.res["house"], w))
        self.solve_now()

    def set_sd_mode(self, k):
        self._sd_mode = k
        self.sync_done()
        self.view.update()

    def sewer_draw_start(self):
        self._sd_on, self._sd, self._sdm, self._sd_mode = False, [], [], "sq"
        self.arm("sewer_draw")
        self.set_hint("Draw the sewer: 1) click on the house wall where the sewer starts (the minimum invert is there), 2) click each corner, 3) click on the main sewer line (or press Done) to finish. "
                      "Square / Skew / Horizontal / Vertical (buttons, or hold Shift for skew) say how the pipe gets to the next click.")
        self.sync_done()

    @staticmethod
    def simplify_path(P, tol=0.3):
        """Douglas-Peucker: a freehand stroke cut down to the few points that keep its shape within `tol` metres"""
        if len(P) < 3:
            return list(P)
        a, b = P[0], P[-1]
        dm, im = -1.0, 0
        for i in range(1, len(P) - 1):
            d = se.line_dist(P[i], a, b) if (a != b) else math.hypot(P[i][0] - a[0], P[i][1] - a[1])
            if d > dm:
                dm, im = d, i
        if dm <= tol:
            return [a, b]
        return SiteServicesPage.simplify_path(P[:im + 1], tol)[:-1] + SiteServicesPage.simplify_path(P[im:], tol)

    def sewer_draw_stroke(self, stroke):
        """a freehand stroke while drawing the sewer: its corner points are added in turn, as skew legs"""
        pts = self.simplify_path([tuple(p) for p in stroke], 0.3)
        for q in pts[1:] if len(pts) > 1 else pts:
            if not getattr(self, "_sd_on", False):
                break
            self.sewer_draw_click(q, True)
        self.view.update()

    def sewer_draw_click(self, w, shift=False):
        if not getattr(self, "_sd_on", False):
            self.st.setdefault("ports", {})["sewer"] = se.nearest_port(self.res["house"], w)
            self.st["sewer_manual"], self.st["sewer_via"], self.st["sewer_free"], self.st["sewer_modes"] = [], [], False, []
            self._sd_on, self._sd, self._sdm = True, [], []
            self.solve_now(False)
            self.set_hint("Now click each corner of the run. Click on the main sewer line to finish (or press Done).")
            return
        mainy = se.mains(self.st)["sewer"]
        mode = "free" if shift else self._sd_mode
        ml_ = se.main_line(self.st)
        if (ml_ and se.main_dist(self.st, w) < 1.2) or (not ml_ and w[1] <= max(0.6, mainy + 1.8)):   # on or near the main line, or past the street boundary: that is the end
            self.sewer_draw_finish(w[0], mode, w[1])
            self.view.finish_mode()
            return
        self._sd.append([round(w[0], 2), round(w[1], 2)])
        self._sdm.append(mode)

    def sewer_draw_finish(self, x=None, mode=None, y=None):
        if not getattr(self, "_sd_on", False):
            return
        self._sd_on = False
        mainy = se.mains(self.st)["sewer"]
        pts = [list(c) for c in self._sd]
        mds = list(self._sdm)
        if x is None:
            x = pts[-1][0] if pts else self.st["points"]["sewer"][0]
        end = se.snap_main(self.st, (x, y if y is not None else (pts[-1][1] if pts else 0.0)))
        end = list(end) if end else [round(x, 2), mainy]
        pts.append(end)
        mds.append(mode or self._sd_mode)
        self.st["sewer_manual"] = pts
        self.st["sewer_modes"] = mds
        self.st["points"]["sewer"] = list(end)
        self.st["pts_manual"] = True
        self._sd = []
        self.solve_now(False)
        self.commit(True)

    def add_sport(self, w):
        sp = self.st.setdefault("sewer_ports", [])
        if len(sp) >= 3:
            self.set_hint("The house already has 4 sewer outlets.")
            return
        sp.append(se.nearest_port(self.res["house"], w))
        self.solve_now(False)
        self.commit(True)

    def remove_sport(self, i):
        sp = self.st.get("sewer_ports") or []
        if 0 <= i < len(sp):
            sp.pop(i)
            self.view.set_sel(None)
            self.solve_now(False)
            self.commit(True)

    def remove_last_wport(self):
        if self.st.get("water_ports"):
            self.st["water_ports"].pop()
            self.solve_now()

    def pick_footprint(self):
        """a house from the footprint library (your footprint drawings)"""
        if not FOOTPRINTS:
            QMessageBox.information(self, "House placing", "The footprint library is not available.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("House from the library")
        v_ = QVBoxLayout(dlg)
        v_.addWidget(QLabel("Footprints from your footprint drawings. The marks (DB, SD, FD, G, KD) come with them: the DB and the sewer outlet are taken from them."))
        row = QHBoxLayout()
        lw = QListWidget()
        for f in FOOTPRINTS:
            lw.addItem("%s   %.1f x %.1f m   %s" % (f["name"], f["w"], f["d"], f["desc"]))
        lw.setCurrentRow(0)
        pv = _FootprintPreview()
        lw.currentRowChanged.connect(lambda i: pv.show_fp(FOOTPRINTS[i] if i >= 0 else None))
        pv.show_fp(FOOTPRINTS[0])
        row.addWidget(lw, 1)
        row.addWidget(pv, 1)
        v_.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v_.addWidget(bb)
        lw.itemDoubleClicked.connect(lambda *_: dlg.accept())
        dlg.resize(760, 380)
        if dlg.exec() == QDialog.DialogCode.Accepted and lw.currentRow() >= 0:
            self.use_footprint(FOOTPRINTS[lw.currentRow()])

    def use_footprint(self, f):
        self.st["house"] = {"poly": [list(p) for p in f["poly"]], "marks": [list(m) for m in f["marks"]], "w": f["w"], "d": f["d"], "rot": 0.0, "cx": 0.0, "cy": 0.0, "name": f["name"]}
        self.st["ports"] = {}
        self.st["water_ports"] = []
        self.st["sewer_ports"] = []
        self._to_fields()
        self.suggest()

    def entry_next(self):
        c = self.st.get("carport")
        if not c:
            return
        c["entry_face"] = (int(c.get("entry_face") or 0) + 1) % 4
        c.pop("entry_x", None)
        self.view.update()
        self.commit(True)

    def set_look(self, key, on):
        if self._busy:
            return
        self.st.setdefault("look", {})[key] = bool(on)
        for cb_ in (self.look_cb.get(key), getattr(self, "tb_walls", None) if key == "walls" else None):
            if cb_ is not None and cb_.isChecked() != bool(on):
                cb_.blockSignals(True)
                cb_.setChecked(bool(on))
                cb_.blockSignals(False)
        self.view.update()
        self.changed()

    def wall_edge_at(self, w, tol=2.5):
        """the stand boundary nearest to a plan point (within tol metres), or None"""
        cs = self.st["stand"]["corners"]
        best, bd = None, tol
        for i in range(len(cs)):
            d = se.seg_dist(w, cs[i], cs[(i + 1) % len(cs)])
            if d < bd:
                best, bd = i, d
        return best

    def wall_run_click(self, w):
        """start / end of a wall run on one boundary; both ends snap to the boundary (and to its corners)"""
        cs = self.st["stand"]["corners"]
        a = getattr(self, "_wr_a", None)
        sn = se.snap_to_edge(cs, w, a[0] if a else None)
        if not sn:
            return
        e, t, _q = sn
        if a is None:
            self._wr_a = (e, t)
        else:
            if abs(t - a[1]) > 1e-3:
                self.st.setdefault("wall_runs", []).append({"edge": e, "t0": round(min(a[1], t), 4), "t1": round(max(a[1], t), 4)})
                self.changed()
            self._wr_a = None
        self.view.update()

    def undo_wall_run(self):
        if self.st.get("wall_runs"):
            self.st["wall_runs"].pop()
            self.view.update()
            self.changed()

    def clear_wall_runs(self):
        self.st.pop("wall_runs", None)
        self._wr_a = None
        self.view.update()
        self.changed()

    def toggle_wall(self, i):
        kinds = se.edge_kinds(self.st["stand"]["corners"])
        we = self.st.setdefault("wall_edges", {})
        we[str(i)] = not se.wall_on(self.st, i, kinds[i])
        self.view.update()
        self.changed()

    def set_walls(self, which):
        """which: 'all', 'none', 'default' (sides and rear), 'nofront' """
        cs = self.st["stand"]["corners"]
        kinds = se.edge_kinds(cs)
        if which == "default":
            self.st.pop("wall_edges", None)
        else:
            self.st["wall_edges"] = {str(i): (which == "all" or (which == "nofront" and kinds[i] != "street")) for i in range(len(cs))}
        self.view.update()
        self.changed()

    def set_snap_mode(self, m):
        self._snap_mode = m
        self.view.update()
        self.sync_done()

    def snap_main(self, w, last, free=False):
        """the point of a drawn main after snapping to the stand's boundary directions (Shift = free)"""
        mode = "free" if free else getattr(self, "_snap_mode", "45")
        if not last:
            return (w[0], w[1]), "start", 0.0, 0.0
        return se.snap_dir(self.st["stand"]["corners"], tuple(last), w, mode)

    def add_mline(self, w):
        if not getattr(self, "_ml_on", False):
            self._ml_on = True
            self.st["main_line"] = []
        ml_ = self.st.get("main_line") or []
        if ml_:
            w = self.snap_main(w, ml_[-1], bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier))[0]
        self.st.setdefault("main_line", []).append([round(w[0], 2), round(w[1], 2)])
        if len(self.st["main_line"]) >= 2:
            self.st["pts_manual"] = False
            self.best_sewer_point()
        self.solve_now()
        self.view.update()

    def add_main(self, k, w):
        """a click of the drawn main water or electrical line: the first click starts a new line (it replaces the one from the drawing), the others add to it"""
        on = getattr(self, "_mn_on", None)
        if on is None:
            on = self._mn_on = {}
        mp = self.st.setdefault("main_poly", {})
        if not on.get(k):
            on[k] = True
            mp[k] = [[]]
        if mp[k][0]:
            w = self.snap_main(w, mp[k][0][-1], bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier))[0]
        mp[k][0].append([round(w[0], 2), round(w[1], 2)])
        if len(mp[k][0]) >= 2:
            self.solve_now(False)
        self.view.update()

    def clear_main(self, k):
        """back to the main as the imported drawing has it (or the straight line along the street)"""
        self._mn_on = {}
        src = (self.st.get("main_poly_dxf") or {}).get(k)
        mp = self.st.setdefault("main_poly", {})
        if src:
            mp[k] = [list(map(list, pl)) for pl in src]
        else:
            mp.pop(k, None)
        self.solve_now()
        self.commit(True)

    def clear_mline(self):
        self.st["main_line"] = []
        self._ml_on = False
        self.st["pts_manual"] = False
        self.solve_now()
        self.commit(True)

    def add_manhole(self, w):
        mh = self.st.setdefault("manholes", [])
        sn = se.snap_main(self.st, w)
        q = list(sn) if sn else [round(w[0], 2), se.mains(self.st)["sewer"]]
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Manhole", "Manhole number or name:", text="MH%d" % (len(mh) + 1))
        if ok and name.strip():
            mh.append({"pt": q, "name": name.strip()})
            self.solve_now(False)
            self.commit(True)

    def rename_manhole(self, i):
        from PySide6.QtWidgets import QInputDialog
        mh = self.st.get("manholes") or []
        if 0 <= i < len(mh):
            name, ok = QInputDialog.getText(self, "Manhole", "Manhole number or name:", text=mh[i].get("name", ""))
            if ok and name.strip():
                mh[i]["name"] = name.strip()
                self.solve_now(False)
                self.commit(True)

    def delete_manhole(self, i):
        mh = self.st.get("manholes") or []
        if 0 <= i < len(mh):
            mh.pop(i)
            self.solve_now(False)
            self.commit(True)

    def turn_storm(self, delta):
        lk = self.st.setdefault("look", {})
        sp, sr = site_sheet.storm_pose(self.st, self.res)
        if sp:
            lk.setdefault("storm_pos", [round(sp[0], 2), round(sp[1], 2)])
        lk["storm_rot"] = 0.0 if delta is None else round((sr + delta) % 360.0, 1)
        self.view.update()
        self.commit(True)

    def reset_storm(self):
        lk = self.st.setdefault("look", {})
        lk.pop("storm_pos", None)
        lk.pop("storm_rot", None)
        self.view.update()
        self.commit(True)

    def remove_manhole(self):
        if self.st.get("manholes"):
            self.st["manholes"].pop()
            self.solve_now(False)
            self.commit(True)

    def add_via(self, w):
        self.st.setdefault("sewer_via", []).append([round(w[0], 2), round(w[1], 2)])
        self.solve_now()

    def clear_via(self):
        self.st["sewer_via"] = []
        self.solve_now()

    def reset_labels(self):
        self.st["labels"] = {}
        self.st["text_hidden"] = []
        self.view.update()
        self.changed()

    # ---- your own points
    def _fill_custom(self):
        self.cu_list.clear()
        for c in self.st.get("custom") or []:
            self.cu_list.addItem("%s - %s  (%.2f, %.2f)" % (c.get("name") or "Point", KINDS.get(c["kind"], "Other"), c["pt"][0], c["pt"][1]))

    def add_custom(self, w):
        n = len(self.st.setdefault("custom", [])) + 1
        kind = self.cu_kind.currentData()
        self.st["custom"].append({"kind": kind, "name": self.cu_name.text().strip() or "%s %d" % (self.cu_kind.currentText(), n), "pt": [round(w[0], 2), round(w[1], 2)]})
        self._fill_custom()
        self.solve_now()

    def remove_custom(self):
        i = self.cu_list.currentRow()
        if 0 <= i < len(self.st.get("custom") or []):
            self.st["custom"].pop(i)
            self._fill_custom()
            self.solve_now()

    # ---- DXF
    def _choose_shape(self, shapes, title, prefer):
        if not shapes:
            QMessageBox.information(self, title, "No closed outlines were found in that drawing. Close the outline (a closed polyline, or lines that meet at their ends).")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Pick the outline:"))
        lw = QListWidget()
        for s_ in shapes:
            xs, ys = [p[0] for p in s_["poly"]], [p[1] for p in s_["poly"]]
            lw.addItem("%.1f m2   %.1f x %.1f m   %d corners   layer %s" % (s_["area"], max(xs) - min(xs), max(ys) - min(ys), len(s_["poly"]), s_["layer"]))
        lw.setCurrentRow(prefer(shapes))
        lw.itemDoubleClicked.connect(lambda *_: dlg.accept())
        v.addWidget(lw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.resize(520, 360)
        if dlg.exec() != QDialog.DialogCode.Accepted or lw.currentRow() < 0:
            return None
        return shapes[lw.currentRow()]

    def _read_dxf(self, path):
        try:
            return site_dxf.read_shapes(path)
        except Exception as e:
            QMessageBox.warning(self, "House placing", str(e))
            return None

    def import_stand_dxf(self, path=None, pick=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import the stand", "", "Drawings (*.dxf *.dwg)")
        if not path:
            return
        if pick is None:
            got = self._dialog(path, "stand")
            if not got:
                return
            poly, under, street = got[:3]
            self.set_stand_world(poly, "Imported stand", src_shapes=[1], street_edge=street)
            xs_, ys_ = [p[0] for p in poly], [p[1] for p in poly]
            self.set_hint("Stand imported at true size: %.2f x %.2f m, %.0f m2." % (max(xs_) - min(xs_), max(ys_) - min(ys_), abs(se.area(poly))))
            QTimer.singleShot(8000, lambda: self.set_hint(""))
            self._set_underlay(under)
            return
        shapes = self._read_dxf(path)
        if shapes is None:
            return
        sh = pick(shapes)
        if sh:
            self.set_stand_world(sh["poly"], "Imported stand", src_shapes=shapes)

    def _dialog(self, path, role):
        try:
            drawing = site_dxf.read_drawing(path)
        except Exception as e:
            QMessageBox.warning(self, "House placing", str(e))
            return None
        try:
            dlg = site_dxf_dialog.ImportDialog(self, drawing, role)
        except Exception as e:
            QMessageBox.warning(self, "House placing", "The drawing could not be shown: %s" % e)
            return None
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return None
        return dlg.result, dlg.underlay(), dlg.street_edge, getattr(dlg, "extras", {})

    # ---- a whole township drawing
    def open_township(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open the township drawing", "", "Drawings (*.dxf *.dwg)")
        if not path:
            return
        import threading
        from PySide6.QtCore import QEventLoop
        tn = site_township.Township()
        box = {"err": None, "done": False}

        def work():
            try:
                tn.load(path)
            except Exception as e:                                  # shown on screen below
                box["err"] = e
            box["done"] = True
        self.set_hint("Reading the township drawing... a big one can take a minute or two.")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        th = threading.Thread(target=work, daemon=True)
        th.start()
        loop = QEventLoop()
        tm = QTimer(self)
        tm.timeout.connect(lambda: loop.quit() if box["done"] else None)
        tm.start(150)
        loop.exec()
        tm.stop()
        QApplication.restoreOverrideCursor()
        self.set_hint("")
        if box["err"]:
            QMessageBox.warning(self, "House placing", "The township drawing could not be read: %s" % box["err"])
            return
        self.tn = tn
        self.tn_layers_b.setEnabled(True)
        self.tn_go.setEnabled(True)
        n_l = sum(1 for v in tn.layers.values() if v["cat"] != "off")
        cats = {}
        for v in tn.layers.values():
            cats[v["cat"]] = cats.get(v["cat"], 0) + 1
        self.tn_lbl.setText("Read %d layers, %d stand outlines, %d texts. Found: %s. Check them with Layers... if a service is missing. Now type a stand number." % (
            len(tn.layers), len(tn.shapes), len(tn.texts), ", ".join("%s %d" % (site_township.CAT_NAMES[c].lower(), n) for c, n in sorted(cats.items()) if c != "off") or "nothing"))
        self.tn_no.setFocus()

    def township_layers(self):
        tn = getattr(self, "tn", None)
        if not tn:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Which layer is which")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("The tool guessed from the layer names. Change any that are wrong, then press OK."))
        tbl = QTableWidget(len(tn.layers), 3)
        tbl.setHorizontalHeaderLabels(["Layer", "Lines", "Is"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        combos = {}
        for r, (name, v) in enumerate(sorted(tn.layers.items(), key=lambda kv: -kv[1]["n"])):
            tbl.setItem(r, 0, QTableWidgetItem(name))
            tbl.setItem(r, 1, QTableWidgetItem(str(v["n"])))
            cb = QComboBox()
            for c in site_township.CATS:
                cb.addItem(site_township.CAT_NAMES[c], c)
            cb.setCurrentIndex(site_township.CATS.index(v["cat"]))
            tbl.setCellWidget(r, 2, cb)
            combos[name] = cb
        tbl.setMinimumSize(560, 360)
        lay.addWidget(tbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tn.set_categories({n: cb.currentData() for n, cb in combos.items()})

    def go_to_stand(self):
        tn = getattr(self, "tn", None)
        no = self.tn_no.text().strip()
        no = site_township.stand_no(no) or no                         # "Erf 2155" and "2155/0" mean 2155
        if not no:
            self.tn_lbl.setText("Type the stand number first.")
            return
        r = None
        if tn:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                r = tn.find(no)
            finally:
                QApplication.restoreOverrideCursor()
        ref = None
        if not r:                                                  # no drawing open (or the number is not in it): the built-in Blue Hills Ext 120 site plan
            r, ref = self._ref_stand(no)
            if not r and not tn:
                self.tn_lbl.setText("Stand %s is not in the built-in Blue Hills Ext 120 plan. Open the township drawing (DXF) to use another one." % no)
                return
        if not r:
            smp = tn.sample_numbers() if tn else []
            self.tn_lbl.setText("Stand %s was not found. Either no text in the drawing says %s, or the lines round it do not close. %sIf the numbers are there, check the stand layers with Layers... (the boundary lines must be on a layer marked Stand boundaries)." % (
                no, no, ("Numbers written in this drawing include: %s. " % ", ".join(smp)) if smp else "No stand numbers were found in the drawing's texts. "))
            return
        self.set_stand_world(r["poly"], "Stand " + no, src_shapes=[1], street_edge=r["street_edge"], north_up=True)
        self._set_township_underlay(r)
        got_c = self._township_connections(r)
        if not r.get("connections"):
            self.solve_now(False)                                      # (the mains read from the drawing change where the lines end)
        self.sh_no.setText(no)
        placed = self._ref_house(ref) if ref and self.tn_house.isChecked() else ""
        c = self.st["stand"]["corners"]
        found = ", ".join(k for k in ("sewer", "water", "elec", "storm") if r["lines"][k])
        self.tn_lbl.setText("Stand %s: %.0f m2, %d corners. %d stands beside it. Services found: %s.%s%s%s" % (
            no, abs(se.area([tuple(p) for p in c])), len(c), len(r["neighbours"]), found or ("none in this plan" if ref else "none (check Layers...)"),
            (" Corner stand: the road is also on side %d; the short frontage is used as the street, and the long side keeps its own %.1f m building line." % (r["corner"][0] + 1, (self.st["stand"].get("setbacks") or {}).get("side", 1.0))) if r.get("corner") else "",
            "" if r["road_known"] else " No road layer was found, so the street side is a guess: click the real street boundary in the plan.",
            " %d texts said %s; the first was used." % (r["matches"], no) if r["matches"] > 1 else "") + got_c + placed)
        self.set_hint("")

    def _ref_stand(self, no):
        """a stand of the built-in site plan (site_township_ref): -> (a result like Township.find gives, the stand's reference data) or (None, None)"""
        try:
            import site_township_ref as ref
        except Exception:
            return None, None
        for name, stands in ref.TOWNSHIPS.items():
            d = stands.get(no)
            if not d:
                continue
            nbs = [{"poly": [tuple(p) for p in stands[n]["poly"]], "no": n} for n in d.get("nb", []) if n in stands and n != no]
            conn = {k: {"pt": (v[3], v[4]), "label": v[2]} for k, v in d.get("conn", {}).items() if len(v) >= 5}
            P_ = [tuple(p) for p in d["poly"]]
            lines = site_township.ref_lines(name, P_)                    # the road and the services of the site plan, kept with the program
            lines, tris = site_township.Township.strip_symbols(lines)
            corner = [i for i in site_township.Township.side_streets(P_, d["street"], lines) if not any(
                site_township._seg_dist(((P_[i][0] + P_[(i + 1) % len(P_)][0]) / 2, (P_[i][1] + P_[(i + 1) % len(P_)][1]) / 2), o["poly"][j], o["poly"][(j + 1) % len(o["poly"])]) < 0.4
                for o in nbs for j in range(len(o["poly"])))]
            r = {"no": no, "poly": P_, "neighbours": nbs, "lines": lines, "street_edge": d["street"], "corner": corner,
                 "road_known": True, "connections": conn, "matches": 1, "label": None, "ref": name}
            return r, d
        return None, None

    def _ref_house(self, d):
        """the house and carport as they are on the site plan, put on the stand (in the stand's own frame); -> a sentence for the status line"""
        h, cp = d.get("house"), d.get("carport")
        if not h or h.get("rot"):
            return " (This stand has no house on the site plan that fits a straight box, so the house is placed by the tool.)" if h else " (No house is drawn on this stand in the site plan, so the house is placed by the tool.)"
        if h["d"] >= h["w"]:
            self.st["house"].update({"cx": h["cx"], "cy": h["cy"], "w": h["d"], "d": h["w"], "rot": 90})
        else:
            self.st["house"].update({"cx": h["cx"], "cy": h["cy"], "w": h["w"], "d": h["d"], "rot": 0})
        self.st["house"].pop("poly", None)
        self.st["house"].pop("marks", None)
        if cp and not cp.get("rot"):
            self.st["carport"] = {"cx": cp["cx"], "cy": cp["cy"], "w": cp["w"], "d": cp["d"], "rot": 0}
        self.st["ports"] = {}
        self._to_fields()
        self.solve_now(False)
        return " House as on the site plan: %s, carport %.0f x %.0f m." % (h.get("type", "house"), cp["w"] if cp else 0, cp["d"] if cp else 0)

    def set_turn(self, t, quiet=False):
        """turn the plan on the page to t degrees (clockwise); the north arrow follows, north itself stays where it is"""
        st = self.st
        t = round(((t + 180.0) % 360.0) - 180.0, 1)
        road = (st.get("sheet") or {}).get("road", "left")
        nw = st.get("north_world")
        st["sheet"]["turn"] = t
        self._busy = True
        self.sh_turn.setValue(t)
        if nw:
            deg = round(se.north_world_to_screen(nw, road, t), 1)
            st["sheet"]["north"] = deg
            self.sh_north.setValue(deg)
        self._busy = False
        if not quiet:
            self.view.update()
        return t

    def square_up(self, quiet=False):
        """turn the plan on the page so the stand's edges run along it, and let the north arrow follow"""
        road = (self.st.get("sheet") or {}).get("road", "left")
        t = self.set_turn(site_sheet.square_turn([tuple(p) for p in self.st["stand"]["corners"]], road), quiet=True)
        if not quiet:
            self.view.fit()
            self.view.update()
        return t

    def _township_north(self):
        """north on the drawing is up the page (+y of the survey coordinates): turn it into the stand's frame, set the arrow and let the house placement use it"""
        fr = self.st.get("frame")
        if not fr:
            return
        nx, ny = site_township.Township.NORTH
        v = (fr[0] * nx - fr[1] * ny, fr[1] * nx + fr[0] * ny)       # north turned into the stand's frame
        road = (self.st.get("sheet") or {}).get("road", "left")
        turn = (self.st.get("sheet") or {}).get("turn", 0.0) or 0.0
        self._busy = True
        self.sh_north.setValue(round(se.north_world_to_screen(v, road, turn), 1))
        self._busy = False
        self.st["north_world"] = [round(v[0], 4), round(v[1], 4)]
        self.st["sheet"]["north"] = round(se.north_world_to_screen(v, road, turn), 1)

    def _township_connections(self, r):
        """the electrical and water connection symbols on the street boundary become the connection points (the water one by the shared-boundary rule
        of the data set); -> a sentence for the status line"""
        fr = self.st.get("frame")
        if not fr:
            return ""
        cons = dict(r.get("connections") or {})
        L = abs(self.st["stand"]["corners"][1][0] - self.st["stand"]["corners"][0][0])
        said = []
        nbx = [(nb_.get("c") or (0, 0))[0] for nb_ in self.st.get("neighbours") or []]
        for kind, c in cons.items():
            q = se.apply_frame(fr, c["pt"])
            x = max(0.3, min(L - 0.3, q[0]))
            if kind == "water":                                  # two adjacent stands share one water connection, split on their common boundary
                x, side_ = site_plans_data.water_pair_x(L, x, nbx)
                self.st["water_pair"] = side_
            self.st["points"][kind] = [round(x, 2), 0.0]
            said.append("%s connection%s at %.1f m along the street" % ("electrical" if kind == "elec" else "water", (" " + c["label"]) if c.get("label") else "", x))
        if "water" not in cons and nbx:                          # no water mark in the drawing: the rule still puts it on the shared boundary
            x, side_ = site_plans_data.water_pair_x(L, None, nbx)
            self.st["water_pair"] = side_
            self.st["points"]["water"] = [x, 0.0]
            said.append("water connection on the boundary shared with the %s neighbour" % side_)
        if not said:
            return ""
        self.st["ports"] = {}
        self.solve_now(False)
        self._to_fields()
        return " Set from the drawing: " + "; ".join(said) + "."

    def _set_township_underlay(self, r):
        """the township's lines and the neighbouring stands, moved into the stand's frame and kept faint under the plan"""
        fr = self.st.get("frame")
        cats = {"sewer": [], "water": [], "elec": [], "storm": [], "other": []}
        if not fr:
            self.under = {}
            self.st["underlay"], self.st["underlay_cat"], self.st["neighbours"] = [], {}, []
            return
        cs = self.st["stand"]["corners"]
        xs, ys = [p[0] for p in cs], [p[1] for p in cs]
        R_ = site_township.SERVICE_REACH
        x0, x1, y0, y1 = min(xs) - R_, max(xs) + R_, min(ys) - R_, max(ys) + R_

        def mv(seg, thick=0):
            p, q = se.apply_frame(fr, (seg[0], seg[1])), se.apply_frame(fr, (seg[2], seg[3]))
            if max(p[0], q[0]) < x0 or min(p[0], q[0]) > x1 or max(p[1], q[1]) < y0 or min(p[1], q[1]) > y1:
                return None
            return [round(p[0], 2), round(p[1], 2), round(q[0], 2), round(q[1], 2), thick]
        for cat, key in (("sewer", "sewer"), ("water", "water"), ("elec", "elec"), ("storm", "storm"), ("road", "other")):                    # (lines on layers that are none of these, such as house drawings, stay out)
            for seg in r["lines"].get(cat, []):
                if cat == "road":
                    continue                                  # (the road is drawn in full as road_lines)
                m = mv(seg)
                if m:
                    cats[key].append(m)
        own = []
        nbs = []
        for o in r["neighbours"]:
            Q = o["poly"]
            for i in range(len(Q)):
                m = mv((Q[i][0], Q[i][1], Q[(i + 1) % len(Q)][0], Q[(i + 1) % len(Q)][1]), 1)
                if m:
                    own.append(m)
            cen = se.apply_frame(fr, site_township.centroid(Q))
            if o.get("no"):
                nbs.append({"no": o["no"], "c": [round(cen[0], 2), round(cen[1], 2)]})
        cats["other"] += own
        rl = []
        for g in r["lines"].get("road", []):
            p_, q_ = se.apply_frame(fr, (g[0], g[1])), se.apply_frame(fr, (g[2], g[3]))
            rl.append([p_[0], p_[1], q_[0], q_[1]])
        R = site_township.ROAD_REACH
        self.st["road_lines"] = self._clip_all(rl, min(xs) - R, max(xs) + R, min(ys) - R, max(ys) + R)
        self._township_mains(r, fr)
        self.st["underlay"] = own                                       # the boundaries beside the stand (the house placing reads these)
        self.st["underlay_cat"] = cats
        self.st["neighbours"] = nbs
        self.under = cats
        self.view.update()

    def _township_mains(self, r, fr):
        """the main sewer, water and electrical lines of the drawing nearest the stand's street boundary, drawn as they run and used as the lines the house connects to"""
        c = self.st["stand"]["corners"]
        ref = ((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
        self.st["main_poly"] = {}
        self.st["main_poly_dxf"] = {}
        self.st["main_line"] = []
        said = []
        for cat, k in (("sewer", "sewer"), ("water", "water"), ("elec", "elec")):
            segs = []
            for g in r["lines"].get(cat, []):
                p_, q_ = se.apply_frame(fr, (g[0], g[1])), se.apply_frame(fr, (g[2], g[3]))
                segs.append((p_[0], p_[1], q_[0], q_[1]))
            if k == "sewer":
                pl = site_township.main_chain(segs, ref, reach=site_plans_data.TOWNSHIP_SEARCH["main"])
                if not pl:
                    continue
                self.st["main_line"] = [[round(x, 2), round(y, 2)] for x, y in pl]
            else:
                runs = site_township.main_runs(segs, ref, reach=site_plans_data.TOWNSHIP_SEARCH["main"])               # the main with its branches, as they run in the drawing
                if not runs:
                    continue
                self.st["main_poly"][k] = [[[round(x, 2), round(y, 2)] for x, y in r_] for r_ in runs]
            said.append(k)
        self.st["main_poly_dxf"] = {k_: [list(map(list, pl)) for pl in v_] for k_, v_ in self.st["main_poly"].items()}
        return said

    @staticmethod
    def _clip_all(segs, x0, x1, y0, y1):
        """segments [x1, y1, x2, y2] cut to the window (Liang-Barsky); the ones outside are left out"""
        out = []
        for a, b, c, d in segs:
            t0, t1 = 0.0, 1.0
            dx, dy = c - a, d - b
            ok = True
            for p_, q_ in ((-dx, a - x0), (dx, x1 - a), (-dy, b - y0), (dy, y1 - b)):
                if abs(p_) < 1e-12:
                    if q_ < 0:
                        ok = False
                        break
                else:
                    r_ = q_ / p_
                    if p_ < 0:
                        t0 = max(t0, r_)
                    else:
                        t1 = min(t1, r_)
            if ok and t0 < t1:
                out.append([round(a + t0 * dx, 2), round(b + t0 * dy, 2), round(a + t1 * dx, 2), round(b + t1 * dy, 2)])
        return out

    def _set_underlay(self, lines):
        """the imported drawing's own lines, kept faint under the plan, moved into the stand frame"""
        fr = self.st.get("frame")
        if not lines or not fr:
            self.st["underlay"] = []
            self.under = {}
            return
        c = self.st["stand"]["corners"]
        xs, ys = [p[0] for p in c], [p[1] for p in c]
        x0, x1, y0, y1 = min(xs) - 40, max(xs) + 40, min(ys) - 40, max(ys) + 40
        out = []
        for a, b, c_, d_ in lines:
            p, q = se.apply_frame(fr, (a, b)), se.apply_frame(fr, (c_, d_))
            if max(p[0], q[0]) < x0 or min(p[0], q[0]) > x1 or max(p[1], q[1]) < y0 or min(p[1], q[1]) > y1:
                continue
            out.append([round(p[0], 2), round(p[1], 2), round(q[0], 2), round(q[1], 2), 0])
        self.st["underlay"] = out
        self.under = {"other": out}
        self.view.update()

    def set_stand_world(self, poly, name="Stand", src_shapes=None, street_edge=None, north_up=False):
        """a stand in drawing coordinates: put the street edge along x at the origin and remember the move so the house and carport from the same drawing land in place"""
        self.st["pts_manual"] = False
        self.st["road_lines"] = []                                    # (the township import fills these in again)
        self.st["main_poly"] = {}
        self.st["main_poly_dxf"] = {}
        c0 = [tuple(p) for p in poly]
        if max(max(p[0] for p in c0) - min(p[0] for p in c0), max(p[1] for p in c0) - min(p[1] for p in c0)) > 2000:
            QMessageBox.warning(self, "House placing", "That stand is more than 2 km across, so the scale must be wrong. Import again and set the drawing units and scale.")
            return
        c = se.clean_corners(c0)
        n = len(c)
        if street_edge is not None and street_edge < len(c0):     # the side you clicked, found again after the corners were tidied
            a_, b_ = c0[street_edge], c0[(street_edge + 1) % len(c0)]
            mid = ((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2)
            street_edge = min(range(n), key=lambda i: se.line_dist(mid, c[i], c[(i + 1) % n]))
        if street_edge is None:
            street_edge = min(range(n), key=lambda i: (c[i][1] + c[(i + 1) % n][1]) / 2)
        frame, new = se.normalise_stand(c, street_edge)
        old = self.st.get("frame")
        self.st["frame"] = se.compose_frames(old, frame) if (old and street_edge is not None and src_shapes is None) else frame
        self.st["stand"]["setbacks"] = self.st["stand"].get("setbacks")
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        self._src_bbox = (min(xs), min(ys), max(xs), max(ys))
        self.set_stand(new, name, points=None, keep_buildings=False)
        L = math.hypot(new[1][0] - new[0][0], new[1][1] - new[0][1])
        self.st["points"] = {"sewer": [round(L * 0.85, 2), 0.0], "water": [round(min(1.5, L / 3), 2), 0.0], "elec": [round(L / 2, 2), 0.0]}
        self.st["custom"] = []
        if north_up:                                               # a site plan: north is up the drawing, so the house placement knows where the sun is
            road_ = (self.st.get("sheet") or {}).get("road", "left")
            self.st["sheet"]["turn"] = site_sheet.square_turn([tuple(p) for p in self.st["stand"]["corners"]], road_)    # and the stand sits square on the page
            self._busy = True
            self.sh_turn.setValue(self.st["sheet"]["turn"])
            self._busy = False
            self._township_north()
        self._to_fields()
        self.suggest()

    def set_street_edge(self, w):
        """a click on a boundary: that boundary becomes the street"""
        c = [tuple(p) for p in self.st["stand"]["corners"]]
        n = len(c)
        i = min(range(n), key=lambda i: se.line_dist(w, c[i], c[(i + 1) % n]))
        if i == 0:
            return
        frame, new = se.normalise_stand(c, i)
        self.st["frame"] = se.compose_frames(self.st.get("frame"), frame)
        mv = lambda p: se.apply_frame(frame, p)
        for k in ("house", "carport"):
            o = self.st.get(k)
            if o:
                o["cx"], o["cy"] = [round(v, 2) for v in mv((o["cx"], o["cy"]))]
                o["rot"] = round((o.get("rot", 0) + frame[6]) % 360, 2)
        self.st["stand"]["corners"] = [[round(a, 2), round(b, 2)] for a, b in new]
        L = math.hypot(new[1][0] - new[0][0], new[1][1] - new[0][1])
        self.st["points"] = {"sewer": [round(L * 0.85, 2), 0.0], "water": [round(min(1.5, L / 3), 2), 0.0], "elec": [round(L / 2, 2), 0.0]}
        self.st["ports"] = {}
        self._to_fields()
        self.solve_now()
        self.view.fit()

    def import_building_dxf(self, role, path=None, pick=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import the %s" % role, "", "Drawings (*.dxf *.dwg)")
        if not path:
            return
        if pick is None:
            got = self._dialog(path, role)
            if not got:
                return
            poly = [tuple(p) for p in got[0]]
            marks_in = (got[3] or {}).get("marks") if len(got) > 3 else None
        else:
            marks_in = None
            shapes = self._read_dxf(path)
            if shapes is None:
                return
            sh = pick(shapes)
            if not sh:
                return
            poly = [tuple(p) for p in sh["poly"]]
        fr = self.st.get("frame")
        bb = getattr(self, "_src_bbox", None)
        cxy = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
        placed = bool(fr and bb and bb[0] <= cxy[0] <= bb[2] and bb[1] <= cxy[1] <= bb[3])
        if placed:
            poly = [se.apply_frame(fr, p) for p in poly]
            if marks_in:
                marks_in = [[m[0], *se.apply_frame(fr, (m[1], m[2]))] for m in marks_in]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        o = {"poly": [[round(a, 3), round(b, 3)] for a, b in poly], "w": round(max(xs) - min(xs), 2), "d": round(max(ys) - min(ys), 2), "rot": 0.0,
             "cx": round((max(xs) + min(xs)) / 2, 2), "cy": round((max(ys) + min(ys)) / 2, 2)}
        if not placed:
            c = self.st["stand"]["corners"]
            o["cx"], o["cy"] = round(sum(p[0] for p in c) / len(c), 2), round(sum(p[1] for p in c) / len(c), 2)
        if role == "house" and marks_in:
            o["marks"] = [[m[0], round(m[1], 3), round(m[2], 3)] for m in marks_in]
        self.st["house" if role == "house" else "carport"] = o
        self.set_hint("%s imported at true size: %.2f x %.2f m.%s" % (role.capitalize(), o["w"], o["d"],
                      (" Marks taken from the drawing: " + ", ".join(sorted({m[0] for m in marks_in})) + ".") if role == "house" and marks_in else ""))
        QTimer.singleShot(8000, lambda: self.set_hint(""))
        self.st["ports"] = {}
        self._to_fields()
        if not placed:
            self.suggest()
        else:
            self.solve_now()
        self.view.fit()

    def plain_rect(self, role):
        o = self.st.get(role)
        if o and o.get("poly"):
            o.pop("poly")
            o.pop("marks", None)
            o["rot"] = 90 if role == "house" else 0
            self._to_fields()
            self.solve_now()

    # ---- turning
    def rotate_dialog(self, role):
        o = self.st.get(role)
        if not o:
            return

        def apply(a, o=o):
            o["rot"] = round(a, 2)
            self._to_fields()
            self.solve_now()
        RotateDialog(self, "Rotate the %s" % role, o.get("rot", 0.0), apply).exec()

    def rotate_by(self, role, deg):
        o = self.st.get(role)
        if o:
            o["rot"] = round((o.get("rot", 0.0) + deg) % 360, 2)
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
        if self.st.get("underlay"):
            self.under = {"other": self.st["underlay"]}
        if self.st.get("underlay_cat"):
            self.under = self.st["underlay_cat"]
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
        w_m, h_m = site_sheet.page_extent(x0, y0, x1, y1, road, self.st["sheet"].get("turn", 0.0))
        s200 = 5.0 * dpi / 25.4                                  # pixels per metre at 1:200
        fit = min(W * 0.92 / w_m, H * 0.80 / h_m)
        s = min(s200, fit)
        scale_txt = "1:200" if s >= s200 - 1e-6 else "1:%d" % round(200 * s200 / s / 10) * 1 if False else ("1:200" if s >= s200 - 1e-6 else "1:%d" % int(round(200 * s200 / s / 50.0) * 50))
        sh = site_sheet.Sheet(s, ((x0 + x1) / 2, (y0 + y1) / 2), (W, H * 0.92), road, self.st["sheet"].get("turn", 0.0))
        p.save()
        site_sheet.draw(p, sh, self.st, self.res, self.sheet_opts(), minpx=5)
        r_px = max(s * 1.5, 18)
        site_sheet.north_arrow(p, self.north_centre(W, H, r_px, False), r_px, self.st["sheet"].get("north", 0))
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

    def save_dxf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the plan as DXF", "site_services.dxf", "DXF (*.dxf)")
        if path:
            import site_export
            site_export.build_sheet(self, path)

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
