"""Icons move: a tile's big icon reacts to hover and press, and small button icons grow while pointed at and return afterwards."""
from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, QEventLoop
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QWidget, QVBoxLayout
import ui_extras as ux

app = QApplication.instance() or QApplication([])
ux.install_icon_motion()
ux.install_icon_motion()                                      # twice is harmless


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def until(cond, ms=5000):                                      # a busy machine runs animations late: wait for the state, not for a time
    for _ in range(ms // 25):
        if cond():
            return True
        wait(25)
    return cond()


pm = QPixmap(72, 72)
pm.fill(QColor("#ff4056"))
host = QWidget()
v = QVBoxLayout(host)
tile = QPushButton("tile")
ai = ux.AnimIcon(pm, "#ff4056", 108)
tile._anim_icon = ai
small = QPushButton(QIcon(pm), "Open")
small.setIconSize(QSize(18, 18))
v.addWidget(tile)
v.addWidget(ai)
v.addWidget(small)
host.show()
wait(50)
w0, h0 = small.width(), small.height()
app.sendEvent(tile, QEvent(QEvent.Type.Enter))
app.sendEvent(small, QEvent(QEvent.Type.Enter))
until(lambda: ai._h > 0.9 and ai._w >= 0.99 and small.iconSize().width() > 18)
assert ai._h > 0.9 and ai._w >= 0.99, (ai._h, ai._w)
assert small.iconSize().width() > 18 and small.size().width() == w0 and small.size().height() == h0, small.iconSize()    # grows, the button does not
# a press squeezes, a release pops back
press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(tile, press)
app.sendEvent(small, press)
until(lambda: ai._p > 0.9 and small.iconSize().width() < 18)
assert ai._p > 0.9 and small.iconSize().width() < 18, (ai._p, small.iconSize())
rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(tile, rel)
app.sendEvent(small, rel)
until(lambda: ai._p < 0.05)
# leaving puts everything back
app.sendEvent(tile, QEvent(QEvent.Type.Leave))
app.sendEvent(small, QEvent(QEvent.Type.Leave))
until(lambda: ai._h < 0.05 and small.iconSize() == QSize(18, 18) and small.minimumSize() == QSize(0, 0))
assert ai._h < 0.05 and small.iconSize() == QSize(18, 18) and small.minimumSize() == QSize(0, 0), (ai._h, small.iconSize(), small.minimumSize())
ai.grab()                                                   # it paints
# a button without an icon is left alone
plain = QPushButton("plain")
v.addWidget(plain)
app.sendEvent(plain, QEvent(QEvent.Type.Enter))
assert plain.property("_ia_base") is None
print("ok")
