"""Parking rules and layout for the SDP Creator. Plain geometry, in metres, no drawing code.

A bay is {"x", "y", "a", "auto", "zone"}: x, y is the centre of the bay, a is the direction (degrees, counter-clockwise from the x axis) in which the
bay opens onto its aisle. The bay is `w` wide and `l` long, and the aisle (the room to reverse out) is `aisle` deep in front of it.
Rules (RULES): bay 2.5 x 5.0 m, aisle 7.0 m, 0.5 m clear of every building, a clearance to the boundary, and optionally outside the building lines."""
import math

RULES = {"w": 2.5, "l": 5.0, "aisle": 7.0, "bld": 0.5, "bound": 0.0, "outside_lines": False}
EPS = 1e-9


def rules(d=None):
    r = dict(RULES)
    r.update({k: v for k, v in (d or {}).items() if k in RULES})
    return r


# ---- geometry
def rect(cx, cy, ang, along, across):
    """a rectangle `along` long in direction ang and `across` wide, round the centre"""
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    h, k = along / 2.0, across / 2.0
    return [(cx - ux * h - vx * k, cy - uy * h - vy * k), (cx + ux * h - vx * k, cy + uy * h - vy * k),
            (cx + ux * h + vx * k, cy + uy * h + vy * k), (cx - ux * h + vx * k, cy - uy * h + vy * k)]


def bay_poly(b, r):
    return rect(b["x"], b["y"], b["a"], r["l"], r["w"])


def aisle_poly(b, r):
    a = math.radians(b["a"])
    d = r["l"] / 2.0 + r["aisle"] / 2.0
    return rect(b["x"] + math.cos(a) * d, b["y"] + math.sin(a) * d, b["a"], r["aisle"], r["w"])


def pip(p, poly):
    """point in polygon (the edge counts as in)"""
    x, y = p
    n = len(poly)
    inside = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if seg_pt(p, (x1, y1), (x2, y2)) < 1e-9:
            return True
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def seg_pt(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < EPS else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def seg_cross(a, b, c, d):
    """the two segments cross each other properly (not just touch)"""
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    return ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS))


def seg_dist(a, b, c, d):
    if seg_cross(a, b, c, d):
        return 0.0
    return min(seg_pt(a, c, d), seg_pt(b, c, d), seg_pt(c, a, b), seg_pt(d, a, b))


def poly_dist(P, Q):
    """the shortest distance between two polygons; 0 when they touch or overlap"""
    if any(pip(p, Q) for p in P) or any(pip(q, P) for q in Q):
        return 0.0
    best = 1e18
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        for j in range(len(Q)):
            best = min(best, seg_dist(a, b, Q[j], Q[(j + 1) % len(Q)]))
            if best < EPS:
                return 0.0
    return best


def overlap(P, Q, shrink=0.02):
    """the two shapes share area (touching edges do not count)"""
    def small(R):
        cx = sum(p[0] for p in R) / len(R)
        cy = sum(p[1] for p in R) / len(R)
        return [(cx + (p[0] - cx) * (1 - shrink), cy + (p[1] - cy) * (1 - shrink)) for p in R]
    return poly_dist(small(P), small(Q)) < EPS


def inside(R, poly):
    """the shape R lies wholly inside poly (a polygon, may be concave)"""
    if not all(pip(p, poly) for p in R):
        return False
    for i in range(len(R)):
        a, b = R[i], R[(i + 1) % len(R)]
        for j in range(len(poly)):
            if seg_cross(a, b, poly[j], poly[(j + 1) % len(poly)]):
                return False
    return all(not _strictly_in(q, R) for q in poly)


def _strictly_in(p, R):
    n = len(R)
    s = [(_cross(R[i], R[(i + 1) % n], p)) for i in range(n)]
    return all(v > 1e-9 for v in s) or all(v < -1e-9 for v in s)


def bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _near(box, ob, gap):
    return not (box[2] + gap < ob[0] or box[0] - gap > ob[2] or box[3] + gap < ob[1] or box[1] - gap > ob[3])


class Site:
    """what the bays are tested against: the stand, the buildings, the building lines"""

    def __init__(self, stand, buildings, env=None, others=None, roads=None, road_owner=None):
        self.roads = [[tuple(p) for p in q] for q in (roads or [])]       # road pieces: bays may not stand on them, their aisles may
        self.rboxes = [bbox(q) for q in self.roads]
        self.rowner = list(road_owner) if road_owner else [-1] * len(self.roads)   # which road each piece belongs to (a road's own bays may stand on it)
        self.stand = [tuple(p) for p in stand]
        self.blds = [[tuple(p) for p in b] for b in buildings]
        self.env = [tuple(p) for p in env] if env else None
        self.bboxes = [bbox(b) for b in self.blds]
        self.others = others or []


def problems(b, r, site, others=()):
    """why a bay breaks the rules: a list of short sentences, empty when it is fine"""
    out = []
    P, A = bay_poly(b, r), aisle_poly(b, r)
    box = bbox(P)
    if site.stand and len(site.stand) >= 3:
        if not inside(P, site.stand):
            out.append("outside the stand")
        elif r["bound"] > 0:
            d = min(seg_dist(P[i], P[(i + 1) % 4], site.stand[j], site.stand[(j + 1) % len(site.stand)]) for i in range(4) for j in range(len(site.stand)))
            if d < r["bound"] - 1e-6:
                out.append("%.2f m from the boundary (needs %.2f m)" % (d, r["bound"]))
    if r.get("outside_lines") and site.env and len(site.env) >= 3 and not inside(P, site.env):
        out.append("inside a building line")
    for k, bl in enumerate(site.blds):
        if not _near(box, site.bboxes[k], r["bld"] + 1):
            continue
        d = poly_dist(P, bl)
        if d < r["bld"] - 1e-6:
            out.append("%.2f m from a building (needs %.2f m)" % (d, r["bld"]))
            break
    for k, q in enumerate(site.roads):
        if b.get("rid") is not None and site.rowner[k] == b["rid"]:
            continue                                                  # the bays of a road are set by its own kerb and pushback
        if _near(box, site.rboxes[k], 0) and overlap(P, q, 0.05):
            out.append("on a road")
            break
    abox = bbox(A)
    aisle_bad = False
    if site.stand and len(site.stand) >= 3 and not inside(A, site.stand):
        aisle_bad = True
    for k, bl in enumerate(site.blds):
        if not aisle_bad and _near(abox, site.bboxes[k], 0.1) and poly_dist(A, bl) < EPS:
            aisle_bad = True
    if aisle_bad:
        out.append("no room to reverse (%.1f m aisle blocked)" % r["aisle"])
    for o in others:
        ob = bbox(bay_poly(o, r))
        if _near(box, ob, 0.1) and overlap(P, bay_poly(o, r)):
            out.append("overlaps another bay")
            break
        if _near(abox, ob, 0.1) and overlap(A, bay_poly(o, r)):
            out.append("a bay is in its aisle")
            break
    return out


# ---- the automatic layout
def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def _longest_dir(poly):
    best, ang = -1.0, 0.0
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L > best:
            best, ang = L, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return ang


def _in_aisles(P, keepA):
    """the bay stands in the aisle of a bay that is already there"""
    pb = bbox(P)
    return any(_near(pb, ab, 0.1) and overlap(P, A) for A, ab in keepA)


def _layout(zone, site, r, theta, tx, ty, keep):
    """bays for rows running along theta, the whole pattern shifted by (tx, ty)"""
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    to_w = lambda x, y: (x * c - y * s, x * s + y * c)
    loc = [(p[0] * c + p[1] * s, -p[0] * s + p[1] * c) for p in zone]
    x0, y0, x1, y1 = bbox(loc)
    L, W, A = r["l"], r["w"], r["aisle"]
    pitch = 2 * L + A
    out = []
    zbox = bbox(zone)
    keepA = [(aisle_poly(k, r), bbox(aisle_poly(k, r))) for k in keep]
    ys = y0 - ty
    while ys < y1:
        for lower in (True, False):
            if lower:
                cy_, ang = ys + L / 2.0, theta + 90.0
            else:
                cy_, ang = ys + L + A + L / 2.0, theta - 90.0
            if cy_ - L / 2.0 > y1 or cy_ + L / 2.0 < y0:
                continue
            xs = x0 - tx
            while xs < x1:
                wx, wy = to_w(xs + W / 2.0, cy_)
                bay = {"x": wx, "y": wy, "a": ang % 360.0, "auto": True}
                P = bay_poly(bay, r)
                if _near(bbox(P), zbox, 0) and inside(P, zone) and inside(aisle_poly(bay, r), zone):
                    if not problems(bay, r, site, keep) and not _in_aisles(P, keepA):
                        out.append(bay)
                xs += W
        ys += pitch
    return out


def fill(zone, site, r=None, angle=None, keep=(), name="", connect=None, limit=0, extra_angles=()):
    """Park a zone full. Rows run along the longest side of the zone (or along `angle`); the pattern is shifted a little in steps
    and turned a quarter, and the layout with the most bays wins. Bays you placed by hand (`keep`) stay where they are.
    connect: road pieces; a layout whose aisles meet the road wins over one that does not. limit: keep only that many bays (the ones nearest the road), 0 = all"""
    r = rules(r)
    zone = [tuple(p) for p in zone]
    if len(zone) < 3:
        return []
    base = _longest_dir(zone) if angle is None else angle
    angs = [base, base + 90.0] if angle is None else [base]
    for e in extra_angles:
        if e is not None:
            angs += [e, e + 90.0]
    qb = [bbox(q) for q in connect] if connect else []
    best, best_key = [], (-1, -1)
    big = abs(_area(zone)) > 3000.0
    step = 3.0 if big else 1.0
    for th in angs:
        for ty in [i * step for i in range(int(math.ceil((2 * r["l"] + r["aisle"]) / step)))]:
            for tx in ((0.0,) if big else (0.0, r["w"] / 2.0)):
                got = _layout(zone, site, r, th, tx, ty, list(keep))
                key = (1 if (connect and got and connected(got, r, connect, qb)) else 0, len(got))
                if key > best_key:
                    best, best_key = got, key
    placed = []
    for b in best:
        b["zone"] = name
        if not problems(b, r, site, list(keep) + placed):
            placed.append(b)
    if limit and len(placed) > limit:
        if connect:
            def near(b):
                return min(math.hypot(b["x"] - (q[0][0] + q[2][0]) / 2.0, b["y"] - (q[0][1] + q[2][1]) / 2.0) for q in connect)
            placed.sort(key=near)
        placed = placed[:limit]
    return placed


def single(x, y, a, r=None):
    return {"x": x, "y": y, "a": a % 360.0, "auto": False, "zone": ""}


def required(units, per_unit=1.0, visitor_per=5):
    """bays needed: a bay (or more) for every unit, and a visitor's bay for every `visitor_per` units"""
    return int(math.ceil(units * per_unit - 1e-9)) + (int(math.ceil(units / float(visitor_per) - 1e-9)) if visitor_per else 0)


# ---- placing blocks (the site solver)
def block_slots(env, obstacles, w, d, side_gap, front_gap, theta=None):
    """Where blocks of w x d metres fit inside `env` (the area inside the building lines), in rows along the longest side (or along theta):
    `side_gap` between blocks in a row, `front_gap` between rows (room for a parking module). Returns the rectangles, first row first.
    The start of the grid is shifted a little and the layout with the most blocks is kept."""
    env = [tuple(p) for p in env]
    if len(env) < 3:
        return []
    th = _longest_dir(env) if theta is None else theta
    c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
    to_w = lambda x, y: (x * c - y * s, x * s + y * c)
    loc = [(p[0] * c + p[1] * s, -p[0] * s + p[1] * c) for p in env]
    x0, y0, x1, y1 = bbox(loc)
    obst = [[tuple(p) for p in o] for o in obstacles]
    ob = [bbox(o) for o in obst]
    best = []
    for ox in (0.0, w / 2.0, w + side_gap / 2.0):
        for oy in (0.0, front_gap / 2.0, front_gap):
            got = []
            y = y0 + oy
            while y + d <= y1 + 1e-9:
                x = x0 + ox
                while x + w <= x1 + 1e-9:
                    cx, cy = to_w(x + w / 2.0, y + d / 2.0)
                    R = rect(cx, cy, th, w, d)
                    if inside(R, env):
                        box = bbox(R)
                        if all(not _near(box, ob[k], side_gap) or poly_dist(R, obst[k]) >= side_gap - 1e-6 for k in range(len(obst))) and \
                                all(poly_dist(R, g) >= side_gap - 1e-6 for g in got):
                            got.append(R)
                            x += w + side_gap
                            continue
                    x += 1.0
                y += d + front_gap
            if len(got) > len(best):
                best = got
    return best


# ---- roads: a spline through the points, a ribbon of road, and bays along its edges
def _spline_seg(pts, step=1.5, smooth=True):
    """the road centreline as points, with the control segment and the share along it for each point.
    smooth: True = a curve through all the points, False = straight pieces, or a list with one flag per piece (True curved, False straight)"""
    pts = [tuple(p) for p in pts]
    if len(pts) < 2:
        return pts, [0] * len(pts), [0.0] * len(pts)
    flags = list(smooth) if isinstance(smooth, (list, tuple)) else [bool(smooth)] * (len(pts) - 1)
    flags += [flags[-1] if flags else True] * (len(pts) - 1 - len(flags))
    out, seg, ts = [pts[0]], [0], [0.0]
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        ln = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if flags[i] and len(pts) > 2:
            n = max(2, int(math.ceil(ln / step)))
            for k in range(1, n + 1):
                t = k / float(n)
                t2, t3 = t * t, t * t * t
                out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2 + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3) for c in (0, 1)))
                seg.append(i)
                ts.append(t)
        else:
            n = max(1, int(math.ceil(ln / step)))
            for k in range(1, n + 1):
                t = k / float(n)
                out.append((p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t))
                seg.append(i)
                ts.append(t)
    return out, seg, ts


def spline(pts, step=1.5, smooth=True):
    """points along the road centreline. smooth: a Catmull-Rom curve through the clicked points, straight pieces, or one flag per piece"""
    return _spline_seg(pts, step, smooth)[0]


def _tangents(c):
    out = []
    for i in range(len(c)):
        a, b = c[max(0, i - 1)], c[min(len(c) - 1, i + 1)]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        out.append(((b[0] - a[0]) / L, (b[1] - a[1]) / L))
    return out


def _arc(c):
    out, run = [0.0], 0.0
    for a, b in zip(c, c[1:]):
        run += math.hypot(b[0] - a[0], b[1] - a[1])
        out.append(run)
    return out


def bay_span(pts, left, right, start, w_bay, smooth=True):
    """the stretch of the road (from, to, in metres along it) that has bays on one side or both: the road is wide there. None when no bays.
    left / right: the number of bays on that side (-1 = as many as fit, 0 = none)"""
    if not left and not right:
        return None
    L = road_length(pts, smooth)
    n = -1 if (left < 0 or right < 0) else max(left, right)
    s0 = max(0.0, min(start, L))
    s1 = L if n < 0 else min(L, s0 + n * w_bay)
    return (s0, s1) if s1 > s0 else None


def merge_spans(spans, gap=0.0):
    out = []
    for a, b in sorted(x for x in spans if x and x[1] > x[0]):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def road_quads(pts, width, smooth=True, span=None, wide=None):
    """the road as short four-sided pieces along its centreline (easy to test against bays and blocks). Inside `span` the road is `wide` metres wide"""
    c = spline(pts, 1.5, smooth)
    if len(c) < 2:
        return []
    t, a = _tangents(c), _arc(c)
    spans = [span] if (span and isinstance(span[0], (int, float))) else list(span or [])
    wd = lambda i: (wide if (wide and any(x0 - 0.01 <= a[i] <= x1 + 0.01 for x0, x1 in spans)) else width) / 2.0
    side = lambda i, s: (c[i][0] - t[i][1] * wd(i) * s, c[i][1] + t[i][0] * wd(i) * s)
    return [[side(i, 1), side(i + 1, 1), side(i + 1, -1), side(i, -1)] for i in range(len(c) - 1)]


def road_length(pts, smooth=True):
    c = spline(pts, 1.5, smooth)
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(c, c[1:]))


def _near_poly(pt, poly, tol):
    return pip(pt, poly) or min(seg_pt(pt, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))) <= tol


def road_bays(pts, width, site, r=None, keep=(), name="Road", smooth=True, left=-1, right=-1, start=0.0, wide=None, zone=None, reach=12.0):
    """bays down the sides of the road, nose to the kerb: the road is their aisle, so they connect to it seamlessly.
    left / right: how many bays on that side (-1 as many as fit, 0 none), counted from `start` metres along the road. `wide` is the road width in the stretch with bays"""
    r = rules(r)
    c = spline(pts, 0.25, smooth)
    if len(c) < 2:
        return []
    t, arc = _tangents(c), _arc(c)
    wd = wide or width
    out, off = [], wd / 2.0 + r["l"] / 2.0
    for sd, cap in ((1, left), (-1, right)):
        if cap == 0:
            continue
        nxt, placed = start + r["w"] / 2.0, 0
        for i in range(len(c)):
            if arc[i] < nxt:
                continue
            if cap > 0 and placed >= cap:
                break
            f = 1.0 if i == 0 or arc[i] == arc[i - 1] else (nxt - arc[i - 1]) / (arc[i] - arc[i - 1])   # exactly one bay width on from the last one
            f = max(0.0, min(1.0, f))
            px, py = c[i - 1][0] + (c[i][0] - c[i - 1][0]) * f if i else c[i][0], c[i - 1][1] + (c[i][1] - c[i - 1][1]) * f if i else c[i][1]
            tx_, ty_ = (t[i - 1][0] + (t[i][0] - t[i - 1][0]) * f, t[i - 1][1] + (t[i][1] - t[i - 1][1]) * f) if i else t[i]
            tl = math.hypot(tx_, ty_) or 1.0
            tx_, ty_ = tx_ / tl, ty_ / tl
            sv = nxt
            nxt += r["w"]
            nx, ny = -ty_ * sd, tx_ * sd                              # the normal on this side, pointing away from the road
            bay = {"x": px + nx * off, "y": py + ny * off, "a": math.degrees(math.atan2(-ny, -nx)) % 360.0, "auto": True, "zone": name}
            if zone is not None:                                          # only where this parking area reaches the road: the bay stands flush with the kerb
                if not any(pip((px + nx * tt, py + ny * tt), zone) for tt in [x * 1.0 for x in range(0, int(wd / 2.0 + r["l"] + reach) + 1)]):
                    continue
                bay["s"] = sv
            if not problems(bay, r, site, list(keep) + out):
                out.append(bay)
                placed += 1
    return out


def road_junction(main_pts, main_smooth, p):
    """where point p meets the centreline of another road: (distance, point on the centreline, tangent there, metres along it)"""
    c = spline(main_pts, 0.5, main_smooth)
    if len(c) < 2:
        return None
    t, a = _tangents(c), _arc(c)
    i = min(range(len(c)), key=lambda k: (c[k][0] - p[0]) ** 2 + (c[k][1] - p[1]) ** 2)
    return math.hypot(c[i][0] - p[0], c[i][1] - p[1]), c[i], t[i], a[i]


def junction_fillets(J, tm, hm, d, hb, R, n=7):
    """the rounded corners where a branch road (leaving the junction point J in direction d, half width hb) meets the edge of the main road
    (tangent tm, half width hm): one fan of triangles for each side of the branch"""
    out = []
    nm, nb = (-tm[1], tm[0]), (-d[1], d[0])
    nd = nm[0] * d[0] + nm[1] * d[1]
    if abs(nd) < 0.05:
        return out
    sg = 1.0 if nd > 0 else -1.0
    for e in (1.0, -1.0):
        v = (sg * hm - e * hb * (nm[0] * nb[0] + nm[1] * nb[1])) / nd
        if v < 0:
            continue
        K = (J[0] + e * hb * nb[0] + v * d[0], J[1] + e * hb * nb[1] + v * d[1])
        tb = tm[0] * nb[0] + tm[1] * nb[1]
        if abs(tb) < 1e-6:
            continue
        sgn = 1.0 if e * tb > 0 else -1.0
        me = (tm[0] * sgn, tm[1] * sgn)
        cos = max(-1.0, min(1.0, d[0] * me[0] + d[1] * me[1]))
        th = math.acos(cos)
        if th < 0.2 or th > math.pi - 0.05:
            continue
        Lt = R / math.tan(th / 2.0)
        if Lt > 25:
            continue
        T1 = (K[0] + d[0] * Lt, K[1] + d[1] * Lt)
        T2 = (K[0] + me[0] * Lt, K[1] + me[1] * Lt)
        bx, by = d[0] + me[0], d[1] + me[1]
        bl = math.hypot(bx, by) or 1.0
        dist = R / math.sin(th / 2.0)
        C = (K[0] + bx / bl * dist, K[1] + by / bl * dist)
        a1, a2 = math.atan2(T1[1] - C[1], T1[0] - C[0]), math.atan2(T2[1] - C[1], T2[0] - C[0])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        arc = [(C[0] + R * math.cos(a1 + da * k / float(n)), C[1] + R * math.sin(a1 + da * k / float(n))) for k in range(n + 1)]
        out += [[K, arc[k], arc[k + 1]] for k in range(n)]
    return out


def connected(bays, r, quads, qboxes):
    """some bay's aisle meets the road: the parking is joined to it"""
    for b in bays:
        A = aisle_poly(b, r)
        ab = bbox(A)
        for k, q in enumerate(quads):
            if _near(ab, qboxes[k], 0.05) and poly_dist(A, q) < 0.05:
                return True
    return False


def push_off(pts, obstacles, clear, pinned, smooth=True, iters=30):
    """move the control points of a road away from buildings until the road keeps `clear` metres off them (the pinned points stay, e.g. at the gate).
    Returns the new points"""
    P = [list(p) for p in pts]
    obs = [[tuple(q) for q in o] for o in obstacles]
    if len(P) < 2 or not obs:
        return P
    for _ in range(iters):
        c, sg_, ts_ = _spline_seg(P, 1.5, smooth)
        segs = list(zip(sg_[1:], ts_[1:]))
        acc = [[0.0, 0.0, 0.0] for _ in P]
        worst = 0.0
        for j in range(1, len(c)):
            if j - 1 >= len(segs):
                break
            k, tt = segs[j - 1]
            p = c[j]
            for o in obs:
                if bbox(o)[0] - clear > p[0] or bbox(o)[2] + clear < p[0] or bbox(o)[1] - clear > p[1] or bbox(o)[3] + clear < p[1]:
                    continue
                best, q = 1e18, None
                for m in range(len(o)):
                    a, b = o[m], o[(m + 1) % len(o)]
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    L2 = dx * dx + dy * dy or 1.0
                    u = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
                    qq = (a[0] + u * dx, a[1] + u * dy)
                    d = math.hypot(p[0] - qq[0], p[1] - qq[1])
                    if d < best:
                        best, q = d, qq
                ins = pip(p, o)
                need = (clear + best) if ins else (clear - best)
                if need <= 0.02:
                    continue
                worst = max(worst, need)
                if best < 1e-9:
                    cx, cy = sum(v[0] for v in o) / len(o), sum(v[1] for v in o) / len(o)
                    vx, vy, L = p[0] - cx, p[1] - cy, math.hypot(p[0] - cx, p[1] - cy) or 1.0
                else:
                    sg = -1.0 if ins else 1.0
                    vx, vy, L = sg * (p[0] - q[0]), sg * (p[1] - q[1]), best
                vx, vy = vx / L * need, vy / L * need
                for idx, wgt in ((k, 1.0 - tt), (k + 1, tt)):
                    if wgt > 1e-6:
                        acc[idx][0] += wgt * vx
                        acc[idx][1] += wgt * vy
                        acc[idx][2] += wgt * wgt
        if worst < 0.05:
            break
        for idx in range(len(P)):
            if idx in pinned or acc[idx][2] < 1e-9:
                continue
            P[idx][0] += acc[idx][0] / acc[idx][2] * 0.8
            P[idx][1] += acc[idx][1] / acc[idx][2] * 0.8
    return P


def _along(c, t, arc, s):
    """the point and the (unit) direction at s metres along the sampled centreline"""
    if s <= 0:
        return c[0], t[0]
    if s >= arc[-1]:
        return c[-1], t[-1]
    lo, hi = 0, len(arc) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if arc[mid] <= s:
            lo = mid
        else:
            hi = mid
    f = (s - arc[lo]) / ((arc[hi] - arc[lo]) or 1.0)
    d = (t[lo][0] + (t[hi][0] - t[lo][0]) * f, t[lo][1] + (t[hi][1] - t[lo][1]) * f)
    L = math.hypot(d[0], d[1]) or 1.0
    return (c[lo][0] + (c[hi][0] - c[lo][0]) * f, c[lo][1] + (c[hi][1] - c[lo][1]) * f), (d[0] / L, d[1] / L)


def _road_bay(c, t, arc, k, sd, w, nose, l):
    (px, py), (tx, ty) = _along(c, t, arc, k * w + w / 2.0)
    nx, ny = -ty * sd, tx * sd
    off = nose + l / 2.0
    return {"x": px + nx * off, "y": py + ny * off, "a": math.degrees(math.atan2(-ny, -nx)) % 360.0}


def _in_zone(bay, r, poly, tol=0.8):
    """a bay stands in a parking area when all of it lies inside, except that its nose may stop short of the polygon edge by `tol` (the edge is drawn by hand)"""
    P = bay_poly(bay, r)
    for q in P + [(bay["x"], bay["y"])]:
        q = (bay["x"] + (q[0] - bay["x"]) * 0.97, bay["y"] + (q[1] - bay["y"]) * 0.97)
        if not (pip(q, poly) or min(seg_pt(q, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))) <= tol):
            return False
    return True


def road_plan(pts, width, smooth, r, left, right, start, zones, reach=4.0):
    """where the bays along a road go: a bay position every bay width, on either side (+1 left, -1 right), wanted because the road is told to have bays there
    (left / right: how many, -1 = as many as fit, 0 = none, from `start` metres) or because a parking area (name, polygon, most bays) reaches the road there.
    Where both sides have bays the road is a double-sided aisle and gets thicker: returns {"st": [(k, side, zone or None)], "dbl": [(from, to)]}"""
    r = rules(r)
    c = spline(pts, 0.25, smooth)
    if len(c) < 2:
        return {"st": [], "dbl": []}
    t, arc = _tangents(c), _arc(c)
    L, w = arc[-1], r["w"]
    n = int(L // w)
    want = {}
    for sd, cap in ((1, left), (-1, right)):
        if not cap:
            continue
        placed = 0
        for k in range(n):
            if k * w + w / 2.0 < start:
                continue
            if cap > 0 and placed >= cap:
                break
            want[(k, sd)] = None
            placed += 1
    half = max(width, r["aisle"]) / 2.0
    for zz in zones:
        name, poly, mx = zz[0], zz[1], zz[2]
        mode = zz[3] if len(zz) > 3 else 0
        got = []
        for k in range(n):
            sv = k * w + w / 2.0
            (px, py), (tx, ty) = _along(c, t, arc, sv)
            for sd in (1, -1):
                nx, ny = -ty * sd, tx * sd
                if any(pip((px + nx * tt, py + ny * tt), poly) for tt in [x * 1.0 for x in range(0, int(half + r["l"] + reach) + 1)]):
                    if not any(_in_zone(_road_bay(c, t, arc, k, sd, w, nz, r["l"]), r, poly) for nz in (r["aisle"] - width / 2.0, r["aisle"] / 2.0)):
                        continue                                   # the bay would stand outside the area
                    got += [(k, sd)] if mode == 0 else [(k, -sd)] if mode == 1 else [(k, sd), (k, -sd)]
        got = sorted(set(got))
        if mx:
            got = got[:int(mx)]
        for key in got:
            want.setdefault(key, name)
    dbl = merge_spans([(k * w, (k + 1) * w) for (k, sd) in want if (k, -sd) in want], 0.01)
    return {"st": [(k, sd, z) for (k, sd), z in sorted(want.items())], "dbl": dbl}


def road_place(pts, width, site, r, keep, name, rid, smooth, plan):
    """put the bays of a road plan on the ground, nose towards the road. The pushback (the aisle, 7 m) always ends exactly at the kerb on the other side:
    on a one-sided stretch the nose stands (aisle - half the road width) from the centre line, on a two-sided one the noses are the aisle apart"""
    r = rules(r)
    c = spline(pts, 0.25, smooth)
    if len(c) < 2:
        return []
    t, arc = _tangents(c), _arc(c)
    w, A, out = r["w"], r["aisle"], []
    both = {(k, sd) for k, sd, z in plan["st"]}
    for k, sd, zn in plan["st"]:
        (px, py), (tx, ty) = _along(c, t, arc, k * w + w / 2.0)
        nose = A / 2.0 if (k, -sd) in both else A - width / 2.0
        nx, ny = -ty * sd, tx * sd
        off = nose + r["l"] / 2.0
        bay = {"x": px + nx * off, "y": py + ny * off, "a": math.degrees(math.atan2(-ny, -nx)) % 360.0, "auto": True, "zone": name, "rid": rid}
        if zn:
            bay["rz"] = zn
        if not problems(bay, r, site, list(keep) + out):
            out.append(bay)
    return out
