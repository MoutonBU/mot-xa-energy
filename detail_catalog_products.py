"""South African products for the Detail Notes catalog (merged into detail_catalog.CATALOG).

Product names come from the manufacturers' own published ranges. Notes name the product "or similar approved" and
give thicknesses only where the manufacturer lists them; everything else says "per manufacturer's spec", so the
note stays correct if you substitute an equal product. Check the current data sheet and Agrement certificate
before specifying."""

SIMILAR = "or similar approved"
XA = "min. R-value per SANS 10400-XA"

EXTRA = {}

EXTRA["SA products: insulation"] = [
    ("IsoBoard 30 mm: cavity wall", f"30 mm IsoBoard polystyrene insulation board ({SIMILAR}) fixed in the cavity against the inner leaf, joints tightly butted, achieving {XA}, wall ties fitted per manufacturer's spec"),
    ("IsoBoard 30 mm: nail-up ceiling", f"30 mm IsoBoard insulation board ({SIMILAR}) nailed up as insulated ceiling to brandering, joints tightly butted, achieving {XA}"),
    ("IsoBoard 40 mm: over purlin", f"40 mm IsoBoard insulation board ({SIMILAR}) laid over purlins under the roof sheeting, joints butted and sheeting fixed through to manufacturer's spec, achieving {XA}"),
    ("IsoBoard 50 mm: inverted roof", f"50 mm IsoBoard insulation board ({SIMILAR}) above the waterproofing membrane with filter fleece and ballast, achieving {XA}"),
    ("IsoBoard 25 mm: under floor / foundation perimeter", f"25 mm IsoBoard insulation board ({SIMILAR}) at the slab edge and foundation perimeter, protected above ground, achieving {XA}"),
    ("IsoBoard: over rafter / truss", f"IsoBoard insulation board ({SIMILAR}) over rafters or trusses under the roof covering, thickness to achieve {XA}, fixed per manufacturer's spec"),
    ("IsoBoard: surface bed (under screed)", f"IsoBoard insulation board ({SIMILAR}) under the screed on the slab, over DPM, thickness to achieve {XA}"),
    ("IsoBoard: thickness to be selected", f"IsoBoard insulation board ({SIMILAR}), thickness to achieve {XA}, installed continuous with no gaps"),
    ("Isotherm insulation", f"Isotherm thermal insulation ({SIMILAR}), thickness to achieve {XA}, installed continuous with no gaps and not compressed"),
    ("Aerolite glasswool over ceiling", f"Aerolite glasswool insulation ({SIMILAR}) laid over the ceiling, thickness to achieve {XA}, continuous with no gaps and not compressed"),
    ("Insulation board (polystyrene): generic", f"Rigid polystyrene insulation board ({SIMILAR}), thickness to achieve {XA}, joints tightly butted"),
]

EXTRA["SA products: waterproofing (a.b.e.)"] = [
    ("a.b.e. abeproof liquid membrane (roof / slab)", f"a.b.e. abeproof liquid membrane on abeproof primer ({SIMILAR}), applied in the coats and thickness per manufacturer's data sheet, turned up min. 150 mm at walls and terminated under flashing"),
    ("a.b.e. super laycryl (flashings, roofs)", f"a.b.e. super laycryl liquid waterproofing reinforced with abe membrane ({SIMILAR}), at flashings, laps and junctions, per manufacturer's spec"),
    ("a.b.e. abe peel and stick membrane", f"a.b.e. peel and stick self-adhesive membrane ({SIMILAR}) over primed surface, laps per manufacturer's spec"),
    ("a.b.e. Mariseal 250 (polyurethane)", f"a.b.e. Mariseal 250 elastomeric polyurethane waterproofing ({SIMILAR}) with Mariseal Fabric 110 reinforcing at wall-floor junctions and outlets, per manufacturer's spec"),
    ("a.b.e. Duraslurry (cementitious slurry)", f"a.b.e. Duraslurry cementitious waterproofing slurry ({SIMILAR}) applied in coats per manufacturer's spec"),
    ("a.b.e. brixeal (bitumen emulsion)", f"a.b.e. brixeal bitumen emulsion ({SIMILAR}) to the concrete face behind exterior brickwork, per manufacturer's spec"),
    ("a.b.e. wallseal (breathable wall sealer)", f"a.b.e. wallseal breathable waterproofing solution ({SIMILAR}) brushed or sprayed to the wall face, per manufacturer's spec"),
    ("a.b.e. dura proof cem block (admixture)", f"a.b.e. dura proof cem block admixture ({SIMILAR}) in the cement mortar or plaster, dosed per manufacturer's spec"),
    ("a.b.e. silvakote eco (reflective top coat)", f"a.b.e. silvakote eco solar-reflective finishing coat ({SIMILAR}) over the waterproofing, per manufacturer's spec"),
    ("a.b.e. duraroof acrylic roof paint", f"a.b.e. duraroof acrylic roof paint ({SIMILAR}) to the roof covering, coats per manufacturer's spec"),
    ("a.b.e. bituseal Plastic (mastic)", f"a.b.e. bituseal Plastic bitumen mastic ({SIMILAR}) at roof laps, valleys and gutter joints, per manufacturer's spec"),
    ("a.b.e. flexothane 27 (polyurethane sealant)", f"a.b.e. flexothane 27 one-component polyurethane sealant ({SIMILAR}) to movement joints with bond breaker and backing rod, per manufacturer's spec"),
    ("a.b.e. dura grout GP", f"a.b.e. dura grout GP cement grout ({SIMILAR}) under base plates and in pockets, per manufacturer's spec"),
]

EXTRA["SA products: boards, cement and masonry"] = [
    ("Fibre-cement board (Nutec) cladding / fascia", f"Fibre-cement board (Nutec {SIMILAR}) fixed with corrosion-resistant screws, joints lapped or sealed, primed and painted, per manufacturer's spec"),
    ("Rhinoboard (ceiling / wall board)", f"Rhinoboard gypsum board (Saint-Gobain {SIMILAR}) on brandering or studs, joints taped and filled, per manufacturer's spec"),
    ("Gyproc plasterboard (partition / ceiling)", f"Gyproc plasterboard (Saint-Gobain {SIMILAR}) on framing, joints taped and filled, per manufacturer's spec"),
    ("Face brick (Corobrik)", f"Face brick (Corobrik {SIMILAR}), bonded and jointed neat, brickforce every 4th course, wall ties per spec"),
    ("Stock / plaster brick (Corobrik)", f"Plaster brick (Corobrik {SIMILAR}), bonded, brickforce every 4th course, wall ties per spec, plastered and painted"),
    ("Cement (PPC / AfriSam)", f"Portland cement (PPC, AfriSam {SIMILAR}) of the class specified by the Eng., stored dry and used fresh"),
    ("Tile adhesive (TAL / Ardex)", f"Tile adhesive (TAL, Ardex {SIMILAR}) applied to a clean, sound substrate, notched trowel and grout per manufacturer's spec"),
    ("Paint system (Plascon / Dulux)", f"Primer and two coats of paint (Plascon, Dulux {SIMILAR}) on prepared plaster, per manufacturer's spec"),
]
