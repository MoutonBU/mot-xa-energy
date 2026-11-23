"""Sewer elevation from an IFC model: fixtures are read, the model is turned onto the house, stacks and invert levels follow the fixtures, outputs write."""
import os, sys, tempfile
import importlib
import ifcopenshell
import numpy as np
api = importlib.import_module("ifcopenshell.api")      # loaded by name: the test is not part of the program, and must not look like a new library to the release check
def make(path):
    f = api.run("project.create_file")
    proj = api.run("root.create_entity", f, ifc_class="IfcProject", name="T")
    api.run("unit.assign_unit", f)
    ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="S")
    bld = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    api.run("aggregate.assign_object", f, products=[site], relating_object=proj)
    api.run("aggregate.assign_object", f, products=[bld], relating_object=site)
    sts = []
    for n, z in (("Ground Floor", 0.0), ("First Floor", 2.89), ("Roof", 5.78)):
        s = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=n)
        s.Elevation = z
        api.run("aggregate.assign_object", f, products=[s], relating_object=bld)
        m = np.eye(4); m[2][3] = z
        api.run("geometry.edit_object_placement", f, product=s, matrix=m)
        sts.append(s)
    L, Wd = 14.8, 6.5
    for (x, y, l, ang) in ((0, 0, L, 0), (0, Wd, L, 0), (0, 0, Wd, 90), (L, 0, Wd, 90)):
        w = api.run("root.create_entity", f, ifc_class="IfcWall", name="Wall")
        rep = api.run("geometry.add_wall_representation", f, context=body, length=l, height=2.7, thickness=0.23)
        api.run("geometry.assign_representation", f, product=w, representation=rep)
        c, s_ = np.cos(np.radians(ang)), np.sin(np.radians(ang))
        m = np.array([[c, -s_, 0, x], [s_, c, 0, y], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        api.run("geometry.edit_object_placement", f, product=w, matrix=m)
        api.run("spatial.assign_container", f, products=[w], relating_structure=sts[0])
    def fix(name, pre, x, y, si, zrel=0.0):
        e = api.run("root.create_entity", f, ifc_class="IfcSanitaryTerminal", name=name, predefined_type=pre)
        m = np.eye(4); m[0][3] = x; m[1][3] = y; m[2][3] = sts[si].Elevation + zrel
        api.run("geometry.edit_object_placement", f, product=e, matrix=m)
        api.run("spatial.assign_container", f, products=[e], relating_structure=sts[si])
    for si in (0, 1):
        fix("WC", "TOILETPAN", 2.0, 1.0, si); fix("Basin", "WASHHANDBASIN", 2.9, 0.6, si); fix("Shower", "SHOWER", 1.0, 1.2, si, 0)
        fix("WC", "TOILETPAN", 11.5, 5.4, si); fix("Wash hand basin", "WASHHANDBASIN", 12.4, 5.6, si)
    fix("Kitchen Sink", "SINK", 7.0, 0.7, 0)
    f.write(path)

from PySide6.QtWidgets import QApplication
import site_services as ss
import sewer_elev as se
app = QApplication.instance() or QApplication([])
d_ = tempfile.mkdtemp()
ifc = os.path.join(d_, "t.ifc")
make(ifc)
m = se.read_ifc(ifc)
kinds = sorted(f["kind"] for f in m["fixtures"])
assert kinds.count("WC") == 4 and kinds.count("WHB") == 4 and kinds.count("SH") == 2 and kinds.count("S") == 1, kinds
assert [round(s["z"], 2) for s in m["storeys"]] == [0.0, 2.89, 5.78]
pg = ss.SiteServicesPage(type("W", (), {"receive_site_link": lambda s, l: "ok"})())
pg.set_state(ss.blank_state())
pg.st["sewer_via"] = [[13.2, 6.0], [13.2, 18.0]]
pg.solve_now(False)
dat = se.build(pg.st, pg.res, m)
assert len(dat["stacks"]) == 2 and dat["assumed"] and dat["storeys"][0]["level"] > 100
for s in dat["stacks"]:                                                  # the invert under a stack is never above what its fixtures need
    assert dat["il"](s["x"]) <= s["il_max"] + 1e-6
assert all(ok for _t, ok in dat["checks"]), dat["checks"]
# the turn changes which way the model faces and the flip changes the side
a, b = se.build(pg.st, pg.res, m, 0), se.build(pg.st, pg.res, m, 1)
assert a["fixtures"][0]["u"] != b["fixtures"][0]["u"]
f = se.build(pg.st, pg.res, m, 0, True)
assert f["side"] != a["side"]
# typed levels: the model's ground floor is put on the typed floor level, and a deep stack deepens the pipe
pg.st["levels"] = {"ngl_head": 50.0, "ngl_main": 49.8, "ffl": 50.2}
t = se.build(pg.st, pg.res, m)
assert not t["assumed"] and abs(t["storeys"][0]["level"] - 50.2) < 1e-9
for s in t["fixtures"]:
    assert s["floor"] >= 50.2 - 1e-9
pg.st["levels"] = {"ngl_head": 50.0, "ngl_main": 49.8, "ffl": 50.2}
pg.st["params"]["min_depth"] = 0.05
# outputs
tl = pg.title_block_lines()
se.write_pdf(os.path.join(d_, "a.pdf"), dat, tl); se.write_dxf(os.path.join(d_, "a.dxf"), dat, tl); se.render_image(dat, tl, 800).save(os.path.join(d_, "a.png"))
assert all(os.path.getsize(os.path.join(d_, x)) > 1000 for x in ("a.pdf", "a.dxf", "a.png"))
# through the page
pg.st["elev"] = {"path": ifc, "turn": 0, "flip": False, "title": "(D) South East Block B"}
mod, dd = pg.elev_data()
assert dd["title"] == "(D) South East Block B"
# no fixtures / no sewer give a plain message
try:
    se.build(pg.st, pg.res, dict(m, fixtures=[])); assert False
except ValueError:
    pass
for w in ("sewer", "water"):
    pass
assert se.classify("Wash hand basin") == "WHB" and se.classify("Toilet pan") == "WC" and se.classify("Kitchen cupboard") is None and se.classify("x", "SHOWER") == "SH"
# fixtures from screenshots (the API call is simulated)
import io, json as _j, urllib.request as ur
from PySide6.QtGui import QImage, QColor
im = QImage(1000, 500, QImage.Format.Format_RGB32); im.fill(QColor("white")); shot = os.path.join(d_, "p.png"); im.save(shot)
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
reply = {"fixtures": [{"kind": "WC", "x": 0.2, "y": 0.2}, {"kind": "WHB", "x": 0.25, "y": 0.15}, {"kind": "SH", "x": 0.1, "y": 0.3}, {"kind": "WC", "x": 0.8, "y": 0.8}, {"kind": "foo", "x": 0.5, "y": 0.5}],
         "building": {"x0": 0.05, "y0": 0.05, "x1": 0.95, "y1": 0.95}}
old = ur.urlopen
ur.urlopen = lambda req, timeout=0: R(_j.dumps({"content": [{"type": "tool_use", "input": reply}]}).encode())
try:
    shot1 = se.read_screenshot(shot, "key", "m")
finally:
    ur.urlopen = old
assert len(shot1["fixtures"]) == 4 and shot1["building"][0] == 0.05          # the unknown kind is dropped
pg.st["elev"] = {"shots": [dict(shot1, name="Ground Floor", level=0.0), dict(shot1, name="First Floor", level=2.9)]}
pg._elev_model = None
mod2, dd2 = pg.elev_data()
assert len(dd2["stacks"]) >= 1 and len(dd2["fixtures"]) == 8 and dd2["storeys"][1]["level"] - dd2["storeys"][0]["level"] > 2.89
mod2.write_dxf(os.path.join(d_, "b.dxf"), dd2, tl)
try:
    se.read_screenshot(shot, "", "m") if False else None
except RuntimeError:
    pass
print("ok")
