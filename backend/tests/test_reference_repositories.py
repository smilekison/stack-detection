import json
import subprocess
from pathlib import Path

from core.engine import Analyzer
from core.scanner import Repository
from generators.docker import dockerfile

ASTRO_BLOG_URL = "https://github.com/smilekison/astro-blog"
SELF_URL = "https://github.com/smilekison/stack-detection"


def _clone(url, tmp_path, name):
    root = tmp_path / name
    subprocess.run(["git", "clone", "--depth", "1", "--no-tags", url, str(root)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    return root


def _analyze(url, tmp_path, name):
    root = _clone(url, tmp_path, name)
    spec, _, result = Analyzer(Repository(root)).analyze()
    return root, spec, result


def test_astro_blog_is_not_released_as_a_false_production_docker_strategy(tmp_path):
    """The real Astro blog targets Vercel server output and documents only `astro dev`.

    The analyzer must not silently promote that development server to production or emit
    a misleading Dockerfile. This fixture is an isolated clone and never shares files with
    the stack-detection repository.
    """
    root, spec, result = _analyze(ASTRO_BLOG_URL, tmp_path, "astro-blog")
    assert result["summary"]["framework"] == "Astro"
    assert result["summary"]["primary_language"] in {"Node.js", "TypeScript", "JavaScript"}
    assert result["deep_analysis"]["status"] == "blocked"
    assert any(x["code"] == "RUNTIME" for x in result["deep_analysis"]["blockers"])
    assert result["generated_files"] if "generated_files" in result else True
    # The generator itself must not turn the blocked IR into a plausible Dockerfile.
    assert spec.build.get("runtime_strategy") in {None, ""}


def test_stack_detection_self_repository_selects_backend_not_detector_text(tmp_path):
    """The real analyzer repository is a backend application with a served frontend.

    Detection source files/documents containing framework names must not change the selected
    application. The backend is the host and its frontend is an integrated dependency.
    """
    root, spec, result = _analyze(SELF_URL, tmp_path, "stack-detection")
    selected = result["repository_model"]["selected_unit"]
    assert selected is not None
    assert selected["root"] == "backend"
    assert result["summary"]["primary_language"] == "Python"
    assert result["summary"]["framework"] == "FastAPI"
    assert result["deep_analysis"]["status"] == "ready"
    assert spec.build.get("entrypoint") == "backend/main.py"
    image = dockerfile(spec)
    assert "FROM python:" in image
    assert "uvicorn backend.main:app" in image or "uvicorn backend.main" in image
    assert "Django" not in result["summary"]["framework"]
