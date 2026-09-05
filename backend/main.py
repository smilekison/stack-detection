from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from pathlib import Path
from collections import defaultdict
import tempfile, subprocess, shutil, re, json

app = FastAPI(title="AutoDeploy Stack Detection Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", "dist", "build", "target", "vendor", ".terraform", ".pytest_cache", ".mypy_cache", ".gradle", ".idea", ".vscode", "coverage", "bin", "obj"}
TEXT_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java", ".kt", ".kts", ".cs", ".php", ".rb", ".swift", ".dart", ".scala", ".sh", ".bash", ".md", ".json", ".yaml", ".yml", ".toml", ".xml", ".gradle", ".properties", ".env", ".ini", ".conf"}


def read_file(path: Path, limit=120_000):
    try:
        return path.read_text(errors="ignore")[:limit]
    except Exception:
        return ""


def repo_files(root: Path):
    output = []
    for p in root.rglob("*"):
        if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts):
            output.append(p.relative_to(root).as_posix())
    return output


def ev(points, file, reason, category):
    return {"points": points, "file": file, "reason": reason, "category": category}


def parse_json(path: Path):
    try:
        return json.loads(read_file(path))
    except Exception:
        return {}


def detect(root: Path):
    fs = repo_files(root)
    s = set(fs)
    interesting = [x for x in fs if Path(x).suffix.lower() in TEXT_EXTENSIONS]
    corpus = "\n".join(f"\n--- {x} ---\n{read_file(root / x, 28_000)}" for x in interesting[:600])
    low = corpus.lower()
    evidence = []

    # Programming languages
    language_signals = []
    def lang(name, points, file, reason):
        language_signals.append((name, points))
        evidence.append(ev(points, file, reason, "language"))

    if "package.json" in s: lang("JavaScript", 45, "package.json", "Node ecosystem manifest detected")
    if "tsconfig.json" in s or any(x.endswith((".ts", ".tsx")) for x in fs): lang("TypeScript", 55 if "tsconfig.json" in s else 35, "tsconfig.json" if "tsconfig.json" in s else "source files", "TypeScript configuration/source files detected")
    if any(x in s for x in ("requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "uv.lock")) or any(x.endswith(".py") for x in fs): lang("Python", 50 if any(x in s for x in ("requirements.txt", "pyproject.toml")) else 25, next((x for x in ("pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock", "uv.lock") if x in s), "source files"), "Python dependency manifest/source files detected")
    if "go.mod" in s: lang("Go", 60, "go.mod", "Go module manifest detected")
    if "Cargo.toml" in s: lang("Rust", 60, "Cargo.toml", "Rust package manifest detected")
    if "pom.xml" in s or "build.gradle" in s or "build.gradle.kts" in s: lang("Java", 55, next((x for x in ("pom.xml", "build.gradle", "build.gradle.kts") if x in s), "build config"), "JVM build manifest detected")
    csproj = next((x for x in fs if x.endswith(".csproj")), None)
    if csproj or any(x.endswith(".sln") for x in fs): lang("C#", 60, csproj or next(x for x in fs if x.endswith(".sln")), ".NET project detected")
    if "composer.json" in s or any(x.endswith(".php") for x in fs): lang("PHP", 50, "composer.json" if "composer.json" in s else "PHP source files", "PHP application markers detected")
    if "Gemfile" in s or any(x.endswith(".rb") for x in fs): lang("Ruby", 50, "Gemfile" if "Gemfile" in s else "Ruby source files", "Ruby application markers detected")
    if "Package.swift" in s or any(x.endswith(".swift") for x in fs): lang("Swift", 50, "Package.swift" if "Package.swift" in s else "Swift source files", "Swift package/source detected")
    if "pubspec.yaml" in s or any(x.endswith(".dart") for x in fs): lang("Dart", 50, "pubspec.yaml" if "pubspec.yaml" in s else "Dart source files", "Dart package/source detected")
    if "mix.exs" in s or any(x.endswith(".ex") for x in fs): lang("Elixir", 50, "mix.exs" if "mix.exs" in s else "Elixir source files", "Elixir project detected")

    language_scores = sorted(language_signals, key=lambda x: x[1], reverse=True)
    language = language_scores[0][0] if language_scores else "Unknown"
    if any(n == "TypeScript" and p >= 45 for n, p in language_scores): language = "TypeScript"

    # Package manager / runtime
    package_manager = "Unknown"
    package_manager_version = None
    if "pnpm-lock.yaml" in s: package_manager = "pnpm"
    elif "yarn.lock" in s: package_manager = "yarn"
    elif "bun.lock" in s or "bun.lockb" in s: package_manager = "bun"
    elif "package-lock.json" in s: package_manager = "npm"
    elif "uv.lock" in s: package_manager = "uv"
    elif "poetry.lock" in s: package_manager = "poetry"
    elif "Pipfile.lock" in s: package_manager = "pipenv"
    elif "requirements.txt" in s: package_manager = "pip"
    elif "go.mod" in s: package_manager = "go modules"
    elif "Cargo.lock" in s: package_manager = "cargo"
    elif "pom.xml" in s: package_manager = "maven"
    elif "build.gradle" in s or "build.gradle.kts" in s: package_manager = "gradle"
    elif "composer.lock" in s: package_manager = "composer"
    elif "Gemfile.lock" in s: package_manager = "bundler"
    if package_manager != "Unknown": evidence.append(ev(35, next((x for x in ("pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "package-lock.json", "uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt", "go.mod", "Cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts", "composer.lock", "Gemfile.lock") if x in s), "package manifest"), f"{package_manager} dependency management detected", "package_manager"))

    runtime, runtime_version = "Unknown", "Not declared"
    if language in ("JavaScript", "TypeScript"):
        runtime = "Node.js"
        for vf in (".nvmrc", ".node-version"):
            if vf in s:
                runtime_version = read_file(root / vf).strip().splitlines()[0]
                evidence.append(ev(40, vf, "Node runtime version explicitly declared", "runtime")); break
        if runtime_version == "Not declared" and "package.json" in s:
            node_constraint = parse_json(root / "package.json").get("engines", {}).get("node")
            if node_constraint:
                runtime_version = node_constraint; evidence.append(ev(28, "package.json", "Node engine constraint detected", "runtime"))
    elif language == "Python":
        runtime = "Python"
        for vf in (".python-version", "runtime.txt"):
            if vf in s:
                runtime_version = read_file(root / vf).strip().splitlines()[0]
                evidence.append(ev(40, vf, "Python runtime version explicitly declared", "runtime")); break
        if runtime_version == "Not declared" and "pyproject.toml" in s:
            txt = read_file(root / "pyproject.toml")
            m = re.search(r'(?:requires-python|python)\s*=\s*["\']([^"\']+)', txt, re.I)
            if m: runtime_version = m.group(1); evidence.append(ev(28, "pyproject.toml", "Python version constraint detected", "runtime"))
    elif language == "Go":
        runtime = "Go"
        m = re.search(r'^go\s+([0-9.]+)', read_file(root / "go.mod"), re.M)
        if m: runtime_version = m.group(1); evidence.append(ev(40, "go.mod", "Go toolchain version declared", "runtime"))
    elif language == "Rust": runtime = "Rust"
    elif language == "Java":
        runtime = "JDK"
        if "pom.xml" in s:
            m = re.search(r'<(?:maven.compiler.release|java.version)>([^<]+)</', read_file(root / "pom.xml"))
            if m: runtime_version = m.group(1); evidence.append(ev(35, "pom.xml", "Java compiler/runtime version declared", "runtime"))
    elif language == "C#":
        runtime = ".NET"
        if csproj:
            m = re.search(r'<TargetFramework[^>]*>([^<]+)</TargetFramework>', read_file(root / csproj))
            if m: runtime_version = m.group(1); evidence.append(ev(40, csproj, ".NET target framework detected", "runtime"))

    # Framework candidates
    framework_candidates = []
    package_json = parse_json(root / "package.json") if "package.json" in s else {}
    deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}
    for label, dep, pts in [("Next.js","next",60),("Nuxt","nuxt",60),("NestJS","@nestjs/core",60),("Express","express",58),("Fastify","fastify",58),("Koa","koa",54),("Hono","hono",54),("Remix","@remix-run/node",58),("SvelteKit","@sveltejs/kit",58),("Angular","@angular/core",55),("React","react",48),("Vue","vue",48),("Vite","vite",42),("Astro","astro",55)]:
        if dep in deps: framework_candidates.append((label, pts, ev(pts, "package.json", f"{label} dependency detected", "framework")))
    python_text = "\n".join(read_file(root / fn).lower() for fn in ("requirements.txt", "pyproject.toml", "Pipfile") if fn in s)
    for label, dep, pts in [("Django","django",60),("FastAPI","fastapi",60),("Flask","flask",55),("Litestar","litestar",55),("Sanic","sanic",55),("Tornado","tornado",50)]:
        if dep in python_text: framework_candidates.append((label, pts, ev(pts, "Python dependency manifest", f"{label} dependency detected", "framework")))
    if language == "Go" and "go.mod" in s:
        gt = read_file(root / "go.mod").lower()
        for label, dep in (("Gin","github.com/gin-gonic/gin"),("Echo","github.com/labstack/echo"),("Fiber","github.com/gofiber/fiber"),("Chi","github.com/go-chi/chi")):
            if dep in gt: framework_candidates.append((label,55,ev(55,"go.mod",f"{label} framework module detected","framework")))
    if language == "Java":
        jt = (read_file(root / "pom.xml") if "pom.xml" in s else read_file(root / "build.gradle") if "build.gradle" in s else "").lower()
        for label, needle, pts in (("Spring Boot","spring-boot",65),("Quarkus","quarkus",60),("Micronaut","micronaut",60)):
            if needle in jt: framework_candidates.append((label,pts,ev(pts,"Java build manifest",f"{label} dependency/plugin detected","framework")))
    framework = "Unknown"
    if framework_candidates:
        framework, _, fe = max(framework_candidates, key=lambda x: x[1]); evidence.append(fe)

    # Build/start commands and outputs
    build_command, start_command, build_output = "Not detected", "Not detected", "Not detected"
    if "package.json" in s:
        scripts = package_json.get("scripts", {})
        build_command = scripts.get("build", build_command); start_command = scripts.get("start", scripts.get("serve", start_command))
        if build_command != "Not detected":
            if ".next" in build_command: build_output = ".next/"
            elif "dist" in build_command: build_output = "dist/"
            elif "build" in build_command: build_output = "build/"
        if "build" in scripts: evidence.append(ev(25,"package.json",f"build script detected: {scripts['build']}","commands"))
        if "start" in scripts: evidence.append(ev(25,"package.json",f"start script detected: {scripts['start']}","commands"))
    if build_command == "Not detected":
        if "Makefile" in s and re.search(r'^build:', read_file(root / "Makefile"), re.M): build_command = "make build"; evidence.append(ev(35,"Makefile","build target detected","commands"))
        elif language == "Go": build_command = "go build -o app ."
        elif language == "Rust": build_command = "cargo build --release"
    if start_command == "Not detected":
        if language in ("JavaScript", "TypeScript"):
            if framework == "Next.js": start_command = "npm run start"
            elif any(x in s for x in ("server.js","server.ts","src/server.js","src/server.ts")): start_command = "node dist/server.js" if any("dist" in x for x in s) else "node server.js"
        elif language == "Python":
            if framework == "Django": start_command = "gunicorn project.wsgi:application"
            elif framework in ("FastAPI","Litestar","Sanic"): start_command = "uvicorn main:app --host 0.0.0.0 --port 8000"
            else:
                py_entry = next((x for x in ("main.py","app.py","src/main.py","src/app.py") if x in s), None)
                if py_entry: start_command = f"python {py_entry}"
        elif language in ("Go","Rust"): start_command = "./app"

    # Network / port
    port = None
    for pat in (r'PORT\s*[:=]\s*["\']?(\d{2,5})', r'\.listen\s*\(\s*([\d]{2,5})', r'--port\s+(\d{2,5})'):
        m = re.search(pat, corpus, re.I)
        if m:
            try: port = int(m.group(1)); break
            except ValueError: pass
    if not port: port = 3000 if framework in ("Next.js","React","Vue","Vite","Express","NestJS","Fastify","Hono","SvelteKit","Nuxt") else 8000 if language == "Python" else 8080 if language in ("Go","Java","C#") else None
    if port: evidence.append(ev(18 if re.search(r'PORT|listen|--port', corpus, re.I) else 10, "source/config", f"Application port detected/inferred as {port}", "network"))

    # Services / integrations
    service_patterns = {
        "PostgreSQL": ["pg", "postgres", "postgresql", "psycopg", "asyncpg", "prisma"], "MySQL": ["mysql", "mysql2", "pymysql"], "MariaDB": ["mariadb"], "MongoDB": ["mongodb", "mongoose", "motor"], "Redis": ["redis", "ioredis", "redis-py"], "RabbitMQ": ["rabbitmq", "amqp", "pika", "aio-pika"], "Kafka": ["kafka", "kafkajs", "confluent-kafka"], "Elasticsearch": ["elasticsearch", "opensearch"], "S3/Object Storage": ["s3", "aws-sdk", "boto3", "minio"], "Supabase": ["supabase"], "Firebase": ["firebase"], "Stripe": ["stripe"]}
    combined = low + "\n" + json.dumps(deps).lower()
    services = []
    for service, needles in service_patterns.items():
        hits = [n for n in needles if n in combined]
        if hits: services.append(service); evidence.append(ev(22,"dependency/source files",f"{service} integration detected ({', '.join(hits[:3])})","service"))

    # Environment variables
    env_names = set()
    for pat in (r'process\.env\.([A-Z][A-Z0-9_]{2,})', r'process\.env\[\s*["\']([A-Z][A-Z0-9_]{2,})["\']\s*\]', r'os\.getenv\(\s*["\']([A-Z][A-Z0-9_]{2,})["\']', r'os\.environ\[["\']([A-Z][A-Z0-9_]{2,})["\']\]', r'getenv\(["\']([A-Z][A-Z0-9_]{2,})["\']'):
        env_names.update(re.findall(pat, corpus))
    if ".env.example" in s:
        for line in read_file(root / ".env.example").splitlines():
            m = re.match(r'\s*([A-Z][A-Z0-9_]{2,})\s*=', line)
            if m: env_names.add(m.group(1))
        evidence.append(ev(30, ".env.example", "Example environment variables documented", "environment"))

    # CI / deployment artifacts
    deployment_files = [x for x in fs if Path(x).name.lower() in {"dockerfile","compose.yaml","compose.yml","docker-compose.yml","makefile","serverless.yml","vercel.json","netlify.toml","fly.toml","render.yaml"} or x.startswith((".github/workflows/","terraform/","helm/","k8s/","kubernetes/","infra/"))]
    if deployment_files: evidence.append(ev(30, deployment_files[0], "Existing deployment/infrastructure configuration found", "deployment"))
    ci_files = [x for x in fs if x.startswith(".github/workflows/") or x.startswith(".gitlab/") or x in {"azure-pipelines.yml", ".circleci/config.yml"}]
    ci_signals = []
    for x in ci_files:
        txt = read_file(root / x, 60_000)
        if "actions/setup-node" in txt: ci_signals.append("Node.js")
        if "actions/setup-python" in txt: ci_signals.append("Python")
        if "actions/setup-java" in txt: ci_signals.append("Java")
        if "docker build" in txt or "docker/build-push-action" in txt: ci_signals.append("Docker")
        if "terraform" in txt.lower(): ci_signals.append("Terraform")
        evidence.append(ev(15, x, "CI/CD workflow detected", "ci"))

    monorepo = bool({"pnpm-workspace.yaml","turbo.json","nx.json","lerna.json"}.intersection(s))
    workspace_files = [x for x in fs if x.startswith(("apps/","packages/","services/"))]
    if workspace_files: monorepo = True; evidence.append(ev(25, workspace_files[0], "Workspace-style monorepo directory detected", "architecture"))
    elif monorepo: evidence.append(ev(30, next(x for x in ("pnpm-workspace.yaml","turbo.json","nx.json","lerna.json") if x in s), "Monorepo workspace configuration detected", "architecture"))

    roles = ["web"]
    if any(x in low for x in ("celery","bullmq","bull","sidekiq","hangfire","rq","dramatiq")): roles.append("worker"); evidence.append(ev(25,"dependency/source files","Background worker framework detected","architecture"))
    if any(x in low for x in ("cron","scheduler","apscheduler","node-cron","agenda")): roles.append("scheduler"); evidence.append(ev(20,"dependency/source files","Scheduler/cron signal detected","architecture"))
    if "consumer" in low or "kafkaconsumer" in low: roles.append("consumer"); evidence.append(ev(20,"source files","Message consumer signal detected","architecture"))

    health_endpoint = next((c for c in ("/health","/healthz","/ready","/readiness","/live") if c in corpus), None)
    if health_endpoint: evidence.append(ev(20,"source files",f"Health/readiness endpoint detected: {health_endpoint}","health"))

    confidence = min(99, max(0, int(45 + min(language_scores[0][1] if language_scores else 0, 60)*0.45 + min(len(evidence),30)*0.8))) if language_scores else 0
    summary = {
        "language": language, "language_candidates": [{"name": n, "score": p} for n,p in language_scores[:8]], "runtime": runtime, "runtime_version": runtime_version,
        "framework": framework, "package_manager": package_manager, "package_manager_version": package_manager_version or "Not declared", "build_command": build_command,
        "build_output": build_output, "start_command": start_command, "port": port, "services": services, "environment_variables": sorted(env_names),
        "monorepo": monorepo, "application_roles": sorted(set(roles)), "health_endpoint": health_endpoint or "Not detected", "ci_signals": sorted(set(ci_signals)),
        "existing_deployment_files": deployment_files, "confidence": confidence}
    return {"summary": summary, "evidence": sorted(evidence, key=lambda x:x["points"], reverse=True), "files": fs[:1000]}


def command_array(command: str): return json.dumps(command.split())


def generate_compose(d, port):
    s=d["summary"]; services=s["services"]
    lines=["services:","  app:","    build:","      context: .","      dockerfile: Dockerfile","    ports:",f'      - "{port}:{port}"',"    restart: unless-stopped"]
    if "PostgreSQL" in services: lines += ["","  postgres:","    image: postgres:16","    environment:","      POSTGRES_DB: app","      POSTGRES_USER: app","      POSTGRES_PASSWORD: change-me","    volumes:","      - postgres_data:/var/lib/postgresql/data"]
    if "Redis" in services: lines += ["","  redis:","    image: redis:7","    restart: unless-stopped"]
    if "MySQL" in services or "MariaDB" in services:
        image="mariadb:11" if "MariaDB" in services else "mysql:8"
        lines += ["", "  mysql:", f"    image: {image}", "    environment:", "      MYSQL_DATABASE: app", "      MYSQL_USER: app", "      MYSQL_PASSWORD: change-me", "      MYSQL_ROOT_PASSWORD: change-me-root", "    volumes:", "      - mysql_data:/var/lib/mysql"]
    vols=[]
    if "PostgreSQL" in services: vols.append("  postgres_data:")
    if "MySQL" in services or "MariaDB" in services: vols.append("  mysql_data:")
    if vols: lines += ["","volumes:"] + vols
    return "\n".join(lines)+"\n"


def generate_artifacts(d):
    s=d["summary"]; lang=s["language"]; port=s["port"] or 3000; pm=s["package_manager"]; version_raw=s["runtime_version"]
    dockerfile="# Generated by AutoDeploy Stack Detection\n"; warnings=[]
    if lang in ("JavaScript","TypeScript"):
        mv=re.search(r"\d+(?:\.\d+)?", version_raw or ""); node_version=mv.group(0) if mv else "20"
        lock={"pnpm":"pnpm-lock.yaml","yarn":"yarn.lock","npm":"package-lock.json","bun":"bun.lock"}.get(pm,"package-lock.json")
        if pm=="pnpm": setup="RUN corepack enable && corepack prepare pnpm@latest --activate"; install="RUN pnpm install --frozen-lockfile"; prod="RUN pnpm install --prod --frozen-lockfile"
        elif pm=="yarn": setup="RUN corepack enable"; install="RUN yarn install --immutable"; prod="RUN yarn install --immutable --production=true"
        elif pm=="bun": setup="RUN npm install -g bun"; install="RUN bun install --frozen-lockfile"; prod="RUN bun install --frozen-lockfile --production"
        else: setup=""; install="RUN npm ci"; prod="RUN npm ci --omit=dev"
        build=s["build_command"] if s["build_command"]!="Not detected" else "npm run build"; start=s["start_command"] if s["start_command"]!="Not detected" else "node dist/server.js"; output=s["build_output"] if s["build_output"]!="Not detected" else "dist/"
        copy_lock=lock if lock in d["files"] else "package.json"
        dockerfile += f"""FROM node:{node_version}-bookworm-slim AS deps
WORKDIR /app
COPY package.json {copy_lock} ./
{setup}
{install}

FROM deps AS build
COPY . .
RUN {build}

FROM node:{node_version}-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT={port}
COPY package.json {copy_lock} ./
{setup}
{prod}
COPY --from=build /app/{output.rstrip('/')} ./{output.rstrip('/')}
USER node
EXPOSE {port}
"""
        dockerfile += 'CMD ["npm", "run", "start"]\n' if s["framework"]=="Next.js" else f"CMD {command_array(start)}\n"
    elif lang=="Python":
        pmatch=re.search(r"\d+\.\d+",version_raw or ""); py=pmatch.group(0) if pmatch else "3.12"; start=s["start_command"] if s["start_command"]!="Not detected" else "uvicorn main:app --host 0.0.0.0 --port 8000"
        install="COPY requirements.txt ./\nRUN pip install --no-cache-dir -r requirements.txt" if "requirements.txt" in d["files"] else "COPY pyproject.toml ./\nRUN pip install --no-cache-dir ."
        dockerfile += f"""FROM python:{py}-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
{install}
COPY . .
RUN useradd --create-home appuser
USER appuser
EXPOSE {port}
CMD {command_array(start)}
"""
    elif lang=="Go":
        gv=re.search(r"\d+\.\d+",version_raw or ""); gv=gv.group(0) if gv else "1.24"
        dockerfile += f"""FROM golang:{gv} AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/app .

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/app /app
EXPOSE {port}
ENTRYPOINT [\"/app\"]
"""
    elif lang=="Rust":
        dockerfile += f"""FROM rust:1.88 AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock* ./
RUN cargo build --release || true
COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=build /src/target/release/* /usr/local/bin/app
EXPOSE {port}
ENTRYPOINT [\"/usr/local/bin/app\"]
"""; warnings.append("Rust binary name may need adjustment for multi-binary workspaces.")
    elif lang=="Java":
        if "pom.xml" in d["files"]:
            dockerfile += """FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml ./
RUN mvn -B -DskipTests dependency:go-offline
COPY . .
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT [\"java\",\"-jar\",\"app.jar\"]
"""
        else:
            dockerfile += """FROM gradle:8-jdk21 AS build
WORKDIR /app
COPY . .
RUN gradle build -x test

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT [\"java\",\"-jar\",\"app.jar\"]
"""
    elif lang=="C#":
        csproj=next((x for x in d["files"] if x.endswith(".csproj")),"app.csproj"); app_name=Path(csproj).stem
        dockerfile += f"""FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish {csproj} -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app/publish .
EXPOSE {port}
ENTRYPOINT [\"dotnet\",\"{app_name}.dll\"]
"""
    else:
        dockerfile += f"# Detected stack: {lang} / {s['framework']}.\n# No safe built-in production template exists yet for this stack.\n"; warnings.append("No safe production Dockerfile template exists yet for this language.")
    return {"Dockerfile":dockerfile,"compose.yaml":generate_compose(d,port),".dockerignore":".git\n.github\n.env\n.env.*\nnode_modules\n__pycache__\n*.pyc\n.venv\nvenv\ncoverage\n*.log\nDockerfile\ncompose.yaml\ndocker-compose.yml\n","warnings":warnings}


def build_ir(d, artifacts):
    s=d["summary"]
    return {"schema_version":"0.2","project":{"name":"repository","monorepo":s["monorepo"],"roles":s["application_roles"]},"runtime":{"language":s["language"],"runtime":s["runtime"],"version":s["runtime_version"],"package_manager":s["package_manager"],"package_manager_version":s["package_manager_version"]},"framework":{"name":s["framework"]},"build":{"command":s["build_command"],"output":s["build_output"]},"start":{"command":s["start_command"]},"network":{"port":s["port"],"health_endpoint":s["health_endpoint"]},"dependencies":{"services":s["services"]},"environment":{"required_or_observed":s["environment_variables"]},"ci_cd":{"signals":s["ci_signals"]},"existing_deployment":{"files":s["existing_deployment_files"]},"generation":{"dockerfile":artifacts["Dockerfile"],"compose":artifacts["compose.yaml"],"dockerignore":artifacts[".dockerignore"]}}

@app.get("/health")
def health(): return {"status":"ok","service":"stack-detection"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    tmp=tempfile.mkdtemp(prefix="stack-detection-"); target=Path(tmp)/"repo"
    try:
        r=subprocess.run(["git","clone","--depth","1",str(req.repo_url),str(target)],capture_output=True,text=True,timeout=120)
        if r.returncode: raise HTTPException(400,"Git clone failed: "+r.stderr[-1800:])
        d=detect(target); artifacts=generate_artifacts(d); d["generated_files"]=artifacts; d["deployment_ir"]=build_ir(d,artifacts); return d
    except subprocess.TimeoutExpired: raise HTTPException(408,"Repository clone timed out after 120 seconds")
    finally: shutil.rmtree(tmp,ignore_errors=True)
