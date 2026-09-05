"""Compatibility entry point for the authoritative deployment analysis."""
from pathlib import Path
from .deployment_analysis_v2 import analyze as _analyze
from .repository_scope import select_unit, files_for_unit


def _blocked_target(spec, result, units, reason):
    spec.frameworks=[]
    spec.languages=[]
    spec.package_managers=[]
    spec.runtime={"name":"Unknown","version":"Not resolved"}
    spec.build.update({"runtime_strategy":None,"container_command":""})
    spec.processes[0]["start_command"]="Not resolved" if spec.processes else None
    spec.network["port"]=None
    spec.network["health_endpoint"]=None
    spec.services=[]
    result["repository_model"]={"units":units,"selected_unit":None,"selection_error":reason}
    result["languages"]=[]
    result["frameworks"]=[]
    result["summary"].update({"primary_language":"Unknown","runtime":"Unknown","runtime_version":"Not resolved","framework":"Unknown","package_manager":"Unknown","start_command":"Not resolved","port":None,"health_endpoint":None,"services":[]})
    deep={"status":"blocked","confidence":0,"checks":[{"code":"APPLICATION_BOUNDARY","title":"Application target selection","status":"blocker","evidence":[],"detail":"No unique application target was selected; generation is blocked rather than guessed."}],"warnings":[],"blockers":[{"code":"APPLICATION_BOUNDARY","title":"Application target selection","status":"blocker","evidence":[],"detail":"No unique application target was selected; generation is blocked rather than guessed."}],"decisions":[],"script_inventory":{}}
    result["deep_analysis"]=deep
    spec.project.update({"application_units":units,"deep_analysis_status":"blocked","deep_analysis_confidence":0,"container_decisions":[]})
    return deep


def analyze(repo, spec, result):
    selected, units, selection_error = select_unit(repo)
    if selection_error:
        return _blocked_target(spec, result, units, selection_error)

    # Static sites have no package manifest by design. Handle them before the
    # manifest-driven strategy engine, while still using the same application boundary.
    if selected and selected.get("ecosystem") == "static":
        files = files_for_unit(repo, selected)
        html = [f for f in files if Path(f).name == "index.html"]
        if html:
            root = selected.get("root") or "."
            spec.project.update({"application_units":units,"selected_application":selected,"application_root":root,"technology_profile":[["Static HTML",len(html)]]})
            spec.runtime={"name":"Static Web","version":"nginx-unprivileged"}
            spec.languages=[{"name":"HTML/CSS/JS","score":95,"confidence":95.0}]
            spec.frameworks=[]; spec.package_managers=[]
            spec.build.update({"runtime_strategy":"static-nginx","output":root,"project_dir":root})
            spec.processes[0]["start_command"]='nginx -g "daemon off;"'
            spec.network.update({"port":8080,"health_endpoint":None})
            result["repository_model"]={"units":units,"selected_unit":selected,"selection_error":None}
            result["summary"].update({"primary_language":"HTML/CSS/JS","runtime":"Static Web","runtime_version":"nginx-unprivileged","framework":"None","package_manager":"None","start_command":spec.processes[0]["start_command"],"port":8080,"health_endpoint":None,"services":[]})
            result["languages"]=spec.languages; result["frameworks"]=[]
            deep={"status":"ready","confidence":98,"checks":[{"code":"APPLICATION_BOUNDARY","title":"Application boundary","status":"pass","evidence":html,"detail":f"Static application root: {root}."},{"code":"RUNTIME","title":"Static web runtime","status":"pass","evidence":html,"detail":"nginx unprivileged static serving strategy."}],"warnings":[],"blockers":[],"decisions":[{"strategy":"static-nginx","application_root":root}],"script_inventory":{},"technology_profile":[["Static HTML",len(html)]]}
            result["deep_analysis"]=deep
            spec.project.update({"deep_analysis_status":"ready","deep_analysis_confidence":98,"container_decisions":deep["decisions"]})
            return deep
    return _analyze(repo, spec, result)

__all__=["analyze"]
