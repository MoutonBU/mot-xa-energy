"""Building materials estimate: quantities taken off the IFC (walls, slabs, roofs, beams, windows, doors) turned into a
bill of materials (bricks, cement, sand, plaster, concrete, steel, floor tiles, roofing, ceilings, paint, windows, doors)
with editable rates, per block and for the whole building.

The allowances (bricks per m2, cement per m3 of mortar ...) are typical figures for estimating and the rates are starting
figures: both are in tables on the tab and can be changed. This is an estimate for budgeting, not a bill of quantities."""
import re

# ---------------- allowances (editable in the tab) ----------------
# key: (description, unit, default)
ALLOW = {
    "brick_per_m2_110": ("Bricks per m2, 110 mm wall", "no.", 52.0),
    "mortar_m3_per_m2_110": ("Mortar per m2, 110 mm wall", "m3", 0.025),
    "waste_brick": ("Brick waste", "%", 5.0),
    "plaster_thick": ("Plaster thickness", "mm", 15.0),
    "waste_plaster": ("Plaster waste", "%", 15.0),
    "cement_bags_per_m3": ("Cement per m3 of mortar (1:4)", "bags", 7.0),
    "sand_m3_per_m3": ("Sand per m3 of mortar", "m3", 1.0),
    "ties_per_m2": ("Wall ties per m2 of cavity wall", "no.", 4.0),
    "steel_slab": ("Reinforcing steel in slabs", "kg/m3", 70.0),
    "steel_beam": ("Reinforcing steel in beams, columns, stairs", "kg/m3", 150.0),
    "steel_footing": ("Reinforcing steel in footings", "kg/m3", 40.0),
    "waste_concrete": ("Concrete waste", "%", 5.0),
    "tile_waste": ("Floor tile waste", "%", 8.0),
    "adhesive_kg_per_m2": ("Tile adhesive and grout", "kg/m2", 5.5),
    "paint_l_per_m2": ("Paint, two coats", "L/m2", 0.2),
    "plaster_brick_walls": ("Plaster the plain 'Brick' walls too (1 = yes)", "0/1", 0.0),
    "labour_pct": ("Labour and plant allowance", "% of materials", 35.0),
    "prelim_pct": ("Preliminaries, overheads and profit", "%", 10.0),
    "contingency_pct": ("Contingency", "%", 5.0),
}

# ---------------- rates ----------------
# key: (description, unit, rand per unit, where the figure comes from)
LIST_NOTE = "retail price list, undated"
EST_NOTE = "my estimate, check a quote"
RATES = {
    "brick": ("Cement / clay stock brick", "each", 2.30, LIST_NOTE),
    "cement": ("Cement, 50 kg bag", "bag", 112.00, LIST_NOTE),
    "sand_build": ("Building sand", "m3", 379.00, LIST_NOTE),
    "sand_plaster": ("Plaster sand", "m3", 569.00, LIST_NOTE),
    "ties": ("Wall tie", "each", 1.50, EST_NOTE),
    "insulation": ("Cavity wall insulation", "m2", 85.00, EST_NOTE),
    "concrete": ("Ready-mix concrete 25 MPa, delivered", "m3", 2400.00, EST_NOTE),
    "steel": ("Reinforcing steel, supplied and cut", "kg", 19.00, EST_NOTE),
    "mesh": ("Reinforcing mesh (ref 193)", "m2", 38.00, EST_NOTE),
    "dpm": ("Damp-proof membrane", "m2", 12.00, EST_NOTE),
    "tile": ("Floor tile", "m2", 190.00, EST_NOTE),
    "adhesive": ("Tile adhesive / grout", "kg", 9.00, EST_NOTE),
    "roof_cover": ("Roof covering (tiles or sheeting), laid", "m2", 260.00, EST_NOTE),
    "roof_timber": ("Roof timber structure with fixings", "m2", 480.00, EST_NOTE),
    "ceiling": ("Ceiling board with brandering and cornice", "m2", 135.00, EST_NOTE),
    "paint": ("Paint (PVA / acrylic)", "L", 95.00, EST_NOTE),
    "window": ("Aluminium window, glazed, fitted", "m2", 3600.00, EST_NOTE),
    "door": ("Door with frame and ironmongery, fitted", "each", 1900.00, EST_NOTE),
}

NON_CEILING = re.compile(r"stoep|patio|carport|balcon|veranda|terrace|garage|roof|passage space", re.I)


# ---------------- reading the model ----------------
def _wall_kind(name):
    n = name.lower()
    t = re.search(r"(\d{2,3})\s*mm", n)
    th = float(t.group(1)) / 1000.0 if t else 0.0
    if "footing" in n or "foundation" in n:
        return "footing", th
    if "cavity" in n or th >= 0.26:
        return "cavity", th
    if th >= 0.20:
        return "brick220", th
    return "brick110", th


def _axis_length(e, sc):
    """Length of a wall drawn only as a centre line (Archicad exports its footings that way)."""
    import math
    try:
        for rep in e.Representation.Representations:
            for it in rep.Items:
                if it.is_a("IfcPolyline"):
                    pts = [p.Coordinates for p in it.Points]
                    return sum(math.dist(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1)) * sc
                if it.is_a("IfcTrimmedCurve") and it.BasisCurve.is_a("IfcLine"):
                    return abs(float(it.Trim2[0].wrappedValue) - float(it.Trim1[0].wrappedValue)) * sc
    except Exception:
        pass
    return 0.0


def _footing_volume(e, name, sc):
    """Footing volume: centre-line length times the section in the type name ('Footing 720 x 800' = 720 wide, 800 deep, mm)."""
    m = re.search(r"(\d{3,4})\s*x\s*(\d{3,4})", name)
    if not m:
        return 0.0
    return _axis_length(e, sc) * float(m.group(1)) / 1000.0 * float(m.group(2)) / 1000.0


def read_ifc_quantities(path):
    """Quantities of one IFC file (one block): wall face areas by type, slab, roof, beam and footing volumes, windows and doors.
    Takes a few seconds for a house. Raises if the file cannot be read."""
    import numpy as np
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU
    f = ifcopenshell.open(path)
    st = ifcopenshell.geom.settings()
    st.set(st.USE_WORLD_COORDS, True)
    sc = UU.calculate_unit_scale(f)
    q = dict(brick110=0.0, brick220=0.0, cavity=0.0, plaster_area=0.0, plain_brick_area=0.0, footing_vol=0.0, footing_len=0.0,
             slab_vol=0.0, slab_area=0.0, tile_area=0.0, dpm_area=0.0, roof_slab_vol=0.0, roof_area=0.0, beam_vol=0.0, win_area=0.0,
             win_n=0, door_n=0, gate_n=0, names={}, levels={})

    def shape_stats(e):
        s = ifcopenshell.geom.create_shape(st, e)
        v = np.array(s.geometry.verts, dtype=float).reshape(-1, 3)
        fc = np.array(s.geometry.faces, dtype=int).reshape(-1, 3)
        tri = v[fc]
        cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ar = np.linalg.norm(cr, axis=1)
        ok = ar > 1e-12
        nz = np.zeros(len(ar))
        nz[ok] = cr[ok, 2] / ar[ok]
        vol = abs(float(np.einsum("ij,ij->i", tri[:, 0], cr).sum()) / 6.0)
        return vol, ar / 2.0, nz, v

    def type_name(e):
        t = None
        try:
            t = UE.get_type(e)
        except Exception:
            pass
        return ((t.Name if t is not None else "") or e.Name or "")

    def level(e):
        try:
            c = UE.get_container(e)
            return (c.Name if c is not None else "") or ""
        except Exception:
            return ""

    def layer_thickness(e):
        try:
            m = UE.get_material(e)
            if m is not None and m.is_a("IfcMaterialLayerSetUsage"):
                m = m.ForLayerSet
            if m is not None and m.is_a("IfcMaterialLayerSet"):
                return sum(float(l.LayerThickness) for l in m.MaterialLayers) * sc
        except Exception:
            pass
        return 0.0

    for e in f.by_type("IfcWall"):
        try:
            name = type_name(e)
            kind, th = _wall_kind(name)
            if kind == "footing":
                q["footing_vol"] += _footing_volume(e, name, sc)
                continue
            vol, ar, nz, v = shape_stats(e)
            th = th or layer_thickness(e) or 0.11
            face = vol / th
            q[kind] += face
            q["names"][name] = q["names"].get(name, 0.0) + face
            lv = level(e)
            q["levels"][lv] = q["levels"].get(lv, 0.0) + face
            if "plaster" in name.lower():
                q["plaster_area"] += 2.0 * face
            elif kind in ("brick110", "brick220"):
                q["plain_brick_area"] += 2.0 * face
        except Exception:
            continue
    for e in f.by_type("IfcSlab"):
        try:
            name = type_name(e)
            vol, ar, nz, v = shape_stats(e)
            top = float(ar[nz > 0.9].sum())
            lv = level(e)
            is_roof = "roof" in name.lower() or "roof" in lv.lower() or str(getattr(e, "PredefinedType", "")) == "ROOF"
            if is_roof:
                q["roof_slab_vol"] += vol
                q["roof_area"] += top
                continue
            q["slab_vol"] += vol
            q["slab_area"] += top
            if "tile" in name.lower():
                q["tile_area"] += top
            if "waterproof" in name.lower() or "membrane" in name.lower() or "dpm" in name.lower():
                q["dpm_area"] += top
        except Exception:
            continue
    for e in f.by_type("IfcRoof"):
        try:
            vol, ar, nz, v = shape_stats(e)
            q["roof_area"] += float(ar[nz > 0.25].sum())
        except Exception:
            continue
    for cls in ("IfcBeam", "IfcColumn", "IfcMember", "IfcStair", "IfcStairFlight"):
        try:
            for e in f.by_type(cls):
                if getattr(e, "Name", "") and "CHS" in (type_name(e) or ""):
                    continue            # a steel tube column is not concrete
                try:
                    q["beam_vol"] += shape_stats(e)[0]
                except Exception:
                    pass
        except Exception:
            pass
    for e in f.by_type("IfcWindow"):
        try:
            w, h = float(e.OverallWidth or 0) * sc, float(e.OverallHeight or 0) * sc
            q["win_area"] += w * h
            q["win_n"] += 1
        except Exception:
            pass
    for e in f.by_type("IfcDoor"):
        if re.match(r"^\s*G\d*\b", str(e.Name or "")):
            q["gate_n"] += 1
        else:
            q["door_n"] += 1
    return q


# ---------------- bill of materials ----------------
def bom(q, rates, allow, rooms=None):
    """Rows for one block: [(group, item, unit, quantity, rate, cost)]. rates / allow: {key: value} overriding the defaults."""
    R = lambda k: float(rates.get(k, RATES[k][2]))
    A = lambda k: float(allow.get(k, ALLOW[k][2]))
    rows = []

    def add(group, item, unit, qty, rkey):
        if qty > 1e-9:
            rows.append((group, item, unit, qty, R(rkey), qty * R(rkey)))
    wb = 1 + A("waste_brick") / 100.0
    per = A("brick_per_m2_110")
    mort = A("mortar_m3_per_m2_110")
    bricks = (q["brick110"] * per + q["brick220"] * 2 * per + q["cavity"] * 2 * per) * wb
    mortar_walls = (q["brick110"] * mort + q["brick220"] * 2 * mort + q["cavity"] * 2 * mort) * wb
    add("Walls", "Bricks", "no.", bricks, "brick")
    add("Walls", "Wall ties (cavity walls)", "no.", q["cavity"] * A("ties_per_m2"), "ties")
    add("Walls", "Cavity insulation", "m2", q["cavity"], "insulation")
    pl_area = q["plaster_area"] + (q["plain_brick_area"] if A("plaster_brick_walls") else 0.0)
    ceil = sum(a for n, a, fl in (rooms or []) if not NON_CEILING.search(n or "")) if rooms else q["slab_area"]
    mortar_plaster = pl_area * A("plaster_thick") / 1000.0 * (1 + A("waste_plaster") / 100.0)
    add("Walls", "Cement for brickwork and plaster", "bag", (mortar_walls + mortar_plaster) * A("cement_bags_per_m3"), "cement")
    add("Walls", "Building sand (brickwork)", "m3", mortar_walls * A("sand_m3_per_m3"), "sand_build")
    add("Walls", "Plaster sand", "m3", mortar_plaster * A("sand_m3_per_m3"), "sand_plaster")
    wc = 1 + A("waste_concrete") / 100.0
    conc_f = q["footing_vol"] * wc
    conc_s = (q["slab_vol"] + q["roof_slab_vol"]) * wc
    conc_b = q["beam_vol"] * wc
    add("Concrete", "Footings (concrete)", "m3", conc_f, "concrete")
    add("Concrete", "Floor and roof slabs (concrete)", "m3", conc_s, "concrete")
    add("Concrete", "Beams, columns and stairs (concrete)", "m3", conc_b, "concrete")
    steel = q["footing_vol"] * A("steel_footing") + (q["slab_vol"] + q["roof_slab_vol"]) * A("steel_slab") + q["beam_vol"] * A("steel_beam")
    add("Concrete", "Reinforcing steel", "kg", steel, "steel")
    add("Concrete", "Damp-proof membrane under slabs", "m2", q["dpm_area"] * 1.1, "dpm")
    add("Floors", "Floor tiles", "m2", q["tile_area"] * (1 + A("tile_waste") / 100.0), "tile")
    add("Floors", "Tile adhesive and grout", "kg", q["tile_area"] * A("adhesive_kg_per_m2"), "adhesive")
    add("Roof and ceiling", "Roof covering", "m2", q["roof_area"], "roof_cover")
    add("Roof and ceiling", "Roof timber structure", "m2", q["roof_area"], "roof_timber")
    add("Roof and ceiling", "Ceilings", "m2", ceil, "ceiling")
    add("Finishes", "Paint (walls and ceilings)", "L", (pl_area + ceil) * A("paint_l_per_m2"), "paint")
    add("Openings", "Windows", "m2", q["win_area"], "window")
    add("Openings", "Doors", "each", float(q["door_n"]), "door")
    return rows


def totals(rows, allow, repeat=1):
    """(materials, labour, prelims, contingency, total) for rows of one block times the number of identical blocks."""
    A = lambda k: float(allow.get(k, ALLOW[k][2]))
    mat = sum(r[5] for r in rows) * repeat
    lab = mat * A("labour_pct") / 100.0
    pre = (mat + lab) * A("prelim_pct") / 100.0
    con = (mat + lab + pre) * A("contingency_pct") / 100.0
    return mat, lab, pre, con, mat + lab + pre + con


# ---------------- the tab ----------------
import html as _html
import json
import os
import sys
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)


def rand(x):
    return "R {:,.0f}".format(float(x)).replace(",", " ")


def num(x, d=1):
    return "{:,.{d}f}".format(float(x), d=d).replace(",", " ")


class MaterialsPage(QWidget):
    is_costing = True
    report_title = "Building Materials Estimate"
    read_done = Signal(int, object, str)

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.blocks = []        # {name, path, repeat, q}
        self.rates = {}         # key -> {"rate": float, "source": str} overrides
        self.allow = {}         # key -> value overrides
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        gb = QGroupBox("Blocks and buildings")
        bv = QVBoxLayout(gb)
        row = QHBoxLayout()
        for text, fn in (("Use this project's IFC", self.add_current), ("Add block (IFC)...", self.add_block), ("Remove", self.remove_block),
                         ("Read quantities from the IFC", self.read_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        self.btab = QTableWidget(0, 5)
        self.btab.setHorizontalHeaderLabels(["Block", "IFC file", "Identical blocks", "Status", "Cost of one block"])
        self.btab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.btab.verticalHeader().setVisible(False)
        self.btab.setMaximumHeight(150)
        h = self.btab.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 150), (2, 120), (3, 190), (4, 140)):
            self.btab.setColumnWidth(i, w)
        self.btab.itemChanged.connect(self._b_edit)
        bv.addWidget(self.btab)
        v.addWidget(gb)
        self.tabs = QTabWidget()
        self.bomt = QTableWidget(0, 6)
        self.bomt.setHorizontalHeaderLabels(["Group", "Item", "Unit", "Quantity", "Rate", "Cost"])
        self.ratet = QTableWidget(0, 4)
        self.ratet.setHorizontalHeaderLabels(["Material", "Unit", "Rate (R)", "Where the figure comes from"])
        self.allowt = QTableWidget(0, 3)
        self.allowt.setHorizontalHeaderLabels(["Allowance", "Unit", "Value"])
        self.qt_ = QTableWidget(0, 3)
        self.qt_.setHorizontalHeaderLabels(["Quantity read from the IFC", "Unit", "Value"])
        for t in (self.bomt, self.ratet, self.allowt, self.qt_):
            t.verticalHeader().setVisible(False)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for t in (self.bomt, self.qt_):
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ratet.itemChanged.connect(self._r_edit)
        self.allowt.itemChanged.connect(self._a_edit)
        self.tabs.addTab(self.bomt, "Bill of materials")
        self.tabs.addTab(self.ratet, "Rates")
        self.tabs.addTab(self.allowt, "Allowances")
        self.tabs.addTab(self.qt_, "Quantities")
        v.addWidget(self.tabs, 1)
        bar = QHBoxLayout()
        for text, fn in (("Update prices with AI...", self.ai_prices), ("Preview PDF", self.preview_pdf), ("Export PDF", self.export_pdf),
                         ("Export CSV", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.total = QLabel("")
        self.total.setStyleSheet("font-weight:700; font-size:14px;")
        bar.addWidget(self.total)
        v.addLayout(bar)
        self.note = QLabel("Rates are starting figures (the Where-from column says which). Prices are taken as including VAT. "
                           "This is a budget estimate, not a bill of quantities.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray; font-size: 11px;")
        v.addWidget(self.note)
        self.read_done.connect(self._read_finished)
        self.refresh()

    # ----- state -----
    def state(self):
        return {"blocks": self.blocks, "rates": self.rates, "allow": self.allow}

    def set_state(self, d):
        d = d or {}
        self.blocks = [dict(b) for b in d.get("blocks", []) if isinstance(b, dict)]
        self.rates = dict(d.get("rates", {}) or {})
        self.allow = dict(d.get("allow", {}) or {})
        self.refresh()

    def rate_vals(self):
        return {k: float(v["rate"]) for k, v in self.rates.items() if k in RATES}

    def rooms(self):
        try:
            return [(r.name, float(r.area_m2), r.floor) for r in self.host.win.read_rooms()]
        except Exception:
            return []

    # ----- blocks -----
    def _project_ifc(self):
        w = self.host.win
        return getattr(w, "ifc_path", "") or (getattr(w, "ifc_data", None) or {}).get("path", "")

    def add_current(self):
        p = self._project_ifc()
        if not p:
            QMessageBox.information(self, "Materials", "Import an IFC in Light && ventilation first, or use Add block.")
            return
        if any(b["path"] == p for b in self.blocks):
            return
        self.blocks.append({"name": os.path.splitext(os.path.basename(p))[0], "path": p, "repeat": 1, "q": None})
        self.refresh()
        self.read_all()

    def add_block(self):
        path, _ = QFileDialog.getOpenFileName(self, "IFC of a block", "", "IFC (*.ifc)")
        if path:
            self.blocks.append({"name": os.path.splitext(os.path.basename(path))[0], "path": path, "repeat": 1, "q": None})
            self.refresh()
            self.read_all()

    def remove_block(self):
        r = self.btab.currentRow()
        if 0 <= r < len(self.blocks):
            self.blocks.pop(r)
            self.refresh()

    def _b_edit(self, it):
        if self._busy or not (0 <= it.row() < len(self.blocks)):
            return
        if it.column() == 0:
            self.blocks[it.row()]["name"] = it.text().strip()
        elif it.column() == 2:
            try:
                self.blocks[it.row()]["repeat"] = max(1, int(float(it.text())))
            except ValueError:
                pass
            self.refresh()

    def read_all(self):
        if not self.blocks:
            self.add_current()
            return
        for i, b in enumerate(self.blocks):
            if not os.path.exists(b["path"]):
                b["status"] = "file not found"
                continue
            b["status"] = "reading..."

            def work(i=i, p=b["path"]):
                try:
                    self.read_done.emit(i, read_ifc_quantities(p), "")
                except Exception as e:
                    self.read_done.emit(i, None, str(e))
            threading.Thread(target=work, daemon=True).start()
        self.refresh()

    def _read_finished(self, i, q, err):
        if 0 <= i < len(self.blocks):
            self.blocks[i]["q"] = q
            self.blocks[i]["status"] = ("read " + __import__("datetime").date.today().isoformat()) if q else ("could not read: " + err[:60])
        self.refresh()

    # ----- sums -----
    def block_rows(self, b):
        return bom(b["q"], self.rate_vals(), self.allow, self.rooms() if b["path"] == self._project_ifc() else None) if b.get("q") else []

    def all_rows(self):
        """Items added up over every block, each block counted as many times as it is repeated."""
        agg = {}
        for b in self.blocks:
            n = max(1, int(b.get("repeat", 1)))
            for g, item, unit, qty, rate, cost in self.block_rows(b):
                a = agg.setdefault((g, item), [g, item, unit, 0.0, rate, 0.0])
                a[3] += qty * n
                a[5] += cost * n
        return list(agg.values())

    def grand(self):
        rows = self.all_rows()
        return totals(rows, self.allow, 1)

    # ----- refresh -----
    def refresh(self):
        self._busy = True
        try:
            t = self.btab
            t.setRowCount(len(self.blocks))
            for r, b in enumerate(self.blocks):
                cells = [b["name"], b["path"], str(b.get("repeat", 1)), b.get("status") or ("read" if b.get("q") else "quantities not read yet"),
                         rand(totals(self.block_rows(b), self.allow)[4]) if b.get("q") else ""]
                for c, txt in enumerate(cells):
                    it = QTableWidgetItem(txt)
                    if c not in (0, 2):
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    t.setItem(r, c, it)
            rows = self.all_rows()
            self.bomt.setRowCount(len(rows))
            for r, (g, item, unit, qty, rate, cost) in enumerate(rows):
                for c, txt in enumerate((g, item, unit, num(qty, 1 if qty < 1000 else 0), num(rate, 2), rand(cost))):
                    it = QTableWidgetItem(txt)
                    if c >= 3:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.bomt.setItem(r, c, it)
            rt = self.ratet
            rt.setRowCount(len(RATES))
            for r, (k, (desc, unit, rate, src)) in enumerate(RATES.items()):
                o = self.rates.get(k)
                vals = (desc, unit, "%.2f" % (o["rate"] if o else rate), o["source"] if o else src)
                for c, txt in enumerate(vals):
                    it = QTableWidgetItem(txt)
                    if c != 2:
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    rt.setItem(r, c, it)
            at = self.allowt
            at.setRowCount(len(ALLOW))
            for r, (k, (desc, unit, d)) in enumerate(ALLOW.items()):
                vals = (desc, unit, "%g" % float(self.allow.get(k, d)))
                for c, txt in enumerate(vals):
                    it = QTableWidgetItem(txt)
                    if c != 2:
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    at.setItem(r, c, it)
            qs = [("Half-brick walls (110), face area", "m2", "brick110"), ("One-brick walls (220), face area", "m2", "brick220"),
                  ("Cavity walls (280), face area", "m2", "cavity"), ("Plastered wall area, both faces", "m2", "plaster_area"),
                  ("Plain brick wall area, both faces", "m2", "plain_brick_area"), ("Footings", "m3", "footing_vol"),
                  ("Floor slabs", "m3", "slab_vol"), ("Floor slab area", "m2", "slab_area"), ("Tiled floor area", "m2", "tile_area"),
                  ("Roof slabs", "m3", "roof_slab_vol"), ("Roof area", "m2", "roof_area"), ("Beams, columns, stairs", "m3", "beam_vol"),
                  ("Windows", "m2", "win_area"), ("Windows", "no.", "win_n"), ("Doors", "no.", "door_n"), ("Gates (not costed)", "no.", "gate_n")]
            qt = self.qt_
            qt.setRowCount(len(qs))
            for r, (d, u, k) in enumerate(qs):
                val = sum((b["q"] or {}).get(k, 0) * max(1, int(b.get("repeat", 1))) for b in self.blocks if b.get("q"))
                for c, txt in enumerate((d, u, num(val, 1 if u != "no." else 0))):
                    qt.setItem(r, c, QTableWidgetItem(txt))
            mat, lab, pre, con, tot = self.grand()
            self.total.setText("Materials %s  +  labour %s  +  overheads %s  +  contingency %s  =  %s" %
                               (rand(mat), rand(lab), rand(pre), rand(con), rand(tot)) if self.blocks else "")
        finally:
            self._busy = False

    def _r_edit(self, it):
        if self._busy or it.column() != 2 or not (0 <= it.row() < len(RATES)):
            return
        k = list(RATES)[it.row()]
        try:
            val = float(it.text().replace(" ", "").replace(",", "."))
        except ValueError:
            return
        self.rates[k] = {"rate": val, "source": "set by you " + __import__("datetime").date.today().isoformat()}
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)

    def _a_edit(self, it):
        if self._busy or it.column() != 2 or not (0 <= it.row() < len(ALLOW)):
            return
        k = list(ALLOW)[it.row()]
        try:
            self.allow[k] = float(it.text().replace(" ", "").replace(",", "."))
        except ValueError:
            return
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)

    # ----- AI prices -----
    def ai_prices(self):
        M = sys.modules[type(self.host.win).__module__]
        if not M.online_ready():
            QMessageBox.information(self, "Materials", "Updating prices uses Claude with web search. Switch Online mode on and enter your API key first "
                                    "(the button at the top right, or Tools > Online mode).")
            return
        from costing import ai_search
        items = "\n".join('- key "%s": %s, per %s' % (k, d, u) for k, (d, u, _r, _s) in RATES.items())
        prompt = ("You are helping a South African builder update his material prices. Use web search to find current retail or merchant prices in "
                  "rand, including VAT, from South African suppliers (Builders Warehouse, Cashbuild, Buco, Italtile, BUCO, local brickyards, "
                  "roof and ceiling suppliers). Items:\n" + items +
                  '\nReturn ONLY JSON: {"prices": [{"key": "brick", "price_zar": 2.4, "source": "shop name and page URL"}]}. '
                  "One entry per key you found a real price for, in the unit given. Never guess: leave a key out if you found nothing. "
                  "For labour-inclusive items (roof covering laid, windows fitted) give a typical supplied-and-fitted rate only if you found one.")
        self.note.setText("Searching for prices... this takes a minute or two.")

        def work():
            try:
                text, _urls = ai_search(M, prompt, (), max_uses=10, max_tokens=4000)
                t = text.strip()
                a, b = t.find("{"), t.rfind("}")
                d = json.loads(t[a:b + 1])
                self.price_found.emit(d.get("prices", []), "")
            except Exception as e:
                self.price_found.emit([], str(e))
        if not getattr(self, "_pf_wired", False):
            self.price_found.connect(self._prices_back)
            self._pf_wired = True
        threading.Thread(target=work, daemon=True).start()

    price_found = Signal(object, str)

    def _prices_back(self, prices, err):
        self.note.setText("Rates are starting figures (the Where-from column says which). Prices are taken as including VAT. "
                          "This is a budget estimate, not a bill of quantities.")
        if err:
            QMessageBox.warning(self, "Materials", "The price search failed: " + err)
            return
        good = [p for p in prices if isinstance(p, dict) and p.get("key") in RATES and float(p.get("price_zar") or 0) > 0]
        if not good:
            QMessageBox.information(self, "Materials", "The search found no usable prices.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Prices found")
        dlg.resize(820, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Tick the prices to use. Check the source before you rely on them."))
        t = QTableWidget(len(good), 5)
        t.setHorizontalHeaderLabels(["Use", "Material", "Now", "Found", "Source"])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for r, p in enumerate(good):
            k = p["key"]
            cur = self.rates.get(k, {}).get("rate", RATES[k][2])
            c = QTableWidgetItem("")
            c.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            c.setCheckState(Qt.CheckState.Checked)
            t.setItem(r, 0, c)
            for ci, txt in ((1, RATES[k][0] + " (per " + RATES[k][1] + ")"), (2, "%.2f" % cur), (3, "%.2f" % float(p["price_zar"])), (4, str(p.get("source", ""))[:200])):
                t.setItem(r, ci, QTableWidgetItem(txt))
        lay.addWidget(t)
        ok = QPushButton("Use the ticked prices")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        if dlg.exec():
            import datetime
            for r, p in enumerate(good):
                if t.item(r, 0).checkState() == Qt.CheckState.Checked:
                    self.rates[p["key"]] = {"rate": float(p["price_zar"]), "source": ("AI search %s: %s" % (datetime.date.today().isoformat(), str(p.get("source", ""))))[:160]}
            self.refresh()

    # ----- reports -----
    def report_html(self):
        import datetime
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        rd = getattr(self.host.win, "rd", {}) or {}
        th = lambda t, w: '<th bgcolor="%s" width="%d%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left": '<td style="padding:3px;text-align:%s;">%s</td>' % (a, t)
        out = ['<h2 style="color:%s;">Building materials estimate</h2>' % RED,
               '<p style="font-size:9pt;color:#444;">%s &nbsp;|&nbsp; %s</p>' % (e(rd.get("project") or "Project"), datetime.date.today().strftime("%d %B %Y"))]
        out.append("<h3>Blocks</h3>")
        rows = "".join("<tr>%s%s%s</tr>" % (td(e(b["name"])), td(str(b.get("repeat", 1)), "center"),
                                            td(rand(totals(self.block_rows(b), self.allow)[4]) if b.get("q") else "not read", "right")) for b in self.blocks)
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s</tr>%s</table>' % (th("Block", 60), th("Identical blocks", 15), th("Cost of one block (all-in)", 25), rows))
        out.append("<h3>Bill of materials, all blocks</h3>")
        rows, last = "", None
        for g, item, unit, qty, rate, cost in self.all_rows():
            rows += "<tr>%s%s%s%s%s</tr>" % (td(e(g) if g != last else ""), td(e(item)), td(e(unit), "center"), td(num(qty, 1 if qty < 1000 else 0), "right"),
                                              td(num(rate, 2), "right") + td(rand(cost), "right"))
            last = g
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s%s%s%s</tr>%s</table>' %
                   (th("", 14), th("Item", 36), th("Unit", 8), th("Quantity", 14), th("Rate", 12), th("Cost", 16), rows))
        mat, lab, pre, con, tot = self.grand()
        A = lambda k: float(self.allow.get(k, ALLOW[k][2]))
        t = ('<tr>%s%s</tr><tr>%s%s</tr><tr>%s%s</tr><tr>%s%s</tr><tr>%s%s</tr>' %
             (td("Materials"), td(rand(mat), "right"), td("Labour and plant %g %%" % A("labour_pct")), td(rand(lab), "right"),
              td("Preliminaries, overheads, profit %g %%" % A("prelim_pct")), td(rand(pre), "right"),
              td("Contingency %g %%" % A("contingency_pct")), td(rand(con), "right"), td("<b>Estimated building cost</b>"), td("<b>%s</b>" % rand(tot), "right")))
        out.append('<p></p><table width="55%%" align="right" border="0.6" cellspacing="0" style="font-size:9pt;">%s</table>' % t)
        out.append('<p style="font-size:7.5pt;color:#666;">Quantities are read from the IFC model; allowances and rates are typical starting figures that can be changed in the program. '
                   'Rates include VAT. Services (electrical, plumbing), sitework, fixtures and professional fees are not included. A budget estimate, not a bill of quantities.</p>')
        return "".join(out)

    def write_pdf(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        w.setTitle("Building materials estimate")
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.report_html() + "</body></html>")
        d.print_(w)

    def preview_pdf(self):
        try:
            self.host.win.preview_pdf_report(self.write_pdf, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, "Materials", "The preview could not be shown (%s). Use Export PDF." % e)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export materials estimate", "Building materials estimate.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.write_pdf(path)
            QMessageBox.information(self, "Materials", "PDF saved:\n" + path)

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export materials estimate", "Building materials estimate.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Group", "Item", "Unit", "Quantity", "Rate", "Cost"])
            for g, item, unit, qty, rate, cost in self.all_rows():
                w.writerow([g, item, unit, "%.2f" % qty, "%.2f" % rate, "%.2f" % cost])
            mat, lab, pre, con, tot = self.grand()
            for n, v in (("Materials", mat), ("Labour and plant", lab), ("Overheads and profit", pre), ("Contingency", con), ("Total", tot)):
                w.writerow([n, "", "", "", "", "%.2f" % v])
