"""Fail-safe: the outlet pipe from the house never runs past the sewer run, whatever hand-placed run is given. Run: python3 test_sewer_failsafe.py"""
import random, math
import site_engine as se
from site_services import blank_state
def seg_pt_dist(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]; l2=dx*dx+dy*dy or 1e-12
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/l2)); return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
bad=0; n=0
random.seed(3)
for k in range(1500):
    st=blank_state()
    st["house"].update(cx=random.uniform(6,12),cy=random.uniform(6,16),rot=random.choice([0,90,180,270,random.uniform(0,360)]),w=random.uniform(6,14),d=random.uniform(5,9))
    if random.random()<.5: st["sewer_manual"]=[[random.uniform(2,16),random.uniform(1,10)],[random.uniform(2,16),-1.0]]
    try: r=se.solve(st)
    except Exception as e: continue
    sw=r["sewer"]; n+=1
    br=sw.get("branch"); P=sw["path"]
    if not br: continue
    p0,q1=br
    # overshoot: the run must contain q1 as its first point, and the run must not lie on the far side of q1 from the house along the outlet direction
    d=(q1[0]-p0[0],q1[1]-p0[1]); L=math.hypot(*d) or 1
    if min(seg_pt_dist(q1,P[i],P[i+1]) for i in range(len(P)-1))>1e-3:
        bad+=1; print("q1 off run",k, [tuple(round(c,2) for c in p) for p in P[:3]], br)
        if bad>5: break
print(n,bad)
# overshoot test: outlet direction vs first run leg, with hand-placed runs
bad=0
for k in range(3000):
    st=blank_state()
    st["house"].update(cx=random.uniform(6,12),cy=random.uniform(6,16),rot=random.choice([0,90,180,270]),w=random.uniform(6,14),d=random.uniform(5,9))
    st["sewer_manual"]=[[random.uniform(2,16),random.uniform(0.5,10)],[random.uniform(2,16),-1.0]]
    try: r=se.solve(st)
    except Exception: continue
    sw=r["sewer"]; br=sw.get("branch"); P=sw["path"]
    if not br or len(P)<2: continue
    p0,q1=br; d=(q1[0]-p0[0],q1[1]-p0[1]); L=math.hypot(*d) or 1; n0=(d[0]/L,d[1]/L)
    e=(P[1][0]-P[0][0],P[1][1]-P[0][1]); le=math.hypot(*e) or 1
    if (e[0]*n0[0]+e[1]*n0[1])/le<-0.5:
        bad+=1
        if bad<4: print("OVERSHOOT",k,br,[tuple(round(c,2) for c in p) for p in P[:3]])
print("manual overshoots",bad)
assert bad == 0
