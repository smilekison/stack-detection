from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile


def astro_fixture(tmp_path):
    (tmp_path / 'package.json').write_text('''{
      "scripts": {"dev": "astro dev", "build": "astro check && astro build", "preview": "astro preview", "start": "astro dev"},
      "dependencies": {"astro": "^4.0.4", "@astrojs/vercel": "^6.1.0"}
    }''')
    (tmp_path / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{}}')
    (tmp_path / 'astro.config.mjs').write_text('''import { defineConfig } from 'astro/config';\nimport tailwind from '@astrojs/tailwind';\nimport vercel from '@astrojs/vercel/serverless';\nexport default defineConfig({ integrations:[tailwind()], output:'server', adapter:vercel() });''')
    (tmp_path / 'README.md').write_text('Run the dev server at http://localhost:4321')
    (tmp_path / 'src/pages/index.astro').parent.mkdir(parents=True)
    (tmp_path / 'src/pages/index.astro').write_text('<h1>hello</h1>')
    return Repository(tmp_path)


def test_astro_deep_analysis_reconciles_vercel_adapter_and_runtime(tmp_path):
    repo = astro_fixture(tmp_path)
    spec, _, result = Analyzer(repo).analyze()
    deep = result['deep_analysis']
    assert deep['status'] == 'ready'
    assert spec.build['runtime_strategy'] == 'dev-server-fallback'
    assert spec.network['port'] == 4321
    assert 'npm run dev -- --host 0.0.0.0 --port 4321' in spec.processes[0]['start_command']

    generated = dockerfile(spec)
    assert 'COPY package.json package-lock.json ./' in generated
    assert 'RUN npm ci' in generated
    assert 'RUN npm run build' in generated
    assert 'EXPOSE 4321' in generated
    assert 'npm run dev -- --host 0.0.0.0 --port 4321' in generated
    assert 'npm run preview' not in generated
    assert 'pnpm-lock.yaml*' not in generated
    assert 'yarn.lock*' not in generated
    assert 'bun.lock*' not in generated
    assert 'USER 10001' in generated
