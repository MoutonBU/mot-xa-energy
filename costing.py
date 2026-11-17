"""Costing tab: a priced fixture schedule (toilets, basins, showers, sinks, taps ...) built from the project's rooms.

* Products: a small catalogue you build up. Paste a shop link and the program reads the name, price and photo from the
  page; or type it in. One product per item can be the default for the whole building.
* Schedule: one line per fixture and room (level, unit, room, item, product, quantity, price). "Build from rooms" fills it
  from the Rooms list by room name; every line stays editable.
* Totals: subtotal, contingency and VAT, and a PDF / CSV schedule with the product photos.

Everything is stored in the project file (the photos are kept as small thumbnails inside it)."""
import base64
import csv
import html as _html
import json
import re
import threading
import urllib.parse
import urllib.request
import webbrowser

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

CATEGORIES = ["Toilet (WC)", "Basin", "Basin mixer", "Shower", "Shower mixer", "Bath", "Bath mixer", "Kitchen sink",
              "Kitchen mixer", "Laundry tub", "Urinal", "Towel rail", "Other"]

# room name (after the unit prefix is removed) -> fixtures to put in it. First match wins.
FIXTURE_RULES = [
    (r"\b(wc|toilet|cloak|powder)", [("Toilet (WC)", 1), ("Basin", 1), ("Basin mixer", 1)]),
    (r"\b(bath|ensuite|en-suite|shower)", [("Toilet (WC)", 1), ("Basin", 1), ("Basin mixer", 1), ("Shower", 1), ("Shower mixer", 1)]),
    (r"\b(kitchen|kitchenette)", [("Kitchen sink", 1), ("Kitchen mixer", 1)]),
    (r"\b(laundry|scullery|utility|wash)", [("Laundry tub", 1)]),
]

# retailers for "Find online": name -> site (None = the whole web)
RETAILERS = [("All shops", None), ("Italtile", "italtile.com"), ("Builders Warehouse", "builders.co.za"), ("Buco", "buco.co.za"),
             ("Cashbuild", "cashbuild.co.za"), ("Takealot", "takealot.com"), ("Plumblink", "plumblink.co.za")]

_UNIT_PREFIX = re.compile(r"^\W*[A-Za-z]{0,2}\s*\d{1,2}\s*[-_.:]\s*(?=[A-Za-z])")


def money(x):
    try:
        return "R {:,.2f}".format(float(x)).replace(",", " ")
    except Exception:
        return "R 0.00"


def fixtures_for(room_name):
    """[(category, qty)] for a room name, or []."""
    n = _UNIT_PREFIX.sub("", str(room_name or "")).strip().lower()
    for pat, items in FIXTURE_RULES:
        if re.search(pat, n):
            return list(items)
    return []


# ---------------- reading a shop page ----------------
def _meta(html, *names):
    for n in names:
        for pat in (r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)["\']' % re.escape(n),
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(n)):
            m = re.search(pat, html, re.I)
            if m and m.group(1).strip():
                return _html.unescape(m.group(1).strip())
    return ""


def _num(s):
    s = re.sub(r"[^\d.,]", "", str(s))
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.rsplit(",", 1)[1]) in (1, 2) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _jsonld(html):
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            out.append(json.loads(m.group(1).strip()))
        except Exception:
            continue

    def walk(o):
        if isinstance(o, list):
            for i in o:
                yield from walk(i)
        elif isinstance(o, dict):
            yield o
            for k in ("@graph", "mainEntity", "itemListElement"):
                if k in o:
                    yield from walk(o[k])
    for d in out:
        yield from walk(d)


def parse_product_html(html, url=""):
    """name, brand, price (rand), image URL, sku, supplier from a shop page. Missing items are empty / 0."""
    r = dict(name="", brand="", price=0.0, image="", sku="", supplier="")
    for o in _jsonld(html):
        t = o.get("@type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            r["name"] = r["name"] or str(o.get("name") or "")
            b = o.get("brand")
            r["brand"] = r["brand"] or str(b.get("name") if isinstance(b, dict) else (b or ""))
            r["sku"] = r["sku"] or str(o.get("sku") or o.get("mpn") or "")
            im = o.get("image")
            im = im[0] if isinstance(im, list) and im else im
            r["image"] = r["image"] or str(im.get("url") if isinstance(im, dict) else (im or ""))
            of = o.get("offers")
            of = of[0] if isinstance(of, list) and of else of
            if isinstance(of, dict) and not r["price"]:
                r["price"] = _num(of.get("price") or of.get("lowPrice") or 0)
    r["name"] = r["name"] or _meta(html, "og:title", "twitter:title")
    if not r["name"]:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        r["name"] = _html.unescape(m.group(1).strip()) if m else ""
    r["image"] = r["image"] or _meta(html, "og:image", "twitter:image")
    if not r["price"]:
        r["price"] = _num(_meta(html, "product:price:amount", "og:price:amount", "twitter:data1"))
    if not r["price"]:
        m = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,\s]+)["\']', html, re.I) or \
            re.search(r'content=["\']([\d.,\s]+)["\'][^>]*itemprop=["\']price["\']', html, re.I)
        if m:
            r["price"] = _num(m.group(1))
    if not r["price"]:
        m = re.search(r"\bR\s?(\d[\d\s,]*(?:\.\d{2})?)", html)
        if m:
            r["price"] = _num(m.group(1))
    if r["image"] and url:
        r["image"] = urllib.parse.urljoin(url, r["image"])
    r["supplier"] = _meta(html, "og:site_name") or (urllib.parse.urlparse(url).netloc.replace("www.", "") if url else "")
    r["name"] = re.sub(r"\s+", " ", r["name"]).strip()[:160]
    return r


def fetch(url, binary=False, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                               "Accept-Language": "en-ZA,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as rsp:
        data = rsp.read(8_000_000)
        if binary:
            return data
        enc = rsp.headers.get_content_charset() or "utf-8"
        return data.decode(enc, "replace")


# ---------------- photos ----------------
def thumb_b64(img, w=240, h=180):
    """Scale a QImage to fit w x h and return it as base64 JPEG text."""
    if img is None or img.isNull():
        return ""
    img = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.convertToFormat(QImage.Format.Format_RGB32).save(buf, "JPG", 85)
    return base64.b64encode(bytes(ba)).decode("ascii")


def pix_from_b64(s):
    pm = QPixmap()
    if s:
        try:
            pm.loadFromData(base64.b64decode(s))
        except Exception:
            pass
    return pm


# ---------------- product dialog ----------------
class ProductDialog(QDialog):
    got = Signal(object, str)

    def __init__(self, parent, prod=None, category=""):
        super().__init__(parent)
        self.setWindowTitle("Product")
        self.setMinimumWidth(560)
        self.p = dict(prod or {})
        self.photo = self.p.get("photo", "")
        f = QFormLayout()
        self.cat = QComboBox()
        self.cat.setEditable(True)
        self.cat.addItems(CATEGORIES)
        self.cat.setCurrentText(self.p.get("category") or category or CATEGORIES[0])
        self.url = QLineEdit(self.p.get("url", ""))
        self.url.setPlaceholderText("Paste the product page link from the shop")
        self.get = QPushButton("Read from link")
        self.get.setToolTip("Reads the name, price and photo from the shop page.")
        self.get.clicked.connect(self._read)
        ur = QHBoxLayout()
        ur.addWidget(self.url, 1)
        ur.addWidget(self.get)
        self.brand = QLineEdit(self.p.get("brand", ""))
        self.name = QLineEdit(self.p.get("name", ""))
        self.sup = QLineEdit(self.p.get("supplier", ""))
        self.sku = QLineEdit(self.p.get("sku", ""))
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 10_000_000)
        self.price.setDecimals(2)
        self.price.setPrefix("R ")
        self.price.setGroupSeparatorShown(True)
        self.price.setValue(float(self.p.get("price", 0) or 0))
        self.price_date = QLabel(self.p.get("price_date", ""))
        pr = QHBoxLayout()
        pr.addWidget(self.price, 1)
        pr.addWidget(self.price_date)
        self.notes = QTextEdit(self.p.get("notes", ""))
        self.notes.setFixedHeight(54)
        self.pic = QLabel("No photo")
        self.pic.setFixedSize(240, 180)
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setStyleSheet("border:1px solid #888;")
        b1, b2 = QPushButton("Choose photo..."), QPushButton("Paste photo")
        b1.clicked.connect(self._choose)
        b2.clicked.connect(self._paste)
        pb = QVBoxLayout()
        pb.addWidget(b1)
        pb.addWidget(b2)
        pb.addStretch(1)
        ph = QHBoxLayout()
        ph.addWidget(self.pic)
        ph.addLayout(pb)
        f.addRow("Item", self.cat)
        f.addRow("Link", ur)
        f.addRow("Brand", self.brand)
        f.addRow("Product", self.name)
        f.addRow("Supplier", self.sup)
        f.addRow("Code / SKU", self.sku)
        f.addRow("Price (incl. VAT)", pr)
        f.addRow("Photo", ph)
        f.addRow("Notes", self.notes)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(f)
        v.addWidget(self.msg)
        v.addWidget(bb)
        self.got.connect(self._fill)
        self._show_photo()

    def _show_photo(self):
        pm = pix_from_b64(self.photo)
        if pm.isNull():
            self.pic.setPixmap(QPixmap())
            self.pic.setText("No photo")
        else:
            self.pic.setPixmap(pm.scaled(self.pic.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Product photo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.photo = thumb_b64(QImage(path)) or self.photo
            self._show_photo()

    def _paste(self):
        from PySide6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if img.isNull():
            self.msg.setText("There is no picture on the clipboard.")
            return
        self.photo = thumb_b64(img)
        self._show_photo()

    def _read(self):
        u = self.url.text().strip()
        if not u:
            return
        if not re.match(r"https?://", u, re.I):
            u = "https://" + u
            self.url.setText(u)
        self.get.setEnabled(False)
        self.msg.setText("Reading the page...")

        def work():
            try:
                info = parse_product_html(fetch(u), u)
                data = None
                if info["image"]:
                    try:
                        data = fetch(info["image"], binary=True)
                    except Exception:
                        data = None
                info["_img"] = data
                self.got.emit(info, "")
            except Exception as e:
                self.got.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _fill(self, info, err):
        self.get.setEnabled(True)
        if not info:
            self.msg.setText("Could not read that page (%s). The shop may block automatic reading: type the details in, "
                             "or paste a photo." % err)
            return
        got = []
        if info["name"] and not self.name.text().strip():
            self.name.setText(info["name"])
            got.append("name")
        elif info["name"]:
            got.append("name (kept yours)")
        if info["brand"] and not self.brand.text().strip():
            self.brand.setText(info["brand"])
        if info["supplier"] and not self.sup.text().strip():
            self.sup.setText(info["supplier"])
        if info["sku"] and not self.sku.text().strip():
            self.sku.setText(info["sku"])
        if info["price"]:
            self.price.setValue(info["price"])
            import datetime
            self.price_date.setText("read " + datetime.date.today().isoformat())
            got.append("price")
        if info.get("_img"):
            img = QImage.fromData(info["_img"])
            if not img.isNull():
                self.photo = thumb_b64(img)
                self._show_photo()
                got.append("photo")
        self.msg.setText(("Read: " + ", ".join(got) + ". Check them against the shop page.") if got else
                         "The page had nothing readable. Type the details in.")

    def result(self):
        p = dict(self.p)
        p.update(category=self.cat.currentText().strip() or "Other", url=self.url.text().strip(), brand=self.brand.text().strip(),
                 name=self.name.text().strip(), supplier=self.sup.text().strip(), sku=self.sku.text().strip(),
                 price=self.price.value(), price_date=self.price_date.text(), photo=self.photo, notes=self.notes.toPlainText().strip())
        if not p.get("id"):
            import uuid
            p["id"] = uuid.uuid4().hex[:8]
        return p


# ---------------- the tab ----------------
class CostingPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.products = []          # {id, category, brand, name, supplier, sku, url, price, price_date, photo, notes}
        self.defaults = {}          # category -> product id
        self.lines = []             # {room, floor, unit, category, product ("" = the default), qty, auto, note}
        self.contingency = 0.0
        self.vat = False
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        sp = QSplitter(Qt.Orientation.Vertical)
        v.addWidget(sp, 1)

        # products
        gp = QGroupBox("Products")
        pv = QVBoxLayout(gp)
        pb = QHBoxLayout()
        for text, fn in (("Add from link...", self.add_from_link), ("Add manually...", self.add_product), ("Edit", self.edit_product),
                         ("Remove", self.remove_product), ("Use as default", self.set_default)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            pb.addWidget(b)
        pb.addSpacing(16)
        pb.addWidget(QLabel("Find online:"))
        self.find_cat = QComboBox()
        self.find_cat.addItems(CATEGORIES[:-1])
        self.find_shop = QComboBox()
        for n, _s in RETAILERS:
            self.find_shop.addItem(n)
        fb = QPushButton("Search")
        fb.setToolTip("Opens a web search in your browser for the chosen item at the chosen shop. Copy the link of a product "
                      "you like and use Add from link.")
        fb.clicked.connect(self.find_online)
        pb.addWidget(self.find_cat)
        pb.addWidget(self.find_shop)
        pb.addWidget(fb)
        pb.addStretch(1)
        pv.addLayout(pb)
        self.ptab = QTableWidget(0, 7)
        self.ptab.setHorizontalHeaderLabels(["Photo", "Item", "Product", "Supplier", "Price", "Default", "Link"])
        self.ptab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ptab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ptab.verticalHeader().setVisible(False)
        self.ptab.setIconSize(QSize(72, 54))
        h = self.ptab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate((84, 130, 0, 130, 100, 80, 120)):
            if w:
                self.ptab.setColumnWidth(i, w)
        self.ptab.doubleClicked.connect(lambda *_: self.edit_product())
        self.ptab.cellClicked.connect(self._p_click)
        pv.addWidget(self.ptab)
        sp.addWidget(gp)

        # schedule
        gs = QGroupBox("Fixture schedule")
        sv = QVBoxLayout(gs)
        sb = QHBoxLayout()
        b = QPushButton("Build from rooms")
        b.setToolTip("Adds toilets, basins, showers, sinks and taps to every wet room in the Rooms list, by room name. "
                     "Lines you have changed or added yourself are kept.")
        b.clicked.connect(self.build_from_rooms)
        sb.addWidget(b)
        for text, fn in (("Add line", self.add_line), ("Remove line", self.remove_line), ("Clear schedule", self.clear_lines)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            sb.addWidget(bb)
        sb.addStretch(1)
        sv.addLayout(sb)
        self.stab = QTableWidget(0, 9)
        self.stab.setHorizontalHeaderLabels(["Ref", "Level", "Unit", "Room", "Item", "Product", "Qty", "Unit price", "Total"])
        self.stab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stab.verticalHeader().setVisible(False)
        h = self.stab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate((56, 110, 60, 150, 170, 0, 76, 110, 110)):
            if w:
                self.stab.setColumnWidth(i, w)
        self.stab.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.stab.itemChanged.connect(self._s_edit)
        sv.addWidget(self.stab)
        tot = QHBoxLayout()
        self.cont = QDoubleSpinBox()
        self.cont.setRange(0, 100)
        self.cont.setSuffix(" % contingency")
        self.cont.valueChanged.connect(self._cont_changed)
        self.vat_chk = QCheckBox("Prices exclude VAT: add 15 %")
        self.vat_chk.toggled.connect(self._vat_changed)
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700; font-size:14px;")
        tot.addWidget(self.cont)
        tot.addWidget(self.vat_chk)
        tot.addStretch(1)
        tot.addWidget(self.total_lbl)
        sv.addLayout(tot)
        sp.addWidget(gs)
        sp.setStretchFactor(0, 2)
        sp.setStretchFactor(1, 3)
        sp.setSizes([300, 400])
        self.refresh()

    # ----- state -----
    def state(self):
        return {"products": self.products, "defaults": self.defaults, "lines": self.lines,
                "contingency": self.contingency, "vat": self.vat}

    def set_state(self, d):
        d = d or {}
        self.products = [dict(p) for p in d.get("products", []) if isinstance(p, dict)]
        self.defaults = dict(d.get("defaults", {}) or {})
        self.lines = [dict(x) for x in d.get("lines", []) if isinstance(x, dict)]
        self.contingency = float(d.get("contingency", 0) or 0)
        self.vat = bool(d.get("vat", False))
        self.refresh()

    def _dirty(self):
        try:
            self.win._mark_dirty()
        except Exception:
            pass

    # ----- lookups -----
    def product(self, pid):
        for p in self.products:
            if p.get("id") == pid:
                return p
        return None

    def line_product(self, ln):
        p = self.product(ln.get("product")) if ln.get("product") else None
        return p or self.product(self.defaults.get(ln.get("category")))

    def totals(self):
        sub = sum((self.line_product(l) or {}).get("price", 0) * l.get("qty", 0) for l in self.lines)
        cont = sub * self.contingency / 100.0
        vat = (sub + cont) * 0.15 if self.vat else 0.0
        return sub, cont, vat, sub + cont + vat

    # ----- refresh -----
    def refresh(self):
        self._busy = True
        try:
            self.cont.setValue(self.contingency)
            self.vat_chk.setChecked(self.vat)
            t = self.ptab
            t.setRowCount(len(self.products))
            for r, p in enumerate(self.products):
                pm = pix_from_b64(p.get("photo", ""))
                it = QTableWidgetItem("")
                if not pm.isNull():
                    it.setIcon(QIcon(pm))
                t.setItem(r, 0, it)
                t.setItem(r, 1, QTableWidgetItem(p.get("category", "")))
                t.setItem(r, 2, QTableWidgetItem(" ".join(x for x in (p.get("brand", ""), p.get("name", "")) if x)))
                t.setItem(r, 3, QTableWidgetItem(p.get("supplier", "")))
                pr = QTableWidgetItem(money(p.get("price", 0)))
                pr.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, 4, pr)
                t.setItem(r, 5, QTableWidgetItem("Default" if self.defaults.get(p.get("category")) == p.get("id") else ""))
                lk = QTableWidgetItem("Open page" if p.get("url") else "")
                t.setItem(r, 6, lk)
                t.setRowHeight(r, 60)
            s = self.stab
            for r_ in range(s.rowCount()):
                for c_ in (4, 5, 6):
                    w_ = s.cellWidget(r_, c_)
                    if w_ is not None:
                        w_.hide()
            s.setRowCount(0)
            s.setRowCount(len(self.lines))
            for r, ln in enumerate(self.lines):
                ro = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                ref = QTableWidgetItem("S%02d" % (r + 1))
                ref.setFlags(ro)
                s.setItem(r, 0, ref)
                for c, k in ((1, "floor"), (2, "unit"), (3, "room")):
                    s.setItem(r, c, QTableWidgetItem(str(ln.get(k, ""))))
                cb = QComboBox()
                cb.setEditable(True)
                cb.addItems(CATEGORIES)
                cb.setCurrentText(ln.get("category", ""))
                cb.currentTextChanged.connect(lambda txt, i=r: self._set(i, "category", txt, True))
                s.setCellWidget(r, 4, cb)
                pc = QComboBox()
                pc.addItem("(default)", "")
                for p in self.products:
                    if p.get("category") == ln.get("category"):
                        pc.addItem(" ".join(x for x in (p.get("brand", ""), p.get("name", "")) if x), p.get("id"))
                k = pc.findData(ln.get("product", ""))
                pc.setCurrentIndex(k if k >= 0 else 0)
                pc.currentIndexChanged.connect(lambda _i, i=r, c=pc: self._set(i, "product", c.currentData() or "", True))
                s.setCellWidget(r, 5, pc)
                sbx = QSpinBox()
                sbx.setRange(0, 999)
                sbx.setValue(int(ln.get("qty", 1)))
                sbx.valueChanged.connect(lambda val, i=r: self._set(i, "qty", val, True))
                s.setCellWidget(r, 6, sbx)
                p = self.line_product(ln)
                up = QTableWidgetItem(money(p["price"]) if p else "no product")
                up.setFlags(ro)
                up.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                s.setItem(r, 7, up)
                tt = QTableWidgetItem(money(p["price"] * ln.get("qty", 0)) if p else "")
                tt.setFlags(ro)
                tt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                s.setItem(r, 8, tt)
            sub, cont, vat, tot = self.totals()
            miss = sum(1 for l in self.lines if not self.line_product(l) and l.get("qty"))
            txt = "Subtotal %s" % money(sub)
            if cont:
                txt += "   +  contingency %s" % money(cont)
            if vat:
                txt += "   +  VAT %s" % money(vat)
            txt += "   =   %s" % money(tot)
            if miss:
                txt += "     (%d lines have no product yet)" % miss
            self.total_lbl.setText(txt)
        finally:
            self._busy = False

    # ----- edits -----
    def _set(self, i, key, val, redraw=False):
        if self._busy or not (0 <= i < len(self.lines)):
            return
        self.lines[i][key] = val
        self.lines[i]["auto"] = False
        if key == "category":
            self.lines[i]["product"] = ""
        self._dirty()
        if redraw:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.refresh)

    def _s_edit(self, it):
        if self._busy:
            return
        k = {1: "floor", 2: "unit", 3: "room"}.get(it.column())
        if k:
            self._set(it.row(), k, it.text().strip())

    def _cont_changed(self, v):
        if not self._busy:
            self.contingency = float(v)
            self._dirty()
            self.refresh()

    def _vat_changed(self, on):
        if not self._busy:
            self.vat = bool(on)
            self._dirty()
            self.refresh()

    def _p_click(self, r, c):
        if c == 6 and 0 <= r < len(self.products) and self.products[r].get("url"):
            webbrowser.open(self.products[r]["url"])

    def _sel_product(self):
        r = self.ptab.currentRow()
        return r if 0 <= r < len(self.products) else -1

    def add_product(self, url=""):
        cat = self.find_cat.currentText()
        d = ProductDialog(self, None, cat)
        if url:
            d.url.setText(url)
        if d.exec():
            p = d.result()
            self.products.append(p)
            self.defaults.setdefault(p["category"], p["id"])
            self._dirty()
            self.refresh()

    def add_from_link(self):
        from PySide6.QtWidgets import QApplication
        clip = (QApplication.clipboard().text() or "").strip()
        d = ProductDialog(self, None, self.find_cat.currentText())
        if re.match(r"https?://\S+$", clip):
            d.url.setText(clip)
        if d.exec():
            p = d.result()
            self.products.append(p)
            self.defaults.setdefault(p["category"], p["id"])
            self._dirty()
            self.refresh()

    def edit_product(self):
        r = self._sel_product()
        if r < 0:
            return
        old = self.products[r]
        d = ProductDialog(self, old)
        if d.exec():
            p = d.result()
            self.products[r] = p
            if p["category"] != old.get("category") and self.defaults.get(old.get("category")) == p["id"]:
                self.defaults.pop(old.get("category"), None)
            self.defaults.setdefault(p["category"], p["id"])
            self._dirty()
            self.refresh()

    def remove_product(self):
        r = self._sel_product()
        if r < 0:
            return
        p = self.products.pop(r)
        for k in [k for k, v in self.defaults.items() if v == p["id"]]:
            self.defaults.pop(k)
        for l in self.lines:
            if l.get("product") == p["id"]:
                l["product"] = ""
        self._dirty()
        self.refresh()

    def set_default(self):
        r = self._sel_product()
        if r < 0:
            return
        p = self.products[r]
        self.defaults[p["category"]] = p["id"]
        self._dirty()
        self.refresh()

    def find_online(self):
        cat = self.find_cat.currentText().replace(" (WC)", "").lower()
        site = dict(RETAILERS).get(self.find_shop.currentText())
        q = "%s buy South Africa" % cat + (" site:%s" % site if site else "")
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))

    # ----- schedule -----
    def add_line(self):
        self.lines.append({"room": "", "floor": "", "unit": "", "category": CATEGORIES[0], "product": "", "qty": 1, "auto": False})
        self._dirty()
        self.refresh()
        self.stab.scrollToBottom()

    def remove_line(self):
        r = self.stab.currentRow()
        if 0 <= r < len(self.lines):
            self.lines.pop(r)
            self._dirty()
            self.refresh()

    def clear_lines(self):
        if self.lines and QMessageBox.question(self, "Clear schedule", "Remove every line of the schedule?") == QMessageBox.StandardButton.Yes:
            self.lines = []
            self._dirty()
            self.refresh()

    def build_from_rooms(self, quiet=False):
        try:
            rooms = self.win.read_rooms()
        except Exception:
            rooms = []
        if not rooms:
            if not quiet:
                QMessageBox.information(self, "Costing", "There are no rooms yet. Import the IFC or add rooms in Light && ventilation > Rooms first.")
            return
        keep = [l for l in self.lines if not l.get("auto")]
        new = []
        for rm in rooms:
            for cat, q in fixtures_for(rm.name):
                new.append({"room": _UNIT_PREFIX.sub("", rm.name).strip(), "floor": rm.floor, "unit": rm.unit, "category": cat,
                            "product": "", "qty": q, "auto": True})
        self.lines = new + keep
        self.lines.sort(key=lambda l: (l.get("floor", ""), l.get("unit", ""), l.get("room", ""), CATEGORIES.index(l["category"]) if l["category"] in CATEGORIES else 99))
        self._dirty()
        self.refresh()
        if not quiet:
            n_wet = len({(l["floor"], l["unit"], l["room"]) for l in new})
            self.win.statusBar().showMessage("Schedule built: %d lines in %d rooms." % (len(new), n_wet), 8000)

    # ----- reports -----
    def summary(self):
        """[(category, product text, qty, unit price, total)] added up over the whole building."""
        agg = {}
        for l in self.lines:
            p = self.line_product(l)
            key = (l.get("category", ""), p.get("id") if p else "")
            a = agg.setdefault(key, [l.get("category", ""), p, 0])
            a[2] += l.get("qty", 0)
        return sorted(agg.values(), key=lambda a: CATEGORIES.index(a[0]) if a[0] in CATEGORIES else 99)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export schedule", "Fixture schedule.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Ref", "Level", "Unit", "Room", "Item", "Brand", "Product", "Supplier", "Code", "Qty", "Unit price", "Total", "Link"])
            for i, l in enumerate(self.lines):
                p = self.line_product(l) or {}
                w.writerow(["S%02d" % (i + 1), l.get("floor", ""), l.get("unit", ""), l.get("room", ""), l.get("category", ""),
                            p.get("brand", ""), p.get("name", ""), p.get("supplier", ""), p.get("sku", ""), l.get("qty", 0),
                            "%.2f" % p.get("price", 0), "%.2f" % (p.get("price", 0) * l.get("qty", 0)), p.get("url", "")])
            sub, cont, vat, tot = self.totals()
            w.writerow([])
            w.writerow(["", "", "", "", "", "", "", "", "", "", "Subtotal", "%.2f" % sub])
            if cont:
                w.writerow(["", "", "", "", "", "", "", "", "", "", "Contingency", "%.2f" % cont])
            if vat:
                w.writerow(["", "", "", "", "", "", "", "", "", "", "VAT 15%", "%.2f" % vat])
            w.writerow(["", "", "", "", "", "", "", "", "", "", "Total", "%.2f" % tot])
        self.win.statusBar().showMessage("Schedule saved: " + path, 8000)

    def report_html(self, doc=None):
        import datetime
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        rd = getattr(self.win, "rd", {}) or {}
        out = ['<h2 style="color:%s;">Sanitary ware and fixtures schedule</h2>' % RED,
               '<p style="font-size:9pt;color:#444;">%s &nbsp;|&nbsp; %s</p>' % (e(rd.get("project") or "Project"), datetime.date.today().strftime("%d %B %Y"))]
        n = 0

        def img(p):
            nonlocal n
            if not p or not p.get("photo") or doc is None:
                return ""
            pm = pix_from_b64(p["photo"])
            if pm.isNull():
                return ""
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QTextDocument
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("p%d" % n), pm.toImage())
            n += 1
            return '<img src="p%d" width="70">' % (n - 1)
        th = lambda t, w: '<th bgcolor="%s" width="%d%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left": '<td style="padding:3px;text-align:%s;vertical-align:middle;">%s</td>' % (a, t)
        out.append("<h3>Totals by item</h3>")
        rows = ""
        for cat, p, q in self.summary():
            pr = (p or {}).get("price", 0)
            rows += "<tr>%s%s%s%s%s</tr>" % (td(img(p)), td(e(cat)), td(e(" ".join(x for x in ((p or {}).get("brand", ""), (p or {}).get("name", "")) if x) or "no product chosen")
                                                              + (("<br><span style='font-size:7.5pt;color:#555;'>%s</span>" % e(p.get("supplier", ""))) if p and p.get("supplier") else "")),
                                              td(str(q), "center"), td(money(pr * q), "right"))
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s%s%s</tr>%s</table>' %
                   (th("", 10), th("Item", 16), th("Product", 46), th("Qty", 8), th("Cost", 20), rows))
        out.append("<h3>Where each fixture goes</h3>")
        rows = ""
        for i, l in enumerate(self.lines):
            p = self.line_product(l) or {}
            rows += "<tr>%s%s%s%s%s%s%s</tr>" % (td("S%02d" % (i + 1)), td(e(l.get("floor", ""))), td(e(l.get("unit", ""))), td(e(l.get("room", ""))),
                                                 td(e(l.get("category", ""))), td(str(l.get("qty", 0)), "center"), td(money(p.get("price", 0) * l.get("qty", 0)), "right"))
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s%s%s%s%s</tr>%s</table>' %
                   (th("Ref", 7), th("Level", 18), th("Unit", 9), th("Room", 26), th("Item", 20), th("Qty", 6), th("Cost", 14), rows))
        sub, cont, vat, tot = self.totals()
        t = '<tr>%s%s</tr>' % (td("Subtotal"), td(money(sub), "right"))
        if cont:
            t += '<tr>%s%s</tr>' % (td("Contingency %g %%" % self.contingency), td(money(cont), "right"))
        if vat:
            t += '<tr>%s%s</tr>' % (td("VAT 15 %"), td(money(vat), "right"))
        t += '<tr>%s%s</tr>' % (td("<b>Total</b>"), td("<b>%s</b>" % money(tot), "right"))
        out.append('<p></p><table width="45%%" align="right" border="0.6" cellspacing="0" style="font-size:9pt;">%s</table>' % t)
        out.append('<p style="font-size:7.5pt;color:#666;">Prices are the shop prices captured on the dates shown in the product list and '
                   'must be confirmed with the supplier before ordering. %s</p>' % ("Prices exclude VAT." if self.vat else "Prices include VAT."))
        return "".join(out)

    def write_pdf(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        w.setTitle("Fixture schedule")
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.report_html(d) + "</body></html>")
        d.print_(w)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export fixture schedule", "Fixture schedule.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.write_pdf(path)
        QMessageBox.information(self, "Costing", "PDF saved:\n" + path)
