"""The Projects board against a small pretend Supabase on this computer: sign-in, members, live changes between two people, drag between columns."""
import json, os, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = {"members": [{"email": "a@x.com", "name": "Ann", "role": "admin", "added_at": "2026-01-01"}, {"email": "b@x.com", "name": "Bob", "role": "member", "added_at": "2026-01-02"}],
      "projects": []}
USERS = {"a@x.com": "pw-a-1", "b@x.com": "pw-b-1"}
CLOCK = [0]


def now():
    CLOCK[0] += 1
    return "2026-11-27T10:00:%02d.%06d+00:00" % (CLOCK[0] // 1000000 % 60, CLOCK[0] % 1000000)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _who(self):
        a = self.headers.get("Authorization", "")
        return a[7:].split("tok-")[-1] if a.startswith("Bearer tok-") else None

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_POST(self):
        u = urlparse(self.path)
        b = self._body()
        if u.path == "/auth/v1/token":
            q = parse_qs(u.query)
            if q["grant_type"][0] == "password":
                if USERS.get(b["email"]) != b["password"]:
                    return self._send(400, {"error_description": "Invalid login credentials"})
                em = b["email"]
            else:
                em = b["refresh_token"].replace("ref-", "")
            return self._send(200, {"access_token": "tok-" + em, "refresh_token": "ref-" + em, "expires_in": 3600, "user": {"email": em}})
        if u.path == "/auth/v1/signup":
            return self._send(200, {"user": {"email": b["email"]}})
        em = self._who()
        if not em:
            return self._send(401, {"message": "no"})
        if u.path == "/rest/v1/board_projects":
            r = dict(b, id=str(uuid.uuid4()), deleted=False, created_at=now(), updated_at=now(), created_by=em, updated_by=em)
            r.setdefault("status", "todo")
            r.setdefault("priority", "normal")
            DB["projects"].append(r)
            return self._send(201, [r])
        if u.path == "/rest/v1/board_members":
            DB["members"].append(dict(b, added_at=now()))
            return self._send(201, None)

    def do_PATCH(self):
        em = self._who()
        q = parse_qs(urlparse(self.path).query)
        pid = q["id"][0][3:]
        for r in DB["projects"]:
            if r["id"] == pid:
                r.update(self._body())
                r["updated_at"], r["updated_by"] = now(), em
                return self._send(200, [r])
        self._send(200, [])

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._who():
            return self._send(401, {"message": "no"})
        if u.path.endswith("board_members"):
            return self._send(200, DB["members"])
        rows = DB["projects"]
        if "updated_at" in q:
            rows = [r for r in rows if r["updated_at"] >= q["updated_at"][0][4:]]
        self._send(200, rows)

    def do_DELETE(self):
        q = parse_qs(urlparse(self.path).query)
        em = q["email"][0][3:]
        DB["members"] = [m for m in DB["members"] if m["email"] != em]
        self._send(204, None)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % srv.server_port

from PySide6.QtWidgets import QApplication, QWidget
app = QApplication.instance() or QApplication([])
import ui_extras as B


def wait(cond, t=5):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


class Tabs:
    def setCurrentIndex(self, i): pass
    def setCurrentWidget(self, w): pass


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.main_tabs, self.launcher_idx, self.msgs = Tabs(), [0], []
    def toast(self, text, *a): self.msgs.append(text)


# the connection itself
GA, GB = {"board_url": URL}, {"board_url": URL}
A, Bo = B.BoardAPI(GA), B.BoardAPI(GB)
try:
    A.sign_in("a@x.com", "wrong")
    raise SystemExit("a wrong password must fail")
except B.BoardError as e:
    assert "Invalid" in str(e)
A.sign_in("a@x.com", "pw-a-1")
assert A.me() == "a@x.com" and A.signed_in()
assert B.BoardAPI(GB).sign_up("c@x.com", "secret1") is False           # needs the confirmation email
print("ok1")

# two people, two pages
ha, hb = Host(), Host()
pa = B.BoardPage(ha, GA, lambda: False, lambda: sys.modules[__name__])
pb = B.BoardPage(hb, GB, lambda: False, lambda: sys.modules[__name__])
save = lambda: None
sys.modules[__name__].save_settings = save
Bo.sign_in("b@x.com", "pw-b-1")
pa.timer.setInterval(100)
pb.timer.setInterval(100)
pa.show(); pb.show()
assert wait(lambda: pa.stack.currentIndex() == 1 and pb.stack.currentIndex() == 1, 6), "both pages open the board"
assert pa.is_admin and not pb.is_admin and pa.team_btn.isVisibleTo(pa) and not pb.team_btn.isVisibleTo(pb)
print("ok2")

# Ann adds a project: it shows on Bob's side, with a pop-up
pa._create({"title": "Lodge plans for Erf 14243", "owner": "b@x.com", "priority": "high", "due": "2026-12-01"})
assert wait(lambda: pb.cols["todo"].count() == 1 and pa.cols["todo"].count() == 1, 6)
assert wait(lambda: any("Ann gave you" in m for m in hb.msgs), 6), hb.msgs
assert not any("added" in m for m in ha.msgs)                              # you are not told about your own change
print("ok3")

# Bob moves it (as a drop in the Done column): Ann sees it move
rid = pb.cols["todo"].item(0).data(B.BROLE)["id"]
pb.cols["done"].dropped.emit(rid, "done")
assert pb.cols["done"].count() == 1 and pb.cols["todo"].count() == 0       # at once on his own screen
assert wait(lambda: pa.cols["done"].count() == 1 and pa.cols["todo"].count() == 0, 6)
assert wait(lambda: any("Bob finished" in m for m in ha.msgs), 6), ha.msgs
print("ok4")

# delete is for everybody
pa._apply(rid, {"deleted": True})
assert wait(lambda: pb.cols["done"].count() == 0, 6)
# the search and "only mine"
pa._create({"title": "Sewer line", "owner": "a@x.com"}); pa._create({"title": "Roof", "owner": "b@x.com"})
assert wait(lambda: pa.cols["todo"].count() == 2, 6)
pa.search.setText("sew"); assert pa.cols["todo"].count() == 1
pa.search.setText(""); pa.mine.setChecked(True); assert pa.cols["todo"].count() == 1
print("ok5")

# the admin adds and removes people
done = []
pa.run(lambda: pa.api.add_member("d@x.com", "Dee", "member"), lambda r, e: done.append(e))
assert wait(lambda: done, 4) and done[0] is None and any(m["email"] == "d@x.com" for m in DB["members"])
pa.run(lambda: pa.api.remove_member("d@x.com"), lambda r, e: done.append(e))
assert wait(lambda: len(done) == 2, 4) and not any(m["email"] == "d@x.com" for m in DB["members"])
# signing out
pb._sign_out(); assert pb.stack.currentIndex() == 0 and not GB.get("board_session")
print("ok6")

# to-dos inside a project, nested
pa.mine.setChecked(False); pa.search.setText("")
pa._create({"title": "Ground floor electrical", "priority": "normal"})
assert wait(lambda: any(r["title"] == "Ground floor electrical" for r in pa.rows.values()), 4)
pj = [r for r in pa.rows.values() if r["title"] == "Ground floor electrical"][0]
dlg = B.ProjectDialog(pa, pj)
dlg.addbox.setText("Plug layout"); dlg._tadd()
assert wait(lambda: dlg.tree.topLevelItemCount() == 1, 4)
top = dlg.tree.topLevelItem(0)
dlg.tree.setCurrentItem(top)
dlg.addbox.setText("Kitchen plugs"); dlg._tadd()
assert wait(lambda: dlg.tree.topLevelItem(0).childCount() == 1, 4)
kid = dlg.tree.topLevelItem(0).child(0)
kid.setCheckState(0, B.Qt.CheckState.Checked)
assert wait(lambda: B.board_progress(pa.rows, pj["id"]) == (1, 1), 4), B.board_progress(pa.rows, pj["id"])
assert wait(lambda: any(r["title"] == "Kitchen plugs" and r["status"] == "done" for r in DB["projects"]), 6)   # it reached the shared database
assert pa.cols["todo"].count() == 3                                  # the to-dos are not cards on the board
if os.environ.get("DLG_SHOT"):
    dlg.show(); app.processEvents(); dlg.grab().save(os.environ["DLG_SHOT"])
dlg._unhook(); dlg.reject()
print("ok7")

# the to-dos open on the card itself
from PySide6.QtCore import QPoint
col = pa.cols["todo"]
pa.open_ids.clear(); pa.render()
ix = [i for i in range(col.count()) if col.item(i).data(B.BROLE)["id"] == pj["id"]][0]
rect = col.visualItemRect(col.item(ix))
card, y0 = pa.delegate.geometry(rect)
col.mousePressEvent(__import__("PySide6.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(B.QEvent.Type.MouseButtonPress, B.QPointF(card.right() - 20, card.top() + 20), B.Qt.MouseButton.LeftButton, B.Qt.MouseButton.LeftButton, B.Qt.KeyboardModifier.NoModifier))
assert pj["id"] in pa.open_ids and col.visualItemRect(col.item(ix)).height() > pa.delegate.H
h = col._hit(B.QPointF(card.left() + 80, y0 + 5).toPoint() if False else QPoint(int(card.left() + 17), int(col.visualItemRect(col.item(ix)).top() + 3 + pa.delegate.H - 6 + 4 + 5)))
assert h and h[0] == "open", h                                            # the first to-do has sub-to-dos
pa.todo_toggle(h[1]); assert wait(lambda: pa.rows[h[1]]["status"] == "done", 4)
pa._apply(h[1], {"priority": "urgent"}); assert pa.rows[h[1]]["priority"] == "urgent"
print("ok8")
if os.environ.get("CARD_SHOT"):
    pa.open_ids.add(h[1]); pa.render(); pa.resize(1300, 700); app.processEvents(); pa.grab().save(os.environ["CARD_SHOT"])

# a picture of it
if os.environ.get("BOARD_SHOT"):
    pa.mine.setChecked(False)
    pa._create({"title": "Submit building plans to council", "client": "Erf 14243", "owner": "b@x.com", "priority": "urgent", "due": "2026-11-01"})
    pa._create({"title": "Sewer line layout", "client": "Block A", "owner": "a@x.com", "priority": "normal", "status": "doing"})
    wait(lambda: pa.cols["doing"].count() == 1, 4)
    pa.resize(1300, 700); app.processEvents(); pa.grab().save(os.environ["BOARD_SHOT"])
