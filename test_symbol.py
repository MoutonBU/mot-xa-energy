import site_township as T
lines = {"elec": [(0,0,2,0),(2,0,1,1.7),(1,1.7,0,0),(5,5,40,5)], "water": [], "sewer": []}
l, t = T.Township.strip_symbols(lines)
assert len(t) == 1 and t[0][0] == "elec" and len(l["elec"]) == 1 and l["elec"][0][2] == 40, (t, l)
print("ok")
# a symbol on the side of the stand is found too
T = T.Township()
T.k = 1.0; T.marks = []; T.texts = [("E3.1", 12, 20, "x")]; T.layers = {}
T.cat_of = lambda l: "elec"
P = [(0, 0), (14, 0), (14, 22), (0, 22)]
tri = [("elec", [(14, 20), (16, 19), (16, 21)])]          # tip on the right-hand side boundary
c = T.connections(P, 0, reach=14.0, tris=tri)
assert c["elec"]["pt"] == (14, 20) and c["elec"]["label"] == "E3.1", c
print("ok side")
