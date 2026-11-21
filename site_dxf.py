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


def read_shapes(path, min_area=0.5):
    """-> list of {"poly": [(x, y) in metres], "area": m2, "layer": name}, biggest first"""
    if str(path).lower().endswith(".dwg"):
        raise ValueError("This is a DWG. Save it as DXF from your CAD program first (Save As, DXF), then import that.")
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
