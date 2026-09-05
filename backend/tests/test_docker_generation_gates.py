import pytest
from core.models import DeploymentSpec
from generators.docker import dockerfile


def base_spec(**project):
    spec=DeploymentSpec(project={"deep_analysis_status":"ready", **project},runtime={"name":"Python","version":"3.12"},network={"port":8000},processes=[{"role":"web","start_command":"uvicorn main:app --host 0.0.0.0 --port 8000"}],build={"runtime_strategy":"python-uvicorn","dependency_manifest":"requirements.txt"})
    return spec


def test_docker_generation_requires_ready_analysis():
    spec=base_spec(deep_analysis_status="blocked")
    with pytest.raises(ValueError): dockerfile(spec)


def test_python_generation_uses_resolved_version_and_manifest():
    spec=base_spec(files=["requirements.txt"],dependency_manifest="requirements.txt")
    image=dockerfile(spec)
    assert "FROM python:3.12-slim" in image
    assert "pip install --no-cache-dir -r requirements.txt" in image
    assert "uvicorn main:app" in image


def test_unknown_runtime_version_never_gets_a_silent_default():
    spec=base_spec(runtime={"name":"Python","version":"Not resolved"})
    with pytest.raises(ValueError): dockerfile(spec)
