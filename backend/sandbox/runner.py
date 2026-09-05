import shutil,subprocess,tempfile,time,urllib.request,os,re
from pathlib import Path
class Sandbox:
 def __init__(self,repo_root):self.repo=Path(repo_root);self.work=Path(tempfile.mkdtemp(prefix='autodeploy-job-'))
 def docker_available(self):return shutil.which('docker') is not None
 def run(self,cmd,timeout=180,cwd=None):
  t=time.time()
  try:
   p=subprocess.run(cmd,cwd=cwd or self.repo,capture_output=True,text=True,timeout=timeout,env={**os.environ,'DOCKER_CONFIG':str(self.work/'docker-config')});return {'command':cmd,'returncode':p.returncode,'stdout':(p.stdout or '')[-20000:],'stderr':(p.stderr or '')[-20000:],'duration_seconds':round(time.time()-t,2)}
  except subprocess.TimeoutExpired:return {'command':cmd,'returncode':124,'stdout':'','stderr':'TIMEOUT','duration_seconds':round(time.time()-t,2)}
 def build_and_test(self,dockerfile_path='Dockerfile',port=8000,health_path='/'):
  if not self.docker_available():return {'available':False,'status':'skipped','reason':'Docker worker unavailable; no untrusted code was executed.'}
  tag='autodeploy-sandbox:'+self.repo.name.lower().replace('_','-')[:30]
  build=self.run(['docker','build','--progress=plain','--network=default','--pull','--no-cache','-f',dockerfile_path,'-t',tag,'.'],900)
  if build['returncode']!=0:return {'available':True,'status':'build_failed','build':build,'diagnosis':diagnose(build['stderr'])}
  run=self.run(['docker','run','-d','--rm','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','128','--memory','1024m','--cpus','1','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=128m','-p',f'127.0.0.1::{port}',tag],60)
  if run['returncode']!=0:return {'available':True,'status':'run_failed','image_tag':tag,'build':build,'run':run,'diagnosis':diagnose(run['stderr'])}
  cid=run['stdout'].strip();mapped=self.run(['docker','port',cid,str(port)],10);m=re.search(r':(\d+)$',mapped.get('stdout','').strip());hp=int(m.group(1)) if m else None;smoke={'ok':False,'status':None,'url':None,'error':None}
  for path in dict.fromkeys([health_path,'/health','/healthz','/']):
   if not hp:break
   smoke['url']=f'http://127.0.0.1:{hp}{path}'
   try:
    with urllib.request.urlopen(smoke['url'],timeout=8) as r:smoke.update(ok=r.status<500,status=r.status,path=path)
    if smoke['ok']:break
   except Exception as e:smoke['error']=str(e)
  logs=self.run(['docker','logs',cid],10);inspect=self.run(['docker','inspect',cid],10);stop=self.run(['docker','stop',cid],15);status='runtime_healthy' if smoke['ok'] else 'runtime_unhealthy'
  return {'available':True,'status':status,'image_tag':tag,'build':build,'run':run,'port_mapping':mapped,'smoke_test':smoke,'logs':logs,'inspect':inspect,'stop':stop,'diagnosis':diagnose(logs.get('stderr','')+logs.get('stdout',''))}
 def security_scan(self,image=None):
  target=image or str(self.repo);out={}
  out['trivy']=self.run(['trivy','image' if image else 'fs','--scanners','vuln,secret,misconfig','--format','json',target],300) if shutil.which('trivy') else {'status':'skipped','reason':'trivy not installed'}
  out['syft']=self.run(['syft',target,'-o','cyclonedx-json'],300) if shutil.which('syft') else {'status':'skipped','reason':'syft not installed'}
  return out
 def cleanup(self):shutil.rmtree(self.work,ignore_errors=True)
def diagnose(text):
 s=(text or '').lower();rules=[('missing_file',['no such file or directory','not found'],'Reinspect generated paths and artifact layout.'),('missing_module',['cannot find module','modulenotfounderror','no module named'],'Reconcile runtime dependency installation and lockfile.'),('exec_format',['exec format error'],'Verify architecture and executable format.'),('permission',['permission denied'],'Fix ownership/permissions while retaining non-root runtime.'),('lockfile',['lockfile','frozen-lockfile','package-lock'],'Use the repository lockfile and matching package manager.'),('memory',['out of memory','oom'],'Increase bounded worker memory or reduce build parallelism.'),('health',['connection refused','timed out'],'Re-evaluate bind address, port and health route.'),('network',['network is unreachable','could not resolve','temporary failure resolving'],'Use controlled build egress and keep runtime egress disabled.')]
 for code,needles,fix in rules:
  if any(n in s for n in needles):return {'code':code,'message':fix,'confidence':0.9}
 return {'code':'unknown','message':'No deterministic diagnosis matched. Stop autonomous mutation and retain evidence for review.','confidence':0.1}
