"""
Specification catalog for the Detail Notes tab.

CATALOG = {category: [(label, note), ...]}.  The label is what is picked from the list, the note is the callout text
(South African practice, spec voice, mm only). A standard is quoted only where the reference is well established;
otherwise the note says "to Eng. design" or "to manufacturer's spec".  Own entries are kept by the program next to the
settings and shown in the same lists under "My specs".
"""
import re


def _t(sizes, fmt):
    return [(fmt[0].format(t=t), fmt[1].format(t=t)) for t in sizes]


CATALOG = {}

# ------------------------------------------------------------------ floors and slabs
CATALOG["Concrete slabs and floors"] = (
    [(f"{t} mm slab on ground, mesh ref. 193",
      f"{t} mm concrete slab to Eng. design, min. 25 MPa, reinforced with mesh ref. 193, over DPM (SANS 10100-1, SANS 10400-J)")
     for t in (85, 100, 120, 150, 170, 200, 255)] +
    [(f"{t} mm slab on ground, mesh ref. 100",
      f"{t} mm concrete slab to Eng. design, min. 25 MPa, reinforced with mesh ref. 100, over DPM (SANS 10100-1, SANS 10400-J)")
     for t in (100, 120, 150)] +
    [(f"{t} mm suspended reinforced slab",
      f"{t} mm suspended reinforced concrete slab to Eng. design, min. 30 MPa (SANS 10100-1)")
     for t in (150, 170, 200, 255)] +
    [("Rib-and-block suspended floor",
      "Rib-and-block suspended floor to Eng. design and manufacturer's spec, with 50 mm structural topping (SANS 10100-1)"),
     ("Hollow-core slab",
      "Precast hollow-core slab to Eng. design and manufacturer's spec, with structural topping where required"),
     ("Concrete apron 100 mm",
      "100 mm concrete apron, min. 1 000 mm wide around the building, falling away from the wall"),
     ("Slab edge thickening",
      "Slab edge thickened to Eng. design, reinforced as detailed (SANS 10100-1)"),
     ("Slip joint at wall/slab",
      "Slip joint or compressible filler at wall/slab junction where differential movement is expected"),
     ("Expansion / control joint",
      "Control joints at max. 4 500 mm centres, saw cut within 24 hours, sealed with flexible sealant")])

CATALOG["Foundations"] = (
    [(f"Strip footing {w} x {d} mm",
      f"Concrete strip footing {w} x {d} mm, min. 25 MPa, to Eng. design, founded on competent soil (SANS 10400-H, SANS 10100-1)")
     for w, d in ((450, 200), (600, 200), (600, 225), (750, 250), (900, 300))] +
    [("Pad footing to Eng. design",
      "Reinforced concrete pad footing to Eng. design, founded on competent soil (SANS 10400-H, SANS 10100-1)"),
     ("Raft foundation to Eng. design",
      "Reinforced concrete raft foundation to Eng. design (SANS 10400-H, SANS 10100-1)"),
     ("Ground beam",
      "Reinforced concrete ground beam to Eng. design, min. 25 MPa, cover per SANS 10100-1"),
     ("Trench-fill foundation",
      "Trench-fill concrete foundation to Eng. design, min. 25 MPa (SANS 10400-H)"),
     ("Foundation wall (below DPC)",
      "Foundation wall in masonry or concrete to Eng. design, up to DPC level (SANS 10400-H, SANS 10400-K)"),
     ("Starter bars",
      "Starter bars to Eng. design, lapped and bent as detailed (SANS 10100-1)"),
     ("Blinding layer",
      "50 mm concrete blinding, min. 15 MPa, under footing"),
     ("Waffle / stiffened raft",
      "Stiffened (waffle) raft to Eng. design and manufacturer's spec (SANS 10400-H)")])

CATALOG["Ground and fill"] = [
    ("Compacted fill 150 mm", "Compacted selected fill in 150 mm layers, min. 93% Mod. AASHTO density, under slab (SANS 10400-H)"),
    ("Compacted hardcore 100 mm", "100 mm compacted hardcore, blinded with sand, under slab"),
    ("Compacted hardcore 150 mm", "150 mm compacted hardcore, blinded with sand, under slab"),
    ("Hardcore 200 mm", "200 mm compacted hardcore, blinded with sand, under slab"),
    ("Sand bed 25 mm", "25 mm sand bed under DPM, free of sharp stones"),
    ("Anti-termite treatment", "Anti-termite treatment of fill and foundations by a registered operator, with guarantee"),
    ("Natural ground level (NGL)", "Natural ground level"),
    ("Finished ground level (FGL)", "Finished ground level, falling away from the building"),
    ("Subsoil drain", "Subsoil drain with gravel surround to discharge to stormwater (SANS 10400-R)"),
    ("Compacted subgrade", "Subgrade compacted to Eng. design requirements (SANS 10400-H)"),
    ("Gravel 19 mm stone", "19 mm stone gravel bed, compacted"),
    ("Paving on sand", "Paving on 25 mm sand bed on compacted sub-base, falling away from the building"),
]

CATALOG["Damp-proofing and waterproofing"] = [
    ("DPM 250 µm under slab", "250 µm DPM below slab with 150 mm taped overlaps, turned up at wall (SANS 952, SANS 10400-J)"),
    ("DPM 375 µm under slab", "375 µm DPM below slab with 150 mm taped overlaps, turned up at wall (SANS 952, SANS 10400-J)"),
    ("DPC in wall 150 above FGL", "DPC min. 150 mm above finished ground level, lapped 150 mm at joints, to SANS 248 / SANS 952 (SANS 10400-K)"),
    ("DPC under cill", "DPC under cill, extending past reveals and turned up at the ends"),
    ("DPC above lintel / cavity tray", "Cavity tray DPC above openings with weep holes at max. 900 mm centres, lapped and sealed"),
    ("DPC at parapet / chimney", "DPC at parapet or chimney base, lapped and sealed to flashing"),
    ("Torch-on waterproofing 4 mm", "4 mm torch-on bituminous waterproofing membrane, fully bonded, lapped 100 mm, turned up 150 mm at walls, to manufacturer's spec"),
    ("Liquid waterproofing (balcony)", "Liquid-applied waterproofing membrane, two coats with reinforcing, turned up 150 mm at walls, to manufacturer's spec"),
    ("Screed to falls 1:80", "Sand-cement screed to falls min. 1:80 to outlets, over structural slab"),
    ("Waterproofing to wet area", "Waterproofing to wet area floor and walls, turned up min. 150 mm (to 1 800 mm in shower), to manufacturer's spec"),
    ("Tanking to retaining wall", "Bituminous tanking to retaining wall face with drainage board and subsoil drain"),
    ("Flashing (lead-free)", "Flashing lapped min. 150 mm under roof sheeting, sealed and fixed to manufacturer's spec"),
]

# ------------------------------------------------------------------ walls
CATALOG["Masonry walls"] = [
    ("110 mm single skin face brick", "110 mm single skin face brick wall to SANS 10400-K, brickforce at every 4th course, wall ties per spec"),
    ("110 mm single skin plaster brick", "110 mm single skin plaster brick wall to SANS 10400-K, brickforce at every 4th course"),
    ("110 mm brick, internal wall", "110 mm brick internal wall to SANS 10400-K, brickforce at every 4th course"),
    ("220 mm solid double skin", "220 mm double skin brick wall, 110 mm leaves bonded as detailed, brickforce at every 4th course (SANS 10400-K)"),
    ("270 mm cavity wall (110 + 50 + 110)", "Cavity wall: 110 mm brick, 50 mm cavity, 110 mm brick; wall ties to SANS 28 at spacing per SANS 10400-K; cavity kept clear of mortar droppings"),
    ("290 mm cavity wall (110 + 70 + 110)", "Cavity wall: 110 mm brick, 70 mm cavity, 110 mm brick; wall ties to SANS 28 at spacing per SANS 10400-K"),
    ("90 mm concrete block (SANS 1215)", "90 mm concrete masonry units to SANS 1215, brickforce at every 4th course (SANS 10400-K)"),
    ("140 mm hollow concrete block", "140 mm hollow concrete masonry units to SANS 1215, brickforce at every 4th course, cells grouted where Eng. requires (SANS 10400-K)"),
    ("190 mm hollow concrete block", "190 mm hollow concrete masonry units to SANS 1215, reinforced and grouted as Eng. design (SANS 10400-K)"),
    ("Retaining wall (to Eng.)", "Retaining wall to Eng. design, with subsoil drain and weep holes"),
    ("Freestanding / boundary wall", "Freestanding wall to Eng. design with piers and movement joints at max. 6 m centres"),
    ("Parapet wall", "Parapet wall to Eng. design, capped and flashed, with DPC at base (SANS 10400-K)"),
    ("Masonry with plaster both sides", "Masonry wall plastered both sides, to SANS 10400-K, brickforce at every 4th course"),
    ("Existing wall (to remain)", "Existing wall to remain, make good to match"),
    ("Brick on edge / soldier course", "Brick on edge course, bedded and jointed to match the wall"),
    ("Mortar joints 10 mm", "10 mm mortar joints, struck flush / raked as specified (SANS 10400-K)"),
]

CATALOG["Wall reinforcing, ties, lintels"] = [
    ("Brickforce 75 mm, every 4th course", "Brickforce reinforcing 75 mm wide in every 4th course of masonry (SANS 10400-K)"),
    ("Brickforce 115 mm, every 4th course", "Brickforce reinforcing 115 mm wide in every 4th course of masonry (SANS 10400-K)"),
    ("Brickforce above & below openings", "Brickforce in the 2 courses above and below openings, extending 600 mm beyond reveals (SANS 10400-K)"),
    ("Brickforce under roof plate", "Brickforce in the top 3 courses under the wall plate (SANS 10400-K)"),
    ("Wall ties (cavity)", "Cavity wall ties to SANS 28, spaced per SANS 10400-K, staggered"),
    ("Wall ties (stainless)", "Stainless steel cavity wall ties, spaced per SANS 10400-K, staggered"),
    ("Precast lintel", "Precast concrete lintel over opening, min. 150 mm bearing each end, to manufacturer's spec (SANS 10400-K)"),
    ("RC lintel 230 x 230", "230 x 230 mm reinforced concrete lintel over opening to Eng. design, min. 25 MPa, cover per SANS 10100-1"),
    ("RC lintel 110 x 150", "110 x 150 mm reinforced concrete lintel to Eng. design, cover per SANS 10100-1"),
    ("Steel angle lintel", "Steel angle lintel to Eng. design, hot-dip galvanised (SANS 121), min. 150 mm bearing"),
    ("Brick arch / soldier lintel", "Brick lintel with steel support angle to Eng. design"),
    ("Concrete ring beam", "Reinforced concrete ring beam to Eng. design, min. 25 MPa (SANS 10100-1)"),
    ("Movement joint in masonry", "Vertical movement joint with compressible filler and sealant, max. 6 m centres (SANS 10400-K)"),
    ("Pilaster / column", "Reinforced masonry or concrete pilaster to Eng. design"),
    ("Anchor straps (roof to wall)", "Galvanised straps anchoring wall plate to masonry, embedded 300 mm (SANS 10400-K, SANS 10400-L)"),
]

CATALOG["Plaster, paint and finishes"] = (
    [(f"{t} mm plaster and paint",
      f"{t} mm plaster and paint finish to specification") for t in (12, 15, 16, 20)] +
    [("Plaster to wet area", "Waterproof plaster and tiles to wet area, to manufacturer's spec"),
     ("External plaster and paint", "External plaster, two coats, with 2 coats exterior acrylic paint to manufacturer's spec"),
     ("Face brick, unpainted", "Face brick left exposed, joints struck flush, sealed to manufacturer's spec"),
     ("Skim coat", "Skim coat finish ready for paint"),
     ("Ceramic wall tiles", "Ceramic wall tiles on adhesive to manufacturer's spec, to 1 800 mm in showers"),
     ("Cladding (fibre-cement)", "Fibre-cement cladding boards fixed to treated battens, to manufacturer's spec (SANS 803)"),
     ("Timber cladding", "Timber cladding to specification, H3 treated (SANS 10005), fixed with stainless steel fixings"),
     ("Wall paint (PVA)", "2 coats PVA paint on primer to specification"),
     ("Enamel paint (trims)", "Enamel paint on primer to timber and steel trims"),
     ("Textured finish", "Textured plaster finish to manufacturer's spec")])

# ------------------------------------------------------------------ insulation
CATALOG["Insulation"] = (
    [(f"{t} mm glasswool above ceiling",
      f"{t} mm Think Pink Aerolite or similar glasswool insulation, achieving min. R-value per SANS 10400-XA, installed above ceiling")
     for t in (75, 100, 135, 150, 170, 200)] +
    [(f"{t} mm EPS board", f"{t} mm EPS insulation board or similar, achieving min. R-value per SANS 10400-XA")
     for t in (25, 40, 50, 75)] +
    [(f"{t} mm XPS board", f"{t} mm XPS insulation board or similar, achieving min. R-value per SANS 10400-XA")
     for t in (25, 40, 50, 75)] +
    [(f"{t} mm PIR board", f"{t} mm PIR insulation board or similar, achieving min. R-value per SANS 10400-XA")
     for t in (25, 40, 50)] +
    [("Reflective foil sarking (roof)", "Reflective foil sarking laid over trusses under roof sheeting, lapped and taped, to manufacturer's spec (SANS 10400-XA)"),
     ("Foil-faced insulation under roof sheets", "Foil-backed insulation blanket under roof sheeting, to manufacturer's spec, achieving min. R-value per SANS 10400-XA"),
     ("Cavity insulation board", "Cavity insulation board fixed to inner leaf with clips, achieving min. R-value per SANS 10400-XA"),
     ("Perimeter slab-edge insulation", "Perimeter slab-edge insulation board, achieving min. R-value per SANS 10400-XA"),
     ("Under-slab insulation", "Insulation board below slab, achieving min. R-value per SANS 10400-XA, over DPM"),
     ("Insulation to wall (internal)", "Insulated lining on battens to inside face of wall, achieving min. R-value per SANS 10400-XA"),
     ("Acoustic insulation", "Acoustic insulation in cavity to manufacturer's spec"),
     ("Hot-water pipe insulation", "Hot-water pipe insulation, min. R-value per SANS 10400-XA, UV-protected outdoors")])

# ------------------------------------------------------------------ roof
CATALOG["Roof covering"] = [
    ("Widedek 760 Charcoal", "Widedek 760 Charcoal roof sheeting on 76 x 50 SA Pine purlins @ 1 200 mm max. to manufacturer's spec. (SANS 10400-L)"),
    ("Widedek 760 Chromadek", "Widedek 760 Chromadek roof sheeting on 76 x 50 SA Pine purlins @ 1 200 mm max. to manufacturer's spec. (SANS 10400-L)"),
    ("IBR 0.5 mm Chromadek", "0.5 mm IBR Chromadek roof sheeting on purlins @ 1 200 mm max., fixed per manufacturer's spec (SANS 10400-L)"),
    ("IBR 0.58 mm galvanised", "0.58 mm IBR galvanised roof sheeting on purlins @ 1 200 mm max., fixed per manufacturer's spec (SANS 10400-L)"),
    ("Corrugated roof sheeting", "Corrugated roof sheeting on purlins @ 900 mm max., fixed per manufacturer's spec (SANS 10400-L)"),
    ("Klip-lok / concealed fix", "Concealed-fix roof sheeting on purlins to manufacturer's spec (SANS 10400-L)"),
    ("Concrete roof tiles", "Concrete roof tiles on 38 x 38 mm battens at gauge to manufacturer's spec, clipped and ridge-bedded (SANS 10400-L)"),
    ("Clay roof tiles", "Clay roof tiles on 38 x 38 mm battens at gauge to manufacturer's spec (SANS 10400-L)"),
    ("Steel tile sheeting", "Steel tile profile sheeting fixed to battens to manufacturer's spec (SANS 10400-L)"),
    ("Thatch roof", "Thatch roof to specialist's spec, fire-retardant treated, min. 45° pitch (SANS 10400-L, SANS 10400-T)"),
    ("Fibre-cement sheeting", "Fibre-cement roof sheeting on purlins to manufacturer's spec (SANS 10400-L)"),
    ("Translucent sheet", "Translucent roof sheet to match profile, fixed per manufacturer's spec"),
    ("Flat roof (concrete + waterproofing)", "Concrete flat roof slab to Eng. design with screed to falls 1:80 and torch-on waterproofing (SANS 10400-L)"),
    ("Ridge capping", "Ridge capping to match sheeting, lapped and sealed per manufacturer's spec"),
    ("Valley gutter / flashing", "Valley gutter in galvanised steel, lapped and sealed per manufacturer's spec (SANS 10400-L)"),
    ("Apron flashing", "Apron flashing to wall, chased into masonry and sealed (SANS 10400-L)"),
    ("Roof pitch note", "Roof pitch to roof sheeting manufacturer's min. pitch"),
]

CATALOG["Purlins and battens"] = [
    ("76 x 50 purlin @ 1 200", "76 x 50 SA Pine purlins to SANS 1783, H3 treated (SANS 10005), @ 1 200 mm max. centres, fixed to trusses per engineer's design (SANS 10400-L)"),
    ("76 x 50 purlin @ 900", "76 x 50 SA Pine purlins to SANS 1783, H3 treated (SANS 10005), @ 900 mm max. centres, fixed to trusses per engineer's design (SANS 10400-L)"),
    ("50 x 50 purlin @ 1 200", "50 x 50 SA Pine purlins to SANS 1783, H3 treated (SANS 10005), @ 1 200 mm max. centres, fixed to trusses per engineer's design (SANS 10400-L)"),
    ("50 x 76 purlin @ 1 200", "50 x 76 SA Pine purlins to SANS 1783, H3 treated (SANS 10005), @ 1 200 mm max. centres (SANS 10400-L)"),
    ("38 x 38 batten", "38 x 38 mm timber battens, H3 treated, fixed to trusses with corrosion-resistant nails at gauge to manufacturer's spec"),
    ("38 x 50 batten", "38 x 50 mm timber battens, H3 treated (SANS 10005), fixed to trusses at gauge to manufacturer's spec"),
    ("38 x 38 ceiling brandering @ 400", "38 x 38 mm ceiling brandering, max. 400 mm c/c for gypsum (SANS 10400-L), fixed to trusses"),
    ("38 x 38 ceiling brandering @ 300", "38 x 38 mm ceiling brandering, max. 300 mm c/c for fibre-cement (SANS 10400-L), fixed to trusses"),
    ("Steel Z purlin", "Cold-formed galvanised steel Z purlins to Eng. design and manufacturer's spec, @ 1 200 mm max. centres"),
    ("Steel C purlin", "Cold-formed galvanised steel C purlins to Eng. design and manufacturer's spec"),
    ("Counter-batten", "Counter-battens at rafter positions, H3 treated (SANS 10005), to manufacturer's spec"),
    ("Purlin cleat", "Galvanised purlin cleat fixed to truss, per Eng. design"),
]

CATALOG["Roof timber and structure"] = [
    ("Prefabricated roof trusses", "Prefabricated roof trusses to engineer's structural design (SANS 10400-L)"),
    ("Trusses @ 1 000 mm centres", "Prefabricated roof trusses @ 1 000 mm centres to engineer's design (SANS 10400-L)"),
    ("Trusses @ 1 200 mm centres", "Prefabricated roof trusses @ 1 200 mm centres to engineer's design (SANS 10400-L)"),
    ("Trusses @ 760 mm centres", "Prefabricated roof trusses @ 760 mm centres to engineer's design (SANS 10400-L)"),
    ("38 x 114 rafter", "38 x 114 SA Pine rafters to SANS 1783, H3 treated (SANS 10005), to Eng. design (SANS 10400-L)"),
    ("38 x 152 rafter", "38 x 152 SA Pine rafters to SANS 1783, H3 treated (SANS 10005), to Eng. design (SANS 10400-L)"),
    ("50 x 152 rafter", "50 x 152 SA Pine rafters to SANS 1783, H3 treated (SANS 10005), to Eng. design (SANS 10400-L)"),
    ("50 x 228 rafter", "50 x 228 SA Pine rafters to SANS 1783, H3 treated (SANS 10005), to Eng. design (SANS 10400-L)"),
    ("114 x 38 wall plate", "114 x 38 SA Pine wall plate, H3 treated (SANS 10005), anchored to trusses with galvanised strap at 2 m centres, embedded 300 mm into masonry (SANS 10400-K, SANS 10400-L)"),
    ("76 x 38 wall plate", "76 x 38 SA Pine wall plate, H3 treated (SANS 10005), anchored with galvanised strap at 2 m centres (SANS 10400-L)"),
    ("Ridge board / beam", "SA Pine ridge board to Eng. design, H3 treated (SANS 10005)"),
    ("Truss anchor (hurricane strap)", "Galvanised hurricane strap anchoring trusses to wall plate, per Eng. design (SANS 10400-L)"),
    ("Tie beam / bracing", "Diagonal and web bracing to truss manufacturer's design (SANS 10400-L)"),
    ("Timber beam (SA Pine)", "SA Pine timber beam to SANS 1783, H3 treated (SANS 10005), to Eng. design"),
    ("Glulam beam", "Glue-laminated timber beam to Eng. design and manufacturer's spec"),
    ("Steel truss / portal frame", "Steel roof truss or portal frame to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Timber, existing", "Existing timber to remain; replace affected members with H3 treated SA Pine"),
]

CATALOG["Ceilings"] = (
    [(f"{t} mm gypsum ceiling board",
      f"{t} mm gypsum ceiling board on brandering at max. centres per manufacturer's spec (SANS 10400-L)")
     for t in ("6.4", "9.5", "12.5")] +
    [(f"{t} mm fibre-cement ceiling",
      f"{t} mm fibre-cement ceiling board on brandering at max. 300 mm c/c per manufacturer's spec (SANS 803)")
     for t in ("4.5", "6")] +
    [("Ceiling board on brandering", "Ceiling board on brandering at max. centres per manufacturer's spec (SANS 10400-L)"),
     ("Suspended ceiling (grid)", "Suspended grid ceiling with lay-in tiles, to manufacturer's spec"),
     ("Cornice", "Cornice to match ceiling, fixed and filled, ready for paint"),
     ("Bulkhead", "Bulkhead framed in treated timber or steel with board lining, to specification"),
     ("Ceiling access hatch", "Ceiling access hatch 600 x 600 mm, insulated to match the ceiling"),
     ("Bulkhead - shadow gap", "Shadow-gap detail between wall and ceiling, to specification"),
     ("Soffit lining (eaves)", "Eaves soffit lined with 6 mm fibre-cement board, vented, to manufacturer's spec (SANS 803)"),
     ("Vapour barrier", "Vapour barrier/foil under insulation, lapped and taped, to manufacturer's spec")])

CATALOG["Fascias, gutters, rainwater"] = [
    ("225 x 22 SA Pine fascia", "225 x 22 SA Pine fascia board, H3 treated (SANS 10005), fixed with stainless steel screws, painted"),
    ("175 mm fibre-cement fascia", "175 mm fibre-cement fascia board (Nutec or similar) to SANS 803, fixed with stainless steel screws"),
    ("200 mm fibre-cement fascia", "200 mm fibre-cement fascia board (Nutec or similar) to SANS 803, fixed with stainless steel screws"),
    ("210 mm fibre-cement fascia", "210 mm fibre-cement fascia board (Nutec or similar) to SANS 803, fixed with stainless steel screws"),
    ("225 mm fibre-cement fascia", "225 mm fibre-cement fascia board (Nutec or similar) to SANS 803, fixed with stainless steel screws"),
    ("Barge board", "Barge board, H3 treated or fibre-cement, fixed with stainless steel screws, to specification"),
    ("100 mm half-round gutter", "100 mm half-round aluminium gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R)"),
    ("120 mm half-round gutter", "120 mm half-round aluminium gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R)"),
    ("125 mm half-round gutter", "125 mm half-round gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R)"),
    ("150 mm ogee / box gutter", "150 mm ogee gutter to manufacturer's spec, min. 1:500 fall to downpipe (SANS 10400-R)"),
    ("Concealed box gutter", "Concealed box gutter, lined and waterproofed, with overflow, to Eng. design (SANS 10400-R)"),
    ("75 mm downpipe", "75 mm downpipe to manufacturer's spec, connected to stormwater (SANS 10400-R)"),
    ("100 mm downpipe", "100 mm downpipe to manufacturer's spec, connected to stormwater (SANS 10400-R)"),
    ("Gutter bracket / stop end", "Gutter fixed with brackets at max. 900 mm centres, with stop ends and outlets"),
    ("Splash block / apron", "Splash block or concrete apron below downpipe, discharging away from the building"),
    ("Eaves overhang 600 mm", "Roof overhang 600 mm, with fascia and soffit as detailed"),
]

# ------------------------------------------------------------------ floors, finishes
CATALOG["Screeds and floor finishes"] = (
    [(f"{t} mm sand-cement screed",
      f"{t} mm sand-cement screed, uniform thickness, movement joints per specification") for t in (25, 30, 40, 50, 65)] +
    [("Ceramic / porcelain floor tiles", "Ceramic or porcelain floor tiles on adhesive over screed, to specification"),
     ("Polished concrete floor", "Power-floated polished concrete floor, sealed, control joints as detailed"),
     ("Vinyl / laminate floor", "Vinyl or laminate flooring on underlay over screed, to manufacturer's spec"),
     ("Timber floor on joists", "Timber floor boards on joists, H3 treated (SANS 10005), ventilated underfloor space (SANS 10400-J)"),
     ("Engineered timber floor", "Engineered timber flooring on underlay, to manufacturer's spec"),
     ("Carpet", "Carpet on underlay, to specification"),
     ("Epoxy floor coating", "Epoxy floor coating on prepared concrete, to manufacturer's spec"),
     ("Skirting", "Skirting to specification, fixed and painted"),
     ("Threshold / transition strip", "Threshold or transition strip between different floor finishes"),
     ("Underfloor heating screed", "Screed over underfloor heating, to manufacturer's spec")])

CATALOG["Windows, doors, openings"] = [
    ("Aluminium window", "Powder-coated aluminium window to manufacturer's spec, glazing to SANS 10400-N"),
    ("Aluminium sliding door", "Powder-coated aluminium sliding door, safety glazing to SANS 10400-N, to manufacturer's spec"),
    ("Aluminium stacking door", "Powder-coated aluminium stacking door, safety glazing to SANS 10400-N, to manufacturer's spec"),
    ("Timber window", "Timber window frame, H3 treated, sealed and painted, glazing to SANS 10400-N"),
    ("Steel window / door", "Steel window or door frame, galvanised and painted, glazing to SANS 10400-N"),
    ("Timber door (hollow-core)", "Hollow-core timber door in frame, to specification"),
    ("Timber door (solid)", "Solid timber door in frame, to specification"),
    ("Steel door frame", "Pressed steel door frame, built in as wall rises, to specification"),
    ("Garage door", "Garage door to manufacturer's spec, with lintel to Eng. design"),
    ("Double glazing (IGU)", "Double glazed units to manufacturer's spec, achieving min. SANS 10400-XA requirements"),
    ("Safety glass", "Safety glazing to SANS 10400-N (laminated or toughened)"),
    ("Window cill (brick)", "Brick cill, sloped away from window, with DPC under, min. 15° slope"),
    ("Window cill (precast)", "Precast concrete cill with drip groove, bedded on DPC, sloped away from the window"),
    ("Reveal / frame seal", "Frame sealed to reveal with flexible sealant over backing rod"),
    ("Opening: min. size noted", "Opening size as scheduled; confirm on site before ordering frames"),
]

# ------------------------------------------------------------------ steel, timber, stairs
CATALOG["Steel and structural"] = [
    ("Steel beam (hot-dip galvanised)", "Steel beam to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Steel beam (painted)", "Steel beam to Eng. design, primed and painted"),
    ("Steel column 100 x 100 SHS", "100 x 100 mm SHS steel column to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Steel column 150 x 150 SHS", "150 x 150 mm SHS steel column to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Steel angle 50 x 50", "50 x 50 mm steel angle to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Steel plate / cleat", "Steel plate or cleat to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Steel flat bar", "Steel flat bar to Eng. design, hot-dip galvanised (SANS 121)"),
    ("Base plate and anchor bolts", "Base plate with chemical or cast-in anchor bolts to Eng. design"),
    ("Reinforcement bars (Y12)", "Y12 reinforcing bars at spacing per Eng. design (SANS 10100-1)"),
    ("Reinforcement bars (Y10)", "Y10 reinforcing bars at spacing per Eng. design (SANS 10100-1)"),
    ("Mesh reinforcement", "Mesh reinforcement as per Eng. design, cover per SANS 10100-1, on spacers"),
    ("Concrete cover 30 mm", "Min. 30 mm concrete cover to reinforcement (SANS 10100-1)"),
    ("Concrete column", "Reinforced concrete column to Eng. design, min. 25 MPa (SANS 10100-1)"),
    ("Pre-engineered Eng. detail", "As per Engineer's detail and design"),
]

CATALOG["Stairs, balustrades, safety"] = [
    ("Balustrade 1 000 mm high", "Balustrade min. 1 000 mm high, openings max. 100 mm, to Eng. design (SANS 10400-D, SANS 10400-M)"),
    ("Handrail 1 000 mm", "Handrail at 1 000 mm height, continuous, to specification (SANS 10400-M)"),
    ("Stair riser max. 200", "Stair risers max. 200 mm and goings min. 250 mm, min. 2 000 mm headroom (SANS 10400-M)"),
    ("Concrete stair", "Reinforced concrete stair to Eng. design (SANS 10100-1, SANS 10400-M)"),
    ("Timber stair", "Timber stair, H3 treated where exposed, to specification (SANS 10400-M)"),
    ("Steel stair", "Steel stair to Eng. design, hot-dip galvanised (SANS 121, SANS 10400-M)"),
    ("Non-slip nosing", "Non-slip nosing to treads, to specification"),
    ("Landing", "Landing with level floor min. as stair width (SANS 10400-M)"),
    ("Ramp (max. 1:12)", "Ramp max. gradient 1:12 with handrails (SANS 10400-S)"),
    ("Fire-rated element", "Fire-rated construction to SANS 10400-T and as certified by the fire engineer"),
]

CATALOG["General notes"] = [
    ("To Eng. design", "To Eng. design"),
    ("To manufacturer's spec", "To manufacturer's spec"),
    ("Existing, to remain", "Existing, to remain"),
    ("Existing, to be removed", "Existing, to be removed and made good"),
    ("Confirm on site", "Confirm on site before ordering"),
    ("N.I.C.", "Not in contract"),
    ("Typical detail", "Typical detail"),
    ("Do not scale", "Do not scale from drawing: use figured dimensions only"),
    ("All dimensions in mm", "All dimensions in mm unless noted"),
    ("Sealant / flexible joint", "Flexible sealant over backing rod, to manufacturer's spec"),
    ("Level / datum", "Finished floor level (FFL) as indicated on the plan"),
    ("Fall to drain", "Fall 1:100 to drain"),
]

# ------------------------------------------------------------------ guess the category from the material
GUESS = [
    (r"dpm|dpc|membrane|damp|waterproof|torch", "Damp-proofing and waterproofing"),
    (r"insul|isotherm|aerolite|glasswool|rockwool|polystyrene|eps|xps|pir|iso.?board", "Insulation"),
    (r"purlin|batten|brander", "Purlins and battens"),
    (r"truss|rafter|wall.?plate|timber|wood|pine|beam", "Roof timber and structure"),
    (r"sheet|ibr|widedek|chromadek|roof|tile|corrug", "Roof covering"),
    (r"fascia|gutter|barge|downpipe", "Fascias, gutters, rainwater"),
    (r"gypsum|ceiling|board", "Ceilings"),
    (r"screed|floor.?finish|vinyl|laminate", "Screeds and floor finishes"),
    (r"plaster|render|skim|paint|finish", "Plaster, paint and finishes"),
    (r"lintel|brickforce|tie", "Wall reinforcing, ties, lintels"),
    (r"brick|masonry|block|wall", "Masonry walls"),
    (r"found|footing|strip|pad", "Foundations"),
    (r"slab|conc|floor", "Concrete slabs and floors"),
    (r"steel|metal|angle|alumin", "Steel and structural"),
    (r"gravel|stone|soil|earth|fill|sand|hardcore|ground", "Ground and fill"),
    (r"window|door|glaz", "Windows, doors, openings"),
    (r"stair|balustrade|rail", "Stairs, balustrades, safety"),
]


def categories():
    return list(CATALOG.keys())


def guess_category(layer="", pattern=""):
    hay = f"{pattern} {layer}".lower().replace("_", " ")
    for rx, cat in GUESS:
        if re.search(rx, hay):
            return cat
    return "General notes"


def first_number(label):
    m = re.search(r"\d+(?:\.\d+)?", label)
    return float(m.group(0)) if m else None


def nearest_index(options, mm):
    """Index of the option whose size (the first number in its label) is closest to a thickness measured from the drawing."""
    best, bi = None, 0
    for i, (lab, _note) in enumerate(options):
        v = first_number(lab)
        if v is None:
            continue
        d = abs(v - mm)
        if best is None or d < best:
            best, bi = d, i
    return bi


def count():
    return sum(len(v) for v in CATALOG.values())
