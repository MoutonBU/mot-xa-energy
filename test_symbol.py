import site_township as T
lines = {"elec": [(0,0,2,0),(2,0,1,1.7),(1,1.7,0,0),(5,5,40,5)], "water": [], "sewer": []}
l, t = T.Township.strip_symbols(lines)
assert len(t) == 1 and t[0][0] == "elec" and len(l["elec"]) == 1 and l["elec"][0][2] == 40, (t, l)
print("ok")
