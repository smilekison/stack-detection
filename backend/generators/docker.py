import json
import re
from pathlib import Path


def _tag(value, default):
    m = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?", str(value or ""))
    if not m:
        return default
    return m.group(1) + (("." + m.group(2)) if m.group(2) else "")


def _pm_info(spec):
    if not spec.package_managers:
        return "npm", "", None
    pm = spec.package_managers[0]
    return pm.get("name", "npm"), pm.get("version", ""), pm.get("evidence_file", "")


def _node_install(spec):
    pm, version, _ = _pm_info(spec)
    files = set(spec.project.get("files", []))
    if pm == "pnpm":
        lock = "pnpm-lock.yaml" if "pnpm-lock.yaml" in files else None
        pin = version if version and version != "bundled/default" else "10.15.0"
        setup = f"RUN corepack enable && corepack prepare pnpm@{pin} --activate"
        manifest = "COPY package.json" + (" pnpm-lock.yaml" if lock else "") + " ./"
        install = "RUN pnpm install --frozen-lockfile" if lock else "RUN pnpm install"
        return "pnpm", setup, manifest, install
    if pm == "yarn":
        lock = "yarn.lock" if "yarn.lock" in files else None
        pin = version if version and version != "bundled/default" else "1.22.22"
        setup = f"RUN corepack enable && corepack prepare yarn@{pin} --activate"
        manifest = "COPY package.json" + (" yarn.lock" if lock else "") + " ./"
        install = "RUN yarn install --immutable" if lock else "RUN yarn install"
        return "yarn", setup, manifest, install
    if pm == "bun":
        lock = "bun.lockb" if "bun.lockb" in files else ("bun.lock" if "bun.lock" in files else None)
        pin = version if version and version != "bundled/default" else "1.1.26"
        setup = f"RUN npm install -g bun@{pin}"
        manifest = "COPY package.json" + (f" {lock}" if lock else "") + " ./"
        install = "RUN bun install --frozen-lockfile" if lock else "RUN bun install"
        return "bun", setup, manifest, install
    lock = "package-lock.json" if "package-lock.json" in files else None
    manifest = "COPY package.json" + (" package-lock.json" if lock else "") + " ./"
    install = "RUN npm ci" if lock else "RUN npm install"
    return "npm", "", manifest, install


def _cmd(start):
    return json.dumps(["sh", "-c", start])


def _copy_user_setup():
    return "RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser"


def dockerfile(spec):
    rt = spec.runtime.get("name", "Unknown")
    port = spec.network.get("port") or 8000
    strategy = spec.build.get("runtime_strategy")
    start = spec.processes[0].get("start_command", "") if spec.processes else ""

    if rt == "Static Web":
        return """FROM nginxinc/nginx-unprivileged:1.27-alpine\nCOPY --chown=nginx:nginx . /usr/share/nginx/html\nEXPOSE 8080\nCMD [\"nginx\", \"-g\", \"daemon off;\"]\n"""

    if rt == "Node.js":
        node = _tag(spec.runtime.get("version"), "20")
        pm, setup, manifest, install = _node_install(spec)
        build = spec.build.get("container_command") or f"{pm} run build"
        if strategy == "dev-server-fallback":
            runtime_cmd = start or f"{pm} run dev -- --host 0.0.0.0 --port {port}"
            return f"""FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_copy_user_setup()}\nCOPY --from=build --chown=10001:10001 /app /app\nENV HOST=0.0.0.0 PORT={port}\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(runtime_cmd)}\n"""
        if strategy == "node-standalone":
            return f"""FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_copy_user_setup()}\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port}\nCOPY --from=build --chown=10001:10001 /app/dist ./dist\nCOPY --from=build --chown=10001:10001 /app/node_modules ./node_modules\nUSER 10001\nEXPOSE {port}\nCMD [\"node\", \"./dist/server/entry.mjs\"]\n"""
        if strategy == "static-preview":
            return f"""FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\nCOPY --from=build /app /app\nENV HOST=0.0.0.0 PORT={port}\nEXPOSE {port}\nCMD {_cmd(f'{pm} run preview -- --host 0.0.0.0 --port {port}')}\n"""
        if strategy == "static-node":
            output = str(spec.build.get("output") or "dist").strip("/")
            return f"""FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime\nCOPY --from=build --chown=nginx:nginx /app/{output}/ /usr/share/nginx/html/\nEXPOSE 8080\nCMD [\"nginx\", \"-g\", \"daemon off;\"]\n"""
        if not start:
            raise ValueError("No verified Node runtime command was resolved.")
        return f"""FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_copy_user_setup()}\nCOPY --from=build --chown=10001:10001 /app /app\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port}\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(start)}\n"""

    if rt == "Python":
        py = _tag(spec.runtime.get("version"), "3.12")
        files = set(spec.project.get("files", []))
        if "requirements.txt" in files:
            install = "pip install --no-cache-dir -r requirements.txt"
        elif "pyproject.toml" in files:
            install = "pip install --no-cache-dir ."
        elif "Pipfile" in files:
            install = "pip install --no-cache-dir pipenv && pipenv install --system --deploy"
        else:
            raise ValueError("No verified Python dependency manifest was resolved.")
        strategy_server = "uvicorn" if spec.build.get("runtime_strategy") == "python-uvicorn" else ("gunicorn" if spec.build.get("runtime_strategy") == "python-gunicorn" else None)
        if strategy_server:
            install += f" && pip install --no-cache-dir {strategy_server}"
        if not start:
            raise ValueError("No verified Python runtime command was resolved.")
        return f"""FROM python:{py}-slim AS runtime\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /app\nCOPY . .\nRUN {install}\n{_copy_user_setup()}\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(start)}\n"""

    if rt == "Go":
        command = spec.build.get("container_command") or "CGO_ENABLED=0 go build -trimpath -ldflags=\"-s -w\" -o /out/app ."
        files = set(spec.project.get("files", []))
        lock_copy = "COPY go.sum ./\n" if "go.sum" in files else ""
        return f"""FROM golang:{_tag(spec.runtime.get('version'), '1.24')}-bookworm AS build\nWORKDIR /src\nCOPY go.mod ./\n{lock_copy}RUN go mod download\nCOPY . .\nRUN {command}\nFROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port}\nENTRYPOINT [\"/app\"]\n"""

    if rt == "Rust":
        binary = spec.build.get("binary", "app")
        command = spec.build.get("container_command") or "cargo build --release"
        files = set(spec.project.get("files", []))
        lock_copy = "COPY Cargo.lock ./\n" if "Cargo.lock" in files else ""
        return f"""FROM rust:{_tag(spec.runtime.get('version'), '1.88')}-bookworm AS build\nWORKDIR /src\nCOPY Cargo.toml ./\n{lock_copy}COPY . .\nRUN {command}\nFROM debian:bookworm-slim\n{_copy_user_setup()}\nCOPY --from=build /src/target/release/{binary} /app\nUSER 10001\nEXPOSE {port}\nENTRYPOINT [\"/app\"]\n"""

    if rt in {"JDK", "JVM"}:
        files = set(spec.project.get("files", []))
        if "gradlew" in files:
            build_cmd = "./gradlew bootJar --no-daemon" if strategy == "jvm-jar" else "./gradlew build --no-daemon"
            builder, artifact_dir = "eclipse-temurin:21-jdk", "/app/build/libs"
        elif "pom.xml" in files:
            build_cmd = "./mvnw -B -DskipTests package" if "mvnw" in files else "mvn -B -DskipTests package"
            builder, artifact_dir = "maven:3.9-eclipse-temurin-21", "/app/target"
        elif "build.gradle" in files or "build.gradle.kts" in files:
            build_cmd = "gradle bootJar --no-daemon" if strategy == "jvm-jar" else "gradle build --no-daemon"
            builder, artifact_dir = "gradle:8.10-jdk21", "/app/build/libs"
        else:
            raise ValueError("No verified Maven/Gradle build manifest was resolved.")
        return f"""FROM {builder} AS build\nWORKDIR /app\nCOPY . .\nRUN {build_cmd}\nRUN mkdir -p /out && cp \"$(find {artifact_dir} -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' | head -n 1)\" /out/app.jar\nFROM eclipse-temurin:21-jre\nWORKDIR /app\n{_copy_user_setup()}\nCOPY --from=build /out/app.jar /app/app.jar\nUSER 10001\nEXPOSE {port}\nENTRYPOINT [\"java\", \"-jar\", \"/app/app.jar\"]\n"""

    if rt == ".NET":
        project = spec.build.get("project_file")
        if not project:
            raise ValueError("No verified .csproj was resolved.")
        name = spec.build.get("assembly") or Path(project).stem
        tfm = str(spec.runtime.get("version", "net8.0"))
        m = re.search(r"net(\d+)(?:\.(\d+))?", tfm, re.I)
        net = f"{m.group(1)}.{m.group(2) or '0'}" if m else "8.0"
        return f"""FROM mcr.microsoft.com/dotnet/sdk:{net} AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet restore {project}\nRUN dotnet publish {project} -c Release --no-restore -o /out\nFROM mcr.microsoft.com/dotnet/aspnet:{net}\nWORKDIR /app\n{_copy_user_setup()}\nCOPY --from=build /out .\nUSER 10001\nENV ASPNETCORE_URLS=http://0.0.0.0:{port}\nEXPOSE {port}\nENTRYPOINT [\"dotnet\", \"/app/{name}.dll\"]\n"""

    if rt == "PHP":
        root = spec.build.get("document_root", ".")
        if "composer.json" in spec.project.get("files", []):
            doc = "/var/www/html/public" if root == "public" else "/var/www/html"
            files = set(spec.project.get("files", []))
            lock_copy = "COPY composer.lock ./\n" if "composer.lock" in files else ""
            return f"""FROM composer:2 AS deps\nWORKDIR /app\nCOPY composer.json ./\n{lock_copy}RUN composer install --no-dev --prefer-dist --no-interaction --no-progress --optimize-autoloader\nFROM php:8.3-apache\nWORKDIR /var/www/html\nRUN a2enmod rewrite\nCOPY --from=deps /app/vendor ./vendor\nCOPY . .\n""" + (f"ENV APACHE_DOCUMENT_ROOT={doc}\nRUN sed -ri 's!/var/www/html!{doc}!g' /etc/apache2/sites-available/000-default.conf /etc/apache2/apache2.conf\n" if root == "public" else "") + """EXPOSE 80\nCMD [\"apache2-foreground\"]\n"""
        return """FROM php:8.3-apache\nWORKDIR /var/www/html\nCOPY . .\nEXPOSE 80\nCMD [\"apache2-foreground\"]\n"""

    if rt == "Ruby":
        if not start:
            raise ValueError("No verified Ruby runtime command was resolved.")
        ruby = _tag(spec.runtime.get("version"), "3.3")
        files = set(spec.project.get("files", []))
        lock_copy = "COPY Gemfile.lock ./\n" if "Gemfile.lock" in files else ""
        return f"""FROM ruby:{ruby}-slim\nWORKDIR /app\nCOPY Gemfile ./\n{lock_copy}RUN bundle install\nCOPY . .\n{_copy_user_setup()}\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(start)}\n"""

    raise ValueError(f"No verified Docker generation strategy for runtime={rt}, strategy={strategy}")


def compose(spec):
    p = spec.network.get("port") or 8000
    extra = ""
    for svc in spec.services:
        if svc.get("name") == "PostgreSQL":
            extra += "\n  postgres:\n    image: postgres:17\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}\n    volumes:\n      - postgres-data:/var/lib/postgresql/data\n"
        if svc.get("name") == "Redis":
            extra += "\n  redis:\n    image: redis:7-alpine\n    volumes:\n      - redis-data:/data\n"
    vols = "\nvolumes:\n  postgres-data:\n  redis-data:\n" if extra else ""
    return f'''services:\n  app:\n    build: .\n    ports:\n      - "{p}:{p}"\n    restart: unless-stopped\n    security_opt:\n      - no-new-privileges:true\n    cap_drop:\n      - ALL\n    read_only: true\n    tmpfs:\n      - /tmp\n{extra}{vols}'''
