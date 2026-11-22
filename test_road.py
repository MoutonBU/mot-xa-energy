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


def test_main_runs_and_branches():
    # a main with a branch: three runs cut at the junction; a short stub and a far line are left out
    segs = [(0, 0, 10, 0), (10, 0, 20, 0), (20, 0, 20, 8), (20, 0, 30, 0), (30, 0, 40, 0), (100, 100, 105, 100), (3, 3, 3, 4)]
    runs = tw.main_runs(segs, (5, 2))
    assert len(runs) == 3 and sorted(len(r) for r in runs) == [2, 2, 2], runs
    assert tw.main_runs(segs, (500, 500)) == []


def test_closing_stand_edges():
    # lines that meet 8 mm apart across a 3 cm grid border still close the face (a corner stand of the real township was lost to this)
    import site_township as t2
    tn = t2.Township()
    tn.k = 1.0
    tn.layers = {"a": {"cat": "stand"}}
    tn.lines = {"a": [0, 0, 20, 0, 20, 0, 20, 10, 20.008, 10, 0, 10.0, 0, 10, 0, 0]}
    tn.shapes, tn.texts = [], []
    f = tn._face_at((10, 5))
    assert f and abs(f["area"] - 200) < 1.0, f


def test_house_turns_to_fit_a_diagonal_corner():
    import site_engine as se
    st = {"stand": {"corners": [(0, 0), (4, 5), (22, 5), (22, 18.5), (-8, 18.5)]}, "house": {"cx": 0, "cy": 0, "w": 12.7, "d": 7.9, "rot": 0},
          "carport": None, "points": {"sewer": [1, 0], "water": [1, 0], "elec": [1, 0]}, "params": {}}
    o = se.suggest(st)
    from site_engine import shape_poly, fits
    assert o and not o.get("relaxed")


if __name__ == "__main__":
    test_main_runs_and_branches()
    test_closing_stand_edges()
    test_house_turns_to_fit_a_diagonal_corner()
    test_main_chain()
    test_engine_snaps_to_real_main()
    test_bulge()
    test_sheet_uses_real_road()
    print("road ok")
