"""Project dashboard for a folder of details: totals, wording check, submission checklist, submission pack.

The checklist only reads the notes the tool wrote (and what you checked). It does not replace the engineer's or
the local authority's own requirements: it shows what the notes do and do not say."""
import re
import shutil
from pathlib import Path

RV = re.compile(r"R-value\s+([\d.]+)")
DPC = re.compile(r"\b(dpc|dpm|damp[- ]?proof|waterproof)", re.I)
DEPTH = re.compile(r"(\d+\s*mm\s*(deep|below|min\. depth|depth))|(depth\s*(of)?\s*\d+)|(min\.?\s*\d+\s*mm\s*deep)", re.I)


def totals(data):
    t = {"details": len(data), "notes": 0, "ok": 0, "verify": 0, "todo": 0}
    for d in data.values():
        for _c, _n, _t, st in d["notes"]:
            t["notes"] += 1
            if st in ("ok", "verify", "todo"):
                t[st] += 1
    return t


def checklist(data, zone=None, findings=None):
    """-> list of (state, title, text); state: y = fine, w = look at it, n = missing / wrong"""
    out = []
    names = sorted(data)

    def where(pred):
        return [d for d in names if any(pred(c, n, t) for c, n, t, _s in data[d]["notes"])]

    # waterproofing / DPC
    have = where(lambda c, n, t: DPC.search(t))
    lack = [d for d in names if d not in have]
    if not names:
        pass
    elif not lack:
        out.append(("y", "Waterproofing / DPC noted", "on every detail"))
    elif have:
        out.append(("w", "Waterproofing / DPC noted", "on " + ", ".join(have) + ". Not on " + ", ".join(lack) + " (fine if they are not ground-level or wet details)"))
    else:
        out.append(("n", "Waterproofing / DPC noted", "not found on any detail"))

    # insulation R-values against the zone
    for label, key, want_key in (("roof / ceiling", "roof", "roof"), ("masonry wall", "wall", "heavy"), ("light-weight wall", "light", "light")):
        found, bad = [], []
        for d in names:
            for _c, _n, t, _s in data[d]["notes"]:
                if label in t and RV.search(t):
                    v = float(RV.search(t).group(1))
                    found.append(d)
                    want = (zone or {}).get(want_key)
                    if want and abs(v - float(want)) > 1e-6:
                        bad.append(f"{d} (R {v:g}, zone needs {float(want):g})")
        title = f"{label.capitalize()} insulation R-value"
        if bad:
            out.append(("n", title, "does not match the climate zone on " + "; ".join(bad)))
        elif found:
            out.append(("y", title, "on " + ", ".join(sorted(set(found))) + (f"; matches zone {zone['zone']}" if zone and zone.get("zone") else "")))
    noval = where(lambda c, n, t: re.search(r"insulation", t, re.I) and not RV.search(t) and "foundation" not in t.lower())
    if noval:
        out.append(("w", "Insulation without an R-value", "on " + ", ".join(noval)))

    # foundation depth
    fnd = [(d, t) for d in names for c, n, t, _s in data[d]["notes"] if re.search(r"foundation|footing", t, re.I)]
    if fnd:
        nodepth = sorted({d for d, t in fnd if not DEPTH.search(t)})
        if nodepth:
            out.append(("n", "Foundation depth stated", "no depth in the foundation note on " + ", ".join(nodepth)))
        else:
            out.append(("y", "Foundation depth stated", "on " + ", ".join(sorted({d for d, _t in fnd}))))

    # what still needs the author
    ver = {d: sum(1 for *_x, s in data[d]["notes"] if s == "verify") for d in names}
    ver = {d: n for d, n in ver.items() if n}
    if ver:
        out.append(("w", "Products and sizes checked", ", ".join(f"{d}: {n}" for d, n in ver.items()) + " note(s) still to verify against the data sheet or Agrément certificate"))
    elif names:
        out.append(("y", "Products and sizes checked", "nothing flagged"))
    todo = {d: sum(1 for *_x, s in data[d]["notes"] if s == "todo") for d in names}
    todo = {d: n for d, n in todo.items() if n}
    if todo:
        out.append(("n", "Specifications chosen", ", ".join(f"{d}: {n}" for d, n in todo.items()) + " part(s) have no specification yet"))
    elif names:
        out.append(("y", "Specifications chosen", "every part has one"))
    if findings is not None:
        if findings:
            out.append(("w", "Wording consistent", f"{len(findings)} material(s) worded differently on different details"))
        elif names:
            out.append(("y", "Wording consistent", "same material, same wording on every detail"))
    return out


def checklist_html(items, title):
    col = {"y": "#1b7f4f", "w": "#b07500", "n": "#b3202f"}
    sym = {"y": "OK", "w": "CHECK", "n": "MISSING"}
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rows = "".join(f"<tr><td style='color:{col[s]};font-weight:bold;padding:4px 10px 4px 0'>{sym[s]}</td>"
                   f"<td style='padding:4px 10px 4px 0'><b>{esc(t)}</b><br>{esc(x)}</td></tr>" for s, t, x in items)
    return (f"<h2>Submission checklist</h2><p>{esc(title)}</p><table>{rows}</table>"
            "<p style='color:#666'>This lists what the notes say and do not say. It does not replace the engineer's design, "
            "the local authority's requirements or your own checking of each note.</p>")


def build_pack(folder_name, out_dir, data, project_pdf, checklist_pdf):
    """copy the noted drawings, each detail's schedule, the project schedule and the checklist into one folder"""
    pack = Path(out_dir) / (folder_name + "_submission_pack")
    pack.mkdir(parents=True, exist_ok=True)
    copied = []
    for d in sorted(data):
        for suffix in ("_noted.dwg", "_noted.dxf", "_notes_schedule.pdf"):
            f = Path(out_dir) / (d + suffix)
            if f.exists():
                shutil.copy(f, pack / f.name)
                copied.append(f.name)
    for f in (project_pdf, checklist_pdf):
        if f and Path(f).exists():
            shutil.copy(f, pack / Path(f).name)
            copied.append(Path(f).name)
    return pack, copied
