import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import materials as M
assert M.qs_number("1 234,50") == 1234.5 and M.qs_number("R 1,234.50") == 1234.5 and M.qs_number("(12.5)") == -12.5 and M.qs_number("m2") is None and M.qs_number("") is None
rows = [["CLIENT BILL"], [], ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"],
        ["A", "EXCAVATION", "", "", "", ""],
        ["A1", "Excavate footings", "m3", "12,5", "210,00", "2 625,00"],
        ["", "in firm soil", "", "", "", ""],
        ["B", "HANDRAILS", "", "", "", ""],
        ["B1", "Stainless handrail", "m", "8", "", "9 600,00"],
        ["B2", "Provisional sum", "", "", "", "5 000,00"],
        ["B3", "Unpriced item", "no", "3", "", ""],
        ["", "Total carried forward", "", "", "", "17 225,00"]]
it, nt = M.parse_qs_sheet(rows)
assert len(it) == 4, it
assert it[0]["group"] == "Excavation" and it[0]["qty"] == 12.5 and it[0]["rate"] == 210.0 and "in firm soil" in it[0]["item"]
assert it[1]["group"] == "Handrails" and it[1]["rate"] == 1200.0
assert it[2]["unit"] == "sum" and it[2]["rate"] == 5000.0 and it[3]["rate"] == 0.0 and nt
assert M.parse_qs_sheet([["a", "b"]])[0] == []
# handrails per metre in the bill of materials
q = dict(brick110=0, brick220=0, cavity=0, plaster_area=0, plain_brick_area=0, footing_vol=0, footing_len=0, slab_vol=0, slab_area=10, tile_area=0, dpm_area=0,
         roof_slab_vol=0, roof_area=0, beam_vol=0, win_area=0, win_n=0, door_n=0, gate_n=0, rail_m=6.0, names={}, levels={}, slab_levels={})
facts = {"area": 10.0, "wet_area": 0, "units": 1, "kitchens": 0, "bedrooms": 0, "baths": 0}
rows_ = [r for r in M.bom(q, {}, {"handrail_extra_m": 4.0}, facts) if r[0] == "Handrails and balustrades"]
assert len(rows_) == 1 and abs(rows_[0][3] - 10.0) < 1e-9 and rows_[0][2] == "m", rows_
print("ok qs/handrail data")
from PySide6.QtWidgets import QApplication
app = QApplication([])
class H:
    pass
p = M.MaterialsPage(H())
import tempfile, openpyxl
wb = openpyxl.Workbook(); ws = wb.active
for r in rows:
    ws.append(r)
f = os.path.join(tempfile.mkdtemp(), "bill.xlsx"); wb.save(f)
p.import_qs(f, incl_vat=True) if False else None
import PySide6.QtWidgets as W
W.QMessageBox.information = staticmethod(lambda *a, **k: 0)
p.import_qs(f, incl_vat=True)
qs = [c for c in p.custom if c.get("src") == "QS"]
assert len(qs) == 4 and abs(qs[1]["lab"] - 1200.0 / 1.15) < 0.01
p.import_qs(f, incl_vat=False)
assert len([c for c in p.custom if c.get("src") == "QS"]) == 4                     # a second import replaces the first
assert any(r[1] == "B1 Stainless handrail" for r in p.all_rows())
p.add_handrail()
assert p.custom[-1]["unit"] == "m"
p.set_state(p.state())
print("ok qs import page")
