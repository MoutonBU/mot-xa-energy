"""Drawing register: feed in PDFs per block or house, get a register (PDF / CSV) and the text of the issue email."""
import datetime
import html as _html
import os
import re

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STATUSES = ["For information", "For comment", "For approval", "For council submission", "For tender", "For construction", "As built", "Superseded"]
COLS = ["Issue", "Drawing no.", "Title", "What it shows", "Size", "Sheets", "Scale", "Rev", "Date", "Status", "File"]
# (pattern in the title or the drawing text, what the drawing is about)
ABOUT = [
    (r"site\s*plan|site\s*development", "Stand layout: building positions, boundaries, building lines, coverage and access."),
    (r"locality|location", "Where the site is, in relation to its surroundings."),
    (r"ground\s*floor|first\s*floor|second\s*floor|floor\s*plan|\bplan\b", "Floor plan: walls, rooms, openings, dimensions and room names."),
    (r"elevation", "Elevations: the outside faces of the building, heights and finishes."),
    (r"section", "Sections: the building cut through, to show levels, heights and construction."),
    (r"roof", "Roof plan: roof shape, falls, drainage and roof covering."),
    (r"foundation|footing", "Foundation layout: footings, sizes and levels."),
    (r"drainage|sewer|plumbing", "Drainage and plumbing layout: pipes, fall, manholes and fixtures."),
    (r"electr|lighting", "Electrical layout: lights, plugs, switches and the distribution board."),
    (r"door|window|schedule", "Schedule of doors and windows: sizes, types and positions."),
    (r"detail", "Construction details: how the parts of the building are built up."),
    (r"energy|sans\s*10400[-\s]*xa|xa\b", "Energy efficiency (SANS 10400-XA) information for the council."),
    (r"light|ventilat", "Natural light and ventilation (SANS 10400-O) for the council."),
    (r"kitchen|bath|cupboard|joinery", "Interior fittings: kitchen, bathroom and cupboard layouts."),
    (r"3d|render|view|perspective", "3D views of the design."),
    (r"cover|title|index", "Cover sheet and drawing index."),
]
SIZES = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297)}


def paper_size(w_pt, h_pt):
    a, b = sorted((w_pt * 25.4 / 72.0, h_pt * 25.4 / 72.0))
    for n, (sw, sh) in SIZES.items():
        if abs(a - sw) < 12 and abs(b - sh) < 15:
            return n
    return "%d x %d mm" % (round(a), round(b))


def read_pdf(path):
    """What can be read from a drawing PDF: sheets, paper size, scale, revision, a first line of text."""
    out = {"pages": 1, "size": "", "scale": "", "rev": "", "text": ""}
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        d = fitz.open(path)
        out["pages"] = len(d)
        if len(d):
            r = d[0].rect
            out["size"] = paper_size(r.width, r.height)
            t = d[0].get_text("text") or ""
            out["text"] = t[:4000]
            m = re.search(r"(?:scale|skaal)?\s*[:@]?\s*(1\s*:\s*\d{1,4})", t, re.I)
            if m:
                out["scale"] = re.sub(r"\s+", "", m.group(1))
            m = re.search(r"\brev(?:ision)?\.?\s*[:\-]?\s*([A-Z]\d?|\d{1,2})\b", t, re.I)
            if m:
                out["rev"] = m.group(1).upper()
        d.close()
    except Exception:
        pass
    return out


def guess_row(path):
    base = os.path.splitext(os.path.basename(path))[0]
    info = read_pdf(path)
    no, title = "", base.replace("_", " ").strip()
    m = re.match(r"^\s*([A-Za-z]{0,3}[-_ ]?\d{1,4}[A-Za-z]?)\s*[-_ .]+\s*(.+)$", base)
    if m:
        no, title = m.group(1).replace("_", "-").replace(" ", "-").upper(), m.group(2).replace("_", " ").strip()
    rev = info["rev"]
    mr = re.search(r"[\s_\-]rev\.?\s*([A-Z]\d?|\d{1,2})\s*$", title, re.I)
    if mr:
        rev = mr.group(1).upper()
        title = title[:mr.start()].strip(" -_")
    about = ""
    hay = title + " " + info["text"][:600]
    for pat, txt in ABOUT:
        if re.search(pat, title, re.I) or (not about and re.search(pat, hay, re.I)):
            about = txt
            if re.search(pat, title, re.I):
                break
    try:
        date = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except OSError:
        date = datetime.date.today().isoformat()
    return {"on": True, "no": no, "title": title, "about": about, "size": info["size"], "pages": info["pages"], "scale": info["scale"],
            "rev": rev, "date": date, "status": "For information", "file": os.path.basename(path), "path": path}


class RegisterPage(QWidget):
    is_costing = True
    report_title = "Drawing Register"

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.groups = []     # {name, rows:[...]}
        self.info = {"project": "", "client": "", "issued_by": "", "to": "", "email": "", "note": "", "issue_no": "1", "date": ""}
        self.cur = 0
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        form = QFormLayout()
        self.f = {}
        top = QHBoxLayout()
        for key, label, ph in (("project", "Project", "taken from Project details if empty"), ("client", "Client", ""), ("issued_by", "Issued by", "MCP Architecture & Interiors")):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            top.addWidget(QLabel(label))
            top.addWidget(e, 1)
        form.addRow(top)
        r2 = QHBoxLayout()
        for key, label, ph, w in (("to", "Send to", "name", 0), ("email", "Email", "address", 0), ("issue_no", "Issue no.", "", 70), ("date", "Date", "empty = today", 110)):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            if w:
                e.setMaximumWidth(w)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            r2.addWidget(QLabel(label))
            r2.addWidget(e, 1 if not w else 0)
        form.addRow(r2)
        v.addLayout(form)
        gl = QHBoxLayout()
        gl.addWidget(QLabel("Block / house:"))
        self.gbox = QComboBox()
        self.gbox.setMinimumWidth(220)
        self.gbox.currentIndexChanged.connect(self._group_changed)
        gl.addWidget(self.gbox)
        for text, fn in (("New group", self.add_group), ("Rename", self.rename_group), ("Delete group", self.del_group), ("Add PDFs...", self.add_pdfs),
                         ("Add a folder...", self.add_folder), ("Remove drawing", self.remove_row), ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            gl.addWidget(b)
        gl.addStretch(1)
        v.addLayout(gl)
        self.tab = QTableWidget(0, len(COLS))
        self.tab.setHorizontalHeaderLabels(COLS)
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((48, 90, 220, 360, 70, 55, 70, 45, 90, 150, 200)):
            self.tab.setColumnWidth(i, w)
        self.tab.itemChanged.connect(self._cell)
        v.addWidget(self.tab, 3)
        v.addWidget(QLabel("Email to send with the register (edit it freely; it is rebuilt from the list when you press Write email):"))
        self.mail = QPlainTextEdit()
        self.mail.setMaximumHeight(170)
        v.addWidget(self.mail, 1)
        bar = QHBoxLayout()
        for text, fn in (("Write email", self.write_mail), ("Copy email", self.copy_mail), ("Open in email program", self.open_mail),
                         ("Preview PDF", self.preview_pdf), ("Export PDF", self.export_pdf), ("Export CSV", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.count = QLabel("")
        bar.addWidget(self.count)
        v.addLayout(bar)
        note = QLabel("Size, scale, revision and what the drawing shows are read from the PDF and its file name (for example \"A-101 Ground floor plan Rev B.pdf\"). "
                      "Check them: every cell can be edited. The tick in the first column decides whether a drawing is in this issue.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        v.addWidget(note)
        self.add_group("House / Block 1", quiet=True)
        self.refresh()

    # ----- state -----
    def state(self):
        return {"groups": self.groups, "info": self.info, "cur": self.cur, "mail": self.mail.toPlainText()}

    def set_state(self, d):
        d = d or {}
        self.groups = [dict(name=g.get("name", "Group"), rows=[dict(r) for r in g.get("rows", [])]) for g in d.get("groups", []) if isinstance(g, dict)]
        if not self.groups:
            self.groups = [{"name": "House / Block 1", "rows": []}]
        self.info.update({k: str(v) for k, v in (d.get("info") or {}).items() if k in self.info})
        self.cur = min(int(d.get("cur", 0) or 0), len(self.groups) - 1)
        self.mail.setPlainText(d.get("mail", "") or "")
        self.refresh()

    def project_name(self):
        return self.info["project"].strip() or (getattr(self.host, "rd", {}) or {}).get("project", "").strip() or "Project"

    def _info_edited(self, *_a):
        for k, e in self.f.items():
            self.info[k] = e.text()

    # ----- groups and rows -----
    def rows(self):
        return self.groups[self.cur]["rows"] if self.groups else []

    def add_group(self, name=None, quiet=False):
        if not isinstance(name, str):
            name, ok = QInputDialog.getText(self, "Drawing register", "Name of the block or house:")
            if not ok or not name.strip():
                return
        self.groups.append({"name": name.strip(), "rows": []})
        self.cur = len(self.groups) - 1
        if not quiet:
            self.refresh()

    def rename_group(self):
        name, ok = QInputDialog.getText(self, "Drawing register", "New name:", text=self.groups[self.cur]["name"])
        if ok and name.strip():
            self.groups[self.cur]["name"] = name.strip()
            self.refresh()

    def del_group(self):
        if len(self.groups) > 1 and QMessageBox.question(self, "Drawing register", "Delete this group and its list of drawings?") == QMessageBox.StandardButton.Yes:
            self.groups.pop(self.cur)
            self.cur = max(0, self.cur - 1)
            self.refresh()

    def _group_changed(self, i):
        if not self._busy and 0 <= i < len(self.groups):
            self.cur = i
            self.refresh()

    def add_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Drawings (PDF)", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder with the drawing PDFs")
        if d:
            self.add_paths([os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".pdf")])

    def add_paths(self, paths):
        have = {r.get("path") for g in self.groups for r in g["rows"]}
        n = 0
        for p in sorted(paths, key=lambda x: os.path.basename(x).lower()):
            if p in have or not p.lower().endswith(".pdf"):
                continue
            self.rows().append(guess_row(p))
            n += 1
        self.rows().sort(key=lambda r: (r.get("no") or "~", r.get("title", "").lower()))
        self.refresh()
        return n

    def remove_row(self):
        r = self.tab.currentRow()
        if 0 <= r < len(self.rows()):
            self.rows().pop(r)
            self.refresh()

    def move(self, d):
        r, rows = self.tab.currentRow(), self.rows()
        if 0 <= r < len(rows) and 0 <= r + d < len(rows):
            rows[r], rows[r + d] = rows[r + d], rows[r]
            self.refresh()
            self.tab.selectRow(r + d)

    def _cell(self, it):
        if self._busy or not (0 <= it.row() < len(self.rows())):
            return
        row = self.rows()[it.row()]
        c = it.column()
        if c == 0:
            row["on"] = it.checkState() == Qt.CheckState.Checked
        else:
            k = ("on", "no", "title", "about", "size", "pages", "scale", "rev", "date", "status", "file")[c]
            if k == "pages":
                try:
                    row[k] = int(it.text())
                except ValueError:
                    return
            else:
                row[k] = it.text().strip()
        QTimer.singleShot(0, self._counts)

    def _counts(self):
        n = sum(1 for g in self.groups for r in g["rows"] if r.get("on"))
        self.count.setText("%d drawings in this issue, %d in all" % (n, sum(len(g["rows"]) for g in self.groups)))

    def refresh(self):
        self._busy = True
        try:
            for k, e in self.f.items():
                e.setText(self.info.get(k, ""))
            self.gbox.clear()
            self.gbox.addItems([g["name"] for g in self.groups])
            self.gbox.setCurrentIndex(self.cur)
            rows = self.rows()
            self.tab.setRowCount(0)
            self.tab.setRowCount(len(rows))
            for i, r in enumerate(rows):
                for c, k in enumerate(("on", "no", "title", "about", "size", "pages", "scale", "rev", "date", "status", "file")):
                    if c == 0:
                        it = QTableWidgetItem("")
                        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        it.setCheckState(Qt.CheckState.Checked if r.get("on", True) else Qt.CheckState.Unchecked)
                    else:
                        it = QTableWidgetItem(str(r.get(k, "")))
                        if k == "file":
                            it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                            it.setToolTip(r.get("path", ""))
                    self.tab.setItem(i, c, it)
                cb = QComboBox()
                cb.addItems(STATUSES)
                cb.setEditable(True)
                cb.setCurrentText(r.get("status", "For information"))
                cb.currentTextChanged.connect(lambda t, row=r: row.__setitem__("status", t))
                self.tab.setCellWidget(i, 9, cb)
            self.tab.resizeRowsToContents()
            self._counts()
        finally:
            self._busy = False

    # ----- output -----
    def issue_date(self):
        return self.info["date"].strip() or datetime.date.today().strftime("%d %B %Y")

    def groups_in_issue(self):
        out = []
        for g in self.groups:
            rows = [r for r in g["rows"] if r.get("on", True)]
            if rows:
                out.append((g["name"], rows))
        return out

    def write_mail(self):
        gi = self.groups_in_issue()
        to = self.info["to"].strip()
        lines = ["Subject: %s - drawing register, issue %s (%s)" % (self.project_name(), self.info["issue_no"] or "1", self.issue_date()), "",
                 "Hi %s," % (to.split()[0] if to else "there"), "",
                 "Please find the drawings for %s issued today, %s. The drawing register is attached; in short:" % (self.project_name(), self.issue_date()), ""]
        for name, rows in gi:
            lines.append(name.upper() + (" (%d drawings)" % len(rows)))
            for r in rows:
                bit = "  - %s  %s  Rev %s  (%s%s)" % (r.get("no") or "-", r.get("title", ""), r.get("rev") or "-", r.get("size", ""), ", " + r["scale"] if r.get("scale") else "")
                bit += ": " + r["about"] if r.get("about") else ""
                lines.append(bit.replace("  -  ", "  - "))
            lines.append("")
        statuses = sorted({r.get("status", "") for _n, rows in gi for r in rows})
        if statuses:
            lines += ["Status of this issue: " + ", ".join(statuses) + ".", ""]
        if self.info["note"].strip():
            lines += [self.info["note"].strip(), ""]
        lines += ["Please let me know if anything is missing or if you have comments.", "", "Regards,", self.info["issued_by"].strip() or "MCP Architecture & Interiors"]
        self.mail.setPlainText("\n".join(lines))

    def _mail_parts(self):
        if not self.mail.toPlainText().strip():
            self.write_mail()
        t = self.mail.toPlainText()
        subj = ""
        if t.startswith("Subject:"):
            first, _, rest = t.partition("\n")
            subj, t = first[8:].strip(), rest.lstrip("\n")
        return subj, t

    def copy_mail(self):
        subj, body = self._mail_parts()
        QGuiApplication.clipboard().setText((("Subject: " + subj + "\n\n") if subj else "") + body)
        self.count.setText("Email text copied")

    def open_mail(self):
        from urllib.parse import quote
        subj, body = self._mail_parts()
        QDesktopServices.openUrl(QUrl("mailto:%s?subject=%s&body=%s" % (self.info["email"].strip(), quote(subj), quote(body))))

    def report_html(self):
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        th = lambda t, w: '<th bgcolor="%s" align="left" width="%s%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left": '<td style="padding:3px;text-align:%s;">%s</td>' % (a, t)
        gi = self.groups_in_issue()
        n = sum(len(r) for _g, r in gi)
        out = ['<h1 style="color:%s;margin-bottom:2px;">Drawing register</h1>' % RED,
               '<table width="100%%" border="0" cellspacing="0" cellpadding="3" style="font-size:9.5pt;">'
               '<tr><td width="50%%"><b>Project:</b> %s</td><td><b>Issue no.:</b> %s</td></tr>'
               '<tr><td><b>Client:</b> %s</td><td><b>Date:</b> %s</td></tr>'
               '<tr><td><b>Issued by:</b> %s</td><td><b>Issued to:</b> %s</td></tr></table>' %
               (e(self.project_name()), e(self.info["issue_no"] or "1"), e(self.info["client"]), e(self.issue_date()),
                e(self.info["issued_by"] or "MCP Architecture & Interiors"), e(self.info["to"])),
               '<p style="font-size:9pt;color:#444;">%d drawings in this issue.</p>' % n]
        for name, rows in gi:
            body = ""
            for i, r in enumerate(rows):
                bg = ' bgcolor="#F6F6F6"' if i % 2 else ""
                cells = (td(e(r.get("no", ""))), td("<b>%s</b>" % e(r.get("title", ""))), td(e(r.get("about", ""))), td(e(r.get("size", "")), "center"),
                         td(e(r.get("scale", "")), "center"), td(e(r.get("rev", "")), "center"), td(e(r.get("date", "")), "center"), td(e(r.get("status", ""))))
                body += "<tr%s>%s</tr>" % (bg, "".join(cells))
            out.append('<h3 style="color:%s;margin-bottom:3px;">%s</h3>' % (RED, e(name)))
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' %
                       ("".join((th("No.", 7), th("Drawing", 22), th("What it shows", 33), th("Size", 5), th("Scale", 6), th("Rev", 4), th("Date", 9), th("Status", 14))), body))
        out.append('<p style="font-size:7.5pt;color:#666;">Only the drawings of this issue are listed. Use the latest revision of every drawing; earlier revisions are superseded.</p>')
        return "".join(out)

    def write_pdf(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        w.setTitle("Drawing register")
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.report_html() + "</body></html>")
        d.print_(w)

    def preview_pdf(self):
        try:
            self.host.preview_pdf_report(self.write_pdf, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, "Drawing register", "The preview could not be shown (%s). Use Export PDF." % e)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export drawing register", "Drawing register.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.write_pdf(path)
            QMessageBox.information(self, "Drawing register", "PDF saved:\n" + path)

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export drawing register", "Drawing register.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Group", "Drawing no.", "Title", "What it shows", "Size", "Sheets", "Scale", "Rev", "Date", "Status", "File"])
            for name, rows in self.groups_in_issue():
                for r in rows:
                    w.writerow([name] + [r.get(k, "") for k in ("no", "title", "about", "size", "pages", "scale", "rev", "date", "status", "file")])
