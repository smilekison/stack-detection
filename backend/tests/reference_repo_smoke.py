"""Live verification helper for the two reference repositories.
Run this only in an environment with network access and Docker.
Each repository is cloned into its own temporary directory and verified independently.
"""
import os
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

def run(command, cwd):
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)

def clone(url, destination):
    result = run(["git", "clone", "--depth", "1", "--no-tags", url, str(destination)], destination.parent)
    if result.returncode:
        raise AssertionError(result.stdout)

def wait_health(host_port, timeout=60):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{host_port}/health", timeout=3) as response:
                return response.status
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise AssertionError(f"health endpoint did not respond: {last}")

def verify(root, expect_ready, expected_port):
    spec, _, result = Analyzer(Repository(root)).analyze()
    assert result["repository_model"]["selected_unit"] is not None
    if not expect_ready:
        assert result["deep_analysis"]["status"] == "blocked"
        assert any(b["code"] in {"RUNTIME", "RUNTIME_VERSION"} for b in result["deep_analysis"]["blockers"])
        assert spec.build.get("runtime_strategy") is None
        return
    assert result["deep_analysis"]["status"] == "ready"
    assert spec.network["port"] == expected_port
    generated = dockerfile(spec)
    generated_path = root / "Dockerfile.generated"
    generated_path.write_text(generated)
    tag = f"stack-detection-reference-{os.getpid()}:verify"
    build = run(["docker", "build", "--pull", "--no-cache", "-f", str(generated_path.name), "-t", tag, "."], root)
    if build.returncode:
        raise AssertionError(build.stdout)
    started = run(["docker", "run", "-d", "--rm", "-p", f"127.0.0.1::{expected_port}", tag], root)
    if started.returncode:
        raise AssertionError(started.stdout)
    container = started.stdout.strip()
    try:
        mapped = run(["docker", "port", container, str(expected_port)], root)
        if mapped.returncode:
            raise AssertionError(mapped.stdout)
        host_port = int(mapped.stdout.strip().rsplit(":", 1)[1])
        assert wait_health(host_port) == 200
    finally:
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    with tempfile.TemporaryDirectory(prefix="reference-repos-") as temp:
        base = Path(temp)
        for name, url, expect_ready, port in CASES:
            root = base / name
            clone(url, root)
            verify(root, expect_ready, port)
            print(f"{name}: PASS")

if __name__ == "__main__":
    main()
