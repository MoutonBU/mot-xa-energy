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
