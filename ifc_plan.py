"""Floor plan from the IFC model itself.

Every storey is cut with a horizontal plane 1.1 m above its floor, so the plan shows exactly what the model contains:
walls, windows, doors, stairs and the rooms (IfcSpace). Rooms are coloured by the light / ventilation result.
Reading the model takes a few seconds, so it runs in a background thread and is kept for the next visit."""
import math
import os
import re
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


def _rect_from_element(v, mat, sc, width):
    """A window or door as a clean rectangle: length along the element's own X axis, thickness of the wall it sits in.
    Open sashes, handles and swing leaves in the mesh are ignored. Returns four corners or None."""
    import numpy as np
    try:
        O = np.array(mat)[:3, 3] * sc
        X = np.array(mat)[:2, 0].astype(float)
        n = float(np.linalg.norm(X))
        if n < 1e-6:
            return None
        X = X / n
        Y = np.array([-X[1], X[0]])
        rel = v[:, :2] - O[:2]
        xs, ys = rel @ X, rel @ Y
        if width and width > 0.1:
            m = (xs >= -0.06) & (xs <= width + 0.06)
        else:
            m = np.ones(len(xs), bool)
        if m.sum() < 3:
            return None
        x0, x1 = float(np.percentile(xs[m], 1)), float(np.percentile(xs[m], 99))
        if width and width > 0.1:
            x0, x1 = max(x0, 0.0), min(x1, float(width))
            if x1 - x0 < 0.5 * width:
                x0, x1 = 0.0, float(width)
        y0, y1 = float(np.percentile(ys[m], 3)), float(np.percentile(ys[m], 97))
        t = min(max(y1 - y0, 0.30), 0.36)
        yc = (y0 + y1) / 2.0
        a, b = yc - t / 2.0, yc + t / 2.0
        pts = [(x0, a), (x1, a), (x1, b), (x0, b), (x0, a)]
        return [(float(O[0] + X[0] * px + Y[0] * py), float(O[1] + X[1] * px + Y[1] * py)) for px, py in pts]
    except Exception:
        return None


def _footprint(v, f):
    """The outline of a room (IfcSpace) seen from above: its flat faces joined up. Works for rooms drawn full height and for
    passages, verandas and patios that the model keeps as a thin sheet near the ceiling."""
    import numpy as np
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import unary_union
    tri = []
    for a, b, c in f:
        p0, p1, p2 = v[a], v[b], v[c]
        n = np.cross(p1 - p0, p2 - p0)
        ln = float(np.linalg.norm(n))
        if ln > 1e-9 and abs(n[2]) / ln > 0.9:
            try:
                g = Polygon([p0[:2], p1[:2], p2[:2]])
                if g.area > 1e-9:
                    tri.append(g.buffer(0))
            except Exception:
                pass
    if not tri:
        return []
    u = unary_union([t.buffer(0.003) for t in tri]).buffer(-0.003)
    out = []
    for g in (u.geoms if isinstance(u, MultiPolygon) else [u]):
        if g.is_empty or g.geom_type != "Polygon" or g.area < 0.3:
            continue
        out.append(([tuple(c) for c in g.exterior.coords], [[tuple(c) for c in h.coords] for h in g.interiors]))
    return out


def _opening(polys):
    """A window or door as a bar at least as thick as a wall, so it fills its gap in the wall on the plan."""
    from shapely.geometry import Polygon
    out = []
    for outer, _holes in polys:
        try:
            g = Polygon(outer).buffer(0)
            if g.is_empty:
                continue
            rect = g.minimum_rotated_rectangle
            c = list(rect.exterior.coords)
            a, b = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1]), math.hypot(c[2][0] - c[1][0], c[2][1] - c[1][1])
            d = max(0.0, (0.21 - min(a, b)) / 2.0)
            r = rect.buffer(d, join_style=2) if d > 0 else rect
            out.append(([tuple(q) for q in r.exterior.coords], []))
        except Exception:
            out.append((outer, []))
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
                    extra = None
                    if kind == "door" and re.match(r"^\s*G\d*\b", str(getattr(el, "Name", "") or ""), re.I):
                        continue                          # a door labelled G is a gate: not part of the floor plan
                    if kind in ("window", "door"):
                        try:
                            import ifcopenshell.util.placement as UP
                            extra = (UP.get_local_placement(el.ObjectPlacement), float(getattr(el, "OverallWidth", None) or 0) * sc,
                                     str(getattr(el, "Name", "") or "")[:8])
                        except Exception:
                            extra = None
                    storeys[cont.id()]["items"].append((kind, v, f, nm, extra))
            except Exception:
                continue
    sc_ = sc
    ordered = sorted(storeys.values(), key=lambda s: s["elev"])
    out = []
    for s in ordered:
        z = s["elev"] + CUT_HEIGHT
        layers, spaces, tags = {}, [], []
        for kind, v, f, nm, extra in s["items"]:
            lo, hi = float(v[:, 2].min()), float(v[:, 2].max())
            if kind == "space":                      # every room, whatever height its shape sits at
                for p_ in _footprint(v, f):
                    spaces.append({"name": nm, "poly": p_})
                continue
            zc = z
            if kind in ("window", "door") and (lo > z or hi < z):
                # high-level windows (bathrooms) do not reach 1.1 m: cut them through the middle of their own height
                if lo < s["elev"] - 0.3 or lo > s["elev"] + 3.2:
                    continue
                zc = (lo + hi) / 2.0
            elif lo > z or hi < z:
                continue
            if kind in ("window", "door"):
                rc = _rect_from_element(v, extra[0], sc_, extra[1]) if extra else None
                ps = [(rc, [])] if rc else _opening(_polys(v, f, zc))
                if extra and extra[2]:
                    tags.extend((kind, extra[2], q[0]) for q in ps)
            else:
                ps = _polys(v, f, zc)
            if kind == "space":
                for p in ps:
                    spaces.append({"name": nm, "poly": p})
            else:
                layers.setdefault(kind, []).extend(ps)
        def _area(sp_):
            o_ = sp_["poly"][0]
            return abs(sum(o_[i][0] * o_[i + 1][1] - o_[i + 1][0] * o_[i][1] for i in range(len(o_) - 1))) / 2.0
        spaces.sort(key=_area, reverse=True)          # small rooms (passages) are drawn on top of large ones
        if layers or spaces:
            out.append({"name": s["name"], "elev": s["elev"], "layers": layers, "spaces": spaces, "tags": tags})
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
    room_clicked = Signal(object)           # the room (its dict)

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
        self.show_tags = True
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
                self.room_clicked.emit(self.rooms[it])

    def highlight(self, name):
        """Outline one room (by name) and bring it to the front; clear with None."""
        for it, sp_ in self.rooms.items():
            on = name is not None and sp_ is name
            pen = QPen(QColor(self._hl if on else self._line), 3.0 if on else 0.0)
            pen.setCosmetic(True)
            it.setPen(pen)
            it.setZValue(1.5 if on else 1)

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
        self._hl, self._line = pal["hl"], pal["spaceline"]
        self.setBackgroundBrush(QBrush(QColor(pal["bg"])))
        pen0 = QPen(Qt.PenStyle.NoPen)
        for sp in storey["spaces"]:
            st = status.get(id(sp))
            it = QGraphicsPathItem(self._path(sp["poly"]))
            if st:
                it.setBrush(QBrush(QColor(pal[st])))
                ln = QPen(QColor(pal["spaceline"]), 0.0)
                it.setZValue(1)
            else:                                   # a zone with no result: faint, under the rooms, never hides one
                c = QColor(pal["nores"])
                c.setAlpha(110)
                it.setBrush(QBrush(c))
                ln = QPen(QColor(pal["spaceline"]), 0.0, Qt.PenStyle.DashLine)
                it.setZValue(0.5)
            ln.setCosmetic(True)
            it.setPen(ln)
            it.setToolTip(sp["name"] or "Room")
            sc.addItem(it)
            self.rooms[it] = sp
        order = (("stair", pal["stair"], 2), ("wall", pal["wall"], 3), ("door", pal["door"], 4), ("window", pal["window"], 4))
        for kind, col, z in order:
            for poly in storey["layers"].get(kind, []):
                it = QGraphicsPathItem(self._path(poly))
                it.setBrush(QBrush(QColor(col)))
                pen = QPen(QColor(pal["edge"]), 1.6 if kind in ("window", "door") else 0.0)
                pen.setCosmetic(True)
                it.setPen(pen)
                it.setZValue(z)
                sc.addItem(it)
                if kind == "window" and len(poly[0]) >= 5:       # the centre line of the glass
                    o = poly[0]
                    a = self._pt((o[0][0] + o[3][0]) / 2, (o[0][1] + o[3][1]) / 2)
                    b = self._pt((o[1][0] + o[2][0]) / 2, (o[1][1] + o[2][1]) / 2)
                    gp = QPen(QColor(pal["glassline"]), 0.0)
                    gp.setCosmetic(True)
                    ln = sc.addLine(a.x(), a.y(), b.x(), b.y(), gp)
                    ln.setZValue(5)
                if kind == "door" and len(poly[0]) >= 5:         # the door leaf, a thin line along one edge
                    o = poly[0]
                    a, b = self._pt(*o[0]), self._pt(*o[1])
                    lp = QPen(QColor(pal["edge"]), 0.0)
                    lp.setCosmetic(True)
                    ln = sc.addLine(a.x(), a.y(), b.x(), b.y(), lp)
                    ln.setZValue(5)
        if self.show_tags:
            from PySide6.QtWidgets import QGraphicsRectItem
            for kind, text, ring in storey.get("tags", []):
                if len(ring) < 4 or not text:
                    continue
                pts = [self._pt(*q) for q in ring[:4]]
                cx = sum(q.x() for q in pts) / 4
                cy = sum(q.y() for q in pts) / 4
                t = QGraphicsSimpleTextItem(text)
                f = t.font()
                f.setPixelSize(1)
                f.setBold(True)
                t.setFont(f)
                br = t.boundingRect()
                k = 0.30 / max(br.height(), 1)
                t.setScale(k)
                t.setTransform(t.transform().scale(1, -1))
                t.setBrush(QBrush(QColor("#ffffff")))
                w_, h_ = br.width() * k, br.height() * k
                chip = QGraphicsRectItem(cx - w_ / 2 - 0.04, cy - h_ / 2 - 0.02, w_ + 0.08, h_ + 0.04)
                chip.setBrush(QBrush(QColor(pal["window"] if kind == "window" else pal["doorchip"])))
                chip.setPen(QPen(Qt.PenStyle.NoPen))
                chip.setZValue(7)
                t.setPos(cx - w_ / 2, cy + h_ / 2)
                t.setZValue(8)
                sc.addItem(chip)
                sc.addItem(t)
        placed = []
        todo = sorted((q for q in storey["spaces"] if q["name"]), key=lambda q: (id(q) not in status, -_poly_area(q)))
        for sp in todo:
            pts = [self._pt(*q) for q in sp["poly"][0]]
            xs = [q.x() for q in pts]
            ys = [q.y() for q in pts]
            ar = _poly_area(sp)
            # area-weighted centre of the outline (the middle of an L-shaped room is inside the room)
            a2 = cxs = cys = 0.0
            for q0, q1 in zip(pts, pts[1:]):
                cr = q0.x() * q1.y() - q1.x() * q0.y()
                a2 += cr
                cxs += (q0.x() + q1.x()) * cr
                cys += (q0.y() + q1.y()) * cr
            if abs(a2) > 1e-9:
                cx, cy = cxs / (3 * a2), cys / (3 * a2)
            else:
                cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            w = max(max(xs) - min(xs), 0.5)
            h = max(max(ys) - min(ys), 0.5)
            lines = [sp["name"].strip()] + (["%.1f m\u00b2" % ar] if ar > 1 else [])
            ks = []
            for ln_ in lines:
                t0 = QGraphicsSimpleTextItem(ln_)
                f0 = t0.font()
                f0.setPixelSize(1)
                t0.setFont(f0)
                ks.append(0.85 * w / max(t0.boundingRect().width(), 1))
            k0 = min(0.30, min(ks), 0.8 * h / (len(lines) * 1.35))
            if k0 < 0.11:                              # too small to read: leave it to the list and the tooltip
                continue
            lh = 1.35 * k0
            widest = max((0.85 * w / ks[n]) * k0 for n in range(len(lines)))
            box = QRectF(cx - widest / 2 - 0.05, cy - len(lines) * lh / 2 - 0.03, widest + 0.1, len(lines) * lh + 0.06)
            if any(box.intersects(b) for b in placed):  # never write one label on top of another
                continue
            placed.append(box)
            for n_, ln_ in enumerate(lines):
                t = QGraphicsSimpleTextItem(ln_)
                t.setBrush(QBrush(QColor(pal["label"])))
                f = t.font()
                f.setPixelSize(1)
                f.setBold(n_ == 0)
                t.setFont(f)
                br = t.boundingRect()
                kk = k0 if n_ == 0 else k0 * 0.8
                t.setScale(kk)
                t.setTransform(t.transform().scale(1, -1))
                t.setPos(cx - br.width() * kk / 2, cy + ((len(lines) - 1) / 2.0 - n_) * lh + br.height() * kk / 2)
                t.setZValue(6)
                sc.addItem(t)
        self.fit()


def _palette(is_light):
    if is_light:
        return dict(bg="#f3f4f6", space="#e4e8ec", spaceline="#aeb6bf", wall="#2a2f36", window="#1e88e5", door="#d99a4e", doorchip="#9a5a14",
                    stair="#98a0a9", edge="#1c1f24", label="#1c1f24", nores="#9aa3ad", hl="#c4162a", glassline="#ffffff", ok="#bfe6cc", check="#fde7b0", fail="#f6b9bf")
    return dict(bg="#101114", space="#1f2328", spaceline="#3a4048", wall="#d9dde2", window="#2f9bff", door="#e0a060", doorchip="#b8741f",
                stair="#6b727b", edge="#101114", label="#eceef0", nores="#6b727b", hl="#ffd23f", glassline="#dff0ff", ok="#2a7a4e", check="#8a6c1c", fail="#9a2e3c")


_UNIT_RE = re.compile(r"^\W*[A-Za-z]{0,2}\s*(\d{1,2})\s*[-_.:]\s*(?=[A-Za-z])")


def _split_unit(name):
    """'U3-Kitchen' -> ('u3', 'kitchen'): the unit and the bare room name, both normalised."""
    name = (name or "").strip()
    m = _UNIT_RE.match(name)
    if m:
        return "u" + m.group(1), _norm(name[m.end():])
    return "", _norm(name)


def _poly_area(sp):
    o = sp["poly"][0]
    return abs(sum(o[i][0] * o[i + 1][1] - o[i + 1][0] * o[i][1] for i in range(len(o) - 1))) / 2.0


def assign_results(storey, results, combined=None):
    """Match every room of a level with a row of the results: {id(room): result row}.
    The program drops the unit prefix from room names (U3-Kitchen becomes Kitchen in unit U3), so rooms are matched
    on level, unit and bare name, then by closest area when a name repeats (several passages)."""
    rows = []
    combined = combined or {}
    for r in results or []:
        parts = combined.get(r.get("room"))
        if parts:                       # an open-plan room made on the Rooms tab: each part on the plan gets its result
            for pt in parts:
                u, n = _split_unit(pt.get("name"))
                try:
                    pa = float(str(pt.get("area", 0)).replace(",", ".") or 0)
                except ValueError:
                    pa = 0.0
                rows.append(([r, pt.get("name")], _norm(pt.get("floor") or r.get("floor")),
                             (_norm(pt.get("unit") or r.get("unit")) or u).lower(), n, _norm(pt.get("name")), pa))
            continue
        u, n = _split_unit(r.get("room"))
        ru = _norm(r.get("unit")) or u
        rows.append(([r, None], _norm(r.get("floor")), ru.lower(), n, _norm(r.get("room")), float(r.get("area") or 0)))
    used, out = set(), {}
    for sp_ in storey["spaces"]:
        sp_.pop("_part_of", None)
    fl = _norm(storey["name"])
    for sp in sorted(storey["spaces"], key=_poly_area, reverse=True):
        su, sn = _split_unit(sp["name"])
        full = _norm(sp["name"])
        ar = _poly_area(sp)
        cand = [x for x in rows if id(x[0]) not in used and (x[3] == sn or x[4] == full or (sn and x[3] and (x[3].endswith(sn) or sn.endswith(x[3]))))]
        c2 = [x for x in cand if x[1] == fl]
        cand = c2 or [x for x in cand if x[1] in ("", fl)] or []
        c3 = [x for x in cand if su and x[2] == su]
        cand = c3 or [x for x in cand if not su or not x[2]] or cand
        if cand:
            best = min(cand, key=lambda x: abs(x[5] - ar) if x[5] and ar else 0)
            used.add(id(best[0]))
            out[id(sp)] = best[0][0]
            if best[0][1]:
                sp["_part_of"] = best[0][0].get("room")
    return out


def print_palette():
    p = _palette(True)
    p.update(bg="#ffffff", space="#f1f3f5", ok="#b9e3c6", check="#fbe3a1", fail="#f4a9b1")
    return p


def render_levels(plan, status, combined=None, width=1100, max_h=900, only_with_rooms=True):
    """[(level name, QImage)] for the PDF report: the plan on white with rooms coloured by result."""
    from PySide6.QtGui import QImage
    out = []
    ang = 0.0
    try:
        ang = square_angle(plan)
    except Exception:
        pass
    for st in plan["storeys"]:
        if only_with_rooms and not st["spaces"]:
            continue
        v = PlanView()
        v.rot = ang
        v.show_storey(st, print_palette(), {k: room_status(r) for k, r in assign_results(st, status, combined).items()})
        r = v.scene().itemsBoundingRect().adjusted(-0.6, -0.6, 0.6, 0.6)
        if r.isEmpty():
            continue
        w = int(width)
        h = int(w * r.height() / max(r.width(), 1e-6))
        if h > max_h:
            h = int(max_h)
            w = int(h * r.width() / max(r.height(), 1e-6))
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        pt = QPainter(img)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pt.translate(0, h)
        pt.scale(1, -1)                                   # model y is up
        v.scene().render(pt, QRectF(0, 0, w, h), r)
        pt.end()
        out.append((st["name"], img))
    return out


def square_angle(plan):
    """Degrees to turn the plan so the long side of the walls' bounding rectangle is level."""
    if "_angle" in plan:
        return plan["_angle"]
    ang = 0.0
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        st = max(plan["storeys"], key=lambda s: len(s["layers"].get("wall", [])))
        u = unary_union([Polygon(p[0]).buffer(0) for p in st["layers"].get("wall", []) if len(p[0]) > 3])
        c = list(u.minimum_rotated_rectangle.exterior.coords)
        e1, e2 = (c[1][0] - c[0][0], c[1][1] - c[0][1]), (c[2][0] - c[1][0], c[2][1] - c[1][1])
        e = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
        ang = -math.degrees(math.atan2(e[1], e[0]))
        ang = (ang + 90) % 180 - 90
    except Exception:
        ang = 0.0
    plan["_angle"] = ang
    return ang


def room_status(r):
    ok = bool(r.get("light_ok")) and bool(r.get("vent_ok"))
    bad = (not r.get("light_ok")) and (not r.get("vent_ok"))
    return "ok" if ok else ("fail" if bad else "check")


class PlanPage(QWidget):
    """The Plan tab: the plan on the left; on the right a key, the counts for the level and a list of its rooms."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._plan, self._path, self._busy = None, "", False
        self._result, self._rows = {}, []
        from PySide6.QtWidgets import QCheckBox, QListWidget, QScrollArea
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        left = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Level:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(180)
        self.combo.currentIndexChanged.connect(self._draw)
        top.addWidget(self.combo)
        self.straight = QCheckBox("Square up")
        self.straight.setChecked(True)
        self.straight.setToolTip("Turn the plan so its main walls run level and upright. Untick for the model's own angle.")
        self.straight.toggled.connect(self._draw)
        top.addWidget(self.straight)
        self.tags_cb = QCheckBox("Tags")
        self.tags_cb.setChecked(True)
        self.tags_cb.setToolTip("Show the window and door tags (W1, D2...) on the plan.")
        self.tags_cb.toggled.connect(lambda on: (setattr(self.view, "show_tags", bool(on)), self._draw()))
        top.addWidget(self.tags_cb)
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(lambda: self.view.fit())
        top.addWidget(self.fit_btn)
        top.addStretch(1)
        left.addLayout(top)
        self.view = PlanView()
        self.view.room_clicked.connect(lambda sp: self._select(sp))
        left.addWidget(self.view, 1)
        self.msg = QLabel("")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setWordWrap(True)
        left.addWidget(self.msg)
        root.addLayout(left, 1)
        # ---- right-hand panel
        self.side = QFrame()
        self.side.setObjectName("planSide")
        self.side.setFixedWidth(300)
        sv = QVBoxLayout(self.side)
        sv.setContentsMargins(12, 10, 12, 10)
        sv.setSpacing(6)
        self.key = QLabel("")
        self.key.setTextFormat(Qt.TextFormat.RichText)
        self.key.setWordWrap(True)
        sv.addWidget(self.key)
        self.count = QLabel("")
        self.count.setTextFormat(Qt.TextFormat.RichText)
        self.count.setWordWrap(True)
        sv.addWidget(self.count)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._pick_row)
        sv.addWidget(self.list, 1)
        self.note = QLabel("Click a room on the plan or in this list.")
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.setWordWrap(True)
        sv.addWidget(self.note)
        self.cb_pdf = QCheckBox("Include floor plans in the PDF report")
        self.cb_pdf.setChecked(bool(getattr(win, "cb_plan_pdf", None) is None or win.cb_plan_pdf.isChecked()))
        self.cb_pdf.toggled.connect(lambda on: win._set_plan_in_pdf(on) if hasattr(win, "_set_plan_in_pdf") else None)
        sv.addWidget(self.cb_pdf)
        self.go_btn = QPushButton("Open rooms list")
        self.go_btn.clicked.connect(lambda: (self.win.main_tabs.setCurrentIndex(1), self.win.tabs.setCurrentIndex(2)))
        sv.addWidget(self.go_btn)
        root.addWidget(self.side)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check)

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
            if i < 0:                                   # first level that has rooms
                i = next((k for k, s in enumerate(self._plan["storeys"]) if s["spaces"]), 0)
            self.combo.setCurrentIndex(i)
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
        self.side.setVisible(False)

    # --- drawing
    def _assigned(self, st):
        return assign_results(st, getattr(self.win, "results", None) or [], getattr(self.win, "combined", None))

    def _draw(self, *_):
        if not self._plan:
            return
        self.msg.setVisible(False)
        self.view.setVisible(True)
        self.side.setVisible(True)
        self.combo.setEnabled(True)
        st = self._plan["storeys"][max(0, self.combo.currentIndex())]
        is_l = bool(self.win.shell_is_light()) if hasattr(self.win, "shell_is_light") else False
        pal = _palette(is_l)
        self.view.rot = square_angle(self._plan) if self.straight.isChecked() else 0.0
        self._asg = self._assigned(st)
        self.view.show_storey(st, pal, {k: room_status(r) for k, r in self._asg.items()})
        fg, bg = ("#1c1f24", "#ffffff") if is_l else ("#eceef0", "#17171b")
        self.list.setStyleSheet("QListWidget{background:%s;color:%s;border:1px solid %s;border-radius:8px;} "
                                "QListWidget::item{padding:3px 4px;} QListWidget::item:selected{background:%s;color:%s;}"
                                % (bg, fg, "#d4d7dc" if is_l else "#26262c", "#fbe3e6" if is_l else "#3a161d", fg))
        sw = lambda c, ring=False: ("<span style='color:%s;font-size:15px'>&#9632;</span>" % c)
        rows = [(pal["ok"], "Passes", "light and ventilation are both enough"),
                (pal["check"], "Check", "only one of light or ventilation fails"),
                (pal["fail"], "Fails", "both light and ventilation fail"),
                (pal["nores"], "No result", "zone not in the results (dashed)"),
                (pal["window"], "Window", "glazing, cut through its own height"),
                (pal["door"], "Door", "gates (G) are left out"), (pal["wall"], "Wall", ""), (pal["stair"], "Stair", "")]
        self.key.setText("<b>Key</b><br>" + "<br>".join(
            "%s <b>%s</b>%s" % (sw(c), a, (" <span style='opacity:.7'>- %s</span>" % b) if b else "") for c, a, b in rows))
        self._rows = []
        self.list.blockSignals(True)
        self.list.clear()
        res = self._asg
        n = {"ok": 0, "check": 0, "fail": 0, "none": 0}
        from PySide6.QtGui import QIcon, QPixmap
        for sp in sorted(st["spaces"], key=lambda q: q["name"] or ""):
            r = res.get(id(sp))
            k = room_status(r) if r else "none"
            n[k] += 1
            col = pal.get(k if k != "none" else "space")
            pm = QPixmap(14, 14)
            pm.fill(QColor(col))
            txt = sp["name"] or "Room"
            if sp.get("_part_of"):
                txt += "  (in %s)" % sp["_part_of"]
            if r:
                txt += "   light %s  vent %s" % ("\u2713" if r.get("light_ok") else "\u2717", "\u2713" if r.get("vent_ok") else "\u2717")
            from PySide6.QtWidgets import QListWidgetItem
            it = QListWidgetItem(QIcon(pm), txt)
            self.list.addItem(it)
            self._rows.append(sp)
        self.list.blockSignals(False)
        self.count.setText("<b>%s</b>: %d rooms. <b>%d</b> pass, <b>%d</b> check, <b>%d</b> fail%s." % (
            st["name"], len(st["spaces"]), n["ok"], n["check"], n["fail"], (", %d without a result" % n["none"]) if n["none"] else ""))
        self.note.setText("Click a room on the plan or in this list." if res else
                          "Run the check (Run check in the ribbon) to colour the rooms.")

    def refresh(self):
        """Colours or results changed."""
        if self._plan and self.isVisible():
            self._draw()

    def _pick_row(self, i):
        if 0 <= i < len(self._rows):
            self._select(self._rows[i], from_list=True)

    def _select(self, sp, from_list=False):
        self.view.highlight(sp)
        if not from_list and sp in self._rows:
            self.list.blockSignals(True)
            self.list.setCurrentRow(self._rows.index(sp))
            self.list.blockSignals(False)
        name = sp["name"]
        r = self._asg.get(id(sp))
        if not r:
            self.note.setText("<b>%s</b>: no result yet. Run the check to colour the rooms." % (name or "Room"))
            return
        area = float(r.get("area") or 0)
        gl = float(r.get("glazed") or 0)
        self.note.setText(
            "<b>%s</b>, %.1f m2<br>Light: <b>%s</b> (glazing %.2f m2%s)<br>Ventilation: <b>%s</b> (openable %.2f m2%s)"
            % (r.get("room"), area, "pass" if r.get("light_ok") else "FAIL", gl,
               ", needs %.2f" % r["light_req"] if isinstance(r.get("light_req"), (int, float)) else "",
               "pass" if r.get("vent_ok") else "FAIL", float(r.get("openable") or 0),
               ", needs %.2f" % r["vent_req"] if isinstance(r.get("vent_req"), (int, float)) else ""))
