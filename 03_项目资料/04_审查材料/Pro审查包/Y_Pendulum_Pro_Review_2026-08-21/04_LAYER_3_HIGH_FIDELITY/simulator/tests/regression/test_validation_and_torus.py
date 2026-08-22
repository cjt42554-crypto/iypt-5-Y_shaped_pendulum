import numpy as np
from ypendulum.config import load_config
from ypendulum.models.torus import TorusParameters, simulate_torus
from ypendulum.validation_suite import run_validation_suite

def test_fast_validation_suite():
    r=run_validation_suite(fast=True,output_directory=None); assert r['passed'] and len(r['cases'])>=9

def test_torus_reference_energy_and_tension():
    cfg=load_config('configs/examples/ideal_3to2.yaml'); TorusParameters.from_config(cfg); result=simulate_torus(cfg)
    rel=np.max(np.abs(result.energy-result.energy[0]))/max(abs(float(result.energy[0])),1e-12); assert rel<1e-8; assert np.all(result.tensions>=-1e-12)
