from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile


def write(root, path, text):
    p=root/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)


def test_static_html_is_not_misclassified_as_node(tmp_path):
    write(tmp_path,'index.html','<html><body><h1>Hello</h1></body></html>')
    write(tmp_path,'styles.css','body { font-family: sans-serif; }')
    spec,_,result=Analyzer(Repository(tmp_path)).analyze()
    assert result['deep_analysis']['status']=='ready'
    assert spec.runtime['name']=='Static Web'
    assert spec.build['runtime_strategy']=='static-nginx'
    assert spec.network['port']==8080
    image=dockerfile(spec)
    assert 'nginxinc/nginx-unprivileged' in image
    assert 'EXPOSE 8080' in image


def test_python_fastapi_resolves_entrypoint(tmp_path):
    write(tmp_path,'requirements.txt','fastapi\nuvicorn\n')
    write(tmp_path,'main.py','from fastapi import FastAPI\napp=FastAPI()\n')
    spec,_,result=Analyzer(Repository(tmp_path)).analyze()
    assert result['deep_analysis']['status']=='ready'
    assert spec.build['runtime_strategy']=='python-uvicorn'
    assert 'uvicorn main:app' in spec.processes[0]['start_command']
    assert 'EXPOSE 8000' in dockerfile(spec)


def test_rust_binary_name_is_resolved(tmp_path):
    write(tmp_path,'Cargo.toml','[package]\nname = "hello-web"\nversion = "0.1.0"\n')
    write(tmp_path,'src/main.rs','fn main() { println!("ok"); }')
    spec,_,result=Analyzer(Repository(tmp_path)).analyze()
    assert result['deep_analysis']['status']=='ready'
    assert spec.build['binary']=='hello-web'
    assert 'target/release/hello-web' in dockerfile(spec)
