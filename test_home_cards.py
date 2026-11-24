"""The start screen's 'Jump back in' cards: newest projects, click to open, and a plain 'edited' phrase."""
import os, sys, time, tempfile, types
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
fake = types.SimpleNamespace(home_cards=box, _recent_load=lambda: files + ["/nowhere/x.json"], open_project_path=lambda p: opened.append(p), _ago=M.MainWindow._ago)
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
