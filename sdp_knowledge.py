"""What the SDP Creator knows about how a finished Site Development Plan looks and how the parking goes.
It was read from the Mystic Views SDP (Erf 6483, Hartenbos, Mossel Bay): the Rev 19 PDF (schedules, parking, phases) and the Archicad drawing
(sdp_reference_data.py: every bay, building and block label). More plans can be added to REFERENCES the same way; the helpers below use all of them."""
import math

# ---- one finished SDP, as read from the sheet
MYSTIC_VIEWS = {
    "name": "Mystic Views, Erf 6483 Hartenbos",
    "source": "000_Global_SDP.pdf (Rev 19, 2026/11/09) and Mystic_Views_001_SG_SDP5.dwg",
    "stand_m2": 51167.35,
    "units": 343,
    # the modules: one row of the unit schedule each (areas are for one block)
    "modules": {
        "Maxi": {"use": "Residential - 1, 2 & 3 Bed", "storeys": 3, "units": 15, "unit_m2": 887.250, "patio_m2": 131.850, "common_m2": 130.254, "gross_m2": 1149.354, "count": 13},
        "Standard 3-storey": {"use": "Residential - 1, 2 & 3 Bed", "storeys": 3, "units": 12, "unit_m2": 726.600, "patio_m2": 85.386, "common_m2": 57.066, "gross_m2": 869.052, "count": 10},
        "Standard 2-storey": {"use": "Residential - 1, 2 & 3 Bed", "storeys": 2, "units": 8, "unit_m2": 484.400, "patio_m2": 56.924, "common_m2": 38.044, "gross_m2": 579.368, "count": 3},
        "Restaurant and residential": {"use": "Restaurant (ground) / 4 residential units (first)", "storeys": 2, "units": 4, "unit_m2": 484.400, "patio_m2": 56.924, "common_m2": 38.044, "gross_m2": 579.368, "count": 1},
    },
    # the gate house system and the amenities, with the areas they were drawn at
    "gatehouse": [("Guard House", "Gate house - ground floor", 19.062, 1), ("Ablution Area", "Gate house - ground floor", 30.305, 1),
                  ("Gate House Office", "Gate house - first floor", 60.200, 1), ("Refuse Area", "Gate house - outside service area", 64.699, 0)],
    "amenities": [("Garages (156 bays)", "Garages - parking", 3174.600, 1), ("Club House / Pool House", "Club house, patios & pool (amenity)", 313.330, 1)],
    "parking": {"ratio": 1.5, "visitor_per": 0, "required": 515, "provided_counted": 520, "types": {"Covered Parkings": (176, True), "Garage Parking": (156, True),
                "Open Parking": (124, True), "Shade Cloth Parking": (64, True), "Tandem Parking (Grass Blocks)": (86, False)},
                "note": "Required bays are for residential units only. Tandem parking on grass blocks is on site but is not counted toward the 1.5 ratio."},
    "coverage_pct": 24.09, "footprints_m2": 12326.21, "far": 0.5787, "gross_floor_m2": 29611.79,
    "hard_surface": {"Walkways to blocks": 546.6, "Internal roads": 23033.0},
    "phases": [("Phase 1", "H1 + H18 - H26 + MU-01 + Gate House + 78 garages", 16, 154, 13834.474),
               ("Phase 2", "H2 - H17 + Pool House + 78 garages (future)", 18, 189, 15777.316)],
    # how the bays were drawn (read from the DWG): 2.5 m wide, 5.5 m deep, two rows back to back are 11.0 m, the aisle between facing rows 7.0 to 7.5 m
    "layout": {"bay_w_m": 2.5, "bay_l_m": 5.5, "aisle_m": (7.0, 7.5), "back_to_back_m": 11.0,
               "notes": ["Covered bays (C) run in rows along the road, beside the blocks.", "Tandem bays (TP) sit at the end of a covered row or in front of a bay, on grass blocks; they are not counted.",
                         "Open bays (O) run along the roads where there is room; shade cloth bays (S) are grouped away from the blocks and do not count toward coverage.",
                         "The refuse area sits with the gate house, outside at the service side."]},
}
REFERENCES = [MYSTIC_VIEWS]

# the parking mix of the counted bays (covered, garage, open, shade cloth), as a share
MIX = {"Covered": 176, "Garage": 156, "Open": 124, "Shade cloth": 64}


def module_preset(name):
    """the usual block of that type: units, storeys and the areas of one block. None when it is not a known module"""
    for ref in REFERENCES:
        m = ref["modules"].get(name)
        if m:
            return dict(m)
    return None


def module_names():
    out = []
    for ref in REFERENCES:
        for k in ref["modules"]:
            if k not in out:
                out.append(k)
    return out


def bays_needed(units, ratio=None):
    """bays the units need: 1.5 a unit in the reference plan, rounded up, residential units only"""
    r = MYSTIC_VIEWS["parking"]["ratio"] if ratio is None else ratio
    return int(math.ceil(units * r - 1e-9))


def parking_mix(bays):
    """how many covered, garage, open and shade cloth bays make up `bays` counted bays, in the proportions of the reference plan"""
    tot = float(sum(MIX.values()))
    out = {k: int(round(bays * v / tot)) for k, v in MIX.items()}
    k = max(out, key=out.get)
    out[k] += bays - sum(out.values())
    return out


def refuse_area(units):
    """the refuse area (m2) for that many units, in the proportion of the reference plan (64.7 m2 for 343 units)"""
    ref = [r for r in REFERENCES if r.get("units")]
    per = sum(next(a for n, u, a, c in r["gatehouse"] if n == "Refuse Area") for r in ref) / float(sum(r["units"] for r in ref))
    return per * units


def gatehouse_set():
    """the parts of the gate house system: (name, use, area m2, counts as floor area)"""
    return list(MYSTIC_VIEWS["gatehouse"])


def reference_plan():
    """the drawn reference: bays, building outlines, block labels (metres)"""
    import sdp_reference_data as d
    return {"bays": d.BAYS, "buildings": d.BUILDINGS, "labels": d.BLOCK_LABELS, "sg": d.SG_LINES}


def layout_stats():
    """measured from the drawn plan: how far apart the bays are along a row (median, m) and per bay type"""
    import sdp_reference_data as d
    out = {}
    pts = [(x, y, t) for x, y, t, _n in d.BAYS]
    for t in sorted({p[2] for p in pts}):
        mine = [p for p in pts if p[2] == t]
        ds = []
        for i, a in enumerate(mine):
            best = min((math.hypot(a[0] - b[0], a[1] - b[1]) for j, b in enumerate(mine) if j != i), default=0.0)
            ds.append(best)
        ds.sort()
        out[t] = {"bays": len(mine), "pitch_m": ds[len(ds) // 2] if ds else 0.0}
    return out
