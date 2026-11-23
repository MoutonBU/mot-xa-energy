"""Sewer long section: levels in, stations / checks out, and the three outputs write."""
import os, tempfile
from PySide6.QtWidgets import QApplication
import site_services as ss
import site_profile as sp
app = QApplication.instance() or QApplication([])
pg = ss.SiteServicesPage(type("W", (), {"receive_site_link": lambda s, l: "ok"})())
pg.set_state(ss.blank_state())
pg.lv_spin["ngl_head"].setValue(98.62); pg.lv_spin["ngl_main"].setValue(98.40); pg.lv_spin["main_il"].setValue(96.9); pg.lv_spots.setText("5=98.55")
assert pg.st["levels"]["ngl_head"] == 98.62 and pg.st["levels"]["spots"] == "5=98.55"
pg.solve_now(False)
d = sp.build(pg.st, pg.res)
st = d["stations"]
assert st[0]["kind"] == "RE" and abs(st[0]["depth"] - 0.45) < 1e-6 and abs(st[0]["il"] - 98.17) < 1e-6          # depth 450 at the house, level 98.62 - 0.45
assert abs(st[-1]["x"] - d["length"]) < 0.01 and st[-1]["kind"] == "MAIN"
assert all(abs((a["il"] - b["il"]) - (b["x"] - a["x"]) / 50.0) < 2e-4 for a, b in zip(st[:-1], st[1:]))         # falls 1:50 all the way
assert not d["assumed"] and d["drop"] > 0
d2 = sp.build(ss.blank_state() | {}, __import__("site_engine").solve(ss.blank_state()))
assert d2["assumed"]                                                                                           # no levels typed: says so
low = sp.build(dict(pg.st, levels={"ngl_head": 98.62, "ngl_main": 98.62, "main_il": 99.5}), pg.res)
assert any(ok is False and "BELOW" in t for t, ok in low["checks"])                                              # the main higher than the pipe cannot drain
tl = pg.title_block_lines()
with tempfile.TemporaryDirectory() as t:
    sp.write_pdf(os.path.join(t, "a.pdf"), d, tl); sp.write_dxf(os.path.join(t, "a.dxf"), d, tl); sp.render_image(d, tl, 800).save(os.path.join(t, "a.png"))
    assert all(os.path.getsize(os.path.join(t, f)) > 1000 for f in ("a.pdf", "a.dxf", "a.png"))
s2 = pg.state(); pg.set_state(s2)
assert abs(pg.lv_spin["ngl_head"].value() - 98.62) < 1e-9 and pg.lv_spots.text() == "5=98.55"
# a drop to reach a deep main: eyes at the drop, the pipe arrives at the main's invert, and the length and fall are unchanged
dd = dict(pg.st, levels={"ngl_head": 98.62, "ngl_main": 98.40, "main_il": 95.0})
d0 = sp.build(dd, pg.res)
assert d0["drop"] > 1.0
pg.lv_spin["main_il"].setValue(95.0); pg.lv_spots.setText(""); pg.add_drop_to_main()          # the choice "the program places it"
assert pg.lv_mode.currentIndex() == 1 and not pg.lv_dropx.isEnabled() and "drop" in pg.lv_dropinfo.text().lower() and "from the house outlet" in pg.lv_dropinfo.text()
x_auto = pg.lv_dropx.value()
pg.lv_mode.setCurrentIndex(2); pg.lv_dropx.setValue(3.0); pg.solve_now(False)                   # "I choose where": at 3 m, and the lower level follows
assert pg.lv_dropx.isEnabled() and pg.lv_drops.text().startswith("3.00 =") and abs(sp.build(pg.st, pg.res)["drop"]) < 0.003
pg.lv_mode.setCurrentIndex(1); pg.solve_now(False)
assert abs(pg.lv_dropx.value() - x_auto) < 0.06
pg.lv_mode.setCurrentIndex(0); pg.solve_now(False)
assert pg.lv_drops.text() == "" and "ABOVE" in pg.lv_dropinfo.text()
pg.lv_mode.setCurrentIndex(1); pg.solve_now(False)
dd["levels"]["drops"] = pg.lv_drops.text()
x_ = float(dd["levels"]["drops"].split("=")[0])
d1 = sp.build(dd, pg.res)
assert abs(d1["drop"]) < 0.003 and d1["drops"] and abs(d1["il"](d1["length"]) - 95.0) < 0.003
assert any(s_["drop"] > 1.0 and s_["kind"] == "RE" for s_ in d1["stations"]) and any("rodding eye with a drop" in s_["desc"].lower() for s_ in d1["stations"])
assert all(ok for _t, ok in d1["checks"]), d1["checks"]
# the same drop shows on the site plan: an inspection eye and a rodding eye at the drop, named as on the section
import site_engine as se
dd2 = dict(pg.st, levels=dict(dd["levels"]))
r2 = se.solve(dd2)
dn_ = [n for n in r2["sewer"]["nodes"] if n.get("drop")]
assert {n["kind"] for n in dn_} == {"RE"}, [n for n in r2["sewer"]["nodes"]]
nm = se.eye_names(r2["sewer"])
sec = {s_["name"] for s_ in d1["stations"] if s_.get("name")}
assert all(nm[id(n)] in sec for n in dn_), (sorted(nm[id(n)] for n in dn_), sec)
sp.render_image(d1, tl, 800).save(os.path.join(t, "b.png")) if False else sp.render_image(d1, tl, 800)
print("ok")

# levels below zero are levels too
import site_profile as _sp
pg.st["levels"] = {"ngl_head": -2.5, "ngl_main": -2.9, "main_il": -4.5, "ffl": -2.3}
neg = _sp.build(pg.st, pg.res)
assert not neg["assumed"] and abs(neg["ngl0"] + 2.5) < 1e-9 and neg["main_typed"] and abs(neg["main_il"] + 4.5) < 1e-9 and abs(neg["ffl"] + 2.3) < 1e-9, neg["ngl0"]
assert not _sp._set(-1000.0) and not _sp._set(None) and _sp._set(0.0) and _sp._set(-3.2)
pg.set_state(pg.state())
assert abs(pg.lv_spin["ngl_head"].value() + 2.5) < 1e-9 and abs(pg.lv_spin["main_il"].value() + 4.5) < 1e-9
pg.lv_spin["main_il"].setValue(-1000.0); pg.solve_now(False)
assert not _sp.build(pg.st, pg.res)["main_typed"]
old_ = pg.state(); old_["levels"] = {"ngl_head": 0, "ngl_main": 0, "main_il": 0, "ffl": 0}            # a project from before: 0 meant "not set"
pg.set_state(old_)
assert pg.lv_spin["ngl_head"].value() == -1000.0 and pg.lv_spin["ngl_head"].text() == "not set"
print("negative ok")

# several drops: the program places them, or you choose where; the pipe still arrives at the main's invert level
pg.set_state(ss.blank_state() if hasattr(ss, "blank_state") else pg.state())
pg.lv_spin["ngl_head"].setValue(100.0); pg.lv_spin["ngl_main"].setValue(100.0); pg.lv_spin["main_il"].setValue(95.0); pg.solve_now(False)
pg.lv_mode.setCurrentIndex(1); pg.lv_nd.setValue(3); pg.solve_now(False)
dm = sp.build(pg.st, pg.res)
assert len(dm["drops"]) == 3 and abs(dm["drop"]) < 0.002 and all(ok for _t, ok in dm["checks"]), (dm["drops"], dm["drop"])
assert "3 drops" in pg.lv_dropinfo.text() and pg.lv_dxs[2].isVisibleTo(pg) is not None
img = sp.render_image(dm, pg.title_block_lines(), 900)                                       # all three drops draw
assert img.width() > 100
assert sum(1 for n_ in pg.res["sewer"]["nodes"] if n_.get("drop")) >= 2
pg.lv_mode.setCurrentIndex(2); pg.lv_nd.setValue(2); pg.lv_dxs[0].setValue(3.0); pg.lv_dxs[1].setValue(6.5); pg.solve_now(False)
dm2 = sp.build(pg.st, pg.res)
assert [round(x_[0], 1) for x_ in dm2["drops"]] == [3.0, 6.5] and abs(dm2["drop"]) < 0.002
pg.lv_dxs[1].setValue(3.5); pg.solve_now(False)
assert "too close" in pg.lv_dropinfo.text() and abs(sp.build(pg.st, pg.res)["drop"]) < 0.002
s_ = pg.state(); pg.set_state(s_)
assert pg.lv_nd.value() == 2 and abs(pg.lv_dxs[0].value() - 3.0) < 1e-9
print("multi drops ok")
