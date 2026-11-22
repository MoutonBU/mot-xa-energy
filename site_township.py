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
         ("water", ("water", "wtr", "wat_", "_wat", "-wat", "wat-", "potable", "hydrant", "w.con", "wcon")),
         ("elec", ("elec", "power", "cable", "eskom", "lv_", "mv_", "_lv", "_mv", "lighting", "transf", "ecs")),
         ("storm", ("storm", "drain", "culvert", "swale", "sw_", "_sw", "kerb inlet", "catchpit", "channel")),
         ("road", ("road", "kerb", "curb", "street", "carriageway", "pavement", "verge", "asphalt")),
         ("stand", ("erf", "erven", "stand", "cadast", "parcel", "boundar", "prop", "lot", "cad", "sg_", "_sg", "diagram", "portion", "ptn")))


def guess_category(layer):
    n = str(layer).lower()
    if n in ("0", "defpoints") or "dim" in n or "text" in n or "title" in n or "frame" in n or "grid" in n:
        return "off" if n in ("defpoints",) or "dim" in n or "title" in n or "frame" in n else "other"
    for cat, ws in WORDS:
        if any(w in n for w in ws):
            return cat
    return "other"


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
    def __init__(self):
        self.layers = {}            # name -> {"n": entity count, "cat": category}
        self.lines = {}             # layer -> array('d') x1 y1 x2 y2 ... in drawing units
        self.shapes = []            # closed outlines: {"layer", "pts" (drawing units), "bbox"}
        self.texts = []             # (clean text, x, y, layer) in drawing units
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
        cnt = [0]

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
                    if progress and cnt[0] % 20000 == 0:
                        progress(cnt[0])
                    if t == "LINE":
                        self.lines.setdefault(lay, []).extend((e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))
                    elif t == "LWPOLYLINE":
                        pts = [(p[0], p[1]) for p in e.get_points("xy")]
                        if len(pts) < 2:
                            continue
                        if e.closed and len(pts) >= 3:
                            self.shapes.append({"layer": lay, "pts": pts})
                        add_lines(lay, pts, bool(e.closed))
                    elif t == "POLYLINE" and not e.is_polygon_mesh:
                        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
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
                        n = max(6, int((a1 - a0) / (math.pi / 8)))
                        add_lines(lay, [(c.x + r * math.cos(a0 + (a1 - a0) * q / n), c.y + r * math.sin(a0 + (a1 - a0) * q / n)) for q in range(n + 1)])
                    elif t in ("TEXT", "MTEXT"):
                        tx = e.dxf.text if t == "TEXT" else e.text
                        s = clean_text(tx)
                        if s:
                            self.texts.append((s, e.dxf.insert.x, e.dxf.insert.y, lay))
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
            self.layers[lay] = {"n": len(self.lines.get(lay, ())) // 4, "cat": guess_category(lay)}
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

    def labels_for(self, number):
        """the texts that are this stand number (the whole text, or one word of it such as ERF 2155)"""
        num = str(number).strip().upper()
        if not num:
            return []
        pat = re.compile(r"(?<![\w/.])" + re.escape(num) + r"(?![\w/])")
        out = []
        for s, x, y, lay in self.texts:
            if self.cat_of(lay) == "off":
                continue
            u = s.upper()
            if u == num or (pat.search(u) and len(u) <= len(num) + 16):
                out.append((s, x, y, lay))
        return out

    def _poly_at(self, pt):
        cands = [s for s in self._stand_shapes() if s["bbox"][0] <= pt[0] <= s["bbox"][2] and s["bbox"][1] <= pt[1] <= s["bbox"][3] and inside(pt, s["pts"])]
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
        for s in self._stand_shapes():
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
        return {"no": str(number).strip(), "poly": P, "neighbours": nb, "lines": lines, "street_edge": edge, "road_known": known,
                "label": label, "matches": len(hits)}

    def _number_in(self, Q):
        """the stand number written inside an outline (the shortest all-digit text in it, else the shortest text)"""
        k = self.k
        xs, ys = [p[0] for p in Q], [p[1] for p in Q]
        best = None
        for s, x, y, lay in self.texts:
            X, Y = x * k, y * k
            if min(xs) <= X <= max(xs) and min(ys) <= Y <= max(ys) and self.cat_of(lay) != "off" and len(s) <= 12 and inside((X, Y), Q):
                key = (not s.replace("/", "").replace(" ", "").isdigit(), len(s))
                if best is None or key < best[0]:
                    best = (key, s)
        return best[1] if best else ""

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
            return min(free, key=d), True
        # no road layer: the free side that has the most open space outside it (nobody beside it), the longest wins a tie
        def open_space(i):
            a, b = P[i], P[(i + 1) % n]
            return -math.hypot(b[0] - a[0], b[1] - a[1])
        return min(free, key=open_space), False
