"""Area schedule: every room with its block, level, unit and type; totals by block, level, unit and room type; the unit mix;
and the floor area that counts toward the floor area ratio (FAR)."""
import csv
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import tool_base as tb
from tool_base import ToolBase

# type, counts toward FAR by default (check the zoning scheme: some schemes count garages or balconies)
KINDS = [("Habitable room", True), ("Kitchen", True), ("Bathroom / WC", True), ("Passage / stairs", True),
         ("Storage / utility", True), ("Garage / carport", False), ("Balcony / patio / veranda", False),
         ("Plant / services", False), ("Other", True)]
KIND_NAMES = [k for k, _ in KINDS]
KIND_FAR = dict(KINDS)
KIND_WORDS = [("Garage / carport", ("garage", "carport", "parking")), ("Balcony / patio / veranda", ("balcon", "patio", "veranda", "stoep", "deck", "terrace")),
              ("Plant / services", ("plant", "meter", "geyser", "service", "lift")), ("Kitchen", ("kitchen", "scullery")),
              ("Bathroom / WC", ("bath", "wc", "toilet", "shower", "ensuite", "en-suite", "cloak", "powder")),
              ("Passage / stairs", ("passage", "hall", "stair", "entrance", "foyer", "lobby", "corridor", "landing")),
              ("Storage / utility", ("store", "laundry", "pantry", "utility", "wardrobe", "dress", "linen")),
              ("Habitable room", ("bed", "lounge", "living", "dining", "study", "family", "office", "tv", "room", "studio", "open plan"))]
HEAD = ["Block", "Level", "Unit", "Room", "Type", "Area m2", "Counts for FAR"]


def guess_kind(name):
    n = (name or "").lower()
    for kind, words in KIND_WORDS:
        if any(w in n for w in words):
            return kind
    return "Other"


class AreaPage(ToolBase):
    KEY = "areas"
    TITLE = "Area schedule"
    STEP_NAMES = ["The rooms", "The totals", "Reports"]
    STEP_HINTS = ["List every room with its area. Fill the list from the project or the IFC model, import a spreadsheet, or type the rooms in.",
                  "The totals by block, level, unit and room type, and the unit mix. Tick which rooms count toward the floor area ratio.",
                  "Save the schedule as a PDF for the submission, or as a spreadsheet."]

    def __init__(self, win):
        super().__init__(win)
        self.unit_types = {}
        self._busy = False
        self._bulk = False
        # ---- step 1: the rooms
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Where do the rooms come from?", "Pick one, or add rooms by hand under the list. Your block names and levels are kept.")
        from flow_layout import FlowLayout
        src = QWidget()
        fl = FlowLayout(src, 6, 6)
        for text, fn, tip in (("Fill from the project rooms", self.fill_project, "The rooms in Light & Ventilation (their floors and units come along)."),
                              ("Fill from the IFC model", self.fill_ifc, "The rooms read from the IFC model."),
                              ("Import a spreadsheet (CSV)...", self.import_csv, "Columns: Block, Level, Unit, Room, Type, Area."),
                              ("Paste from a spreadsheet", self.paste_rows, "Copy rows in a spreadsheet, then press this. Columns: Room, Area, Level, Unit, Block."),
                              ("Add a room", lambda: self.add_row(focus=True), "Add one empty line."),
                              ("Remove selected", self.remove_rows, "Remove the lines you selected."),
                              ("Clear the list", self.clear_rows, "Remove every line.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        src.setMinimumHeight(84)
        bv.addWidget(src)
        v1.addWidget(bx)
        self.table = QTableWidget(0, len(HEAD))
        self.table.setHorizontalHeaderLabels(HEAD)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for i, w_ in enumerate((90, 120, 80, 0, 215, 90, 120)):
            if w_:
                self.table.setColumnWidth(i, w_)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setMinimumHeight(320)
        self.table.itemChanged.connect(self._item_changed)
        v1.addWidget(self.table, 1)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("xaSub")
        v1.addWidget(self.count_lbl)
        # ---- step 2: the totals
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Totals")
        self.tot_lbl = QLabel("")
        self.tot_lbl.setWordWrap(True)
        bv.addWidget(self.tot_lbl)
        v2.addWidget(bx)
        bx, bv = self.box("By block and level")
        self.t_level = self._ro_table(["Block", "Level", "Rooms", "Area m2", "Counts for FAR m2"])
        bv.addWidget(self.t_level)
        v2.addWidget(bx)
        bx, bv = self.box("Units", "Type a unit type for each unit (for example 1 bed, 2 bed). The mix below is worked out from it.")
        self.t_unit = QTableWidget(0, 5)
        self.t_unit.setHorizontalHeaderLabels(["Block", "Unit", "Rooms", "Area m2", "Unit type"])
        self._style_ro(self.t_unit)
        self.t_unit.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.t_unit.itemChanged.connect(self._unit_type_edited)
        bv.addWidget(self.t_unit)
        v2.addWidget(bx)
        bx, bv = self.box("Unit mix")
        self.t_mix = self._ro_table(["Unit type", "How many", "Total m2", "Average m2"])
        bv.addWidget(self.t_mix)
        v2.addWidget(bx)
        bx, bv = self.box("By room type")
        self.t_kind = self._ro_table(["Type", "Rooms", "Area m2", "Counts for FAR"])
        bv.addWidget(self.t_kind)
        v2.addWidget(bx)
        v2.addStretch(1)
        # ---- step 3: reports
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Reports", "The PDF has the totals, the unit mix and the full room list.")
        row = QWidget()
        fl = FlowLayout(row, 6, 6)
        for text, fn in (("Preview the PDF", self.preview), ("Save the PDF...", self.export), ("Save as a spreadsheet (CSV)...", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        row.setMinimumHeight(46)
        bv.addWidget(row)
        self.far_lbl = QLabel("")
        self.far_lbl.setWordWrap(True)
        bv.addWidget(self.far_lbl)
        v3.addWidget(bx)
        v3.addStretch(1)
        self.build_frame([p1, p2, p3])
        self.restore()
        self.refresh()

    # ---- tables
    def _style_ro(self, t):
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setMinimumHeight(110)

    def _ro_table(self, head):
        t = QTableWidget(0, len(head))
        t.setHorizontalHeaderLabels(head)
        self._style_ro(t)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        return t

    def add_row(self, d=None, focus=False):
        d = d or {}
        self._busy = True
        try:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, key in ((0, "block"), (1, "level"), (2, "unit"), (3, "room")):
                self.table.setItem(r, c, QTableWidgetItem(str(d.get(key, "") or "")))
            kind = d.get("kind") or guess_kind(d.get("room", ""))
            cb = QComboBox()
            cb.addItems(KIND_NAMES)
            cb.setCurrentText(kind if kind in KIND_NAMES else "Other")
            cb.currentTextChanged.connect(lambda _t, w=cb: self._kind_changed(w))
            self.table.setCellWidget(r, 4, cb)
            a = QTableWidgetItem(("%.2f" % tb.num(d.get("area"))) if d.get("area") not in (None, "") else "")
            a.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, a)
            f = QTableWidgetItem("")
            f.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            far = d.get("far")
            f.setCheckState(Qt.CheckState.Checked if (KIND_FAR.get(cb.currentText(), True) if far is None else far) else Qt.CheckState.Unchecked)
            self.table.setItem(r, 6, f)
        finally:
            self._busy = False
        if focus:
            self.table.setCurrentCell(r, 3)
            self.table.editItem(self.table.item(r, 3))
        if not self._bulk:
            self.changed()
            self.refresh()

    def _bulk_add(self, items):
        self._bulk = True
        try:
            for d in items:
                self.add_row(d)
        finally:
            self._bulk = False
        self.changed()
        self.refresh()

    def _kind_changed(self, cb):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 4) is cb:
                it = self.table.item(r, 6)
                self._busy = True
                it.setCheckState(Qt.CheckState.Checked if KIND_FAR.get(cb.currentText(), True) else Qt.CheckState.Unchecked)
                self._busy = False
                break
        self.changed()
        self.refresh()

    def _item_changed(self, it):
        if self._busy:
            return
        if it.column() == 3:                            # a new room name: suggest its type when the type is still "Other"
            cb = self.table.cellWidget(it.row(), 4)
            if cb is not None and cb.currentText() == "Other":
                cb.setCurrentText(guess_kind(it.text()))
        self.changed()
        self.refresh()

    def rows(self):
        out = []
        t = self.table
        tx = lambda r, c: (t.item(r, c).text().strip() if t.item(r, c) else "")
        for r in range(t.rowCount()):
            cb = t.cellWidget(r, 4)
            out.append({"block": tx(r, 0), "level": tx(r, 1), "unit": tx(r, 2), "room": tx(r, 3),
                        "kind": cb.currentText() if cb else "Other", "area": tb.num(tx(r, 5)),
                        "far": bool(t.item(r, 6) and t.item(r, 6).checkState() == Qt.CheckState.Checked)})
        return out

    def remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.changed()
        self.refresh()

    def clear_rows(self):
        if self.table.rowCount() and QMessageBox.question(self, "Area schedule", "Remove all the rooms from the list?") != QMessageBox.StandardButton.Yes:
            return
        self.table.setRowCount(0)
        self.changed()
        self.refresh()

    def _ask_replace(self):
        if not self.table.rowCount():
            return True
        m = QMessageBox(self)
        m.setWindowTitle("Area schedule")
        m.setText("The list already has rooms.")
        rep = m.addButton("Replace them", QMessageBox.ButtonRole.DestructiveRole)
        m.addButton("Add to them", QMessageBox.ButtonRole.AcceptRole)
        cancel = m.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        m.exec()
        if m.clickedButton() is cancel:
            return None
        if m.clickedButton() is rep:
            self.table.setRowCount(0)
        return True

    # ---- sources
    def fill_project(self):
        try:
            rooms = self.win.read_rooms()
        except Exception:
            rooms = []
        if not rooms:
            QMessageBox.information(self, "Area schedule", "There are no rooms in Light & Ventilation yet. Add them there, or import the IFC model.")
            return
        if self._ask_replace() is None:
            return
        self._bulk_add([{"room": r.name, "area": r.area_m2, "level": r.floor, "unit": r.unit} for r in rooms])

    def fill_ifc(self):
        data = getattr(self.win, "ifc_data", None) or {}
        rooms = data.get("rooms") or []
        if not rooms:
            QMessageBox.information(self, "Area schedule", "No IFC model is loaded. Use Import IFC in the ribbon first.")
            return
        if self._ask_replace() is None:
            return
        self._bulk_add([{"room": r.get("name", ""), "area": r.get("area", 0), "level": r.get("floor") or "", "unit": r.get("unit", "")} for r in rooms])

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import rooms", "", "Spreadsheet (*.csv *.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                txt = f.read()
        except Exception as e:
            QMessageBox.warning(self, "Area schedule", "The file could not be read (%s)." % e)
            return
        n = self._load_text(txt)
        QMessageBox.information(self, "Area schedule", "%d rooms added." % n)

    def paste_rows(self):
        txt = QApplication.clipboard().text()
        if not txt.strip():
            QMessageBox.information(self, "Area schedule", "Copy the rows in your spreadsheet first (Room, Area, Level, Unit, Block), then press this again.")
            return
        n = self._load_text(txt, pasted=True)
        QMessageBox.information(self, "Area schedule", "%d rooms added." % n)

    def _load_text(self, txt, pasted=False):
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        if not lines:
            return 0
        try:
            dia = csv.Sniffer().sniff(lines[0], delimiters=";,\t")
            delim = dia.delimiter
        except Exception:
            delim = "\t" if "\t" in lines[0] else ";" if ";" in lines[0] else ","
        rows = list(csv.reader(lines, delimiter=delim))
        head = [c.strip().lower() for c in rows[0]]
        has_head = any(h in ("room", "name", "area", "block", "level", "floor", "unit", "type") for h in head)
        cols = {}
        if has_head:
            for i, h in enumerate(head):
                for key, words in (("room", ("room", "name")), ("area", ("area", "m2", "m²")), ("level", ("level", "floor", "storey")),
                                   ("unit", ("unit", "flat")), ("block", ("block", "building", "house")), ("kind", ("type", "kind", "use"))):
                    if key not in cols and any(w in h for w in words):
                        cols[key] = i
            rows = rows[1:]
        else:
            order = ("room", "area", "level", "unit", "block") if pasted else ("block", "level", "unit", "room", "kind", "area")
            cols = {k: i for i, k in enumerate(order)}
        if self._ask_replace() is None:
            return 0
        items = []
        for r in rows:
            g = lambda k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else "")
            if not g("room") and not g("area"):
                continue
            kind = g("kind")
            items.append({"room": g("room"), "area": tb.num(g("area")), "level": g("level"), "unit": g("unit"), "block": g("block"),
                          "kind": kind if kind in KIND_NAMES else None})
        self._bulk_add(items)
        return len(items)

    # ---- totals
    def far_area(self):
        return sum(r["area"] for r in self.rows() if r["far"])

    def total_area(self):
        return sum(r["area"] for r in self.rows())

    def _groups(self):
        rows = self.rows()
        lv, un, kd = {}, {}, {}
        for r in rows:
            a = lv.setdefault((r["block"], r["level"]), [0, 0.0, 0.0])
            a[0] += 1
            a[1] += r["area"]
            a[2] += r["area"] if r["far"] else 0
            if r["unit"]:
                u = un.setdefault((r["block"], r["unit"]), [0, 0.0])
                u[0] += 1
                u[1] += r["area"]
            k = kd.setdefault(r["kind"], [0, 0.0, 0.0])
            k[0] += 1
            k[1] += r["area"]
            k[2] += r["area"] if r["far"] else 0
        mix = {}
        for (b, u), (n, a) in un.items():
            ty = self.unit_types.get(b + "|" + u, "").strip() or "(no type yet)"
            m = mix.setdefault(ty, [0, 0.0])
            m[0] += 1
            m[1] += a
        return rows, lv, un, kd, mix

    def refresh(self):
        if getattr(self, "_refreshing", False):
            return
        self._refreshing = True
        try:
            rows, lv, un, kd, mix = self._groups()
            tot, far = sum(r["area"] for r in rows), sum(r["area"] for r in rows if r["far"])
            self.count_lbl.setText("%d rooms, %.2f m2 in all, %.2f m2 count toward FAR." % (len(rows), tot, far) if rows else
                                   "No rooms yet. Use one of the buttons above, or press Add a room.")
            self.tot_lbl.setText("<span style='font-size:16px'><b>%.2f m2</b> in all &nbsp;|&nbsp; <b>%.2f m2</b> count toward FAR &nbsp;|&nbsp; "
                                 "%.2f m2 do not &nbsp;|&nbsp; %d rooms</span>" % (tot, far, tot - far, len(rows)))
            self.far_lbl.setText("Floor area counted toward FAR: <b>%.2f m2</b>. Building lines uses this number for the floor area ratio." % far)
            self._fill(self.t_level, [[b or "-", l or "-", n, "%.2f" % a, "%.2f" % f] for (b, l), (n, a, f) in sorted(lv.items())])
            self._fill(self.t_kind, [[k, n, "%.2f" % a, "%.2f" % f] for k, (n, a, f) in sorted(kd.items())])
            self._fill(self.t_mix, [[t, n, "%.2f" % a, "%.2f" % (a / n if n else 0)] for t, (n, a) in sorted(mix.items())])
            t = self.t_unit
            if not t.hasFocus() and t.state() != QAbstractItemView.State.EditingState:
                t.blockSignals(True)
                t.setRowCount(0)
                for (b, u), (n, a) in sorted(un.items()):
                    r = t.rowCount()
                    t.insertRow(r)
                    for c, v in enumerate((b or "-", u, n, "%.2f" % a)):
                        it = QTableWidgetItem(str(v))
                        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        t.setItem(r, c, it)
                    ty = QTableWidgetItem(self.unit_types.get(b + "|" + u, ""))
                    ty.setData(Qt.ItemDataRole.UserRole, b + "|" + u)
                    t.setItem(r, 4, ty)
                t.blockSignals(False)
        finally:
            self._refreshing = False

    def _fill(self, t, rows):
        t.setRowCount(0)
        for r in rows:
            i = t.rowCount()
            t.insertRow(i)
            for c, v in enumerate(r):
                it = QTableWidgetItem(str(v))
                if c >= 1 and re.fullmatch(r"-?\d+(\.\d+)?", str(v)):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(i, c, it)

    def _unit_type_edited(self, it):
        if it.column() != 4:
            return
        key = it.data(Qt.ItemDataRole.UserRole)
        if key:
            self.unit_types[key] = it.text().strip()
            self.changed()
            rows, lv, un, kd, mix = self._groups()
            self._fill(self.t_mix, [[t, n, "%.2f" % a, "%.2f" % (a / n if n else 0)] for t, (n, a) in sorted(mix.items())])

    def on_step(self, i):
        if i == 1:
            self.refresh()

    # ---- state
    def state(self):
        return {"rows": self.rows(), "unit_types": dict(self.unit_types)}

    def set_state(self, d):
        d = d or {}
        self._busy = True
        self.table.setRowCount(0)
        self._busy = False
        self.unit_types = dict(d.get("unit_types") or {})
        self._bulk_add(d.get("rows") or [])

    # ---- reports
    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        rows, lv, un, kd, mix = self._groups()
        tot, far = sum(r["area"] for r in rows), sum(r["area"] for r in rows if r["far"])
        R = ["right"] * 5
        body = ('<p style="font-size:11pt;"><b>%.2f m2</b> in all, <b>%.2f m2</b> counted toward the floor area ratio, %d rooms.</p>' % (tot, far, len(rows)))
        body += "<h3>By block and level</h3>" + tb.table(["Block", "Level", "Rooms", "Area m2", "Counts for FAR m2"],
                                                         [[b or "-", l or "-", n, "%.2f" % a, "%.2f" % f] for (b, l), (n, a, f) in sorted(lv.items())] +
                                                         [["Total", "", len(rows), "%.2f" % tot, "%.2f" % far]], aligns=["left", "left", "right", "right", "right"])
        if un:
            body += "<h3>Units</h3>" + tb.table(["Block", "Unit", "Rooms", "Area m2", "Unit type"],
                                                [[b or "-", u, n, "%.2f" % a, self.unit_types.get(b + "|" + u, "")] for (b, u), (n, a) in sorted(un.items())],
                                                aligns=["left", "left", "right", "right", "left"])
            body += "<h3>Unit mix</h3>" + tb.table(["Unit type", "How many", "Total m2", "Average m2"],
                                                   [[t, n, "%.2f" % a, "%.2f" % (a / n if n else 0)] for t, (n, a) in sorted(mix.items())],
                                                   aligns=["left", "right", "right", "right"])
        body += "<h3>By room type</h3>" + tb.table(["Type", "Rooms", "Area m2", "Counts for FAR m2"],
                                                   [[k, n, "%.2f" % a, "%.2f" % f] for k, (n, a, f) in sorted(kd.items())],
                                                   aligns=["left", "right", "right", "right"])
        body += "<h3>Room list</h3>" + tb.table(["Block", "Level", "Unit", "Room", "Type", "Area m2", "FAR"],
                                                [[r["block"], r["level"], r["unit"], r["room"], r["kind"], "%.2f" % r["area"], "yes" if r["far"] else "no"] for r in rows],
                                                aligns=["left", "left", "left", "left", "left", "right", "center"])
        return tb.report_doc_html("Area schedule", "Floor areas by block, level, unit and room type", body, rd)

    def export_csv(self):
        rd = getattr(self.win, "rd", {}) or {}
        start = ((rd.get("project") or "").strip() or "Project") + " - Area schedule.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save the area schedule", start, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Block", "Level", "Unit", "Room", "Type", "Area m2", "Counts for FAR"])
            for r in self.rows():
                w.writerow([r["block"], r["level"], r["unit"], r["room"], r["kind"], "%.2f" % r["area"], "yes" if r["far"] else "no"])
        QMessageBox.information(self, "Area schedule", "Saved:\n" + path)
