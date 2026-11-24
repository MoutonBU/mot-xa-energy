import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
import mot_xa_energy as M
app = QApplication([])
w = M.MainWindow(); w.resize(1400, 860)
M.apply_glass_theme(app, w); w.show()
def pump(s):
    t = time.time()
    while time.time() - t < s: app.processEvents()
pump(0.6)
assert len(app.styleSheet()) < 2000, "the whole look must not sit on the application"
w.main_tabs.setCurrentIndex(w._tab_index("Costing")); pump(0.3)
t = time.perf_counter(); w.toggle_mode(); dt = time.perf_counter() - t
assert dt < 4.0, dt
pump(0.4)
pg = w.main_tabs.currentWidget()
assert "#f" in pg.styleSheet().lower() and pg.__dict__["_thk"][0] == "light"
inv = w.main_tabs.widget(w._tab_index("Invoicing"))
assert inv.__dict__.get("_thk", ("dark",))[0] != "light"        # the page that is not on screen waits
w.main_tabs.setCurrentIndex(w._tab_index("Invoicing")); pump(0.3)
assert inv.__dict__["_thk"][0] == "light"                       # and takes the look when opened
w.toggle_mode(); pump(0.2)
assert inv.__dict__["_thk"][0] == "dark"
print("ok theme", round(dt, 2))
