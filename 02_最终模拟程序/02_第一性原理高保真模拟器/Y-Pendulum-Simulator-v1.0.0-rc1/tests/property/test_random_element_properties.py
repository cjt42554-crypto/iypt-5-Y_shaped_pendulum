import numpy as np
from ypendulum.elements import CableElementBatch,evaluate_cable_elements

def test_random_tension_only_action_reaction_properties():
    rng=np.random.default_rng(20260818)
    for _ in range(100):
        rest=rng.uniform(.1,2.); d=rng.normal(size=3); d/=np.linalg.norm(d); current=rest+rng.uniform(-.05*rest,.1*rest); x=np.array([[0.,0.,0.],d*current]); v=rng.normal(scale=.1,size=(2,3))
        e=CableElementBatch(node_i=np.array([0]),node_j=np.array([1]),rest_length=np.array([rest]),ea=np.array([rng.uniform(10,1000)]),eta_a=np.array([rng.uniform(0,10)]),area=np.array([1e-6]),density=np.array([1000.]),diameter=np.array([.001]),drag_cd_normal=np.array([1.2]),cable_id=np.array([0]))
        r=evaluate_cable_elements(x,v,e,length_guard=1e-14); assert r.tension[0]>=0; assert np.allclose(r.force_i[0]+r.force_j[0],0); assert r.dissipation_rate[0]>=0
