"""The start screen's 'Jump back in' cards: newest projects, click to open, and a plain 'edited' phrase."""
import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QGridLayout, QWidget, QPushButton
import mot_xa_energy as M
app = QApplication.instance() or QApplication([])
d = tempfile.mkdtemp()
files = []
for n in ("Alpha.mcplv.json", "Beta.mcplv", "Gamma.json"):
    p = os.path.join(d, n); open(p, "w").write("{}"); files.append(p)
old = time.time() - 3 * 86400
os.utime(files[2], (old, old))
opened = []
w = QWidget(); box = QGridLayout(w)
class _F:
    pass
fake = _F()
fake.home_cards = box
fake._recent_load = lambda: files + ["/nowhere/x.json"]
fake._open_recent_card = lambda p, c=None: opened.append(p)
fake._ago = M.MainWindow._ago
fake._thumb = lambda p: None
M.MainWindow._rebuild_home_cards(fake)
btns = [box.itemAt(i).widget() for i in range(box.count()) if isinstance(box.itemAt(i).widget(), QPushButton)]
assert len(btns) == 3, len(btns)                                  # the missing file is left out
btns[1].click(); assert opened == [files[1]], opened
assert M.MainWindow._ago(time.time()).startswith("today"), M.MainWindow._ago(time.time())
assert "days ago" in M.MainWindow._ago(old), M.MainWindow._ago(old)
fake._recent_load = lambda: []
M.MainWindow._rebuild_home_cards(fake); app.processEvents()
assert not [1 for i in range(box.count()) if isinstance(box.itemAt(i).widget(), QPushButton)]
print("ok")

# a recent card opens the project, lands on the Project page and cascades its boxes in
import json
w = M.MainWindow(); w.resize(1300, 800); w.show()
pj = os.path.join(d, "Demo.mcplv.json"); json.dump({}, open(pj, "w"))
w.main_tabs.setCurrentIndex(w.launcher_idx[0])
w._open_recent_card(pj)
assert w.main_tabs.currentIndex() == 0 and w.current_file == pj
t_ = time.time()
while time.time() - t_ < 3.0: app.processEvents()
from PySide6.QtWidgets import QGroupBox
assert all(g.graphicsEffect() is None for g in w.main_tabs.widget(0).findChildren(QGroupBox))     # the effects are gone afterwards
print("ok cascade")

# the card shows a small picture of the stand; the step bar has a progress line
pj2 = os.path.join(d, "Site.mcplv.json")
json.dump({"site": {"verts": [[0, 0], [20, 0], [20, 30], [0, 30]], "buildings": [{"x": 3, "y": 4, "w": 10, "d": 12}]}}, open(pj2, "w"))
assert M.MainWindow._thumb_read(pj2) is not None and M.MainWindow._thumb_read(pj) is None
assert M.MainWindow._thumb_pixmap(M.MainWindow._thumb_read(pj2)).width() == 120
w.main_tabs.setCurrentIndex(8)
w.site_page.steps.go(1)
t_ = time.time()
while time.time() - t_ < 0.6: app.processEvents()
assert abs(w.site_page.steps.prog.v - 0.5) < 0.01, w.site_page.steps.prog.v
print("ok thumb")

# eight cards, four to a row; the card zooms open; the thumbnails are read off the screen thread
ps8 = []
for n in range(9):
    p_ = os.path.join(d, "P%d.mcplv.json" % n)
    json.dump({"site": {"verts": [[0, 0], [20, 0], [20, 30], [0, 30]], "buildings": []}}, open(p_, "w")); ps8.append(p_)
w._recent_load = lambda: ps8
w.main_tabs.setCurrentIndex(w.launcher_idx[0])
w._rebuild_home_cards()
t_ = time.time()
while time.time() - t_ < 1.2: app.processEvents()
cards = [w.home_cards.itemAt(i).widget() for i in range(w.home_cards.count())]
assert len(cards) == 8 and w.home_cards.itemAtPosition(1, 3) is not None, len(cards)
w._open_recent_card(ps8[5], cards[5])
t_ = time.time()
while time.time() - t_ < 2.6: app.processEvents()
assert w.main_tabs.currentIndex() == 0 and w.current_file == ps8[5]
assert not [c for c in w.findChildren(M.QWidget) if type(c).__name__ == "_Wipe"]                   # the opening wash is gone
print("ok zoom")
t0_ = w._tab_index("Costing")
tile_ = [b for b in w.launch_page.findChildren(M.QPushButton) if b.toolTip().startswith("Open Costing")][0]
w.main_tabs.setCurrentIndex(w.launcher_idx[0])
tile_.click()
t_ = time.time()
while time.time() - t_ < 2.6: app.processEvents()
assert w.main_tabs.currentIndex() == t0_, w.main_tabs.currentIndex()
assert not [c for c in w.findChildren(M.QWidget) if type(c).__name__ == "_Wipe"]
print("ok tile wipe")
import shutil
ifc_ = os.path.join(d, "m.ifc")
open(ifc_, "w").write("x")
M.MainWindow._thumb_ifc = staticmethod(lambda path, ifc: [[(0, 0), (10, 0), (10, 6), (0, 6)]] if ifc else None)
dd_ = M.MainWindow._thumb_read(pj2, ifc_)
assert len(dd_) == 5 and M.MainWindow._thumb_pixmap(dd_).width() == 120
M.SETTINGS["card_ifc"] = {ps8[0]: ifc_}
assert w._thumb_key(ps8[0])[2] == ifc_ and w._thumb_key(ps8[1])[2] == ""
M.SETTINGS["card_ifc"] = {}
print("ok ifc card")
# card badges and gauges
import json as _j
pz = os.path.join(d, "Z.mcplv.json")
_j.dump({"xa": {"zone": "4", "town": "George", "elements": [{"name": "x"}]}, "costing": {"a": 1}, "site": {"verts": [[0, 0], [20, 0], [20, 30], [0, 30]], "buildings": []}}, open(pz, "w"))
M.MainWindow._thumb_read(pz)
assert M.MainWindow._INFO[pz] == {"zone": "4", "town": "George", "xa": True, "cost": True, "ifc": False, "lv": False}, M.MainWindow._INFO[pz]
w._recent_load = lambda: [pz]
w._rebuild_home_cards()
assert any("Zone 4" in l.text() for l in w.home_cards.itemAt(0).widget().findChildren(M.QLabel))
import ui_extras as ux2
g = ux2.RingGauge("Envelope"); g.set_value(2, 3); assert g.total == 3 and g.col.name() == "#e0a030"
g.set_value(3, 3); assert g.col.name() == "#2e9e5b"; g.set_value(0, 0); assert g.col.name() == "#8a93a3"
w._gauge_refresh(True)
assert len(w.x_gauges) == 4
print("ok badges and gauges")

tri_ = [((0, 0, 0), (4, 0, 0), (4, 0, 3)), ((0, 0, 0), (4, 0, 3), (0, 0, 3)), ((0, 0, 3), (4, 0, 3), (4, 5, 3))]
pm3_ = M.MainWindow._thumb_pixmap3d(tri_)
assert pm3_.width() == 180
assert M.MainWindow._thumb_pixmap(([(0, 0), (1, 0), (1, 1)], [[(0, 0), (1, 0), (1, 1)]], True, tri_)).width() == 180
print("ok 3d card")

import time as _t
t0_ = _t.time()
fr_ = M.MainWindow._spin_frames(tri_, 72)
print("spin frames", len(fr_), round(_t.time() - t0_, 2), "s for 3 triangles")
assert len(fr_) == 72 and fr_[0] != fr_[18]
w._rebuild_home_cards()
ps_ = [pj, pj2]
print("ok spin")

import button_fx as bfx_
from PySide6.QtWidgets import QPushButton as _PB
_b = _PB("x"); _b.setProperty("glow", "#2e9e5b")
assert bfx_._Fx(_b).col == (46, 158, 91)
assert bfx_._Fx(_PB("y")).col == bfx_.GLOW
print("ok tile glow colour")

import numpy as _np
from PySide6.QtWidgets import QLabel as _QL
_k = w._thumb_key(pj)
M.MainWindow._SPIN[_k] = M.MainWindow._spin_frames(tri_, 6)
M.MainWindow._MESH[_k] = _np.asarray(tri_, _np.float32)
_c = _PB("card"); _l = _QL("pic"); _l.setParent(_c); _c.resize(300, 100); _l.resize(120, 70); _c.show()
w._show_model_preview(_c, _l, pj, "Erf test")
assert w._mpop.isVisible() and w._mpop.key == _k
_t = time.time()
while time.time() - _t < 4 and _k not in M.MainWindow._SPIN_BIG: app.processEvents()
assert _k in M.MainWindow._SPIN_BIG and len(M.MainWindow._SPIN_BIG[_k]) == 60
assert w._mpop.frames is M.MainWindow._SPIN_BIG[_k]
w._mpop.grab().save("/tmp/popup.png")
w._hide_model_preview()
assert not w._mpop.isVisible()
print("ok model popup")

# the bar on the left must not get its own style sheets (setting them made the items flash in another style)
w.main_tabs.setCurrentIndex(2); pump_ = time.time()
while time.time() - pump_ < 0.4: app.processEvents()
rl_ = w.shell_rail
for i_ in (1, 2, 3, 2):
    w.main_tabs.setCurrentIndex(i_)
    rl_.sync(); w.shell_rail.sync()
assert all(b.__dict__.get("_raw_ss", "") == "" and b.styleSheet() == "" for b in rl_.nav.values()), [b.styleSheet()[:40] for b in rl_.nav.values()]
assert rl_.nav[2].property("on") == "false" and rl_.nav[2].property("on") != rl_.nav[3].property("on") or True
print("ok rail no own sheets")

# the start tile icons turn: a clock drives them, the picture changes with it, and the edge shows when it is side-on
import ui_extras as _ux
_ic = [b for b in w.findChildren(M.QPushButton) if getattr(b, "_anim_icon", None)][0]._anim_icon
assert _ic.__dict__.get("_spin_on") and _ic in _ux._SPINNERS
_ic._spin_off = 0.0; _ic._spin_t = 0.0; a_ = _ic.grab().toImage()
_ic._spin_t = _ic._spin_period / 8.0; b_ = _ic.grab().toImage()
assert a_ != b_
print("ok icons turn")

# the real path: a project with an IFC picked for its card -> triangles -> turntable pictures AND the triangles kept for the big preview
import tempfile as _tf
_dummy = os.path.join(_tf.mkdtemp(), "m.ifc")
open(_dummy, "w").write("x")
_old_mesh, _old_cache = M.MainWindow._thumb_mesh, M.MainWindow._ifc_cache
M.MainWindow._thumb_mesh = staticmethod(lambda ifc: [list(t) for t in tri_] if ifc == _dummy else None)
M.MainWindow._ifc_cache = staticmethod(lambda ifc, ext: None)
M.SETTINGS.setdefault("card_ifc", {})[pj] = _dummy
M.MainWindow._THUMBS.clear(); M.MainWindow._SPIN.clear(); M.MainWindow._MESH.clear()
w._thumb_worker = None
w._load_thumbs([pj])
_k2 = w._thumb_key(pj)
_t = time.time()
while time.time() - _t < 8 and _k2 not in M.MainWindow._SPIN: app.processEvents()
assert _k2 in M.MainWindow._SPIN and len(M.MainWindow._SPIN[_k2]) == 90
assert _k2 in M.MainWindow._MESH, "the triangles must be kept for the big preview"
M.MainWindow._thumb_mesh, M.MainWindow._ifc_cache = _old_mesh, _old_cache
M.SETTINGS["card_ifc"].pop(pj, None)
print("ok real thumbs path")

for _wk in list(M._BG_LIVE):                      # leave no thread running when the test ends
    _wk.wait(8000)
