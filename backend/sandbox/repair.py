from pathlib import Path
from core.models import RepairAction

def candidates(spec,validation):
 code=validation.get('diagnosis',{}).get('code','unknown');mapping={'missing_file':('RECALCULATE_ENTRYPOINT','Recalculate executable/output path from repository evidence.',0.88),'missing_module':('RECONCILE_DEPENDENCIES','Reconcile production dependency installation with the resolved dependency graph.',0.91),'lockfile':('PIN_PACKAGE_MANAGER','Use the detected lockfile and package-manager family.',0.94),'permission':('FIX_RUNTIME_OWNERSHIP','Regenerate runtime stage with non-root ownership and executable permissions.',0.96),'health':('RECALCULATE_HEALTH','Recalculate bind address, port and health path from evidence.',0.83),'memory':('INCREASE_BUILD_LIMIT','Increase only bounded worker memory.',0.72),'network':('CONTROLLED_BUILD_EGRESS','Allow egress only during the dependency build phase.',0.90)}
 if code in mapping:
  c,d,conf=mapping[code];return [RepairAction(c,d,conf,True,{}).__dict__]
 return []

def apply(spec,validation,repo):
 code=validation.get('diagnosis',{}).get('code')
 if code=='missing_file' and spec.runtime.get('name')=='Node.js':
  cs=[f for f in repo.files if Path(f).name in {'server.js','server.ts','index.js','index.ts','main.js','main.ts'}]
  if cs:spec.processes[0]['start_command']=f'node {cs[0]}';return {'changed':True,'action':'RECALCULATE_ENTRYPOINT','details':cs[0]}
 if code=='health':spec.network['health_endpoint']='/';spec.network['smoke_paths']=['/','/health','/healthz'];return {'changed':True,'action':'RECALCULATE_HEALTH'}
 if code=='permission':spec.policy['force_non_root']=True;return {'changed':True,'action':'FIX_RUNTIME_OWNERSHIP'}
 return {'changed':False,'action':'NONE'}
