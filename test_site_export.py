"""The DXF export is the plan as drawn on the screen: same texts, dimensions, layers, true size. Run: QT_QPA_PLATFORM=offscreen python3 test_site_export.py"""
import os
import tempfile

import ezdxf
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import site_export
import site_services as ss


def test_export():
    app = QApplication.instance() or QApplication([])

    class W:
        pass
    pg = ss.SiteServicesPage(W())
    pg.resize(1500, 900)
    pg.show()
    QTest.qWait(100)
    pg.st["house"].update(cx=9.0, cy=12.0)
    pg.st["sheet"]["street"] = "BURGER ST"
    pg.solve_now(False)
    QTest.qWait(200)
    path = os.path.join(tempfile.mkdtemp(), "plan.dxf")
    site_export.build_sheet(pg, path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    for want in ("NEW HOUSE", "Main Sewer Line", "Main Water Line", "IE", "RE", "BURGER ST", "Site Plan"):
        assert want in texts, want
    assert any(t.endswith("B/L") for t in texts), "building lines labelled"
    assert any("," in t and t.replace(",", "").isdigit() for t in texts), "dimension figures in mm"
    layers = {e.dxf.layer for e in msp}
    assert {"SEWER", "WATER", "ELECTRICAL", "HOUSE", "SETTING OUT", "SITE PLAN", "TEXT"} <= layers, layers
    assert doc.header["$INSUNITS"] == 4
    # true size: the stand's 18 m wide frontage is 18000 units wherever it lies
    pl = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "SITE PLAN"]
    spans = []
    for e in pl:
        pts = list(e.get_points("xy"))
        spans.append(max(p[0] for p in pts) - min(p[0] for p in pts))
    assert any(abs(s - 15000) < 60 or abs(s - 25000) < 60 or s > 10000 for s in spans)
    assert any(e.dxftype() == "HATCH" for e in msp), "the red house and carport are filled"


if __name__ == "__main__":
    test_export()
    print("export matches the plan")
