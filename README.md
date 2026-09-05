# Stack Detection & Deployment Intelligence

An **independent repository-intelligence project**. It is not the AutoDeploy product itself.

The engine's job is to understand a repository before it creates deployment artifacts. It does not blindly guess a Dockerfile from a framework name. It first builds an evidence-backed model of the repository, normalizes it into a Deployment IR, performs a deployment-focused analysis, and only then generates the specific artifact requested by the user.

## Analysis-first architecture

```text
Repository
   ↓
Acquire / isolate
   ↓
Full file inventory
   ↓
Language + framework detection
   ↓
Runtime + package manager + lockfile resolution
   ↓
Build / start / entrypoint analysis
   ↓
Application roles + services + ports + environment
   ↓
Infrastructure + CI/CD discovery
   ↓
Dependency graph + source/AST analysis
   ↓
Migration + security analysis
   ↓
Deep deployment analysis / blockers / decisions
   ↓
Deployment IR
   ↓
        ┌─────────────────────────────────────────┐
        │ ONLY NOW generate the requested artifact │
        └─────────────────────────────────────────┘
             ↓          ↓          ↓
         Dockerfile   Compose   K8s/Terraform
```

**Analysis never generates deployment artifacts.** The analysis response contains `generated_files: {}` and `generation.status: "not_requested"`.

Generation endpoints can reuse the immediately preceding analysis through its `analysis_id`. Before reuse, the server clones the repository again and compares its repository hash. If the repository changed or the analysis is unavailable/expired, the complete analysis runs again before generation.

## Local usage

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`.

Paste a public GitHub repository.

### Analyse

**Analyse** performs the complete repository intelligence pass and streams the stages to the dashboard. It does not create a Dockerfile, Compose file, Kubernetes manifest, or Terraform file.

### Generate Dockerfile

**Generate Dockerfile** first ensures that a complete analysis exists. It then sends the `analysis_id` to the generation endpoint. The server verifies that the repository hash is unchanged, applies the deep-analysis gate, generates only the Dockerfile, and statically validates it before returning it.

Optional runtime verification can be requested with `run_validation: true`. If runtime verification is enabled, the sandbox can build, start, smoke-test, diagnose and apply bounded deterministic repairs before the Dockerfile is released.

### Generate docker-compose

**Generate docker-compose** follows the same analysis gate and returns only `compose.yaml` plus the analysis/deployment metadata. It does not silently generate Dockerfile, Kubernetes or Terraform artifacts.

### Other artifacts

The backend also exposes the same gated generation mechanism for:

- `k8s`
- `terraform-aws`
- `terraform-gcp`
- `terraform-azure`

The generic endpoint is `POST /generate/{artifact}`.

## API

- `GET /` — dashboard
- `GET /health` — service health
- `POST /analyze` — complete analysis, no generated artifacts
- `POST /analyze-stream` — live NDJSON analysis stream, no generated artifacts
- `POST /generate/dockerfile` — analysis gate → Dockerfile → static validation → optional runtime verification
- `POST /generate/docker-compose` — analysis gate → Compose only
- `POST /generate/{artifact}` — analysis gate → one requested artifact only
- `POST /validate` — analysis followed by sandbox validation/repair
- `POST /analyze-and-validate` — analysis followed by sandbox validation/repair
- `POST /analyze-upload` — ZIP repository analysis
- `GET /docs` — OpenAPI/Swagger UI

All structured generation failures are returned as JSON objects containing a human-readable `message`, `phase`, requested artifact and the relevant analysis/validation details. The frontend explicitly normalizes these objects so they can never appear as JavaScript `[object Object]`.

## What the analysis checks

The analysis pass is intentionally broader than Docker generation. Depending on repository contents it examines:

- repository file inventory and layout
- primary and secondary languages
- framework candidates and confidence
- package managers and lockfiles
- runtime/version constraints
- production build scripts
- production/dev/start/serve commands
- executable entrypoints
- static vs dynamic/SSR application mode
- framework adapters and output modes
- ports and health endpoints
- application roles such as web, worker, scheduler and consumer
- database/cache/external service signals
- environment-variable and secret-file signals
- existing Docker/Kubernetes/Terraform/serverless configuration
- CI/CD workflows
- direct and resolved dependencies
- source imports and syntax structures
- migration frameworks and destructive migration patterns
- repository security findings
- monorepo/workspace conditions
- deterministic deployment blockers and strategy decisions

Framework names alone are never treated as enough evidence for generation.

## Docker generation contract

A Dockerfile is released only when the deep analysis can establish a deterministic deployment strategy. Unknown or ambiguous repositories are blocked rather than receiving a guessed Dockerfile.

The current strategy matrix covers deterministic paths for static web applications and several common Node.js, Python, Go, Rust, JVM, .NET, PHP and Ruby deployments. The correct product behavior for an unsupported or ambiguous project is **explicit blocking with evidence**, not pretending every arbitrary repository can be safely containerized.

## Design principles

1. **Repository before artifact.** Understand the repository first.
2. **No hidden generation.** Analysis does not call Docker/Compose/Kubernetes/Terraform generators.
3. **Only requested artifacts.** A request for Dockerfile produces Dockerfile; a request for Compose produces Compose; other generators are not run as side effects.
4. **Analysis reuse with integrity.** `analysis_id` is reusable only while the repository hash remains identical.
5. **Deployment IR is the source of truth.** Artifact generators consume the normalized deployment model.
6. **Deterministic first.** No OpenAI or Claude API key is required for the core pipeline.
7. **Fail closed.** Insufficient evidence produces a blocker rather than a speculative artifact.
8. **Structured errors.** API failures retain their diagnostic structure and are never coerced into `[object Object]` in the UI.
9. **Verification is separate.** Static validation is part of Dockerfile generation; expensive runtime verification is explicitly controllable.
10. **Bounded repair.** Runtime repair is allow-listed and deterministic rather than arbitrary source rewriting.

## Backend layout

```text
backend/
  core/            scanner, detection, deep analysis, IR, AST/source analysis,
                   dependencies, migrations and policy
  generators/      Docker, Compose, Kubernetes and cloud Terraform
  pricing/         deterministic cost model/provider boundary
  sandbox/         build/runtime isolation, diagnostics and bounded repair
  security/        repository security, SBOM and vulnerability planning
  tests/            regression tests
  main.py          analysis-first FastAPI API
frontend/
  index.html       dashboard shell
  app.js           analysis/generation UI
  app.css          dashboard styling
```

## Verification

Run before release changes are considered complete:

```bash
cd backend
python -m compileall -q .
python -m pytest -q
```
