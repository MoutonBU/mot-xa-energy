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
    name, role, phone = g("sig_name"), g("sig_role"), g("sig_phone")
    email = g("sig_email") or g("mail_address")
    p.setPen(INK)
    _fit(p, name, 37, 660)
    p.drawText(QPointF(850, 158), name)
    if role:
        p.setPen(RED)
        _fit(p, role, 25, 660)
        p.drawText(QPointF(851, 199), role)
    p.setPen(INK)
    if phone:
        line = phone
        _fit(p, line, 21.5, 322)
        p.drawText(QPointF(890, 257), line)
    if email:
        _fit(p, email, 21, 575)
        p.drawText(QPointF(1266, 257), email)
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
    return {"phone": phone, "tel": tel, "email": g("sig_email") or g("mail_address")}


def slices(S, width=1250, quality=92):
    """The banner cut into pieces so the phone, the email and the website can each be a real link.
    Returns (rows, jpegs): rows is a list of (height_px, [(index, x0, x1, kind), ...]) in the 1875 wide design;
    kind is "", "tel", "mail" or "web"."""
    lt = link_text(S)
    full = _rounded(S, width)
    k = width / float(W)
    ymap = lambda y: int(round(y * k))
    spec = [(0, 232, [(0, W, "")]),
            (232, 274, [(0, 840, ""), (840, 1215, "tel" if lt["tel"] else ""), (1215, 1862, "mail" if lt["email"] else ""), (1862, W, "")]),
            (274, 332, [(0, 840, ""), (840, 1180, "web"), (1180, W, "")]),
            (332, H, [(0, W, "")])]
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
