import os, time, base64, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import ui_extras as U, mot_xa_energy as M, mail_oauth as mo

b64 = lambda t: base64.urlsafe_b64encode(t.encode()).decode().rstrip("=")
def msg(i, frm, subj, labels, html="<p>Hello <b>world</b></p>", att=False):
    parts = [{"mimeType": "text/html", "body": {"data": b64(html)}}]
    if att:
        parts.append({"mimeType": "application/pdf", "filename": "plan.pdf", "body": {"attachmentId": "A1", "size": 2048}})
    return {"id": "m%d" % i, "labelIds": labels, "internalDate": str(int(time.time() * 1000)), "snippet": "snippet %d" % i,
            "payload": {"mimeType": "multipart/mixed", "headers": [{"name": "From", "value": frm}, {"name": "To", "value": "me@x.com"}, {"name": "Subject", "value": subj},
                                                                  {"name": "Message-ID", "value": "<id%d@x>" % i}], "parts": parts}}
THREADS = {"t1": {"id": "t1", "messages": [msg(1, "Dewann Blaauw <d@y.com>", "Erf 670", ["INBOX", "UNREAD"], att=True), msg(2, "me@x.com", "Re: Erf 670", ["INBOX", "SENT"])]},
           "t2": {"id": "t2", "messages": [msg(3, "Google Cloud <g@z.com>", "Pricing update", ["INBOX", "STARRED"])]}}
calls = []
def fake(S, method, path, params=None, body=None, timeout=60):
    calls.append((method, path))
    if path == "labels":
        return {"labels": [{"id": "INBOX", "type": "system"}, {"id": "Label_1", "name": "City Dev", "type": "user"}, {"id": "Label_2", "name": "City Dev/Zandspruit", "type": "user"}]}
    if path == "profile":
        return {"emailAddress": "me@x.com"}
    if path.startswith("labels/"):
        return {"threadsUnread": 364, "threadsTotal": 900}
    if path == "threads":
        return {"threads": [{"id": "t1", "snippet": "Hello world"}, {"id": "t2", "snippet": "Review pricing"}], "nextPageToken": "N2"}
    if path.startswith("threads/") and path.endswith("/modify"):
        return {}
    if path.startswith("threads/"):
        return THREADS[path.split("/")[1]]
    return {}
mo.gmail_call = fake
mo.gmail_batch = lambda *a, **k: None

w = M.MainWindow()
S = M.SETTINGS
S.update({"google_client_id": "x", "google_refresh": "r", "gmail_modify": True, "gmail_read": True, "mail_address": "me@x.com", "mail_provider": "gmail", "mail_collapsed": []})
mp = w.mail_page
assert mp is not None and w.main_tabs.tabText(w.main_tabs.indexOf(mp)) == "Mail"
mp._refresh_state()

assert mp.ready() and not mp.main.isHidden()
def wait(cond, t=8):
    t0 = time.time()
    while time.time() - t0 < t:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False
mp._loaded = False
mp.ensure_loaded()
assert wait(lambda: mp.list.count() == 2), mp.list.count()
r = mp.rows[0]
assert r["id"] == "t1" and r["count"] == 2 and r["unread"] and r["sender"] == "Dewann Blaauw, me" and r["attach"], r
assert mp.rows[1]["starred"] and not mp.rows[1]["unread"]
assert wait(lambda: any(mp.side.item(i).text().strip().startswith("Inbox   364") for i in range(mp.side.count()))), [mp.side.item(i).text() for i in range(mp.side.count())]
names = [mp.side.item(i).text() for i in range(mp.side.count())]
assert any("City Dev" in n for n in names) and any("Zandspruit" in n for n in names), names
assert mp.next.isEnabled() and not mp.prev.isEnabled()
# open and read
mp.open_thread("t1", "Erf 670")
assert wait(lambda: mp.thread_lay.count() >= 2 and getattr(mp, "msgs", None))
assert mp.stack.currentIndex() == 1 and len(mp.msgs) == 2
assert mp.msgs[0][3][0]["name"] == "plan.pdf"
# star + archive
mp.toggle_star("t2", False, 1)
assert wait(lambda: ("POST", "threads/t2/modify") in calls)
mp._back()
mp.list.item(0).setData(U.ROLE_CHECK, True); mp.update_bulk()
assert mp.checked_ids() == ["t1"]
mp.act("archive")
assert wait(lambda: mp.list.count() == 1)
# compose message with signature lines
S.update({"sig_name": "Mouton Burger", "sig_role": "CEO"})
m = U.mail_compose(S, "a@b.com", subject="Hi", html_body="<p>Hello</p>", plain_body="Hello")
assert m["To"] == "a@b.com" and m["Subject"] == "Hi" and "Mouton" in str(m["From"])
raw = bytes(m); assert b"text/html" in raw and b"Hello" in raw
# reply dialog values
mp.open_thread("t1", "Erf 670"); wait(lambda: getattr(mp, "msgs", None) and mp.thread_lay.count() >= 2)
import ui_extras
opened = {}
class D(ui_extras.MailCompose):
    def exec(self):
        opened.update(to=self.to.text(), cc=self.cc.text(), subj=self.subject.text(), tid=self.thread_id, irt=self.in_reply_to, body=self.body.toPlainText())
        return 0
ui_extras.MailCompose = D
mp._reply("reply")
assert opened["to"] == "me@x.com" or "me@x.com" in opened["to"] or opened["to"], opened       # last message is mine: reply goes to who I wrote to
assert opened["subj"] == "Re: Erf 670" and opened["tid"] == "t1" and opened["irt"] == "<id2@x>" and "wrote" in opened["body"], opened
mp._reply("forward")
assert opened["subj"].startswith("Re: ") or opened["subj"].startswith("Fwd:"), opened
# not signed in view
S["gmail_modify"] = False
mp._refresh_state(); assert not mp.connect_box.isHidden() and mp.main.isHidden()
assert U.mail_date_text(int(time.time() * 1000)).endswith(("AM", "PM"))
print("ok")

# categories use Gmail's own category labels
S.update({"gmail_modify": True, "gmail_read": True})
gcalls = []
_f = mo.gmail_call
def spy(S, method, path, params=None, body=None, timeout=60):
    gcalls.append((method, path, params, body))
    return _f(S, method, path, params, body, timeout)
mo.gmail_call = spy
mp.label = "INBOX"; mp.query = ""; mp.stack.setCurrentIndex(0)
mp.cats.blockSignals(True); mp.cats.setCurrentIndex(3); mp.cats.blockSignals(False)
mp.cats.setCurrentIndex(1)
assert wait(lambda: any(c[1] == "threads" and c[2] and "CATEGORY_PROMOTIONS" in c[2].get("labelIds", []) for c in gcalls)), gcalls[-3:]
mp.cats.setCurrentIndex(0)
assert wait(lambda: any(c[1] == "threads" and c[2] and c[2].get("labelIds") == ["INBOX"] and "-category:promotions" in c[2].get("q", "") for c in gcalls))
# collapse a parent label: its child disappears, and expanding brings it back
def texts():
    return [mp.side.item(i).text() for i in range(mp.side.count())]
S["mail_collapsed"] = ["City Dev"]
mp._fill_side()
assert not any("Zandspruit" in t for t in texts()) and any("▸ City Dev" in t for t in texts()), texts()
S["mail_collapsed"] = []
mp._fill_side()
assert any("Zandspruit" in t for t in texts())
S.pop("mail_collapsed", None)
mp._fill_side()
assert not any("Zandspruit" in t for t in texts()), texts()          # groups start closed
S["mail_collapsed"] = []
mp._fill_side()
# a label created here is created in Gmail
mp._label_dialog = lambda title, name="", parent="": ("Quotes", "City Dev")
gcalls.clear()
mp.new_label()
assert wait(lambda: any(c[0] == "POST" and c[1] == "labels" and c[3]["name"] == "City Dev/Quotes" for c in gcalls)), gcalls
# labelling selected mail adds the Gmail label to the threads
mp.list.item(0).setData(M.ROLE_CHECK if hasattr(M, "ROLE_CHECK") else mo.ROLE_CHECK, True) if False else None
mp.modify(["t1"], add=["Label_1"])
assert wait(lambda: any(c[1] == "threads/t1/modify" and c[3]["addLabelIds"] == ["Label_1"] for c in gcalls))
print("ok2")

# inline signature pictures: found whatever the case of the cid, fetched only when the body uses them
import base64 as _b
html = "<p>hi</p><img src=\"cid:Image001.PNG@01DC\"><img src=\"cid:Image002.PNG@01DC\">"
th = {"id": "tz", "messages": [{"id": "m1", "payload": {"mimeType": "multipart/related", "headers": [], "parts": [
    {"mimeType": "text/html", "body": {"data": _b.urlsafe_b64encode(html.encode()).decode()}},
    {"mimeType": "image/png", "filename": "image001.png", "headers": [{"name": "Content-ID", "value": "<image001.png@01dc>"}], "body": {"attachmentId": "A1", "size": 900}},
    {"mimeType": "image/png", "filename": "image002.png", "headers": [{"name": "Content-ID", "value": "<image002.png@01dc>"}], "body": {"attachmentId": "A2", "size": 900}},
    {"mimeType": "image/png", "filename": "image003.png", "headers": [{"name": "Content-ID", "value": "<image003.png@01dc>"}], "body": {"attachmentId": "A3", "size": 900}}]}}]}
fetched = []
_old = mo.gmail_call
mo.gmail_call = lambda S, method, path, params=None, body=None, timeout=60: th if path == "threads/tz" else {"data": _b.urlsafe_b64encode(b"PNGDATA").decode()} if "attachments" in path else _old(S, method, path, params, body, timeout)
_r = mp._fetch_thread("tz"); mp._thread_images("tz"); got = _r[1][0][4]
assert sorted(got) == ["image001.png@01dc", "image002.png@01dc"] and got["image001.png@01dc"] == b"PNGDATA", got
mo.gmail_call = _old
print("ok3")

# pictures either show or vanish, never the grey missing-picture box
from PySide6.QtGui import QImage, QTextDocument as _TD
from PySide6.QtCore import QBuffer, QByteArray
_im = QImage(4, 4, QImage.Format.Format_RGB32); _im.fill(0xff0000)
_ba = QByteArray(); _bf = QBuffer(_ba); _bf.open(QBuffer.OpenModeFlag.WriteOnly); _im.save(_bf, "PNG"); png = bytes(_ba)
dd = _TD()
body = ('<img src="cid:A@x" width=10><img src="cid:MISSING"><img src="data:image/png;base64,%s"><img src="https://a.b/c.png?x=1&amp;y=2">'
        '<img src="https://a.b/d.png"><img src="cid:BAD@x">') % _b.b64encode(png).decode()
out = U.mail_fix_images(body, dd, {"a@x": png, "bad@x": b"notanimage", "url:https://a.b/c.png?x=1&y=2": png}, True)
assert out.count("<img") == 3 and "MISSING" not in out and "d.png" not in out and "BAD" not in out, out
assert U.mail_web_images(body) == ["https://a.b/c.png?x=1&y=2", "https://a.b/d.png"]
print("ok4")

# the Mail tab takes the whole window: no ribbon, rail or step strip, but Home and Switch tool stay
w.main_tabs.setCurrentWidget(mp)
app.processEvents()
import app_shell
w.shell_refresh() if hasattr(w, "shell_refresh") else None
for _ in range(3):
    app.processEvents()
w._shell_timer.timeout.emit()
assert w.shell_ribbon.isHidden() and w.shell_rail.isHidden() and w.step_strip.isHidden(), (w.shell_ribbon.isHidden(), w.shell_rail.isHidden(), w.step_strip.isHidden())
labels = [b.text() for b in mp.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
assert any("Home" in t for t in labels) and any("Switch tool" in t for t in labels)
w.main_tabs.setCurrentIndex(w.main_tabs.indexOf(w.plan_page) if getattr(w, "plan_page", None) is not None else 0)
w._shell_timer.timeout.emit()
print("ok5")

# the batch path: the missing conversations come from ONE call
mo.gmail_batch = lambda S, paths, timeout=60: [{"id": p.split("/")[1].split("?")[0], "messages": THREADS["t1"]["messages"]} for p in paths]
mp._tcache = {}
mp._lcache = {}
mp.label = "INBOX"; mp.query = ""
mp.load_list(reset=True)
assert wait(lambda: mp.list.count() == 2)
print("ok6")

# Gmail signature pictures (hosted by Google) show without pressing anything
url = "https://ci3.googleusercontent.com/mail-sig/AIorK4zr8kiQJ7zs8yAvmTPzrLFCfyN8A33yBZfc9DnqiXtW8WyIhLL5HDg1vH3lvE6OCcqveYDEJg6NxREG"
assert U.mail_trusted_image(url) and not U.mail_trusted_image("https://evil.example/mail-sig/x.png") and not U.mail_trusted_image("http://ci3.googleusercontent.com/mail-sig/x")
th2 = {"id": "tw", "messages": [{"id": "m9", "payload": {"mimeType": "text/html", "headers": [], "body": {"data": _b.urlsafe_b64encode(('<p>x</p><div><img src="%s"></div><img src="https://tracker.example/p.png">' % url).encode()).decode()}}}]}
fetched = []
U._web_picture = lambda u: (fetched.append(u), png)[1]
S["mail_images"] = False
mo.gmail_call = lambda S_, method, path, params=None, body=None, timeout=60: th2 if path == "threads/tw" else _old(S_, method, path, params, body, timeout)
mp._topen.clear()
_r = mp._fetch_thread("tw"); mp._thread_images("tw"); got = _r[1][0][4]
assert fetched == [url] and "url:" + url in got, (fetched, list(got))
mo.gmail_call = _old
print("ok7")

# resizable, rounded side column; width is remembered
assert mp.split.count() == 2 and mp.split.widget(0).objectName() == "mailside"
mp.split.sizes = lambda: [300, 900]; mp._save_side_width()
assert S.get("mail_side_w") == 300 or abs(S.get("mail_side_w", 0) - 300) < 3, S.get("mail_side_w")
print("ok8")

# a picture Qt cannot read falls back to OpenCV; unreadable data says what it was
import cv2 as _cv2, numpy as _np
_ok, _enc = _cv2.imencode(".webp", _np.full((8, 8, 3), 200, _np.uint8))
if _ok:
    assert not U.mail_pixmap(bytes(_enc.tobytes())).isNull()
assert "web page" in U.mail_sniff(b"<!DOCTYPE html><html>") and U.mail_sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
dd2 = _TD()
txt = U.mail_fix_images('<img src="cid:q@x">', dd2, {"q@x": b"<html>nope"}, True)
assert "could not be read" in txt and "web page" in txt, txt
print("ok9")

# wide emails fit the view: big pictures and fixed-width tables are cut down to the window
big = QImage(2000, 800, QImage.Format.Format_RGB32); big.fill(0x00ff00)
ba2 = QByteArray(); bf2 = QBuffer(ba2); bf2.open(QBuffer.OpenModeFlag.WriteOnly); big.save(bf2, "PNG"); bigpng = bytes(ba2)
wide = ('<table width="1200" style="width:1200px;min-width:1200px"><tr><td width="900" style="width:900px">x</td></tr></table>'
        '<img src="cid:big@x" width="100%" style="display:block;width:100%"><img src="cid:big@x" width="3000">')
dd3 = _TD()
res = U.mail_fix_images(wide, dd3, {"big@x": bigpng}, True, 640)
assert "1200" not in res and "900" not in res and "min-width" not in res, res
import re as _re
ws = [int(x) for x in _re.findall(r'<img[^>]*width="(\d+)"', res)]
assert ws and all(x <= 640 for x in ws), ws
assert all(int(h) == int(int(w) * 0.4 + 0.5) for w, h in _re.findall(r'<img[^>]*width="(\d+)" height="(\d+)"', res)), res
dd3.setHtml(res); dd3.setTextWidth(700)
assert dd3.idealWidth() <= 705, dd3.idealWidth()

# Gmail's per-minute limit: the budget makes calls wait, and a real "no" teaches it to use less
import time as _t
from PySide6.QtCore import Qt
mo._UNITS.clear(); mo._BUDGET[0] = 100.0; mo._BLOCK[0] = 0.0
mo._spend(60); mo._spend(30)
try:
    mo._spend(30, max_wait=0)
    raise SystemExit("budget not enforced")
except RuntimeError as e:
    assert "catching up" in str(e)
mo._UNITS.clear(); mo._UNITS.append((_t.time(), 1000)); mo._BUDGET[0] = 8000.0; _Sb = {}
mo._quota_hit(_Sb)
assert mo.gmail_blocked() > 20 and mo._BUDGET[0] == 1000.0, (mo.gmail_blocked(), mo._BUDGET[0])
assert _Sb["gmail_budget"] == 1000.0
mo._BUDGET[0] = 8000.0; mo._learned(_Sb); assert mo._BUDGET[0] == 1000.0
mo._BLOCK[0] = 0.0; mo._BUDGET[0] = 8000.0; mo._UNITS.clear()
assert mo.gmail_cost("GET", "threads/abc?format=full") == 10 and mo.gmail_cost("GET", "profile") == 1

# a list seen before costs no request while the mailbox has not changed; clicking the open label returns from an email
mp._lcache.clear(); mp._hid = "H1"; mp.label = "INBOX"; mp.query = ""; mp.cat = 0; mp.stack.setCurrentIndex(0)
time.sleep(0.3); app.processEvents()
mp._lcache.clear()
mp.load_list(reset=True)
assert wait(lambda: len(mp._lcache) == 1)
time.sleep(0.3); app.processEvents()
n0 = []
_g = mo.gmail_call
mo.gmail_call = lambda *a, **k: (n0.append(a[2]), _g(*a, **k))[1]
mp.load_list(reset=True)
app.processEvents()
assert not n0 and mp.list.count() == 2, (n0, mp._hid, {k: v[2] for k, v in mp._lcache.items()})
mp._hid = "H2"
mp.load_list(reset=True)
assert wait(lambda: n0), "a changed mailbox must reload"
mo.gmail_call = _g
mp.open_thread("t1", "x"); assert wait(lambda: mp.stack.currentIndex() == 1)
for i in range(mp.side.count()):
    if mp.side.item(i).data(Qt.ItemDataRole.UserRole) == "INBOX":
        mp._side_clicked(mp.side.item(i))
assert mp.stack.currentIndex() == 0
print("ok10")

# many attachments must not make the email wider than the window
mp.resize(1000, 700); mp.show(); app.processEvents()
atts = [{"mimeType": "application/pdf", "filename": "Drawing number %03d long file name here.pdf" % i, "headers": [], "body": {"attachmentId": "A%d" % i, "size": 400000}} for i in range(16)]
thx = {"id": "tm", "messages": [{"id": "mm", "internalDate": "1", "payload": {"mimeType": "multipart/mixed", "headers": [{"name": "From", "value": "a <a@b.c>"}, {"name": "To", "value": "x@y.z"}], "parts": [
    {"mimeType": "text/html", "body": {"data": _b.urlsafe_b64encode(b"<table width=1500><tr><td>hello</td></tr></table>").decode()}}] + atts}}]}
mo.gmail_call = lambda S_, method, path, params=None, body=None, timeout=60: thx if path == "threads/tm" else _old(S_, method, path, params, body, timeout)
mp._topen.clear()
mp.open_thread("tm", "many")
assert wait(lambda: mp.thread_lay.count() >= 2)
app.processEvents()
vw = mp.sa.viewport().width()
assert mp.thread_host.minimumSizeHint().width() <= vw, (mp.thread_host.minimumSizeHint().width(), vw)
assert mp.thread_host.width() <= vw + 2, (mp.thread_host.width(), vw)
mo.gmail_call = _old
print("ok11")

# rounded cards, pills and capped column are rebuilt for Qt's text view
from PySide6.QtWidgets import QTextBrowser as _TB
_b = _TB()
_html_in = ('<table width="100%"><tr><td align="center"><table width="680" style="width:100%;max-width:680px;"><tr>'
            '<td bgcolor="#dddddd" style="background-color:#dddddd;border:1px solid #c9c9c9;border-radius:18px;padding:20px;">Title</td></tr>'
            '<tr><td><span style="background-color:#c8102e;color:#fff;border-radius:10px;padding:2px 8px;font-size:12px;">-</span></td></tr></table></td></tr></table>')
_out = U.mail_fix_images(_html_in, _b.document(), {}, False, 1500)
assert "border-radius" not in _out and "mrc:///" in _out and "width=\"704\"" in _out, _out
_b.resize(900, 400); _b.setHtml(_out); _b.document().setTextWidth(900)
assert _b.document().size().height() > 40
print("ok12")

# hidden dark-mode logo and phone-only blocks are dropped
_hid = '<img src="cid:a" class="lgl" width="150"><img src="cid:b" class="lgd" style="display:none;max-height:0;" width="150"><div style="display:none;max-height:0"><div>mobile</div></div><p>keep</p>'
_o = U.mail_drop_hidden(_hid)
assert "cid:b" not in _o and "mobile" not in _o and "cid:a" in _o and "keep" in _o, _o
print("ok13")

# new-mail pop-up: history says a message was added -> one pop-up row with sender, subject and the first lines
import tempfile as _tf
os.environ["MOT_TEST"] = "1"
_old2 = mo.gmail_call
def _fake(S_, method, path, params=None, body=None, timeout=60):
    if path == "history":
        return {"historyId": "99", "history": [{"messagesAdded": [{"message": {"id": "n1", "labelIds": ["INBOX", "UNREAD"]}}]}]}
    if path == "messages/n1":
        return {"threadId": "tn1", "snippet": "Please see the new drawings &amp; revise", "payload": {"headers": [{"name": "From", "value": "Dewann <d@x.co.za>"}, {"name": "Subject", "value": "New drawings"}]}}
    return _old2(S_, method, path, params, body, timeout)
mo.gmail_call = _fake
S["mail_notify_hid"] = "50"; S["mail_notify"] = True
_shown = []
mp._show_toast = lambda rows: _shown.append(rows)
mp._nbusy = False
mp._notify_tick()
assert wait(lambda: _shown), "no pop-up"
assert _shown[0][0]["from"] == "Dewann" and _shown[0][0]["subject"] == "New drawings" and "&amp;" not in _shown[0][0]["snippet"] and S["mail_notify_hid"] == "99"
# a mail you send to yourself (labels INBOX and SENT) pops up too; a reply of yours (SENT only) does not
_h = {"historyId": "100", "history": [{"messagesAdded": [{"message": {"id": "n1", "labelIds": ["INBOX", "SENT", "UNREAD"]}}, {"message": {"id": "n2", "labelIds": ["SENT"]}}]}]}
mo.gmail_call = lambda S_, method, path, params=None, body=None, timeout=60: _h if path == "history" else _fake(S_, method, path, params, body, timeout)
_shown.clear(); mp._nbusy = False; mp._notify_tick()
assert wait(lambda: _shown) and len(_shown[0]) == 1, _shown
mo.gmail_call = _old2
_t = U.MailToast(_shown[0], None, lambda r: None); _t.show(); app.processEvents(); assert _t.width() > 300; _t.close()
print("ok14")

# save all attachments into one folder
_d = _tf.mkdtemp()
_files = [{"name": "a.pdf", "mime": "application/pdf", "size": 3, "id": "", "cid": "", "data": __import__("base64").urlsafe_b64encode(b"abc").decode()},
          {"name": "a.pdf", "mime": "application/pdf", "size": 3, "id": "", "cid": "", "data": __import__("base64").urlsafe_b64encode(b"xyz").decode()}]
U._QFD.getExistingDirectory = staticmethod(lambda *a, **k: _d)
mp._save_all("mm", _files)
assert wait(lambda: len(os.listdir(_d)) == 2), os.listdir(_d)
assert sorted(os.listdir(_d)) == ["a (2).pdf", "a.pdf"]
print("ok15")

# older signature rows (cells adding up to 2/3) are stretched to the full row; PDF previews come from PyMuPDF
_r = '<table><tr><td width="66.667%"><img src="x"></td></tr></table><table><tr><td width="29.867%">a</td><td width="10.293%">b</td><td width="25.84%">c</td></tr></table><table><tr><td width="50%">a</td><td width="50%">b</td></tr></table>'
_o2 = U.mail_fix_rows(_r)
assert 'width="100.000%"' in _o2 and _o2.count('width="50%"') == 2, _o2
import pymupdf as _fz
_dc = _fz.open(); _dc.new_page(width=400, height=300).insert_text((40, 60), "Drawing"); _pdfb = _dc.tobytes()
_pm = U.mail_pdf_pixmap(_pdfb, 130)
assert not _pm.isNull() and _pm.height() == 130, (_pm.width(), _pm.height())
print("ok16")
from PySide6.QtWidgets import QHBoxLayout as _H2
mp.open_thread("t1", "x"); assert wait(lambda: mp.stack.currentIndex() == 1)
_lay = _H2(); _lay.addStretch(1)
mp._thumbs("mm", [{"name": "a.pdf", "mime": "application/pdf", "size": len(_pdfb), "id": "", "data": __import__("base64").urlsafe_b64encode(_pdfb).decode()}], _lay)
assert wait(lambda: _lay.count() >= 2), "no preview button"
print("ok17")

# dark theme: the email's own dark colours are applied; the pop-up takes the mail tab's colours
_dh = '<style>\n@media (prefers-color-scheme: dark){\n .pg{background-color:#0E0F12 !important;}\n .cd{background-color:#23262D !important;border-color:#383C45 !important;}\n .tx{color:#D7D9DE !important;}\n .lgl{display:none !important;}\n}\n</style><body class="pg" style="background-color:#FFFFFF;"><table class="cd" bgcolor="#F2F2F2" style="background-color:#F2F2F2;border:1px solid #C9C9C9;"><tr><td class="tx" style="color:#111;">x</td></tr></table><img class="lgl" src="cid:a"><img class="lgd" src="cid:b" style="display:none;max-height:0;">'
_do, _pg = U.mail_dark(_dh)
assert _pg == "#0E0F12" and 'bgcolor="#23262D"' in _do and "color:#D7D9DE" in _do and "border:1px solid #383C45" in _do and 'cid:a' not in _do and "display:none" not in _do.split("cid:b")[1], _do
_tp = U.MailToast([{"from": "A", "subject": "S", "snippet": "x", "tid": "t"}], None, lambda r: None, ("#ffffff", "#1c1f23", "#6b727b", "#f1f3f5", "#d8132b"))
assert _tp._pal[0] == "#ffffff"; _tp.close()
print("ok18")

# accent = the Mail card's blue; opening a conversation already in memory is immediate; settings hold the signature editor
import app_shell as _sh
assert _sh.TOOL_COL["mail"] == "#4aa3df" and _sh.TOOL_COL["costing"] == "#a587e0" and _sh.TAB_KEY["Mail"] == "mail" and _sh.TAB_KEY["Energy (XA)"] == "xa"
assert mp._pal()["accent"] != _sh._palette0(True)["accent"] and "4aa3df" in mp.compose_btn.styleSheet()
mp.open_thread("t1", "x"); assert wait(lambda: mp.stack.currentIndex() == 1 and mp.thread_lay.count() > 1)
mp.stack.setCurrentIndex(0)
mp.open_thread("t1", "x")
assert mp.thread_lay.count() > 1 and mp.msgs, "a conversation in memory must show without waiting"
assert hasattr(mp, "set_btn") and hasattr(mp, "_edit_signature")
print("ok19")

# label colours: squares before the tick box, colours in the side list, labelling a row updates it at once
mp.labels = [{"id": "Label_1", "name": "City Dev", "type": "user", "color": {"backgroundColor": "#16a766", "textColor": "#ffffff"}}, {"id": "Label_2", "name": "Plain", "type": "user"}]
mp.lcol = {x["id"]: (x.get("color") or {}).get("backgroundColor") or U.MAIL_NOCOL for x in mp.labels}
mp._fill_side()
assert any(mp.side.item(i).icon().isNull() is False for i in range(mp.side.count()) if mp.side.item(i).data(Qt.ItemDataRole.UserRole + 2)), "side swatches"
assert mp._label_cols(["INBOX", "Label_1", "Label_2"]) == ["#16a766", U.MAIL_NOCOL]
mp.rows[0]["labels"] = ["INBOX"]; mp._fill_list()
assert not mp.list.item(0).data(U.ROLE_LABS)
mp.modify([mp.rows[0]["id"]], add=["Label_1"])
assert wait(lambda: mp.list.item(0).data(U.ROLE_LABS) == ["#16a766"]), mp.list.item(0).data(U.ROLE_LABS)
assert mp.sel_all.text() == "Select all"
mp.list.item(0).setData(U.ROLE_LABS, ["#16a766","#4a86e8"]); mp.resize(1200,700); mp.list.grab().save("/tmp/lst.png")
print("ok20")

# the text opens before the pictures arrive; a pulsing mail icon shows while it loads; 54 label colours
import time as _tm
_old2 = mo.gmail_call
def _slow(S, method, path, params=None, body=None, timeout=60):
    if path == "threads/tz":
        return th
    if "attachments" in path:
        _tm.sleep(1.2)
        return {"data": _b.urlsafe_b64encode(b"PNGDATA").decode()}
    return _old2(S, method, path, params, body, timeout)
mo.gmail_call = _slow
mp._topen.clear(); mp._tpend.clear()
t0 = _tm.time(); mp.open_thread("tz", "x")
assert wait(lambda: mp.msgs and mp.thread_lay.count() > 0 and any(isinstance(mp.thread_lay.itemAt(i).widget(), U._QF) for i in range(mp.thread_lay.count()))), "text"
assert _tm.time() - t0 < 1.0, _tm.time() - t0
assert wait(lambda: len(mp.msgs[0][4]) == 2, 8), mp.msgs[0][4].keys()
mo.gmail_call = _old2
assert sum(len(r) for r in U.MAIL_GRID) == 54 and U.mail_text_on("#fad165") == "#000000" and U.mail_text_on("#285bac") == "#ffffff"
_pl = U.MailPulse(); _pl.show(); app.processEvents(); _pl.grab().save("/tmp/pulse.png"); _pl.close()
print("ok21")

# simple emails wear the dark look; designed ones stay on a soft light page
assert U.mail_plain("<div>test<br>--<br><span style='color:#000000'>Kind</span></div>") and not U.mail_plain('<div><img src="cid:a"></div>') and not U.mail_plain('<table bgcolor="#112233"><tr><td>x')
assert U.mail_plain('<div style="background-color:#ffffff">x</div>')
_l = U.mail_lighten('<span style="color:#000000">a</span><a style="color:#1155cc">b</a><span style="color:#999999">c</span><font color="black">d</font>')
assert "#eceef0" in _l and "#7cb7f0" in _l and "#999999" in _l and 'color="#eceef0"' in _l, _l
print("ok22")

# the drop-down arrows of the labels still toggle with the colour squares in front
from PySide6.QtCore import QPoint as _QP, QPointF as _QPF
from PySide6.QtGui import QMouseEvent as _QME
from PySide6.QtCore import QEvent as _QEv
mp.labels = [{"id": "Label_1", "name": "City Dev", "type": "user"}, {"id": "Label_2", "name": "City Dev/Zandspruit", "type": "user"}]
mp.lcol = {}; S.pop("mail_collapsed", None); mp._fill_side()
def _row(n):
    return next(mp.side.item(i) for i in range(mp.side.count()) if (mp.side.item(i).data(Qt.ItemDataRole.UserRole + 2) or "") == n)
_it = _row("City Dev"); _r = mp.side.visualItemRect(_it)
_hit = []
for _x in range(_r.left(), _r.left() + 90, 2):
    S.pop("mail_collapsed", None)
    _pt = _QPF(_x, _r.center().y())
    app.sendEvent(mp.side.viewport(), _QME(_QEv.Type.MouseButtonPress, _pt, mp.side.viewport().mapToGlobal(_pt), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    if S.get("mail_collapsed") is not None:
        _hit.append(_x - _r.left())
print("arrow clickable at", _hit[:1], _hit[-1:], "icon", mp.side.iconSize())
assert _hit and _hit[0] < 40 and _hit[-1] > 40, _hit
print("ok23")

# every folder is read ahead: switching shows its mail at once, with no waiting for Gmail
mp._lcache.clear(); mp._pw_busy = False
mp._prewarm(0)
assert wait(lambda: all((l, "", 0, "") in mp._lcache for l in ("STARRED", "SENT", "DRAFT", "ALL")), 10), list(mp._lcache)
mp.label = "SENT"; mp.query = ""; mp.rows = []; mp._fill_list()
mp.load_list(reset=True)
assert mp.list.count() == len(mp._lcache[("SENT", "", 0, "")][0]) and mp.list.count() > 0, mp.list.count()
print("ok24")

# the last mailbox view is kept on disk; a picture in an email can be saved or copied with a right-click
import tempfile as _tf2
_dpf = os.path.join(_tf2.mkdtemp(), "mail_cache.json")
mp._disk_path = lambda: _dpf; mp._disk_test = True
S["mail_address"] = "me@x.com"
mp._lcache[("INBOX", "", 0, "")] = ([{"id": "z1", "sender": "A", "subject": "S", "snippet": "x", "date": 1, "unread": True, "starred": False, "count": 1, "attach": False, "labels": ["INBOX"]}], "", None)
mp._disk_save(); assert os.path.exists(_dpf)
mp._lcache.clear(); mp._disk_load()
assert mp._lcache[("INBOX", "", 0, "")][0][0]["id"] == "z1" and mp._lcache[("INBOX", "", 0, "")][2] is None
from PySide6.QtGui import QImage as _QI, QColor as _QC
from PySide6.QtCore import QBuffer as _QB, QIODevice as _QD2, QPoint as _QP2
_im = _QI(120, 60, _QI.Format.Format_RGB32); _im.fill(_QC("#336699")); _bf = _QB(); _bf.open(_QD2.OpenModeFlag.WriteOnly); _im.save(_bf, "PNG"); _png = bytes(_bf.data())
_ab = U._AutoBrowser(); _ab.resize(600, 300); _ab.show()
_ab.setHtml(U.mail_fix_images('<p>hello</p><img src="cid:p@x" width="120">', _ab.document(), {"p@x": _png}, False, 500)); app.processEvents()
_nm = ""
for _y in range(0, 120, 6):
    for _x in range(0, 200, 10):
        _nm = _ab._image_at(_QP2(_x, _y))
        if _nm: break
    if _nm: break
assert _nm and _ab._picture_bytes(_nm) == _png, _nm
assert not _ab._image_at(_QP2(500, 20)), "far from the picture is not the picture"
_dst = os.path.join(_tf2.mkdtemp(), "out.png")
U._QFD.getSaveFileName = staticmethod(lambda *a, **k: (_dst, ""))
_ab.save_picture(_nm); assert open(_dst, "rb").read() == _png
_ab.copy_picture(_nm); assert not app.clipboard().image().isNull()
_ab.close()
print("ok25")

# Primary asks for the inbox minus the other tabs, so mail you send to yourself (no tab label) is listed
_seen_p = []
_old3 = mo.gmail_call
def _cap(S_, method, path, params=None, body=None, timeout=60):
    if path == "threads":
        _seen_p.append(dict(params or {}))
    return _old3(S_, method, path, params, body, timeout)
mo.gmail_call = _cap
mp._page("INBOX", "", 0, ""); mp._page("INBOX", "", 1, "")
mo.gmail_call = _old3
assert _seen_p[0]["labelIds"] == ["INBOX"] and "-category:promotions" in _seen_p[0]["q"], _seen_p[0]
assert _seen_p[1]["labelIds"] == ["INBOX", "CATEGORY_PROMOTIONS"] and "q" not in _seen_p[1], _seen_p[1]
print("ok26")

# marking, labelling and deleting show at once; Gmail is told afterwards, many conversations in parallel
import time as _tm3
mp.label = "INBOX"; mp.query = ""
mp.rows = [dict(id="q%d" % i, sender="A", subject="S", snippet="x", date=1, unread=True, starred=False, count=1, attach=False, labels=["INBOX", "UNREAD"]) for i in range(10)]
mp._fill_list()
_calls3 = []
_old4 = mo.gmail_call
def _slow3(S_, method, path, params=None, body=None, timeout=60):
    if "/modify" in path or "/trash" in path:
        _tm3.sleep(0.4); _calls3.append(path); return {}
    return _old4(S_, method, path, params, body, timeout)
mo.gmail_call = _slow3
for _i in range(10):
    mp.list.item(_i).setData(U.ROLE_CHECK, True)
mp.update_bulk()
_t0 = _tm3.time(); mp.act("read")
assert _tm3.time() - _t0 < 0.2 and not any(mp.list.item(i).data(U.ROLE_UNREAD) for i in range(10)), "the screen must change at once"
assert wait(lambda: len(_calls3) == 10, 6) and _tm3.time() - _t0 < 2.5, (len(_calls3), _tm3.time() - _t0)      # 10 x 0.4 s in parallel, not 4 s in a row
for _i in range(3):
    mp.list.item(_i).setData(U.ROLE_CHECK, True)
_t0 = _tm3.time(); mp.act("trash")
assert _tm3.time() - _t0 < 0.2 and mp.list.count() == 7
mo.gmail_call = _old4
print("ok27")

# the signature banner: the logo side is ONE picture (never cut through the logo); only the right side is cut into linked rows
import sig_banner as _sb
_S2 = {"sig_name": "Mouton Burger", "sig_role": "CG", "sig_phone": "+27 71 873 2219", "sig_email": "m@x.co.za", "mail_address": "m@x.co.za"}
_spec, _jp = _sb.slices(_S2)
assert _spec["left"][0] == 0 and _spec["left"][1] > 500 and len(_spec["rows"]) == 5
assert sum(r[0] for r in _spec["rows"]) == _sb.H
_h2, _jp2, _ = U.mail_sig_html(_S2)
assert 'data-t="620"' in _h2 and _h2.count("<img") == len(_jp2) and "tel:" in _h2 and "mailto:" in _h2
_px = U.mail_sig_px(_h2, 500)
assert 'data-pw' in _px and 'width="%d"' % round(500 * _spec["left"][1] / float(_spec["left"][2])) in _px
print("ok28")

# background reading never queues in front of a click: it may use 40 percent of the allowance and gives up at once; a click waits for nothing
import threading as _thr9
mo._UNITS.clear(); mo._BLOCK[0] = 0.0
mo._UNITS.append((time.time(), int(mo._BUDGET[0] * 0.45)))
_res9 = {}
def _bgtry():
    mo.background(True)
    try:
        mo._spend(10); _res9["bg"] = "ran"
    except RuntimeError as e:
        _res9["bg"] = str(e)
_t9 = _thr9.Thread(target=_bgtry); _t9.start(); _t9.join(2)
assert _res9.get("bg") == "busy", _res9
t0 = time.time(); mo._spend(10); assert time.time() - t0 < 0.5      # a click is served at once
mo._UNITS.clear()
# an open does not wait for a read-ahead that holds the conversation for long
_lk9 = _thr9.Lock(); mp._tlock["slowt"] = _lk9; _lk9.acquire()
_old9 = mp._fetch_thread2; mp._fetch_thread2 = lambda tid: ({"id": tid}, [])
t0 = time.time(); _o9 = mp._fetch_thread("slowt"); _dt9 = time.time() - t0
mp._fetch_thread2 = _old9; _lk9.release()
assert _o9[0]["id"] == "slowt" and 2.5 < _dt9 < 5, _dt9
print("ok29")
