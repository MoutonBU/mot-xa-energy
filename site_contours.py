"""Ground contours for the Site services tool: read them out of a DXF (survey or site plan), and give the ground level at any point of the stand.

Contours are polylines (or lines / splines) lying at a level: the level is the polyline's elevation, the Z of its vertices, or - for flat 2D contours -
the number written on the line (a TEXT / MTEXT close to it). Loose spot heights (POINT with a Z, or a number written with a point) are kept too.
The ground between the contours is taken as straight between the two nearest contour levels (the usual way a contoured plan is read)."""
import math

_UNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}


def _num(t):
    t = str(t).replace(",", ".").strip()
    for junk in ("m", "M", "+", "RL", "rl", "FFL", "ffl", "NGL", "ngl"):
        t = t.replace(junk, "")
    t = t.strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return v


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def read(path):
    """-> {"lines": [[level, [[x, y], ...]], ...], "spots": [[x, y, level], ...], "unit": metres per drawing unit}; coordinates and levels in metres"""
    import site_dxf
    path = site_dxf.dwg_to_dxf(path)
    import ezdxf
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        from ezdxf import recover
        doc, _aud = recover.readfile(path)
    u = int(doc.header.get("$INSUNITS", 0) or 0)
    unit = _UNITS.get(u)
    raw_lines, raw_spots, texts = [], [], []

    def walk(ents, depth=0):
        for e in ents:
            t = e.dxftype()
            try:
                if t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    z = float(e.dxf.elevation) if e.dxf.hasattr("elevation") else 0.0
                    if e.closed and pts:
                        pts.append(pts[0])
                    raw_lines.append((z, pts))
                elif t == "POLYLINE" and not e.is_polygon_mesh:
                    vs = [v.dxf.location for v in e.vertices]
                    pts = [(v.x, v.y) for v in vs]
                    zs = [v.z for v in vs]
                    z = sum(zs) / len(zs) if zs else 0.0
                    if e.is_closed and pts:
                        pts.append(pts[0])
                    raw_lines.append((z, pts))
                elif t == "LINE":
                    raw_lines.append((float(e.dxf.start.z), [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]))
                elif t == "SPLINE":
                    q = list(e.flattening(0.05))
                    if q:
                        raw_lines.append((sum(v[2] for v in q) / len(q), [(v[0], v[1]) for v in q]))
                elif t == "POINT":
                    loc = e.dxf.location
                    raw_spots.append((loc.x, loc.y, float(loc.z)))
                elif t in ("TEXT", "MTEXT"):
                    tx = e.dxf.text if t == "TEXT" else e.text
                    v = _num(tx)
                    if v is not None:
                        texts.append((e.dxf.insert.x, e.dxf.insert.y, v, float(e.dxf.insert.z)))
                elif t == "INSERT" and depth < 3:
                    walk(e.virtual_entities(), depth + 1)
            except Exception:
                continue
    walk(doc.modelspace())
    if not raw_lines and not raw_spots:
        raise ValueError("No contour lines or spot heights were found in this drawing.")
    xs = [p[0] for _z, pts in raw_lines for p in pts] + [s[0] for s in raw_spots]
    ys = [p[1] for _z, pts in raw_lines for p in pts] + [s[1] for s in raw_spots]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) if xs else 0.0
    if unit is None or (unit >= 1.0 and span > 2000):
        unit = 0.001 if span > 2000 else 1.0
    zmax = max([abs(z) for z, _p in raw_lines] + [abs(s[2]) for s in raw_spots] + [abs(t[2]) for t in texts] + [0.0])
    zf = unit if (unit == 0.001 and zmax > 400.0) else (0.001 if zmax > 5000.0 else 1.0)    # levels follow the drawing's units when it is in millimetres
    lines = []
    flat = []
    for z, pts in raw_lines:
        if len(pts) < 2:
            continue
        if abs(z) > 1e-9:
            lines.append([z * zf, [[p[0] * unit, p[1] * unit] for p in pts]])
        else:
            flat.append(pts)
    if flat and texts:                                          # flat 2D contours: the level is the number written on or beside the line
        tol = 3.0 / unit
        for pts in flat:
            best, bd = None, 1e18
            for tx, ty, v, _tz in texts:
                d = min(_seg_dist((tx, ty), a, b) for a, b in zip(pts[:-1], pts[1:]))
                if d < bd:
                    best, bd = v, d
            if best is not None and bd <= tol:
                lines.append([best * zf, [[p[0] * unit, p[1] * unit] for p in pts]])
    spots = [[s[0] * unit, s[1] * unit, s[2] * zf] for s in raw_spots if abs(s[2]) > 1e-9]
    spots += [[tx * unit, ty * unit, (tz if abs(tz) > 1e-9 else v) * zf] for tx, ty, v, tz in texts if abs(tz) > 1e-9]
    if not lines and not spots:
        raise ValueError("The lines in this drawing carry no levels: give the contours an elevation, or write the level beside each line.")
    return {"lines": lines, "spots": spots, "unit": unit}


def clip(data, poly, margin=40.0):
    """only what lies near a stand (world metres), so the project file stays small"""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin
    out = []
    for z, pts in data["lines"]:
        if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in pts):
            out.append([z, [[round(p[0], 3), round(p[1], 3)] for p in pts]])
    sp = [[round(s[0], 3), round(s[1], 3), round(s[2], 3)] for s in data["spots"] if x0 <= s[0] <= x1 and y0 <= s[1] <= y1]
    return {"lines": out, "spots": sp, "unit": data.get("unit", 1.0)}


class Terrain:
    """ground level at a point, from contours (and spot heights) given in metres"""

    def __init__(self, lines, spots=()):
        self.levels = {}
        for z, pts in lines:
            key = round(float(z), 4)
            self.levels.setdefault(key, []).extend(zip(pts[:-1], pts[1:]))
        self.spots = [(float(s[0]), float(s[1]), float(s[2])) for s in spots]
        ks = sorted(self.levels)
        steps = [b - a for a, b in zip(ks[:-1], ks[1:]) if b - a > 1e-6]
        self.step = min(steps) if steps else 0.0
        self.keys = ks

    def ok(self):
        return bool(self.levels) or bool(self.spots)

    def _dist(self, p, key):
        return min(_seg_dist(p, a, b) for a, b in self.levels[key])

    def z_at(self, x, y):
        p = (x, y)
        if self.keys:
            d = {k: self._dist(p, k) for k in self.keys}
            k1 = min(d, key=d.get)
            d1 = d[k1]
            if len(self.keys) == 1:
                return k1
            cand = [k for k in self.keys if abs(abs(k - k1) - self.step) < 1e-6 and k != k1]
            if not cand:
                cand = [k for k in self.keys if k != k1]
            k2 = min(cand, key=lambda k: d[k])
            d2 = d[k2]
            if d1 + d2 < 1e-9:
                return k1
            return k1 + (k2 - k1) * d1 / (d1 + d2)
        w = [(1.0 / max(math.hypot(x - sx, y - sy), 0.05) ** 2, sz) for sx, sy, sz in self.spots]
        sw = sum(a for a, _b in w)
        return sum(a * b for a, b in w) / sw if sw else 0.0

    def range(self):
        zs = list(self.keys) + [s[2] for s in self.spots]
        return (min(zs), max(zs)) if zs else (0.0, 0.0)
