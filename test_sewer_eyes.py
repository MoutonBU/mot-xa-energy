"""The sewer eye rules as Mouton wants them (checked against his plans). Run: python3 test_sewer_eyes.py"""
import math

import site_engine as se
from site_services import blank_state


def nodes_for(state):
    r = se.solve(state)
    return r["sewer"]


def test_rules():
    st = blank_state()
    st["house"].update(cx=9.0, cy=12.0)
    sw = nodes_for(st)
    path, nodes = sw["path"], sw["nodes"]
    tail = se.DEFAULTS["re_ext"]
    # 1. the rodding eye at the wall end of the outlet pipe (Min IL 450); the outlet pipe butts flush on the run: an inspection eye at the joint, no tail past it, no rodding eye there
    assert nodes[0]["kind"] == "RE" and nodes[0]["label"].startswith("RE Min IL 450")
    assert nodes[1]["kind"] == "IE" and nodes[1]["chainage"] < 0.02
    assert not any(n["kind"] == "RE" and n is not nodes[0] and n["chainage"] < 0.02 for n in nodes)
    # 2. at every corner: an inspection eye on the corner and a rodding eye re_ext away on a stub, along the leg that runs on to the main, backwards
    assert sw["stubs"], "a corner needs its stub"
    for a, b in sw["stubs"]:
        assert abs(math.hypot(b[0] - a[0], b[1] - a[1]) - tail) < 0.01
        assert any(n["kind"] == "IE" and math.hypot(n["pt"][0] - a[0], n["pt"][1] - a[1]) < 0.05 for n in nodes)
        assert any(n["kind"] == "RE" and math.hypot(n["pt"][0] - b[0], n["pt"][1] - b[1]) < 0.05 for n in nodes)
    # 3. where the run crosses the stand boundary: the rodding eye comes first, just inside, then an inspection eye against the stand
    cut = [n for n in nodes if n["kind"] == "IE" and abs(n["pt"][1]) < 0.1]
    assert cut, "an inspection eye on the boundary"
    assert any(n["kind"] == "RE" and 0.2 < n["pt"][1] < 0.5 for n in nodes)
    # 4. eyes can be moved and deleted, and every eye has a key
    k = [n for n in nodes if n["kind"] == "IE"][0]["key"]
    st["eyes"] = {"del": [k], "pos": {}}
    assert all(n.get("key") != k for n in nodes_for(st)["nodes"])

if __name__ == "__main__":
    test_rules()
    print("sewer eye rules hold")
