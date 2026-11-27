"""SDP Creator: the numbers, the blocks, the saved state, the sheet."""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import sdp_creator as sc

# numbers
site = dict(sc.blank_site(), stand_area=10000.0, follow=False, max_cov=40, max_far=0.8, max_density=40, bays_per_unit=1.5, visitor_per=5)
blocks = [sc.blank_block("H%d" % i, "Phase 1" if i <= 2 else "Phase 2", units=4, foot=300, floor=700, bays=6) for i in range(1, 5)]
an = sc.analyse(site, blocks)
assert an["total"]["units"] == 16 and abs(an["cov"] - 12.0) < 1e-9 and abs(an["far"] - 0.28) < 1e-9
assert abs(an["density"] - 16.0) < 1e-9
assert an["bays_needed"] == 24 + 4 and an["total"]["bays"] == 24
assert [c[3] for c in an["checks"]] == [True, True, True, False] and not an["ok"]
assert set(an["phases"]) == {"Phase 1", "Phase 2"}
blocks[0]["cov"] = False
assert abs(sc.analyse(site, blocks)["cov"] - 9.0) < 1e-9
assert sc.block_names("H", 1, 3) == ["H1", "H2", "H3"]

# the page
class W:
    rd = {"project": "Test"}
    site_page = None
    area_page = None
pg = sc.SdpPage(W())
pg.set_state({"site": dict(site), "blocks": blocks})
assert len(pg.blocks()) == 4 and pg.blocks()[0]["cov"] is False and pg.site()["max_cov"] == 40
st = pg.state()
pg2 = sc.SdpPage(W())
pg2.load_state(st)
assert pg2.blocks() == pg.blocks() and pg2.site()["stand_area"] == 10000.0
pg.add_block()
assert len(pg.blocks()) == 5 and pg.blocks()[-1]["block"] == "H5"
d = sc._BlocksDialog(pg)
d.first.setValue(1); d.last.setValue(26); d.prefix.setText("H")
assert len(d.blocks()) == 26 and d.blocks()[25]["block"] == "H26"
pg.t.selectRow(0)
pg.remove_blocks()
assert len(pg.blocks()) == 4
assert pg.rt.rowCount() == 4 and pg.pt.rowCount() == 3
p = os.path.join(tempfile.mkdtemp(), "sdp.pdf")
pg.write_report(p)
assert os.path.getsize(p) > 2000
# light and dark look: the page grabs without error
pg.resize(1100, 700); pg.show(); pg.steps.go(1); pg.grab(); pg.steps.go(2); pg.grab()
print("ok sdp")
