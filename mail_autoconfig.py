"""Find the mail server for an email address and check that the password works, so a user only types address + password."""
import re
import smtplib
import socket
import ssl
import urllib.request
import xml.etree.ElementTree as ET

KNOWN = {
    "gmail.com": ("smtp.gmail.com", 465, "SSL"), "googlemail.com": ("smtp.gmail.com", 465, "SSL"),
    "outlook.com": ("smtp-mail.outlook.com", 587, "STARTTLS"), "hotmail.com": ("smtp-mail.outlook.com", 587, "STARTTLS"),
    "live.com": ("smtp-mail.outlook.com", 587, "STARTTLS"), "yahoo.com": ("smtp.mail.yahoo.com", 465, "SSL"),
    "icloud.com": ("smtp.mail.me.com", 587, "STARTTLS"), "me.com": ("smtp.mail.me.com", 587, "STARTTLS"),
}
APP_PASSWORD_DOMAINS = {"gmail.com": "https://myaccount.google.com/apppasswords", "googlemail.com": "https://myaccount.google.com/apppasswords",
                        "yahoo.com": "https://login.yahoo.com/account/security", "icloud.com": "https://account.apple.com", "me.com": "https://account.apple.com"}


def parse_autoconfig(xml_text, email):
    """Mozilla autoconfig XML -> [(host, port, security, username)] for the outgoing server."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    local, dom = email.split("@", 1)
    for s in root.iter("outgoingServer"):
        if (s.get("type") or "smtp") != "smtp":
            continue
        host = (s.findtext("hostname") or "").strip()
        port = int((s.findtext("port") or "587").strip() or 587)
        sock = (s.findtext("socketType") or "STARTTLS").upper()
        sec = "SSL" if sock in ("SSL", "TLS") else "STARTTLS" if sock == "STARTTLS" else "None"
        user = (s.findtext("username") or "%EMAILADDRESS%").replace("%EMAILADDRESS%", email).replace("%EMAILLOCALPART%", local).replace("%EMAILDOMAIN%", dom)
        if host:
            out.append((host, port, sec, user))
    return out


def fetch(url, timeout=6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


def candidates(email):
    local, dom = email.lower().split("@", 1)
    c = []
    if dom in KNOWN:
        h, p, s = KNOWN[dom]
        c.append((h, p, s, email))
        if h == "smtp.gmail.com":
            c.append((h, 587, "STARTTLS", email))
    for url in ("https://autoconfig.%s/mail/config-v1.1.xml" % dom, "https://%s/.well-known/autoconfig/mail/config-v1.1.xml" % dom,
                "https://autoconfig.thunderbird.net/v1.1/%s" % dom):
        c += parse_autoconfig(fetch(url), email)
        if c:
            break
    for h in ("smtp.%s" % dom, "mail.%s" % dom, dom):
        for p, s in ((465, "SSL"), (587, "STARTTLS")):
            c.append((h, p, s, email))
    seen, out = set(), []
    for x in c:
        if x[:3] not in seen:
            seen.add(x[:3])
            out.append(x)
    return out


def try_login(host, port, sec, user, password, timeout=12):
    """('ok' | 'auth' | 'down', detail). 'auth' = server found but the login was refused; 'down' = could not reach or talk to it."""
    try:
        ctx = ssl.create_default_context()
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout) if sec == "SSL" else smtplib.SMTP(host, port, timeout=timeout)
        try:
            if sec != "SSL":
                s.ehlo()
                if sec == "STARTTLS":
                    s.starttls(context=ctx)
                    s.ehlo()
            s.login(user, password)
            return "ok", ""
        finally:
            try:
                s.quit()
            except Exception:
                pass
    except smtplib.SMTPAuthenticationError as e:
        return "auth", (e.smtp_error.decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e))[:160]
    except socket.timeout:
        return "down", "no answer (timed out): a firewall, antivirus or the network may be blocking mail"
    except ssl.SSLError as e:
        return "down", "secure connection failed: %s" % (getattr(e, "reason", None) or e)
    except (OSError, smtplib.SMTPException) as e:
        return "down", "%s: %s" % (type(e).__name__, e)


def detect(email, password, progress=None):
    """Returns {"smtp_host", "smtp_port", "smtp_security", "smtp_user"}; raises RuntimeError with a plain reason."""
    email = email.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise RuntimeError("that does not look like an email address")
    refused, first_err = None, ""
    for host, port, sec, user in candidates(email):
        if progress:
            progress("Trying %s ..." % host)
        users = [user] + ([email.split("@")[0]] if user == email else [])
        for u in users:
            r, why = try_login(host, port, sec, u, password)
            if r == "down" and not first_err:
                first_err = "%s port %d: %s" % (host, port, why)
            if r == "auth":
                refused_why = why
            if r == "ok":
                return {"smtp_host": host, "smtp_port": port, "smtp_security": sec, "smtp_user": u}
            if r == "auth":
                refused = host
            if r == "down":
                break
        if refused:
            break
    dom = email.split("@")[1].lower()
    if refused:
        if dom in APP_PASSWORD_DOMAINS:
            raise RuntimeError("%s refused the password. %s needs a special app password instead of your normal one." % (refused, dom.split(".")[0].title()))
        raise RuntimeError("%s found your mail account but refused the email or password. Check them and try again." % refused)
    if dom in KNOWN and first_err:
        raise RuntimeError("could not reach %s. %s" % (KNOWN[dom][0], first_err))
    raise RuntimeError("could not find the mail server for %s. Tick \"Other ways to connect\" and type the outgoing (SMTP) server, which your email provider can tell you." % dom)
