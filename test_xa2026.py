import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
import mot_xa_energy as M
# Annex C: the new towns, SCCP flag, coordinates
assert M.XA_TOWNS["Albertinia"] == "4" and M.XA_TOWNS["Alexandria"] == "4" and M.XA_TOWNS["Colesberg"] == "1" and M.XA_TOWNS["Ubombo"] == "5"
assert "Albertinia *" not in M.XA_TOWNS and "Colesberg *" not in M.XA_TOWNS
assert M.xa_sccp("George") and M.xa_sccp("Mosselbaai") and not M.xa_sccp("Johannesburg") and not M.xa_sccp("Knysna")
assert M.xa_sccp("Wilderness *") == M.xa_sccp(M.XA_NEAREST["Wilderness *"])      # a town worked out from a near one takes its answer
assert len(M.XA_SCCP) == 32 and abs(M.XA_COORDS["George"][1] - 33.963) < 0.2
assert "condensation" in M.xa_town_note("George").lower() and "condensation" not in M.xa_town_note("Johannesburg").lower()
# tables are as in the 2026 edition
assert M.XA_MAX_CONS["H4"] == [95, 100, 50, 80, 85, 60, 110, 110] and M.XA_MAX_DEMAND["H4"][2] == 40
assert M.XA_TABLE4[1] == (25, 5.20, 0.66, 0.49) and M.LT_LPD_TABLE["F1"] == 20
# roof lights (5.3.9, table 5)
assert M.xa_rooflight_limits(1.0)[0] is None
assert M.xa_rooflight_limits(2.0)[:2] == (5.8, 0.75) and M.xa_rooflight_limits(4.0)[:2] == (5.8, 0.50)
assert M.xa_rooflight_limits(8.0)[:2] == (2.7, 0.25) and M.xa_rooflight_limits(12.0)[:2] == (2.0, 0.25)
# thatch (5.6.6), category 1 walls (5.5.2)
assert M.xa_thatch_min("1")[0] == 210 and M.xa_thatch_min("5H")[0] == 175 and M.xa_thatch_min("3", True)[0] == 300
r = M.xa_check_element({"name": "Thatch", "type": "Roof / ceiling", "layers": [{"mat": "Thatch grass", "t": 150}]}, "1")
assert "210" in r["notes"] and "only 150" in r["notes"], r["notes"]
assert M.xa_cat1_wall_note(110) and not M.xa_cat1_wall_note(140)
assert len(M.XA_AC_COP) == 19 and M.XA_SENSOR_MAX_M2 == 100.0
# the routes carry the 2026 clause numbers and old saved projects still map
assert "4.2" in M.RD_ROUTES[0] and "4.4" in M.RD_ROUTES[1]
assert M.rd_route("Rational design (SANS 10400-XA:2021 clause 4.3) - reference building") == M.RD_ROUTES[1]
assert M.rd_route("Deemed-to-satisfy (SANS 10400-XA:2021 clause 4.4)") == M.RD_ROUTES[0]
print("ok xa2026")
