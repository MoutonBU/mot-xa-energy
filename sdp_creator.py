"""SDP Creator: the Site Development Plan for council. It is Building lines and House placing in one tool, made for the SDP:
load the survey (DXF, DWG or PDF) under the plan, set the stand and its building lines, place the buildings (blocks) by their footprints, then draw
the parking areas round them. The tool fills an area with bays (2.5 x 5.0 m, with the 7 m aisle in front to reverse out), keeps every bay 0.5 m
clear of the buildings and checks each bay against the rules. A schedule of the blocks and one PDF sheet finish it.
The stand, buildings, survey, rotation, north arrow and footprints are Building lines' own (site_lines.SitePage); this file adds the parking."""
import math
import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

import sdp_parking as sp
import site_lines as sl
import tool_base as tb
from flow_layout import FlowLayout
from site_lines import PlanView, SitePage, bpoly, signed_area

TYPES = ["Maxi", "Standard 3-storey", "Standard 2-storey", "Gatehouse", "Other"]
COLS = ["Block", "Phase", "Type", "Storeys", "Units", "Footprint m2", "Floor area m2", "Counts"]
SCALES = ["1:200", "1:250", "1:500", "1:1000", "1:1250", "1:2000"]


def _num(x, d=0.0):
    return tb.num(x, d)


def blank_site():
    return {"project": "", "township": "", "owner": "", "drawing": "SDP-01", "scale": "1:500", "date": time.strftime("%Y-%m-%d"),
            "max_density": 0.0, "bays_per_unit": 1.0, "visitor_per": 5, "extra_bays": 0, "notes": ""}


def blank_block(name="", phase="Phase 1", typ="Standard 3-storey", storeys=3, units=0, foot=0.0, floor=0.0, cov=True):
    return {"block": name, "phase": phase, "type": typ, "storeys": storeys, "units": units, "foot": foot, "floor": floor, "cov": cov}


def analyse(site, blocks, stand_area, cov_area=None, plan_bays=None, max_cov=0.0, max_far=0.0):
    """Totals per phase and for the whole development, and each check against the limits that were typed in (0 = no limit).
    cov_area: the area the buildings cover on the plan (when there are buildings); plan_bays: the bays placed on the plan."""
    area = float(stand_area or 0)
    phases = {}
    for b in blocks:
        p = phases.setdefault(b.get("phase") or "Phase 1", {"blocks": 0, "units": 0, "foot": 0.0, "floor": 0.0})
        p["blocks"] += 1
        p["units"] += int(_num(b.get("units")))
        p["foot"] += _num(b.get("foot"))
        p["floor"] += _num(b.get("floor"))
    tot = {k: sum(p[k] for p in phases.values()) for k in ("blocks", "units", "foot", "floor")}
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

    def blocks(self):
        lo, hi = self.first.value(), max(self.first.value(), self.last.value())
        return [blank_block(nm, self.phase.text().strip() or "Phase 1", self.typ.currentText(), 2 if "2-storey" in self.typ.currentText() else 3, self.units.value())
                for nm in block_names(self.prefix.text().strip() or "H", lo, hi)]


# ---------------------------------------------------------------- the plan
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
        if self.drag and self.drag[0] == "bay":
            self.drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.page.refresh_parking(user=True)
            return
        super().mouseReleaseEvent(e)

    def begin(self, mode, role=None):
        super().begin(mode, role)
        if mode == "add_bay":
            self.setCursor(Qt.CursorShape.CrossCursor)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.mode == "select" and self.page.sel_bay >= 0:
            self.page.delete_bay()
        elif k == Qt.Key.Key_R and self.mode in ("select", "add_bay"):
            self.page.rotate_bay()
        else:
            super().keyPressEvent(e)


class SdpPage(SitePage):
    KEY = "sdp"
    TITLE = "SDP Creator"
    PLAN_CLS = ParkView
    STEP_NAMES = ["The stand", "The buildings", "Parking", "Schedule", "Check and sheet"]
    STEP_HINTS = ["Load the survey (DXF, DWG, PDF), pick or trace the stand and set the building line on each boundary.",
                  "Bring in each block's footprint (from the IFC model, a drawing, or trace it) and place it on the stand.",
                  "Draw the parking areas round the buildings. The program fills them with bays and keeps the rules: 0.5 m from a building, 7 m to reverse out.",
                  "The schedule of blocks: phase, units, floor area. Fill in the title block details for the sheet.",
                  "What complies and what does not, then save the Site Development Plan as a PDF for council."]

    def __init__(self, win):
        self.zones, self.bays, self._bad = [], [], []
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

    def _parking_page(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Parking rules", "A bay is 2.5 by 5.0 m and needs 7 m in front of it to reverse out. A bay that breaks a rule shows red on the plan.")
        fl = FlowLayout(None, 10, 6)
        self.r_w = sl.spin(1.5, 5, sp.RULES["w"], 2, " m")
        self.r_l = sl.spin(3, 10, sp.RULES["l"], 2, " m")
        self.r_aisle = sl.spin(3, 12, sp.RULES["aisle"], 2, " m")
        self.r_bld = sl.spin(0, 5, sp.RULES["bld"], 2, " m")
        self.r_bound = sl.spin(0, 5, sp.RULES["bound"], 2, " m")
        for lab, w, tip in (("Bay width", self.r_w, ""), ("Bay length", self.r_l, ""), ("Room to reverse out", self.r_aisle, "The aisle in front of a bay."),
                            ("Clear of a building", self.r_bld, "The nearest a bay may be to a building."), ("Clear of the boundary", self.r_bound, "0 means a bay may touch the boundary.")):
            w.setToolTip(tip)
            w.valueChanged.connect(self._rules_changed)
            fl.addWidget(self._pair(lab, w))
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
        self.zt = QTableWidget(0, 3)
        self.zt.setHorizontalHeaderLabels(["Area", "Rows run at (degrees, or auto)", "Bays"])
        self.zt.verticalHeader().setVisible(False)
        self.zt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.zt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.zt.setMinimumHeight(130)
        self.zt.itemChanged.connect(self._zone_edited)
        self.zt.itemSelectionChanged.connect(lambda: setattr(self, "sel_zone", (self.zt.currentRow() if self.zt.currentRow() >= 0 else -1)) or self.plan.update())
        bv.addWidget(self.zt)
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
        for text, fn, tip in (("Add a refuse area", self.add_refuse, "Puts a refuse area of this size on the plan."),
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
        for i, w_ in enumerate((90, 110, 160, 70, 70, 110, 120, 70)):
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
                "outside_lines": self.r_lines.isChecked()}

    def site_obj(self):
        v = self.verts()
        env = None
        if self.r_lines.isChecked() and len(v) >= 3:
            env = sl.envelope(v, [e["sb"] for e in self.edges()])
        return sp.Site(v, [bpoly(b) for b in self.buildings()], env)

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
        self._pbusy = True
        try:
            self.zt.setRowCount(0)
            for i, z in enumerate(self.zones):
                self.zt.insertRow(i)
                n = sum(1 for b in self.bays if b.get("zone") == z["name"])
                for c, val in enumerate((z["name"], "auto" if z.get("angle") is None else "%g" % z["angle"], str(n))):
                    it = QTableWidgetItem(val)
                    if c == 2:
                        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.zt.setItem(i, c, it)
            if 0 <= self.sel_zone < self.zt.rowCount():
                self.zt.selectRow(self.sel_zone)
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
        self.plan.update()
        if user:
            self.changed()
            self._after_edit()

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
        txt = ("<b>%d units in %d blocks need %d bays</b> (%.2g per unit, and a visitor's bay for every %s units).<br>On the plan: <b>%d bays</b> - " %
               (t["units"], t["blocks"], a["bays_needed"], site["bays_per_unit"], site["visitor_per"] or "-", a["bays"]))
        txt += ("<span style='color:#2e9e5b'><b>enough</b></span>" if short <= 0 else "<span style='color:#e0243a'><b>%d short</b></span>" % short)
        if len(a["phases"]) > 1:
            txt += "<br>" + " | ".join("%s: %d units, %d bays" % (k, p["units"], p["bays_needed"]) for k, p in a["phases"].items())
        self.need_lbl.setText(txt)

    def park_selected(self):
        if 0 <= self.sel_bay < len(self.bays):
            pr = self._bad[self.sel_bay] if self.sel_bay < len(self._bad) else []
            self.set_hint(("This bay: " + "; ".join(pr) + ".") if pr else "This bay keeps the rules. Drag it, press R to turn it, Delete to remove it.")

    # ------------------------------------------------------------- parking: areas and bays
    def start_zone(self):
        if len(self.verts()) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self.plan.begin("trace_parking")
        self.set_hint("Click each corner of the parking area, round the buildings. Hold Shift to keep a line straight. Double-click or press Enter to finish.")

    def trace_done(self, mode, role, pts):
        if mode != "trace_parking":
            return super().trace_done(mode, role, pts)
        self._new_zone(sl.si.clean(pts))
        self.set_hint("Area drawn. Press 'Fill the selected area'.")

    def _new_zone(self, pts, name=None):
        n = len(self.zones) + 1
        nm = name or "Parking area %d" % n
        while any(z["name"] == nm for z in self.zones):
            n += 1
            nm = "Parking area %d" % n
        self.zones.append({"name": nm, "poly": [list(p) for p in pts], "angle": None})
        self.sel_zone = len(self.zones) - 1
        self.refresh_parking(user=True)

    def zone_whole_stand(self):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        self._new_zone(v, "Whole stand")

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

    def _fill(self, idxs):
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
                got = sp.fill([tuple(p) for p in z["poly"]], site, r, z.get("angle"), keep, z["name"])
                self.bays += got
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_parking(user=True)

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
        self.bays.append(b)
        self.sel_bay = len(self.bays) - 1
        self.refresh_parking(user=True)
        self.park_selected()

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

    def add_gatehouse(self):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, self.TITLE, "Set the stand first (first step).")
            return
        x0, y0 = min(p[0] for p in v), min(p[1] for p in v)
        self.add_building({"name": "Gatehouse", "x": x0 + 6.0, "y": y0 + 2.0, "w": 3.0, "d": 3.0, "cov": True})
        self.bt.selectRow(self.bt.rowCount() - 1)
        self.set_hint("Gatehouse added. Drag it to the entrance, or press Rotate building to turn it.")

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
        for b in getattr(self, "bays", []):
            b["x"] += dx
            b["y"] += dy

    def rotate_world(self, a, cx, cy):
        super().rotate_world(a, cx, cy)
        for z in getattr(self, "zones", []):
            z["poly"] = [list(q) for q in self._rot_pts([tuple(p) for p in z["poly"]], a, cx, cy)]
            if z.get("angle") is not None:
                z["angle"] = (z["angle"] + math.degrees(a)) % 180
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
        for i, z in enumerate(self.zones):
            p.setPen(QPen(QColor("#7a3fc4"), 3 if (i == self.sel_zone and not snapshot) else 1.4, Qt.PenStyle.DashLine))
            p.setBrush(QColor(122, 63, 196, 28))
            p.drawPolygon(QPolygonF([to(q) for q in z["poly"]]))
        for b in self.bays:                                        # the aisles first, under the bays
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(110, 110, 110, 34))
            p.drawPolygon(QPolygonF([to(q) for q in sp.aisle_poly(b, r)]))
        big = W >= 900
        for i, b in enumerate(self.bays):
            bad = i < len(self._bad) and bool(self._bad[i])
            sel = i == self.sel_bay and not snapshot
            p.setPen(QPen(QColor("#b01028") if bad else QColor("#1f7a45"), 3 if sel else 1.0))
            p.setBrush(QColor(224, 36, 58, 120) if bad else QColor(46, 158, 91, 90))
            poly = sp.bay_poly(b, r)
            p.drawPolygon(QPolygonF([to(q) for q in poly]))
            if s > 9:                                              # a small tick on the open side, so you can see which way the bay faces
                a = math.radians(b["a"])
                m = to((b["x"] + math.cos(a) * r["l"] / 2, b["y"] + math.sin(a) * r["l"] / 2))
                p.setPen(QPen(QColor("#1f7a45") if not bad else QColor("#b01028"), 1))
                p.drawLine(m, to((b["x"] + math.cos(a) * (r["l"] / 2 - 0.5), b["y"] + math.sin(a) * (r["l"] / 2 - 0.5))))
        if self.zones and s > 3:
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
        vals = [b["block"], b["phase"], b["type"], b["storeys"], b["units"], "%.2f" % _num(b["foot"]), "%.2f" % _num(b["floor"])]
        for c, val in enumerate(vals):
            it = QTableWidgetItem(str(val))
            if c >= 3:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(r, c, it)
        cb = QTableWidgetItem("")
        cb.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        cb.setCheckState(Qt.CheckState.Checked if b.get("cov", True) else Qt.CheckState.Unchecked)
        t.setItem(r, 7, cb)
        t.blockSignals(was)

    def blocks(self):
        out = []
        t = self.t
        tx = lambda r, c: t.item(r, c).text().strip() if t.item(r, c) else ""
        for r in range(t.rowCount()):
            out.append({"block": tx(r, 0), "phase": tx(r, 1) or "Phase 1", "type": tx(r, 2), "storeys": int(_num(tx(r, 3))), "units": int(_num(tx(r, 4))),
                        "foot": _num(tx(r, 5)), "floor": _num(tx(r, 6)),
                        "cov": bool(t.item(r, 7) and t.item(r, 7).checkState() == Qt.CheckState.Checked)})
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
                    self.t.item(rows[k], 5).setText("%.2f" % area)
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
                self.t.item(r, 6).setText("%.2f" % sums[k])
                n += 1
        self.t.blockSignals(was)
        self._edited()
        QMessageBox.information(self, self.TITLE, ("Floor area filled in for %d block%s." % (n, "" if n == 1 else "s")) if n else
                                "No block name in the Area schedule matches a block here. Use the same names, for example H1.")

    def _edited(self, *_a):
        if getattr(self, "_pbusy", False):
            return
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
        good = sum(1 for pr in self._bad if not pr) if self._bad else 0
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
        head = ["Block", "Phase", "Type", "Storeys", "Units", "Footprint m2", "Floor area m2"]
        rows = []
        bl = self.blocks()
        for ph, p in an["phases"].items():
            for b in bl:
                if (b["phase"] or "Phase 1") == ph:
                    rows.append([b["block"], ph, b["type"], b["storeys"], b["units"], "%.1f" % b["foot"], "%.1f" % b["floor"]])
            rows.append(([ph + " total", "", "%d blocks, %d bays needed" % (p["blocks"], p["bays_needed"]), "", p["units"], "%.1f" % p["foot"], "%.1f" % p["floor"]], "#e9e9e9"))
        t = an["total"]
        rows.append((["All phases", "", "%d blocks" % t["blocks"], "", t["units"], "%.1f" % t["foot"], "%.1f" % t["floor"]], "#d6d6d6"))
        extra = []
        for b in self.buildings():
            k = kind_of(b["name"])
            if k != "block":
                extra.append("%s (%.1f m2)" % (b["name"], abs(signed_area(bpoly(b)))))
        if extra:
            body += '<p style="font-size:9pt;">Also on the plan: %s.</p>' % e(", ".join(extra))
        body += "<h3>Schedule of blocks</h3>" + tb.table(head, rows, aligns=["left", "left", "left", "right", "right", "right", "right"])
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
                  "prules": self.rules_now()})
        return d

    def set_state(self, d):
        d = d or {}
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
            self.r_w.setValue(pr["w"]), self.r_l.setValue(pr["l"]), self.r_aisle.setValue(pr["aisle"]), self.r_bld.setValue(pr["bld"]), self.r_bound.setValue(pr["bound"])
            self.r_lines.setChecked(bool(pr["outside_lines"]))
            self.fill_blocks([b for b in (d.get("blocks") or []) if isinstance(b, dict)])
            self.zones = [dict(z) for z in (d.get("zones") or []) if isinstance(z, dict) and z.get("poly")]
            self.bays = [dict(b) for b in (d.get("bays") or []) if isinstance(b, dict) and "x" in b]
            self.sel_bay = self.sel_zone = -1
        finally:
            self._pbusy = False
        self._refresh_sum()
        self.refresh_parking()
        self._after_edit()
