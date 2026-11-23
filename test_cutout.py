"""The blue export frame is square to the paper (never 45 degrees), can be turned, and the DXF export is cut to it. QT_QPA_PLATFORM=offscreen python3 test_cutout.py"""
import math, os, tempfile
import ezdxf
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QPoint, Qt, QEvent
from PySide6.QtGui import QMouseEvent
import site_export, site_services as ss, site_sheet


def paper_edges(pg):
    sh = site_sheet.Sheet(1.0, (0, 0), (0, 0), pg.st["sheet"].get("road", "left"), pg.st["sheet"].get("turn", 0.0))
    q = [sh.pt(p) for p in pg.cutout_poly()]
    return [math.degrees(math.atan2(q[(i + 1) % 4].y() - q[i].y(), q[(i + 1) % 4].x() - q[i].x())) % 90.0 for i in range(4)]


def run():
    app = QApplication.instance() or QApplication([])

    class W:
        pass
    pg = ss.SiteServicesPage(W())
    pg.resize(1500, 900)
    pg.show()
    app.processEvents()
    pg.st["sheet"]["turn"] = 45.0                     # the plan itself is turned 45 degrees on the paper, as in the screenshot
    pg.st["house"].update(cx=9.0, cy=12.0)
    pg.solve_now(False)
    app.processEvents()
    for a in paper_edges(pg):
        assert min(a, 90.0 - a) < 1e-6, "default frame square to the paper: %s" % a
    (c, w, h, r) = pg.cutout_frame()
    assert r == 0.0 and w > 10 and h > 10
    # an old project: a plain rectangle in the stand's frame becomes a frame square to the paper holding it
    pg.st["cutout"] = [-5.0, -6.0, 25.0, 30.0]
    for a in paper_edges(pg):
        assert min(a, 90.0 - a) < 1e-6
    pg.st.pop("cutout")
    # turn it
    v = pg.view
    v.fit(); app.processEvents()
    g = v._cut_geom()
    assert v._cut_hit(g["rot"]) == ("rot",) and v._cut_hit(g["C"]) == ("move",)
    class E:
        def __init__(s, p, mod=Qt.KeyboardModifier.NoModifier): s.p, s.m = p, mod
        def position(s): return s.p
        def modifiers(s): return s.m
    frame0 = pg.cutout_frame()
    d = ("cut", ("rot",), frame0, g["rot"])
    ang = math.radians(20.0)
    rel = g["rot"] - g["C"]
    tgt = g["C"] + QPointF(rel.x() * math.cos(ang) - rel.y() * math.sin(ang), rel.x() * math.sin(ang) + rel.y() * math.cos(ang))
    v._cut_drag(E(tgt), d)
    assert abs(pg.cutout_frame()[3] - 20.0) < 0.1, pg.cutout_frame()
    for a in paper_edges(pg):
        pass
    # near a right angle it snaps
    ang = math.radians(1.0)
    tgt = g["C"] + QPointF(rel.x() * math.cos(ang) - rel.y() * math.sin(ang), rel.x() * math.sin(ang) + rel.y() * math.cos(ang))
    v._cut_drag(E(tgt), d)
    assert pg.cutout_frame()[3] == 0.0
    # resize by the right edge keeps the left edge
    frame0 = pg.cutout_frame()
    g = v._cut_geom()
    hw = g["w"] / 2 * v.sh.s
    right = g["C"] + g["u"] * hw
    assert v._cut_hit(right) == ("edge", 1, 0), v._cut_hit(right)
    v._cut_drag(E(right + g["u"] * 30.0), ("cut", ("edge", 1, 0), frame0, right))
    (c1, w1, h1, r1) = pg.cutout_frame()
    assert abs(w1 - (frame0[1] + 30.0 / v.sh.s)) < 0.05 and abs(h1 - frame0[2]) < 0.01
    # export with a turned frame: written, and everything lies inside the frame
    pg.st["cutout"] = {"c": list(frame0[0]), "w": frame0[1], "h": frame0[2], "rot": 25.0}
    path = os.path.join(tempfile.mkdtemp(), "plan.dxf")
    site_export.build_sheet(pg, path)
    doc = ezdxf.readfile(path)
    assert len(list(doc.modelspace())) > 50
    print("cutout ok")


if __name__ == "__main__":
    run()
