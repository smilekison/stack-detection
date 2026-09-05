from pathlib import Path
import json
import re
from .repository_scope import select_unit, files_for_unit, read_unit_json, text as scoped_text
from .technology_catalog import SOURCE_EXTENSIONS, NODE_FRAMEWORKS, PY_FRAMEWORKS, GO_FRAMEWORKS, RUST_FRAMEWORKS, JVM_FRAMEWORKS, DOTNET_FRAMEWORKS, PHP_FRAMEWORKS, RUBY_FRAMEWORKS, ecosystem_for_manifest
from . import readme_evidence

LANGUAGE_NAMES={"javascript":"JavaScript","typescript":"TypeScript","python":"Python","go":"Go","rust":"Rust","java":"Java","kotlin":"Kotlin","scala":"Scala","csharp":"C#","fsharp":"F#","vbnet":"VB.NET","php":"PHP","ruby":"Ruby","elixir":"Elixir","erlang":"Erlang","swift":"Swift","dart":"Dart","haskell":"Haskell","clojure":"Clojure","c":"C","cpp":"C++","objective-c":"Objective-C","objective-cpp":"Objective-C++","lua":"Lua","perl":"Perl","r":"R","julia":"Julia","zig":"Zig","nim":"Nim","crystal":"Crystal","vlang":"V","solidity":"Solidity","assembly":"Assembly"}


def _read(repo,path): return repo.read(path) if path else ""
def _files(repo,unit): return files_for_unit(repo,unit)
def _module(path): return Path(path).with_suffix("").as_posix().replace("/",".")

def _port(content,default,readme_port=None):
    if readme_port and 1<=readme_port<=65535: return readme_port
    for pat in (r"--port(?:=|\s+)[\"']?(\d{2,5})",r"\bPORT\s*[:=]\s*[\"']?(\d{2,5})",r"localhost:(\d{2,5})",r"127\.0\.0\.1:(\d{2,5})"):
        m=re.search(pat,content or "",re.I)
        if m and 1<=int(m.group(1))<=65535:return int(m.group(1))
    return default

def _reconcile_command(manifest_command,readme_command):
    if not manifest_command:return readme_command,False
    if not readme_command:return manifest_command,False
    a,b=manifest_command.strip(),readme_command.strip()
    if a==b or a.split(" ",1)[0]==b.split(" ",1)[0]:return a,False
    return a,True

def _framework_from_dependencies(mapping, dependencies):
    for needle,name in mapping.items():
        if needle in dependencies:return name
    return None

def _node(repo,unit):
    manifests=unit.get("manifests",[]); package=next((f for f in manifests if Path(f).name=="package.json"),None)
    pkg=read_unit_json(repo,{**unit,"manifest":package}) if package else {}; deps={**(pkg.get("dependencies") or {}),**(pkg.get("devDependencies") or {})}; scripts=pkg.get("scripts") or {}
    framework=_framework_from_dependencies(NODE_FRAMEWORKS,deps); declaration=str(pkg.get("packageManager") or ""); pm=declaration.split("@",1)[0] if declaration else None; pm_version=declaration.split("@",1)[1] if "@" in declaration else ""
    files=set(_files(repo,unit)); locks={"npm":"package-lock.json","pnpm":"pnpm-lock.yaml","yarn":"yarn.lock","bun":"bun.lock"}
    if not pm: pm=next((x for x,l in locks.items() if l in files),"npm")
    lock=locks.get(pm)
    return package,pkg,deps,framework,scripts,pm,pm_version,lock if lock in files else None

def _python(repo,unit):
    files=_files(repo,unit); manifests=[f for f in files if Path(f).name in {"requirements.txt","requirements-dev.txt","pyproject.toml","Pipfile"}]
    parts=[]
    for f in manifests:
        for raw in _read(repo,f).splitlines():
            line=raw.split("#",1)[0].strip().lower()
            if line: parts.append(re.split(r"[<>=!~;\[]",line,1)[0].strip())
    framework=_framework_from_dependencies(PY_FRAMEWORKS,set(parts))
    if not framework:
        # Import evidence is only used as a confirmation after manifest dependencies are
        # exhausted. It is syntax/import based, not a whole-repository substring scan.
        source=scoped_text(repo,unit,suffixes={".py"})
        for module,name in (("django","Django"),("fastapi","FastAPI"),("flask","Flask"),("litestar","Litestar"),("sanic","Sanic"),("starlette","Starlette"),("quart","Quart")):
            if re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(module)}\b",source): framework=name; break
    return manifests,framework

def _go(repo,unit):
    files=_files(repo,unit); mains=[]
    for f in files:
        if not f.endswith(".go"):continue
        t=_read(repo,f)
        if re.search(r"(?m)^\s*package\s+main\b",t) and re.search(r"(?m)^\s*func\s+main\s*\(",t):mains.append(Path(f).parent.as_posix())
    dirs=sorted(set(mains)); target="." if "." in dirs else ("./"+next((d for d in dirs if d.startswith("cmd/")),dirs[0]).lstrip("./")) if dirs else None
    framework=None; mod=_read(repo,unit.get("manifest"))
    for needle,name in GO_FRAMEWORKS.items():
        if re.search(rf"(?m)^\s*{re.escape(needle)}\s+v",mod): framework=name;break
    return target,framework

def _rust(repo,unit):
    cargo=_read(repo,unit.get("manifest")); bins=re.findall(r"(?ms)^\s*\[\[bin\]\]\s*.*?^\s*name\s*=\s*[\"']([^\"']+)",cargo); nm=re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)",cargo); binary=bins[0] if bins else (nm.group(1) if nm else "app")
    framework=None
    for needle,name in RUST_FRAMEWORKS.items():
        if re.search(rf"{re.escape(needle)}(?:\s|=|\"|')",cargo):framework=name;break
    return binary,framework

def _jvm(repo,unit):
    manifest=unit.get("manifest"); t=_read(repo,manifest).lower(); name=Path(manifest).name if manifest else ""; framework=None
    for needle,label in JVM_FRAMEWORKS.items():
        if needle.lower() in t:framework=label;break
    return ("gradle" if name.startswith(("build.gradle","settings.gradle")) else "maven"),framework

def _dotnet(repo,unit):
    files=_files(repo,unit); project=next((f for f in files if f.lower().endswith((".csproj",".fsproj",".vbproj"))),None); t=_read(repo,project); tfm=re.search(r"<TargetFramework[^>]*>([^<]+)",t,re.I); framework="ASP.NET Core" if re.search(r"Microsoft\.AspNetCore|Microsoft\.NET\.Sdk\.Web",t,re.I) else None
    return project,(tfm.group(1) if tfm else None),(Path(project).stem if project else "app"),framework

def _php(repo,unit):
    files=_files(repo,unit); composer=next((f for f in files if Path(f).name=="composer.json"),unit.get("manifest")); content=_read(repo,composer); framework=None
    try:
        data=json.loads(content or "{}"); deps={**(data.get("require") or {}),**(data.get("require-dev") or {})}
        for needle,name in PHP_FRAMEWORKS.items():
            if needle in deps:framework=name;break
    except Exception: pass
    public=any(Path(f).name=="index.php" and "public" in Path(f).parts for f in files); index=any(Path(f).name=="index.php" for f in files)
    return composer,framework,public or index,public

def _ruby(repo,unit):
    files=set(_files(repo,unit)); gemfile=_read(repo,unit.get("manifest")); framework=None
    try:
        if re.search(r"gem\s+[\"']rails[\"']",gemfile,re.I):framework="Rails"
        elif re.search(r"gem\s+[\"']sinatra[\"']",gemfile,re.I):framework="Sinatra"
        elif re.search(r"gem\s+[\"']rack[\"']",gemfile,re.I):framework="Rack"
        elif re.search(r"gem\s+[\"']hanami",gemfile,re.I):framework="Hanami"
    except Exception:pass
    return framework,"bin/rails" in files or "config/application.rb" in files,"config.ru" in files

def _source_profile(repo,unit):
    counts={}
    for f in _files(repo,unit):
        lang=SOURCE_EXTENSIONS.get(Path(f).suffix.lower())
        if lang:counts[lang]=counts.get(lang,0)+1
    return sorted(((LANGUAGE_NAMES.get(k,k),v) for k,v in counts.items()),key=lambda x:-x[1])

def _services(repo,unit):
    t=scoped_text(repo,unit).lower(); rules={"PostgreSQL":("postgresql","psycopg","asyncpg","pgx","prisma","typeorm"),"MySQL":("mysql","mysql2","pymysql"),"MariaDB":("mariadb",),"MongoDB":("mongodb","mongoose","motor"),"Redis":("redis","ioredis","redis-py"),"RabbitMQ":("rabbitmq","pika","aio-pika"),"Kafka":("kafka","kafkajs","confluent-kafka"),"Elasticsearch":("elasticsearch","opensearch"),"S3/Object Storage":("boto3","aws-sdk","minio"),"Supabase":("supabase",),"Firebase":("firebase",),"Stripe":("stripe",),"DynamoDB":("dynamodb",),"SQLite":("sqlite","sqlite3")}
    return [{"name":n,"signals":[x for x in needles if x in t][:5]} for n,needles in rules.items() if any(x in t for x in needles)]
def _unit_text(repo,unit):return scoped_text(repo,unit)
def _health(repo,unit):
    t=_unit_text(repo,unit)
    return next((x for x in ("/health","/healthz","/ready","/readiness","/live") if x in t),None)


def analyze(repo,spec,result,target=None):
    selected,units,selection_error=select_unit(repo,preferred_root=target); checks=[]; warnings=[]; blockers=[]; decisions=[]
    def check(code,title,status,evidence=None,detail=""):
        x={"code":code,"title":title,"status":status,"evidence":evidence or [],"detail":detail};checks.append(x)
        if status=="blocker":blockers.append(x)
        elif status=="warning":warnings.append(x)
    result["repository_model"]={"units":units,"selected_unit":selected,"selection_error":selection_error}
    if selection_error:
        check("APPLICATION_BOUNDARY","Application target selection","blocker",[],"No unique deployable application unit can be selected; generation is blocked.")
        result["deep_analysis"]={"status":"blocked","confidence":0,"checks":checks,"warnings":warnings,"blockers":blockers,"decisions":decisions,"script_inventory":{}}
        spec.project.update({"application_units":units,"deep_analysis_status":"blocked","deep_analysis_confidence":0}); return result["deep_analysis"]
    root=selected.get("root") or "."; files=_files(repo,selected); eco=selected.get("ecosystem"); profile=_source_profile(repo,selected); readme=readme_evidence.parse(repo,selected)
    spec.project.update({"application_units":units,"selected_application":selected,"application_root":root,"technology_profile":profile,"files":files,"readme_evidence":readme})
    check("APPLICATION_BOUNDARY","Application boundary","pass",selected.get("manifests",[]) or files[:5],f"Deployment target: {selected.get('id') or '.'}.")
    framework=None; strategy=None; port=None; start=""; manifest=None; script_inventory={}; language=LANGUAGE_NAMES.get(eco,eco or "Unknown")
    if eco=="polyglot":
        candidates=[]
        for e in selected.get("ecosystems",[]):
            if e=="node":
                _,pkg,_,fw,scripts,pm,_,lock=_node(repo,selected); candidates.append((bool(scripts.get("build") or scripts.get("start") or scripts.get("dev")),e,fw,scripts))
            elif e=="python": ms,fw=_python(repo,selected); candidates.append((bool(ms),e,fw,{}))
            elif e=="go": target_path,fw=_go(repo,selected); candidates.append((bool(target_path),e,fw,{}))
            elif e=="rust": candidates.append((True,e,*_rust(repo,selected)[1:],{}))
            else:candidates.append((False,e,None,{}))
        viable=[x for x in candidates if x[0]]
        if len(viable)==1:eco=viable[0][1];language=LANGUAGE_NAMES.get(eco,eco)
        else:check("POLYGLOT_TARGET","Polyglot target","blocker",selected.get("manifests",[]),"Multiple ecosystems exist in the same application root and no single executable target is provable.")
    if not blockers and eco=="node":
        manifest,pkg,deps,scripts_framework,scripts,pm,pm_version,lock=_node(repo,selected); framework=scripts_framework; language="Node.js";script_inventory=scripts
        node_version=None
        for evidence_key in (".nvmrc",".node-version"):
            if evidence_key in files: node_version=_read(repo,evidence_key).strip().splitlines()[0].lstrip("v") or None; break
        node_version=node_version or ((pkg.get("engines") or {}).get("node") or None)
        if node_version is None: check("RUNTIME_VERSION","Node.js runtime version","blocker",[manifest],"No runtime version was explicitly declared by repository evidence; refusing to guess.")
        spec.runtime={"name":"Node.js","version":node_version or "Not resolved"};spec.package_managers=[{"name":pm,"ecosystem":"node","version":pm_version,"evidence_file":manifest}];spec.build.update({"project_dir":root,"dependency_manifest":manifest,"lockfile":lock,"container_command":f"{pm} run build" if scripts.get("build") else ""});check("MANIFEST","Node package manifest","pass",[manifest]);check("LOCKFILE","Dependency lockfile","pass" if lock else "warning",[lock] if lock else [],"Pinned install will use the detected lockfile." if lock else "No lockfile; reproducibility is weaker.");check("BUILD_SCRIPT","Production build script","pass" if scripts.get("build") else "blocker",[manifest],scripts.get("build") or "No build script.");check("FRAMEWORK","Framework identity","pass" if framework else "warning",[manifest],framework or "No known Node framework dependency was proven.")
        if framework=="Astro":
            cfgf=next((f for f in files if Path(f).name.startswith("astro.config.")),None);cfg=_read(repo,cfgf);adapter=next((x for dep,x in (("@astrojs/vercel","vercel"),("@astrojs/node","node"),("@astrojs/netlify","netlify"),("@astrojs/cloudflare","cloudflare")) if dep in deps or dep in cfg),"unknown");output="server" if re.search(r"output\s*:\s*['\"]server['\"]",cfg) else ("hybrid" if re.search(r"output\s*:\s*['\"]hybrid['\"]",cfg) else "static");port=_port(cfg,4321,readme.get("port"));check("FRAMEWORK_CONFIG","Astro adapter/output","pass" if cfgf else "warning",[cfgf] if cfgf else [],f"adapter={adapter}, output={output}")
            readme_prod=readme["commands"]["start"]["production"]
            if readme_prod:
                documented=readme_prod[0]["command"]
                if output=="server" and adapter=="vercel" and "astro dev" in documented.lower():
                    check("RUNTIME","README runtime command","warning",[readme_prod[0]["source"]],"README documents only the local development server for the Vercel server runtime; it is not promoted to production automatically.")
            if adapter=="node" and output in {"server","hybrid"}:strategy="node-standalone";start="node ./dist/server/entry.mjs";spec.build.update({"runtime_strategy":strategy,"adapter":"node"})
            elif adapter=="vercel" and output in {"server","hybrid"}:
                strategy=None;check("RUNTIME","Production runtime","blocker",[cfgf] if cfgf else [],"Astro server output targets Vercel serverless, but no Vercel-compatible local production runtime was proven. README/dev server is not substituted as production.")
            elif output=="static":strategy="static-preview";start=f"{pm} run preview -- --host 0.0.0.0 --port {port}";spec.build.update({"runtime_strategy":strategy,"adapter":adapter})
            else:check("RUNTIME","Production runtime","blocker",[cfgf] if cfgf else [],"No deterministic Astro runtime for the selected adapter/output.")
        elif framework in {"Next.js","Nuxt","NestJS","SvelteKit","Remix"} and scripts.get("start"):
            port=_port(_unit_text(repo,selected),3000,readme.get("port"));strategy="node-framework";start=f"{pm} run start -- --hostname 0.0.0.0 --port {port}" if framework in {"Next.js","Nuxt"} else scripts["start"];spec.build["runtime_strategy"]=strategy
        elif framework in {"Vite","React","Vue","Svelte","Angular","Gatsby","Docusaurus","Eleventy","SolidJS","Preact"} and scripts.get("build") and not scripts.get("start"):
            port=8080;output="build" if framework=="React" and "react-scripts" in deps else "dist";strategy="static-node";start='nginx -g "daemon off;"';spec.build.update({"runtime_strategy":strategy,"output":output})
        elif scripts.get("start"):
            port=_port(_unit_text(repo,selected),3000,readme.get("port"));strategy="node-script";start=scripts["start"];spec.build["runtime_strategy"]=strategy;readme_start=next((c["command"] for c in readme["commands"]["start"]["production"]),None);start,contradiction=_reconcile_command(start,readme_start)
            if contradiction:check("EVIDENCE_RECONCILIATION","Production command reconciliation","blocker",[manifest],f"README documents a different production command ('{readme_start}') than package.json ('{scripts['start']}').")
        elif readme["commands"]["start"]["production"]:
            readme_cmd=readme["commands"]["start"]["production"][0];start=readme_cmd["command"];port=_port(_unit_text(repo,selected),3000,readme["port"]);strategy="readme-documented";spec.build["runtime_strategy"]=strategy;check("RUNTIME","Production runtime (README)","pass",[readme_cmd["source"]],start)
        elif scripts.get("dev"):check("RUNTIME","Production runtime","blocker",[manifest],"Only a development script exists; refusing to convert it into production.")
        else:check("RUNTIME","Production runtime","blocker",[manifest],"No deterministic Node runtime command.")
    elif not blockers and eco=="python":
        manifests,framework=_python(repo,selected);manifest=manifests[0] if manifests else None;language="Python";spec.runtime={"name":"Python","version":None};spec.build.update({"dependency_manifest":manifest,"project_dir":root});check("MANIFEST","Python dependency manifest","pass" if manifest else "blocker",manifests[:10]);py=[f for f in files if f.endswith(".py")];entry=None;port=_port(_unit_text(repo,selected),8000,readme["port"])
        version=None
        for vf in (".python-version","runtime.txt"):
            if vf in files:version=_read(repo,vf).strip().splitlines()[0] or None;break
        if not version and "pyproject.toml" in files:
            m=re.search(r"requires-python\s*=\s*[\"']([^\"']+)",_read(repo,"pyproject.toml"),re.I);version=m.group(1) if m else None
        if not version:check("RUNTIME_VERSION","Python runtime version","blocker",manifests,"No explicit Python runtime version was proven; refusing to guess.")
        spec.runtime["version"]=version or "Not resolved"
        if framework=="Django":entry=next((f for f in py if Path(f).name=="wsgi.py"),None);strategy="python-gunicorn";start=f"gunicorn {_module(entry)}:application --bind 0.0.0.0:{port}" if entry else ""
        elif framework in {"FastAPI","Litestar","Sanic","Starlette","Quart"}:entry=next((f for f in py if Path(f).name in {"main.py","app.py","server.py","application.py"} and re.search(r"(?:FastAPI|Litestar|Sanic|Starlette|Quart)\s*\(",_read(repo,f),re.I)),None);strategy="python-uvicorn";start=f"uvicorn {_module(entry)}:app --host 0.0.0.0 --port {port}" if entry else ""
        elif framework=="Flask":entry=next((f for f in py if Path(f).name in {"main.py","app.py","application.py"} and re.search(r"\bapp\s*=",_read(repo,f))),None);strategy="python-gunicorn";start=f"gunicorn {_module(entry)}:app --bind 0.0.0.0:{port}" if entry else ""
        readme_start=next((c for c in readme["commands"]["start"]["production"]),None)
        if entry and readme_start:
            start,contradiction=_reconcile_command(readme_start["command"],start)
            if contradiction:check("EVIDENCE_RECONCILIATION","Production command reconciliation","blocker",[entry,readme_start["source"]],f"README documents '{readme_start['command']}' while source-derived runtime resolves '{start}'.")
        if entry:spec.build.update({"runtime_strategy":strategy,"entrypoint":entry});check("ENTRYPOINT","Python web entrypoint","pass",[entry],start)
        elif readme_start:strategy="readme-documented";start=readme_start["command"];spec.build["runtime_strategy"]=strategy;check("ENTRYPOINT","Python web entrypoint (README)","pass",[readme_start["source"]],start)
        else:check("ENTRYPOINT","Python web entrypoint","blocker",py[:10],f"No deterministic web entrypoint for framework={framework or 'Unknown'}.")
    elif not blockers and eco=="go":
        target_path,framework=_go(repo,selected);language="Go";gm=_read(repo,selected.get("manifest"));m=re.search(r"(?m)^go\s+([0-9.]+)",gm);version=m.group(1) if m else None;spec.runtime={"name":"Go","version":version or "Not resolved"};port=_port(_unit_text(repo,selected),8080,readme["port"])
        if not version:check("RUNTIME_VERSION","Go runtime version","blocker",[selected.get("manifest")],"No Go version directive was proven; refusing to guess.")
        if target_path:strategy="go-binary";start="/app";spec.build.update({"runtime_strategy":strategy,"source_package":target_path,"container_command":f'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app {target_path}'})
        else:check("ENTRYPOINT","Go main package","blocker",[],"No package main + func main entrypoint.")
    elif not blockers and eco=="rust":
        binary,framework=_rust(repo,selected);language="Rust";port=_port(_unit_text(repo,selected),8080,readme["port"]);strategy="rust-binary";start=f"/app/{binary}";spec.runtime={"name":"Rust","version":"Not resolved"};cargo=_read(repo,selected.get("manifest"));version=re.search(r"^rust-version\s*=\s*[\"']([^\"']+)",cargo,re.M);spec.runtime["version"]=version.group(1) if version else "Not resolved";spec.build.update({"runtime_strategy":strategy,"binary":binary,"container_command":"cargo build --release"});
        if not version:check("RUNTIME_VERSION","Rust runtime version","blocker",[selected.get("manifest")],"No rust-version was declared; refusing to guess.")
    elif not blockers and eco in {"jvm","scala"}:
        manager,framework=_jvm(repo,selected);language="JVM";spec.runtime={"name":"JDK","version":"Not resolved"};port=_port(_unit_text(repo,selected),8080,readme["port"]);manifest_text=_read(repo,selected.get("manifest"));java_version=re.search(r"<java.version>\s*([^<]+)",manifest_text,re.I) or re.search(r"maven.compiler.release>\s*([^<]+)",manifest_text,re.I) or re.search(r"sourceCompatibility\s*=\s*['\"]?([0-9]+)",manifest_text,re.I);version=java_version.group(1) if java_version else None
        if not version:check("RUNTIME_VERSION","JVM runtime version","blocker",[selected.get("manifest")],"No JVM version was declared; refusing to guess.")
        else:spec.runtime["version"]=version
        if framework in {"Spring Boot","Quarkus","Micronaut","Ktor","Play Framework"}:strategy="jvm-jar";start="java -jar /app/app.jar";spec.build.update({"runtime_strategy":strategy,"jvm_manager":manager})
        else:check("ENTRYPOINT","JVM web runtime","blocker",[selected.get("manifest")],"No deterministic supported JVM web framework/runtime identified.")
    elif not blockers and eco in {"dotnet","fsharp","vbnet"}:
        project,tfm,assembly,framework=_dotnet(repo,selected);language=LANGUAGE_NAMES.get(eco,eco);port=_port(_unit_text(repo,selected),8080,readme["port"])
        if not tfm:check("RUNTIME_VERSION",".NET runtime version","blocker",[project] if project else [],"No TargetFramework was declared; refusing to guess.")
        spec.runtime={"name":".NET","version":tfm or "Not resolved"}
        if project and framework:strategy="dotnet-aspnet";start=f"dotnet /app/{assembly}.dll";spec.build.update({"runtime_strategy":strategy,"project_file":project,"assembly":assembly})
        else:check("ENTRYPOINT",".NET web runtime","blocker",[project] if project else [],"No deterministic ASP.NET web project identified.")
    elif not blockers and eco=="php":
        composer,framework,web,public=_php(repo,selected);language="PHP";strategy="php-apache" if web else None;start="apache2-foreground" if web else "";port=80;spec.runtime={"name":"PHP","version":"8.3"};spec.build.update({"runtime_strategy":strategy,"document_root":"public" if public else ".","dependency_manifest":composer}) if strategy else None
        if not strategy:check("ENTRYPOINT","PHP web entrypoint","blocker",[composer] if composer else [],"No deterministic PHP web entrypoint.")
    elif not blockers and eco=="ruby":
        framework,rails,rack=_ruby(repo,selected);language="Ruby";port=_port(_unit_text(repo,selected),3000,readme["port"]);readme_start=next((c for c in readme["commands"]["start"]["production"]),None)
        if rails:strategy="ruby-rails";start=f"bundle exec rails server -b 0.0.0.0 -p {port}"
        elif rack:strategy="ruby-rack";start=f"bundle exec rackup -o 0.0.0.0 -p {port}"
        elif readme_start:strategy="readme-documented";start=readme_start["command"]
        else:check("ENTRYPOINT","Ruby web entrypoint","blocker",[],"No Rails/Rack entrypoint or README production command.")
        spec.runtime={"name":"Ruby","version":"Not resolved"};gem=_read(repo,selected.get("manifest"));version=re.search(r"ruby\s+[\"']([0-9][^\"']*)",gem,re.I);spec.runtime["version"]=version.group(1) if version else "Not resolved";spec.build["runtime_strategy"]=strategy
        if not version:check("RUNTIME_VERSION","Ruby runtime version","blocker",[selected.get("manifest")],"No Ruby runtime version was declared; refusing to guess.")
    elif not blockers:check("UNSUPPORTED_TARGET","Deployment strategy","blocker",selected.get("manifests",[]),f"Technology {language} is recognized but has no verified deployment strategy.")
    if not blockers and strategy:
        spec.processes[0]["start_command"]=start;spec.network.update({"port":port,"health_endpoint":_health(repo,selected)});spec.services=_services(repo,selected);spec.frameworks=[{"name":framework,"score":95,"evidence":"scoped application manifest/source"}] if framework else [];spec.languages=[{"name":language,"score":95,"confidence":95.0}];spec.project["container_decisions"]=[{"strategy":strategy,"application_root":root,"manifest":manifest or selected.get("manifest")},{"readme_documents":readme.get("documents",[])}];decisions.extend(spec.project["container_decisions"]);check("RUNTIME","Production runtime","pass",[manifest] if manifest else [],f"Resolved strategy={strategy}, start={start}, port={port}.")
    result["summary"].update({"primary_language":language,"runtime":spec.runtime.get("name",language),"runtime_version":spec.runtime.get("version","Not declared"),"framework":framework or "Unknown","package_manager":spec.package_managers[0]["name"] if spec.package_managers else "Unknown","start_command":start or "Not detected","port":port,"health_endpoint":spec.network.get("health_endpoint"),"services":[x["name"] for x in spec.services]})
    result["languages"]=spec.languages;result["frameworks"]=spec.frameworks;deep={"status":"ready" if not blockers else "blocked","confidence":96 if not blockers else 0,"checks":checks,"warnings":warnings,"blockers":blockers,"decisions":decisions,"script_inventory":script_inventory,"technology_profile":profile,"readme":readme};result["deep_analysis"]=deep;spec.project.update({"deep_analysis_status":deep["status"],"deep_analysis_confidence":deep["confidence"]});return deep
