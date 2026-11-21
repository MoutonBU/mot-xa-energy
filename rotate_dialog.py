"""A small turn-it dialog with a slider, fine steps and live preview. The caller gives the angle now and a function that applies an angle;
Cancel puts the original angle back."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout


class RotateDialog(QDialog):
    def __init__(self, parent, title, angle, apply_fn, note="Positive turns anticlockwise."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.start, self.fn = float(angle), apply_fn
        v = QVBoxLayout(self)
        v.addWidget(QLabel(note))
        self.sl = QSlider(Qt.Orientation.Horizontal)
        self.sl.setRange(-1800, 1800)
        self.sp = QDoubleSpinBox()
        self.sp.setRange(-3600, 3600)
        self.sp.setDecimals(2)
        self.sp.setSingleStep(0.5)
        self.sp.setSuffix(" °")
        row = QHBoxLayout()
        row.addWidget(self.sl, 1)
        row.addWidget(self.sp)
        v.addLayout(row)
        row = QHBoxLayout()
        for txt, d in (("-90°", -90), ("-15°", -15), ("-1°", -1), ("-0.1°", -0.1), ("+0.1°", 0.1), ("+1°", 1), ("+15°", 15), ("+90°", 90)):
            b = QPushButton(txt)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, d_=d: self.sp.setValue(self.sp.value() + d_))
            row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        rb = QPushButton("Back to start")
        rb.setAutoDefault(False)
        rb.clicked.connect(lambda: self.sp.setValue(self.start))
        ok, no = QPushButton("OK"), QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        no.clicked.connect(self.reject)
        for b in (rb, ok, no):
            row.addWidget(b)
        v.addLayout(row)
        self.sp.setValue(self.start)
        self.sl.setValue(int(round(((self.start + 180) % 360 - 180) * 10)))
        self.sp.valueChanged.connect(self._sp)
        self.sl.valueChanged.connect(self._sl)

    def _sp(self, val):
        self.sl.blockSignals(True)
        self.sl.setValue(int(round(((val + 180) % 360 - 180) * 10)))
        self.sl.blockSignals(False)
        self.fn(val)

    def _sl(self, v):
        self.sp.setValue(v / 10.0)

    def reject(self):
        self.fn(self.start)
        super().reject()
