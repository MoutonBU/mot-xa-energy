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
