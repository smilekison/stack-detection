from pathlib import Path
import json
import re


LOCKFILES = {
    'npm': 'package-lock.json',
    'pnpm': 'pnpm-lock.yaml',
    'yarn': 'yarn.lock',
    'bun': 'bun.lock',
}


def _package(repo):
    return repo.json('package.json') if 'package.json' in repo.file_set else {}


def _script(pkg, name):
    return (pkg.get('scripts') or {}).get(name)


def _first_file(repo, names):
    return next((f for f in repo.files if Path(f).name in names), None)


def _port_from_text(text):
    patterns = [
        r'(?i)(?:--port|port\s*[:=]|PORT\s*[:=]|listen\s*\(\s*[^,]+,?\s*)(?:parseInt\([^,]+,?\s*)?[\'\"]?(\d{2,5})',
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
    if engines.get('node'):
        return str(engines['node'])
    return '20'


def analyze(repo, spec, result):
    """Perform a second, deployment-focused pass before artifact generation.

    This pass intentionally does not infer a command from a framework name alone.
    It reconciles manifests, scripts, config, adapters, output mode, ports and
    repository layout, then records explicit generation gates in the IR.
    """
    checks = []
    warnings = []
    blockers = []
    decisions = []
    pkg = _package(repo)
    primary = result['summary'].get('primary_language')
    framework = result['summary'].get('framework')
    pm = result['summary'].get('package_manager')

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
        check(
            'NODE_MANIFEST', 'Node package manifest', 'pass' if 'package.json' in repo.file_set else 'blocker',
            ['package.json'] if 'package.json' in repo.file_set else [],
            'package.json is the source of truth for scripts and dependencies.' if 'package.json' in repo.file_set else 'package.json is required.'
        )
        if pm != 'Unknown' and lock:
            check('LOCKFILE_MATCH', 'Package manager and lockfile', 'pass' if lock_present else 'warning',
                  [lock] if lock_present else ['package.json'],
                  f'{pm} lockfile detected.' if lock_present else f'No {lock} found; installation will use the package manager without frozen resolution.')
        build = scripts.get('build')
        if not build:
            check('BUILD_SCRIPT', 'Production build command', 'blocker', ['package.json'], 'No package.json build script was found.')
        else:
            check('BUILD_SCRIPT', 'Production build command', 'pass', ['package.json'], f'Using repository script: {build}')
        start = scripts.get('start')
        dev = scripts.get('dev')
        preview = scripts.get('preview')
        if start:
            check('START_SCRIPT', 'Application start command', 'pass', ['package.json'], f'package.json start script: {start}')
        elif dev:
            check('START_SCRIPT', 'Application start command', 'warning', ['package.json'], 'No start script; dev script is available as a fallback only when the framework/runtime requires it.')
        else:
            check('START_SCRIPT', 'Application start command', 'blocker', ['package.json'], 'No start or dev script was found.')
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
            serverless_vercel = adapter == 'vercel' and ('serverless' in cfg or output in {'server', 'hybrid'})
            preview_supported = adapter == 'node' or output == 'static'
            adapter_evidence = [x for x in [cfg_file, 'package.json'] if x]
            check('ASTRO_CONFIG', 'Astro configuration', 'pass' if cfg_file else 'warning', adapter_evidence,
                  f'Astro adapter={adapter}, output={output}.')
            if adapter == 'vercel' and output in {'server', 'hybrid'}:
                if not dev:
                    check('ASTRO_CONTAINER_RUNTIME', 'Container runtime compatibility', 'blocker', adapter_evidence,
                          'Vercel SSR output cannot be served by a local Docker container without a Node-compatible adapter, and no dev script exists.')
                else:
                    check('ASTRO_CONTAINER_RUNTIME', 'Container runtime compatibility', 'pass', adapter_evidence,
                          'The Vercel SSR adapter targets Vercel; for a faithful local container, use the repository dev server rather than astro preview.')
                    decisions.append({'code': 'ASTRO_VERCEL_DEV_RUNTIME', 'decision': 'use_dev_server', 'reason': 'Vercel serverless adapter does not provide a local preview server; repository dev script is the verified runnable entrypoint.'})
                    spec.processes[0]['start_command'] = f'{pm if pm not in {"Unknown", "npm"} else "npm"} run dev -- --host 0.0.0.0 --port {{port}}'
                    spec.build['runtime_strategy'] = 'dev-server-fallback'
                    spec.build['adapter'] = 'vercel-serverless'
                    spec.build['preview_supported'] = preview_supported
            elif adapter == 'node' and output in {'server', 'hybrid'}:
                check('ASTRO_CONTAINER_RUNTIME', 'Node SSR runtime', 'pass', adapter_evidence,
                      'Astro Node adapter supports a standalone Node server for Docker.')
                decisions.append({'code': 'ASTRO_NODE_STANDALONE', 'decision': 'node_dist_entry', 'reason': 'Node adapter provides a Docker-compatible server entrypoint.'})
                spec.build['runtime_strategy'] = 'node-standalone'
                spec.build['adapter'] = 'node'
                spec.build['preview_supported'] = True
            elif output == 'static':
                check('ASTRO_CONTAINER_RUNTIME', 'Static runtime compatibility', 'pass', adapter_evidence,
                      'Static Astro output can be served by a static web server or Astro preview for local validation.')
                spec.build['runtime_strategy'] = 'static'
                spec.build['adapter'] = adapter
                spec.build['preview_supported'] = True

            port = _port_from_text(cfg) or _port_from_text(pkg.get('scripts', {}).get('dev', ''))
            if not port:
                readme = _first_file(repo, {'README.md', 'readme.md'})
                port = _port_from_text(repo.read(readme)) if readme else None
            if not port:
                port = 4321
            spec.network['port'] = port
            decisions.append({'code': 'PORT', 'decision': port, 'reason': 'Resolved from Astro configuration/scripts/README, otherwise Astro default 4321.'})
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

    monorepo = bool(spec.project.get('monorepo'))
    if monorepo:
        check('MONOREPO_TARGET', 'Monorepo deployment target', 'blocker', spec.infrastructure.get('files', []),
              'The repository contains workspace/monorepo markers but no selected deployable workspace. Docker generation must not guess the target package.')

    if 'Dockerfile' in repo.file_set:
        check('EXISTING_DOCKERFILE', 'Existing Dockerfile', 'warning', ['Dockerfile'],
              'An existing Dockerfile was found. It is treated as evidence, not copied blindly into the generated artifact.')

    if spec.environment.get('secret_files'):
        check('SECRET_FILES', 'Repository secret files', 'warning', spec.environment['secret_files'],
              'Secret-bearing environment files were detected. They must not be copied into the image.')

    # The generator is released only when every required decision is deterministic.
    confidence = 100
    if warnings:
        confidence -= min(20, len(warnings) * 3)
    if blockers:
        confidence = 0
    ready = not blockers
    result['deep_analysis'] = {
        'status': 'ready' if ready else 'blocked',
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
