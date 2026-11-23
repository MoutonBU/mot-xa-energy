"""The Detail generator tab: type or dictate the detail you want, Claude draws it, you save the DXF."""
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

import detail_generator as gen
from flow_layout import FlowLayout

HINT = ("Say what you want, with sizes if you have them. For example:\n"
        "  Cavity wall on a 600 x 300 strip footing, 110 brick both leaves, 50 mm cavity, 170 slab on DPM and hardcore.\n"
        "  Parapet wall with concrete coping, 150 mm fall to the roof, waterproofing turned up 300 mm.")


class _Job(QThread):
    done = Signal(object)
    fail = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as ex:
            self.fail.emit(str(ex))


def start_dictation():
    """Windows' own voice typing (the Win+H panel) types into the box that has the cursor. No other system has this."""
    if not sys.platform.startswith("win"):
        return False
    import ctypes
    u = ctypes.windll.user32
    for vk, up in ((0x5B, 0), (0x48, 0), (0x48, 2), (0x5B, 2)):
        u.keybd_event(vk, 0, up, 0)
    return True


class GeneratorPage(QWidget):
    def __init__(self, notes_win=None, goto_notes=None):
        super().__init__()
        self.notes_win, self.goto_notes = notes_win, goto_notes
        self.spec = None
        self._job = None
        self._png = os.path.join(tempfile.gettempdir(), "mot_detail_generator.png")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        head = QLabel("Describe the detail you need. Claude draws it in the house style (true size, brickwork in red, "
                      "concrete in green, notes in a column) and you save it as a DXF for Archicad.")
        head.setWordWrap(True)
        v.addWidget(head)
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText(HINT)
        self.box.setMinimumHeight(96)
        self.box.setMaximumHeight(150)
        v.addWidget(self.box)
        row = FlowLayout(None, 8, 6)
        self.b_dict = QPushButton("Dictate (voice)")
        self.b_dict.setToolTip("Opens Windows voice typing. Speak, and the words appear in the box above.")
        self.b_go = QPushButton("Draw this detail")
        self.b_go.setObjectName("accent")
        self.b_sample = QPushButton("Show a sample")
        self.b_sample.setToolTip("A cavity wall on a strip footing, drawn without the internet or a key.")
        self.b_save = QPushButton("Save DXF...")
        self.b_open = QPushButton("Add notes in Detail notes")
        for b in (self.b_dict, self.b_go, self.b_sample, self.b_save, self.b_open):
            row.addWidget(b)
        v.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.pic = QLabel("The drawing shows here.")
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.pic)
        v.addWidget(sc, 1)
        self.b_dict.clicked.connect(self.dictate)
        self.b_go.clicked.connect(self.draw)
        self.b_sample.clicked.connect(self.sample)
        self.b_save.clicked.connect(self.save)
        self.b_open.clicked.connect(self.to_notes)
        self.b_save.setEnabled(False)
        self.b_open.setEnabled(False)
        self.b_open.setVisible(notes_win is not None)

    # ---- actions
    def dictate(self):
        self.box.setFocus()
        if not start_dictation():
            QMessageBox.information(self, "Dictate", "Voice typing is built into Windows (press the Windows key + H). "
                                    "On this computer, type the request instead.")

    def say(self, t):
        self.status.setText(t)

    def draw(self):
        txt = self.box.toPlainText().strip()
        if not txt:
            self.say("Type or dictate what you want drawn first.")
            return
        key = gen.api_key()
        if not key:
            QMessageBox.information(self, "Detail generator",
                                    "Drawing from words needs an Anthropic API key. Save one under Settings in the Detail "
                                    "notes tab. A Claude Pro subscription does not give the program a key; the key comes "
                                    "from console.anthropic.com and is billed by use (a detail costs a few cents).\n\n"
                                    "'Show a sample' works without it.")
            return
        model = gen.api_model()
        self.b_go.setEnabled(False)
        self.say("Drawing...")
        self._job = _Job(lambda: gen.generate(txt, key, model))
        self._job.done.connect(self._drawn)
        self._job.fail.connect(self._failed)
        self._job.start()

    def sample(self):
        self._drawn(gen.clean_spec(gen.SAMPLE_SPEC))

    def _failed(self, msg):
        self.b_go.setEnabled(True)
        self.say(msg)

    def _drawn(self, res):
        self.b_go.setEnabled(True)
        spec, problems = res
        try:
            n = gen.make_detail(spec, os.path.join(tempfile.gettempdir(), "mot_detail_generator.dxf"), self._png)
        except Exception as ex:
            self.say("The drawing could not be made: %s" % ex)
            return
        self.spec = spec
        pm = QPixmap(self._png)
        self.pic.setPixmap(pm.scaledToWidth(min(pm.width(), 1100), Qt.TransformationMode.SmoothTransformation))
        msg = "%s: %d shapes, %d notes." % (spec["title"], len(spec["shapes"]), n)
        if spec["assumptions"]:
            msg += "  Assumed: " + " ".join(spec["assumptions"])
        if problems:
            msg += "  Left out: " + "; ".join(problems)
        msg += "  Check every size and note against SANS and your Engineer before issuing."
        self.say(msg)
        self.b_save.setEnabled(True)
        self.b_open.setEnabled(True)

    def _write(self, path):
        gen.make_detail(self.spec, path)

    def save(self):
        if not self.spec:
            return
        name = "".join(c if c.isalnum() or c in " -_" else "" for c in self.spec["title"]).strip() or "Detail"
        p, _ = QFileDialog.getSaveFileName(self, "Save detail", str(Path.home() / (name + ".dxf")), "DXF drawing (*.dxf)")
        if p:
            try:
                self._write(p)
                self.say("Saved: " + p)
            except Exception as ex:
                self.say("Could not save: %s" % ex)

    def to_notes(self):
        if not (self.spec and self.notes_win):
            return
        p = os.path.join(tempfile.gettempdir(), "mot_detail_generated.dxf")
        try:
            self._write(p)
            self.notes_win.open_file(p)
            if self.goto_notes:
                self.goto_notes()
        except Exception as ex:
            self.say("Could not open it in Detail notes: %s" % ex)
