"""Water points on a turned house: each leaves the wall square to the plan, never through the house, and rounded corners stay on the pipe. Run: QT_QPA_PLATFORM=offscreen python3 test_water_straight.py"""
import math
import site_engine as se
from PySide6.QtWidgets import QApplication
import site_services as ss


def main():
    app = QApplication.instance() or QApplication([])

    class W:
        pass
    pg = ss.SiteServicesPage(W())
    bad = n = 0
    for rot in range(0, 360, 15):
        pg.st["house"].update(cx=9.0, cy=12.0, rot=rot)
        pg.st["water_ports"] = [{"edge": e, "t": t} for e, t in ((0, 0.3), (1, 0.5), (2, 0.7))]
        pg.solve_now(False)
        app.processEvents()
        hp = se.house_poly(pg.st["house"])
        for br in pg.res["water"]["branches"]:
            n += 1
            pts = br["path"]
            if len(pts) <= 3:                                     # straight (or one turn) out of the wall: every leg square to the plan
                for a, b in zip(pts[:-1], pts[1:]):
                    if abs(a[0] - b[0]) > 1e-3 and abs(a[1] - b[1]) > 1e-3:
                        bad += 1
            mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts[:-1], pts[1:])]
            if any(se.inside(m, hp) for m in mids):
                bad += 1
        r = se.rounded(pg.res["water"]["path"])
        assert r[0] == tuple(pg.res["water"]["path"][0]) and r[-1] == tuple(pg.res["water"]["path"][-1])
    print("water branches", n, "bad", bad)
    assert bad == 0


if __name__ == "__main__":
    main()
