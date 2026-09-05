from core.scanner import Repository
from core.engine import Analyzer


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_readme_supplies_the_only_start_command_when_entrypoint_is_unconventional(tmp_path):
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "service.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "README.md", """# Run

```bash
uvicorn service:app --host 0.0.0.0 --port 9000
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready"
    assert result["summary"]["start_command"] == "uvicorn service:app --host 0.0.0.0 --port 9000"
    assert result["summary"]["port"] == 9000


def test_readme_dev_only_command_is_never_used_as_a_fallback(tmp_path):
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "service.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "README.md", """# Develop

```bash
uvicorn service:app --reload --port 9000
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "blocked"
    assert any(b["code"] == "ENTRYPOINT" for b in result["deep_analysis"]["blockers"])


def test_readme_contradicting_manifest_command_blocks_generation(tmp_path):
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "README.md", """# Run

```bash
gunicorn main:app --bind 0.0.0.0:8000
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "blocked"
    assert any(b["code"] == "EVIDENCE_RECONCILIATION" for b in result["deep_analysis"]["blockers"])


def test_readme_supplies_ruby_start_command_when_no_rails_or_rack_marker_exists(tmp_path):
    write(tmp_path, "Gemfile", "source 'https://rubygems.org'\ngem 'sinatra'\n")
    write(tmp_path, "app.rb", "require 'sinatra'\nget('/') { 'ok' }\n")
    write(tmp_path, "README.md", """# Run

```bash
bundle exec ruby app.rb -p 4567
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready"
    assert result["summary"]["start_command"] == "bundle exec ruby app.rb -p 4567"


def test_readme_and_source_together_prove_backend_serves_frontend(tmp_path):
    write(tmp_path, "backend/requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "backend/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "frontend/index.html", "<html><body>frontend</body></html>")
    write(tmp_path, "README.md", "The backend serves the frontend's static files at runtime.")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready"
    assert result["repository_model"]["selected_unit"]["root"] == "backend"
