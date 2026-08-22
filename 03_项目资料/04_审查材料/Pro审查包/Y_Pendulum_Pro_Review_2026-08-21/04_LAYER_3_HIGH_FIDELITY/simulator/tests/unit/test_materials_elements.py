import numpy as np
import pytest
from ypendulum.elements import CableElementBatch, assemble_element_forces, evaluate_cable_elements
from ypendulum.materials import TabulatedTensionMaterial, evaluate_kelvin_voigt

def batch(rest=1.0,ea=100.0,eta_a=0.0):
    return CableElementBatch(node_i=np.array([0]),node_j=np.array([1]),rest_length=np.array([rest]),ea=np.array([ea]),eta_a=np.array([eta_a]),area=np.array([1e-6]),density=np.array([1000.0]),diameter=np.array([.001]),drag_cd_normal=np.array([1.2]),cable_id=np.array([0]))

def test_unilateral_kelvin_voigt_never_compresses():
    r=evaluate_kelvin_voigt(np.array([-.1,.1,.1]),np.array([0.,0.,-100.]),np.ones(3),np.full(3,100.),np.full(3,1.))
    assert np.all(r.tension>=0); assert r.tension[0]==0; assert r.tension[1]==pytest.approx(10); assert r.tension[2]==0; assert np.all(r.dissipation_rate>=0)

def test_element_action_reaction_and_energy_gradient():
    p=np.array([[0.,0.,0.],[1.02,.1,-.03]]); v=np.zeros_like(p); e=batch(rest=1,ea=200)
    r=evaluate_cable_elements(p,v,e,length_guard=1e-12); assert np.allclose(assemble_element_forces(2,e,r).sum(0),0,atol=1e-14)
    d=np.array([.3,-.4,.2]); eps=1e-7; pp=p.copy(); pm=p.copy(); pp[1]+=eps*d; pm[1]-=eps*d
    ep=evaluate_cable_elements(pp,v,e,length_guard=1e-12).elastic_energy[0]; em=evaluate_cable_elements(pm,v,e,length_guard=1e-12).elastic_energy[0]
    assert (ep-em)/(2*eps)==pytest.approx(-np.dot(r.force_j[0],d),rel=2e-7)

def test_element_tangent_matches_directional_difference():
    rng=np.random.default_rng(4); p=np.array([[0.,0.,0.],[1.05,.2,.1]]); v=np.array([[.01,.02,-.01],[-.03,.01,.02]]); e=batch(rest=1,ea=300,eta_a=2)
    r=evaluate_cable_elements(p,v,e,length_guard=1e-12); d=rng.normal(size=3); eps=1e-7; p1=p.copy(); p0=p.copy(); p1[1]+=eps*d; p0[1]-=eps*d
    fd=(evaluate_cable_elements(p1,v,e,length_guard=1e-12).force_i[0]-evaluate_cable_elements(p0,v,e,length_guard=1e-12).force_i[0])/(2*eps)
    assert np.linalg.norm(fd-r.tangent_position[0]@d)/np.linalg.norm(fd)<2e-7

def test_tabulated_material_mesh_objectivity():
    m=TabulatedTensionMaterial(np.array([0.,.01,.02]),np.array([0.,10.,20.]),calibration_length=1.)
    w=m.evaluate(np.array([.01]),np.array([0.]),np.array([1.])); h=m.evaluate(np.array([.005,.005]),np.zeros(2),np.array([.5,.5]))
    assert h.tension[0]==pytest.approx(w.tension[0]); assert h.elastic_energy.sum()==pytest.approx(w.elastic_energy[0])


def test_tabulated_calibration_length_can_differ_from_installed_length(config_dict, tmp_path) -> None:
    import copy
    import pandas as pd

    from ypendulum.config import load_config
    from ypendulum.models.full_cable import FullCableModel

    table = tmp_path / "curve.csv"
    pd.DataFrame(
        {"extension": [0.0, 0.001, 0.002], "tension": [0.0, 2.0, 4.0]}
    ).to_csv(table, index=False)
    raw = copy.deepcopy(config_dict)
    raw["cables"]["lower"]["material_model"] = "tabulated_tension_extension"
    raw["cables"]["lower"]["table_file"] = str(table)
    raw["cables"]["lower"]["table_calibration_length"] = {
        "value": 0.5,
        "unit": "m",
        "source": "calibrated_independent",
    }
    cfg = load_config(raw)
    model = FullCableModel(cfg)
    material = model.material_overrides[2]
    assert material.calibration_length == pytest.approx(0.5)
