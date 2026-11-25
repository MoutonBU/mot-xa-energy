import mot_xa_energy as M
def test_none():
    assert M._ifc_wall_thickness(None) == 0.0
def test_name_regex():
    class T:  # stands in for an IFC type name read by the fallback
        Name = "Brick - Structural 110"
    import re
    x = re.search(r"(\d{2,3})\s*(?:mm)?\s*(?:brick|block|wall|$)", T.Name, re.I) or re.search(r"(\d{2,3})\s*$", T.Name)
    assert float(x.group(1)) == 110.0
if __name__ == "__main__":
    test_none(); test_name_regex(); print("ok")

def test_open_tag():
    for t, w in (("WD -09", "WD-09"), ("WD - 09", "WD-09"), ("WD-09", "WD-09"), ("W1", "W1"), ("TWD - 04", "TWD-04"), ("W 12", "W-12"), ("D3 A", "D3")):
        assert M._ifc_open_tag(t) == w, t
    assert M._ifc_open_tag("Window:Fixed", fallback="x") == "x"
    assert M._ifc_open_tag("", "WD - 02") == "WD-02"
test_open_tag(); print("ok2")
