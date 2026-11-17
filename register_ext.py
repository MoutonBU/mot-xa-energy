"""Drawing register, part 2: the orders-and-revisions log (what the practice sends the client with every issue) and sending the email from the program."""
import datetime
import email as _email
import email.policy
import os
import re
import smtplib
import ssl
import sys
import tempfile
import threading
from collections import Counter
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

LOGK = ("group", "type", "rev", "date", "order", "text", "by", "req_subject", "req_date", "req_from", "sent_date", "sent_to", "status")
LOGC = ["House / block", "Type", "Rev", "Date", "Order no.", "What was ordered / changed", "Requested by", "Request email (subject)", "Received",
        "From", "Sent on", "Sent to", "Status"]
TYPES = ["Order", "Change", "Issue"]
LSTAT = ["Draft", "Final", "Issued", "Superseded"]
PRESETS = {"Gmail": ("smtp.gmail.com", 465, "SSL"), "Outlook / Office 365": ("smtp.office365.com", 587, "STARTTLS"), "Other": ("", 587, "STARTTLS")}


def _iso(d):
    try:
        return parsedate_to_datetime(d).date().isoformat()
    except Exception:
        return ""


def read_reference(path):
    """Subject, sender, date received and a body preview from an .eml (or the file name for any other kind of file)."""
    out = {"subject": os.path.splitext(os.path.basename(path))[0], "from": "", "date": "", "body": ""}
    low = path.lower()
    try:
        if low.endswith(".eml"):
            with open(path, "rb") as f:
                m = _email.message_from_binary_file(f, policy=email.policy.default)
            out["subject"] = str(m["subject"] or out["subject"])
            out["from"] = str(m["from"] or "")
            out["date"] = _iso(str(m["date"] or ""))
            b = m.get_body(preferencelist=("plain", "html"))
            out["body"] = (b.get_content() if b else "")[:3000]
        elif low.endswith(".msg"):
            import extract_msg
            m = extract_msg.Message(path)
            out.update({"subject": m.subject or out["subject"], "from": m.sender or "", "body": (m.body or "")[:3000]})
            out["date"] = _iso(str(m.date or ""))
    except Exception:
        pass
    if not out["date"]:
        try:
            out["date"] = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
        except OSError:
            pass
    return out


def find_order_no(text):
    for m in re.finditer(r"(?:purchase\s*order|order|\bPO\b)\s*(?:no\.?|number|nr\.?|#)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{3,20})", text or "", re.I):
        if re.search(r"\d", m.group(1)):
            return m.group(1)
    return ""


def short_date(iso):
    try:
        return datetime.date.fromisoformat(iso).strftime("%d %b %y").lstrip("0")
    except (ValueError, TypeError):
        return iso or ""


class SmtpDialog(QDialog):
    def __init__(self, M, parent=None):
        super().__init__(parent)
        self.M = M
        self.setWindowTitle("Email account")
        self.resize(520, 380)
        S = M.SETTINGS
        v = QVBoxLayout(self)
        v.addWidget(QLabel("The account the drawing register is sent from. Gmail and Microsoft need an app password (made in the account's security "
                           "settings), not the normal password. The password is kept in this program's settings file on this computer, not encrypted."))
        v.itemAt(0).widget().setWordWrap(True)
        f = QFormLayout()
        self.pre = QComboBox()
        self.pre.addItems(list(PRESETS))
        self.host = QLineEdit(S.get("smtp_host", ""))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(S.get("smtp_port") or 587))
        self.sec = QComboBox()
        self.sec.addItems(["SSL", "STARTTLS", "None"])
        self.sec.setCurrentText(S.get("smtp_security") or "STARTTLS")
        self.user = QLineEdit(S.get("smtp_user", ""))
        self.pw = QLineEdit(S.get("smtp_pass", ""))
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.frm = QLineEdit(S.get("smtp_from", ""))
        self.frm.setPlaceholderText("MCP Architecture & Interiors <you@example.com>  (empty = the user name)")
        self.cc_me = QCheckBox("Send myself a copy (Bcc)")
        self.cc_me.setChecked(bool(S.get("smtp_bcc_me", True)))
        for k, w in (("Provider", self.pre), ("Server", self.host), ("Port", self.port), ("Security", self.sec), ("User name", self.user),
                     ("Password", self.pw), ("From", self.frm)):
            f.addRow(k, w)
        f.addRow("", self.cc_me)
        v.addLayout(f)
        self.pre.currentTextChanged.connect(self._preset)
        for name, (h, p, s) in PRESETS.items():
            if h and h == self.host.text():
                self.pre.setCurrentText(name)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        bar = QHBoxLayout()
        for text, fn in (("Send a test to myself", self.test), ("Save", self.save), ("Cancel", self.reject)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)

    def _preset(self, name):
        h, p, s = PRESETS[name]
        if h:
            self.host.setText(h)
            self.port.setValue(p)
            self.sec.setCurrentText(s)

    def cfg(self):
        return {"smtp_host": self.host.text().strip(), "smtp_port": self.port.value(), "smtp_security": self.sec.currentText(),
                "smtp_user": self.user.text().strip(), "smtp_pass": self.pw.text(), "smtp_from": self.frm.text().strip(),
                "smtp_bcc_me": self.cc_me.isChecked()}

    def save(self):
        self.M.SETTINGS.update(self.cfg())
        self.M.save_settings()
        self.accept()

    def test(self):
        c = self.cfg()
        addr = c["smtp_from"] or c["smtp_user"]
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = addr, addr, "Drawing register: test"
        m.set_content("This is a test from the drawing register. The email account works.")
        try:
            smtp_send(c, m)
            self.msg.setText("Test sent to %s." % addr)
        except Exception as e:
            self.msg.setText("Could not send: %s" % e)


def smtp_send(c, msg):
    host, port, sec = c["smtp_host"], int(c["smtp_port"]), c["smtp_security"]
    if not host:
        raise RuntimeError("no mail server set")
    ctx = ssl.create_default_context()
    if sec == "SSL":
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=90)
    else:
        s = smtplib.SMTP(host, port, timeout=90)
        s.ehlo()
        if sec == "STARTTLS":
            s.starttls(context=ctx)
            s.ehlo()
    try:
        if c.get("smtp_user"):
            s.login(c["smtp_user"], c.get("smtp_pass", ""))
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except Exception:
            pass


def addresses(t):
    return [a.strip() for a in re.split(r"[;,]", t or "") if a.strip()]


class SendDialog(QDialog):
    def __init__(self, page, subject, body, pdf_path, drawings):
        super().__init__(page)
        self.setWindowTitle("Send the drawing register")
        self.resize(760, 640)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.to = QLineEdit(page.info.get("email", ""))
        self.cc = QLineEdit(page.info.get("cc", ""))
        self.sub = QLineEdit(subject)
        f.addRow("To", self.to)
        f.addRow("Cc", self.cc)
        f.addRow("Subject", self.sub)
        v.addLayout(f)
        self.body = QPlainTextEdit(body)
        v.addWidget(self.body, 3)
        v.addWidget(QLabel("Attachments (tick what goes):"))
        self.att = QListWidget()
        self.items = []
        for label, p in [("Drawing register (PDF)", pdf_path)] + [(os.path.basename(x), x) for x in drawings]:
            it = QListWidgetItem("%s   (%.1f MB)" % (label, os.path.getsize(p) / 1e6))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.att.addItem(it)
            self.items.append((it, p))
        self.att.itemChanged.connect(self._size)
        v.addWidget(self.att, 2)
        self.size = QLabel("")
        v.addWidget(self.size)
        bar = QHBoxLayout()
        self.send = QPushButton("Send")
        self.send.setDefault(True)
        c = QPushButton("Cancel")
        self.send.clicked.connect(self._go)
        c.clicked.connect(self.reject)
        bar.addStretch(1)
        bar.addWidget(c)
        bar.addWidget(self.send)
        v.addLayout(bar)
        self._size()

    def files(self):
        return [p for it, p in self.items if it.checkState() == Qt.CheckState.Checked]

    def _size(self, *_a):
        mb = sum(os.path.getsize(p) for p in self.files()) / 1e6
        self.size.setText("%d files, %.1f MB%s" % (len(self.files()), mb, "   (many mail servers refuse more than 20 to 25 MB: untick drawings or send in two emails)" if mb > 20 else ""))

    def _go(self):
        if not addresses(self.to.text()):
            QMessageBox.information(self, "Drawing register", "Enter who it goes to.")
            return
        self.accept()


class LogMixin:
    """The orders-and-revisions log."""

    def build_log(self):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        bar = QHBoxLayout()
        for text, fn in (("Add order", lambda: self.add_log("Order")), ("Add change", lambda: self.add_log("Change")),
                         ("Attach email / PDF...", self.attach_ref), ("Open attached", self.open_ref), ("Remove line", self.remove_log)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)
        self.ltab = QTableWidget(0, len(LOGK))
        self.ltab.setHorizontalHeaderLabels(LOGC)
        self.ltab.verticalHeader().setVisible(False)
        self.ltab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ltab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.ltab.horizontalHeader().setStretchLastSection(True)
        for i, wd in enumerate((130, 70, 40, 85, 100, 330, 130, 240, 85, 170, 85, 200, 80)):
            self.ltab.setColumnWidth(i, wd)
        self.ltab.itemChanged.connect(self._log_cell)
        v.addWidget(self.ltab, 1)
        n = QLabel("One line per order or revision, like the register you send now: what was ordered or changed, the email it came from (attach the "
                   "client's email here as the reference), and the email you sent back. Orders and changes you add stay \"Draft\" until the next "
                   "email goes out; sending (or Mark as issued) fills in the rev, date and who it was sent to. Drawings that changed are listed for you.")
        n.setWordWrap(True)
        n.setStyleSheet("color: gray; font-size: 11px;")
        v.addWidget(n)
        return w

    def add_log(self, typ):
        e = {k: "" for k in LOGK}
        e.update({"group": self.groups[self.cur]["name"], "type": typ, "date": datetime.date.today().isoformat(), "status": "Draft",
                  "text": "New order" if typ == "Order" else "", "req_path": "", "sent_path": "", "drawings": ""})
        self.log.append(e)
        self.refresh_log()
        self.ltab.selectRow(len(self.log) - 1)

    def remove_log(self):
        r = self.ltab.currentRow()
        if 0 <= r < len(self.log):
            self.log.pop(r)
            self.refresh_log()

    def attach_ref(self):
        r = self.ltab.currentRow()
        if not (0 <= r < len(self.log)):
            QMessageBox.information(self, "Drawing register", "Add an order or a change first, select it, then attach the email.")
            return
        p, _ = QFileDialog.getOpenFileName(self, "The client's email (.eml, .msg, .pdf or a screenshot)", "", "Email or document (*.eml *.msg *.pdf *.png *.jpg *.jpeg *.txt);;All files (*)")
        if not p:
            return
        ref = read_reference(p)
        e = self.log[r]
        e["req_path"], e["req_subject"], e["req_from"], e["req_date"] = p, ref["subject"], ref["from"], ref["date"]
        if not e.get("order"):
            e["order"] = find_order_no(ref["subject"] + " " + ref["body"])
        if not e.get("text") or e["text"] == "New order":
            e["text"] = ref["subject"] or e.get("text") or "Change"
        low = (ref["subject"] + " " + ref["body"]).lower()
        if not e.get("by"):
            e["by"] = "Council request" if re.search(r"council|municip", low) else "Client request"
        self.refresh_log()

    def open_ref(self):
        r = self.ltab.currentRow()
        if 0 <= r < len(self.log):
            p = self.log[r].get("req_path") or self.log[r].get("sent_path")
            if p and os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _log_cell(self, it):
        if self._busy or not (0 <= it.row() < len(self.log)):
            return
        k = LOGK[it.column()]
        self.log[it.row()][k] = it.text().strip()

    def refresh_log(self):
        self._busy = True
        try:
            t = self.ltab
            t.setRowCount(0)
            t.setRowCount(len(self.log))
            for i, e in enumerate(self.log):
                for c, k in enumerate(LOGK):
                    it = QTableWidgetItem(str(e.get(k, "")))
                    if k in ("req_subject",) and e.get("req_path"):
                        it.setToolTip(e["req_path"])
                    if e.get("status") == "Draft":
                        it.setBackground(QColor(120, 90, 20, 90))
                    t.setItem(i, c, it)
                for k, vals in (("group", [g["name"] for g in self.groups]), ("type", TYPES), ("by", None), ("status", LSTAT)):
                    cb = QComboBox()
                    cb.setEditable(True)
                    from register import BYS
                    cb.addItems(vals if vals is not None else BYS)
                    cb.setCurrentText(str(e.get(k, "")))
                    cb.currentTextChanged.connect(lambda tx, ent=e, kk=k: ent.__setitem__(kk, tx))
                    t.setCellWidget(i, LOGK.index(k), cb)
            t.resizeRowsToContents()
        finally:
            self._busy = False

    # called when an issue goes out
    def log_issue(self, gi, changes, first, sent):
        today = datetime.date.today().isoformat()
        for name, rows in gi:
            items = [r for r in rows if first or changes.get(id(r)) in ("new", "revised")]
            pend = next((e for e in self.log if e.get("group") == name and not e.get("sent_date")), None)
            if not items and pend is None:
                continue
            if pend is None:
                pend = {k: "" for k in LOGK}
                pend.update({"group": name, "type": "Issue" if first else "Change", "req_path": "", "sent_path": "", "drawings": ""})
                self.log.append(pend)
            done = sum(1 for e in self.log if e.get("group") == name and e.get("sent_date"))
            if not pend.get("rev"):
                pend["rev"] = str(done)
            by = Counter(r.get("by") for r in items if r.get("by")).most_common(1)
            if not pend.get("by") and by:
                pend["by"] = by[0][0]
            pend["drawings"] = "; ".join("%s Rev %s" % (r.get("no") or r.get("title", ""), r.get("rev") or "-") for r in items)
            if not pend.get("text") or pend["text"] == "New order":
                parts = [self._why(r) for r in items if r.get("comment") or r.get("by")]
                pend["text"] = (pend.get("text") or "") + ("; ".join(parts) if parts else ("Drawings issued" if first else "Drawings revised"))
            pend["date"] = today
            if sent:
                pend["sent_date"], pend["sent_to"], pend["sent_subject"], pend["sent_path"] = today, sent["to"], sent["subject"], sent.get("path", "")
            else:
                pend["sent_date"] = today
            pend["status"] = "Final"
        self.refresh_log()

    # ----- the log as it prints (the layout of the register you use now) -----
    def log_html(self, e_, td, th, RED):
        if not self.log:
            return ""
        out = ['<h3 style="color:%s;margin-bottom:3px;">Orders and revisions</h3>' % RED]
        names = [g["name"] for g in self.groups] + sorted({x.get("group") for x in self.log} - {g["name"] for g in self.groups})
        body = ""
        for name in names:
            ents = [x for x in self.log if x.get("group") == name]
            ents.sort(key=lambda x: (x.get("sent_date") or "9999", x.get("date", "")))
            for x in ents:
                head = ("New order" if x.get("type") == "Order" else "Change on" if x.get("type") == "Change" else "Issue") 
                txt = x.get("text", "")
                first = '<b>%s</b>' % e_(txt) if x.get("type") == "Order" else '<b><font color="#C00000">%s</font> %s</b>' % (e_(head), e_(txt)) if x.get("type") == "Change" else '<b>%s</b>' % e_(txt)
                if x.get("order"):
                    first += ' &nbsp;<b>[Order no. %s]</b>' % e_(x["order"])
                lines = [first]
                if x.get("drawings"):
                    lines.append('<font color="#555555">Drawings: %s</font>' % e_(x["drawings"]))
                if x.get("req_subject") or x.get("by"):
                    lines.append('<font color="#1E8CC8">Request%s: %s%s%s</font>' % (" (%s)" % e_(x["by"]) if x.get("by") else "", e_(x.get("req_subject", "")),
                                 " (date received %s)" % e_(short_date(x["req_date"])) if x.get("req_date") else "", " " + e_(x["req_from"].split("<")[0].strip()) if x.get("req_from") else ""))
                if x.get("sent_date"):
                    lines.append('<font color="#1E9C5A">email sent: %s %s</font>' % (e_(x.get("sent_subject", "")), e_(short_date(x["sent_date"]))))
                left = '<b>%s</b>' % e_(name)
                if x.get("status"):
                    left += '<br><font color="#1E9C5A"><b>%s</b></font>' % e_(x["status"].lower())
                if x.get("sent_to"):
                    left += '<br><font size="1">sent to %s</font>' % e_(x["sent_to"])
                body += "<tr>%s%s%s%s</tr>" % (td(left), td("<br>".join(lines)), td("<b>%s</b>" % e_(x.get("rev", "")), "center"), td(e_(short_date(x.get("sent_date") or x.get("date", ""))), "center"))
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' %
                   ("".join((th("House / block", 20), th("Description", 60), th("Rev", 6), th("Date", 14))), body))
        return "".join(out)


class MailMixin:
    def email_account(self):
        M = sys.modules[type(self.host).__module__]
        if not hasattr(M, "SETTINGS"):
            return None
        d = SmtpDialog(M, self)
        return d.exec()

    def _smtp_cfg(self):
        M = sys.modules[type(self.host).__module__]
        S = M.SETTINGS
        c = {k: S.get(k, "") for k in ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_pass", "smtp_from", "smtp_bcc_me")}
        return c if c["smtp_host"] else None

    def send_mail(self):
        gi = self.groups_in_issue()
        if not gi:
            QMessageBox.information(self, "Drawing register", "Tick the drawings that go in this issue first.")
            return
        cfg = self._smtp_cfg()
        if cfg is None:
            QMessageBox.information(self, "Drawing register", "Set up the email account the register is sent from first.")
            if not self.email_account():
                return
            cfg = self._smtp_cfg()
            if cfg is None:
                return
        subj, body = self._mail_parts()
        tmp = tempfile.mkdtemp()
        pdf = os.path.join(tmp, re.sub(r'[\\/:*?"<>|]+', "-", "Drawing register - %s - issue %s.pdf" % (self.project_name(), self.info["issue_no"] or "1")))
        self.write_pdf(pdf)
        seen, drawings = set(), []
        for _n, rows in gi:
            for r in rows:
                p = r.get("path")
                if p and os.path.exists(p) and p not in seen:
                    seen.add(p)
                    drawings.append(p)
        dlg = SendDialog(self, subj, body, pdf, drawings)
        if not dlg.exec():
            return
        m = EmailMessage()
        frm = cfg["smtp_from"] or cfg["smtp_user"]
        to, cc = addresses(dlg.to.text()), addresses(dlg.cc.text())
        m["From"], m["To"], m["Subject"] = frm, ", ".join(to), dlg.sub.text().strip()
        if cc:
            m["Cc"] = ", ".join(cc)
        m.set_content(dlg.body.toPlainText())
        for p in dlg.files():
            with open(p, "rb") as f:
                m.add_attachment(f.read(), maintype="application", subtype="pdf" if p.lower().endswith(".pdf") else "octet-stream", filename=os.path.basename(p))
        bcc = [frm] if cfg.get("smtp_bcc_me") else []
        self.info["email"], self.info["cc"] = dlg.to.text().strip(), dlg.cc.text().strip()
        self._sending = {"to": ", ".join(to + cc), "subject": m["Subject"], "msg": m}
        self.count.setText("Sending...")
        self.setEnabled(False)

        def work():
            try:
                smtp_send(cfg, m) if not bcc else self._send_with_bcc(cfg, m, to + cc + bcc)
                self.mail_done.emit(True, "")
            except Exception as e:
                self.mail_done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _send_with_bcc(cfg, m, rcpts):
        host, port, sec = cfg["smtp_host"], int(cfg["smtp_port"]), cfg["smtp_security"]
        ctx = ssl.create_default_context()
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=90) if sec == "SSL" else smtplib.SMTP(host, port, timeout=90)
        try:
            if sec != "SSL":
                s.ehlo()
                if sec == "STARTTLS":
                    s.starttls(context=ctx)
                    s.ehlo()
            if cfg.get("smtp_user"):
                s.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))
            s.send_message(m, to_addrs=rcpts)
        finally:
            try:
                s.quit()
            except Exception:
                pass

    def _mail_finished(self, ok, err):
        self.setEnabled(True)
        s = getattr(self, "_sending", None)
        if not ok or not s:
            self.count.setText("Not sent")
            QMessageBox.warning(self, "Drawing register", "The email was not sent: %s\n\nCheck the account (Email account...) and the addresses." % err)
            return
        path = ""
        try:
            M = sys.modules[type(self.host).__module__]
            d = os.path.join(M._user_data_dir(), "register_sent")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "%s - %s.eml" % (datetime.datetime.now().strftime("%Y-%m-%d %H%M"), re.sub(r'[\\/:*?"<>|]+', "-", s["subject"])[:80]))
            with open(path, "wb") as f:
                f.write(bytes(s["msg"]))
        except Exception:
            path = ""
        self.count.setText("Sent to %s" % s["to"])
        self.mark_issued(sent={"to": s["to"], "subject": s["subject"], "path": path}, ask=False)
        QMessageBox.information(self, "Drawing register", "Sent to %s.\nThe issue is recorded in the log; a copy of the email is saved with it." % s["to"])
