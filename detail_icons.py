"""Families and icons for the catalog picker. Only emoji from the older Unicode releases, so they show on every Windows 10 / 11 PC."""

FAMILIES = [
    ("\U0001F3D7️", "Foundations and floors", ["Foundations", "Ground and fill", "Concrete slabs and floors",
                                                    "Screeds and floor finishes", "Steel and structural"]),
    ("\U0001F9F1", "Walls", ["Masonry walls", "Masonry details", "Wall reinforcing, ties, lintels",
                             "Light-weight and framed walls", "Plaster, paint and finishes", "Stone, coping and cladding"]),
    ("\U0001F3E0", "Roof and ceiling", ["Roof covering", "Purlins and battens", "Roof timber and structure",
                                        "Roofs: flat roofs and waterproofing", "Ceilings", "Fascias, gutters, rainwater"]),
    ("\U0001F4A7", "Waterproofing and insulation", ["Damp-proofing and waterproofing", "Insulation",
                                                    "Thermal and energy (SANS 10400-XA)"]),
    ("\U0001F6AA", "Windows, doors and joinery", ["Windows, doors, openings", "Window and door details",
                                                  "Joinery, trims and internal finishes", "Timber and carpentry"]),
    ("\U0001F527", "Services and outside", ["Wet areas and plumbing", "Services: energy, solar, electrical",
                                            "External works", "Stairs, balustrades, safety", "Fire and safety"]),
    ("\U0001F3A8", "Finishes and general", ["Paint, sealants and coatings", "General notes"]),
    ("\U0001F3F7️", "South African products", ["SA products: insulation", "SA products: waterproofing (a.b.e.)",
                                                    "SA products: boards, cement and masonry"]),
    ("⭐", "My specs", ["My specs"]),
]

ICONS = {
    "Foundations": "⛏️", "Ground and fill": "⛰️", "Concrete slabs and floors": "\U0001F3E2",
    "Screeds and floor finishes": "\U0001F4D0", "Steel and structural": "\U0001F529",
    "Masonry walls": "\U0001F9F1", "Masonry details": "\U0001F50D", "Wall reinforcing, ties, lintels": "\U0001F517",
    "Light-weight and framed walls": "\U0001F528", "Plaster, paint and finishes": "\U0001F58C️",
    "Stone, coping and cladding": "\U0001F5FF",
    "Roof covering": "\U0001F3E0", "Purlins and battens": "\U0001F4CF", "Roof timber and structure": "\U0001F332",
    "Roofs: flat roofs and waterproofing": "☔", "Ceilings": "☁️", "Fascias, gutters, rainwater": "\U0001F327️",
    "Damp-proofing and waterproofing": "\U0001F4A7", "Insulation": "❄️", "Thermal and energy (SANS 10400-XA)": "\U0001F321️",
    "Windows, doors, openings": "\U0001F5BC️", "Window and door details": "\U0001F511",
    "Joinery, trims and internal finishes": "\U0001F6E0️", "Timber and carpentry": "\U0001F333",
    "Wet areas and plumbing": "\U0001F6BF", "Services: energy, solar, electrical": "⚡", "External works": "\U0001F333",
    "Stairs, balustrades, safety": "\U0001F53C", "Fire and safety": "\U0001F525",
    "Paint, sealants and coatings": "\U0001F3A8", "General notes": "\U0001F4DD",
    "SA products: insulation": "❄️", "SA products: waterproofing (a.b.e.)": "\U0001F4A7",
    "SA products: boards, cement and masonry": "\U0001F4E6", "My specs": "⭐",
}

EXAMPLES = ["concrete coping", "stone cill", "170 slab", "DPC", "50 x 50 purlin", "IsoBoard", "gutter"]


def family_of(group):
    for ic, name, groups in FAMILIES:
        if group in groups:
            return name
    return None
