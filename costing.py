"""Costing tab: a priced fixture schedule (toilets, basins, showers, sinks, taps ...) built from the project's rooms.

* Products: a small catalogue you build up. Paste a shop link and the program reads the name, price and photo from the
  page; or type it in. One product per item can be the default for the whole building.
* Schedule: one line per fixture and room (level, unit, room, item, product, quantity, price). "Build from rooms" fills it
  from the Rooms list by room name; every line stays editable.
* Totals: subtotal, contingency and VAT, and a PDF / CSV schedule with the product photos.

Everything is stored in the project file (the photos are kept as small thumbnails inside it)."""
import base64
import csv
import os
import html as _html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QInputDialog, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

CATEGORIES = ["Toilet (WC)", "Basin", "Basin mixer", "Shower", "Shower head", "Shower mixer", "Bath", "Bath mixer", "Kitchen sink",
              "Kitchen mixer", "Laundry tub", "Urinal", "Vanity cabinet", "Mirror", "Towel rail", "Other"]

# room name (after the unit prefix is removed) -> fixtures to put in it. First match wins.
FIXTURE_RULES = [
    (r"\b(wc|toilet|cloak|powder)", [("Toilet (WC)", 1), ("Basin", 1), ("Basin mixer", 1)]),
    (r"\b(bath|ensuite|en-suite|shower)", [("Toilet (WC)", 1), ("Basin", 1), ("Basin mixer", 1), ("Shower", 1), ("Shower head", 1), ("Shower mixer", 1)]),
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
# ----- the costings the program keeps for you (one file each, saved by itself, independent of any project)
COST_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MCP_LightVent", "costings")


def cost_list():
    out = []
    try:
        for fn in os.listdir(COST_DIR):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(COST_DIR, fn), encoding="utf-8") as f:
                        out.append((fn[:-5], str(json.load(f).get("name", fn[:-5]))))
                except Exception:
                    pass
    except OSError:
        pass
    return sorted(out, key=lambda x: x[1].lower())


def cost_load(cid):
    try:
        with open(os.path.join(COST_DIR, cid + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cost_save(cid, name, state):
    try:
        os.makedirs(COST_DIR, exist_ok=True)
        tmp = os.path.join(COST_DIR, cid + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"name": name, "saved": time.time(), "state": state}, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(COST_DIR, cid + ".json"))
        return True
    except Exception:
        return False


def cost_last(set_to=None):
    fp = os.path.join(COST_DIR, "_last.txt")
    try:
        if set_to is not None:
            os.makedirs(COST_DIR, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(set_to)
            return set_to
        with open(fp, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


class CostingPage(QWidget):
    is_costing = True
    ifc_done = Signal(object, str)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.products = []          # {id, category, brand, name, supplier, sku, url, price, price_date, photo, notes}
        self.defaults = {}          # category -> product id
        self.lines = []             # {room, floor, unit, category, product ("" = the default), qty, auto, note}
        self.contingency = 0.0
        self.vat = False
        self._busy = False
        self.cid, self.cname, self._loaded, self._saving = "", "", False, False
        self.what, self.linked, self.link_ok, self.host = "costing", False, True, win
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        cb = QHBoxLayout()
        cb.addWidget(QLabel("<b>Costing:</b>"))
        self.cbox = QComboBox()
        self.cbox.setMinimumWidth(240)
        self.cbox.setToolTip("Every costing is kept by the program and saves itself. It does not depend on the project that is open, but you can still pull rooms, fixtures and sizes from the open project.")
        self.cbox.activated.connect(self._cost_picked)
        cb.addWidget(self.cbox)
        for txt, tip, fn in (("+ New costing...", "Starts a new, empty costing, for example for a new job.", self.cost_new),
                             ("Rename...", "Changes the name of this costing.", self.cost_rename),
                             ("Delete", "Removes this costing (asks first).", self.cost_delete),
                             ("Save a copy...", "Writes this costing to a file, as a backup or to open on another computer.", self.cost_export),
                             ("Open a copy...", "Brings in a costing from a file saved with Save a copy.", self.cost_import)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            cb.addWidget(b)
        cb.addStretch(1)
        v.addLayout(cb)
        from ui_extras import LinkBar
        self.link_bar = LinkBar(self)
        v.addWidget(self.link_bar)
        QTimer.singleShot(0, lambda: None if self._loaded else self.set_state({}))
        from PySide6.QtWidgets import QTabWidget
        self.main = QTabWidget()
        v.addWidget(self.main, 1)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.main.addTab(sp, "Fixtures and sanitary ware")
        try:
            import materials
            self.materials = materials.MaterialsPage(self)
            self.main.addTab(self.materials, "Building materials")
        except Exception:
            self.materials = None
        self.summary_page = SummaryPage(self)
        self.main.addTab(self.summary_page, "Whole building and budget")
        self.main.currentChanged.connect(lambda i: self.summary_page.refresh() if self.main.widget(i) is self.summary_page else None)

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
        pb.addWidget(QLabel("Or open the shops:"))
        self.find_cat = QComboBox()
        self.find_cat.addItems(CATEGORIES[:-1])
        self.find_shop = QComboBox()
        for n, _s in RETAILERS:
            self.find_shop.addItem(n)
        ai = QPushButton("Find product (AI)...")
        ai.setToolTip("Describe the item or give a picture of the look you want. The program searches South African online shops and "
                      "lists real products with their name, code, price and photo.")
        ai.clicked.connect(self.find_ai)
        pb.insertWidget(0, ai)
        fb = QPushButton("Web search")
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
        for text, fn in (("Add line", self.add_line), ("Remove line", self.remove_line), ("Clear schedule", self.clear_lines),
                         ("Preview PDF", self.preview_pdf), ("Export PDF", self.export_pdf)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            sb.addWidget(bb)
        sb.addStretch(1)
        sv.addLayout(sb)
        self.stab = QTableWidget(0, 10)
        self.stab.setHorizontalHeaderLabels(["Ref", "Level", "Unit", "Room", "Item", "Product", "Qty", "Unit price", "Total", "Source"])
        self.stab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stab.verticalHeader().setVisible(False)
        h = self.stab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate((56, 110, 60, 150, 170, 0, 76, 110, 110, 90)):
            if w:
                self.stab.setColumnWidth(i, w)
        self.stab.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.stab.itemChanged.connect(self._s_edit)
        from PySide6.QtWidgets import QTabWidget
        self.sub_tabs = QTabWidget()
        self.sub_tabs.addTab(self.stab, "Schedule")
        self.ttab = QTableWidget(0, 6)
        self.ttab.setHorizontalHeaderLabels(["Photo", "Item", "Product", "Qty", "Unit price", "Cost"])
        self.ttab.setIconSize(QSize(60, 45))
        self.gtab = QTableWidget(0, 4)
        self.gtab.setHorizontalHeaderLabels(["Level", "Unit", "Fixtures", "Cost"])
        for t_, st_ in ((self.ttab, 2), (self.gtab, 0)):
            t_.verticalHeader().setVisible(False)
            t_.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t_.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sub_tabs.addTab(self.ttab, "Tally by item")
        self.sub_tabs.addTab(self.gtab, "Cost by level and unit")
        sv.addWidget(self.sub_tabs)
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
        """What the project file keeps: nothing when you unlinked it, otherwise the costing with its id (the program's own copy wins on opening)."""
        if not self.link_ok:
            return None
        d = self._state()
        d["cid"], d["cname"] = self.cid, self.cname
        self.linked = True
        self.link_bar.refresh()
        return d

    def _state(self):
        return {"products": self.products, "defaults": self.defaults, "lines": self.lines,
                "contingency": self.contingency, "vat": self.vat,
                "materials": self.materials.state() if getattr(self, "materials", None) else None,
                "budget": self.summary_page.state() if getattr(self, "summary_page", None) else None}

    @staticmethod
    def _has_data(d):
        return bool(d.get("products") or d.get("lines") or d.get("materials") or d.get("budget"))

    def set_state(self, d):
        """From a project (or empty). The costing kept by the program wins over the copy inside the project."""
        d = d or {}
        if self._loaded:
            self.save_costing()
        cid, name, st = d.get("cid") or "", "", None
        if cid:
            rec = cost_load(cid)
            if rec:
                st, name = rec.get("state"), rec.get("name", "")
        if st is None and self._has_data(d):
            cid = cid or "c%d" % int(time.time() * 1000)
            name = d.get("cname") or "Imported costing"
            st = d
        if st is None:
            last = cost_last()
            rec = cost_load(last) if last else None
            if rec:
                cid, name, st = last, rec.get("name", ""), rec.get("state")
            elif self._loaded and self.cid:
                return
            else:
                cid, name, st = "c%d" % int(time.time() * 1000), "My costing", {}
        self.linked = bool(d.get("cid")) and st is not None and cid == d.get("cid")
        self.link_ok = True
        self._cswitch(cid, name, st)

    def _cswitch(self, cid, name, st):
        self.cid, self.cname = cid, name
        self._loaded = False
        self._apply_state(st)
        self._loaded = True
        cost_last(cid)
        self.save_costing()
        self._cost_combo()
        self.link_bar.refresh()

    def _cost_combo(self):
        self.cbox.blockSignals(True)
        self.cbox.clear()
        for cid, nm in cost_list():
            self.cbox.addItem(nm, cid)
        i = self.cbox.findData(self.cid)
        if i >= 0:
            self.cbox.setCurrentIndex(i)
        self.cbox.blockSignals(False)

    def save_costing(self):
        if self.cid and self._loaded and not self._saving:
            self._saving = True
            try:
                cost_save(self.cid, self.cname, self._state())
            finally:
                self._saving = False

    def _autosave(self):
        if not getattr(self, "_save_timer", None):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_costing)
        self._save_timer.start(800)

    def _cost_picked(self, i):
        cid = self.cbox.itemData(i)
        if not cid or cid == self.cid:
            return
        self.save_costing()
        rec = cost_load(cid)
        if rec:
            self._cswitch(cid, rec.get("name", ""), rec.get("state"))
        else:
            self._cost_combo()

    def cost_new(self):
        name, ok = QInputDialog.getText(self, "New costing", "Name of the costing (for example the job or house):")
        name = name.strip()
        if not ok or not name:
            return
        self.save_costing()
        self._cswitch("c%d" % int(time.time() * 1000), name, {})

    def cost_rename(self):
        name, ok = QInputDialog.getText(self, "Rename costing", "New name:", text=self.cname)
        name = name.strip()
        if not ok or not name:
            return
        self.cname = name
        self.save_costing()
        self._cost_combo()

    def cost_delete(self):
        if QMessageBox.question(self, "Delete costing", "Delete the costing \"%s\" with all its products, lines and budget? This cannot be undone." % self.cname) != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(os.path.join(COST_DIR, self.cid + ".json"))
        except OSError:
            pass
        rest = cost_list()
        self._loaded = False
        if rest:
            rec = cost_load(rest[0][0])
            self._cswitch(rest[0][0], rec.get("name", ""), rec.get("state"))
        else:
            self._cswitch("c%d" % int(time.time() * 1000), "My costing", {})

    def cost_export(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save a copy of this costing", (self.cname or "costing") + ".mcpcost", "Costing (*.mcpcost)")
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"name": self.cname, "state": self._state()}, f, ensure_ascii=False)
        except OSError as ex:
            QMessageBox.warning(self, "Save a copy", "Could not save the file: %s" % ex)

    def cost_import(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open a copy of a costing", "", "Costing (*.mcpcost)")
        if not fn:
            return
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            st, name = d["state"], str(d.get("name") or "Costing")
        except Exception:
            QMessageBox.warning(self, "Open a copy", "That file is not a costing.")
            return
        if name in [n for _i, n in cost_list()]:
            name += " (copy)"
        self.save_costing()
        self._cswitch("c%d" % int(time.time() * 1000), name, st)

    def _apply_state(self, d):
        d = d or {}
        self.products = [dict(p) for p in d.get("products", []) if isinstance(p, dict)]
        self.defaults = dict(d.get("defaults", {}) or {})
        self.lines = [dict(x) for x in d.get("lines", []) if isinstance(x, dict)]
        self.contingency = float(d.get("contingency", 0) or 0)
        self.vat = bool(d.get("vat", False))
        if getattr(self, "materials", None):
            self.materials.set_state(d.get("materials"))
        if getattr(self, "summary_page", None):
            self.summary_page.set_state(d.get("budget"))
        self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.link_bar.refresh()

    def _dirty(self):
        if self._loaded:
            self._autosave()
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

    def tally_groups(self):
        """[(level, unit, fixture count, cost)] over the whole schedule."""
        g = {}
        for l in self.lines:
            p = self.line_product(l)
            k = (l.get("floor", ""), l.get("unit", ""))
            a = g.setdefault(k, [0, 0.0])
            a[0] += l.get("qty", 0)
            a[1] += (p or {}).get("price", 0) * l.get("qty", 0)
        return [(k[0], k[1], v[0], v[1]) for k, v in sorted(g.items())]

    def _fill_tally(self):
        t = self.ttab
        rows = self.summary()
        t.setRowCount(len(rows) + 1)
        for r, (cat, p, q) in enumerate(rows):
            it = QTableWidgetItem("")
            pm = pix_from_b64((p or {}).get("photo", ""))
            if not pm.isNull():
                it.setIcon(QIcon(pm))
            t.setItem(r, 0, it)
            t.setItem(r, 1, QTableWidgetItem(cat))
            t.setItem(r, 2, QTableWidgetItem(" ".join(x for x in ((p or {}).get("brand", ""), (p or {}).get("name", "")) if x) or "no product chosen"))
            t.setItem(r, 3, QTableWidgetItem(str(q)))
            t.setItem(r, 4, QTableWidgetItem(money((p or {}).get("price", 0))))
            t.setItem(r, 5, QTableWidgetItem(money((p or {}).get("price", 0) * q)))
            t.setRowHeight(r, 50)
        n = len(rows)
        t.setItem(n, 1, QTableWidgetItem("Total"))
        t.setItem(n, 3, QTableWidgetItem(str(sum(q for _c, _p, q in rows))))
        t.setItem(n, 5, QTableWidgetItem(money(self.totals()[0])))
        for c_ in (1, 3, 5):
            f_ = t.item(n, c_).font()
            f_.setBold(True)
            t.item(n, c_).setFont(f_)
        g = self.tally_groups()
        self.gtab.setRowCount(len(g))
        for r, (lv, un, q, c) in enumerate(g):
            for c_, v in enumerate((lv, un, str(q), money(c))):
                self.gtab.setItem(r, c_, QTableWidgetItem(v))

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
                src = QTableWidgetItem(ln.get("source", "Manual"))
                src.setFlags(ro)
                if ln.get("ifc_type"):
                    src.setToolTip("IFC object: " + ln["ifc_type"])
                s.setItem(r, 9, src)
            self._fill_tally()
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
            if getattr(self, "summary_page", None):
                self.summary_page.refresh()
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

    def find_ai(self):
        d = FinderDialog(self, self.find_cat.currentText())
        sp = getattr(self, "summary_page", None)
        if sp is not None:
            mx = sp.max_price(self.find_cat.currentText())
            if mx > 0:
                d.budget.setValue(round(mx, -1))
                d.status.setText("Price limit set from your target cost per m2 (the most each %s can cost). Change it if you like." % self.find_cat.currentText())
        d.exec()

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
        """Read the fixtures out of the IFC (when one is loaded), add what the room names call for, and fill the schedule."""
        try:
            rooms = [(r.name, r.floor, r.unit) for r in self.win.read_rooms()]
        except Exception:
            rooms = []
        path = getattr(self.win, "ifc_path", "") or (getattr(self.win, "ifc_data", None) or {}).get("path", "")
        if path and os.path.exists(path):
            self._rooms_pending, self._quiet = rooms, quiet
            self.win.statusBar().showMessage("Reading the fixtures from the IFC model...", 15000)

            def work():
                try:
                    self.ifc_done.emit(read_ifc_fixtures(path), "")
                except Exception as e:
                    self.ifc_done.emit([], str(e))
            if not getattr(self, "_ifc_wired", False):
                self.ifc_done.connect(self._ifc_read)
                self._ifc_wired = True
            threading.Thread(target=work, daemon=True).start()
            return
        self._fill_lines([], rooms, quiet, "")

    def _ifc_read(self, items, err):
        self._fill_lines(items, self._rooms_pending, self._quiet, err)

    def _fill_lines(self, items, rooms, quiet, err):
        if not items and not rooms:
            if not quiet:
                QMessageBox.information(self, "Costing", "There are no rooms or fixtures yet. Import the IFC, or add rooms in Light && ventilation > Rooms.")
            return
        keep = [l for l in self.lines if not l.get("auto")]
        new = schedule_lines(items, rooms)
        self.lines = new + keep
        self.ifc_found = {}
        for it in items:
            self.ifc_found[it["category"]] = self.ifc_found.get(it["category"], 0) + 1
        self._dirty()
        self.refresh()
        if quiet:
            return
        found = ", ".join("%d x %s" % (n, c) for c, n in sorted(self.ifc_found.items(), key=lambda x: CATEGORIES.index(x[0]) if x[0] in CATEGORIES else 99))
        from_rules = sum(1 for l in new if l.get("source") == "Room name")
        msg = ("The IFC holds: %s." % found) if found else "The IFC holds no sanitary fixtures."
        if err:
            msg = "The IFC could not be read (%s)." % err
        if from_rules:
            msg += ("\n\n%d lines were added from the room names for fixtures that are not in the model (marked 'Room name' in the "
                    "Source column). Check them: a model that does not draw its toilets, basins and taps cannot be counted." % from_rules)
        QMessageBox.information(self, "Schedule built", msg)

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
        out.append("<h3>Cost by level and unit</h3>")
        rows = "".join("<tr>%s%s%s%s</tr>" % (td(e(lv)), td(e(un)), td(str(q), "center"), td(money(c), "right")) for lv, un, q, c in self.tally_groups())
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s%s</tr>%s</table>' %
                   (th("Level", 40), th("Unit", 20), th("Fixtures", 15), th("Cost", 25), rows))
        sub, cont, vat, tot = self.totals()
        n_fix = sum(l.get("qty", 0) for l in self.lines)
        out.append('<p></p><table width="100%%" border="0" cellspacing="0" cellpadding="8"><tr><td bgcolor="#F4F4F4" style="font-size:10pt;">'
                   '<b>%d fixtures</b> in %d lines &nbsp;&nbsp; <b>Estimated cost of fittings: %s</b>%s</td></tr></table>' %
                   (n_fix, len(self.lines), money(tot), " (excluding VAT)" if self.vat is False and False else ""))
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

    # ----- building materials (the ribbon calls these) -----
    def mat_show(self):
        self.main.setCurrentIndex(1)

    def mat_read(self):
        self.mat_show()
        if self.materials:
            self.materials.add_current() if not self.materials.blocks else self.materials.read_all()

    def mat_preview(self):
        self.mat_show()
        if self.materials:
            self.materials.preview_pdf()

    def mat_export(self):
        self.mat_show()
        if self.materials:
            self.materials.export_pdf()

    def preview_pdf(self):
        try:
            self.win.preview_pdf_report(self.write_pdf, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, "Costing", "The preview could not be shown (%s). Use Export PDF." % e)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export fixture schedule", "Fixture schedule.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.write_pdf(path)
        QMessageBox.information(self, "Costing", "PDF saved:\n" + path)


# ---------------- reading the fixtures out of the IFC ----------------
_IFC_SKIP = {"IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcBeam", "IfcColumn", "IfcRoof", "IfcWindow", "IfcDoor", "IfcSpace",
             "IfcOpeningElement", "IfcBuildingElementPart", "IfcMember", "IfcStair", "IfcStairFlight", "IfcCovering", "IfcRailing",
             "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcCurtainWall", "IfcPlate", "IfcFooting", "IfcRamp", "IfcRampFlight"}

# (pattern, category): first match wins. The library code in an Archicad name (WC120) is not a toilet, so it is removed first.
_IFC_WORDS = [
    (r"shower\s*(head|rose|arm|hose)|hand\s*shower|rain\s*shower", "Shower head"),
    (r"shower.*(mixer|tap|valve|control)|(mixer|tap|valve).*shower", "Shower mixer"),
    (r"shower", "Shower"),
    (r"bath\s*(tub)?\s*(mixer|tap|filler)|(mixer|tap).*\bbath\b", "Bath mixer"),
    (r"\bbath(tub)?\b|\bbathtub\b", "Bath"),
    (r"(kitchen|sink).*(mixer|faucet|\btap)|(mixer|faucet|\btap).*(kitchen|sink)", "Kitchen mixer"),
    (r"(basin|whb|wash\s*hand|lavatory).*(mixer|faucet|\btap)|(mixer|faucet|\btap).*(basin|whb|wash\s*hand|lavatory)", "Basin mixer"),
    (r"urinal", "Urinal"),
    (r"toilet|water\s*closet|\bwc\b|\bwc\s*pan|cistern|lavatory\s*pan", "Toilet (WC)"),
    (r"wash\s*hand|washbasin|wash\s*basin|hand\s*basin|\bwhb\b|lavatory|\bbasin\b|\bvanity\s*basin", "Basin"),
    (r"laundry|utility\s*sink|wash\s*trough|scullery\s*tub", "Laundry tub"),
    (r"\bsink\b|kitchen\s*sink", "Kitchen sink"),
    (r"mixer|faucet|\btap\b|\btaps\b", "Basin mixer"),
    (r"vanity|bathroom\s*cabinet|basin\s*cabinet", "Vanity cabinet"),
    (r"mirror", "Mirror"),
    (r"towel\s*rail|towel\s*rack|heated\s*rail", "Towel rail"),
]
_IFC_PREDEF = {"BATH": "Bath", "SHOWER": "Shower", "SINK": "Kitchen sink", "TOILETPAN": "Toilet (WC)", "URINAL": "Urinal",
               "WASHHANDBASIN": "Basin", "CISTERN": "Toilet (WC)"}


def classify_fixture(*texts, predef=""):
    """The fixture category for the names of an IFC element, or None when it is not a sanitary fixture."""
    if predef and str(predef).upper() in _IFC_PREDEF:
        return _IFC_PREDEF[str(predef).upper()]
    t = " ".join(str(x) for x in texts if x)
    t = re.sub(r"\b[A-Za-z]{1,3}\d{2,}\b", " ", t).lower()          # library codes such as WC120
    for pat, cat in _IFC_WORDS:
        if re.search(pat, t):
            return cat
    return None


def _norm_room(name):
    return re.sub(r"[^a-z0-9]", "", _UNIT_PREFIX.sub("", str(name or "")).lower())


def _unit_of(name):
    m = _UNIT_PREFIX.match(str(name or "").strip())
    if not m:
        return ""
    d = re.search(r"\d+", m.group(0))
    return "U" + d.group(0) if d else ""


def read_ifc_fixtures(path):
    """[{category, type, floor, unit, room, ifc_class}] for every sanitary fixture, tap, shower part and sink in the IFC.
    Rooms come from the room named in the element's own properties (Archicad writes 'Room: U1-Bath 1' there)."""
    import ifcopenshell
    import ifcopenshell.util.element as UE
    f = ifcopenshell.open(path)
    out, seen = [], set()
    for e in f.by_type("IfcProduct"):
        cls = e.is_a()
        if cls in _IFC_SKIP or any(cls == k for k in _IFC_SKIP):
            continue
        t = None
        try:
            t = UE.get_type(e)
        except Exception:
            pass
        tname = (t.Name if t is not None else "") or ""
        cat = classify_fixture(tname, getattr(e, "ObjectType", ""), e.Name, getattr(e, "Description", ""),
                               predef=getattr(e, "PredefinedType", "") or getattr(t, "PredefinedType", "") or "")
        if not cat:
            continue
        room, floor = "", ""
        try:
            for ps in UE.get_psets(e).values():
                for v in ps.values():
                    if isinstance(v, str):
                        m = re.search(r"Room:\s*(.+?)\s*$", v)
                        if m:
                            room = m.group(1)
                        m = re.search(r"Stor(?:e)?y:\s*(.+?)\s+Room:", v)
                        if m:
                            floor = m.group(1)
        except Exception:
            pass
        try:
            c = UE.get_container(e)
            if c is not None and not floor:
                floor = c.Name or ""
        except Exception:
            pass
        try:
            import ifcopenshell.util.placement as PL
            pt = tuple(round(float(x), 1) for x in PL.get_local_placement(e.ObjectPlacement)[:3, 3])
        except Exception:
            pt = ()
        key = (cat, tname, floor, room, pt)
        if pt and key in seen:
            continue
        seen.add(key)
        out.append(dict(category=cat, type=tname or e.Name or "", floor=floor, unit=_unit_of(room), room=_UNIT_PREFIX.sub("", room).strip(),
                        ifc_class=cls))
    return out


def schedule_lines(ifc_items, rooms):
    """Fixture lines from the IFC items, plus fixtures the room names call for that the IFC does not hold.
    rooms: [(name, floor, unit)]. A room that has an IFC item of a category gets the IFC count for it, not the rule."""
    lines, have = [], {}
    for it in ifc_items:
        k = (it["floor"], it["unit"], _norm_room(it["room"]), it["category"])
        have[k] = have.get(k, 0) + 1
    shown = {}
    for it in ifc_items:
        k = (it["floor"], it["unit"], it["room"], it["category"])
        shown[k] = shown.get(k, 0) + 1
    for (floor, unit, room, cat), q in shown.items():
        lines.append({"room": room, "floor": floor, "unit": unit, "category": cat, "product": "", "qty": q, "auto": True, "source": "IFC",
                      "ifc_type": next((i["type"] for i in ifc_items if (i["floor"], i["unit"], i["room"], i["category"]) == (floor, unit, room, cat)), "")})
    for name, floor, unit in rooms:
        bare = _UNIT_PREFIX.sub("", name).strip()
        for cat, q in fixtures_for(name):
            if have.get((floor, unit, _norm_room(name), cat)):
                continue
            lines.append({"room": bare, "floor": floor, "unit": unit, "category": cat, "product": "", "qty": q, "auto": True,
                          "source": "Room name"})
    lines.sort(key=lambda l: (l.get("floor", ""), l.get("unit", ""), l.get("room", ""), CATEGORIES.index(l["category"]) if l["category"] in CATEGORIES else 99))
    return lines


# ---------------- whole building and budget ----------------
# relative cost of one of each fixture, used to share the sanitary-ware budget out when no products are chosen yet
try:
    from materials import NON_CEILING
except Exception:
    NON_CEILING = re.compile(r'stoep|patio|carport|balcon|veranda|terrace|garage|roof', re.I)
DEFAULT_W = {"Toilet (WC)": 1.0, "Basin": 0.6, "Basin mixer": 0.3, "Shower": 1.8, "Shower head": 0.3, "Shower mixer": 0.5, "Bath": 1.5,
             "Bath mixer": 0.4, "Kitchen sink": 1.0, "Kitchen mixer": 0.35, "Laundry tub": 0.6, "Urinal": 0.8, "Vanity cabinet": 1.0,
             "Mirror": 0.2, "Towel rail": 0.2, "Other": 0.3}
AREA_BASES = ["Floor slabs of the IFC (gross)", "Rooms list (net, this project's block)", "Typed in"]


def mon0(x):
    try:
        return "R " + "{:,.0f}".format(float(x)).replace(",", " ")
    except Exception:
        return "R 0"


class SummaryPage(QWidget):
    """Fixtures and building materials together: cost, cost per m2, and a budget worked backwards from a target rand per m2."""

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.basis, self.manual, self.target, self.fx_share = 0, 0.0, 0.0, 8.0
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        top = QFormLayout()
        self.basis_box = QComboBox()
        self.basis_box.addItems(AREA_BASES)
        self.manual_spin = QDoubleSpinBox()
        self.manual_spin.setRange(0, 10_000_000)
        self.manual_spin.setSuffix(" m2")
        self.manual_spin.setDecimals(1)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0, 1_000_000)
        self.target_spin.setPrefix("R ")
        self.target_spin.setSuffix(" per m2")
        self.target_spin.setDecimals(0)
        self.target_spin.setSpecialValueText("no target")
        self.target_spin.setToolTip("The cost per square metre you want the building built for. The budget for every part is worked from it.")
        self.share_spin = QDoubleSpinBox()
        self.share_spin.setRange(0, 60)
        self.share_spin.setSuffix(" % of the budget")
        self.share_spin.setToolTip("How much of the budget goes to sanitary ware. An assumption of mine (around 5 to 10 % for a house): change it.")
        ar = QHBoxLayout()
        ar.addWidget(self.basis_box, 1)
        ar.addWidget(self.manual_spin)
        top.addRow("Floor area used", ar)
        top.addRow("Target cost", self.target_spin)
        top.addRow("Sanitary ware share", self.share_spin)
        v.addLayout(top)
        self.big = QLabel("")
        self.big.setStyleSheet("font-weight:700; font-size:16px; padding:6px 0;")
        self.big.setWordWrap(True)
        v.addWidget(self.big)
        self.ctab = QTableWidget(0, 6)
        self.ctab.setHorizontalHeaderLabels(["Part of the cost", "Estimate", "R per m2", "Share", "Budget at the target", "Over (+) / under (-)"])
        self.ftab = QTableWidget(0, 6)
        self.ftab.setHorizontalHeaderLabels(["Fixture", "Number", "Budget for the item", "Most to pay each", "Product chosen costs", "Check"])
        for t in (self.ctab, self.ftab):
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.ctab, 3)
        lab = QLabel("Sanitary ware, worked from the budget (use these as the price limit when you search for products):")
        v.addWidget(lab)
        v.addWidget(self.ftab, 3)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray; font-size: 11px;")
        v.addWidget(self.note)
        for w_, sig in ((self.basis_box, "currentIndexChanged"), (self.manual_spin, "valueChanged"), (self.target_spin, "valueChanged"),
                        (self.share_spin, "valueChanged")):
            getattr(w_, sig).connect(self._edited)
        self.refresh()

    def state(self):
        return {"basis": self.basis, "manual": self.manual, "target": self.target, "fx_share": self.fx_share}

    def set_state(self, d):
        d = d or {}
        self.basis, self.manual = int(d.get("basis", 0) or 0), float(d.get("manual", 0) or 0)
        self.target, self.fx_share = float(d.get("target", 0) or 0), float(d.get("fx_share", 8.0) or 0)
        self.refresh()

    def _edited(self, *_a):
        if self._busy:
            return
        self.basis, self.manual = self.basis_box.currentIndex(), self.manual_spin.value()
        self.target, self.fx_share = self.target_spin.value(), self.share_spin.value()
        self.refresh()

    # ----- numbers -----
    def area(self):
        m = getattr(self.host, "materials", None)
        if self.basis == 2:
            return self.manual
        if not m:
            return 0.0
        tot = 0.0
        proj = m._project_ifc()
        for b in m.blocks:
            n = max(1, int(b.get("repeat", 1)))
            if self.basis == 1 and b.get("path") == proj:
                tot += sum(r[1] for r in m.rooms_full() if not NON_CEILING.search(r[0] or "")) * n
            elif b.get("q"):
                tot += float(b["q"].get("slab_area", 0)) * n
        return tot

    def fx_mult(self):
        m = getattr(self.host, "materials", None)
        if not m:
            return 1
        proj = m._project_ifc()
        for b in m.blocks:
            if b.get("path") == proj:
                return max(1, int(b.get("repeat", 1)))
        return 1

    def components(self):
        """[(group, all-in cost)] (breakage, preliminaries, profit, contingency, fees and VAT spread over the groups) and the total."""
        m = getattr(self.host, "materials", None)
        rows = m.group_costs() if m and m.blocks else []
        return rows, sum(c for _n, c in rows)

    def fixture_budget(self):
        """{category: (number, budget, most each)} when a target is set."""
        area = self.area()
        if not (self.target > 0 and area > 0):
            return {}
        budget = self.target * area * self.fx_share / 100.0
        mult = self.fx_mult()
        qty = {}
        for l in self.host.lines:
            qty[l.get("category", "")] = qty.get(l.get("category", ""), 0) + l.get("qty", 0) * mult
        wsum = sum(DEFAULT_W.get(c, 0.3) * n for c, n in qty.items())
        out = {}
        for c, n in qty.items():
            if n and wsum:
                b = budget * DEFAULT_W.get(c, 0.3) * n / wsum
                out[c] = (n, b, b / n)
        return out

    def max_price(self, category):
        r = self.fixture_budget().get(category)
        return r[2] if r else 0.0

    def refresh(self):
        self._busy = True
        try:
            self.basis_box.setCurrentIndex(self.basis)
            self.manual_spin.setValue(self.manual)
            self.manual_spin.setEnabled(self.basis == 2)
            self.target_spin.setValue(self.target)
            self.share_spin.setValue(self.fx_share)
            area = self.area()
            rows, total = self.components()
            budget = self.target * area if self.target > 0 and area > 0 else 0.0
            per = (total / area) if area > 0 else 0.0
            txt = "Whole building: %s" % mon0(total)
            if area > 0:
                txt += "   on %s m2   =   %s per m2" % ("{:,.0f}".format(area).replace(",", " "), mon0(per))
            else:
                txt += "   (read the quantities on the Building materials tab to get the floor area)"
            if budget:
                diff = total - budget
                txt += "\nBudget at %s per m2: %s   |   the estimate is %s %s the budget" % (mon0(self.target), mon0(budget), mon0(abs(diff)), "over" if diff > 0 else "under")
            self.big.setText(txt)
            t = self.ctab
            t.setRowCount(len(rows) + 1)
            for r, (name, c) in enumerate(rows + [("Total", total)]):
                if budget and name == "Total":
                    bud = budget
                elif budget and name.startswith("Sanitary"):
                    bud = budget * self.fx_share / 100.0
                elif budget:
                    others = sum(c2 for n2, c2 in rows if not n2.startswith("Sanitary"))
                    bud = budget * (100.0 - self.fx_share) / 100.0 * c / others if others else 0.0
                else:
                    bud = 0.0
                vals = (name, mon0(c), mon0(c / area) if area else "", "%.1f %%" % (100.0 * c / total) if total else "",
                        mon0(bud) if budget else "", mon0(c - bud) if budget else "")
                for ci, tx in enumerate(vals):
                    it = QTableWidgetItem(tx)
                    if ci:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if name == "Total":
                        f_ = it.font()
                        f_.setBold(True)
                        it.setFont(f_)
                    t.setItem(r, ci, it)
            fb = self.fixture_budget()
            ft = self.ftab
            cats = sorted(fb, key=lambda c: CATEGORIES.index(c) if c in CATEGORIES else 99)
            ft.setRowCount(len(cats))
            mult = self.fx_mult()
            for r, c in enumerate(cats):
                n, b, each = fb[c]
                p = None
                for l in self.host.lines:
                    if l.get("category") == c:
                        p = self.host.line_product(l)
                        break
                price = (p or {}).get("price", 0)
                chk = "no product yet" if not p else ("over by %s each" % mon0(price - each) if price > each else "within")
                for ci, tx in enumerate((c, str(n), mon0(b), mon0(each), mon0(price) if p else "", chk)):
                    it = QTableWidgetItem(tx)
                    if ci in (1, 2, 3, 4):
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    ft.setItem(r, ci, it)
            self.note.setText(("Fixtures are counted %d time%s (the repeats of this project's block). " % (mult, "" if mult == 1 else "s")) +
                              "Sanitary ware gets the share of the budget set above; the rest is split between the building parts in the proportions of the "
                              "current estimate. The fixture budget is shared by typical relative cost: a guide, not a quotation." if budget else
                              "Type a target cost per m2 above to see the budget for each part and the most you can pay for each fixture.")
        finally:
            self._busy = False


# ---------------- AI product finder ----------------
FINDER_PROMPT = """You are helping an architect price the sanitary ware of a building in South Africa. Use web search to find \
real products that are for sale on South African online shops{shops}.

Item wanted: {item}
Description: {desc}
{budget}{image}
Return up to {n} products in total, the best value first.
Return ONLY JSON, no other text, in this form:
{{"looks": "one line on the style you matched", "products": [{{"item": "one of: {cats}", "name": "the product's own title as shown on the shop page (brand, model and description)", "brand": "", "sku": "the product code shown on the page", "price_zar": 1499.0, "supplier": "shop name", "url": "the product page", "image_url": "the main product photo", "match": "one short line on why it fits"}}]}}

Rules:
- name is the product title itself, for example "Maya white round rimless close-coupled toilet". It is never a web address.
- sku is the product / item code printed on the page. Leave it empty if the page shows none. Never guess a code.
- price_zar is the price in rand shown on the page, 0 if none is shown.
- url must be the page of that one product, not a search page or a category page.
- Only list products you actually found. Do not invent products, codes, prices or links. Fewer is fine."""


def _walk_urls(blocks):
    """Every URL that web search returned, so a link the model gives can be checked against them."""
    out = set()
    for b in blocks:
        if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            for r in b["content"]:
                if isinstance(r, dict) and r.get("url"):
                    out.add(r["url"])
    return out


ZA_SHOPS = ["italtile.com", "builders.co.za", "buco.co.za", "cashbuild.co.za", "takealot.com", "plumblink.co.za", "pricecheck.co.za",
            "leroymerlin.co.za", "bathroomwarehouse.co.za", "tileafrica.co.za", "ctm.co.za", "agrimark.co.za"]


def ai_search(M, prompt, images_b64=(), max_uses=None, max_tokens=2500, domains=None):
    """Ask Claude with live web search. Returns (reply text, set of URLs that the search returned).
    M is the program's main module (settings and the plain request live there)."""
    st = M.SETTINGS
    if not str(st.get("provider", "")).startswith("Claude"):
        raise RuntimeError("Product search needs the Claude (Anthropic) provider, which has web search. "
                           "Change the provider in Online mode.")
    key = st.get("api_key", "").strip()
    model = (st.get("search_model") or "").strip() or "claude-haiku-5-5"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}} for b in images_b64]
    content.append({"type": "text", "text": prompt})
    msgs = [{"role": "user", "content": content}]
    # every search costs 1 cent and its results are read as tokens, so the number of searches and the sites searched are kept small
    uses = int(max_uses or st.get("search_uses") or 5)
    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": max(1, min(20, uses)),
            "user_location": {"type": "approximate", "country": "ZA"}}
    if domains is None and st.get("search_za_only", True):
        domains = ZA_SHOPS
    if domains:
        tool["allowed_domains"] = list(domains)
    urls, text = set(), ""

    def post(body):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            raise RuntimeError("Claude said: %s (code %s). If it mentions web search, switch web search on for your key in the "
                               "Anthropic console." % (msg or e.reason, e.code))
        except urllib.error.URLError as e:
            raise RuntimeError("No internet connection (%s)" % e.reason)
        if hasattr(M, "ai_track"):
            M.ai_track(data.get("usage"), "Claude", model)
        return data

    def texts(blocks):
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    stop = ""
    for _ in range(6):                                   # a long search can pause; carry on
        data = post({"model": model, "max_tokens": max_tokens, "messages": msgs, "tools": [tool]})
        blocks = data.get("content", [])
        urls |= _walk_urls(blocks)
        text = texts(blocks)
        stop = data.get("stop_reason")
        if stop == "pause_turn":
            msgs.append({"role": "assistant", "content": blocks})
            continue
        break
    if "{" not in text or stop in ("max_tokens", "pause_turn"):
        # the model searched but did not give the list (or ran out of room): ask for it now, without more searching
        msgs.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "..."}]})
        msgs.append({"role": "user", "content": [{"type": "text", "text": "Now give the result as the JSON only, from what you have found so far. "
                                                  "No other text. If you found nothing for an item, leave it out."}]})
        data = post({"model": model, "max_tokens": max_tokens, "messages": msgs, "tools": [tool], "tool_choice": {"type": "none"}})
        urls |= _walk_urls(data.get("content", []))
        text = texts(data.get("content", [])) or text
    return text, urls


def parse_finder_json(text):
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("The search did not come back with a product list. Try again, or describe the item more closely.")
    d = json.loads(t[a:b + 1])
    out = []
    for p in d.get("products", []) or []:
        if not isinstance(p, dict) or not str(p.get("name", "")).strip():
            continue
        name = str(p["name"]).strip()
        if re.match(r"https?://", name, re.I):          # a link is not a name
            continue
        out.append(dict(item=str(p.get("item") or "").strip(), name=name, brand=str(p.get("brand") or "").strip(),
                        sku=str(p.get("sku") or "").strip(), price=_num(p.get("price_zar") or p.get("price") or 0),
                        supplier=str(p.get("supplier") or "").strip(), url=str(p.get("url") or "").strip(),
                        image=str(p.get("image_url") or "").strip(), match=str(p.get("match") or "").strip()))
    return str(d.get("looks") or ""), out


def verify_products(prods, found_urls, fetch_fn=None, img_fn=None):
    """Open each product page and check it. Returns the products that are real, each with 'verified' and 'photo'.
    A page that cannot be opened is kept only if the web search itself returned that link."""
    fetch_fn = fetch_fn or fetch
    out, lock = [], threading.Lock()

    def one(p):
        p = dict(p)
        p["verified"], p["photo"] = False, ""
        page = None
        if p["url"]:
            try:
                page = parse_product_html(fetch_fn(p["url"]), p["url"])
                p["verified"] = True
            except Exception:
                page = None
        if page is None and p["url"] not in found_urls:
            return
        if page:
            if page["price"]:
                p["price"] = page["price"]
            p["sku"] = p["sku"] or page["sku"]
            p["brand"] = p["brand"] or page["brand"]
            p["supplier"] = p["supplier"] or page["supplier"]
            p["image"] = page["image"] or p["image"]
        if p["image"]:
            try:
                data = (img_fn or (lambda u: fetch(u, binary=True)))(p["image"])
                p["photo"] = thumb_b64(QImage.fromData(data))
            except Exception:
                pass
        with lock:
            out.append(p)
    ts = [threading.Thread(target=one, args=(p,), daemon=True) for p in prods]
    for t in ts:
        t.start()
    for t in ts:
        t.join(40)
    out.sort(key=lambda p: (p["price"] <= 0, p["price"]))   # cheapest first, unpriced last
    return out


class FinderDialog(QDialog):
    done = Signal(object, str, str)

    def __init__(self, page, category=""):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("Find a product online")
        self.resize(1050, 640)
        self.ref = []                       # reference pictures (base64 PNG)
        self.results = []
        v = QVBoxLayout(self)
        info = QLabel("Describe the item, or give a picture of the look you want (a catalogue page, a photo, a screenshot). The program searches "
                      "South African online shops with Claude, opens each product page to check the name, code, price and photo, and lists "
                      "the matches cheapest first.")
        info.setWordWrap(True)
        v.addWidget(info)
        f = QFormLayout()
        self.item = QComboBox()
        self.item.addItem("(any fixture in the picture)")
        self.item.addItems(CATEGORIES[:-1])
        if category:
            self.item.setCurrentText(category)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("e.g. white round rimless floor-standing toilet, soft-close seat, concealed cistern")
        row = QHBoxLayout()
        self.shop = QComboBox()
        for n, _s in RETAILERS:
            self.shop.addItem(n)
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0, 1_000_000)
        self.budget.setPrefix("up to R ")
        self.budget.setSpecialValueText("no price limit")
        self.budget.setDecimals(0)
        self.count = QSpinBox()
        self.count.setRange(1, 12)
        self.count.setValue(6)
        self.count.setSuffix(" results")
        row.addWidget(self.shop)
        row.addWidget(self.budget)
        row.addWidget(self.count)
        row.addStretch(1)
        pr = QHBoxLayout()
        self.pic = QLabel("No picture")
        self.pic.setFixedSize(150, 100)
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setStyleSheet("border:1px solid #888;")
        b1, b2, b3 = QPushButton("Choose picture..."), QPushButton("Paste picture"), QPushButton("Remove")
        b1.clicked.connect(self._choose)
        b2.clicked.connect(self._paste)
        b3.clicked.connect(self._clear)
        pr.addWidget(self.pic)
        pb = QVBoxLayout()
        pb.addWidget(b1)
        pb.addWidget(b2)
        pb.addWidget(b3)
        pr.addLayout(pb)
        pr.addStretch(1)
        f.addRow("Item", self.item)
        f.addRow("Description", self.desc)
        f.addRow("Shop / budget", row)
        f.addRow("Look wanted", pr)
        v.addLayout(f)
        go = QHBoxLayout()
        self.go = QPushButton("Search")
        self.go.clicked.connect(self.search)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        go.addWidget(self.go)
        go.addWidget(self.status, 1)
        v.addLayout(go)
        self.tab = QTableWidget(0, 7)
        self.tab.setHorizontalHeaderLabels(["Add", "Photo", "Product", "Code", "Supplier", "Price", "Why it fits"])
        self.tab.setIconSize(QSize(84, 63))
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate((46, 96, 0, 110, 130, 100, 0)):
            if w:
                self.tab.setColumnWidth(i, w)
        self.tab.cellDoubleClicked.connect(self._open)
        v.addWidget(self.tab, 1)
        bb = QHBoxLayout()
        self.add = QPushButton("Add ticked products to the list")
        self.add.clicked.connect(self._add)
        op = QPushButton("Open product page")
        op.clicked.connect(lambda: self._open(self.tab.currentRow(), 0))
        cl = QPushButton("Close")
        cl.clicked.connect(self.accept)
        bb.addWidget(self.add)
        bb.addWidget(op)
        bb.addStretch(1)
        bb.addWidget(cl)
        v.addLayout(bb)
        self.done.connect(self._finished)

    # reference picture
    def _set_pic(self, img):
        if img is None or img.isNull():
            return
        big = max(img.width(), img.height())
        if big > 1600:
            img = img.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.convertToFormat(QImage.Format.Format_RGB32).save(buf, "PNG")
        self.ref = [base64.b64encode(bytes(ba)).decode("ascii")]
        self.pic.setPixmap(QPixmap.fromImage(img).scaled(self.pic.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Picture of the look wanted", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._set_pic(QImage(path))

    def _paste(self):
        from PySide6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if img.isNull():
            self.status.setText("There is no picture on the clipboard.")
        else:
            self._set_pic(img)

    def _clear(self):
        self.ref = []
        self.pic.setPixmap(QPixmap())
        self.pic.setText("No picture")

    # search
    def prompt(self):
        item = self.item.currentText()
        any_item = item.startswith("(")
        shop = dict(RETAILERS).get(self.shop.currentText())
        b = self.budget.value()
        return FINDER_PROMPT.format(
            shops=(" (prefer %s, the product pages must be on that site)" % shop) if shop else "",
            item="every fixture shown in the picture (find matches for each, at most 3 per fixture)" if any_item else item,
            desc=self.desc.text().strip() or "(see the picture)",
            budget=("Budget: no more than R %d each, including VAT.\n" % b) if b else "",
            image=("The attached picture shows the look wanted (shape, colour, mounting, finish). Find products that look as close to it "
                   "as you can.\n") if self.ref else "",
            n=self.count.value() * (2 if any_item else 1), cats=", ".join(CATEGORIES))

    def search(self):
        if self.item.currentText().startswith("(") and not self.ref:
            self.status.setText("Give a picture, or pick the item.")
            return
        M = sys.modules[type(self.page.win).__module__]
        if not M.online_ready():
            QMessageBox.information(self, "Find a product", "Product search uses Claude with web search. Switch on Online mode and enter your "
                                    "API key first (the Offline / Online AI button at the top right, or Tools > Online mode).")
            try:
                self.page.win.online_settings()
            except Exception:
                pass
            if not M.online_ready():
                return
        self.go.setEnabled(False)
        self.status.setText("Searching the shops... this takes a minute or two.")
        prompt, imgs = self.prompt(), list(self.ref)

        def work():
            try:
                site = dict(RETAILERS).get(self.shop.currentText())
                text, urls = ai_search(M, prompt, imgs, max_tokens=3500, domains=[site] if site else None)
                looks, prods = parse_finder_json(text)
                if not prods:
                    self.done.emit([], "", "The search found no matching products. Try a simpler description or another shop.")
                    return
                self.done.emit(verify_products(prods, urls), looks, "")
            except Exception as e:
                self.done.emit(None, "", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, res, looks, err):
        self.go.setEnabled(True)
        if res is None or err:
            self.status.setText(err or "Nothing found.")
            if res is None:
                return
        self.results = res
        n_ok = sum(1 for p in res if p.get("verified"))
        if res:
            self.status.setText(("Matched style: %s. " % looks if looks else "") +
                                "%d products, %d opened and checked on the shop page. Prices change: confirm before ordering." % (len(res), n_ok))
        t = self.tab
        t.setRowCount(len(res))
        for r, p in enumerate(res):
            c = QTableWidgetItem("")
            c.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            c.setCheckState(Qt.CheckState.Checked if r == 0 else Qt.CheckState.Unchecked)
            t.setItem(r, 0, c)
            ph = QTableWidgetItem("")
            pm = pix_from_b64(p.get("photo", ""))
            if not pm.isNull():
                ph.setIcon(QIcon(pm))
            t.setItem(r, 1, ph)
            t.setItem(r, 2, QTableWidgetItem(p["name"] + ("" if p.get("verified") else "   (page not checked)")))
            t.setItem(r, 3, QTableWidgetItem(p.get("sku", "")))
            t.setItem(r, 4, QTableWidgetItem(p.get("supplier", "")))
            pr = QTableWidgetItem(money(p["price"]) if p["price"] else "see page")
            pr.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(r, 5, pr)
            t.setItem(r, 6, QTableWidgetItem(p.get("match", "")))
            t.setRowHeight(r, 68)

    def _open(self, r, _c):
        if 0 <= r < len(self.results) and self.results[r].get("url"):
            webbrowser.open(self.results[r]["url"])

    def _add(self):
        import datetime
        import uuid
        added = 0
        for r, p in enumerate(self.results):
            it = self.tab.item(r, 0)
            if it is None or it.checkState() != Qt.CheckState.Checked:
                continue
            cat = p.get("item") if p.get("item") in CATEGORIES else (self.item.currentText() if self.item.currentText() in CATEGORIES else "Other")
            if any(q.get("url") == p["url"] and p["url"] for q in self.page.products):
                continue
            prod = dict(id=uuid.uuid4().hex[:8], category=cat, brand=p.get("brand", ""), name=p["name"], supplier=p.get("supplier", ""),
                        sku=p.get("sku", ""), url=p.get("url", ""), price=p.get("price", 0), photo=p.get("photo", ""),
                        price_date="read " + datetime.date.today().isoformat(), notes=p.get("match", ""))
            self.page.products.append(prod)
            self.page.defaults.setdefault(cat, prod["id"])
            added += 1
        self.page.refresh()
        self.status.setText("%d product%s added to the Products list." % (added, "" if added == 1 else "s"))
