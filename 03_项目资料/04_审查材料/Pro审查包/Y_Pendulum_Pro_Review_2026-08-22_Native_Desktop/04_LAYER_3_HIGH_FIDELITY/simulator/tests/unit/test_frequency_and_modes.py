import numpy as np
from ypendulum import analyze_linear_modes
from ypendulum.analysis import estimate_dominant_frequency

def test_continuous_frequency_refinement_avoids_fft_bin_quantisation():
    t=np.linspace(0,8,1601); f=.5874321; x=.03*np.cos(2*np.pi*f*t+.4)+.001*t; e=estimate_dominant_frequency(t,x); assert e.reliable; assert abs(e.frequency_hz-f)<2e-6; assert e.fit_r2>.999999

def test_frequency_estimator_refuses_fraction_of_cycle():
    t=np.linspace(0,.2,101); e=estimate_dominant_frequency(t,np.sin(2*np.pi*.6*t)); assert not e.reliable; assert 'cycles_observed' in e.reason or 'frequency_at_search_boundary' in e.reason

def test_h1_linear_modes_are_bob_dominated_and_ordered():
    m=analyze_linear_modes('configs/examples/full_quick_3to2.yaml',count=2)['modes']; assert len(m)==2; assert m[0]['frequency_hz']<m[1]['frequency_hz']; assert m[0]['bob_kinetic_participation']>.9 and m[1]['bob_kinetic_participation']>.9; assert {x['descriptive_label'] for x in m}=={'transverse_slow','support_axis_fast'}
