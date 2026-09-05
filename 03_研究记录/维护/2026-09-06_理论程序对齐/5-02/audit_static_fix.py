"""Compare final static preparation bitwise with frozen wave initial arrays."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[4]
PROJECT=ROOT/'02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
sys.path.insert(0,str(PROJECT))
from y_pendulum_forward.cable import parse_cable_physical,CableFEM
from y_pendulum_forward.contracts import source_tree_sha256
output=Path(sys.argv[1]);rows=[]
if output.exists():raise FileExistsError(output)
for path in sorted(Path(__file__).with_name('acceptance-01').glob('n*/config.snapshot.json')):
    config=json.loads(path.read_text());issues,physical=parse_cable_physical(config);assert not issues
    model=CableFEM(physical,config['numerics']);old=np.load(path.with_name('trajectory.npz'))
    rows.append({'case':path.parent.name,'exact_initial_positions_equal':bool(np.array_equal(model.initial_positions,old['state__node_positions'][0])),'max_position_difference_m':float(np.max(np.abs(model.initial_positions-old['state__node_positions'][0]))),'issues':[item.as_dict() for item in model.numerical_issues],'selected_iterations':model.preparation_diagnostics['selected_iterations']})
report={'status':'PASS' if len(rows)==5 and all(x['exact_initial_positions_equal'] and not x['issues'] for x in rows) else 'FAIL','source_tree_sha256':source_tree_sha256(),'rows':rows,'command':[sys.executable,*sys.argv],'scope':'Only the static minimizer energy stopping condition changed; dynamics and integration remain unchanged. This audit checks preparation, not a new wave integration.'}
output.write_text(json.dumps(report,indent=2)+'\n');print(report['status']);sys.exit(int(report['status']!='PASS'))
