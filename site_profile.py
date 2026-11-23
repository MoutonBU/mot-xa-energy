"""Sewer long section (longitudinal section) for the council, worked out from the sewer placed on the site plan.

build(state, res)   -> the numbers: a station every eye and the connection, with chainage, natural ground level, invert level, depth, cover and fall
draw(p, W, H, S, data, title_lines)  -> the sheet (A3 landscape, 420 x 297 mm), drawn with a QPainter or the DxfPainter of site_export
write_pdf / write_dxf / render_image -> the three outputs

Levels: the engine only knows depths below the ground. The ground levels (at the house, at the main, optional spot levels along the run) and the main's
invert level are typed in by the designer (state["levels"]); when they are not typed the sheet says the levels are assumed. The invert level at the
house is the ground level there minus the minimum depth, and falls at the pipe's fall (1 : n) all the way to the main. All sizes below are paper millimetres
(S = drawing units per paper millimetre, so the same code makes the PDF and the 1:200 DXF)."""
import datetime
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPen, QPolygonF

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


def build(state, res):
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

    def ngl(x):
        x = max(0.0, min(Hh, x))
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            if xa <= x <= xb:
                return ya + (yb - ya) * ((x - xa) / (xb - xa) if xb > xa else 0.0)
        return ngl1

    il_head = ngl0 - D0

    def il(x):
        return il_head - x / fall

    conn_depth = float(par.get("conn_depth", 1.5))
    main_il_typed = _set(mil)
    main_il = float(mil) if main_il_typed else ngl1 - conn_depth
    nodes = []
    for n in sw["nodes"]:
        d = n.get("dist")
        x = (Hh - d) if d is not None else (Hh - Lp + n["chainage"])
        nodes.append((max(0.0, min(Hh, x)), n))
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
        st.append({"name": name, "kind": k, "desc": desc, "x": round(x, 2), "ngl": g, "il": i, "depth": g - i, "cover": g - i - od})
    covers = [ngl(k / 10.0 * Hh) - il(k / 10.0 * Hh) - od for k in range(0, 11)]
    covers += [s["cover"] for s in st]
    min_cover = min(covers) if covers else 0.0
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
                   else "Soil cover is less than %d mm (lowest %d mm): lay the pipe deeper." % (round(mc * 1000), round(min_cover * 1000)), min_cover >= mc - 1e-6))
    if drop >= -1e-6:
        checks.append(("The pipe reaches the main %d mm above its invert level (%s)." % (round(drop * 1000), "typed" if main_il_typed else "taken as %d mm below the ground at the main" % round(conn_depth * 1000)), True))
    else:
        checks.append(("The pipe arrives %d mm BELOW the invert of the main: it cannot drain to the main by gravity. Lay it shallower or flatter, or check the main's level." % round(-drop * 1000), False))
    gaps = [b["x"] - a["x"] for a, b in zip(st[:-1], st[1:])]
    mx = float(par.get("max_ie", 25.0))
    if gaps:
        checks.append(("Eyes are at most %.1f m apart (limit %.0f m)." % (max(gaps), mx) if max(gaps) <= mx + 1e-6 else "Eyes are %.1f m apart: more than %.0f m." % (max(gaps), mx), max(gaps) <= mx + 1e-6))
    return {"stations": st, "length": Hh, "fall": fall, "od": od, "pipe": str(par.get("sewer_pipe", "110")), "ngl": ngl, "il": il, "ngl0": ngl0, "ngl1": ngl1,
            "pts": pts, "main_il": main_il, "main_typed": main_il_typed, "drop": drop, "assumed": assumed, "min_cover": min_cover, "checks": checks,
            "ffl": float(lv["ffl"]) if _set(lv.get("ffl")) else None, "note": sw.get("note", "")}


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
    # ---- frame and heading
    layer("TITLE BLOCK")
    line(8, 8, 412, 8, BLACK, 0.5)
    line(412, 8, 412, 289, BLACK, 0.5)
    line(412, 289, 8, 289, BLACK, 0.5)
    line(8, 289, 8, 8, BLACK, 0.5)
    nm = ""
    for a, b in title_lines:
        if a == "Stand":
            nm = b
    text(14, 19, "SEWER LONGITUDINAL SECTION", 5.0, True)
    text(14, 26, ("%s  -  %sØ SWP sewer at 1:%d, %.1f m long" % (nm, d["pipe"], round(d["fall"]), Hh)).strip(" -"), 3.0)
    # ---- the graph
    gx0, gx1, gy0, gy1 = 62.0, 402.0, 40.0, 128.0
    x0 = gx0 + 26.0
    hs = _nice(Hh * 1000.0 / (gx1 - x0 - 30.0), [50, 100, 200, 250, 500, 1000, 2000])
    levels = [s["ngl"] for s in st] + [d["ngl0"], d["ngl1"]] + [y for _x, y in d["pts"]]
    top = max(levels + ([d["ffl"]] if d["ffl"] is not None else [])) + 0.9
    low_p = min(s["il"] for s in st) if st else d["main_il"]
    datum_f = math.floor((min(low_p, d["main_il"]) - 0.45) / 0.5) * 0.5          # with the main in the picture
    datum_p = math.floor((low_p - 0.45) / 0.5) * 0.5                             # the pipe and the ground only
    room = gy1 - gy0 - 6.0
    vs_f = _nice((top - datum_f) * 1000.0 / room, [5, 10, 20, 25, 30, 40, 50, 100, 200])
    vs_p = _nice((top - datum_p) * 1000.0 / room, [5, 10, 20, 25, 30, 40, 50, 100, 200])
    main_off = vs_p < vs_f and d["main_il"] < datum_p + 0.15                      # the main is far below: keep the detail and show it with an arrow
    datum, vs = (datum_p, vs_p) if main_off else (datum_f, vs_f)

    def X(xm):
        return x0 + xm * 1000.0 / hs

    def Y(lvl):
        return gy1 - (lvl - datum) * 1000.0 / vs

    text(412 - 6, 19, "Horizontal 1:%d    Vertical 1:%d" % (hs, vs), 3.0, True, align="r")
    text(412 - 6, 26, "Levels in metres.  Datum level %.3f" % datum, 3.0, align="r")
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
    text(pts_mm[-1][0], pts_mm[-1][1] - 9.0, "NATURAL GROUND LEVEL", 2.2, False, GREEN, "r")
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
    od_mm = max(d["od"] * 1000.0 / vs, 0.8)
    p.setPen(pen(BROWN, 0.6))
    p.drawLine(P(X(0.0), Y(ilh)), P(X(Hh), Y(ile)))
    p.setPen(pen(BROWN, 0.3))
    p.drawLine(P(X(0.0), Y(ilh) - od_mm), P(X(Hh), Y(ile) - od_mm))
    p.drawLine(P(X(0.0), Y(ilh)), P(X(0.0), Y(ilh) - od_mm))
    # eyes
    for i, s in enumerate(st):
        if s["kind"] == "MAIN":
            continue
        xe, yg, yc = X(s["x"]), Y(s["ngl"]), Y(s["il"]) - od_mm
        w = 1.6
        sty = Qt.PenStyle.SolidLine if s["kind"] == "IE" else Qt.PenStyle.DashLine
        lean = (yc - yg) if s["kind"] == "RE" else 0.0              # a rodding eye leans at 45 degrees (on the paper) up the line, back towards the house
        line(xe - w, yc, xe - w - lean, yg, BROWN, 0.35, sty)
        line(xe + w, yc, xe + w - lean, yg, BROWN, 0.35, sty)
        line(xe - w - lean - 0.8, yg, xe + w - lean + 0.8, yg, BROWN, 0.5)
        ly = yg - 5.0 - (i % 3) * 3.8
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
    ty = 142.0
    cols = [("Eye", 16), ("What", 68), ("Chainage m", 28), ("Ground level", 34), ("Invert level", 34), ("Depth mm", 28), ("Cover mm", 28), ("Fall to the next", 46)]
    n = len(st)
    rh = min(6.0, 66.0 / (n + 1))
    xx = 14.0
    xs = []
    for _t, w in cols:
        xs.append(xx)
        xx += w
    xend = xx
    line(14, ty, xend, ty, BLACK, 0.4)
    for (t, w), x in zip(cols, xs):
        text(x + 1.5, ty + rh - 1.7, t, 2.4, True)
    line(14, ty + rh, xend, ty + rh, BLACK, 0.3)
    for i, s in enumerate(st):
        y = ty + rh * (i + 1)
        nxt = st[i + 1] if i + 1 < n else None
        row = [s["name"], s["desc"], "%.2f" % s["x"], "%.3f" % s["ngl"], "%.3f" % s["il"], "%d" % round(s["depth"] * 1000),
               "%d" % round(s["cover"] * 1000), ("1:%d over %.2f m" % (round(d["fall"]), nxt["x"] - s["x"])) if nxt and nxt["x"] - s["x"] > 0.005 else "-"]
        for (t, w), x, v in zip(cols, xs, row):
            low_cover = t == "Cover mm" and s["cover"] < 0.3 - 1e-6
            text(x + 1.5, y + rh - 1.7, v, 2.4, False, RED if low_cover else BLACK)
        line(14, y + rh, xend, y + rh, QColor(200, 200, 200), 0.15)
    for x in xs + [xend]:
        line(x, ty, x, ty + rh * (n + 1), QColor(120, 120, 120), 0.15)
    # ---- checks, notes and the title block
    layer("TITLE BLOCK")
    by = ty + rh * (n + 1) + 8.0
    text(14, by, "CHECKS", 2.8, True)
    f = _f(S, 2.4)
    y = by + 5.0
    for t, ok in d["checks"]:
        tag = "OK" if ok else "CHECK" if ok is None else "NOT MET"
        col = BLACK if ok else RED
        text(14, y, tag, 2.4, True, col)
        for ln in _wrap(f, t, (238 - 36) * S)[:2]:
            text(36, y, ln, 2.4, False, col)
            y += 4.0
        y += 0.6
    y += 3.0
    text(14, y, "NOTES", 2.8, True)
    y += 5.0
    notes = []
    if d["assumed"]:
        notes.append("GROUND LEVELS ARE ASSUMED (the ground at the house is taken as %.3f). Type the surveyed levels in the sewer section settings before submitting." % d["ngl0"])
    else:
        notes.append("Natural ground levels are as given by the designer: confirm them against the land surveyor's levels before the section is submitted.")
    notes += ["The invert level at the house is the ground level there minus the minimum depth, falling at 1:%d to the main. The level of the main and the connection are to be confirmed against the council's records and on site." % round(d["fall"]),
              "Bedding, backfill, testing and the manholes or eyes as required by the local authority and SANS 10252-2. Inspection eyes at every change of direction and at the limits shown above.",
              "Horizontal scale 1:%d, vertical scale 1:%d (the vertical is drawn larger so the fall can be read)." % (hs, vs)]
    for i, t in enumerate(notes):
        lines = _wrap(f, t, (238 - 28) * S)
        for j, ln in enumerate(lines):
            if j == 0:
                text(14, y, "%d." % (i + 1), 2.4)
            text(21, y, ln, 2.4, False, RED if (i == 0 and d["assumed"]) else BLACK)
            y += 4.0
        y += 0.6
    # title block
    tx0, ty1 = 252.0, 285.0
    tx1 = 406.0
    rows = list(title_lines) + [("Sheet", "Sewer long section"), ("Date", (when or datetime.date.today()).strftime("%d/%m/%Y"))]
    rows = [r for i, r in enumerate(rows) if r[0] not in [q[0] for q in rows[:i]]]
    step = 6.5
    ty0 = ty1 - (len(rows) * step + 5.0)
    p.setPen(pen(BLACK, 0.4))
    p.drawRect(QRectF(P(tx0, ty0), P(tx1, ty1)))
    for i, (a, b) in enumerate(rows):
        yy = ty0 + 5.0 + i * step
        text(tx0 + 3.0, yy, a + ":", 2.4, True)
        text(tx0 + 30.0, yy, str(b)[:46], 2.4)
        line(tx0, yy + 1.6, tx1, yy + 1.6, QColor(210, 210, 210), 0.12)
    layer(None)


# ---------------------------------------------------------------- outputs
def write_pdf(path, d, title_lines=(), when=None):
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
    w.setPageOrientation(QPageLayout.Orientation.Landscape)
    w.setResolution(300)
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
    S = 200.0                                    # drawn at 1:200 of paper, like the site plan: 1 drawing unit = 1 mm
    draw(p, 420.0 * S, 297.0 * S, S, d, title_lines, when)
    doc.saveas(path)
    return path
