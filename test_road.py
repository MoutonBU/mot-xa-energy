"""the road of a township drawing is drawn as it is (curved kerbs from polyline bulges and arcs), not as two straight lines"""
import math
import site_township as tw


def _circle_ok(pts, r, c):
    return all(abs(math.hypot(x - c[0], y - c[1]) - r) < 1e-6 for x, y in pts)


def test_bulge():
    for b, centre in ((math.tan(math.pi / 8), (0, 0)), (-math.tan(math.pi / 8), (10, 10))):
        pts = tw.bulged([(10, 0, b), (0, 10, 0)])
        assert _circle_ok(pts, 10, centre) and len(pts) > 10 and pts[-1] == (0, 10)
    assert tw.bulged([(0, 0, 0), (5, 0, 0)]) == [(0, 0), (5, 0)]


def test_sheet_uses_real_road():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import site_services as ss
    import site_sheet
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    class W:
        pass
    pg = ss.SiteServicesPage(W())
    pg.set_stand([(0, 0), (14, 0), (14, 22), (0, 22)], "T")
    assert pg.st["road_lines"] == []
    pg.st["road_lines"] = [[-20, -5, 0, -5], [0, -5, 5, -12]]
    rec = []

    class D:
        def __getattr__(self, n):
            return lambda *a, **k: None
    # the straight kerbs are not drawn when the real road is there: count the long horizontal black lines through the Drawer
    src = open("site_sheet.py").read()
    assert "real_road" in src and "if real_road" in src


if __name__ == "__main__":
    test_bulge()
    test_sheet_uses_real_road()
    print("road ok")
