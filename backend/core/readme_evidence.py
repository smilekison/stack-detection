"""README / operational-documentation evidence (PROGRAM.md Priority 1).

Parses fenced code blocks under markdown headings into install/build/start
commands, classifying start commands as development or production from
explicit flag evidence so a documented `--reload` invocation can never be
mistaken for a production command (PROGRAM.md S8).
"""
import re
from pathlib import Path

README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}
SHELL_LANGUAGES = {"bash", "sh", "shell", "zsh", "console", "cmd", "powershell", "ps1"}
# \bdev\w*\b, not just \bdev\b: frameworks name their dev-mode command "develop"/
# "development" as often as bare "dev" (Strapi's `strapi develop` / `npm run develop` is
# its actual auto-reload dev server, the same role `--reload` plays elsewhere) - the exact-
# word version missed those, letting a genuine dev command read as a production one.
DEV_PATTERN = re.compile(r"--reload|--hot|nodemon|\bdev\w*\b|\bwatch\b", re.I)
INSTALL_MARKERS = ("pip install", "npm ci", "npm install", "yarn install", "pnpm install", "bundle install", "composer install", "go mod download", "poetry install", "pipenv install", "bun install")
TEST_MARKERS = ("pytest", "unittest", "compileall", "mypy", "flake8", "eslint", "jest", "mocha", "go test", "cargo test", "rspec", "phpunit")
# File/env/utility verbs that show up constantly in README setup instructions (copying an
# example env file, making a directory, chmod'ing a script...) but never start a long-running
# server. Without this, `_classify` had no way to say "none of the above" other than
# defaulting to "start" - so `cp .env.example .env` was mistaken for a documented production
# command and blocked generation against a real repo (README vs package.json contradiction
# that was never a real contradiction). A blocklist of unambiguous non-start verbs is more
# robust here than trying to allowlist every framework's start-command syntax.
SETUP_VERBS = {"cp", "mv", "mkdir", "rmdir", "rm", "touch", "chmod", "chown", "export", "source", "git", "curl", "wget", "echo", "cat", "ls", "ln", "tar", "unzip", "sed", "awk", "grep", "find", "open", "code", "vim", "vi", "nano", "set", "unset", "kubectl", "helm"}
PORT_PATTERNS = (r"--port[= ](\d{2,5})", r"\bport[= ](\d{2,5})\b", r":(\d{2,5})\b")


def _readmes(repo, unit):
    roots = {""}
    if unit and unit.get("root"): roots.add(unit["root"])
    out = []
    for f in repo.files:
        parent = Path(f).parent.as_posix(); parent = "" if parent == "." else parent
        if parent in roots and Path(f).name.lower() in README_NAMES: out.append(f)
    return sorted(out)


def _sections(text):
    lines = text.splitlines(); sections = []; heading = ""; buf = []
    for line in lines:
        if re.match(r"^#{1,6}\s+", line):
            if buf: sections.append((heading, "\n".join(buf)))
            heading = re.sub(r"^#{1,6}\s+", "", line).strip(); buf = []
        else: buf.append(line)
    if buf: sections.append((heading, "\n".join(buf)))
    return sections


def _code_blocks(body):
    """Only shell-tagged fences are scanned for commands.

    An untagged or prose-tagged fence (```text ascii diagrams, ```json samples, ...)
    is not runnable evidence and must not be swept up as a documented command.
    """
    return [code for lang, code in re.findall(r"```([a-zA-Z]*)\n(.*?)```", body, re.S) if lang.lower() in SHELL_LANGUAGES]


def _is_development(command): return bool(DEV_PATTERN.search(command))


def _first_verb(command):
    tokens = command.strip().split()
    i = 0
    while i < len(tokens) and tokens[i].lower() == "sudo": i += 1
    return tokens[i].lower() if i < len(tokens) else ""


def _classify(command):
    low = command.lower()
    if any(m in low for m in INSTALL_MARKERS): return "install"
    if any(m in low for m in TEST_MARKERS): return "test"
    if re.search(r"\bbuild\b", low): return "build"
    if _first_verb(command) in SETUP_VERBS: return "setup"
    return "start"


def _port(command):
    for pat in PORT_PATTERNS:
        m = re.search(pat, command, re.I)
        if m:
            p = int(m.group(1))
            if 1 <= p <= 65535: return p
    return None


def parse(repo, unit=None):
    """Extract structured operational evidence from README(s) for a unit (or the repo root)."""
    result = {"working_directory": None, "port": None, "commands": {"install": [], "build": [], "test": [], "setup": [], "start": {"development": [], "production": []}}}
    for path in _readmes(repo, unit):
        for heading, body in _sections(repo.read(path)):
            for block in _code_blocks(body):
                cwd = None
                for raw in block.splitlines():
                    line = raw.strip().lstrip("$").strip()
                    if not line or line.startswith("#"): continue
                    cd_match = re.match(r"^cd\s+([\w./-]+)", line)
                    if cd_match: cwd = cd_match.group(1).strip("/"); continue
                    port = _port(line)
                    if port and result["port"] is None: result["port"] = port
                    if cwd and result["working_directory"] is None: result["working_directory"] = cwd
                    entry = {"command": line, "heading": heading, "working_directory": cwd, "source": path}
                    kind = _classify(line)
                    if kind in ("install", "build", "test", "setup"): result["commands"][kind].append(entry)
                    else: result["commands"]["start"]["development" if _is_development(line) else "production"].append(entry)
    return result
