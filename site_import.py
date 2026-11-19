"""Importing a surveyed site (DXF / DWG / PDF) and building footprints (IFC model, PDF, DXF / DWG) for the Building lines tool.

An Underlay is a drawing laid under the plan. Its own points are kept in 'raw' metres; the plan sees them as
world = raw * k + (ox, oy). For a PDF, raw is in metres on the paper and k is the drawing scale (1:500 -> 500), so setting or
calibrating the scale only changes k."""
import math
import os

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainterPath

PT_M = 0.0254 / 72.0            # one PDF point in metres on the paper


def poly_area(p):
    n = len(p)
    return 0.5 * sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n)) if n >= 3 else 0.0


def clean(poly, tol=1e-6):
    out = []
    for q in poly:
        if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > tol:
            out.append((float(q[0]), float(q[1])))
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = poly[i][0], poly[i][1], poly[j][0], poly[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


class Underlay:
    def __init__(self, kind, path, role="site"):
        self.kind, self.file, self.role = kind, path, role
        self.k, self.ox, self.oy = 1.0, 0.0, 0.0
        self.rot = 0.0               # radians, anticlockwise
        self.opacity = 0.75 if role == "site" else 0.6
        self.polys = []              # raw polylines (DXF)
        self.cands = []              # raw closed shapes that could be a stand or a building
        self.image = None            # PDF page as a picture
        self.raw_w = self.raw_h = 0.0
        self.unit = "m"              # DXF units chosen at load
        self.scale_n = 500           # PDF scale chosen at load
        self.page = 0
        self._qpath = None
        self._snap = None

    # ---- geometry
    def to_world(self, p):
        c, sn = math.cos(self.rot), math.sin(self.rot)
        x, y = p[0] * self.k, p[1] * self.k
        return (x * c - y * sn + self.ox, x * sn + y * c + self.oy)

    def to_raw(self, p):
        c, sn = math.cos(self.rot), math.sin(self.rot)
        x, y = p[0] - self.ox, p[1] - self.oy
        return ((x * c + y * sn) / self.k, (-x * sn + y * c) / self.k)

    def qt(self):
        """QTransform from raw drawing coordinates to world metres."""
        from PySide6.QtGui import QTransform
        c, sn = self.k * math.cos(self.rot), self.k * math.sin(self.rot)
        return QTransform(c, sn, -sn, c, self.ox, self.oy)

    def rotate_about(self, a, cx, cy):
        """Turn the whole drawing by a radians about the world point (cx, cy)."""
        c, sn = math.cos(a), math.sin(a)
        x, y = self.ox - cx, self.oy - cy
        self.ox, self.oy = cx + x * c - y * sn, cy + x * sn + y * c
        self.rot += a
        self._snap = None

    def raw_bounds(self):
        if self.image is not None:
            return 0.0, 0.0, self.raw_w, self.raw_h
        xs = [p[0] for pl in self.polys for p in pl]
        ys = [p[1] for pl in self.polys for p in pl]
        if not xs:
            return 0.0, 0.0, 1.0, 1.0
        return min(xs), min(ys), max(xs), max(ys)

    def world_bounds(self):
        x0, y0, x1, y1 = self.raw_bounds()
        ps = [self.to_world(q) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        return min(p[0] for p in ps), min(p[1] for p in ps), max(p[0] for p in ps), max(p[1] for p in ps)

    def centre_world(self):
        a = self.world_bounds()
        return (a[0] + a[2]) / 2, (a[1] + a[3]) / 2

    def move_centre_to(self, cx, cy):
        c = self.centre_world()
        self.ox += cx - c[0]
        self.oy += cy - c[1]

    def set_k(self, newk):
        """Change the scale about the middle of the drawing."""
        c = self.centre_world()
        self.k = newk
        self.move_centre_to(*c)

    def calibrate(self, p1, p2, real):
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if d <= 1e-9 or real <= 0:
            return
        f = real / d
        self.k *= f
        self.ox = p1[0] - (p1[0] - self.ox) * f
        self.oy = p1[1] - (p1[1] - self.oy) * f

    def path(self):
        if self._qpath is None:
            qp = QPainterPath()
            for pl in self.polys:
                if len(pl) < 2:
                    continue
                qp.moveTo(pl[0][0], pl[0][1])
                for q in pl[1:]:
                    qp.lineTo(q[0], q[1])
            self._qpath = qp
        return self._qpath

    def snap_points(self):
        """World points to snap to: corners of the shapes (PDF) or every vertex (DXF)."""
        try:
            import numpy as np
        except Exception:
            return None
        if self._snap is None:
            src = [p for pl in self.polys for p in pl] if self.polys else [p for c in self.cands for p in c]
            self._snap = np.array(src, float) if src else np.zeros((0, 2))
        if not len(self._snap):
            return self._snap
        c, sn = math.cos(self.rot), math.sin(self.rot)
        a = self._snap * self.k
        return np.column_stack((a[:, 0] * c - a[:, 1] * sn + self.ox, a[:, 0] * sn + a[:, 1] * c + self.oy))

    def candidates(self, min_area=4.0):
        out = []
        for c in self.cands:
            w = [self.to_world(p) for p in c]
            a = abs(poly_area(w))
            if a >= min_area:
                out.append((a, w))
        out.sort(key=lambda t: -t[0])
        return out

    # ---- saving
    def state(self):
        return {"kind": self.kind, "path": self.file, "k": self.k, "ox": self.ox, "oy": self.oy, "rot": self.rot, "opacity": self.opacity,
                "unit": self.unit, "scale_n": self.scale_n, "page": self.page}


# ---------------------------------------------------------------- DXF / DWG
def dwg_to_dxf(path):
    import detail_to_dwg as dd
    out = dd.oda_convert(path, "DXF")
    if not out:
        raise RuntimeError("A DWG file can only be read with the free ODA File Converter, and it was not found. "
                           "Install it from opendesign.com, or save the survey as DXF from your CAD program and load that.")
    return str(out)


def dxf_guess_unit(path):
    """'m', 'mm' or 'cm' from the file's own unit setting or the size of the drawing."""
    try:
        doc = _read_dxf(path)
        u = doc.header.get("$INSUNITS", 0)
        if u == 6:
            return "m"
        if u == 4:
            return "mm"
        if u == 5:
            return "cm"
        from ezdxf import bbox
        ex = bbox.extents(doc.modelspace())
        size = max(ex.size.x, ex.size.y)
        return "mm" if size > 3000 else "m"
    except Exception:
        return "m"


def _read_dxf(path):
    import ezdxf
    if path.lower().endswith(".dwg"):
        path = dwg_to_dxf(path)
    try:
        return ezdxf.readfile(path)
    except Exception:
        doc, _ = ezdxf.recover.readfile(path)
        return doc


def load_dxf(path, unit="m", underlay=None):
    from ezdxf import path as dpath
    doc = _read_dxf(path)
    f = {"m": 1.0, "mm": 0.001, "cm": 0.01}.get(unit, 1.0)
    tol = 0.03 / f
    polys, cands = [], []

    def add(pts, closed):
        pts = [(p[0] * f, p[1] * f) for p in pts]
        if len(pts) < 2:
            return
        polys.append(pts)
        c = clean(pts)
        if len(c) >= 3 and (closed or math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4):
            cands.append(c)

    def walk(ents, depth=0):
        for e in ents:
            t = e.dxftype()
            try:
                if t == "INSERT":
                    if depth < 4:
                        walk(e.virtual_entities(), depth + 1)
                    continue
                if t not in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                    continue
                if t == "POLYLINE" and not e.is_2d_polyline and not e.is_3d_polyline:
                    continue
                p = dpath.make_path(e)
                closed = bool(getattr(e, "closed", False) or getattr(e, "is_closed", False) or t == "CIRCLE")
                subs = p.sub_paths() if p.has_sub_paths else [p]
                for sp in subs:
                    pts = [(v.x, v.y) for v in sp.flattening(tol)]
                    add(pts, closed)
            except Exception:
                continue
    walk(doc.modelspace())
    if not polys:
        raise RuntimeError("No lines were found in this drawing.")
    mnx = min(p[0] for pl in polys for p in pl)
    mny = min(p[1] for pl in polys for p in pl)
    polys = [[(x - mnx, y - mny) for x, y in pl] for pl in polys]
    cands = [[(x - mnx, y - mny) for x, y in c] for c in cands]
    u = underlay or Underlay("dxf", path)
    u.kind, u.file, u.polys, u.cands, u.image, u.unit = "dxf", path, polys, cands, None, unit
    u._qpath = None
    u._snap = None
    return u


# ---------------------------------------------------------------- PDF
def pdf_pages(path):
    import fitz
    with fitz.open(path) as d:
        return len(d)


def load_pdf(path, scale_n=500, page=0, underlay=None, dpi=150):
    import fitz
    doc = fitz.open(path)
    pg = doc[min(max(0, page), len(doc) - 1)]
    w_pt, h_pt = pg.rect.width, pg.rect.height
    while w_pt * dpi / 72 > 6500 or h_pt * dpi / 72 > 6500:
        dpi = int(dpi * 0.7)
    pix = pg.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
    cands = []
    try:
        if not pg.rotation:
            for d in pg.get_drawings():
                pts, closed = [], bool(d.get("closePath"))
                for it in d.get("items", []):
                    op = it[0]
                    if op == "re":
                        r = it[1]
                        cands.append(clean([(r.x0 * PT_M, (h_pt - r.y0) * PT_M), (r.x1 * PT_M, (h_pt - r.y0) * PT_M),
                                            (r.x1 * PT_M, (h_pt - r.y1) * PT_M), (r.x0 * PT_M, (h_pt - r.y1) * PT_M)]))
                        continue
                    if op == "qu":
                        q = it[1]
                        cands.append(clean([(p.x * PT_M, (h_pt - p.y) * PT_M) for p in (q.ul, q.ur, q.lr, q.ll)]))
                        continue
                    a, b = (it[1], it[-1]) if op in ("l", "c") else (None, None)
                    if a is None:
                        continue
                    if not pts or math.hypot(pts[-1][0] - a.x, pts[-1][1] - a.y) > 0.05:
                        if len(pts) >= 4 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.05:
                            cands.append(clean([(x * PT_M, (h_pt - y) * PT_M) for x, y in pts]))
                        pts = [(a.x, a.y)]
                    pts.append((b.x, b.y))
                if len(pts) >= 4 and (closed or math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.05):
                    cands.append(clean([(x * PT_M, (h_pt - y) * PT_M) for x, y in pts]))
    except Exception:
        pass
    cands = [c for c in cands if len(c) >= 3 and len(c) <= 400]
    u = underlay or Underlay("pdf", path)
    u.kind, u.file, u.page, u.polys, u.image = "pdf", path, page, [], img
    u.raw_w, u.raw_h = w_pt * PT_M, h_pt * PT_M
    u.cands = cands
    u.scale_n = scale_n
    u.k = float(scale_n)
    u._qpath = None
    u._snap = None
    return u


def load_underlay(path, role, unit=None, scale_n=None, page=0, underlay=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".dxf", ".dwg"):
        return load_dxf(path, unit or dxf_guess_unit(path), underlay)
    if ext == ".pdf":
        return load_pdf(path, scale_n or 500, page, underlay)
    raise RuntimeError("Use a DWG, DXF or PDF file.")


# ---------------------------------------------------------------- IFC footprint
def ifc_footprint(path, include_slabs=True, include_roof=True, progress=None):
    """The outline seen from above: walls, columns, stairs, and (optionally) slabs such as patios and balconies and roofs.
    Returns a list of polygons in metres (model coordinates), largest first. progress(i, n) returns False to cancel."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.unit as UU
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ifc = ifcopenshell.open(path)
    sc = float(UU.calculate_unit_scale(ifc))
    st = ifcopenshell.geom.settings()
    st.set(st.USE_WORLD_COORDS, True)
    classes = ["IfcWall", "IfcWallStandardCase", "IfcColumn", "IfcStair", "IfcCurtainWall"]
    if include_slabs:
        classes += ["IfcSlab"]
    if include_roof:
        classes += ["IfcRoof"]
    els = []
    for c in classes:
        try:
            els += list(ifc.by_type(c))
        except Exception:
            pass
    polys = []
    for i, el in enumerate(els):
        if progress and i % 8 == 0 and progress(i, len(els)) is False:
            raise RuntimeError("Cancelled")
        try:
            g = ifcopenshell.geom.create_shape(st, el).geometry
            v = np.array(g.verts, float).reshape(-1, 3)  # already metres
            f = np.array(g.faces, int).reshape(-1, 3)
        except Exception:
            continue
        for a, b, c in f:
            pa, pb, pc = v[a][:2], v[b][:2], v[c][:2]
            ar = abs((pb[0] - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (pb[1] - pa[1]))
            if ar > 1e-6:
                polys.append(Polygon([tuple(pa), tuple(pb), tuple(pc)]))
    if not polys:
        raise RuntimeError("No walls, slabs or roofs with a shape were found in this IFC model.")
    u = unary_union(polys).buffer(0.03).buffer(-0.03).simplify(0.03)
    parts = list(u.geoms) if hasattr(u, "geoms") else [u]
    out = []
    for p in parts:
        if p.is_empty or p.area < 1.0:
            continue
        out.append((p.area, clean(list(p.exterior.coords))))
    out.sort(key=lambda t: -t[0])
    return [c for _, c in out]
