"""Evidence catalog for repository technology classification.

Descriptive only: a catalog match never authorizes deployment. A deployment strategy still
requires an executable build/runtime proof and may fail closed.
"""
from pathlib import Path

# Only files capable of defining an application/build unit belong here. Lockfiles are
# deliberately excluded: a lockfile alone must never create an application target.
MANIFEST_ECOSYSTEMS={
 "package.json":"node","deno.json":"deno","deno.jsonc":"deno",
 "pyproject.toml":"python","requirements.txt":"python","requirements-dev.txt":"python","Pipfile":"python",
 "go.mod":"go","Cargo.toml":"rust","pom.xml":"jvm","build.gradle":"jvm","build.gradle.kts":"jvm",
 "settings.gradle":"jvm","settings.gradle.kts":"jvm","build.sbt":"scala","composer.json":"php","Gemfile":"ruby",
 "mix.exs":"elixir","rebar.config":"erlang","Package.swift":"swift","pubspec.yaml":"dart","stack.yaml":"haskell",
 "*.cabal":"haskell","CMakeLists.txt":"cpp","meson.build":"cpp","Makefile":"native","vcpkg.json":"cpp",
 "conanfile.txt":"cpp","conanfile.py":"cpp","*.csproj":"dotnet","*.fsproj":"fsharp","*.vbproj":"vbnet",
 "project.clj":"clojure","deps.edn":"clojure",
}
LOCKFILES={
 "package-lock.json":"npm","pnpm-lock.yaml":"pnpm","yarn.lock":"yarn","bun.lock":"bun","bun.lockb":"bun",
 "Pipfile.lock":"pipenv","poetry.lock":"poetry","uv.lock":"uv","go.sum":"go","Cargo.lock":"cargo",
 "composer.lock":"composer","Gemfile.lock":"bundler","mix.lock":"hex","Package.resolved":"swiftpm",
}
SOURCE_EXTENSIONS={
 ".js":"javascript",".jsx":"javascript",".mjs":"javascript",".cjs":"javascript",".ts":"typescript",".tsx":"typescript",
 ".py":"python",".pyi":"python",".go":"go",".rs":"rust",".java":"java",".kt":"kotlin",".kts":"kotlin",
 ".scala":"scala",".sc":"scala",".cs":"csharp",".fs":"fsharp",".fsx":"fsharp",".vb":"vbnet",".php":"php",
 ".rb":"ruby",".rake":"ruby",".ex":"elixir",".exs":"elixir",".erl":"erlang",".hrl":"erlang",".swift":"swift",
 ".dart":"dart",".hs":"haskell",".lhs":"haskell",".clj":"clojure",".cljs":"clojure",".cljc":"clojure",".c":"c",
 ".h":"c",".cc":"cpp",".cpp":"cpp",".cxx":"cpp",".hpp":"cpp",".m":"objective-c",".mm":"objective-cpp",
 ".lua":"lua",".pl":"perl",".pm":"perl",".r":"r",".jl":"julia",".zig":"zig",".nim":"nim",".cr":"crystal",
 ".v":"vlang",".sol":"solidity",".asm":"assembly",".s":"assembly",
}
NODE_FRAMEWORKS={
 "next":"Next.js","nuxt":"Nuxt","@nestjs/core":"NestJS","express":"Express","fastify":"Fastify","koa":"Koa","hono":"Hono",
 "@remix-run/node":"Remix","@sveltejs/kit":"SvelteKit","@angular/core":"Angular","react":"React","react-dom":"React",
 "vue":"Vue","svelte":"Svelte","astro":"Astro","gatsby":"Gatsby","@docusaurus/core":"Docusaurus","vite":"Vite",
 "webpack":"Webpack","parcel":"Parcel","@11ty/eleventy":"Eleventy","solid-js":"SolidJS","@solidjs/start":"SolidStart",
 "@builder.io/qwik":"Qwik","preact":"Preact","ember-source":"Ember","meteor":"Meteor","strapi":"Strapi","@directus/sdk":"Directus",
}
PY_FRAMEWORKS={"django":"Django","fastapi":"FastAPI","flask":"Flask","litestar":"Litestar","sanic":"Sanic","tornado":"Tornado","starlette":"Starlette","quart":"Quart","falcon":"Falcon","pyramid":"Pyramid","bottle":"Bottle","aiohttp":"aiohttp","streamlit":"Streamlit","gradio":"Gradio","celery":"Celery"}
GO_FRAMEWORKS={"github.com/gin-gonic/gin":"Gin","github.com/labstack/echo":"Echo","github.com/gofiber/fiber":"Fiber","github.com/go-chi/chi":"Chi","github.com/gorilla/mux":"Gorilla Mux","github.com/beego/beego":"Beego"}
RUST_FRAMEWORKS={"axum":"Axum","actix-web":"Actix Web","rocket":"Rocket","warp":"Warp","poem":"Poem"}
JVM_FRAMEWORKS={"spring-boot":"Spring Boot","quarkus":"Quarkus","micronaut":"Micronaut","io.ktor":"Ktor","playframework":"Play Framework"}
DOTNET_FRAMEWORKS={"Microsoft.AspNetCore":"ASP.NET Core","Microsoft.NET.Sdk.Web":"ASP.NET Core"}
PHP_FRAMEWORKS={"laravel":"Laravel","symfony":"Symfony","wordpress":"WordPress","slim/slim":"Slim","cakephp":"CakePHP"}
RUBY_FRAMEWORKS={"rails":"Rails","sinatra":"Sinatra","rack":"Rack","hanami":"Hanami"}
ELIXIR_FRAMEWORKS={"phoenix":"Phoenix","plug":"Plug","bandit":"Bandit"}
STATIC_MARKERS={"hugo":("hugo.toml","hugo.yaml","hugo.json"),"jekyll":("_config.yml","_config.yaml"),"mkdocs":("mkdocs.yml",),"docusaurus":("docusaurus.config.js","docusaurus.config.ts"),"eleventy":(".eleventy.js","eleventy.config.js","eleventy.config.cjs")}
FRAMEWORK_DEPENDENCY_KEYS={**NODE_FRAMEWORKS,**PY_FRAMEWORKS,**GO_FRAMEWORKS,**RUST_FRAMEWORKS,**JVM_FRAMEWORKS,**DOTNET_FRAMEWORKS,**PHP_FRAMEWORKS,**RUBY_FRAMEWORKS,**ELIXIR_FRAMEWORKS}

def glob_manifest_matches(path):
    name=Path(path).name
    return any((pattern.startswith("*") and name.endswith(pattern[1:])) or pattern==name for pattern in MANIFEST_ECOSYSTEMS)

def ecosystem_for_manifest(path):
    name=Path(path).name
    for pattern,eco in MANIFEST_ECOSYSTEMS.items():
        if (pattern.startswith("*") and name.endswith(pattern[1:])) or pattern==name: return eco
    return None
