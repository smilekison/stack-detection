"""Universal, repository-scoped deployment analysis.

This is the only layer allowed to turn repository evidence into a deployment strategy.
It is deliberately conservative: it recognizes a broad technology universe, but only
returns ``ready`` when build/runtime behavior is deterministic for the generator.
Unknown, unsupported, mixed, or ambiguous targets become explicit blockers.
"""
from pathlib import Path
import json
import re
from .repository_scope import select_unit, discover_units, files_for_unit, read_unit_json, text as scoped_text
from .technology_catalog import SOURCE_EXTENSIONS, NODE_FRAMEWORKS, PY_FRAMEWORKS, GO_FRAMEWORKS, RUST_FRAMEWORKS, JVM_FRAMEWORKS, DOTNET_FRAMEWORKS, PHP_FRAMEWORKS, RUBY_FRAMEWORKS, ELIXIR_FRAMEWORKS, STATIC_MARKERS, ecosystem_for_manifest
from . import readme_evidence

LANGUAGE_NAMES = {
    "javascript":"JavaScript", "typescript":"TypeScript", "python":"Python", "go":"Go", "rust":"Rust", "java":"Java",
    "kotlin":"Kotlin", "scala":"Scala", "csharp":"C#", "fsharp":"F#", "vbnet":"VB.NET", "php":"PHP", "ruby":"Ruby",
    "elixir":"Elixir", "erlang":"Erlang", "swift":"Swift", "dart":"Dart", "haskell":"Haskell", "clojure":"Clojure",
    "c":"C", "cpp":"C++", "objective-c":"Objective-C", "objective-cpp":"Objective-C++", "lua":"Lua", "perl":"Perl",
    "r":"R", "julia":"Julia", "zig":"Zig", "nim":"Nim", "crystal":"Crystal", "vlang":"V", "solidity":"Solidity", "assembly":"Assembly",
}

MANIFEST_BY_ECOSYSTEM = {}
for p in ("package.json", "deno.json", "deno.jsonc", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "Pipfile", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "build.sbt", "composer.json", "Gemfile", "mix.exs", "rebar.config", "Package.swift", "pubspec.yaml", "stack.yaml", "CMakeLists.txt", "meson.build", "vcpkg.json", "conanfile.txt", "conanfile.py", "project.clj", "deps.edn"):
    eco = ecosystem_for_manifest(p)
    if eco: MANIFEST_BY_ECOSYSTEM.setdefault(eco, []).append(p)


def _read(repo, path): return repo.read(path) if path else ""

def _files(repo, unit): return files_for_unit(repo, unit)

def _port(content, default):
    for pat in (r"(?i)--port(?:=|\s+)[\"']?(\d{2,5})", r"(?i)\bPORT\s*[:=]\s*[\"']?(\d{2,5})", r"(?i)localhost:(\d{2,5})", r"(?i)127\.0\.0\.1:(\d{2,5})"):
        m = re.search(pat, content or "")
        if m and 1 <= int(m.group(1)) <= 65535: return int(m.group(1))
    return default


def _module(path): return Path(path).with_suffix("").as_posix().replace("/", ".")


def _reconcile_command(manifest_command, readme_command):
    """Reconcile a manifest/source-resolved command against a README-documented one.

    Evidence reconciliation (PROGRAM.md Priority 2), scoped to the single fact this
    engine currently resolves twice: the production start command. Agreement, or a
    README command confirming/extending the same tool, keeps the resolved command;
    a README command naming a genuinely different tool with no manifest command is
    accepted as the fallback; two different tools both claimed as authoritative is a
    contradiction that must block rather than silently pick one.
    """
    if not manifest_command: return readme_command, False
    if not readme_command: return manifest_command, False
    a, b = manifest_command.strip(), readme_command.strip()
    if a == b or a.split(" ", 1)[0] == b.split(" ", 1)[0]: return a, False
    return a, True

def _framework_from_text(mapping, manifest_text, source_text=""):
    """Manifest/dependency evidence is checked before falling back to source text.

    Source text alone is Tier 5 (generic textual mentions) and must not outrank a
    real dependency declaration - a detector-like file that merely lists framework
    names as data (e.g. a technology catalog) must never win over the manifest.
    """
    for text in (manifest_text, source_text):
        low = (text or "").lower()
        for needle, name in mapping.items():
            if needle.lower() in low: return name
    return None

def _node(repo, unit):
    manifests = unit.get("manifests", [])
    package = next((f for f in manifests if Path(f).name == "package.json"), None)
    pkg = read_unit_json(repo, {**unit, "manifest": package}) if package else {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    framework = next((name for dep, name in NODE_FRAMEWORKS.items() if dep in deps), None)
    scripts = pkg.get("scripts") or {}
    declaration = str(pkg.get("packageManager") or "")
    pm = declaration.split("@", 1)[0] if declaration else None
    pm_version = declaration.split("@", 1)[1] if "@" in declaration else ""
    files = set(_files(repo, unit))
    locks = {"npm":"package-lock.json", "pnpm":"pnpm-lock.yaml", "yarn":"yarn.lock", "bun":"bun.lock"}
    if not pm: pm = next((x for x, lock in locks.items() if lock in files), "npm")
    lock = locks.get(pm)
    return package, pkg, deps, framework, scripts, pm, pm_version, lock if lock in files else None


def _python(repo, unit):
    files = _files(repo, unit); manifests = [f for f in files if Path(f).name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile"}]
    content = "\n".join(_read(repo, f) for f in manifests).lower(); source = scoped_text(repo, unit, suffixes={".py"})
    framework = _framework_from_text(PY_FRAMEWORKS, content, source)
    return manifests, framework


def _go(repo, unit):
    files = _files(repo, unit); mains=[]
    for f in files:
        if not f.endswith(".go"): continue
        t=_read(repo,f)
        if re.search(r"(?m)^\s*package\s+main\b",t) and re.search(r"(?m)^\s*func\s+main\s*\(",t): mains.append(Path(f).parent.as_posix())
    dirs=sorted(set(mains)); target="." if "." in dirs else ("./"+next((d for d in dirs if d.startswith("cmd/")),dirs[0]).lstrip("./")) if dirs else None
    mod=_read(repo,unit.get("manifest")); framework=_framework_from_text(GO_FRAMEWORKS,mod)
    return target, framework


def _rust(repo, unit):
    cargo=_read(repo,unit.get("manifest")); bins=re.findall(r"(?ms)^\s*\[\[bin\]\]\s*.*?^\s*name\s*=\s*[\"']([^\"']+)",cargo)
    nm=re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)",cargo); binary=bins[0] if bins else (nm.group(1) if nm else "app")
    source=scoped_text(repo,unit,suffixes={".rs"}); framework=_framework_from_text(RUST_FRAMEWORKS,cargo,source)
    return binary,framework


def _jvm(repo,unit):
    manifest=unit.get("manifest"); t=_read(repo,manifest).lower(); name=Path(manifest).name if manifest else ""
    framework=_framework_from_text(JVM_FRAMEWORKS,t,scoped_text(repo,unit,suffixes={".java",".kt",".scala"}))
    return ("gradle" if name.startswith(("build.gradle","settings.gradle")) else "maven"), framework


def _dotnet(repo,unit):
    files=_files(repo,unit); project=next((f for f in files if f.lower().endswith((".csproj",".fsproj",".vbproj"))),None)
    t=_read(repo,project); tfm=re.search(r"<TargetFramework[^>]*>([^<]+)",t,re.I); framework=_framework_from_text(DOTNET_FRAMEWORKS,t,scoped_text(repo,unit,suffixes={".cs"}))
    return project, (tfm.group(1) if tfm else "net8.0"), (Path(project).stem if project else "app"), framework


def _php(repo,unit):
    files=_files(repo,unit); composer=next((f for f in files if Path(f).name=="composer.json"),unit.get("manifest")); content=_read(repo,composer); framework=_framework_from_text(PHP_FRAMEWORKS,content,scoped_text(repo,unit,suffixes={".php"}))
    public=any(Path(f).name=="index.php" and "public" in Path(f).parts for f in files); index=any(Path(f).name=="index.php" for f in files)
    return composer, framework, (public or index), public


def _ruby(repo,unit):
    files=set(_files(repo,unit)); source=scoped_text(repo,unit,suffixes={".rb"}); framework=_framework_from_text(RUBY_FRAMEWORKS,"",source+"\n"+" ".join(files)); return framework, ("bin/rails" in files or "config/application.rb" in files), ("config.ru" in files)


def _source_profile(repo, unit):
    counts={}
    for f in _files(repo,unit):
        lang=SOURCE_EXTENSIONS.get(Path(f).suffix.lower())
        if lang: counts[lang]=counts.get(lang,0)+1
    return sorted(((LANGUAGE_NAMES.get(k,k),v) for k,v in counts.items()),key=lambda x:-x[1])


def _services(repo,unit):
    t=_unit_text(repo,unit).lower(); rules={"PostgreSQL":("postgresql","postgres","psycopg","asyncpg","pgx","prisma","typeorm"),"MySQL":("mysql","mysql2","pymysql"),"MariaDB":("mariadb",),"MongoDB":("mongodb","mongoose","motor"),"Redis":("redis","ioredis","redis-py"),"RabbitMQ":("rabbitmq","amqp","pika","aio-pika"),"Kafka":("kafka","kafkajs","confluent-kafka"),"Elasticsearch":("elasticsearch","opensearch"),"S3/Object Storage":("s3","aws-sdk","boto3","minio"),"Supabase":("supabase",),"Firebase":("firebase",),"Stripe":("stripe",),"DynamoDB":("dynamodb",),"SQLite":("sqlite","sqlite3")}
    return [{"name":n,"signals":[x for x in needles if x in t][:5]} for n,needles in rules.items() if any(x in t for x in needles)]


def _unit_text(repo,unit): return scoped_text(repo,unit)

def _health(repo,unit):
    t=_unit_text(repo,unit)
    return next((x for x in ("/health","/healthz","/ready","/readiness","/live") if x in t),None)


def analyze(repo,spec,result,target=None):
    selected,units,selection_error=select_unit(repo,preferred_root=target)
    checks=[]; warnings=[]; blockers=[]; decisions=[]
    def check(code,title,status,evidence=None,detail=""):
        x={"code":code,"title":title,"status":status,"evidence":evidence or [],"detail":detail};checks.append(x)
        (blockers if status=="blocker" else warnings if status=="warning" else []).append(x)
    result["repository_model"]={"units":units,"selected_unit":selected,"selection_error":selection_error}
    if selection_error:
        check("APPLICATION_BOUNDARY","Application target selection","blocker",[],"No unique deployable application unit can be selected; AutoDeploy will not guess.")
        result["deep_analysis"]={"status":"blocked","confidence":0,"checks":checks,"warnings":warnings,"blockers":blockers,"decisions":decisions,"script_inventory":{}}
        spec.project.update({"application_units":units,"deep_analysis_status":"blocked","deep_analysis_confidence":0})
        return result["deep_analysis"]

    root=selected.get("root") or "."; files=_files(repo,selected); eco=selected.get("ecosystem"); profile=_source_profile(repo,selected)
    readme=readme_evidence.parse(repo,selected)
    spec.project.update({"application_units":units,"selected_application":selected,"application_root":root,"technology_profile":profile,"files":files})
    check("APPLICATION_BOUNDARY","Application boundary","pass",selected.get("manifests",[]) or files[:5],f"Deployment target: {selected.get('id') or '.'}.")

    framework=None; strategy=None; port=None; start=""; manifest=None; script_inventory={}; language=LANGUAGE_NAMES.get(eco,eco or "Unknown")
    if eco=="polyglot":
        # A polyglot unit is allowed only when exactly one manifest supplies a deterministic web build/runtime.
        candidates=[]
        for e in selected.get("ecosystems",[]):
            if e=="node":
                _,pkg,_,fw,scripts,pm,_,lock=_node(repo,selected); candidates.append((bool(scripts.get("build") or scripts.get("start") or scripts.get("dev")),e,fw,scripts))
            elif e=="python":
                ms,fw=_python(repo,selected); candidates.append((bool(ms),e,fw,{}))
            elif e=="go":
                target,fw=_go(repo,selected); candidates.append((bool(target),e,fw,{}))
            elif e=="rust":
                candidates.append((True,e,*_rust(repo,selected)[1:],{}))
            else: candidates.append((False,e,None,{}))
        viable=[x for x in candidates if x[0]]
        if len(viable)==1: eco=viable[0][1]; language=LANGUAGE_NAMES.get(eco,eco)
        else: check("POLYGLOT_TARGET","Polyglot target","blocker",selected.get("manifests",[]),"Multiple ecosystems exist in the same application root and no single executable target is provable.")

    if not blockers and eco=="node":
        manifest,pkg,deps,framework,scripts,pm,pm_version,lock=_node(repo,selected); language="Node.js"; script_inventory=scripts
        spec.runtime={"name":"Node.js","version":str((pkg.get("engines") or {}).get("node","20")).lstrip("v").split()[0]}; spec.package_managers=[{"name":pm,"ecosystem":"npm","version":pm_version,"evidence_file":manifest}]
        spec.build.update({"project_dir":root,"dependency_manifest":manifest,"lockfile":lock,"container_command":f"{pm} run build" if scripts.get("build") else ""})
        check("MANIFEST","Node package manifest","pass",[manifest]); check("LOCKFILE","Dependency lockfile","pass" if lock else "warning",[lock] if lock else [],"Pinned dependency installation will use the detected lockfile." if lock else "No lockfile; reproducibility is weaker.")
        check("BUILD_SCRIPT","Production build script","pass" if scripts.get("build") else "blocker",[manifest],scripts.get("build") or "No build script.")
        check("FRAMEWORK","Framework identity","pass" if framework else "warning",[manifest],framework or "No known Node framework dependency was proven.")
        if framework=="Astro":
            cfgf=next((f for f in files if Path(f).name.startswith("astro.config.")),None); cfg=_read(repo,cfgf); adapter=next((x for dep,x in (("@astrojs/vercel","vercel"),("@astrojs/node","node"),("@astrojs/netlify","netlify"),("@astrojs/cloudflare","cloudflare")) if dep in deps or dep in cfg),"unknown"); output="server" if re.search(r"output\s*:\s*['\"]server['\"]",cfg) else ("hybrid" if re.search(r"output\s*:\s*['\"]hybrid['\"]",cfg) else "static"); port=_port(cfg+"\n"+str(scripts),4321)
            check("FRAMEWORK_CONFIG","Astro adapter/output","pass" if cfgf else "warning",[cfgf] if cfgf else [],f"adapter={adapter}, output={output}")
            if adapter=="vercel" and output in {"server","hybrid"} and scripts.get("dev"):
                strategy="dev-server-fallback"; start=f"{pm} run dev -- --host 0.0.0.0 --port {port}"; spec.build.update({"runtime_strategy":strategy,"adapter":"vercel-serverless","preview_supported":False})
            elif adapter=="node" and output in {"server","hybrid"}:
                strategy="node-standalone"; start="node ./dist/server/entry.mjs"; spec.build.update({"runtime_strategy":strategy,"adapter":"node"})
            elif output=="static":
                strategy="static-preview"; start=f"{pm} run preview -- --host 0.0.0.0 --port {port}"; spec.build.update({"runtime_strategy":strategy,"adapter":adapter})
            else: check("RUNTIME","Production runtime","blocker",[cfgf] if cfgf else [],"No deterministic Astro runtime for the selected adapter/output.")
        elif framework in {"Next.js","Nuxt","NestJS","SvelteKit","Remix"} and scripts.get("start"):
            port=_port(_unit_text(repo,selected),3000); strategy="node-framework"; start=f"{pm} run start -- --hostname 0.0.0.0 --port {port}" if framework in {"Next.js","Nuxt"} else scripts["start"]; spec.build["runtime_strategy"]=strategy
        elif framework in {"Vite","React","Vue","Svelte","Angular","Gatsby","Docusaurus","Eleventy","SolidJS","Preact"} and scripts.get("build") and not scripts.get("start"):
            port=8080; output="build" if framework=="React" and "react-scripts" in deps else "dist"; strategy="static-node"; start='nginx -g "daemon off;"'; spec.build.update({"runtime_strategy":strategy,"output":output})
        elif scripts.get("start"):
            port=_port(_unit_text(repo,selected),readme["port"] or 3000); strategy="node-script"; start=scripts["start"]; spec.build["runtime_strategy"]=strategy
            readme_start=next((c["command"] for c in readme["commands"]["start"]["production"]),None)
            if readme_start:
                start,contradiction=_reconcile_command(start,readme_start)
                if contradiction: check("EVIDENCE_RECONCILIATION","Production command reconciliation","blocker",[manifest],f"README documents a different production command ('{readme_start}') than package.json's start script ('{scripts['start']}'); refusing to guess.")
        elif readme["commands"]["start"]["production"]:
            readme_cmd=readme["commands"]["start"]["production"][0]; start=readme_cmd["command"]; port=_port(_unit_text(repo,selected),readme["port"] or 3000); strategy="readme-documented"; spec.build["runtime_strategy"]=strategy
            check("RUNTIME","Production runtime (README)","pass",[readme_cmd["source"]],f"No package.json start script was provable; using README-documented production command: {start}")
        elif scripts.get("dev"):
            check("RUNTIME","Production runtime","blocker",[manifest],"Only a development script exists; refusing to turn it into a production runtime except for a verified framework fallback.")
        else: check("RUNTIME","Production runtime","blocker",[manifest],"No deterministic Node runtime command.")

    elif not blockers and eco=="python":
        manifests,framework=_python(repo,selected); manifest=manifests[0] if manifests else None; language="Python"; spec.runtime={"name":"Python","version":"3.12"}; spec.build.update({"dependency_manifest":manifest,"project_dir":root})
        check("MANIFEST","Python dependency manifest","pass" if manifest else "blocker",manifests[:10])
        port=_port(_unit_text(repo,selected),readme["port"] or 8000); py=[f for f in files if f.endswith(".py")]; entry=None
        if framework=="Django":
            entry=next((f for f in py if Path(f).name=="wsgi.py"),None); start=f"gunicorn {_module(entry)}:application --bind 0.0.0.0:{port}" if entry else ""
            strategy="python-gunicorn"
        elif framework in {"FastAPI","Litestar","Sanic","Starlette","Quart","Aiohttp"}:
            entry=next((f for f in py if Path(f).name in {"main.py","app.py","server.py","application.py"} and re.search(r"(?:FastAPI|Litestar|Sanic|Starlette|Quart|Application)\s*\(",_read(repo,f),re.I)),None); start=f"uvicorn {_module(entry)}:app --host 0.0.0.0 --port {port}" if entry else ""; strategy="python-uvicorn"
        elif framework=="Flask":
            entry=next((f for f in py if Path(f).name in {"main.py","app.py","application.py"} and re.search(r"\bapp\s*=",_read(repo,f))),None); start=f"gunicorn {_module(entry)}:app --bind 0.0.0.0:{port}" if entry else ""; strategy="python-gunicorn"
        else: start=""; strategy=None
        readme_start=next((c["command"] for c in readme["commands"]["start"]["production"]),None)
        if entry and readme_start:
            # README (Tier 2) outranks a naming-convention-derived entrypoint guess (Tier 3):
            # when they agree on the tool, the documented command is authoritative, not our guess.
            start,contradiction=_reconcile_command(readme_start,start)
            if contradiction: check("EVIDENCE_RECONCILIATION","Production command reconciliation","blocker",[entry],f"README documents a different production command ('{readme_start}') than the resolved entrypoint command ('{start}'); refusing to guess.")
        if entry: spec.build.update({"runtime_strategy":strategy,"entrypoint":entry}); spec.processes[0]["start_command"]=start; check("ENTRYPOINT","Python web entrypoint","pass",[entry],start)
        elif readme_start:
            readme_cmd=readme["commands"]["start"]["production"][0]; start=readme_start; strategy=strategy or "readme-documented"
            spec.build.update({"runtime_strategy":strategy}); check("ENTRYPOINT","Python web entrypoint (README)","pass",[readme_cmd["source"]],f"No conventional entrypoint file was provable; using README-documented production command: {start}")
        else: check("ENTRYPOINT","Python web entrypoint","blocker",py[:10],f"No deterministic web entrypoint for framework={framework or 'Unknown'}.")

    elif not blockers and eco=="go":
        target,framework=_go(repo,selected); language="Go"; gm=_read(repo,selected.get("manifest")); m=re.search(r"(?m)^go\s+([0-9.]+)",gm); spec.runtime={"name":"Go","version":m.group(1) if m else "1.24"}; port=_port(_unit_text(repo,selected),readme["port"] or 8080)
        if target: strategy="go-binary"; start="/app"; spec.build.update({"runtime_strategy":strategy,"source_package":target,"container_command":f'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app {target}'})
        else: check("ENTRYPOINT","Go main package","blocker",[],"No package main + func main entrypoint.")

    elif not blockers and eco=="rust":
        binary,framework=_rust(repo,selected); language="Rust"; spec.runtime={"name":"Rust","version":"1.88"}; port=_port(_unit_text(repo,selected),readme["port"] or 8080); strategy="rust-binary"; start=f"/app/{binary}"; spec.build.update({"runtime_strategy":strategy,"binary":binary,"container_command":"cargo build --release"})

    elif not blockers and eco in {"jvm","scala"}:
        manager,framework=_jvm(repo,selected); language="JVM"; spec.runtime={"name":"JDK","version":"21"}; port=_port(_unit_text(repo,selected),readme["port"] or 8080)
        if framework in {"Spring Boot","Quarkus","Micronaut","Ktor","Play Framework"}: strategy="jvm-jar"; start="java -jar /app/app.jar"; spec.build.update({"runtime_strategy":strategy,"jvm_manager":manager})
        else: check("ENTRYPOINT","JVM web runtime","blocker",selected.get("manifests",[]),"No deterministic supported JVM web framework/runtime identified.")

    elif not blockers and eco in {"dotnet","fsharp","vbnet"}:
        project,tfm,assembly,framework=_dotnet(repo,selected); language=LANGUAGE_NAMES.get(eco,eco); spec.runtime={"name":".NET","version":tfm}; port=_port(_unit_text(repo,selected),readme["port"] or 8080)
        if project and (framework or eco=="dotnet"): strategy="dotnet-aspnet"; start=f"dotnet /app/{assembly}.dll"; spec.build.update({"runtime_strategy":strategy,"project_file":project,"assembly":assembly})
        else: check("ENTRYPOINT",".NET web runtime","blocker",[project] if project else [],"No deterministic ASP.NET web project identified.")

    elif not blockers and eco=="php":
        # PHP's Apache runtime always listens on 80 inside the container regardless of what a
        # README documents for local `php -S` development - README port evidence does not apply here.
        composer,framework,web,public=_php(repo,selected); language="PHP"; port=80
        if web: strategy="php-apache"; start="apache2-foreground"; spec.runtime={"name":"PHP","version":"8.3"}; spec.build.update({"runtime_strategy":strategy,"document_root":"public" if public else ".","dependency_manifest":composer})
        else: check("ENTRYPOINT","PHP web entrypoint","blocker",[composer] if composer else [],"No deterministic PHP web entrypoint.")

    elif not blockers and eco=="ruby":
        framework,rails,rack=_ruby(repo,selected); language="Ruby"; port=_port(_unit_text(repo,selected),readme["port"] or 3000)
        readme_start=next((c["command"] for c in readme["commands"]["start"]["production"]),None)
        if rails: strategy="ruby-rails"; start=f"bundle exec rails server -b 0.0.0.0 -p {port}"
        elif rack: strategy="ruby-rack"; start=f"bundle exec rackup -o 0.0.0.0 -p {port}"
        elif readme_start:
            readme_cmd=readme["commands"]["start"]["production"][0]; start=readme_start; strategy="readme-documented"
            check("ENTRYPOINT","Ruby web entrypoint (README)","pass",[readme_cmd["source"]],f"No Rails or Rack marker was provable; using README-documented production command: {start}")
        else: check("ENTRYPOINT","Ruby web entrypoint","blocker",[],"No Rails or Rack web entrypoint identified.")
        if strategy: spec.runtime={"name":"Ruby","version":"3.3"}; spec.build["runtime_strategy"]=strategy

    elif not blockers:
        # Broad language recognition is intentional. Generation remains fail-closed until a
        # verified strategy exists, so C/C++, Swift, Kotlin, Elixir, Haskell, Erlang, Dart,
        # Clojure, Lua, Perl, R, Julia, Zig, Nim, Crystal, V, Solidity and Assembly are never
        # accidentally emitted as another ecosystem.
        check("UNSUPPORTED_TARGET","Deployment strategy","blocker",selected.get("manifests",[]),f"Technology {language} is recognized but has no verified deployment strategy yet.")

    if not blockers and strategy:
        spec.processes[0]["start_command"]=start; spec.network["port"]=port; spec.network["health_endpoint"]=_health(repo,selected); spec.services=_services(repo,selected)
        spec.frameworks=[{"name":framework,"score":95,"evidence":"scoped application manifest/source"}] if framework else []
        spec.languages=[{"name":language,"score":95,"confidence":95.0}]
        if readme.get("working_directory") in (root, Path(root).name) and readme["working_directory"]: spec.build["working_directory"]=readme["working_directory"]
        spec.project["container_decisions"]=[{"strategy":strategy,"application_root":root,"manifest":manifest or selected.get("manifest")}]
        decisions.extend(spec.project["container_decisions"])
        check("RUNTIME","Production runtime","pass",[manifest] if manifest else [],f"Resolved strategy={strategy}, start={start}, port={port}.")

    result["summary"].update({"primary_language":language,"runtime":spec.runtime.get("name",language),"runtime_version":spec.runtime.get("version","Not declared"),"framework":framework or "Unknown","package_manager":spec.package_managers[0]["name"] if spec.package_managers else "Unknown","start_command":start or "Not detected","port":port,"health_endpoint":spec.network.get("health_endpoint"),"services":[x["name"] for x in spec.services]})
    result["languages"]=spec.languages; result["frameworks"]=spec.frameworks
    deep={"status":"ready" if not blockers else "blocked","confidence":96 if not blockers else 0,"checks":checks,"warnings":warnings,"blockers":blockers,"decisions":decisions,"script_inventory":script_inventory,"technology_profile":profile}
    result["deep_analysis"]=deep; spec.project.update({"deep_analysis_status":deep["status"],"deep_analysis_confidence":deep["confidence"]})
    return deep
