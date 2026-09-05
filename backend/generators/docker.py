from pathlib import Path

def _node_install(spec):
    pm=spec.package_managers[0].get('name','npm') if spec.package_managers else 'npm';ev=spec.package_managers[0].get('evidence_file','') if spec.package_managers else ''
    if pm=='pnpm':return 'pnpm','RUN corepack enable && corepack prepare pnpm@latest --activate','COPY package.json pnpm-lock.yaml ./','RUN pnpm install --frozen-lockfile'
    if pm=='yarn':return 'yarn','RUN corepack enable && corepack prepare yarn@stable --activate','COPY package.json yarn.lock ./','RUN yarn install --immutable'
    if pm=='bun':return 'bun','RUN npm install -g bun','COPY package.json bun.lock ./','RUN bun install --frozen-lockfile'
    return 'npm','',('COPY package.json package-lock.json ./' if ev=='package-lock.json' else 'COPY package.json ./'),('RUN npm ci' if ev=='package-lock.json' else 'RUN npm install')

def dockerfile(spec):
    rt=spec.runtime.get('name','Unknown');fw=spec.frameworks[0]['name'] if spec.frameworks else '';port=spec.network.get('port') or 8000;strategy=spec.build.get('runtime_strategy');start=spec.processes[0].get('start_command','') if spec.processes else '';node_pm,setup,manifest,install=_node_install(spec)
    if rt=='Static Web':
        return '''FROM nginx:1.27-alpine\nCOPY . /usr/share/nginx/html\nEXPOSE 80\nCMD ["nginx", "-g", "daemon off;"]\n'''
    if rt=='Node.js':
        build=spec.build.get('container_command') or 'npm run build';
        if strategy=='dev-server-fallback':
            return f'''FROM node:{spec.runtime.get('version','20')}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{spec.runtime.get('version','20')}-bookworm-slim AS runtime\nWORKDIR /app\nRUN useradd --system --uid 10001 --no-create-home appuser\nCOPY --from=build --chown=10001:10001 /app /app\nUSER 10001\nENV HOST=0.0.0.0\nENV PORT={port}\nEXPOSE {port}\nCMD ["sh", "-c", "{start or f'{node_pm} run dev -- --host 0.0.0.0 --port {port}'}"]\n'''
        if strategy=='node-standalone':
            return f'''FROM node:{spec.runtime.get('version','20')}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{spec.runtime.get('version','20')}-bookworm-slim AS runtime\nWORKDIR /app\nRUN useradd --system --uid 10001 --no-create-home appuser\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port}\nCOPY --from=build --chown=10001:10001 /app/dist ./dist\nCOPY --from=build --chown=10001:10001 /app/node_modules ./node_modules\nUSER 10001\nEXPOSE {port}\nCMD ["node", "./dist/server/entry.mjs"]\n'''
        if strategy=='static-preview':
            return f'''FROM node:{spec.runtime.get('version','20')}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{spec.runtime.get('version','20')}-bookworm-slim\nWORKDIR /app\nCOPY --from=build /app /app\nENV HOST=0.0.0.0 PORT={port}\nEXPOSE {port}\nCMD ["sh", "-c", "{node_pm} run preview -- --host 0.0.0.0 --port {port}"]\n'''
        return f'''FROM node:{spec.runtime.get('version','20')}-bookworm-slim AS build\nWORKDIR /app\n{setup}\n{manifest}\n{install}\nCOPY . .\nRUN {build}\nFROM node:{spec.runtime.get('version','20')}-bookworm-slim\nWORKDIR /app\nENV NODE_ENV=production HOST=0.0.0.0 PORT={port}\nCOPY --from=build /app /app\nEXPOSE {port}\nCMD ["sh", "-c", {start!r}]\n'''
    if rt=='Python':
        base=spec.runtime.get('version','3.12');man=next((x for x in ('requirements.txt','pyproject.toml','Pipfile') if x in spec.project.get('files',[])),None);install={'requirements.txt':'pip install --no-cache-dir -r requirements.txt','pyproject.toml':'pip install --no-cache-dir .','Pipfile':'pip install --no-cache-dir pipenv && pipenv install --system --deploy'}.get(man,'pip install --no-cache-dir .')
        return f'''FROM python:{base}-slim\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /app\nCOPY . .\nRUN {install}\nRUN useradd --system --uid 10001 appuser\nUSER 10001\nEXPOSE {port}\nCMD ["sh", "-c", {start!r}]\n'''
    if rt=='Go':return f'''FROM golang:1.24-bookworm AS build\nWORKDIR /src\nCOPY go.mod go.sum* ./\nRUN go mod download\nCOPY . .\nRUN {spec.build.get('container_command','CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .')}\nFROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port}\nENTRYPOINT ["/app"]\n'''
    if rt=='Rust':return f'''FROM rust:1.88-bookworm AS build\nWORKDIR /src\nCOPY Cargo.toml Cargo.lock* ./\nCOPY . .\nRUN cargo build --release\nFROM debian:bookworm-slim\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build /src/target/release/{spec.build.get('binary','app')} /app\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["/app"]\n'''
    if rt in {'JDK','JVM'}:return '''FROM maven:3.9-eclipse-temurin-21 AS build\nWORKDIR /app\nCOPY . .\nRUN mvn -B -DskipTests package\nFROM eclipse-temurin:21-jre\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build /app/target/*.jar /app/app.jar\nUSER 10001\nEXPOSE 8080\nENTRYPOINT ["java", "-jar", "/app/app.jar"]\n'''
    if rt=='.NET':
        name=spec.build.get('assembly','app');return f'''FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet publish -c Release -o /out\nFROM mcr.microsoft.com/dotnet/aspnet:8.0\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build /out .\nUSER 10001\nENV ASPNETCORE_URLS=http://0.0.0.0:{port}\nEXPOSE {port}\nENTRYPOINT ["dotnet", "/app/{name}.dll"]\n'''
    if rt=='PHP':return '''FROM php:8.3-apache\nWORKDIR /var/www/html\nCOPY . /var/www/html/\nRUN chown -R www-data:www-data /var/www/html\nEXPOSE 80\nCMD ["apache2-foreground"]\n'''
    if rt=='Ruby':return f'''FROM ruby:3.3-slim\nWORKDIR /app\nCOPY Gemfile Gemfile.lock* ./\nRUN bundle install\nCOPY . .\nRUN useradd --system --uid 10001 appuser\nUSER 10001\nEXPOSE {port}\nCMD ["sh", "-c", {start or f'bundle exec rackup -o 0.0.0.0 -p {port}'!r}]\n'''
    raise ValueError(f'No verified Docker generation strategy for runtime={rt}, strategy={strategy}')

def compose(spec):
    p=spec.network.get('port') or 8000;extra=''
    for svc in spec.services:
        if svc.get('name')=='PostgreSQL':extra+='\n  postgres:\n    image: postgres:17\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}\n    volumes:\n      - postgres-data:/var/lib/postgresql/data\n'
        if svc.get('name')=='Redis':extra+='\n  redis:\n    image: redis:7-alpine\n    volumes:\n      - redis-data:/data\n'
    vols='\nvolumes:\n  postgres-data:\n  redis-data:\n' if extra else ''
    return f'''services:\n  app:\n    build: .\n    ports:\n      - "{p}:{p}"\n    restart: unless-stopped\n    security_opt:\n      - no-new-privileges:true\n    cap_drop:\n      - ALL\n    read_only: true\n    tmpfs:\n      - /tmp\n{extra}{vols}'''
