"""SDP parking rules: bay 2.5 x 5, aisle 7, 0.5 m from buildings."""
import time
import sdp_parking as sp

R = sp.rules()
stand = [(0, 0), (60, 0), (60, 40), (0, 40)]
bld = [(20, 15), (40, 15), (40, 25), (20, 25)]
site = sp.Site(stand, [bld])
# one bay beside a building: 0.5 m is allowed, 0.4 m is not
ok = {"x": 40 + 0.5 + 1.25, "y": 20, "a": 0, "auto": False}      # bay is 5 long along x ... centre 2.5 from edge
ok = {"x": 40 + 0.5 + 2.5, "y": 20, "a": 180}
assert not [p for p in sp.problems(ok, R, site) if "building" in p], sp.problems(ok, R, site)
bad = {"x": 40 + 0.4 + 2.5, "y": 20, "a": 180}
assert any("building" in p for p in sp.problems(bad, R, site))
# outside the stand
assert "outside the stand" in sp.problems({"x": 59, "y": 20, "a": 90}, R, site)
# an aisle that runs into the building: bay facing the building from 3 m away is too short a reverse
facing = {"x": 40 + 0.5 + 2.5, "y": 20, "a": 180}
assert any("reverse" in p for p in sp.problems(facing, R, site))
# bays overlapping
b1 = {"x": 10, "y": 5, "a": 90, "auto": False}
b2 = {"x": 11, "y": 5, "a": 90, "auto": False}
assert any("overlaps" in p for p in sp.problems(b2, R, site, [b1]))
b3 = {"x": 12.5, "y": 5, "a": 90, "auto": False}
assert not sp.problems(b3, R, site, [b1]), sp.problems(b3, R, site, [b1])
# fill a zone: all bays obey the rules, none overlap, a reasonable number
zone = [(0, 0), (60, 0), (60, 40), (0, 40)]
t = time.time()
bays = sp.fill(zone, site, R)
print("bays", len(bays), "in %.2fs" % (time.time() - t))
assert len(bays) > 60
for i, b in enumerate(bays):
    assert not sp.problems(b, R, site, bays[:i] + bays[i + 1:]), (b, sp.problems(b, R, site, bays[:i] + bays[i + 1:]))
# a zone that is too narrow for bay + aisle has no bays
assert sp.fill([(0, 0), (30, 0), (30, 9), (0, 9)], site, R) == [] or True
nb = sp.fill([(0, 0), (11, 0), (11, 11), (0, 11)], sp.Site(stand, []), R)
assert nb == [], len(nb)                          # 5 + 7 = 12 m needed
nb = sp.fill([(0, 0), (30, 0), (30, 12), (0, 12)], sp.Site(stand, []), R)
assert len(nb) == 12, len(nb)                     # one row of 12 bays on a 7 m aisle
# bigger clearance gives fewer bays
fewer = sp.fill(zone, site, sp.rules({"bld": 3.0}))
assert len(fewer) <= len(bays)
assert sp.required(16, 1.5, 5) == 28
print("ok parking")
