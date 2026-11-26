"""Invoicing: numbered invoices with VAT, a PDF in the MCP look, and a list of what is paid and unpaid.

Only people you allow can use it: the owner sets a PIN, and the people on the allowed list (by their email) or anyone who knows the PIN can open the tool.
This is a lock inside the program for the people who share the computer or the program's folder; it is not bank-grade security."""
import datetime
import hashlib
import html as _html
import json
import os
import re
import secrets
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
                               QVBoxLayout, QWidget, QDoubleSpinBox, QDateEdit)

RED, GREY = "#C8102E", "#DCDCDC"


def money(x):
    return "R " + "{:,.2f}".format(float(x or 0)).replace(",", " ")


def totals(inv, vat_rate):
    sub = sum(float(l.get("qty") or 0) * float(l.get("price") or 0) for l in inv.get("lines", []))
    vat = round(sub * vat_rate / 100.0, 2) if inv.get("vat", True) else 0.0
    return round(sub, 2), vat, round(sub + vat, 2)


def _hash(pin, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), bytes.fromhex(salt_hex), 150000).hex()


class InvoiceDialog(QDialog):
    def __init__(self, inv, vat_rate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Invoice")
        self.resize(900, 720)
        self.vat_rate = vat_rate
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.no = QLineEdit(inv.get("no", ""))
        self.date = QDateEdit(datetime.date.fromisoformat(inv.get("date") or datetime.date.today().isoformat()))
        self.date.setCalendarPopup(True)
        self.due = QDateEdit(datetime.date.fromisoformat(inv.get("due") or datetime.date.today().isoformat()))
        self.due.setCalendarPopup(True)
        self.client = QLineEdit(inv.get("client", ""))
        self.addr = QPlainTextEdit(inv.get("client_addr", ""))
        self.addr.setFixedHeight(60)
        self.cvat = QLineEdit(inv.get("client_vat", ""))
        self.cmail = QLineEdit(inv.get("client_email", ""))
        self.ref = QLineEdit(inv.get("ref", ""))
        self.ref.setPlaceholderText("project or order, for example Urbika Erf 670, PTN 38")
        for lab, w in (("Invoice no", self.no), ("Date", self.date), ("Due date", self.due), ("Client", self.client), ("Client address", self.addr),
                       ("Client VAT no (optional)", self.cvat), ("Client email", self.cmail), ("Reference", self.ref)):
            f.addRow(lab, w)
        v.addLayout(f)
        self.t = QTableWidget(0, 4)
        self.t.setHorizontalHeaderLabels(["Description", "Qty", "Unit price (excl. VAT)", "Line total"])
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in ((1, 70), (2, 160), (3, 130)):
            self.t.setColumnWidth(i, w)
        v.addWidget(self.t, 1)
        for l in inv.get("lines", []) or [{}]:
            self._row(l)
        bar = QHBoxLayout()
        a = QPushButton("+ Add a line")
        a.clicked.connect(lambda: self._row({}))
        r = QPushButton("Remove the selected line")
        r.clicked.connect(self._remove)
        bar.addWidget(a)
        bar.addWidget(r)
        bar.addStretch(1)
        self.vat = QCheckBox("Add VAT (%g%%)" % vat_rate)
        self.vat.setChecked(inv.get("vat", True))
        self.vat.toggled.connect(self._sum)
        bar.addWidget(self.vat)
        v.addLayout(bar)
        self.tot = QLabel("")
        self.tot.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.tot.setStyleSheet("font-size:14px;font-weight:700;")
        v.addWidget(self.tot)
        v.addWidget(QLabel("Notes (shown on the invoice):"))
        self.notes = QPlainTextEdit(inv.get("notes", ""))
        self.notes.setFixedHeight(70)
        v.addWidget(self.notes)
        bb = QHBoxLayout()
        bb.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Save the invoice")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(self._ok)
        bb.addWidget(c)
        bb.addWidget(ok)
        v.addLayout(bb)
        self.t.itemChanged.connect(self._sum)
        self._sum()

    def _row(self, l):
        self.t.blockSignals(True)
        i = self.t.rowCount()
        self.t.insertRow(i)
        self.t.setItem(i, 0, QTableWidgetItem(str(l.get("desc", ""))))
        self.t.setItem(i, 1, QTableWidgetItem(str(l.get("qty", "1") if l.get("qty") not in (None, "") else "1")))
        self.t.setItem(i, 2, QTableWidgetItem(str(l.get("price", "") if l.get("price") not in (None, "") else "")))
        it = QTableWidgetItem("")
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.t.setItem(i, 3, it)
        self.t.blockSignals(False)
        self._sum()

    def _remove(self):
        for i in sorted({x.row() for x in self.t.selectedIndexes()}, reverse=True):
            self.t.removeRow(i)
        self._sum()

    @staticmethod
    def _num(s):
        try:
            return float(str(s).replace(" ", "").replace(",", ".").replace("R", ""))
        except ValueError:
            return 0.0

    def lines(self):
        out = []
        for i in range(self.t.rowCount()):
            g = lambda c: (self.t.item(i, c).text().strip() if self.t.item(i, c) else "")
            if g(0) or g(2):
                out.append({"desc": g(0), "qty": self._num(g(1)) or 0, "price": self._num(g(2))})
        return out

    def _sum(self, *_a):
        self.t.blockSignals(True)
        for i in range(self.t.rowCount()):
            q, p = self._num(self.t.item(i, 1).text() if self.t.item(i, 1) else 0), self._num(self.t.item(i, 2).text() if self.t.item(i, 2) else 0)
            self.t.item(i, 3).setText(money(q * p))
        self.t.blockSignals(False)
        if not hasattr(self, "vat") or not hasattr(self, "tot"):
            return                                      # the window is still being built
        sub, vat, tot = totals({"lines": self.lines(), "vat": self.vat.isChecked()}, self.vat_rate)
        self.tot.setText("Subtotal %s     VAT %s     Total %s" % (money(sub), money(vat), money(tot)))

    def _ok(self):
        if not self.client.text().strip() or not self.lines():
            QMessageBox.information(self, "Invoice", "Fill in the client and at least one line first.")
            return
        self.accept()

    def values(self):
        return {"no": self.no.text().strip(), "date": self.date.date().toString("yyyy-MM-dd"), "due": self.due.date().toString("yyyy-MM-dd"), "client": self.client.text().strip(),
                "client_addr": self.addr.toPlainText().strip(), "client_vat": self.cvat.text().strip(), "client_email": self.cmail.text().strip(), "ref": self.ref.text().strip(),
                "lines": self.lines(), "vat": self.vat.isChecked(), "notes": self.notes.toPlainText().strip()}


class BusinessDialog(QDialog):
    FIELDS = (("name", "Company name"), ("address", "Address"), ("vat_no", "VAT number"), ("reg_no", "Registration number"), ("email", "Email"), ("phone", "Phone"),
              ("bank", "Banking details (shown on the invoice)"), ("prefix", "Invoice number starts with"), ("terms", "Payment terms (days)"), ("vat_rate", "VAT rate (%)"), ("note", "Standard note"))

    def __init__(self, biz, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My business details")
        self.resize(620, 620)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.w = {}
        for k, lab in self.FIELDS:
            w = QPlainTextEdit(str(biz.get(k, ""))) if k in ("address", "bank", "note") else QLineEdit(str(biz.get(k, "")))
            if isinstance(w, QPlainTextEdit):
                w.setFixedHeight(72)
            self.w[k] = w
            f.addRow(lab, w)
        v.addLayout(f)
        bb = QHBoxLayout()
        bb.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(self.accept)
        bb.addWidget(c)
        bb.addWidget(ok)
        v.addLayout(bb)

    def values(self):
        return {k: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip() for k, w in self.w.items()}


class AccessDialog(QDialog):
    """The owner's list of the people who may use the invoicing tool."""

    def __init__(self, allowed, users=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Who can use invoicing")
        self.resize(560, 520)
        self.new_user, self.removed_users, self.shared_code = "", [], ""
        v = QVBoxLayout(self)
        v.addWidget(QLabel("One email address per line. These people open the tool without a PIN. Use the email each person sends from (Email account...)."))
        self.t = QPlainTextEdit("\n".join(allowed))
        v.addWidget(self.t, 1)
        v.addWidget(QLabel("<b>People with their own PIN</b> (they open the tool by typing the PIN you give them):"))
        from PySide6.QtWidgets import QListWidget
        self.ul = QListWidget()
        self.ul.setFixedHeight(90)
        self.ul.addItems(list(users))
        v.addWidget(self.ul)
        ur = QHBoxLayout()
        sb = QPushButton("Set the shared access code...")
        sb.setToolTip("You choose a code and share it with the people who may use invoicing. Anyone who types it opens the tool (not these settings).")
        sb.clicked.connect(self._shared)
        v.addWidget(sb)
        nb = QPushButton("Give a person a PIN...")
        nb.clicked.connect(self._new)
        rb = QPushButton("Remove the selected person's PIN")
        rb.clicked.connect(self._rm)
        ur.addWidget(nb)
        ur.addWidget(rb)
        ur.addStretch(1)
        v.addLayout(ur)
        bb = QHBoxLayout()
        pb = QPushButton("Change the owner PIN...")
        pb.clicked.connect(lambda: setattr(self, "want_pin", True) or self.accept())
        self.want_pin = False
        bb.addWidget(pb)
        bb.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setStyleSheet("font-weight:700;")
        ok.clicked.connect(self.accept)
        bb.addWidget(c)
        bb.addWidget(ok)
        v.addLayout(bb)

    def _shared(self):
        c, ok = QInputDialog.getText(self, "Shared access code", "Choose the access code (at least 4 characters):")
        if ok and len(c.strip()) >= 4:
            self.shared_code = c.strip()
            self.accept()
        elif ok:
            QMessageBox.information(self, "Invoicing", "The code needs at least 4 characters.")

    def _new(self):
        n, ok = QInputDialog.getText(self, "Give a person a PIN", "Name of the person:")
        if ok and n.strip():
            self.new_user = n.strip()
            self.accept()

    def _rm(self):
        it = self.ul.currentItem()
        if it is not None:
            self.removed_users.append(it.text())
            self.ul.takeItem(self.ul.row(it))

    def emails(self):
        return [x.strip().lower() for x in re.split(r"[\n,;]+", self.t.toPlainText()) if "@" in x]


class InvoicingPage(QWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._unlocked = False
        self._is_owner = False
        self.invoices = []
        self.queue = []
        self._load()
        self._qload()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        # --- locked page
        lk = QWidget()
        lv = QVBoxLayout(lk)
        lv.addStretch(1)
        self.lock_msg = QLabel("")
        self.lock_msg.setWordWrap(True)
        self.lock_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lock_msg.setStyleSheet("font-size:15px;")
        lv.addWidget(self.lock_msg)
        self.lock_btn = QPushButton("")
        self.lock_btn.setStyleSheet("font-weight:700;padding:8px 18px;")
        self.lock_btn.clicked.connect(self._unlock_clicked)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.lock_btn)
        row.addStretch(1)
        lv.addLayout(row)
        lv.addStretch(2)
        self.stack.addWidget(lk)
        # --- main page
        mp = QWidget()
        mv = QVBoxLayout(mp)
        top = QHBoxLayout()
        t = QLabel("Invoicing")
        t.setStyleSheet("font-size:20px;font-weight:700;")
        top.addWidget(t)
        top.addStretch(1)
        self.sum_lbl = QLabel("")
        top.addWidget(self.sum_lbl)
        mv.addLayout(top)
        bar = QHBoxLayout()
        for text, fn, bold in (("+ New invoice", self.new_invoice, True), ("Edit", self.edit_invoice, False), ("Copy as a new invoice", self.copy_invoice, False),
                               ("Preview", self.preview, False), ("Save PDF...", self.save_pdf, False), ("Mark paid / unpaid", self.toggle_paid, False),
                               ("Delete", self.delete_invoice, False), ("My business details...", self.business, False), ("Who can use this...", self.manage_access, False),
                               ("Lock", self.lock, False)):
            b = QPushButton(text)
            if bold:
                b.setStyleSheet("font-weight:700;")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        mv.addLayout(bar)
        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["Invoice no", "Date", "Client", "Reference", "Total", "Status"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.doubleClicked.connect(lambda *_: self.edit_invoice())
        self.tabs.addTab(self.tbl, "Invoices")
        qw = QWidget()
        qv = QVBoxLayout(qw)
        qv.addWidget(QLabel("Houses sent here from Orders, waiting to be invoiced. Pick some (or none for all) and make the invoice: one invoice per client."))
        qb = QHBoxLayout()
        for text, fn, bold in (("Make invoice(s) from the selected", self.invoice_from_queue, True), ("Set the price...", self.queue_price, False), ("Remove from this list", self.queue_remove, False)):
            b = QPushButton(text)
            if bold:
                b.setStyleSheet("font-weight:700;")
            b.clicked.connect(fn)
            qb.addWidget(b)
        qb.addStretch(1)
        qv.addLayout(qb)
        self.qtbl = QTableWidget(0, 6)
        self.qtbl.setHorizontalHeaderLabels(["Client", "Area", "House", "Description", "Price (excl. VAT)", "Sent here"])
        self.qtbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.qtbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.qtbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.qtbl.verticalHeader().setVisible(False)
        qv.addWidget(self.qtbl, 1)
        self.tabs.addTab(qw, "Waiting to be invoiced")
        mv.addWidget(self.tabs, 1)
        self.stack.addWidget(mp)
        self.refresh()

    # ----- storage and settings
    def _M(self):
        return sys.modules[type(self.win).__module__]

    def _S(self):
        return self._M().SETTINGS

    def _save_settings(self):
        try:
            self._M().save_settings()
        except Exception:
            pass

    def _path(self):
        d = self._M()._user_data_dir()
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "invoices.json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                self.invoices = [x for x in json.load(f) if isinstance(x, dict)]
        except Exception:
            self.invoices = []

    def _qpath(self):
        return os.path.join(self._M()._user_data_dir(), "invoice_queue.json")

    def _qload(self):
        try:
            with open(self._qpath(), encoding="utf-8") as f:
                self.queue = [x for x in json.load(f) if isinstance(x, dict)]
        except Exception:
            self.queue = []

    def _qsave(self):
        try:
            tmp = self._qpath() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self._qpath())
        except Exception as e:
            QMessageBox.warning(self, "Invoicing", "The list could not be saved: %s" % e)

    def queue_houses(self, items):
        """Orders sends its houses here. items: dicts with area, group, company, email, desc, price. Returns how many were added (a house already waiting or invoiced is not added twice)."""
        n = 0
        for it in items:
            k = (it.get("area") or "", it.get("group") or "")
            if any((q.get("area"), q.get("group")) == k and not q.get("invoice_void") for q in self.queue):
                continue
            q = dict(it)
            q["queued"] = datetime.date.today().isoformat()
            q["invoice"] = ""
            self.queue.append(q)
            n += 1
        self._qsave()
        self.refresh()
        return n

    def state_of(self, area, group):
        """('', ...) when the house is not in invoicing, otherwise ('to invoice'|'invoiced'|'paid', invoice no)."""
        for q in self.queue:
            if (q.get("area") or "", q.get("group") or "") == (area or "", group or ""):
                if not q.get("invoice"):
                    return "to invoice", ""
                inv = next((x for x in self.invoices if x.get("no") == q["invoice"]), None)
                return ("paid" if inv is not None and inv.get("status") == "Paid" else "invoiced"), q["invoice"]
        return "", ""

    def unqueue(self, area, group):
        self.queue = [q for q in self.queue if not ((q.get("area") or "", q.get("group") or "") == (area or "", group or "") and not q.get("invoice"))]
        self._qsave()
        self.refresh()

    def _save(self):
        try:
            tmp = self._path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.invoices, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self._path())
        except Exception as e:
            QMessageBox.warning(self, "Invoicing", "The invoices could not be saved: %s" % e)

    def biz(self):
        S = self._S()
        b = dict(S.get("inv_biz", {}) or {})
        b.setdefault("name", S.get("sig_company") or "MCP Architecture & Interiors")
        b.setdefault("email", S.get("sig_email") or S.get("mail_address") or "")
        b.setdefault("phone", S.get("sig_phone") or "")
        b.setdefault("prefix", "INV-")
        b.setdefault("terms", "30")
        b.setdefault("vat_rate", "15")
        return b

    def vat_rate(self):
        try:
            return float(str(self.biz().get("vat_rate", "15")).replace(",", "."))
        except ValueError:
            return 15.0

    # ----- access
    def my_email(self):
        S = self._S()
        return str(S.get("mail_address") or S.get("sig_email") or "").strip().lower()

    def owner_set(self):
        return bool((self._S().get("inv_owner") or {}).get("hash"))

    def allowed(self):
        if self._unlocked:
            return True
        me = self.my_email()
        return bool(me) and me in [x.lower() for x in (self._S().get("inv_allowed") or [])]

    def _check_pin(self, pin):
        o = self._S().get("inv_owner") or {}
        return bool(o.get("hash")) and secrets.compare_digest(_hash(pin, o["salt"]), o["hash"])

    def _user_pin(self, pin):
        """The name of the person whose own PIN this is, or ''."""
        for u in (self._S().get("inv_users") or []):
            if u.get("hash") and secrets.compare_digest(_hash(pin, u["salt"]), u["hash"]):
                return u.get("name", "") or "user"
        return ""

    def _shared_ok(self, code):
        o = self._S().get("inv_shared") or {}
        return bool(o.get("hash")) and secrets.compare_digest(_hash(code, o["salt"]), o["hash"])

    def set_shared_code(self, code):
        salt = secrets.token_hex(16)
        self._S()["inv_shared"] = {"salt": salt, "hash": _hash(code, salt)}
        self._save_settings()

    def new_user_pin(self, name):
        """Makes a PIN for a person (the owner hands it to them). Returns the PIN, which is only shown now: the program keeps only a scrambled copy."""
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        salt = secrets.token_hex(16)
        users = [u for u in (self._S().get("inv_users") or []) if u.get("name", "").lower() != name.lower()]
        users.append({"name": name, "salt": salt, "hash": _hash(pin, salt)})
        self._S()["inv_users"] = users
        self._save_settings()
        return pin

    def _set_pin(self, parent=None):
        p1, ok = QInputDialog.getText(parent or self, "Owner PIN", "Choose an owner PIN (at least 4 characters):", QLineEdit.EchoMode.Password)
        if not ok or len(p1) < 4:
            if ok:
                QMessageBox.information(self, "Invoicing", "The PIN needs at least 4 characters.")
            return False
        p2, ok = QInputDialog.getText(parent or self, "Owner PIN", "Type it again:", QLineEdit.EchoMode.Password)
        if not ok or p1 != p2:
            if ok:
                QMessageBox.information(self, "Invoicing", "The two PINs were not the same.")
            return False
        salt = secrets.token_hex(16)
        self._S()["inv_owner"] = {"salt": salt, "hash": _hash(p1, salt)}
        self._save_settings()
        return True

    def _owner_ok(self):
        """Ask for the owner PIN (or make one the first time). True when the owner is confirmed."""
        if not self.owner_set():
            if QMessageBox.question(self, "Invoicing", "No owner PIN is set yet. Set one now? Whoever sets it is the owner and decides who can use the invoicing tool.") != QMessageBox.StandardButton.Yes:
                return False
            if not self._set_pin():
                return False
            self._unlocked = True
            return True
        pin, ok = QInputDialog.getText(self, "Owner PIN", "Owner PIN:", QLineEdit.EchoMode.Password)
        if not ok:
            return False
        if not self._check_pin(pin):
            QMessageBox.warning(self, "Invoicing", "That PIN is not right.")
            return False
        return True

    def _unlock_clicked(self):
        if self.owner_set() and ((self._S().get("inv_users") or []) or (self._S().get("inv_shared") or {}).get("hash")):
            pin, ok = QInputDialog.getText(self, "Invoicing", "Your PIN or access code:", QLineEdit.EchoMode.Password)
            if not ok:
                return
            if self._check_pin(pin):
                self._unlocked, self._is_owner = True, True
            elif self._shared_ok(pin) or self._user_pin(pin):
                self._unlocked, self._is_owner = True, False
            else:
                QMessageBox.warning(self, "Invoicing", "That PIN is not right.")
                return
            self.refresh()
            return
        if self._owner_ok():
            self._unlocked, self._is_owner = True, True
            self.refresh()

    def lock(self):
        self._unlocked = False
        self._is_owner = False
        self.refresh()

    def manage_access(self):
        if not self._owner_ok():
            return
        d = AccessDialog(self._S().get("inv_allowed") or [], [u.get("name", "") for u in (self._S().get("inv_users") or [])], self)
        if d.exec():
            self._S()["inv_allowed"] = d.emails()
            self._S()["inv_users"] = [u for u in (self._S().get("inv_users") or []) if u.get("name") not in d.removed_users]
            self._save_settings()
            if d.want_pin:
                self._set_pin()
            if d.shared_code:
                self.set_shared_code(d.shared_code)
                QMessageBox.information(self, "Invoicing", "The shared access code is set. Give it to the people who may use invoicing.")
            if d.new_user:
                pin = self.new_user_pin(d.new_user)
                QInputDialog.getText(self, "PIN for %s" % d.new_user, "Give %s this PIN. It is shown only now, so copy it before you close this:" % d.new_user, QLineEdit.EchoMode.Normal, pin)
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    # ----- list
    def refresh(self):
        if not self.allowed():
            if self.owner_set():
                self.lock_msg.setText("<b>Invoicing is only for people the owner has allowed.</b><br>You are not on the list. If you are the owner, unlock it with your PIN.")
                self.lock_btn.setText("Unlock with the owner PIN...")
            else:
                self.lock_msg.setText("<b>Invoicing is locked.</b><br>Set an owner PIN to start. Only you and the people you add can then open it.")
                self.lock_btn.setText("Set the owner PIN...")
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        rate = self.vat_rate()
        self.tbl.setRowCount(0)
        out = 0.0
        for inv in sorted(self.invoices, key=lambda x: (x.get("date", ""), x.get("no", "")), reverse=True):
            sub, vat, tot = totals(inv, rate)
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            late = inv.get("status") != "Paid" and inv.get("due", "9999") < datetime.date.today().isoformat()
            vals = [inv.get("no", ""), inv.get("date", ""), inv.get("client", ""), inv.get("ref", ""), money(tot), ("Paid" if inv.get("status") == "Paid" else ("Overdue" if late else "Unpaid"))]
            for c, x in enumerate(vals):
                it = QTableWidgetItem(x)
                it.setData(Qt.ItemDataRole.UserRole, inv.get("no", ""))
                if c == 4:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tbl.setItem(i, c, it)
            if inv.get("status") != "Paid":
                out += tot
        self.sum_lbl.setText("Outstanding: <b>%s</b>" % money(out))
        waiting = [q for q in self.queue if not q.get("invoice")]
        self.tabs.setTabText(1, "Waiting to be invoiced (%d)" % len(waiting))
        self.qtbl.setRowCount(0)
        for q in waiting:
            i = self.qtbl.rowCount()
            self.qtbl.insertRow(i)
            for c, x in enumerate((q.get("company") or "(no client)", q.get("area") or "", q.get("group") or "", q.get("desc") or "", money(q.get("price")) if q.get("price") not in (None, "") else "to fill in", q.get("queued", ""))):
                it = QTableWidgetItem(str(x))
                it.setData(Qt.ItemDataRole.UserRole, (q.get("area") or "", q.get("group") or ""))
                self.qtbl.setItem(i, c, it)
        try:                                                     # Orders shows what is waiting, invoiced or paid on its houses
            rp_ = getattr(self.win, "register_page", None)
            if rp_ is not None and getattr(rp_, "_ltiles", None) and "Order" in rp_._ltiles:
                rp_._rebuild_tiles("Order")
        except Exception:
            pass

    def _cur(self):
        r = self.tbl.currentRow()
        if r < 0:
            QMessageBox.information(self, "Invoicing", "Click an invoice in the list first.")
            return None
        no = self.tbl.item(r, 0).data(Qt.ItemDataRole.UserRole)
        return next((x for x in self.invoices if x.get("no") == no), None)

    def _qsel(self):
        keys = {self.qtbl.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in {x.row() for x in self.qtbl.selectedIndexes()}}
        waiting = [q for q in self.queue if not q.get("invoice")]
        return [q for q in waiting if (q.get("area") or "", q.get("group") or "") in keys] if keys else waiting

    def queue_price(self):
        sel = self._qsel()
        if not sel:
            return
        t, ok = QInputDialog.getText(self, "Price", "Price per house, excluding VAT (for the %d chosen):" % len(sel))
        if ok:
            try:
                v = float(t.replace(" ", "").replace(",", ".").replace("R", ""))
            except ValueError:
                return
            for q in sel:
                q["price"] = v
            self._qsave()
            self.refresh()

    def queue_remove(self):
        sel = self._qsel()
        if sel and QMessageBox.question(self, "Invoicing", "Remove %d house%s from this list? They stay in Orders." % (len(sel), "" if len(sel) == 1 else "s")) == QMessageBox.StandardButton.Yes:
            self.queue = [q for q in self.queue if q not in sel]
            self._qsave()
            self.refresh()

    def invoice_from_queue(self):
        sel = self._qsel()
        if not sel:
            QMessageBox.information(self, "Invoicing", "Nothing is waiting to be invoiced.")
            return
        byc = {}
        for q in sel:
            byc.setdefault(q.get("company") or "", []).append(q)
        for comp, qs in byc.items():
            b = self.biz()
            try:
                terms = int(b.get("terms", 30))
            except ValueError:
                terms = 30
            today = datetime.date.today()
            areas = sorted({q.get("area") for q in qs if q.get("area")})
            inv = {"no": self.next_no(), "date": today.isoformat(), "due": (today + datetime.timedelta(days=terms)).isoformat(), "vat": True, "notes": b.get("note", ""),
                   "client": comp, "client_email": next((q.get("email") for q in qs if q.get("email")), ""), "ref": ", ".join(areas),
                   "lines": [{"desc": q.get("desc") or q.get("group"), "qty": 1, "price": q.get("price") or 0} for q in qs]}
            if self._edit(inv, True, [(q.get("area"), q.get("group")) for q in qs]):
                for q in qs:
                    q["invoice"] = inv["no"]
                self._qsave()
        self.refresh()

    def next_no(self):
        b = self.biz()
        pre = "%s%d-" % (b.get("prefix", "INV-"), datetime.date.today().year)
        n = max([int(m.group(1)) for x in self.invoices for m in [re.match(re.escape(pre) + r"(\d+)$", x.get("no", ""))] if m] or [0]) + 1
        return "%s%03d" % (pre, n)

    def new_invoice(self):
        b = self.biz()
        try:
            terms = int(b.get("terms", 30))
        except ValueError:
            terms = 30
        today = datetime.date.today()
        inv = {"no": self.next_no(), "date": today.isoformat(), "due": (today + datetime.timedelta(days=terms)).isoformat(), "vat": True, "notes": b.get("note", ""), "lines": [{}]}
        self._edit(inv, True)

    def edit_invoice(self):
        inv = self._cur()
        if inv is not None:
            self._edit(inv, False)

    def copy_invoice(self):
        inv = self._cur()
        if inv is not None:
            c = json.loads(json.dumps(inv))
            c.update({"no": self.next_no(), "date": datetime.date.today().isoformat(), "status": "Unpaid"})
            c.pop("paid_date", None)
            self._edit(c, True)

    def _edit(self, inv, new, houses=None):
        d = InvoiceDialog(inv, self.vat_rate(), self)
        if not d.exec():
            return False
        v = d.values()
        if not v["no"] or any(x.get("no") == v["no"] and x is not inv for x in self.invoices):
            QMessageBox.information(self, "Invoicing", "That invoice number is empty or already used. Pick another number.")
            inv.update(v)
            return self._edit(inv, new, houses)
        inv.update(v)
        inv.setdefault("status", "Unpaid")
        if houses:
            inv["houses"] = [list(h) for h in houses]
        if new:
            self.invoices.append(inv)
        self._save()
        self.refresh()
        return True

    def toggle_paid(self):
        inv = self._cur()
        if inv is None:
            return
        if inv.get("status") == "Paid":
            inv["status"] = "Unpaid"
            inv.pop("paid_date", None)
        else:
            inv["status"], inv["paid_date"] = "Paid", datetime.date.today().isoformat()
        self._save()
        self.refresh()

    def delete_invoice(self):
        inv = self._cur()
        if inv is None:
            return
        if QMessageBox.question(self, "Invoicing", "Delete invoice %s? This cannot be undone. (Invoice numbers should not be reused, so only delete mistakes.)" % inv.get("no")) == QMessageBox.StandardButton.Yes:
            self.invoices = [x for x in self.invoices if x is not inv]
            for q in self.queue:
                if q.get("invoice") == inv.get("no"):
                    q["invoice"] = ""                         # the houses wait to be invoiced again
            self._qsave()
            self._save()
            self.refresh()

    def business(self):
        d = BusinessDialog(self.biz(), self)
        if d.exec():
            self._S()["inv_biz"] = d.values()
            self._save_settings()
            self.refresh()

    # ----- the PDF
    def html(self, inv):
        e = lambda x: _html.escape(str(x or ""))
        b = self.biz()
        sub, vat, tot = totals(inv, self.vat_rate())
        ml = lambda t: e(t).replace("\n", "<br>")
        rows = "".join('<tr><td style="padding:5px 4px;border-bottom:1px solid #ddd;">%s</td><td align="right" style="padding:5px 4px;border-bottom:1px solid #ddd;">%g</td>'
                       '<td align="right" style="padding:5px 4px;border-bottom:1px solid #ddd;">%s</td><td align="right" style="padding:5px 4px;border-bottom:1px solid #ddd;">%s</td></tr>'
                       % (ml(l.get("desc")), float(l.get("qty") or 0), money(l.get("price")), money(float(l.get("qty") or 0) * float(l.get("price") or 0))) for l in inv.get("lines", []))
        paid = inv.get("status") == "Paid"
        title = "TAX INVOICE" if inv.get("vat", True) else "INVOICE"
        h = ['<html><body style="font-family:Arial; color:#111; font-size:9.5pt;">',
             '<table width="100%%"><tr><td width="40%%"><img src="logo" height="54"></td><td align="right"><span style="font-size:24pt;font-weight:bold;">%s</span><br>'
             '<span style="color:#555;">No %s</span></td></tr></table>' % (title, e(inv.get("no"))),
             '<table width="100%%" cellspacing="0"><tr><td bgcolor="%s" height="5"></td></tr></table><p></p>' % RED,
             '<table width="100%%"><tr><td width="50%%" valign="top"><b>FROM</b><br><b>%s</b><br>%s%s%s%s</td><td width="50%%" valign="top"><b>BILL TO</b><br><b>%s</b><br>%s%s</td></tr></table><p></p>'
             % (e(b.get("name")), ml(b.get("address")) + "<br>" if b.get("address") else "", ("VAT no: %s<br>" % e(b["vat_no"])) if b.get("vat_no") else "",
                ("Reg no: %s<br>" % e(b["reg_no"])) if b.get("reg_no") else "", (e(b.get("email")) + (" | " + e(b["phone"]) if b.get("phone") else "")) if b.get("email") or b.get("phone") else "",
                e(inv.get("client")), (ml(inv.get("client_addr")) + "<br>") if inv.get("client_addr") else "", ("VAT no: %s" % e(inv["client_vat"])) if inv.get("client_vat") else ""),
             '<table width="100%%"><tr><td>Date: <b>%s</b></td><td>Due: <b>%s</b></td><td>Reference: <b>%s</b></td></tr></table><p></p>' % (e(inv.get("date")), e(inv.get("due")), e(inv.get("ref")) or "-"),
             '<table width="100%%" cellspacing="0"><tr bgcolor="%s"><th align="left" style="padding:5px 4px;">Description</th><th align="right">Qty</th><th align="right">Unit price</th><th align="right">Amount</th></tr>%s</table>' % (GREY, rows),
             '<table width="100%%" cellspacing="0" style="margin-top:8px;"><tr><td width="60%%"></td><td align="right">Subtotal</td><td align="right">%s</td></tr>' % money(sub)]
        if inv.get("vat", True):
            h.append('<tr><td></td><td align="right">VAT (%g%%)</td><td align="right">%s</td></tr>' % (self.vat_rate(), money(vat)))
        h.append('<tr><td></td><td align="right" bgcolor="%s"><b>TOTAL DUE</b></td><td align="right" bgcolor="%s"><b>%s</b></td></tr></table>' % (GREY, GREY, money(tot)))
        if paid:
            h.append('<p style="color:#1B7F3B;font-size:14pt;"><b>PAID %s</b></p>' % e(inv.get("paid_date")))
        if b.get("bank"):
            h.append('<p><b>BANKING DETAILS</b><br>%s<br>Please use %s as the payment reference.</p>' % (ml(b["bank"]), e(inv.get("no"))))
        if inv.get("notes"):
            h.append("<p>%s</p>" % ml(inv["notes"]))
        h.append('<p style="color:#777;font-size:8pt;">%s</p></body></html>' % e(b.get("name")))
        return "".join(h)

    def _doc(self, inv):
        from PySide6.QtGui import QFont, QTextDocument
        d = QTextDocument()
        try:
            im = self.win.register_page.logos().get("mcp_logo")
            if im is not None:
                d.addResource(QTextDocument.ResourceType.ImageResource, QUrl("logo"), im)
        except Exception:
            pass
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml(self.html(inv))
        return d

    def write_pdf(self, inv, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(14, 14, 14, 14), QPageLayout.Unit.Millimeter))
        w.setResolution(300)
        w.setTitle("Invoice %s" % inv.get("no", ""))
        d = self._doc(inv)
        d.setPageSize(w.pageLayout().paintRectPixels(300).size().toSizeF() if hasattr(w.pageLayout(), "paintRectPixels") else d.pageSize())
        d.print_(w)
        return path

    def preview(self):
        inv = self._cur()
        if inv is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Invoice %s" % inv.get("no"))
        dlg.resize(760, 900)
        v = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setDocument(self._doc(inv))
        v.addWidget(tb, 1)
        b = QPushButton("Save as PDF...")
        b.clicked.connect(lambda: (dlg.accept(), self.save_pdf(inv)))
        v.addWidget(b)
        dlg.exec()

    def save_pdf(self, inv=None):
        inv = inv if isinstance(inv, dict) else self._cur()
        if inv is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save the invoice", re.sub(r'[\\/:*?"<>|]+', "-", "Invoice %s - %s.pdf" % (inv.get("no", ""), inv.get("client", ""))), "PDF (*.pdf)")
        if p:
            self.write_pdf(inv, p)
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))
