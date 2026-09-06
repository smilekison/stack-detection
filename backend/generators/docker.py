import json
import re
from pathlib import Path


_RANGE_MARKERS = re.compile(r"[<>^~]|\s")


def _tag(value, default):
    """Docker base-image tag from a version string - manifest fields like package.json
    engines or a runtime spec often hold a RANGE (">=18.0.0 <=22.x.x"), not a single
    version. The old two-part extraction truncated that into "18.0" - not a real published
    tag (Node's official images only ever publish MAJOR alone or a full MAJOR.MINOR.PATCH
    pin), so the build failed outright. A range only ever pins safely to its major version;
    a single standalone version (no range operators) can use its full precision.
    """
    s = str(value or "").strip()
    m = re.search(r"(?<!\d)(\d+)(?:\.(\d+)(?:\.(\d+))?)?", s)
    if not m: return default
    if _RANGE_MARKERS.search(s): return m.group(1)
    return m.group(1) + (("." + m.group(2) + (("." + m.group(3)) if m.group(3) else "")) if m.group(2) else "")


def _php_tag(value, default="8.3"):
    """PHP's official images, unlike Node's, never publish a bare-MAJOR tag (no `php:8`) -
    MAJOR.MINOR is the shortest valid one, so _tag()'s range fallback to major-only would
    itself produce an invalid tag here. Composer version constraints ("^8.3", ">=8.4.1",
    "8.2.*") all still contain a real MAJOR.MINOR pair; take that regardless of the operator.
    """
    m = re.search(r"(\d+)\.(\d+)", str(value or ""))
    return f"{m.group(1)}.{m.group(2)}" if m else default


def _pm_info(spec):
    pm = spec.package_managers[0] if spec.package_managers else {}
    return pm.get("name", "npm"), pm.get("version", ""), pm.get("evidence_file", "")


def _node_install(spec):
    pm, version, _ = _pm_info(spec); files = set(spec.project.get("files", []))
    if pm == "pnpm":
        lock = "pnpm-lock.yaml" if "pnpm-lock.yaml" in files else None; pin = version or "10.15.0"
        return "pnpm", f"RUN corepack enable && corepack prepare pnpm@{pin} --activate", "COPY package.json" + (" pnpm-lock.yaml" if lock else "") + " ./", "RUN pnpm install --frozen-lockfile" if lock else "RUN pnpm install"
    if pm == "yarn":
        lock = "yarn.lock" if "yarn.lock" in files else None; pin = version or "1.22.22"
        return "yarn", f"RUN corepack enable && corepack prepare yarn@{pin} --activate", "COPY package.json" + (" yarn.lock" if lock else "") + " ./", "RUN yarn install --immutable" if lock else "RUN yarn install"
    if pm == "bun":
        lock = "bun.lock" if "bun.lock" in files else ("bun.lockb" if "bun.lockb" in files else None); pin = version or "1.1.26"
        return "bun", f"RUN npm install -g bun@{pin}", "COPY package.json" + (f" {lock}" if lock else "") + " ./", "RUN bun install --frozen-lockfile" if lock else "RUN bun install"
    lock = "package-lock.json" if "package-lock.json" in files else None
    return "npm", "", "COPY package.json" + (" package-lock.json" if lock else "") + " ./", "RUN npm ci" if lock else "RUN npm install"


def _cmd(command): return json.dumps(["sh", "-c", command])
def _user(): return "RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser"


def dockerfile(spec):
    rt = spec.runtime.get("name", "Unknown"); port = spec.network.get("port") or 8000; strategy = spec.build.get("runtime_strategy")
    start = spec.processes[0].get("start_command", "") if spec.processes else ""; files = set(spec.project.get("files", []))
    if rt == "Static Web": return 'FROM nginxinc/nginx-unprivileged:1.27-alpine\nCOPY --chown=nginx:nginx . /usr/share/nginx/html\nEXPOSE 8080\nCMD ["nginx", "-g", "daemon off;"]\n'
    if rt == "Node.js":
        node = _tag(spec.runtime.get("version"), "20"); pm, setup, manifest, install = _node_install(spec); build = spec.build.get("container_command") or f"{pm} run build"
        if strategy == "dev-server-fallback":
            runtime_cmd = start or f"{pm} run dev -- --host 0.0.0.0 --port {port}"
            return f'''FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nCOPY --from=build --chown=10001:10001 /app /app\nENV HOST=0.0.0.0 PORT={port} HOME=/app\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(runtime_cmd)}\n'''
        if strategy == "node-standalone":
            return f'''FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port} HOME=/app\nCOPY --from=build --chown=10001:10001 /app/dist ./dist\nCOPY --from=build --chown=10001:10001 /app/node_modules ./node_modules\nUSER 10001\nEXPOSE {port}\nCMD ["node", "./dist/server/entry.mjs"]\n'''
        if strategy == "static-preview":
            return f'''FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\nCOPY --from=build /app /app\nENV HOST=0.0.0.0 PORT={port}\nEXPOSE {port}\nCMD {_cmd(f'{pm} run preview -- --host 0.0.0.0 --port {port}')}\n'''
        if strategy == "static-node":
            output = str(spec.build.get("output") or "dist").strip("/")
            return f'''FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime\nCOPY --from=build --chown=nginx:nginx /app/{output}/ /usr/share/nginx/html/\nEXPOSE 8080\nCMD ["nginx", "-g", "daemon off;"]\n'''
        if not start: raise ValueError("No verified Node runtime command was resolved.")
        return f'''FROM node:{node}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{node}-bookworm-slim AS runtime\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nCOPY --from=build --chown=10001:10001 /app /app\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port} HOME=/app\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(start)}\n'''
    if rt == "Python":
        py = _tag(spec.runtime.get("version"), "3.12"); manifest = spec.build.get("dependency_manifest")
        if not manifest:
            manifest = next((f for f in files if Path(f).name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile"}), None)
        if not manifest: raise ValueError("No verified Python dependency manifest was resolved.")
        manifest = str(manifest).replace("\\", "/")
        if manifest.endswith(("requirements.txt", "requirements-dev.txt")): install = f"pip install --no-cache-dir -r {manifest}"
        elif manifest.endswith("Pipfile"): install = f"pip install --no-cache-dir pipenv && pipenv install --system --deploy --chdir {Path(manifest).parent.as_posix() or '.'}"
        else: install = f"pip install --no-cache-dir ./{manifest}"
        server = "uvicorn" if strategy == "python-uvicorn" else ("gunicorn" if strategy == "python-gunicorn" else None)
        if server and server not in install: install += f" && pip install --no-cache-dir {server}"
        if not start: raise ValueError("No verified Python runtime command was resolved.")
        # The module reference in `start` is relative to the application root (e.g. `main`,
        # not `backend.main`), because that root's own internal imports are written relative
        # to itself, not the repo root. Run the server from there, same as a human would
        # `cd backend && uvicorn main:app` - COPY/install still happen at /app (repo root) so
        # cross-directory references from the app (e.g. serving a sibling frontend/) keep working.
        project_dir = str(spec.build.get("project_dir") or "").strip("/")
        run_cmd = f"cd {project_dir} && {start}" if project_dir and project_dir != "." else start
        # A binary the app shells out to at runtime (e.g. `git clone`) is a real system
        # dependency `pip install` never touches - the container boots fine and 500s the
        # first time the app actually tries to use it. Install it before COPY so the layer
        # caches independently of application code changes.
        system_packages = spec.build.get("system_packages") or []
        apt_install = f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(system_packages)} && rm -rf /var/lib/apt/lists/*\n" if system_packages else ""
        return f'''FROM python:{py}-slim AS runtime\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/app\nWORKDIR /app\n{apt_install}COPY . .\nRUN {install}\n{_user()}\nRUN chown 10001:10001 /app\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(run_cmd)}\n'''
    if rt == "Go":
        command = spec.build.get("container_command") or 'CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .'; lock = "COPY go.sum ./\n" if "go.sum" in files else ""
        return f'''FROM golang:{_tag(spec.runtime.get('version'), '1.24')}-bookworm AS build\nWORKDIR /src\nCOPY go.mod ./\n{lock}RUN go mod download\nCOPY . .\nRUN {command}\nFROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port}\nENTRYPOINT ["/app"]\n'''
    if rt == "Rust":
        binary = spec.build.get("binary", "app"); lock = "COPY Cargo.lock ./\n" if "Cargo.lock" in files else ""; command = spec.build.get("container_command") or "cargo build --release"
        return f'''FROM rust:{_tag(spec.runtime.get('version'), '1.88')}-bookworm AS build\nWORKDIR /src\nCOPY Cargo.toml ./\n{lock}COPY . .\nRUN {command}\nFROM debian:bookworm-slim\n{_user()}\nCOPY --from=build /src/target/release/{binary} /app\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["/app"]\n'''
    if rt in {"JDK", "JVM"}:
        if "gradlew" in files or "build.gradle" in files or "build.gradle.kts" in files: builder, outdir, cmd = "eclipse-temurin:21-jdk", "/app/build/libs", "./gradlew bootJar --no-daemon" if "gradlew" in files else "gradle bootJar --no-daemon"
        elif "pom.xml" in files: builder, outdir, cmd = "maven:3.9-eclipse-temurin-21", "/app/target", "./mvnw -B -DskipTests package" if "mvnw" in files else "mvn -B -DskipTests package"
        else: raise ValueError("No verified Maven/Gradle build manifest was resolved.")
        return f'''FROM {builder} AS build\nWORKDIR /app\nCOPY . .\nRUN {cmd}\nRUN mkdir -p /out && cp "$(find {outdir} -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' | head -n 1)" /out/app.jar\nFROM eclipse-temurin:21-jre\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nENV HOME=/app\nCOPY --from=build --chown=10001:10001 /out/app.jar /app/app.jar\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["java", "-jar", "/app/app.jar"]\n'''
    if rt == ".NET":
        project = spec.build.get("project_file");
        if not project: raise ValueError("No verified .csproj was resolved.")
        name = spec.build.get("assembly") or Path(project).stem; tfm = str(spec.runtime.get("version", "net8.0")); m = re.search(r"net(\d+)(?:\.(\d+))?", tfm, re.I); net = f"{m.group(1)}.{m.group(2) or '0'}" if m else "8.0"
        return f'''FROM mcr.microsoft.com/dotnet/sdk:{net} AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet restore {project}\nRUN dotnet publish {project} -c Release --no-restore -o /out\nFROM mcr.microsoft.com/dotnet/aspnet:{net}\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nCOPY --from=build --chown=10001:10001 /out .\nUSER 10001\nENV ASPNETCORE_URLS=http://0.0.0.0:{port} HOME=/app\nEXPOSE {port}\nENTRYPOINT ["dotnet", "/app/{name}.dll"]\n'''
    if rt == "PHP":
        root = spec.build.get("document_root", "."); php = _php_tag(spec.runtime.get("version"))
        if "composer.json" in files:
            doc = "/var/www/html/public" if root == "public" else "/var/www/html"; lock = "COPY composer.lock ./\n" if "composer.lock" in files else ""; rewrite = f"ENV APACHE_DOCUMENT_ROOT={doc}\nRUN sed -ri 's!/var/www/html!{doc}!g' /etc/apache2/sites-available/000-default.conf /etc/apache2/apache2.conf\n" if root == "public" else ""
            # --no-scripts: Laravel's `artisan package:discover` (a post-autoload-dump hook)
            # needs the full application source, which isn't copied into this stage, only the
            # manifest - composer install would fail outright otherwise. The optimized
            # autoloader itself (--optimize-autoloader) is a core composer feature, not a
            # script, and still gets built correctly. But skipping the hook isn't just a lost
            # cache warm-up as it first looks: without the resulting package manifest cache,
            # Laravel fails to register core service providers at all (`Target class [view]
            # does not exist`) - it must be re-run once the real app is present, below.
            laravel = "artisan" in files
            writable = "RUN chown -R www-data:www-data storage bootstrap/cache\n" if laravel else ""
            discover = "RUN php artisan package:discover --ansi\n" if laravel else ""
            # COPY . . must run BEFORE the vendor copy, not after: a local dev environment
            # almost always already has its own vendor/ sitting in the build context (from
            # running composer locally, dev deps included), and COPY . . would otherwise
            # silently clobber the correctly `--no-dev`-installed vendor/ from the deps stage
            # with that one - the exact failure mode this order avoids.
            # A build-only Node companion (Vite, most commonly) that lost the polyglot
            # tie-break to this PHP backend still needs its own build to run: Laravel's
            # Blade views reference the compiled manifest via @vite(), and without it the
            # page 500s even though the PHP side is entirely correct. Folded in as its own
            # stage rather than assumed away, using the same package-manager evidence
            # already resolved for the companion (npm/pnpm/yarn/bun, with or without a
            # lockfile) instead of hardcoding npm.
            frontend = spec.build.get("frontend_build")
            assets_stage = assets_copy = ""
            if frontend:
                node_pm = frontend.get("package_manager") or "npm"; node_lock = frontend.get("lockfile")
                node_install = {"pnpm":"pnpm install --frozen-lockfile","yarn":"yarn install --immutable","bun":"bun install --frozen-lockfile"}.get(node_pm, "npm ci") if node_lock else {"pnpm":"pnpm install","yarn":"yarn install","bun":"bun install"}.get(node_pm, "npm install")
                assets_stage = f'''FROM node:20-bookworm-slim AS assets\nWORKDIR /app\nCOPY package.json{(" " + node_lock) if node_lock else ""} ./\nRUN {node_install}\nCOPY . .\nRUN {node_pm} run build\n'''
                assets_copy = "COPY --from=assets --chown=www-data:www-data /app/public/build ./public/build\n"
            return f'''{assets_stage}FROM composer:2 AS deps\nWORKDIR /app\nCOPY composer.json ./\n{lock}RUN composer install --no-dev --prefer-dist --no-interaction --no-progress --optimize-autoloader --no-scripts\nFROM php:{php}-apache\nWORKDIR /var/www/html\nRUN a2enmod rewrite\nCOPY . .\nCOPY --from=deps /app/vendor ./vendor\n{assets_copy}{writable}{discover}{rewrite}EXPOSE 80\nCMD ["apache2-foreground"]\n'''
        return f'FROM php:{php}-apache\nWORKDIR /var/www/html\nCOPY . .\nEXPOSE 80\nCMD ["apache2-foreground"]\n'
    if rt == "Ruby":
        if not start: raise ValueError("No verified Ruby runtime command was resolved.")
        ruby = _tag(spec.runtime.get("version"), "3.3"); lock = "COPY Gemfile.lock ./\n" if "Gemfile.lock" in files else ""
        # Rack 3 split the `rackup` executable into its own gem. A Gemfile pinning only
        # `rack` no longer guarantees `bundle exec rackup` resolves - a known package
        # installation issue (PROGRAM.md's bounded-repair class). The fix must run after
        # `COPY . .`: that copy brings back the host's original Gemfile, overwriting any
        # patch applied earlier, so patching before it would silently be undone.
        ensure_rackup = "RUN grep -q rackup Gemfile || echo \"gem 'rackup'\" >> Gemfile && bundle install\n" if strategy == "ruby-rack" else ""
        # Multi-stage: most real Ruby apps pull in at least one native-extension gem
        # transitively (Rails -> rails-html-sanitizer -> nokogiri; puma -> nio4r; pg,
        # mysql2, sqlite3...), and ruby:slim has no build toolchain at all - bundle
        # install fails on any of them. Compiling in a build stage with build-essential,
        # then copying only the installed gems into a slim runtime stage, fixes that
        # without bloating the final image the way installing build tools everywhere would.
        return f'''FROM ruby:{ruby}-slim AS build\nRUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*\nWORKDIR /app\nCOPY Gemfile ./\n{lock}RUN bundle install\nCOPY . .\n{ensure_rackup}FROM ruby:{ruby}-slim AS runtime\nWORKDIR /app\n{_user()}\nRUN chown 10001:10001 /app\nENV HOME=/app\nCOPY --from=build --chown=10001:10001 /usr/local/bundle /usr/local/bundle\nCOPY --from=build --chown=10001:10001 /app /app\nUSER 10001\nEXPOSE {port}\nCMD {_cmd(start)}\n'''
    raise ValueError(f"No verified Docker generation strategy for runtime={rt}, strategy={strategy}")


# Self-hostable data services with a well-known official image and standard credential
# env vars - what compose() can wire up deterministically. The rest of _services()'s
# catalog (S3, Supabase, Firebase, Stripe, DynamoDB) names managed third-party APIs with
# no meaningful "run it in a container" story, so they're deliberately left out here
# rather than faked into a container that wouldn't be the real thing anyway.
_COMPOSE_SERVICES = {
    "PostgreSQL": ("postgres", "postgres:17", "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}", "/var/lib/postgresql/data"),
    "MySQL": ("mysql", "mysql:9", "      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?required}\n      MYSQL_DATABASE: ${MYSQL_DATABASE:-app}", "/var/lib/mysql"),
    "MariaDB": ("mariadb", "mariadb:11", "      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD:?required}\n      MARIADB_DATABASE: ${MARIADB_DATABASE:-app}", "/var/lib/mysql"),
    "MongoDB": ("mongodb", "mongo:7", "      MONGO_INITDB_ROOT_USERNAME: ${MONGO_INITDB_ROOT_USERNAME:?required}\n      MONGO_INITDB_ROOT_PASSWORD: ${MONGO_INITDB_ROOT_PASSWORD:?required}", "/data/db"),
    "Redis": ("redis", "redis:7-alpine", None, "/data"),
}


def compose(spec):
    p = spec.network.get("port") or 8000; names = {x.get("name") for x in spec.services}; extra = []; vols = []; depends = []
    for svc, (key, image, env, path) in _COMPOSE_SERVICES.items():
        if svc not in names: continue
        depends.append(key); vol = f"{key}-data"
        env_block = f"\n    environment:\n{env}" if env else ""
        extra.append(f"  {key}:\n    image: {image}{env_block}\n    volumes:\n      - {vol}:{path}"); vols.append(f"  {vol}:")
    services = "\n".join(extra); volume_block = "\nvolumes:\n" + "\n".join(vols) if vols else ""
    depends_block = "\n    depends_on:\n" + "\n".join(f"      - {d}" for d in depends) if depends else ""
    # A .env.example/.env.sample/.env.template in the repo (see engine.py's envs()) is the
    # project's own declaration of what it needs at runtime - wiring it in as `env_file`
    # here just means the same "cp .env.example .env" step every real-world compose-based
    # project already expects before its first run, not a new requirement this tool invents.
    example = spec.environment.get("example_file") if isinstance(spec.environment, dict) else None
    env_file_block = "\n    env_file:\n      - .env  # copy from " + example if example else ""
    return f'''services:\n  app:\n    build: .\n    ports:\n      - "{p}:{p}"{env_file_block}{depends_block}\n    restart: unless-stopped\n    security_opt:\n      - no-new-privileges:true\n    cap_drop:\n      - ALL\n    read_only: true\n    tmpfs:\n      - /tmp\n{services}{volume_block}\n'''
