"""Mail accounts that are not Gmail (your own domain, Outlook, Yahoo, iCloud ...): the Mail tab talks to them through this file.
It answers the same calls the Mail tab makes to Gmail (profile, labels, threads, history ...) but reads the mailbox over IMAP.
Sending goes through the program's normal SMTP path (register_ext.deliver)."""
import base64
import email
import email.policy
import email.utils
import imaplib
import json
import quopri
import re
import socket
import ssl
import threading
import time
import urllib.parse
from html import unescape

imaplib._MAXLINE = 10_000_000

_POOL = {}
_PL = threading.Lock()
_META = {}                       # (account, thread id) -> (flags marker, Gmail-style thread)
_FOLDERS = {}                    # account -> (time, {"INBOX": name, "SENT": name ...}, [(name, delimiter)])
_LOCK_F = threading.Lock()
PAGE = 25


def handles(S):
    try:
        return bool(S.get("imap_host"))
    except Exception:
        return False


def _key(S):
    return (str(S.get("imap_host")), str(S.get("imap_port")), str(S.get("imap_user") or S.get("mail_address") or ""), hash(str(S.get("imap_pass") or "")))


# ------------------------------------------------------------------ connection
def connect(host, port, sec, user, password, timeout=30):
    ctx = ssl.create_default_context()
    try:
        if sec == "SSL":
            c = imaplib.IMAP4_SSL(host, int(port), ssl_context=ctx, timeout=timeout)
        else:
            c = imaplib.IMAP4(host, int(port), timeout=timeout)
            if sec == "STARTTLS":
                c.starttls(ssl_context=ctx)
        c.login(user, password)
        return c
    except imaplib.IMAP4.error as e:
        raise RuntimeError("the mail server refused the email or password (%s)" % str(e)[:100])
    except socket.timeout:
        raise RuntimeError("the mail server did not answer (timed out): a firewall or the network may be blocking mail")
    except ssl.SSLError as e:
        raise RuntimeError("secure connection to the mail server failed: %s" % (getattr(e, "reason", None) or e))
    except OSError as e:
        raise RuntimeError("could not reach the mail server (%s)" % e)


class _Use:
    def __init__(self, S):
        self.S = S
        self.k = _key(S)
        self.c = None

    def __enter__(self):
        with _PL:
            idle = _POOL.setdefault(self.k, [])
            self.c = idle.pop() if idle else None
        if self.c is None:
            S = self.S
            self.c = connect(S.get("imap_host"), S.get("imap_port") or 993, S.get("imap_security") or "SSL",
                             S.get("imap_user") or S.get("mail_address"), S.get("imap_pass") or "")
            self.c._sel = None
        return self.c

    def __exit__(self, et, ev, tb):
        ok = et is None
        if ok:
            with _PL:
                idle = _POOL.setdefault(self.k, [])
                if len(idle) < 4:
                    idle.append(self.c)
                    return False
        try:
            self.c.logout()
        except Exception:
            try:
                self.c.shutdown()
            except Exception:
                pass
        if et is not None and issubclass(et, (imaplib.IMAP4.abort, socket.timeout, OSError, EOFError)) and not issubclass(et, RuntimeError):
            raise RuntimeError("the mail server connection dropped (%s); trying again in a moment" % (ev or et.__name__))
        return False


def _run(S, fn):
    """Run fn(connection); one retry on a dropped (old) pooled connection."""
    last = None
    for _ in range(2):
        try:
            with _Use(S) as c:
                return fn(c)
        except RuntimeError as e:
            last = e
            if "dropped" not in str(e):
                raise
    raise last


def drop_pool(S):
    with _PL:
        for c in _POOL.pop(_key(S), []):
            try:
                c.logout()
            except Exception:
                pass


# ------------------------------------------------------------------ parsing
def _q(name):
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _utf7_dec(s):
    if "&" not in s:
        return s
    def f(m):
        t = m.group(1)
        if t == "":
            return "&"
        try:
            b = base64.b64decode(t.replace(",", "/") + "=" * (-len(t) % 4))
            return b.decode("utf-16-be")
        except Exception:
            return m.group(0)
    return re.sub(r"&([^-]*)-", f, s)


def _utf7_enc(s):
    if all(ord(ch) < 128 for ch in s):
        return s.replace("&", "&-")
    out, buf = "", ""
    def flush():
        nonlocal out, buf
        if buf:
            out += "&" + base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",") + "-"
            buf = ""
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7e:
            flush()
            out += "&-" if ch == "&" else ch
        else:
            buf += ch
    flush()
    return out


def _s(x):
    return x.decode("utf-8", "replace") if isinstance(x, (bytes, bytearray)) else str(x)


def _parse_fetch(data):
    """imaplib FETCH data -> [{"uid", "flags", "date", "lits": [bytes...], "text": str}]"""
    out, cur = [], None
    for it in data or []:
        if isinstance(it, tuple):
            meta, lit = it[0], it[1]
        else:
            meta, lit = it, None
        if not isinstance(meta, (bytes, bytearray)):
            continue
        t = meta.decode("latin-1")
        if re.match(r"^\s*\d+ \(", t):
            cur = {"lits": [], "text": ""}
            out.append(cur)
        if cur is None:
            continue
        cur["text"] += t + " "
        if lit is not None:
            cur["lits"].append(bytes(lit))
    for m in out:
        t = m["text"]
        u = re.search(r"UID (\d+)", t)
        m["uid"] = int(u.group(1)) if u else 0
        f = re.search(r"FLAGS \(([^)]*)\)", t)
        m["flags"] = set(x for x in (f.group(1).split() if f else []))
        d = re.search(r'INTERNALDATE "([^"]+)"', t)
        m["date"] = 0
        if d:
            try:
                m["date"] = int(time.mktime(imaplib.Internaldate2tuple(('INTERNALDATE "%s"' % d.group(1)).encode()))) * 1000
            except Exception:
                m["date"] = 0
        sz = re.search(r"RFC822\.SIZE (\d+)", t)
        m["size"] = int(sz.group(1)) if sz else 0
        m["attach"] = bool(re.search(r'(?i)"attachment"|"filename"|"name" "', t)) and "BODYSTRUCTURE" in t
    return out


def _dec_text(raw, cte, ctype=""):
    cte = (cte or "").lower()
    try:
        if "quoted" in cte:
            raw = quopri.decodestring(raw)
        elif "base64" in cte:
            b = re.sub(rb"[^A-Za-z0-9+/=]", b"", raw)
            b = b[: len(b) // 4 * 4]
            raw = base64.b64decode(b)
    except Exception:
        pass
    return raw.decode("utf-8", "replace")


def _snippet(raw, top_cte="", top_type=""):
    if not raw:
        return ""
    t = raw
    cte, ctype = top_cte, top_type
    if t.lstrip().startswith(b"--"):                           # multipart: look at the first part
        head, _, body = t.partition(b"\r\n\r\n")
        if not body:
            head, _, body = t.partition(b"\n\n")
        hp = head.decode("latin-1", "replace")
        m = re.search(r"(?i)content-transfer-encoding:\s*([\w-]+)", hp)
        cte = m.group(1) if m else ""
        m = re.search(r"(?i)content-type:\s*([\w/+-]+)", hp)
        ctype = m.group(1) if m else ""
        if ctype.lower().startswith("multipart"):               # nested: its first part
            head2, _, body2 = body.partition(b"\r\n\r\n")
            body = body2 or body
            cte, ctype = "", "text/plain"
        t = body
    s = _dec_text(t, cte, ctype)
    if "<" in s and re.search(r"(?i)<(html|body|div|p|br|table)\b", s):
        s = re.sub(r"(?is)<(style|script|head).*?</\1>", " ", s)
        s = re.sub(r"(?s)<[^>]*>", " ", s)
    s = unescape(s)
    s = re.sub(r"(?m)^--[\w=_.\-+]+.*$", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140]


def _hdrs(raw):
    try:
        m = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return []
    out = []
    for k, v in m.items():
        try:
            out.append({"name": k, "value": str(v)})
        except Exception:
            out.append({"name": k, "value": ""})
    return out


def enc(folder, uid):
    return base64.urlsafe_b64encode(folder.encode("utf-8")).decode().rstrip("=") + "~" + str(uid)


def dec(tid):
    f, _, u = str(tid).rpartition("~")
    return base64.urlsafe_b64decode(f + "=" * (-len(f) % 4)).decode("utf-8"), int(u)


# ------------------------------------------------------------------ folders
_SPECIAL = {"\\Sent": "SENT", "\\Drafts": "DRAFT", "\\Trash": "TRASH", "\\Junk": "SPAM", "\\All": "ALL", "\\Archive": "ARCHIVE"}
_GUESS = {"SENT": ("sent", "sent items", "sent mail", "sent messages", "inbox.sent"), "DRAFT": ("drafts", "draft", "inbox.drafts"),
          "TRASH": ("trash", "deleted", "deleted items", "deleted messages", "bin", "inbox.trash"),
          "SPAM": ("junk", "spam", "junk e-mail", "junk email", "bulk mail", "inbox.junk"), "ARCHIVE": ("archive", "archives", "inbox.archive"),
          "ALL": ("all mail",)}


def folders(S, c=None, force=False):
    k = _key(S)
    with _LOCK_F:
        hit = _FOLDERS.get(k)
        if hit and not force and time.time() - hit[0] < 60:
            return hit[1], hit[2]

    def go(c):
        typ, data = c.list()
        names, roles = [], {}
        for ln in data or []:
            if not ln:
                continue
            t = ln.decode("utf-8", "replace") if isinstance(ln, bytes) else str(ln)
            m = re.match(r'\((?P<fl>[^)]*)\)\s+(?:"(?P<d>(?:[^"\\]|\\.)*)"|NIL)\s+(?P<n>.+)$', t)
            if not m:
                continue
            fl, d, n = m.group("fl"), m.group("d") or "/", m.group("n").strip()
            if n.startswith('"') and n.endswith('"'):
                n = n[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if "\\Noselect" in fl or "\\NonExistent" in fl:
                continue
            n = _utf7_dec(n)
            names.append((n, d))
            for sf, role in _SPECIAL.items():
                if sf.lower() in fl.lower():
                    roles.setdefault(role, n)
        low = {n.lower(): n for n, _ in names}
        for role, gs in _GUESS.items():
            if role not in roles:
                for g in gs:
                    if g in low:
                        roles[role] = low[g]
                        break
        inbox = next((n for n, _ in names if n.upper() == "INBOX"), "INBOX")
        roles["INBOX"] = inbox
        return roles, names
    if c is not None:
        roles, names = go(c)
    else:
        roles, names = _run(S, go)
    with _LOCK_F:
        _FOLDERS[k] = (time.time(), roles, names)
    return roles, names


def _label_to_folder(S, lab, roles):
    if lab in roles:
        return roles[lab]
    if lab in ("STARRED", "UNREAD", "IMPORTANT"):
        return roles["INBOX"]
    if lab == "ALL":
        return roles.get("ALL") or roles["INBOX"]
    return lab


def _folder_to_label(name, roles):
    for r, n in roles.items():
        if n == name and r in ("INBOX", "SENT", "DRAFT", "TRASH", "SPAM"):
            return r
    return name


def _select(c, folder, ro=False):
    typ, d = c.select('"%s"' % _utf7_enc(folder).replace("\\", "\\\\").replace('"', '\\"'), readonly=ro)
    if typ != "OK":
        raise RuntimeError("the folder %s could not be opened" % folder)
    c._sel = folder
    return d


# ------------------------------------------------------------------ search
def _criteria(q, label):
    """Gmail style search text -> IMAP SEARCH criteria (list of tokens, strings with spaces are sent as quoted)."""
    out = []
    toks = re.findall(r'(-?\w+:"[^"]*"|-?\w+:\S+|"[^"]*"|\S+)', q or "")
    for t in toks:
        neg = t.startswith("-")
        t2 = t[1:] if neg else t
        m = re.match(r'(\w+):(.*)$', t2)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip('"')
            if k == "category" or k == "label" or k == "in":
                continue
            if k == "is":
                crit = {"unread": ["UNSEEN"], "read": ["SEEN"], "starred": ["FLAGGED"]}.get(v.lower())
                if crit:
                    out += (["NOT"] if neg else []) + crit
                continue
            if k in ("from", "to", "cc", "bcc", "subject"):
                out += (["NOT"] if neg else []) + [k.upper(), v]
                continue
            if k in ("has", "filename", "after", "before", "newer_than", "older_than"):
                continue
            v = t2.strip('"')
            out += (["NOT"] if neg else []) + ["TEXT", v]
        else:
            out += (["NOT"] if neg else []) + ["TEXT", t2.strip('"')]
    if label == "STARRED":
        out = ["FLAGGED"] + out
    return out


def _search(c, crit, charset=True):
    args = ["ALL"] if not crit else crit
    if any(ord(ch) > 127 for a in args for ch in a):
        typ, d = c.uid("SEARCH", "CHARSET", "UTF-8", *[a if a.isupper() and " " not in a else '"%s"' % a.replace('"', "") for a in args])
        if typ == "OK":
            return [int(x) for x in (d[0] or b"").split()]
    parts = []
    for a in args:
        if re.fullmatch(r"[A-Z]+", a):
            parts.append(a)
        else:
            parts.append('"%s"' % a.replace("\\", "\\\\").replace('"', '\\"'))
    typ, d = c.uid("SEARCH", None, *parts)
    if typ != "OK":
        raise RuntimeError("the mail server could not search")
    return [int(x) for x in (d[0] or b"").split()]


# ------------------------------------------------------------------ message building
FETCH_META = "(UID FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID CONTENT-TYPE CONTENT-TRANSFER-ENCODING)] BODY.PEEK[TEXT]<0.700>)"


def _marker(flags):
    return "|".join(sorted(f.lower() for f in flags if f.lower() in ("\\seen", "\\flagged", "\\deleted")))


def _labels(folder, flags, roles):
    labs = [_folder_to_label(folder, roles)]
    if "\\Seen" not in flags and "\\seen" not in {f.lower() for f in flags}:
        labs.append("UNREAD")
    if "\\flagged" in {f.lower() for f in flags}:
        labs.append("STARRED")
    return labs


def _meta_msg(S, folder, m, roles):
    heads = m["lits"][0] if m["lits"] else b""
    hl = _hdrs(heads)
    hd = {h["name"].lower(): h["value"] for h in hl}
    snip = _snippet(m["lits"][1] if len(m["lits"]) > 1 else b"", hd.get("content-transfer-encoding", ""), hd.get("content-type", ""))
    tid = enc(folder, m["uid"])
    date = m["date"]
    if not date and hd.get("date"):
        try:
            date = int(email.utils.parsedate_to_datetime(hd["date"]).timestamp() * 1000)
        except Exception:
            date = 0
    payload = {"mimeType": "multipart/mixed" if m["attach"] else "text/plain",
               "headers": [h for h in hl if h["name"].lower() in ("from", "to", "subject", "date", "message-id")]}
    if m["attach"]:
        payload["parts"] = [{"filename": "attachment"}]
    return {"id": tid, "threadId": tid, "labelIds": _labels(folder, m["flags"], roles), "snippet": snip, "internalDate": str(date), "payload": payload}


def _thread_of(msg):
    return {"id": msg["id"], "historyId": _marker_of(msg), "snippet": msg["snippet"], "messages": [msg]}


def _marker_of(msg):
    return "%s:%s" % (msg["id"], ",".join(sorted(msg["labelIds"])))


def _fetch_meta(S, c, folder, uids, roles):
    out = {}
    uids = list(uids)
    for i in range(0, len(uids), 50):
        chunk = uids[i:i + 50]
        typ, d = c.uid("FETCH", ",".join(str(u) for u in chunk), FETCH_META)
        if typ != "OK":
            continue
        for m in _parse_fetch(d):
            if m["uid"]:
                msg = _meta_msg(S, folder, m, roles)
                th = _thread_of(msg)
                out[m["uid"]] = th
                _META[(_key(S), msg["id"])] = th
    if len(_META) > 3000:
        for k in list(_META)[:1000]:
            _META.pop(k, None)
    return out


def _full_msg(S, folder, uid, c, roles):
    typ, d = c.uid("FETCH", str(uid), "(UID FLAGS INTERNALDATE BODY.PEEK[])")
    ms = [m for m in _parse_fetch(d) if m["lits"]]
    if typ != "OK" or not ms:
        raise RuntimeError("that email is no longer on the mail server")
    m = ms[0]
    raw = m["lits"][0]
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    tid = enc(folder, uid)
    pay = _payload(msg, "")
    hdr = {h["name"].lower(): h["value"] for h in pay["headers"]}
    date = m["date"]
    if not date and hdr.get("date"):
        try:
            date = int(email.utils.parsedate_to_datetime(hdr["date"]).timestamp() * 1000)
        except Exception:
            date = 0
    plain = ""
    try:
        b = msg.get_body(preferencelist=("plain",))
        plain = b.get_content() if b else ""
    except Exception:
        pass
    snip = re.sub(r"\s+", " ", plain).strip()[:140]
    return {"id": tid, "threadId": tid, "labelIds": _labels(folder, m["flags"], roles), "snippet": snip, "internalDate": str(date), "payload": pay}


def _b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _payload(part, path):
    mime = part.get_content_type()
    hdrs = []
    for k, v in part.items():
        try:
            hdrs.append({"name": k, "value": str(v)})
        except Exception:
            pass
    out = {"mimeType": mime, "headers": hdrs, "filename": "", "body": {"size": 0}}
    if part.is_multipart():
        out["parts"] = [_payload(p, (path + "." if path else "") + str(i)) for i, p in enumerate(part.iter_parts())]
        return out
    name = part.get_filename() or ""
    disp = str(part.get_content_disposition() or "")
    if mime in ("text/plain", "text/html") and not name and disp != "attachment":
        try:
            txt = part.get_content()
        except Exception:
            txt = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        b = txt.encode("utf-8", "replace")
        out["body"] = {"size": len(b), "data": _b64u(b)}
        return out
    data = part.get_payload(decode=True) or b""
    out["filename"] = name or ("attachment" if disp == "attachment" else "")
    out["body"] = {"size": len(data), "attachmentId": path or "0"}
    return out


def _part_bytes(msg, path):
    p = msg
    for i in [int(x) for x in path.split(".") if x != ""] if path not in ("", "0") else []:
        p = list(p.iter_parts())[i]
    return p.get_payload(decode=True) or b""


# ------------------------------------------------------------------ the calls
def _split(path):
    p, _, qs = path.partition("?")
    return p, dict(urllib.parse.parse_qsl(qs))


def _profile(S, c, roles):
    d = _select(c, roles["INBOX"], True)
    typ, st = c.status('"%s"' % roles["INBOX"], "(UIDNEXT UIDVALIDITY UNSEEN MESSAGES)")
    t = _s(st[0]) if st and st[0] else ""
    g = lambda k: int((re.search(k + r" (\d+)", t) or [0, 0])[1])
    return {"emailAddress": str(S.get("mail_address") or ""), "historyId": "%d.%d.%d" % (g("UIDVALIDITY"), g("UIDNEXT"), g("UNSEEN")),
            "messagesTotal": g("MESSAGES"), "unseen": g("UNSEEN"), "uidnext": g("UIDNEXT")}


def call(S, method, path, params=None, body=None, timeout=60):
    p, qs = _split(path)
    params = dict(params or {})
    for k, v in qs.items():
        params.setdefault(k, v)
    method = method.upper()
    if p == "profile":
        def go(c):
            roles, _ = folders(S, c)
            r = _profile(S, c, roles)
            return {k: r[k] for k in ("emailAddress", "historyId", "messagesTotal")}
        return _run(S, go)
    if p == "history":
        return _run(S, lambda c: _history(S, c, params))
    if p == "labels" and method == "GET":
        return _run(S, lambda c: _labels_list(S, c))
    if p == "labels" and method == "POST":
        return _run(S, lambda c: _label_create(S, c, body or {}))
    if p.startswith("labels/"):
        lid = p[len("labels/"):]
        return _run(S, lambda c: _label_op(S, c, method, urllib.parse.unquote(lid), body or {}))
    if p == "threads" and method == "GET":
        return _run(S, lambda c: _list(S, c, params))
    if p.startswith("threads/"):
        rest = p[len("threads/"):]
        tid, _, act = rest.partition("/")
        if method == "GET":
            return _run(S, lambda c: _thread_get(S, c, tid, params))
        if act == "trash":
            return _run(S, lambda c: _modify(S, c, [tid], [], [], True))
        if act == "modify":
            b = body or {}
            return _run(S, lambda c: _modify(S, c, [tid], b.get("addLabelIds") or [], b.get("removeLabelIds") or [], False))
    if p.startswith("messages/") and method == "GET" and "/attachments/" not in p:
        mid = p[len("messages/"):]
        th = _run(S, lambda c: _thread_get(S, c, mid, {"format": "metadata"}))
        m = dict(th["messages"][0])
        return m
    if p == "messages" and method == "GET":
        return _run(S, lambda c: _messages(S, c, params))
    if p == "messages/batchModify":
        b = body or {}
        return _run(S, lambda c: _modify(S, c, b.get("ids") or [], b.get("addLabelIds") or [], b.get("removeLabelIds") or [], False))
    raise RuntimeError("this is not available for a non-Gmail account yet (%s)" % p)


def batch(S, paths, timeout=60):
    out = []
    for p in paths:
        try:
            out.append(call(S, "GET", p))
        except Exception:
            out.append(None)
    return out


def bytes_(S, path, timeout=120):
    p, _ = _split(path)
    m = re.match(r"messages/([^/]+)/attachments/(.*)$", p)
    if not m:
        raise RuntimeError("this attachment cannot be read")
    mid, aid = m.group(1), m.group(2)

    def go(c):
        folder, uid = dec(mid)
        _select(c, folder, True)
        typ, d = c.uid("FETCH", str(uid), "(BODY.PEEK[])")
        ms = [x for x in _parse_fetch(d) if x["lits"]]
        if not ms:
            raise RuntimeError("that email is no longer on the mail server")
        msg = email.message_from_bytes(ms[0]["lits"][0], policy=email.policy.default)
        return _part_bytes(msg, aid)
    return _run(S, go)


_NS = {}


def _namespace(S, c, names):
    """(prefix, delimiter) for new folders: servers like Courier and Cyrus only allow them below 'INBOX.', Gmail-style servers at the top."""
    k = _key(S)
    if k in _NS:
        return _NS[k]
    pre, d = "", "/"
    try:
        typ, data = c.namespace()
        t = " ".join(_s(x) for x in data or [] if x)
        m = re.match(r'\s*\(\("([^"]*)"\s+(?:"([^"]*)"|NIL)', t)
        if m:
            pre, d = m.group(1), (m.group(2) or "/")
    except Exception:
        m = None
    if not pre:
        dl = next((dd for n, dd in names if n != "INBOX"), "/")
        d = d if d != "/" or dl == "/" else dl
        if names and dl and all(n == "INBOX" or n.startswith("INBOX" + dl) for n, _ in names):
            pre, d = "INBOX" + dl, dl
    _NS[k] = (pre, d)
    return pre, d


def _display(S, c, n, d, names):
    pre, dl = _namespace(S, c, names)
    shown = n[len(pre):] if pre and n.startswith(pre) else n
    return shown.replace(d, "/") if d and d != "/" else shown


def _cols(S):
    try:
        d = S.get("imap_label_colors")
        if d is None:
            d = {}
            S["imap_label_colors"] = d
        return d
    except Exception:
        return {}


def _ckey(S, lid):
    return "%s|%s" % (str(S.get("mail_address", "")).lower(), lid)


def _labels_list(S, c):
    roles, names = folders(S, c, force=True)
    sysnames = {v for k, v in roles.items()}
    labs = [{"id": "INBOX", "name": "INBOX", "type": "system"}, {"id": "STARRED", "name": "STARRED", "type": "system"},
            {"id": "SENT", "name": "SENT", "type": "system"}, {"id": "DRAFT", "name": "DRAFT", "type": "system"},
            {"id": "SPAM", "name": "SPAM", "type": "system"}, {"id": "TRASH", "name": "TRASH", "type": "system"}]
    for n, d in names:
        if n in sysnames or n.upper() == "INBOX":
            continue
        lb = {"id": n, "name": _display(S, c, n, d, names), "type": "user"}
        hx = _cols(S).get(_ckey(S, n))
        if hx:
            lb["color"] = {"backgroundColor": hx[0], "textColor": hx[1]}
        labs.append(lb)
    return {"labels": labs}


def _label_op(S, c, method, lid, body):
    roles, names = folders(S, c)
    folder = _label_to_folder(S, lid, roles)
    if method == "GET":
        try:
            typ, st = c.status('"%s"' % _utf7_enc(folder), "(MESSAGES UNSEEN)")
        except Exception:
            return {"id": lid, "threadsUnread": 0, "threadsTotal": 0}
        t = _s(st[0]) if st and st[0] else ""
        g = lambda k: int((re.search(k + r" (\d+)", t) or [0, 0])[1])
        return {"id": lid, "threadsUnread": g("UNSEEN"), "threadsTotal": g("MESSAGES"), "messagesUnread": g("UNSEEN"), "messagesTotal": g("MESSAGES")}
    if method == "PUT":
        col = body.get("color")
        if col:
            _cols(S)[_ckey(S, lid)] = (col.get("backgroundColor", ""), col.get("textColor", "#000000"))
        new = (body.get("name") or "").strip()
        if new and new != lid:
            d = next((d for n, d in names if n == lid), "/")
            pre, _dl = _namespace(S, c, names)
            new = pre + new.replace("/", d)
            typ, r = c.rename('"%s"' % _utf7_enc(lid), '"%s"' % _utf7_enc(new))
            if typ != "OK":
                raise RuntimeError("the mail server did not allow renaming the folder")
            cc = _cols(S)
            if _ckey(S, lid) in cc:
                cc[_ckey(S, new)] = cc.pop(_ckey(S, lid))
            folders(S, c, force=True)
        return {"id": new or lid, "name": new or lid}
    if method == "DELETE":
        typ, r = c.delete('"%s"' % _utf7_enc(lid))
        if typ != "OK":
            raise RuntimeError("the mail server did not allow deleting the folder")
        folders(S, c, force=True)
        return {}
    return {}


def _label_create(S, c, body):
    """A new folder; 'Cosmo/Areas/North' makes the whole chain (the groups above it are created first, because many servers refuse a folder whose parent is missing)."""
    roles, names = folders(S, c)
    pre, d = _namespace(S, c, names)
    d = next((dd for n, dd in names if dd and n != "INBOX"), d) or "/"
    shown = (body.get("name") or "").strip().strip("/")
    if not shown:
        raise RuntimeError("the label needs a name")
    parts = [x.strip() for x in shown.split("/") if x.strip()]
    have = {n for n, _ in names}
    cur, last = pre.rstrip(d) if pre.endswith(d) else pre.rstrip("."), ""
    full = ""
    for i, part in enumerate(parts):
        full = (cur + d + part) if cur else part
        if pre and not cur:
            full = pre + part
        if full not in have:
            typ, r = c.create('"%s"' % _utf7_enc(full))
            if typ != "OK":
                why = _s(r[0]) if r and r[0] else ""
                raise RuntimeError("the mail server did not allow creating the folder %s (%s)" % ("/".join(parts[:i + 1]), why or "refused"))
            try:
                c.subscribe('"%s"' % _utf7_enc(full))
            except Exception:
                pass
            have.add(full)
        cur = full
    col = body.get("color")
    if col:
        _cols(S)[_ckey(S, full)] = (col.get("backgroundColor", ""), col.get("textColor", "#000000"))
    folders(S, c, force=True)
    return {"id": full, "name": "/".join(parts), "type": "user"}


def _list(S, c, params):
    roles, _ = folders(S, c)
    labs = params.get("labelIds") or []
    if isinstance(labs, str):
        labs = [labs]
    q = params.get("q") or ""
    lab = next((x for x in labs if not x.startswith("CATEGORY_") and x != "UNREAD"), "ALL" if not q else "INBOX")
    if any(x.startswith("CATEGORY_") and x != "CATEGORY_PERSONAL" for x in labs):
        return {"threads": [], "resultSizeEstimate": 0}
    folder = _label_to_folder(S, lab, roles)
    if folder != roles.get("INBOX") and folder not in [n for n, _ in folders(S, c)[1]]:
        return {"threads": [], "resultSizeEstimate": 0}                      # a group that only exists because labels sit inside it
    crit = _criteria(q, lab)
    if "UNREAD" in labs:
        crit = ["UNSEEN"] + crit
    folds = [folder]
    if q and not labs:                                                       # a search looks in every folder except the Trash and Spam
        folds = [n for n, _ in folders(S, c)[1] if n not in (roles.get("TRASH"), roles.get("SPAM"), roles.get("DRAFT"))][:12]
    start = int(params.get("pageToken") or 0)
    allu = []
    for f in folds:
        _select(c, f, True)
        for u in _search(c, crit):
            allu.append((f, u))
    allu.sort(key=lambda x: x[1], reverse=True) if len(folds) == 1 else None
    page = allu[start:start + PAGE]
    out = []
    byf = {}
    for f, u in page:
        byf.setdefault(f, []).append(u)
    got = {}
    for f, us in byf.items():
        _select(c, f, True)
        for u, th in _fetch_meta(S, c, f, us, roles).items():
            got[(f, u)] = th
    for f, u in page:
        th = got.get((f, u))
        if th:
            out.append({"id": th["id"], "snippet": th["snippet"], "historyId": th["historyId"]})
    nxt = str(start + PAGE) if start + PAGE < len(allu) else ""
    res = {"threads": out, "resultSizeEstimate": len(allu)}
    if nxt:
        res["nextPageToken"] = nxt
    return res


def _messages(S, c, params):
    roles, _ = folders(S, c)
    labs = params.get("labelIds") or []
    lab = next((x for x in labs if x not in ("UNREAD",)), "INBOX")
    crit = ["UNSEEN"] if "UNREAD" in labs else []
    folder = _label_to_folder(S, lab, roles)
    _select(c, folder, True)
    uids = sorted(_search(c, crit), reverse=True)[:500]
    return {"messages": [{"id": enc(folder, u), "threadId": enc(folder, u)} for u in uids]}


def _thread_get(S, c, tid, params):
    roles, _ = folders(S, c)
    folder, uid = dec(tid)
    if (params.get("format") or "metadata") == "full":
        _select(c, folder, True)
        msg = _full_msg(S, folder, uid, c, roles)
        return {"id": tid, "historyId": _marker_of(msg), "snippet": msg["snippet"], "messages": [msg]}
    hit = _META.get((_key(S), tid))
    if hit:
        return hit[1] if isinstance(hit, tuple) else hit
    _select(c, folder, True)
    r = _fetch_meta(S, c, folder, [uid], roles)
    if uid not in r:
        raise RuntimeError("that email is no longer on the mail server")
    return r[uid]


def _history(S, c, params):
    roles, _ = folders(S, c)
    start = str(params.get("startHistoryId") or "")
    cur = _profile(S, c, roles)
    try:
        vv, un, _x = start.split(".")
        un = int(un)
    except Exception:
        raise RuntimeError("history marker too old")
    res = {"historyId": cur["historyId"], "history": []}
    if un >= cur["uidnext"]:
        return res
    uids = _search_range(c, roles["INBOX"], un)
    th = _fetch_meta(S, c, roles["INBOX"], uids[-100:], roles)
    res["history"] = [{"messagesAdded": [{"message": {"id": t["id"], "threadId": t["id"], "labelIds": t["messages"][0]["labelIds"]}}]} for t in th.values()]
    return res


def _search_range(c, folder, un):
    _select(c, folder, True)
    typ, d = c.uid("SEARCH", None, "UID", "%d:*" % un)
    us = [int(x) for x in (d[0] or b"").split()]
    return sorted(u for u in us if u >= un)


def _modify(S, c, tids, add, remove, trash):
    roles, _ = folders(S, c)
    byf = {}
    for t in tids:
        f, u = dec(t)
        byf.setdefault(f, []).append(u)
    add, remove = list(add), list(remove)
    caps = " ".join(getattr(c, "capabilities", ()) or ()).upper()
    for f, us in byf.items():
        _select(c, f)
        uset = ",".join(str(u) for u in us)
        if "UNREAD" in remove:
            c.uid("STORE", uset, "+FLAGS.SILENT", "(\\Seen)")
        if "UNREAD" in add:
            c.uid("STORE", uset, "-FLAGS.SILENT", "(\\Seen)")
        if "STARRED" in add:
            c.uid("STORE", uset, "+FLAGS.SILENT", "(\\Flagged)")
        if "STARRED" in remove:
            c.uid("STORE", uset, "-FLAGS.SILENT", "(\\Flagged)")
        dest = None
        if trash or "TRASH" in add:
            dest = roles.get("TRASH") or "Trash"
        elif "SPAM" in add:
            dest = roles.get("SPAM") or "Junk"
        elif "INBOX" in remove and f == roles["INBOX"]:
            dest = roles.get("ARCHIVE") or roles.get("ALL") or "Archive"
        elif "INBOX" in add and f != roles["INBOX"]:
            dest = roles["INBOX"]
        else:
            for x in add:
                if x not in ("UNREAD", "STARRED", "INBOX", "TRASH", "SPAM", "IMPORTANT", "SENT", "DRAFT") and not x.startswith("CATEGORY_") and x != f:
                    c.uid("COPY", uset, '"%s"' % _utf7_enc(x))
            for x in remove:
                if x == f and x not in (roles["INBOX"],):
                    dest = roles["INBOX"]
        if dest and dest != f:
            _move(c, uset, dest, caps)
    return {}


def _move(c, uset, dest, caps):
    q = '"%s"' % _utf7_enc(dest)
    if "MOVE" in caps:
        typ, r = c.uid("MOVE", uset, q)
        if typ == "OK":
            return
    typ, r = c.uid("COPY", uset, q)
    if typ != "OK":
        try:
            c.create(q)
            typ, r = c.uid("COPY", uset, q)
        except Exception:
            pass
    if typ != "OK":
        raise RuntimeError("the mail server could not move the email to %s" % dest)
    c.uid("STORE", uset, "+FLAGS.SILENT", "(\\Deleted)")
    if "UIDPLUS" in caps:
        c.uid("EXPUNGE", uset)
    else:
        c.expunge()


def append_sent(S, msg):
    """Keep a copy of what was sent in the Sent folder (most mail servers do not do it by themselves)."""
    def go(c):
        roles, _ = folders(S, c)
        f = roles.get("SENT") or "Sent"
        c.append('"%s"' % _utf7_enc(f), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    try:
        _run(S, go)
    except Exception:
        pass


def test_login(host, port, sec, user, password):
    """('ok'|'auth'|'down', detail) for the add-account dialog."""
    try:
        ctx = ssl.create_default_context()
        if sec == "SSL":
            c = imaplib.IMAP4_SSL(host, int(port), ssl_context=ctx, timeout=12)
        else:
            c = imaplib.IMAP4(host, int(port), timeout=12)
            if sec == "STARTTLS":
                c.starttls(ssl_context=ctx)
        try:
            c.login(user, password)
        finally:
            try:
                c.logout()
            except Exception:
                pass
        return "ok", ""
    except imaplib.IMAP4.error as e:
        return "auth", str(e)[:160]
    except socket.timeout:
        return "down", "no answer (timed out)"
    except ssl.SSLError as e:
        return "down", "secure connection failed: %s" % (getattr(e, "reason", None) or e)
    except OSError as e:
        return "down", "%s: %s" % (type(e).__name__, e)
