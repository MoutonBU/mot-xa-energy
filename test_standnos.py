import site_sheet as ss
cp=[(0,0),(40,0),(40,30),(0,30)]
st={"neighbours":[{"no":"1","c":[5,5]}],"far_stands":[
 {"no":"2","c":[20,10],"poly":[]},
 {"no":"3","c":[60,10],"poly":[(55,5),(65,5),(65,15),(55,15)]},
 {"no":"4","c":[44,10],"poly":[(38,5),(50,5),(50,15),(38,15)]}]}
n=[x["no"] for x in ss._numbered_stands(st,cp)]
assert n==["1","2","4"],n
q=ss._into_poly((44,10),cp,1.4); assert ss._in_poly(q,cp) and q[0]<=38.7,q
assert ss._into_poly((20,10),cp)==(20,10)
print("ok")
o={"cutpoly":[(0,0),(40,10),(35,40),(-5,30)]}
x,y=ss._fit_x((-30,20),o,left=9.0)
assert ss._in_poly((x-9,y),o["cutpoly"]) and ss._in_poly((x,y),o["cutpoly"]),(x,y)
assert ss._fit_x((10,20),o,left=2)==(10,20)
print("ok fit")
