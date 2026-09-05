#!/usr/bin/env python3
"""Four bounded matched-state studies through the public solver and file exports."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import shutil
from types import SimpleNamespace
import time
import numpy as np
from scipy.linalg import eigh
from scipy.optimize import root

ROOT=Path(__file__).resolve().parents[4]
PROJECT=ROOT/'02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
sys.path.insert(0,str(PROJECT))
from y_pendulum_forward.runner import run_config
from y_pendulum_forward.io import write_result
from y_pendulum_forward.contracts import THEORY_SHA256,JUNCTION_THEORY_SHA256,source_tree_sha256,runtime_versions,json_safe

PLAN={'window_s':2.,'output_dt_s':.005,'mesh_levels':[1,2,4], 'case_mesh_levels':{'larger_amplitude':[2,4,8],'finite_flexibility':[2,4,8]},
      'time_steps_s':[.003,.0015,.00075], 'cable_time_steps_s':[.02,.01,.005],
      'numerical_budget':{'bob_position_m':2e-5,'junction_position_m':1e-4,'frequency_relative':.002,'phase_rad':.03,'minimum_tension_difference_N':.02,'axial_energy_range_difference_J':.001},
      'good_match':{'bob_position_m':.002,'frequency_relative':.01,'phase_rad':.15},
      'counterexample_bob_position_m':.003,
      'cases':[{'id':'small_taut','theta':.02,'junction_mass':.0008,'EA':10.,'mu':.0008},
               {'id':'larger_amplitude','theta':.3,'junction_mass':.0008,'EA':10.,'mu':.0008},
               {'id':'junction_inertia','theta':.12,'junction_mass':.04,'EA':10.,'mu':.0008},
               {'id':'finite_flexibility','theta':.12,'junction_mass':.0008,'EA':2.5,'mu':.0008}],
      'cable_tolerance_levels':{'rtol':[1.6e-5,4e-6,1e-6],'atol':[1.6e-7,4e-8,1e-8]},
      'outside_qualified_domain':[{'case':'additional heavy flexible rope','theta':.12,'junction_mass':.0008,'EA':2.5,'mu':.005,'status':'JUNCTION_SPATIAL_RESOLUTION_NOT_MET','J_mesh_difference_m_4_to_8':.0002273108270857179,'J_mesh_difference_m_8_to_16':.00015388890921892183,'budget_m':.0001,'evidence':'acceptance-05 and acceptance-06','decision':'retain failed stress case; do not broaden high-cost mesh work for short-term personal use. Required compliance representative keeps the same light-rope density as the other cases and changes stiffness.'}],
      'window_basis':'two-second bounded personal-use comparison; cycle estimates use consecutive opposite-direction zero crossings, not statistical frequency confidence',
      'scope':'synthetic gravity-only matched held endpoints; numerical budgets are finite-window resolutions, not experimental uncertainty'}

def configurations(case,n,step,T=2.):
    theta=case['theta'];h=.3;ell=.6;s=np.hypot(.2,h);mb=.08;mj=case['junction_mass'];g=9.81
    er=np.array([0.,np.sin(theta),np.cos(theta)]);J=h*er;bob=(h+ell)*er
    physical={'A':[-.2,0.,0.],'B':[.2,0.,0.],'e_z':[0.,0.,1.],'g':g,'mass':mb,'s_A':s,'s_B':s,'lower_length':ell,'T':T}
    common={'schema_version':'YPS-FWD-CONFIG-1.0','units':'SI','numerics':{'method':'DOP853','rtol':1e-8,'atol':1e-10,'max_step':step,'output_dt':.005,'event_cluster_tolerance':1e-9},'observation':{'type':'orthographic','axis_1':[1.,0.,0.],'axis_2':[0.,1.,0.],'t0':0.,'record_times':{'kind':'uniform','start':0.,'stop':T,'step':.005}},'metadata':{'purpose':PLAN['scope'],'case_id':case['id']}}
    torus={**deepcopy(common),'model_id':'FWD-TORUS-1.0','theory_sha256':THEORY_SHA256,'physical':{**physical,'initial_state':[0.,theta,0.,0.]}}
    j3={**deepcopy(common),'model_id':'YP-FWD-J3-v1','theory_sha256':JUNCTION_THEORY_SHA256,'physical':{**physical,'junction_mass':mj,'initial_state':[theta,0.,*er,0.,0.,0.]}}
    # Independent elastic-catenary equilibrium under the radial gravity
    # component g*cos(theta), including distributed rope weight. This fixes
    # MATERIAL lengths before any mesh refinement; the production held solve
    # still resolves the full gravity and transverse sag, without fitting data.
    EA=case['EA'];mu=case['mu'];gr=g*np.cos(theta)
    coefficient=1+mb*gr/EA
    Llower=2*ell/(coefficient+np.sqrt(coefficient**2+2*mu*gr*ell/EA))
    bottom=(mb+mj+mu*Llower)*gr/2
    qx,qw=np.polynomial.legendre.leggauss(48)
    def residual(values):
        horizontal,L=values;coordinate=(qx+1)*L/2
        vertical=bottom+mu*gr*(L-coordinate)
        tension=np.sqrt(horizontal**2+vertical**2)
        dx=L/2*np.dot(qw,horizontal/tension+horizontal/EA)
        dz=L/2*np.dot(qw,vertical/tension+vertical/EA)
        return [dx-.2,dz-h]
    equilibrium=root(residual,[bottom*.2/h,s/(1+bottom*s/h/EA)],tol=1e-11)
    if not equilibrium.success or max(abs(np.asarray(residual(equilibrium.x))))>1e-10:
        raise RuntimeError('independent elastic-catenary material length construction failed')
    lengths={'A':float(equilibrium.x[1]),'B':float(equilibrium.x[1]),'lower':float(Llower)}
    chord={'A':s,'B':s,'lower':ell}
    branches={k:{'L0':lengths[k],'mu':case['mu'],'EA':case['EA'],'Ca':0.,'delta':1e-6,'c_parallel':0.,'c_perp':0.,'d_parallel':0.,'d_perp':0.,'material_domain':{'kind':'open_box','lambda_lower':.2,'lambda_upper':3.,'rate_lower':-1000.,'rate_upper':1000.}} for k in chord}
    cable={**deepcopy(common),'model_id':'FWD-CABLE-1.0','theory_sha256':THEORY_SHA256,
           'physical':{'g':g,'e_z':[0.,0.,1.],'junction_mass':mj,'bob_mass':mb,'rho_air':0.,'bob_volume':0.,'bob_c1':0.,'bob_c2':0.,'lambda_min':.2,'T':T,'branches':branches},
           'inputs':{'support_A':{'kind':'constant','value':physical['A']},'support_B':{'kind':'constant','value':physical['B']},'air_velocity':{'kind':'zero'},'distributed_forces':{k:{'kind':'zero'} for k in chord},'junction_force':{'kind':'zero'},'bob_force':{'kind':'zero'},'exit_guards':[],'hold_release':{'source':'initial_static_reaction','history':'instantaneous','start':0.,'duration':0.}},
           'initial_state':{'mode':'STATIC_HOLD_RELEASE','hold':{'fixed_nodes':{'junction':J.tolist(),'bob':bob.tolist()}},'seed':{'r_J':J.tolist(),'r_m':bob.tolist()}}}
    cable['numerics'].update(method='Radau',rtol=1e-6*(step/.005)**2,atol=1e-8*(step/.005)**2,elements={k:n for k in chord},quadrature_order=2,static_multistart=8,static_maxiter=800,static_gradient_tolerance=2e-7,static_energy_tolerance=1e-10,static_uniqueness_tolerance=1e-4)
    return {'torus':torus,'junction':j3,'cable':cable}


def frequency_phase(t,y):
    # Phase is accumulated from consecutive opposite-direction crossings, interpolated
    # monotonically between crossings; endpoints use adjacent full-cycle rates.
    # It measures this observable's cycle timing, not a unique mixed-mode phase.
    inds=np.flatnonzero(y[:-1]*y[1:]<0)
    crossings=t[inds]-y[inds]*(t[inds+1]-t[inds])/(y[inds+1]-y[inds])
    if len(crossings)<2:return {'status':'NOT_IDENTIFIABLE','crossings_s':crossings.tolist(),'omega_rad_s':None},None
    period=float(np.mean(np.diff(crossings)));omega=np.pi/period
    phase=np.interp(t,crossings,np.pi*np.arange(len(crossings)))
    left=t<crossings[0];right=t>crossings[-1]
    phase[left]=np.pi*(t[left]-crossings[0])/(crossings[1]-crossings[0])
    phase[right]=np.pi*(len(crossings)-1)+np.pi*(t[right]-crossings[-1])/(crossings[-1]-crossings[-2])
    return {'status':'OBSERVABLE_CYCLE_ESTIMATE','crossings_s':crossings.tolist(),'omega_rad_s':float(omega),'whole_window_phase_advance_rad':float(phase[-1]-phase[0]),'definition':'r_m,y consecutive opposite-direction zero crossings; endpoint extrapolation from adjacent half-cycle; two-second observable estimate, not a mixed-mode eigenfrequency'},phase


def execute(config,output,reuse=None):
    start=time.perf_counter();reused=False
    candidate=reuse/output.name if reuse is not None else None
    if candidate is not None and candidate.is_dir():
        saved_config=json.loads((candidate/'config.snapshot.json').read_text())
        saved_result=json.loads((candidate/'result.json').read_text())
        if saved_config==config and saved_result['metadata']['source_tree_sha256']==source_tree_sha256():
            shutil.copytree(candidate,output);reused=True
    if not reused:
        result=run_config(config);write_result(output,config,result,plots=False)
    else:
        saved=json.loads((output/'result.json').read_text())
        result=SimpleNamespace(**{k:saved[k] for k in ('model_id','numerical_status','returned_interval','tau','diagnostics','metadata','events')})
    print(output.name,result.numerical_status,f'{time.perf_counter()-start:.1f}s',flush=True)
    # All comparisons read the serialized public outputs, including observations.
    summary=json.loads((output/'result.json').read_text());data=dict(np.load(output/'trajectory.npz',allow_pickle=False))
    if result.numerical_status!='SUCCESS_SINGLE_RUN':raise RuntimeError(f'{output.name}: {result.events}')
    result=SimpleNamespace(**{k:summary[k] for k in ('model_id','numerical_status','returned_interval','tau','diagnostics','metadata','events')})
    t=data['time'];bob=data.get('state__r_m',data.get('derived__r_m'));J=data.get('state__r_J',data.get('derived__J'))
    projected=data['observations__values'];obs_time=data['observations__model_time']
    if not np.allclose(projected[:,1],np.interp(obs_time,t,bob[:,1]),atol=1e-10,rtol=0):raise AssertionError('observation readback mismatch')
    freq,phase=frequency_phase(t,bob[:,1]);d=result.diagnostics
    stats={'artifact':str(output.name),'model_id':result.model_id,'theory_sha256':summary['theory_sha256'],'source_tree_sha256':summary['metadata']['source_tree_sha256'],'numerical_status':result.numerical_status,'returned_interval':result.returned_interval,'valid_end_s':result.tau,'accepted_steps':d.get('accepted_steps'),'actual_max_step_s':d.get('max_actual_step',d.get('maximum_accepted_step')),'frequency':freq,'elapsed_s':time.perf_counter()-start,'reused_from':str(candidate) if reused else None}
    if result.model_id=='FWD-CABLE-1.0':
        stats['minimum_tension_N']=min(float(np.min(data['derived__branches__'+k+'__N'])) for k in ('A','B','lower'))
        axial=data['derived__V_ax'];stats['internal_energy']={'definition':'total axial elastic energy, includes static preload; output-sampled range is not isolated wave energy or a continuous-time maximum','initial_J':float(axial[0]),'range_J':float(np.ptp(axial)),'fast_mode_energy_J':None}
        nodes=data['state__node_positions'][0];mapping={}
        for k,ids in result.metadata['branch_nodes'].items():
            points=nodes[ids];straight=points[0]+np.linspace(0,1,len(ids))[:,None]*(points[-1]-points[0])
            mapping[k]={'unloaded_material_length_m':config['physical']['branches'][k]['L0'],'loaded_arc_length_m':float(np.sum(np.linalg.norm(np.diff(points,axis=0),axis=1))),'endpoint_chord_length_m':float(np.linalg.norm(points[-1]-points[0])),'max_sag_from_chord_m':float(np.max(np.linalg.norm(points-straight,axis=1)))}
        stats['initial_mapping']=mapping;stats['held_preparation']=d.get('preparation')
    else:
        stats['minimum_tension_N']=min(float(np.min(data['derived__'+k])) for k in ('T_A','T_B','T_lower'))
        stats['internal_energy']={'axial_elastic_energy_J':None,'rope_wave_energy_J':None,'reason':'inextensible massless ropes; not defined'}
        if result.model_id=='YP-FWD-J3-v1':
            # Small-angle two-angle mass/stiffness from Cartesian kinetic energy
            # and gravity, mass-normalized modes. Proxy explicitly not nonlinear
            # modal energy for the large-amplitude case.
            p=config['physical'];h=.3;ell=.6;m=p['mass'];mj=p['junction_mass'];g=p['g']
            M=np.array([[(m+mj)*h*h,m*h*ell],[m*h*ell,m*ell*ell]]);K=np.diag([(m+mj)*g*h,m*g*ell]);w2,V=eigh(K,M)
            angles=np.column_stack((np.arctan2(J[:,1],J[:,2]),np.arctan2((bob-J)[:,1],(bob-J)[:,2])))
            amplitudes=angles@M@V;vel=np.gradient(amplitudes,t,axis=0,edge_order=2)
            fast=.5*(vel[:,-1]**2+w2[-1]*amplitudes[:,-1]**2)
            stats['internal_energy']['linear_fast_mode_proxy_J']={'initial':float(fast[0]),'maximum':float(np.max(fast)),'definition':'quadratic upright eigenmode projection; velocity from exported 5 ms trajectory, sampling proxy only'}
    return {'stats':stats,'t':t,'bob':bob,'J':J,'phase':phase}


def difference(a,b):
    sa,sb=a['stats'],b['stats'];wa=sa['frequency']['omega_rad_s'];wb=sb['frequency']['omega_rad_s']
    return {'initial_bob_position_difference_m':float(np.linalg.norm(a['bob'][0]-b['bob'][0])),'initial_junction_position_difference_m':float(np.linalg.norm(a['J'][0]-b['J'][0])),'bob_position_m':float(np.max(np.linalg.norm(a['bob']-b['bob'],axis=1))),'junction_position_m':float(np.max(np.linalg.norm(a['J']-b['J'],axis=1))),'frequency_relative':abs(wa-wb)/abs(wb) if wa and wb else None,'phase_rad':float(np.max(np.abs((a['phase']-a['phase'][0])-(b['phase']-b['phase'][0])))) if a['phase'] is not None and b['phase'] is not None else None,'minimum_tension_difference_N':abs(sa['minimum_tension_N']-sb['minimum_tension_N']),'axial_energy_range_difference_J':abs(sa['internal_energy'].get('range_J',0.)-sb['internal_energy'].get('range_J',0.)) if sa['model_id']==sb['model_id']=='FWD-CABLE-1.0' else None}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--pilot',action='store_true');parser.add_argument('--reuse',type=Path);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);source=source_tree_sha256();(args.output/'plan.json').write_text(json.dumps(PLAN,indent=2)+'\n')
    (args.output/'compare_models.source.py').write_bytes(Path(__file__).read_bytes())
    report={'status':'RUNNING','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_tree_sha256':source,'runtime':runtime_versions(),'command':[sys.executable,*sys.argv],'cases':[],'errors':[]}
    try:
        for case in PLAN['cases']:
            if args.pilot:
                execute(configurations(case,2,.004,T=.1)['cable'],args.output/(case['id']+'-pilot'));break
            meshes=PLAN['case_mesh_levels'].get(case['id'],PLAN['mesh_levels']);finest_n=meshes[-1]
            runs={};row={'case':case,'models':{},'time_refinement':{},'space_refinement':{},'comparisons':{}}
            def run(model,n,step):
                key=(model,n if model=='cable' else 0,step)
                if key not in runs:runs[key]=execute(configurations(case,n,step)[model],args.output/f"{case['id']}-{model}-n{key[1]}-dt{step:g}",args.reuse)
                return runs[key]
            for model in ('torus','junction','cable'):
                steps=PLAN['cable_time_steps_s'] if model=='cable' else PLAN['time_steps_s']
                levels=[run(model,finest_n,step) for step in steps]
                differences=[difference(levels[i],levels[i+1]) for i in range(2)];row['time_refinement'][model]=differences;row['models'][model]=levels[-1]['stats'];row.setdefault('time_levels',{})[model]=[r['stats'] for r in levels]
                actual=[r['stats']['actual_max_step_s'] for r in levels]
                if not all(actual[i]>1.05*actual[i+1] for i in range(2)):report['errors'].append(f"{case['id']} {model} actual steps not separated: {actual}")
                if levels[-1]['stats']['minimum_tension_N']<=0:report['errors'].append(f"{case['id']} {model} lost positive tension")
                for metric,budget in PLAN['numerical_budget'].items():
                    value=differences[-1][metric]
                    if value is not None and value>budget:report['errors'].append(f"{case['id']} {model} time {metric}: {value}")
                if levels[-1]['phase'] is None:report['errors'].append(f"{case['id']} {model} frequency not identifiable")
            space=[run('cable',n,.005) for n in meshes];diffs=[difference(space[i],space[i+1]) for i in range(2)];row['space_refinement']={'differences':diffs,'levels':[r['stats'] for r in space]}
            for metric,budget in PLAN['numerical_budget'].items():
                value=diffs[-1][metric]
                if value is not None and value>budget:report['errors'].append(f"{case['id']} cable space {metric}: {value}")
            for a,b in (('cable','junction'),('junction','torus'),('cable','torus')):
                row['comparisons'][a+'-'+b]=difference(run(a,finest_n,.005 if a=='cable' else .00075),run(b,finest_n,.005 if b=='cable' else .00075))
            for comparison in row['comparisons'].values():
                if max(comparison['initial_bob_position_difference_m'],comparison['initial_junction_position_difference_m'])>1e-12:report['errors'].append(f"{case['id']} unmatched endpoints")
            report['cases'].append(row);(args.output/'summary.partial.json').write_text(json.dumps(json_safe(report),indent=2)+'\n')
        if not args.pilot:
            good=report['cases'][0]['comparisons']['cable-torus']
            for metric,budget in PLAN['good_match'].items():
                if good[metric] is None or good[metric]>budget:report['errors'].append('good match '+metric)
            if max(r['comparisons']['cable-torus']['bob_position_m'] for r in report['cases'][2:])<PLAN['counterexample_bob_position_m']:report['errors'].append('no resolved counterexample')
    except Exception as exc:report['errors'].append(repr(exc))
    if source_tree_sha256()!=source:report['errors'].append('SOURCE_DRIFT')
    report['source_tree_sha256_at_end']=source_tree_sha256();report['status']='PASS' if not report['errors'] else 'FAIL'
    (args.output/'summary.json').write_text(json.dumps(json_safe(report),ensure_ascii=False,indent=2)+'\n');print(report['status'],report['errors'],flush=True)
    return int(bool(report['errors']))
if __name__=='__main__':sys.exit(main())
