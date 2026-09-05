"""Repository-level application boundaries and evidence scoping."""
from pathlib import Path
from .technology_catalog import ecosystem_for_manifest

CONTROL_DIRS={"backend","frontend","server","client","api","app","web","worker","workers","services","apps","packages","src"}
ENTRYPOINT_NAMES={"main.py","app.py","server.py","wsgi.py","asgi.py","main.go","main.rs","Program.cs","index.php","config.ru","index.html","Application.java","Main.java"}
NON_RUNTIME_DIRS={"tests","test","__tests__","docs","doc","examples","example","fixtures","mocks","mock","benchmarks","benchmark","samples","sample"}
NON_RUNTIME_NAMES={"readme.md","readme.rst","changelog.md","license","license.md"}
SERVING_MARKERS=(
    "StaticFiles", "FileResponse", "send_from_directory", "sendFile", "express.static",
    "static_folder", "staticfiles", "serve-static", "WhiteNoise", "mount(", "app.mount(",
)


def _depth(path): return len(Path(path).parts)
def _root_for(path):
    p=Path(path).parent
    return "" if str(p)=="." else p.as_posix()
def _under(path,root): return not root or path==root or path.startswith(root+"/")
def _is_runtime_file(path):
    parts=Path(path).parts
    return not any(p.lower() in NON_RUNTIME_DIRS for p in parts[:-1]) and Path(path).name.lower() not in NON_RUNTIME_NAMES


def discover_units(repo):
    """Discover one application unit per directory, including manifest-less static sites."""
    grouped={}
    for path in repo.files:
        eco=ecosystem_for_manifest(path)
        if eco: grouped.setdefault(_root_for(path),[]).append(path)
    units=[]
    for root,manifests in grouped.items():
        manifests=sorted(manifests,key=lambda p:(_depth(p),p)); ecosystems=sorted({ecosystem_for_manifest(p) for p in manifests if ecosystem_for_manifest(p)})
        units.append({"id":root or ".","root":root,"manifest":manifests[0],"manifests":manifests,"manifest_name":Path(manifests[0]).name,"ecosystem":ecosystems[0] if len(ecosystems)==1 else "polyglot","ecosystems":ecosystems})
    manifest_roots=[u["root"] for u in units]
    html_roots=sorted({_root_for(f) for f in repo.files if Path(f).name=="index.html" and _is_runtime_file(f)},key=lambda x:(_depth(x),x))
    for root in html_roots:
        # A static site becomes a separate unit unless the HTML is part of an existing
        # application root. This makes backend/frontend repositories explicitly ambiguous.
        if any(_under(root,m) or _under(m,root) for m in manifest_roots if m): continue
        units.append({"id":root or ".","root":root,"manifest":None,"manifests":[],"manifest_name":None,"ecosystem":"static","ecosystems":["static"]})
    return sorted(units,key=lambda u:(_depth(u["root"]),u["root"],u["manifest"] or ""))


def files_for_unit(repo,unit,include_nested_units=False,include_non_runtime=False):
    root=unit.get("root",""); all_units=discover_units(repo); nested={u["root"] for u in all_units if u["root"] and u["root"]!=root and _under(u["root"],root)}; out=[]
    for f in repo.files:
        if not _under(f,root): continue
        if not include_nested_units and any(_under(f,n) for n in nested): continue
        if not include_non_runtime and not _is_runtime_file(f): continue
        out.append(f)
    for m in unit.get("manifests",[]):
        if m not in out: out.append(m)
    return sorted(set(out))


def read_unit_json(repo,unit):
    m=unit.get("manifest")
    return repo.json(m) if m and m.endswith(".json") else {}


def text(repo,unit,suffixes=None,names=None,include_nested_units=False,include_non_runtime=False):
    suffixes,names=set(suffixes or ()),set(names or ()); selected=[f for f in files_for_unit(repo,unit,include_nested_units,include_non_runtime) if Path(f).suffix.lower() in suffixes or Path(f).name in names]
    return "\n".join(f"--- {f} ---\n{repo.read(f)}" for f in selected)


def import_text(repo,unit,extensions): return text(repo,unit,suffixes=extensions)


def _score(repo,unit):
    files=set(files_for_unit(repo,unit)); s=40 if unit.get("manifest") else 30
    is_root=unit.get("root")==""; is_control_dir=Path(unit.get("root") or ".").name in CONTROL_DIRS
    has_entrypoint=any(Path(f).name in ENTRYPOINT_NAMES for f in files)
    # A manifest-holding unit gets the entrypoint bonus unconditionally - a real second
    # signal on top of the manifest. A manifest-less (static) unit only gets it when it's
    # also at the repository root or in a conventionally-named app directory: a bare
    # index.html sitting in an arbitrarily-named nested folder (a theme/asset/reference
    # directory, say) is not meaningfully stronger evidence than the fact that already
    # made it a candidate unit in the first place, and must not outscore an actual
    # manifest-backed application root purely on that single, already-counted signal.
    if has_entrypoint and (unit.get("manifest") or is_root or is_control_dir): s+=25
    if is_root: s+=8
    if is_control_dir: s+=8
    if len(unit.get("ecosystems",[]))==1: s+=5
    return s


SERVING_VERBS=("serve","serves","served","serving","mount","mounted","static","embed","embedded")


def _readme_serving_evidence(repo,dependency):
    """A second, equally-valid proof path: the root README documents the relationship.

    Source markers are Tier 3 evidence; README is Tier 2 and PROGRAM.md requires it be
    treated as first-class. Either proof is sufficient - this is the general "README +
    source prove A serves B" rule, not a special case for one repository.
    """
    root=dependency.get("root") or ""
    if not root: return []
    name=Path(root).name
    for f in repo.files:
        parent=Path(f).parent.as_posix()
        if parent not in (".",""): continue
        if Path(f).name.lower() not in NON_RUNTIME_NAMES: continue
        for line in repo.read(f).lower().splitlines():
            if (root.lower() in line or name.lower() in line) and any(v in line for v in SERVING_VERBS):
                return [f"{f}: README documents {name} being served by the host application"]
    return []


def _integration_evidence(repo,host,dependency):
    """Return concrete evidence that a host application serves another unit.

    A sibling application is not suppressed merely because it is called frontend/api/etc.
    We require both a reference to the dependency unit path and a serving mechanism. This
    lets an application such as a FastAPI backend that serves a static frontend be selected
    as one deployable unit, while unrelated backend/frontend monorepos remain ambiguous.
    """
    root=dependency.get("root") or ""
    if not root: return []
    source=text(repo,host,suffixes={
        ".py",".js",".jsx",".ts",".tsx",".go",".rs",".java",".kt",".scala",
        ".cs",".fs",".vb",".php",".rb",".ex",".exs"
    })
    if source:
        normalized=source.replace("\\","/")
        root_token=root.replace("\\","/")
        if root_token in normalized or Path(root_token).name in normalized:
            marker_hits=[m for m in SERVING_MARKERS if m.lower() in normalized.lower()]
            if marker_hits: return [f"{root_token}: referenced by host application"]+marker_hits[:3]
    return _readme_serving_evidence(repo,dependency)


def _integrated_dependencies(repo,host,units):
    evidence=[]
    for dependency in units:
        if dependency is host or dependency.get("root")==host.get("root"): continue
        hits=_integration_evidence(repo,host,dependency)
        if hits: evidence.append({"unit":dependency,"evidence":hits})
    return evidence


def select_unit(repo,preferred_root=None):
    """Select a target only when evidence supports it; never silently choose a close rival."""
    units=discover_units(repo)
    if not units: return None,units,"no_application_unit"
    if preferred_root is not None:
        exact=[u for u in units if u["root"]==preferred_root or u["id"]==preferred_root]
        if len(exact)==1: return exact[0],units,None
    ranked=sorted(((_score(repo,u),u) for u in units),key=lambda x:(-x[0],_depth(x[1]["root"]),x[1]["root"]))
    if len(ranked)>1:
        top_score,top=ranked[0]; second_score,second=ranked[1]
        integrated=_integrated_dependencies(repo,top,units)
        integrated_roots={x["unit"].get("root") for x in integrated}
        # A concrete host->dependency serving relationship makes the host the deployable
        # boundary. The dependency remains inventoried, but it is not treated as a rival
        # deployment target because the host is provably responsible for serving it.
        if second.get("root") in integrated_roots:
            return top,units,None
        # Any second real application within 15 points of the best candidate is a
        # deployment-target ambiguity. A higher score must not become permission to guess.
        if top["root"]!=second["root"] and second_score>=max(60,top_score-15): return None,units,"ambiguous_application_units"
    return ranked[0][1],units,None


def describe(repo):
    units=discover_units(repo); selected,_,error=select_unit(repo)
    return {"units":units,"selected_unit":selected,"selection_error":error,"unit_count":len(units)}
