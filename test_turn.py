"""the plan can be turned on the page (any angle); a township stand is squared up and the north arrow follows"""
import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import site_engine as se
import site_sheet as sh


def test_square_turn():
    # a rectangle turned 30 degrees: squaring turns it back
    a = math.radians(30)
    R = [(0, 0), (20, 0), (20, 10), (0, 10)]
    P = [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in R]
    t = sh.square_turn(P, "top")
    assert abs(((t + 30 + 45) % 90) - 45) < 0.2, t
    assert sh.square_turn(R, "left") == 0.0


def test_sheet_roundtrip_and_extent():
    s = sh.Sheet(5.0, (3, 4), (800, 600), "left", 37.0)
    for q in ((0, 0), (10, -3), (-4, 12)):
        b = s.inv(s.pt(q))
        assert abs(b[0] - q[0]) < 1e-9 and abs(b[1] - q[1]) < 1e-9
    w, h = sh.page_extent(0, 0, 10, 20, "top", 0.0)
    assert abs(w - 10) < 1e-9 and abs(h - 20) < 1e-9
    w, h = sh.page_extent(0, 0, 10, 20, "top", 90.0)
    assert abs(w - 20) < 1e-6 and abs(h - 10) < 1e-6


def test_north_follows_turn():
    v = (0.3, 0.954)
    for road in ("left", "top", "right", "bottom"):
        for turn in (0, 25, -40, 90):
            d = se.north_world_to_screen(v, road, turn)
            w = se.north_screen_to_world(d, road, turn)
            assert abs(w[0] - v[0] / math.hypot(*v)) < 1e-6 and abs(w[1] - v[1] / math.hypot(*v)) < 1e-6
    assert abs((se.north_world_to_screen(v, "top", 30) - se.north_world_to_screen(v, "top", 0)) - 30) < 1e-6


if __name__ == "__main__":
    test_square_turn()
    test_sheet_roundtrip_and_extent()
    test_north_follows_turn()
    print("turn ok")
