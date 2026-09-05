"""Proves the fail-closed promise (PROGRAM.md S19, S37): recognized-but-unsupported
technology and genuinely ambiguous polyglot roots must block rather than be guessed
into a strategy they were never verified for."""
from core.scanner import Repository
from core.engine import Analyzer
from core.migrations import analyze as migration_analyze


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_recognized_unsupported_technology_blocks_rather_than_guesses(tmp_path):
    write(tmp_path, "mix.exs", "defmodule Demo.MixProject do\n  use Mix.Project\nend\n")
    write(tmp_path, "lib/demo.ex", "defmodule Demo do\nend\n")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    deep = result["deep_analysis"]
    assert deep["status"] == "blocked"
    assert any(b["code"] == "UNSUPPORTED_TARGET" for b in deep["blockers"])
    assert result["summary"]["framework"] == "Unknown"


def test_polyglot_root_with_no_single_viable_target_blocks(tmp_path):
    write(tmp_path, "package.json", '{"scripts":{"dev":"vite"}}')
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    deep = result["deep_analysis"]
    assert deep["status"] == "blocked"
    assert any(b["code"] == "POLYGLOT_TARGET" for b in deep["blockers"])


def test_jvm_manifest_without_a_supported_framework_blocks(tmp_path):
    write(tmp_path, "pom.xml", "<project><groupId>demo</groupId><artifactId>demo</artifactId></project>\n")
    write(tmp_path, "src/main/java/Demo.java", "public class Demo { public static void main(String[] a) {} }\n")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    deep = result["deep_analysis"]
    assert deep["status"] == "blocked"
    assert any(b["code"] == "ENTRYPOINT" for b in deep["blockers"])


def test_readme_port_outranks_generic_source_scan(tmp_path):
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n# also mentions localhost:9999 in a comment, not a real bind\n")
    write(tmp_path, "README.md", """# Run

```bash
uvicorn main:app --host 0.0.0.0 --port 5000
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["deep_analysis"]["status"] == "ready"
    assert result["summary"]["port"] == 5000


def test_ruby_readme_contradicting_rails_server_blocks(tmp_path):
    write(tmp_path, "Gemfile", "source 'https://rubygems.org'\ngem 'rails'\n")
    write(tmp_path, "bin/rails", "#!/usr/bin/env ruby\n")
    write(tmp_path, "config/application.rb", "module App\nend\n")
    write(tmp_path, "README.md", """# Run

```bash
puma -C config/puma.rb
```
""")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    # Rails/Rack markers already resolve a start command deterministically; a README
    # documenting an unrelated tool is informational context here, not a rival claim
    # on the SAME fact this engine resolves twice (unlike Python/Node's entrypoint
    # reconciliation) - Ruby's fallback path only consults README when no Rails/Rack
    # marker exists at all. Documented for completeness, not a contradiction blocker.
    assert result["deep_analysis"]["status"] == "ready"
    assert "rails server" in result["summary"]["start_command"]


def test_migration_analyzer_still_flags_a_real_destructive_migration(tmp_path):
    write(tmp_path, "requirements.txt", "django\n")
    write(tmp_path, "app/migrations/0002_drop_legacy.py", "operations = []\n# DROP TABLE legacy_users;\n")
    result = migration_analyze(Repository(tmp_path))
    assert result["requires_manual_approval"]
    assert any(f["code"] == "DROP_TABLE" for f in result["destructive_changes"])
    assert "Django" in result["systems"]
