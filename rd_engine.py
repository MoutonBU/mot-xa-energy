"""Built-in hourly energy model for the SANS 10400-XA rational design (the 'performance route').

Method: the hourly 5R1C model of EN ISO 13790 (annex C) / ISO 52016, one thermal zone per room, ideal-loads heating and cooling
between two set-points, 8760 hours of the weather file. The same building is run twice: as designed, and as the REFERENCE building
(same shape, same rooms, same weather and use, with the deemed-to-satisfy envelope of the climate zone). The design passes when its
annual energy consumption and its peak electrical demand are not more than the reference building's.

Only numpy is used. No Qt: this file can be tested on its own (see test_rd_engine.py).
Frame: surfaces carry `az` = degrees clockwise from true north (the outward normal), `tilt` 90 = wall, 0 = roof.
"""
import math
import numpy as np

HOURS = 8760
MDAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
RHO_CP_AIR = 0.34                  # Wh/(m3 K): air density x specific heat / 3600
FILMS = {"ext_wall": (0.13, 0.04), "roof": (0.10, 0.04), "floor_exp": (0.17, 0.04), "floor_ground": (0.17, 1.0),   # (inside film, outside film / soil)
         "int_wall": (0.12, 0.12), "floor_int": (0.17, 0.10)}
GROUND_SOIL_R = 1.0                # m2K/W of soil below a slab on grade (same in both buildings, so it cancels in the comparison)
DOOR_LEAF_R = 0.25
ABSORPT = {"ext_wall": 0.6, "roof": 0.6, "floor_exp": 0.6}
DEFAULTS = {"ach": 0.5, "heat_sp": 19.0, "cool_sp": 25.0, "cop_heat": 1.0, "cop_cool": 3.0,
            "lpd": 4.0, "light_hours": 4.0, "persons_m2": 0.04, "person_w": 75.0, "equip_w_m2": 2.0, "hours": 0.0, "days": 7, "sky_dt": 11.0}


# ---------------------------------------------------------------------------------------------- constructions
def cons_r(c):
    """Resistance of the layers only (no films)."""
    r = 0.0
    for l in c.get("layers") or []:
        if l.get("rfix", 0) > 0:
            r += l["rfix"]
        elif l.get("lam", 0) > 0:
            r += l.get("t", 0) / l["lam"]
    return r if (c.get("layers") or []) else float(c.get("r_default", 0.0))


def cons_u(c, key):
    """U-value of a construction including the surface films it has in this position."""
    ri, ro = FILMS.get(key, (0.13, 0.04))
    return 1.0 / (cons_r(c) + ri + ro)


def cons_kappa(c, depth=0.10):
    """Heat capacity (J/m2K) of the layers on the room side, down to the first insulating layer or `depth` metres."""
    k, used = 0.0, 0.0
    for l in reversed(c.get("layers") or []):                # layers are listed outside -> inside
        if l.get("rfix", 0) > 0 or l.get("lam", 0) <= 0 or l.get("lam", 0) < 0.1:
            break                                             # air gap, resistance, or insulation: heat storage stops here
        t = min(l["t"], depth - used)
        if t <= 0:
            break
        k += t * l.get("dens", 1800.0) * l.get("cp", 840.0)
        used += t
    return k


def reference_construction(c, key, r_total_req):
    """The same heavy layers (so the thermal mass is the same) with the insulation set to the deemed-to-satisfy total R of the zone."""
    keep = [dict(l) for l in (c.get("layers") or []) if l.get("rfix", 0) <= 0 and l.get("lam", 0) >= 0.1]
    ri, ro = FILMS.get(key, (0.13, 0.04))
    r_keep = sum(l["t"] / l["lam"] for l in keep)
    add = max(0.0, r_total_req - ri - ro - r_keep)
    if add > 1e-6:
        keep.insert(0, {"name": "Reference insulation", "t": 0.0, "lam": 0.0, "rfix": add, "dens": 20.0, "cp": 1400.0})
    return {"name": "Reference " + key, "layers": keep, "r_default": 0.0 if keep else r_total_req}


# ---------------------------------------------------------------------------------------------- geometry helpers
def poly_area(pts):
    """Area of a planar polygon in 3D (Newell)."""
    n = len(pts)
    sx = sy = sz = 0.0
    for i in range(n):
        x1, y1, z1 = pts[i]
        x2, y2, z2 = pts[(i + 1) % n]
        sx += (y1 - y2) * (z1 + z2)
        sy += (z1 - z2) * (x1 + x2)
        sz += (x1 - x2) * (y1 + y2)
    return 0.5 * math.sqrt(sx * sx + sy * sy + sz * sz)


def zones_from_model(model, cons, glass, shade=None, glass_default=(5.6, 0.77)):
    """Plain description of each room for the engine, from the IFC model made by sim_build_model.
    {'name','area','vol','lights_w','lights_h','surfs':[...],'wins':[...],'doors':[...]}"""
    shade = shade or {}
    out = []
    for z in model["zones"]:
        d = {"name": z["label"], "storey": z["storey"], "area": float(z["pg"].area), "vol": float(z["pg"].area) * max(0.5, z["z1"] - z["z0"]),
             "lights_w": float(z.get("lights_w", 0.0)), "lights_h": float(z.get("lights_h", 0.0)), "surfs": [], "wins": [], "doors": []}
        for s in model["surfaces"]:
            if s["zid"] != z["zid"]:
                continue
            a = poly_area(s["pts"])
            ops = s.get("ops") or []
            a_ops = sum(o["w"] * o["h"] for o in ops)
            kind = s["cons"]
            sf = {"cons": kind, "area": max(0.0, a - a_ops), "az": float(s.get("az", 0.0)), "tilt": float(s.get("tilt", 90.0)),
                  "bc": s["bc"]}
            d["surfs"].append(sf)
            for o in ops:
                nm = str(o["name"])
                g = glass.get(nm) or glass.get(nm.upper()) or None
                if o["kind"] == "Window" or g is not None:
                    u, sg = g or glass.get("*") or glass_default
                    p = float((shade.get(nm) or shade.get(nm.upper()) or 0.0))
                    d["wins"].append({"area": o["w"] * o["h"], "U": float(u), "g": float(sg), "az": sf["az"], "h": float(o["h"]), "P": p / 1000.0, "name": nm})
                else:
                    d["doors"].append({"area": o["w"] * o["h"], "U": 1.0 / (DOOR_LEAF_R + 0.17), "az": sf["az"], "name": nm})
        out.append(d)
    return out


# ---------------------------------------------------------------------------------------------- sun on a plane
def plane_irradiance(w, sun, tilt, az):
    """(total, beam on the plane, cos of incidence) in W/m2 on a surface of this tilt and azimuth, per hour."""
    alt, saz = sun
    DN = np.asarray(w["DNI"][:HOURS], float)
    DF = np.asarray(w["DHI"][:HOURS], float)
    G = np.asarray(w["GHI"][:HOURS], float)
    b = math.radians(tilt)
    cth = np.sin(alt) * math.cos(b) + np.cos(alt) * math.sin(b) * np.cos(saz - math.radians(az))
    cth = np.where(alt > 0, cth, 0.0)
    beam = DN * np.clip(cth, 0.0, None)
    tot = beam + DF * (1 + math.cos(b)) / 2.0 + G * 0.2 * (1 - math.cos(b)) / 2.0
    return tot, beam, np.clip(cth, 0.0, 1.0)


def profile_24(on_from, hours):
    """Hours of the day (24 values 0/1) switched on for `hours` from `on_from`, wrapping past midnight."""
    p = np.zeros(24)
    h = max(0.0, min(24.0, hours))
    for k in range(24):
        x = (k + 0.5 - on_from) % 24.0
        p[k] = 1.0 if x < h else 0.0
    return p


# ---------------------------------------------------------------------------------------------- the simulation
def simulate(zones, cons, w, sun, opts=None, label="building"):
    """Run one building. Returns {'monthly_heat','monthly_cool' (kWh), 'heat','cool','lights','equip' (kWh/a), 'peak_w', 'area',
    'zones':[{name,area,heat,cool}], 'ua': {...}, 'solar_by_sector': {...}, 'hourly_elec': array}."""
    o = dict(DEFAULTS)
    o.update(opts or {})
    nz = len(zones)
    Te = np.asarray(w["T"][:HOURS], float)
    tground = float(Te.mean())
    hod = np.arange(HOURS) % 24
    dow = (np.arange(HOURS) // 24) % 7
    alt, saz = sun
    cache = {}

    def plane(tilt, az):
        k = (round(tilt), round(az / 5.0) * 5 % 360)
        if k not in cache:
            cache[k] = plane_irradiance(w, sun, k[0], k[1])
        return cache[k]
    Hve = np.zeros(nz); Hw = np.zeros(nz); Hop = np.zeros(nz); Atot = np.zeros(nz); Cm = np.zeros(nz); Am = np.zeros(nz); Af = np.zeros(nz)
    Teq = np.zeros((HOURS, nz)); Psol = np.zeros((HOURS, nz)); Pint = np.zeros((HOURS, nz)); Plight = np.zeros((HOURS, nz)); Pequip = np.zeros((HOURS, nz))
    ua = {"Walls": 0.0, "Roof": 0.0, "Floor": 0.0, "Windows": 0.0, "Doors": 0.0, "Air leakage": 0.0}
    sector_gain = {k: 0.0 for k in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}
    secnames = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    for i, z in enumerate(zones):
        Af[i] = z["area"]
        Hve[i] = RHO_CP_AIR * o["ach"] * z["vol"]
        ua["Air leakage"] += Hve[i]
        sk2 = 0.0
        heq = np.zeros(HOURS)
        for s in z["surfs"]:
            c = cons[s["cons"]]
            A = s["area"]
            if A <= 0:
                continue
            Atot[i] += A
            kap = cons_kappa(c)
            Cm[i] += kap * A
            sk2 += kap * kap * A
            if s["bc"] == "Adiabatic":
                continue
            U = cons_u(c, s["cons"])
            H = U * A
            if s["bc"] == "Ground":
                Hop[i] += H
                heq += H * tground
                ua["Floor"] += H
                continue
            Hop[i] += H
            tot, _b, _c = plane(s["tilt"], s["az"])
            rse = FILMS.get(s["cons"], (0.13, 0.04))[1]
            fr = 1.0 if s["tilt"] < 45 else 0.5
            tsa = Te + rse * (ABSORPT.get(s["cons"], 0.6) * tot - 0.9 * 5.0 * o["sky_dt"] * fr)
            heq += H * tsa
            ua["Roof" if s["cons"] == "roof" else ("Floor" if "floor" in s["cons"] else "Walls")] += H
        for wn in z["wins"]:
            H = wn["area"] * wn["U"]
            Hw[i] += H
            ua["Windows"] += H
            Atot[i] += wn["area"]
            tot, beam, cth = plane(90.0, wn["az"])
            sh = np.zeros(HOURS)
            if wn.get("P", 0) > 0 and wn.get("h", 0) > 0:
                cg = np.cos(saz - math.radians(wn["az"]))
                okk = (cg > 0.02) & (alt > 0)
                tanp = np.where(okk, np.tan(np.clip(alt, 0.0, 1.5)) / np.where(okk, cg, 1.0), 0.0)
                sh = np.clip(wn["P"] * tanp / wn["h"], 0.0, 1.0)
            ang = 1.0 - (1.0 - cth) ** 5                             # fall of glass transmittance at a slanted angle
            dif = (tot - beam) * 0.85
            gain = wn["area"] * wn["g"] * (beam * ang * (1.0 - sh) + dif)
            Psol[:, i] += gain
            sec = secnames[int(((wn["az"] % 360) + 22.5) // 45) % 8]
            sector_gain[sec] += float(gain.sum()) / 1000.0
        for dr in z["doors"]:
            H = dr["area"] * dr["U"]
            Hw[i] += H
            ua["Doors"] += H
            Atot[i] += dr["area"]
        if Hop[i] > 0:
            Teq[:, i] = heq / Hop[i]
        else:
            Teq[:, i] = Te
        Cm[i] = max(Cm[i], 1.0e4 * z["area"])
        Am[i] = (Cm[i] ** 2 / sk2) if sk2 > 0 else 2.5 * z["area"]
        Atot[i] = max(Atot[i], 2.0 * z["area"])
        Am[i] = min(Am[i], Atot[i])
        # internal gains: people, equipment, lights
        occ = np.zeros(HOURS)
        if o["hours"] > 0:
            prof = profile_24(8.0, o["hours"])
            occ = prof[hod] * (dow < o["days"])
        else:
            prof = np.where((np.arange(24) >= 17) | (np.arange(24) < 8), 1.0, 0.25)
            occ = prof[hod]
        eq = np.where(occ > 0.9, 1.0, 0.3) if o["hours"] <= 0 else occ
        lw = z["lights_w"] if z["lights_w"] > 0 else o["lpd"] * z["area"]
        lh = z["lights_h"] if z["lights_h"] > 0 else o["light_hours"]
        lpr = profile_24(18.0, lh)[hod]
        Plight[:, i] = lw * lpr
        Pequip[:, i] = o["equip_w_m2"] * z["area"] * eq
        Pint[:, i] = o["persons_m2"] * z["area"] * o["person_w"] * occ + Pequip[:, i] + Plight[:, i]
    # ---- ISO 13790 coefficients (per zone, vectors)
    Htr_is = 3.45 * Atot
    # the U-values already contain the inside surface film; ISO's Htr_is is a second resistance in series, which would under-count the loss
    # by about a fifth. Scaling the envelope conductances by 1/(1 - H/Htr_is) makes the steady-state loss equal to the plain UA sum.
    f_ = 1.0 / (1.0 - np.minimum((Hop + Hw) / Htr_is, 0.9))
    Hop = Hop * f_
    Hw = Hw * f_
    Htr_ms = np.maximum(9.1 * Am, 1.25 * Hop)
    Htr_em = np.where(Hop > 0, 1.0 / np.maximum(1.0 / np.maximum(Hop, 1e-9) - 1.0 / Htr_ms, 1e-9), 0.0)
    Hve_ = np.maximum(Hve, 1e-6)
    Htr_1 = 1.0 / (1.0 / Hve_ + 1.0 / Htr_is)
    Htr_2 = Htr_1 + Hw
    Htr_3 = 1.0 / (1.0 / Htr_2 + 1.0 / Htr_ms)
    amr = Am / Atot
    fst = 1.0 - amr - Hw / (9.1 * Atot)
    Cm_t = Cm / 3600.0
    hsp, csp = float(o["heat_sp"]), float(o["cool_sp"])
    heat = np.zeros((HOURS, nz)); cool = np.zeros((HOURS, nz))
    tm = np.full(nz, 0.5 * (hsp + csp))

    def solve(i_sol_int, Ph, te, teq_, tm_prev):
        ph_ia = 0.5 * i_sol_int[0]
        gm = amr * (0.5 * i_sol_int[0] + i_sol_int[1])
        gst = fst * (0.5 * i_sol_int[0] + i_sol_int[1])
        pm_tot = gm + Htr_em * teq_ + Htr_3 * (gst + Hw * te + Htr_1 * ((ph_ia + Ph) / Hve_ + te)) / Htr_2
        tm_t = (tm_prev * (Cm_t - 0.5 * (Htr_3 + Htr_em)) + pm_tot) / (Cm_t + 0.5 * (Htr_3 + Htr_em))
        tmm = 0.5 * (tm_t + tm_prev)
        ts = (Htr_ms * tmm + gst + Hw * te + Htr_1 * (te + (ph_ia + Ph) / Hve_)) / (Htr_ms + Hw + Htr_1)
        ta = (Htr_is * ts + Hve_ * te + ph_ia + Ph) / (Htr_is + Hve_)
        return ta, tm_t
    spin = 24 * 12
    for step in range(-spin, HOURS):
        t = step % HOURS
        te = Te[t]
        teq_ = Teq[t]
        isi = (Pint[t], Psol[t])
        ta0, tm0 = solve(isi, np.zeros(nz), te, teq_, tm)
        ph = np.zeros(nz)
        need_h = ta0 < hsp
        need_c = ta0 > csp
        if need_h.any() or need_c.any():
            ta10, _ = solve(isi, np.full(nz, 10.0), te, teq_, tm)
            sp = np.where(need_h, hsp, csp)
            den = np.where(np.abs(ta10 - ta0) > 1e-9, ta10 - ta0, 1e-9)
            ph = np.where(need_h | need_c, 10.0 * (sp - ta0) / den, 0.0)
            _, tm0 = solve(isi, ph, te, teq_, tm)
        tm = tm0
        if step >= 0:
            heat[t] = np.where(ph > 0, ph, 0.0)
            cool[t] = np.where(ph < 0, -ph, 0.0)
    # ---- results
    mon = np.concatenate([[m] * (d * 24) for m, d in enumerate(MDAYS)])
    hs, cs = heat.sum(axis=1) / 1000.0, cool.sum(axis=1) / 1000.0
    mh = [float(hs[mon == m].sum()) for m in range(12)]
    mc = [float(cs[mon == m].sum()) for m in range(12)]
    elec = heat.sum(axis=1) / o["cop_heat"] + cool.sum(axis=1) / max(o["cop_cool"], 0.1) + Plight.sum(axis=1) + Pequip.sum(axis=1)
    return {"label": label, "area": float(Af.sum()), "monthly_heat": mh, "monthly_cool": mc,
            "heat": float(hs.sum()), "cool": float(cs.sum()),
            "lights": float(Plight.sum() / 1000.0), "equip": float(Pequip.sum() / 1000.0),
            "elec_heat": float(hs.sum() / o["cop_heat"]), "elec_cool": float(cs.sum() / max(o["cop_cool"], 0.1)),
            "peak_w": float(elec.max()), "zones": [{"name": z["name"], "area": z["area"], "heat": float(heat[:, i].sum() / 1000.0),
                                                     "cool": float(cool[:, i].sum() / 1000.0)} for i, z in enumerate(zones)],
            "ua": ua, "solar_by_sector": sector_gain, "tground": tground}


def consumption(res, per_m2=True):
    """Annual electricity (kWh) the building uses for heating, cooling and lights (equipment is the same in both buildings and is left out)."""
    e = res["elec_heat"] + res["elec_cool"] + res["lights"]
    return e / res["area"] if per_m2 else e


def demand_va_m2(res):
    return res["peak_w"] / res["area"]


# ---------------------------------------------------------------------------------------------- the reference building
def make_reference(zones, cons, required_r, limit_pct, ref_glass, lpd, light_hours=4.0):
    """Reference zones and constructions: same rooms and shape, deemed-to-satisfy insulation, glass area not above `limit_pct` of the floor
    area (scaled down evenly when the design has more), no shading, plain glass of `ref_glass` = (U, SHGC), lights at the allowed power density.
    required_r: {'ext_wall': total R, 'roof': total R, 'floor_exp': total R}."""
    rc = {k: dict(v) for k, v in cons.items()}
    for key, r in (required_r or {}).items():
        if key in rc and r and r > 0:
            rc[key] = reference_construction(rc[key], key, r)
    floor = sum(z["area"] for z in zones)
    glass = sum(wn["area"] for z in zones for wn in z["wins"])
    k = 1.0
    if floor > 0 and glass > 0 and glass / floor * 100.0 > limit_pct:
        k = (limit_pct / 100.0 * floor) / glass
    rz = []
    for z in zones:
        n = dict(z)
        n["wins"] = [dict(wn, area=wn["area"] * k, U=ref_glass[0], g=ref_glass[1], P=0.0) for wn in z["wins"]]
        n["lights_w"] = lpd * z["area"]
        n["lights_h"] = z["lights_h"] if z["lights_h"] > 0 else light_hours
        rz.append(n)
    return rz, rc, k


def run_rational(zones, cons, w, sun, required_r, limit_pct, ref_glass, lpd, opts=None):
    """Actual and reference buildings and the verdict."""
    o = dict(DEFAULTS)
    o.update(opts or {})
    o["lpd"] = lpd
    act = simulate(zones, cons, w, sun, o, "Actual building")
    rz, rc, k = make_reference(zones, cons, required_r, limit_pct, ref_glass, lpd, o["light_hours"])
    ref = simulate(rz, rc, w, sun, o, "Reference building")
    ca, cr = consumption(act), consumption(ref)
    da, dr = demand_va_m2(act), demand_va_m2(ref)
    return {"actual": act, "reference": ref, "act_cons": ca, "ref_cons": cr, "act_demand": da, "ref_demand": dr,
            "cons_ok": ca <= cr + 0.05, "demand_ok": da <= dr + 0.05, "ok": ca <= cr + 0.05 and da <= dr + 0.05,
            "glass_scale": k, "opts": o}
