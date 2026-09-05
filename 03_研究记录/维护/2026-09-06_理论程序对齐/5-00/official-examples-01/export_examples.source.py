"""Run all three committed example configurations through the unchanged CLI."""
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[4]
PROJECT=ROOT/'02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
sys.path.insert(0,str(PROJECT))
from y_pendulum_forward.contracts import source_tree_sha256,runtime_versions
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=False)
rows=[];source=source_tree_sha256()
for name in ('cable','torus','junction'):
    config=PROJECT/'configs'/f'{name}_example.json';destination=output/name
    command=[sys.executable,str(PROJECT/'run.py'),'run',str(config),'--output',str(destination),'--no-plots']
    start=time.perf_counter()
    with (output/f'{name}.log').open('w') as handle:
        completed=subprocess.run(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
    row={'example':name,'command':command,'exit_code':completed.returncode,'elapsed_s':time.perf_counter()-start}
    if completed.returncode==0:
        result=json.loads((destination/'result.json').read_text());data=dict(np.load(destination/'trajectory.npz',allow_pickle=False))
        row.update(model_id=result['model_id'],numerical_status=result['numerical_status'],samples=int(len(data['time'])),observation_valid=bool(np.all(data['observations__valid_mask'])),artifact=name)
    rows.append(row);print(row,flush=True)
report={'status':'PASS' if all(r['exit_code']==0 and r.get('observation_valid') for r in rows) and source_tree_sha256()==source else 'FAIL','source_tree_sha256':source,'source_tree_sha256_at_end':source_tree_sha256(),'runtime':runtime_versions(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'rows':rows}
(output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');sys.exit(int(report['status']!='PASS'))
