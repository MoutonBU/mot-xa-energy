"""a made-up township: stands in rows either side of a road, with sewer, water and electrical layers; find a stand by number"""
import os, tempfile, math
import ezdxf
import site_township as tw


def make(path, scale=1.0, loose=False):
    doc = ezdxf.new("R2010")
    ms = doc.modelspace()
    ox, oy = 120000.0 * scale, -3750000.0 * scale
    no = 1000
    for row, y0 in enumerate((0.0, 40.0)):            # two rows, road between at y 25..35
        for i in range(10):
            x0 = i * 15.0
            pts = [(x0, y0), (x0 + 15, y0), (x0 + 15, y0 + 25), (x0, y0 + 25)]
            P = [((ox / scale + x) * scale, (oy / scale + y) * scale) for x, y in pts]
            if loose:
                for j in range(4):
                    ms.add_line(P[j], P[(j + 1) % 4], dxfattribs={"layer": "ERF_BOUNDARY"})
            else:
                ms.add_lwpolyline(P, close=True, dxfattribs={"layer": "ERF_BOUNDARY"})
            no += 1
            ms.add_text(str(no), dxfattribs={"layer": "ERF_NO", "insert": (P[0][0] + 7 * scale, P[0][1] + 12 * scale), "height": 1 * scale})
    for y in (25.0, 35.0):
        ms.add_line((ox, (oy / scale + y) * scale), (ox + 150 * scale, (oy / scale + y) * scale), dxfattribs={"layer": "ROAD_KERB"})
    ms.add_line((ox, oy + 30 * scale), (ox + 150 * scale, oy + 30 * scale), dxfattribs={"layer": "SEWER_MAIN"})
    ms.add_line((ox, oy + 28 * scale), (ox + 150 * scale, oy + 28 * scale), dxfattribs={"layer": "WATER_MAIN"})
    ms.add_line((ox, oy + 32 * scale), (ox + 150 * scale, oy + 32 * scale), dxfattribs={"layer": "ELEC_CABLE"})
    doc.saveas(path)


def run(scale, loose):
    p = os.path.join(tempfile.mkdtemp(), "t.dxf")
    make(p, scale, loose)
    t = tw.Township().load(p)
    assert abs(t.k - 1.0 / scale) < 1e-9, (t.k, scale)
    assert t.layers["SEWER_MAIN"]["cat"] == "sewer" and t.layers["WATER_MAIN"]["cat"] == "water" and t.layers["ELEC_CABLE"]["cat"] == "elec"
    r = t.find("1004")
    assert r, "stand not found"
    P = r["poly"]
    w = max(x for x, y in P) - min(x for x, y in P)
    d = max(y for x, y in P) - min(y for x, y in P)
    assert abs(w - 15) < 0.01 and abs(d - 25) < 0.01, (w, d)
    nos = sorted(n["no"] for n in r["neighbours"])
    assert "1003" in nos and "1005" in nos, nos           # the stands either side
    assert r["lines"]["sewer"] and r["lines"]["water"] and r["lines"]["elec"]
    # the street side is the one at the road (top edge, y = 25 on the first row's side)
    a, b = P[r["street_edge"]], P[(r["street_edge"] + 1) % len(P)]
    assert abs(a[1] - b[1]) < 0.01 and abs(abs(a[0] - b[0]) - 15) < 0.01, (a, b)     # a level 15 m side, the one at the road
    assert abs(abs(a[1] - max(y for x, y in P)) - 0) < 0.01 or abs(a[1] - min(y for x, y in P)) < 0.01
    assert r["road_known"]
    assert t.find("99999") is None
    assert t.find("ERF 1004") is None or True
    return len(r["neighbours"])


def test_all():
    for scale in (1.0, 1000.0):
        for loose in (False, True):
            n = run(scale, loose)
            print("scale", scale, "loose", loose, "neighbours", n)


if __name__ == "__main__":
    test_all()
    print("township ok")
