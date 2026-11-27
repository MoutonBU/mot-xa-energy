"""A tiny pretend mail server (IMAP + SMTP) for tests only."""
import base64
import re
import socketserver
import threading
import time
from email.message import EmailMessage


def mk(frm, subj, body, to="me@test.local", att=False, html=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"], m["Message-ID"] = frm, to, subj, "Mon, 02 Mar 2026 10:00:00 +0000", "<%d@t>" % int(time.time() * 1e6)
    if html:
        m.set_content(body)
        m.add_alternative("<html><body><p>%s</p></body></html>" % body, subtype="html")
    else:
        m.set_content(body)
    if att:
        m.add_attachment(b"%PDF-1.4 fake pdf bytes", maintype="application", subtype="pdf", filename="plan.pdf")
    return m.as_bytes()


class Store:
    def __init__(self):
        self.f = {"INBOX": [], "Sent": [], "Trash": [], "Junk": [], "Clients": [], "Archive": []}
        self.next = {k: 1 for k in self.f}
        self.sent_smtp = []
        self.logins = []
        self.lock = threading.RLock()
        self.delim, self.prefix, self.strict = "/", "", False        # prefix "INBOX." and strict: like Courier / Cyrus servers

    def add(self, folder, raw, flags=()):
        with self.lock:
            u = self.next[folder]
            self.next[folder] += 1
            self.f[folder].append({"uid": u, "flags": set(flags), "raw": raw, "date": "02-Mar-2026 10:00:00 +0000"})
            return u


def _lit(b):
    return b"{%d}\r\n" % len(b) + b


class ImapH(socketserver.StreamRequestHandler):
    def send(self, b):
        self.wfile.write(b if isinstance(b, bytes) else b.encode())
        self.wfile.flush()

    def handle(self):
        st = self.server.store
        self.sel = None
        self.send("* OK fake IMAP ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            line = line.rstrip(b"\r\n").decode("utf-8", "replace")
            m = re.match(r"(\S+) (\S+)\s*(.*)$", line)
            if not m:
                continue
            tag, cmd, rest = m.group(1), m.group(2).upper(), m.group(3)
            try:
                if cmd == "CAPABILITY":
                    self.send("* CAPABILITY IMAP4rev1 UIDPLUS\r\n%s OK done\r\n" % tag)
                elif cmd == "LOGIN":
                    a = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', rest)
                    u, p = [x[0] or x[1] for x in a][:2]
                    st.logins.append((u, p))
                    if p != self.server.password:
                        self.send("%s NO [AUTHENTICATIONFAILED] bad login\r\n" % tag)
                    else:
                        self.send("%s OK logged in\r\n" % tag)
                elif cmd == "LIST":
                    out = ""
                    for n in st.f:
                        fl = {"Sent": "\\Sent", "Trash": "\\Trash", "Junk": "\\Junk", "Archive": "\\Archive"}.get(n, "")
                        out += '* LIST (%s) "%s" "%s"\r\n' % (fl, st.delim, n)
                    self.send(out + "%s OK done\r\n" % tag)
                elif cmd in ("SELECT", "EXAMINE"):
                    n = rest.strip().strip('"')
                    if n not in st.f:
                        self.send("%s NO no such folder\r\n" % tag)
                        continue
                    self.sel = n
                    self.send('* %d EXISTS\r\n* 0 RECENT\r\n* FLAGS (\\Seen \\Flagged \\Deleted)\r\n* OK [UIDVALIDITY 7]\r\n* OK [UIDNEXT %d]\r\n%s OK [READ-WRITE] done\r\n'
                              % (len(st.f[n]), st.next[n], tag))
                elif cmd == "STATUS":
                    n = re.match(r'"?([^"]+)"?', rest).group(1)
                    if n not in st.f:
                        self.send("%s NO no folder\r\n" % tag)
                        continue
                    un = sum(1 for x in st.f[n] if "\\Seen" not in x["flags"])
                    self.send('* STATUS "%s" (MESSAGES %d UNSEEN %d UIDNEXT %d UIDVALIDITY 7)\r\n%s OK done\r\n' % (n, len(st.f[n]), un, st.next[n], tag))
                elif cmd == "UID":
                    self.uid(tag, rest)
                elif cmd == "EXPUNGE":
                    st.f[self.sel] = [x for x in st.f[self.sel] if "\\Deleted" not in x["flags"]]
                    self.send("%s OK done\r\n" % tag)
                elif cmd == "NAMESPACE":
                    self.send('* NAMESPACE (("%s" "%s")) NIL NIL\r\n%s OK done\r\n' % (st.prefix, st.delim, tag))
                elif cmd == "CREATE":
                    n = rest.strip().strip('"')
                    if st.prefix and not n.startswith(st.prefix):
                        self.send("%s NO [CANNOT] Invalid mailbox name: must start with %s\r\n" % (tag, st.prefix))
                        continue
                    if st.strict and st.delim in n.rstrip(st.delim) and n.rsplit(st.delim, 1)[0] not in st.f and n.rsplit(st.delim, 1)[0] != st.prefix.rstrip(st.delim):
                        self.send("%s NO [NONEXISTENT] parent missing\r\n" % tag)
                        continue
                    st.f.setdefault(n, [])
                    st.next.setdefault(n, 1)
                    self.send("%s OK done\r\n" % tag)
                elif cmd == "RENAME":
                    a, b = re.findall(r'"([^"]+)"', rest)
                    st.f[b] = st.f.pop(a)
                    st.next[b] = st.next.pop(a)
                    self.send("%s OK done\r\n" % tag)
                elif cmd == "DELETE":
                    n = rest.strip().strip('"')
                    st.f.pop(n, None)
                    self.send("%s OK done\r\n" % tag)
                elif cmd in ("SUBSCRIBE", "NOOP"):
                    self.send("%s OK done\r\n" % tag)
                elif cmd == "APPEND":
                    mm = re.match(r'"([^"]+)"\s*(?:\(([^)]*)\))?\s*(?:"[^"]*")?\s*\{(\d+)\}', rest)
                    n, fl, ln = mm.group(1), mm.group(2) or "", int(mm.group(3))
                    self.send("+ go\r\n")
                    data = self.rfile.read(ln)
                    self.rfile.readline()
                    st.add(n, data, fl.split())
                    self.send("%s OK appended\r\n" % tag)
                elif cmd == "LOGOUT":
                    self.send("* BYE\r\n%s OK bye\r\n" % tag)
                    return
                else:
                    self.send("%s BAD unknown %s\r\n" % (tag, cmd))
            except Exception as e:
                self.send("%s BAD %s\r\n" % (tag, e))

    def _uids(self, spec):
        st = self.server.store
        out = []
        for part in spec.split(","):
            if ":" in part:
                a, b = part.split(":")
                lo = int(a)
                hi = 10 ** 9 if b == "*" else int(b)
                out += [x["uid"] for x in st.f[self.sel] if lo <= x["uid"] <= hi]
            else:
                out.append(int(part))
        return out

    def uid(self, tag, rest):
        st = self.server.store
        sub, _, args = rest.partition(" ")
        sub = sub.upper()
        msgs = st.f[self.sel]
        if sub == "SEARCH":
            args = re.sub(r"^CHARSET UTF-8 ", "", args)
            toks = re.findall(r'"(?:[^"\\]|\\.)*"|\S+', args)
            res = []
            for x in msgs:
                if self._match(x, toks):
                    res.append(x["uid"])
            self.send("* SEARCH %s\r\n%s OK done\r\n" % (" ".join(str(u) for u in res), tag))
        elif sub == "FETCH":
            spec, _, items = args.partition(" ")
            out = b""
            for u in self._uids(spec):
                x = next((y for y in msgs if y["uid"] == u), None)
                if not x:
                    continue
                seq = msgs.index(x) + 1
                parts = []
                if "UID" in items:
                    parts.append(b"UID %d" % u)
                if "FLAGS" in items:
                    parts.append(b"FLAGS (%s)" % " ".join(sorted(x["flags"])).encode())
                if "INTERNALDATE" in items:
                    parts.append(b'INTERNALDATE "%s"' % x["date"].encode())
                if "RFC822.SIZE" in items:
                    parts.append(b"RFC822.SIZE %d" % len(x["raw"]))
                if "BODYSTRUCTURE" in items:
                    if b"filename=" in x["raw"]:
                        parts.append(b'BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 10 1)("APPLICATION" "PDF" ("NAME" "plan.pdf") NIL NIL "BASE64" 100 NIL ("ATTACHMENT" ("FILENAME" "plan.pdf"))) "MIXED")')
                    else:
                        parts.append(b'BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 10 1)')
                raw = x["raw"]
                head, _, body = raw.partition(b"\r\n\r\n")
                if not _:
                    head, _, body = raw.partition(b"\n\n")
                if "HEADER.FIELDS" in items:
                    want = re.search(r"HEADER\.FIELDS \(([^)]*)\)", items).group(1).upper().split()
                    keep = b""
                    for ln in re.split(rb"\r?\n(?![ \t])", head):
                        if ln.split(b":")[0].decode().upper() in want:
                            keep += ln + b"\r\n"
                    parts.append(b"BODY[HEADER.FIELDS (%s)] " % " ".join(want).encode() + _lit(keep + b"\r\n"))
                if "BODY.PEEK[TEXT]" in items or "BODY[TEXT]" in items:
                    mm = re.search(r"TEXT\]<0\.(\d+)>", items)
                    t = body[: int(mm.group(1))] if mm else body
                    parts.append(b"BODY[TEXT]<0> " + _lit(t))
                if re.search(r"BODY\.PEEK\[\]|BODY\[\]", items):
                    parts.append(b"BODY[] " + _lit(raw))
                out += b"* %d FETCH (" % seq + b" ".join(parts) + b")\r\n"
            self.send(out + ("%s OK done\r\n" % tag).encode())
        elif sub == "STORE":
            spec, op, fl = re.match(r"(\S+) (\S+) \(([^)]*)\)", args).groups()
            for u in self._uids(spec):
                for x in msgs:
                    if x["uid"] == u:
                        if op.startswith("+"):
                            x["flags"] |= set(fl.split())
                        else:
                            x["flags"] -= set(fl.split())
            self.send("%s OK done\r\n" % tag)
        elif sub == "COPY":
            spec, dest = re.match(r'(\S+) "([^"]+)"', args).groups()
            if dest not in st.f:
                self.send("%s NO [TRYCREATE] no folder\r\n" % tag)
                return
            for u in self._uids(spec):
                for x in msgs:
                    if x["uid"] == u:
                        st.add(dest, x["raw"], x["flags"])
            self.send("%s OK done\r\n" % tag)
        elif sub == "EXPUNGE":
            gone = set(self._uids(args.strip()))
            st.f[self.sel] = [x for x in msgs if not (x["uid"] in gone and "\\Deleted" in x["flags"])]
            self.send("%s OK done\r\n" % tag)
        else:
            self.send("%s BAD uid %s\r\n" % (tag, sub))

    def _match(self, x, toks):
        i = 0
        raw = x["raw"].decode("utf-8", "replace").lower()
        head = raw.split("\n\n")[0].split("\r\n\r\n")[0]
        while i < len(toks):
            t = toks[i].upper()
            neg = False
            if t == "NOT":
                neg = True
                i += 1
                t = toks[i].upper()
            ok = True
            if t == "ALL":
                ok = True
            elif t == "UNSEEN":
                ok = "\\Seen" not in x["flags"]
            elif t == "SEEN":
                ok = "\\Seen" in x["flags"]
            elif t == "FLAGGED":
                ok = "\\Flagged" in x["flags"]
            elif t == "UID":
                i += 1
                lo = int(toks[i].split(":")[0])
                ok = x["uid"] >= lo
            elif t == "HEADER":
                name = toks[i + 1].strip('"').lower()
                v = toks[i + 2].strip('"').lower()
                i += 2
                ok = any(l.lower().startswith(name + ":") and v in l.lower() for l in head.splitlines())
            elif t in ("TEXT", "FROM", "TO", "SUBJECT"):
                i += 1
                v = toks[i].strip('"').lower()
                hay = raw if t == "TEXT" else "\n".join(l for l in head.splitlines() if l.lower().startswith(t.lower() + ":"))
                ok = v in hay
            if ok == neg:
                return False
            i += 1
        return True


class SmtpH(socketserver.StreamRequestHandler):
    def send(self, s):
        self.wfile.write(s.encode())
        self.wfile.flush()

    def handle(self):
        st = self.server.store
        self.send("220 fake smtp\r\n")
        rc, auth = [], False
        while True:
            ln = self.rfile.readline()
            if not ln:
                return
            ln = ln.decode().rstrip("\r\n")
            u = ln.upper()
            if u.startswith("EHLO") or u.startswith("HELO"):
                self.send("250-fake\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
            elif u.startswith("AUTH PLAIN"):
                parts = base64.b64decode(ln.split()[2]).split(b"\0")
                if parts[-1].decode() == self.server.password:
                    auth = True
                    self.send("235 ok\r\n")
                else:
                    self.send("535 bad\r\n")
            elif u.startswith("MAIL FROM"):
                rc = []
                self.send("250 ok\r\n")
            elif u.startswith("RCPT TO"):
                rc.append(re.search(r"<([^>]*)>", ln).group(1))
                self.send("250 ok\r\n")
            elif u == "DATA":
                self.send("354 go\r\n")
                buf = b""
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b".\n"):
                        break
                    buf += l
                st.sent_smtp.append((list(rc), buf, auth))
                self.send("250 queued\r\n")
            elif u == "QUIT":
                self.send("221 bye\r\n")
                return
            else:
                self.send("250 ok\r\n")


class Srv(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(password="secret"):
    st = Store()
    imap, smtp = Srv(("127.0.0.1", 0), ImapH), Srv(("127.0.0.1", 0), SmtpH)
    for s in (imap, smtp):
        s.store, s.password = st, password
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return st, imap.server_address[1], smtp.server_address[1], (imap, smtp)
