import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
import sdp_creator as sc
app = QApplication.instance() or QApplication([])


class W:
    rd = {"project": "Test"}
    area_page = None
    site_page = None


pg = sc.SdpPage(W())
pg.resize(1300, 800)
pg.q_w.setValue(160), pg.q_d.setValue(100)
pg.make_rect()
o = {"type": "Standard 3-storey", "prefix": "H", "phase": "Phase 1", "w": 24, "d": 12, "side": 6, "front": 17.5, "count": 4, "parking": True}
pg.generate(dict(o))
bl = pg.blocks()
assert len(bl) == 4 and all(b["units"] == 12 for b in bl), bl
assert len(pg.buildings()) == 4 and pg.bays
a = pg.sdp()
assert a["total"]["units"] == 48
assert not any(pg._bad), "bays break rules"
assert "Units" in pg.metrics_lbl.text() and "Bays" in pg.metrics_lbl.text()
# again: replaces its own blocks, keeps the others
pg.add_building({"name": "Mine", "x": 2, "y": 2, "w": 8, "d": 8})
pg.generate(dict(o, count=3))
names = [b["name"] for b in pg.buildings()]
assert names.count("Mine") == 1 and len([n for n in names if n.startswith("H")]) == 3, names
# as many as the parking allows
t0 = time.time()
pg.generate(dict(o, count=0))
n = len([b for b in pg.buildings() if b["name"].startswith("H")])
a = pg.sdp()
print("max blocks", n, "bays", a["bays"], "needed", a["bays_needed"], "%.1fs" % (time.time() - t0))
assert n >= 1 and a["bays"] >= a["bays_needed"] or n == 1
st = pg.state()
pg2 = sc.SdpPage(W()); pg2.set_state(st)
assert pg2._gen_names() == pg._gen_names()
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok generate")
# live: moving a building re-parks by itself
pg3 = sc.SdpPage(W()); pg3.q_w.setValue(60), pg3.q_d.setValue(40); pg3.make_rect()
pg3.add_building({"name": "H1", "x": 20, "y": 14, "w": 20, "d": 12}); pg3.zone_whole_stand(); pg3.fill_all()
n0 = len(pg3.bays)
pg3.add_building({"name": "H2", "x": 2, "y": 2, "w": 10, "d": 8})
import time as _t
for _ in range(30):
    app.processEvents(); _t.sleep(0.1)
assert len(pg3.bays) != n0 and not any(pg3._bad), (n0, len(pg3.bays))
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok live")
# ada / ev, schemes, export
import tempfile
pg3.ada_pct.setValue(4); pg3.ev_pct.setValue(2)
pg3.assign_special()
c = pg3.bay_counts()
assert sum(c.get("Accessible", (0, 0))) >= 1 and sum(c.get("EV", (0, 0))) >= 1, c
pg3.save_scheme(); pg3.add_building({"name": "H3", "x": 44, "y": 25, "w": 10, "d": 8}); pg3._live_fill(); pg3.save_scheme()
assert len(pg3.schemes) == 2 and "Scheme 2" in pg3.scheme_lbl.text()
nb = len(pg3.buildings()); pg3.scheme_cb.setCurrentIndex(0); pg3.load_scheme()
assert len(pg3.buildings()) == nb - 1 and len(pg3.schemes) == 2
d = tempfile.mkdtemp()
pg3.export_dxf(d + "/a.dxf"); pg3.export_csv(d + "/a.csv")
import ezdxf; assert len(list(ezdxf.readfile(d + "/a.dxf").modelspace())) > 20
assert os.path.getsize(d + "/a.csv") > 50
pg4 = sc.SdpPage(W()); pg4.set_state(pg3.state()); assert len(pg4.schemes) == 2
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok extras")
# new plan, and fill on finishing the polygon
pg5 = sc.SdpPage(W()); pg5.q_w.setValue(60), pg5.q_d.setValue(40); pg5.make_rect()
pg5.add_building({"name": "H1", "x": 20, "y": 14, "w": 20, "d": 12})
pg5.trace_done("trace_parking", "", [(2, 2), (58, 2), (58, 38), (2, 38)])
assert len(pg5.zones) == 1 and len(pg5.bays) > 20 and not any(pg5._bad)
pg5.new_plan(ask=False)
assert not pg5.buildings() and not pg5.bays and not pg5.zones and not pg5.schemes
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok newplan")
# keep-clear area and find options
pg6 = sc.SdpPage(W()); pg6.q_w.setValue(160), pg6.q_d.setValue(100); pg6.make_rect()
pg6.start_excl(); pg6.trace_done("trace_parking", "", [(0, 0), (60, 0), (60, 100), (0, 100)])
assert len(pg6.excl) == 1 and not pg6.zones
pg6.generate({"type": "Maxi", "prefix": "H", "phase": "Phase 1", "w": 30, "d": 14, "side": 6, "front": 17.5, "count": 0, "parking": True})
for b in pg6.buildings():
    assert b["x"] >= 59.9, b
assert not any(pg6._bad)
pg6.find_options({"units": 10, "cov": 0})
assert len(pg6.schemes) >= 2, len(pg6.schemes)
st = pg6.state(); pg7 = sc.SdpPage(W()); pg7.set_state(st); assert len(pg7.excl) == 1
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok options", [s_["name"] for s_ in pg6.schemes])
# drag corners by hand
pg8 = sc.SdpPage(W()); pg8.q_w.setValue(60), pg8.q_d.setValue(40); pg8.make_rect()
pg8.zone_whole_stand(); pg8.fill_all()
v0 = [tuple(q) for q in pg8.verts()]
h = pg8.corner_at((v0[2][0] - 0.2, v0[2][1] + 0.1), 1.0)
assert h and h[0] in ("stand", "zone"), h
pg8.move_corner(("stand", 0, 2), v0[2][0] - 10, v0[2][1]); pg8.corner_released()
assert abs(pg8.verts()[2][0] - (v0[2][0] - 10)) < 0.01
pg8.move_corner(("zone", 0, 1), 40.0, 5.0); pg8.corner_released()
assert pg8.zones[0]["poly"][1] == [40.0, 5.0] and not any(pg8._bad)
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok corners")
# unit mix, variations, goal
pg9 = sc.SdpPage(W()); pg9.q_w.setValue(160), pg9.q_d.setValue(100); pg9.make_rect()
pg9.generate({"type": "Standard 3-storey", "prefix": "H", "phase": "Phase 1", "w": 24, "d": 12, "side": 6, "front": 17.5, "count": 3, "parking": True})
pg9.use_mix()
assert abs(pg9.f["bays_per_unit"].value() - 1.45) < 1e-6, pg9.f["bays_per_unit"].value()
assert "Beds" in pg9.metrics_lbl.text()
pg9.more_like_this()
assert len(pg9.schemes) == 6 and "&#9733;" in pg9.scheme_lbl.text()
pg9.goal_cb.setCurrentIndex(2)
assert "&#9733;" in pg9.scheme_lbl.text()
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok mix")
# roads: a spline road, bays along it, blocks and bays keep off it
pg10 = sc.SdpPage(W()); pg10.q_w.setValue(100), pg10.q_d.setValue(60); pg10.make_rect()
pg10.start_road(); pg10.trace_done("trace_road", "", [(3, 30), (35, 22), (65, 40), (97, 30)])
assert len(pg10.roads) == 1 and not pg10.bays
pg10.park_roads_clicked()
nr = len(pg10.bays)
assert nr > 30 and all(str(b["zone"]).startswith("Road") for b in pg10.bays) and not any(pg10._bad), (nr, [x for x in pg10._bad if x][:2])
pg10.zone_whole_stand(); pg10.fill_all()
assert len(pg10.bays) > nr and not any(pg10._bad)
quads = pg10.road_quads_all()
import sdp_parking as _sp
for b in pg10.bays:
    assert not any(_sp.overlap(_sp.bay_poly(b, pg10.rules_now()), q, 0.05) for q in quads[::3]), b
pg10.generate({"type": "Standard 3-storey", "prefix": "H", "phase": "Phase 1", "w": 20, "d": 12, "side": 6, "front": 17.5, "count": 3, "parking": True})
for b in pg10.buildings():
    P = [(b["x"], b["y"]), (b["x"] + b["w"], b["y"]), (b["x"] + b["w"], b["y"] + b["d"]), (b["x"], b["y"] + b["d"])]
    assert not any(_sp.poly_dist(P, q) < 1e-6 for q in quads), b
assert not any(pg10._bad)
pg10.move_corner(("road", 0, 1), 35.0, 12.0); pg10.corner_released()
assert not any(pg10._bad)
print("road pt after move", pg10.roads[0]["pts"][1])
st = pg10.state(); pg11 = sc.SdpPage(W()); pg11.set_state(st); assert len(pg11.roads) == 1
import tempfile as _t2; _d = _t2.mkdtemp(); pg10.export_dxf(_d + "/r.dxf")
pg10.clear_roads(); assert not pg10.roads and not any(str(b["zone"]).startswith("Road") for b in pg10.bays)
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok roads")
# road width per road
pg12 = sc.SdpPage(W()); pg12.q_w.setValue(100), pg12.q_d.setValue(60); pg12.make_rect()
pg12.start_road(); pg12.trace_done("trace_road", "", [(3, 15), (50, 12), (97, 15)])
pg12.road_w.setValue(6.0)
pg12.start_road(); pg12.trace_done("trace_road", "", [(3, 45), (50, 48), (97, 45)])
assert [r["w"] for r in pg12.roads] == [6.0, 6.0], [r["w"] for r in pg12.roads]
pg12.road_cb.setCurrentIndex(1); pg12.road_w.setValue(9.0)
assert [r["w"] for r in pg12.roads] == [6.0, 9.0] and not any(pg12._bad)
pg12.road_cb.setCurrentIndex(0); assert abs(pg12.road_w.value() - 6.0) < 1e-9
assert "9.0 m wide" in pg12.road_cb.itemText(1)
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok widths")
# smart road: bays per side, road widens to the pushback, bends round a block, zone joins and is limited
pg13 = sc.SdpPage(W()); pg13.q_w.setValue(100), pg13.q_d.setValue(60); pg13.make_rect()
pg13.start_road(); pg13.trace_done("trace_road", "", [(3, 30), (50, 30), (97, 30)])
rd = pg13.roads[0]
assert not pg13.road_span(rd) and abs(pg13.road_wide(rd) - 7.0) < 1e-9 and not pg13.bays
pg13.left_sp.setValue(2); pg13.right_sp.setValue(2)
assert len(pg13.bays) == 4 and not any(pg13._bad), len(pg13.bays)
assert pg13.road_span(rd) == [(0.0, 5.0)]
q = pg13.road_quads_all()
ws = sorted({round(sc.math.hypot(a[0] - d[0], a[1] - d[1]), 2) for a, b_, c_, d in q})
assert ws == [6.0, 7.0], ws                       # 7 m where the bays are, the plain width elsewhere
pg13.left_sp.setValue(-1); pg13.right_sp.setValue(0)
assert len(pg13.bays) > 20 and all(b["a"] < 360 for b in pg13.bays)
# a block dropped on the road: the road bends round it
pg13.add_building({"name": "H1", "x": 40, "y": 26, "w": 20, "d": 12})
for _ in range(30):
    app.processEvents(); _t.sleep(0.1)
bd = pg13.buildings()[0]
P = [(bd["x"], bd["y"]), (bd["x"] + bd["w"], bd["y"]), (bd["x"] + bd["w"], bd["y"] + bd["d"]), (bd["x"], bd["y"] + bd["d"])]
assert not any(_sp.poly_dist(P, q_) < 1e-6 for q_ in pg13.road_quads_all()), pg13.roads[0]["pts"]
assert pg13.roads[0]["pts"][1] != [50, 30] and not any(pg13._bad)
# a parking area beside the road, joined to it, and limited to a number of bays
pg13.zones = []
pg13._new_zone([(3, 42), (97, 42), (97, 58), (3, 58)], "Lot")
pg13._fill([0])
n_all = len(pg13.bays)
pg13.zt.selectRow(0); pg13.max_sp.setValue(10)
lot = [b for b in pg13.bays if b.get("zone") == "Lot"]
assert len(lot) == 10 and pg13.zones[0]["max"] == 10 and not any(pg13._bad)
pg13.join_cb.setChecked(False); assert pg13.zones[0]["join"] is False
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok smart road")
# junction with rounded corners, and a parking strip along a road
pg14 = sc.SdpPage(W()); pg14.q_w.setValue(100), pg14.q_d.setValue(60); pg14.make_rect()
pg14.start_road(); pg14.trace_done("trace_road", "", [(3, 30), (50, 30), (97, 30)])
pg14.start_road(); pg14.trace_done("trace_road", "", [(50, 4), (52, 12), (53, 26)])
e = pg14.roads[1]["pts"][-1]
assert abs(e[1] - 30) < 0.6, e                                      # the end snapped onto the main road
fl = pg14.road_fillets()
assert len(fl) >= 10, len(fl)
assert pg14.road_quads_all()[-1] in fl
pg14.corner_r.setValue(0); assert pg14.road_fillets() == []; pg14.corner_r.setValue(6)
pg14._new_zone([(60, 33.5), (95, 33.5), (95, 41), (60, 41)], "Strip")
pg14._fill([0])
rb = [b for b in pg14.bays if str(b["zone"]).startswith("Road")]
assert len(rb) >= 8 and not any(pg14._bad), (len(rb), [x for x in pg14._bad if x][:2])
assert pg14.roads[0]["_zs"], "road should widen along the strip"
q = pg14.road_quads_all()
ws = sorted({round(sc.math.hypot(a_[0] - d_[0], a_[1] - d_[1]), 1) for a_, b_, c_, d_ in [x for x in q if len(x) == 4][:40]})
assert any(abs(x - 7.0) < 0.2 for x in [sc.math.hypot(a_[0] - d_[0], a_[1] - d_[1]) for a_, b_, c_, d_ in [x for x in q if len(x) == 4] if a_[0] > 62 and a_[0] < 90]), ws
os.system("rm -f ~/MCP_XA_Energy/tools/sdp.json")
print("ok junction and strip")
