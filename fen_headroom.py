"""How far each window can be reduced or taken out while its room still has enough daylight and ventilation, and a plan of
reductions that brings a unit or storey inside the solar heat gain and conductance limits without breaking light or ventilation.

entries: one dict per window type in a room:
  floor (group), room, tag, qty, area (m2 of one window), g (glazed m2 of one), o (openable m2 of one), w, h (mm), s, u, e, sector,
  room_area, light_req, vent_req, room_glazed, room_open, light_free, vent_free (True when artificial light / mechanical vent apply)
"""
import math

INF = float("inf")


def _spare(en):
    sl = INF if en.get("light_free") else max(0.0, en["room_glazed"] - en["light_req"])
    sv = INF if en.get("vent_free") else max(0.0, en["room_open"] - en["vent_req"])
    return sl, sv


def _max_cut(en, rl, rv):
    """Largest fraction (0..1) of this window type that can go, given the room's remaining spare light (rl) and ventilation (rv)."""
    tot_g, tot_o = en["g"] * en["qty"], en["o"] * en["qty"]
    if tot_g <= 1e-9 and tot_o <= 1e-9:
        return 1.0, "nothing counts"
    f = 1.0
    why = "can be taken out"
    if tot_g > 1e-9 and rl < INF and rl / tot_g < f:
        f, why = rl / tot_g, "daylight"
    if tot_o > 1e-9 and rv < INF and rv / tot_o < f:
        f, why = rv / tot_o, "ventilation"
    return max(0.0, min(1.0, f)), why


def _size(en, frac):
    k = math.sqrt(max(0.0, 1.0 - frac))
    return int(round(en["w"] * k / 10.0) * 10), int(round(en["h"] * k / 10.0) * 10)


def analyse(entries, calc):
    """Returns {"rows": [...], "plan": [...], "agg_s", "agg_u", "max_s", "max_u", "ok", "need_s", "need_u", "after_s", "after_u", "rooms": [...]}"""
    rows = []
    for en in entries:
        rl, rv = _spare(en)
        frac, why = _max_cut(en, rl, rv)
        area = en["area"] * en["qty"]
        w2, h2 = _size(en, frac)
        rows.append({"floor": en["floor"], "room": en["room"], "tag": en["tag"], "qty": en["qty"], "w": en["w"], "h": en["h"],
                     "frac": frac, "why": why, "w2": w2, "h2": h2, "remove": frac >= 0.999,
                     "s_save": area * frac * en["s"] * en["e"], "u_save": area * frac * en["u"], "sector": en.get("sector", ""),
                     "free": bool(en.get("light_free") or en.get("vent_free")),
                     "fixed_m2": max(0.0, min(rl, en["g"] * en["qty"] - en["o"] * en["qty"]))})
    need_s = max(0.0, calc["agg_s"] - calc["max_s"])
    need_u = max(0.0, calc["agg_u"] - calc["max_u"])
    out = {"rows": rows, "plan": [], "rooms": [], "agg_s": calc["agg_s"], "agg_u": calc["agg_u"], "max_s": calc["max_s"],
           "max_u": calc["max_u"], "need_s": need_s, "need_u": need_u, "after_s": calc["agg_s"], "after_u": calc["agg_u"],
           "ok": need_s <= 1e-9 and need_u <= 1e-9}
    if out["ok"]:
        return out
    # remaining room spare, shared by all windows in the room
    rem = {}
    for en in entries:
        k = (en["floor"], en["room"])
        if k not in rem:
            rem[k] = list(_spare(en)) + [en["room_glazed"], en["room_open"], en["room_area"], en["light_req"], en["vent_req"]]
    rs, ru = need_s, need_u
    sv_s = sv_u = 0.0

    def density(en):
        d = 0.0
        if need_s > 1e-9:
            d += en["s"] * en["e"] / need_s
        if need_u > 1e-9:
            d += en["u"] / need_u
        return d
    for en in sorted(entries, key=lambda e_: -density(e_)):
        if rs <= 1e-9 and ru <= 1e-9:
            break
        k = (en["floor"], en["room"])
        r_ = rem[k]
        frac, why = _max_cut(en, r_[0], r_[1])
        if frac <= 1e-6:
            continue
        area = en["area"] * en["qty"]
        want = 0.0
        if rs > 1e-9 and en["s"] * en["e"] > 1e-9:
            want = max(want, rs / (area * en["s"] * en["e"]))
        if ru > 1e-9 and en["u"] > 1e-9:
            want = max(want, ru / (area * en["u"]))
        cut = min(frac, want)
        if cut <= 1e-6:
            continue
        cg, co = en["g"] * en["qty"] * cut, en["o"] * en["qty"] * cut
        r_[0] = r_[0] - cg if r_[0] < INF else INF
        r_[1] = r_[1] - co if r_[1] < INF else INF
        r_[2] -= cg
        r_[3] -= co
        rs -= area * cut * en["s"] * en["e"]
        ru -= area * cut * en["u"]
        sv_s += area * cut * en["s"] * en["e"]
        sv_u += area * cut * en["u"]
        w2, h2 = _size(en, cut)
        out["plan"].append({"floor": en["floor"], "room": en["room"], "tag": en["tag"], "qty": en["qty"], "w": en["w"], "h": en["h"],
                            "cut": cut, "w2": w2, "h2": h2, "remove": cut >= 0.999, "full": cut >= frac - 1e-6, "limit": why})
    out["after_s"] = calc["agg_s"] - sv_s
    out["after_u"] = calc["agg_u"] - sv_u
    out["achieved"] = rs <= 1e-6 and ru <= 1e-6
    out["short_s"], out["short_u"] = max(0.0, rs), max(0.0, ru)
    for (fl, nm), r_ in rem.items():
        if any(p["room"] == nm and p["floor"] == fl for p in out["plan"]):
            area = r_[4] or 1.0
            out["rooms"].append({"floor": fl, "room": nm, "light_pct": r_[2] / area * 100.0 if r_[4] else 0.0,
                                 "vent_pct": r_[3] / area * 100.0 if r_[4] else 0.0})
    return out
