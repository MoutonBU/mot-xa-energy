"""Guidelines review: check the design against the rules of the architectural development (estate guidelines) and the council's
guidelines. Rules are typed in once as sets. Where the program already knows the number (coverage, floor area ratio, building
lines, light, ventilation, glazing, floor area) it is measured for you; the rest you tick by hand or type the design value."""
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QScrollArea, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import tool_base as tb
from tool_base import ToolBase

KINDS = [("max", "Not more than"), ("min", "Not less than"), ("check", "Tick by hand")]
STATUS = ["To check", "Passes", "Fails", "Not applicable"]
# key -> label shown in the list
MEASURES = [("", "Typed by me"), ("cov", "Coverage % (Building lines)"), ("far", "Floor area ratio (Building lines)"),
            ("lines", "Building line encroachments (Building lines)"), ("floor", "Floor area m2 (Area schedule)"),
            ("light", "Rooms failing natural light"), ("vent", "Rooms failing ventilation"), ("glaze", "Rooms over the glazing limit")]
SETS = ["Architectural guidelines (development)", "Council guidelines"]
# set index, rule, kind, limit, unit, measure
USUAL = [
    (0, "Maximum coverage", "max", 50, "%", "cov"), (0, "Maximum floor area ratio", "max", 0.6, "", "far"),
    (0, "No building line encroachment", "max", 0, "", "lines"), (0, "Maximum building height", "max", 8, "m", ""),
    (0, "Roof pitch and material as the guidelines", "check", 0, "", ""), (0, "Colour and finish palette", "check", 0, "", ""),
    (0, "Boundary wall height", "max", 1.8, "m", ""), (0, "Parking bays", "min", 2, "", ""),
    (1, "Natural light: no room fails", "max", 0, "", "light"), (1, "Natural ventilation: no room fails", "max", 0, "", "vent"),
    (1, "Glazing within the limit", "max", 0, "", "glaze"), (1, "Building lines respected", "max", 0, "", "lines"),
    (1, "Coverage within the zoning", "max", 60, "%", "cov"), (1, "Parking as the scheme requires", "check", 0, "", ""),
]


def _f(x):
    try:
        return float(str(x).replace(",", ".").strip())
    except Exception:
        return None


class GuidelinesPage(ToolBase):
    KEY = "guidelines"
    TITLE = "Guidelines review"
    STEP_NAMES = ["The rules", "Review the design", "Report"]
    STEP_HINTS = ["Type in the rules of the development's architectural guidelines and of the council. Use 'Add the usual rules' to start.",
                  "Each rule is measured from the program where it can be, otherwise type the design value or tick it by hand.",
                  "A list of what passes, what fails and what is still to check."]

    def __init__(self, win):
        super().__init__(win)
        self.rules = []
        self._busy = False
        # ---- step 1: the rules
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The rules", "One line per rule. Set: which guidelines it comes from (type your own name too, for example the estate's name).")
        self.rt = QTableWidget(0, 6)
        self.rt.setHorizontalHeaderLabels(["Guidelines", "Rule", "Test", "Limit", "Unit", "Measured from"])
        self.rt.verticalHeader().setVisible(False)
        h = self.rt.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w_ in enumerate((220, 0, 130, 80, 60, 260)):
            if w_:
                self.rt.setColumnWidth(i, w_)
        self.rt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rt.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rt.setMinimumHeight(360)
        self.rt.itemChanged.connect(self._edited)
        bv.addWidget(self.rt)
        from PySide6.QtGui import QKeySequence, QShortcut
        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.rt)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self.remove_rule)
        row = QHBoxLayout()
        for text, fn, tip in (("Read rules from a PDF...", self.read_pdf_rules, "Pick the guidelines PDF (an estate's, a council's or a zoning scheme). The AI lists the rules in it; you can edit them."),
                              ("Add the usual rules", self.add_usual, "Adds a typical list for an estate's architectural guidelines and for a council."),
                              ("Add a rule", self.add_rule, ""),
                              ("Select all", self.select_all_rules, "Selects every rule. Ctrl or Shift + click picks several."),
                              ("Select one set", self.select_set, "Selects every rule of the same guidelines as the rule you clicked."),
                              ("Remove selected", self.remove_rule, "Removes every selected rule (also the Delete key).")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        v1.addWidget(bx, 1)
        # ---- step 2: the review
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Review the design")
        self.sum = QLabel("")
        self.sum.setObjectName("xaSub")
        self.sum.setWordWrap(True)
        bv.addWidget(self.sum)
        self.vt = QTableWidget(0, 6)
        self.vt.setHorizontalHeaderLabels(["Guidelines", "Rule", "Required", "In the design", "Result", "Note"])
        self.vt.verticalHeader().setVisible(False)
        self.vt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vt.itemDoubleClicked.connect(lambda _i: self.show_on_plan())
        h = self.vt.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w_ in enumerate((200, 0, 120, 150, 140, 220)):
            if w_:
                self.vt.setColumnWidth(i, w_)
        self.vt.setMinimumHeight(380)
        self.vt.itemChanged.connect(self._review_edited)
        bv.addWidget(self.vt)
        self.plans = []
        self.plan_lab = QLabel("")
        self.plan_lab.setWordWrap(True)
        self.plan_lab.setObjectName("xaSub")
        bv.addWidget(self.plan_lab)
        pr = QHBoxLayout()
        for text, fn, tip in (("Add the plans to review...", self.add_plans, "The PDF sheets you are going to submit."),
                              ("Clear the plans", self.clear_plans, ""),
                              ("Show the selected rule on the plan", self.show_on_plan, "Select a failed rule in the list: opens the plan page where it was found, with the spot marked in red. Double-click a row does the same."),
                              ("Review the plans against the rules", self.review_with_ai, "The AI reads the plans and marks each rule that the program cannot measure itself.")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            pr.addWidget(b)
        pr.addStretch(1)
        bv.addLayout(pr)
        rb = QPushButton("Measure again")
        rb.setToolTip("Reads coverage, floor area ratio, building lines, light, ventilation and glazing from the program again.")
        rb.clicked.connect(self.refresh_review)
        r2 = QHBoxLayout()
        r2.addWidget(rb)
        r2.addStretch(1)
        bv.addLayout(r2)
        v2.addWidget(bx, 1)
        # ---- step 3: report
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Report", "A one-page list of every rule and whether the design meets it.")
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
        self._plans_label()
        self.restore()
        if not self.rules:
            self.add_usual()
        else:
            self.fill_rules()

    # ---- the rules
    @staticmethod
    def _new(sname, rule, kind="max", limit=0, unit="", measure=""):
        return {"set": sname, "rule": rule, "kind": kind, "limit": limit, "unit": unit, "measure": measure, "value": "", "status": "To check", "note": "", "ai": None}

    def add_usual(self):
        have = {(r["set"], r["rule"]) for r in self.rules}
        for si, rule, kind, lim, unit, meas in USUAL:
            if (SETS[si], rule) not in have:
                self.rules.append(self._new(SETS[si], rule, kind, lim, unit, meas))
        self.fill_rules()
        self.changed()

    def add_rule(self):
        sets = [r["set"] for r in self.rules]
        self.rules.append(self._new(sets[-1] if sets else SETS[0], "New rule", "check"))
        self.fill_rules()
        self.rt.scrollToBottom()
        self.changed()

    def _sel_rows(self, t=None):
        t = t or self.rt
        rows = {i.row() for i in t.selectionModel().selectedRows()} or {i.row() for i in t.selectedIndexes()}
        return sorted(r for r in rows if 0 <= r < len(self.rules))

    def select_all_rules(self):
        self.rt.selectAll()

    def select_set(self):
        r = self.rt.currentRow()
        if not (0 <= r < len(self.rules)):
            return
        name = self.rules[r]["set"]
        self.rt.clearSelection()
        mode = self.rt.selectionMode()
        self.rt.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for i, x in enumerate(self.rules):
            if x["set"] == name:
                self.rt.selectRow(i)
        self.rt.setSelectionMode(mode)

    def remove_rule(self):
        rows = self._sel_rows()
        if not rows:
            return
        if len(rows) > 1:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, self.TITLE, "Remove %d rules?" % len(rows)) != QMessageBox.StandardButton.Yes:
                return
        for r in reversed(rows):
            del self.rules[r]
        self.fill_rules()
        self.changed()

    def fill_rules(self):
        self._busy = True
        t = self.rt
        t.blockSignals(True)
        t.setRowCount(0)
        for i, r in enumerate(self.rules):
            t.insertRow(i)
            for c, k in ((0, "set"), (1, "rule"), (3, "limit"), (4, "unit")):
                t.setItem(i, c, QTableWidgetItem(str(r[k]) if k != "limit" or r["kind"] != "check" else ""))
            kc = QComboBox()
            for k, lab in KINDS:
                kc.addItem(lab, k)
            kc.setCurrentIndex([k for k, _ in KINDS].index(r["kind"]))
            kc.currentIndexChanged.connect(lambda _i, row=i, w=kc: self._kind(row, w))
            t.setCellWidget(i, 2, kc)
            mc = QComboBox()
            for k, lab in MEASURES:
                mc.addItem(lab, k)
            mc.setCurrentIndex([k for k, _ in MEASURES].index(r["measure"]) if r["measure"] in [k for k, _ in MEASURES] else 0)
            mc.currentIndexChanged.connect(lambda _i, row=i, w=mc: self._measure(row, w))
            t.setCellWidget(i, 5, mc)
            t.setRowHeight(i, 34)
        t.blockSignals(False)
        self._busy = False
        self.refresh_review()

    def _kind(self, row, w):
        if 0 <= row < len(self.rules):
            self.rules[row]["kind"] = w.currentData()
            self.changed()
            self.refresh_review()

    def _measure(self, row, w):
        if 0 <= row < len(self.rules):
            self.rules[row]["measure"] = w.currentData()
            self.changed()
            self.refresh_review()

    def _edited(self, it):
        if self._busy:
            return
        r, c = it.row(), it.column()
        if not (0 <= r < len(self.rules)):
            return
        k = {0: "set", 1: "rule", 3: "limit", 4: "unit"}.get(c)
        if k:
            v = it.text().strip()
            self.rules[r][k] = (_f(v) if _f(v) is not None else 0) if k == "limit" else v
            self.changed()
            self.refresh_review()

    # ---- PDFs: rules in, plans reviewed
    def read_pdf_rules(self):
        import doc_review as dr
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        paths, _ = QFileDialog.getOpenFileNames(self, "Guidelines PDF", "", "PDF (*.pdf)")
        if not paths:
            return
        try:
            n = sum(min(dr.page_count(p), 12) for p in paths)
        except Exception as e:
            QMessageBox.warning(self, self.TITLE, "The PDF could not be opened: %s" % e)
            return
        mode = dr.choose_mode(self, dr.main_mod(self.win), "Read the rules from %d PDF(s)." % len(paths), n)
        if mode is None:
            return
        try:
            found = dr.run_busy(self, "Reading the guidelines...", lambda: dr.extract_rules(self.win, paths, mode == "offline"))
        except RuntimeError as e:
            QMessageBox.warning(self, self.TITLE, str(e))
            return
        have = {(r["set"], r["rule"]) for r in self.rules}
        add = 0
        for r in found:
            sname = os.path.splitext(r["file"])[0]
            if (sname, r["rule"]) in have:
                continue
            x = self._new(sname, r["rule"], r["kind"], r["limit"], r["unit"], r["measure"])
            x["note"] = r["source"]
            self.rules.append(x)
            add += 1
        self.fill_rules()
        self.changed()
        QMessageBox.information(self, self.TITLE, "%d rule(s) read. Check them and fix any limit that was read wrongly." % add)

    def add_plans(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, "Plans to review (PDF)", "", "PDF (*.pdf)")
        for p in paths:
            if p not in self.plans:
                self.plans.append(p)
        self._plans_label()
        self.changed()

    def clear_plans(self):
        self.plans = []
        self._plans_label()
        self.changed()

    def _plans_label(self):
        self.plan_lab.setText(("Plans: " + ", ".join(os.path.basename(p) for p in self.plans)) if self.plans
                              else "No plans added yet. Add the PDF sheets you will submit.")

    def review_with_ai(self):
        import doc_review as dr
        from PySide6.QtWidgets import QMessageBox
        if not self.plans:
            QMessageBox.information(self, self.TITLE, "Add the plans to review first.")
            return
        meas = self.measures()
        todo = [i for i, r in enumerate(self.rules)
                if not (r["measure"] and r["measure"] in meas) and not (r["kind"] != "check" and _f(r["value"]) is not None)]
        if not todo:
            QMessageBox.information(self, self.TITLE, "Every rule is already measured or filled in.")
            return
        miss = [p for p in self.plans if not os.path.exists(p)]
        if miss:
            QMessageBox.warning(self, self.TITLE, "Cannot find: " + ", ".join(os.path.basename(p) for p in miss))
            return
        n = dr.n_plan_pages(self.plans) * ((len(todo) + 19) // 20)
        mode = dr.choose_mode(self, dr.main_mod(self.win), "Review the plans against %d rule(s)." % len(todo), n)
        if mode is None:
            return
        sub = [self.rules[i] for i in todo]
        try:
            res = dr.run_busy(self, "Reading the plans...", lambda: dr.review_plans(self.win, sub, self.plans, mode == "offline"))
        except RuntimeError as e:
            QMessageBox.warning(self, self.TITLE, str(e))
            return
        for j, i in enumerate(todo):
            if j in res:
                self.rules[i]["ai"] = res[j]
        self.changed()
        self.refresh_review()
        bad = sum(1 for j in res.values() if j["result"] == "fail")
        QMessageBox.information(self, self.TITLE, "Done. %d rule(s) flagged as not according to the rules. The reader (AI or offline) can be wrong: read each flagged line "
                                "and the page it points to before you rely on it." % bad)

    def _plan_for(self, r):
        """(path, page number) where this rule was found in the plans, or (None, 0)."""
        a = r.get("ai") or {}
        pg = str(a.get("page") or "")
        m = re.search(r"(?:page|p\.?|sheet)\s*(\d+)", pg, re.I) or re.search(r"(\d+)\s*$", pg)
        n = int(m.group(1)) if m else 0
        path = None
        for p in self.plans:
            b = os.path.basename(p).lower()
            if b and (b in pg.lower() or os.path.splitext(b)[0] in pg.lower()):
                path = p
                break
        if path is None and self.plans and (n or len(self.plans) == 1):
            path = self.plans[0]
        return path, n

    def show_on_plan(self):
        from PySide6.QtWidgets import QMessageBox
        rows = self._sel_rows(self.vt)
        if not rows:
            QMessageBox.information(self, self.TITLE, "Click a rule in the review list first (a failed one is the most useful).")
            return
        r = self.rules[rows[0]]
        if not self.plans:
            QMessageBox.information(self, self.TITLE, "Add the plans first, then review them: the page where the rule was found can be shown.")
            return
        path, n = self._plan_for(r)
        if not path or not os.path.exists(path):
            path = self.plans[0]
        meas = self.measures()
        shown, res, _c = self.judge(r, meas)
        a = r.get("ai") or {}
        key = " ".join(x for x in (a.get("found", ""), r["rule"]) if x)
        _PlanView(self, path, n, r, shown, res, a.get("reason", ""), key).exec()

    @staticmethod
    def _ai_view(r):
        a = r.get("ai")
        if not a:
            return None
        res = {"pass": "Passes", "fail": "Fails"}.get(a.get("result"), "To check")
        note = ("From the plans: " + a.get("reason", "") + ((" [" + a["page"] + "]") if a.get("page") else "")).strip()
        return (a.get("found", ""), res, note)

    # ---- measuring
    def measures(self):
        """{key: number} for everything the program knows right now (missing when it does not know)."""
        w, m = self.win, {}
        sp = getattr(w, "site_page", None)
        try:
            if sp is not None and sp.verts() and len(sp.verts()) >= 3:
                an = sp.result()
                m["cov"] = round(an["cov_pct"], 2)
                m["far"] = round(an["far"], 3)
                m["lines"] = float(len(sp.encroachments()))
        except Exception:
            pass
        ap = getattr(w, "area_page", None)
        try:
            if ap is not None and ap.total_area() > 0:
                m["floor"] = round(ap.far_area(), 2)
        except Exception:
            pass
        res = getattr(w, "results", None) or []
        if res:
            m["light"] = float(sum(1 for r in res if r.get("light_ok") is False))
            m["vent"] = float(sum(1 for r in res if r.get("vent_ok") is False))
            m["glaze"] = float(sum(1 for r in res if r.get("glaze_ok") is False))
        return m

    def judge(self, r, meas):
        """(design value text, result, colour)"""
        lim, kind = _f(r["limit"]) or 0.0, r["kind"]
        val = meas.get(r["measure"]) if r["measure"] else _f(r["value"])
        ai = self._ai_view(r)
        if kind == "check":
            if r["status"] == "To check" and ai:
                return (ai[0], ai[1], None)
            return (r["value"] or "", r["status"], None)
        if val is None:
            if ai and not r["measure"]:
                return (ai[0], ai[1], None)
            return ("not measured yet" if r["measure"] else (r["value"] or ""), "To check", None)
        ok = val <= lim + 1e-9 if kind == "max" else val >= lim - 1e-9
        shown = ("%g" % val) + ((" " + r["unit"]) if r["unit"] else "")
        return (shown, "Passes" if ok else "Fails", None)

    def refresh_review(self, *_a):
        if getattr(self, "vt", None) is None:
            return
        meas = self.measures()
        t = self.vt
        self._busy = True
        t.blockSignals(True)
        t.setRowCount(0)
        n_ok = n_bad = n_chk = 0
        for i, r in enumerate(self.rules):
            t.insertRow(i)
            shown, res, _c = self.judge(r, meas)
            if r["status"] == "Not applicable" and r["kind"] != "check":
                res = "Not applicable"
            kind = r["kind"]
            req = "tick by hand" if kind == "check" else (("not more than " if kind == "max" else "not less than ") + ("%g" % (_f(r["limit"]) or 0)) + ((" " + r["unit"]) if r["unit"] else ""))
            ai_ = self._ai_view(r)
            cells = [r["set"], r["rule"], req, shown, res, (ai_[2] if ai_ and ai_[1] == res and not r["value"] else r["note"])]
            for c, v in enumerate(cells):
                it = QTableWidgetItem(str(v))
                if c in (0, 1, 2) or (c == 3 and r["measure"]) or c == 4:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 4:
                    col = {"Passes": "#2e9d5b", "Fails": "#d83a4b", "To check": "#c08a1c"}.get(res)
                    if col:
                        it.setForeground(QColor(col))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                t.setItem(i, c, it)
            if kind == "check" or (not r["measure"]):
                cb = QComboBox()
                cb.addItems(STATUS)
                cb.setCurrentText(r["status"])
                cb.currentTextChanged.connect(lambda txt, row=i: self._status(row, txt))
                if kind == "check":
                    t.setCellWidget(i, 4, cb)
            t.setRowHeight(i, 34)
            if res == "Passes":
                n_ok += 1
            elif res == "Fails":
                n_bad += 1
            elif res != "Not applicable":
                n_chk += 1
        t.blockSignals(False)
        self._busy = False
        self.sum.setText("%d pass, %d fail, %d still to check." % (n_ok, n_bad, n_chk))

    def _status(self, row, txt):
        if 0 <= row < len(self.rules):
            self.rules[row]["status"] = txt
            self.changed()
            self.refresh_review()

    def _review_edited(self, it):
        if self._busy:
            return
        r, c = it.row(), it.column()
        if not (0 <= r < len(self.rules)):
            return
        if c == 3:
            self.rules[r]["value"] = it.text().strip()
        elif c == 5:
            self.rules[r]["note"] = it.text().strip()
        else:
            return
        self.changed()
        self.refresh_review()

    def on_step(self, i):
        if i == 1:
            self.refresh_review()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_review()

    # ---- report and state
    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        meas = self.measures()
        rows = []
        for r in self.rules:
            shown, res, _c = self.judge(r, meas)
            kind = r["kind"]
            req = "tick by hand" if kind == "check" else (("not more than " if kind == "max" else "not less than ") + ("%g" % (_f(r["limit"]) or 0)) + ((" " + r["unit"]) if r["unit"] else ""))
            bg = {"Passes": "#e4f4ea", "Fails": "#fbe3e6", "To check": "#fdf3d8"}.get(res)
            ai_ = self._ai_view(r)
            nt = ai_[2] if ai_ and ai_[1] == res and not r["value"] else r["note"]
            rows.append(((r["set"], r["rule"], req, shown, res, nt), bg) if bg else (r["set"], r["rule"], req, shown, res, nt))
        body = tb.table(["Guidelines", "Rule", "Required", "In the design", "Result", "Note"], rows, [18, 28, 16, 14, 10, 14])
        return tb.report_doc_html("Guidelines review", "The design against the architectural and council guidelines", body, rd)

    def state(self):
        return {"rules": [dict(r) for r in self.rules], "plans": list(self.plans)}

    def set_state(self, d):
        d = d or {}
        self.plans = [p for p in (d.get("plans") or []) if isinstance(p, str)]
        if getattr(self, "plan_lab", None) is not None:
            self._plans_label()
        saved = d.get("rules")
        self.rules = [dict(self._new("", ""), **r) for r in saved] if saved else []
        if not self.rules:
            self.add_usual()
        elif getattr(self, "rt", None) is not None:
            self.fill_rules()


class _PlanView(QDialog):
    """One plan page with the place a rule was found marked in red (text matches are boxed), and the rule above it."""

    def __init__(self, parent, path, page, rule, shown, res, reason, key):
        super().__init__(parent)
        self.setWindowTitle("Rule on the plan")
        self.resize(1100, 860)
        self.path, self.key, self.zoom = path, key, 1.0
        import fitz
        with fitz.open(path) as d:
            self.n = d.page_count
        self.pg = min(max(page, 1), self.n) if page else 0
        v = QVBoxLayout(self)
        req = "tick by hand" if rule["kind"] == "check" else (("not more than " if rule["kind"] == "max" else "not less than ") +
                                                              ("%g" % (_f(rule["limit"]) or 0)) + ((" " + rule["unit"]) if rule["unit"] else ""))
        head = QLabel("<b>%s</b><br>Required: %s &nbsp; In the design: %s &nbsp; <b style='color:%s'>%s</b><br>%s" % (
            rule["rule"], req, shown or "-", "#d83a4b" if res == "Fails" else "#2e9d5b" if res == "Passes" else "#c08a1c", res,
            reason or ("Measured from the program: it is not on one plan page." if rule["measure"] else "")))
        head.setWordWrap(True)
        v.addWidget(head)
        bar = QHBoxLayout()
        self.lab = QLabel("")
        for t, f in (("< Page", lambda: self.go(-1)), ("Page >", lambda: self.go(1)), ("Zoom in", lambda: self.zm(1.25)), ("Zoom out", lambda: self.zm(0.8)),
                     ("Open the PDF", self.open_pdf), ("Save this page as a picture...", self.save_png)):
            b = QPushButton(t)
            b.clicked.connect(lambda _=False, fn=f: fn())
            bar.addWidget(b)
        bar.addWidget(self.lab, 1)
        v.addLayout(bar)
        self.sa = QScrollArea()
        self.img = QLabel()
        self.sa.setWidget(self.img)
        self.sa.setWidgetResizable(False)
        v.addWidget(self.sa, 1)
        if not self.pg:
            self.pg = self._find_page() or 1
        self.draw()

    def _words(self):
        ws = [w for w in re.findall(r"[A-Za-z0-9.%]{4,}", self.key.lower()) if w not in ("that", "with", "must", "than", "from", "shall", "rule")]
        return list(dict.fromkeys(ws))[:8]

    def _find_page(self):
        import fitz
        best, bs = 0, 0
        ws = self._words()
        with fitz.open(self.path) as d:
            for i, p in enumerate(d):
                t = (p.get_text("text") or "").lower()
                sc = sum(1 for w in ws if w in t)
                if sc > bs:
                    best, bs = i + 1, sc
        return best

    def draw(self):
        import fitz
        from PySide6.QtGui import QImage, QPixmap
        with fitz.open(self.path) as d:
            p = d[self.pg - 1]
            hits = []
            for w in self._words():
                try:
                    hits += p.search_for(w)
                except Exception:
                    pass
            for rc in hits[:40]:
                p.draw_rect(rc, color=(0.85, 0.15, 0.2), width=1.6)
            p.draw_rect(p.rect + (4, 4, -4, -4), color=(0.85, 0.15, 0.2), width=3)
            s = min(3.0, 1500 / max(p.rect.width, p.rect.height, 1.0)) * self.zoom
            pm = p.get_pixmap(matrix=fitz.Matrix(s, s), alpha=False)
            im = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888).copy()
        self.img.setPixmap(QPixmap.fromImage(im))
        self.img.resize(im.size())
        self.lab.setText("%s - page %d of %d%s" % (os.path.basename(self.path), self.pg, self.n,
                                                 ("  (%d marks)" % len(hits)) if hits else "  (nothing to mark: the rule is not written on this page)"))

    def go(self, d):
        self.pg = min(max(self.pg + d, 1), self.n)
        self.draw()

    def zm(self, f):
        self.zoom = min(4.0, max(0.3, self.zoom * f))
        self.draw()

    def open_pdf(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def save_png(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save picture", "rule_on_plan.png", "PNG (*.png)")
        if f:
            self.img.pixmap().save(f, "PNG")
