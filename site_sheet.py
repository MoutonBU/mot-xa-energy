"""The site plan drawn the way the MOT plans look: road on one side with its name and the mains, the stand with long-dash building lines, the entry,
the carport (crossed, in two label boxes), the red house with its white NEW HOUSE box, the services in brown (sewer, long dash), blue (water) and
yellow (electrical), IE / RE as spaced letters, dimensions in mm with oblique ticks, bold stand numbers and the compass.
Everything is placed in metres and drawn at the scale of `s` pixels per metre, so the same code makes the screen plan and the 1:200 sheet."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF

import site_engine as se

BROWN = QColor(173, 71, 10)
BLUE = QColor(15, 130, 255)
YELLOW = QColor(219, 209, 20)
RED = QColor(255, 0, 0)
CARPORT = QColor(255, 128, 128)
ENTRY = QColor(255, 235, 214)
GREY = QColor(120, 120, 120)
BLACK = QColor(0, 0, 0)
ROTS = {"top": 0, "right": 90, "bottom": 180, "left": 270}          # which side of the plan the road is on


def mm(v):
    return "{:,}".format(int(round(v * 1000)))


class Sheet:
    """world (x along the street, y into the stand, metres) -> paper, with the road on the chosen side"""

    def __init__(self, s, centre, size, road="left"):
        self.s = s
        self.cx, self.cy = centre
        self.W, self.H = size
        self.road = road
        self.rot = ROTS.get(road, 270)

    def pt(self, q):
        x, y = q[0] - self.cx, q[1] - self.cy
        r = self.rot
        if r == 0:
            sx, sy = x, y
        elif r == 90:
            sx, sy = -y, x
        elif r == 180:
            sx, sy = -x, -y
        else:
            sx, sy = y, -x
        return QPointF(self.W / 2 + sx * self.s, self.H / 2 + sy * self.s)

    def inv(self, pt):
        sx, sy = (pt.x() - self.W / 2) / self.s, (pt.y() - self.H / 2) / self.s
        r = self.rot
        if r == 0:
            x, y = sx, sy
        elif r == 90:
            x, y = sy, -sx
        elif r == 180:
            x, y = -sx, -sy
        else:
            x, y = -sy, sx
        return (x + self.cx, y + self.cy)

    def hdir(self):
        """the world direction that runs left-right on the paper (for labels that must read across the page)"""
        return (0, 1) if self.rot in (90, 270) else (1, 0)

    def angle(self, d):
        """screen angle in degrees of a world direction, turned so text is never upside down"""
        a = self.pt((self.cx + d[0], self.cy + d[1]))
        o = self.pt((self.cx, self.cy))
        ang = math.degrees(math.atan2(a.y() - o.y(), a.x() - o.x()))
        if ang > 90.01:
            ang -= 180
        elif ang <= -90.01:
            ang += 180
        return ang


def font(px, bold=False, spacing=100, family="Arial"):
    f = QFont(family)
    f.setPixelSize(max(int(px), 5))
    f.setBold(bold)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return f


class Drawer:
    def __init__(self, p, sh, minpx=7, lite=False):
        self.p, self.sh, self.s, self.minpx, self.lite = p, sh, sh.s, minpx, lite

    # ---- helpers
    def lw(self, m):                                    # a line weight in metres of paper-at-1:200 -> pixels
        return max(0.8, m * self.s)

    def text(self, q, txt, h=0.5, d=(1, 0), bold=False, color=BLACK, spacing=100, box=None, align="c", family="Arial", rot=None, bg=False):
        """text with its centre at world point q, running along world direction d. h = capital height in metres."""
        if self.lite:
            return
        p = self.p
        px = max(h * self.s * 1.4, self.minpx)
        p.save()
        p.setFont(font(px, bold, spacing, family))
        pt = self.sh.pt(q)
        p.translate(pt)
        p.rotate(self.sh.angle(d) if rot is None else rot)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(txt)
        ht = fm.ascent()
        x0 = -w / 2 if align == "c" else (0 if align == "l" else -w)
        if box or bg:
            pad = px * 0.28
            r = QRectF(x0 - pad, -ht / 2 - pad * 0.9, w + 2 * pad, ht + pad * 1.8)
            p.setBrush(QBrush(QColor("white")))
            p.setPen(QPen(BLACK, self.lw(0.04)) if box else Qt.PenStyle.NoPen)
            p.drawRect(r)
        p.setPen(color)
        p.drawText(QPointF(x0, ht / 2 - px * 0.05), txt)
        p.restore()

    def line(self, a, b, color=BLACK, w=0.05, dash=None, cap=False):
        pen = QPen(color, self.lw(w))
        if dash:
            pen.setDashPattern(dash)
        if not cap:
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.p.setPen(pen)
        self.p.drawLine(self.sh.pt(a), self.sh.pt(b))

    def poly(self, pts, color=BLACK, w=0.05, fill=None, dash=None, closed=True):
        pen = QPen(color, self.lw(w)) if color else Qt.PenStyle.NoPen
        if dash and color:
            pen.setDashPattern(dash)
        self.p.setPen(pen)
        self.p.setBrush(QBrush(fill) if fill else Qt.BrushStyle.NoBrush)
        qp = QPolygonF([self.sh.pt(q) for q in pts])
        if closed:
            self.p.drawPolygon(qp)
        else:
            self.p.drawPolyline(qp)

    def dim(self, a, b, off, txt, h=0.45, side=1):
        """dimension line between world points a and b, drawn `off` metres to one side, with oblique ticks and the figure"""
        if self.lite:
            return
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            return
        ux, uy = dx / L, dy / L
        nx, ny = -uy * side, ux * side
        a2 = (a[0] + nx * off, a[1] + ny * off)
        b2 = (b[0] + nx * off, b[1] + ny * off)
        ext = 0.3 * (1 if off >= 0 else -1)
        for q, q2 in ((a, a2), (b, b2)):
            self.line(q, (q2[0] + nx * ext, q2[1] + ny * ext), BLACK, 0.025)
        self.line(a2, b2, BLACK, 0.03)
        for q in (a2, b2):                                    # oblique ticks
            t = 0.28
            self.line((q[0] - (ux + nx) * t * 0.7, q[1] - (uy + ny) * t * 0.7), (q[0] + (ux + nx) * t * 0.7, q[1] + (uy + ny) * t * 0.7), BLACK, 0.05)
        mid = ((a2[0] + b2[0]) / 2 + nx * 0.42, (a2[1] + b2[1]) / 2 + ny * 0.42)
        self.text(mid, txt, h, (ux, uy))


def edge_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def draw(p, sh, st, res, opts, minpx=7, under=None, show_under=False, lite=False):
    """the whole plan. st = engine state, res = engine result, opts = sheet details (names, north, scale text)"""
    D = Drawer(p, sh, minpx, lite)
    stand = st["stand"]["corners"]
    n = len(stand)
    F = edge_len(stand[0], stand[1])
    xs = [q[0] for q in stand]
    ys = [q[1] for q in stand]
    depth = max(ys)
    sb = {"street": 1.0, "side": 1.0, "rear": 2.0}
    sb.update({k: v for k, v in (st["stand"].get("setbacks") or {}).items() if v is not None})
    kinds = se.edge_kinds(stand)
    xmin, xmax = min(xs), max(xs)
    ROAD_K, ROAD_K2 = -3.4, -3.8                       # the two kerb lines
    xa, xb = xmin - 14, xmax + 14
    # ---- road: kerb lines, the mains, the street name
    D.line((xa, ROAD_K), (xb, ROAD_K), BLACK, 0.04)
    D.line((xa, ROAD_K2), (xb, ROAD_K2), BLACK, 0.04)
    mn = se.mains(st)
    D.line((xa, mn["water"]), (xb, mn["water"]), BLUE, 0.04)
    D.text((xmin - 6.0, mn["water"]), "Main Water Line", 0.5, (1, 0), spacing=110, align="r")
    D.line((xa, mn["sewer"]), (xb, mn["sewer"]), BROWN, 0.08, dash=[9, 5])
    D.text((xmax + 10.5, mn["sewer"]), "Main Sewer Line", 0.5, (1, 0), spacing=125, align="r")
    D.line((xa, mn["elec"]), (xmin - 7, mn["elec"]), YELLOW, 0.05, dash=[5, 4])
    D.text((xmin - 11.5, mn["elec"]), "Main Electrical Line", 0.5, (1, 0), spacing=125)
    street = opts.get("street", "")
    if street:
        D.text(((xmin + xmax) / 2 + 3.0, -6.4), street, 1.05, (1, 0))
        sub = "%s  %s" % (opts.get("road_w", ""), opts.get("street_erf", ""))
        D.text(((xmin + xmax) / 2 + 3.0, -8.0), sub.strip(), 1.05, (1, 0))
    # ---- entry block (kerb to the carport front)
    cp = res.get("carport") if res else None
    if cp:
        cxs = [q[0] for q in cp]
        cys = [q[1] for q in cp]
        D.poly([(min(cxs), ROAD_K), (max(cxs), ROAD_K), (max(cxs), min(cys)), (min(cxs), min(cys))], GREY, 0.03, ENTRY)
        D.text(((min(cxs) + max(cxs)) / 2, (ROAD_K + min(cys)) / 2 - 0.9), "Entry", 0.5, (1, 0), rot=None)
    # ---- the stand
    D.poly(stand, BLACK, 0.05)
    for i in range(n):                                 # side lines run on past the street boundary to the kerb, as on the plans
        if kinds[i] == "side":
            a, b = stand[i], stand[(i + 1) % n]
            street_end = a if abs(a[1]) < abs(b[1]) else b
            if abs(street_end[1]) < 0.6:
                D.line(street_end, (street_end[0], ROAD_K2), BLACK, 0.05)
    # building lines
    inset = []
    for i in range(n):
        a, b = stand[i], stand[(i + 1) % n]
        L = edge_len(a, b) or 1
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        if se.area(stand) < 0:
            nx, ny = -nx, -ny
        d = sb[kinds[i]]
        inset.append(((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d)))
    for i in range(n):
        (a1, a2), (b1, b2) = inset[i], inset[(i + 1) % n]
        den = (a1[0] - a2[0]) * (b1[1] - b2[1]) - (a1[1] - a2[1]) * (b1[0] - b2[0])
        if abs(den) > 1e-9:
            t = ((a1[0] - b1[0]) * (b1[1] - b2[1]) - (a1[1] - b1[1]) * (b1[0] - b2[0])) / den
            inset[i] = (inset[i][0], (a1[0] + t * (a2[0] - a1[0]), a1[1] + t * (a2[1] - a1[1])))
            inset[(i + 1) % n] = ((a1[0] + t * (a2[0] - a1[0]), a1[1] + t * (a2[1] - a1[1])), inset[(i + 1) % n][1])
    for i, (a, b) in enumerate(inset):
        D.line(a, b, BLACK, 0.04, dash=[22, 10])
        m = ((a[0] + b[0]) / 2 + (b[0] - a[0]) * 0.12, (a[1] + b[1]) / 2 + (b[1] - a[1]) * 0.12)
        d = (b[0] - a[0], b[1] - a[1])
        if edge_len(a, b) > 9:
            D.text(m, "%s B/L" % ("%gm" % sb[kinds[i]]), 0.5, d, spacing=120, bg=True)
    # stand figures: side lengths outside, frontage inside the boundary
    for i in range(n):
        a, b = stand[i], stand[(i + 1) % n]
        L = edge_len(a, b)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        dxn, dyn = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        out = (dyn, -dxn) if se.area(stand) > 0 else (-dyn, dxn)
        if kinds[i] == "street":
            D.text((mid[0] + out[0] * 0.55, mid[1] + out[1] * 0.55), "%.2f" % L, 0.5, (dxn, dyn), spacing=125)
        elif kinds[i] == "side":
            D.text((mid[0] + out[0] * 0.65, mid[1] + out[1] * 0.65), "%.2f" % L, 0.5, (dxn, dyn), spacing=125)
    # stand numbers (bold)
    num = opts.get("stand_no", "")
    nb = opts.get("neigh", [])
    cx_ = (xmin + xmax) / 2
    house = res.get("house") if res else None
    if num:
        free_y = depth * 0.5
        # in the part of the stand the house does not cover
        pos = (cx_, depth * 0.5)
        if house:
            best = None
            for fx in (xmin + F * 0.2, xmin + F * 0.5, xmin + F * 0.8):
                for fy in (depth * 0.3, depth * 0.5, depth * 0.7):
                    c = (fx, fy)
                    dd = min(se.poly_dist(c, house), se.poly_dist(c, cp) if cp else 99)
                    if se.inside(c, stand) and (best is None or dd > best[0]):
                        best = (dd, c)
            if best:
                pos = best[1]
        D.text(pos, str(num), 1.9, sh.hdir(), bold=True, family="Arial Black")
    for k, no in enumerate(nb[:2]):
        yy = depth * 0.45
        xx = xmin - F * 0.55 if k == 0 else xmax + F * 0.55
        D.text((xx, yy), str(no), 1.9, sh.hdir(), bold=True, family="Arial Black")
    # ---- carport
    if cp:
        D.poly(cp, BLACK, 0.04, CARPORT)
        D.line(cp[0], cp[2], BLACK, 0.025, dash=[4, 3])
        D.line(cp[1], cp[3], BLACK, 0.025, dash=[4, 3])
        cxm = sum(q[0] for q in cp) / len(cp)
        cym = sum(q[1] for q in cp) / len(cp)
        wide = (st["carport"]["w"] if st.get("carport") else 5) >= 4.5 or (st["carport"]["d"] >= 4.5)
        D.text(_off(sh, (cxm, cym), -0.0, -0.8), "Double" if wide else "Single", 0.5, sh.hdir(), box=True, spacing=110)
        D.text(_off(sh, (cxm, cym), 0.0, 0.9), "Carport", 0.5, sh.hdir(), box=True, spacing=110)
    # ---- the house
    if house:
        D.poly(house, BLACK, 0.04, RED)
        hx = sum(q[0] for q in house) / len(house)
        hy = sum(q[1] for q in house) / len(house)
        D.text((hx, hy), "NEW HOUSE", 0.75, sh.hdir(), bold=True, box=True)
    # ---- services
    if res:
        sw = res["sewer"]
        path = sw["path"]
        D.poly(path, BROWN, 0.09, None, dash=[8, 4], closed=False)
        for nd in sw["nodes"]:
            q = nd["pt"]
            if nd["kind"] in ("IE", "RE"):
                D.text(_off(sh, q, 0.9, -0.9), nd["kind"], 0.5, sh.hdir(), spacing=130)
            if nd["kind"] == "RE":
                D.text(_off(sh, q, 3.2, 0.0), "Min IL", 0.5, sh.hdir(), spacing=130)
                D.text(_off(sh, q, 3.2, 0.9), "%d" % round(res["params"]["min_depth"] * 1000), 0.5, sh.hdir(), spacing=130)
        D.text(_midrun(path, -0.9), sw["note"], 0.5, _rundir(path), spacing=105, bg=True)
        wt = res["water"]
        D.poly(wt["path"], BLUE, 0.05, None, closed=False)
        for k, (a, b) in enumerate(zip(wt["path"][:-1], wt["path"][1:])):
            L = edge_len(a, b)
            if L > 9.0:
                D.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "WL", 0.5, (b[0] - a[0], b[1] - a[1]), spacing=120, bg=True)
        for nd in wt["nodes"]:
            q = nd["pt"]
            if nd["kind"] == "WCON":
                D.text((q[0] + 0.0, q[1] - 0.9), "W.CON", 0.5, (1, 0), spacing=120)
            if nd["kind"] == "WM":
                D.poly([(q[0] - 0.25, q[1] - 0.25), (q[0] + 0.25, q[1] - 0.25), (q[0] + 0.25, q[1] + 0.25), (q[0] - 0.25, q[1] + 0.25)], BLUE, 0.04, QColor("white"))
        el = res["elec"]
        D.poly(el["path"], YELLOW, 0.05, None, closed=False)
        for a, b in zip(el["path"][:-1], el["path"][1:]):
            if edge_len(a, b) > 2.5:
                D.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "EL", 0.5, (b[0] - a[0], b[1] - a[1]), spacing=120, bg=True)
        for nd in el["nodes"]:
            q = nd["pt"]
            if nd["kind"] == "EC":
                D.text((q[0] + 0.7, q[1] - 0.75), "EC", 0.5, sh.hdir(), spacing=120)
                tri = [(q[0] - 1.2, q[1] + 0.9), (q[0] + 1.2, q[1] + 0.9), (q[0], q[1] - 1.2)]
                D.poly(tri, YELLOW, 0.04)
            if nd["kind"] == "DB":
                D.text(_off(sh, q, 0.0, 0.9), "DB", 0.55, sh.hdir(), bold=True)
    # ---- dimensions, in mm, placed like the plans: along the side boundary outside the stand, and in the strip in front of the street boundary
    lowx = (xmin, -1)
    highx = (xmax, 1)
    if cp:
        cxs, cys = [q[0] for q in cp], [q[1] for q in cp]
        x0, x1, y0, y1 = min(cxs), max(cxs), min(cys), max(cys)
        near_low = (x0 - xmin) <= (xmax - x1)
        sx, sgn = lowx if near_low else highx
        # from the street boundary to the carport front and across the carport (along the depth), outside the side boundary
        D.dim((sx, 0.0), (sx, y0), 1.6, mm(y0), 0.45, side=-sgn) if y0 > 0.05 else None
        D.dim((sx, y0), (sx, y1), 1.6, mm(y1 - y0), 0.45, side=-sgn)
        # along the street: the gap to the side boundary and the width of the carport, in the strip in front of the boundary
        if near_low:
            D.dim((xmin, 0.0), (x0, 0.0), 0.7, mm(x0 - xmin), 0.45, side=-1) if x0 - xmin > 0.05 else None
        else:
            D.dim((x1, 0.0), (xmax, 0.0), 0.7, mm(xmax - x1), 0.45, side=-1) if xmax - x1 > 0.05 else None
        D.dim((x0, 0.0), (x1, 0.0), 0.7, mm(x1 - x0), 0.45, side=-1)
    if house:
        hx0, hx1 = min(q[0] for q in house), max(q[0] for q in house)
        hy0, hy1 = min(q[1] for q in house), max(q[1] for q in house)
        rear = max(ys)
        # the house to the street, outside the side boundary opposite the carport
        far_low = False
        if cp:
            far_low = not ((min(q[0] for q in cp) - xmin) <= (xmax - max(q[0] for q in cp)))
        sx, sgn = lowx if far_low else highx
        D.dim((sx, 0.0), (sx, hy0), 1.6, mm(hy0), 0.45, side=-sgn) if hy0 > 0.05 else None
        # the gaps beside and behind the house, drawn in the gap
        gx = hx0 - xmin
        gx2 = xmax - hx1
        if gx > 0.05:
            D.dim((xmin, hy1 - 0.4), (hx0, hy1 - 0.4), 0.0, mm(gx), 0.45, side=1)
        if gx2 > 0.05:
            D.dim((hx1, hy1 - 0.4), (xmax, hy1 - 0.4), 0.0, mm(gx2), 0.45, side=1)
        if rear - hy1 > 0.05:
            D.dim((hx0 + 0.6, hy1), (hx0 + 0.6, rear), 0.0, mm(rear - hy1), 0.45, side=1)
    # ---- your own points
    for c in st.get("custom") or []:
        q = c["pt"]
        col = {"sewer": BROWN, "water": BLUE, "elec": YELLOW}.get(c["kind"], GREY)
        D.poly([(q[0], q[1] - 0.4), (q[0] + 0.4, q[1]), (q[0], q[1] + 0.4), (q[0] - 0.4, q[1])], BLACK, 0.04, col)
        D.text((q[0] + 0.9, q[1] - 0.8), c.get("name", ""), 0.5, sh.hdir(), spacing=110)
    # ---- north arrow, title
    return D


def _off(sh, q, dh, dv):
    """a point moved on the paper: dh to the right and dv down, in metres, whatever the road side"""
    o = sh.pt(q)
    return sh.inv(QPointF(o.x() + dh * sh.s, o.y() + dv * sh.s))


def _midrun(path, off):
    best, bl = 0, 0
    for i in range(len(path) - 1):
        L = edge_len(path[i], path[i + 1])
        if L > bl:
            best, bl = i, L
    a, b = path[best], path[best + 1]
    m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    L = bl or 1
    nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
    return (m[0] + nx * off, m[1] + ny * off)


def _rundir(path):
    best, bl = 0, 0
    for i in range(len(path) - 1):
        L = edge_len(path[i], path[i + 1])
        if L > bl:
            best, bl = i, L
    a, b = path[best], path[best + 1]
    return (b[0] - a[0], b[1] - a[1])


def north_arrow(p, centre_px, r_px, deg, minpx=7):
    """circle with a black needle and a red N, turned by `deg` clockwise from up"""
    p.save()
    p.translate(centre_px)
    p.rotate(deg)
    p.setPen(QPen(BLACK, max(0.8, r_px * 0.03)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0, 0), r_px, r_px)
    p.drawLine(QPointF(0, -r_px * 1.12), QPointF(0, r_px * 1.12))
    p.drawLine(QPointF(-r_px * 1.12, r_px * 0.1), QPointF(r_px * 1.12, -r_px * 0.1))
    p.setBrush(QBrush(BLACK))
    p.drawPolygon(QPolygonF([QPointF(0, -r_px * 0.95), QPointF(-r_px * 0.32, r_px * 0.82), QPointF(r_px * 0.33, r_px * 0.62)]))
    p.setFont(font(max(r_px * 0.95, minpx), True))
    p.setPen(RED)
    p.drawText(QPointF(-r_px * 0.35, -r_px * 1.3), "N")
    p.restore()
