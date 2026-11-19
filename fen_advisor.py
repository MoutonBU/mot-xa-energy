"""Which windows spoil the energy (XA) fenestration check, and what to change.

Pure calculation (no screen code). Input per group (a unit or a floor): the net floor area, the screening limit, and the windows
as dicts {room, tag, area (m2, all of that tag in the room), u, s, e, sector, shaded}. Output: the problems, the windows that cause
them (worst first) and plain suggestions with the numbers worked out."""

GROUP_A = {"W", "NW", "N", "NE", "E"}


def _top(wins, key):
    return sorted(wins, key=key, reverse=True)


def _glass_options(glass, field):
    """[(name, U, S)] real glass types, best first for `field` ('s' or 'u')."""
    rows = [(n, v[0], v[1]) for n, v in glass.items() if n != "Custom"]
    return sorted(rows, key=lambda r: r[2] if field == "s" else r[1])


def _fix_by_glass(wins, agg, limit, field, glass, weight):
    """Least change that brings `agg` (a sum over windows of area*value*weight) under `limit`: the fewest windows, then the mildest glass.
    Returns a dict or None."""
    opts = _glass_options(glass, field)
    ranked = _top(wins, lambda w: w["area"] * w[field] * weight(w))
    for k in range(1, len(ranked) + 1):
        picked = ranked[:k]
        best = None
        for name, gu, gs in opts:                                 # mildest first = highest value that still complies
            new = gs if field == "s" else gu + 0.35               # a window U is a little worse than its glass: frame edge
            saved = sum(w["area"] * max(0.0, w[field] - new) * weight(w) for w in picked)
            if agg - saved <= limit + 1e-9:
                if best is None or new > best[1]:
                    best = (name, new, agg - saved, gu, gs)
        if best:
            return {"windows": picked, "glass": best[0], "value": best[1], "after": best[2]}
    return None


def advise(group, nfa, limit_pct, wins, calc, glass, orient_rows=None, zone="", fen=None):
    """One group's problems. calc = fenestration_storey() result; orient_rows = the Table 4 rows of this group."""
    fen = sum(w["area"] for w in wins) if fen is None else fen
    pct = fen / nfa * 100 if nfa else 0.0
    out = {"group": group, "issues": [], "bad": []}
    if not wins or not nfa:
        return out
    bad = {}

    def mark(ws, why):
        for w in ws:
            bad.setdefault((w.get("floor", ""), w["room"], w["tag"]), []).append(why)

    # 1. solar heat gain, whole group (deemed-to-satisfy calculation)
    if calc["agg_s"] > calc["max_s"] + 1e-9:
        ex = calc["agg_s"] - calc["max_s"]
        ranked = _top(wins, lambda w: w["area"] * w["s"] * w["e"])
        tot = calc["agg_s"] or 1.0
        fixes = []
        f = _fix_by_glass(wins, calc["agg_s"], calc["max_s"], "s", glass, lambda w: w["e"])
        if f:
            names = ", ".join("%s in %s" % (w["tag"], w["room"]) for w in f["windows"])
            fixes.append("Change %s to <b>%s</b> (solar gain about %.2f). The group's solar heat gain falls from %.2f to %.2f "
                         "(limit %.2f), so it complies." % (names, f["glass"], f["value"], calc["agg_s"], f["after"], calc["max_s"]))
            mark(f["windows"], "solar")
        else:
            mark(ranked[:3], "solar")
        avg_s = sum(w["area"] * w["s"] * w["e"] for w in wins) / (sum(w["area"] for w in wins) or 1)
        drop = ex / (avg_s or 1)
        fixes.append("Or take about <b>%.2f m2</b> of glass out of the group (the windows above first)." % drop)
        # shading: only W / NW / N / NE / E windows that are not already shaded can earn a lower exposure factor E
        elig = [w for w in wins if not w.get("shaded") and ((w.get("sector") in GROUP_A) or not w.get("sector"))]
        base = sum(w["area"] * w["s"] for w in elig)
        if elig and base > 0:
            e_now = sum(w["area"] * w["s"] * w["e"] for w in elig)
            e_need = (e_now - ex) / base                      # the exposure factor these windows must drop to
            seen, lines = set(), []
            for w in sorted(elig, key=lambda w: -w["area"] * w["s"] * w["e"]):
                key = (w["tag"], w.get("H"))
                if key in seen:
                    continue
                seen.add(key)
                H, m = w.get("H") or 0.0, w.get("mult") or 0.0
                if H and m:
                    lines.append("%s (%s, faces %s): projection of at least <b>%.0f mm</b> (%.2f x H of %.0f mm)%s" % (
                        w["tag"], w["room"], w.get("sector") or "?", H * m, m, H,
                        " - now %.0f mm" % w["P"] if w.get("P") else ""))
                if len(lines) >= 6:
                    break
            if e_need > 0.05:
                fixes.append("Or <b>shade</b> the %d unshaded west, north and east windows with a deep overhang, louvres or a screen. "
                             "Their exposure factor E must come down from about %.2f to <b>%.2f or lower</b> (use the SANS 204 value "
                             "for the projection you choose) for the group to comply. Projection needed so the window counts as shaded "
                             "(SANS 10400-XA table 3), measured out from the glass:<br>&nbsp;&nbsp;%s" % (
                                 len(elig), e_now / base, e_need, "<br>&nbsp;&nbsp;".join(lines) or "enter the window height H in the glass table"))
            else:
                fixes.append("Shading alone cannot fix this group: even with full shading the west, north and east windows leave "
                             "it over the limit. Change the glass or take glass out as well.")
        out["issues"].append({
            "kind": "solar", "title": "Solar heat gain is %.2f, the limit is %.2f (over by %.2f)" % (calc["agg_s"], calc["max_s"], ex),
            "windows": [{**w, "contrib": w["area"] * w["s"] * w["e"], "share": w["area"] * w["s"] * w["e"] / tot * 100} for w in ranked[:6]],
            "fixes": fixes})
    # 2. conductance, whole group
    if calc["agg_u"] > calc["max_u"] + 1e-9:
        ex = calc["agg_u"] - calc["max_u"]
        ranked = _top(wins, lambda w: w["area"] * w["u"])
        tot = calc["agg_u"] or 1.0
        fixes = []
        f = _fix_by_glass(wins, calc["agg_u"], calc["max_u"], "u", glass, lambda w: 1.0)
        if f:
            names = ", ".join("%s in %s" % (w["tag"], w["room"]) for w in f["windows"])
            fixes.append("Change %s to <b>%s</b> with a thermally broken frame (window U about %.1f). Conductance falls from %.2f to %.2f "
                         "(limit %.2f)." % (names, f["glass"], f["value"], calc["agg_u"], f["after"], calc["max_u"]))
            mark(f["windows"], "conductance")
        else:
            mark(ranked[:3], "conductance")
        fixes.append("Or take about <b>%.2f m2</b> of glass out (single glass at U 5.6 costs the most per m2)." % (ex / (sum(w["area"] * w["u"] for w in wins) / (sum(w["area"] for w in wins) or 1) or 1)))
        out["issues"].append({
            "kind": "u", "title": "Conductance is %.2f, the limit is %.2f (over by %.2f)" % (calc["agg_u"], calc["max_u"], ex),
            "windows": [{**w, "contrib": w["area"] * w["u"], "share": w["area"] * w["u"] / tot * 100} for w in ranked[:6]],
            "fixes": fixes})
    # 3. more glass than the screening limit allows (only matters when the calculation above is not met)
    over = pct > limit_pct + 1e-9
    if over:
        allowed = nfa * limit_pct / 100.0
        ranked = _top(wins, lambda w: w["area"])
        out["issues"].append({
            "kind": "screen", "title": "Glazing is %.1f%% of the floor, the screening limit is %g%% (%.2f m2 too much)" % (pct, limit_pct, fen - allowed),
            "windows": [{**w, "contrib": w["area"], "share": w["area"] / fen * 100} for w in ranked[:5]],
            "fixes": ["Keep glazing to %.2f m2 (or run the SANS 204 calculation, which this group %s)." % (
                allowed, "passes" if calc["ok"] else "does not pass yet")]})
        if not calc["ok"]:
            mark(ranked[:3], "area")
    # 4. Table 4 facade groups
    for rw in orient_rows or []:
        if rw.get("ok"):
            continue
        sect = GROUP_A if rw["group"].startswith("W") else {"SW", "S", "SE"}
        ws = [w for w in wins if (w.get("sector") in sect) or (not w.get("sector") and rw["group"].startswith("W"))]
        if not ws:
            continue
        fixes = []
        if not rw["ok_s"] and rw["max_s"] is not None:
            if rw["group"].startswith("W") and not rw.get("shaded"):
                fixes.append("Shade these windows (overhang projection at least the multiplier x H shown above): the allowed solar gain "
                             "then rises from the unshaded to the shaded value in table 4.")
            f = _fix_by_glass(ws, sum(w["area"] * w["s"] for w in ws), rw["max_s"] * rw["area"], "s", glass, lambda w: 1.0)
            if f:
                names = ", ".join("%s in %s" % (w["tag"], w["room"]) for w in f["windows"])
                fixes.append("Or change %s to <b>%s</b> (solar gain about %.2f): the facade average drops to %.2f (limit %.2f)." % (
                    names, f["glass"], f["value"], f["after"] / rw["area"], rw["max_s"]))
                mark(f["windows"], "facade")
        if not rw["ok_u"] and rw["max_u"] is not None:
            f = _fix_by_glass(ws, sum(w["area"] * w["u"] for w in ws), rw["max_u"] * rw["area"], "u", glass, lambda w: 1.0)
            if f:
                names = ", ".join("%s in %s" % (w["tag"], w["room"]) for w in f["windows"])
                fixes.append("Change %s to <b>%s</b> with a thermally broken frame (window U about %.1f): the facade average drops to %.2f (limit %.2f)." % (
                    names, f["glass"], f["value"], f["after"] / rw["area"], rw["max_u"]))
                mark(f["windows"], "facade")
        mark(ws, "facade")
        out["issues"].append({
            "kind": "orient", "title": "%s facades fail table 4 (%s)" % (rw["group"], " and ".join(
                x for x, ok in (("U-value", rw["ok_u"]), ("solar gain", rw["ok_s"])) if not ok)),
            "windows": [{**w, "contrib": w["area"], "share": w["area"] / (sum(x["area"] for x in ws) or 1) * 100}
                        for w in _top(ws, lambda w: w["area"] * (w["s"] if not rw["ok_s"] else w["u"]))[:6]],
            "fixes": fixes or ["Reduce the glass on this facade or move it to the south side."]})
    out["bad"] = [{"floor": k[0], "room": k[1], "tag": k[2], "why": sorted(set(v))} for k, v in bad.items()]
    return out
