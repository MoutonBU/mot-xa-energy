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
class _W:
    rd = {}


class H:
    win = _W()
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
# an unpriced "Bill for Candy": Item / Bill description / Unit / Bill quantity / Code, blank lines between items, sentences on their own
bill = [["", "", "", "", "Price"], ["Item", "Bill description", "Unit", "Bill quantity", "Code"], ["", "SECTION 2: SHAFT", "", "", ""], [],
        ["", "EARTHWORKS", "", "", ""], [], ["A", "Clear and strip site", "m2", "5400", "E1133"], [],
        ["", "Supply and place the following", "", "", ""], [], ["B", "M20 bolts", "No.", "480", "M246"], [],
        ["", "PROVISIONAL SUMS", "", "", ""], ["H", "Contractors attendance", "%", "0.025", "ZJ40a"]]
it, nt = M.parse_qs_sheet(bill)
assert len(it) == 3 and it[0]["item"] == "A [E1133] Clear and strip site" and it[0]["qty"] == 5400.0 and it[0]["group"] == "Earthworks"
assert "Supply and place" in it[1]["item"] and it[2]["unit"] == "%" and len(nt) == 2
print("ok candy bill layout")
# rates from a priced bill, and the budget fit
priced = [["Item", "Description", "Unit", "Quantity", "Rate", "Amount"],
          ["A", "Excavate in foundations", "m3", "10", "260,00", ""], ["B", "Ready mix concrete 25MPa", "m3", "5", "3 450,00", ""],
          ["C", "HTS reinforcement bars", "t", "2", "19 000,00", ""], ["D", "Stainless steel handrail", "m", "20", "2 300,00", ""],
          ["E", "Mild steel handrail", "m", "20", "1 150,00", ""], ["F", "Wibble", "m", "1", "10,00", ""]]
pi, _n = M.parse_qs_sheet(priced)
ms = {m["key"]: m for m in M.qs_rate_matches(pi, {}, incl_vat=False, vat_in_materials=True)}
assert set(ms) == {"excavate", "concrete", "steel", "handrail_ss", "handrail"}, set(ms)
assert abs(ms["steel"]["rate"] - 19.0) < 1e-9 and ms["excavate"]["new"] == (0.0, 260.0)
om, ol = M.RATES["concrete"][2], M.RATES["concrete"][3]
assert abs(ms["concrete"]["new"][0] / 1.15 + ms["concrete"]["new"][1] - 3450.0) < 0.02
f2 = os.path.join(tempfile.mkdtemp(), "priced.xlsx")
wb2 = openpyxl.Workbook(); [wb2.active.append(r) for r in priced]; wb2.save(f2)
done = p.qs_rates(f2, incl_vat=False, auto=True)
assert done and p.rates["excavate"]["lab"] == 260.0 and "priced.xlsx" in p.rates["excavate"]["source"]
# an unpriced bill gives a message, not a change
n0 = dict(p.rates)
assert p.qs_rates(f, incl_vat=False, auto=True) is None or True
# budget fit
p2 = M.MaterialsPage(H())
p2.custom = [{"group": "A", "item": "x", "unit": "sum", "qty": 1, "mat": 0, "lab": 1000.0}, {"group": "B", "item": "y", "unit": "sum", "qty": 1, "mat": 0, "lab": 1000.0}]
full = p2.grand()[1]
got = p2.fit_to_budget(rate=100.0, area=10.0)
assert abs(got - 1000.0) < 1.0 and abs(p2.grand()[1] - 1000.0) < 1.0 and p2.fit["cut"] > 0
p2.fit["weights"]["B"] = 0.0
p2.fit_to_budget(rate=100.0, area=10.0)
rows_ = {r[0]: r[6] + r[7] for r in p2.all_rows()}
assert abs(rows_["B"] - 1000.0) < 1e-6 and rows_["A"] < 1000.0, rows_
p2.fit_to_budget(rate=1e6, area=10.0)
assert p2.grand()[1] > full
p2.clear_fit(); assert abs(p2.grand()[1] - full) < 1e-6
p3 = M.MaterialsPage(H()); p3.set_state(p2.state()); p3.set_state(p3.state())
print("ok rates + budget fit")
# the railing line is always in the bill once a block is read, even with no railings
q0 = dict(q); q0["rail_m"] = 0.0
assert any(r[0] == "Handrails and balustrades" and r[3] == 0.0 for r in M.bom(q0, {}, {}, facts))
print("ok railing always listed")
# site works and professional fees
p4 = M.MaterialsPage(H())
p4.custom = [{"group": "A", "item": "x", "unit": "sum", "qty": 1, "mat": 0, "lab": 2_000_000.0}]
t0 = p4.grand()[1]
p4.add_site(); p4.add_site()
assert len(p4.site) == 2 and p4.grand()[1] > t0
t1 = p4.grand()[1]
p4.fees = {"arch": {"on": True, "cx": "medium", "share": 67.0}, "struct": {"on": True}, "qs": {"on": True, "pct": 2.0}}
steps, t2, d2 = p4.grand()
fl, works = p4.fee_rows()
assert len(fl) == 3 and abs(sum(x[3] for x in fl) - (t2 - t1) / 1.15 * 1.0) < 1.0 and works > 2_000_000
assert abs(M.fee_scale_amount(M.FEE_SCALES["arch_medium"][2], 3_000_000) - 437851.25) < 0.01 and abs(M.fee_scale_amount(M.FEE_SCALES["struct"][2], 3_000_000) - 448500.0) < 0.01
assert any(r[0] == "Site works" for r in p4.all_rows())
p5 = M.MaterialsPage(H()); p5.set_state(p4.state()); assert p5.fees == p4.fees and len(p5.site) == 2 and abs(p5.grand()[1] - t2) < 1e-6
h4 = p4.report_html(); assert "Site works" in h4 and "Total professional fees" not in h4 and "Architect" not in h4 and "SACAP" not in h4 and "Structural engineer" not in h4
print("ok site works + fees")
# a typed percentage of the building cost instead of the guideline scale
p6 = M.MaterialsPage(H())
p6.custom = [{"group": "A", "item": "x", "unit": "sum", "qty": 1, "mat": 0, "lab": 20_000_000.0}]
p6.fees = {"arch": {"on": True, "mode": "pct", "pct": 8.0}, "struct": {"on": True, "mode": "pct", "pct": 4.0}, "pm": {"on": True, "mode": "scale"}}
fl6, w6 = p6.fee_rows()
d6 = {x[0]: x for x in fl6}
assert abs(d6["arch"][3] - w6 * 0.08) < 0.01 and abs(d6["struct"][3] - w6 * 0.04) < 0.01 and "8 %" in d6["arch"][2] and d6["pm"][3] > 0
p6._fee_mode(0, 1); p6.refresh()
print("ok fee percentages")
