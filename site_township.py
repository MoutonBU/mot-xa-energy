"""A whole township (or SG sheet) drawing for House placing: read it once, then type a stand number and get that stand, the stands beside it and the sewer,
water, electrical and stormwater lines around it, all in metres. No Qt here (the page drives it), so it can be tested without a window.

Layers are told apart by name (sewer / swr / san ..., water / wtr ..., elec / power / cable ..., storm ..., road / kerb ..., erf / stand / cadastre ...) and the
guess can be changed by the person before the stand is searched for."""
import math
import re

import site_dxf

CATS = ("stand", "road", "sewer", "water", "elec", "storm", "other", "off")
CAT_NAMES = {"stand": "Stand boundaries", "road": "Roads and kerbs", "sewer": "Sewer", "water": "Water", "elec": "Electrical", "storm": "Stormwater",
             "other": "Other lines", "off": "Leave out"}
WORDS = (("sewer", ("sewer", "swr", "sanit", "sewage", "foul", "manhole", "sew_", "_sew", "-sew", "sew-", "sew ")),
         ("storm", ("storm", "drain", "culvert", "swale", "sw_", "_sw", "kerb inlet", "catchpit", "channel")),
         ("water", ("water", "wtr", "wat_", "_wat", "-wat", "wat-", "potable", "hydrant", "w.con", "wcon")),
         ("elec", ("elec", "power", "cable", "eskom", "lv_", "mv_", "_lv", "_mv", "lighting", "transf", "ecs")),
         ("road", ("road", "kerb", "curb", "street", "carriageway", "pavement", "verge", "asphalt")),
         ("stand", ("erf", "erven", "stand", "cadast", "parcel", "boundar", "prop", "lot", "cad", "sg_", "_sg", "diagram", "portion", "ptn")))


def bulged(vs, closed=False):
    """polyline vertices (x, y, bulge) -> points, with every arc segment (bulge <> 0) cut into short straight pieces (about 5 degrees each)"""
    out = []
    n = len(vs)
    for i in range(n):
        x0, y0, b = vs[i]
        out.append((x0, y0))
        if not b or (i == n - 1 and not closed):
            continue
        x1, y1 = vs[(i + 1) % n][0], vs[(i + 1) % n][1]
        ch = math.hypot(x1 - x0, y1 - y0)
        if ch < 1e-9:
            continue
        th = 4 * math.atan(b)                                        # the angle the arc turns through (signed)
        r = ch / (2 * math.sin(abs(th) / 2))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        off = ch / 2 * (1 - b * b) / (2 * b)                         # the centre, along the chord's left-hand normal (negative when the arc turns clockwise)
        cx, cy = mx - (y1 - y0) / ch * off, my + (x1 - x0) / ch * off
        a_s = math.atan2(y0 - cy, x0 - cx)
        k = max(2, int(abs(th) / (math.pi / 36)) + 1)
        for q in range(1, k):
            a = a_s + th * q / k
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def main_chain(segs, ref, reach=40.0, min_len=12.0):
    """the main service line near a point: the lines (x1, y1, x2, y2) are joined end to end into runs, and the longest run that comes within `reach` of `ref`
    (closest first, then longest) is returned as a list of points, or None. Short bits (symbols, house connections) are ignored by min_len."""
    key = lambda x, y: (round(x * 20), round(y * 20))
    par = {}

    def find(a):
        while par.setdefault(a, a) != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    pts = {}
    for x1, y1, x2, y2 in segs:
        a, b = key(x1, y1), key(x2, y2)
        if a == b:
            continue
        pts[a], pts[b] = (x1, y1), (x2, y2)
        par[find(a)] = find(b)
    comps = {}
    for x1, y1, x2, y2 in segs:
        a, b = key(x1, y1), key(x2, y2)
        if a != b:
            comps.setdefault(find(a), []).append((a, b))
    best = None
    for c, es in comps.items():
        tot = sum(math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]) for a, b in es)
        if tot < min_len:
            continue
        d = min(_seg_dist(ref, pts[a], pts[b]) for a, b in es)
        if d > reach:
            continue
        sc = (round(d / 8.0), -tot)
        if best is None or sc < best[0]:
            best = (sc, es)
    if not best:
        return None
    adj = {}
    for a, b in best[1]:
        w = math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))

    def far(s0):
        dist, prev, st_ = {s0: 0.0}, {}, [s0]
        while st_:
            u = st_.pop()
            for v, w in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + w
                    prev[v] = u
                    st_.append(v)
        e = max(dist, key=dist.get)
        return e, prev
    a0, _ = far(next(iter(adj)))
    a1, prev = far(a0)
    path = [a1]
    while path[-1] != a0:
        path.append(prev[path[-1]])
    out = [pts[k] for k in path]
    o2 = [out[0]]                                              # drop points on a straight stretch
    for i in range(1, len(out) - 1):
        a, b, c = o2[-1], out[i], out[i + 1]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-4:
            o2.append(b)
    o2.append(out[-1])
    return o2


def guess_category(layer):
    n = str(layer).lower()
    if n in ("0", "defpoints") or "dim" in n or "text" in n or "title" in n or "frame" in n or "grid" in n:
        return "off" if n in ("defpoints",) or "dim" in n or "title" in n or "frame" in n else "other"
    for cat, ws in WORDS:
        if any(w in n for w in ws):
            return cat
    return "other"


def rgb_category(rgb):
    """what a true (RGB) colour stands for: yellow = electrical, blue / cyan = water, orange / brown = sewer, pink / magenta = stormwater, green = stormwater"""
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    hi, lo = max(r, g, b), min(r, g, b)
    if hi - lo < 40:
        return "other"                                           # grey, black, white
    d = float(hi - lo)
    if hi == r:
        h = (60 * ((g - b) / d)) % 360
    elif hi == g:
        h = 60 * ((b - r) / d) + 120
    else:
        h = 60 * ((r - g) / d) + 240
    if 45 <= h < 70:
        return "elec"
    if 170 <= h < 260:
        return "water"
    if 10 <= h < 45:
        return "sewer"
    if h >= 290 or h < 10:
        return "storm"
    if 70 <= h < 170:
        return "storm"
    return "other"


def colour_category(cols):
    """what a layer is, from the AutoCAD colour its lines mostly have: yellow = electrical, blue / cyan = water, brown / orange = sewer, green = stormwater"""
    if not cols:
        return "other"
    c = max(cols, key=cols.get)
    if isinstance(c, str):                                       # "rgb:<number>" a true colour
        return rgb_category(int(c[4:]))
    if c in (6, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219):
        return "storm"
    if c == 2 or 50 <= c <= 59:
        return "elec"
    if c in (4, 5, 140, 141, 150, 151, 160, 161) or 130 <= c <= 179:
        return "water"
    if 10 <= c <= 49:                                            # browns and oranges
        return "sewer"
    if c in (3, 92, 93, 94, 95, 96) or 80 <= c <= 109:
        return "storm"
    return "other"


def stand_no(text):
    """the stand number a text says (2155, ERF 2155, Erf 2155/0, Stand 12, Lot 12), or None"""
    m = re.match(r"^(?:ERF|ERVEN|ERVEN NO|STAND|LOT|SITE|PLOT|NO\.?)?\s*[:#.-]?\s*(\d{1,6})(?:\s*/\s*\d+)?$", str(text).strip().upper())
    return m.group(1) if m else None


def clean_text(t):
    """plain text out of a drawing text (MTEXT codes removed)"""
    t = str(t)
    t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t)
    t = t.replace("\\P", " ").replace("\\~", " ").replace("{", "").replace("}", "").replace("%%c", "")
    return " ".join(t.split())


def _area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def inside(pt, poly):
    x, y = pt
    c = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-12) + a[0]:
            c = not c
    return c


def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy or 1e-12
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


class Township:
    NORTH = (0.0, -1.0)         # where north points in the coordinates find() hands over
    def __init__(self):
        self.layers = {}            # name -> {"n": entity count, "cat": category}
        self.lines = {}             # layer -> array('d') x1 y1 x2 y2 ... in drawing units
        self.shapes = []            # closed outlines: {"layer", "pts" (drawing units), "bbox"}
        self.texts = []             # (clean text, x, y, layer) in drawing units
        self.text_h = []            # the heights of those texts (drawing units), for guessing the unit
        self.k = 1.0                # metres per drawing unit
        self.path = ""

    # ---- reading
    def load(self, path, progress=None):
        path = site_dxf.dwg_to_dxf(path)
        import ezdxf
        try:
            doc = ezdxf.readfile(path)
        except Exception:
            from ezdxf import recover
            doc, _aud = recover.readfile(path)
        self.path = path
        u = int(doc.header.get("$INSUNITS", 0) or 0)
        unit = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}.get(u)
        self.lines, self.shapes, self.texts, self.layers = {}, [], [], {}
        self.text_h = []
        self.colours = {}                                        # layer -> {AutoCAD colour number: lines}
        self.marks = []                                          # small filled triangles and boxes (connection symbols): {"pts", "layer", "col"}
        lay_col = {}
        try:
            for L in doc.layers:
                lay_col[L.dxf.name] = abs(int(L.dxf.color))
        except Exception:
            pass
        cnt = [0]

        def paint(e, lay):
            try:
                c = int(e.dxf.color)
            except Exception:
                c = 256
            if c in (0, 256):
                c = lay_col.get(lay, 7)
            try:
                if e.dxf.hasattr("true_color") and int(e.dxf.true_color):
                    c = "rgb:%d" % (int(e.dxf.true_color) & 0xFFFFFF)
            except Exception:
                pass
            d = self.colours.setdefault(lay, {})
            d[c] = d.get(c, 0) + 1

        def add_lines(lay, pts, closed=False):
            arr = self.lines.setdefault(lay, [])
            n = len(pts)
            for i in range(n - 1 + (1 if closed else 0)):
                a, b = pts[i], pts[(i + 1) % n]
                arr.extend((a[0], a[1], b[0], b[1]))

        def walk(ents, depth=0, over=None):
            for e in ents:
                t = e.dxftype()
                try:
                    lay = over or e.dxf.layer
                    cnt[0] += 1
                    if t in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"):
                        paint(e, lay)
                    if t in ("SOLID", "TRACE", "3DFACE") and len(self.marks) < 60000:
                        vs = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3] if t != "3DFACE" else [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3]
                        pts = [(v.x, v.y) for v in vs]
                        try:
                            c = int(e.dxf.color)
                        except Exception:
                            c = 256
                        if c in (0, 256):
                            c = lay_col.get(lay, 7)
                        u = []
                        for q in pts:                              # a triangle repeats a corner
                            if not u or q != u[-1]:
                                u.append(q)
                        if len(u) > 1 and u[0] == u[-1]:
                            u.pop()
                        self.marks.append({"pts": u, "layer": lay, "col": c})
                        paint(e, lay)
                    elif t == "HATCH" and len(self.marks) < 60000:
                        for hp in e.paths:
                            if hasattr(hp, "vertices") and 3 <= len(hp.vertices) <= 4:
                                try:
                                    c = int(e.dxf.color)
                                except Exception:
                                    c = 256
                                if c in (0, 256):
                                    c = lay_col.get(lay, 7)
                                self.marks.append({"pts": [(q[0], q[1]) for q in hp.vertices], "layer": lay, "col": c})
                    if progress and cnt[0] % 20000 == 0:
                        progress(cnt[0])
                    if t == "LINE":
                        self.lines.setdefault(lay, []).extend((e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))
                    elif t == "LWPOLYLINE":
                        pts = bulged([(p[0], p[1], p[2]) for p in e.get_points("xyb")], bool(e.closed))
                        if len(pts) < 2:
                            continue
                        if e.closed and len(pts) >= 3:
                            self.shapes.append({"layer": lay, "pts": pts})
                        add_lines(lay, pts, bool(e.closed))
                    elif t == "POLYLINE" and not e.is_polygon_mesh:
                        pts = bulged([(v.dxf.location.x, v.dxf.location.y, v.dxf.bulge if v.dxf.hasattr("bulge") else 0.0) for v in e.vertices], bool(e.is_closed))
                        if len(pts) < 2:
                            continue
                        if e.is_closed and len(pts) >= 3:
                            self.shapes.append({"layer": lay, "pts": pts})
                        add_lines(lay, pts, bool(e.is_closed))
                    elif t in ("ARC", "CIRCLE"):
                        c, r = e.dxf.center, e.dxf.radius
                        a0, a1 = (math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)) if t == "ARC" else (0.0, 2 * math.pi)
                        if a1 <= a0:
                            a1 += 2 * math.pi
                        n = max(6, int((a1 - a0) / (math.pi / 36)))
                        add_lines(lay, [(c.x + r * math.cos(a0 + (a1 - a0) * q / n), c.y + r * math.sin(a0 + (a1 - a0) * q / n)) for q in range(n + 1)])
                    elif t in ("TEXT", "MTEXT"):
                        tx = e.dxf.text if t == "TEXT" else e.text
                        s = clean_text(tx)
                        if s:
                            self.texts.append((s, e.dxf.insert.x, e.dxf.insert.y, lay))
                            try:
                                self.text_h.append(float(e.dxf.height if t == "TEXT" else e.dxf.char_height))
                            except Exception:
                                pass
                    elif t == "INSERT" and depth < 3:
                        walk(e.virtual_entities(), depth + 1, lay if over is None and e.dxf.layer not in ("0",) else over)
                except Exception:
                    continue
        walk(doc.modelspace())
        if not self.lines and not self.shapes:
            for lay in doc.layouts:
                if lay.name != "Model":
                    walk(lay)
        if not self.lines and not self.shapes:
            raise ValueError("No lines were found in this drawing. Explode blocks / xrefs or save it as plain lines and polylines.")
        for s in self.shapes:
            xs, ys = [p[0] for p in s["pts"]], [p[1] for p in s["pts"]]
            s["bbox"] = (min(xs), min(ys), max(xs), max(ys))
        for lay in set(self.lines) | {s["layer"] for s in self.shapes} | {t[3] for t in self.texts}:
            cat = guess_category(lay)
            if cat == "other" and not any(w in lay.lower() for w in ("(", "sqm", "patio", "braai", "carport", "house", "pond")):                                   # the layer name says nothing: go by the colour the lines are drawn in
                cat = colour_category(self.colours.get(lay, {}))
            self.layers[lay] = {"n": len(self.lines.get(lay, ())) // 4, "cat": cat}
        self.k = self._units(unit)
        self._index = None
        return self

    def _units(self, unit):
        """metres per drawing unit: from the drawing's setting if it is believable, else the one that makes the closed shapes the size of stands"""
        areas = sorted(abs(_area(s["pts"])) for s in self.shapes if len(s["pts"]) >= 3)[:200000]
        cands = [k for k in (unit, 1.0, 0.001, 0.01, 0.3048) if k]
        loop_areas = {}
        if len(areas) < 20:                                      # loose boundary lines: join a sample of them to see what size the outlines come to
            segs = []
            for lay, v in self.layers.items():
                arr = self.lines.get(lay)
                if arr and v["cat"] in ("stand", "other") and len(segs) < 4000:
                    segs += [((arr[i], arr[i + 1]), (arr[i + 2], arr[i + 3])) for i in range(0, min(len(arr), 4 * 3000), 4)]
            for k in cands:
                loop_areas[k] = [abs(_area(lp)) for lp in site_dxf._join(segs, 0.05 / k)]

        def score(k):
            ar = loop_areas.get(k) if loop_areas else areas
            if not ar:
                return 0
            return sum(1 for a in ar if 60 <= a * k * k <= 6000) / len(ar)
        if unit and score(unit) >= 0.1:                          # the drawing says what its unit is, and the shapes agree
            return unit
        if max([score(k) for k in cands] or [0]) < 0.05 and self.text_h:   # no usable outlines to measure: the writing is usually 0.3 to 6 m high on the ground
            mh = sorted(self.text_h)[len(self.text_h) // 2]
            ok = [k for k in cands if 0.3 <= mh * k <= 6.0]
            if ok:
                return unit if unit in ok else max(ok)
        return max(cands, key=lambda k: (round(score(k), 2), k == unit, k == 1.0))

    def set_categories(self, mapping):
        for lay, cat in mapping.items():
            if lay in self.layers and cat in CATS:
                self.layers[lay]["cat"] = cat
        self._index = None

    def cat_of(self, lay):
        return self.layers.get(lay, {}).get("cat", "other")

    # ---- the stands
    def _stand_shapes(self):
        """every closed outline of stand size on the stand layers (or on any layer when none is a stand layer), with its area in m2"""
        if getattr(self, "_index", None) is not None:
            return self._index
        k2 = self.k * self.k
        stand_layers = {l for l, v in self.layers.items() if v["cat"] == "stand"}
        out = []
        for s in self.shapes:
            if stand_layers and s["layer"] not in stand_layers:
                continue
            if not stand_layers and self.cat_of(s["layer"]) == "off":
                continue
            a = abs(_area(s["pts"])) * k2
            if 25 <= a <= 60000:
                out.append({"pts": s["pts"], "bbox": s["bbox"], "area": a, "layer": s["layer"]})
        self._index = out
        return out

    def _from_lines(self, pt, reach=80.0):
        """stand outlines made of loose lines on the stand layers, around a point (in drawing units): joined end to end"""
        r = reach / self.k
        segs = []
        for lay, v in self.layers.items():
            if v["cat"] != "stand":
                continue
            arr = self.lines.get(lay)
            if not arr:
                continue
            for i in range(0, len(arr), 4):
                x1, y1, x2, y2 = arr[i], arr[i + 1], arr[i + 2], arr[i + 3]
                if min(x1, x2) > pt[0] + r or max(x1, x2) < pt[0] - r or min(y1, y2) > pt[1] + r or max(y1, y2) < pt[1] - r:
                    continue
                segs.append(((x1, y1), (x2, y2)))
        loops = site_dxf._join(segs, 0.05 / self.k)
        out = []
        for lp in loops:
            a = abs(_area(lp)) * self.k * self.k
            if 25 <= a <= 60000:
                xs, ys = [p[0] for p in lp], [p[1] for p in lp]
                out.append({"pts": lp, "bbox": (min(xs), min(ys), max(xs), max(ys)), "area": a, "layer": "lines"})
        return out

    def sample_numbers(self, n=8):
        """a few stand numbers that are written in the drawing (to show when the one typed is not there)"""
        seen, out = set(), []
        for s_, x, y, lay in self.texts:
            sn = stand_no(s_)
            if sn and 2 <= len(sn) <= 6 and sn not in seen and self.cat_of(lay) != "off":
                seen.add(sn)
                out.append(sn)
                if len(out) >= n:
                    break
        return out

    def labels_for(self, number):
        """the texts that are this stand number (the whole text, or one word of it such as ERF 2155)"""
        num = stand_no(number) or str(number).strip().upper()
        if not num:
            return []
        pat = re.compile(r"(?<![\w/.])" + re.escape(num) + r"(?![\w/])")
        out = []
        for s, x, y, lay in self.texts:
            if self.cat_of(lay) == "off":
                continue
            u = s.upper()
            if u == num or stand_no(u) == num or (pat.search(u) and len(u) <= len(num) + 16):
                out.append((s, x, y, lay))
        return out

    def _seg_cache(self, pt, reach=130.0):
        """the stand-layer line segments round a point, in metres (kept for the next stand beside it)"""
        c = getattr(self, "_sc", None)
        k = self.k
        if c and abs(c[0][0] - pt[0] * k) < reach * 0.4 and abs(c[0][1] - pt[1] * k) < reach * 0.4:
            return c[1]
        segs = []
        r = reach / k
        has_stand = any(v["cat"] == "stand" and self.lines.get(l) for l, v in self.layers.items())
        use = ("stand",) if has_stand else ("other", "road", "stand")
        for lay, v in self.layers.items():
            if v["cat"] not in use:
                continue
            arr = self.lines.get(lay)
            if not arr:
                continue
            for i in range(0, len(arr), 4):
                x1, y1, x2, y2 = arr[i], arr[i + 1], arr[i + 2], arr[i + 3]
                if min(x1, x2) > pt[0] + r or max(x1, x2) < pt[0] - r or min(y1, y2) > pt[1] + r or max(y1, y2) < pt[1] - r:
                    continue
                if abs(x2 - x1) + abs(y2 - y1) > 1e-9:
                    segs.append((x1 * k, y1 * k, x2 * k, y2 * k))
        self._sc = ((pt[0] * k, pt[1] * k), segs)
        return segs

    def _face_at(self, pt):
        """the smallest closed area round a point, made from stand-layer lines that cross, run past each other or only nearly meet (boundaries drawn as long
        lines): the lines are cut where they cross, dead ends are dropped, and the area's edge is walked round. -> {"pts" (drawing units), "area" (m2)} or None"""
        k = self.k
        P = (pt[0] * k, pt[1] * k)
        segs = [sg for sg in self._seg_cache(pt) if min(sg[0], sg[2]) < P[0] + 70 and max(sg[0], sg[2]) > P[0] - 70 and min(sg[1], sg[3]) < P[1] + 70 and max(sg[1], sg[3]) > P[1] - 70]
        if len(segs) < 3:
            return None
        tol = 0.08
        cuts = [[0.0, 1.0] for _ in segs]
        n = len(segs)
        for i in range(n):
            ax, ay, bx, by = segs[i]
            for j in range(i + 1, n):
                cx, cy, dx, dy = segs[j]
                if max(ax, bx) + tol < min(cx, dx) or max(cx, dx) + tol < min(ax, bx) or max(ay, by) + tol < min(cy, dy) or max(cy, dy) + tol < min(ay, by):
                    continue
                r1x, r1y, r2x, r2y = bx - ax, by - ay, dx - cx, dy - cy
                den = r1x * r2y - r1y * r2x
                if abs(den) < 1e-12:
                    continue
                t = ((cx - ax) * r2y - (cy - ay) * r2x) / den
                u = ((cx - ax) * r1y - (cy - ay) * r1x) / den
                l1, l2 = math.hypot(r1x, r1y), math.hypot(r2x, r2y)
                e1, e2 = tol / l1, tol / l2
                if -e1 <= t <= 1 + e1 and -e2 <= u <= 1 + e2:
                    cuts[i].append(min(1.0, max(0.0, t)))
                    cuts[j].append(min(1.0, max(0.0, u)))
        # the graph: vertices on a 2 cm grid
        vid = {}
        pts = []

        def vert(x, y):
            key = (round(x / 0.02), round(y / 0.02))
            if key not in vid:
                vid[key] = len(pts)
                pts.append((x, y))
            return vid[key]
        adj = {}
        for sg, cu in zip(segs, cuts):
            cu = sorted(set(round(c, 6) for c in cu))
            for a, b in zip(cu, cu[1:]):
                if b - a < 1e-9:
                    continue
                p = vert(sg[0] + (sg[2] - sg[0]) * a, sg[1] + (sg[3] - sg[1]) * a)
                q = vert(sg[0] + (sg[2] - sg[0]) * b, sg[1] + (sg[3] - sg[1]) * b)
                if p != q:
                    adj.setdefault(p, set()).add(q)
                    adj.setdefault(q, set()).add(p)
        changed = True
        while changed:                                           # lines that only hang off (overshoots) are not part of any area
            changed = False
            for v in [v for v, nb in adj.items() if len(nb) <= 1]:
                for w in adj.pop(v, ()):
                    adj[w].discard(v)
                changed = True
        if len(adj) < 3:
            return None
        # the nearest edge straight along +x from the point: the area is on its left (if the edge runs up) or right
        best = None
        for p, nb in adj.items():
            for q in nb:
                (x1, y1), (x2, y2) = pts[p], pts[q]
                if (y1 > P[1]) != (y2 > P[1]):
                    x = x1 + (P[1] - y1) * (x2 - x1) / (y2 - y1)
                    if x > P[0] and (best is None or x < best[0]):
                        best = (x, p, q)
        if best is None:
            return None
        _x, p, q = best
        if pts[q][1] < pts[p][1]:                                # walk it downwards: then the point (to its left) is inside
            p, q = q, p
        # now p -> q runs with y rising; the point is to the left of it
        start = (p, q)
        walk = [p]
        cur = (p, q)
        for _ in range(4000):
            a, b = cur
            walk.append(b)
            din = math.atan2(pts[b][1] - pts[a][1], pts[b][0] - pts[a][0])
            nxt = None
            best_t = -10.0
            for c in adj.get(b, ()):
                if c == a and len(adj[b]) > 1:
                    continue
                dout = math.atan2(pts[c][1] - pts[b][1], pts[c][0] - pts[b][0])
                t = (dout - din + math.pi) % (2 * math.pi) - math.pi        # a turn to the left is positive
                if t > best_t:
                    best_t, nxt = t, c
            if nxt is None:
                return None
            cur = (b, nxt)
            if cur == start:
                break
        else:
            return None
        poly = [pts[v] for v in walk[:-1]]
        # drop points that sit on a straight run
        out = []
        for i, q in enumerate(poly):
            a, b = poly[i - 1], poly[(i + 1) % len(poly)]
            if abs((q[0] - a[0]) * (b[1] - q[1]) - (q[1] - a[1]) * (b[0] - q[0])) > 1e-6 * (1 + math.hypot(b[0] - a[0], b[1] - a[1])):
                out.append(q)
        if len(out) < 3 or not inside(P, out):
            return None
        area = abs(_area(out))
        if not (25 <= area <= 60000):
            return None
        return {"pts": [(x / k, y / k) for x, y in out], "area": area, "layer": "faces",
                "bbox": (min(x for x, y in out) / k, min(y for x, y in out) / k, max(x for x, y in out) / k, max(y for x, y in out) / k)}

    def _poly_at(self, pt):
        cands = [s for s in self._stand_shapes() if s["bbox"][0] <= pt[0] <= s["bbox"][2] and s["bbox"][1] <= pt[1] <= s["bbox"][3] and inside(pt, s["pts"])]
        f = self._face_at(pt)
        if f:
            cands.append(f)
        if not cands:
            cands = [s for s in self._from_lines(pt) if inside(pt, s["pts"])]
        if not cands:
            return None
        return min(cands, key=lambda s: s["area"])

    def find(self, number, reach=45.0):
        """-> {"no", "poly" (metres), "neighbours": [{"no", "poly"}], "lines": {cat: [(x1, y1, x2, y2)]}, "street_edge", "road_known"} or None.
        Everything in metres in the drawing's own coordinates; the page moves it into the stand frame."""
        hits = self.labels_for(number)
        if not hits:
            return None
        k = self.k
        poly = None
        label = None
        for s, x, y, lay in hits:
            sh = self._poly_at((x, y))
            if sh:
                poly, label = sh, (s, x, y)
                break
        if poly is None:
            return None
        P = [(x * k, y * k) for x, y in site_dxf._clean(poly["pts"])]
        if len(P) < 3:
            return None
        if _area(P) < 0:
            P.reverse()
        bx = (min(p[0] for p in P) - reach, min(p[1] for p in P) - reach, max(p[0] for p in P) + reach, max(p[1] for p in P) + reach)
        # the stands beside it
        nb = []
        pc = centroid(P)
        for s_, x_, y_, lay_ in self.texts:                      # the stands beside it: the area round each stand number written near it
            X, Y = x_ * k, y_ * k
            sn_ = stand_no(s_)
            if not (bx[0] <= X <= bx[2] and bx[1] <= Y <= bx[3]) or not sn_ or not 2 <= len(sn_) <= 6 or self.cat_of(lay_) == "off":
                continue
            s_ = sn_
            if inside((X, Y), P):
                continue
            f = self._poly_at((x_, y_))
            if not f:
                continue
            Q = [(x * k, y * k) for x, y in site_dxf._clean(f["pts"])]
            if len(Q) < 3 or any(math.hypot(centroid(Q)[0] - centroid(o["poly"])[0], centroid(Q)[1] - centroid(o["poly"])[1]) < 0.5 for o in nb) or math.hypot(centroid(Q)[0] - pc[0], centroid(Q)[1] - pc[1]) < 0.5:
                continue
            if math.hypot(centroid(Q)[0] - pc[0], centroid(Q)[1] - pc[1]) <= 42.0:
                nb.append({"poly": Q, "no": s_, "area": abs(_area(Q))})
        for s in ([] if len(nb) >= 2 else self._stand_shapes()):
            sb = s["bbox"]
            if sb[2] * k < bx[0] or sb[0] * k > bx[2] or sb[3] * k < bx[1] or sb[1] * k > bx[3]:
                continue
            Q = [(x * k, y * k) for x, y in site_dxf._clean(s["pts"])]
            if len(Q) < 3 or (abs(centroid(Q)[0] - pc[0]) < 0.05 and abs(centroid(Q)[1] - pc[1]) < 0.05):
                continue
            if abs(abs(_area(Q)) - abs(_area(P))) < 0.01 and math.hypot(centroid(Q)[0] - pc[0], centroid(Q)[1] - pc[1]) < 0.5:
                continue
            nb.append({"poly": Q, "no": self._number_in(Q), "area": abs(_area(Q))})
        if len(nb) < 2:                                          # the boundaries are loose lines: join them near the stand
            for s in self._from_lines((pc[0] / k, pc[1] / k), reach + 30):
                Q = [(x * k, y * k) for x, y in site_dxf._clean(s["pts"])]
                if len(Q) >= 3 and math.hypot(centroid(Q)[0] - pc[0], centroid(Q)[1] - pc[1]) > 0.5 and not any(math.hypot(centroid(Q)[0] - centroid(o["poly"])[0], centroid(Q)[1] - centroid(o["poly"])[1]) < 0.5 for o in nb):
                    if bx[0] <= centroid(Q)[0] <= bx[2] and bx[1] <= centroid(Q)[1] <= bx[3]:
                        nb.append({"poly": Q, "no": self._number_in(Q), "area": abs(_area(Q))})
        # the lines around it, by what they are
        lines = {c: [] for c in CATS}
        for lay, v in self.layers.items():
            cat = v["cat"]
            arr = self.lines.get(lay)
            if cat == "off" or not arr:
                continue
            for i in range(0, len(arr), 4):
                x1, y1, x2, y2 = arr[i] * k, arr[i + 1] * k, arr[i + 2] * k, arr[i + 3] * k
                if min(x1, x2) > bx[2] or max(x1, x2) < bx[0] or min(y1, y2) > bx[3] or max(y1, y2) < bx[1]:
                    continue
                lines[cat].append((x1, y1, x2, y2))
                if len(lines[cat]) > 40000:
                    break
        edge, known = self.street_edge(P, nb, lines)
        conn = self.connections(P, edge, reach=8.0)
        corner = [i for i in self.side_streets(P, edge, lines) if not any(
            _seg_dist(((P[i][0] + P[(i + 1) % len(P)][0]) / 2, (P[i][1] + P[(i + 1) % len(P)][1]) / 2), o["poly"][j], o["poly"][(j + 1) % len(o["poly"])]) < 0.4
            for o in nb for j in range(len(o["poly"])))]
        # Survey coordinates have north up (y up); the plan sheet is drawn with y down. So the picture is not turned into its own mirror image, everything is handed over
        # with y negated (the drawing's north is then -y; see Township.NORTH).
        P = [(x, -y) for x, y in P]
        for o in nb:
            o["poly"] = [(x, -y) for x, y in o["poly"]]
        lines = {c: [(a, -b_, c_, -d) for a, b_, c_, d in v] for c, v in lines.items()}
        for c_ in conn.values():
            c_["pt"] = (c_["pt"][0], -c_["pt"][1])
        return {"no": str(number).strip(), "poly": P, "connections": conn, "neighbours": nb, "lines": lines, "street_edge": edge, "road_known": known, "corner": corner,
                "label": label, "matches": len(hits)}

    def connections(self, P, edge, reach=8.0):
        """the connection symbols (a small filled triangle or box) on or near the stand's street boundary: {"elec": {...}, "water": {...}}. Each has "pt" (the point of
        the triangle that touches the boundary, in metres) and "label" (the text beside it, such as C5.1 2p)."""
        k = self.k
        n = len(P)
        a, b = P[edge], P[(edge + 1) % n]
        out = {}
        for m in self.marks:
            kind = "elec" if (m["col"] == 2 or self.cat_of(m["layer"]) == "elec") else ("water" if (m["col"] in (4, 5) or 130 <= m["col"] <= 179 or self.cat_of(m["layer"]) == "water") else None)
            if not kind:
                continue
            Q = [(x * k, y * k) for x, y in m["pts"]]
            if len(Q) < 3:
                continue
            ext = max(max(q[0] for q in Q) - min(q[0] for q in Q), max(q[1] for q in Q) - min(q[1] for q in Q))
            if ext > 4.0 or ext < 0.05:
                continue
            tip = min(Q, key=lambda q: _seg_dist(q, a, b))
            d = _seg_dist(tip, a, b)
            if d > reach:
                continue
            if kind not in out or d < out[kind]["d"]:
                out[kind] = {"pt": tip, "d": d, "kind": kind}
        for kind, c in out.items():
            best = None
            for s, x, y, lay in self.texts:
                dd = math.hypot(x * k - c["pt"][0], y * k - c["pt"][1])
                if dd < 6.0 and re.match(r"^([A-Za-z]{1,3}\d+(\.\d+)?|\d+ ?[pP])$", s.strip()) and (best is None or dd < best[0]):
                    best = (dd, s)
            c["label"] = best[1] if best else ""
        return out

    def _number_in(self, Q):
        """the stand number written inside an outline (the shortest all-digit text in it, else the shortest text)"""
        k = self.k
        xs, ys = [p[0] for p in Q], [p[1] for p in Q]
        best = None
        for s, x, y, lay in self.texts:
            X, Y = x * k, y * k
            if min(xs) <= X <= max(xs) and min(ys) <= Y <= max(ys) and self.cat_of(lay) != "off" and len(s) <= 14 and inside((X, Y), Q):
                sn = stand_no(s)
                key = (sn is None, len(s))
                if best is None or key < best[0]:
                    best = (key, sn or s)
        return best[1] if best else ""

    @staticmethod
    def side_streets(P, edge, lines):
        """the other sides of a corner stand that face a road (edge indexes), apart from the street side; [] for an ordinary stand"""
        n = len(P)
        road = lines.get("road") or []
        out = []
        for i in range(n):
            if i == edge or i in (edge,):
                continue
            a, b = P[i], P[(i + 1) % n]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if road and min(_seg_dist(mid, (r[0], r[1]), (r[2], r[3])) for r in road) < 5.0 and math.hypot(b[0] - a[0], b[1] - a[1]) > 5:
                out.append(i)
        return out

    @staticmethod
    def street_edge(P, nb, lines):
        """the side of the stand that is the street: not shared with a stand beside it, and nearest to the road and kerb lines. -> (edge index, road known)"""
        n = len(P)
        shared = []
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            hit = False
            for o in nb:
                Q = o["poly"]
                for j in range(len(Q)):
                    if _seg_dist(mid, Q[j], Q[(j + 1) % len(Q)]) < 0.4:
                        hit = True
                        break
                if hit:
                    break
            shared.append(hit)
        free = [i for i in range(n) if not shared[i]] or list(range(n))
        road = lines.get("road") or []
        if road:
            def d(i):
                a, b = P[i], P[(i + 1) % n]
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                return min(_seg_dist(mid, (r[0], r[1]), (r[2], r[3])) for r in road)
            near = [i for i in free if d(i) < 5.0]
            if len(near) >= 2:                      # a corner stand: the road is on two sides. The short frontage is the street (entry, carport); the long side is the side street
                L = lambda i: math.hypot(P[(i + 1) % n][0] - P[i][0], P[(i + 1) % n][1] - P[i][1])
                return min(near, key=L), True
            return min(free, key=d), True
        # no road layer: the free side that has the most open space outside it (nobody beside it), the longest wins a tie
        def open_space(i):
            a, b = P[i], P[(i + 1) % n]
            return -math.hypot(b[0] - a[0], b[1] - a[1])
        return min(free, key=open_space), False
