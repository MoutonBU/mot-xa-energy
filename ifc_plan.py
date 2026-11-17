"""Floor plan from the IFC model itself.

Every storey is cut with a horizontal plane 1.1 m above its floor, so the plan shows exactly what the model contains:
walls, windows, doors, stairs and the rooms (IfcSpace). Rooms are coloured by the light / ventilation result.
Reading the model takes a few seconds, so it runs in a background thread and is kept for the next visit."""
import math
import os
import threading

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

CUT_HEIGHT = 1.1
_CACHE = {}          # (path, mtime) -> plan dict
_LOCK = threading.Lock()


def _segments(v, f, z):
    """Where the triangles of one mesh cross the plane at height z: a list of ((x1, y1), (x2, y2))."""
    import numpy as np
    tri = v[f]                                   # (n, 3, 3)
    d = tri[:, :, 2] - z
    keep = ~((d > 0).all(axis=1) | (d < 0).all(axis=1))
    out = []
    for t, dd in zip(tri[keep], d[keep]):
        pts = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            if (dd[i] > 0) != (dd[j] > 0) and dd[i] != dd[j]:
                k = dd[i] / (dd[i] - dd[j])
                pts.append(t[i][:2] + (t[j][:2] - t[i][:2]) * k)
        if len(pts) == 2 and float(np.linalg.norm(pts[0] - pts[1])) > 1e-6:
            out.append((tuple(pts[0]), tuple(pts[1])))
    return out


def _polys(v, f, z):
    """Closed outlines of one element at height z. Open meshes fall back to their flat faces, then to thick lines."""
    import numpy as np
    from shapely.geometry import LineString, MultiPolygon, Polygon
    from shapely.ops import polygonize, unary_union
    segs = _segments(v, f, z)
    if not segs:
        return []
    lines = unary_union([LineString(s) for s in segs])
    polys = list(polygonize(lines))
    if not polys:
        tri = []
        for a, b, c in f:
            p0, p1, p2 = v[a], v[b], v[c]
            n = np.cross(p1 - p0, p2 - p0)
            ln = float(np.linalg.norm(n))
            if ln > 1e-9 and abs(n[2]) / ln > 0.95:
                try:
                    tri.append(Polygon([p0[:2], p1[:2], p2[:2]]).buffer(0))
                except Exception:
                    pass
        fp = unary_union(tri).buffer(0.003) if tri else None
        polys = [fp] if fp is not None and not fp.is_empty else [lines.buffer(0.02)]
    out = []
    for p in polys:
        for g in (p.geoms if isinstance(p, MultiPolygon) else [p]):
            if g.is_empty or g.geom_type != "Polygon":
                continue
            out.append(([tuple(c) for c in g.exterior.coords], [[tuple(c) for c in h.coords] for h in g.interiors]))
    return out


def build_plan(path):
    """Read the IFC and return {"storeys": [{"name", "elev", "layers": {kind: [polygon]}, "spaces": [{"name","poly"}]}]}.
    A polygon is (outer ring, [hole rings]) in metres. Raises on a file that cannot be read."""
    import numpy as np
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU
    ifc = ifcopenshell.open(path)
    st = ifcopenshell.geom.settings()
    st.set(st.USE_WORLD_COORDS, True)
    sc = UU.calculate_unit_scale(ifc)
    kinds = {"IfcWall": "wall", "IfcWallStandardCase": "wall", "IfcColumn": "wall", "IfcCurtainWall": "wall",
             "IfcWindow": "window", "IfcDoor": "door", "IfcStair": "stair", "IfcStairFlight": "stair", "IfcSpace": "space"}
    storeys = {}
    for s in ifc.by_type("IfcBuildingStorey"):
        storeys[s.id()] = {"name": s.Name or "Level", "elev": float(s.Elevation or 0) * sc, "items": []}
    for cls, kind in kinds.items():
        for el in ifc.by_type(cls):
            try:
                cont = UE.get_container(el)
                if cont is None and cls == "IfcSpace":
                    cont = next((r.RelatingObject for r in (el.Decomposes or []) if r.RelatingObject.is_a("IfcBuildingStorey")), None)
                if cont is None or cont.id() not in storeys:
                    continue
                sh = ifcopenshell.geom.create_shape(st, el)
                v = np.array(sh.geometry.verts, dtype=float).reshape(-1, 3)      # already metres, in world coordinates
                f = np.array(sh.geometry.faces, dtype=int).reshape(-1, 3)
                if len(f):
                    nm = (getattr(el, "LongName", None) or getattr(el, "Name", None) or "") if kind == "space" else ""
                    storeys[cont.id()]["items"].append((kind, v, f, nm))
            except Exception:
                continue
    ordered = sorted(storeys.values(), key=lambda s: s["elev"])
    out = []
    for s in ordered:
        z = s["elev"] + CUT_HEIGHT
        layers, spaces = {}, []
        for kind, v, f, nm in s["items"]:
            if v[:, 2].min() > z or v[:, 2].max() < z:
                continue
            ps = _polys(v, f, z)
            if kind == "space":
                for p in ps:
                    spaces.append({"name": nm, "poly": p})
            else:
                layers.setdefault(kind, []).extend(ps)
        if layers or spaces:
            out.append({"name": s["name"], "elev": s["elev"], "layers": layers, "spaces": spaces})
    return {"storeys": out}


def plan_for(path):
    """The plan for a file (cached by name and modification time)."""
    key = (path, os.path.getmtime(path))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    plan = build_plan(path)
    with _LOCK:
        _CACHE[key] = plan
    return plan


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


class PlanView(QGraphicsView):
    room_clicked = Signal(str, str)         # storey name, room name

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.scale(1, -1)                    # model y is up
        self.rooms = {}                      # item -> (storey, name)
        self._storey = ""
        self._zoomed = False                 # the user zoomed or panned: stop re-fitting on resize
        self.rot = 0.0                       # degrees the plan is turned (to square it up on the screen)

    def wheelEvent(self, e):
        k = 1.18 if e.angleDelta().y() > 0 else 1 / 1.18
        self._zoomed = True
        self.scale(k, k)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._zoomed and self.scene().items():
            self.fit()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            it = self.itemAt(e.position().toPoint())
            while it is not None and it not in self.rooms:
                it = it.parentItem()
            if it in self.rooms:
                self.room_clicked.emit(*self.rooms[it])

    def fit(self):
        self._zoomed = False
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-1, -1, 1, 1), Qt.AspectRatioMode.KeepAspectRatio)

    def _pt(self, x, y):
        c, s_ = math.cos(math.radians(self.rot)), math.sin(math.radians(self.rot))
        return QPointF(x * c - y * s_, x * s_ + y * c)

    def _path(self, poly):
        from PySide6.QtGui import QPolygonF
        outer, holes = poly
        p = QPainterPath()
        p.addPolygon(QPolygonF([self._pt(x, y) for x, y in outer]))
        for h in holes:
            hp = QPainterPath()
            hp.addPolygon(QPolygonF([self._pt(x, y) for x, y in h]))
            p = p.subtracted(hp)
        return p

    def show_storey(self, storey, pal, status):
        """Draw one storey. pal = colours, status = {normalised room name: 'ok' | 'check' | 'fail'}."""
        sc = self.scene()
        sc.clear()
        self.rooms = {}
        self._storey = storey["name"]
        self.setBackgroundBrush(QBrush(QColor(pal["bg"])))
        pen0 = QPen(Qt.PenStyle.NoPen)
        for sp in storey["spaces"]:
            st = status.get(_norm(sp["name"]))
            fill = QColor(pal.get(st or "space"))
            it = QGraphicsPathItem(self._path(sp["poly"]))
            it.setBrush(QBrush(fill))
            ln = QPen(QColor(pal["spaceline"]), 0.0)
            it.setPen(ln)
            it.setZValue(1)
            it.setToolTip(sp["name"] or "Room")
            sc.addItem(it)
            self.rooms[it] = (storey["name"], sp["name"])
        order = (("stair", pal["stair"], 2), ("wall", pal["wall"], 3), ("door", pal["door"], 4), ("window", pal["window"], 4))
        for kind, col, z in order:
            for poly in storey["layers"].get(kind, []):
                it = QGraphicsPathItem(self._path(poly))
                it.setBrush(QBrush(QColor(col)))
                pen = QPen(QColor(pal["edge"]), 0.0)
                it.setPen(pen)
                it.setZValue(z)
                sc.addItem(it)
        for sp in storey["spaces"]:
            if not sp["name"]:
                continue
            pts = [self._pt(*q) for q in sp["poly"][0]]
            xs = [q.x() for q in pts]
            ys = [q.y() for q in pts]
            t = QGraphicsSimpleTextItem(sp["name"])
            t.setBrush(QBrush(QColor(pal["label"])))
            f = t.font()
            f.setPixelSize(1)
            t.setFont(f)
            w = max(max(xs) - min(xs), 0.5)
            br = t.boundingRect()
            k = min(0.30, 0.8 * w / max(br.width(), 1))        # text height in metres, kept inside the room
            t.setScale(k)
            t.setTransform(t.transform().scale(1, -1))          # undo the y flip of the view
            t.setPos((min(xs) + max(xs)) / 2 - br.width() * k / 2, (min(ys) + max(ys)) / 2 + br.height() * k / 2)
            t.setZValue(6)
            sc.addItem(t)
        self.fit()


def _palette(is_light):
    if is_light:
        return dict(bg="#f3f4f6", space="#e4e8ec", spaceline="#aeb6bf", wall="#2a2f36", window="#4aa3e8", door="#b98a52",
                    stair="#98a0a9", edge="#1c1f24", label="#1c1f24", ok="#bfe6cc", check="#fde7b0", fail="#f6b9bf")
    return dict(bg="#101114", space="#1f2328", spaceline="#3a4048", wall="#d9dde2", window="#4aa3e8", door="#c8975a",
                stair="#6b727b", edge="#101114", label="#eceef0", ok="#2a7a4e", check="#8a6c1c", fail="#9a2e3c")


class PlanPage(QWidget):
    """The Plan tab: storey picker, the plan, a legend and a short note about the selected room."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._plan, self._path, self._err, self._busy = None, "", "", False
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        top = QHBoxLayout()
        top.addWidget(QLabel("Level:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(180)
        self.combo.currentIndexChanged.connect(self._draw)
        top.addWidget(self.combo)
        from PySide6.QtWidgets import QCheckBox
        self.straight = QCheckBox("Square up")
        self.straight.setChecked(True)
        self.straight.setToolTip("Turn the plan so its main walls run level and upright. Untick for the model's own angle.")
        self.straight.toggled.connect(self._draw)
        top.addWidget(self.straight)
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(lambda: self.view.fit())
        top.addWidget(self.fit_btn)
        self.legend = QLabel("")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        top.addSpacing(14)
        top.addWidget(self.legend)
        top.addStretch(1)
        self.go_btn = QPushButton("Open rooms list")
        self.go_btn.clicked.connect(lambda: (self.win.main_tabs.setCurrentIndex(1), self.win.tabs.setCurrentIndex(2)))
        top.addWidget(self.go_btn)
        v.addLayout(top)
        self.view = PlanView()
        self.view.room_clicked.connect(self._room)
        v.addWidget(self.view, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.msg = QLabel("")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check)
        self._result = {}
        self._light = None

    # --- loading
    def activate(self):
        """Call when the tab is shown: loads the plan (in the background) if the model changed."""
        path = getattr(self.win, "ifc_path", "") or ""
        if not path or not os.path.exists(path):
            self._plan, self._path = None, ""
            self._show_msg("Import an IFC model (Import IFC in the ribbon) to see its floor plan here.")
            return
        if path == self._path and self._plan is not None:
            self._draw()
            return
        if self._busy:
            return
        self._path, self._busy = path, True
        self._show_msg("Reading the floor plan from the model...")
        self._result = {}

        def work(p=path):
            try:
                self._result = {"plan": plan_for(p)}
            except Exception as ex:
                self._result = {"err": str(ex)}
        threading.Thread(target=work, daemon=True).start()
        self._poll.start(250)

    def _check(self):
        if not self._result:
            return
        self._poll.stop()
        self._busy = False
        r, self._result = self._result, {}
        if "plan" in r and r["plan"]["storeys"]:
            self._plan = r["plan"]
            cur = self.combo.currentText()
            self.combo.blockSignals(True)
            self.combo.clear()
            for s in self._plan["storeys"]:
                self.combo.addItem(s["name"])
            i = self.combo.findText(cur)
            self.combo.setCurrentIndex(i if i >= 0 else 0)
            self.combo.blockSignals(False)
            self._draw()
        else:
            self._plan = None
            self._show_msg("The model has no walls or rooms that can be cut into a plan." if "plan" in r
                           else "The floor plan could not be read from this model.")

    def _show_msg(self, text):
        self.msg.setText(text)
        self.msg.setVisible(True)
        self.view.setVisible(False)
        self.combo.setEnabled(False)

    # --- drawing
    def _status(self):
        """Normalised room name -> ok / check / fail from the latest results."""
        out = {}
        for r in getattr(self.win, "results", None) or []:
            ok = bool(r.get("light_ok")) and bool(r.get("vent_ok"))
            bad = (not r.get("light_ok")) and (not r.get("vent_ok"))
            out[_norm(r.get("room"))] = "ok" if ok else ("fail" if bad else "check")
        return out

    def _draw(self, *_):
        if not self._plan:
            return
        self.msg.setVisible(False)
        self.view.setVisible(True)
        self.combo.setEnabled(True)
        i = max(0, self.combo.currentIndex())
        is_l = bool(self.win.shell_is_light()) if hasattr(self.win, "shell_is_light") else False
        pal = _palette(is_l)
        self.view.rot = self._square_angle() if self.straight.isChecked() else 0.0
        self.view.show_storey(self._plan["storeys"][i], pal, self._status())
        self.legend.setText("<span style='color:%s'>&#9632;</span> pass &nbsp; <span style='color:%s'>&#9632;</span> check "
                            "&nbsp; <span style='color:%s'>&#9632;</span> fail &nbsp; <span style='color:%s'>&#9632;</span> window "
                            "&nbsp; <span style='color:%s'>&#9632;</span> door"
                            % (pal["ok"], pal["check"], pal["fail"], pal["window"], pal["door"]))
        self._light = is_l

    def _square_angle(self):
        """Degrees to turn the plan so the long side of the walls' bounding rectangle is level."""
        if "_angle" in self._plan:
            return self._plan["_angle"]
        ang = 0.0
        try:
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
            st = max(self._plan["storeys"], key=lambda s: len(s["layers"].get("wall", [])))
            u = unary_union([Polygon(p[0]).buffer(0) for p in st["layers"].get("wall", []) if len(p[0]) > 3])
            rect = u.minimum_rotated_rectangle
            c = list(rect.exterior.coords)
            e1, e2 = (c[1][0] - c[0][0], c[1][1] - c[0][1]), (c[2][0] - c[1][0], c[2][1] - c[1][1])
            e = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
            ang = -math.degrees(math.atan2(e[1], e[0]))
            ang = (ang + 90) % 180 - 90               # nearest to level, never upside down
        except Exception:
            ang = 0.0
        self._plan["_angle"] = ang
        return ang

    def refresh(self):
        """Colours or results changed."""
        if self._plan and self.isVisible():
            self._draw()

    def _room(self, storey, name):
        res = {_norm(r.get("room")): r for r in (getattr(self.win, "results", None) or [])}
        r = res.get(_norm(name))
        if not r:
            self.note.setText("<b>%s</b>: no result yet. Run the check to colour the rooms." % (name or "Room"))
            return
        self.note.setText("<b>%s</b>: light %s (%.1f%% of floor, needs %s), ventilation %s. %s" % (
            r.get("room"), "passes" if r.get("light_ok") else "fails", 100.0 * (r.get("glazed") or 0) / max(r.get("area") or 1, 1e-9),
            r.get("light_req", ""), "passes" if r.get("vent_ok") else "fails", "Open the Rooms list to change its windows."))
