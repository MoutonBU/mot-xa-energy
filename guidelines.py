"""Guidelines review: check the design against the rules of the architectural development (estate guidelines) and the council's
guidelines. Rules are typed in once as sets. Where the program already knows the number (coverage, floor area ratio, building
lines, light, ventilation, glazing, floor area) it is measured for you; the rest you tick by hand or type the design value."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
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
        self.rt.setMinimumHeight(360)
        self.rt.itemChanged.connect(self._edited)
        bv.addWidget(self.rt)
        row = QHBoxLayout()
        for text, fn, tip in (("Read rules from a PDF...", self.read_pdf_rules, "Pick the guidelines PDF (an estate's, a council's or a zoning scheme). The AI lists the rules in it; you can edit them."),
                              ("Add the usual rules", self.add_usual, "Adds a typical list for an estate's architectural guidelines and for a council."),
                              ("Add a rule", self.add_rule, ""), ("Remove the rule", self.remove_rule, "Removes the selected rule.")):
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

    def remove_rule(self):
        r = self.rt.currentRow()
        if 0 <= r < len(self.rules):
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
        if not dr.confirm_send(self, dr.main_mod(self.win), "Read the rules from %d PDF(s)." % len(paths), n):
            return
        try:
            found = dr.run_busy(self, "Reading the guidelines...", lambda: dr.extract_rules(self.win, paths))
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
        if not dr.confirm_send(self, dr.main_mod(self.win), "Review the plans against %d rule(s)." % len(todo), n):
            return
        sub = [self.rules[i] for i in todo]
        try:
            res = dr.run_busy(self, "Reading the plans...", lambda: dr.review_plans(self.win, sub, self.plans))
        except RuntimeError as e:
            QMessageBox.warning(self, self.TITLE, str(e))
            return
        for j, i in enumerate(todo):
            if j in res:
                self.rules[i]["ai"] = res[j]
        self.changed()
        self.refresh_review()
        bad = sum(1 for j in res.values() if j["result"] == "fail")
        QMessageBox.information(self, self.TITLE, "Done. %d rule(s) flagged as not according to the rules. The AI can be wrong: read each flagged line "
                                "and the page it points to before you rely on it." % bad)

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
