from core.scanner import Repository
from core.engine import Analyzer


def test_self_layout_accepts_runtime_from_existing_dockerfile_and_serves_frontend(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "requirements.txt").write_text("fastapi==0.116.1\nuvicorn[standard]==0.35.0\n")
    (backend / "Dockerfile").write_text("FROM python:3.12-slim\nWORKDIR /app\n")
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\nfrom fastapi.responses import FileResponse\n"
        "FRONTEND='frontend'\napp=FastAPI()\n"
        "@app.get('/health')\ndef health(): return {'status':'ok'}\n"
        "@app.get('/')\ndef home(): return FileResponse(FRONTEND+'/index.html')\n"
    )
    (tmp_path / "frontend" / "index.html").parent.mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["repository_model"]["selected_unit"]["root"] == "backend"
    assert result["summary"]["primary_language"] == "Python"
    assert result["summary"]["framework"] == "FastAPI"
    assert result["summary"]["runtime_version"] == "3.12"
    assert result["summary"]["start_command"].startswith("uvicorn backend.main:app")
    assert result["deep_analysis"]["status"] == "ready"
