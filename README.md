# Stack Detection & Deployment Intelligence

Independent, AI-optional repository intelligence engine for AutoDeploy.

The goal is not to ask an LLM to guess a Dockerfile. The engine first constructs an evidence-backed model of a repository, normalizes it into a Deployment IR, generates artifacts from deterministic templates, validates them in a bounded Docker runtime when Docker is available, and records why each decision was made.

## v1.0.0 frontend

The backend serves the repository intelligence dashboard at `/`, so the normal local workflow needs only the FastAPI server.

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`.

Paste a **public GitHub repository** and use one of the three primary actions:

- **Analyse** — streams the analysis trace and then shows the complete result.
- **Generate Dockerfile** — analyzes the repository using the same engine and returns the generated Dockerfile plus the evidence-backed Deployment IR and static validation.
- **Generate docker-compose** — analyzes the repository and returns the generated Compose file plus the Deployment IR.

The Analyse view deliberately exposes the work as it happens: repository acquisition, inventory, language detection, runtime resolution, framework candidates, package managers, build/start entrypoints, services, environment signals, infrastructure, CI/CD, dependency graph, AST/source analysis, migration safety, security checks, Docker/Compose synthesis, static validation, pricing, and completion.

The live endpoint is `POST /analyze-stream` and emits newline-delimited JSON events followed by the final analysis result. This avoids a fake progress bar: the frontend renders the actual pipeline events produced by the backend.

## API

- `GET /` — v1 dashboard
- `GET /health` — health check
- `POST /analyze` — complete non-streaming analysis
- `POST /analyze-stream` — live NDJSON analysis stream
- `POST /generate/dockerfile` — Dockerfile generation from the analysis IR
- `POST /generate/docker-compose` — Compose generation from the analysis IR
- `POST /validate` — sandbox validation and bounded repair
- `POST /analyze-and-validate` — analysis followed by validation/repair
- `POST /analyze-upload` — ZIP repository analysis
- `GET /docs` — OpenAPI/Swagger UI

## Design principles

1. **Evidence before generation.** Repository facts are collected before artifacts are synthesized.
2. **Deployment IR is the source of truth.** Docker, Compose, Kubernetes and cloud artifacts are generated from the same normalized model.
3. **No blind AI dependency.** The core engine is deterministic and works without OpenAI or Claude API keys.
4. **Safety gates.** Destructive migrations, high/critical findings, low confidence and failed validation prevent automatic deployment eligibility.
5. **Bounded repair.** Runtime failures are diagnosed and only approved deterministic mutations are attempted; unknown failures stop instead of triggering arbitrary source rewrites.
6. **Isolation matters.** Docker runtime controls are included, but internet-scale hostile arbitrary repositories should execute in a dedicated worker with a VM/microVM boundary and no host Docker socket exposed to the API.
7. **Pricing honesty.** The bundled pricing layer is a planning engine with a provider adapter boundary; live regional provider catalogs must be refreshed rather than pretending static numbers are live quotes.

## Backend layout

```text
backend/
  core/            scanning, detection, IR, AST/source analysis, dependencies, migrations, policy
  generators/      Docker, Compose, Kubernetes, cloud Terraform
  pricing/         deterministic cost model + provider boundary
  sandbox/         build/runtime isolation policy, diagnostics, bounded repair
  security/        secret/security checks, SBOM/vulnerability plans
  tests/            regression tests
  main.py          FastAPI API + streaming pipeline
frontend/
  index.html       dashboard shell
  app.js           live analysis UI
  app.css          dashboard styling
```

## Verification

The backend regression suite is expected to remain green before release changes are considered complete:

```bash
cd backend
python -m compileall -q .
python -m pytest -q
```
