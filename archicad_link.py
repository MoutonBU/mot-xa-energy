import re
"""Archicad link (WIP, work in progress).

Talks to a running Archicad through its JSON command interface on this computer (the same one the official Python
package uses; no extra package needed). Tapir, the free community add-on, is used when it is installed, for the
things the official commands do not give (which storey an element is on, polygon outlines).
Everything here is read only: nothing is written back to Archicad."""
import json
import math
import urllib.request

import time

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QDialog, QLineEdit, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QFileDialog)

PORTS = range(19723, 19743)


class LinkError(Exception):
    pass


class ACLink:
    def __init__(self, log=None):
        self.port = None
        self.log = log or (lambda s: None)
        self.tapir_ok = False

    # ---- the wire
    def _post(self, body, port=None, timeout=60):
        req = urllib.request.Request("http://127.0.0.1:%d" % (port or self.port), data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def connect(self):
        for port in PORTS:
            try:
                r = self._post({"command": "API.GetProductInfo"}, port, timeout=2)
            except Exception:
                continue
            if r.get("succeeded"):
                self.port = port
                self.log("Connected on port %d: %s" % (port, json.dumps(r.get("result"))))
                return r["result"]
        raise LinkError("Archicad was not found. Open Archicad with your project, then try again.")

    def call(self, command, params=None):
        body = {"command": command}
        if params is not None:
            body["parameters"] = params
        self.log("-> %s" % command)
        r = self._post(body)
        if not r.get("succeeded"):
            self.log("   failed: %s" % json.dumps(r.get("error"))[:300])
            raise LinkError("%s: %s" % (command, (r.get("error") or {}).get("message", "failed")))
        res = r.get("result") or {}
        self.log("   ok: " + json.dumps(res)[:240])
        return res

    def tapir(self, name, params=None):
        res = self.call("API.ExecuteAddOnCommand", {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
                                                    "addOnCommandParameters": params or {}})
        return res.get("addOnCommandResponse", res)

    def check_tapir(self):
        self.tapir_ok = False
        try:
            r = self.call("API.IsAddOnCommandAvailable", {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": "GetStories"}})
            self.tapir_ok = bool(r.get("isAvailable"))
        except Exception:
            pass
        if not self.tapir_ok:                      # the question may not be answered the way we expect: just try a command
            try:
                self.tapir("GetStories")
                self.tapir_ok = True
            except Exception:
                pass
        return self.tapir_ok

    # ---- reading
    def elements(self, etype):
        r = self.call("API.GetElementsByType", {"elementType": etype})
        return r.get("elements", [])

    def stories(self):
        """{floorIndex: name}"""
        out = {}
        for fn in (lambda: self.call("API.GetStories"), lambda: self.tapir("GetStories")):
            try:
                r = fn()
                for s in r.get("stories", []):
                    out[s.get("index", s.get("floorIndex"))] = s.get("name") or s.get("floorName") or ""
                if out:
                    return out
            except Exception:
                pass
        return out

    def _prop_ids(self, wanted):
        """Look up built-in property ids. wanted: list of (key, [name fragments in order of preference])"""
        names = []
        try:
            r = self.call("API.GetAllPropertyNames")
            names = [p.get("nonLocalizedName", "") for p in r.get("properties", []) if p.get("type") == "BuiltIn"]
        except Exception:
            pass
        chosen = {}
        for key, prefs in wanted:
            for pref in prefs:
                hit = next((n for n in names if n == pref), None) or next((n for n in names if pref in n), None)
                if hit:
                    chosen[key] = hit
                    break
        if not chosen:
            return {}
        r = self.call("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName": n} for n in chosen.values()]})
        ids = {}
        for (key, _n), p in zip(chosen.items(), r.get("properties", [])):
            if "propertyId" in p:
                ids[key] = p["propertyId"]
        self.log("   property names used: %s" % json.dumps(chosen))
        return ids

    def zones(self):
        """The rooms (zones): name, number, area in m2, and the storey name when it can be found."""
        els = self.elements("Zone")
        if not els:
            return []
        ids = self._prop_ids([("name", ["Zone_ZoneName", "ZoneName"]), ("number", ["Zone_ZoneNumber", "ZoneNumber"]),
                              ("area", ["Zone_NetArea", "Zone_CalculatedArea", "NetArea", "Area"])])
        keys = [k for k in ("name", "number", "area") if k in ids]
        vals = {}
        if keys:
            for i in range(0, len(els), 500):
                chunk = els[i:i + 500]
                r = self.call("API.GetPropertyValuesOfElements", {"elements": chunk, "properties": [{"propertyId": ids[k]} for k in keys]})
                for j, row in enumerate(r.get("propertyValuesForElements", [])):
                    d = {}
                    for k, pv in zip(keys, row.get("propertyValues", [])):
                        d[k] = (pv.get("propertyValue") or {}).get("value")
                    vals[i + j] = d
        floors = {}
        if self.tapir_ok:
            try:
                det = self.tapir("GetDetailsOfElements", {"elements": els}).get("detailsOfElements", [])
                floors = {i: d.get("floorIndex") for i, d in enumerate(det)}
            except Exception:
                pass
        st = self.stories() if floors else {}
        out = []
        for i, _e in enumerate(els):
            v = vals.get(i, {})
            out.append({"room": str(v.get("name") or "").strip(), "unit": str(v.get("number") or "").strip(), "area": v.get("area"),
                        "level": st.get(floors.get(i), "") if floors else ""})
        return out

    # ---- the whole model, in the shape the program's own tables use
    def diagnose(self):
        out = []
        self.log("--- diagnose ---")
        try:
            out.append("Tapir installed: %s" % self.check_tapir())
        except Exception as e:
            out.append("Tapir check failed: %s" % e)
        for t in ("Zone", "Window", "Door", "Wall", "Slab", "Mesh", "Skylight", "Opening"):
            try:
                out.append("%s elements: %d" % (t, len(self.elements(t))))
            except Exception as e:
                out.append("%s: %s" % (t, e))
        try:
            r = self.call("API.GetAllPropertyNames")
            names = sorted(p.get("nonLocalizedName", "") for p in r.get("properties", []) if p.get("type") == "BuiltIn")
            keys = ("width", "height", "window", "door", "opening", "sill", "glaz", "wall", "composite", "structure", "zone")
            out.append("%d built-in properties. Matching: " % len(names))
            out += ["  " + n for n in names if any(k in n.lower() for k in keys)][:250]
        except Exception as e:
            out.append("Property names failed: %s" % e)
        # full replies for one window, one door and one room, and the GDL parameters of the window (so the exact field names are known)
        for t in ("Window", "Door", "Zone"):
            try:
                els = self.elements(t)[:1]
                if els and self.tapir_ok:
                    d = self.tapir("GetDetailsOfElements", {"elements": els})
                    out.append("FULL %s details: %s" % (t, json.dumps(d)[:6000]))
                    if t == "Window":
                        try:
                            g = self.tapir("GetGDLParametersOfElements", {"elements": els})
                            out.append("FULL Window GDL parameters: %s" % json.dumps(g)[:9000])
                        except Exception as e:
                            out.append("GDL parameters failed: %s" % e)
            except Exception as e:
                out.append("%s details failed: %s" % (t, e))
        try:
            r = self.call("API.GetAllPropertyNames")
            allnames = sorted(p.get("nonLocalizedName", "") for p in r.get("properties", []) if p.get("type") == "BuiltIn")
            out.append("ALL built-in property names: " + ", ".join(allnames))
        except Exception:
            pass
        self.log("\n".join(out))
        return out

    @staticmethod
    def _find_num(o, keys):
        """First number stored under one of keys anywhere in a details reply."""
        low = [k.lower() for k in keys]
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() in low and isinstance(v, (int, float)):
                    return float(v)
            for v in o.values():
                r = ACLink._find_num(v, keys)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = ACLink._find_num(v, keys)
                if r is not None:
                    return r
        return None

    @staticmethod
    def _guids(lst):
        out = []
        for e in lst or []:
            g = (e.get("elementId") or {}).get("guid") if isinstance(e, dict) else None
            if g:
                out.append(g)
        return out

    def _details(self, els):
        out = []
        for i in range(0, len(els), 400):
            out += self.tapir("GetDetailsOfElements", {"elements": els[i:i + 400]}).get("detailsOfElements", [])
        return out

    def _opening_prop_ids(self):
        """Find the width and height properties of doors and windows by their names (they differ between Archicad versions)."""
        try:
            r = self.call("API.GetAllPropertyNames")
        except Exception:
            return {}
        names = [p.get("nonLocalizedName", "") for p in r.get("properties", []) if p.get("type") == "BuiltIn"]

        def pick(word):
            bad = ("sill", "head", "frame", "wall", "reveal", "thick", "depth", "area", "volume", "perimeter", "marker", "sash", "panel", "glaz")
            cands = [n for n in names if word in n.lower() and not any(b in n.lower() for b in bad)]
            cands.sort(key=lambda n: (0 if ("opening" in n.lower()) else 1 if ("window" in n.lower() or "door" in n.lower()) else 2, len(n)))
            return cands
        out = {}
        for key, word in (("w", "width"), ("h", "height")):
            c = pick(word)
            self.log("   %s candidates: %s" % (word, c[:8]))
            if c:
                out[key] = c[0]
        if len(out) < 2:
            return {}
        r = self.call("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName": out["w"]}, {"type": "BuiltIn", "nonLocalizedName": out["h"]}]})
        ps = r.get("properties", [])
        if len(ps) == 2 and all("propertyId" in p for p in ps):
            self.log("   opening properties used: %s, %s" % (out["w"], out["h"]))
            return {"w": ps[0]["propertyId"], "h": ps[1]["propertyId"]}
        return {}

    def _prop_names(self):
        if not hasattr(self, "_pn"):
            try:
                r = self.call("API.GetAllPropertyNames")
                self._pn = [p.get("nonLocalizedName", "") for p in r.get("properties", []) if p.get("type") == "BuiltIn"]
            except Exception:
                self._pn = []
        return self._pn

    def _values(self, els, name):
        """One built-in property for many elements: a list of values (None where Archicad has none)."""
        out = [None] * len(els)
        try:
            ids = self.call("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName": name}]}).get("properties", [])
            if not ids or "propertyId" not in ids[0]:
                return out
            pid = ids[0]["propertyId"]
            for i in range(0, len(els), 500):
                r = self.call("API.GetPropertyValuesOfElements", {"elements": els[i:i + 500], "properties": [{"propertyId": pid}]})
                for j, row in enumerate(r.get("propertyValuesForElements", [])):
                    pv = row.get("propertyValues") or [{}]
                    v = (pv[0].get("propertyValue") or {}).get("value")
                    out[i + j] = v
        except Exception as e:
            self.log("   property %s failed: %s" % (name, e))
        return out

    def _first_name(self, any_of, none_of=()):
        c = [n for n in self._prop_names() if any(k in n.lower() for k in any_of) and not any(b in n.lower() for b in none_of)]
        c.sort(key=len)
        return c

    def _openings(self, etype):
        """[{guid, w, h, name, glazed_m2}] for every window or door (sizes in mm, glazed area in m2 or None)."""
        els = self.elements(etype)
        self.log("   %d %s elements" % (len(els), etype))
        if not els:
            return []
        wh = [(None, None)] * len(els)
        glz = [None] * len(els)
        dnames = [("", "")] * len(els)
        dpos = [None] * len(els)
        dfloor = [None] * len(els)
        if self.tapir_ok:
            try:
                det = self._details(els)
                dnames = [(str(d.get("id") or "").strip(), str(((d.get("details") or {}).get("libPart") or {}).get("name") or "").strip()) for d in det]
                dpos = [self._find_xy(d.get("details") or {}) for d in det]
                dfloor = [d.get("floorIndex") for d in det]
                wh = [(self._find_num(d, ("width", "openingWidth")), self._find_num(d, ("height", "openingHeight"))) for d in det]
                glz = [self._find_num(d, ("glazingArea", "glassArea", "glazedArea")) for d in det]
            except Exception as e:
                self.log("   details failed: %s" % e)
        if any(w is None or h is None for w, h in wh):
            ids = self._opening_prop_ids()
            if "w" in ids and "h" in ids:
                for i in range(0, len(els), 500):
                    chunk = els[i:i + 500]
                    r = self.call("API.GetPropertyValuesOfElements", {"elements": chunk, "properties": [{"propertyId": ids["w"]}, {"propertyId": ids["h"]}]})
                    for j, row in enumerate(r.get("propertyValuesForElements", [])):
                        pv = [(p.get("propertyValue") or {}).get("value") for p in row.get("propertyValues", [])]
                        if len(pv) == 2 and wh[i + j][0] is None:
                            wh[i + j] = (pv[0], pv[1])
        # the name the architect gave it (Element ID, like W01 or Window 1), else the library part name
        ids_ = [None] * len(els)
        for nm in self._first_name(("elementid", "element_id")):
            ids_ = self._values(els, nm)
            self.log("   name from %s: %s" % (nm, [v for v in ids_ if v][:6]))
            if any(ids_):
                break
        libs = [None] * len(els)
        for nm in self._first_name(("librarypart", "libpart")):
            libs = self._values(els, nm)
            self.log("   library part name from %s: %s" % (nm, [v for v in libs if v][:6]))
            if any(libs):
                break
        if not any(g is not None for g in glz):
            for nm in self._first_name(("glaz", "glass"), ("frame", "sash", "perimeter", "thick")):
                if "area" in nm.lower() or "surface" in nm.lower():
                    glz = self._values(els, nm)
                    self.log("   glazed area from %s: %s" % (nm, [v for v in glz if v is not None][:6]))
                    if any(v for v in glz):
                        break
        libn = [(dn[1] or str(lb or "")) for dn, lb in zip(dnames, libs)]
        gdl = {}
        try:
            gdl = self._gdl_by_libpart(els, libn)
        except Exception as ex:
            self.log("   library settings failed: %s" % ex)
        out = []
        for e, (w, h), nid, lib, gl, dn, pos, fl, ln in zip(els, wh, ids_, libs, glz, dnames, dpos, dfloor, libn):
            nid = dn[0] or nid
            lib = dn[1] or lib
            g = (e.get("elementId") or {}).get("guid")
            if g and w and h:
                # Archicad reports lengths in metres
                wm, hm = int(round(float(w) * 1000)), int(round(float(h) * 1000))
                src = "model"
                if not (isinstance(gl, (int, float)) and gl > 0):
                    gl, npan, word = self._gdl_read(gdl.get(ln), wm, hm)
                    src = "library part"
                else:
                    _g, npan, word = self._gdl_read(gdl.get(ln), wm, hm)
                out.append({"guid": g, "w": wm, "h": hm,
                            "name": (str(nid or "").strip() or str(lib or "").strip()),
                            "glazed_m2": float(gl) if isinstance(gl, (int, float)) and gl > 0 else None,
                            "glazed_src": src, "panels": npan, "open_word": word, "lib": ln,
                            "xy": pos, "floor": fl})
        self.log("   %d of %d %s elements had a size; %d named; %d with a glazed area" % (
            len(out), len(els), etype, sum(1 for o in out if o["name"]), sum(1 for o in out if o["glazed_m2"])))
        return out

    # ---- library part (GDL) settings: glass and how the window opens
    def _gdl_by_libpart(self, els, names):
        """{libpart name: {parameter name/description (lower): value}} using one element per library part."""
        first = {}
        for e, n in zip(els, names):
            if n and n not in first:
                first[n] = e
        out = {}
        if not first or not self.tapir_ok:
            return out
        keys = list(first)
        for i in range(0, len(keys), 50):
            ks = keys[i:i + 50]
            try:
                r = self.tapir("GetGDLParametersOfElements", {"elements": [first[k] for k in ks]})
            except Exception as e:
                self.log("   GDL parameters failed: %s" % e)
                return out
            lst = r.get("gdlParametersOfElements") or r.get("parametersOfElements") or []
            for k, entry in zip(ks, lst):
                flat = {}

                def walk(o):
                    if isinstance(o, dict):
                        if "name" in o and "value" in o and not isinstance(o["value"], (dict, list)):
                            for key in (o.get("name"), o.get("description")):
                                if key:
                                    flat[str(key).lower()] = o["value"]
                        for v in o.values():
                            if isinstance(v, (dict, list)):
                                walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v)
                walk(entry)
                out[k] = flat
        self.log("   library part settings read for %d type(s): %s" % (len(out), ", ".join("%s (%d)" % (k, len(v)) for k, v in out.items())[:300]))
        return out

    @staticmethod
    def _gdl_read(par, w_mm, h_mm):
        """From one library part's settings: (glazed m2 or None, panels, opening word) - an estimate, noted as such."""
        if not par:
            return None, None, ""

        def num(*words, bad=()):
            for k, v in par.items():
                if all(w in k for w in words) and not any(b in k for b in bad) and isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(v)
            return None
        gl = num("glass", "area") or num("glazing", "area") or num("glazed", "area")
        n = num("number", "panel") or num("number", "sash") or num("number", "leaf") or num("panel", "count") or num("sash", "count")
        f = num("frame", "width", bad=("height",)) or num("frame", "thickness") or num("frame", "wid")
        word = ""
        for k, v in par.items():
            if isinstance(v, str) and any(t in k for t in ("opening", "operation", "type", "style", "sash")) and any(t in v.lower() for t in ("fixed", "casement", "tilt", "slid", "hung", "turn", "awning", "open")):
                word = v.lower()
                break
        w, h = w_mm / 1000.0, h_mm / 1000.0
        if gl is not None:
            gl = gl if gl < 100 else gl / 1e6
            return gl, (int(n) if n else None), word
        if f:
            f = f / 1000.0 if f > 1 else f
            nn = max(1, int(n)) if n else 1
            g = max(0.0, (w - 2 * f - (nn - 1) * f)) * max(0.0, (h - 2 * f))
            return (g if g > 0 else None), (nn if n else None), word
        return None, (int(n) if n else None), word

    @staticmethod
    def _find_xy(o, depth=0):
        """The (x, y) position in metres stored in a window/door details reply, or None."""
        if depth > 4:
            return None
        if isinstance(o, dict):
            if isinstance(o.get("x"), (int, float)) and isinstance(o.get("y"), (int, float)):
                return (float(o["x"]), float(o["y"]))
            pref = [k for k in o if any(w in k.lower() for w in ("coord", "pos", "loc", "origo", "beg", "center"))]
            for k in pref + [k for k in o if k not in pref and k != "libPart"]:
                r = ACLink._find_xy(o[k], depth + 1)
                if r:
                    return r
        return None

    @staticmethod
    def _dist_poly(p, poly):
        """Distance in metres from point p to a polygon's outline (0 when inside)."""
        import math
        x, y = p
        inside = False
        best = 1e9
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
                inside = not inside
            dx, dy = x2 - x1, y2 - y1
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
        return 0.0 if inside else best

    def _connected(self, zones, etype):
        """For each zone, the set of guids of the windows or doors that belong to it."""
        res = [set() for _ in zones]
        if not self.tapir_ok or not zones:
            return res
        try:
            r = self.tapir("GetConnectedElements", {"elements": zones, "connectedElementType": etype})
            ce = r.get("connectedElements", [])
            if len(ce) == len(zones):
                for i, entry in enumerate(ce):
                    lst = entry.get("elements", entry if isinstance(entry, list) else [entry]) if isinstance(entry, (dict, list)) else []
                    res[i] = set(self._guids(lst))
                return res
        except Exception as e:
            self.log("   batch connected failed: %s" % e)
        for i, z in enumerate(zones):
            try:
                r = self.tapir("GetConnectedElements", {"elements": [z], "connectedElementType": etype})
                ce = r.get("connectedElements", [])
                if ce:
                    entry = ce[0]
                    lst = entry.get("elements", []) if isinstance(entry, dict) else entry
                    res[i] = set(self._guids(lst))
            except Exception:
                pass
        return res

    def model(self, ignore=()):
        """Rooms, windows and doors of the open project, shaped like the program's IFC import:
        {'rooms': [{name, area, tags{tag: n}, floor, elev}], 'items': [{tag, width, height, kind, qty, glazed, openable}]}"""
        zones = self.elements("Zone")
        zr = self.zones()
        floors, zpoly, zfloor = {}, {}, {}
        if self.tapir_ok and zones:
            try:
                det = self._details(zones)
                st = self.stories()
                floors = {i: st.get(d.get("floorIndex"), "") for i, d in enumerate(det)}
                zfloor = {i: d.get("floorIndex") for i, d in enumerate(det)}
                zpoly = {i: self._find_poly(d) for i, d in enumerate(det)}
            except Exception:
                pass
        items, tagof = {}, {}
        used = {}
        opos = {}
        for etype, kind, pre in (("Window", "Window", "W"), ("Door", "Door", "D")):
            groups, meta = {}, {}
            for o in self._openings(etype):
                opos[o["guid"]] = (o["xy"], o["floor"], etype)
                gz = round(o["glazed_m2"], 2) if o["glazed_m2"] else None
                groups.setdefault((o["name"], o["w"], o["h"], gz), []).append(o["guid"])
                meta[(o["name"], o["w"], o["h"], gz)] = (o["glazed_src"], o["panels"], o["open_word"], o["lib"])
            for (nm, w, h, gz), guids in groups.items():
                base = re.sub(r"[,:;]", "-", (nm or "%s%dx%d" % (pre, w, h))).strip().upper()
                n = used[base] = used.get(base, 0) + 1
                tag = base if n == 1 else "%s_%d" % (base, n)
                area = w * h / 1e6
                if gz:
                    pct = max(0.0, min(100.0, gz / area * 100.0)) if area else 0.0
                    note = "From Archicad: size and glazed area (%.2f m2) are read from the model. Hover the row to set how it opens." % gz
                else:
                    pct = 85.0 if kind == "Window" else 0.0
                    note = "From Archicad: the size is read from the model; the glazed % is typical. Hover the row to change it."
                src, npan, word, lib = meta[(nm, w, h, gz)]
                if gz and src == "library part":
                    note = "From Archicad: size from the model; glazed area (%.2f m2) estimated from the library part '%s'. Hover the row to check how it opens." % (gz, lib)
                items[tag] = {"ac_panels": npan, "ac_word": word, "tag": tag, "width": float(w), "height": float(h), "kind": kind, "qty": len(guids), "style": "Custom",
                              "glazed": pct, "glazed_m2": float(gz or 0.0), "openable": 50.0 if kind == "Window" else 100.0,
                              "flag": [], "note": note, "from_ac_glazed": bool(gz)}
                for g in guids:
                    tagof[g] = tag
        rooms = []
        conns = {et: self._connected(zones, et) for et in ("Window", "Door")} if zones else {}
        for et in ("Window", "Door"):                         # Archicad does not tie windows to rooms: use where they sit
            if zones and not any(conns.get(et, [])) and zpoly:
                n_ = 0
                for g, (xy, fl, et2) in opos.items():
                    if et2 != et or not xy:
                        continue
                    cands = sorted((self._dist_poly(xy, zpoly[i]), i) for i in zpoly
                                   if zpoly[i] and (fl is None or zfloor.get(i) in (None, fl)))
                    near = [i for d_, i in cands if d_ <= 0.6] or []
                    if et == "Window" and near:
                        near = near[:1]
                    for i in near:
                        conns[et][i].add(g)
                        n_ += 1
                self.log("   %s: placed %d against room outlines (no room links from Archicad)" % (et, n_))
        for i, z in enumerate(zr):
            if not z["area"]:
                continue
            tags = {}
            for et in ("Window", "Door"):
                for g in conns.get(et, [set()] * len(zr))[i]:
                    if g in tagof:
                        tags[tagof[g]] = tags.get(tagof[g], 0) + 1
            nm_ = z["room"] or ("Zone " + (z["unit"] or str(i + 1)))
            if any(w_ and w_ in nm_.lower() for w_ in ignore):
                continue
            rooms.append({"name": nm_, "area": float(z["area"]), "tags": tags,
                          "floor": floors.get(i) or z["level"] or "Ground Floor", "elev": 0.0})
        return {"rooms": rooms, "items": list(items.values()), "n_zones": len(zones), "n_win": sum(i["qty"] for i in items.values() if i["kind"] == "Window"),
                "n_door": sum(i["qty"] for i in items.values() if i["kind"] == "Door")}

    @staticmethod
    def _find_poly(o):
        """Find a list of corner points anywhere in a details reply."""
        if isinstance(o, dict):
            for k in ("polygonCoordinates", "coordinates", "polygon"):
                v = o.get(k)
                pts = ACLink._pts(v)
                if pts:
                    return pts
            for v in o.values():
                r = ACLink._find_poly(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = ACLink._find_poly(v)
                if r:
                    return r
        return None

    @staticmethod
    def _pts(v):
        if not isinstance(v, list) or len(v) < 3:
            return None
        try:
            if isinstance(v[0], dict):
                return [(float(p["x"]), float(p["y"])) for p in v]
            return [(float(p[0]), float(p[1])) for p in v]
        except Exception:
            return None

    def outlines(self, types=("Slab", "Mesh", "Zone")):
        """Closed outlines (metres) that could be the stand: [(label, area, points)] biggest first. Needs Tapir."""
        if not self.tapir_ok:
            raise LinkError("The outlines need the Tapir add-on in Archicad (Options > Add-On Manager). The rooms work without it.")
        out = []
        for t in types:
            try:
                els = self.elements(t)
            except Exception:
                continue
            if not els:
                continue
            det = self.tapir("GetDetailsOfElements", {"elements": els[:400]}).get("detailsOfElements", [])
            for d in det:
                pts = self._find_poly(d)
                if pts:
                    a = 0.0
                    for i in range(len(pts)):
                        x1, y1, x2, y2 = pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
                        a += x1 * y2 - x2 * y1
                    out.append(("%s, %.1f m2" % (t, abs(a) / 2), abs(a) / 2, pts))
        out.sort(key=lambda t_: -t_[1])
        return out


class ArchicadDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Archicad link (WIP, work in progress)")
        self.resize(640, 520)
        self.link = ACLink(self.say)
        v = QVBoxLayout(self)
        lab = QLabel("Reads from the Archicad project that is open on this computer. Nothing is changed in Archicad.\n"
                     "Open Archicad with your project first. The Tapir add-on is optional: it adds the storey names and the outlines.")
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.status = QLabel("Not connected.")
        self.status.setStyleSheet("font-weight:600;")
        v.addWidget(self.status)
        row = QHBoxLayout()
        for text, fn in (("Connect and test", self.connect_test), ("Rooms to Area schedule", self.rooms_to_schedule),
                         ("Stand outline to Building lines", self.stand_to_lines), ("Save the log...", self.save_log)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        v.addLayout(row)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        v.addWidget(self.out, 1)

    def say(self, s):
        self.out.appendPlainText(s)

    def _ready(self):
        try:
            if self.link.port is None:
                self.connect_test()
            return self.link.port is not None
        except Exception:
            return False

    def connect_test(self):
        try:
            info = self.link.connect()
            tp = self.link.check_tapir()
            self.status.setText("Connected to Archicad %s. Tapir: %s" % (info.get("version", info.get("buildNumber", "")), "found" if tp else "not found"))
            for t in ("Zone", "Slab", "Mesh"):
                try:
                    self.say("%s elements: %d" % (t, len(self.link.elements(t))))
                except Exception as e:
                    self.say("%s: %s" % (t, e))
        except Exception as e:
            self.status.setText(str(e))
            self.say(str(e))

    def rooms_to_schedule(self):
        if not self._ready():
            return
        ap = getattr(self.win, "area_page", None)
        try:
            zs = self.link.zones()
        except Exception as e:
            QMessageBox.warning(self, "Archicad link", str(e))
            return
        zs = [z for z in zs if z["room"] or z["area"]]
        if not zs or ap is None:
            QMessageBox.information(self, "Archicad link", "No rooms (zones) were found in the open project.")
            return
        miss = sum(1 for z in zs if z["area"] in (None, ""))
        ap._bulk_add([{"level": z["level"], "unit": z["unit"], "room": z["room"], "area": z["area"]} for z in zs])
        self.say("%d rooms added to the Area schedule%s." % (len(zs), (" (%d without an area)" % miss) if miss else ""))

    def stand_to_lines(self):
        if not self._ready():
            return
        sp = getattr(self.win, "site_page", None)
        try:
            cands = self.link.outlines()
        except Exception as e:
            QMessageBox.warning(self, "Archicad link", str(e))
            return
        if not cands or sp is None:
            QMessageBox.information(self, "Archicad link", "No outlines were found. Draw the site as a Mesh or a Slab (or a Zone) in Archicad, then try again.")
            return
        item, ok = QInputDialog.getItem(self, "Archicad link", "Which outline is the stand?", ["%d. %s" % (i + 1, c[0]) for i, c in enumerate(cands)], 0, False)
        if ok:
            sp.apply_stand_polygon(cands[int(item.split(".")[0]) - 1][2])
            self.say("Stand drawn from the Archicad outline.")

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the log", "archicad_link_log.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.out.toPlainText())


class _Fetch(QThread):
    done = Signal(object)

    def __init__(self, ignore=(), diagnose=False):
        super().__init__()
        self.ignore, self.diag = ignore, diagnose

    def run(self):
        lg = []
        link = ACLink(lg.append)
        try:
            link.connect()
            link.check_tapir()
            if self.diag:
                self.done.emit({"diag": link.diagnose(), "log": lg})
                return
            m = link.model(self.ignore)
            m["tapir"] = link.tapir_ok
            self.done.emit({"model": m, "log": lg})
        except Exception as e:
            self.done.emit({"error": str(e), "log": lg})


class LivePanel(QDialog):
    """A narrow window to keep open beside Archicad: follows the design, updates the schedules and shows where it breaks the rules."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Live design check (WIP)")
        self.resize(380, 720)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.sig = None
        self.busy = False
        self.log = []
        v = QVBoxLayout(self)
        self.head = QLabel("Not started.")
        self.head.setStyleSheet("font-weight:700; font-size:15px;")
        v.addWidget(self.head)
        self.sub = QLabel("")
        self.sub.setWordWrap(True)
        v.addWidget(self.sub)
        row = QHBoxLayout()
        self.btn = QPushButton("Start live")
        self.btn.clicked.connect(self.toggle)
        now = QPushButton("Refresh now")
        now.clicked.connect(lambda: self.tick(force=True))
        row.addWidget(self.btn)
        row.addWidget(now)
        v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Check every"))
        self.every = QDoubleSpinBox()
        self.every.setRange(1, 60)
        self.every.setValue(3)
        self.every.setSuffix(" s")
        row2.addWidget(self.every)
        self.top = QCheckBox("Keep on top")
        self.top.setChecked(True)
        self.top.toggled.connect(self._ontop)
        row2.addWidget(self.top)
        row2.addStretch(1)
        v.addLayout(row2)
        v.addWidget(QLabel("Ignore rooms whose name has (comma separated):"))
        self.ignore = QLineEdit(str(self._setting("ac_ignore", "gross area, site, sqm, typical, total")))
        self.ignore.setToolTip("Zones that are not rooms: gross areas, the site, totals. They are left out of every check.")
        self.ignore.editingFinished.connect(self._ignore_changed)
        v.addWidget(self.ignore)
        dg = QPushButton("Diagnose what Archicad offers")
        dg.setToolTip("Lists what the link can see. Save the log and send it if windows or doors do not come through.")
        dg.clicked.connect(self.diagnose)
        v.addWidget(dg)
        self.out = QLabel("")
        self.out.setTextFormat(Qt.TextFormat.RichText)
        self.out.setWordWrap(True)
        self.out.setAlignment(Qt.AlignmentFlag.AlignTop)
        from PySide6.QtWidgets import QScrollArea
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.out)
        v.addWidget(sc, 1)
        self.tp = QPushButton("Install the Tapir add-on...")
        self.tp.setToolTip("Starts the Tapir installer that came with this program. Archicad must be closed.")
        self.tp.clicked.connect(self.install_tapir)
        v.addWidget(self.tp)
        sv = QPushButton("Save the log...")
        sv.clicked.connect(self.save_log)
        v.addWidget(sv)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.th = None

    def _setting(self, k, default):
        try:
            import sys
            mod = sys.modules.get("__main__")
            return (getattr(mod, "SETTINGS", {}) or {}).get(k, default)
        except Exception:
            return default

    def _ignore_changed(self):
        try:
            import sys
            mod = sys.modules.get("__main__")
            mod.SETTINGS["ac_ignore"] = self.ignore.text()
            mod.save_settings()
        except Exception:
            pass
        self.sig = None
        if self.timer.isActive():
            self.tick(force=True)

    def _ignore_words(self):
        return tuple(w.strip().lower() for w in self.ignore.text().split(",") if w.strip())

    def diagnose(self):
        if self.busy:
            return
        self.busy = True
        self.th = _Fetch((), True)
        self.th.done.connect(self._got)
        self.th.start()

    def install_tapir(self):
        import os
        import sys
        from PySide6.QtWidgets import QMessageBox
        p = os.path.join(os.path.dirname(sys.executable), "tapir", "TapirInstaller.exe")
        if not os.path.exists(p):
            QMessageBox.information(self, "Tapir", "The Tapir installer is not part of this build. Get it from github.com/ENZYME-APD/tapir-archicad-automation "
                                    "(Releases), or in Archicad: Options > Add-On Manager.")
            return
        try:
            os.startfile(p)
        except Exception as e:
            QMessageBox.warning(self, "Tapir", str(e))

    def _ontop(self, on):
        vis = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        if vis:
            self.show()

    def toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.btn.setText("Start live")
            self.head.setText("Paused.")
        else:
            if not getattr(self.win, "_ac_taken", False):
                from PySide6.QtWidgets import QMessageBox
                if QMessageBox.question(self, "Live design check", "Live mode takes over the rooms, windows and doors in Light and Ventilation, "
                                        "and the Area schedule: they follow Archicad and anything typed there is replaced when the design changes.\n\n"
                                        "Continue?") != QMessageBox.StandardButton.Yes:
                    return
            self.btn.setText("Stop live")
            self.timer.start(int(self.every.value() * 1000))
            self.tick(force=True)

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)

    def tick(self, force=False):
        if self.busy:
            return
        self.busy = True
        self.th = _Fetch(self._ignore_words())
        self.th.done.connect(self._got)
        self.th.start()
        self._force = force

    def _got(self, r):
        self.busy = False
        self.log = (self.log + r.get("log", []))[-400:]
        if "diag" in r:
            self.head.setText("Diagnosis")
            self.sub.setText("Save the log and send it if something is missing.")
            self.out.setText("<pre>" + "\n".join(x.replace("<", "&lt;") for x in r["diag"]) + "</pre>")
            return
        if "error" in r:
            self.head.setText("Archicad not reachable")
            self.sub.setText(r["error"])
            return
        m = r["model"]
        sig = json.dumps({"r": m["rooms"], "i": sorted(m["items"], key=lambda x: x["tag"])}, sort_keys=True)
        changed = sig != self.sig or getattr(self, "_force", False)
        if changed:
            self.sig = sig
            t0 = time.time()
            try:
                self.win.apply_archicad_model(m)
            except Exception as e:
                self.log.append("apply failed: %r" % e)
                self.head.setText("Could not apply the model")
                self.sub.setText(str(e))
                return
            self.show_results(m, time.time() - t0)
        self.head.setText(("\u25cf Live" if self.timer.isActive() else "Updated") + "  " + time.strftime("%H:%M:%S"))
        self.sub.setText("%d rooms, %d windows, %d doors%s" % (len(m["rooms"]), m["n_win"], m["n_door"],
                         "" if m.get("tapir") else "   Tapir not found: windows and doors cannot be tied to rooms. Install the free Tapir add-on in Archicad (Options > Add-On Manager)."))

    def show_results(self, m, secs):
        w = self.win
        ok, bad = "#2e9e5b", "#c8102e"
        h = []
        res = getattr(w, "results", []) or []
        need = [r for r in res if not r["circulation"] and not r["no_area"]]
        fails = [r for r in need if not (r["light_ok"] and r["vent_ok"])]
        h.append("<h3>Light and ventilation (SANS 10400-O)</h3>")
        h.append("<p style='color:%s'><b>%d of %d rooms pass</b></p>" % (ok if not fails else bad, len(need) - len(fails), len(need)))
        for r in fails:
            why = []
            if not r["light_ok"]:
                why.append("light %.1f%% (min %.1f m2 needed)" % (r["light_pct"], r["light_req"]))
            if not r["vent_ok"]:
                why.append("ventilation %.1f%% (min %.2f m2)" % (r["vent_pct"], r["vent_req"]))
            h.append("<p>&#10007; <b>%s</b> (%s): %s</p>" % (r["room"], r["floor"], "; ".join(why)))
        over = [r for r in need if not r["glaze_ok"]]
        if over:
            h.append("<p style='color:%s'>Glazing over the limit: %s</p>" % (bad, ", ".join(r["room"] for r in over)))
        nores = [r["name"] for r in m["rooms"] if not r["tags"]]
        if nores:
            h.append("<p style='color:#b7791f'>No window or door linked: %s</p>" % ", ".join(nores[:12]))
        h.append("<h3>Energy (SANS 10400-XA) windows</h3>")
        xr = getattr(w, "xa_fen_results", []) or []
        if not xr:
            h.append("<p>Nothing to check yet.</p>")
        for f in xr:
            good = f["within"]
            h.append("<p style='color:%s'>%s %s: glazing %.1f%% of floor (limit %g%%)%s</p>" % (
                ok if good else bad, "&#10003;" if good else "&#10007;", f["floor"], f["pct"], f["limit"], "" if good else " - calculation needed"))
        h.append("<p style='color:#888'>Windows use typical glazed and openable percentages until you set them per type. "
                 "Walls (cavity or solid) and the coverage are not read from Archicad yet.</p>")
        h.append("<p style='color:#888'>Updated in %.1f s.</p>" % secs)
        self.out.setText("".join(h))

    def save_log(self):
        import os
        path, _ = QFileDialog.getSaveFileName(self, "Save the log", os.path.join(os.path.expanduser("~"), "Desktop", "archicad_live_log.txt"), "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log))
