from pathlib import Path
import re

LOCKFILES = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock", "bun": "bun.lock"}


def _pkg(r):
    return r.json("package.json") if "package.json" in r.file_set else {}


def _first(r, names):
    return next((f for f in r.files if Path(f).name in names), None)


def _port(text, default=None):
    for p in (
        r"(?i)--port(?:=|\s+)[\"']?(\d{2,5})",
        r"(?i)\bPORT\s*[:=]\s*[\"']?(\d{2,5})",
        r"(?i)localhost:(\d{2,5})",
        r"(?i)127\.0\.0\.1:(\d{2,5})",
    ):
        m = re.search(p, text or "")
        if m and 1 <= int(m.group(1)) <= 65535:
            return int(m.group(1))
    return default


def _script(pkg, name):
    return (pkg.get("scripts") or {}).get(name)


def _node_manager(pkg, repo, fallback="npm"):
    declared = str(pkg.get("packageManager", ""))
    if declared:
        name, _, version = declared.partition("@")
        if name in {"npm", "pnpm", "yarn", "bun"}:
            return name, version or None
    for name, lock in LOCKFILES.items():
        if lock in repo.file_set:
            return name, None
    return fallback, None


def _static_source(r):
    server_ext = {".py", ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb", ".ex", ".exs"}
    return (
        "package.json" not in r.file_set
        and any(Path(f).name == "index.html" for f in r.files)
        and not any(Path(f).suffix in server_ext for f in r.files)
    )


def _go_target(repo):
    mains = []
    for f in repo.files:
        if Path(f).suffix != ".go":
            continue
        text = repo.read(f)
        if re.search(r"(?m)^\s*package\s+main\b", text) and re.search(r"(?m)^\s*func\s+main\s*\(", text):
            mains.append(str(Path(f).parent))
    dirs = sorted(set(mains))
    if not dirs:
        return None
    if "." in dirs:
        return "."
    for d in dirs:
        if d.startswith("cmd/"):
            return "./" + d.replace("\\", "/")
    return "./" + dirs[0].replace("\\", "/")


def _rust_binary(repo):
    cargo = repo.read("Cargo.toml") if "Cargo.toml" in repo.file_set else ""
    bins = re.findall(r"(?ms)^\s*\[\[bin\]\]\s*.*?^\s*name\s*=\s*[\"']([^\"']+)", cargo)
    if bins:
        return bins[0]
    m = re.search(r"(?m)^\s*name\s*=\s*[\"']([^\"']+)", cargo)
    return m.group(1) if m else Path(repo.root).name.replace("-", "_")


def analyze(repo, spec, result):
    checks, warnings, blockers, decisions = [], [], [], []
    pkg = _pkg(repo)
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
        spec.frameworks = []
        spec.package_managers = []
        spec.build = {"command": "none", "runtime_strategy": "static-nginx", "output": "repository-root"}
        spec.processes = [{"role": "web", "start_command": 'nginx -g "daemon off;"'}]
        spec.network.update({"port": 8080, "health_endpoint": "/"})
        check("STATIC_ENTRYPOINT", "Static HTML entrypoint", "pass", [f for f in repo.files if Path(f).name == "index.html"][:3])
        decisions += [
            {"code": "TARGET", "decision": "static-nginx", "reason": "No application build/runtime was detected."},
            {"code": "PORT", "decision": 8080, "reason": "Unprivileged nginx listens on 8080."},
        ]

    elif primary in {"JavaScript", "TypeScript"} or "package.json" in repo.file_set:
        scripts = pkg.get("scripts") or {}
        pm, pm_version = _node_manager(pkg, repo)
        lock = LOCKFILES.get(pm)
        has_lock = bool(lock and lock in repo.file_set)
        if pm_version:
            spec.package_managers = [{"name": pm, "ecosystem": "npm", "version": pm_version, "evidence_file": "package.json"}]
        if "package.json" not in repo.file_set:
            check("NODE_MANIFEST", "Node package manifest", "blocker", [], "package.json is required for Node deployment.")
        else:
            check("NODE_MANIFEST", "Node package manifest", "pass", ["package.json"])
        if lock:
            check("LOCKFILE_MATCH", "Package manager lockfile", "pass" if has_lock else "warning", [lock] if has_lock else ["package.json"], "Lockfile present." if has_lock else "No lockfile; install is non-frozen.")
        build = scripts.get("build")
        start = scripts.get("start") or scripts.get("serve")
        dev = scripts.get("dev")
        check("BUILD_SCRIPT", "Production build command", "pass" if build else "blocker", ["package.json"], build or "No build script found.")
        check("START_SCRIPT", "Runtime command", "pass" if start else ("warning" if dev else "blocker"), ["package.json"], start or dev or "No start/dev script found.")
        spec.runtime["version"] = str((pkg.get("engines") or {}).get("node", "20")).lstrip("v").split()[0]
        spec.build["container_command"] = f"{pm} run build" if build else ""

        if framework == "Astro":
            cf = _first(repo, {"astro.config.mjs", "astro.config.js", "astro.config.ts", "astro.config.cjs"})
            cfg = repo.read(cf) if cf else ""
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            adapter = next((n for d, n in [("@astrojs/vercel", "vercel"), ("@astrojs/node", "node"), ("@astrojs/netlify", "netlify"), ("@astrojs/cloudflare", "cloudflare")] if d in deps or d in cfg), "unknown")
            output = "server" if re.search(r"output\s*:\s*['\"]server['\"]", cfg) else ("hybrid" if re.search(r"output\s*:\s*['\"]hybrid['\"]", cfg) else "static")
            check("FRAMEWORK_CONFIG", "Framework adapter/output", "pass" if cf else "warning", [cf] if cf else [], f"Astro adapter={adapter}, output={output}.")
            port = _port(cfg) or _port(dev) or 4321
            if adapter == "vercel" and output in {"server", "hybrid"}:
                if not dev:
                    check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "blocker", [cf] if cf else [], "Vercel SSR has no deterministic local runtime without a dev server.")
                else:
                    spec.build.update({"runtime_strategy": "dev-server-fallback", "adapter": "vercel-serverless", "preview_supported": False})
                    spec.processes[0]["start_command"] = f"{pm} run dev -- --host 0.0.0.0 --port {port}"
                    check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Vercel SSR verified through the repository dev server.")
            elif adapter == "node" and output in {"server", "hybrid"}:
                spec.build.update({"runtime_strategy": "node-standalone", "adapter": "node"})
                spec.processes[0]["start_command"] = "node ./dist/server/entry.mjs"
                check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Astro Node adapter provides a standalone server entrypoint.")
            elif output == "static":
                spec.build.update({"runtime_strategy": "static-preview", "adapter": adapter})
                spec.processes[0]["start_command"] = f"{pm} run preview -- --host 0.0.0.0 --port {port}"
                check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "pass", [cf] if cf else [], "Static Astro output can be served by preview.")
            else:
                check("RUNTIME_COMPATIBILITY", "Container runtime compatibility", "blocker", [cf] if cf else [], "Unknown Astro adapter/runtime combination.")
            spec.network["port"] = port

        elif framework in {"Next.js", "Nuxt", "NestJS"}:
            port = _port(repo.corpus, 3000)
            spec.network["port"] = port
            if start:
                if framework in {"Next.js", "Nuxt"}:
                    spec.processes[0]["start_command"] = f"{pm} run start -- --hostname 0.0.0.0 --port {port}"
                else:
                    spec.processes[0]["start_command"] = start
                spec.build["runtime_strategy"] = "node-framework"
            elif dev:
                check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "Only a development command is available for a server framework.")
            else:
                check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "No production runtime command was resolved.")

        elif framework in {"Vite", "React", "Vue", "Angular", "Svelte"} and build and not start:
            out = "build" if framework == "React" and "react-scripts" in str(pkg.get("dependencies", {})) else "dist"
            spec.build.update({"runtime_strategy": "static-node", "output": out})
            spec.network["port"] = 8080
            spec.processes[0]["start_command"] = 'nginx -g "daemon off;"'
            check("STATIC_BUILD", "Static build output", "pass", ["package.json"], f"{framework} build will be served from {out}/.")

        else:
            port = _port(repo.corpus, 3000)
            spec.network["port"] = port
            if start:
                spec.processes[0]["start_command"] = start
                spec.build["runtime_strategy"] = "node-script"
            elif dev:
                check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "Only a development command is available.")
            else:
                check("RUNTIME_COMPATIBILITY", "Production runtime", "blocker", ["package.json"], "No deterministic Node runtime command was resolved.")

    elif primary == "Python":
        manifests = [x for x in ("requirements.txt", "pyproject.toml", "Pipfile") if x in repo.file_set]
        check("PYTHON_MANIFEST", "Python dependency manifest", "pass" if manifests else "blocker", manifests, "Supported dependency manifest detected." if manifests else "No supported dependency manifest.")
        port = _port(repo.corpus, 8000)
        fw = result["summary"].get("framework")
        start = None
        if fw == "Django":
            wsgi = next((f for f in repo.files if f.endswith("wsgi.py")), None)
            if wsgi:
                mod = Path(wsgi).with_suffix("").as_posix().replace("/", ".")
                start = f"gunicorn {mod}:application --bind 0.0.0.0:{port}"
                spec.build["runtime_strategy"] = "python-gunicorn"
        elif fw in {"FastAPI", "Litestar", "Sanic"}:
            f = next((x for x in repo.files if Path(x).name in {"main.py", "app.py", "server.py"}), None)
            if f:
                mod = Path(f).with_suffix("").as_posix().replace("/", ".")
                start = f"uvicorn {mod}:app --host 0.0.0.0 --port {port}"
                spec.build["runtime_strategy"] = "python-uvicorn"
        elif fw == "Flask":
            f = next((x for x in repo.files if Path(x).name in {"app.py", "main.py"}), None)
            if f:
                mod = Path(f).with_suffix("").as_posix().replace("/", ".")
                start = f"gunicorn {mod}:app --bind 0.0.0.0:{port}"
                spec.build["runtime_strategy"] = "python-gunicorn"
        if start:
            spec.processes[0]["start_command"] = start
            spec.network["port"] = port
            check("PYTHON_ENTRYPOINT", "Production web entrypoint", "pass", [], start)
        else:
            check("PYTHON_ENTRYPOINT", "Production web entrypoint", "blocker", [], "No deterministic WSGI/ASGI entrypoint was identified.")

    elif primary == "Go":
        check("GO_MODULE", "Go module", "pass" if "go.mod" in repo.file_set else "blocker", ["go.mod"] if "go.mod" in repo.file_set else [], "go.mod controls dependencies.")
        target = _go_target(repo)
        if not target:
            check("GO_ENTRYPOINT", "Go main package", "blocker", [], "No package main + func main entrypoint was identified.")
        else:
            command = f'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app {target}'
            spec.build.update({"runtime_strategy": "go-binary", "container_command": command, "source_package": target})
            spec.processes[0]["start_command"] = "/app"
            spec.network["port"] = _port(repo.corpus, 8080)
            check("GO_ENTRYPOINT", "Go main package", "pass", [], f"Building {target}.")

    elif primary == "Rust":
        check("RUST_MANIFEST", "Cargo manifest", "pass" if "Cargo.toml" in repo.file_set else "blocker", ["Cargo.toml"] if "Cargo.toml" in repo.file_set else [], "Cargo manifest detected.")
        if "Cargo.toml" in repo.file_set:
            binary = _rust_binary(repo)
            spec.build.update({"runtime_strategy": "rust-binary", "binary": binary, "container_command": "cargo build --release"})
            spec.processes[0]["start_command"] = f"/app/{binary}"
            spec.network["port"] = _port(repo.corpus, 8080)

    elif primary == "Java":
        manifest = next((x for x in ("pom.xml", "build.gradle", "build.gradle.kts") if x in repo.file_set), None)
        check("JVM_BUILD", "JVM build manifest", "pass" if manifest else "blocker", [manifest] if manifest else [], "Maven/Gradle build detected." if manifest else "No JVM build manifest.")
        if manifest:
            text = repo.read(manifest).lower()
            spring = "spring-boot" in text or "org.springframework.boot" in text
            if not spring:
                check("JVM_ENTRYPOINT", "JVM web runtime", "blocker", [manifest], "Only Spring Boot JAR runtime is currently deterministic.")
            else:
                manager = "gradle" if manifest.startswith("build.gradle") else "maven"
                if manager == "gradle" and "gradlew" in repo.file_set:
                    cmd = "./gradlew bootJar --no-daemon"
                elif manager == "gradle":
                    cmd = "gradle bootJar --no-daemon"
                elif "mvnw" in repo.file_set:
                    cmd = "./mvnw -B -DskipTests package"
                else:
                    cmd = "mvn -B -DskipTests package"
                spec.build.update({"runtime_strategy": "jvm-jar", "container_command": cmd, "jvm_manager": manager})
                spec.processes[0]["start_command"] = "java -jar /app/app.jar"
                spec.network["port"] = _port(repo.corpus, 8080)
                check("JVM_ENTRYPOINT", "JVM web runtime", "pass", [manifest], "Spring Boot executable JAR strategy selected.")

    elif primary == "C#":
        cs = next((f for f in repo.files if f.endswith(".csproj")), None)
        check("DOTNET_PROJECT", ".NET project", "pass" if cs else "blocker", [cs] if cs else [], "Project file detected." if cs else "No .csproj found.")
        if cs:
            text = repo.read(cs)
            tfm = re.search(r"<TargetFramework[^>]*>([^<]+)", text, re.I)
            name = Path(cs).stem
            spec.runtime["version"] = tfm.group(1) if tfm else "net8.0"
            spec.build.update({"runtime_strategy": "dotnet-publish", "project_file": cs, "assembly": name})
            spec.processes[0]["start_command"] = f"dotnet /app/{name}.dll"
            spec.network["port"] = _port(repo.corpus, 8080)

    elif primary == "PHP":
        composer = "composer.json" in repo.file_set
        public = any(f.startswith("public/") for f in repo.files)
        index = any(Path(f).name == "index.php" for f in repo.files)
        check("PHP_COMPOSER", "Composer manifest", "pass" if composer else "warning", ["composer.json"] if composer else [], "Composer dependencies detected." if composer else "No composer.json.")
        check("PHP_ENTRYPOINT", "PHP document root", "pass" if public or index else "blocker", [], "Web entrypoint identified." if public or index else "No deterministic document root.")
        if public or index:
            spec.build.update({"runtime_strategy": "php-apache", "document_root": "public" if public else "."})
            spec.network["port"] = 80
            spec.processes[0]["start_command"] = "apache2-foreground"

    elif primary == "Ruby":
        check("RUBY_BUNDLE", "Bundler manifest", "pass" if "Gemfile" in repo.file_set else "blocker", ["Gemfile"] if "Gemfile" in repo.file_set else [], "Gemfile detected." if "Gemfile" in repo.file_set else "No Gemfile.")
        if "Gemfile" in repo.file_set:
            if "bin/rails" in repo.file_set or "config/application.rb" in repo.file_set:
                spec.build["runtime_strategy"] = "ruby-rails"
                spec.processes[0]["start_command"] = f"bundle exec rails server -b 0.0.0.0 -p {_port(repo.corpus, 3000)}"
            elif "config.ru" in repo.file_set:
                spec.build["runtime_strategy"] = "ruby-rack"
                spec.processes[0]["start_command"] = f"bundle exec rackup -o 0.0.0.0 -p {_port(repo.corpus, 3000)}"
            else:
                check("RUBY_ENTRYPOINT", "Ruby web entrypoint", "blocker", [], "No Rails or Rack entrypoint identified.")
            spec.network["port"] = _port(repo.corpus, 3000)

    else:
        check("UNSUPPORTED_TARGET", "Deployable target identification", "blocker", [], f"No deterministic deployment strategy for {primary}.")

    if spec.project.get("monorepo"):
        check("MONOREPO_TARGET", "Monorepo deployment target", "blocker", [], "Monorepo detected but no workspace/package target was selected; generation will not guess.")
    if "Dockerfile" in repo.file_set:
        check("EXISTING_DOCKERFILE", "Existing Dockerfile", "warning", ["Dockerfile"], "Existing Dockerfile is evidence only.")
    if spec.environment.get("secret_files"):
        check("SECRET_FILES", "Repository secret files", "warning", spec.environment["secret_files"], "Secret-bearing files must not enter an image.")

    confidence = 100 - min(20, len(warnings) * 3) if not blockers else 0
    result["deep_analysis"] = {
        "status": "ready" if not blockers else "blocked",
        "confidence": confidence,
        "checks": checks,
        "warnings": warnings,
        "blockers": blockers,
        "decisions": decisions,
        "script_inventory": {k: _script(pkg, k) for k in ("build", "start", "dev", "preview", "serve") if _script(pkg, k)},
    }
    spec.project.update({"deep_analysis_status": result["deep_analysis"]["status"], "deep_analysis_confidence": confidence, "container_decisions": decisions})
    return result["deep_analysis"]
