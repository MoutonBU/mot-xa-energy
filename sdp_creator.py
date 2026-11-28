"""SDP Creator: the Site Development Plan for council. It is Building lines and House placing in one tool, made for the SDP:
load the survey (DXF, DWG or PDF) under the plan, set the stand and its building lines, place the buildings (blocks) by their footprints, then draw
the parking areas round them. The tool fills an area with bays (2.5 x 5.0 m, with the 7 m aisle in front to reverse out), keeps every bay 0.5 m
clear of the buildings and checks each bay against the rules. A schedule of the blocks and one PDF sheet finish it.
The stand, buildings, survey, rotation, north arrow and footprints are Building lines' own (site_lines.SitePage); this file adds the parking."""
import copy
import json
import math
import time

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF
from PySide6.QtWidgets import (QMenu, QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

import sdp_knowledge as kb
import sdp_parking as sp
import site_lines as sl
import tool_base as tb
from flow_layout import FlowLayout
from site_lines import PlanView, SitePage, bpoly, signed_area

TYPES = kb.module_names() + ["Gatehouse", "Other"]
COLS = ["Block", "Phase", "Type", "Storeys", "Units", "Unit area m2", "Patio m2", "Common m2", "Footprint m2", "Floor area m2", "Counts"]
# South African parking standards the tool can apply. Sources: City of Cape Town zoning scheme (bay 5 x 2.5 m, parallel 6 x 2.5 m, accessible 3.7 x 5 m, group housing and flats 1.75 bays + 0.25 visitor
# bays per unit), Mangaung land use scheme (bay 2.5 x 5.0 m, aisle 7.5 m, accessible 3.5 m, 0.5 visitor bay per unit, 1.5 bays for 3 habitable rooms), South African parking standards (aisle 5.4 m at 60
# degrees, 5.2 m at 45 degrees).
STANDARDS = {"My rules (7 m aisle)": None,
             "City of Cape Town": {"w": 2.5, "l": 5.0, "aisle": 7.0, "par_l": 6.0, "ada_w": 3.7, "bays_per_unit": 1.75, "visitor_per": 4},
             "Mangaung (Free State)": {"w": 2.5, "l": 5.0, "aisle": 7.5, "par_l": 6.0, "ada_w": 3.5, "bays_per_unit": 1.5, "visitor_per": 2}}
BAY_TYPES = ["Open", "Covered", "Garage", "Shade cloth", "Tandem", "Compact", "Accessible", "EV"]
BAY_COL = {"Open": (46, 158, 91), "Covered": (74, 127, 181), "Garage": (196, 140, 50), "Shade cloth": (60, 170, 170), "Tandem": (230, 160, 90), "Compact": (120, 150, 210), "Accessible": (40, 90, 220), "EV": (150, 80, 200)}
SCALES = ["1:200", "1:250", "1:500", "1:1000", "1:1250", "1:2000"]


def _num(x, d=0.0):
    return tb.num(x, d)


def blank_site():
    return {"project": "", "township": "", "owner": "", "drawing": "SDP-01", "scale": "1:500", "date": time.strftime("%Y-%m-%d"),
            "max_density": 0.0, "bays_per_unit": 1.5, "visitor_per": 0, "extra_bays": 0, "walkways": 0.0, "roads": 0.0, "notes": ""}


def blank_block(name="", phase="Phase 1", typ="Standard 3-storey", storeys=3, units=0, foot=0.0, floor=0.0, cov=True, unit_m2=0.0, patio=0.0, common=0.0):
    return {"block": name, "phase": phase, "type": typ, "storeys": storeys, "units": units, "foot": foot, "floor": floor, "cov": cov, "unit_m2": unit_m2, "patio": patio, "common": common}


def preset_block(name, typ, phase="Phase 1"):
    """a block of a known module, with the units and areas of the reference plan; the footprint comes from the plan"""
    m = kb.module_preset(typ)
    if not m:
        return blank_block(name, phase, typ)
    return blank_block(name, phase, typ, m["storeys"], m["units"], 0.0, m["gross_m2"], True, m["unit_m2"], m["patio_m2"], m["common_m2"])


def analyse(site, blocks, stand_area, cov_area=None, plan_bays=None, max_cov=0.0, max_far=0.0):
    """Totals per phase and for the whole development, and each check against the limits that were typed in (0 = no limit).
    cov_area: the area the buildings cover on the plan (when there are buildings); plan_bays: the bays placed on the plan."""
    area = float(stand_area or 0)
    phases = {}
    for b in blocks:
        p = phases.setdefault(b.get("phase") or "Phase 1", {"blocks": 0, "units": 0, "foot": 0.0, "floor": 0.0, "unit_m2": 0.0, "patio": 0.0, "common": 0.0})
        p["blocks"] += 1
        p["units"] += int(_num(b.get("units")))
        p["foot"] += _num(b.get("foot"))
        p["floor"] += _num(b.get("floor"))
        for k_ in ("unit_m2", "patio", "common"):
            p[k_] += _num(b.get(k_))
    tot = {k: sum(p[k] for p in phases.values()) for k in ("blocks", "units", "foot", "floor", "unit_m2", "patio", "common")}
    cov_foot = cov_area if cov_area is not None else sum(_num(b.get("foot")) for b in blocks if b.get("cov", True))
    bays = int(plan_bays) if plan_bays else int(_num(site.get("extra_bays")))
    cov = 100.0 * cov_foot / area if area else 0.0
    far = tot["floor"] / area if area else 0.0
    dens = tot["units"] / (area / 10000.0) if area else 0.0
    need = sp.required(tot["units"], _num(site.get("bays_per_unit"), 1.0), max(0, int(_num(site.get("visitor_per")))))
    md = _num(site.get("max_density"))
    checks = [("Coverage", "%.1f %%" % cov, ("%.1f %%" % max_cov) if max_cov else "no limit", (not max_cov) or cov <= max_cov + 1e-6),
              ("Floor area ratio", "%.2f" % far, ("%.2f" % max_far) if max_far else "no limit", (not max_far) or far <= max_far + 1e-6),
              ("Density", "%.1f units/ha" % dens, ("%.1f units/ha" % md) if md else "no limit", (not md) or dens <= md + 1e-6),
              ("Parking bays", "%d provided" % bays, "%d required" % need, bays >= need)]
    for p_ in phases.values():
        p_["bays_needed"] = sp.required(p_["units"], _num(site.get("bays_per_unit"), 1.0), max(0, int(_num(site.get("visitor_per")))))
    return {"area": area, "phases": phases, "total": tot, "cov": cov, "far": far, "density": dens, "bays": bays, "bays_needed": need, "checks": checks,
            "ok": all(c[3] for c in checks)}


def kind_of(name):
    """what a building on the plan is, from its name: Refuse..., Gatehouse..., or a block"""
    n = (name or "").strip().lower()
    if n.startswith(("refuse", "bin ", "waste", "garbage")):
        return "refuse"
    if n.startswith("gate"):
        return "gate"
    return "block"


def block_names(prefix, first, last):
    return ["%s%d" % (prefix, i) for i in range(first, last + 1)]


class _BlocksDialog(QDialog):
    """add a run of blocks to the schedule in one go: H1 to H26, which phase, which type"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add several blocks")
        f = QFormLayout(self)
        self.prefix = QLineEdit("H")
        self.first, self.last = QSpinBox(), QSpinBox()
        for s, v in ((self.first, 1), (self.last, 14)):
            s.setRange(1, 999)
            s.setValue(v)
        self.phase = QLineEdit("Phase 1")
        self.typ = QComboBox()
        self.typ.addItems(TYPES)
        self.typ.setCurrentIndex(1)
        self.units = QSpinBox()
        self.units.setRange(0, 999)
        self.units.setValue(4)
        self.typ.currentTextChanged.connect(self._type)
        self._type(self.typ.currentText())
        f.addRow("Name starts with", self.prefix)
        f.addRow("From number", self.first)
        f.addRow("To number", self.last)
        f.addRow("Phase", self.phase)
        f.addRow("Type", self.typ)
        f.addRow("Units in each block", self.units)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _type(self, t):
        m = kb.module_preset(t)
        if m:
            self.units.setValue(m["units"])

    def blocks(self):
        lo, hi = self.first.value(), max(self.first.value(), self.last.value())
        out = []
        for nm in block_names(self.prefix.text().strip() or "H", lo, hi):
            b = preset_block(nm, self.typ.currentText(), self.phase.text().strip() or "Phase 1")
            b["units"] = self.units.value()
            out.append(b)
        return out


class _GenerateDialog(QDialog):
    """Generate a layout: which block, how many (or as many as the parking allows), and the room between blocks"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Generate a layout")
        f = QFormLayout(self)
        intro = QLabel("The tool places the blocks inside the building lines in rows, then fills what is left with parking bays. "
                       "Blocks it made before (named H1, H2 ...) are replaced; blocks you placed yourself stay.")
        intro.setWordWrap(True)
        intro.setMinimumWidth(420)
        f.addRow(intro)
        self.typ = QComboBox()
        self.typ.addItems(kb.module_names()[:3])
        self.typ.currentTextChanged.connect(self._type)
        f.addRow("Block type", self.typ)
        self.prefix = QLineEdit("H")
        f.addRow("Names start with", self.prefix)
        self.phase = QLineEdit("Phase 1")
        f.addRow("Phase", self.phase)
        self.w, self.d = sl.spin(3, 80, 20, 1, " m"), sl.spin(3, 80, 12, 1, " m")
        f.addRow("Block width", self.w)
        f.addRow("Block depth", self.d)
        self.side = sl.spin(0, 40, 6, 1, " m")
        self.front = sl.spin(0, 60, 17.5, 1, " m")
        self.side.setToolTip("Between two blocks in a row.")
        self.front.setToolTip("Between rows of blocks: room for a double row of bays on the 7 m aisle (5.5 + 7 + 5.5 = 18).")
        f.addRow("Space between blocks in a row", self.side)
        f.addRow("Space between rows (for parking)", self.front)
        self.mode = QComboBox()
        self.mode.addItems(["As many blocks as the parking allows", "This many blocks"])
        self.mode.currentIndexChanged.connect(lambda i: self.count.setEnabled(i == 1))
        f.addRow("How many", self.mode)
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setValue(6)
        self.count.setEnabled(False)
        f.addRow("Number of blocks", self.count)
        self.parking = QCheckBox("Fill the rest with parking bays")
        self.parking.setChecked(True)
        f.addRow(self.parking)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._type(self.typ.currentText())

    def _type(self, t):
        m = kb.module_preset(t)
        if m:
            area = m["gross_m2"] / float(m["storeys"])          # one floor of the block
            w = round(math.sqrt(area * 2.2), 1)
            self.w.setValue(w)
            self.d.setValue(round(area / w, 1))


# ---------------------------------------------------------------- the plan
class _NoWheel(QObject):
    """a number box changes with the mouse wheel only while you are typing in it: scrolling the page must never change the aisle or a bay size"""
    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.Wheel and not o.hasFocus():
            e.ignore()
            return True
        return False


class ParkView(PlanView):
    """Building lines' plan, with the parking drawn over it: the areas, the aisles, the bays (red when one breaks a rule)."""

    def draw(self, p, W, H, v=None, snapshot=False):
        v = v or self.current_view(W, H)
        super().draw(p, W, H, v=v, snapshot=snapshot)
        try:
            self.page.draw_parking(p, W, H, v, snapshot)
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            w = self._world(e.position())
            if w is not None:
                pg = self.page
                if self.mode == "add_bay":
                    pg.add_bay_at(w)
                    return
                if self.mode == "select" and not self._hit_north(e.position()):
                    gz = pg.gizmo()
                    if gz is not None and math.hypot(gz["h"][0] - w[0], gz["h"][1] - w[1]) * self._v[0] < 12:
                        self.setFocus()
                        self.drag = ("grot", gz, math.atan2(w[1] - gz["c"][1], w[0] - gz["c"][0]), pg.gz_ang, pg.gizmo_snapshot(gz))
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                        pg.set_hint("Turn it: drag the round handle. Hold Shift to turn in steps of 15 degrees.")
                        return
                    h = pg.corner_at(w, 10.0 / self._v[0])
                    if h is not None:
                        self.setFocus()
                        self.drag = ("corner",) + h
                        pg.sel_corner = h
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                        pg.set_hint("Drag the corner to where you want it, or press Delete to remove it.")
                        self.update()
                        return
                    if pg.sel_corner is not None:
                        pg.sel_corner = None
                        self.update()
                    zi = pg.zone_edge_at(w, 7.0 / self._v[0])
                    if zi >= 0:
                        self.setFocus()
                        pg.pick_zone(zi)
                        self.drag = ("zone", zi, w[0], w[1], [list(q) for q in pg.zones[zi]["poly"]],
                                     [(b, b["x"], b["y"]) for b in pg.bays if b.get("auto") and b.get("zone") == pg.zones[zi]["name"]])
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                        pg.set_hint("Drag to move the whole parking area. Right-click it to copy it.")
                        return
                    from site_import import point_in_poly
                    if not any(point_in_poly(w, bpoly(b)) for b in pg.buildings()):
                        i = pg.bay_at(w)
                        if i >= 0:
                            self.setFocus()
                            pg.sel_bay = i
                            b = pg.bays[i]
                            self.drag = ("bay", i, w[0] - b["x"], w[1] - b["y"])
                            self.setCursor(Qt.CursorShape.ClosedHandCursor)
                            pg.park_selected()
                            self.update()
                            return
                        if pg.sel_bay >= 0:
                            pg.sel_bay = -1
                            self.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        w = self._world(e.position())
        if w is not None:
            if self.drag and self.drag[0] == "corner":
                self.page.move_corner(self.drag[1:], round(w[0] * 20) / 20, round(w[1] * 20) / 20)
                return
            self._lastw = w
            if self.drag and self.drag[0] == "grot":
                _, gz, a0, g0, snap = self.drag
                d = math.atan2(w[1] - gz["c"][1], w[0] - gz["c"][0]) - a0
                d = (d + math.pi) % (2 * math.pi) - math.pi
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    step = math.radians(15.0)
                    d = round((g0 + d) / step) * step - g0
                self.page.gizmo_turn(gz, snap, d, g0)
                return
            if self.drag and self.drag[0] == "zone":
                _, zi, x0, y0, orig, bays0 = self.drag
                dx, dy = round((w[0] - x0) * 20) / 20, round((w[1] - y0) * 20) / 20
                self.page.zones[zi]["poly"] = [[q[0] + dx, q[1] + dy] for q in orig]
                for b, bx, by in bays0:
                    b["x"], b["y"] = bx + dx, by + dy
                self.update()
                return
            if self.drag and self.drag[0] == "bay":
                _, i, dx, dy = self.drag
                b = self.page.bays[i]
                b["x"], b["y"], b["auto"] = round((w[0] - dx) * 20) / 20, round((w[1] - dy) * 20) / 20, False
                self.page.bay_moved_live(i)
                return
            if self.mode == "add_bay":
                self.hover = w
                self.update()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.drag and self.drag[0] == "grot":
            gz = self.drag[1]
            self.drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.page.gizmo_done(gz)
            return
        if self.drag and self.drag[0] == "zone":
            self.drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.page.zone_released()
            return
        if self.drag and self.drag[0] == "corner":
            self.drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.page.corner_released()
            return
        if self.drag and self.drag[0] == "bay":
            self.drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.page.refresh_parking(user=True)
            return
        super().mouseReleaseEvent(e)

    def _context(self, gpos, pos):
        w = self._world(pos)
        self._ctx_w = w
        pg = self.page
        if w is not None and self.mode == "select" and not self._hit_north(pos) and pg.roads:
            h = pg.corner_at(w, 10.0 / self._v[0])
            hit = pg.road_at(w)
            if (h is not None and h[0] == "road") or hit is not None:
                menu = QMenu(self)
                if h is not None and h[0] == "road":
                    ri, k = h[1], h[2]
                    piece = max(0, min(k, len(pg.roads[ri]["pts"]) - 2))
                    pt = None
                    if len(pg.roads[ri]["pts"]) > 2:
                        end = k in (0, len(pg.roads[ri]["pts"]) - 1)
                        menu.addAction("Cut the road back from this end" if end else "Remove this bend point", lambda: pg.remove_road_point(ri, k))
                else:
                    ri, piece, pt = hit
                fl = pg.road_flags(pg.roads[ri])
                if fl[piece]:
                    menu.addAction("Make this stretch of road straight", lambda: pg.set_road_curve(ri, piece, False))
                else:
                    menu.addAction("Curve this stretch of road", lambda: pg.set_road_curve(ri, piece, True))
                menu.addAction("Make the whole road straight", lambda: pg.set_road_curve(ri, None, False))
                menu.addAction("Curve the whole road", lambda: pg.set_road_curve(ri, None, True))
                if pt is not None:
                    menu.addAction("Add a bend point here", lambda: pg.add_road_point(ri, piece, pt))
                menu.exec(gpos)
                return
        if w is not None and self.mode == "select" and not self._hit_north(pos):
            zi = pg.zone_edge_at(w, 7.0 / self._v[0])
            if zi < 0:
                from site_import import point_in_poly
                if not any(point_in_poly(w, bpoly(b)) for b in pg.buildings()) and pg.bay_at(w) < 0:
                    zi = pg.zone_inside_at(w)
            if zi >= 0 or pg.clip_zone is not None:
                menu = QMenu(self)
                if zi >= 0:
                    pg.pick_zone(zi)
                    menu.addAction("Copy this parking area", lambda: pg.copy_zone(zi))
                    menu.addAction("Delete this parking area", lambda: pg.delete_zone(zi))
                if pg.clip_zone is not None:
                    menu.addAction("Paste a copy here", lambda: pg.paste_zone(w))
                menu.exec(gpos)
                return
        super()._context(gpos, pos)

    def begin(self, mode, role=None):
        super().begin(mode, role)
        if mode == "add_bay":
            self.setCursor(Qt.CursorShape.CrossCursor)

    def keyPressEvent(self, e):
        k = e.key()
        pg = self.page
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_Z and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            pg.undo()
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and (k == Qt.Key.Key_Y or (k == Qt.Key.Key_Z and e.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            pg.redo()
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_C and self.sel >= 0 and pg.sel_bay < 0:
            pg.copy_buildings()
        elif e.modifiers() & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_V and pg.clip_bld and (self.sel >= 0 or pg.clip_zone is None):
            pg.paste_buildings(getattr(self, "_lastw", None))
        elif e.modifiers() & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_C and pg.sel_bay < 0 and pg.sel_zone >= 0:
            pg.copy_zone(pg.sel_zone)
        elif e.modifiers() & Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_V and pg.clip_zone is not None and not (pg.clip_bld and self.sel >= 0):
            pg.paste_zone(getattr(self, "_lastw", None))
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.mode == "select" and pg.sel_bay < 0 and pg.sel_corner is not None:
            pg.remove_corner(pg.sel_corner)
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.mode == "select" and self.page.sel_bay >= 0:
            self.page.delete_bay()
        elif k == Qt.Key.Key_R and self.mode in ("select", "add_bay"):
            self.page.rotate_bay()
        else:
            super().keyPressEvent(e)


class SdpPage(SitePage):
    KEY = "sdp"
    TITLE = "SDP Creator"
    PLAN_CLS = ParkView
    sel_corner = None
    STEP_NAMES = ["The stand", "The buildings", "Parking", "Schedule", "Check and sheet"]
    STEP_HINTS = ["Load the survey (DXF, DWG, PDF), pick or trace the stand and set the building line on each boundary.",
                  "Bring in each block's footprint (from the IFC model, a drawing, or trace it) and place it on the stand.",
                  "Draw the parking areas round the buildings. The program fills them with bays and keeps the rules: 0.5 m from a building, 7 m to reverse out.",
                  "The schedule of blocks: phase, units, floor area. Fill in the title block details for the sheet.",
                  "What complies and what does not, then save the Site Development Plan as a PDF for council."]

    def __init__(self, win):
        self.zones, self.bays, self._bad, self.schemes, self.excl, self.roads = [], [], [], [], [], []
        self.clip_zone = None
        self.clip_bld = None
        self._rq = (None, [], [], [])
        self._tracing_road = False
        self.gz_ang, self._gz_key = 0.0, None
        self._undo, self._redo, self._ulast = [], [], None
        QTimer.singleShot(600, self._undo_baseline)
        self._tracing_path = False
        self._tracing_excl = False
        self.sel_bay = -1
        self.sel_zone = -1
        self._pbusy = False
        self._keep = []
        self.f = {}
        super().__init__(win)

    # ------------------------------------------------------------- the steps
    def _assemble(self, p1, p2, p3):
        self._keep = [p3, self._area_host]               # the checks step is the old results step; the area schedule is not used here
        self.build_frame([p1, p2, self._parking_page(), self._schedule_page(), p3], side=self._plan_panel())

    def _plan_panel(self):
        inner = super()._plan_panel()
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.metrics_lbl = QLabel("")
        self.metrics_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.metrics_lbl.setWordWrap(True)
        self.metrics_lbl.setObjectName("sdpMetrics")
        self.metrics_lbl.setStyleSheet("#sdpMetrics { background: rgba(128,128,128,0.14); border-radius: 6px; padding: 6px 10px; }")
        v.addWidget(self.metrics_lbl)
        v.addWidget(inner, 1)
        return panel

    def update_metrics(self):
        """the numbers that follow every change, over the plan: units, bays, coverage, floor area ratio, density"""
        if getattr(self, "metrics_lbl", None) is None or getattr(self, "t", None) is None or getattr(self, "zt", None) is None:
            return
        a = self.sdp()
        t = a["total"]
        ok, bad = "#2e9e5b", "#e0243a"
        cell = lambda lab, val, good=None: "<span style='color:#8a8f98'>%s</span> <b%s>%s</b>" % (lab, "" if good is None else " style='color:%s'" % (ok if good else bad), val)
        chk = {c[0]: c[3] for c in a["checks"]}
        tm = sum(w[0].value() for w in self.mix.values()) or 1.0
        beds = t["units"] * sum(w[0].value() * int(k) for k, w in self.mix.items()) / tm
        parts = [cell("Units", t["units"]), cell("Beds", "%d" % round(beds)), cell("Bays", "%d / %d needed" % (a["bays"], a["bays_needed"]), chk["Parking bays"])]
        if t["units"]:
            parts.append(cell("per unit", "%.2f" % (a["bays"] / float(t["units"]))))
        if a["bays"]:
            parts.append(cell("site per bay", "%.0f m2" % (a["area"] / a["bays"])))
        parts += [cell("Coverage", "%.1f %%" % a["cov"], chk["Coverage"]), cell("FAR", "%.2f" % a["far"], chk["Floor area ratio"]), cell("Density", "%.1f u/ha" % a["density"], chk["Density"])]
        if self.r_aisle.value() < 7.0 - 1e-6:
            parts.append("<b style='color:%s'>Aisle %.1f m is under the 7 m standard</b>" % (bad, self.r_aisle.value()))
        nb = sum(1 for pr in self._bad if pr)
        if nb:
            parts.append("<b style='color:%s'>%d bays break a rule</b>" % (bad, nb))
        self.metrics_lbl.setText("&nbsp;&nbsp;|&nbsp;&nbsp;".join(parts))

    def _parking_page(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Generate a layout", "Like a site solver: the tool places the blocks in rows inside the building lines and fills the rest with parking, then shows what fits. "
                          "You can then drag, turn or change anything by hand.")
        br = FlowLayout(None, 8, 6)
        b = QPushButton("New plan")
        b.setToolTip("Clear the stand, buildings, parking and schedule and start a fresh SDP.")
        b.clicked.connect(lambda _=False: self.new_plan())
        br.addWidget(b)
        b = QPushButton("Undo")
        b.setToolTip("Undo the last change (Ctrl+Z).")
        b.clicked.connect(lambda _=False: self.undo())
        br.addWidget(b)
        b = QPushButton("Redo")
        b.setToolTip("Put back what you undid (Ctrl+Y).")
        b.clicked.connect(lambda _=False: self.redo())
        br.addWidget(b)
        b = QPushButton("Keep an area clear")
        b.setToolTip("Draw a no-build, no-parking area: flood zone, servitude, steep slope, trees.")
        b.clicked.connect(lambda _=False: self.start_excl())
        br.addWidget(b)
        b = QPushButton("Remove keep-clear areas")
        b.clicked.connect(lambda _=False: self.clear_excl())
        br.addWidget(b)
        b = QPushButton("Find options...")
        b.setToolTip("Tries each block type in both directions and keeps the ones that meet your limits as schemes.")
        b.clicked.connect(lambda _=False: self.find_options())
        br.addWidget(b)
        b = QPushButton("Generate a layout...")
        b.clicked.connect(lambda _=False: self.generate())
        br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        v.addWidget(bx)
        bx, bv = self.box("Roads", "Draw a road as a smooth curve. Blocks and bays keep off it, bays run along both sides of it (the road is their aisle) and parking areas next to it line up with it.")
        fl = FlowLayout(None, 10, 6)
        self.road_w = sl.spin(1, 15, 7, 1, " m")
        self.road_w.setToolTip("The width of the road. With bays on one side, the 7 m pushback ends at the kerb on the other side (7 m is the width that fits exactly). With bays on both sides the road is made at least 7 m wide.")
        self.road_w.valueChanged.connect(self.road_width_changed)
        self.road_cb = QComboBox()
        self.road_cb.setMinimumWidth(230)
        self.road_cb.setToolTip("Pick a road, then change its width in the box next to it.")
        self.road_cb.currentIndexChanged.connect(self._road_picked)
        fl.addWidget(self._pair("Road", self.road_cb))
        self.road_smooth = QCheckBox("Smooth curve")
        self.road_smooth.setChecked(True)
        self.road_type = QComboBox()
        self.road_type.addItems(BAY_TYPES)
        fl.addWidget(self._pair("Width (no bays)", self.road_w))
        self.left_sp, self.right_sp = QSpinBox(), QSpinBox()
        for w_, tip in ((self.left_sp, "left"), (self.right_sp, "right")):
            w_.setRange(-1, 999)
            w_.setSpecialValueText("as many as fit")
            w_.setValue(0)
            w_.setToolTip("How many bays on the %s side of the road, going the way you drew it. 0 = none. The road widens to the pushback where there are bays." % tip)
            w_.valueChanged.connect(self._road_fields_changed)
        self.start_sp = sl.spin(0, 5000, 0, 1, " m")
        self.start_sp.setToolTip("Where the bays start along the road, measured from the start of it.")
        self.start_sp.valueChanged.connect(self._road_fields_changed)
        fl.addWidget(self._pair("Bays on the left", self.left_sp))
        fl.addWidget(self._pair("Bays on the right", self.right_sp))
        fl.addWidget(self._pair("Bays start at", self.start_sp))
        self.corner_r = sl.spin(0, 3, 2, 1, " m")
        self.corner_r.setToolTip("The rounded (driving) corner where a road meets another road: 2 m, 3 m at most. 0 = sharp corner.")
        self.corner_r.valueChanged.connect(lambda _v: (None if self._pbusy else (self.refresh_parking(user=True), self.changed())))
        fl.addWidget(self._pair("Corner radius at junctions", self.corner_r))
        self.path_w = sl.spin(0.8, 6, 2.0, 1, " m")
        self.path_w.setToolTip("The width of the next pathway you draw (change a drawn one with the width box above).")
        self.path_r = sl.spin(0, 3, 0.5, 1, " m")
        self.path_r.setToolTip("The rounded corner where a pathway meets a road or another pathway. 0 = sharp corner.")
        self.path_r.valueChanged.connect(lambda _v: (None if self._pbusy else (self.refresh_parking(user=True), self.changed())))
        fl.addWidget(self._pair("Pathway width", self.path_w))
        fl.addWidget(self._pair("Pathway corner radius", self.path_r))
        self.follow_bld = QCheckBox("Roads bend round buildings")
        self.follow_bld.setChecked(True)
        fl.addWidget(self.follow_bld)
        fl.addWidget(self.road_smooth)
        fl.addWidget(self._pair("Bays along it are", self.road_type))
        bv.addLayout(fl)
        br = FlowLayout(None, 8, 6)
        for txt, fn in (("Draw a road", self.start_road), ("Draw a pathway", self.start_path), ("Straighten this road", lambda: self._curve_picked(False)), ("Curve this road", lambda: self._curve_picked(True)),
                        ("Park along the roads", self.park_roads_clicked), ("Remove roads", self.clear_roads)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        v.addWidget(bx)
        bx, bv = self.box("Accessible and EV bays, schemes, export", "Like the TestFit parking solver: set aside accessible and electric-vehicle bays (nearest the buildings), keep several layouts as schemes and compare them, and export to CAD or CSV.")
        fl = FlowLayout(None, 10, 6)
        self.ada_tab = QCheckBox("Accessible bays as the municipal table asks")
        self.ada_tab.setChecked(True)
        self.ada_tab.setToolTip("City of Cape Town: 1 accessible bay for 1-50 bays, 2 for 51-100, 3 for 101-150, 4 for 151-200, then one more for every further 100. Each is 3.7 m wide, so it takes the room of a neighbouring bay. Untick to use the percentage instead.")
        self.ada_pct, self.ev_pct = sl.spin(0, 100, 2, 1, " %"), sl.spin(0, 100, 0, 1, " %")
        self.ada_pct.setToolTip("Share of the bays set aside for accessible parking. Check the figure your municipality asks for.")
        fl.addWidget(self.ada_tab)
        fl.addWidget(self._pair("Accessible bays", self.ada_pct))
        fl.addWidget(self._pair("EV bays", self.ev_pct))
        bv.addLayout(fl)
        br = FlowLayout(None, 8, 6)
        mixl = FlowLayout(None, 10, 6)
        self.mix = {}
        for k, (lab, share, ratio) in {"1": ("1 bed", 30, 1.0), "2": ("2 bed", 50, 1.5), "3": ("3 bed", 20, 2.0)}.items():
            sh, ra = sl.spin(0, 100, share, 1, " %"), sl.spin(0, 5, ratio, 2, "")
            sh.setToolTip("Share of the units that are %s." % lab)
            ra.setToolTip("Bays for each %s unit." % lab)
            self.mix[k] = (sh, ra)
            mixl.addWidget(self._pair(lab + " share", sh))
            mixl.addWidget(self._pair("bays each", ra))
        bv.addLayout(mixl)
        self.mix_lbl = QLabel("")
        bv.addWidget(self.mix_lbl)
        for txt, fn in (("Use this unit mix", self.use_mix), ("More like this", self.more_like_this), ("Set them aside", self.assign_special), ("Save as a scheme", self.save_scheme), ("Export to CAD (DXF)", self.export_dxf), ("Export numbers (CSV)", self.export_csv)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        row = QHBoxLayout()
        self.scheme_cb = QComboBox()
        row.addWidget(self.scheme_cb, 1)
        self.goal_cb = QComboBox()
        self.goal_cb.addItems(["Best: most units", "Best: most spare bays", "Best: least coverage", "Best: fewest m2 per bay"])
        self.goal_cb.currentIndexChanged.connect(lambda _i: self._show_schemes())
        row.addWidget(self.goal_cb)
        for txt, fn in (("Open scheme", self.load_scheme), ("Delete scheme", self.delete_scheme)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        bv.addLayout(row)
        self.scheme_lbl = QLabel("")
        self.scheme_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.scheme_lbl.setWordWrap(True)
        bv.addWidget(self.scheme_lbl)
        v.addWidget(bx)
        bx, bv = self.box("Parking rules", "A bay is 2.5 by 5.0 m and needs 7 m in front of it to reverse out. A bay that breaks a rule shows red on the plan.")
        fl = FlowLayout(None, 10, 6)
        self.r_w = sl.spin(1.5, 5, sp.RULES["w"], 2, " m")
        self.r_l = sl.spin(3, 10, sp.RULES["l"], 2, " m")
        self.r_aisle = sl.spin(3, 12, sp.RULES["aisle"], 2, " m")
        self.r_bld = sl.spin(0, 5, sp.RULES["bld"], 2, " m")
        self.r_bound = sl.spin(0, 5, sp.RULES["bound"], 2, " m")
        self.r_parl = sl.spin(4, 9, sp.RULES["par_l"], 2, " m")
        self.r_adaw = sl.spin(2.5, 5, sp.RULES["ada_w"], 2, " m")
        self.std_cb = QComboBox()
        self.std_cb.addItems(list(STANDARDS))
        self.std_cb.setToolTip("South African municipal parking standards. Pressing 'Use this standard' sets the bay sizes, aisle, parallel bay, accessible bay width and the parking ratio for the residents and visitors.")
        std_b = QPushButton("Use this standard")
        std_b.clicked.connect(lambda _=False: self.use_standard())
        fl.addWidget(self._pair("Standard", self.std_cb))
        fl.addWidget(std_b)
        for lab, w, tip in (("Bay width", self.r_w, ""), ("Bay length", self.r_l, ""), ("Room to reverse out", self.r_aisle, "The aisle in front of a bay."),
                            ("Clear of a building", self.r_bld, "The nearest a bay may be to a building."), ("Clear of the boundary", self.r_bound, "0 means a bay may touch the boundary."),
                            ("Parallel bay length", self.r_parl, "A bay along the kerb: 6 m x 2.5 m (City of Cape Town zoning scheme)."),
                            ("Accessible bay width", self.r_adaw, "An accessible bay is at least 3.7 m wide and 5 m long (City of Cape Town); 3.5 m in Mangaung. Setting the accessible bays widens them.")):
            w.setToolTip(tip)
            w.valueChanged.connect(self._rules_changed)
            fl.addWidget(self._pair(lab, w))
        self.auto_fill = QCheckBox("Fill an area with bays as soon as I finish drawing it")
        self.auto_fill.setChecked(True)
        fl.addWidget(self.auto_fill)
        self.live = QCheckBox("Re-park by itself when I move or add a building")
        self.live.setChecked(True)
        fl.addWidget(self.live)
        self.r_lines = QCheckBox("Keep the bays out of the building lines")
        self.r_lines.toggled.connect(self._rules_changed)
        fl.addWidget(self.r_lines)
        fl.addStretch(1)
        bv.addLayout(fl)
        v.addWidget(bx)
        bx, bv = self.box("Parking areas", "Draw the polygon where cars may park and drive, round the buildings. Then press Fill: the bays are laid out along the longest side, "
                          "on the 7 m aisle, and the layout with the most bays is kept.")
        br = FlowLayout(None, 8, 6)
        for text, fn, tip in (("Draw a parking area", self.start_zone, "Click each corner of the area on the plan. Double-click or Enter to finish."),
                              ("Use the whole stand", self.zone_whole_stand, "One area over the whole stand. The buildings are left out of it by the rules."),
                              ("Fill the selected area", self.fill_selected, ""), ("Fill all areas", self.fill_all, ""),
                              ("Remove its bays", self.clear_selected, "Takes the automatic bays out of the selected area."), ("Remove the area", self.remove_zone, "")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        self.zt = QTableWidget(0, 4)
        self.zt.setHorizontalHeaderLabels(["Area", "Rows run at (degrees, or auto)", "Its bays are", "Bays"])
        self.zt.verticalHeader().setVisible(False)
        self.zt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.zt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.zt.setMinimumHeight(130)
        self.zt.itemChanged.connect(self._zone_edited)
        self.zt.itemSelectionChanged.connect(self._zone_picked)
        self.zt.itemSelectionChanged.connect(lambda: setattr(self, "sel_zone", (self.zt.currentRow() if self.zt.currentRow() >= 0 else -1)) or self.plan.update())
        bv.addWidget(self.zt)
        fl = FlowLayout(None, 10, 6)
        self.join_cb = QCheckBox("The selected area joins the road")
        self.join_cb.setChecked(True)
        self.join_cb.setToolTip("Rows are laid so their aisles meet the road. Untick for a cul-de-sac that stands on its own.")
        self.join_cb.toggled.connect(self._zone_opts)
        self.max_sp = QSpinBox()
        self.max_sp.setRange(0, 5000)
        self.max_sp.setSpecialValueText("all that fit")
        self.max_sp.setToolTip("How many bays in the selected area (the ones nearest the road are kept). 0 = as many as fit.")
        self.max_sp.valueChanged.connect(self._zone_opts)
        self.side_cb = QComboBox()
        self.side_cb.addItems(["Where the area is", "Other side of the road", "Both sides of the road"])
        self.side_cb.setToolTip("Which side of the road the bays along it go. 'Other side' puts them opposite the area; 'Both sides' makes the road a double-sided aisle (7 m).")
        self.side_cb.currentIndexChanged.connect(self._zone_opts)
        fl.addWidget(self.join_cb)
        self.style_cb = QComboBox()
        self.style_cb.addItems(["Automatic", "Across the road", "Parallel to the road"])
        self.style_cb.setToolTip("Automatic: bays stand across the road with the 7 m pushback; where the area is only a narrow strip beside the road (too shallow for a bay across it) they are laid parallel to the kerb.")
        self.style_cb.currentIndexChanged.connect(self._zone_opts)
        self.ang_cb = QComboBox()
        self.ang_cb.addItems(["90 degrees (square)", "60 degrees", "45 degrees"])
        self.ang_cb.setToolTip("Angled bays save space on a one-way aisle: aisle 5.4 m at 60 degrees, 5.2 m at 45 degrees (South African parking standards). A bay is still 2.5 x 5.0 m.")
        self.ang_cb.currentIndexChanged.connect(self._zone_opts)
        fl.addWidget(self._pair("Bay angle", self.ang_cb))
        fl.addWidget(self._pair("Bay style", self.style_cb))
        fl.addWidget(self._pair("Bays on", self.side_cb))
        fl.addWidget(self._pair("Bays in the selected area", self.max_sp))
        bv.addLayout(fl)
        v.addWidget(bx)
        bx, bv = self.box("Single bays", "Click a bay on the plan to select it and drag it. Delete removes it, R turns it a quarter. Bays you place or move yourself are kept when an area is filled again.")
        br = FlowLayout(None, 8, 6)
        for text, fn, tip in (("Add a bay by clicking", self.start_add_bay, "Click on the plan to place a bay. The bay shows red if it breaks a rule. Esc stops."),
                              ("Turn the selected bay", self.rotate_bay, ""), ("Delete the selected bay", self.delete_bay, ""),
                              ("Remove all bays", self.clear_all_bays, "")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        self.new_type = QComboBox()
        self.new_type.addItems(BAY_TYPES)
        self.new_type.setToolTip("The kind of the next bay you place, and of the selected bay when you change it.")
        self.new_type.activated.connect(self._set_bay_type)
        br.addWidget(self._pair("Bay is", self.new_type))
        br.addStretch(1)
        bv.addLayout(br)
        v.addWidget(bx)
        bx, bv = self.box("Refuse area and gatehouse", "They are buildings on the plan, so you can drag and turn them and the bays keep 0.5 m away from them. "
                          "A building whose name starts with Refuse or Gatehouse is drawn in its own colour.")
        row = FlowLayout(None, 10, 6)
        self.refuse_w, self.refuse_d = sl.spin(1, 30, 6.0, 1, " m"), sl.spin(1, 30, 3.0, 1, " m")
        row.addWidget(self._pair("Refuse area, width", self.refuse_w))
        row.addWidget(self._pair("depth", self.refuse_d))
        bv.addLayout(row)
        br = FlowLayout(None, 8, 6)
        for text, fn, tip in (("Size it for the units", self.size_refuse, "Sets the size from the number of units, in the proportion of the Mystic Views plan."),
                              ("Add a refuse area", self.add_refuse, "Puts a refuse area of this size on the plan."),
                              ("Suggest a place for it", self.suggest_refuse, "Finds a spot near the street, clear of the buildings, the bays and their aisles."),
                              ("Add the gatehouse", self.add_gatehouse, "A small building at the entrance. Drag it into place."),
                              ("Gatehouse from the IFC model...", self.gatehouse_from_ifc, "Reads the gatehouse's footprint from an IFC model. Name it Gatehouse."),
                              ("Gatehouse from a drawing...", self.gatehouse_from_drawing, "Load a drawing with the gatehouse, then pick or trace it. Name it Gatehouse.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        v.addWidget(bx)
        bx, bv = self.box("How many bays the development needs", "From the units in the schedule: a bay for every unit (or more, see the schedule step) and a visitor's bay for every few units.")
        self.need_lbl = QLabel("")
        self.need_lbl.setWordWrap(True)
        self.need_lbl.setTextFormat(Qt.TextFormat.RichText)
        bv.addWidget(self.need_lbl)
        v.addWidget(bx)
        bx, bv = self.box("Result")
        self.park_lbl = QLabel("")
        self.park_lbl.setWordWrap(True)
        self.park_lbl.setTextFormat(Qt.TextFormat.RichText)
        bv.addWidget(self.park_lbl)
        v.addWidget(bx)
        v.addStretch(1)
        return p

    def _schedule_page(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The development", "These go in the title block of the sheet. The erf and the zoning are from the first step.")
        fl = QFormLayout()
        for key, label, tip in (("project", "Development name", "for example Blue Hills Estate"), ("township", "Township or town", ""), ("owner", "Owner or applicant", ""),
                                ("drawing", "Drawing number", "")):
            e = QLineEdit()
            e.setPlaceholderText(tip)
            e.textChanged.connect(self.changed)
            self.f[key] = e
            fl.addRow(label, e)
        self.f["scale"] = QComboBox()
        self.f["scale"].setEditable(True)
        self.f["scale"].addItems(SCALES)
        self.f["scale"].setCurrentText("1:500")
        self.f["scale"].currentTextChanged.connect(self.changed)
        fl.addRow("Scale", self.f["scale"])
        self.f["date"] = QLineEdit()
        self.f["date"].textChanged.connect(self.changed)
        fl.addRow("Date", self.f["date"])
        for key, label in (("walkways", "Walkways to the blocks"), ("roads", "Internal roads")):
            self.f[key] = sl.spin(0, 9999999, 0, 1, " m2")
            self.f[key].valueChanged.connect(self.changed)
            fl.addRow(label + " (hard surface)", self.f[key])
        bv.addLayout(fl)
        v.addWidget(bx)
        bx, bv = self.box("More limits", "A limit of 0 means there is none, and it is not checked. Coverage and floor area ratio are in the first step.")
        row = FlowLayout(None, 10, 6)
        self.f["max_density"] = sl.spin(0, 1000, 0, 1, " units/ha")
        self.f["bays_per_unit"] = sl.spin(0, 10, 1.0, 2, " per unit")
        self.f["visitor_per"] = QSpinBox()
        self.f["visitor_per"].setRange(0, 100)
        self.f["visitor_per"].setValue(5)
        self.f["visitor_per"].setSuffix(" units")
        self.f["visitor_per"].setSpecialValueText("none")
        self.f["extra_bays"] = QSpinBox()
        self.f["extra_bays"].setRange(0, 9999)
        self.f["extra_bays"].setToolTip("Used for the bays provided only when no bays are placed on the plan.")
        for key, label in (("max_density", "Density not more than"), ("bays_per_unit", "Parking for residents"), ("visitor_per", "One visitor's bay for every"),
                           ("extra_bays", "Bays when none are on the plan")):
            self.f[key].valueChanged.connect(self.changed)
            row.addWidget(self._pair(label, self.f[key]))
        bv.addLayout(row)
        v.addWidget(bx)
        bx, bv = self.box("The blocks", "One line for each block. The footprint comes from the buildings on the plan. Phase is just a name, for example Phase 1 and Phase 2.")
        br = FlowLayout(None, 8, 6)
        for text, fn, tip in (("Add a block", self.add_block, ""), ("Add several blocks...", self.add_run, "For example H1 to H26 in one go."),
                              ("Remove selected", self.remove_blocks, ""),
                              ("Read the footprints from the plan", self.read_from_site, "Adds a block for each building on the plan and fills in its footprint."),
                              ("Read floor areas from the Area schedule", self.read_floor_areas, "Where a block name in the Area schedule matches, its floor area is filled in.")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            br.addWidget(b)
        br.addStretch(1)
        bv.addLayout(br)
        self.t = QTableWidget(0, len(COLS))
        self.t.setHorizontalHeaderLabels(COLS)
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        h = self.t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w_ in enumerate((90, 100, 160, 60, 60, 90, 80, 80, 90, 100, 60)):
            self.t.setColumnWidth(i, w_)
        h.setStretchLastSection(True)
        self.t.setMinimumHeight(320)
        self.t.itemChanged.connect(self._edited)
        bv.addWidget(self.t)
        self.sum_lbl = QLabel("")
        self.sum_lbl.setObjectName("xaSub")
        self.sum_lbl.setWordWrap(True)
        bv.addWidget(self.sum_lbl)
        v.addWidget(bx, 1)
        bx, bv = self.box("Notes on the sheet", "Printed under the schedule, for example the conditions of the approval or the phasing.")
        self.f["notes"] = QPlainTextEdit()
        self.f["notes"].setMinimumHeight(90)
        self.f["notes"].textChanged.connect(self.changed)
        bv.addWidget(self.f["notes"])
        v.addWidget(bx)
        return p

    @staticmethod
    def _pair(label, w):
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        h.addWidget(w)
        return c

    def on_step(self, i):
        super().on_step(i)                               # the schedule step has the whole width, like the area schedule had
        if i == 3:
            self.sync_blocks()
        if i in (2, 4):
            self.refresh_parking()

    # ------------------------------------------------------------- parking: rules and what they are tested against
    def rules_now(self):
        return {"w": self.r_w.value(), "l": self.r_l.value(), "aisle": self.r_aisle.value(), "bld": self.r_bld.value(), "bound": self.r_bound.value(),
                "outside_lines": self.r_lines.isChecked(), "par_l": self.r_parl.value(), "ada_w": self.r_adaw.value()}

    def site_obj(self):
        v = self.verts()
        env = None
        if self.r_lines.isChecked() and len(v) >= 3:
            env = sl.envelope(v, [e["sb"] for e in self.edges()])
        return sp.Site(v, [bpoly(b) for b in self.buildings()] + [[tuple(q) for q in e] for e in self.excl], env, roads=self.road_quads_all(), road_owner=self.road_owner_all())

    def _rules_changed(self, *_a):
        if not self._pbusy:
            self.refresh_parking(user=True)

    def bay_at(self, w):
        r = self.rules_now()
        for i in range(len(self.bays) - 1, -1, -1):
            if sp.pip(w, sp.bay_poly(self.bays[i], r)):
                return i
        return -1

    def bay_problems(self, i, site=None, r=None):
        r = r or self.rules_now()
        site = site or self.site_obj()
        return sp.problems(self.bays[i], r, site, self.bays[:i] + self.bays[i + 1:])

    def bay_moved_live(self, i):
        while len(self._bad) < len(self.bays):
            self._bad.append([])
        self._bad[i] = self.bay_problems(i)
        self.plan.update()

    def refresh_parking(self, user=False):
        if getattr(self, "zt", None) is None or self._pbusy:
            return
        site, r = self.site_obj(), self.rules_now()
        self._bad = [sp.problems(b, r, site, self.bays[:i] + self.bays[i + 1:]) for i, b in enumerate(self.bays)]
        keep_sel = self.sel_zone
        self._pbusy = True
        try:
            self.zt.setRowCount(0)
            for i, z in enumerate(self.zones):
                self.zt.insertRow(i)
                n = sum(1 for b in self.bays if b.get("zone") == z["name"])
                for c, val in enumerate((z["name"], "auto" if z.get("angle") is None else "%g" % z["angle"], "", str(n))):
                    it = QTableWidgetItem(val)
                    if c >= 2:
                        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.zt.setItem(i, c, it)
                cb = QComboBox()
                cb.addItems(BAY_TYPES)
                cb.setCurrentText(z.get("type", "Open"))
                cb.setToolTip("Covered, garage, open, shade cloth or tandem (grass blocks). Tandem bays are not counted toward the parking requirement.")
                cb.currentTextChanged.connect(lambda t_, k=i: self._zone_type(k, t_))
                self.zt.setCellWidget(i, 2, cb)
            if 0 <= keep_sel < self.zt.rowCount():
                self.sel_zone = keep_sel
                self.zt.selectRow(keep_sel)
        finally:
            self._pbusy = False
        bad = [i for i, pr in enumerate(self._bad) if pr]
        n = len(self.bays)
        if not n:
            self.park_lbl.setText("No bays yet. Draw a parking area and press Fill.")
        else:
            txt = "<b>%d bays</b>: %d keep the rules" % (n, n - len(bad))
            if bad:
                txt += ", <span style='color:#e0243a'><b>%d break a rule</b></span> (red on the plan):<br>" % len(bad)
                kinds = {}
                for i in bad:
                    for pr in self._bad[i]:
                        key = pr.split(" (")[0].split(" from a building")[0] if "from a building" in pr else pr.split(" (")[0]
                        kinds[key] = kinds.get(key, 0) + 1
                txt += "<br>".join("%d x %s" % (c, k) for k, c in sorted(kinds.items(), key=lambda kv: -kv[1])[:6])
            else:
                txt += ". <span style='color:#2e9e5b'><b>Every bay keeps the rules.</b></span>"
            self.park_lbl.setText(txt)
        self._need_text()
        self.update_metrics()
        self.plan.update()
        if user:
            self.changed()
            self._after_edit()

    def bay_counts(self):
        """bays on the plan by type: (kept the rules, broke a rule)"""
        out = {}
        for i, b in enumerate(self.bays):
            k = b.get("type", "Open")
            ok, bad = out.get(k, (0, 0))
            out[k] = (ok + (0 if (i < len(self._bad) and self._bad[i]) else 1), bad + (1 if (i < len(self._bad) and self._bad[i]) else 0))
        return out

    def _need_text(self):
        if getattr(self, "need_lbl", None) is None or getattr(self, "t", None) is None:
            return
        a = self.sdp()
        t = a["total"]
        if not t["units"]:
            self.need_lbl.setText("No units in the schedule yet (fourth step), so the number of bays needed cannot be worked out.")
            return
        site = self.site()
        short = a["bays_needed"] - a["bays"]
        vis = ", and a visitor's bay for every %d units" % site["visitor_per"] if site["visitor_per"] else ""
        txt = ("<b>%d units in %d blocks need %d bays</b> (%.2g per unit%s).<br>On the plan: <b>%d counted bays</b> - " %
               (t["units"], t["blocks"], a["bays_needed"], site["bays_per_unit"], vis, a["bays"]))
        txt += ("<span style='color:#2e9e5b'><b>enough</b></span>" if short <= 0 else "<span style='color:#e0243a'><b>%d short</b></span>" % short)
        bc = self.bay_counts()
        if bc:
            txt += "<br>" + ", ".join("%d %s%s" % (ok + bad, k.lower(), " (not counted)" if k == "Tandem" else "") for k, (ok, bad) in sorted(bc.items()))
        if len(a["phases"]) > 1:
            txt += "<br>" + " | ".join("%s: %d units, %d bays" % (k, p["units"], p["bays_needed"]) for k, p in a["phases"].items())
        mix = kb.parking_mix(a["bays_needed"])
        txt += "<br><span style='color:#8a8f98'>Like Mystic Views, %d bays would be about %s. A refuse area would be about %.0f m2.</span>" % (
            a["bays_needed"], ", ".join("%d %s" % (v_, k_.lower()) for k_, v_ in mix.items()), kb.refuse_area(t["units"]))
        self.need_lbl.setText(txt)

    def park_selected(self):
        if 0 <= self.sel_bay < len(self.bays):
            self.new_type.setCurrentText(self.bays[self.sel_bay].get("type", "Open"))
            pr = self._bad[self.sel_bay] if self.sel_bay < len(self._bad) else []
            self.set_hint(("This bay: " + "; ".join(pr) + ".") if pr else "This bay keeps the rules. Drag it, press R to turn it, Delete to remove it.")

    # ------------------------------------------------------------- parking: areas and bays
    def start_zone(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self.plan.begin("trace_parking")
        self.set_hint("Click each corner of the parking area, round the buildings. Hold Shift to keep a line straight. Double-click or press Enter to finish.")

    def road_wide(self, rd):
        """the road is as wide as the pushback (7 m) where it has bays, and as wide as you set it elsewhere"""
        return rd["w"] if rd.get("path") else max(self.r_aisle.value(), rd["w"])

    def road_span(self, rd):
        """the stretches of the road that are thickened to the pushback: only where there are bays on both sides of it"""
        return sp.merge_spans(list(rd.get("_zs", [])), 0.5)

    def road_geom(self, rd):
        return sp.road_quads(rd["pts"], rd["w"], (rd.get("segs") or rd.get("smooth", True)), self.road_span(rd), self.road_wide(rd))

    def road_quads_all(self):
        if not self.roads:
            return []
        key = repr([(bool(r.get("path")), r["pts"], r["w"], self.path_r.value(), (r.get("segs") or r.get("smooth", True)), r.get("_zs", []), self.r_aisle.value(), self.corner_r.value()) for r in self.roads])
        if self._rq[0] != key or len(self._rq) < 4:
            quads, owner = [], []
            for i, r in enumerate(self.roads):
                g = self.road_geom(r)
                quads += g
                owner += [i] * len(g)
            self._fpath = []
            fl = self.road_fillets()
            self._rq = (key, quads + fl, owner + [-1] * len(fl), [bool(self.roads[o_].get("path")) for o_ in owner] + list(self._fpath))
        return self._rq[1]

    def road_owner_all(self):
        self.road_quads_all()
        return self._rq[2] if (self.roads and len(self._rq) > 2) else []

    def _half_at(self, rd, s):
        return (self.road_wide(rd) if any(a - 0.01 <= s <= b + 0.01 for a, b in self.road_span(rd)) else rd["w"]) / 2.0

    def connect_roads(self):
        """roads that end on another road join it: the end is snapped onto the other road's centre line"""
        moved = False
        for i, rd in enumerate(self.roads):
            for e in (0, -1):
                q = rd["pts"][e]
                best = None
                for j, o in enumerate(self.roads):
                    if j == i:
                        continue
                    jn = sp.road_junction(o["pts"], (o.get("segs") or o.get("smooth", True)), q)
                    if jn and jn[0] <= (3.0 if rd.get("path") else 8.0) and (best is None or jn[0] < best[0]):
                        best = jn
                if best and best[0] > 0.02:
                    rd["pts"][e] = [round(best[1][0], 3), round(best[1][1], 3)]
                    if rd.get("base") and len(rd["base"]) == len(rd["pts"]):
                        rd["base"][e] = list(rd["pts"][e])
                    moved = True
        return moved

    def road_fillets(self):
        """the rounded corners where one road meets the side of another"""
        out = []
        for i, rd in enumerate(self.roads):
            c = sp.spline(rd["pts"], 0.5, (rd.get("segs") or rd.get("smooth", True)))
            if len(c) < 8:
                continue
            L = sp.road_length(rd["pts"], (rd.get("segs") or rd.get("smooth", True)))
            for e in (0, -1):
                q = rd["pts"][e]
                for j, o in enumerate(self.roads):
                    if j == i:
                        continue
                    jn = sp.road_junction(o["pts"], (o.get("segs") or o.get("smooth", True)), q)
                    if not jn or jn[0] > 0.6:
                        continue
                    a, b = (c[0], c[min(8, len(c) - 1)]) if e == 0 else (c[-1], c[max(-9, -len(c))])
                    ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                    d = ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)
                    pth = bool(rd.get("path") or o.get("path"))
                    R = min(3.0, self.path_r.value() if pth else self.corner_r.value())
                    if R < 0.1:
                        continue
                    g = sp.junction_fillets(jn[1], jn[2], self._half_at(o, jn[3]), d, self._half_at(rd, 0.0 if e == 0 else L), R)
                    out += g
                    self._fpath = getattr(self, "_fpath", []) + [pth] * len(g)
        return out

    def settle_roads(self):
        a = self.reroute_roads()
        b = self.connect_roads()
        return a or b

    def reroute_roads(self):
        """the road bends round buildings: control points that leave less than the clear room are pushed away (the ends at the boundary stay)"""
        if not self.roads:
            return False
        obs = [bpoly(b) for b in self.buildings()] + [[tuple(q) for q in e] for e in self.excl] if self.follow_bld.isChecked() else []
        for rd in self.roads:                                   # "base" = the points as drawn; the road round the buildings is worked out from it, so it springs back
            if not rd.get("base") or len(rd["base"]) != len(rd["pts"]):
                rd["base"] = [list(q) for q in rd["pts"]]
        v = [tuple(q) for q in self.verts()]
        r = self.rules_now()
        moved = False
        for rd in self.roads:
            pin = {0, len(rd["pts"]) - 1}                      # the ends (the gate) stay where you put them
            wide = self.road_wide(rd) if (rd.get("left", 0) or rd.get("right", 0)) else rd["w"]
            clear = wide / 2.0 + r["bld"] + 0.3 + (r["l"] if (rd.get("left", 0) or rd.get("right", 0)) else 0.0)
            new = sp.push_off(rd["base"], obs, clear, pin, (rd.get("segs") or rd.get("smooth", True))) if obs else [list(q) for q in rd["base"]]
            for k_ in range(1, len(new) - 1):                  # a bend never leaves the stand
                if len(v) >= 3 and not sp.pip(tuple(new[k_]), v):
                    best, bq = 1e18, None
                    for i_ in range(len(v)):
                        a_, b_ = v[i_], v[(i_ + 1) % len(v)]
                        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
                        L2 = dx * dx + dy * dy or 1.0
                        u = max(0.0, min(1.0, ((new[k_][0] - a_[0]) * dx + (new[k_][1] - a_[1]) * dy) / L2))
                        q_ = (a_[0] + u * dx, a_[1] + u * dy)
                        d_ = math.hypot(new[k_][0] - q_[0], new[k_][1] - q_[1])
                        if d_ < best:
                            best, bq = d_, q_
                    cx_, cy_ = sum(p_[0] for p_ in v) / len(v), sum(p_[1] for p_ in v) / len(v)
                    L_ = math.hypot(cx_ - bq[0], cy_ - bq[1]) or 1.0
                    new[k_] = [bq[0] + (cx_ - bq[0]) / L_ * 1.0, bq[1] + (cy_ - bq[1]) / L_ * 1.0]
            if any(abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6 for a, b in zip(new, rd["pts"])):
                rd["pts"] = [[round(q[0], 3), round(q[1], 3)] for q in new]
                moved = True
        return moved

    def start_road(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self._tracing_road = True
        self._tracing_path = False
        self.plan.begin("trace_road")
        self.set_hint("Click the points the road goes through, from the gate inwards. Double-click or press Enter to finish: the road is drawn as a smooth curve.")

    def start_path(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self._tracing_road = True
        self._tracing_path = True
        self.plan.begin("trace_road")
        self.set_hint("Click the points the pathway goes through. Double-click or press Enter to finish. A pathway has no bays and its own light pavement colour; it joins a road or another pathway if it ends on it.")

    def road_width_changed(self, v):
        """the width box sets the chosen road (and the next one you draw)"""
        if self._pbusy or getattr(self, "_rw_busy", False):
            return
        i = self.road_cb.currentIndex()
        if 0 <= i < len(self.roads):
            self.roads[i]["w"] = float(v)
            self._show_roads(i)
            self.park_roads()
            self.refresh_parking(user=True)
            self.changed()

    def _show_roads(self, sel=None):
        """the list of roads: one entry each, the box shows the width of the chosen one"""
        if getattr(self, "road_cb", None) is None:
            return
        self._rw_busy = True
        try:
            i = self.road_cb.currentIndex() if sel is None else sel
            self.road_cb.clear()
            self.road_cb.addItems(["%s %d  (%.1f m wide%s, %.0f m long)" % ("Pathway" if r.get("path") else "Road", k + 1, r["w"], "" if not self.road_span(r) else ", %.1f with bays" % self.road_wide(r), sp.road_length(r["pts"], (r.get("segs") or r.get("smooth", True))))
                                   for k, r in enumerate(self.roads)])
            if self.roads:
                i = max(0, min(i, len(self.roads) - 1))
                self.road_cb.setCurrentIndex(i)
                self.road_w.setValue(self.roads[i]["w"])
                self.left_sp.setValue(int(self.roads[i].get("left", 0)))
                self.right_sp.setValue(int(self.roads[i].get("right", 0)))
                self.start_sp.setValue(float(self.roads[i].get("start", 0.0)))
        finally:
            self._rw_busy = False

    def _load_road_fields(self, i):
        rd = self.roads[i]
        self._rw_busy = True
        try:
            self.road_w.setValue(rd["w"])
            self.left_sp.setValue(int(rd.get("left", 0)))
            self.right_sp.setValue(int(rd.get("right", 0)))
            self.start_sp.setValue(float(rd.get("start", 0.0)))
        finally:
            self._rw_busy = False

    def _curve_picked(self, curved):
        i = self.road_cb.currentIndex()
        if 0 <= i < len(self.roads):
            self.set_road_curve(i, None, curved)
        else:
            self.set_hint("Draw a road first.")

    def _road_picked(self, i):
        if 0 <= i < len(self.roads) and not getattr(self, "_rw_busy", False):
            self._load_road_fields(i)

    def _road_fields_changed(self, *_a):
        if self._pbusy or getattr(self, "_rw_busy", False):
            return
        i = self.road_cb.currentIndex()
        if 0 <= i < len(self.roads):
            rd = self.roads[i]
            rd["left"], rd["right"], rd["start"] = self.left_sp.value(), self.right_sp.value(), self.start_sp.value()
            self.settle_roads()
            self.park_roads()
            self.refresh_parking(user=True)
            self.changed()

    def park_roads(self):
        """bays along the roads, nose to the road. A road is told how many bays it has on each side, and a parking area that runs along a road gets its bays standing
        along it. The 7 m pushback always ends exactly at the kerb on the other side; only where there are bays on both sides is the road made thicker (to 7 m)"""
        self.bays = [b for b in self.bays if not str(b.get("zone", "")).startswith("Road ")]
        for rd in self.roads:
            rd["_zs"] = []
        self._rq = (None, [], [], [])
        if not self.roads:
            return 0
        r, n = self.rules_now(), 0
        zs = [(z["name"], [tuple(q) for q in z["poly"]], int(z.get("max", 0)), int(z.get("side", 0)), int(z.get("style", 0))) for z in self.zones if z.get("join", True) and len(z["poly"]) >= 3 and int(z.get("bay_angle", 90)) == 90]
        plans = []
        for rd in self.roads:
            if rd.get("path"):
                plans.append({"st": [], "dbl": []})
                continue
            pl = sp.road_plan(rd["pts"], rd["w"], self.road_flags(rd), r, rd.get("left", 0), rd.get("right", 0), rd.get("start", 0.0), zs)
            rd["_zs"] = pl["dbl"]
            plans.append(pl)
        self._rq = (None, [], [], [])
        site = self.site_obj()
        ztype = {z["name"]: z.get("type", "Open") for z in self.zones}
        for i, rd in enumerate(self.roads):
            got = sp.road_place(rd["pts"], rd["w"], site, r, list(self.bays), "Road %d" % (i + 1), i, self.road_flags(rd), plans[i])
            for b in got:
                b["type"] = ztype.get(b.get("rz"), self.road_type.currentText())
            self.bays += got
            n += len(got)
        self._rq = (None, [], [], [])
        self._show_roads()
        return n

    def park_roads_clicked(self):
        for rd in self.roads:
            if rd.get("path"):
                continue
            if not rd.get("left") and not rd.get("right"):
                rd["left"] = rd["right"] = -1
        self._show_roads()
        self._rq = (None, [], [], [])
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = self.park_roads()
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_parking(user=True)
        self.set_hint("%d bays placed along the roads." % n if self.roads else "Draw a road first.")

    def clear_roads(self):
        self.roads = []
        self._show_roads()
        self.bays = [b for b in self.bays if not str(b.get("zone", "")).startswith("Road ")]
        self.refresh_parking(user=True)

    def road_angle_near(self, poly):
        """the direction of the nearest road at a parking area, so its rows run along the road and join it"""
        if not self.roads:
            return None
        cx = sum(q[0] for q in poly) / len(poly)
        cy = sum(q[1] for q in poly) / len(poly)
        best, ang = 1e18, None
        for rd in self.roads:
            c = sp.spline(rd["pts"], 2.0, (rd.get("segs") or rd.get("smooth", True)))
            for i in range(len(c) - 1):
                d = sp.seg_pt((cx, cy), c[i], c[i + 1])
                if d < best:
                    best, ang = d, math.degrees(math.atan2(c[i + 1][1] - c[i][1], c[i + 1][0] - c[i][0])) % 180.0
        return ang

    def corner_at(self, w, tol):
        """the corner (of the stand, a parking area or a keep-clear area) under world point w: (kind, i, k) or None"""
        best, hit = tol, None
        for kind, polys in (("road", [r["pts"] for r in self.roads]), ("excl", self.excl), ("zone", [z["poly"] for z in self.zones]), ("stand", [self.verts()])):
            for i, pl in enumerate(polys):
                for k, q in enumerate(pl):
                    d = math.hypot(q[0] - w[0], q[1] - w[1])
                    if d < best:
                        best, hit = d, (kind, i, k)
        return hit

    def move_corner(self, h, x, y):
        kind, i, k = h
        if kind == "road" and getattr(self, "road_cb", None) is not None and self.road_cb.currentIndex() != i and not getattr(self, "_rw_busy", False):
            self.road_cb.setCurrentIndex(i)
        if kind == "stand":
            vs = [tuple(q) for q in self.verts()]
            vs[k] = (x, y)
            self.set_vertices(vs)
        elif kind == "road":
            self.roads[i]["pts"][k] = [x, y]
            bs = self.roads[i].get("base")
            if bs and len(bs) == len(self.roads[i]["pts"]):
                bs[k] = [x, y]
        elif kind == "zone":
            self.zones[i]["poly"][k] = [x, y]
        else:
            self.excl[i][k] = [x, y]
        self.plan.update()

    def corner_released(self):
        """a corner was moved: the parking is checked again, and re-parked when 'by itself' is on"""
        if self.live.isChecked() and (self.zones or self.roads):
            self.settle_roads()
            self.park_roads()
            kind_, zi_ = (self.sel_corner or (None, -1, 0))[:2]
            only = [zi_] if kind_ == "zone" and 0 <= zi_ < len(self.zones) else (list(range(len(self.zones))) if self.zones else [])
            self._fill(only, quiet=True)
        else:
            self.prune_auto()
            self.refresh_parking(user=True)
        self._show_roads()
        self.changed()
        self._after_edit(True)
        self.set_hint("Corner moved. Drag any corner of the stand, a parking area or a keep-clear area.")

    def start_excl(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self._tracing_excl = True
        self.plan.begin("trace_parking")
        self.set_hint("Click each corner of the area to keep clear (flood zone, servitude, slope, trees). Double-click or press Enter to finish. No building or bay goes in it.")

    def clear_excl(self):
        self.excl = []
        self.refresh_parking(user=True)

    def trace_done(self, mode, role, pts):
        if mode not in ("trace_parking", "trace_road"):
            return super().trace_done(mode, role, pts)
        if self._tracing_road:
            self._tracing_road = False
            pth = self._tracing_path
            self._tracing_path = False
            self.roads.append({"pts": [list(q) for q in pts], "w": self.path_w.value() if pth else self.road_w.value(), "smooth": self.road_smooth.isChecked(), "left": 0, "right": 0, "start": 0.0})
            if pth:
                self.roads[-1]["path"] = True
            self.settle_roads()
            self._show_roads(len(self.roads) - 1)
            self.refresh_parking(user=True)
            self.set_hint("Pathway drawn. Drag the white squares to bend it, set its width above." if pth else "Road drawn. Now say where the bays go: set 'Bays on the left / right' for it (or press 'Park along the roads'). Drag the white squares to bend it.")
            return
        if self._tracing_excl:
            self._tracing_excl = False
            self.excl.append([list(q) for q in sl.si.clean(pts)])
            self.refresh_parking(user=True)
            self.set_hint("Keep-clear area added. Press Generate or Fill again to park round it.")
            return
        self._new_zone(sp.min_rect(sl.si.clean(pts)))           # drawn freehand, squared up when you finish
        if self.auto_fill.isChecked():
            self._fill([len(self.zones) - 1])
            self.set_hint("Area drawn and parked. Draw another area, or drag the corners/buildings and it follows.")
        else:
            self.set_hint("Area drawn. Press 'Fill the selected area'.")

    def _new_zone(self, pts, name=None):
        n = len(self.zones) + 1
        nm = name or "Parking area %d" % n
        while any(z["name"] == nm for z in self.zones):
            n += 1
            nm = "Parking area %d" % n
        self.zones.append({"name": nm, "poly": [list(p) for p in pts], "angle": None, "type": "Open"})
        self.sel_zone = len(self.zones) - 1
        self.refresh_parking(user=True)

    # --- copy and paste buildings
    def copy_buildings(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        if not rows and self.plan.sel >= 0:
            rows = [self.plan.sel]
        if not rows:
            self.set_hint("Click a building first, then copy it.")
            return
        for r in list(rows):
            rows += [g for g in self._group_rows(r) if g not in rows]
        bl, bk = self.buildings(), {b["block"].strip().lower(): b for b in self.blocks()}
        self.clip_bld = []
        for r in sorted(set(rows)):
            b = bl[r]
            self.clip_bld.append({"name": b["name"], "poly": [list(q) for q in b["poly"]] if b["poly"] else None, "x": b["x"], "y": b["y"], "w": b["w"], "d": b["d"],
                                  "cov": b["cov"], "grp": b["grp"], "block": dict(bk[b["name"].strip().lower()]) if b["name"].strip().lower() in bk else None})
        self.set_hint("%d building%s copied. Right-click the plan and choose 'Paste a copy here' (or Ctrl+V)." % (len(self.clip_bld), "" if len(self.clip_bld) == 1 else "s"))

    def _next_name(self, name, taken):
        import re
        m = re.match(r"^(.*?)(\d+)$", name.strip())
        pre = m.group(1) if m else name.strip() + " "
        n = max([int(x.group(2)) for x in (re.match(r"^(.*?)(\d+)$", t) for t in taken) if x and x.group(1) == pre] + [int(m.group(2)) if m else 0]) + 1
        return "%s%d" % (pre, n)

    def paste_buildings(self, w=None, count=1, gap=6.0, direction="right"):
        c = self.clip_bld
        if not c:
            self.set_hint("Copy a building first (right-click it).")
            return
        pts = [q for b in c for q in (b["poly"] or [(b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["d"])])]
        x0, y0, x1, y1 = min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts), max(q[1] for q in pts)
        tx, ty = (w[0], w[1]) if w is not None else ((x0 + x1) / 2.0 + 12.0, (y0 + y1) / 2.0 + 12.0)
        sx, sy = {"right": (1, 0), "left": (-1, 0), "down": (0, -1), "up": (0, 1)}.get(direction, (1, 0))
        stepx, stepy = sx * ((x1 - x0) + gap), sy * ((y1 - y0) + gap)
        made = 0
        for k in range(max(1, int(count))):
            dx, dy = tx - (x0 + x1) / 2.0 + k * stepx, ty - (y0 + y1) / 2.0 + k * stepy
            gid = ("g%d_%d" % (len(self.buildings()), k)) if len(c) > 1 else ""
            for b in c:
                taken = [x["name"] for x in self.buildings()]
                nm = self._next_name(b["name"], taken)
                d = {"name": nm, "cov": b["cov"], "grp": gid}
                if b["poly"]:
                    d["poly"] = [[q[0] + dx, q[1] + dy] for q in b["poly"]]
                else:
                    d.update({"x": round(b["x"] + dx, 2), "y": round(b["y"] + dy, 2), "w": b["w"], "d": b["d"]})
                self.add_building(d)
                if b.get("block"):
                    bb = b["block"]
                    self._row(preset_block(nm, bb["type"], bb["phase"]) if kb.module_preset(bb["type"]) else dict(bb, block=nm))
                made += 1
        self.sync_blocks()
        self._edited()
        self.set_hint("%d building%s pasted." % (made, "" if made == 1 else "s"))

    def paste_several(self, w=None):
        if not self.clip_bld:
            return
        d = QDialog(self)
        d.setWindowTitle("Paste several copies")
        f = QFormLayout(d)
        n = QSpinBox()
        n.setRange(1, 100)
        n.setValue(5)
        g = sl.spin(0, 100, 6, 1, " m")
        dr = QComboBox()
        dr.addItems(["right", "left", "down", "up"])
        f.addRow("How many copies", n)
        f.addRow("Space between them", g)
        f.addRow("In a row going", dr)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec():
            self.paste_buildings(w, n.value(), g.value(), dr.currentText())

    def building_menu(self, menu):
        w = getattr(self.plan, "_ctx_w", None)
        menu.addAction("Copy this building", self.copy_buildings)
        a = menu.addAction("Paste a copy here", lambda: self.paste_buildings(w))
        a.setEnabled(bool(self.clip_bld))
        a = menu.addAction("Paste several copies...", lambda: self.paste_several(w))
        a.setEnabled(bool(self.clip_bld))
        menu.addSeparator()
        super().building_menu(menu)

    def plan_menu(self, menu):
        w = getattr(self.plan, "_ctx_w", None)
        if self.clip_bld:
            menu.addAction("Paste a copy of the building here", lambda: self.paste_buildings(w))
            menu.addAction("Paste several copies of the building...", lambda: self.paste_several(w))
            menu.addSeparator()
        super().plan_menu(menu)

    # --- one road: curved here, straight there
    def road_flags(self, rd):
        f = rd.get("segs") or rd.get("smooth", True)
        n = len(rd["pts"]) - 1
        if isinstance(f, (list, tuple)):
            f = list(f)
            return (f + [f[-1] if f else True] * (n - len(f)))[:n]
        return [bool(f)] * n

    def road_at(self, w, tol=1.0):
        """(road, control piece, point on the centre line) under world point w, or None"""
        best = None
        for i, rd in enumerate(self.roads):
            c, sg, _t = sp._spline_seg(rd["pts"], 1.0, self.road_flags(rd))
            lim = self.road_wide(rd) / 2.0 + tol
            for k in range(len(c) - 1):
                d = sp.seg_pt(tuple(w), c[k], c[k + 1])
                if d <= lim and (best is None or d < best[0]):
                    best = (d, i, sg[k + 1], c[k])
        return best[1:] if best else None

    def _roads_changed(self):
        self._rq = (None, [], [], [])
        self.settle_roads()
        if self.zones or self.roads:
            self.park_roads()
            self._fill(list(range(len(self.zones))), quiet=True)
        else:
            self.refresh_parking(user=True)
        self._show_roads()
        self.changed()

    def set_road_curve(self, i, piece, curved):
        """piece = None: the whole road. Otherwise just that stretch between two bend points"""
        rd = self.roads[i]
        f = self.road_flags(rd)
        if piece is None:
            f = [curved] * len(f)
        else:
            f[piece] = curved
        rd["segs"] = f
        self.pick_road(i)
        self._roads_changed()
        self.set_hint("%s. Right-click the road again to change another stretch." % ("Curved" if curved else "Straight"))

    def add_road_point(self, i, piece, pt):
        rd = self.roads[i]
        f = self.road_flags(rd)
        rd["pts"].insert(piece + 1, [round(pt[0], 3), round(pt[1], 3)])
        rd.pop("base", None)
        f.insert(piece + 1, f[piece])
        rd["segs"] = f
        self.pick_road(i)
        self._roads_changed()
        self.set_hint("Bend point added. Drag its white square to bend the road there.")

    def remove_road_point(self, i, k):
        rd = self.roads[i]
        if len(rd["pts"]) <= 2 or not 0 <= k < len(rd["pts"]):
            return
        f = self.road_flags(rd)
        del rd["pts"][k]
        rd.pop("base", None)
        del f[k - 1 if k > 0 else 0]
        rd["segs"] = f
        self.sel_corner = None
        self._roads_changed()
        self.set_hint("Point removed. A road keeps at least two points.")

    def remove_corner(self, h):
        """delete the selected corner: a road point (a road keeps 2), a parking or keep-clear area corner (keeps 3)"""
        kind, i, k = h
        self.sel_corner = None
        if kind == "road" and 0 <= i < len(self.roads):
            self.remove_road_point(i, k)
        elif kind in ("zone", "excl"):
            pl = self.zones[i]["poly"] if kind == "zone" and i < len(self.zones) else (self.excl[i] if kind == "excl" and i < len(self.excl) else None)
            if pl is None or len(pl) <= 3 or not 0 <= k < len(pl):
                self.set_hint("An area needs at least three corners.")
                self.plan.update()
                return
            del pl[k]
            if kind == "zone":
                self._fill([i], quiet=True)
            else:
                self.prune_auto()
                self.refresh_parking(user=True)
            self._show_roads()
            self.changed()
            self._after_edit(True)
            self.set_hint("Corner removed.")
        else:
            self.set_hint("The stand's corners are changed in the first step.")
        self.plan.update()

    def pick_road(self, i):
        if getattr(self, "road_cb", None) is not None and 0 <= i < len(self.roads) and self.road_cb.currentIndex() != i:
            self.road_cb.setCurrentIndex(i)

    def zone_edge_at(self, w, tol):
        """the parking area whose border is under world point w, or -1 (corners are handled first)"""
        best, hit = tol, -1
        for i, z in enumerate(self.zones):
            pl = z["poly"]
            if z["name"] == "Whole stand":                          # its border is the stand's own: left to the stand's edge menu
                continue
            for k in range(len(pl)):
                d = sp.seg_pt(tuple(w), tuple(pl[k]), tuple(pl[(k + 1) % len(pl)]))
                if d < best:
                    best, hit = d, i
        return hit

    def zone_inside_at(self, w):
        for i in range(len(self.zones) - 1, -1, -1):
            if sp.pip(tuple(w), [tuple(q) for q in self.zones[i]["poly"]]):
                return i
        return -1

    def pick_zone(self, i):
        self.sel_zone = i
        if 0 <= i < self.zt.rowCount():
            self.zt.selectRow(i)
        self.plan.update()

    def zone_released(self):
        """a whole parking area was dragged: its bays are laid again where it now stands (the road bays follow it), whatever the 'by itself' box says"""
        self.settle_roads()
        self._fill(list(range(len(self.zones))), quiet=True)
        self._show_roads()
        self.changed()
        self._after_edit(True)
        self.set_hint("Parking area moved and parked again.")

    def copy_zone(self, i):
        if 0 <= i < len(self.zones):
            self.clip_zone = {k: (copy.deepcopy(v) if k != "name" else v) for k, v in self.zones[i].items()}
            self.set_hint("Parking area copied. Right-click on the plan and choose 'Paste a copy here' (or Ctrl+V).")

    def paste_zone(self, w=None):
        z = self.clip_zone
        if z is None:
            return
        pl = z["poly"]
        cx, cy = sum(q[0] for q in pl) / len(pl), sum(q[1] for q in pl) / len(pl)
        tx, ty = (w[0], w[1]) if w is not None else (cx + 12.0, cy + 12.0)
        n = len(self.zones) + 1
        nm = "Parking area %d" % n
        while any(x["name"] == nm for x in self.zones):
            n += 1
            nm = "Parking area %d" % n
        nz = copy.deepcopy(z)
        nz["name"] = nm
        nz["poly"] = [[round(q[0] - cx + tx, 3), round(q[1] - cy + ty, 3)] for q in pl]
        self.zones.append(nz)
        self.sel_zone = len(self.zones) - 1
        self._fill([len(self.zones) - 1])
        self.set_hint("Pasted as %s. Drag its border to move it." % nm)

    def delete_zone(self, i):
        self.pick_zone(i)
        self.remove_zone()

    def zone_whole_stand(self):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self._new_zone(v, "Whole stand")

    def _zone_opts(self, *_a):
        if self._pbusy or getattr(self, "_zo_busy", False):
            return
        i = self.zt.currentRow()
        if 0 <= i < len(self.zones):
            self.zones[i]["join"] = self.join_cb.isChecked()
            self.zones[i]["max"] = self.max_sp.value()
            self.zones[i]["side"] = self.side_cb.currentIndex()
            self.zones[i]["style"] = self.style_cb.currentIndex()
            self.zones[i]["bay_angle"] = (90, 60, 45)[self.ang_cb.currentIndex()]
            self._fill([i])

    def _zone_picked(self):
        i = self.zt.currentRow()
        if 0 <= i < len(self.zones):
            self._zo_busy = True
            try:
                self.join_cb.setChecked(bool(self.zones[i].get("join", True)))
                self.max_sp.setValue(int(self.zones[i].get("max", 0)))
                self.side_cb.setCurrentIndex(int(self.zones[i].get("side", 0)))
                self.style_cb.setCurrentIndex(int(self.zones[i].get("style", 0)))
                self.ang_cb.setCurrentIndex({90: 0, 60: 1, 45: 2}.get(int(self.zones[i].get("bay_angle", 90)), 0))
            finally:
                self._zo_busy = False

    def _zone_type(self, i, t):
        if self._pbusy or not (0 <= i < len(self.zones)):
            return
        self.zones[i]["type"] = t
        for b in self.bays:
            if b.get("auto") and b.get("zone") == self.zones[i]["name"]:
                b["type"] = t
        self.refresh_parking(user=True)

    def _zone_edited(self, it):
        if self._pbusy or it.row() >= len(self.zones):
            return
        z = self.zones[it.row()]
        if it.column() == 0:
            old, new = z["name"], it.text().strip() or z["name"]
            for b in self.bays:
                if b.get("zone") == old:
                    b["zone"] = new
            z["name"] = new
        elif it.column() == 1:
            t = it.text().strip().lower()
            z["angle"] = None if t in ("", "auto") else _num(t)
        self.refresh_parking(user=True)

    def remove_zone(self):
        i = self.zt.currentRow()
        if not (0 <= i < len(self.zones)):
            QMessageBox.information(self, self.TITLE, "Click an area in the list first.")
            return
        nm = self.zones[i]["name"]
        self.bays = [b for b in self.bays if b.get("zone") != nm or not b.get("auto")]
        del self.zones[i]
        self.sel_zone = -1
        self.refresh_parking(user=True)

    def _fill(self, idxs, quiet=False):
        if self.roads and not getattr(self, "_in_fill", False):
            self._in_fill = True
            try:
                self.park_roads()
            finally:
                self._in_fill = False
        if not idxs and quiet:
            self.prune_auto()
            self.refresh_parking(user=True)
            return
        if not idxs:
            QMessageBox.information(self, self.TITLE, "Draw a parking area first, or press 'Use the whole stand'.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            site, r = self.site_obj(), self.rules_now()
            for i in idxs:
                z = self.zones[i]
                self.bays = [b for b in self.bays if not (b.get("auto") and b.get("zone") == z["name"])]
                keep = list(self.bays)
                roads = self.road_quads_all() if (z.get("join", True) and self.roads) else None
                got = sp.fill([tuple(p) for p in z["poly"]], site, r, z.get("angle"), keep, z["name"], roads, int(z.get("max", 0)),
                              [self.road_angle_near(z["poly"])] if roads else (), 90 - int(z.get("bay_angle", 90)))
                for b_ in got:
                    b_["type"] = z.get("type", "Open")
                self.bays += got
        finally:
            QApplication.restoreOverrideCursor()
        self.prune_auto()
        self.refresh_parking(user=True)

    def prune_auto(self):
        """bays the program placed itself that break a rule (stand on a road, overlap, outside their area) are dropped, so moving things never leaves stray bays behind"""
        if not self.bays:
            return 0
        site, r = self.site_obj(), self.rules_now()
        zp = {z["name"]: [tuple(q) for q in z["poly"]] for z in self.zones if len(z["poly"]) >= 3}
        kept = [b for b in self.bays if not b.get("auto")]
        out, n = [], 0
        for b in self.bays:
            if not b.get("auto"):
                out.append(b)
                continue
            poly = zp.get(b.get("zone"))
            ok = not sp.problems(b, r, site, kept)
            if ok and poly is not None and not sp.inside(sp.bay_poly(b, r), poly):
                ok = False
            if ok and b.get("rz") in zp and not sp._in_zone(b, r, zp[b["rz"]]) and not any(z["name"] == b["rz"] and z.get("side", 0) for z in self.zones):
                ok = False
            if ok and str(b.get("zone", "")).startswith("Road") and b.get("rz") is None and False:
                ok = False
            if ok:
                kept.append(b)
                out.append(b)
            else:
                n += 1
        self.bays = out
        return n

    def zone_hugs_road(self, z):
        """the whole parking area lies within reach of a road (a strip beside it)"""
        if not z.get("join", True) or not self.roads:
            return False
        reach = self.r_aisle.value() / 2.0 + self.r_l.value() + 12.0
        for q in z["poly"]:
            d = 1e18
            for rd in self.roads:
                c = sp.spline(rd["pts"], 2.0, (rd.get("segs") or rd.get("smooth", True)))
                d = min([d] + [sp.seg_pt(tuple(q), c[i], c[i + 1]) for i in range(len(c) - 1)])
            if d > reach:
                return False
        return True

    def fill_selected(self):
        i = self.zt.currentRow()
        if i < 0 and len(self.zones) == 1:
            i = 0
        if i < 0:
            QMessageBox.information(self, self.TITLE, "Click an area in the list first, or press Fill all areas.")
            return
        self._fill([i])

    def fill_all(self):
        self._fill(list(range(len(self.zones))))

    def clear_selected(self):
        i = self.zt.currentRow()
        if not (0 <= i < len(self.zones)):
            QMessageBox.information(self, self.TITLE, "Click an area in the list first.")
            return
        nm = self.zones[i]["name"]
        self.bays = [b for b in self.bays if not (b.get("auto") and b.get("zone") == nm)]
        self.refresh_parking(user=True)

    def clear_all_bays(self):
        if self.bays and QMessageBox.question(self, self.TITLE, "Remove all %d bays?" % len(self.bays)) != QMessageBox.StandardButton.Yes:
            return
        self.bays = []
        self.sel_bay = -1
        self.refresh_parking(user=True)

    def start_add_bay(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self.plan.begin("add_bay")
        self.set_hint("Click where the bay goes. R turns it, Esc stops. Red means it breaks a rule.")

    def _default_angle(self):
        if self.bays:
            return self.bays[-1]["a"]
        return 90.0

    def add_bay_at(self, w):
        b = sp.single(round(w[0] * 20) / 20, round(w[1] * 20) / 20, getattr(self.plan, "_add_angle", self._default_angle()))
        b["type"] = self.new_type.currentText()
        self.bays.append(b)
        self.sel_bay = len(self.bays) - 1
        self.refresh_parking(user=True)
        self.park_selected()

    def _set_bay_type(self, *_a):
        if 0 <= self.sel_bay < len(self.bays):
            self.bays[self.sel_bay]["type"], self.bays[self.sel_bay]["auto"] = self.new_type.currentText(), False
            self.refresh_parking(user=True)

    def rotate_bay(self):
        if self.plan.mode == "add_bay":
            self.plan._add_angle = (getattr(self.plan, "_add_angle", self._default_angle()) + 90.0) % 360
            self.plan.update()
            return
        if not (0 <= self.sel_bay < len(self.bays)):
            QMessageBox.information(self, self.TITLE, "Click a bay on the plan first.")
            return
        b = self.bays[self.sel_bay]
        b["a"], b["auto"] = (b["a"] + 90.0) % 360, False
        self.refresh_parking(user=True)
        self.park_selected()

    def delete_bay(self):
        if not (0 <= self.sel_bay < len(self.bays)):
            QMessageBox.information(self, self.TITLE, "Click a bay on the plan first.")
            return
        del self.bays[self.sel_bay]
        self.sel_bay = -1
        self.refresh_parking(user=True)

    def use_mix(self):
        """the unit mix (1, 2, 3 bed) gives the bays a unit needs on average and the beds; the bays per unit on the Schedule step is set from it"""
        tot = sum(w[0].value() for w in self.mix.values()) or 1.0
        per = sum(w[0].value() * w[1].value() for w in self.mix.values()) / tot
        beds = sum(w[0].value() * int(k) for k, w in self.mix.items()) / tot
        self.f["bays_per_unit"].setValue(round(per, 3))
        u = self.sdp()["total"]["units"]
        self.mix_lbl.setText("Average %.2f bays and %.2f beds a unit. %d units = %d beds, %d bays needed." % (per, beds, u, round(u * beds), self.sdp()["bays_needed"]))
        self.refresh_parking(user=True)

    def more_like_this(self):
        """directed variation: small changes to the last generated layout (size, spacing), each saved as a scheme"""
        o = getattr(self, "_last_opts", None)
        if not o:
            QMessageBox.information(self, self.TITLE, "Generate a layout first, then ask for more like it.")
            return
        base = dict(o, count=0, parking=True)
        vs = [dict(w=o["w"] * 0.9, d=o["d"] * 1.1), dict(w=o["w"] * 1.1, d=o["d"] * 0.9), dict(front=max(10.0, o["front"] - 2.5)), dict(front=o["front"] + 3.0),
              dict(side=max(3.0, o["side"] - 2.0)), dict(side=o["side"] + 3.0)]
        for i, v_ in enumerate(vs):
            self.generate(dict(base, **v_))
            QApplication.processEvents()
            self.save_scheme()
            self.schemes[-1]["name"] = "Variation %d" % (i + 1)
        self._show_schemes()
        self.set_hint("%d variations saved as schemes. Pick the goal next to the list to see the best one." % len(vs))

    def find_options(self, filt=None):
        """the site solver's 'filtered options': every block type in both directions is solved; those that meet the limits are saved as schemes"""
        if filt is None:
            d = QDialog(self)
            d.setWindowTitle("Find options")
            f = QFormLayout(d)
            lab = QLabel("Each block type is tried, in both directions, with as many blocks as the parking allows. The options that meet your limits are saved as schemes to compare. 0 means no limit.")
            lab.setWordWrap(True)
            lab.setMinimumWidth(400)
            f.addRow(lab)
            mu, mc = QSpinBox(), sl.spin(0, 100, 0, 1, " %")
            mu.setRange(0, 5000)
            f.addRow("At least this many units", mu)
            f.addRow("Coverage not more than", mc)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(d.accept)
            bb.rejected.connect(d.reject)
            f.addRow(bb)
            if not d.exec():
                return
            filt = {"units": mu.value(), "cov": mc.value()}
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        base = {"prefix": "H", "phase": "Phase 1", "side": 6.0, "front": 17.5, "count": 0, "parking": True}
        kept, best, tried = 0, None, 0
        env0 = sl.envelope(self.verts(), [e["sb"] for e in self.edges()]) or self.verts()
        turned = sp._longest_dir(env0) + 90.0
        for typ in kb.module_names()[:3]:
            m = kb.module_preset(typ)
            area = m["gross_m2"] / float(m["storeys"])
            w = round(math.sqrt(area * 2.2), 1)
            for th in (None, turned):
                o = dict(base, type=typ, w=w, d=round(area / w, 1), theta=th)
                self.generate(o)
                QApplication.processEvents()
                tried += 1
                a = self.sdp()
                ok = a["total"]["units"] >= filt.get("units", 0) and a["bays"] >= a["bays_needed"] and (not filt.get("cov") or a["cov"] <= filt["cov"])
                if ok:
                    self.save_scheme()
                    self.schemes[-1]["name"] = "%s%s" % (typ, "" if th is None else " (turned)")
                    kept += 1
                    if best is None or a["total"]["units"] > best[0]:
                        best = (a["total"]["units"], len(self.schemes) - 1)
        self._show_schemes()
        if best is not None:
            self.scheme_cb.setCurrentIndex(best[1])
            self.load_scheme()
        self.set_hint("%d of %d options meet your limits and are saved as schemes (the one with the most units is open)." % (kept, tried))

    def new_plan(self, ask=True):
        """start a fresh SDP: the stand, buildings, parking areas, bays, schedule and schemes are cleared"""
        if ask and (self.verts() or self.buildings() or self.bays):
            if QMessageBox.question(self, self.TITLE, "Start a new plan? The stand, buildings, parking and schedule on this page are cleared (saved schemes too).") != QMessageBox.StandardButton.Yes:
                return
        proj = self.f["project"].text() if "project" in self.f else ""
        self.schemes = []
        self.excl = []
        self.roads = []
        self.set_state({})
        self.schemes = []
        self._show_schemes()
        if proj:
            self.f["project"].setText(proj)
        self.steps.go(0)
        self.set_hint("New plan. Set the stand first: type its sides or trace it, then place the buildings and draw the parking areas.")

    # ------------------------------------------------------------- accessible / EV, schemes, export
    def assign_special(self):
        """accessible and EV bays: the auto bays nearest a building door (the building centre) are set aside"""
        auto = [b for b in self.bays if b.get("auto") and b.get("type", "Open") != "Tandem"]
        zt = {z["name"]: z.get("type", "Open") for z in self.zones}
        for b in auto:
            if b.get("type") in ("Accessible", "EV"):
                b["type"] = zt.get(b.get("zone"), "Open")
            sp.unwiden(b)
        cs = []
        for b in self.buildings():
            if kind_of(b["name"]) == "block":
                P = bpoly(b)
                cs.append((sum(q[0] for q in P) / len(P), sum(q[1] for q in P) / len(P)))
        if not auto or not cs:
            QMessageBox.information(self, self.TITLE, "Place buildings and fill the parking first.")
            return
        auto.sort(key=lambda b: min(math.hypot(b["x"] - c[0], b["y"] - c[1]) for c in cs))
        na = sp.accessible_required(len(self.bays)) if self.ada_tab.isChecked() else int(math.ceil(len(auto) * self.ada_pct.value() / 100.0 - 1e-9))
        na = min(na, len(auto))
        ne = int(math.ceil(len(auto) * self.ev_pct.value() / 100.0 - 1e-9))
        r = self.rules_now()
        gone = []
        for i, b in enumerate(auto):
            if i < na:
                b["type"] = "Accessible"
                gone += sp.widen(b, [x for x in self.bays if x not in gone], r, r["ada_w"])      # 3.7 m wide: it takes the room of the bay beside it
            elif i < na + ne:
                b["type"] = "EV"
        self.bays = [b for b in self.bays if not any(b is g for g in gone) or b.get("type") == "Accessible"]
        self.refresh_parking(user=True)
        self.set_hint("%d accessible (%.1f m wide) and %d EV bays set aside, nearest the buildings." % (na, r["ada_w"], ne))

    def _scheme_numbers(self):
        a = self.sdp()
        t = a["total"]
        return {"units": t["units"], "bays": a["bays"], "need": a["bays_needed"], "cov": round(a["cov"], 2), "far": round(a["far"], 3),
                "per_unit": round(a["bays"] / float(t["units"]), 2) if t["units"] else 0.0, "per_bay": round(a["area"] / a["bays"]) if a["bays"] else 0,
                "blocks": len(self.blocks()), "ada": sum(1 for b in self.bays if b.get("type") == "Accessible"), "ev": sum(1 for b in self.bays if b.get("type") == "EV")}

    def save_scheme(self):
        st = self.state()
        st.pop("schemes", None)
        n = len(self.schemes) + 1
        self.schemes.append({"name": "Scheme %d" % n, "num": self._scheme_numbers(), "state": st})
        self._show_schemes()
        self.changed()
        self.set_hint("Saved as Scheme %d. Change the layout and save again to compare." % n)

    def _show_schemes(self):
        if getattr(self, "scheme_cb", None) is None:
            return
        self.scheme_cb.clear()
        self.scheme_cb.addItems([sc_["name"] for sc_ in self.schemes])
        if not self.schemes:
            self.scheme_lbl.setText("")
            return
        g = self.goal_cb.currentIndex()
        key = [lambda n: n["units"], lambda n: n["bays"] - n["need"], lambda n: -n["cov"], lambda n: -n["per_bay"] if n["per_bay"] else -1e9][g]
        ok_ = [i for i, x in enumerate(self.schemes) if x["num"]["bays"] >= x["num"]["need"]] or list(range(len(self.schemes)))
        star = max(ok_, key=lambda i: key(self.schemes[i]["num"]))
        h = "<table cellpadding='3'><tr><th align=left>Scheme</th><th>Blocks</th><th>Units</th><th>Bays</th><th>Needed</th><th>Per unit</th><th>m2 / bay</th><th>Cover %</th><th>FAR</th></tr>"
        for si, sc_ in enumerate(self.schemes):
            n = sc_["num"]
            col = "#2e9e5b" if n["bays"] >= n["need"] else "#e0243a"
            h += "<tr><td>%s</td><td align=right>%d</td><td align=right>%d</td><td align=right style='color:%s'><b>%d</b></td><td align=right>%d</td><td align=right>%.2f</td><td align=right>%d</td><td align=right>%.1f</td><td align=right>%.2f</td></tr>" % (
                ("&#9733; " if si == star else "") + sc_["name"], n["blocks"], n["units"], col, n["bays"], n["need"], n["per_unit"], n["per_bay"], n["cov"], n["far"])
        self.scheme_lbl.setText(h + "</table>")

    def load_scheme(self):
        i = self.scheme_cb.currentIndex()
        if not (0 <= i < len(self.schemes)):
            return
        keep = self.schemes
        self.set_state(dict(self.schemes[i]["state"]))
        self.schemes = keep
        self._show_schemes()
        self.scheme_cb.setCurrentIndex(i)
        self.plan.fit()

    def delete_scheme(self):
        i = self.scheme_cb.currentIndex()
        if 0 <= i < len(self.schemes):
            del self.schemes[i]
            self._show_schemes()
            self.changed()

    def export_csv(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export numbers", "sdp_numbers.csv", "CSV (*.csv)")
        if not path:
            return
        a = self.sdp()
        rows = [["Item", "Value"], ["Units", a["total"]["units"]], ["Bays counted", a["bays"]], ["Bays needed", a["bays_needed"]], ["Site area m2", "%.2f" % a["area"]],
                ["Coverage %", "%.2f" % a["cov"]], ["FAR", "%.4f" % a["far"]], ["Density u/ha", "%.1f" % a["density"]]]
        for k, (ok, bad) in sorted(self.bay_counts().items()):
            rows.append(["Bays - " + k, ok + bad])
        rows += [[], ["Block", "Phase", "Type", "Storeys", "Units", "Footprint m2", "Floor area m2"]]
        rows += [[b["block"], b["phase"], b["type"], b["storeys"], b["units"], "%.2f" % b["foot"], "%.2f" % b["floor"]] for b in self.blocks()]
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        self.set_hint("Numbers saved to " + path)

    def export_dxf(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export to CAD", "sdp_layout.dxf", "DXF (*.dxf)")
        if not path:
            return
        import ezdxf
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        for name, col in (("STAND", 7), ("BUILDINGS", 1), ("BAYS", 3), ("BAY_ACCESSIBLE", 5), ("BAY_EV", 6), ("BAY_OTHER", 30), ("PARKING_AREAS", 8), ("BAY_NUMBERS", 3), ("ROADS", 9), ("PATHWAYS", 2), ("ROAD_CENTRELINE", 4)):
            doc.layers.add(name, color=col)
        poly = lambda pts, layer: msp.add_lwpolyline([(q[0], q[1]) for q in pts], close=True, dxfattribs={"layer": layer})
        if len(self.verts()) >= 3:
            poly(self.verts(), "STAND")
        for b in self.buildings():
            poly(bpoly(b), "BUILDINGS")
            P = bpoly(b)
            msp.add_text(b["name"], dxfattribs={"layer": "BUILDINGS", "height": 1.5, "insert": (sum(q[0] for q in P) / len(P), sum(q[1] for q in P) / len(P))})
        for z in self.zones:
            poly(z["poly"], "PARKING_AREAS")
        for rd in self.roads:
            c = sp.spline(rd["pts"], 1.5, (rd.get("segs") or rd.get("smooth", True)))
            msp.add_lwpolyline(c, dxfattribs={"layer": "ROAD_CENTRELINE"})
            L = [q[0] for q in self.road_geom(rd)]
            Rr = [q[3] for q in self.road_geom(rd)]
            if L:
                last = self.road_geom(rd)[-1]
                lay = "PATHWAYS" if rd.get("path") else "ROADS"
                msp.add_lwpolyline(L + [last[1]], dxfattribs={"layer": lay})
                msp.add_lwpolyline(Rr + [last[2]], dxfattribs={"layer": lay})
        r = self.rules_now()
        for b in self.bays:
            t = b.get("type", "Open")
            msp.add_text(str(self.bays.index(b) + 1), dxfattribs={"layer": "BAY_NUMBERS", "height": 0.7, "insert": (b["x"] - 0.4, b["y"] - 0.35)})
            poly(sp.bay_poly(b, r), {"Accessible": "BAY_ACCESSIBLE", "EV": "BAY_EV"}.get(t, "BAYS" if t == "Open" else "BAY_OTHER"))
        doc.saveas(path)
        self.set_hint("Drawing saved to " + path)

    # ------------------------------------------------------------- the solver
    def _gen_names(self):
        return [n for n in getattr(self, "gen_names", [])]

    def _evaluate(self, slots, n, upb, r, own):
        """parking for n blocks placed in the first n slots: counted bays against the bays the units need"""
        v = self.verts()
        env = sl.envelope(v, [e["sb"] for e in self.edges()]) if self.r_lines.isChecked() else None
        site = sp.Site(v, own + [[tuple(q) for q in e] for e in self.excl] + [list(R) for R in slots[:n]], env, roads=self.road_quads_all(), road_owner=self.road_owner_all())
        bays = sp.fill(v, site, r, None, [], "gen")
        sd = self.site()
        need = sp.required(n * upb, _num(sd.get("bays_per_unit"), 1.5), int(_num(sd.get("visitor_per"))))
        return len(bays), need

    def generate(self, opts=None):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        if opts is None:
            d = _GenerateDialog(self)
            if not d.exec():
                return
            opts = {"type": d.typ.currentText(), "prefix": d.prefix.text().strip(), "phase": d.phase.text().strip(), "w": d.w.value(), "d": d.d.value(),
                    "side": d.side.value(), "front": d.front.value(), "count": d.count.value() if d.mode.currentIndex() == 1 else 0, "parking": d.parking.isChecked()}
        self._last_opts = dict(opts)
        typ, pre, phase = opts["type"], opts.get("prefix") or "H", opts.get("phase") or "Phase 1"
        m = kb.module_preset(typ)
        r = self.rules_now()
        self._pbusy = True
        old = {n.lower() for n in self._gen_names()}
        rows = [i for i, b in enumerate(self.buildings()) if b["name"].lower() in old]
        for i in sorted(rows, reverse=True):
            self.bt.removeRow(i)
        self._pbusy = False
        own = [bpoly(b) for b in self.buildings()] + [[tuple(q) for q in e] for e in self.excl] + self.road_quads_all()
        env = sl.envelope(v, [e["sb"] for e in self.edges()]) or v
        slots = sp.block_slots(env, own, opts["w"], opts["d"], opts["side"], opts["front"], opts.get("theta"))
        if not slots:
            QMessageBox.information(self, self.TITLE, "No block of %.1f x %.1f m fits inside the building lines. Make the block smaller or the gaps less." % (opts["w"], opts["d"]))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if opts.get("count"):
                n = min(opts["count"], len(slots))
            else:                                                        # the most blocks whose parking still meets the requirement
                lo, hi, n = 0, len(slots), 0
                c, need = self._evaluate(slots, hi, m["units"], r, own)       # all of them first: often the parking is plenty
                if c >= need:
                    lo = hi
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    c, need = self._evaluate(slots, mid, m["units"], r, own)
                    if c >= need:
                        lo, n = mid, mid
                    else:
                        hi = mid - 1
                n = lo or 1
        finally:
            QApplication.restoreOverrideCursor()
        self.gen_names = []
        was = self._pbusy
        self._pbusy = True
        nb0 = self.t.rowCount()
        for k_ in range(n):
            R = slots[k_]
            xs, ys = [q[0] for q in R], [q[1] for q in R]
            nm = "%s%d" % (pre, k_ + 1)
            if nm.lower() in {b["name"].lower() for b in self.buildings()}:
                nm = "%s%d" % (pre, self.bt.rowCount() + 1)
            self.add_building({"name": nm, "poly": R, "cov": True})
            self.gen_names.append(nm)
            have = [bb["block"].lower() for bb in self.blocks()]
            if nm.lower() not in have:
                self._row(preset_block(nm, typ, phase))
        for r_ in range(self.t.rowCount() - 1, -1, -1):                  # the schedule of the blocks made before goes
            if self.t.item(r_, 0).text().strip().lower() in old and self.t.item(r_, 0).text().strip() not in self.gen_names:
                self.t.removeRow(r_)
        self._pbusy = was
        self.sync_blocks()
        if opts.get("parking", True):
            self.zones = [z for z in self.zones if z["name"] != "Whole stand"]
            self.bays = [b for b in self.bays if not (b.get("auto") and b.get("zone") == "Whole stand")]
            self.park_roads()
            self._new_zone(v, "Whole stand")
            self._fill([len(self.zones) - 1])
        self.plan.fit()
        self._edited()
        a = self.sdp()
        self.set_hint("%d blocks (%d units) placed. Bays: %d counted for %d needed." % (n, a["total"]["units"], a["bays"], a["bays_needed"]))

    # ------------------------------------------------------------- refuse area and gatehouse
    def add_refuse(self):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        n = sum(1 for b in self.buildings() if kind_of(b["name"]) == "refuse") + 1
        x0, y0 = min(p[0] for p in v), min(p[1] for p in v)
        self.add_building({"name": "Refuse area" if n == 1 else "Refuse area %d" % n, "x": x0 + 2.0, "y": y0 + 2.0, "w": self.refuse_w.value(), "d": self.refuse_d.value(), "cov": False})
        self.bt.selectRow(self.bt.rowCount() - 1)
        self.set_hint("Refuse area added. Drag it into place, or press 'Suggest a place for it'.")

    def size_refuse(self):
        u = sum(b["units"] for b in self.blocks())
        if not u:
            QMessageBox.information(self, self.TITLE, "Fill in the units in the schedule first (fourth step).")
            return
        a = max(kb.refuse_area(u), 6.0)
        w = round(math.sqrt(a * 2.0), 1)
        self.refuse_w.setValue(w)
        self.refuse_d.setValue(round(a / w, 1))
        self.set_hint("Refuse area for %d units: about %.0f m2 (%.1f x %.1f m)." % (u, a, self.refuse_w.value(), self.refuse_d.value()))

    def add_gatehouse(self):
        """the gate house system of the reference plan: a guard house (19 m2) and an ablution area (30 m2) on the plan, and the office (60 m2) over the ablution area in the schedule"""
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        x0, y0 = min(p[0] for p in v), min(p[1] for p in v)
        have = {b["name"].lower() for b in self.buildings()}
        parts = {n: a for n, u, a, c in kb.gatehouse_set()}
        x = x0 + 6.0
        for nm, area in (("Gatehouse - guard house", parts["Guard House"]), ("Gatehouse - ablution", parts["Ablution Area"])):
            if nm.lower() in have:
                continue
            w = round(math.sqrt(area * 1.25), 1)
            self.add_building({"name": nm, "x": x, "y": y0 + 2.0, "w": w, "d": round(area / w, 1), "cov": True})
            x += w + 1.0
        self.sync_blocks()
        names = {b["block"].lower() for b in self.blocks()}
        if "gatehouse - office (first floor)" not in names:
            self._row(blank_block("Gatehouse - office (first floor)", typ="Gatehouse", storeys=1, floor=parts["Gate House Office"], cov=False))
        for r_, b_ in enumerate(self.blocks()):                      # a gate house part counts its footprint as floor area
            if kind_of(b_["block"]) == "gate" and b_["floor"] == 0 and b_["foot"] > 0:
                self.t.item(r_, 9).setText("%.2f" % b_["foot"])
        self._edited()
        self.bt.selectRow(self.bt.rowCount() - 1)
        self.set_hint("Gate house added: guard house and ablution area. Drag them to the entrance. The office is in the schedule.")

    def gatehouse_from_ifc(self):
        self.footprint_from_ifc()
        self.set_hint("Name the new building 'Gatehouse' in the list (second step) so the sheet knows what it is.")

    def gatehouse_from_drawing(self):
        self.steps.go(1)
        self.load_drawing("fp")
        self.set_hint("Load the drawing, then 'Pick a building from the drawing' or trace the gatehouse. Name it 'Gatehouse' in the list.")

    def suggest_refuse(self):
        """a place for the refuse area: inside the stand, 0.5 m clear of buildings, bays and aisles, and as near the street as it goes"""
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        rows = [i for i, b in enumerate(self.buildings()) if kind_of(b["name"]) == "refuse"]
        if not rows:
            self.add_refuse()
            rows = [self.bt.rowCount() - 1]
        r_i = rows[-1]
        r = self.rules_now()
        w, d = self.refuse_w.value(), self.refuse_d.value()
        others = [bpoly(b) for i, b in enumerate(self.buildings()) if i != r_i]
        obst = others + [sp.bay_poly(b, r) for b in self.bays] + [sp.aisle_poly(b, r) for b in self.bays]
        edges = self.edges()
        st = [i for i, e in enumerate(edges) if e["kind"] == "Street"] or [0]
        m = [((v[i][0] + v[(i + 1) % len(v)][0]) / 2, (v[i][1] + v[(i + 1) % len(v)][1]) / 2) for i in st]
        x0, y0, x1, y1 = sp.bbox(v)
        best, bd = None, 1e18
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for ang in (0.0, 90.0):
                x = x0
                while x <= x1:
                    y = y0
                    while y <= y1:
                        c = (x + w / 2, y + d / 2) if ang == 0 else (x + d / 2, y + w / 2)
                        R = sp.rect(c[0], c[1], ang, w, d)
                        dist = min(math.hypot(c[0] - q[0], c[1] - q[1]) for q in m)
                        if dist < bd and sp.inside(R, v) and all(sp.poly_dist(R, o) >= r["bld"] - 1e-6 if o in others else not sp.overlap(R, o) for o in obst):
                            best, bd = R, dist
                        y += 1.0
                    x += 1.0
        finally:
            QApplication.restoreOverrideCursor()
        if best is None:
            QMessageBox.information(self, self.TITLE, "There is no free spot of %.1f x %.1f m. Make the area smaller, or move a building or the bays." % (w, d))
            return
        self._set_poly(r_i, best)
        self.plan.update()
        self._after_edit(True)
        self.set_hint("Refuse area placed near the street. Drag it if you want it elsewhere.")

    # ------------------------------------------------------------- the plan, moved and turned together
    def shift_world(self, dx, dy):
        super().shift_world(dx, dy)
        for z in getattr(self, "zones", []):
            z["poly"] = [[x + dx, y + dy] for x, y in z["poly"]]
        self.excl = [[[x + dx, y + dy] for x, y in e] for e in getattr(self, "excl", [])]
        for r_ in getattr(self, "roads", []):
            r_["pts"] = [[x + dx, y + dy] for x, y in r_["pts"]]
            if r_.get("base"):
                r_["base"] = [[x + dx, y + dy] for x, y in r_["base"]]
        for b in getattr(self, "bays", []):
            b["x"] += dx
            b["y"] += dy

    def rotate_world(self, a, cx, cy):
        super().rotate_world(a, cx, cy)
        for z in getattr(self, "zones", []):
            z["poly"] = [list(q) for q in self._rot_pts([tuple(p) for p in z["poly"]], a, cx, cy)]
            if z.get("angle") is not None:
                z["angle"] = (z["angle"] + math.degrees(a)) % 180
        self.excl = [[list(q) for q in self._rot_pts([tuple(p) for p in e], a, cx, cy)] for e in getattr(self, "excl", [])]
        for r_ in getattr(self, "roads", []):
            r_["pts"] = [list(q) for q in self._rot_pts([tuple(p) for p in r_["pts"]], a, cx, cy)]
            if r_.get("base"):
                r_["base"] = [list(q) for q in self._rot_pts([tuple(p) for p in r_["base"]], a, cx, cy)]
        for b in getattr(self, "bays", []):
            (b["x"], b["y"]), = self._rot_pts([(b["x"], b["y"])], a, cx, cy)
            b["a"] = (b["a"] + math.degrees(a)) % 360

    # ------------------------------------------------------------- drawing the parking on the plan
    def draw_parking(self, p, W, H, v, snapshot=False):
        s = v[0]
        to = lambda q: self.plan._sc(q, v, W, H)
        r = self.rules_now()
        from PySide6.QtCore import QRectF
        # 0.5 m round every building: the clear zone
        if r["bld"] > 0:
            for b in self.buildings():
                pen = QPen(QColor(240, 140, 20, 70), max(1.0, 2 * r["bld"] * s))
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF([to(q) for q in bpoly(b)]))
        from PySide6.QtCore import QRectF as _QR
        for b in self.buildings():
            k = kind_of(b["name"])
            if k == "block":
                continue
            col = QColor(150, 98, 40) if k == "refuse" else QColor(235, 150, 20)
            pl = QPolygonF([to(q) for q in bpoly(b)])
            p.setPen(QPen(col.darker(130), 1.6))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 190))
            p.drawPolygon(pl)
            if s > 3:
                f = QFont("Arial")
                f.setPixelSize(13 if W >= 900 else 10)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor("#ffffff") if k == "refuse" else QColor("#111111"))
                c = pl.boundingRect().center()
                p.drawText(_QR(c.x() - 70, c.y() - 9, 140, 18), int(Qt.AlignmentFlag.AlignCenter), b["name"])
        for rd in self.roads:
            pass
        road_col = QColor(128, 130, 138)
        p.setPen(QPen(road_col, 1.2))
        p.setBrush(road_col)
        self.road_quads_all()
        kinds = self._rq[3] if len(self._rq) > 3 else []
        for pth_ in (True, False):                                        # pathways (pavement) first, so the road covers where they end on it
            if pth_:
                pav = QColor(206, 196, 178)
                p.setPen(QPen(pav, 1.0))
                p.setBrush(pav)
            else:
                p.setPen(QPen(road_col, 1.2))
                p.setBrush(road_col)
            for q, k_ in zip(self._rq[1], kinds):
                if bool(k_) == pth_:
                    p.drawPolygon(QPolygonF([to(c_) for c_ in q]))
        if not snapshot and self.plan.mode == "select":                  # handles on every corner that can be dragged
            p.setPen(QPen(QColor("#222222"), 1))
            p.setBrush(QColor("#ffffff"))
            for pl in [self.verts()] + [z["poly"] for z in self.zones] + list(self.excl) + [r_["pts"] for r_ in self.roads]:
                for q in pl:
                    c = to(q)
                    p.drawRect(QRectF(c.x() - 4, c.y() - 4, 8, 8))
            sc_ = self.sel_corner
            if sc_ is not None:
                try:
                    q = {"road": lambda: self.roads[sc_[1]]["pts"], "excl": lambda: self.excl[sc_[1]], "zone": lambda: self.zones[sc_[1]]["poly"], "stand": self.verts}[sc_[0]]()[sc_[2]]
                    c = to(q)
                    p.setBrush(QColor("#ff8c00"))
                    p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
                except (IndexError, KeyError):
                    self.sel_corner = None
        for e in self.excl:
            p.setPen(QPen(QColor(110, 110, 110), 1.4))
            p.setBrush(QBrush(QColor(120, 120, 120, 110), Qt.BrushStyle.BDiagPattern))
            p.drawPolygon(QPolygonF([to(q) for q in e]))
        for i, z in enumerate(self.zones):                         # the purple area is a working aid: not in the printed plan
            if snapshot:
                break
            p.setPen(QPen(QColor("#7a3fc4"), 3 if i == self.sel_zone else 1.4, Qt.PenStyle.DashLine))
            p.setBrush(QColor(122, 63, 196, 28))
            p.drawPolygon(QPolygonF([to(q) for q in z["poly"]]))
        for b in self.bays:                                        # the pushback (aisle) in road grey, under the bays
            p.setPen(QPen(QColor(128, 130, 138), 1.0))
            p.setBrush(QColor(128, 130, 138))
            p.drawPolygon(QPolygonF([to(q) for q in sp.aisle_poly(b, r)]))
        big = W >= 900
        for i, b in enumerate(self.bays):
            bad = i < len(self._bad) and bool(self._bad[i])
            sel = i == self.sel_bay and not snapshot
            bc = BAY_COL.get(b.get("type", "Open"), BAY_COL["Open"])
            p.setPen(QPen(QColor("#b01028") if bad else QColor(*bc).darker(140), 3 if sel else 1.0))
            p.setBrush(QColor(224, 36, 58, 120) if bad else QColor(bc[0], bc[1], bc[2], 110))
            poly = sp.bay_poly(b, r)
            p.drawPolygon(QPolygonF([to(q) for q in poly]))
            if s > 9:                                              # a small tick on the open side, so you can see which way the bay faces
                a = math.radians(b["a"])
                dp = sp.depth(b, r)
                m = to((b["x"] + math.cos(a) * dp / 2, b["y"] + math.sin(a) * dp / 2))
                p.setPen(QPen(QColor("#1f7a45") if not bad else QColor("#b01028"), 1))
                p.drawLine(m, to((b["x"] + math.cos(a) * (dp / 2 - 0.5), b["y"] + math.sin(a) * (dp / 2 - 0.5))))
        if not snapshot and self.plan.mode == "select":              # the turning ring
            gz = self.gizmo()
            if gz is not None:
                pink = QColor("#d6209a")
                cs, hs = to(gz["c"]), to(gz["h"])
                rpx = gz["R"] * s
                p.setPen(QPen(pink, 1.4, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cs, rpx, rpx)
                p.drawLine(cs, hs)
                p.setPen(QPen(pink, 2))
                p.setBrush(QBrush(QColor("white")))
                p.drawEllipse(hs, 8, 8)
                p.drawEllipse(cs, 4, 4)
                p.setPen(pink)
                p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                p.drawText(QPointF(hs.x() + 12, hs.y() - 10), "%d\u00b0" % round(math.degrees(self.gz_ang)))
        if not snapshot:                                           # the outline of each purple area on top of everything
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i, z in enumerate(self.zones):
                p.setPen(QPen(QColor("#7a3fc4"), 3 if i == self.sel_zone else 1.4, Qt.PenStyle.DashLine))
                p.drawPolygon(QPolygonF([to(q) for q in z["poly"]]))
        if self.bays and s > 5:                                    # bay numbers
            f = QFont("Arial")
            f.setPixelSize(int(max(6, min(12, 1.7 * s))))
            p.setFont(f)
            for i, b in enumerate(self.bays):
                c = to((b["x"], b["y"]))
                p.setPen(QColor("#0b3d1e"))
                p.drawText(QRectF(c.x() - 14, c.y() - 7, 28, 14), int(Qt.AlignmentFlag.AlignCenter), str(i + 1))
        if self.zones and s > 3 and not snapshot:
            f = QFont("Arial")
            f.setPixelSize(15 if big else 11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#5a2a9a"))
            for z in self.zones:
                pts = [to(q) for q in z["poly"]]
                c = QPolygonF(pts).boundingRect().center()
                n = sum(1 for b in self.bays if b.get("zone") == z["name"])
                p.drawText(QRectF(c.x() - 120, c.y() - 10, 240, 20), int(Qt.AlignmentFlag.AlignCenter), "%s - %d bays" % (z["name"], n) if n else z["name"])
        if self.plan.mode == "add_bay" and self.plan.hover is not None and not snapshot:      # the bay that would be placed, red when it breaks a rule
            h = self.plan.hover
            g = sp.single(h[0], h[1], getattr(self.plan, "_add_angle", self._default_angle()))
            bad = bool(sp.problems(g, r, self.site_obj(), self.bays))
            p.setPen(QPen(QColor("#b01028") if bad else QColor("#1f7a45"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(224, 36, 58, 70) if bad else QColor(46, 158, 91, 70))
            p.drawPolygon(QPolygonF([to(q) for q in sp.bay_poly(g, r)]))

    # ------------------------------------------------------------- the schedule of blocks
    def _row(self, b):
        t = self.t
        r = t.rowCount()
        was = t.blockSignals(True)
        t.insertRow(r)
        vals = [b["block"], b["phase"], b["type"], b["storeys"], b["units"], "%.3f" % _num(b.get("unit_m2")), "%.3f" % _num(b.get("patio")), "%.3f" % _num(b.get("common")),
                "%.2f" % _num(b["foot"]), "%.3f" % _num(b["floor"])]
        for c, val in enumerate(vals):
            it = QTableWidgetItem(str(val))
            if c >= 3:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(r, c, it)
        cb = QTableWidgetItem("")
        cb.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        cb.setCheckState(Qt.CheckState.Checked if b.get("cov", True) else Qt.CheckState.Unchecked)
        t.setItem(r, 10, cb)
        t.blockSignals(was)

    def blocks(self):
        out = []
        t = self.t
        tx = lambda r, c: t.item(r, c).text().strip() if t.item(r, c) else ""
        for r in range(t.rowCount()):
            out.append({"block": tx(r, 0), "phase": tx(r, 1) or "Phase 1", "type": tx(r, 2), "storeys": int(_num(tx(r, 3))), "units": int(_num(tx(r, 4))),
                        "unit_m2": _num(tx(r, 5)), "patio": _num(tx(r, 6)), "common": _num(tx(r, 7)), "foot": _num(tx(r, 8)), "floor": _num(tx(r, 9)),
                        "cov": bool(t.item(r, 10) and t.item(r, 10).checkState() == Qt.CheckState.Checked)})
        return out

    def fill_blocks(self, blocks):
        was = self.t.blockSignals(True)
        self.t.setRowCount(0)
        self.t.blockSignals(was)
        for b in blocks:
            self._row(dict(blank_block(), **b))

    def add_block(self):
        n = self.t.rowCount() + 1
        last = self.blocks()[-1] if self.t.rowCount() else None
        self._row(blank_block("H%d" % n, last["phase"] if last else "Phase 1", last["type"] if last else "Standard 3-storey", last["storeys"] if last else 3, last["units"] if last else 0))
        self.t.scrollToBottom()
        self._edited()

    def add_run(self):
        d = _BlocksDialog(self)
        if d.exec():
            have = {b["block"].lower() for b in self.blocks()}
            for b in d.blocks():
                if b["block"].lower() not in have:
                    self._row(b)
            self._edited()

    def remove_blocks(self):
        rows = sorted({i.row() for i in self.t.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, self.TITLE, "Click a block in the list first.")
            return
        for r in rows:
            self.t.removeRow(r)
        self._edited()

    def sync_blocks(self):
        """a block for each building on the plan, with its footprint. Blocks you typed in that are not on the plan are left as they are."""
        rows = {b["block"].lower(): r for r, b in enumerate(self.blocks())}
        was = self.t.blockSignals(True)
        added = 0
        try:
            for b in self.buildings():
                if kind_of(b["name"]) == "refuse":
                    continue                                   # the refuse area is not a block of units
                area = abs(signed_area(bpoly(b)))
                k = b["name"].lower()
                if k in rows:
                    self.t.item(rows[k], 8).setText("%.2f" % area)
                else:
                    self._row(blank_block(b["name"], typ="Gatehouse" if kind_of(b["name"]) == "gate" else "Standard 3-storey", storeys=1 if kind_of(b["name"]) == "gate" else 3,
                                          foot=area, cov=bool(b.get("cov", True))))
                    added += 1
        finally:
            self.t.blockSignals(was)
        self._refresh_sum()
        return added

    def read_from_site(self):
        n = self.sync_blocks()
        self._edited()
        QMessageBox.information(self, self.TITLE, "%d new block%s added from the plan. The footprints of all blocks on the plan are up to date." % (n, "" if n == 1 else "s"))

    def read_floor_areas(self):
        ap = getattr(self.win, "area_page", None)
        if ap is None:
            QMessageBox.information(self, self.TITLE, "The Area schedule is not available.")
            return
        sums = {}
        for r in ap.rows():
            if r["block"]:
                k = r["block"].strip().lower()
                sums[k] = sums.get(k, 0.0) + (r["area"] if r["far"] else 0.0)
        n = 0
        was = self.t.blockSignals(True)
        for r in range(self.t.rowCount()):
            k = (self.t.item(r, 0).text() if self.t.item(r, 0) else "").strip().lower()
            if k in sums and sums[k] > 0:
                self.t.item(r, 9).setText("%.2f" % sums[k])
                n += 1
        self.t.blockSignals(was)
        self._edited()
        QMessageBox.information(self, self.TITLE, ("Floor area filled in for %d block%s." % (n, "" if n == 1 else "s")) if n else
                                "No block name in the Area schedule matches a block here. Use the same names, for example H1.")

    # --- undo and redo: a snapshot of the plan after each change (a drag counts as one change)
    def changed(self, *_a):
        super().changed(*_a)
        if getattr(self, "_undo", None) is not None and not getattr(self, "_restoring", False):
            t = getattr(self, "_undo_t", None)
            if t is None:
                t = self._undo_t = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(self.undo_snap)
            t.start(350)

    def _snap_text(self):
        d = self.state()
        d.pop("under", None)
        return json.dumps(d, default=str, sort_keys=True)

    def undo_snap(self):
        if getattr(self, "_undo", None) is None or getattr(self, "_restoring", False) or getattr(self, "zt", None) is None:
            return
        txt = self._snap_text()
        if txt == self._ulast:
            return
        if self._ulast is not None:
            self._undo.append(self._ulast)
            del self._undo[:-40]
            self._redo = []
        self._ulast = txt

    def _restore_snap(self, txt):
        d = json.loads(txt)
        d["under"] = self.state().get("under") or {}
        self._restoring = True
        try:
            super_state = d
            self.set_state(super_state)
            self._rq = (None, [], [], [])
            self.refresh_parking(user=True)
            self._show_roads()
        finally:
            self._restoring = False
        self._ulast = txt
        self.changed()

    def undo(self):
        self.undo_snap()
        if not self._undo:
            self.set_hint("Nothing to undo.")
            return
        self._redo.append(self._ulast)
        self._restore_snap(self._undo.pop())
        self.set_hint("Undone (Ctrl+Y puts it back).")

    def redo(self):
        self.undo_snap()
        if not self._redo:
            self.set_hint("Nothing to redo.")
            return
        cur = self._ulast
        txt = self._redo.pop()
        self._restore_snap(txt)
        self._undo.append(cur)
        self.set_hint("Done again.")

    def _after_edit(self, user=False):
        super()._after_edit(user)
        if getattr(self, "zt", None) is None or getattr(self, "live", None) is None or getattr(self, "_filling", False):
            return
        sig = tuple(tuple((round(q[0], 2), round(q[1], 2)) for q in bpoly(b)) for b in self.buildings())
        if sig == getattr(self, "_sig", None):
            return
        had = getattr(self, "_sig", None) is not None
        self._sig = sig
        if had and self.live.isChecked() and (any(z.get("poly") for z in self.zones) or self.roads):
            t = getattr(self, "_live_t", None)
            if t is None:
                t = self._live_t = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(self._live_fill)
            t.start(600)                                   # wait until the building stops moving

    def _live_fill(self):
        self._filling = True
        try:
            if (self.zones or self.roads) and self.live.isChecked():
                self.settle_roads()
                self.park_roads()
                self._fill(list(range(len(self.zones))), quiet=True)
                self.set_hint("Parking updated to the buildings.")
        finally:
            self._filling = False
            self._sig = tuple(tuple((round(q[0], 2), round(q[1], 2)) for q in bpoly(b)) for b in self.buildings())

    def _edited(self, *_a):
        if getattr(self, "_pbusy", False):
            return
        it = _a[0] if _a and hasattr(_a[0], "column") else None
        if it is not None and it.column() == 2:                      # a known module type fills in its units and areas
            m = kb.module_preset(it.text().strip())
            if m:
                r_ = it.row()
                was = self.t.blockSignals(True)
                for c_, val in ((3, m["storeys"]), (4, m["units"]), (5, "%.3f" % m["unit_m2"]), (6, "%.3f" % m["patio_m2"]), (7, "%.3f" % m["common_m2"]), (9, "%.3f" % m["gross_m2"])):
                    self.t.item(r_, c_).setText(str(val))
                self.t.blockSignals(was)
        self._refresh_sum()
        self._need_text()
        self.changed()
        self._after_edit()

    def _refresh_sum(self):
        if getattr(self, "sum_lbl", None) is None:
            return
        bl = self.blocks()
        self.sum_lbl.setText("%d blocks | %d units | footprint %.1f m2 | floor area %.1f m2" % (len(bl), sum(b["units"] for b in bl), sum(b["foot"] for b in bl), sum(b["floor"] for b in bl)))

    # ------------------------------------------------------------- numbers and checks
    def site(self):
        d = {}
        for k, w in self.f.items():
            if isinstance(w, QLineEdit):
                d[k] = w.text().strip()
            elif isinstance(w, QComboBox):
                d[k] = w.currentText().strip()
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                d[k] = w.value()
            else:
                d[k] = w.toPlainText()
        return d

    def sdp(self):
        res = SitePage.result(self)
        bl = self.blocks()
        good = sum(1 for i, pr in enumerate(self._bad) if not pr and self.bays[i].get("type", "Open") != "Tandem") if self._bad else 0
        return analyse(self.site(), bl, res["area"], cov_area=res["cov_area"] if res["buildings"] else None, plan_bays=good or None,
                       max_cov=self.max_cov.value(), max_far=self.max_far.value())

    def current_floor_area(self):
        tot = sum(b["floor"] for b in self.blocks()) if getattr(self, "t", None) is not None else 0.0
        return tot if tot > 0 else super().current_floor_area()

    def fill_results(self, an):
        super().fill_results(an)
        if getattr(self, "t", None) is None or getattr(self, "zt", None) is None:
            return
        s = self.sdp()
        rows = [(n, "OK" if ok else "Over", "%s (%s)" % (val, lim), ok) for n, val, lim, ok in s["checks"][2:]]
        if self.bays:
            nb = sum(1 for pr in self._bad if pr)
            rows.append(("Parking rules", "OK" if not nb else "Broken", "Every bay keeps the rules" if not nb else "%d bay%s break the rules (red on the plan)" % (nb, "" if nb == 1 else "s"), not nb))
        t = self.res_t
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
        t.resizeRowsToContents()

    # ------------------------------------------------------------- the sheet
    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        s = self.site()
        an = self.sdp()
        e = tb.esc
        name = s["project"] or rd.get("project") or "Site Development Plan"
        erf = " | ".join(x for x in (("Erf " + self.erf.text().strip()) if self.erf.text().strip() else "", s["township"]) if x)
        body = ('<table width="100%%" cellspacing="0" cellpadding="6" border="0.8" style="border-color:#444444;"><tr>'
                '<td width="62%%"><span style="font-size:10pt; color:#555555;">SITE DEVELOPMENT PLAN</span><br><span style="font-size:17pt; font-weight:bold;">%s</span>'
                '<br><span style="font-size:10pt;">%s</span></td>'
                '<td width="38%%" style="font-size:9pt;">Owner / applicant: %s<br>Zoning: %s<br>Stand area: %.1f m2<br>Drawing: %s &nbsp; Scale %s (at A3)<br>Date: %s</td></tr></table>'
                % (e(name), e(erf), e(s["owner"] or "-"), e(self.zoning.text().strip() or "-"), an["area"], e(s["drawing"]), e(s["scale"]), e(s["date"] or time.strftime("%Y-%m-%d"))))
        body += '<p align="center"><img src="plan" width="700"></p>'
        body += ('<p style="font-size:8pt; color:#555555;">Blue: the buildings. Red dashed line: the building lines. Green: parking bays; each bay %.1f x %.1f m with %.1f m to reverse out, '
                 '%.2f m clear of the buildings.</p>' % (self.r_w.value(), self.r_l.value(), self.r_aisle.value(), self.r_bld.value()))
        bl = self.blocks()
        t = an["total"]
        f1 = lambda v: "%s" % "{:,.3f}".format(v)
        use = lambda ty: (kb.module_preset(ty) or {}).get("use") or ty
        extra = []
        for b in self.buildings():
            if kind_of(b["name"]) != "block":
                extra.append("%s (%.1f m2)" % (b["name"], abs(signed_area(bpoly(b)))))
        if extra:
            body += '<p style="font-size:9pt;">Also on the plan: %s.</p>' % e(", ".join(extra))
        al = ["left", "left", "left", "right", "right", "right", "right", "right", "right"]
        rows = [[b["block"], b["type"], use(b["type"]), b["storeys"], b["units"], f1(b["unit_m2"]), f1(b["patio"]), f1(b["common"]), f1(b["floor"])] for b in bl]
        rows.append((["TOTAL (UNITS / AREAS)", "", "", "", t["units"], f1(t["unit_m2"]), f1(t["patio"]), f1(t["common"]), f1(t["floor"])], "#d6d6d6"))
        body += "<h3>Unit schedule - building and residential unit summary</h3>" + tb.table(
            ["Block", "Module / building type", "Use", "Storeys", "Units", "Unit area m2", "Patio m2", "Common m2", "Total gross m2"], rows, aligns=al)
        groups = {}
        for b in bl:
            g = groups.setdefault(b["type"], {"n": 0, "storeys": b["storeys"], "units": 0, "unit_m2": 0.0, "patio": 0.0, "common": 0.0, "floor": 0.0})
            g["n"] += 1
            for k in ("units", "unit_m2", "patio", "common", "floor"):
                g[k] += b[k]
        rows = [[g["n"], k, use(k), g["storeys"], g["units"], f1(g["unit_m2"]), f1(g["patio"]), f1(g["common"]), f1(g["floor"])] for k, g in groups.items()]
        rows.append((["%d" % len(bl), "DEVELOPMENT TOTAL", "", "", t["units"], f1(t["unit_m2"]), f1(t["patio"]), f1(t["common"]), f1(t["floor"])], "#d6d6d6"))
        body += "<h3>Summary by type</h3>" + tb.table(["Count", "Module / building type", "Use", "Storeys", "Units", "Unit area m2", "Patio m2", "Common m2", "Total gross m2"], rows, aligns=al)
        hard = s["walkways"] + s["roads"]
        sa = an["area"] or 1.0
        foot = SitePage.result(self)["cov_area"]
        body += "<h3>Coverage</h3>" + tb.table(["Zone", "Measured area m2", "% of site area", "Note"], [
            ["Building footprints", "{:,.2f}".format(foot), "%.2f %%" % (100.0 * foot / sa), "Coverage"], ["Site area", "{:,.2f}".format(an["area"]), "100.00 %", "Site"],
            ["Total gross floor area (from schedule)", "{:,.2f}".format(t["floor"]), "%.4f" % an["far"], "Floor area ratio (FAR) - ratio, not %"]], aligns=["left", "right", "right", "left"])
        if hard:
            body += "<h3>Hard surfaces</h3>" + tb.table(["Surface", "Area m2", "% of site area"], [
                ["Walkways to blocks", "{:,.1f}".format(s["walkways"]), "%.2f %%" % (100.0 * s["walkways"] / sa)], ["Internal roads", "{:,.1f}".format(s["roads"]), "%.2f %%" % (100.0 * s["roads"] / sa)],
                (["TOTAL HARD SURFACE", "{:,.1f}".format(hard), "%.2f %%" % (100.0 * hard / sa)], "#d6d6d6")], aligns=["left", "right", "right"])
        bc = self.bay_counts()
        if bc:
            rows = [[k + " parking", ok + bad, "No" if k == "Tandem" else "Yes"] for k, (ok, bad) in sorted(bc.items())]
            rows.append((["TOTAL PARKING BAYS", sum(ok + bad for ok, bad in bc.values()), ""], "#d6d6d6"))
            body += "<h3>Parking - bays on site</h3>" + tb.table(["Parking type", "Bays", "Counts toward the ratio"], rows, aligns=["left", "right", "left"])
        if t["units"]:
            nt = sum(ok + bad for k, (ok, bad) in bc.items() if k == "Tandem")
            body += "<h3>Parking requirement (%.2g bays per unit)</h3>" % s["bays_per_unit"] + tb.table(["Item", "Value"], [
                ["Residential units", t["units"]], ["Parking ratio (bays per unit)", "%.2g" % s["bays_per_unit"]], ["Bays required", an["bays_needed"]],
                ["Bays provided (counted toward the ratio)", an["bays"]], ["Surplus / (shortfall)", an["bays"] - an["bays_needed"]],
                ["Bays per unit provided", "%.2f" % (an["bays"] / float(t["units"]))], ["Extra bays not counted (tandem)", nt]], aligns=["left", "right"])
        if len(an["phases"]) > 1:
            rows = [[k, p["blocks"], p["units"], f1(p["unit_m2"]), f1(p["patio"]), f1(p["common"]), f1(p["floor"])] for k, p in an["phases"].items()]
            rows.append((["TOTAL", t["blocks"], t["units"], f1(t["unit_m2"]), f1(t["patio"]), f1(t["common"]), f1(t["floor"])], "#d6d6d6"))
            body += "<h3>Development phases</h3>" + tb.table(["Phase", "Buildings", "Residential units", "Unit area m2", "Patio m2", "Common m2", "Total gross m2"], rows,
                                                           aligns=["left", "right", "right", "right", "right", "right", "right"])
        sb = SitePage.result(self)
        crow = []
        for b in sb["buildings"]:
            crow.append(([b["name"] + " - building lines", "inside every building line" if not b["enc"] else "over a building line", "", "complies" if not b["enc"] else "does not comply"],
                         "#e4f4ea" if not b["enc"] else "#fbe3e6"))
        crow += [([n, v, l, "complies" if ok else "does not comply"], "#e4f4ea" if ok else "#fbe3e6") for n, v, l, ok in an["checks"]]
        if self.bays:
            nb = sum(1 for pr in self._bad if pr)
            crow.append((["Parking rules", "%d bays, %d break a rule" % (len(self.bays), nb), "0.5 m from buildings, %.1f m aisle" % self.r_aisle.value(),
                          "complies" if not nb else "does not comply"], "#e4f4ea" if not nb else "#fbe3e6"))
        body += "<h3>Development parameters</h3>" + tb.table(["Check", "In the design", "Limit", "Result"], crow)
        if s["notes"].strip():
            body += "<h3>Notes</h3><p>%s</p>" % e(s["notes"]).replace("\n", "<br>")
        mot = self.motiv.toPlainText().strip()
        if any(b["enc"] for b in sb["buildings"]) and mot:
            body += "<h3>Departure motivation</h3><p>%s</p>" % e(mot).replace("\n", "<br>")
        return tb.report_doc_html("Site Development Plan", "%s%s" % (name, (" | " + erf) if erf else ""), body, rd)

    def report_resources(self):
        return {"plan": self.plan.snapshot(1500, 760)}

    def write_report(self, path):
        d, w = tb.write_pdf(path, self.report_html(), self.TITLE, landscape=True, resources=self.report_resources())
        tb.print_doc(d, w)

    # ------------------------------------------------------------- state
    def state(self):
        d = super().state()
        d.update({"sdp": self.site(), "blocks": self.blocks(), "zones": [dict(z) for z in self.zones], "bays": [dict(b) for b in self.bays],
                  "prules": self.rules_now(), "gen": self._gen_names(), "schemes": self.schemes, "excl": self.excl, "roads": self.roads, "mix": {k: [w[0].value(), w[1].value()] for k, w in self.mix.items()}})
        return d

    # --- the turning handle (like the one in the house spacing tool): a ring round the selected building or parking area with a round handle to drag
    def gizmo(self):
        if self.sel_bay >= 0 or getattr(self, "zt", None) is None:
            return None
        bl = self.buildings()
        g = None
        if 0 <= self.plan.sel < len(bl):
            rows = sorted(self._group_rows(self.plan.sel))
            pts = [q for i in rows for q in bpoly(bl[i])]
            g = {"kind": "bld", "rows": rows, "pts": pts, "key": ("b", tuple(rows))}
        elif 0 <= self.sel_zone < len(self.zones) and len(self.zones[self.sel_zone]["poly"]) >= 3 and self.zones[self.sel_zone]["name"] != "Whole stand":
            pts = [tuple(q) for q in self.zones[self.sel_zone]["poly"]]
            g = {"kind": "zone", "idx": self.sel_zone, "pts": pts, "key": ("z", self.sel_zone)}
        if g is None:
            return None
        if g["key"] != getattr(self, "_gz_key", None) and not (self.plan.drag and self.plan.drag[0] == "grot"):
            self._gz_key, self.gz_ang = g["key"], 0.0
        xs, ys = [q[0] for q in g["pts"]], [q[1] for q in g["pts"]]
        c = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        R = max(math.hypot(q[0] - c[0], q[1] - c[1]) for q in g["pts"]) + 1.6
        g["c"], g["R"] = c, R
        g["h"] = (c[0] + R * math.cos(self.gz_ang), c[1] + R * math.sin(self.gz_ang))
        return g

    def gizmo_snapshot(self, g):
        if g["kind"] == "bld":
            bl = self.buildings()
            return {"polys": {i: [tuple(q) for q in bpoly(bl[i])] for i in g["rows"]}}
        z = self.zones[g["idx"]]
        return {"poly": [list(q) for q in z["poly"]], "bays": [(b, b["x"], b["y"], b["a"]) for b in self.bays if b.get("auto") and b.get("zone") == z["name"]]}

    def gizmo_turn(self, g, snap, d, g0):
        self.gz_ang = g0 + d
        if g["kind"] == "bld":
            for i, P in snap["polys"].items():
                self._set_poly(i, self._rot_pts(P, d, g["c"][0], g["c"][1]))
        else:
            z = self.zones[g["idx"]]
            z["poly"] = [list(q) for q in self._rot_pts([tuple(q) for q in snap["poly"]], d, g["c"][0], g["c"][1])]
            for b, bx, by, ba in snap["bays"]:
                (b["x"], b["y"]), = self._rot_pts([(bx, by)], d, g["c"][0], g["c"][1])
                b["a"] = (ba + math.degrees(d)) % 360.0
        self.plan.update()

    def gizmo_done(self, g):
        if g["kind"] == "bld":
            self._after_edit(True)
            self.changed()
            self.refresh_parking(user=True)
        else:
            self.zone_released()
        self.set_hint("Turned %d degrees." % round(math.degrees(self.gz_ang)))

    def _guard_wheel(self):
        if getattr(self, "_nw", None) is None:
            self._nw = _NoWheel(self)
        for w in self.findChildren(QDoubleSpinBox) + self.findChildren(QSpinBox) + self.findChildren(QComboBox):
            if w.property("_nw") is None:
                w.setProperty("_nw", True)
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self._nw)

    def use_standard(self):
        d = STANDARDS.get(self.std_cb.currentText())
        if not d:
            self.set_hint("These are your own rules: change them in the boxes.")
            return
        self._pbusy = True
        try:
            self.r_w.setValue(d["w"]), self.r_l.setValue(d["l"]), self.r_aisle.setValue(d["aisle"]), self.r_parl.setValue(d["par_l"]), self.r_adaw.setValue(d["ada_w"])
            self.f["bays_per_unit"].setValue(d["bays_per_unit"])
            self.f["visitor_per"].setValue(d["visitor_per"])
        finally:
            self._pbusy = False
        self._rules_changed()
        self.set_hint("%s: bay %.1f x %.1f m, aisle %.1f m, parallel bay %.1f m, accessible bay %.1f m wide, %.2f bays per unit and a visitor bay for every %d units." % (
            self.std_cb.currentText(), d["w"], d["l"], d["aisle"], d["par_l"], d["ada_w"], d["bays_per_unit"], d["visitor_per"]))

    def _undo_baseline(self):
        self._undo, self._redo, self._ulast = [], [], None
        self._guard_wheel()
        self.undo_snap()

    def set_state(self, d):
        d = d or {}
        if not getattr(self, "_restoring", False) and getattr(self, "_undo", None) is not None:
            self._undo, self._redo, self._ulast = [], [], None
            QTimer.singleShot(400, self._undo_baseline)
        super().set_state(d)
        if getattr(self, "zt", None) is None:
            return
        self._pbusy = True
        try:
            s = dict(blank_site(), **(d.get("sdp") or {}))
            for k, w in self.f.items():
                val = s.get(k)
                if isinstance(w, QLineEdit):
                    w.setText(str(val or ""))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(val or ""))
                elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                    w.setValue(_num(val))
                else:
                    w.setPlainText(str(val or ""))
            pr = sp.rules(d.get("prules"))
            self.r_w.setValue(pr["w"]), self.r_l.setValue(pr["l"]), self.r_aisle.setValue(pr["aisle"]), self.r_bld.setValue(pr["bld"]), self.r_bound.setValue(pr["bound"]), self.r_parl.setValue(pr["par_l"]), self.r_adaw.setValue(pr["ada_w"])
            self.r_lines.setChecked(bool(pr["outside_lines"]))
            self.fill_blocks([b for b in (d.get("blocks") or []) if isinstance(b, dict)])
            self.zones = [dict(z) for z in (d.get("zones") or []) if isinstance(z, dict) and z.get("poly")]
            self.bays = [dict(b) for b in (d.get("bays") or []) if isinstance(b, dict) and "x" in b]
            self.sel_bay = self.sel_zone = -1
            self.gen_names = [str(n) for n in (d.get("gen") or [])]
            self.excl = [[list(q) for q in e] for e in (d.get("excl") or [])]
            self.roads = [dict(r_) for r_ in (d.get("roads") or []) if isinstance(r_, dict) and len(r_.get("pts") or []) >= 2]
            for k, vv in (d.get("mix") or {}).items():
                if k in self.mix and len(vv) == 2:
                    self.mix[k][0].setValue(vv[0]), self.mix[k][1].setValue(vv[1])
            if "schemes" in d:
                self.schemes = [x for x in (d.get("schemes") or []) if isinstance(x, dict) and x.get("state")]
            self._show_schemes()
        finally:
            self._pbusy = False
        self._show_roads(0)
        self._refresh_sum()
        self.refresh_parking()
        self._after_edit()
