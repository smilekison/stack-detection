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


def test_astro_blog_blocks_unsupported_vercel_server_runtime(tmp_path):
    root, spec, result = _analyze(ASTRO_BLOG_URL, tmp_path, "astro-blog")
    assert root.exists()
    assert result["summary"]["framework"] == "Astro"
    assert result["summary"]["primary_language"] in {"Node.js", "TypeScript", "JavaScript"}
    assert result["deep_analysis"]["status"] == "blocked"
    assert any(x["code"] == "RUNTIME" for x in result["deep_analysis"]["blockers"])
    assert spec.build.get("runtime_strategy") is None


def test_stack_detection_selects_backend_as_composite_application(tmp_path):
    root, spec, result = _analyze(SELF_URL, tmp_path, "stack-detection")
    assert root.exists()
    selected = result["repository_model"]["selected_unit"]
    assert selected is not None
    assert selected["root"] == "backend"
    assert result["summary"]["primary_language"] == "Python"
    assert result["summary"]["framework"] == "FastAPI"
    assert result["deep_analysis"]["status"] == "ready"
    assert spec.build.get("entrypoint") == "backend/main.py"
    image = dockerfile(spec)
    assert "FROM python:" in image
    assert "uvicorn backend.main:app" in image
