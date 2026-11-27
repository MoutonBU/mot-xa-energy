"""SDP Creator: the Site Development Plan (SDP) that goes to council with a multi-block development.
Three simple steps: the site (name, erf, zoning, limits), the blocks (H1, H2, ... with phase, units, footprint, floor area, parking bays), and the
sheet (what complies, and one PDF with the plan, the title block, the schedule of blocks by phase and the checks).
The stand and the building footprints can be read from Building lines, and the floor areas from the Area schedule."""
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import tool_base as tb
from flow_layout import FlowLayout
from tool_base import ToolBase

TYPES = ["Maxi", "Standard 3-storey", "Standard 2-storey", "Other"]
COLS = ["Block", "Phase", "Type", "Storeys", "Units", "Footprint m2", "Floor area m2", "Bays", "Counts"]
SCALES = ["1:200", "1:250", "1:500", "1:1000", "1:1250", "1:2000"]


def _num(x, d=0.0):
    return tb.num(x, d)


def blank_site():
    return {"project": "", "erf": "", "township": "", "zoning": "", "owner": "", "drawing": "SDP-01", "scale": "1:500", "date": time.strftime("%Y-%m-%d"),
            "stand_area": 0.0, "follow": True, "max_cov": 0.0, "max_far": 0.0, "max_density": 0.0, "bays_per_unit": 1.0, "visitor_per": 5, "extra_bays": 0, "notes": ""}


def blank_block(name="", phase="Phase 1", typ="Standard 3-storey", storeys=3, units=0, foot=0.0, floor=0.0, bays=0, cov=True):
    return {"block": name, "phase": phase, "type": typ, "storeys": storeys, "units": units, "foot": foot, "floor": floor, "bays": bays, "cov": cov}


def analyse(site, blocks):
    """Totals per phase and for the whole development, and each check against the limits that were typed in (0 = no limit)."""
    area = _num(site.get("stand_area"))
    phases = {}
    for b in blocks:
        p = phases.setdefault(b.get("phase") or "Phase 1", {"blocks": 0, "units": 0, "foot": 0.0, "cov_foot": 0.0, "floor": 0.0, "bays": 0})
        p["blocks"] += 1
        p["units"] += int(_num(b.get("units")))
        p["foot"] += _num(b.get("foot"))
        p["cov_foot"] += _num(b.get("foot")) if b.get("cov", True) else 0.0
        p["floor"] += _num(b.get("floor"))
        p["bays"] += int(_num(b.get("bays")))
    tot = {k: sum(p[k] for p in phases.values()) for k in ("blocks", "units", "foot", "cov_foot", "floor", "bays")}
    tot["bays"] += int(_num(site.get("extra_bays")))
    cov = 100.0 * tot["cov_foot"] / area if area else 0.0
    far = tot["floor"] / area if area else 0.0
    dens = tot["units"] / (area / 10000.0) if area else 0.0
    per = max(0, int(_num(site.get("visitor_per"))))
    need = int(math.ceil(tot["units"] * _num(site.get("bays_per_unit"), 1.0) - 1e-9)) + (int(math.ceil(tot["units"] / float(per) - 1e-9)) if per else 0)
    lim = lambda k: _num(site.get(k))
    checks = [("Coverage", "%.1f %%" % cov, ("%.1f %%" % lim("max_cov")) if lim("max_cov") else "no limit", (not lim("max_cov")) or cov <= lim("max_cov") + 1e-6),
              ("Floor area ratio", "%.2f" % far, ("%.2f" % lim("max_far")) if lim("max_far") else "no limit", (not lim("max_far")) or far <= lim("max_far") + 1e-6),
              ("Density", "%.1f units/ha" % dens, ("%.1f units/ha" % lim("max_density")) if lim("max_density") else "no limit", (not lim("max_density")) or dens <= lim("max_density") + 1e-6),
              ("Parking bays", "%d provided" % tot["bays"], "%d required" % need, tot["bays"] >= need)]
    return {"area": area, "phases": phases, "total": tot, "cov": cov, "far": far, "density": dens, "bays_needed": need, "checks": checks,
            "ok": all(c[3] for c in checks)}


def block_names(prefix, first, last):
    return ["%s%d" % (prefix, i) for i in range(first, last + 1)]


class _BlocksDialog(QDialog):
    """add a run of blocks in one go: H1 to H26, which phase, which type"""

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
        n = self.first.value(), max(self.first.value(), self.last.value())
        return [blank_block(nm, self.phase.text().strip() or "Phase 1", self.typ.currentText(), 2 if "2-storey" in self.typ.currentText() else 3, self.units.value())
                for nm in block_names(self.prefix.text().strip() or "H", n[0], n[1])]


class SdpPage(ToolBase):
    KEY = "sdp"
    TITLE = "SDP Creator"
    STEP_NAMES = ["The site", "The blocks", "The sheet"]
    STEP_HINTS = ["Type the name of the development, the erf, the zoning and the limits from the zoning scheme. Leave a limit at 0 when there is none.",
                  "One line for each block (H1, H2 ...): its phase, how many units, the footprint, the floor area and the parking bays. Add a whole run of blocks at once.",
                  "What complies and what does not, then save the Site Development Plan as a PDF for council."]

    def __init__(self, win):
        super().__init__(win)
        self._busy = False
        self.f = {}
        # ---- step 1: the site
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The development", "These go in the title block of the sheet.")
        fl = QFormLayout()
        for key, label, tip in (("project", "Development name", "for example Blue Hills Estate"), ("erf", "Erf number", ""), ("township", "Township or town", ""),
                                ("zoning", "Zoning", "for example Residential zone III"), ("owner", "Owner or applicant", ""), ("drawing", "Drawing number", "")):
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
        v1.addWidget(bx)
        bx, bv = self.box("The site area", "The area of the whole stand, in square metres.")
        row = FlowLayout(None, 10, 6)
        self.f["stand_area"] = self._spin(0, 99999999, 0, 1, " m2")
        row.addWidget(QLabel("Stand area"))
        row.addWidget(self.f["stand_area"])
        self.f["follow"] = QCheckBox("Take it from Building lines")
        self.f["follow"].setChecked(True)
        self.f["follow"].toggled.connect(self._follow_changed)
        row.addWidget(self.f["follow"])
        row.addStretch(1)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("The limits", "From the zoning scheme. A limit of 0 means there is none, and it is not checked.")
        row = FlowLayout(None, 10, 6)
        for key, label, hi, dec, suf in (("max_cov", "Coverage not more than", 100, 1, " %"), ("max_far", "Floor area ratio not more than", 20, 2, ""),
                                         ("max_density", "Density not more than", 1000, 1, " units/ha")):
            self.f[key] = self._spin(0, hi, 0, dec, suf)
            row.addWidget(self._pair(label, self.f[key]))
        bv.addLayout(row)
        row = FlowLayout(None, 10, 6)
        self.f["bays_per_unit"] = self._spin(0, 10, 1.0, 2, " per unit")
        self.f["visitor_per"] = QSpinBox()
        self.f["visitor_per"].setRange(0, 100)
        self.f["visitor_per"].setValue(5)
        self.f["visitor_per"].setSuffix(" units")
        self.f["visitor_per"].setSpecialValueText("none")
        self.f["extra_bays"] = QSpinBox()
        self.f["extra_bays"].setRange(0, 9999)
        self.f["extra_bays"].setToolTip("Bays that belong to no block, for example visitors' bays or bays at the restaurant.")
        for key in ("bays_per_unit", "visitor_per", "extra_bays"):
            self.f[key].valueChanged.connect(self.changed)
        row.addWidget(self._pair("Parking for residents", self.f["bays_per_unit"]))
        row.addWidget(self._pair("One visitor's bay for every", self.f["visitor_per"]))
        row.addWidget(self._pair("Extra bays not in a block", self.f["extra_bays"]))
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("Notes on the sheet", "Printed under the schedule, for example the conditions of the approval or the phasing.")
        from PySide6.QtWidgets import QPlainTextEdit
        self.f["notes"] = QPlainTextEdit()
        self.f["notes"].setMinimumHeight(90)
        self.f["notes"].textChanged.connect(self.changed)
        bv.addWidget(self.f["notes"])
        v1.addWidget(bx)
        v1.addStretch(1)
        for k in ("max_cov", "max_far", "max_density", "stand_area"):
            self.f[k].valueChanged.connect(self.changed)
        # ---- step 2: the blocks
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The blocks", "Click a cell to type. Phase is just a name, for example Phase 1 and Phase 2. Untick 'Counts' for a building that must not count toward coverage.")
        br = FlowLayout(None, 8, 6)
        for text, fn, tip in (("Add a block", self.add_block, ""), ("Add several blocks...", self.add_run, "For example H1 to H26 in one go."),
                              ("Remove selected", self.remove_blocks, ""),
                              ("Read from Building lines", self.read_from_site, "Adds a block for each building in Building lines, with its footprint area."),
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
        for i, w_ in enumerate((90, 110, 160, 70, 70, 110, 120, 70, 70)):
            self.t.setColumnWidth(i, w_)
        h.setStretchLastSection(True)
        self.t.setMinimumHeight(380)
        self.t.itemChanged.connect(self._edited)
        bv.addWidget(self.t)
        self.sum_lbl = QLabel("")
        self.sum_lbl.setObjectName("xaSub")
        self.sum_lbl.setWordWrap(True)
        bv.addWidget(self.sum_lbl)
        v2.addWidget(bx, 1)
        # ---- step 3: the sheet
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("What complies", "Green complies, red does not.")
        self.rt = QTableWidget(0, 4)
        self.rt.setHorizontalHeaderLabels(["Check", "In the design", "Limit", "Result"])
        self.rt.verticalHeader().setVisible(False)
        self.rt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rt.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rt.verticalHeader().setDefaultSectionSize(36)
        self.rt.setMinimumHeight(200)
        bv.addWidget(self.rt)
        self.pt = QTableWidget(0, 6)
        self.pt.setHorizontalHeaderLabels(["Phase", "Blocks", "Units", "Footprint m2", "Floor area m2", "Bays"])
        self.pt.verticalHeader().setVisible(False)
        self.pt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pt.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pt.verticalHeader().setDefaultSectionSize(32)
        self.pt.setMinimumHeight(170)
        bv.addWidget(self.pt)
        v3.addWidget(bx)
        bx, bv = self.box("The sheet", "Preview it, or save it as a PDF to submit. The plan is the one drawn in Building lines.")
        row = QHBoxLayout()
        for text, fn in (("Preview", self.preview), ("Save PDF...", self.export)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        v3.addWidget(bx)
        v3.addStretch(1)
        self.build_frame([p1, p2, p3])
        self.set_state({})
        self.restore()

    # ---- small helpers
    @staticmethod
    def _spin(lo, hi, val, dec, suffix=""):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setValue(val)
        if suffix:
            s.setSuffix(suffix)
        s.setMaximumWidth(150)
        return s

    @staticmethod
    def _pair(label, w):
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        h.addWidget(w)
        return c

    def _site_page(self):
        return getattr(self.win, "site_page", None)

    def _follow_changed(self, *_a):
        on = self.f["follow"].isChecked()
        self.f["stand_area"].setEnabled(not on)
        if on:
            self.read_stand_area()
        self.changed()

    def read_stand_area(self):
        sp = self._site_page()
        try:
            a = sp.result()["area"] if sp is not None else 0.0
        except Exception:
            a = 0.0
        if a > 0:
            self.f["stand_area"].setValue(round(a, 1))
        return a

    # ---- the blocks table
    def _row(self, b):
        t = self.t
        r = t.rowCount()
        was = t.blockSignals(True)
        t.insertRow(r)
        vals = [b["block"], b["phase"], b["type"], b["storeys"], b["units"], "%.2f" % _num(b["foot"]), "%.2f" % _num(b["floor"]), b["bays"]]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(str(v))
            if c >= 3:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(r, c, it)
        cb = QTableWidgetItem("")
        cb.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        cb.setCheckState(Qt.CheckState.Checked if b.get("cov", True) else Qt.CheckState.Unchecked)
        t.setItem(r, 8, cb)
        t.blockSignals(was)

    def blocks(self):
        out = []
        t = self.t
        tx = lambda r, c: t.item(r, c).text().strip() if t.item(r, c) else ""
        for r in range(t.rowCount()):
            out.append({"block": tx(r, 0), "phase": tx(r, 1) or "Phase 1", "type": tx(r, 2), "storeys": int(_num(tx(r, 3))), "units": int(_num(tx(r, 4))),
                        "foot": _num(tx(r, 5)), "floor": _num(tx(r, 6)), "bays": int(_num(tx(r, 7))),
                        "cov": bool(t.item(r, 8) and t.item(r, 8).checkState() == Qt.CheckState.Checked)})
        return out

    def fill_blocks(self, blocks):
        was = self.t.blockSignals(True)
        self.t.setRowCount(0)
        self.t.blockSignals(was)
        for b in blocks:
            self._row(dict(blank_block(), **b))
        self.refresh()

    def add_block(self):
        n = self.t.rowCount() + 1
        last = self.blocks()[-1] if self.t.rowCount() else None
        self._row(blank_block("H%d" % n, last["phase"] if last else "Phase 1", last["type"] if last else "Standard 3-storey",
                              last["storeys"] if last else 3, last["units"] if last else 0))
        self.t.scrollToBottom()
        self._edited()

    def add_run(self):
        d = _BlocksDialog(self)
        if d.exec():
            for b in d.blocks():
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

    def read_from_site(self):
        sp = self._site_page()
        if sp is None:
            QMessageBox.information(self, self.TITLE, "Building lines is not available.")
            return
        have = {b["block"].lower() for b in self.blocks()}
        added = 0
        rows = {b["block"].lower(): r for r, b in enumerate(self.blocks())}
        was = self.t.blockSignals(True)
        try:
            from site_lines import bpoly, signed_area
            for b in sp.buildings():
                area = abs(signed_area(bpoly(b)))
                k = b["name"].lower()
                if k in have:
                    self.t.item(rows[k], 5).setText("%.2f" % area)
                else:
                    self._row(blank_block(b["name"], foot=area, cov=bool(b.get("cov", True))))
                    added += 1
        finally:
            self.t.blockSignals(was)
        self._edited()
        QMessageBox.information(self, self.TITLE, "%d new block%s added from Building lines. Footprints of blocks with the same name were updated." % (added, "" if added == 1 else "s"))

    def read_floor_areas(self):
        ap = getattr(self.win, "area_page", None)
        if ap is None:
            QMessageBox.information(self, self.TITLE, "The Area schedule is not available.")
            return
        sums = {}
        for r in ap.rows():
            if r["block"]:
                sums[r["block"].strip().lower()] = sums.get(r["block"].strip().lower(), 0.0) + (r["area"] if r["far"] else 0.0)
        n = 0
        was = self.t.blockSignals(True)
        for r in range(self.t.rowCount()):
            k = (self.t.item(r, 0).text() if self.t.item(r, 0) else "").strip().lower()
            if k in sums and sums[k] > 0:
                self.t.item(r, 6).setText("%.2f" % sums[k])
                n += 1
        self.t.blockSignals(was)
        self._edited()
        QMessageBox.information(self, self.TITLE, "Floor area filled in for %d block%s." % (n, "" if n == 1 else "s") if n else
                                "No block name in the Area schedule matches a block here. Use the same names, for example H1.")

    def _edited(self, *_a):
        self.changed()

    def changed(self, *_a):
        if self._busy:
            return
        self.refresh()
        super().changed()

    # ---- the numbers
    def site(self):
        d = {}
        for k, w in self.f.items():
            if isinstance(w, QLineEdit):
                d[k] = w.text().strip()
            elif isinstance(w, QComboBox):
                d[k] = w.currentText().strip()
            elif isinstance(w, QCheckBox):
                d[k] = w.isChecked()
            elif isinstance(w, QDoubleSpinBox) or isinstance(w, QSpinBox):
                d[k] = w.value()
            else:
                d[k] = w.toPlainText()
        return d

    def result(self):
        s = self.site()
        if s.get("follow"):
            self.read_stand_area()
            s["stand_area"] = self.f["stand_area"].value()
        return analyse(s, self.blocks())

    def refresh(self, *_a):
        if getattr(self, "rt", None) is None or self._busy:
            return
        self._busy = True
        try:
            an = self.result()
        finally:
            self._busy = False
        t = an["total"]
        self.sum_lbl.setText("%d blocks | %d units | footprint %.1f m2 | floor area %.1f m2 | %d bays" % (t["blocks"], t["units"], t["foot"], t["floor"], t["bays"]))
        self._busy = True
        self.rt.setRowCount(0)
        for i, (nm, val, lim, ok) in enumerate(an["checks"]):
            self.rt.insertRow(i)
            for c, v in enumerate((nm, val, lim, "Complies" if ok else "Does not comply")):
                lab = QLabel(v)                              # a label with its own colours reads the same in light and dark mode
                lab.setStyleSheet("background:%s; color:#111111; padding:2px 8px; font-weight:%s;" % ("#cfeedd" if ok else "#f7cdd2", "normal" if c < 3 else "bold"))
                lab.setMinimumHeight(30)
                self.rt.setCellWidget(i, c, lab)
        self.pt.setRowCount(0)
        rows = [(k, p) for k, p in an["phases"].items()] + [("All phases", dict(an["total"]))]
        for i, (k, p) in enumerate(rows):
            self.pt.insertRow(i)
            for c, v in enumerate((k, p["blocks"], p["units"], "%.1f" % p["foot"], "%.1f" % p["floor"], p["bays"])):
                self.pt.setItem(i, c, QTableWidgetItem(str(v)))
        self._busy = False

    def on_step(self, i):
        if i == 2:
            self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        if self.f["follow"].isChecked():
            self.read_stand_area()
        self.refresh()

    # ---- the sheet
    def report_resources(self):
        sp = self._site_page()
        try:
            if sp is not None and len(sp.verts()) >= 3:
                return {"plan": sp.plan.snapshot(1400, 900)}
        except Exception:
            pass
        return {}

    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        s = self.site()
        an = self.result()
        e = tb.esc
        name = s["project"] or rd.get("project") or "Site Development Plan"
        erf = " | ".join(x for x in (("Erf " + s["erf"]) if s["erf"] else "", s["township"]) if x)
        body = ('<table width="100%%" cellspacing="0" cellpadding="6" border="0.8" style="border-color:#444444;"><tr>'
                '<td width="62%%"><span style="font-size:10pt; color:#555555;">SITE DEVELOPMENT PLAN</span><br><span style="font-size:17pt; font-weight:bold;">%s</span>'
                '<br><span style="font-size:10pt;">%s</span></td>'
                '<td width="38%%" style="font-size:9pt;">Owner / applicant: %s<br>Zoning: %s<br>Stand area: %.1f m2<br>Drawing: %s &nbsp; Scale %s (at A3)<br>Date: %s</td></tr></table>'
                % (e(name), e(erf), e(s["owner"] or "-"), e(s["zoning"] or "-"), an["area"], e(s["drawing"]), e(s["scale"]), e(s["date"])))
        if self.report_resources():
            body += '<p align="center"><img src="plan" width="760"></p><p style="font-size:8pt; color:#555555;">The stand, its building lines and the buildings, from Building lines.</p>'
        head = ["Block", "Phase", "Type", "Storeys", "Units", "Footprint m2", "Floor area m2", "Bays"]
        rows = []
        for ph, p in an["phases"].items():
            for b in self.blocks():
                if (b["phase"] or "Phase 1") == ph:
                    rows.append([b["block"], ph, b["type"], b["storeys"], b["units"], "%.1f" % b["foot"], "%.1f" % b["floor"], b["bays"]])
            rows.append(([ph + " total", "", "%d blocks" % p["blocks"], "", p["units"], "%.1f" % p["foot"], "%.1f" % p["floor"], p["bays"]], "#e9e9e9"))
        t = an["total"]
        rows.append(([("All phases"), "", "%d blocks" % t["blocks"], "", t["units"], "%.1f" % t["foot"], "%.1f" % t["floor"], t["bays"]], "#d6d6d6"))
        body += "<h3>Schedule of blocks</h3>" + tb.table(head, rows, aligns=["left", "left", "left", "right", "right", "right", "right", "right"])
        crow = [([n, v, l, "complies" if ok else "does not comply"], "#e4f4ea" if ok else "#fbe3e6") for n, v, l, ok in an["checks"]]
        body += "<h3>Development parameters</h3>" + tb.table(["Check", "In the design", "Limit", "Result"], crow)
        if s["notes"].strip():
            body += "<h3>Notes</h3><p>%s</p>" % e(s["notes"]).replace("\n", "<br>")
        return tb.report_doc_html("Site Development Plan", "%s%s" % (name, (" | " + erf) if erf else ""), body, rd)

    def write_report(self, path):
        d, w = tb.write_pdf(path, self.report_html(), self.TITLE, landscape=True, resources=self.report_resources())
        tb.print_doc(d, w)

    # ---- state
    def state(self):
        return {"site": self.site(), "blocks": self.blocks()}

    def set_state(self, d):
        d = d or {}
        self._busy = True
        try:
            s = dict(blank_site(), **(d.get("site") or {}))
            for k, w in self.f.items():
                v = s.get(k)
                if isinstance(w, QLineEdit):
                    w.setText(str(v or ""))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(v or ""))
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                    w.setValue(_num(v))
                else:
                    w.setPlainText(str(v or ""))
            self.f["stand_area"].setEnabled(not self.f["follow"].isChecked())
            self.fill_blocks(d.get("blocks") or [])
        finally:
            self._busy = False
        self.refresh()
