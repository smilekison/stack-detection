from pathlib import Path


def _node_install(spec):
    pm = spec.package_managers[0].get('name', 'npm') if spec.package_managers else 'npm'
    evidence = spec.package_managers[0].get('evidence_file', '') if spec.package_managers else ''
    if pm == 'pnpm':
        return pm, 'RUN corepack enable && corepack prepare pnpm@latest --activate', 'COPY package.json pnpm-lock.yaml ./', 'RUN pnpm install --frozen-lockfile'
    if pm == 'yarn':
        return pm, 'RUN corepack enable && corepack prepare yarn@stable --activate', 'COPY package.json yarn.lock ./', 'RUN yarn install --immutable'
    if pm == 'bun':
        return pm, 'RUN npm install -g bun', 'COPY package.json bun.lock ./', 'RUN bun install --frozen-lockfile'
    if evidence == 'package-lock.json':
        return 'npm', '', 'COPY package.json package-lock.json ./', 'RUN npm ci'
    return 'npm', '', 'COPY package.json ./', 'RUN npm install'


def dockerfile(spec):
    rt = spec.runtime.get('name', 'Unknown')
    fw = spec.frameworks[0]['name'] if spec.frameworks else ''
    port = spec.network.get('port') or 8000
    start = spec.processes[0].get('start_command', '') if spec.processes else ''
    strategy = spec.build.get('runtime_strategy')

    if rt == 'Node.js':
        pm, setup, manifest_copy, install = _node_install(spec)
        build = spec.build.get('container_command') or 'npm run build'

        if fw == 'Astro' and strategy == 'dev-server-fallback':
            command = f'{pm} run dev -- --host 0.0.0.0 --port {port}'
            return f'''FROM node:20-bookworm-slim AS build
WORKDIR /app
{setup}
{manifest_copy}
{install}
COPY . .
RUN {build}

FROM node:20-bookworm-slim AS runtime
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home appuser
COPY --from=build --chown=10001:10001 /app /app
USER 10001
ENV HOST=0.0.0.0
ENV PORT={port}
EXPOSE {port}
CMD ["sh", "-c", "{command}"]
'''

        if fw == 'Astro' and strategy == 'node-standalone':
            return f'''FROM node:20-bookworm-slim AS build
WORKDIR /app
{setup}
{manifest_copy}
{install}
COPY . .
RUN {build}

FROM node:20-bookworm-slim AS runtime
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home appuser
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT={port}
COPY --from=build --chown=10001:10001 /app/dist ./dist
COPY --from=build --chown=10001:10001 /app/node_modules ./node_modules
USER 10001
EXPOSE {port}
CMD ["node", "./dist/server/entry.mjs"]
'''

        if fw == 'Astro' and strategy == 'static':
            return f'''FROM node:20-bookworm-slim AS build
WORKDIR /app
{setup}
{manifest_copy}
{install}
COPY . .
RUN {build}

FROM node:20-bookworm-slim AS runtime
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home appuser
COPY --from=build --chown=10001:10001 /app /app
USER 10001
ENV HOST=0.0.0.0
ENV PORT={port}
EXPOSE {port}
CMD ["sh", "-c", "{pm} run preview -- --host 0.0.0.0 --port {port}"]
'''

        command = start or ('npm run start' if fw in {'Next.js', 'NestJS', 'Nuxt'} else 'npm start')
        return f'''FROM node:20-bookworm-slim AS build
WORKDIR /app
{setup}
{manifest_copy}
{install}
COPY . .
RUN {build}

FROM node:20-bookworm-slim AS runtime
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home appuser
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT={port}
COPY --from=build --chown=10001:10001 /app /app
USER 10001
EXPOSE {port}
CMD ["sh", "-c", {command!r}]
'''

    if rt == 'Python':
        start = start or 'python -m uvicorn main:app --host 0.0.0.0 --port 8000'
        install = 'pip install --no-cache-dir -r requirements.txt' if 'requirements.txt' in spec.project.get('files', []) else 'pip install --no-cache-dir .'
        return f'''FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 appuser
COPY . .
RUN {install}
USER 10001
EXPOSE {port}
CMD ["sh", "-c", {start!r}]
'''
    if rt == 'Go':
        return f'''FROM golang:1.24-bookworm AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
EXPOSE {port}
USER nonroot:nonroot
ENTRYPOINT ["/app"]
'''
    if rt == 'Rust':
        return f'''FROM rust:1.88-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock* ./
COPY . .
RUN cargo build --release
FROM debian:bookworm-slim
RUN useradd --system --uid 10001 appuser
COPY --from=build /src/target/release /opt/app
USER 10001
EXPOSE {port}
ENTRYPOINT ["/opt/app/app"]
'''
    if rt in {'JDK', 'JVM'}:
        return f'''FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY . .
RUN mvn -B -DskipTests package
FROM eclipse-temurin:21-jre
WORKDIR /app
RUN useradd --system --uid 10001 appuser
COPY --from=build /app/target/*.jar /app/app.jar
USER 10001
EXPOSE {port}
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
'''
    if rt == '.NET':
        return f'''FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /out
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
RUN useradd --system --uid 10001 appuser || true
COPY --from=build /out .
USER 10001
EXPOSE {port}
ENTRYPOINT ["dotnet", "app.dll"]
'''
    return f'''FROM alpine:3.21
WORKDIR /app
COPY . .
RUN adduser -D -u 10001 appuser
USER 10001
EXPOSE {port}
CMD ["sh", "-c", {start or 'sleep infinity'!r}]
'''


def compose(spec):
    p=spec.network.get('port') or 8000;extra=''
    for svc in spec.services:
        if svc.get('name')=='PostgreSQL':extra+='\n  postgres:\n    image: postgres:17\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}\n      POSTGRES_DB: app\n    volumes:\n      - postgres-data:/var/lib/postgresql/data\n'
        if svc.get('name')=='Redis':extra+='\n  redis:\n    image: redis:7-alpine\n    volumes:\n      - redis-data:/data\n'
    vols='\nvolumes:\n  postgres-data:\n  redis-data:\n' if extra else ''
    return f'''services:\n  app:\n    build: .\n    ports:\n      - "{p}:{p}"\n    restart: unless-stopped\n    security_opt:\n      - no-new-privileges:true\n    cap_drop:\n      - ALL\n    read_only: true\n    tmpfs:\n      - /tmp\n{extra}{vols}'''
