"""Building cost estimate: quantities taken off the IFC (walls, slabs, roofs, beams, windows, doors) and the rooms list turned into a
bill of everything that goes into a building, with material AND labour for each item: site work, walls, concrete, floors, roof, ceilings,
finishes, windows and doors, electrical (points and light fittings), plumbing, kitchen and built-in cupboards, sanitary ware and its installation.
On top of the trades come breakage and wastage, preliminaries, the builder's overheads and profit, contingency, optional fees and VAT.

Allowances (bricks per m2, points per m2 ...) and rates are starting figures in tables on the tab and can be changed.
This is a budget estimate, not a bill of quantities."""
import re

# ---------------- allowances (editable in the tab) ----------------
# key: (description, unit, default)
ALLOW = {
    "brick_per_m2_110": ("Bricks per m2, 110 mm wall", "no.", 52.0),
    "mortar_m3_per_m2_110": ("Mortar per m2, 110 mm wall", "m3", 0.025),
    "waste_brick": ("Brick waste (in the quantity)", "%", 5.0),
    "plaster_thick": ("Plaster thickness", "mm", 15.0),
    "waste_plaster": ("Plaster waste (in the quantity)", "%", 15.0),
    "cement_bags_per_m3": ("Cement per m3 of mortar (1:4)", "bags", 7.0),
    "sand_m3_per_m3": ("Sand per m3 of mortar", "m3", 1.0),
    "ties_per_m2": ("Wall ties per m2 of cavity wall", "no.", 4.0),
    "steel_slab": ("Reinforcing steel in slabs", "kg/m3", 70.0),
    "steel_beam": ("Reinforcing steel in beams, columns, stairs", "kg/m3", 150.0),
    "steel_footing": ("Reinforcing steel in footings", "kg/m3", 40.0),
    "waste_concrete": ("Concrete waste (in the quantity)", "%", 5.0),
    "tile_waste": ("Floor tile waste (in the quantity)", "%", 8.0),
    "adhesive_kg_per_m2": ("Tile adhesive and grout", "kg/m2", 5.5),
    "paint_l_per_m2": ("Paint, two coats", "L/m2", 0.2),
    "skirting_m_per_m2": ("Skirting per m2 of tiled floor", "m", 0.7),
    "hardcore_m": ("Hardcore under the ground slab", "m", 0.15),
    "wet_factor": ("Waterproofed area per m2 of bathroom floor", "m2", 2.5),
    "lights_per_100m2": ("Light points per 100 m2 of floor", "no.", 13.0),
    "sockets_per_100m2": ("Socket outlets per 100 m2 of floor", "no.", 26.0),
    "switches_per_100m2": ("Switches per 100 m2 of floor", "no.", 11.0),
    "kitchen_base_m": ("Kitchen base units per kitchen", "m", 4.0),
    "kitchen_wall_m": ("Kitchen wall units per kitchen", "m", 3.0),
    "bic_m_per_bedroom": ("Built-in cupboard per bedroom", "m", 2.4),
    "plaster_brick_walls": ("Plaster the plain 'Brick' walls too (1 = yes)", "0/1", 0.0),
    # how the price is built up
    "breakage_pct": ("Breakage, theft and wastage allowance, on all materials", "%", 3.0),
    "prelim_pct": ("Preliminaries: site costs, supervision, insurance, scaffolding", "% of direct cost", 8.0),
    "profit_pct": ("Builder's overheads and profit", "%", 10.0),
    "contingency_pct": ("Contingency", "%", 5.0),
    "fees_pct": ("Professional fees and council costs (0 = not included)", "%", 0.0),
    "rates_incl_vat": ("The material prices include VAT (1 = yes, VAT is taken out first)", "0/1", 1.0),
    "vat_pct": ("VAT added to the final price (0 = none)", "%", 15.0),
}

# ---------------- rates ----------------
# key: (description, unit, material rand per unit, labour rand per unit, where the figures come from)
LIST_NOTE = "material: retail list, undated; labour: my estimate"
EST_NOTE = "my estimate: check a quote and your trades"
RATES = {
    "site_clear": ("Site clearing and levelling", "m2", 0.0, 18.0, EST_NOTE),
    "excavate": ("Excavating and backfilling footings", "m3", 0.0, 200.0, EST_NOTE),
    "hardcore": ("Hardcore fill under slabs, compacted", "m3", 380.0, 120.0, EST_NOTE),
    "brick": ("Brick, laid (labour is per brick)", "each", 2.30, 2.50, LIST_NOTE),
    "ties": ("Wall tie", "each", 1.50, 0.0, EST_NOTE),
    "brickforce": ("Brickforce in brickwork", "m2 of wall", 7.0, 0.0, EST_NOTE),
    "insulation": ("Cavity wall insulation", "m2", 85.0, 25.0, EST_NOTE),
    "cement": ("Cement, 50 kg bag", "bag", 112.0, 0.0, "material: retail list, undated"),
    "sand_build": ("Building sand", "m3", 379.0, 0.0, "material: retail list, undated"),
    "sand_plaster": ("Plaster sand", "m3", 569.0, 0.0, "material: retail list, undated"),
    "plaster": ("Plastering labour", "m2", 0.0, 85.0, EST_NOTE),
    "concrete": ("Ready-mix concrete 25 MPa, delivered, placed and finished", "m3", 2400.0, 450.0, EST_NOTE),
    "steel": ("Reinforcing steel, cut, bent and fixed", "kg", 19.0, 7.0, EST_NOTE),
    "mesh": ("Reinforcing mesh (ref 193)", "m2", 38.0, 6.0, EST_NOTE),
    "dpm": ("Damp-proof membrane", "m2", 12.0, 5.0, EST_NOTE),
    "waterproof": ("Wet-area waterproofing", "m2", 95.0, 60.0, EST_NOTE),
    "tile": ("Floor tile, laid", "m2", 190.0, 170.0, EST_NOTE),
    "adhesive": ("Tile adhesive and grout", "kg", 9.0, 0.0, EST_NOTE),
    "skirting": ("Skirting, fixed", "m", 45.0, 35.0, EST_NOTE),
    "roof_cover": ("Roof covering (tiles or sheeting), laid", "m2", 190.0, 90.0, EST_NOTE),
    "roof_timber": ("Roof timber structure with fixings", "m2", 330.0, 190.0, EST_NOTE),
    "gutter": ("Gutter and fascia", "m", 120.0, 45.0, EST_NOTE),
    "downpipe": ("Downpipe", "m", 90.0, 35.0, EST_NOTE),
    "ceiling": ("Ceiling board with brandering and cornice, fixed", "m2", 85.0, 65.0, EST_NOTE),
    "paint": ("Paint (PVA / acrylic)", "L", 95.0, 0.0, EST_NOTE),
    "painting": ("Painting labour, with preparation", "m2", 0.0, 42.0, EST_NOTE),
    "window": ("Aluminium window, glazed, fitted", "m2", 3350.0, 250.0, EST_NOTE),
    "door": ("Door with frame and ironmongery, hung", "each", 1500.0, 380.0, EST_NOTE),
    "light_point": ("Light point: wiring, conduit and box", "each", 90.0, 290.0, EST_NOTE),
    "light_fitting": ("Light fitting, fixed", "each", 280.0, 60.0, EST_NOTE),
    "socket": ("Socket outlet, wired", "each", 70.0, 260.0, EST_NOTE),
    "switch": ("Switch, wired", "each", 55.0, 220.0, EST_NOTE),
    "db": ("Distribution board with breakers", "each", 3200.0, 1100.0, EST_NOTE),
    "coc": ("Electrical test and certificate of compliance", "each", 0.0, 1600.0, EST_NOTE),
    "plumb_point": ("Plumbing per fixture: supply and waste pipes", "each", 1100.0, 1300.0, EST_NOTE),
    "geyser": ("Geyser 150 L installed", "each", 6800.0, 1800.0, EST_NOTE),
    "services": ("Water and sewer connection per dwelling", "each", 2500.0, 3000.0, EST_NOTE),
    "cup_base": ("Kitchen base units", "m", 2300.0, 900.0, EST_NOTE),
    "cup_wall": ("Kitchen wall units", "m", 1500.0, 600.0, EST_NOTE),
    "countertop": ("Kitchen countertop", "m", 1200.0, 450.0, EST_NOTE),
    "bic": ("Built-in bedroom cupboard", "m", 2500.0, 800.0, EST_NOTE),
    "accessories": ("Bathroom accessories (roll holder, towel rail, mirror)", "per bathroom", 600.0, 120.0, EST_NOTE),
}
# installation labour for each sanitary fixture (the fixture itself is priced on the fixtures tab)
INSTALL = {"Toilet (WC)": 450.0, "Basin": 350.0, "Basin mixer": 150.0, "Shower": 700.0, "Shower head": 120.0, "Shower mixer": 220.0,
           "Bath": 800.0, "Bath mixer": 200.0, "Kitchen sink": 450.0, "Kitchen mixer": 150.0, "Laundry tub": 350.0, "Urinal": 400.0,
           "Vanity cabinet": 350.0, "Mirror": 100.0, "Towel rail": 120.0, "Other": 150.0}
for _c, _v in INSTALL.items():
    RATES["inst:" + _c] = ("Install " + _c.lower(), "each", 0.0, _v, EST_NOTE)
POINT_CATS = {"Toilet (WC)", "Basin", "Shower", "Bath", "Kitchen sink", "Laundry tub", "Urinal"}   # each needs supply and waste pipes

NON_CEILING = re.compile(r"stoep|patio|carport|balcon|veranda|terrace|garage|roof|passage space", re.I)
WET = re.compile(r"\b(bath|ensuite|en-suite|shower|wc|toilet)", re.I)


# ---------------- reading the model ----------------
def _wall_kind(name):
    n = name.lower()
    t = re.search(r"(\d{2,3})\s*mm", n)
    th = float(t.group(1)) / 1000.0 if t else 0.0
    if "footing" in n or "foundation" in n:
        return "footing", th
    if "cavity" in n or th >= 0.26:
        return "cavity", th
    if th >= 0.20:
        return "brick220", th
    return "brick110", th


def _axis_length(e, sc):
    """Length of a wall drawn only as a centre line (Archicad exports its footings that way)."""
    import math
    try:
        for rep in e.Representation.Representations:
            for it in rep.Items:
                if it.is_a("IfcPolyline"):
                    pts = [p.Coordinates for p in it.Points]
                    return sum(math.dist(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1)) * sc
                if it.is_a("IfcTrimmedCurve") and it.BasisCurve.is_a("IfcLine"):
                    return abs(float(it.Trim2[0].wrappedValue) - float(it.Trim1[0].wrappedValue)) * sc
    except Exception:
        pass
    return 0.0


def _footing_volume(e, name, sc):
    """Footing volume: centre-line length times the section in the type name ('Footing 720 x 800' = 720 wide, 800 deep, mm)."""
    m = re.search(r"(\d{3,4})\s*x\s*(\d{3,4})", name)
    if not m:
        return 0.0
    return _axis_length(e, sc) * float(m.group(1)) / 1000.0 * float(m.group(2)) / 1000.0


def read_ifc_quantities(path):
    """Quantities of one IFC file (one block): wall face areas by type, slab, roof, beam and footing volumes, windows and doors.
    Takes a few seconds for a house. Raises if the file cannot be read."""
    import numpy as np
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU
    f = ifcopenshell.open(path)
    st = ifcopenshell.geom.settings()
    st.set(st.USE_WORLD_COORDS, True)
    sc = UU.calculate_unit_scale(f)
    q = dict(brick110=0.0, brick220=0.0, cavity=0.0, plaster_area=0.0, plain_brick_area=0.0, footing_vol=0.0, footing_len=0.0,
             slab_vol=0.0, slab_area=0.0, tile_area=0.0, dpm_area=0.0, roof_slab_vol=0.0, roof_area=0.0, beam_vol=0.0, win_area=0.0,
             win_n=0, door_n=0, gate_n=0, names={}, levels={}, slab_levels={})

    def shape_stats(e):
        s = ifcopenshell.geom.create_shape(st, e)
        v = np.array(s.geometry.verts, dtype=float).reshape(-1, 3)
        fc = np.array(s.geometry.faces, dtype=int).reshape(-1, 3)
        tri = v[fc]
        cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ar = np.linalg.norm(cr, axis=1)
        ok = ar > 1e-12
        nz = np.zeros(len(ar))
        nz[ok] = cr[ok, 2] / ar[ok]
        vol = abs(float(np.einsum("ij,ij->i", tri[:, 0], cr).sum()) / 6.0)
        return vol, ar / 2.0, nz, v

    def type_name(e):
        t = None
        try:
            t = UE.get_type(e)
        except Exception:
            pass
        return ((t.Name if t is not None else "") or e.Name or "")

    def level(e):
        try:
            c = UE.get_container(e)
            return (c.Name if c is not None else "") or ""
        except Exception:
            return ""

    def layer_thickness(e):
        try:
            m = UE.get_material(e)
            if m is not None and m.is_a("IfcMaterialLayerSetUsage"):
                m = m.ForLayerSet
            if m is not None and m.is_a("IfcMaterialLayerSet"):
                return sum(float(l.LayerThickness) for l in m.MaterialLayers) * sc
        except Exception:
            pass
        return 0.0

    for e in f.by_type("IfcWall"):
        try:
            name = type_name(e)
            kind, th = _wall_kind(name)
            if kind == "footing":
                q["footing_vol"] += _footing_volume(e, name, sc)
                continue
            vol, ar, nz, v = shape_stats(e)
            th = th or layer_thickness(e) or 0.11
            face = vol / th
            q[kind] += face
            q["names"][name] = q["names"].get(name, 0.0) + face
            lv = level(e)
            q["levels"][lv] = q["levels"].get(lv, 0.0) + face
            if "plaster" in name.lower():
                q["plaster_area"] += 2.0 * face
            elif kind in ("brick110", "brick220"):
                q["plain_brick_area"] += 2.0 * face
        except Exception:
            continue
    for e in f.by_type("IfcSlab"):
        try:
            name = type_name(e)
            vol, ar, nz, v = shape_stats(e)
            top = float(ar[nz > 0.9].sum())
            lv = level(e)
            is_roof = "roof" in name.lower() or "roof" in lv.lower() or str(getattr(e, "PredefinedType", "")) == "ROOF"
            if is_roof:
                q["roof_slab_vol"] += vol
                q["roof_area"] += top
                continue
            q["slab_vol"] += vol
            q["slab_area"] += top
            q["slab_levels"][lv] = q["slab_levels"].get(lv, 0.0) + top
            if "tile" in name.lower():
                q["tile_area"] += top
            if "waterproof" in name.lower() or "membrane" in name.lower() or "dpm" in name.lower():
                q["dpm_area"] += top
        except Exception:
            continue
    for e in f.by_type("IfcRoof"):
        try:
            vol, ar, nz, v = shape_stats(e)
            q["roof_area"] += float(ar[nz > 0.25].sum())
        except Exception:
            continue
    for cls in ("IfcBeam", "IfcColumn", "IfcMember", "IfcStair", "IfcStairFlight"):
        try:
            for e in f.by_type(cls):
                if getattr(e, "Name", "") and "CHS" in (type_name(e) or ""):
                    continue            # a steel tube column is not concrete
                try:
                    q["beam_vol"] += shape_stats(e)[0]
                except Exception:
                    pass
        except Exception:
            pass
    for e in f.by_type("IfcWindow"):
        try:
            w, h = float(e.OverallWidth or 0) * sc, float(e.OverallHeight or 0) * sc
            q["win_area"] += w * h
            q["win_n"] += 1
        except Exception:
            pass
    for e in f.by_type("IfcDoor"):
        if re.match(r"^\s*G\d*\b", str(e.Name or "")):
            q["gate_n"] += 1
        else:
            q["door_n"] += 1
    return q


# ---------------- bill of everything ----------------
def facts_from_rooms(rooms):
    """Counts of what the rooms list holds: dwellings, kitchens, bedrooms, bathrooms, wet floor area, floor area. rooms: [(name, area, floor, unit)]"""
    f = dict(units=0, kitchens=0, bedrooms=0, baths=0, wet_area=0.0, area=0.0)
    units = set()
    for n, a, fl, u in rooms:
        base = re.sub(r"^\W*[A-Za-z]{0,2}\s*\d{1,2}\s*[-_.:]\s*(?=[A-Za-z])", "", n or "").lower()
        if u:
            units.add(u)
        if not NON_CEILING.search(n or ""):
            f["area"] += a
        if re.search(r"kitchen", base):
            f["kitchens"] += 1
        if re.search(r"bed", base):
            f["bedrooms"] += 1
        if re.search(r"bath|ensuite|en-suite|shower", base):
            f["baths"] += 1
        if WET.search(base):
            f["wet_area"] += a
    f["units"] = len(units) or max(1, f["kitchens"])
    return f


def facts_from_area(slab_area):
    u = max(1, round(slab_area / 80.0))
    return dict(units=u, kitchens=u, bedrooms=2 * u, baths=u, wet_area=0.08 * slab_area, area=0.85 * slab_area)


def bom(q, rates, allow, facts, fixtures=None):
    """Rows for one block: [(group, item, unit, qty, material rate, labour rate)].
    rates {key: (mat, lab)} and allow {key: value} override the defaults; facts = counts from the rooms; fixtures = {category: number}."""
    R = lambda k: tuple(rates.get(k, (RATES[k][2], RATES[k][3])))
    A = lambda k: float(allow.get(k, ALLOW[k][2]))
    rows = []

    def add(group, item, unit, qty, key):
        if qty > 1e-9:
            m, l = R(key)
            rows.append((group, item, unit, qty, m, l))
    wb = 1 + A("waste_brick") / 100.0
    per, mort = A("brick_per_m2_110"), A("mortar_m3_per_m2_110")
    wall = q["brick110"] + 2 * q["brick220"] + 2 * q["cavity"]          # in half-brick skins
    face = q["brick110"] + q["brick220"] + q["cavity"]
    slab_by = q.get("slab_levels") or {}
    foot = max(slab_by.values()) if slab_by else q["slab_area"] / 2.0
    area = max(facts["area"], 1.0)
    # site and foundations
    add("Site and foundations", "Site clearing and levelling", "m2", foot * 1.3, "site_clear")
    add("Site and foundations", "Excavation and backfill of footings", "m3", q["footing_vol"] * 1.4, "excavate")
    add("Site and foundations", "Hardcore under the ground slab", "m3", foot * A("hardcore_m"), "hardcore")
    wc = 1 + A("waste_concrete") / 100.0
    add("Concrete", "Footings (concrete)", "m3", q["footing_vol"] * wc, "concrete")
    add("Concrete", "Floor and roof slabs (concrete)", "m3", (q["slab_vol"] + q["roof_slab_vol"]) * wc, "concrete")
    add("Concrete", "Beams, columns and stairs (concrete)", "m3", q["beam_vol"] * wc, "concrete")
    steel = q["footing_vol"] * A("steel_footing") + (q["slab_vol"] + q["roof_slab_vol"]) * A("steel_slab") + q["beam_vol"] * A("steel_beam")
    add("Concrete", "Reinforcing steel", "kg", steel, "steel")
    add("Concrete", "Damp-proof membrane under slabs", "m2", q["dpm_area"] * 1.1, "dpm")
    # walls
    add("Walls", "Bricks laid", "no.", wall * per * wb, "brick")
    add("Walls", "Brickforce", "m2", face, "brickforce")
    add("Walls", "Wall ties (cavity walls)", "no.", q["cavity"] * A("ties_per_m2"), "ties")
    add("Walls", "Cavity insulation", "m2", q["cavity"], "insulation")
    pl_area = q["plaster_area"] + (q["plain_brick_area"] if A("plaster_brick_walls") else 0.0)
    mortar_walls = wall * mort * wb
    mortar_plaster = pl_area * A("plaster_thick") / 1000.0 * (1 + A("waste_plaster") / 100.0)
    add("Walls", "Cement for brickwork and plaster", "bag", (mortar_walls + mortar_plaster) * A("cement_bags_per_m3"), "cement")
    add("Walls", "Building sand (brickwork)", "m3", mortar_walls * A("sand_m3_per_m3"), "sand_build")
    add("Walls", "Plaster sand", "m3", mortar_plaster * A("sand_m3_per_m3"), "sand_plaster")
    add("Walls", "Plastering", "m2", pl_area, "plaster")
    # floors
    tile = q["tile_area"] * (1 + A("tile_waste") / 100.0)
    add("Floors", "Floor tiles, laid", "m2", tile, "tile")
    add("Floors", "Tile adhesive and grout", "kg", q["tile_area"] * A("adhesive_kg_per_m2"), "adhesive")
    add("Floors", "Skirting", "m", q["tile_area"] * A("skirting_m_per_m2"), "skirting")
    add("Floors", "Waterproofing of wet areas", "m2", facts["wet_area"] * A("wet_factor"), "waterproof")
    # roof and ceiling
    add("Roof and ceiling", "Roof covering", "m2", q["roof_area"], "roof_cover")
    add("Roof and ceiling", "Roof timber structure", "m2", q["roof_area"], "roof_timber")
    perim = 4.0 * (max(q["roof_area"], 1.0) ** 0.5) * 1.15 if q["roof_area"] else 0.0
    add("Roof and ceiling", "Gutter and fascia", "m", perim, "gutter")
    add("Roof and ceiling", "Downpipes", "m", (q["roof_area"] / 25.0) * 3.0, "downpipe")
    add("Roof and ceiling", "Ceilings", "m2", area, "ceiling")
    # finishes
    add("Finishes", "Paint (walls and ceilings)", "L", (pl_area + area) * A("paint_l_per_m2"), "paint")
    add("Finishes", "Painting labour", "m2", pl_area + area, "painting")
    # openings
    add("Windows and doors", "Windows", "m2", q["win_area"], "window")
    add("Windows and doors", "Doors", "each", float(q["door_n"]), "door")
    # electrical
    lights = area * A("lights_per_100m2") / 100.0
    add("Electrical", "Light points", "no.", lights, "light_point")
    add("Electrical", "Light fittings", "no.", lights, "light_fitting")
    add("Electrical", "Socket outlets", "no.", area * A("sockets_per_100m2") / 100.0, "socket")
    add("Electrical", "Switches", "no.", area * A("switches_per_100m2") / 100.0, "switch")
    add("Electrical", "Distribution boards", "no.", float(facts["units"]), "db")
    add("Electrical", "Testing and certificate of compliance", "no.", float(facts["units"]), "coc")
    # plumbing
    pts = sum(n for c, n in (fixtures or {}).items() if c in POINT_CATS)
    add("Plumbing", "Supply and waste pipes to each fixture", "no.", float(pts), "plumb_point")
    add("Plumbing", "Geysers", "no.", float(facts["units"]), "geyser")
    add("Plumbing", "Water and sewer connections", "no.", float(facts["units"]), "services")
    # cupboards
    k = facts["kitchens"]
    add("Cupboards and fittings", "Kitchen base units", "m", k * A("kitchen_base_m"), "cup_base")
    add("Cupboards and fittings", "Kitchen wall units", "m", k * A("kitchen_wall_m"), "cup_wall")
    add("Cupboards and fittings", "Kitchen countertops", "m", k * A("kitchen_base_m"), "countertop")
    add("Cupboards and fittings", "Built-in bedroom cupboards", "m", facts["bedrooms"] * A("bic_m_per_bedroom"), "bic")
    add("Cupboards and fittings", "Bathroom accessories", "no.", float(facts["baths"]), "accessories")
    # sanitary ware installation (labour; the fixtures are added from the fixtures tab)
    for cat, n in (fixtures or {}).items():
        key = "inst:" + cat if ("inst:" + cat) in RATES else "inst:Other"
        add("Sanitary ware", "Install " + cat.lower(), "no.", float(n), key)
    return rows


def buildup(mat, lab, allow):
    """The price build-up. mat, lab: material and labour totals as the rates give them. Returns ([(label, amount)], total, direct cost)."""
    A = lambda k: float(allow.get(k, ALLOW[k][2]))
    ex = mat / 1.15 if A("rates_incl_vat") else mat
    brk = ex * A("breakage_pct") / 100.0
    direct = ex + brk + lab
    pre = direct * A("prelim_pct") / 100.0
    oh = (direct + pre) * A("profit_pct") / 100.0
    con = (direct + pre + oh) * A("contingency_pct") / 100.0
    fees = (direct + pre + oh + con) * A("fees_pct") / 100.0
    net = direct + pre + oh + con + fees
    vat = net * A("vat_pct") / 100.0
    steps = [("Materials and sanitary ware", ex), ("Breakage and wastage", brk), ("Labour, all trades", lab), ("Preliminaries and site costs", pre),
             ("Builder's overheads and profit", oh), ("Contingency", con), ("Professional fees and council costs", fees), ("VAT", vat)]
    return steps, net + vat, direct


def markup_factor(mat, lab, allow):
    """How much a rand of direct cost becomes once breakage, preliminaries, profit, contingency, fees and VAT are added."""
    steps, total, direct = buildup(mat, lab, allow)
    return total / direct if direct else 1.0

# ---------------- the tab ----------------
import datetime
import html as _html
import json
import os
import sys
import threading

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)


def rand(x):
    return "R {:,.0f}".format(float(x)).replace(",", " ")


def num(x, d=1):
    return "{:,.{d}f}".format(float(x), d=d).replace(",", " ")


class MaterialsPage(QWidget):
    is_costing = True
    report_title = "Building Cost Estimate"
    read_done = Signal(int, object, str)
    price_found = Signal(object, str)

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.blocks = []        # {name, path, repeat, q}
        self.rates = {}         # key -> {"mat", "lab", "source"} overrides
        self.allow = {}         # key -> value overrides
        self.custom = []        # {group, item, unit, qty, mat, lab}
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        from ui_extras import icon_group
        gb = icon_group("Blocks and buildings")
        bv = QVBoxLayout(gb)
        row = QHBoxLayout()
        for text, fn in (("Use this project's IFC", self.add_current), ("Add block (IFC)...", self.add_block), ("Remove", self.remove_block),
                         ("Read quantities from the IFC", self.read_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        bv.addLayout(row)
        self.btab = QTableWidget(0, 5)
        self.btab.setHorizontalHeaderLabels(["Block", "IFC file", "Identical blocks", "Status", "All-in cost of one block"])
        self.btab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.btab.verticalHeader().setVisible(False)
        self.btab.setMaximumHeight(130)
        h = self.btab.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 150), (2, 120), (3, 190), (4, 170)):
            self.btab.setColumnWidth(i, w)
        self.btab.itemChanged.connect(self._b_edit)
        bv.addWidget(self.btab)
        v.addWidget(gb)
        self.tabs = QTabWidget()
        self.bomt = QTableWidget(0, 7)
        self.bomt.setHorizontalHeaderLabels(["Group", "Item", "Unit", "Quantity", "Material rate", "Labour rate", "Cost (material + labour)"])
        self.buildt = QTableWidget(0, 3)
        self.buildt.setHorizontalHeaderLabels(["Price build-up", "Amount", "Share of the price"])
        self.ratet = QTableWidget(0, 5)
        self.ratet.setHorizontalHeaderLabels(["Item", "Unit", "Material (R)", "Labour (R)", "Where the figures come from"])
        self.allowt = QTableWidget(0, 3)
        self.allowt.setHorizontalHeaderLabels(["Allowance", "Unit", "Value"])
        self.qt_ = QTableWidget(0, 3)
        self.qt_.setHorizontalHeaderLabels(["Quantity read from the IFC", "Unit", "Value"])
        self.extrat = QTableWidget(0, 6)
        self.extrat.setHorizontalHeaderLabels(["Group", "Item", "Unit", "Quantity", "Material rate", "Labour rate"])
        for t in (self.bomt, self.buildt, self.ratet, self.allowt, self.qt_, self.extrat):
            t.verticalHeader().setVisible(False)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for t in (self.bomt, self.qt_, self.buildt):
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ratet.itemChanged.connect(self._r_edit)
        self.allowt.itemChanged.connect(self._a_edit)
        self.extrat.itemChanged.connect(self._x_edit)
        ew = QWidget()
        ev = QVBoxLayout(ew)
        ev.setContentsMargins(0, 0, 0, 0)
        eb = QHBoxLayout()
        for text, fn in (("Add item", self.add_extra), ("Remove item", self.remove_extra)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            eb.addWidget(b)
        eb.addWidget(QLabel("Anything the model does not hold: solar, boundary walls, paving, a pool, fees ..."))
        eb.addStretch(1)
        ev.addLayout(eb)
        ev.addWidget(self.extrat)
        self.tabs.addTab(self.bomt, "Bill of materials and labour")
        self.tabs.addTab(self.buildt, "Price build-up")
        self.tabs.addTab(self.ratet, "Rates")
        self.tabs.addTab(self.allowt, "Allowances")
        self.tabs.addTab(ew, "Extra items")
        self.tabs.addTab(self.qt_, "Quantities")
        v.addWidget(self.tabs, 1)
        bar = QHBoxLayout()
        for text, fn in (("Update prices with AI...", self.ai_prices), ("Preview PDF", self.preview_pdf), ("Export PDF", self.export_pdf),
                         ("Export CSV", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.total = QLabel("")
        self.total.setStyleSheet("font-weight:700; font-size:14px;")
        bar.addWidget(self.total)
        v.addLayout(bar)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray; font-size: 11px;")
        v.addWidget(self.note)
        self._default_note()
        self.read_done.connect(self._read_finished)
        self.price_found.connect(self._prices_back)
        self.refresh()

    def _default_note(self):
        self.note.setText("Rates are starting figures (the Where-from column says which): material and labour for every item, with breakage, preliminaries, the "
                          "builder's profit, contingency and VAT added on the Price build-up tab. A budget estimate, not a bill of quantities.")

    # ----- state -----
    def state(self):
        return {"blocks": self.blocks, "rates": self.rates, "allow": self.allow, "custom": self.custom}

    def set_state(self, d):
        d = d or {}
        self.blocks = [dict(b) for b in d.get("blocks", []) if isinstance(b, dict)]
        self.rates = dict(d.get("rates", {}) or {})
        self.allow = dict(d.get("allow", {}) or {})
        self.custom = [dict(c) for c in d.get("custom", []) if isinstance(c, dict)]
        self.refresh()

    def rate_vals(self):
        out = {}
        for k, v in self.rates.items():
            if k not in RATES:
                continue
            out[k] = (float(v.get("mat", v.get("rate", RATES[k][2]))), float(v.get("lab", RATES[k][3])))
        return out

    # ----- what the project holds -----
    def _project_ifc(self):
        w = self.host.win
        return getattr(w, "ifc_path", "") or (getattr(w, "ifc_data", None) or {}).get("path", "")

    def rooms_full(self):
        try:
            return [(r.name, float(r.area_m2), r.floor, r.unit) for r in self.host.win.read_rooms()]
        except Exception:
            return []

    def _proj_slab(self):
        p = self._project_ifc()
        for b in self.blocks:
            if b.get("path") == p and b.get("q"):
                return float(b["q"].get("slab_area", 0))
        rf = facts_from_rooms(self.rooms_full())["area"]
        return rf / 0.85 if rf else 0.0

    def scale(self, b):
        """1 for the project's own block; the other blocks take the project's fixtures in proportion to their floor area."""
        if b.get("path") == self._project_ifc():
            return 1.0
        ps = self._proj_slab()
        sa = float((b.get("q") or {}).get("slab_area", 0))
        return sa / ps if ps and sa else 1.0

    def fx_scale_total(self):
        if not self.blocks:
            return 1.0
        return sum(max(1, int(b.get("repeat", 1))) * self.scale(b) for b in self.blocks) or 1.0

    def fx_counts(self):
        c = {}
        for l in self.host.lines:
            c[l.get("category", "Other")] = c.get(l.get("category", "Other"), 0) + l.get("qty", 0)
        return c

    def fx_cost(self):
        return sum((self.host.line_product(l) or {}).get("price", 0) * l.get("qty", 0) for l in self.host.lines)

    def facts(self, b):
        rooms = self.rooms_full()
        sa = float((b.get("q") or {}).get("slab_area", 0))
        if b.get("path") == self._project_ifc() and rooms:
            return facts_from_rooms(rooms)
        s = self.scale(b)
        if rooms and s:
            f = facts_from_rooms(rooms)
            return dict(units=max(1, round(f["units"] * s)), kitchens=round(f["kitchens"] * s), bedrooms=round(f["bedrooms"] * s),
                        baths=round(f["baths"] * s), wet_area=f["wet_area"] * s, area=f["area"] * s)
        return facts_from_area(sa)

    # ----- blocks -----
    def add_current(self):
        p = self._project_ifc()
        if not p:
            QMessageBox.information(self, "Costing", "Import an IFC in Light && ventilation first, or use Add block.")
            return
        if any(b["path"] == p for b in self.blocks):
            return
        self.blocks.append({"name": os.path.splitext(os.path.basename(p))[0], "path": p, "repeat": 1, "q": None})
        self.refresh()
        self.read_all()

    def add_block(self):
        path, _ = QFileDialog.getOpenFileName(self, "IFC of a block", "", "IFC (*.ifc)")
        if path:
            self.blocks.append({"name": os.path.splitext(os.path.basename(path))[0], "path": path, "repeat": 1, "q": None})
            self.refresh()
            self.read_all()

    def remove_block(self):
        r = self.btab.currentRow()
        if 0 <= r < len(self.blocks):
            self.blocks.pop(r)
            self.refresh()

    def _b_edit(self, it):
        if self._busy or not (0 <= it.row() < len(self.blocks)):
            return
        if it.column() == 0:
            self.blocks[it.row()]["name"] = it.text().strip()
        elif it.column() == 2:
            try:
                self.blocks[it.row()]["repeat"] = max(1, int(float(it.text())))
            except ValueError:
                pass
            QTimer.singleShot(0, self.refresh)

    def read_all(self):
        if not self.blocks:
            self.add_current()
            return
        for i, b in enumerate(self.blocks):
            if not os.path.exists(b["path"]):
                b["status"] = "file not found"
                continue
            b["status"] = "reading..."

            def work(i=i, p=b["path"]):
                try:
                    self.read_done.emit(i, read_ifc_quantities(p), "")
                except Exception as e:
                    self.read_done.emit(i, None, str(e))
            threading.Thread(target=work, daemon=True).start()
        self.refresh()

    def _read_finished(self, i, q, err):
        if 0 <= i < len(self.blocks):
            self.blocks[i]["q"] = q
            self.blocks[i]["status"] = ("read " + datetime.date.today().isoformat()) if q else ("could not read: " + err[:60])
        self.refresh()

    # ----- sums -----
    def block_rows(self, b):
        """Rows of one copy of a block: (group, item, unit, qty, material rate, labour rate)."""
        if not b.get("q"):
            return []
        s = self.scale(b)
        fx = {c: n * s for c, n in self.fx_counts().items()}
        rows = bom(b["q"], self.rate_vals(), self.allow, self.facts(b), fx)
        if self.fx_cost():
            rows.append(("Sanitary ware", "Sanitary ware supplied (see Fixtures tab)", "sum", 1.0, self.fx_cost() * s, 0.0))
        return rows

    def all_rows(self):
        """Items added up over every block (each block counted as often as it is repeated), then the extra items:
        (group, item, unit, qty, material rate, labour rate, material cost, labour cost)."""
        agg = {}
        for b in self.blocks:
            n = max(1, int(b.get("repeat", 1)))
            for g, item, unit, qty, mr, lr in self.block_rows(b):
                a = agg.setdefault((g, item), [g, item, unit, 0.0, mr, lr, 0.0, 0.0])
                a[3] += qty * n
                a[6] += qty * n * mr
                a[7] += qty * n * lr
        rows = list(agg.values())
        for c in self.custom:
            try:
                q_, m_, l_ = float(c.get("qty", 0)), float(c.get("mat", 0)), float(c.get("lab", 0))
            except ValueError:
                continue
            if q_:
                rows.append([c.get("group") or "Extra items", c.get("item", ""), c.get("unit", ""), q_, m_, l_, q_ * m_, q_ * l_])
        return rows

    def sums(self, rows=None):
        rows = self.all_rows() if rows is None else rows
        return sum(r[6] for r in rows), sum(r[7] for r in rows)

    def grand(self):
        mat, lab = self.sums()
        return buildup(mat, lab, self.allow)

    def block_cost(self, b):
        rows = [(g, i, u, q * 1, mr, lr) for g, i, u, q, mr, lr in self.block_rows(b)]
        mat = sum(r[3] * r[4] for r in rows)
        lab = sum(r[3] * r[5] for r in rows)
        return buildup(mat, lab, self.allow)[1]

    def group_costs(self):
        """[(group, all-in cost)] with breakage, preliminaries, profit, contingency, fees and VAT spread over the groups."""
        rows = self.all_rows()
        mat, lab = self.sums(rows)
        mf = markup_factor(mat, lab, self.allow)
        A = lambda k: float(self.allow.get(k, ALLOW[k][2]))
        vd = 1.15 if A("rates_incl_vat") else 1.0
        g = {}
        for r in rows:
            g[r[0]] = g.get(r[0], 0.0) + (r[6] / vd * (1 + A("breakage_pct") / 100.0) + r[7]) * mf
        return list(g.items())

    # ----- refresh -----
    def refresh(self):
        self._busy = True
        try:
            t = self.btab
            t.setRowCount(len(self.blocks))
            for r, b in enumerate(self.blocks):
                cells = [b["name"], b["path"], str(b.get("repeat", 1)), b.get("status") or ("read" if b.get("q") else "quantities not read yet"),
                         rand(self.block_cost(b)) if b.get("q") else ""]
                for c, txt in enumerate(cells):
                    it = QTableWidgetItem(txt)
                    if c not in (0, 2):
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    t.setItem(r, c, it)
            rows = self.all_rows()
            self.bomt.setRowCount(len(rows))
            for r, (g, item, unit, qty, mr, lr, mc, lc) in enumerate(rows):
                for c, txt in enumerate((g, item, unit, num(qty, 1 if qty < 1000 else 0), num(mr, 2), num(lr, 2), rand(mc + lc))):
                    it = QTableWidgetItem(txt)
                    if c >= 3:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.bomt.setItem(r, c, it)
            steps, total, direct = self.grand()
            bt = self.buildt
            bt.setRowCount(len(steps) + 2)
            mat, lab = self.sums(rows)
            for r, (lbl, amt) in enumerate(steps + [("Total price, all-in", total)]):
                bt.setItem(r, 0, QTableWidgetItem(lbl))
                bt.setItem(r, 1, QTableWidgetItem(rand(amt)))
                bt.setItem(r, 2, QTableWidgetItem("%.1f %%" % (100.0 * amt / total) if total else ""))
                for c in (1, 2):
                    bt.item(r, c).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if lbl.startswith("Total"):
                    for c in (0, 1, 2):
                        f_ = bt.item(r, c).font()
                        f_.setBold(True)
                        bt.item(r, c).setFont(f_)
            rt = self.ratet
            rt.setRowCount(len(RATES))
            ov = self.rate_vals()
            for r, (k, (desc, unit, mr, lr, src)) in enumerate(RATES.items()):
                m_, l_ = ov.get(k, (mr, lr))
                o = self.rates.get(k)
                vals = (desc, unit, "%.2f" % m_, "%.2f" % l_, o.get("source", "set by you") if o else src)
                for c, txt in enumerate(vals):
                    it = QTableWidgetItem(txt)
                    if c not in (2, 3):
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    rt.setItem(r, c, it)
            at = self.allowt
            at.setRowCount(len(ALLOW))
            for r, (k, (desc, unit, d)) in enumerate(ALLOW.items()):
                vals = (desc, unit, "%g" % float(self.allow.get(k, d)))
                for c, txt in enumerate(vals):
                    it = QTableWidgetItem(txt)
                    if c != 2:
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    at.setItem(r, c, it)
            xt = self.extrat
            xt.setRowCount(len(self.custom))
            for r, c_ in enumerate(self.custom):
                for ci, k in enumerate(("group", "item", "unit", "qty", "mat", "lab")):
                    xt.setItem(r, ci, QTableWidgetItem(str(c_.get(k, ""))))
            qs = [("Half-brick walls (110), face area", "m2", "brick110"), ("One-brick walls (220), face area", "m2", "brick220"),
                  ("Cavity walls (280), face area", "m2", "cavity"), ("Plastered wall area, both faces", "m2", "plaster_area"),
                  ("Plain brick wall area, both faces", "m2", "plain_brick_area"), ("Footings", "m3", "footing_vol"),
                  ("Floor slabs", "m3", "slab_vol"), ("Floor slab area", "m2", "slab_area"), ("Tiled floor area", "m2", "tile_area"),
                  ("Roof slabs", "m3", "roof_slab_vol"), ("Roof area", "m2", "roof_area"), ("Beams, columns, stairs", "m3", "beam_vol"),
                  ("Windows", "m2", "win_area"), ("Windows", "no.", "win_n"), ("Doors", "no.", "door_n"), ("Gates (not costed)", "no.", "gate_n")]
            qt = self.qt_
            qt.setRowCount(len(qs))
            for r, (d, u, k) in enumerate(qs):
                val = sum((b["q"] or {}).get(k, 0) * max(1, int(b.get("repeat", 1))) for b in self.blocks if b.get("q"))
                for c, txt in enumerate((d, u, num(val, 1 if u != "no." else 0))):
                    qt.setItem(r, c, QTableWidgetItem(txt))
            self.total.setText(("Direct cost %s   >   all-in price %s (incl. profit, breakage, VAT)" % (rand(direct), rand(total))) if rows else "")
        finally:
            self._busy = False

    def _r_edit(self, it):
        if self._busy or it.column() not in (2, 3) or not (0 <= it.row() < len(RATES)):
            return
        k = list(RATES)[it.row()]
        try:
            val = float(it.text().replace(" ", "").replace(",", "."))
        except ValueError:
            return
        cur = self.rate_vals().get(k, (RATES[k][2], RATES[k][3]))
        m_, l_ = (val, cur[1]) if it.column() == 2 else (cur[0], val)
        self.rates[k] = {"mat": m_, "lab": l_, "source": "set by you " + datetime.date.today().isoformat()}
        QTimer.singleShot(0, self.refresh)

    def _a_edit(self, it):
        if self._busy or it.column() != 2 or not (0 <= it.row() < len(ALLOW)):
            return
        k = list(ALLOW)[it.row()]
        try:
            self.allow[k] = float(it.text().replace(" ", "").replace(",", "."))
        except ValueError:
            return
        QTimer.singleShot(0, self.refresh)

    def add_extra(self):
        self.custom.append({"group": "Extra items", "item": "New item", "unit": "sum", "qty": 1, "mat": 0, "lab": 0})
        self.refresh()
        self.tabs.setCurrentIndex(4)

    def remove_extra(self):
        r = self.extrat.currentRow()
        if 0 <= r < len(self.custom):
            self.custom.pop(r)
            self.refresh()

    def _x_edit(self, it):
        if self._busy or not (0 <= it.row() < len(self.custom)):
            return
        k = ("group", "item", "unit", "qty", "mat", "lab")[it.column()]
        txt = it.text().strip()
        if k in ("qty", "mat", "lab"):
            try:
                txt = float(txt.replace(" ", "").replace(",", "."))
            except ValueError:
                return
        self.custom[it.row()][k] = txt
        QTimer.singleShot(0, self.refresh)

    # ----- AI prices -----
    def ai_prices(self):
        M = sys.modules[type(self.host.win).__module__]
        if not M.online_ready():
            QMessageBox.information(self, "Costing", "Updating prices uses Claude with web search. Switch Online mode on and enter your API key first "
                                    "(the button at the top right, or Tools > Online mode).")
            return
        from costing import ai_search
        keys_all = [k for k, v in RATES.items() if v[2] > 0 and not k.startswith("inst:")]      # material prices; labour is not searched
        dlg = QDialog(self)
        dlg.setWindowTitle("Update prices with AI")
        dlg.resize(640, 600)
        lay = QVBoxLayout(dlg)
        uses = int(M.SETTINGS.get("search_uses") or 5)
        lay.addWidget(QLabel("Tick the materials to look up. One request is made for all of them, with at most %d web searches (about %d cents plus a "
                             "few thousand tokens). Items priced by AI in the last 14 days are left unticked. Labour rates are not searched: they are "
                             "yours to set with your trades." % (uses, uses)))
        pt = QTableWidget(len(keys_all), 3)
        pt.setHorizontalHeaderLabels(["Look up", "Material", "Price now"])
        pt.verticalHeader().setVisible(False)
        pt.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        today = datetime.date.today()
        ov = self.rate_vals()
        for r, k in enumerate(keys_all):
            d, u = RATES[k][0], RATES[k][1]
            o = self.rates.get(k)
            fresh = False
            if o and str(o.get("source", "")).startswith("AI search"):
                try:
                    fresh = (today - datetime.date.fromisoformat(o["source"][10:20])).days < 14
                except ValueError:
                    pass
            c = QTableWidgetItem("")
            c.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            c.setCheckState(Qt.CheckState.Unchecked if fresh else Qt.CheckState.Checked)
            pt.setItem(r, 0, c)
            pt.setItem(r, 1, QTableWidgetItem("%s (per %s)" % (d, u)))
            pt.setItem(r, 2, QTableWidgetItem("%.2f  %s" % (ov.get(k, (RATES[k][2], 0))[0], "(AI, recent)" if fresh else "")))
        lay.addWidget(pt)
        go = QPushButton("Search")
        go.clicked.connect(dlg.accept)
        lay.addWidget(go)
        if not dlg.exec():
            return
        keys = [k for r, k in enumerate(keys_all) if pt.item(r, 0).checkState() == Qt.CheckState.Checked]
        if not keys:
            return
        items = "\n".join('- key "%s": %s, per %s' % (k, RATES[k][0], RATES[k][1]) for k in keys)
        prompt = ("Find current South African retail prices in rand incl. VAT for these building materials and fittings (the material or product only, "
                  "not the labour). Search efficiently: one search can cover several items. Items:\n" + items +
                  '\nReply with ONLY this JSON, no other text: {"prices": [{"key": "brick", "price_zar": 2.4, "source": "shop and URL"}]}. '
                  "Include a key only if you found a real price in the unit given. Never guess.")
        self.note.setText("Searching for prices... this takes a minute or two.")

        def work():
            try:
                text, _urls = ai_search(M, prompt, (), max_tokens=2200)
                t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                a, b = t.find("{"), t.rfind("}")
                if a < 0 or b <= a:
                    raise RuntimeError("The AI did not return a price list. It said: " + (text.strip()[:300] or "(nothing)"))
                self.price_found.emit(json.loads(t[a:b + 1]).get("prices", []), "")
            except Exception as e:
                self.price_found.emit([], str(e)[:400])
        threading.Thread(target=work, daemon=True).start()

    def _prices_back(self, prices, err):
        self._default_note()
        if err:
            QMessageBox.warning(self, "Costing", "The price search failed: " + err)
            return
        good = []
        for p in prices:
            try:
                if isinstance(p, dict) and p.get("key") in RATES and float(p.get("price_zar") or 0) > 0:
                    good.append(p)
            except (TypeError, ValueError):
                pass
        if not good:
            QMessageBox.information(self, "Costing", "The search found no usable prices.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Prices found")
        dlg.resize(820, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Tick the prices to use. Check the source before you rely on them."))
        t = QTableWidget(len(good), 5)
        t.setHorizontalHeaderLabels(["Use", "Material", "Now", "Found", "Source"])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        ov = self.rate_vals()
        for r, p in enumerate(good):
            k = p["key"]
            cur = ov.get(k, (RATES[k][2], RATES[k][3]))[0]
            c = QTableWidgetItem("")
            c.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            c.setCheckState(Qt.CheckState.Checked)
            t.setItem(r, 0, c)
            for ci, txt in ((1, RATES[k][0] + " (per " + RATES[k][1] + ")"), (2, "%.2f" % cur), (3, "%.2f" % float(p["price_zar"])), (4, str(p.get("source", ""))[:200])):
                t.setItem(r, ci, QTableWidgetItem(txt))
        lay.addWidget(t)
        ok = QPushButton("Use the ticked prices")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        if dlg.exec():
            for r, p in enumerate(good):
                if t.item(r, 0).checkState() == Qt.CheckState.Checked:
                    k = p["key"]
                    cur = ov.get(k, (RATES[k][2], RATES[k][3]))
                    self.rates[k] = {"mat": float(p["price_zar"]), "lab": cur[1],
                                     "source": ("AI search %s: %s" % (datetime.date.today().isoformat(), str(p.get("source", ""))))[:160]}
            self.refresh()

    # ----- reports -----
    def report_html(self):
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        rd = getattr(self.host.win, "rd", {}) or {}
        th = lambda t, w: '<th bgcolor="%s" width="%d%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left": '<td style="padding:3px;text-align:%s;">%s</td>' % (a, t)
        out = ['<h2 style="color:%s;">Building cost estimate</h2>' % RED,
               '<p style="font-size:9pt;color:#444;">%s &nbsp;|&nbsp; %s</p>' % (e(rd.get("project") or "Project"), datetime.date.today().strftime("%d %B %Y"))]
        steps, total, direct = self.grand()
        area = 0.0
        sp = getattr(self.host, "summary_page", None)
        if sp is not None:
            try:
                area = sp.area()
            except Exception:
                area = 0.0
        out.append('<table width="100%%" border="0" cellspacing="0" cellpadding="8"><tr><td bgcolor="#F4F4F4" style="font-size:11pt;"><b>All-in price: %s</b>%s</td></tr></table>' %
                   (rand(total), (" &nbsp; on %s m2 = <b>%s per m2</b>" % (num(area, 0), rand(total / area))) if area else ""))
        out.append("<h3>Blocks</h3>")
        rows = "".join("<tr>%s%s%s</tr>" % (td(e(b["name"])), td(str(b.get("repeat", 1)), "center"),
                                            td(rand(self.block_cost(b)) if b.get("q") else "not read", "right")) for b in self.blocks)
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s</tr>%s</table>' % (th("Block", 60), th("Identical blocks", 15), th("All-in cost of one block", 25), rows))
        out.append("<h3>Price build-up</h3>")
        rows = "".join("<tr>%s%s%s</tr>" % (td(e(l)), td(rand(a), "right"), td("%.1f %%" % (100.0 * a / total) if total else "", "right")) for l, a in steps)
        rows += "<tr>%s%s%s</tr>" % (td("<b>Total, all-in</b>"), td("<b>%s</b>" % rand(total), "right"), td("100 %", "right"))
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:9pt;"><tr>%s%s%s</tr>%s</table>' % (th("", 60), th("Amount", 25), th("Share", 15), rows))
        out.append("<h3>Cost by group, with the markups spread over them</h3>")
        gc = self.group_costs()
        rows = "".join("<tr>%s%s%s</tr>" % (td(e(g)), td(rand(c), "right"), td(rand(c / area) if area else "", "right")) for g, c in gc)
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s%s%s</tr>%s</table>' % (th("Group", 50), th("All-in cost", 25), th("Per m2", 25), rows))
        out.append("<h3>Bill of materials and labour, all blocks</h3>")
        rows, last = "", None
        for g, item, unit, qty, mr, lr, mc, lc in self.all_rows():
            rows += "<tr>%s%s%s%s%s%s%s</tr>" % (td(e(g) if g != last else ""), td(e(item)), td(e(unit), "center"), td(num(qty, 1 if qty < 1000 else 0), "right"),
                                                   td(rand(mc), "right"), td(rand(lc), "right"), td(rand(mc + lc), "right"))
            last = g
        out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8pt;"><tr>%s%s%s%s%s%s%s</tr>%s</table>' %
                   (th("", 13), th("Item", 33), th("Unit", 6), th("Quantity", 11), th("Material", 13), th("Labour", 12), th("Total", 12), rows))
        out.append('<p style="font-size:7.5pt;color:#666;">Quantities are read from the IFC model and the rooms list; allowances and rates are starting figures that can be changed in the program. '
                   'Material prices are shop prices, the builder\'s profit, breakage, preliminaries, contingency and VAT are added as set under Allowances. A budget estimate, not a bill of quantities; '
                   'confirm with quotations before contract.</p>')
        return "".join(out)

    def write_pdf(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        w.setTitle("Building cost estimate")
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.report_html() + "</body></html>")
        d.print_(w)

    def preview_pdf(self):
        try:
            self.host.win.preview_pdf_report(self.write_pdf, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, "Costing", "The preview could not be shown (%s). Use Export PDF." % e)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export building cost estimate", "Building cost estimate.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.write_pdf(path)
            QMessageBox.information(self, "Costing", "PDF saved:\n" + path)

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export building cost estimate", "Building cost estimate.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Group", "Item", "Unit", "Quantity", "Material rate", "Labour rate", "Material cost", "Labour cost"])
            for g, item, unit, qty, mr, lr, mc, lc in self.all_rows():
                w.writerow([g, item, unit, "%.2f" % qty, "%.2f" % mr, "%.2f" % lr, "%.2f" % mc, "%.2f" % lc])
            steps, total, _d = self.grand()
            w.writerow([])
            for n, v_ in steps + [("Total, all-in", total)]:
                w.writerow([n, "", "", "", "", "", "", "%.2f" % v_])
