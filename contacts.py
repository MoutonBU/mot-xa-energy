"""Gmail contacts for the To / Cc boxes: type a few letters of a name and pick the address.
The list comes from the signed-in Google account (People API: saved contacts and people you have emailed) and is kept in a small
file next to the program settings, so the boxes complete instantly and also work offline."""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QCompleter

import mail_oauth

SCOPES = "https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/contacts.other.readonly"
CONNECTIONS = "https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses&pageSize=1000"
OTHER = "https://people.googleapis.com/v1/otherContacts?readMask=names,emailAddresses&pageSize=1000"
MAX_AGE = 12 * 3600


class ContactsError(Exception):
    def __init__(self, msg, need_signin=False):
        super().__init__(msg)
        self.need_signin = need_signin


def _get(url, token):
    import urllib.error
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
            msg = err.get("message") or str(e)
            status = err.get("status", "")
        except Exception:
            msg, status = str(e), ""
        scope = e.code in (401, 403) and bool(re.search(r"scope|insufficient|permission|PERMISSION_DENIED|UNAUTHENTICATED", msg + status, re.I))
        if e.code == 403 and re.search(r"has not been used|disabled|SERVICE_DISABLED", msg + status, re.I):
            scope = False
            msg = "the People API is not switched on yet for the program (%s)" % msg
        raise ContactsError(msg, need_signin=scope)


def _parse(people):
    out = []
    for p in people or []:
        nm = ((p.get("names") or [{}])[0].get("displayName") or "").strip()
        for em in p.get("emailAddresses") or []:
            ad = (em.get("value") or "").strip()
            if ad:
                out.append((nm, ad))
    return out


def fetch(S, getter=_get):
    """[(name, email)] from the signed-in Google account. Raises if the account has not allowed contacts yet."""
    try:
        tok = mail_oauth.access_token(S, "gmail")
    except Exception as e:
        raise ContactsError(str(e), need_signin=True)
    items = []
    for base, key in ((CONNECTIONS, "connections"), (OTHER, "otherContacts")):
        page = ""
        for _ in range(40):
            d = getter(base + (("&pageToken=" + urllib.parse.quote(page)) if page else ""), tok)
            items += _parse(d.get(key))
            page = d.get("nextPageToken") or ""
            if not page:
                break
    seen, out = set(), []
    for nm, ad in items:
        k = ad.lower()
        if k not in seen:
            seen.add(k)
            out.append((nm, ad))
    out.sort(key=lambda x: (x[0] or x[1]).lower())
    return out


def label(nm, ad):
    return "%s <%s>" % (nm, ad) if nm else ad


def cache_path(M):
    return os.path.join(os.path.dirname(getattr(M, "SETTINGS_PATH", "") or os.path.expanduser("~/x")), "gmail_contacts.json")


def load(M):
    try:
        with open(cache_path(M), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("time", 0), [tuple(x) for x in d.get("items", [])]
    except Exception:
        return 0, []


def save(M, items):
    try:
        os.makedirs(os.path.dirname(cache_path(M)), exist_ok=True)
        with open(cache_path(M), "w", encoding="utf-8") as f:
            json.dump({"time": time.time(), "items": items}, f)
    except Exception:
        pass


class ContactCompleter(QCompleter):
    """Completes the address being typed after the last comma or semicolon."""

    show_all = False

    def splitPath(self, path):
        if self.show_all:
            return [""]
        return [re.split(r"[;,]", path)[-1].strip()]

    def pathFromIndex(self, index):
        txt = index.data() or ""
        m = re.search(r"<([^>]+)>", txt)
        w = self.widget()
        cur = w.text() if w is not None else ""
        cut = max(cur.rfind(","), cur.rfind(";")) + 1
        head = cur[:cut].rstrip() + " " if cut else ""
        return head + (m.group(1) if m else txt)


class _Bus(QObject):
    loaded = Signal(list)
    finished = Signal(str, bool, bool)     # message, ok, need_signin


_state = {"bus": None, "model": None, "busy": False, "google": [], "local": []}


def model():
    from PySide6.QtCore import QStringListModel
    if _state["model"] is None:
        _state["model"] = QStringListModel()
        _state["bus"] = _Bus()
        _state["bus"].loaded.connect(_set_google)
    return _state["model"]


def _push():
    seen, out = set(), []
    for n, a in list(_state["google"]) + list(_state["local"]):
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(label(n, a))
    _state["model"].setStringList(out)


def _set_google(items):
    _state["google"] = list(items)
    _push()


def set_local(items):
    """Addresses already used in this register (clients, copies, emails received and sent): [(name, email)]."""
    model()
    _state["local"] = [(n, a) for n, a in items if a and "@" in a]
    _push()


def count():
    return len(_state["google"])


def attach(line_edit, get_M):
    """Give a QLineEdit the contact autocomplete. get_M() returns the settings module (called lazily)."""
    m = model()
    if not _state["google"]:
        try:
            _t, items = load(get_M())
            _set_google(items)
        except Exception:
            pass
    c = ContactCompleter(m, line_edit)
    c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    c.setFilterMode(Qt.MatchFlag.MatchContains)
    c.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    c.setMaxVisibleItems(12)
    line_edit.setCompleter(c)
    line_edit._contact_completer = c
    _dropdown(line_edit, c)


def _dropdown(le, c):
    """A small arrow at the right of the box (and a click in an empty box) shows the whole contact list."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QStyle

    def show_all():
        c.show_all = True
        c.setCompletionPrefix("")
        c.complete()

    act = QAction(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown), "Show my contacts", le)
    act.setToolTip("Show my contacts")
    act.triggered.connect(show_all)
    le.addAction(act, le.ActionPosition.TrailingPosition)
    c.activated.connect(lambda *_: setattr(c, "show_all", False))
    le.textEdited.connect(lambda *_: setattr(c, "show_all", False))

    class _F(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.MouseButtonPress and not le.text().strip():
                QTimer.singleShot(0, show_all)
            return False
    f = _F(le)
    le.installEventFilter(f)
    le._contact_filter = f


def refresh_async(M, force=False, report=False):
    """Fetch the contact list in the background when signed in with Google (at most every 12 hours unless forced)."""
    S = M.SETTINGS
    if _state["busy"]:
        return
    if S.get("mail_provider") != "gmail" or not mail_oauth.signed_in(S, "gmail"):
        model()
        if report:
            _state["bus"].finished.emit("You are not signed in with Google yet.", False, True)
        return
    t, items = load(M)
    model()
    if not force and items and time.time() - t < MAX_AGE:
        _state["bus"].loaded.emit(items)
        if report:
            _state["bus"].finished.emit("%d contacts are ready." % len(items), True, False)
        return
    _state["busy"] = True

    def work():
        try:
            got = fetch(S)
            save(M, got)
            S["contacts_note"] = ""
            _state["bus"].loaded.emit(got)
            if report:
                _state["bus"].finished.emit("Loaded %d contacts from your Gmail account." % len(got), True, False)
        except Exception as e:
            need = bool(getattr(e, "need_signin", False))
            S["contacts_note"] = "contacts" if need else ""
            S["contacts_error"] = str(e)
            if report:
                _state["bus"].finished.emit("Google said: %s" % e, False, need)
        finally:
            _state["busy"] = False
    threading.Thread(target=work, daemon=True).start()
