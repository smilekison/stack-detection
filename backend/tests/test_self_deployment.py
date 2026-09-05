from pathlib import Path

from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile


def test_stack_detection_can_analyze_and_generate_for_its_own_layout(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "requirements.txt").write_text("fastapi==0.116.1\nuvicorn[standard]==0.35.0\n")
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\nfrom fastapi.responses import FileResponse\n\n"
        "FRONTEND = 'frontend'\napp = FastAPI()\n\n"
        "@app.get('/health')\ndef health(): return {'status': 'ok'}\n\n"
        "@app.get('/')\ndef home(): return FileResponse(FRONTEND + '/index.html')\n"
    )
    (tmp_path / "frontend" / "index.html").parent.mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")

    repo = Repository(tmp_path)
    spec, _, result = Analyzer(repo).analyze()
    deep = result["deep_analysis"]

    assert deep["status"] == "ready"
    assert result["summary"]["framework"] == "FastAPI"
    assert spec.build["dependency_manifest"] == "backend/requirements.txt"
    assert spec.build["entrypoint"] == "backend/main.py"
    assert spec.build["runtime_strategy"] == "python-uvicorn"
    # The module name is relative to the application root (backend/), not the repo root:
    # `uvicorn backend.main:app` run from the repo root would crash on `main.py`'s own
    # `from core.scanner import ...`-style imports, which are written relative to backend/
    # itself (verified with a real Docker build+run - see PR history for the traceback).
    assert "uvicorn main:app" in spec.processes[0]["start_command"]

    generated = dockerfile(spec)
    assert "COPY . ." in generated
    assert "pip install --no-cache-dir -r backend/requirements.txt" in generated
    assert "cd backend && uvicorn main:app" in generated
    assert "EXPOSE 8000" in generated
    assert "USER 10001" in generated
