"""The plan as a DXF at true size: 1 drawing unit = 1 mm (INSUNITS = millimetres), so it opens at 1:1 in any CAD program and plots at 1:200 as drawn.
Layers carry the colours of the sheet."""
import math

import ezdxf

# layer: (AutoCAD colour index, true colour)
LAYERS = {
    "STAND": (7, None), "BUILDING LINES": (8, None), "HOUSE": (1, None), "CARPORT": (7, None),
    "SEWER": (30, (173, 71, 10)), "WATER": (5, (15, 130, 255)), "ELECTRICAL": (2, (219, 209, 20)),
    "POINTS": (7, None), "TEXT": (7, None), "UNDERLAY": (9, None),
}


def build(st, res, path, scale_text="1:200"):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, (aci, tc) in LAYERS.items():
        ly = doc.layers.add(name)
        ly.color = aci
        if tc:
            ly.rgb = tc
    msp = doc.modelspace()
    M = lambda p: (p[0] * 1000.0, p[1] * 1000.0)

    def poly(pts, layer, close=True, **kw):
        msp.add_lwpolyline([M(p) for p in pts], close=close, dxfattribs=dict(layer=layer, **kw))

    def text(t, p, h, layer="TEXT"):
        e = msp.add_text(t, height=h * 1000.0, dxfattribs={"layer": layer})
        e.set_placement(M(p))

    poly(st["stand"]["corners"], "STAND", lineweight=35)
    for a, b, c, d, *_ in st.get("underlay") or []:
        msp.add_line(M((a, b)), M((c, d)), dxfattribs={"layer": "UNDERLAY"})
    if res.get("carport"):
        poly(res["carport"], "CARPORT")
        text("CARPORT", (sum(q[0] for q in res["carport"]) / 4 - 1.0, sum(q[1] for q in res["carport"]) / 4), 0.5)
    if res.get("house"):
        h = res["house"]
        poly(h, "HOUSE", lineweight=35)
        text("NEW HOUSE", (sum(q[0] for q in h) / len(h) - 1.5, sum(q[1] for q in h) / len(h)), 0.75)
        for nm, q in res.get("marks") or []:
            text(nm, q, 0.4)
    for key, layer in (("sewer", "SEWER"), ("water", "WATER"), ("elec", "ELECTRICAL")):
        r = res.get(key)
        if not r:
            continue
        paths = [r["path"]] + [b for b in (r.get("branches") or [])] + [b for b in (r.get("stubs") or [])]
        for pth in paths:
            if len(pth) > 1:
                poly(pth, layer, close=False, lineweight=25)
        for n in r.get("nodes") or []:
            text(n.get("label") or n["kind"], n["pt"], 0.4, layer)
            msp.add_circle(M(n["pt"]), 150, dxfattribs={"layer": "POINTS"})
    for k, p in (st.get("points") or {}).items():
        msp.add_circle(M(p), 200, dxfattribs={"layer": "POINTS"})
    x = [p[0] for p in st["stand"]["corners"]]
    y = [p[1] for p in st["stand"]["corners"]]
    text("Site Plan  " + scale_text, (min(x), min(y) - 4.0), 0.9)
    doc.saveas(path)
    return path
