"""Watching the Gmail inbox for client orders: finds new emails by subject, saves each as an .eml and splits it into one order per house."""
import base64
import email
import email.policy
import html as _html
import os
import re
import time

HOUSE = re.compile(r"(?P<head>\b(?:stand|standplaas|erf|house|huis|unit|eenheid|plot|perseel|block|blok|site|lot)\b\s*(?:no\.?|number|#|:)?\s*[-:]?\s*(?P<id>[A-Za-z]?\d[\w+/\-]*))", re.I)
ORDER_NO = re.compile(r"\b(?:order|bestelling|opdrag|po|purchase order|ref|reference|verwysing)\b\s*(?:no\.?|number|#|:)?\s*[-:]?\s*(?P<n>[A-Z]{0,4}[\-/]?\d[\w/\-]*)", re.I)
BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")


URGENT = re.compile(r"\b(urgent(ly)?|asap|a\.s\.a\.p\.?|as soon as possible|immediately|top priority|high priority|priority|rush|emergency|dringend(e)?|dadelik(e)?|onmiddellik(e)?|spoedeisend(e)?|spoed|spoedig moontlik|so (gou|spoedig) (as )?moontlik|prioriteit|noodgeval|hoogs dringend)\b", re.I)


def is_urgent(subject, body):
    """True when the client says it is urgent in the subject or the top of the email (quoted older mail is ignored)."""
    top = "\n".join(ln for ln in str(body or "").split("\n")[:40] if not ln.lstrip().startswith(">"))
    return bool(URGENT.search(str(subject or "") + "\n" + top))


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def _tables(html):
    """All tables of an HTML email as rows of cell texts (plain text matching: no extra library is needed)."""
    def txt(x):
        x = re.sub(r"(?is)<(script|style).*?</\1>", "", x)
        x = re.sub(r"(?i)<br\s*/?>|</p>|</div>", " ", x)
        return re.sub(r"\s+", " ", _html.unescape(re.sub(r"(?s)<[^>]+>", "", x))).strip()
    out = []
    for tb in re.findall(r"(?is)<table\b.*?</table>", html or ""):
        rows = []
        for tr in re.findall(r"(?is)<tr\b.*?</tr>", tb):
            cells = [txt(c) for c in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", tr)]
            if any(cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


AREA_COL = re.compile(r"township|estate|development|complex|suburb|dorp|ontwikkeling|area\\b|project", re.I)
STAND_COL = re.compile(r"(stand|standplaas|erf)\s*(no|nr|number|nommer|#)|^(erf|house|huis|unit|eenheid|plot|perseel|lot)\b.*(no|nr|number|nommer|#)?|^(stand|standplaas|erf|house|huis|unit|eenheid|plot|perseel|lot)$", re.I)


def orders_from_tables(html, houses=()):
    """One order per row of the table that has a stand / erf / house number column (a client's order list). [] when there is no such table."""
    out = []
    for rows in _tables(html):
        hi = next((i for i, r in enumerate(rows[:3]) if any(STAND_COL.search(c) for c in r)), None)
        if hi is None:
            continue
        head = rows[hi]
        ci = next(i for i, c in enumerate(head) if STAND_COL.search(c))
        kind = re.match(r"(standplaas|stand|erf|house|huis|unit|eenheid|plot|perseel|lot)", head[ci], re.I)
        word = (kind.group(1) if kind else "Stand").capitalize()
        for r in rows[hi + 1:]:
            if len(r) <= ci or not r[ci].strip() or not re.search(r"\d", r[ci]):
                continue
            num = r[ci].strip()
            pcode = portion_code(num)
            group = _portion_house(pcode, houses) if pcode else next((h for h in houses if _norm(num) and _norm(h).endswith(_norm(num))), "%s %s" % (word, num))
            yes, no, facts, area = [], [], [], ""
            for i, c in enumerate(r):
                if i == ci or not c.strip() or i >= len(head) or not head[i].strip():
                    continue
                if AREA_COL.search(head[i]) and not area:
                    area = c.strip()                      # the Township column is the area
                    continue
                h = re.sub(r"\s*\(list\)", "", head[i], flags=re.I).strip()
                if c.strip().upper() in ("YES", "NO", "Y", "N"):
                    (yes if c.strip().upper() in ("YES", "Y") else no).append(re.sub(r"\((\w+)\)", lambda m_: "(" + m_.group(1).upper() + ")", h.capitalize()) if h.isupper() else h)
                else:
                    facts.append("%s: %s" % (h, c.strip()))
            out.append({"group": group, "order": "", "area": area, "extras": "; ".join(re.sub(r"(\w)\(", r"\1 (", y) for y in yes), "text": ("%s %s\n%s" % (word, num, "; ".join(facts))).strip()})
    return out


PORTION = re.compile(r"(?<![\w])(?:(?P<farm>[A-Za-z]{2,5}\s?\d{1,5})[\s\-_/|,:\u2013\u2014]+)?(?P<p>PTN|PT|PORTION|PORT)\s*\.?\s*(?P<n>\d{1,4})(?![\w])", re.I)


def portion_code(text):
    """'ARF670-PTN4' (farm/erf code + portion = the stand number), also 'arf 670 ptn 14' or just 'PTN35'. '' when the text has none."""
    m = PORTION.search(str(text))
    if not m:
        return ""
    farm = re.sub(r"\s+", "", m.group("farm") or "").upper()
    farm = re.sub(r"^(ERF|ERVEN)(?=\d)", "ARF", farm)         # Erf 670 and ARF670 are the same farm/erf
    ptn = "PTN%d" % int(m.group("n"))
    return farm + "-" + ptn if farm else ptn


_AREA_LEAD = {"new", "order", "orders", "urgent", "re", "fwd", "fw", "aw", "for", "stand", "please", "hi", "dear", "the", "from", "at", "in", "of", "to",
              "house", "houses", "change", "changes", "dringend", "bestelling", "final", "finals", "plan", "plans", "extras"}


_AREA_LEAD |= {"or", "fo", "fr", "orde", "ordr", "ordrs", "od", "ord", "bestellings", "nuwe", "a", "an", "and", "pls", "plz", "ptn"}


def _trim_lead(words):
    """Drops the filler in front of an area name: 'Or fo Urbika Erf 670' -> 'Urbika Erf 670' (order words, typos of them, short words)."""
    words = list(words)
    while len(words) > 1 and (words[0].lower().strip(".,:-") in _AREA_LEAD or (len(words[0]) <= 3 and words[0].isalpha() and words[0].lower() not in ("erf", "ext", "ptn"))
                              and not re.search(r"\d", " ".join(words[1:2]))):
        words.pop(0)
    return words


def pipe_area(subject):
    """'Urbika Erf 670 | PTN 38' (also 'Blue Hills Ext 120 | Stand 2037'): what stands before the | is the area. '' when the subject has no | or nothing usable before it."""
    t = re.sub(r"^\s*((re|fwd?|aw)\s*:\s*)+", "", str(subject), flags=re.I)
    if "|" not in t:
        return ""
    left = t.split("|", 1)[0]
    words = [w for w in re.split(r"\s+", left.strip()) if w]
    words = _trim_lead(words)
    a = " ".join(words).strip(" -,:")
    if not a or len(a) < 3:
        return ""
    return re.sub(r"\b(?:ARF|ERF)\s*(\d)", r"Erf \1", a, flags=re.I)


def portion_area(text):
    """The area a portion code sits in: 'Urbika ARF670-PTN38' and 'Urbika Erf 670 PTN 38' both give 'Urbika Erf 670'; 'Urbika PTN 38' gives 'Urbika';
    '' when nothing but the portion is written."""
    t = str(text)
    m = PORTION.search(t)
    if not m:
        return ""
    farm = re.sub(r"\s+", "", m.group("farm") or "")
    fm = re.match(r"([A-Za-z]+)(\d+)", farm)
    fdisp = ""
    if fm:
        fdisp = ("Erf" if fm.group(1).upper() in ("ARF", "ERF", "ERVEN", "RF") else ("Ext" if fm.group(1).upper() == "EXT" else ("Phase" if fm.group(1).upper() in ("PHASE", "FASE") else fm.group(1).upper()))) + " " + fm.group(2)
    words = re.findall(r"[A-Za-z][\w'\u2019-]*", re.sub(r"^\s*((re|fwd?|aw)\s*:\s*)+", "", t[:m.start()], flags=re.I))
    name = []
    for w in reversed(words):
        if w.lower() in _AREA_LEAD or len(name) >= 3:
            break
        name.insert(0, w)
    return " ".join(_trim_lead(name) + ([fdisp] if fdisp else [])).strip()


def _portion_house(code, houses):
    """The house for a portion code: just the stand number, 'PTN 38' (the farm/erf part is the area, not part of the house name).
    An existing house with the same portion number is reused."""
    ptn = code.split("-")[-1]
    for h in houses:
        pc = portion_code(h)
        if pc and pc.split("-")[-1] == ptn:
            return h
    return "PTN " + re.sub(r"\D", "", ptn)


def _known_in(text, houses):
    """The houses whose number appears in the text on its own (2037 for Stand 2037), when no house word is used."""
    found = []
    for h in houses:
        mm = re.search(r"(\d{2,}[A-Za-z]?(?:[+/\-]\d+)?)\s*$", str(h))
        if mm and re.search(r"(?<![\w+/\-])%s(?![\w+/\-])" % re.escape(mm.group(1)), text, re.I) and h not in found:
            found.append(h)
    return found


def parse_orders(subject, body, houses=(), html=""):
    """Splits one email into orders: [{'group', 'order', 'text'}].
    A new order starts on every line that names a stand, erf, house, unit, plot, block or site (or one of your own house and block names).
    Lines that follow belong to it until the next such line. An email that names none is one order for the whole email."""
    houses = [h for h in houses if h]
    tab = orders_from_tables(html, houses)
    if tab:
        allno = ORDER_NO.search(str(subject))
        for o in tab:
            if not o.get("area") and portion_code(o.get("group", "")):
                o["area"] = portion_area(subject) or portion_area(o["group"])
            o["order"] = allno.group("n").strip(" .,;") if allno else ""
        return tab
    lines = [ln.rstrip() for ln in str(body or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if not ln.lstrip().startswith(">")]
    cut = next((i for i, ln in enumerate(lines) if re.match(r"\s*(--\s*$|On .+ wrote:|Op .+ geskryf:|Sent from my|From:\s|Van:\s|(kind |best |warm )?regards\b|groete\b|vriendelike groete\b|dankie\b|thanks\b|thank you\b|cheers\b)", ln, re.I)), len(lines))
    lines = [ln for ln in lines[:cut] if ln.strip()]

    def group_of(text):
        pc = portion_code(text)
        if pc:
            return _portion_house(pc, houses)
        low = _norm(text)
        for h in sorted(houses, key=len, reverse=True):
            if _norm(h) and _norm(h) in low:
                return h
        m = HOUSE.search(text)
        if m:
            num = _norm(m.group("id"))
            for h in houses:                      # "Standplaas 2037" in the email is "Stand 2037" in your register
                if num and re.search(r"\d", num) and _norm(h).endswith(num):
                    return h
        return re.sub(r"\s+", " ", m.group("head")).strip().capitalize() if m else ""

    num_lines = [i for i, ln in enumerate(lines) if re.fullmatch(r"\s*(?:(?:stand|erf|house|unit|plot|lot)\s*(?:no\.?|#)?\s*)?(\d{2,6}[A-Za-z]?)\s*[:\-]?\s*", ln, re.I)]
    if num_lines and not any(HOUSE.search(ln) and not re.fullmatch(r"\s*(?:stand|erf|house|unit|plot|lot)\s*(?:no\.?|#)?\s*\d+\s*", ln, re.I) for ln in lines):
        # the format "3339 / 91m2 (4+2) Extras: ...": a line with only the stand number, then what is wanted on it
        intro = " ".join(ln.strip() for ln in lines[:num_lines[0]] if re.search(r"\b(please|following|finals?|finale|orders?|bestelling|plans?|planne|asseblief|volgende)\b", ln, re.I)).strip(" :")
        low = (intro + " " + str(subject)).lower()
        kinds = ", ".join(k for k, pat in (("Final plans", r"\b(finals?|finale)\b"), ("Masters", r"\bmasters?\b"), ("SDP", r"\bsdp\b")) if re.search(pat, low))
        out = []
        for j, i in enumerate(num_lines):
            end = num_lines[j + 1] if j + 1 < len(num_lines) else len(lines)
            num = re.search(r"\d{2,6}[A-Za-z]?", lines[i]).group(0)
            word = (re.match(r"\s*(stand|erf|house|unit|plot|lot)", lines[i], re.I) or re.match(r"(stand)", "stand")).group(1).capitalize()
            group = next((h for h in houses if _norm(h).endswith(_norm(num))), "%s %s" % (word, num))
            det, ex = [], []
            for x in lines[i + 1:end]:
                if not x.strip():
                    continue
                mm = re.search(r"\b(?:extras?|ekstra'?s?|ekstras)\s*:\s*(.*)$", x, re.I)
                if mm:
                    ex += [y.strip() for y in re.split(r"[;,]", mm.group(1)) if y.strip()]
                    x = x[:mm.start()].strip()
                if x:
                    det.append(x.strip())
            out.append({"group": group, "order": "", "kinds": kinds, "extras": "; ".join(ex), "text": ("%s %s%s\n%s" % (word, num, (" - " + intro) if intro else "", "\n".join(det))).strip()})
        allno = ORDER_NO.search(str(subject) + "\n" + intro)
        for o in out:
            o["order"] = allno.group("n").strip(" .,;") if allno else ""
        return out
    out, cur = [], None
    has_ptn = any(portion_code(ln) for ln in lines)
    hdr = ""
    for ln in lines:
        mh = re.fullmatch(r"\s*([A-Za-z][\w'\u2019 -]*?)\s+(?:erf|arf|erven)\s?(\d+)\s*[:\-]?\s*", ln, re.I) if has_ptn else None
        if mh:
            hdr = " ".join(_trim_lead(mh.group(1).split())) + " Erf " + mh.group(2)      # "Urbika Erf 670" on a line of its own heads the portions below it
            continue
        g = group_of(ln)
        if g and (cur is None or g != cur["group"] or BULLET.match(ln)):
            cur = {"group": g, "order": "", "text": ln.strip(), "hdr": hdr}
            out.append(cur)
        elif cur is not None:
            cur["text"] += "\n" + ln.strip()
    if not out:        # no house named in the body: one order for the whole email, the house from the subject if it names one
        txt_all = "\n".join(lines).strip() or str(subject)
        g0 = group_of(subject)
        if not g0:
            known = _known_in(str(subject) + "\n" + "\n".join(lines), houses)      # "2037 is urgent": a number that is one of your houses
            if known:
                out = [{"group": h, "order": "", "text": txt_all} for h in known]
        if not out:
            out = [{"group": g0, "order": "", "text": txt_all}]
    allno = ORDER_NO.search(str(subject) + "\n" + "\n".join(lines))
    sub_area = portion_area(subject)
    for o in out:
        if portion_code(o.get("group", "")) and not o.get("area"):
            a = portion_area(o["text"].split("\n")[0])
            if not re.search(r"\d", a) and (o.get("hdr") or sub_area):       # "Urbika PTN 38" in the body, the farm only in a heading line or the subject
                a = o.get("hdr") or sub_area
            elif not a:
                a = o.get("hdr") or sub_area
            if a:
                o["area"] = a
        m = ORDER_NO.search(o["text"])
        o["order"] = (m or allno).group("n").strip(" .,;") if (m or allno) else ""
        o["text"] = o["text"].strip()[:1500]
        o.pop("hdr", None)
    return out


def _body_text(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    txt = part.get_content()
    if part.get_content_type() == "text/html":
        txt = re.sub(r"(?is)<(script|style).*?</\1>", "", txt)
        txt = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", txt)
        txt = re.sub(r"(?s)<[^>]+>", " ", txt)
        txt = _html.unescape(txt)
        txt = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in txt.split("\n"))
    return txt


def _rows_html(rows):
    return "<table>" + "".join("<tr>" + "".join("<%s>%s</%s>" % ("th" if i == 0 else "td", _html.escape(str(c or "").strip()), "th" if i == 0 else "td") for c in r) + "</tr>"
                               for i, r in enumerate(rows) if any(str(c or "").strip() for c in r)) + "</table>"


def _xlsx_rows(data):
    """Rows of the first sheets of an .xlsx: openpyxl when it is there, otherwise read straight from the file (no extra library needed)."""
    import io
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:3]:
            out.append([[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)])
        return out
    except Exception:
        pass
    import zipfile
    from xml.etree import ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(io.BytesIO(data))
    sst = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            sst.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))

    def colno(ref):
        n = 0
        for ch in re.match(r"[A-Z]+", ref).group(0):
            n = n * 26 + ord(ch) - 64
        return n - 1
    out = []
    for nm in sorted(x for x in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", x))[:3]:
        rows = []
        for r in ET.fromstring(z.read(nm)).iter("{%s}row" % ns["m"]):
            cells = {}
            for c in r.findall("m:c", ns):
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = sst[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[colno(c.get("r", "A1"))] = val
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        out.append(rows)
    return out


def attachment_texts(msg):
    """Reads the attachments of an email that can hold an order sheet: PDF, Excel (.xlsx) and CSV. Returns (text, html, names): text lines for the order parser,
    the sheets as HTML tables (so a stand column becomes one order per row), and the file names."""
    texts, htmls, names = [], [], []
    try:
        parts = list(msg.iter_attachments())
    except Exception:
        return "", "", []
    for part in parts:
        try:
            name = part.get_filename() or ""
            ext = os.path.splitext(name)[1].lower()
            data = part.get_payload(decode=True) or b""
            if not data or len(data) > 12 * 1024 * 1024:
                continue
            if ext == ".pdf" or part.get_content_type() == "application/pdf":
                try:
                    import fitz
                except Exception:
                    import pymupdf as fitz
                doc = fitz.open(stream=data, filetype="pdf")
                tx = []
                for pg in list(doc)[:12]:
                    tx.append(pg.get_text())
                    try:
                        for t in pg.find_tables().tables:
                            htmls.append(_rows_html(t.extract()))
                    except Exception:
                        pass
                texts.append("\n".join(tx))
                names.append(name or "attachment.pdf")
            elif ext in (".xlsx", ".xlsm"):
                for rows in _xlsx_rows(data):
                    if rows:
                        htmls.append(_rows_html(rows))
                        texts.append("\n".join(" ".join(str(c) for c in r if str(c).strip()) for r in rows))
                names.append(name)
            elif ext in (".csv", ".txt", ".tsv"):
                import csv
                import io
                raw = data.decode("utf-8-sig", "replace")
                if ext == ".txt":
                    texts.append(raw)
                else:
                    rows = list(csv.reader(io.StringIO(raw), delimiter="\t" if ext == ".tsv" else (";" if raw.count(";") > raw.count(",") else ",")))
                    htmls.append(_rows_html(rows))
                    texts.append("\n".join(" ".join(r) for r in rows))
                names.append(name)
        except Exception:
            continue
    return "\n".join(texts)[:20000], "".join(htmls), names


def parse_email_orders(it, houses=()):
    """The orders of one email: from its text and tables, plus those of an attached order sheet (PDF, Excel, CSV). Houses found in both are listed once."""
    out = parse_orders(it["subject"], it["body"], houses, it.get("html", ""))
    if not (it.get("attach_text") or it.get("attach_html")):
        return out
    try:
        att = [o for o in parse_orders(it["subject"], it.get("attach_text", ""), houses, it.get("attach_html", "")) if o.get("group")]
    except Exception:
        att = []
    if not att:
        return out
    have = {_norm(o["group"]) for o in out if o.get("group")}
    merged = [o for o in out if o.get("group")] + [o for o in att if _norm(o["group"]) not in have]
    return merged or out


def read_eml(raw, path=""):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    h = msg.get_body(preferencelist=("html",))
    try:
        html = h.get_content() if h is not None else ""
    except Exception:
        html = ""
    at, ah, an = attachment_texts(msg)
    return {"subject": str(msg.get("Subject", "")), "from": str(msg.get("From", "")), "date": str(msg.get("Date", "")),
            "body": _body_text(msg), "html": html, "path": path, "raw": raw, "attach_text": at, "attach_html": ah, "attach_names": an}


ORDERISH = re.compile(r"\b(orders?|bestelling(s)?|stands?|erf|erwe|standplaas|changes?|wysigings?|extras?|urgent|dringend|ext(ension)?|uitbreiding|plans?|tekeninge|drawings?|revisions?|nominations?|braai|patio|ibr)\b", re.I)
STANDNO = re.compile(r"\b(stand|erf|standplaas|house|unit|plot|lot)\s*(no\.?|nr\.?|#)?\s*\d{2,6}\b|\bPTN\s?\d+\b", re.I)
ROBOT = re.compile(r"(no-?reply|donotreply|mailer-daemon|notifications?@|newsletter|marketing@|alerts?@)", re.I)


def sender_addr(frm):
    from email.utils import parseaddr
    return parseaddr(str(frm))[1].strip().lower()


def looks_like_order(subject, body, html, sender, trusted=(), houses=()):
    """Senses whether an email is an order or a change from a client, without any typed words: a sender whose orders were accepted before, an order word in the
    subject, a stand/erf/house number anywhere in the top of the email, or an order table. Robots and newsletters are not."""
    addr = sender_addr(sender)
    if addr and addr in {t.lower() for t in trusted}:
        return True
    if ROBOT.search(addr):
        return False
    top = str(body or "")[:4000]
    if ORDERISH.search(str(subject)) or re.match(r"\s*(re:|fwd?:)?\s*[A-Za-z]{2,4}\s*\d{3,6}\b", str(subject), re.I) or STANDNO.search(str(subject) + "\n" + top):
        return True
    try:
        return any(o.get("group") for o in orders_from_tables(html, list(houses)))
    except Exception:
        return False


GREET = re.compile(r"^\s*(hi|hello|hey|dear|hallo|goeie\s*(dag|more|middag)|good\s*(day|morning|afternoon))\b[^\n]{0,30}$", re.I)
SIGNOFF = re.compile(r"^\s*(\*|--|(kind |best |warm )?regards\b|groete\b|vriendelike groete\b|dankie\b|thanks\b|thank you\b|cheers\b|sent from my|on .+ wrote:|op .+ geskryf:|from:\s|van:\s)", re.I)
CONTACT = re.compile(r"(@|https?://|www\.|\+?\d[\d ()-]{7,}\d|\*[CEW]\s*:)", re.I)


def clean_change_text(body, group=""):
    """The part of a follow-up email that says what the client wants changed: greeting, signature, quoted mail and a bare 'it is urgent' line are dropped."""
    lines = [ln.rstrip() for ln in str(body or "").replace("\r", "").split("\n")]
    keep = []
    for ln in lines:
        if ln.lstrip().startswith(">"):
            continue
        if SIGNOFF.match(ln) and keep:
            break
        if not ln.strip() or GREET.match(ln) or CONTACT.search(ln):
            continue
        keep.append(ln.strip())
    g = _norm(group)
    keep = [ln for ln in keep if not (g and _norm(ln) in (g, g + "isurgent", "urgent" + g))]
    rest = [ln for ln in keep if not (URGENT.search(ln) and len(ln) < 60 and not re.search(r"\bchange|wysig|add|remove|move|swap|replace|enlarge|reduce\b", ln, re.I))]
    return "\n".join(rest or ([] if all(URGENT.search(ln) for ln in keep) else keep)).strip()


_NOTCODE = {"re", "fw", "fwd", "aw", "erf", "stand", "unit", "lot", "plot", "new", "no", "ref", "the", "hi"}


def subject_code(subject):
    """The short area code a subject starts with: 'BH 2037' and 'BH nominations orders' give BH; 'Re: AD46 braai' gives AD. '' when there is none."""
    t = re.sub(r"^\s*((re|fwd?|aw)\s*:\s*)+", "", str(subject), flags=re.I)
    if re.match(r"\s*(?:[A-Za-z]{2,5}\s?\d{1,5}\s*[-_/ ]\s*)?(?:PTN|PORTION)\s*\.?\s*\d", t, re.I):
        return ""                                 # ARF670-PTN4 is a house, not an area code
    m = re.match(r"\s*([A-Za-z]{2,4})\s*[-_ ]?\s*\d{2,6}\b", t) or re.match(r"\s*([A-Z]{2,4})\b", t)
    code = m.group(1) if m else ""
    return "" if code.lower() in _NOTCODE else code.upper()


CHANGE_WORD = re.compile(r"\b(chang(e|es|ed|ing)|amend(s|ed|ing|ment|ments)?|revis(e|es|ed|ion|ions)|alter(s|ed|ation|ations)?|modif(y|ied|ication)|updat(e|es|ed)|mov(e|ed)|replac(e|ed)|swap(ped)?|instead|wysig(ing|ings|ings)?|verander(ing|ings)?|aanpassing(s)?|vervang|skuif|in plaas van)\b", re.I)


def split_changes(text):
    """Splits the lines of an order into (what is ordered, what is to be changed). The first line (the house) always stays with the order."""
    lines = [ln for ln in str(text or "").split("\n")]
    keep, chg = [], []
    for i, ln in enumerate(lines):
        if i > 0 and ln.strip() and CHANGE_WORD.search(ln):
            chg.append(ln.strip())
        else:
            keep.append(ln)
    return "\n".join(keep).strip(), "\n".join(chg).strip()


def save_eml(folder, rec):
    """Writes the email to the inbox folder (only done for emails that were taken in) and returns the path."""
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", rec["subject"])[:60].strip() or "email"
    path = os.path.join(folder, "%s %s.eml" % (time.strftime("%Y-%m-%d %H%M"), safe))
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, "%s %s (%d).eml" % (time.strftime("%Y-%m-%d %H%M"), safe, n))
    with open(path, "wb") as f:
        f.write(rec["raw"])
    return path


def fetch_new(S, keywords, seen, folder, days=14, limit=40, stubs=False, senders=(), by_subject=True):
    """The newest inbox emails whose SUBJECT has one of the words (order words, area names, short codes) and that have not been looked at yet (your own mail left out): [{'id', 'subject', 'from', 'date', 'body', 'html', 'raw'}].
    Nothing is written to disk here; the caller decides which emails are orders. With stubs=True only the ids come back (the first look at the inbox)."""
    import mail_oauth as mo
    words = [w.strip() for w in re.split(r"[,;\n]", keywords or "") if w.strip()] or ["order", "orders"]
    frm = [x.strip() for x in senders if "@" in str(x)]
    cond = "subject:(%s)" % " OR ".join('"%s"' % w if " " in w else w for w in words)
    if frm and by_subject:
        cond = "(%s OR from:(%s))" % (cond, " OR ".join(frm))
    elif frm:
        cond = "from:(%s)" % " OR ".join(frm)                     # only the addresses you listed
    elif not by_subject:
        return []
    q = "in:inbox is:unread newer_than:%dd -from:me %s" % (days, cond)
    lst = mo.gmail_get(S, "messages", {"q": q, "maxResults": limit})
    out = []
    for m in lst.get("messages", []) or []:
        if m["id"] in seen:
            continue
        if stubs:
            out.append({"id": m["id"], "subject": "", "from": "", "date": "", "body": "", "html": "", "raw": b"", "path": ""})
            continue
        full = mo.gmail_get(S, "messages/" + m["id"], {"format": "raw"})
        raw = base64.urlsafe_b64decode(full["raw"] + "=" * (-len(full["raw"]) % 4))
        rec = read_eml(raw)
        rec["id"] = m["id"]
        out.append(rec)
    return out
