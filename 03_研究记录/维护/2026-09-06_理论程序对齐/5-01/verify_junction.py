#!/usr/bin/env python3
"""Run production J3 acceptance and preserve metrics plus the original log."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[4]
PROJECT=ROOT/'02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
sys.path[:0]=[str(PROJECT),str(PROJECT/'tests')]
from y_pendulum_forward.contracts import source_tree_sha256,runtime_versions,json_safe
import test_junction
import test_junction_guards
import test_junction_integration

output=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('acceptance')
output.mkdir(parents=True,exist_ok=False)
source=source_tree_sha256()
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in [test_junction,test_junction_guards,test_junction_integration])
with (output/'validation.log').open('w') as handle:
    result=unittest.TextTestRunner(stream=handle,verbosity=2).run(suite)
report={'status':'PASS' if result.wasSuccessful() and source_tree_sha256()==source else 'FAIL','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_tree_sha256':source,'source_tree_sha256_at_end':source_tree_sha256(),'runtime':runtime_versions(),'command':[sys.executable,*sys.argv],'cwd':str(Path.cwd()),'reference':'tests/junction_reference.py; independent Cartesian Newton/KKT; synthetic inputs only','test_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [PROJECT/'tests'/name for name in ['junction_reference.py','test_junction.py','test_junction_guards.py','test_junction_integration.py']]},'metrics':test_junction.METRICS}
(output/'summary.json').write_text(json.dumps(json_safe(report),ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['status','tests_run','failures','errors','skipped']},ensure_ascii=False))
sys.exit(0 if report['status']=='PASS' else 1)
