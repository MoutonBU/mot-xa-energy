"""The designed (HTML) version of the register email: dark MCP look, logo on a rounded white tile above the company name,
a rounded title card with a red rounded bar, rounded cards, MCP red.
It is dark by default and carries a light version for mail programs that are in light mode; the logo sits on its own white tile so it reads in both.
The plain text in the email box stays the one thing the person edits; this turns that text into the designed email.
Email programs only understand old-style HTML, so everything is tables with inline styles plus a few dark-mode classes."""
import html
import re

RED = "#C8102E"
PAGE = "#FFFFFF"       # class pg
HEAD = "#DCDCDC"       # class hd   (the grey title card, as on the PDF)
CARD = "#F3F3F3"       # class cd
ROW1 = "#FFFFFF"       # class r1
ROW2 = "#F6F6F6"       # class r2
LINE = "#CFCFCF"       # class bd
TXT = "#2B2B2B"        # class tx
STRONG = "#111111"     # class st
MUTED = "#6B6B6B"      # class mu
FONT = "'Segoe UI',Helvetica,Arial,sans-serif"
BRAND = "MCP Architecture & Interiors"     # always the full name under the logo, whatever the signature company says

# The email is LIGHT by default (that is what Gmail and most programs show) and switches itself to dark in programs that are in dark mode
DARK_CSS = """
:root{color-scheme:light dark;supported-color-schemes:light dark;}
@media (prefers-color-scheme: dark){
 .pg{background-color:#0E0F12 !important;}
 .hd{background-color:#2A2D34 !important;border-color:#454953 !important;}
 .cd{background-color:#23262D !important;border-color:#383C45 !important;}
 .r1{background-color:#1A1C21 !important;}
 .r2{background-color:#202329 !important;}
 .bd{border-color:#383C45 !important;}
 .tx{color:#D7D9DE !important;}
 .st{color:#FFFFFF !important;}
 .mu{color:#9DA1AA !important;}
 .lgl{display:none !important;max-height:0 !important;}
 .lgd{display:block !important;max-height:none !important;overflow:visible !important;}
}
@media only screen and (max-width:480px){
 .sgd{display:none !important;max-height:0 !important;overflow:hidden !important;}
 .sgm{display:block !important;max-height:none !important;overflow:visible !important;}
}
[data-ogsc] .pg{background-color:#0E0F12 !important;} [data-ogsc] .hd{background-color:#2A2D34 !important;} [data-ogsc] .cd{background-color:#23262D !important;}
[data-ogsc] .r1{background-color:#1A1C21 !important;} [data-ogsc] .r2{background-color:#202329 !important;}
[data-ogsc] .tx{color:#D7D9DE !important;} [data-ogsc] .st{color:#FFFFFF !important;} [data-ogsc] .mu{color:#9DA1AA !important;}
"""

DRAWING = re.compile(r"^(\S+)\s{2,}(.*?)\s{2,}Rev (\S+)\s+\(([^)]*)\):?\s*(.*)$")


def _e(t):
    return html.escape(t or "", quote=True)


# ---- the program's own preview (Qt) cannot draw rounded corners, so there each card is built from little corner pictures ----
_pv = {"on": False, "res": {}}


def _corner(color, r, pos):
    name = "rc_%s_%d_%s.png" % (color.lstrip("#"), r, pos)
    _pv["res"][name] = (color, r, pos)
    return '<img src="%s" width="%d" height="%d" style="vertical-align:top;">' % (name, r, r)


def preview_resources():
    """[(name, png bytes)] for the corner pictures the last preview build used."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter
    out = []
    k = 3
    for name, (color, r, pos) in _pv["res"].items():
        im = QImage(r * k, r * k, QImage.Format.Format_ARGB32)
        im.fill(QColor(0, 0, 0, 0))
        p = QPainter(im)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(0, 0, 0, 0))
        p.setBrush(QColor(color))
        ox = 0 if pos[1] == "l" else -r * k
        oy = 0 if pos[0] == "t" else -r * k
        p.drawEllipse(ox, oy, 2 * r * k, 2 * r * k)
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        im.save(buf, "PNG")
        out.append((name, bytes(buf.data())))
    return out


def _wrap(inner, bg, r=12, accent=None, width="100%", tight=False):
    """A rounded card for the preview only: top and bottom rows with rounded corner pictures around the content."""
    a = accent or bg
    w = ('width="%s" ' % width) if width else ""
    return ('<table %scellspacing="0" cellpadding="0" border="0">'
            '<tr><td width="%d" height="%d" style="font-size:1px;line-height:1px;">%s</td><td bgcolor="%s" style="font-size:1px;line-height:1px;"></td><td width="%d" style="font-size:1px;line-height:1px;">%s</td></tr>'
            '<tr><td width="%d" bgcolor="%s"></td><td bgcolor="%s" %s>%s</td><td width="%d" bgcolor="%s"></td></tr>'
            '<tr><td width="%d" height="%d" style="font-size:1px;line-height:1px;">%s</td><td bgcolor="%s" style="font-size:1px;line-height:1px;"></td><td width="%d" style="font-size:1px;line-height:1px;">%s</td></tr></table>'
            % (w, r, r, _corner(a, r, "tl"), bg, r, _corner(bg, r, "tr"),
               r, a, bg, ('style="font-size:1px;line-height:1px;"' if tight else ""), inner, r, bg,
               r, r, _corner(a, r, "bl"), bg, r, _corner(bg, r, "br")))


def _bar(width, height, align="left", gap="10px 0 18px 0", radius=None):
    """A red rounded bar made of a table cell (works in email programs and in the program's own preview)."""
    r = height // 2 if radius is None else radius
    if _pv["on"]:
        return _wrap("", RED, r, width="100%", tight=True)
    w = ('width="%d" ' % width) if isinstance(width, int) else 'width="100%"'
    return ('<table cellpadding="0" cellspacing="0" border="0" %s align="%s" style="margin:%s;"><tr>'
            '<td height="%d" bgcolor="%s" style="background-color:%s;height:%dpx;border-radius:%dpx;font-size:1px;line-height:%dpx;">&nbsp;</td></tr></table>'
            % (w, align, gap, height, RED, RED, height, r, height))


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
            kind = "sub" if (blocks and blocks[-1][0] in ("h", "sub")) or re.search(r"\(\d+ drawings?\)", s) or re.match(r"^[A-Z]?[\d-]+\s{2,}", s) else "h"
            blocks.append((kind, s))
        else:
            para.append(s)
    flush()
    return blocks


def _heading(kind, text):
    if kind == "h":
        return ('<tr><td align="center" style="padding:28px 0 12px 0;font-family:%s;font-size:12px;letter-spacing:4px;color:%s;font-weight:700;">%s</td></tr>'
                % (FONT, RED, _e(text)))
    return ('<tr><td class="st" style="padding:14px 4px 8px 4px;font-family:%s;font-size:13px;letter-spacing:1.5px;color:%s;font-weight:700;">%s</td></tr>' % (FONT, STRONG, _e(text)))


def _drawing_table(rows):
    head = "".join('<td class="mu bd" width="%s" style="padding:10px 12px;font-family:%s;font-size:11px;letter-spacing:1.5px;color:%s;border-bottom:1px solid %s;">%s</td>' % (w, FONT, MUTED, LINE, _e(t))
                   for w, t in (("14%", "DRAWING"), ("30%", "TITLE"), ("8%", "REV"), ("18%", "SIZE / SCALE"), ("30%", "SHOWS")))
    body = ""
    for n, (no, title, rev, size, about) in enumerate(rows):
        cls, bg = ("r1", ROW1) if n % 2 == 0 else ("r2", ROW2)
        cell = 'class="%s tx" style="padding:10px 12px;font-family:%s;font-size:13px;color:%s;background-color:%s;" bgcolor="%s"' % (cls, FONT, TXT, bg, bg)
        body += ('<tr><td %s><b class="st" style="color:%s;">%s</b></td><td %s>%s</td>'
                 '<td %s><span style="background-color:%s;color:#FFFFFF;border-radius:10px;padding:2px 8px;font-size:12px;font-weight:700;" bgcolor="%s">%s</span></td>'
                 '<td %s>%s</td><td %s>%s</td></tr>') % (cell, STRONG, _e(no), cell, _e(title), cell, RED, RED, _e(rev), cell, _e(size), cell, _e(about))
    if _pv["on"]:
        return _wrap('<table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>%s</tr>%s</table>' % (head, body), ROW1, 12)
    return ('<table class="bd" width="100%%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid %s;border-radius:14px;border-collapse:separate;overflow:hidden;table-layout:fixed;">'
            '<tr>%s</tr>%s</table>' % (LINE, head, body))


def _list(items):
    out = ""
    for it in items:
        tags = re.findall(r"\[([^\]]+)\]", it)
        main = re.sub(r"\s*\[[^\]]+\]", "", it).strip()
        if ": " in main and len(main.split(": ", 1)[0]) < 70:
            lead, rest = main.split(": ", 1)
            main_html = '<b class="st" style="color:%s;">%s</b><br><span class="tx" style="color:%s;">%s</span>' % (STRONG, _e(lead), TXT, _e(rest))
        else:
            main_html = '<span class="tx" style="color:%s;">%s</span>' % (TXT, _e(main))
        tag_html = "".join('<br><span class="mu" style="color:%s;font-size:12px;">%s</span>' % (MUTED, _e(t)) for t in tags)
        if _pv["on"]:
            out += ('<tr><td>%s</td></tr><tr><td height="6" style="font-size:1px;line-height:1px;">&nbsp;</td></tr>'
                    % _wrap('<div style="font-family:%s;font-size:14px;line-height:21px;">%s%s</div>' % (FONT, main_html, tag_html), ROW1, 8, accent=RED))
            continue
        out += ('<tr><td width="5" bgcolor="%s" style="background-color:%s;border-radius:6px 0 0 6px;font-size:0;line-height:0;">&nbsp;</td>'
                '<td class="r1" style="padding:10px 14px;font-family:%s;font-size:14px;line-height:21px;background-color:%s;border-radius:0 10px 10px 0;" bgcolor="%s">%s%s</td></tr>'
                '<tr><td colspan="2" height="6" style="font-size:0;line-height:0;">&nbsp;</td></tr>') % (RED, RED, FONT, ROW1, ROW1, main_html, tag_html)
    return '<table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table>' % out


def _title_parts(subject):
    """(project name, 'Revision 2 | 17 November 2026') from the subject line."""
    m = re.match(r"^(.*?)\s+-\s+revision\s+(\S+)\s*(?:\((.*)\))?\s*$", subject or "", re.I)
    if m:
        return m.group(1).strip(), "Revision %s%s" % (m.group(2), ("  |  " + m.group(3)) if m.group(3) else "")
    return (subject or "Drawing register").strip(), ""


def build(subject, body, logo_src="cid:mcplogo", attached="", logo_dark_src="", company="MCP Architecture & Interiors", preview=False, sig_src="", sig_parts=None):
    _pv["on"] = bool(preview)
    _pv["res"] = {}
    project, strip = _title_parts(subject)
    blocks = parse(body)
    greet = next((b[1] for b in blocks if b[0] == "greet"), "")
    rows = []
    for kind, val in blocks:
        if kind == "greet":
            continue
        if kind == "p":
            rows.append('<tr><td class="tx" style="padding:0 0 14px 0;font-family:%s;font-size:15px;line-height:24px;color:%s;">%s</td></tr>' % (FONT, TXT, _e(val).replace("\n", "<br>")))
        elif kind in ("h", "sub"):
            rows.append(("H", kind, val))
        elif kind == "items":
            parsed = [DRAWING.match(x) for x in val]
            if all(parsed):
                rows.append(("T", [m.groups() for m in parsed]))
            else:
                rows.append(("L", val))
        elif kind == "status":
            rows.append(("S", val.split(":", 1)[-1].strip().rstrip(".")))
        elif kind == "sig":
            rows.append(("G", val))

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
            sections += ('<tr><td class="tx" style="padding:14px 6px 0 6px;font-family:%s;font-size:15px;line-height:24px;color:%s;">%s</td></tr>' % (FONT, TXT, r.split(">", 2)[-1].rsplit("</td>", 1)[0]))
        elif r[0] == "H":
            sections += _heading(r[1], r[2])
        elif r[0] == "T":
            sections += '<tr><td style="padding:0 0 8px 0;">%s</td></tr>' % _drawing_table(r[1])
        elif r[0] == "L":
            sections += '<tr><td style="padding:0 0 8px 0;">%s</td></tr>' % _list(r[1])
        elif r[0] == "S":
            if _pv["on"]:
                pill = ('<tr><td align="center" style="padding:0 0 22px 0;">%s</td></tr>' %
                        _wrap('<span style="font-family:%s;font-size:16px;font-weight:700;color:#FFFFFF;">&nbsp;%s&nbsp;</span>' % (FONT, _e(r[1])), RED, 12, width=""))
            else:
                pill = ('<tr><td align="center" style="padding:0 0 22px 0;"><span style="font-family:%s;font-size:16px;font-weight:700;color:#FFFFFF;background-color:%s;border-radius:18px;padding:7px 22px;" bgcolor="%s">%s</span></td></tr>'
                        % (FONT, RED, RED, _e(r[1])))
            sections += ('<tr><td align="center" class="mu" style="padding:28px 0 16px 0;font-family:%s;font-size:12px;letter-spacing:3px;color:%s;">STATUS OF THIS REVISION</td></tr>' % (FONT, MUTED)) + pill
        elif r[0] == "G" and sig_src and sig_parts and not _pv["on"]:
            # the banner in pieces, so the phone, email and website are real links; the pieces scale with the width
            rows, lt = sig_parts
            href = {"tel": "tel:" + lt.get("tel", ""), "mail": "mailto:" + lt.get("email", ""), "web": "https://www.mcparchitecture.co.za"}
            alt = {"tel": lt.get("phone", ""), "mail": lt.get("email", ""), "web": "www.mcparchitecture.co.za"}
            nm, rl = sig_parts[1].get("name", ""), sig_parts[1].get("role", "")
            mob = ('<div class="sgm cd" style="display:none;max-height:0;overflow:hidden;mso-hide:all;background-color:#F1F1F1;border-radius:14px;padding:16px 18px;font-family:%s;">'
                   '<div class="st" style="font-size:20px;font-weight:700;color:%s;">%s</div>'
                   '<div style="font-size:15px;font-weight:700;color:%s;padding:2px 0 8px 0;">%s</div>'
                   '<div style="font-size:16px;line-height:26px;">%s</div></div>'
                   % (FONT, STRONG, _e(nm), RED, _e(rl), "<br>".join(
                       '<a class="st" href="%s" style="color:%s;text-decoration:none;">%s</a>' % (_e(href[k]), STRONG, _e(alt[k])) for k in ("tel", "mail", "web") if alt[k])))
            tb = ""
            for _h, cells in rows:
                tds = ""
                for idx, x0, x1, kind in cells:
                    img = ('<img src="cid:mcpsig%d" width="100%%" alt="%s" style="display:block;width:100%%;height:auto;border:0;">' % (idx, _e(alt.get(kind, "")) or "Signature"))
                    if kind:
                        img = '<a href="%s" style="text-decoration:none;">%s</a>' % (_e(href[kind]), img)
                    tds += '<td width="%.3f%%" style="padding:0;font-size:0;line-height:0;">%s</td>' % ((x1 - x0) * 100.0 / 1875.0, img)
                tb += '<table width="100%%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;table-layout:fixed;"><tr>%s</tr></table>' % tds
            sections += ('<tr><td style="padding:26px 0 0 0;font-family:%s;font-size:12px;letter-spacing:3px;font-weight:700;color:%s;">REGARDS</td></tr>' % (FONT, RED)
                         + '<tr><td style="padding:10px 0 0 0;"><div class="sgd" style="max-width:680px;border-radius:12px;overflow:hidden;">%s</div>%s</td></tr>' % (tb, mob))
        elif r[0] == "G" and sig_src:
            # the finished signature banner (picture): "Regards," above it, scaled to the width of the phone
            sections += ('<tr><td style="padding:26px 0 0 0;font-family:%s;font-size:12px;letter-spacing:3px;font-weight:700;color:%s;">REGARDS</td></tr>'
                         '<tr><td style="padding:10px 0 0 0;"><img src="%s" width="%d" alt="Signature" style="display:block;width:100%%;%sheight:auto;border:0;border-radius:12px;"></td></tr>'
                         % (FONT, RED, sig_src, 600 if _pv["on"] else 680, "" if _pv["on"] else "max-width:680px;"))
        elif r[0] == "G":
            sig = r[1]
            name = sig[0] if sig else ""
            role = sig[1] if len(sig) > 1 else ""
            more = "".join('<br><span class="mu" style="color:%s;">%s</span>' % (MUTED, _e(x)) for x in sig[2:])
            if _pv["on"]:
                inner = ('<div style="padding:10px 12px;font-family:%s;font-size:14px;line-height:22px;color:%s;">'
                         '<span style="color:%s;font-size:12px;letter-spacing:3px;font-weight:700;">REGARDS</span><br><b style="font-size:17px;color:%s;">%s</b><br>%s%s</div>'
                         % (FONT, TXT, RED, STRONG, _e(name), _e(role), more))
                sections += '<tr><td style="padding:26px 0 0 0;">%s</td></tr>' % _wrap(inner, CARD, 14, accent=RED)
            else:
                sections += ('<tr><td style="padding:26px 0 0 0;"><table class="cd bd" width="100%%" cellpadding="0" cellspacing="0" border="0" style="background-color:%s;border:1px solid %s;border-radius:18px;border-collapse:separate;" bgcolor="%s"><tr>'
                             '<td width="6" bgcolor="%s" style="background-color:%s;border-radius:18px 0 0 18px;font-size:0;">&nbsp;</td>'
                             '<td class="tx" style="padding:18px 22px;font-family:%s;font-size:14px;line-height:22px;color:%s;">'
                             '<span style="color:%s;font-size:12px;letter-spacing:3px;font-weight:700;">REGARDS</span><br><b class="st" style="font-size:17px;color:%s;">%s</b><br>%s%s</td></tr></table></td></tr>'
                             % (CARD, LINE, CARD, RED, RED, FONT, TXT, RED, STRONG, _e(name), _e(role), more))

    attached_html = ('<tr><td align="center" class="mu" style="padding:18px 10px 0 10px;font-family:%s;font-size:12px;color:%s;">%s</td></tr>' % (FONT, MUTED, _e(attached))) if attached else ""
    sub_line = ('<div class="mu" style="font-family:%s;font-size:14px;color:%s;padding-top:6px;">%s</div>' % (FONT, MUTED, _e(strip))) if strip else ""
    title_inner = ('<div class="st" style="font-family:%s;font-size:34px;line-height:38px;font-weight:700;color:%s;">DRAWING REGISTER</div>%s'
                   '<div class="tx" style="font-family:%s;font-size:15px;color:%s;padding-top:8px;font-weight:700;">%s</div>' % (FONT, STRONG, sub_line, FONT, TXT, _e(project)))
    intro_inner = ('<div class="st" style="font-family:%s;font-size:16px;font-weight:700;color:%s;padding-bottom:12px;">%s</div>'
                   '<table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table>' % (FONT, STRONG, _e(greet), intro))
    if _pv["on"]:
        title_card = '<tr><td>%s</td></tr>' % _wrap('<div style="padding:12px 14px;">%s</div>' % title_inner, HEAD, 16)
        intro_card = '<tr><td>%s</td></tr>' % _wrap('<div style="padding:14px 16px;">%s</div>' % intro_inner, CARD, 16)
    else:
        title_card = ('<tr><td class="hd" bgcolor="%s" style="background-color:%s;border:1px solid #C9C9C9;border-radius:18px;padding:22px 26px 20px 26px;">%s</td></tr>' % (HEAD, HEAD, title_inner))
        intro_card = ('<tr><td class="cd" style="background-color:%s;border:1px solid %s;border-radius:22px;" bgcolor="%s">'
                      '<table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr><td style="padding:26px 30px 14px 30px;">%s</td></tr></table></td></tr>' % (CARD, LINE, CARD, intro_inner))
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">'
            '<title>%(title)s</title><style>%(css)s</style></head>'
            '<body class="pg" style="margin:0;padding:0;background-color:%(page)s;" bgcolor="%(page)s">'
            '<table class="pg" width="100%%" cellpadding="0" cellspacing="0" border="0" bgcolor="%(page)s" style="background-color:%(page)s;"><tr><td align="center" style="padding:22px 12px;">'
            '<table width="680" cellpadding="0" cellspacing="0" border="0" style="width:100%%;max-width:680px;">'
            # the logo: white and red for dark mode (the default), black and red for light mode
            '<tr><td align="center" style="padding:10px 0 0 0;">'
            '<img class="lgl" src="%(logo)s" width="150" alt="MCP" style="display:block;border:0;margin:0 auto;">'
            '%(logo_light)s</td></tr>'
            '<tr><td align="center" class="st" style="padding:14px 0 22px 0;font-family:%(font)s;font-size:19px;font-weight:700;letter-spacing:2px;color:%(st)s;">%(company_caps)s</td></tr>'
            # grey rounded title card + red rounded bar, as on the PDF
            '%(title_card)s'
            '<tr><td style="padding:10px 0 14px 0;">%(bar)s</td></tr>'
            '%(intro_card)s'
            '%(sections_wrap)s'
            '%(attached)s'
            '<tr><td align="center" class="mu" style="padding:22px 0 4px 0;font-family:%(font)s;font-size:11px;letter-spacing:3px;color:%(muted)s;">%(company_caps)s</td></tr>'
            '</table></td></tr></table></body></html>') % {
        "title": _e(project), "css": DARK_CSS, "page": PAGE, "head": HEAD, "card": CARD, "line": LINE, "tx": TXT, "st": STRONG, "muted": MUTED,
        "logo": logo_src, "logo_light": ('<img class="lgd" src="%s" width="150" alt="MCP" style="display:none;max-height:0;overflow:hidden;mso-hide:all;border:0;margin:0 auto;">' % logo_dark_src) if logo_dark_src else "", "font": FONT, "sub": sub_line, "project": _e(project), "company": _e(BRAND), "company_caps": _e(BRAND.upper()),
        "title_card": title_card, "intro_card": intro_card, "bar": _bar(None, 12, "left", "0"), "greet": _e(greet), "intro": intro, "attached": attached_html,
        "sections_wrap": ('<tr><td style="padding-top:6px;"><table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table></td></tr>' % sections) if sections else ""}
