"""the township import must not depend on how one office drew its sheet: odd layer names, everything on layer 0, rotated layouts, mm or m, labels with
prefixes, MTEXT, boundaries as closed shapes or as long crossing lines"""
import math, os, tempfile
import ezdxf
import site_township as tw


def site(path, layer="0", rot=0.0, scale=1.0, label="{n}", mtext=False, loose=False, ox=250000.0, oy=-3600000.0, roads=True):
    doc = ezdxf.new("R2010")
    ms = doc.modelspace()
    c, s_ = math.cos(math.radians(rot)), math.sin(math.radians(rot))

    def T(x, y):
        return ((ox + x * c - y * s_) * scale, (oy + x * s_ + y * c) * scale)
    no = 500
    for row, y0 in enumerate((0.0, 40.0)):
        for i in range(8):
            x0 = i * 14.0
            pts = [T(x0, y0), T(x0 + 14, y0), T(x0 + 14, y0 + 22), T(x0, y0 + 22)]
            if loose:                                              # long lines that run past each other
                for a, b in ((T(x0 - 3, y0), T(x0 + 17, y0)), (T(x0 + 14, y0 - 3), T(x0 + 14, y0 + 25)), (T(x0 - 3, y0 + 22), T(x0 + 17, y0 + 22)), (T(x0, y0 - 3), T(x0, y0 + 25))):
                    ms.add_line(a, b, dxfattribs={"layer": layer})
            else:
                ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
            no += 1
            p = T(x0 + 7, y0 + 11)
            txt = label.format(n=no)
            if mtext:
                ms.add_mtext("{\\fArial|b0;" + txt + "}", dxfattribs={"layer": "TXT", "insert": p, "char_height": 1.0 * scale})
            else:
                ms.add_text(txt, dxfattribs={"layer": "TXT", "insert": p, "height": 1.0 * scale})
    if roads:
        for y in (22.0, 40.0):
            ms.add_line(T(-5, y), T(125, y), dxfattribs={"layer": "ROADS"})
    doc.saveas(path)


def check(**kw):
    p = os.path.join(tempfile.mkdtemp(), "s.dxf")
    site(p, **kw)
    t = tw.Township().load(p)
    r = t.find("505")
    assert r, kw
    P = r["poly"]
    a = abs(tw._area(P))
    assert abs(a - 14 * 22) < 1.0, (kw, a)
    nos = {n["no"] for n in r["neighbours"]}
    assert "504" in nos and "506" in nos, (kw, nos)
    return r


def test_all():
    for kw in ({"layer": "0"}, {"layer": "XYZ_LINES"}, {"layer": "SG", "rot": 33.0}, {"layer": "0", "scale": 1000.0}, {"layer": "A$C123", "rot": 90.0, "label": "ERF {n}"},
               {"layer": "0", "mtext": True}, {"layer": "0", "loose": True}, {"layer": "0", "loose": True, "rot": 17.0, "scale": 1000.0, "label": "Erf {n}"},
               {"layer": "0", "label": "{n}/0"}, {"layer": "BOUNDARY", "roads": False}):
        check(**kw)
        print("ok", kw)


if __name__ == "__main__":
    test_all()
    print("township any ok")
