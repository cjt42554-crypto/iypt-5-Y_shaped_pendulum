"""Independent synthetic qualification of the production J3 branch (5-B1--B4)."""
from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
from scipy.optimize import minimize_scalar, brentq

from y_pendulum_forward.contracts import load_json, THEORY_SHA256
from y_pendulum_forward.junction import junction_rhs, junction_derived, validate_junction_config
from y_pendulum_forward.runner import run_config
from junction_reference import (
    CartesianParameters, state_to_cartesian, kkt_accelerations,
    cartesian_energy, integrate_cartesian, tension_events, constraint_values,
    independent_linear_modes, local_cartesian_mass, finite_difference_potential_gradient,
)
from test_junction_guards import first_upper_a_loss_config

PROJECT = Path(__file__).resolve().parents[1]
METRICS = {}


def config():
    c = load_json(PROJECT / 'configs/junction_example.json')
    c['physical']['obstacles'] = []
    c['observation'] = None
    return c


def state(theta, alpha, beta, nu=0., ad=0., bd=0.):
    n = np.array([np.sin(alpha), np.cos(alpha)*np.sin(beta), np.cos(alpha)*np.cos(beta)])
    eta = ad*np.array([np.cos(alpha), -np.sin(alpha)*np.sin(beta), -np.sin(alpha)*np.cos(beta)])
    eta += bd*np.array([0., np.cos(alpha)*np.cos(beta), -np.cos(alpha)*np.sin(beta)])
    return np.r_[theta, nu, n, eta]


def modal_state(vector, amplitude):
    q = amplitude * vector / np.max(np.abs(vector))
    n = np.array([q[1], q[2], np.sqrt(1-q[1]**2-q[2]**2)])
    return np.r_[q[0], 0., n, [0., 0., 0.]]


def omega_formula(p):
    eta = p.junction_mass/(p.junction_mass+p.mass)
    disc = np.sqrt((p.h+p.lower_length)**2 - 4*eta*p.h*p.lower_length)
    return np.sort(np.sqrt([p.g/p.lower_length, 2*p.g/(p.h+p.lower_length+disc),
                           p.g*(p.h+p.lower_length+disc)/(2*eta*p.h*p.lower_length)]))


def positions(result):
    return np.c_[result.state['r_J'], result.state['r_m']]


class JunctionQualificationTests(unittest.TestCase):
    def test_5_b1_independent_cartesian_acceleration_tensions_and_energy(self):
        rng = np.random.default_rng(20260905)
        errors=[]; conditions=[]; ratios=[]; rejected=0; attempts=0
        while len(errors)<120 and attempts<5000:
            attempts += 1
            c=config(); a,b,h=rng.uniform(.16,.24),rng.uniform(.16,.24),rng.uniform(.25,.35)
            ratio=(.01,.1,1.)[len(errors)%3]
            c['physical'].update(A=[-a,0.,0.],B=[b,0.,0.],s_A=float(np.hypot(a,h)),
                                 s_B=float(np.hypot(b,h)),junction_mass=ratio)
            y=state(*rng.uniform(-.5,.5,3),*rng.uniform(-2.,2.,3))
            c['physical']['initial_state']=y.tolist()
            rp=CartesianParameters.from_physical(c['physical']); z=state_to_cartesian(rp,y)
            acceleration,tensions,condition=kkt_accelerations(rp,z)
            if np.min(tensions)<=1e-5 or condition>1e6:
                rejected+=1; continue
            issues,p=validate_junction_config(c)
            self.assertEqual(issues,[])
            dy=junction_rhs(p,0.,y); d=junction_derived(p,y)
            actual_acc=np.r_[d['a_J'][0],d['a_m'][0]]
            actual_t=np.array([d[k][0] for k in ('T_A','T_B','T_lower')])
            e_a=np.linalg.norm(actual_acc-acceleration)/(rp.g+np.linalg.norm(acceleration))
            e_t=np.linalg.norm(actual_t-tensions)/(rp.mass*rp.g+np.linalg.norm(tensions))
            reference_e=cartesian_energy(rp,z)
            e_energy=abs(d['E_junction'][0]-reference_e)/(rp.mass*rp.g*rp.lower_length+abs(reference_e))
            self.assertEqual(dy.shape,(8,))
            self.assertLessEqual(max(e_a,e_t,e_energy),1e-10)
            errors.append([float(e_a),float(e_t),float(e_energy)]); conditions.append(condition); ratios.append(ratio)
        self.assertEqual(len(errors),120)
        self.assertEqual(set(ratios),{.01,.1,1.})
        METRICS['5-B1']={'seed':20260905,'accepted':120,'attempted':attempts,'rejected':rejected,
                         'max_condition':max(conditions),'mass_ratios':sorted(set(ratios)),
                         'max_scaled_errors':np.max(errors,axis=0).tolist(),'threshold':1e-10}

    def test_5_b1_cartesian_mass_and_potential_gradient(self):
        c=config(); rp=CartesianParameters.from_physical(c['physical'])
        q=np.array([.12,.08,-.05]); rates=np.array([.04,.03,-.02])
        M,jj,jb=local_cartesian_mass(rp,q)
        n=np.r_[q[1:3],np.sqrt(1-q[1]**2-q[2]**2)]
        eta=np.r_[rates[1:3],-np.dot(q[1:3],rates[1:3])/n[2]]
        y=np.r_[q[0],rates[0],n,eta]
        c['physical']['initial_state']=y.tolist(); issues,p=validate_junction_config(c); self.assertEqual(issues,[])
        d=junction_derived(p,y)
        kinetic=.5*rp.junction_mass*np.dot(d['v_J'][0],d['v_J'][0])+.5*rp.mass*np.dot(d['v_m'][0],d['v_m'][0])
        mass_error=abs(.5*rates@M@rates-kinetic)/(1+kinetic)
        y_zero=y.copy(); y_zero[1]=0.;y_zero[5:]=0.
        dy=junction_rhs(p,0.,y_zero)
        gradient=finite_difference_potential_gradient(rp,q)
        residual=M@np.array([dy[1],dy[5],dy[6]])+gradient
        gradient_error=np.linalg.norm(residual)/(rp.mass*rp.g*rp.lower_length+np.linalg.norm(gradient))
        self.assertGreater(np.min(np.linalg.eigvalsh(M)),0.)
        self.assertLessEqual(mass_error,1e-10);self.assertLessEqual(gradient_error,1e-10)
        METRICS['5-B1-energy-structure']={'mass_error':float(mass_error),'potential_gradient_error':float(gradient_error),'threshold':1e-10}

    def test_5_b2_independent_frequencies_and_actual_modal_trajectories(self):
        c=config();rp=CartesianParameters.from_physical(c['physical'])
        freq,vectors,M,K=independent_linear_modes(rp)
        anchors=np.array([3.336101839011105,4.043513323831146,22.987397080133864])
        self.assertLessEqual(np.max(np.abs(freq-anchors)/(1+anchors)),1e-10)
        rows=[]
        for mode in range(3):
            mode_rows=[]
            for amplitude in (1e-4,5e-5):
                case=deepcopy(c); y0=modal_state(vectors[:,mode],amplitude)
                T=6*np.pi/anchors[mode]
                case['physical'].update(initial_state=y0.tolist(),T=float(T))
                case['numerics'].update(max_step=.008,output_dt=float(T/600),rtol=1e-11,atol=1e-13)
                result=run_config(case)
                self.assertEqual(result.numerical_status,'SUCCESS_SINGLE_RUN',result.events)
                X=result.state['X_junction']; q=X[:,[0,2,3]]
                observable=q@M@vectors[:,mode]
                t=result.time
                def objective(w):
                    design=np.c_[np.cos(w*t),np.sin(w*t),np.ones(t.size)]
                    fit=np.linalg.lstsq(design,observable,rcond=None)[0]
                    return np.mean((design@fit-observable)**2)
                opt=minimize_scalar(objective,bounds=(anchors[mode]*.999,anchors[mode]*1.001),method='bounded',options={'xatol':1e-12})
                self.assertTrue(opt.success)
                frequency_error=abs(opt.x-anchors[mode])/anchors[mode]
                qref=np.cos(anchors[mode]*t)[:,None]*y0[[0,2,3]]
                trajectory_error=np.max(np.linalg.norm(q-qref,axis=1))/(amplitude+np.max(np.linalg.norm(qref,axis=1)))
                self.assertLessEqual(frequency_error,1e-6)
                self.assertLessEqual(trajectory_error,1e-6)
                mode_rows.append({'amplitude':amplitude,'frequency_rad_s':float(opt.x),'relative_frequency_error':float(frequency_error),'scaled_trajectory_error':float(trajectory_error),'window_s':float(T)})
            rows.append(mode_rows)
        METRICS['5-B2']={'independent_omega':freq.tolist(),'anchors':anchors.tolist(),'modes':rows,'trajectory_threshold':1e-6}

    def test_5_b3_non_coplanar_cartesian_trajectory_four_real_steps(self):
        c=config();c['physical']['initial_state']=state(.06,.04,-.03,.12,-.07,.09).tolist()
        c['physical']['T']=2.;rp=CartesianParameters.from_physical(c['physical'])
        ref=integrate_cartesian(rp,np.array(c['physical']['initial_state']),2.,rtol=3e-13,atol=3e-15,max_step=.001)
        self.assertTrue(ref.success)
        reference_constraint=max(np.max(np.abs(constraint_values(rp,z))) for z in ref.y.T)
        self.assertLessEqual(reference_constraint,1e-10)
        rows=[]
        for step in (.01,.0075,.005,.0025):
            case=deepcopy(c);case['numerics'].update(method='Radau',rtol=1e-5,atol=1e-8,max_step=step,output_dt=.01)
            r=run_config(case);self.assertEqual(r.numerical_status,'SUCCESS_SINGLE_RUN',r.events)
            reference=ref.sol(r.time).T[:,:6]
            error=float(np.max(np.linalg.norm(positions(r)-reference,axis=1))/(rp.lower_length+np.max(np.linalg.norm(reference,axis=1))))
            self.assertLessEqual(error,1e-6)
            d=r.diagnostics
            self.assertLessEqual(d['max_abs_n_norm_error'],1e-8)
            self.assertLessEqual(d['max_abs_n_dot_eta'],1e-8)
            self.assertLessEqual(d['max_relative_energy_drift'],1e-6)
            self.assertLessEqual(d['max_actual_step'],step*(1+1e-12))
            rows.append({'max_step':step,'actual_max_step':d['max_actual_step'],'accepted_steps':d['accepted_steps'],'scaled_position_error':error,'constraint_norm':d['max_abs_n_norm_error'],'constraint_tangent':d['max_abs_n_dot_eta'],'relative_energy_drift':d['max_relative_energy_drift']})
        self.assertTrue(all(rows[i]['actual_max_step'] > 1.15*rows[i+1]['actual_max_step'] for i in range(3)))
        observed=[np.log(rows[i]['scaled_position_error']/rows[i+1]['scaled_position_error'])/np.log(rows[i]['actual_max_step']/rows[i+1]['actual_max_step']) for i in range(3)]
        self.assertLess(rows[-1]['scaled_position_error'],rows[0]['scaled_position_error'])
        METRICS['5-B3-trajectory']={'reference_max_constraint_m':float(reference_constraint),'reference_steps':ref.t.size-1,'levels':rows,'observed_orders':observed,'design_order':'Radau IIA fifth order accepted endpoints; dense trajectory order can differ'}

    def test_5_b3_three_first_loss_events_against_cartesian_reference(self):
        upper_a=first_upper_a_loss_config(); upper_a['physical']['obstacles']=[]
        upper_b=deepcopy(upper_a);upper_b['physical']['initial_state'][2]*=-1;upper_b['physical']['initial_state'][5]*=-1
        lower=config();lower['physical'].update(junction_mass=10.,initial_state=[0.,0.,0.,0.,1.,0.,7.,0.],T=1.)
        lower['numerics'].update(max_step=.005,output_dt=.01)
        rows=[]
        for case,expected in [(upper_a,'T_A_ZERO'),(upper_b,'T_B_ZERO'),(lower,'T_LOWER_ZERO')]:
            rp=CartesianParameters.from_physical(case['physical'])
            ref=integrate_cartesian(rp,np.array(case['physical']['initial_state']),case['physical']['T'],max_step=.0005,events=tension_events(rp))
            self.assertTrue(ref.success)
            times=[x[0] for x in ref.t_events if len(x)];self.assertTrue(times)
            reference_time=min(times)
            r=run_config(case);self.assertEqual(r.numerical_status,'SUCCESS_EVENT',r.events)
            self.assertIn(expected,r.events[0]['triggers'])
            self.assertLessEqual(abs(r.tau-reference_time),1e-7)
            self.assertTrue(np.all(r.time<r.tau))
            for name in ('T_A','T_B','T_lower'): self.assertGreater(np.min(r.derived[name]),0.)
            rows.append({'first_trigger':expected,'time':r.tau,'reference_time':float(reference_time),'absolute_time_error':float(abs(r.tau-reference_time)),'root_bracket':r.events[0]['root_bracket'],'T_star_s':1.})
        METRICS['5-B3-tensions']=rows

    def test_5_b3_initial_loss_contact_and_spherical_pole(self):
        c=config();c['physical']['initial_state']=[0.,0.,0.,0.,-1.,0.,0.,0.]
        invalid=run_config(c);self.assertEqual(invalid.numerical_status,'INPUT_REJECTED');self.assertEqual(invalid.time.size,0)
        c=config();c['physical'].update(junction_mass=100.,initial_state=[0.,0.,float(np.sqrt(1-1e-16)),0.,1e-8,0.,1.,0.],T=.02)
        c['numerics'].update(max_step=.001,output_dt=.002)
        polar=run_config(c);self.assertEqual(polar.numerical_status,'SUCCESS_SINGLE_RUN',polar.events)
        c=config();c['physical'].update(initial_state=state(0.,.12,0.,0.,-.7,0.).tolist(),T=.1)
        rp=CartesianParameters.from_physical(c['physical'])
        ref=integrate_cartesian(rp,np.array(c['physical']['initial_state']),.1,max_step=.0005)
        crossing_time=.04;plane_x=float(ref.sol(crossing_time)[3])
        c['physical']['obstacles']=[{'id':'screen','kind':'plane','target':'bob','point':[plane_x,0.,0.],'normal':[1.,0.,0.],'allowed_side':1}]
        r=run_config(c);self.assertEqual(r.numerical_status,'SUCCESS_EVENT',r.events)
        self.assertIn('CONTACT_screen',r.events[0]['triggers']);self.assertLessEqual(abs(r.tau-crossing_time),1e-7)
        METRICS['5-B3-other']={'initial_loss':'INPUT_REJECTED','near_pole_status':polar.numerical_status,'contact_time':r.tau,'contact_reference_time':crossing_time,'contact_error':abs(r.tau-crossing_time)}

    def test_5_b3_grazing_contact_has_a_conservative_valid_interval(self):
        c=config(); c['physical'].update(initial_state=state(0.,.12,0.).tolist(),T=1.2)
        rp=CartesianParameters.from_physical(c['physical'])
        ref=integrate_cartesian(rp,np.array(c['physical']['initial_state']),1.2,max_step=.0005)
        touch=brentq(lambda t: ref.sol(t)[9],.5,1.1,xtol=1e-13)
        wall_x=-rp.lower_length*np.sin(.12)
        c['physical']['obstacles']=[{'id':'tangent','kind':'plane','target':'bob','point':[float(wall_x),0.,0.],'normal':[1.,0.,0.],'allowed_side':1}]
        r=run_config(c)
        self.assertIn(r.numerical_status,('SUCCESS_EVENT','EVENT_UNRESOLVED'))
        self.assertLessEqual(r.tau,touch+1e-7)
        self.assertTrue(np.all(r.time<=r.tau))
        self.assertGreaterEqual(np.min(r.state['r_m'][:,0]-wall_x),-1e-10)
        METRICS['5-B3-grazing']={'status':r.numerical_status,'last_valid_time':r.tau,'independent_touch_time':touch,'reason':'grazing event uses conservative interval rather than simple-root time precision'}

    def test_5_a_illegal_physical_inputs_are_rejected(self):
        mutations=[lambda c:c['physical'].update(junction_mass=0.),
                   lambda c:c['physical'].update(junction_mass=-1.),
                   lambda c:c['physical'].update(s_A=.01,s_B=.01),
                   lambda c:c['physical']['initial_state'].__setitem__(4,2.),
                   lambda c:c['physical']['initial_state'].__setitem__(7,.2),
                   lambda c:c['physical'].update(initial_state=[0.,0.,1.,0.,0.,0.,0.,0.])]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                c=config();mutate(c);r=run_config(c)
                self.assertEqual(r.numerical_status,'INPUT_REJECTED')
                self.assertEqual(r.time.size,0)
                self.assertTrue(r.events[0]['failures'])

    def test_5_b4_prepared_limit_and_unprepared_fast_mode_counterexample(self):
        rows=[]
        for ratio in (.1,.01,.001):
            c=config();c['physical']['junction_mass']=ratio
            rp=CartesianParameters.from_physical(c['physical']);omega,vectors,M,K=independent_linear_modes(rp)
            slow=modal_state(vectors[:,0],.001)
            c['physical'].update(initial_state=slow.tolist(),T=2.)
            c['numerics'].update(max_step=float(min(.008,.2/omega[-1])),output_dt=.005,rtol=1e-11,atol=1e-13)
            r=run_config(c);self.assertEqual(r.numerical_status,'SUCCESS_SINGLE_RUN',r.events)
            torus=load_json(PROJECT/'configs/torus_example.json')
            torus['physical'].update(A=c['physical']['A'],B=c['physical']['B'],s_A=rp.s_A,s_B=rp.s_B,lower_length=rp.lower_length,mass=rp.mass,g=rp.g,initial_state=[0.,float(slow[0]),0.,0.],T=2.)
            torus['observation']=None;torus['numerics'].update(output_dt=.005,max_step=.008)
            tr=run_config(torus);self.assertEqual(tr.numerical_status,'SUCCESS_SINGLE_RUN')
            difference=float(np.max(np.linalg.norm(r.state['r_m']-tr.derived['r_m'],axis=1)))
            fast=modal_state(vectors[:,-1],.001)
            unprepared=deepcopy(c);unprepared['physical']['initial_state']=fast.tolist();unprepared['physical']['T']=float(4*np.pi/omega[-1]);unprepared['numerics']['output_dt']=float(unprepared['physical']['T']/160)
            ur=run_config(unprepared);self.assertEqual(ur.numerical_status,'SUCCESS_SINGLE_RUN',ur.events)
            speed=float(np.max(np.linalg.norm(ur.state['v_J'],axis=1)))
            rows.append({'mass_ratio':ratio,'omega_slow':float(omega[0]),'omega_fast':float(omega[-1]),'slow_frequency_error_to_torus':float(omega[0]/np.sqrt(rp.g/(rp.h+rp.lower_length))-1),'prepared_bob_max_error_m':difference,'prepared_fast_position_amplitude':float(abs(vectors[:,-1]@M@slow[[0,2,3]])),'unprepared_fast_junction_angle_amplitude':float(abs(fast[0])),'unprepared_max_junction_speed_m_s':speed})
        self.assertTrue(all(rows[i+1]['prepared_bob_max_error_m']<rows[i]['prepared_bob_max_error_m'] for i in range(2)))
        self.assertTrue(all(rows[i+1]['slow_frequency_error_to_torus']<rows[i]['slow_frequency_error_to_torus'] for i in range(2)))
        self.assertGreater(rows[-1]['unprepared_max_junction_speed_m_s'],2*rows[0]['unprepared_max_junction_speed_m_s'])
        METRICS['5-B4']=rows

if __name__=='__main__': unittest.main()
