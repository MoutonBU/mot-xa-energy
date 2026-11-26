"""Program-wide zoom: Ctrl + wheel, Ctrl + / - / 0, the magnifier button, stored zoom, sizes follow, a drawing keeps its own wheel zoom."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QWidget
import mot_xa_energy as M, app_shell as A
app = QApplication.instance() or QApplication([])
M.save_settings = lambda *a, **k: None
w = M.MainWindow(); M.apply_glass_theme(app, w); w.resize(1400, 850); w.show()
for _ in range(5): app.processEvents()
assert hasattr(w, "zoom_btn") and w.zoom_btn.isVisible()
# the magnifier sits at the top right, next to the Online AI button
assert w.zoom_btn.geometry().right() < w.mode_pill.geometry().left() + w.mode_pill.parentWidget().x() + 400
g1, g2 = w.zoom_btn.mapToGlobal(QPoint(0, 0)), w.mode_pill.mapToGlobal(QPoint(0, 0))
assert g1.x() < g2.x() and abs(g1.y() - g2.y()) < 12, (g1, g2)
h100 = w.mode_pill.height()
fs100 = w.font().pointSizeF()
def wheel(target, dy, mods=Qt.KeyboardModifier.ControlModifier):
    pos = QPointF(5, 5)
    ev = QWheelEvent(pos, target.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(target, ev)
    app.processEvents()
btn = w.mode_btn
import time as _t
def settle():
    t0 = _t.time()
    while (A._PEND[0] is not None or A._TIMER[0] is not None and A._TIMER[0].isActive()) and _t.time() - t0 < 3:
        app.processEvents()
    app.processEvents()
wheel(btn, 120); settle(); assert abs(A.ZOOM[0] - 1.1) < 1e-6, A.ZOOM[0]
wheel(btn, 120); wheel(btn, 0); settle(); assert abs(A.ZOOM[0] - 1.25) < 1e-6
# several quick notches are drawn once
_n = []
_o = A.set_zoom
A.set_zoom = lambda *a, **k: (_n.append(a), _o(*a, **k))[1]
wheel(btn, 120); wheel(btn, 120); wheel(btn, -120); wheel(btn, 120); settle()
A.set_zoom = _o
assert len(_n) == 1 and abs(A.ZOOM[0] - 1.75) < 1e-6, (_n, A.ZOOM[0])
wheel(btn, -120); wheel(btn, -120); settle(); assert abs(A.ZOOM[0] - 1.25) < 1e-6, A.ZOOM[0]
assert app.font().pointSizeF() > fs100 and btn.width() > 78, (app.font().pointSizeF(), btn.width())      # fixed sizes followed
wheel(btn, -120); wheel(btn, -120); settle(); assert abs(A.ZOOM[0] - 1.0) < 1e-6
assert btn.width() == 78 and abs(app.font().pointSizeF() - fs100) < 0.01, btn.width()
z0 = A.ZOOM[0]; wheel(btn, 120, Qt.KeyboardModifier.NoModifier); assert A.ZOOM[0] == z0                # a plain wheel does not zoom
A.set_zoom(2.0); assert btn.width() == 156 and A.zoom_pct() == "200%"
A.set_zoom(1.0); assert btn.width() == 78
# zoom is remembered
saved = {}
A._ZSAVE[0] = lambda f: saved.update(z=f)
A.step_zoom(1); settle(); assert saved["z"] == 1.1
A.step_zoom(1, 40); settle(); assert A.ZOOM[0] == 3.0
A.step_zoom(-1, 40); settle(); assert A.ZOOM[0] == 0.5
A.set_zoom(1.0)
# a drawing that zooms with its own wheel keeps it
class Canvas(QWidget):
    _own_zoom = True
    def __init__(s): super().__init__(); s.got = 0
    def wheelEvent(s, e): s.got += 1
cv = Canvas(); cv.resize(100, 100); cv.show(); app.processEvents()
wheel(cv, 120); assert cv.got == 1 and A.ZOOM[0] == 1.0
# style sheets and rich-text labels follow too
A.set_zoom(1.5); settle(); [app.processEvents() for _ in range(5)]
lab = QLabel("<span style='font-size:20px'>x</span>"); lab2 = M.QLabel("<span style='font-size:20px'>x</span>")
assert "30px" in lab2.text(), lab2.text()
t = QWidget(); t.show(); t.setStyleSheet("QWidget{font-size:12px;border:1px solid red;}"); assert "18px" in t.styleSheet(), t.styleSheet()
A.set_zoom(1.0); settle(); [app.processEvents() for _ in range(5)]; assert "12px" in t.styleSheet(), t.styleSheet()
print("ok zoom")
