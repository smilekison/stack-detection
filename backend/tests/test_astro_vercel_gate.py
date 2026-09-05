from core.engine import Analyzer
from core.scanner import Repository


def test_astro_vercel_server_output_is_blocked_without_local_production_runtime(tmp_path):
    (tmp_path / 'package.json').write_text('''{
      "type":"module",
      "scripts":{"dev":"astro dev","start":"astro dev","build":"astro check && astro build","preview":"astro preview"},
      "dependencies":{"astro":"^4.0.4","@astrojs/vercel":"^6.1.0"}
    }''')
    (tmp_path / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{}}')
    (tmp_path / '.nvmrc').write_text('20\n')
    (tmp_path / 'astro.config.mjs').write_text("import { defineConfig } from 'astro/config';\nimport vercel from '@astrojs/vercel/serverless';\nexport default defineConfig({output:'server',adapter:vercel()});\n")
    (tmp_path / 'README.md').write_text('''## Local development\n```bash\nnpm install\nnpm run dev\n```\n''')
    (tmp_path / 'src/pages').mkdir(parents=True)
    (tmp_path / 'src/pages/index.astro').write_text('<h1>ok</h1>')

    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result['summary']['framework'] == 'Astro'
    assert result['deep_analysis']['status'] == 'blocked'
    assert any(b['code'] == 'RUNTIME' for b in result['deep_analysis']['blockers'])
    assert result['summary']['start_command'] == 'Not detected'
