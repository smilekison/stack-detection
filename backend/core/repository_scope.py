"""Repository-level application boundaries and evidence scoping.

This module is deliberately independent from framework-specific detectors. The critical
rule is that repository metadata, detector source, documentation, tests, generated output,
and unrelated applications are not allowed to masquerade as application evidence.
"""
from pathlib import Path

MANIFESTS = {
    "package.json": "node", "pyproject.toml": "python", "requirements.txt": "python",
    "Pipfile": "python", "go.mod": "go", "Cargo.toml": "rust", "pom.xml": "jvm",
    "build.gradle": "jvm", "build.gradle.kts": "jvm", "composer.json": "php",
    "Gemfile": "ruby", "mix.exs": "elixir", "Package.swift": "swift", "pubspec.yaml": "dart",
}
CONTROL_DIRS = {"backend", "frontend", "server", "client", "api", "app", "web", "worker", "workers", "services", "apps", "packages", "src"}
ENTRYPOINT_NAMES = {"main.py", "app.py", "server.py", "wsgi.py", "asgi.py", "main.go", "main.rs", "Program.cs", "index.php", "config.ru", "index.html"}


def _depth(path):
    return len(Path(path).parts)


def _root_for(path):
    p = Path(path).parent
    return "" if str(p) == "." else p.as_posix()


def _under(path, root):
    return not root or path == root or path.startswith(root + "/")


def discover_units(repo):
    """Discover real application units from manifests, never from repository-wide words."""
    units = []
    seen = set()
    for path in repo.files:
        name = Path(path).name
        ecosystem = MANIFESTS.get(name)
        if not ecosystem:
            continue
        root = _root_for(path)
        key = (root, ecosystem, path)
        if key in seen:
            continue
        seen.add(key)
        units.append({"id": root or ".", "root": root, "manifest": path, "manifest_name": name, "ecosystem": ecosystem})

    if not units:
        html = [f for f in repo.files if Path(f).name == "index.html"]
        if html:
            for root in sorted({_root_for(f) for f in html}, key=lambda x: (_depth(x), x)):
                units.append({"id": root or ".", "root": root, "manifest": None, "manifest_name": None, "ecosystem": "static"})
    return sorted(units, key=lambda u: (_depth(u["root"]), u["root"], u["manifest"] or ""))


def files_for_unit(repo, unit, include_nested_units=False):
    root = unit.get("root", "")
    all_units = discover_units(repo)
    nested_roots = {u["root"] for u in all_units if u["root"] and u["root"] != root and _under(u["root"], root)}
    return [f for f in repo.files if _under(f, root) and (include_nested_units or not any(_under(f, n) for n in nested_roots))]


def read_unit_json(repo, unit):
    manifest = unit.get("manifest")
    if not manifest or not manifest.endswith(".json"):
        return {}
    return repo.json(manifest)


def text(repo, unit, suffixes=None, names=None, include_nested_units=False):
    suffixes, names = set(suffixes or ()), set(names or ())
    selected = [f for f in files_for_unit(repo, unit, include_nested_units) if Path(f).suffix.lower() in suffixes or Path(f).name in names]
    return "\n".join(f"--- {f} ---\n{repo.read(f)}" for f in selected)


def import_text(repo, unit, extensions):
    return text(repo, unit, suffixes=extensions)


def _score(repo, unit):
    files = set(files_for_unit(repo, unit)); s = 0
    manifest = unit.get("manifest")
    if manifest: s += 40
    if any(Path(f).name in ENTRYPOINT_NAMES for f in files): s += 25
    if unit.get("root") == "": s += 8
    if Path(unit.get("root") or ".").name in CONTROL_DIRS: s += 8
    if manifest and Path(manifest).name == "package.json":
        pkg = read_unit_json(repo, unit); scripts = pkg.get("scripts") or {}
        if scripts.get("build"): s += 10
        if scripts.get("start") or scripts.get("serve") or scripts.get("dev"): s += 10
        if pkg.get("dependencies") or pkg.get("devDependencies"): s += 3
    if manifest and Path(manifest).name in {"requirements.txt", "pyproject.toml", "Pipfile"}: s += 3
    return s


def select_unit(repo, preferred_root=None):
    """Select a single deployment target only when repository evidence supports it."""
    units = discover_units(repo)
    if not units:
        return None, units, "no_application_unit"
    if preferred_root is not None:
        exact = [u for u in units if u["root"] == preferred_root or u["id"] == preferred_root]
        if len(exact) == 1:
            return exact[0], units, None

    ranked = sorted(((_score(repo, u), u) for u in units), key=lambda x: (-x[0], _depth(x[1]["root"]), x[1]["root"]))
    if len(ranked) > 1:
        top_score, top = ranked[0]
        second_score, second = ranked[1]
        # A close contest between real application units is an ambiguity, not a reason to guess.
        if top["root"] != second["root"] and second_score >= max(50, top_score - 8):
            return None, units, "ambiguous_application_units"
    return ranked[0][1], units, None


def describe(repo):
    units = discover_units(repo)
    selected, _, error = select_unit(repo)
    return {"units": units, "selected_unit": selected, "selection_error": error, "unit_count": len(units)}
