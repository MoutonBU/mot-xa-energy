import os, tempfile, json
import detail_generator as g

def main():
    spec, probs = g.clean_spec(g.SAMPLE_SPEC)
    assert not probs and len(spec["shapes"]) == 8
    d = tempfile.mkdtemp()
    dxf, png = os.path.join(d, "a.dxf"), os.path.join(d, "a.png")
    n = g.make_detail(spec, dxf, png)
    assert n == 5, n
    assert os.path.getsize(dxf) > 5000 and os.path.getsize(png) > 1000
    import ezdxf
    doc = ezdxf.readfile(dxf)
    lay = {e.dxf.layer for e in doc.modelspace()}
    assert "MOT_NOTES" in lay and "MOT_BRICKWORK" in lay, lay
    # parse + clean of messy replies
    raw = "Here you go:\n```json\n" + json.dumps({"shapes": [
        {"material": "Brick", "pts": [[0, 0], [110, 0], [110, 500], [0, 500], [0, 0]]},
        {"material": "weird", "pts": [[0, 0], [1, 1]]},
        {"material": "concrete", "pts": [[0, 0], [1e9, 0], [0, 5]]},
        {"material": "concrete", "pts": [[0, 0], [10, 0], [20, 0]]}],
        "notes": {"brick": "110 mm brick", "nonsense": "x"}}) + "\n```"
    s2, p2 = g.clean_spec(g.parse_reply(raw))
    assert len(s2["shapes"]) == 1 and len(p2) == 3 and list(s2["notes"]) == ["brick"], (s2, p2)
    for bad in ("no json here", "{broken"):
        try:
            g.parse_reply(bad); assert False
        except g.GenError:
            pass
    try:
        g.clean_spec({"shapes": []}); assert False
    except g.GenError:
        pass
    sp3, _p = g.clean_spec(g.SAMPLE_SPEC)
    specs = g.geometry_for_notes(sp3, os.path.join(d, "g.dxf"))
    assert len(specs) == 5 and all(v["note"] and "x" in v for v in specs.values())
    import ezdxf
    gd = ezdxf.readfile(os.path.join(d, "g.dxf"))
    assert all(gd.entitydb.get(h) is not None and gd.entitydb.get(h).dxftype() == "HATCH" for h in specs)
    assert g.parse_reply({"shapes": []}) == {"shapes": []}          # a tool reply is already an object
    import io, json as _j, urllib.request as ur
    calls = []
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def fake(req, timeout=0):
        calls.append(1)
        body = _j.loads(req.data.decode())
        assert body["tool_choice"]["type"] == "auto" and body["tools"][0]["name"] == "draw_detail"
        return R(_j.dumps({"content": [{"type": "tool_use", "input": g.SAMPLE_SPEC}]}).encode())
    old = ur.urlopen; ur.urlopen = fake
    try:
        sp2, pr = g.generate("wall", "k", "m")
    finally:
        ur.urlopen = old
    assert len(sp2["shapes"]) == 8 and calls
    # the designer's own details: saved, found again by their words, and shown to Claude as examples of the style
    lp = os.path.join(d, "lib.json")
    g.save_detail("Loffelstein retaining wall 1 m high on a strip footing", dict(g.SAMPLE_SPEC, title="Loffelstein wall"), lp)
    g.save_detail("cavity wall on strip footing", dict(g.SAMPLE_SPEC, title="Cavity wall"), lp)
    g.save_detail("cavity wall on strip footing, new version", dict(g.SAMPLE_SPEC, title="Cavity wall"), lp)       # the same title replaces
    lib = g.load_library(lp)
    assert [x["title"] for x in lib] == ["Loffelstein wall", "Cavity wall"] and "new version" in lib[1]["request"]
    assert g.pick_examples("a Loffelstein retaining wall detail", lib, 1)[0]["title"] == "Loffelstein wall"
    seen = []
    def fake2(req, timeout=0):
        seen.append(_j.loads(req.data.decode())["system"])
        return R(_j.dumps({"content": [{"type": "tool_use", "input": g.SAMPLE_SPEC}]}).encode())
    ur.urlopen = fake2
    try:
        g.generate("Loffelstein retaining wall", "k", "m", library=lib)
        g.generate("something else", "k", "m", library=[])
    finally:
        ur.urlopen = old
    assert "SAVED DETAILS" in seen[0] and "Loffelstein wall" in seen[0] and "SAVED DETAILS" not in seen[1]
    g.delete_detail("Loffelstein wall", lp)
    assert [x["title"] for x in g.load_library(lp)] == ["Cavity wall"]
    assert g.load_library(os.path.join(d, "none.json")) == []
    print("generator ok")

if __name__ == "__main__":
    main()
