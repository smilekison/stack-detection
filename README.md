# Stack Detection Engine

An independent, AI-free repository intelligence prototype for turning a software repository into an evidence-backed deployment specification and generated container/infrastructure artifacts.

> Goal: prove the repository → stack detection → deployment IR → Docker → validation architecture before integrating it into AutoDeploy.

## Architecture

```text
Repository URL / ZIP
        |
        v
Repository Scanner
        |
        +--> manifests / lockfiles
        +--> source files
        +--> CI/CD
        +--> Docker / Kubernetes / Terraform
        +--> runtime/version files
        |
        v
Detector Registry
        |
        +--> languages
        +--> runtimes
        +--> package managers
        +--> frameworks
        +--> databases/caches/queues
        +--> application roles
        +--> entrypoints/build commands
        +--> ports/health endpoints
        +--> environment variables
        +--> monorepo topology
        |
        v
Evidence Engine
        |
        +--> weighted signals
        +--> confidence
        +--> conflicts
        |
        v
Deployment IR (versioned JSON)
        |
        +--> Dockerfile
        +--> Compose
        +--> Kubernetes
        +--> Terraform starting point
        |
        v
Validation
        |
        +--> static checks
        +--> docker build (when Docker is available)
        +--> container startup diagnostics
        +--> health/smoke validation hooks
        |
        v
Security review + deterministic repair analysis
```

No OpenAI, Claude, Gemini, or other hosted AI API is required.

## What is detected

### Programming languages

- JavaScript
- TypeScript
- Python
- Go
- Rust
- Java/JVM
- C#/.NET
- Ruby
- PHP

Detection uses multiple signals rather than one filename. Examples include manifests, lockfiles and source extensions.

### Runtime and version

- Node.js via `.nvmrc`, `.node-version`, `package.json` engines
- Python via `.python-version`, `runtime.txt`, `pyproject.toml`
- Go via `go.mod`
- Ruby via `.ruby-version`
- Rust/Java/.NET runtime families

The engine records whether a version was explicitly declared or had to be defaulted by the generator.

### Package managers / dependency systems

- npm
- pnpm
- Yarn
- Bun
- pip
- Pipenv
- Poetry
- uv
- Go modules
- Cargo
- Bundler
- Composer

Lockfiles receive strong evidence weight. A `packageManager` declaration in `package.json` can override weaker lockfile evidence.

### Frameworks and application tooling

Node ecosystem:

- Express
- NestJS
- Fastify
- Koa
- Hono
- Next.js
- Remix
- Nuxt
- React
- Vue
- Angular
- Svelte
- Astro
- Vite
- Electron
- Socket.IO

Python:

- FastAPI
- Django
- Flask
- Starlette
- Tornado
- Streamlit
- Celery

Go:

- Gin
- Echo
- Fiber
- Chi

Rust:

- Actix Web
- Axum
- Rocket
- Warp

JVM:

- Spring Boot
- Quarkus
- Micronaut

.NET:

- ASP.NET Core

The detector keeps alternatives instead of silently throwing away competing framework evidence.

### Data stores, caches, queues and integrations

Signals cover:

- PostgreSQL
- MySQL
- MariaDB
- MongoDB
- Redis
- RabbitMQ
- Kafka
- SQLite
- Elasticsearch
- DynamoDB
- S3/object storage

These are repository signals, not claims that a production database should automatically be provisioned. The Deployment IR separates detection from provisioning decisions.

### Architecture / service roles

- API
- frontend
- worker
- scheduler
- consumer
- process manager signals such as PM2/Gunicorn
- server signals such as Uvicorn
- monorepo

### CI/CD and infrastructure

- GitHub Actions
- GitLab CI
- Jenkins
- Azure Pipelines
- Bitbucket Pipelines
- Docker
- Docker Compose
- Terraform
- Kubernetes/Helm
- Serverless configuration

### Environment variables

The scanner extracts referenced variable names from common Node/Python patterns and `${VAR}` references. It never copies actual secret values into generated Dockerfiles.

### Ports and health

The engine looks for explicit port configuration and then uses framework defaults only as lower-confidence evidence.

Health route signals include:

- `/health`
- `/healthz`
- `/ready`
- `/readiness`
- `/live`
- `/liveness`

## Evidence model

Every important detection can carry:

```json
{
  "points": 60,
  "file": "go.mod",
  "reason": "Go module manifest",
  "category": "language"
}
```

The result contains:

- detected value
- alternatives
- weighted evidence
- confidence score
- conflicts

This is intentionally designed so the engine can answer why it made a deployment decision.

## Deployment IR

The normalized representation is the boundary between analysis and artifact generation.

Example shape:

```json
{
  "schema_version": "1.0",
  "runtime": {
    "language": "TypeScript",
    "runtime": "Node.js",
    "version": "20",
    "package_manager": "pnpm"
  },
  "framework": {
    "name": "Express"
  },
  "build": {
    "command": "pnpm build",
    "output": "dist/"
  },
  "start": {
    "command": "node dist/server.js"
  },
  "network": {
    "port": 3000
  },
  "services": ["PostgreSQL", "Redis"],
  "environment": {
    "variables": ["DATABASE_URL", "REDIS_URL"]
  }
}
```

Keeping this IR separate means Docker, Compose, Kubernetes and cloud-specific generators can evolve independently.

## Generated artifacts

The prototype generates:

- `Dockerfile`
- `.dockerignore`
- `compose.yaml`
- `kubernetes/deployment.yaml`
- `terraform/main.tf`

Docker templates include multi-stage builds for common compiled Node workloads, non-root runtime users where practical, explicit ports and health-check support.

Generated infrastructure is intentionally conservative. It is a starting point, not an automatic production approval.

## Validation

When Docker is installed in the environment running the backend, the engine can:

1. Write the generated Dockerfile into the temporary repository.
2. Run `docker build`.
3. Capture stdout/stderr and exit codes.
4. Start the image briefly for runtime diagnostics.
5. Return validation information to the UI.

If Docker is unavailable, analysis still works and explicitly reports that build validation was skipped.

### Safety boundary

The current validator is intended for repositories you have permission to analyze. A production AutoDeploy implementation should execute builds in a hardened, isolated worker/sandbox with:

- CPU/memory/time limits
- no host Docker socket exposure
- restricted network egress
- ephemeral filesystem
- dropped privileges/capabilities
- image and dependency scanning
- secret redaction

Do not expose the development Compose Docker socket setup to untrusted users.

## Deterministic repair strategy

The prototype records unresolved areas and produces conservative fallbacks. The intended production loop is:

```text
Generate
   -> build
   -> inspect failure
   -> classify failure
   -> collect additional repository evidence
   -> modify Deployment IR
   -> regenerate
   -> rebuild
```

The repair layer should only make deterministic changes that are supported by repository evidence. An optional local or hosted LLM can later be plugged into ambiguous diagnosis, but it is not a dependency of the core engine.

## Run locally

### Backend

Requirements:

- Python 3.11+
- Git
- Docker optional

```bash
cd backend
python -m venv .venv
```

Windows:

```bash
.venv\\Scripts\\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

Requirements:

- Node.js 20+

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

Paste a public GitHub URL and choose Analyze repository.

### ZIP input

The backend also exposes:

```text
POST /analyze-zip
```

with a multipart ZIP upload, which makes the prototype usable without GitHub access.

## API

### `GET /health`

Returns engine status and confirms that AI is not required.

### `POST /analyze`

```json
{
  "repo_url": "https://github.com/owner/repo",
  "validate_docker": true,
  "generate_infrastructure": true
}
```

### `POST /analyze-zip`

Multipart upload field: `file=<repository.zip>`.

Optional query parameters: `validate_docker=true` and `generate_infrastructure=true`.

## Production roadmap

This independent prototype establishes the architecture. The next hardening stages are:

1. Split detectors into a registry/plugin system.
2. Add language-aware AST parsers instead of relying primarily on regex/source heuristics.
3. Add complete lockfile and dependency graph analysis.
4. Trace entrypoints through scripts, imports and framework conventions.
5. Detect multiple deployable services in monorepos.
6. Add migration detection and destructive-operation classification.
7. Add a real isolated build sandbox.
8. Add container health/smoke testing with controlled networking.
9. Add deterministic failure classifiers and evidence-backed repair iterations.
10. Add Trivy/Grype or equivalent vulnerability scanning in a controlled worker.
11. Add SBOM generation.
12. Add secret detection and redaction.
13. Add provider-specific Terraform modules for AWS/GCP/Azure.
14. Add ECS/Fargate, Kubernetes and serverless deployment targets.
15. Add cloud cost estimation from the Deployment IR.
16. Add policy gates for security, cost and production approval.
17. Add optional local-model inference for genuinely ambiguous repositories.
18. Add a signed, versioned detector/template registry.
19. Add regression fixtures covering hundreds of real-world repositories.
20. Integrate the engine into AutoDeploy only after the independent test suite is stable.

## Design principle

The core product is not an AI that writes Dockerfiles.

It is a repository intelligence engine that converts evidence into a normalized deployment specification, then deterministically generates and validates infrastructure from that specification.

AI can be an optional accelerator. It should never be required to understand a repository that already contains enough machine-readable evidence to understand itself.
