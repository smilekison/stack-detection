from core.scanner import Repository
from core.engine import Analyzer
from core.repository_scope import discover_units, select_unit


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_detector_source_cannot_create_framework_evidence(tmp_path):
    write(tmp_path, "backend/requirements.txt", "fastapi==0.116.1\nuvicorn==0.35.0\n")
    write(tmp_path, "backend/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "backend/core/engine.py", "FRAMEWORKS = [('Django','django'),('Flask','flask')]\n")
    write(tmp_path, "docs/README.md", "Django Flask FastAPI Next.js Express")

    repo = Repository(tmp_path)
    spec, _, result = Analyzer(repo).analyze()

    assert result["summary"]["framework"] == "FastAPI"
    assert result["repository_model"]["selected_unit"]["root"] == "backend"
    assert result["deep_analysis"]["status"] == "ready"
    assert spec.build["entrypoint"] == "backend/main.py"


def test_multiple_real_application_units_are_not_guessed(tmp_path):
    write(tmp_path, "api/requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "api/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "worker/requirements.txt", "celery\n")
    write(tmp_path, "worker/main.py", "from celery import Celery\napp = Celery('worker')\n")

    repo = Repository(tmp_path)
    selected, units, error = select_unit(repo)
    assert len(units) == 2
    assert selected is None
    assert error == "ambiguous_application_units"

    _, _, result = Analyzer(repo).analyze()
    assert result["deep_analysis"]["status"] == "blocked"
    assert any(x["code"] == "APPLICATION_BOUNDARY" for x in result["deep_analysis"]["blockers"])


def test_application_units_are_manifest_based(tmp_path):
    write(tmp_path, "backend/requirements.txt", "fastapi\n")
    write(tmp_path, "frontend/index.html", "<html></html>")
    units = discover_units(Repository(tmp_path))
    assert len(units) == 2
    backend = next(x for x in units if x["root"] == "backend")
    frontend = next(x for x in units if x["root"] == "frontend")
    assert backend["manifest"] == "backend/requirements.txt"
    assert backend["manifests"] == ["backend/requirements.txt"]
    assert backend["ecosystem"] == "python"
    assert backend["ecosystems"] == ["python"]
    assert frontend["ecosystem"] == "static"


def test_polyglot_manifests_in_one_root_are_one_unit(tmp_path):
    write(tmp_path, "package.json", '{"scripts":{"build":"vite build"}}')
    write(tmp_path, "pyproject.toml", '[project]\nname="tooling"\n')
    units = discover_units(Repository(tmp_path))
    assert len(units) == 1
    assert units[0]["ecosystem"] == "polyglot"
    assert set(units[0]["ecosystems"]) == {"node", "python"}


def test_technology_mentions_in_docs_and_tests_do_not_define_project_stack(tmp_path):
    write(tmp_path, "package.json", '{"dependencies":{"express":"5.0.0"},"scripts":{"start":"node server.js"}}')
    write(tmp_path, "server.js", "const express = require('express');\nconst app = express();\napp.listen(process.env.PORT || 3000);\n")
    write(tmp_path, "docs/architecture.md", "This example compares Django, Rails, Laravel, Spring Boot and FastAPI.")
    write(tmp_path, "tests/framework-fixture.js", "const fake = 'django flask rails laravel spring';\n")
    write(tmp_path, "src/notes.txt", "Next.js and Astro are alternatives.")

    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["summary"]["framework"] == "Express"
    assert result["frameworks"][0]["name"] == "Express"
    assert result["deep_analysis"]["technology_profile"][0][0] == "JavaScript"


def test_backend_and_static_frontend_are_not_silently_merged(tmp_path):
    write(tmp_path, "backend/requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "backend/main.py", "from fastapi import FastAPI\napp=FastAPI()\n")
    write(tmp_path, "frontend/index.html", "<html><body>frontend</body></html>")
    selected, units, error = select_unit(Repository(tmp_path))
    assert len(units) == 2
    assert selected is None
    assert error == "ambiguous_application_units"
