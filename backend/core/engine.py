from pathlib import Path
import re
from .models import Evidence,Candidate,DeploymentSpec
LANG_RULES=[('TypeScript',60,lambda r:r.exists('tsconfig.json') or any(Path(f).suffix in {'.ts','.tsx'} for f in r.files)),('JavaScript',45,lambda r:r.exists('package.json') or any(Path(f).suffix in {'.js','.jsx','.mjs','.cjs'} for f in r.files)),('Python',60,lambda r:r.exists('pyproject.toml','requirements.txt','Pipfile','poetry.lock','uv.lock') or any(f.endswith('.py') for f in r.files)),('Go',65,lambda r:r.exists('go.mod')),('Rust',65,lambda r:r.exists('Cargo.toml')),('Java',60,lambda r:r.exists('pom.xml','build.gradle','build.gradle.kts') or any(f.endswith(('.java','.kt','.kts')) for f in r.files)),('C#',65,lambda r:any(f.endswith('.csproj') for f in r.files) or any(f.endswith('.sln') for f in r.files)),('PHP',55,lambda r:r.exists('composer.json') or any(f.endswith('.php') for f in r.files)),('Ruby',55,lambda r:r.exists('Gemfile') or any(f.endswith('.rb') for f in r.files)),('Swift',55,lambda r:r.exists('Package.swift') or any(f.endswith('.swift') for f in r.files)),('Dart',55,lambda r:r.exists('pubspec.yaml') or any(f.endswith('.dart') for f in r.files)),('Elixir',55,lambda r:r.exists('mix.exs') or any(f.endswith('.ex') for f in r.files)),('Scala',55,lambda r:r.exists('build.sbt') or any(f.endswith('.scala') for f in r.files))]
FRAMEWORKS={'Node.js':[('Next.js','next',65),('Nuxt','nuxt',65),('NestJS','@nestjs/core',65),('Express','express',62),('Fastify','fastify',60),('Koa','koa',58),('Hono','hono',58),('Remix','@remix-run/node',62),('SvelteKit','@sveltejs/kit',62),('Angular','@angular/core',60),('React','react',50),('Vue','vue',50),('Vite','vite',42),('Astro','astro',58)],'Python':[('Django','django',65),('FastAPI','fastapi',65),('Flask','flask',60),('Litestar','litestar',60),('Sanic','sanic',58),('Tornado','tornado',55),('Celery','celery',48)],'Go':[('Gin','github.com/gin-gonic/gin',62),('Echo','github.com/labstack/echo',62),('Fiber','github.com/gofiber/fiber',62),('Chi','github.com/go-chi/chi',58)],'Java':[('Spring Boot','spring-boot',70),('Quarkus','quarkus',65),('Micronaut','micronaut',65)],'Rust':[('Axum','axum',65),('Actix Web','actix-web',65),('Rocket','rocket',60)],'C#':[('ASP.NET Core','Microsoft.AspNetCore',70)]}
PM_RULES=[('pnpm','pnpm-lock.yaml','pnpm'),('yarn','yarn.lock','yarn'),('bun','bun.lock','bun'),('npm','package-lock.json','npm'),('uv','uv.lock','uv'),('poetry','poetry.lock','poetry'),('pipenv','Pipfile.lock','pipenv'),('pip','requirements.txt','pip'),('go modules','go.mod','go'),('cargo','Cargo.lock','cargo'),('maven','pom.xml','maven'),('gradle','build.gradle','gradle'),('gradle','build.gradle.kts','gradle'),('composer','composer.lock','composer'),('bundler','Gemfile.lock','bundler')]
SERVICES={'PostgreSQL':['postgresql','postgres','psycopg','asyncpg','pg','prisma','typeorm'],'MySQL':['mysql','mysql2','pymysql'],'MariaDB':['mariadb'],'MongoDB':['mongodb','mongoose','motor'],'Redis':['redis','ioredis','redis-py'],'RabbitMQ':['rabbitmq','amqp','pika','aio-pika'],'Kafka':['kafka','kafkajs','confluent-kafka'],'Elasticsearch':['elasticsearch','opensearch'],'S3/Object Storage':['s3','aws-sdk','boto3','minio'],'Supabase':['supabase'],'Firebase':['firebase'],'Stripe':['stripe'],'DynamoDB':['dynamodb'],'SQLite':['sqlite','sqlite3']}
class Analyzer:
 def __init__(self,r):self.r=r;self.evidence=[]
 def add(self,cat,tech,points,file,reason):self.evidence.append(Evidence(cat,tech,points,file,reason))
 def candidates(self,rules):
  c={}
  for name,pts,test in rules:
   if test(self.r):c.setdefault(name,Candidate(name)).score+=pts
  return sorted(c.values(),key=lambda x:x.score,reverse=True)
 def analyze(self):
  r=self.r;langs=self.candidates(LANG_RULES)
  for c in langs:self.add('language',c.name,c.score,'source files',f'{c.name} project markers detected')
  primary=langs[0].name if langs else 'Unknown'
  if any(c.name=='TypeScript' and c.score>=60 for c in langs):primary='TypeScript'
  runtime,rv=self.runtime(primary);pms=[]
  for name,file,eco in PM_RULES:
   if file in r.file_set:pms.append({'name':name,'ecosystem':eco,'evidence_file':file});self.add('package_manager',name,35,file,f'{name} manifest/lockfile detected')
  if not pms and 'package.json' in r.file_set:
   pm=r.json('package.json').get('packageManager','');name=pm.split('@',1)[0] if pm else 'npm';pms=[{'name':name,'ecosystem':'npm','version':pm.split('@',1)[1] if '@' in pm else 'bundled/default','evidence_file':'package.json'}];self.add('package_manager',name,15,'package.json','Node package manifest detected; no lockfile was present.')
  frameworks=self.frameworks(primary);services=[];deptext=r.lower+(('\n'+str(r.json('package.json')).lower()) if 'package.json' in r.file_set else '')
  for svc,needles in SERVICES.items():
   hits=[n for n in needles if n in deptext]
   if hits:services.append({'name':svc,'signals':hits[:5]});self.add('service',svc,22,'dependency/source files',f'{svc} integration detected')
  build,start,out=self.commands(primary,frameworks[0]['name'] if frameworks else 'Unknown');port=self.port();env=self.envs();infra=self.infrastructure();roles=self.roles();health=self.health()
  spec=DeploymentSpec(project={'name':r.root.name,'repository_hash':r.hash(),'source_size_bytes':r.size_bytes(),'monorepo':self.monorepo(),'roles':roles},languages=[{'name':c.name,'score':c.score,'confidence':round(min(99,c.score/70*100),1)} for c in langs],runtime={'name':runtime,'version':rv},frameworks=[{'name':x['name'],'score':x['score']} for x in frameworks],package_managers=pms,build={'command':build,'output':out},processes=[{'role':role,'start_command':start if role=='web' else 'detected externally'} for role in roles],network={'port':port,'health_endpoint':health,'smoke_paths':[health,'/health','/healthz','/'] if health else ['/','/health','/healthz']},services=services,environment=env,ci_cd=self.ci(),infrastructure=infra,security={},cloud={})
  summary={'primary_language':primary,'runtime':runtime,'runtime_version':rv,'framework':frameworks[0]['name'] if frameworks else 'Unknown','package_manager':pms[0]['name'] if pms else 'Unknown','build_command':build,'start_command':start,'build_output':out,'port':port,'health_endpoint':health,'services':[x['name'] for x in services],'environment_variables':env['names'],'application_roles':roles,'monorepo':self.monorepo(),'confidence':self.overall_confidence(langs,frameworks,pms,build,start)}
  result={'summary':summary,'languages':[{'name':c.name,'score':c.score} for c in langs],'frameworks':frameworks,'evidence':[e.__dict__ for e in self.evidence],'files':r.files[:5000],'deployment_ir':spec.to_dict()}
  return spec,self.evidence,result
 def runtime(self,lang):
  r=self.r;runtime={'TypeScript':'Node.js','JavaScript':'Node.js','Python':'Python','Go':'Go','Rust':'Rust','Java':'JDK','C#':'.NET','PHP':'PHP','Ruby':'Ruby','Swift':'Swift','Dart':'Dart','Elixir':'Elixir','Scala':'JVM'}.get(lang,'Unknown');rv='Not declared'
  for f in {'Node.js':['.nvmrc','.node-version'],'Python':['.python-version','runtime.txt']}.get(runtime,[]):
   if f in r.file_set:rv=r.read(f).strip().splitlines()[0] or rv;return runtime,rv
  if runtime=='Node.js' and 'package.json' in r.file_set:rv=r.json('package.json').get('engines',{}).get('node',rv)
  elif runtime=='Python' and 'pyproject.toml' in r.file_set:
   m=re.search(r'requires-python\s*=\s*["\']([^"\']+)',r.read('pyproject.toml'),re.I);rv=m.group(1) if m else rv
  elif runtime=='Go' and 'go.mod' in r.file_set:
   m=re.search(r'^go\s+([0-9.]+)',r.read('go.mod'),re.M);rv=m.group(1) if m else rv
  elif runtime=='.NET':
   f=next((x for x in r.files if x.endswith('.csproj')),None);m=re.search(r'<TargetFramework[^>]*>([^<]+)',r.read(f)) if f else None;rv=m.group(1) if m else rv
  return runtime,rv
 def frameworks(self,lang):
  ecosystem='Node.js' if lang in ('JavaScript','TypeScript') else lang;out=[];pkg=self.r.json('package.json') if 'package.json' in self.r.file_set else {};js={**pkg.get('dependencies',{}),**pkg.get('devDependencies',{})};txt=self.r.lower
  for name,needle,pts in FRAMEWORKS.get(ecosystem,[]):
   if (needle.lower() in str(js).lower()) if ecosystem=='Node.js' else (needle.lower() in txt):out.append({'name':name,'score':pts})
  return sorted(out,key=lambda x:x['score'],reverse=True)
 def commands(self,lang,framework):
  r=self.r;build=start='Not detected';out='Not detected'
  if 'package.json' in r.file_set:
   s=r.json('package.json').get('scripts',{});build=s.get('build',build);start=s.get('start',s.get('serve',start));out='.next/' if framework=='Next.js' else ('dist/' if build!='Not detected' and 'dist' in build else ('build/' if build!='Not detected' and 'build' in build else 'Not detected'))
  if build=='Not detected' and 'Makefile' in r.file_set and re.search(r'^build:',r.read('Makefile'),re.M):build='make build'
  if lang=='Go' and build=='Not detected':build='go build -o app .'
  if lang=='Rust' and build=='Not detected':build='cargo build --release'
  if start=='Not detected':
   if lang in ('JavaScript','TypeScript'):start='npm run start' if framework in ('Next.js','Nuxt','NestJS') else ('node dist/server.js' if any(Path(f).name in {'server.js','server.ts'} for f in r.files) else 'Not detected')
   elif lang=='Python':start='gunicorn project.wsgi:application' if framework=='Django' else ('uvicorn main:app --host 0.0.0.0 --port 8000' if framework in ('FastAPI','Litestar','Sanic') else 'Not detected')
   elif lang in ('Go','Rust'):start='./app'
  return build,start,out
 def port(self):
  for pat in [r'(?:process\.env\.PORT|PORT)\s*[:=]\s*(?:parseInt\()?([0-9]{2,5})',r'(?:port|PORT)\s*[:=]\s*([0-9]{2,5})',r'--port\s+([0-9]{2,5})']:
   m=re.search(pat,self.r.corpus,re.I)
   if m:return int(m.group(1))
  return 3000 if any(x in self.r.lower for x in ['next.js','vite','express']) and 'python' not in self.r.lower else 8000
 def envs(self):
  names=set()
  for t in self.r.text.values():
   for m in re.finditer(r'\b[A-Z][A-Z0-9_]{2,}\b',t):
    if m.group(0) not in {'HTTP','HTTPS','JSON','NODE_ENV','PATH','HOME','PORT','TRUE','FALSE','GET','POST','PUT','DELETE'}:names.add(m.group(0))
  return {'names':sorted(names)[:500],'secret_files':[f for f in self.r.files if Path(f).name.startswith('.env') and Path(f).name not in {'.env.example','.env.sample','.env.template'}]}
 def infrastructure(self):
  files=[f for f in self.r.files if Path(f).name.lower() in {'dockerfile','compose.yml','compose.yaml','docker-compose.yml','terraform.tf','main.tf','pulumi.yaml','serverless.yml','vercel.json','render.yaml','fly.toml'} or f.startswith(('terraform/','k8s/','kubernetes/','helm/','infra/','.github/workflows/'))]
  return {'files':files,'providers':sorted(set(x for x in ['AWS','GCP','Azure','Kubernetes'] if x.lower() in self.r.lower))}
 def ci(self):
  out=[]
  for f in self.r.files:
   if f.startswith('.github/workflows/') or f in {'azure-pipelines.yml','.gitlab-ci.yml','.circleci/config.yml'}:out.append({'file':f,'tools':[n for k,n in [('docker','Docker'),('terraform','Terraform'),('setup-node','Node.js'),('setup-python','Python'),('setup-java','Java'),('kubectl','Kubernetes')] if k in self.r.read(f).lower()]})
  return {'workflows':out}
 def monorepo(self):return bool(self.r.exists('pnpm-workspace.yaml','turbo.json','nx.json','lerna.json','rush.json')) or any(f.startswith(('apps/','packages/','services/')) for f in self.r.files)
 def roles(self):
  l=self.r.lower;roles=['web']
  if any(x in l for x in ['celery','bullmq','sidekiq','hangfire','rq','dramatiq']):roles.append('worker')
  if any(x in l for x in ['cron','scheduler','apscheduler','node-cron','agenda']):roles.append('scheduler')
  if 'consumer' in l or 'kafkaconsumer' in l:roles.append('consumer')
  return sorted(set(roles))
 def health(self):
  for x in ['/health','/healthz','/ready','/readiness','/live']:
   if x in self.r.corpus:return x
  return None
 def overall_confidence(self,langs,fw,pms,build,start):return min(99,35+(30 if langs else 0)+(15 if fw else 0)+(10 if pms else 0)+(5 if build!='Not detected' else 0)+(5 if start!='Not detected' else 0))

# Deep deployment analysis is intentionally executed as part of Analyzer.analyze,
# before any caller can synthesize a Dockerfile from the returned Deployment IR.
_original_analyze = Analyzer.analyze

def _analyze_with_deep_pass(self, target=None):
    spec, evidence, result = _original_analyze(self)
    from .deep_analysis import analyze as deep_analyze
    deep_analyze(self.r, spec, result, target=target)
    if spec.processes:
        result['summary']['start_command'] = spec.processes[0].get('start_command', result['summary'].get('start_command'))
    result['summary']['port'] = spec.network.get('port', result['summary'].get('port'))
    result['summary']['deep_analysis_status'] = result['deep_analysis']['status']
    result['summary']['deep_analysis_confidence'] = result['deep_analysis']['confidence']
    result['deployment_ir'] = spec.to_dict()
    return spec, evidence, result

Analyzer.analyze = _analyze_with_deep_pass
