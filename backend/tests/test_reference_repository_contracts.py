from core.engine import Analyzer
from core.scanner import Repository
from generators.docker import dockerfile


def _write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_astro_vercel_server_output_blocks_even_with_runtime_pin(tmp_path):
    _write(tmp_path, 'package.json', '''{
      "type":"module",
      "scripts":{"dev":"astro dev","start":"astro dev","build":"astro check && astro build","preview":"astro preview"},
      "dependencies":{"astro":"^4.0.4","@astrojs/vercel":"^6.1.0"}
    }''')
    _write(tmp_path, 'package-lock.json', '{"lockfileVersion":3,"packages":{}}')
    _write(tmp_path, '.nvmrc', '20\n')
    _write(tmp_path, 'astro.config.mjs', "import { defineConfig } from 'astro/config';\nimport vercel from '@astrojs/vercel/serverless';\nexport default defineConfig({ output:'server', adapter:vercel() });\n")
    _write(tmp_path, 'README.md', '# Usage\n\n```bash\nnpm run dev\n```\n')
    _write(tmp_path, 'src/pages/index.astro', '<h1>ok</h1>')

    _, spec, result = _analyze(tmp_path)
    assert result['summary']['framework'] == 'Astro'
    assert result['deep_analysis']['status'] == 'blocked'
    assert any(x['code'] == 'RUNTIME' for x in result['deep_analysis']['blockers'])
    assert spec.build.get('runtime_strategy') is None


def test_stack_detection_layout_generates_from_backend_boundary(tmp_path):
    _write(tmp_path, 'backend/requirements.txt', 'fastapi==0.116.1\nuvicorn[standard]==0.35.0\n')
    _write(tmp_path, 'backend/Dockerfile', 'FROM python:3.12-slim\n')
    _write(tmp_path, 'backend/main.py', "from fastapi import FastAPI\nfrom fastapi.responses import FileResponse\nFRONTEND='frontend'\napp=FastAPI()\n@app.get('/health')\ndef health(): return {'status':'ok'}\n@app.get('/')\ndef home(): return FileResponse(FRONTEND+'/index.html')\n")
    _write(tmp_path, 'frontend/package.json', '{"private":true,"name":"dashboard","version":"1.0.0"}')
    _write(tmp_path, 'frontend/index.html', '<h1>dashboard</h1>')

    _, spec, result = _analyze(tmp_path)
    assert result['repository_model']['selected_unit']['root'] == 'backend'
    assert result['summary']['framework'] == 'FastAPI'
    assert result['deep_analysis']['status'] == 'ready'
    assert spec.runtime['version'] == '3.12-slim'
    assert spec.build['dependency_manifest'] == 'backend/requirements.txt'
    image = dockerfile(spec)
    assert 'FROM python:3.12-slim' in image
    assert 'pip install --no-cache-dir -r backend/requirements.txt' in image
    assert 'uvicorn backend.main:app' in image
    assert 'USER 10001' in image


def _analyze(root):
    spec, _, result = Analyzer(Repository(root)).analyze()
    return root, spec, result
