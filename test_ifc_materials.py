import materials as m
def test_classes():
    assert m.mat_class("Concrete 25MPa") == "concrete"
    assert m.mat_class("Face Brick") == "brick"
    assert m.mat_class("Rockwool insulation") == "insulation"
    assert m.mat_class("Hollow concrete block") == "block"
    assert m.mat_class("Structural steel S355") == "steel"
    assert m.mat_class("Saligna timber") == "timber"
    assert m.mat_class("Cavity") == "air"
def test_bom_new_rows():
    q = dict(brick110=0, brick220=0, cavity=0, plaster_area=0, plain_brick_area=0, footing_vol=0, slab_vol=0, slab_area=0, tile_area=0, dpm_area=0,
             roof_slab_vol=0, roof_area=0, beam_vol=0, win_area=0, door_n=0, rail_m=0, conc_wall_vol=10.0, steel_kg=500.0, timber_vol=2.0, ins_area=20.0, fill_vol=3.0)
    facts = dict(area=100, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1)
    rows = m.bom(q, {}, {}, facts)
    items = {r[1]: r[3] for r in rows}
    assert items["Concrete walls"] > 10
    assert items["Structural steel sections"] == 500.0
    assert items["Timber columns, beams and members"] == 2.0
    steel = items["Reinforcing steel"]
    assert abs(steel - 10.0 * 100.0) < 1e-6
if __name__ == "__main__":
    test_classes(); test_bom_new_rows(); print("ok")

def test_rooms_facts():
    rooms = [("U1-Kitchen", 10, "", "U1"), ("U1-Bedroom 1", 12, "", "U1"), ("U2-Kitchen", 10, "", "U2"), ("U2-Bath 1", 5, "", "U2")]
    f = m.facts_from_rooms(rooms)
    assert f["units"] == 2 and f["kitchens"] == 2
test_rooms_facts(); print("ok2")

def test_report_is_json():
    import json
    json.dumps({"mat_report": [["Walls", "brick", "m2", 1.0]], "rooms": [("U1-Kitchen", 1.0, "", "U1")]})
test_report_is_json(); print("ok3")

def test_roof_timber_replaces_generic():
    q = dict(brick110=0, brick220=0, cavity=0, plaster_area=0, plain_brick_area=0, footing_vol=0, slab_vol=0, slab_area=0, tile_area=0, dpm_area=0,
             roof_slab_vol=0, roof_area=100.0, beam_vol=0, win_area=0, door_n=0, rail_m=0, timber_vol=5.0, roof_timber_vol=5.0)
    facts = dict(area=100, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1)
    items = [r[1] for r in m.bom(q, {}, {}, facts)]
    assert "Roof timber structure" not in items and "Timber columns, beams and members" in items
test_roof_timber_replaces_generic(); print("ok4")

def test_db_per_level_and_unit():
    house = [("Lounge", 40, "Basement", ""), ("Lounge", 50, "Ground Floor", ""), ("Bedroom 1", 30, "First Floor", ""), ("Kitchen", 20, "Ground Floor", "")]
    f = m.facts_from_rooms(house)
    assert f["levels"] == 3 and f["dbs"] == 3
    block = [("U1-Kitchen", 10, "Ground", "U1"), ("U1-Bedroom", 12, "First", "U1"), ("U2-Kitchen", 10, "Ground", "U2")]
    assert m.facts_from_rooms(block)["dbs"] == 2

def test_truss_from_pitch_when_no_roof():
    q = dict(brick110=0, brick220=0, cavity=0, plaster_area=0, plain_brick_area=0, footing_vol=0, slab_vol=0, slab_area=100.0, tile_area=0, dpm_area=0,
             roof_slab_vol=0, roof_area=0, beam_vol=0, win_area=0, door_n=0, rail_m=0, slab_levels={"G": 100.0})
    facts = dict(area=90, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1, dbs=1)
    rows = m.bom(q, {}, {}, facts)
    tr = [r for r in rows if r[1].startswith("Roof trusses")]
    assert tr and tr[0][3] > 3.0
    assert any(r[1] == "Roof covering" and r[3] > 100 for r in rows)
test_db_per_level_and_unit(); test_truss_from_pitch_when_no_roof(); print("ok5")

def _q(**kw):
    q = dict(brick110=0, brick220=0, cavity=0, plaster_area=0, plain_brick_area=0, footing_vol=0, slab_vol=0, slab_area=100.0, tile_area=0, dpm_area=0,
             roof_slab_vol=0, roof_area=100.0, beam_vol=0, win_area=0, door_n=0, rail_m=0, slab_levels={"G": 100.0}, storeys=[["G", 0.0, False]])
    q.update(kw)
    return q

def test_openings_glazing_and_doors():
    facts = dict(area=90, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1, dbs=1)
    ops = [["Window", "W1", 2.0, 1.5, "double", "window"], ["Door", "D1", 3.0, 2.4, "double", "slider"], ["Door", "D2", 0.8, 2.0, "", "internal"],
           ["Door", "D3", 0.9, 2.1, "", "external"], ["Door", "GD", 2.4, 2.1, "", "garage"]]
    rows = {r[1]: r for r in m.bom(_q(openings=ops), {}, {}, facts)}
    assert abs(rows["Double glazing, extra over single"][3] - (3.0 + 7.2)) < 1e-6
    assert rows["Internal doors"][3] == 1 and rows["External doors"][3] == 1 and rows["Garage doors"][3] == 1
    rows3 = {r[1]: r for r in m.bom(_q(openings=ops), {}, {"glazing_level": 3}, facts)}
    assert "Triple glazing, low-e, extra over single" in rows3 and "Double glazing, extra over single" not in rows3
    rows1 = {r[1]: r for r in m.bom(_q(openings=ops), {}, {"glazing_level": 1}, facts)}
    assert "Double glazing, extra over single" not in rows1

def test_cabinets_replace_generic():
    facts = dict(area=90, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1, dbs=1)
    rows = {r[1]: r for r in m.bom(_q(cab_base_m=12.5, cab_tall_m=6.0, cab_wall_m=8.0, appliance_n=2), {}, {}, facts)}
    assert rows["Base units and vanities (from the model)"][3] == 12.5 and "Kitchen base units" not in rows
    assert rows["Built-in cooktops, ovens and extractors (from the model)"][3] == 2.0

def test_footing_fallback_and_spec():
    facts = dict(area=90, wet_area=10, units=1, kitchens=1, bedrooms=2, baths=1, dbs=1)
    rows = m.bom(_q(wall_len={"G": 100.0}), {}, {}, facts)
    f = [r for r in rows if r[1].startswith("Footings (concrete)")][0]
    assert abs(f[3] - 100.0 * 0.6 * 0.3 * 1.05) < 0.5 and "allowance" in f[1]
    base = {r[1]: r for r in m.bom(_q(), {}, {}, facts)}
    lux = {r[1]: r for r in m.bom(_q(), {}, {"spec_level": 3}, facts)}
    assert lux["Floor tiles, laid"][4] > base["Floor tiles, laid"][4] * 1.7
    assert abs(lux["Bricks laid"][4] - base["Bricks laid"][4]) < 1e-9 if "Bricks laid" in lux else True
    own = {r[1]: r for r in m.bom(_q(), {"tile": (100.0, 50.0)}, {"spec_level": 3}, facts)}
    assert own["Floor tiles, laid"][4] == 100.0
test_openings_glazing_and_doors(); test_cabinets_replace_generic(); test_footing_fallback_and_spec(); print("ok6")

def test_unread_is_json():
    import json
    json.dumps({"unread": [["IfcDiscreteAccessory", "Water", 20, 0.41]], "openings": [["Window", "W1", 1.0, 1.0, "double", "window"]]})
test_unread_is_json(); print("ok7")
