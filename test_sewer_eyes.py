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
    # 1. the rodding eye at the wall end of the outlet pipe (Min IL 450); the outlet butts flush on the run, which carries on re_ext past the joint and ends in a rodding eye;
    #    an inspection eye at the joint
    assert nodes[0]["kind"] == "RE" and nodes[0]["label"].startswith("RE Min IL 450")
    assert any(n["kind"] == "RE" and n is not nodes[0] and n["chainage"] < 0.02 for n in nodes), "the rodding eye at the end of the run"
    assert any(n["kind"] == "IE" and abs(n["chainage"] - tail) < 0.02 for n in nodes), "the inspection eye at the joint"
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
    # 4. eyes cannot be left out: a "deleted" eye is still there
    k = [n for n in nodes if n["kind"] == "IE"][0]["key"]
    st["eyes"] = {"del": [k], "pos": {}}
    assert len([n for n in nodes_for(st)["nodes"] if n["kind"] in ("IE", "RE")]) == len([n for n in nodes if n["kind"] in ("IE", "RE")])


def test_every_eye_in():
    """fail-safe: over many houses, turns, runs and outlets every joint, bend, end and wall has its eye"""
    import random
    random.seed(7)
    bad = 0
    for i in range(300):
        st = blank_state()
        st["house"].update(cx=random.uniform(6, 12), cy=random.uniform(8, 16), rot=random.choice([0, 90, 180, 270, random.uniform(0, 360)]))
        if random.random() < 0.6:
            st["sewer_ports"] = [{"edge": random.randrange(4), "t": random.uniform(0.1, 0.9)} for _ in range(random.randrange(1, 4))]
        sw = nodes_for(st)
        nodes = sw["nodes"]

        def has(kind, pt):
            return any(n["kind"] == kind and math.hypot(n["pt"][0] - pt[0], n["pt"][1] - pt[1]) < 0.07 for n in nodes)
        path = sw["path"]
        need = [("RE", path[0])]
        for a_, b_ in sw["stubs"]:
            need += [("IE", a_), ("RE", b_)]
        if sw["branch"]:
            need += [("IE", sw["branch"][1]), ("RE", sw["branch"][0])]
        for ex in sw["extra"]:
            need += [("IE", ex["path"][0]), ("RE", ex["path"][-1])]
        for kind, pt in need:
            if not has(kind, pt):
                bad += 1
    assert bad == 0, bad


if __name__ == "__main__":
    test_rules()
    test_every_eye_in()
    print("sewer eye rules hold")
