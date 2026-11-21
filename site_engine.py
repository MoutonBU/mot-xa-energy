"""Site services engine: the house and carport on a stand, three service points (sewer, water, electrical) and the house's own
connection points (sewer outlet, water entry, DB). It routes each pipe or cable round the buildings, puts rodding eyes and
inspection eyes where they belong, works out the invert levels from the fall, and checks the result. No Qt in here.

Frame: metres. x along the street boundary, y into the stand. The street boundary is the first edge of the stand (corner 0 to corner 1).
Everything is recomputed from the state, so moving anything gives a new, consistent plan."""
import heapq
import math

GRID = 0.25
DEFAULTS = {"fall": 50.0, "conn_depth": 1.5, "max_ie": 25.0, "min_depth": 0.45, "sewer_pipe": "110", "water_pipe": "20",
            "clear": 0.3, "re_ext": 1.5, "sb_street": 1.0, "sb_side": 1.0, "sb_rear": 2.0}


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


def conn_point(state, k):
    """the connection point on the main line: x as placed, y on the main line"""
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
    xs = [p[0] for p in stand] + [a[0], b[0]]
    ys = [p[1] for p in stand] + [a[1], b[1]]
    x0, y0 = min(xs) - pad, min(ys) - pad
    nx = int((max(xs) + pad - x0) / GRID) + 1
    ny = int((max(ys) + pad - y0) / GRID) + 1
    cell = {}
    street = (stand[0], stand[1])

    def cost(i, j):
        k = (i, j)
        if k in cell:
            return cell[k]
        p = (x0 + i * GRID, y0 + j * GRID)
        c = 1.0
        for poly in blocked:
            if inside(p, poly):
                c = None
                break
        if c is not None and not inside(p, stand):
            c = 1.4 if seg_dist(p, *street) < street_band else 8.0
        cell[k] = c
        return c

    s = (int(round((a[0] - x0) / GRID)), int(round((a[1] - y0) / GRID)))
    g = (int(round((b[0] - x0) / GRID)), int(round((b[1] - y0) / GRID)))
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
            nd = d + (c or 1.0) * GRID + (bend if dr not in (-1, k) else 0.0)
            if nd < best.get((nxt, k), 1e18) - 1e-9:
                best[(nxt, k)] = nd
                prev[(nxt, k)] = (cur, dr)
                heapq.heappush(pq, (nd + (abs(nxt[0] - g[0]) + abs(nxt[1] - g[1])) * GRID, nd, nxt, k))
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
    pts = [(x0 + i * GRID, y0 + j * GRID) for i, j in cells]
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
def _obstacles(hp, cp, params):
    return [offset(hull(hp), params["clear"])] + ([offset(hull(cp), params["clear"])] if cp else [])


def _port_for(state, hp, key, target, t0, others, build):
    """house port: the user's, or the side that faces the target; the automatic one is nudged along the wall until the line does not run on top of another"""
    user = (state.get("ports") or {}).get(key)
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


def sewer(state, hp, cp, params, others=()):
    stand = state["stand"]["corners"]
    obs = _obstacles(hp, cp, params)
    cands = candidates(state, "sewer")

    def build(port):
        p0, n0 = port_point(hp, port)
        ext = params["re_ext"]
        q1 = (p0[0] + n0[0] * ext, p0[1] + n0[1] * ext)
        rest = best_line(q1, cands, obs)
        path = dedupe([p0, q1] + rest[1:])
        return {"path": path, "port": port, "q1": q1}
    port, r = _port_for(state, hp, "sewer", cands[0], 0.25, others, build)
    path = r["path"]
    L = length(path)
    fall = params["fall"]
    cut = crossing(path, stand)
    ext = min(params["re_ext"], L)
    marks = [(0.0, "RE"), (ext, "IE")]                       # rodding eye at the wall, inspection eye a little way out
    acc = 0.0
    for i in range(1, len(path) - 1):
        acc += math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        if all(abs(acc - m[0]) > 0.3 for m in marks):
            marks.append((acc, "IE"))                        # and one at every bend
    if cut is not None and all(abs(cut - m[0]) > 0.6 for m in marks):
        marks.append((max(cut - 0.6, 0.3), "IE"))           # just inside the boundary, as on your plans
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
                      "label": kind + (" Min IL %d" % round(D0 * 1000) if kind == "RE" and s_ == 0 else "")})
    d_main = D0 + L / fall
    nodes.append({"kind": "MAIN", "pt": path[-1], "chainage": round(L, 2), "depth": round(d_main, 3), "label": "Connect to main sewer line"})
    return {"path": path, "nodes": nodes, "length": round(L, 2), "drop_mm": round(L * 1000.0 / fall), "port": port,
            "depth_house": round(D0, 3), "depth_main": round(d_main, 3), "note": "%s\u00d8 SWP, FALL 1:%d" % (params["sewer_pipe"], round(fall))}


def water(state, hp, cp, params, others=()):
    stand = state["stand"]["corners"]
    obs = _obstacles(hp, cp, params)
    cands = candidates(state, "water")

    def build(port):
        p0, n0 = port_point(hp, port)
        start = (p0[0] + n0[0] * 0.5, p0[1] + n0[1] * 0.5)
        best = best_line(start, cands, obs)[::-1]
        return {"path": dedupe(best + [p0]), "port": port}
    port, r = _port_for(state, hp, "water", cands[0], 0.7, others, build)
    path = r["path"]
    L = length(path)
    cut = crossing(path, stand)
    nodes = [{"kind": "WCON", "pt": point_at(path, cut) if cut is not None else path[0], "chainage": round(cut or 0.0, 2), "label": "W.CON"}]
    if cut is not None:
        nodes.append({"kind": "WM", "pt": point_at(path, cut + 0.6), "chainage": round(cut + 0.6, 2), "label": "Water meter"})
    nodes.append({"kind": "SC", "pt": point_at(path, max(L - 0.6, 0)), "chainage": round(max(L - 0.6, 0), 2), "label": "Stop cock"})
    return {"path": path, "nodes": nodes, "length": round(L, 2), "port": port, "note": "%smm Cold Water Line" % params["water_pipe"]}


def electrical(state, hp, cp, params, others=()):
    obs = _obstacles(hp, cp, params)
    cands = candidates(state, "elec")

    def build(port):
        p0, n0 = port_point(hp, port)
        start = (p0[0] + n0[0] * 0.3, p0[1] + n0[1] * 0.3)
        best = best_line(start, cands, obs)[::-1]
        return {"path": dedupe(best + [p0]), "port": port}
    port, r = _port_for(state, hp, "db", cands[0], 0.8, others, build)
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
    lines = [("sewer", res["sewer"]["path"]), ("water", res["water"]["path"]), ("electrical", res["elec"]["path"])]
    for i in range(3):
        for j in range(i + 1, 3):
            if overlap_len(lines[i][1], lines[j][1]) > 0.5:
                w.append("The %s and %s lines run on top of each other. Move one of the house connections." % (lines[i][0], lines[j][0]))
    return w


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
    res["carport"] = cp
    res["warnings"] = checks(state, hp, cp, params, res)
    stand = state["stand"]["corners"]
    cov = (abs(area(hp)) + (abs(area(cp)) if cp else 0)) / max(abs(area(stand)), 1e-6) * 100
    res["coverage_pct"] = round(cov, 1)
    res["stand_area"] = round(abs(area(stand)), 1)
    res["params"] = params
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


def suggest(state, relax=False):
    """house and carport on the stand: the carport at the street on one side, the house at the back on the other side, everything inside the
    building lines. Searches positions on a 0.25 m grid and takes the first that fits."""
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
    step = 0.25
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
        for rot in ((h.get("rot", 0),) if h.get("poly") else (90, 0)):
            hposs = None
            for y in yr[::-1]:
                for x in (xr[::-1] if left else xr):
                    hp = shape_poly(dict(h, cx=x, cy=y, rot=rot))
                    if not fits(hp, stand, sb):
                        continue
                    if c and seg_overlap(hp, [(px, py) for px, py in rect(cpos[0], cpos[1], c["w"] + 0.5, c["d"] + 0.5, c.get("rot", 0))])[0]:
                        continue
                    hposs = (x, y)
                    break
                if hposs:
                    break
            if not hposs:
                continue
            score = (0 if rot == 90 else 3) + math.hypot(hposs[0] - target[0], hposs[1] - target[1]) * 0.05 + (0 if left else 0.01)
            cand = {"house": dict(h, cx=round(hposs[0], 2), cy=round(hposs[1], 2), rot=rot)}
            if c:
                cand["carport"] = dict(c, cx=round(cpos[0], 2), cy=round(cpos[1], 2), rot=c.get("rot", 0) if c.get("poly") else 0)
            if best is None or score < best[0]:
                best = (score, cand)
    if best is None:
        if not relax:
            out = suggest(state, relax=True)
            out["relaxed"] = True                              # the building lines could not all be met: the warnings will say where
            return out
        return {"house": dict(h), "carport": dict(c) if c else None}
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
