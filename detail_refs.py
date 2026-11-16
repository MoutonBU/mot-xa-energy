"""Part-level references for the catalog groups, and the standard detail templates.

References name the SANS 10400 part (or other document) that governs that kind of element. They are NOT clause
numbers: the person issuing the drawing must confirm the clause in the current edition. Nothing here is invented
to look precise - a group with no confident reference shows no reference."""
import re

NHBRC = "NHBRC Home Building Manual"

# group -> (short tag shown in the list, long text shown in the tooltip)
REFS = {
    "Foundations": ("SANS 10400-H", f"SANS 10400 Part H (foundations); {NHBRC}"),
    "Ground and fill": ("SANS 10400-H/J", f"SANS 10400 Parts H (foundations) and J (floors); {NHBRC}"),
    "Concrete slabs and floors": ("SANS 10400-J", f"SANS 10400 Part J (floors); {NHBRC}"),
    "Screeds and floor finishes": ("SANS 10400-J", "SANS 10400 Part J (floors)"),
    "Damp-proofing and waterproofing": ("SANS 10400-J/K/L", f"SANS 10400 Parts J, K and L, depending on the element; {NHBRC}"),
    "Masonry walls": ("SANS 10400-K", f"SANS 10400 Part K (walls); {NHBRC}"),
    "Masonry details": ("SANS 10400-K", f"SANS 10400 Part K (walls); {NHBRC}"),
    "Wall reinforcing, ties, lintels": ("SANS 10400-K", f"SANS 10400 Part K (walls); {NHBRC}"),
    "Light-weight and framed walls": ("SANS 10400-K/B", "SANS 10400 Parts K (walls) and B (structural design)"),
    "Plaster, paint and finishes": ("SANS 10400-K", "SANS 10400 Part K (walls)"),
    "Insulation": ("SANS 10400-XA", "SANS 10400 Part XA (energy usage in buildings)"),
    "Thermal and energy (SANS 10400-XA)": ("SANS 10400-XA", "SANS 10400 Part XA (energy usage in buildings)"),
    "Roof covering": ("SANS 10400-L", f"SANS 10400 Part L (roofs); {NHBRC}"),
    "Purlins and battens": ("SANS 10400-L", f"SANS 10400 Part L (roofs); {NHBRC}"),
    "Roof timber and structure": ("SANS 10400-L", f"SANS 10400 Part L (roofs); {NHBRC}"),
    "Roofs: flat roofs and waterproofing": ("SANS 10400-L", f"SANS 10400 Part L (roofs); {NHBRC}"),
    "Ceilings": ("SANS 10400-L/XA", "SANS 10400 Parts L (roofs) and XA (energy usage)"),
    "Fascias, gutters, rainwater": ("SANS 10400-L/R", "SANS 10400 Parts L (roofs) and R (stormwater)"),
    "Windows, doors, openings": ("SANS 10400-N/XA", "SANS 10400 Parts N (glazing) and XA (fenestration)"),
    "Window and door details": ("SANS 10400-N/XA", "SANS 10400 Parts N (glazing) and XA (fenestration)"),
    "Stone, coping and cladding": ("SANS 10400-K/L", "SANS 10400 Parts K (walls) and L (roofs), depending on the element"),
    "Steel and structural": ("SANS 10400-B", "SANS 10400 Part B (structural design) - the engineer's design governs"),
    "Stairs, balustrades, safety": ("SANS 10400-M/D", "SANS 10400 Parts M (stairways) and D (public safety)"),
    "Wet areas and plumbing": ("SANS 10400-P", "SANS 10400 Part P (drainage)"),
    "Services: energy, solar, electrical": ("SANS 10400-XA", "SANS 10400 Part XA; electrical wiring: SANS 10142-1"),
    "External works": ("SANS 10400-R/P", "SANS 10400 Parts R (stormwater) and P (drainage)"),
    "SA products: insulation": ("SANS 10400-XA", "SANS 10400 Part XA (energy usage in buildings); check the product's Agrement certificate"),
    "SA products: waterproofing (a.b.e.)": ("SANS 10400-J/K/L", "SANS 10400 Parts J, K and L depending on the element; follow the manufacturer's data sheet"),
    "Fire and safety": ("SANS 10400-T", "SANS 10400 Part T (fire protection)"),
}

CLAUSE_WARNING = "Part-level reference only: confirm the clause in the current edition before issuing."


def norm(txt):
    return re.sub(r"\s+", " ", (txt or "").strip().lower())


_IDX = {}


def category_of(note):
    """catalog group a note's exact wording comes from, or '' (typed or edited notes)"""
    if not _IDX:
        import detail_catalog as cat
        for k, lst in cat.CATALOG.items():
            for _lab, n in lst:
                _IDX.setdefault(norm(n), k)
    return _IDX.get(norm(note), "")


def ref_for(category):
    return REFS.get(category)


# ---------------------------------------------------------------- templates
# each step: what to click, and the words that write its note
TEMPLATES = [
    ("Parapet with concrete coping", [
        ("the concrete coping", "concrete coping"),
        ("the parapet wall", "parapet"),
        ("the waterproofing or flashing", "waterproofing"),
        ("the roof slab", "slab"),
        ("the roof insulation", "insulation")]),
    ("Slab-on-ground at the wall", [
        ("the floor slab", "slab"),
        ("the foundation", "foundation"),
        ("the hardcore / fill", "hardcore"),
        ("the damp-proof membrane", "dpm"),
        ("the brick wall", "brickwork"),
        ("the DPC in the wall", "dpc")]),
    ("Window head and cill", [
        ("the cill", "cill"),
        ("the lintel", "lintel"),
        ("the window", "window"),
        ("the wall", "brickwork")]),
    ("Pitched roof at the eaves", [
        ("the roof sheeting", "roof sheeting"),
        ("a purlin", "purlin"),
        ("the fascia", "fascia"),
        ("the gutter", "gutter"),
        ("the wall plate", "wall plate"),
        ("the ceiling", "ceiling"),
        ("the ceiling insulation", "insulation")]),
    ("Door threshold", [
        ("the threshold", "threshold"),
        ("the floor slab", "slab"),
        ("the door", "door")]),
    ("Garden / retaining wall", [
        ("the wall", "retaining wall"),
        ("the coping", "garden wall coping"),
        ("the foundation", "foundation"),
        ("the drain", "drain")]),
]
