"""Live integration smoke tests for the two reference repositories.

Run explicitly in CI with Docker. Each reference repository gets its own clone and
container; neither checkout is ever used as a shared workspace for the other.
"""
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from core.engine import Analyzer
from core.scanner import Repository
from generators.docker import dockerfile

CASES = (
    ("astro-blog", "https://github.com/smilekison/astro-blog", False, None),
    ("stack-detection", "https://github.com/smilekison/stack-detection", True, 8000),
)


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)


def clone(url, destination):
    result = run(["git", "clone", "--depth", "1", "--no-tags", url, str(destination)])
    if result.returncode:
        raise AssertionError(result.stdout)


def wait_http(port, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                return response.status
        except Exception:
            time.sleep(1)
    raise AssertionError(f"container did not answer on port {port}")


def check_case(root, should_generate, expected_port):
    spec, _, result = Analyzer(Repository(root)).analyze()
    assert result["repository_model"]["selected_unit"] is not None
    if not should_generate:
        assert result["deep_analysis"]["status"] == "blocked"
        assert any(b["code"] in {"RUNTIME", "RUNTIME_VERSION"} for b in result["deep_analysis"]["blockers"])
        assert spec.build.get("runtime_strategy") is None
        return

    assert result["deep_analysis"]["status"] == "ready"
    assert spec.network["port"] == expected_port
    image = dockerfile(spec)
    (root / "Dockerfile.generated").write_text(image)
    tag = f"reference-{root.name}-{os_getpid()}:smoke"
    build = run(["docker", "build", "--pull", "--no-cache", "-f", "Dockerfile.generated", "-t", tag, "."], cwd=root)
    if build.returncode:
        raise AssertionError(build.stdout)
    run_result = run(["docker", "run", "-d", "--rm", "-p", f"127.0.0.1::${expected_port}", tag], cwd=root)
    if run_result.returncode:
        raise AssertionError(run_result.stdout)
    cid = run_result.stdout.strip()
    try:
        mapping = run(["docker", "port", cid, str(expected_port)])
        if mapping.returncode:
            raise AssertionError(mapping.stdout)
        host_port = int(mapping.stdout.rsplit(":", 1)[1].strip())
        assert 200 <= wait_http(host_port) < 500
    finally:
        subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def os_getpid():
    import os
    return os.getpid()


def main():
    with tempfile.TemporaryDirectory(prefix="reference-smoke-") as temp:
        root = Path(temp)
        for name, url, should_generate, port in CASES:
            case_root = root / name
            clone(url, case_root)
            check_case(case_root, should_generate, port)
            print(f"{name}: PASS", flush=True)


if __name__ == "__main__":
    main()
