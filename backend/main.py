from fastapi import FastAPI,HTTPException,UploadFile,File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,StreamingResponse
from pydantic import BaseModel,HttpUrl,Field
from pathlib import Path
import tempfile,subprocess,shutil,zipfile,os,uuid,json,time,queue,threading
from core.scanner import Repository
from core.engine import Analyzer
from core.ast import ASTAnalyzer
from core.deps import graph
from core.migrations import analyze as migration_analyze
from core.models import DeploymentSpec
from core.validate import static_dockerfile
from generators.docker import dockerfile,compose
from generators.cloud import terraform,kubernetes
from security.audit import audit,sbom_plan,vulnerability_plan,policy as security_policy
from pricing.engine import PricingEngine
from sandbox.runner import Sandbox
from sandbox.repair import candidates as repair_candidates,apply as repair_apply
from sandbox.policy import DEFAULT_POLICY,validate_policy
from core.policy import deployment_gate
APP_ROOT=Path(__file__).resolve().parents[1];FRONTEND=APP_ROOT/'frontend'
app=FastAPI(title='AutoDeploy Stack Intelligence',version='1.0.0',description='Deterministic repository-to-deployment analysis and bounded validation/repair engine.')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
class AnalyzeRequest(BaseModel):
 repo_url:HttpUrl
 run_validation:bool=False
 max_repair_attempts:int=Field(default=3,ge=1,le=5)
 providers:list[str]=Field(default_factory=lambda:['aws','gcp','azure'])
 run_security_tools:bool=False
class ValidateRequest(AnalyzeRequest): run_validation:bool=True
def emit(events,phase,message,status='running',**extra):
 e={'id':str(uuid.uuid4()),'time':time.time(),'phase':phase,'message':message,'status':status};e.update(extra);events.append(e);return e
def clone(url):
 tmp=tempfile.mkdtemp(prefix='autodeploy-repo-');target=Path(tmp)/'repo';p=subprocess.run(['git','clone','--depth','1','--no-tags','--filter=blob:none',str(url),str(target)],capture_output=True,text=True,timeout=180)
 if p.returncode:shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(400,'Git clone failed: '+p.stderr[-3000:])
 return tmp,target
def extract_zip(data):
 tmp=tempfile.mkdtemp(prefix='autodeploy-zip-');z=Path(tmp)/'upload.zip';z.write_bytes(data);root=Path(tmp)/'repo';root.mkdir()
 try:
  with zipfile.ZipFile(z) as a:
   for i in a.infolist():
    t=(root/i.filename).resolve()
    if not str(t).startswith(str(root.resolve())+os.sep):raise HTTPException(400,'Unsafe ZIP path detected.')
   a.extractall(root)
 except zipfile.BadZipFile:shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(400,'Invalid ZIP archive.')
 children=[p for p in root.iterdir() if p.is_dir()]
 if len(children)==1 and not (root/'package.json').exists() and not (root/'pyproject.toml').exists():root=children[0]
 return tmp,root
def analyze_root(root,providers,events=None):
 events=events if events is not None else [];emit(events,'acquisition','Repository acquired and workspace created.','done')
 repo=Repository(root);emit(events,'inventory',f'Indexed {len(repo.files):,} files ({repo.size_bytes():,} bytes of source/config data).','done',file_count=len(repo.files))
 analyzer=Analyzer(repo);emit(events,'identification','Running deterministic stack identification from manifests, lockfiles, source markers and configuration…');spec,evidence,result=analyzer.analyze()
 emit(events,'languages',f"Detected primary language: {result['summary']['primary_language']}",'done',data=result['languages'])
 emit(events,'runtime',f"Resolved runtime: {result['summary']['runtime']} {result['summary']['runtime_version']}",'done')
 emit(events,'frameworks',f"Framework candidates: {', '.join(x['name'] for x in result['frameworks']) or 'none'}",'done',data=result['frameworks'])
 emit(events,'package_managers',f"Package managers: {', '.join(x['name'] for x in spec.package_managers) or 'none'}",'done',data=spec.package_managers)
 deep=result.get('deep_analysis',{})
 emit(events,'deep_analysis',f"Deep deployment analysis: {len(deep.get('checks',[]))} checks, {len(deep.get('warnings',[]))} warnings, {len(deep.get('blockers',[]))} blockers.",'done' if deep.get('status')=='ready' else 'warning',data=deep)
 emit(events,'entrypoints',f"Build: {result['summary']['build_command']} · Start: {result['summary']['start_command']} · Port: {result['summary']['port']}",'done')
 emit(events,'services',f"Detected services: {', '.join(result['summary']['services']) or 'none'}",'done',data=spec.services)
 emit(events,'environment',f"Collected {len(result['summary']['environment_variables'])} environment-variable signals.",'done')
 emit(events,'infrastructure',f"Found {len(spec.infrastructure.get('files',[]))} infrastructure/config files.",'done',data=spec.infrastructure)
 emit(events,'ci_cd',f"Found {len(spec.ci_cd.get('workflows',[]))} CI/CD workflow definitions.",'done')
 emit(events,'dependencies','Building dependency graph from manifests and lockfiles…');spec.dependencies=graph(repo);emit(events,'dependencies',f"Dependency graph: {spec.dependencies.get('direct_count',0)} direct, {spec.dependencies.get('resolved_count',0)} resolved.",'done',data=spec.dependencies)
 emit(events,'ast','Analyzing source imports and syntax structures across detected languages…');ast=ASTAnalyzer(repo).analyze();emit(events,'ast','AST/source analysis completed.','done',data=ast)
 emit(events,'migrations','Checking migration frameworks and destructive database operations…');spec.migrations=migration_analyze(repo);mm='Manual approval required.' if spec.migrations.get('requires_manual_approval') else 'No destructive migration requiring approval detected.';emit(events,'migrations',mm,'warning' if spec.migrations.get('requires_manual_approval') else 'done',data=spec.migrations)
 emit(events,'security','Running repository security policy checks…');findings=audit(repo);spec.security={'findings':[x.__dict__ for x in findings]};emit(events,'security',f'Security policy found {len(findings)} finding(s).','warning' if any(x.severity in {'critical','high'} for x in findings) else 'done',data=spec.security)
 emit(events,'artifacts','Synthesizing deployment artifacts from the Deployment IR…');files={'Dockerfile':dockerfile(spec),'compose.yaml':compose(spec),'.dockerignore':'.git\n.github\n.env\n.env.*\nnode_modules\n__pycache__\n*.pyc\n.venv\ncoverage\n*.log\n.gitignore'};files['k8s.yaml']=kubernetes(spec)
 for p in providers:
  if p in {'aws','gcp','azure'}:files[f'terraform-{p}.tf']=terraform(spec,p)
 emit(events,'docker','Dockerfile generated from detected runtime, framework, build, adapter and entrypoint evidence.','done');emit(events,'compose','docker-compose configuration generated from detected application roles and services.','done')
 emit(events,'validation','Running deterministic Dockerfile validation…');validation=static_dockerfile(files['Dockerfile']);emit(events,'validation','Dockerfile static validation passed.' if validation['valid'] else 'Dockerfile static validation found blocking issues.','done' if validation['valid'] else 'warning',data=validation)
 emit(events,'pricing','Calculating deterministic cloud planning estimates…');pricing={p:PricingEngine().estimate(spec,p) for p in providers if p in {'aws','gcp','azure'}};emit(events,'pricing','Cloud planning estimates calculated.','done',data=pricing)
 spec.cloud={'providers':providers,'artifacts':list(files.keys())};spec.policy={'confidence':min(result['summary']['confidence'],deep.get('confidence',0) or 0),'requires_manual_approval':spec.migrations.get('requires_manual_approval',False),'auto_deploy_eligible':result['summary']['confidence']>=80 and deep.get('status')=='ready' and not spec.migrations.get('requires_manual_approval',False) and validation['valid'] and not any(x['severity'] in {'critical','high'} for x in spec.security['findings'])}
 result.update({'sandbox_policy':validate_policy(DEFAULT_POLICY),'deployment_ir':spec.to_dict(),'generated_files':files,'ast':ast,'dependency_graph':spec.dependencies,'migrations':spec.migrations,'security':{'findings':[x.__dict__ for x in findings],'sbom':sbom_plan(repo,result['summary']['package_manager']),'vulnerability_scan':vulnerability_plan(),'policy':security_policy(findings)},'static_validation':validation,'cloud_cost_estimates':pricing,'analysis_id':str(uuid.uuid4()),'repository':{'path_count':len(repo.files),'size_bytes':repo.size_bytes(),'hash':repo.hash()}});emit(events,'complete','Repository analysis complete.','done',data={'analysis_id':result['analysis_id'],'confidence':result['summary']['confidence'],'deep_analysis':deep.get('status')});return result,repo,spec
def autonomous_validate(root,result,spec,max_attempts,run_security_tools=False,events=None):
 events=events if events is not None else [];sb=Sandbox(root);attempts=[];ledger=[];current=dockerfile(spec)
 try:
  for i in range(min(max_attempts,DEFAULT_POLICY.max_repair_attempts)):
   emit(events,'sandbox',f'Build attempt {i+1}/{max_attempts}: creating ephemeral build/runtime environment…');Path(root,'Dockerfile').write_text(current);outcome=sb.build_and_test(port=spec.network.get('port') or 8000,health_path=spec.network.get('health_endpoint') or '/');outcome['attempt']=i+1;attempts.append(outcome);emit(events,'sandbox',f"Attempt {i+1}: {outcome.get('status','unknown')}",'done' if outcome.get('status')=='runtime_healthy' else 'warning',data=outcome)
   if run_security_tools and outcome.get('status') in {'runtime_healthy','runtime_started'}:
    emit(events,'security','Running runtime image SBOM/vulnerability tools…');image=outcome.get('image_tag');outcome['security_scan']=sb.security_scan(image);emit(events,'security','Runtime security scan completed.','done',data=outcome['security_scan'])
   if outcome.get('status')=='runtime_healthy':ledger.append({'attempt':i+1,'result':'pass','repair':None});break
   emit(events,'repair','Diagnosing failure and evaluating bounded deterministic repairs…');actions=repair_candidates(spec,outcome);repair=repair_apply(spec,outcome,Repository(root));ledger.append({'attempt':i+1,'result':outcome.get('status'),'diagnosis':outcome.get('diagnosis'),'candidates':actions,'repair':repair});emit(events,'repair',repair.get('message','Repair evaluation completed.'),'done' if repair.get('changed') else 'warning',data={'candidates':actions,'repair':repair})
   if not repair.get('changed'):break
   current=dockerfile(spec)
  result['validation']={'status':'passed' if attempts and attempts[-1].get('status')=='runtime_healthy' else ('skipped' if attempts and attempts[-1].get('status')=='skipped' else 'not_passed'),'attempts':attempts,'repair_ledger':ledger,'max_attempts':max_attempts,'autonomous_repair':bool(any(x.get('repair',{}).get('changed') for x in ledger))};result['deployment_gate']=deployment_gate(spec,result.get('static_validation',{}),result.get('security',{}).get('findings',[]),result['validation'])
 finally:sb.cleanup()
 return result
@app.get('/')
def root():
 index=FRONTEND/'index.html';return FileResponse(index) if index.exists() else {'service':'AutoDeploy Stack Intelligence','version':app.version,'docs':'/docs'}
@app.get('/frontend/{asset_path:path}')
def frontend_asset(asset_path:str):
 target=(FRONTEND/asset_path).resolve()
 if not str(target).startswith(str(FRONTEND.resolve())+os.sep) or not target.is_file():raise HTTPException(404,'Frontend asset not found.')
 return FileResponse(target)
@app.get('/health')
def health():return {'status':'ok','version':app.version,'engine':'deterministic-v1'}
@app.post('/analyze')
def analyze(req:AnalyzeRequest):
 tmp,root=clone(req.repo_url)
 try:d,_,_=analyze_root(root,req.providers);return d
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/analyze-stream')
def analyze_stream(req:AnalyzeRequest):
 def stream():
  q=queue.Queue();done=object()
  class LiveEvents(list):
   def append(self,item):super().append(item);q.put(item)
  def worker():
   try:
    q.put({'phase':'acquisition','message':'Cloning public GitHub repository…','status':'running','id':str(uuid.uuid4()),'time':time.time()});tmp,root=clone(req.repo_url)
    try:result,_,_=analyze_root(root,req.providers,LiveEvents());q.put({'__result__':result})
    finally:shutil.rmtree(tmp,ignore_errors=True)
   except Exception as exc:q.put({'__error__':str(exc)})
   finally:q.put(done)
  yield json.dumps({'type':'meta','analysis_id':str(uuid.uuid4()),'phase':'start','message':'Starting repository intelligence pipeline.'})+'\n';t=threading.Thread(target=worker,daemon=True);t.start()
  while True:
   item=q.get()
   if item is done:break
   if '__result__' in item:yield json.dumps({'type':'result','data':item['__result__']},default=str)+'\n'
   elif '__error__' in item:yield json.dumps({'type':'error','message':item['__error__']})+'\n'
   else:yield json.dumps({'type':'event',**item},default=str)+'\n'
  t.join(timeout=1)
 return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','Connection':'keep-alive'})
@app.post('/generate/dockerfile')
def generate_dockerfile(req:AnalyzeRequest):
 tmp,root=clone(req.repo_url)
 try:
  d,_,spec=analyze_root(root,req.providers)
  deep=d.get('deep_analysis',{})
  if deep.get('status')!='ready':
   raise HTTPException(422,detail={'message':'Dockerfile generation blocked: deep repository analysis did not reach a deterministic ready state.','deep_analysis':deep})
  if not d.get('static_validation',{}).get('valid',False):
   raise HTTPException(422,detail={'message':'Dockerfile generation blocked by static validation.','static_validation':d.get('static_validation',{})})
  verification=autonomous_validate(root,d,spec,req.max_repair_attempts,req.run_security_tools)
  if verification.get('validation',{}).get('status')!='passed':
   reason='Docker runtime verification is unavailable; Dockerfile withheld.' if verification.get('validation',{}).get('status')=='skipped' else 'Generated Dockerfile did not pass build/runtime verification after bounded repair attempts; Dockerfile withheld.'
   raise HTTPException(503 if verification.get('validation',{}).get('status')=='skipped' else 422,detail={'message':reason,'analysis_id':d['analysis_id'],'deep_analysis':deep,'validation':verification.get('validation',{}),'deployment_gate':verification.get('deployment_gate',{})})
  final_path=Path(root)/'Dockerfile'
  final=final_path.read_text() if final_path.exists() else dockerfile(spec)
  d['generated_files']['Dockerfile']=final
  return {'analysis_id':d['analysis_id'],'summary':d['summary'],'deep_analysis':deep,'stacks':{'languages':d['languages'],'frameworks':d['frameworks'],'services':d['summary']['services']},'dockerfile':final,'deployment_ir':d['deployment_ir'],'static_validation':static_dockerfile(final),'verification':verification.get('validation',{}),'deployment_gate':verification.get('deployment_gate',{})}
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/generate/docker-compose')
def generate_compose(req:AnalyzeRequest):
 tmp,root=clone(req.repo_url)
 try:
  d,_,_=analyze_root(root,req.providers);return {'analysis_id':d['analysis_id'],'summary':d['summary'],'deep_analysis':d.get('deep_analysis',{}),'stacks':{'languages':d['languages'],'frameworks':d['frameworks'],'services':d['summary']['services']},'compose':d['generated_files']['compose.yaml'],'deployment_ir':d['deployment_ir']}
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/analyze-upload')
async def analyze_upload(file:UploadFile=File(...),validate:bool=False,max_repair_attempts:int=3):
 if not file.filename or not file.filename.lower().endswith('.zip'):raise HTTPException(400,'Upload a .zip repository archive.')
 tmp,root=extract_zip(await file.read())
 try:
  d,_,spec=analyze_root(root,['aws','gcp','azure'])
  if validate:d=autonomous_validate(root,d,spec,max_repair_attempts)
  return d
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/validate')
def validate(req:ValidateRequest):
 tmp,root=clone(req.repo_url)
 try:d,_,spec=analyze_root(root,req.providers);return autonomous_validate(root,d,spec,req.max_repair_attempts,req.run_security_tools)
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/analyze-and-validate')
def analyze_validate(req:AnalyzeRequest):
 tmp,root=clone(req.repo_url)
 try:d,_,spec=analyze_root(root,req.providers);return autonomous_validate(root,d,spec,req.max_repair_attempts,req.run_security_tools)
 finally:shutil.rmtree(tmp,ignore_errors=True)
