from core.scanner import Repository
from core.engine import Analyzer


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _ambiguous_fixture(tmp_path):
    write(tmp_path, "api/requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "api/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "worker/requirements.txt", "celery\n")
    write(tmp_path, "worker/main.py", "from celery import Celery\napp = Celery('worker')\n")


def test_ambiguous_repo_is_blocked_without_explicit_target(tmp_path):
    _ambiguous_fixture(tmp_path)
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "blocked"
    assert len(result["repository_model"]["units"]) == 2


def test_explicit_target_resolves_the_ambiguity(tmp_path):
    _ambiguous_fixture(tmp_path)
    _, _, result = Analyzer(Repository(tmp_path)).analyze(target="api")
    assert result["deep_analysis"]["status"] == "ready"
    assert result["repository_model"]["selected_unit"]["root"] == "api"
    assert result["summary"]["framework"] == "FastAPI"
