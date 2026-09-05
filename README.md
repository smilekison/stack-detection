# Stack Detection & Deployment Intelligence

Independent, AI-optional repository intelligence engine for AutoDeploy.

The goal is not to ask an LLM to guess a Dockerfile. The engine first constructs an evidence-backed model of a repository, normalizes it into a Deployment IR, performs a second deployment-focused analysis of manifests, lockfiles, scripts, framework configuration, adapters, output modes, ports and repository layout, then generates artifacts from deterministic templates. Dockerfile generation is gated by that deep analysis and, for the explicit Dockerfile generation endpoint, by a real Docker build/runtime smoke test with bounded deterministic repair when a Docker worker is available.

## v1.0.0 frontend

The backend serves the repository intelligence dashboard at `/`, so the normal local workflow needs only the FastAPI server.

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

```

Open `http://localhost:8000`.

Paste a **public GitHub repository** and use one of the three primary actions:

- **Analyse** — streams the full analysis trace and then shows the complete result.
- **Generate Dockerfile** — performs the same identification plus the deep deployment pass, statically validates the candidate, builds and runs it in the sandbox, applies only bounded deterministic repairs when needed, and returns the Dockerfile only after runtime verification succeeds. If Docker is unavailable or verification fails, the artifact is withheld instead of being presented as verified.
- **Generate docker-compose** — analyzes the repository and returns the generated Compose file plus the Deployment IR.

The analysis pipeline deliberately exposes the work in order: repository acquisition, inventory, deterministic stack identification, runtime resolution, framework candidates, package managers, **deep deployment analysis**, build/start entrypoints, services, environment signals, infrastructure, CI/CD, dependency graph, AST/source analysis, migration safety, security checks, artifact synthesis, static validation, pricing, and completion.

The live endpoint is `POST /analyze-stream` and emits newline-delimited JSON events followed by the final analysis result. The frontend renders actual backend events rather than a fake timed progress bar.

## API

- `GET /` — v1 dashboard
- `GET /health` — health check
- `POST /analyze` — complete non-streaming analysis
- `POST /analyze-stream` — live NDJSON analysis stream
- `POST /generate/dockerfile` — deep analysis + static validation + sandbox build/runtime verification + bounded repair, then Dockerfile release
- `POST /generate/docker-compose` — Compose generation from the analysis IR
- `POST /validate` — sandbox validation and bounded repair
- `POST /analyze-and-validate` — analysis followed by validation/repair
- `POST /analyze-upload` — ZIP repository analysis
- `GET /docs` — OpenAPI/Swagger UI

## Docker generation contract

Dockerfile generation is intentionally stricter than ordinary analysis. The generator must resolve the repository's actual package manager and lockfile, build script, framework configuration, server adapter/output mode, runtime version, start strategy, application port, monorepo target and relevant environment constraints before producing the candidate. Framework names alone are never sufficient.

The generated Dockerfile is then checked statically. The explicit generation endpoint writes the candidate into the cloned repository and uses the sandbox to perform a real Docker build, start an isolated runtime, map the detected port and issue HTTP smoke requests. Failed attempts are diagnosed and only allow-listed deterministic repairs may be applied. A failed or unavailable runtime verification means no Dockerfile is returned as a verified artifact.

For example, an Astro project using `@astrojs/vercel/serverless` with `output: 'server'` is not blindly assigned `astro preview`: that adapter is host-specific and does not provide the local preview runtime. The deep pass records the adapter decision and selects a repository dev-server fallback when that is the only deterministic runnable path. Astro's documentation likewise states that `astro preview` for SSR requires an adapter that supports it, with Node being the supported preview adapter in the Astro v4 documentation.

## Design principles

1. **Evidence before generation.** Repository facts are collected before artifacts are synthesized.
2. **Deep deployment analysis before Docker.** Manifests, lockfiles, scripts, framework adapters, output modes, ports and repository layout are reconciled before Dockerfile generation.
3. **Deployment IR is the source of truth.** Docker, Compose, Kubernetes and cloud artifacts are generated from the same normalized model.
4. **No blind AI dependency.** The core engine is deterministic and works without OpenAI or Claude API keys.
5. **Verification before release.** A Dockerfile requested through the generation endpoint is withheld unless the sandbox can build and smoke-test it successfully.
6. **Safety gates.** Destructive migrations, high/critical findings, low confidence and failed validation prevent automatic deployment eligibility.
7. **Bounded repair.** Runtime failures are diagnosed and only approved deterministic mutations are attempted; unknown failures stop instead of triggering arbitrary source rewrites.
8. **Isolation matters.** Docker runtime controls are included, but internet-scale hostile arbitrary repositories should execute in a dedicated worker with a VM/microVM boundary and no host Docker socket exposed to the API.
9. **Pricing honesty.** The bundled pricing layer is a planning engine with a provider adapter boundary; live regional provider catalogs must be refreshed rather than pretending static numbers are live quotes.

## Backend layout

```text
backend/
  core/            scanning, detection, deep deployment analysis, IR, AST/source analysis, dependencies, migrations, policy
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
