"""The Detail generator tab: draw, save as my detail, open, delete."""
import os, tempfile
from PySide6.QtWidgets import QApplication, QWidget
import detail_generator as gen
import detail_generator_ui as ui

app = QApplication.instance() or QApplication([])
d = tempfile.mkdtemp()
gen.library_path = lambda: os.path.join(d, "my_details.json")


class Notes(QWidget):                                           # stands in for the Detail notes workspace
    def __init__(self):
        super().__init__()
        self.opened = []
        self.src = None
    def edits_path(self):
        return os.path.join(d, "e.json")
    def open_file(self, p):
        self.opened.append(p)


import mot_detail_notes_app as dn
dn.OUT_DIR = type(dn.OUT_DIR)(d)
nw = Notes()
pg = ui.GeneratorPage(nw)
assert not pg.b_save.isEnabled() and not pg.b_open.isEnabled()
pg.box.setPlainText("cavity wall on strip footing")
pg.sample()                                                      # a detail is drawn without a key
assert nw.opened and pg.b_save.isEnabled()
pg._last = ("cavity wall on strip footing", pg._last[1])
pg.save_mine()
assert pg.mine.count() == 1 and pg.b_open.isEnabled() and "Saved" in pg.status.text()
assert len(gen.load_library()) == 1
n0 = len(nw.opened)
pg.open_mine()
assert len(nw.opened) == n0 + 1 and pg.box.toPlainText() == "cavity wall on strip footing"
gen.delete_detail(pg.mine.currentText())
pg.refresh_mine()
assert pg.mine.count() == 0 and not pg.b_open.isEnabled()
print("ok")
