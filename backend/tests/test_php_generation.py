"""Regression coverage for the PHP/Laravel Dockerfile generation logic found and fixed by
analyzing a real `composer create-project laravel/laravel` scaffold end to end (build, run,
verified HTTP 200). A full Laravel build is too heavy for the automated docker_smoke suite,
so this pins the generated Dockerfile's structure directly instead - each assertion here
corresponds to one bug that broke a real build."""
from core.scanner import Repository
from core.engine import Analyzer
from generators.docker import dockerfile


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def laravel_fixture(tmp_path):
    write(tmp_path, "composer.json", '{"require":{"php":"^8.3","laravel/framework":"^11.0"}}')
    write(tmp_path, "composer.lock", "{}")
    write(tmp_path, "artisan", "#!/usr/bin/env php\n")
    write(tmp_path, "public/index.php", "<?php echo 'ok';")
    write(tmp_path, "storage/logs/.gitkeep", "")
    write(tmp_path, "bootstrap/cache/.gitkeep", "")
    # A Vite companion with only a build script - no start, no dev - must resolve to PHP,
    # not be mistaken for a rival Node application (or silently win over the real backend).
    write(tmp_path, "package.json", '{"scripts":{"build":"vite build"}}')
    return Repository(tmp_path)


def test_laravel_resolves_ready_with_the_php_backend(tmp_path):
    repo = laravel_fixture(tmp_path)
    spec, _, result = Analyzer(repo).analyze()
    assert result["deep_analysis"]["status"] == "ready"
    assert result["summary"]["primary_language"] == "PHP"
    assert result["summary"]["framework"] == "Laravel"


def test_generated_dockerfile_covers_every_laravel_specific_fix(tmp_path):
    repo = laravel_fixture(tmp_path)
    spec, _, _ = Analyzer(repo).analyze()
    df = dockerfile(spec)

    # Runtime version comes from composer.json's own declared constraint, not a hardcoded
    # literal - PHP's official images need MAJOR.MINOR precision, unlike Node's bare-major.
    assert "FROM php:8.3-apache" in df

    # A build-only Vite companion is folded into its own stage and its output copied into
    # the final image - Blade's @vite() needs the compiled manifest to render at all.
    assert "FROM node:20-bookworm-slim AS assets" in df
    assert "COPY --from=assets" in df and "/app/public/build ./public/build" in df

    # composer install must skip scripts (artisan isn't present in that stage yet) and
    # package:discover must be re-run once the full app is present - skipping it outright
    # breaks core service provider registration, it's not just a lost cache warm-up.
    assert "--no-scripts" in df
    assert "RUN php artisan package:discover --ansi" in df

    # storage/ and bootstrap/cache/ must be writable by the web server user, or the app
    # 500s on its very first request even when otherwise perfectly configured.
    assert "RUN chown -R www-data:www-data storage bootstrap/cache" in df

    # COPY . . must run BEFORE the deps-stage vendor copy, not after - a local dev
    # environment's own vendor/ (dev dependencies included) would otherwise silently
    # clobber the correctly `--no-dev`-installed one.
    assert df.index("COPY . .") < df.index("COPY --from=deps /app/vendor ./vendor")
