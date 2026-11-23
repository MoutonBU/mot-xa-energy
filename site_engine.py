"""Site services engine: the house and carport on a stand, three service points (sewer, water, electrical) and the house's own
connection points (sewer outlet, water entry, DB). It routes each pipe or cable round the buildings, puts rodding eyes and
inspection eyes where they belong, works out the invert levels from the fall, and checks the result. No Qt in here.

Frame: metres. x along the street boundary, y into the stand. The street boundary is the first edge of the stand (corner 0 to corner 1).
Everything is recomputed from the state, so moving anything gives a new, consistent plan."""
import heapq
import math

GRID = 0.25
FAST = False                 # while the plan is being dragged: a coarser routing grid, so the lines follow at once; the exact ones come when you let go
DEFAULTS = {"fall": 50.0, "conn_depth": 1.5, "max_ie": 25.0, "min_depth": 0.45, "sewer_pipe": "110", "water_pipe": "20",
            "clear": 0.3, "re_ext": 0.35, "ie_first": 1.5, "sep_water": 0.5, "sep_service": 0.1, "min_cover": 0.3, "stub": 1.0, "sb_street": 1.0, "sb_side": 1.0, "sb_rear": 2.0, "fall_flat": 60.0, "fall_special": 120.0, "anchor_fall": 10.0}


# ------------------------------------------------------------------ geometry
def area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def inside(p, poly):
    x, y = p
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def poly_dist(p, poly):
    return min(seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def rect(cx, cy, w, d, rot=0.0):
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    pts = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]


def shape_poly(h):
    """a building outline: a rectangle, or an imported footprint (h["poly"]) turned by rot about its centre and put at cx, cy"""
    pl = h.get("poly")
    if not pl:
        return rect(h["cx"], h["cy"], h["w"], h["d"], h.get("rot", 0.0))
    mx = (min(p[0] for p in pl) + max(p[0] for p in pl)) / 2
    my = (min(p[1] for p in pl) + max(p[1] for p in pl)) / 2
    a = math.radians(h.get("rot", 0.0))
    ca, sa = math.cos(a), math.sin(a)
    return [(h["cx"] + (x - mx) * ca - (y - my) * sa, h["cy"] + (x - mx) * sa + (y - my) * ca) for x, y in pl]


def mark_points(h):
    """the marks of a library footprint (DB, SD, FD, G, KD) in stand coordinates, turned and placed with the house"""
    pl = h.get("poly")
    if not pl or not h.get("marks"):
        return []
    mx = (min(p[0] for p in pl) + max(p[0] for p in pl)) / 2
    my = (min(p[1] for p in pl) + max(p[1] for p in pl)) / 2
    a = math.radians(h.get("rot", 0.0))
    ca, sa = math.cos(a), math.sin(a)
    return [(m[0], (h["cx"] + (m[1] - mx) * ca - (m[2] - my) * sa, h["cy"] + (m[1] - mx) * sa + (m[2] - my) * ca)) for m in h["marks"]]


def house_poly(h):
    return shape_poly(h)


def carport_poly(c):
    return shape_poly(c) if c else None


def hull(pts):
    """convex hull (counter-clockwise); used so an L-shaped footprint is avoided as one block"""
    p = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))
    if len(p) < 3:
        return p

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in p:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(up) >= 2 and cr(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def outward(poly, i):
    """unit normal of edge i pointing out of the polygon"""
    a, b = poly[i], poly[(i + 1) % len(poly)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1
    n = (dy / L, -dx / L)
    return n if area(poly) > 0 else (-n[0], -n[1])


def port_point(poly, port):
    """point on the house outline and its outward direction for a stored port {edge, t}"""
    i = int(port["edge"]) % len(poly)
    a, b = poly[i], poly[(i + 1) % len(poly)]
    t = max(0.02, min(0.98, float(port["t"])))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), outward(poly, i)


def nearest_port(poly, pt):
    """the outline position closest to a clicked point -> {edge, t}"""
    best = None
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0.02, min(0.98, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L))
        d = math.hypot(pt[0] - a[0] - t * dx, pt[1] - a[1] - t * dy)
        if best is None or d < best[0]:
            best = (d, {"edge": i, "t": round(t, 3)})
    return best[1]


def auto_port(poly, target, t=0.5):
    """the side of the house that faces the target, on that side at fraction t"""
    best = None
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        n = outward(poly, i)
        facing = (target[0] - m[0]) * n[0] + (target[1] - m[1]) * n[1]
        score = math.hypot(target[0] - m[0], target[1] - m[1]) - (4.0 if facing > 0 else 0.0)
        if best is None or score < best[0]:
            best = (score, i)
    return {"edge": best[1], "t": t}


# ------------------------------------------------------------------ shortest routes
def _enters(a, b, poly):
    """True if the segment a-b runs through the inside of a convex counter-clockwise polygon (touching its edge does not count)"""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        nx, ny = -ey, ex                                   # inward normal of a counter-clockwise polygon
        num = (a[0] - p[0]) * nx + (a[1] - p[1]) * ny
        den = dx * nx + dy * ny
        if abs(den) < 1e-12:
            if num <= 1e-9:
                return False
            continue
        t = -num / den
        if den > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1 - 1e-9:
            return False
    return (t1 - t0) * math.hypot(dx, dy) > 0.02


def shortest(a, b, obstacles):
    """the shortest path from a to b round convex obstacles (any angle). Returns the corner points."""
    obs = []
    for o in obstacles:
        h = hull(o)
        if len(h) >= 3:
            obs.append(offset(h, -0.004))
    nodes = [tuple(a), tuple(b)]
    for o in obstacles:
        nodes += hull(o)
    n = len(nodes)

    def clear(p, q):
        return not any(_enters(p, q, o) for o in obs)
    dist = {0: 0.0}
    prev = {}
    done = set()
    while True:
        cur = None
        for k, v in dist.items():
            if k not in done and (cur is None or v < dist[cur]):
                cur = k
        if cur is None:
            break
        if cur == 1:
            break
        done.add(cur)
        for j in range(n):
            if j in done or j == cur:
                continue
            if clear(nodes[cur], nodes[j]):
                d = dist[cur] + math.hypot(nodes[cur][0] - nodes[j][0], nodes[cur][1] - nodes[j][1])
                if d < dist.get(j, 1e18):
                    dist[j] = d
                    prev[j] = cur
    if 1 not in dist:
        return [tuple(a), tuple(b)]
    out, k = [], 1
    while k != 0:
        out.append(nodes[k])
        k = prev[k]
    out.append(nodes[0])
    return out[::-1]


def parallel_gap(p1, p2, min_run=0.5):
    """the smallest distance between two paths where they run side by side (same or opposite direction within 6 degrees) for at least min_run"""
    best = None
    for i in range(len(p1) - 1):
        a, b = p1[i], p1[i + 1]
        la = math.hypot(b[0] - a[0], b[1] - a[1])
        if la < 1e-6:
            continue
        ux, uy = (b[0] - a[0]) / la, (b[1] - a[1]) / la
        for j in range(len(p2) - 1):
            c, d = p2[j], p2[j + 1]
            lc = math.hypot(d[0] - c[0], d[1] - c[1])
            if lc < 1e-6 or abs(ux * (d[1] - c[1]) / lc - uy * (d[0] - c[0]) / lc) > 0.105:
                continue
            t0, t1 = sorted([(c[0] - a[0]) * ux + (c[1] - a[1]) * uy, (d[0] - a[0]) * ux + (d[1] - a[1]) * uy])
            if min(t1, la) - max(t0, 0.0) < min_run:
                continue
            g = max(abs((c[0] - a[0]) * uy - (c[1] - a[1]) * ux), abs((d[0] - a[0]) * uy - (d[1] - a[1]) * ux))
            best = g if best is None else min(best, g)
    return best


def overlap_len(p1, p2, tol=0.35):
    """length over which two paths run on top of each other (same direction within 6 degrees and closer than tol)"""
    tot = 0.0
    for i in range(len(p1) - 1):
        a, b = p1[i], p1[i + 1]
        la = math.hypot(b[0] - a[0], b[1] - a[1])
        if la < 1e-6:
            continue
        ux, uy = (b[0] - a[0]) / la, (b[1] - a[1]) / la
        for j in range(len(p2) - 1):
            c, d = p2[j], p2[j + 1]
            lc = math.hypot(d[0] - c[0], d[1] - c[1])
            if lc < 1e-6:
                continue
            if abs(ux * (d[1] - c[1]) / lc - uy * (d[0] - c[0]) / lc) > 0.105:
                continue
            if min(abs((c[0] - a[0]) * uy - (c[1] - a[1]) * ux), abs((d[0] - a[0]) * uy - (d[1] - a[1]) * ux)) > tol:
                continue
            t0, t1 = sorted([(c[0] - a[0]) * ux + (c[1] - a[1]) * uy, (d[0] - a[0]) * ux + (d[1] - a[1]) * uy])
            tot += max(0.0, min(t1, la) - max(t0, 0.0))
    return tot


DEFAULT_MAINS = {"sewer": -1.2, "water": -2.0, "elec": -0.5}


def mains(state):
    m = dict(DEFAULT_MAINS)
    m.update(state.get("mains") or {})
    return m


def main_line(state):
    """the main sewer as a polyline when it runs through the stand (drawn by the user); None when it is the straight line along the street"""
    ml = state.get("main_line") or []
    return [tuple(p) for p in ml] if len(ml) >= 2 else None


def snap_main(state, w):
    """the point on the drawn main sewer nearest to w (None when the main is the straight street line)"""
    ml = main_line(state)
    if not ml:
        return None
    best = None
    for a, b in zip(ml[:-1], ml[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((w[0] - a[0]) * dx + (w[1] - a[1]) * dy) / L2))
        q = (a[0] + dx * t, a[1] + dy * t)
        d = math.hypot(q[0] - w[0], q[1] - w[1])
        if best is None or d < best[0]:
            best = (d, q)
    return (round(best[1][0], 3), round(best[1][1], 3))


def main_dist(state, w):
    """how far w is from the main sewer (the drawn one, or the straight street line)"""
    q = snap_main(state, w)
    return math.hypot(q[0] - w[0], q[1] - w[1]) if q else abs(w[1] - mains(state)["sewer"])


def main_poly(state, k):
    """the water or electrical main from the township drawing: a list of polylines (the main and its branches); None when there is none (then the straight line along the street)"""
    p = (state.get("main_poly") or {}).get(k) or []
    if not p:
        return None
    if isinstance(p[0][0], (int, float)):                        # one polyline given as a list of points
        p = [p]
    out = [[tuple(q) for q in pl] for pl in p if len(pl) >= 2]
    return out or None


def snap_poly(poly, w):
    """the point on a polyline (or on the nearest of several polylines) nearest to w"""
    polys = poly if poly and isinstance(poly[0][0], (list, tuple)) else [poly]
    best = None
    for pl in polys:
        for a, b in zip(pl[:-1], pl[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((w[0] - a[0]) * dx + (w[1] - a[1]) * dy) / L2))
            q = (a[0] + dx * t, a[1] + dy * t)
            d = math.hypot(q[0] - w[0], q[1] - w[1])
            if best is None or d < best[0]:
                best = (d, q)
    return (round(best[1][0], 3), round(best[1][1], 3))


def conn_point(state, k):
    """the connection point on the main line: x as placed, y on the main line (a sewer main that runs through the stand: the nearest point on it)"""
    if k == "sewer" and main_line(state):
        return snap_main(state, state["points"]["sewer"])
    mp = main_poly(state, k) if k != "sewer" else None
    if mp:                                                      # the real main from the township drawing: the nearest point on it to where the line leaves the stand
        return snap_poly(mp, (state["points"][k][0], 0.0))
    return (state["points"][k][0], mains(state)[k])


def candidates(state, k):
    """the main connection plus any custom points of that kind"""
    out = [conn_point(state, k)]
    for c in state.get("custom") or []:
        if c.get("kind") == k:
            out.append(tuple(c["pt"]))
    return out


def best_line(a, cands, obstacles, others=()):
    """shortest route from a to whichever candidate is nearest by path; tries small sideways shifts of a if it would run on top of another line"""
    best = None
    for c in cands:
        p = shortest(a, c, obstacles)
        L = length(p)
        if best is None or L < best[0]:
            best = (L, p)
    return best[1]


# ------------------------------------------------------------------ routing
def route(a, b, stand, blocked, street_band=2.5, pad=2.0, bend=3.0):
    """Orthogonal route from a to b on a 0.25 m grid. Blocked polygons are avoided; open land of the neighbours costs a lot,
    the strip in front of the street boundary costs nothing extra (that is where mains are). Returns a list of corner points."""
    G = 0.5 if FAST else GRID
    xs = [p[0] for p in stand] + [a[0], b[0]]
    ys = [p[1] for p in stand] + [a[1], b[1]]
    x0, y0 = min(xs) - pad, min(ys) - pad
    nx = int((max(xs) + pad - x0) / G) + 1
    ny = int((max(ys) + pad - y0) / G) + 1
    cell = {}
    street = (stand[0], stand[1])
    bbs = [(min(q[0] for q in poly), min(q[1] for q in poly), max(q[0] for q in poly), max(q[1] for q in poly), poly) for poly in blocked]
    sbb = (min(q[0] for q in stand), min(q[1] for q in stand), max(q[0] for q in stand), max(q[1] for q in stand))

    def cost(i, j):
        k = (i, j)
        if k in cell:
            return cell[k]
        p = (x0 + i * G, y0 + j * G)
        c = 1.0
        for bx0, by0, bx1, by1, poly in bbs:
            if bx0 <= p[0] <= bx1 and by0 <= p[1] <= by1 and inside(p, poly):
                c = None
                break
        if c is not None and not (sbb[0] <= p[0] <= sbb[2] and sbb[1] <= p[1] <= sbb[3] and inside(p, stand)):
            c = 1.4 if seg_dist(p, *street) < street_band else 8.0
        cell[k] = c
        return c

    s = (int(round((a[0] - x0) / G)), int(round((a[1] - y0) / G)))
    g = (int(round((b[0] - x0) / G)), int(round((b[1] - y0) / G)))
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    pq = [(0.0, 0.0, s, -1)]
    best = {(s, -1): 0.0}
    prev = {}
    end = None
    while pq:
        f, d, cur, dr = heapq.heappop(pq)
        if cur == g:
            end = (cur, dr)
            break
        if d > best.get((cur, dr), 1e18) + 1e-9:
            continue
        for k, (dx, dy) in enumerate(dirs):
            nxt = (cur[0] + dx, cur[1] + dy)
            if not (0 <= nxt[0] < nx and 0 <= nxt[1] < ny):
                continue
            c = cost(*nxt)
            if c is None and nxt != g:
                continue
            nd = d + (c or 1.0) * G + (bend if dr not in (-1, k) else 0.0)
            if nd < best.get((nxt, k), 1e18) - 1e-9:
                best[(nxt, k)] = nd
                prev[(nxt, k)] = (cur, dr)
                heapq.heappush(pq, (nd + (abs(nxt[0] - g[0]) + abs(nxt[1] - g[1])) * G, nd, nxt, k))
    if end is None:
        return [a, b]
    cells = []
    node = end
    while node in prev or node[0] == s:
        cells.append(node[0])
        if node[0] == s and node not in prev:
            break
        node = prev[node]
    cells.reverse()
    pts = [(x0 + i * G, y0 + j * G) for i, j in cells]
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        d1 = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        d2 = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 1e-9:
            out.append(pts[i])
    out.append(pts[-1])
    out[0], out[-1] = a, b
    # the grid centre of the first/last step can be off the exact point: keep the run square by moving the neighbour
    if len(out) > 2:
        for idx, nb in ((1, 0), (len(out) - 2, len(out) - 1)):
            p, q = out[idx], out[nb]
            if abs(p[0] - q[0]) < 0.2:
                out[idx] = (q[0], p[1])
            elif abs(p[1] - q[1]) < 0.2:
                out[idx] = (p[0], q[1])
    return dedupe(out)


def dedupe(pts):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 0.02:
            out.append(p)
    # drop points that sit on a straight run, so only real bends remain
    k = [out[0]] if out else []
    for i in range(1, len(out) - 1):
        a, b, c = k[-1], out[i], out[i + 1]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6:
            k.append(b)
    if len(out) > 1:
        k.append(out[-1])
    return k


def length(path):
    return sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]) for i in range(len(path) - 1))


def point_at(path, s):
    """point and direction at distance s along the path"""
    acc = 0.0
    for i in range(len(path) - 1):
        L = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        if acc + L >= s - 1e-9 and L > 0:
            t = (s - acc) / L
            return (path[i][0] + (path[i + 1][0] - path[i][0]) * t, path[i][1] + (path[i + 1][1] - path[i][1]) * t)
        acc += L
    return path[-1]


def crossing(path, stand):
    """distance along the path where it first enters the stand, or None"""
    acc = 0.0
    prev_in = inside(path[0], stand)
    for i in range(len(path) - 1):
        L = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        n = max(1, int(L / 0.05))
        for k in range(1, n + 1):
            p = point_at(path, acc + L * k / n)
            cur = inside(p, stand)
            if cur != prev_in:
                return acc + L * k / n
        acc += L
    return None


# ------------------------------------------------------------------ the three services
def _obstacles(hp, cp, params, with_carport=True):
    return [offset(hull(hp), params["clear"])] + ([offset(hull(cp), params["clear"])] if (cp and with_carport) else [])


def manual_route(q1, man, modes, mainy, free_all=False):
    """the run you drew, point by point: each point comes with how the pipe gets to it from the one before - square (an elbow), skew (straight to it),
    horizontal or vertical (forced level / upright). The last point is always on the main line."""
    pts = [tuple(q1)]
    n = len(man)
    for i, m in enumerate(man):
        mode = "free" if free_all else (modes[i] if i < len(modes) else "sq")
        a, b = pts[-1], tuple(m)
        last = i == n - 1
        if last:
            b = (b[0], mainy)
        elif mode == "h":
            b = (b[0], a[1])
        elif mode == "v":
            b = (a[0], b[1])
        if mode == "sq" or (last and mode in ("h", "v")):
            if abs(a[0] - b[0]) > 1e-3 and abs(a[1] - b[1]) > 1e-3:
                if len(pts) >= 2 and abs(pts[-2][0] - a[0]) < 1e-3:
                    pts.append((a[0], b[1]))
                else:
                    pts.append((b[0], a[1]))
        pts.append(b)
    return dedupe(pts)


def square_join(pts):
    """a chain of points made square: where two points are not level, an elbow goes in, turning the same way the run was already going"""
    out = [tuple(pts[0])]
    for b in pts[1:]:
        a, b = out[-1], tuple(b)
        if abs(a[0] - b[0]) > 1e-3 and abs(a[1] - b[1]) > 1e-3:
            if len(out) >= 2 and abs(out[-2][0] - a[0]) < 1e-3:
                out.append((a[0], b[1]))
            else:
                out.append((b[0], a[1]))
        out.append(b)
    return dedupe(out)


def ortho(path):
    """make every leg run along x or y: where a leg is slanted, put an elbow in"""
    out = [path[0]]
    for q in path[1:]:
        p = out[-1]
        if abs(q[0] - p[0]) > 1e-3 and abs(q[1] - p[1]) > 1e-3:
            out.append((q[0], p[1]))
        out.append(q)
    return dedupe(out)


def best_ortho(a, cands, stand, blocked, from_end=False):
    best = None
    for c in cands:
        p = ortho(route(a, c, stand, blocked))
        L = length(p)
        if best is None or L < best[0]:
            best = (L, p)
    return best[1]


def _mark_port(state, hp, kinds, target):
    """a house port taken from the footprint's own marks (the mark nearest the target), or None"""
    best = None
    for kind, pt in mark_points(state["house"]):
        if kind in kinds:
            d = math.hypot(pt[0] - target[0], pt[1] - target[1])
            if best is None or d < best[0]:
                best = (d, pt)
    return nearest_port(hp, best[1]) if best else None


def _port_for(state, hp, key, target, t0, others, build, kinds=()):
    """house port: the user's, or the side that faces the target; the automatic one is nudged along the wall until the line does not run on top of another"""
    user = (state.get("ports") or {}).get(key) or (_mark_port(state, hp, kinds, target) if kinds else None)
    if user:
        return user, build(user)
    base = auto_port(hp, target, t0)
    best = None
    for dt in (0, 0.1, -0.1, 0.2, -0.2, 0.3, -0.3, 0.4, -0.4):
        port = {"edge": base["edge"], "t": round(min(0.95, max(0.05, base["t"] + dt)), 3)}
        r = build(port)
        ov = sum(overlap_len(r["path"], o) for o in others)
        if best is None or ov < best[0]:
            best = (ov, port, r)
        if ov < 0.3:
            break
    return best[1], best[2]


def join45(state, path, k=1.2):
    """state["sewer_join"] = +1 / -1: the run meets the main sewer at 45 degrees instead of square. The last leg is shortened by k, then a leg at 45 degrees to the
    main (and to that leg) carries on to the connection point; where the leg before it runs along the main, its corner slides along it, so the run stays tidy.
    Returns the new path (the same one when it does not apply)."""
    sj = state.get("sewer_join")
    if not sj or len(path) < 2:
        return path
    X, A = path[-1], path[-2]
    Ll = math.hypot(X[0] - A[0], X[1] - A[1])
    if Ll < 0.8:
        return path
    n = ((X[0] - A[0]) / Ll, (X[1] - A[1]) / Ll)
    m = (1.0, 0.0)
    pls = main_poly(state, "sewer") if False else None
    ml = main_line(state)
    if ml and len(ml) > 1:
        best = min(range(len(ml) - 1), key=lambda i: seg_dist(X, ml[i], ml[i + 1]))
        dx, dy = ml[best + 1][0] - ml[best][0], ml[best + 1][1] - ml[best][1]
        Lm = math.hypot(dx, dy) or 1.0
        m = (dx / Lm, dy / Lm)
    if abs(n[0] * m[0] + n[1] * m[1]) > 0.35:                      # the last leg does not meet the main square: nothing to turn
        return path
    sg = 1.0 if sj > 0 else -1.0
    k = min(k, Ll * 0.6)
    C = (X[0] - n[0] * k - sg * m[0] * k, X[1] - n[1] * k - sg * m[1] * k)
    if len(path) >= 3:
        P = path[-3]
        dP = (A[0] - P[0], A[1] - P[1])
        LP = math.hypot(*dP)
        if LP > 0.2 and abs(dP[0] * m[1] - dP[1] * m[0]) / LP < 0.2:   # the leg before runs along the main: its corner slides along it
            A2 = (A[0] - sg * m[0] * k, A[1] - sg * m[1] * k)
            along = ((A2[0] - P[0]) * dP[0] + (A2[1] - P[1]) * dP[1]) / LP
            if along > 0.3:
                return dedupe(list(path[:-2]) + [A2, C, X])
    return dedupe(list(path[:-1]) + [C, X])


def sewer(state, hp, cp, params, others=()):
    """Square (90 degree) runs only. The house outlet leaves the wall, turns into the run at an inspection eye, and the run carries on a little
    way past that eye to the rodding eye, which is the highest point of the line: that is where the minimum invert is. From there the pipe
    falls all the way to the main sewer line."""
    stand = state["stand"]["corners"]
    obs = _obstacles(hp, cp, params)
    cands = candidates(state, "sewer")

    def build(port):
        p0, n0 = port_point(hp, port)
        stub = params["stub"]
        q1 = (p0[0] + n0[0] * stub, p0[1] + n0[1] * stub)
        via = [tuple(p) for p in (state.get("sewer_via") or [])]
        man = [tuple(p) for p in (state.get("sewer_manual") or [])]
        rest = [q1]
        if man:                                                  # a run you have placed by hand: it stays where you put it, kept square, ending on the main line
            cpt = conn_point(state, "sewer")
            man[-1] = (cpt[0], cpt[1])
            via = []
            rest = manual_route(q1, man, state.get("sewer_modes") or [], cpt[1], bool(state.get("sewer_free")))
        for v_ in via:                                           # your own sewer points: the run goes through them in order, square
            rest = dedupe(rest[:-1] + ortho(route(rest[-1], v_, stand, obs)))
        if not man:
            rest = dedupe(rest[:-1] + best_ortho(rest[-1], cands, stand, obs))
        while len(rest) > 2:                                     # fail-safe: the outlet pipe never runs past the run. If the run's first leg turns back along the outlet
            e1 = (rest[1][0] - rest[0][0], rest[1][1] - rest[0][1])   # (a hand-placed run that sits nearer the wall than the stub), the outlet ends where the run is
            le = math.hypot(*e1) or 1.0
            back = (e1[0] * n0[0] + e1[1] * n0[1]) / le < -0.9
            s_ = (rest[1][0] - p0[0]) * n0[0] + (rest[1][1] - p0[1]) * n0[1]
            if back and s_ >= 0.15 and abs((rest[1][0] - p0[0]) * n0[1] - (rest[1][1] - p0[1]) * n0[0]) < 0.05:
                q1 = rest[1]
                rest = rest[1:]
            else:
                break
        e1 = (rest[1][0] - rest[0][0], rest[1][1] - rest[0][1]) if len(rest) > 1 else (0.0, 0.0)
        if math.hypot(*e1) > 0.02 and (e1[0] * n0[0] + e1[1] * n0[1]) / math.hypot(*e1) < -0.3:
            rest = dedupe([q1] + best_ortho(q1, cands, stand, obs))   # still turning back into the outlet: that hand-placed run cannot be used, so route it automatically
        d1 = (rest[1][0] - rest[0][0], rest[1][1] - rest[0][1])
        L1 = math.hypot(*d1) or 1.0
        u = (d1[0] / L1, d1[1] / L1)
        along = u[0] * n0[0] + u[1] * n0[1]
        if along > 0.9:                                          # the run carries straight on from the outlet: the rodding eye is at the wall
            path = dedupe([p0] + rest)
            return {"path": path, "port": port, "branch": None, "q1": q1, "junction": 0.0, "tail": 0.0}
        tail = params["re_ext"]                                  # the outlet butts flush onto the run at q1; the run itself carries on a little way past the joint, ending in a rodding eye
        t0 = (q1[0] - u[0] * tail, q1[1] - u[1] * tail)
        path = dedupe([t0] + rest)
        return {"path": path, "port": port, "branch": [p0, q1], "q1": q1, "junction": tail, "tail": tail}
    port, r = _port_for(state, hp, "sewer", cands[0], 0.25, others, build, ("SD",))
    path = join45(state, r["path"])
    r["path"] = path
    L = length(path)
    fall = params["fall"]
    cut = crossing(path, stand)
    jn = r["junction"]
    branched = bool(r.get("branch"))
    marks = [(0.0, "RE")]                                        # the rodding eye at the end of the run
    if jn > 0:
        marks.append((jn, "IE"))                                 # an inspection eye where the outlet pipe joins
    acc = 0.0
    for i in range(1, len(path) - 1):
        acc += math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        if all(abs(acc - m[0]) > 0.3 for m in marks):
            marks.append((acc, "IE"))                            # and one at every bend
    if cut is not None and all(abs(cut - m[0]) > 0.6 for m in marks):
        marks.append((max(cut - params["re_ext"], 0.3), "RE"))  # the rodding eye comes first, just inside the boundary, then the inspection eye against the stand (below)
    for v_ in (state.get("sewer_via") or []):                    # an inspection eye at every point you put in
        best = min(range(0, int(L * 20) + 1), key=lambda k: math.hypot(point_at(path, k / 20.0)[0] - v_[0], point_at(path, k / 20.0)[1] - v_[1]))
        c_ = best / 20.0
        if all(abs(c_ - m[0]) > 0.3 for m in marks) and 0.3 < c_ < L - 0.3:
            marks.append((c_, "IE"))
    if jn == 0 and not branched and all(abs(m[0] - min(params["ie_first"], L)) > 0.3 for m in marks):
        marks.append((min(params["ie_first"], L), "IE"))
    marks.sort()
    full = []
    for k, (s_, kind) in enumerate(marks):
        full.append((s_, kind))
        nxt = marks[k + 1][0] if k + 1 < len(marks) else L
        gap = nxt - s_
        if gap > params["max_ie"]:
            n = int(gap // params["max_ie"])
            for q in range(1, n + 1):
                full.append((s_ + gap * q / (n + 1), "IE"))
    full.sort()
    D0 = params["min_depth"]
    nodes = []
    for s_, kind in full:
        nodes.append({"kind": kind, "pt": point_at(path, s_), "chainage": round(s_, 2), "depth": round(D0 + s_ / fall, 3),
                      "label": kind + (" Min IL %d" % round(D0 * 1000) if kind == "RE" and s_ == 0 and not branched else "")})
    if branched:
        nodes.insert(0, {"kind": "RE", "pt": r["branch"][0], "chainage": 0.0, "depth": round(D0, 3), "label": "RE Min IL %d" % round(D0 * 1000)})
    stubs = []                                                    # where the run turns a corner, the leg after it is carried back re_ext past the corner to a rodding eye
    acc = 0.0
    for i in range(1, len(path) - 1):
        a_, b_, c_ = path[i - 1], path[i], path[i + 1]
        acc += math.hypot(b_[0] - a_[0], b_[1] - a_[1])
        d1 = (b_[0] - a_[0], b_[1] - a_[1])
        d2 = (c_[0] - b_[0], c_[1] - b_[1])
        l1, l2 = math.hypot(*d1), math.hypot(*d2)
        if l1 < 1e-6 or l2 < 1e-6 or abs(d1[0] * d2[1] - d1[1] * d2[0]) / (l1 * l2) < 0.5:
            continue
        end = (b_[0] - d2[0] / l2 * params["re_ext"], b_[1] - d2[1] / l2 * params["re_ext"])   # the next leg, carried back past the corner
        stubs.append([b_, end])
        si = len(stubs) - 1
        if not any(abs(n["chainage"] - acc) < 0.3 and n["kind"] == "IE" for n in nodes):
            nodes.append({"kind": "IE", "pt": b_, "chainage": round(acc, 2), "depth": round(D0 + acc / fall, 3), "label": "IE"})
        nodes.append({"kind": "RE", "pt": end, "chainage": round(acc, 2), "depth": round(D0 + acc / fall, 3), "label": "RE", "stub": si})
    if cut is not None and 0 < cut < L:
        nodes.append({"kind": "IE", "pt": point_at(path, cut), "chainage": round(cut, 2), "depth": round(D0 + cut / fall, 3), "label": "IE"})
    extra = []                                                    # more sewer outlets on the house (up to 4 in all): each runs square to the nearest point of the run and butts onto it
    for wp in (state.get("sewer_ports") or [])[:3]:
        p0, n0 = port_point(hp, wp)
        start = (p0[0] + n0[0] * 0.5, p0[1] + n0[1] * 0.5)
        samples = [(k * 0.5, point_at(path, min(k * 0.5, L))) for k in range(int(L / 0.5) + 1)]
        samples.sort(key=lambda q: abs(q[1][0] - start[0]) + abs(q[1][1] - start[1]))
        best = None
        for c_, q in samples[:(1 if FAST else 4)]:
            pr = ortho(route(q, start, stand, obs))
            Lq = length(pr)
            if best is None or Lq < best[0]:
                best = (Lq, pr, c_)
        bp = dedupe(best[1] + [p0])
        extra.append({"path": bp, "port": wp})
        nodes.append({"kind": "IE", "pt": bp[0], "chainage": round(best[2], 2), "depth": round(D0 + best[2] / fall, 3), "label": "IE", "dist": L - best[2]})
        nodes.append({"kind": "RE", "pt": p0, "chainage": round(best[2] + 0.001, 2), "depth": round(D0 + best[2] / fall, 3), "label": "RE", "wall": len(extra) - 1,
                      "dist": (L - best[2]) + length(bp)})
    # fail-safe: every eye the rules ask for is there, whatever the spacing or distance checks above decided (a bend close to a joint, a short leg...)
    def _chain(pt):
        k_ = min(range(0, int(L * 20) + 1), key=lambda k: math.hypot(point_at(path, k / 20.0)[0] - pt[0], point_at(path, k / 20.0)[1] - pt[1]))
        return k_ / 20.0

    def _need(kind, pt, ch=None, **kw):
        if any(n["kind"] == kind and math.hypot(n["pt"][0] - pt[0], n["pt"][1] - pt[1]) < (0.45 if kind == "IE" else 0.06) for n in nodes):
            return
        c_ = _chain(pt) if ch is None else ch
        d = {"kind": kind, "pt": tuple(pt), "chainage": round(c_, 2), "depth": round(D0 + c_ / fall, 3), "label": kind}
        d.update(kw)
        nodes.append(d)
    _need("RE", path[0], 0.0)
    for b_, e_ in stubs:
        _need("IE", b_)
        _need("RE", e_, None, stub=stubs.index([b_, e_]) if [b_, e_] in stubs else 0)
    if branched:
        _need("IE", r["branch"][1])
        _need("RE", r["branch"][0], 0.0, label="RE Min IL %d" % round(D0 * 1000))
    if cut is not None and 0 < cut < L:
        _need("IE", point_at(path, cut))
    for ex_ in extra:
        _need("IE", ex_["path"][0])
        _need("RE", ex_["path"][-1], None, wall=extra.index(ex_), dist=L)
    # never two inspection eyes on top of each other: within 0.45 m of one another they are one eye (the one on a bend or joint stays)
    req_pts = [b_ for b_, _e in stubs] + ([r["branch"][1]] if branched else []) + [ex_["path"][0] for ex_ in extra]
    ies = [n for n in nodes if n["kind"] == "IE"]
    ies.sort(key=lambda n: (not any(math.hypot(n["pt"][0] - q[0], n["pt"][1] - q[1]) < 0.06 for q in req_pts), n["chainage"]))
    keep_ie = []
    for n in ies:
        if all(math.hypot(n["pt"][0] - k["pt"][0], n["pt"][1] - k["pt"][1]) >= 0.45 for k in keep_ie):
            keep_ie.append(n)
    nodes = [n for n in nodes if n["kind"] != "IE" or any(n is k for k in keep_ie)]
    nodes.sort(key=lambda n: n["chainage"])
    cnt = {}
    for n_ in nodes:                                              # a key for every eye (kind + number along the run), so you can pick, move and delete them
        cnt[n_["kind"]] = cnt.get(n_["kind"], -1) + 1
        n_["key"] = "%s%d" % (n_["kind"], cnt[n_["kind"]])
    ed = state.get("eyes") or {}
    gone = set()                                                  # eyes cannot be left out: the rules need every one of them (Eyes back still resets any you moved)
    drop = set()
    for n_ in nodes:
        if n_["key"] in gone:
            drop.add(n_["key"])
            if "stub" in n_:
                stubs[n_["stub"]] = None
        elif n_["key"] in (ed.get("pos") or {}):
            n_["pt"] = tuple(ed["pos"][n_["key"]])
            if "stub" in n_ and stubs[n_["stub"]]:
                stubs[n_["stub"]][1] = n_["pt"]
    nodes = [n_ for n_ in nodes if n_["key"] not in drop]
    stubs = [x for x in stubs if x]
    # the minimum invert (Min IL) is at the outlet furthest from the main, whichever that is: a toilet that sits further up the line moves it there,
    # and every invert level is worked back from it
    walls = [n_ for n_ in nodes if "wall" in n_ or str(n_.get("label", "")).startswith("RE Min")]
    for n_ in walls:
        if "wall" not in n_:
            n_["dist"] = L
    H = max([L] + [n_["dist"] for n_ in walls])
    head = max(walls, key=lambda n_: n_["dist"]) if walls else None
    for n_ in nodes:
        dist = n_.get("dist", L - n_["chainage"])
        n_["depth"] = round(D0 + (H - dist) / fall, 3)
        if n_["kind"] == "RE" and "dist" in n_ and n_.get("label", "").startswith("RE"):
            n_["label"] = ("RE Min IL %d" % round(D0 * 1000)) if n_ is head else "RE"
    d_main = D0 + H / fall
    nodes.append({"kind": "MAIN", "pt": path[-1], "chainage": round(L, 2), "depth": round(d_main, 3), "label": "Connect to main sewer line"})
    return {"path": path, "nodes": nodes, "length": round(H, 2), "drop_mm": round(H * 1000.0 / fall), "port": port, "branch": r["branch"],
            "stubs": stubs, "extra": extra, "depth_house": round(D0, 3), "depth_main": round(d_main, 3), "note": "%s\u00d8 SWP, FALL 1:%d" % (params["sewer_pipe"], round(fall))}


def straight_out(p0, n0, net, hp, bounds_ok=None):
    """a pipe from the house point p0 that leaves the house square to the plan (along x or y, never into the house) and runs straight onto the nearest
    straight piece of the pipes already laid. Returns the path from the pipe to p0, or None when there is no such way."""
    best = None
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if d[0] * n0[0] + d[1] * n0[1] < 0.2:
            continue                                              # that way goes into the house or along its wall
        for pp in net:
            for a, b in zip(pp[:-1], pp[1:]):
                if d[0] != 0:
                    if abs(a[0] - b[0]) > 1e-3 or (a[0] - p0[0]) * d[0] < 0.15:
                        continue
                    lo, hi = sorted((a[1], b[1]))
                    if not (lo - 1e-6 <= p0[1] <= hi + 1e-6):
                        continue
                    q = (a[0], p0[1])
                else:
                    if abs(a[1] - b[1]) > 1e-3 or (a[1] - p0[1]) * d[1] < 0.15:
                        continue
                    lo, hi = sorted((a[0], b[0]))
                    if not (lo - 1e-6 <= p0[0] <= hi + 1e-6):
                        continue
                    q = (p0[0], a[1])
                L = math.hypot(q[0] - p0[0], q[1] - p0[1])
                ok = all(not inside((p0[0] + (q[0] - p0[0]) * k / 40.0, p0[1] + (q[1] - p0[1]) * k / 40.0), hp) for k in range(2, 41))
                if ok and (bounds_ok is None or bounds_ok(q)) and (best is None or L < best[0]):
                    best = (L, [q, p0])
    if best:
        return best[1]
    # no straight way: out square to the plan, then one turn, then straight onto a piece of pipe that runs the same way as the first leg
    def clear(a, b):
        return all(not inside((a[0] + (b[0] - a[0]) * k / 30.0, a[1] + (b[1] - a[1]) * k / 30.0), hp) for k in range(1, 31))
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if d[0] * n0[0] + d[1] * n0[1] < 0.2:
            continue
        ax = 0 if d[0] != 0 else 1                                 # the axis the first leg runs along
        for pp in net:
            for a, b in zip(pp[:-1], pp[1:]):
                if abs(a[1 - ax] - b[1 - ax]) > 1e-3:
                    continue                                       # the piece must run along the same axis as the first leg
                lo, hi = sorted((a[ax], b[ax]))
                sgn = d[ax]
                lim = p0[ax] + sgn * 0.5
                tgt = min(max(lim, lo), hi) if sgn > 0 else min(max(lim, lo), hi)
                if (tgt - p0[ax]) * sgn < 0.5:
                    tgt = lim if lo - 1e-6 <= lim <= hi + 1e-6 else None
                if tgt is None:
                    continue
                c = list(p0)
                c[ax] = tgt
                q = list(c)
                q[1 - ax] = a[1 - ax]
                c, q = tuple(c), tuple(q)
                L = math.hypot(c[0] - p0[0], c[1] - p0[1]) + math.hypot(q[0] - c[0], q[1] - c[1])
                if clear(p0, c) and clear(c, q) and (best is None or L < best[0]):
                    best = (L, [q, c, p0])
    return best[1] if best else None


def rounded(path, r=0.45, steps=6):
    """the same path with every corner rounded (a quarter-circle-like curve of radius about r)"""
    if len(path) < 3:
        return list(path)
    out = [tuple(path[0])]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        l1, l2 = math.hypot(b[0] - a[0], b[1] - a[1]), math.hypot(c[0] - b[0], c[1] - b[1])
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        rr = min(r, l1 / 2.0, l2 / 2.0)
        p1 = (b[0] + (a[0] - b[0]) / l1 * rr, b[1] + (a[1] - b[1]) / l1 * rr)
        p2 = (b[0] + (c[0] - b[0]) / l2 * rr, b[1] + (c[1] - b[1]) / l2 * rr)
        for k in range(steps + 1):
            t = k / float(steps)
            out.append(((1 - t) ** 2 * p1[0] + 2 * (1 - t) * t * b[0] + t * t * p2[0], (1 - t) ** 2 * p1[1] + 2 * (1 - t) * t * b[1] + t * t * p2[1]))
    out.append(tuple(path[-1]))
    return out


def water(state, hp, cp, params, others=()):
    """square runs; a paved carport can be crossed"""
    stand = state["stand"]["corners"]
    obs = _obstacles(hp, cp, params, with_carport=False)
    cands = candidates(state, "water")

    def build(port):
        p0, n0 = port_point(hp, port)
        start = (p0[0] + n0[0] * 0.5, p0[1] + n0[1] * 0.5)
        best = best_ortho(start, cands, stand, obs)[::-1]
        return {"path": dedupe(best + [p0]), "port": port}
    port, r = _port_for(state, hp, "water", cands[0], 0.7, others, build, ("KD",))
    path = r["path"]
    L = length(path)
    cut = crossing(path, stand)
    nodes = [{"kind": "WCON", "pt": point_at(path, cut) if cut is not None else path[0], "chainage": round(cut or 0.0, 2), "label": "W.CON"}]
    if cut is not None:
        nodes.append({"kind": "WM", "pt": point_at(path, cut + 0.6), "chainage": round(cut + 0.6, 2), "label": "Water meter"})
    nodes.append({"kind": "SC", "pt": point_at(path, max(L - 0.6, 0)), "chainage": round(max(L - 0.6, 0), 2), "label": "Stop cock"})
    # more water points on the house (up to 4 in all): each one branches off the nearest point of the water pipe already laid
    branches = []
    net = [path]
    for wp in (state.get("water_ports") or [])[:3]:
        p0, n0 = port_point(hp, wp)
        start = (p0[0] + n0[0] * 0.5, p0[1] + n0[1] * 0.5)
        samples = []
        for pp in net:
            for k in range(int(length(pp) / 0.5) + 1):
                samples.append(point_at(pp, min(k * 0.5, length(pp))))
        samples.sort(key=lambda q: abs(q[0] - start[0]) + abs(q[1] - start[1]))
        bp = straight_out(p0, n0, net, hp)                       # straight out of the wall, square to the plan, onto the pipe already laid
        if bp is None:
            best = None
            for q in samples[:(1 if FAST else 4)]:
                pr = ortho(route(q, start, stand, obs))
                Lq = length(pr)
                if best is None or Lq < best[0]:
                    best = (Lq, pr)
            bp = dedupe(best[1] + [p0])
        branches.append({"path": bp, "port": wp})
        net.append(bp)
        nodes.append({"kind": "SC", "pt": point_at(bp, max(length(bp) - 0.6, 0)), "chainage": 0.0, "label": "Stop cock"})
        L += length(bp)
    return {"path": path, "branches": branches, "nodes": nodes, "length": round(L, 2), "port": port, "note": "%smm Cold Water Line" % params["water_pipe"]}


def electrical(state, hp, cp, params, others=()):
    """the shortest way to the DB, any angle; it can pass under a paved carport"""
    obs = _obstacles(hp, cp, params, with_carport=False)
    cands = candidates(state, "elec")

    def build(port):
        p0, n0 = port_point(hp, port)
        start = (p0[0] + n0[0] * 0.3, p0[1] + n0[1] * 0.3)
        best = best_line(start, cands, obs)[::-1]
        return {"path": dedupe(best + [p0]), "port": port}
    port, r = _port_for(state, hp, "db", cands[0], 0.8, others, build, ("DB",))
    path = r["path"]
    L = length(path)
    nodes = [{"kind": "EC", "pt": path[0], "chainage": 0.0, "label": "EC"}, {"kind": "DB", "pt": path[-1], "chainage": round(L, 2), "label": "DB"}]
    return {"path": path, "nodes": nodes, "length": round(L, 2), "port": port, "note": "Electrical line"}


def offset(poly, d):
    """polygon grown by d (convex shapes: moves every vertex away from the centre)"""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    out = []
    for p in poly:
        dx, dy = p[0] - cx, p[1] - cy
        L = math.hypot(dx, dy) or 1
        out.append((p[0] + dx / L * d * 1.1, p[1] + dy / L * d * 1.1))
    return out


# ------------------------------------------------------------------ checks and the whole solve
def edge_kinds(stand):
    """street = edge 0, the edges touching it are sides, the rest is rear"""
    n = len(stand)
    return ["street" if i == 0 else "side" if i in (1, n - 1) else "rear" for i in range(n)]


def wall_on(state, i, kind):
    """is there a 1.2 m boundary wall on edge i? the user's choice if they made one, else along the sides and the rear"""
    ov = (state.get("wall_edges") or {}).get(str(i))
    if ov is not None:
        return bool(ov)
    return kind in ("side", "rear")


def snap_to_edge(stand, w, edge=None, tol=4.0, corner=0.4):
    """the point on the stand's boundary nearest to w (on boundary `edge` only when given): (edge, t along it 0..1, point), or None when it is further than tol.
    It sticks to a corner when within `corner` metres of it."""
    n = len(stand)
    best = None
    for i in ([edge] if edge is not None else range(n)):
        a, b = stand[i], stand[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((w[0] - a[0]) * dx + (w[1] - a[1]) * dy) / L2))
        L = math.sqrt(L2)
        if t * L < corner:
            t = 0.0
        elif (1 - t) * L < corner:
            t = 1.0
        q = (a[0] + dx * t, a[1] + dy * t)
        d = math.hypot(w[0] - q[0], w[1] - q[1])
        if best is None or d < best[0]:
            best = (d, i, t, q)
    if best is None or best[0] > tol:
        return None
    return best[1], best[2], best[3]


def line_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / L


def checks(state, hp, cp, params, res):
    w = []
    stand = state["stand"]["corners"]
    kinds = edge_kinds(stand)
    sb = {"street": params["sb_street"], "side": params["sb_side"], "rear": params["sb_rear"]}
    sbs = state["stand"].get("setbacks") or {}
    sb.update({k: v for k, v in sbs.items() if v is not None})
    for name, poly in (("The house", hp), ("The carport", cp)):
        if not poly:
            continue
        for p in poly:
            if not inside(p, stand):
                w.append("%s is outside the stand." % name)
                break
        else:
            for i, k in enumerate(kinds):
                a, b = stand[i], stand[(i + 1) % len(stand)]
                dmin = min(line_dist(p, a, b) for p in poly)
                if dmin < sb[k] - 0.01:
                    w.append("%s is %.2f m from the %s boundary; the building line is %.2f m." % (name, dmin, k, sb[k]))
    if cp and any(seg_overlap(hp, cp)):
        w.append("The house and the carport overlap.")
    s = res["sewer"]
    if s["depth_main"] > params["conn_depth"] + 1e-6:
        w.append("Sewer: from the minimum depth of %.0f mm at the house, a %.1f m run at 1:%d is %.0f mm deep at the main, but the main is only %.0f mm deep there. "
                 "Lay it flatter, or the main must be deeper." % (params["min_depth"] * 1000, s["length"], params["fall"], s["depth_main"] * 1000, params["conn_depth"] * 1000))
    gap = parallel_gap(res["sewer"]["path"], res["water"]["path"])
    if gap is not None and gap < params["sep_water"] - 1e-6:
        w.append("Water and sewer run side by side only %.0f mm apart; a drain and a potable water pipe laid side by side must be at least %.0f mm apart "
                 "(SANS 10252-2, 6.7.6.1)." % (gap * 1000, params["sep_water"] * 1000))
    gap = parallel_gap(res["sewer"]["path"], res["elec"]["path"])
    if gap is not None and gap < params["sep_service"] - 1e-6:
        w.append("The electrical line runs %.0f mm from the sewer; no service may be within %.0f mm of a drain (SANS 10252-2, 6.7.6.2)." % (gap * 1000, params["sep_service"] * 1000))
    if params["min_depth"] < params["min_cover"] - 1e-6:
        w.append("The minimum invert depth is less than the %.0f mm soil cover the standard asks for (SANS 10252-2, 6.7.6.8)." % (params["min_cover"] * 1000))
    lines = [("sewer", res["sewer"]["path"]), ("water", res["water"]["path"]), ("electrical", res["elec"]["path"])]
    for i in range(3):
        for j in range(i + 1, 3):
            if overlap_len(lines[i][1], lines[j][1]) > 0.5:
                w.append("The %s and %s lines run on top of each other. Move one of the house connections." % (lines[i][0], lines[j][0]))
    # the fall of the drain (SANS 10252-2, table 13: 100 / 110 mm drains, 1 in 60 is the flattest without special permission, 1 in 120 the flattest at all; clause 6.7.6.6: anchor blocks steeper than 1 in 10)
    fl = params["fall"]
    if fl > params["fall_special"] + 1e-6:
        w.append("The sewer fall of 1:%g is flatter than 1:%g, which SANS 10252-2 (table 13) does not allow for a 110 mm drain." % (fl, params["fall_special"]))
    elif fl > params["fall_flat"] + 1e-6:
        w.append("The sewer fall of 1:%g is flatter than 1:%g: the municipality must give special permission (SANS 10252-2, table 13)." % (fl, params["fall_flat"]))
    elif fl < params["anchor_fall"] - 1e-6:
        w.append("The sewer fall of 1:%g is steeper than 1:%g: anchor blocks are needed (SANS 10252-2, 6.7.6.6)." % (fl, params["anchor_fall"]))
    # a service line that leaves the stand anywhere but at the street runs over the neighbour's stand
    res["flags"] = []
    st0, st1 = stand[0], stand[1 % len(stand)]
    cen_ = (sum(q[0] for q in stand) / len(stand), sum(q[1] for q in stand) / len(stand))
    side_ = lambda q: (st1[0] - st0[0]) * (q[1] - st0[1]) - (st1[1] - st0[1]) * (q[0] - st0[0])

    def street_side(q):                                              # on the far side of the street boundary from the stand: the road reserve, where the mains are
        return side_(q) * side_(cen_) < 0
    for name, key in (("sewer", "sewer"), ("water", "water"), ("electrical", "elec")):
        path = res[key]["path"]
        hit = None
        for a, b in zip(path[:-1], path[1:]):
            n_ = max(int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25), 1)
            for t in range(n_ + 1):
                q = (a[0] + (b[0] - a[0]) * t / n_, a[1] + (b[1] - a[1]) * t / n_)
                if not inside(q, stand) and poly_dist(q, stand) > 0.3 and not street_side(q):
                    hit = q
                    break
            if hit:
                break
        if hit and not (state.get("main_line") and key == "sewer"):
            w.append("The %s line runs over a neighbouring stand (at the red mark). Keep service lines inside your own stand." % name)
            res["flags"].append({"pt": [round(hit[0], 2), round(hit[1], 2)], "text": "%s line leaves the stand" % name})
    return w


# ------------------------------------------------------------------ zoning compliance (limits the user enters from the zoning scheme)
ZONING_DEFAULTS = {"coverage": 0.0, "far": 0.0, "height": 0.0, "storeys": 1, "house_height": 0.0, "bays_req": 0, "bays": 0, "gfa": 0.0}


def compliance(state, res):
    """pass / fail rows for the building lines, coverage, floor area ratio, height and parking. The limits come from the municipality's zoning scheme and are
    typed in by the user (0 = no limit entered, shown as 'no limit set'). -> [{"key", "label", "value", "limit", "ok" (True / False / None), "text"}]"""
    z = dict(ZONING_DEFAULTS)
    z.update((state["stand"].get("zoning") or {}))
    stand = [tuple(p) for p in state["stand"]["corners"]]
    sa = max(abs(area(stand)), 1e-6)
    hp, cp = res["house"], res.get("carport")
    kinds = edge_kinds(stand)
    sb = {"street": DEFAULTS["sb_street"], "side": DEFAULTS["sb_side"], "rear": DEFAULTS["sb_rear"]}
    sb.update({k: v for k, v in ((state["stand"].get("setbacks") or {}).items()) if v is not None})
    rows = []
    for kind, lab in (("street", "Street building line"), ("side", "Side building line"), ("rear", "Rear building line")):
        ds = []
        for poly in (hp, cp):
            if not poly:
                continue
            for i, k in enumerate(kinds):
                if k == kind:
                    a, b = stand[i], stand[(i + 1) % len(stand)]
                    ds.append(min(line_dist(q, a, b) for q in poly))
        if not ds:
            continue
        d = min(ds)
        rows.append({"key": "bl_" + kind, "label": lab, "value": "%.2f m" % d, "limit": "at least %.2f m" % sb[kind], "ok": d >= sb[kind] - 0.01,
                     "text": "%.2f m from the %s boundary (building line %.2f m)" % (d, kind, sb[kind])})
    out_ = any(not inside(q, stand) for poly in (hp, cp) if poly for q in poly)
    rows.append({"key": "inside", "label": "Inside the stand", "value": "no" if out_ else "yes", "limit": "", "ok": not out_, "text": "the house or carport sticks out of the stand" if out_ else "all corners inside"})
    foot = abs(area(hp)) + (abs(area(cp)) if cp else 0)
    cov = foot / sa * 100
    lim = z["coverage"]
    rows.append({"key": "coverage", "label": "Coverage", "value": "%.1f %%" % cov, "limit": ("at most %.1f %%" % lim) if lim else "no limit set",
                 "ok": (cov <= lim + 1e-9) if lim else None,
                 "text": "%.1f m2 built on %.0f m2%s" % (foot, sa, (" - %.1f m2 over" % (foot - lim * sa / 100)) if lim and cov > lim else "")})
    gfa = z["gfa"] or abs(area(hp)) * max(int(z["storeys"] or 1), 1) + (abs(area(cp)) if (cp and z.get("carport_in_far")) else 0)
    far = gfa / sa
    lim = z["far"]
    rows.append({"key": "far", "label": "Floor area ratio", "value": "%.2f" % far, "limit": ("at most %.2f" % lim) if lim else "no limit set",
                 "ok": (far <= lim + 1e-9) if lim else None,
                 "text": "%.1f m2 floor area on %.0f m2%s" % (gfa, sa, (" - %.1f m2 over" % (gfa - lim * sa)) if lim and far > lim else "")})
    lim, hh = z["height"], z["house_height"]
    rows.append({"key": "height", "label": "Height", "value": ("%.2f m" % hh) if hh else "not entered", "limit": ("at most %.2f m" % lim) if lim else "no limit set",
                 "ok": ((hh <= lim + 1e-9) if (lim and hh) else None),
                 "text": "type the building height above natural ground to check it" if (lim and not hh) else ""})
    req, have = int(z["bays_req"] or 0), int(z["bays"] or 0)
    rows.append({"key": "parking", "label": "Parking bays", "value": "%d" % have, "limit": ("at least %d" % req) if req else "no limit set",
                 "ok": (have >= req) if req else None, "text": ("%d bay%s short" % (req - have, "" if req - have == 1 else "s")) if req and have < req else ""})
    return rows


def seg_overlap(a, b):
    """True if two convex polygons overlap (separating axis)"""
    for poly in (a, b):
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            ax, ay = -(q[1] - p[1]), q[0] - p[0]
            pa = [x * ax + y * ay for x, y in a]
            pb = [x * ax + y * ay for x, y in b]
            if max(pa) <= min(pb) + 1e-9 or max(pb) <= min(pa) + 1e-9:
                return [False]
    return [True]


def solve(state):
    params = dict(DEFAULTS)
    params.update(state.get("params") or {})
    hp = house_poly(state["house"])
    cp = carport_poly(state.get("carport"))
    sw = sewer(state, hp, cp, params)
    wt = water(state, hp, cp, params, [sw["path"]])
    el = electrical(state, hp, cp, params, [sw["path"], wt["path"]])
    res = {"sewer": sw, "water": wt, "elec": el}
    res["house"] = hp
    res["marks"] = mark_points(state["house"])
    res["carport"] = cp
    res["warnings"] = checks(state, hp, cp, params, res)
    stand = state["stand"]["corners"]
    try:
        import site_plans_data
        res["reference"] = site_plans_data.notes_for(state, abs(area(stand)))
    except Exception:
        res["reference"] = []
    cov = (abs(area(hp)) + (abs(area(cp)) if cp else 0)) / max(abs(area(stand)), 1e-6) * 100
    res["coverage_pct"] = round(cov, 1)
    res["stand_area"] = round(abs(area(stand)), 1)
    res["params"] = params
    res["compliance"] = compliance(state, res)
    return res


# ------------------------------------------------------------------ frames (moving an imported drawing into the stand frame)
def normalise_stand(c, i):
    """corners c with edge i as the street. Returns (frame, new corners): the street edge runs from the origin along +x, the stand lies at +y.
    A frame is [a, b, tx, ty, ...]: point -> (a*x - b*y + tx, b*x + a*y + ty), and frame[6] is the turn in degrees."""
    n = len(c)
    pts = [tuple(p) for p in c]
    if area(pts) < 0:
        pts = pts[::-1]
        i = (n - 2 - i) % n
    pts = pts[i:] + pts[:i]
    a0, b0 = pts[0], pts[1]
    ang = -math.atan2(b0[1] - a0[1], b0[0] - a0[0])
    ca, sa = math.cos(ang), math.sin(ang)
    frame = [ca, sa, -(ca * a0[0] - sa * a0[1]), -(sa * a0[0] + ca * a0[1]), 0, 0, math.degrees(ang)]
    return frame, [apply_frame(frame, p) for p in pts]


def apply_frame(f, p):
    return (f[0] * p[0] - f[1] * p[1] + f[2], f[1] * p[0] + f[0] * p[1] + f[3])


def compose_frames(f1, f2):
    """first f1 then f2"""
    if not f1:
        return f2
    ang = math.radians(f1[6] + f2[6])
    ca, sa = math.cos(ang), math.sin(ang)
    o = apply_frame(f2, (f1[2], f1[3]))
    return [ca, sa, o[0], o[1], 0, 0, math.degrees(ang)]


# ------------------------------------------------------------------ starting points
def clean_corners(c, min_edge=1.0):
    """drop corners that make a sliver (an edge shorter than min_edge), so the street/side/rear edges stay meaningful"""
    c = [tuple(p) for p in c]
    changed = True
    while changed and len(c) > 3:
        changed = False
        for i in range(len(c)):
            if math.hypot(c[i][0] - c[(i + 1) % len(c)][0], c[i][1] - c[(i + 1) % len(c)][1]) < min_edge:
                j = (i + 1) % len(c)
                c.pop(i if j == 0 else j)                 # corner 0 starts the street boundary, so it stays
                changed = True
                break
    return c


def orient_street_first(c, street_a=None, street_b=None):
    """order the corners so that edge 0 is the street boundary and the stand lies at y > 0 side. With no hint the lowest edge is the street."""
    c = [tuple(p) for p in c]
    if street_a is None:
        best = None
        for i in range(len(c)):
            a, b = c[i], c[(i + 1) % len(c)]
            m = (a[1] + b[1]) / 2
            if best is None or m < best[0]:
                best = (m, i)
        i = best[1]
    else:
        i = min(range(len(c)), key=lambda k: math.hypot(c[k][0] - street_a[0], c[k][1] - street_a[1]))
    c = c[i:] + c[:i]
    if area(c) < 0:
        c = [c[0]] + c[1:][::-1]
        c = c[1:] + c[:1] if False else c
    return c


def fits(poly, stand, sb):
    if any(not inside(p, stand) for p in poly):
        return False
    kinds = edge_kinds(stand)
    for i, k in enumerate(kinds):
        a, b = stand[i], stand[(i + 1) % len(stand)]
        if min(line_dist(p, a, b) for p in poly) < sb[k] - 1e-6:
            return False
    return True


def north_screen_to_world(deg, road, turn=0.0):
    """the direction north points, in the stand's own frame (x along the street, y into the stand), from the arrow's turn (degrees clockwise from up on the
    page) and the side of the plan the road is on"""
    rot = {"top": 0, "right": 90, "bottom": 180, "left": 270}.get(road, 270)
    deg = deg - (turn or 0.0)                                    # (the whole plan may be turned on the page by `turn` degrees clockwise)
    sx, sy = math.sin(math.radians(deg)), -math.cos(math.radians(deg))
    if rot == 0:
        return (sx, sy)
    if rot == 90:
        return (sy, -sx)
    if rot == 180:
        return (-sx, -sy)
    return (-sy, sx)


def north_world_to_screen(v, road, turn=0.0):
    """the arrow's turn (degrees clockwise from up) for a north direction in the stand's frame"""
    rot = {"top": 0, "right": 90, "bottom": 180, "left": 270}.get(road, 270)
    x, y = v
    if rot == 0:
        sx, sy = x, y
    elif rot == 90:
        sx, sy = -y, x
    elif rot == 180:
        sx, sy = -x, -y
    else:
        sx, sy = y, -x
    return math.degrees(math.atan2(sx, -sy)) + (turn or 0.0)


def suggest(state, relax=False, gap=None):
    """house and carport placement: tries the clear distance between carport and house that your finished plans keep, then smaller ones, and takes the
    first that also puts the house the usual way round (long side down the stand); otherwise the best of what fits"""
    if gap is not None:
        return _suggest(state, relax, gap)
    try:
        import site_plans_data
        pref = site_plans_data.preferred_gap(state)
    except Exception:
        pref = 1.0
    outs = []
    for g in sorted({pref, 1.0, 0.25}, reverse=True):
        o = _suggest(state, relax, g, strict=True)
        if o:
            outs.append(o)
            if o["house"].get("poly") or o["house"].get("rot", 0) == 90:
                return o
    if outs:
        return outs[0]
    for g in sorted({pref, 1.0, 0.25}, reverse=True):          # nothing fits square to the street: turn the house to run along the stand's own sides
        o = _suggest(state, relax, g, strict=True, alt=True)
        if o:
            return o
    return _suggest(state, relax, 0.25)


def _side_angles(stand):
    """the directions (degrees, 0..180, in the stand's frame) of its longer sides, and the ones across them"""
    n = len(stand)
    out = []
    for i in range(n):
        a, b = stand[i], stand[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 5.0:
            continue
        d = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
        for q in (d, (d + 90.0) % 180.0):
            if all(abs(((q - o + 90) % 180) - 90) > 1.0 for o in out) and abs(((q - 0 + 90) % 180) - 90) > 1.0 and abs(((q - 90 + 90) % 180) - 90) > 1.0:
                out.append(round(q, 2))
    return out


def _suggest(state, relax=False, gap=1.0, strict=False, alt=False):
    """house and carport on the stand: the carport at the street on one side, the house at the back on the other side, everything inside the
    building lines. Searches positions on a 0.25 m grid and takes the first that fits. The house keeps `gap` clear of the carport (1.0 m, as on the
    finished plans; tighter only when it cannot fit)."""
    params = dict(DEFAULTS)
    params.update(state.get("params") or {})
    stand = state["stand"]["corners"]
    sb = {"street": params["sb_street"], "side": params["sb_side"], "rear": params["sb_rear"]}
    sb.update({k: v for k, v in (state["stand"].get("setbacks") or {}).items() if v is not None})
    if relax:
        sb = {"street": 0.0, "side": 0.0, "rear": 0.0}
    h = state["house"]
    c = state.get("carport")
    xs = [p[0] for p in stand]
    ys = [p[1] for p in stand]
    step = max(0.25, round(max(max(xs) - min(xs), max(ys) - min(ys)) / 160.0, 2))   # a huge stand must not mean a million trial positions
    target = state["points"]["sewer"]
    xr = [min(xs) + i * step for i in range(int((max(xs) - min(xs)) / step) + 1)]
    yr = [min(ys) + i * step for i in range(int((max(ys) - min(ys)) / step) + 1)]
    best = None
    for left in (True, False):
        # carport: against the street, tight to one side
        cpos = None
        if c:
            order = xr if left else xr[::-1]
            for y in yr:
                for x in order:
                    poly = shape_poly(dict(c, cx=x, cy=y, rot=c.get("rot", 0)))
                    if fits(poly, stand, sb):
                        cpos = (x, y)
                        break
                if cpos:
                    break
            if not cpos:
                continue
        for rot in ((h.get("rot", 0),) if h.get("poly") else ((90, 0) if not alt else tuple(_side_angles(stand)))):
            hposs = None
            for y in yr[::-1]:
                for x in (xr[::-1] if left else xr):
                    hp = shape_poly(dict(h, cx=x, cy=y, rot=rot))
                    if not fits(hp, stand, sb):
                        continue
                    if c and seg_overlap(hp, [(px, py) for px, py in rect(cpos[0], cpos[1], c["w"] + 2 * gap, c["d"] + 2 * gap, c.get("rot", 0))])[0]:
                        continue
                    hposs = (x, y)
                    break
                if hposs:
                    break
            if not hposs:
                continue
            score = (0 if rot == 90 else 3 if rot == 0 else 5) + math.hypot(hposs[0] - target[0], hposs[1] - target[1]) * 0.05 + (0 if left else 0.01)
            nv = state.get("north_world")
            if nv and not h.get("poly"):                          # the sun: the long wall faces north, and the house sits to the south so the yard is on the north side
                ln = math.hypot(nv[0], nv[1]) or 1.0
                nx, ny = nv[0] / ln, nv[1] / ln
                ax, ay = (0.0, 1.0) if rot == 90 else (1.0, 0.0)          # the long axis of the house
                facing = abs(ax * ny - ay * nx)                           # 1 = the long wall faces north (or south), 0 = it faces east or west
                score += (1.0 - facing) * 4.0
                cxs, cys = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
                score += max(0.0, (hposs[0] - cxs) * nx + (hposs[1] - cys) * ny) / span * 2.0
            cand = {"house": dict(h, cx=round(hposs[0], 2), cy=round(hposs[1], 2), rot=rot)}
            if c:
                cand["carport"] = dict(c, cx=round(cpos[0], 2), cy=round(cpos[1], 2), rot=c.get("rot", 0) if c.get("poly") else 0)
            if best is None or score < best[0]:
                best = (score, cand)
    if best is None:
        if strict:
            return None
        if not relax:
            out = _suggest(state, relax=True, gap=gap)
            out["relaxed"] = True                              # the building lines could not all be met: the warnings will say where
            return out
        cx, cy = (min(xs) + max(xs)) / 2, min(ys) + (max(ys) - min(ys)) * 0.65
        return {"house": dict(h, cx=round(cx, 2), cy=round(cy, 2)), "carport": dict(c, cx=round(cx, 2), cy=round(min(ys) + c["d"] / 2 + 1, 2)) if c else None}
    best[1].setdefault("carport", None)
    return best[1]


def default_points(d):
    """sewer, water and electrical points for a bundled stand: where the survey's connection line meets the street boundary,
    the nearest short water stub, and the middle of the frontage for the electrical point (not in the SG sheets: place your own)"""
    fr = d["frontage"]
    hx, hy = d["hc"]
    sew = [round(min(max(hx, 1.0), fr - 1.0), 2), 0.0]
    wat = None
    for s in d["layers"].get("water", []):
        x1, y1, x2, y2, thick = s
        if abs(x2 - x1) + abs(y2 - y1) > 4.0:
            continue
        for (x, y) in ((x1, y1), (x2, y2)):
            if -2.5 <= y <= 1.0 and 0.5 <= x <= fr - 0.5 and abs(x - sew[0]) > 3:
                if wat is None or abs(y) < abs(wat[1]):
                    wat = [round(x, 2), 0.0]
    return {"sewer": sew, "water": wat or [round(min(1.5, fr / 2), 2), 0.0], "elec": [round(fr / 2, 2), 0.0]}


def ref_angles(stand, min_len=3.0):
    """the directions a drawn main may follow: along each boundary of the stand (and square to it), and 45 degrees either side of those.
    Returns a list of (angle in radians 0..pi, label)"""
    out = []
    n = len(stand)
    for i in range(n):
        a, b = stand[i], stand[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < min_len:
            continue
        base = math.atan2(b[1] - a[1], b[0] - a[0])
        for k, lab in ((0, "parallel to the boundary"), (2, "square to the boundary"), (1, "45 deg to the boundary"), (3, "45 deg to the boundary")):
            ang = (base + k * math.pi / 4) % math.pi
            out.append((ang, lab))
    if not out:
        out = [(0.0, "level"), (math.pi / 2, "upright"), (math.pi / 4, "45 deg"), (3 * math.pi / 4, "45 deg")]
    return out


def snap_dir(stand, prev, w, mode="45"):
    """a drawn main's next point: 'par' snaps only to directions parallel / square to the stand's boundaries (when within 12 degrees),
    '45' always takes the nearest boundary-parallel, square or 45 degree direction, 'free' leaves the point alone.
    Returns (point, label, angle_deg, length)"""
    dx, dy = w[0] - prev[0], w[1] - prev[1]
    L = math.hypot(dx, dy)
    if mode == "free" or L < 1e-6:
        return (w[0], w[1]), "free", math.degrees(math.atan2(dy, dx)) % 180, L
    ang = math.atan2(dy, dx)
    best, bl, bd = None, "free", 1e9
    for a, lab in ref_angles(stand):
        if mode == "par" and lab.startswith("45"):
            continue
        d = abs(((ang - a + math.pi / 2) % math.pi) - math.pi / 2)
        if d < bd:
            best, bl, bd = a, lab, d
    if best is None or (mode == "par" and bd > math.radians(12)):
        return (w[0], w[1]), "free", math.degrees(ang) % 180, L
    u = (math.cos(best), math.sin(best))
    t = dx * u[0] + dy * u[1]
    return (prev[0] + u[0] * t, prev[1] + u[1] * t), bl, math.degrees(best), abs(t)
