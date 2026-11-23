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
n0 = len(calls)
app.sendEvent(btn, QEvent(QEvent.Type.Enter))
assert calls[-1][1] == "#ff4056" and calls[-1][2] == 28, calls[-1]
app.sendEvent(btn, QEvent(QEvent.Type.Leave))
assert calls[-1][1] == "#eceef0" and len(calls) == n0 + 2
print("ok")
