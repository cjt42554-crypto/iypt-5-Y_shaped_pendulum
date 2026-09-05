"""Bounded release regression; large spatial studies have a separate runner."""
from copy import deepcopy
import unittest
import json
from pathlib import Path
import numpy as np
from scipy.optimize import brentq
from y_pendulum_forward.runner import run_config
from y_pendulum_forward.providers import build_holding_force_release
from release_reference import wave_config, modal_release

METRICS={}


class ReleaseProtocolTests(unittest.TestCase):
    def test_held_equilibrium_does_not_stop_on_energy_change_before_force_tolerance(self):
        path=Path(__file__).with_name('fixtures')/'held_equilibrium_energy_cutoff.json'
        config=json.loads(path.read_text())
        result=run_config(config)
        self.assertEqual(result.numerical_status,'SUCCESS_SINGLE_RUN',result.events)
        preparation=result.diagnostics['preparation']
        self.assertLessEqual(preparation['selected_gradient_inf'],2e-7)
        self.assertGreaterEqual(preparation['accepted_candidate_count'],1)
        for name,key in [('junction','r_J'),('bob','r_m')]:
            np.testing.assert_allclose(result.state[key][0],config['initial_state']['hold']['fixed_nodes'][name],atol=1e-14,rtol=0)

    def test_three_durations_match_independent_linear_modal_convolution(self):
        rows=[]
        for duration in (.002,.006,.012):
            c=wave_config(8,.0005,start=.0027,duration=duration,final_time=.03,output_dt=.003)
            r=run_config(c);self.assertEqual(r.numerical_status,'SUCCESS_SINGLE_RUN',r.events)
            ids=r.metadata['branch_nodes']['lower']
            q=r.state['node_positions'][:,ids,0]-r.state['node_positions'][0,ids,0]
            v=r.state['node_velocities'][:,ids,0]
            qr,vr=modal_release(8,r.time,.0027,duration)
            qr2,vr2=modal_release(8,r.time,.0027,duration,quadrature=256)
            q_error=float(np.max(np.abs(q-qr))/1e-4)
            v_error=float(np.max(np.abs(v-vr))/.01)
            quadrature_error=float(max(np.max(np.abs(qr-qr2))/1e-4,np.max(np.abs(vr-vr2))/.01))
            self.assertLess(q_error,1e-6);self.assertLess(v_error,1e-6);self.assertLess(quadrature_error,1e-10)
            work=r.diagnostics['power_integral_hold'];after=r.time>=.0027+duration
            self.assertTrue(np.all(r.derived['P_hold'][after]==0.))
            self.assertLessEqual(np.ptp(work[after]),1e-18)
            rows.append({'duration':duration,'scaled_position_error':q_error,'scaled_velocity_error':v_error,'reference_quadrature_error':quadrature_error,'holding_work_J':float(work[-1]),'after_release_work_range_J':float(np.ptp(work[after]))})
        METRICS['5-C2-modal']=rows

    def test_output_grid_does_not_change_release_work_across_breakpoints(self):
        c=wave_config(8,.0005,start=.0027,duration=.0083,final_time=.03,output_dt=.006)
        fine=deepcopy(c);fine['numerics']['output_dt']=.003
        a,b=run_config(c),run_config(fine)
        self.assertEqual(a.numerical_status,'SUCCESS_SINGLE_RUN');self.assertEqual(b.numerical_status,'SUCCESS_SINGLE_RUN')
        work_a=a.diagnostics['power_integral_hold'];work_b=b.diagnostics['power_integral_hold'][::2]
        error=float(np.max(np.abs(work_a-work_b)))
        self.assertLessEqual(error,1e-6*1e-6)
        self.assertEqual(a.metadata['physical_input_sha256'],b.metadata['physical_input_sha256'])
        METRICS['5-C2-output']={'absolute_work_difference_J':error,'exchange_scale_J':1e-6,'relative_threshold':1e-6,'start_s':.0027,'end_s':.011,'output_dt_s':[.006,.003]}

    def test_explicit_instantaneous_release_preserves_legacy_input(self):
        c=wave_config(8,.0005,final_time=.01,output_dt=.002)
        old=deepcopy(c);del old['inputs']['hold_release']
        a,b=run_config(c),run_config(old)
        self.assertEqual(a.numerical_status,'SUCCESS_SINGLE_RUN');self.assertEqual(b.numerical_status,'SUCCESS_SINGLE_RUN')
        np.testing.assert_array_equal(a.state['node_positions'],b.state['node_positions'])
        np.testing.assert_array_equal(a.state['node_velocities'],b.state['node_velocities'])
        self.assertNotIn('P_hold',b.derived)
        self.assertNotIn('power_integral_hold',b.diagnostics)
        self.assertTrue(np.all(a.diagnostics['power_integral_hold']==0.))

    def test_zero_holding_force_equilibrium_is_a_stationary_limit(self):
        c=wave_config(1,.001,start=.0027,duration=.0083,final_time=.03,output_dt=.003)
        p=c['physical'];p.update(g=9.81,junction_mass=.1,bob_mass=.02)
        length=float(np.hypot(.2,.3));mu=.01;EA=100.
        for name,L in [('A',length),('B',length),('lower',.6)]:
            p['branches'][name].update(L0=L,EA=EA)
        lower_tension=9.81*(.02+mu*.6/2)
        needed=lower_tension+9.81*(.1+mu*length+mu*.6/2)
        h=brentq(lambda h:2*EA*(np.hypot(.2,h)/length-1)*h/np.hypot(.2,h)-needed,.3,.6,xtol=1e-14)
        ell=.6*(1+lower_tension/EA)
        c['inputs']['support_A']['value']=[-.2,0.,0.];c['inputs']['support_B']['value']=[.2,0.,0.]
        c['initial_state']['hold']['fixed_nodes']={'bob':[0.,0.,h+ell]}
        c['initial_state']['seed']={'r_J':[0.,0.,h],'r_m':[0.,0.,h+ell]}
        c['numerics'].update(static_gradient_tolerance=1e-10,static_energy_tolerance=1e-12)
        r=run_config(c);self.assertEqual(r.numerical_status,'SUCCESS_SINGLE_RUN',r.events)
        force=float(np.max(np.linalg.norm(r.derived['F_hold_b'],axis=1)))
        displacement=float(np.max(np.linalg.norm(r.state['r_m']-r.state['r_m'][0],axis=1)))
        work=float(np.max(np.abs(r.diagnostics['power_integral_hold'])))
        self.assertLessEqual(force,1e-7);self.assertLessEqual(displacement,1e-8);self.assertLessEqual(work,1e-14)
        METRICS['5-C2-zero']={'holding_force_N':force,'maximum_bob_displacement_m':displacement,'holding_work_abs_J':work,'absolute_bounds':[1e-7,1e-8,1e-14],'basis':'independent discrete gravity/axial static balance; floating-point preparation tolerance'}

    def test_invalid_protocols_are_rejected(self):
        for updates in ({'duration':-.1},{'history':'mystery'},{'source':'fit_to_future'},{'duration':0.,'history':'smoothstep_c1'}):
            with self.subTest(updates=updates):
                c=wave_config(1);c['inputs']['hold_release'].update(updates)
                r=run_config(c);self.assertEqual(r.numerical_status,'INPUT_REJECTED');self.assertEqual(r.time.size,0)

if __name__=='__main__': unittest.main()
