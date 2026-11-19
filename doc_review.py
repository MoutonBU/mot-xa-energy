"""Reading rules from a PDF and reviewing plans against them. Shared by the Guidelines review and the Council pack.
Uses the program's Online mode (the person's own API key): the documents are sent to the chosen AI provider only after he says yes."""
import base64
import json
import os
import re
import sys

from PySide6.QtCore import QEventLoop, Qt, QThread
from PySide6.QtWidgets import QMessageBox, QProgressDialog

MEASURE_KEYS = "cov (coverage %), far (floor area ratio), lines (building line encroachments), floor (floor area m2), light, vent, glaze"
MAX_TEXT = 12000          # characters of guideline text per request
MAX_IMG_SIDE = 2200
MAX_PLAN_PAGES = 14       # pages of plans sent per review


def main_mod(win):
    return sys.modules[type(win).__module__]


def pdf_pages_text(path):
    """[(page number, text)]"""
    import fitz
    out = []
    with fitz.open(path) as d:
        for i, p in enumerate(d):
            out.append((i + 1, p.get_text("text") or ""))
    return out


def pdf_page_images(path, pages=None, max_side=MAX_IMG_SIDE):
    """[(page number, base64 png)] for the given pages (all when None)."""
    import fitz
    out = []
    with fitz.open(path) as d:
        for i, p in enumerate(d):
            if pages is not None and (i + 1) not in pages:
                continue
            r = p.rect
            s = min(3.0, max_side / max(r.width, r.height, 1.0))
            pm = p.get_pixmap(matrix=fitz.Matrix(s, s), alpha=False)
            out.append((i + 1, base64.b64encode(pm.tobytes("png")).decode()))
    return out


def page_count(path):
    import fitz
    with fitz.open(path) as d:
        return d.page_count


class _T(QThread):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.res, self.err = fn, None, ""

    def run(self):
        try:
            self.res = self.fn()
        except Exception as e:
            self.err = str(e) or e.__class__.__name__


def run_busy(parent, text, fn):
    """Run fn on a thread behind a busy box; returns its result or raises RuntimeError."""
    dlg = QProgressDialog(text, None, 0, 0, parent)
    dlg.setWindowTitle("Working")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.show()
    th = _T(fn)
    loop = QEventLoop()
    th.finished.connect(loop.quit)
    th.start()
    loop.exec()
    dlg.close()
    if th.err:
        raise RuntimeError(th.err)
    return th.res


def confirm_send(parent, M, what, n_pages):
    """The documents leave the computer: say so and ask. False when he says no or Online mode is off."""
    if not M.online_ready():
        QMessageBox.information(parent, "Online mode", "Reading and reviewing PDFs uses the AI in Online mode. Switch Online mode on and "
                                "type your API key first (File > Online mode).")
        return False
    prov = M.SETTINGS.get("provider", "Claude (Anthropic)")
    r = QMessageBox.question(parent, "Send to the AI?", "%s\n\nThis sends about %d page(s) to %s with your API key. It costs a little "
                             "(a few cents per page, counted in the program's AI cost). Do not send drawings you are not allowed to share.\n\nContinue?"
                             % (what, n_pages, prov))
    return r == QMessageBox.StandardButton.Yes


def _json_list(M, text, key):
    """The list under `key`. When the reply is cut off or has a stray quote, every complete entry before the damage is still kept."""
    try:
        d = M._json_from(text)
        v = d.get(key, [])
        return v if isinstance(v, list) else []
    except Exception:
        pass
    t = re.sub(r"```(?:json)?", "", text or "")
    i = t.find("[", max(0, t.find('"%s"' % key)))
    dec, out, pos = json.JSONDecoder(), [], i + 1 if i >= 0 else 0
    while True:
        j = t.find("{", pos)
        if j < 0:
            break
        try:
            o, end = dec.raw_decode(t, j)
        except ValueError:
            nxt = t.find("{", j + 1)                       # skip the damaged entry, carry on with the next
            if nxt < 0:
                break
            pos = nxt
            continue
        if isinstance(o, dict):
            out.append(o)
        pos = end
    if not out:
        raise RuntimeError("The AI's answer could not be read. Try again, or use the offline reader.")
    return out


# ---- rules out of a guideline PDF
RULES_PROMPT = """Below is text from design guidelines, a zoning scheme or a council's requirements for building plan submissions \
(South Africa). Pull out every rule that a set of architectural plans could be checked against: limits (coverage, floor area ratio, height, \
building lines, parking, wall heights, materials, colours, roof pitch, fences) and things that must be shown or provided.

Return ONLY JSON: {"rules": [{"rule": "short name of the rule", "kind": "max" or "min" or "check", "limit": number or null, "unit": "%" or "m" or "m2" or "" , \
"measure": "", "source": "clause number or page"}]}

- kind "max" = must not be more than limit, "min" = must not be less than limit, "check" = a yes/no requirement with no number.
- Put the number in limit with its unit; for a "check" rule limit is null.
- measure: one of %s when the rule is exactly that figure, otherwise "".
- One entry per rule. Keep the wording short and clear. Do not invent rules that are not in the text.

TEXT:
%s"""


def extract_rules(win, paths, offline=False):
    """[{rule, kind, limit, unit, measure, source}] read from guideline PDFs."""
    M = main_mod(win)
    if offline:
        return offline_extract_rules(win, paths)
    out = []
    for path in paths:
        pages = pdf_pages_text(path)
        txt = "\n".join("[page %d]\n%s" % (n, t) for n, t in pages if t.strip())
        name = os.path.basename(path)
        chunks, cur = [], ""
        for n, t in pages:
            blk = "[page %d]\n%s\n" % (n, t)
            if len(cur) + len(blk) > MAX_TEXT and cur:
                chunks.append(cur)
                cur = ""
            cur += blk
        if cur.strip():
            chunks.append(cur)
        if len(txt) < 200:                                           # scanned: send the first pages as pictures
            imgs = [b for _n, b in pdf_page_images(path, set(range(1, 11)))]
            reply = M.ai_request(RULES_PROMPT.replace("%s", MEASURE_KEYS, 1).replace("%s", "(the guidelines are in the pictures)", 1), imgs, 8000)
            rs = _json_list(M, reply, "rules")
        else:
            rs = []
            for ch in chunks[:10]:
                rs += _json_list(M, M.ai_request(RULES_PROMPT.replace("%s", MEASURE_KEYS, 1).replace("%s", ch, 1), (), 8000), "rules")
        for r in rs:
            if not isinstance(r, dict) or not str(r.get("rule", "")).strip():
                continue
            kind = r.get("kind") if r.get("kind") in ("max", "min", "check") else "check"
            try:
                lim = float(r.get("limit")) if r.get("limit") is not None else 0.0
            except (TypeError, ValueError):
                lim, kind = 0.0, "check"
            meas = r.get("measure") if r.get("measure") in ("cov", "far", "lines", "floor", "light", "vent", "glaze") else ""
            out.append({"rule": str(r["rule"]).strip(), "kind": kind, "limit": lim, "unit": str(r.get("unit") or "").strip(),
                        "measure": meas, "source": "%s %s" % (name, str(r.get("source") or "").strip()), "file": name})
    return out


# ---- plans against rules
REVIEW_PROMPT = """You are checking building plans (pictures of the drawing sheets, with the text of each sheet) against a list of rules. \
The pictures are labelled with their file and page.

For every rule decide: "pass" (the plans clearly comply), "fail" (the plans clearly do not comply, or a required item is missing from \
the sheets), or "unclear" (you cannot tell from these sheets). Do not guess: use "unclear" when you cannot read a value. When a rule has a limit, \
read the matching figure from the plans (a dimension, a note, a table) and give it.

Return ONLY JSON: {"results": [{"n": 1, "result": "pass" or "fail" or "unclear", "found": "what the plans show, with the number", \
"page": "file and page where you saw it", "reason": "one short sentence"}]}

RULES:
%s"""


def _rule_line(i, r):
    k = r.get("kind")
    if k == "check":
        return "%d. %s (a requirement: is it shown or provided?)" % (i, r["rule"])
    return "%d. %s: %s %g%s" % (i, r["rule"], "not more than" if k == "max" else "not less than", float(r.get("limit") or 0),
                                (" " + r["unit"]) if r.get("unit") else "")


def review_plans(win, rules, plan_paths, offline=False):
    """{index in rules: {result, found, page, reason}} for the plans (pictures + text) against the rules."""
    M = main_mod(win)
    if offline:
        return offline_review(win, rules, plan_paths)
    imgs, texts = [], []
    for p in plan_paths:
        name = os.path.basename(p)
        n = page_count(p)
        pages = list(range(1, n + 1))[:max(1, MAX_PLAN_PAGES // max(1, len(plan_paths)))]
        for pg, b in pdf_page_images(p, set(pages)):
            imgs.append(("%s page %d" % (name, pg), b))
        for pg, t in pdf_pages_text(p):
            if pg in pages and t.strip():
                texts.append("[%s page %d] %s" % (name, pg, re.sub(r"\s+", " ", t)[:2500]))
    imgs = imgs[:MAX_PLAN_PAGES]
    out = {}
    for s in range(0, len(rules), 20):
        chunk = rules[s:s + 20]
        body = "\n".join(_rule_line(i + 1, r) for i, r in enumerate(chunk))
        prompt = REVIEW_PROMPT.replace("%s", body, 1)
        prompt += "\n\nSHEETS (order of the pictures): " + "; ".join(l for l, _b in imgs)
        if texts:
            prompt += "\n\nTEXT ON THE SHEETS:\n" + "\n".join(texts)[:30000]
        reply = M.ai_request(prompt, [b for _l, b in imgs], 8000)
        for r in _json_list(M, reply, "results"):
            try:
                i = int(r.get("n")) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(chunk):
                res = str(r.get("result", "unclear")).lower()
                out[s + i] = {"result": res if res in ("pass", "fail", "unclear") else "unclear", "found": str(r.get("found") or ""),
                              "page": str(r.get("page") or ""), "reason": str(r.get("reason") or "")}
    return out


def n_plan_pages(paths):
    n = 0
    for p in paths:
        try:
            n += min(page_count(p), max(1, MAX_PLAN_PAGES // max(1, len(paths))))
        except Exception:
            pass
    return min(n, MAX_PLAN_PAGES)


# ---------------------------------------------------------------- offline: no AI, no internet
def choose_mode(parent, M, what, n_pages):
    """'ai', 'offline' or None. Without Online mode the offline reader is used straight away."""
    if not M.online_ready():
        return "offline"
    box = QMessageBox(parent)
    box.setWindowTitle("How should it read the PDFs?")
    box.setText("%s\n\nOffline: the program reads the text in the PDFs on this computer. Nothing is sent anywhere. It is simpler and misses "
                "things that are only drawn, not written.\n\nWith the AI (Online mode): about %d page(s) are sent to %s with your API key. It "
                "reads drawings better and costs a few cents per page." % (what, n_pages, M.SETTINGS.get("provider", "Claude (Anthropic)")))
    off = box.addButton("Read offline", QMessageBox.ButtonRole.AcceptRole)
    ai = box.addButton("Use the AI", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return "offline" if box.clickedButton() is off else "ai" if box.clickedButton() is ai else None


_UNITS = r"(m\s?[2\u00b2]|sqm|m\u00b2|mm|m|%|percent|degrees?|\u00b0|deg|storeys?|stories|levels?|bays?|spaces?)"
_NUM = r"(\d+(?:[.,]\d+)?)"
_MAXW = r"(maximum|max\.?|not\s+(?:to\s+)?exceed|shall\s+not\s+exceed|no\s+more\s+than|not\s+(?:be\s+)?(?:more|higher|taller|greater|larger)\s+than|limited\s+to|up\s+to)"
_MINW = r"(minimum|min\.?|at\s+least|not\s+(?:be\s+)?(?:less|lower|smaller)\s+than|no\s+less\s+than)"
_STOP = set("the a an of to be is are shall must should and or for in on at by with from that this any all each than not no more less maximum minimum max min "
            "exceed least up limited height".split()) - {"height"}
_MEAS = [("cov", r"coverage"), ("far", r"floor\s+area\s+ratio|\bfar\b|bulk"), ("lines", r"building\s+line|set\s?back"),
         ("floor", r"(?:total\s+)?floor\s+area")]


def _unit(u):
    u = u.lower().replace(" ", "")
    if u in ("m2", "m\u00b2", "sqm"):
        return "m2"
    if u in ("percent", "%"):
        return "%"
    if u.startswith("deg") or u == "\u00b0":
        return "deg"
    return u


def _num(s):
    return float(s.replace(",", "."))


def _sentences(text):
    t = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    t = re.sub(r"\n(?=[a-z(])", " ", t)                 # a wrapped line continues the sentence
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z0-9(])|\n+", t)
    return [p.strip() for p in parts if 12 <= len(p.strip()) <= 400]


def offline_extract_rules(win, paths):
    out, seen = [], set()
    for path in paths:
        name = os.path.basename(path)
        pages = pdf_pages_text(path)
        if sum(len(t) for _n, t in pages) < 200:
            pages = _ocr_pages(win, path, 12)
        for pg, text in pages:
            for s in _sentences(text):
                low = s.lower()
                kind, lim, unit = None, 0.0, ""
                m = re.search(_MAXW + r"[^0-9]{0,40}?" + _NUM + r"\s?" + _UNITS + r"?", s, re.I) or \
                    re.search(_NUM + r"\s?" + _UNITS + r"\s+(?:maximum|max\.?)\b", s, re.I)
                if m:
                    g = m.groups()
                    nums = [x for x in g if x and re.fullmatch(r"\d+(?:[.,]\d+)?", x)]
                    uns = [x for x in g if x and not re.fullmatch(r"\d+(?:[.,]\d+)?", x) and re.fullmatch(_UNITS, x, re.I)]
                    if nums:
                        kind, lim, unit = "max", _num(nums[0]), _unit(uns[0]) if uns else ""
                if kind is None:
                    m = re.search(_MINW + r"[^0-9]{0,40}?" + _NUM + r"\s?" + _UNITS + r"?", s, re.I) or \
                        re.search(_NUM + r"\s?" + _UNITS + r"\s+(?:minimum|min\.?)\b", s, re.I)
                    if m:
                        g = m.groups()
                        nums = [x for x in g if x and re.fullmatch(r"\d+(?:[.,]\d+)?", x)]
                        uns = [x for x in g if x and not re.fullmatch(r"\d+(?:[.,]\d+)?", x) and re.fullmatch(_UNITS, x, re.I)]
                        if nums:
                            kind, lim, unit = "min", _num(nums[0]), _unit(uns[0]) if uns else ""
                if kind is None:
                    if re.search(r"\b(shall|must|is required|are required|to be (?:provided|submitted|shown|indicated)|should be (?:provided|submitted|shown))\b", low):
                        kind = "check"
                if kind is None:
                    continue
                rule = re.sub(r"^(?:\d+(?:\.\d+)*[.)]?|\(?[a-z]\))\s+", "", s).strip()
                rule = (rule[:110] + "...") if len(rule) > 113 else rule
                key = rule.lower()
                if key in seen:
                    continue
                seen.add(key)
                meas = ""
                for k, pat in _MEAS:
                    if re.search(pat, low):
                        meas = k
                        break
                if kind == "check" or meas == "":
                    pass
                out.append({"rule": rule, "kind": kind, "limit": lim, "unit": unit, "measure": meas if kind != "check" else "",
                            "source": "%s page %d" % (name, pg), "file": name})
    return out[:150]


def _ocr_pages(win, path, max_pages):
    """[(page, text)] by reading page pictures with the program's offline text reader (for scanned PDFs)."""
    from PySide6.QtGui import QImage
    M = main_mod(win)
    out = []
    for pg, b in pdf_page_images(path, set(range(1, max_pages + 1)), 2600):
        img = QImage.fromData(base64.b64decode(b))
        lines, _w, _h = M.ocr_lines(img)
        out.append((pg, "\n".join(t for *_c, t in sorted(lines, key=lambda l: (round(l[1] / 18), l[0])))))
    return out


def _kw(rule):
    words = re.findall(r"[a-z]{3,}", rule.lower())
    return [w for w in words if w not in _STOP][:6]


def _lines_with(pages, kws, need):
    """(page, line, next line) for lines that hold at least `need` of the keywords."""
    hits = []
    for pg, text in pages:
        ls = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
        for i, l in enumerate(ls):
            low = l.lower()
            if sum(1 for k in kws if k in low) >= need:
                hits.append((pg, l, ls[i + 1] if i + 1 < len(ls) else ""))
    return hits


def offline_review(win, rules, plan_paths):
    pages = []
    for p in plan_paths:
        name = os.path.basename(p)
        pp = pdf_pages_text(p)
        if sum(len(t) for _n, t in pp) < 100:
            try:
                pp = _ocr_pages(win, p, 6)
            except Exception:
                pp = []
        pages += [("%s page %d" % (name, n), t) for n, t in pp]
    out = {}
    for i, r in enumerate(rules):
        kws = _kw(r["rule"])
        if not kws:
            out[i] = {"result": "unclear", "found": "", "page": "", "reason": "Read offline: the rule has no words to look for."}
            continue
        if r.get("kind") == "check":
            need = max(1, (len(kws) + 1) // 2)
            hits = _lines_with(pages, kws, need)
            if not hits:                                   # the words may be on separate lines of one sheet
                for pg_, t_ in pages:
                    if sum(1 for k in kws if k in t_.lower()) >= need:
                        hits = [(pg_, "words found on this sheet", "")]
                        break
            if hits:
                pg, l, _n = hits[0]
                out[i] = {"result": "pass", "found": l[:80], "page": pg, "reason": "Read offline: the words of this item appear in the plans."}
            else:
                out[i] = {"result": "unclear", "found": "", "page": "",
                          "reason": "Read offline: nothing in the text of the plans matches (it may be drawn, not written)."}
            continue
        unit = _unit(r.get("unit") or "")
        lim = float(r.get("limit") or 0)
        best = None
        for need in (len(kws), max(1, (len(kws) + 1) // 2), 1):
            hits = _lines_with(pages, kws, need)
            vals = []
            for pg, l, nxt in hits:
                for txt in (l, l + " " + nxt):
                    for m in re.finditer(_NUM + r"\s?" + _UNITS + r"?", txt, re.I):
                        u = _unit(m.group(2)) if m.group(2) else ""
                        if unit and u and u != unit:
                            continue
                        if unit and not u and unit.rstrip("s") not in txt.lower():
                            continue
                        vals.append((_num(m.group(1)), pg, l))
                    if vals:
                        break
            if vals:
                best = vals
                break
        if not best:
            out[i] = {"result": "unclear", "found": "", "page": "", "reason": "Read offline: no matching figure with the unit found in the text of the plans."}
            continue
        v, pg, l = max(best, key=lambda x: x[0]) if r["kind"] == "max" else min(best, key=lambda x: x[0])
        ok = v <= lim + 1e-9 if r["kind"] == "max" else v >= lim - 1e-9
        out[i] = {"result": "pass" if ok else "fail", "found": "%g%s  (\"%s\")" % (v, (" " + unit) if unit else "", l[:60]), "page": pg,
                  "reason": "Read offline: figure picked from the text next to the matching words - check it is the right one."}
    return out
