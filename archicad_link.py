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
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QFileDialog)

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

    # ---- the whole model, in the shape the program's own tables use
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

    def _openings(self, etype):
        """[(guid, width_mm, height_mm)] for every window or door."""
        els = self.elements(etype)
        if not els:
            return []
        wh = [(None, None)] * len(els)
        if self.tapir_ok:
            try:
                det = self._details(els)
                wh = [(self._find_num(d, ("width", "openingWidth")), self._find_num(d, ("height", "openingHeight"))) for d in det]
            except Exception as e:
                self.log("   details failed: %s" % e)
        if any(w is None or h is None for w, h in wh):
            ids = self._prop_ids([("w", ["Opening_Width", "OpeningWidth", "_Width"]), ("h", ["Opening_Height", "OpeningHeight", "_Height"])])
            if "w" in ids and "h" in ids:
                for i in range(0, len(els), 500):
                    chunk = els[i:i + 500]
                    r = self.call("API.GetPropertyValuesOfElements", {"elements": chunk, "properties": [{"propertyId": ids["w"]}, {"propertyId": ids["h"]}]})
                    for j, row in enumerate(r.get("propertyValuesForElements", [])):
                        pv = [(p.get("propertyValue") or {}).get("value") for p in row.get("propertyValues", [])]
                        if len(pv) == 2 and wh[i + j][0] is None:
                            wh[i + j] = (pv[0], pv[1])
        out = []
        for e, (w, h) in zip(els, wh):
            g = (e.get("elementId") or {}).get("guid")
            if g and w and h:
                # Archicad reports lengths in metres
                out.append((g, int(round(float(w) * 1000)), int(round(float(h) * 1000))))
        return out

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

    def model(self):
        """Rooms, windows and doors of the open project, shaped like the program's IFC import:
        {'rooms': [{name, area, tags{tag: n}, floor, elev}], 'items': [{tag, width, height, kind, qty, glazed, openable}]}"""
        zones = self.elements("Zone")
        zr = self.zones()
        floors = {}
        if self.tapir_ok and zones:
            try:
                det = self._details(zones)
                st = self.stories()
                floors = {i: st.get(d.get("floorIndex"), "") for i, d in enumerate(det)}
            except Exception:
                pass
        items, tagof = {}, {}
        for etype, kind, pre in (("Window", "Window", "W"), ("Door", "Door", "D")):
            for g, w, h in self._openings(etype):
                tag = "%s%dx%d" % (pre, w, h)
                tagof[g] = tag
                it = items.setdefault(tag, {"tag": tag, "width": float(w), "height": float(h), "kind": kind, "qty": 0, "style": "Custom",
                                            "glazed": 85.0 if kind == "Window" else 0.0, "openable": 50.0 if kind == "Window" else 100.0,
                                            "flag": [], "note": "From Archicad: the size is read from the model. Glazed and openable % are typical values: set them for each type."})
                it["qty"] += 1
        rooms = []
        conns = {et: self._connected(zones, et) for et in ("Window", "Door")} if zones else {}
        for i, z in enumerate(zr):
            if not z["area"]:
                continue
            tags = {}
            for et in ("Window", "Door"):
                for g in conns.get(et, [set()] * len(zr))[i]:
                    if g in tagof:
                        tags[tagof[g]] = tags.get(tagof[g], 0) + 1
            rooms.append({"name": z["room"] or ("Zone " + (z["unit"] or str(i + 1))), "area": float(z["area"]), "tags": tags,
                          "floor": floors.get(i) or z["level"] or "Ground Floor", "elev": 0.0})
        return {"rooms": rooms, "items": list(items.values()), "n_zones": len(zones), "n_win": sum(1 for t in tagof.values() if t[0] == "W"),
                "n_door": sum(1 for t in tagof.values() if t[0] == "D")}

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

    def run(self):
        lg = []
        link = ACLink(lg.append)
        try:
            link.connect()
            link.check_tapir()
            m = link.model()
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
        self.out = QLabel("")
        self.out.setTextFormat(Qt.TextFormat.RichText)
        self.out.setWordWrap(True)
        self.out.setAlignment(Qt.AlignmentFlag.AlignTop)
        from PySide6.QtWidgets import QScrollArea
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.out)
        v.addWidget(sc, 1)
        sv = QPushButton("Save the log...")
        sv.clicked.connect(self.save_log)
        v.addWidget(sv)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.th = None

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
        self.th = _Fetch()
        self.th.done.connect(self._got)
        self.th.start()
        self._force = force

    def _got(self, r):
        self.busy = False
        self.log = (self.log + r.get("log", []))[-400:]
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
                         "" if m.get("tapir") else "   (Tapir not found: windows and doors cannot be tied to rooms)"))

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
        path, _ = QFileDialog.getSaveFileName(self, "Save the log", "archicad_live_log.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log))
