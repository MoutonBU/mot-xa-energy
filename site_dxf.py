"""Read outlines (stands, houses, carports) out of a DXF drawing for the Site services tool. Closed polylines are taken as they are; loose
lines and open polylines are joined end to end into outlines. Units come from the drawing ($INSUNITS) or are guessed (big numbers = mm)."""
import math


def _clean(pts, tol=1e-4):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tol:
            out.append((float(p[0]), float(p[1])))
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tol:
        out.pop()
    k = []
    n = len(out)
    for i in range(n):                                          # drop vertices that sit on a straight run
        a, b, c = out[i - 1], out[i], out[(i + 1) % n]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-9 * max(1.0, abs(b[0]) + abs(b[1])):
            k.append(b)
    return k if len(k) >= 3 else out


def _area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def _join(segs, tol):
    """loose segments -> closed loops"""
    segs = [(tuple(a), tuple(b)) for a, b in segs if math.hypot(a[0] - b[0], a[1] - b[1]) > tol]
    loops = []
    used = [False] * len(segs)

    def near(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1]) <= tol
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        chain = [segs[i][0], segs[i][1]]
        grew = True
        while grew:
            grew = False
            for j in range(len(segs)):
                if used[j]:
                    continue
                a, b = segs[j]
                if near(chain[-1], a):
                    chain.append(b)
                elif near(chain[-1], b):
                    chain.append(a)
                else:
                    continue
                used[j] = True
                grew = True
                if near(chain[0], chain[-1]):
                    grew = False
                break
        if len(chain) >= 4 and near(chain[0], chain[-1]):
            loops.append(chain[:-1])
    return loops


def dwg_to_dxf(path):
    """a DWG is turned into a DXF with a converter on the computer (ODA File Converter or LibreDWG), when there is one; otherwise the way out is said plainly"""
    if not str(path).lower().endswith(".dwg"):
        return path
    import glob
    import os
    import shutil
    import subprocess
    import tempfile
    out = tempfile.mkdtemp(prefix="mot_dwg_")
    exe = shutil.which("dwg2dxf")
    if exe:
        dst = os.path.join(out, "converted.dxf")
        subprocess.run([exe, "-y", "-o", dst, path], capture_output=True, timeout=120)
        if os.path.exists(dst):
            return dst
    cands = shutil.which("ODAFileConverter") or next(iter(sorted(glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe") + glob.glob(r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe"))), None)
    if cands:
        src = tempfile.mkdtemp(prefix="mot_dwg_in_")
        shutil.copy(path, src)
        subprocess.run([cands, src, out, "ACAD2013", "DXF", "0", "1"], capture_output=True, timeout=180)
        got = glob.glob(os.path.join(out, "*.dxf"))
        if got:
            return got[0]
    raise ValueError("This is a DWG, and this computer has no DWG converter. Either save it as DXF from your CAD program (Save As, DXF, 2013 or older), or install the free ODA File Converter and import the DWG again.")


def read_shapes(path, min_area=0.5):
    """-> list of {"poly": [(x, y) in metres], "area": m2, "layer": name}, biggest first"""
    path = dwg_to_dxf(path)
    import ezdxf
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        from ezdxf import recover
        doc, _aud = recover.readfile(path)
    u = int(doc.header.get("$INSUNITS", 0) or 0)
    scale = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}.get(u)
    raw, loose = [], []

    def walk(ents, depth=0):
        for e in ents:
            t = e.dxftype()
            lay = e.dxf.layer
            if t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                (raw if e.closed else loose).append((lay, pts))
            elif t == "POLYLINE" and not e.is_3d_polyline and not e.is_polygon_mesh:
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                (raw if e.is_closed else loose).append((lay, pts))
            elif t == "LINE":
                loose.append((lay, [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]))
            elif t == "INSERT" and depth < 3:
                try:
                    walk(e.virtual_entities(), depth + 1)
                except Exception:
                    pass
    walk(doc.modelspace())
    xs = [p[0] for _l, pts in raw + loose for p in pts]
    ys = [p[1] for _l, pts in raw + loose for p in pts]
    if not xs:
        return []
    if scale is None:
        scale = 0.001 if max(max(xs) - min(xs), max(ys) - min(ys)) > 2000 else 1.0
    out = []
    seen = set()

    def add(lay, pts):
        poly = _clean([(x * scale, y * scale) for x, y in pts])
        if len(poly) < 3:
            return
        a = abs(_area(poly))
        if a < min_area:
            return
        key = (round(a, 2), round(poly[0][0], 1), round(poly[0][1], 1))
        if key in seen:
            return
        seen.add(key)
        out.append({"poly": poly, "area": a, "layer": lay})
    for lay, pts in raw:
        add(lay, pts)
    bylayer = {}
    for lay, pts in loose:
        for i in range(len(pts) - 1):
            bylayer.setdefault(lay, []).append((pts[i], pts[i + 1]))
    for lay, segs in bylayer.items():
        for loop in _join(segs, 0.01 / scale if scale < 1 else 0.01):
            add(lay, loop)
    out.sort(key=lambda s: -s["area"])
    return out


# ------------------------------------------------------------------ the whole drawing, for the import window
def read_drawing(path):
    """-> {"lines": [(x1, y1, x2, y2, colour)], "texts": [(text, x, y)], "raw_shapes": [(layer, pts)], "unit": guessed unit in metres per drawing unit,
    "span": (w, h) in drawing units}. Coordinates are left in drawing units; use scale_drawing() to turn them into metres."""
    path = dwg_to_dxf(path)
    import ezdxf
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        from ezdxf import recover
        doc, _aud = recover.readfile(path)
    u = int(doc.header.get("$INSUNITS", 0) or 0)
    unit = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}.get(u)
    lines, texts, closed = [], [], []

    def col(e):
        try:
            return int(e.dxf.color)
        except Exception:
            return 7

    def walk(ents, depth=0):
        nonlocal lines
        for e in ents:
            t = e.dxftype()
            try:
                if t == "LINE":
                    lines.append((e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y, col(e)))
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    if e.closed:
                        pts.append(pts[0])
                        closed.append((e.dxf.layer, pts[:-1]))
                    lines += [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], col(e)) for i in range(len(pts) - 1)]
                elif t == "POLYLINE" and not e.is_polygon_mesh:
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                    if e.is_closed:
                        closed.append((e.dxf.layer, list(pts)))
                        pts.append(pts[0])
                    lines += [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], col(e)) for i in range(len(pts) - 1)]
                elif t in ("ARC", "CIRCLE"):
                    c, r = e.dxf.center, e.dxf.radius
                    a0, a1 = (math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)) if t == "ARC" else (0.0, 2 * math.pi)
                    if a1 <= a0:
                        a1 += 2 * math.pi
                    n = max(6, int((a1 - a0) / (math.pi / 12)))
                    pts = [(c.x + r * math.cos(a0 + (a1 - a0) * k / n), c.y + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
                    lines += [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], col(e)) for i in range(n)]
                elif t in ("SPLINE", "ELLIPSE"):
                    pts = [(q[0], q[1]) for q in e.flattening(max(0.0001, (max(span_hint[0], 1.0)) / 5000.0))]
                    lines += [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], col(e)) for i in range(len(pts) - 1)]
                elif t in ("SOLID", "TRACE", "3DFACE"):
                    vs = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3 if t != "3DFACE" else e.dxf.vtx2, e.dxf.vtx2 if t != "3DFACE" else e.dxf.vtx3]
                    pts = [(q.x, q.y) for q in vs]
                    lines += [(pts[i][0], pts[i][1], pts[(i + 1) % 4][0], pts[(i + 1) % 4][1], col(e)) for i in range(4)]
                elif t == "HATCH":
                    for path in e.paths:
                        if hasattr(path, "vertices"):
                            pts = [(q[0], q[1]) for q in path.vertices]
                            if len(pts) > 2:
                                closed.append((e.dxf.layer, pts))
                                lines += [(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1], col(e)) for i in range(len(pts))]
                elif t in ("TEXT", "MTEXT"):
                    tx = e.dxf.text if t == "TEXT" else e.text
                    texts.append((str(tx).strip(), e.dxf.insert.x, e.dxf.insert.y))
                elif t == "INSERT" and depth < 3:
                    walk(e.virtual_entities(), depth + 1)
            except Exception:
                continue
    span_hint = (100.0, 100.0)
    walk(doc.modelspace())
    if not lines:                                               # drawings kept on a sheet (paper space) layout
        for lay in doc.layouts:
            if lay.name != "Model":
                walk(lay)
    if not lines:
        kinds = sorted({e.dxftype() for e in doc.modelspace()})
        raise ValueError("No lines were found in this drawing. It holds: %s. Explode blocks / xrefs, or save the stand as plain lines or polylines." % (", ".join(kinds) or "nothing"))
    xs = [v for l in lines for v in (l[0], l[2])]
    ys = [v for l in lines for v in (l[1], l[3])]
    span = (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0, 0)
    if unit is None or (unit >= 1.0 and max(span) > 2000):     # a drawing saying metres but 2 km across is millimetres
        unit = 0.001 if max(span) > 2000 else 1.0
    return {"lines": lines, "texts": texts, "raw_shapes": closed, "unit": unit, "span": span}


def outlines(drawing, factor, min_area=0.5):
    """closed outlines (in metres) from a drawing: closed polylines, plus loose lines that meet end to end"""
    out, seen = [], set()

    def add(lay, pts):
        poly = _clean([(x * factor, y * factor) for x, y in pts])
        if len(poly) < 3:
            return
        a = abs(_area(poly))
        if a < min_area or (len(poly) >= 20 and a < 30):          # text frames are rounded boxes with many corners
            return
        key = (round(a, 2), round(poly[0][0], 1), round(poly[0][1], 1))
        if key not in seen:
            seen.add(key)
            out.append({"poly": poly, "area": a, "layer": lay})
    for lay, pts in drawing["raw_shapes"]:
        add(lay, pts)
    segs = [((l[0], l[1]), (l[2], l[3])) for l in drawing["lines"]]
    for tol_m in (0.01, 0.1, 0.4):                               # lines that nearly meet (a loose drawing) join up with a wider reach
        for loop in _join(segs, tol_m / factor if factor else tol_m):
            add("lines", loop)
    for poly in _rectangles(segs, factor or 1.0):                 # square boundaries whose lines cross or overshoot at the corners
        add("lines", poly)
    out.sort(key=lambda s: -s["area"])
    return out


def _rectangles(segs, factor, min_len=3.0, tol=0.06, cover=0.97):
    """level and upright lines (in the drawing's units) that make a closed box even where they cross or run past the corners"""
    H, V = [], []
    for (x1, y1), (x2, y2) in segs:
        L = math.hypot(x2 - x1, y2 - y1) * factor
        if L < min_len:
            continue
        if abs(y2 - y1) * factor < tol:
            H.append(((y1 + y2) / 2 * factor, min(x1, x2) * factor, max(x1, x2) * factor))
        elif abs(x2 - x1) * factor < tol:
            V.append(((x1 + x2) / 2 * factor, min(y1, y2) * factor, max(y1, y2) * factor))

    def merged(items):
        """lines on the same level, grouped, with their spans joined"""
        items.sort()
        out = []
        for c, lo, hi in items:
            if out and abs(out[-1][0] - c) <= tol and lo <= out[-1][2] + tol:
                out[-1][2] = max(out[-1][2], hi)
                out[-1][1] = min(out[-1][1], lo)
            else:
                out.append([c, lo, hi])
        return out
    H, V = merged(H), merged(V)
    if len(H) > 60 or len(V) > 60:
        H = sorted(H, key=lambda t: -(t[2] - t[1]))[:60]
        V = sorted(V, key=lambda t: -(t[2] - t[1]))[:60]
    res = []

    def span(c, lo, hi, line):
        return min(hi, line[2]) - max(lo, line[1])
    for i, h1 in enumerate(H):
        for h2 in H[i + 1:]:
            if abs(h1[0] - h2[0]) < min_len:
                continue
            ylo, yhi = sorted((h1[0], h2[0]))
            for j, v1 in enumerate(V):
                for v2 in V[j + 1:]:
                    if abs(v1[0] - v2[0]) < min_len:
                        continue
                    xlo, xhi = sorted((v1[0], v2[0]))
                    W, Hh = xhi - xlo, yhi - ylo
                    ok = (span(0, xlo, xhi, h1) >= cover * W and span(0, xlo, xhi, h2) >= cover * W
                          and span(0, ylo, yhi, v1) >= cover * Hh and span(0, ylo, yhi, v2) >= cover * Hh)
                    if ok:
                        res.append([(xlo, ylo), (xhi, ylo), (xhi, yhi), (xlo, yhi)])
    res.sort(key=lambda r: -abs((r[2][0] - r[0][0]) * (r[2][1] - r[0][1])))
    return [[(x / factor, y / factor) for x, y in r] for r in res[:12]]


MARK_NAMES = ("DB", "SD", "FD", "G", "KD")
WATER_COLOURS = {4, 5} | set(range(130, 180))                   # cyan and blue in the colour index
PATIO_WORDS = ("patio", "stoep", "veranda", "braai", "porch", "pergola")


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy or 1e-12
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _poly_dist(p, poly):
    return min(_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _inside(p, poly):
    x, y = p
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def building_extras(texts_m, lines_m, shapes, poly):
    """what the footprint drawing says besides the outline, all in metres: the marks (DB, SD, FD, G, KD) lying on or round it, where the blue water
    pipe meets the house (that is the kitchen connection, against the KD or, failing that, the gully G), and any covered patio / stoep / braai
    outline that touches it."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    m = 1.5
    marks = []
    for t, x, y in texts_m:
        tt = t.strip().upper()
        if tt in MARK_NAMES and min(xs) - m <= x <= max(xs) + m and min(ys) - m <= y <= max(ys) + m:
            marks.append([tt, round(x, 3), round(y, 3)])
    # the blue pipe ends on the house wall
    stubs = []
    for l in lines_m:
        if len(l) > 4 and l[4] in WATER_COLOURS:
            a, b = (l[0], l[1]), (l[2], l[3])
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.3:
                continue
            for e, o in ((a, b), (b, a)):
                if _poly_dist(e, poly) < 0.35 and not _inside(o, poly) and _poly_dist(o, poly) > 0.25:
                    stubs.append(e)
    ref = [(mk[1], mk[2]) for mk in marks if mk[0] == "KD"] or [(mk[1], mk[2]) for mk in marks if mk[0] == "G"]
    water = None
    if stubs:
        water = min(stubs, key=lambda q: min(math.hypot(q[0] - r[0], q[1] - r[1]) for r in ref)) if ref else None
        if water is not None and ref and min(math.hypot(water[0] - r[0], water[1] - r[1]) for r in ref) > 4.0:
            water = None                                         # a stub nowhere near the kitchen: not the water connection
    if water is not None:
        marks = [mk for mk in marks if mk[0] != "KD"]
        marks.append(["KD", round(water[0], 3), round(water[1], 3)])
    patios = []
    lab = [(t.strip().lower(), x, y) for t, x, y in texts_m]
    for s in shapes:
        q = s["poly"]
        if s["area"] > abs(_area(poly)) * 0.8 or s["area"] < 2.0:
            continue
        if not any(any(w in t for w in PATIO_WORDS) and _inside((x, y), q) for t, x, y in lab):
            continue
        if any(_poly_dist(p, poly) < 0.1 for p in q) or any(_poly_dist(p, q) < 0.1 for p in poly):
            patios.append([tuple(p) for p in q])
    return {"marks": marks, "patios": patios, "water": water}


def union_polys(poly, others):
    """the house outline and the patios joined into one outline (shapely); the house alone if that fails"""
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        u = unary_union([Polygon(poly).buffer(0.01, join_style=2)] + [Polygon(o).buffer(0.01, join_style=2) for o in others]).buffer(-0.01, join_style=2)
        if u.geom_type != "Polygon":
            u = max(u.geoms, key=lambda g: g.area)
        pts = [(round(x, 4), round(y, 4)) for x, y in list(u.exterior.coords)[:-1]]
        return _clean(pts, 0.005)
    except Exception:
        return list(poly)


# ---------------------------------------------------------------- contours
# Ground contours for the Site services tool: read them out of a DXF (survey or site plan), and give the ground level at any point of the stand.
# 
# Contours are polylines (or lines / splines) lying at a level: the level is the polyline's elevation, the Z of its vertices, or - for flat 2D contours -
# the number written on the line (a TEXT / MTEXT close to it). Loose spot heights (POINT with a Z, or a number written with a point) are kept too.
# The ground between the contours is taken as straight between the two nearest contour levels (the usual way a contoured plan is read).
_C_UNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}


def _c_num(t):
    t = str(t).replace(",", ".").strip()
    for junk in ("m", "M", "+", "RL", "rl", "FFL", "ffl", "NGL", "ngl"):
        t = t.replace(junk, "")
    t = t.strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return v


def _c_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 <= 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def read_contours(path):
    """-> {"lines": [[level, [[x, y], ...]], ...], "spots": [[x, y, level], ...], "unit": metres per drawing unit}; coordinates and levels in metres"""
    path = dwg_to_dxf(path)
    import ezdxf
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        from ezdxf import recover
        doc, _aud = recover.readfile(path)
    u = int(doc.header.get("$INSUNITS", 0) or 0)
    unit = _C_UNITS.get(u)
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
                    v = _c_num(tx)
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
                d = min(_c_seg_dist((tx, ty), a, b) for a, b in zip(pts[:-1], pts[1:]))
                if d < bd:
                    best, bd = v, d
            if best is not None and bd <= tol:
                lines.append([best * zf, [[p[0] * unit, p[1] * unit] for p in pts]])
    spots = [[s[0] * unit, s[1] * unit, s[2] * zf] for s in raw_spots if abs(s[2]) > 1e-9]
    spots += [[tx * unit, ty * unit, (tz if abs(tz) > 1e-9 else v) * zf] for tx, ty, v, tz in texts if abs(tz) > 1e-9]
    if not lines and not spots:
        raise ValueError("The lines in this drawing carry no levels: give the contours an elevation, or write the level beside each line.")
    return {"lines": lines, "spots": spots, "unit": unit}


def clip_contours(data, poly, margin=40.0):
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
        return min(_c_seg_dist(p, a, b) for a, b in self.levels[key])

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
