"""Structured README/operational-documentation evidence."""
import re
from pathlib import Path
README_NAMES={"readme.md","readme.rst","readme.txt","readme"}
SHELL_LANGUAGES={"bash","sh","shell","zsh","console","cmd","powershell","ps1"}
DEV_PATTERN=re.compile(r"--reload|--hot|\bnodemon\b|\bwatch(?:ing)?\b|\bdev server\b",re.I)
INSTALL_MARKERS=("pip install","npm ci","npm install","yarn install","pnpm install","bundle install","composer install","go mod download","poetry install","pipenv install","bun install")
TEST_MARKERS=("pytest","unittest","compileall","mypy","flake8","eslint","jest","mocha","go test","cargo test","rspec","phpunit")
PORT_PATTERNS=(re.compile(r"--port(?:=|\s+)[\"']?(\d{2,5})",re.I),re.compile(r"\bport\s*[=:]\s*[\"']?(\d{2,5})",re.I),re.compile(r"localhost:(\d{2,5})\b",re.I),re.compile(r"127\.0\.0\.1:(\d{2,5})\b",re.I))

def _rooted(path):
    p=Path(path).parent.as_posix(); return "" if p=="." else p

def _readmes(repo,unit):
    roots={""}
    if unit and unit.get("root"): roots.add(unit["root"])
    return sorted(f for f in repo.files if _rooted(f) in roots and Path(f).name.lower() in README_NAMES)

def _sections(text):
    lines=text.splitlines(); out=[]; heading=""; buf=[]
    for line in lines:
        m=re.match(r"^#{1,6}\s+(.+?)\s*$",line)
        if m:
            if buf: out.append((heading,"\n".join(buf)))
            heading=m.group(1).strip(); buf=[]
        else: buf.append(line)
    if buf: out.append((heading,"\n".join(buf)))
    return out

def _code_blocks(body):
    p=re.compile(r"```([a-zA-Z0-9_+-]*)\s*\n(.*?)```",re.S)
    return [(lang.lower(),code) for lang,code in p.findall(body) if lang.lower() in SHELL_LANGUAGES]

def _strip_prompt(line): return re.sub(r"^\s*(?:\$|>)\s*","",line).strip()
def _is_development(command,heading): return bool(DEV_PATTERN.search(command) or re.search(r"\b(dev|development|develop|debug|local)\b",heading or "",re.I))
def _classify(command):
    low=command.lower().strip()
    if any(x in low for x in INSTALL_MARKERS): return "install"
    if any(x in low for x in TEST_MARKERS): return "test"
    if re.search(r"\b(build|compile|package|generate)\b",low): return "build"
    return "start"
def _port(command):
    for p in PORT_PATTERNS:
        m=p.search(command)
        if m:
            value=int(m.group(1))
            if 1<=value<=65535: return value
    return None

def parse(repo,unit=None):
    result={"documents":[],"working_directories":[],"working_directory":None,"ports":[],"port":None,"commands":{"install":[],"build":[],"test":[],"start":{"development":[],"production":[]}}}
    for path in _readmes(repo,unit):
        result["documents"].append(path)
        for heading,body in _sections(repo.read(path)):
            for language,block in _code_blocks(body):
                cwd=None
                for raw in block.splitlines():
                    line=_strip_prompt(raw)
                    if not line or line.startswith("#"): continue
                    cd=re.match(r"^cd\s+([\w./@-]+)\s*(?:&&)?$",line)
                    if cd: cwd=cd.group(1).strip("/") or "."; continue
                    if cwd and cwd not in result["working_directories"]: result["working_directories"].append(cwd)
                    p=_port(line)
                    if p and p not in result["ports"]: result["ports"].append(p)
                    entry={"command":line,"heading":heading,"working_directory":cwd,"language":language,"source":path}
                    kind=_classify(line)
                    if kind in {"install","build","test"}: result["commands"][kind].append(entry)
                    else: result["commands"]["start"]["development" if _is_development(line,heading) else "production"].append(entry)
    result["working_directory"]=result["working_directories"][0] if result["working_directories"] else None
    result["port"]=result["ports"][0] if result["ports"] else None
    return result
