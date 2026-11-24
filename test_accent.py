"""Each tool's colour runs through the whole tool: the style sheet's reds become the tool's colour, and go back on the start screen."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
import mot_xa_energy as M
import ui_extras as ux
app = QApplication.instance() or QApplication([])
base = M._final_qss()
assert "#d8132b" in base
M.ACCENT_COL[0] = "#8b5cf6"
q = M._final_qss()
assert "#d8132b" not in q and "#8b5cf6" in q.lower(), "costing is not purple"
assert M.accent_qss(base, "#d8132b") == base and M.accent_qss(base, None) == base
M.ACCENT_COL[0] = None
assert M._final_qss() == base
import app_shell as sh
sh.ACC[0] = "#8b5cf6"
assert sh._palette(False)["hot"] != sh._palette0(False)["hot"] and sh._palette(True)["accent"] != sh._palette0(True)["accent"]
sh.ACC[0] = None
assert sh._palette(False) == sh._palette0(False)
print("ok")
