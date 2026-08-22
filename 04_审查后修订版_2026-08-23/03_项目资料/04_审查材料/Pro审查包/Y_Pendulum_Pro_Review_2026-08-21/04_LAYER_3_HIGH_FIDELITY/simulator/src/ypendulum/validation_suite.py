"""Executable analytic and semi-analytic validation suite V-001 ... V-013."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Any

import numpy as np
from scipy import sparse
from scipy.integrate import solve_ivp
from scipy.linalg import eigh
from scipy.optimize import brentq, minimize
from scipy.special import ellipk

from ypendulum.config import load_config
from ypendulum.elements import (
    CableElementBatch,
    assemble_element_forces,
    assemble_element_tangent,
    assemble_mass_matrix,
    evaluate_cable_elements,
)
from ypendulum.geometry import reduced_geometry_from_loaded_state
from ypendulum.io import write_json
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.torus import TorusParameters, torus_rhs
from ypendulum.observers import PinholeCamera, sample_with_exposure
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium


@dataclass
class ValidationCase:
    case: str
    passed: bool
    metric: float
    threshold: float
    description: str
    details: dict[str, Any]


def _batch(
    node_i, node_j, rest, ea, density, area=1e-6, eta_a=0.0, cable_id=0
) -> CableElementBatch:
    n = len(np.atleast_1d(node_i))
    return CableElementBatch(
        node_i=np.asarray(node_i, dtype=np.int64),
        node_j=np.asarray(node_j, dtype=np.int64),
        rest_length=np.broadcast_to(np.asarray(rest, dtype=float), (n,)).copy(),
        ea=np.broadcast_to(np.asarray(ea, dtype=float), (n,)).copy(),
        eta_a=np.broadcast_to(np.asarray(eta_a, dtype=float), (n,)).copy(),
        area=np.broadcast_to(np.asarray(area, dtype=float), (n,)).copy(),
        density=np.broadcast_to(np.asarray(density, dtype=float), (n,)).copy(),
        diameter=np.full(n, 2.0 * math.sqrt(area / math.pi)),
        drag_cd_normal=np.full(n, 1.2),
        cable_id=np.full(n, cable_id, dtype=np.int64),
    )


def _base_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run": {
            "name": "validation",
            "mode": "full",
            "seed": 20260818,
            "output_directory": "/tmp/ypendulum_validation",
            "claim_level": "VERIFIED",
        },
        "environment": {
            "gravity": {"value": [0, 0, -9.80665], "unit": "m/s^2"},
            "air_density": {"value": 1.2, "unit": "kg/m^3"},
            "air_velocity": {"value": [0, 0, 0], "unit": "m/s"},
        },
        "supports": {
            "A": {"type": "fixed", "position": {"value": [-0.15, 0, 0], "unit": "m"}},
            "B": {"type": "fixed", "position": {"value": [0.15, 0, 0], "unit": "m"}},
        },
        "junction": {"mass": {"value": 1e-5, "unit": "kg"}},
        "bob": {
            "mass": {"value": 0.2, "unit": "kg"},
            "radius": {"value": 0.01, "unit": "m"},
            "drag": {"enabled": False},
            "buoyancy": False,
        },
        "cables": {
            "upper_A": {
                "rest_length": {"value": 0.403887, "unit": "m"},
                "diameter": {"value": 0.0005, "unit": "m"},
                "density": {"value": 1.0, "unit": "kg/m^3"},
                "young_modulus": {"value": 2e9, "unit": "Pa"},
                "axial_viscosity": {"value": 0.0, "unit": "Pa*s"},
                "elements": 2,
            },
            "upper_B": {"inherit": "upper_A"},
            "lower": {
                "rest_length": {"value": 0.3, "unit": "m"},
                "diameter": {"value": 0.0005, "unit": "m"},
                "density": {"value": 1.0, "unit": "kg/m^3"},
                "young_modulus": {"value": 2e9, "unit": "Pa"},
                "axial_viscosity": {"value": 0.0, "unit": "Pa*s"},
                "elements": 3,
            },
        },
        "initial_condition": {
            "type": "reduced_angles_release",
            "phi": {"value": 2.0, "unit": "degree"},
            "theta": {"value": 1.0, "unit": "degree"},
        },
        "solver": {
            "profile": "quick",
            "t_end": {"value": 0.08, "unit": "s"},
            "output_dt": {"value": 0.002, "unit": "s"},
            "mass_matrix": "lumped",
            "method": "Radau",
            "analytic_jacobian": True,
            "allow_subminimum_mesh": True,
            "static": {
                "force_tolerance": {"value": 1e-8, "unit": "N"},
                "max_iterations": 100,
                "continuation_steps": 5,
            },
        },
        "analysis": {"target_ratio": [3, 2]},
        "observer": {"type": "orthographic_xy"},
    }


def _linearised_matrices(model: FullCableModel, positions: np.ndarray):
    qf = model.topology.pack_free(positions)
    ev = model.evaluate(0.0, qf, np.zeros_like(qf), compute_tangent=True, include_aero=False)
    assert ev.tangent_position is not None
    fd = model.topology.free_dofs
    stiffness = -ev.tangent_position[fd][:, fd].toarray()
    mass = model.mass_ff.toarray()
    stiffness = 0.5 * (stiffness + stiffness.T)
    mass = 0.5 * (mass + mass.T)
    return stiffness, mass


def v001() -> ValidationCase:
    rest, ea, force = 0.8, 1200.0, 3.0
    delta = force * rest / ea
    x = np.array([[0.0, 0, 0], [rest + delta, 0, 0]])
    response = evaluate_cable_elements(x, np.zeros_like(x), _batch([0], [1], rest, ea, 1.0), length_guard=1e-12)
    metric = abs(response.tension[0] - force) / force
    return ValidationCase("V-001", metric < 1e-8, metric, 1e-8, "Single-element extension F L/(EA).", {"tension": response.tension[0]})


def _catenary_parameter(span: float, length: float) -> float:
    if length <= span:
        raise ValueError("A catenary must be longer than its horizontal span.")
    # The relevant root is O(span^2/sag); this bracket avoids the artificial
    # sinh overflow produced by an unnecessarily tiny lower endpoint.
    return brentq(lambda a: 2 * a * np.sinh(span / (2 * a)) - length, span / 100.0, span * 100.0)


def v002() -> ValidationCase:
    span, length, n = 1.0, 1.02, 30
    linear_density = 0.01
    area, ea = 1e-6, 2e3
    density = linear_density / area
    # Use a slightly longer loaded catenary as the taut initial guess.  If the
    # continuum arc length is used verbatim, every straight FE chord is a tiny
    # bit shorter than its natural segment and the exact unilateral law quite
    # correctly classifies the whole initial mesh as slack.
    initial_loaded_length = length + 1.0e-4
    a = _catenary_parameter(span, initial_loaded_length)
    s = np.linspace(-initial_loaded_length / 2, initial_loaded_length / 2, n + 1)
    xcoord = a * np.arcsinh(s / a)
    zcoord = a * np.cosh(xcoord / a) - a * np.cosh(span / (2 * a))
    pos = np.column_stack([xcoord, np.zeros_like(xcoord), zcoord])
    elements = _batch(np.arange(n), np.arange(1, n + 1), length / n, ea, density, area)
    mass = assemble_mass_matrix(n + 1, elements, {}, kind="consistent")
    gravity = np.tile([0.0, 0.0, -9.80665], n + 1)
    gravity_force = np.asarray(mass @ gravity).reshape(n + 1, 3)
    free_nodes = np.arange(1, n)
    # The reference solution is planar.  Holding y=0 removes a physically
    # irrelevant flat direction from the optimiser without constraining the
    # catenary's in-plane equilibrium.
    variable = np.concatenate([np.array([3 * k, 3 * k + 2]) for k in free_nodes])
    full0 = pos.reshape(-1)

    def fg(x):
        full = full0.copy(); full[variable] = x
        p = full.reshape(n + 1, 3)
        resp = evaluate_cable_elements(p, np.zeros_like(p), elements, length_guard=1e-12)
        f = assemble_element_forces(n + 1, elements, resp) + gravity_force
        U = float(np.sum(resp.elastic_energy) - full @ gravity_force.reshape(-1))
        return U, -f.reshape(-1)[variable]

    opt = minimize(
        lambda x: fg(x)[0],
        full0[variable],
        jac=lambda x: fg(x)[1],
        method="L-BFGS-B",
        options={"gtol":1e-11,"ftol":1e-14,"maxiter":3000,"maxls":100},
    )
    full = full0.copy(); full[variable] = opt.x
    computed = full.reshape(n + 1, 3)
    polygon_length = float(np.sum(np.linalg.norm(np.diff(computed, axis=0), axis=1)))
    a_loaded = _catenary_parameter(span, polygon_length)
    analytic_z = a_loaded * np.cosh(computed[:,0] / a_loaded) - a_loaded * np.cosh(span/(2*a_loaded))
    rms = float(np.sqrt(np.mean((computed[:,2]-analytic_z)**2)) / span)
    resp = evaluate_cable_elements(computed, np.zeros_like(computed), elements, length_guard=1e-12)
    H = linear_density * 9.80665 * a_loaded
    endpoint_theory = math.hypot(H, linear_density * 9.80665 * polygon_length / 2)
    tension_error = abs(resp.tension[0]-endpoint_theory)/endpoint_theory
    metric = max(rms, tension_error)
    return ValidationCase("V-002", metric < 0.01, metric, 0.01, "Finite-element cable approaches an inextensible catenary.", {"shape_rms":rms,"endpoint_tension_error":tension_error,"optimizer_success":bool(opt.success)})


def v003() -> ValidationCase:
    L, E, rho, area, n = 1.0, 2e9, 1200.0, 1e-6, 30
    le = L/n
    # Scalar axial bar FE matrices, fixed at node 0, free at node n.
    K=np.zeros((n,n)); M=np.zeros((n,n))
    ke=E*area/le*np.array([[1,-1],[-1,1]],float)
    me=rho*area*le/6*np.array([[2,1],[1,2]],float)
    for e in range(n):
        nodes=[e,e+1]
        for aidx in range(2):
            for bidx in range(2):
                if nodes[aidx]>0 and nodes[bidx]>0:
                    K[nodes[aidx]-1,nodes[bidx]-1]+=ke[aidx,bidx]
                    M[nodes[aidx]-1,nodes[bidx]-1]+=me[aidx,bidx]
    vals=eigh(K,M,eigvals_only=True)
    omega=math.sqrt(vals[0])
    theory=math.pi*math.sqrt(E/rho)/(2*L)
    metric=abs(omega-theory)/theory
    return ValidationCase("V-003", metric<0.01, metric,0.01,"First fixed-free longitudinal FE mode recovers c=sqrt(E/rho).",{"omega":omega,"theory":theory})


def _pure_mode_period(fast: bool) -> tuple[float,float]:
    cfg=load_config(_base_config()); cfg.run.mode="torus"
    p=TorusParameters.from_config(cfg)
    amplitude=0.35
    y0=np.array([amplitude if fast else 0.0, 0.0 if fast else amplitude, 0.0,0.0])
    def event(_t,y): return y[2] if fast else y[3]
    event.direction=1.0; event.terminal=False
    sol=solve_ivp(lambda t,y:torus_rhs(t,y,p),(1e-9,10),y0,method="DOP853",rtol=1e-12,atol=1e-14,events=event,max_step=0.005)
    times=sol.t_events[0]
    # Starting maximum has negative acceleration; first direction=+1 turning point is the opposite maximum, then every full period.
    numerical=float(times[1]-times[0])
    length=p.lower_length if fast else p.lower_length+p.geometry.h
    theory=4*math.sqrt(length/p.gravity_magnitude)*ellipk(math.sin(amplitude/2)**2)
    return numerical,theory


def v004() -> ValidationCase:
    num,theory=_pure_mode_period(True); metric=abs(num-theory)/theory
    return ValidationCase("V-004",metric<5e-4,metric,5e-4,"A1 pure fast mode matches the nonlinear pendulum period.",{"numerical":num,"theory":theory})


def v005() -> ValidationCase:
    num,theory=_pure_mode_period(False); metric=abs(num-theory)/theory
    return ValidationCase("V-005",metric<5e-4,metric,5e-4,"A1 pure slow mode matches the nonlinear pendulum period.",{"numerical":num,"theory":theory})


def v006() -> ValidationCase:
    raw=_base_config()
    # This case verifies the *inextensible* light-string limit.  The ordinary
    # example modulus (2 GPa) leaves enough upper-cable axial compliance for
    # the junction to move along the support axis and produces an O(1e-2)
    # frequency-ratio correction.  Raise EA explicitly rather than hiding
    # that real physical correction in the acceptance threshold.
    raw["cables"]["upper_A"]["young_modulus"]={"value":2e12,"unit":"Pa"}
    raw["cables"]["lower"]["young_modulus"]={"value":2e12,"unit":"Pa"}
    cfg=load_config(raw); model=FullCableModel(cfg); eq=solve_static_equilibrium(cfg,model)
    K,M=_linearised_matrices(model,eq.positions); vals=eigh(K,M,eigvals_only=True); vals=vals[vals>1e-5]
    omega=np.sqrt(vals[:2]); ratio=max(omega)/min(omega)
    A,B=eq.positions[0],eq.positions[1]; J=eq.positions[model.topology.junction_node]; P=eq.positions[model.topology.bob_node]
    geom=reduced_geometry_from_loaded_state(A,B,J,model.gravity); lower=np.linalg.norm(P-J)
    theory=math.sqrt(1+geom.h/lower); metric=abs(ratio-theory)/theory
    return ValidationCase("V-006",metric<5e-4,metric,5e-4,"H1 low modes recover rho^2=1+h/l in the light-string stiff limit.",{"omega":omega.tolist(),"ratio":ratio,"theory":theory})


def v007() -> ValidationCase:
    raw=_base_config(); raw["junction"]["mass"]={"value":0.02,"unit":"kg"}
    raw["cables"]["upper_A"]["elements"]=1; raw["cables"]["lower"]["elements"]=1
    raw["cables"]["upper_A"]["density"]={"value":1e-6,"unit":"kg/m^3"}; raw["cables"]["lower"]["density"]={"value":1e-6,"unit":"kg/m^3"}
    cfg=load_config(raw); model=FullCableModel(cfg); eq=solve_static_equilibrium(cfg,model); K,M=_linearised_matrices(model,eq.positions)
    axis=(eq.positions[1]-eq.positions[0]); axis/=np.linalg.norm(axis); down=model.gravity/np.linalg.norm(model.gravity); slow=np.cross(down,axis); slow/=np.linalg.norm(slow)
    node_to_offset={int(n):3*i for i,n in enumerate(model.topology.free_nodes)}
    Bmat=np.zeros((model.position_dof_count,2))
    for col,node in enumerate((model.topology.junction_node,model.topology.bob_node)):
        base=node_to_offset[node]; Bmat[base:base+3,col]=slow
    K2=Bmat.T@K@Bmat; M2=Bmat.T@M@Bmat; omega2=eigh(K2,M2,eigvals_only=True)
    A,Bp=eq.positions[0],eq.positions[1]; J=eq.positions[model.topology.junction_node]; P=eq.positions[model.topology.bob_node]
    geom=reduced_geometry_from_loaded_state(A,Bp,J,model.gravity); l=float(np.linalg.norm(P-J)); h=geom.h; H=h+l; g=float(np.linalg.norm(model.gravity)); mj=model.junction_mass; m=model.bob_mass; eps=mj/(mj+m)
    roots=np.array([g*(H-math.sqrt(H*H-4*eps*h*l))/(2*eps*h*l),g*(H+math.sqrt(H*H-4*eps*h*l))/(2*eps*h*l)])
    metric=float(np.max(np.abs(omega2-roots)/roots))
    return ValidationCase("V-007",metric<2e-3,metric,2e-3,"Finite-junction transverse eigenvalues match the analytic two-root formula.",{"numeric_omega2":omega2.tolist(),"analytic_omega2":roots.tolist()})


def _string_pendulum_frequency(string_mass_ratio: float, n: int=40) -> float:
    L=1.0; m=1.0; g=9.80665; area=1e-6; E=1e11; EA=E*area; total_mass=string_mass_ratio*m; rho=total_mass/(area*L) if total_mass>0 else 1e-9
    le=L/n; me=total_mass/n
    tensions=np.array([g*(m+(n-e-0.5)*me) for e in range(n)])
    loaded=le+tensions*le/EA
    z=np.concatenate([[0.0],-np.cumsum(loaded)]); positions=np.column_stack([np.zeros(n+1),np.zeros(n+1),z]); velocities=np.zeros_like(positions)
    elements=_batch(np.arange(n),np.arange(1,n+1),le,EA,rho,area)
    resp=evaluate_cable_elements(positions,velocities,elements,length_guard=1e-12)
    K=-assemble_element_tangent(n+1,elements,resp.tangent_position).toarray()
    M=assemble_mass_matrix(n+1,elements,{n:m},kind="consistent").toarray()
    dofs=np.array([3*k for k in range(1,n+1)])
    vals=eigh(K[np.ix_(dofs,dofs)],M[np.ix_(dofs,dofs)],eigvals_only=True); return math.sqrt(vals[vals>1e-8][0])


def v008() -> ValidationCase:
    ratios=np.array([0.001,0.003,0.006,0.01]); w0=math.sqrt(9.80665)
    shifts=np.array([_string_pendulum_frequency(r)/w0-1 for r in ratios]); slope=float(np.dot(ratios,shifts)/np.dot(ratios,ratios)); metric=abs(slope-1/12)/(1/12)
    return ValidationCase("V-008",metric<0.10,metric,0.10,"Distributed lower-string mass approaches the Rayleigh slope +1/12.",{"slope":slope,"ratios":ratios.tolist(),"shifts":shifts.tolist()})


def v009() -> ValidationCase:
    cfg=load_config(_base_config()); model=FullCableModel(cfg); q=model.topology.reference_positions.copy()
    # Collapse every cable path to 80% of rest length while preserving endpoints of each chain in a separate direction.
    A=q[0].copy(); B=q[1].copy(); J=0.5*(A+B)+np.array([0,0,-0.1]); P=J+np.array([0,0,-0.1]); q[model.topology.junction_node]=J; q[model.topology.bob_node]=P
    for path in model.topology.cable_node_paths.values():
        for k,node in enumerate(path): q[node]=(1-k/(len(path)-1))*q[path[0]]+(k/(len(path)-1))*q[path[-1]]
    qf=model.topology.pack_free(q); vf=np.zeros_like(qf); ev=model.evaluate(0,qf,vf,include_aero=False); acc=model.mass_solve(ev.free_force).reshape(-1,3)
    bob_free_index=list(model.topology.free_nodes).index(model.topology.bob_node); bob_acc=acc[bob_free_index]
    metric=float(np.linalg.norm(bob_acc-model.gravity)/np.linalg.norm(model.gravity))
    return ValidationCase("V-009",metric<1e-12,metric,1e-12,"When all lower elements are slack the bob is in free fall.",{"bob_acceleration":bob_acc.tolist(),"active_count":int(ev.active.sum())})


def _retension_run(rtol:float,max_step:float):
    m,g,L,k,c=1.0,9.80665,1.0,1000.0,8.0; y0=np.array([0.8,0.0])
    def rhs(_t,y):
        delta=y[0]-L; trial=k*delta+c*y[1]; T=trial if delta>0 and trial>0 else 0.0; return [y[1],g-T/m]
    def event(_t,y): return y[0]-L
    event.direction=1; event.terminal=False
    sol=solve_ivp(rhs,(0,0.8),y0,method="Radau",rtol=rtol,atol=rtol*1e-3,max_step=max_step,events=event,dense_output=False)
    t=sol.t; y=sol.y[0]; v=sol.y[1]; delta=np.maximum(y-L,0); trial=k*delta+c*v; active=(delta>0)&(trial>0); T=np.where(active,trial,0); U=0.5*m*v*v-m*g*y+0.5*k*delta*delta
    diss=np.where(active,c*v*v,np.where((delta>0)&~active,np.maximum(-k*delta*v,0),0)); D=np.concatenate([[0],np.cumsum(0.5*(diss[1:]+diss[:-1])*np.diff(t))]); residual=U-U[0]+D
    return float(sol.t_events[0][0]),float(np.max(np.abs(residual))/max(abs(U[0]),m*g*L))


def v010() -> ValidationCase:
    t1,e1=_retension_run(1e-8,1e-3); t2,e2=_retension_run(1e-10,2e-4); metric=max(abs(t1-t2)/t2,e1,e2)
    return ValidationCase("V-010",metric<1e-3,metric,1e-3,"Unilateral retension timing converges and the work-energy ledger closes.",{"time_coarse":t1,"time_fine":t2,"energy_coarse":e1,"energy_fine":e2})


def v011() -> ValidationCase:
    raw=_base_config(); raw["solver"]["t_end"]={"value":0.12,"unit":"s"}; raw["initial_condition"]["phi"]={"value":2.0,"unit":"degree"}
    cfgp=load_config(raw); mp=FullCableModel(cfgp); eqp=solve_static_equilibrium(cfgp,mp); rp=simulate_full(cfgp,model=mp,equilibrium=eqp)
    rawn=copy.deepcopy(raw); rawn["initial_condition"]["phi"]={"value":-2.0,"unit":"degree"}; cfgn=load_config(rawn); mn=FullCableModel(cfgn); eqn=solve_static_equilibrium(cfgn,mn); rn=simulate_full(cfgn,model=mn,equilibrium=eqn)
    bp=rp.positions[:,-1]; bn=rn.positions[:,-1]; center=0.5*(rp.positions[0,0]+rp.positions[0,1]); mirrored=bn.copy(); mirrored[:,0]=2*center[0]-mirrored[:,0]
    trajectory=float(np.max(np.linalg.norm(bp-mirrored,axis=1))/0.3)
    ta=mp.topology.cable_slices["upper_A"]; tb=mp.topology.cable_slices["upper_B"]; tension=float(max(np.max(np.abs(rp.tension[:,ta]-rn.tension[:,tb])),np.max(np.abs(rp.tension[:,tb]-rn.tension[:,ta])))/max(np.max(rp.tension),1e-12))
    metric=max(trajectory,tension)
    return ValidationCase("V-011",metric<2e-4,metric,2e-4,"Mirror releases generate mirrored trajectories and swap upper tensions.",{"trajectory":trajectory,"tension":tension})


def _low_modes_for_mass(mass:float):
    raw=_base_config(); raw["bob"]["mass"]={"value":mass,"unit":"kg"}; raw["junction"]["mass"]={"value":mass*1e-5,"unit":"kg"}; raw["cables"]["upper_A"]["density"]={"value":1e-4,"unit":"kg/m^3"}; raw["cables"]["lower"]["density"]={"value":1e-4,"unit":"kg/m^3"}
    # Eliminate the mass-dependent static extension.  V-012 is explicitly an
    # ideal light-string, high-EA limit test; finite EA should be assessed by
    # separate ablation rather than silently contaminating this invariant.
    raw["cables"]["upper_A"]["young_modulus"]={"value":2e12,"unit":"Pa"}
    raw["cables"]["lower"]["young_modulus"]={"value":2e12,"unit":"Pa"}
    cfg=load_config(raw); model=FullCableModel(cfg); eq=solve_static_equilibrium(cfg,model); K,M=_linearised_matrices(model,eq.positions); vals=eigh(K,M,eigvals_only=True); return np.sqrt(vals[vals>1e-5][:2])


def v012() -> ValidationCase:
    w1=_low_modes_for_mass(0.1); w2=_low_modes_for_mass(0.4); metric=float(np.max(np.abs(w1-w2)/w2))
    return ValidationCase("V-012",metric<1e-4,metric,1e-4,"Light-string stiff-limit frequencies are independent of bob mass.",{"omega_0.1":w1.tolist(),"omega_0.4":w2.tolist()})


def v013() -> ValidationCase:
    K=np.array([[1000,0,640],[0,1000,360],[0,0,1]],float); R=np.eye(3); t=np.zeros(3); dist=(0.1,-0.02,0.001,-0.002,0.005); cam=PinholeCamera(K,R,t,dist)
    points=np.array([[0.1,-0.2,2.0],[0.3,0.4,3.0]]); pixels=cam.project(points)
    # Independent scalar Brown-Conrady computation.
    expected=[]
    for X,Y,Z in points:
        x,y=X/Z,Y/Z; r2=x*x+y*y; k1,k2,p1,p2,k3=dist; radial=1+k1*r2+k2*r2**2+k3*r2**3; xd=x*radial+2*p1*x*y+p2*(r2+2*x*x); yd=y*radial+p1*(r2+2*y*y)+2*p2*x*y; expected.append([1000*xd+640,1000*yd+360])
    projection=float(np.max(np.abs(pixels-np.asarray(expected))))
    time=np.linspace(0,1,1001); values=np.column_stack([time,2*time]); ft,av=sample_with_exposure(time,values,frame_rate=20,exposure_time=0.02,sub_samples=17); exposure=float(np.max(np.abs(av[:,0]-ft)))
    metric=max(projection,exposure)
    return ValidationCase("V-013",metric<1e-10,metric,1e-10,"Pinhole distortion and finite-exposure averaging match independent analytic calculations.",{"projection_abs":projection,"exposure_abs":exposure})


_CASES: list[Callable[[],ValidationCase]]=[v001,v002,v003,v004,v005,v006,v007,v008,v009,v010,v011,v012,v013]


def run_validation_suite(*, fast: bool = False, output_directory: str | Path | None = "validation/generated") -> dict[str, Any]:
    functions=_CASES if not fast else [v001,v003,v004,v005,v006,v007,v009,v010,v013]
    cases=[]
    for fn in functions:
        try: cases.append(fn())
        except Exception as exc: cases.append(ValidationCase(fn.__name__.upper(),False,float("inf"),0.0,"Validation raised an exception.",{"error":f"{type(exc).__name__}: {exc}"}))
    passed=all(c.passed for c in cases); report={"passed":passed,"fast":fast,"cases":[asdict(c) for c in cases]}
    if output_directory is not None:
        out = Path(output_directory)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / ("validation_fast.json" if fast else "validation_report.json"), report)
        lines = [
            "# YP-FPSim 数值验证报告", "",
            f"- 模式：`{'fast' if fast else 'full'}`",
            f"- 总体：`{'PASS' if passed else 'FAIL'}`", "",
            "| 案例 | 状态 | 指标 | 阈值 | 说明 |",
            "|---|---:|---:|---:|---|",
        ]
        for c in cases:
            lines.append(
                f"| {c.case} | {'PASS' if c.passed else 'FAIL'} | "
                f"{c.metric:.6g} | {c.threshold:.6g} | {c.description} |"
            )
        lines += ["", "该报告验证数值实现与解析/半解析基准；不构成实验 `VALIDATED` 或 `PREDICTIVE` 证明。"]
        (out / ("validation_fast.md" if fast else "validation_report.md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
