"""Sign in with Google or Microsoft in the browser (no password in the program) and send mail through their web services."""
import base64
import hashlib
import json
import secrets
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

GOOGLE = {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
          "scope": "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/contacts.other.readonly openid email", "id": "google_client_id", "secret": "google_client_secret",
          "refresh": "google_refresh", "host": "127.0.0.1"}
MICROSOFT = {"auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
             "scope": "offline_access Mail.Send User.Read openid email", "id": "ms_client_id", "secret": "", "refresh": "ms_refresh", "host": "localhost"}
PROVIDERS = {"gmail": GOOGLE, "outlook": MICROSOFT}


def _bundled():
    """Client IDs shipped with the program (mail_client.json), so nobody has to type them."""
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        try:
            with open(os.path.join(base or "", "mail_client.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _g(S, key):
    return ((S.get(key) or "").strip() if key else "") or str(_bundled().get(key, "") or "").strip()


def post(url, data=None, headers=None, raw=None, timeout=90):
    """POST form data (dict) or a raw body; returns (status, text)."""
    body = raw if raw is not None else urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _claims(id_token):
    try:
        p = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}


def configured(S, provider):
    P = PROVIDERS[provider]
    return bool(_g(S, P["id"]))


def signed_in(S, provider):
    return bool(S.get(PROVIDERS[provider]["refresh"]))


def sign_in(S, provider, hint="", timeout=240, opener=webbrowser.open, extra_scope=""):
    """Opens the browser, waits for the redirect on a local port, swaps the code for a refresh token. Returns the account's email."""
    P = PROVIDERS[provider]
    cid = _g(S, P["id"])
    if not cid:
        raise RuntimeError("the one-time setup (client ID) has not been entered")
    if provider == "gmail" and S.get("gmail_read") is not False and S.get("gmail_read") and GMAIL_READ not in extra_scope:
        extra_scope = (extra_scope + " " + GMAIL_READ).strip()       # reading was allowed before: a later sign-in keeps it
    if provider == "gmail" and S.get("gmail_modify") and GMAIL_MODIFY not in extra_scope:
        extra_scope = (extra_scope + " " + GMAIL_MODIFY).strip()     # so does the permission to archive, star and delete in the Mail tab
    verifier = _b64u(secrets.token_bytes(48))
    state = secrets.token_urlsafe(12)
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got["q"] = {k: v[0] for k, v in q.items()}
                msg = "You are signed in. You can close this window and go back to the program." if "code" in q else "Sign-in was cancelled. You can close this window."
            else:
                msg = "Waiting..."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<html><body style='font-family:Arial;padding:40px'><h2>%s</h2></body></html>" % msg).encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.timeout = 1
    redirect = "http://%s:%d" % (P["host"], srv.server_address[1])
    params = {"client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": (P["scope"] + " " + extra_scope).strip(), "state": state,
              "code_challenge": _b64u(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    if provider == "gmail":
        params.update({"access_type": "offline", "prompt": "consent"})
        if hint:
            params["login_hint"] = hint
    elif hint:
        params["login_hint"] = hint
    opener(P["auth"] + "?" + urllib.parse.urlencode(params))
    import time
    t0 = time.time()
    while "q" not in got and time.time() - t0 < timeout:
        srv.handle_request()
    srv.server_close()
    q = got.get("q")
    if not q:
        raise RuntimeError("timed out waiting for the sign-in")
    if "error" in q:
        raise RuntimeError("sign-in was cancelled (%s)" % q["error"])
    if q.get("state") != state:
        raise RuntimeError("sign-in answer did not match (try again)")
    form = {"client_id": cid, "code": q["code"], "code_verifier": verifier, "redirect_uri": redirect, "grant_type": "authorization_code"}
    if P["secret"] and _g(S, P["secret"]):
        form["client_secret"] = _g(S, P["secret"])
    st, txt = post(P["token"], form)
    tok = json.loads(txt or "{}")
    if st != 200 or "refresh_token" not in tok:
        raise RuntimeError(tok.get("error_description") or tok.get("error") or "no sign-in token came back (%s)" % st)
    S[P["refresh"]] = tok["refresh_token"]
    if provider == "gmail":
        sc_ = str(tok.get("scope", "")) + " " + extra_scope
        S["gmail_modify"] = "gmail.modify" in sc_
        S["gmail_read"] = "gmail.readonly" in sc_ or "gmail.modify" in sc_      # changing mail includes reading it
    c = _claims(tok.get("id_token", ""))
    return c.get("email") or c.get("preferred_username") or hint


def sign_out(S, provider):
    S[PROVIDERS[provider]["refresh"]] = ""


_TOKS = {}


def access_token(S, provider):
    P = PROVIDERS[provider]
    import time as _t
    key = (provider, S.get(P["refresh"], ""))
    hit = _TOKS.get(key)
    if hit and hit[0] > _t.time():
        if provider == "gmail":
            S["gmail_modify"], S["gmail_read"] = hit[2], hit[3]
        return hit[1]
    form = {"client_id": _g(S, P["id"]), "refresh_token": S.get(P["refresh"], ""), "grant_type": "refresh_token"}
    if P["secret"] and _g(S, P["secret"]):
        form["client_secret"] = _g(S, P["secret"])
    if provider == "outlook":
        form["scope"] = P["scope"]
    st, txt = post(P["token"], form)
    tok = json.loads(txt or "{}")
    if provider == "gmail" and st == 200 and tok.get("scope"):
        S["gmail_modify"] = "gmail.modify" in str(tok["scope"])
        S["gmail_read"] = "gmail.readonly" in str(tok["scope"]) or S["gmail_modify"]           # what Google really allowed
    if st != 200 or "access_token" not in tok:
        if tok.get("error") == "invalid_grant":
            raise RuntimeError("Google ended the Gmail sign-in (it does this after 7 days while the Google project is in Testing: set its publishing status to In production once, then sign in one last time)")
        raise RuntimeError("could not reach Gmail just now (%s); it tries again by itself" % (tok.get("error_description") or tok.get("error") or st))
    _TOKS[key] = (_t.time() + max(60, int(tok.get("expires_in", 3600) or 3600) - 120), tok["access_token"], S.get("gmail_modify"), S.get("gmail_read"))
    return tok["access_token"]


def send(S, provider, msg, thread_id=""):
    """msg is an email.message.EmailMessage with From/To/Subject (and Cc/Bcc headers) set. thread_id keeps a Gmail reply in its conversation."""
    tok = access_token(S, provider)
    mime = bytes(msg)
    if provider == "gmail":
        body_ = {"raw": _b64u(mime)}
        if thread_id:
            body_["threadId"] = thread_id
        st, txt = post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", raw=json.dumps(body_).encode(),
                       headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        ok = st == 200
    else:
        st, txt = post("https://graph.microsoft.com/v1.0/me/sendMail", raw=base64.b64encode(mime),
                       headers={"Authorization": "Bearer " + tok, "Content-Type": "text/plain"})
        ok = st in (200, 202)
    if not ok:
        try:
            err = json.loads(txt).get("error")
            err = err.get("message") if isinstance(err, dict) else err
        except Exception:
            err = txt[:200]
        raise RuntimeError("%s (%s)" % (err or "the mail service refused it", st))


def sign_in_thread(S, provider, hint, done, extra_scope=""):
    def work():
        try:
            done(True, sign_in(S, provider, hint, extra_scope=extra_scope) or hint)
        except Exception as e:
            done(False, str(e))
    threading.Thread(target=work, daemon=True).start()


GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"


def gmail_get(S, path, params=None, timeout=60):
    """GET https://gmail.googleapis.com/gmail/v1/users/me/<path>; returns the decoded JSON."""
    tok = access_token(S, "gmail")
    url = "https://gmail.googleapis.com/gmail/v1/users/me/" + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace").lower()
        except Exception:
            pass
        if e.code in (401, 403) and ("insufficient" in body or "scope" in body):
            S["gmail_read"] = False                       # only when Google really says the permission is missing
            raise RuntimeError("Google did not allow reading the mailbox: press Allow Gmail reading again (%s)" % e.code)
        if e.code in (401, 403, 429):
            raise RuntimeError("Gmail said wait a moment (%s); it tries again by itself" % e.code)
        raise RuntimeError("Gmail answered %s" % e.code)


GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"


_POOL = []
_PLOCK = threading.Lock()


def _gmail_http(method, path, hdr, data, timeout):
    """One request over a kept-open HTTPS connection (no new handshake for every call); returns (status, bytes)."""
    _hc = urllib.request.http.client            # already loaded by urllib
    with _PLOCK:
        conn = _POOL.pop() if _POOL else None
    for attempt in (0, 1):
        if conn is None:
            conn = _hc.HTTPSConnection("gmail.googleapis.com", timeout=timeout)
        try:
            conn.request(method, path, body=data, headers=hdr)
            r = conn.getresponse()
            raw = r.read()
            st = r.status
            with _PLOCK:
                if len(_POOL) < 8:
                    _POOL.append(conn)
                else:
                    conn.close()
            return st, raw
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = None
            if attempt:
                raise


def gmail_call(S, method, path, params=None, body=None, timeout=60):
    """Any call to https://gmail.googleapis.com/gmail/v1/users/me/<path> (GET, POST ...); returns the decoded JSON. Used by the Mail tab."""
    tok = access_token(S, "gmail")
    url = "/gmail/v1/users/me/" + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Authorization": "Bearer " + tok, "Accept-Encoding": "identity"}
    if data is not None:
        hdr["Content-Type"] = "application/json"
    try:
        code, raw = _gmail_http(method, url, hdr, data, timeout)
    except Exception as e:
        raise RuntimeError("could not reach Gmail (%s)" % e)
    if code < 400:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    body_ = raw.decode("utf-8", "replace").lower()
    if code == 401:
        for k in [k for k in _TOKS if k[0] == "gmail"]:
            _TOKS.pop(k, None)
    if code in (401, 403) and ("insufficient" in body_ or "scope" in body_):
        if method != "GET":
            S["gmail_modify"] = False
        else:
            S["gmail_read"] = False
        raise RuntimeError("Google did not allow this: press Allow Gmail again in the Mail tab (%s)" % code)
    if code == 403 and ("not been used" in body_ or "disabled" in body_ or "accessnotconfigured" in body_):
        raise RuntimeError("The Gmail API is switched off in your Google Cloud project. Open console.cloud.google.com, APIs & Services, Library, search Gmail API and press Enable (403)")
    if code in (401, 403, 429):
        why = ""
        try:
            why = json.loads(body_).get("error", {}).get("message", "")[:160]
        except Exception:
            why = body_[:160]
        raise RuntimeError("Gmail refused (%s): %s" % (code, why or "no reason given"))
    raise RuntimeError("Gmail answered %s" % code)


def gmail_bytes(S, path, timeout=120):
    """Raw GET (attachments come back as JSON with base64 data, decoded here)."""
    j = gmail_call(S, "GET", path, timeout=timeout)
    d = j.get("data", "")
    return base64.urlsafe_b64decode(d + "=" * (-len(d) % 4))
