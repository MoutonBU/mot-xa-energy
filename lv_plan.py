"""Plan view for the Light & Ventilation check: the rooms are drawn on a plan and coloured pass / check / fail, with a room
list on the left and an inspector (light, ventilation, what-if) on the right.

Real room outlines come from the IFC model when one is loaded (read in the background); with no model the rooms are laid out
as a schematic, each box sized by its floor area, so the screen still works. Everything here reads the host window's results
(host.results) and never changes them, except 'Apply' which widens one window in the Windows or Doors table."""
import math
import re
import threading

from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

FILL = {"ok": "#143a2a", "warn": "#40300c", "fail": "#6b1a26", "na": "#26262c"}
EDGE = {"ok": "#7ee2ae", "warn": "#ffcf6b", "fail": "#ff7a8a", "na": "#8a8a96"}
WORD = {"ok": "Pass", "warn": "Check", "fail": "Fail", "na": "Not required"}
PILL = {"ok": ("#143a2a", "#7ee2ae"), "warn": ("#40300c", "#ffcf6b"), "fail": ("#41161d", "#ff9aa8"), "na": ("#26262c", "#c4c4cc")}


def room_status(res):
    """fail: light or ventilation short. check: passes but needs a look. na: passage / no area."""
    if res.get("circulation"):
        return "na"
    if not res["light_ok"] or not res["vent_ok"]:
        return "fail"
    if res.get("art_used") or not res.get("glaze_ok", True) or res.get("missing") or res.get("assumed") or res.get("internal"):
        return "warn"
    return "ok"


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def schematic_layout(rows):
    """rows: [(key, area_m2)] -> {key: [(x, y) x4]} boxes in metres, area-true, packed in shelves."""
    rows = [(k, max(float(a or 0.0), 1.5)) for k, a in rows]
    if not rows:
        return {}
    total = sum(a for _k, a in rows)
    width = math.sqrt(total * 1.7)
    out, x, y, rowh = {}, 0.0, 0.0, 0.0
    for k, a in sorted(rows, key=lambda r: -r[1]):
        w = math.sqrt(a * 1.35)
        h = a / w
        if x + w > width and x > 0:
            x, y, rowh = 0.0, y + rowh, 0.0
        out[k] = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        x += w
        rowh = max(rowh, h)
    return out


class PlanView(QGraphicsView):
    room_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#101013")))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._items = {}
        self._press = None

    def set_rooms(self, rooms, windows, selected=None, note=""):
        """rooms: [{key, poly [(x,y) m], label, status}]; windows: [[(x0,y0),(x1,y1)]] m."""
        sc = self.scene()
        sc.clear()
        self._items = {}
        if not rooms:
            t = sc.addSimpleText(note or "No rooms to show yet. Run the compliance check.")
            t.setBrush(QBrush(QColor("#a0a0aa")))
            self.fit()
            return
        for r in rooms:
            poly = QPolygonF([QPointF(x * 100.0, -y * 100.0) for x, y in r["poly"]])
            it = QGraphicsPolygonItem(poly)
            it.setBrush(QBrush(QColor(FILL[r["status"]])))
            it.setPen(QPen(QColor(EDGE[r["status"]]), 3))
            it.setData(0, r["key"])
            it.setAcceptHoverEvents(True)
            it.setToolTip("%s: %s" % (r["label"], WORD[r["status"]]))
            sc.addItem(it)
            self._items[r["key"]] = it
            br = it.boundingRect()
            t = QGraphicsSimpleTextItem(r["label"])
            f = QFont("Inter")
            f.setPixelSize(int(max(14, min(30, br.width() / max(4, len(r["label"])) * 1.5))))
            f.setWeight(QFont.Weight.DemiBold)
            t.setFont(f)
            t.setBrush(QBrush(QColor("#f2f2f4")))
            tb = t.boundingRect()
            t.setPos(br.center().x() - tb.width() / 2, br.center().y() - tb.height() / 2)
            t.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            t.setZValue(5)
            sc.addItem(t)
        for (x0, y0), (x1, y1) in windows:
            xa, xb = sorted((x0 * 100.0, x1 * 100.0))
            ya, yb = sorted((-y0 * 100.0, -y1 * 100.0))
            w, h = max(xb - xa, 12), max(yb - ya, 12)
            wi = QGraphicsRectItem(xa - (w - (xb - xa)) / 2, ya - (h - (yb - ya)) / 2, w, h)
            wi.setBrush(QBrush(QColor("#7ac8ff")))
            wi.setPen(QPen(Qt.PenStyle.NoPen))
            wi.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            wi.setZValue(3)
            sc.addItem(wi)
        m = 120
        b = sc.itemsBoundingRect()
        sc.setSceneRect(b.adjusted(-m, -m, m, m))
        self.select(selected)
        self.fit()

    def select(self, key):
        for k, it in self._items.items():
            pen = it.pen()
            sel = (k == key)
            pen.setWidth(8 if sel else 3)
            if sel:
                pen.setColor(QColor("#ffffff"))
            it.setPen(pen)
            it.setZValue(1 if sel else 0)

    def fit(self):
        self.resetTransform()
        r = self.scene().sceneRect()
        if r.width() > 0:
            self.fitInView(r, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, f):
        self.scale(f, f)

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        p = e.position().toPoint()
        if self._press is not None and (p - self._press).manhattanLength() < 5:
            it = self.itemAt(p)
            while it is not None and it.data(0) is None:
                it = it.parentItem()
            if it is not None:
                self.room_clicked.emit(str(it.data(0)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()


class Meter(QWidget):
    """a bar with the actual value and a mark at the required value"""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(16)
        self.actual, self.need, self.colour = 0.0, 1.0, "#4cc38a"

    def set(self, actual, need, colour):
        self.actual, self.need, self.colour = float(actual), float(need) if need else 1.0, colour
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        top = (self.need * 1.25) or 1.0
        p.setBrush(QColor("#2a2a31"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 4, w, 8, 4, 4)
        p.setBrush(QColor(self.colour))
        p.drawRoundedRect(0, 4, int(w * min(self.actual / top, 1.0)), 8, 4, 4)
        x = int(w * min(self.need / top, 1.0))
        p.setBrush(QColor("#f2f2f4"))
        p.drawRect(x - 1, 0, 2, 16)


def _pill(status):
    bg, fg = PILL[status]
    return "background:%s;color:%s;border-radius:11px;padding:3px 10px;font-weight:600;font-size:12px;" % (bg, fg)


class PlanPage(QWidget):
    def __init__(self, host, geo_fn=None):
        super().__init__()
        self.host, self.geo_fn = host, geo_fn
        self.geo = None
        self.geo_path = None
        self._thread = None
        self._res = {}
        self.key = None
        self.setStyleSheet(
            "QWidget{color:#f2f2f4;} PlanPage{background:#0e0e10;}"
            "QListWidget{background:#131316;border:1px solid #26262c;border-radius:10px;padding:4px;font-size:13px;}"
            "QListWidget::item{padding:7px 8px;border-radius:8px;}QListWidget::item:selected{background:#221517;border:1px solid #e0243a;color:#fff;}"
            "QFrame#card{background:#17171b;border:1px solid #2a2a30;border-radius:14px;}QLabel{background:transparent;}"
            "QComboBox,QSpinBox{background:#1f1f24;border:1px solid #3a3a42;border-radius:8px;padding:5px 8px;min-height:24px;}"
            "QPushButton{background:#1f1f24;border:1px solid #3a3a42;border-radius:9px;padding:8px 14px;font-weight:500;}"
            "QPushButton:hover{background:#2a2a31;}"
            "QPushButton#primary{background:#e0243a;border-color:#e0243a;color:#fff;font-weight:600;}"
            "QPushButton#primary:disabled{background:#4a2a30;border-color:#4a2a30;color:#9a8a8c;}")
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        left = QVBoxLayout()
        self.floor_box = QComboBox()
        self.floor_box.currentIndexChanged.connect(self._floor_changed)
        left.addWidget(self.floor_box)
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#a0a0aa;font-size:11px;font-weight:600;")
        left.addWidget(self.count_lbl)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentItemChanged.connect(lambda cur, _p: cur and self.select(cur.data(Qt.ItemDataRole.UserRole)))
        left.addWidget(self.list, 1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(230)
        root.addWidget(lw)

        mid = QVBoxLayout()
        self.view = PlanView()
        self.view.room_clicked.connect(self.select)
        mid.addWidget(self.view, 1)
        bar = QHBoxLayout()
        self.note = QLabel("")
        self.note.setStyleSheet("color:#a0a0aa;font-size:12px;")
        bar.addWidget(self.note, 1)
        for txt, fn in (("Fit", self.view.fit), ("+", lambda: self.view.zoom(1.25)), ("−", lambda: self.view.zoom(0.8))):
            b = QPushButton(txt)
            b.setFixedWidth(46 if txt == "Fit" else 36)
            b.clicked.connect(fn)
            bar.addWidget(b)
        mid.addLayout(bar)
        root.addLayout(mid, 1)

        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(360)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(6)
        head = QHBoxLayout()
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet("font-size:20px;font-weight:700;")
        self.pill = QLabel("")
        head.addWidget(self.name_lbl, 1)
        head.addWidget(self.pill)
        cl.addLayout(head)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color:#c9c9d2;font-size:13px;")
        cl.addWidget(self.msg)
        cl.addSpacing(8)
        self.l_title, self.l_vals, self.l_meter = self._block(cl, "NATURAL LIGHT")
        cl.addSpacing(6)
        self.v_title, self.v_vals, self.v_meter = self._block(cl, "VENTILATION")
        cl.addSpacing(10)
        k = QLabel("WHAT IF")
        k.setStyleSheet("color:#a0a0aa;font-size:11px;font-weight:600;")
        cl.addWidget(k)
        row = QHBoxLayout()
        self.win_box = QComboBox()
        self.win_box.currentIndexChanged.connect(self._whatif)
        self.dw = QSpinBox()
        self.dw.setRange(0, 3000)
        self.dw.setSingleStep(100)
        self.dw.setSuffix(" mm wider")
        self.dw.setMinimumWidth(150)
        self.dw.valueChanged.connect(self._whatif)
        row.addWidget(self.win_box, 1)
        row.addWidget(self.dw)
        cl.addLayout(row)
        self.then = QLabel("")
        self.then.setWordWrap(True)
        self.then.setStyleSheet("font-size:13px;color:#c9c9d2;")
        cl.addWidget(self.then)
        self.apply_btn = QPushButton("Apply to this window")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply)
        cl.addWidget(self.apply_btn)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color:#a0a0aa;font-size:11.5px;")
        cl.addWidget(self.warn)
        cl.addStretch(1)
        row2 = QHBoxLayout()
        b1 = QPushButton("Windows list")
        b1.clicked.connect(lambda: host._goto_lv(0))
        b2 = QPushButton("Results table")
        b2.clicked.connect(lambda: host._goto_lv(3))
        row2.addWidget(b1)
        row2.addWidget(b2)
        cl.addLayout(row2)
        root.addWidget(card)

        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._poll_geo)

    def _block(self, lay, title):
        t = QLabel(title)
        t.setStyleSheet("color:#a0a0aa;font-size:11px;font-weight:600;")
        lay.addWidget(t)
        v = QLabel("")
        v.setStyleSheet("font-size:13px;")
        lay.addWidget(v)
        m = Meter()
        lay.addWidget(m)
        return t, v, m

    # ---- data ------------------------------------------------------------
    def refresh(self):
        """called after every compliance check"""
        results = getattr(self.host, "results", None) or []
        self._res = {self._key(r): r for r in results}
        floors = list(dict.fromkeys(r["floor"] for r in results))
        cur = self.floor_box.currentText()
        self.floor_box.blockSignals(True)
        self.floor_box.clear()
        self.floor_box.addItems(floors)
        if cur in floors:
            self.floor_box.setCurrentText(cur)
        self.floor_box.blockSignals(False)
        self._maybe_read_geo()
        self._redraw()

    @staticmethod
    def _key(r):
        return "%s|%s|%s" % (r["floor"], r.get("unit", ""), r["room"])

    def _maybe_read_geo(self):
        path = (getattr(self.host, "ifc_data", None) or {}).get("path")
        if not path or not self.geo_fn or path == self.geo_path or self._thread is not None:
            return
        self.geo_path = path
        self.note.setText("Reading room outlines from the model...")
        box = {}

        def work():
            try:
                box["geo"] = self.geo_fn(path)
            except Exception as ex:
                box["err"] = str(ex)
        self._box = box
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        self._poll.start()

    def _poll_geo(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._poll.stop()
        self._thread = None
        self.geo = self._box.get("geo")
        if not self.geo:
            self.geo_path = None if "err" not in self._box else self.geo_path
        self._redraw()

    def _geo_for_floor(self, floor, results):
        """-> (rooms with real outlines, windows) or None when the model has nothing matching"""
        if not self.geo:
            return None
        spaces = [s for s in self.geo["spaces"] if _norm(s["storey"]) == _norm(floor)] or self.geo["spaces"]
        by_name = {}
        for s in spaces:
            by_name.setdefault(_norm(s["name"]), []).append(s)
        out, used = {}, set()
        for r in results:
            c = [s for s in by_name.get(_norm(r["room"]), []) if id(s) not in used]
            if c:
                s = min(c, key=lambda s_: abs(s_["area"] - float(r.get("area") or 0.0)))
                used.add(id(s))
                out[self._key(r)] = s["poly"]
        if len(out) < max(1, len(results) // 2):
            return None
        stor = {s["storey"] for s in spaces}
        wins = []
        for o in self.geo["openings"]:
            if o["kind"] == "Window" and (not stor or o["storey"] in stor):
                xs = [p[0] for p in o["xy"]]
                ys = [p[1] for p in o["xy"]]
                wins.append([(min(xs), min(ys)), (max(xs), max(ys))])
        return out, wins

    def _redraw(self):
        floor = self.floor_box.currentText()
        results = [r for r in (getattr(self.host, "results", None) or []) if r["floor"] == floor]
        self.list.blockSignals(True)
        self.list.clear()
        for r in results:
            st = room_status(r)
            it = QListWidgetItem("●  %s    %.1f m²" % (r["room"], r.get("area") or 0.0))
            it.setForeground(QBrush(QColor(EDGE[st])))
            it.setData(Qt.ItemDataRole.UserRole, self._key(r))
            self.list.addItem(it)
        self.list.blockSignals(False)
        allr = getattr(self.host, "results", None) or []
        bad = sum(1 for r in allr if room_status(r) == "fail")
        self.count_lbl.setText("ROOMS · %d OF %d PASS" % (sum(1 for r in allr if room_status(r) in ("ok", "warn", "na")), len(allr)) if allr else "ROOMS")
        real = self._geo_for_floor(floor, results)
        if real:
            polys, wins = real
            self.note.setText("Room outlines from the IFC model. Click a room to inspect it.")
        else:
            polys = schematic_layout([(self._key(r), r.get("area")) for r in results])
            wins = []
            self.note.setText("Schematic: each box is sized by its floor area. Load an IFC model for the real plan.")
        rooms = [{"key": self._key(r), "poly": polys[self._key(r)], "label": r["room"], "status": room_status(r)}
                 for r in results if self._key(r) in polys]
        if self.key not in self._res or self._res[self.key]["floor"] != floor:
            self.key = self._key(results[0]) if results else None
        self.view.set_rooms(rooms, wins, self.key, "Run the compliance check to see the plan.")
        self._fill_inspector()

    def _floor_changed(self, _i):
        self.key = None
        self._redraw()

    def select(self, key):
        if key not in self._res:
            return
        self.key = key
        self.view.select(key)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == key:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
        self._fill_inspector()

    # ---- inspector -------------------------------------------------------
    def _fill_inspector(self):
        r = self._res.get(self.key)
        if not r:
            self.name_lbl.setText("No room")
            self.pill.setText("")
            self.msg.setText("Run the compliance check, then click a room.")
            for w in (self.l_vals, self.v_vals, self.then, self.warn):
                w.setText("")
            self.apply_btn.setEnabled(False)
            return
        st = room_status(r)
        self.name_lbl.setText(r["room"])
        self.pill.setText(WORD[st])
        self.pill.setStyleSheet(_pill(st))
        self._msg(r, st)
        self.l_vals.setText("%.2f m² glazing    needs %.2f m² (%.1f %%)" % (r["glazed"], r["light_req"], r["light_pct"]))
        self.l_meter.set(r["glazed"], r["light_req"], "#4cc38a" if r["light_ok"] else "#ff7a8a")
        self.v_vals.setText("%.2f m² opening    needs %.2f m² (%.1f %%)" % (r["openable"], r["vent_req"], r["vent_pct"]))
        self.v_meter.set(r["openable"], r["vent_req"], "#4cc38a" if r["vent_ok"] else "#ff7a8a")
        self.win_box.blockSignals(True)
        self.win_box.clear()
        for tag in r.get("tags", []):
            self.win_box.addItem(tag)
        self.win_box.blockSignals(False)
        self._whatif()

    def _msg(self, r, st):
        if st == "na":
            self.msg.setText("Passage or circulation space: no natural light or ventilation area is required.")
            return
        bits = []
        if not r["light_ok"]:
            bits.append("Light is %.2f m² short." % (r["light_req"] - r["glazed"]))
        if not r["vent_ok"]:
            bits.append("Ventilation is %.2f m² short." % (r["vent_req"] - r["openable"]))
        if st == "warn":
            if r.get("art_used"):
                bits.append("Relies on artificial light: confirm your council accepts this.")
            if not r.get("glaze_ok", True):
                bits.append("Glazing is over the limit: a rational design is needed.")
            if r.get("missing"):
                bits.append("Unknown window tags: " + ", ".join(r["missing"]) + ".")
            if r.get("assumed"):
                bits.append("100 % glass assumed for " + ", ".join(r["assumed"]) + ".")
            if r.get("internal"):
                bits.append("Internal room: check mechanical ventilation.")
        self.msg.setText(" ".join(bits) or "Light and ventilation both comply.")

    def _tag_row(self, tag):
        for t in (self.host.sched_table, self.host.door_table):
            for i in range(t.rowCount()):
                it = t.item(i, 0)
                if it and it.text().strip().upper() == tag.strip().upper():
                    return t, i
        return None, -1

    def _whatif(self, *_a):
        r = self._res.get(self.key)
        tag = self.win_box.currentText()
        ok = False
        if r and tag:
            try:
                op = self.host.read_schedule().get(tag.upper()) or self.host.read_schedule().get(tag)
            except Exception:
                op = None
            if op is not None and op.width_mm > 0:
                f = (op.width_mm + self.dw.value()) / op.width_mm
                n = float(r["tags"][tag])
                g = r["glazed"] + op.glazed_m2 * (f - 1) * n
                v = r["openable"] + op.openable_m2 * (f - 1) * n
                lok = g >= r["light_req"] - 1e-9 or r["circulation"]
                vok = v >= r["vent_req"] - 1e-9 or r["circulation"]
                self.then.setText("Then: light %.2f m² (%s), ventilation %.2f m² (%s). %s is %d mm wide now."
                                  % (g, "passes" if lok else "still short", v, "passes" if vok else "still short", tag, op.width_mm))
                self.l_meter.set(g, r["light_req"], "#4cc38a" if lok else "#ff7a8a")
                self.v_meter.set(v, r["vent_req"], "#4cc38a" if vok else "#ff7a8a")
                self.warn.setText("Changes every room that uses %s, and the Windows list. Estimates scale the glass and opening with the width." % tag)
                ok = self.dw.value() > 0
        if not ok:
            self.then.setText("Pick a window and how much wider to try." if (r and tag) else "This room has no windows listed.")
            self.warn.setText("")
            if r:
                self.l_meter.set(r["glazed"], r["light_req"], "#4cc38a" if r["light_ok"] else "#ff7a8a")
                self.v_meter.set(r["openable"], r["vent_req"], "#4cc38a" if r["vent_ok"] else "#ff7a8a")
        self.apply_btn.setEnabled(ok)

    def _apply(self):
        tag = self.win_box.currentText()
        t, i = self._tag_row(tag)
        if t is None or not self.dw.value():
            return
        try:
            old = float(t.item(i, 1).text())
        except Exception:
            return
        new = old + self.dw.value()
        ga = t.item(i, 11)
        if ga is not None and ga.text().strip():
            try:
                ga.setText("%.3f" % (float(ga.text()) * new / old))
            except Exception:
                pass
        t.item(i, 1).setText("%g" % new)
        self.dw.setValue(0)
        self.host.run_check(goto=False)
