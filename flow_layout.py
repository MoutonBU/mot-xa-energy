"""A row of controls that wraps onto a second line instead of forcing the window wider."""
from PySide6.QtCore import Qt, QRect, QSize, QPoint
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """Like a row of buttons, but wraps onto a second line when the window is narrower
    (a long single row made the whole program open wider than the screen)."""

    def __init__(self, parent=None, hspace=8, vspace=6):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspace, vspace

    def addItem(self, item):
        self._items.append(item)

    def addStretch(self, *_a):
        pass

    def addSpacing(self, *_a):
        pass

    def addWidget(self, w, *_a):
        super().addWidget(w)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize()
        for it in self._items:
            sz = sz.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            sh = it.sizeHint()
            if x + sh.width() > r.right() + 1 and line_h > 0:
                x = r.x()
                y += line_h + self._v
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sh))
            x += sh.width() + self._h
            line_h = max(line_h, sh.height())
        return y + line_h - rect.y() + m.bottom()
