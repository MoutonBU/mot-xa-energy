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
pg.st["levels"].update(dd["levels"]); pg.st["levels"]["drops"] = ""
pg.lv_drops.setText(""); pg.add_drop_to_main()
dd["levels"]["drops"] = pg.lv_drops.text()
x_ = float(dd["levels"]["drops"].split("=")[0])
d1 = sp.build(dd, pg.res)
assert abs(d1["drop"]) < 0.003 and d1["drops"] and abs(d1["il"](d1["length"]) - 95.0) < 0.003
assert any(s_["drop"] > 1.0 and s_["kind"] == "IE" for s_ in d1["stations"]) and any("rodding eye at the drop" in s_["desc"].lower() for s_ in d1["stations"])
assert all(ok for _t, ok in d1["checks"]), d1["checks"]
# the same drop shows on the site plan: an inspection eye and a rodding eye at the drop, named as on the section
import site_engine as se
dd2 = dict(pg.st, levels=dict(dd["levels"]))
r2 = se.solve(dd2)
dn_ = [n for n in r2["sewer"]["nodes"] if n.get("drop")]
assert {n["kind"] for n in dn_} == {"IE", "RE"}, [n for n in r2["sewer"]["nodes"]]
nm = se.eye_names(r2["sewer"])
sec = {s_["name"] for s_ in d1["stations"] if s_.get("name")}
assert all(nm[id(n)] in sec for n in dn_), (sorted(nm[id(n)] for n in dn_), sec)
sp.render_image(d1, tl, 800).save(os.path.join(t, "b.png")) if False else sp.render_image(d1, tl, 800)
print("ok")
