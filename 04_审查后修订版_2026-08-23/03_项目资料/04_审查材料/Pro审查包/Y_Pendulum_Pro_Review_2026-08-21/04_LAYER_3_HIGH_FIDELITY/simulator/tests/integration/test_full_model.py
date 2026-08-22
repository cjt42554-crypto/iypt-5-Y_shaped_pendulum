from __future__ import annotations
import copy
from pathlib import Path
import h5py
import numpy as np
from ypendulum.config import load_config
from ypendulum.io.hdf5 import read_h1_result, write_h1_result
from ypendulum.models.full_cable import FullCableModel
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium

def test_static_equilibrium_force_residual(config):
    model=FullCableModel(config); eq=solve_static_equilibrium(config,model)
    assert eq.converged and eq.force_residual_max<=1e-8 and np.all(np.isfinite(eq.positions))

def _run(config_dict,method):
    raw=copy.deepcopy(config_dict); raw['solver']['method']=method; cfg=load_config(raw); model=FullCableModel(cfg); eq=solve_static_equilibrium(cfg,model)
    return model,simulate_full(cfg,model=model,equilibrium=eq)

def test_newmark_matches_radau_on_smooth_case(config_dict):
    mr,r=_run(config_dict,'Radau'); mn,n=_run(config_dict,'Newmark'); assert mr.topology.node_labels==mn.topology.node_labels
    assert np.max(np.linalg.norm(n.positions[:,-1]-r.positions[:,-1],axis=1))<2e-7
    assert np.max(np.abs(n.energy['balance_residual']))<1e-5; assert n.diagnostics['solver_method']=='Newmark'

def test_hdf5_roundtrip_has_units(tmp_path:Path,config_dict):
    model,result=_run(config_dict,'Newmark'); target=tmp_path/'result.h5'; write_h1_result(target,result,model); data=read_h1_result(target); assert data['positions'].shape==result.positions.shape
    with h5py.File(target,'r') as h5:
        assert h5['/time'].attrs['unit']=='s'; assert h5['/cables/lower/elements/tension'].attrs['unit']=='N'; assert np.all(np.asarray(h5['/cables/lower/elements/tension'])>=0)

def test_model_rhs_jacobian_directional_consistency(config):
    model=FullCableModel(config); eq=solve_static_equilibrium(config,model); y=model.pack_state(eq.positions,eq.velocities); rng=np.random.default_rng(8); y=y+1e-7*rng.standard_normal(y.size); d=rng.standard_normal(y.size); d/=np.linalg.norm(d)
    J=model.jacobian(0.,y); J=J.toarray() if hasattr(J,'toarray') else np.asarray(J); eps=1e-7; fd=(model.rhs(0.,y+eps*d)-model.rhs(0.,y-eps*d))/(2*eps)
    assert np.linalg.norm(fd-J@d)/max(np.linalg.norm(fd),1e-12)<1e-5

def test_elastic_prestress_geometry_can_exist_without_natural_sphere_intersection(config_dict):
    raw=copy.deepcopy(config_dict); raw['supports']['A']['position']={'value':[-.1505,0,0],'unit':'m'}; raw['supports']['B']['position']={'value':[.1505,0,0],'unit':'m'}
    upper=raw['cables']['upper_A']; upper['rest_length']={'value':.15,'unit':'m'}; upper['diameter']={'value':.002,'unit':'m'}; upper['young_modulus']={'value':2e9,'unit':'Pa'}; raw['cables']['upper_B']={'inherit':'upper_A'}
    raw['cables']['lower']['diameter']={'value':.002,'unit':'m'}; raw['cables']['lower']['young_modulus']={'value':2e9,'unit':'Pa'}
    cfg=load_config(raw); model=FullCableModel(cfg); eq=solve_static_equilibrium(cfg,model); ev=model.evaluate(0.,model.topology.pack_free(eq.positions),model.topology.pack_free(eq.velocities))
    assert eq.force_residual_max<1e-8 and np.all(ev.tension>0)
    assert np.linalg.norm(eq.positions[model.topology.support_nodes[1]]-eq.positions[model.topology.support_nodes[0]])>.30


def test_every_hdf5_dataset_has_unit_and_description(tmp_path: Path, config_dict) -> None:
    model, result = _run(config_dict, "Newmark")
    target = tmp_path / "result_contract.h5"
    write_h1_result(target, result, model)
    missing: list[str] = []
    with h5py.File(target, "r") as h5:
        def visitor(name, obj):
            if isinstance(obj, h5py.Dataset):
                if "unit" not in obj.attrs or "description" not in obj.attrs:
                    missing.append(name)
        h5.visititems(visitor)
    assert missing == []


def test_prescribed_support_inertia_and_work_close_energy_ledger(config_dict) -> None:
    """Consistent moving-boundary inertia and support reaction work must agree."""

    raw = copy.deepcopy(config_dict)
    for name, x in (("A", -0.15), ("B", 0.15)):
        raw["supports"][name] = {
            "type": "prescribed",
            "position": {"value": [x, 0.0, 0.0], "unit": "m"},
            "motion": {
                "model": "sinusoidal",
                "amplitude": {"value": [0.0, 0.0, 0.0002], "unit": "m"},
                "frequency": {"value": 4.0, "unit": "Hz"},
                "phase": {"value": 0.0, "unit": "rad"},
            },
        }
    raw["initial_condition"]["type"] = "static_equilibrium"
    raw["solver"]["t_end"] = {"value": 0.03, "unit": "s"}
    raw["solver"]["output_dt"] = {"value": 0.00025, "unit": "s"}
    raw["solver"]["max_step"] = {"value": 0.0001, "unit": "s"}

    cfg = load_config(raw)
    model = FullCableModel(cfg)
    equilibrium = solve_static_equilibrium(cfg, model)
    result = simulate_full(cfg, model=model, equilibrium=equilibrium)
    assert abs(float(result.energy["support_work"][-1])) > 1e-6
    assert np.max(np.abs(result.energy["balance_residual"])) < 2e-7
    mechanical_change = float(result.energy["mechanical"][-1] - result.energy["mechanical"][0])
    support_work = float(result.energy["support_work"][-1])
    assert abs(mechanical_change - support_work) < 2e-7


def test_reduced_release_velocity_is_taut_compatible_and_preserves_bob_velocity(config_dict) -> None:
    """Nonzero angular release must not inject an arbitrary axial velocity pulse."""

    from ypendulum.elements import evaluate_cable_elements
    from ypendulum.geometry import reduced_geometry_from_loaded_state, torus_velocity
    from ypendulum.solvers.static import build_initial_state

    raw = copy.deepcopy(config_dict)
    raw["initial_condition"]["phi"] = {"value": 3.0, "unit": "degree"}
    raw["initial_condition"]["theta"] = {"value": 2.0, "unit": "degree"}
    raw["initial_condition"]["phi_dot"] = {"value": 0.18, "unit": "rad/s"}
    raw["initial_condition"]["theta_dot"] = {"value": -0.11, "unit": "rad/s"}
    cfg = load_config(raw)
    model = FullCableModel(cfg)
    base = solve_static_equilibrium(cfg, model)
    geom = reduced_geometry_from_loaded_state(
        base.positions[model.topology.support_nodes[0]],
        base.positions[model.topology.support_nodes[1]],
        base.positions[model.topology.junction_node],
        model.gravity,
    )
    loaded_lower = float(
        np.linalg.norm(
            base.positions[model.topology.bob_node]
            - base.positions[model.topology.junction_node]
        )
    )
    _jv, target_bob_velocity = torus_velocity(
        geom,
        loaded_lower,
        np.deg2rad(3.0),
        np.deg2rad(2.0),
        0.18,
        -0.11,
    )
    state, _t0, conditioned = build_initial_state(cfg, model, equilibrium=base)
    assert conditioned is not None
    q_free, v_free = model.split_state(state)
    positions, velocities, _ = model.topology.expand_free(0.0, q_free, v_free)
    response = evaluate_cable_elements(
        positions,
        velocities,
        model.topology.elements,
        length_guard=model.length_guard,
        material_overrides=model.material_overrides,
    )
    initially_taut = response.active & (response.tension > 0.0)
    assert np.max(np.abs(response.kinematics.delta_dot[initially_taut])) < 2e-10
    assert np.allclose(
        velocities[model.topology.bob_node], target_bob_velocity, atol=2e-11
    )
    projection = conditioned.metadata["initial_velocity_projection"]
    assert projection["applied"]
    assert projection["maximum_axial_rate_residual_m_s"] < 2e-10


def test_static_initialisation_follows_prescribed_support_velocity_without_axial_impulse(config_dict) -> None:
    from ypendulum.elements import evaluate_cable_elements
    from ypendulum.solvers.static import build_initial_state

    raw = copy.deepcopy(config_dict)
    for name, x in (("A", -0.15), ("B", 0.15)):
        raw["supports"][name] = {
            "type": "prescribed",
            "position": {"value": [x, 0.0, 0.0], "unit": "m"},
            "motion": {
                "model": "sinusoidal",
                "amplitude": {"value": [0.0002, 0.0, 0.0], "unit": "m"},
                "frequency": {"value": 2.0, "unit": "Hz"},
                "phase": {"value": 0.0, "unit": "rad"},
            },
        }
    raw["initial_condition"]["type"] = "static_equilibrium"
    cfg = load_config(raw)
    model = FullCableModel(cfg)
    base = solve_static_equilibrium(cfg, model)
    state, _t0, conditioned = build_initial_state(cfg, model, equilibrium=base)
    assert conditioned is not None
    q_free, v_free = model.split_state(state)
    positions, velocities, _ = model.topology.expand_free(0.0, q_free, v_free)
    response = evaluate_cable_elements(
        positions,
        velocities,
        model.topology.elements,
        length_guard=model.length_guard,
        material_overrides=model.material_overrides,
    )
    initially_taut = response.active & (response.tension > 0.0)
    assert np.max(np.abs(response.kinematics.delta_dot[initially_taut])) < 2e-10
