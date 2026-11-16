"""
Detail Notes: turn a few typed words ("concrete coping", "170 slab", "stone cill") into a full callout note with the
detailing that goes with it (falls, drips, DPC, fixings, the usual SANS reference). This is the offline writer; when an
AI key is saved the dialog can ask Claude for the same thing.

smart_note(text) -> (note, recipe_name or None)
"""
import re

# material words -> how they are written in the note
MATS = [
    (r"pre-?cast", "precast concrete"),
    (r"in.?situ|cast", "cast in situ concrete"),
    (r"concrete|conc\b", "concrete"),
    (r"granite|slate|sandstone|stone|cut.?stone", "natural stone"),
    (r"face.?brick|brick", "brick"),
    (r"block", "concrete block"),
    (r"alumin|aluminium", "powder-coated aluminium"),
    (r"stainless", "stainless steel"),
    (r"galv", "hot-dip galvanised steel"),
    (r"steel|metal", "steel"),
    (r"fibre.?cement|nutec|fibre", "fibre-cement"),
    (r"upvc|pvc", "uPVC"),
    (r"pine|timber|wood|saligna|hardwood", "SA Pine"),
    (r"gypsum|dry.?wall", "gypsum"),
    (r"glasswool|aerolite|isotherm", "glasswool"),
    (r"eps|polystyrene", "EPS"),
    (r"xps", "XPS"),
    (r"pir", "PIR"),
]


def _size(text):
    m = re.search(r"(\d+)\s*[x×*]\s*(\d+)", text)
    if m:
        return f"{m.group(1)} x {m.group(2)}"
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(mm|m\b)?", text):
        v = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit == "m":
            return f"{v * 1000:g} mm"
        if v >= 8:
            return f"{v:g} mm"
    return ""


def _mat(text):
    for rx, name in MATS:
        if re.search(rx, text):
            return name
    return ""


def _lead(size, mat, default, noun):
    parts = [size, mat or default, noun]
    return " ".join(p for p in parts if p).strip()


# (name, regex, default material, template). {lead} = size + material + noun, {size}, {mat} also available
R = []


def _r(name, rx, default, tmpl, noun=None):
    R.append((name, re.compile(rx), default, tmpl, noun or name))


_r("coping", r"coping|cap\b", "precast concrete",
   "{lead} with drip grooves (throatings) on both sides, sloped to fall to the roof side, bedded in mortar over DPC, "
   "joints sealed to manufacturer's spec")
_r("cill", r"\bcill|\bsill", "precast concrete",
   "{lead} with drip groove under the front edge, sloped away from the window, bedded in mortar over DPC with the ends turned up")
_r("lintel", r"lintel", "reinforced concrete",
   "{lead} over the opening, min. 150 mm bearing each end, to Eng. design, cover per SANS 10100-1 (SANS 10400-K)")
_r("plinth", r"plinth|upstand|kerb upstand", "concrete",
   "{lead} min. 150 mm above finished level, top sloped to shed water, waterproofing turned up and terminated under flashing, sealed or painted")
_r("threshold", r"threshold", "concrete",
   "{lead} with drip, sloped to fall outwards, bedded over DPC, set below the door leaf")
_r("parapet", r"parapet", "brick",
   "{lead} wall capped with coping with drip grooves, DPC below the coping, waterproofing turned up min. 150 mm "
   "and terminated under cap flashing (SANS 10400-K)")
_r("flashing", r"flashing", "lead-free",
   "{lead} lapped min. 100 mm, chased 20 mm into the wall and sealed, with drip clear of the wall face")
_r("gutter", r"gutter", "aluminium",
   "{lead} fixed with brackets at max. 900 mm centres, min. 1:500 fall to downpipe, with stop ends and outlet (SANS 10400-R)")
_r("downpipe", r"downpipe|down.?pipe|rwp", "uPVC",
   "{lead} fixed with clips at max. 1 800 mm centres, discharging to stormwater or onto a splash block clear of the wall (SANS 10400-R)")
_r("fascia", r"fascia|barge", "fibre-cement",
   "{lead} board fixed with stainless steel screws, joints lapped and sealed, primed and painted on all faces")
_r("soffit", r"soffit|eaves", "fibre-cement",
   "{lead} lining to eaves, ventilated at the edge, fixed with stainless steel screws, painted")
_r("purlin", r"purlin", "SA Pine",
   "{lead} to SANS 1783, H3 treated (SANS 10005), @ 1 200 mm max. centres, fixed to trusses per engineer's design (SANS 10400-L)")
_r("batten", r"batten|brander", "SA Pine",
   "{lead} H3 treated (SANS 10005), at gauge to manufacturer's spec, fixed to trusses with corrosion-resistant nails (SANS 10400-L)")
_r("wall plate", r"wall.?plate", "SA Pine",
   "{lead} H3 treated (SANS 10005), anchored with galvanised strap at 2 m centres, embedded 300 mm into masonry (SANS 10400-K, SANS 10400-L)")
_r("truss", r"truss|rafter", "SA Pine",
   "Prefabricated roof trusses to engineer's structural design, anchored to the wall plate with galvanised straps (SANS 10400-L)")
_r("ceiling", r"ceiling", "gypsum",
   "{lead} board on brandering at max. centres per manufacturer's spec, joints taped and filled, with cornice (SANS 10400-L)")
_r("insulation", r"insul|glasswool|aerolite", "",
   "{lead}, achieving min. R-value per SANS 10400-XA, laid continuous with no gaps and not compressed")
_r("dpm", r"\bdpm|polythene|damp.?proof(?:ing)? membrane", "polyethylene",
   "250 µm DPM below slab with 150 mm taped overlaps, turned up at the wall and lapped to the DPC (SANS 952, SANS 10400-J)")
_r("dpc", r"\bdpc|damp.?proof course", "",
   "DPC min. 150 mm above finished ground level, lapped 150 mm at joints and sealed, to SANS 248 / SANS 952 (SANS 10400-K)")
_r("waterproofing", r"waterproof|torch|membrane|tanking", "",
   "{lead} fully bonded, lapped 100 mm, turned up min. 150 mm at walls and terminated under flashing, to manufacturer's spec")
_r("screed", r"screed", "sand-cement",
   "{lead} to falls where required, uniform thickness, movement joints per specification, cured and free of laitance")
_r("foundation", r"footing|foundation|strip|raft", "concrete",
   "{lead} to Eng. design, min. 25 MPa, founded on competent soil (SANS 10400-H, SANS 10100-1)")
_r("hardcore", r"hardcore|fill\b|compacted|sub.?base", "",
   "{lead} compacted in layers of max. 150 mm, blinded with sand, under slab (SANS 10400-H)")
_r("slab", r"slab|floor|concrete", "concrete",
   "{lead} to Eng. design, min. 25 MPa, reinforced with mesh, over DPM (SANS 10100-1, SANS 10400-J)", "slab")
_r("brickwork", r"brick|masonry|block|wall", "brick",
   "{lead} wall to SANS 10400-K, brickforce at every 4th course, wall ties per spec, joints 10 mm", "")
_r("plaster", r"plaster|render|skim", "",
   "{lead} in two coats, steel-floated, ready for paint, with stop beads at edges")
_r("paint", r"paint|coating|coat", "",
   "{lead}: two coats over primer, to manufacturer's spec")
_r("tile", r"tile|tiling", "ceramic",
   "{lead} on adhesive over screed, with grout and movement joints at perimeter, to specification")
_r("paving", r"paving|paver|driveway", "concrete",
   "{lead} on 25 mm sand bed over compacted sub-base, with edge restraint, falling away from the building")
_r("steps", r"stair|step", "concrete",
   "{lead} to Eng. design, risers max. 200 mm and goings min. 250 mm, non-slip nosing (SANS 10400-M)")
_r("balustrade", r"balustrade|handrail|barrier|railing", "steel",
   "{lead} min. 1 000 mm high, openings max. 100 mm, fixed to Eng. design (SANS 10400-D, SANS 10400-M)")
_r("window", r"window", "powder-coated aluminium",
   "{lead} frame fixed with hold-fasts, sealed to the reveal with flexible sealant, safety glazing where required (SANS 10400-N)")
_r("door", r"door", "",
   "{lead} in frame, set over threshold with drip, safety glazing where required (SANS 10400-N)")
_r("glazing", r"glaz|glass", "",
   "{lead} to SANS 10400-N, safety glass where required, to manufacturer's spec")
_r("skylight", r"skylight|roof.?light", "",
   "{lead} on upstand curb, flashed and sealed, glazing to SANS 10400-N")
_r("roof sheeting", r"ibr|widedek|chromadek|sheeting|corrugated|roof.?sheet", "",
   "{lead} on purlins at max. 1 200 mm centres, fixed and lapped per manufacturer's spec, with sealed ridge and flashings (SANS 10400-L)", "roof sheeting")
_r("roof tiles", r"roof.?tile|clay.?tile", "concrete",
   "{lead} on battens at gauge per manufacturer's spec, clipped and ridge-bedded (SANS 10400-L)", "roof tiles")
_r("ridge", r"ridge", "",
   "{lead} capping lapped and sealed per manufacturer's spec")
_r("valley", r"valley", "galvanised steel",
   "{lead} gutter lapped and sealed per manufacturer's spec (SANS 10400-L)")
_r("drain", r"drain|sewer|soil.?pipe|pipe", "uPVC",
   "{lead} to SANS 10400-P, laid to fall on a granular bed, with rodding access at changes of direction")
_r("kerb", r"kerb|curb", "concrete",
   "{lead} bedded on concrete, joints at max. 3 m, falling to drain")
_r("retaining wall", r"retaining", "reinforced concrete",
   "{lead} to Eng. design, with subsoil drain, weep holes and waterproofing to the retained face")
_r("steel", r"beam|column|angle|plate|\bshs\b|\bipe\b|\bpfc\b|\bsteel", "steel",
   "{lead} to Eng. design, hot-dip galvanised (SANS 121), connections as detailed", "section")
_r("timber", r"joist|deck|pergola|post|timber|\bpine", "SA Pine",
   "{lead} H3 treated (SANS 10005), to Eng. design, stainless steel or galvanised fixings", "section")
_r("cladding", r"cladding|clad", "fibre-cement",
   "{lead} fixed to treated battens over breathable membrane, ventilated cavity behind, to manufacturer's spec")
_r("stone", r"stone|granite|slate", "natural stone",
   "{lead} bedded in mortar and fixed to Eng. detail, with movement joints and drips where exposed")


def smart_note(text):
    """-> (note, recipe name or None). The note is never empty: with no recipe the words are kept and sent to the Eng./manufacturer."""
    t = " ".join((text or "").strip().split())
    if not t:
        return "", None
    low = t.lower()
    size, mat = _size(low), _mat(low)
    order = sorted(R, key=lambda r: 0 if (r[0] == "retaining wall" and "coping" not in low) else 1)
    for name, rx, default, tmpl, noun in order:
        if rx.search(low):
            sz = size
            if name in ("purlin",) and not sz:
                sz = "76 x 50"
            if name in ("batten",) and not sz:
                sz = "38 x 38"
            if name == "gutter" and not sz:
                sz = "100 mm half-round"
            if name == "fascia" and not sz:
                sz = "200 mm"
            if name == "dpm" or name == "dpc" or name == "truss":
                return tmpl, name
            # the noun is dropped when the typed words already end the lead naturally
            lead = _lead(sz, mat, default, noun if name not in ("brickwork",) else "")
            if name in ("insulation",):
                lead = _lead(sz, mat, "", "insulation")
            if name in ("waterproofing", "plaster", "paint", "glazing", "window", "door", "tile", "ceiling", "wall plate"):
                lead = _lead(sz, mat, default, noun if noun else name)
            if name == "plaster":
                lead = _lead(sz, mat, default, "plaster")
            if name == "paving":
                lead = _lead(sz, mat, default, "paving")
            if name in ("purlin", "batten"):
                lead = _lead(sz, mat, default, name + "s")
            if name == "steel":
                m_ = re.search(r"beam|column|angle|plate|shs|ipe|pfc", low)
                lead = _lead(sz, "", "steel", m_.group(0) if m_ and m_.group(0) not in ("shs", "ipe", "pfc") else ("section" if m_ else "section"))
            if name == "timber":
                m_ = re.search(r"joist|deck|pergola|post", low)
                lead = _lead(sz, mat, "SA Pine", m_.group(0) if m_ else "member")
            if name == "waterproofing" and "torch" in low:
                lead = _lead(sz, "", "torch-on", "waterproofing membrane")
            note = tmpl.format(lead=lead.strip(), size=sz, mat=mat)
            if name == "coping" and re.search(r"garden|boundary|free.?standing|wall coping", low) and "parapet" not in low:
                note = note.replace("sloped to fall to the roof side", "sloped to shed water to one side")
            note = re.sub(r"\s+", " ", note).strip()
            return note[0].upper() + note[1:], name
    words = re.sub(r"\d+(?:\.\d+)?\s*(?:mm|m)?\b", "", t).strip()
    note = (size + " " if size else "") + (words or t) + " to Eng. design / manufacturer's spec"
    note = re.sub(r"\s+", " ", note).strip()
    return note[0].upper() + note[1:], None
