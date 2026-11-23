"""The Detail generator tab: type or dictate the detail you want, Claude draws it, you save the DXF."""
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
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
    """Request box on top, and below it the whole Detail notes workspace (same tools, catalog, templates, auto note, outputs):
    the generated detail is opened in it with Claude's notes already in the list."""

    def __init__(self, notes_win):
        super().__init__()
        self.win = notes_win
        self._job = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(18, 6, 18, 0)
        tl.setSpacing(6)
        head = QLabel("Describe the detail you need. Claude draws it below and writes its notes; then use the same tools as in Detail notes "
                      "(click a part to change its spec, the catalog, templates, auto note, outputs).")
        head.setWordWrap(True)
        tl.addWidget(head)
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText(HINT)
        self.box.setFixedHeight(84)
        tl.addWidget(self.box)
        row = FlowLayout(None, 8, 6)
        self.b_dict = QPushButton("Dictate (voice)")
        self.b_dict.setToolTip("Opens Windows voice typing. Speak, and the words appear in the box above.")
        self.b_go = QPushButton("Draw this detail")
        self.b_go.setObjectName("accent")
        self.b_sample = QPushButton("Show a sample")
        self.b_sample.setToolTip("A cavity wall on a strip footing, drawn without the internet or a key.")
        for b in (self.b_dict, self.b_go, self.b_sample):
            row.addWidget(b)
        tl.addLayout(row)
        row2 = FlowLayout(None, 8, 6)                       # the designer's own details: saved ones teach the generator their style
        self.mine = QComboBox()
        self.mine.setMinimumWidth(240)
        self.b_save = QPushButton("Save as my detail")
        self.b_save.setToolTip("Keeps this detail. When you ask for a new one, the generator is shown your saved details that are closest to the request, so new details are drawn the way you draw them.")
        self.b_save.setEnabled(False)
        self.b_open = QPushButton("Open my detail")
        self.b_del = QPushButton("Delete it")
        for w in (self.b_save, QLabel("My details"), self.mine, self.b_open, self.b_del):
            row2.addWidget(w)
        tl.addLayout(row2)
        self._last = None
        self.refresh_mine()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        tl.addWidget(self.status)
        v.addWidget(top)
        v.addWidget(notes_win, 1)
        self.b_dict.clicked.connect(self.dictate)
        self.b_go.clicked.connect(self.draw)
        self.b_sample.clicked.connect(self.sample)
        self.b_save.clicked.connect(self.save_mine)
        self.b_open.clicked.connect(self.open_mine)
        self.b_del.clicked.connect(self.delete_mine)

    # ---- my details
    def refresh_mine(self, pick=None):
        lib = gen.load_library()
        self.mine.clear()
        for d in lib:
            self.mine.addItem(d["title"])
        if pick:
            i = self.mine.findText(pick)
            if i >= 0:
                self.mine.setCurrentIndex(i)
        self.b_open.setEnabled(bool(lib))
        self.b_del.setEnabled(bool(lib))
        return lib

    def save_mine(self):
        if not self._last:
            self.say("Draw a detail first, then save it.")
            return
        req, spec = self._last
        n = gen.save_detail(req or self.box.toPlainText(), spec)
        self.refresh_mine(spec.get("title"))
        self.say("Saved \"%s\" (%d saved). The generator now draws new details with your saved ones as examples of your style." % (spec.get("title"), n))

    def open_mine(self):
        t = self.mine.currentText()
        for d in gen.load_library():
            if d["title"] == t:
                self.box.setPlainText(d.get("request", ""))
                self._drawn((gen.clean_spec(d["spec"])[0], []), d.get("request", ""))
                return

    def delete_mine(self):
        t = self.mine.currentText()
        if t and QMessageBox.question(self, "My details", "Delete \"%s\" from your saved details?" % t) == QMessageBox.StandardButton.Yes:
            gen.delete_detail(t)
            self.refresh_mine()
            self.say("Deleted.")

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
        self._job.done.connect(lambda res, t=txt: self._drawn(res, t))
        self._job.fail.connect(self._failed)
        self._job.start()

    def sample(self):
        self._drawn(gen.clean_spec(gen.SAMPLE_SPEC))

    def _failed(self, msg):
        self.b_go.setEnabled(True)
        self.say(msg)

    def _drawn(self, res, request=""):
        import re
        import time
        import json
        import mot_detail_notes_app as dn
        self.b_go.setEnabled(True)
        spec, problems = res
        self._last = (request, spec)
        self.b_save.setEnabled(True)
        slug = re.sub(r"[^A-Za-z0-9]+", "_", spec["title"]).strip("_")[:40] or "detail"
        dxf = Path(dn.OUT_DIR) / ("generated_%s_%s.dxf" % (slug, time.strftime("%H%M%S")))
        try:
            dn.OUT_DIR.mkdir(parents=True, exist_ok=True)
            specs = gen.geometry_for_notes(spec, str(dxf))
            self.win.src = dxf
            Path(self.win.edits_path()).write_text(json.dumps({"elements": [], "overrides": {}, "specs": specs}), encoding="utf-8")
            self.win.open_file(str(dxf))
        except Exception as ex:
            self.say("The drawing could not be made: %s" % ex)
            return
        msg = "%s: %d shapes, %d notes (open in the workspace below)." % (spec["title"], len(spec["shapes"]), len(specs))
        if spec["assumptions"]:
            msg += "  Assumed: " + " ".join(spec["assumptions"])
        if problems:
            msg += "  Left out: " + "; ".join(problems)
        msg += "  Check every size and note against SANS and your Engineer before issuing."
        self.say(msg)
