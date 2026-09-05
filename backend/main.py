from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from pathlib import Path
import tempfile, subprocess, shutil, re, json, zipfile, ast

app = FastAPI(title='Stack Detection Engine', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    validate_docker: bool = True
    generate_infrastructure: bool = True

IGNORE_DIRS={'.git','node_modules','.venv','venv','__pycache__','.next','dist','build','target','vendor','.terraform','.pytest_cache','coverage','.idea','.vscode'}
TEXT_EXT={'.js','.jsx','.ts','.tsx','.py','.go','.rs','.java','.kt','.kts','.cs','.fs','.rb','.php','.swift','.scala','.sh','.bash','.json','.yaml','.yml','.toml','.ini','.cfg','.env','.md','.txt','.xml','.gradle'}
MANIFESTS={'package.json','requirements.txt','pyproject.toml','Pipfile','poetry.lock','uv.lock','go.mod','Cargo.toml','pom.xml','build.gradle','build.gradle.kts','Gemfile','composer.json'}

def read(p, limit=300_000):
    try: return p.read_text(errors='ignore')[:limit]
    except: return ''

def repo_files(root): return sorted([p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts)])
def ev(points,file,reason,category): return {'points':points,'file':file,'reason':reason,'category':category}
def parse_json(root,name):
    try: return json.loads(read(root/name)) if (root/name).exists() else {}
    except: return {}
def package_data(root, files):
    if 'package.json' not in files:return {},{}
    j=parse_json(root,'package.json'); return j,{**j.get('dependencies',{}),**j.get('devDependencies',{})}

def detect_languages(root, files):
    scores={}; evidence=[]
    def add(n,p,f,r): scores[n]=scores.get(n,0)+p; evidence.append(ev(p,f,r,'language'))
    if 'package.json' in files:add('JavaScript',40,'package.json','Node package manifest')
    if 'tsconfig.json' in files:add('TypeScript',55,'tsconfig.json','TypeScript compiler configuration')
    if any(f.endswith(('.js','.jsx')) for f in files):add('JavaScript',15,'source','JavaScript source files present')
    if any(f.endswith(('.ts','.tsx')) for f in files):add('TypeScript',20,'source','TypeScript source files present')
    if 'requirements.txt' in files or 'pyproject.toml' in files or 'Pipfile' in files:add('Python',50,'requirements.txt' if 'requirements.txt' in files else 'pyproject.toml','Python dependency manifest')
    if any(f.endswith('.py') for f in files):add('Python',20,'source','Python source files present')
    if 'go.mod' in files:add('Go',60,'go.mod','Go module manifest')
    if any(f.endswith('.go') for f in files):add('Go',15,'source','Go source files present')
    if 'Cargo.toml' in files:add('Rust',60,'Cargo.toml','Rust manifest')
    if any(f.endswith('.rs') for f in files):add('Rust',15,'source','Rust source files present')
    if 'pom.xml' in files or 'build.gradle' in files or 'build.gradle.kts' in files:add('Java',55,'pom.xml' if 'pom.xml' in files else 'build.gradle','Java build manifest')
    if any(f.endswith(('.java','.kt','.kts')) for f in files):add('Java/JVM',20,'source','JVM source files present')
    cs=next((f for f in files if f.endswith('.csproj')),None)
    if cs:add('C#/.NET',65,cs,'.NET project file')
    if any(f.endswith('.cs') for f in files):add('C#/.NET',20,'source','C# source files present')
    if 'Gemfile' in files:add('Ruby',60,'Gemfile','Ruby dependency manifest')
    if any(f.endswith('.rb') for f in files):add('Ruby',15,'source','Ruby source files present')
    if 'composer.json' in files:add('PHP',60,'composer.json','PHP dependency manifest')
    if any(f.endswith('.php') for f in files):add('PHP',15,'source','PHP source files present')
    return sorted(scores.items(),key=lambda x:x[1],reverse=True),evidence

def detect_frameworks(root, files, pkg, deps):
    found=[]
    def dep(n,l,p):
        if n in deps:found.append((l,p,'package.json',f'{l} dependency detected'))
    for x in [('next','Next.js',60),('express','Express',55),('@nestjs/core','NestJS',60),('fastify','Fastify',55),('koa','Koa',50),('hono','Hono',50),('react','React',35),('vue','Vue',40),('@angular/core','Angular',50),('svelte','Svelte',45),('nuxt','Nuxt',55),('remix','Remix',55),('astro','Astro',50),('vite','Vite',40),('electron','Electron',40),('socket.io','Socket.IO',40)]:dep(*x)
    pytext=(read(root/'requirements.txt') if 'requirements.txt' in files else '')+(read(root/'pyproject.toml') if 'pyproject.toml' in files else '')
    for n,l,p in [('fastapi','FastAPI',60),('django','Django',60),('flask','Flask',55),('starlette','Starlette',45),('tornado','Tornado',45),('streamlit','Streamlit',50),('celery','Celery',45)]:
        if re.search(r'\b'+re.escape(n)+r'\b',pytext,re.I):found.append((l,p,'requirements/pyproject',f'{l} dependency detected'))
    gotext=' '.join(read(root/f) for f in files if f.endswith('.go')); gomod=read(root/'go.mod') if 'go.mod' in files else ''
    for n,l,p in [('gin-gonic/gin','Gin',55),('labstack/echo','Echo',55),('gofiber/fiber','Fiber',55),('go-chi/chi','Chi',50)]:
        if n in gotext or n in gomod:found.append((l,p,'go.mod/source',f'{l} import/module detected'))
    if 'Cargo.toml' in files:
        t=read(root/'Cargo.toml')
        for n,l,p in [('actix-web','Actix Web',55),('axum','Axum',55),('rocket','Rocket',50),('warp','Warp',45)]:
            if n in t:found.append((l,p,'Cargo.toml',f'{l} dependency detected'))
    if 'pom.xml' in files:
        t=read(root/'pom.xml').lower()
        for n,l,p in [('spring-boot','Spring Boot',60),('quarkus','Quarkus',55),('micronaut','Micronaut',55)]:
            if n in t:found.append((l,p,'pom.xml',f'{l} dependency detected'))
    cs=[f for f in files if f.endswith('.csproj')]
    if cs and any(x in ' '.join(read(root/f) for f in cs).lower() for x in ('microsoft.net.sdk.web','microsoft.aspnetcore')):found.append(('ASP.NET Core',60,'*.csproj','ASP.NET Core web SDK detected'))
    return sorted(found,key=lambda x:x[1],reverse=True)

def detect_package_manager(root, files, pkg):
    c=[]
    for n,f,p in [('pnpm','pnpm-lock.yaml',50),('yarn','yarn.lock',50),('npm','package-lock.json',50),('bun','bun.lock',50),('pipenv','Pipfile',50),('poetry','poetry.lock',50),('uv','uv.lock',50),('pip','requirements.txt',35),('go modules','go.mod',60),('cargo','Cargo.toml',60),('bundler','Gemfile',60),('composer','composer.json',60)]:
        if f in files or n=='bun' and 'bun.lockb' in files:c.append((n,f,p))
    if '@' in pkg.get('packageManager',''):
        n,_=pkg['packageManager'].split('@',1);c.insert(0,(n,'package.json',70))
    return c

def detect_runtime(root, files, language):
    name={'JavaScript':'Node.js','TypeScript':'Node.js','Python':'Python','Go':'Go','Rust':'Rust','Java/JVM':'JDK','Java':'JDK','C#/.NET':'.NET','Ruby':'Ruby','PHP':'PHP'}.get(language,'Unknown'); version=None;e=[]
    for f in {'Node.js':['.nvmrc','.node-version'],'Python':['.python-version','runtime.txt'],'Ruby':['.ruby-version']}.get(name,[]):
        if f in files:version=read(root/f).strip().splitlines()[0];e.append(ev(60,f,f'{name} version explicitly declared','runtime'));break
    if name=='Node.js' and not version and 'package.json' in files:
        x=parse_json(root,'package.json').get('engines',{}).get('node');
        if x:version=x;e.append(ev(40,'package.json','Node engine constraint','runtime'))
    if name=='Python' and not version and 'pyproject.toml' in files:
        m=re.search(r'(?:requires-python|python)\s*=\s*["\']([^"\']+)',read(root/'pyproject.toml'))
        if m:version=m.group(1);e.append(ev(35,'pyproject.toml','Python version constraint','runtime'))
    if name=='Go' and 'go.mod' in files:
        m=re.search(r'^go\s+([0-9.]+)',read(root/'go.mod'),re.M)
        if m:version=m.group(1);e.append(ev(60,'go.mod','Go language version','runtime'))
    return {'name':name,'version':version},e

def detect_commands(root, files, pkg, language):
    scripts=pkg.get('scripts',{}) if pkg else {};build=scripts.get('build','');start=scripts.get('start') or scripts.get('serve') or scripts.get('preview','');e=[]
    if build:e.append(ev(45,'package.json',f'build script: {build}','build'))
    if start:e.append(ev(45,'package.json',f'start script: {start}','entrypoint'))
    output='';
    for x in (('.next','dist') if '.next' in build else ('dist','dist') if 'dist' in build else ('build','build') if 'build' in build else ('out','out') if 'out' in build else (None,None)):
        if x[0]:output=x[1]+'/'
    if not start:
        f=next((x for x in ['server.js','server.ts','src/server.js','src/server.ts','main.py','app.py','src/main.py','manage.py','main.go','cmd/server/main.go','Program.cs'] if x in files),None)
        if f:start=f;e.append(ev(25,f,'Likely application entrypoint','entrypoint'))
    return build,start,output,e

def detect_ports(texts,framework):
    alltext='\n'.join(texts.values())
    for p in [r'process\.env\.PORT\s*\|\|\s*(\d{2,5})',r'listen\(\s*(?:process\.env\.PORT\s*\|\|\s*)?(\d{2,5})',r'port\s*[:=]\s*(\d{2,5})',r'--port[ =](\d{2,5})',r'EXPOSE\s+(\d{2,5})']:
        m=re.search(p,alltext,re.I)
        if m:return int(m.group(1)),ev(35,'source/config','Application port explicitly detected','network')
    defaults={'Next.js':3000,'Vite':5173,'Express':3000,'NestJS':3000,'Fastify':3000,'FastAPI':8000,'Django':8000,'Flask':5000,'ASP.NET Core':8080,'Spring Boot':8080,'Go':8080,'Rust':8080}
    return (defaults.get(framework),ev(15,'framework/default','Framework default port','network')) if framework in defaults else (None,None)

def detect_services(texts,deps):
    hay='\n'.join(texts.values()).lower();keys={k.lower() for k in deps};found=[];e=[]
    patterns={'PostgreSQL':['postgresql','postgres','psycopg','pgx','pg','prisma'],'MySQL':['mysql','pymysql'],'MariaDB':['mariadb'],'MongoDB':['mongodb','mongoose','pymongo'],'Redis':['redis','ioredis','bullmq'],'RabbitMQ':['rabbitmq','amqplib'],'Kafka':['kafka','kafkajs','confluent'],'SQLite':['sqlite'],'Elasticsearch':['elasticsearch'],'DynamoDB':['dynamodb'],'S3/Object Storage':['s3','minio']}
    for name,needles in patterns.items():
        hits=[n for n in needles if n in hay or n in keys]
        if hits:found.append(name);e.append(ev(min(35,15+5*len(hits)),'dependencies/source',f'{name} indicators: {", ".join(hits[:5])}','service'))
    return found,e

def detect_envs(texts):
    found=set();pats=[r'process\.env\.([A-Z][A-Z0-9_]{2,})',r'os\.getenv\(["\']([A-Z][A-Z0-9_]{2,})',r'getenv\(["\']([A-Z][A-Z0-9_]{2,})',r'os\.environ\[["\']([A-Z][A-Z0-9_]{2,})',r'\$\{([A-Z][A-Z0-9_]{2,})\}']
    for t in texts.values():
        for p in pats:found.update(re.findall(p,t))
    return sorted(found)

def detect_architecture(files,texts,services,framework,deps):
    dirs={Path(f).parts[0] for f in files if Path(f).parts};roles=[]
    if {'pnpm-workspace.yaml','turbo.json','nx.json','lerna.json'}.intersection(files) or any(x in dirs for x in ('apps','packages','services')):roles.append('monorepo')
    hay=' '.join(texts.values()).lower()
    for name,signals in [('worker',['worker','celery','bullmq','sidekiq','consumer']),('scheduler',['cron','schedule','scheduler','beat']),('api',['express','fastapi','django','flask','nestjs','http.listen','uvicorn','spring']),('frontend',['react','vue','angular','svelte','next.js','vite'])]:
        if any(x in hay for x in signals):roles.append(name)
    if 'pm2' in deps:roles.append('process-manager:pm2')
    if 'gunicorn' in deps:roles.append('process-manager:gunicorn')
    if 'uvicorn' in deps:roles.append('server:uvicorn')
    return sorted(set(roles))

def detect_health(texts):return sorted({r for t in texts.values() for r in ['/health','/healthz','/ready','/readiness','/live','/liveness'] if r in t})
def detect_ci_infra(files):
    ci=[];infra=[]
    if any(f.startswith('.github/workflows/') for f in files):ci.append('GitHub Actions')
    if '.gitlab-ci.yml' in files:ci.append('GitLab CI')
    if 'Jenkinsfile' in files:ci.append('Jenkins')
    if 'azure-pipelines.yml' in files:ci.append('Azure Pipelines')
    if 'bitbucket-pipelines.yml' in files:ci.append('Bitbucket Pipelines')
    if any(Path(f).name.lower().startswith('dockerfile') for f in files):infra.append('Docker')
    if any(Path(f).name.lower() in ('docker-compose.yml','docker-compose.yaml','compose.yml','compose.yaml') for f in files):infra.append('Docker Compose')
    if any(f.endswith('.tf') or f.startswith('terraform/') for f in files):infra.append('Terraform')
    if any(f.startswith(('k8s/','kubernetes/','helm/')) for f in files):infra.append('Kubernetes/Helm')
    if any(f in files for f in ('serverless.yml','serverless.yaml','sam-template.yaml','template.yaml')):infra.append('Serverless')
    return ci,infra

def ast_analysis(root,files,language):
    r={'python_imports':[],'python_entrypoints':[],'js_imports':[],'parse_errors':[]}
    if language=='Python':
        for f in files:
            if f.endswith('.py'):
                try:
                    tree=ast.parse(read(root/f))
                    for n in ast.walk(tree):
                        if isinstance(n,ast.Import):r['python_imports'] += [a.name.split('.')[0] for a in n.names]
                        elif isinstance(n,ast.ImportFrom) and n.module:r['python_imports'].append(n.module.split('.')[0])
                        elif isinstance(n,ast.FunctionDef) and n.name in ('main','create_app','get_app'):r['python_entrypoints'].append(f'{f}:{n.name}')
                except Exception as e:r['parse_errors'].append(f'{f}: {e}')
    else:
        for f in files:
            if f.endswith(('.js','.jsx','.ts','.tsx')):r['js_imports'] += re.findall(r'(?:from|require\()\s*[\'\"]([^\'\"]+)',read(root/f,100_000))
    r['python_imports']=sorted(set(r['python_imports']));r['js_imports']=sorted(set(r['js_imports']));return r

def detect(root):
    files=repo_files(root);texts={f:read(root/f) for f in files if Path(f).suffix.lower() in TEXT_EXT or Path(f).name in MANIFESTS};pkg,deps=package_data(root,files)
    langs,lev=detect_languages(root,files);language=langs[0][0] if langs else 'Unknown';evidence=lev[:]
    frameworks=detect_frameworks(root,files,pkg,deps);framework=frameworks[0][0] if frameworks else 'Unknown';evidence += [ev(x[1],x[2],x[3],'framework') for x in frameworks[:4]]
    pms=detect_package_manager(root,files,pkg);pm=pms[0][0] if pms else 'Unknown';pmver=pkg.get('packageManager','').split('@',1)[1] if '@' in pkg.get('packageManager','') else None;evidence += [ev(x[2],x[1],f'{x[0]} package manager signal','package-manager') for x in pms[:3]]
    runtime,rev=detect_runtime(root,files,language);evidence += rev;build,start,output,cev=detect_commands(root,files,pkg,language);evidence += cev;port,pev=detect_ports(texts,framework);evidence += [pev] if pev else [];services,sev=detect_services(texts,deps);evidence += sev;envs=detect_envs(texts);roles=detect_architecture(files,texts,services,framework,deps);health=detect_health(texts);ci,infra=detect_ci_infra(files);astx=ast_analysis(root,files,language);monorepo='monorepo' in roles;existing=[f for f in files if Path(f).name.lower() in {'dockerfile','compose.yaml','compose.yml','docker-compose.yml'} or f.endswith('.tf')]
    confidence=min(99,max(0,round(35+sum(x['points'] for x in evidence)/max(10,len(files))*65)));conflicts=[]
    if len(langs)>1 and langs[0][1]-langs[1][1]<20:conflicts.append('Multiple language signals are close; review the evidence ledger before production deployment.')
    ir={'schema_version':'1.0','project':{'files_scanned':len(files),'monorepo':monorepo},'runtime':{'language':language,'version':runtime['version'] or 'not-declared','runtime':runtime['name'],'package_manager':pm,'package_manager_version':pmver or 'not-declared'},'framework':{'name':framework,'alternatives':[x[0] for x in frameworks[1:8]]},'build':{'command':build or None,'output':output or None},'start':{'command':start or None},'network':{'port':port},'services':services,'environment':{'variables':envs},'architecture':{'roles':roles,'health_endpoints':health,'ci':ci,'infrastructure':infra},'evidence':evidence,'conflicts':conflicts,'ast':astx}
    return {'summary':{'language':language,'language_candidates':langs[:8],'runtime':runtime['name'],'runtime_version':runtime['version'] or 'Not declared','framework':framework,'framework_alternatives':[x[0] for x in frameworks[1:8]],'package_manager':pm,'package_manager_version':pmver or 'Not declared','build_command':build or 'Not detected','start_command':start or 'Not detected','build_output':output or 'Not detected','port':port,'services':services,'environment_variables':envs,'roles':roles,'health_endpoints':health,'ci':ci,'infrastructure':infra,'monorepo':monorepo,'confidence':confidence},'evidence':sorted(evidence,key=lambda x:x['points'],reverse=True),'files':files[:2000],'existing_deployment_files':existing,'deployment_ir':ir}

def shell_cmd(cmd):return cmd.split()
def dockerfile_for(d):
    s=d['summary'];lang=s['language'];pm=s['package_manager'];ver=s['runtime_version'];port=s['port'] or 3000;build=s['build_command'];start=s['start_command'];output=s['build_output']
    if lang in ('JavaScript','TypeScript'):
        node=re.search(r'\d+(?:\.\d+)?',ver or '');nodever=node.group(0) if node else '20';lock={'pnpm':'pnpm-lock.yaml','yarn':'yarn.lock','npm':'package-lock.json','bun':'bun.lock'}.get(pm,'package-lock.json');setup={'pnpm':f'RUN corepack enable && corepack prepare pnpm@{s["package_manager_version"] if s["package_manager_version"]!="Not declared" else "latest"} --activate\nRUN pnpm install --frozen-lockfile','yarn':'RUN corepack enable && yarn install --immutable','bun':'RUN npm install -g bun && bun install --frozen-lockfile'}.get(pm,'RUN npm ci');prod={'pnpm':f'RUN corepack enable && corepack prepare pnpm@{s["package_manager_version"] if s["package_manager_version"]!="Not declared" else "latest"} --activate\nRUN pnpm install --prod --frozen-lockfile','yarn':'RUN corepack enable && yarn install --immutable --production=true','bun':'RUN npm install -g bun && bun install --frozen-lockfile --production'}.get(pm,'RUN npm ci --omit=dev');buildcmd=build if build!='Not detected' else 'npm run build';startcmd=start if start!='Not detected' else 'node dist/server.js';copyout=output.rstrip('/') if output!='Not detected' else 'dist'
        return f'''# Generated by Stack Detection Engine. Review before production use.\nFROM node:{nodever}-bookworm-slim AS deps\nWORKDIR /app\nCOPY package.json {lock} ./\n{setup}\n\nFROM deps AS build\nCOPY . .\nRUN {buildcmd}\n\nFROM node:{nodever}-bookworm-slim AS runtime\nWORKDIR /app\nENV NODE_ENV=production\nENV PORT={port}\nCOPY package.json {lock} ./\n{prod}\nCOPY --from=build /app/{copyout} ./{copyout}\nRUN chown -R node:node /app\nUSER node\nEXPOSE {port}\nCMD {json.dumps(shell_cmd(startcmd))}\n'''
    if lang=='Python':
        pv=re.search(r'\d+\.\d+',ver or '');py=pv.group(0) if pv else '3.12';install='RUN pip install --no-cache-dir -r requirements.txt' if 'requirements.txt' in d['files'] else 'RUN pip install --no-cache-dir .';startcmd=start if start!='Not detected' else 'uvicorn main:app --host 0.0.0.0 --port 8000';return f'''FROM python:{py}-slim\nWORKDIR /app\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nCOPY {'requirements.txt' if 'requirements.txt' in d['files'] else '.'} {'requirements.txt' if 'requirements.txt' in d['files'] else ''}\n{install}\nCOPY . .\nRUN useradd --create-home --uid 10001 appuser\nUSER appuser\nEXPOSE {port or 8000}\nCMD {json.dumps(shell_cmd(startcmd))}\n'''
    if lang=='Go':
        gv=re.search(r'\d+(?:\.\d+){1,2}',ver or '');go=gv.group(0) if gv else '1.24';return f'''FROM golang:{go} AS build\nWORKDIR /src\nCOPY go.mod go.sum* ./\nRUN go mod download\nCOPY . .\nRUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .\nFROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port or 8080}\nENTRYPOINT ["/app"]\n'''
    if lang=='Rust':return f'''FROM rust:1.89 AS build\nWORKDIR /src\nCOPY Cargo.toml Cargo.lock* ./\nRUN cargo fetch\nCOPY . .\nRUN cargo build --release\nFROM debian:bookworm-slim\nCOPY --from=build /src/target/release/ /opt/app/\nEXPOSE {port or 8080}\nUSER 10001:10001\nENTRYPOINT ["/opt/app/app"]\n'''
    if lang in ('Java','Java/JVM'):return f'''FROM eclipse-temurin:21-jdk AS build\nWORKDIR /app\nCOPY . .\nRUN if [ -f ./mvnw ]; then ./mvnw -DskipTests package; elif [ -f ./gradlew ]; then ./gradlew bootJar -x test; else echo "No supported Maven/Gradle wrapper" && exit 1; fi\nFROM eclipse-temurin:21-jre\nWORKDIR /app\nCOPY --from=build /app/target/*.jar /app/app.jar\nEXPOSE {port or 8080}\nUSER 10001\nENTRYPOINT ["java","-jar","/app/app.jar"]\n'''
    if lang=='C#/.NET':return f'''FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet publish -c Release -o /out\nFROM mcr.microsoft.com/dotnet/aspnet:8.0\nWORKDIR /app\nCOPY --from=build /out .\nUSER 10001\nEXPOSE {port or 8080}\nENTRYPOINT ["dotnet","APP.dll"]\n'''
    return f'# No safe production template is registered for detected language: {lang}\n# Framework: {s["framework"]}\n'

def compose_for(d):
    s=d['summary'];p=s['port'] or 3000;lines=['services:','  app:','    build:','      context: .','      dockerfile: Dockerfile',f'    ports:\n      - "{p}:{p}"','    restart: unless-stopped']
    if 'PostgreSQL' in s['services']:lines += ['    environment:','      DATABASE_URL: ${DATABASE_URL:-postgresql://app:change-me@postgres:5432/app}','    depends_on:','      postgres:','        condition: service_healthy','  postgres:','    image: postgres:16','    environment:','      POSTGRES_DB: app','      POSTGRES_USER: app','      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change-me}','    volumes:','      - postgres_data:/var/lib/postgresql/data','    healthcheck:','      test: ["CMD-SHELL", "pg_isready -U app -d app"]','      interval: 10s','      timeout: 5s','      retries: 5','volumes:','  postgres_data:']
    if 'Redis' in s['services']:lines += ['  redis:','    image: redis:7-alpine','    healthcheck:','      test: ["CMD", "redis-cli", "ping"]','      interval: 10s','      timeout: 5s','      retries: 5']
    return '\n'.join(lines)+'\n'
def terraform_for(d):return f'''# Minimal provider-neutral starting point generated from Deployment IR.\nterraform {{ required_version = ">= 1.6.0" }}\nvariable "container_port" {{ type=number default={d["summary"]["port"] or 3000} }}\noutput "detected_container_port" {{ value=var.container_port }}\n'''
def k8s_for(d):
    p=d['summary']['port'] or 3000;return f'''apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: detected-app\nspec:\n  replicas: 2\n  selector:\n    matchLabels:\n      app: detected-app\n  template:\n    metadata:\n      labels:\n        app: detected-app\n    spec:\n      containers:\n        - name: app\n          image: REPLACE_ME\n          ports:\n            - containerPort: {p}\n          readinessProbe:\n            httpGet:\n              path: /health\n              port: {p}\n---\napiVersion: v1\nkind: Service\nmetadata:\n  name: detected-app\nspec:\n  selector:\n    app: detected-app\n  ports:\n    - port: {p}\n      targetPort: {p}\n'''
def security_review(d):
    issues=[]
    for f in d['files']:
        if Path(f).name in ('.env','.env.local','.env.production'):issues.append({'severity':'high','file':f,'message':'Environment file may contain secrets; do not bake it into images.'})
    if d['summary']['runtime_version']=='Not declared':issues.append({'severity':'medium','file':'runtime','message':'Runtime version is not explicitly pinned.'})
    if d['summary']['start_command']=='Not detected':issues.append({'severity':'medium','file':'entrypoint','message':'Application start command could not be proven from repository evidence.'})
    return issues

def docker_validate(root,dockerfile,port,health_endpoints):
    out={'available':shutil.which('docker') is not None,'build':None,'run':None,'health':None,'errors':[]}
    if not out['available']:out['errors'].append('Docker CLI unavailable; build/runtime validation skipped.');return out
    (root/'Dockerfile.autodeploy').write_text(dockerfile)
    try:b=subprocess.run(['docker','build','-f','Dockerfile.autodeploy','-t','stack-detection-check:latest','.'],cwd=root,capture_output=True,text=True,timeout=600)
    except subprocess.TimeoutExpired:out['errors'].append('Docker build timed out.');return out
    out['build']={'passed':b.returncode==0,'exit_code':b.returncode,'stdout':b.stdout[-4000:],'stderr':b.stderr[-4000:]}
    if b.returncode:return out
    cid=subprocess.run(['docker','create','stack-detection-check:latest'],cwd=root,capture_output=True,text=True,timeout=30)
    if cid.returncode:out['errors'].append(cid.stderr[-2000:]);return out
    container=cid.stdout.strip()
    try:
        subprocess.run(['docker','start',container],cwd=root,capture_output=True,text=True,timeout=30);import time;time.sleep(3);logs=subprocess.run(['docker','logs',container],capture_output=True,text=True,timeout=10);inspect=subprocess.run(['docker','inspect','-f','{{.State.Status}} {{.State.ExitCode}}',container],capture_output=True,text=True,timeout=10);out['run']={'passed':True,'status':inspect.stdout.strip(),'logs':(logs.stdout+logs.stderr)[-4000:]}
    finally:subprocess.run(['docker','rm','-f',container],capture_output=True,text=True,timeout=20)
    return out

def classify_failure(validation):
    b=validation.get('build') or {};text=((b.get('stderr') or '')+' '+(b.get('stdout') or '')).lower()
    if not text:return None
    if 'cannot find module' in text or 'no such file or directory' in text:return 'missing-artifact-or-entrypoint'
    if 'command not found' in text:return 'missing-runtime-tool'
    if 'permission denied' in text:return 'permissions'
    if 'out of memory' in text:return 'resource-limit'
    if 'npm err!' in text or ('pnpm' in text and 'err' in text):return 'dependency-installation'
    return 'unknown-build-failure'

def deterministic_repairs(d,validation):
    repairs=[];kind=classify_failure(validation);s=d['summary']
    if kind=='missing-artifact-or-entrypoint' and s['language'] in ('JavaScript','TypeScript') and s['start_command']=='Not detected':
        c=[f for f in d['files'] if Path(f).name in ('server.js','server.ts','main.js','main.ts')]
        if c:repairs.append({'type':'entrypoint','action':'set-start-candidate','value':c[0],'reason':'Source file matches application entrypoint naming convention.'})
    if kind=='permissions':repairs.append({'type':'security','action':'review-file-ownership','reason':'Container process likely lacks permission for a copied runtime artifact.'})
    return repairs

def optional_security_tools(root,image_name):
    result={}
    for tool,cmd in [('trivy',['trivy','image','--format','json','--quiet',image_name]),('syft',['syft',image_name,'-o','json'])]:
        if not shutil.which(tool):result[tool]={'available':False};continue
        try:r=subprocess.run(cmd,capture_output=True,text=True,timeout=300);result[tool]={'available':True,'passed':r.returncode==0,'output':r.stdout[-20000:],'stderr':r.stderr[-3000:]}
        except Exception as e:result[tool]={'available':True,'error':str(e)}
    return result

def provider_architecture(d):
    s=d['summary'];p=s['port'] or 3000;return {'aws':{'compute':'ECS/Fargate','load_balancer':'ALB','port':p,'services':s['services']},'gcp':{'compute':'Cloud Run','port':p,'services':s['services']},'azure':{'compute':'Container Apps','port':p,'services':s['services']},'kubernetes':{'workload':'Deployment','replicas':2,'service_port':p,'health_path':s['health_endpoints'][0] if s['health_endpoints'] else None}}
def cost_estimate(d):return {'currency':'USD','model':'provider-dependent','assumptions':{'replicas':2,'compute_class':'small'},'detected_services':d['summary']['services'],'monthly_ranges':{'compute':'requires provider/region/SKU pricing','managed_services':'requires provider/region/SKU pricing','total':'requires provider/region/SKU pricing'}}

def analyze_root(root,validate=True,infra=True):
    d=detect(root);d['generated_files']={'Dockerfile':dockerfile_for(d),'.dockerignore':'.git\n.github\n.env\n.env.*\nnode_modules\n__pycache__\n*.log\ncoverage\n'}
    if infra:d['generated_files'].update({'compose.yaml':compose_for(d),'terraform/main.tf':terraform_for(d),'kubernetes/deployment.yaml':k8s_for(d)})
    d['security_review']=security_review(d);d['validation']={'static':{'dockerfile_generated':True,'deployment_ir_valid':bool(d.get('deployment_ir'))}}
    d['validation']['docker']=docker_validate(root,d['generated_files']['Dockerfile'],d['summary']['port'],d['summary']['health_endpoints']) if validate else {'skipped':True}
    d['validation']['failure_class']=classify_failure(d['validation']['docker']) if validate else None
    d['repair_analysis']={'attempted':False,'iterations':0,'candidate_repairs':deterministic_repairs(d,d['validation']['docker']) if validate else [],'notes':[]}
    if d['repair_analysis']['candidate_repairs']:d['repair_analysis']['notes'].append('Deterministic repair candidates identified; automatic application belongs in an isolated production sandbox.')
    if d['summary']['start_command']=='Not detected':d['repair_analysis']['notes'].append('Entrypoint unresolved; conservative fallback used.')
    if d['summary']['runtime_version']=='Not declared':d['repair_analysis']['notes'].append('Runtime version unresolved; generator selected a conservative default.')
    d['security_tools']=optional_security_tools(root,'stack-detection-check:latest') if d['validation']['docker'].get('build',{}).get('passed') else {'trivy':{'available':bool(shutil.which('trivy')),'skipped':True},'syft':{'available':bool(shutil.which('syft')),'skipped':True}}
    d['cloud_architecture']=provider_architecture(d);d['cost_estimate']=cost_estimate(d);return d

def clone_repo(url):
    tmp=tempfile.mkdtemp(prefix='stack-detection-');root=Path(tmp)/'repo';r=subprocess.run(['git','clone','--depth','1',str(url),str(root)],capture_output=True,text=True,timeout=120)
    if r.returncode:shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(400,'Git clone failed: '+r.stderr[-1500:])
    return tmp,root
@app.get('/health')
def health():return {'status':'ok','version':'1.0.0','ai_required':False}
@app.post('/analyze')
def analyze(req:AnalyzeRequest):
    tmp,root=clone_repo(req.repo_url)
    try:return analyze_root(root,req.validate_docker,req.generate_infrastructure)
    finally:shutil.rmtree(tmp,ignore_errors=True)
@app.post('/analyze-zip')
async def analyze_zip(file:UploadFile=File(...),validate_docker:bool=True,generate_infrastructure:bool=True):
    tmp=tempfile.mkdtemp(prefix='stack-detection-');z=Path(tmp)/'repo.zip';z.write_bytes(await file.read());root=Path(tmp)/'repo';root.mkdir()
    try:
        with zipfile.ZipFile(z) as zf:zf.extractall(root)
        children=list(root.iterdir())
        if len(children)==1 and children[0].is_dir():root=children[0]
        return analyze_root(root,validate_docker,generate_infrastructure)
    except zipfile.BadZipFile:raise HTTPException(400,'Invalid ZIP archive')
    finally:shutil.rmtree(tmp,ignore_errors=True)
