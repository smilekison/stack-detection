"""Pins core.multi_compose.build(): the auto-wiring behavior that turns N independently-
analyzed repos into one docker-compose.yaml - what a single-repo analysis can never resolve
on its own (which app's env var should point at which other app's service name)."""
from core.scanner import Repository
from core.engine import Analyzer
from core.multi_compose import build as build_multi, slug


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def analyze(tmp_path, role=None):
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready", result["deep_analysis"]
    from core.models import DeploymentSpec
    return {"slug": tmp_path.name, "spec": DeploymentSpec(**result["deployment_ir"]), "repo": Repository(tmp_path), "role": role}


def backend_fixture(root):
    write(root, "requirements.txt", "flask\npsycopg2-binary\ngunicorn\n")
    write(root, "app.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(root, "README.md", "```bash\ngunicorn app:app --bind 0.0.0.0:8000\n```\n")


def frontend_fixture(root, api_url_file=".env"):
    write(root, "package.json", '{"scripts":{"build":"vite build","start":"vite preview --host 0.0.0.0 --port 3000"}}')
    write(root, "index.html", "<html></html>")
    write(root, api_url_file, 'VITE_API_URL="http://localhost:8000/api"\n')


def test_frontend_url_var_is_wired_to_the_auto_detected_backend_as_a_build_arg(tmp_path):
    backend_dir = tmp_path / "backend"; backend_dir.mkdir(); backend_fixture(backend_dir)
    frontend_dir = tmp_path / "frontend"; frontend_dir.mkdir(); frontend_fixture(frontend_dir)
    backend = analyze(backend_dir); frontend = analyze(frontend_dir)
    dockerfiles, compose_yaml, notes = build_multi([backend, frontend])
    assert not notes
    # backend has no shared data service declared here (sqlite/none), so no depends_on is
    # forced onto it, but the frontend's build arg must be wired to its compose service name.
    assert "VITE_API_URL: http://backend:8000/api" in compose_yaml
    assert "args:" in compose_yaml
    assert "ARG VITE_API_URL" in dockerfiles["frontend"]
    assert "ENV VITE_API_URL=$VITE_API_URL" in dockerfiles["frontend"]
    assert dockerfiles["frontend"].index("ARG VITE_API_URL") < dockerfiles["frontend"].index("RUN npm run build")


def test_ambiguous_backend_skips_wiring_and_reports_a_note(tmp_path):
    a_dir = tmp_path / "svc-a"; a_dir.mkdir(); backend_fixture(a_dir)
    write(a_dir, "requirements.txt", "flask\npsycopg2-binary\ngunicorn\nredis\n")
    b_dir = tmp_path / "svc-b"; b_dir.mkdir(); backend_fixture(b_dir)
    write(b_dir, "requirements.txt", "flask\npsycopg2-binary\ngunicorn\n")
    a = analyze(a_dir); b = analyze(b_dir)
    dockerfiles, compose_yaml, notes = build_multi([a, b])
    assert any("ambiguous" in n for n in notes)


def test_explicit_backend_role_resolves_ambiguity(tmp_path):
    a_dir = tmp_path / "svc-a"; a_dir.mkdir(); backend_fixture(a_dir)
    write(a_dir, "requirements.txt", "flask\npsycopg2-binary\ngunicorn\nredis\n")
    b_dir = tmp_path / "svc-b"; b_dir.mkdir(); frontend_fixture(b_dir)
    a = analyze(a_dir, role="backend"); b = analyze(b_dir)
    dockerfiles, compose_yaml, notes = build_multi([a, b])
    assert f'http://svc-a:8000/api' in compose_yaml


def test_shared_service_gets_a_compose_block_and_healthy_depends_on(tmp_path):
    backend_dir = tmp_path / "backend"; backend_dir.mkdir()
    write(backend_dir, "requirements.txt", "flask\npsycopg2-binary\ngunicorn\n")
    write(backend_dir, "app.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(backend_dir, "README.md", "```bash\ngunicorn app:app --bind 0.0.0.0:8000\n```\n")
    frontend_dir = tmp_path / "frontend"; frontend_dir.mkdir(); frontend_fixture(frontend_dir)
    backend = analyze(backend_dir); frontend = analyze(frontend_dir)
    dockerfiles, compose_yaml, notes = build_multi([backend, frontend])
    assert "postgres:" in compose_yaml and "image: postgres:17" in compose_yaml
    assert "      postgres:\n        condition: service_healthy" in compose_yaml


def test_slug_derives_a_clean_compose_service_name_from_a_repo_url():
    assert slug("https://github.com/bradtraversy/friendly-dev-backend") == "friendly-dev-backend"
    assert slug("https://github.com/bradtraversy/friendly-dev-backend.git") == "friendly-dev-backend"
