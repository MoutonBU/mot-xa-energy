"""What Mouton's finished council plans (Erf 670, Parkdene Ext 6 / Urbika) say, kept as data and rules for placing a house.

Read from the nine finished A1 sets (site plan, floor plans, notes): the house types, their footprints, how each one sits on its stand, the
figures printed on the sheets (gross floor area, footprint + carport, FAR) and the sewer conventions. The numbers marked 'drawing' were measured
off the vector site plan (1:200, within about 0.1 m); the rest are printed on the sheets."""
import math

# house types used on the plans: gross floor area, footprint + carport (printed), the house box and the carport, and where they were used
HOUSE_TYPES = {
    "UR_115": {"gfa": 115.04, "footprint_carport": 84.52, "house": (10.0, 7.2), "carport": (5.0, 5.0), "plans": ["21", "14", "36", "45"]},
    "UR_100": {"gfa": 100.68, "footprint_carport": None, "house": (14.7, 6.6), "carport": (5.0, 5.0), "plans": ["3", "29"]},
    "UR_156": {"gfa": 156.06, "footprint_carport": 105.12, "house": (11.2, 7.1), "carport": (7.1, 7.1), "plans": ["34", "42"]},
    "UR_157": {"gfa": 156.59, "footprint_carport": 105.18, "house": None, "carport": None, "plans": ["18"]},
    # the 81 and 91 m2 houses on the Street 7071 stands (preliminary site development plans): a 6.75 m wide box, a double carport of 5.0 x 5.0
    "81": {"gfa": 81.0, "footprint_carport": None, "house": (12.0, 6.75), "carport": (5.0, 5.0), "plans": ["6855", "6859"], "dev": "street7071"},
    "91": {"gfa": 91.0, "footprint_carport": None, "house": (13.43, 6.75), "carport": (5.0, 5.0), "plans": ["6845", "7035", "7048", "6997", "7069"], "dev": "street7071"},
}

# one line per finished plan (Erf 670, Ptn n): the house type, the FAR printed on the sheet, the stand area worked back from it (GFA / FAR),
# the house's long side against the street boundary (0 = parallel, 90 = across it, others = a corner or skew stand), and the gaps measured off the site plan
PLANS = [
    {"ptn": "21", "type": "UR_115", "far": 0.32, "stand_area": 357.0, "rot_vs_street": 0, "house_street_gap": 1.0, "carport_at_street": True},
    {"ptn": "14", "type": "UR_115", "far": 0.38, "stand_area": 303.0, "rot_vs_street": 90, "house_street_gap": 1.0, "carport_at_street": True},
    {"ptn": "36", "type": "UR_115", "far": 0.44, "stand_area": 261.0, "rot_vs_street": 90, "house_street_gap": 3.2, "carport_at_street": False},
    {"ptn": "45", "type": "UR_115", "far": 0.42, "stand_area": 274.0, "rot_vs_street": 0, "house_street_gap": 1.0, "carport_at_street": True},
    {"ptn": "18", "type": "UR_157", "far": 0.42, "stand_area": 373.0, "rot_vs_street": None, "house_street_gap": None, "carport_at_street": None},
    {"ptn": "3", "type": "UR_100", "far": None, "stand_area": None, "rot_vs_street": 90, "house_street_gap": 2.0, "carport_at_street": True},
    {"ptn": "34", "type": "UR_156", "far": 0.43, "stand_area": 363.0, "rot_vs_street": 45, "house_street_gap": 1.1, "carport_at_street": True},
    {"ptn": "42", "type": "UR_156", "far": None, "stand_area": None, "rot_vs_street": 5, "house_street_gap": 2.5, "carport_at_street": True},
    {"ptn": "29", "type": "UR_100", "far": None, "stand_area": None, "rot_vs_street": 0, "house_street_gap": 1.2, "carport_at_street": True},
]

# the preliminary site development plans on the Street 7071 stands (14.0 x 19.3 m and corner stands, 1 m servitudes, a no-access road): how each house was placed
PLANS_7071 = [
    {"stand": "6855", "type": "81", "stand_size": (14.01, 19.30), "carport_street_gap": 0.5, "carport_house_gap": 2.26, "note": "house along the side boundary, carport at the street corner; no access from Lebombo Road"},
    {"stand": "6859", "type": "81", "stand_size": (14.01, 19.34), "carport_street_gap": 0.5, "carport_house_gap": 2.27, "note": "same layout; the stand is cut by a splay on the no-access road"},
    {"stand": "6845", "type": "91", "stand_size": (13.82, 18.0), "carport_street_gap": 0.0, "carport_house_gap": None, "note": "1 m servitude on the long side; the house had a boundary wall problem at the back"},
    {"stand": "7035", "type": "91", "stand_size": None, "carport_street_gap": 0.5, "carport_house_gap": 2.54, "note": "narrow skew stand: house square to the 1 m servitude side, carport at the street"},
    {"stand": "7048", "type": "91", "stand_size": None, "carport_street_gap": 0.0, "carport_house_gap": 2.54, "note": "corner stand: house along the servitude, carport at the corner"},
    {"stand": "6997", "type": "91", "stand_size": None, "carport_street_gap": None, "carport_house_gap": None, "note": "three tries, none fits: the stand is too small for a 91 m2 house with the carport"},
    {"stand": "7069", "type": "91", "stand_size": None, "carport_street_gap": None, "carport_house_gap": None, "note": "two layouts compared: the house along the side boundary with the carport at the street (chosen) beat the house across the stand against the road, which ran into the service circles"},
]

# the sewer and site conventions that are the same on every plan
CONVENTIONS = {
    "sewer_pipe": "110 mm uPVC", "fall": 50, "min_il": 450, "eyes": "IE at the joint and every bend, RE at the end of every run and at the wall",
    "wp_vv": "50 dia WP's and 110 dia GI VV at the wet wall", "marks": ("SD", "FD", "KD", "G", "DB"),
    "boundary_wall": "1.2 m high pre-cast concrete wall on the side and rear boundaries", "storm": "stormwater flows towards the street",
    "carport_gap": 1.0, "street_building_line": 1.0, "carport_size": 5.0,
    # Street 7071 stands: B/L 3 m to the street and the no-access road, 2 m to a neighbour, 1 m to a 1 m servitude; the carport 0.5 m off the street boundary
    "b7071": {"street": 3.0, "no_access": 3.0, "side": 2.0, "servitude": 1.0}, "carport_street_gap_7071": 0.5, "carport_house_gap_7071": 2.25,
    "storm_arrow": "a blue Stormwater Flow arrow on every plan, pointing down the fall of the stand (usually towards the street)",
}

# the rules those plans give, in the order the tool uses them when it suggests a placement
# how far round a stand the township reader looks when a stand is cut out of a big site drawing (metres). These are rules, not tuning: a stand on a bend
# or a corner needs the road both ways round the bend, the kerb on the far side of the street, and every main that serves it (Blue Hills Ext 120, stands
# 2121, 2122, 2228, 2236: the road runs 60 to 100 m round the corner and the mains follow it).
TOWNSHIP_SEARCH = {
    "road": 130.0,         # kerbs, road edges, road names: the whole bend, both sides of the street, the next streets
    "services": 90.0,      # sewer, water, electrical, stormwater lines and their symbols
    "stands": 45.0,        # neighbouring stands and their numbers
    "main": 40.0,          # a main line is taken from the nearest run of lines that comes this close to the stand's street boundary
}

RULES = [
    "The carport sits against the street boundary (the entry), 5.0 x 5.0 m, or 7.1 x 7.1 m when it is a double.",
    "The house is 1.0 m clear of the carport, and 1.0 to 2.5 m behind the street boundary.",
    "The house long side runs parallel to the street, or square to the nearest boundary on a corner or skew stand.",
    "Sewer: 110 mm at fall 1:50, Min IL 450 at the gully, an IE at every joint and bend, an RE at the end of every run.",
    "Side and rear boundaries carry a 1.2 m pre-cast concrete wall; stormwater falls to the street.",
    "Street 7071 stands: building lines 3 m to the street and to the no-access road, 2 m to a neighbour, 1 m to a servitude; the carport 5.0 x 5.0 sits 0.5 m off the street boundary and about 2.25 m from the house; the house runs along the side boundary (outlet at the far end, sewer in the servitude side), never across the stand against the road.",
    "Blue Hills Ext 120 (the MCP site plan, 204 stands, 39 houses placed): stands about 14 x 22 m (280 to 390 m2); the carport is a 5.0 x 5.0 m box with its front edge 1.0 m behind the street boundary, in the left or the right corner 1.0 m off the side boundary; the house (about 10 m wide, 12.7 to 15 m long with its patio / braai) starts 2.8 to 6.0 m from the street (beside or behind the carport) and runs back to the rear boundary; mains and connections are in the road.",
    "On the finished plans the footprint with the carport covers 84 to 105 m2 on stands of 260 to 375 m2 (FAR 0.32 to 0.44).",
]


def house_type(w, d, tol=0.45):
    """the house type whose box is this size (either way round), or None"""
    for name, t in HOUSE_TYPES.items():
        if not t["house"]:
            continue
        a, b = t["house"]
        if (abs(w - a) <= tol and abs(d - b) <= tol) or (abs(w - b) <= tol and abs(d - a) <= tol):
            return name
    return None


def preferred_gap(state):
    """the clear distance wanted between the carport and the house: 1.0 m on the Erf 670 plans, about 2.25 m on the 81 / 91 m2 plans"""
    h = state.get("house") or {}
    ht = house_type(h.get("w", 0), h.get("d", 0)) if not h.get("poly") else None
    return CONVENTIONS["carport_house_gap_7071"] if ht in ("81", "91") else CONVENTIONS["carport_gap"]


def notes_for(state, stand_area):
    """short lines comparing this placement with the finished plans"""
    out = []
    h = state.get("house") or {}
    ht = house_type(h.get("w", 0), h.get("d", 0)) if not h.get("poly") else None
    if ht in ("81", "91"):
        t = HOUSE_TYPES[ht]
        out.append("This house is the %s m2 type, as on the Street 7071 plans (Stands %s). They keep the carport 0.5 m off the street boundary and about 2.25 m from the house, with the house along the side boundary."
                   % (ht, ", ".join(t["plans"])))
        ht = None
    if ht:
        t = HOUSE_TYPES[ht]
        plans = ", ".join("Ptn " + p for p in t["plans"])
        far = t["gfa"] / stand_area if stand_area else 0
        out.append("This house is the %s type (%s on Erf 670). Gross floor area %.0f m2 gives FAR %.2f on this stand; your plans ran 0.32 to 0.44." % (ht, plans, t["gfa"], far))
        if far > 0.47:
            out.append("FAR %.2f is higher than any of your finished plans (highest 0.44)." % far)
    c = state.get("carport")
    if c and h:
        g = _gap_house_carport(state)
        want = preferred_gap(state)
        if g is not None and g < min(want, CONVENTIONS["carport_gap"]) - 0.05:
            out.append("The carport is %.2f m from the house; your plans keep at least %.1f m." % (g, CONVENTIONS["carport_gap"]))
    return out


def _gap_house_carport(state):
    import site_engine as se
    try:
        hp = se.house_poly(state["house"])
        cp = se.carport_poly(state.get("carport"))
    except Exception:
        return None
    if not cp:
        return None
    best = None
    for i in range(len(hp)):
        for j in range(len(cp)):
            d = _seg_seg(hp[i], hp[(i + 1) % len(hp)], cp[j], cp[(j + 1) % len(cp)])
            best = d if best is None else min(best, d)
    return best


def _seg_seg(a, b, c, d):
    def pt_seg(p, s, e):
        dx, dy = e[0] - s[0], e[1] - s[1]
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy) / L2))
        return math.hypot(p[0] - s[0] - t * dx, p[1] - s[1] - t * dy)
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))
