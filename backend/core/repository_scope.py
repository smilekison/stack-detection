"""Repository-level application boundaries and evidence scoping.

The detector must reason about application units before framework/runtime detection. A unit is
identified by its own manifest and directory; documentation, tests, detector source and other
applications cannot become framework evidence merely because they contain matching words.
"""
from pathlib import Path

MANIFESTS = {
    "package.json": "node", "pyproject.toml": "python", "requirements.txt": "python", "Pipfile": "python",
    "go.mod": "go", "Cargo.toml": "rust", "pom.xml": "jvm", "build.gradle": "jvm", "build.gradle.kts": "jvm",
    "composer.json": "php", "Gemfile": "ruby", "mix.exs": "elixir", "Package.swift": "swift", "pubspec.yaml": "dart",
}
MANIFEST_PRIORITY = {"pyproject.toml": 50, "Pipfile": 40, "requirements.txt": 30, "package.json": 50, "go.mod": 50, "Cargo.toml": 50, "pom.xml": 40, "build.gradle": 40, "build.gradle.kts": 40, "composer.json": 50, "Gemfile": 50, "mix.exs": 50, "Package.swift": 50, "pubspec.yaml": 50}
CONTROL_DIRS = {"backend", "frontend", "server", "client", "api", "app", "web", "worker", "workers", "services", "apps", "packages", "src"}
ENTRYPOINT_NAMES = {"main.py", "app.py", "server.py", "wsgi.py", "asgi.py", "main.go", "main.rs", "Program.cs", "index.php", "config.ru", "index.html"}
NON_RUNTIME_DIRS = {"tests", "test", "__tests__", "docs", "doc", "examples", "example", "fixtures", "mocks", "mock", "benchmarks", "benchmark"}
NON_RUNTIME_NAMES = {"readme.md", "readme.rst", "changelog.md", "license", "license.md"}


def _depth(path):
    return len(Path(path).parts)


def _root_for(path):
    p = Path(path).parent
    return "" if str(p) == "." else p.as_posix()


def _under(path, root):
    return not root or path == root or path.startswith(root + "/")


def discover_units(repo):
    """Discover one normalized application unit per directory/ecosystem."""
    grouped = {}
    for path in repo.files:
        name = Path(path).name
        ecosystem = MANIFESTS.get(name)
        if not ecosystem:
            continue
        root = _root_for(path)
        key = (root, ecosystem)
        grouped.setdefault(key, []).append(path)

    units = []
    for (root, ecosystem), manifests in grouped.items():
        manifests = sorted(manifests, key=lambda p: (-MANIFEST_PRIORITY.get(Path(p).name, 0), _depth(p), p))
        canonical = manifests[0]
        units.append({
            "id": root or ".", "root": root, "manifest": canonical, "manifests": manifests,
            "manifest_name": Path(canonical).name, "ecosystem": ecosystem,
        })

    if not units:
        html = [f for f in repo.files if Path(f).name == "index.html" and not any(p.lower() in NON_RUNTIME_DIRS for p in Path(f).parts[:-1])]
        for root in sorted({_root_for(f) for f in html}, key=lambda x: (_depth(x), x)):
            units.append({"id": root or ".", "root": root, "manifest": None, "manifests": [], "manifest_name": None, "ecosystem": "static"})
    return sorted(units, key=lambda u: (_depth(u["root"]), u["root"], u["manifest"] or ""))


def files_for_unit(repo, unit, include_nested_units=False, include_non_runtime=False):
    root = unit.get("root", "")
    all_units = discover_units(repo)
    nested_roots = {u["root"] for u in all_units if u["root"] and u["root"] != root and _under(u["root"], root)}
    out = []
    for f in repo.files:
        if not _under(f, root):
            continue
        if not include_nested_units and any(_under(f, n) for n in nested_roots):
            continue
        if not include_non_runtime:
            parts = Path(f).parts
            if any(p.lower() in NON_RUNTIME_DIRS for p in parts[:-1]) or Path(f).name.lower() in NON_RUNTIME_NAMES:
                continue
        out.append(f)
    for manifest in unit.get("manifests", []):
        if manifest not in out:
            out.append(manifest)
    return sorted(set(out))


def read_unit_json(repo, unit):
    manifest = unit.get("manifest")
    if not manifest or not manifest.endswith(".json"):
        return {}
    return repo.json(manifest)


def text(repo, unit, suffixes=None, names=None, include_nested_units=False, include_non_runtime=False):
    suffixes, names = set(suffixes or ()), set(names or ())
    selected = [f for f in files_for_unit(repo, unit, include_nested_units, include_non_runtime) if Path(f).suffix.lower() in suffixes or Path(f).name in names]
    return "\n".join(f"--- {f} ---\n{repo.read(f)}" for f in selected)


def import_text(repo, unit, extensions):
    return text(repo, unit, suffixes=extensions)


def _score(repo, unit):
    files = set(files_for_unit(repo, unit)); s = 0
    if unit.get("manifest"): s += 40
    if any(Path(f).name in ENTRYPOINT_NAMES for f in files): s += 25
    if unit.get("root") == "": s += 8
    if Path(unit.get("root") or ".").name in CONTROL_DIRS: s += 8
    if unit.get("manifest") and Path(unit["manifest"]).name == "package.json":
        pkg = read_unit_json(repo, unit); scripts = pkg.get("scripts") or {}
        if scripts.get("build"): s += 10
        if scripts.get("start") or scripts.get("serve") or scripts.get("dev"): s += 10
        if pkg.get("dependencies") or pkg.get("devDependencies"): s += 3
    if len(unit.get("manifests", [])) > 1: s += 2
    return s


def select_unit(repo, preferred_root=None):
    """Select one deployment target only when repository evidence supports it."""
    units = discover_units(repo)
    if not units:
        return None, units, "no_application_unit"
    if preferred_root is not None:
        exact = [u for u in units if u["root"] == preferred_root or u["id"] == preferred_root]
        if len(exact) == 1:
            return exact[0], units, None
    ranked = sorted(((_score(repo, u), u) for u in units), key=lambda x: (-x[0], _depth(x[1]["root"]), x[1]["root"]))
    if len(ranked) > 1:
        top_score, top = ranked[0]; second_score, second = ranked[1]
        if top["root"] != second["root"] and second_score >= max(50, top_score - 8):
            return None, units, "ambiguous_application_units"
    return ranked[0][1], units, None


def describe(repo):
    units = discover_units(repo); selected, _, error = select_unit(repo)
    return {"units": units, "selected_unit": selected, "selection_error": error, "unit_count": len(units)}
