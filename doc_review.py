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
MAX_TEXT = 22000          # characters of guideline text per request
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
    d = M._json_from(text)
    v = d.get(key, [])
    return v if isinstance(v, list) else []


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


def extract_rules(win, paths):
    """[{rule, kind, limit, unit, measure, source}] read from guideline PDFs."""
    M = main_mod(win)
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
            reply = M.ai_request(RULES_PROMPT.replace("%s", MEASURE_KEYS, 1).replace("%s", "(the guidelines are in the pictures)", 1), imgs, 4096)
            rs = _json_list(M, reply, "rules")
        else:
            rs = []
            for ch in chunks[:6]:
                rs += _json_list(M, M.ai_request(RULES_PROMPT.replace("%s", MEASURE_KEYS, 1).replace("%s", ch, 1), (), 4096), "rules")
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


def review_plans(win, rules, plan_paths):
    """{index in rules: {result, found, page, reason}} for the plans (pictures + text) against the rules."""
    M = main_mod(win)
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
        reply = M.ai_request(prompt, [b for _l, b in imgs], 4096)
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
