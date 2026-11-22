"""house placement follows north: the long wall faces north when the stand lets it; the arrow turns with the road side"""
import math
import site_engine as se


def test_conversions():
    for road in ("left", "top", "right", "bottom"):
        for deg in (0, 33, 90, 200, 300):
            v = se.north_screen_to_world(deg, road)
            back = se.north_world_to_screen(v, road) % 360
            assert abs(((back - deg + 180) % 360) - 180) < 1e-6, (road, deg, back)


def test_suggest_follows_north():
    st = se.default_state() if hasattr(se, "default_state") else None
    import site_services as ss
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    class W:
        pass
    pg = ss.SiteServicesPage(W())
    pg.set_stand([(0, 0), (20, 0), (20, 26), (0, 26)], "T", points=None, keep_buildings=False)
    res = {}
    for name, nv in (("north_along_y", (0.0, 1.0)), ("north_along_x", (1.0, 0.0))):
        pg.st["north_world"] = list(nv)
        o = se.suggest(pg.st)
        h = o["house"]
        long_axis_y = h.get("rot") == 90
        res[name] = long_axis_y
        print(name, "rot", h.get("rot"), "long wall faces north" if (long_axis_y == (nv[0] == 1.0)) else "long wall faces east/west")
    assert res["north_along_y"] is False and res["north_along_x"] is True      # north up the stand: the long axis runs across it (rot 0); north across: along it (rot 90)


if __name__ == "__main__":
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    test_conversions()
    test_suggest_follows_north()
    print("north ok")
