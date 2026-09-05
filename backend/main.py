from fastapi import FastAPI,HTTPException,UploadFile,File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,HttpUrl,Field
from pathlib import Path
import tempfile,subprocess,shutil,zipfile,os,uuid
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
app=FastAPI(title='AutoDeploy Stack Intelligence',version='1.0.0',description='Deterministic repository-to-deployment analysis and bounded validation/repair engine.')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
class AnalyzeRequest(BaseModel):
 repo_url:HttpUrl;run_validation:bool=False;max_repair_attempts:int=Field(default=3,ge=1,le=5);providers:list[str]=Field(default_factory=lambda:['aws','gcp','azure']);run_security_tools:bool=False
class ValidateRequest(AnalyzeRequest):run_validation:bool=True
def clone(url):
 tmp=tempfile.mkdtemp(prefix='autodeploy-repo-');target=Path(tmp)/'repo';p=subprocess.run(['git','clone','--depth','1','--no-tags','--filter=blob:none',str(url),str(target)],capture_output=True,text=True,timeout=180)
 if p.returncode:shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(400,'Git clone failed: '+p.stderr[-3000:])
 return tmp,target
def extract_zip(data):
 tmp=tempfile.mkdtemp(prefix='autodeploy-zip-');root=Path(tmp)/'repo';root.mkdir()
 try:
  import io
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   for info in z.infolist():
    target=(root/info.filename).resolve()
    if not str(target).startswith(str(root.resolve())+os.sep):raise HTTPException(400,'Unsafe ZIP path detected.')
   z.extractall(root)
 except zipfile.BadZipFile:shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(400,'Invalid ZIP archive.')
 children=[p for p in root.iterdir() if p.is_dir()]
 if len(children)==1 and not any(root.iterdir()):root=children[0]
 elif len(children)==1 and not (root/'package.json').exists() and not (root/'pyproject.toml').exists():root=children[0]
 return tmp,root
def analyze_root(root,providers):
 repo=Repository(root);analyzer=Analyzer(repo);spec,_,result=analyzer.analyze();spec.dependencies=graph(repo);spec.migrations=migration_analyze(repo);findings=audit(repo);ast=ASTAnalyzer(repo).analyze();spec.security={'findings':[x.__dict__ for x in findings]};files={'Dockerfile':dockerfile(spec),'compose.yaml':compose(spec),'.dockerignore':'.git\n.github\n.env\n.env.*\nnode_modules\n__pycache__\n*.pyc\n.venv\ncoverage\n*.log\n.gitignore'};files['k8s.yaml']=kubernetes(spec)
 for p in providers:
  if p in {'aws','gcp','azure'}:files[f'terraform-{p}.tf']=terraform(spec,p)
 validation=static_dockerfile(files['Dockerfile']);pricing={p:PricingEngine().estimate(spec,p) for p in providers if p in {'aws','gcp','azure'}};spec.cloud={'providers':providers,'artifacts':list(files)};spec.policy={'confidence':result['summary']['confidence'],'requires_manual_approval':spec.migrations.get('requires_manual_approval',False)}
 result.update({'sandbox_policy':validate_policy(),'deployment_ir':spec.to_dict(),'generated_files':files,'ast':ast,'dependency_graph':spec.dependencies,'migrations':spec.migrations,'security':{'findings':[x.__dict__ for x in findings],'sbom':sbom_plan(repo,result['summary']['package_manager']),'vulnerability_scan':vulnerability_plan(),'policy':security_policy(findings)},'static_validation':validation,'cloud_cost_estimates':pricing,'analysis_id':str(uuid.uuid4()),'repository':{'path_count':len(repo.files),'size_bytes':repo.size_bytes(),'hash':repo.hash()}});return result,repo,spec
def autonomous_validate(root,result,spec,max_attempts,run_security_tools=False):
 sb=Sandbox(root);attempts=[];ledger=[];current=dockerfile(spec)
 try:
  for i in range(min(max_attempts,DEFAULT_POLICY.max_repair_attempts)):
   Path(root,'Dockerfile').write_text(current);outcome=sb.build_and_test(port=spec.network.get('port') or 8000,health_path=spec.network.get('health_endpoint') or '/');outcome['attempt']=i+1;attempts.append(outcome)
   if run_security_tools and outcome.get('status') in {'runtime_healthy','runtime_started'}:outcome['security_scan']=sb.security_scan(outcome.get('image_tag'))
   if outcome.get('status')=='runtime_healthy':ledger.append({'attempt':i+1,'result':'pass','repair':None});break
   actions=repair_candidates(spec,outcome);repair=repair_apply(spec,outcome,Repository(root));ledger.append({'attempt':i+1,'result':outcome.get('status'),'diagnosis':outcome.get('diagnosis'),'candidates':actions,'repair':repair})
   if not repair.get('changed'):break
   current=dockerfile(spec)
  result['validation']={'status':'passed' if attempts and attempts[-1].get('status')=='runtime_healthy' else 'not_passed','attempts':attempts,'repair_ledger':ledger,'max_attempts':max_attempts,'autonomous_repair':bool(any(x.get('repair',{}).get('changed') for x in ledger))};result['deployment_gate']=deployment_gate(spec,result.get('static_validation',{}),result.get('security',{}).get('findings',[]),result['validation'])
 finally:sb.cleanup()
 return result
@app.get('/health')
def health():return {'status':'ok','version':app.version,'engine':'deterministic-v1'}
@app.post('/analyze')
def analyze(req:AnalyzeRequest):
 tmp,root=clone(req.repo_url)
 try:return analyze_root(root,req.providers)[0]
 finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/analyze-upload')
async def analyze_upload(file:UploadFile=File(...),run_validation:bool=False,max_repair_attempts:int=3):
 if not file.filename or not file.filename.lower().endswith('.zip'):raise HTTPException(400,'Upload a .zip repository archive.')
 tmp,root=extract_zip(await file.read())
 try:
  d,_,spec=analyze_root(root,['aws','gcp','azure']);return autonomous_validate(root,d,spec,max_repair_attempts) if run_validation else d
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
