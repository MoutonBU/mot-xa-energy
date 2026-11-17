"""The designed (HTML) version of the register email: dark cards, MCP red and black, logo banner.
The plain text in the email box stays the one thing the person edits; this turns that text into the designed email.
Email programs only understand old-style HTML, so everything is tables with inline styles."""
import html
import re

RED = "#E4203A"
BG = "#0E0F12"
CARD = "#23262D"
CARD2 = "#1A1C21"
LINE = "#383C45"
TXT = "#D7D9DE"
MUTED = "#8E929B"
FONT = "'Segoe UI',Helvetica,Arial,sans-serif"

DRAWING = re.compile(r"^(\S+)\s{2,}(.*?)\s{2,}Rev (\S+)\s+\(([^)]*)\):?\s*(.*)$")


def _e(t):
    return html.escape(t or "", quote=True)


def _rule(width, height, align="left", gap="10px 0 18px 0"):
    """A thin coloured line made of a table cell (works in email programs and in the program's own preview)."""
    return ('<table cellpadding="0" cellspacing="0" border="0" width="%d" align="%s" style="margin:%s;"><tr>'
            '<td width="%d" height="%d" bgcolor="%s" style="background-color:%s;height:%dpx;font-size:1px;line-height:%dpx;">&nbsp;</td></tr></table>'
            % (width, align, gap, width, height, RED, RED, height, height))


def _caps(line):
    core = re.sub(r"\(.*?\)", "", line).strip()
    return len(core) >= 4 and not re.search(r"[a-z]", core) and bool(re.search(r"[A-Z]", core)) and not line.startswith(" ")


def parse(body):
    """Text -> blocks: greet, p, h (section), sub (group), items, status, sig."""
    lines = body.replace("\r", "").split("\n")
    blocks, para, items = [], [], []

    def flush():
        nonlocal para, items
        if para:
            blocks.append(("p", "\n".join(para)))
            para = []
        if items:
            blocks.append(("items", items))
            items = []

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        i += 1
        if not s:
            flush()
            continue
        if re.match(r"^(kind )?regards,?$", s, re.I) or re.match(r"^(yours|sincerely)", s, re.I):
            flush()
            sig = [x.strip() for x in lines[i:] if x.strip()]
            blocks.append(("sig", sig))
            return blocks
        if re.match(r"^\s+[-•]\s", raw):
            if para:
                flush()
            items.append(re.sub(r"^\s+[-•]\s+", "", raw).rstrip())
            continue
        flush()
        if not blocks and re.match(r"^(hi|hello|dear)\b", s, re.I):
            blocks.append(("greet", s))
        elif s.lower().startswith("status of this revision"):
            blocks.append(("status", s))
        elif _caps(s) and len(s) < 90:
            kind = "sub" if (blocks and blocks[-1][0] in ("h", "sub")) or re.search(r"\(\d+ drawings?\)", s) else "h"
            blocks.append((kind, s))
        else:
            para.append(s)
    flush()
    return blocks


def _heading(kind, text):
    if kind == "h":
        return ('<tr><td align="center" style="padding:30px 0 12px 0;font-family:%s;font-size:12px;letter-spacing:4px;color:%s;font-weight:600;">%s</td></tr>'
                % (FONT, RED, _e(text)))
    return ('<tr><td style="padding:14px 4px 8px 4px;font-family:%s;font-size:13px;letter-spacing:1.5px;color:#FFFFFF;font-weight:600;">%s</td></tr>' % (FONT, _e(text)))


def _drawing_table(rows):
    head = "".join('<td width="%s" style="padding:10px 12px;font-family:%s;font-size:11px;letter-spacing:1.5px;color:%s;border-bottom:1px solid %s;">%s</td>' % (w, FONT, MUTED, LINE, _e(t))
                   for w, t in (("14%", "DRAWING"), ("30%", "TITLE"), ("8%", "REV"), ("18%", "SIZE / SCALE"), ("30%", "SHOWS")))
    body = ""
    for n, (no, title, rev, size, about) in enumerate(rows):
        bg = CARD2 if n % 2 == 0 else "#202329"
        cell = 'style="padding:10px 12px;font-family:%s;font-size:13px;color:%s;background-color:%s;" bgcolor="%s"' % (FONT, TXT, bg, bg)
        body += ('<tr><td %s><b style="color:#FFFFFF;">%s</b></td><td %s>%s</td>'
                 '<td %s><span style="background-color:%s;color:#FFFFFF;border-radius:10px;padding:2px 8px;font-size:12px;" bgcolor="%s">%s</span></td>'
                 '<td %s>%s</td><td %s>%s</td></tr>') % (cell, _e(no), cell, _e(title), cell, RED, RED, _e(rev), cell, _e(size), cell, _e(about))
    return ('<table width="100%%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid %s;border-radius:14px;border-collapse:separate;overflow:hidden;table-layout:fixed;">'
            '<tr>%s</tr>%s</table>' % (LINE, head, body))


def _list(items):
    out = ""
    for it in items:
        tags = re.findall(r"\[([^\]]+)\]", it)
        main = re.sub(r"\s*\[[^\]]+\]", "", it).strip()
        if ": " in main and len(main.split(": ", 1)[0]) < 70:
            lead, rest = main.split(": ", 1)
            main_html = '<b style="color:#FFFFFF;">%s</b><br><span style="color:%s;">%s</span>' % (_e(lead), TXT, _e(rest))
        else:
            main_html = '<span style="color:%s;">%s</span>' % (TXT, _e(main))
        tag_html = "".join('<br><span style="color:%s;font-size:12px;">%s</span>' % (MUTED, _e(t)) for t in tags)
        out += ('<tr><td width="4" bgcolor="%s" style="background-color:%s;font-size:0;line-height:0;">&nbsp;</td>'
                '<td style="padding:10px 14px;font-family:%s;font-size:14px;line-height:21px;background-color:%s;" bgcolor="%s">%s%s</td></tr>'
                '<tr><td colspan="2" height="6" style="font-size:0;line-height:0;">&nbsp;</td></tr>') % (RED, RED, FONT, CARD2, CARD2, main_html, tag_html)
    return '<table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table>' % out


def _title_parts(subject):
    m = re.match(r"^(.*?)\s+-\s+revision\s+(\S+)\s*(?:\((.*)\))?\s*$", subject or "", re.I)
    if m:
        return m.group(1).strip(), "REVISION %s%s" % (m.group(2), ("  ·  " + m.group(3).upper()) if m.group(3) else "")
    return (subject or "Drawing register").strip(), "DRAWING REGISTER"


def build(subject, body, logo_src="cid:mcplogo", attached="", company="MCP Architecture & Interiors"):
    title, strip = _title_parts(subject)
    blocks = parse(body)
    greet = next((b[1] for b in blocks if b[0] == "greet"), "")
    rows = []
    for kind, val in blocks:
        if kind == "greet":
            continue
        if kind == "p":
            rows.append('<tr><td style="padding:0 0 14px 0;font-family:%s;font-size:15px;line-height:24px;color:%s;">%s</td></tr>' % (FONT, TXT, _e(val).replace("\n", "<br>")))
        elif kind in ("h", "sub"):
            rows.append(("H", kind, val))
        elif kind == "items":
            parsed = [DRAWING.match(x) for x in val]
            if all(parsed):
                rows.append(("T", [m.groups() for m in parsed]))
            else:
                rows.append(("L", val))
        elif kind == "status":
            txt = val.split(":", 1)[-1].strip().rstrip(".")
            rows.append(("S", txt))
        elif kind == "sig":
            rows.append(("G", val))

    # the first card holds the greeting, the heading and the introduction paragraphs; sections and the signature follow
    intro, rest, seen_section = "", [], False
    for r in rows:
        if not seen_section and isinstance(r, str):
            intro += r
        else:
            seen_section = True
            rest.append(r)

    sections = ""
    for r in rest:
        if isinstance(r, str):
            sections += ('<tr><td style="padding:14px 6px 0 6px;font-family:%s;font-size:15px;line-height:24px;color:%s;">%s</td></tr>' % (FONT, TXT, r.split(">", 2)[-1].rsplit("</td>", 1)[0]))
        elif r[0] == "H":
            sections += _heading(r[1], r[2])
        elif r[0] == "T":
            sections += '<tr><td style="padding:0 0 8px 0;">%s</td></tr>' % _drawing_table(r[1])
        elif r[0] == "L":
            sections += '<tr><td style="padding:0 0 8px 0;">%s</td></tr>' % _list(r[1])
        elif r[0] == "S":
            sections += ('<tr><td align="center" style="padding:20px 0 6px 0;font-family:%s;font-size:12px;letter-spacing:3px;color:%s;">STATUS OF THIS REVISION</td></tr>'
                         '<tr><td align="center" style="padding:0 0 10px 0;"><span style="font-family:%s;font-size:16px;font-weight:600;color:#FFFFFF;background-color:%s;border-radius:18px;padding:7px 22px;" bgcolor="%s">%s</span></td></tr>'
                         % (FONT, MUTED, FONT, RED, RED, _e(r[1])))
        elif r[0] == "G":
            sig = r[1]
            name = sig[0] if sig else ""
            role = sig[1] if len(sig) > 1 else ""
            more = "".join('<br><span style="color:%s;">%s</span>' % (MUTED, _e(x)) for x in sig[2:])
            sections += ('<tr><td style="padding:26px 0 0 0;"><table width="100%%" cellpadding="0" cellspacing="0" border="0" style="background-color:%s;border:1px solid %s;border-radius:18px;" bgcolor="%s"><tr>'
                         '<td width="5" bgcolor="%s" style="background-color:%s;border-radius:18px 0 0 18px;font-size:0;">&nbsp;</td>'
                         '<td style="padding:18px 22px;font-family:%s;font-size:14px;line-height:22px;color:%s;">'
                         '<span style="color:%s;font-size:12px;letter-spacing:3px;">REGARDS</span><br><b style="font-size:17px;color:#FFFFFF;">%s</b><br>%s%s</td></tr></table></td></tr>'
                         % (CARD, LINE, CARD, RED, RED, FONT, TXT, RED, _e(name), _e(role), more))

    attached_html = ('<tr><td align="center" style="padding:18px 10px 0 10px;font-family:%s;font-size:12px;color:%s;">%s</td></tr>' % (FONT, MUTED, _e(attached))) if attached else ""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="dark"><title>%(title)s</title></head>'
            '<body style="margin:0;padding:0;background-color:%(bg)s;" bgcolor="%(bg)s">'
            '<table width="100%%" cellpadding="0" cellspacing="0" border="0" bgcolor="%(bg)s" style="background-color:%(bg)s;"><tr><td align="center" style="padding:22px 12px;">'
            '<table width="640" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:640px;">'
            # banner
            '<tr><td style="border-radius:20px;border:1px solid %(line)s;background-color:#0B0C0F;background-image:linear-gradient(135deg,#2A0A12 0%%,#0B0C0F 55%%,#1F0710 100%%);" bgcolor="#0B0C0F" align="center">'
            '<table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="padding:34px 26px;">'
            '<table cellpadding="0" cellspacing="0" border="0" style="border:2px solid #9A9DA6;border-radius:30px;background-color:#16181D;" bgcolor="#16181D"><tr><td align="center" style="padding:30px 46px 26px 46px;">'
            '<img src="%(logo)s" width="86" alt="MCP" style="display:block;margin:0 auto 14px auto;border:0;">'
            '<div style="font-family:%(font)s;font-size:38px;letter-spacing:10px;color:#FFFFFF;font-weight:300;padding-left:10px;">MCP</div>'
            '%(rule1)s'
            '<div style="font-family:%(font)s;font-size:11px;letter-spacing:4px;color:#C9CCD3;">ARCHITECTURE &amp; INTERIORS</div>'
            '<div style="font-family:%(font)s;font-size:10px;letter-spacing:3px;color:%(muted)s;padding-top:10px;">%(strip)s</div>'
            '</td></tr></table></td></tr></table></td></tr>'
            '<tr><td height="18" style="font-size:0;line-height:0;">&nbsp;</td></tr>'
            # intro card
            '<tr><td style="background-color:%(card)s;border:1px solid %(line)s;border-radius:24px;" bgcolor="%(card)s">'
            '<table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr><td style="padding:30px 34px 18px 34px;">'
            '<div style="font-family:%(font)s;font-size:15px;color:%(muted)s;padding-bottom:10px;">%(greet)s</div>'
            '<div style="font-family:%(font)s;font-size:28px;line-height:34px;font-weight:700;color:#FFFFFF;padding-bottom:6px;">%(title)s</div>'
            '%(rule2)s'
            '<table width="100%%" cellpadding="0" cellspacing="0" border="0">%(intro)s</table>'
            '</td></tr></table></td></tr>'
            '%(sections_wrap)s'
            '%(attached)s'
            '<tr><td align="center" style="padding:22px 0 4px 0;font-family:%(font)s;font-size:11px;letter-spacing:3px;color:%(muted)s;">%(company)s</td></tr>'
            '</table></td></tr></table></body></html>') % {
        "title": _e(title), "bg": BG, "line": LINE, "logo": logo_src, "font": FONT, "red": RED, "muted": MUTED, "strip": _e(strip), "card": CARD,
        "rule1": _rule(70, 2, "center", "12px auto 12px auto"), "rule2": _rule(46, 3, "left", "10px 0 18px 0"), "greet": _e(greet), "intro": intro, "attached": attached_html, "company": _e(company.upper()),
        "sections_wrap": ('<tr><td><table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table></td></tr>' % sections) if sections else ""}
