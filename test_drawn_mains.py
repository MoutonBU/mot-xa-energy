import math, site_engine as se, site_plans_data as pd
stand = [(0, 0), (14, 0), (14, 22), (0, 22)]
# snap: a click almost level snaps level; nearly 45 snaps to 45; free leaves it
p, lab, ang, ln = se.snap_dir(stand, (0, 0), (10, 0.8), "45")
assert abs(p[1]) < 1e-9 and lab.startswith("parallel"), (p, lab)
p, lab, ang, ln = se.snap_dir(stand, (0, 0), (6, 5), "45")
assert abs(p[0] - p[1]) < 1e-6 and lab.startswith("45"), (p, lab)
p, lab, *_ = se.snap_dir(stand, (0, 0), (6, 5), "par")
assert lab == "free" or abs(p[1]) < 1e-9 or abs(p[0]) < 1e-9
assert se.snap_dir(stand, (0, 0), (6, 5), "free")[0] == (6, 5)
# a skew stand: the snapped direction follows the stand's side
sk = [(0, 0), (14, 3), (12, 25), (-2, 22)]
base = math.atan2(3, 14)
p, lab, ang, ln = se.snap_dir(sk, (0, 0), (10, 2.1), "45")
assert abs(math.atan2(p[1], p[0]) - base) < 1e-6, p
# walls per edge
st = {"stand": {"corners": stand}}
k = se.edge_kinds(stand)
assert [se.wall_on(st, i, k[i]) for i in range(4)] == [False, True, True, True]
st["wall_edges"] = {"0": True, "2": False}
assert [se.wall_on(st, i, k[i]) for i in range(4)] == [True, True, False, True]
# water pair
x, side = pd.water_pair_x(14, 9.0, [-7, 21])
assert side == "right" and x == 13.9
x, side = pd.water_pair_x(14, 3.0, [-7])
assert side == "left" and x == 0.1
x, side = pd.water_pair_x(14, 3.0, [21])
assert side == "right"
print("ok")
# wall runs snap to the boundary and to corners
sn = se.snap_to_edge(stand, (5.0, 1.5))
assert sn[0] == 0 and abs(sn[1] - 5 / 14) < 1e-9 and sn[2] == (5.0, 0.0), sn
assert se.snap_to_edge(stand, (0.2, 0.3))[1] == 0.0
assert se.snap_to_edge(stand, (5.0, 1.5), edge=2, tol=99)[0] == 2
assert se.snap_to_edge(stand, (50, 50)) is None
print("ok runs")
