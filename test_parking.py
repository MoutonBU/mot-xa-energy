import os, sys, json
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PySide6.QtWidgets import QApplication
app=QApplication.instance() or QApplication([])
import mot_xa_energy as M
p=dict(M.PARK_DEFAULTS, units=12, counts={"open":8,"carport":10,"tandem":2,"access":1})
r=M.parking_calc(p)
assert r["required"]==21 and r["provided"]==8+10+4+1, r
assert r["covered_area"]>0 and r["tandem_note"]
assert M.parking_calc(dict(M.PARK_DEFAULTS))["required"]==0
assert M.parking_cost_lines(p)
json.dumps(p)
w=M.MainWindow()
w.park_load(p); st=w.cov_state(); json.dumps(st)
assert st["parking"]["units"]==12 and st["parking"]["counts"]["tandem"]==2
w.cov_load(json.loads(json.dumps(st)))
assert w.park_state()["counts"]["carport"]==10
assert "Short" in w.park_html() or "met" in w.park_html()
w.cov_stand.setValue(2000)
sc=M.cov_scenarios(w.cov_state()); assert any("parking" in x["name"] for x in sc)
w._park_to_costing.__func__  # exists
mp=w.costing_page.materials
mp.set_parking_lines(M.parking_cost_lines(p)); n=len(mp.site)
mp.set_parking_lines(M.parking_cost_lines(p)); assert len(mp.site)==n>0
import tempfile
w._write_cov_pdf(os.path.join(tempfile.mkdtemp(),"a.pdf"))
print("ok")
p2=dict(M.PARK_DEFAULTS, units=4, counts={"open":2,"shade":4,"carport":2})
r2=M.parking_calc(p2); assert r2["provided"]==8 and r2["visitor_provided"]==8
assert abs(r2["covered_area"]-(2*2.7*5.5+4*2.5*5.0))<1e-6
assert M.parking_calc(dict(p2,shade_covered=False))["covered_area"]<r2["covered_area"]
assert any("shade" in l[0] for l in M.parking_cost_lines(p2))
print("ok shade")
w2=M.MainWindow(); w2.park_load(dict(M.PARK_DEFAULTS, units=12, counts={"open":21,"access":1}))
assert "WITHIN" in w2.park_badge_html() and "1B9F4B" in w2.park_badge_style()
w2.park_load(dict(M.PARK_DEFAULTS, units=12, counts={"open":10}))
assert "OVER THE MARGIN" in w2.park_badge_html() and "E03050" in w2.park_badge_style()
w2.park_load(dict(M.PARK_DEFAULTS, units=12, counts={"open":21,"access":1})); w2.cov_stand.setValue(100); w2._cov_refresh()
assert "WITHIN" in w2.park_badge.text()
print("ok badge")
