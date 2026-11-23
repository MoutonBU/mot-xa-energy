import math, numpy as np
import rd_engine as E

def weather(T=10.0, sun=False):
    z = np.zeros(8760)
    w = {"T": np.full(8760, T), "GHI": z.copy(), "DNI": z.copy(), "DHI": z.copy(), "lat": -34.0, "lon": 22.0}
    alt = np.full(8760, -0.5) if not sun else np.where((np.arange(8760) % 24 >= 8) & (np.arange(8760) % 24 < 16), 0.8, -0.5)
    saz = np.full(8760, math.radians(0.0))
    if sun:
        w["DNI"] = np.where(alt > 0, 700.0, 0.0); w["DHI"] = np.where(alt > 0, 100.0, 0.0); w["GHI"] = w["DNI"] * np.sin(0.8) + w["DHI"]
    return w, (alt, saz)

BRICK = {"layers": [{"t": 0.22, "lam": 0.8, "rfix": 0, "dens": 1800, "cp": 840}], "r_default": 0}
def cons(rwall=0.0, roof_r=3.7):
    wall = {"layers": list(BRICK["layers"]) + ([{"t": 0, "lam": 0, "rfix": rwall, "dens": 20, "cp": 1400}] if rwall else []), "r_default": 0}
    return {"ext_wall": wall, "int_wall": BRICK, "roof": {"layers": [], "r_default": roof_r - 0.14}, "floor_ground": {"layers": [], "r_default": 0.2},
            "floor_int": BRICK, "floor_exp": {"layers": [], "r_default": 1.5}}

def box(win=2.0, glass=(5.6, 0.77), az=180.0):
    z = {"name": "R", "storey": "G", "area": 20.0, "vol": 50.0, "lights_w": 0.0, "lights_h": 0.0,
         "surfs": [{"cons": "ext_wall", "area": 30.0 - win, "az": az, "tilt": 90.0, "bc": "Outdoors"},
                   {"cons": "roof", "area": 20.0, "az": 0.0, "tilt": 0.0, "bc": "Outdoors"},
                   {"cons": "floor_ground", "area": 20.0, "az": 0.0, "tilt": 180.0, "bc": "Ground"}],
         "wins": [{"area": win, "U": glass[0], "g": glass[1], "az": az, "h": 1.2, "P": 0.0, "name": "W1"}] if win else [], "doors": []}
    return [z]

# 1. steady state: constant 10 C outside, no sun, no gains -> heating power = total conductance x (19 - 10)
w, sun = weather(10.0)
c = cons()
opts = {"sky_dt": 0.0, "equip_w_m2": 0.0, "persons_m2": 0.0, "lpd": 0.0, "light_hours": 0.0}
r = E.simulate(box(), c, w, sun, opts)
z = box()[0]
H = sum(E.cons_u(c[s["cons"]], s["cons"]) * s["area"] for s in z["surfs"] if s["bc"] == "Outdoors")
H += E.cons_u(c["floor_ground"], "floor_ground") * 20.0 * (19 - 10) / 9.0     # ground at the annual mean = 10 C too
H += 2.0 * 5.6 + E.RHO_CP_AIR * 0.5 * 50.0
want = H * 9.0 * 8760 / 1000.0
print("steady heating", round(r["heat"]), "expected", round(want))
assert abs(r["heat"] - want) / want < 0.01 and r["cool"] < 1.0

# 2. more insulation -> less heating; hot weather -> cooling
c2 = cons(rwall=1.5)
assert E.simulate(box(), c2, w, sun, opts)["heat"] < r["heat"] * 0.95
wh, sh = weather(32.0)
assert E.simulate(box(), c, wh, sh, opts)["cool"] > 100

# 3. sun through a window facing the sun adds gain and lowers heating; an overhang cuts it
ws, ss = weather(10.0, sun=True)
b_n = E.simulate(box(win=6.0, az=0.0), c, ws, ss, opts)
b_s = E.simulate(box(win=6.0, az=180.0), c, ws, ss, opts)
assert b_n["solar_by_sector"]["N"] > 2 * b_s["solar_by_sector"]["S"]   # the test sun is in the north
assert b_n["heat"] < b_s["heat"]
zz = box(win=6.0, az=0.0); zz[0]["wins"][0]["P"] = 1.0
shaded = E.simulate(zz, c, ws, ss, opts)
assert shaded["solar_by_sector"]["N"] < b_n["solar_by_sector"]["N"] * 0.8 and shaded["heat"] > b_n["heat"]

# 4. reference building: same design with exactly the required insulation passes only when it is better
req = {"ext_wall": 0.6, "roof": 3.7, "floor_exp": 1.5}
good = E.run_rational(box(win=2.0, glass=(2.8, 0.5)), cons(rwall=1.0), w, sun, req, 15.0, (5.6, 0.77), 4.0, opts)
bad = E.run_rational(box(win=8.0, glass=(5.6, 0.77)), cons(), w, sun, req, 15.0, (5.6, 0.77), 4.0, opts)
print("good", round(good["act_cons"], 1), round(good["ref_cons"], 1), "bad", round(bad["act_cons"], 1), round(bad["ref_cons"], 1))
assert good["ok"] or good["act_cons"] <= good["ref_cons"] * 1.02
assert good["act_cons"] < good["ref_cons"]
assert bad["glass_scale"] < 1.0
print("rd_engine tests OK")
