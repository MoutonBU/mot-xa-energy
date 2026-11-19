"""Archicad link (VIP, experimental).

Talks to a running Archicad through its JSON command interface on this computer (the same one the official Python
package uses; no extra package needed). Tapir, the free community add-on, is used when it is installed, for the
things the official commands do not give (which storey an element is on, polygon outlines).
Everything here is read only: nothing is written back to Archicad."""
import json
import math
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QFileDialog)

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
        try:
            r = self.call("API.IsAddOnCommandAvailable", {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": "GetStories"}})
            self.tapir_ok = bool(r.get("isAvailable"))
        except Exception:
            self.tapir_ok = False
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
        self.setWindowTitle("Archicad link (VIP, experimental)")
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
