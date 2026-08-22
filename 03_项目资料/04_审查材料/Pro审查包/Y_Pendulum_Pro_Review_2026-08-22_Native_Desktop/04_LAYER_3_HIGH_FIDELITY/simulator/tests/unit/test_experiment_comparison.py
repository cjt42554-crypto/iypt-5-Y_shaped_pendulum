import numpy as np
from ypendulum.analysis import AlignmentOptions,align_prediction_to_experiment

def traj(t): return np.column_stack([np.sin(2*np.pi*.73*t)+.013*t**2,.6*np.cos(2*np.pi*.47*t+.2)+.01*t,.08*np.sin(2*np.pi*1.1*t)])

def test_direct_forward_comparison_is_exact():
    t=np.linspace(0,4,801); v=traj(t); r=align_prediction_to_experiment(t,v,t,v); assert r.report['nuisance_parameters_fitted']==[]; assert r.report['normalized_rms_error']<1e-14

def test_explicit_nuisance_alignment_recovers_known_transform():
    tp=np.linspace(0,5,2501); te=np.linspace(.3,4.5,841); shift=.037; raw=traj(te+shift); angle=.12; c,s=np.cos(angle),np.sin(angle); R=np.array([[c,-s,0],[s,c,0],[0,0,1]]); tr=np.array([.018,-.011,.004]); obs=raw@R.T+tr
    r=align_prediction_to_experiment(tp,traj(tp),te,obs,options=AlignmentOptions(estimate_time_shift=True,maximum_time_shift_s=.08,estimate_translation=True,estimate_planar_rotation=True))
    assert abs(r.report['time_shift_s']-shift)<2e-5; assert abs(r.report['planar_rotation_rad']-angle)<2e-5; assert np.allclose(r.report['translation'],tr,atol=2e-5); assert r.report['normalized_rms_error']<2e-5

def test_short_overlap_is_rejected():
    t=np.linspace(0,1,101); v=traj(t)
    try: align_prediction_to_experiment(t,v,np.linspace(2,3,101),v,options=AlignmentOptions(minimum_overlap_samples=12))
    except ValueError as e: assert 'overlapping' in str(e)
    else: raise AssertionError('Non-overlapping observations accepted')
