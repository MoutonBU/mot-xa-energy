"""
Detail generator: a typed (or dictated) request -> a construction detail drawn as a DXF in the house style.

The request goes to Claude, which returns a small JSON drawing (outlines of each material in mm, plus one note per
material). This module checks that JSON, draws it, gives it the house colours and real brick coursing
(detail_to_dwg.restyle) and places the callout notes in a column (detail_to_dwg.place_notes).

Nothing here needs Qt, so it can be tested without a window.
"""
import json
import math
import os
import re
import urllib.error
import urllib.request

import detail_to_dwg as core

# material -> layer name. The names are chosen so detail_to_dwg.classify gives each its house colour.
LAYERS = {
    "brick": "DET_Brickwork", "block": "DET_Blockwork", "concrete": "DET_Concrete", "screed": "DET_Screed",
    "insulation": "DET_Insulation", "plaster": "DET_Plaster", "finish": "DET_Finish", "timber": "DET_Timber",
    "steel": "DET_Steel", "ground": "DET_Ground", "dpm": "DET_DPM", "other": "DET_Other",
}
MAX_SHAPES = 150
LIMIT = 30000.0            # mm: nothing in a construction detail is further than this from the origin

SYSTEM = (
    "You draw South African construction details (sections) for an architectural technologist. You are given a "
    "request and answer ONLY by calling the draw_detail tool (never with plain text).\n\n"
    "Shape of the drawing:\n"
    '{"title": "short title", "shapes": [{"material": "<m>", "pts": [[x,y], ...]}], '
    '"notes": {"<m>": "callout note"}, "assumptions": ["short sentence", ...]}\n\n'
    "RULES\n"
    "- Section view, millimetres, x to the right, y up, true size 1:1. Put finished floor level at y = 0 unless the "
    "request is for something else.\n"
    "- Every shape is ONE closed polygon (3 to 40 points, no repeated first point), drawn the way it really is: walls "
    "as full-height rectangles, slabs, footings, screed, insulation, DPM as thin strips (a membrane is 2 to 4 mm thick "
    "drawn as a strip, not a line), etc. Shapes of the same material may overlap only at shared edges.\n"
    "- material must be one of: brick, block, concrete, screed, insulation, plaster, finish, timber, steel, ground, "
    "dpm, other. Use brick for face or plaster brick walls, block for concrete blockwork. Use dpm for DPC and DPM.\n"
    "- Sizes follow SA practice: brick 110 wide (single skin), cavity wall 110 + 50 cavity + 110, 190 hollow block, "
    "concrete strip footing at least 600 wide x 200 thick on 750 deep for single storey unless the request gives "
    "sizes, 100 to 170 mm slab on 250 um DPM over compacted hardcore, 25 to 50 mm screed, DPC 150 mm above ground. "
    "Use the sizes in the request when given. Do not invent engineer's values: say 'to Eng. design' in the note.\n"
    "- notes: one per material that you drew, keyed by material, 1 to 3 sentences, max 200 characters, spec voice, "
    "metric mm only, thousands with a space (1 200), SANS references only where you are sure (SANS 10400 parts H "
    "foundations, J floors, K walls, L roofs, XA energy, SANS 10100-1 concrete, SANS 952 DPM). Example: "
    "'170 mm concrete to Eng. design min. 25 MPa, reinforced mesh ref. 193, over DPM (SANS 10100-1, SANS 10400-J).'\n"
    "- Proprietary systems (e.g. Loffelstein or other retaining blocks, Hyload, Cemcrete): draw the generic shape and size from your knowledge, and say in the note 'to manufacturer\'s spec' and list the size you assumed under assumptions. Retaining walls also need a drain (gravel and a perforated pipe) behind the wall, filter fabric, a base and the retained ground.\n"
    "- assumptions: what you had to assume that the request did not say (sizes, levels). At most 5.\n"
    "- Keep the whole detail to about 2 000 mm wide and 1 500 mm high unless the request needs more.")


TOOL = {
    "name": "draw_detail",
    "description": "The construction detail to draw: outlines per material (mm) and one note per material.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "shapes": {"type": "array", "items": {"type": "object", "properties": {
                "material": {"type": "string", "enum": sorted(LAYERS)},
                "pts": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}, "minItems": 3}},
                "required": ["material", "pts"]}},
            "notes": {"type": "object", "additionalProperties": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}}},
        "required": ["title", "shapes", "notes"]}}


class GenError(Exception):
    pass


def api_key():
    try:
        import mot_detail_notes_app as dn
        return dn.api_key()
    except Exception:
        return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def api_model():
    try:
        import mot_detail_notes_app as dn
        return dn.api_model()
    except Exception:
        return core.MODEL


# ---------------------------------------------------------------- the designer's own details
LIB_MAX = 60


def library_path():
    try:
        import mot_detail_notes_app as dn
        return os.path.join(str(dn.OUT_DIR), "my_details.json")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "my_details.json")


def load_library(path=None):
    """-> [{"title", "request", "spec"}] saved by the designer (empty when there are none or the file cannot be read)"""
    try:
        with open(path or library_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and isinstance(d.get("spec"), dict) and d.get("title")]
    except Exception:
        return []


def _write_library(lib, path=None):
    p = path or library_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(lib[-LIB_MAX:], f, ensure_ascii=False)


def save_detail(request, spec, path=None):
    """keep a detail the designer is happy with; the generator reads these as examples of how they like details drawn. Same title replaces."""
    lib = [d for d in load_library(path) if d["title"] != spec.get("title")]
    lib.append({"title": spec.get("title") or "Detail", "request": (request or "").strip(), "spec": spec})
    _write_library(lib, path)
    return len(lib)


def delete_detail(title, path=None):
    lib = load_library(path)
    _write_library([d for d in lib if d["title"] != title], path)


def pick_examples(request, lib, n=2):
    """the saved details whose words are closest to the request"""
    words = {w for w in re.findall(r"[a-z]{4,}", (request or "").lower())}
    scored = []
    for d in lib:
        dw = {w for w in re.findall(r"[a-z]{4,}", (d["title"] + " " + d.get("request", "")).lower())}
        scored.append((len(words & dw), d))
    scored = [t for t in scored if t[0] > 0] or [(0, d) for d in lib[-1:]]          # nothing close: the latest one still shows the style
    scored.sort(key=lambda t: -t[0])
    return [d for _s, d in scored[:n]]


def examples_text(exs, limit=7000):
    out, used = [], 0
    for d in exs:
        t = json.dumps(d["spec"], ensure_ascii=False, separators=(",", ":"))
        if used + len(t) > limit:
            break
        used += len(t)
        out.append("Request: %s\nDrawing: %s" % (d.get("request") or d["title"], t))
    if not out:
        return ""
    return ("\n\nTHE DESIGNER'S OWN SAVED DETAILS. Draw in the same style: the same material names, layers, level of detail, note wording and way of "
            "dimensioning, unless the request asks for something different. Do not copy a detail that does not match the request.\n\n" + "\n\n".join(out))


def ask_claude(request, key, model, timeout=120, examples=""):
    """-> raw reply text. Raises GenError with a plain message."""
    body = {"model": model, "max_tokens": 8000, "system": SYSTEM + (examples or ""), "tools": [TOOL], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": request.strip()}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise GenError(f"Claude said: {msg or e.reason} (code {e.code})")
    except urllib.error.URLError as e:
        raise GenError(f"No internet connection ({e.reason})")
    for p in data.get("content", []):
        if p.get("type") == "tool_use" and isinstance(p.get("input"), dict):
            return p["input"]                      # already a checked JSON object
    if data.get("stop_reason") == "max_tokens":
        raise GenError("The detail was too big for one reply. Ask for a simpler detail or fewer parts.")
    return "".join(p.get("text", "") for p in data.get("content", []))


def parse_reply(text):
    if isinstance(text, dict):
        return text
    """pull the JSON object out of the reply (tolerates fences or a stray sentence around it)"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise GenError("The reply had no drawing in it.")
    try:
        return json.loads(t[a:b + 1])
    except ValueError as ex:
        raise GenError(f"The reply could not be read ({ex}).")


def clean_spec(spec):
    """-> (spec, problems). Drops shapes that cannot be drawn and says why."""
    problems = []
    if not isinstance(spec, dict):
        raise GenError("The drawing was not in the expected form.")
    shapes = []
    for k, s in enumerate(spec.get("shapes") or [], 1):
        try:
            mat = str(s.get("material", "other")).strip().lower()
            if mat not in LAYERS:
                mat = "other"
            pts = [(float(p[0]), float(p[1])) for p in s["pts"]]
        except Exception:
            problems.append(f"shape {k} skipped (unreadable)")
            continue
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            problems.append(f"shape {k} skipped (fewer than 3 points)")
            continue
        if any((not math.isfinite(x)) or (not math.isfinite(y)) or abs(x) > LIMIT or abs(y) > LIMIT for x, y in pts):
            problems.append(f"shape {k} skipped (off the page)")
            continue
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            a += x1 * y2 - x2 * y1
        if abs(a) < 1.0:
            problems.append(f"shape {k} skipped (no area)")
            continue
        shapes.append({"material": mat, "pts": pts})
        if len(shapes) >= MAX_SHAPES:
            problems.append("more than %d shapes: the rest were left out" % MAX_SHAPES)
            break
    if not shapes:
        raise GenError("Nothing could be drawn from that reply. Try again, or describe the detail with more words.")
    notes = {}
    for m, t in (spec.get("notes") or {}).items():
        m = str(m).strip().lower()
        t = " ".join(str(t).split())
        if m in LAYERS and t:
            notes[m] = t[:400]
    return {"title": str(spec.get("title") or "Detail")[:80], "shapes": shapes, "notes": notes,
            "assumptions": [str(a)[:200] for a in (spec.get("assumptions") or [])][:5]}, problems


def build_doc(spec, scale=20, text_mm=2.5, width_mm=70.0, gap_mm=10.0):
    """cleaned spec -> (ezdxf doc, extents, placed notes)"""
    import ezdxf
    from shapely.geometry import Polygon
    doc = ezdxf.new("R2010", setup=True)
    doc.units = 4                                    # millimetres
    msp = doc.modelspace()
    doc.layers.add("DET_OUTLINE", color=7)
    for m, lay in LAYERS.items():
        doc.layers.add(lay, color=7)
    for s in spec["shapes"]:
        poly = Polygon(s["pts"])
        if not poly.is_valid:
            poly = poly.buffer(0)
        polys = [poly] if poly.geom_type == "Polygon" else [g for g in poly.geoms if g.geom_type == "Polygon"]
        core._add_fill(msp, polys, (217, 217, 217), LAYERS[s["material"]])
        msp.add_lwpolyline(s["pts"], close=True, dxfattribs={"layer": "DET_OUTLINE", "lineweight": 25})
    core.restyle(doc, 1.0)                           # house colours + 85 mm bricks with 10 mm joints
    from ezdxf import bbox as ezbbox
    try:
        e = ezbbox.extents(msp)
        extents = (e.extmin.x, e.extmin.y, e.extmax.x, e.extmax.y)
    except Exception:
        extents = (0, 0, 1000, 1000)
    notes = []
    for m in LAYERS:                                  # one note per material, pointing into its biggest piece
        txt = spec["notes"].get(m)
        pieces = [Polygon(s["pts"]).buffer(0) for s in spec["shapes"] if s["material"] == m]
        pieces = [p for p in pieces if p.geom_type == "Polygon" and p.area > 0]
        if not txt or not pieces:
            continue
        big = max(pieces, key=lambda p: p.area)
        x0, y0, x1, y1 = big.bounds
        rp = big.representative_point()
        item = {"layer": LAYERS[m], "pattern": "SOLID", "color": 7, "area": big.area, "point": (rp.x, rp.y),
                "bbox": (x1 - x0, y1 - y0), "count": len(pieces), "poly": big, "id": len(notes) + 1}
        notes.append({"id": item["id"], "note": txt, "verify": False, "item": item})
    placed = core.place_notes(doc, notes, extents, 1.0, scale, text_mm, width_mm, gap_mm) if notes else []
    return doc, extents, placed


def make_detail(spec, dxf_path, png_path=None, **kw):
    """draw the cleaned spec to dxf_path (and a preview png). -> number of notes placed"""
    doc, _ext, placed = build_doc(spec, **kw)
    core.save_doc(doc, dxf_path)
    if png_path:
        core.render_png(doc, png_path)
    return len(placed)


def generate(request, key=None, model=None, library=None):
    """request words -> (clean spec, problems). Needs an API key."""
    key = key or api_key()
    if not key:
        raise GenError("No API key saved. Add one under Settings in the Detail notes tab "
                       "(a Claude Pro subscription does not give the program a key).")
    last = None
    lib = load_library() if library is None else library
    ex = examples_text(pick_examples(request, lib)) if lib else ""
    for _try in range(2):                           # a reply that cannot be read is tried once more
        try:
            return clean_spec(parse_reply(ask_claude(request, key, model or api_model(), examples=ex)))
        except GenError as ex:
            last = ex
            if "Claude said" in str(ex) or "internet" in str(ex):
                raise
    raise last


# A detail that needs no internet or key, so the tab can be tried straight away.
SAMPLE_SPEC = {
    "title": "Sample: cavity wall on strip footing",
    "shapes": [
        {"material": "ground", "pts": [[-700, -1050], [-150, -1050], [-150, -750], [0, -750], [0, -150], [-700, -150]]},
        {"material": "ground", "pts": [[450, -1050], [1300, -1050], [1300, -150], [190, -150], [190, -750], [450, -750]]},
        {"material": "concrete", "pts": [[-150, -1050], [450, -1050], [450, -750], [-150, -750]]},
        {"material": "block", "pts": [[0, -750], [190, -750], [190, -150], [0, -150]]},
        {"material": "brick", "pts": [[0, -150], [110, -150], [110, 1500], [0, 1500]]},
        {"material": "brick", "pts": [[160, -150], [270, -150], [270, 1500], [160, 1500]]},
        {"material": "dpm", "pts": [[0, -150], [270, -150], [270, -146], [0, -146]]},
        {"material": "concrete", "pts": [[270, -150], [1300, -150], [1300, 20], [270, 20]]},
    ],
    "notes": {
        "ground": "Compacted hardcore fill in 150 mm layers, min. 95% Mod. AASHTO (SANS 10400-J).",
        "concrete": "Concrete strip footing 600 x 300 mm to Eng. design, min. 25 MPa, founded on firm natural ground (SANS 10400-H, SANS 10100-1).",
        "block": "190 mm concrete blockwork below DPC, cavity filled with concrete to ground level (SANS 10400-K).",
        "brick": "Cavity wall: 2 x 110 mm face brick leaves, 50 mm cavity, wall ties @ 600 mm c/c (SANS 10400-K).",
        "dpm": "DPC/DPM lapped 150 mm and turned up at the wall, continuous with the DPM under the slab (SANS 952, SANS 10400-K).",
    },
    "assumptions": ["Sizes are an example only and must be checked by the Engineer."],
}


def geometry_for_notes(spec, dxf_path):
    """Draws only the parts (coloured fills and outlines, no notes) so the Detail notes workspace can take the drawing over, and
    returns the notes Claude wrote as that workspace's own saved specs: {hatch handle: {note, x, y, cat}}."""
    import ezdxf
    from shapely.geometry import Polygon
    doc = ezdxf.new("R2010", setup=True)
    doc.units = 4
    msp = doc.modelspace()
    doc.layers.add("DET_OUTLINE", color=7)
    for lay in LAYERS.values():
        doc.layers.add(lay, color=7)
    best = {}                                          # material -> (area, handle, point): the biggest piece carries the note
    for s in spec["shapes"]:
        poly = Polygon(s["pts"])
        if not poly.is_valid:
            poly = poly.buffer(0)
        polys = [poly] if poly.geom_type == "Polygon" else [g for g in poly.geoms if g.geom_type == "Polygon"]
        if not polys:
            continue
        lay = LAYERS[s["material"]]
        rgb = core.classify(lay, "SOLID")[1] or (217, 217, 217)
        h = core._add_fill(msp, polys, rgb, lay)
        msp.add_lwpolyline(s["pts"], close=True, dxfattribs={"layer": "DET_OUTLINE", "lineweight": 25})
        big = max(polys, key=lambda g: g.area)
        if s["material"] not in best or big.area > best[s["material"]][0]:
            rp = big.representative_point()
            best[s["material"]] = (big.area, h.dxf.handle, (rp.x, rp.y))
    core.save_doc(doc, dxf_path)
    return {hd: {"note": spec["notes"][m], "x": pt[0], "y": pt[1], "cat": ""} for m, (_a, hd, pt) in best.items() if spec["notes"].get(m)}
