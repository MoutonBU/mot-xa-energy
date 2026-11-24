"""Every button in the program gets a soft glow that rises when the mouse comes over it, sinks when it is pressed and flashes when it is clicked.

One filter on the whole application does it, so every window and every new button has it without any code of its own."""
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton, QToolButton

GLOW = (216, 19, 43)                     # the program's red


class _Fx:
    """The glow of one button: level 0 = none, 1 = mouse over, below 1 = pressed in, above 1 = the flash of a click."""

    def __init__(self, btn):
        self.btn = btn
        self.col = GLOW
        try:
            c_ = QColor(btn.property("glow") or "")            # a button can carry its own glow colour (the start tiles take their tool's colour)
            if c_.isValid():
                self.col = (c_.red(), c_.green(), c_.blue())
        except Exception:
            pass
        self.level = 0.0
        self.eff = QGraphicsDropShadowEffect(btn)
        self.eff.setColor(QColor(*self.col, 0))
        self.eff.setBlurRadius(0)
        self.eff.setOffset(QPointF(0, 0))
        btn.setGraphicsEffect(self.eff)
        self.anim = QVariantAnimation(self.eff)
        self.anim.valueChanged.connect(self._apply)
        self.anim.finished.connect(self._done)

    def _apply(self, v):
        try:
            v = float(v)
            self.level = v
            self.eff.setBlurRadius(max(0.0, 24.0 * v))
            self.eff.setOffset(QPointF(0, max(0.0, 3.5 * v)))
            self.eff.setColor(QColor(self.col[0], self.col[1], self.col[2], int(max(0, min(255, 140 * v)))))
        except RuntimeError:
            pass

    def go(self, to, ms, curve):
        self.anim.stop()
        self.anim.setStartValue(self.level)
        self.anim.setEndValue(float(to))
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(curve)
        self.anim.start()

    def _done(self):
        try:
            if self.level < 0.02 and getattr(self.btn, "_fx", None) is self:
                self.btn._fx = None
                self.btn.setGraphicsEffect(None)                 # nothing is drawn while the mouse is away, so the program stays light
        except RuntimeError:
            pass


class ButtonFx(QObject):
    WATCH = (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in self.WATCH or not isinstance(obj, (QPushButton, QToolButton)):
            return False
        try:
            fx = getattr(obj, "_fx", None)
            if t == QEvent.Type.Enter:
                if not obj.isEnabled() or (obj.graphicsEffect() is not None and fx is None):
                    return False                                  # a button that already has its own effect keeps it
                if fx is None:
                    fx = obj._fx = _Fx(obj)
                fx.go(1.0, 180, QEasingCurve(QEasingCurve.Type.OutCubic))
            elif fx is None:
                return False
            elif t == QEvent.Type.Leave:
                fx.go(0.0, 260, QEasingCurve(QEasingCurve.Type.InOutQuad))
            elif t == QEvent.Type.MouseButtonPress:
                fx.go(0.3, 90, QEasingCurve(QEasingCurve.Type.OutQuad))                    # pressed in
            elif t == QEvent.Type.MouseButtonRelease:
                fx.anim.stop()
                fx.go(1.0, 380, QEasingCurve(QEasingCurve.Type.OutBack))                    # springs back with a flash
        except RuntimeError:
            pass
        return False


def install(app):
    f = ButtonFx(app)
    app.installEventFilter(f)
    app._button_fx = f
    return f
