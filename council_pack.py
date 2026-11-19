"""Council submission pack: the application details, a checklist of what a building plan submission needs, and one button
that gathers everything into a numbered folder with an index sheet (and one joined PDF)."""
import os
import re
import shutil

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import tool_base as tb
from tool_base import ToolBase

STATUS = ["To do", "In progress", "Done", "Not needed"]
APP_TYPES = ["New dwelling house", "Additions and alterations", "Multi-unit residential", "Commercial or industrial",
             "Departure or consent use", "Other"]
# section, what is needed, auto key (made from the program), hint
ITEMS = [
    ("Application", "Application form (the municipality's form)", None, "Signed by the owner or the applicant."),
    ("Application", "Appointment of the competent person (architect)", None, "The SANS 10400-A appointment forms."),
    ("Application", "Proof of payment of the submission fee", None, ""),
    ("Application", "Electronic copy (PDF or DWG) if the municipality asks for it", None, ""),
    ("Ownership and land", "Title deed or proof of ownership", None, ""),
    ("Ownership and land", "Surveyor-General diagram or general plan", None, ""),
    ("Ownership and land", "Zoning certificate and conditions", None, ""),
    ("Ownership and land", "Owner's consent or power of attorney", None, "If the applicant is not the owner."),
    ("Ownership and land", "Company or trust resolution", None, "If the owner is a company or trust."),
    ("Ownership and land", "Servitude, HOA or body corporate consent", None, "If it applies."),
    ("Drawings", "Site plan with the building lines", "site", "Made from Building lines."),
    ("Drawings", "Floor plans", None, ""),
    ("Drawings", "Elevations", None, ""),
    ("Drawings", "Sections", None, ""),
    ("Drawings", "Roof plan", None, ""),
    ("Drawings", "Drainage and stormwater plan", None, ""),
    ("Drawings", "Drawing register (sheet index)", "reg", "Made from the Drawing register."),
    ("Calculations and reports", "SANS 10400-XA energy report", "xa", "Made from Energy (XA)."),
    ("Calculations and reports", "SANS 10400-O light and ventilation report", "lv", "Made from Light & Ventilation."),
    ("Calculations and reports", "Coverage and floor area ratio calculation", "cov", "Made from Coverage & FAR."),
    ("Calculations and reports", "Area schedule", "area", "Made from the Area schedule."),
    ("Calculations and reports", "Rational design report (if used)", "rd", "Made from Energy (XA)."),
    ("Engineering and other", "Structural engineer's appointment and design", None, ""),
    ("Engineering and other", "Fire report (SANS 10400-T), if it applies", None, ""),
    ("Engineering and other", "NHBRC enrolment, where it applies", None, ""),
    ("Engineering and other", "Heritage clearance, if it applies", None, ""),
    ("Engineering and other", "Departure motivation and neighbour consent", "dep", "Made from Building lines when a line is crossed."),
]
FIELDS = [("name", "Project", "taken from Project details if empty"), ("muni", "Municipality", "for example Mossel Bay Municipality"),
          ("erf", "Erf number", ""), ("address", "Site address", ""), ("owner", "Owner", ""), ("architect", "Architect (firm)", ""),
          ("competent", "Competent person", ""), ("sacap", "SACAP registration number", ""), ("engineer", "Structural engineer", ""),
          ("ref", "Municipal reference", "if the municipality gave one"), ("date", "Date", "")]


def safe(s):
    return re.sub(r'[\\/:*?"<>|]+', " ", str(s)).strip()


class CouncilPage(ToolBase):
    KEY = "council"
    TITLE = "Council submission pack"
    STEP_NAMES = ["The application", "The checklist", "Build the pack"]
    STEP_HINTS = ["Who and where. Details from Project details are filled in for you; change anything that is not right.",
                  "Set the status of each item and attach the file. Items marked 'from the program' are made for you when you build the pack.",
                  "Gathers every file into one numbered folder with an index sheet, and can join the PDFs into one."]

    def __init__(self, win):
        super().__init__(win)
        self.items = [self._new_item(s, w, a, h) for s, w, a, h in ITEMS]
        self._busy = False
        self.last_folder = ""
        # ---- step 1
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("The application")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.f = {}
        for i, (k, lab, ph) in enumerate(FIELDS):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textChanged.connect(self.changed)
            self.f[k] = e
            g.addWidget(QLabel(lab), i // 2, (i % 2) * 2)
            g.addWidget(e, i // 2, (i % 2) * 2 + 1)
        self.app_type = QComboBox()
        self.app_type.addItems(APP_TYPES)
        self.app_type.currentTextChanged.connect(self.changed)
        n = (len(FIELDS) + 1) // 2
        g.addWidget(QLabel("Kind of application"), n, 0)
        g.addWidget(self.app_type, n, 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        bv.addLayout(g)
        fb = QPushButton("Fill from the project details")
        fb.setToolTip("Copies project, site, owner, architect, competent person and registration number from Project details.")
        fb.clicked.connect(lambda: self.fill_from_project(False))
        r = QHBoxLayout()
        r.addWidget(fb)
        r.addStretch(1)
        bv.addLayout(r)
        v1.addWidget(bx)
        v1.addStretch(1)
        # ---- step 2
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("What a submission needs", "A typical list. Your municipality may ask for more or less: add, remove or mark items 'Not needed'.")
        self.prog = QLabel("")
        self.prog.setObjectName("xaSub")
        bv.addWidget(self.prog)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Section", "What is needed", "Status", "File", "Note"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w_ in enumerate((150, 0, 120, 210, 230)):
            if w_:
                self.table.setColumnWidth(i, w_)
        self.table.setMinimumHeight(380)
        self.table.cellDoubleClicked.connect(lambda r_, c_: self.attach(r_) if c_ in (1, 3) else self.edit_note(r_) if c_ == 4 else None)
        bv.addWidget(self.table)
        from flow_layout import FlowLayout
        row = QWidget()
        fl = FlowLayout(row, 6, 6)
        for text, fn, tip in (("Attach a file...", self.attach, "Pick the file for the selected item."),
                              ("Open the file", self.open_file, "Opens the attached file."),
                              ("Remove the file", self.detach, "Takes the file off the item."),
                              ("Mark as done", lambda: self.set_status("Done"), ""),
                              ("Mark as not needed", lambda: self.set_status("Not needed"), ""),
                              ("Add an item...", self.add_item, "Add something your municipality asks for."),
                              ("Remove item", self.remove_item, "Remove the selected item from the list."),
                              ("Write a note...", lambda: self.edit_note(), "A short note on the selected item.")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        row.setMinimumHeight(84)
        bv.addWidget(row)
        self.only_left = QCheckBox("Show only what is left to do")
        self.only_left.toggled.connect(self.refresh_table)
        bv.addWidget(self.only_left)
        v2.addWidget(bx, 1)
        # ---- step 3
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Is it ready?")
        self.ready = QLabel("")
        self.ready.setWordWrap(True)
        bv.addWidget(self.ready)
        v3.addWidget(bx)
        bx, bv = self.box("Build the pack", "Makes a folder with every file numbered in order and an index sheet in front.")
        self.make_auto = QCheckBox("Make the reports from the program for items that have no file")
        self.make_auto.setChecked(True)
        self.join = QCheckBox("Also join all the PDFs into one file")
        self.join.setChecked(True)
        bv.addWidget(self.make_auto)
        bv.addWidget(self.join)
        row = QWidget()
        fl = FlowLayout(row, 6, 6)
        for text, fn in (("Preview the index sheet", self.preview), ("Build the pack...", self.build), ("Open the folder", self.open_folder)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        row.setMinimumHeight(46)
        bv.addWidget(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        bv.addWidget(self.result)
        v3.addWidget(bx)
        v3.addStretch(1)
        self.build_frame([p1, p2, p3])
        self.restore()
        self.refresh_table()

    @staticmethod
    def _new_item(section, what, auto, hint):
        return {"section": section, "what": what, "auto": auto, "hint": hint, "status": "Not needed" if auto == "rd" else "To do", "file": "", "note": ""}

    # ---- application
    def fill_from_project(self, only_empty=True):
        rd = getattr(self.win, "rd", {}) or {}
        m = {"name": rd.get("project"), "address": rd.get("details"), "owner": rd.get("owner"), "architect": rd.get("architect") or rd.get("company"),
             "competent": rd.get("prepared_by"), "sacap": rd.get("reg_no")}
        for k, v in m.items():
            if v and (not only_empty or not self.f[k].text().strip()):
                self.f[k].setText(str(v))

    def showEvent(self, e):
        super().showEvent(e)
        self.fill_from_project(True)

    # ---- checklist
    def _auto_ok(self, key):
        w = self.win
        if key == "dep":
            sp = getattr(w, "site_page", None)
            return bool(sp is not None and sp.encroachments())
        attr = {"site": "site_page", "reg": "register_page", "xa": "_write_xa_pdf", "lv": "_write_report_pdf", "cov": "_write_cov_pdf",
                "area": "area_page", "rd": "_write_rd_pdf"}.get(key)
        return bool(attr) and getattr(w, attr, None) is not None

    def refresh_table(self, *_a):
        t = self.table
        t.blockSignals(True)
        t.setRowCount(0)
        left = self.only_left.isChecked()
        for idx, it in enumerate(self.items):
            if left and it["status"] in ("Done", "Not needed"):
                continue
            r = t.rowCount()
            t.insertRow(r)
            vals = [it["section"], it["what"], None, None, it["note"] or it["hint"]]
            if it["file"]:
                vals[3] = os.path.basename(it["file"])
            elif it["auto"]:
                vals[3] = "From the program" if self._auto_ok(it["auto"]) else "(nothing to make yet)"
            else:
                vals[3] = ""
            for c in (0, 1, 3, 4):
                cell = QTableWidgetItem(vals[c])
                cell.setData(Qt.ItemDataRole.UserRole, idx)
                if c == 3 and not it["file"] and it["auto"]:
                    f = cell.font()
                    f.setItalic(True)
                    cell.setFont(f)
                if c == 4 and not it["note"]:
                    cell.setForeground(QColor("#8a8f98"))
                t.setItem(r, c, cell)
            cb = QComboBox()
            cb.addItems(STATUS)
            cb.setCurrentText(it["status"])
            cb.currentTextChanged.connect(lambda txt, i=idx: self._status(i, txt))
            t.setCellWidget(r, 2, cb)
            t.setRowHeight(r, 40)
        t.blockSignals(False)
        self._summary()

    def _status(self, idx, txt):
        self.items[idx]["status"] = txt
        self._color_rows()
        self._summary()
        self.changed()
        if self.only_left.isChecked() and txt in ("Done", "Not needed"):
            self.refresh_table()

    def _color_rows(self):
        pass

    def _summary(self):
        need = [i for i in self.items if i["status"] != "Not needed"]
        done = [i for i in need if i["status"] == "Done"]
        self.prog.setText("%d of %d items done." % (len(done), len(need)))
        left = [i for i in need if i["status"] != "Done"]
        if not need:
            self.ready.setText("The list is empty.")
        elif not left:
            self.ready.setText("<span style='color:#2e9e5b; font-size:15px'><b>Everything is marked done.</b></span>")
        else:
            nofile = [i for i in left if i["file"] == "" and not i["auto"]]
            self.ready.setText("<span style='font-size:15px'><b>%d of %d items done.</b></span><br>Still to do:<br>%s" %
                               (len(done), len(need), "<br>".join("&nbsp;&nbsp;- " + tb.esc(i["what"]) + (" (no file yet)" if i in nofile else "") for i in left[:14])
                               + ("<br>&nbsp;&nbsp;... and %d more" % (len(left) - 14) if len(left) > 14 else "")))

    def _sel_idx(self):
        r = self.table.currentRow()
        if r < 0 or not self.table.item(r, 1):
            QMessageBox.information(self, "Council pack", "Click an item in the list first.")
            return None
        return self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)

    def attach(self, row=None):
        if isinstance(row, int) and row >= 0:
            self.table.setCurrentCell(row, 1)
        i = self._sel_idx()
        if i is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Attach a file to: " + self.items[i]["what"], "", "All files (*)")
        if path:
            self.items[i]["file"] = path
            if self.items[i]["status"] == "To do":
                self.items[i]["status"] = "In progress"
            self.refresh_table()
            self.changed()

    def detach(self):
        i = self._sel_idx()
        if i is not None:
            self.items[i]["file"] = ""
            self.refresh_table()
            self.changed()

    def open_file(self):
        i = self._sel_idx()
        if i is not None and self.items[i]["file"]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.items[i]["file"]))

    def set_status(self, s):
        i = self._sel_idx()
        if i is not None:
            self.items[i]["status"] = s
            self.refresh_table()
            self.changed()

    def edit_note(self, row=None):
        if isinstance(row, int) and row >= 0:
            self.table.setCurrentCell(row, 4)
        i = self._sel_idx()
        if i is None:
            return
        from PySide6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(self, "Note", self.items[i]["what"], text=self.items[i]["note"])
        if ok:
            self.items[i]["note"] = txt.strip()
            self.refresh_table()
            self.changed()

    def add_item(self):
        from PySide6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(self, "Add an item", "What does the municipality also ask for?")
        if ok and txt.strip():
            self.items.append(self._new_item("Other", txt.strip(), None, ""))
            self.refresh_table()
            self.changed()

    def remove_item(self):
        i = self._sel_idx()
        if i is not None and QMessageBox.question(self, "Council pack", "Remove this item from the list?\n\n" + self.items[i]["what"]) == QMessageBox.StandardButton.Yes:
            del self.items[i]
            self.refresh_table()
            self.changed()

    # ---- making the pack
    def _make_auto(self, key, path):
        w = self.win
        if key == "xa":
            w._run_xa()
            w._write_xa_pdf(path)
        elif key == "lv":
            w.run_check(goto=False)
            w._write_report_pdf(path)
        elif key == "cov":
            w._write_cov_pdf(path)
        elif key == "rd":
            w._write_rd_pdf(path)
        elif key == "area":
            w.area_page.write_report(path)
        elif key == "site":
            w.site_page.write_report(path)
        elif key == "dep":
            w.site_page.write_motivation_pdf(path)
        elif key == "reg":
            w.register_page.write_pdf(path)
        else:
            raise RuntimeError("nothing to make")

    def pack_name(self):
        return safe(self.f["name"].text() or (getattr(self.win, "rd", {}) or {}).get("project") or "Project")

    def build(self):
        base = QFileDialog.getExistingDirectory(self, "Where should the pack folder go?", self.last_folder or os.path.expanduser("~/Documents"))
        if not base:
            return
        folder = os.path.join(base, self.pack_name() + " - council pack")
        os.makedirs(folder, exist_ok=True)
        files, made, failed, missing = [], [], [], []
        n = 0
        for it in self.items:
            if it["status"] == "Not needed":
                continue
            src, ext = it["file"], ""
            if src and os.path.exists(src):
                ext = os.path.splitext(src)[1]
            elif it["auto"] and self.make_auto.isChecked() and self._auto_ok(it["auto"]):
                src = None
            else:
                missing.append(it["what"])
                continue
            n += 1
            name = "%02d %s%s" % (n, safe(it["what"])[:70], ext or ".pdf")
            dst = os.path.join(folder, name)
            try:
                if src:
                    shutil.copy2(src, dst)
                else:
                    self._make_auto(it["auto"], dst)
                    made.append(it["what"])
                    it["_made"] = dst
                files.append((it, dst))
            except Exception as e:
                failed.append("%s (%s)" % (it["what"], e))
                n -= 1
        idx_path = os.path.join(folder, "00 Index.pdf")
        self._index_files = {id(it): os.path.basename(p) for it, p in files}
        try:
            self.write_report(idx_path)
        except Exception as e:
            failed.append("Index sheet (%s)" % e)
        joined = ""
        if self.join.isChecked():
            joined = self._join(folder, idx_path, files)
        self.last_folder = base
        self._folder = folder
        msg = "<b>%d files</b> in the folder%s." % (len(files), (", joined into <b>%s</b>" % tb.esc(os.path.basename(joined))) if joined else "")
        if made:
            msg += "<br>Made from the program: " + tb.esc(", ".join(made)) + "."
        if missing:
            msg += "<br><span style='color:#d9a21b'>Not in the pack yet:</span> " + tb.esc("; ".join(missing)) + "."
        if failed:
            msg += "<br><span style='color:#e0243a'>Could not make:</span> " + tb.esc("; ".join(failed)) + "."
        self.result.setText(msg)
        self.changed()
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            pass

    def _join(self, folder, idx_path, files):
        try:
            import fitz
        except Exception:
            return ""
        try:
            out = fitz.open()
            toc = []
            for label, p in [("Index", idx_path)] + [(it["what"], p) for it, p in files]:
                if not p.lower().endswith(".pdf") or not os.path.exists(p):
                    continue
                with fitz.open(p) as d:
                    toc.append([1, label, len(out) + 1])
                    out.insert_pdf(d)
            if len(out):
                out.set_toc(toc)
                path = os.path.join(folder, self.pack_name() + " - complete pack.pdf")
                out.save(path)
                return path
        except Exception:
            return ""
        return ""

    def open_folder(self):
        f = getattr(self, "_folder", "") or self.last_folder
        if f and os.path.isdir(f):
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))
        else:
            QMessageBox.information(self, "Council pack", "Build the pack first.")

    # ---- the index sheet
    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        F = lambda k: self.f[k].text().strip()
        info = [("Project", F("name")), ("Municipality", F("muni")), ("Erf", F("erf")), ("Site", F("address")), ("Kind of application", self.app_type.currentText()),
                ("Owner", F("owner")), ("Architect", F("architect")), ("Competent person", F("competent") + ((" (SACAP " + F("sacap") + ")") if F("sacap") else "")),
                ("Structural engineer", F("engineer")), ("Municipal reference", F("ref")), ("Date", F("date"))]
        body = '<table width="100%" cellspacing="0" cellpadding="3">' + "".join(
            '<tr><td width="28%%" style="color:#666666;">%s</td><td><b>%s</b></td></tr>' % (tb.esc(k), tb.esc(v)) for k, v in info if v) + "</table>"
        names = getattr(self, "_index_files", {})
        rows, sec, no = [], "", 0
        for it in self.items:
            if it["status"] == "Not needed":
                continue
            fn = names.get(id(it)) or (os.path.basename(it["file"]) if it["file"] else "")
            color = "#e4f4ea" if it["status"] == "Done" else "#fff4d6" if it["status"] == "In progress" else "#fde3e6"
            if fn:
                no += 1
            rows.append(([it["section"] if it["section"] != sec else "", it["what"], it["status"], fn or "not in the pack"], color))
            sec = it["section"]
        body += "<h3>Contents</h3>" + tb.table(["Section", "Item", "Status", "File"], rows, [20, 40, 12, 28])
        return tb.report_doc_html("Building plan submission", self.pack_name() + " | Index of documents", body, rd)

    # ---- state
    def state(self):
        d = {k: e.text() for k, e in self.f.items()}
        return {"fields": d, "app_type": self.app_type.currentText(), "only_left": self.only_left.isChecked(), "last_folder": self.last_folder,
                "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in self.items]}

    def set_state(self, d):
        d = d or {}
        for k, e in self.f.items():
            e.setText((d.get("fields") or {}).get(k, ""))
        self.app_type.setCurrentText(d.get("app_type") or APP_TYPES[0])
        self.last_folder = d.get("last_folder", "")
        saved = d.get("items")
        if saved:
            self.items = [dict(self._new_item("Other", "", None, ""), **it) for it in saved]
        else:
            self.items = [self._new_item(s, w, a, h) for s, w, a, h in ITEMS]
        self.refresh_table()
