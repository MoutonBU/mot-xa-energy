"""Drawing register: feed in PDFs per block or house, get a register (PDF / CSV) and the text of the issue email."""
import datetime
import html as _html
import json
import os
import re
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QMenu, QTabWidget, QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STATUSES = ["For information", "For comment", "For approval", "For council submission", "For tender", "For construction", "As built", "Superseded"]
KEYS = ("on", "no", "title", "about", "size", "scale", "rev", "rdate", "pdfdate", "by", "comment", "status", "file")
COLS = ["Send", "Drawing no.", "Drawing", "What it shows", "Size", "Scale", "Rev", "Rev date", "PDF'd", "Requested by", "What changed", "Status", "File"]
BYS = ["", "Client request", "Council request", "Engineer", "Architect (own change)", "Site / contractor"]
DATE_RE = r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4})"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def norm_date(t):
    """Any of 2026-11-17, 17/11/2026, 17.11.26, 17 Nov 2026 -> 2026-11-17 (empty if it is not a date)."""
    t = (t or "").strip()
    try:
        m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", t)
        if m:
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
        else:
            m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", t)
            if m:
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
                y += 2000 if y < 100 else 0
            else:
                m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{2,4})$", t)
                if not m or m[2].lower() not in MONTHS:
                    return ""
                d, mo, y = int(m[1]), MONTHS[m[2].lower()], int(m[3])
                y += 2000 if y < 100 else 0
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _lines_from_page(page, clip):
    """Text lines of a region, top to bottom (selectable text first, OCR when the title block is drawn as lines)."""
    words = page.get_text("words", clip=clip) or []
    rows = {}
    for x0, y0, x1, y1, w, *_r in words:
        rows.setdefault(round((y0 + y1) / 2 / 4), []).append((x0, w))
    lines = [" ".join(w for _x, w in sorted(v)) for _k, v in sorted(rows.items())]
    if sum(len(l) for l in lines) >= 25:
        return lines
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        pix = page.get_pixmap(clip=clip, dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        res, _ = RapidOCR()(img)
        rows = {}
        for box, txt, _sc in (res or []):
            yc = (box[0][1] + box[2][1]) / 2
            rows.setdefault(round(yc / 18), []).append((box[0][0], txt))
        return [" ".join(w for _x, w in sorted(v)) for _k, v in sorted(rows.items())]
    except Exception:
        return lines


def parse_titleblock(lines):
    """Drawing number, current revision with its date and description, and every revision row, from title-block text lines."""
    out = {"no": "", "title": "", "revs": [], "rev": "", "rdate": "", "rdesc": ""}
    for i, l in enumerate(lines):
        m = re.search(r"(?:drawing|dwg|sheet)\s*(?:no|nr|number|nommer)\.?\s*[:\-]?\s*([A-Za-z]{0,4}[-_. ]?\d{1,4}[A-Za-z]?(?:[-_.]\d{1,3})?)", l, re.I)
        if not m and re.search(r"(?:drawing|dwg|sheet)\s*(?:no|nr|number)\.?\s*[:\-]?\s*$", l, re.I) and i + 1 < len(lines):
            m = re.match(r"\s*([A-Za-z]{0,4}[-_. ]?\d{1,4}[A-Za-z]?)\b", lines[i + 1])
        if m:
            out["no"] = re.sub(r"[\s_.]+", "-", m.group(1).strip()).upper()
            break
    for l in lines:
        m = re.search(r"(?:drawing\s*title|dwg\s*title|title|tekening\s*titel)\s*[:\-]\s*(.{3,80})$", l, re.I)
        if m:
            out["title"] = m.group(1).strip()
            break
    for l in lines:
        m = re.match(r"^\s*(?:rev\.?\s*)?([A-Z]\d?|\d{1,2})\s+" + DATE_RE + r"\s*(.*)$", l, re.I)
        if m and norm_date(m.group(2)):
            out["revs"].append((m.group(1).upper(), norm_date(m.group(2)), m.group(3).strip(" -:")))
            continue
        m = re.match(r"^\s*" + DATE_RE + r"\s+(?:rev\.?\s*)?([A-Z]\d?|\d{1,2})\b\s*(.*)$", l, re.I)
        if m and norm_date(m.group(1)):
            out["revs"].append((m.group(2).upper(), norm_date(m.group(1)), m.group(3).strip(" -:")))
    if not out["revs"]:
        for l in lines:        # Rev ID, Change Name, Date  (the date last)
            m = re.match(r"^\s*(?:rev\.?\s*)?([A-Z]\d?|\d{1,3})\s+(.+?)\s+" + DATE_RE + r"\s*$", l, re.I)
            if m and norm_date(m.group(3)):
                out["revs"].append((m.group(1).upper(), norm_date(m.group(3)), m.group(2).strip(" -:")))
    if not out["revs"]:
        # the revision letter is sometimes lost (drawn text read by OCR): number the dated rows A, B, C ... in the order they appear
        rows = []
        for l in lines:
            m = re.match(r"^\s*" + DATE_RE + r"\s+(\S.*)$", l)
            if m and norm_date(m.group(1)):
                rows.append((norm_date(m.group(1)), m.group(2).strip(" -:")))
        out["revs"] = [(chr(65 + i), dt, ds) for i, (dt, ds) in enumerate(rows[:26])]
    if not out["revs"]:
        for l in lines:
            m = re.search(r"\brev(?:ision)?\.?\s*[:\-]?\s*([A-Z]\d?|\d{1,2})\b", l, re.I)
            if m:
                out["rev"] = m.group(1).upper()
                d = re.search(DATE_RE, l)
                out["rdate"] = norm_date(d.group(1)) if d else ""
                break
    else:
        key = lambda r: (r[1], r[0])
        cur = max(out["revs"], key=key)
        out["rev"], out["rdate"], out["rdesc"] = cur
    return out


def _revision_field(page):
    """The drawing's own revision (for example 1 or B) from the title block's 'Revision' box: the value sits under the label."""
    words = page.get_text("words") or []
    W, H = page.rect.width, page.rect.height
    for w in words:
        if w[4].lower() != "revision" or w[0] < W * 0.5 or w[1] < H * 0.4:
            continue
        same = [v for v in words if abs(v[1] - w[1]) < 4 and v[0] > w[2] and v[0] - w[2] < 40]
        if any(v[4].lower() in ("history", "date", "id") for v in same):
            continue
        below = sorted([v for v in words if 6 < v[1] - w[1] < 34 and abs(v[0] - w[0]) < 45], key=lambda v: (v[1], v[0]))
        for v in below:
            t = v[4].strip()
            if norm_date(t):
                continue
            if re.match(r"^(?:[A-Za-z]|[A-Za-z]?\d{1,3})$", t):
                return t.upper()
    return ""


def _label_value(page, label):
    """The text under a title block label such as 'Drawing Name' or 'Layout ID' (the value sits on the line below the label)."""
    words = page.get_text("words") or []
    W, H = page.rect.width, page.rect.height
    parts = label.lower().split()
    for i, w in enumerate(words):
        if w[0] < W * 0.5 or w[1] < H * 0.4 or w[4].lower() != parts[0]:
            continue
        line = [w]
        for p_ in parts[1:]:
            nx = next((v for v in words if abs(v[1] - w[1]) < 3 and 0 < v[0] - line[-1][2] < 12 and v[4].lower() == p_), None)
            if nx is None:
                break
            line.append(nx)
        if len(line) != len(parts):
            continue
        x0 = line[0][0]
        below = [v for v in words if 3 < v[1] - w[1] < 22 and x0 - 6 <= v[0] < x0 + 160]
        if not below:
            continue
        y = min(v[1] for v in below)
        txt = " ".join(v[4] for v in sorted([v for v in below if abs(v[1] - y) < 3], key=lambda v: v[0]))
        return txt.strip()
    return ""


def _revision_grid(page):
    """The Archicad title block table with the columns RevID | ChID | Change Name | Date. The RevID and the date are merged cells that
    cover all the changes of one revision, so the table's ruled lines are used to see which changes belong to which revision.
    Returns [(change id, date, description)]; when change IDs repeat from one revision to the next they become '<rev>.<id>'."""
    words = page.get_text("words") or []
    W, H = page.rect.width, page.rect.height
    cand = [w for w in words if w[0] > W * 0.4 and w[1] > H * 0.3]
    chid = next((w for w in cand if w[4].lower() == "chid"), None)
    if chid is None:
        return []
    hl = sorted([v for v in cand if abs(v[1] - chid[1]) < 4], key=lambda v: v[0])
    low = [v[4].lower() for v in hl]
    try:
        rev = next(v for v in hl if v[4].lower() in ("revid", "rev") and v[0] < chid[0])
        ch = next(v for v in hl if v[4].lower() == "change")
        nm = next((v for v in hl if v[4].lower() == "name" and v[0] > ch[0]), ch)
        dt = next(v for v in hl if v[4].lower() == "date")
    except StopIteration:
        return []
    hl = [v for v in hl if v[0] >= rev[0] - 1 and v[0] < dt[2] + 5]
    hy1 = max(v[3] for v in hl)
    b1 = (rev[2] + chid[0]) / 2 if rev[4].lower() == "revid" else (chid[0] - 3)
    b2 = (chid[2] + ch[0]) / 2
    b3 = (nm[2] + dt[0]) / 2
    left, right = rev[0] - 6, dt[2] + 14
    # ruled lines across the whole table = the edges of the revisions
    ys = []
    try:
        for d in page.get_drawings():
            rc = d["rect"]
            if rc.height < 1.0 and rc.width > (right - left) * 0.8 and abs(rc.x0 - left) < 14 and rc.y0 > hy1 - 12 and rc.y0 < hy1 + 500:
                ys.append(round(rc.y0, 1))
    except Exception:
        ys = []
    ys = sorted(set(ys))
    chain = []
    for y in ys:
        if not chain:
            if y > hy1 - 6:
                chain.append(y)
        elif y - chain[-1] < 40:
            if y - chain[-1] > 1.5:
                chain.append(y)
        else:
            break
    if len(chain) < 2:
        return []

    def col(v):
        return "rev" if v[0] < b1 else "ch" if v[0] < b2 else "desc" if v[0] < b3 else "date"

    out = []
    for ya, yb in zip(chain, chain[1:]):
        blk = [v for v in words if left <= v[0] <= right and ya < (v[1] + v[3]) / 2 < yb]
        if not blk:
            continue
        revt = " ".join(v[4] for v in sorted([v for v in blk if col(v) == "rev"], key=lambda v: (v[1], v[0])))
        dts = [v[4] for v in sorted([v for v in blk if col(v) == "date"], key=lambda v: (v[1], v[0]))]
        date = ""
        for k in (3, 2, 1):
            if len(dts) >= k and norm_date(" ".join(dts[:k])):
                date = norm_date(" ".join(dts[:k]))
                break
        rows, lastmid = [], None
        for v in sorted([v for v in blk if col(v) in ("ch", "desc")], key=lambda v: ((v[1] + v[3]) / 2, v[0])):
            mid = (v[1] + v[3]) / 2
            if lastmid is None or abs(mid - lastmid) > 3.5:
                rows.append({"id": [], "desc": [], "mid": mid})
                lastmid = mid
            rows[-1]["id" if col(v) == "ch" else "desc"].append(v[4])
        cur = None
        for r_ in rows:
            idt = " ".join(r_["id"]).strip()
            dsc = " ".join(r_["desc"]).strip(" -:")
            if idt and re.match(r"^[A-Za-z]?\d{1,3}$", idt):
                cur = [revt.upper(), idt.upper(), date, dsc]
                out.append(cur)
            elif not idt and dsc and cur is not None:
                cur[3] = (cur[3] + " " + dsc).strip()          # the description runs on to a second line
    out = [x for x in out if x[3]]                              # a change with no description is not a described change
    ids = [x[1] for x in out]
    dup = len(set(ids)) != len(ids)
    return [(("%s.%s" % (x[0], x[1])) if dup and x[0] else x[1], x[2], x[3]) for x in out]


def _revision_table(page):
    """Rows of the title block's revision history table: [(rev, date, description)].
    The heading (Rev ID / Change Name / Date) fixes the columns; only words inside those columns are read, a row counts only when it
    has a change ID in the ID column and a date in the date column, and reading stops at the first line that is not part of the table,
    so neighbouring title block boxes (drawn by, checked, project, ...) are never mistaken for changes."""
    try:
        g = _revision_grid(page)
    except Exception:
        g = []
    if g:
        return g
    words = page.get_text("words") or []
    if not words:
        return []
    W, H = page.rect.width, page.rect.height
    cand = [w for w in words if w[0] > W * 0.4 and w[1] > H * 0.3]
    head = None
    for w in cand:
        if w[4].lower() in ("rev", "id", "rev."):
            near = [v for v in cand if abs(v[1] - w[1]) < 6 and v[0] >= w[0] - 1 and v[0] - w[0] < 400]
            txt = " ".join(v[4].lower() for v in sorted(near, key=lambda v: v[0]))
            if re.search(r"\bdate\b", txt) and re.search(r"\bchange\b|\bdescription\b|\bdetails?\b|\bname\b|\bnote", txt):
                head = (w, near)
                break
    if head is None:
        return []
    w0, near = head
    near = sorted(near, key=lambda v: v[0])
    hy0, hy1 = min(v[1] for v in near), max(v[3] for v in near)
    lh = max(6.0, sorted(v[3] - v[1] for v in near)[len(near) // 2])
    # column starts from the heading words
    id_x = w0[0]
    date_x = next((v[0] for v in near if v[4].lower().startswith("date")), None)
    desc_x = next((v[0] for v in near if re.match(r"change|description|details?|name|note", v[4].lower()) and v[0] > id_x + 1), None)
    if date_x is None or desc_x is None:
        return []
    starts = sorted({id_x, date_x, desc_x})
    right = {id_x: "id", date_x: "date", desc_x: "desc"}
    last_col = right[starts[-1]]
    x_left = id_x - 6
    x_right = near[-1][2] + (420 if last_col == "desc" else 40)

    def cell(v):
        col = right[starts[0]]
        for st in starts:
            if v[0] >= st - 4:
                col = right[st]
        return col

    def lines(sel):
        ls = []
        for v in sorted(sel, key=lambda v: ((v[1] + v[3]) / 2, v[0])):
            mid = (v[1] + v[3]) / 2
            if ls and abs(ls[-1][0] - mid) < lh * 0.6:
                ls[-1][1].append(v)
            else:
                ls.append([mid, [v]])
        return [(m, sorted(ws, key=lambda v: v[0])) for m, ws in ls]

    def read(rows_lines):
        out, prev = [], None
        for mid, ws in rows_lines:
            if prev is not None and abs(mid - prev) > lh * 3.2:
                break
            c = {"id": [], "date": [], "desc": []}
            for v in ws:
                c[cell(v)].append(v[4])
            idt = " ".join(c["id"]).strip()
            dts = ""
            toks = c["date"]
            for k in (1, 2, 3):                                   # the date is the last 1-3 words of the date column; any words before it are description that ran over
                if len(toks) >= k and norm_date(" ".join(toks[-k:])):
                    dts = " ".join(toks[-k:])
                    c["desc"] += toks[:-k]
                    break
            else:
                c["desc"] += toks
            dsc = " ".join(c["desc"]).strip(" -:")
            dt = norm_date(dts) if dts else ""
            if re.match(r"^(?:rev\.?\s*)?([A-Za-z]|[A-Za-z]?\d{1,3})$", idt, re.I) and dt:
                out.append([re.sub(r"^rev\.?\s*", "", idt, flags=re.I).upper(), dt, dsc])
            elif not idt and not dts and dsc and out and abs(mid - prev) < lh * 1.9:
                out[-1][2] = (out[-1][2] + " " + dsc).strip()      # a description that runs on to a second line
            elif idt and not dt and not dsc:
                pass                                              # an empty numbered row
            else:
                break                                             # something else: the table is over
            prev = mid
        return [tuple(x) for x in out]

    sel = [v for v in words if x_left <= v[0] <= x_right]
    below = [v for v in sel if (v[1] + v[3]) / 2 > hy1 + 1]
    res = read(lines(below))
    if not res:
        above = [v for v in sel if (v[1] + v[3]) / 2 < hy0 - 1]
        res = read(list(reversed(lines(above))))                  # nearest the heading first
        res.reverse()
    seen, out = set(), []
    for rv, dt, ds in res:
        if (rv, dt, ds) in seen:
            continue
        seen.add((rv, dt, ds))
        out.append((rv, dt, ds))
    return out


def pdf_date(meta):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", (meta or {}).get("creationDate") or (meta or {}).get("modDate") or "")
    return "%s-%s-%s" % m.groups() if m else ""


# (pattern in the title or the drawing text, what the drawing is about)
ABOUT = [
    (r"site\s*plan|site\s*development", "Stand layout: building positions, boundaries, building lines, coverage and access."),
    (r"locality|location", "Where the site is, in relation to its surroundings."),
    (r"ground\s*floor|first\s*floor|second\s*floor|floor\s*plan|\bplan\b", "Floor plan: walls, rooms, openings, dimensions and room names."),
    (r"elevation", "Elevations: the outside faces of the building, heights and finishes."),
    (r"section", "Sections: the building cut through, to show levels, heights and construction."),
    (r"roof", "Roof plan: roof shape, falls, drainage and roof covering."),
    (r"foundation|footing", "Foundation layout: footings, sizes and levels."),
    (r"drainage|sewer|plumbing", "Drainage and plumbing layout: pipes, fall, manholes and fixtures."),
    (r"electr|lighting", "Electrical layout: lights, plugs, switches and the distribution board."),
    (r"door|window|schedule", "Schedule of doors and windows: sizes, types and positions."),
    (r"detail", "Construction details: how the parts of the building are built up."),
    (r"energy|sans\s*10400[-\s]*xa|xa\b", "Energy efficiency (SANS 10400-XA) information for the council."),
    (r"light|ventilat", "Natural light and ventilation (SANS 10400-O) for the council."),
    (r"kitchen|bath|cupboard|joinery", "Interior fittings: kitchen, bathroom and cupboard layouts."),
    (r"3d|render|view|perspective", "3D views of the design."),
    (r"cover|title|index", "Cover sheet and drawing index."),
]
SIZES = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297)}


def paper_size(w_pt, h_pt):
    a, b = sorted((w_pt * 25.4 / 72.0, h_pt * 25.4 / 72.0))
    for n, (sw, sh) in SIZES.items():
        if abs(a - sw) < 12 and abs(b - sh) < 15:
            return n
    return "%d x %d mm" % (round(a), round(b))


def read_pdf(path):
    """What can be read from a drawing PDF: sheets, paper size, scale, and the title block at the bottom right
    (drawing number, revisions with date and description), plus the date the PDF was made."""
    out = {"pages": 1, "size": "", "scale": "", "rev": "", "rdate": "", "rdesc": "", "no": "", "title": "", "revs": [], "pdfdate": "", "text": ""}
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        d = fitz.open(path)
        out["pages"] = len(d)
        out["pdfdate"] = pdf_date(d.metadata)
        if len(d):
            pg = d[0]
            r = pg.rect
            out["size"] = paper_size(r.width, r.height)
            t = pg.get_text("text") or ""
            out["text"] = t[:4000]
            m = re.search(r"(?:scale|skaal)?\s*[:@]?\s*(1\s*:\s*\d{1,4})", t, re.I)
            if m:
                out["scale"] = re.sub(r"\s+", "", m.group(1))
            tb = None
            try:
                rt = _revision_table(pg)
            except Exception:
                rt = []
            for fx, fy in ((0.55, 0.62), (0.35, 0.40), (0.0, 0.0)):
                clip = fitz.Rect(r.x0 + r.width * fx, r.y0 + r.height * fy, r.x1, r.y1)
                cand = parse_titleblock(_lines_from_page(pg, clip))
                if cand["revs"] or cand["rev"] or cand["no"]:
                    tb = cand if tb is None or cand["revs"] else tb
                    if cand["revs"] and cand["no"]:
                        break
            if tb:
                out.update({k: tb[k] for k in ("no", "title", "revs", "rev", "rdate", "rdesc")})
            try:
                lid, lname = _label_value(pg, "Layout ID"), _label_value(pg, "Drawing Name")
            except Exception:
                lid = lname = ""
            if lid and re.match(r"^[A-Za-z]{0,3}[\d.\-]{1,8}[A-Za-z]?$", lid) and not out["no"]:
                out["no"] = lid
            if lname and not out["title"]:
                out["title"] = lname
            if rt:      # the revision history table, read by position, is the most reliable
                cur = max(rt, key=lambda x: (x[1], x[0]))
                out.update({"revs": rt, "rev": cur[0], "rdate": cur[1], "rdesc": cur[2]})
                try:
                    rf = _revision_field(pg)       # the table's IDs are the individual changes (01, 02, 03); the drawing's revision is its own box
                except Exception:
                    rf = ""
                if rf:
                    out["rev"] = rf
            if not out["scale"] and tb is None:
                pass
        d.close()
    except Exception:
        pass
    return out


def guess_row(path):
    """One register row from a drawing PDF: the title block wins, the file name fills what the title block does not give."""
    base = os.path.splitext(os.path.basename(path))[0]
    info = read_pdf(path)
    no, title = "", base.replace("_", " ").strip()
    m = re.match(r"^\s*([A-Za-z]{0,3}[-_ ]?\d{1,4}[A-Za-z]?)\s*[-_ .]+\s*(.+)$", base)
    if m:
        no, title = m.group(1).replace("_", "-").replace(" ", "-").upper(), m.group(2).replace("_", " ").strip()
    rev = info["rev"]
    mr = re.search(r"[\s_\-]rev\.?\s*([A-Z]\d?|\d{1,2})\s*$", title, re.I)
    if mr:
        rev = rev or mr.group(1).upper()
        title = title[:mr.start()].strip(" -_")
    no = info["no"] or no
    if info["title"] and (not m or re.fullmatch(r"[A-Za-z]{0,3}[-_ ]?\d{1,4}[A-Za-z]?", base.strip())):
        title = info["title"]
    about = ""
    hay = title + " " + info["text"][:600]
    for pat, txt in ABOUT:
        if re.search(pat, title, re.I) or (not about and re.search(pat, hay, re.I)):
            about = txt
            if re.search(pat, title, re.I):
                break
    try:
        fdate = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except OSError:
        fdate = datetime.date.today().isoformat()
    desc = info["rdesc"]
    if len(info["revs"]) > 1 and all(len(x) >= 3 for x in info["revs"]):
        desc = "; ".join(x[2] for x in info["revs"] if x[2]) or desc
    by = ""
    if re.search(r"client|owner|eienaar|kliënt", desc, re.I):
        by = "Client request"
    elif re.search(r"council|municip|munisipal|plan\s*approv", desc, re.I):
        by = "Council request"
    elif re.search(r"engineer|ingenieur", desc, re.I):
        by = "Engineer"
    return {"on": True, "no": no, "title": title, "about": about, "size": info["size"], "pages": info["pages"], "scale": info["scale"],
            "rev": rev, "rdate": info["rdate"] or "", "pdfdate": info["pdfdate"] or fdate, "by": by, "comment": desc, "auto": desc,
            "revs": info["revs"], "status": "For information", "file": os.path.basename(path), "path": path}


from register_ext import LogMixin, MailMixin, short_date


# ----- the registers the program keeps for you (one file each, saved by itself, independent of any project)
REG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MCP_LightVent", "registers")


def reg_list():
    out = []
    try:
        for fn in os.listdir(REG_DIR):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(REG_DIR, fn), encoding="utf-8") as f:
                        d = json.load(f)
                    out.append((fn[:-5], str(d.get("name", fn[:-5]))))
                except Exception:
                    pass
    except OSError:
        pass
    return sorted(out, key=lambda x: x[1].lower())


def reg_load(rid):
    try:
        with open(os.path.join(REG_DIR, rid + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def reg_save(rid, name, state):
    try:
        os.makedirs(REG_DIR, exist_ok=True)
        tmp = os.path.join(REG_DIR, rid + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"name": name, "saved": time.time(), "state": state}, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(REG_DIR, rid + ".json"))
        return True
    except Exception:
        return False


def reg_last(set_to=None):
    fp = os.path.join(REG_DIR, "_last.txt")
    try:
        if set_to is not None:
            os.makedirs(REG_DIR, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(set_to)
            return set_to
        with open(fp, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _empty_register(name=""):
    return {"groups": [{"name": "Main house", "rows": []}], "info": {"project": name}, "cur": 0, "mail": "", "history": [], "log": [], "reports": []}


class RegisterPage(LogMixin, MailMixin, QWidget):
    mail_done = Signal(bool, str)
    is_costing = True
    report_title = "Drawing Register"

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.groups = []     # {name, rows:[...]}
        self.history = []    # issues already sent: {issue, date, rows:{key: {rev, rdate, title, comment}}}
        self.info = {"project": "", "client": "", "issued_by": "", "to": "", "email": "", "note": "", "issue_no": "0", "date": "", "cc": "", "client_logo": "", "sheet_index": "1", "show_index": "1", "issue_kind": "", "show_orders": "0", "show_changes": "0"}
        self.log = []        # orders and revisions, see register_ext
        self.cur = 0
        self._busy = False
        self.rid, self.rname, self._loaded, self._saving = "", "", False, False
        self.what, self.linked, self.link_ok = "register", False, True
        self._info0 = dict(self.info)
        QTimer.singleShot(0, lambda: None if self._loaded else self.set_state({}))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sub = QTabWidget()
        outer.addWidget(self.sub)
        self.draw_w = QWidget()
        v = QVBoxLayout(self.draw_w)
        v.setContentsMargins(0, 6, 0, 0)
        step = lambda t: QLabel('<span style="font-size:14px; font-weight:700;">%s</span>' % t)
        # 0  which register (kept by the program, saves itself, works without a project)
        rb = QHBoxLayout()
        rb.addWidget(QLabel("<b>Register:</b>"))
        self.rbox = QComboBox()
        self.rbox.setMinimumWidth(240)
        self.rbox.setToolTip("Every register is kept by the program and saves itself, also when you press Send. It does not depend on the project that is open.")
        self.rbox.activated.connect(self._reg_picked)
        rb.addWidget(self.rbox)
        for txt, tip, fn in (("+ New register...", "Starts a new, empty register, for example for a new job.", self.reg_new),
                             ("Rename...", "Changes the name of this register.", self.reg_rename),
                             ("Delete", "Removes this register and its issue history (asks first).", self.reg_delete),
                             ("Save a copy...", "Writes this register to a file, as a backup or to open on another computer.", self.reg_export),
                             ("Open a copy...", "Brings in a register from a file saved with Save a copy.", self.reg_import)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            rb.addWidget(b)
        rb.addStretch(1)
        v.addLayout(rb)
        from ui_extras import LinkBar
        self.link_bar = LinkBar(self)
        v.addWidget(self.link_bar)
        v.addSpacing(4)
        # 1  who is it for
        v.addWidget(step("1.  Who is it for?"))
        self.f = {}
        g1 = QGridLayout()
        for i, (key, label, ph) in enumerate((("project", "Project", "taken from Project details if empty"), ("client", "Client", ""),
                                              ("to", "Send to (name)", ""), ("email", "Their email", "name@company.co.za"))):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            if key == "email":
                self._contacts_on(e)
            g1.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g1.addWidget(e, i // 2, (i % 2) * 2 + 1)
        v.addLayout(g1)
        self.contacts_hint = QLabel("")
        self.contacts_hint.setStyleSheet("color:gray;")
        self.contacts_hint.setWordWrap(True)
        self.contacts_hint.setVisible(False)
        v.addWidget(self.contacts_hint)
        self.more_chk = QCheckBox("More details (revision, date, copy to, logo)")
        v.addWidget(self.more_chk)
        self.more_w = QWidget()
        g2 = QGridLayout(self.more_w)
        g2.setContentsMargins(0, 0, 0, 0)
        for i, (key, label, ph) in enumerate((("issued_by", "Issued by", "from your signature"), ("issue_no", "Revision", "0"),
                                              ("date", "Date", "empty = today"), ("cc", "Copy to (Cc)", ""))):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._info_edited)
            self.f[key] = e
            g2.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            if key == "issued_by":
                e.setVisible(False)
                self.issued_btn = QPushButton("")
                self.issued_btn.setStyleSheet("text-align:left;")
                self.issued_btn.clicked.connect(self.my_signature)
                g2.addWidget(self.issued_btn, i // 2, (i % 2) * 2 + 1)
            else:
                if key == "cc":
                    self._contacts_on(e)
                g2.addWidget(e, i // 2, (i % 2) * 2 + 1)
        lb = QPushButton("Client logo...")
        lb.clicked.connect(self.pick_logo)
        g2.addWidget(lb, 2, 1)
        self.more_w.setVisible(False)
        self.more_chk.toggled.connect(self.more_w.setVisible)
        v.addWidget(self.more_w)
        # 2  the drawings
        v.addSpacing(6)
        v.addWidget(step("2.  Add the drawings (PDFs)"))
        hint = QLabel("How it works: first load the list of every drawing in the job (the Archicad sheet index), then add the PDFs you are sending today. "
                      "Whatever you do not send is listed for the client as still to come.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        v.addWidget(hint)
        # a) the whole job
        la = QHBoxLayout()
        la.addWidget(QLabel("<b>A.</b> The whole job:"))
        fi = QPushButton("Load all sheet indexes from a folder...")
        fi.setStyleSheet("font-weight:700;")
        fi.setToolTip("Pick the folder where your sheet indexes are saved. Every sheet index inside it, also in the Block A, Block B... folders, is found at once.")
        fi.clicked.connect(self.import_sheet_index_folder)
        la.addWidget(fi)
        ib = QPushButton("Pick sheet index files...")
        ib.setToolTip("Pick the sheet index PDF (or csv/xlsx) from Archicad. Pick one for each block or house, all at once. Every drawing in them is added and listed as still to come.")
        ib.clicked.connect(self.import_sheet_index)
        la.addWidget(ib)
        pb = QPushButton("Type drawings that are still to come...")
        pb.setToolTip("No sheet index? Type the drawings that are not ready yet, one per line.")
        pb.clicked.connect(self.add_planned)
        la.addWidget(pb)
        la.addStretch(1)
        v.addLayout(la)
        # b) what goes today
        gl = QHBoxLayout()
        gl.addWidget(QLabel("<b>B.</b> What I am sending today:"))
        self.add_btn = QPushButton("Add drawing PDFs...")
        self.add_btn.setStyleSheet("font-weight:700;")
        self.add_btn.setToolTip("Pick the PDFs you are sending. Each one is matched to the sheet index by its drawing number and ticked to send. Anything else stays as still to come.")
        self.add_btn.clicked.connect(self.add_pdfs)
        gl.addWidget(self.add_btn)
        fb = QPushButton("Add a whole folder...")
        fb.clicked.connect(self.add_folder)
        gl.addWidget(fb)
        gl.addSpacing(16)
        sb = QPushButton("Select all")
        sb.setToolTip("Highlights every drawing in the list (Ctrl+A does the same). Click a row to highlight just that one; Ctrl or Shift click picks several.")
        sb.clicked.connect(lambda: (self.tab.setFocus(), self.tab.selectAll()))
        gl.addWidget(sb)
        rb = QPushButton("Remove selected")
        rb.clicked.connect(self.remove_row)
        gl.addWidget(rb)
        ra = QPushButton("Remove all")
        ra.setToolTip("Takes every drawing out of this block's list (asks first).")
        ra.clicked.connect(self.remove_all)
        gl.addWidget(ra)
        gl.addStretch(1)
        v.addLayout(gl)
        # c) the blocks and houses
        gb = QHBoxLayout()
        gb.addWidget(QLabel("<b>Block or house shown below:</b>"))
        self.gbox = QComboBox()
        self.gbox.setMinimumWidth(200)
        self.gbox.currentIndexChanged.connect(self._group_changed)
        gb.addWidget(self.gbox)
        nb = QPushButton("+ Add a block or house...")
        nb.clicked.connect(self.add_group)
        gb.addWidget(nb)
        rn = QPushButton("Rename...")
        rn.setToolTip("Give this block or house your own name, for example Block A, Unit 3 or Clubhouse.")
        rn.clicked.connect(self.rename_group)
        gb.addWidget(rn)
        dl = QPushButton("Delete")
        dl.setToolTip("Deletes this block or house and its list of drawings (asks first).")
        dl.clicked.connect(self.del_group)
        gb.addWidget(dl)
        gb.addStretch(1)
        v.addLayout(gb)
        self.blocks_w = QWidget()
        self.blocks_l = QHBoxLayout(self.blocks_w)
        self.blocks_l.setContentsMargins(0, 2, 0, 0)
        v.addWidget(self.blocks_w)
        self.plan_lbl = QLabel("")
        self.plan_lbl.setWordWrap(True)
        v.addWidget(self.plan_lbl)
        self.tab = QTableWidget(0, len(COLS))
        self.tab.setMinimumHeight(170)
        self.tab.horizontalHeader().setSectionsClickable(True)
        self.tab.horizontalHeader().sectionClicked.connect(self.sort_by_column)
        self.tab.horizontalHeader().setToolTip("Click a heading to sort the list by it; click again to reverse.")
        self.tab.setHorizontalHeaderLabels(COLS)
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tab, activated=lambda: self.remove_row(), context=Qt.ShortcutContext.WidgetShortcut)
        # the selected drawing(s) show clearly: a red band across the whole row
        self.tab.setStyleSheet("QTableWidget::item:selected{background:rgba(200,16,46,150);color:white;}"
                               "QTableWidget::item:selected:!active{background:rgba(200,16,46,110);color:white;}")
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((46, 90, 230, 250, 60, 60, 45, 90, 90, 140, 360, 150, 180)):
            self.tab.setColumnWidth(i, w)
        self.tab.itemChanged.connect(self._cell)
        v.addWidget(self.tab, 2)
        self.all_chk = QCheckBox("Show all details (size, scale, dates, who asked, status, file)")
        self.all_chk.toggled.connect(self._columns)
        v.addWidget(self.all_chk)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("<b>Status for many drawings at once:</b>"))
        self.status_all = QComboBox()
        self.status_all.addItems(STATUSES)
        self.status_all.setEditable(True)
        self.status_all.setMinimumWidth(190)
        self.status_all.setToolTip("Pick or type a status, then press one of the buttons.")
        sr.addWidget(self.status_all)
        for txt, tip, mode in (("Set for ticked drawings", "Changes the status of every drawing that is ticked to be sent.", "ticked"),
                               ("Set for this block", "Changes the status of every drawing in the block or house shown above.", "block"),
                               ("Set for everything", "Changes the status of every drawing in every block or house.", "all")):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mode: self.set_status_all(m))
            sr.addWidget(b)
        sr.addStretch(1)
        v.addLayout(sr)
        # 3  the email and send
        v.addSpacing(6)
        v.addWidget(step("3.  Check the email and send it"))
        head = QHBoxLayout()
        self.to_lbl = QLabel("")
        head.addWidget(self.to_lbl, 1)
        rw = QPushButton("Write it again")
        rw.setToolTip("Throws away your changes to the text and writes the email again from the list above.")
        rw.clicked.connect(self.rewrite_mail)
        self.stale_lbl = QLabel("You changed this email by hand, so it no longer updates itself. Press Write it again to bring in the latest drawings, sheet index and options.")
        self.stale_lbl.setStyleSheet("color:#E0A020;font-weight:700;")
        self.stale_lbl.setWordWrap(True)
        self.stale_lbl.hide()
        head.addWidget(rw)
        v.addLayout(head)
        v.addWidget(self.stale_lbl)
        self.mail = QPlainTextEdit()      # written automatically from the drawings, orders and changes; you can still edit it
        self.mail.setMinimumHeight(150)
        self._mail_setting, self._mail_manual = False, False
        self.mail.textChanged.connect(self._mail_edited)
        v.addWidget(self.mail, 1)
        self.att_lbl = QLabel("")
        self.att_lbl.setWordWrap(True)
        self.att_lbl.setStyleSheet("color: gray;")
        v.addWidget(self.att_lbl)
        rr = QHBoxLayout()
        rr.addWidget(QLabel("<b>Also attach a report:</b>"))
        self.rep_chk = {}
        for kind, label in (("lv", "Light & Ventilation"), ("xa", "Energy XA"), ("rd", "Rational design"), ("cov", "Coverage and FAR")):
            c = QCheckBox(label)
            c.setToolTip("Makes this report from the project that is open and sends it with the drawings.")
            c.toggled.connect(self._reports_changed)
            self.rep_chk[kind] = c
            rr.addWidget(c)
        rr.addStretch(1)
        v.addLayout(rr)
        rk = QHBoxLayout()
        rk.addWidget(QLabel("<b>This email is:</b>"))
        self.kind_box = QComboBox()
        self.kind_box.addItem("Revised drawings (shows what changed)", "revised")
        self.kind_box.addItem("A new set of drawings", "new")
        self.kind_box.addItem("These drawings (just the list, no changes shown)", "these")
        self.kind_box.setToolTip("Revised: the email says what changed since the last issue. New set or These drawings: it is just the list of drawings, with no changes shown.")
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        rk.addWidget(self.kind_box)
        rk.addSpacing(16)
        self.idx_btn = QPushButton()
        self.idx_btn.setCheckable(True)
        self.idx_btn.setChecked(self.info.get("show_index") != "0")
        self.idx_btn.setToolTip("On: the email also lists every drawing of every block or house and what is still to come (needs the sheet index loaded). Off: the email lists only the drawings you are sending.")
        self.idx_btn.toggled.connect(self._idx_toggled)
        rk.addWidget(self.idx_btn)
        self._style_idx_btn()
        rk.addStretch(1)
        v.addLayout(rk)
        self._sync_kind()
        rx = QHBoxLayout()
        rx.addWidget(QLabel("<b>Also list in the email and the PDF:</b>"))
        self.ord_chk = QCheckBox("Orders")
        self.chg_chk = QCheckBox("Client changes")
        for c, k in ((self.ord_chk, "show_orders"), (self.chg_chk, "show_changes")):
            c.setToolTip("Off: they stay in their own tab and are not put in the email or the register PDF.")
            c.setChecked(self.info.get(k) == "1")
            c.toggled.connect(lambda on, k=k: self._opt_changed(k, on))
            rx.addWidget(c)
        rx.addStretch(1)
        v.addLayout(rx)
        bar = QHBoxLayout()
        self.send_btn = QPushButton("Send to the client...")
        self.send_btn.setMinimumHeight(38)
        self.send_btn.setStyleSheet("font-weight:700; padding: 0 22px;")
        self.send_btn.clicked.connect(self.send_mail)
        bar.addWidget(self.send_btn)
        for text, fn in (("Preview and edit the email", self.preview_email), ("Preview the PDF", self.preview_pdf), ("Save the PDF", self.export_pdf)):
            b = QPushButton(text)
            b.setMinimumHeight(38)
            b.clicked.connect(fn)
            bar.addWidget(b)
        more = QPushButton("More")
        more.setMinimumHeight(38)
        menu = QMenu(more)
        for text, fn in (("Email account...", self.email_account), ("My email signature...", self.my_signature), ("Load my Gmail contacts", self.load_contacts_now), ("I sent it another way: record it as issued", self.mark_issued), ("Continue from an earlier issue I already sent...", self.continue_from_earlier), (None, None),
                         ("Rename this block or house", self.rename_group), ("Delete this block or house", self.del_group),
                         ("Move the selected drawing up", lambda: self.move(-1)), ("Move the selected drawing down", lambda: self.move(1)),
                         ("Read the PDFs again (after you re-saved them)", self.reread), (None, None),
                         ("Copy the email text", self.copy_mail), ("Save the list as CSV", self.export_csv)):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, fn)
        more.setMenu(menu)
        bar.addWidget(more)
        bar.addStretch(1)
        self.count = QLabel("")
        bar.addWidget(self.count)
        v.addLayout(bar)
        from PySide6.QtWidgets import QScrollArea
        self.draw_w.setMinimumHeight(900)                  # on a small screen the page scrolls instead of squashing its rows together
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sc.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        sc.setWidget(self.draw_w)
        self.sub.addTab(sc, "Drawings")
        self.sub.addTab(self.build_log("Order"), "Orders")
        self.sub.addTab(self.build_log("Change"), "Client changes")
        self.sub.addTab(self.build_history(), "Sent and revisions")
        self.mail_done.connect(self._mail_finished)
        self.add_group("Main house", quiet=True)
        self._columns()
        self.refresh()

    def _mail_edited(self):
        if not self._mail_setting:
            self._mail_manual = True
            if hasattr(self, "stale_lbl"):
                self.stale_lbl.show()

    def rewrite_mail(self):
        self._mail_manual = False
        if hasattr(self, "stale_lbl"):
            self.stale_lbl.hide()
        self.update_mail()

    def update_mail(self):
        """Keep the email under the list up to date: written from the drawings, orders and changes unless you have edited it yourself."""
        self._autosave()
        if getattr(self, "_mail_setting", None) is None or not hasattr(self, "att_lbl"):
            return
        if hasattr(self, "stale_lbl"):
            self.stale_lbl.setVisible(bool(self._mail_manual))
        if not self._mail_manual:
            self._mail_setting = True
            try:
                self.write_mail()
            except Exception as e:       # never leave the email box empty
                self.mail.setPlainText("(The email could not be written automatically: %s.)\n\nYou can still type it here." % e)
            finally:
                self._mail_setting = False
        gi = self.groups_in_issue()
        files = []
        for _n, rows in gi:
            for r in rows:
                p = r.get("path")
                if p and os.path.exists(p) and p not in files:
                    files.append(p)
        mb = sum(os.path.getsize(p) for p in files) / 1e6
        self.to_lbl.setText("<b>To:</b> %s" % (self.info.get("email") or "<i>add their email above</i>"))
        reps = [c.text() for c in getattr(self, "rep_chk", {}).values() if c.isChecked()]
        self.att_lbl.setText("Attached when you send: the drawing register (PDF)%s%s.%s" % (
            (" and %d drawing PDFs (%.1f MB)" % (len(files), mb)) if files else "",
            ("; reports: " + ", ".join(reps)) if reps else "",
            "  That is too big for one email: the send window can make the PDFs smaller or send them in several emails." if mb > 17 else ""))

    SIMPLE = ("on", "no", "title", "rev", "comment")

    def _columns(self, *_a):
        full = self.all_chk.isChecked()
        for i, k in enumerate(KEYS):
            self.tab.setColumnHidden(i, not (full or k in self.SIMPLE))

    # ----- state -----
    def state(self):
        """What the project file keeps: nothing when you unlinked it, otherwise the register with its id (the program's own copy wins on opening)."""
        if not self.link_ok:
            return None
        d = self._state()
        d["rid"], d["rname"] = self.rid, self.rname
        d["linked"] = bool(self.linked)
        return d

    def after_project_saved(self):
        """The project file was written with this register in it: it is linked now."""
        if self.link_ok:
            self.linked = True
            self.link_bar.refresh()

    def _state(self):
        return {"groups": self.groups, "info": self.info, "cur": self.cur, "mail": self.mail.toPlainText(), "mail_manual": bool(self._mail_manual), "history": self.history, "log": self.log,
                "reports": [k for k, c in getattr(self, "rep_chk", {}).items() if c.isChecked()]}

    def set_state(self, d):
        """From a project (or empty). The register kept by the program wins over the copy inside the project, so the history is never behind."""
        d = d or {}
        if self._loaded:
            self.save_register()
        rid, name, st = d.get("rid") or "", "", None
        if rid:
            rec = reg_load(rid)
            if rec:
                st, name = rec.get("state"), rec.get("name", "")
        if st is None and (d.get("history") or d.get("log") or any(g.get("rows") for g in d.get("groups", []) if isinstance(g, dict))):
            rid = rid or "r%d" % int(time.time() * 1000)
            name = d.get("rname") or (d.get("info") or {}).get("project") or "Imported register"
            st = d
        if st is None:
            last = reg_last()
            rec = reg_load(last) if last else None
            if rec:
                rid, name, st = last, rec.get("name", ""), rec.get("state")
            elif self._loaded and self.rid:
                return          # nothing to change: keep working in the register that is open
            else:
                rid, name, st = "r%d" % int(time.time() * 1000), "My register", _empty_register()
        self.linked = bool(d.get("rid")) and bool(st is not None) and rid == d.get("rid")
        self.link_ok = True
        self._switch(rid, name, st)

    def _switch(self, rid, name, st):
        self.rid, self.rname = rid, name
        self._loaded = False
        self._apply_state(st)
        self._loaded = True
        reg_last(rid)
        self.save_register()
        self._reg_combo()
        self.link_bar.refresh()

    def _reg_combo(self):
        self.rbox.blockSignals(True)
        self.rbox.clear()
        for rid, nm in reg_list():
            self.rbox.addItem(nm, rid)
        i = self.rbox.findData(self.rid)
        if i >= 0:
            self.rbox.setCurrentIndex(i)
        self.rbox.blockSignals(False)

    def save_register(self):
        if self.rid and self._loaded and not self._saving:
            self._saving = True
            try:
                reg_save(self.rid, self.rname, self._state())
            finally:
                self._saving = False

    def _autosave(self):
        if not getattr(self, "_save_timer", None):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_register)
        self._save_timer.start(500)

    def _reg_picked(self, i):
        rid = self.rbox.itemData(i)
        if not rid or rid == self.rid:
            return
        self.save_register()
        rec = reg_load(rid)
        if rec:
            self._switch(rid, rec.get("name", ""), rec.get("state"))
        else:
            self._reg_combo()

    def reg_new(self):
        name, ok = QInputDialog.getText(self, "New register", "Name of the register (for example the job number, ODN 14243):")
        name = name.strip()
        if not ok or not name:
            return
        self.save_register()
        self._switch("r%d" % int(time.time() * 1000), name, _empty_register(name))

    def reg_rename(self):
        name, ok = QInputDialog.getText(self, "Rename register", "New name:", text=self.rname)
        name = name.strip()
        if not ok or not name:
            return
        if self.info.get("project", "").strip() in ("", self.rname):
            self.info["project"] = name
            self.f["project"].setText(name)
        self.rname = name
        self.save_register()
        self._reg_combo()

    def reg_delete(self):
        if QMessageBox.question(self, "Delete register", "Delete the register \"%s\" with all its issues and history? This cannot be undone." % self.rname) != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(os.path.join(REG_DIR, self.rid + ".json"))
        except OSError:
            pass
        rest = reg_list()
        self._loaded = False
        if rest:
            rec = reg_load(rest[0][0])
            self._switch(rest[0][0], rec.get("name", ""), rec.get("state"))
        else:
            self._switch("r%d" % int(time.time() * 1000), "My register", _empty_register())

    def reg_export(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save a copy of this register", (self.rname or "register") + ".mcpreg", "Drawing register (*.mcpreg)")
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"name": self.rname, "state": self._state()}, f, ensure_ascii=False)
        except OSError as ex:
            QMessageBox.warning(self, "Save a copy", "Could not save the file: %s" % ex)

    def reg_import(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open a copy of a register", "", "Drawing register (*.mcpreg)")
        if not fn:
            return
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            st, name = d["state"], str(d.get("name") or "Register")
        except Exception:
            QMessageBox.warning(self, "Open a copy", "That file is not a drawing register.")
            return
        if name in [n for _i, n in reg_list()]:
            name += " (copy)"
        self.save_register()
        self._switch("r%d" % int(time.time() * 1000), name, st)

    def _apply_state(self, d):
        d = d or {}
        self.groups = [dict(name=g.get("name", "Group"), rows=[dict(r, revs=[tuple(x) for x in (r.get("revs") or []) if isinstance(x, (list, tuple))]) for r in g.get("rows", [])]) for g in d.get("groups", []) if isinstance(g, dict)]
        if not self.groups:
            self.groups = [{"name": "Main house", "rows": []}]
        self.info.clear()
        self.info.update(self._info0)
        self.info.update({k: str(v) for k, v in (d.get("info") or {}).items() if k in self.info})
        for k, c in getattr(self, "rep_chk", {}).items():
            c.blockSignals(True)
            c.setChecked(k in (d.get("reports") or []))
            c.blockSignals(False)
        self.log = [dict(x) for x in d.get("log", []) if isinstance(x, dict)]
        self.history = [dict(h) for h in d.get("history", []) if isinstance(h, dict)]
        self.cur = min(int(d.get("cur", 0) or 0), len(self.groups) - 1)
        # the email is written again from the drawings when the project opens, unless you had changed the text by hand
        keep = bool(d.get("mail_manual")) and bool((d.get("mail") or "").strip())
        self._mail_setting = True
        try:
            self.mail.setPlainText(d.get("mail", "") or "" if keep else "")
        finally:
            self._mail_setting = False
        self._mail_manual = keep
        if hasattr(self, "stale_lbl"):
            self.stale_lbl.setVisible(keep)
        self.refresh()
        self.refresh_history()
        if not keep:
            self.update_mail()

    def project_name(self):
        return self.info["project"].strip() or (getattr(self.host, "rd", {}) or {}).get("project", "").strip() or "Project"

    def _info_edited(self, *_a):
        for k, e in self.f.items():
            self.info[k] = e.text()
        self.update_mail()

    # ----- groups and rows -----
    def rows(self):
        return self.groups[self.cur]["rows"] if self.groups else []

    def add_group(self, name=None, quiet=False):
        if not isinstance(name, str):
            name, ok = QInputDialog.getText(self, "Drawing register", "Name of the block or house (for example Block A, House 2, Clubhouse):")
            if not ok or not name.strip():
                return
        self.groups.append({"name": name.strip(), "rows": []})
        self.cur = len(self.groups) - 1
        if not quiet:
            self.refresh()

    def rename_group(self):
        name, ok = QInputDialog.getText(self, "Drawing register", "New name for this block or house:", text=self.groups[self.cur]["name"])
        if ok and name.strip():
            self.groups[self.cur]["name"] = name.strip()
            self.refresh()

    def del_group(self):
        if len(self.groups) > 1 and QMessageBox.question(self, "Drawing register", "Delete this group and its list of drawings?") == QMessageBox.StandardButton.Yes:
            self.groups.pop(self.cur)
            self.cur = max(0, self.cur - 1)
            self.refresh()

    def _group_changed(self, i):
        if not self._busy and 0 <= i < len(self.groups):
            self.cur = i
            self.refresh()

    def add_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Drawings (PDF)", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder with the drawing PDFs")
        if d:
            self.add_paths([os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".pdf")])

    @staticmethod
    def key(r):
        return (r.get("no") or r.get("title", "")).strip().lower()

    @staticmethod
    def _loose(k):
        return re.sub(r"[^0-9a-z]", "", str(k).lower())

    def find_in_group(self, g, k):
        lk = self._loose(k)
        for r in g["rows"]:
            if self.key(r) == k or (lk and self._loose(self.key(r)) == lk):
                return r
        return None

    def find_row(self, k):
        cur = self.groups[self.cur] if 0 <= self.cur < len(self.groups) else None
        if cur is not None:                     # the block that is open comes first (the same drawing number can be in several blocks)
            r = self.find_in_group(cur, k)
            if r is not None:
                return r
        for g in self.groups:
            for r in g["rows"]:
                if self.key(r) == k:
                    return r
        lk = self._loose(k)
        if lk:
            for g in self.groups:
                for r in g["rows"]:
                    if self._loose(self.key(r)) == lk:
                        return r
        return None

    def add_paths(self, paths):
        """New drawings are added to the current group. A drawing already in the register (same drawing number) is updated in
        place from the new PDF, so a revised drawing replaces its older revision; comments you typed are kept."""
        added = updated = 0
        for p in sorted(paths, key=lambda x: os.path.basename(x).lower()):
            if not p.lower().endswith(".pdf"):
                continue
            new = guess_row(p)
            old = self.find_row(self.key(new))
            if old is None:
                self.rows().append(new)
                added += 1
            else:
                was_planned = not old.get("path")
                self._merge(old, new)
                if was_planned and old.get("path"):
                    old["on"] = True            # its PDF is here: it goes today
                updated += 1
        self.rows().sort(key=lambda r: (r.get("no") or "~", r.get("title", "").lower()))
        self.refresh()
        self.count.setText("%d added, %d updated from newer PDFs" % (added, updated) if (added or updated) else self.count.text())
        return added + updated

    def _merge(self, old, new):
        keep_c = old.get("comment", "") not in ("", old.get("auto", ""))
        keep_b = bool(old.get("by"))
        for k in ("title", "about", "size", "pages", "scale", "rev", "rdate", "pdfdate", "revs", "file", "path", "auto"):
            if new.get(k) not in (None, ""):
                old[k] = new[k]
        if not keep_c:
            old["comment"] = new["comment"]
            try:       # what changed = every revision row newer than the last issue sent
                items = self.change_items(old)
                if items:
                    old["comment"] = "; ".join(d for d, _rv in items)
                    old["auto"] = old["comment"]
            except Exception:
                pass
        if not keep_b:
            old["by"] = new["by"]

    def reread(self):
        paths = [r.get("path") for g in self.groups for r in g["rows"] if r.get("path") and os.path.exists(r["path"])]
        for g in self.groups:
            for r in g["rows"]:
                if r.get("path") and os.path.exists(r["path"]):
                    self._merge(r, guess_row(r["path"]))
        self.refresh()
        self.count.setText("%d PDFs read again" % len(paths))

    # ----- carrying on after a crash, or with a project that was never recorded here -----
    @staticmethod
    def _read_sent_register(path):
        """(revision number, date) from a sent register or email: its file name, its first page text, or the email's headers."""
        rev, date = "", ""
        base = os.path.basename(path)
        m = re.search(r"revision\s*([0-9A-Za-z]+)", base, re.I)
        if m:
            rev = m.group(1)
        try:
            if path.lower().endswith(".pdf"):
                try:
                    import pymupdf as fitz
                except ImportError:
                    import fitz
                d = fitz.open(path)
                t = (d[0].get_text("text") or "") if len(d) else ""
                d.close()
                m = re.search(r"revision\s*([0-9A-Za-z]+)\s*[|\-,]*\s*" + DATE_RE, t, re.I)
                if m:
                    rev, date = rev or m.group(1), norm_date(m.group(2))
                if not date:
                    for x in re.findall(DATE_RE, t):
                        if norm_date(x):
                            date = norm_date(x)
                            break
            elif path.lower().endswith(".eml"):
                from email import policy
                from email.parser import BytesParser
                from email.utils import parsedate_to_datetime
                with open(path, "rb") as f:
                    msg = BytesParser(policy=policy.default).parse(f)
                m = re.search(r"revision\s*([0-9A-Za-z]+)", msg.get("Subject", "") or "", re.I)
                if m:
                    rev = rev or m.group(1)
                if msg.get("Date"):
                    date = parsedate_to_datetime(msg["Date"]).date().isoformat()
        except Exception:
            pass
        return rev, date

    def continue_from_earlier(self):
        """More > Continue from an earlier issue: tell the register which revision was last sent and when, so the next one shows only what changed after that."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle("Continue from an earlier issue")
        d.resize(560, 300)
        v = QVBoxLayout(d)
        t = QLabel("Use this if the program closed before the last register was recorded, or this project was sent before it was kept here.\n"
                   "Tell it which revision you last sent and the date. Every revision row in the title blocks dated on or before that day counts as already sent, "
                   "and the next email shows only what changed after it.")
        t.setWordWrap(True)
        v.addWidget(t)
        fold = QPushButton("Use the folder of the revision I sent (the PDFs as they were)...")
        fold.setStyleSheet("font-weight:700;")
        v.addWidget(fold)
        pick = QPushButton("Or read the number and date from the register PDF or email I sent...")
        v.addWidget(pick)
        base = {}
        f = QFormLayout()
        try:
            guess = str(max(int(self.info["issue_no"] or "1") - 1, 0))
        except ValueError:
            guess = "0"
        rev = QLineEdit(guess)
        dt = QLineEdit("")
        dt.setPlaceholderText("for example 2026-11-17")
        f.addRow("Revision last sent", rev)
        f.addRow("Date it was sent", dt)
        v.addLayout(f)
        info = QLabel("")
        info.setWordWrap(True)
        v.addWidget(info)

        def choose():
            p, _ = QFileDialog.getOpenFileName(d, "The register PDF or the email you sent", "", "Register or email (*.pdf *.eml);;All files (*)")
            if not p:
                return
            r_, dd = self._read_sent_register(p)
            if r_:
                rev.setText(r_)
            if dd:
                dt.setText(dd)
            info.setText("Read: revision %s, %s." % (r_ or "?", dd or "date not found, type it in") if (r_ or dd) else "Could not read a revision or a date from that file. Type them in.")
        pick.clicked.connect(choose)

        def choose_folder():
            p = QFileDialog.getExistingDirectory(d, "The folder of the revision you sent (its drawing PDFs)")
            if not p:
                return
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                got, dates = self._read_folder(p)
            finally:
                QApplication.restoreOverrideCursor()
            if not got:
                info.setText("No drawing PDFs found in that folder.")
                return
            base.clear()
            base.update(got)
            m = re.search(r"(?:rev(?:ision)?)[\s_.-]*([0-9A-Za-z]+)", os.path.basename(p.rstrip("/\\")), re.I)
            if m and not rev.isModified():
                rev.setText(m.group(1))
            if dates and not dt.text().strip():
                dt.setText(max(dates))
            info.setText("Read %d drawings from that folder. They are counted as what was sent. Check the revision number and the date it was sent below (%s)."
                         % (len(got), "the newest PDF there is dated " + max(dates) if dates else "type the date"))
        fold.clicked.connect(choose_folder)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        date = norm_date(dt.text().strip())
        if not date:
            QMessageBox.information(self, "Drawing register", "Type the date it was sent, like 2026-11-17.")
            return
        n = self.rebuild_history(rev.text().strip() or "0", date, base or None)
        self.count.setText("Continuing from revision %s of %s: %d drawings are counted as sent." % (rev.text().strip() or "0", date, n))

    def _read_folder(self, folder):
        """The drawing PDFs of an earlier revision's folder as they were: ({key: {rev, rdate, title, no}}, [dates the PDFs were made])."""
        rows, dates = {}, []
        for root, _dirs, files in os.walk(folder):
            for f in sorted(files):
                if not f.lower().endswith(".pdf") or re.search(r"drawing register", f, re.I):
                    continue
                path = os.path.join(root, f)
                try:
                    r = guess_row(path)
                except Exception:
                    continue
                revs = [tuple(str(v or "") for v in x[:3]) for x in (r.get("revs") or []) if len(x) >= 3]
                rdate = r.get("rdate") or (max((x[1] for x in revs if x[1]), default=""))
                rows[self.key(r)] = {"rev": r.get("rev", ""), "rdate": rdate, "title": r.get("title", ""), "no": r.get("no", ""), "comment": "", "by": "",
                                     "maxid": max((x[0] for x in revs), default="")}
                if r.get("pdfdate"):
                    dates.append(r["pdfdate"])
        return rows, dates

    def rebuild_history(self, issue, date, baseline=None):
        """Make an earlier issue: from the PDFs of that revision's folder when given, otherwise out of the drawings in the list as they looked on that date (read from their revision rows)."""
        rows = dict(baseline) if baseline else {}
        for g in ([] if baseline else self.groups):
            for r in g["rows"]:
                revs = [tuple(str(v or "") for v in x[:3]) for x in (r.get("revs") or []) if len(x) >= 3]
                dated = [x for x in revs if x[1]]
                if dated and min(x[1] for x in dated) > date:
                    continue                     # its first revision came after that date: it was not there yet, so it is new now
                upto = [x for x in dated if x[1] <= date]
                if upto:
                    cur = max(upto, key=lambda x: (x[1], x[0]))
                    rev, rdate = cur[0], cur[1]
                else:
                    rev, rdate = r.get("rev", ""), r.get("rdate", "")
                rows[self.key(r)] = {"rev": rev, "rdate": rdate or date, "title": r.get("title", ""), "no": r.get("no", ""), "comment": "", "by": "",
                                     "maxid": max((x[0] for x in upto), default="")}
        self.history = [h for h in self.history if str(h.get("issue")) != str(issue)]
        self.history.append({"issue": str(issue), "date": date, "rows": rows})
        self.history.sort(key=lambda h: (h.get("date", ""), str(h.get("issue", ""))))
        try:
            self.info["issue_no"] = str(int(str(issue)) + 1)
        except ValueError:
            self.info["issue_no"] = str(issue) + "+"
        for g in self.groups:
            for x in g["rows"]:
                x["comment"] = x["auto"] = ""
                try:
                    self._merge(x, dict(x, comment=""))
                except Exception:
                    pass
        self._mail_manual = False
        self.mail.setPlainText("")
        self.refresh()
        self.refresh_history()
        return len(rows)

    # ----- what changed since the last issue -----
    def last_issue(self):
        return self.history[-1] if self.history else None

    def change_of(self, r):
        """('new' | 'revised' | 'same' | '', text) against the last issue that was marked as sent."""
        h = self.last_issue()
        if not h:
            return "", ""
        o = (h.get("rows") or {}).get(self.key(r))
        if o is None:
            return "new", "New drawing"
        if (o.get("rev") or "") != (r.get("rev") or "") or (r.get("rdate") and o.get("rdate") and r["rdate"] != o["rdate"]):
            return "revised", "Revised: Rev %s to Rev %s" % (o.get("rev") or "-", r.get("rev") or "-")
        return "same", "No change"

    def issue_record(self, gi, changes, first, sent, rows):
        """Everything worth remembering about one issue, kept in the project file: what was sent, when, to whom, the drawings with their revisions,
        and what changed since the issue before it."""
        now = datetime.datetime.now()
        groups, changed = [], []
        for name, rs in gi:
            drs = []
            for r in rs:
                kind = "new" if first else (changes.get(id(r)) or "")
                its = [d for d, _rv in self.change_items(r)]
                if kind in ("new", "revised") and not its:
                    its = [self._why(r)] if (r.get("comment") or r.get("by")) else []
                d = {"no": r.get("no", ""), "title": r.get("title", ""), "rev": r.get("rev", ""), "rdate": r.get("rdate", ""), "size": r.get("size", ""), "scale": r.get("scale", ""),
                     "about": r.get("about", ""), "file": r.get("file", ""), "path": r.get("path", ""), "kind": kind, "changes": its}
                drs.append(d)
                if kind in ("new", "revised"):
                    changed.append(dict(d, group=name))
            groups.append({"name": name, "drawings": drs})
        n_new = sum(1 for c in changed if c["kind"] == "new")
        n_rev = sum(1 for c in changed if c["kind"] == "revised")
        total = sum(len(g["drawings"]) for g in groups)
        if first:
            summary = "First issue: %d drawings" % total
        else:
            bits = []
            if n_rev:
                bits.append("%d revised" % n_rev)
            if n_new:
                bits.append("%d new" % n_new)
            summary = ", ".join(bits) if bits else "No drawing changed"
        rec = {"issue": self.info["issue_no"] or "0", "date": now.date().isoformat(), "time": now.strftime("%H:%M"), "rows": rows,
               "groups": groups, "summary": summary, "first": bool(first), "project": self.project_name(), "client": self.info.get("client", ""),
               "register_pdf": ""}
        if sent:
            rec["sent"] = {"to": sent.get("to", ""), "cc": sent.get("cc", ""), "subject": sent.get("subject", ""), "path": sent.get("path", ""),
                           "body": sent.get("body", ""), "files": list(sent.get("files", [])), "emails": sent.get("emails", 1)}
        else:
            rec["sent"] = {}
        return rec

    def mark_issued(self, sent=None, ask=True):
        gi = self.groups_in_issue()
        if not gi:
            QMessageBox.information(self, "Drawing register", "Tick the drawings that were sent first.")
            return
        if ask and QMessageBox.question(self, "Drawing register", "Record this register as issued? The next register will show what changed "
                                        "against it (new drawings, new revisions and why), the log gets a line for it, and the comments are cleared for the next round.") != QMessageBox.StandardButton.Yes:
            return
        changes = {id(r): self.change_of(r)[0] for _n, rs in gi for r in rs}
        first = not self.history
        self.log_issue(gi, changes, first, sent)
        rows = {}
        for _n, rs in gi:
            for r in rs:
                rows[self.key(r)] = {"rev": r.get("rev", ""), "rdate": r.get("rdate", ""), "title": r.get("title", ""), "no": r.get("no", ""),
                                     "comment": r.get("comment", ""), "by": r.get("by", ""),
                                     "maxid": max((str(x[0]) for x in (r.get("revs") or []) if len(x) >= 3), default="")}
        self.history.append(self.issue_record(gi, changes, first, sent, rows))
        try:
            self.info["issue_no"] = str(int(self.info["issue_no"] or "0") + 1)
        except ValueError:
            self.info["issue_no"] = self.info["issue_no"] + "+"
        for g in self.groups:
            for r in g["rows"]:
                r["comment"], r["auto"], r["by"] = "", "", ""
        self._mail_manual = False
        self.mail.setPlainText("")
        self.refresh()
        self.refresh_history()
        self.count.setText("Issue recorded. Add the revised PDFs (or press Re-read the PDFs) to see the changes.")
        self.save_register()

    def pick_logo(self):
        p, _ = QFileDialog.getOpenFileName(self, "Client logo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if p:
            self.info["client_logo"] = p
            self.count.setText("Client logo set")

    def logos(self):
        from PySide6.QtGui import QImage
        out = {}
        try:
            M = sys.modules[type(self.host).__module__]
            im = M.logo_pixmap().toImage().convertToFormat(QImage.Format.Format_ARGB32)
            for yy in range(im.height()):
                for xx in range(im.width()):
                    c = im.pixelColor(xx, yy)
                    if c.alpha() and c.red() > 200 and c.green() > 200 and c.blue() > 200:
                        im.setPixelColor(xx, yy, QColor(17, 17, 17, c.alpha()))
            out["mcp_logo"] = im
        except Exception:
            pass
        p = self.info.get("client_logo")
        if p and os.path.exists(p):
            im = QImage(p)
            if not im.isNull():
                out["client_logo"] = im
        return out

    def remove_row(self):
        picked = sorted({i.row() for i in self.tab.selectedIndexes()}, reverse=True)
        if not picked:
            r = self.tab.currentRow()
            picked = [r] if r >= 0 else []
        n = 0
        snap = None
        for r in picked:
            if 0 <= r < len(self.rows()):
                if snap is None:
                    import copy
                    snap = copy.deepcopy(self.state())
                self.rows().pop(r)
                n += 1
        if n:
            self.refresh()
            self._toast_undo("%d drawing%s taken out of the list" % (n, "" if n == 1 else "s"), snap)

    def open_pdf_of_selected(self, folder=False):
        """Open the PDF of the selected drawing, or the folder it is in."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        r = self.tab.currentRow()
        rows = self.rows()
        if not (0 <= r < len(rows)):
            return
        p = rows[r].get("path") or ""
        if not p or not os.path.exists(p):
            QMessageBox.information(self, "Drawing register", "That drawing's file was not found on this computer.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p) if folder else p))

    def sort_by_column(self, col):
        """Click a column heading to sort the list by it; click again to reverse."""
        if not (0 <= col < len(KEYS)):
            return
        k = KEYS[col]
        asc = not (getattr(self, "_sort", (None, True))[0] == col and getattr(self, "_sort", (None, True))[1])
        self._sort = (col, asc)

        def keyf(r):
            v = r.get(k, "")
            if k == "on":
                return (0 if v else 1,)
            t = str(v or "").strip().lower()
            digits = re.sub(r"[^0-9.]", "", t)
            try:
                return (0, float(digits), t) if digits and k in ("no", "rev", "size") and digits.replace(".", "", 1).isdigit() else (1, 0.0, t)
            except ValueError:
                return (1, 0.0, t)
        self.rows().sort(key=keyf, reverse=not asc)
        self.refresh()
        hd = self.tab.horizontalHeader()
        hd.setSortIndicatorShown(True)
        hd.setSortIndicator(col, Qt.SortOrder.AscendingOrder if asc else Qt.SortOrder.DescendingOrder)

    def remove_all(self):
        n = len(self.rows())
        if not n:
            return
        import copy
        snap = copy.deepcopy(self.state())
        self.rows().clear()
        self.refresh()
        self._toast_undo("All %d drawings taken out of the list (the PDF files are not touched)" % n, snap)

    def _toast_undo(self, message, snap):
        def undo():
            self.set_state(snap)
            self.refresh()
            try:
                self.refresh_history()
            except Exception:
                pass
        h = getattr(self, "host", None)
        if hasattr(h, "toast"):
            h.toast(message, "Undo", undo)

    def move(self, d):
        r, rows = self.tab.currentRow(), self.rows()
        if 0 <= r < len(rows) and 0 <= r + d < len(rows):
            rows[r], rows[r + d] = rows[r + d], rows[r]
            self.refresh()
            self.tab.selectRow(r + d)

    def _cell(self, it):
        if self._busy or not (0 <= it.row() < len(self.rows())):
            return
        row = self.rows()[it.row()]
        k = KEYS[it.column()]
        if k == "on":
            row["on"] = it.checkState() == Qt.CheckState.Checked
        elif k in ("rdate", "pdfdate"):
            row[k] = norm_date(it.text()) or it.text().strip()
        else:
            row[k] = it.text().strip()
        QTimer.singleShot(0, self._counts)

    def set_status_all(self, mode):
        t = self.status_all.currentText().strip()
        if not t:
            return
        if mode == "ticked":
            rs = [r for g in self.groups for r in g["rows"] if r.get("on")]
        elif mode == "block":
            rs = list(self.rows())
        else:
            rs = [r for g in self.groups for r in g["rows"]]
        for r in rs:
            r["status"] = t
        self.refresh()
        self._counts()

    def _counts(self):
        self.update_mail()
        n = sum(1 for g in self.groups for r in g["rows"] if r.get("on"))
        self.count.setText("%d drawings in this issue, %d in all" % (n, sum(len(g["rows"]) for g in self.groups)))

    def refresh(self):
        self._busy = True
        try:
            for k, e in self.f.items():
                e.setText(self.info.get(k, ""))
            self._sync_issuer()
            self.gbox.clear()
            self.gbox.addItems([g["name"] for g in self.groups])
            self.gbox.setCurrentIndex(self.cur)
            rows = self.rows()
            self.tab.setRowCount(0)
            self.tab.setRowCount(len(rows))
            for i, r in enumerate(rows):
                kind, _t = self.change_of(r)
                for c, k in enumerate(KEYS):
                    if k == "on":
                        it = QTableWidgetItem("")
                        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        it.setCheckState(Qt.CheckState.Checked if r.get("on", True) else Qt.CheckState.Unchecked)
                    else:
                        txt = str(r.get(k, ""))
                        it = QTableWidgetItem(txt)
                        if k == "file":
                            it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                            it.setToolTip(r.get("path", ""))
                        if k == "title" and kind in ("new", "revised"):
                            it.setToolTip(_t)
                        if k == "rev" and r.get("revs"):
                            it.setToolTip("\n".join("Rev %s  %s  %s" % tuple((list(x) + ["", "", ""])[:3]) for x in r["revs"]))
                    if kind in ("new", "revised"):
                        it.setBackground(QColor(120, 90, 20, 110) if kind == "revised" else QColor(30, 110, 60, 110))
                    self.tab.setItem(i, c, it)
                cb = QComboBox()
                cb.addItems(STATUSES)
                cb.setEditable(True)
                cb.setCurrentText(r.get("status", "For information"))
                cb.currentTextChanged.connect(lambda t, row=r: row.__setitem__("status", t))
                self.tab.setCellWidget(i, KEYS.index("status"), cb)
                cb2 = QComboBox()
                cb2.addItems(BYS)
                cb2.setEditable(True)
                cb2.setCurrentText(r.get("by", ""))
                cb2.currentTextChanged.connect(lambda t, row=r: row.__setitem__("by", t))
                self.tab.setCellWidget(i, KEYS.index("by"), cb2)
            self.tab.resizeRowsToContents()
            self._counts()
            self._blocks_panel()
            self.refresh_log()
        finally:
            self._busy = False

    # ----- output -----
    def issue_date(self):
        return self.info["date"].strip() or datetime.date.today().strftime("%d %B %Y")

    def groups_in_issue(self):
        out = []
        for g in self.groups:
            rows = [r for r in g["rows"] if r.get("on", True)]
            if rows:
                out.append((g["name"], rows))
        return out

    def changes(self):
        """(new, revised) rows of the issue against the last one sent."""
        new, rev = [], []
        for _n, rows in self.groups_in_issue():
            for r in rows:
                k, _t = self.change_of(r)
                if k == "new":
                    new.append(r)
                elif k == "revised":
                    rev.append(r)
        return new, rev

    @staticmethod
    def _clean(r):
        by = r.get("by") or ""
        c = (r.get("comment") or "").strip()
        if by and c.lower().startswith(by.lower().split()[0]):
            c = re.sub(r"^\s*[A-Za-z ]{3,22}[:\-]\s*", "", c)
        return c

    def _local_addresses(self):
        from email.utils import getaddresses
        out = []
        for t in [self.info.get("email", ""), self.info.get("cc", "")] + [x.get("req_from", "") for x in self.log] + [x.get("sent_to", "") for x in self.log] \
                + [x.get("by_email", "") for x in self.log]:
            out += [(n, a) for n, a in getaddresses([t or ""]) if a]
        n = (self.info.get("to") or "").strip()
        if n and self.info.get("email"):
            out.append((n, self.info["email"].split(",")[0].split(";")[0].strip()))
        return out

    def _contacts_state(self):
        """Load the Google contacts in the background and tell the person if one more sign-in is needed."""
        try:
            import contacts
            M = self._M()
            if not getattr(self, "_hint_wired", False):
                self._hint_wired = True
                contacts.model()
                contacts._state["bus"].loaded.connect(lambda *_: self.contacts_hint.setVisible(False))
            contacts.set_local(self._local_addresses())
            contacts.refresh_async(M)
            S = M.SETTINGS
            need = S.get("mail_provider") != "gmail" or not S.get("google_refresh") or bool(S.get("contacts_note"))
            self.contacts_hint.setVisible(need and not contacts.count())
            self.contacts_hint.setText("To get your Gmail contacts here as you type: Email account > Sign in with Google (once more) and allow contacts."
                                       if S.get("mail_provider") == "gmail" else
                                       "Tip: sign in with Google (Email account) and the contacts of that Gmail account will appear here as you type.")
        except Exception:
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        self.link_bar.refresh()
        self._contacts_state()

    def load_contacts_now(self):
        """More > Load my Gmail contacts: fetch now and say exactly what happened."""
        import contacts
        contacts.model()
        bus = contacts._state["bus"]

        def done(msg, ok, need):
            try:
                bus.finished.disconnect(done)
            except Exception:
                pass
            if ok:
                QMessageBox.information(self, "Gmail contacts", msg + "\nClick the arrow at the right of an email box to choose one.")
            elif need:
                if QMessageBox.question(self, "Gmail contacts", msg + "\n\nSign in with Google again now and tick the contacts permission?") == QMessageBox.StandardButton.Yes:
                    self.email_account()
            else:
                QMessageBox.warning(self, "Gmail contacts", msg)
            self._contacts_state()
        bus.finished.connect(done)
        contacts.refresh_async(self._M(), force=True, report=True)

    def _contacts_on(self, line_edit):
        try:
            import contacts
            contacts.attach(line_edit, self._M)
        except Exception:
            pass

    def issuer(self):
        """Who the register is issued by: the signature of the person using the program."""
        try:
            nm = str(self._M().SETTINGS.get("sig_name", "") or "").strip()
            if nm:
                return nm
            from register_ext import signature_text
            t = [x for x in signature_text(self._M().SETTINGS, "").split("\n") if x.strip()]
            return t[0] if t else ""
        except Exception:
            return self.info.get("issued_by", "")

    def _sync_issuer(self):
        if hasattr(self, "issued_btn"):
            self.issued_btn.setText(self.issuer() or "Click to set your name and details (your email signature)...")

    def rev_items(self, r):
        """The revision-column rows of this drawing that are newer than the last issue: [(rev, date, description)]."""
        h = self.last_issue()
        o = ((h or {}).get("rows") or {}).get(self.key(r)) or {}
        orev, odate = (o.get("rev") or ""), (o.get("rdate") or "")
        out = []
        for it in sorted((tuple(str(v or "") for v in x[:3]) for x in (r.get("revs") or []) if len(x) >= 3), key=lambda x: (x[1], x[0])):
            rv, dt, ds = it[0], it[1], it[2]
            if not ds:
                continue
            if o:
                if odate and dt:
                    if dt < odate or (dt == odate and (not o.get("maxid") or rv <= o["maxid"])):
                        continue
                elif (o.get("maxid") or orev) and rv <= (o.get("maxid") or orev):
                    continue
            out.append((rv, dt, ds))
        return out

    @staticmethod
    def _clean_desc(ds):
        """A revision description without the codes that sometimes lead it ("01 ", "Rev B - ", "A: ")."""
        t = (ds or "").strip()
        c = re.sub(r"^\s*(?:rev(?:ision)?\.?\s*)?[A-Za-z]?\d{0,3}\s*[-:.)]\s+", "", t, flags=re.I)
        c = re.sub(r"^\s*(?:rev(?:ision)?\.?\s*)?\d{1,3}\s+(?=[A-Za-z])", "", c, flags=re.I)
        return (c or t).strip(" -:")

    def change_items(self, r):
        """What changed on one drawing, one entry per revision row newer than the last issue: [(description, rev)], described rows only."""
        try:
            items = self.rev_items(r)
        except Exception:
            items = []
        return [(self._clean_desc(ds), rv) for rv, _dt, ds in items if (ds or "").strip()]

    def _what(self, r):
        """What changed on a drawing, read from the title block's revision column: 'Kitchen moved (Rev 02); Bedroom 2 enlarged (Rev 03)'. Falls back to the typed comment."""
        its = self.change_items(r)
        by = r.get("by") or ""
        if its:
            return (by + ": " if by else "") + "; ".join(d for d, _rv in its)
        return self._why(r)

    def _why(self, r):
        by, c = r.get("by") or "", self._clean(r)
        return (by + (": " if by and c else "") + c) if (by or c) else "no reason given"

    REPORTS = (("lv", "Light & Ventilation report", "SANS 10400-O natural light and ventilation, room by room"),
               ("xa", "Energy XA report", "SANS 10400-XA energy usage: walls, roofs and glazing"),
               ("rd", "Rational design report", "SANS 10400-XA rational design"),
               ("cov", "Coverage and FAR report", "site coverage and floor area ratio"))

    def reports_ticked(self):
        on = {k for k, c in getattr(self, "rep_chk", {}).items() if c.isChecked()}
        return [(k, lab, d) for k, lab, d in self.REPORTS if k in on]

    def _blocks_panel(self):
        self._sync_kind()
        """One tick box per block or house: tick it to send it now, leave it unticked to tell the client it is still to come."""
        lay = self.blocks_l
        while lay.count():
            it = lay.takeAt(0)
            w_ = it.widget()
            if w_ is not None:
                w_.setParent(None)
                w_.deleteLater()
        multi = len(self.groups) > 1
        lay.addWidget(QLabel("<b>Send now:</b>"))
        for gi_, g in enumerate(self.groups):
            n = len(g["rows"])
            on = sum(1 for r in g["rows"] if r.get("on", True))
            c = QCheckBox("%s (%d)" % (g["name"], n))
            c.setEnabled(n > 0)
            c.setCheckState(Qt.CheckState.Checked if on == n and n else Qt.CheckState.PartiallyChecked if on else Qt.CheckState.Unchecked)
            c.setToolTip("Tick to send every drawing of this block or house in this issue. Untick to hold it back: it is then listed as still to come.")
            c.clicked.connect(lambda _x=False, g=g, all_on=(on == n): self._block_toggle(g, not all_on))
            lay.addWidget(c)
        lay.addStretch(1)
        now = [(g["name"], sum(1 for r in g["rows"] if r.get("on", True))) for g in self.groups]
        later = [(g["name"], sum(1 for r in g["rows"] if not r.get("on", True))) for g in self.groups]
        now = [(n, k) for n, k in now if k]
        later = [(n, k) for n, k in later if k]
        if not later:
            txt = "Sending now: all %d drawings." % sum(k for _n, k in now) if now else "Nothing is ticked to send yet."
        else:
            txt = "<b>Sending now:</b> %s.  <b>Not in this issue (listed for the client as still to come):</b> %s." % (
                ", ".join("%s (%d)" % x for x in now) or "nothing", ", ".join("%s (%d)" % x for x in later))
        self.plan_lbl.setText(txt if now or later else "")

    def _block_toggle(self, g, on):
        for r in g["rows"]:
            r["on"] = bool(on)
        self.refresh()
        self.update_mail()

    @staticmethod
    def read_sheet_index(path):
        """[(number, title, rev)] from a sheet index exported by Archicad (.csv, .txt, .tsv or .xlsx). The columns are found by their headings."""
        import csv, io
        rows = []
        if path.lower().endswith(".pdf"):
            return RegisterPage.read_sheet_index_pdf(path)
        if path.lower().endswith((".xlsx", ".xlsm")):
            import openpyxl
            ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
            rows = [[("" if c is None else str(c)).strip() for c in r] for r in ws.iter_rows(values_only=True)]
        else:
            raw = open(path, "rb").read()
            text = ""
            for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue
            sample = "\n".join(text.splitlines()[:5])
            delim = max("\t;,", key=lambda d: sample.count(d))
            rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
        rows = [r for r in rows if any(r)]
        hi, cols = -1, {}
        for i, r in enumerate(rows[:15]):
            low = [c.lower() for c in r]
            def find(*pats):
                for j, c in enumerate(low):
                    if any(re.search(p, c) for p in pats):
                        return j
                return None
            no, ti, rv = find(r"^(id|no\.?|number|nr\.?|sheet|drawing|layout)\b", r"\bno\b|number|\bid\b"), find(r"name|title|description"), find(r"rev")
            if no is not None and ti is not None and no != ti:
                hi, cols = i, {"no": no, "title": ti, "rev": rv}
                break
        if hi < 0:
            hi, cols = -1, {"no": 0, "title": 1 if max(len(r) for r in rows) > 1 else 0, "rev": None}
        out = []
        for r in rows[hi + 1:]:
            g = lambda k: (r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else "").strip()
            no, title = g("no"), g("title")
            if title or no:
                out.append((no, title, g("rev")))
        return out

    @staticmethod
    def read_sheet_index_pdf(path):
        """[(number, title, rev)] from a sheet index that is a PDF (a table of drawing numbers and names). Rows are rebuilt from the position of the words;
        the columns are found from the heading row when there is one."""
        import fitz
        NUM = re.compile(r"^[A-Za-z]{0,6}[-_./]?\d[\w.\-/]*$")
        REV = re.compile(r"^([A-Za-z]{1,2}|\d{1,2}|-)$")
        doc = fitz.open(path)
        out, seen = [], set()
        for page in doc:
            words = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
            lines, cur, cy = [], [], None
            for w in words:
                y = (w[1] + w[3]) / 2
                if cy is None or abs(y - cy) <= 3.5:
                    cur.append(w)
                    cy = y if cy is None else (cy + y) / 2
                else:
                    lines.append(cur)
                    cur, cy = [w], y
            if cur:
                lines.append(cur)
            cells_of = []
            for ln in lines:
                ln.sort(key=lambda w: w[0])
                cells = []
                for w in ln:
                    if cells and w[0] - cells[-1][2] < 9:
                        cells[-1][2] = w[2]
                        cells[-1][3] += " " + w[4]
                    else:
                        cells.append([w[0], w[0], w[2], w[4]])
                cells_of.append([(c[0], c[3]) for c in cells])
            head = None
            for cells in cells_of:
                low = [t.lower() for _x, t in cells]
                if any(re.search(r"^(no\.?|number|nr\.?|id|sheet|drawing|layout)\b|\bno\b|number", t) for t in low) and any(re.search(r"name|title|description", t) for t in low):
                    head = {"no": next(i for i, t in enumerate(low) if re.search(r"^(no\.?|number|nr\.?|id|sheet|drawing|layout)\b|\bno\b|number", t)),
                            "title": next(i for i, t in enumerate(low) if re.search(r"name|title|description", t)),
                            "rev": next((i for i, t in enumerate(low) if t.startswith("rev")), None), "x": [x for x, _t in cells]}
                    break
            for cells in cells_of:
                if head:
                    if cells and cells[0][1].lower() == "" :
                        continue
                    cols = {}
                    for x, t in cells:
                        ci = max([i for i, hx in enumerate(head["x"]) if hx <= x + 4] or [0])
                        cols[ci] = (cols.get(ci, "") + " " + t).strip()
                    no, title, rev = cols.get(head["no"], ""), cols.get(head["title"], ""), cols.get(head["rev"], "") if head["rev"] is not None else ""
                else:
                    texts = [t for _x, t in cells]
                    if len(texts) < 2:
                        continue
                    no, title = texts[0], texts[1]
                    rev = next((t for t in texts[2:] if REV.match(t)), "")
                if not NUM.match(no) or not title or (no, title) in seen:
                    continue
                seen.add((no, title))
                out.append((no, title, rev))
        return out

    def import_sheet_index(self):
        """Pick the sheet index file(s); one per block or house, or one for the whole job. A small window shows what was found and lets you name each block."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        files, _ = QFileDialog.getOpenFileNames(self, "Sheet index from Archicad: pick one for each block or house (you can pick several)", "", "Sheet index (*.pdf *.csv *.txt *.tsv *.xlsx);;All files (*)")
        if not files:
            return
        self._load_indexes(files)

    def import_sheet_index_folder(self):
        """Point to the folder that holds the block folders; every sheet index inside it (also in the sub folders) is found and named from its file or folder name."""
        top = QFileDialog.getExistingDirectory(self, "Pick the folder that holds your sheet indexes (the block folders can be inside it)")
        if not top:
            return
        files = []
        for root, _dirs, names in os.walk(top):
            for n in sorted(names):
                if n.lower().endswith((".pdf", ".csv", ".txt", ".tsv", ".xlsx")) and re.search(r"index|drawing list|sheet list|layout list|register", n, re.I):
                    files.append(os.path.join(root, n))
        if not files:
            QMessageBox.information(self, "Drawing register", "No sheet index found in that folder. A sheet index file has the word index in its name, for example \"Block A sheet index.pdf\" or a file called \"Sheet index.pdf\" inside a folder called Block A.")
            return
        self._load_indexes(files)

    @staticmethod
    def _block_name_of(path):
        """Block or house name from the file name ("Block A sheet index.pdf" -> Block A); when the file only says "Sheet index", from the folder it is in."""
        stem = os.path.splitext(os.path.basename(path))[0]
        name = re.sub(r"(?i)[\s_.-]*\b(sheet|drawing|layout)?[\s_-]*(index|list|register)\b[\s_-]*", " ", stem).strip(" _-.")
        name = re.sub(r"(?i)\b(rev|revision)\s*\w*$", "", name).strip(" _-.")
        if not name:
            name = os.path.basename(os.path.dirname(os.path.abspath(path))) or stem
        return name

    def _load_indexes(self, files):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        found = []
        for f in files:
            try:
                items = self.read_sheet_index(f)
            except Exception as e:
                QMessageBox.warning(self, "Drawing register", "Could not read %s:\n%s" % (os.path.basename(f), e))
                continue
            if not items:
                QMessageBox.information(self, "Drawing register", "No drawings found in %s. (A scanned PDF, which is only a picture, cannot be read.)" % os.path.basename(f))
                continue
            found.append((f, items))
        if not found:
            return
        names = [g["name"] for g in self.groups]
        d = QDialog(self)
        d.setWindowTitle("Load the sheet index")
        v = QVBoxLayout(d)
        v.addWidget(QLabel("Here is what was found. Give each list a name: the block or house it belongs to (pick one or type your own).\nUntick a list you do not want."))
        t = QTableWidget(len(found), 3)
        t.setHorizontalHeaderLabels(["Use", "Block or house", "Drawings found"])
        t.verticalHeader().setVisible(False)
        t.setMinimumSize(620, 40 + 34 * min(len(found), 8))
        boxes = []
        for i, (f, items) in enumerate(found):
            ck = QTableWidgetItem("")
            ck.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            ck.setCheckState(Qt.CheckState.Checked)
            t.setItem(i, 0, ck)
            stem = self._block_name_of(f)
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItems(names)
            cb.setCurrentText(next((n for n in names if n.lower() == stem.lower()), stem))
            t.setCellWidget(i, 1, cb)
            boxes.append(cb)
            it = QTableWidgetItem("%d   (%s)" % (len(items), os.path.basename(f)))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            t.setItem(i, 2, it)
        t.setColumnWidth(0, 40)
        t.setColumnWidth(1, 240)
        t.horizontalHeader().setStretchLastSection(True)
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Add them")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if not d.exec():
            return
        total = skipped = 0
        blank = [g for g in self.groups if not g["rows"]]
        for i, (f, items) in enumerate(found):
            if t.item(i, 0).checkState() != Qt.CheckState.Checked:
                continue
            name = boxes[i].currentText().strip() or "Block"
            g = next((x for x in self.groups if x["name"].lower() == name.lower()), None)
            if g is None and blank:
                g = blank.pop(0)                    # the empty starting block takes the first name instead of staying empty
                g["name"] = name
            if g is None:
                g = {"name": name, "rows": []}
                self.groups.append(g)
            if g in blank:
                blank.remove(g)
            for no, title, rev in items:
                row = {"on": False, "no": no, "title": title, "about": "", "size": "", "scale": "", "rev": rev, "rdate": "", "pdfdate": "", "by": "", "comment": "", "status": "For information", "file": "", "path": "", "revs": []}
                old = self.find_in_group(g, self.key(row))
                if old is not None:
                    if not old.get("title") and title:
                        old["title"] = title
                    skipped += 1
                    continue
                g["rows"].append(row)
                total += 1
            g["rows"].sort(key=lambda r: (r.get("no") or "~", r.get("title", "").lower()))
        self.cur = min(self.cur, len(self.groups) - 1)
        self.refresh()
        self.update_mail()
        self.count.setText("%d drawing%s loaded from the sheet index%s. Now add the PDFs you are sending today (B)." % (total, "" if total == 1 else "s",
                           (" (%d already in that block, left as they were)" % skipped) if skipped else ""))
        if self._mail_manual:
            QMessageBox.information(self, "Drawing register", "The drawings are loaded. Your email was edited by hand, so it was not updated: press \"Write it again\" (step 3) to bring the sheet index into it.")

    def add_planned(self):
        """Type drawings that are not ready yet (one per line, number then title) so they show as still to come."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit
        d = QDialog(self)
        d.setWindowTitle("Drawings still to come")
        v = QVBoxLayout(d)
        v.addWidget(QLabel("Which block or house are they for?"))
        box = QComboBox()
        box.addItems([g["name"] for g in self.groups])
        box.setCurrentIndex(self.cur)
        v.addWidget(box)
        v.addWidget(QLabel("One drawing per line: the drawing number, then its name. For example:\n101  Ground floor plan\n102  First floor plan"))
        te = QPlainTextEdit()
        te.setMinimumSize(420, 160)
        v.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if not d.exec():
            return
        g = self.groups[box.currentIndex()]
        added = 0
        for line in te.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\t|\s{2,}|\s+-\s+", line, maxsplit=1)
            if len(parts) < 2:
                parts = line.split(None, 1) if re.match(r"^[A-Za-z]*[\d.-]+\S*\s+\S", line) else ["", line]
            no, title = parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
            row = {"on": False, "no": no, "title": title, "about": "", "size": "", "scale": "", "rev": "", "rdate": "", "pdfdate": "", "by": "", "comment": "", "status": "For information", "file": "", "path": "", "revs": []}
            if self.find_in_group(g, self.key(row)) is not None:
                continue
            g["rows"].append(row)
            added += 1
        g["rows"].sort(key=lambda r: (r.get("no") or "~", r.get("title", "").lower()))
        self.refresh()
        self.update_mail()
        self.count.setText("%d drawing%s added as still to come." % (added, "" if added == 1 else "s"))

    def _style_idx_btn(self):
        on = self.idx_btn.isChecked()
        self.idx_btn.setText("Sheet index (what is still to come): ON" if on else "Sheet index (what is still to come): OFF")
        self.idx_btn.setStyleSheet("QPushButton{background-color:%s;color:#FFFFFF;font-weight:700;border:1px solid %s;border-radius:8px;padding:6px 14px;}"
                                   "QPushButton:hover{background-color:%s;}" % (("#1F7A8C", "#16596A", "#2791A6") if on else ("#6B6F78", "#50545C", "#7B808A")))

    def _idx_toggled(self, on):
        self.info["show_index"] = "1" if on else "0"
        self._style_idx_btn()
        self.update_mail()

    def _opt_changed(self, k, on):
        self.info[k] = "1" if on else "0"
        self.update_mail()
        try:
            self.refresh()
        except Exception:
            pass

    def issue_kind(self):
        """revised, new or these. Until you choose, it is revised when something was sent before, otherwise a new set."""
        k = self.info.get("issue_kind", "")
        if k in ("revised", "new", "these"):
            return k
        return "revised" if self.last_issue() else "new"

    def _sync_kind(self):
        if not hasattr(self, "kind_box"):
            return
        if hasattr(self, "idx_btn") and self.idx_btn.isChecked() != (self.info.get("show_index") != "0"):
            self.idx_btn.blockSignals(True)
            self.idx_btn.setChecked(self.info.get("show_index") != "0")
            self.idx_btn.blockSignals(False)
            self._style_idx_btn()
        i = self.kind_box.findData(self.issue_kind())
        if i >= 0 and i != self.kind_box.currentIndex():
            self.kind_box.blockSignals(True)
            self.kind_box.setCurrentIndex(i)
            self.kind_box.blockSignals(False)

    def _kind_changed(self, *_a):
        self.info["issue_kind"] = self.kind_box.currentData()
        self.update_mail()

    def want_log(self, kind):
        return self.info.get("show_orders" if kind == "Order" else "show_changes") == "1"

    def _sent_in(self, h, group, r):
        """The entry of drawing r (of this block or house) in an issue that was sent, or None. Older issues only know the drawing number."""
        lk = self._loose(self.key(r))
        gs = h.get("groups") or []
        if gs:
            for g in gs:
                if str(g.get("name", "")).strip().lower() == str(group).strip().lower():
                    for d in g.get("drawings") or []:
                        if self._loose((d.get("no") or d.get("title", "")).strip().lower()) == lk:
                            return d
            return None
        return (h.get("rows") or {}).get(self.key(r))

    def sheet_index(self):
        """Every drawing of every block/house: [(group name, [(row, state, note)], n_today)], or [] when there is nothing more than today's issue to show.
        state is 'today', 'earlier' or 'not'."""
        if self.info.get("show_index") == "0":
            return []
        out, total, today = [], 0, 0
        for g in self.groups:
            rows = []
            for r in g["rows"]:
                if r.get("on", True):
                    rows.append((r, "today", ""))
                    today += 1
                else:
                    for h in reversed(self.history):
                        o = self._sent_in(h, g["name"], r)
                        if o is not None:
                            note = "REV %s, %s" % (o.get("rev") or "-", h.get("date", "")) if (o.get("rev") or h.get("date")) else ""
                            rows.append((r, "earlier", note))
                            break
                    else:
                        rows.append((r, "not", ""))
                total += 1
            if rows:
                out.append((g["name"], rows, sum(1 for _r, st, _n in rows if st == "today")))
        if total <= today and len(out) <= 1:
            return []
        return out

    def _reports_changed(self, *_a):
        """A report was ticked or unticked: the email and the register PDF list it, so write the email again (unless it was edited by hand)."""
        self.update_mail()

    def write_mail(self):
        gi = self.groups_in_issue()
        to = self.info["to"].strip()
        last = self.last_issue()
        new, rev = self.changes()
        kind = self.issue_kind()
        intro = {"revised": "Please find the revised drawings", "new": "Please find attached a new set of drawings", "these": "Please find attached the following drawings"}[kind]
        lines = ["Subject: %s - revision %s (%s)" % (self.project_name(), self.info["issue_no"] or "0", self.issue_date()), "",
                 "Hi %s," % (to.split()[0] if to else "there"), "",
                 "%s for %s issued today, %s. The drawing register is attached." % (intro, self.project_name(), self.issue_date()), ""]
        if kind != "revised":
            last = None             # a new set (or just these drawings): no comparison with an earlier issue
        if last and (rev or new):
            lines.append("WHAT CHANGED SINCE REVISION %s (%s)" % (last.get("issue", ""), last.get("date", "")))
            for r in rev:
                lines.append("%s  %s%s" % (r.get("no") or "-", (r.get("title", "") or "").upper(), ("  (REVISION %s)" % r["rev"]) if r.get("rev") else ""))
                its = self.change_items(r)
                if its:
                    for d, _rv in its:
                        lines.append("  - %s" % d)
                else:
                    lines.append("  - " + self._why(r))
            for r in new:
                lines.append("%s  %s%s" % (r.get("no") or "-", (r.get("title", "") or "").upper(), ("  (REVISION %s)" % r["rev"]) if r.get("rev") else ""))
                lines.append("  - New drawing: %s" % (r.get("about", "") or "added to the set"))
            lines.append("")
        elif last:
            lines += ["No drawing has changed since revision %s." % last.get("issue", ""), ""]
        names = {n for n, _r in gi}
        for kind_, head_ in (("Order", "ORDERS COVERED BY THIS REVISION"), ("Change", "CLIENT CHANGES COVERED BY THIS REVISION")):
            pend = [x for x in self.log if not x.get("sent_date") and x.get("group") in names and self.log_kind(x) == kind_]
            if not (pend and self.want_log(kind_)):
                continue
            lines.append(head_)
            for x in pend:
                bit = "  - %s" % x.get("group", "")
                bit += (" (order no. %s)" % x["order"]) if x.get("order") else ""
                if x.get("auto_text") and x.get("text") == x.get("auto_text"):
                    bit += ": the changes listed above"            # made from the drawings: not repeated here, only its kind of change
                else:
                    bit += ": " + (x.get("text") or ("New order" if x.get("type") == "Order" else "Change")).replace("\n", "  /  ")
                if x.get("kinds"):
                    bit += " [%s]" % x["kinds"]
                if x.get("by_name") or x.get("by_email"):
                    bit += " [asked by %s]" % " ".join(t for t in (x.get("by_name", ""), ("<%s>" % x["by_email"]) if x.get("by_email") else "") if t)
                if x.get("req_subject"):
                    bit += " [your email: %s%s]" % (x["req_subject"], ", " + short_date(x["req_date"]) if x.get("req_date") else "")
                lines.append(bit)
            lines.append("")
        idx = self.sheet_index()
        if idx:
            # one list for everything: what goes today (with its details) and what is still to come, block by block
            lines.append("THE DRAWINGS: ISSUED TODAY AND STILL TO COME")
            now_ = ["%s (%d of %d)" % (nm, nt, len(rs)) for nm, rs, nt in idx if nt]
            later_ = [(nm, sum(1 for _r, st, _n in rs if st == "not")) for nm, rs, _nt in idx]
            later_ = ["%s (%d drawing%s)" % (nm, k, "" if k == 1 else "s") for nm, k in later_ if k]
            early_ = ["%s (%d)" % (nm, sum(1 for _r, st, _n in rs if st == "earlier")) for nm, rs, _nt in idx if any(st == "earlier" for _r, st, _n in rs)]
            lines.append(("Issued today: %s. " % ", ".join(now_) if now_ else "") + ("Issued earlier: %s. " % ", ".join(early_) if early_ else "")
                         + ("Still to come: %s." % ", ".join(later_) if later_ else "Nothing else is outstanding."))
            lines.append("")
            for name, rows, nt in idx:
                lines.append("%s (%d drawing%s) - %d ISSUED TODAY" % (name.upper(), len(rows), "" if len(rows) == 1 else "s", nt))
                for r, st, note in rows:
                    lab = {"today": "ISSUED TODAY", "earlier": "ISSUED EARLIER" + ((" (%s)" % note) if note else ""), "not": "NOT YET ISSUED"}[st]
                    sz = "%s%s" % (r.get("size", ""), (", " + r["scale"]) if r.get("scale") else "")
                    lines.append("  - %s | %s | Rev %s | %s | %s%s" % ((r.get("no") or "-").replace("|", "/"), (r.get("title", "") or "").replace("|", "/"), r.get("rev") or "-", sz or "-", lab,
                                                                  (" | " + r["about"]) if (st == "today" and r.get("about")) else ""))
                lines.append("")
        else:
            lines.append("THE FULL LIST" if (last and kind == "revised") else "THE DRAWINGS")
            for name, rows in gi:
                lines.append(name.upper() + (" (%d drawings)" % len(rows)))
                for r in rows:
                    bit = "  - %s  %s  Rev %s  (%s%s)" % (r.get("no") or "-", r.get("title", ""), r.get("rev") or "-", r.get("size", ""), ", " + r["scale"] if r.get("scale") else "")
                    bit += ": " + r["about"] if r.get("about") else ""
                    lines.append(bit.replace("  -  ", "  - "))
                lines.append("")
        reps = self.reports_ticked()
        if reps:
            lines.append("REPORTS SENT WITH THIS ISSUE (%d)" % len(reps))
            for _k, lab, d in reps:
                lines.append("  - %s: %s" % (lab, d))
            lines.append("")
        statuses = sorted({r.get("status", "") for _n, rows in gi for r in rows})
        if statuses:
            lines += ["Status of this revision: " + ", ".join(statuses) + ".", ""]
        if self.info["note"].strip():
            lines += [self.info["note"].strip(), ""]
        lines += ["Please let me know if anything is missing or if you have comments.", "", "Regards,"]
        try:
            from register_ext import signature_text
            lines.append(signature_text(self._M().SETTINGS, self.info["issued_by"].strip() or "MCP Architecture & Interiors"))
        except Exception:
            lines.append(self.info["issued_by"].strip() or "MCP Architecture & Interiors")
        self.mail.setPlainText("\n".join(lines))

    def _mail_parts(self):
        if not self.mail.toPlainText().strip():
            self.write_mail()
        t = self.mail.toPlainText()
        subj = ""
        if t.startswith("Subject:"):
            first, _, rest = t.partition("\n")
            subj, t = first[8:].strip(), rest.lstrip("\n")
        return subj, t

    def copy_mail(self):
        subj, body = self._mail_parts()
        QGuiApplication.clipboard().setText((("Subject: " + subj + "\n\n") if subj else "") + body)
        self.count.setText("Email text copied")

    def open_mail(self):
        from urllib.parse import quote
        subj, body = self._mail_parts()
        QDesktopServices.openUrl(QUrl("mailto:%s?subject=%s&body=%s" % (self.info["email"].strip(), quote(subj), quote(body))))

    def report_parts(self):
        e = lambda x: _html.escape(str(x))
        RED, DARK = "#C8102E", "#DCDCDC"
        th = lambda t, w: '<th bgcolor="%s" align="left" width="%s%%" style="padding:3px;">%s</th>' % (DARK, w, t)
        td = lambda t, a="left", bg="": '<td%s style="padding:3px;text-align:%s;">%s</td>' % (' bgcolor="%s"' % bg if bg else "", a, t)
        gi = self.groups_in_issue()
        n = sum(len(r) for _g, r in gi)
        last = self.last_issue() if self.issue_kind() == "revised" else None
        new, rev = self.changes()
        out = ['<p style="font-size:9pt;color:#444;">%d drawings in this issue.%s</p>' %
               (n, (" %d revised and %d new since revision %s." % (len(rev), len(new), e(last.get("issue", "")))) if last else "")]
        for kind_ in ("Order", "Change"):
            if self.want_log(kind_):
                out.append(self.log_html(e, td, th, RED, only=kind_))
        if last and (rev or new):
            body = ""
            for r in rev:
                _k, t = self.change_of(r)
                body += "<tr>%s%s%s%s%s</tr>" % (td(e(r.get("no", ""))), td("<b>%s</b>" % e(r.get("title", ""))), td(e(t.replace("Revised: ", "")), "center"),
                                                  td(e(r.get("rdate") or r.get("pdfdate", "")), "center"), td(e(self._why(r))))
            for r in new:
                body += "<tr>%s%s%s%s%s</tr>" % (td(e(r.get("no", ""))), td("<b>%s</b>" % e(r.get("title", ""))), td("New", "center"),
                                                  td(e(r.get("rdate") or r.get("pdfdate", "")), "center"), td(e(r.get("about", ""))))
            out.append('<h3 style="color:%s;margin-bottom:3px;">Changes since revision %s (%s)</h3>' % (RED, e(last.get("issue", "")), e(last.get("date", ""))))
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' %
                       ("".join((th("No.", 8), th("Drawing", 24), th("Change", 14), th("Date", 10), th("Why / what was changed", 44))), body))
        for name, rows in gi:
            body = ""
            for i, r in enumerate(rows):
                kind, _t = self.change_of(r)
                bg = "#FFF1CC" if kind == "revised" else "#DDF3E4" if kind == "new" else ("#F6F6F6" if i % 2 else "")
                cmt = self._clean(r)
                if r.get("by"):
                    cmt = "<i>%s</i>%s" % (e(r["by"]), (": " + e(cmt)) if cmt else "")
                else:
                    cmt = e(cmt)
                cells = (td(e(r.get("no", "")), bg=bg), td("<b>%s</b>" % e(r.get("title", "")), bg=bg), td(e(r.get("about", "")), bg=bg), td(e(r.get("size", "")), "center", bg),
                         td(e(r.get("scale", "")), "center", bg), td("<b>%s</b>" % e(r.get("rev", "")), "center", bg), td(e(r.get("rdate", "")), "center", bg),
                         td(e(r.get("pdfdate", "")), "center", bg), td(cmt, bg=bg), td(e(r.get("status", "")), bg=bg))
                body += "<tr>%s</tr>" % "".join(cells)
            out.append('<h3 style="color:%s;margin-bottom:3px;">%s</h3>' % (RED, e(name)))
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8pt;"><tr>%s</tr>%s</table>' %
                       ("".join((th("No.", 6), th("Drawing", 15), th("What it shows", 22), th("Size", 4), th("Scale", 5), th("Rev", 3), th("Rev date", 8),
                                 th("PDF'd", 8), th("What changed", 19), th("Status", 10))), body))
        idx = self.sheet_index()
        if idx:
            out.append('<h3 style="color:%s;margin-bottom:3px;">Sheet index: issued today and still to come</h3>' % RED)
            for name, rows, nt in idx:
                body = ""
                for i, (r, st, note) in enumerate(rows):
                    bg, lab = {"today": ("#DDF3E4", "Issued today"), "earlier": ("#F6F6F6", "Issued earlier" + ((" (%s)" % note.title()) if note else "")), "not": ("#FFF1CC", "Not yet issued")}[st]
                    body += "<tr>%s%s%s%s</tr>" % (td(e(r.get("no", "")), bg=bg), td("<b>%s</b>" % e(r.get("title", "")), bg=bg), td(e(r.get("rev", "") or "-"), "center", bg), td(lab, bg=bg))
                out.append('<p style="font-size:9pt;"><b>%s</b>: %d drawings, %d issued today.</p>' % (e(name), len(rows), nt))
                out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' %
                           ("".join((th("No.", 12), th("Drawing", 50), th("Rev", 8), th("Status", 30))), body))
        reps = self.reports_ticked()
        if reps:
            out.append('<h3 style="color:%s;margin-bottom:3px;">Reports issued with this register</h3>' % RED)
            out.append('<table width="100%%" border="0.6" cellspacing="0" style="font-size:8.5pt;"><tr>%s</tr>%s</table>' % (
                "".join((th("Report", 30), th("What it covers", 52), th("Revision", 8), th("Date", 10))),
                "".join("<tr>%s%s%s%s</tr>" % (td("<b>%s</b>" % e(lab)), td(e(d[:1].upper() + d[1:])), td(e(self.info["issue_no"] or "0"), "center"),
                                               td(e(self.issue_date()), "center")) for _k, lab, d in reps)))
        if self.history:
            out.append('<p style="font-size:7.5pt;color:#666;">Earlier revisions: %s.</p>' % e("; ".join("revision %s, %s (%d drawings)" % (h.get("issue", ""), h.get("date", ""), len(h.get("rows", {}))) for h in self.history)))
        out.append('<p style="font-size:7.5pt;color:#666;">Revision, revision date and drawing number are read from the title block of each drawing; PDF\'d is the date the PDF was made. '
                   'Shaded rows are new or revised since the last issue. Use the latest revision of every drawing; earlier revisions are superseded.</p>')
        return [x for x in out if x]

    def report_html(self):
        return "".join(self.report_parts())

    def cover_html(self):
        e = lambda x: _html.escape(str(x))
        rd = getattr(self.host, "rd", {}) or {}
        RED, DARK = "#C8102E", "#DCDCDC"
        company = rd.get("company") or "MCP Architecture & Interiors"
        client_logo = '<img src="client_logo" height="55">' if "client_logo" in self.logos() else ""
        h = ('<p style="font-size:40pt;">&nbsp;</p><p align="center"><img src="logo" height="90"></p>'
             '<p align="center" style="font-size:11pt; color:#444444;">%s</p><p style="font-size:30pt;">&nbsp;</p>'
             '<table width="100%%" cellspacing="0" cellpadding="14" border="0"><tr><td bgcolor="%s" style="color:#222222;">'
             '<span style="font-size:24pt; font-weight:bold;">DRAWING REGISTER</span><br>'
             '<span style="font-size:9pt; color:#555555;">Revision %s &nbsp;|&nbsp; %s</span></td></tr></table>'
             '<table width="100%%" cellspacing="0" cellpadding="0" border="0"><tr><td bgcolor="%s" height="4"></td></tr></table>' %
             (e(company), DARK, e(self.info["issue_no"] or "0"), e(self.issue_date()), RED))
        h += ('<p style="font-size:12pt;">&nbsp;</p><p style="font-size:9pt; color:#666666;">PROJECT</p>'
              '<p style="font-size:16pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>'
              '<p style="font-size:9pt; color:#666666;">SITE</p>'
              '<p style="font-size:13pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>' % (e(self.project_name()), e(rd.get("details") or "-")))
        h += ('<p style="font-size:12pt;">&nbsp;</p><table width="100%%" cellspacing="0" cellpadding="3" border="0"><tr>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">CLIENT<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">ISSUED TO<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td></tr></table>'
              '<p style="font-size:8pt;">&nbsp;</p><table width="100%%" cellspacing="0" cellpadding="3" border="0"><tr>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">ARCHITECTURE FIRM<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%s</span></td>'
              '<td width="50%%" style="font-size:8.5pt; color:#666666;">DRAWINGS IN THIS REVISION<br><span style="font-size:12pt; font-weight:bold; color:#222222;">%d</span></td></tr></table>' %
              (e(self.info["client"] or rd.get("owner") or "-"), e(self.info["to"] or "-"), e(rd.get("architect") or company),
               sum(len(r) for _g, r in self.groups_in_issue())))
        if client_logo:
            h += '<p style="font-size:10pt;">&nbsp;</p><p align="right">%s</p>' % client_logo
        h += ('<p style="font-size:20pt;">&nbsp;</p><p style="font-size:9pt; color:#666666;">THIS REGISTER WAS COMPILED BY</p>'
              '<p style="font-size:12pt; font-weight:bold; color:#222222; margin-top:0px;">%s</p>' % e(self.issuer() or rd.get("prepared_by") or company))
        if rd.get("contact"):
            h += '<p style="font-size:8pt; color:#777777;">%s</p>' % e(rd["contact"])
        return h

    def write_pdf(self, path):
        """Cover page like the other reports (logo, grey title band with the red bar), then the register on landscape pages with a footer."""
        from PySide6.QtCore import QMarginsF, QRectF, QSizeF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument
        M = sys.modules[type(self.host).__module__]
        if not hasattr(M, "_pack_pages"):
            return self._write_plain(path)
        lg = self.logos()
        if "mcp_logo" in lg:
            lg["logo"] = lg.pop("mcp_logo")
        w = QPdfWriter(path)
        mk = lambda o: QPageLayout(QPageSize(QPageSize.PageSizeId.A4), o, QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
        w.setPageLayout(mk(QPageLayout.Orientation.Portrait))
        w.setResolution(96)
        w.setTitle("Drawing register")
        pwp, php = float(w.width()), float(w.height())

        def mkdoc(html_, pw):
            d_ = QTextDocument()
            for nm, im in lg.items():
                d_.addResource(QTextDocument.ResourceType.ImageResource, QUrl(nm), im)
            d_.setDefaultFont(QFont("Arial", 9))
            d_.setHtml('<html><body style="font-family:Arial; color:#111111;">' + html_ + "</body></html>")
            d_.setPageSize(QSizeF(pw, 1e7))
            return d_
        # the client logo is stored under the name used in the html
        painter = QPainter(w)
        painter.save()
        M._draw_doc_rounded(painter, mkdoc(self.cover_html(), pwp))
        painter.restore()
        w.setPageLayout(mk(QPageLayout.Orientation.Landscape))
        w.newPage()
        pw, ph = float(w.width()), float(w.height())
        body = self.report_parts()
        pages = M._pack_pages(lambda h: mkdoc(h, pw), body, ph - 30.0)
        company = (getattr(self.host, "rd", {}) or {}).get("company") or "MCP Architecture & Interiors"
        for i, (html_, y0, y1) in enumerate(pages):
            if i:
                w.newPage()
            painter.save()
            painter.translate(0, -y0)
            if y1 is not None:
                painter.setClipRect(QRectF(-5, y0, pw + 10, y1 - y0 + 1))
            M._draw_doc_rounded(painter, mkdoc(html_, pw))
            painter.restore()
            painter.save()
            painter.setPen(QColor("#9A9A9A"))
            painter.setFont(QFont("Arial", 7))
            painter.drawLine(0, int(ph - 24), int(pw), int(ph - 24))
            painter.drawText(QRectF(0, ph - 22, pw * 0.8, 16), int(Qt.AlignmentFlag.AlignLeft),
                             "%s  |  Drawing Register  |  %s  |  Revision %s" % (company, self.project_name(), self.info["issue_no"] or "0"))
            painter.drawText(QRectF(0, ph - 22, pw, 16), int(Qt.AlignmentFlag.AlignRight), "Page %d of %d" % (i + 2, len(pages) + 1))
            painter.restore()
        painter.end()

    def _write_plain(self, path):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
        w = QPdfWriter(path)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
        d = QTextDocument()
        d.setDefaultFont(QFont("Arial", 9))
        d.setHtml('<html><body style="font-family:Arial;color:#111;">' + self.cover_html() + self.report_html() + "</body></html>")
        d.print_(w)

    def preview_pdf(self):
        try:
            self.host.preview_pdf_report(self.write_pdf, lambda: None)
        except Exception as e:
            QMessageBox.warning(self, "Drawing register", "The preview could not be shown (%s). Use Export PDF." % e)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export drawing register", "Drawing register.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.write_pdf(path)
            QMessageBox.information(self, "Drawing register", "PDF saved:\n" + path)

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export drawing register", "Drawing register.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Group", "Drawing no.", "Title", "What it shows", "Size", "Scale", "Rev", "Rev date", "PDF date", "Requested by", "What changed", "Change since last issue", "Status", "File"])
            for name, rows in self.groups_in_issue():
                for r in rows:
                    w.writerow([name] + [r.get(k, "") for k in ("no", "title", "about", "size", "scale", "rev", "rdate", "pdfdate", "by", "comment")] +
                               [self.change_of(r)[1], r.get("status", ""), r.get("file", "")])
