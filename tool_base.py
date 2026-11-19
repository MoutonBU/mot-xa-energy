"""Shared pieces for the Council pack, Area schedule and Building lines tools: the page frame (step bar, one step shown
at a time, Back / Next under the content), autosave to the user's folder, and the look of the PDF reports."""
import json
import os
import html as _html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
                               QFileDialog)

RED = "#C8102E"


def tools_dir():
    d = os.path.join(os.path.expanduser("~"), "MCP_XA_Energy", "tools")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def esc(x):
    return _html.escape(str(x if x is not None else ""))


def num(x, default=0.0):
    try:
        return float(str(x).replace(",", ".").replace(" ", "").replace("m2", "").replace("m²", "") or default)
    except Exception:
        return default


def report_doc_html(title, subtitle, body, rd=None):
    """The page head used by the three reports: red title bar, project line, then the body."""
    rd = rd or {}
    line = " | ".join(x for x in (rd.get("project"), rd.get("details")) if x)
    return ('<table width="100%%" cellspacing="0" cellpadding="0"><tr><td bgcolor="#2b2b2b" style="padding:10px;">'
            '<span style="font-size:17pt; font-weight:bold; color:#ffffff;">%s</span><br>'
            '<span style="font-size:9pt; color:#dddddd;">%s</span></td><td width="8" bgcolor="%s"></td></tr></table>'
            '<p style="font-size:9pt; color:#555555;">%s</p>%s'
            '<p style="font-size:8pt; color:#888888;">%s</p>'
            % (esc(title), esc(subtitle), RED, esc(line), body,
               esc((rd.get("company") or "MCP Architecture & Interiors") + "  |  " + (rd.get("prepared_by") or ""))))


def th(txt, w=None):
    return '<th bgcolor="#dcdcdc" style="padding:4px;"%s>%s</th>' % (' width="%s%%"' % w if w else "", esc(txt))


def td(txt, align="left", bold=False, color=None, bg=None):
    sty = "padding:3px; text-align:%s;" % align + ("font-weight:bold;" if bold else "") + ("color:%s;" % color if color else "")
    return '<td%s style="%s">%s</td>' % (' bgcolor="%s"' % bg if bg else "", sty, esc(txt))


def table(head, rows, widths=None, aligns=None):
    h = "".join(th(x, (widths or [None] * len(head))[i]) for i, x in enumerate(head))
    out = ['<table width="100%" cellspacing="0" cellpadding="0" border="0.6" style="border-color:#bbbbbb;"><tr>' + h + "</tr>"]
    for r in rows:
        bg = None
        if isinstance(r, tuple) and len(r) == 2 and isinstance(r[1], str) and r[1].startswith("#"):
            r, bg = r
        out.append("<tr>" + "".join(td(c, (aligns or ["left"] * len(r))[i], bg=bg) for i, c in enumerate(r)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def write_pdf(path, html_body, title="Report", landscape=False, resources=None):
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
    w = QPdfWriter(path)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4),
                                QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait,
                                QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
    w.setTitle(title)
    d = QTextDocument()
    from PySide6.QtCore import QUrl
    for nm, im in (resources or {}).items():
        d.addResource(QTextDocument.ResourceType.ImageResource, QUrl(nm), im)
    d.setDefaultFont(QFont("Arial", 9))
    d.setHtml('<html><body style="font-family:Arial;color:#111;">' + html_body + "</body></html>")
    return d, w


def print_doc(d, w):
    d.print_(w)


class ToolBase(QWidget):
    """A tool page with guided steps. Subclasses fill `self.make_steps()` and implement state() / set_state()."""
    KEY = "tool"
    TITLE = "Tool"
    STEP_NAMES = []
    STEP_HINTS = []

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._autosave)
        self.report_title = self.TITLE

    # ---- the frame: steps on top, content, Back / Next below ----
    def build_frame(self, pages, side=None):
        import ui_extras as ux
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)
        self.steps = ux.StepBar(self.STEP_NAMES, self.STEP_HINTS)
        outer.addWidget(self.steps.top)
        self.stack = QStackedWidget()
        for p in pages:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sc.setWidget(p)
            self.stack.addWidget(sc)
        if side is not None:
            mid = QHBoxLayout()
            mid.setSpacing(10)
            mid.addWidget(self.stack, 3)
            mid.addWidget(side, 2)
            outer.addLayout(mid, 1)
        else:
            outer.addWidget(self.stack, 1)
        outer.addWidget(self.steps.bottom)
        self.steps.changed.connect(self._step_changed)
        self.steps.go(0)

    def _step_changed(self, i):
        self.stack.setCurrentIndex(i)
        try:
            self.on_step(i)
        except Exception:
            pass

    def on_step(self, i):
        pass

    def box(self, title, sub=""):
        """A framed group with an icon in its title, like the boxes in Energy (XA)."""
        import ui_extras as ux
        b = ux.icon_group(title)
        b.setObjectName("xaGroup")
        v = QVBoxLayout(b)
        v.setContentsMargins(14, 8, 14, 12)
        v.setSpacing(8)
        if sub:
            lab = QLabel(sub)
            lab.setWordWrap(True)
            lab.setObjectName("xaSub")
            v.addWidget(lab)
        return b, v

    # ---- state, kept in the project file and in an autosave file ----
    def state(self):
        return {}

    def set_state(self, d):
        pass

    def changed(self, *_a):
        if not self._loading:
            self._timer.start()

    def _path(self):
        return os.path.join(tools_dir(), self.KEY + ".json")

    def _autosave(self):
        try:
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(self.state(), f)
        except Exception:
            pass

    def restore(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
            self._loading = True
            self.set_state(d)
        except Exception:
            pass
        finally:
            self._loading = False

    def load_state(self, d):
        self._loading = True
        try:
            self.set_state(d or {})
        finally:
            self._loading = False
        self._autosave()

    # ---- reports ----
    def report_html(self):
        return ""

    def report_resources(self):
        return {}

    def write_report(self, path):
        d, w = write_pdf(path, self.report_html(), self.TITLE, resources=self.report_resources())
        print_doc(d, w)

    def preview(self):
        try:
            self.win.preview_pdf_report(self.write_report, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, self.TITLE, "The preview could not be shown (%s). Use Export PDF." % e)

    def export(self):
        rd = getattr(self.win, "rd", {}) or {}
        base = " - ".join(x for x in ((rd.get("project") or "").strip(), self.TITLE) if x)
        start = base + ".pdf"
        try:
            start = self.win.pdf_default_path(self.TITLE)
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(self, "Export " + self.TITLE.lower(), start, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.write_report(path)
        try:
            self.win.toast_saved(path)
        except Exception:
            QMessageBox.information(self, self.TITLE, "PDF saved:\n" + path)
