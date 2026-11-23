"""Sewer elevation from floor plan and elevation screenshots (the AI calls are simulated): the plan is laid onto the house, stacks and invert levels follow the fixtures, outputs write."""
import io, json as _j, os, tempfile, urllib.request as ur
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
import site_services as ss
import sewer_elev as se
app = QApplication.instance() or QApplication([])
d_ = tempfile.mkdtemp()
im = QImage(1000, 500, QImage.Format.Format_RGB32); im.fill(QColor("white")); shot = os.path.join(d_, "p.png"); im.save(shot)


class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass


def ai(reply):
    old = ur.urlopen
    ur.urlopen = lambda req, timeout=0: R(_j.dumps({"content": [{"type": "tool_use", "input": reply}]}).encode())
    return old


plan = {"fixtures": [{"kind": "WC", "x": 0.2, "y": 0.2}, {"kind": "WHB", "x": 0.25, "y": 0.15}, {"kind": "SH", "x": 0.1, "y": 0.3}, {"kind": "WC", "x": 0.8, "y": 0.8},
                     {"kind": "WHB", "x": 0.85, "y": 0.75}, {"kind": "S", "x": 0.5, "y": 0.1}, {"kind": "foo", "x": 0.5, "y": 0.5}],
        "building": {"x0": 0.05, "y0": 0.05, "x1": 0.95, "y1": 0.95}}
old = ai(plan)
try:
    s1 = se.read_screenshot(shot, "key", "m")
finally:
    ur.urlopen = old
assert len(s1["fixtures"]) == 6 and s1["building"][0] == 0.05                      # the unknown kind is dropped
old = ai({"levels": [{"name": "First Floor", "level": 221.49}, {"name": "Ground Floor", "level": 218.6}, {"name": "bad", "level": "x"}]})
try:
    lv = se.read_levels(shot, "key", "m")
finally:
    ur.urlopen = old
assert [x["name"] for x in lv] == ["Ground Floor", "First Floor"] and lv[0]["level"] == 218.6      # lowest first, unreadable ones dropped
for bad in ({}, {"levels": []}):
    old = ai(bad)
    try:
        se.read_levels(shot, "key", "m"); assert False
    except RuntimeError:
        pass
    finally:
        ur.urlopen = old

pg = ss.SiteServicesPage(type("W", (), {"receive_site_link": lambda s, l: "ok"})())
pg.set_state(ss.blank_state())
pg.st["sewer_via"] = [[13.2, 6.0], [13.2, 18.0]]
pg.solve_now(False)
shots = [dict(s1, name="Ground Floor", level=218.6), dict(s1, name="First Floor", level=221.49)]
pg.st["elev"] = {"shots": shots, "levels": lv}
pg._elev_model = None
mod, dat = pg.elev_data()
assert len(dat["stacks"]) >= 1 and len(dat["fixtures"]) == 12 and abs(dat["storeys"][1]["level"] - dat["storeys"][0]["level"] - 2.89) < 1e-6
assert dat["storeys"][0]["level"] > 200                                              # the levels read from the elevation are used as written
for s in dat["stacks"]:                                                              # the invert under a stack is never above what its fixtures need
    assert dat["il"](s["x"]) <= s["il_max"] + 1e-6
assert all(ok for _t, ok in dat["checks"]), dat["checks"]
a, b = se.build(pg.st, pg.res, pg._elev_model, 0), se.build(pg.st, pg.res, pg._elev_model, 1)
assert a["fixtures"][0]["u"] != b["fixtures"][0]["u"]                                # turning the plan changes which way it faces
assert se.build(pg.st, pg.res, pg._elev_model, 0, True)["side"] != a["side"]       # the other side
pg.st["levels"] = {"ngl_head": 218.45, "ngl_main": 218.3, "ffl": 218.6}              # typed levels are used
t = se.build(pg.st, pg.res, pg._elev_model)
assert not t["assumed"] and abs(t["storeys"][0]["level"] - 218.6) < 1e-9
tl = pg.title_block_lines()
for f_, fn in (("a.pdf", se.write_pdf), ("a.dxf", se.write_dxf)):
    fn(os.path.join(d_, f_), dat, tl)
se.render_image(dat, tl, 800).save(os.path.join(d_, "a.png"))
assert all(os.path.getsize(os.path.join(d_, x)) > 1000 for x in ("a.pdf", "a.dxf", "a.png"))
pg.st["levels"] = {"ngl_head": 218.45, "ngl_main": 218.45, "ffl": 218.6, "main_il": 216.5}           # the main is deep: the pipe cannot reach it without a drop
bad = se.build(pg.st, pg.res, pg._elev_model)
assert any((not ok) and "BELOW" in tx or (not ok) for tx, ok in bad["checks"]) or bad["il"](bad["length"]) >= 216.5
pg.st["levels"]["drops"] = "%.2f = %.3f" % (bad["stations"][-2]["x"], 216.5 + (bad["length"] - bad["stations"][-2]["x"]) / bad["fall"])
fixed = se.build(pg.st, pg.res, pg._elev_model)
assert abs(fixed["il"](fixed["length"]) - 216.5) < 0.003 and any(t_["drop"] > 0.5 for t_ in fixed["stations"]), [(t_["name"], t_["drop"]) for t_ in fixed["stations"]]
assert all(t_.get("name") for t_ in fixed["stations"]) and len({t_["name"] for t_ in fixed["stations"]}) == len(fixed["stations"])
se.render_image(fixed, tl, 2000).save("/tmp/elev_drop.png")
pg.st["levels"] = {"ngl_head": 218.45, "ngl_main": 218.3, "ffl": 218.6}
pg.st["elev"]["title"] = "(D) South East Block B"
assert pg.elev_data()[1]["title"] == "(D) South East Block B"
pg.st["elev"] = {}
try:
    pg.elev_data(); assert False
except ValueError:
    pass
try:
    se.build(pg.st, pg.res, dict(pg._elev_model, fixtures=[])); assert False
except ValueError:
    pass
assert se.classify("Wash hand basin") == "WHB" and se.classify("x", "SHOWER") == "SH"
pg.elev_clear_shots(); pg.elev_status()
print("ok")
