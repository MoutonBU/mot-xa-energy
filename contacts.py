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

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QCompleter

import mail_oauth

SCOPES = "https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/contacts.other.readonly"
CONNECTIONS = "https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses&pageSize=1000"
OTHER = "https://people.googleapis.com/v1/otherContacts?readMask=names,emailAddresses&pageSize=1000"
MAX_AGE = 12 * 3600


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


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
    tok = mail_oauth.access_token(S, "gmail")
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

    def splitPath(self, path):
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
    c.setMaxVisibleItems(8)
    line_edit.setCompleter(c)
    line_edit._contact_completer = c


def refresh_async(M, force=False):
    """Fetch the contact list in the background when signed in with Google (at most every 12 hours unless forced)."""
    S = M.SETTINGS
    if _state["busy"] or S.get("mail_provider") != "gmail" or not mail_oauth.signed_in(S, "gmail"):
        return
    t, items = load(M)
    model()
    if not force and items and time.time() - t < MAX_AGE:
        _state["bus"].loaded.emit(items)
        return
    _state["busy"] = True

    def work():
        try:
            got = fetch(S)
            save(M, got)
            S["contacts_note"] = ""
            _state["bus"].loaded.emit(got)
        except Exception as e:
            S["contacts_note"] = "contacts" if re.search(r"403|insufficient|scope|PERMISSION", str(e), re.I) else ""
        finally:
            _state["busy"] = False
    threading.Thread(target=work, daemon=True).start()
