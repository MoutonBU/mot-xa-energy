"""Drawing register: feed in PDFs per block or house, get a register (PDF / CSV) and the text of the issue email."""
import datetime
import html as _html
import os
import re
import sys

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QMenu, QTabWidget, QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STATUSES = ["For information", "For comment", "For approval", "For council submission", "For tender", "For construction", "As built", "Superseded"]
KEYS = ("on", "no", "title", "about", "size", "scale", "rev", "rdate", "pdfdate", "by", "comment", "status", "file")
COLS = ["Send", "Drawing no.", "Drawing", "What it shows", "Size", "Scale", "Rev", "Rev date", "PDF'd", "Requested by", "What changed", "Status", "File"]
BYS = ["", "Client request", "Council request", "Engineer", "Architect (own change)", "Site / contractor"]
DATE_RE = r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4})"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def norm_date(t):
    """Any of 2026-11-17, 17/11/2026, 17.11.26, 17 Nov 2026 -> 2026-11-17 (empty if it is not a date)."""
    t = (t or "").strip()
    try:
        m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", t)
        if m:
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
        else:
            m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", t)
            if m:
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
                y += 2000 if y < 100 else 0
            else:
                m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{2,4})$", t)
                if not m or m[2].lower() not in MONTHS:
                    return ""
                d, mo, y = int(m[1]), MONTHS[m[2].lower()], int(m[3])
                y += 2000 if y < 100 else 0
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _lines_from_page(page, clip):
    """Text lines of a region, top to bottom (selectable text first, OCR when the title block is drawn as lines)."""
    words = page.get_text("words", clip=clip) or []
    rows = {}
    for x0, y0, x1, y1, w, *_r in words:
        rows.setdefault(round((y0 + y1) / 2 / 4), []).append((x0, w))
    lines = [" ".join(w for _x, w in sorted(v)) for _k, v in sorted(rows.items())]
    if sum(len(l) for l in lines) >= 25:
        return lines
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        pix = page.get_pixmap(clip=clip, dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        res, _ = RapidOCR()(img)
        rows = {}
        for box, txt, _sc in (res or []):
            yc = (box[0][1] + box[2][1]) / 2
            rows.setdefault(round(yc / 18), []).append((box[0][0], txt))
        return [" ".join(w for _x, w in sorted(v)) for _k, v in sorted(rows.items())]
    except Exception:
        return lines


def parse_titleblock(lines):
    """Drawing number, current revision with its date and description, and every revision row, from title-block text lines."""
    out = {"no": "", "title": "", "revs": [], "rev": "", "rdate": "", "rdesc": ""}
    for i, l in enumerate(lines):
        m = re.search(r"(?:drawing|dwg|sheet)\s*(?:no|nr|number|nommer)\.?\s*[:\-]?\s*([A-Za-z]{0,4}[-_. ]?\d{1,4}[A-Za-z]?(?:[-_.]\d{1,3})?)", l, re.I)
        if not m and re.search(r"(?:drawing|dwg|sheet)\s*(?:no|nr|number)\.?\s*[:\-]?\s*$", l, re.I) and i + 1 < len(lines):
            m = re.match(r"\s*([A-Za-z]{0,4}[-_. ]?\d{1,4}[A-Za-z]?)\b", lines[i + 1])
        if m:
            out["no"] = re.sub(r"[\s_.]+", "-", m.group(1).strip()).upper()
            break
    for l in lines:
        m = re.search(r"(?:drawing\s*title|dwg\s*title|title|tekening\s*titel)\s*[:\-]\s*(.{3,80})$", l, re.I)
        if m:
            out["title"] = m.group(1).strip()
            break
    for l in lines:
        m = re.match(r"^\s*(?:rev\.?\s*)?([A-Z]\d?|\d{1,2})\s+" + DATE_RE + r"\s*(.*)$", l, re.I)
        if m and norm_date(m.group(2)):
            out["revs"].append((m.group(1).upper(), norm_date(m.group(2)), m.group(3).strip(" -:")))
            continue
        m = re.match(r"^\s*" + DATE_RE + r"\s+(?:rev\.?\s*)?([A-Z]\d?|\d{1,2})\b\s*(.*)$", l, re.I)
        if m and norm_date(m.group(1)):
            out["revs"].append((m.group(2).upper(), norm_date(m.group(1)), m.group(3).strip(" -:")))
    if not out["revs"]:
        # the revision letter is sometimes lost (drawn text read by OCR): number the dated rows A, B, C ... in the order they appear
        rows = []
        for l in lines:
            m = re.match(r"^\s*" + DATE_RE + r"\s+(\S.*)$", l)
            if m and norm_date(m.group(1)):
                rows.append((norm_date(m.group(1)), m.group(2).strip(" -:")))
        out["revs"] = [(chr(65 + i), dt, ds) for i, (dt, ds) in enumerate(rows[:26])]
    if not out["revs"]:
        for l in lines:
            m = re.search(r"\brev(?:ision)?\.?\s*[:\-]?\s*([A-Z]\d?|\d{1,2})\b", l, re.I)
            if m:
                out["rev"] = m.group(1).upper()
                d = re.search(DATE_RE, l)
                out["rdate"] = norm_date(d.group(1)) if d else ""
                break
    else:
        key = lambda r: (r[1], r[0])
        cur = max(out["revs"], key=key)
        out["rev"], out["rdate"], out["rdesc"] = cur
    return out


def pdf_date(meta):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", (meta or {}).get("creationDate") or (meta or {}).get("modDate") or "")
    return "%s-%s-%s" % m.groups() if m else ""


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
    """What can be read from a drawing PDF: sheets, paper size, scale, and the title block at the bottom right
    (drawing number, revisions with date and description), plus the date the PDF was made."""
    out = {"pages": 1, "size": "", "scale": "", "rev": "", "rdate": "", "rdesc": "", "no": "", "title": "", "revs": [], "pdfdate": "", "text": ""}
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        d = fitz.open(path)
        out["pages"] = len(d)
        out["pdfdate"] = pdf_date(d.metadata)
        if len(d):
            pg = d[0]
            r = pg.rect
            out["size"] = paper_size(r.width, r.height)
            t = pg.get_text("text") or ""
            out["text"] = t[:4000]
            m = re.search(r"(?:scale|skaal)?\s*[:@]?\s*(1\s*:\s*\d{1,4})", t, re.I)
            if m:
                out["scale"] = re.sub(r"\s+", "", m.group(1))
            tb = None
            for fx, fy in ((0.55, 0.62), (0.35, 0.40), (0.0, 0.0)):
                clip = fitz.Rect(r.x0 + r.width * fx, r.y0 + r.height * fy, r.x1, r.y1)
                cand = parse_titleblock(_lines_from_page(pg, clip))
                if cand["revs"] or cand["rev"] or cand["no"]:
                    tb = cand if tb is None or cand["revs"] else tb
                    if cand["revs"] and cand["no"]:
                        break
            if tb:
                out.update({k: tb[k] for k in ("no", "title", "revs", "rev", "rdate", "rdesc")})
            if not out["scale"] and tb is None:
                pass
        d.close()
    except Exception:
        pass
    return out


def guess_row(path):
    """One register row from a drawing PDF: the title block wins, the file name fills what the title block does not give."""
    base = os.path.splitext(os.path.basename(path))[0]
    info = read_pdf(path)
    no, title = "", base.replace("_", " ").strip()
    m = re.match(r"^\s*([A-Za-z]{0,3}[-_ ]?\d{1,4}[A-Za-z]?)\s*[-_ .]+\s*(.+)$", base)
    if m:
        no, title = m.group(1).replace("_", "-").replace(" ", "-").upper(), m.group(2).replace("_", " ").strip()
    rev = info["rev"]
    mr = re.search(r"[\s_\-]rev\.?\s*([A-Z]\d?|\d{1,2})\s*$", title, re.I)
    if mr:
        rev = rev or mr.group(1).upper()
        title = title[:mr.start()].strip(" -_")
    no = info["no"] or no
    if info["title"] and (not m or re.fullmatch(r"[A-Za-z]{0,3}[-_ ]?\d{1,4}[A-Za-z]?", base.strip())):
        title = info["title"]
    about = ""
    hay = title + " " + info["text"][:600]
    for pat, txt in ABOUT:
        if re.search(pat, title, re.I) or (not about and re.search(pat, hay, re.I)):
            about = txt
            if re.search(pat, title, re.I):
                break
    try:
        fdate = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except OSError:
        fdate = datetime.date.today().isoformat()
    desc = info["rdesc"]
    by = ""
    if re.search(r"client|owner|eienaar|kliënt", desc, re.I):
        by = "Client request"
    elif re.search(r"council|municip|munisipal|plan\s*approv", desc, re.I):
        by = "Council request"
    elif re.search(r"engineer|ingenieur", desc, re.I):
        by = "Engineer"
    return {"on": True, "no": no, "title": title, "about": about, "size": info["size"], "pages": info["pages"], "scale": info["scale"],
            "rev": rev, "rdate": info["rdate"] or "", "pdfdate": info["pdfdate"] or fdate, "by": by, "comment": desc, "auto": desc,
            "revs": info["revs"], "status": "For information", "file": os.path.basename(path), "path": path}


from register_ext import LogMixin, MailMixin, short_date


class RegisterPage(LogMixin, MailMixin, QWidget):
    mail_done = Signal(bool, str)
    is_costing = True
    report_title = "Drawing Register"

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.groups = []     # {name, rows:[...]}
        self.history = []    # issues already sent: {issue, date, rows:{key: {rev, rdate, title, comment}}}
        self.info = {"project": "", "client": "", "issued_by": "", "to": "", "email": "", "note": "", "issue_no": "0", "date": "", "cc": "", "client_logo": ""}
        self.log = []        # orders and revisions, see register_ext
        self.cur = 0
        self._busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sub = QTabWidget()
        outer.addWidget(self.sub)
        self.draw_w = QWidget()
        v = QVBoxLayout(self.draw_w)
        v.setContentsMargins(0, 6, 0, 0)
        step = lambda t: QLabel('<span style="font-size:14px; font-weight:700;">%s</span>' % t)
        # 1  who is it for
        v.addWidget(step("1.  Who is it for?"))
        self.f = {}
        g1 = QGridLayout()
        for i, (key, label, ph) in enumerate((("project", "Project", "taken from Project details if empty"), ("client", "Client", ""),
                                              ("to", "Send to (name)", ""), ("email", "Their email", "name@company.co.za"))):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            if key == "email":
                self._contacts_on(e)
            g1.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g1.addWidget(e, i // 2, (i % 2) * 2 + 1)
        v.addLayout(g1)
        self.contacts_hint = QLabel("")
        self.contacts_hint.setStyleSheet("color:gray;")
        self.contacts_hint.setWordWrap(True)
        self.contacts_hint.setVisible(False)
        v.addWidget(self.contacts_hint)
        self.more_chk = QCheckBox("More details (revision, date, copy to, logo)")
        v.addWidget(self.more_chk)
        self.more_w = QWidget()
        g2 = QGridLayout(self.more_w)
        g2.setContentsMargins(0, 0, 0, 0)
        for i, (key, label, ph) in enumerate((("issued_by", "Issued by", "from your signature"), ("issue_no", "Revision", "0"),
                                              ("date", "Date", "empty = today"), ("cc", "Copy to (Cc)", ""))):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            g2.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            if key == "issued_by":
                e.setVisible(False)
                self.issued_btn = QPushButton("")
                self.issued_btn.setStyleSheet("text-align:left;")
                self.issued_btn.clicked.connect(self.my_signature)
                g2.addWidget(self.issued_btn, i // 2, (i % 2) * 2 + 1)
            else:
                if key == "cc":
                    self._contacts_on(e)
                g2.addWidget(e, i // 2, (i % 2) * 2 + 1)
        lb = QPushButton("Client logo...")
        lb.clicked.connect(self.pick_logo)
        g2.addWidget(lb, 2, 1)
        self.more_w.setVisible(False)
        self.more_chk.toggled.connect(self.more_w.setVisible)
        v.addWidget(self.more_w)
        # 2  the drawings
        v.addSpacing(6)
        v.addWidget(step("2.  Add the drawings (PDFs)"))
        gl = QHBoxLayout()
        gl.addWidget(QLabel("For:"))
        self.gbox = QComboBox()
        self.gbox.setMinimumWidth(200)
        self.gbox.currentIndexChanged.connect(self._group_changed)
        gl.addWidget(self.gbox)
        nb = QPushButton("+ Another block or house")
        nb.clicked.connect(self.add_group)
        gl.addWidget(nb)
        gl.addSpacing(16)
        self.add_btn = QPushButton("Add drawing PDFs...")
        self.add_btn.setStyleSheet("font-weight:700;")
        self.add_btn.clicked.connect(self.add_pdfs)
        gl.addWidget(self.add_btn)
        fb = QPushButton("Add a whole folder...")
        fb.clicked.connect(self.add_folder)
        gl.addWidget(fb)
        rb = QPushButton("Remove selected")
        rb.clicked.connect(self.remove_row)
        gl.addWidget(rb)
        gl.addStretch(1)
        v.addLayout(gl)
        self.tab = QTableWidget(0, len(COLS))
        self.tab.setHorizontalHeaderLabels(COLS)
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((46, 90, 230, 250, 60, 60, 45, 90, 90, 140, 360, 150, 180)):
            self.tab.setColumnWidth(i, w)
        self.tab.itemChanged.connect(self._cell)
        v.addWidget(self.tab, 2)
        self.all_chk = QCheckBox("Show all details (size, scale, dates, who asked, status, file)")
        self.all_chk.toggled.connect(self._columns)
        v.addWidget(self.all_chk)
        # 3  the email and send
        v.addSpacing(6)
        v.addWidget(step("3.  Check the email and send it"))
        head = QHBoxLayout()
        self.to_lbl = QLabel("")
        head.addWidget(self.to_lbl, 1)
        rw = QPushButton("Write it again")
        rw.setToolTip("Throws away your changes to the text and writes the email again from the list above.")
        rw.clicked.connect(self.rewrite_mail)
        head.addWidget(rw)
        v.addLayout(head)
        self.mail = QPlainTextEdit()      # written automatically from the drawings, orders and changes; you can still edit it
        self.mail.setMinimumHeight(150)
        self._mail_setting, self._mail_manual = False, False
        self.mail.textChanged.connect(self._mail_edited)
        v.addWidget(self.mail, 1)
        self.att_lbl = QLabel("")
        self.att_lbl.setWordWrap(True)
        self.att_lbl.setStyleSheet("color: gray;")
        v.addWidget(self.att_lbl)
        bar = QHBoxLayout()
        self.send_btn = QPushButton("Send to the client...")
        self.send_btn.setMinimumHeight(38)
        self.send_btn.setStyleSheet("font-weight:700; padding: 0 22px;")
        self.send_btn.clicked.connect(self.send_mail)
        bar.addWidget(self.send_btn)
        for text, fn in (("Preview and edit the email", self.preview_email), ("Preview the PDF", self.preview_pdf), ("Save the PDF", self.export_pdf)):
            b = QPushButton(text)
            b.setMinimumHeight(38)
            b.clicked.connect(fn)
            bar.addWidget(b)
        more = QPushButton("More")
        more.setMinimumHeight(38)
        menu = QMenu(more)
        for text, fn in (("Email account...", self.email_account), ("My email signature...", self.my_signature), ("I sent it another way: record it as issued", self.mark_issued), (None, None),
                         ("Rename this block or house", self.rename_group), ("Delete this block or house", self.del_group),
                         ("Move the selected drawing up", lambda: self.move(-1)), ("Move the selected drawing down", lambda: self.move(1)),
                         ("Read the PDFs again (after you re-saved them)", self.reread), (None, None),
                         ("Copy the email text", self.copy_mail), ("Save the list as CSV", self.export_csv)):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, fn)
        more.setMenu(menu)
        bar.addWidget(more)
        bar.addStretch(1)
        self.count = QLabel("")
        bar.addWidget(self.count)
        v.addLayout(bar)
        self.sub.addTab(self.draw_w, "Drawings")
        self.sub.addTab(self.build_log(), "Orders and changes")
        self.mail_done.connect(self._mail_finished)
        self.add_group("House / Block 1", quiet=True)
        self._columns()
        self.refresh()

    def _mail_edited(self):
        if not self._mail_setting:
            self._mail_manual = True

    def rewrite_mail(self):
        self._mail_manual = False
        self.update_mail()

    def update_mail(self):
        """Keep the email under the list up to date: written from the drawings, orders and changes unless you have edited it yourself."""
        if getattr(self, "_mail_setting", None) is None or not hasattr(self, "att_lbl"):
            return
        if not self._mail_manual:
            self._mail_setting = True
            try:
                self.write_mail()
            except Exception as e:       # never leave the email box empty
                self.mail.setPlainText("(The email could not be written automatically: %s.)\n\nYou can still type it here." % e)
            finally:
                self._mail_setting = False
        gi = self.groups_in_issue()
        files = []
        for _n, rows in gi:
            for r in rows:
                p = r.get("path")
                if p and os.path.exists(p) and p not in files:
                    files.append(p)
        mb = sum(os.path.getsize(p) for p in files) / 1e6
        self.to_lbl.setText("<b>To:</b> %s" % (self.info.get("email") or "<i>add their email above</i>"))
        self.att_lbl.setText("Attached when you send: the drawing register (PDF)%s.%s" % (
            (" and %d drawing PDFs (%.1f MB)" % (len(files), mb)) if files else "",
            "  That is too big for one email: the send window can make the PDFs smaller or send them in several emails." if mb > 17 else ""))

    SIMPLE = ("on", "no", "title", "rev", "comment")

    def _columns(self, *_a):
        full = self.all_chk.isChecked()
        for i, k in enumerate(KEYS):
            self.tab.setColumnHidden(i, not (full or k in self.SIMPLE))

    # ----- state -----
    def state(self):
        return {"groups": self.groups, "info": self.info, "cur": self.cur, "mail": self.mail.toPlainText(), "history": self.history, "log": self.log}

    def set_state(self, d):
        d = d or {}
        self.groups = [dict(name=g.get("name", "Group"), rows=[dict(r) for r in g.get("rows", [])]) for g in d.get("groups", []) if isinstance(g, dict)]
        if not self.groups:
            self.groups = [{"name": "House / Block 1", "rows": []}]
        self.info.update({k: str(v) for k, v in (d.get("info") or {}).items() if k in self.info})
        self.log = [dict(x) for x in d.get("log", []) if isinstance(x, dict)]
        self.history = [dict(h) for h in d.get("history", []) if isinstance(h, dict)]
        self.cur = min(int(d.get("cur", 0) or 0), len(self.groups) - 1)
        self.mail.setPlainText(d.get("mail", "") or "")
        self.refresh()

    def project_name(self):
        return self.info["project"].strip() or (getattr(self.host, "rd", {}) or {}).get("project", "").strip() or "Project"

    def _info_edited(self, *_a):
        for k, e in self.f.items():
            self.info[k] = e.text()
        self.update_mail()

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

    @staticmethod
    def key(r):
        return (r.get("no") or r.get("title", "")).strip().lower()

    def find_row(self, k):
        for g in self.groups:
            for r in g["rows"]:
                if self.key(r) == k:
                    return r
        return None

    def add_paths(self, paths):
        """New drawings are added to the current group. A drawing already in the register (same drawing number) is updated in
        place from the new PDF, so a revised drawing replaces its older revision; comments you typed are kept."""
        added = updated = 0
        for p in sorted(paths, key=lambda x: os.path.basename(x).lower()):
            if not p.lower().endswith(".pdf"):
                continue
            new = guess_row(p)
            old = self.find_row(self.key(new))
            if old is None:
                self.rows().append(new)
                added += 1
            else:
                self._merge(old, new)
                updated += 1
        self.rows().sort(key=lambda r: (r.get("no") or "~", r.get("title", "").lower()))
        self.refresh()
        self.count.setText("%d added, %d updated from newer PDFs" % (added, updated) if (added or updated) else self.count.text())
        return added + updated

    def _merge(self, old, new):
        keep_c = old.get("comment", "") not in ("", old.get("auto", ""))
        keep_b = bool(old.get("by"))
        for k in ("title", "about", "size", "pages", "scale", "rev", "rdate", "pdfdate", "revs", "file", "path", "auto"):
            if new.get(k) not in (None, ""):
                old[k] = new[k]
        if not keep_c:
            old["comment"] = new["comment"]
        if not keep_b:
            old["by"] = new["by"]

    def reread(self):
        paths = [r.get("path") for g in self.groups for r in g["rows"] if r.get("path") and os.path.exists(r["path"])]
        for g in self.groups:
            for r in g["rows"]:
                if r.get("path") and os.path.exists(r["path"]):
                    self._merge(r, guess_row(r["path"]))
        self.refresh()
        self.count.setText("%d PDFs read again" % len(paths))

    # ----- what changed since the last issue -----
    def last_issue(self):
        return self.history[-1] if self.history else None

    def change_of(self, r):
        """('new' | 'revised' | 'same' | '', text) against the last issue that was marked as sent."""
        h = self.last_issue()
        if not h:
            return "", ""
        o = (h.get("rows") or {}).get(self.key(r))
        if o is None:
            return "new", "New drawing"
        if (o.get("rev") or "") != (r.get("rev") or "") or (r.get("rdate") and o.get("rdate") and r["rdate"] != o["rdate"]):
            return "revised", "Revised: Rev %s to Rev %s" % (o.get("rev") or "-", r.get("rev") or "-")
        return "same", "No change"

    def mark_issued(self, sent=None, ask=True):
        gi = self.groups_in_issue()
        if not gi:
            QMessageBox.information(self, "Drawing register", "Tick the drawings that were sent first.")
            return
        if ask and QMessageBox.question(self, "Drawing register", "Record this register as issued? The next register will show what changed "
                                        "against it (new drawings, new revisions and why), the log gets a line for it, and the comments are cleared for the next round.") != QMessageBox.StandardButton.Yes:
            return
        changes = {id(r): self.change_of(r)[0] for _n, rs in gi for r in rs}
        first = not self.history
        self.log_issue(gi, changes, first, sent)
        rows = {}
        for _n, rs in gi:
            for r in rs:
                rows[self.key(r)] = {"rev": r.get("rev", ""), "rdate": r.get("rdate", ""), "title": r.get("title", ""), "no": r.get("no", ""),
                                     "comment": r.get("comment", ""), "by": r.get("by", "")}
        self.history.append({"issue": self.info["issue_no"] or "0", "date": datetime.date.today().isoformat(), "rows": rows})
        try:
            self.info["issue_no"] = str(int(self.info["issue_no"] or "0") + 1)
        except ValueError:
            self.info["issue_no"] = self.info["issue_no"] + "+"
        for g in self.groups:
            for r in g["rows"]:
                r["comment"], r["auto"], r["by"] = "", "", ""
        self._mail_manual = False
        self.mail.setPlainText("")
        self.refresh()
        self.count.setText("Issue recorded. Add the revised PDFs (or press Re-read the PDFs) to see the changes.")

    def pick_logo(self):
        p, _ = QFileDialog.getOpenFileName(self, "Client logo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if p:
            self.info["client_logo"] = p
            self.count.setText("Client logo set")

    def logos(self):
        from PySide6.QtGui import QImage
        out = {}
        try:
            M = sys.modules[type(self.host).__module__]
            im = M.logo_pixmap().toImage().convertToFormat(QImage.Format.Format_ARGB32)
            for yy in range(im.height()):
                for xx in range(im.width()):
                    c = im.pixelColor(xx, yy)
                    if c.alpha() and c.red() > 200 and c.green() > 200 and c.blue() > 200:
                        im.setPixelColor(xx, yy, QColor(17, 17, 17, c.alpha()))
            out["mcp_logo"] = im
        except Exception:
            pass
        p = self.info.get("client_logo")
        if p and os.path.exists(p):
            im = QImage(p)
            if not im.isNull():
                out["client_logo"] = im
        return out

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
        k = KEYS[it.column()]
        if k == "on":
            row["on"] = it.checkState() == Qt.CheckState.Checked
        elif k in ("rdate", "pdfdate"):
            row[k] = norm_date(it.text()) or it.text().strip()
        else:
            row[k] = it.text().strip()
        QTimer.singleShot(0, self._counts)

    def _counts(self):
        self.update_mail()
        n = sum(1 for g in self.groups for r in g["rows"] if r.get("on"))
        self.count.setText("%d drawings in this issue, %d in all" % (n, sum(len(g["rows"]) for g in self.groups)))

    def refresh(self):
        self._busy = True
        try:
            for k, e in self.f.items():
                e.setText(self.info.get(k, ""))
            self._sync_issuer()
            self.gbox.clear()
            self.gbox.addItems([g["name"] for g in self.groups])
            self.gbox.setCurrentIndex(self.cur)
            rows = self.rows()
            self.tab.setRowCount(0)
            self.tab.setRowCount(len(rows))
            for i, r in enumerate(rows):
                kind, _t = self.change_of(r)
                for c, k in enumerate(KEYS):
                    if k == "on":
                        it = QTableWidgetItem("")
                        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        it.setCheckState(Qt.CheckState.Checked if r.get("on", True) else Qt.CheckState.Unchecked)
                    else:
                        txt = str(r.get(k, ""))
                        it = QTableWidgetItem(txt)
                        if k == "file":
                            it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                            it.setToolTip(r.get("path", ""))
                        if k == "title" and kind in ("new", "revised"):
                            it.setToolTip(_t)
                        if k == "rev" and r.get("revs"):
                            it.setToolTip("\n".join("Rev %s  %s  %s" % x for x in r["revs"]))
                    if kind in ("new", "revised"):
                        it.setBackground(QColor(120, 90, 20, 110) if kind == "revised" else QColor(30, 110, 60, 110))
                    self.tab.setItem(i, c, it)
                cb = QComboBox()
                cb.addItems(STATUSES)
                cb.setEditable(True)
                cb.setCurrentText(r.get("status", "For information"))
                cb.currentTextChanged.connect(lambda t, row=r: row.__setitem__("status", t))
                self.tab.setCellWidget(i, KEYS.index("status"), cb)
                cb2 = QComboBox()
                cb2.addItems(BYS)
                cb2.setEditable(True)
                cb2.setCurrentText(r.get("by", ""))
                cb2.currentTextChanged.connect(lambda t, row=r: row.__setitem__("by", t))
                self.tab.setCellWidget(i, KEYS.index("by"), cb2)
            self.tab.resizeRowsToContents()
            self._counts()
            self.refresh_log()
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

    def changes(self):
        """(new, revised) rows of the issue against the last one sent."""
        new, rev = [], []
        for _n, rows in self.groups_in_issue():
            for r in rows:
                k, _t = self.change_of(r)
                if k == "new":
                    new.append(r)
                elif k == "revised":
                    rev.append(r)
        return new, rev

    @staticmethod
    def _clean(r):
        by = r.get("by") or ""
        c = (r.get("comment") or "").strip()
        if by and c.lower().startswith(by.lower().split()[0]):
            c = re.sub(r"^\s*[A-Za-z ]{3,22}[:\-]\s*", "", c)
        return c

    def _local_addresses(self):
        from email.utils import getaddresses
        out = []
        for t in [self.info.get("email", ""), self.info.get("cc", "")] + [x.get("req_from", "") for x in self.log] + [x.get("sent_to", "") for x in self.log] \
                + [x.get("by_email", "") for x in self.log]:
            out += [(n, a) for n, a in getaddresses([t or ""]) if a]
        n = (self.info.get("to") or "").strip()
        if n and self.info.get("email"):
            out.append((n, self.info["email"].split(",")[0].split(";")[0].strip()))
        return out

    def _contacts_state(self):
        """Load the Google contacts in the background and tell the person if one more sign-in is needed."""
        try:
            import contacts
            M = self._M()
            if not getattr(self, "_hint_wired", False):
                self._hint_wired = True
                contacts.model()
                contacts._state["bus"].loaded.connect(lambda *_: self.contacts_hint.setVisible(False))
            contacts.set_local(self._local_addresses())
            contacts.refresh_async(M)
            S = M.SETTINGS
            need = S.get("mail_provider") != "gmail" or not S.get("google_refresh") or bool(S.get("contacts_note"))
            self.contacts_hint.setVisible(need and not contacts.count())
            self.contacts_hint.setText("To get your Gmail contacts here as you type: Email account > Sign in with Google (once more) and allow contacts."
                                       if S.get("mail_provider") == "gmail" else
                                       "Tip: sign in with Google (Email account) and the contacts of that Gmail account will appear here as you type.")
        except Exception:
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        self._contacts_state()

    def _contacts_on(self, line_edit):
        try:
            import contacts
            contacts.attach(line_edit, self._M)
        except Exception:
            pass

    def issuer(self):
        """Who the register is issued by: the signature of the person using the program."""
        try:
            from register_ext import signature_text
            t = signature_text(self._M().SETTINGS, "").split("\n")
            return ", ".join(x for x in t[:3] if x)
        except Exception:
            return self.info.get("issued_by", "")

    def _sync_issuer(self):
        if hasattr(self, "issued_btn"):
            self.issued_btn.setText(self.issuer() or "Click to set your name and details (your email signature)...")

    def rev_items(self, r):
        """The revision-column rows of this drawing that are newer than the last issue: [(rev, date, description)]."""
        h = self.last_issue()
        o = ((h or {}).get("rows") or {}).get(self.key(r)) or {}
        orev, odate = (o.get("rev") or ""), (o.get("rdate") or "")
        out = []
        for it in sorted((tuple(str(v or "") for v in x[:3]) for x in (r.get("revs") or []) if len(x) >= 3), key=lambda x: (x[1], x[0])):
            rv, dt, ds = it[0], it[1], it[2]
            if not ds:
                continue
            if o:
                if odate and dt:
                    if dt <= odate:
                        continue
                elif orev and rv <= orev:
                    continue
            out.append((rv, dt, ds))
        return out

    def _what(self, r):
        """What changed on a drawing, read from the title block's revision column; falls back to the typed comment."""
        try:
            items = self.rev_items(r)
        except Exception:
            items = []
        by = r.get("by") or ""
        if items:
            return (by + ": " if by else "") + "; ".join("Rev %s - %s" % (rv, ds) for rv, _dt, ds in items)
        return self._why(r)

    def _why(self, r):
        by, c = r.get("by") or "", self._clean(r)
        return (by + (": " if by and c else "") + c) if (by or c) else "no reason given"

    def write_mail(self):
        gi = self.groups_in_issue()
        to = self.info["to"].strip()
        last = self.last_issue()
        new, rev = self.changes()
        lines = ["Subject: %s - revision %s (%s)" % (self.project_name(), self.info["issue_no"] or "0", self.issue_date()), "",
                 "Hi %s," % (to.split()[0] if to else "there"), "",
                 "Please find the %sdrawings for %s issued today, %s. The drawing register is attached." %
                 ("revised " if last else "", self.project_name(), self.issue_date()), ""]
        if last and (rev or new):
            lines.append("WHAT CHANGED SINCE REVISION %s (%s)" % (last.get("issue", ""), last.get("date", "")))
            for r in rev:
                _k, t = self.change_of(r)
                lines.append("  - %s  %s  %s (%s): %s" % (r.get("no") or "-", r.get("title", ""), t.replace("Revised: ", ""), r.get("rdate") or r.get("pdfdate", ""), self._what(r)))
            for r in new:
                lines.append("  - %s  %s  NEW: %s" % (r.get("no") or "-", r.get("title", ""), r.get("about", "")))
            lines.append("")
        elif last:
            lines += ["No drawing has changed since revision %s." % last.get("issue", ""), ""]
        names = {n for n, _r in gi}
        pend = [x for x in self.log if not x.get("sent_date") and x.get("group") in names]
        if pend:
            lines.append("ORDERS AND CHANGES COVERED BY THIS REVISION")
            for x in pend:
                bit = "  - %s" % x.get("group", "")
                bit += (" (order no. %s)" % x["order"]) if x.get("order") else ""
                bit += ": " + (x.get("text") or ("New order" if x.get("type") == "Order" else "Change"))
                if x.get("by_name") or x.get("by_email"):
                    bit += " [asked by %s]" % " ".join(t for t in (x.get("by_name", ""), ("<%s>" % x["by_email"]) if x.get("by_email") else "") if t)
                if x.get("req_subject"):
                    bit += " [your email: %s%s]" % (x["req_subject"], ", " + short_date(x["req_date"]) if x.get("req_date") else "")
                lines.append(bit)
            lines.append("")
        lines.append("THE FULL LIST" if last else "THE DRAWINGS")
        for name, rows in gi:
            lines.append(name.upper() + (" (%d drawings)" % len(rows)))
            for r in rows:
                bit = "  - %s  %s  Rev %s  (%s%s)" % (r.get("no") or "-", r.get("title", ""), r.get("rev") or "-", r.get("size", ""), ", " + r["scale"] if r.get("scale") else "")
                bit += ": " + r["about"] if r.get("about") else ""
                lines.append(bit.replace("  -  ", "  - "))
            lines.append("")
        statuses = sorted({r.get("status", "") for _n, rows in gi for r in rows})
        if statuses:
            lines += ["Status of this revision: " + ", ".join(statuses) + ".", ""]
        if self.info["note"].strip():
            lines += [self.info["note"].strip(), ""]
        lines += ["Please let me know if anything is missing or if you have comments.", "", "Regards,"]
        try:
            from register_ext import signature_text
            lines.append(signature_text(self._M().SETTINGS, self.info["issued_by"].strip() or "MCP Architecture & Interiors"))
        except Exception:
            lines.append(self.info["issued_by"].strip() or "MCP Architecture & Interiors")
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

    def report_parts(self):
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        th = lambda t, w: '<th bgcolor="%s" align="left" width="%s%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left", bg="": '<td%s style="padding:3px;text-align:%s;">%s</td>' % (' bgcolor="%s"' % bg if bg else "", a, t)
        gi = self.groups_in_issue()
        n = sum(len(r) for _g, r in gi)
        last = self.last_issue()
        new, rev = self.changes()
        out = ['<p style="font-size:9pt;color:#444;">%d drawings in this issue.%s</p>' %
               (n, (" %d revised and %d new since revision %s." % (len(rev), len(new), e(last.get("issue", "")))) if last else "")]
        out.append(self.log_html(e, td, th, RED))
        if last and (rev or new):
            body = ""
            for r in rev:
                _k, t = self.change_of(r)
                body += "<tr>%s%s%s%s%s</tr>" % (td(e(r.get("no", ""))), td("<b>%s</b>" % e(r.get("title", ""))), td(e(t.replace("Revised: ", "")), "center"),
                                                  td(e(r.get("rdate") or r.get("pdfdate", "")), "center"), td(e(self._why(r))))
            for r in new:
                body += "<tr>%s%s%s%s%s</tr>" % (td(e(r.get("no", ""))), td("<b>%s</b>" % e(r.get("title", ""))), td("New", "center"),
                                                  td(e(r.get("rdate") or r.get("pdfdate", "")), "center"), td(e(r.get("about", ""))))
            out.append('<h3 style="color:%s;margin-bottom:3px;">Changes since revision %s (%s)</h3>' % (RED, e(last.get("issue", "")), e(last.get("date", ""))))
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' %
                       ("".join((th("No.", 8), th("Drawing", 24), th("Change", 14), th("Date", 10), th("Why / what was changed", 44))), body))
        for name, rows in gi:
            body = ""
            for i, r in enumerate(rows):
                kind, _t = self.change_of(r)
                bg = "#FFF1CC" if kind == "revised" else "#DDF3E4" if kind == "new" else ("#F6F6F6" if i % 2 else "")
                cmt = self._clean(r)
                if r.get("by"):
                    cmt = "<i>%s</i>%s" % (e(r["by"]), (": " + e(cmt)) if cmt else "")
                else:
                    cmt = e(cmt)
                cells = (td(e(r.get("no", "")), bg=bg), td("<b>%s</b>" % e(r.get("title", "")), bg=bg), td(e(r.get("about", "")), bg=bg), td(e(r.get("size", "")), "center", bg),
                         td(e(r.get("scale", "")), "center", bg), td("<b>%s</b>" % e(r.get("rev", "")), "center", bg), td(e(r.get("rdate", "")), "center", bg),
                         td(e(r.get("pdfdate", "")), "center", bg), td(cmt, bg=bg), td(e(r.get("status", "")), bg=bg))
                body += "<tr>%s</tr>" % "".join(cells)
            out.append('<h3 style="color:%s;margin-bottom:3px;">%s</h3>' % (RED, e(name)))
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8pt;"><tr>%s</tr>%s</table>' %
                       ("".join((th("No.", 6), th("Drawing", 15), th("What it shows", 22), th("Size", 4), th("Scale", 5), th("Rev", 3), th("Rev date", 8),
                                 th("PDF'd", 8), th("What changed", 19), th("Status", 10))), body))
        if self.history:
            out.append('<p style="font-size:7.5pt;color:#666;">Earlier revisions: %s.</p>' % e("; ".join("revision %s, %s (%d drawings)" % (h.get("issue", ""), h.get("date", ""), len(h.get("rows", {}))) for h in self.history)))
        out.append('<p style="font-size:7.5pt;color:#666;">Revision, revision date and drawing number are read from the title block of each drawing; PDF\'d is the date the PDF was made. '
                   'Shaded rows are new or revised since the last issue. Use the latest revision of every drawing; earlier revisions are superseded.</p>')
        return [x for x in out if x]

    def report_html(self):
        return "".join(self.report_parts())

    def cover_html(self):
        e = lambda x: _html.escape(str(x))
        rd = getattr(self.host, "rd", {}) or {}
        RED, DARK = "#C8102E", "#DCDCDC"
        company = rd.get("company") or "MCP Architecture & Interiors"
        client_logo = '<img src="client_logo" height="55">' if "client_logo" in self.logos() else ""
        h = ('<p style="font-size:40pt;">&nbsp;</p><p align="center"><img src="logo" height="90"></p>'
             '<p align="center" style="font-size:11pt; color:#444444;">%s</p><p style="font-size:30pt;">&nbsp;</p>'
             '<table width="100%%" cellspacing="0" cellpadding="14" border="0"><tr><td bgcolor="%s" style="color:#222222;">'
             '<span style="font-size:24pt; font-weight:bold;">DRAWING REGISTER</span><br>'
             '<span style="font-size:9pt; color:#555555;">Revision %s &nbsp;|&nbsp; %s</span></td></tr></table>'
             '<table width="100%%" cellspacing="0" cellpadding="0" border="0"><tr><td bgcolor="%s" height="4"></td></tr></table>' %
             (e(company), DARK, e(self.info["issue_no"] or "0"), e(self.issue_date()), RED))
        h += ('<p style="font-size:12pt;">&nbsp;</p><p style="font-size:9pt; color:#666666;">PROJECT</p>'
              '<p style="font-size:16pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>'
              '<p style="font-size:9pt; color:#666666;">SITE</p>'
              '<p style="font-size:13pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>' % (e(self.project_name()), e(rd.get("details") or "-")))
        h += ('<p style="font-size:12pt;">&nbsp;</p><table width="100%%" cellspacing="0" cellpadding="3" border="0"><tr>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">CLIENT<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">ISSUED TO<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td></tr></table>'
              '<p style="font-size:8pt;">&nbsp;</p><table width="100%%" cellspacing="0" cellpadding="3" border="0"><tr>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">ARCHITECTURE FIRM<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">DRAWINGS IN THIS REVISION<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%d</span></td></tr></table>' %
              (e(self.info["client"] or rd.get("owner") or "-"), e(self.info["to"] or "-"), e(rd.get("architect") or company),
               sum(len(r) for _g, r in self.groups_in_issue())))
        if client_logo:
            h += '<p style="font-size:10pt;">&nbsp;</p><p align="right">%s</p>' % client_logo
        h += ('<p style="font-size:20pt;">&nbsp;</p><p style="font-size:9pt; color:#666666;">THIS REGISTER WAS COMPILED BY</p>'
              '<p style="font-size:12pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>' % e(self.issuer() or rd.get("prepared_by") or company))
        if rd.get("contact"):
            h += '<p style="font-size:8pt; color:#777777;">%s</p>' % e(rd["contact"])
        return h

    def write_pdf(self, path):
        """Cover page like the other reports (logo, grey title band with the red bar), then the register on landscape pages with a footer."""
        from PySide6.QtCore import QMarginsF, QRectF, QSizeF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument
        M = sys.modules[type(self.host).__module__]
        if not hasattr(M, "_pack_pages"):
            return self._write_plain(path)
        lg = self.logos()
        if "mcp_logo" in lg:
            lg["logo"] = lg.pop("mcp_logo")
        w = QPdfWriter(path)
        mk = lambda o: QPageLayout(QPageSize(QPageSize.PageSizeId.A4), o, QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
        w.setPageLayout(mk(QPageLayout.Orientation.Portrait))
        w.setResolution(96)
        w.setTitle("Drawing register")
        pwp, php = float(w.width()), float(w.height())

        def mkdoc(html_, pw):
            d_ = QTextDocument()
            for nm, im in lg.items():
                d_.addResource(QTextDocument.ResourceType.ImageResource, QUrl(nm), im)
            d_.setDefaultFont(QFont("Arial", 9))
            d_.setHtml('<html><body style="font-family:Arial; color:#111111;">' + html_ + "</body></html>")
            d_.setPageSize(QSizeF(pw, 1e7))
            return d_
        # the client logo is stored under the name used in the html
        painter = QPainter(w)
        painter.save()
        M._draw_doc_rounded(painter, mkdoc(self.cover_html(), pwp))
        painter.restore()
        w.setPageLayout(mk(QPageLayout.Orientation.Landscape))
        w.newPage()
        pw, ph = float(w.width()), float(w.height())
        body = self.report_parts()
        pages = M._pack_pages(lambda h: mkdoc(h, pw), body, ph - 30.0)
        company = (getattr(self.host, "rd", {}) or {}).get("company") or "MCP Architecture & Interiors"
        for i, (html_, y0, y1) in enumerate(pages):
            if i:
                w.newPage()
            painter.save()
            painter.translate(0, -y0)
            if y1 is not None:
                painter.setClipRect(QRectF(-5, y0, pw + 10, y1 - y0 + 1))
            M._draw_doc_rounded(painter, mkdoc(html_, pw))
            painter.restore()
            painter.save()
            painter.setPen(QColor("#9A9A9A"))
            painter.setFont(QFont("Arial", 7))
            painter.drawLine(0, int(ph - 24), int(pw), int(ph - 24))
            painter.drawText(QRectF(0, ph - 22, pw * 0.8, 16), int(Qt.AlignmentFlag.AlignLeft),
                             "%s  |  Drawing Register  |  %s  |  Revision %s" % (company, self.project_name(), self.info["issue_no"] or "0"))
            painter.drawText(QRectF(0, ph - 22, pw, 16), int(Qt.AlignmentFlag.AlignRight), "Page %d of %d" % (i + 2, len(pages) + 1))
            painter.restore()
        painter.end()

    def _write_plain(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.cover_html() + self.report_html() + "</body></html>")
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
            w.writerow(["Group", "Drawing no.", "Title", "What it shows", "Size", "Scale", "Rev", "Rev date", "PDF date", "Requested by", "What changed", "Change since last issue", "Status", "File"])
            for name, rows in self.groups_in_issue():
                for r in rows:
                    w.writerow([name] + [r.get(k, "") for k in ("no", "title", "about", "size", "scale", "rev", "rdate", "pdfdate", "by", "comment")] +
                               [self.change_of(r)[1], r.get("status", ""), r.get("file", "")])
