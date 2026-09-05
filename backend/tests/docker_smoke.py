from pathlib import Path
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def fixture(name, files):
    root = Path(tempfile.mkdtemp(prefix=f"autodeploy-{name}-"))
    for path, text in files.items():
        write(root, path, text)
    return root


def run(cmd, cwd=None):
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def wait_http(port, timeout=60):
    """A 4xx/5xx response still proves the app answered - urlopen raises HTTPError for
    those instead of returning them, so it must be caught and treated the same as a
    normal response rather than retried until the timeout."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
                if 200 <= r.status < 500:
                    return r.status
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 500: return exc.code
            last = exc
        except Exception as exc:
            last = exc
        time.sleep(1)
    raise RuntimeError(f"HTTP smoke test failed on {port}: {last}")


def docker_smoke(name, root, expected_port):
    spec, _, result = Analyzer(Repository(root)).analyze()
    deep = result["deep_analysis"]
    if deep["status"] != "ready":
        raise AssertionError(f"{name}: analysis blocked: {deep['blockers']}")
    (root / "Dockerfile").write_text(dockerfile(spec))
    tag = f"autodeploy-smoke-{name}:ci"
    build = run(["docker", "build", "--pull", "--no-cache", "-t", tag, "."], cwd=root)
    if build.returncode:
        print(build.stdout)
        raise AssertionError(f"{name}: docker build failed")
    cp = run(["docker", "run", "-d", "--rm", "-p", f"0:{expected_port}", tag])
    if cp.returncode:
        print(cp.stdout)
        raise AssertionError(f"{name}: docker run failed")
    cid = cp.stdout.strip()
    try:
        mapped = run(["docker", "port", cid, str(expected_port)])
        if mapped.returncode:
            print(mapped.stdout)
            raise AssertionError(f"{name}: port lookup failed")
        host_port = int(mapped.stdout.strip().rsplit(":", 1)[1])
        status = wait_http(host_port)
        print(f"{name}: PASS — build + start + HTTP {status}", flush=True)
    finally:
        subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    fixtures = {
        "static": (fixture("static", {"index.html": "<h1>ok</h1>\n"}), 8080),
        "node": (fixture("node", {
            "package.json": json.dumps({"scripts": {"build": "mkdir -p dist && printf ok > dist-marker", "start": "node server.js"}}),
            "server.js": "require('http').createServer((q,s)=>s.end('ok')).listen(process.env.PORT||3000,'0.0.0.0')\n",
        }), 3000),
        "python": (fixture("python", {
            "requirements.txt": "fastapi==0.116.1\nuvicorn==0.35.0\n",
            "main.py": "from fastapi import FastAPI\napp=FastAPI()\n",
        }), 8000),
        "go": (fixture("go", {
            "go.mod": "module smoke\n\ngo 1.24\n",
            "main.go": 'package main\nimport ("fmt"; "net/http")\nfunc main(){http.HandleFunc("/",func(w http.ResponseWriter,r *http.Request){fmt.Fprint(w,"ok")}); http.ListenAndServe(":8080",nil)}\n',
        }), 8080),
        "rust": (fixture("rust", {
            "Cargo.toml": '[package]\nname="smoke"\nversion="0.1.0"\nedition="2021"\n',
            "src/main.rs": 'use std::io::{Read,Write}; use std::net::TcpListener; fn main(){let l=TcpListener::bind("0.0.0.0:8080").unwrap(); for mut s in l.incoming().flatten(){let mut b=[0;512];let _=s.read(&mut b);let r="HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok";let _=s.write_all(r.as_bytes());}}\n',
        }), 8080),
        "java": (fixture("java", {
            "pom.xml": """<project xmlns=\"http://maven.apache.org/POM/4.0.0\"><modelVersion>4.0.0</modelVersion><parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.4.5</version></parent><groupId>ci.smoke</groupId><artifactId>smoke</artifactId><version>0.0.1</version><properties><java.version>21</java.version></properties><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies><build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build></project>""",
            "src/main/java/ci/smoke/Application.java": "package ci.smoke; import org.springframework.boot.SpringApplication; import org.springframework.boot.autoconfigure.SpringBootApplication; import org.springframework.web.bind.annotation.GetMapping; import org.springframework.web.bind.annotation.RestController; @SpringBootApplication public class Application { public static void main(String[] a){SpringApplication.run(Application.class,a);} @RestController static class C { @GetMapping(\"/\") String ok(){return \"ok\";} } }\n",
        }), 8080),
        "dotnet": (fixture("dotnet", {
            "Smoke.csproj": """<Project Sdk=\"Microsoft.NET.Sdk.Web\"><PropertyGroup><TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>""",
            "Program.cs": "var app = WebApplication.CreateBuilder(args).Build(); app.MapGet(\"/\", () => \"ok\"); app.Run();\n",
        }), 8080),
        "php": (fixture("php", {
            "composer.json": json.dumps({"require": {}}),
            "index.php": "<?php echo 'ok';",
        }), 80),
        "ruby": (fixture("ruby", {
            # webrick, not puma: puma's nio4r dependency needs native build tools the
            # ruby:slim base image doesn't have - a separate, pre-existing gap in the
            # Ruby Docker template (out of scope here; webrick is pure Ruby).
            "Gemfile": "source 'https://rubygems.org'\ngem 'rack', '~> 3.0'\ngem 'webrick'\n",
            "config.ru": "run ->(_env) { [200, {'content-type'=>'text/plain'}, ['ok']] }\n",
        }), 3000),
    }
    for name, (root, port) in fixtures.items():
        docker_smoke(name, root, port)


if __name__ == "__main__":
    main()
