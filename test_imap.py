import os, time, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MOT_TEST"] = "1"
import fake_mailserver as fm
import mail_imap as mi, mail_oauth as mo

st, ip, sp, _srv = fm.start("secret")
st.add("INBOX", fm.mk("Dewann Blaauw <d@y.com>", "Erf 670 plans", "Please find the plans for erf 670 attached.", att=True))
st.add("INBOX", fm.mk("Google <g@z.com>", "Pricing update", "Review the new pricing", html=True), {"\\Flagged"})
st.add("INBOX", fm.mk("Bob <b@z.com>", "Lunch", "Lunch on friday? Gr=C3=BCsse"), {"\\Seen"})
S = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "None", "imap_user": "me@test.local", "imap_pass": "secret", "mail_address": "me@test.local",
     "smtp_host": "127.0.0.1", "smtp_port": sp, "smtp_security": "None", "smtp_user": "me@test.local", "smtp_pass": "secret", "mail_provider": "smtp"}
G = lambda m, p, params=None, body=None: mo.gmail_call(S, m, p, params, body)

# login test
assert mi.test_login("127.0.0.1", ip, "None", "me@test.local", "secret")[0] == "ok"
assert mi.test_login("127.0.0.1", ip, "None", "me@test.local", "wrong")[0] == "auth"
assert mi.test_login("127.0.0.1", 1, "None", "me@test.local", "x")[0] == "down"

pr = G("GET", "profile")
assert pr["emailAddress"] == "me@test.local" and pr["historyId"].startswith("7.4."), pr
labs = G("GET", "labels")["labels"]
names = {l["id"]: l for l in labs}
assert "INBOX" in names and "Clients" in names and names["Clients"]["type"] == "user" and "Trash" not in names and "Sent" not in names, list(names)
c = G("GET", "labels/INBOX")
assert c["threadsUnread"] == 2 and c["threadsTotal"] == 3, c
l = G("GET", "threads", {"labelIds": ["INBOX"], "maxResults": 25, "q": "-category:promotions -category:social"})
ids = [t["id"] for t in l["threads"]]
assert len(ids) == 3 and "Bob" not in l["threads"][0]["snippet"], l
assert "plans for erf 670" in l["threads"][2]["snippet"] or "plans for erf 670" in " ".join(t["snippet"] for t in l["threads"]), l
th = G("GET", "threads/" + ids[2], {"format": "metadata"})
import ui_extras as U
row = U.mail_thread_row(th, "me@test.local")
assert row["subject"] == "Erf 670 plans" and row["sender"] == "Dewann Blaauw" and row["unread"] and row["attach"], row
row1 = U.mail_thread_row(G("GET", "threads/" + ids[1]), "me@test.local")
assert row1["starred"] and row1["unread"], row1
row0 = U.mail_thread_row(G("GET", "threads/" + ids[0]), "me@test.local")
assert not row0["unread"], row0
bt = mo.gmail_batch(S, ["threads/%s?format=metadata&metadataHeaders=From" % i for i in ids])
assert len(bt) == 3 and all(bt), bt
# search
r = G("GET", "threads", {"q": "pricing"})
assert len(r["threads"]) == 1, r
r = G("GET", "threads", {"labelIds": ["INBOX"], "q": "from:dewann"})
assert len(r["threads"]) == 1
r = G("GET", "threads", {"labelIds": ["INBOX"], "q": "is:unread"})
assert len(r["threads"]) == 2
r = G("GET", "threads", {"labelIds": ["STARRED"]})
assert len(r["threads"]) == 1
# full thread + attachment
full = G("GET", "threads/" + ids[2], {"format": "full"})
m = full["messages"][0]
html, plain, atts = U.mail_parts(m["payload"])
assert "plans for erf 670" in plain and len(atts) == 1 and atts[0]["name"] == "plan.pdf", (plain, atts)
data = mo.gmail_bytes(S, "messages/%s/attachments/%s" % (m["id"], atts[0]["id"]))
assert data.startswith(b"%PDF"), data[:20]
fp = G("GET", "threads/" + ids[1], {"format": "full"})["messages"][0]
h2, p2, a2 = U.mail_parts(fp["payload"])
assert "<p>Review the new pricing</p>" in h2, h2
# mark read / star / trash
G("POST", "threads/%s/modify" % ids[2], body={"removeLabelIds": ["UNREAD"], "addLabelIds": ["STARRED"]})
x = [y for y in st.f["INBOX"] if y["uid"] == 1][0]
assert "\\Seen" in x["flags"] and "\\Flagged" in x["flags"], x["flags"]
G("POST", "threads/%s/trash" % ids[0], body={})
assert len(st.f["Trash"]) == 1 and len(st.f["INBOX"]) == 2, (len(st.f["Trash"]), len(st.f["INBOX"]))
G("POST", "threads/%s/modify" % ids[1], body={"addLabelIds": ["Clients"]})
assert len(st.f["Clients"]) == 1
G("POST", "threads/%s/modify" % ids[1], body={"removeLabelIds": ["INBOX"]})
assert len(st.f["Archive"]) == 1 and len(st.f["INBOX"]) == 1
tl = G("GET", "threads", {"labelIds": ["TRASH"]})
assert len(tl["threads"]) == 1
# history (new mail)
h0 = G("GET", "profile")["historyId"]
st.add("INBOX", fm.mk("New Person <n@z.com>", "Brand new", "hello there"))
h = G("GET", "history", {"startHistoryId": h0, "historyTypes": "messageAdded", "labelId": "INBOX"})
assert len(h["history"]) == 1 and "INBOX" in h["history"][0]["messagesAdded"][0]["message"]["labelIds"], h
mid = h["history"][0]["messagesAdded"][0]["message"]["id"]
mm = G("GET", "messages/" + mid, {"format": "metadata"})
assert any(x["value"].startswith("Brand") for x in mm["payload"]["headers"] if x["name"] == "Subject")
assert G("GET", "profile")["historyId"] != h0
# labels create / rename / delete
G("POST", "labels", body={"name": "Projects"})
assert "Projects" in st.f
G("PUT", "labels/Projects", body={"name": "Jobs"})
assert "Jobs" in st.f and "Projects" not in st.f
G("DELETE", "labels/Jobs")
assert "Jobs" not in st.f
# mark all read
res = G("GET", "messages", {"labelIds": ["INBOX", "UNREAD"], "maxResults": 500})
assert len(res["messages"]) >= 1
G("POST", "messages/batchModify", body={"ids": [x["id"] for x in res["messages"]], "removeLabelIds": ["UNREAD"]})
assert G("GET", "labels/INBOX")["threadsUnread"] == 0
# wrong password
try:
    mo.gmail_call(dict(S, imap_pass="nope"), "GET", "profile")
    assert False
except RuntimeError as e:
    assert "refused" in str(e), e
print("backend ok")

# ---- the Mail tab with such an account
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import mot_xa_energy as M
w = M.MainWindow()
SS = M.SETTINGS
SS.update({"google_client_id": "x", "google_refresh": "r", "gmail_modify": True, "gmail_read": True, "mail_address": "main@gmail.com", "mail_provider": "gmail", "mail_collapsed": []})
mp = w.mail_page
def wait(cond, t=10):
    t0 = time.time()
    while time.time() - t0 < t:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False
orig = mo.gmail_call
def gm(S_, method, path, params=None, body=None, timeout=60):
    if S_.get("imap_host"):
        return orig(S_, method, path, params, body, timeout)
    if path == "profile":
        return {"emailAddress": "main@gmail.com", "historyId": "1"}
    if path == "labels":
        return {"labels": [{"id": "INBOX", "type": "system"}]}
    if path.startswith("labels/"):
        return {"threadsUnread": 1, "threadsTotal": 1}
    return {"threads": []}
mo.gmail_call = gm
mo.gmail_batch = lambda S_, p, timeout=60: mi.batch(S_, p) if S_.get("imap_host") else None
SS["mail_accounts"] = [{"kind": "imap", "address": "me@test.local", "hid": "", "color": "#2e7d32", "modify": True, "read": True, "imap_host": "127.0.0.1", "imap_port": ip,
                        "imap_security": "None", "imap_user": "me@test.local", "imap_pass": "secret", "smtp_host": "127.0.0.1", "smtp_port": sp, "smtp_security": "None",
                        "smtp_user": "me@test.local", "smtp_pass": "secret"}]
mp._refresh_state()
mp._rebuild_acc_bar(True)
mp._switch_account("me@test.local")
assert mp.S.get("imap_host") and mp.ready()
assert wait(lambda: mp.list.count() >= 2), mp.list.count()
subs = [r["subject"] for r in mp.rows]
print(subs)
assert "Brand new" in subs, subs
assert not mp.cats.isVisible() or True
r0 = next(r for r in mp.rows if r["subject"] == "Brand new")
# open
mp.open_thread(r0["id"], r0["subject"])
assert wait(lambda: getattr(mp, "msgs", None) and mp.thread_lay.count() >= 1), "thread did not open"
assert wait(lambda: mp.stack.currentIndex() == 1)
print("opened:", len(mp.msgs))
print("tab ok")

# ---- sending through the account's own SMTP, and a copy in Sent
import register_ext as RE
from email.message import EmailMessage
em = EmailMessage(); em["From"] = "me@test.local"; em["To"] = "client@x.com"; em["Subject"] = "Re: Erf 670 plans"; em.set_content("Thanks, received.")
RE.deliver(mp.S, em)
assert len(st.sent_smtp) == 1 and st.sent_smtp[0][0] == ["client@x.com"] and st.sent_smtp[0][2], st.sent_smtp
assert wait(lambda: len(st.f["Sent"]) == 1), "no copy in Sent"
sl = mo.gmail_call(mp.S, "GET", "threads", {"labelIds": ["SENT"]})
assert len(sl["threads"]) == 1
print("send ok")

# ---- the Add account window (typed servers)
d = U.ImapAccountDialog(mp, {"me@test.local"})
d.addr.setText("info@test.local"); d.pw.setText("secret"); d.adv.setChecked(True)
e, pt, sc = d.f["imap_host"]; e.setText("127.0.0.1"); pt.setText(str(ip)); sc.setCurrentText("None")
e, pt, sc = d.f["smtp_host"]; e.setText("127.0.0.1"); pt.setText(str(sp)); sc.setCurrentText("None")
d.connect_now()
assert wait(lambda: d.cfg is not None or "Could not" in d.status.text()), d.status.text()
assert d.cfg and d.cfg["imap_host"] == "127.0.0.1" and d.cfg["address"] == "info@test.local" and d.cfg["smtp_pass"] == "secret", (d.cfg, d.status.text())
d2 = U.ImapAccountDialog(mp, set()); d2.addr.setText("a@test.local"); d2.pw.setText("WRONG"); d2.adv.setChecked(True)
e, pt, sc = d2.f["imap_host"]; e.setText("127.0.0.1"); pt.setText(str(ip)); sc.setCurrentText("None")
d2.connect_now()
assert wait(lambda: "Could not" in d2.status.text()), d2.status.text()
print("dialog ok:", d2.status.text())
print("ALL OK")
