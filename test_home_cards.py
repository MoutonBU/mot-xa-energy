"""The start screen's 'Jump back in' cards: newest projects, click to open, and a plain 'edited' phrase."""
import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget, QPushButton
import mot_xa_energy as M
app = QApplication.instance() or QApplication([])
d = tempfile.mkdtemp()
files = []
for n in ("Alpha.mcplv.json", "Beta.mcplv", "Gamma.json"):
    p = os.path.join(d, n); open(p, "w").write("{}"); files.append(p)
old = time.time() - 3 * 86400
os.utime(files[2], (old, old))
opened = []
w = QWidget(); box = QHBoxLayout(w)
class _F:
    pass
fake = _F()
fake.home_cards = box
fake._recent_load = lambda: files + ["/nowhere/x.json"]
fake._open_recent_card = lambda p: opened.append(p)
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
while time.time() - t_ < 1.6: app.processEvents()
from PySide6.QtWidgets import QGroupBox
assert all(g.graphicsEffect() is None for g in w.main_tabs.widget(0).findChildren(QGroupBox))     # the effects are gone afterwards
print("ok cascade")

# the card shows a small picture of the stand; the step bar has a progress line
pj2 = os.path.join(d, "Site.mcplv.json")
json.dump({"site": {"verts": [[0, 0], [20, 0], [20, 30], [0, 30]], "buildings": [{"x": 3, "y": 4, "w": 10, "d": 12}]}}, open(pj2, "w"))
assert w._thumb(pj2) is not None and w._thumb(pj) is None
w.main_tabs.setCurrentIndex(8)
w.site_page.steps.go(1)
t_ = time.time()
while time.time() - t_ < 0.6: app.processEvents()
assert abs(w.site_page.steps.prog.v - 0.5) < 0.01, w.site_page.steps.prog.v
print("ok thumb")
