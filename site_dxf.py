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
    for loop in _join(segs, 0.01 / factor if factor else 0.01):
        add("lines", loop)
    out.sort(key=lambda s: -s["area"])
    return out


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
