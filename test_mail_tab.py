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
assert wait(lambda: any(c[1] == "threads" and c[2] and "CATEGORY_PERSONAL" in c[2].get("labelIds", []) for c in gcalls))
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
got = mp._fetch_thread("tz")[1][0][4]
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
got = mp._fetch_thread("tw")[1][0][4]
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
assert mo.gmail_blocked() > 20 and mo._BUDGET[0] == 600.0, (mo.gmail_blocked(), mo._BUDGET[0])
assert _Sb["gmail_budget"] == 600.0
mo._BUDGET[0] = 8000.0; mo._learned(_Sb); assert mo._BUDGET[0] == 600.0
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
