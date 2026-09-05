"""Repository-level application boundaries and evidence scoping.

This module is deliberately independent from framework-specific detectors.  The
critical rule is that repository metadata, detector source, documentation, tests,
and unrelated applications are not allowed to masquerade as application evidence.
"""
from pathlib import Path
import json

IGNORED_PARTS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", ".next", "dist", "build", "target", ".terraform", ".gradle", ".idea", ".vscode", "coverage", "bin", "obj", ".pytest_cache", ".mypy_cache", ".tox", ".cache"}
MANIFESTS = {
    "package.json": "node", "pyproject.toml": "python", "requirements.txt": "python",
    "Pipfile": "python", "go.mod": "go", "Cargo.toml": "rust", "pom.xml": "jvm",
    "build.gradle": "jvm", "build.gradle.kts": "jvm", "composer.json": "php",
    "Gemfile": "ruby", "mix.exs": "elixir", "Package.swift": "swift", "pubspec.yaml": "dart",
}
CONTROL_DIRS = {"backend", "frontend", "server", "client", "api", "app", "web", "worker", "workers", "services", "apps", "packages", "src"}


def _depth(path):
    return len(Path(path).parts)


def _root_for(path):
    p = Path(path).parent
    return "" if str(p) == "." else p.as_posix()


def _under(path, root):
    return not root or path == root or path.startswith(root + "/")


def discover_units(repo):
    """Return application units from manifests, not from arbitrary source words."""
    units = []
    for path in repo.files:
        name = Path(path).name
        ecosystem = MANIFESTS.get(name)
        if not ecosystem:
            continue
        root = _root_for(path)
        # A lockfile alone never creates a unit; only real manifests do.
        if name.endswith(".lock"):
            continue
        units.append({"id": root or ".", "root": root, "manifest": path, "manifest_name": name, "ecosystem": ecosystem})

    # A bare static web root is an application unit when no build manifest exists.
    if not units:
        html = [f for f in repo.files if Path(f).name == "index.html"]
        if html:
            roots = sorted({_root_for(f) for f in html}, key=lambda x: (_depth(x), x))
            units.extend({"id": r or ".", "root": r, "manifest": None, "manifest_name": None, "ecosystem": "static"} for r in roots)

    # Keep nested manifests as separate units.  Parent/child units are legitimate
    # in monorepos; selection happens later using deployment evidence.
    return sorted(units, key=lambda u: (_depth(u["root"]), u["root"], u["manifest"] or ""))


def files_for_unit(repo, unit, include_nested_units=False):
    root = unit.get("root", "")
    nested_roots = {u["root"] for u in discover_units(repo) if u["root"] and u["root"] != root and _under(u["root"], root)}
    out = []
    for f in repo.files:
        if not _under(f, root):
            continue
        if not include_nested_units and any(_under(f, n) for n in nested_roots):
            continue
        out.append(f)
    return out


def read_unit_json(repo, unit):
    manifest = unit.get("manifest")
    if not manifest or not manifest.endswith(".json"):
        return {}
    try:
        return repo.json(manifest)
    except Exception:
        return {}


def text(repo, unit, suffixes=None, names=None, include_nested_units=False):
    suffixes = set(suffixes or ())
    names = set(names or ())
    files = files_for_unit(repo, unit, include_nested_units)
    selected = [f for f in files if Path(f).suffix.lower() in suffixes or Path(f).name in names]
    return "\n".join(f"--- {f} ---\n{repo.read(f)}" for f in selected)


def import_text(repo, unit, extensions):
    return text(repo, unit, suffixes=extensions)


def select_unit(repo, preferred_root=None):
    """Select one deployable unit only when evidence supports it.

    A root application is preferred when it has a manifest and a conventional
    application entrypoint. Otherwise the strongest unit is selected. If two
    unrelated units are equally plausible, return an explicit ambiguity instead
    of silently choosing one.
    """
    units = discover_units(repo)
    if not units:
        return None, units, "no_application_unit"
    if preferred_root is not None:
        exact = [u for u in units if u["root"] == preferred_root or u["id"] == preferred_root]
        if len(exact) == 1:
            return exact[0], units, None

    def score(u):
        files = set(files_for_unit(repo, u))
        s = 0
        if u["manifest"]: s += 40
        if any(Path(f).name in {"main.py", "app.py", "server.py", "wsgi.py", "asgi.py", "index.html"} for f in files): s += 25
        if any(Path(f).name in {"Dockerfile", "compose.yaml", "docker-compose.yml", "README.md"} for f in files): s += 5
        if u["root"] == "": s += 8
        if Path(u["root"]).name in CONTROL_DIRS: s += 8
        return s

    ranked = sorted(((score(u), u) for u in units), key=lambda x: (-x[0], _depth(x[1]["root"]), x[1]["root"]))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and ranked[0][1]["root"] != ranked[1][1]["root"]:
        return None, units, "ambiguous_application_units"
    return ranked[0][1], units, None


def describe(repo):
    units = discover_units(repo)
    selected, _, error = select_unit(repo)
    return {
        "units": units,
        "selected_unit": selected,
        "selection_error": error,
        "unit_count": len(units),
    }
