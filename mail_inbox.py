"""Watching the Gmail inbox for client orders: finds new emails by subject, saves each as an .eml and splits it into one order per house."""
import base64
import email
import email.policy
import html as _html
import os
import re
import time

HOUSE = re.compile(r"(?P<head>\b(?:stand|erf|house|unit|plot|block|site|lot)\b\s*(?:no\.?|number|#|:)?\s*[-:]?\s*(?P<id>[A-Za-z]?\d[\w+/\-]*))", re.I)
ORDER_NO = re.compile(r"\b(?:order|po|purchase order|ref|reference)\b\s*(?:no\.?|number|#|:)?\s*[-:]?\s*(?P<n>[A-Z]{0,4}[\-/]?\d[\w/\-]*)", re.I)
BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


class _Tables(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    """All tables of an HTML email as rows of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = []
        elif tag in ("br", "p", "div") and self._c is not None:
            self._c.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None and self._r is not None:
            self._r.append(re.sub(r"\s+", " ", "".join(self._c)).strip())
            self._c = None
        elif tag == "tr" and self._r is not None and self._t is not None:
            if any(self._r):
                self._t.append(self._r)
            self._r = None
        elif tag == "table" and self._t is not None:
            if self._t:
                self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


STAND_COL = re.compile(r"stand\s*(no|nr|number|#)|^(erf|house|unit|plot|lot)\b.*(no|nr|number|#)?|^(stand|erf|house|unit|plot|lot)$", re.I)


def orders_from_tables(html, houses=()):
    """One order per row of the table that has a stand / erf / house number column (a client's order list). [] when there is no such table."""
    p = _Tables()
    try:
        p.feed(html or "")
    except Exception:
        return []
    out = []
    for rows in p.tables:
        hi = next((i for i, r in enumerate(rows[:3]) if any(STAND_COL.search(c) for c in r)), None)
        if hi is None:
            continue
        head = rows[hi]
        ci = next(i for i, c in enumerate(head) if STAND_COL.search(c))
        kind = re.match(r"(stand|erf|house|unit|plot|lot)", head[ci], re.I)
        word = (kind.group(1) if kind else "Stand").capitalize()
        for r in rows[hi + 1:]:
            if len(r) <= ci or not r[ci].strip() or not re.search(r"\d", r[ci]):
                continue
            num = r[ci].strip()
            group = next((h for h in houses if _norm(num) and _norm(h).endswith(_norm(num))), "%s %s" % (word, num))
            yes, no, facts = [], [], []
            for i, c in enumerate(r):
                if i == ci or not c.strip() or i >= len(head) or not head[i].strip():
                    continue
                h = re.sub(r"\s*\(list\)", "", head[i], flags=re.I).strip()
                if c.strip().upper() in ("YES", "NO", "Y", "N"):
                    (yes if c.strip().upper() in ("YES", "Y") else no).append(re.sub(r"\((\w+)\)", lambda m_: "(" + m_.group(1).upper() + ")", h.capitalize()) if h.isupper() else h)
                else:
                    facts.append("%s: %s" % (h, c.strip()))
            txt = "%s %s\n%s" % (word, num, "; ".join(facts))
            if yes or no:
                txt += "\nExtras: " + (", ".join(yes) if yes else "none")
            out.append({"group": group, "order": "", "text": txt.strip()})
    return out


def parse_orders(subject, body, houses=(), html=""):
    """Splits one email into orders: [{'group', 'order', 'text'}].
    A new order starts on every line that names a stand, erf, house, unit, plot, block or site (or one of your own house and block names).
    Lines that follow belong to it until the next such line. An email that names none is one order for the whole email."""
    houses = [h for h in houses if h]
    tab = orders_from_tables(html, houses)
    if tab:
        allno = ORDER_NO.search(str(subject))
        for o in tab:
            o["order"] = allno.group("n").strip(" .,;") if allno else ""
        return tab
    lines = [ln.rstrip() for ln in str(body or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if not ln.lstrip().startswith(">")]
    cut = next((i for i, ln in enumerate(lines) if re.match(r"\s*(--\s*$|On .+ wrote:|Sent from my|From:\s|(kind |best |warm )?regards\b|thanks\b|thank you\b|cheers\b)", ln, re.I)), len(lines))
    lines = [ln for ln in lines[:cut] if ln.strip()]

    def group_of(text):
        low = _norm(text)
        for h in sorted(houses, key=len, reverse=True):
            if _norm(h) and _norm(h) in low:
                return h
        m = HOUSE.search(text)
        return re.sub(r"\s+", " ", m.group("head")).strip().capitalize() if m else ""

    out, cur = [], None
    for ln in lines:
        g = group_of(ln)
        if g and (cur is None or g != cur["group"] or BULLET.match(ln)):
            cur = {"group": g, "order": "", "text": ln.strip()}
            out.append(cur)
        elif cur is not None:
            cur["text"] += "\n" + ln.strip()
    if not out:        # no house named in the body: one order for the whole email, the house from the subject if it names one
        out = [{"group": group_of(subject), "order": "", "text": "\n".join(lines).strip() or str(subject)}]
    allno = ORDER_NO.search(str(subject) + "\n" + "\n".join(lines))
    for o in out:
        m = ORDER_NO.search(o["text"])
        o["order"] = (m or allno).group("n").strip(" .,;") if (m or allno) else ""
        o["text"] = o["text"].strip()[:1500]
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


def read_eml(raw, path=""):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    h = msg.get_body(preferencelist=("html",))
    try:
        html = h.get_content() if h is not None else ""
    except Exception:
        html = ""
    return {"subject": str(msg.get("Subject", "")), "from": str(msg.get("From", "")), "date": str(msg.get("Date", "")),
            "body": _body_text(msg), "html": html, "path": path, "raw": raw}


def fetch_new(S, keywords, seen, folder, days=14, limit=25):
    """New emails matching the subject words, newest first: [{'id', 'subject', 'from', 'date', 'body', 'path'}]. Each is saved as an .eml in `folder`."""
    import mail_oauth as mo
    words = [w.strip() for w in re.split(r"[,;\n]", keywords or "") if w.strip()] or ["order", "orders"]
    q = "in:inbox newer_than:%dd subject:(%s)" % (days, " OR ".join('"%s"' % w if " " in w else w for w in words))
    lst = mo.gmail_get(S, "messages", {"q": q, "maxResults": limit})
    out = []
    os.makedirs(folder, exist_ok=True)
    for m in lst.get("messages", []) or []:
        if m["id"] in seen:
            continue
        full = mo.gmail_get(S, "messages/" + m["id"], {"format": "raw"})
        raw = base64.urlsafe_b64decode(full["raw"] + "=" * (-len(full["raw"]) % 4))
        rec = read_eml(raw)
        safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", rec["subject"])[:60].strip() or "email"
        path = os.path.join(folder, "%s %s.eml" % (time.strftime("%Y-%m-%d %H%M"), safe))
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, "%s %s (%d).eml" % (time.strftime("%Y-%m-%d %H%M"), safe, n))
        with open(path, "wb") as f:
            f.write(raw)
        rec.update({"id": m["id"], "path": path})
        rec.pop("raw", None)
        out.append(rec)
    return out
