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
from PySide6.QtWidgets import (QWidget, QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

LOGK = ("group", "type", "rev", "date", "order", "text", "kinds", "by", "req_subject", "req_date", "req_from", "sent_date", "sent_to", "status", "by_name", "by_email", "sent_subject")
LOGC = ["House or block", "Type", "Rev", "Date", "Order number", "What was ordered or changed", "Kind of change", "Asked by", "The client's email", "Received",
        "From", "Sent to the client on", "Sent to", "Status", "Client name", "Client email", "Email that was sent"]
TYPES = ["Order", "Change", "Issue"]
KINDS = ["Minor changes", "Major changes", "Masters", "Final plans", "SDP"]
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


class EmailPreviewDialog(QDialog):
    """Two tabs: Edit (To, Cc, Subject and the text) and How it will look."""

    def __init__(self, page, to, cc, subject, body, attached):
        super().__init__(page)
        from PySide6.QtWidgets import QTabWidget, QTextBrowser
        self.setWindowTitle("Preview and edit the email")
        self.resize(780, 700)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        ed = QWidget()
        ev = QVBoxLayout(ed)
        f = QFormLayout()
        self.to, self.cc, self.sub = QLineEdit(to), QLineEdit(cc), QLineEdit(subject)
        try:
            import contacts
            contacts.attach(self.to, lambda: page._M())
            contacts.attach(self.cc, lambda: page._M())
        except Exception:
            pass
        f.addRow("To", self.to)
        f.addRow("Cc", self.cc)
        f.addRow("Subject", self.sub)
        ev.addLayout(f)
        self.body = QPlainTextEdit(body)
        ev.addWidget(self.body, 1)
        self.tabs.addTab(ed, "Edit")
        self.view = QTextBrowser()
        self.page = page
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QTextDocument
        try:
            self.view.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl("cid:mcplogo"), QImage.fromData(page.design_png()))
        except Exception:
            pass
        self.tabs.addTab(self.view, "How it will look")
        self.attached = attached
        self.tabs.currentChanged.connect(self._look)
        v.addWidget(self.tabs, 1)
        self.design_chk = QCheckBox("Send as a designed email (MCP look)")
        self.design_chk.setChecked(page.designed_on())
        self.design_chk.toggled.connect(lambda *_: self._look(self.tabs.currentIndex()))
        v.addWidget(self.design_chk)
        v.addWidget(QLabel(attached))
        bar = QHBoxLayout()
        bar.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use = QPushButton("Use this email")
        use.setStyleSheet("font-weight:700;")
        use.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(use)
        v.addLayout(bar)

    def values(self):
        return self.to.text().strip(), self.cc.text().strip(), self.sub.text().strip(), self.body.toPlainText()

    def _look(self, i):
        if i != 1:
            return
        import html
        to, cc, sub, body = self.values()
        if self.design_chk.isChecked():
            try:
                self.page.show_corners(self.view, self.page.design_html(sub, body, attached=self.attached, preview=True))
                return
            except Exception:
                pass
        h = ('<div style="font-family:Segoe UI,Arial; font-size:10pt;">'
             '<table cellspacing="0" cellpadding="3"><tr><td><b>To</b></td><td>%s</td></tr>%s<tr><td><b>Subject</b></td><td><b>%s</b></td></tr></table><hr>'
             '<div style="white-space:pre-wrap;">%s</div><hr><p style="color:#777;">%s</p></div>' %
             (html.escape(to or "(nobody yet: add their email)"), ("<tr><td><b>Cc</b></td><td>%s</td></tr>" % html.escape(cc)) if cc else "",
              html.escape(sub), html.escape(body), html.escape(self.attached)))
        self.view.setHtml(h)

SIGK = (("sig_name", "Your name", "Mouton Burger"), ("sig_role", "Your position", "Director"), ("sig_company", "Company", "MCP Architecture & Interiors"),
        ("sig_phone", "Phone", "082 000 0000"), ("sig_email", "Email", "name@company.co.za"), ("sig_web", "Website", ""), ("sig_address", "Address", ""))


def signature_text(S, fallback=""):
    """The email signature of the person using this program (each person fills in their own)."""
    g = lambda k: str(S.get(k, "") or "").strip()
    lines = [g("sig_name"), g("sig_role"), g("sig_company")]
    contact = " | ".join(x for x in (("Tel: " + g("sig_phone")) if g("sig_phone") else "", g("sig_email") or g("mail_address"), g("sig_web")) if x)
    lines += [contact, g("sig_address")]
    lines = [x for x in lines if x]
    return "\n".join(lines) if g("sig_name") or g("sig_company") else fallback


class SignatureDialog(QDialog):
    def __init__(self, M, parent=None):
        super().__init__(parent)
        self.M, self.S = M, M.SETTINGS
        self.setWindowTitle("My email signature")
        self.resize(520, 440)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Fill in your own details. They are added to the bottom of every register email you send from this computer."))
        f = QFormLayout()
        self.ed = {}
        for k, label, ph in SIGK:
            w = QLineEdit(str(self.S.get(k, "") or (self.S.get("mail_address", "") if k == "sig_email" else "")))
            w.setPlaceholderText(ph)
            w.textChanged.connect(self._prev)
            f.addRow(label, w)
            self.ed[k] = w
        v.addLayout(f)
        v.addWidget(QLabel("<b>How it will look</b>"))
        self.prev = QPlainTextEdit()
        self.prev.setReadOnly(True)
        v.addWidget(self.prev, 1)
        bar = QHBoxLayout()
        bar.addStretch(1)
        ok = QPushButton("Save")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(self.save)
        bar.addWidget(ok)
        v.addLayout(bar)
        self._prev()

    def _vals(self):
        return {k: w.text().strip() for k, w in self.ed.items()}

    def _prev(self, *_a):
        t = signature_text(dict(self._vals(), mail_address=self.S.get("mail_address", "")))
        self.prev.setPlainText("Regards,\n" + (t or "(type your name)"))

    def save(self):
        self.S.update(self._vals())
        self.M.save_settings()
        self.accept()


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
        self.resize(480, 300)
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
        self.reqbtn = QPushButton("Ask for access (opens an email to the person who manages the program)")
        self.reqbtn.setVisible(False)
        self.reqbtn.clicked.connect(self.ask_access)
        v.addWidget(self.reqbtn)
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
        if self.S.get("contacts_note") and self.S.get("mail_provider") == "gmail":
            self.status.setText(self.status.text() + "\nTo find your Gmail contacts when you type a name, press Sign in with Google once more and allow contacts.")

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
        self.pwlink.setVisible(False)
        self.adv.setVisible(False)
        self.bcc.setVisible(False)
        self.test_b.setVisible(False)
        self.out_b.setVisible(bool(mail_ready(self.S)))
        self.pwlink.setText("Use an app password instead" if self.easy else "Back: sign in with Google instead")
        self.pw_lbl.setVisible(not self.easy and bool(d))
        self.pw.setVisible(not self.easy and bool(d))
        self.connect_b.setText("Sign in with Google" if (self.easy or not d) else "Connect")
        self.connect_b.setVisible(True)
        self.gbtn.setVisible(bool(link) and not self.easy)
        if self.easy or not d:
            self.hint.setText("Type your Gmail address, then press the button. Google's own window opens: sign in there and press Allow.")
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

    def ask_access(self):
        import urllib.parse
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        admin = str(self.mo._bundled().get("admin_email", "") or "")
        me = self.addr.text().strip()
        q = urllib.parse.quote
        QDesktopServices.openUrl(QUrl("mailto:%s?subject=%s&body=%s" % (
            admin, q("Please approve my Gmail for the drawing register"),
            q("Please add this Gmail address so I can sign in to the drawing register:\n\n%s\n" % me))))

    def _toggle_pw(self):
        self._pw_mode = not self._pw_mode
        self.refresh()

    def connect_now(self):
        import mail_autoconfig as ac
        addr, pw = self.addr.text().strip(), self.pw.text()
        if not addr:
            self.status.setText("Type your email address first.")
            return
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
            try:
                import contacts
                contacts.refresh_async(self.M, force=True)
            except Exception:
                pass
            self.refresh()
            self.status.setText("Signed in as %s. You can send from the program now." % (msg or "your account"))
        elif "access_denied" in msg and self.S.get("mail_provider") == "gmail":
            self.status.setText("Google says this address is not approved for the program yet. Press the button below to ask for access; "
                                "once you are approved, press Sign in with Google again.")
            self.reqbtn.setVisible(True)
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
        try:
            self._commit()
        except Exception:
            pass
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
        try:
            import contacts
            contacts.attach(self.to, lambda: page._M())
            contacts.attach(self.cc, lambda: page._M())
        except Exception:
            pass
        f.addRow("To", self.to)
        f.addRow("Cc", self.cc)
        f.addRow("Subject", self.sub)
        v.addLayout(f)
        self.body = QPlainTextEdit(body)
        v.addWidget(self.body, 3)
        dr = QHBoxLayout()
        self.design_chk = QCheckBox("Send as a designed email (MCP look)")
        self.design_chk.setChecked(page.designed_on())
        dr.addWidget(self.design_chk)
        seeb = QPushButton("See how it looks")
        seeb.clicked.connect(lambda: page.show_design(self.sub.text(), self.body.toPlainText()))
        dr.addWidget(seeb)
        dr.addStretch(1)
        v.addLayout(dr)
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
        self._page = page
        self._rep = {}
        host = getattr(page, "host", None)
        if host is not None and hasattr(host, "_write_report_pdf"):
            rr = QHBoxLayout()
            rr.addWidget(QLabel("Also attach a report:"))
            for kind, label in (("lv", "Light & Ventilation"), ("xa", "Energy XA"), ("rd", "Rational design"), ("cov", "Coverage and FAR")):
                c = QCheckBox(label)
                c.setToolTip("Makes the report from the project that is open now and adds it to the attachments.")
                c.toggled.connect(lambda on, k=kind, l=label: self._report_toggled(k, l, on))
                rr.addWidget(c)
                self._rep_boxes = getattr(self, "_rep_boxes", {})
                self._rep_boxes[kind] = c
            rr.addStretch(1)
            v.addLayout(rr)
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
        for k, c in getattr(self, "_rep_boxes", {}).items():     # the ones ticked on the register page start ticked here
            pc = getattr(page, "rep_chk", {}).get(k)
            if pc is not None and pc.isChecked():
                c.setChecked(True)

    def _report_toggled(self, kind, label, on):
        """Make the report when it is ticked and put it in the attachment list; take it out again when unticked."""
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt as _Qt
        if not on:
            it = self._rep.pop(kind, None)
            if it is not None:
                self.items = [(i, p) for i, p in self.items if i is not it]
                self.att.takeItem(self.att.row(it))
                self._size()
            return
        host = self._page.host
        w, pre = {"lv": (host._write_report_pdf, host.run_check), "xa": (host._write_xa_pdf, host._run_xa),
                  "rd": (host._write_rd_pdf, host._run_xa_quiet), "cov": (host._write_cov_pdf, lambda: None)}[kind]
        proj = re.sub(r'[\\/:*?"<>|]+', "-", self._page.project_name() or "Project")
        path = os.path.join(self.tmp, "%s - %s report.pdf" % (proj, label))
        QApplication.setOverrideCursor(_Qt.CursorShape.WaitCursor)
        self.size.setText("Making the %s report ..." % label)
        QApplication.processEvents()
        try:
            pre()
            w(path)
            if not os.path.exists(path):
                raise RuntimeError("the report was not written")
        except Exception as e:
            QApplication.restoreOverrideCursor()
            sender = self.sender()
            if sender is not None:
                sender.blockSignals(True)
                sender.setChecked(False)
                sender.blockSignals(False)
            QMessageBox.information(self, "Drawing register", "The %s report could not be made: %s\n\nOpen that tab and check the project first." % (label, e))
            self._size()
            return
        QApplication.restoreOverrideCursor()
        it = QListWidgetItem("%s report (PDF)   (%.1f MB)" % (label, os.path.getsize(path) / 1e6))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked)
        self.att.addItem(it)
        self.items.append((it, path))
        self._rep[kind] = it
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

    LOG_SIMPLE = ("group", "order", "text", "kinds", "by_name", "by_email", "req_subject", "sent_subject")

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
                               ("Get changes from the drawings", self.changes_from_drawings, True), ("Attach the client's email...", self.attach_ref, False), ("Open the client's email", self.open_ref, False), ("Open the email I sent", self.open_sent, False), ("Remove line", self.remove_log, False)):
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
        for i, wd in enumerate((150, 70, 40, 85, 110, 360, 660, 130, 300, 85, 170, 85, 200, 80, 150, 200, 320)):
            self.ltab.setColumnWidth(i, wd)
        self.ltab.itemChanged.connect(self._log_cell)
        self.ltab.cellDoubleClicked.connect(lambda r, c: self.open_sent() if LOGK[c] == "sent_subject" else self.open_ref() if LOGK[c] == "req_subject" else None)
        v.addWidget(self.ltab, 1)
        self.log_all = QCheckBox("Show all details (rev, dates, who asked, sent to, status)")
        self.log_all.toggled.connect(self._log_columns)
        v.addWidget(self.log_all)
        self._log_columns()
        return w

    def _kinds_box(self, e):
        """Tick boxes for the kind of change: Minor changes, Major changes, Masters, Final plans, SDP."""
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 0, 4, 0)
        have = {x.strip() for x in str(e.get("kinds", "")).split(",") if x.strip()}
        for kname in KINDS:
            cb = QCheckBox(kname)
            cb.setChecked(kname in have)
            cb.toggled.connect(lambda _on, ent=e: self._kinds_changed(ent, w))
            h.addWidget(cb)
        h.addStretch(1)
        return w

    def _kinds_changed(self, ent, w):
        ent["kinds"] = ", ".join(cb.text() for cb in w.findChildren(QCheckBox) if cb.isChecked())
        self.update_mail()

    def _log_columns(self, *_a):
        full = self.log_all.isChecked()
        for i, k in enumerate(LOGK):
            self.ltab.setColumnHidden(i, not (full or k in self.LOG_SIMPLE))

    # ----- fill the log from the drawings' revision rows -----
    MAJOR = re.compile(r"\b(add|added|new|remov|delet|mov|reloc|redesign|re-?design|enlarg|resiz|extend|extension|re-?lay|stair|structur|wall|roof|window|door|room|bedroom|kitchen|bathroom|garage|floor|level|coverage|building line)", re.I)
    MINOR = re.compile(r"\b(dimension|dim\b|text|note|label|typo|spelling|annotation|correct|update|tidy|clarif|title ?block|scale|legend|symbol|hatch|tag)", re.I)

    def guess_kinds(self, rows_changed, new_rows, group):
        """Tick-box suggestions for one house or block: which kind of change it looks like."""
        kinds = []
        text = " ".join(str(x) for r in rows_changed + new_rows for x in (r.get("title", ""), r.get("no", ""), r.get("comment", ""), self._what(r), r.get("status", ""))) + " " + group
        low = text.lower()
        major = bool(new_rows) or len(rows_changed) >= 4 or any(self.MAJOR.search(self._what(r) or "") and not self.MINOR.search(self._what(r) or "") for r in rows_changed)
        kinds.append("Major changes" if major else "Minor changes")
        if new_rows or "master" in low:
            kinds.append("Masters")
        if re.search(r"\bfinal\b|for construction|approved|approval set", low) or any((r.get("status") or "").lower().startswith("final") for r in rows_changed + new_rows):
            kinds.append("Final plans")
        if re.search(r"\bsdp\b|site development", low):
            kinds.append("SDP")
        return [k for k in KINDS if k in kinds]

    def changes_from_drawings(self):
        """Orders and changes > Get changes from the drawings: one line per house or block with what the revision rows say changed, and the kind of change ticked as a suggestion."""
        if not self.history:
            QMessageBox.information(self, "Drawing register", "There is nothing to compare with yet. Record an issue first, or use More > Continue from an earlier issue I already sent.")
            return
        made = 0
        for name, rows in self.groups_in_issue():
            rev, new = [], []
            for r in rows:
                try:
                    labelled = [it for it in self.rev_items(r) if it[2].strip()]
                except Exception:
                    labelled = []
                if not labelled:
                    continue          # only drawings whose revision column says what changed
                kind, _t = self.change_of(r)
                if kind == "revised":
                    rev.append(r)
                elif kind == "new":
                    new.append(r)
            line = next((e for e in self.log if e.get("group") == name and not e.get("sent_date") and e.get("auto_text") is not None
                         and e.get("text") in ("", e.get("auto_text"))), None)
            if not (rev or new):
                if line is not None:      # an earlier automatic line that no longer has anything behind it
                    self.log.remove(line)
                continue
            rv_ = lambda r: (" (Rev %s)" % r["rev"]) if r.get("rev") else ""
            parts = ["%s %s%s: %s" % (r.get("no") or "-", r.get("title", ""), rv_(r), self._what(r)) for r in rev]
            parts += ["%s %s%s: NEW drawing, %s" % (r.get("no") or "-", r.get("title", ""), rv_(r), self._what(r)) for r in new]
            text = "\n".join(parts)          # one drawing per line
            kinds = ", ".join(self.guess_kinds(rev, new, name))
            if line is None:
                line = {k: "" for k in LOGK}
                line.update({"group": name, "type": "Change", "date": datetime.date.today().isoformat(), "status": "Draft", "req_path": "", "sent_path": "", "drawings": "",
                             "by_name": self.info.get("to", ""), "by_email": self.info.get("email", "")})
                self.log.append(line)
            line["text"], line["auto_text"] = text, text
            if not line.get("kinds") or line.get("kinds_auto") == line.get("kinds"):
                line["kinds"], line["kinds_auto"] = kinds, kinds
            made += 1
        self.refresh_log()
        if made:
            self.count.setText("%d change line%s made from the drawings. Check the ticked kind of change on each." % (made, "" if made == 1 else "s"))
            QMessageBox.information(self, "Drawing register", "%d change line%s made from the revision rows in the drawings.\n\n"
                                    "The kind of change is ticked as a suggestion: Major for new or reworked rooms and walls, Minor for dimensions and notes, Masters for new drawings, "
                                    "Final plans and SDP when the drawings say so. Change any of them." % (made, "" if made == 1 else "s"))
        else:
            QMessageBox.information(self, "Drawing register", "No drawing has a described change in its revision column since the last issue. Add the revised PDFs or press Re-read the PDFs first.")

    # ----- the memory: every issue that went out, with what changed -----
    @staticmethod
    def _long_date(d):
        try:
            return datetime.date.fromisoformat(d).strftime("%d %B %Y").lstrip("0")
        except Exception:
            return d or ""

    def build_history(self):
        from PySide6.QtWidgets import QSplitter, QTextBrowser, QWidget
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        n = QLabel("Every register that went out from this project, with the date, who it went to, and what changed since the one before. "
                   "It is kept in the project file, so it is here when you open the project again.")
        n.setWordWrap(True)
        v.addWidget(n)
        bar = QHBoxLayout()
        self.h_open_mail = QPushButton("Open the email that was sent")
        self.h_open_dir = QPushButton("Open the drawings folder")
        self.h_open_mail.clicked.connect(self._h_open_mail)
        self.h_open_dir.clicked.connect(self._h_open_dir)
        bar.addWidget(self.h_open_mail)
        bar.addWidget(self.h_open_dir)
        bar.addSpacing(18)
        self.h_add = QPushButton("Add an earlier issue (email, PDF or folder)...")
        self.h_add.setToolTip("Continue from a register that was sent before: pick the email you sent (.eml), its register PDF, or the folder of that revision's drawings, or type the revision and date. It is added to this list.")
        self.h_add.clicked.connect(self.continue_from_earlier)
        self.h_del = QPushButton("Delete selected")
        self.h_del.setToolTip("Takes the highlighted revision out of the list. The next register then compares with the revision before it.")
        self.h_del.clicked.connect(self._h_delete)
        self.h_clear = QPushButton("Start fresh (delete all)")
        self.h_clear.setToolTip("Clears the whole list so the next register is a first issue. Your drawings stay as they are.")
        self.h_clear.clicked.connect(self._h_clear)
        bar.addWidget(self.h_add)
        bar.addWidget(self.h_del)
        bar.addWidget(self.h_clear)
        bar.addStretch(1)
        v.addLayout(bar)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.htab = QTableWidget(0, 6)
        self.htab.setHorizontalHeaderLabels(["Revision", "Date", "Sent to", "Drawings", "Sheets changed", "Email subject"])
        self.htab.verticalHeader().setVisible(False)
        self.htab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.htab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.htab.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.htab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.htab.horizontalHeader().setStretchLastSection(True)
        for i, wd in enumerate((110, 190, 220, 80, 420, 300)):
            self.htab.setColumnWidth(i, wd)
        self.htab.itemSelectionChanged.connect(self._h_show)
        sp.addWidget(self.htab)
        self.hview = QTextBrowser()
        self.hview.setOpenLinks(False)
        sp.addWidget(self.hview)
        sp.setSizes([220, 500])
        v.addWidget(sp, 1)
        self._h_rows = []
        return w

    def refresh_history(self):
        if not hasattr(self, "htab"):
            return
        keep = self.htab.currentRow()
        hist = list(self.history)
        self._h_rows = list(reversed(hist))             # newest first
        t = self.htab
        t.blockSignals(True)
        t.setRowCount(len(self._h_rows))
        for i, h in enumerate(self._h_rows):
            sent = h.get("sent") or {}
            vals = ["Revision %s" % h.get("issue", ""), "%s%s" % (self._long_date(h.get("date", "")), (" " + h["time"]) if h.get("time") else ""),
                    sent.get("to") or "(recorded, not sent from here)", str(len(h.get("rows", {}))), self._h_where(h, hist), sent.get("subject", "")]
            for c, val in enumerate(vals):
                t.setItem(i, c, QTableWidgetItem(val))
        t.blockSignals(False)
        if self._h_rows:
            t.selectRow(min(max(keep, 0), len(self._h_rows) - 1))
            self._h_show()
        else:
            self.hview.setHtml("<p>Nothing has been sent from this project yet. When you send a register (or record one as issued), it is kept here.</p>")
        self._h_buttons()

    def _h_where(self, h, hist):
        """The sheets the changes were made on: '3 revised: 001 Ground Floor, 002 First Floor, ...' (the sheet numbers, not just a count)."""
        i = hist.index(h) if h in hist else -1
        sheets = []
        if h.get("groups"):
            for g in h["groups"]:
                for d in g.get("drawings", []):
                    if d.get("kind") in ("new", "revised"):
                        sheets.append((d.get("no", ""), d.get("title", ""), d.get("kind")))
        elif i > 0:
            new, rev = self._h_diff(hist[i - 1], h)
            sheets = [(r.get("no", ""), r.get("title", ""), "revised") for r in rev] + [(r.get("no", ""), r.get("title", ""), "new") for r in new]
        if not sheets:
            return h.get("summary") or self._h_summary(h, hist)
        if h.get("first"):
            return "First issue: all %d sheets" % len(h.get("rows", {}))
        txt = ", ".join(("%s %s" % (n, t)).strip() + (" (new)" if k == "new" else "") for n, t, k in sheets)
        return "%d sheet%s: %s" % (len(sheets), "" if len(sheets) == 1 else "s", txt)

    def _h_delete(self):
        h = self._h_current()
        if h is None:
            return
        if QMessageBox.question(self, "Sent and revisions", "Delete Revision %s (%s) from this list?\n\nThe next register will compare with the revision before it. "
                                "The email and the PDFs on your computer are not touched." % (h.get("issue", ""), self._long_date(h.get("date", "")))) != QMessageBox.StandardButton.Yes:
            return
        self.history = [x for x in self.history if x is not h]
        self._h_after_change()

    def _h_clear(self):
        if not self.history:
            return
        if QMessageBox.question(self, "Sent and revisions", "Delete all %d revisions from this list and start fresh?\n\nThe next register becomes a first issue. "
                                "Your drawings, emails and PDFs are not touched." % len(self.history)) != QMessageBox.StandardButton.Yes:
            return
        self.history = []
        self._h_after_change()

    def _h_after_change(self):
        """After revisions were removed: the next revision number follows the last one left, and the 'what changed' lines are worked out again."""
        last = self.history[-1] if self.history else None
        if last:
            try:
                self.info["issue_no"] = str(int(str(last.get("issue"))) + 1)
            except ValueError:
                self.info["issue_no"] = str(last.get("issue")) + "+"
        else:
            self.info["issue_no"] = "0"
        for g in self.groups:
            for x in g["rows"]:
                x["comment"] = x["auto"] = ""
                try:
                    self._merge(x, dict(x, comment=""))
                except Exception:
                    pass
        self._mail_manual = False
        try:
            self.mail.setPlainText("")
        except Exception:
            pass
        self.refresh()
        self.refresh_history()

    def _h_summary(self, h, hist):
        """A short line for an issue recorded without the full memory: compare its drawings with the issue before it."""
        i = hist.index(h) if h in hist else -1
        if i <= 0:
            return "First issue" if h.get("rows") else ""
        new, rev = self._h_diff(hist[i - 1], h)
        bits = []
        if rev:
            bits.append("%d revised" % len(rev))
        if new:
            bits.append("%d new" % len(new))
        return ", ".join(bits) or "No drawing changed"

    @staticmethod
    def _h_diff(prev, cur):
        p, c = prev.get("rows", {}), cur.get("rows", {})
        new = [c[k] for k in c if k not in p]
        rev = [c[k] for k in c if k in p and (c[k].get("rev") or "") != (p[k].get("rev") or "")]
        return new, rev

    def _h_current(self):
        r = self.htab.currentRow() if hasattr(self, "htab") else -1
        return self._h_rows[r] if 0 <= r < len(self._h_rows) else None

    def _h_buttons(self):
        h = self._h_current()
        p = ((h or {}).get("sent") or {}).get("path", "")
        self.h_open_mail.setEnabled(bool(p and os.path.exists(p)))
        self.h_open_dir.setEnabled(bool(self._h_folder(h)))

    def _h_folder(self, h):
        for g in (h or {}).get("groups", []):
            for d in g.get("drawings", []):
                p = d.get("path", "")
                if p and os.path.isdir(os.path.dirname(p)):
                    return os.path.dirname(p)
        return ""

    def _h_open_mail(self):
        h = self._h_current()
        p = ((h or {}).get("sent") or {}).get("path", "")
        if p and os.path.exists(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _h_open_dir(self):
        d = self._h_folder(self._h_current())
        if d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _h_show(self):
        h = self._h_current()
        self._h_buttons()
        if h is not None:
            self.hview.setHtml(self.history_html(h))

    def history_html(self, h):
        from html import escape as e
        RED = "#C8102E"
        hist = list(self.history)
        i = hist.index(h) if h in hist else -1
        prev = hist[i - 1] if i > 0 else None
        sent = h.get("sent") or {}
        out = ['<h2 style="margin-bottom:2px;">Revision %s <span style="font-size:11pt;font-weight:400;">&nbsp;%s%s</span></h2>' % (
            e(str(h.get("issue", ""))), e(self._long_date(h.get("date", ""))), (" at " + e(h["time"])) if h.get("time") else "")]
        if sent:
            out.append('<p><b>Sent to:</b> %s%s<br><b>Subject:</b> %s<br><b>Attached:</b> %s</p>' % (
                e(sent.get("to", "")), (" &nbsp;(cc %s)" % e(sent["cc"])) if sent.get("cc") else "", e(sent.get("subject", "")),
                e(", ".join(sent.get("files", [])) or "the drawing register and the drawing PDFs")))
        else:
            out.append('<p><i>Recorded in the project without an email from here (sent another way, or carried on from an earlier issue).</i></p>')
        out.append('<h3 style="color:%s;margin-bottom:2px;">What changed, by sheet%s</h3>' % (RED, (" (since revision %s)" % e(str(prev.get("issue", "")))) if prev else ""))
        groups = h.get("groups")
        shown = False
        if groups:
            for g in groups:
                ch = [d for d in g.get("drawings", []) if d.get("kind") in ("new", "revised")]
                if not ch:
                    continue
                shown = True
                if len(groups) > 1:
                    out.append('<p style="margin-bottom:0px;"><b>%s</b></p>' % e(g.get("name", "")))
                for d in ch:
                    tag = " (new drawing)" if d.get("kind") == "new" and not h.get("first") else ""
                    out.append('<p style="margin:6px 0 0 0;"><b>Sheet %s &nbsp;%s</b>%s%s</p>' % (e(d.get("no", "")), e(d.get("title", "")), (" &nbsp;(Revision %s)" % e(d["rev"])) if d.get("rev") else "", tag))
                    its = d.get("changes") or []
                    if its:
                        out.append("<ul style='margin-top:0px;'>%s</ul>" % "".join("<li>%s</li>" % e(x) for x in its))
        elif prev:
            new, rev = self._h_diff(prev, h)
            for r in rev:
                shown = True
                out.append("<p style='margin:4px 0 0 0;'><b>%s %s</b>: Revision %s to %s</p>" % (e(r.get("no", "")), e(r.get("title", "")), e(str(prev["rows"].get(next((k for k, v in h["rows"].items() if v is r), ""), {}).get("rev", "-"))), e(r.get("rev", "-"))))
            for r in new:
                shown = True
                out.append("<p style='margin:4px 0 0 0;'><b>%s %s</b>: new drawing</p>" % (e(r.get("no", "")), e(r.get("title", ""))))
        if h.get("first") or (not prev and not shown):
            out.append("<p>First issue of this project: all %d drawings were sent.</p>" % len(h.get("rows", {})))
        elif not shown:
            out.append("<p>No drawing changed.</p>")
        # the orders and changes of that day
        day = [x for x in self.log if x.get("sent_date") == h.get("date") and x.get("type") in ("Order", "Change") and x.get("text")]
        if day:
            out.append('<h3 style="color:%s;margin-bottom:2px;">Orders and changes that day</h3><ul style="margin-top:0px;">' % RED)
            for x in day:
                out.append("<li><b>%s</b>: %s%s%s</li>" % (e(x.get("group", "")), e((x.get("text") or "").replace("\n", " / ")),
                                                           (" [%s]" % e(x["kinds"])) if x.get("kinds") else "", (" (asked by %s)" % e(x["by_name"])) if x.get("by_name") else ""))
            out.append("</ul>")
        # the drawings in this revision
        rows = []
        for g in (groups or []):
            for d in g.get("drawings", []):
                rows.append((g.get("name", ""), d.get("no", ""), d.get("title", ""), d.get("rev", ""), (d.get("size", "") + " " + d.get("scale", "")).strip(), d.get("kind", "")))
        if not rows:
            rows = [("", r.get("no", ""), r.get("title", ""), r.get("rev", ""), "", "") for r in h.get("rows", {}).values()]
        if rows:
            out.append('<h3 style="color:%s;margin-bottom:2px;">The %d drawings in this revision</h3><table cellspacing="0" cellpadding="3" width="100%%">' % (RED, len(rows)))
            for gname, no, title, rv, sz, kind in rows:
                mark = {"new": " NEW", "revised": " CHANGED"}.get(kind, "")
                out.append("<tr><td width='60'>%s</td><td>%s</td><td width='70'>Rev %s</td><td width='110'>%s</td><td width='90'><b>%s</b></td></tr>" % (e(no), e(title), e(rv or "-"), e(sz), e(mark.strip())))
            out.append("</table>")
        if sent.get("body"):
            out.append('<h3 style="color:%s;margin-bottom:2px;">The email as it was sent</h3><pre style="font-family:Segoe UI,Arial;">%s</pre>' % (RED, e(sent["body"])))
        return "".join(out)

    def add_log(self, typ):
        e = {k: "" for k in LOGK}
        e.update({"group": self.groups[self.cur]["name"], "type": typ, "date": datetime.date.today().isoformat(), "status": "Draft",
                  "text": "New order" if typ == "Order" else "", "req_path": "", "sent_path": "", "drawings": "",
                  "by_name": self.info.get("to", ""), "by_email": self.info.get("email", "")})
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
        from email.utils import parseaddr
        nm, ad = parseaddr(ref["from"] or "")
        if nm or ad:
            e["by_name"], e["by_email"] = nm or e.get("by_name", ""), ad or e.get("by_email", "")
        if not e.get("order"):
            e["order"] = find_order_no(ref["subject"] + " " + ref["body"])
        if not e.get("text") or e["text"] == "New order":
            e["text"] = ref["subject"] or e.get("text") or "Change"
        low = (ref["subject"] + " " + ref["body"]).lower()
        if not e.get("by"):
            e["by"] = "Council request" if re.search(r"council|municip", low) else "Client request"
        self.refresh_log()

    def open_sent(self):
        r = self.ltab.currentRow()
        if 0 <= r < len(self.log):
            p = self.log[r].get("sent_path")
            if p and os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            else:
                QMessageBox.information(self, "Drawing register", "That line has no sent email yet. It is linked when you send the drawings from the program.")

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
                    it = QTableWidgetItem("" if k == "kinds" else str(e.get(k, "")))
                    if k == "kinds":
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
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
                t.setCellWidget(i, LOGK.index("kinds"), self._kinds_box(e))
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
            if not pend.get("by_name"):
                pend["by_name"] = self.info.get("to", "")
            if not pend.get("by_email"):
                pend["by_email"] = self.info.get("email", "")
            pend["drawings"] = "; ".join("%s Rev %s" % (r.get("no") or r.get("title", ""), r.get("rev") or "-") for r in items)
            if not pend.get("text") or pend["text"] == "New order":
                parts = ["%s %s" % (r.get("no") or r.get("title", ""), self._what(r)) for r in items if r.get("comment") or r.get("by") or self.rev_items(r)]
                pend["text"] = (pend.get("text") or "") + ("; ".join(parts) if parts else ("Drawings issued" if first else "Drawings revised"))
            pend["date"] = today
            if sent:
                pend["sent_date"], pend["sent_to"], pend["sent_subject"], pend["sent_path"] = today, sent["to"], sent["subject"], sent.get("path", "")
                if sent.get("path"):
                    pend["sent_subject"] = "%s  (%s)" % (sent["subject"], os.path.basename(sent["path"]))
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
                if x.get("by_name") or x.get("by_email"):
                    lines.append('<font color="#1E8CC8">%s%s</font>' % (e_(x.get("by_name", "")), ("<br>" + e_(x["by_email"])) if x.get("by_email") else ""))
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

    def design_png(self, dark=False):
        """The MCP logo as PNG bytes with a transparent background: black and red (for light mode, the default) or white and red (dark=True)."""
        import base64
        M = self._M()
        raw = base64.b64decode(M.LOGO_B64)
        if dark:
            return raw
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QColor, QImage
        im = QImage.fromData(raw, "PNG").convertToFormat(QImage.Format.Format_ARGB32)
        for y in range(im.height()):
            for x in range(im.width()):
                c = im.pixelColor(x, y)
                if c.alpha() and c.red() > 200 and c.green() > 200 and c.blue() > 200:
                    im.setPixelColor(x, y, QColor(17, 17, 17, c.alpha()))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        im.save(buf, "PNG")
        return bytes(buf.data())

    def show_corners(self, view, html_text):
        """Show the preview in a QTextBrowser, adding the little corner pictures that make the cards rounded."""
        import mail_design
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QTextDocument
        for name, png in mail_design.preview_resources():
            view.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), QImage.fromData(png))
        view.setHtml(html_text)

    def design_html(self, subject, body, src="cid:mcplogo", attached="", both=False, preview=False):
        import mail_design
        return mail_design.build(subject, body, logo_src=src, logo_dark_src=("cid:mcplogod" if both else ""), preview=preview, attached=attached, company=self._M().SETTINGS.get("sig_company") or "MCP Architecture & Interiors")

    def designed_on(self):
        try:
            return bool(self._M().SETTINGS.get("mail_designed", True))
        except Exception:
            return True

    def show_design(self, subject, body, attached=""):
        """A window showing the designed email."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QTextDocument
        from PySide6.QtWidgets import QTextBrowser
        d = QDialog(self)
        d.setWindowTitle("How the designed email will look")
        d.resize(760, 860)
        v = QVBoxLayout(d)
        tb = QTextBrowser()
        img = QImage.fromData(self.design_png())
        tb.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl("cid:mcplogo"), img)
        self.show_corners(tb, self.design_html(subject, body, attached=attached, preview=True))
        v.addWidget(tb, 1)
        v.addWidget(QLabel("This is a preview. The email arrives in light or dark mode to match the person's mail program."))
        b = QPushButton("Close")
        b.clicked.connect(d.accept)
        v.addWidget(b)
        d.exec()

    def preview_email(self):
        """Show the email as the client will get it, and let the person change anything before it is sent."""
        subj, body = self._mail_parts()
        d = EmailPreviewDialog(self, self.info.get("email", ""), self.info.get("cc", ""), subj, body, self.att_lbl.text())
        if d.exec():
            to, cc, subj, body = d.values()
            self.info["email"], self.info["cc"] = to, cc
            if "email" in self.f:
                self.f["email"].setText(to)
            if "cc" in self.f:
                self.f["cc"].setText(cc)
            self._mail_setting = True
            try:
                self.mail.setPlainText(("Subject: %s\n\n" % subj if subj else "") + body)
            finally:
                self._mail_setting = False
            self._mail_manual = True
            try:
                self._M().SETTINGS["mail_designed"] = bool(d.design_chk.isChecked())
            except Exception:
                pass

    def my_signature(self):
        M = self._M()
        if not hasattr(M, "SETTINGS"):
            return None
        r = SignatureDialog(M, self).exec()
        if r:
            self._mail_manual = False
            self.write_mail()
            self._sync_issuer()
        return r

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
        try:
            import contacts
            contacts.refresh_async(self._M())
        except Exception:
            pass
        if not signature_text(S) and not getattr(self, "_sig_asked", False):
            self._sig_asked = True
            if QMessageBox.question(self, "Drawing register", "Your name and details are not set up for the bottom of the email yet. Set up your signature now?") == QMessageBox.StandardButton.Yes:
                self.my_signature()
        if not getattr(self, "_mail_manual", False):
            self.write_mail()
        subj, body = self._mail_parts()
        tmp = tempfile.mkdtemp()
        pdf = os.path.join(tmp, re.sub(r'[\\/:*?"<>|]+', "-", "Drawing register - %s - revision %s.pdf" % (self.project_name(), self.info["issue_no"] or "0")))
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
            if i == 0 and dlg.design_chk.isChecked():
                try:
                    note = ("This issue is sent in %d emails because of the size. This is part 1." % n) if n > 1 else ""
                    m.add_alternative(self.design_html(dlg.sub.text().strip(), dlg.body.toPlainText(), attached=note, both=True), subtype="html")
                    m.get_payload()[1].add_related(self.design_png(), maintype="image", subtype="png", cid="<mcplogo>", filename="mcp-logo.png", disposition="inline")
                    m.get_payload()[1].add_related(self.design_png(True), maintype="image", subtype="png", cid="<mcplogod>", filename="mcp-logo-dark.png", disposition="inline")
                except Exception:
                    pass
            for p in files:
                with open(p, "rb") as f:
                    m.add_attachment(f.read(), maintype="application", subtype="pdf" if p.lower().endswith(".pdf") else "octet-stream",
                                     filename=re.sub(r"^\d+_\d+_", "", os.path.basename(p)))
            msgs.append(m)
        bcc_me = bool(S.get("smtp_bcc_me", True))
        S["mail_designed"] = bool(dlg.design_chk.isChecked())
        self._M().save_settings()
        self.info["email"], self.info["cc"] = dlg.to.text().strip(), dlg.cc.text().strip()
        self._sending = {"to": ", ".join(to + cc), "subject": dlg.sub.text().strip(), "msg": msgs[0], "body": dlg.body.toPlainText(),
                         "cc": ", ".join(cc), "to_only": ", ".join(to), "emails": n,
                         "files": [os.path.basename(p) for fl in parts for p in fl], "designed": bool(dlg.design_chk.isChecked())}
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
        self.mark_issued(sent={"to": s["to"], "subject": s["subject"], "path": path, "body": s.get("body", ""), "cc": s.get("cc", ""),
                               "files": s.get("files", []), "emails": s.get("emails", 1)}, ask=False)
        QMessageBox.information(self, "Drawing register", "Sent to %s.\nThe issue is recorded in the log; a copy of the email is saved with it." % s["to"])
