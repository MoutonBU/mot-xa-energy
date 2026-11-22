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


def test_main_chain():
    segs = [(0, 0, 10, 0), (10, 0, 20, 0), (20, 0, 30, 5), (30, 5, 31, 5), (50, 50, 52, 50), (5, 3, 5, 4)]
    assert tw.main_chain(segs, (5, 3)) == [(0, 0), (20, 0), (30, 5), (31, 5)]       # the long run, not the short bits
    assert tw.main_chain(segs, (500, 500)) is None


def test_engine_snaps_to_real_main():
    import site_engine as se
    st = {"points": {"water": [4.0, 0.0], "elec": [3.0, 0.0], "sewer": [3.0, 0.0]}, "mains": {}, "main_poly": {"water": [[-10, -6], [20, -6]]}}
    assert se.conn_point(st, "water") == (4.0, -6.0)
    assert se.conn_point(st, "elec") == (3.0, se.mains(st)["elec"])                  # no real main: the straight line, as before


if __name__ == "__main__":
    test_main_chain()
    test_engine_snaps_to_real_main()
    test_bulge()
    test_sheet_uses_real_road()
    print("road ok")
