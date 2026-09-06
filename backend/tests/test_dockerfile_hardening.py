"""Pins the fixes made while auditing generated Dockerfiles/compose files against
dockerfile-pre.txt and dockercompose.txt's review checklists: a real pip install bug,
missing dependency-layer caching, missing HEALTHCHECK evidence wiring, and the
previously entirely-absent .dockerignore generation."""
from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile, dockerignore
from core.models import DeploymentSpec


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def spec_for(tmp_path):
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready", result["deep_analysis"]
    return DeploymentSpec(**result["deployment_ir"])


def test_pyproject_toml_install_targets_the_project_directory_not_the_manifest_file(tmp_path):
    # `pip install ./pyproject.toml` is not valid pip syntax (confirmed against real pip:
    # "ERROR: Invalid requirement") - it must install the directory containing the manifest.
    write(tmp_path, "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["flask"]\n\n[build-system]\nrequires = ["setuptools>=61"]\nbuild-backend = "setuptools.build_meta"\n')
    write(tmp_path, "main.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(tmp_path, "README.md", "```bash\ngunicorn main:app --bind 0.0.0.0:8000\n```\n")
    df = dockerfile(spec_for(tmp_path))
    assert "pip install --no-cache-dir ./pyproject.toml" not in df
    assert "pip install --no-cache-dir ." in df


def test_requirements_txt_is_copied_and_installed_before_the_rest_of_the_source(tmp_path):
    write(tmp_path, "requirements.txt", "flask\ngunicorn\n")
    write(tmp_path, "main.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(tmp_path, "README.md", "```bash\ngunicorn main:app --bind 0.0.0.0:8000\n```\n")
    df = dockerfile(spec_for(tmp_path))
    assert df.index("COPY requirements.txt requirements.txt") < df.index("RUN pip install") < df.index("COPY . .")


def test_healthcheck_is_only_emitted_when_a_real_endpoint_was_found(tmp_path):
    write(tmp_path, "requirements.txt", "flask\ngunicorn\n")
    write(tmp_path, "main.py", "from flask import Flask\napp = Flask(__name__)\n@app.route('/healthz')\ndef h(): return 'ok'\n")
    write(tmp_path, "README.md", "```bash\ngunicorn main:app --bind 0.0.0.0:8000\n```\n")
    df = dockerfile(spec_for(tmp_path))
    assert "HEALTHCHECK" in df and "/health" in df


def test_no_healthcheck_is_fabricated_without_endpoint_evidence(tmp_path):
    write(tmp_path, "requirements.txt", "flask\ngunicorn\n")
    write(tmp_path, "main.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(tmp_path, "README.md", "```bash\ngunicorn main:app --bind 0.0.0.0:8000\n```\n")
    df = dockerfile(spec_for(tmp_path))
    assert "HEALTHCHECK" not in df


def test_dockerignore_covers_universal_and_runtime_specific_excludes(tmp_path):
    write(tmp_path, "composer.json", '{"require":{"php":"^8.3"}}')
    write(tmp_path, "public/index.php", "<?php echo 'ok';")
    spec = spec_for(tmp_path)
    out = dockerignore(spec)
    assert ".env" in out and ".git" in out and "vendor" in out
