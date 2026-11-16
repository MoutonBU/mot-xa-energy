"""Uploads the installer to the PRIVATE Supabase storage bucket 'releases' (in parts of 40 MB, so any plan accepts it)
and then writes latest.json. Only signed-in users can read the bucket, so nothing is public and no token is needed."""
import json, os, sys, urllib.request, urllib.error

URL = os.environ["SB_URL"].rstrip("/")
KEY = os.environ["SB_SERVICE_KEY"].strip()
VER = os.environ["APP_VER"]
SRC = sys.argv[1]
PART = 40 * 1024 * 1024


def hdr(extra=None):
    h = {"apikey": KEY}
    if KEY.startswith("eyJ"):
        h["Authorization"] = "Bearer " + KEY
    h.update(extra or {})
    return h


def call(method, path, data=None, extra=None, timeout=600):
    req = urllib.request.Request(URL + "/storage/v1" + path, data=data, headers=hdr(extra), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


old = []
try:
    old = [p["f"] for p in json.loads(call("GET", "/object/authenticated/releases/latest.json")).get("parts", [])]
except Exception as ex:
    print("no previous release listed:", ex)

parts = []
with open(SRC, "rb") as f:
    i = 0
    while True:
        b = f.read(PART)
        if not b:
            break
        name = "v%s/part_%03d" % (VER, i)
        call("POST", "/object/releases/" + name, b, {"x-upsert": "true", "Content-Type": "application/octet-stream"})
        parts.append({"f": name, "size": len(b)})
        print("uploaded", name, len(b))
        i += 1
meta = {"version": VER, "name": "MOT_XA_Energy_Setup.exe", "parts": parts}
call("POST", "/object/releases/latest.json", json.dumps(meta).encode(), {"x-upsert": "true", "Content-Type": "application/json"})
print("latest.json written for", VER)
if old:
    try:
        call("DELETE", "/object/releases", json.dumps({"prefixes": old}).encode(), {"Content-Type": "application/json"})
        print("removed the previous version's parts:", len(old))
    except Exception as ex:
        print("could not remove old parts:", ex)
