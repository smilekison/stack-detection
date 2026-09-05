from core.scanner import Repository
from core.readme_evidence import parse


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_readme_canonical_example_extracts_working_directory_port_and_production_command(tmp_path):
    write(tmp_path, "README.md", """# Run

## Production

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```
""")
    evidence = parse(Repository(tmp_path))
    assert evidence["working_directory"] == "backend"
    assert evidence["port"] == 8000
    prod = evidence["commands"]["start"]["production"]
    assert len(prod) == 1
    assert prod[0]["command"] == "uvicorn main:app --host 0.0.0.0 --port 8000"
    assert evidence["commands"]["start"]["development"] == []


def test_readme_reload_command_is_never_classified_production(tmp_path):
    write(tmp_path, "README.md", """# Development

```bash
uvicorn main:app --reload --port 8000
```
""")
    evidence = parse(Repository(tmp_path))
    assert evidence["commands"]["start"]["production"] == []
    assert len(evidence["commands"]["start"]["development"]) == 1


def test_readme_install_and_build_commands_are_classified(tmp_path):
    write(tmp_path, "README.md", """# Setup

```bash
npm install
npm run build
npm start
```
""")
    evidence = parse(Repository(tmp_path))
    assert evidence["commands"]["install"][0]["command"] == "npm install"
    assert evidence["commands"]["build"][0]["command"] == "npm run build"
    assert evidence["commands"]["start"]["production"][0]["command"] == "npm start"
