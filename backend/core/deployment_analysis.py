"""Repository-scoped deployment analysis.

This is the authoritative pre-generation pass.  It never treats arbitrary repository
text as application evidence.  Detection is performed against a selected application
unit (manifest + files beneath that unit), with explicit ambiguity blockers.
"""
from pathlib import Path
import json
import re
from .repository_scope import select_unit, discover_units, files_for_unit, read_unit_json, text as scoped_text

NODE_FRAMEWORKS = {
    "next": "Next.js", "nuxt": "Nuxt", "@nestjs/core": "NestJS", "express": "Express",
    "fastify": "Fastify", "koa": "Koa", "hono": "Hono", "@remix-run/node": "Remix",
    "@sveltejs/kit": "SvelteKit", "@angular/core": "Angular", "react": "React",
    "vue": "Vue", "vite": "Vite", "astro": "Astro",
}
PY_FRAMEWORKS = {
    "django": "Django", "fastapi": "FastAPI", "flask": "Flask", "litestar": "Litestar",
    "sanic": "Sanic", "tornado": "Tornado",
}
GO_FRAMEWORKS = {"github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo", "github.com/gofiber/fiber": "Fiber", "github.com/go-chi/chi": "Chi"}
RUST_FRAMEWORKS = {"axum": "Axum", "actix-web": "Actix Web", "rocket": "Rocket"}
SERVICE_RULES = {
    "PostgreSQL": ("postgresql", "postgres", "psycopg", "asyncpg", "pgx", "prisma", "typeorm"),
    "MySQL": ("mysql", "mysql2", "pymysql"), "MariaDB": ("mariadb",),
    "MongoDB": ("mongodb", "mongoose", "motor"), "Redis": ("redis", "ioredis", "redis-py"),
    "RabbitMQ": ("rabbitmq", "amqp", "pika", "aio-pika"), "Kafka": ("kafka", "kafkajs", "confluent-kafka"),
    "Elasticsearch": ("elasticsearch", "opensearch"), "S3/Object Storage": ("s3", "aws-sdk", "boto3", "minio"),
    "Supabase": ("supabase",), "Firebase": ("firebase",), "Stripe": ("stripe",),
    "DynamoDB": ("dynamodb",), "SQLite": ("sqlite", "sqlite3"),
}
PORT_PATTERNS = (
    r"(?i)--port(?:=|\s+)[\"']?(\d{2,5})", r"(?i)\bPORT\s*[:=]\s*[\"']?(\d{2,5})",
    r"(?i)localhost:(\d{2,5})", r"(?i)127\.0\.0\.1:(\d{2,5})",
)


def _read(repo, path):
    return repo.read(path) if path else ""


def _port(text, default):
    for pattern in PORT_PATTERNS:
        m = re.search(pattern, text or "")
        if m and 1 <= int(m.group(1)) <= 65535:
            return int(m.group(1))
    return default


def _module(path):
    return Path(path).with_suffix("").as_posix().replace("/", ".")


def _node_info(repo, unit):
    pkg = read_unit_json(repo, unit)
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    framework = next((name for dep, name in NODE_FRAMEWORKS.items() if dep in deps), None)
    pm_decl = str(pkg.get("packageManager") or "")
    pm = pm_decl.split("@", 1)[0] if pm_decl else None
    pm_version = pm_decl.split("@", 1)[1] if "@" in pm_decl else None
    files = set(files_for_unit(repo, unit))
    for name, lock in (("pnpm", "pnpm-lock.yaml"), ("yarn", "yarn.lock"), ("bun", "bun.lock"), ("npm", "package-lock.json")):
        if not pm and lock in files:
            pm = name
    pm = pm or "npm"
    scripts = pkg.get("scripts") or {}
    return pkg, deps, framework, pm, pm_version, scripts


def _python_info(repo, unit):
    files = files_for_unit(repo, unit)
    manifests = [f for f in files if Path(f).name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock"}]
    evidence = "\n".join(_read(repo, f).lower() for f in manifests)
    framework = next((name for dep, name in PY_FRAMEWORKS.items() if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(dep)}(?![A-Za-z0-9_-])", evidence)), None)
    if not framework:
        imports = scoped_text(repo, unit, suffixes={".py"})
        framework = next((name for dep, name in PY_FRAMEWORKS.items() if re.search(rf"(?:from|import)\s+{re.escape(dep)}\b", imports, re.I)), None)
    return manifests, framework


def _go_info(repo, unit):
    files = files_for_unit(repo, unit); go_files = [f for f in files if f.endswith(".go")]
    mains = []
    for f in go_files:
        t = _read(repo, f)
        if re.search(r"(?m)^\s*package\s+main\b", t) and re.search(r"(?m)^\s*func\s+main\s*\(", t): mains.append(str(Path(f).parent))
    target = None
    dirs = sorted(set(mains))
    if dirs:
        target = "." if "." in dirs else "./" + next((d for d in dirs if d.startswith("cmd/")), dirs[0]).replace("\\", "/")
    module = _read(repo, unit.get("manifest"))
    deps = module.lower()
    framework = next((name for dep, name in GO_FRAMEWORKS.items() if dep in deps), None)
    return target, framework


def _rust_info(repo, unit):
    cargo = _read(repo, unit.get("manifest")); files = files_for_unit(repo, unit)
    bins = re.findall(r"(?ms)^\s*\[\[bin\]\]\s*.*?^\s*name\s*=\s*[\"']([^\"']+)", cargo)
    name = bins[0] if bins else (re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)", cargo).group(1) if re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)", cargo) else Path(unit.get("root") or repo.root).name.replace("-", "_"))
    txt = "\n".join(_read(repo, f).lower() for f in files if f.endswith(".rs"))
    framework = next((name for dep, name in RUST_FRAMEWORKS.items() if dep in txt or dep in cargo.lower()), None)
    return name, framework


def _jvm_info(repo, unit):
    manifest = unit.get("manifest"); text = _read(repo, manifest).lower(); name = Path(manifest).name if manifest else ""
    spring = "spring-boot" in text or "org.springframework.boot" in text
    return spring, ("gradle" if name.startswith("build.gradle") else "maven")


def _dotnet_info(repo, unit):
    f = unit.get("manifest"); text = _read(repo, f); m = re.search(r"<TargetFramework[^>]*>([^<]+)", text, re.I); return f, (m.group(1) if m else "net8.0"), Path(f).stem if f else "app"


def _php_info(repo, unit):
    files = files_for_unit(repo, unit); composer = unit.get("manifest")
    public = any(Path(f).name == "index.php" and "public" in Path(f).parts for f in files)
    index = any(Path(f).name == "index.php" for f in files)
    return composer, public or index


def _ruby_info(repo, unit):
    files = set(files_for_unit(repo, unit)); return ("bin/rails" in files or "config/application.rb" in files), ("config.ru" in files)


def _language(unit, repo):
    return {"node": "Node.js", "python": "Python", "go": "Go", "rust": "Rust", "jvm": "Java", "php": "PHP", "ruby": "Ruby", "elixir": "Elixir", "swift": "Swift", "dart": "Dart"}.get(unit.get("ecosystem"), "Unknown")


def _unit_text(repo, unit):
    return scoped_text(repo, unit, include_nested_units=False)


def _services(repo, unit):
    t = _unit_text(repo, unit).lower(); out = []
    for service, needles in SERVICE_RULES.items():
        hits = [n for n in needles if n in t]
        if hits: out.append({"name": service, "signals": hits[:5]})
    return out


def _health(repo, unit):
    t = _unit_text(repo, unit)
    return next((p for p in ("/health", "/healthz", "/ready", "/readiness", "/live") if p in t), None)


def analyze(repo, spec, result):
    selected, units, selection_error = select_unit(repo)
    checks, warnings, blockers, decisions = [], [], [], []
    def check(code, title, status, evidence=None, detail=""):
        item = {"code": code, "title": title, "status": status, "evidence": evidence or [], "detail": detail}; checks.append(item)
        if status == "blocker": blockers.append(item)
        elif status == "warning": warnings.append(item)

    result["repository_model"] = {"units": units, "selected_unit": selected, "selection_error": selection_error}
    if selection_error:
        check("APPLICATION_BOUNDARY", "Application unit selection", "blocker", [], "No unique application unit could be selected; generation will not guess between unrelated applications.")
    if not selected:
        confidence = 0
        result["deep_analysis"] = {"status": "blocked", "confidence": confidence, "checks": checks, "warnings": warnings, "blockers": blockers, "decisions": decisions, "script_inventory": {}}
        spec.project.update({"application_units": units, "deep_analysis_status": "blocked", "deep_analysis_confidence": 0})
        return result["deep_analysis"]

    root = selected.get("root") or "."; files = files_for_unit(repo, selected); ecosystem = selected.get("ecosystem"); language = _language(selected, repo)
    spec.project.update({"application_units": units, "selected_application": selected, "application_root": root})
    check("APPLICATION_BOUNDARY", "Application boundary", "pass", [selected.get("manifest")] if selected.get("manifest") else files[:3], f"Selected application unit {selected.get('id') or '.'}.")

    if ecosystem == "node":
        pkg, deps, framework, pm, pm_version, scripts = _node_info(repo, selected)
        spec.runtime = {"name": "Node.js", "version": str((pkg.get("engines") or {}).get("node", "20")).lstrip("v").split()[0]}
        spec.package_managers = [{"name": pm, "ecosystem": "npm", "version": pm_version or "", "evidence_file": selected.get("manifest")}]
        build, start, dev = scripts.get("build"), scripts.get("start") or scripts.get("serve"), scripts.get("dev")
        check("MANIFEST", "Node manifest", "pass", [selected.get("manifest")])
        lock = {"npm":"package-lock.json","pnpm":"pnpm-lock.yaml","yarn":"yarn.lock","bun":"bun.lock"}.get(pm)
        check("LOCKFILE", "Package manager lockfile", "pass" if lock and lock in set(files) else "warning", [lock] if lock and lock in set(files) else [], "Exact lockfile selected from the application unit.")
        check("BUILD_SCRIPT", "Production build script", "pass" if build else "blocker", [selected.get("manifest")], build or "No build script.")
        check("FRAMEWORK", "Framework identity", "pass" if framework else "warning", [selected.get("manifest")], framework or "No known framework dependency; runtime must still be explicit.")
        spec.build.update({"container_command": f"{pm} run build" if build else "", "project_dir": root, "dependency_manifest": selected.get("manifest")})
        if framework == "Astro":
            configs = [f for f in files if Path(f).name.startswith("astro.config.")]; cfgf = configs[0] if configs else None; cfg = _read(repo, cfgf)
            adapter = next((x for dep, x in (("@astrojs/vercel", "vercel"), ("@astrojs/node", "node"), ("@astrojs/netlify", "netlify"), ("@astrojs/cloudflare", "cloudflare")) if dep in deps or dep in cfg), "unknown")
            output = "server" if re.search(r"output\s*:\s*['\"]server['\"]", cfg) else ("hybrid" if re.search(r"output\s*:\s*['\"]hybrid['\"]", cfg) else "static")
            port = _port(cfg + "\n" + str(dev), 4321); spec.network["port"] = port
            check("FRAMEWORK_CONFIG", "Framework adapter/output", "pass" if cfgf else "warning", [cfgf] if cfgf else [], f"Astro adapter={adapter}, output={output}.")
            if adapter == "vercel" and output in {"server", "hybrid"} and dev:
                spec.build.update({"runtime_strategy":"dev-server-fallback", "adapter":"vercel-serverless", "preview_supported":False}); spec.processes[0]["start_command"] = f"{pm} run dev -- --host 0.0.0.0 --port {port}"; check("RUNTIME", "Container runtime", "pass", [cfgf] if cfgf else [], "Repository dev server selected for Vercel SSR compatibility.")
            elif adapter == "node" and output in {"server", "hybrid"}:
                spec.build.update({"runtime_strategy":"node-standalone", "adapter":"node"}); spec.processes[0]["start_command"] = "node ./dist/server/entry.mjs"; check("RUNTIME", "Container runtime", "pass", [cfgf] if cfgf else [], "Astro Node standalone server selected.")
            elif output == "static":
                spec.build.update({"runtime_strategy":"static-preview", "adapter":adapter}); spec.processes[0]["start_command"] = f"{pm} run preview -- --host 0.0.0.0 --port {port}"; check("RUNTIME", "Container runtime", "pass", [cfgf] if cfgf else [], "Static Astro output selected.")
            else: check("RUNTIME", "Container runtime", "blocker", [cfgf] if cfgf else [], "No deterministic Astro runtime for this adapter/output combination.")
        elif framework in {"Next.js", "Nuxt", "NestJS"} and start:
            port = _port(_unit_text(repo, selected), 3000); spec.network["port"] = port; spec.build["runtime_strategy"] = "node-framework"; spec.processes[0]["start_command"] = f"{pm} run start -- --hostname 0.0.0.0 --port {port}" if framework in {"Next.js","Nuxt"} else start
        elif framework in {"Vite","React","Vue","Angular","Svelte"} and build and not start:
            out = "build" if framework == "React" and "react-scripts" in str(deps) else "dist"; spec.build.update({"runtime_strategy":"static-node","output":out}); spec.network["port"] = 8080; spec.processes[0]["start_command"] = 'nginx -g "daemon off;"'
        elif start:
            spec.build["runtime_strategy"] = "node-script"; spec.network["port"] = _port(_unit_text(repo, selected), 3000); spec.processes[0]["start_command"] = start
        elif dev:
            check("RUNTIME", "Production runtime", "blocker", [selected.get("manifest")], "Only a development command exists; refusing to invent a production runtime.")
        else: check("RUNTIME", "Production runtime", "blocker", [selected.get("manifest")], "No deterministic Node runtime command.")

    elif ecosystem == "python":
        manifests, framework = _python_info(repo, selected); manifest = manifests[0] if manifests else None
        spec.runtime = {"name":"Python", "version":"3.12"}; spec.build.update({"dependency_manifest":manifest, "project_dir":root})
        check("MANIFEST", "Python dependency manifest", "pass" if manifest else "blocker", manifests[:10], "Scoped Python dependency manifest selected." if manifest else "No dependency manifest.")
        py_files = [f for f in files if f.endswith(".py")]; entry = None; start = None; strategy = None
        port = _port(_unit_text(repo, selected), 8000)
        if framework == "Django":
            wsgi = [f for f in py_files if Path(f).name == "wsgi.py"]
            if wsgi: entry=wsgi[0]; start=f"gunicorn {_module(entry)}:application --bind 0.0.0.0:{port}"; strategy="python-gunicorn"
        elif framework in {"FastAPI","Litestar","Sanic"}:
            for f in [x for x in py_files if Path(x).name in {"main.py","app.py","server.py","application.py"}]:
                t=_read(repo,f)
                if re.search(r"(?:FastAPI|Litestar|Sanic)\s*\(",t) or re.search(r"\bapp\s*=",t): entry=f; start=f"uvicorn {_module(f)}:app --host 0.0.0.0 --port {port}"; strategy="python-uvicorn"; break
        elif framework == "Flask":
            for f in [x for x in py_files if Path(x).name in {"app.py","main.py","application.py"}]:
                if re.search(r"\bapp\s*=",_read(repo,f)): entry=f; start=f"gunicorn {_module(f)}:app --bind 0.0.0.0:{port}"; strategy="python-gunicorn"; break
        if not entry:
            check("ENTRYPOINT", "Production Python web entrypoint", "blocker", py_files[:10], f"No deterministic web entrypoint for framework={framework or 'Unknown'}.")
        else:
            spec.build.update({"runtime_strategy":strategy,"entrypoint":entry}); spec.processes[0]["start_command"]=start; spec.network["port"]=port; check("ENTRYPOINT", "Production Python web entrypoint", "pass", [entry], start)
        result["summary"]["framework"] = framework or "Unknown"; result["frameworks"] = [{"name":framework,"score":90,"evidence":"scoped dependency/import analysis"}] if framework else []

    elif ecosystem == "go":
        target, framework = _go_info(repo, selected); spec.runtime={"name":"Go","version":re.search(r"(?m)^go\s+([0-9.]+)",_read(repo,selected.get("manifest"))).group(1) if re.search(r"(?m)^go\s+([0-9.]+)",_read(repo,selected.get("manifest"))) else "1.24"}
        if target: spec.build.update({"runtime_strategy":"go-binary","container_command":f'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app {target}',"source_package":target}); spec.processes[0]["start_command"]="/app"; spec.network["port"]=_port(_unit_text(repo,selected),8080); check("ENTRYPOINT","Go main package","pass",[],f"Building {target}.")
        else: check("ENTRYPOINT","Go main package","blocker",[],"No package main + func main entrypoint.")

    elif ecosystem == "rust":
        binary, framework = _rust_info(repo, selected); spec.runtime={"name":"Rust","version":"1.88"}; spec.build.update({"runtime_strategy":"rust-binary","binary":binary,"container_command":"cargo build --release"}); spec.processes[0]["start_command"]=f"/app/{binary}"; spec.network["port"]=_port(_unit_text(repo,selected),8080); check("ENTRYPOINT","Rust binary","pass",[selected.get("manifest")],f"Cargo binary {binary}.")

    elif ecosystem == "jvm":
        spring, manager = _jvm_info(repo, selected); check("BUILD","JVM build system","pass",[selected.get("manifest")],manager); 
        if spring:
            spec.runtime={"name":"JDK","version":"21"}; spec.build.update({"runtime_strategy":"jvm-jar","jvm_manager":manager}); spec.processes[0]["start_command"]="java -jar /app/app.jar"; spec.network["port"]=_port(_unit_text(repo,selected),8080); check("ENTRYPOINT","JVM web runtime","pass",[selected.get("manifest")],"Spring Boot executable JAR strategy.")
        else: check("ENTRYPOINT","JVM web runtime","blocker",[selected.get("manifest")],"No deterministic JVM web framework/runtime identified.")

    elif ecosystem == "php":
        composer, web = _php_info(repo, selected); check("ENTRYPOINT","PHP document root","pass" if web else "blocker",[composer] if composer else [],"PHP web entrypoint detected." if web else "No deterministic PHP web entrypoint.")
        if web: spec.runtime={"name":"PHP","version":"8.3"}; spec.build.update({"runtime_strategy":"php-apache","document_root":"public" if any(Path(f).name=="index.php" and "public" in Path(f).parts for f in files) else ".","dependency_manifest":composer}); spec.processes[0]["start_command"]="apache2-foreground"; spec.network["port"]=80

    elif ecosystem == "ruby":
        rails, rack = _ruby_info(repo, selected); port=_port(_unit_text(repo,selected),3000); check("BUNDLE","Bundler manifest","pass",[selected.get("manifest")]);
        if rails: spec.runtime={"name":"Ruby","version":"3.3"}; spec.build["runtime_strategy"]="ruby-rails"; spec.processes[0]["start_command"]=f"bundle exec rails server -b 0.0.0.0 -p {port}"
        elif rack: spec.runtime={"name":"Ruby","version":"3.3"}; spec.build["runtime_strategy"]="ruby-rack"; spec.processes[0]["start_command"]=f"bundle exec rackup -o 0.0.0.0 -p {port}"
        else: check("ENTRYPOINT","Ruby web entrypoint","blocker",[],"No Rails or Rack entrypoint identified.")
        spec.network["port"]=port

    else:
        check("UNSUPPORTED_TARGET","Deployable target","blocker",[],f"No deterministic deployment strategy for ecosystem={ecosystem}.")

    spec.services = _services(repo, selected)
    spec.network["health_endpoint"] = _health(repo, selected)
    result["summary"].update({"primary_language":language,"runtime":spec.runtime.get("name",language),"runtime_version":spec.runtime.get("version","Not declared"),"package_manager":spec.package_managers[0]["name"] if spec.package_managers else "Unknown","start_command":spec.processes[0].get("start_command","Not detected"),"port":spec.network.get("port"),"health_endpoint":spec.network.get("health_endpoint"),"services":[x["name"] for x in spec.services]})
    result["deep_analysis"]={"status":"ready" if not blockers else "blocked","confidence":max(0,100-min(35,len(warnings)*3)) if not blockers else 0,"checks":checks,"warnings":warnings,"blockers":blockers,"decisions":decisions,"script_inventory":_node_info(repo,selected)[5] if ecosystem=="node" else {}}
    spec.project.update({"deep_analysis_status":result["deep_analysis"]["status"],"deep_analysis_confidence":result["deep_analysis"]["confidence"],"container_decisions":decisions})
    return result["deep_analysis"]
