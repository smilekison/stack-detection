# AutoDeploy Stack Detection Engine

An independent, **AI-free repository intelligence prototype** for turning a GitHub repository into an evidence-backed deployment specification and starter Docker artifacts.

## Core idea

```text
GitHub repository
        ↓
Repository Scanner
        ↓
Deterministic Detection Engine
        ↓
Evidence Ledger + Confidence
        ↓
Deployment IR
        ↓
Dockerfile / Compose / .dockerignore
```

The engine does **not** require OpenAI, Claude, Gemini, or any external AI API key.

## What it detects

### Programming languages
- JavaScript
- TypeScript
- Python
- Go
- Rust
- Java / JVM
- C# / .NET
- PHP
- Ruby
- Swift
- Dart
- Elixir

### Runtimes and versions
- Node.js via `.nvmrc`, `.node-version`, `package.json.engines`
- Python via `.python-version`, `runtime.txt`, `pyproject.toml`
- Go via `go.mod`
- Java via Maven configuration
- .NET via `TargetFramework`

### Package managers / build systems
- npm
- pnpm
- Yarn
- Bun
- pip
- Poetry
- uv
- Pipenv
- Go modules
- Cargo
- Maven
- Gradle
- Composer
- Bundler

### Frameworks
- Next.js
- Nuxt
- NestJS
- Express
- Fastify
- Koa
- Hono
- Remix
- SvelteKit
- Angular
- React
- Vue
- Vite
- Astro
- Django
- FastAPI
- Flask
- Litestar
- Sanic
- Tornado
- Gin
- Echo
- Fiber
- Chi
- Spring Boot
- Quarkus
- Micronaut

### Data stores / infrastructure integrations
- PostgreSQL
- MySQL
- MariaDB
- MongoDB
- Redis
- RabbitMQ
- Kafka
- Elasticsearch / OpenSearch
- S3 / object storage
- Supabase
- Firebase
- Stripe

### Architecture signals
- Monorepo/workspaces
- Web application
- Background workers
- Schedulers / cron
- Message consumers
- Health/readiness endpoints
- Environment variables
- Existing Docker / Compose configuration
- Terraform / Helm / Kubernetes / CI/CD files

### Deployment evidence
The detector records the repository evidence behind each important decision, including:

```json
{
  "points": 40,
  "file": ".nvmrc",
  "reason": "Node runtime version explicitly declared",
  "category": "runtime"
}
```

This makes the system explainable instead of returning a black-box answer.

## Deployment IR

The engine normalizes detection into an intermediate representation containing:

- project / monorepo structure
- application roles
- language and runtime
- runtime version
- package manager
- framework
- build command
- build output
- start command
- network port
- health endpoint
- external services
- environment variables
- CI/CD signals
- existing deployment files
- generated Docker artifacts

The IR is deliberately independent of Docker so that future generators can target:

```text
Deployment IR
   ├── Dockerfile
   ├── Compose
   ├── Terraform
   ├── Kubernetes
   ├── ECS
   └── Cloud provider resources
```

## Docker generation

Supported starter production templates currently include:

- Node.js / TypeScript
- Python
- Go
- Rust
- Java/Maven
- Java/Gradle
- .NET

The generator uses multi-stage images where appropriate, production dependency installation, non-root runtime where practical, exposed ports, and explicit entrypoints.

For unknown or ambiguous stacks the system intentionally refuses to invent a production Dockerfile and returns a warning. This is a design principle: **uncertainty should be surfaced, not hidden.**

## Run locally

Requirements:

- Python 3.11+
- Node.js 20+
- Git
- Docker optional

### Backend

```bash
cd backend
python -m venv .venv
```

Windows:

```powershell
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

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`.

Paste a public GitHub repository URL and click **Analyze repository**.

## API

`POST /analyze`

```json
{
  "repo_url": "https://github.com/owner/repository"
}
```

The response contains:

```text
summary
evidence
files
generated_files
deployment_ir
```

## Architecture roadmap

This repository is intentionally an independent testbed before integration into AutoDeploy.

Next engineering layers:

1. Detector registry with independently versioned fingerprints.
2. AST parsing for JavaScript/TypeScript, Python, Go, Java and C#.
3. Better conflict resolution across manifests, CI and existing Dockerfiles.
4. Private GitHub OAuth / installation support.
5. ZIP upload support.
6. Isolated Docker build sandbox.
7. Container startup and health validation.
8. Build-error classification and automatic repair.
9. SBOM and vulnerability scanning.
10. Terraform / Kubernetes / ECS generators.
11. Cost-estimation model.
12. Optional local-LLM fallback for low-confidence ambiguity only.

## Safety principles

- Never place secrets in generated Dockerfiles.
- Do not claim a technology is present without repository evidence.
- Do not silently override conflicting runtime declarations.
- Do not execute destructive database migrations automatically.
- Do not generate unsafe production infrastructure when confidence is too low.

## License

Use this prototype as the foundation for your own development and testing.
