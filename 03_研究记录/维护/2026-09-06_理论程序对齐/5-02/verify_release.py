#!/usr/bin/env python3
"""Bounded production release-wave refinement and independent modal acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
import numpy as np
from scipy.integrate import trapezoid

ROOT=Path(__file__).resolve().parents[4]
PROJECT=ROOT/'02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
sys.path[:0]=[str(PROJECT),str(PROJECT/'tests')]
from y_pendulum_forward.runner import run_config
from y_pendulum_forward.io import write_result
from y_pendulum_forward.contracts import source_tree_sha256,runtime_versions,json_safe
from release_reference import wave_config,semi_infinite_wave,modal_release
import test_release_protocol

output=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('acceptance')
output.mkdir(parents=True,exist_ok=False)
source=source_tree_sha256()
plan={'spatial_elements':[32,64,256],'space_max_step_s':5e-5,'time_elements':64,'time_max_step_s':[1e-4,5e-5,2.5e-5],'window_s':.02,'endpoint_relative_threshold':1e-3,'time_position_scale_m':1e-4,'time_velocity_scale_m_s':.01,'time_error_threshold':1e-6,'scope':'synthetic longitudinal strictly taut subproblem before first reflection; no device accuracy claim'}
(output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
cache={}
errors=[]

def run(n,dt):
    key=(n,dt)
    if key in cache:return cache[key]
    config=wave_config(n,dt);config['metadata']={'purpose':plan['scope']}
    start=time.perf_counter();result=run_config(config)
    name=f'n{n}-dt{dt:g}'
    write_result(output/name,config,result,plots=False)
    print(name,result.numerical_status,f'{time.perf_counter()-start:.1f} s',flush=True)
    if result.numerical_status!='SUCCESS_SINGLE_RUN':
        raise RuntimeError(f'{name}: {result.numerical_status}: {result.events}')
    ids=result.metadata['branch_nodes']['lower'];xi=np.linspace(0,1,n+1)
    q=result.state['node_positions'][0,ids,0]-result.state['node_positions'][-1,ids,0]
    v=-result.state['node_velocities'][-1,ids,0]
    N=result.derived['branches']['lower']['N'][-1]
    qr,vr,Nr=semi_infinite_wave(xi,.02)
    midpoint_N=semi_infinite_wave((xi[:-1]+xi[1:])/2,.02)[2]
    front=np.abs(xi-.6)<=2/n
    norms=lambda actual,reference:float(np.sqrt(trapezoid((actual-reference)**2,xi)))
    row={'elements':n,'max_step':dt,'accepted_steps':result.diagnostics['accepted_steps'],'actual_max_step':result.diagnostics['max_actual_step'],'endpoint_q_error':float(abs(q[-1]-qr[-1])/qr[-1]),'endpoint_v_error':float(abs(v[-1]-vr[-1])/vr[-1]),'endpoint_traction_error':float(abs(N[-1]-Nr[-1])/.01),'full_field_L2_q_m':norms(q,qr),'full_field_L2_v_m_s':norms(v,vr),'element_midpoint_L2_traction_N':float(np.sqrt(np.mean((N-midpoint_N)**2))),'front_region_L2_q_m':float(np.sqrt(trapezoid(np.where(front,(q-qr)**2,0.),xi))),'front_region_L2_v_m_s':float(np.sqrt(trapezoid(np.where(front,(v-vr)**2,0.),xi))),'junction_displacement_m':float(np.max(np.linalg.norm(result.state['r_J']-result.state['r_J'][0],axis=1))),'max_transverse_motion_m':float(np.max(np.linalg.norm(result.state['node_positions'][:,:,1:]-result.state['node_positions'][0,:,1:],axis=2))),'traction_reference_N':float(Nr[-1]),'artifact':name}
    # The production P1 endpoint traction is the last element's constant value;
    # keep that first-order boundary error rather than silently extrapolating it.
    cache[key]=(result,row,q,v)
    return cache[key]

try:
    space=[run(n,plan['space_max_step_s'])[1] for n in plan['spatial_elements']]
    finest=space[-1]
    for metric in ('endpoint_q_error','endpoint_v_error','endpoint_traction_error'):
        if finest[metric]>plan['endpoint_relative_threshold']:errors.append(metric)
    if not all(space[i+1]['endpoint_traction_error']<space[i]['endpoint_traction_error'] for i in range(2)):
        errors.append('traction spatial refinement trend')
    temporal=[]
    qref,vref=modal_release(64,[.02],0.,0.,quadrature=256)
    qcheck,vcheck=modal_release(64,[.02],0.,0.,quadrature=384)
    quadrature_error=max(float(np.max(np.abs(qref-qcheck)))/1e-4,float(np.max(np.abs(vref-vcheck)))/.01)
    for dt in plan['time_max_step_s']:
        result,row,q,v=run(64,dt)
        qerror=float(np.max(np.abs(q+qref[0]))/1e-4)
        verror=float(np.max(np.abs(v+vref[0]))/.01)
        temporal.append({**row,'independent_semidiscrete_q_error':qerror,'independent_semidiscrete_v_error':verror})
        if max(qerror,verror)>plan['time_error_threshold']:errors.append(f'time {dt}')
    if quadrature_error>1e-8:errors.append('modal convolution quadrature not resolved')
    # Motion transverse to the exact longitudinal limit and motion of the very
    # heavy root are measured explicitly; neither is fitted away as damping.
    perturbation=(finest['junction_displacement_m']+finest['max_transverse_motion_m'])/1e-4
    if perturbation>1e-3:errors.append('departure from longitudinal limit')
except Exception as exc:
    errors.append(repr(exc));space=locals().get('space',[]);temporal=locals().get('temporal',[]);quadrature_error=None;perturbation=None

with (output/'validation.log').open('w') as handle:
    unit=unittest.TextTestRunner(stream=handle,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_release_protocol))
if not unit.wasSuccessful():errors.append('release unit/modal acceptance')
if source_tree_sha256()!=source:errors.append('SOURCE_DRIFT')
report={'status':'PASS' if not errors else 'FAIL','errors':errors,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_tree_sha256':source,'source_tree_sha256_at_end':source_tree_sha256(),'runtime':runtime_versions(),'command':[sys.executable,*sys.argv],'cwd':str(Path.cwd()),'plan':plan,'spatial':space,'temporal':temporal,'reference_quadrature_scaled_error':quadrature_error,'measured_departure_from_longitudinal_limit':perturbation,'5-C2':test_release_protocol.METRICS,'tests_run':unit.testsRun,'failures':len(unit.failures),'unit_errors':len(unit.errors),'skipped':len(unit.skipped)}
(output/'summary.json').write_text(json.dumps(json_safe(report),ensure_ascii=False,indent=2)+'\n')
print(report['status'],errors,flush=True)
sys.exit(0 if not errors else 1)
