# AutoDeploy Stack Intelligence v1.0.0

AutoDeploy analyzes an arbitrary software repository and turns repository evidence into a deployment specification and production-oriented artifacts without requiring an OpenAI/Claude API key.

## v1.0.0 pipeline

`repository → inventory → deterministic detection → source/AST analysis → dependency graph → migration safety → deployment IR → Docker/Compose/Kubernetes/Terraform → static validation → sandbox build/runtime test → diagnosis → bounded repair → security/SBOM plan → cloud cost estimate → deployment policy gate`

### Implemented

- Git repository acquisition with shallow clone and ZIP upload support.
- Resource-bounded repository scanner that ignores build/vendor directories and caps file size.
- Evidence-backed detection for major language/runtime/framework/package-manager families.
- Multi-language source-analysis adapter covering Python, JavaScript/TypeScript, Go, Rust, Java/Kotlin, C#, PHP, Ruby, Swift, Dart and Scala.
- Cross-ecosystem dependency graph inventory with package-lock and manifest resolution where statically available.
- Migration framework detection plus destructive/ambiguous operation detection and mandatory approval policy.
- Versioned Deployment IR (`1.0.0`) used as the source of truth for generated artifacts.
- Hardened Docker/Compose generation with non-root runtime and reduced privileges.
- AWS ECS/Fargate, GCP Cloud Run and Azure Container Apps Terraform synthesis, with managed database/cache resources when detected.
- Kubernetes Deployment/Service/HPA/PDB/NetworkPolicy/ServiceAccount synthesis.
- Deterministic Dockerfile security validation.
- Repository secret detection and integrated SBOM/Trivy execution plans.
- Versioned cloud cost model with region/usage dimensions and a documented live-provider adapter boundary.
- Bounded failure → diagnosis → repair → regeneration → rebuild loop with an attempt ledger.
- Runtime isolation controls: no network, dropped capabilities, no-new-privileges, read-only rootfs, tmpfs, CPU/memory/PID limits.
- Deployment policy gate preventing automatic promotion on low confidence, destructive migrations, high/critical findings or failed validation.
- Regression tests for detection, AST, dependencies, migrations, security, generators, pricing and diagnostics.

## Security boundary

The local runner is a hardened Docker worker implementation for development. For an internet-facing production service, the API must submit jobs to a dedicated sandbox worker and must never expose the host Docker socket to the API. The recommended worker boundary is rootless BuildKit plus a VM/microVM isolation layer (Kata/Firecracker), controlled build egress, ephemeral storage and zero cloud credentials. Runtime egress remains disabled.

## Pricing boundary

The bundled catalog is deterministic planning data, not a live provider quote. Production billing should refresh regional SKU catalogs and normalize compute, storage, managed services, requests, egress, NAT, logs, backups and discounts through the provider adapter interface before presenting a commitment price.

## Autonomous repair policy

Auto-repair is deliberately bounded. Deterministic diagnoses may mutate only deployment IR fields with explicit repair rules. Unknown failures stop the loop instead of blindly editing application source. Every attempt records diagnosis, candidate actions and applied mutation. Production deployment still requires policy gates and approval for risky changes.

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The frontend is a small React/Vite dashboard and consumes `/analyze`, `/validate`, `/analyze-and-validate` and `/analyze-upload`.

## Test

```bash
cd backend
python -m compileall -q .
python -m pytest -q
```

The release regression suite is expected to pass before a v1.0.0 build is promoted.
