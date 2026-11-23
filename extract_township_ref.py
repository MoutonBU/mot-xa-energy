"""Builds site_township_ref.py from the engineer / MCP township site plan (one big DXF): every stand's outline, number, street side, the stands beside it, the
electrical and water connection symbols, and the house type and carport as you placed them on it (in the stand's own frame: x along the street, y into the stand).
Run: python extract_township_ref.py "Untitled.dxf" "Blue Hills Ext 120"      (not part of the program; the program only reads site_township_ref.py)"""
import json
import math
import re
import sys
from collections import defaultdict

import site_engine as se
import site_township as tw


def base(layer):
    b = re.sub(r"^New_MCP_", "", layer)
    return re.sub(r"_Pen_No__\d+$", "", b).strip()


def build(path, name):
    T = tw.Township().load(path)
    k = T.k
    nums = sorted({s for s, x, y, l in T.texts if s.isdigit() and 3 <= len(s) <= 5 and "ERVEN_NUMBERS" in l})
    found = {}
    for no in nums:
        r = T.find(no)
        if r:
            found[no] = r
    house_layers = defaultdict(list)                            # type -> layers
    for lay in T.layers:
        b = base(lay)
        if b and b not in ("SITE_CARPORT",) and any(w in lay for w in ("(", "SQM", "ds181")) and lay.endswith("_Pen_No__1"):
            house_layers[b].append(lay)
    carport_layers = [l for l in T.layers if "SITE_CARPORT" in l]
    out = {}
    for no, r in found.items():
        P = r["poly"]
        n = len(P)
        frame, new = se.normalise_stand(P, r["street_edge"])
        bb = (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))

        def lines_in(layers):
            res = []
            for lay in layers:
                a = T.lines.get(lay, [])
                for i in range(0, len(a), 4):
                    p, q = (a[i] * k, -a[i + 1] * k), (a[i + 2] * k, -a[i + 3] * k)      # y negated, as Township.find hands the stands over
                    m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                    if bb[0] <= m[0] <= bb[2] and bb[1] <= m[1] <= bb[3] and tw.inside(m, P):
                        res.append((se.apply_frame(frame, p), se.apply_frame(frame, q)))
            return res

        def box(ls):
            xs = [p[0] for l in ls for p in l]
            ys = [p[1] for l in ls for p in l]
            ang = defaultdict(float)
            for (x1, y1), (x2, y2) in ls:
                L = math.hypot(x2 - x1, y2 - y1)
                ang[round(math.degrees(math.atan2(y2 - y1, x2 - x1)) % 90, 0)] += L
            rot = max(ang, key=ang.get) if ang else 0
            return {"cx": round((min(xs) + max(xs)) / 2, 2), "cy": round((min(ys) + max(ys)) / 2, 2), "w": round(max(xs) - min(xs), 2), "d": round(max(ys) - min(ys), 2),
                    "rot": 0 if rot in (0.0, 90.0) or rot < 2 or rot > 88 else rot}
        best = None
        for t, lays in house_layers.items():
            ls = lines_in(lays)
            if len(ls) >= 40 and (best is None or len(ls) > len(best[1])):
                best = (t, ls)
        cp = lines_in(carport_layers)
        conn = {}
        for kind, c in r.get("connections", {}).items():
            q = se.apply_frame(frame, c["pt"])
            conn[kind] = [round(q[0], 2), round(q[1], 2), c.get("label", ""), round(c["pt"][0], 2), round(c["pt"][1], 2)]
        if not 120 <= abs(tw._area(P)) <= 700:                  # not a house stand (open space, a block or an odd shape): left out
            continue
        L = math.hypot(new[1][0] - new[0][0], new[1][1] - new[0][1])
        out[no] = {"area": round(abs(tw._area(P)), 1), "poly": [[round(x, 2), round(y, 2)] for x, y in P], "street": r["street_edge"], "frontage": round(L, 2),
                   "conn": conn, "nb": sorted(o["no"] for o in r["neighbours"] if o.get("no"))[:24]}
        if best:
            out[no]["house"] = dict(box(best[1]), type=best[0])
        if len(cp) >= 8:
            out[no]["carport"] = box(cp)
    types = defaultdict(list)
    for v in out.values():
        h = v.get("house")
        if h and h["rot"] == 0:
            types[h["type"]].append((h["w"], h["d"]))
    houses = {t: {"w": round(sorted(a for a, b in v)[len(v) // 2], 2), "d": round(sorted(b for a, b in v)[len(v) // 2], 2), "count": len(v)} for t, v in types.items()}
    return {"name": name, "stands": out, "houses": houses}


def write_lines(path, name, out="site_township_lines.py"):
    """the road, sewer, water, electrical and stormwater lines of the whole site plan (y negated like the stands, whole centimetres, packed), so a stand of the built-in
    plan gets its road and services without the DXF being open"""
    import base64
    import struct
    import zlib
    T = tw.Township().load(path)
    k = T.k
    data = {}
    for lay, v in T.layers.items():
        a = T.lines.get(lay)
        if v["cat"] in ("road", "sewer", "water", "elec", "storm") and a:
            seg = data.setdefault(v["cat"], [])
            for i in range(0, len(a), 4):
                seg += [round(a[i] * k * 100), round(-a[i + 1] * k * 100), round(a[i + 2] * k * 100), round(-a[i + 3] * k * 100)]
    with open(out, "w", encoding="utf-8") as f:
        f.write('"""The road and service lines of the MCP site plan (written by extract_township_ref.write_lines; not edited by hand). Per category: zlib-compressed little-endian int32\ncentimetres, x1 y1 x2 y2 per line, y negated as in site_township_ref."""\n')
        f.write("LINES = {%r: {\n" % name)
        for cat, arr in sorted(data.items()):
            f.write("    %r: %r,\n" % (cat, base64.b64encode(zlib.compress(struct.pack("<%di" % len(arr), *arr), 9)).decode()))
        f.write("}}\n")
    return {c: len(v) // 4 for c, v in data.items()}


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "lines":
        print(write_lines(sys.argv[1], sys.argv[2]))
        sys.exit(0)
    d = build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Township")
    with open("site_township_ref.py", "w", encoding="utf-8") as f:
        f.write('"""Reference township read from the MCP site plan (the extraction script extract_township_ref.py; not edited by hand). Metres, survey coordinates; a stand\'s house and\ncarport are in the stand\'s own frame (x along the street, y into the stand)."""\n')
        f.write("TOWNSHIPS = {%r: %s}\n" % (d["name"], json.dumps(d["stands"], separators=(",", ":"))))
        f.write("HOUSES = {%r: %s}   # house type -> the box it covers on the site plan (with its patio / braai), and on how many stands\n" % (d["name"], json.dumps(d["houses"], separators=(",", ":"))))
    print(len(d["stands"]), "stands,", sum(1 for s in d["stands"].values() if "house" in s), "with a house,", sum(1 for s in d["stands"].values() if "carport" in s), "with a carport")
