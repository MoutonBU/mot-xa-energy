"""The area schedule is the last step of Building lines, in the Site colour; the old tab number redirects there."""
import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
import mot_xa_energy as M
app = QApplication.instance() or QApplication([])
w = M.MainWindow(); w.resize(1400, 850); w.show()
def pump(s=0.4):
    t = time.time()
    while time.time() - t < s: app.processEvents()
pump()
assert w.area_page.parent() is not None and not w.main_tabs.isTabVisible(7)
assert w.site_page.STEP_NAMES[-1] == "Area schedule" and len(w.site_page.steps.names) == 4
w.main_tabs.setCurrentIndex(7); pump()
assert w.main_tabs.currentIndex() == 8 and w.site_page.steps.i == 3
assert M.ACCENT_COL[0] == "#c08e5c", M.ACCENT_COL[0]
assert w.shell_ribbon.stack.currentWidget() is w.shell_ribbon.pages[7]          # the area schedule's own buttons show
w.site_page.steps.go(0); pump()
assert w.shell_ribbon.stack.currentWidget() is w.shell_ribbon.pages[8]
assert '"land", "Building lines"),' in open(M.__file__, encoding="utf-8").read()   # the Site and areas tile opens Building lines straight away
print("ok")
