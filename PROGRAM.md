# Stack Detection & Deployment Intelligence — Program Specification

**Document:** `PROGRAM.md`  
**Status:** Active program specification  
**Purpose:** Define what this project is intended to become, what has already been implemented, what remains to be built, the governing algorithm, architectural rules, verification requirements, and the definition of done.

> This document is the engineering north star for the project. It describes the intended behavior of the system rather than merely documenting the current implementation. Items marked **Achieved** are implemented to the degree stated; items marked **In Progress**, **Required**, or **Future** must not be represented as complete until verified.

---

## 1. What this project is

**Stack Detection & Deployment Intelligence** is an independent repository-intelligence system.

It is **not AutoDeploy itself**. It is the technical intelligence layer that can eventually be used by deployment products, but it must remain useful and correct as a standalone system.

The fundamental problem it solves is:

> Given an arbitrary software repository, understand how that repository actually works before producing a deployment artifact.

The system must not reduce a repository to a framework label such as `FastAPI`, `Astro`, `Next.js`, or `Django` and then select a canned Dockerfile. A framework name is only one fact in a much larger deployment model.

The system must determine, from repository evidence:

- what the application is;
- where the application boundary is;
- which parts are production applications versus tooling, tests, examples, documentation, or fixtures;
- which languages and frameworks are actually used;
- which package manager and lockfile govern dependencies;
- which runtime/version is required or safely established;
- how dependencies are installed;
- whether a build is required;
- exactly how the application is started in production;
- which working directory is required;
- which port(s) are exposed;
- how health is established;
- which environment variables and external services are required;
- whether frontend/backend/worker components form one deployable application or multiple deployment targets;
- whether existing Docker, Compose, Kubernetes, Terraform, CI/CD, scripts, or runbooks already define operational behavior;
- whether migrations or security conditions require manual intervention;
- whether enough evidence exists to generate a deterministic deployment artifact.

The central rule is:

> **Understand first. Prove second. Generate third. Verify fourth.**

---

# 2. The intended product behavior

The project should behave like a repository engineer, not like a string-matching Dockerfile generator.

For a repository such as an application with:

```text
README.md
backend/
  requirements.txt
  main.py
frontend/
  package.json
  src/
```

the system should not immediately conclude that it has two unrelated deployment targets.

It must read the repository's operational instructions and inspect the code. If the README says that the backend serves the frontend, and the backend code confirms that relationship, the system should understand the backend and frontend as a composite deployment boundary when appropriate.

Conversely, if the repository contains:

```text
api/       FastAPI service
worker/    Celery worker
frontend/  Next.js application
```

and there is no deterministic evidence that these form one deployable target, the system must not silently choose one. It should report the ambiguity and require an explicit target selection or another deterministic resolution mechanism.

This distinction is fundamental:

- **Integrated components:** resolve when repository evidence proves the relationship.
- **Independent applications:** preserve as separate targets.
- **Ambiguous applications:** block rather than guess.

---

# 3. The most important correction to the original approach

The project originally placed too much weight on manifests, filenames, and source markers while treating documentation as non-runtime material.

That is insufficient.

A repository's README and operational documentation frequently contain the most explicit description of how the author expects the application to be installed, built, started, tested, configured, and deployed.

Therefore:

> **README and operational documentation are first-class deployment evidence.**

They are not automatically authoritative, because documentation can become stale or incorrect. They must be parsed and reconciled against executable repository evidence.

The correct model is not:

```text
README = documentation = ignore
```

and it is also not:

```text
README = absolute truth
```

It is:

```text
README/documentation
        +
manifests/scripts/configuration
        +
source code
        +
CI/CD
        +
existing deployment files
        ↓
Evidence reconciliation
        ↓
Deployment IR
```

---

# 4. Evidence model

Every important deployment fact should eventually be traceable to evidence.

Examples:

```text
Fact: package manager = npm
Evidence: package.json + package-lock.json

Fact: framework = Astro
Evidence: package.json dependency + astro.config.* + scripts

Fact: start command = uvicorn main:app --host 0.0.0.0 --port 8000
Evidence: README + source entrypoint + installed dependency

Fact: frontend is served by backend
Evidence: README architecture/run instructions + backend source serving frontend

Fact: port = 8000
Evidence: production command + application configuration
```

## Evidence classes

### Tier 1 — Executable/deployment truth

Highest authority normally includes:

- existing Dockerfiles;
- Compose files;
- Kubernetes manifests;
- Terraform/cloud deployment configuration;
- CI/CD workflow commands;
- package/build manifests;
- package scripts;
- Makefiles/Justfiles/Taskfiles;
- Procfiles;
- explicit runtime configuration;
- framework configuration files.

### Tier 2 — Operational documentation

Includes:

- `README.md`;
- `README.rst`;
- deployment documentation;
- runbooks;
- setup/development/production documentation;
- contribution documentation when it contains operational instructions.

Documentation is high-value evidence but must be checked for contradictions.

### Tier 3 — Source-code evidence

Includes:

- imports;
- application objects;
- executable entrypoints;
- server initialization;
- build output paths;
- static-file serving;
- port binding;
- health endpoints;
- framework initialization;
- service clients.

### Tier 4 — Structural/conventional evidence

Includes:

- conventional filenames such as `main.py`, `server.js`, `Program.cs`;
- conventional directory structures;
- language extensions;
- standard framework layouts.

### Tier 5 — Generic textual mentions

Generic mentions such as:

```text
"Django is an alternative to FastAPI."
```

must not establish the project's framework.

The system must explicitly prevent detector source, documentation examples, test fixtures, and arbitrary text from becoming false application evidence.

---

# 5. Complete intended algorithm

The canonical pipeline is:

```text
GitHub / ZIP
    ↓
1. ACQUIRE
    ↓
2. COMPLETE INVENTORY
    ↓
3. DOCUMENTATION / README ANALYSIS
    ↓
4. TECHNOLOGY ANALYSIS
    ↓
5. APPLICATION-UNIT DISCOVERY
    ↓
6. ARCHITECTURE + RELATIONSHIP ANALYSIS
    ↓
7. ENTRYPOINT / BUILD / START ANALYSIS
    ↓
8. EVIDENCE RECONCILIATION
    ↓
9. DEPLOYMENT IR
    ↓
10. DETERMINISTIC DEPLOYMENT GATE
    ↓
11. REQUESTED ARTIFACT GENERATION
    ↓
12. STATIC VALIDATION
    ↓
13. OPTIONAL SANDBOX BUILD / RUNTIME VERIFICATION
    ↓
14. DIAGNOSIS + BOUNDED REPAIR
    ↓
15. FINAL DEPLOYMENT GATE
```

Each phase has a specific responsibility.

---

# 6. Phase 1 — Acquire

**Goal:** obtain a reproducible repository snapshot.

Current behavior includes:

- public Git clone;
- shallow clone behavior;
- isolated temporary repository workspace;
- ZIP repository ingestion;
- ZIP path traversal protection;
- repository hashing.

The analysis/generation API uses repository hashes so a previous analysis cannot silently be reused against a changed repository.

**Status: Achieved** for the currently supported acquisition paths.

Future hardening should include stronger clone policies, commit pinning, submodule policy, Git LFS handling policy, archive limits, and resource controls.

---

# 7. Phase 2 — Complete inventory

The inventory must understand the whole repository before making deployment decisions.

It should inventory:

- source files;
- manifests;
- lockfiles;
- README/documentation;
- build scripts;
- shell/PowerShell scripts;
- framework configuration;
- runtime version files;
- Dockerfiles;
- Compose files;
- Kubernetes manifests;
- Terraform/cloud configuration;
- CI/CD workflows;
- environment templates;
- migration files;
- test/example/fixture areas;
- generated artifacts;
- monorepo/workspace metadata.

The scanner already applies safety limits and ignores common non-source/generated directories.

**Status: Achieved as a repository scanner; broader semantic inventory is still In Progress.**

---

# 8. Phase 3 — Documentation and README analysis

This is a major required capability.

The system must actively read operational documentation and extract structured instructions.

It should identify sections and statements such as:

```text
Installation
Setup
Requirements
Development
Build
Production
Run
Start
Deploy
Docker
Environment
Configuration
Database
Health
Architecture
```

It should extract commands such as:

```bash
npm install
npm run build
npm start
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
go build ./cmd/api
cargo run --release
```

It should also identify command context:

```text
Development command
Production command
Test command
Build command
Installation command
```

For example:

```text
uvicorn main:app --reload
```

should be recognized as development-oriented because of `--reload`, not blindly copied into a production Dockerfile.

If README states:

```text
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

the resulting evidence must include:

```text
working_directory = backend
runtime_command = uvicorn main:app --host 0.0.0.0 --port 8000
port = 8000
entrypoint = main:app
```

**Status: Required / In Progress.**

The repository currently has the analysis-first architecture and evidence boundaries, but README must become a dedicated structured operational-evidence subsystem rather than being broadly excluded from runtime evidence.

---

# 9. Phase 4 — Technology analysis

The system must identify technology from evidence rather than from generic text.

The catalog has already been expanded substantially.

Current catalog coverage includes major ecosystems such as:

- Node.js;
- Deno;
- Python;
- Go;
- Rust;
- JVM;
- Scala;
- PHP;
- Ruby;
- Elixir;
- Erlang;
- Swift;
- Dart;
- Haskell;
- C/C++ and native build systems;
- .NET;
- Clojure;
- and broad source-language extension coverage.

Framework coverage includes, among others:

- Next.js;
- Nuxt;
- NestJS;
- Express;
- Fastify;
- Koa;
- Hono;
- Remix;
- SvelteKit;
- Angular;
- React;
- Vue;
- Svelte;
- Astro;
- Gatsby;
- Vite;
- Docusaurus;
- Django;
- FastAPI;
- Flask;
- Litestar;
- Sanic;
- Starlette;
- Quart;
- Tornado;
- Falcon;
- Pyramid;
- Bottle;
- aiohttp;
- Streamlit;
- Gradio;
- Celery;
- Gin;
- Echo;
- Fiber;
- Chi;
- Axum;
- Actix Web;
- Rocket;
- Spring Boot;
- Quarkus;
- Micronaut;
- Ktor;
- Play Framework;
- ASP.NET Core;
- Laravel;
- Symfony;
- WordPress;
- Rails;
- Sinatra;
- Phoenix;
- and others represented in the technology catalog.

Lockfiles are explicitly separated from application manifests so a lockfile alone cannot create a false application unit.

**Status: Achieved as a catalog foundation; evidence quality and strategy coverage continue to expand.**

---

# 10. Phase 5 — Application-unit discovery

The system must determine the boundaries of actual applications.

An application unit may be:

- the repository root;
- a backend;
- a frontend;
- a worker;
- a service;
- a CLI;
- a static site;
- another independently executable component.

Multiple manifests in the same application directory are grouped into one unit when appropriate.

The system must not treat these as automatically equivalent:

```text
/api
/frontend
/worker
```

Folder names are clues, not proof.

Current implementation has:

- manifest-based application-unit discovery;
- static `index.html` unit discovery;
- lockfile-only protection;
- non-runtime directory filtering;
- polyglot same-root grouping;
- application-target ambiguity blocking;
- preferred-root selection support at the core selection layer.

**Status: Achieved as a strong foundation; documentation-driven boundary resolution is Required.**

---

# 11. Phase 6 — Architecture and relationship analysis

The system must understand relationships between application units.

Examples:

```text
frontend → backend API
backend → frontend static files
web → worker
web → database
worker → queue
application → Redis
application → S3
```

A sibling frontend should only be considered part of a backend deployment boundary when evidence proves that the backend serves/builds/includes it.

Evidence may include:

- README statements;
- source references;
- static serving configuration;
- build output references;
- package scripts;
- CI pipeline relationships;
- Docker/Compose configuration.

The recently added integrated-host logic is an initial implementation of this concept.

**Status: Partially Achieved.**

The current implementation detects some concrete host-serving relationships. It must be expanded into a general architecture relationship model and must prioritize README/operational evidence.

---

# 12. Phase 7 — Entrypoint, installation, build and start analysis

This is the core of deployment intelligence.

For every candidate application, the system should answer:

### Installation

How are dependencies installed?

### Build

Does a production build exist? What command produces it? Where does output go?

### Start

What exact production command starts the application?

### Working directory

Where must the command execute?

### Port

Which port is actually bound?

### Health

Is there a health endpoint or deterministic process-health mechanism?

### Runtime

Which runtime and version are required?

### Filesystem

What files must exist at runtime? Is a writable directory required?

### Environment

Which variables are required, optional, secret, or externally supplied?

The analyzer must prefer explicit evidence over conventions.

It must distinguish:

```text
production
```
from:

```text
development
```

and:

```text
test
```

commands.

**Status: Partially Achieved.**

Many common strategies are already implemented, but the evidence/reconciliation layer must become substantially deeper and README-aware.

---

# 13. Phase 8 — Evidence reconciliation

No important deployment decision should depend on one weak signal when multiple stronger signals exist.

The reconciler should combine evidence and detect contradictions.

Example:

```text
README:
    npm start

package.json:
    start = node server.js

source:
    server.js creates HTTP server

CI:
    npm ci && npm run build && npm start
```

Result:

```text
start command = npm start
resolved executable behavior = node server.js
confidence = high
```

Contradiction example:

```text
README:
    npm run preview

package.json:
    preview = vite preview

Astro config:
    output = static

CI:
    npm run build
```

The system should investigate whether the repository is a static Astro deployment, an SSR deployment, or a preview-only workflow. It must not blindly select the first matching command.

When evidence conflicts materially and cannot be deterministically resolved, the correct result is:

```text
BLOCKED
reason = contradictory_deployment_evidence
```

not a guess.

**Status: Required.**

---

# 14. Phase 9 — Deployment IR

The Deployment IR is the normalized source of truth consumed by artifact generators.

A target IR should eventually contain information similar to:

```json
{
  "application": {
    "root": "backend",
    "role": "web",
    "boundary_type": "composite"
  },
  "technology": {
    "language": "Python",
    "framework": "FastAPI",
    "runtime": "python",
    "runtime_version": "3.12"
  },
  "dependencies": {
    "package_manager": "pip",
    "manifest": "backend/requirements.txt",
    "lockfile": null
  },
  "installation": {
    "command": "pip install -r requirements.txt"
  },
  "build": {
    "required": false,
    "command": null
  },
  "runtime": {
    "working_directory": "backend",
    "command": "uvicorn main:app --host 0.0.0.0 --port 8000",
    "port": 8000
  },
  "health": {
    "endpoint": "/health"
  },
  "services": [],
  "environment": [],
  "evidence": []
}
```

The exact schema may evolve, but the architectural principle must not:

> **Generators consume Deployment IR. Generators do not rediscover repository behavior.**

**Status: Achieved as the current architecture; schema depth and evidence traceability are In Progress.**

---

# 15. Phase 10 — Deterministic deployment gate

Generation is allowed only if the target has enough evidence to establish a safe strategy.

Minimum questions include:

```text
Do we know the application boundary?
Do we know the language?
Do we know the runtime?
Do we know how dependencies are installed?
Do we know whether a build is required?
Do we know how production starts?
Do we know the working directory?
Do we know the listening port or a safe strategy to determine it?
Do we know required runtime files?
Do we understand critical external services?
Are there unresolved contradictions?
```

If yes:

```text
READY
```

If not:

```text
BLOCKED
```

The blocker must explain exactly what is missing or contradictory.

Examples:

```text
BLOCKED
Application target is ambiguous.

BLOCKED
Production entrypoint cannot be established.

BLOCKED
README and CI define contradictory production commands.

BLOCKED
Recognized ecosystem has no deterministic deployment strategy.
```

This is a **fail-closed** system.

**Status: Achieved as the core gate.**

---

# 16. Phase 11 — Requested artifact generation

Generation must be explicitly requested.

If the user requests:

```text
Dockerfile
```

generate only the Dockerfile.

If the user requests:

```text
Compose
```

generate only Compose.

Likewise:

- Kubernetes;
- Terraform AWS;
- Terraform GCP;
- Terraform Azure;
- future deployment artifacts.

Analysis must never silently generate deployment artifacts.

Generation must reuse a completed analysis through `analysis_id` only when the repository hash is unchanged.

**Status: Achieved.**

---

# 17. Dockerfile generation requirements

The Docker generator must not perform independent technology detection.

It receives the Deployment IR and produces the requested Dockerfile.

The generated Dockerfile should reflect:

- correct base runtime;
- correct runtime version;
- correct working directory;
- correct dependency installation;
- correct build process;
- production-only dependencies where safe;
- correct copied artifacts;
- correct entrypoint;
- correct port;
- correct environment behavior;
- non-root operation where supported;
- minimal attack surface;
- deterministic and reproducible behavior where practical.

Development-only commands such as:

```text
--reload
vite dev
astro dev
```

must not accidentally become production commands.

**Status: Partially Achieved.**

The current generator supports multiple major ecosystems and deployment strategies. Deeper IR-driven production-command resolution and broader strategy coverage remain Required.

---

# 18. Existing technology strategy coverage

The current deep analyzer has deterministic paths for several common deployment families.

These include:

### Node.js

- generic Node application/script;
- common framework applications;
- static-node paths;
- Astro-specific strategies including development-server fallback, Node standalone, and static preview paths.

### Python

Common WSGI/ASGI deployment paths including:

- Django;
- FastAPI;
- Litestar;
- Sanic;
- Starlette;
- Quart;
- Flask.

Entrypoint discovery includes conventional files such as:

```text
main.py
app.py
server.py
application.py
wsgi.py
asgi.py
```

### Go

- Go binary strategy;
- `package main` and `func main()` detection;
- common `cmd/...` structures.

### Rust

- Cargo binary strategy.

### JVM

- Spring Boot;
- Quarkus;
- Micronaut;
- Ktor;
- Play Framework;
- JAR-oriented deployment strategy.

### .NET

- ASP.NET Core deployment strategy.

### PHP

- Apache-oriented deployment strategy for supported applications.

### Ruby

- Rails/Rack deployment paths.

Recognized ecosystems without a deterministic implementation must be blocked rather than falsely mapped to another technology.

**Status: Achieved as an initial deterministic strategy matrix; expansion and fixture coverage are Required.**

---

# 19. Unsupported technologies

Recognition and deployability are separate concepts.

A technology may be recognized correctly while still being unsupported for automatic artifact generation.

For example:

```text
Technology: Elixir
Recognition: YES
Deterministic deployment strategy: NO
Generation: BLOCKED
```

This is a valid result.

The system must never say:

```text
Elixir detected
→ use generic Node Dockerfile
```

or otherwise fabricate a deployment strategy.

Future support should be added through explicit strategy implementations and tests.

---

# 20. Runtime-version resolution

Runtime versions must be evidence-based.

The analyzer should inspect, where relevant:

```text
.nvmrc
.node-version
.python-version
runtime.txt
.tool-versions
pyproject.toml
package.json engines
Go go.mod
rust-toolchain.toml
Cargo.toml
pom.xml
build.gradle
csproj TargetFramework
composer platform requirements
Gemfile / Ruby version configuration
framework-specific version files
```

Current implementation has several safe/default runtime fallbacks for unsupported or missing explicit version evidence.

These defaults must not silently be represented as facts.

Preferred future behavior:

```text
explicit version → authoritative
compatible declared range → resolved policy
no version evidence → clearly marked inferred baseline or block according to strategy
```

**Status: In Progress.**

---

# 21. Dependency analysis

Dependency analysis must understand:

- direct dependencies;
- development dependencies;
- optional dependencies;
- peer dependencies where relevant;
- lockfiles;
- resolved dependency counts;
- workspace/monorepo dependencies;
- production dependency requirements.

Lockfiles are evidence for dependency resolution but must not independently create application targets.

The current dependency graph subsystem supports multiple ecosystems.

**Status: Achieved as a foundation; deeper production-dependency semantics remain In Progress.**

---

# 22. Source and AST analysis

Source analysis exists to verify deployment conclusions, not to replace deterministic repository understanding with arbitrary code interpretation.

The project currently uses:

- Python standard-library AST analysis;
- syntax-aware/lexical adapters for other supported languages;
- import analysis;
- source structure analysis.

The analyzer should use source evidence to verify claims such as:

```text
FastAPI app exists
HTTP server exists
main function exists
static directory is served
port is configured
health route exists
```

**Status: Achieved as a foundation.**

---

# 23. Services and environment analysis

The analysis should identify likely external services, including where supported:

- PostgreSQL;
- MySQL/MariaDB;
- MongoDB;
- Redis;
- RabbitMQ;
- Kafka;
- Elasticsearch;
- S3;
- Supabase;
- Firebase;
- Stripe;
- DynamoDB;
- SQLite.

Environment analysis should distinguish:

```text
required runtime variable
optional variable
secret
local-development variable
service URL
credential
```

Secrets must never be copied into generated artifacts.

**Status: Partially Achieved.**

---

# 24. Infrastructure and CI/CD analysis

Existing infrastructure must be discovered before generating replacement infrastructure.

Inspect:

```text
Dockerfile
compose.yaml
k8s/*.yaml
helm/
terraform/
*.tf
.github/workflows/
.gitlab-ci.yml
Jenkinsfile
cloudbuild.yaml
serverless configuration
platform-specific deployment files
```

The system should understand whether an existing artifact is:

- authoritative production configuration;
- development configuration;
- obsolete/legacy;
- partial evidence.

**Status: Foundation Achieved; semantic reconciliation Required.**

---

# 25. Migration analysis

Database migrations must be analyzed separately from application deployment.

The system should identify:

- migration framework;
- pending migration requirements;
- destructive operations;
- schema changes;
- data migrations;
- whether manual approval is required.

A deployment artifact must not automatically perform dangerous destructive migrations merely because a migration command exists.

The current migration analyzer can flag destructive migration patterns and require manual approval.

**Status: Achieved as a safety layer; broader framework coverage remains In Progress.**

---

# 26. Security analysis

Security is part of deployment intelligence, not an afterthought.

The system already has planning/analysis for:

- repository secret findings;
- unsafe Dockerfile patterns;
- SBOM generation planning;
- vulnerability scanning planning;
- security policy evaluation.

Generated artifacts should favor:

- non-root users;
- minimal images;
- no unnecessary capabilities;
- safe filesystem permissions;
- explicit ports;
- no embedded secrets;
- predictable runtime behavior.

**Status: Foundation Achieved; production-grade security policy expansion Required.**

---

# 27. Sandbox verification

Static validation is not enough.

Where explicitly requested, the system should be able to:

```text
Generate
  ↓
Build image
  ↓
Start isolated container
  ↓
Smoke test
  ↓
Health check
  ↓
Inspect logs
  ↓
Diagnose
  ↓
Bounded repair
  ↓
Rebuild
  ↓
Retest
```

The sandbox currently applies restrictions such as:

- network controls;
- dropped capabilities;
- no-new-privileges;
- process limits;
- memory/CPU limits;
- read-only root filesystem where appropriate;
- temporary writable filesystems;
- isolated runtime networking;
- smoke testing;
- bounded repair attempts.

**Status: Foundation Achieved.**

Actual Docker build/runtime verification must be performed in CI or an environment with Docker available; it must never be claimed as passed merely because the code exists.

---

# 28. Bounded repair

If generated Docker configuration fails validation, repair must be constrained.

Allowed repair should operate on known failure classes such as:

```text
missing directory
wrong working directory
missing runtime file
incorrect port
known package installation issue
known framework command issue
```

It must not become:

```text
AI edits arbitrary application source until tests pass
```

The repository source should remain protected unless a future explicitly authorized repair mode is introduced.

**Status: Achieved as a bounded-repair foundation.**

---

# 29. AI policy

The core deterministic pipeline must not require an OpenAI, Claude, or other model API key.

AI may eventually be useful for:

- interpreting ambiguous human documentation;
- explaining blockers;
- suggesting remediation;
- ranking non-authoritative evidence;
- assisting unsupported strategy research.

But AI must not silently fabricate deployment facts.

The deterministic engine remains the authority for release gates.

A model suggestion must never convert:

```text
unknown
```

to:

```text
known
```

without verifiable repository evidence.

---

# 30. Analysis-first API contract

The API architecture already separates analysis and generation.

Important endpoints include:

```text
POST /analyze
POST /analyze-stream
POST /generate/dockerfile
POST /generate/docker-compose
POST /generate/{artifact}
POST /validate
POST /analyze-and-validate
POST /analyze-upload
```

Analysis returns no generated deployment artifact.

Generation can reuse an `analysis_id` only if the repository hash still matches.

The generation gate checks the completed deep-analysis state before releasing an artifact.

Structured generation failures retain:

- message;
- phase;
- requested artifact;
- relevant deep-analysis details;
- validation details where applicable.

The frontend must render these structures as human-readable errors and must never display JavaScript `[object Object]`.

**Status: Achieved.**

---

# 31. Frontend requirements

The dashboard should make the analysis understandable rather than merely showing a final framework label.

Current UI areas include:

- Overview;
- Deep Analysis;
- Evidence;
- Stacks;
- Dependencies;
- Migrations;
- Security;
- Artifacts;
- Run Script;
- Deployment IR.

The UI should eventually make the following visible:

```text
What did we find?
Why do we believe it?
What application are we deploying?
Why was this boundary selected?
Which README instructions were used?
Which executable files confirmed them?
What contradictions were found?
What deployment strategy was selected?
Why is generation allowed or blocked?
```

For an ambiguous monorepo, the UI should eventually offer explicit target selection rather than forcing the user to infer the blocker from logs.

**Status: Partially Achieved.**

---

# 32. Monorepo and multi-application behavior

This is a critical correctness requirement.

The analyzer must support repositories containing:

```text
frontend
backend
worker
scheduler
CLI
packages
services
```

It must distinguish:

### One application split across directories

Resolve into one composite deployment boundary when proven.

### Multiple independently deployable applications

Represent as multiple targets.

### Multiple plausible targets without enough evidence

Block and ask for explicit target selection.

Future API behavior should support something like:

```text
analysis
  targets:
    - backend
    - frontend
    - worker

selected_target:
    backend
```

rather than making the repository permanently ambiguous.

**Status: Core ambiguity protection Achieved; explicit API/UI target selection Required.**

---

# 33. Existing repository work that is already achieved

The project currently has a substantial foundation.

### Repository safety and scanning

- repository scanner;
- ignored/generated directory handling;
- file size/read limits;
- repository hashing;
- ZIP safety checks.

### Detection

- broad ecosystem catalog;
- framework catalog;
- package manager detection;
- lockfile separation;
- source-language mapping.

### Application boundaries

- application-unit discovery;
- same-root polyglot grouping;
- static application discovery;
- non-runtime evidence filtering;
- ambiguity blocking;
- integrated host/dependency selection foundation.

### Deep deployment analysis

- authoritative scoped deep analyzer;
- deterministic strategy selection for multiple common ecosystems;
- unsupported strategy blocking;
- application-boundary blockers;
- runtime/build/start/entrypoint/port/service analysis foundation.

### Generation

- analysis-first generation;
- analysis cache and repository hash validation;
- requested-artifact-only generation;
- Dockerfile generation;
- Compose generation;
- Kubernetes generation;
- Terraform AWS/GCP/Azure generation boundaries;
- static Dockerfile validation.

### Verification and security

- sandbox policy;
- Docker runtime validation architecture;
- smoke testing;
- diagnostics;
- bounded repair;
- migration safety gate;
- security analysis;
- SBOM/vulnerability scan planning.

### Tests

Regression coverage exists for important boundary cases including:

- detector source not becoming framework evidence;
- multiple real application units remaining ambiguous;
- backend + static frontend not being silently merged;
- polyglot manifests in one root being grouped;
- lockfiles not creating application units;
- documentation/test technology mentions not becoming the application framework;
- a host application with concrete frontend-serving evidence being selected as the composite boundary.

---

# 34. What is NOT yet complete

The following must not be considered solved merely because a partial implementation exists.

## Highest priority

### A. README/operational documentation intelligence

**Required.**

The analyzer must actively parse README and deployment documentation and convert operational instructions into structured evidence.

### B. Evidence reconciliation

**Required.**

README, manifests, source, CI, scripts, existing deployment files, and configuration must be reconciled rather than considered independently.

### C. Runtime version truth

**Required.**

Remove or explicitly mark silent version guesses.

### D. General architecture relationships

**Required.**

Move from special-case frontend-serving detection toward a reusable relationship model.

### E. Explicit target selection

**Required.**

When a repository genuinely has multiple applications, expose the target list and let the user select one rather than providing only a generic blocker.

### F. Strategy registry

**Required.**

Move deployment strategies toward a capability/requirements registry instead of an ever-growing set of hard-coded branches.

### G. Full integration fixtures

**Required.**

Every supported strategy must have repository fixtures proving:

```text
analyze → READY → generate → validate
```

and unsupported/ambiguous fixtures proving:

```text
analyze → BLOCKED
```

### H. Real CI verification

**Required.**

Connector-created commits have not always triggered the repository's GitHub Actions workflow. A release cannot be declared verified until CI has actually executed against the relevant commit or the code has been independently executed in an equivalent environment.

---

# 35. Testing philosophy

Tests must verify behavior, not merely function execution.

For each supported technology, fixtures should cover:

1. minimal application;
2. README with explicit install/build/start instructions;
3. README with development and production commands;
4. nested application root;
5. monorepo;
6. frontend/backend composite;
7. multiple independent services;
8. misleading docs;
9. misleading detector/source text;
10. lockfile-only repository;
11. missing runtime version;
12. contradictory commands;
13. existing Dockerfile;
14. existing CI deployment instructions;
15. external service requirements;
16. migration requirements;
17. unsupported technology.

A strategy is not complete until its failure modes are tested.

---

# 36. Definition of READY

A repository target is `READY` only when:

```text
Application boundary        proven
Technology                  proven
Runtime                     proven or policy-approved
Dependency installation     proven
Build behavior              proven/not-required
Production start            proven
Working directory           proven/not-required
Port                        proven or deterministic
Critical services           understood
Critical environment        understood
Contradictions              resolved
Deployment strategy         supported
```

The exact threshold can evolve, but the system must always be able to explain why it considers a target ready.

---

# 37. Definition of BLOCKED

A repository is `BLOCKED` when safe deterministic generation cannot be established.

Examples:

```text
No application unit found
Multiple deployment targets with no unique selection
Contradictory production commands
Unsupported deployment strategy
Missing executable entrypoint
Unknown critical runtime behavior
Unresolved destructive migration approval
Insufficient evidence for requested artifact
```

A blocker is a **correct result**, not an error in the product, when the repository genuinely does not provide enough evidence for safe automatic deployment.

However, the system must continuously reduce **false blockers** caused by incomplete analysis of evidence that is actually present in the repository.

---

# 38. Definition of GENERATION COMPLETE

A generated artifact is complete only when:

```text
Analysis READY
      ↓
Requested artifact generated
      ↓
Artifact statically validated
      ↓
Optional runtime verification passed
      ↓
Security checks acceptable
      ↓
Deployment gate passed
```

Generation must never be described as successful merely because a text file was produced.

---

# 39. Definition of DONE for the program

The project reaches its intended mature state when an arbitrary repository can be processed through the following contract:

```text
1. Clone repository.
2. Read the repository completely enough to understand its structure.
3. Read README and operational documentation.
4. Identify all application candidates.
5. Determine which candidates are actually deployable.
6. Determine relationships between them.
7. Determine technology from strong evidence.
8. Determine install/build/start behavior.
9. Determine runtime, port, health, services and environment.
10. Reconcile all evidence.
11. Produce an evidence-backed Deployment IR.
12. Explain the selected strategy.
13. Block if evidence is insufficient or contradictory.
14. Generate only the requested artifact.
15. Validate the artifact.
16. Optionally build/run it in a sandbox.
17. Diagnose failures.
18. Apply only bounded deterministic repairs.
19. Revalidate.
20. Release only when the deployment gate passes.
```

The system must be able to answer, for every generated Dockerfile:

> **"Why exactly did you generate this Dockerfile? Show me the repository evidence that proves every important decision."**

That question is the ultimate quality bar.

---

# 40. Engineering rules — do not violate these

1. **Never guess an application boundary when real ambiguity exists.**
2. **Never ignore README/operational documentation when determining deployment behavior.**
3. **Never treat README as unquestionable truth; reconcile it against executable evidence.**
4. **Never let detector source code become application evidence.**
5. **Never let docs/examples/tests create false framework detection.**
6. **Never let a lockfile alone create an application.**
7. **Never use a framework label as the deployment strategy by itself.**
8. **Never generate before deep analysis is complete.**
9. **Never generate an artifact that was not requested.**
10. **Never silently substitute an unsupported strategy.**
11. **Never hide a contradiction.**
12. **Never silently turn a development command into a production command.**
13. **Never embed secrets in generated artifacts.**
14. **Never claim runtime verification passed unless it actually ran.**
15. **Never let AI override deterministic evidence without verification.**
16. **Never weaken a safety gate merely to make a test repository generate.**
17. **Fix the generalized algorithm, not one repository-specific case.**
18. **Every new strategy must come with positive and negative fixtures.**
19. **Deployment generators consume Deployment IR; they do not rediscover the repository.**
20. **When evidence is insufficient, explain the blocker rather than fabricate certainty.**

---

# 41. Current priority order

The next engineering sequence should be:

```text
PRIORITY 1
README + operational documentation parser

PRIORITY 2
Evidence model + reconciliation engine

PRIORITY 3
General application relationship graph

PRIORITY 4
Evidence-based runtime/version resolution

PRIORITY 5
Explicit target selection API + UI

PRIORITY 6
Deployment strategy registry/capability model

PRIORITY 7
Full strategy fixtures and integration tests

PRIORITY 8
CI reliability and reproducible verification

PRIORITY 9
Expand ecosystem/strategy coverage

PRIORITY 10
Production hardening and performance
```

Do not jump to Priority 9 merely because the technology catalog looks impressive. Correct repository understanding is more important than the number of frameworks recognized.

---

# 42. Relationship to Astro Blog and other test repositories

Repositories such as **astro-blog** and **stack-detection** are not special-case targets.

They are test cases for the generalized repository-understanding algorithm.

If both repositories contain explicit README instructions describing:

- installation;
- build;
- development;
- production;
- preview;
- deployment;
- environment;
- architecture;

the analyzer must learn to extract those instructions generically.

A fix that says:

```text
if repo == stack-detection:
    choose backend
```

is prohibited.

A fix that says:

```text
if README + source + manifests prove that component A serves component B:
    resolve the composite boundary
```

is the correct class of fix.

---

# 43. Final architectural vision

The mature system should effectively perform:

```text
                    REPOSITORY
                        │
                        ▼
              ┌───────────────────┐
              │ COMPLETE INVENTORY│
              └─────────┬─────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     DOCUMENTATION   EXECUTABLE    STRUCTURE
       EVIDENCE       EVIDENCE      EVIDENCE
          │             │             │
          └─────────────┼─────────────┘
                        ▼
              ┌───────────────────┐
              │ EVIDENCE GRAPH    │
              │                   │
              │ apps              │
              │ components        │
              │ commands          │
              │ dependencies      │
              │ services          │
              │ ports             │
              │ environments      │
              │ relationships     │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ DEPLOYMENT IR     │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ DETERMINISTIC GATE│
              └─────────┬─────────┘
                        │
                 ┌──────┴──────┐
                 │             │
               READY        BLOCKED
                 │             │
                 ▼             ▼
          REQUESTED ARTIFACT  EXPLAIN WHY
                 │
                 ▼
             VALIDATION
                 │
                 ▼
              SANDBOX
                 │
                 ▼
          DIAGNOSIS / REPAIR
                 │
                 ▼
          DEPLOYMENT GATE
```

The end product is not merely a Dockerfile generator.

It is a **repository deployment intelligence engine** whose output happens to include deployment artifacts.

The Dockerfile is the final expression of the analysis — **not the analysis itself**.

---

# 44. Short version — the rule to remember

If there is ever uncertainty about what the program should do, use this sequence:

```text
READ THE REPOSITORY
        ↓
READ THE README
        ↓
READ THE OPERATIONAL DOCS
        ↓
UNDERSTAND THE APPLICATION BOUNDARY
        ↓
VERIFY WITH MANIFESTS + SOURCE + CONFIG + CI
        ↓
RECONCILE CONFLICTS
        ↓
BUILD DEPLOYMENT IR
        ↓
PROVE DEPLOYABILITY
        ↓
GENERATE ONLY WHAT THE USER REQUESTED
        ↓
VERIFY IT
```

**Do not skip the understanding phase just because a framework is recognizable.**
