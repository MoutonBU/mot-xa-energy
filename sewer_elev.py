"""Sewer elevation for the council, from floor plan and elevation screenshots and the sewer placed on the site plan.

read_screenshot / read_levels        -> Claude reads a floor plan screenshot (the fixtures) and an elevation screenshot (the floor levels)
model_from_shots(shots, house)       -> the fixtures and floors as one model, scaled to the house on the site plan
build(state, res, model, ...)        -> the model turned onto the stand to match the house on the site plan, a view along the sewer, the stacks, and the sewer levels
draw(p, W, H, S, data, title_lines)  -> the A3 sheet (paper mm; S = drawing units per paper mm), for a QPainter or the DxfPainter of site_export
write_pdf / write_dxf / render_image -> the outputs

How the plan is turned: the outline of the building on the plan screenshot is laid over the house on the site plan (same shape, same middle). A rectangle has
two fits (the way round and the other way round), a square four; the program takes the fit that puts the wet fixtures nearest the sewer, and the page
can turn it by 180 or 90 degrees if that is not the way the house really faces.
How the levels follow the fixtures: every stack (a vertical pipe collecting the fixtures along the same stretch of wall) must leave its lowest fixture with
a fall of 1:40 and clear the slab, so the sewer invert under the stack can be no higher than that. The invert at the house is the shallowest the
site settings allow, or deeper if a stack needs it, and the pipe then falls 1:n to the main."""
import datetime
import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF

import site_engine as se
import site_profile as sp

BROWN = QColor(200, 96, 40)
GREEN = QColor(0, 200, 0)
RED = QColor(220, 0, 0)
BLACK = QColor(0, 0, 0)
GREY = QColor(120, 120, 120)

# fixture kinds -> the letters the council drawings use, and the height of the waste outlet above the floor (m)
KINDS = {"WC": ("WC", 0.15), "WHB": ("WHB", 0.55), "SH": ("SH", 0.0), "B": ("B", 0.0), "S": ("S", 0.55), "WM": ("WM", 0.90), "DW": ("dw", 0.55), "G": ("G", 0.0)}
PATTERNS = [
    ("WC", r"\bwc\b|water.?closet|toilet|\bpan\b|urinal|cistern|\bloo\b"),
    ("WHB", r"basin|\bwhb\b|wash.?hand|lavatory|hand.?wash|bidet"),
    ("SH", r"shower"),
    ("B", r"\bbath|\btub\b"),
    ("WM", r"washing.?machine|\bwm\b|laundry"),
    ("DW", r"dish.?washer|\bdw\b"),
    ("S", r"\bsink|scullery"),
    ("G", r"gully|floor.?trap|floor.?drain"),
]
PREDEFINED = {"TOILETPAN": "WC", "WCSEAT": "WC", "CISTERN": "WC", "URINAL": "WC", "WASHHANDBASIN": "WHB", "BIDET": "WHB", "SHOWER": "SH", "BATH": "B", "SINK": "S",
              "WASHINGMACHINE": "WM", "DISHWASHER": "DW", "FLOORTRAP": "G", "GULLYTRAP": "G", "FLOORWASTE": "G"}
CLASSES = ["IfcSanitaryTerminal", "IfcWasteTerminal", "IfcFlowTerminal", "IfcElectricAppliance", "IfcFurniture", "IfcFurnishingElement", "IfcBuildingElementProxy",
           "IfcDistributionFlowElement"]
STACK_GAP = 2.5          # m: fixtures further apart than this along the wall do not share a stack
BRANCH_FALL = 40.0       # waste pipes from the fixtures fall 1:40
CLEAR = 0.10             # trap, bend and bedding below the lowest outlet (m)
SLAB = 0.30              # the drain runs this far below the lowest floor (slab, screed and bedding, m)


def classify(text, predefined=""):
    pre = PREDEFINED.get(str(predefined or "").upper().replace(" ", ""))
    if pre:
        return pre
    t = (text or "").lower()
    for k, rx in PATTERNS:
        if re.search(rx, t):
            return k
    return None


# ---------------------------------------------------------------- turning the model onto the stand
def _poly(pts):
    from shapely.geometry import Polygon
    return Polygon(pts).buffer(0)


def _long_axis(poly):
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    L1, L2 = math.hypot(*e1), math.hypot(*e2)
    e, a, b = (e1, L1, L2) if L1 >= L2 else (e2, L2, L1)
    return math.atan2(e[1], e[0]), a, b


def _xform(pt, c_from, c_to, th):
    ca, sa = math.cos(th), math.sin(th)
    x, y = pt[0] - c_from[0], pt[1] - c_from[1]
    return (c_to[0] + x * ca - y * sa, c_to[1] + x * sa + y * ca)


def fits(model, house_pts):
    """the turns (radians) that lay the model's outline over the house, best first: [(theta, overlap 0..1)]"""
    fp = model.get("footprint")
    if not fp:
        raise ValueError("The plan has no building outline to take.")
    P, Hh = _poly(fp), _poly(house_pts)
    a_i, L_i, W_i = _long_axis(P)
    a_h, L_h, W_h = _long_axis(Hh)
    base = a_h - a_i
    cands = [base, base + math.pi]
    if L_i < W_i * 1.15 or L_h < W_h * 1.15:
        cands += [base + math.pi / 2, base + 3 * math.pi / 2]
    ci, ch = (P.centroid.x, P.centroid.y), (Hh.centroid.x, Hh.centroid.y)
    res = []
    for th in cands:
        T = _poly([_xform(q, ci, ch, th) for q in fp])
        inter = T.intersection(Hh).area
        uni = T.union(Hh).area or 1.0
        res.append((th, inter / uni))
    res.sort(key=lambda t: -t[1])
    return res, ci, ch


def _seg_pt(a, b, p):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return (a[0] + t * dx, a[1] + t * dy), t


def _near_path(path, p):
    best = None
    for a, b in zip(path[:-1], path[1:]):
        q, _t = _seg_pt(a, b, p)
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if best is None or d < best[0]:
            best = (d, q, a, b)
    return best


def compass(vx, vy, north_deg):
    """the compass point of a direction in stand coordinates (x east, y up on the sheet) when the north arrow is turned `north_deg` clockwise"""
    ang = math.degrees(math.atan2(vx, vy)) - float(north_deg or 0.0)          # clockwise from the sheet's up, minus the turn of north
    names = ["North", "North East", "East", "South East", "South", "South West", "West", "North West"]
    return names[int(((ang % 360) + 22.5) // 45) % 8]


def _fmt_level(v):
    s = "%d" % round(v * 1000)
    out = ""
    while len(s) > 3:
        out = " " + s[-3:] + out
        s = s[:-3]
    return "+" + s + out


def build(state, res, model, turn=0, flip=False, title=None):
    sw = (res or {}).get("sewer")
    if not sw or not sw.get("path"):
        raise ValueError("There is no sewer on the site plan yet.")
    if not model["fixtures"]:
        raise ValueError("No WC, basin, shower, bath, sink or washing machine was found on the screenshots.")
    house = se.house_poly(state["house"])
    cands, ci, ch = fits(model, house)
    path = [tuple(q) for q in sw["path"]]

    def mean_dist(th):
        ds = []
        for f in model["fixtures"]:
            q = _xform((f["x"], f["y"]), ci, ch, th)
            ds.append(_near_path(path, q)[0])
        return sum(ds) / len(ds)
    near = [c for c in cands if c[1] >= cands[0][1] - 0.08]
    near.sort(key=lambda c: mean_dist(c[0]))
    rest = [c for c in cands if c not in near]
    ordered = near + rest
    th, ov = ordered[int(turn) % len(ordered)]
    fx = []
    for f in model["fixtures"]:
        q = _xform((f["x"], f["y"]), ci, ch, th)
        fx.append(dict(f, sx=q[0], sy=q[1]))
    gx = sum(f["sx"] for f in fx) / len(fx)
    gy = sum(f["sy"] for f in fx) / len(fx)
    d0, q0, a0, b0 = _near_path(path, (gx, gy))
    sx_, sy_ = b0[0] - a0[0], b0[1] - a0[1]
    sl = math.hypot(sx_, sy_) or 1.0
    sx_, sy_ = sx_ / sl, sy_ / sl
    gdx, gdy = gx - q0[0], gy - q0[1]
    gl_ = math.hypot(gdx, gdy) or 1.0
    if abs(sx_ * gdy - sy_ * gdx) / gl_ < 0.5:         # the pipe heads straight at the house: look along the long wall on the side of the main
        ang, _L, _W = _long_axis(_poly(house))
        sx_, sy_ = math.cos(ang), math.sin(ang)
        nx, ny = (-sy_, sx_)
        mx_, my_ = path[-1] if math.hypot(path[-1][0] - gx, path[-1][1] - gy) > math.hypot(path[0][0] - gx, path[0][1] - gy) else path[0]
        if nx * (gx - mx_) + ny * (gy - my_) < 0:
            nx, ny = -nx, -ny
    else:
        nx, ny = (-sy_, sx_)
        if nx * gdx + ny * gdy < 0:
            nx, ny = -nx, -ny                       # looking from the sewer towards the house
    if flip:
        nx, ny = -nx, -ny
    tx, ty = ny, -nx                                # to the right as the viewer sees it
    origin = q0

    def U(p):
        return (p[0] - origin[0]) * tx + (p[1] - origin[1]) * ty
    north = float((state.get("sheet") or {}).get("north", 0.0) or 0.0)
    side = compass(-nx, -ny, north)                  # the side of the house the viewer stands on

    # ---- levels: the site levels, with the storeys of the model on the same datum
    storeys = model["storeys"]
    if not storeys:
        raise ValueError("There are no floors: add a floor plan screenshot.")
    gi = next((i for i, s in enumerate(storeys) if re.search(r"ground|\b0\b|gf|grond|^g$", s["name"].lower())), None)
    if gi is None:
        gi = min((i for i, s in enumerate(storeys) if any(f["storey"] == i for f in fx)), key=lambda i: storeys[i]["z"], default=0)
    g_elev = storeys[gi]["elev"]
    lv = dict(state.get("levels") or {})
    typed_ffl = sp._set(lv.get("ffl"))
    typed_ngl = sp._set(lv.get("ngl_head")) or sp._set(lv.get("ngl_main"))
    assumed = not typed_ngl
    if typed_ffl:
        ffl_abs = float(lv["ffl"])
    elif typed_ngl:
        ffl_abs = float(lv.get("ngl_head") if sp._set(lv.get("ngl_head")) else lv.get("ngl_main")) + 0.15      # floor assumed 150 mm above the ground
    else:
        ffl_abs = g_elev if g_elev > 1.0 else sp.ASSUMED_DATUM + 0.15
    shift = ffl_abs - g_elev
    if not typed_ngl:
        lv["ngl_head"] = ffl_abs - 0.15                                      # ground taken as 150 mm under the floor
        lv["ngl_main"] = ffl_abs - 0.15
    st2 = dict(state, levels=lv)
    prof = sp.build(st2, res)
    Hh, fall = prof["length"], prof["fall"]
    Lp = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path[:-1], path[1:]))
    xs, us, c = [], [], 0.0
    for i, q in enumerate(path):
        if i:
            c += math.hypot(q[0] - path[i - 1][0], q[1] - path[i - 1][1])
        xs.append(Hh - Lp + c)
        us.append(U(q))

    def u_of_x(x):
        x = max(xs[0], min(xs[-1], x))
        for k in range(len(xs) - 1):
            if xs[k] <= x <= xs[k + 1]:
                t = 0.0 if xs[k + 1] == xs[k] else (x - xs[k]) / (xs[k + 1] - xs[k])
                return us[k] + (us[k + 1] - us[k]) * t
        return us[-1]

    def x_of_u(u):
        best = None
        for k in range(len(us) - 1):
            lo, hi = min(us[k], us[k + 1]), max(us[k], us[k + 1])
            d = 0.0 if lo <= u <= hi else min(abs(u - lo), abs(u - hi))
            if best is None or d < best[0]:
                t = 0.0 if us[k + 1] == us[k] else max(0.0, min(1.0, (u - us[k]) / (us[k + 1] - us[k])))
                best = (d, xs[k] + (xs[k + 1] - xs[k]) * t)
        return best[1]

    for f in fx:
        f["u"] = U((f["sx"], f["sy"]))
        s = storeys[f["storey"]] if f["storey"] is not None else storeys[gi]
        f["floor"] = s["elev"] + shift
        f["out"] = f["floor"] + KINDS[f["kind"]][1]
        f["storey_name"] = s["name"]
    # ---- stacks: fixtures along the same stretch of wall share one
    order = sorted(range(len(fx)), key=lambda i: fx[i]["u"])
    groups, cur = [], []
    for i in order:
        if cur and fx[i]["u"] - fx[cur[-1]]["u"] > STACK_GAP:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    stacks = []
    for g in groups:
        fs = [fx[i] for i in g]
        wc = [f for f in fs if f["kind"] == "WC"]
        base_f = min(fs, key=lambda f: f["floor"])
        ref = [f for f in wc if abs(f["floor"] - base_f["floor"]) < 0.05] or [f for f in fs if abs(f["floor"] - base_f["floor"]) < 0.05]
        u = sum(f["u"] for f in ref) / len(ref)
        low = min(f["out"] for f in fs)
        run = max(abs(f["u"] - u) for f in fs)
        il_max = min(low - run / BRANCH_FALL - CLEAR, min(f["floor"] for f in fs) - SLAB)
        x = x_of_u(u)
        stacks.append({"u": u, "x": x, "il_max": il_max, "fixtures": fs, "top": max(f["out"] for f in fs), "low_floor": min(f["floor"] for f in fs)})
    for s in stacks:
        s["need_head"] = s["il_max"] + s["x"] / fall
    il_head0 = prof["il"](0.0)
    il_head = min([il_head0] + [s["need_head"] for s in stacks])
    delta = il_head - il_head0
    deeper = delta < -1e-6
    od = prof["od"]

    def il(x):
        return prof["il"](x) + delta

    # ---- stations: from the plan, and one inspection eye under every stack
    sts = []
    for s in prof["stations"]:
        sts.append({"kind": s["kind"], "x": s["x"], "u": u_of_x(s["x"]), "desc": s["desc"]})
    for k, s in enumerate(stacks, 1):
        if not any(abs(t["x"] - s["x"]) < 0.4 for t in sts if t["kind"] in ("IE", "RE")):
            sts.append({"kind": "IE", "x": s["x"], "u": s["u"], "desc": "Inspection eye at stack %d" % k})
    sts.sort(key=lambda t: t["x"])
    for t in sts:
        t["ngl"] = prof["ngl"](t["x"])
        t["il"] = il(t["x"])
        t["depth"] = t["ngl"] - t["il"]
        t["cover"] = t["ngl"] - t["il"] - od
    # ---- checks
    checks = []
    for k, s in enumerate(stacks, 1):
        i_here = il(s["x"])
        ok = i_here <= s["il_max"] + 1e-6
        checks.append(("Stack %d (%d fixtures): invert %.3f is %d mm below the lowest outlet, a fall of 1:%d to the stack and clear of the slab." %
                       (k, len(s["fixtures"]), i_here, round((s["low_floor"] - i_here) * 1000), BRANCH_FALL) if ok else
                       "Stack %d: invert %.3f is above the %.3f the fixtures need." % (k, i_here, s["il_max"]), ok))
    mcov = min(t["cover"] for t in sts) if sts else 0.0
    par = res.get("params") or {}
    mc = float(par.get("min_cover", 0.3))
    checks.append(("Soil cover over the pipe is at least %d mm (lowest %d mm)." % (round(mc * 1000), round(mcov * 1000)) if mcov >= mc - 1e-6
                   else "Soil cover is only %d mm (minimum %d mm)." % (round(mcov * 1000), round(mc * 1000)), mcov >= mc - 1e-6))
    drop = il(Hh) - prof["main_il"]
    checks.append(("The pipe reaches the main %d mm above its invert level." % round(drop * 1000) if drop >= -1e-6
                   else "The pipe arrives %d mm BELOW the invert of the main: it cannot drain by gravity." % round(-drop * 1000), drop >= -1e-6))
    for t, ok in prof["checks"][:1]:
        checks.append((t, ok))
    nm = (state.get("stand") or {}).get("name", "")
    return {"fixtures": fx, "stacks": stacks, "stations": sts, "storeys": [dict(s, level=s["elev"] + shift) for s in storeys], "ground_i": gi,
            "ngl": prof["ngl"], "il": il, "x_of_u": x_of_u, "u_of_x": u_of_x, "od": od, "fall": fall, "pipe": prof["pipe"], "length": Hh, "main_il": prof["main_il"],
            "assumed": assumed, "deeper": deeper, "il_head": il_head, "checks": checks, "side": side, "turn_ok": ov, "overlap": ov, "main_u": u_of_x(Hh),
            "title": title or ("(A) %s %s" % (side, nm)).strip(), "typed_ffl": typed_ffl}


# ---------------------------------------------------------------- the sheet
def layout(d):
    fx, stacks, sts, storeys = d["fixtures"], d["stacks"], d["stations"], d["storeys"]
    ulo = min([f["u"] for f in fx] + [s["u"] for s in stacks]) - 3.5
    uhi = max([f["u"] for f in fx] + [s["u"] for s in stacks]) + 3.5
    top = max(s["level"] for s in storeys) + 0.6
    top = max(top, max(s["top"] for s in stacks) + 1.6)
    inw = [t["il"] for t in sts if ulo - 0.01 <= t["u"] <= uhi + 0.01]
    low = min(inw) if inw else min(s["il_max"] for s in stacks)
    low = min(low, min(d["il"](s["x"]) for s in stacks)) - 0.75
    gx0, gx1, gy0, gy1 = 16.0, 404.0, 14.0, 200.0
    scl = sp._nice(max((uhi - ulo) * 1000.0 / (gx1 - gx0 - 30.0), (top - low) * 1000.0 / (gy1 - gy0)), [50, 75, 100, 125, 150, 200, 250, 500])
    return {"ulo": ulo, "uhi": uhi, "top": top, "low": low, "scl": scl, "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1}


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

    def text(x, y, s, h=2.5, bold=False, col=BLACK, align="l", rot=0):
        f = sp._f(S, h, bold)
        p.setFont(f)
        p.setPen(col)
        w = sp._tw(f, s) / S
        ox = -(w if align == "r" else w / 2 if align == "c" else 0)
        if rot:
            p.save()
            p.translate(P(x, y))
            p.rotate(rot)
            p.drawText(QPointF(ox * S, 0), s)
            p.restore()
        else:
            p.drawText(P(x + ox, y), s)

    def line(x1, y1, x2, y2, c=BLACK, w=0.25, style=Qt.PenStyle.SolidLine):
        p.setPen(pen(c, w, style))
        p.drawLine(P(x1, y1), P(x2, y2))

    DD, DA, SO = Qt.PenStyle.DashDotLine, Qt.PenStyle.DashLine, Qt.PenStyle.SolidLine
    p.fillRect(0, 0, int(W), int(H), QColor("white"))
    fx, stacks, sts, storeys = d["fixtures"], d["stacks"], d["stations"], d["storeys"]
    od = d["od"]
    L = layout(d)
    ulo, uhi, top, low, scl = L["ulo"], L["uhi"], L["top"], L["low"], L["scl"]
    gx0, gx1, gy0, gy1 = L["gx0"], L["gx1"], L["gy0"], L["gy1"]

    def X(u):
        return gx0 + 18.0 + (u - ulo) * 1000.0 / scl

    def Y(v):
        return gy1 - (v - low) * 1000.0 / scl

    xr = gx1 - 6.0
    layer("TITLE BLOCK")
    for a, b, c_, e in ((8, 8, 412, 8), (412, 8, 412, 289), (412, 289, 8, 289), (8, 289, 8, 8)):
        line(a, b, c_, e, QColor(170, 170, 170), 0.15, Qt.PenStyle.DotLine)
    # ---- storey level lines
    layer("SECTION GROUND")
    for s in storeys:
        y = Y(s["level"])
        if y < gy0 - 2 or y > gy1 + 2:
            continue
        line(gx0, y, xr, y, BLACK, 0.25, DD)
        text(gx0 + 18, y - 1.2, _fmt_level(s["level"]), 2.5, align="r")
        text(gx0 + 18, y + 3.0, s["name"], 2.5, align="r")
        text(xr - 14, y - 1.2, _fmt_level(s["level"]), 2.5, align="r")
        text(xr - 14, y + 3.0, s["name"], 2.5, align="r")
    # ---- ground line at the cover level of the sewer
    inwin = [t for t in sts if ulo - 0.01 <= t["u"] <= uhi + 0.01]
    gl = d["ngl"](inwin[0]["x"]) if inwin else d["ngl"](0.0)
    line(gx0 + 4, Y(gl), xr, Y(gl), BLACK, 0.35)
    # ---- the sewer: invert and crown, through the stations and the stacks
    pts = sorted([(t["x"], t["u"]) for t in sts], key=lambda a: a[0])

    def seg_clip(u1, v1, u2, v2):
        """the part of a straight piece inside the window"""
        if (u1 < ulo and u2 < ulo) or (u1 > uhi and u2 > uhi):
            return None
        if u2 == u1:
            return (u1, v1, u2, v2)
        t0 = max(0.0, min(1.0, (ulo - u1) / (u2 - u1))) if u2 > u1 else max(0.0, min(1.0, (uhi - u1) / (u2 - u1)))
        t1 = max(0.0, min(1.0, (uhi - u1) / (u2 - u1))) if u2 > u1 else max(0.0, min(1.0, (ulo - u1) / (u2 - u1)))
        a, b = min(t0, t1), max(t0, t1)
        return (u1 + (u2 - u1) * a, v1 + (v2 - v1) * a, u1 + (u2 - u1) * b, v1 + (v2 - v1) * b)
    layer("SEWER")
    for (xa, ua), (xb, ub) in zip(pts[:-1], pts[1:]):
        for off in (0.0, od):
            c_ = seg_clip(ua, d["il"](xa) + off, ub, d["il"](xb) + off)
            if c_:
                line(X(c_[0]), Y(c_[1]), X(c_[2]), Y(c_[3]), BROWN, 0.25, DD)
    cut_l = any(t["u"] < ulo for t in sts)
    cut_r = any(t["u"] > uhi for t in sts)
    # ---- eyes and the manhole
    tags = []
    for t in sts:
        if not (ulo - 0.01 <= t["u"] <= uhi + 0.01):
            continue
        ux, il_ = X(t["u"]), t["il"]
        if t["kind"] == "MAIN":
            w = 1.0
            line(X(t["u"] - w / 2), Y(t["ngl"]), X(t["u"] - w / 2), Y(il_ - 0.15), BLACK, 0.35)
            line(X(t["u"] + w / 2), Y(t["ngl"]), X(t["u"] + w / 2), Y(il_ - 0.15), BLACK, 0.35)
            line(X(t["u"] - w / 2), Y(il_ - 0.15), X(t["u"] + w / 2), Y(il_ - 0.15), BLACK, 0.35)
            p.setBrush(QColor(200, 230, 200))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(P(X(t["u"] - w / 2), Y(t["ngl"])), P(X(t["u"] + w / 2), Y(il_ - 0.15))))
            p.setBrush(Qt.BrushStyle.NoBrush)
            text(ux, Y(t["ngl"]) + 5.0, "MH", 2.5, True, align="c")
            text(ux + w * 1000.0 / scl / 2 + 2, Y(il_ - 0.15), "MH size to be designed by the Civil Eng. to the local council's criteria.", 2.0)
        elif t["kind"] == "RE":
            dirn = -1.0 if d["u_of_x"](max(0.0, t["x"] - 0.5)) < d["u_of_x"](t["x"]) else 1.0      # leans up the line, the way the pipe comes from
            run = (Y(il_ + od) - Y(t["ngl"])) * dirn                                              # 45 degrees on the paper
            line(ux, Y(il_ + od), ux + run, Y(t["ngl"]), BROWN, 0.25, DD)
            line(ux, Y(il_), ux + run, Y(t["ngl"]), BROWN, 0.25, DD)
            text(ux + run + (1.5 if dirn > 0 else -1.5), Y(t["ngl"]) + 3.0, "RE", 2.2, True, align="l" if dirn > 0 else "r")
            t["_lean"] = run
        else:
            line(ux, Y(il_ + od), ux, Y(t["ngl"]), BROWN, 0.25, DD)
            text(ux - 1.5, Y(t["ngl"]) + 4.0, "IE", 2.2, True, align="r")
        if t["kind"] != "MAIN" and any(abs(o["u"] - t["u"]) < 0.5 and o["kind"] != "IE" for o in tags):
            continue
        if any(abs(o["u"] - t["u"]) < 0.5 and abs(o["il"] - t["il"]) < 0.12 for o in tags):
            continue
        tags.append(t)
    # ---- stacks, branches and fixtures
    layer("SEWER")
    for k, s in enumerate(stacks, 1):
        y_top = Y(s["top"] + 1.2)
        ux = X(s["u"])
        line(ux, Y(d["il"](s["x"]) + od), ux, Y(s["top"]), GREY, 0.25, DD)
        line(ux, Y(s["top"]), ux, y_top, RED, 0.3, DD)
        text(ux + 1.5, y_top + 3.0, "Vent Pipe", 2.2, True, RED)
    layer("FIXTURES")
    done = set()
    placed = {}                                    # storey -> label x positions already used on that floor (paper mm)
    for s in stacks:
        for f in sorted(s["fixtures"], key=lambda f: f["u"]):
            ux = X(s["u"])
            lx = X(f["u"])
            row = placed.setdefault(round(f["floor"], 2), [])
            while any(abs(lx - o) < 8.5 for o in row):
                lx += 8.5
            row.append(lx)
            yy = Y(f["out"])
            if abs(lx - ux) > 0.5:
                line(lx + 1.5, yy, ux, Y(f["out"] - abs(lx - ux) * scl / 1000.0 / BRANCH_FALL), GREEN, 0.3, DD)
            text(lx - 2, yy - 1.2, KINDS[f["kind"]][0], 2.5, True)
            if f["kind"] != "WC" and (id(s), round(f["floor"], 2)) not in done:
                done.add((id(s), round(f["floor"], 2)))
                text(ux + 2, yy - 15.0, "40dia WP's", 2.2)
                text(ux + 2, yy - 11.6, "100dia vv", 2.2)
    # ---- tags with CL, IL and depth, staggered under the pipe
    layer("SEWER")
    tags.sort(key=lambda t: t["u"])
    rows_end = [-1e9, -1e9, -1e9]
    bw, bh = 21.0, 11.0
    for t in tags:
        ux = X(t["u"])
        r = next((i for i, e in enumerate(rows_end) if e < ux - bw / 2 - 1.0), None)
        if r is None:
            r = min(range(3), key=lambda i: rows_end[i])
        rows_end[r] = ux + bw / 2
        by = Y(t["il"]) + 8.0 + r * (bh + 2.0)
        bx = ux - bw / 2 + (6.0 if t["kind"] == "RE" else 0)
        p.setPen(pen(BLACK, 0.2))
        p.drawRect(QRectF(P(bx, by), P(bx + bw, by + bh)))
        text(bx + 1.2, by + 3.3, "CL = %.3f" % t["ngl"], 2.2)
        text(bx + 1.2, by + 6.3, "IL  = %.3f" % t["il"], 2.2)
        text(bx + 1.2, by + 9.3, "D  = %dmm" % round(t["depth"] * 1000) if t["depth"] < 1.0 else "D  = %.2fm" % t["depth"], 2.2)
        gx_ = X(t["u"]) + t.get("_lean", 0.0)
        line(bx + (0 if bx > gx_ else bw), by + 4.0, gx_, Y(t["ngl"]) + 0.4, BLACK, 0.2)
        p.setBrush(BLACK)
        p.drawEllipse(P(gx_, Y(t["ngl"]) + 0.4), 0.5 * S, 0.5 * S)
        p.setBrush(Qt.BrushStyle.NoBrush)
    first = next((t for t in tags if t["kind"] in ("RE", "IE")), None)
    if first and first["depth"] > 0.2:
        ux = X(first["u"]) - 4.0
        line(ux, Y(first["ngl"]), ux, Y(first["il"]), BLACK, 0.2)
        text(ux - 1.0, (Y(first["ngl"]) + Y(first["il"])) / 2, "%d" % round(first["depth"] * 1000), 2.8, align="c", rot=-90)
    n_main = next((t for t in sts if t["kind"] == "MAIN"), None)
    if cut_l:
        text(gx0 + 20, Y(gl) + 12.0, "<  sewer continues to the left", 2.2)
    if cut_r:
        text(xr - 6, Y(gl) + 12.0, "sewer continues to the right  >" + ("  (main sewer %.1f m on)" % abs(d["main_u"] - uhi) if n_main and n_main["u"] > uhi else ""), 2.2, align="r")
    if tags:
        mid = tags[len(tags) // 2]
        text(X((ulo + uhi) / 2), Y(d["il"](d["x_of_u"]((ulo + uhi) / 2)) + od) - 2.5, "%sØ SWP, FALL 1:%d" % (d["pipe"], round(d["fall"])), 2.8, True, align="c")
    # ---- title bottom left, checks and title block bottom right
    layer("TITLE BLOCK")
    text(14, 262, "Sewer Elevation", 6.0)
    text(90, 262, "1:%d" % scl, 6.0)
    line(14, 264, 96, 264, BLACK, 0.4)
    text(14, 272, d["title"], 5.0)
    f = sp._f(S, 2.2)
    y = 258.0
    xk = 150.0
    text(xk, y - 5.0, "CHECKS", 2.4, True)
    for t_, ok in d["checks"][:6]:
        col = BLACK if ok else RED
        ln = sp._wrap(f, ("OK  " if ok else "CHECK  ") + t_, (252 - xk) * S)[:2]
        for ln_ in ln:
            text(xk, y, ln_, 2.2, False, col)
            y += 3.4
        if y > 285:
            break
    notes = []
    if d["assumed"]:
        notes.append("GROUND LEVELS ARE ASSUMED: ground taken as 150 mm under the finished floor. Type the surveyed levels before submitting.")
    if d["deeper"]:
        notes.append("The pipe is laid deeper than the site minimum so that it clears the lowest fixtures.")
    notes.append("Fixtures read from floor plan screenshots by AI; outlet heights assumed (WC 150, basins and sinks 550, washing machine 900 mm above the floor). Pipe sizes, falls and levels to be confirmed by the Engineer.")
    yy = 258.0
    xn = 256.0
    text(xn, yy - 5.0, "NOTES", 2.4, True)
    for t_ in notes:
        for ln_ in sp._wrap(f, t_, (404 - xn) * S):
            text(xn, yy, ln_, 2.2, False, RED if t_.startswith("GROUND") else BLACK)
            yy += 3.4
        yy += 0.8
    rows = [r for r in title_lines if r[0] in ("Stand", "Project", "Client", "Erf", "Site")][:3] + [("Date", (when or datetime.date.today()).strftime("%d/%m/%Y"))]
    ty = 281.0
    text(404, ty, "  |  ".join("%s %s" % (a, b) for a, b in rows)[:90], 2.2, align="r")
    layer(None)


def write_pdf(path, d, title_lines=(), when=None):
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
    w.setPageOrientation(QPageLayout.Orientation.Landscape)
    w.setResolution(300)
    p = QPainter(w)
    draw(p, w.width(), w.height(), w.width() / 420.0, d, title_lines, when)
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
    S = float(layout(d)["scl"])                  # drawn full size: 1 drawing unit = 1 mm, the paper millimetres of the sheet times the printed scale
    draw(p, 420.0 * S, 297.0 * S, S, d, title_lines, when)
    doc.saveas(path)
    return path


# ---------------------------------------------------------------- fixtures from a screenshot of a plan
SHOT_SYSTEM = (
    "You read a floor plan screenshot (an architectural plan, usually from ArchiCAD) and list the plumbing fixtures on it. Answer ONLY by calling the "
    "list_fixtures tool. Positions are fractions of the picture: x from 0 (left edge) to 1 (right edge), y from 0 (top edge) to 1 (bottom edge), taken at the "
    "middle of each fixture. Kinds: WC (toilet), WHB (wash hand basin or vanity basin), SH (shower), B (bath), S (kitchen or scullery sink), WM (washing machine "
    "point), DW (dishwasher), G (gully or floor trap). List every fixture you can see and nothing you cannot. building = the rectangle (same fractions) that just "
    "contains the whole building outline on the plan, outer walls included, without dimension lines or text outside the walls.")
SHOT_TOOL = {"name": "list_fixtures", "description": "The plumbing fixtures on the plan and the building outline.",
             "input_schema": {"type": "object", "properties": {
                 "fixtures": {"type": "array", "items": {"type": "object", "properties": {
                     "kind": {"type": "string", "enum": sorted(KINDS)}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["kind", "x", "y"]}},
                 "building": {"type": "object", "properties": {"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"}},
                              "required": ["x0", "y0", "x1", "y1"]}},
                 "required": ["fixtures", "building"]}}


def _vision(path, system, tool, text, key=None, model=None, timeout=120):
    """a picture + a tool the answer must come through -> the tool's input (dict). Raises RuntimeError with a plain message."""
    import base64
    import json
    import urllib.error
    import urllib.request
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    import detail_generator as gen
    key = key or gen.api_key()
    if not key:
        raise RuntimeError("No API key saved. Add one under Settings in the Detail notes tab (a Claude Pro subscription does not give the program a key).")
    img = QImage(str(path))
    if img.isNull():
        raise RuntimeError("That picture could not be opened.")
    size = (img.width(), img.height())
    if max(size) > 1600:
        img = img.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    body = {"model": model or gen.api_model(), "max_tokens": 4000, "system": system, "tools": [tool], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(bytes(ba)).decode()}},
                {"type": "text", "text": text}]}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError("Claude said: %s (code %s)" % (msg or e.reason, e.code))
    except urllib.error.URLError as e:
        raise RuntimeError("No internet connection (%s)" % e.reason)
    inp = next((p["input"] for p in data.get("content", []) if p.get("type") == "tool_use" and isinstance(p.get("input"), dict)), None)
    if inp is None:
        raise RuntimeError("Claude could not read anything from that picture. Try a clearer or larger screenshot.")
    return inp, size


def read_screenshot(path, key=None, model=None, timeout=120):
    """a plan screenshot -> {"fixtures": [{kind, x, y}], "building": (x0, y0, x1, y1), "w": px, "h": px}"""
    inp, (w, h) = _vision(path, SHOT_SYSTEM, SHOT_TOOL, "List the plumbing fixtures on this plan and the building outline.", key, model, timeout)
    fx = []
    for f in inp.get("fixtures") or []:
        try:
            k = str(f["kind"]).upper()
            if k in KINDS:
                fx.append({"kind": k, "x": min(1.0, max(0.0, float(f["x"]))), "y": min(1.0, max(0.0, float(f["y"])))})
        except (KeyError, TypeError, ValueError):
            pass
    b = inp.get("building") or {}
    try:
        bb = (float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))
        if bb[2] - bb[0] < 0.05 or bb[3] - bb[1] < 0.05:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        bb = (0.0, 0.0, 1.0, 1.0)
    return {"fixtures": fx, "building": bb, "w": w, "h": h}


LEVELS_SYSTEM = (
    "You read an architectural elevation or section screenshot and list the floor levels written on it (level markers such as '+221 490  1 First Floor', "
    "'0 Ground Floor', 'Roof'). Answer ONLY by calling the list_levels tool. level is in METRES as a number (+221 490 means 221.49; a plain 2.89 stays 2.89). "
    "name is the name written beside it (Ground Floor, First Floor, Roof ...). List only levels you can read, lowest first. Do not list ground or natural ground lines.")
LEVELS_TOOL = {"name": "list_levels", "description": "The floor levels written on the elevation.",
               "input_schema": {"type": "object", "properties": {"levels": {"type": "array", "items": {"type": "object", "properties": {
                   "name": {"type": "string"}, "level": {"type": "number"}}, "required": ["name", "level"]}}}, "required": ["levels"]}}


def read_levels(path, key=None, model=None, timeout=120):
    """an elevation screenshot -> [{"name", "level"}] lowest first"""
    inp, _size = _vision(path, LEVELS_SYSTEM, LEVELS_TOOL, "List the floor levels on this elevation.", key, model, timeout)
    out = []
    for x in inp.get("levels") or []:
        try:
            out.append({"name": str(x["name"]).strip()[:40] or "Level", "level": float(x["level"])})
        except (KeyError, TypeError, ValueError):
            pass
    if not out:
        raise RuntimeError("No floor levels could be read from that elevation.")
    return sorted(out, key=lambda x: x["level"])


def model_from_shots(shots, house_pts):
    """shots: [{"name", "level", "fixtures", "building", "w", "h"}] (one per floor, ground first) -> the model build() takes.
    The plan is scaled so the building outline on the screenshot is as long as the house on the site plan, with the screenshot's up as north-up of the house's fit."""
    from shapely.geometry import Polygon
    H = Polygon(house_pts).buffer(0)
    _a, Lh, Wh = _long_axis(H)
    storeys, fixtures = [], []
    k = None
    for i, s in enumerate(shots):
        x0, y0, x1, y1 = s["building"]
        bw, bh = (x1 - x0) * s["w"], (y1 - y0) * s["h"]
        kk = Lh / max(bw, bh)
        if k is None:
            k = kk
            fw, fh = bw * kk, bh * kk
        cx, cy = (x0 + x1) / 2 * s["w"], (y0 + y1) / 2 * s["h"]
        storeys.append({"id": i, "name": s["name"], "z": float(s["level"]), "elev": float(s["level"])})
        for f in s["fixtures"]:
            fixtures.append({"kind": f["kind"], "name": f["kind"], "x": (f["x"] * s["w"] - cx) * kk, "y": -(f["y"] * s["h"] - cy) * kk,
                             "z": float(s["level"]), "storey": i})
    if not storeys or k is None:
        raise ValueError("No screenshots yet.")
    fp = [(-fw / 2, -fh / 2), (fw / 2, -fh / 2), (fw / 2, fh / 2), (-fw / 2, fh / 2)]
    order = sorted(range(len(storeys)), key=lambda i: storeys[i]["z"])
    remap = {old: new for new, old in enumerate(order)}
    storeys = [storeys[i] for i in order]
    for f in fixtures:
        f["storey"] = remap[f["storey"]]
    return {"storeys": storeys, "fixtures": fixtures, "footprint": fp, "file": "plan screenshots"}
