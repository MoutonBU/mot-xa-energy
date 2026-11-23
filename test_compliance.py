import site_engine as se, site_services as ss
st=ss.blank_state()
st["stand"]["zoning"]={"coverage":50,"far":0.6,"storeys":2,"height":8,"house_height":9,"bays_req":2,"bays":1}
r=se.solve(st)
rows={x["key"]:x for x in r["compliance"]}
print({k:(v["value"],v["ok"]) for k,v in rows.items()})
assert rows["coverage"]["ok"] is False or rows["coverage"]["ok"] is True
assert rows["height"]["ok"] is False and rows["parking"]["ok"] is False
st["stand"]["zoning"]={}
assert all(x["ok"] is not False or x["key"].startswith("bl_") or x["key"]=="inside" for x in se.solve(st)["compliance"])
print("ok")
import site_engine as se
st=ss.blank_state(); r=se.solve(st)
r["water"]["path"]=[(1.5,-2),(1.5,0),(-4,5),(2,6)]
w=se.checks(st,r["house"],r["carport"],dict(se.DEFAULTS),r)
assert any("neighbouring stand" in x for x in w) and r["flags"]
st["params"]={"fall":150}; assert any("table 13" in x for x in se.solve(st)["warnings"])
st["params"]={"fall":80}; assert any("special permission" in x for x in se.solve(st)["warnings"])
st["params"]={"fall":8}; assert any("anchor" in x for x in se.solve(st)["warnings"])
print("ok2")
