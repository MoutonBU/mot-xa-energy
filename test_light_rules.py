"""SANS 10400-O:2011 Ed 3, 4.2.1.1.3: the 0,2 m2 minimum belongs to the 10 % route only; the 5 % (category 1) route has none."""
import mot_xa_energy as M

room = M.Room("Bedroom", 3.0, "")
r10 = M.check_room(room, {}, 10.0)
r5 = M.check_room(room, {}, 5.0)
assert abs(r10["light_req"] - 0.3) < 1e-9, r10["light_req"]      # 10 % of 3 m2 = 0,3 (above the 0,2 floor)
assert abs(r5["light_req"] - 0.15) < 1e-9, r5["light_req"]       # 5 % route: no 0,2 floor
small = M.check_room(M.Room("Bedroom", 1.5, ""), {}, 10.0)
assert abs(small["light_req"] - 0.2) < 1e-9, small["light_req"]  # 10 % of 1,5 = 0,15 -> floor of 0,2 applies
print("ok")
