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
          "scope": "https://www.googleapis.com/auth/gmail.send openid email", "id": "google_client_id", "secret": "google_client_secret",
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


def sign_in(S, provider, hint="", timeout=240, opener=webbrowser.open):
    """Opens the browser, waits for the redirect on a local port, swaps the code for a refresh token. Returns the account's email."""
    P = PROVIDERS[provider]
    cid = _g(S, P["id"])
    if not cid:
        raise RuntimeError("the one-time setup (client ID) has not been entered")
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
    params = {"client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": P["scope"], "state": state,
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
    c = _claims(tok.get("id_token", ""))
    return c.get("email") or c.get("preferred_username") or hint


def sign_out(S, provider):
    S[PROVIDERS[provider]["refresh"]] = ""


def access_token(S, provider):
    P = PROVIDERS[provider]
    form = {"client_id": _g(S, P["id"]), "refresh_token": S.get(P["refresh"], ""), "grant_type": "refresh_token"}
    if P["secret"] and _g(S, P["secret"]):
        form["client_secret"] = _g(S, P["secret"])
    if provider == "outlook":
        form["scope"] = P["scope"]
    st, txt = post(P["token"], form)
    tok = json.loads(txt or "{}")
    if st != 200 or "access_token" not in tok:
        raise RuntimeError("sign in again (%s)" % (tok.get("error_description") or tok.get("error") or st))
    return tok["access_token"]


def send(S, provider, msg):
    """msg is an email.message.EmailMessage with From/To/Subject (and Cc/Bcc headers) set."""
    tok = access_token(S, provider)
    mime = bytes(msg)
    if provider == "gmail":
        st, txt = post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", raw=json.dumps({"raw": _b64u(mime)}).encode(),
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


def sign_in_thread(S, provider, hint, done):
    def work():
        try:
            done(True, sign_in(S, provider, hint) or hint)
        except Exception as e:
            done(False, str(e))
    threading.Thread(target=work, daemon=True).start()
