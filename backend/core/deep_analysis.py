from pathlib import Path
import re

LOCKFILES={'npm':'package-lock.json','pnpm':'pnpm-lock.yaml','yarn':'yarn.lock','bun':'bun.lock'}
def _pkg(r): return r.json('package.json') if 'package.json' in r.file_set else {}
def _first(r,names): return next((f for f in r.files if Path(f).name in names),None)
def _port(text,default=None):
    for p in (r'(?i)--port(?:=|\s+)(?:["\']?)(\d{2,5})',r'(?i)\bPORT\s*[:=]\s*["\']?(\d{2,5})',r'(?i)localhost:(\d{2,5})',r'(?i)127\.0\.0\.1:(\d{2,5})'):
        m=re.search(p,text or '')
        if m:
            n=int(m.group(1))
            if 1<=n<=65535:return n
    return default
def _script(pkg,n): return (pkg.get('scripts') or {}).get(n)
def _static(r,primary,framework):
    server_ext={'.py','.go','.rs','.java','.kt','.cs','.php','.rb','.ex','.exs'}
    return 'package.json' not in r.file_set and framework in {'Unknown',''} and any(Path(f).name=='index.html' for f in r.files) and not any(Path(f).suffix in server_ext for f in r.files)

def analyze(repo,spec,result):
    checks=[];warnings=[];blockers=[];decisions=[];pkg=_pkg(repo);primary=result['summary'].get('primary_language');framework=result['summary'].get('framework');pm=result['summary'].get('package_manager');spec.project['files']=list(repo.files)
    def check(code,title,status,evidence=None,detail=''):
        x={'code':code,'title':title,'status':status,'evidence':evidence or [],'detail':detail};checks.append(x)
        if status=='blocker':blockers.append(x)
        elif status=='warning':warnings.append(x)
    if _static(repo,primary,framework):
        spec.runtime={'name':'Static Web','version':'nginx:1.27-alpine'};spec.frameworks=[];spec.package_managers=[];spec.build={'command':'none','runtime_strategy':'static-nginx','output':'repository-root'};spec.processes=[{'role':'web','start_command':'nginx -g "daemon off;"'}];spec.network.update({'port':80,'health_endpoint':'/'})
        check('STATIC_ENTRYPOINT','Static HTML entrypoint','pass',[f for f in repo.files if Path(f).name=='index.html'][:3],'Static site detected; no application runtime is required.');check('STATIC_RUNTIME','Static runtime','pass',[],'Nginx will serve repository content.');decisions += [{'code':'TARGET','decision':'static-nginx','reason':'No server runtime or package build system detected.'},{'code':'PORT','decision':80,'reason':'Nginx default HTTP port.'}]
    elif primary in {'JavaScript','TypeScript'} or 'package.json' in repo.file_set:
        scripts=pkg.get('scripts') or {};lock=LOCKFILES.get(pm);has_lock=bool(lock and lock in repo.file_set);check('NODE_MANIFEST','Node package manifest','pass' if 'package.json' in repo.file_set else 'blocker',['package.json'] if 'package.json' in repo.file_set else [],'package.json required for deterministic Node builds.')
        if pm in LOCKFILES: check('LOCKFILE_MATCH','Package manager and lockfile','pass' if has_lock else 'warning',[lock] if has_lock else ['package.json'],f'{pm} lockfile '+('present.' if has_lock else 'missing; npm install fallback will be used.'))
        build=scripts.get('build');start=scripts.get('start');dev=scripts.get('dev');check('BUILD_SCRIPT','Production build command','pass' if build else 'blocker',['package.json'],build or 'No build script found.');check('START_SCRIPT','Runtime command','pass' if start else ('warning' if dev else 'blocker'),['package.json'],start or dev or 'No start/dev script found.');spec.runtime['version']=str((pkg.get('engines') or {}).get('node','20')).lstrip('v').split()[0];spec.build['container_command']=f'{pm if pm not in {"Unknown","npm"} else "npm"} run build' if build else ''
        if framework=='Astro':
            cf=_first(repo,{'astro.config.mjs','astro.config.js','astro.config.ts','astro.config.cjs'});cfg=repo.read(cf) if cf else '';deps={**pkg.get('dependencies',{}),**pkg.get('devDependencies',{})};adapter=next((n for d,n in [('@astrojs/vercel','vercel'),('@astrojs/node','node'),('@astrojs/netlify','netlify'),('@astrojs/cloudflare','cloudflare')] if d in deps or d in cfg),'unknown');output='server' if re.search(r"output\s*:\s*['\"]server['\"]",cfg) else ('hybrid' if re.search(r"output\s*:\s*['\"]hybrid['\"]",cfg) else 'static');ev=[x for x in (cf,'package.json') if x];check('FRAMEWORK_CONFIG','Framework adapter/output','pass' if cf else 'warning',ev,f'Astro adapter={adapter}, output={output}.')
            if adapter=='vercel' and output in {'server','hybrid'}:
                if not dev: check('RUNTIME_COMPATIBILITY','Container runtime compatibility','blocker',ev,'Vercel SSR adapter has no deterministic local container runtime without a dev command.')
                else: spec.build.update({'runtime_strategy':'dev-server-fallback','adapter':'vercel-serverless','preview_supported':False});spec.processes[0]['start_command']=f'{pm if pm not in {"Unknown","npm"} else "npm"} run dev -- --host 0.0.0.0 --port {_port(cfg) or _port(dev) or 4321}';check('RUNTIME_COMPATIBILITY','Container runtime compatibility','pass',ev,'Host-specific Vercel SSR uses repository dev server for local container verification.')
            elif adapter=='node' and output in {'server','hybrid'}: spec.build.update({'runtime_strategy':'node-standalone','adapter':'node'});check('RUNTIME_COMPATIBILITY','Container runtime compatibility','pass',ev,'Astro Node adapter provides a standalone Node runtime.')
            elif output=='static': spec.build.update({'runtime_strategy':'static-preview','adapter':adapter});check('RUNTIME_COMPATIBILITY','Container runtime compatibility','pass',ev,'Static Astro output can be served by preview.')
            port=_port(cfg) or _port(dev) or 4321;spec.network['port']=port;decisions.append({'code':'PORT','decision':port,'reason':'Framework config/script/default.'})
        elif framework in {'Next.js','Nuxt','NestJS'}:
            port=_port(repo.corpus,3000);spec.network['port']=port
            if start: spec.processes[0]['start_command']=f'{pm if pm not in {"Unknown","npm"} else "npm"} run start -- --hostname 0.0.0.0 --port {port}' if framework in {'Next.js','Nuxt'} else f'{pm if pm not in {"Unknown","npm"} else "npm"} run start'
            spec.build['runtime_strategy']='node-framework';decisions.append({'code':'PORT','decision':port,'reason':'Framework convention/source configuration.'})
        else:
            port=_port(repo.corpus,3000);spec.network['port']=port
            if start: spec.processes[0]['start_command']=start
            spec.build['runtime_strategy']='node-script' if start else 'unknown'
    elif primary=='Python':
        manifests=[x for x in ('requirements.txt','pyproject.toml','Pipfile') if x in repo.file_set];check('PYTHON_MANIFEST','Python dependency manifest','pass' if manifests else 'blocker',manifests,'Dependency manifest detected.' if manifests else 'No supported dependency manifest.');port=_port(repo.corpus,8000);fw=result['summary'].get('framework');start=None
        if fw=='Django':
            wsgi=next((f for f in repo.files if f.endswith('wsgi.py')),None);mod=Path(wsgi).with_suffix('').as_posix().replace('/','.') if wsgi else None;start=f'gunicorn {mod}:application --bind 0.0.0.0:{port}' if mod else None;spec.build['runtime_strategy']='python-gunicorn'
        elif fw in {'FastAPI','Litestar','Sanic'}:
            f=next((x for x in repo.files if Path(x).name in {'main.py','app.py','server.py'}),None);mod=Path(f).with_suffix('').as_posix().replace('/','.') if f else None;start=f'uvicorn {mod}:app --host 0.0.0.0 --port {port}' if mod else None;spec.build['runtime_strategy']='python-uvicorn'
        if start:spec.processes[0]['start_command']=start;spec.network['port']=port;check('PYTHON_ENTRYPOINT','Production web entrypoint','pass',[],start)
        else:check('PYTHON_ENTRYPOINT','Production web entrypoint','blocker',[],'No deterministic WSGI/ASGI entrypoint was identified.')
    elif primary=='Go':
        check('GO_MODULE','Go module','pass' if 'go.mod' in repo.file_set else 'blocker',['go.mod'] if 'go.mod' in repo.file_set else [],'go.mod controls dependencies.');spec.build.update({'runtime_strategy':'go-binary','container_command':'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .'});spec.processes[0]['start_command']='/app';spec.network['port']=_port(repo.corpus,8080)
    elif primary=='Rust':
        check('RUST_MANIFEST','Cargo manifest','pass' if 'Cargo.toml' in repo.file_set else 'blocker',['Cargo.toml'] if 'Cargo.toml' in repo.file_set else [],'Cargo.toml controls build.');cargo=repo.read('Cargo.toml') if 'Cargo.toml' in repo.file_set else '';m=re.search(r'^\s*name\s*=\s*["\']([^"\']+)',cargo,re.M);binary=m.group(1) if m else Path(repo.root).name.replace('-','_');spec.build.update({'runtime_strategy':'rust-binary','binary':binary,'container_command':'cargo build --release'});spec.processes[0]['start_command']=f'/app/{binary}';spec.network['port']=_port(repo.corpus,8080)
    elif primary=='Java':
        manifest='pom.xml' if 'pom.xml' in repo.file_set else ('build.gradle' if 'build.gradle' in repo.file_set else 'build.gradle.kts' if 'build.gradle.kts' in repo.file_set else None);check('JVM_BUILD','JVM build manifest','pass' if manifest else 'blocker',[manifest] if manifest else [],'Maven/Gradle build detected.' if manifest else 'No JVM build manifest.')
        if manifest and 'spring-boot' in repo.lower:spec.build.update({'runtime_strategy':'jvm-jar','container_command':'mvn -B -DskipTests package'});spec.processes[0]['start_command']='java -jar /app/app.jar';spec.network['port']=_port(repo.corpus,8080)
        else:check('JVM_ENTRYPOINT','JVM runtime entrypoint','blocker',[],'No deterministic web runtime artifact was identified.')
    elif primary=='C#':
        cs=next((f for f in repo.files if f.endswith('.csproj')),None);check('DOTNET_PROJECT','.NET project','pass' if cs else 'blocker',[cs] if cs else [],'Project file detected.' if cs else 'No .csproj found.');
        if cs:
            name=Path(cs).stem;spec.build.update({'runtime_strategy':'dotnet-publish','project_file':cs,'assembly':name});spec.processes[0]['start_command']=f'dotnet /app/{name}.dll';spec.network['port']=_port(repo.corpus,8080)
    elif primary=='PHP':
        check('PHP_COMPOSER','Composer manifest','pass' if 'composer.json' in repo.file_set else 'warning',['composer.json'] if 'composer.json' in repo.file_set else [],'Composer dependency manifest.');root='public' if any(f.startswith('public/') for f in repo.files) else '';entry=any(Path(f).name=='index.php' for f in repo.files);check('PHP_ENTRYPOINT','PHP web document root','pass' if root or entry else 'blocker',[],'PHP web entrypoint identified.' if root or entry else 'No deterministic document root.')
        if root or entry:spec.build.update({'runtime_strategy':'php-apache','document_root':root or '.'});spec.network['port']=80;spec.processes[0]['start_command']='apache2-foreground'
    elif primary=='Ruby':
        check('RUBY_BUNDLE','Bundler manifest','pass' if 'Gemfile' in repo.file_set else 'blocker',['Gemfile'] if 'Gemfile' in repo.file_set else [],'Gemfile detected.');spec.build['runtime_strategy']='ruby-rack' if 'config.ru' in repo.file_set else 'unknown';spec.network['port']=_port(repo.corpus,3000)
        if 'config.ru' in repo.file_set:spec.processes[0]['start_command']=f'bundle exec rackup -o 0.0.0.0 -p {spec.network["port"]}'
    else: check('UNSUPPORTED_TARGET','Deployable target identification','blocker',[],f'No deterministic deployment strategy for {primary}.')
    if spec.project.get('monorepo'):check('MONOREPO_TARGET','Monorepo deployment target','blocker',spec.infrastructure.get('files',[]),'Monorepo detected but no deployable workspace was selected; generation will not guess.')
    if 'Dockerfile' in repo.file_set:check('EXISTING_DOCKERFILE','Existing Dockerfile','warning',['Dockerfile'],'Existing Dockerfile is evidence only.')
    if spec.environment.get('secret_files'):check('SECRET_FILES','Repository secret files','warning',spec.environment['secret_files'],'Secret-bearing files must not enter an image.')
    confidence=100-min(20,len(warnings)*3) if not blockers else 0;result['deep_analysis']={'status':'ready' if not blockers else 'blocked','confidence':confidence,'checks':checks,'warnings':warnings,'blockers':blockers,'decisions':decisions,'script_inventory':{k:_script(pkg,k) for k in ('build','start','dev','preview','serve') if _script(pkg,k)}};spec.project.update({'deep_analysis_status':result['deep_analysis']['status'],'deep_analysis_confidence':confidence,'container_decisions':decisions});return result['deep_analysis']
