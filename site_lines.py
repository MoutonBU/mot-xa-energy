"""Building lines: draw the stand, set the building lines on each boundary, place the buildings, and see at once what
encroaches. Works out coverage and floor area ratio, and writes a departure motivation to adapt."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF, QImage
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QMenu, QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QListWidget, QSlider, QProgressDialog, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import os

import tool_base as tb
import site_import as si
from flow_layout import FlowLayout
from tool_base import ToolBase

KINDS = ["Street", "Side", "Rear", "Other"]
REASONS = [
    ("nb_light", "It does not take light, ventilation or privacy from the neighbours."),
    ("char", "It fits the character of the street, and similar departures exist nearby."),
    ("shape", "The shape or slope of the stand limits where a building can go."),
    ("serv", "A servitude, tree or service limits where the building can go."),
    ("consent", "The neighbours have given written consent."),
    ("traffic", "It does not affect traffic safety or sight lines."),
    ("min", "It is the smallest departure that makes the building workable."),
]
EPS = 0.005


def corner_name(i):
    return chr(65 + i % 26) + (str(i // 26) if i >= 26 else "")


# ---------------------------------------------------------------- geometry
def signed_area(v):
    return 0.5 * sum(v[i][0] * v[(i + 1) % len(v)][1] - v[(i + 1) % len(v)][0] * v[i][1] for i in range(len(v)))


def edge_dist(v, i, p, sign):
    """How far point p is inside boundary i (negative: outside the stand)."""
    a, b = v[i], v[(i + 1) % len(v)]
    ex, ey = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(ex, ey) or 1.0
    return sign * (ex * (p[1] - a[1]) - ey * (p[0] - a[0])) / ln


def envelope(v, sbs):
    """The area inside every building line (clip the stand by a line parallel to each boundary)."""
    if len(v) < 3:
        return []
    sign = 1.0 if signed_area(v) >= 0 else -1.0
    poly = [tuple(p) for p in v]
    for i, sb in enumerate(sbs):
        if sb <= 0 or not poly:
            continue
        out = []
        f = lambda p: edge_dist(v, i, p, sign) - sb
        for k in range(len(poly)):
            p, q = poly[k], poly[(k + 1) % len(poly)]
            fp, fq = f(p), f(q)
            if fp >= 0:
                out.append(p)
            if (fp >= 0) != (fq >= 0):
                t = fp / (fp - fq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        poly = out
    return poly


def is_convex(v):
    if len(v) < 4:
        return True
    s = 0
    for i in range(len(v)):
        a, b, c = v[i], v[(i + 1) % len(v)], v[(i + 2) % len(v)]
        z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(z) > 1e-9:
            if s and (z > 0) != (s > 0):
                return False
            s = z
    return True




def bpoly(b):
    """A building as a list of corners: its traced outline, or its rectangle."""
    if b.get("poly"):
        return [tuple(p) for p in b["poly"]]
    x, y, w, d = b["x"], b["y"], b["w"], b["d"]
    return [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]


def analyse(v, edges, buildings, max_cov, max_far, floor_area):
    """Per building: how far it goes into each building line. Plus coverage and floor area ratio."""
    n = len(v)
    out = {"area": abs(signed_area(v)) if n >= 3 else 0.0, "buildings": []}
    sign = 1.0 if n >= 3 and signed_area(v) >= 0 else -1.0
    cov = 0.0
    for b in buildings:
        corners = bpoly(b)
        enc = []
        for i in range(n):
            sb = max(0.0, edges[i]["sb"]) if i < len(edges) else 0.0
            worst = max(sb - edge_dist(v, i, p, sign) for p in corners)
            if worst > EPS:
                dist = sb - worst
                enc.append({"edge": i, "kind": edges[i]["kind"] if i < len(edges) else "Other", "sb": sb, "by": worst, "dist": dist})
        area = abs(signed_area(corners))
        out["buildings"].append({"name": b["name"], "enc": enc, "area": area})
        if b.get("cov", True):
            cov += area
    out["cov_area"] = cov
    out["cov_pct"] = 100.0 * cov / out["area"] if out["area"] else 0.0
    out["cov_ok"] = (not max_cov) or out["cov_pct"] <= max_cov + 1e-6
    out["far"] = floor_area / out["area"] if out["area"] else 0.0
    out["far_ok"] = (not max_far) or out["far"] <= max_far + 1e-6
    return out


class PlanView(QWidget):
    """The stand, its building lines and the buildings, drawn on a sheet over the survey drawing. Mouse wheel zooms, a drag on
    empty space (or the middle button) pans, a drag on a building moves it. Tools: trace the stand or a building, calibrate."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drag = None
        self.sel = -1
        self.auto = True
        self.view = (1.0, 0.0, 0.0)             # scale (px per m), world point at the centre
        self._v = None
        self.mode = "select"
        self.role = None
        self.tpts = []
        self.cal = []
        self.hover = None
        self.snap_pt = None
        self.highlight = None
        self.pan = None

    # ---- the view
    def bounds(self, W=None, include_under=False):
        pg = self.page
        v = pg.verts()
        pts = list(v)
        for b in pg.buildings():
            pts += bpoly(b)
        if include_under or not pts:
            for u in pg.under.values():
                if u is not None:
                    x0, y0, x1, y1 = u.world_bounds()
                    pts += [(x0, y0), (x1, y1)]
        if not pts:
            return 0, 0, 10, 10
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def fit_view(self, W, H, include_under=False):
        x0, y0, x1, y1 = self.bounds(include_under=include_under)
        pad = 46
        s = min((W - 2 * pad) / max(x1 - x0, 1e-6), (H - 2 * pad) / max(y1 - y0, 1e-6))
        return (s, (x0 + x1) / 2, (y0 + y1) / 2)

    def current_view(self, W, H):
        if self.auto:
            self.view = self.fit_view(W, H, include_under=self.mode != "select" or not self.page.verts())
        return self.view

    def fit(self):
        self.auto = True
        self.update()

    def zoom(self, f, at=None):
        if self._v is None:
            return
        s, cx, cy, W, H = self._v
        self.auto = False
        if at is None:
            at = (W / 2, H / 2)
        wx, wy = cx + (at[0] - W / 2) / s, cy - (at[1] - H / 2) / s
        s2 = min(max(s * f, 0.02), 5000)
        self.view = (s2, wx - (at[0] - W / 2) / s2, wy + (at[1] - H / 2) / s2)
        self.update()

    def _sc(self, p, v, W, H):
        s, cx, cy = v
        return QPointF(W / 2 + (p[0] - cx) * s, H / 2 - (p[1] - cy) * s)

    def _world(self, pt):
        if not self._v:
            return None
        s, cx, cy, W, H = self._v
        return (cx + (pt.x() - W / 2) / s, cy - (pt.y() - H / 2) / s)

    # ---- drawing
    def draw(self, p, W, H, v=None, snapshot=False):
        from PySide6.QtGui import QTransform
        pg = self.page
        verts, edges, blds = pg.verts(), pg.edges(), pg.buildings()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(0, 0, W, H, QColor("#fbfbf8"))
        v = v or self.current_view(W, H)
        s = v[0]
        if not snapshot:
            self._v = (v[0], v[1], v[2], W, H)
        to = lambda q: self._sc(q, v, W, H)
        # the drawings under the plan
        have_under = False
        for role in ("site", "fp"):
            u = pg.under.get(role)
            if u is None:
                continue
            have_under = True
            p.save()
            p.setOpacity(u.opacity)
            from PySide6.QtGui import QTransform as _QT
            scr = _QT(s, 0, 0, -s, W / 2 - v[1] * s, H / 2 + v[2] * s)
            if u.image is not None:
                p.setTransform(_QT(1, 0, 0, -1, 0, u.raw_h) * u.qt() * scr)
                p.drawImage(QRectF(0, 0, u.raw_w, u.raw_h), u.image)
            else:
                p.setTransform(u.qt() * scr)
                p.setPen(QPen(QColor("#7d7d7d") if role == "site" else QColor("#3a7bd5"), 0))
                p.drawPath(u.path())
            p.restore()
        if len(verts) < 3:
            if not have_under:
                p.setPen(QColor("#777777"))
                p.drawText(QRectF(0, 0, W, H), int(Qt.AlignmentFlag.AlignCenter),
                           "Enter the corners of the stand,\npress Make a rectangle,\nor load the survey drawing.")
            self._v_done(p, W, H, to, s)
            return
        sbs = [e["sb"] for e in edges]
        stand = QPolygonF([to(q) for q in verts])
        p.setPen(QPen(QColor("#222222"), 2))
        p.setBrush(QColor(239, 237, 226, 70 if have_under else 255))
        p.drawPolygon(stand)
        env = envelope(verts, sbs)
        if len(env) >= 3:
            p.setBrush(QColor(46, 158, 91, 38))
            p.setPen(QPen(QColor("#C8102E"), 1.6, Qt.PenStyle.DashLine))
            p.drawPolygon(QPolygonF([to(q) for q in env]))
        an = analyse(verts, edges, blds, 0, 0, 0)
        big = W >= 900
        for i, b in enumerate(blds):
            bad = bool(an["buildings"][i]["enc"])
            pl = QPolygonF([to(q) for q in bpoly(b)])
            p.setBrush(QColor(200, 16, 46, 120) if bad else QColor(60, 120, 200, 110))
            p.setPen(QPen(QColor("#C8102E") if bad else QColor("#2a5fa8"), 3 if i == self.sel else 1.6))
            p.drawPolygon(pl)
            f = QFont("Arial")
            f.setPixelSize(19 if big else 12)
            p.setFont(f)
            p.setPen(QColor("#111111"))
            c = pl.boundingRect().center()
            p.drawText(QRectF(c.x() - 80, c.y() - 12, 160, 24), int(Qt.AlignmentFlag.AlignCenter), b["name"])
        if 0 <= self.sel < len(blds):
            self._dims(p, to, verts, bpoly(blds[self.sel]), big)
        f = QFont("Arial")
        f.setPixelSize(17 if big else 11)
        p.setFont(f)
        cen = QPointF(sum(to(q).x() for q in verts) / len(verts), sum(to(q).y() for q in verts) / len(verts))
        for i in range(len(verts)):
            a, b = to(verts[i]), to(verts[(i + 1) % len(verts)])
            m = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            dx, dy = m.x() - cen.x(), m.y() - cen.y()
            ln = math.hypot(dx, dy) or 1
            tp = QPointF(m.x() + dx / ln * 40, m.y() + dy / ln * 26)
            p.setPen(QColor("#333333"))
            k = edges[i]["kind"] if i < len(edges) else ""
            txt = ("%s %s" % (k, ("%.1f m" % edges[i]["sb"]) if i < len(edges) and edges[i]["sb"] else "")).strip()
            nm = edges[i].get("name", "") if i < len(edges) else ""
            if nm:
                f2 = QFont(f)
                f2.setBold(True)
                p.setFont(f2)
                p.drawText(QRectF(tp.x() - 110, tp.y() - 24, 220, 18), int(Qt.AlignmentFlag.AlignCenter), nm)
                p.setFont(f)
            p.drawText(QRectF(tp.x() - 80, tp.y() - 6, 160, 20), int(Qt.AlignmentFlag.AlignCenter), txt)
            p.setPen(QPen(QColor("#222222"), 1))
            p.setBrush(QColor("#ffffff"))
            r_ = 12 if big else 8
            p.drawEllipse(a, r_, r_)
            p.drawText(QRectF(a.x() - r_, a.y() - r_, 2 * r_, 2 * r_), int(Qt.AlignmentFlag.AlignCenter), corner_name(i))
        self._v_done(p, W, H, to, s, big)

    def _dims(self, p, to, verts, pts, big):
        """Dimension lines from the selected building to each boundary, so you can see the distances as you place it."""
        sg = 1.0 if signed_area(verts) >= 0 else -1.0
        f = QFont("Arial")
        f.setPixelSize(15 if big else 10)
        f.setBold(True)
        p.setFont(f)
        for i in range(len(verts)):
            a, b = verts[i], verts[(i + 1) % len(verts)]
            ex, ey = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(ex, ey)
            if ln < 1e-9:
                continue
            nx, ny = -ey / ln * sg, ex / ln * sg
            q = min(pts, key=lambda r: nx * (r[0] - a[0]) + ny * (r[1] - a[1]))
            d = nx * (q[0] - a[0]) + ny * (q[1] - a[1])
            foot = (q[0] - nx * d, q[1] - ny * d)
            t_ = ((foot[0] - a[0]) * ex + (foot[1] - a[1]) * ey) / (ln * ln)
            if not (0 <= t_ <= 1):
                continue
            p.setPen(QPen(QColor("#d6209a"), 1.4, Qt.PenStyle.DashLine))
            qa, qb = to(q), to(foot)
            p.drawLine(qa, qb)
            p.setPen(QColor("#d6209a"))
            p.drawText(QRectF((qa.x() + qb.x()) / 2 - 40, (qa.y() + qb.y()) / 2 - 20, 80, 18), int(Qt.AlignmentFlag.AlignCenter), "%.2f m" % d)

    def _draw_north(self, p, W, big):
        R = 34 if big else 24
        cx, cy = W - R - 22, R + 26
        self._north_c = (cx, cy, R)
        th = math.radians(self.page.north)
        d = (math.cos(th), -math.sin(th))          # on screen
        nrm = (-d[1], d[0])
        P = lambda a, b: QPointF(cx + d[0] * a + nrm[0] * b, cy + d[1] * a + nrm[1] * b)
        p.save()
        p.setPen(QPen(QColor("#222222"), 1.4))
        p.setBrush(QColor(255, 255, 255, 215))
        p.drawEllipse(QPointF(cx, cy), R, R)
        tip, tail = P(R * 0.92, 0), P(-R * 0.62, 0)
        l_, r_ = P(-R * 0.62, R * 0.42), P(-R * 0.62, -R * 0.42)
        mid = P(-R * 0.18, 0)
        p.setBrush(QColor("#111111"))
        p.drawPolygon(QPolygonF([tip, mid, l_]))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([tip, r_, mid]))
        p.setBrush(QColor("#111111"))
        p.drawPolygon(QPolygonF([mid, r_, tail]))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([mid, tail, l_]))
        f = QFont("Arial")
        f.setPixelSize(int(R * 0.62))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#111111"))
        q = P(R + R * 0.42, 0)
        p.drawText(QRectF(q.x() - R * 0.4, q.y() - R * 0.4, R * 0.8, R * 0.8), int(Qt.AlignmentFlag.AlignCenter), "N")
        p.restore()

    def _hit_north(self, pos):
        c = getattr(self, "_north_c", None)
        return bool(c and getattr(self.page, "north_on", True) and math.hypot(pos.x() - c[0], pos.y() - c[1]) <= c[2] * 1.5)

    def _v_done(self, p, W, H, to, s, big=False):
        if self.highlight:
            p.setPen(QPen(QColor("#d6209a"), 3))
            p.setBrush(QColor(214, 32, 154, 60))
            p.drawPolygon(QPolygonF([to(q) for q in self.highlight]))
        # tracing in progress
        pts = self.tpts if self.mode.startswith("trace") else self.cal
        if pts:
            p.setPen(QPen(QColor("#d6209a"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            qs = [to(q) for q in pts]
            for a, b in zip(qs, qs[1:]):
                p.drawLine(a, b)
            if self.hover is not None:
                p.setPen(QPen(QColor("#d6209a"), 1, Qt.PenStyle.DashLine))
                p.drawLine(qs[-1], to(self.hover))
            p.setBrush(QColor("#ffffff"))
            for q in qs:
                p.drawEllipse(q, 4, 4)
        if self.snap_pt is not None:
            p.setPen(QPen(QColor("#d6209a"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            q = to(self.snap_pt)
            p.drawRect(QRectF(q.x() - 6, q.y() - 6, 12, 12))
        if getattr(self.page, "north_on", True):
            self._draw_north(p, W, big)
        # scale bar
        length = 10 if s * 10 < W * 0.45 else 5
        if s * 10 < 40:
            length = 50 if s * 50 < W * 0.45 else 20
        x0, y0 = 14, H - 16
        p.setPen(QPen(QColor("#222222"), 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + s * length, y0))
        p.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        p.drawLine(QPointF(x0 + s * length, y0 - 4), QPointF(x0 + s * length, y0 + 4))
        f = QFont("Arial")
        f.setPixelSize(17 if big else 11)
        p.setFont(f)
        p.setPen(QColor("#222222"))
        p.drawText(QPointF(x0 + s * length + 6, y0 + 5), "%d m" % length)

    def paintEvent(self, _e):
        p = QPainter(self)
        self.draw(p, self.width(), self.height())
        p.end()

    def snapshot(self, W=1000, H=720):
        img = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(img)
        old = self.highlight
        self.highlight = None
        self.draw(p, W, H, v=self.fit_view(W, H), snapshot=True)
        self.highlight = old
        p.setPen(QPen(QColor("#999999"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, W - 1, H - 1)
        p.end()
        return img

    # ---- tools
    def begin(self, mode, role=None):
        self.mode, self.role = mode, role
        self.tpts, self.cal, self.snap_pt, self.hover = [], [], None, None
        self.drag = None
        self.setCursor(Qt.CursorShape.CrossCursor if mode in ("trace_stand", "trace_building", "calibrate") else
                       Qt.CursorShape.SizeAllCursor if mode == "move_under" else Qt.CursorShape.ArrowCursor)
        self.setFocus()
        self.update()

    def end(self):
        self.begin("select")
        self.page.set_hint("")

    def _snap(self, w, px=11):
        """Snap to a corner of the drawing, of the stand or of a point already placed."""
        if self._v is None:
            return w, None
        s = self._v[0]
        best, bd = None, px / s
        try:
            import numpy as np
            for u in self.page.under.values():
                if u is None:
                    continue
                pts = u.snap_points()
                if pts is not None and len(pts):
                    d = np.hypot(pts[:, 0] - w[0], pts[:, 1] - w[1])
                    i = int(d.argmin())
                    if d[i] < bd:
                        best, bd = (float(pts[i][0]), float(pts[i][1])), float(d[i])
        except Exception:
            pass
        for q in list(self.page.verts()) + self.tpts + self.cal:
            d = math.hypot(q[0] - w[0], q[1] - w[1])
            if d < bd:
                best, bd = q, d
        return (best, best) if best else (w, None)

    def _constrain(self, w, ref, ortho):
        if ortho and ref is not None:
            if abs(w[0] - ref[0]) >= abs(w[1] - ref[1]):
                return (w[0], ref[1])
            return (ref[0], w[1])
        return w

    def _finish_trace(self):
        pts = list(self.tpts)
        if len(pts) < 3:
            self.page.set_hint("A shape needs at least three corners.")
            return
        mode, role = self.mode, self.role
        self.end()
        self.page.trace_done(mode, role, pts)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.end()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.mode.startswith("trace"):
            self._finish_trace()
        elif k == Qt.Key.Key_Backspace and self.tpts:
            self.tpts.pop()
            self.update()
        else:
            super().keyPressEvent(e)

    # ---- mouse
    def wheelEvent(self, e):
        self.zoom(1.18 if e.angleDelta().y() > 0 else 1 / 1.18, (e.position().x(), e.position().y()))

    def mousePressEvent(self, e):
        self.setFocus()
        w = self._world(e.position())
        if w is None:
            return
        if e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.rclick = e.position() if e.button() == Qt.MouseButton.RightButton else None
            self.pan = (e.position(), self.view)
            self.auto = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == "select" and self._hit_north(e.position()):
            self.drag = ("north",)
            self.page.set_hint("Drag round to point north. Hold Shift to step in 15 degrees. Right-click the arrow for more.")
            return
        ortho = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.mode in ("trace_stand", "trace_building"):
            ref = self.tpts[-1] if self.tpts else None
            q, sn = self._snap(w)
            if sn is None:
                q = self._constrain(w, ref, ortho)
            if len(self.tpts) >= 3 and math.hypot(q[0] - self.tpts[0][0], q[1] - self.tpts[0][1]) < 11 / self._v[0]:
                self._finish_trace()
                return
            self.tpts.append(q)
            self.page.set_hint("%d corners. Double-click or press Enter to finish, Backspace removes the last, Esc cancels." % len(self.tpts))
            self.update()
            return
        if self.mode == "calibrate":
            q, _sn = self._snap(w)
            self.cal.append(q)
            if len(self.cal) == 2:
                a, b, role = self.cal[0], self.cal[1], self.role
                self.end()
                self.page.calibrate_done(role, a, b)
            else:
                self.page.set_hint("Now click the second point.")
            self.update()
            return
        if self.mode == "move_under":
            self.drag = ("under", w)
            return
        blds = self.page.buildings()
        for i in range(len(blds) - 1, -1, -1):
            b = blds[i]
            from site_import import point_in_poly
            if point_in_poly(w, bpoly(b)):
                self.sel = i
                self.drag = ("b", i, w[0] - b["x"], w[1] - b["y"])
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.page.select_building(i)
                self.update()
                return
        self.sel = -1
        self.pan = (e.position(), self.view)
        self.auto = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.mode.startswith("trace") and e.button() == Qt.MouseButton.LeftButton:
            self._finish_trace()

    def mouseMoveEvent(self, e):
        w = self._world(e.position())
        if w is None:
            return
        if self.drag and self.drag[0] == "north":
            c = self._north_c
            ang = math.degrees(math.atan2(-(e.position().y() - c[1]), e.position().x() - c[0]))
            ang = round(ang / 15.0) * 15.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else round(ang)
            self.page.north = ang % 360
            self.update()
            return
        if self.pan is not None:
            p0, v0 = self.pan
            s = v0[0]
            self.view = (s, v0[1] - (e.position().x() - p0.x()) / s, v0[2] + (e.position().y() - p0.y()) / s)
            self.update()
            return
        if self.drag and self.drag[0] == "b":
            _, i, dx, dy = self.drag
            self.page.move_building(i, round((w[0] - dx) * 20) / 20, round((w[1] - dy) * 20) / 20)
            return
        if self.drag and self.drag[0] == "under":
            u = self.page.under.get(self.role)
            if u is not None:
                u.ox += w[0] - self.drag[1][0]
                u.oy += w[1] - self.drag[1][1]
                self.drag = ("under", self._world(e.position()))
                self.page.changed()
                self.update()
            return
        if self.mode in ("trace_stand", "trace_building", "calibrate"):
            q, sn = self._snap(w)
            ref = (self.tpts or self.cal or [None])[-1]
            if sn is None:
                q = self._constrain(w, ref, bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            self.hover, self.snap_pt = q, sn
            self.update()
            return
        from site_import import point_in_poly
        over = any(point_in_poly(w, bpoly(b)) for b in self.page.buildings()) or self._hit_north(e.position())
        self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        was_north = bool(self.drag and self.drag[0] == "north")
        right = e.button() == Qt.MouseButton.RightButton and getattr(self, "rclick", None) is not None
        click = right and math.hypot(e.position().x() - self.rclick.x(), e.position().y() - self.rclick.y()) < 5
        self.drag = None
        self.pan = None
        self.rclick = None
        self.setCursor(Qt.CursorShape.CrossCursor if self.mode in ("trace_stand", "trace_building", "calibrate") else
                       Qt.CursorShape.SizeAllCursor if self.mode == "move_under" else Qt.CursorShape.ArrowCursor)
        if was_north:
            self.page.changed()
        if click and self.mode == "select":
            self._context(e.globalPosition().toPoint(), e.position())

    def _edge_hit(self, pos):
        v = self.page.verts()
        if len(v) < 3 or not self._v:
            return -1
        s, cx, cy, W, H = self._v
        for i in range(len(v)):
            a, b = self._sc(v[i], (s, cx, cy), W, H), self._sc(v[(i + 1) % len(v)], (s, cx, cy), W, H)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            L2 = dx * dx + dy * dy or 1.0
            t_ = max(0.0, min(1.0, ((pos.x() - a.x()) * dx + (pos.y() - a.y()) * dy) / L2))
            if math.hypot(pos.x() - (a.x() + t_ * dx), pos.y() - (a.y() + t_ * dy)) < 10:
                return i
        return -1

    def _context(self, gpos, pos):
        from site_import import point_in_poly
        w = self._world(pos)
        menu = QMenu(self)
        if self._hit_north(pos):
            self.page.north_menu(menu)
        else:
            hit = -1
            if w is not None:
                for i, b in enumerate(self.page.buildings()):
                    if point_in_poly(w, bpoly(b)):
                        hit = i
            eh = self._edge_hit(pos) if hit < 0 else -1
            if eh >= 0:
                self.page.edge_menu(menu, eh)
            elif hit >= 0:
                self.sel = hit
                self.page.select_building(hit)
                self.update()
                self.page.building_menu(menu)
            else:
                self.page.plan_menu(menu)
        menu.exec(gpos)

class PickDialog(QDialog):
    """A list of the closed outlines found in a drawing. The one you select is shown in pink on the plan."""

    def __init__(self, page, cands, target):
        super().__init__(page)
        self.chosen = None
        self.cands = cands
        self.setWindowTitle("Pick the stand" if target == "stand" else "Pick a building")
        self.resize(460, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Click an outline to see it on the plan. The biggest are first.%s" %
                           ("\nThe stand is usually the one with the area written on the survey." if target == "stand" else "")))
        self.lst = QListWidget()
        for i, (a, pts) in enumerate(cands):
            self.lst.addItem("Outline %d  -  %.1f m2  -  %d corners" % (i + 1, a, len(pts)))
        self.lst.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.lst, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def accept(self):
        r = self.lst.currentRow()
        if r >= 0:
            self.chosen = self.cands[r][1]
        super().accept()


def spin(lo, hi, val, dec=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class SitePage(ToolBase):
    KEY = "site"
    TITLE = "Building lines"
    STEP_NAMES = ["The stand", "The buildings", "The result", "Area schedule"]
    STEP_HINTS = ["Describe the stand: its corners in metres and the building line on each boundary. A plain rectangle takes two numbers.",
                  "Place each building by its corner position and size, or drag it in the plan. Red means it goes over a building line.",
                  "What complies, what encroaches and by how much, coverage and floor area ratio, and a departure motivation to adapt.",
                  "Every room by block, level and unit, the totals and unit mix, and the floor area that counts toward the floor area ratio."]

    def __init__(self, win):
        super().__init__(win)
        self._busy = False
        self.north, self.north_on = 90.0, True
        self.under = {"site": None, "fp": None}
        self._under_note = {}
        self._grp_n = 0
        self.plan = PlanView(self)
        # ---- step 1
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Survey drawing", "Load your surveyed site (DWG, DXF or PDF) under the plan, then pick the stand from it or trace it by clicking the corners.")
        self.survey_lbl = QLabel("No drawing loaded.")
        self.survey_lbl.setObjectName("xaSub")
        self.survey_lbl.setWordWrap(True)
        bv.addWidget(self.survey_lbl)
        bv.addWidget(self._tool_row("site", [
            ("Load the survey (DWG, DXF, PDF)...", lambda: self.load_drawing("site"), "A surveyed site plan. A PDF asks for its scale."),
            ("Pick the stand from the drawing...", lambda: self.pick_shape("site", "stand"), "Lists the closed outlines in the drawing; choose the boundary of the stand."),
            ("Trace the stand by clicking", lambda: self.start_trace("trace_stand", "site"), "Click each corner of the stand on the drawing."),
            ("Set the scale or units...", lambda: self.set_scale("site"), ""),
            ("Calibrate with two points", lambda: self.start_calibrate("site"), "Click two points on the drawing, then type the real distance."),
            ("Move the drawing", lambda: self.start_move("site"), "Drag the drawing under the plan."),
            ("Remove the drawing", lambda: self.remove_drawing("site"), "")]))
        self.fade_site = self._fade_slider("site")
        bv.addWidget(self.fade_site)
        v1.addWidget(bx)
        bx, bv = self.box("The stand")
        row = QHBoxLayout()
        self.erf = QLineEdit()
        self.erf.setPlaceholderText("Erf number and suburb or town")
        self.zoning = QLineEdit()
        self.zoning.setPlaceholderText("for example Residential zone I")
        row.addWidget(QLabel("Erf"))
        row.addWidget(self.erf, 2)
        row.addWidget(QLabel("Zoning"))
        row.addWidget(self.zoning, 2)
        bv.addLayout(row)
        v1.addWidget(bx)
        bx, bv = self.box("Corners of the stand", "Metres, measured from any corner. Go round the stand in order. A rectangle is the quickest start.")
        rr = FlowLayout(None, 10, 6)
        self.q_w, self.q_d = spin(1, 5000, 20, 2, " m"), spin(1, 5000, 30, 2, " m")
        rr.addWidget(self._pair("Width", self.q_w))
        rr.addWidget(self._pair("Depth", self.q_d))
        mk = QPushButton("Make a rectangle")
        mk.setToolTip("Sets four corners. The bottom boundary is the street.")
        mk.clicked.connect(self.make_rect)
        rr.addWidget(mk)
        rr.addStretch(1)
        bv.addLayout(rr)
        self.vt = QTableWidget(0, 3)
        self.vt.setHorizontalHeaderLabels(["Corner", "X (m)", "Y (m)"])
        self.vt.verticalHeader().setVisible(False)
        self.vt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.vt.setMinimumHeight(150)
        self.vt.itemChanged.connect(self._verts_edited)
        bv.addWidget(self.vt)
        br = FlowLayout(None, 8, 6)
        a1, a2 = QPushButton("Add a corner"), QPushButton("Remove last corner")
        a1.clicked.connect(lambda: self.add_vertex())
        a2.clicked.connect(self.remove_vertex)
        br.addWidget(a1)
        br.addWidget(a2)
        br.addStretch(1)
        bv.addLayout(br)
        self.area_lbl = QLabel("")
        self.area_lbl.setObjectName("xaSub")
        bv.addWidget(self.area_lbl)
        v1.addWidget(bx)
        bx, bv = self.box("Building lines", "Set the distance to keep clear on each boundary. Check the numbers against your zoning scheme.")
        qr = FlowLayout(None, 10, 6)
        self.q_street, self.q_side, self.q_rear = spin(0, 50, 4.5, 2, " m"), spin(0, 50, 2.0, 2, " m"), spin(0, 50, 3.0, 2, " m")
        for lab, w_ in (("Street", self.q_street), ("Side", self.q_side), ("Rear", self.q_rear)):
            qr.addWidget(self._pair(lab, w_))
        ap = QPushButton("Apply to the boundaries")
        ap.setToolTip("Fills the table below from the kind of each boundary.")
        ap.clicked.connect(self.apply_quick)
        qr.addWidget(ap)
        qr.addStretch(1)
        bv.addLayout(qr)
        self.et = QTableWidget(0, 4)
        self.et.setHorizontalHeaderLabels(["Boundary", "Kind", "Building line (m)", "Name (street name, for example)"])
        self.et.itemChanged.connect(self._edge_text_edited)
        self.et.verticalHeader().setVisible(False)
        self.et.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.et.setMinimumHeight(150)
        bv.addWidget(self.et)
        v1.addWidget(bx)
        bx, bv = self.box("Limits", "Coverage is the share of the stand the buildings cover. FAR is the floor area divided by the stand area. Use 0 for no limit.")
        lr = FlowLayout(None, 10, 6)
        self.max_cov, self.max_far, self.floor_area = spin(0, 100, 60, 1, " %"), spin(0, 20, 0, 2), spin(0, 100000, 0, 2, " m2")
        for lab, w_ in (("Coverage limit", self.max_cov), ("FAR limit", self.max_far), ("Floor area", self.floor_area)):
            lr.addWidget(self._pair(lab, w_))
        self.follow = QCheckBox("Follow the area schedule")
        self.follow.setChecked(True)
        self.follow.setToolTip("Uses the floor area that counts for FAR in the Area schedule.")
        lr.addWidget(self.follow)
        lr.addStretch(1)
        bv.addLayout(lr)
        v1.addWidget(bx)
        v1.addStretch(1)
        # ---- step 2
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("Building footprint", "Bring in the shape of the building as seen from above: from the IFC model (with patios and roof overhangs), or trace it from a footprint drawing.")
        self.fp_lbl = QLabel("No footprint drawing loaded.")
        self.fp_lbl.setObjectName("xaSub")
        self.fp_lbl.setWordWrap(True)
        bv.addWidget(self.fp_lbl)
        bv.addWidget(self._tool_row("fp", [
            ("Footprint from the IFC model...", self.footprint_from_ifc, "The outline from above of walls, slabs (patios, balconies) and roofs."),
            ("Load a footprint drawing (PDF, DXF, DWG)...", lambda: self.load_drawing("fp"), "A floor plan or roof plan to trace over the site."),
            ("Pick a building from the drawing...", lambda: self.pick_shape("fp", "building"), "Lists the closed outlines in the footprint drawing."),
            ("Trace a building by clicking", lambda: self.start_trace("trace_building", "fp"), "Click each corner of the building outline."),
            ("Set the scale or units...", lambda: self.set_scale("fp"), ""),
            ("Calibrate with two points", lambda: self.start_calibrate("fp"), "Click two points on the footprint drawing, then type the real distance."),
            ("Move the drawing", lambda: self.start_move("fp"), "Drag the footprint drawing under the plan."),
            ("Remove the drawing", lambda: self.remove_drawing("fp"), "")]))
        self.fade_fp = self._fade_slider("fp")
        bv.addWidget(self.fade_fp)
        v2.addWidget(bx)
        bx, bv = self.box("Buildings on the stand", "X and Y are the lower left corner of the building, in metres, from the same corner as the stand. A traced shape moves as one piece.")
        self.bt = QTableWidget(0, 7)
        self.bt.setHorizontalHeaderLabels(["Name", "X (m)", "Y (m)", "Width (m)", "Depth (m)", "Area (m2)", "In coverage"])
        self.bt.verticalHeader().setVisible(False)
        self.bt.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bt.setMinimumHeight(200)
        self.bt.itemChanged.connect(self._bld_edited)
        self.bt.itemSelectionChanged.connect(self._sel_changed)
        bv.addWidget(self.bt)
        br = QWidget()
        br_l = FlowLayout(br, 6, 6)
        br.setMinimumHeight(46)
        for text, fn in (("Add a building", lambda: self.add_building()), ("Remove selected", self.remove_building),
                         ("Centre it on the stand", self.centre_building), ("Place with a ruler...", self.place_with_ruler), ("Rotate...", self.rotate_selected),
                         ("Ungroup", self.ungroup_selected)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            br_l.addWidget(b)
        bv.addWidget(br)
        self.live_lbl = QLabel("")
        self.live_lbl.setWordWrap(True)
        bv.addWidget(self.live_lbl)
        v2.addWidget(bx)
        v2.addStretch(1)
        # ---- step 3
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        v3.setContentsMargins(0, 0, 8, 8)
        bx, bv = self.box("What complies", "")
        self.res_t = QTableWidget(0, 3)
        self.res_t.setHorizontalHeaderLabels(["Check", "Result", "Detail"])
        self.res_t.verticalHeader().setVisible(False)
        self.res_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.res_t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.res_t.setMinimumHeight(180)
        bv.addWidget(self.res_t)
        v3.addWidget(bx)
        bx, bv = self.box("Departure motivation", "Only needed when a building goes over a building line. Tick the reasons that are true, then adapt the text.")
        self.reason_cb = {}
        for k, t in REASONS:
            c = QCheckBox(t)
            c.toggled.connect(self._reason_toggled)
            self.reason_cb[k] = c
            bv.addWidget(c)
        self.motiv = QPlainTextEdit()
        self.motiv.setMinimumHeight(200)
        self.motiv.textChanged.connect(self._motiv_edited)
        bv.addWidget(self.motiv)
        mr = QHBoxLayout()
        wb = QPushButton("Write it again")
        wb.setToolTip("Replaces the text with a fresh draft from the numbers and the ticked reasons.")
        wb.clicked.connect(lambda: self.write_motivation(force=True))
        cp = QPushButton("Copy the text")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.motiv.toPlainText()))
        mr.addWidget(wb)
        mr.addWidget(cp)
        mr.addStretch(1)
        bv.addLayout(mr)
        v3.addWidget(bx)
        bx, bv = self.box("Reports")
        rr = QHBoxLayout()
        for text, fn in (("Preview the PDF", self.preview), ("Save the PDF...", self.export)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            rr.addWidget(b)
        rr.addStretch(1)
        bv.addLayout(rr)
        v3.addWidget(bx)
        v3.addStretch(1)
        self._motiv_user = False
        self._area_host = QWidget()                      # the area schedule lives in the last step
        QVBoxLayout(self._area_host).setContentsMargins(0, 0, 0, 0)
        self.build_frame([p1, p2, p3, self._area_host], side=self._plan_panel())
        self.make_rect()
        self.restore()
        self._after_edit()

    def fuse_area(self, area_page):
        """The area schedule is the last step of Building lines: the page is kept as it was, it just sits in this tool."""
        self._area_host.layout().addWidget(area_page)
        self.area_page = area_page

    def on_step(self, i):
        sp = getattr(self, "split", None)             # the plan is not needed for the area schedule: it gets the whole width
        if sp is None:
            return
        tot = max(sum(sp.sizes()), 1000)
        if i == 3:
            self._plan_hidden = True
            sp.setSizes([tot, 0])
        elif getattr(self, "_plan_hidden", False):
            self._plan_hidden = False
            sp.setSizes([int(tot * 0.6), int(tot * 0.4)])

    # ---- reading the tables
    def verts(self):
        out = []
        for r in range(self.vt.rowCount()):
            x, y = self.vt.item(r, 1), self.vt.item(r, 2)
            out.append((tb.num(x.text() if x else 0), tb.num(y.text() if y else 0)))
        return out

    def edges(self):
        out = []
        for r in range(self.et.rowCount()):
            cb, sp = self.et.cellWidget(r, 1), self.et.cellWidget(r, 2)
            out.append({"kind": cb.currentText() if cb else "Side", "sb": sp.value() if sp else 0.0,
                        "name": (self.et.item(r, 3).text().strip() if self.et.item(r, 3) else "")})
        return out

    def buildings(self):
        out = []
        t = self.bt
        g = lambda r, c: tb.num(t.item(r, c).text() if t.item(r, c) else 0)
        for r in range(t.rowCount()):
            nm = t.item(r, 0).text().strip() if t.item(r, 0) else ""
            meta = (t.item(r, 0).data(Qt.ItemDataRole.UserRole) if t.item(r, 0) else None) or {}
            out.append({"name": nm or "Building %d" % (r + 1), "x": g(r, 1), "y": g(r, 2), "w": g(r, 3), "d": g(r, 4),
                        "cov": bool(t.item(r, 6) and t.item(r, 6).checkState() == Qt.CheckState.Checked),
                        "poly": [tuple(p) for p in meta["poly"]] if meta.get("poly") else None, "grp": meta.get("grp", "")})
        return out

    # ---- the stand
    def set_vertices(self, vs, edges=None):
        self._busy = True
        try:
            old = edges or self.edges()
            self.vt.setRowCount(0)
            for i, (x, y) in enumerate(vs):
                self.vt.insertRow(i)
                c = QTableWidgetItem(corner_name(i))
                c.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.vt.setItem(i, 0, c)
                for k, val in ((1, x), (2, y)):
                    it = QTableWidgetItem("%.2f" % val)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.vt.setItem(i, k, it)
            self.et.setRowCount(0)
            n = len(vs)
            for i in range(n):
                self.et.insertRow(i)
                lab = QTableWidgetItem("%s to %s" % (corner_name(i), corner_name((i + 1) % n)))
                lab.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.et.setItem(i, 0, lab)
                e = old[i] if i < len(old) else {"kind": "Side", "sb": self.q_side.value()}
                nm = QTableWidgetItem(e.get("name", ""))
                nm.setToolTip("Type the street name here, for example Jacob Street. A name with Street, Road, Avenue, Laan or Straat in it makes this boundary the street.")
                self.et.setItem(i, 3, nm)
                cb = QComboBox()
                cb.addItems(KINDS)
                cb.setCurrentText(e["kind"])
                cb.currentTextChanged.connect(lambda _t, c_=cb: self._kind_changed(c_))
                sp = spin(0, 100, e["sb"], 2, " m")
                sp.valueChanged.connect(lambda _v: self._after_edit(True))
                self.et.setCellWidget(i, 1, cb)
                self.et.setCellWidget(i, 2, sp)
        finally:
            self._busy = False

    STREET_WORDS = ("street", "st", "road", "rd", "avenue", "ave", "drive", "dr", "straat", "laan", "weg", "lane", "ln", "crescent", "way", "close",
                    "boulevard", "blvd", "highway", "pad", "singel", "plein")

    def _default_sb(self, kind):
        return {"Street": self.q_street.value(), "Side": self.q_side.value(), "Rear": self.q_rear.value()}.get(kind)

    def _kind_changed(self, cb):
        """Choosing Street, Side or Rear fills in that kind's usual building line. You can still type another number."""
        if not self._busy:
            for r in range(self.et.rowCount()):
                if self.et.cellWidget(r, 1) is cb:
                    v = self._default_sb(cb.currentText())
                    if v is not None:
                        self.et.cellWidget(r, 2).setValue(v)
                    break
        self._after_edit(True)

    def _edge_text_edited(self, it):
        if self._busy or it.column() != 3:
            return
        words = [w_.strip(".,") for w_ in it.text().lower().split()]
        cb = self.et.cellWidget(it.row(), 1)
        if cb is not None and any(w_ in self.STREET_WORDS for w_ in words) and cb.currentText() != "Street":
            cb.setCurrentText("Street")        # also fills in the street building line
            return
        self._after_edit(True)

    def set_edge_kind(self, i, kind, ask_name=False):
        cb = self.et.cellWidget(i, 1)
        if cb is None:
            return
        cb.setCurrentText(kind)
        if kind == "Street" and ask_name and not (self.et.item(i, 3) and self.et.item(i, 3).text().strip()):
            self.name_edge(i)

    def name_edge(self, i):
        cur = self.et.item(i, 3).text() if self.et.item(i, 3) else ""
        txt, ok = QInputDialog.getText(self, "Name the boundary", "Name of this boundary (for example the street name):", text=cur)
        if ok:
            self.et.item(i, 3).setText(txt.strip())

    def set_edge_setback(self, i):
        sp = self.et.cellWidget(i, 2)
        if sp is None:
            return
        val, ok = QInputDialog.getDouble(self, "Building line", "Building line on boundary %s, in metres:" % self._edge_name(i), sp.value(), 0, 100, 2)
        if ok:
            sp.setValue(val)

    def edge_menu(self, menu, i):
        menu.addAction("Boundary " + self._edge_name(i)).setEnabled(False)
        menu.addAction("This is the street...", lambda: self.set_edge_kind(i, "Street", True))
        menu.addAction("This is a side boundary", lambda: self.set_edge_kind(i, "Side"))
        menu.addAction("This is the rear boundary", lambda: self.set_edge_kind(i, "Rear"))
        menu.addAction("Other", lambda: self.set_edge_kind(i, "Other"))
        menu.addSeparator()
        menu.addAction("Name this boundary...", lambda: self.name_edge(i))
        menu.addAction("Change the building line...", lambda: self.set_edge_setback(i))

    def make_rect(self):
        w, d = self.q_w.value(), self.q_d.value()
        self.set_vertices([(0, 0), (w, 0), (w, d), (0, d)],
                          [{"kind": "Street", "sb": self.q_street.value()}, {"kind": "Side", "sb": self.q_side.value()},
                           {"kind": "Rear", "sb": self.q_rear.value()}, {"kind": "Side", "sb": self.q_side.value()}])
        self._after_edit(True)

    def add_vertex(self):
        v = self.verts()
        last = v[-1] if v else (0.0, 0.0)
        self.set_vertices(v + [(last[0] + 5, last[1] + 5)])
        self._after_edit(True)

    def remove_vertex(self):
        v = self.verts()
        if len(v) > 3:
            self.set_vertices(v[:-1])
            self._after_edit(True)

    def apply_quick(self):
        m = {"Street": self.q_street.value(), "Side": self.q_side.value(), "Rear": self.q_rear.value()}
        self._busy = True
        for r in range(self.et.rowCount()):
            k = self.et.cellWidget(r, 1).currentText()
            if k in m:
                self.et.cellWidget(r, 2).setValue(m[k])
        self._busy = False
        self._after_edit(True)

    def _verts_edited(self, _it):
        if not self._busy:
            self._after_edit(True)

    # ---- the buildings
    def add_building(self, d=None):
        d = d or {}
        self._busy = True
        try:
            r = self.bt.rowCount()
            self.bt.insertRow(r)
            v = self.verts()
            poly = [tuple(p) for p in d["poly"]] if d.get("poly") else None
            if poly:
                xs, ys = [q[0] for q in poly], [q[1] for q in poly]
                vals = [d.get("name") or "Building %d" % (r + 1), min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            elif d:
                vals = [d.get("name", ""), d.get("x", 0), d.get("y", 0), d.get("w", 10), d.get("d", 10)]
            else:
                bw, bd = 10.0, 8.0
                if v:
                    xs, ys = [p[0] for p in v], [p[1] for p in v]
                    vals = ["Building %d" % (r + 1), round((min(xs) + max(xs)) / 2 - bw / 2, 2), round((min(ys) + max(ys)) / 2 - bd / 2, 2), bw, bd]
                else:
                    vals = ["Building %d" % (r + 1), 0, 0, bw, bd]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val if isinstance(val, str) else "%.2f" % val)
                if c:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if poly and c in (3, 4):
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.bt.setItem(r, c, it)
            self.bt.item(r, 0).setData(Qt.ItemDataRole.UserRole, {"poly": [list(q) for q in poly] if poly else None, "grp": d.get("grp", "")})
            if poly:
                self.bt.item(r, 0).setToolTip("A traced shape: it moves and turns as one piece. Width and depth are its bounding box.")
            ar = QTableWidgetItem("")
            ar.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            ar.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.bt.setItem(r, 5, ar)
            f = QTableWidgetItem("")
            f.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            f.setCheckState(Qt.CheckState.Checked if d.get("cov", True) else Qt.CheckState.Unchecked)
            self.bt.setItem(r, 6, f)
        finally:
            self._busy = False
        if not getattr(self, "_bulk", False):
            self._after_edit(True)

    def remove_building(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()}, reverse=True) or ([self.bt.rowCount() - 1] if self.bt.rowCount() else [])
        for r in rows:
            self.bt.removeRow(r)
        self._after_edit(True)

    def _meta(self, r):
        it = self.bt.item(r, 0)
        return (it.data(Qt.ItemDataRole.UserRole) if it else None) or {}

    def _set_poly(self, r, poly):
        """Give row r a traced outline and refresh its box, keeping its group."""
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        m = self._meta(r)
        m = {"poly": [list(q) for q in poly], "grp": m.get("grp", "")}
        self._busy = True
        self.bt.item(r, 0).setData(Qt.ItemDataRole.UserRole, m)
        for c, val in ((1, min(xs)), (2, min(ys)), (3, max(xs) - min(xs)), (4, max(ys) - min(ys))):
            self.bt.item(r, c).setText("%.2f" % val)
        for c in (3, 4):
            self.bt.item(r, c).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._busy = False

    def _group_rows(self, r):
        g = self._meta(r).get("grp", "")
        if not g:
            return [r]
        return [i for i in range(self.bt.rowCount()) if self._meta(i).get("grp", "") == g]

    def _translate_rows(self, rows, dx, dy):
        self._busy = True
        for r in rows:
            m = self._meta(r)
            if m.get("poly"):
                self._busy = False
                self._set_poly(r, [(q[0] + dx, q[1] + dy) for q in m["poly"]])
                self._busy = True
            else:
                for c in (1, 2):
                    self.bt.item(r, c).setText("%.2f" % (tb.num(self.bt.item(r, c).text()) + (dx if c == 1 else dy)))
        self._busy = False

    def centre_building(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()}) or ([0] if self.bt.rowCount() else [])
        v = self.verts()
        if not v or not rows:
            return
        cx, cy = sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)
        bl = self.buildings()
        allrows = sorted({i for r in rows for i in self._group_rows(r)})
        x0 = min(bpoly(bl[i])[k][0] for i in allrows for k in range(len(bpoly(bl[i]))))
        x1 = max(bpoly(bl[i])[k][0] for i in allrows for k in range(len(bpoly(bl[i]))))
        y0 = min(bpoly(bl[i])[k][1] for i in allrows for k in range(len(bpoly(bl[i]))))
        y1 = max(bpoly(bl[i])[k][1] for i in allrows for k in range(len(bpoly(bl[i]))))
        self._translate_rows(allrows, cx - (x0 + x1) / 2, cy - (y0 + y1) / 2)
        self._after_edit(True)

    def _sel_group(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Building lines", "Click a building in the list or in the plan first.")
            return None
        return sorted({i for r in rows for i in self._group_rows(r)})

    def rotate_rows(self, allrows, deg):
        bl = self.buildings()
        pts = [q for i in allrows for q in bpoly(bl[i])]
        cx, cy = (min(q[0] for q in pts) + max(q[0] for q in pts)) / 2, (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2
        a = math.radians(deg)
        for i in allrows:
            self._set_poly(i, self._rot_pts(bpoly(bl[i]), a, cx, cy))
        self._after_edit(True)
        self.plan.update()

    def rotate_selected(self, deg=None):
        """Turn the selected building (anticlockwise is positive). Without an angle it asks."""
        allrows = self._sel_group()
        if allrows is None:
            return
        if deg is None:
            self.rotate_live(allrows)
            return
        if deg:
            self.rotate_rows(allrows, deg)

    def rotate_live(self, allrows):
        """fine-tune turn with a slider and live preview; Cancel puts the building back"""
        from rotate_dialog import RotateDialog
        bl = self.buildings()
        snap = {i: [tuple(q) for q in bpoly(bl[i])] for i in allrows}
        pts = [q for i in allrows for q in snap[i]]
        cx, cy = (min(q[0] for q in pts) + max(q[0] for q in pts)) / 2, (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2

        def apply(a):
            for i in allrows:
                self._set_poly(i, self._rot_pts(snap[i], math.radians(a), cx, cy))
            self._after_edit(True)
            self.plan.update()
        RotateDialog(self, "Rotate the building", 0.0, apply, "Turn the building. Positive turns it anticlockwise, negative clockwise. Cancel puts it back.").exec()

    def _group_angle(self, allrows):
        bl = self.buildings()
        polys = [bpoly(bl[i]) for i in allrows]
        big = max(polys, key=lambda p: abs(si.poly_area(p)))
        best, ang = -1.0, 0.0
        for i in range(len(big)):
            a, b = big[i], big[(i + 1) % len(big)]
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            if ln > best:
                best, ang = ln, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        return ang

    def snap_selected(self, step):
        """Turn the building so its longest wall lies on the nearest multiple of step degrees (90 = horizontal or vertical)."""
        allrows = self._sel_group()
        if allrows is None:
            return
        ang = self._group_angle(allrows)
        d = round(ang / step) * step - ang
        if abs(d) > 1e-6:
            self.rotate_rows(allrows, d)

    def align_to_boundary(self):
        allrows = self._sel_group()
        v = self.verts()
        if allrows is None or len(v) < 3:
            return
        ang = self._group_angle(allrows)
        best = None
        for i in range(len(v)):
            a, b = v[i], v[(i + 1) % len(v)]
            ea = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            d = (ea - ang + 90) % 180 - 90
            if best is None or abs(d) < abs(best):
                best = d
        if best:
            self.rotate_rows(allrows, best)

    # ---- turning the whole plan, the north arrow, and the menus
    def rotate_plan(self, deg=None):
        v = self.verts()
        if len(v) < 3:
            QMessageBox.information(self, "Building lines", "Set the stand first.")
            return
        if deg is None:
            deg, ok = QInputDialog.getDouble(self, "Rotate the plan", "Turn the stand, the drawings and the buildings by how many degrees?\n"
                                             "(positive turns anticlockwise, negative clockwise)", 0, -360, 360, 1)
            if not ok:
                return
        if not deg:
            return
        a = math.radians(deg)
        cx, cy = sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)
        self.rotate_world(a, cx, cy)
        nv = self._rot_pts(v, a, cx, cy)
        mnx, mny = min(p[0] for p in nv), min(p[1] for p in nv)
        self.shift_world(-mnx, -mny)
        self.set_vertices([(x - mnx, y - mny) for x, y in nv])
        self.plan.fit()
        self._after_edit(True)

    def level_plan(self):
        v = self.verts()
        if len(v) >= 3:
            self.rotate_plan(math.degrees(-self._long_edge_angle(v)))

    def rotate_north(self, deg):
        self.north = (self.north + deg) % 360
        self.plan.update()
        self.changed()

    def north_custom(self):
        cur = round((90 - self.north) % 360)
        b, ok = QInputDialog.getInt(self, "North arrow", "Where does north point?\nGive the direction in degrees clockwise from straight up (0 = up, 90 = right).", cur, 0, 359)
        if ok:
            self.north = (90 - b) % 360
            self.plan.update()
            self.changed()

    def _steps_menu(self, menu, fn, custom, title=None):
        for step in (90, 45, 15, 1):
            menu.addAction("Turn %d\u00b0 clockwise" % step, lambda s_=step: fn(-s_))
            menu.addAction("Turn %d\u00b0 anticlockwise" % step, lambda s_=step: fn(s_))
        menu.addSeparator()
        menu.addAction("Custom angle...", custom)

    def north_menu(self, menu):
        menu.addAction("North points up", lambda: (setattr(self, "north", 90.0), self.plan.update(), self.changed()))
        menu.addSeparator()
        self._steps_menu(menu, self.rotate_north, self.north_custom)
        menu.addSeparator()
        menu.addAction("Hide the north arrow", lambda: self.show_north(False))

    def show_north(self, on):
        self.north_on = bool(on)
        self.plan.update()
        self.changed()

    def plan_menu(self, menu):
        menu.addAction("Rotate the whole plan").setEnabled(False)
        self._steps_menu(menu, self.rotate_plan, self.rotate_plan)
        menu.addSeparator()
        menu.addAction("Turn the longest boundary horizontal", self.level_plan)
        menu.addSeparator()
        menu.addAction("Show the whole stand", self.plan.fit)
        menu.addAction("Hide the north arrow" if self.north_on else "Show the north arrow", lambda: self.show_north(not self.north_on))

    def building_menu(self, menu):
        menu.addAction("Rotate (fine tune with a slider)...", self.rotate_selected)
        menu.addSeparator()
        self._steps_menu(menu, self.rotate_selected, self.rotate_selected)
        menu.addSeparator()
        sn = menu.addMenu("Snap its angle to")
        sn.addAction("90\u00b0 (walls horizontal and vertical)", lambda: self.snap_selected(90))
        sn.addAction("45\u00b0", lambda: self.snap_selected(45))
        sn.addAction("15\u00b0", lambda: self.snap_selected(15))
        menu.addAction("Line up with the nearest boundary", self.align_to_boundary)
        menu.addSeparator()
        menu.addAction("Place with a ruler...", self.place_with_ruler)
        menu.addAction("Centre it on the stand", self.centre_building)
        menu.addAction("Ungroup", self.ungroup_selected)
        menu.addAction("Remove this building", self.remove_building)

    def ungroup_selected(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        for r in rows:
            for i in self._group_rows(r):
                m = self._meta(i)
                self.bt.item(i, 0).setData(Qt.ItemDataRole.UserRole, {"poly": m.get("poly"), "grp": ""})
        self.changed()

    def _bld_edited(self, it):
        if self._busy:
            return
        r = it.row()
        m = self._meta(r)
        if it.column() in (1, 2) and m.get("poly"):
            xs, ys = [q[0] for q in m["poly"]], [q[1] for q in m["poly"]]
            dx = tb.num(self.bt.item(r, 1).text()) - min(xs)
            dy = tb.num(self.bt.item(r, 2).text()) - min(ys)
            self._translate_rows(self._group_rows(r), dx, dy)
        self._after_edit(True)

    def _sel_changed(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        self.plan.sel = rows[0] if rows else -1
        self.plan.update()

    def select_building(self, i):
        self.bt.selectRow(i)

    def move_building(self, i, x, y):
        if i >= self.bt.rowCount():
            return
        cx, cy = tb.num(self.bt.item(i, 1).text()), tb.num(self.bt.item(i, 2).text())
        self._translate_rows(self._group_rows(i), x - cx, y - cy)
        self._after_edit(True)


    # ---- survey drawing and footprint drawing
    @staticmethod
    def _pair(lab, w):
        """a label with its box, kept together when a row wraps"""
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        if lab:
            h.addWidget(QLabel(lab))
        h.addWidget(w)
        return c

    def _tool_row(self, role, items):
        row = QWidget()
        fl = FlowLayout(row, 6, 6)
        for text, fn, tip in items:
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        row.setMinimumHeight(92)
        return row

    def _fade_slider(self, role):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Fade the drawing"))
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(10, 100)
        sl.setValue(75 if role == "site" else 60)
        sl.setMaximumWidth(260)
        sl.valueChanged.connect(lambda val, r=role: self._set_opacity(r, val))
        h.addWidget(sl)
        h.addStretch(1)
        w.slider = sl
        return w

    def _set_opacity(self, role, val):
        u = self.under.get(role)
        if u is not None:
            u.opacity = val / 100.0
            self.plan.update()
            self.changed()

    def _plan_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        bar = QWidget()
        fl = FlowLayout(bar, 4, 4)
        for text, fn, tip in (("Fit", self.plan.fit, "Show the whole stand."), ("Zoom in", lambda: self.plan.zoom(1.4), "Or turn the mouse wheel."),
                              ("Zoom out", lambda: self.plan.zoom(1 / 1.4), ""), ("Stop the tool", self.plan.end, "Or press Esc.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            fl.addWidget(b)
        for text, filler, tip in (("Rotate plan", self.plan_menu, "Turn the stand, the survey and the buildings together."),
                                  ("North arrow", self.north_menu, "Turn the north arrow, or drag it in the plan."),
                                  ("Rotate building", self.building_menu, "Turn the selected building by steps, snap it, or type an angle.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            mn = QMenu(b)
            mn.aboutToShow.connect(lambda m=mn, f=filler: (m.clear(), f(m)))
            b.setMenu(mn)
            fl.addWidget(b)
        bar.setMinimumHeight(84)
        v.addWidget(bar)
        self.hint_lbl = QLabel("")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet("color:#d6209a; font-weight:600;")
        self.hint_lbl.setVisible(False)
        v.addWidget(self.hint_lbl)
        v.addWidget(self.plan, 1)
        return panel

    def set_hint(self, t):
        self.hint_lbl.setText(t)
        self.hint_lbl.setVisible(bool(t))

    def _busy_run(self, fn, *a, **k):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return fn(*a, **k)
        finally:
            QApplication.restoreOverrideCursor()

    def _ask_scale(self, default=500):
        items = ["1:50", "1:100", "1:200", "1:250", "1:500", "1:1000", "1:2000", "Other..."]
        cur = "1:%d" % int(round(default))
        txt, ok = QInputDialog.getItem(self, "Drawing scale", "What is the scale of this drawing when printed?", items,
                                       items.index(cur) if cur in items else 4, False)
        if not ok:
            return None
        if txt == "Other...":
            n, ok = QInputDialog.getInt(self, "Drawing scale", "1 :", int(default), 1, 100000)
            return n if ok else None
        return int(txt.split(":")[1])

    def load_drawing(self, role):
        title = "Load the survey drawing" if role == "site" else "Load the footprint drawing"
        path, _ = QFileDialog.getOpenFileName(self, title, "", "Drawings (*.dwg *.dxf *.pdf);;All files (*)")
        if path:
            self._load_path(role, path, ask=True)

    def _load_path(self, role, path, ask=True, st=None):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".dxf", ".dwg"):
                src = self._busy_run(si.dwg_to_dxf, path) if ext == ".dwg" else path
                unit = (st or {}).get("unit")
                if ask:
                    guess = self._busy_run(si.dxf_guess_unit, src)
                    names = ["Metres", "Millimetres", "Centimetres"]
                    item, ok = QInputDialog.getItem(self, "Units", "What units is this drawing in?", names, {"m": 0, "mm": 1, "cm": 2}[guess], False)
                    if not ok:
                        return
                    unit = {"Metres": "m", "Millimetres": "mm", "Centimetres": "cm"}[item]
                u = self._busy_run(si.load_dxf, src, unit or "m")
                u.file = path
            elif ext == ".pdf":
                page, scale = (st or {}).get("page", 0), (st or {}).get("scale_n", 500)
                if ask:
                    n = si.pdf_pages(path)
                    if n > 1:
                        pg, ok = QInputDialog.getInt(self, "Which page?", "This PDF has %d pages. Which page is the drawing?" % n, 1, 1, n)
                        if not ok:
                            return
                        page = pg - 1
                    scale = self._ask_scale(500 if role == "site" else 100)
                    if scale is None:
                        return
                u = self._busy_run(si.load_pdf, path, scale, page)
            else:
                raise RuntimeError("Use a DWG, DXF or PDF file.")
        except Exception as e:
            if st is not None:
                self._under_note[role] = "The drawing could not be loaded: %s (%s)" % (os.path.basename(path), e)
                return
            QMessageBox.warning(self, "Building lines", str(e))
            return
        u.role = role
        u.opacity = 0.75 if role == "site" else 0.6
        if st:
            u.k, u.ox, u.oy, u.rot = st.get("k", u.k), st.get("ox", 0.0), st.get("oy", 0.0), st.get("rot", 0.0)
            u.opacity = st.get("opacity", u.opacity)
        elif role == "fp":
            v = self.verts()
            if v:
                u.move_centre_to(sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v))
        self.under[role] = u
        self._under_note.pop(role, None)
        self._update_under_labels()
        self.plan.auto = True
        self.plan.update()
        self.changed()
        if ask and role == "site":
            if not self.auto_stand():
                self.set_hint("No outline that looks like the stand was found. Use Pick the stand from the drawing, or Trace the stand by clicking.")
        elif ask and role == "fp":
            self.set_hint("Footprint drawing placed at the middle of the stand. Use Move the drawing to put it where you want, then trace the outline.")

    def _restore_unders(self, st):
        self.under = {"site": None, "fp": None}
        self._under_note = {}
        for role, d in st.items():
            if role in self.under and d and d.get("path"):
                if os.path.exists(d["path"]):
                    self._load_path(role, d["path"], False, d)
                else:
                    self._under_note[role] = "The drawing file was not found: " + d["path"]
        self._update_under_labels()

    def _update_under_labels(self):
        for role, lbl, sl in (("site", self.survey_lbl, self.fade_site), ("fp", self.fp_lbl, self.fade_fp)):
            u = self.under.get(role)
            if u is None:
                lbl.setText(self._under_note.get(role) or ("No drawing loaded." if role == "site" else "No footprint drawing loaded."))
                continue
            how = ("PDF at 1:%d" % round(u.k)) if u.kind == "pdf" else "units %s" % {"m": "metres", "mm": "millimetres", "cm": "centimetres"}.get(u.unit, u.unit)
            lbl.setText("<b>%s</b>  |  %s  |  %d closed outlines found" % (tb.esc(os.path.basename(u.file)), how, len(u.candidates(1))))
            sl.slider.blockSignals(True)
            sl.slider.setValue(int(u.opacity * 100))
            sl.slider.blockSignals(False)

    def _under(self, role):
        u = self.under.get(role)
        if u is None:
            QMessageBox.information(self, "Building lines", "Load the drawing first.")
        return u

    def remove_drawing(self, role):
        self.under[role] = None
        self._update_under_labels()
        self.plan.update()
        self.changed()

    def set_scale(self, role):
        u = self._under(role)
        if u is None:
            return
        if u.kind == "pdf":
            n = self._ask_scale(u.k)
            if n:
                u.set_k(float(n))
                u.scale_n = n
        else:
            names = ["Metres", "Millimetres", "Centimetres"]
            item, ok = QInputDialog.getItem(self, "Units", "What units is this drawing in?", names, {"m": 0, "mm": 1, "cm": 2}.get(u.unit, 0), False)
            if ok:
                new = {"Metres": "m", "Millimetres": "mm", "Centimetres": "cm"}[item]
                f = {"m": 1.0, "mm": 0.001, "cm": 0.01}
                u.set_k(u.k * f[new] / f[u.unit])
                u.unit = new
        self._update_under_labels()
        self.plan.auto = True
        self.plan.update()
        self.changed()

    def start_calibrate(self, role):
        if self._under(role) is None:
            return
        self.plan.begin("calibrate", role)
        self.set_hint("Click the first point of a distance you know (for example two ends of a boundary).")

    def calibrate_done(self, role, a, b):
        u = self.under.get(role)
        if u is None:
            return
        m = math.hypot(b[0] - a[0], b[1] - a[1])
        real, ok = QInputDialog.getDouble(self, "Calibrate", "The real distance between the two points, in metres:", round(m, 2), 0.01, 100000, 3)
        if ok:
            u.calibrate(a, b, real)
            self._update_under_labels()
            self.changed()
        self.plan.update()

    def start_move(self, role):
        if self._under(role) is None:
            return
        self.plan.begin("move_under", role)
        self.set_hint("Drag the drawing to where you want it. Press Esc or Stop the tool when done.")

    def start_trace(self, mode, role):
        if self._under(role) is None:
            return
        self.plan.begin(mode, role)
        self.set_hint("Click each corner. Hold Shift to keep a line straight. The mouse wheel zooms, the middle or right button pans. "
                      "Double-click or press Enter to finish.")

    def trace_done(self, mode, role, pts):
        if mode == "trace_stand":
            self.apply_stand_polygon(pts)
        else:
            self._grp_n += 1
            self.add_building({"name": "Building %d" % (self.bt.rowCount() + 1), "poly": self._level_group([si.clean(pts)])[0] if role == "fp" else si.clean(pts)})
            self.plan.fit()
            self.bt.selectRow(self.bt.rowCount() - 1)
            self.set_hint("Building traced. Drag it, or press Rotate... to turn it.")

    def shift_world(self, dx, dy):
        for u in self.under.values():
            if u is not None:
                u.ox += dx
                u.oy += dy
        self._translate_rows(list(range(self.bt.rowCount())), dx, dy)

    @staticmethod
    def _long_edge_angle(pts):
        """Angle (radians, -90..90 degrees) of the longest edge, so that edge can be turned to horizontal."""
        best, ang = -1.0, 0.0
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            if ln > best:
                best, ang = ln, math.atan2(b[1] - a[1], b[0] - a[0])
        d = math.degrees(ang)
        while d > 90:
            d -= 180
        while d <= -90:
            d += 180
        return math.radians(d)

    @staticmethod
    def _rot_pts(pts, a, cx, cy):
        c, s_ = math.cos(a), math.sin(a)
        return [(cx + (x - cx) * c - (y - cy) * s_, cy + (x - cx) * s_ + (y - cy) * c) for x, y in pts]

    def rotate_world(self, a, cx, cy):
        """Turn the drawings and every building about a point. The stand is turned by the caller."""
        self.north = (self.north + math.degrees(a)) % 360
        for u in self.under.values():
            if u is not None:
                u.rotate_about(a, cx, cy)
        bl = self.buildings()
        for i, b in enumerate(bl):
            self._set_poly(i, self._rot_pts(bpoly(b), a, cx, cy))

    def apply_stand_polygon(self, pts):
        pts = si.clean(pts)
        if len(pts) < 3:
            return
        # always horizontal: turn the longest boundary to run left to right, whatever way the drawing came in
        a = -self._long_edge_angle(pts)
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if abs(a) > 1e-6:
            self.rotate_world(a, cx, cy)
            pts = self._rot_pts(pts, a, cx, cy)
        mnx, mny = min(p[0] for p in pts), min(p[1] for p in pts)
        self.shift_world(-mnx, -mny)
        self.set_vertices([(x - mnx, y - mny) for x, y in pts])
        self.plan.fit()
        self.set_hint("The stand is drawn from the survey and turned so its longest boundary is horizontal. Set which boundary is the street, a side or the rear, "
                      "then press Apply to the boundaries.")
        self._after_edit(True)

    def auto_stand(self):
        """Draw the stand from the survey: the biggest closed outline that is not the sheet border."""
        u = self.under.get("site")
        if u is None:
            return False
        x0, y0, x1, y1 = u.raw_bounds()
        W_, H_ = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        best = None
        for c in u.cands:
            xs, ys = [q[0] for q in c], [q[1] for q in c]
            if (max(xs) - min(xs)) > 0.9 * W_ and (max(ys) - min(ys)) > 0.9 * H_:
                continue
            w = [u.to_world(q) for q in c]
            ar = abs(si.poly_area(w))
            if ar >= 20 and (best is None or ar > best[0]):
                best = (ar, w)
        if best is None:
            return False
        self.apply_stand_polygon(best[1])
        return True

    def _level_group(self, polys):
        """Turn a set of shapes that belong together so the longest edge of the biggest one is horizontal."""
        if not polys:
            return polys
        big = max(polys, key=lambda p: abs(si.poly_area(p)))
        a = -self._long_edge_angle(big)
        if abs(a) < 1e-6:
            return polys
        pts = [q for p in polys for q in p]
        cx, cy = (min(q[0] for q in pts) + max(q[0] for q in pts)) / 2, (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2
        return [self._rot_pts(p, a, cx, cy) for p in polys]

    # ---- place a building with a ruler
    def _inward(self):
        v = self.verts()
        sg = 1.0 if signed_area(v) >= 0 else -1.0
        out = []
        for i in range(len(v)):
            a, b = v[i], v[(i + 1) % len(v)]
            ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            out.append(((-(b[1] - a[1]) / ln) * sg, ((b[0] - a[0]) / ln) * sg, a))
        return out

    def edge_distance(self, pts, i):
        """Shortest distance from the shape to boundary i, measured at a right angle (negative means over the line)."""
        nx, ny, a = self._inward()[i]
        return min(nx * (q[0] - a[0]) + ny * (q[1] - a[1]) for q in pts)

    def place_with_ruler(self):
        rows = sorted({i.row() for i in self.bt.selectedIndexes()})
        v = self.verts()
        if not rows or len(v) < 3:
            QMessageBox.information(self, "Building lines", "Click a building in the list or in the plan first (and set the stand).")
            return
        grp = sorted({i for r in rows for i in self._group_rows(r)})
        bl = self.buildings()
        pts = [q for i in grp for q in bpoly(bl[i])]
        n = len(v)
        names = ["%s  -  %s" % (self._edge_name(i), (self.edges()[i]["kind"] if i < len(self.edges()) else "")) for i in range(n)]
        kinds = [e["kind"] for e in self.edges()]
        ia = kinds.index("Street") if "Street" in kinds else 0
        inw = self._inward()

        def par(i, j):
            return abs(inw[i][0] * inw[j][1] - inw[i][1] * inw[j][0]) < 0.05
        ib = next((j for j in range(n) if j != ia and not par(ia, j) and kinds[j] == "Side"), None)
        if ib is None:
            ib = next((j for j in range(n) if j != ia and not par(ia, j)), (ia + 1) % n)
        d = QDialog(self)
        d.setWindowTitle("Place with a ruler")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Say how far the building must be from two boundaries. It moves as you type.\n"
                             "The distance is measured at a right angle from the boundary to the nearest part of the building."))
        grid = QGridLayout()
        lay.addLayout(grid)
        cbs, sps = [], []
        for r_, (ix, lab) in enumerate(((ia, "From boundary"), (ib, "and from boundary"))):
            cb = QComboBox()
            cb.addItems(names)
            cb.setCurrentIndex(ix)
            sp = QDoubleSpinBox()
            sp.setRange(-50, 1000)
            sp.setDecimals(2)
            sp.setSingleStep(0.1)
            sp.setSuffix(" m")
            sp.setValue(round(self.edge_distance(pts, ix), 2))
            grid.addWidget(QLabel(lab), r_, 0)
            grid.addWidget(cb, r_, 1)
            grid.addWidget(QLabel("is"), r_, 2)
            grid.addWidget(sp, r_, 3)
            cbs.append(cb)
            sps.append(sp)
        warn = QLabel("")
        warn.setStyleSheet("color:#d9a21b;")
        lay.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        applied = [0.0, 0.0]
        base = [pts]

        def apply(_=None):
            i, j = cbs[0].currentIndex(), cbs[1].currentIndex()
            det = inw[i][0] * inw[j][1] - inw[i][1] * inw[j][0]
            if i == j or abs(det) < 0.05:
                warn.setText("Choose two boundaries that are not parallel.")
                return
            warn.setText("")
            ea = sps[0].value() - self.edge_distance(base[0], i)
            eb = sps[1].value() - self.edge_distance(base[0], j)
            tx = (ea * inw[j][1] - eb * inw[i][1]) / det
            ty = (inw[i][0] * eb - inw[j][0] * ea) / det
            self._translate_rows(grp, tx - applied[0], ty - applied[1])
            applied[0], applied[1] = tx, ty
            self._after_edit(True)
        for w_ in cbs:
            w_.currentIndexChanged.connect(apply)
        for w_ in sps:
            w_.valueChanged.connect(apply)
        if not d.exec():
            self._translate_rows(grp, -applied[0], -applied[1])
            self._after_edit(True)
        self.plan.update()

    def pick_shape(self, role, target):
        u = self._under(role)
        if u is None:
            return
        cands = u.candidates(20 if target == "stand" else 4)[:300]
        if not cands:
            QMessageBox.information(self, "Building lines", "No closed outlines were found in this drawing. Use Trace by clicking instead.")
            return
        dlg = PickDialog(self, cands, target)
        dlg.lst.currentRowChanged.connect(lambda i: (setattr(self.plan, "highlight", cands[i][1] if 0 <= i < len(cands) else None), self.plan.update()))
        dlg.lst.setCurrentRow(0)
        ok = dlg.exec()
        self.plan.highlight = None
        self.plan.update()
        if ok and dlg.chosen is not None:
            if target == "stand":
                self.apply_stand_polygon(dlg.chosen)
            else:
                self.add_building({"name": "Building %d" % (self.bt.rowCount() + 1), "poly": self._level_group([si.clean(dlg.chosen)])[0] if role == "fp" else si.clean(dlg.chosen)})
                self.plan.fit()

    def footprint_from_ifc(self):
        try:
            import ifcopenshell  # noqa
        except Exception:
            try:
                self.win._install_ifcopenshell(self.footprint_from_ifc)
            except Exception:
                QMessageBox.warning(self, "Building lines", "The IFC reader is not installed.")
            return
        path = getattr(self.win, "ifc_path", "") or ""
        if path and os.path.exists(path):
            m = QMessageBox(self)
            m.setWindowTitle("IFC model")
            m.setText("Use the model already loaded in this project?\n\n" + os.path.basename(path))
            use = m.addButton("Use this model", QMessageBox.ButtonRole.AcceptRole)
            other = m.addButton("Choose another...", QMessageBox.ButtonRole.ActionRole)
            cancel = m.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            m.exec()
            if m.clickedButton() is cancel:
                return
            if m.clickedButton() is other:
                path = ""
        else:
            path = ""
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "IFC model", "", "IFC model (*.ifc *.ifczip)")
            if not path:
                return
        d = QDialog(self)
        d.setWindowTitle("Footprint from the IFC model")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("What counts as part of the footprint, seen from above?"))
        c1 = QCheckBox("Patios, balconies and other slabs")
        c1.setChecked(True)
        c2 = QCheckBox("Roof overhangs")
        c2.setChecked(True)
        c3 = QCheckBox("Straighten it (turn the longest wall to horizontal)")
        c3.setToolTip("Leave this off to keep the direction the model was drawn in. You can always turn it later: right-click the building in the plan.")
        lay.addWidget(c1)
        lay.addWidget(c2)
        lay.addWidget(c3)
        lay.addWidget(QLabel("Walls, columns and stairs are always included."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if not d.exec():
            return
        pd = QProgressDialog("Reading the IFC model...", "Cancel", 0, 100, self)
        pd.setWindowModality(Qt.WindowModality.WindowModal)
        pd.setMinimumDuration(0)

        def prog(i, n):
            pd.setValue(int(100 * i / max(n, 1)))
            QApplication.processEvents()
            return not pd.wasCanceled()
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            polys = si.ifc_footprint(path, c1.isChecked(), c2.isChecked(), prog)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            pd.close()
            if str(e) != "Cancelled":
                QMessageBox.warning(self, "Building lines", "The footprint could not be made: %s" % e)
            return
        QApplication.restoreOverrideCursor()
        pd.close()
        if c3.isChecked():
            polys = self._level_group(polys)
        pts = [q for p in polys for q in p]
        mx, my = (min(q[0] for q in pts) + max(q[0] for q in pts)) / 2, (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2
        v = self.verts()
        tx, ty = (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) if v else (0.0, 0.0)
        self._grp_n += 1
        grp = "ifc%d" % self._grp_n
        n0 = self.bt.rowCount()
        self._bulk = True
        for k, p in enumerate(polys):
            self.add_building({"name": "Footprint %d" % (n0 + k + 1), "poly": [(x - mx + tx, y - my + ty) for x, y in p], "grp": grp})
        self._bulk = False
        self._after_edit(True)
        self.plan.fit()
        self.set_hint("%d footprint%s added at the middle of the stand. Drag it into place and right-click it to turn it the way you want." %
                      (len(polys), "" if len(polys) == 1 else "s"))

    # ---- results
    def current_floor_area(self):
        if self.follow.isChecked():
            ap = getattr(self.win, "area_page", None)
            if ap is not None and ap.total_area() > 0:
                return ap.far_area()
        return self.floor_area.value()

    def result(self):
        return analyse(self.verts(), self.edges(), self.buildings(), self.max_cov.value(), self.max_far.value(), self.current_floor_area())

    def encroachments(self):
        an = self.result()
        return [(b["name"], e) for b in an["buildings"] for e in b["enc"]]

    def _after_edit(self, user=False):
        if self._busy:
            return
        v = self.verts()
        self._busy = True
        for r_, b_ in enumerate(self.buildings()):
            if self.bt.item(r_, 5):
                self.bt.item(r_, 5).setText("%.2f" % abs(signed_area(bpoly(b_))))
        self._busy = False
        if self.follow.isChecked():
            ap = getattr(self.win, "area_page", None)
            if ap is not None and ap.total_area() > 0:
                self._busy = True
                self.floor_area.setValue(ap.far_area())
                self._busy = False
        a = abs(signed_area(v)) if len(v) >= 3 else 0
        note = "" if is_convex(v) else "  The stand is not convex, so the check near inside corners is approximate."
        self.area_lbl.setText("Stand area: %.2f m2.%s" % (a, note))
        an = self.result()
        enc = [(b["name"], e) for b in an["buildings"] for e in b["enc"]]
        if not an["buildings"]:
            self.live_lbl.setText("No buildings yet. Press Add a building.")
        elif enc:
            self.live_lbl.setText("<span style='color:#d8303f'><b>%d building line problem%s.</b></span> See the plan (red)." % (len(enc), "" if len(enc) == 1 else "s"))
        else:
            self.live_lbl.setText("<span style='color:#2e9e5b'><b>Every building is inside the building lines.</b></span>")
        self.fill_results(an)
        if not self._motiv_user:
            self.write_motivation()
        self.plan.update()
        if user:
            self.changed()

    def fill_results(self, an):
        t = self.res_t
        t.setRowCount(0)
        rows = []
        for b in an["buildings"]:
            if b["enc"]:
                rows.append((b["name"] + " - building lines", "Over", "; ".join("%s line %s: over by %.2f m (%.2f m from the boundary)" %
                                                                                (e["kind"].lower(), self._edge_name(e["edge"]), e["by"], e["dist"]) for e in b["enc"]), False))
            else:
                rows.append((b["name"] + " - building lines", "OK", "Inside every building line", True))
        rows.append(("Coverage", "OK" if an["cov_ok"] else "Over", "%.1f %% of the stand%s" % (an["cov_pct"], (" (limit %.1f %%)" % self.max_cov.value()) if self.max_cov.value() else ""), an["cov_ok"]))
        rows.append(("Floor area ratio", "OK" if an["far_ok"] else "Over", "%.2f%s" % (an["far"], (" (limit %.2f)" % self.max_far.value()) if self.max_far.value() else "") +
                     ("" if self.current_floor_area() else "  - no floor area yet (fill the Area schedule)"), an["far_ok"]))
        for lab, res, det, ok in rows:
            r = t.rowCount()
            t.insertRow(r)
            for c, val in enumerate((lab, res, det)):
                it = QTableWidgetItem(val)
                if c == 1:
                    it.setForeground(QColor("#2e9e5b") if ok else QColor("#e0243a"))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                t.setItem(r, c, it)
        t.setColumnWidth(0, 200)
        t.setColumnWidth(1, 70)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        t.setWordWrap(True)
        t.resizeRowsToContents()

    def _edge_name(self, i):
        n = len(self.verts())
        if not n:
            return ""
        nm = self.et.item(i, 3).text().strip() if i < self.et.rowCount() and self.et.item(i, 3) else ""
        return "%s to %s%s" % (corner_name(i), corner_name((i + 1) % n), (" (%s)" % nm) if nm else "")

    # ---- the departure motivation
    def _reason_toggled(self, _c):
        self.write_motivation(force=True)
        self.changed()

    def _motiv_edited(self):
        if not getattr(self, "_writing", False):
            self._motiv_user = True
            self.changed()

    def motivation_text(self):
        an = self.result()
        enc = [(b["name"], e) for b in an["buildings"] for e in b["enc"]]
        site = (self.erf.text().strip() or (getattr(self.win, "rd", {}) or {}).get("details") or "the stand")
        if not enc:
            return "No departure is needed on %s: every building is inside the building lines." % site
        lines = ["APPLICATION FOR A DEPARTURE FROM THE BUILDING LINES", site, "",
                 "The proposed building work goes over the following building lines:"]
        for nm, e in enc:
            lines.append("- %s goes %.2f m into the %.2f m %s building line (boundary %s), which leaves %.2f m to the boundary." %
                         (nm, e["by"], e["sb"], e["kind"].lower(), self._edge_name(e["edge"]), e["dist"]))
        picked = [t for k, t in REASONS if self.reason_cb[k].isChecked()]
        lines += ["", "Motivation:"]
        lines += ["%d. %s" % (i + 1, t) for i, t in enumerate(picked)] if picked else ["(Tick the reasons that are true above, or write your own here.)"]
        lines += ["", "Approval is respectfully requested for a relaxation of the building line(s) as shown on the attached site plan."]
        return "\n".join(lines)

    def write_motivation(self, force=False):
        if force:
            self._motiv_user = False
        if self._motiv_user:
            return
        self._writing = True
        self.motiv.setPlainText(self.motivation_text())
        self._writing = False

    # ---- state
    def state(self):
        return {"erf": self.erf.text(), "zoning": self.zoning.text(), "verts": [list(p) for p in self.verts()], "edges": self.edges(),
                "max_cov": self.max_cov.value(), "max_far": self.max_far.value(), "floor_area": self.floor_area.value(),
                "follow": self.follow.isChecked(), "buildings": self.buildings(),
                "reasons": [k for k, c in self.reason_cb.items() if c.isChecked()],
                "motivation": self.motiv.toPlainText() if self._motiv_user else "", "q": [self.q_street.value(), self.q_side.value(), self.q_rear.value()],
                "under": {r: u.state() for r, u in self.under.items() if u is not None},
                "north": self.north, "north_on": self.north_on}

    def set_state(self, d):
        d = d or {}
        self._busy = True
        self.erf.setText(d.get("erf", ""))
        self.zoning.setText(d.get("zoning", ""))
        self.max_cov.setValue(d.get("max_cov", 60))
        self.max_far.setValue(d.get("max_far", 0))
        self.floor_area.setValue(d.get("floor_area", 0))
        self.follow.setChecked(d.get("follow", True))
        q = d.get("q") or [4.5, 2.0, 3.0]
        self.q_street.setValue(q[0]), self.q_side.setValue(q[1]), self.q_rear.setValue(q[2])
        for k, c in self.reason_cb.items():
            c.setChecked(k in (d.get("reasons") or []))
        self._busy = False
        if d.get("verts"):
            self.set_vertices([tuple(p) for p in d["verts"]], d.get("edges"))
        else:
            self.make_rect()
        self._busy = True
        self.bt.setRowCount(0)
        self._busy = False
        self._bulk = True
        for b in d.get("buildings") or []:
            self.add_building(b)
        self._bulk = False
        self.north, self.north_on = float(d.get("north", 90.0)), bool(d.get("north_on", True))
        self._restore_unders(d.get("under") or {})
        self._motiv_user = bool(d.get("motivation"))
        if self._motiv_user:
            self._writing = True
            self.motiv.setPlainText(d["motivation"])
            self._writing = False
        self._after_edit()

    # ---- the report
    def report_resources(self):
        return {"plan": self.plan.snapshot()}

    def report_html(self):
        rd = getattr(self.win, "rd", {}) or {}
        an = self.result()
        t = lambda v: "yes" if v else "no"
        body = '<p style="font-size:11pt;"><b>%s</b>%s &nbsp;|&nbsp; stand area %.2f m2</p>' % (
            tb.esc(self.erf.text() or rd.get("details") or "Stand"), (" &nbsp;|&nbsp; " + tb.esc(self.zoning.text())) if self.zoning.text() else "", an["area"])
        body += '<p align="center"><img src="plan" width="620"></p>'
        body += '<p style="font-size:8pt; color:#555555;">Green: the area inside every building line. Red dashed line: the building lines.</p>'
        body += "<h3>Building lines</h3>" + tb.table(["Boundary", "Kind", "Building line m"],
                                                     [[self._edge_name(i), e["kind"], "%.2f" % e["sb"]] for i, e in enumerate(self.edges())], aligns=["left", "left", "right"])
        rows = []
        for b in an["buildings"]:
            if b["enc"]:
                for e in b["enc"]:
                    rows.append(([b["name"], "%s %s" % (e["kind"], self._edge_name(e["edge"])), "%.2f" % e["sb"], "%.2f" % e["dist"], "%.2f" % e["by"]], "#fde3e6"))
            else:
                rows.append((([b["name"], "all", "", "", "complies"]), "#e4f4ea"))
        body += "<h3>Buildings</h3>" + tb.table(["Building", "Building line", "Required m", "Distance m", "Over by m"], rows,
                                                 aligns=["left", "left", "right", "right", "right"])
        body += "<h3>Coverage and floor area ratio</h3>" + tb.table(
            ["Check", "Result", "Limit", "Complies"],
            [["Coverage", "%.1f %% (%.2f m2)" % (an["cov_pct"], an["cov_area"]), ("%.1f %%" % self.max_cov.value()) if self.max_cov.value() else "none", t(an["cov_ok"])],
             ["Floor area ratio", "%.2f (%.2f m2)" % (an["far"], self.current_floor_area()), ("%.2f" % self.max_far.value()) if self.max_far.value() else "none", t(an["far_ok"])]])
        mot = self.motiv.toPlainText().strip()
        if any(b["enc"] for b in an["buildings"]) and mot:
            body += "<h3>Departure motivation</h3><p>%s</p>" % tb.esc(mot).replace("\n", "<br>")
        return tb.report_doc_html("Building lines", "Building lines, coverage and floor area ratio", body, rd)

    def write_motivation_pdf(self, path):
        rd = getattr(self.win, "rd", {}) or {}
        body = "<p>%s</p>" % tb.esc(self.motiv.toPlainText()).replace("\n", "<br>")
        d, w = tb.write_pdf(path, tb.report_doc_html("Departure motivation", "Application for a departure from the building lines", body, rd), "Departure motivation")
        tb.print_doc(d, w)
