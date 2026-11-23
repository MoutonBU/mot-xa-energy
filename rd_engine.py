"""Built-in hourly energy model for the SANS 10400-XA rational design (the 'performance route').

Method: the hourly 5R1C model of EN ISO 13790 (annex C) / ISO 52016, one thermal zone per room, ideal-loads heating and cooling
between two set-points, 8760 hours of the weather file. The same building is run twice: as designed, and as the REFERENCE building
(same shape, same rooms, same weather and use, with the deemed-to-satisfy envelope of the climate zone). The design passes when its
annual energy consumption and its peak electrical demand are not more than the reference building's.

Only numpy is used. No Qt: this file can be tested on its own (see test_rd_engine.py).
Frame: surfaces carry `az` = degrees clockwise from true north (the outward normal), `tilt` 90 = wall, 0 = roof.
"""
import math
import re as _re
import numpy as np

HOURS = 8760
MDAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
RHO_CP_AIR = 0.34                  # Wh/(m3 K): air density x specific heat / 3600
FILMS = {"ext_wall": (0.13, 0.04), "roof": (0.10, 0.04), "floor_exp": (0.17, 0.04), "floor_ground": (0.17, 1.0),   # (inside film, outside film / soil)
         "int_wall": (0.12, 0.12), "floor_int": (0.17, 0.10)}
GROUND_SOIL_R = 1.0                # m2K/W of soil below a slab on grade (same in both buildings, so it cancels in the comparison)
DOOR_LEAF_R = 0.25
ABSORPT = {"ext_wall": 0.6, "roof": 0.6, "floor_exp": 0.6}
# SANS 10400-XA:2021 Annex B: 75 W sensible per person; lights at table 12; appliance gain 15 W/m2 (G1), 5 W/m2 (F1), none for any other occupancy;
# 19-25 C; hot water at 60 C per table 10; schedules from table B.2 (H3 / H4 loaded; other occupancies use the simple hours given).
DEFAULTS = {"ach": 0.5, "heat_sp": 19.0, "cool_sp": 25.0, "cop_heat": 1.0, "cop_cool": 3.0,
            "lpd": 4.0, "light_hours": 4.0, "persons_m2": 0.04, "pop": 0.0, "person_w": 75.0, "equip_w_m2": 0.0, "hours": 0.0, "days": 7, "sky_dt": 11.0,
            "occ": "H4", "dhw_l_pd": 115.0, "dhw_kind": "resistance", "dhw_cop": 3.0, "dhw_solar": 0.0, "dhw_gas_eff": 0.85, "dhw_on": True}
# Table B.2, H3 / H4: fractions for 0-8, 8-11, 11-18, 18-22, 22-24 h
B2_EDGES = [0, 8, 11, 18, 22, 24]
B2 = {"occ": {"wd": [0.88, 0.37, 0.36, 0.73, 1.0], "sa": [1.0, 0.43, 0.43, 0.97, 1.0], "su": [1.0, 0.43, 0.43, 0.97, 1.0]},
      "light": {"wd": [0.13, 0.13, 0.14, 0.24, 0.10], "sa": [0.09, 0.20, 0.14, 0.30, 0.18], "su": [0.09, 0.20, 0.14, 0.30, 0.18]},
      "plug": {"wd": [0.53, 0.57, 0.59, 0.78, 0.60], "sa": [0.53, 0.57, 0.59, 0.78, 0.60], "su": [0.53, 0.57, 0.59, 0.78, 0.60]}}
APPLIANCE_W_M2 = {"G1": 15.0, "F1": 5.0}


def b2_series(load, dow):
    """8760-hour utilisation series from table B.2 (day 1 of the year is taken as a Monday; public holidays are not marked)."""
    out = np.zeros(HOURS)
    for h in range(HOURS):
        d = dow[h]
        key = "wd" if d < 5 else ("sa" if d == 5 else "su")
        hr = h % 24
        for k in range(5):
            if B2_EDGES[k] <= hr < B2_EDGES[k + 1]:
                out[h] = B2[load][key][k]
                break
    return out


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
             "lights_w": float(z.get("lights_w", 0.0)), "lights_h": float(z.get("lights_h", 0.0)), "surfs": [], "wins": [], "doors": [],
             "habitable": not _re.search(r"garage|carport|stoep|stoop|patio|veranda|porch|deck|balcon|store|shed", z["label"], _re.I)}
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
def horizon_mask(sun, horizon):
    """True where the sun is above the skyline of the neighbouring buildings. horizon = 36 altitudes in degrees, one per 10 degrees of compass bearing (0 = north)."""
    if not horizon:
        return None
    hz = np.asarray([float(x) for x in horizon], float)
    alt, saz = sun
    idx = np.rint((np.degrees(saz) % 360.0) / 10.0).astype(int) % len(hz)
    return np.degrees(alt) > hz[idx]


def plane_irradiance(w, sun, tilt, az, mask=None):
    """(total, beam on the plane, cos of incidence) in W/m2 on a surface of this tilt and azimuth, per hour."""
    alt, saz = sun
    DN = np.asarray(w["DNI"][:HOURS], float)
    DF = np.asarray(w["DHI"][:HOURS], float)
    G = np.asarray(w["GHI"][:HOURS], float)
    b = math.radians(tilt)
    cth = np.sin(alt) * math.cos(b) + np.cos(alt) * math.sin(b) * np.cos(saz - math.radians(az))
    cth = np.where(alt > 0, cth, 0.0)
    beam = DN * np.clip(cth, 0.0, None)
    if mask is not None:                                           # a neighbouring building hides the sun: no beam in those hours
        beam = np.where(mask, beam, 0.0)
        cth = np.where(mask, cth, 0.0)
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
    hmask = horizon_mask(sun, o.get("horizon"))

    def plane(tilt, az):
        k = (round(tilt), round(az / 5.0) * 5 % 360)
        if k not in cache:
            cache[k] = plane_irradiance(w, sun, k[0], k[1], hmask)
        return cache[k]
    Hve = np.zeros(nz); Hw = np.zeros(nz); Hop = np.zeros(nz); Atot = np.zeros(nz); Cm = np.zeros(nz); Am = np.zeros(nz); Af = np.zeros(nz)
    Teq = np.zeros((HOURS, nz)); Psol = np.zeros((HOURS, nz)); Pint = np.zeros((HOURS, nz)); Plight = np.zeros((HOURS, nz)); Pequip = np.zeros((HOURS, nz))
    ua = {"Walls": 0.0, "Roof": 0.0, "Floor": 0.0, "Windows": 0.0, "Doors": 0.0, "Air leakage": 0.0}
    sector_gain = {k: 0.0 for k in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}
    secnames = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    occ_b2, lig_b2, plug_b2 = b2_series("occ", dow), b2_series("light", dow), b2_series("plug", dow)
    pop_area = sum(z["area"] for z in zones if z.get("habitable", True))
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
        # internal gains (Annex B): people at 75 W sensible, lights at the table 12 power, appliances only for G1 / F1
        h34 = str(o["occ"]).startswith(("H3", "H4"))
        if h34:
            occ = occ_b2
            lfr = lig_b2
            pfr = plug_b2
        else:
            if o["hours"] > 0:
                occ = profile_24(8.0, o["hours"])[hod] * (dow < o["days"])
            else:
                occ = np.where((hod >= 17) | (hod < 8), 1.0, 0.25)
            lfr = profile_24(18.0, o["light_hours"] if o["light_hours"] > 0 else 4.0)[hod]
            pfr = np.where(occ > 0.9, 1.0, 0.3)
        lw = z["lights_w"] if z["lights_w"] > 0 else o["lpd"] * z["area"]
        Plight[:, i] = lw * lfr
        Pequip[:, i] = o["equip_w_m2"] * z["area"] * pfr
        if o["pop"] > 0:
            share = z["area"] / pop_area if z.get("habitable", True) and pop_area > 0 else 0.0
            npers = o["pop"] * share
        else:
            npers = o["persons_m2"] * z["area"] if z.get("habitable", True) else 0.0
        Pint[:, i] = npers * o["person_w"] * occ + Pequip[:, i] + Plight[:, i]
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
    # ---- hot water (table 10 litres, stored at 60 C), same people and hours in both buildings
    dhw_el = np.zeros(HOURS)
    dhw_gas = 0.0
    dhw_q = 0.0
    pop = o["pop"] if o["pop"] > 0 else o["persons_m2"] * pop_area
    if o.get("dhw_on", True) and pop > 0 and o["dhw_l_pd"] > 0:
        mon_h = np.concatenate([[m] * (d * 24) for m, d in enumerate(MDAYS)])
        tm_air = np.array([Te[mon_h == m].mean() for m in range(12)])
        tcold = np.clip(tm_air, 10.0, 22.0)[mon_h]
        daily = pop * o["dhw_l_pd"] * 4.186 * (60.0 - tcold) / 3600.0                 # kWh a day, as an hourly series that is spread below
        prof = np.zeros(24)
        prof[6:8] = 0.2; prof[18:21] = 0.2                                           # 40% of the day's water in the morning, 60% in the evening
        q = daily * prof[hod]
        dhw_q = float(q.sum())
        kind = o["dhw_kind"]
        if kind == "ref":                                                            # reference: half from electric elements, half from a non-resistance source
            dhw_el = 0.5 * q + 0.5 * q / max(o["dhw_cop"], 0.5)
        elif kind == "heatpump":
            dhw_el = q / max(o["dhw_cop"], 0.5)
        elif kind == "solar":
            dhw_el = q * (1.0 - min(1.0, max(0.0, o["dhw_solar"])))
        elif kind == "gas":
            dhw_gas = float(q.sum()) / max(o["dhw_gas_eff"], 0.3)
        else:
            dhw_el = q
    # ---- results
    mon = np.concatenate([[m] * (d * 24) for m, d in enumerate(MDAYS)])
    hs, cs = heat.sum(axis=1) / 1000.0, cool.sum(axis=1) / 1000.0
    mh = [float(hs[mon == m].sum()) for m in range(12)]
    mc = [float(cs[mon == m].sum()) for m in range(12)]
    elec = heat.sum(axis=1) / o["cop_heat"] + cool.sum(axis=1) / max(o["cop_cool"], 0.1) + Plight.sum(axis=1) + Pequip.sum(axis=1) + dhw_el * 1000.0
    mmax = [float(elec[mon == m].max()) for m in range(12)]
    return {"label": label, "area": float(Af.sum()), "monthly_heat": mh, "monthly_cool": mc,
            "heat": float(hs.sum()), "cool": float(cs.sum()),
            "lights": float(Plight.sum() / 1000.0), "equip": float(Pequip.sum() / 1000.0),
            "elec_heat": float(hs.sum() / o["cop_heat"]), "elec_cool": float(cs.sum() / max(o["cop_cool"], 0.1)),
            "dhw_q": dhw_q, "dhw_elec": float(dhw_el.sum()), "dhw_gas": dhw_gas, "pop": pop,
            "peak_w": float(elec.max()), "avg_peak_w": float(np.mean(mmax)), "monthly_peak_w": mmax,
            "zones": [{"name": z["name"], "area": z["area"], "heat": float(heat[:, i].sum() / 1000.0),
                       "cool": float(cool[:, i].sum() / 1000.0)} for i, z in enumerate(zones)],
            "ua": ua, "solar_by_sector": sector_gain, "tground": tground}


def consumption(res, per_m2=True):
    """Annual energy (kWh) the building uses: heating, cooling, lights, appliances (G1 / F1 only) and hot water."""
    e = res["elec_heat"] + res["elec_cool"] + res["lights"] + res["equip"] + res["dhw_elec"] + res["dhw_gas"]
    return e / res["area"] if per_m2 else e


def demand_va_m2(res):
    """Average demand: the highest hour of each month, averaged over the 12 months, per m2 (power factor 1). The single highest hour is res['peak_w']."""
    return res["avg_peak_w"] / res["area"]


# ---------------------------------------------------------------------------------------------- the reference building
def table4_row(table, pct):
    for row in table:
        if pct <= row[0] + 1e-9:
            return row
    return table[-1]


def make_reference(zones, cons, required_r, table4, clear_glass, lpd, light_hours=4.0):
    """Reference zones and constructions (SANS 10400-XA:2021 clause 3.16 and 4.4): same rooms, shape and orientation, the deemed-to-satisfy insulation, and
    the same glass AREA as the design (clause 5.3 lets the area go above 20% when table 4 is met) with the table 4 U-value and SHGC for each storey's
    glass share (no limit up to 20%: plain clear glass). The SHGC used is the table's stricter column (no shading credit), and no shading is modelled.
    Lights at the table 12 power. required_r: {'ext_wall': total R, 'roof': total R, 'floor_exp': total R}."""
    rc = {k: dict(v) for k, v in cons.items()}
    for key, r in (required_r or {}).items():
        if key in rc and r and r > 0:
            rc[key] = reference_construction(rc[key], key, r)
    by_storey = {}
    for z in zones:
        d = by_storey.setdefault(z["storey"], [0.0, 0.0])
        d[0] += z["area"]
        d[1] += sum(wn["area"] for wn in z["wins"])
    notes = {}
    rz = []
    for z in zones:
        fl, gl = by_storey[z["storey"]]
        pct = gl / fl * 100.0 if fl > 0 else 0.0
        row = table4_row(table4, pct)
        if row[1]:
            u, g = float(row[1]), float(row[3])
        else:
            u, g = clear_glass
        notes[z["storey"]] = {"pct": pct, "U": u, "g": g}
        n = dict(z)
        n["wins"] = [dict(wn, U=u, g=g, P=0.0) for wn in z["wins"]]
        n["lights_w"] = lpd * z["area"]
        rz.append(n)
    return rz, rc, notes


def run_rational(zones, cons, w, sun, required_r, table4, clear_glass, lpd, opts=None, dhw_design=None):
    """Design and reference buildings and the verdict. dhw_design: {'dhw_kind','dhw_cop','dhw_solar','dhw_gas_eff'} for the design's hot water."""
    o = dict(DEFAULTS)
    o.update(opts or {})
    o["lpd"] = lpd
    od = dict(o)
    od.update(dhw_design or {})
    act = simulate(zones, cons, w, sun, od, "Actual building")
    rz, rc, notes = make_reference(zones, cons, required_r, table4, clear_glass, lpd, o["light_hours"])
    orf = dict(o)
    orf["dhw_kind"] = "ref"
    ref = simulate(rz, rc, w, sun, orf, "Reference building")
    ca, cr = consumption(act), consumption(ref)
    da, dr = demand_va_m2(act), demand_va_m2(ref)
    return {"actual": act, "reference": ref, "act_cons": ca, "ref_cons": cr, "act_demand": da, "ref_demand": dr,
            "cons_ok": ca <= cr + 0.05, "demand_ok": da <= dr + 0.05, "ok": ca <= cr + 0.05 and da <= dr + 0.05,
            "ref_glass": notes, "opts": od}


# ---------------------------------------------------------------------------------------------- what to change to pass
def _add_r(c, r):
    """More insulation in a construction: a plain resistance layer on the outside."""
    c = {"layers": [dict(l) for l in (c.get("layers") or [])], "r_default": c.get("r_default", 0.0), "name": c.get("name", "")}
    if c["layers"]:
        c["layers"].insert(0, {"name": "Added insulation", "t": 0.0, "lam": 0.0, "rfix": r, "dens": 20.0, "cp": 1400.0})
    else:
        c["r_default"] = c["r_default"] + r
    return c


def advice_measures(shade_mult=0.54):
    """Changes a designer can make, as (group, name, function(state) -> text or None). state = {'z','c','o','d'}: zones, constructions, options, hot water."""
    def dhw_hp(st):
        if st["d"].get("dhw_kind") in ("heatpump", "solar"):
            return None
        st["d"] = dict(st["d"], dhw_kind="heatpump", dhw_cop=3.0)
        return "Heat the hot water with a heat pump (COP 3) instead of electric elements"

    def dhw_solar(st):
        if st["d"].get("dhw_kind") == "solar" and st["d"].get("dhw_solar", 0) >= 0.6:
            return None
        st["d"] = dict(st["d"], dhw_kind="solar", dhw_solar=0.6)
        return "Heat the hot water with a solar water heater (60% of the heat) and electric back-up"

    def roof(st):
        st["c"] = dict(st["c"], roof=_add_r(st["c"]["roof"], 1.5))
        return "Add 1.5 m2K/W more insulation in the ceiling (about 60 mm of glasswool or 55 mm of PIR on top of what is there)"

    def wall(st):
        st["c"] = dict(st["c"], ext_wall=_add_r(st["c"]["ext_wall"], 0.7))
        return "Add 0.7 m2K/W of insulation to the outside walls (about 25 mm of EPS or 30 mm of PIR)"

    def glass1(st):
        n = 0
        for z in st["z"]:
            for wn in z["wins"]:
                if wn["U"] > 3.0:
                    wn["U"], wn["g"] = 3.0, min(wn["g"], 0.65)
                    n += 1
        return "Fit double glazing (U 3.0, SHGC 0.65) in all windows" if n else None

    def glass2(st):
        n = 0
        for z in st["z"]:
            for wn in z["wins"]:
                if wn["U"] > 2.0:
                    wn["U"], wn["g"] = 2.0, min(wn["g"], 0.45)
                    n += 1
        return "Fit low-e double glazing (U 2.0, SHGC 0.45) in all windows" if n else None

    def shade(st):
        n = 0
        for z in st["z"]:
            for wn in z["wins"]:
                a = wn["az"] % 360
                if (a >= 270 or a <= 100) and wn["P"] < shade_mult * wn["h"] - 1e-9:
                    wn["P"] = shade_mult * wn["h"]
                    n += 1
        return ("Shade the north, east and west windows with a projection of %.2f x the window height (verandah, canopy or eaves)" % shade_mult) if n else None

    def less_glass(st):
        n = 0
        for z in st["z"]:
            for wn in z["wins"]:
                a = wn["az"] % 360
                if 225 <= a <= 315 or 45 <= a <= 135:
                    cut = wn["area"] * 0.25
                    wn["area"] -= cut
                    for sf in z["surfs"]:
                        if sf["cons"] == "ext_wall" and abs(((sf["az"] - wn["az"]) + 180) % 360 - 180) < 1.0:
                            sf["area"] += cut
                            break
                    n += 1
        return "Make the east and west windows 25% smaller" if n else None

    def light(st):
        for z in st["z"]:
            z["lights_w"] = 0.75 * (z["lights_w"] if z["lights_w"] > 0 else st["o"]["lpd"] * z["area"])
        return "Lower the lighting power by 25% (LED fittings, fewer points)"

    def air(st):
        if st["o"].get("ach", 0.5) <= 0.3:
            return None
        st["o"] = dict(st["o"], ach=0.3)
        return "Seal the building better: air leakage 0.3 air changes an hour (clause 5.7)"

    def hvac(st):
        if st["o"].get("cop_heat", 1.0) >= 3.0:
            return None
        st["o"] = dict(st["o"], cop_heat=3.0)
        return "Heat the rooms with an air-conditioner / heat pump (COP 3) instead of electric elements"
    return [("dhw", "dhw_hp", dhw_hp), ("dhw", "dhw_solar", dhw_solar), ("roof", "roof", roof), ("wall", "wall", wall), ("glass", "glass1", glass1),
            ("glass", "glass2", glass2), ("shade", "shade", shade), ("area", "less_glass", less_glass), ("light", "light", light), ("air", "air", air),
            ("hvac", "hvac", hvac)]


def advise(zones, cons, w, sun, opts, dhw_design, lpd, ref_cons, ref_demand, shade_mult=0.54, max_steps=6):
    """Each change on its own (how much energy and demand it saves), then the order of changes that gets the design to or under the reference.
    Returns {'single': [...], 'plan': [...], 'ok': bool, 'base': (cons, demand)}."""
    import copy
    o0 = dict(DEFAULTS)
    o0.update(opts or {})
    o0["lpd"] = lpd

    def run(st):
        od = dict(st["o"])
        od.update(st["d"] or {})
        r = simulate(st["z"], st["c"], w, sun, od)
        return consumption(r), demand_va_m2(r)
    base_st = {"z": zones, "c": cons, "o": o0, "d": dict(dhw_design or {})}
    b_c, b_d = run(base_st)
    ok = lambda c, d: c <= ref_cons + 0.05 and d <= ref_demand + 0.05
    meas = advice_measures(shade_mult)
    singles = []
    for grp, key, fn in meas:
        st = {"z": copy.deepcopy(zones), "c": dict(cons), "o": dict(o0), "d": dict(dhw_design or {})}
        txt = fn(st)
        if not txt:
            continue
        c_, d_ = run(st)
        singles.append({"group": grp, "key": key, "text": txt, "cons": c_, "demand": d_, "dcons": c_ - b_c, "ddemand": d_ - b_d, "passes": ok(c_, d_)})
    singles.sort(key=lambda s: s["dcons"])
    plan, st = [], {"z": copy.deepcopy(zones), "c": dict(cons), "o": dict(o0), "d": dict(dhw_design or {})}
    cur_c, cur_d = b_c, b_d
    used = set()
    done = ok(cur_c, cur_d)
    while not done and len(plan) < max_steps:
        best = None
        for grp, key, fn in meas:
            if grp in used:
                continue
            t = {"z": copy.deepcopy(st["z"]), "c": dict(st["c"]), "o": dict(st["o"]), "d": dict(st["d"])}
            txt = fn(t)
            if not txt:
                continue
            c_, d_ = run(t)
            score = (c_ - ref_cons) + (d_ - ref_demand) * 0.5
            if best is None or score < best[0]:
                best = (score, grp, txt, t, c_, d_)
        if best is None or best[4] >= cur_c - 1e-6 and best[5] >= cur_d - 1e-6:
            break
        _s, grp, txt, st, cur_c, cur_d = best
        used.add(grp)
        plan.append({"text": txt, "cons": cur_c, "demand": cur_d})
        done = ok(cur_c, cur_d)
    return {"single": singles, "plan": plan, "ok": done, "base": (b_c, b_d), "ref": (ref_cons, ref_demand)}
