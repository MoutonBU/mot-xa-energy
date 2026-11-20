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

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QPoint
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QWidget, QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QStackedWidget, QScrollArea, QFrame, QSizePolicy)

LOGK = ("group", "priority", "type", "rev", "date", "order", "text", "extras", "kinds", "by", "req_subject", "req_date", "req_from", "sent_date", "sent_to", "status", "by_name", "by_email", "sent_subject")
LOGC = ["House or block", "Priority", "Type", "Rev", "Date", "Order number", "What was ordered or changed", "Extras the client wants", "Kind of change", "Asked by", "The client's email", "Received",
        "From", "Sent to the client on", "Sent to", "Status", "Client name", "Client email", "Email that was sent"]
TYPES = ["Order", "Change", "Issue"]
KINDS = ["Minor changes", "Major changes", "Masters", "Final plans", "SDP"]
PRIO = ["", "Urgent", "Asked again"]
NOT_SORTED = "Not sorted"
LSTAT = ["New", "Draft", "Final", "Issued", "Superseded"]
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
    lines = [g("sig_name"), g("sig_role"), g("sig_company") or "MCP Architecture & Interiors"]
    contact = " | ".join(x for x in (("Tel: " + g("sig_phone")) if g("sig_phone") else "", g("sig_email") or g("mail_address"), g("sig_web") or "www.mcparchitecture.co.za") if x)
    lines += [contact, g("sig_address")]
    lines = [x for x in lines if x]
    return "\n".join(lines) if g("sig_name") or g("sig_company") else fallback


class SignatureDialog(QDialog):
    """Your own details for the signature at the bottom of the register email. The background, logo and website are fixed;
    you type your name, position, phone and email and choose your photo."""

    FIELDS = (("sig_name", "Your name", "Mouton Burger"), ("sig_role", "Your position", "Director"),
              ("sig_phone", "Phone", "082 000 0000"), ("sig_email", "Email", "name@company.co.za"))

    def __init__(self, M, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer as _QT
        self.M, self.S = M, M.SETTINGS
        self.photo = str(self.S.get("sig_photo", "") or "")
        self._new_photo = ""
        self.setWindowTitle("My email signature")
        self.resize(780, 640)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Fill in your own details and choose your photo. The background, logo and website are the same for everyone. "
                           "This goes at the bottom of every register email you send from this computer."))
        f = QFormLayout()
        self.ed = {}
        for k, label, ph in self.FIELDS:
            w = QLineEdit(str(self.S.get(k, "") or (self.S.get("mail_address", "") if k == "sig_email" else "")))
            w.setPlaceholderText(ph)
            w.textChanged.connect(self._prev_soon)
            f.addRow(label, w)
            self.ed[k] = w
        v.addLayout(f)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("Your photo"))
        self.photo_btn = QPushButton("Choose my photo...")
        self.photo_btn.clicked.connect(self.choose_photo)
        pr.addWidget(self.photo_btn)
        self.photo_clear = QPushButton("Remove photo")
        self.photo_clear.clicked.connect(self.clear_photo)
        pr.addWidget(self.photo_clear)
        pr.addStretch(1)
        v.addLayout(pr)
        v.addWidget(QLabel("<b>How it will look</b>"))
        self.prev = QLabel()
        self.prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.prev, 1)
        self.note = QLabel("Use a head-and-shoulders photo with a plain background. It is cut to the slanted shape on the left.")
        self.note.setStyleSheet("color:gray;")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        bar = QHBoxLayout()
        bar.addStretch(1)
        ok = QPushButton("Save")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(self.save)
        bar.addWidget(ok)
        v.addLayout(bar)
        self._t = _QT(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self._prev)
        self._prev()

    def _vals(self):
        return {k: w.text().strip() for k, w in self.ed.items()}

    def _prev_soon(self, *_a):
        self._t.start(250)

    def _prev(self, *_a):
        import sig_banner
        from PySide6.QtGui import QPixmap
        d = dict(self._vals(), sig_photo=self.photo, mail_address=self.S.get("mail_address", ""))
        if not d.get("sig_name"):
            d["sig_name"] = "Your name"
        img = sig_banner.render(d)
        self.prev.setPixmap(QPixmap.fromImage(img).scaledToWidth(720, Qt.TransformationMode.SmoothTransformation))
        self.photo_clear.setEnabled(bool(self.photo))

    def choose_photo(self):
        p, _ = QFileDialog.getOpenFileName(self, "Your photo", "", "Pictures (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not p:
            return
        import sig_banner
        dest = os.path.join(self.M._user_data_dir(), "signature_photo.png")
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        except Exception:
            pass
        if not sig_banner.prepare_photo(p, dest):
            QMessageBox.information(self, "My email signature", "That picture could not be opened. Try a JPG or PNG.")
            return
        self.photo = self._new_photo = dest
        self._prev()

    def clear_photo(self):
        self.photo = ""
        self._prev()

    def save(self):
        self.S.update(self._vals())
        self.S["sig_photo"] = self.photo
        self.S.setdefault("sig_company", "MCP Architecture & Interiors")
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
    def __init__(self, page, subject, body, pdf_path, drawings, index_path=None):
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
        self.cc.setPlaceholderText("several people: separate the addresses with a comma or semicolon")
        self.cc.setToolTip("Add as many addresses as you like, separated by a comma or a semicolon: name@a.com, other@b.com")
        self.to.setPlaceholderText("several people: separate the addresses with a comma or semicolon")
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
        lk = QHBoxLayout()
        lk.addWidget(QLabel("Download link:"))
        self.link = QLineEdit()
        self.link.setPlaceholderText("Swiss Transfer, WeTransfer or other link, when the drawings are too big to email")
        self.link.setToolTip("Paste the link where the drawings can be downloaded. It is put in the email under the first paragraph.")
        lk.addWidget(self.link, 1)
        self.link_note = QLineEdit()
        self.link_note.setPlaceholderText("Expires / password (optional)")
        self.link_note.setMaximumWidth(210)
        lk.addWidget(self.link_note)
        self.link_only = QCheckBox("Do not attach the drawings")
        self.link_only.setToolTip("Unticks every drawing below; the register, sheet index and reports still go with the email.")
        self.link_only.toggled.connect(self._link_only)
        lk.addWidget(self.link_only)
        v.addLayout(lk)
        self._link_block = ""
        self._drawing_paths = set(drawings)
        self.link.editingFinished.connect(self._put_link)
        self.link_note.editingFinished.connect(self._put_link)
        v.addWidget(QLabel("Attachments (tick what goes):"))
        self.att = QListWidget()
        self.items = []
        for label, p in [("Drawing register (PDF)", pdf_path)] + ([("Sheet index (PDF)", index_path)] if index_path else []) + [(os.path.basename(x), x) for x in drawings]:
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
        self._auto_body = self.body.toPlainText()
        for k, c in getattr(self, "_rep_boxes", {}).items():     # the ones ticked on the register page start ticked here
            pc = getattr(page, "rep_chk", {}).get(k)
            if pc is not None and pc.isChecked():
                c.setChecked(True)

    def _report_toggled(self, kind, label, on):
        self._report_toggled2(kind, label, on)
        # keep the register page in step, so the email text and the register PDF list the same reports
        pc = getattr(self._page, "rep_chk", {}).get(kind)
        ok = (kind in self._rep) == bool(on)
        if pc is not None and ok and pc.isChecked() != bool(on):
            pc.setChecked(bool(on))
            if self.body.toPlainText() == getattr(self, "_auto_body", None):
                try:
                    sub, txt = self._page._mail_parts()
                    self.body.setPlainText(txt)
                    self._auto_body = self.body.toPlainText()
                except Exception:
                    pass

    def _report_toggled2(self, kind, label, on):
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

    def _put_link(self):
        """Put the download link in the email text, under the opening paragraph (replacing an earlier one)."""
        url = self.link.text().strip()
        txt = self.body.toPlainText()
        if self._link_block and self._link_block in txt:
            txt = txt.replace(self._link_block, "", 1)
        self._link_block = ""
        if url:
            note = self.link_note.text().strip()
            blk = "The drawings are too large to email. Download them here:\n%s%s\n\n" % (url, ("\n(%s)" % note) if note else "")
            k = txt.find("\n\n")
            k = txt.find("\n\n", k + 2) if k >= 0 else -1
            at = k + 2 if k >= 0 else len(txt)
            txt = txt[:at] + blk + txt[at:]
            self._link_block = blk
        self.body.setPlainText(txt)

    def _link_only(self, on):
        for it, p in self.items:
            if p in self._drawing_paths:
                it.setCheckState(Qt.CheckState.Unchecked if on else Qt.CheckState.Checked)

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


class InboxDialog(QDialog):
    """Watch the Gmail inbox: new emails whose subject has your words become order lines, one per house, flagged New."""
    signed = Signal(bool, str)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.M = host._M()
        self.S = self.M.SETTINGS
        import mail_oauth
        self.mo = mail_oauth
        self.setWindowTitle("Watch my Gmail inbox for orders")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        t = QLabel("The program looks at the <b>subjects</b> of your Gmail inbox (never the whole email) for order words and for the name and short codes of each of your areas "
                   "(for example Blue Hills, BH, BHE). Each email found is split into one order per house and added to the area's square marked <b>New</b>; a later email about a "
                   "house that already has its order is added to that order as a <b>change</b>. An estate that is not there yet gets its own square. "
                   "The program only reads; it never deletes or changes your mail.")
        t.setWordWrap(True)
        v.addWidget(t)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.allow = QPushButton("Allow Gmail reading (opens Google)")
        self.allow.setStyleSheet("font-weight:700;")
        self.allow.clicked.connect(self._allow)
        v.addWidget(self.allow)
        f = QFormLayout()
        self.words = QLineEdit(self.S.get("inbox_words", "order, orders, bestelling, bestellings"))
        self.words.setPlaceholderText("order, new order, bestelling")
        f.addRow("Extra subject words (optional)", self.words)
        self.secs = QSpinBox()
        self.secs.setRange(10, 600)
        self.secs.setSuffix(" seconds")
        self.secs.setValue(self._secs(self.S))
        f.addRow("Look every", self.secs)
        v.addLayout(f)
        self.on = QCheckBox("Watch my inbox while the program is open")
        self.on.setChecked(bool(self.S.get("inbox_on")))
        v.addWidget(self.on)
        self.old = QCheckBox("Also bring in the matching emails of the last 14 days (otherwise only emails that arrive from now on)")
        self.old.setChecked(False)
        v.addWidget(self.old)
        row = QHBoxLayout()
        row.addStretch(1)
        now = QPushButton("Save and check now")
        now.setStyleSheet("font-weight:700;")
        now.clicked.connect(self._save)
        cl = QPushButton("Close")
        cl.clicked.connect(self.reject)
        row.addWidget(now)
        row.addWidget(cl)
        v.addLayout(row)
        self.signed.connect(self._signed)
        self._refresh()

    @staticmethod
    def _secs(S):
        v = int(S.get("inbox_secs", 10) or 10)
        return 10 if v in (30, 60) else max(10, v)          # the earlier defaults (60 and 30 seconds) become 10

    def _refresh(self):
        mo, S = self.mo, self.S
        if not mo.configured(S, "gmail"):
            self.status.setText("Gmail sign-in is not set up in this program yet (Email account > Gmail).")
            self.allow.setEnabled(False)
        elif mo.signed_in(S, "gmail") and S.get("gmail_read"):
            self.status.setText("Gmail reading is allowed for %s." % (S.get("mail_address", "") or "your account"))
            self.allow.setText("Allow Gmail reading again")
        else:
            self.status.setText("Press the button, sign in with Google and press Allow. Google will say the program is not verified: press Advanced, then continue.")

    def _allow(self):
        self.allow.setEnabled(False)
        self.status.setText("Waiting for Google in your browser...")
        self.mo.sign_in_thread(self.S, "gmail", self.S.get("mail_address", ""), lambda ok, m: self.signed.emit(ok, m), extra_scope=self.mo.GMAIL_READ)

    def _signed(self, ok, msg):
        self.allow.setEnabled(True)
        if ok:
            if msg and not self.S.get("mail_address"):
                self.S["mail_address"] = msg
            self.M.save_settings()
        else:
            self.status.setText("Not allowed: %s" % msg)
            return
        self._refresh()

    def _save(self):
        S = self.S
        if self.on.isChecked() and not (self.mo.signed_in(S, "gmail") and S.get("gmail_read")):
            QMessageBox.information(self, "Gmail inbox", "Press Allow Gmail reading first.")
            return
        if self.on.isChecked() and not S.get("inbox_on") and not self.old.isChecked():
            S["inbox_baseline"] = True            # the first look only notes what is already there
        S["inbox_words"], S["inbox_secs"], S["inbox_on"] = self.words.text().strip() or "order, orders, bestelling, bestellings", self.secs.value(), self.on.isChecked()
        if self.old.isChecked():
            S["inbox_seen"] = []
            S.pop("inbox_baseline", None)
        self.M.save_settings()
        self.host._inbox_apply(now=True)
        self.accept()


def _gnorm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


class _ExtrasCell(QWidget):
    """Under a drop-down heading: the extras the client wants on this house (one per line, editable)."""

    def __init__(self, host, e, table):
        super().__init__()
        self.host, self.e, self.table = host, e, table
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(2)
        self.btn = QPushButton()
        self.btn.setFlat(True)
        self.btn.setStyleSheet("text-align:left;font-weight:700;")
        self.btn.clicked.connect(self._toggle)
        v.addWidget(self.btn)
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText("One extra per line")
        self.box.setPlainText("\n".join(LogMixin.extras_of(e)))
        self.box.textChanged.connect(self._edited)
        v.addWidget(self.box)
        self._show()

    def _show(self):
        n = len(LogMixin.extras_of(self.e))
        opened = id(self.e) not in self.host._extras_closed
        self.btn.setText(("\u25BE " if opened else "\u25B8 ") + ("Extras (%d)" % n if n else "Extras (none)"))
        self.box.setVisible(opened)
        self.box.setFixedHeight(max(1, n) * 20 + 14)

    def _toggle(self):
        k = id(self.e)
        if k in self.host._extras_closed:
            self.host._extras_closed.discard(k)
        else:
            self.host._extras_closed.add(k)
        self._show()
        self.updateGeometry()
        self.table.resizeRowsToContents()

    def _edited(self):
        lines = [x.strip() for x in self.box.toPlainText().split("\n") if x.strip()]
        self.e["extras"] = "; ".join(lines)
        self.box.setFixedHeight(max(1, len(lines)) * 20 + 14)
        self._show_count()
        self.host.update_mail()

    def _show_count(self):
        n = len(LogMixin.extras_of(self.e))
        opened = id(self.e) not in self.host._extras_closed
        self.btn.setText(("\u25BE " if opened else "\u25B8 ") + ("Extras (%d)" % n if n else "Extras (none)"))


class AreaTile(QPushButton):
    """A large area square: the photo (if there is one) fills it, darkened, with the text centred over it."""
    def __init__(self, photo="", urgent=False, light=False):
        super().__init__()
        self._pm = None
        self._urgent, self._light = urgent, light
        if photo and os.path.exists(photo):
            from PySide6.QtGui import QPixmap
            pm = QPixmap(photo)
            self._pm = pm if not pm.isNull() else None

    def paintEvent(self, ev):
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        from PySide6.QtCore import QRectF
        if self._pm is None:
            return super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        sc = self._pm.scaled(self.size() * self.devicePixelRatioF(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        sc.setDevicePixelRatio(self.devicePixelRatioF())
        dw, dh = sc.width() / self.devicePixelRatioF(), sc.height() / self.devicePixelRatioF()
        p.drawPixmap(int((self.width() - dw) / 2), int((self.height() - dh) / 2), sc)
        p.fillRect(self.rect(), QColor(0, 0, 0, 130 if not self.underMouse() else 95))
        p.setClipping(False)
        p.setPen(QPen(QColor("#d8132b") if (self._urgent or self.underMouse()) else QColor(255, 255, 255, 70), 2 if self._urgent else 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14, 14)


class OrderToast(QWidget):
    """The corner pop-up for new orders: MCP logo, the new orders by area and house, and a bright red look when something is urgent."""
    def __init__(self, rows, logo_png, on_open, urgent):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        from PySide6.QtGui import QPixmap
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._urgent, self._on_open, self._pulse = urgent, on_open, 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(400)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        lg = QLabel()
        pm = QPixmap()
        pm.loadFromData(logo_png, "PNG")
        lg.setPixmap(pm.scaledToHeight(44, Qt.TransformationMode.SmoothTransformation))
        top.addWidget(lg)
        n = sum(r["count"] for r in rows)
        c = sum(r.get("changes", 0) for r in rows)
        sub = ("%d new order%s" % (n, "" if n == 1 else "s") if n else "") + (" and " if n and c else "") + ("%d change%s" % (c, "" if c == 1 else "s") if c else "")
        t = QLabel("<div style='font-size:17px;font-weight:800;color:%s'>%s</div><div style='color:#aab0b8'>%s</div>" % (
            "#ff4d5e" if urgent else "#ffffff", "URGENT" if urgent else ("New orders" if n else "Client changes"), sub or "the client wrote again"))
        top.addWidget(t, 1)
        x = QPushButton("\u00d7")
        x.setFixedSize(26, 26)
        x.setStyleSheet("QPushButton{border:none;color:#aab0b8;font-size:20px;background:transparent;}QPushButton:hover{color:#ffffff;}")
        x.clicked.connect(self.close)
        top.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        for r in rows[:6]:
            lab = QLabel(self._row_html(r))
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.RichText)
            if r["urgent"]:
                lab.setStyleSheet("background:#ff1f3a;color:#ffffff;border-radius:8px;padding:7px 10px;")
            else:
                lab.setStyleSheet("background:#262a30;color:#eceef0;border-radius:8px;padding:7px 10px;")
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            v.addWidget(lab)
        if len(rows) > 6:
            more = QLabel("and %d more..." % (len(rows) - 6))
            more.setStyleSheet("color:#aab0b8;")
            v.addWidget(more)
        f = QLabel("Click to open the Orders")
        f.setStyleSheet("color:#8a919a;font-size:11px;")
        v.addWidget(f)
        self.adjustSize()
        if urgent:
            self._tm = QTimer(self)
            self._tm.timeout.connect(self._tick)
            self._tm.start(450)
        else:
            QTimer.singleShot(16000, self.close)

    @staticmethod
    def _row_html(r):
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;")
        tag = "<b>URGENT</b> &nbsp;" if r["urgent"] else ""
        cnt = (" &nbsp;<span style='opacity:.8'>%d lines</span>" % r["count"]) if r["count"] > 1 else ""
        if r.get("changes") and not r["count"]:
            cnt = " &nbsp;<span style='opacity:.8'>%d change%s</span>" % (r["changes"], "" if r["changes"] == 1 else "s")
        note = ("<br><span style='opacity:.85'>%s</span>" % esc(r["note"])) if r.get("note") else ""
        return "%s<b>%s</b> &nbsp;%s%s%s" % (tag, esc(r["group"]), esc(r["area"]), cnt, note)

    def _tick(self):
        self._pulse ^= 1
        self.update()

    def paintEvent(self, ev):
        from PySide6.QtGui import QPainter, QPen, QLinearGradient
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#2a0d12") if self._urgent else QColor("#1b1e23"))
        g.setColorAt(1, QColor("#16181c"))
        p.setBrush(g)
        p.setPen(QPen(QColor("#ff2a40" if (self._urgent and self._pulse) else "#d8132b") if self._urgent else QColor("#3a3f46"), 3 if self._urgent else 1.5))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff2a40" if self._urgent else "#d8132b"))
        p.drawRoundedRect(QRectF(3, 16, 5, self.height() - 32), 2.5, 2.5)

    def mousePressEvent(self, ev):
        try:
            self._on_open()
        finally:
            self.close()


class LogMixin:
    """The orders-and-revisions log."""

    LOG_SIMPLE = ("group", "priority", "order", "text", "extras", "kinds", "by_name", "by_email", "req_subject", "sent_subject")

    def build_log(self, kind="Order"):
        """One of the two lists: the client's orders, or the client's changes. They share the log behind them, so the email and the PDF still find everything."""
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        if not hasattr(self, "ltabs"):
            self.ltabs, self.lpages, self.lall = {}, {}, {}
            self._lgroup, self._ltiles, self._ltitle, self._lstack = {}, {}, {}, {}
            self._lidx, self._larea = {}, {}
        self._lgroup[kind] = None
        self._larea[kind] = None
        back = QHBoxLayout()
        bb = QPushButton("\u2039  All houses and blocks")
        bb.setStyleSheet("font-weight:700;")
        bb.clicked.connect(lambda _c=False, k=kind: self._close_group(k))
        ttl = QLabel("")
        ttl.setStyleSheet("font-size:16px;font-weight:700;")
        back.addWidget(bb)
        back.addWidget(ttl)
        back.addStretch(1)
        v.addLayout(back)
        self._ltitle[kind] = ttl
        if kind == "Order":
            note = "The orders the client placed, house by house. Add the line, attach the client's email as proof, and when you send the drawings the rest is filled in for you."
            btns = (("+ New order", lambda: self.add_log("Order"), True), ("Attach the client's email...", self.attach_ref, False), ("Open the client's email", self.open_ref, False),
                    ("Open the email I sent", self.open_sent, False), ("Remove line", self.remove_log, False))
        else:
            note = "The changes the client asked for, house by house. Add a change, or let the program make them from the revision rows of the drawings."
            btns = (("+ Client change", lambda: self.add_log("Change"), True), ("Get changes from the drawings", self.changes_from_drawings, True),
                    ("Attach the client's email...", self.attach_ref, False), ("Open the client's email", self.open_ref, False), ("Open the email I sent", self.open_sent, False),
                    ("Remove line", self.remove_log, False))
        n = QLabel(note)
        n.setWordWrap(True)
        v.addWidget(n)
        bar = QHBoxLayout()
        for text, fn, bold in btns:
            b = QPushButton(text)
            if bold:
                b.setStyleSheet("font-weight:700;")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)
        t = QTableWidget(0, len(LOGK))
        t.setHorizontalHeaderLabels(LOGC)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        t.horizontalHeader().setStretchLastSection(True)
        for i, wd in enumerate((150, 100, 70, 40, 85, 110, 330, 300, 660, 130, 300, 85, 170, 85, 200, 80, 150, 200, 320)):
            t.setColumnWidth(i, wd)
        t.itemChanged.connect(self._log_cell)
        t.cellDoubleClicked.connect(lambda r, c: self.open_sent() if LOGK[c] == "sent_subject" else self.open_ref() if LOGK[c] == "req_subject" else None)
        v.addWidget(t, 1)
        if kind == "Order":
            from PySide6.QtWidgets import QScrollArea as _SA
            ct = QLabel("Changes the client asked for on this house, newest first. Click a change to open it.")
            ct.setStyleSheet("font-size:14px;font-weight:700;padding-top:6px;")
            chrow = QHBoxLayout()
            chrow.addWidget(ct, 1)
            addc = QPushButton("+ Add a change")
            addc.setStyleSheet("font-weight:700;")
            addc.clicked.connect(self.add_order_change)
            chrow.addWidget(addc)
            v.addLayout(chrow)
            sa = _SA()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setMinimumHeight(170)
            sa.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
            hostw = QWidget()
            self._ch_lay = QVBoxLayout(hostw)
            self._ch_lay.setContentsMargins(0, 0, 0, 0)
            self._ch_lay.setSpacing(6)
            sa.setWidget(hostw)
            v.addWidget(sa, 2)
            self._ch_title = ct
        chk = QCheckBox("Show all details (rev, dates, who asked, sent to, status)")
        chk.toggled.connect(self._log_columns)
        v.addWidget(chk)
        self.ltabs[kind], self.lall[kind] = t, chk
        self._lrows = getattr(self, "_lrows", {})
        self._lrows[kind] = []
        self._log_columns()
        stack = QStackedWidget()
        if kind == "Order":
            stack.addWidget(self._area_page())
            self._lidx[kind] = {"areas": 0, "houses": 1, "detail": 2}
        else:
            self._lidx[kind] = {"houses": 0, "detail": 1}
        stack.addWidget(self._tile_page(kind))
        stack.addWidget(w)
        self.lpages[kind], self._lstack[kind] = stack, stack
        return stack

    # ----- watching the Gmail inbox for orders -----
    def _changes_of(self, group):
        """The changes that live inside this house's order (from emails or added by hand); the Client changes tab keeps the others (drawing revisions, blocks)."""
        return [c for c in self.log if c.get("type") == "Change" and c.get("of_order") and group and _gnorm(c.get("group")) == _gnorm(group)]

    def add_order_change(self):
        g = self._lgroup.get("Order")
        if not g:
            return
        from PySide6.QtWidgets import QPlainTextEdit
        d = QDialog(self)
        d.setWindowTitle("Add a change to %s" % g)
        d.setMinimumWidth(480)
        v = QVBoxLayout(d)
        v.addWidget(QLabel("What must be changed on %s?" % g))
        te = QPlainTextEdit()
        te.setFixedHeight(110)
        v.addWidget(te)
        ur = QCheckBox("Urgent")
        v.addWidget(ur)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Add the change")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(d.accept)
        cn = QPushButton("Cancel")
        cn.clicked.connect(d.reject)
        row.addWidget(ok)
        row.addWidget(cn)
        v.addLayout(row)
        if d.exec() != QDialog.DialogCode.Accepted or not te.toPlainText().strip():
            return
        order = next((x for x in self.log if x.get("type") == "Order" and x.get("group") == g), None)
        ce = {k: "" for k in LOGK}
        ce.update({"group": g, "type": "Change", "rev": str(1 + len(self._changes_of(g))), "date": datetime.date.today().isoformat(), "text": te.toPlainText().strip(),
                   "status": "Draft", "req_path": "", "sent_path": "", "drawings": "", "by_name": self.info.get("to", ""), "by_email": self.info.get("email", ""),
                   "area": (order or {}).get("area", ""), "priority": "Urgent" if ur.isChecked() else "", "of_order": True})
        self.log.append(ce)
        if ur.isChecked() and order:
            order["priority"] = "Urgent"
        if not hasattr(self, "_ch_open"):
            self._ch_open = set()
        self._ch_open.add(id(ce))
        self.refresh_log()

    def _rebuild_changes(self):
        lay = getattr(self, "_ch_lay", None)
        if lay is None:
            return
        while lay.count():
            it = lay.takeAt(0)
            w_ = it.widget()
            if w_ is not None:
                w_.setParent(None)
                w_.deleteLater()
        g = self._lgroup.get("Order")
        if not g:
            return
        chs = self._changes_of(g)
        self._ch_title.setText("Changes the client asked for on %s (%d)%s" % (g, len(chs), ", newest first. Click a change to open it." if chs else ": none yet. Follow-up emails about this house appear here."))
        if not hasattr(self, "_ch_open"):
            self._ch_open = set()
        from PySide6.QtWidgets import QPlainTextEdit, QToolButton
        for c in reversed(chs):
            card = QFrame()
            card.setStyleSheet("QFrame#chc{border:1px solid %s;border-radius:8px;}" % ("#d8132b" if self._is_urgent(c) else "#3a3f46"))
            card.setObjectName("chc")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(8, 6, 8, 6)
            cv.setSpacing(4)
            urg = self._is_urgent(c)
            first = str(c.get("text", "")).split("\n")[0][:90]
            head = QPushButton()
            head.setCheckable(True)
            head.setStyleSheet("QPushButton{border:none;background:transparent;text-align:left;font-weight:700;padding:4px;%s}" % ("color:#ff4d5e;" if urg else ""))
            when = "%s%s" % (c.get("req_date") or c.get("date", ""), (", " + c["by_name"]) if c.get("by_name") else "")
            head.setText("%s  Change %s   %s   %s%s%s" % ("\u25be" if id(c) in self._ch_open else "\u25b8", c.get("rev") or "-", when,
                                                    "URGENT   " if urg else "", ("NEW   " if c.get("status") == "New" else ""), first))
            head.setChecked(id(c) in self._ch_open)
            cv.addWidget(head)
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(4, 0, 4, 0)
            te = QPlainTextEdit(str(c.get("text", "")))
            te.setFixedHeight(84)
            te.textChanged.connect(lambda ent=c, w_=te: ent.__setitem__("text", w_.toPlainText()))
            bl.addWidget(te)
            if c.get("extras"):
                bl.addWidget(QLabel("Extras: " + str(c["extras"])))
            row = QHBoxLayout()
            if c.get("req_path") and os.path.exists(c["req_path"]):
                ob = QPushButton("Open the client's email")
                ob.clicked.connect(lambda _c=False, pth=c["req_path"]: QDesktopServices.openUrl(QUrl.fromLocalFile(pth)))
                row.addWidget(ob)
            if c.get("sent_date"):
                row.addWidget(QLabel("Sent to the client on %s" % c["sent_date"]))
            row.addStretch(1)
            db = QPushButton("Delete this change")
            db.clicked.connect(lambda _c=False, ent=c: self._delete_change(ent))
            row.addWidget(db)
            bl.addLayout(row)
            body.setVisible(id(c) in self._ch_open)
            cv.addWidget(body)

            def toggled(on, ent=c, b_=body, h_=head):
                if on:
                    self._ch_open.add(id(ent))
                    if ent.get("status") == "New":
                        ent["status"] = "Seen"
                else:
                    self._ch_open.discard(id(ent))
                b_.setVisible(on)
                h_.setText(h_.text().replace("\u25b8", "\u25be") if on else h_.text().replace("\u25be", "\u25b8"))
                h_.setText(h_.text().replace("NEW   ", "") if on else h_.text())
            head.toggled.connect(toggled)
            lay.addWidget(card)
        lay.addStretch(1)

    def _delete_change(self, ent):
        if QMessageBox.question(self, "Orders", "Delete this change?\n\nThis cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        self.log[:] = [x for x in self.log if x is not ent]
        self.refresh_log()

    def _inbox_setup(self):
        if getattr(self, "_inbox_timer", None) is not None:
            return                                   # set up once: a second set-up would make every email arrive twice
        self._inbox_busy = False
        self._inbox_timer = QTimer(self)
        self._inbox_timer.timeout.connect(self.inbox_check)
        self.inbox_done.connect(self._inbox_result, Qt.ConnectionType.UniqueConnection)
        QTimer.singleShot(4000, self._inbox_apply)

    @staticmethod
    def extras_of(e):
        return [x.strip() for x in str(e.get("extras", "") or "").split(";") if x.strip()]

    def _migrate_extras(self):
        """Older order lines have the extras inside the text (an Extras: line): move them to their own column."""
        for e in self.log:
            if e.get("extras") or "extras:" not in str(e.get("text", "")).lower():
                continue
            keep, ex = [], []
            for ln in str(e["text"]).split("\n"):
                m = re.match(r"\s*extras\s*:\s*(.*)$", ln, re.I)
                if m:
                    ex += [x.strip() for x in re.split(r"[;,]", m.group(1)) if x.strip() and x.strip().lower() != "none"]
                else:
                    keep.append(ln)
            e["text"], e["extras"] = "\n".join(keep).strip(), "; ".join(ex)

    @staticmethod
    def _order_key(e):
        """Two lines with the same key are the same order, whichever email it came in: same house, same wording after the first line, same extras."""
        def n(x):
            return re.sub(r"\s+", " ", re.sub(r"^\s*(\d{1,2}[.)]|[-*])\s*", "", str(x or ""))).strip().lower()
        lines = [n(x) for x in str(e.get("text", "")).split("\n") if x.strip()]
        body = lines[1:] if len(lines) > 1 else lines
        ex = sorted({n(x) for x in LogMixin.extras_of(e)})
        return (e.get("type", ""), n(e.get("group", "")), tuple(body), tuple(ex))

    @classmethod
    def _key_hash(cls, e):
        import hashlib
        return hashlib.sha1(repr(cls._order_key(e)).encode("utf-8")).hexdigest()[:16]

    def inbox_dedupe(self):
        """Removes copies of an order that came in more than once from the inbox (unsent lines only). Returns how many were removed."""
        seen, drop = set(), []
        for e in self.log:
            if e.get("type") != "Order" or e.get("sent_date") or not e.get("req_subject"):
                continue
            k = self._order_key(e)
            if k in seen:
                drop.append(e)
            seen.add(k)
        for e in drop:
            self.log.remove(e)
        return len(drop)

    def _chase(self, lines, urgent, alerts, it):
        """The client wrote again about an order that is already in the list: it moves up (urgent) or is marked as asked again."""
        for x in lines:
            x["chased"] = int(x.get("chased", 0) or 0) + 1
            if urgent:
                x["priority"] = "Urgent"
            elif not x.get("priority"):
                x["priority"] = "Asked again"
        if lines and urgent:
            alerts.append((lines[0].get("group", ""), it["subject"], "again"))

    def _order_toast(self, news, alerts):
        """The corner pop-up for orders that just came in (also when the program sits in the tray)."""
        rows, idx = [], {}
        for e in news:
            key = (self._area_of(e), e["group"])
            r = idx.get(key)
            if r is None:
                r = idx[key] = {"area": key[0], "group": key[1], "count": 0, "urgent": False, "note": ""}
                rows.append(r)
            r["count"] += 1
            r["urgent"] = r["urgent"] or e.get("priority") == "Urgent"
            if e.get("type") == "Change":
                r["count"] -= 1
                r["changes"] = r.get("changes", 0) + 1
                r["note"] = ("new change: " + str(e.get("text", "")).split("\n")[0][:70]) if not r["note"] else r["note"]
        for g, subj, how in alerts:
            if how in ("again", "change"):
                ue = next((x for x in self.log if x.get("group") == g and x.get("type") == "Order"), None)
                key = (self._area_of(ue) if ue else NOT_SORTED, g)
                r = idx.get(key)
                if r is None:
                    r = idx[key] = {"area": key[0], "group": g, "count": 0, "urgent": True, "note": ""}
                    rows.append(r)
                r["urgent"] = True
                r["note"] = r["note"] or "the client wrote again"
        if not rows:
            return
        rows.sort(key=lambda r: not r["urgent"])
        urgent = rows[0]["urgent"]
        first = rows[0]

        def open_it():
            try:
                w = self.window()
                w.showNormal()
                w.raise_()
                w.activateWindow()
                self.show_orders("Order")
                self._open_area(first["area"])
                self._open_group("Order", first["group"])
            except Exception:
                pass
        try:
            from PySide6.QtWidgets import QApplication
            old = getattr(self, "_toast", None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            t = OrderToast(rows, self.design_png(True), open_it, urgent)
            self._toast = t
            ag = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            end = QPoint(ag.right() - t.width() - 16, ag.bottom() - t.height() - 16)
            t.move(end.x() + 60, end.y())
            t.setWindowOpacity(0.0)
            t.show()
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
            a1 = QPropertyAnimation(t, b"pos", t)
            a1.setStartValue(QPoint(end.x() + 60, end.y()))
            a1.setEndValue(end)
            a1.setDuration(320)
            a1.setEasingCurve(QEasingCurve.Type.OutCubic)
            a2 = QPropertyAnimation(t, b"windowOpacity", t)
            a2.setStartValue(0.0)
            a2.setEndValue(1.0)
            a2.setDuration(320)
            grp = QParallelAnimationGroup(t)
            grp.addAnimation(a1)
            grp.addAnimation(a2)
            grp.start()
            t._anim = grp
            if urgent:
                QApplication.beep()
        except Exception:
            pass

    def _urgent_popup(self, alerts):
        from PySide6.QtWidgets import QApplication
        seen_, rows = set(), []
        for g, subj, how in alerts:
            if g in seen_:
                continue
            seen_.add(g)
            rows.append("%s  (%s: %s)" % (g, "the client wrote again" if how == "again" else "new urgent order", subj))
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Urgent order")
        box.setText("<b>URGENT</b> - the client needs attention on:<br><br>" + "<br>".join(x.replace("<", "&lt;") for x in rows) +
                    "<br><br>It is now at the top of the Orders list, marked Urgent.")
        op = box.addButton("Open the first one", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        first = next(iter(seen_))
        box.setModal(False)

        def clicked(b):
            if b is op:
                try:
                    self.show_orders("Order")
                    ue = next((x for x in self.log if x.get("group") == first and self._is_urgent(x)), None)
                    self._open_area(self._area_of(ue) if ue else NOT_SORTED)
                    self._open_group("Order", first)
                except Exception:
                    pass
        box.buttonClicked.connect(clicked)
        self._popups = getattr(self, "_popups", [])[-3:] + [box]
        box.show()
        box.raise_()
        try:
            QApplication.alert(self.window(), 0)
        except Exception:
            pass

    def show_orders(self, kind="Order"):
        """Opens the Orders tool (or the register's own page when the tool is not there) on the Orders or Client changes page."""
        op_ = getattr(self, "orders_page", None)
        if op_ is not None:
            self.host.main_tabs.setCurrentIndex(self.host.main_tabs.indexOf(op_))
            op_.sub.setCurrentIndex(op_.sub.indexOf(self.lpages[kind]))
        else:
            self.sub.setCurrentIndex(self.sub.indexOf(self.lpages[kind]))

    def inbox_check_now(self):
        self.inbox_check(manual=True)

    def inbox_dialog(self):
        InboxDialog(self, self).exec()

    def _inbox_apply(self, now=False):
        S = self._M().SETTINGS
        self._inbox_timer.stop()
        if self.inbox_dedupe():
            self.refresh_log()
        if S.get("inbox_on"):
            self._inbox_timer.start(InboxDialog._secs(S) * 1000)
            if now or True:
                self.inbox_check()
        self._inbox_label()

    def _inbox_label(self, extra=""):
        S = self._M().SETTINGS
        txt = ("Watching Gmail (every %d s)" % InboxDialog._secs(S)) if S.get("inbox_on") else "Not watching Gmail"
        self.inbox_lbl.setText(txt + (" - " + extra if extra else ""))

    def inbox_check(self, manual=False):
        M = self._M()
        S = M.SETTINGS
        try:
            import mail_oauth as mo
            allowed = bool(mo.signed_in(S, "gmail") and S.get("gmail_read") is not False)
        except Exception:
            allowed = False
        if manual and not allowed:
            self._inbox_label("press Watch my Gmail inbox for orders... and allow Gmail reading once")
            return
        if not (allowed and (S.get("inbox_on") or manual)) or self._inbox_busy:
            if manual and self._inbox_busy:
                self._inbox_label("still checking...")
            return
        if manual:
            self._inbox_label("checking...")
        self._inbox_busy = True
        words, seen, folder = self._search_words(), set(S.get("inbox_seen", [])), os.path.join(M._user_data_dir(), "inbox")

        def work():
            try:
                import mail_inbox
                self.inbox_done.emit(mail_inbox.fetch_new(S, words, seen, folder, stubs=bool(S.get("inbox_baseline"))), "")
            except Exception as ex:
                self.inbox_done.emit([], str(ex))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _derived_codes(name):
        """BH and BHE for Blue Hills; AL and ALE for Albertsdal: the initials (or the first two letters of a single name), with and without an E for extension."""
        words = [w for w in re.split(r"[^A-Za-z]+", LogMixin._area_base(name)) if w]
        if not words:
            return []
        base = "".join(w[0] for w in words).upper() if len(words) > 1 else words[0][:2].upper()
        return [base, base + "E"]

    def _area_codes(self, a):
        explicit = [c.strip().upper() for c in re.split(r"[,;\s]+", a.get("codes", "")) if c.strip()]
        return explicit + [c for c in self._derived_codes(a["name"]) if c not in explicit]

    def _search_words(self):
        """The subject words the Gmail search uses: your own words, the order words, and for every area its name, its email words and its short codes (BH, BHE...).
        Only the subject is searched, never the whole email."""
        S = self._M().SETTINGS
        words = [w.strip() for w in re.split(r"[,;\n]", S.get("inbox_words", "") or "") if w.strip()]
        words += ["order", "orders", "bestelling", "bestellings", "extension", "ext", "uitbreiding"]
        for a in self.areas:
            words += [a["name"], self._area_base(a["name"])] + [k.strip() for k in re.split(r"[,;\n]", a.get("keys", "")) if k.strip()] + self._area_codes(a)
        out = []
        for w in words:
            if w and w.lower() not in [x.lower() for x in out]:
                out.append(w)
        return ", ".join(out)

    def _learn_code(self, subject, area):
        """The short code at the start of a subject (BH, AD...) is remembered for the area it was filed in, so the next email with that code files itself."""
        import mail_inbox
        code = mail_inbox.subject_code(subject)
        a = next((x for x in self.areas if x["name"] == area), None) if area else None
        if not code or a is None:
            return
        codes = [c.strip().upper() for c in re.split(r"[,;\s]+", a.get("codes", "")) if c.strip()]
        if code.upper() not in codes:
            a["codes"] = ", ".join(codes + [code.upper()])

    def _process_email(self, it, st, force_area=None):
        """Takes one email from a client in: its orders go to the houses (or to the one order the house already has, as a change)."""
        import mail_inbox
        import hashlib
        from email.utils import parseaddr
        have, mem, alerts, news, houses = st["have"], st["mem"], st["alerts"], st["news"], st["houses"]
        nm, addr = parseaddr(it["from"])
        try:
            rd = short_date(parsedate_to_datetime(it["date"]).date().isoformat())
        except Exception:
            rd = it["date"][:16]
        urgent = mail_inbox.is_urgent(it["subject"], it["body"])
        took = False
        for o in mail_inbox.parse_orders(it["subject"], it["body"], houses, it.get("html", "")):
            grp = o["group"] or "Not sure which house"
            area = force_area if force_area is not None else self._area_for(it["subject"], it["body"], o["group"], o.get("area", ""))
            existing = [x for x in self.log if x.get("type") == "Order" and o["group"] and _gnorm(x.get("group")) == _gnorm(grp)]
            if existing and existing[0].get("area"):
                area = existing[0]["area"]
            e = {k: "" for k in LOGK}
            e.update({"group": existing[0]["group"] if existing else grp, "type": "Order", "date": datetime.date.today().isoformat(), "order": o["order"], "text": o["text"],
                      "extras": o.get("extras", ""), "status": "New", "kinds": o.get("kinds", ""), "req_subject": it["subject"], "req_date": rd, "req_from": it["from"],
                      "req_path": "", "sent_path": "", "drawings": "", "by_name": nm, "by_email": addr, "msg_id": it["id"], "area": area})
            k = self._order_key(e)
            kh = self._key_hash(e)
            if existing:
                # the house already has its one order: this is the client coming back about it
                ctext = mail_inbox.clean_change_text(o["text"] if len(str(o["text"]).split("\n")) > 1 or not it["body"].strip() else it["body"], e["group"])
                if not ctext and not e["extras"]:
                    self._chase(existing, urgent, alerts, it)       # "Stand 2037 is urgent": no new wording, only a reminder
                    took = True
                    continue
                ckey = ("change", _gnorm(e["group"]), re.sub(r"\s+", " ", (ctext + "|" + e["extras"]).lower()))
                ch = "c" + hashlib.sha1(repr(ckey).encode("utf-8")).hexdigest()[:15]
                if ch in mem or any(c.get("type") == "Change" and _gnorm(c.get("group")) == _gnorm(e["group"]) and re.sub(r"\s+", " ", (str(c.get("text", "")) + "|" + str(c.get("extras", ""))).lower()) == ckey[2]
                                    for c in self.log):
                    self._chase(existing, urgent, alerts, it)
                    took = True
                    continue
                ce = {k_: "" for k_ in LOGK}
                nrev = 1 + sum(1 for c in self.log if c.get("type") == "Change" and c.get("of_order") and _gnorm(c.get("group")) == _gnorm(e["group"]))
                ce.update({"group": e["group"], "type": "Change", "rev": str(nrev), "date": e["date"], "text": ctext or "(extras)", "extras": e["extras"], "status": "New",
                           "req_subject": it["subject"], "req_date": rd, "req_from": it["from"], "req_path": "", "sent_path": "", "drawings": "", "by_name": nm, "by_email": addr,
                           "msg_id": it["id"], "area": e["area"], "priority": "Urgent" if urgent else "", "of_order": True})
                self.log.append(ce)
                mem.append(ch)
                if urgent:
                    for x in existing:
                        x["priority"] = "Urgent"
                    alerts.append((e["group"], it["subject"], "change"))
                news.append(dict(ce, type="Change"))
                st["changes"] += 1
                took = True
                continue
            ordered, wanted = mail_inbox.split_changes(e["text"])
            if wanted and len([x for x in ordered.split("\n") if x.strip()]) >= 2:
                e["text"] = ordered                                   # the "change ..." lines go to the house's changes, not into the order
                k = self._order_key(e)
                kh = self._key_hash(e)
            else:
                wanted = ""
            if k in have or kh in mem:
                continue                                              # the same order came in before: only added once
            if urgent:
                e["priority"] = "Urgent"
                alerts.append((e["group"], it["subject"], "new"))
            news.append(e)
            have.add(k)
            mem.append(kh)
            self.log.append(e)
            st["made"] += 1
            took = True
            if wanted:
                ce = {k_: "" for k_ in LOGK}
                ce.update({"group": e["group"], "type": "Change", "rev": "1", "date": e["date"], "text": wanted, "status": "New", "req_subject": it["subject"], "req_date": rd,
                           "req_from": it["from"], "req_path": "", "sent_path": "", "drawings": "", "by_name": nm, "by_email": addr, "msg_id": it["id"], "area": e["area"],
                           "priority": "Urgent" if urgent else "", "of_order": True})
                self.log.append(ce)
                news.append(dict(ce, type="Change"))
                st["changes"] += 1
        if took:
            path = it.get("path", "")
            if not path:
                try:
                    path = mail_inbox.save_eml(st["folder"], it)
                except Exception:
                    path = ""
            for x in self.log:
                if x.get("msg_id") == it["id"] and not x.get("req_path"):
                    x["req_path"] = path
        return took

    def _inbox_result(self, items, err):
        self._inbox_busy = False
        M = self._M()
        S = M.SETTINGS
        now = datetime.datetime.now().strftime("%H:%M")
        if err:
            self._inbox_label("could not check at %s: %s" % (now, err))
            return
        import mail_inbox
        from email.utils import parseaddr
        base = S.pop("inbox_baseline", False)
        seen = list(S.get("inbox_seen", []))
        houses = [g["name"] for g in self.groups]
        for x in self.log:
            gx = x.get("group", "")
            if gx and gx != "Not sure which house" and gx not in houses:
                houses.append(gx)
        made = 0
        alerts, news = [], []
        have = {self._order_key(e) for e in self.log if e.get("type") == "Order"}
        mem = list(S.get("inbox_keys", []))
        have_ids = {e.get("msg_id") for e in self.log if e.get("msg_id")}
        folder = os.path.join(M._user_data_dir(), "inbox")
        st = {"made": 0, "changes": 0, "alerts": alerts, "news": news, "have": have, "mem": mem, "houses": houses, "folder": folder}
        for it in reversed(items):
            if it["id"] in seen or it["id"] in have_ids:
                continue
            seen.append(it["id"])
            if base:
                continue
            if mail_inbox.ROBOT.search(mail_inbox.sender_addr(it["from"])):
                continue
            self._process_email(it, st)
        made, changes_made = st["made"], st["changes"]
        S["inbox_seen"] = seen[-3000:]
        S["inbox_keys"] = mem[-3000:]
        M.save_settings()
        removed = self.inbox_dedupe()
        if made or removed or alerts or changes_made:
            self.refresh_log()
            self._order_toast(news, alerts)
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.alert(self.window(), 0)
            except Exception:
                pass
        self._inbox_label("checked %s%s" % (now, ((", %d new order%s" % (made, "" if made == 1 else "s")) + ((", %d change%s" % (changes_made, "" if changes_made == 1 else "s")) if changes_made else "")) if (made or changes_made) else ", nothing new") + "")

    # ----- areas: the large squares (Blue Hills, another estate...) that the houses and orders sit in -----
    @staticmethod
    def _area_of(e):
        return e.get("area") or NOT_SORTED

    @staticmethod
    def _area_base(name):
        """Blue Hills Ext 120 -> Blue Hills: the name without a trailing extension, phase or number."""
        return re.sub(r"[\s,\-]*(ext(ension)?\.?|phase|stage|fase)?\s*\d+\s*$", "", str(name or ""), flags=re.I).strip()

    def _match_area(self, name):
        """The existing area this name belongs to (same name, same name apart from Ext 120, or a near spelling such as Blue Heels), else None."""
        import difflib
        g, b = _gnorm(name), _gnorm(self._area_base(name))
        for a in self.areas:
            if _gnorm(a["name"]) == g or (b and _gnorm(self._area_base(a["name"])) == b):
                return a["name"]
        for a in self.areas:
            ab = _gnorm(self._area_base(a["name"]))
            if b and len(b) >= 5 and difflib.SequenceMatcher(None, b, ab).ratio() >= 0.75:
                return a["name"]
        return None

    def _ensure_area(self, name):
        got = self._match_area(name)
        if got:
            return got
        self.areas.append({"name": name.strip(), "keys": "", "codes": ", ".join(self._derived_codes(name))})
        return name.strip()

    _EXT_RX = re.compile(r"([A-Z][\w'\u2019-]+(?:[ \t]+[A-Z][\w'\u2019-]+){0,3})[ \t]*,?[ \t]*(?i:(?:ext(?:ension)?|uitbreiding|uitb)\b\.?(?:[ \t]*\d+)?|(?:phase|fase)[ \t]*\.?[ \t]*\d+)")
    _REV_RX = re.compile(r"(?i:ext(?:ension)?|uitbreiding)\.?[ \t]*\d+[ \t]*[-,:]?[ \t]*(?i:of|in|at|van)?[ \t]*([A-Z][\w'\u2019-]+(?:[ \t]+[A-Z][\w'\u2019-]+)?)")
    _LEAD = {"new", "order", "orders", "urgent", "re", "fwd", "fw", "for", "stand", "erf", "please", "hi", "dear", "dringend", "bestelling", "bestellings",
             "the", "from", "at", "in", "of", "to", "house", "houses", "list", "sheet"}

    def _area_from_text(self, text):
        """An estate name written as 'Albertsdal Ext 46' / 'Blue Hills Extension 120' in the text, without the number; "" when none."""
        rev = self._REV_RX.search(str(text))
        if rev and rev.group(1).lower() not in self._LEAD and not self._EXT_RX.search(str(text)):
            return rev.group(1)
        for m in self._EXT_RX.finditer(str(text)):
            words = m.group(1).split()
            while words and words[0].lower().strip(".,:-") in self._LEAD:
                words.pop(0)
            if words:
                return " ".join(words)
        return ""

    def _area_by_code(self, subject):
        """The area whose short code (BH, AD...) the subject starts with, or ''."""
        try:
            import mail_inbox
            code = mail_inbox.subject_code(subject)
        except Exception:
            return ""
        if code:
            for a in self.areas:
                if code.upper() in self._area_codes(a):
                    return a["name"]
        return ""

    def _area_for(self, subject, body, group, from_table=""):
        """The area (name, or "" for Not sorted) for an incoming order. In order: the Township column; an existing area whose name or email words appear in the subject
        or top of the email; an estate written like 'Albertsdal Ext 46' (a missing area is made for it); the area this house already sits in."""
        if from_table.strip():
            return self._ensure_area(from_table.strip())
        bycode = self._area_by_code(subject)
        if bycode:
            return bycode
        hay = _gnorm(str(subject) + " " + str(body)[:3000])
        for a in self.areas:
            keys = [a["name"], self._area_base(a["name"])] + [k for k in re.split(r"[,;\n]", a.get("keys", "")) if k.strip()]
            if any(len(_gnorm(k)) >= 4 and _gnorm(k) in hay for k in keys):
                return a["name"]
        found = self._area_from_text(subject) or self._area_from_text(str(body)[:3000])
        if found:
            return self._ensure_area(self._area_base(found) or found)
        same = Counter(self._area_of(x) for x in self.log if x.get("type") == "Order" and _gnorm(x.get("group")) == _gnorm(group) and x.get("area"))
        if same:
            return same.most_common(1)[0][0]
        return ""

    def _area_page(self):
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 6, 0, 0)
        n = QLabel("Each large square is an area or development (for example Blue Hills). Everything the client sends for that area goes into its square. "
                   "Add your own with New area; the program also makes a square when an order names a new township.")
        n.setWordWrap(True)
        v.addWidget(n)
        bar = QHBoxLayout()
        na = QPushButton("+ New area")
        na.setStyleSheet("font-weight:700;")
        na.clicked.connect(self.new_area)
        bar.addWidget(na)
        b = QPushButton("Watch my Gmail inbox for orders...")
        b.setStyleSheet("font-weight:700;")
        b.clicked.connect(self.inbox_dialog)
        self.inbox_btn = b
        bar.addWidget(b)
        cb_ = QPushButton("Check now")
        cb_.setStyleSheet("font-weight:700;")
        cb_.clicked.connect(lambda: self.inbox_check(manual=True))
        bar.addWidget(cb_)
        self.inbox_lbl = QLabel("")
        bar.addWidget(self.inbox_lbl)
        self._inbox_setup()
        da = QPushButton("Delete all orders...")
        da.clicked.connect(lambda: self.delete_all_log("Order"))
        bar.addWidget(da)
        bar.addStretch(1)
        v.addLayout(bar)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        host = QWidget()
        from PySide6.QtWidgets import QGridLayout
        gl = QGridLayout(host)
        gl.setContentsMargins(2, 4, 2, 4)
        gl.setSpacing(18)
        gl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sc.setWidget(host)
        v.addWidget(sc, 1)
        self._atiles = (host, gl, sc, [])
        sc.viewport().installEventFilter(self._area_filter())
        return pg

    def _area_filter(self):
        from PySide6.QtCore import QObject, QEvent

        class F(QObject):
            def eventFilter(_s, obj, ev):
                if ev.type() == QEvent.Type.Resize:
                    QTimer.singleShot(0, self._reflow_areas)
                return False
        f = F(self)
        self._tile_filters = getattr(self, "_tile_filters", []) + [f]
        return f

    def _reflow_areas(self):
        host, gl, sc, tiles = self._atiles
        while gl.count():
            gl.takeAt(0)
        cols = max(1, (sc.viewport().width() - 4) // 372)
        row = col = 0
        for w in tiles:
            if getattr(w, "_full", False):
                if col:
                    row, col = row + 1, 0
                gl.addWidget(w, row, 0, 1, cols)
                row, col = row + 1, 0
            else:
                gl.addWidget(w, row, col)
                col += 1
                if col >= cols:
                    row, col = row + 1, 0

    def _area_names(self):
        names = [a["name"] for a in self.areas]
        for e in self.log:
            if e.get("type") == "Order" and e.get("area") and e["area"] not in names:
                self.areas.append({"name": e["area"], "keys": "", "codes": ", ".join(self._derived_codes(e["area"]))})
                names.append(e["area"])
        if any(e.get("type") == "Order" and not e.get("area") for e in self.log):
            names.append(NOT_SORTED)
        return names

    def _rebuild_areas(self):
        host, gl, sc, tiles = self._atiles
        for b in tiles:
            gl.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        tiles.clear()
        lt = self._M().light()
        txt = "#1c1f23" if lt else "#eceef0"
        qss = ("QPushButton{border-radius:14px;border:1px solid %s;background:%s;}QPushButton:hover{border-color:#d8132b;}"
               % (("#c3c9d0", "#ffffff") if lt else ("#3a3f46", "#1f2125")))
        names = self._area_names()

        def stat(n_):
            ents = [e for e in self.log if e.get("type") == "Order" and self._area_of(e) == n_]
            return ents, sum(1 for e in ents if self._is_urgent(e))
        urg = [n_ for n_ in names if stat(n_)[1]]
        order = urg + [n_ for n_ in names if n_ not in urg]
        heads = {}
        if urg:
            heads[urg[0]] = "Priority"
            rest = next((n_ for n_ in order if n_ not in urg), None)
            if rest:
                heads[rest] = "All areas"
        for name in order:
            if name in heads:
                hl = QLabel(heads[name])
                hl.setStyleSheet("font-size:14px;font-weight:700;padding:6px 0 0 2px;%s" % ("color:#d8132b;" if heads[name] == "Priority" else ""))
                hl._full = True
                hl.setParent(host)
                hl.show()
                tiles.append(hl)
            ents, nurg = stat(name)
            houses = len({e.get("group") for e in ents})
            new = sum(1 for e in ents if e.get("status") == "New")
            lines = ["<b style='font-size:19px'>%s</b>" % name.replace("<", "&lt;"),
                     ("%d house%s, %d order%s" % (houses, "" if houses == 1 else "s", len(ents), "" if len(ents) == 1 else "s")) if ents else "nothing yet"]
            if nurg:
                lines.insert(1, "<b style='color:#ff4d5e'>URGENT</b>")
            if new:
                lines.append("<b style='color:#ff4d5e'>%d new</b>" % new)
            ar = next((a for a in self.areas if a["name"] == name), None)
            photo = (ar or {}).get("photo", "")
            btn = AreaTile(photo, bool(nurg), lt)
            btn.setFixedSize(350, 170)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            has_ph = btn._pm is not None
            if has_ph:
                btn.setStyleSheet("QPushButton{background:transparent;border:none;}")
            else:
                btn.setStyleSheet(qss + ("QPushButton{border:2px solid #d8132b;}" if nurg else "") + ("QPushButton{background:%s;}" % ("#ffe3e6" if lt else "#3a1b20") if nurg else ""))
            lab = QLabel("<br>".join(lines), btn)
            lab.setStyleSheet("background:transparent;border:none;color:%s;" % ("#ffffff" if has_ph else txt))
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lab.setGeometry(12, 8, 326, 154)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setWordWrap(True)
            if has_ph:
                from PySide6.QtWidgets import QGraphicsDropShadowEffect
                sh = QGraphicsDropShadowEffect(lab)
                sh.setBlurRadius(8)
                sh.setOffset(0, 1)
                sh.setColor(QColor(0, 0, 0, 220))
                lab.setGraphicsEffect(sh)
            btn.clicked.connect(lambda _c=False, n_=name: self._open_area(n_))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _p, n_=name, b_=btn: self._area_menu(n_, b_))
            tiles.append(btn)
        self._reflow_areas()

    def _open_area(self, name):
        self._larea["Order"] = name
        self._lgroup["Order"] = None
        self._area_title.setText(name)
        self.refresh_log()
        self._lstack["Order"].setCurrentIndex(self._lidx["Order"]["houses"])

    def _close_area(self):
        self._larea["Order"] = None
        self._lgroup["Order"] = None
        self._lstack["Order"].setCurrentIndex(0)
        self.refresh_log()

    def _area_menu(self, name, btn):
        from PySide6.QtWidgets import QMenu
        m = QMenu(btn)
        a1 = m.addAction("Open")
        a2 = m.addAction("Edit name and email words...") if name != NOT_SORTED else None
        ap = m.addAction("Set photo...") if name != NOT_SORTED else None
        ar = next((a for a in self.areas if a["name"] == name), None)
        ax = m.addAction("Remove photo") if (ar and ar.get("photo")) else None
        a3 = m.addAction("Delete this area and its orders...")
        pick = m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if ap is not None and pick is ap:
            self.set_area_photo(name)
            return
        if ax is not None and pick is ax:
            ar["photo"] = ""
            self.refresh_log()
            return
        if pick is a1:
            self._open_area(name)
        elif a2 is not None and pick is a2:
            self.edit_area(name)
        elif pick is a3:
            self.delete_area(name)

    def set_area_photo(self, name):
        a = next((x for x in self.areas if x["name"] == name), None)
        if a is None:
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Photo for %s" % name, "", "Pictures (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not fn:
            return
        from PySide6.QtGui import QImage
        im = QImage(fn)
        if im.isNull():
            QMessageBox.warning(self, "Orders", "That picture could not be opened.")
            return
        im = im.scaled(900, 440, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        d_ = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MCP_XA_Energy", "area_photos")
        os.makedirs(d_, exist_ok=True)
        out = os.path.join(d_, "%s_%d.jpg" % (re.sub(r"\W+", "_", name)[:40], int(datetime.datetime.now().timestamp())))
        if not im.save(out, "JPG", 88):
            QMessageBox.warning(self, "Orders", "The picture could not be saved.")
            return
        a["photo"] = out
        self.refresh_log()

    def _area_dialog(self, name="", keys="", codes=""):
        d = QDialog(self)
        d.setWindowTitle("Area")
        d.setMinimumWidth(460)
        v = QVBoxLayout(d)
        f = QFormLayout()
        nm = QLineEdit(name)
        nm.setPlaceholderText("for example Blue Hills Ext 120")
        kw = QLineEdit(keys)
        kw.setPlaceholderText("Blue Hills, Cosmo")
        cd = QLineEdit(codes)
        cd.setPlaceholderText("BH, BHE")
        f.addRow("Area name", nm)
        f.addRow("Words in the client's emails", kw)
        f.addRow("Short codes at the start of the subject", cd)
        v.addLayout(f)
        t = QLabel("An email whose subject or first lines have the area name (or one of these words) is put in this area. "
                   "An order table with a Township column is put in the area of that name.")
        t.setWordWrap(True)
        v.addWidget(t)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Save")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(d.accept)
        cn = QPushButton("Cancel")
        cn.clicked.connect(d.reject)
        row.addWidget(ok)
        row.addWidget(cn)
        v.addLayout(row)
        if d.exec() != QDialog.DialogCode.Accepted or not nm.text().strip():
            return None
        return nm.text().strip(), kw.text().strip(), cd.text().strip()

    def new_area(self):
        r = self._area_dialog()
        if r is None:
            return
        if self._match_area(r[0]) and _gnorm(self._match_area(r[0])) == _gnorm(r[0]):
            QMessageBox.information(self, "Orders", "There is already an area called %s." % r[0])
            return
        self.areas.append({"name": r[0], "keys": r[1], "codes": r[2]})
        self.refresh_log()
        if QMessageBox.question(self, "Orders", "Choose a photo for the %s square now?" % r[0]) == QMessageBox.StandardButton.Yes:
            self.set_area_photo(r[0])

    def edit_area(self, name):
        a = next((x for x in self.areas if x["name"] == name), None)
        if a is None:
            return
        r = self._area_dialog(a["name"], a.get("keys", ""), a.get("codes", ""))
        if r is None:
            return
        for e in self.log:
            if e.get("area") == name:
                e["area"] = r[0]
        a["name"], a["keys"], a["codes"] = r
        self.refresh_log()

    def delete_area(self, name):
        ents = [e for e in self.log if e.get("type") == "Order" and self._area_of(e) == name]
        if QMessageBox.question(self, "Orders", "Delete the area %s and its %d order%s?\n\nThis cannot be undone." % (name, len(ents), "" if len(ents) == 1 else "s")) != QMessageBox.StandardButton.Yes:
            return
        gone = {id(e) for e in ents}
        self.log[:] = [e for e in self.log if id(e) not in gone]
        self.areas[:] = [a for a in self.areas if a["name"] != name]
        self._close_area()

    def move_house(self, group):
        from PySide6.QtWidgets import QInputDialog
        cur = self._larea.get("Order")
        opts = [n for n in self._area_names() if n != cur] + ([NOT_SORTED] if cur != NOT_SORTED and NOT_SORTED not in self._area_names() else [])
        if not opts:
            return
        pick, ok = QInputDialog.getItem(self, "Move %s" % group, "Move %s and its orders to:" % group, opts, 0, False)
        if not ok:
            return
        for e in self.log:
            if e.get("type") == "Order" and e.get("group") == group and self._area_of(e) == cur:
                e["area"] = "" if pick == NOT_SORTED else pick
        for c in self._changes_of(group):
            c["area"] = "" if pick == NOT_SORTED else pick
        if pick != NOT_SORTED:
            for e in self.log:
                if e.get("group") == group and e.get("req_subject"):
                    self._learn_code(e["req_subject"], pick)
                    break
        self.refresh_log()

    def new_order(self):
        """Asks for the house (and the area when none is open) and starts an order line for it."""
        from PySide6.QtWidgets import QInputDialog
        area = self._larea.get("Order")
        if area is None:
            names = self._area_names() or [NOT_SORTED]
            area, ok = QInputDialog.getItem(self, "New order", "Area:", names, 0, False)
            if not ok:
                return
        house, ok = QInputDialog.getText(self, "New order", "House or stand (for example Stand 2037):")
        if not ok or not house.strip():
            return
        e = {k: "" for k in LOGK}
        e.update({"group": house.strip(), "area": "" if area == NOT_SORTED else area, "type": "Order", "date": datetime.date.today().isoformat(), "status": "Draft",
                  "text": "New order", "req_path": "", "sent_path": "", "drawings": "", "by_name": self.info.get("to", ""), "by_email": self.info.get("email", "")})
        self.log.append(e)
        self._larea["Order"] = area
        self._area_title.setText(area)
        self._lgroup["Order"] = None
        self.refresh_log()
        self._lstack["Order"].setCurrentIndex(self._lidx["Order"]["houses"])
        self._open_group("Order", house.strip())

    # ----- the house and block squares -----
    TILE_QSS = ("QPushButton{text-align:left;padding:10px 12px;border-radius:10px;border:1px solid palette(mid);background:palette(base);}"
                "QPushButton:hover{border-color:#d8132b;}")

    def _tile_page(self, kind):
        from flow_layout import FlowLayout
        pg = QWidget()
        v = QVBoxLayout(pg)
        v.setContentsMargins(0, 6, 0, 0)
        n = QLabel("Click a house or stand to open its orders." if kind == "Order" else "Click a house or block to open the changes the client asked for. Add a change inside it, or let the program make them from the revision rows of the drawings.")
        n.setWordWrap(True)
        v.addWidget(n)
        bar = QHBoxLayout()
        if kind == "Order":
            ab = QPushButton("\u2039  All areas")
            ab.setStyleSheet("font-weight:700;")
            ab.clicked.connect(self._close_area)
            bar.addWidget(ab)
            self._area_title = QLabel("")
            self._area_title.setStyleSheet("font-size:16px;font-weight:700;")
            bar.addWidget(self._area_title)
            nb = QPushButton("+ Add house / new order")
            nb.setStyleSheet("font-weight:700;")
            nb.clicked.connect(self.new_order)
            bar.addWidget(nb)
            da = QPushButton("Delete this area's orders...")
            da.clicked.connect(lambda: self.delete_all_log("Order", None))
            bar.addWidget(da)
        else:
            b = QPushButton("Get changes from the drawings")
            b.setStyleSheet("font-weight:700;")
            b.clicked.connect(self.changes_from_drawings)
            bar.addWidget(b)
            da = QPushButton("Delete all...")
            da.clicked.connect(lambda: self.delete_all_log(kind))
            bar.addWidget(da)
        bar.addStretch(1)
        v.addLayout(bar)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        host = QWidget()
        from PySide6.QtWidgets import QGridLayout
        gl = QGridLayout(host)
        gl.setContentsMargins(2, 4, 2, 4)
        gl.setSpacing(12)
        gl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sc.setWidget(host)
        v.addWidget(sc, 1)
        self._ltiles[kind] = (host, gl, sc, [])
        sc.viewport().installEventFilter(self._tile_filter(kind))
        return pg

    def _tile_filter(self, kind):
        from PySide6.QtCore import QObject, QEvent

        class F(QObject):
            def eventFilter(_s, obj, ev):
                if ev.type() == QEvent.Type.Resize:
                    QTimer.singleShot(0, lambda: self._reflow(kind))
                return False
        f = F(self)
        self._tile_filters = getattr(self, "_tile_filters", []) + [f]
        return f

    def _reflow(self, kind):
        host, gl, sc, tiles = self._ltiles[kind]
        while gl.count():
            gl.takeAt(0)
        cols = max(1, (sc.viewport().width() - 4) // 232)
        row = col = 0
        for w in tiles:
            if getattr(w, "_full", False):
                if col:
                    row, col = row + 1, 0
                gl.addWidget(w, row, 0, 1, cols)
                row, col = row + 1, 0
            else:
                gl.addWidget(w, row, col)
                col += 1
                if col >= cols:
                    row, col = row + 1, 0

    @staticmethod
    def _is_urgent(e):
        return e.get("priority") == "Urgent" and not e.get("sent_date")

    def _in_scope(self, e, kind):
        """The line belongs to this kind and, for orders, to the area that is open."""
        if self.log_kind(e) != kind:
            return False
        if kind == "Change" and e.get("of_order"):
            return False                      # a change that lives inside an order is shown in its house, not here
        if kind == "Order" and self._larea.get("Order") is not None:
            return self._area_of(e) == self._larea["Order"]
        return True

    def _tile_names(self, kind):
        if kind == "Order":
            names = []
        else:
            names = [g["name"] for g in self.groups]
        for e in self.log:
            g = e.get("group", "")
            if g and g not in names and self._in_scope(e, kind):
                names.append(g)
        urg = {e.get("group") for e in self.log if self._in_scope(e, kind) and self._is_urgent(e)}
        return [n for n in names if n in urg] + [n for n in names if n not in urg]          # houses with an urgent order come first

    def _rebuild_tiles(self, kind):
        host, gl, sc, tiles = self._ltiles[kind]
        for b in tiles:
            gl.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        tiles.clear()
        lt = self._M().light()
        txt = "#1c1f23" if lt else "#eceef0"
        qss = ("QPushButton{border-radius:10px;border:1px solid %s;background:%s;}QPushButton:hover{border-color:#d8132b;}"
               % (("#c3c9d0", "#ffffff") if lt else ("#3a3f46", "#1f2125")))
        names_ = self._tile_names(kind)
        urgent_names = [n_ for n_ in names_ if any(self._is_urgent(e) for e in self.log if e.get("group") == n_ and self._in_scope(e, kind))]
        heads = {}
        if urgent_names:
            heads[urgent_names[0]] = "Priority"
            first_rest = next((n_ for n_ in names_ if n_ not in urgent_names), None)
            if first_rest:
                heads[first_rest] = "All houses and blocks"
        for name in names_:
            if name in heads:
                hl = QLabel(heads[name])
                hl.setStyleSheet("font-size:14px;font-weight:700;padding:6px 0 0 2px;%s" % ("color:#d8132b;" if heads[name] == "Priority" else ""))
                hl._full = True
                hl.setParent(host)
                hl.show()
                tiles.append(hl)
            ents = [e for e in self.log if e.get("group") == name and self._in_scope(e, kind)]
            new = sum(1 for e in ents if e.get("status") == "New")
            open_ = sum(1 for e in ents if not e.get("sent_date"))
            last = max([str(e.get("date", "")) for e in ents] or [""])
            lines = ["<b style='font-size:14px'>%s</b>" % name.replace("<", "&lt;"),
                     ("%d %s" % (len(ents), ("order" if kind == "Order" else "change") + ("" if len(ents) == 1 else "s"))) if ents else "nothing yet"]
            if kind == "Order":
                chs = self._changes_of(name)
                if chs:
                    lines[1] += ", %d change%s" % (len(chs), "" if len(chs) == 1 else "s")
                    new += sum(1 for c in chs if c.get("status") == "New")
            urg = sum(1 for e in ents if self._is_urgent(e))
            asked = sum(1 for e in ents if e.get("priority") == "Asked again" and not e.get("sent_date"))
            if urg:
                lines.insert(1, "<b style='color:#ff4d5e'>URGENT</b>")
            elif asked:
                lines.insert(1, "<b style='color:#d8932f'>client asked again</b>")
            if new:
                lines.append("<b style='color:#ff4d5e'>%d new</b>" % new)
            elif open_:
                lines.append("%d not sent yet" % open_)
            elif last:
                lines.append("last: %s" % last)
            btn = QPushButton()
            btn.setFixedSize(220, 100)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(qss + ("QPushButton{border:2px solid #d8132b;}" if urg else "") + ("QPushButton{background:%s;}" % ("#ffe3e6" if lt else "#3a1b20") if urg else ""))
            lab = QLabel("<br>".join(lines), btn)
            lab.setStyleSheet("background:transparent;border:none;color:%s;" % txt)
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lab.setGeometry(12, 8, 196, 84)
            lab.setWordWrap(True)
            btn.clicked.connect(lambda _c=False, k=kind, n_=name: self._open_group(k, n_))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _p, k=kind, n_=name, b_=btn: self._tile_menu(k, n_, b_))
            tiles.append(btn)
        self._reflow(kind)

    def _tile_menu(self, kind, name, btn):
        from PySide6.QtWidgets import QMenu
        m = QMenu(btn)
        a1 = m.addAction("Open")
        a3 = m.addAction("Move to another area...") if kind == "Order" else None
        a2 = m.addAction("Delete all the %s of %s..." % ("orders" if kind == "Order" else "changes", name))
        pick = m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if pick is a1:
            self._open_group(kind, name)
        elif pick is a2:
            self.delete_all_log(kind, name)
        elif a3 is not None and pick is a3:
            self.move_house(name)

    def delete_all_log(self, kind, group=None):
        """Removes every order (or change) line, or only those of one house. Deleting all orders also makes the inbox watcher forget what it has read,
        so Check now brings the emails in again from the start."""
        what = "orders" if kind == "Order" else "changes"
        ents = [e for e in self.log if self._in_scope(e, kind) and (group is None or e.get("group") == group)]
        if not ents:
            QMessageBox.information(self, "Drawing register", "There are no %s to delete." % what)
            return
        sent = sum(1 for e in ents if e.get("sent_date"))
        txt = "Delete %d %s%s?%s\n\nThis cannot be undone." % (len(ents), what, (" of " + group) if group else "",
                                                                  ("\n%d of them were already sent to the client." % sent) if sent else "")
        if QMessageBox.question(self, "Drawing register", txt) != QMessageBox.StandardButton.Yes:
            return
        gone = {id(e) for e in ents}
        if kind == "Order":
            gs = {_gnorm(e.get("group")) for e in ents}
            gone |= {id(c) for c in self.log if c.get("type") == "Change" and c.get("msg_id") and _gnorm(c.get("group")) in gs}
        self.log[:] = [e for e in self.log if id(e) not in gone]
        if kind == "Order" and group is None and self._larea.get("Order") is None:
            S = self._M().SETTINGS
            S["inbox_seen"], S["inbox_keys"] = [], []
            self._M().save_settings()
        self._lgroup[kind] = None
        self._lstack[kind].setCurrentIndex(self._lidx[kind]["houses"] if (kind != "Order" or self._larea.get("Order") is not None) else 0)
        self.refresh_log()

    def _open_group(self, kind, name):
        self._lgroup[kind] = name
        self._ltitle[kind].setText(name)
        self.refresh_log()
        self._lstack[kind].setCurrentIndex(self._lidx[kind]["detail"])

    def _close_group(self, kind):
        self._lgroup[kind] = None
        self._lstack[kind].setCurrentIndex(self._lidx[kind]["houses"])
        self.refresh_log()

    @staticmethod
    def log_kind(e):
        return "Order" if e.get("type") == "Order" else "Change"

    def _cur_log(self):
        """(entry, kind) of the selected line in the tab that is open, or (None, None)."""
        kinds = list(self.ltabs)
        op_ = getattr(self, "orders_page", None)
        cur = (op_.sub if op_ is not None else self.sub).currentWidget() if hasattr(self, "sub") else None
        mine = [k for k in kinds if cur is not None and (self.lpages[k] is cur or self.lpages[k].isAncestorOf(cur))]
        for k in (mine or kinds):
            r = self.ltabs[k].currentRow()
            if 0 <= r < len(self._lrows.get(k, [])):
                return self._lrows[k][r], k
        return None, None

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
        for kind, t in getattr(self, "ltabs", {}).items():
            full = self.lall[kind].isChecked()
            for i, k in enumerate(LOGK):
                t.setColumnHidden(i, not (full or k in self.LOG_SIMPLE))

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
        import copy
        snap = copy.deepcopy(self.state())
        self.history = [x for x in self.history if x is not h]
        self._h_after_change()
        self._toast_undo("Revision %s taken out of the list. The next register compares with the one before it." % h.get("issue", ""), snap)

    def _h_clear(self):
        if not self.history:
            return
        import copy
        snap = copy.deepcopy(self.state())
        n = len(self.history)
        self.history = []
        self._h_after_change()
        self._toast_undo("All %d revisions taken out. The next register is a first issue." % n, snap)

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
                out.append("<li><b>%s</b>: %s%s%s</li>" % (e(x.get("group", "")), e(((x.get("text") or "") + ((" (extras: %s)" % "; ".join(LogMixin.extras_of(x))) if LogMixin.extras_of(x) else "")).replace("\n", " / ")),
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
        e.update({"group": (getattr(self, "_lgroup", {}).get(self.log_kind({"type": typ})) or self.groups[self.cur]["name"]), "type": typ,
                  "area": ((self._larea.get("Order") or "") if typ == "Order" and self._larea.get("Order") != NOT_SORTED else ""), "date": datetime.date.today().isoformat(), "status": "Draft",
                  "text": "New order" if typ == "Order" else "", "req_path": "", "sent_path": "", "drawings": "",
                  "by_name": self.info.get("to", ""), "by_email": self.info.get("email", "")})
        self.log.append(e)
        self.refresh_log()
        k = self.log_kind(e)
        self.ltabs[k].selectRow(len(self._lrows[k]) - 1)

    def remove_log(self):
        e, _k = self._cur_log()
        if e is not None and e in self.log:
            self.log.remove(e)
            self.refresh_log()

    def attach_ref(self):
        e, _k = self._cur_log()
        if e is None:
            QMessageBox.information(self, "Drawing register", "Add an order or a change first, select it, then attach the email.")
            return
        p, _ = QFileDialog.getOpenFileName(self, "The client's email (.eml, .msg, .pdf or a screenshot)", "", "Email or document (*.eml *.msg *.pdf *.png *.jpg *.jpeg *.txt);;All files (*)")
        if not p:
            return
        ref = read_reference(p)
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
        e, _k = self._cur_log()
        if e is not None:
            p = e.get("sent_path")
            if p and os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            else:
                QMessageBox.information(self, "Drawing register", "That line has no sent email yet. It is linked when you send the drawings from the program.")

    def open_ref(self):
        e, _k = self._cur_log()
        if e is not None:
            p = e.get("req_path") or e.get("sent_path")
            if p and os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _log_cell(self, it):
        t = it.tableWidget()
        kind = next((k for k, tt in self.ltabs.items() if tt is t), None)
        if self._busy or kind is None or not (0 <= it.row() < len(self._lrows.get(kind, []))):
            return
        self._lrows[kind][it.row()][LOGK[it.column()]] = it.text().strip()
        self.update_mail()

    def refresh_log(self):
        self._busy = True
        if not hasattr(self, "_extras_closed"):
            self._extras_closed = set()
        try:
            self._migrate_extras()
            for e_ in self.log:
                if e_.get("type") == "Change" and e_.get("msg_id") and "of_order" not in e_:
                    e_["of_order"] = True       # changes that came in by email belong to their order
            for kind, t in getattr(self, "ltabs", {}).items():
                keep_row = t.currentRow()
                gsel = self._lgroup.get(kind)
                ents = [e for e in self.log if self._in_scope(e, kind) and (gsel is None or e.get("group") == gsel)]
                ents.sort(key=lambda e: 0 if self._is_urgent(e) else 1)          # urgent ones on top
                self._lrows[kind] = ents
                t.setRowCount(0)
                t.setRowCount(len(ents))
                for i, e in enumerate(ents):
                    for c, k in enumerate(LOGK):
                        it = QTableWidgetItem("" if k in ("kinds", "extras") else str(e.get(k, "")))
                        if k in ("kinds", "extras"):
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        if k in ("req_subject",) and e.get("req_path"):
                            it.setToolTip(e["req_path"])
                        if self._is_urgent(e):
                            it.setBackground(QColor(216, 19, 43, 70))
                        elif e.get("status") == "Draft":
                            it.setBackground(QColor(120, 90, 20, 90))
                        t.setItem(i, c, it)
                    for k, vals in (("group", [g["name"] for g in self.groups]), ("priority", PRIO), ("type", TYPES), ("by", None), ("status", LSTAT)):
                        cb = QComboBox()
                        cb.setEditable(True)
                        from register import BYS
                        cb.addItems(vals if vals is not None else BYS)
                        cb.setCurrentText(str(e.get(k, "")))
                        cb.currentTextChanged.connect(lambda tx, ent=e, kk=k: ent.__setitem__(kk, tx))
                        if k == "priority":
                            cb.currentTextChanged.connect(lambda _tx: QTimer.singleShot(0, self.refresh_log))
                        t.setCellWidget(i, LOGK.index(k), cb)
                    t.setCellWidget(i, LOGK.index("kinds"), self._kinds_box(e))
                    t.setCellWidget(i, LOGK.index("extras"), _ExtrasCell(self, e, t))
                t.resizeRowsToContents()
                if 0 <= keep_row < len(ents):
                    t.selectRow(keep_row)
                self._rebuild_tiles(kind)
            self._rebuild_changes()
            self._rebuild_areas()
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
    def log_html(self, e_, td, th, RED, only=None):
        ents_all = [x for x in self.log if only is None or self.log_kind(x) == only]
        if not ents_all:
            return ""
        out = ['<h3 style="color:%s;margin-bottom:3px;">%s</h3>' % (RED, {"Order": "Orders", "Change": "Client changes"}.get(only, "Orders and revisions"))]
        names = [g["name"] for g in self.groups] + sorted({x.get("group") for x in self.log} - {g["name"] for g in self.groups})
        body = ""
        for name in names:
            ents = [x for x in ents_all if x.get("group") == name]
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
        if self.sig_picture_on():
            try:
                view.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl("cid:mcpsig"), QImage.fromData(self.sig_bytes()))
            except Exception:
                pass
        view._corner_html = html_text
        self._fit_sig(view)
        if not getattr(view, "_sig_fit_on", False):
            view._sig_fit_on = True
            from PySide6.QtCore import QObject, QEvent, QTimer
            page = self

            class _F(QObject):
                def eventFilter(s, o, e):
                    if e.type() == QEvent.Type.Resize and getattr(view, "_corner_html", None):
                        if not hasattr(view, "_sig_t"):
                            view._sig_t = QTimer(view)
                            view._sig_t.setSingleShot(True)
                            view._sig_t.timeout.connect(lambda: page._fit_sig(view))
                        view._sig_t.start(120)
                    return False
            view._sig_f = _F(view)
            view.viewport().installEventFilter(view._sig_f)

    def _fit_sig(self, view):
        """Make the signature banner as wide as the cards (it follows the preview width)."""
        h = view._corner_html
        if 'alt="Signature"' in h:
            w = max(260, view.viewport().width() - 32)
            if w < 420:
                # a small window (like a phone): plain readable text instead of the picture
                import re, html as _h
                import sig_banner
                lt = sig_banner.link_text(self._M().SETTINGS)
                card = ('<table width="100%%" cellpadding="12" cellspacing="0" bgcolor="#F1F1F1"><tr><td>'
                        '<span style="font-size:15pt;font-weight:700;color:#111111;">%s</span><br>'
                        '<span style="font-size:10pt;font-weight:700;color:#D1121F;">%s</span><br><br>'
                        '<span style="font-size:11pt;color:#111111;">%s<br>%s<br>www.mcparchitecture.co.za</span></td></tr></table>'
                        % (_h.escape(lt["name"]), _h.escape(lt["role"]), _h.escape(lt["phone"]), _h.escape(lt["email"])))
                h = re.sub(r'<img src="cid:mcpsig"[^>]*>', lambda m_: card, h, count=1)
            else:
                h = h.replace('width="600" alt="Signature"', 'width="%d" alt="Signature"' % w)
        sb = view.verticalScrollBar().value()
        view.setHtml(h)
        view.verticalScrollBar().setValue(sb)

    def sig_picture_on(self):
        try:
            import sig_banner
            return sig_banner.available(self._M().SETTINGS)
        except Exception:
            return False

    def sig_parts(self):
        import sig_banner
        if not hasattr(self, "_sig_cache") or self._sig_cache[0] != str(self._sig_key()):
            rows, jp = sig_banner.slices(self._M().SETTINGS)
            self._sig_cache = (str(self._sig_key()), rows, jp)
        return self._sig_cache[1], sig_banner.link_text(self._M().SETTINGS)

    def _sig_key(self):
        S = self._M().SETTINGS
        return tuple(str(S.get(k, "")) for k in ("sig_name", "sig_role", "sig_phone", "sig_email", "mail_address", "sig_photo"))

    def sig_bytes(self):
        import sig_banner
        return sig_banner.jpeg_bytes(self._M().SETTINGS)

    def design_html(self, subject, body, src="cid:mcplogo", attached="", both=False, preview=False):
        import mail_design
        return mail_design.build(subject, body, logo_src=src, logo_dark_src=("cid:mcplogod" if both else ""), preview=preview, attached=attached,
                                 company=self._M().SETTINGS.get("sig_company") or "MCP Architecture & Interiors", sig_src=("cid:mcpsig" if self.sig_picture_on() else ""),
                                 sig_parts=(self.sig_parts() if (both and self.sig_picture_on()) else None))

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
        idx_pdf = os.path.join(tmp, re.sub(r'[\\/:*?"<>|]+', "-", "Sheet index - %s - revision %s.pdf" % (self.project_name(), self.info["issue_no"] or "0")))
        try:
            self.write_index_pdf(idx_pdf)
        except Exception:
            idx_pdf = None
        seen, drawings = set(), []
        for _n, rows in gi:
            for r in rows:
                p = r.get("path")
                if p and os.path.exists(p) and p not in seen:
                    seen.add(p)
                    drawings.append(p)
        dlg = SendDialog(self, subj, body, pdf, drawings, idx_pdf)
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
                    if self.sig_picture_on():
                        self.sig_parts()
                        for _i, _b in enumerate(self._sig_cache[2]):
                            m.get_payload()[1].add_related(_b, maintype="image", subtype="jpeg", cid="<mcpsig%d>" % _i, filename="signature%d.jpg" % _i, disposition="inline")
                except Exception:
                    pass
            for p in files:
                import mimetypes
                _mt = (mimetypes.guess_type(p)[0] or "application/octet-stream") if not p.lower().endswith(".pdf") else "application/pdf"
                _main, _sub = (_mt.split("/", 1) + ["octet-stream"])[:2]
                with open(p, "rb") as f:
                    m.add_attachment(f.read(), maintype=_main, subtype=_sub,
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
