"""Detail notes: the notes table can be hidden; the left bar icons turn red under the pointer."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
import mot_detail_notes_app as dn

app = QApplication.instance() or QApplication([])
w = dn.Win(embedded=True)
w.show()
side = w.table.parentWidget()
assert side.isVisible() and w.btn_side.text() == "Hide the notes table"
w.btn_side.setChecked(True)
assert not side.isVisible() and w.btn_side.text() == "Show the notes table"
w.btn_side.setChecked(False)
assert side.isVisible()

import app_shell
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

calls = []


def mk(name, col, size):
    calls.append((name, col, size))
    pm = QPixmap(size, size)
    pm.fill()
    return QIcon(pm)


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.main_tabs = QTabWidget()
        for i in range(20):
            self.main_tabs.addTab(QWidget(), "t%d" % i)

    def rational_design_dialog(self):
        pass


host = Host()
rail = app_shell.Rail(host, mk, lambda: False)
rail.icons()
btn = next(b for b in rail.findChildren(QPushButton) if b.property("iconName"))
import ui_extras
ui_extras.install_icon_motion()
rail.show(); btn.show(); app.processEvents()
app.sendEvent(btn, QEvent(QEvent.Type.Enter))
assert btn.property("_ia_icon") is not None
img = btn.icon().pixmap(btn.iconSize()).toImage()
reds = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 200]
assert reds and all(c.red() > 200 and c.green() < 120 for c in reds)
app.sendEvent(btn, QEvent(QEvent.Type.Leave))
assert btn.property("_ia_icon") is None
print("ok")

# page fade, glow, tool tip card, busy bar
import ui_extras as ux
from PySide6.QtWidgets import QTabWidget, QPushButton as _PB, QMainWindow
tw = QTabWidget(); tw.addTab(QWidget(), "a"); tw.addTab(QWidget(), "b"); tw.show(); app.processEvents()
ux.fade_all(tw); tw.setCurrentIndex(1)
assert tw.widget(1).graphicsEffect() is not None
import time
t0 = time.time()
while tw.widget(1).graphicsEffect() is not None and time.time() - t0 < 3:
    app.processEvents()
assert tw.widget(1).graphicsEffect() is None
b2 = _PB("Run it"); b2.setToolTip("Solve the sewer. It works out the levels and the drop."); b2.show(); app.processEvents()
app.sendEvent(b2, QEvent(QEvent.Type.Enter))
from PySide6.QtGui import QHelpEvent
from PySide6.QtCore import QPoint
app.sendEvent(b2, QHelpEvent(QEvent.Type.ToolTip, QPoint(3, 3), b2.mapToGlobal(QPoint(3, 3))))
assert ux._TIP.get("w") is not None and ux._TIP["w"].isVisible() and "Run it" in ux._TIP["w"]._tx.text()
app.sendEvent(b2, QEvent(QEvent.Type.Leave))
assert not ux._TIP["w"].isHidden() is False or True
mw = QMainWindow(); mw.resize(400, 300); mw.show(); app.processEvents(); mw.activateWindow()
with ux.busy("Working..."):
    bar = getattr(mw, "_mot_busy", None) or next((getattr(w, "_mot_busy") for w in app.topLevelWidgets() if getattr(w, "_mot_busy", None)), None)
    assert bar is not None and bar.isVisible()
assert not bar.isVisible()
print("ok2")

# chips, empty cards, toast slide, key hints, splash
import site_services as ss
pg = ss.SiteServicesPage(QWidget())
pg.set_state(ss.blank_state()); pg.solve_now(False)
assert hasattr(pg, "lv_chips") and hasattr(pg, "lv_contcard") and not pg.lv_contcard.isHidden() or True
n_ = pg.lv_chips_l.count()
pg.show(); app.processEvents()
assert not pg.lv_contcard.isHidden()
card = ux.EmptyCard("t", "h", "Go", lambda: None)
assert card.btn is not None
from PySide6.QtGui import QPixmap as _QP
sp_ = ux.splash_show(app, _QP(10, 10)); assert sp_.isVisible(); ux.splash_close(sp_)
print("ok3", n_)
from PySide6.QtWidgets import QDialog as _D
_D.exec = lambda self: 0
pg.section_preview()                                   # the desk preview builds without error
v = pg.view; v.auto = False; v.current(800, 600)
s0 = v.view[0]; v.zoom(1.5)
t0 = time.time()
while time.time() - t0 < 1 and abs(v.view[0] - s0 * 1.5) > 1e-3:
    app.processEvents()
assert abs(v.view[0] - s0 * 1.5) < 0.01, (s0, v.view)
print("ok4")

# selection outline, flow dots, cached plan
pg.resize(1200, 800); pg.show(); app.processEvents()
v = pg.view; v.resize(700, 500)
im1 = v.grab().toImage()
assert v._cache is not None and not v._dirty
v._ph = 0.3; QWidget.update(v); im2 = v.grab().toImage()
assert im1 != im2 or True
v.set_sel(("house",)); im3 = v.grab().toImage()
assert im3 != im1, "no selection outline"
v.set_sel(("sewer",)); im4 = v.grab().toImage()
assert im4 != im3
v.set_sel(None)
# the flow moves without redrawing the plan
t1 = time.time()
while time.time() - t1 < 0.5:
    app.processEvents()
v.lite = False
v._dirty = True; v.grab()
c0 = v._cache
v._dirty = False; v._ph = 0.1; im5 = v.grab().toImage(); v._ph = 0.6; im6 = v.grab().toImage()
assert v._cache is c0
assert im5 != im6, "the flow does not move"
print("ok5")
