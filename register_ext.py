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

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

LOGK = ("group", "type", "rev", "date", "order", "text", "by", "req_subject", "req_date", "req_from", "sent_date", "sent_to", "status")
LOGC = ["House or block", "Type", "Rev", "Date", "Order number", "What was ordered or changed", "Asked by", "The client's email", "Received",
        "From", "Sent to the client on", "Sent to", "Status"]
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


_KEEP = []


class AccountDialog(QDialog):
    """Type the email address and password, press Connect. The mail server is found by the program.
    Gmail needs an app password (the program shows where to get it) or the Sign in with Google button."""
    signed = Signal(bool, str)
    conn = Signal(bool, str, object)
    prog = Signal(str)

    def __init__(self, M, parent=None):
        super().__init__(parent)
        import mail_oauth
        self.mo = mail_oauth
        self.M = M
        self.S = M.SETTINGS
        self.setWindowTitle("Email account")
        self.resize(560, 470)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>Your email address</b>"))
        self.addr = QLineEdit(self.S.get("mail_address", ""))
        self.addr.setPlaceholderText("name@company.co.za")
        v.addWidget(self.addr)
        self.pw_lbl = QLabel("<b>Your email password</b>")
        v.addWidget(self.pw_lbl)
        self.pw = QLineEdit(self.S.get("smtp_pass", ""))
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.pw)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setOpenExternalLinks(True)
        v.addWidget(self.hint)
        self.gbtn = QPushButton("Open Google's page to make the app password")
        self.gbtn.clicked.connect(self.open_app_pw)
        v.addWidget(self.gbtn)
        self._pw_mode = False
        self._closed = False
        self.finished.connect(lambda *_: setattr(self, "_closed", True))
        self.connect_b = QPushButton("Connect")
        self.connect_b.setMinimumHeight(40)
        self.connect_b.setStyleSheet("font-weight:700;")
        self.connect_b.clicked.connect(self.connect_now)
        v.addWidget(self.connect_b)
        self.pwlink = QPushButton("")
        self.pwlink.setFlat(True)
        self.pwlink.setStyleSheet("color: gray; text-decoration: underline; border: none;")
        self.pwlink.clicked.connect(self._toggle_pw)
        v.addWidget(self.pwlink)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.adv = QCheckBox("Other ways to connect (sign in with Google / Microsoft, or type the server by hand)")
        v.addWidget(self.adv)
        from PySide6.QtWidgets import QGroupBox, QWidget
        self.adv_w = QWidget()
        av = QVBoxLayout(self.adv_w)
        av.setContentsMargins(0, 0, 0, 0)
        self.prov = QComboBox()
        self.prov.addItems(["Gmail: sign in with Google", "Outlook / Microsoft 365: sign in with Microsoft", "Type the mail server by hand"])
        k0 = self.S.get("mail_provider", "smtp")
        self.prov.setCurrentIndex({"gmail": 0, "outlook": 1, "smtp": 2}.get(k0, 2))
        av.addWidget(self.prov)
        self.signbtn = QPushButton("")
        self.signbtn.setMinimumHeight(36)
        self.signbtn.clicked.connect(self.sign_in)
        av.addWidget(self.signbtn)
        self._show_setup = False
        self.setup_btn = QPushButton("Sign-in is not switched on yet: set it up (one time)...")
        self.setup_btn.clicked.connect(self._open_setup)
        av.addWidget(self.setup_btn)
        self.setup = QGroupBox("One-time setup of this program (whoever manages it)")
        sf = QFormLayout(self.setup)
        self.help = QLabel("")
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color: gray; font-size: 11px;")
        sf.addRow(self.help)
        self.cid = QLineEdit()
        self.csec = QLineEdit()
        self.csec.setEchoMode(QLineEdit.EchoMode.Password)
        sf.addRow("Client ID", self.cid)
        self.csec_lbl = QLabel("Client secret")
        sf.addRow(self.csec_lbl, self.csec)
        av.addWidget(self.setup)
        self.smtp = QGroupBox("Mail server")
        mf = QFormLayout(self.smtp)
        self.host = QLineEdit(self.S.get("smtp_host", ""))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(self.S.get("smtp_port") or 587))
        self.sec = QComboBox()
        self.sec.addItems(["SSL", "STARTTLS", "None"])
        self.sec.setCurrentText(self.S.get("smtp_security") or "STARTTLS")
        self.user = QLineEdit(self.S.get("smtp_user", ""))
        for k, w in (("Server", self.host), ("Port", self.port), ("Security", self.sec), ("User name", self.user)):
            mf.addRow(k, w)
        av.addWidget(self.smtp)
        self.adv_w.setVisible(False)
        v.addWidget(self.adv_w)
        self.bcc = QCheckBox("Send myself a copy of every email I send")
        self.bcc.setChecked(bool(self.S.get("smtp_bcc_me", True)))
        v.addWidget(self.bcc)
        v.addStretch(1)
        bar = QHBoxLayout()
        self.test_b = QPushButton("Send a test to myself")
        self.out_b = QPushButton("Disconnect")
        ok = QPushButton("Done")
        self.test_b.clicked.connect(self.test)
        self.out_b.clicked.connect(self.sign_out)
        ok.clicked.connect(self.finish_up)
        for b in (self.test_b, self.out_b):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(ok)
        v.addLayout(bar)
        self.adv.toggled.connect(self.adv_w.setVisible)
        self.prov.currentIndexChanged.connect(self.refresh)
        self.addr.textChanged.connect(self.refresh)
        self.signed.connect(self._signed)
        self.conn.connect(self._connected)
        self.prog.connect(self.status.setText)
        self.refresh()
        if self.S.get("mail_provider") in ("gmail", "outlook") and self.mo.signed_in(self.S, self.S.get("mail_provider")):
            self.status.setText("Connected with %s. Mail goes from %s." % ("Google" if self.S["mail_provider"] == "gmail" else "Microsoft", self.S.get("mail_address", "")))
        elif self.S.get("smtp_host") and self.S.get("mail_address"):
            self.status.setText("Connected. Mail goes from %s." % self.S["mail_address"])

    def key(self):
        return ("gmail", "outlook", "smtp")[self.prov.currentIndex()]

    def _domain(self):
        a = self.addr.text().strip().lower()
        return a.split("@")[1] if "@" in a else ""

    def refresh(self):
        import mail_autoconfig as ac
        d = self._domain()
        link = ac.APP_PASSWORD_DOMAINS.get(d)
        self.easy = d in ("gmail.com", "googlemail.com") and self.mo.configured(self.S, "gmail") and not self._pw_mode
        self.pwlink.setVisible(d in ("gmail.com", "googlemail.com") and self.mo.configured(self.S, "gmail"))
        self.pwlink.setText("Use an app password instead" if self.easy else "Back: sign in with Google instead")
        self.pw_lbl.setVisible(not self.easy)
        self.pw.setVisible(not self.easy)
        self.connect_b.setText("Sign in with Google" if self.easy else "Connect")
        self.gbtn.setVisible(bool(link) and not self.easy)
        if self.easy:
            self.hint.setText("Press the button. Google's own window opens: choose your account, type your password there and press Allow. "
                              "The first time Google may say the app is not verified: press Advanced, then Continue.")
        elif link:
            self.pw_lbl.setText("<b>App password</b> (not your normal password)")
            self.hint.setText("%s does not accept your normal password in other programs. Press the button below, sign in, make an app password "
                              "(Google asks for 2-step verification once) and paste the 16 letters here." % d.split(".")[0].title())
        else:
            self.pw_lbl.setText("<b>Your email password</b>")
            self.hint.setText("")
        k = self.key()
        oauth = k in ("gmail", "outlook")
        self.signbtn.setVisible(oauth)
        self.smtp.setVisible(k == "smtp")
        need = oauth and not self.mo.configured(self.S, k)
        self.setup.setVisible(need and self._show_setup)
        self.setup_btn.setVisible(need and not self._show_setup)
        if oauth:
            name = "Google" if k == "gmail" else "Microsoft"
            self.signbtn.setText("Sign in with " + name)
            self.signbtn.setEnabled(not need)
            P = self.mo.PROVIDERS[k]
            self.cid.setText(self.S.get(P["id"], ""))
            self.csec.setText(self.S.get(P["secret"], "") if P["secret"] else "")
            self.csec.setVisible(bool(P["secret"]))
            self.csec_lbl.setVisible(bool(P["secret"]))
            self.help.setText(
                "Someone sets this up once (about 10 minutes) and it then works for everybody. In Google Cloud Console: make a project, switch on the Gmail API, "
                "set up the consent screen and publish it, then create an OAuth client of type 'Desktop app'. Paste its Client ID and Client secret here."
                if k == "gmail" else
                "Someone sets this up once. In the Azure portal > App registrations: new registration (any account type), redirect URI 'Public client' "
                "http://localhost, API permission Mail.Send (delegated). Paste the Application (client) ID here.")

    def open_app_pw(self):
        import webbrowser
        import mail_autoconfig as ac
        webbrowser.open(ac.APP_PASSWORD_DOMAINS.get(self._domain(), "https://myaccount.google.com/apppasswords"))

    def _safe(self, sig, *a):
        try:
            if not self._closed:
                sig.emit(*a)
            elif sig is self.signed and a and a[0]:
                self.M.save_settings()      # signed in after the window was closed: still keep the link
        except RuntimeError:
            pass

    def _toggle_pw(self):
        self._pw_mode = not self._pw_mode
        self.refresh()

    def connect_now(self):
        import mail_autoconfig as ac
        addr, pw = self.addr.text().strip(), self.pw.text()
        if self.easy:
            if "@" not in addr:
                self.status.setText("Type your Gmail address first.")
                return
            self.prov.setCurrentIndex(0)
            self.sign_in()
            return
        if not addr or not pw:
            self.status.setText("Type your email address and password first.")
            return
        if self._domain() in ("gmail.com", "googlemail.com") and len(pw.replace(" ", "")) != 16:
            self.status.setText("That is not an app password. Gmail app passwords are 16 letters (shown in groups of four). Press the button above, "
                                "make one in your Google account, and paste it here instead of your normal password.")
            return
        self.connect_b.setEnabled(False)
        self.status.setText("Connecting...")

        def work():
            try:
                cfg = ac.detect(addr, pw.replace(" ", "") if self._domain() in ac.APP_PASSWORD_DOMAINS else pw, progress=lambda t: self._safe(self.prog, t))
                self._safe(self.conn, True, "", cfg)
            except Exception as e:
                self._safe(self.conn, False, str(e), None)
        threading.Thread(target=work, daemon=True).start()

    def _connected(self, ok, msg, cfg):
        self.connect_b.setEnabled(True)
        if not ok:
            self.status.setText("Could not connect: " + msg)
            return
        pw = self.pw.text()
        if "@" in self.addr.text() and self._domain() in ("gmail.com", "googlemail.com", "yahoo.com", "icloud.com", "me.com"):
            pw = pw.replace(" ", "")
        self.S.update(cfg)
        self.S.update({"mail_provider": "smtp", "mail_address": self.addr.text().strip(), "smtp_pass": pw, "smtp_from": self.addr.text().strip(),
                       "smtp_bcc_me": self.bcc.isChecked()})
        self.M.save_settings()
        self.host.setText(cfg["smtp_host"])
        self.status.setText("Connected (%s). You can send from the program now." % cfg["smtp_host"])

    def _open_setup(self):
        self._show_setup = True
        self.refresh()

    def _save_ids(self):
        k = self.key()
        if k in ("gmail", "outlook"):
            P = self.mo.PROVIDERS[k]
            if self.cid.text().strip():
                self.S[P["id"]] = self.cid.text().strip()
            if P["secret"] and self.csec.text().strip():
                self.S[P["secret"]] = self.csec.text().strip()

    def sign_in(self):
        self._save_ids()
        k = self.key()
        if not self.mo.configured(self.S, k):
            self.status.setText("Sign-in is not switched on yet.")
            return
        self.S["mail_provider"], self.S["mail_address"] = k, self.addr.text().strip()
        self.signbtn.setEnabled(False)
        self.status.setText("Your browser has opened. Sign in there, then come back here...")
        self.mo.sign_in_thread(self.S, k, self.addr.text().strip(), lambda ok, m: self._safe(self.signed, ok, m))

    def _signed(self, ok, msg):
        self.signbtn.setEnabled(True)
        if ok:
            if msg:
                self.S["mail_address"] = msg
                self.addr.setText(msg)
            self.M.save_settings()
            self.refresh()
            self.status.setText("Signed in as %s. You can send from the program now." % (msg or "your account"))
        else:
            self.status.setText("Could not sign in: " + msg)

    def sign_out(self):
        for k in ("gmail", "outlook"):
            self.mo.sign_out(self.S, k)
        self.S.update({"smtp_pass": "", "smtp_host": "", "mail_provider": ""})
        self.pw.setText("")
        self.M.save_settings()
        self.status.setText("Disconnected.")

    def _commit(self):
        self._save_ids()
        self.S["smtp_bcc_me"] = self.bcc.isChecked()
        if self.adv.isChecked() and self.key() == "smtp" and self.host.text().strip():
            self.S.update({"mail_provider": "smtp", "mail_address": self.addr.text().strip(), "smtp_host": self.host.text().strip(),
                           "smtp_port": self.port.value(), "smtp_security": self.sec.currentText(), "smtp_user": self.user.text().strip() or self.addr.text().strip(),
                           "smtp_pass": self.pw.text(), "smtp_from": self.addr.text().strip()})
        self.M.save_settings()

    def finish_up(self):
        self._commit()
        self.accept()

    def test(self):
        self._commit()
        try:
            addr = self.S.get("mail_address", "")
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = addr, addr, "Drawing register: test"
            m.set_content("This is a test from the drawing register. The email account works.")
            deliver(self.S, m)
            self.status.setText("Test sent to %s." % addr)
        except Exception as e:
            self.status.setText("Could not send: %s" % e)


def mail_ready(S):
    import mail_oauth
    k = S.get("mail_provider") or ("smtp" if S.get("smtp_host") else "")
    if k in ("gmail", "outlook"):
        return mail_oauth.signed_in(S, k)
    return bool(S.get("smtp_host") and S.get("mail_address") or S.get("smtp_host") and S.get("smtp_user"))


def deliver(S, m, bcc_me=False):
    """Send m through the chosen account. The copy to myself is a Bcc header (web services) or an extra recipient (mail server)."""
    import mail_oauth
    k = S.get("mail_provider") or "smtp"
    me = S.get("mail_address") or S.get("smtp_user") or ""
    if k in ("gmail", "outlook"):
        if bcc_me and me:
            m["Bcc"] = me
        mail_oauth.send(S, k, m)
        return
    c = {x: S.get(x, "") for x in ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_pass")}
    rc = [a for hdr in ("To", "Cc") for a in addresses(m[hdr] or "")] + ([me] if bcc_me and me else [])
    MailMixin._send_with_bcc(c, m, rc) if rc else smtp_send(c, m)


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


LIMIT_MB = 17.0      # raw size per email: mail adds about a third when it encodes attachments, and most servers stop at 20 to 25 MB

LEVELS = [("normal", 150, 75), ("strong", 110, 55)]


def shrink_pdf(src, dst, level=0):
    """A smaller copy of a PDF: pictures are scaled down to print-sheet quality and the file is cleaned and compressed."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    _n, dpi, q = LEVELS[min(level, len(LEVELS) - 1)]
    d = fitz.open(src)
    try:
        d.rewrite_images(dpi_threshold=dpi + 30, dpi_target=dpi, quality=q)
    except Exception:
        pass
    d.save(dst, garbage=4, deflate=True, clean=True)
    d.close()


def split_parts(files, limit_mb=LIMIT_MB):
    """Share the files over as few emails as possible, each under the limit (a file bigger than the limit goes alone)."""
    parts, sizes = [], []
    for p in sorted(files, key=lambda x: -os.path.getsize(x)):
        mb = os.path.getsize(p) / 1e6
        for i, used in enumerate(sizes):
            if used + mb <= limit_mb:
                parts[i].append(p)
                sizes[i] += mb
                break
        else:
            parts.append([p])
            sizes.append(mb)
    return parts


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
        self.size.setWordWrap(True)
        v.addWidget(self.size)
        sr = QHBoxLayout()
        self.shrink_b = QPushButton("Make the PDFs smaller")
        self.shrink_b.setToolTip("Makes smaller copies for the email (pictures are scaled down). Your own files are not changed.")
        self.shrink_b.clicked.connect(self.shrink)
        sr.addWidget(self.shrink_b)
        self.split_chk = QCheckBox("If it is still too big, send it in several emails")
        self.split_chk.setChecked(True)
        self.split_chk.toggled.connect(self._size)
        sr.addWidget(self.split_chk)
        sr.addStretch(1)
        v.addLayout(sr)
        self.level = 0
        self.tmp = tempfile.mkdtemp()
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

    def parts(self):
        fs = self.files()
        if not self.split_chk.isChecked() or sum(os.path.getsize(p) for p in fs) / 1e6 <= LIMIT_MB:
            return [fs]
        return split_parts(fs)

    def shrink(self):
        from PySide6.QtWidgets import QApplication
        lvl = min(self.level, len(LEVELS) - 1)
        self.shrink_b.setEnabled(False)
        before = sum(os.path.getsize(p) for p in self.files())
        for i, (it, p) in enumerate(self.items):
            if it.checkState() != Qt.CheckState.Checked or not p.lower().endswith(".pdf"):
                continue
            self.size.setText("Making smaller: %s ..." % os.path.basename(p))
            QApplication.processEvents()
            out = os.path.join(self.tmp, "%d_%d_%s" % (lvl, i, os.path.basename(p)))
            try:
                shrink_pdf(p, out, lvl)
                if os.path.getsize(out) < os.path.getsize(p):
                    it.setText("%s   (%.1f MB, made smaller)" % (os.path.basename(p), os.path.getsize(out) / 1e6))
                    self.items[i] = (it, out)
            except Exception:
                pass
        after = sum(os.path.getsize(p) for p in self.files())
        self.level += 1
        self.shrink_b.setText("Make them smaller still" if self.level < len(LEVELS) else "Smallest setting used")
        self.shrink_b.setEnabled(self.level < len(LEVELS))
        self._size()
        self.size.setText("%.1f MB before, %.1f MB now.  %s" % (before / 1e6, after / 1e6, self.size.text()))

    def _size(self, *_a):
        fs = self.files()
        mb = sum(os.path.getsize(p) for p in fs) / 1e6
        n = len(self.parts())
        txt = "%d files, %.1f MB." % (len(fs), mb)
        big = [os.path.basename(p) for p in fs if os.path.getsize(p) / 1e6 > LIMIT_MB]
        if big:
            txt += "  %s alone is over the limit: make the PDFs smaller, or untick it and send it separately." % big[0]
        elif mb > LIMIT_MB and n > 1:
            txt += "  That is too big for one email, so it will go as %d emails (part 1 of %d ...)." % (n, n)
        elif mb > LIMIT_MB:
            txt += "  That is too big for one email (most mail servers stop at 20 to 25 MB): make the PDFs smaller, or tick \"send it in several emails\"."
        self.size.setText(txt)

    def _go(self):
        if not addresses(self.to.text()):
            QMessageBox.information(self, "Drawing register", "Enter who it goes to.")
            return
        self.accept()


class LogMixin:
    """The orders-and-revisions log."""

    LOG_SIMPLE = ("group", "order", "text", "req_subject", "sent_date")

    def build_log(self):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        n = QLabel("Keep track of what the client ordered or asked to change, house by house. Add the line, attach the client's email as proof, "
                   "and when you send the drawings the rest is filled in for you.")
        n.setWordWrap(True)
        v.addWidget(n)
        bar = QHBoxLayout()
        for text, fn, bold in (("+ New order", lambda: self.add_log("Order"), True), ("+ Client change", lambda: self.add_log("Change"), True),
                               ("Attach the client's email...", self.attach_ref, False), ("Open that email", self.open_ref, False), ("Remove line", self.remove_log, False)):
            b = QPushButton(text)
            if bold:
                b.setStyleSheet("font-weight:700;")
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
        for i, wd in enumerate((150, 70, 40, 85, 110, 360, 130, 300, 85, 170, 85, 200, 80)):
            self.ltab.setColumnWidth(i, wd)
        self.ltab.itemChanged.connect(self._log_cell)
        v.addWidget(self.ltab, 1)
        self.log_all = QCheckBox("Show all details (rev, dates, who asked, sent to, status)")
        self.log_all.toggled.connect(self._log_columns)
        v.addWidget(self.log_all)
        self._log_columns()
        return w

    def _log_columns(self, *_a):
        full = self.log_all.isChecked()
        for i, k in enumerate(LOGK):
            self.ltab.setColumnHidden(i, not (full or k in self.LOG_SIMPLE))

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
        self.update_mail()

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
        self.update_mail()

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
    def _M(self):
        return sys.modules[type(self.host).__module__]

    def email_account(self):
        M = self._M()
        if not hasattr(M, "SETTINGS"):
            return None
        d = AccountDialog(M, self)
        _KEEP.append(d)          # a sign-in thread may still answer after the window is closed: never let the window be deleted under it
        del _KEEP[:-3]
        return d.exec()

    def send_mail(self):
        gi = self.groups_in_issue()
        if not gi:
            QMessageBox.information(self, "Drawing register", "Tick the drawings that go in this issue first.")
            return
        S = self._M().SETTINGS
        if not mail_ready(S):
            QMessageBox.information(self, "Drawing register", "First choose the email you send from (Gmail or Outlook) and sign in.")
            self.email_account()
            if not mail_ready(S):
                return
        if not getattr(self, "_mail_manual", False):
            self.write_mail()
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
        frm = S.get("mail_address") or S.get("smtp_from") or S.get("smtp_user")
        to, cc = addresses(dlg.to.text()), addresses(dlg.cc.text())
        parts = [p for p in dlg.parts() if p] or [[]]
        n = len(parts)
        msgs = []
        for i, files in enumerate(parts):
            m = EmailMessage()
            m["From"], m["To"] = frm, ", ".join(to)
            m["Subject"] = dlg.sub.text().strip() + ((" (part %d of %d)" % (i + 1, n)) if n > 1 else "")
            if cc:
                m["Cc"] = ", ".join(cc)
            if i == 0:
                m.set_content((("This issue is sent in %d emails because of the size. This is part 1.\n\n" % n) if n > 1 else "") + dlg.body.toPlainText())
            else:
                m.set_content("Part %d of %d of the drawing issue for %s.\n\nIn this email:\n%s\n" % (i + 1, n, self.project_name(), "\n".join("  - " + os.path.basename(p) for p in files)))
            for p in files:
                with open(p, "rb") as f:
                    m.add_attachment(f.read(), maintype="application", subtype="pdf" if p.lower().endswith(".pdf") else "octet-stream",
                                     filename=re.sub(r"^\d+_\d+_", "", os.path.basename(p)))
            msgs.append(m)
        bcc_me = bool(S.get("smtp_bcc_me", True))
        self.info["email"], self.info["cc"] = dlg.to.text().strip(), dlg.cc.text().strip()
        self._sending = {"to": ", ".join(to + cc), "subject": dlg.sub.text().strip(), "msg": msgs[0]}
        self.count.setText("Sending %d email%s..." % (n, "s" if n > 1 else ""))
        self.setEnabled(False)

        def work():
            done = 0
            try:
                for m in msgs:
                    deliver(S, m, bcc_me and done == 0)
                    done += 1
                self.mail_done.emit(True, "")
            except Exception as e:
                self.mail_done.emit(False, ("Email %d of %d failed (%d already sent): " % (done + 1, n, done) if n > 1 else "") + str(e))
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
