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
