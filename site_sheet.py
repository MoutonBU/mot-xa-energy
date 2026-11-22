"""The site plan drawn the way the MOT plans look: road on one side with its name and the mains, the stand with long-dash building lines, the entry,
the carport (crossed, in two label boxes), the red house with its white NEW HOUSE box, the services in brown (sewer, long dash), blue (water) and
yellow (electrical), IE / RE as spaced letters, dimensions in mm with oblique ticks, bold stand numbers and the compass.
Everything is placed in metres and drawn at the scale of `s` pixels per metre, so the same code makes the screen plan and the 1:200 sheet."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPicture, QPolygonF

import site_engine as se

BROWN = QColor(173, 71, 10)
BLUE = QColor(15, 130, 255)
YELLOW = QColor(219, 209, 20)
RED = QColor(255, 0, 0)
CARPORT = QColor(255, 128, 128)
ENTRY = QColor(255, 235, 214)
GREY = QColor(120, 120, 120)
SETOUT = QColor(110, 190, 245)
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
        self.offsets, self.hits, self.seen, self.dseen, self.edits, self.hidden = {}, [], {}, {}, {}, set()

    # ---- helpers
    def lw(self, m):                                    # a line weight in metres of paper-at-1:200 -> pixels
        return max(0.8, m * self.s)

    def text(self, q, txt, h=0.5, d=(1, 0), bold=False, color=BLACK, spacing=100, box=None, align="c", family="Arial", rot=None, bg=False, key=None, fixed=False):
        """text with its centre at world point q, running along world direction d. h = capital height in metres."""
        if self.lite:
            return
        p = self.p
        n_ = self.seen.get(txt, 0)
        self.seen[txt] = n_ + 1
        key = key or "%s#%d" % (txt, n_)
        if key in self.hidden:                                     # a text you deleted (the eyes themselves always stay; Texts back restores the words)
            return
        ed = self.edits.get(key)                                   # a text you edited: the words, the size, the turn
        extra_rot = 0.0
        if ed:
            txt = ed.get("t") or txt
            h = h * ed.get("s", 1.0)
            extra_rot = ed.get("r", 0.0)
        px = max(h * self.s * 1.4, self.minpx)
        off = None if fixed else self.offsets.get(key)
        if off:
            q = (q[0] + off[0], q[1] + off[1])                     # a label you moved by hand
        p.save()
        p.setFont(font(px, bold, spacing, family))
        pt = self.sh.pt(q)
        p.translate(pt)
        ang = (self.sh.angle(d) if rot is None else rot) + extra_rot
        p.rotate(ang)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(txt)
        ht = fm.ascent()
        self.hits.append((key, pt.x(), pt.y(), ang, w, ht, q, 0.0 if align == "c" else (w / 2 if align == "l" else -w / 2)))
        x0 = -w / 2 if align == "c" else (0 if align == "l" else -w)
        if (box or bg) and txt == "NEW HOUSE":                     # only NEW HOUSE keeps its white box; every other text is see-through
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

    def dot(self, q, r, color, filled=True):
        """a small ring (inspection eye) or a filled dot (rodding eye) on the pipe, so the eye is visibly on it"""
        if self.lite:
            return
        rp = max(r * self.s, 3.0)
        self.p.setPen(QPen(color, self.lw(0.04)))
        self.p.setBrush(QBrush(color if filled else QColor("white")))
        self.p.drawEllipse(self.sh.pt(q), rp, rp)

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

    def dim(self, a, b, off, txt, h=0.45, side=1, dkey=None):
        """dimension line between world points a and b, drawn `off` metres to one side, with oblique ticks and the figure.
        Drag its figure and the whole dimension slides up or down across its line."""
        if self.lite:
            return
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            return
        ux, uy = dx / L, dy / L
        nx, ny = -uy * side, ux * side
        if dkey is None:
            n_ = self.dseen.get(txt, 0)
            self.dseen[txt] = n_ + 1
            dkey = "DIM:%s#%d" % (txt, n_)
        if dkey in self.hidden:                                    # a dimension you deleted goes whole: lines, ticks and figure
            return
        mv = self.offsets.get(dkey)
        if mv:
            off = off + mv[0] * nx + mv[1] * ny
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
        self.text(mid, txt, h, (ux, uy), key=dkey, fixed=True)


def edge_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _draw(p, sh, st, res, opts, minpx=7, under=None, show_under=False, lite=False):
    """the whole plan. st = engine state, res = engine result, opts = sheet details (names, north, scale text)"""
    D = Drawer(p, sh, minpx, lite)
    D.offsets = dict(opts.get("auto_off") or {})                 # texts moved off each other by the program ...
    D.offsets.update(opts.get("labels") or {})                   # ... and the ones you moved by hand, which win
    D.edits = opts.get("text_edit") or {}
    D.hidden = set(opts.get("hidden") or [])
    sh.hits = D.hits                                         # so the page can tell which label you clicked
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
    real_road = st.get("road_lines") or []
    if real_road:                                      # a township drawing: the road as it really is (kerbs, bends, bell-mouths), not two straight lines
        for a_, b_, c_, d_ in real_road:
            D.line((a_, b_), (c_, d_), BLACK, 0.04)
    else:
        D.line((xa, ROAD_K), (xb, ROAD_K), BLACK, 0.04)
        D.line((xa, ROAD_K2), (xb, ROAD_K2), BLACK, 0.04)
    mn = se.mains(st)
    street = opts.get("street", "")
    if street:
        D.text(((xmin + xmax) / 2 + 3.0, -6.4), street, 1.05, (1, 0))
        sub = "%s  %s" % (opts.get("road_w", ""), opts.get("street_erf", ""))
        D.text(((xmin + xmax) / 2 + 3.0, -8.0), sub.strip(), 1.05, (1, 0))
    # ---- the stand, and the neighbours' boundaries running on from its corners (read from the imported drawing)
    for a_, b_ in opts.get("nb_lines") or []:
        D.line(a_, b_, BLACK, 0.04)
    look = st.get("look") or {}
    GREEN, WALLC = QColor(183, 221, 167), QColor(170, 25, 25)
    D.poly(stand, BLACK, 0.05, GREEN if look.get("fill", True) else None)       # the stand in green, as on the finished sheets
    if look.get("walls", True):                                                 # the boundary walls (1.2 m high pre-cast concrete) along the side and rear boundaries
        for i in range(n):
            if kinds[i] in ("side", "rear"):
                a, b = stand[i], stand[(i + 1) % n]
                L = edge_len(a, b) or 1
                nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
                if se.area(stand) < 0:
                    nx, ny = -nx, -ny
                D.poly([a, b, (b[0] + nx * 0.23, b[1] + ny * 0.23), (a[0] + nx * 0.23, a[1] + ny * 0.23)], BLACK, 0.02, WALLC)
                if L > 6:
                    m_ = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    D.text((m_[0] - nx * 0.75, m_[1] - ny * 0.75), "1.2m High Pre-Cast Concrete Wall", 0.4, (b[0] - a[0], b[1] - a[1]), spacing=105)
    # ---- entry block (kerb to the carport front)
    cp = res.get("carport") if res else None
    for i_, nb_ in enumerate(st.get("neighbours") or []):          # the stands beside it, from the township drawing
        if nb_.get("no"):
            D.text(tuple(nb_["c"]), str(nb_["no"]), 1.6, (1, 0), bold=True, color=QColor(120, 120, 120), key="NB:%d" % i_)
    if cp:
        en = entry_shape(st, cp)
        D.poly(en["poly"], GREY, 0.03, ENTRY)
        D.text(en["mid"], "Entry", 0.5, (1, 0), rot=None)
    if cp:
        D.poly(stand, BLACK, 0.05, None)                  # the street boundary line stays on top of the entry
    # the mains and manholes go over the entry and the green
    def real_main(k_, col, w_, dash, label, sp):
        pl = se.main_poly(st, k_)
        if not pl:
            return False
        D.poly(pl, col, w_, None, dash=dash, closed=False)
        i_ = max(range(len(pl) - 1), key=lambda i: edge_len(pl[i], pl[i + 1]))
        a_, b_ = pl[i_], pl[i_ + 1]
        D.text(((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2), label, 0.5, (b_[0] - a_[0], b_[1] - a_[1]), spacing=sp, bg=True)
        return True
    if not real_main("water", BLUE, 0.04, None, "Main Water Line", 110):
        D.line((xa, mn["water"]), (xb, mn["water"]), BLUE, 0.04)
        D.text((xmin - 6.0, mn["water"]), "Main Water Line", 0.5, (1, 0), spacing=110, align="r")
    mline = se.main_line(st)
    if mline:                                                    # the main runs through the stand, as drawn
        D.poly(mline, BROWN, 0.08, None, dash=[9, 5], closed=False)
        k_ = max(range(len(mline) - 1), key=lambda i: edge_len(mline[i], mline[i + 1]))
        a_, b_ = mline[k_], mline[k_ + 1]
        D.text(((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2), "Main Sewer Line", 0.5, (b_[0] - a_[0], b_[1] - a_[1]), spacing=125, bg=True)
    else:
        D.line((xa, mn["sewer"]), (xb, mn["sewer"]), BROWN, 0.08, dash=[9, 5])
        D.text((xmax + 10.5, mn["sewer"]), "Main Sewer Line", 0.5, (1, 0), spacing=125, align="r")
    for mh_ in st.get("manholes") or []:                         # manholes on the main, with their numbers
        q_ = tuple(mh_["pt"])
        D.dot(q_, 0.9, BROWN, filled=True)
        D.text((q_[0] + 1.2, q_[1] - 1.2), mh_.get("name", ""), 0.5, (1, 0), color=BROWN, spacing=110)
    if not real_main("elec", YELLOW, 0.05, [5, 4], "Main Electrical Line", 125):
        D.line((xa, mn["elec"]), (xmin - 7, mn["elec"]), YELLOW, 0.05, dash=[5, 4])
        D.text((xmin - 11.5, mn["elec"]), "Main Electrical Line", 0.5, (1, 0), spacing=125)
    for i in range(n):                                 # side lines run on past the street boundary to the kerb, as on the plans
        if kinds[i] == "side":
            a, b = stand[i], stand[(i + 1) % n]
            street_end = a if abs(a[1]) < abs(b[1]) else b
            if abs(street_end[1]) < 0.6 and not real_road:
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
        elif kinds[i] in ("side", "rear"):
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
    if cp:
        for a_, b_ in entry_shape(st, cp)["arrows"]:                                  # the way the cars drive in
            ux, uy = b_[0] - a_[0], b_[1] - a_[1]
            Lu = math.hypot(ux, uy) or 1.0
            ux, uy = ux / Lu, uy / Lu
            D.line(a_, b_, QColor(70, 70, 70), 0.05)
            D.poly([b_, (b_[0] - ux * 0.9 - uy * 0.4, b_[1] - uy * 0.9 + ux * 0.4), (b_[0] - ux * 0.9 + uy * 0.4, b_[1] - uy * 0.9 - ux * 0.4)], QColor(70, 70, 70), 0.03, QColor(70, 70, 70))
    # ---- the house
    if house:
        D.poly(house, BLACK, 0.04, RED)
        hx = sum(q[0] for q in house) / len(house)
        hy = sum(q[1] for q in house) / len(house)
        D.text((hx, hy), "NEW HOUSE", 0.75, sh.hdir(), bold=True, box=True)
        for nm, q in (res.get("marks") or []) if res else []:
            D.text(q, nm, 0.4, sh.hdir(), spacing=110)
        if res and look.get("wp_box", True):
            # the marks the finished plans carry on the house (SD at the soil outlet, KD at the kitchen water) when the footprint has none, and the waste / vent pipe box
            sp0, sn0 = se.port_point(res["house"], res["sewer"]["port"])
            if not res.get("marks"):
                D.text((sp0[0] - sn0[0] * 0.9, sp0[1] - sn0[1] * 0.9), "SD", 0.4, sh.hdir(), spacing=110)
                wp0, wn0 = se.port_point(res["house"], res["water"]["port"])
                D.text((wp0[0] - wn0[0] * 0.9, wp0[1] - wn0[1] * 0.9), "KD", 0.4, sh.hdir(), spacing=110)
            hcx = sum(q[0] for q in house) / len(house)
            hcy = sum(q[1] for q in house) / len(house)
            tx, ty = -sn0[1], sn0[0]
            sg = 1.0 if (sp0[0] - hcx) * tx + (sp0[1] - hcy) * ty >= 0 else -1.0
            bc = (sp0[0] - sn0[0] * 1.5 + tx * sg * 3.0, sp0[1] - sn0[1] * 1.5 + ty * sg * 3.0)    # inside the wall, off to one side so it never sits on NEW HOUSE
            D.poly([_off(sh, bc, -2.3, -0.95), _off(sh, bc, 2.3, -0.95), _off(sh, bc, 2.3, 0.95), _off(sh, bc, -2.3, 0.95)], QColor(220, 20, 20), 0.03, None)
            D.text(_off(sh, bc, 0, -0.42), "50\u00d8 WP's", 0.45, sh.hdir(), spacing=105)
            D.text(_off(sh, bc, 0, 0.42), "110\u00d8 GI VV", 0.45, sh.hdir(), spacing=105)
    # ---- services
    if res:
        sw = res["sewer"]
        path = sw["path"]
        D.poly(path, BROWN, 0.09, None, dash=[8, 4], closed=False)
        if sw.get("branch"):
            D.poly(sw["branch"], BROWN, 0.09, None, dash=[8, 4], closed=False)
        for ex in sw.get("extra") or []:
            D.poly(ex["path"], BROWN, 0.09, None, dash=[8, 4], closed=False)
        for sb in sw.get("stubs") or []:
            D.poly(sb, BROWN, 0.09, None, dash=[8, 4], closed=False)
        for nd in sw["nodes"]:
            q = nd["pt"]
            if nd["kind"] in ("IE", "RE"):
                D.dot(q, 0.17, BROWN, filled=nd["kind"] == "RE")
                D.text(_off(sh, q, 0.7, 0.55 if nd["label"] == "RE" else -0.55), nd["kind"], 0.5, sh.hdir(), spacing=130, key="EYE:" + str(nd.get("key", nd["kind"])))
            if nd["kind"] == "RE" and str(nd.get("label", "")).startswith("RE Min"):
                D.text(_off(sh, q, 3.2, 0.0), "Min IL", 0.5, sh.hdir(), spacing=130)
                D.text(_off(sh, q, 3.2, 0.9), "%d" % round(res["params"]["min_depth"] * 1000), 0.5, sh.hdir(), spacing=130)
        D.text(_midrun(path, -0.9), sw["note"], 0.5, _rundir(path), spacing=105)
        wt = res["water"]
        D.poly(se.rounded(wt["path"]), BLUE, 0.05, None, closed=False)
        for br in wt.get("branches") or []:
            D.poly(se.rounded(br["path"]), BLUE, 0.05, None, closed=False)
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
    if look.get("storm", True) and res:
        sd, srot = storm_pose(st, res)
        if sd:
            SW = QColor(20, 90, 220)
            t_ = storm_head(sd, srot)                                # the flow runs the way the arrow points (towards the street unless you turned it)
            ux, uy = (t_[0] - sd[0]) / 3.0, (t_[1] - sd[1]) / 3.0
            D.line(sd, t_, SW, 0.05)
            D.poly([t_, (t_[0] - ux * 0.8 - uy * 0.35, t_[1] - uy * 0.8 + ux * 0.35), (t_[0] - ux * 0.8 + uy * 0.35, t_[1] - uy * 0.8 - ux * 0.35)], SW, 0.03, SW)
            mid = ((sd[0] + t_[0]) / 2, (sd[1] + t_[1]) / 2)
            D.text(mid, "Stormwater Flow", 0.5, (ux, uy), color=SW, spacing=110, key="STORM")
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
    square = True
    if house:
        square = all(min(abs(house[(i + 1) % len(house)][0] - house[i][0]), abs(house[(i + 1) % len(house)][1] - house[i][1])) <= 0.02 * max(edge_len(house[i], house[(i + 1) % len(house)]), 1e-6)
                     for i in range(len(house)))
        if opts.get("setting_out", True):
            _setting_out(D, stand, house, kinds, label=True)
    if house and square and not opts.get("setting_out", True):   # (with setting-out on, the chains outside the boundaries give these distances)
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
    for k, dm in enumerate(st.get("dims") or []):              # dimensions you added: two points and how far off the line it sits
        a_, b_ = dm["a"], dm["b"]
        D.dim(a_, b_, dm.get("off", 1.0), mm(edge_len(a_, b_)), 0.45, side=1, dkey="DIM:u%d" % k)
    for k, nt in enumerate(st.get("notes") or []):             # texts you added
        pt = tuple(nt["pt"])
        lk = nt.get("link")
        if lk and lk.get("a"):                                         # linked: it moves with the thing it is linked to
            an = link_anchor(st, res, lk)
            if an:
                pt = (pt[0] + an[0] - lk["a"][0], pt[1] + an[1] - lk["a"][1])
        D.text(pt, nt["t"], 0.5, sh.hdir(), key="NOTE:%d" % k)
    # ---- your own points
    for c in st.get("custom") or []:
        q = c["pt"]
        col = {"sewer": BROWN, "water": BLUE, "elec": YELLOW}.get(c["kind"], GREY)
        D.poly([(q[0], q[1] - 0.4), (q[0] + 0.4, q[1]), (q[0], q[1] + 0.4), (q[0] - 0.4, q[1])], BLACK, 0.04, col)
        D.text((q[0] + 0.9, q[1] - 0.8), c.get("name", ""), 0.5, sh.hdir(), spacing=110)
    # ---- north arrow, title
    return D


KERB = -3.4                                                    # the kerb line the entry starts from (street boundary is y = 0)


def entry_shape(st, cp, kerb=KERB):
    """the entry (drive) from the kerb to the carport and the arrows of the cars driving in. The cars come in on the side facing the street unless you
    turned the entry to another side (carport "entry_face": 0 = the street side, then a quarter turn at a time). The drive is 5 m wide for a double
    carport and 3 m for a single (the South African usual widths); it leaves the kerb at your point (or square in front of the carport) and runs
    round the carport to the side the cars enter, with rounded corners. Returns {poly, k (kerb centre), width, face, mid, arrows}."""
    n = len(cp)
    cen = (sum(q[0] for q in cp) / n, sum(q[1] for q in cp) / n)
    c = st.get("carport") or {}
    ex = c.get("entry_x")
    k_face = int(c.get("entry_face") or 0) % 4
    target = (0.0, -1.0)
    for _ in range(k_face):                                        # a quarter turn anticlockwise per step
        target = (-target[1], target[0])
    best = None
    for i in range(n):
        a, b = cp[i], cp[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-6:
            continue
        nr = ((b[1] - a[1]) / L, -(b[0] - a[0]) / L)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if (mid[0] - cen[0]) * nr[0] + (mid[1] - cen[1]) * nr[1] < 0:
            nr = (-nr[0], -nr[1])
        score = nr[0] * target[0] + nr[1] * target[1]            # how squarely the side faces the way the cars come from
        key = (round(score, 3), -abs(mid[0] - (ex if ex is not None else cen[0])))
        if best is None or key > best[0]:
            best = (key, a, b, nr, L, mid)
    _k, a, b, nr, L, mid = best
    W = 5.0 if L >= 4.0 else 3.0
    f1, f2 = (a, b) if a[0] <= b[0] else (b, a)
    if k_face == 0:
        if ex is None:
            ex = mid[0]
        k1, k2 = (ex - W / 2.0, kerb), (ex + W / 2.0, kerb)

        def curve(k, f):
            d = 0.4 * math.hypot(f[0] - k[0], f[1] - k[1])
            p0, p1, p2, p3 = k, (k[0], k[1] + d), (f[0] + nr[0] * d, f[1] + nr[1] * d), f
            out = []
            for i in range(15):
                t = i / 14.0
                u = 1 - t
                out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
            return out
        left, right = curve(k1, f1), curve(k2, f2)
        poly = left + right[::-1]
        dmid = ((left[7][0] + right[7][0]) / 2, (left[7][1] + right[7][1]) / 2)
    else:
        r = W / 2.0 + 0.8
        s_ = r + 0.6
        A = (mid[0] + nr[0] * s_, mid[1] + nr[1] * s_)
        sx = [q[0] for q in (st.get("stand") or {}).get("corners", [(0, 0), (20, 0)])]
        if ex is None:
            if abs(nr[1]) > 0.7:                                    # a side facing along the stand: come in from beside the carport
                xs_ = [q[0] for q in cp]
                ex = min(xs_) - W / 2.0 - 1.0
                if ex - W / 2.0 < min(sx):
                    ex = max(xs_) + W / 2.0 + 1.0
            else:
                ex = A[0]
        centre = [(ex, kerb), (ex, A[1]), A, mid]
        cl = se.rounded(se.dedupe(centre), r=r, steps=10)
        tl, tr = [], []
        for i, p_ in enumerate(cl):
            q0 = cl[max(i - 1, 0)]
            q1 = cl[min(i + 1, len(cl) - 1)]
            tx, ty = q1[0] - q0[0], q1[1] - q0[1]
            Lt = math.hypot(tx, ty) or 1.0
            lx, ly = -ty / Lt, tx / Lt
            tl.append((p_[0] + lx * W / 2.0, p_[1] + ly * W / 2.0))
            tr.append((p_[0] - lx * W / 2.0, p_[1] - ly * W / 2.0))
        tx, ty = cl[-1][0] - cl[-2][0], cl[-1][1] - cl[-2][1]
        lx, ly = -ty, tx
        fl, fr = (f1, f2) if (f1[0] - mid[0]) * lx + (f1[1] - mid[1]) * ly > 0 else (f2, f1)
        tl[-1], tr[-1] = fl, fr
        poly = tl + tr[::-1]
        dmid = cl[len(cl) // 2]
    # the cars driving in: one arrow for a single carport, two for a double, from the entry side to the far side
    tx, ty = (f2[0] - f1[0]) / (L or 1), (f2[1] - f1[1]) / (L or 1)
    depth = max((cen[0] - q[0]) * 0 + (q[0] - mid[0]) * -nr[0] + (q[1] - mid[1]) * -nr[1] for q in cp)
    arrows = []
    for off in ((-L / 4.0, L / 4.0) if L >= 4.0 else (0.0,)):
        st_ = (mid[0] + tx * off - nr[0] * 0.5, mid[1] + ty * off - nr[1] * 0.5)
        en_ = (mid[0] + tx * off - nr[0] * (depth * 0.8), mid[1] + ty * off - nr[1] * (depth * 0.8))
        arrows.append((st_, en_))
    return {"poly": poly, "k": (ex, kerb), "width": W, "face": (f1, f2), "mid": dmid, "arrows": arrows}


def storm_pose(st, res):
    """where the stormwater arrow sits (its tail) and how it is turned (0 = pointing at the street, degrees anticlockwise); your own placement wins"""
    look = st.get("look") or {}
    stand = st["stand"]["corners"]
    rot = float(look.get("storm_rot", 0.0))
    pos = look.get("storm_pos")
    if pos:
        return (pos[0], pos[1]), rot
    house = (res or {}).get("house")
    cp = (res or {}).get("carport")
    hc = (sum(q[0] for q in house) / len(house), sum(q[1] for q in house) / len(house)) if house else (0, 0)
    hb = se.offset(se.hull(house), 2.0) if house else None
    cb = se.offset(se.hull(cp), 1.5) if cp else None
    gy = [q[1] for q in stand]
    best = None
    for gx_ in range(int(min(q[0] for q in stand)) + 2, int(max(q[0] for q in stand)) - 1):
        for gy_ in range(int(min(gy) + 0.2 * (max(gy) - min(gy))), int(max(gy)) - 2):
            q = (float(gx_), float(gy_))
            if se.inside(q, stand) and se.inside((q[0], q[1] - 3.0), stand) and not (hb and se.inside(q, hb)) and not (cb and se.inside(q, cb)) \
                    and not (hb and se.inside((q[0], q[1] - 3.0), hb)):
                d_ = math.hypot(q[0] - hc[0], q[1] - hc[1])
                if best is None or d_ > best[0]:
                    best = (d_, q)
    return (best[1] if best else None), rot


def storm_head(pos, rot, L=3.0):
    a = math.radians(-90.0 + rot)
    return (pos[0] + L * math.cos(a), pos[1] + L * math.sin(a))


def _avoid(sh, hits, manual):
    """nothing may overlap: texts that sit on another text are moved off it, the biggest texts stay put. Returns {key: world shift}."""
    boxes = []
    for key, px, py, ang, w, ht, q, cx in hits:
        a = math.radians(ang)
        ew = abs(w * math.cos(a)) + abs(ht * math.sin(a))
        eh = abs(w * math.sin(a)) + abs(ht * math.cos(a))
        boxes.append([key, px + cx * math.cos(a), py + cx * math.sin(a), ew + 6, eh + 6, ang, w, ht])
    order = sorted(range(len(boxes)), key=lambda i: -(boxes[i][6] * boxes[i][7]))
    placed, shifts = [], {}

    def hit(b, x, y):
        return any(abs(x - o[0]) < (b[3] + o[3]) / 2 and abs(y - o[1]) < (b[4] + o[4]) / 2 for o in placed)

    for i in order:
        b = boxes[i]
        x, y = b[1], b[2]
        movable = b[0] not in manual and not b[0].startswith("DIM:") and not b[0].startswith("NOTE:")
        if movable and hit(b, x, y):
            a = math.radians(b[5])
            ax, ay = math.cos(a), math.sin(a)
            step = b[7] * 1.05
            best = None
            for k in range(1, 7):
                for dx, dy in ((ay, -ax), (-ay, ax), (ax, ay), (-ax, -ay)):    # up, down across the text, then along it
                    d = step * k
                    if not hit(b, x + dx * d, y + dy * d):
                        best = (dx * d, dy * d)
                        break
                if best:
                    break
            if best:
                x, y = x + best[0], y + best[1]
                p0 = sh.inv(QPointF(b[1], b[2]))
                p1 = sh.inv(QPointF(x, y))
                shifts[b[0]] = (p1[0] - p0[0], p1[1] - p0[1])
        placed.append([x, y, 0, b[3], b[4]])
    return shifts


def draw(p, sh, st, res, opts, minpx=7, under=None, show_under=False, lite=False):
    """the whole plan. A first pass finds where texts collide, the second draws with the colliding ones moved apart."""
    if not lite and not opts.get("no_avoid"):
        pic = QPicture()
        pp = QPainter(pic)
        D1 = _draw(pp, sh, st, res, opts, minpx, under, show_under, lite)
        pp.end()
        o2 = dict(opts)
        o2["auto_off"] = _avoid(sh, D1.hits, set(opts.get("labels") or {}))
        return _draw(p, sh, st, res, o2, minpx, under, show_under, lite)
    return _draw(p, sh, st, res, opts, minpx, under, show_under, lite)


def _setting_out(D, stand, house, kinds, label):
    """setting out: from each boundary to the nearest corner of the house, square to the boundary, in light blue dashes. Follows the house when it is rotated.
    When the house is not square to the boundary, the corners it reaches out to (the nearest one and the two at the ends) are also carried out past the
    boundary in light blue, and a dimension chain outside the boundary gives the distances between the stand's corners and those lines."""
    n = len(stand)
    ccw = se.area(stand) > 0
    for i in range(n):
        a, b = stand[i], stand[(i + 1) % n]
        L = edge_len(a, b)
        if L < 1e-6:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        out = (uy, -ux) if ccw else (-uy, ux)
        cands = []
        for v in house:
            t = (v[0] - a[0]) * ux + (v[1] - a[1]) * uy
            if not 0.0 <= t <= L:
                continue
            f = (a[0] + ux * t, a[1] + uy * t)
            d = edge_len(v, f)
            if 0.05 < d < 60:
                cands.append((d, t, v, f))
        if not cands:
            continue
        d, t, v, f = min(cands)
        D.line(v, f, SETOUT, 0.045, dash=[7, 4])
        if label:
            D.text(((v[0] + f[0]) / 2, (v[1] + f[1]) / 2), mm(d), 0.4, (v[0] - f[0], v[1] - f[1]), spacing=110, color=BLACK)
        if label:
            pick = {id(c): c for c in (min(cands), min(cands, key=lambda c: c[1]), max(cands, key=lambda c: c[1]))}.values()
            off = 2.4
            ts = []
            for d2, t2, v2, f2 in pick:
                if all(abs(t2 - q) > 0.05 for q in ts):
                    ts.append(t2)
                    D.line(f2, (f2[0] + out[0] * (off + 0.3), f2[1] + out[1] * (off + 0.3)), SETOUT, 0.045, dash=[7, 4])
                    if d2 > 0.05 and (d2, t2, v2, f2) != (d, t, v, f):
                        D.line(v2, f2, SETOUT, 0.045, dash=[7, 4])
            chain = [0.0] + sorted(ts) + [L]
            for t0, t1 in zip(chain[:-1], chain[1:]):
                if t1 - t0 > 0.05:
                    D.dim((a[0] + ux * t0, a[1] + uy * t0), (a[0] + ux * t1, a[1] + uy * t1), off, mm(t1 - t0), 0.45, side=-1 if ccw else 1)


def link_anchor(st, res, lk):
    """where the thing a text is linked to is now"""
    k = (lk or {}).get("k")
    if k in ("house", "carport") and st.get(k):
        return (st[k]["cx"], st[k]["cy"])
    if not res:
        return None
    if k == "eye":
        for nd in res["sewer"]["nodes"]:
            if nd.get("key") == lk.get("key"):
                return tuple(nd["pt"])
        return None
    if k == "sewer":
        P = res["sewer"]["path"]
        return ((P[0][0] + P[-1][0]) / 2, (P[0][1] + P[-1][1]) / 2) if P else None
    return None


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
