from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, HttpUrl, Field
from pathlib import Path
from dataclasses import asdict
import tempfile, subprocess, shutil, zipfile, os, uuid, json, time, queue, threading

from core.scanner import Repository
from core.engine import Analyzer
from core.ast import ASTAnalyzer
from core.deps import graph
from core.migrations import analyze as migration_analyze
from core.models import DeploymentSpec
from core.validate import static_dockerfile
from generators.docker import dockerfile, compose
from generators.cloud import terraform, kubernetes
from security.audit import audit, sbom_plan, vulnerability_plan, policy as security_policy
from pricing.engine import PricingEngine
from sandbox.runner import Sandbox
from sandbox.repair import candidates as repair_candidates, apply as repair_apply
from sandbox.policy import DEFAULT_POLICY, validate_policy
from core.policy import deployment_gate

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = APP_ROOT / 'frontend'

app = FastAPI(title='Stack Detection & Deployment Intelligence', version='1.1.0', description='Repository-first deterministic analysis. Generation is a separate, gated phase.')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    run_validation: bool = False
    max_repair_attempts: int = Field(default=3, ge=1, le=5)
    providers: list[str] = Field(default_factory=lambda: ['aws', 'gcp', 'azure'])
    run_security_tools: bool = False
    analysis_id: str | None = None
    target: str | None = None
    mode: str | None = None  # 'generate' | 'existing' - required when a Dockerfile already exists

class ValidateRequest(AnalyzeRequest):
    run_validation: bool = True

ANALYSIS_CACHE: dict[str, dict] = {}
ANALYSIS_CACHE_LOCK = threading.Lock()
ANALYSIS_CACHE_TTL = 30 * 60

def emit(events, phase, message, status='running', **extra):
    event = {'id': str(uuid.uuid4()), 'time': time.time(), 'phase': phase, 'message': message, 'status': status}
    event.update(extra); events.append(event); return event

def clone(url):
    tmp = tempfile.mkdtemp(prefix='stack-detection-repo-'); target = Path(tmp) / 'repo'
    p = subprocess.run(['git', 'clone', '--depth', '1', '--no-tags', '--filter=blob:none', str(url), str(target)], capture_output=True, text=True, timeout=180)
    if p.returncode:
        shutil.rmtree(tmp, ignore_errors=True); raise HTTPException(400, 'Git clone failed: ' + p.stderr[-3000:])
    return tmp, target

def extract_zip(upload_bytes):
    tmp = tempfile.mkdtemp(prefix='stack-detection-zip-'); z = Path(tmp) / 'upload.zip'; z.write_bytes(upload_bytes); root = Path(tmp) / 'repo'; root.mkdir()
    try:
        with zipfile.ZipFile(z) as archive:
            root_resolved = root.resolve()
            for info in archive.infolist():
                target = (root / info.filename).resolve()
                if not str(target).startswith(str(root_resolved) + os.sep): raise HTTPException(400, 'Unsafe ZIP path detected.')
            archive.extractall(root)
    except zipfile.BadZipFile:
        shutil.rmtree(tmp, ignore_errors=True); raise HTTPException(400, 'Invalid ZIP archive.')
    children = [p for p in root.iterdir() if p.is_dir()]
    if len(children) == 1 and not (root / 'package.json').exists() and not (root / 'pyproject.toml').exists(): root = children[0]
    return tmp, root

def _cache_put(result, spec, repo_url):
    now = time.time()
    item = {'created_at': now, 'repo_url': str(repo_url), 'repository': result.get('repository', {}), 'deployment_ir': spec.to_dict(), 'analysis': result}
    with ANALYSIS_CACHE_LOCK:
        ANALYSIS_CACHE[result['analysis_id']] = item
        stale = [k for k, v in ANALYSIS_CACHE.items() if now - v.get('created_at', 0) > ANALYSIS_CACHE_TTL]
        for k in stale: ANALYSIS_CACHE.pop(k, None)

def _cache_get(analysis_id, repo_url):
    if not analysis_id: return None
    with ANALYSIS_CACHE_LOCK: item = ANALYSIS_CACHE.get(analysis_id)
    if not item or item.get('repo_url') != str(repo_url) or time.time() - item.get('created_at', 0) > ANALYSIS_CACHE_TTL: return None
    return item

def analyze_root(root, providers, events=None, repo_url=None, target=None):
    """Analysis phase only. No deployment artifact is generated here."""
    events = events if events is not None else []
    emit(events, 'acquisition', 'Repository acquired and isolated for analysis.', 'done')
    repo = Repository(root)
    emit(events, 'inventory', f'Indexed {len(repo.files):,} files ({repo.size_bytes():,} bytes of source/config data).', 'done', file_count=len(repo.files))
    analyzer = Analyzer(repo)
    emit(events, 'identification', 'Running deterministic stack identification from manifests, lockfiles, source markers and configuration…')
    spec, evidence, result = analyzer.analyze(target=target)
    emit(events, 'identification', f"Primary language: {result['summary']['primary_language']}; framework: {result['summary']['framework']}.", 'done', data={'languages': result['languages'], 'frameworks': result['frameworks']})
    emit(events, 'runtime', f"Runtime: {result['summary']['runtime']} {result['summary']['runtime_version']}", 'done')
    emit(events, 'package_managers', f"Package managers: {', '.join(x['name'] for x in spec.package_managers) or 'none'}", 'done', data=spec.package_managers)
    deep = result.get('deep_analysis', {})
    emit(events, 'deep_analysis', f"Deep deployment analysis completed: {len(deep.get('checks', []))} checks, {len(deep.get('warnings', []))} warnings, {len(deep.get('blockers', []))} blockers.", 'done' if deep.get('status') == 'ready' else 'warning', data=deep)
    emit(events, 'entrypoints', f"Build: {result['summary']['build_command']} · Start: {result['summary']['start_command']} · Port: {result['summary']['port']}", 'done')
    emit(events, 'architecture', f"Roles: {', '.join(result['summary']['application_roles']) or 'none'}; services: {', '.join(result['summary']['services']) or 'none'}.", 'done')
    emit(events, 'environment', f"Collected {len(result['summary']['environment_variables'])} environment-variable signals.", 'done')
    emit(events, 'infrastructure', f"Found {len(spec.infrastructure.get('files', []))} infrastructure/config files.", 'done', data=spec.infrastructure)
    emit(events, 'ci_cd', f"Found {len(spec.ci_cd.get('workflows', []))} CI/CD workflow definitions.", 'done')
    emit(events, 'dependencies', 'Building dependency graph from manifests and lockfiles…')
    spec.dependencies = graph(repo)
    emit(events, 'dependencies', f"Dependency graph: {spec.dependencies.get('direct_count', 0)} direct, {spec.dependencies.get('resolved_count', 0)} resolved.", 'done', data=spec.dependencies)
    emit(events, 'ast', 'Analyzing source imports and syntax structures across detected languages…')
    ast = ASTAnalyzer(repo).analyze()
    emit(events, 'ast', f"AST/source analysis completed for {len(ast.get('files', [])) if isinstance(ast, dict) else 0} source files.", 'done', data=ast)
    emit(events, 'migrations', 'Checking migration frameworks and destructive database operations…')
    spec.migrations = migration_analyze(repo)
    migration_msg = 'Manual approval required.' if spec.migrations.get('requires_manual_approval') else 'No destructive migration requiring approval detected.'
    emit(events, 'migrations', migration_msg, 'warning' if spec.migrations.get('requires_manual_approval') else 'done', data=spec.migrations)
    emit(events, 'security', 'Running repository security policy checks…')
    findings = audit(repo)
    spec.security = {'findings': [asdict(x) for x in findings]}
    emit(events, 'security', f"Security policy found {len(findings)} finding(s).", 'warning' if any(x.severity in {'critical', 'high'} for x in findings) else 'done', data=spec.security)
    spec.cloud = {'providers': providers, 'artifacts': []}
    spec.policy = {'confidence': min(result['summary']['confidence'], deep.get('confidence', result['summary']['confidence']) or 0), 'requires_manual_approval': spec.migrations.get('requires_manual_approval', False), 'auto_deploy_eligible': False, 'generation_gate': 'analysis_complete_only'}
    analysis_id = str(uuid.uuid4())
    result.update({'analysis_id': analysis_id, 'sandbox_policy': validate_policy(DEFAULT_POLICY), 'deployment_ir': spec.to_dict(), 'generated_files': {}, 'ast': ast, 'dependency_graph': spec.dependencies, 'migrations': spec.migrations, 'security': {'findings': [asdict(x) for x in findings], 'sbom': sbom_plan(repo, result['summary']['package_manager']), 'vulnerability_scan': vulnerability_plan(), 'policy': security_policy(findings)}, 'static_validation': None, 'cloud_cost_estimates': {p: PricingEngine().estimate(spec, p) for p in providers if p in {'aws', 'gcp', 'azure'}}, 'repository': {'path_count': len(repo.files), 'size_bytes': repo.size_bytes(), 'hash': repo.hash()}, 'generation': {'status': 'not_requested', 'requested_artifact': None}})
    emit(events, 'complete', 'Repository analysis complete. No deployment artifact was generated.', 'done', data={'analysis_id': analysis_id, 'confidence': result['summary']['confidence'], 'deep_analysis': deep.get('status')})
    if repo_url: _cache_put(result, spec, repo_url)
    return result, repo, spec

def _spec_from_cached(item): return DeploymentSpec(**item['deployment_ir'])

def _reuse_or_analyze(root, req, providers, events=None):
    cached = _cache_get(req.analysis_id, req.repo_url)
    if cached:
        repo = Repository(root); current_hash = repo.hash(); expected_hash = cached.get('repository', {}).get('hash')
        if expected_hash and current_hash == expected_hash:
            spec = _spec_from_cached(cached); result = json.loads(json.dumps(cached['analysis']))
            if events is not None: emit(events, 'analysis_reuse', 'Reusing the completed repository analysis; repository hash matches.', 'done')
            return result, repo, spec
    if events is not None: emit(events, 'analysis_reuse', 'No matching analysis cache was supplied; running the full analysis gate first.', 'done')
    return analyze_root(root, providers, events, req.repo_url, target=req.target)

def _requested_artifact(spec, artifact):
    artifact = artifact.lower().strip()
    if artifact in {'dockerfile', 'docker'}: return 'Dockerfile', dockerfile(spec), 'dockerfile'
    if artifact in {'compose', 'docker-compose', 'docker_compose', 'compose.yaml'}: return 'compose.yaml', compose(spec), 'docker-compose'
    if artifact in {'k8s', 'kubernetes', 'k8s.yaml'}: return 'k8s.yaml', kubernetes(spec), 'kubernetes'
    if artifact.startswith('terraform-'):
        provider = artifact.removeprefix('terraform-').removesuffix('.tf')
        if provider not in {'aws', 'gcp', 'azure'}: raise HTTPException(400, f'Unsupported Terraform provider: {provider}')
        return f'terraform-{provider}.tf', terraform(spec, provider), f'terraform-{provider}'
    raise HTTPException(400, f'Unsupported artifact: {artifact}. Supported artifacts: dockerfile, docker-compose, k8s, terraform-aws, terraform-gcp, terraform-azure.')

def _generation_gate(result, spec, artifact):
    deep = result.get('deep_analysis', {})
    if deep.get('status') != 'ready':
        raise HTTPException(status_code=422, detail={'message': 'Generation blocked because repository analysis did not reach a deterministic ready state.', 'phase': 'analysis_gate', 'requested_artifact': artifact, 'deep_analysis': deep})
    if spec.migrations.get('requires_manual_approval'):
        raise HTTPException(status_code=409, detail={'message': 'Generation blocked by the repository migration approval gate.', 'phase': 'analysis_gate', 'requested_artifact': artifact, 'migrations': spec.migrations})

def _existing_dockerfile(root, spec):
    """The repo's own Dockerfile, if any - PROGRAM.md S24: existing infrastructure must be
    discovered before generating replacement infrastructure, not silently overwritten.
    Prefers the shallowest match (closest to repo root, the conventional location)."""
    candidates = sorted((f for f in spec.infrastructure.get('files', []) if Path(f).name.lower() == 'dockerfile'), key=lambda f: len(Path(f).parts))
    if not candidates: return None
    path = candidates[0]; full = Path(root, path)
    if not full.exists(): return None
    return path, full.read_text(errors='ignore')

def _generate_from_analysis(root, result, spec, artifact, req):
    _generation_gate(result, spec, artifact)
    if artifact.lower().strip() in {'dockerfile', 'docker'}:
        existing = _existing_dockerfile(root, spec)
        mode = (req.mode or '').lower().strip()
        if existing and mode not in {'generate', 'existing'}:
            path, content = existing
            raise HTTPException(status_code=409, detail={'message': f'A Dockerfile already exists at {path}. Choose how to proceed: mode="existing" to use it as-is, or mode="generate" to generate a new one from the analyzed evidence.', 'phase': 'existing_artifact_choice', 'requested_artifact': 'dockerfile', 'existing_dockerfile': {'path': path, 'content': content}})
        if existing and mode == 'existing':
            path, content = existing
            generation = {'status': 'existing', 'requested_artifact': 'dockerfile', 'files': [path], 'source': 'repository'}
            result['generation'] = generation; result['generated_files'] = {path: content}
            return path, content, result, generation
    filename, content, kind = _requested_artifact(spec, artifact)
    generation = {'status': 'generated', 'requested_artifact': kind, 'files': [filename]}
    if kind == 'dockerfile':
        validation = static_dockerfile(content)
        if not validation.get('valid'):
            raise HTTPException(status_code=422, detail={'message': 'Dockerfile generation was completed but static validation failed; the artifact was withheld.', 'phase': 'artifact_validation', 'requested_artifact': kind, 'static_validation': validation, 'deep_analysis': result.get('deep_analysis', {})})
        result['static_validation'] = validation; result['generation'] = generation; result['generated_files'] = {filename: content}
        if req.run_validation:
            verification = autonomous_validate(root, result, spec, req.max_repair_attempts, req.run_security_tools)
            if verification.get('validation', {}).get('status') != 'passed':
                raise HTTPException(status_code=422, detail={'message': 'Dockerfile was generated and statically validated, but runtime verification did not pass.', 'phase': 'runtime_verification', 'requested_artifact': kind, 'validation': verification.get('validation', {}), 'deployment_gate': verification.get('deployment_gate', {}), 'deep_analysis': result.get('deep_analysis', {})})
            content = Path(root, 'Dockerfile').read_text() if Path(root, 'Dockerfile').exists() else content
            result['generated_files'] = {filename: content}; generation['verification'] = verification.get('validation', {}); generation['deployment_gate'] = verification.get('deployment_gate', {})
        return filename, content, result, generation
    result['generation'] = generation; result['generated_files'] = {filename: content}
    return filename, content, result, generation

def autonomous_validate(root, result, spec, max_attempts, run_security_tools=False, events=None):
    events = events if events is not None else []; sb = Sandbox(root); attempts, ledger = [], []; current = dockerfile(spec)
    try:
        for i in range(min(max_attempts, DEFAULT_POLICY.max_repair_attempts)):
            emit(events, 'sandbox', f'Build attempt {i + 1}/{max_attempts}: creating ephemeral build/runtime environment…')
            Path(root, 'Dockerfile').write_text(current)
            outcome = sb.build_and_test(port=spec.network.get('port') or 8000, health_path=spec.network.get('health_endpoint') or '/')
            outcome['attempt'] = i + 1; attempts.append(outcome)
            emit(events, 'sandbox', f"Attempt {i + 1}: {outcome.get('status', 'unknown')}", 'done' if outcome.get('status') == 'runtime_healthy' else 'warning', data=outcome)
            if run_security_tools and outcome.get('status') in {'runtime_healthy', 'runtime_started'}:
                emit(events, 'security', 'Running runtime image SBOM/vulnerability tools…'); image = outcome.get('image_tag'); outcome['security_scan'] = sb.security_scan(image); emit(events, 'security', 'Runtime security scan completed.', 'done', data=outcome['security_scan'])
            if outcome.get('status') == 'runtime_healthy': ledger.append({'attempt': i + 1, 'result': 'pass', 'repair': None}); break
            emit(events, 'repair', 'Diagnosing failure and evaluating bounded deterministic repairs…')
            actions = repair_candidates(spec, outcome); repair = repair_apply(spec, outcome, Repository(root))
            ledger.append({'attempt': i + 1, 'result': outcome.get('status'), 'diagnosis': outcome.get('diagnosis'), 'candidates': actions, 'repair': repair})
            emit(events, 'repair', repair.get('message', 'Repair evaluation completed.'), 'done' if repair.get('changed') else 'warning', data={'candidates': actions, 'repair': repair})
            if not repair.get('changed'): break
            current = dockerfile(spec)
        result['validation'] = {'status': 'passed' if attempts and attempts[-1].get('status') == 'runtime_healthy' else ('skipped' if attempts and attempts[-1].get('status') == 'skipped' else 'not_passed'), 'attempts': attempts, 'repair_ledger': ledger, 'max_attempts': max_attempts, 'autonomous_repair': bool(any(x.get('repair', {}).get('changed') for x in ledger))}
        result['deployment_gate'] = deployment_gate(spec, result.get('static_validation') or {}, result.get('security', {}).get('findings', []), result['validation'])
    finally: sb.cleanup()
    return result

@app.get('/')
def root():
    index = FRONTEND / 'index.html'; return FileResponse(index) if index.exists() else {'service': app.title, 'version': app.version, 'docs': '/docs'}

@app.get('/frontend/{asset_path:path}')
def frontend_asset(asset_path: str):
    target = (FRONTEND / asset_path).resolve()
    if not str(target).startswith(str(FRONTEND.resolve()) + os.sep) or not target.is_file(): raise HTTPException(404, 'Frontend asset not found.')
    return FileResponse(target)

@app.get('/health')
def health(): return {'status': 'ok', 'version': app.version, 'engine': 'deterministic-v1', 'pipeline': 'analysis-gated-generation'}

@app.post('/analyze')
def analyze(req: AnalyzeRequest):
    tmp, root = clone(req.repo_url)
    try: d, _, _ = analyze_root(root, req.providers, repo_url=req.repo_url, target=req.target); return d
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/analyze-stream')
def analyze_stream(req: AnalyzeRequest):
    def stream():
        q = queue.Queue(); done = object()
        class LiveEvents(list):
            def append(self, item): super().append(item); q.put(item)
        def worker():
            try:
                q.put({'phase': 'acquisition', 'message': 'Cloning repository for detailed analysis…', 'status': 'running', 'id': str(uuid.uuid4()), 'time': time.time()})
                tmp, root = clone(req.repo_url)
                try: result, _, _ = analyze_root(root, req.providers, LiveEvents(), req.repo_url, target=req.target); q.put({'__result__': result})
                finally: shutil.rmtree(tmp, ignore_errors=True)
            except Exception as exc: q.put({'__error__': str(exc)})
            finally: q.put(done)
        yield json.dumps({'type': 'meta', 'analysis_id': str(uuid.uuid4()), 'phase': 'start', 'message': 'Starting repository-first intelligence pipeline.'}) + '\n'
        t = threading.Thread(target=worker, daemon=True); t.start()
        while True:
            item = q.get()
            if item is done: break
            if '__result__' in item: yield json.dumps({'type': 'result', 'data': item['__result__']}, default=str) + '\n'
            elif '__error__' in item: yield json.dumps({'type': 'error', 'message': item['__error__']}) + '\n'
            else: yield json.dumps({'type': 'event', **item}, default=str) + '\n'
        t.join(timeout=1)
    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})

@app.post('/generate/dockerfile')
def generate_dockerfile(req: AnalyzeRequest):
    tmp, root = clone(req.repo_url)
    try:
        d, _, spec = _reuse_or_analyze(root, req, req.providers)
        filename, content, d, generation = _generate_from_analysis(root, d, spec, 'dockerfile', req)
        return {'analysis_id': d['analysis_id'], 'summary': d['summary'], 'deep_analysis': d.get('deep_analysis', {}), 'stacks': {'languages': d['languages'], 'frameworks': d['frameworks'], 'services': d['summary']['services']}, 'dockerfile': content, 'deployment_ir': d['deployment_ir'], 'static_validation': d.get('static_validation'), 'verification': d.get('validation'), 'deployment_gate': d.get('deployment_gate'), 'generation': generation}
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/generate/docker-compose')
def generate_compose(req: AnalyzeRequest):
    tmp, root = clone(req.repo_url)
    try:
        d, _, spec = _reuse_or_analyze(root, req, req.providers)
        filename, content, d, generation = _generate_from_analysis(root, d, spec, 'docker-compose', req)
        return {'analysis_id': d['analysis_id'], 'summary': d['summary'], 'deep_analysis': d.get('deep_analysis', {}), 'stacks': {'languages': d['languages'], 'frameworks': d['frameworks'], 'services': d['summary']['services']}, 'compose': content, 'deployment_ir': d['deployment_ir'], 'generation': generation}
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/generate/{artifact}')
def generate_artifact(artifact: str, req: AnalyzeRequest):
    tmp, root = clone(req.repo_url)
    try:
        d, _, spec = _reuse_or_analyze(root, req, req.providers)
        filename, content, d, generation = _generate_from_analysis(root, d, spec, artifact, req)
        return {'analysis_id': d['analysis_id'], 'summary': d['summary'], 'deep_analysis': d.get('deep_analysis', {}), 'stacks': {'languages': d['languages'], 'frameworks': d['frameworks'], 'services': d['summary']['services']}, 'artifact': filename, 'content': content, 'deployment_ir': d['deployment_ir'], 'generation': generation, 'static_validation': d.get('static_validation'), 'verification': d.get('validation'), 'deployment_gate': d.get('deployment_gate')}
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/analyze-upload')
async def analyze_upload(file: UploadFile = File(...), validate: bool = False, max_repair_attempts: int = 3):
    if not file.filename or not file.filename.lower().endswith('.zip'): raise HTTPException(400, 'Upload a .zip repository archive.')
    tmp, root = extract_zip(await file.read())
    try:
        d, _, spec = analyze_root(root, ['aws', 'gcp', 'azure'])
        if validate: d = autonomous_validate(root, d, spec, max_repair_attempts)
        return d
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/validate')
def validate(req: ValidateRequest):
    tmp, root = clone(req.repo_url)
    try:
        d, _, spec = analyze_root(root, req.providers, repo_url=req.repo_url, target=req.target); return autonomous_validate(root, d, spec, req.max_repair_attempts, req.run_security_tools)
    finally: shutil.rmtree(tmp, ignore_errors=True)

@app.post('/analyze-and-validate')
def analyze_validate(req: AnalyzeRequest):
    tmp, root = clone(req.repo_url)
    try:
        d, _, spec = analyze_root(root, req.providers, repo_url=req.repo_url, target=req.target); return autonomous_validate(root, d, spec, req.max_repair_attempts, req.run_security_tools)
    finally: shutil.rmtree(tmp, ignore_errors=True)
