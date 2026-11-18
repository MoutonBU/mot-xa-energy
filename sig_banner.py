"""The email signature banner. The background, logo and website are fixed (sig_template.png); the name, position, phone, email and photo are
drawn on it from the user's own details."""
import os
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPolygonF

W, H = 1875, 469
PHOTO_POLY = [(0, 0), (340, 0), (262, H), (0, H)]
INK, RED = QColor("#111111"), QColor("#D1121F")


def _template_path():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(base, "sig_template.png"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "sig_template.png")):
        if os.path.exists(p):
            return p
    return ""


def available(S):
    """The new signature is used once the person has typed their name."""
    return bool(str(S.get("sig_name", "") or "").strip()) and bool(_template_path())


def _fit(p, text, px, maxw, bold=True, min_px=14):
    f = QFont("Arial")
    f.setBold(bold)
    while px > min_px:
        f.setPixelSize(int(px))
        if QFontMetrics(f).horizontalAdvance(text) <= maxw:
            break
        px -= 1
    f.setPixelSize(int(px))
    p.setFont(f)
    return f


def _placeholder(p):
    p.fillRect(QRectF(0, 0, 340, H), QColor("#d6d8db"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#a3a8ae"))
    p.drawEllipse(QPointF(150, 170), 78, 92)                      # head
    path = QPainterPath()
    path.addEllipse(QPointF(150, 470), 170, 190)                  # shoulders
    p.drawPath(path)


_ICONS = {}


def _icon(kind):
    if kind not in _ICONS:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        _ICONS[kind] = QImage(os.path.join(base, "sig_icon_%s.png" % kind))
    return _ICONS[kind]


ROW1, ROW2, FS = 254, 315, 32


def _tw(text, px, maxw):
    f = QFont("Arial")
    f.setBold(True)
    while px > 14:
        f.setPixelSize(int(px))
        if QFontMetrics(f).horizontalAdvance(text) <= maxw:
            break
        px -= 1
    f.setPixelSize(int(px))
    return QFontMetrics(f).horizontalAdvance(text), px


def layout(S):
    """Where the phone, email and website sit. The email follows straight after the phone number, so the two stay together."""
    g = lambda k: str(S.get(k, "") or "").strip()
    phone, email = g("sig_phone"), g("sig_email") or g("mail_address")
    L = {}
    right = 1850
    x = 850
    if phone:
        w, px = _tw(phone, FS, 420)
        L["phone"] = {"text": phone, "x0": x, "tx": x + 44, "px": px, "maxw": 420, "base": ROW1, "end": x + 44 + w}
        x = x + 44 + w + 44
    if email:
        avail = right - (x + 44)
        w, px = _tw(email, FS, avail)
        L["mail"] = {"text": email, "x0": x, "tx": x + 44, "px": px, "maxw": avail, "base": ROW1, "end": x + 44 + w}
    w, px = _tw("www.mcparchitecture.co.za", FS, 900)
    L["web"] = {"text": "www.mcparchitecture.co.za", "x0": 850, "tx": 894, "px": px, "maxw": 900, "base": ROW2, "end": 894 + w}
    return L


def render(S, photo_path=None):
    """The signature as a QImage (1875 x 469)."""
    tpl = QImage(_template_path())
    if tpl.isNull():
        tpl = QImage(W, H, QImage.Format.Format_RGB32)
        tpl.fill(QColor("#f4f4f4"))
    img = tpl.convertToFormat(QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    # photo, cut to the slanted strip
    clip = QPainterPath()
    clip.addPolygon(QPolygonF([QPointF(x, y) for x, y in PHOTO_POLY]))
    clip.closeSubpath()
    p.save()
    p.setClipPath(clip)
    ph = QImage(photo_path or str(S.get("sig_photo", "") or "")) if (photo_path or S.get("sig_photo")) else QImage()
    if ph.isNull():
        _placeholder(p)
    else:
        sc = max(340 / ph.width(), H / ph.height())
        w, h = ph.width() * sc, ph.height() * sc
        x = (340 - w) / 2
        y = min(0.0, max(H - h, -(h - H) * 0.22))               # keep the head: crop more from the bottom than from the top
        p.drawImage(QRectF(x, y, w, h), ph)
    p.restore()
    g = lambda k: str(S.get(k, "") or "").strip()
    name, role = g("sig_name"), g("sig_role")
    L = layout(S)
    p.setPen(INK)
    _fit(p, name, 49, 980)
    p.drawText(QPointF(850, 152), name)
    if role:
        p.setPen(RED)
        _fit(p, role, 33, 980)
        p.drawText(QPointF(851, 195), role)
    p.setPen(INK)
    for key, kind in (("phone", "phone"), ("mail", "mail"), ("web", "web")):
        if key not in L:
            continue
        txt, x0, tx, px, base = L[key]["text"], L[key]["x0"], L[key]["tx"], L[key]["px"], L[key]["base"]
        ic = _icon(kind)
        if not ic.isNull():
            p.drawImage(QRectF(x0, base - 29, ic.width() * 1.12, ic.height() * 1.12), ic)
        _fit(p, txt, px, L[key]["maxw"])
        p.drawText(QPointF(tx, base), txt)
    p.end()
    return img


def _rounded(S, width):
    img = render(S).convertToFormat(QImage.Format.Format_RGB32)
    img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    # rounded corners like the cards in the email (the corners are white, the email page is white)
    out = QImage(img.size(), QImage.Format.Format_RGB32)
    out.fill(QColor("#FFFFFF"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, img.width(), img.height()), width * 0.022, width * 0.022)
    p.setClipPath(path)
    p.drawImage(0, 0, img)
    p.end()
    return out


def _jpg(img, quality):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", quality)
    return bytes(ba)


def jpeg_bytes(S, width=1250, quality=92):
    return _jpg(_rounded(S, width), quality)


def link_text(S):
    g = lambda k: str(S.get(k, "") or "").strip()
    phone = g("sig_phone")
    tel = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return {"phone": phone, "tel": tel, "email": g("sig_email") or g("mail_address"), "name": g("sig_name"), "role": g("sig_role")}


def slices(S, width=1250, quality=92):
    """The banner cut into pieces so the phone, the email and the website can each be a real link.
    Returns (rows, jpegs): rows is a list of (height_px, [(index, x0, x1, kind), ...]) in the 1875 wide design;
    kind is "", "tel", "mail" or "web"."""
    lt = link_text(S)
    full = _rounded(S, width)
    k = width / float(W)
    ymap = lambda y: int(round(y * k))
    L = layout(S)
    row1 = [(0, 840, "")]
    cur = 840
    for key, kind in (("phone", "tel"), ("mail", "mail")):
        if key in L:
            x0, x1 = (L[key]["x0"] - 10), L[key]["end"] + 12
            if x0 > cur:
                row1.append((cur, x0, ""))
            row1.append((x0, x1, kind))
            cur = x1
    row1.append((cur, W, ""))
    pe = L["web"]["end"] + 12
    spec = [(0, 222, [(0, W, "")]), (222, 274, row1), (274, 282, [(0, W, "")]),
            (282, 332, [(0, 840, ""), (840, pe, "web"), (pe, W, "")]), (332, H, [(0, W, "")])]
    rows, jp = [], []
    for y0, y1, cells in spec:
        r = []
        for x0, x1, kind in cells:
            ix0, ix1 = ymap(x0), (width if x1 >= W else ymap(x1))
            piece = full.copy(ix0, ymap(y0), ix1 - ix0, (full.height() if y1 >= H else ymap(y1)) - ymap(y0))
            r.append((len(jp), ix0, ix1, kind))
            jp.append(_jpg(piece, quality))
        rows.append((y1 - y0, r))
    return rows, jp


def prepare_photo(src_path, dest_path):
    """Save the chosen picture for the signature: a sensible size, so the settings folder stays small."""
    im = QImage(src_path)
    if im.isNull():
        return False
    if im.width() > 900 or im.height() > 1200:
        im = im.scaled(900, 1200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return im.save(dest_path, "PNG")
