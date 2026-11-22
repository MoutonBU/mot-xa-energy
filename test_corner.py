import site_township as tw
P=[(0,0),(14,0),(14,22),(0,22)]
roadlines={"road":[(-5,-3,20,-3),(15.5,-5,15.5,30)]}
e,k=tw.Township.street_edge(P,[],roadlines)
assert k and e==0,(e,k)           # 14 m frontage beats 22 m side
print(tw.Township.side_streets(P,e,roadlines))
assert tw.Township.side_streets(P,e,roadlines)==[1]
assert tw.Township.side_streets(P,0,{"road":[(-5,-3,20,-3)]})==[]
print("ok")
