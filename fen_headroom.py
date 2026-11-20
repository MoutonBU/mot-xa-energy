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


# ---------------------------------------------------------------------------------------------------------------------
# Same suggestion for the same room type in every unit.
MIN_DOOR_W = 750          # a door or glazed door is only ever narrowed (its height stays) and never below this width, in mm
MIN_WIN = 450             # a window is never made smaller than this in either direction, in mm
import re as _re


def _room_key(name):
    n = _re.sub(r"^\s*u(?:nit)?\s*\d+\s*[-_. ]\s*", "", str(name or ""), flags=_re.I)
    return _re.sub(r"[^a-z0-9]", "", n.lower())


def _is_door(en):
    return str(en.get("kind", "")).lower().startswith("door")


def _size_cap(en):
    """Largest fraction of the opening's area that may go, by its own shape rules (doors: width only, window: minimum size)."""
    w, h = float(en["w"] or 0), float(en["h"] or 0)
    if _is_door(en):
        return max(0.0, (w - MIN_DOOR_W) / w) if w > 0 else 0.0
    m = min(w, h)
    return max(0.0, 1.0 - (MIN_WIN / m) ** 2) if m > 0 else 0.0


def _new_size(en, c):
    if _is_door(en):
        return int(round(en["w"] * (1.0 - c) / 10.0) * 10), int(en["h"])
    return _size(en, c)


def analyse_global(by_group, calcs):
    """by_group: {group: [entries]}, calcs: {group: calc}. One change per (room type, window type), applied in every unit.
    Returns {"rows", "plan", "units", "achieved", "rooms"}."""
    keys = {}
    for g, ens in by_group.items():
        for en in ens:
            keys.setdefault((_room_key(en["room"]), en["tag"]), []).append((g, en))
    rem = {}
    for g, ens in by_group.items():
        for en in ens:
            k = (g, en["room"])
            if k not in rem:
                rem[k] = list(_spare(en)) + [en["room_glazed"], en["room_open"], en["room_area"]]

    def cap(k):
        c, why = 1.0, "can be taken out"
        for g, en in keys[k]:
            r_ = rem[(g, en["room"])]
            f, w_ = _max_cut(en, r_[0], r_[1])
            if f < c:
                c, why = f, w_
        sc = min(_size_cap(en) for _g, en in keys[k])
        any_door = any(_is_door(en) for _g, en in keys[k])
        return c, sc, any_door, why

    rows = []
    for k, inst in keys.items():
        c, sc, door, why = cap(k)
        if door:
            lim, remv = min(c, sc), False
            if sc < c:
                why = "minimum door width %d mm" % MIN_DOOR_W
        else:
            remv = c >= 0.999
            lim = 1.0 if remv else min(c, sc)
            if not remv and sc < c:
                why = "minimum window size %d mm" % MIN_WIN
        en0 = inst[0][1]
        w2, h2 = _new_size(en0, lim)
        s_save = sum(en["area"] * en["qty"] * lim * en["s"] * en["e"] for _g, en in inst)
        units = sorted({g for g, _en in inst})
        sizes = sorted({(int(en["w"]), int(en["h"])) for _g, en in inst})
        rows.append({"key": k, "room": en0["room"], "tag": en0["tag"], "units": units, "n": len(inst), "door": door, "frac": lim, "remove": remv,
                     "why": why, "w": en0["w"], "h": en0["h"], "w2": w2, "h2": h2, "sizes": sizes, "s_save": s_save,
                     "free": any(en.get("light_free") or en.get("vent_free") for _g, en in inst),
                     "fixed_m2": max(0.0, min(min((_spare(en)[0] for _g, en in inst)),
                                               min(en["g"] * en["qty"] - en["o"] * en["qty"] for _g, en in inst)))})
    # per unit what has to go
    st = {}
    for g, c_ in calcs.items():
        ns, nu = max(0.0, c_["agg_s"] - c_["max_s"]), max(0.0, c_["agg_u"] - c_["max_u"])
        st[g] = {"group": g, "agg_s": c_["agg_s"], "agg_u": c_["agg_u"], "max_s": c_["max_s"], "max_u": c_["max_u"],
                 "rs": ns, "ru": nu, "ok": ns <= 1e-9 and nu <= 1e-9, "sv_s": 0.0, "sv_u": 0.0}
    plan = []
    failing = lambda: [g for g, v in st.items() if v["rs"] > 1e-9 or v["ru"] > 1e-9]   # noqa: E731
    if failing():
        def density(k):
            d = 0.0
            for g, en in keys[k]:
                v = st.get(g)
                if not v:
                    continue
                a = en["area"] * en["qty"]
                if v["rs"] > 1e-9:
                    d += a * en["s"] * en["e"] / v["rs"]
                if v["ru"] > 1e-9:
                    d += a * en["u"] / v["ru"]
            return d
        for k in sorted(keys, key=lambda k_: -density(k_)):
            fl = failing()
            if not fl:
                break
            inst = [(g, en) for g, en in keys[k] if g in fl]
            if not inst:
                continue
            c, sc, door, why = cap(k)
            want = 0.0
            for g in fl:
                v = st[g]
                mine = [en for g_, en in keys[k] if g_ == g]
                if not mine:
                    continue
                a_s = sum(en["area"] * en["qty"] * en["s"] * en["e"] for en in mine)
                a_u = sum(en["area"] * en["qty"] * en["u"] for en in mine)
                if v["rs"] > 1e-9 and a_s > 1e-9:
                    want = max(want, v["rs"] / a_s)
                if v["ru"] > 1e-9 and a_u > 1e-9:
                    want = max(want, v["ru"] / a_u)
            if want <= 1e-6:
                continue
            if door:
                cut, remove = min(want, c, sc), False
            elif want > sc and c >= 0.999:
                cut, remove = 1.0, True
            else:
                cut, remove = min(want, c, sc), False
            if cut <= 1e-6:
                continue
            for g, en in keys[k]:
                r_ = rem[(g, en["room"])]
                cg, co = en["g"] * en["qty"] * cut, en["o"] * en["qty"] * cut
                if r_[0] < INF:
                    r_[0] -= cg
                if r_[1] < INF:
                    r_[1] -= co
                r_[2] -= cg
                r_[3] -= co
                v = st[g]
                a = en["area"] * en["qty"]
                v["rs"] = max(0.0, v["rs"] - a * cut * en["s"] * en["e"])
                v["ru"] = max(0.0, v["ru"] - a * cut * en["u"])
                v["sv_s"] += a * cut * en["s"] * en["e"]
                v["sv_u"] += a * cut * en["u"]
            en0 = keys[k][0][1]
            w2, h2 = _new_size(en0, cut)
            if door and sc <= c + 1e-9:
                why = "minimum door width %d mm" % MIN_DOOR_W
            elif not door and not remove and sc < c:
                why = "minimum window size %d mm" % MIN_WIN
            plan.append({"room": en0["room"], "tag": en0["tag"], "units": sorted({g for g, _e in keys[k]}), "door": door, "cut": cut,
                         "remove": remove, "w": en0["w"], "h": en0["h"], "w2": w2, "h2": h2,
                         "full": cut >= min(c, sc) - 1e-6, "limit": why,
                         "sizes": sorted({(int(e["w"]), int(e["h"])) for _g, e in keys[k]})})
    units = []
    for g, v in st.items():
        v["after_s"] = v["agg_s"] - v["sv_s"]
        v["after_u"] = v["agg_u"] - v["sv_u"]
        v["ok_after"] = v["after_s"] <= v["max_s"] + 1e-6 and v["after_u"] <= v["max_u"] + 1e-6
        units.append(v)
    touched = {id(en) for p_ in [] for en in []}
    rooms = []
    changed = {(p_["room"] and _room_key(p_["room"]), p_["tag"]) for p_ in plan}
    for (g, nm), r_ in rem.items():
        if any((_room_key(e["room"]), e["tag"]) in changed and e["room"] == nm for e in by_group[g]) and r_[4]:
            rooms.append({"unit": g, "room": nm, "light_pct": r_[2] / r_[4] * 100.0, "vent_pct": r_[3] / r_[4] * 100.0})
    return {"rows": rows, "plan": plan, "units": units, "achieved": all(u["ok_after"] for u in units), "rooms": rooms}
