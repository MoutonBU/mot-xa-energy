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

    def __init__(self, stand, buildings, env=None, others=None):
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
def _longest_dir(poly):
    best, ang = -1.0, 0.0
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L > best:
            best, ang = L, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return ang


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
                    if not problems(bay, r, site, keep):
                        out.append(bay)
                xs += W
        ys += pitch
    return out


def fill(zone, site, r=None, angle=None, keep=(), name=""):
    """Park a zone full. Rows run along the longest side of the zone (or along `angle`); the pattern is shifted a little in steps
    and turned a quarter, and the layout with the most bays wins. Bays you placed by hand (`keep`) stay where they are."""
    r = rules(r)
    zone = [tuple(p) for p in zone]
    if len(zone) < 3:
        return []
    base = _longest_dir(zone) if angle is None else angle
    best = []
    for th in ((base, base + 90.0) if angle is None else (base,)):
        for ty in [i * 1.0 for i in range(int(math.ceil(2 * r["l"] + r["aisle"])))]:
            for tx in (0.0, r["w"] / 2.0):
                got = _layout(zone, site, r, th, tx, ty, list(keep))
                if len(got) > len(best):
                    best = got
    placed = []
    for b in best:
        b["zone"] = name
        if not problems(b, r, site, list(keep) + placed):
            placed.append(b)
    return placed


def single(x, y, a, r=None):
    return {"x": x, "y": y, "a": a % 360.0, "auto": False, "zone": ""}


def required(units, per_unit=1.0, visitor_per=5):
    """bays needed: a bay (or more) for every unit, and a visitor's bay for every `visitor_per` units"""
    return int(math.ceil(units * per_unit - 1e-9)) + (int(math.ceil(units / float(visitor_per) - 1e-9)) if visitor_per else 0)
