"""Pins a real bug found analyzing bradtraversy/friendly-dev-backend (a Strapi app): its
config/server.ts declares `port: env.int('PORT', 1337)` - a real Tier 1 default a generic
`PORT[:=]\\d+` scan never matches, so the generator silently fell back to the unrelated
Node default of 3000 and generated a Dockerfile that EXPOSEd and set PORT to the wrong port
entirely."""
from core.scanner import Repository
from core.engine import Analyzer


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_strapi_style_env_int_port_default_is_detected(tmp_path):
    write(tmp_path, "package.json", '{"scripts":{"build":"strapi build","start":"npm run start"}}')
    write(tmp_path, "config/server.ts", "export default ({ env }) => ({\n  host: env('HOST', '0.0.0.0'),\n  port: env.int('PORT', 1337),\n});\n")
    write(tmp_path, "src/index.ts", "export default {};\n")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["summary"]["port"] == 1337


def test_plain_express_style_env_or_default_port_is_detected(tmp_path):
    write(tmp_path, "package.json", '{"scripts":{"build":"echo ok","start":"node server.js"}}')
    write(tmp_path, "server.js", "const express = require('express');\nconst app = express();\nconst PORT = process.env.PORT || 4000;\napp.listen(PORT);\n")
    _, _, result = Analyzer(Repository(tmp_path)).analyze()
    assert result["summary"]["port"] == 4000
