"""SDP Creator: the numbers, the blocks, parking on the plan, the saved state, the sheet."""
import os, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import sdp_creator as sc
import sdp_parking as sp

# numbers
site = dict(sc.blank_site(), max_density=40, bays_per_unit=1.5, visitor_per=5)
blocks = [sc.blank_block("H%d" % i, "Phase 1" if i <= 2 else "Phase 2", units=4, foot=300, floor=700) for i in range(1, 5)]
an = sc.analyse(site, blocks, 10000.0, plan_bays=24, max_cov=40, max_far=0.8)
assert an["total"]["units"] == 16 and abs(an["cov"] - 12.0) < 1e-9 and abs(an["far"] - 0.28) < 1e-9 and abs(an["density"] - 16.0) < 1e-9
assert an["bays_needed"] == 28 and [c[3] for c in an["checks"]] == [True, True, True, False] and not an["ok"]
assert abs(sc.analyse(site, blocks, 10000.0, cov_area=900.0)["cov"] - 9.0) < 1e-9
assert sc.block_names("H", 1, 3) == ["H1", "H2", "H3"]


import sdp_knowledge as kb
assert kb.bays_needed(343) == 515 and sum(kb.parking_mix(515).values()) == 515
assert abs(kb.refuse_area(343) - 64.699) < 1e-6
m = kb.module_preset("Maxi"); assert m["units"] == 15 and abs(m["gross_m2"] - 1149.354) < 1e-6
r = kb.reference_plan(); assert len(r["bays"]) == 611 and len(r["labels"]) == 25
assert 2.0 < kb.layout_stats()["C"]["pitch_m"] < 3.0


class W:
    rd = {"project": "Test"}
    area_page = None
    site_page = None


pg = sc.SdpPage(W())
pg.resize(1300, 800)
# the stand and a building, the way Building lines does it
pg.q_w.setValue(60), pg.q_d.setValue(40)
pg.make_rect()
assert len(pg.verts()) == 4
pg.add_building({"name": "H1", "x": 20, "y": 14, "w": 20, "d": 12})
assert len(pg.buildings()) == 1
# a parking area over the whole stand, filled
pg.zone_whole_stand()
assert len(pg.zones) == 1
pg.fill_all()
n = len(pg.bays)
assert n > 50, n
assert all(not pr for pr in pg._bad), [pr for pr in pg._bad if pr][:3]
# the 0.5 m rule against the building
r = pg.rules_now()
for b in pg.bays:
    assert sp.poly_dist(sp.bay_poly(b, r), [(20, 14), (40, 14), (40, 26), (20, 26)]) >= 0.5 - 1e-6
# a bay put right against the building is red, one in the open is not
pg.add_bay_at((40.0 + 0.2 + 2.5, 20.0)); 
assert pg._bad[-1], "a bay 0.2 m from the building must break the rule"
pg.delete_bay()
assert len(pg.bays) == n
# moving the building and refreshing marks the bays that now touch it
pg.refresh_parking()
# state round trip
st = pg.state()
pg2 = sc.SdpPage(W())
pg2.load_state(st)
assert len(pg2.bays) == n and len(pg2.zones) == 1 and pg2.rules_now() == pg.rules_now() and len(pg2.buildings()) == 1
# refuse area and gatehouse
pg.add_gatehouse(); pg.add_refuse()
names = [b["name"] for b in pg.buildings()]
assert "Gatehouse - guard house" in names and "Gatehouse - ablution" in names and "Refuse area" in names
assert sc.kind_of("Refuse area 2") == "refuse" and sc.kind_of("Gatehouse") == "gate" and sc.kind_of("H3") == "block"
pg.clear_all_bays = lambda: None
pg.bays = []; pg.refresh_parking()
pg.suggest_refuse()
i = names.index("Refuse area"); rb = pg.buildings()[i]
R = sp.rect(0, 0, 0, 1, 1)
from site_lines import bpoly
assert sp.inside(bpoly(rb), pg.verts())
for j, b in enumerate(pg.buildings()):
    if j != i:
        assert sp.poly_dist(bpoly(rb), bpoly(b)) >= 0.5 - 1e-6, b["name"]
pg.fill_all()
assert all(not pr for pr in pg._bad)
# bay types: tandem bays are not counted toward the requirement
pg.bays[0]["type"] = "Tandem"; pg.refresh_parking()
assert pg.bay_counts()["Tandem"][0] == 1
cnt = sum(1 for i, b in enumerate(pg.bays) if not pg._bad[i] and b["type"] != "Tandem")
assert pg.sdp()["bays"] == cnt
# a module type fills in the units and areas
pg.add_run if False else None
pg._row(sc.blank_block("HX", typ="Maxi"))
pg.t.item(pg.t.rowCount() - 1, 2).setText("Standard 2-storey")
b0 = pg.blocks()[-1]
assert b0["units"] == 8 and abs(b0["floor"] - 579.368) < 1e-6 and b0["storeys"] == 2
pg.t.removeRow(pg.t.rowCount() - 1)
pg.t.item(0, 4).setText("8")
pg.size_refuse()
assert abs(pg.refuse_w.value() * pg.refuse_d.value() - max(kb.refuse_area(8), 6.0)) < 2
# the schedule
pg.sync_blocks()
assert [b["block"] for b in pg.blocks()][:3] == ["H1", "Gatehouse - guard house", "Gatehouse - ablution"] and abs(pg.blocks()[0]["foot"] - 240.0) < 1e-6 and pg.blocks()[1]["type"] == "Gatehouse"
assert any(b["block"].startswith("Gatehouse - office") and abs(b["floor"] - 60.2) < 1e-6 for b in pg.blocks())
assert abs(pg.blocks()[1]["floor"] - pg.blocks()[1]["foot"]) < 1e-6
pg.t.item(0, 4).setText("12")
assert "need" in pg.need_lbl.text() and "12 units" in pg.need_lbl.text(), pg.need_lbl.text()
pg.blocks()
d = sc._BlocksDialog(pg); d.first.setValue(1); d.last.setValue(26)
assert len(d.blocks()) == 26
a = pg.sdp()
assert a["bays"] == cnt and abs(a["area"] - 2400.0) < 1e-6
# rotating the plan turns the parking with it
before = (pg.bays[0]["x"], pg.bays[0]["y"], pg.bays[0]["a"])
pg.rotate_world(1.5707963267948966, 30.0, 20.0)
assert abs(pg.bays[0]["a"] - (before[2] + 90) % 360) < 1e-6
# the sheet
p = os.path.join(tempfile.mkdtemp(), "sdp.pdf")
pg.write_report(p)
assert os.path.getsize(p) > 4000
pg.show()
for i in range(5):
    pg.steps.go(i); pg.grab()
print("ok sdp")
