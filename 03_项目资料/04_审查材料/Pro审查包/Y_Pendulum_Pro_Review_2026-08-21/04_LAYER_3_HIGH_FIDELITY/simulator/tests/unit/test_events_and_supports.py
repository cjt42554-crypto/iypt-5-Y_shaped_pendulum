from pathlib import Path
import numpy as np
from ypendulum.analysis import detect_tension_events
from ypendulum.config.models import SupportConfig
from ypendulum.geometry import SupportMotion

def test_serial_branch_loses_transmission_on_one_slack_element():
    t=np.array([0.,.1,.2,.3]); T=np.array([[1.,1.],[1.,0.],[1.,0.],[1.,1.]])
    kinds=[e["type"] for e in detect_tension_events(t,T,T>0,{"upper_A":slice(0,2)},minimum_duration=0.)]
    assert "cable_slack" in kinds and "cable_retension" in kinds and "cable_fully_unloaded" not in kinds

def test_sinusoidal_support_state():
    cfg=SupportConfig.model_validate({"type":"prescribed","position":{"value":[1,2,3],"unit":"m"},"motion":{"model":"sinusoidal","amplitude":{"value":[.1,0,0],"unit":"m"},"frequency":{"value":2.,"unit":"Hz"},"phase":{"value":0.,"unit":"rad"}}})
    p,v,a=SupportMotion.from_config(cfg).state(0.); assert np.allclose(p,[1,2,3]); assert np.isclose(v[0],.1*4*np.pi); assert np.isclose(a[0],0)

def test_table_support_motion(tmp_path:Path):
    table=tmp_path/'motion.csv'; table.write_text('time,x,y,z\n0,0,0,0\n0.5,0.01,0,0\n1.0,0,0,0\n')
    cfg=SupportConfig.model_validate({"type":"prescribed","position":{"value":[0,0,0],"unit":"m"},"motion":{"model":"table","table_file":str(table)}})
    p,v,a=SupportMotion.from_config(cfg).state(.5); assert np.isclose(p[0],.01); assert np.all(np.isfinite(v)) and np.all(np.isfinite(a))
