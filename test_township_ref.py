"""the built-in Blue Hills Ext 120 site plan data is sane, and a stand number brings up the stand with the house as drawn"""
import math
import site_township_ref as r


def test_data():
    S = r.TOWNSHIPS["Blue Hills Ext 120"]
    assert len(S) > 150
    houses = 0
    for no, d in S.items():
        assert 100 < d["area"] < 1100, (no, d["area"])
        assert len(d["poly"]) >= 3 and 0 <= d["street"] < len(d["poly"])
        h = d.get("house")
        if h and not h["rot"]:
            houses += 1
            assert 8 < h["w"] < 11 and 11 < h["d"] < 16, (no, h)
            assert h["cy"] - h["d"] / 2 >= 2.0, (no, h)
            c = d["carport"]
            assert abs(c["w"] - 5) < 0.2 and abs(c["d"] - 5) < 0.2 and c["cy"] - 2.5 < 1.5, (no, c)
    assert houses >= 30


if __name__ == "__main__":
    test_data()
    print("township reference ok")
