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
assert len(dd_) == 4 and M.MainWindow._thumb_pixmap(dd_).width() == 120
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
