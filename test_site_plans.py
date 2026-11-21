"""The finished plans as data and rules. Run: python3 test_site_plans.py"""
import site_engine as se
import site_plans_data as pd
from site_services import blank_state


def test_all():
    assert pd.house_type(10.0, 7.2) == "UR_115" and pd.house_type(7.2, 10.0) == "UR_115" and pd.house_type(14.8, 6.5) == "UR_100"
    assert pd.house_type(3, 3) is None
    assert len(pd.PLANS) == 9 and all(p["type"] in pd.HOUSE_TYPES for p in pd.PLANS)
    st = blank_state()
    st["house"].update(w=10.0, d=7.2, rot=90)
    st["stand"]["corners"] = [[0, 0], [13.5, 0], [13.5, 22], [0, 22]]
    out = se.suggest(st)
    st["house"].update(out["house"])
    st["carport"] = out["carport"]
    g = pd._gap_house_carport(st)
    assert g is None or g >= 0.95, g                              # the usual 1.0 m between carport and house when there is room
    r = se.solve(st)
    assert any("UR_115" in x for x in r["reference"]), r["reference"]
    # a stand with no room for 1.0 m still gets a placement
    st2 = blank_state()
    st2["stand"]["corners"] = [[0, 0], [11, 0], [11, 14], [0, 14]]
    st2["house"].update(w=10.0, d=7.2, rot=90)
    out2 = se.suggest(st2)
    assert out2["house"]


if __name__ == "__main__":
    test_all()
    print("finished plans data holds")
