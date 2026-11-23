import numpy as np, rd_engine as E
# horizon: a wall of 40 deg to the south hides the winter sun, and the south window gets less beam
w={"DNI":np.full(8760,500.0),"DHI":np.full(8760,100.0),"GHI":np.full(8760,400.0),"T":np.full(8760,20.0)}
alt=np.radians(np.full(8760,30.0)); saz=np.radians(np.full(8760,0.0))   # sun in the north, 30 deg up
hz=[0.0]*36; hz[0]=40.0
m=E.horizon_mask((alt,saz),hz); assert m is not None and not m.any()
hz[0]=20.0; assert E.horizon_mask((alt,saz),hz).all()
t0,b0,_=E.plane_irradiance(w,(alt,saz),90,0)
t1,b1,_=E.plane_irradiance(w,(alt,saz),90,0,E.horizon_mask((alt,saz),[0.0]*35+[0.0]) )
t2,b2,_=E.plane_irradiance(w,(alt,saz),90,0,np.zeros(8760,bool))
assert b2.sum()==0 and b1.sum()==b0.sum() and t2.sum()<t0.sum()
print("ok engine")
# site side
from PySide6.QtWidgets import QApplication
import site_services as ss
app=QApplication.instance() or QApplication([])
class W:
    got=None
    def receive_site_link(self,l): W.got=l; return "ok"
pg=ss.SiteServicesPage(W())
pg.st["neighbours"]=[{"no":"2","c":[-8,10],"poly":[[-15,0],[-1.5,0],[-1.5,22],[-15,22]]}]
pg.st["sheet"]["north"]=0.0
pg.solve_now(False)
h=pg.site_horizon(3.5)
b=pg.paper_bearing((1,0)); v=pg.bearing_vec(b); assert abs(v[0]*0+v[1]*0)>=0
vec=pg.bearing_vec(pg.paper_bearing((1,0))); assert vec[0]>0 and abs(vec[1])<1e-6,vec
# the neighbour is on the -x side of the stand: the shade is on the bearing that points to -x
bx=pg.paper_bearing((-1,0)); k=round(bx/10)%36
assert h[k]>0 and h[(k+18)%36]==0,(bx,h)
l=pg.energy_link(); assert len(l["horizon"])==36 and l["stand_area"]>0
pg.send_to_energy.__func__  # exists
print("ok site", round(bx), h[k])
hz=E.block_horizon(180,5,7.5,10)
assert hz[18]>0 and hz[0]==0 and abs(hz[18]-round(__import__("math").degrees(__import__("math").atan2(6.0,5)),1))<0.2
assert hz[17]>0 and hz[19]>0 and hz[12]==0
print("ok block")
pg.shade_cb.setChecked(True)
o=pg.sheet_opts(); assert o["shade"] and all(len(w[0])==4 for w in o["shade"])
from PySide6.QtGui import QImage, QPainter
img=QImage(900,700,QImage.Format_RGB32); p_=QPainter(img)
import site_sheet as sx
sh=sx.Sheet(20.0,(9,10),(900,700),"left",0.0); sx._draw(p_,sh,pg.st,pg.res,o,7); p_.end()
img.save("/tmp/claude-0/-home-claude/3e984422-d403-5b77-8b1a-953c242365ed/scratchpad/shade.png"); print("ok shade")
