import math, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import site_engine as se
st = {"stand": {"corners": [(0, 0), (14, 0), (14, 22), (0, 22)]}, "main_line": [(-10, -4), (30, -4)], "sewer_join": 1}
path = [(3.0, 15.0), (3.0, -1.0)]      # (illustrative) run going to the main square
path = [(5.0, 10.0), (5.0, 6.0), (9.0, 6.0), (9.0, -4.0)]
out = se.join45(st, path)
last = (out[-1][0] - out[-2][0], out[-1][1] - out[-2][1])
ang = abs(math.degrees(math.atan2(last[1], last[0])) % 90)
assert out[-1] == (9.0, -4.0) and abs(ang - 45) < 1e-6, (out, ang)
st["sewer_join"] = 0
assert se.join45(st, path) == path
print("ok")
