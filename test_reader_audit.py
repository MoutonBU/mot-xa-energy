import os, glob, json
import materials as m
D = "/mnt/user-data/attachments/3e984422-d403-5b77-8b1a-953c242365ed"
fs = glob.glob(D + "/*Stand_2066*.ifc")
if fs:
    q = m.read_ifc_quantities(fs[0])
    json.dumps({"audit": q["audit"], "unread": q["unread"], "failed": q["failed"]})
    a = {r[0].split(":")[0]: r for r in q["audit"]}
    assert a["Windows"][1] == a["Windows"][2] == 8
    assert a["Doors and gates"][1] == a["Doors and gates"][2]
    assert any("2D line only" in k for k in q["failed"])          # drawing lines are named, not silently dropped
    assert any(u[0].startswith("COULD NOT READ") for u in q["unread"])
print("ok")
