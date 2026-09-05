from pathlib import Path
import json
import re

LOCKFILES = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock", "bun": "bun.lock", "uv": "uv.lock", "poetry": "poetry.lock", "pipenv": "Pipfile.lock"}


def _first_named(repo, names):
    wanted = set(names)
    return next((f for f in repo.files if Path(f).name in wanted), None)


def _all_named(repo, names):
    wanted = set(names)
    return [f for f in repo.files if Path(f).name in wanted]


def _read(repo, path):
    try:
        return repo.read(path)
    except Exception:
        return ""


def _port(text, default=None):
    for pattern in (
        r"(?i)--port(?:=|\s+)[\"']?(\d{2,5})",
        r"(?i)\bPORT\s*[:=]\s*[\"']?(\d{2,5})",
        r"(?i)localhost:(\d{2,5})",
        r"(?i)127\.0\.0\.1:(\d{2,5})",
    ):
        m = re.search(pattern, text or "")
        if m and 1 <= int(m.group(1)) <= 65535:
            return int(m.group(1))
    return default


def _script(pkg, name):
    return (pkg.get("scripts") or {}).get(name)


def _package(repo):
    if "package.json" in repo.file_set:
        try:
            return repo.json("package.json")
        except Exception:
            return {}
    return {}


def _node_manager(pkg, repo):
    declared = str(pkg.get("packageManager", ""))
    if declared:
        name, _, version = declared.partition("@")
        if name in {"npm", "pnpm", "yarn", "bun"}:
            return name, version or None
    for name, lock in (("pnpm", "pnpm-lock.yaml"), ("yarn", "yarn.lock"), ("bun", "bun.lock"), ("npm", "package-lock.json")):
        if lock in repo.file_set:
            return name, None
    return "npm", None


def _static_source(repo):
    server_ext = {".py", ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb", ".ex", ".exs", ".swift", ".scala"}
    return "package.json" not in repo.file_set and any(Path(f).name == "index.html" for f in repo.files) and not any(Path(f).suffix in server_ext for f in repo.files)


def _python_framework(repo):
    # Never infer a framework from the entire repository corpus: AutoDeploy itself
    # contains words such as "Django" in its detector source. Use dependency manifests
    # and actual import statements instead.
    manifests = [f for f in repo.files if Path(f).name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock"}]
    evidence = "\n".join(_read(repo, f).lower() for f in manifests)
    candidates = []
    rules = [("Django", r"(^|[\s=<>!~\[\],\"'])django([\s=<>!~\[\],\"']|$)"), ("FastAPI", r"(^|[\s=<>!~\[\],\"'])fastapi([\s=<>!~\[\],\"']|$)"), ("Flask", r"(^|[\s=<>!~\[\],\"'])flask([\s=<>!~\[\],\"']|$)"), ("Litestar", r"(^|[\s=<>!~\[\],\"'])litestar([\s=<>!~\[\],\"']|$)"), ("Sanic", r"(^|[\s=<>!~\[\],\"'])sanic([\s=<>!~\[\],\"']|$)"), ("Tornado", r"(^|[\s=<>!~\[\],\"'])tornado([\s=<>!~\[\],\"']|$)")]
    for name, pattern in rules:
        if re.search(pattern, evidence):
            candidates.append(name)
    if candidates:
        return candidates[0]
    imports = "\n".join(_read(repo, f) for f in repo.files if Path(f).suffix == ".py")
    for name, pattern in (("FastAPI", r"from\s+fastapi\s+import|import\s+fastapi"), ("Flask", r"from\s+flask\s+import|import\s+flask"), ("Django", r"from\s+django\b|import\s+django")):
        if re.search(pattern, imports, re.I):
            return name
    return None


def _python_entry(repo, framework):
    py_files = [f for f in repo.files if f.endswith(".py")]
    if framework == "Django":
        wsgi = [f for f in py_files if Path(f).name == "wsgi.py"]
        if wsgi:
            p = Path(wsgi[0]).with_suffix("").as_posix().replace("/", ".")
            return wsgi[0], f"gunicorn {p}:application --bind 0.0.0.0:8000", "python-gunicorn"
    if framework in {"FastAPI", "Litestar", "Sanic"}:
        preferred = [f for f in py_files if Path(f).name in {"main.py", "app.py", "server.py", "application.py"}]
        for f in preferred:
            text = _read(repo, f)
            if re.search(r"\bapp\s*=", text) or re.search(r"FastAPI\s*\(", text) or re.search(r"Litestar\s*\(", text) or re.search(r"Sanic\s*\(", text):
                p = Path(f).with_suffix("").as_posix().replace("/", ".")
                return f, f"uvicorn {p}:app --host 0.0.0.0 --port 8000", "python-uvicorn"
    if framework == "Flask":
        preferred = [f for f in py_files if Path(f).name in {"app.py", "main.py", "application.py"}]
        for f in preferred:
            text = _read(repo, f)
            if re.search(r"\bapp\s*=", text):
                p = Path(f).with_suffix("").as_posix().replace("/", ".")
                return f, f"gunicorn {p}:app --bind 0.0.0.0:8000", "python-gunicorn"
    return None, None, None


def _go_target(repo):
    mains = []
    for f in repo.files:
        if Path(f).suffix == ".go":
            text = _read(repo, f)
            if re.search(r"(?m)^\s*package\s+main\b", text) and re.search(r"(?m)^\s*func\s+main\s*\(", text):
                mains.append(str(Path(f).parent))
    dirs = sorted(set(mains))
    if not dirs:
        return None
    if "." in dirs:
        return "."
    cmd = next((d for d in dirs if d.startswith("cmd/")), dirs[0])
    return "./" + cmd.replace("\\", "/")


def _rust_binary(repo):
    cargo = _read(repo, "Cargo.toml")
    bins = re.findall(r"(?ms)^\s*\[\[bin\]\]\s*.*?^\s*name\s*=\s*[\"']([^\"']+)", cargo)
    if bins:
        return bins[0]
    m = re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)", cargo)
    return m.group(1) if m else Path(repo.root).name.replace("-", "_")


def _project_dir(path):
    parent = Path(path).parent.as_posix()
    return "" if parent == "." else parent


def analyze(repo, spec, result):
    checks, warnings, blockers, decisions = [], [], [], []
    pkg = _package(repo)
    primary = result["summary"].get("primary_language")
    framework = result["summary"].get("framework")
    spec.project["files"] = list(repo.files)

    def check(code, title, status, evidence=None, detail=""):
        item = {"code": code, "title": title, "status": status, "evidence": evidence or [], "detail": detail}
        checks.append(item)
        if status == "blocker": blockers.append(item)
        elif status == "warning": warnings.append(item)

    if _static_source(repo):
        spec.runtime = {"name": "Static Web", "version": "nginx-unprivileged:alpine"}
        spec.frameworks, spec.package_managers = [], []
        spec.build = {"command": "none", "runtime_strategy": "static-nginx", "output": "repository-root", "project_dir": ""}
        spec.processes = [{"role": "web", "start_command": 'nginx -g "daemon off;"'}]
        spec.network.update({"port": 8080, "health_endpoint": "/"})
        check("STATIC_ENTRYPOINT", "Static HTML entrypoint", "pass", [f for f in repo.files if Path(f).name == "index.html"][:3])
        decisions += [{"code": "TARGET", "decision": "static-nginx", "reason": "No application build/runtime was detected."}, {"code": "PORT", "decision": 8080, "reason": "Unprivileged nginx listens on 8080."}]

    elif primary in {"JavaScript", "TypeScript"} or "package.json" in repo.file_set:
        scripts = pkg.get("scripts") or {}
        pm, pm_version = _node_manager(pkg, repo)
        lock = LOCKFILES.get(pm)
        has_lock = bool(lock and lock in repo.file_set)
        spec.package_managers = [{"name": pm, "ecosystem": "npm", "version": pm_version or "", "evidence_file": "package.json"}]
        check("NODE_MANIFEST", "Node package manifest", "pass", ["package.json"] if "package.json" in repo.file_set else [], "package.json is required for Node deployment." if "package.json" not in repo.file_set else "")
        if "package.json" not in repo.file_set:
            blockers.append(checks[-1])
        check("LOCKFILE_MATCH", "Package manager lockfile", "pass" if has_lock else "warning", [lock] if has_lock else ["package.json"], "Lockfile present." if has_lock else "No lockfile; install is non-frozen.")
        build, start, dev = scripts.get("build"), scripts.get("start") or scripts.get("serve"), scripts.get("dev")
        check("BUILD_SCRIPT", "Production build command", "pass" if build else "blocker", ["package.json"], build or "No build script found.")
        check("START_SCRIPT", "Runtime command", "pass" if start else ("warning" if dev else "blocker"), ["package.json"], start or dev or "No start/dev script found.")
        spec.runtime["version"] = str((pkg.get("engines") or {}).get("node", "20")).lstrip("v").split()[0]
        spec.build.update({"container_command": f"{pm} run build" if build else "", "project_dir": ""})
        if framework == "Astro":
            cf = _first_named(repo, {"astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs"}); cfg = _read(repo, cf) if cf else ""
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            adapter = next((n for d, n in [("@astrojs/vercel", "vercel"), ("@astrojs/node", "node"), ("@astrojs/netlify", "netlify"), ("@astrojs/cloudflare", "cloudflare")] if d in deps or d in cfg), "unknown")
            output = "server" if re.search(r"output\s*:\s*['\"]server['\"]", cfg) else ("hybrid" if re.search(r"output\s*:\s*['\"]hybrid['\"]", cfg) else "static")
            port = _port(cfg) or _port(dev) or 4321
            check("FRAMEWORK_CONFIG", "Framework adapter/output", "pass" if cf else "warning", [cf] if cf else [], f"Astro adapter={adapter}, output={output}.")
            if adapter == "vercel" and output in {"server", "hybrid"}:
                if dev:
                    spec.build.update({"runtime_strategy": "dev-server-fallback", "adapter": "vercel-serverless", "preview_supported": False})
                    spec.processes[0]["start_command"] = f"{pm} run dev -- --host 0.0.0.0 --port {port}"
                    check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Vercel SSR uses the repository dev server as its deterministic local runtime.")
                else: check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "blocker", [cf] if cf else [], "No deterministic local runtime for this Vercel SSR configuration.")
            elif adapter == "node" and output in {"server", "hybrid"}:
                spec.build.update({"runtime_strategy": "node-standalone", "adapter": "node"}); spec.processes[0]["start_command"] = "node ./dist/server/entry.mjs"; check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Astro Node adapter provides a standalone server entrypoint.")
            elif output == "static":
                spec.build.update({"runtime_strategy": "static-preview", "adapter": adapter}); spec.processes[0]["start_command"] = f"{pm} run preview -- --host 0.0.0.0 --port {port}"; check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Static Astro output selected.")
            else: check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "blocker", [cf] if cf else [], "Unknown Astro adapter/runtime combination.")
            spec.network["port"] = port
        elif framework in {"Next.js", "Nuxt", "NestJS"}:
            port = _port(repo.corpus, 3000); spec.network["port"] = port
            if start:
                spec.processes[0]["start_command"] = f"{pm} run start -- --hostname 0.0.0.0 --port {port}" if framework in {"Next.js", "Nuxt"} else start; spec.build["runtime_strategy"] = "node-framework"
            else: check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "No production runtime command was resolved.")
        elif framework in {"Vite", "React", "Vue", "Angular", "Svelte"} and build and not start:
            out = "build" if framework == "React" and "react-scripts" in str(pkg.get("dependencies", {})) else "dist"; spec.build.update({"runtime_strategy": "static-node", "output": out}); spec.network["port"] = 8080; spec.processes[0]["start_command"] = 'nginx -g "daemon off;"'; check("STATIC_BUILD", "Static build output", "pass", ["package.json"], f"{framework} build will be served from {out}/.")
        elif start:
            spec.network["port"] = _port(repo.corpus, 3000); spec.processes[0]["start_command"] = start; spec.build["runtime_strategy"] = "node-script"
        else: check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "No deterministic Node runtime command was resolved.")

    elif primary == "Python":
        resolved_framework = _python_framework(repo) or (None if framework == "Unknown" else framework)
        if resolved_framework:
            framework = resolved_framework
            result["summary"]["framework"] = resolved_framework
            result["frameworks"] = [{"name": resolved_framework, "score": 70, "evidence": "dependency/import analysis"}]
        manifests = [f for f in repo.files if Path(f).name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile"}]
        if not manifests:
            check("PYTHON_MANIFEST", "Python dependency manifest", "blocker", [], "No supported Python dependency manifest was found anywhere in the repository.")
        else:
            manifest = next((f for f in manifests if Path(f).name == "requirements.txt"), manifests[0]); spec.build["dependency_manifest"] = manifest; spec.build["project_dir"] = _project_dir(manifest); check("PYTHON_MANIFEST", "Python dependency manifest", "pass", manifests[:10], f"Using {manifest}.")
        entry, start, strategy = _python_entry(repo, framework)
        if entry:
            port = _port(repo.corpus, 8000); start = re.sub(r":8000\b", f":{port}", start); spec.build.update({"runtime_strategy": strategy, "entrypoint": entry}); spec.processes[0]["start_command"] = start; spec.network["port"] = port; check("PYTHON_ENTRYPOINT", "Production web entrypoint", "pass", [entry], start)
        else:
            check("PYTHON_ENTRYPOINT", "Production web entrypoint", "blocker", [], f"No deterministic production entrypoint was identified for framework={framework or 'Unknown'}.")
        if resolved_framework: decisions.append({"code": "FRAMEWORK", "decision": resolved_framework, "reason": "Resolved from Python dependency manifests/imports; repository-wide detector source text is excluded from framework inference."})

    elif primary == "Go":
        check("GO_MODULE", "Go module", "pass" if "go.mod" in repo.file_set else "blocker", ["go.mod"] if "go.mod" in repo.file_set else [], "go.mod controls dependencies.")
        target = _go_target(repo)
        if target:
            spec.build.update({"runtime_strategy": "go-binary", "container_command": f'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app {target}', "source_package": target}); spec.processes[0]["start_command"] = "/app"; spec.network["port"] = _port(repo.corpus, 8080); check("GO_ENTRYPOINT", "Go main package", "pass", [], f"Building {target}.")
        else: check("GO_ENTRYPOINT", "Go main package", "blocker", [], "No package main + func main entrypoint was identified.")

    elif primary == "Rust":
        check("RUST_MANIFEST", "Cargo manifest", "pass" if "Cargo.toml" in repo.file_set else "blocker", ["Cargo.toml"] if "Cargo.toml" in repo.file_set else [], "Cargo manifest detected.")
        if "Cargo.toml" in repo.file_set:
            binary = _rust_binary(repo); spec.build.update({"runtime_strategy": "rust-binary", "binary": binary, "container_command": "cargo build --release"}); spec.processes[0]["start_command"] = f"/app/{binary}"; spec.network["port"] = _port(repo.corpus, 8080)

    elif primary == "Java":
        manifest = next((f for f in repo.files if Path(f).name in {"pom.xml", "build.gradle", "build.gradle.kts"}), None); check("JVM_BUILD", "JVM build manifest", "pass" if manifest else "blocker", [manifest] if manifest else [], "Maven/Gradle build detected." if manifest else "No JVM build manifest.")
        if manifest:
            text = _read(repo, manifest).lower(); spring = "spring-boot" in text or "org.springframework.boot" in text
            if spring:
                manager = "gradle" if Path(manifest).name.startswith("build.gradle") else "maven"; spec.build.update({"runtime_strategy": "jvm-jar", "container_command": "./gradlew bootJar --no-daemon" if manager == "gradle" and "gradlew" in repo.file_set else ("gradle bootJar --no-daemon" if manager == "gradle" else ("./mvnw -B -DskipTests package" if "mvnw" in repo.file_set else "mvn -B -DskipTests package")), "jvm_manager": manager}); spec.processes[0]["start_command"] = "java -jar /app/app.jar"; spec.network["port"] = _port(repo.corpus, 8080); check("JVM_ENTRYPOINT", "JVM web runtime", "pass", [manifest], "Spring Boot executable JAR strategy selected.")
            else: check("JVM_ENTRYPOINT", "JVM web runtime", "blocker", [manifest], "No deterministic JVM web runtime was identified.")

    elif primary == "C#":
        cs = next((f for f in repo.files if f.endswith(".csproj")), None); check("DOTNET_PROJECT", ".NET project", "pass" if cs else "blocker", [cs] if cs else [], "Project file detected." if cs else "No .csproj found.")
        if cs:
            text = _read(repo, cs); tfm = re.search(r"<TargetFramework[^>]*>([^<]+)", text, re.I); name = Path(cs).stem; spec.runtime["version"] = tfm.group(1) if tfm else "net8.0"; spec.build.update({"runtime_strategy": "dotnet-publish", "project_file": cs, "assembly": name}); spec.processes[0]["start_command"] = f"dotnet /app/{name}.dll"; spec.network["port"] = _port(repo.corpus, 8080)

    elif primary == "PHP":
        composer = next((f for f in repo.files if Path(f).name == "composer.json"), None); public = any(Path(f).parts and Path(f).parts[-2:-1] == ("public",) for f in repo.files if Path(f).name == "index.php"); index = any(Path(f).name == "index.php" for f in repo.files); check("PHP_COMPOSER", "Composer manifest", "pass" if composer else "warning", [composer] if composer else [], "Composer dependencies detected." if composer else "No composer.json."); check("PHP_ENTRYPOINT", "PHP document root", "pass" if public or index else "blocker", [], "Web entrypoint identified." if public or index else "No deterministic document root.")
        if public or index: spec.build.update({"runtime_strategy": "php-apache", "document_root": "public" if public else ".", "dependency_manifest": composer}); spec.network["port"] = 80; spec.processes[0]["start_command"] = "apache2-foreground"

    elif primary == "Ruby":
        check("RUBY_BUNDLE", "Bundler manifest", "pass" if "Gemfile" in repo.file_set else "blocker", ["Gemfile"] if "Gemfile" in repo.file_set else [], "Gemfile detected." if "Gemfile" in repo.file_set else "No Gemfile.")
        if "Gemfile" in repo.file_set:
            port = _port(repo.corpus, 3000)
            if "bin/rails" in repo.file_set or "config/application.rb" in repo.file_set: spec.build["runtime_strategy"] = "ruby-rails"; spec.processes[0]["start_command"] = f"bundle exec rails server -b 0.0.0.0 -p {port}"
            elif "config.ru" in repo.file_set: spec.build["runtime_strategy"] = "ruby-rack"; spec.processes[0]["start_command"] = f"bundle exec rackup -o 0.0.0.0 -p {port}"
            else: check("RUBY_ENTRYPOINT", "Ruby web entrypoint", "blocker", [], "No Rails or Rack entrypoint identified.")
            spec.network["port"] = port

    else:
        check("UNSUPPORTED_TARGET", "Deployable target identification", "blocker", [], f"No deterministic deployment strategy for {primary}.")

    if spec.project.get("monorepo"):
        check("MONOREPO_TARGET", "Monorepo deployment target", "blocker", [], "Monorepo detected but no workspace/package target was selected; generation will not guess.")
    if "Dockerfile" in repo.file_set: check("EXISTING_DOCKERFILE", "Existing Dockerfile", "warning", ["Dockerfile"], "Existing Dockerfile is evidence only.")
    if spec.environment.get("secret_files"): check("SECRET_FILES", "Repository secret files", "warning", spec.environment["secret_files"], "Secret-bearing files must not enter an image.")

    confidence = max(0, 100 - min(30, len(warnings) * 3)) if not blockers else 0
    result["deep_analysis"] = {"status": "ready" if not blockers else "blocked", "confidence": confidence, "checks": checks, "warnings": warnings, "blockers": blockers, "decisions": decisions, "script_inventory": {k: _script(pkg, k) for k in ("build", "start", "dev", "preview", "serve") if _script(pkg, k)}}
    spec.project.update({"deep_analysis_status": result["deep_analysis"]["status"], "deep_analysis_confidence": confidence, "container_decisions": decisions})
    return result["deep_analysis"]
