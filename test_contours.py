"""Contours: read a DXF, the ground along the sewer follows them, and a pipe that would come out of the ground is flagged."""
import os, tempfile
import ezdxf
from PySide6.QtWidgets import QApplication
import site_dxf as sc
import site_services as ss
import site_profile as sp

# a plan with contours falling steeply away from the road: levels 100 at y=0 down to 96 at y=40 (metres, one contour a metre)
d_ = tempfile.mkdtemp()
path = os.path.join(d_, "c.dxf")
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 6
msp = doc.modelspace()
for k in range(0, 5):
    z = 100.0 - k
    msp.add_lwpolyline([(-20, 10.0 * k), (60, 10.0 * k)], dxfattribs={"elevation": z, "layer": "CONT"})
doc.saveas(path)
data = sc.read_contours(path)
assert len(data["lines"]) == 5 and abs(max(z for z, _ in data["lines"]) - 100.0) < 1e-9, data
t = sc.Terrain(data["lines"])
assert abs(t.z_at(5, 5) - 99.5) < 1e-6 and abs(t.z_at(5, 25) - 97.5) < 1e-6 and abs(t.z_at(5, 10) - 99.0) < 1e-6, (t.z_at(5, 5), t.z_at(5, 25))
# flat 2D contours with the level written on them
p2 = os.path.join(d_, "f.dxf")
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 6
msp = doc.modelspace()
for k in range(3):
    msp.add_lwpolyline([(0, 10.0 * k), (50, 10.0 * k)])
    msp.add_text("%d.0" % (100 - k), dxfattribs={"insert": (20, 10.0 * k + 0.4), "height": 0.5})
doc.saveas(p2)
assert sorted(round(z) for z, _ in sc.read_contours(p2)["lines"]) == [98, 99, 100]
# millimetre drawing, levels in mm
p3 = os.path.join(d_, "m.dxf")
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4
msp = doc.modelspace()
msp.add_lwpolyline([(0, 0), (50000, 0)], dxfattribs={"elevation": 98500.0})
doc.saveas(p3)
r3 = sc.read_contours(p3)
assert abs(r3["lines"][0][0] - 98.5) < 1e-9 and abs(r3["lines"][0][1][1][0] - 50.0) < 1e-9
try:
    sc.read_contours(os.path.join(d_, "none.dxf"))
    assert False
except Exception:
    pass

app = QApplication.instance() or QApplication([])
pg = ss.SiteServicesPage(type("W", (), {"receive_site_link": lambda s, l: "ok"})())
pg.set_state(ss.blank_state())
pg.lv_spin["ngl_head"].setValue(50.0); pg.lv_spin["ngl_main"].setValue(50.0)           # typed levels that the contours must override
pg.solve_now(False)
d0 = sp.build(pg.st, pg.res)
assert not d0["terrain"]
pg.import_contours(path)
assert pg.st["contours"]["lines"], "contours were kept"
d1 = sp.build(pg.st, pg.res)
assert d1["terrain"] and not d1["assumed"] and d1["ngl0"] != d0["ngl0"] and 90 < d1["ngl0"] < 101, (d1["ngl0"], d1["ngl1"])
assert "Contours from c.dxf" in pg.lv_continfo.text()
# the contours are used by the section: the ground at both ends differs and follows the contours
assert abs(d1["ngl"](0.0) - d1["ngl0"]) < 1e-9 and abs(d1["ngl"](d1["length"]) - d1["ngl1"]) < 1e-9
# switched off: the typed levels again
pg.lv_usecont.setChecked(False); pg.solve_now(False)
assert not sp.build(pg.st, pg.res)["terrain"] and "Not used" in pg.lv_continfo.text()
pg.lv_usecont.setChecked(True); pg.solve_now(False)
# the state keeps the contours
s_ = pg.state(); pg.set_state(s_)
assert pg.st["contours"]["lines"] and sp.build(pg.st, pg.res)["terrain"]
# ground falling faster than the pipe: the pipe would come out of the ground and the check says so with where
cs = [pg._world_of(p) for p in pg.st["stand"]["corners"]]
cx_, cy_ = sum(p[0] for p in cs) / len(cs), sum(p[1] for p in cs) / len(cs)
pyr = {"lines": [[200.0 - k, [[cx_ - 2 * k - 1, cy_ - 2 * k - 1], [cx_ + 2 * k + 1, cy_ - 2 * k - 1], [cx_ + 2 * k + 1, cy_ + 2 * k + 1], [cx_ - 2 * k - 1, cy_ + 2 * k + 1], [cx_ - 2 * k - 1, cy_ - 2 * k - 1]]] for k in range(0, 40)], "spots": [], "unit": 1.0, "file": "pyramid.dxf"}
pg.st["contours"] = pyr
pg.solve_now(False)
d3 = sp.build(pg.st, pg.res)
bad = [tx for tx, ok in d3["checks"] if not ok and "Soil cover" in tx]
assert d3["terrain"] and d3["min_cover"] < 0.3 and bad and "from the house" in bad[0], (d3["min_cover"], d3["checks"])
# the contours are drawn on the plan (with levels) and the long section can be lines only
import site_sheet as _sh
from PySide6.QtGui import QPicture, QPainter as _QP
pic = QPicture(); qp = _QP(pic)
D_ = _sh.Drawer(qp, pg.view.sheet(800, 600), 7, False)
_sh._contours(D_, pg.st, pg.st["stand"]["corners"])
assert any(str(t[0]).startswith("contour_") for t in D_.hits), "no contour labels"
qp.end()
pg.lv_lines.setChecked(True); pg.solve_now(False)
assert sp.build(pg.st, pg.res)["lines_only"]
pg.lv_lines.setChecked(False)
assert d3["bad"] and all(b_ > a_ for a_, b_ in d3["bad"]), d3["bad"]          # the stretches with too little cover
pg.st["contours"] = pyr; pg.solve_now(False)
pg.resize(900, 700); pg.show()
import time as _t
_t0 = _t.time()
while _t.time() - _t0 < 0.4:
    app.processEvents()
pg.view.lite = False; pg.view._dirty = True
im_a = pg.view.grab().toImage()                        # the ground colours and steep glow draw without error
pg.set_look("ground", False); pg.view._dirty = True
im_b = pg.view.grab().toImage()
assert im_a != im_b, "ground shading did not show"
pg.set_look("ground", True)
# which way the ground falls: contours that fall 0.5 m every 10 m towards +x
cw_ = [pg._world_of(p_) for p_ in pg.st["stand"]["corners"]]
cx2, cy2 = sum(p_[0] for p_ in cw_) / len(cw_), sum(p_[1] for p_ in cw_) / len(cw_)
pg.st["contours"] = {"lines": [[100.0 - 0.5 * k_, [[cx2 + 10 * k_ - 60, cy2 - 60], [cx2 + 10 * k_ - 60, cy2 + 60]]] for k_ in range(0, 13)], "spots": [], "unit": 1.0, "file": "slope.dxf"}
pg.solve_now(False)
fl_ = _sh.ground_fall(pg.st, pg.st["stand"]["corners"])
assert fl_ and abs(fl_[2] - 0.05) < 0.005, fl_                                                  # 1 in 20
g_ = [t_ for t_, _ok in sp.build(pg.st, pg.res)["checks"] if t_.startswith("The ground")]
assert g_ and "1:" in g_[0] and ("falls" in g_[0] or "rises" in g_[0]), g_
pg.view.lite = False; pg.view._dirty = True; pg.view.grab()                                    # the arrows and the running water draw
pg.view._ph = 0.5; pg.view.grab()
pg.remove_contours()
assert not sp.build(pg.st, pg.res)["terrain"] and "No contours" in pg.lv_continfo.text()
print("ok")
