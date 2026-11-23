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
print("ok")
