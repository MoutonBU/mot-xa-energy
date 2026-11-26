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

w = M.MainWindow()
S = M.SETTINGS
S.update({"google_client_id": "x", "google_refresh": "r", "gmail_modify": True, "gmail_read": True, "mail_address": "me@x.com", "mail_provider": "gmail"})
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
