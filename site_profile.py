"""Sewer long section (longitudinal section) for the council, worked out from the sewer placed on the site plan.

build(state, res)   -> the numbers: a station every eye and the connection, with chainage, natural ground level, invert level, depth, cover and fall
draw(p, W, H, S, data, title_lines)  -> the sheet (A1 landscape: laid out as 420 x 297 and printed at twice that size), drawn with a QPainter or the DxfPainter of site_export
write_pdf / write_dxf / render_image -> the three outputs

Levels: the engine only knows depths below the ground. The ground levels (at the house, at the main, optional spot levels along the run) and the main's
invert level are typed in by the designer (state["levels"]); when they are not typed the sheet says the levels are assumed. The invert level at the
house is the ground level there minus the minimum depth, and falls at the pipe's fall (1 : n) all the way to the main. All sizes below are paper millimetres
(S = drawing units per paper millimetre, so the same code makes the PDF and the 1:200 DXF)."""
import datetime
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QImage, QPen, QPolygonF

import site_sheet

PIPE_OD = {"110": 0.110, "160": 0.160}
BROWN = QColor(173, 71, 10)                       # the sewer colour of the plan (layer SEWER in the DXF)
GREEN = QColor(40, 110, 40)
GREY = QColor(150, 150, 150)
BLACK = QColor(0, 0, 0)
RED = QColor(220, 0, 0)
ASSUMED_DATUM = 100.0
CAP = 0.716


def _set(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def parse_spots(text):
    """'5=99.8, 10=99.6' -> [(5.0, 99.8), (10.0, 99.6)] (chainage from the house, level)"""
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        if "=" in part:
            a, b = part.split("=", 1)
            try:
                out.append((float(a), float(b)))
            except ValueError:
                pass
    return sorted(out)


_TERR = {}


def terrain_for(state):
    """the ground model made from the contours in the project (in the stand's own frame), or None when there are none or they are switched off"""
    cd = state.get("contours")
    if not cd or not (cd.get("lines") or cd.get("spots")):
        return None
    if not (state.get("levels") or {}).get("use_contours", 1):
        return None
    import site_dxf as site_contours
    import site_engine as se_
    fr = state.get("frame")
    key = (id(cd), len(cd.get("lines") or []), len(cd.get("spots") or []), tuple(fr) if fr else None)
    t = _TERR.get("t")
    if _TERR.get("k") == key and t is not None:
        return t
    mp = (lambda p: se_.apply_frame(fr, p)) if fr else (lambda p: tuple(p))
    t = site_contours.Terrain([[z, [mp(p) for p in pts]] for z, pts in cd.get("lines") or []], [list(mp(s[:2])) + [s[2]] for s in cd.get("spots") or []])
    _TERR["k"], _TERR["t"] = key, t
    return t if t.ok() else None


def build(state, res, il_head=None, lean_ratio=None):
    sw = res["sewer"]
    par = res.get("params") or {}
    lv = state.get("levels") or {}
    fall = float(par.get("fall", 50.0))
    D0 = float(par.get("min_depth", 0.45))
    od = PIPE_OD.get(str(par.get("sewer_pipe", "110")), 0.110)
    path = sw["path"]
    Lp = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path[:-1], path[1:]))
    Hh = float(sw["length"])
    n0, n1, mil = lv.get("ngl_head"), lv.get("ngl_main"), lv.get("main_il")
    assumed = not (_set(n0) or _set(n1))
    if _set(n0):
        ngl0 = float(n0)
    elif _set(n1):
        ngl0 = float(n1)
    else:
        ngl0 = ASSUMED_DATUM
    ngl1 = float(n1) if _set(n1) else ngl0
    spots = [(x, y) for x, y in parse_spots(lv.get("spots")) if 0 < x < Hh]
    pts = [(0.0, ngl0)] + spots + [(Hh, ngl1)]
    terr = terrain_for(state)
    if terr is not None:                                        # a contoured site: the ground along the pipe is read off the contours
        import site_engine as se_
        path_ = [tuple(q) for q in sw["path"]]
        Lp_ = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path_[:-1], path_[1:]))

        def gxy(x_):
            c_ = x_ - (Hh - Lp_)
            return path_[0] if c_ <= 0 else se_._point_at(path_, c_)
        xs_c = sorted(set([k_ * 0.5 for k_ in range(int(Hh / 0.5) + 1)] + [Hh]))
        pts = [(x_, terr.z_at(*gxy(x_))) for x_ in xs_c]
        ngl0, ngl1 = pts[0][1], pts[-1][1]
        assumed = False

    def ngl(x):
        x = max(0.0, min(Hh, x))
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            if xa <= x <= xb:
                return ya + (yb - ya) * ((x - xa) / (xb - xa) if xb > xa else 0.0)
        return ngl1

    il_head = ngl0 - D0 if il_head is None else float(il_head)
    # drops the designer added (chainage = invert level just after the drop): the pipe steps down at a rodding eye and carries on at the fall
    drops_in = [(x, y) for x, y in parse_spots(lv.get("drops")) if 0 < x < Hh]
    # the steep part of a drop is drawn at 45 degrees on the sheet (horizontal 1:50, vertical 1:100): it takes half its height in metres of chainage,
    # and the lower run starts at the foot of it
    segs, drop_lean = [(0.0, il_head)], {}
    for xd_, yd_ in drops_in:
        yin_ = segs[-1][1] - (xd_ - segs[-1][0]) / fall
        lean_ = max(0.0, (0.5 if lean_ratio is None else lean_ratio) * (yin_ - yd_))
        lean_ = min(lean_, max(Hh - xd_ - 0.05, 0.0))
        drop_lean[xd_] = lean_
        segs.append((xd_ + lean_, yd_))                         # (chainage where the run starts, invert level there)

    def il(x):
        xs_, ys_ = segs[0]
        for a_, b_ in segs:
            if a_ <= x + 0.03:                                  # a station and a drop typed to the centimetre are the same place
                xs_, ys_ = a_, b_
        return ys_ - (x - xs_) / fall

    def il_in(x):                                               # the level the pipe arrives at, before a drop at x
        k = 0
        for i_, (a_, _b) in enumerate(segs):
            if a_ < x - 0.03:
                k = i_
        return segs[k][1] - (x - segs[k][0]) / fall

    conn_depth = float(par.get("conn_depth", 1.5))
    main_il_typed = _set(mil)
    main_il = float(mil) if main_il_typed else ngl1 - conn_depth
    nodes = []
    for n in sw["nodes"]:
        d = n.get("dist")
        x = (Hh - d) if d is not None else (Hh - Lp + n["chainage"])
        nodes.append((max(0.0, min(Hh, x)), n))
    for xd, _yd in drops_in:                                    # a rodding eye where the pipe drops (it is rodded down the steep part); an eye already there stays
        for k_ in ("RE",):
            if not any(abs(x_ - xd) < 0.05 and n_["kind"] == k_ for x_, n_ in nodes):
                nodes.append((xd, {"kind": k_, "label": k_, "drop": True}))
    nodes.sort(key=lambda t: (t[0], t[1]["kind"]))
    st, count = [], {}
    for x, n in nodes:
        if st and abs(st[-1]["x"] - x) < 0.05 and st[-1]["kind"] == n["kind"]:
            continue
        k = n["kind"]
        if k == "MAIN":
            name, desc = "MAIN", "Connection to the main sewer"
        else:
            count[k] = count.get(k, 0) + 1
            name = "%s%d" % (k, count[k])
            desc = ("Inspection eye" if k == "IE" else "Rodding eye") + (" (minimum invert level)" if str(n.get("label", "")).startswith("RE Min") else "")
            if "wall" in n:
                desc = "Outlet from the house"
        g = ngl(x)
        i = il(x)
        dr = next((yd for xd, yd in drops_in if abs(xd - x) < 0.05), None)
        if dr is not None:
            i = dr
        if dr is not None and k != "MAIN":
            desc = ("Rodding eye with a drop of %d mm" % round((il_in(x) - i) * 1000)) if k == "RE" else "Inspection eye at the drop"
        st.append({"name": name, "kind": k, "desc": desc, "x": round(x, 2), "ngl": g, "il": i, "depth": g - i, "cover": g - i - od,
                   "drop": (il_in(x) - i) if dr is not None and k == "RE" else 0.0, "top": il_in(x) if dr is not None else i})
    covers = [ngl(k / 10.0 * Hh) - il(k / 10.0 * Hh) - od for k in range(0, 11)]
    if terr is not None:                                        # on a contoured site look every half metre, so no hump in the ground is missed
        covers += [ngl(x_) - il(x_) - od for x_ in xs_c]
    worst = min(range(0, 41), key=lambda k: ngl(k / 40.0 * Hh) - il(k / 40.0 * Hh) - od) / 40.0 * Hh
    covers += [s["cover"] for s in st] + [ngl(x_) - il_in(x_) - od for x_, _y in drops_in]
    min_cover = min(covers) if covers else 0.0
    mc_ = float(par.get("min_cover", 0.3))
    bad, run_ = [], None                                         # the stretches where the soil cover is too low (every 0.25 m)
    for k_ in range(0, int(Hh / 0.25) + 2):
        x_ = min(k_ * 0.25, Hh)
        low_ = ngl(x_) - il(x_) - od < mc_ - 1e-6
        if low_ and run_ is None:
            run_ = x_
        if not low_ and run_ is not None:
            bad.append((run_, x_))
            run_ = None
    if run_ is not None:
        bad.append((run_, Hh))
    drop = il(Hh) - main_il
    checks = []
    f_flat, f_sp = float(par.get("fall_flat", 60.0)), float(par.get("fall_special", 120.0))
    if fall <= f_flat:
        checks.append(("Fall 1:%d is not flatter than 1:%d (SANS 10252-2, table 13)." % (fall, f_flat), True))
    elif fall <= f_sp:
        checks.append(("Fall 1:%d is flatter than 1:%d: special permission from the council is needed (SANS 10252-2, table 13)." % (fall, f_flat), None))
    else:
        checks.append(("Fall 1:%d is flatter than 1:%d, the flattest allowed (SANS 10252-2, table 13)." % (fall, f_sp), False))
    mc = float(par.get("min_cover", 0.3))
    checks.append(("Soil cover over the pipe is at least %d mm everywhere (lowest %d mm)." % (round(mc * 1000), round(min_cover * 1000)) if min_cover >= mc - 1e-6
                   else ("Soil cover is less than %d mm (lowest %d mm, at %.1f m from the house%s): lay the pipe deeper%s." % (
                       round(mc * 1000), round(min_cover * 1000), worst, " - the pipe comes out of the ground there" if min_cover < 0 else "",
                       "" if drops_in else ", for example start it about %d mm deeper at the house or use a steeper fall" % (math.ceil((mc - min_cover) * 20.0) * 50))), min_cover >= mc - 1e-6))
    if drop >= -0.002:
        checks.append(("The pipe reaches the main %d mm above its invert level (%s)." % (round(drop * 1000), "typed" if main_il_typed else "taken as %d mm below the ground at the main" % round(conn_depth * 1000)), True))
    else:
        checks.append(("The pipe arrives %d mm BELOW the invert of the main: it cannot drain to the main by gravity. Lay it shallower or flatter, or check the main's level." % round(-drop * 1000), False))
    for xd, yd in drops_in:
        h_ = il_in(xd) - yd
        checks.append(("Drop of %d mm at chainage %.1f m, with a rodding eye at the top of the steep part." % (round(h_ * 1000), xd), h_ >= -1e-6) if h_ >= -1e-6 else
                      ("The drop at chainage %.1f m would lift the pipe by %d mm: type a lower invert level." % (xd, round(-h_ * 1000)), False))
    gaps = [b["x"] - a["x"] for a, b in zip(st[:-1], st[1:])]
    mx = float(par.get("max_ie", 25.0))
    if gaps:
        checks.append(("Eyes are at most %.1f m apart (limit %.0f m)." % (max(gaps), mx) if max(gaps) <= mx + 1e-6 else "Eyes are %.1f m apart: more than %.0f m." % (max(gaps), mx), max(gaps) <= mx + 1e-6))
    out = {"stations": st, "length": Hh, "fall": fall, "od": od, "pipe": str(par.get("sewer_pipe", "110")), "ngl": ngl, "il": il, "ngl0": ngl0, "ngl1": ngl1,
            "pts": pts, "il_in": il_in, "segs": segs, "drops": [(x_, il_in(x_), y_) for x_, y_ in drops_in], "drop_lean": drop_lean, "terrain": terr is not None, "main_il": main_il, "main_typed": main_il_typed, "drop": drop, "assumed": assumed, "min_cover": min_cover, "checks": checks,
            "ffl": float(lv["ffl"]) if _set(lv.get("ffl")) else None, "note": sw.get("note", ""), "bad": bad, "lines_only": bool(lv.get("lines_only"))}
    out["lean_ratio"] = 0.5 if lean_ratio is None else lean_ratio
    if drops_in and lean_ratio is None:                         # the steep part is 45 degrees on the sheet: its run is its height times (horizontal scale / vertical scale)
        r_ = 0.5
        for _k in range(6):                                     # the scales depend on the levels the drop gives: settle them
            out = build(state, res, il_head, r_)
            hs_, vs_, _dt, _mo = scales(out)
            if abs(hs_ / float(vs_) - r_) < 1e-9:
                break
            r_ = hs_ / float(vs_)
    return out


# ---------------------------------------------------------------- drawing
def _f(S, h_mm, bold=False):
    return site_sheet.font(h_mm / CAP * S, bold, 100)


def _tw(font, txt):
    return QFontMetricsF(font).horizontalAdvance(txt)


def _wrap(font, txt, width):
    words, line, out = str(txt).split(), "", []
    for w in words:
        t = (line + " " + w).strip()
        if _tw(font, t) <= width or not line:
            line = t
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out


def _nice(v, options):
    for o in options:
        if v <= o:
            return o
    return options[-1]


GX0, GX1, GY0, GY1 = 62.0, 402.0, 70.0, 164.0


def scales(d):
    """(horizontal scale, vertical scale, datum, main_off) of the section as laid out on the 420 x 297 sheet; printed on A1 they are half of these numbers"""
    st, Hh = d["stations"], d["length"]
    x0 = GX0 + 26.0
    hs = _nice(Hh * 1000.0 / (GX1 - x0 - 30.0), [100, 150, 200, 300, 400, 500, 1000, 2000, 4000])
    levels = [s["ngl"] for s in st] + [d["ngl0"], d["ngl1"]] + [y for _x, y in d["pts"]]
    top = max(levels + ([d["ffl"]] if d["ffl"] is not None else [])) + 0.9
    low_p = min(min(s["il"] for s in st), d["il"](Hh)) if st else d["main_il"]
    datum_f = math.floor((min(low_p, d["main_il"]) - 0.45) / 0.5) * 0.5          # with the main in the picture
    datum_p = math.floor((low_p - 0.45) / 0.5) * 0.5                             # the pipe and the ground only
    room = GY1 - GY0 - 6.0
    opts = [10, 20, 30, 40, 50, 60, 80, 100, 200, 400]
    vs_f = _nice((top - datum_f) * 1000.0 / room, opts)
    vs_p = _nice((top - datum_p) * 1000.0 / room, opts)
    main_off = vs_p < vs_f and d["main_il"] < datum_p + 0.15                      # the main is far below: keep the detail and show it with an arrow
    return hs, (vs_p if main_off else vs_f), (datum_p if main_off else datum_f), main_off


PANEL = QColor(220, 220, 220)
CARD_LINE = QColor(190, 190, 190)
LABEL = QColor(95, 95, 95)
BRAND_RED = QColor(200, 16, 46)
_LOGO = {}


def _logo_image():
    """the MCP logo (black and red, transparent) from the running program; None when it cannot be found"""
    if "img" in _LOGO:
        return _LOGO["img"]
    img = None
    try:
        import base64
        import sys
        for nm_ in ("mot_xa_energy", "__main__"):
            m_ = sys.modules.get(nm_)
            if m_ is not None and hasattr(m_, "LOGO_B64"):
                im_ = QImage.fromData(base64.b64decode(m_.LOGO_B64), "PNG").convertToFormat(QImage.Format.Format_ARGB32)
                for yy in range(im_.height()):
                    for xx in range(im_.width()):
                        c = im_.pixelColor(xx, yy)
                        if c.alpha() and c.red() > 200 and c.green() > 200 and c.blue() > 200:
                            im_.setPixelColor(xx, yy, QColor(28, 31, 35, c.alpha()))
                img = im_
                break
    except Exception:
        img = None
    _LOGO["img"] = img
    return img


def _rr_points(x, y, w, h, r, n=6):
    """the outline of a rectangle with rounded corners"""
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90.0), (x + w - r, y + h - r, 0.0), (x + r, y + h - r, 90.0), (x + r, y + r, 180.0)):
        for k in range(n + 1):
            a = math.radians(a0 + 90.0 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw(p, W, H, S, d, title_lines=(), when=None):
    def P(x, y):
        return QPointF(x * S, y * S)

    def pen(c, w=0.25, style=Qt.PenStyle.SolidLine):
        q = QPen(c, w * S)
        q.setStyle(style)
        q.setCapStyle(Qt.PenCapStyle.FlatCap)
        return q

    def layer(n):
        if hasattr(p, "set_layer"):
            p.set_layer(n)

    def text(x, y, s, h=2.5, bold=False, col=BLACK, align="l"):
        f = _f(S, h, bold)
        p.setFont(f)
        p.setPen(col)
        w = _tw(f, s) / S
        p.drawText(P(x - (w if align == "r" else w / 2 if align == "c" else 0), y), s)

    def line(x1, y1, x2, y2, c=BLACK, w=0.25, style=Qt.PenStyle.SolidLine):
        p.setPen(pen(c, w, style))
        p.drawLine(P(x1, y1), P(x2, y2))

    p.fillRect(0, 0, int(W), int(H), QColor("white"))
    st = d["stations"]
    Hh = d["length"]
    # ---- frame and heading: the same look as the coverage report (grey panel with the logo, red bar, rounded information card)
    layer("TITLE BLOCK")

    def rr(x, y, w, h, r=2.5, stroke=CARD_LINE, fill=None, lw=0.3):
        p.setPen(pen(stroke, lw) if stroke is not None else QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(fill) if fill is not None else QBrush())
        p.drawPolygon(QPolygonF([P(a_, b_) for a_, b_ in _rr_points(x, y, w, h, r)]))
        p.setBrush(QBrush())

    hs0, vs0, datum0, _mo = scales(d)
    rr(8, 8, 404, 281, 4.0, BLACK, None, 0.5)
    nm = ""
    for a, b in title_lines:
        if a == "Stand":
            nm = b
    rr(12, 12, 396, 24, 4.0, CARD_LINE, PANEL, 0.3)
    lg = _logo_image()
    if lg is not None and not hasattr(p, "set_layer"):
        ph = 17.0
        p.drawImage(QRectF(P(17, 15.5), P(17 + ph * lg.width() / float(lg.height()), 15.5 + ph)), lg)
        tx = 17 + ph * lg.width() / float(lg.height()) + 6.0
    else:
        tx = 18.0
    text(tx, 25.0, "Sewer Longitudinal Section", 6.5, True, QColor(17, 17, 17))
    text(tx, 31.5, ("%s  |  %sØ SWP sewer at 1:%d, %.1f m long" % (nm, d["pipe"], round(d["fall"]), Hh)).strip(" |"), 3.1, False, QColor(68, 68, 68))
    text(404, 24.0, "Horizontal 1:%g    Vertical 1:%g" % (hs0 / 2.0, vs0 / 2.0), 3.0, True, QColor(17, 17, 17), "r")
    text(404, 30.5, "Levels in metres.  Datum level %.3f" % datum0, 3.0, False, QColor(68, 68, 68), "r")
    rr(12, 38.5, 396, 2.6, 1.3, None, BRAND_RED)
    info = [(a, b) for a, b in list(title_lines) + [("Sheet", "Sewer long section"), ("Date", (when or datetime.date.today()).strftime("%d/%m/%Y"))]]
    info = [r_ for i_, r_ in enumerate(info) if r_[0] not in [q[0] for q in info[:i_]]]
    half = (len(info) + 1) // 2
    ih = half * 6.2 + 3.0
    rr(12, 44, 396, ih, 4.0, CARD_LINE, None, 0.3)
    for i_, (a, b) in enumerate(info):
        cx_ = 17.0 if i_ < half else 214.0
        cy_ = 50.0 + (i_ % half) * 6.2
        text(cx_, cy_, a, 2.9, False, LABEL)
        text(cx_ + 34.0, cy_, str(b)[:48], 2.9, True)
    # ---- the graph
    gx0, gx1, gy0, gy1 = GX0, GX1, GY0, GY1
    x0 = gx0 + 26.0
    hs, vs, datum, main_off = scales(d)

    def X(xm):
        return x0 + xm * 1000.0 / hs

    def Y(lvl):
        return gy1 - (lvl - datum) * 1000.0 / vs

    layer("SECTION GROUND")
    # level scale on the left and light level lines
    step = 0.5 if (gy1 - gy0) * vs / 1000.0 < 6 else 1.0
    lv_ = datum
    while Y(lv_) >= gy0:
        if lv_ > datum + 1e-9:
            line(gx0, Y(lv_), gx1, Y(lv_), QColor(225, 225, 225), 0.1)
        text(gx0 - 2, Y(lv_) + 0.9, "%.3f" % lv_, 2.2, align="r")
        lv_ += step
    line(gx0, gy1, gx1, gy1, BLACK, 0.5)
    text(gx0 + 2, gy1 - 1.6, "DATUM %.3f" % datum, 2.4, True)
    # chainage ticks under the datum
    tick = _nice(Hh / 8.0, [1, 2, 5, 10, 20, 50])
    c = 0.0
    while c <= Hh + 1e-6:
        line(X(c), gy1, X(c), gy1 + 1.6, BLACK, 0.2)
        text(X(c), gy1 + 5.0, "%g" % c, 2.2, align="c")
        c += tick
    text(gx0 - 2, gy1 + 5.0, "Chainage m", 2.2, align="r")
    # ground line with its little hatch ticks
    pts_mm = [(x0 - 22.0, Y(d["ngl0"]))] + [(X(x), Y(y)) for x, y in d["pts"]] + [(X(Hh) + 14.0, Y(d["ngl1"]))]
    p.setPen(pen(GREEN, 0.35))
    p.drawPolyline(QPolygonF([P(a, b) for a, b in pts_mm]))
    k = pts_mm[0][0]
    while k < pts_mm[-1][0]:
        yy = None
        for (xa, ya), (xb, yb) in zip(pts_mm[:-1], pts_mm[1:]):
            if xa <= k <= xb:
                yy = ya + (yb - ya) * ((k - xa) / (xb - xa) if xb > xa else 0.0)
                break
        if yy is not None:
            line(k, yy, k - 1.2, yy + 1.8, GREEN, 0.15)
        k += 3.0
    if pts_mm[-1][0] + 2.0 + 38.0 <= gx1:                           # beside the end of the ground line, clear of the eye names
        text(pts_mm[-1][0] + 2.0, pts_mm[-1][1] + 0.8, "NATURAL GROUND LEVEL", 2.2, False, GREEN)
    else:
        text(pts_mm[-1][0], pts_mm[-1][1] + 6.0, "NATURAL GROUND LEVEL", 2.2, False, GREEN, "r")
    # the house at the left
    layer("SECTION PIPE")
    top = Y(d["ffl"] if d["ffl"] is not None else d["ngl0"] + 0.5) - (2.0 if d["ffl"] is None else 0.0)
    top = max(top, gy0 + 3.0)
    p.setPen(pen(BLACK, 0.35))
    p.drawRect(QRectF(P(x0 - 22.0, top), P(x0 - 2.0, Y(d["ngl0"]) + 3.0)))
    text(x0 - 12.0, (top + Y(d["ngl0"])) / 2.0, "HOUSE", 2.6, True, BLACK, "c")
    if d["ffl"] is not None:
        line(x0 - 22.0, Y(d["ffl"]), x0 + 6.0, Y(d["ffl"]), BLACK, 0.2, Qt.PenStyle.DashLine)
        text(x0 - 21.0, Y(d["ffl"]) - 1.0, "FFL %.3f" % d["ffl"], 2.0)
    # the pipe: invert and crown
    ilh, ile = d["il"](0.0), d["il"](Hh)
    lo_ = bool(d.get("lines_only"))                              # brown lines only: no pipe width
    od_mm = 0.0 if lo_ else max(d["od"] * 1000.0 / vs, 0.8)
    bounds = [x_ for x_, _y in d["segs"]] + [Hh]
    for k_ in range(len(bounds) - 1):
        xa_, xb_ = bounds[k_], bounds[k_ + 1]
        ya_ = d["il"](xa_)
        if k_ + 1 < len(bounds) - 1:                             # an upper run ends at the drop, before the foot of the steep part
            xb_ = next((xd_ for xd_, _a, _b in d["drops"] if abs(xd_ + d["drop_lean"].get(xd_, 0.0) - xb_) < 1e-6), xb_)
            yb_ = d["il_in"](xb_)
        else:
            yb_ = d["il"](xb_)
        for off_, w_ in (((0.0, 0.8),) if lo_ else ((0.0, 0.6), (od_mm, 0.3))):
            line(X(xa_), Y(ya_) - off_, X(xb_), Y(yb_) - off_, BROWN, w_)
    for xa_, xb_ in d.get("bad") or []:                          # where the cover is too low: a red band along the pipe
        n_ = max(2, int((xb_ - xa_) / 0.5) + 1)
        for k_ in range(n_):
            x1_, x2_ = xa_ + (xb_ - xa_) * k_ / n_, xa_ + (xb_ - xa_) * (k_ + 1) / n_
            line(X(x1_), Y(d["il"](x1_)) - od_mm / 2.0, X(x2_), Y(d["il"](x2_)) - od_mm / 2.0, QColor(216, 19, 43, 150), 2.4)
        text((X(xa_) + X(xb_)) / 2.0, Y(d["il"]((xa_ + xb_) / 2.0)) + 4.0, "cover too low", 2.0, True, QColor(216, 19, 43), "c")
    p.setPen(pen(BROWN, 0.3))
    if not lo_:
        p.drawLine(P(X(0.0), Y(ilh)), P(X(0.0), Y(ilh) - od_mm))
    for xd_, yin_, yout_ in d["drops"]:                           # the drop: a steep part from the upper pipe down to the lower pipe
        xf_ = xd_ + d["drop_lean"].get(xd_, 0.0)
        for off_ in ((0.0,) if lo_ else (0.0, od_mm)):
            line(X(xd_), Y(yin_) - off_, X(xf_), Y(yout_) - off_, BROWN, (0.8 if lo_ else 0.6) if off_ == 0 else 0.3)
        text((X(xd_) + X(xf_)) / 2.0 + 3.0, (Y(yin_) + Y(yout_)) / 2.0 + 0.8, "drop %d mm" % round((yin_ - yout_) * 1000), 2.2, True, BROWN)
    # eyes
    for i, s in enumerate(st):
        if s["kind"] == "MAIN":
            continue
        xe, yg, yc = X(s["x"]), Y(s["ngl"]), Y(s.get("top", s["il"])) - od_mm
        w = 1.6
        sty = Qt.PenStyle.SolidLine if s["kind"] == "IE" else Qt.PenStyle.DashLine
        lean = (yc - yg) if s["kind"] == "RE" else 0.0              # a rodding eye leans at 45 degrees (on the paper) up the line, back towards the house
        if lo_:                                                     # one line for the eye
            line(xe, yc, xe - lean, yg, BROWN, 0.5, sty)
            line(xe - lean - 1.2, yg, xe - lean + 1.2, yg, BROWN, 0.5)
        else:
            line(xe - w, yc, xe - w - lean, yg, BROWN, 0.35, sty)
            line(xe + w, yc, xe + w - lean, yg, BROWN, 0.35, sty)
            line(xe - w - lean - 0.8, yg, xe + w - lean + 0.8, yg, BROWN, 0.5)
        ly = yg - 5.0 - (i % 4) * 4.6
        line(xe - lean, yg - 0.5, xe - lean, ly + 0.6, GREY, 0.12)
        text(xe - lean, ly, s["name"], 2.3, True, BROWN, "c")
    # the main sewer at the right
    r = 3.2
    if main_off:
        line(X(Hh), Y(ile), X(Hh), gy1 - 4.0, BROWN, 0.3, Qt.PenStyle.DashLine)
        p.setPen(pen(BROWN, 0.3))
        p.drawPolygon(QPolygonF([P(X(Hh), gy1 - 1.0), P(X(Hh) - 1.2, gy1 - 4.0), P(X(Hh) + 1.2, gy1 - 4.0)]))
        text(X(Hh) + 3.0, gy1 - 8.0, "TO THE MAIN SEWER  IL %.3f%s" % (d["main_il"], "" if d["main_typed"] else " (from depth)"), 2.4, True)
        text(X(Hh) + 3.0, gy1 - 4.5, "the pipe arrives %d mm above the main's invert (below this section)" % round(d["drop"] * 1000), 2.2)
    else:
        ym = Y(d["main_il"])
        p.setPen(pen(BLACK, 0.4))
        p.drawEllipse(P(X(Hh), ym - r), r * S, r * S)
        text(X(Hh) + r + 2.0, ym - r - 1.0, "MAIN SEWER", 2.4, True)
        text(X(Hh) + r + 2.0, ym - r + 2.0, "IL %.3f%s" % (d["main_il"], "" if d["main_typed"] else " (from depth)"), 2.2)
        if d["drop"] > 0.005:
            line(X(Hh), Y(ile), X(Hh), ym - 2 * r, BROWN, 0.25, Qt.PenStyle.DashLine)
            text(X(Hh) + 1.5, (Y(ile) + ym - 2 * r) / 2.0 + 0.8, "drop %d mm" % round(d["drop"] * 1000), 2.0, False, BROWN)
    # gradient label under the pipe, and the invert levels at both ends
    mid = Hh / 2.0
    text(X(mid), Y(d["il"](mid)) + 5.0, "%sØ uPVC SWP  1:%d  (%.2f %%)" % (d["pipe"], round(d["fall"]), 100.0 / d["fall"]), 2.6, True, BROWN, "c")
    text(X(0.0) + 1.0, Y(ilh) + 3.6, "IL %.3f" % ilh, 2.2, False, BROWN)
    text(X(Hh) - 1.5, Y(ile) + 3.6, "IL %.3f" % ile, 2.2, False, BROWN, "r")
    # ---- the table of stations
    layer("SECTION TABLE")
    ty = GY1 + 17.0
    cols = [("Eye", 16), ("What", 68), ("Chainage m", 28), ("Ground level", 34), ("Invert level", 34), ("Depth mm", 28), ("Cover mm", 28), ("Fall to the next", 46)]
    n = len(st)
    rh = min(6.0, 54.0 / (n + 1))
    xx = 14.0
    xs = []
    for _t, w in cols:
        xs.append(xx)
        xx += w
    xend = xx
    p.setPen(QPen(Qt.PenStyle.NoPen))
    p.setBrush(QBrush(QColor(236, 236, 236)))
    p.drawPolygon(QPolygonF([P(a_, b_) for a_, b_ in _rr_points(14, ty, xend - 14, rh, 2.5)]))
    p.setBrush(QBrush())
    for (t, w), x in zip(cols, xs):
        text(x + 1.5, ty + rh - 1.7, t, 2.4, True)
    for i, s in enumerate(st):
        y = ty + rh * (i + 1)
        nxt = st[i + 1] if i + 1 < n else None
        row = [s["name"], s["desc"], "%.2f" % s["x"], "%.3f" % s["ngl"], "%.3f" % s["il"], "%d" % round(s["depth"] * 1000),
               "%d" % round(s["cover"] * 1000), ("1:%d over %.2f m" % (round(d["fall"]), nxt["x"] - s["x"])) if nxt and nxt["x"] - s["x"] > 0.005 else "-"]
        for (t, w), x, v in zip(cols, xs, row):
            low_cover = t == "Cover mm" and s["cover"] < 0.3 - 1e-6
            text(x + 1.5, y + rh - 1.7, v, 2.4, False, RED if low_cover else BLACK)
        if i + 1 < n:
            line(14.5, y + rh, xend - 0.5, y + rh, QColor(215, 215, 215), 0.12)
    for x in xs[1:]:
        line(x, ty + 1.0, x, ty + rh * (n + 1) - 1.0, QColor(215, 215, 215), 0.12)
    rr(14, ty, xend - 14, rh * (n + 1), 2.5, CARD_LINE, None, 0.3)
    # ---- checks and notes, side by side in their own rounded cards
    layer("TITLE BLOCK")
    by = ty + rh * (n + 1) + 6.0
    f = _f(S, 2.4)
    cx0, cw = 14.0, 196.0
    text(cx0 + 3, by + 4.5, "CHECKS", 2.8, True)
    y = by + 10.0
    for t, ok in d["checks"]:
        tag = "OK" if ok else "CHECK" if ok is None else "NOT MET"
        col = BLACK if ok else RED
        text(cx0 + 3, y, tag, 2.4, True, col)
        for ln in _wrap(f, t, (cw - 36) * S)[:2]:
            text(cx0 + 22, y, ln, 2.4, False, col)
            y += 4.0
        y += 0.6
    y1 = y
    nx0, nw = 216.0, 192.0
    text(nx0 + 3, by + 4.5, "NOTES", 2.8, True)
    y = by + 10.0
    notes = []
    if d["assumed"]:
        notes.append("GROUND LEVELS ARE ASSUMED (the ground at the house is taken as %.3f). Type the surveyed levels in the sewer section settings before submitting." % d["ngl0"])
    else:
        notes.append("Natural ground levels are as given by the designer: confirm them against the land surveyor's levels before the section is submitted.")
    notes += ["The invert level at the house is the ground level there minus the minimum depth, falling at 1:%d to the main. The level of the main and the connection are to be confirmed against the council's records and on site." % round(d["fall"]),
              "Bedding, backfill, testing and the manholes or eyes as required by the local authority and SANS 10252-2. Inspection eyes at every change of direction and at the limits shown above.",
              "A1 sheet. Horizontal scale 1:%g, vertical scale 1:%g (the vertical is drawn larger so the fall can be read)." % (hs / 2.0, vs / 2.0)]
    for i, t in enumerate(notes):
        lines = _wrap(f, t, (nw - 14) * S)
        for j, ln in enumerate(lines):
            if j == 0:
                text(nx0 + 3, y, "%d." % (i + 1), 2.4)
            text(nx0 + 9, y, ln, 2.4, False, RED if (i == 0 and d["assumed"]) else BLACK)
            y += 4.0
        y += 0.6
    bot = max(y1, y) + 1.5
    rr(cx0, by, cw, bot - by, 3.0, CARD_LINE, None, 0.3)
    rr(nx0, by, nw, bot - by, 3.0, CARD_LINE, None, 0.3)
    layer(None)


# ---------------------------------------------------------------- outputs
def write_pdf(path, d, title_lines=(), when=None):
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A1))
    w.setPageOrientation(QPageLayout.Orientation.Landscape)
    w.setResolution(150)
    p = QPainter(w)
    S = w.width() / 420.0
    draw(p, w.width(), w.height(), S, d, title_lines, when)
    p.end()
    return path


def render_image(d, title_lines=(), width=2100, when=None):
    from PySide6.QtGui import QImage, QPainter
    S = width / 420.0
    img = QImage(int(width), int(297 * S), QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    draw(p, img.width(), img.height(), S, d, title_lines, when)
    p.end()
    return img


def write_dxf(path, d, title_lines=(), when=None):
    import site_export
    doc = site_export.new_doc()
    p = site_export.DxfPainter(doc, doc.modelspace())
    S = 200.0                                    # the sheet is A1 (twice the 420 x 297 layout) drawn at 1:100: 1 drawing unit = 1 mm
    draw(p, 420.0 * S, 297.0 * S, S, d, title_lines, when)
    doc.saveas(path)
    return path
