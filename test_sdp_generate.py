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
