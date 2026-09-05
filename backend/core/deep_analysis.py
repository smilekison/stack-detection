from pathlib import Path
import re


LOCKFILES = {'npm': 'package-lock.json', 'pnpm': 'pnpm-lock.yaml', 'yarn': 'yarn.lock', 'bun': 'bun.lock'}


def _package(repo):
    return repo.json('package.json') if 'package.json' in repo.file_set else {}


def _script(pkg, name):
    return (pkg.get('scripts') or {}).get(name)


def _first_file(repo, names):
    return next((f for f in repo.files if Path(f).name in names), None)


def _port_from_text(text):
    patterns = [
        r'(?i)--port\s+(?:=\s*)?[\'\"]?(\d{2,5})',
        r'(?i)\b(?:port|PORT)\s*[:=]\s*[\'\"]?(\d{2,5})',
        r'(?i)localhost:(\d{2,5})',
        r'(?i)127\.0\.0\.1:(\d{2,5})',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                p = int(m.group(1))
                if 1 <= p <= 65535:
                    return p
            except (TypeError, ValueError):
                pass
    return None


def _astro_config(repo):
    f = _first_file(repo, {'astro.config.mjs', 'astro.config.js', 'astro.config.ts', 'astro.config.cjs'})
    return f, repo.read(f) if f else ''


def _node_version(repo, pkg):
    for name in ('.nvmrc', '.node-version'):
        if name in repo.file_set:
            value = repo.read(name).strip().splitlines()[0] if repo.read(name).strip() else ''
            if value:
                return value
    engines = pkg.get('engines') or {}
    return str(engines.get('node', '20'))


def analyze(repo, spec, result):
    """Second deployment-focused pass. No artifact is considered releasable until this pass is complete."""
    checks, warnings, blockers, decisions = [], [], [], []
    pkg = _package(repo)
    primary = result['summary'].get('primary_language')
    framework = result['summary'].get('framework')
    pm = result['summary'].get('package_manager')
    spec.project['files'] = list(repo.files)

    def check(code, title, status, evidence=None, detail=''):
        item = {'code': code, 'title': title, 'status': status, 'evidence': evidence or [], 'detail': detail}
        checks.append(item)
        if status == 'blocker':
            blockers.append(item)
        elif status == 'warning':
            warnings.append(item)
        return item

    if primary in {'JavaScript', 'TypeScript'} or 'package.json' in repo.file_set:
        scripts = pkg.get('scripts') or {}
        lock = LOCKFILES.get(pm)
        lock_present = bool(lock and lock in repo.file_set)
        check('NODE_MANIFEST', 'Node package manifest', 'pass' if 'package.json' in repo.file_set else 'blocker',
              ['package.json'] if 'package.json' in repo.file_set else [],
              'package.json is the source of truth for scripts and dependencies.' if 'package.json' in repo.file_set else 'package.json is required.')
        if pm != 'Unknown' and lock:
            check('LOCKFILE_MATCH', 'Package manager and lockfile', 'pass' if lock_present else 'warning',
                  [lock] if lock_present else ['package.json'],
                  f'{pm} lockfile detected.' if lock_present else f'No {lock} found; installation will use a non-frozen dependency resolution.')
        build = scripts.get('build')
        check('BUILD_SCRIPT', 'Production build command', 'pass' if build else 'blocker', ['package.json'],
              f'Using repository script: {build}' if build else 'No package.json build script was found.')
        start = scripts.get('start')
        dev = scripts.get('dev')
        check('START_SCRIPT', 'Application start command', 'pass' if start else ('warning' if dev else 'blocker'), ['package.json'],
              f'package.json start script: {start}' if start else ('No start script; dev is available as a fallback.' if dev else 'No start or dev script was found.'))
        spec.runtime['version'] = _node_version(repo, pkg)

        if framework == 'Astro':
            cfg_file, cfg = _astro_config(repo)
            deps = {**(pkg.get('dependencies') or {}), **(pkg.get('devDependencies') or {})}
            adapter = 'unknown'
            if '@astrojs/vercel' in deps or '@astrojs/vercel' in cfg:
                adapter = 'vercel'
            elif '@astrojs/node' in deps or '@astrojs/node' in cfg:
                adapter = 'node'
            elif '@astrojs/netlify' in deps or '@astrojs/netlify' in cfg:
                adapter = 'netlify'
            elif '@astrojs/cloudflare' in deps or '@astrojs/cloudflare' in cfg:
                adapter = 'cloudflare'
            output = 'server' if re.search(r"output\s*:\s*['\"]server['\"]", cfg) else ('hybrid' if re.search(r"output\s*:\s*['\"]hybrid['\"]", cfg) else 'static')
            adapter_evidence = [x for x in (cfg_file, 'package.json') if x]
            check('ASTRO_CONFIG', 'Astro configuration', 'pass' if cfg_file else 'warning', adapter_evidence,
                  f'Astro adapter={adapter}, output={output}.')

            if adapter == 'vercel' and output in {'server', 'hybrid'}:
                if not dev:
                    check('ASTRO_CONTAINER_RUNTIME', 'Container runtime compatibility', 'blocker', adapter_evidence,
                          'Vercel SSR output cannot be locally served by astro preview; a dev script is required unless the project is converted to the Node adapter.')
                else:
                    check('ASTRO_CONTAINER_RUNTIME', 'Container runtime compatibility', 'pass', adapter_evidence,
                          'Vercel SSR is preserved; Docker uses the repository dev server because the Vercel serverless adapter does not support astro preview.')
                    spec.build['runtime_strategy'] = 'dev-server-fallback'
                    spec.build['adapter'] = 'vercel-serverless'
                    spec.build['preview_supported'] = False
                    decisions.append({'code': 'ASTRO_VERCEL_DEV_RUNTIME', 'decision': 'use_dev_server', 'reason': 'Vercel serverless adapter is host-specific; use the repository dev server for a runnable local container.'})
            elif adapter == 'node' and output in {'server', 'hybrid'}:
                check('ASTRO_CONTAINER_RUNTIME', 'Node SSR runtime', 'pass', adapter_evidence,
                      'Astro Node adapter provides a Docker-compatible Node server entrypoint.')
                spec.build['runtime_strategy'] = 'node-standalone'
                spec.build['adapter'] = 'node'
                spec.build['preview_supported'] = True
                decisions.append({'code': 'ASTRO_NODE_STANDALONE', 'decision': 'node_dist_entry', 'reason': 'Node adapter supplies dist/server/entry.mjs.'})
            elif output == 'static':
                check('ASTRO_CONTAINER_RUNTIME', 'Static runtime compatibility', 'pass', adapter_evidence,
                      'Static Astro output can be served with the preview server for local validation.')
                spec.build['runtime_strategy'] = 'static'
                spec.build['adapter'] = adapter
                spec.build['preview_supported'] = True

            port = _port_from_text(cfg) or _port_from_text(scripts.get('dev', ''))
            if not port:
                readme = _first_file(repo, {'README.md', 'readme.md'})
                port = _port_from_text(repo.read(readme)) if readme else None
            port = port or 4321
            spec.network['port'] = port
            if adapter == 'vercel' and output in {'server', 'hybrid'} and dev:
                spec.processes[0]['start_command'] = f'{pm if pm not in {"Unknown", "npm"} else "npm"} run dev -- --host 0.0.0.0 --port {port}'
            decisions.append({'code': 'PORT', 'decision': port, 'reason': 'Resolved from Astro configuration, dev script, README, or Astro default 4321.'})
            check('PORT', 'Application port', 'pass', [cfg_file or 'package.json'], f'Container port resolved to {port}.')
        else:
            port = _port_from_text(repo.corpus) or spec.network.get('port') or 3000
            spec.network['port'] = port
            decisions.append({'code': 'PORT', 'decision': port, 'reason': 'Resolved from repository configuration/source signals.'})

    elif primary == 'Python':
        required = [x for x in ('requirements.txt', 'pyproject.toml', 'Pipfile') if x in repo.file_set]
        check('PYTHON_MANIFEST', 'Python dependency manifest', 'pass' if required else 'blocker', required,
              'Python dependency manifest detected.' if required else 'No supported Python dependency manifest was found.')
        if result['summary'].get('start_command') == 'Not detected':
            check('PYTHON_ENTRYPOINT', 'Python application entrypoint', 'blocker', [], 'No deterministic Python web entrypoint was identified.')

    if spec.project.get('monorepo'):
        check('MONOREPO_TARGET', 'Monorepo deployment target', 'blocker', spec.infrastructure.get('files', []),
              'Workspace/monorepo markers exist but no deployable workspace was selected; Docker generation must not guess.')

    if 'Dockerfile' in repo.file_set:
        check('EXISTING_DOCKERFILE', 'Existing Dockerfile', 'warning', ['Dockerfile'],
              'Existing Dockerfile is evidence only and is not copied blindly into the generated artifact.')

    if spec.environment.get('secret_files'):
        check('SECRET_FILES', 'Repository secret files', 'warning', spec.environment['secret_files'],
              'Secret-bearing environment files were detected and must not enter the image.')

    confidence = 100 - min(20, len(warnings) * 3) if not blockers else 0
    result['deep_analysis'] = {
        'status': 'ready' if not blockers else 'blocked',
        'confidence': confidence,
        'checks': checks,
        'warnings': warnings,
        'blockers': blockers,
        'decisions': decisions,
        'script_inventory': {k: _script(pkg, k) for k in ('build', 'start', 'dev', 'preview', 'serve') if _script(pkg, k)},
    }
    spec.project['deep_analysis_status'] = result['deep_analysis']['status']
    spec.project['deep_analysis_confidence'] = confidence
    spec.project['container_decisions'] = decisions
    return result['deep_analysis']
