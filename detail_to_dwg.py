#!/usr/bin/env python3
"""
MOT Studio - Detail to DWG
==========================
Give it a DWG/DXF of a construction detail (section). It finds the materials
(hatches), writes the callout notes in your house style, places them as MText
with dotted leaders on their own layers, and saves a new DWG.

    python detail_to_dwg.py detail.dwg
    python detail_to_dwg.py detail.dwg --scale 10 --text 3 --no-ai

Needs
  pip install ezdxf matplotlib shapely anthropic
  ODA File Converter (free, opendesign.com) for .dwg in/out. Without it, save
  the detail as .dxf from Archicad/AutoCAD and the tool returns a .dxf.
  Anthropic API key (env ANTHROPIC_API_KEY or api_key.txt next to this script)
  for the AI notes. Without a key, --no-ai rules use layer / pattern names.

Output (next to the input)
  <name>_noted.dwg / .dxf   drawing with notes on layers MOT_NOTES, MOT_NOTE_LEADERS
  <name>_notes.txt          the notes + items flagged [VERIFY]
  <name>_noted_preview.png  quick look at the result
"""
import argparse
import base64
import glob
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = "claude-sonnet-5-5"
NOTE_LAYER = "MOT_NOTES"
LEADER_LAYER = "MOT_NOTE_LEADERS"

STYLE_GUIDE = """You are a South African architectural technologist writing construction-detail callout notes.

HOUSE STYLE (examples of the notes this office issues):
- Widedek 760 Charcoal roof sheeting on 76 x 50 SA Pine Purlins @ 1 200mm Max.
- 135 mm Think Pink Aerolite or similar glasswool insulation, achieving min. R-value per SANS 10400-XA, installed above ceiling.
- 38x38 mm timber battens, H3 treated, fixed to trusses with corrosion-resistant nails. For ceiling brandering: max. 400 mm c/c (gypsum) or 300 mm c/c (fibre-cement) per SANS 10400-L & manufacturer's spec.
- 210 mm fibre-cement fascia board (Nutec or similar) to SANS 803, fixed with stainless steel screws.
- 120 mm half-round aluminium gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R).
- Wall plate anchored to trusses with galvanised strap at 2 m centres, embedded 300 mm into masonry (SANS 10400-K).
- Prefabricated roof trusses to engineer's structural design (SANS 10400-L).
- 170 mm concrete to Eng. design min. 25 MPa, reinforced mesh ref. 193, over DPM (SANS 10100-1, SANS 10400-J).
- Install 250 µm DPM below slab with 150 mm taped overlaps, turned up at wall (SANS 952, SANS 10400-J).
- Provide slip joint or compressible filler at wall/slab junction if differential movement expected.
- Reinforced concrete lintel over openings to engineer's design, min. 25 MPa concrete, cover per SANS 10100-1.

RULES
- One short note per marked item (1-3 sentences, about 160 characters max). Sentence-case, spec voice, no full stops needed on fragments.
- Identify each item from the picture, its layer name and hatch pattern. Use sizes that are dimensioned or measurable from the item's size in the table (mm); otherwise write "to Eng. design" / "to manufacturer's spec" rather than inventing a number.
- Everything must follow South African practice and standards: SANS 10400 parts (K walls, L roofs, J floors, R stormwater, XA energy), SANS 10100-1 concrete, SANS 1783/10005 timber, SANS 952 DPM/DPC; SA terms (brickforce, DPC, DPM, SA Pine, IBR/Widedek, Nutec, NHBRC, Eng. design); metric mm only, thousands with a space (1 200), micron as µm.
- Add a SANS 10400 part reference (or other SANS) only where confident. Do not invent brand names unless they appear in the drawing text.
- Skip markers that do not need a note (duplicates, backgrounds, ground fill) unless the item is a recognisable building element.
- If you are unsure what an item is, still write the best note and set "verify": true.
- Return ONLY a JSON array, ordered top-to-bottom as the items appear in the drawing:
  [{"id": 3, "note": "...", "verify": false}, ...]"""

# --------------------------------------------------------------------------
# Rule-based fallback (no AI)
# --------------------------------------------------------------------------
RULES = [
    (r"widedek|ibr|sheet|roof.?cover|corrug|tile|\\broof\\b", "Roof sheeting on SA Pine purlins @ 1 200 mm max. to manufacturer's spec. (SANS 10400-L)"),
    (r"purlin|batten|brander", "SA Pine purlins / battens to SANS 1783, H3 treated (SANS 10005), fixed to trusses per engineer's design (SANS 10400-L)"),
    (r"truss|rafter|timber|wood|pine|wall.?plate", "Prefabricated roof trusses to engineer's structural design (SANS 10400-L)"),
    (r"insul|isotherm|aerolite|glasswool|rockwool", "Glasswool insulation achieving min. R-value per SANS 10400-XA, installed above ceiling"),
    (r"gutter|rwg|downpipe", "Half-round gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R)"),
    (r"fascia|barge", "Fibre-cement fascia board fixed with stainless steel screws"),
    (r"lintel", "Reinforced concrete lintel over openings to engineer's design, cover per SANS 10100-1"),
    (r"dpc", "DPC min. 150 mm above finished ground level, lapped 150 mm at joints, to SANS 248 / SANS 952 (SANS 10400-K)"),
    (r"dpm|damp|membrane", "250 µm DPM below slab with 150 mm taped overlaps, turned up at wall (SANS 952, SANS 10400-J)"),
    (r"screed", "Sand-cement screed to falls, uniform thickness, movement joints per specification"),
    (r"iso.?board|polystyrene|eps|xps|pir", "Insulation board or similar, achieving min. R-value per SANS 10400-XA"),
    (r"stone|granite|sandstone|slate", "Natural stone to specification, bedded in mortar and fixed per Eng. detail"),
    (r"slab|conc|floor|found|footing", "Concrete to Eng. design min. 25 MPa, reinforced, over DPM (SANS 10100-1, SANS 10400-J)"),
    (r"brick|masonry|block|wall", "Masonry wall to SANS 10400-K, brickforce at every 4th course, wall ties per spec"),
    (r"plaster|render|paint|finish", "Plaster and paint finish to specification"),
    (r"gypsum|ceiling|board|drywall", "Ceiling board on brandering at max. centres per manufacturer's spec (SANS 10400-L)"),
]


def clean_name(pattern):
    """Archicad material names like '110mm_Brick' / '170mm_Conc__Slab_to_Eng__C3' -> readable."""
    t = re.sub(r"_+", " ", pattern or "").strip()
    t = re.sub(r"(\d)\s*mm", r"\1 mm", t)
    return t


LAYERED = r"insul|aerolite|glasswool|rockwool|iso.?board|polystyrene|eps|xps|pir|slab|conc|screed|plaster|render|gypsum|ceiling"


def measured_mm(item, mmu):
    """Thickness of a layer-like item (long and thin) measured from the drawing, to the nearest 5 mm. None otherwise."""
    try:
        w, h = item["bbox"]
        lo, hi = min(w, h) * mmu, max(w, h) * mmu
        if lo >= 8 and hi / lo >= 2.5:
            return int(5 * round(lo / 5))
    except Exception:
        pass
    return None


def rule_note(layer, pattern, thick=None):
    name = clean_name(pattern)
    size = re.search(r"(\d+)\s*mm", name)
    sz = f"{size.group(1)} mm " if size else ""
    measured = False
    if not sz and thick and re.search(LAYERED, f"{layer} {name}".lower().replace("_", " ")):
        sz = f"{thick} mm "              # no size in the material name: use what is drawn
        measured = True
    # material (hatch) name first, layer name only as a fallback
    if name.upper() in ("SOLID", "") and thick and thick < 30 and not size:
        return f"{layer}: thin solid fill (about {thick} mm) - describe element and specification", True
    for hay in (name.lower(), f"{layer} {name}".lower().replace("_", " ")):
        for rx, note in RULES:
            if re.search(rx, hay):
                if re.search(r"Concrete to Eng", note) and sz and int(re.match(r"\d+", sz).group()) >= 300:
                    note = "Concrete foundation to Eng. design min. 25 MPa, founded on competent soil (SANS 10400-H, SANS 10100-1)"
                if sz and not re.search(r"\d+\s*mm", note):
                    note = sz + note[0].lower() + note[1:]
                return note, measured       # a size measured from the drawing is flagged VERIFY
    if name and name.upper() not in ("SOLID", "WOOD"):
        return f"{name} - confirm specification", True
    return f"{layer}: describe element and specification", True


# --------------------------------------------------------------------------
# DWG <-> DXF via ODA File Converter
# --------------------------------------------------------------------------
def find_oda():
    env = os.environ.get("ODA_CONVERTER")
    if env and os.path.exists(env):
        return env
    home = os.path.expanduser("~")
    pats = [r"C:\Program Files\ODA\*\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
            r"C:\Program Files\ODA*\ODAFileConverter*.exe",
            r"C:\Program Files\ODA*\*\ODAFileConverter*.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ODA*", "ODAFileConverter*.exe"),
            os.path.join(home, "Downloads", "ODAFileConverter*", "ODAFileConverter*.exe"),
            os.path.join(home, "Desktop", "ODA*", "ODAFileConverter*.exe"),
            os.path.join(home, "Desktop", "ODAFileConverter*", "ODAFileConverter*.exe")]
    for p in pats:
        m = sorted(glob.glob(p))
        if m:
            return m[-1]
    return shutil.which("ODAFileConverter")


def oda_convert(src, out_fmt):
    """out_fmt 'DXF' or 'DWG'. Returns path of converted temp file or None."""
    exe = find_oda()
    if not exe:
        return None
    src = Path(src)
    tin, tout = tempfile.mkdtemp(), tempfile.mkdtemp()
    shutil.copy(src, tin)
    subprocess.run([exe, tin, tout, "ACAD2018", out_fmt, "0", "1", "*" + src.suffix],
                   check=False, timeout=240)
    res = list(Path(tout).glob("*." + out_fmt.lower()))
    if not res:
        return None
    keep = Path(tempfile.mkdtemp()) / res[0].name
    shutil.copy(res[0], keep)
    return keep


# --------------------------------------------------------------------------
# Reading the detail
# --------------------------------------------------------------------------
def load_doc(path):
    import ezdxf
    p = Path(path)
    if p.suffix.lower() == ".dwg":
        dxf = oda_convert(p, "DXF")
        if not dxf:
            raise SystemExit(
                "Cannot read .dwg: ODA File Converter not found.\n"
                "Install it free from opendesign.com (ODA File Converter), or save the "
                "detail as .dxf from Archicad/AutoCAD and run again.")
        p = dxf
    try:
        return ezdxf.readfile(str(p))
    except Exception:
        doc, _ = ezdxf.recover.readfile(str(p))
        return doc


def mm_per_unit(doc):
    return {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}.get(doc.header.get("$INSUNITS", 4), 1.0)


def aci_name(i):
    names = {1: "red", 2: "yellow", 3: "green", 4: "cyan", 5: "blue", 6: "magenta", 7: "white/black", 8: "grey"}
    return names.get(i, f"ACI {i}")


def extract_items(doc):
    """Group hatches into material items. Returns (items, existing_texts, extents)."""
    from ezdxf import bbox as ezbbox
    from ezdxf import path as ezpath
    msp = doc.modelspace()
    groups = {}
    texts = []
    for e in msp:
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            try:
                texts.append(e.plain_text() if t == "MTEXT" else e.dxf.text)
            except Exception:
                pass
        elif t == "DIMENSION":
            try:
                texts.append(f"dimension {e.get_measurement():.0f}")
            except Exception:
                pass
        elif t == "HATCH":
            layer = e.dxf.layer
            color = e.dxf.color
            if color in (0, 256):
                try:
                    color = doc.layers.get(layer).color
                except Exception:
                    color = 7
            pattern = "SOLID" if e.dxf.solid_fill else (e.dxf.pattern_name or "")
            polys = []
            try:
                for pth in ezpath.from_hatch(e):
                    pts = [(v.x, v.y) for v in pth.flattening(1.0)]
                    if len(pts) >= 3:
                        polys.append(pts)
            except Exception:
                pass
            if not polys:
                continue
            area, point, bb, geom = _poly_info(polys)
            if area <= 0:
                continue
            groups.setdefault((layer, pattern, color), []).append((area, point, bb, geom))
    items = []
    for (layer, pattern, color), pieces in groups.items():
        area, point, bb, geom = max(pieces, key=lambda p: p[0])
        items.append({"layer": layer, "pattern": pattern, "color": color,
                      "area": area, "point": point, "bbox": bb, "count": len(pieces), "poly": geom})
    items.sort(key=lambda i: -i["area"])
    for n, it in enumerate(items, 1):
        it["id"] = n
    try:
        ext = ezbbox.extents(msp)
        extents = (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
    except Exception:
        extents = (0, 0, 1000, 1000)
    return items, texts, extents


def _poly_info(polys):
    """largest polygon -> (area, interior point, (w, h))"""
    try:
        from shapely.geometry import Polygon
        best = None
        for pts in polys:
            g = Polygon(pts).buffer(0)
            if best is None or g.area > best.area:
                best = g
        rp = best.representative_point()
        minx, miny, maxx, maxy = best.bounds
        return best.area, (rp.x, rp.y), (maxx - minx, maxy - miny), best
    except Exception:
        pts = max(polys, key=len)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2, (sum(xs) / len(xs), sum(ys) / len(ys)), (max(xs) - min(xs), max(ys) - min(ys)), None


# --------------------------------------------------------------------------
# Preview image
# --------------------------------------------------------------------------
def render_png(doc, path, markers=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig = plt.figure(figsize=(10, 10), dpi=110)
    ax = fig.add_axes([0, 0, 1, 1])
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace(), finalize=True)
    for mid, (x, y) in (markers or {}).items():
        ax.annotate(str(mid), (x, y), ha="center", va="center", fontsize=11, color="white",
                    fontweight="bold",
                    bbox=dict(boxstyle="circle,pad=0.25", fc="#C8102E", ec="white", lw=1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


# --------------------------------------------------------------------------
# Notes: AI or rules
# --------------------------------------------------------------------------
def get_key():
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k.strip()
    f = Path(__file__).with_name("api_key.txt")
    if f.exists():
        return f.read_text().strip()
    return None


def ai_prompt(items, texts, mmu):
    table = [{"id": i["id"], "layer": i["layer"], "hatch_pattern": i["pattern"],
              "colour": aci_name(i["color"]), "material_name": clean_name(i["pattern"]),
              "size_mm": [round(i["bbox"][0] * mmu), round(i["bbox"][1] * mmu)],
              "pieces_in_drawing": i["count"]} for i in items]
    prompt = ("Numbered red markers on the attached detail point at the items listed below "
              "(largest piece of each material).\n\nITEMS:\n" + json.dumps(table, indent=1) +
              "\n\nTEXT ALREADY IN THE DRAWING (do not repeat; may name products/sizes):\n" +
              json.dumps(texts[:60]) + "\n\nWrite the callout notes.")
    return prompt


def ai_notes(png, items, texts, mmu, key):
    import anthropic
    prompt = ai_prompt(items, texts, mmu)
    img = base64.standard_b64encode(Path(png).read_bytes()).decode()
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=MODEL, max_tokens=4000, system=STYLE_GUIDE,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
            {"type": "text", "text": prompt}]}])
    return parse_notes("".join(b.text for b in msg.content if b.type == "text"))


def parse_notes(text):
    a, b = text.find("["), text.rfind("]")
    data = json.loads(text[a:b + 1])
    return [{"id": int(d["id"]), "note": " ".join(str(d["note"]).split()),
             "verify": bool(d.get("verify", False))} for d in data if d.get("note")]


def dedupe_notes(notes):
    """one callout per identical note text (keeps the largest item)"""
    best = {}
    for n in notes:
        k = n["note"].strip().lower()
        if k not in best or n["item"]["area"] > best[k]["item"]["area"]:
            best[k] = n
    keep = {id(v) for v in best.values()}
    return [n for n in notes if id(n) in keep]


def make_notes(items, png, texts, mmu, use_ai):
    by_id = {i["id"]: i for i in items}
    notes = []
    key = get_key() if use_ai else None
    if use_ai and not key:
        print("No API key (ANTHROPIC_API_KEY or api_key.txt) - using rule-based notes.")
    if key:
        try:
            raw = ai_notes(png, items, texts, mmu, key)
            for n in raw:
                if n["id"] in by_id:
                    notes.append({**n, "item": by_id[n["id"]]})
        except Exception as ex:
            print(f"AI step failed ({ex}) - using rule-based notes.")
            notes = []
    if not notes:
        for it in items:
            if max(it["bbox"]) * mmu < 15:
                continue  # ignore tiny specks (under 15 mm)
            txt, ver = rule_note(it["layer"], it["pattern"], measured_mm(it, mmu))
            notes.append({"id": it["id"], "note": txt, "verify": ver, "item": it})
    notes = dedupe_notes(notes)
    return notes


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# House colours + brick coursing
# --------------------------------------------------------------------------
# Sampled from the Archicad detail (first match wins; matched on material name, then layer).
PALETTE = [
    ("brick",    r"brick|masonry|block",                                   (255, 0, 0)),
    ("screed",   r"screed",                                                (170, 255, 213)),
    ("insul",    r"insul|iso.?board|glasswool|aerolite|rockwool|polystyrene|\beps\b|\bxps\b", (237, 134, 255)),
    ("concrete", r"conc|slab|found|footing|lintel",                        (0, 255, 0)),
    ("plaster",  r"plaster|render|skim",                                   (230, 230, 230)),
    ("finish",   r"tile|finish|paint|laminate|floor.?cover",               (251, 223, 206)),
    ("timber",   r"wood|timber|truss|rafter|purlin|batten|pine|beam",      (255, 255, 0)),
    ("metal",    r"steel|alumin|metal|angle|flash|sheet|roof|ibr|widedek|chromadek|gutter", (75, 78, 84)),
    ("ground",   r"gravel|stone|soil|earth|fill|sand|hardcore|ground",     (217, 217, 217)),
    ("membrane", r"dpm|dpc|membrane|damp|waterproof",                      (84, 104, 158)),
]
MORTAR_RGB = (166, 166, 166)
BRICK_LAYER = "MOT_BRICKWORK"


def classify(layer, pattern):
    """-> (key, rgb) or (None, None)"""
    name = clean_name(pattern).lower()
    for hay in (name, f"{layer} {name}".lower().replace("_", " ")):
        for key, rx, rgb in PALETTE:
            if re.search(rx, hay):
                return key, rgb
    return None, None


def hatch_geometry(e):
    """Shapely geometry (polygons with holes) of a HATCH, or None."""
    from ezdxf import path as ezpath
    from shapely.geometry import Polygon
    rings = []
    for pth in ezpath.from_hatch(e):
        pts = [(v.x, v.y) for v in pth.flattening(0.5)]
        if len(pts) >= 3:
            g = Polygon(pts).buffer(0)
            if not g.is_empty:
                rings.append(g)
    if not rings:
        return None
    rings.sort(key=lambda g: -g.area)
    out = []
    for r in rings:
        for k, o in enumerate(out):
            if o.contains(r):
                out[k] = o.difference(r)
                break
        else:
            out.append(r)
    from shapely.ops import unary_union
    return unary_union(out)


def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon" and not x.is_empty]


def _add_fill(msp, polys, rgb, layer, pattern=None, spacing=25.0):
    """pattern: 'diag' = 45-degree section lines `spacing` drawing-units apart, defined
    explicitly (the built-in names are inch-based and mis-scale in imperial-flagged files)."""
    from ezdxf import const
    h = msp.add_hatch(color=7, dxfattribs={"layer": layer})
    if pattern:
        k = spacing * 0.7071067811865476
        h.set_pattern_fill("MOT_DIAG", angle=0.0, scale=1.0,
                           pattern_type=const.HATCH_TYPE_CUSTOM,
                           definition=[[45.0, (0.0, 0.0), (-k, k), []]])
    else:
        h.set_solid_fill(rgb=rgb)
    for poly in polys:
        h.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True,
                                  flags=const.BOUNDARY_PATH_EXTERNAL)
        for hole in poly.interiors:
            h.paths.add_polyline_path(list(hole.coords)[:-1], is_closed=True,
                                      flags=const.BOUNDARY_PATH_OUTERMOST)
    return h


def restyle(doc, mmu, brick_mm=85.0, joint_mm=10.0, colours=True, coursing=True):
    """Colour hatches like the house standard and rebuild brick hatches as real brickwork
    (brick_mm bricks with joint_mm mortar, courses built up from the bottom of each piece)."""
    from shapely.geometry import box
    msp = doc.modelspace()
    if BRICK_LAYER not in doc.layers:
        doc.layers.add(BRICK_LAYER, color=7)
    bh, mj = brick_mm / mmu, joint_mm / mmu
    stats = {"coloured": 0, "bricks": 0, "courses": 0}
    low = []          # new fills that must sit underneath existing linework
    for h in list(msp.query("HATCH")):
        if h.dxf.layer.startswith("MOT_"):
            continue
        pattern = "SOLID" if h.dxf.solid_fill else (h.dxf.pattern_name or "")
        key, rgb = classify(h.dxf.layer, pattern)
        if key is None:
            continue
        if key == "brick" and coursing:
            try:
                g = hatch_geometry(h)
            except Exception:
                g = None
            if g is not None:
                bricks, mortar = [], []
                for poly in _polys(g):
                    x0, y0, x1, y1 = poly.bounds
                    y = y0
                    while y < y1 - 1e-6:
                        b = box(x0, y, x1, min(y + bh, y1)).intersection(poly)
                        m = box(x0, y + bh, x1, min(y + bh + mj, y1)).intersection(poly)
                        bricks += _polys(b)
                        mortar += _polys(m)
                        y += bh + mj
                        stats["courses"] += 1
                layer = h.dxf.layer
                msp.delete_entity(h)
                low.append(_add_fill(msp, _polys(g), MORTAR_RGB, BRICK_LAYER))       # mortar base
                low.append(_add_fill(msp, bricks, (255, 0, 0) if colours else (200, 200, 200), BRICK_LAYER))
                low.append(_add_fill(msp, bricks, None, BRICK_LAYER, pattern="diag", spacing=25.0 / mmu))
                for bk in bricks:
                    msp.add_lwpolyline(list(bk.exterior.coords)[:-1], close=True,
                                       dxfattribs={"layer": BRICK_LAYER, "lineweight": 13})
                stats["bricks"] += len(bricks)
                continue
        if colours:
            if not h.dxf.solid_fill:
                ov = h.copy()                   # keep the pattern lines on top of the colour
                msp.add_entity(ov)
            h.set_solid_fill(rgb=rgb)
            stats["coloured"] += 1
    try:                                        # draw new brick fills beneath existing linework
        msp.set_redraw_order([(e.dxf.handle, "%X" % (1 + i)) for i, e in enumerate(low)])
    except Exception:
        pass
    return stats


# --------------------------------------------------------------------------
# Completeness check against SA practice + drawing the missing elements
# --------------------------------------------------------------------------
ADD_LAYER = "MOT_ADDED"
TIMBER_RGB, MEMBRANE_RGB, BLACK_RGB = (255, 255, 0), (84, 104, 158), (0, 0, 0)

NOTE_PURLIN = "76 x 50 SA Pine purlins to SANS 1783, H3 treated (SANS 10005), @ 1 200 mm max. centres, fixed to trusses per engineer's design (SANS 10400-L)"
NOTE_BRICKFORCE = "Brickforce reinforcing in every 4th course of masonry (SANS 10400-K)"
NOTE_DPC = "DPC min. 150 mm above finished ground level, lapped 150 mm at joints, to SANS 248 / SANS 952 (SANS 10400-K)"
NOTE_WALLPLATE = "114 x 38 SA Pine wall plate, H3 treated (SANS 10005), anchored to trusses with galvanised strap at 2 m centres, embedded 300 mm into masonry (SANS 10400-K, SANS 10400-L)"
NOTE_CEILINS = "135 mm Aerolite or similar glasswool insulation above ceiling, achieving min. R-value per SANS 10400-XA"
NOTE_DPM = "250 µm DPM below slab with 150 mm taped overlaps, turned up at wall (SANS 952, SANS 10400-J)"

# (label, regex that shows it is already in the detail, what to do if missing)
ROOF_CHECKS = [
    ("Roof covering", r"sheet|ibr|widedek|chromadek|tile|roof", None),
    ("Purlins / battens", r"purlin|batten", "purlins"),
    ("Trusses / rafters", r"truss|rafter|timber|wood", None),
    ("Wall plate", r"wall.?plate", "wallplate"),
    ("Ceiling insulation", r"insul|aerolite|glasswool|isotherm|rockwool", "ceilins"),
    ("Ceiling board / brandering", r"ceiling|brander|gypsum|board", None),
    ("Fascia", r"fascia", None),
    ("Gutter", r"gutter", None),
]
WALL_CHECKS = [
    ("Masonry", r"brick|masonry|block", None),
    ("Floor slab", r"slab|conc", None),
    ("DPM under slab", r"dpm|membrane|polythene|damp|waterproof", "dpm"),
    ("DPC in wall", r"dpc|damp.?proof course", "dpc"),
    ("Brickforce", r"brickforce|brick.?force|reinforc", "brickforce"),
    ("Wall ties", r"\bties\b|wall.?tie", None),
]


def _rot_rect(cx, cy, ux, uy, along, perp):
    from shapely.geometry import Polygon
    nx, ny = -uy, ux
    hl, hp = along / 2, perp / 2
    return Polygon([(cx - ux * hl - nx * hp, cy - uy * hl - ny * hp),
                    (cx + ux * hl - nx * hp, cy + uy * hl - ny * hp),
                    (cx + ux * hl + nx * hp, cy + uy * hl + ny * hp),
                    (cx - ux * hl + nx * hp, cy - uy * hl + ny * hp)])


def _hatches(doc, want):
    """yield (hatch, geometry) for hatches whose class key == want"""
    for h in doc.modelspace().query("HATCH"):
        if h.dxf.layer.startswith("MOT_"):
            continue
        pattern = "SOLID" if h.dxf.solid_fill else (h.dxf.pattern_name or "")
        key, _ = classify(h.dxf.layer, pattern)
        if key == want:
            try:
                g = hatch_geometry(h)
            except Exception:
                g = None
            if g is not None and not g.is_empty:
                yield h, g, f"{h.dxf.layer} {clean_name(pattern)}".lower().replace("_", " ")


def _add(key, label, polys, rgb, note, outline=True):
    from shapely.geometry import MultiPolygon
    mp = MultiPolygon(polys) if polys else None
    pt = polys[0].representative_point() if polys else (0, 0)
    x0, y0, x1, y1 = mp.bounds
    return {"key": key, "label": label, "polys": polys, "rgb": rgb, "note": note, "outline": outline,
            "point": (pt.x, pt.y), "bbox": (x1 - x0, y1 - y0), "area": mp.area, "geom": mp}


def plan_purlins(doc, mmu):
    best = None
    for h, g, name in _hatches(doc, "metal"):
        if not re.search(r"sheet|roof|ibr|widedek|chromadek|corrug", name):
            continue
        for poly in _polys(g):
            mr = poly.minimum_rotated_rectangle
            c = list(mr.exterior.coords)[:4]
            e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
            e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
            L0, L1 = math.hypot(*e0), math.hypot(*e1)
            long, L, T = (e0, L0, L1) if L0 >= L1 else (e1, L1, L0)
            if T <= 0 or L / T < 3:
                continue
            if best is None or L > best[0]:
                best = (L, T, long, mr.centroid)
    if not best:
        return None
    L, T, long, cen = best
    ux, uy = long[0] / L, long[1] / L
    if uy < 0:
        ux, uy = -ux, -uy                         # up-slope
    if uy < math.sin(math.radians(3)):
        return None                               # flat: not a pitched roof
    nx, ny = uy, -ux                              # normal, pointing down
    if ny > 0:
        nx, ny = -nx, -ny
    pd, pw = 76 / mmu, 50 / mmu
    sx, sy = cen.x - ux * L / 2, cen.y - uy * L / 2
    d = T / 2 + pd / 2
    polys, t = [], 100 / mmu
    while t <= L - 40 / mmu:
        polys.append(_rot_rect(sx + ux * t + nx * d, sy + uy * t + ny * d, ux, uy, pw, pd))
        t += 1200 / mmu
    return _add("purlins", "Purlins", polys, TIMBER_RGB, NOTE_PURLIN) if polys else None


def plan_brickforce(doc, mmu, brick_mm, joint_mm):
    from shapely.geometry import box
    bh, mj = brick_mm / mmu, joint_mm / mmu
    polys = []
    for h, g, name in _hatches(doc, "brick"):
        for poly in _polys(g):
            x0, y0, x1, y1 = poly.bounds
            if x1 - x0 < 60 / mmu:
                continue
            y, k = y0, 0
            while y < y1:
                if (k + 1) % 4 == 0:
                    yj = y + bh + mj / 2
                    if yj < y1:
                        polys += _polys(box(x0 + 15 / mmu, yj - 1.5 / mmu, x1 - 15 / mmu, yj + 1.5 / mmu)
                                        .intersection(poly))
                k += 1
                y += bh + mj
    return _add("brickforce", "Brickforce", polys, BLACK_RGB, NOTE_BRICKFORCE, outline=False) if polys else None


def plan_dpm(doc, mmu):
    from shapely.geometry import box
    best = None
    for h, g, name in _hatches(doc, "concrete"):
        if not re.search(r"slab|conc", name):
            continue
        for poly in _polys(g):
            x0, y0, x1, y1 = poly.bounds
            if (x1 - x0) >= 1.5 * (y1 - y0) and (best is None or poly.area > best.area):
                best = poly
    if best is None:
        return None
    x0, y0, x1, y1 = best.bounds
    tol = 1.0 / mmu
    xs = [x for x, y in best.exterior.coords if y <= y0 + tol]
    if not xs or max(xs) - min(xs) < 100 / mmu:
        return None
    return _add("dpm", "DPM", [box(min(xs), y0 - 3 / mmu, max(xs), y0)], MEMBRANE_RGB, NOTE_DPM, outline=False)


def _brick_polys(doc, mmu):
    out = []
    for h, g, name in _hatches(doc, "brick"):
        for poly in _polys(g):
            x0, y0, x1, y1 = poly.bounds
            if x1 - x0 >= 60 / mmu and y1 - y0 >= 150 / mmu:
                out.append(poly)
    return out


def plan_dpc(doc, mmu):
    """DPC through the masonry: at the top of the slab when that is inside the wall, otherwise 150 mm above the bottom of the wall."""
    from shapely.geometry import box
    walls = _brick_polys(doc, mmu)
    if not walls:
        return None
    low = min(walls, key=lambda p: p.bounds[1])
    x0, y0, x1, y1 = low.bounds
    y = y0 + 150 / mmu
    for h, g, name in _hatches(doc, "concrete"):
        if re.search(r"slab|conc", name):
            for sl in _polys(g):
                sx0, sy0, sx1, sy1 = sl.bounds
                if (sx1 - sx0) >= 1.5 * (sy1 - sy0) and y0 < sy1 < y1 and sx0 <= x1 + 1 / mmu and sx1 >= x0 - 1 / mmu:
                    y = sy1
    if not y0 < y < y1:
        return None
    return _add("dpc", "DPC", [box(x0, y - 2 / mmu, x1, y + 2 / mmu).intersection(low)], MEMBRANE_RGB, NOTE_DPC, outline=False)


def plan_wallplate(doc, mmu):
    """114 x 38 wall plate on the highest masonry wall, unless timber already sits there."""
    from shapely.geometry import box
    walls = _brick_polys(doc, mmu)
    if not walls:
        return None
    top = max(walls, key=lambda p: p.bounds[3])
    x0, y0, x1, y1 = top.bounds
    w = min(x1 - x0, 114 / mmu)
    cx = (x0 + x1) / 2
    plate = box(cx - w / 2, y1, cx + w / 2, y1 + 38 / mmu)
    for h, g, name in _hatches(doc, "timber"):
        for t in _polys(g):
            if t.intersection(plate).area > 0.3 * plate.area:
                return None                      # a timber member is already there
    return _add("wallplate", "Wall plate", [plate], TIMBER_RGB, NOTE_WALLPLATE)


def plan_ceilins(doc, mmu):
    """135 mm insulation lying on the ceiling board."""
    from shapely.geometry import box
    best = None
    for h in doc.modelspace().query("HATCH"):
        if h.dxf.layer.startswith("MOT_"):
            continue
        pattern = "SOLID" if h.dxf.solid_fill else (h.dxf.pattern_name or "")
        if not re.search(r"ceiling|gypsum|brander|drywall|ceil", f"{h.dxf.layer} {clean_name(pattern)}".lower().replace("_", " ")):
            continue
        try:
            g = hatch_geometry(h)
        except Exception:
            g = None
        for poly in (_polys(g) if g is not None and not g.is_empty else []):
            x0, y0, x1, y1 = poly.bounds
            if (x1 - x0) >= 4 * (y1 - y0) and (best is None or poly.area > best[0].area):
                best = (poly, (x0, y0, x1, y1))
    if not best:
        return None
    x0, y0, x1, y1 = best[1]
    return _add("ceilins", "Ceiling insulation", [box(x0, y1, x1, y1 + 135 / mmu)], (237, 134, 255), NOTE_CEILINS)


def completeness(doc, texts, items, mmu, brick_mm=85.0, joint_mm=10.0, coursing=True):
    """Check the detail against SA practice. Returns {"report": [(label, state)], "adds": [...]}.
    state: ok | added | manual. Missing elements whose position can be derived are drawn."""
    hay = " ".join([f"{i['layer']} {clean_name(i['pattern'])}" for i in items] + list(texts)
                   ).lower().replace("_", " ")
    have = lambda rx: re.search(rx, hay) is not None
    report, adds = [], []
    roof = any(True for _ in _hatches(doc, "metal") if re.search(r"sheet|roof|ibr|widedek|chromadek|corrug", _[2]))
    wall = have(r"brick|masonry|block") or have(r"slab|conc")
    makers = {"purlins": lambda: plan_purlins(doc, mmu),
              "brickforce": lambda: plan_brickforce(doc, mmu, brick_mm, joint_mm) if coursing else None,
              "dpm": lambda: plan_dpm(doc, mmu),
              "dpc": lambda: plan_dpc(doc, mmu),
              "wallplate": lambda: plan_wallplate(doc, mmu),
              "ceilins": lambda: plan_ceilins(doc, mmu)}
    for enabled, checks in ((roof, ROOF_CHECKS), (wall, WALL_CHECKS)):
        if not enabled:
            continue
        for label, rx, maker in checks:
            if have(rx):
                report.append((label, "ok"))
                continue
            a = makers[maker]() if maker else None
            if a:
                adds.append(a)
                report.append((label, "added"))
            else:
                report.append((label, "manual"))
    return {"report": report, "adds": adds}


def draw_adds(doc, adds):
    msp = doc.modelspace()
    if ADD_LAYER not in doc.layers:
        doc.layers.add(ADD_LAYER, color=7)
    for a in adds:
        _add_fill(msp, a["polys"], a["rgb"], ADD_LAYER)
        if a["outline"]:
            for poly in a["polys"]:
                msp.add_lwpolyline(list(poly.exterior.coords)[:-1], close=True,
                                   dxfattribs={"layer": ADD_LAYER, "lineweight": 13})


# --------------------------------------------------------------------------
# Elements the user draws / detail by hand in the preview window
# --------------------------------------------------------------------------
USER_LAYER = "MOT_USER"
SHEET_RGB = (75, 78, 84)
NOTE_SHEET = "Widedek 760 Charcoal roof sheeting on 76 x 50 SA Pine purlins @ 1 200 mm max. to manufacturer's spec. (SANS 10400-L)"
# material -> (label, rgb, house note)
USER_MATS = {
    "timber":   ("Timber",     (255, 255, 0),   "SA Pine timber to SANS 1783, H3 treated (SANS 10005)"),
    "concrete": ("Concrete",   (0, 255, 0),     "Concrete to Eng. design min. 25 MPa, reinforced (SANS 10100-1)"),
    "brick":    ("Brickwork",  (255, 0, 0),     "Masonry wall to SANS 10400-K, brickforce at every 4th course, wall ties per spec"),
    "insul":    ("Insulation", (237, 134, 255), "Insulation achieving min. R-value per SANS 10400-XA"),
    "metal":    ("Steel",      (75, 78, 84),    "Steel section to Eng. design, hot-dip galvanised (SANS 121)"),
    "screed":   ("Screed",     (170, 255, 213), "Sand-cement screed to falls, uniform thickness, movement joints per specification"),
    "plaster":  ("Plaster",    (230, 230, 230), "Plaster and paint finish to specification"),
    "membrane": ("DPM / DPC",  (84, 104, 158),  "250 \u00b5m DPM, 150 mm taped overlaps (SANS 952, SANS 10400-J)"),
}


def sheet_polygon(p0, p1, mmu, pitch=177.0, rib=37.0, thick=1.2):
    """Corrugated roof-sheet profile (IBR/Widedek style) from p0 to p1, ribs on the upper side."""
    from shapely.geometry import LineString
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    if ny < 0 or (abs(ny) < 1e-9 and nx < 0):
        nx, ny = -nx, -ny
    k = 1.0 / mmu
    valley, rise, top = 94.0 * k, 28.0 * k, 27.0 * k
    prof, s = [(0.0, 0.0)], 0.0
    while s < L:
        for ds, h in ((valley, 0.0), (rise, rib * k), (top, rib * k), (rise, 0.0)):
            s += ds
            prof.append((s, h))
            if s >= L:
                break
    out = []
    for i, (a, h) in enumerate(prof):
        if a > L:                                   # clip the last segment at L
            a0, h0 = prof[i - 1]
            t = (L - a0) / (a - a0)
            out.append((L, h0 + (h - h0) * t))
            break
        out.append((a, h))
    pts = [(p0[0] + ux * a + nx * h, p0[1] + uy * a + ny * h) for a, h in out]
    if len(pts) < 2:
        return None
    return LineString(pts).buffer(thick * k / 2, cap_style=2, join_style=2)


def roof_direction(doc):
    """unit up-slope vector of the main roof sheet in the detail, or None"""
    best = None
    for h, g, name in _hatches(doc, "metal"):
        if not re.search(r"sheet|roof|ibr|widedek|chromadek|corrug", name):
            continue
        for poly in _polys(g):
            c = list(poly.minimum_rotated_rectangle.exterior.coords)[:4]
            e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
            e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
            L0, L1 = math.hypot(*e0), math.hypot(*e1)
            long, L, T = (e0, L0, L1) if L0 >= L1 else (e1, L1, L0)
            if T > 0 and L / T >= 3 and (best is None or L > best[0]):
                best = (L, long)
    if not best:
        return None
    L, v = best
    ux, uy = v[0] / L, v[1] / L
    return (-ux, -uy) if uy < 0 else (ux, uy)


def user_geometry(el, mmu):
    """shapely geometry of a user element (None for lines/notes)"""
    from shapely.geometry import box
    t = el["type"]
    if t == "sheet":
        return sheet_polygon(el["pts"][0], el["pts"][1], mmu)
    if t == "purlin":
        ux, uy = el["dir"]
        return _rot_rect(el["pts"][0][0], el["pts"][0][1], ux, uy, 50 / mmu, 76 / mmu)
    if t == "rect":
        (x0, y0), (x1, y1) = el["pts"][0], el["pts"][1]
        if abs(x1 - x0) < 1e-9 or abs(y1 - y0) < 1e-9:
            return None
        return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return None


def user_item(el, mmu, nid):
    """a note target for an element, shaped like the items extract_items makes"""
    from shapely.geometry import Point
    g = user_geometry(el, mmu)
    if g is not None and not g.is_empty:
        if el["type"] == "sheet":
            m = ((el["pts"][0][0] + el["pts"][1][0]) / 2, (el["pts"][0][1] + el["pts"][1][1]) / 2)
            ring = g.exterior
            q = ring.interpolate(ring.project(Point(m)))
            pt = (q.x, q.y)
            poly = None
        else:
            r = g.representative_point()
            pt, poly = (r.x, r.y), g
        x0, y0, x1, y1 = g.bounds
        bbox, area = (x1 - x0, y1 - y0), g.area
    else:
        pt = tuple(el["pts"][0])
        bbox, area, poly = (2 / mmu, 2 / mmu), 1.0, None
    label = {"sheet": "Roof sheeting", "purlin": "Purlin", "note": "Note",
             "rect": USER_MATS.get(el.get("mat"), ("Fill",))[0]}.get(el["type"], "Yours")
    return {"id": nid, "layer": USER_LAYER, "pattern": label, "color": 7, "area": area, "point": pt,
            "bbox": bbox, "count": 1, "poly": poly, "synthetic": True, "user": el["uid"],
            "key": "user:%s" % el["uid"], "note": el.get("note", "")}


def apply_overrides(doc, overrides, mmu):
    """overrides: {hatch handle: material key | 'delete'} - recolour or remove fills of the original detail"""
    msp = doc.modelspace()
    if USER_LAYER not in doc.layers:
        doc.layers.add(USER_LAYER, color=7)
    done = 0
    for h in list(msp.query("HATCH")):
        act = overrides.get(str(h.dxf.handle))
        if not act:
            continue
        if act != "delete":
            try:
                g = hatch_geometry(h)
            except Exception:
                g = None
            if g is not None and act in USER_MATS:
                _add_fill(msp, _polys(g), USER_MATS[act][1], USER_LAYER)
        msp.delete_entity(h)
        done += 1
    return done


def draw_user(doc, elems, mmu):
    msp = doc.modelspace()
    if USER_LAYER not in doc.layers:
        doc.layers.add(USER_LAYER, color=7)
    for el in elems:
        t = el["type"]
        if t == "line":
            msp.add_lwpolyline([tuple(p) for p in el["pts"]],
                               dxfattribs={"layer": USER_LAYER, "lineweight": 25, "color": 7})
            continue
        g = user_geometry(el, mmu)
        if g is None or g.is_empty:
            continue
        rgb = SHEET_RGB if t == "sheet" else (TIMBER_RGB if t == "purlin" else
                                               USER_MATS.get(el.get("mat"), USER_MATS["timber"])[1])
        _add_fill(msp, _polys(g), rgb, USER_LAYER)
        if t != "sheet":
            for poly in _polys(g):
                msp.add_lwpolyline(list(poly.exterior.coords)[:-1], close=True,
                                   dxfattribs={"layer": USER_LAYER, "lineweight": 13, "color": 7})


LAST_CONFLICTS = [0]


def save_doc(doc, path):
    """Save as DXF 2018. Old R2000 files cannot store true colours: the house colours would
    silently turn white/black, so the version is raised before saving."""
    try:
        if doc.dxfversion < "AC1018":
            doc.dxfversion = "AC1032"
    except Exception:
        pass
    doc.saveas(str(path))



def _candidates(it, limit=30):
    """Possible dot positions inside the item's hatch (first = best representative point)."""
    pts = [it["point"]]
    g = it.get("poly")
    if g is None:
        return pts
    try:
        from shapely.geometry import Point
        w, hgt = it["bbox"]
        inset = g.buffer(-0.12 * min(w, hgt))
        if inset.is_empty:
            inset = g
        x0, y0, x1, y1 = inset.bounds
        extra = []
        for i in range(10):
            for j in range(10):
                x = x0 + (x1 - x0) * (i + 0.5) / 10
                y = y0 + (y1 - y0) * (j + 0.5) / 10
                if inset.contains(Point(x, y)):
                    extra.append((x, y))
        random.Random(3).shuffle(extra)
        pts += extra[:limit - 1]
    except Exception:
        pass
    return pts


def _layout(notes, heights, ax, y_top, h, dmin, iters=6000):
    """Choose note order + dot positions so no leader segment or dot comes within dmin
    of another leader (no crossing, overlap, touching or dot-on-line)."""
    n = len(notes)
    cands = [_candidates(nt["item"]) for nt in notes]
    rnd = random.Random(11)
    d2 = dmin * dmin

    def build(order, pick):
        y = y_top
        out = [None] * n
        for k in order:
            ym = y - 0.6 * h
            tx, ty = cands[k][pick[k]]
            out[k] = ((min(tx, ax), max(tx, ax), ym, ym), (tx, tx, min(ym, ty), max(ym, ty)), (tx, ty))
            y -= heights[k]
        return out

    def cost(order, pick):
        segs = build(order, pick)
        bad = 0
        length = 0.0
        for i in range(n):
            Hi, Vi, _ = segs[i]
            length += (Hi[1] - Hi[0]) + (Vi[3] - Vi[2])
            for j in range(i + 1, n):
                Hj, Vj, _ = segs[j]
                for a in (Hi, Vi):
                    for b in (Hj, Vj):
                        dx = max(a[0] - b[1], b[0] - a[1], 0.0)
                        dy = max(a[2] - b[3], b[2] - a[3], 0.0)
                        if dx * dx + dy * dy < d2:
                            bad += 1
        return bad * 1e9 + length, bad

    order = sorted(range(n), key=lambda k: -cands[k][0][1])
    pick = [0] * n
    cur, bad = cost(order, pick)
    best = (cur, bad, order[:], pick[:])
    since = 0
    for it in range(iters):
        o2, p2 = order[:], pick[:]
        if n > 1 and rnd.random() < 0.45:
            i, j = rnd.sample(range(n), 2)
            o2[i], o2[j] = o2[j], o2[i]
        else:
            k = rnd.randrange(n)
            p2[k] = rnd.randrange(len(cands[k]))
        c2, b2 = cost(o2, p2)
        if c2 <= cur or rnd.random() < 0.01:
            order, pick, cur, bad = o2, p2, c2, b2
        if cur < best[0] - 1e-9:
            best = (cur, bad, order[:], pick[:])
            since = 0
        else:
            since += 1
        if best[1] == 0 and since > 900:
            break
        if since > 1500:                      # stuck: restart from best with a shake
            order, pick, cur, bad = best[2][:], best[3][:], best[0], best[1]
            if n > 1:
                i, j = rnd.sample(range(n), 2)
                order[i], order[j] = order[j], order[i]
                cur, bad = cost(order, pick)
            since = 0
    return best, cands


LAST_COLUMN_X = [None]


def _pointer(msp, style, tx, ty, fx, fy, h, dot_r):
    """end marker of a leader: dot, ring, arrow, tick or none. (fx, fy) is where the leader comes from."""
    lay = {"layer": LEADER_LAYER}
    if style == "none":
        return
    if style == "ring":
        msp.add_circle((tx, ty), dot_r * 1.15, dxfattribs=lay)
        return
    if style == "tick":
        d = 0.7 * h
        msp.add_line((tx - d, ty - d), (tx + d, ty + d), dxfattribs=lay)
        return
    if style == "arrow":
        dx, dy = tx - fx, ty - fy
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        al, aw = 1.5 * h, 0.4 * h
        bx, by = tx - ux * al, ty - uy * al
        hatch = msp.add_hatch(color=7, dxfattribs=lay)
        hatch.paths.add_polyline_path([(tx, ty), (bx - uy * aw, by + ux * aw), (bx + uy * aw, by - ux * aw)], is_closed=True)
        return
    hatch = msp.add_hatch(color=7, dxfattribs=lay)
    hatch.paths.add_polyline_path([(tx - dot_r, ty, 1), (tx + dot_r, ty, 1)], is_closed=True)


def place_notes(doc, notes, extents, mmu, scale, text_mm, width_mm, gap_mm, number=False, manual=None, targets=None, pointer="dot", pointers=None):
    if not notes:
        return []
    msp = doc.modelspace()
    h = text_mm * scale / mmu                # text height, drawing units
    width = width_mm * scale / mmu
    gap = gap_mm * scale / mmu
    minx, miny, maxx, maxy = extents
    if "MOT_NOTE" not in doc.styles:
        doc.styles.add("MOT_NOTE", font="arial.ttf")
    for name, col in ((NOTE_LAYER, 7), (LEADER_LAYER, 7)):
        if name not in doc.layers:
            doc.layers.add(name, color=col)
    x = maxx + gap
    LAST_COLUMN_X[0] = x
    y_top = maxy + h
    cpl = max(10, int(width / (0.78 * h)))   # chars per line estimate
    dot_r = 0.35 * h
    heights = []
    for n in notes:      # the number is only added to what is drawn: the note text itself stays clean
        extra = 5 if number else 0
        lines = max(1, sum(math.ceil(max(1, len(p) + extra) / cpl) for p in n["note"].split("\n")))
        heights.append(lines * h * 1.4 + 1.2 * h)
    ax = x - 0.4 * h
    best, cands = _layout(notes, heights, ax, y_top, h, dmin=0.9 * h)
    LAST_CONFLICTS[0] = best[1]
    order, pick = best[2], best[3]
    ordered = []
    y = y_top
    manual = manual or {}
    mboxes = [(manual[notes[k]["id"]][0], manual[notes[k]["id"]][1] - heights[k],
               manual[notes[k]["id"]][0] + width, manual[notes[k]["id"]][1])
              for k in range(len(notes)) if notes[k].get("id") in manual]
    for k in order:
        n = notes[k]
        tx, ty = cands[k][pick[k]]
        tp = (targets or {}).get(n.get("id"))
        if tp:
            tx, ty = tp                                   # you moved the dot: it points where you put it
        n["target"] = (tx, ty)
        mp = manual.get(n.get("id"))
        if not mp:                                        # the other notes close ranks around the ones you placed
            while True:
                bottom = y - heights[k]
                hit = [b for b in mboxes if not (b[2] <= x or b[0] >= x + width or b[3] <= bottom or b[1] >= y)]
                if not hit:
                    break
                y = min(b[1] for b in hit) - 0.3 * h
        px, py = (mp if mp else (x, y))                  # a note you dragged keeps your position and takes no slot in the stack
        n["box"] = (px, py - heights[k], px + width, py)
        msp.add_mtext((f"{len(ordered) + 1}.  " if number else "") + n["note"], dxfattribs={
            "layer": NOTE_LAYER, "style": "MOT_NOTE", "char_height": h, "width": width,
            "insert": (px, py), "attachment_point": 1,
            "color": 1 if n["verify"] else 256})
        ymid = py - 0.6 * h
        msp.add_lwpolyline([(px - 0.4 * h, ymid), (tx, ymid), (tx, ty)], dxfattribs={"layer": LEADER_LAYER})
        _pointer(msp, (pointers or {}).get(n.get("id"), pointer), tx, ty, tx, ymid, h, dot_r)
        if not mp:
            y -= heights[k]
        ordered.append(n)
    return ordered


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Add detail notes to a DWG/DXF")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output path (.dwg or .dxf)")
    ap.add_argument("--scale", type=float, default=10, help="drawing scale denominator (1:N), default 10")
    ap.add_argument("--text", type=float, default=3.0, help="text height on paper, mm (default 3)")
    ap.add_argument("--note-width", type=float, default=65, help="note column width on paper, mm")
    ap.add_argument("--gap", type=float, default=12, help="gap drawing -> notes on paper, mm")
    ap.add_argument("--no-ai", action="store_true", help="rule-based notes only")
    ap.add_argument("--brick", type=float, default=85.0, help="brick height mm (default 85)")
    ap.add_argument("--joint", type=float, default=10.0, help="mortar joint mm (default 10)")
    ap.add_argument("--no-style", action="store_true", help="skip house colours + brick coursing")
    a = ap.parse_args()

    src = Path(a.input)
    doc = load_doc(src)
    mmu = mm_per_unit(doc)
    items, texts, extents = extract_items(doc)
    if not items:
        raise SystemExit("No hatches found in the drawing - nothing to label. "
                         "(Export the detail with its hatches/fills.)")
    print(f"{len(items)} material groups found.")

    tmp_png = Path(tempfile.mkdtemp()) / "markers.png"
    render_png(doc, tmp_png, {i["id"]: i["point"] for i in items})
    notes = make_notes(items, tmp_png, texts, mmu, not a.no_ai)
    if not a.no_style:
        print("Style:", restyle(doc, mmu, a.brick, a.joint))
    ordered = place_notes(doc, notes, extents, mmu, a.scale, a.text, a.note_width, a.gap)

    out = Path(a.output) if a.output else src.with_name(src.stem + "_noted" + src.suffix)
    want_dwg = out.suffix.lower() == ".dwg"
    dxf_out = out.with_suffix(".dxf")
    save_doc(doc, dxf_out)
    final = dxf_out
    if want_dwg:
        dwg = oda_convert(dxf_out, "DWG")
        if dwg:
            shutil.copy(dwg, out)
            final = out
            dxf_out.unlink(missing_ok=True)
        else:
            print("ODA File Converter not found - saved .dxf instead (open in Archicad/AutoCAD and save as DWG).")
    render_png(doc, final.with_name(src.stem + "_noted_preview.png"))
    rep = final.with_name(src.stem + "_notes.txt")
    with open(rep, "w", encoding="utf-8") as f:
        for i, n in enumerate(ordered, 1):
            f.write(f"{i}. {n['note']}" + ("   [VERIFY]" if n["verify"] else "") + "\n")
    print(f"Saved: {final}\n       {rep}")
    print("Leaders: no overlaps." if LAST_CONFLICTS[0] == 0 else
          f"Leaders: {LAST_CONFLICTS[0]} spots still close - nudge by hand.")
    if any(n["verify"] for n in ordered):
        print("Notes in RED on the drawing are flagged [VERIFY].")


if __name__ == "__main__":
    main()
