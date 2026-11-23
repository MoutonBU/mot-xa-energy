"""The plan as a DXF at true size, drawn by the very same code that draws it on the screen, so what opens in ArchiCAD (or any CAD) is the plan you see:
the road, the stand, building lines, dimensions, setting-out, texts, eyes, the carport, the house, the compass, the underlay.

How: site_sheet draws with a QPainter. Here a stand-in painter (DxfPainter) receives the same calls and writes DXF entities instead of pixels.
1 drawing unit = 1 mm (INSUNITS = millimetres), the plan at 1:1, so it plots at 1:200 as drawn. Line weights are the 1:200 pen widths, dashes keep
their proportions, colours go to layers (and are kept as true colours). Texts are real TEXT entities (Arial) sized and turned as on the plan."""
import math

import ezdxf
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QFontMetrics, QPainter, QPen, QPicture, QPolygonF

import site_sheet

S_MM = 1000.0                                   # pixels per metre of the stand-in painter = millimetres per metre: the plan at 1:1

# layer by colour (r, g, b): name, AutoCAD colour index
LAYER_OF = {
    (173, 71, 10): ("SEWER", 30), (15, 130, 255): ("WATER", 5), (219, 209, 20): ("ELECTRICAL", 2), (255, 0, 0): ("HOUSE", 1),
    (255, 128, 128): ("CARPORT", 6), (255, 235, 214): ("ENTRY", 51), (110, 190, 245): ("SETTING OUT", 4), (120, 120, 120): ("ENTRY", 8),
}
UNDER_COLOURS = {(207, 214, 228), (183, 220, 183), (198, 222, 250), (236, 208, 182)}
EXTRA_LAYERS = [("SITE PLAN", 7), ("TEXT", 7), ("UNDERLAY", 9)]
STYLES = {("Arial", False): ("ARIAL", "arial.ttf"), ("Arial", True): ("ARIAL_BOLD", "arialbd.ttf"),
          ("Arial Black", True): ("ARIAL_BLACK", "ariblk.ttf"), ("Arial Black", False): ("ARIAL_BLACK", "ariblk.ttf")}
VALID_LW = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]   # the line weights DXF allows (1/100 mm)
CAP = 0.716                                      # Arial capital height / em


def _rgb(c):
    return (c.red(), c.green(), c.blue())


class DxfPainter:
    """just enough of QPainter for site_sheet: pen, brush, font, a transform stack, lines, polygons, rectangles, ellipses and text"""

    def __init__(self, doc, msp):
        self.doc, self.msp = doc, msp
        self.m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.stack = []
        self.pen = QPen(QColor("black"), 1)
        self.brush = QBrush(Qt.BrushStyle.NoBrush)
        self.font = None
        self.ltypes = {}

    # ---- the QPainter calls that carry no drawing
    def setRenderHint(self, *a, **k):
        pass

    def fillRect(self, *a, **k):
        pass

    def end(self):
        pass

    # ---- state
    def save(self):
        self.stack.append((self.m, QPen(self.pen), QBrush(self.brush), self.font))

    def restore(self):
        if self.stack:
            self.m, self.pen, self.brush, self.font = self.stack.pop()

    def setPen(self, v):
        if isinstance(v, QPen):
            self.pen = QPen(v)
        elif isinstance(v, QColor):
            self.pen = QPen(v, 1)
        else:
            self.pen = QPen(v)

    def setBrush(self, v):
        self.brush = QBrush(v)

    def setFont(self, f):
        self.font = f

    def fontMetrics(self):
        return QFontMetrics(self.font)

    def translate(self, a, b=None):
        tx, ty = (a.x(), a.y()) if b is None else (a, b)
        m = self.m
        self.m = (m[0], m[1], m[2], m[3], m[4] + m[0] * tx + m[2] * ty, m[5] + m[1] * tx + m[3] * ty)

    def rotate(self, deg):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        m = self.m
        self.m = (m[0] * c + m[2] * s, m[1] * c + m[3] * s, -m[0] * s + m[2] * c, -m[1] * s + m[3] * c, m[4], m[5])

    def _pt(self, x, y):
        m = self.m
        return (m[0] * x + m[2] * y + m[4], -(m[1] * x + m[3] * y + m[5]))          # paper pixels (y down) -> DXF (y up)

    # ---- entities
    def _layer(self, rgb, text=False):
        if rgb in LAYER_OF:
            return LAYER_OF[rgb][0]
        if rgb in UNDER_COLOURS:
            return "UNDERLAY"
        return "TEXT" if text else "SITE PLAN"

    def _attribs(self, rgb, text=False):
        return {"layer": self._layer(rgb, text), "true_color": ezdxf.colors.rgb2int(rgb)}

    def _lw(self):
        px = self.pen.widthF()
        v = px / S_MM * 500.0                                                         # the pen at 1:200, in 1/100 mm on paper
        return min(VALID_LW, key=lambda w: abs(w - v)) if v > 0 else 0

    def _ltype(self):
        if self.pen.style() in (Qt.PenStyle.SolidLine, Qt.PenStyle.NoPen):
            return None
        pat = list(self.pen.dashPattern())
        if len(pat) % 2:
            pat += pat
        w = max(self.pen.widthF(), 0.5)
        key = tuple(round(v * w, 1) for v in pat)
        if key not in self.ltypes:
            name = "DASH_%d" % len(self.ltypes)
            lens = []
            for i, v in enumerate(key):
                lens.append(v if i % 2 == 0 else -v)
            self.doc.linetypes.add(name, pattern=[sum(key)] + lens, description=name)
            self.ltypes[key] = name
        return self.ltypes[key]

    def _outline(self, pts, closed):
        if self.pen.style() == Qt.PenStyle.NoPen or len(pts) < 2:
            return
        at = self._attribs(_rgb(self.pen.color()))
        lw = self._lw()
        if lw:
            at["lineweight"] = lw
        lt = self._ltype()
        if lt:
            at["linetype"] = lt
        self.msp.add_lwpolyline(pts, close=closed, dxfattribs=at)

    def _fill(self, pts=None, circle=None):
        if self.brush.style() == Qt.BrushStyle.NoBrush:
            return
        rgb = _rgb(self.brush.color())
        h = self.msp.add_hatch(dxfattribs={"layer": self._layer(rgb)})
        h.set_solid_fill(rgb=rgb)
        if circle:
            (cx, cy), r = circle
            h.paths.add_edge_path().add_arc((cx, cy), r, 0, 360)
        else:
            h.paths.add_polyline_path(pts, is_closed=True)

    def drawLine(self, a, b):
        if isinstance(a, QPointF):
            self._outline([self._pt(a.x(), a.y()), self._pt(b.x(), b.y())], False)

    def drawPolyline(self, poly):
        self._outline([self._pt(q.x(), q.y()) for q in poly], False)

    def drawPolygon(self, poly):
        pts = [self._pt(q.x(), q.y()) for q in poly]
        self._fill(pts)
        self._outline(pts, True)

    def drawRect(self, r):
        if not isinstance(r, QRectF):
            r = QRectF(r)
        pts = [self._pt(r.left(), r.top()), self._pt(r.right(), r.top()), self._pt(r.right(), r.bottom()), self._pt(r.left(), r.bottom())]
        self._fill(pts)
        self._outline(pts, True)

    def drawEllipse(self, c, rx, ry=None):
        ctr = self._pt(c.x(), c.y())
        sc = math.hypot(self.m[0], self.m[1])
        self._fill(circle=(ctr, rx * sc))
        if self.pen.style() != Qt.PenStyle.NoPen:
            at = self._attribs(_rgb(self.pen.color()))
            lw = self._lw()
            if lw:
                at["lineweight"] = lw
            self.msp.add_circle(ctr, rx * sc, dxfattribs=at)

    def drawText(self, pos, txt):
        f = self.font
        px = f.pixelSize()
        fam = "Arial Black" if "Black" in f.family() else "Arial"
        style, ttf = STYLES.get((fam, f.bold()), STYLES[("Arial", False)])
        if style not in self.doc.styles:
            self.doc.styles.add(style, font=ttf)
        natural = QFontMetricsF(self._plain(f)).horizontalAdvance(txt)
        spaced = QFontMetricsF(f).horizontalAdvance(txt)
        wf = min(max(spaced / natural, 0.4), 4.0) if natural > 0 else 1.0
        x, y = self._pt(pos.x(), pos.y())
        ang = -math.degrees(math.atan2(self.m[1], self.m[0]))
        rgb = _rgb(self.pen.color())
        at = self._attribs(rgb, text=True)
        at.update({"style": style, "width": round(wf, 3), "rotation": round(ang % 360.0, 3)})
        e = self.msp.add_text(txt, height=px * CAP, dxfattribs=at)
        e.set_placement((x, y))

    @staticmethod
    def _plain(f):
        from PySide6.QtGui import QFont
        g = QFont(f)
        g.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100)
        return g


def new_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LTSCALE"] = 1.0
    seen = set()
    for name, aci in [(v[0], v[1]) for v in LAYER_OF.values()] + EXTRA_LAYERS:
        if name in seen:
            continue
        seen.add(name)
        doc.layers.add(name).color = aci
    return doc


def build_sheet(page, path, scale_text="1:200"):
    """what the screen shows, written as a DXF at true size"""
    st, res = page.st, page.res
    view = page.view
    (cx, cy), w_m, h_m = page.cutout_extent()                # the closer cut (the blue frame) goes to Archicad, not the wide working view
    cpoly = page.cutout_poly()
    road = st["sheet"].get("road", "left")
    turn = st["sheet"].get("turn", 0.0)
    W, H = w_m * S_MM, h_m * S_MM
    opts = page.export_opts()
    # where texts have to move off each other is worked out the way the screen does it, at the zoom on the screen
    scr = view.sh or site_sheet.Sheet(max(min(800.0 / w_m, 600.0 / h_m), 2.0), (cx, cy), (800, 600), road, turn)
    pic = QPicture()
    pp = QPainter(pic)
    d1 = site_sheet._draw(pp, scr, st, res, opts, 7)
    pp.end()
    o2 = dict(opts)
    o2["auto_off"] = site_sheet._avoid(scr, d1.hits, set(opts.get("labels") or {}))
    doc = new_doc()
    p = DxfPainter(doc, doc.modelspace())
    sh = site_sheet.Sheet(S_MM, (cx, cy), (W, H), road, turn)
    # the imported drawing's own lines, faint, under the plan
    if getattr(page, "under", None):
        for key, col in (("other", QColor("#cfd6e4")), ("storm", QColor("#b7dcb7")), ("water", QColor("#c6defa")), ("sewer", QColor("#ecd0b6")), ("elec", QColor("#efdc9a"))):
            for ux1, uy1, ux2, uy2, thick in page.under.get(key, []):
                p.setPen(QPen(col, 8 if thick else 4))
                p.drawLine(sh.pt((ux1, uy1)), sh.pt((ux2, uy2)))
    d = site_sheet._draw(p, sh, st, res, o2, minpx=0)
    r_px = max(S_MM * 1.5, 18)
    site_sheet.north_arrow(p, page.north_centre(W, H, r_px, False), r_px, st["sheet"].get("north", 0), minpx=0)
    _clip_to(doc.modelspace(),
             [p._pt(sh.pt(q_).x(), sh.pt(q_).y()) for q_ in cpoly])
    # the title block under the plan, as on the PDF sheet
    name = st["sheet"].get("stand_no") or st["stand"].get("name", "Stand")
    base = H + 3500
    p.setPen(QColor("black"))
    p.setFont(site_sheet.font(S_MM * 0.62, True, 100))
    p.drawText(QPointF(W * 0.04, base), "Site Plan")
    p.setFont(site_sheet.font(S_MM * 0.62, False, 100))
    p.drawText(QPointF(W * 0.04, base + S_MM * 0.9), scale_text)
    p.setPen(site_sheet.RED)
    p.setFont(site_sheet.font(S_MM * 0.8, True, 100))
    p.drawText(QPointF(W * 0.20, base + S_MM * 0.9), "To Scale if printed to A3")
    p.setPen(QColor("black"))
    p.setFont(site_sheet.font(S_MM * 0.5, False, 100))
    lines = ["Stand %s   %.0f m2   coverage %.1f%%" % (name, res["stand_area"], res["coverage_pct"]),
             "Sewer %s, %.1f m, depth at the house %d mm.   Water %.1f m.   Electrical %.1f m." % (res["sewer"]["note"], res["sewer"]["length"], round(res["sewer"]["depth_house"] * 1000), res["water"]["length"], res["elec"]["length"])]
    for i, t in enumerate(lines):
        p.drawText(QPointF(W * 0.55, base + i * S_MM * 0.9), t)
    doc.saveas(path)
    return path


def _clip_to(msp, poly):
    """keep only what is inside the frame (a convex polygon in DXF coordinates): lines and polylines are cut at the frame, texts, circles and fills outside it are dropped"""
    xs, ys = [q[0] for q in poly], [q[1] for q in poly]
    area = sum(poly[i][0] * poly[(i + 1) % 4][1] - poly[(i + 1) % 4][0] * poly[i][1] for i in range(4))
    sg = 1.0 if area > 0 else -1.0
    edges = [(poly[i], poly[(i + 1) % 4]) for i in range(4)]

    def side(q, e):
        return sg * ((e[1][0] - e[0][0]) * (q[1] - e[0][1]) - (e[1][1] - e[0][1]) * (q[0] - e[0][0]))

    def inside(q, tol=1e-6):
        return all(side(q, e) >= -tol * 1000 for e in edges)

    def clip(a, b):
        t0, t1 = 0.0, 1.0
        for e in edges:
            da, db = side(a, e), side(b, e)
            if da < 0 and db < 0:
                return None
            if da < 0:
                t0 = max(t0, da / (da - db))
            elif db < 0:
                t1 = min(t1, da / (da - db))
        if t0 >= t1:
            return None
        return (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0), (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
    for e in list(msp):
        t = e.dxftype()
        if t == "LINE":
            c = clip((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
            if c is None:
                msp.delete_entity(e)
            else:
                e.dxf.start, e.dxf.end = (c[0][0], c[0][1], 0), (c[1][0], c[1][1], 0)
        elif t == "LWPOLYLINE":
            pts = [(q[0], q[1]) for q in e.get_points("xy")]
            if all(inside(q) for q in pts):
                continue
            closed = e.closed
            if closed:
                if not any(inside(q) for q in pts):
                    msp.delete_entity(e)
                continue
            at = {k: getattr(e.dxf, k) for k in ("layer", "color", "lineweight", "linetype") if e.dxf.hasattr(k)}
            for a, b in zip(pts[:-1], pts[1:]):
                c = clip(a, b)
                if c:
                    msp.add_line(c[0], c[1], dxfattribs=at)
            msp.delete_entity(e)
        elif t == "TEXT":
            if not inside((e.dxf.insert.x, e.dxf.insert.y)):
                msp.delete_entity(e)
        elif t == "CIRCLE":
            if not inside((e.dxf.center.x, e.dxf.center.y)):
                msp.delete_entity(e)
        elif t == "HATCH":
            try:
                vs = [(v[0], v[1]) for path in e.paths for v in getattr(path, "vertices", [])]
                if vs and not any(inside(q) for q in vs):
                    msp.delete_entity(e)
            except Exception:
                pass
