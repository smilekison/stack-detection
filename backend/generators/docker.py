from pathlib import Path

def dockerfile(spec):
    rt=spec.runtime.get('name','Unknown');fw=spec.frameworks[0]['name'] if spec.frameworks else '';port=spec.network.get('port') or 8000;start=spec.processes[0].get('start_command','') if spec.processes else ''
    if rt=='Node.js':
        pm=spec.package_managers[0].get('name','npm') if spec.package_managers else 'npm';install={'pnpm':'pnpm install --frozen-lockfile','yarn':'yarn install --immutable','bun':'bun install --frozen-lockfile','npm':'npm ci'}.get(pm,'npm ci');setup={'pnpm':'RUN corepack enable && corepack prepare pnpm@latest --activate','yarn':'RUN corepack enable && corepack prepare yarn@stable --activate','bun':'RUN npm install -g bun','npm':''}.get(pm,'');build=spec.build.get('command') or 'npm run build';start=start or ('npm run start' if fw in {'Next.js','NestJS','Nuxt'} else 'npm start')
        return f'''FROM node:22-bookworm-slim AS build\nWORKDIR /app\n{setup}\nCOPY package*.json ./\nCOPY pnpm-lock.yaml* yarn.lock* bun.lock* ./\nRUN {install}\nCOPY . .\nRUN {build}\nFROM node:22-bookworm-slim AS runtime\nENV NODE_ENV=production\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build --chown=appuser:appuser /app /app\nUSER 10001\nEXPOSE {port}\nCMD ["sh","-c",{start!r}]\n'''
    if rt=='Python':
        start=start or 'python -m uvicorn main:app --host 0.0.0.0 --port 8000';install='pip install --no-cache-dir -r requirements.txt' if 'requirements.txt' in spec.project.get('files',[]) else 'pip install --no-cache-dir .'
        return f'''FROM python:3.12-slim\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser\nCOPY . .\nRUN {install}\nUSER 10001\nEXPOSE {port}\nCMD ["sh","-c",{start!r}]\n'''
    if rt=='Go':return f'''FROM golang:1.24-bookworm AS build\nWORKDIR /src\nCOPY go.mod go.sum* ./\nRUN go mod download\nCOPY . .\nRUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .\nFROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port}\nUSER nonroot:nonroot\nENTRYPOINT ["/app"]\n'''
    if rt=='Rust':return f'''FROM rust:1.88-bookworm AS build\nWORKDIR /src\nCOPY Cargo.toml Cargo.lock* ./\nCOPY . .\nRUN cargo build --release\nFROM debian:bookworm-slim\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build /src/target/release /opt/app\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["/opt/app/app"]\n'''
    if rt in {'JDK','JVM'}:return f'''FROM maven:3.9-eclipse-temurin-21 AS build\nWORKDIR /app\nCOPY . .\nRUN mvn -B -DskipTests package\nFROM eclipse-temurin:21-jre\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser\nCOPY --from=build /app/target/*.jar /app/app.jar\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["java","-jar","/app/app.jar"]\n'''
    if rt=='.NET':return f'''FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet publish -c Release -o /out\nFROM mcr.microsoft.com/dotnet/aspnet:8.0\nWORKDIR /app\nRUN useradd --system --uid 10001 appuser || true\nCOPY --from=build /out .\nUSER 10001\nEXPOSE {port}\nENTRYPOINT ["dotnet","app.dll"]\n'''
    return f'''FROM alpine:3.21\nWORKDIR /app\nCOPY . .\nRUN adduser -D -u 10001 appuser\nUSER 10001\nEXPOSE {port}\nCMD ["sh","-c",{(start or 'sleep infinity')!r}]\n'''

def compose(spec):
    p=spec.network.get('port') or 8000;extra=''
    for svc in spec.services:
        if svc.get('name')=='PostgreSQL':extra+='\n  postgres:\n    image: postgres:17\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}\n      POSTGRES_DB: app\n    volumes:\n      - postgres-data:/var/lib/postgresql/data\n'
        if svc.get('name')=='Redis':extra+='\n  redis:\n    image: redis:7-alpine\n    volumes:\n      - redis-data:/data\n'
    vols='\nvolumes:\n  postgres-data:\n  redis-data:\n' if extra else ''
    return f'''services:\n  app:\n    build: .\n    ports:\n      - "{p}:{p}"\n    restart: unless-stopped\n    security_opt:\n      - no-new-privileges:true\n    cap_drop:\n      - ALL\n    read_only: true\n    tmpfs:\n      - /tmp\n{extra}{vols}'''
