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
