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


def _snap_openings(layers, tags):
    """Centre every window, door and gate in the wall it sits in and give it the wall's thickness.
    Each opening is a rectangle (corners c0..c3); a short probe across it finds the wall there."""
    try:
        from shapely.geometry import LineString, Polygon
        from shapely.ops import unary_union
        walls = [Polygon(p[0]).buffer(0) for p in layers.get("wall", []) if len(p[0]) > 3]
        if not walls:
            return {}
        wu = unary_union(walls)
    except Exception:
        return {}
    new_tags = {}
    for kind in ("window", "door", "gate"):
        out = []
        for poly in layers.get(kind, []):
            c = poly[0]
            if len(c) < 5:
                out.append(poly)
                continue
            try:
                x0, y0 = c[0]
                ux, uy = c[1][0] - x0, c[1][1] - y0
                vx, vy = c[3][0] - x0, c[3][1] - y0
                lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
                if lu < 1e-6 or lv < 1e-6:
                    out.append(poly)
                    continue
                ux, uy, vx, vy = ux / lu, uy / lu, vx / lv, vy / lv
                mx = (c[0][0] + c[2][0]) / 2
                my = (c[0][1] + c[2][1]) / 2
                best = None
                for off in (0.0, -0.3 * lu, 0.3 * lu):          # probe across the middle, then either side
                    px, py = mx + ux * off, my + uy * off
                    cut = wu.intersection(LineString([(px - vx * 0.7, py - vy * 0.7), (px + vx * 0.7, py + vy * 0.7)]))
                    segs = [cut] if cut.geom_type == "LineString" else [g for g in getattr(cut, "geoms", []) if g.geom_type == "LineString"]
                    for g in segs:
                        if g.is_empty:
                            continue
                        ts = sorted(((q[0] - px) * vx + (q[1] - py) * vy) for q in g.coords)
                        a, b = ts[0], ts[-1]
                        if a <= 0.05 and b >= -0.05 and 0.06 < b - a < 0.6:
                            if best is None or (b - a) > (best[1] - best[0]):
                                best = (a, b)
                    if best:
                        break
                if not best:
                    out.append(poly)
                    continue
                t0 = (best[0] + best[1]) / 2 - (best[1] - best[0]) / 2 - 0.03
                t1 = (best[0] + best[1]) / 2 + (best[1] - best[0]) / 2 + 0.03
                # corners: along the opening from its start to its end, across the wall from t0 to t1
                ax, ay = mx - ux * lu / 2, my - uy * lu / 2
                bx, by = mx + ux * lu / 2, my + uy * lu / 2
                pts = [(ax + vx * t0, ay + vy * t0), (bx + vx * t0, by + vy * t0), (bx + vx * t1, by + vy * t1),
                       (ax + vx * t1, ay + vy * t1)]
                pts.append(pts[0])
                out.append((pts, []))
                new_tags[id(c)] = pts
            except Exception:
                out.append(poly)
        layers[kind] = out
    return new_tags


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
                kind = kinds[cls]
                is_gate = kind == "door" and re.match(r"^\s*G\d*\b", str(getattr(el, "Name", "") or ""), re.I)
                if is_gate:
                    kind = "gate"                          # a door labelled G is a gate: shown in a light grey
                extra = None
                if kind in ("window", "door", "gate"):
                    try:
                        import ifcopenshell.util.placement as UP
                        extra = [UP.get_local_placement(el.ObjectPlacement), float(getattr(el, "OverallWidth", None) or 0) * sc,
                                 str(getattr(el, "Name", "") or "")[:8], None]
                    except Exception:
                        extra = None
                try:
                    sh = ifcopenshell.geom.create_shape(st, el)
                    v = np.array(sh.geometry.verts, dtype=float).reshape(-1, 3)      # already metres, in world coordinates
                    f = np.array(sh.geometry.faces, dtype=int).reshape(-1, 3)
                except Exception:
                    # doors drawn only as a 2D symbol have no 3D shape: place a bar from the door's own position and width
                    if not (extra and extra[1] > 0.1):
                        continue
                    mt = np.array(extra[0])
                    o3 = mt[:3, 3] * sc
                    xa = mt[:2, 0].astype(float)
                    xa = xa / max(float(np.linalg.norm(xa)), 1e-9)
                    ya = np.array([-xa[1], xa[0]])
                    w_, h_ = extra[1], float(getattr(el, "OverallHeight", None) or 2100 / max(sc, 1e-9) * 1.0) * sc
                    corners = [(-0.0, -0.19), (w_, -0.19), (w_, 0.03), (-0.0, 0.03), (-0.0, -0.19)]
                    extra[3] = [(float(o3[0] + xa[0] * px + ya[0] * py), float(o3[1] + xa[1] * px + ya[1] * py)) for px, py in corners]
                    v = np.array([[o3[0], o3[1], o3[2]], [o3[0], o3[1], o3[2] + max(h_, 2.0)]])
                    f = np.zeros((1, 3), dtype=int)
                if len(f):
                    nm = (getattr(el, "LongName", None) or getattr(el, "Name", None) or "") if kind == "space" else ""
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
            if kind in ("window", "door", "gate") and (lo > z or hi < z):
                # high-level windows (bathrooms) do not reach 1.1 m: cut them through the middle of their own height
                if lo < s["elev"] - 0.3 or lo > s["elev"] + 3.2:
                    continue
                zc = (lo + hi) / 2.0
            elif lo > z or hi < z:
                continue
            if kind in ("window", "door", "gate"):
                rc = (extra[3] or _rect_from_element(v, extra[0], sc_, extra[1])) if extra else None
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
        _nt = _snap_openings(layers, tags) or {}
        tags[:] = [(k, t, _nt.get(id(r), r)) for (k, t, r) in tags]
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
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        # redraw the whole view every time: partial redraws left tags and labels missing after a click or a pan
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scale(1, -1)                    # model y is up
        self.rooms = {}                      # item -> room dict
        self._storey = ""
        self._zoomed = False                 # the user zoomed or panned: stop re-fitting on resize
        self.show_tags = True
        self.rot = 0.0                       # degrees the plan is turned (to square it up on the screen)
        self._press = None
        self._sel = None                     # the selected room
        self._sel_item = None
        self._hover_item = None
        self._hl, self._line = "#ffd23f", "#3a4048"
        self._base = 1.0                     # scale of the fitted view, for zoom limits
        self._tips = {}

    # ---- zoom and pan
    def zoom(self, k):
        cur = abs(self.transform().m11())
        k = max(0.6 * self._base / cur, min(k, 60 * self._base / cur))      # keep between 0.6x and 60x the fitted size
        self._zoomed = True
        self.scale(k, k)

    def pan(self, dx, dy):
        """Move the view by a fraction of its size (dx = 0.25 is a quarter of the width to the right)."""
        self._zoomed = True
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + int(dx * self.viewport().width()))
        v.setValue(v.value() - int(dy * self.viewport().height()))     # dy up = up on the screen (the view is flipped)

    def wheelEvent(self, e):
        d = e.angleDelta()
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:           # Shift + wheel: left and right
            self.pan(-0.15 if (d.y() or d.x()) > 0 else 0.15, 0)
        elif e.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.pan(0, 0.15 if d.y() > 0 else -0.15)
        elif d.x() and not d.y():                                       # a sideways wheel or trackpad swipe
            self.pan(-0.15 if d.x() > 0 else 0.15, 0)
        else:
            self.zoom(1.2 if d.y() > 0 else 1 / 1.2)

    def keyPressEvent(self, e):
        k = e.key()
        step = 0.2
        if k == Qt.Key.Key_Left:
            self.pan(-step, 0)
        elif k == Qt.Key.Key_Right:
            self.pan(step, 0)
        elif k == Qt.Key.Key_Up:
            self.pan(0, step)
        elif k == Qt.Key.Key_Down:
            self.pan(0, -step)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(1.25)
        elif k == Qt.Key.Key_Minus:
            self.zoom(1 / 1.25)
        elif k in (Qt.Key.Key_F, Qt.Key.Key_0):
            self.fit()
        elif k == Qt.Key.Key_Escape:
            self.highlight(None)
            self.room_clicked.emit(None)
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._zoomed and self.scene().items():
            self.fit()

    def mouseDoubleClickEvent(self, e):
        self.fit()

    # ---- picking: the room under the cursor (the smallest one when zones overlap)
    def room_at(self, view_pos):
        p = self.mapToScene(view_pos)
        best, ba = None, None
        for it, sp in self.rooms.items():
            if it.path().contains(p):
                a = _poly_area(sp)
                if ba is None or a < ba:
                    best, ba = sp, a
        return best

    def mousePressEvent(self, e):
        self._press = e.position().toPoint() if e.button() == Qt.MouseButton.LeftButton else None
        self.setFocus()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._zoomed = True
            self._hover(None)
            return
        sp = self.room_at(e.position().toPoint())
        self._hover(sp)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if sp else Qt.CursorShape.OpenHandCursor)
        self.viewport().setToolTip(self._tips.get(id(sp), "") if sp else "")

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            moved = (e.position().toPoint() - self._press).manhattanLength()
            self._press = None
            if moved <= 4:                                   # a click, not the end of a drag
                sp = self.room_at(e.position().toPoint())
                self.highlight(sp)
                self.room_clicked.emit(sp)

    def leaveEvent(self, e):
        self._hover(None)
        super().leaveEvent(e)

    def _outline(self, sp, width, alpha, z):
        """An outline (and a light wash) drawn over a room, so the room itself is never changed."""
        it = next((i for i, s_ in self.rooms.items() if s_ is sp), None)
        if it is None:
            return None
        o = QGraphicsPathItem(it.path())
        pen = QPen(QColor(self._hl), width)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        o.setPen(pen)
        c = QColor(self._hl)
        c.setAlpha(alpha)
        o.setBrush(QBrush(c))
        o.setZValue(z)
        o.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.scene().addItem(o)
        return o

    def _hover(self, sp):
        if self._hover_item is not None:
            self.scene().removeItem(self._hover_item)
            self._hover_item = None
        if sp is not None and sp is not self._sel:
            self._hover_item = self._outline(sp, 1.5, 28, 8.5)

    def highlight(self, sp):
        """Mark one room: a thick bright outline and a light wash over it. None clears it."""
        if self._sel_item is not None:
            self.scene().removeItem(self._sel_item)
            self._sel_item = None
        self._sel = sp
        if sp is not None:
            self._sel_item = self._outline(sp, 4.0, 55, 9)
        self._hover(None)

    def fit(self):
        self._zoomed = False
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-0.8, -0.8, 0.8, 0.8), Qt.AspectRatioMode.KeepAspectRatio)
            self._base = abs(self.transform().m11())

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
        self._sel_item = self._hover_item = None
        self.rooms = {}
        self._tips = {}
        self._storey = storey["name"]
        self._hl, self._line = pal["hl"], pal["spaceline"]
        self._hl = pal["hl"]
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
            self._tips[id(sp)] = "%s  %.1f m2  -  %s" % (sp["name"] or "Room", _poly_area(sp), {
                "ok": "passes", "check": "check", "fail": "fails"}.get(st, "no result"))
        order = (("stair", pal["stair"], 2), ("wall", pal["wall"], 3), ("door", pal["door"], 4), ("gate", pal["gate"], 4), ("window", pal["window"], 4))
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
                if kind in ("door", "gate") and len(poly[0]) >= 5:         # the door leaf, a thin line along one edge
                    o = poly[0]
                    a, b = self._pt(*o[0]), self._pt(*o[1])
                    lp = QPen(QColor(pal["edge"]), 0.0)
                    lp.setCosmetic(True)
                    ln = sc.addLine(a.x(), a.y(), b.x(), b.y(), lp)
                    ln.setZValue(5)
        chips = []
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
                chip.setBrush(QBrush(QColor(pal["window"] if kind == "window" else pal["gatechip"] if kind == "gate" else pal["doorchip"])))
                chip.setPen(QPen(Qt.PenStyle.NoPen))
                chips.append(QRectF(cx - w_ / 2 - 0.08, cy - h_ / 2 - 0.06, w_ + 0.16, h_ + 0.12))
                chip.setZValue(7)
                t.setPos(cx - w_ / 2, cy + h_ / 2)
                t.setZValue(8)
                sc.addItem(chip)
                sc.addItem(t)
        placed = list(chips)                           # door and window chips keep their place; room names move round them
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
            from PySide6.QtGui import QPolygonF
            outline = QPolygonF(pts)
            bw, bh = widest + 0.1, len(lines) * lh + 0.06
            spot = None
            for dx, dy in ((0, 0), (0, 0.3), (0, -0.3), (0.3, 0), (-0.3, 0), (0, 0.5), (0, -0.5), (0.5, 0), (-0.5, 0),
                           (0.3, 0.3), (-0.3, 0.3), (0.3, -0.3), (-0.3, -0.3)):
                px, py = cx + dx, cy + dy
                if (dx or dy) and not outline.containsPoint(QPointF(px, py), Qt.FillRule.OddEvenFill):
                    continue
                if (dx or dy) and (px - bw / 2 < min(xs) or px + bw / 2 > max(xs) or py - bh / 2 < min(ys) or py + bh / 2 > max(ys)):
                    continue
                b_ = QRectF(px - bw / 2, py - bh / 2, bw, bh)
                if not any(b_.intersects(q) for q in placed):
                    spot = (px, py, b_)
                    break
            if spot is None:                           # nowhere clear: leave it to the list and the tooltip
                continue
            cx, cy, box = spot
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
        r = sc.itemsBoundingRect()
        m = max(r.width(), r.height()) * 0.6                    # room to pan beyond the plan
        sc.setSceneRect(r.adjusted(-m, -m, m, m))
        self.fit()
        if self._sel is not None and any(q is self._sel for q in self.rooms.values()):
            self.highlight(self._sel)
        else:
            self._sel = None


def _palette(is_light):
    if is_light:
        return dict(bg="#f3f4f6", space="#e4e8ec", spaceline="#aeb6bf", wall="#2a2f36", window="#1e88e5", door="#d99a4e", doorchip="#9a5a14", gate="#c9ced5", gatechip="#6d747d",
                    stair="#98a0a9", edge="#1c1f24", label="#1c1f24", nores="#9aa3ad", hl="#c4162a", glassline="#ffffff", ok="#bfe6cc", check="#fde7b0", fail="#f6b9bf")
    return dict(bg="#101114", space="#1f2328", spaceline="#3a4048", wall="#d9dde2", window="#2f9bff", door="#e0a060", doorchip="#b8741f", gate="#c9ced5", gatechip="#7c838c",
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
                # the result row decides the level and unit: two units may have combined rooms of the same name
                rows.append(([r, pt.get("name")], _norm(r.get("floor") or pt.get("floor")),
                             (_norm(r.get("unit") or pt.get("unit")) or u).lower(), n, _norm(pt.get("name")), pa))
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
        cand = c2 or [x for x in cand if x[1] in ("", fl)]
        if not cand:                    # the results name the level differently from the model: go by unit, name and area
            cand = [x for x in rows if id(x[0]) not in used and (x[3] == sn or x[4] == full)]
        c3 = [x for x in cand if su and x[2] == su]
        cand = c3 or [x for x in cand if not su or not x[2]] or cand
        if cand:
            best = min(cand, key=lambda x: abs(x[5] - ar) if x[5] and ar else 0)
            used.add(id(best[0]))
            out[id(sp)] = best[0][0]
            if best[0][1]:
                sp["_part_of"] = best[0][0].get("room")
    # second pass: a combined room whose parts could not be matched above (renamed, or the same name used twice):
    # its name lists the parts ("Kitchen / Lounge"), so give every still-unmatched room of that unit and level its result
    done = {id(v) for v in out.values()}
    left = [sp for sp in storey["spaces"] if id(sp) not in out]
    for r in results or []:
        nm = str(r.get("room") or "")
        if id(r) in done or not left or not re.search(r"[/+&,]| and ", nm, re.I):
            continue
        rf = _norm(r.get("floor"))
        if rf and rf != fl:
            continue
        toks = [_split_unit(t)[1] for t in re.split(r"[/+&,]| and ", nm, flags=re.I) if t.strip()]
        ru = (_norm(r.get("unit")) or _split_unit(nm)[0]).lower()
        hit = [sp for sp in left if _split_unit(sp["name"])[1] in toks and (not ru or not _split_unit(sp["name"])[0]
                                                                          or _split_unit(sp["name"])[0] == ru)]
        if len(hit) >= 2:
            for sp in hit:
                out[id(sp)] = r
                sp["_part_of"] = nm
            left = [sp for sp in left if id(sp) not in out]
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
    """Degrees to turn the plan so its walls run exactly level and upright, whatever angle the model was drawn at.
    The angle comes from every wall edge on every level (longer edges count more), folded into quarter turns, so one
    odd angled wall cannot tip the plan. The long side of the building ends up horizontal."""
    if "_angle" in plan:
        return plan["_angle"]
    ang = 0.0
    try:
        sx = sy = 0.0
        pts = []
        for st in plan["storeys"]:
            for poly in st["layers"].get("wall", []):
                for ring in [poly[0]] + list(poly[1]):
                    n = len(ring)
                    for i in range(n):
                        x1, y1 = ring[i][0], ring[i][1]
                        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
                        dx, dy = x2 - x1, y2 - y1
                        ln = math.hypot(dx, dy)
                        if ln < 0.05:
                            continue
                        t = 4 * math.atan2(dy, dx)
                        sx += ln * math.cos(t)
                        sy += ln * math.sin(t)
                    pts += [(p[0], p[1]) for p in ring]
        if sx or sy:
            dom = math.degrees(math.atan2(sy, sx)) / 4.0          # the walls' main direction, within +-45 degrees
            ang = -dom
            c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            xs = [x * c - y * s_ for x, y in pts]
            ys = [x * s_ + y * c for x, y in pts]
            if pts and (max(ys) - min(ys)) > (max(xs) - min(xs)) * 1.0001:
                ang += 90.0 if ang <= 0 else -90.0                  # long side level
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
        self.straight.setVisible(False)      # the plan is always shown level; there is no reason to turn it off
        self.tags_cb = QCheckBox("Tags")
        self.tags_cb.setChecked(True)
        self.tags_cb.setToolTip("Show the window and door tags (W1, D2...) on the plan.")
        self.tags_cb.toggled.connect(lambda on: (setattr(self.view, "show_tags", bool(on)), self._draw()))
        top.addWidget(self.tags_cb)
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Fit the whole level in the window (double-click the plan or press F)")
        self.fit_btn.clicked.connect(lambda: self.view.fit())
        top.addSpacing(10)
        top.addWidget(self.fit_btn)
        from PySide6.QtWidgets import QToolButton
        for glyph, tip, fn in (("\u2212", "Zoom out (- key, mouse wheel)", lambda: self.view.zoom(1 / 1.3)),
                               ("+", "Zoom in (+ key, mouse wheel)", lambda: self.view.zoom(1.3)),
                               ("\u25C0", "Pan left (arrow key, Shift + wheel)", lambda: self.view.pan(-0.25, 0)),
                               ("\u25B6", "Pan right (arrow key, Shift + wheel)", lambda: self.view.pan(0.25, 0)),
                               ("\u25B2", "Pan up (arrow key)", lambda: self.view.pan(0, 0.25)),
                               ("\u25BC", "Pan down (arrow key)", lambda: self.view.pan(0, -0.25))):
            tb = QPushButton(glyph)
            tb.setToolTip(tip)
            tb.setFixedSize(34, 30)
            tb.setStyleSheet("padding:0; font-size:14px;")
            tb.setAutoRepeat(glyph in ("\u25C0", "\u25B6", "\u25B2", "\u25BC"))
            tb.clicked.connect(lambda _c=False, f=fn: f())
            top.addWidget(tb)
        top.addStretch(1)
        left.addLayout(top)
        self.view = PlanView()
        self.view.room_clicked.connect(lambda sp: self._select(sp))
        left.addWidget(self.view, 1)
        self.hint = QLabel("Click a room to select it  |  drag to move the plan  |  wheel to zoom  |  Shift + wheel or arrow keys to pan  |  double-click to fit")
        self.hint.setObjectName("muted")
        left.addWidget(self.hint)
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
        self.key.setWordWrap(False)
        self.key.setMinimumHeight(205)
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
                self.combo.addItem(s["name"] + ("" if s["spaces"] else "  (no rooms)"))
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
        self.hint.setVisible(False)
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
        self.hint.setVisible(True)
        self.side.setVisible(True)
        self.combo.setEnabled(True)
        st = self._plan["storeys"][max(0, self.combo.currentIndex())]
        is_l = bool(self.win.shell_is_light()) if hasattr(self.win, "shell_is_light") else False
        pal = _palette(is_l)
        self.view.rot = square_angle(self._plan)
        self._asg = self._assigned(st)
        self.view.show_storey(st, pal, {k: room_status(r) for k, r in self._asg.items()})
        fg, bg = ("#1c1f24", "#ffffff") if is_l else ("#eceef0", "#17171b")
        self.list.setStyleSheet("QListWidget{background:%s;color:%s;border:1px solid %s;border-radius:8px;} "
                                "QListWidget::item{padding:3px 4px;} QListWidget::item:selected{background:%s;color:%s;}"
                                % (bg, fg, "#d4d7dc" if is_l else "#26262c", "#fbe3e6" if is_l else "#3a161d", fg))
        sw = lambda c, ring=False: ("<span style='color:%s;font-size:15px'>&#9632;</span>" % c)
        rows = [(pal["ok"], "Passes", "light and ventilation OK"),
                (pal["check"], "Check", "light or ventilation fails"),
                (pal["fail"], "Fails", "both fail"),
                (pal["nores"], "No result", "dashed"),
                (pal["window"], "Window", ""), (pal["door"], "Door", ""), (pal["gate"], "Gate", "door named G"),
                (pal["wall"], "Wall", ""), (pal["stair"], "Stair", "")]
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
        if sp is None:
            self.view.highlight(None)
            self.list.blockSignals(True)
            self.list.setCurrentRow(-1)
            self.list.blockSignals(False)
            self.note.setText("Click a room on the plan or in this list.")
            return
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
