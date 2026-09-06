"""Multi-repository docker-compose orchestration.

Wires together N independently-analyzed repositories (e.g. a frontend + a backend) plus any
shared infrastructure services they declare needing, into one docker-compose.yaml. Each
repo is still analyzed by the existing single-repo pipeline unchanged - this module only
adds the part a single-repo analysis structurally cannot do on its own: knowing that one
app's env var should point at another app's compose service name.

Deliberately conservative, matching this project's fail-closed doctrine (PROGRAM.md): a
cross-repo URL is only ever auto-wired when the evidence is unambiguous - a committed
.env-family file declaring a var shaped like `*_API_URL`/`*_BACKEND_URL` with an http(s)
value, AND exactly one other submitted repo identifiable as "the backend" (either an
explicit role hint, or the one repo declaring its own backing data service). Client-exposed
build-time env var prefixes (VITE_, NEXT_PUBLIC_, REACT_APP_, ...) are a real, documented
bundler convention, not a guess, so those are wired as Docker build ARGs; everything else is
a runtime environment var. Anything less certain than that is left as an explicit note
rather than silently guessed or silently dropped.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from generators.docker import dockerfile, _COMPOSE_SERVICES

_URL_VAR = re.compile(r"(?i)^[A-Z][A-Z0-9_]*(?:API|BACKEND|SERVER)[A-Z0-9_]*URL$")
_SECRET_SUFFIX = re.compile(r"(?i)(PASSWORD|TOKEN|SECRET|KEY)$")
# Bundler conventions where the prefix ALONE guarantees the var is inlined into the compiled
# JS at build time (Vite, Next.js, Create React App, Vue CLI, Gatsby) - a real, documented
# rule per tool, not a heuristic guess.
_BUILD_TIME_PREFIXES = ("VITE_", "NEXT_PUBLIC_", "REACT_APP_", "PUBLIC_", "VUE_APP_", "GATSBY_")


def slug(repo_url):
    name = urlparse(str(repo_url)).path.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.git$", "", name)
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "app"


def _declared_urls(repo):
    # Checked across .env.example/.env.sample/.env.template AND a real committed .env -
    # evidence only, never baked into an image (see generators.docker.dockerignore) - since a
    # demo/tutorial repo often ships its real dev defaults directly in .env with no separate
    # .example file (e.g. bradtraversy/friendly-dev-frontend). First file found wins per key.
    out = {}
    for fname in (".env.example", ".env.sample", ".env.template", ".env"):
        f = next((x for x in repo.files if Path(x).name == fname), None)
        if not f:
            continue
        for line in repo.read(f).splitlines():
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip("\"'")
            if key in out or _SECRET_SUFFIX.search(key):
                continue
            if _URL_VAR.match(key) and re.match(r"(?i)^https?://", val):
                out[key] = val
    return out


def _inject_build_args(df, arg_names):
    """Insert `ARG X` / `ENV X=$X` right before the build stage's own build command, so a
    build-time-only env var is actually visible when `npm run build` (or equivalent) runs.
    Every Node branch in generators.docker.dockerfile() copies source (`COPY . .`)
    immediately before running its build command - the one structural constant this relies
    on; only ever invoked when a VITE_/NEXT_PUBLIC_/...-prefixed var was found, which only
    happens for JS frontends that take one of those branches."""
    if not arg_names:
        return df
    block = "".join(f"ARG {a}\n" for a in arg_names) + f"ENV {' '.join(f'{a}=${a}' for a in arg_names)}\n"
    return re.sub(r"(COPY \. \.\n)(RUN )", lambda m: m.group(1) + block + m.group(2), df, count=1)


def build(analyzed):
    """analyzed: list of {"slug", "spec", "repo", "role"} - one per repository already run
    through the existing single-repo analysis pipeline (deep_analysis.status must already be
    "ready" for every entry; callers gate that before calling this).

    Returns (dockerfiles: {slug: str}, compose_yaml: str, notes: list[str])."""
    notes = []
    services_by_slug = {a["slug"]: {x["name"] for x in a["spec"].services} for a in analyzed}
    by_slug = {a["slug"]: a for a in analyzed}

    backend_candidates = [a["slug"] for a in analyzed if a.get("role") == "backend"]
    if not backend_candidates:
        backend_candidates = [s for s in services_by_slug if services_by_slug[s]]
    backend_slug = backend_candidates[0] if len(backend_candidates) == 1 else None
    if len(backend_candidates) > 1:
        notes.append(f"Multiple repos ({', '.join(backend_candidates)}) each declare their own backing service - cross-repo URL wiring was skipped as ambiguous. Pass role=\"backend\" on exactly one repo to resolve this, or wire the others manually.")

    backend_port = by_slug[backend_slug]["spec"].network.get("port") if backend_slug else None
    backend_health = by_slug[backend_slug]["spec"].network.get("health_endpoint") if backend_slug else None

    dockerfiles = {}
    app_blocks = []
    shared_needed = set()
    for a in analyzed:
        s, spec = a["slug"], a["spec"]
        df = dockerfile(spec)
        port = spec.network.get("port") or 8000
        needed = services_by_slug[s]
        shared_needed |= needed

        build_args, run_env = {}, {}
        if backend_slug and s != backend_slug:
            for key, val in _declared_urls(a["repo"]).items():
                path = urlparse(val).path or ""
                new_val = f"http://{backend_slug}:{backend_port}{path}"
                (build_args if key.startswith(_BUILD_TIME_PREFIXES) else run_env)[key] = new_val
            if not build_args and not run_env:
                notes.append(f"'{s}' declares no *_API_URL/*_BACKEND_URL-shaped env var pointing at another service - if it needs to reach '{backend_slug}', wire it manually (http://{backend_slug}:{backend_port}).")
        elif not backend_slug and s not in backend_candidates and _declared_urls(a["repo"]):
            notes.append(f"'{s}' declares a backend-looking URL env var, but no single other repo could be identified as the backend it should point to - wire it manually.")

        if build_args:
            df = _inject_build_args(df, list(build_args.keys()))
        dockerfiles[s] = df

        depends = []
        for svc in needed:
            entry = _COMPOSE_SERVICES.get(svc)
            if entry:
                depends.append((entry[0], "service_healthy"))
        if backend_slug and s != backend_slug and (build_args or run_env):
            depends.append((backend_slug, "service_healthy" if backend_health else "service_started"))

        env_block = ("\n    environment:\n" + "\n".join(f"      {k}: {v}" for k, v in run_env.items())) if run_env else ""
        args_block = ("\n      args:\n" + "\n".join(f"        {k}: {v}" for k, v in build_args.items())) if build_args else ""
        depends_block = ("\n    depends_on:\n" + "\n".join(f"      {d}:\n        condition: {c}" for d, c in depends)) if depends else ""
        app_blocks.append(f'  {s}:\n    build:\n      context: ./{s}{args_block}\n    ports:\n      - "{port}:{port}"{env_block}{depends_block}\n    restart: unless-stopped')

    # Shared infra services (db/cache/...) reuse the exact same catalog, healthcheck, and
    # restart-policy pattern as the single-repo compose() generator, rather than
    # reimplementing it - see generators.docker._COMPOSE_SERVICES.
    shared_blocks, vols = [], []
    for svc_name, (key, image, env, path, hc) in _COMPOSE_SERVICES.items():
        if svc_name not in shared_needed:
            continue
        env_block = f"\n    environment:\n{env}" if env else ""
        healthcheck = f"\n    healthcheck:\n      test: {json.dumps(hc)}\n      interval: 10s\n      timeout: 5s\n      retries: 5"
        vol = f"{key}-data"
        shared_blocks.append(f"  {key}:\n    image: {image}{env_block}\n    volumes:\n      - {vol}:{path}{healthcheck}\n    restart: unless-stopped")
        vols.append(f"  {vol}:")

    volume_block = "\nvolumes:\n" + "\n".join(vols) if vols else ""
    compose_yaml = "services:\n" + "\n".join(app_blocks + shared_blocks) + volume_block + "\n"
    return dockerfiles, compose_yaml, notes
