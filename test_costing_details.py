import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
import mot_xa_energy as M, costing
w = M.MainWindow()
cp = w.costing_page
cp.cname = "Test costing"
# stands on its own: its details, edited and saved with the costing
cp.det_edits["project"].setText("Standalone house"); cp._detail_changed("project")
cp.det_edits["town"].setText("George"); cp._detail_changed("town")
assert cp.details["zone"] and cp.details["province"], cp.details
cp.det_edits["owner"].setText("Mr Client"); cp._detail_changed("owner")
cp.save_now()
assert "Saved" in cp.saved_lbl.text()
st = cp._state()
assert st["details"]["project"] == "Standalone house"
cp2 = costing.CostingPage(w); cp2._apply_state(st)
assert cp2.details["owner"] == "Mr Client" and cp2.det_edits["owner"].text() == "Mr Client"
ro, lo = costing.detail_overrides(cp.details)
assert ro["project"] == "Standalone house" and ro["owner"] == "Mr Client" and "George" in lo and "energy zone" in lo
# the cover and reports use them, not the open project's
w.rd = {**getattr(w, "rd", {}), "project": "Some other project", "owner": "Other owner"}
import html
d = __import__("PySide6.QtGui", fromlist=["QTextDocument"]).QTextDocument()
h = costing.report_cover(d, w, "COSTING REPORT", "Cost estimate", None, cp.details)
assert "Standalone house" in h and "Mr Client" in h and "Some other project" not in h and "Other owner" not in h and "George" in h
assert cp.det_rd()["project"] == "Standalone house"
# empty details: the project's are used
h2 = costing.report_cover(d, w, "COSTING REPORT", "Cost estimate", None, {})
assert "Some other project" in h2
# copy from the open project
cp.details = {}
cp.details_from_project()
assert cp.details.get("project") == "Some other project"
cp.write_cost_report("/tmp/cd.pdf"); cp.materials.write_pdf("/tmp/cdm.pdf")
print("ok costing details")

# builder's quantities: the same quantities with no prices anywhere
import materials as _mat
_mp = cp.materials
_q = dict(brick110=100.0, brick220=0, cavity=0, plaster_area=80.0, plain_brick_area=0, footing_vol=5.0, slab_vol=8.0, slab_area=60.0, tile_area=0, dpm_area=60.0,
          roof_slab_vol=0, roof_area=70.0, beam_vol=1.0, win_area=6.0, door_n=3, rail_m=0, conc_wall_vol=0, steel_kg=0, timber_vol=0, ins_area=20.0, fill_vol=0)
_mp.blocks = [{"name": "House", "path": "", "repeat": 1, "q": _q}]
_rows = _mp.qty_rows()
assert _rows and all(len(r) == 4 for r in _rows), _rows[:2]
_h = _mp.qty_html()
assert "Builder" in _h and "Your rate" in _h and "R " not in _h and "Material" not in _h and "Labour" not in _h
_mp.write_qty_pdf("/tmp/qty.pdf")
assert os.path.getsize("/tmp/qty.pdf") > 1000
print("ok builder quantities")
