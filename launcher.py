"""Start-up file of the installed program.

When a code-only update has been installed (Menu > Check for updates), the newer .py files live in
~/MCP_XA_Energy/code_update and are used in place of the ones inside the installer. They are used only while they belong to the
installed program (meta.json "base" equals the installed version) and are newer than it. If they fail to load, they are put aside
(code_update.bad) and the program starts from the installer's own files."""
import importlib.abc
import importlib.util
import json
import os
import re
import sys


def _ver(txt):
    return tuple(int(x) for x in re.findall(r"\d+", str(txt)))


def _installed():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            return _ver(f.read())
    except Exception:
        return ()


class _Overlay(importlib.abc.MetaPathFinder):
    def __init__(self, folder):
        self.folder = folder

    def find_spec(self, name, path=None, target=None):
        if "." in name:
            return None
        f = os.path.join(self.folder, name + ".py")
        if os.path.isfile(f):
            return importlib.util.spec_from_file_location(name, f)
        return None


def overlay_folder():
    return os.path.join(os.path.expanduser("~"), "MCP_XA_Energy", "code_update")


def _start_overlay():
    d = overlay_folder()
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        inst = _installed()
        if not inst or _ver(meta.get("base")) != inst or _ver(meta.get("ver")) <= inst:
            return None
        finder = _Overlay(d)
        sys.meta_path.insert(0, finder)
        os.environ["MOT_CODE_VER"] = str(meta["ver"])
        os.environ["MOT_CODE_DIR"] = d
        return finder
    except Exception:
        return None


def _drop_overlay(finder):
    d = finder.folder
    try:
        sys.meta_path.remove(finder)
    except ValueError:
        pass
    for n, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if f and os.path.abspath(f).startswith(os.path.abspath(d)):
            del sys.modules[n]
    os.environ.pop("MOT_CODE_VER", None)
    os.environ.pop("MOT_CODE_DIR", None)
    try:
        bad = d + ".bad"
        if os.path.isdir(bad):
            import shutil
            shutil.rmtree(bad, ignore_errors=True)
        os.rename(d, bad)
    except Exception:
        pass

_LOGO = "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"


def _early_splash():
    """The splash is on screen before the big program files are even read, so the start feels instant."""
    if any(a in sys.argv for a in ("--ready", "--restore", "--tray", "--plan-worker", "--selftest")):
        return None
    try:
        import base64
        from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QTimer, Qt
        from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
        from PySide6.QtWidgets import QApplication, QWidget
        try:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        except Exception:
            pass
        app = QApplication.instance() or QApplication(sys.argv)
        pm = QPixmap()
        pm.loadFromData(base64.b64decode(_LOGO))
        class _Splash(QWidget):
            """Start-up card. The logo itself is animated: it rises like a skyline, column by column (white first, then the red), settles with a
            soft bounce, then a light keeps sweeping across it while a thin red line moves underneath."""

            def __init__(self, logo):
                super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
                self.setFixedSize(440, 260)
                self.logo = None
                self.strips = []
                if logo is not None and not logo.isNull():
                    self.logo = logo.scaledToHeight(104, Qt.TransformationMode.SmoothTransformation)
                    img = self.logo.toImage().convertToFormat(QImage.Format.Format_ARGB32)
                    w, h = img.width(), img.height()
                    sw = 4
                    for x0 in range(0, w, sw):
                        red = 0
                        tot = 0
                        for yy in range(0, h, 3):
                            for xx in range(x0, min(w, x0 + sw), 2):
                                c = img.pixelColor(xx, yy)
                                if c.alpha() > 100:
                                    tot += 1
                                    if c.red() > 150 and c.green() < 110:
                                        red += 1
                        self.strips.append((x0, min(sw, w - x0), red > tot * 0.5 and tot > 0))
                self.t = QElapsedTimer()
                self.t.start()
                self.tm = QTimer(self)
                self.tm.timeout.connect(self.update)
                self.tm.start(16)

            def paintEvent(self, e):
                import math
                p = QPainter(self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                W, H = self.width(), self.height()
                ms = self.t.elapsed()
                p.fillRect(0, 0, W, H, QColor("#16171a"))
                p.setPen(QPen(QColor("#2a2c31"), 1))
                p.drawRect(0, 0, W - 1, H - 1)
                cx, cy = W / 2, H / 2 - 18
                pulse = 0.5 + 0.5 * math.sin(ms / 380.0)
                grow = min(1.0, ms / 900.0)
                g = QRadialGradient(cx, cy, 125)
                g.setColorAt(0, QColor(255, 64, 86, int((30 + 38 * pulse) * grow)))
                g.setColorAt(1, QColor(255, 64, 86, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(g)
                p.drawEllipse(QPointF(cx, cy), 125, 125)
                if self.logo is not None:
                    lw, lh = self.logo.width(), self.logo.height()
                    ox, oy = cx - lw / 2.0, cy - lh / 2.0 + 2.5 * math.sin(ms / 700.0) * min(1.0, ms / 1400.0)          # gentle float once built
                    for x0, sw, red in self.strips:
                        u = x0 / float(max(1, lw))
                        d = 60 + u * 520 + (260 if red else 0)                       # left to right; the red columns follow the white
                        k = max(0.0, min(1.0, (ms - d) / 420.0))
                        if k <= 0:
                            continue
                        ease = 1 - (1 - k) ** 3
                        bump = 1.0 + 0.07 * math.sin(k * math.pi) * (1 - k) * 3     # a little overshoot at the top as it lands
                        hh = lh * ease * min(1.0, bump)
                        p.setOpacity(min(1.0, k * 2))
                        p.drawPixmap(QRectF(ox + x0, oy + lh - hh, sw, hh), self.logo, QRectF(x0, lh - hh, sw, hh))
                    p.setOpacity(1.0)
                    if ms > 1300:                                                   # a light sweeps over the finished logo
                        ph = ((ms - 1300) % 2200) / 2200.0
                        x = ox - 40 + ph * (lw + 120)
                        sweep = QImage(lw, lh, QImage.Format.Format_ARGB32_Premultiplied)
                        sweep.fill(0)
                        q = QPainter(sweep)
                        q.drawPixmap(0, 0, self.logo)
                        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                        lg = QLinearGradient(x - ox - 26, 0, x - ox + 26, lh * 0.35)
                        lg.setColorAt(0, QColor(255, 255, 255, 0))
                        lg.setColorAt(0.5, QColor(255, 255, 255, 200))
                        lg.setColorAt(1, QColor(255, 255, 255, 0))
                        q.fillRect(0, 0, lw, lh, lg)
                        q.end()
                        p.drawImage(QPointF(ox, oy), sweep)
                else:
                    p.setPen(QColor("#eceef0"))
                    f = QFont(self.font())
                    f.setPointSize(16)
                    f.setBold(True)
                    p.setFont(f)
                    p.drawText(QRectF(0, cy - 20, W, 40), Qt.AlignmentFlag.AlignCenter, "MCP Architecture & Interiors")
                ly = H - 38
                p.setPen(QPen(QColor("#2a2c31"), 2))
                p.drawLine(70, ly, W - 70, ly)
                ph = (ms % 1300) / 1300.0
                seg = 90
                x0 = 70 + (W - 140 + seg) * ph - seg
                a0, a1 = max(70, x0), min(W - 70, x0 + seg)
                if a1 > a0:
                    lg = QLinearGradient(x0, 0, x0 + seg, 0)
                    lg.setColorAt(0, QColor(255, 64, 86, 0))
                    lg.setColorAt(0.5, QColor(255, 64, 86, 255))
                    lg.setColorAt(1, QColor(255, 64, 86, 0))
                    p.setPen(QPen(QBrush(lg), 2))
                    p.drawLine(QPointF(a0, ly), QPointF(a1, ly))
                p.end()
        w = _Splash(pm)
        scr = app.primaryScreen().availableGeometry()
        w.move(scr.center().x() - w.width() // 2, scr.center().y() - w.height() // 2)
        w.show()
        w.repaint()
        app.processEvents()
        app._splash = w
        return w
    except Exception:
        return None


def run():
    _early_splash()
    finder = _start_overlay()
    try:
        import mot_xa_energy as M
    except Exception:
        if finder is None:
            raise
        _drop_overlay(finder)
        import mot_xa_energy as M
    if len(sys.argv) >= 4 and sys.argv[1] == "--plan-worker":
        import ifc_plan
        ifc_plan.worker_main(sys.argv[2], sys.argv[3])
        sys.exit(0)
    M.main()


if __name__ == "__main__":
    run()
