"""Pins docker-compose generation: service wiring (beyond the original postgres/redis-only
coverage) and .env.example-driven env_file wiring, so an app that needs a database or its
own declared env vars doesn't silently 500 the way Strapi/Rails/Laravel did before their
requirements were surfaced (PRs #7-#9)."""
from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import compose


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def analyze(tmp_path):
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    return result


def test_compose_wires_a_newly_covered_service_with_depends_on_and_credentials(tmp_path):
    write(tmp_path, "requirements.txt", "flask\nmotor\n")
    write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef h(): return 'ok'\n")
    result = analyze(tmp_path)
    assert result["deep_analysis"]["status"] == "ready"
    from core.models import DeploymentSpec
    spec = DeploymentSpec(**{**result["deployment_ir"]})
    out = compose(spec)
    assert "mongodb:" in out and "image: mongo:7" in out
    assert "MONGO_INITDB_ROOT_PASSWORD: ${MONGO_INITDB_ROOT_PASSWORD:?required}" in out
    assert "    depends_on:\n      mongodb:\n        condition: service_healthy" in out
    assert '"db.adminCommand(\'ping\')"' in out and "restart: unless-stopped" in out


def test_compose_wires_env_file_from_a_declared_env_example(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef h(): return 'ok'\n")
    write(tmp_path, ".env.example", "SECRET_KEY=changeme\nDEBUG=false\n")
    result = analyze(tmp_path)
    from core.models import DeploymentSpec
    spec = DeploymentSpec(**{**result["deployment_ir"]})
    out = compose(spec)
    assert "env_file:\n      - .env  # copy from .env.example" in out


def test_compose_omits_service_blocks_when_none_are_detected(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef h(): return 'ok'\n")
    result = analyze(tmp_path)
    from core.models import DeploymentSpec
    spec = DeploymentSpec(**{**result["deployment_ir"]})
    out = compose(spec)
    assert "depends_on" not in out and "env_file" not in out and "volumes:" not in out
